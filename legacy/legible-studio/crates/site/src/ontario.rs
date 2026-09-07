//! Ontario LiDAR DEM tile index + downloader.
//!
//! Ontario distributes its 1-metre LiDAR-derived DEMs as **1 km square
//! tiles** indexed by UTM coordinates. Each tile's filename encodes its
//! UTM origin:
//!
//! ```text
//! 1km{zone:2}{easting_km:3}{northing_m:7}[suffix].tif
//! ```
//!
//! e.g. `1km17542 5123030LLAKENIPISSING_DSM.tif` — UTM zone 17, easting
//! 542 000 m, northing 5 123 030 m. (The actual filename strips the space.)
//!
//! Tiles are grouped into named **packages** for download
//! (one package = one ZIP archive on the Ontario data server). The
//! authoritative tile→package mapping lives in
//! `OntarioDSM_LidarDerived_TileIndex.zip`; this module leaves that lookup
//! as a trait (see [`PackageResolver`]) so a static table, a parsed index
//! zip, or a remote service can plug in equally.
//!
//! What's pure here, testable without the network:
//! - Tile-name formatting + parsing from a UTM coord.
//! - 1km tile enumeration over a UTM bounding box.
//! - WGS84 bbox → UTM 17 N → tile list.
//! - `LocalTileIndex` — index of already-downloaded `1km*.tif` files in a
//!   directory.
//!
//! The HTTP fetch + ZIP extraction belongs to v2 of this module; today's
//! flow is "download packages with the Python tool or by hand, point us at
//! the directory".

use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};

use crate::coord::{LatLon, utm17_from_wgs84};

/// Tile side length in metres. Ontario tiles are always 1 km × 1 km.
pub const TILE_SIDE_M: u32 = 1000;

/// One 1km Ontario tile, indexed by its UTM origin.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct OntarioTile {
    pub zone: u8,
    /// SW corner easting in metres (always a multiple of 1000).
    pub easting_m: u32,
    /// SW corner northing in metres (always a multiple of 1000).
    pub northing_m: u32,
}

impl OntarioTile {
    /// The tile prefix used in filenames: `1km{zone:02}{ekm:03}{nm:07}`.
    /// Ontario filenames append a package/data-type suffix; the prefix is
    /// what we match against on disk.
    #[must_use]
    pub fn name_prefix(&self) -> String {
        let ekm = self.easting_m / 1000;
        format!("1km{:02}{:03}{:07}", self.zone, ekm, self.northing_m)
    }

    /// UTM bbox `(min_e, min_n, max_e, max_n)` covered by this tile.
    #[must_use]
    pub fn utm_bounds(&self) -> (u32, u32, u32, u32) {
        (
            self.easting_m,
            self.northing_m,
            self.easting_m + TILE_SIDE_M,
            self.northing_m + TILE_SIDE_M,
        )
    }
}

/// Parse a tile name prefix back into an `OntarioTile`. Accepts either
/// the bare prefix or a full filename — anything after the prefix is
/// ignored. Returns `None` on shape or numeric parse failures.
#[must_use]
pub fn parse_tile_prefix(name: &str) -> Option<OntarioTile> {
    let stem = Path::new(name).file_name()?.to_str()?;
    if !stem.starts_with("1km") || stem.len() < 15 {
        return None;
    }
    let zone: u8 = stem.get(3..5)?.parse().ok()?;
    let ekm: u32 = stem.get(5..8)?.parse().ok()?;
    let nm: u32 = stem.get(8..15)?.parse().ok()?;
    Some(OntarioTile { zone, easting_m: ekm * 1000, northing_m: nm })
}

/// All tiles whose 1km square intersects the given UTM bbox. Zone is
/// constant across the bbox.
#[must_use]
pub fn tiles_for_utm_bbox(
    zone: u8,
    min_e: u32, min_n: u32, max_e: u32, max_n: u32,
) -> Vec<OntarioTile> {
    let e0 = (min_e / TILE_SIDE_M) * TILE_SIDE_M;
    let n0 = (min_n / TILE_SIDE_M) * TILE_SIDE_M;
    let mut out = Vec::new();
    let mut n = n0;
    while n < max_n {
        let mut e = e0;
        while e < max_e {
            out.push(OntarioTile { zone, easting_m: e, northing_m: n });
            e += TILE_SIDE_M;
        }
        n += TILE_SIDE_M;
    }
    out
}

