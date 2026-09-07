//! As-built interior wall detection from a LiDAR point cloud.
//!
//! Vertical walls show up as dense, near-vertical planes. Reduce the 3-D
//! plane-segmentation problem to a 2-D line-detection problem:
//!
//! 1. Find the floor (lowest points) and slice a horizontal band well above
//!    it and below the ceiling — typically 0.5 m .. 1.8 m. That band misses
//!    floor, ceiling, and most furniture tops while keeping wall faces.
//! 2. Project the band to the plan (XZ). Wall faces become dense line
//!    clusters.
//! 3. Voxel-downsample the plan so density is uniform and the cost is bounded.
//! 4. Deterministic Hough vote over (θ, ρ); greedily extract the strongest
//!    line, refit it to its inliers (PCA), split that line into segments where
//!    the scan has gaps (doorways, openings), keep the long ones, remove the
//!    consumed points, and repeat.
//!
//! Like [`crate::footprint`], this is an intentionally crude bootstrap. It
//! assumes near-vertical walls and one dominant floor level. Multi-storey
//! splitting, slanted walls, and curved walls are future work.
//!
//! **Units:** input points are metres with **y up** (x east, z north — the
//! same convention as `SchemaWall`). Output plan coordinates are millimetres.

use glam::{Vec2, Vec3};

use crate::mesh::M_TO_MM;

/// One detected as-built wall, as a centreline segment in plan millimetres.
#[derive(Debug, Clone)]
pub struct AsBuiltWall {
    /// Segment start in plan millimetres (x east, y north — a `Vec2` plan).
    pub start_mm: Vec2,
    /// Segment end in plan millimetres.
    pub end_mm: Vec2,
    /// Rough thickness estimate: perpendicular spread of the supporting
    /// points, clamped to a sane minimum. Scans often see one face only, so
    /// treat this as a lower bound, not a measurement.
    pub thickness_mm: f32,
    /// How many (downsampled) points supported this segment.
    pub point_count: usize,
}

impl AsBuiltWall {
    /// Segment length in plan millimetres.
    #[must_use]
    pub fn length_mm(&self) -> f32 {
        self.start_mm.distance(self.end_mm)
    }
}

/// Result of an as-built wall extraction.
#[derive(Debug, Clone)]
pub struct AsBuiltResult {
    /// Detected wall centrelines (plan millimetres).
    pub walls: Vec<AsBuiltWall>,
    /// Estimated floor elevation (metres, original cloud frame).
    pub floor_elevation_m: f32,
    /// Estimated ceiling elevation (metres, original cloud frame).
    pub ceiling_elevation_m: f32,
    /// Floor-to-ceiling height (metres).
    pub wall_height_m: f32,
    /// Points that fell in the analysis band before downsampling.
    pub band_points: usize,
    /// Occupied plan voxels fed to the line detector.
    pub voxels: usize,
}

/// Tunable parameters for [`detect_walls`].
#[derive(Debug, Clone)]
pub struct WallDetectParams {
    /// Band lower bound above the detected floor (metres).
    pub band_low_m: f32,
    /// Band upper bound above the detected floor (metres).
    pub band_high_m: f32,
    /// Plan voxel size for downsampling (millimetres).
    pub voxel_mm: f32,
    /// Number of angle bins across [0°, 180°).
    pub angle_steps: usize,
    /// ρ bin width (millimetres).
    pub rho_res_mm: f32,
    /// Perpendicular inlier tolerance when collecting a line's support (mm).
    pub dist_tol_mm: f32,
    /// Shortest segment we will emit (millimetres).
    pub min_wall_len_mm: f32,
    /// A gap larger than this along a line splits it into separate walls (mm).
    pub max_gap_mm: f32,
    /// Stop once the strongest remaining line has fewer supporting voxels.
    pub min_votes: usize,
    /// Hard cap on the number of extraction iterations.
    pub max_walls: usize,
}

impl Default for WallDetectParams {
    fn default() -> Self {
        Self {
            band_low_m: 0.5,
            band_high_m: 1.8,
            voxel_mm: 50.0,
            angle_steps: 180,
            rho_res_mm: 100.0,
            dist_tol_mm: 200.0,
            min_wall_len_mm: 600.0,
            max_gap_mm: 500.0,
            min_votes: 6,
            max_walls: 256,
        }
    }
}

