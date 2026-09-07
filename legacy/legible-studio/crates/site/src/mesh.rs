//! Terrain-mesh stitcher: bbox → DEM tiles → JSON for `qbd::terrain`.
//!
//! The producer side of the `terrain_mesh` contract. Given a WGS84 bbox
//! (typically the bounds of the parcel polygon the user drew on the map
//! widget) and a [`LocalTileIndex`](crate::ontario::LocalTileIndex)
//! pointing at a directory of Ontario DEM tiles, this module:
//!
//! 1. Projects the bbox into UTM 17 N to get a UTM rectangle.
//! 2. Enumerates every 1 km tile the rectangle intersects.
//! 3. For each grid sample inside the UTM rect, finds the covering tile and
//!    nearest-neighbour-samples its elevation raster.
//! 4. Emits a [`TerrainMesh`] in *local plan millimetres* (x east, z north,
//!    y elevation) with the SW corner at the origin — exactly the shape
//!    [`qbd::terrain::from_json`] reads.
//!
//! Tiles are opened lazily and cached — a single 50×50 sample grid over a
//! 1-tile area opens that one tile once.

use std::collections::HashMap;

use serde::{Deserialize, Serialize};

use crate::coord::{LatLon, utm17_from_wgs84};
use crate::geotiff::{ElevationRaster, GeoTiffError, read_elevation};
use crate::ontario::{LocalTileIndex, OntarioTile, tiles_for_utm_bbox};

/// One mesh vertex `[x_mm, y_elev_mm, z_mm]`. Matches the
/// `{"position": [...]}` form that `qbd::terrain::from_json` reads after
/// it's wrapped in `MeshVertex { position }`.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct MeshPos(pub [f32; 3]);

/// One mesh vertex wrapping the position — matches the JSON shape
/// `qbd::terrain` already parses.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct MeshVertex {
    pub position: [f32; 3],
}

/// `terrain_mesh` payload — lot dimensions, elevation range, vertex list.
/// Field names match the JSON keys `qbd::terrain::from_json` reads.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TerrainMesh {
    pub width_ft: f32,
    pub depth_ft: f32,
    pub min_elevation: f32,
    pub max_elevation: f32,
    pub vertices: Vec<MeshVertex>,
}

/// Wrap a [`TerrainMesh`] in the top-level `{"terrain_mesh": …}` envelope
/// `qbd::terrain::from_json` accepts.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TerrainMeshEnvelope {
    pub terrain_mesh: TerrainMesh,
}

/// What stitching produced + what it couldn't.
#[derive(Debug)]
pub struct StitchResult {
    /// The mesh ready to hand to `qbd::terrain`.
    pub mesh: TerrainMesh,
    /// Tiles enumerated for the bbox that weren't found in the index. Pass
    /// these to the downloader (or have the user run the Python tool over
    /// the listed bbox).
    pub missing: Vec<OntarioTile>,
    /// Total grid samples taken.
    pub samples_taken: usize,
    /// Samples that fell outside any DEM (no covering tile or out-of-raster).
    /// Populated as zero elevation in the mesh and counted here.
    pub samples_missed: usize,
}