/// All tiles intersecting a WGS84 bbox `(nw, se)` — projects through UTM
/// Zone 17 N, so this is Ontario-only. Out-of-zone callers see distorted
/// (but still well-formed) tile lists.
#[must_use]
#[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)]
pub fn tiles_for_wgs84_bbox(nw: LatLon, se: LatLon) -> Vec<OntarioTile> {
    // Project all four corners — UTM rectangles aren't aligned with
    // lat/lon rectangles, so the safest bbox is the convex hull of the
    // projected corners.
    let ne = LatLon { lat_deg: nw.lat_deg, lon_deg: se.lon_deg };
    let sw = LatLon { lat_deg: se.lat_deg, lon_deg: nw.lon_deg };
    let pts = [
        utm17_from_wgs84(nw),
        utm17_from_wgs84(ne),
        utm17_from_wgs84(se),
        utm17_from_wgs84(sw),
    ];
    let min_e = pts.iter().map(|p| p.easting_m).fold(f64::INFINITY, f64::min);
    let max_e = pts.iter().map(|p| p.easting_m).fold(f64::NEG_INFINITY, f64::max);
    let min_n = pts.iter().map(|p| p.northing_m).fold(f64::INFINITY, f64::min);
    let max_n = pts.iter().map(|p| p.northing_m).fold(f64::NEG_INFINITY, f64::max);
    if !min_e.is_finite() || min_e < 0.0 || min_n < 0.0 {
        return Vec::new();
    }
    tiles_for_utm_bbox(17, min_e as u32, min_n as u32, max_e.ceil() as u32, max_n.ceil() as u32)
}

/// `(have, missing)` pair from [`LocalTileIndex::classify`] — paths for
/// tiles already on disk and names for those that still need downloading.
pub type ClassifiedTiles = (Vec<PathBuf>, Vec<OntarioTile>);

/// Tiles already on disk, indexed by name prefix. Built once per directory
/// scan; cheap to query thereafter.
#[derive(Debug, Default)]
pub struct LocalTileIndex {
    by_prefix: HashMap<String, PathBuf>,
}

impl LocalTileIndex {
    /// Scan `dir` recursively for files whose name starts with the Ontario
    /// `1km` prefix and ends in `.tif`. Multiple files matching the same
    /// prefix (e.g. DSM + DTM) are deduped: the first one wins — pass the
    /// canonical DTM directory if you want depth surfaces specifically.
    pub fn scan(dir: &Path) -> std::io::Result<Self> {
        let mut by_prefix: HashMap<String, PathBuf> = HashMap::new();
        scan_dir(dir, &mut by_prefix)?;
        Ok(Self { by_prefix })
    }

    /// Number of tiles indexed.
    #[must_use]
    pub fn len(&self) -> usize {
        self.by_prefix.len()
    }

    /// True if no tiles were found.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.by_prefix.is_empty()
    }

    /// Look up the local path for an Ontario tile, if it's been scanned.
    #[must_use]
    pub fn path_for(&self, tile: OntarioTile) -> Option<&Path> {
        self.by_prefix.get(&tile.name_prefix()).map(PathBuf::as_path)
    }

    /// All requested tiles split into (have, missing): paths for tiles we
    /// have on disk, names for those we don't. Useful for "download
    /// what's missing" planners.
    #[must_use]
    pub fn classify(&self, wanted: &[OntarioTile]) -> ClassifiedTiles {
        let mut have = Vec::new();
        let mut miss = Vec::new();
        for t in wanted {
            match self.path_for(*t) {
                Some(p) => have.push(p.to_path_buf()),
                None => miss.push(*t),
            }
        }
        (have, miss)
    }
}

fn scan_dir(dir: &Path, out: &mut HashMap<String, PathBuf>) -> std::io::Result<()> {
    if !dir.is_dir() {
        return Ok(());
    }
    for entry in fs::read_dir(dir)? {
        let entry = entry?;
        let path = entry.path();
        let ft = entry.file_type()?;
        if ft.is_dir() {
            scan_dir(&path, out)?;
            continue;
        }
        if !ft.is_file() {
            continue;
        }
        let Some(name) = path.file_name().and_then(|s| s.to_str()) else { continue; };
        let ext_ok = path
            .extension()
            .and_then(|e| e.to_str())
            .is_some_and(|e| e.eq_ignore_ascii_case("tif") || e.eq_ignore_ascii_case("tiff"));
        if !ext_ok {
            continue;
        }
        if let Some(tile) = parse_tile_prefix(name) {
            out.entry(tile.name_prefix()).or_insert_with(|| path.clone());
        }
    }
    Ok(())
}