/// Errors the wall detector can produce.
#[derive(Debug, thiserror::Error)]
pub enum AsBuiltError {
    #[error("point cloud is empty")]
    EmptyCloud,
    #[error("no points fell in the {0:.2}..{1:.2} m analysis band — check the band or the cloud's vertical axis")]
    EmptyBand(f32, f32),
    #[error("band collapsed to fewer than 2 plan voxels — cloud is too sparse")]
    TooSparse,
    #[error("angle_steps must be ≥ 2")]
    BadAngleSteps,
}

/// Detect interior walls from a point cloud.
///
/// `points` are metres with y up. See the module docs for the algorithm.
#[allow(
    clippy::cast_possible_truncation,
    clippy::cast_precision_loss,
    clippy::cast_sign_loss,
    clippy::cast_possible_wrap,
)]
pub fn detect_walls(
    points: &[Vec3],
    params: &WallDetectParams,
) -> Result<AsBuiltResult, AsBuiltError> {
    if points.is_empty() {
        return Err(AsBuiltError::EmptyCloud);
    }
    if params.angle_steps < 2 {
        return Err(AsBuiltError::BadAngleSteps);
    }

    // --- floor / ceiling from the vertical extent ---------------------------
    let mut floor = f32::INFINITY;
    let mut ceiling = f32::NEG_INFINITY;
    for p in points {
        floor = floor.min(p.y);
        ceiling = ceiling.max(p.y);
    }

    // --- horizontal band slice ---------------------------------------------
    let band_lo = floor + params.band_low_m;
    let band_hi = floor + params.band_high_m;
    let mut band: Vec<Vec2> = Vec::new();
    for p in points {
        if p.y >= band_lo && p.y <= band_hi {
            // metres → millimetres, plan only (x, z).
            band.push(Vec2::new(p.x * M_TO_MM, p.z * M_TO_MM));
        }
    }
    if band.is_empty() {
        return Err(AsBuiltError::EmptyBand(params.band_low_m, params.band_high_m));
    }
    let band_points = band.len();

    // --- voxel downsample in plan ------------------------------------------
    let voxels = voxel_downsample(&band, params.voxel_mm);
    if voxels.len() < 2 {
        return Err(AsBuiltError::TooSparse);
    }
    let voxel_count = voxels.len();

    // --- iterative Hough line extraction -----------------------------------
    let mut remaining = voxels;
    let mut walls: Vec<AsBuiltWall> = Vec::new();

    for _ in 0..params.max_walls {
        if remaining.len() < params.min_votes {
            break;
        }
        let Some((theta, rho, votes)) = strongest_line(&remaining, params) else {
            break;
        };
        if votes < params.min_votes {
            break;
        }

        // Collect inliers by perpendicular distance to the (θ, ρ) line.
        let (nx, ny) = (theta.cos(), theta.sin());
        let mut inlier_idx: Vec<usize> = Vec::new();
        for (i, p) in remaining.iter().enumerate() {
            let perp = p.x * nx + p.y * ny - rho;
            if perp.abs() <= params.dist_tol_mm {
                inlier_idx.push(i);
            }
        }
        if inlier_idx.len() < params.min_votes {
            // Degenerate — drop these points so we make progress.
            remove_indices(&mut remaining, &inlier_idx);
            continue;
        }

        let inliers: Vec<Vec2> = inlier_idx.iter().map(|&i| remaining[i]).collect();
        // Refit the line to its inliers, then cut it into gap-free segments.
        let (centroid, dir) = fit_line(&inliers);
        for seg in split_into_segments(&inliers, centroid, dir, params) {
            walls.push(seg);
        }

        remove_indices(&mut remaining, &inlier_idx);
    }

    Ok(AsBuiltResult {
        walls,
        floor_elevation_m: floor,
        ceiling_elevation_m: ceiling,
        wall_height_m: (ceiling - floor).max(0.0),
        band_points,
        voxels: voxel_count,
    })
}