/// Errors the stitcher can produce.
#[derive(Debug, thiserror::Error)]
pub enum StitchError {
    #[error("bbox is degenerate: NW must be north-and-west of SE")]
    DegenerateBbox,
    #[error("bbox falls outside UTM zone 17 N")]
    OutOfZone,
    #[error("grid_n must be ≥ 2")]
    BadGridN,
    #[error("opening a DEM tile failed: {0}")]
    Geotiff(#[from] GeoTiffError),
}

/// Convenience: how many vertices the default grid produces.
pub const DEFAULT_GRID_N: usize = 33;

const M_TO_FT: f32 = 3.280_84;
pub(crate) const M_TO_MM: f32 = 1000.0;

/// Stitch a `TerrainMesh` covering the WGS84 bbox `(nw, se)`, sampling on
/// a `grid_n × grid_n` lattice. Tiles are opened lazily and reused across
/// samples. Missing tiles (not in `index`) leave their samples at zero —
/// callers should fetch them and re-run.
///
/// `grid_n` defaults to [`DEFAULT_GRID_N`] (33×33 = 1 089 vertices, plenty
/// for the marching-squares contour generator in `qbd::terrain`).
#[allow(
    clippy::cast_possible_truncation,
    clippy::cast_precision_loss,
    clippy::cast_sign_loss,
)]
pub fn stitch(
    nw: LatLon, se: LatLon, index: &LocalTileIndex, grid_n: usize,
) -> Result<StitchResult, StitchError> {
    if nw.lat_deg <= se.lat_deg || nw.lon_deg >= se.lon_deg {
        return Err(StitchError::DegenerateBbox);
    }
    if grid_n < 2 {
        return Err(StitchError::BadGridN);
    }
    // Project the 4 corners; the UTM rect is their bounding box.
    let ne = LatLon { lat_deg: nw.lat_deg, lon_deg: se.lon_deg };
    let sw = LatLon { lat_deg: se.lat_deg, lon_deg: nw.lon_deg };
    let utm_pts = [
        utm17_from_wgs84(nw),
        utm17_from_wgs84(ne),
        utm17_from_wgs84(se),
        utm17_from_wgs84(sw),
    ];
    if utm_pts.iter().any(|p| p.zone != 17 || !p.northern_hemisphere) {
        return Err(StitchError::OutOfZone);
    }
    let min_e = utm_pts.iter().map(|p| p.easting_m).fold(f64::INFINITY, f64::min);
    let max_e = utm_pts.iter().map(|p| p.easting_m).fold(f64::NEG_INFINITY, f64::max);
    let min_n = utm_pts.iter().map(|p| p.northing_m).fold(f64::INFINITY, f64::min);
    let max_n = utm_pts.iter().map(|p| p.northing_m).fold(f64::NEG_INFINITY, f64::max);

    let width_m = (max_e - min_e) as f32;
    let depth_m = (max_n - min_n) as f32;

    // Which tiles cover the rect, and which of those aren't on disk?
    let wanted = tiles_for_utm_bbox(
        17, min_e.floor() as u32, min_n.floor() as u32,
        max_e.ceil() as u32, max_n.ceil() as u32,
    );
    let (_have_paths, missing) = index.classify(&wanted);

    // Lazy-open cache: tile prefix → loaded raster. Keeps memory bounded
    // to the tiles actually needed, opens each at most once.
    let mut open: HashMap<String, ElevationRaster> = HashMap::new();
    let mut min_elev = f32::INFINITY;
    let mut max_elev = f32::NEG_INFINITY;
    let mut samples_missed = 0_usize;
    let mut vertices: Vec<MeshVertex> = Vec::with_capacity(grid_n * grid_n);

    for j in 0..grid_n {
        for i in 0..grid_n {
            let u = i as f64 / (grid_n - 1) as f64;
            let v = j as f64 / (grid_n - 1) as f64;
            let easting = min_e + u * (max_e - min_e);
            // j=0 is the SW corner row (z=0); j=grid_n-1 is the NE row.
            let northing = min_n + v * (max_n - min_n);
            // Local plan coords: x east, z north, origin at SW corner, mm.
            let x_mm = (easting - min_e) as f32 * M_TO_MM;
            let z_mm = (northing - min_n) as f32 * M_TO_MM;

            let elev = if let Some(e) = sample_at(&mut open, index, &wanted, easting, northing)? {
                e
            } else {
                samples_missed += 1;
                0.0
            };
            min_elev = min_elev.min(elev);
            max_elev = max_elev.max(elev);
            let y_mm = elev * M_TO_MM;
            vertices.push(MeshVertex { position: [x_mm, y_mm, z_mm] });
        }
    }
    if !min_elev.is_finite() {
        min_elev = 0.0;
    }
    if !max_elev.is_finite() {
        max_elev = 0.0;
    }
    let mesh = TerrainMesh {
        width_ft: width_m * M_TO_FT,
        depth_ft: depth_m * M_TO_FT,
        min_elevation: min_elev,
        max_elevation: max_elev,
        vertices,
    };
    Ok(StitchResult {
        mesh,
        missing,
        samples_taken: grid_n * grid_n,
        samples_missed,
    })
}

