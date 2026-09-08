//! Ontario LiDAR package downloader — Rust port of
//! `ArchEngine_CAD/tools/lidar/downloader.py`.
//!
//! Pulls DEM packages from Ontario's open-data download server, extracts
//! the `.tif` tiles into a local directory, and exposes a `LocalTileIndex`-
//! ready directory layout. Together with [`crate::mesh::stitch`] this
//! removes the last Python dependency from the site stack — the full
//! sketch-to-permit-set pipeline now runs on any platform that has a
//! Rust toolchain (Semantic OS included).
//!
//! ## Behaviour change from the Python port
//!
//! The Python `download_for_location` stops after the **first** package
//! whose URL responds `200 OK`, even if the user's parcel actually sits
//! in another package number. This Rust port downloads **every** existing
//! package in the matching regions — full coverage. That's more bytes on
//! first run but eliminates "missing tile" surprises and matches the
//! `legible-stitch` contract (any unmatched samples are reported).

use std::fs;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::time::Duration;

use crate::coord::LatLon;

/// Default tile-package download server.
pub const PACKAGE_BASE_URL: &str =
    "https://ws.gisetl.lrc.gov.on.ca/fmedatadownload/Packages/";

/// User-agent string sent on every request. Matches the OSM-fetcher
/// convention; substitute a real contact in production deploys via
/// [`LidarDownloader::with_user_agent`].
pub const DEFAULT_USER_AGENT: &str =
    "LegibleStudios/0.1 (https://github.com/jerroy/LegibleStudios)";

/// DEM data type a package provides.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum PackageDataType {
    /// Digital Surface Model — bare earth + buildings + trees. The
    /// silhouette-style elevation; what street-level visualisation wants.
    Dsm,
    /// Digital Terrain Model — bare-earth surface. What grading + contour
    /// generation wants. Default for the stitcher.
    Dtm,
}

impl PackageDataType {
    /// Three-letter URL token Ontario uses (`"DSM"` / `"DTM"`).
    #[must_use]
    pub fn as_str(&self) -> &'static str {
        match self {
            PackageDataType::Dsm => "DSM",
            PackageDataType::Dtm => "DTM",
        }
    }
}

/// One downloadable Ontario package — `{region}-{type}-{number}.zip`.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct PackageInfo {
    /// Region name (e.g. `"Sudbury"`).
    pub name: String,
    /// Two-digit package number (e.g. `"05"`).
    pub number: String,
    pub data_type: PackageDataType,
}

impl PackageInfo {
    /// Full archive name: `"Sudbury-DTM-05"`.
    #[must_use]
    pub fn full_name(&self) -> String {
        format!("{}-{}-{}", self.name, self.data_type.as_str(), self.number)
    }

    /// ZIP filename: `"Sudbury-DTM-05.zip"`.
    #[must_use]
    pub fn filename(&self) -> String {
        format!("{}.zip", self.full_name())
    }

    /// Full download URL (under [`PACKAGE_BASE_URL`]).
    #[must_use]
    pub fn url(&self) -> String {
        format!("{PACKAGE_BASE_URL}{}", self.filename())
    }
}

/// Known-region package numbers, mirroring
/// `ArchEngine_CAD/tools/lidar/downloader.py:KNOWN_PACKAGES`. Each row is
/// `(region, [package_numbers])`. The region's bbox lives in
/// [`crate::ontario::KNOWN_REGIONS`]; this table layers on the
/// enumerable package numbers.
pub const KNOWN_PACKAGES: &[(&str, &[&str])] = &[
    ("LakeNipissing", &["01", "02", "03", "04", "05", "06", "07", "08", "09", "10"]),
    ("Sudbury",       &["01", "02", "03", "04", "05", "06", "07", "08", "09", "10"]),
    ("GTA-Peel",      &["01", "02", "03", "04", "05"]),
    ("GTA-York",      &["01", "02", "03", "04", "05"]),
    ("Ottawa",        &["01", "02", "03", "04", "05", "06", "07", "08"]),
    ("Peterborough",  &["01", "02", "03", "04", "05", "06", "07", "08"]),
    ("ThunderBay",    &["01", "02", "03", "04", "05"]),
];

/// Known package numbers for `region`, or empty slice if unknown.
#[must_use]
pub fn package_numbers_for(region: &str) -> &'static [&'static str] {
    KNOWN_PACKAGES
        .iter()
        .find(|(name, _)| *name == region)
        .map_or(&[] as &[&str], |(_, nums)| *nums)
}