// ---------------------------------------------------------------------------
// Voxel downsample (plan)
// ---------------------------------------------------------------------------

#[allow(
    clippy::cast_possible_truncation,
    clippy::cast_possible_wrap,
    clippy::cast_precision_loss,
)]
fn voxel_downsample(points: &[Vec2], voxel_mm: f32) -> Vec<Vec2> {
    use std::collections::HashMap;
    if voxel_mm <= 0.0 {
        return points.to_vec();
    }
    // Accumulate a centroid per occupied cell so the kept point sits on the
    // wall face rather than on an arbitrary cell corner.
    let mut cells: HashMap<(i64, i64), (Vec2, u32)> = HashMap::new();
    for &p in points {
        let key = (
            (p.x / voxel_mm).floor() as i64,
            (p.y / voxel_mm).floor() as i64,
        );
        let e = cells.entry(key).or_insert((Vec2::ZERO, 0));
        e.0 += p;
        e.1 += 1;
    }
    let mut out: Vec<Vec2> = cells
        .into_iter()
        .map(|(_, (sum, n))| sum / n as f32)
        .collect();
    // Deterministic order — HashMap iteration is not stable across runs.
    out.sort_by(|a, b| {
        a.x.partial_cmp(&b.x)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then(a.y.partial_cmp(&b.y).unwrap_or(std::cmp::Ordering::Equal))
    });
    out
}

// ---------------------------------------------------------------------------
// Hough accumulator
// ---------------------------------------------------------------------------

/// Vote every point across all angle bins and return the (θ, ρ, votes) of the
/// strongest cell. θ is the line-normal angle in radians, ρ in millimetres.
#[allow(
    clippy::cast_possible_truncation,
    clippy::cast_precision_loss,
    clippy::cast_sign_loss,
)]
fn strongest_line(points: &[Vec2], params: &WallDetectParams) -> Option<(f32, f32, usize)> {
    let n_theta = params.angle_steps;

    // Conservative ρ bounds. ρ = x·cosθ + z·sinθ peaks at |p|·√2 (a far
    // corner viewed at 45°), so the band must be √2 wider than the bbox or
    // out-of-range points pile into the clamped end bin and forge a phantom
    // high-vote diagonal line.
    let mut max_abs = 0.0_f32;
    for p in points {
        max_abs = max_abs.max(p.x.abs()).max(p.y.abs());
    }
    let rho_extent = max_abs * std::f32::consts::SQRT_2;
    let rho_min = -rho_extent;
    let rho_span = 2.0 * rho_extent;
    if rho_span <= 0.0 {
        return None;
    }
    let n_rho = (rho_span / params.rho_res_mm).ceil() as usize + 1;

    // Precompute (cos, sin) for each angle bin across [0, π).
    let mut cs: Vec<(f32, f32)> = Vec::with_capacity(n_theta);
    for t in 0..n_theta {
        let theta = std::f32::consts::PI * (t as f32) / (n_theta as f32);
        cs.push((theta.cos(), theta.sin()));
    }

    let mut acc = vec![0u32; n_theta * n_rho];
    for p in points {
        for (t, &(c, s)) in cs.iter().enumerate() {
            let rho = p.x * c + p.y * s;
            let bin = ((rho - rho_min) / params.rho_res_mm).round() as usize;
            let bin = bin.min(n_rho - 1);
            acc[t * n_rho + bin] += 1;
        }
    }

    // Strongest cell, first-wins on ties for determinism.
    let mut best = 0u32;
    let mut best_t = 0usize;
    let mut best_b = 0usize;
    for t in 0..n_theta {
        for b in 0..n_rho {
            let v = acc[t * n_rho + b];
            if v > best {
                best = v;
                best_t = t;
                best_b = b;
            }
        }
    }
    if best == 0 {
        return None;
    }

    let theta = std::f32::consts::PI * (best_t as f32) / (n_theta as f32);
    let rho = rho_min + (best_b as f32) * params.rho_res_mm;
    Some((theta, rho, best as usize))
}

// ---------------------------------------------------------------------------
// Line fit + segment splitting
// ---------------------------------------------------------------------------