/// Sample one UTM 17 point: pick the covering tile, open it lazily, look
/// up the elevation. Returns `None` when no tile in `wanted` covers the
/// point or the tile isn't on disk.
fn sample_at(
    open: &mut HashMap<String, ElevationRaster>,
    index: &LocalTileIndex,
    wanted: &[OntarioTile],
    easting: f64, northing: f64,
) -> Result<Option<f32>, StitchError> {
    let Some(tile) = covering_tile(wanted, easting, northing) else {
        return Ok(None);
    };
    let prefix = tile.name_prefix();
    if !open.contains_key(&prefix) {
        let Some(path) = index.path_for(tile) else {
            return Ok(None);
        };
        let raster = read_elevation(path)?;
        open.insert(prefix.clone(), raster);
    }
    let raster = &open[&prefix];
    Ok(raster.sample_model(easting, northing))
}

/// First tile in `wanted` whose UTM bounds contain `(easting, northing)`.
#[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)]
fn covering_tile(wanted: &[OntarioTile], easting: f64, northing: f64) -> Option<OntarioTile> {
    if easting < 0.0 || northing < 0.0 {
        return None;
    }
    let e = easting as u32;
    let n = northing as u32;
    wanted.iter().copied().find(|t| {
        let (e0, n0, e1, n1) = t.utm_bounds();
        e >= e0 && e < e1 && n >= n0 && n < n1
    })
}