/// Errors the downloader can produce.
#[derive(Debug, thiserror::Error)]
pub enum DownloadError {
    #[error("I/O error: {0}")]
    Io(#[from] std::io::Error),
    #[error("HTTP error: {0}")]
    Http(#[from] reqwest::Error),
    #[error("server returned status {0} for {1}")]
    BadStatus(u16, String),
    #[error("ZIP extraction error: {0}")]
    Zip(#[from] zip::result::ZipError),
}

/// Pull Ontario LiDAR packages over HTTPS and extract their `.tif` tiles.
#[derive(Debug)]
pub struct LidarDownloader {
    output_dir: PathBuf,
    client: reqwest::blocking::Client,
}

impl LidarDownloader {
    /// New downloader writing extracted packages under `output_dir`. The
    /// directory is created if it doesn't exist.
    pub fn new(output_dir: impl Into<PathBuf>) -> Result<Self, DownloadError> {
        let output_dir = output_dir.into();
        fs::create_dir_all(&output_dir)?;
        let client = reqwest::blocking::Client::builder()
            .user_agent(DEFAULT_USER_AGENT)
            // Packages can be hundreds of MB; raise the read timeout from
            // the OSM fetcher's 15 s default.
            .timeout(Duration::from_secs(600))
            .build()?;
        Ok(Self { output_dir, client })
    }

    /// Override the User-Agent string (replace the default e-mail/repo
    /// contact in production deploys).
    #[must_use]
    pub fn with_user_agent(mut self, ua: &str) -> Self {
        if let Ok(c) = reqwest::blocking::Client::builder()
            .user_agent(ua)
            .timeout(Duration::from_secs(600))
            .build()
        {
            self.client = c;
        }
        self
    }

    /// Output directory packages get extracted under (one subdir per
    /// [`PackageInfo::full_name`]).
    #[must_use]
    pub fn output_dir(&self) -> &Path {
        &self.output_dir
    }

    /// Region names whose WGS84 bbox contains `p` (delegates to
    /// [`crate::ontario::region_for`] but returns ALL matches, not just
    /// the first).
    #[must_use]
    pub fn find_regions(p: LatLon) -> Vec<&'static str> {
        crate::ontario::KNOWN_REGIONS
            .iter()
            .filter(|(_, (lat_min, lat_max, lon_min, lon_max))| {
                p.lat_deg >= *lat_min
                    && p.lat_deg <= *lat_max
                    && p.lon_deg >= *lon_min
                    && p.lon_deg <= *lon_max
            })
            .map(|(n, _)| *n)
            .collect()
    }

    /// Every (region, number, type) combination Ontario knows about for
    /// `p`. The list isn't filtered to packages that actually exist on
    /// the server — use [`Self::check_exists`] or just kick off
    /// [`Self::download`] (which 404-tolerates).
    #[must_use]
    pub fn packages_for(p: LatLon, types: &[PackageDataType]) -> Vec<PackageInfo> {
        let mut out = Vec::new();
        for region in Self::find_regions(p) {
            for &num in package_numbers_for(region) {
                for &t in types {
                    out.push(PackageInfo {
                        name: region.to_string(),
                        number: num.to_string(),
                        data_type: t,
                    });
                }
            }
        }
        out
    }

    /// HEAD request; `Ok(true)` if the server responds 200.
    pub fn check_exists(&self, pkg: &PackageInfo) -> Result<bool, DownloadError> {
        let resp = self.client.head(pkg.url()).send()?;
        Ok(resp.status().is_success())
    }

    /// Where this package's extracted contents land.
    #[must_use]
    pub fn package_dir(&self, pkg: &PackageInfo) -> PathBuf {
        self.output_dir.join(pkg.full_name())
    }

    /// True when the package's extraction directory contains at least one
    /// `.tif` file (i.e. a previous run already pulled it).
    #[must_use]
    pub fn already_extracted(&self, pkg: &PackageInfo) -> bool {
        let dir = self.package_dir(pkg);
        let Ok(rd) = fs::read_dir(&dir) else { return false; };
        rd.flatten().any(|e| {
            e.path().extension().and_then(|s| s.to_str())
                .is_some_and(|e| e.eq_ignore_ascii_case("tif") || e.eq_ignore_ascii_case("tiff"))
        })
    }

    /// Download + extract one package. Idempotent: re-runs short-circuit
    /// when the package directory already holds `.tif` files. 404s return
    /// `Ok(None)` (the package number doesn't exist for that region).
    /// `on_progress(bytes_done, bytes_total)` fires every chunk;
    /// `bytes_total` is `0` when the server omits `content-length`.
    pub fn download(
        &self,
        pkg: &PackageInfo,
        mut on_progress: impl FnMut(u64, u64),
    ) -> Result<Option<PathBuf>, DownloadError> {
        let extract_dir = self.package_dir(pkg);
        if self.already_extracted(pkg) {
            return Ok(Some(extract_dir));
        }
        let zip_path = self.output_dir.join(pkg.filename());
        let mut resp = self.client.get(pkg.url()).send()?;
        if resp.status().as_u16() == 404 {
            return Ok(None);
        }
        if !resp.status().is_success() {
            return Err(DownloadError::BadStatus(resp.status().as_u16(), pkg.full_name()));
        }
        let total = resp.content_length().unwrap_or(0);
        // Stream the body to a temp file, then atomic-rename to the final
        // ZIP path so a partial download never gets seen as "complete".
        let tmp_path = zip_path.with_extension("zip.tmp");
        {
            let mut tmp = fs::File::create(&tmp_path)?;
            // Buffer is heap-allocated so we don't put 64 KB on the stack.
            let mut buf = vec![0_u8; 64 * 1024];
            let mut done: u64 = 0;
            loop {
                let n = resp.read(&mut buf)?;
                if n == 0 {
                    break;
                }
                tmp.write_all(&buf[..n])?;
                done += n as u64;
                on_progress(done, total);
            }
            tmp.flush()?;
        }
        fs::rename(&tmp_path, &zip_path)?;
        // Extract .tif files only — Ontario packages also ship metadata
        // PDFs, .xml, etc.; the stitcher only needs the rasters.
        fs::create_dir_all(&extract_dir)?;
        let file = fs::File::open(&zip_path)?;
        let mut archive = zip::ZipArchive::new(file)?;
        for i in 0..archive.len() {
            let mut entry = archive.by_index(i)?;
            let Some(name) = entry.enclosed_name() else { continue; };
            let is_tif = name
                .extension()
                .and_then(|e| e.to_str())
                .is_some_and(|e| e.eq_ignore_ascii_case("tif") || e.eq_ignore_ascii_case("tiff"));
            if !is_tif {
                continue;
            }
            // Flatten subdirectories — the stitcher walks recursively
            // anyway, but a flat layout makes the directory easier to
            // inspect.
            let Some(file_name) = name.file_name().and_then(|s| s.to_str()) else { continue; };
            let out_path = extract_dir.join(file_name);
            let mut out = fs::File::create(&out_path)?;
            std::io::copy(&mut entry, &mut out)?;
        }
        // The ZIP is no longer needed; recover the disk.
        let _ = fs::remove_file(&zip_path);
        Ok(Some(extract_dir))
    }

    /// Download every existing package in regions covering `p`. Unlike the
    /// Python port this does NOT stop at the first 200 — it pulls all
    /// packages so the stitcher's coverage map is complete. Returns the
    /// extraction directories.
    pub fn download_for_location(
        &self,
        p: LatLon,
        types: &[PackageDataType],
        mut on_progress: impl FnMut(&PackageInfo, u64, u64),
    ) -> Result<Vec<PathBuf>, DownloadError> {
        let mut out = Vec::new();
        for pkg in Self::packages_for(p, types) {
            // Per-package progress wrapper.
            let pkg_for_cb = pkg.clone();
            let cb = |done: u64, total: u64| on_progress(&pkg_for_cb, done, total);
            // 404 returns Ok(None) — we silently skip unknown package numbers.
            if let Some(dir) = self.download(&pkg, cb)? {
                out.push(dir);
            }
        }
        Ok(out)
    }

    /// Same as [`Self::download_for_location`] but the trigger is a bbox
    /// (the centre is sampled for region matching).
    pub fn download_for_bbox(
        &self,
        nw: LatLon, se: LatLon,
        types: &[PackageDataType],
        on_progress: impl FnMut(&PackageInfo, u64, u64),
    ) -> Result<Vec<PathBuf>, DownloadError> {
        let centre = LatLon {
            lat_deg: (nw.lat_deg + se.lat_deg) * 0.5,
            lon_deg: (nw.lon_deg + se.lon_deg) * 0.5,
        };
        self.download_for_location(centre, types, on_progress)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    fn tmp_dir(name: &str) -> PathBuf {
        let p = std::env::temp_dir().join(format!("ls-site-dl-test-{name}"));
        let _ = fs::remove_dir_all(&p);
        p
    }

    #[test]
    fn package_info_renders_python_compatible_url() {
        let pkg = PackageInfo {
            name: "Sudbury".into(),
            number: "05".into(),
            data_type: PackageDataType::Dtm,
        };
        assert_eq!(pkg.full_name(), "Sudbury-DTM-05");
        assert_eq!(pkg.filename(), "Sudbury-DTM-05.zip");
        assert_eq!(pkg.url(), format!("{PACKAGE_BASE_URL}Sudbury-DTM-05.zip"));
    }

    #[test]
    fn known_packages_matches_python_table_counts() {
        // Mirrors KNOWN_PACKAGES in downloader.py.
        assert_eq!(package_numbers_for("Sudbury").len(), 10);
        assert_eq!(package_numbers_for("LakeNipissing").len(), 10);
        assert_eq!(package_numbers_for("GTA-Peel").len(), 5);
        assert_eq!(package_numbers_for("Ottawa").len(), 8);
        assert_eq!(package_numbers_for("Unknown"), &[] as &[&str]);
    }

    #[test]
    fn find_regions_for_sudbury_picks_sudbury_only() {
        let regions = LidarDownloader::find_regions(LatLon {
            lat_deg: 46.4917, lon_deg: -80.9930,
        });
        assert_eq!(regions, vec!["Sudbury"]);
    }

    #[test]
    fn packages_for_a_point_in_sudbury_enumerates_all_combos() {
        let p = LatLon { lat_deg: 46.4917, lon_deg: -80.9930 };
        let pkgs = LidarDownloader::packages_for(p, &[PackageDataType::Dtm]);
        // Sudbury has 10 numbers × 1 type = 10.
        assert_eq!(pkgs.len(), 10);
        assert!(pkgs.iter().all(|p| p.name == "Sudbury" && p.data_type == PackageDataType::Dtm));
        let pkgs = LidarDownloader::packages_for(p, &[PackageDataType::Dtm, PackageDataType::Dsm]);
        assert_eq!(pkgs.len(), 20);
    }

    #[test]
    fn download_short_circuits_when_a_tif_is_already_extracted() {
        // Pre-seed the package dir with a fake .tif; download should skip
        // the network entirely and report Ok(Some(dir)).
        let out = tmp_dir("preseeded");
        let dl = LidarDownloader::new(out.clone()).unwrap();
        let pkg = PackageInfo {
            name: "Sudbury".into(),
            number: "99".into(),
            data_type: PackageDataType::Dtm,
        };
        let pkg_dir = dl.package_dir(&pkg);
        fs::create_dir_all(&pkg_dir).unwrap();
        fs::write(pkg_dir.join("fake.tif"), b"not real").unwrap();
        assert!(dl.already_extracted(&pkg));
        let res = dl.download(&pkg, |_, _| {}).unwrap();
        assert_eq!(res, Some(pkg_dir));
    }

    /// Live OSM-style "is the server up" smoke test — opt-in.
    /// `cargo test -p ls-site -- --ignored sudbury_dtm_01_exists` will
    /// HEAD the real Ontario URL.
    #[test]
    #[ignore = "hits the real Ontario download server"]
    fn sudbury_dtm_01_exists() {
        let out = tmp_dir("real_head");
        let dl = LidarDownloader::new(out).unwrap();
        let pkg = PackageInfo {
            name: "Sudbury".into(),
            number: "01".into(),
            data_type: PackageDataType::Dtm,
        };
        // Just confirm a 200/404 came back (we don't care which on first
        // boot — the server may have rotated numbers).
        let _ = dl.check_exists(&pkg).expect("HEAD");
    }

    /// Synthetic ZIP extraction round-trip: build a tiny ZIP containing a
    /// fake .tif and a fake .pdf, drive `download` against a file:// path
    /// (skipped here because reqwest doesn't do file://) — so test extract
    /// indirectly via the same code path the downloader uses.
    #[test]
    fn zip_extraction_keeps_only_tif_files() {
        let dir = tmp_dir("zip_extract");
        fs::create_dir_all(&dir).unwrap();
        let zip_path = dir.join("synth.zip");
        {
            let f = fs::File::create(&zip_path).unwrap();
            let mut zw = zip::ZipWriter::new(f);
            let opt: zip::write::SimpleFileOptions = zip::write::SimpleFileOptions::default()
                .compression_method(zip::CompressionMethod::Deflated);
            zw.start_file("tile.tif", opt).unwrap();
            zw.write_all(b"FAKE_TIF").unwrap();
            zw.start_file("meta.pdf", opt).unwrap();
            zw.write_all(b"PDF").unwrap();
            zw.finish().unwrap();
        }
        // Drive only the extraction loop from `download` (manually, to keep
        // the test offline).
        let extract_dir = dir.join("out");
        fs::create_dir_all(&extract_dir).unwrap();
        let file = fs::File::open(&zip_path).unwrap();
        let mut archive = zip::ZipArchive::new(file).unwrap();
        let mut kept = 0;
        for i in 0..archive.len() {
            let mut e = archive.by_index(i).unwrap();
            let name = e.enclosed_name().unwrap();
            if name.extension().and_then(|s| s.to_str()).is_some_and(|s| s.eq_ignore_ascii_case("tif")) {
                let mut out = fs::File::create(extract_dir.join(name.file_name().unwrap())).unwrap();
                std::io::copy(&mut e, &mut out).unwrap();
                kept += 1;
            }
        }
        assert_eq!(kept, 1);
        assert!(extract_dir.join("tile.tif").is_file());
        assert!(!extract_dir.join("meta.pdf").exists());
    }
}