/// PCA line fit: returns (centroid, unit direction along the major axis).
#[allow(clippy::cast_precision_loss)]
fn fit_line(points: &[Vec2]) -> (Vec2, Vec2) {
    let n = points.len() as f32;
    let centroid = points.iter().fold(Vec2::ZERO, |a, &p| a + p) / n;
    let (mut sxx, mut sxy, mut syy) = (0.0_f32, 0.0_f32, 0.0_f32);
    for &p in points {
        let d = p - centroid;
        sxx += d.x * d.x;
        sxy += d.x * d.y;
        syy += d.y * d.y;
    }
    // Major-axis angle of the 2×2 covariance.
    let angle = 0.5 * (2.0 * sxy).atan2(sxx - syy);
    let dir = Vec2::new(angle.cos(), angle.sin());
    (centroid, dir)
}

/// Project inliers onto the fitted line, sort, split at gaps, and emit each
/// run that clears the minimum length as a centreline segment.
#[allow(clippy::cast_precision_loss)]
fn split_into_segments(
    inliers: &[Vec2],
    centroid: Vec2,
    dir: Vec2,
    params: &WallDetectParams,
) -> Vec<AsBuiltWall> {
    // (signed distance along dir, signed perpendicular distance).
    let perp = Vec2::new(-dir.y, dir.x);
    let mut proj: Vec<(f32, f32)> = inliers
        .iter()
        .map(|&p| {
            let d = p - centroid;
            (d.dot(dir), d.dot(perp))
        })
        .collect();
    proj.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal));

    let mut walls = Vec::new();
    let mut run_start = 0usize;
    for i in 1..=proj.len() {
        let split = i == proj.len() || (proj[i].0 - proj[i - 1].0) > params.max_gap_mm;
        if split {
            let run = &proj[run_start..i];
            run_start = i;
            if run.len() < params.min_votes {
                continue;
            }
            let t0 = run[0].0;
            let t1 = run[run.len() - 1].0;
            if (t1 - t0) < params.min_wall_len_mm {
                continue;
            }
            // Centre the segment in the perpendicular direction so the
            // centreline runs through the supporting points.
            let perp_mean = run.iter().map(|r| r.1).sum::<f32>() / run.len() as f32;
            let (mut perp_lo, mut perp_hi) = (f32::INFINITY, f32::NEG_INFINITY);
            for r in run {
                perp_lo = perp_lo.min(r.1);
                perp_hi = perp_hi.max(r.1);
            }
            let base = centroid + perp * perp_mean;
            let start = base + dir * t0;
            let end = base + dir * t1;
            let thickness = (perp_hi - perp_lo).max(75.0);
            walls.push(AsBuiltWall {
                start_mm: start,
                end_mm: end,
                thickness_mm: thickness,
                point_count: run.len(),
            });
        }
    }
    walls
}

