//! Building-footprint extraction from LiDAR DEM rasters.
//!
//! Simple height-threshold + convex-hull approach:
//! 1. Sample DSM (and optionally DTM) on a grid inside the WGS84 bbox.
//! 2. `height = DSM - DTM` (or `DSM - min_elevation` if no DTM).
//! 3. Keep points where height > threshold.
//! 4. 2-D convex hull of those points in local plan millimetres.
//! 5. Return polygon vertices.
//!
//! This is intentionally crude — it exists to bootstrap the as-built
//! pipeline. A later increment can replace the threshold+convex-hull
//! with vegetation filtering, plane segmentation, or ML.

use std::collections::HashMap;

use glam::Vec2;

use crate::coord::LatLon;
use crate::geotiff::{ElevationRaster, GeoTiffError, read_elevation};
use crate::mesh::M_TO_MM;
use crate::ontario::{LocalTileIndex, OntarioTile, tiles_for_utm_bbox};

/// One building footprint extracted from a LiDAR DEM pair.
#[derive(Debug, Clone)]
pub struct FootprintResult {
    /// Convex-hull vertices in local plan millimetres (x east, z north),
    /// origin at the SW corner of the bbox. Compatible with
    /// `SchemaDocument::footprint_polygon_mm`.
    pub polygon_mm: Vec<Vec2>,
    /// Lowest elevation found on the sampled grid (metres).
    pub ground_elevation_m: f32,
    /// Tallest point above ground (metres).
    pub max_height_above_ground_m: f32,
    /// How many grid samples exceeded the threshold.
    pub samples_above_threshold: usize,
    /// Total grid samples evaluated.
    pub total_samples: usize,
}