/// Resolves a tile name to a remote URL. Implementations may consult a
/// static table, the Ontario index zip, or a custom map. The default
/// [`StaticPackageResolver`] covers the regions known to the Python tool.
pub trait PackageResolver {
    /// Return the package URL for a tile (the multi-tile ZIP archive that
    /// contains it), or `None` if no mapping is known.
    fn package_url_for(&self, tile: OntarioTile) -> Option<String>;
}

/// Hardcoded region → package-prefix table, lifted from the Python
/// downloader. This is incomplete (not every Ontario region is here) but
/// covers the major residential markets (Sudbury, GTA, Ottawa,
/// Peterborough, Thunder Bay). A future increment can replace this with
/// the parsed `OntarioDSM_LidarDerived_TileIndex.zip` lookup.
#[derive(Debug, Default)]
pub struct StaticPackageResolver;

/// Known package regions: name + WGS84 bbox `(lat_min, lat_max, lon_min,
/// lon_max)`. Mirrors `KNOWN_PACKAGES` in
/// `ArchEngine_CAD/tools/lidar/downloader.py` so the Rust port covers the
/// same out-of-the-box areas.
/// One `KNOWN_REGIONS` row: `(name, (lat_min, lat_max, lon_min, lon_max))`.
pub type KnownRegion = (&'static str, (f64, f64, f64, f64));

pub const KNOWN_REGIONS: &[KnownRegion] = &[
    ("LakeNipissing", (46.0, 46.5, -80.8, -79.8)),
    ("Sudbury", (46.3, 46.7, -81.2, -80.6)),
    ("GTA-Peel", (43.4, 44.0, -80.0, -79.2)),
    ("GTA-York", (43.7, 44.3, -79.8, -79.2)),
    ("Ottawa", (45.2, 45.6, -76.0, -75.4)),
    ("Peterborough", (44.0, 44.6, -78.6, -77.8)),
];

/// Base URL of the Ontario LiDAR package download server.
pub const PACKAGE_BASE_URL: &str =
    "https://ws.gisetl.lrc.gov.on.ca/fmedatadownload/Packages/";

/// Region whose WGS84 bbox contains `p`, or `None` if no known region
/// covers it. Used as a coarse "which package family covers this lot"
/// hint.
#[must_use]
pub fn region_for(p: LatLon) -> Option<&'static str> {
    for &(name, (lat_min, lat_max, lon_min, lon_max)) in KNOWN_REGIONS {
        if p.lat_deg >= lat_min
            && p.lat_deg <= lat_max
            && p.lon_deg >= lon_min
            && p.lon_deg <= lon_max
        {
            return Some(name);
        }
    }
    None
}