/// Serialise a [`TerrainMesh`] into the `{"terrain_mesh": …}` JSON envelope
/// `qbd::terrain::from_json` accepts.
#[must_use]
pub fn to_terrain_json(mesh: &TerrainMesh) -> String {
    serde_json::to_string_pretty(&TerrainMeshEnvelope { terrain_mesh: mesh.clone() })
        .unwrap_or_else(|_| "{}".into())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::coord::wgs84_from_utm17;
    use crate::ontario::OntarioTile;
    use std::fs;
    use std::io::Cursor;
    use std::path::PathBuf;
    use tiff::encoder::{TiffEncoder, colortype};
    use tiff::tags::Tag;

    /// Write a synthetic 1 km Ontario DEM with a known elevation ramp into
    /// `dir`, named so [`LocalTileIndex`] picks it up.
    fn write_fake_ontario_tile(
        dir: &std::path::Path,
        zone: u8, ekm: u32, nm: u32,
        ramp_origin_m: f32,
    ) -> OntarioTile {
        let tile = OntarioTile { zone, easting_m: ekm * 1000, northing_m: nm };
        let prefix = tile.name_prefix();
        let path = dir.join(format!("{prefix}TEST_DSM.tif"));
        // 100 × 100 raster at 10 m/pixel — 1 km tile.
        let width = 100_u32;
        let height = 100_u32;
        let scale_xy = 10.0_f64;
        // Model origin = NW corner of the tile (raster (0,0)).
        let origin_x = f64::from(tile.easting_m);
        let origin_y = f64::from(tile.northing_m + 1000); // y flips: raster top is north
        let samples: Vec<f32> = (0..(width * height))
            .map(|i| ramp_origin_m + (i as f32) * 0.01)
            .collect();
        let mut buf = Cursor::new(Vec::<u8>::new());
        {
            let mut enc = TiffEncoder::new(&mut buf).unwrap();
            let mut img = enc.new_image::<colortype::Gray32Float>(width, height).unwrap();
            img.encoder().write_tag(
                Tag::ModelTiepointTag,
                &[0.0_f64, 0.0, 0.0, origin_x, origin_y, 0.0][..],
            ).unwrap();
            img.encoder().write_tag(
                Tag::ModelPixelScaleTag,
                &[scale_xy, scale_xy, 0.0][..],
            ).unwrap();
            img.encoder().write_tag(
                Tag::GeoKeyDirectoryTag,
                &[1_u16, 1, 0, 1, 3072, 0, 1, 26917][..],
            ).unwrap();
            img.write_data(&samples).unwrap();
        }
        fs::write(&path, buf.into_inner()).unwrap();
        tile
    }

    fn tmp_tiles(name: &str) -> PathBuf {
        let p = std::env::temp_dir().join(format!("ls-site-mesh-test-{name}"));
        let _ = fs::remove_dir_all(&p);
        fs::create_dir_all(&p).unwrap();
        p
    }

    /// A bbox whose UTM projection lands entirely inside the synthetic
    /// tile produces a mesh with all samples populated and no missing
    /// tiles.
    #[test]
    fn stitch_over_a_covered_bbox_populates_all_samples() {
        let dir = tmp_tiles("covered");
        // Synthetic tile at easting 500 km, northing 5 000 000.
        let _t = write_fake_ontario_tile(&dir, 17, 500, 5_000_000, 100.0);
        // Pick a sub-bbox inside the tile: UTM rect (500200..500800, 5000200..5000800).
        let nw_utm = crate::UtmCoord {
            easting_m: 500_200.0,
            northing_m: 5_000_800.0,
            zone: 17,
            northern_hemisphere: true,
        };
        let se_utm = crate::UtmCoord {
            easting_m: 500_800.0,
            northing_m: 5_000_200.0,
            zone: 17,
            northern_hemisphere: true,
        };
        let nw = wgs84_from_utm17(nw_utm);
        let se = wgs84_from_utm17(se_utm);
        let index = LocalTileIndex::scan(&dir).unwrap();
        assert_eq!(index.len(), 1);
        let res = stitch(nw, se, &index, 8).unwrap();
        assert!(res.missing.is_empty(), "missing {:?}", res.missing);
        assert_eq!(res.samples_taken, 64);
        assert_eq!(res.samples_missed, 0);
        assert_eq!(res.mesh.vertices.len(), 64);
        // Width / depth are sub-km but positive, in feet.
        assert!(res.mesh.width_ft > 0.0 && res.mesh.depth_ft > 0.0);
        // Elevations are populated and the min/max bracket the samples.
        assert!(res.mesh.min_elevation >= 100.0);
        assert!(res.mesh.max_elevation < 200.0);
    }

    /// A bbox over an empty index reports every needed tile as missing and
    /// leaves the mesh elevations at zero (without crashing).
    #[test]
    fn stitch_over_an_empty_index_lists_missing_tiles() {
        let dir = tmp_tiles("empty");
        let index = LocalTileIndex::scan(&dir).unwrap();
        let nw_utm = crate::UtmCoord {
            easting_m: 500_200.0, northing_m: 5_000_800.0,
            zone: 17, northern_hemisphere: true,
        };
        let se_utm = crate::UtmCoord {
            easting_m: 500_800.0, northing_m: 5_000_200.0,
            zone: 17, northern_hemisphere: true,
        };
        let res = stitch(
            wgs84_from_utm17(nw_utm), wgs84_from_utm17(se_utm), &index, 4,
        ).unwrap();
        assert!(!res.missing.is_empty(), "no missing reported");
        // All samples missed; mesh still emits 16 zero-elevation vertices.
        assert_eq!(res.samples_missed, 16);
        assert_eq!(res.mesh.vertices.len(), 16);
        assert_eq!(res.mesh.min_elevation, 0.0);
        assert_eq!(res.mesh.max_elevation, 0.0);
    }

    /// JSON round-trips through qbd::terrain's expected envelope.
    #[test]
    fn emitted_json_has_terrain_mesh_envelope() {
        let mesh = TerrainMesh {
            width_ft: 50.0,
            depth_ft: 50.0,
            min_elevation: 0.0,
            max_elevation: 2.0,
            vertices: vec![MeshVertex { position: [0.0, 0.0, 0.0] }],
        };
        let json = to_terrain_json(&mesh);
        let v: serde_json::Value = serde_json::from_str(&json).unwrap();
        assert!(v.get("terrain_mesh").is_some());
        assert_eq!(v["terrain_mesh"]["width_ft"], 50.0);
        assert_eq!(v["terrain_mesh"]["vertices"][0]["position"][0], 0.0);
    }

    #[test]
    fn degenerate_bbox_is_rejected() {
        let dir = tmp_tiles("bad");
        let index = LocalTileIndex::scan(&dir).unwrap();
        // NW south of SE.
        let nw = LatLon { lat_deg: 46.49, lon_deg: -81.0 };
        let se = LatLon { lat_deg: 46.50, lon_deg: -80.99 };
        let r = stitch(nw, se, &index, 4);
        assert!(matches!(r, Err(StitchError::DegenerateBbox)));
    }

    #[test]
    fn grid_n_less_than_two_is_rejected() {
        let dir = tmp_tiles("grid1");
        let index = LocalTileIndex::scan(&dir).unwrap();
        let nw = LatLon { lat_deg: 46.50, lon_deg: -81.0 };
        let se = LatLon { lat_deg: 46.49, lon_deg: -80.99 };
        let r = stitch(nw, se, &index, 1);
        assert!(matches!(r, Err(StitchError::BadGridN)));
    }
}