/// Errors the footprint extractor can produce.
#[derive(Debug, thiserror::Error)]
pub enum FootprintError {
    #[error("bbox is degenerate: NW must be north-and-west of SE")]
    DegenerateBbox,
    #[error("bbox falls outside UTM zone 17 N")]
    OutOfZone,
    #[error("grid_n must be ≥ 2")]
    BadGridN,
    #[error("opening a DEM tile failed: {0}")]
    Geotiff(#[from] GeoTiffError),
    #[error("no samples above {0} m — try a lower threshold or check the DEM coverage")]
    NoBuildingFound(f32),
}

/// Extract a building footprint from DSM (+ optional DTM) tiles.
///
/// `grid_n` controls the sampling density (default 65 gives ~15 m spacing
/// on a 1 km lot). `height_threshold_m` is the minimum elevation above
/// ground that counts as building (default 2.0 m).
#[allow(
    clippy::cast_possible_truncation,
    clippy::cast_precision_loss,
    clippy::cast_sign_loss,
)]
pub fn extract_footprint(
    nw: LatLon,
    se: LatLon,
    dsm_index: &LocalTileIndex,
    dtm_index: Option<&LocalTileIndex>,
    grid_n: usize,
    height_threshold_m: f32,
) -> Result<FootprintResult, FootprintError> {
    if nw.lat_deg <= se.lat_deg || nw.lon_deg >= se.lon_deg {
        return Err(FootprintError::DegenerateBbox);
    }
    if grid_n < 2 {
        return Err(FootprintError::BadGridN);
    }

    let ne = LatLon {
        lat_deg: nw.lat_deg,
        lon_deg: se.lon_deg,
    };
    let sw = LatLon {
        lat_deg: se.lat_deg,
        lon_deg: nw.lon_deg,
    };
    let utm_pts = [
        crate::coord::utm17_from_wgs84(nw),
        crate::coord::utm17_from_wgs84(ne),
        crate::coord::utm17_from_wgs84(se),
        crate::coord::utm17_from_wgs84(sw),
    ];
    if utm_pts.iter().any(|p| p.zone != 17 || !p.northern_hemisphere) {
        return Err(FootprintError::OutOfZone);
    }

    let min_e = utm_pts.iter().map(|p| p.easting_m).fold(f64::INFINITY, f64::min);
    let max_e = utm_pts.iter().map(|p| p.easting_m).fold(f64::NEG_INFINITY, f64::max);
    let min_n = utm_pts.iter().map(|p| p.northing_m).fold(f64::INFINITY, f64::min);
    let max_n = utm_pts.iter().map(|p| p.northing_m).fold(f64::NEG_INFINITY, f64::max);

    let wanted = tiles_for_utm_bbox(
        17,
        min_e.floor() as u32,
        min_n.floor() as u32,
        max_e.ceil() as u32,
        max_n.ceil() as u32,
    );

    let mut dsm_open: HashMap<String, ElevationRaster> = HashMap::new();
    let mut dtm_open: HashMap<String, ElevationRaster> = HashMap::new();

    let mut ground_elev = f32::INFINITY;
    // First pass: sample DSM (+ optional DTM) on every grid point and
    // collect raw elevations. We need the global ground level (minimum DTM
    // or minimum DSM when DTM is absent) before we can compute heights.
    #[derive(Clone, Copy)]
    struct Sample {
        easting: f64,
        northing: f64,
        dsm: Option<f32>,
        dtm: Option<f32>,
    }

    let mut samples: Vec<Sample> = Vec::with_capacity(grid_n * grid_n);
    for j in 0..grid_n {
        for i in 0..grid_n {
            let u = i as f64 / (grid_n - 1) as f64;
            let v = j as f64 / (grid_n - 1) as f64;
            let easting = min_e + u * (max_e - min_e);
            let northing = min_n + v * (max_n - min_n);

            let dsm_elev = sample_at(&mut dsm_open, dsm_index, &wanted, easting, northing
            )?;
            let dtm_elev = if let Some(idx) = dtm_index {
                sample_at(&mut dtm_open, idx, &wanted, easting, northing)?
            } else {
                None
            };

            // Track the lowest elevation seen — when DTM is present that's
            // the ground; when absent it's the lowest DSM sample.
            let ground_here = dtm_elev.unwrap_or(dsm_elev.unwrap_or(0.0));
            ground_elev = ground_elev.min(ground_here);

            samples.push(Sample {
                easting,
                northing,
                dsm: dsm_elev,
                dtm: dtm_elev,
            });
        }
    }

    // Second pass: compute heights using the global ground level.
    let mut max_height = 0.0_f32;
    let mut above = 0usize;
    let mut above_points: Vec<Vec2> = Vec::new();
    for s in &samples {
        let ground = s.dtm.unwrap_or(ground_elev);
        let height = if let Some(dsm) = s.dsm {
            dsm - ground
        } else {
            0.0
        };
        max_height = max_height.max(height);
        if height > height_threshold_m {
            above += 1;
            let x_mm = ((s.easting - min_e) * f64::from(M_TO_MM)) as f32;
            let z_mm = ((s.northing - min_n) * f64::from(M_TO_MM)) as f32;
            above_points.push(Vec2::new(x_mm, z_mm));
        }
    }

    if above_points.is_empty() {
        return Err(FootprintError::NoBuildingFound(height_threshold_m));
    }

    let hull = convex_hull(&above_points);

    Ok(FootprintResult {
        polygon_mm: hull,
        ground_elevation_m: ground_elev,
        max_height_above_ground_m: max_height,
        samples_above_threshold: above,
        total_samples: samples.len(),
    })
}

// ---------------------------------------------------------------------------
// Sampling helper (mirrors mesh.rs::sample_at but returns GeoTiffError)
// ---------------------------------------------------------------------------