impl PackageResolver for StaticPackageResolver {
    fn package_url_for(&self, tile: OntarioTile) -> Option<String> {
        // Map the tile to a region via its UTM 17 centre. Tiles outside
        // any known region return None — caller must supply its own
        // resolver (e.g. parse the index zip).
        let centre_e = f64::from(tile.easting_m) + f64::from(TILE_SIDE_M) / 2.0;
        let centre_n = f64::from(tile.northing_m) + f64::from(TILE_SIDE_M) / 2.0;
        let ll = crate::wgs84_from_utm17(crate::UtmCoord {
            easting_m: centre_e,
            northing_m: centre_n,
            zone: tile.zone,
            northern_hemisphere: true,
        });
        let region = region_for(ll)?;
        // Without the full index zip we can't pick a specific package
        // number; return the region's listing URL so a caller (or a v2
        // resolver) can pick the right one. The user typically downloads
        // the whole region anyway.
        Some(format!("{PACKAGE_BASE_URL}{region}/"))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    #[test]
    fn tile_name_round_trips() {
        // 1km + zone(2) + ekm(3) + northing_m(7) = 15-char prefix.
        let t = OntarioTile { zone: 17, easting_m: 542_000, northing_m: 5_123_030 };
        let name = t.name_prefix();
        assert_eq!(name, "1km175425123030");
        let back = parse_tile_prefix(&format!("{name}LLAKENIPISSING_DSM.tif")).unwrap();
        assert_eq!(back, t);
    }

    #[test]
    fn tile_name_matches_python_format_from_geotiff_docs() {
        // From ArchEngine_CAD/tools/lidar/geotiff.py docstring:
        //   1km175420512303030..._DSM.tif -> zone 17, easting 542000, northing 5123030
        // The prefix is 1km + 17 + 542 + 5123030 = "1km175425123030" — 15 chars.
        // Our format matches.
        let parsed = parse_tile_prefix("1km175425123030LLAKENIPISSING_DSM.tif").unwrap();
        assert_eq!(parsed.zone, 17);
        assert_eq!(parsed.easting_m, 542_000);
        assert_eq!(parsed.northing_m, 5_123_030);
    }

    #[test]
    fn tiles_cover_a_small_utm_bbox() {
        // A 2.5km × 1.5km bbox starting at (500250, 5_000_500) should
        // hit 3 columns × 2 rows = 6 tiles.
        let ts = tiles_for_utm_bbox(17, 500_250, 5_000_500, 502_750, 5_002_000);
        assert_eq!(ts.len(), 6, "got {ts:#?}");
    }

    #[test]
    fn wgs84_bbox_around_sudbury_yields_at_least_one_tile() {
        let nw = LatLon { lat_deg: 46.4920, lon_deg: -80.9950 };
        let se = LatLon { lat_deg: 46.4910, lon_deg: -80.9930 };
        let tiles = tiles_for_wgs84_bbox(nw, se);
        assert!(!tiles.is_empty(), "no tiles for Sudbury bbox");
        for t in &tiles {
            assert_eq!(t.zone, 17);
            // The bbox is north of the equator and well inside the zone.
            assert!(t.northing_m > 5_000_000);
        }
    }

    #[test]
    fn local_index_finds_named_tiles_in_a_directory() {
        let dir = std::env::temp_dir().join("ls-site-ontario-test");
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        // Two real Ontario-shaped filenames; one bogus.
        let real_a = "1km175425123030LLAKENIPISSING_DSM.tif";
        let real_b = "1km175435123030LLAKENIPISSING_DSM.tif";
        let bogus = "totally-unrelated.tif";
        for n in [real_a, real_b, bogus] {
            fs::write(dir.join(n), b"fake").unwrap();
        }
        let idx = LocalTileIndex::scan(&dir).unwrap();
        assert_eq!(idx.len(), 2);
        let t = parse_tile_prefix(real_a).unwrap();
        assert!(idx.path_for(t).is_some());
    }

    #[test]
    fn classify_splits_wanted_into_have_and_miss() {
        let dir = std::env::temp_dir().join("ls-site-ontario-test-classify");
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        fs::write(dir.join("1km175425000000ABC_DSM.tif"), b"fake").unwrap();
        let idx = LocalTileIndex::scan(&dir).unwrap();
        let wanted = vec![
            OntarioTile { zone: 17, easting_m: 542_000, northing_m: 5_000_000 },
            OntarioTile { zone: 17, easting_m: 543_000, northing_m: 5_000_000 },
        ];
        let (have, miss) = idx.classify(&wanted);
        assert_eq!(have.len(), 1);
        assert_eq!(miss.len(), 1);
        assert_eq!(miss[0].easting_m, 543_000);
    }

    #[test]
    fn region_for_sudbury_picks_sudbury() {
        let r = region_for(LatLon { lat_deg: 46.4917, lon_deg: -80.9930 });
        assert_eq!(r, Some("Sudbury"));
        // Outside any known region returns None.
        let r = region_for(LatLon { lat_deg: 0.0, lon_deg: 0.0 });
        assert_eq!(r, None);
    }

    #[test]
    fn static_resolver_gives_a_package_url_for_sudbury_tile() {
        // A tile inside the Sudbury bounding box.
        let sudbury = utm17_from_wgs84(LatLon { lat_deg: 46.4917, lon_deg: -80.9930 });
        let tile = OntarioTile {
            zone: 17,
            #[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)]
            easting_m: ((sudbury.easting_m as u32) / TILE_SIDE_M) * TILE_SIDE_M,
            #[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)]
            northing_m: ((sudbury.northing_m as u32) / TILE_SIDE_M) * TILE_SIDE_M,
        };
        let url = StaticPackageResolver.package_url_for(tile).expect("resolver");
        assert!(url.starts_with(PACKAGE_BASE_URL));
        assert!(url.contains("Sudbury"));
    }
}