/// Remove the given (unsorted) indices from `v` in O(n).
fn remove_indices(v: &mut Vec<Vec2>, idx: &[usize]) {
    let mut drop = vec![false; v.len()];
    for &i in idx {
        if i < drop.len() {
            drop[i] = true;
        }
    }
    let mut keep = 0usize;
    for i in 0..v.len() {
        if !drop[i] {
            v[keep] = v[i];
            keep += 1;
        }
    }
    v.truncate(keep);
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    /// Build a rectangular room's wall point cloud (metres, y up).
    /// Corners (x0,z0)..(x1,z1), walls sampled every `step` m along their
    /// length and every `step` m vertically from floor..ceiling.
    fn rect_room(
        x0: f32, z0: f32, x1: f32, z1: f32,
        ceiling: f32, step: f32,
    ) -> Vec<Vec3> {
        let mut pts = Vec::new();
        let mut y = 0.0;
        while y <= ceiling + 1e-3 {
            // South (z0) and north (z1) walls run along x.
            let mut x = x0;
            while x <= x1 + 1e-3 {
                pts.push(Vec3::new(x, y, z0));
                pts.push(Vec3::new(x, y, z1));
                x += step;
            }
            // West (x0) and east (x1) walls run along z.
            let mut z = z0;
            while z <= z1 + 1e-3 {
                pts.push(Vec3::new(x0, y, z));
                pts.push(Vec3::new(x1, y, z));
                z += step;
            }
            y += step;
        }
        pts
    }

    fn nearly(a: f32, b: f32, tol: f32) -> bool {
        (a - b).abs() <= tol
    }

    #[test]
    fn empty_cloud_errors() {
        let err = detect_walls(&[], &WallDetectParams::default()).unwrap_err();
        assert!(matches!(err, AsBuiltError::EmptyCloud));
    }

    #[test]
    fn detects_four_walls_of_a_rectangular_room() {
        // 6 m × 4 m room, 2.7 m ceiling.
        let cloud = rect_room(0.0, 0.0, 6.0, 4.0, 2.7, 0.1);
        let res = detect_walls(&cloud, &WallDetectParams::default()).unwrap();

        assert!(nearly(res.floor_elevation_m, 0.0, 1e-3));
        assert!(nearly(res.wall_height_m, 2.7, 0.05));
        assert_eq!(
            res.walls.len(),
            4,
            "expected 4 walls, got {}: {:#?}",
            res.walls.len(),
            res.walls
        );

        // Total centreline length ≈ perimeter (2*(6+4) = 20 m = 20_000 mm).
        let total: f32 = res.walls.iter().map(AsBuiltWall::length_mm).sum();
        assert!(
            nearly(total, 20_000.0, 1_200.0),
            "perimeter {total} mm off expected 20000"
        );
    }

    #[test]
    fn wall_with_a_doorway_gap_splits_in_two() {
        // One long wall along z=0 from x=0..6, but a 1 m doorway gap at x=2.5..3.5.
        let mut cloud = Vec::new();
        let mut y = 0.0;
        while y <= 2.7 {
            let mut x = 0.0;
            while x <= 6.0 {
                if !(2.5..=3.5).contains(&x) {
                    cloud.push(Vec3::new(x, y, 0.0));
                }
                x += 0.1;
            }
            y += 0.1;
        }
        // A perpendicular wall so a floor exists and detection has scale.
        let mut z = 0.0;
        while z <= 4.0 {
            let mut yy = 0.0;
            while yy <= 2.7 {
                cloud.push(Vec3::new(0.0, yy, z));
                yy += 0.1;
            }
            z += 0.1;
        }

        let res = detect_walls(&cloud, &WallDetectParams::default()).unwrap();
        // The z=0 line should be two segments; plus the x=0 wall = 3 total.
        let along_z0: Vec<_> = res
            .walls
            .iter()
            .filter(|w| nearly(w.start_mm.y, 0.0, 250.0) && nearly(w.end_mm.y, 0.0, 250.0))
            .collect();
        assert_eq!(
            along_z0.len(),
            2,
            "doorway should split the wall in two, got {}",
            along_z0.len()
        );
    }

    #[test]
    fn band_filter_excludes_floor_and_ceiling_clutter() {
        // Walls plus a dense floor slab and ceiling slab that must NOT be
        // detected as walls (they're horizontal, outside the band anyway).
        let mut cloud = rect_room(0.0, 0.0, 5.0, 5.0, 2.7, 0.1);
        let mut x = 0.0;
        while x <= 5.0 {
            let mut z = 0.0;
            while z <= 5.0 {
                cloud.push(Vec3::new(x, 0.0, z)); // floor
                cloud.push(Vec3::new(x, 2.7, z)); // ceiling
                z += 0.2;
            }
            x += 0.2;
        }
        let res = detect_walls(&cloud, &WallDetectParams::default()).unwrap();
        assert_eq!(res.walls.len(), 4, "got {:#?}", res.walls);
    }

    #[test]
    fn no_points_in_band_errors() {
        // A flat floor only — nothing in the 0.5..1.8 m band.
        let mut cloud = Vec::new();
        let mut x = 0.0;
        while x <= 5.0 {
            cloud.push(Vec3::new(x, 0.0, 0.0));
            x += 0.1;
        }
        let err = detect_walls(&cloud, &WallDetectParams::default()).unwrap_err();
        assert!(matches!(err, AsBuiltError::EmptyBand(..)));
    }
}