fn sample_at(
    open: &mut HashMap<String, ElevationRaster>,
    index: &LocalTileIndex,
    wanted: &[OntarioTile],
    easting: f64,
    northing: f64,
) -> Result<Option<f32>, GeoTiffError> {
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

// ---------------------------------------------------------------------------
// Monotone-chain convex hull
// ---------------------------------------------------------------------------

/// Andrew's monotone chain — O(n log n). Returns vertices in CCW order.
/// Collinear interior points are removed (keeps only the endpoints).
fn convex_hull(points: &[Vec2]) -> Vec<Vec2> {
    if points.len() <= 1 {
        return points.to_vec();
    }

    let mut pts: Vec<Vec2> = points.to_vec();
    pts.sort_by(|a, b| {
        a.x.partial_cmp(&b.x)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| a.y.partial_cmp(&b.y).unwrap_or(std::cmp::Ordering::Equal))
    });
    // Deduplicate within 1 mm — grid samples can produce exact duplicates.
    pts.dedup_by(|a, b| (a.x - b.x).abs() < 1.0 && (a.y - b.y).abs() < 1.0);

    if pts.len() <= 1 {
        return pts;
    }

    let cross = |o: Vec2, a: Vec2, b: Vec2| -> f32 {
        (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x)
    };

    let mut lower = Vec::new();
    for &p in &pts {
        while lower.len() >= 2 && cross(lower[lower.len() - 2], lower[lower.len() - 1], p) <= 0.0
        {
            lower.pop();
        }
        lower.push(p);
    }

    let mut upper = Vec::new();
    for &p in pts.iter().rev() {
        while upper.len() >= 2 && cross(upper[upper.len() - 2], upper[upper.len() - 1], p) <= 0.0
        {
            upper.pop();
        }
        upper.push(p);
    }

    // Last point of each half is omitted because it's repeated in the other half.
    lower.pop();
    upper.pop();
    lower.extend(upper);
    lower
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn convex_hull_of_square() {
        let pts = vec![
            Vec2::new(0.0, 0.0),
            Vec2::new(10.0, 0.0),
            Vec2::new(10.0, 10.0),
            Vec2::new(0.0, 10.0),
            Vec2::new(5.0, 5.0), // interior
        ];
        let hull = convex_hull(&pts);
        assert_eq!(hull.len(), 4);
        assert!(hull.contains(&Vec2::new(0.0, 0.0)));
        assert!(hull.contains(&Vec2::new(10.0, 0.0)));
        assert!(hull.contains(&Vec2::new(10.0, 10.0)));
        assert!(hull.contains(&Vec2::new(0.0, 10.0)));
    }

    #[test]
    fn convex_hull_of_collinear_points_is_endpoints() {
        let pts = vec![
            Vec2::new(0.0, 0.0),
            Vec2::new(1.0, 1.0),
            Vec2::new(2.0, 2.0),
            Vec2::new(3.0, 3.0),
        ];
        let hull = convex_hull(&pts);
        assert_eq!(hull.len(), 2);
        assert!(hull.contains(&Vec2::new(0.0, 0.0)));
        assert!(hull.contains(&Vec2::new(3.0, 3.0)));
    }

    #[test]
    fn convex_hull_of_single_point() {
        let pts = vec![Vec2::new(5.0, 5.0)];
        assert_eq!(convex_hull(&pts), pts);
    }

    #[test]
    fn convex_hull_of_two_points() {
        let pts = vec![Vec2::new(0.0, 0.0), Vec2::new(10.0, 10.0)];
        let hull = convex_hull(&pts);
        assert_eq!(hull.len(), 2);
    }

    #[test]
    fn convex_hull_of_l_shape() {
        // An L-shape without the NE corner — the hull is a pentagon.
        let pts = vec![
            Vec2::new(0.0, 0.0),
            Vec2::new(10.0, 0.0),
            Vec2::new(10.0, 5.0),
            Vec2::new(5.0, 5.0),
            Vec2::new(5.0, 10.0),
            Vec2::new(0.0, 10.0),
        ];
        let hull = convex_hull(&pts);
        // Monotone-chain hull of these 6 points is a pentagon with area 87.5.
        let area = polygon_area(&hull);
        assert!((area - 87.5).abs() < 0.1, "area = {area}");
    }

    #[test]
    fn convex_hull_of_rectangle() {
        let pts = vec![
            Vec2::new(0.0, 0.0),
            Vec2::new(10.0, 0.0),
            Vec2::new(10.0, 10.0),
            Vec2::new(0.0, 10.0),
        ];
        let hull = convex_hull(&pts);
        assert_eq!(polygon_area(&hull), 100.0);
    }

    fn polygon_area(poly: &[Vec2]) -> f32 {
        if poly.is_empty() {
            return 0.0;
        }
        let mut a = 0.0_f32;
        let n = poly.len();
        for i in 0..n {
            let j = (i + 1) % n;
            a += poly[i].x * poly[j].y - poly[j].x * poly[i].y;
        }
        a.abs() * 0.5
    }

    // -----------------------------------------------------------------------
    // Integration test with synthetic Ontario DEM tiles
    // -----------------------------------------------------------------------

    use std::fs;
    use std::io::Cursor;
    use tiff::encoder::{TiffEncoder, colortype};
    use tiff::tags::Tag;

    fn write_fake_tile(
        dir: &std::path::Path,
        zone: u8, ekm: u32, nm: u32,
        samples: &[f32], width: u32, height: u32,
    ) {
        let tile = crate::ontario::OntarioTile { zone, easting_m: ekm * 1000, northing_m: nm };
        let prefix = tile.name_prefix();
        let path = dir.join(format!("{prefix}TEST.tif"));
        let scale_xy = 10.0_f64;
        let origin_x = f64::from(tile.easting_m);
        let origin_y = f64::from(tile.northing_m + 1000);
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
            img.write_data(samples).unwrap();
        }
        fs::write(&path, buf.into_inner()).unwrap();
    }

    fn tmp_dir(name: &str) -> std::path::PathBuf {
        let p = std::env::temp_dir().join(format!("ls-footprint-test-{name}"));
        let _ = fs::remove_dir_all(&p);
        fs::create_dir_all(&p).unwrap();
        p
    }

    #[test]
    fn extract_footprint_from_synthetic_dem() {
        let dsm_dir = tmp_dir("dsm");
        let dtm_dir = tmp_dir("dtm");

        // 100×100 raster at 10 m/pixel → 1 km tile.
        let width = 100_u32;
        let height = 100_u32;
        let mut dsm_samples: Vec<f32> = vec![0.0; (width * height) as usize];
        let mut dtm_samples: Vec<f32> = vec![0.0; (width * height) as usize];

        // Raise a 40×40 block in the centre to 10 m.
        for y in 30..70 {
            for x in 30..70 {
                let idx = (y * width as usize + x) as usize;
                dsm_samples[idx] = 10.0;
            }
        }

        // Tile at zone 17, easting 500 km, northing 5_000_000.
        write_fake_tile(&dsm_dir, 17, 500, 5_000_000, &dsm_samples, width, height);
        write_fake_tile(&dtm_dir, 17, 500, 5_000_000, &dtm_samples, width, height);

        // Bbox inside the tile: UTM rect (500200..500800, 5000200..5000800).
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
        let nw = crate::coord::wgs84_from_utm17(nw_utm);
        let se = crate::coord::wgs84_from_utm17(se_utm);

        let dsm_index = crate::ontario::LocalTileIndex::scan(&dsm_dir).unwrap();
        let dtm_index = crate::ontario::LocalTileIndex::scan(&dtm_dir).unwrap();

        let res = extract_footprint(nw, se, &dsm_index, Some(&dtm_index), 8, 2.0).unwrap();

        // On an 8×8 grid over 600 m the sample spacing is ~86 m.
        // The high block (400 m wide) is fully covered by 4×4 interior
        // samples → hull is a square roughly 257 mm on a side.
        assert!(
            res.samples_above_threshold >= 4,
            "expected several samples above threshold, got {}",
            res.samples_above_threshold
        );
        assert_eq!(res.ground_elevation_m, 0.0);
        assert!(res.max_height_above_ground_m >= 10.0);

        // Hull area in mm² — on this coarse grid the interior 4 samples
        // give a square ~257_000 mm on a side → area ~6.6e10.
        let area = polygon_area(&res.polygon_mm);
        assert!(
            area > 5.0e10 && area < 8.0e10,
            "hull area {area} outside expected range"
        );
    }

    #[test]
    fn extract_footprint_without_dtm_uses_min_elevation() {
        let dsm_dir = tmp_dir("dsm_no_dtm");
        let width = 100_u32;
        let height = 100_u32;
        let mut dsm_samples: Vec<f32> = vec![5.0; (width * height) as usize];
        // 20×20 elevated block at the centre (200 m × 200 m).
        for y in 40..60 {
            for x in 40..60 {
                dsm_samples[y * width as usize + x] = 15.0;
            }
        }
        write_fake_tile(&dsm_dir, 17, 500, 5_000_000, &dsm_samples, width, height);

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
        let nw = crate::coord::wgs84_from_utm17(nw_utm);
        let se = crate::coord::wgs84_from_utm17(se_utm);

        let dsm_index = crate::ontario::LocalTileIndex::scan(&dsm_dir).unwrap();

        // Threshold 8 m: ground = min = 5 m, so the 200 m block is 10 m
        // above ground and should be detected.
        let res = extract_footprint(nw, se, &dsm_index, None, 16, 8.0).unwrap();
        assert!(
            res.samples_above_threshold >= 4,
            "expected several samples above threshold, got {}",
            res.samples_above_threshold
        );
        assert_eq!(res.ground_elevation_m, 5.0);
    }
}
