//! As-built elevation projection from an exterior LiDAR point cloud.
//!
//! An elevation is what you see looking horizontally at one face of the
//! building. The detection mirrors [`crate::aswall`] but slices *vertically*
//! per facade instead of horizontally:
//!
//! 1. Take the plan bbox of the whole cloud. For each cardinal facade, keep the
//!    points within `facade_depth` of that face.
//! 2. Project them onto the facade plane: a horizontal axis `h` along the wall
//!    and a vertical axis `v` measured up from the ground datum.
//! 3. Bin the plane into a cell grid; a cell is "wall" if it holds points.
//! 4. The facade extent is the bounding rectangle of the projected points.
//! 5. **Openings** (windows, doors) are empty cells that sit *below the
//!    roofline* of their column — i.e. holes in an otherwise solid wall.
//!    Connected empty cells are grouped; each group's bounding box, if big
//!    enough, is an opening. Doors reach the ground; windows float.
//!
//! Like the rest of the as-built stack this is an intentionally crude
//! bootstrap. It assumes near-rectangular facades (matching the rect-only
//! elevation drawing path) and one ground datum. Gable/roof-profile tracing is
//! future work.
//!
//! **Units:** input points are metres with **y up** (x east, z north). Output
//! plane coordinates are millimetres with the origin at the facade's
//! bottom-left.

use glam::{Vec2, Vec3};

use crate::mesh::M_TO_MM;

/// The four cardinal building faces.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Facade {
    /// Faces −Z (front, looking north).
    South,
    /// Faces +Z (back, looking south).
    North,
    /// Faces +X (right, looking west).
    East,
    /// Faces −X (left, looking east).
    West,
}

impl Facade {
    /// All four facades in a stable order.
    #[must_use]
    pub const fn all() -> [Facade; 4] {
        [Facade::South, Facade::North, Facade::East, Facade::West]
    }

    /// Lowercase tag used in filenames / JSON (`south`, `north`, …).
    #[must_use]
    pub const fn tag(self) -> &'static str {
        match self {
            Facade::South => "south",
            Facade::North => "north",
            Facade::East => "east",
            Facade::West => "west",
        }
    }
}

/// One detected opening (window or door) in a facade.
#[derive(Debug, Clone)]
pub struct AsBuiltOpening {
    /// Bottom-left corner in plane millimetres (h right, v up).
    pub min_mm: Vec2,
    /// Top-right corner in plane millimetres.
    pub max_mm: Vec2,
    /// How many empty cells formed the opening.
    pub cell_count: usize,
}

impl AsBuiltOpening {
    /// Opening width in millimetres.
    #[must_use]
    pub fn width_mm(&self) -> f32 {
        self.max_mm.x - self.min_mm.x
    }
    /// Opening height in millimetres.
    #[must_use]
    pub fn height_mm(&self) -> f32 {
        self.max_mm.y - self.min_mm.y
    }
    /// True when the opening reaches the ground datum (likely a door).
    #[must_use]
    pub fn is_door(&self) -> bool {
        self.min_mm.y <= 1.0
    }
}

/// A projected as-built elevation for one facade.
#[derive(Debug, Clone)]
pub struct AsBuiltElevation {
    pub facade: Facade,
    /// Facade width (millimetres).
    pub width_mm: f32,
    /// Facade height above the ground datum (millimetres).
    pub height_mm: f32,
    /// Bounding-rectangle outline, CCW from the bottom-left (plane mm).
    pub outline_mm: Vec<Vec2>,
    /// Detected openings, sorted bottom-left first.
    pub openings: Vec<AsBuiltOpening>,
    /// Ground datum (metres, original cloud frame).
    pub ground_elevation_m: f32,
    /// Highest point on this facade (metres, original cloud frame).
    pub ridge_elevation_m: f32,
    /// Projected points used for this facade.
    pub facade_points: usize,
}

/// Tunable parameters for elevation projection.
#[derive(Debug, Clone)]
pub struct ElevationParams {
    /// How deep into the building to grab facade points (metres).
    pub facade_depth_m: f32,
    /// Cell size for the occupancy grid (millimetres).
    pub bin_mm: f32,
    /// Smallest opening edge we will emit (millimetres) — filters scan noise.
    pub min_opening_mm: f32,
}

impl Default for ElevationParams {
    fn default() -> Self {
        Self {
            facade_depth_m: 0.6,
            bin_mm: 100.0,
            min_opening_mm: 400.0,
        }
    }
}

/// Errors the elevation projector can produce.
#[derive(Debug, thiserror::Error)]
pub enum ElevationError {
    #[error("point cloud is empty")]
    EmptyCloud,
    #[error("no points fell within {0:.2} m of the {1} facade")]
    EmptyFacade(f32, &'static str),
    #[error("facade collapsed to fewer than 2 grid columns — too sparse")]
    TooSparse,
    #[error("bin_mm must be > 0")]
    BadBin,
}

/// Project all four cardinal elevations from a single exterior cloud, sharing
/// one ground datum (the cloud's lowest point).
///
/// # Errors
/// Propagates [`ElevationError`] from any facade that has too few points.
pub fn project_all_elevations(
    points: &[Vec3],
    params: &ElevationParams,
) -> Result<Vec<AsBuiltElevation>, ElevationError> {
    if points.is_empty() {
        return Err(ElevationError::EmptyCloud);
    }
    let floor = points.iter().fold(f32::INFINITY, |a, p| a.min(p.y));
    Facade::all()
        .into_iter()
        .map(|f| project_elevation(points, f, floor, params))
        .collect()
}

/// Project a single facade. `ground_floor_m` is the shared ground datum (use
/// the cloud's minimum y when in doubt).
///
/// # Errors
/// Returns [`ElevationError`] when the cloud is empty, the facade slice is
/// empty, or the grid is degenerate.
#[allow(
    clippy::cast_possible_truncation,
    clippy::cast_precision_loss,
    clippy::cast_sign_loss,
    clippy::cast_possible_wrap,
)]
pub fn project_elevation(
    points: &[Vec3],
    facade: Facade,
    ground_floor_m: f32,
    params: &ElevationParams,
) -> Result<AsBuiltElevation, ElevationError> {
    if points.is_empty() {
        return Err(ElevationError::EmptyCloud);
    }
    if params.bin_mm <= 0.0 {
        return Err(ElevationError::BadBin);
    }

    // Plan bbox (metres) of the whole cloud.
    let (mut min_x, mut max_x) = (f32::INFINITY, f32::NEG_INFINITY);
    let (mut min_z, mut max_z) = (f32::INFINITY, f32::NEG_INFINITY);
    for p in points {
        min_x = min_x.min(p.x);
        max_x = max_x.max(p.x);
        min_z = min_z.min(p.z);
        max_z = max_z.max(p.z);
    }

    let depth = params.facade_depth_m;
    // Select facade points and map each to (h, v) plane metres.
    let mut plane: Vec<Vec2> = Vec::new();
    let mut ridge = f32::NEG_INFINITY;
    for p in points {
        let keep_h = match facade {
            Facade::South => (p.z <= min_z + depth).then_some(p.x - min_x),
            Facade::North => (p.z >= max_z - depth).then_some(p.x - min_x),
            Facade::East => (p.x >= max_x - depth).then_some(p.z - min_z),
            Facade::West => (p.x <= min_x + depth).then_some(p.z - min_z),
        };
        if let Some(h) = keep_h {
            let v = p.y - ground_floor_m;
            plane.push(Vec2::new(h * M_TO_MM, v * M_TO_MM));
            ridge = ridge.max(p.y);
        }
    }
    if plane.is_empty() {
        return Err(ElevationError::EmptyFacade(depth, facade.tag()));
    }
    let facade_points = plane.len();

    // Facade extent.
    let (mut h_max, mut v_max) = (0.0_f32, 0.0_f32);
    for p in &plane {
        h_max = h_max.max(p.x);
        v_max = v_max.max(p.y);
    }
    let width_mm = h_max;
    let height_mm = v_max;

    // Occupancy grid.
    let nh = (h_max / params.bin_mm).ceil() as usize + 1;
    let nv = (v_max / params.bin_mm).ceil() as usize + 1;
    if nh < 2 || nv < 2 {
        return Err(ElevationError::TooSparse);
    }
    let mut occ = vec![false; nh * nv];
    for p in &plane {
        let hi = ((p.x / params.bin_mm) as usize).min(nh - 1);
        let vi = ((p.y / params.bin_mm) as usize).min(nv - 1);
        occ[hi * nv + vi] = true;
    }

    // Roofline per column: highest occupied row, or -1 for empty columns.
    let mut roofline = vec![-1_i32; nh];
    for hi in 0..nh {
        for vi in (0..nv).rev() {
            if occ[hi * nv + vi] {
                roofline[hi] = vi as i32;
                break;
            }
        }
    }

    // Candidate opening cells: empty, and strictly below their column roofline.
    let mut candidate = vec![false; nh * nv];
    for hi in 0..nh {
        let rh = roofline[hi];
        if rh < 0 {
            continue;
        }
        for vi in 0..rh as usize {
            if !occ[hi * nv + vi] {
                candidate[hi * nv + vi] = true;
            }
        }
    }

    // Connected components (4-connectivity) over candidate cells.
    let openings = extract_openings(&candidate, nh, nv, params.bin_mm, params.min_opening_mm);

    let outline_mm = vec![
        Vec2::new(0.0, 0.0),
        Vec2::new(width_mm, 0.0),
        Vec2::new(width_mm, height_mm),
        Vec2::new(0.0, height_mm),
    ];

    Ok(AsBuiltElevation {
        facade,
        width_mm,
        height_mm,
        outline_mm,
        openings,
        ground_elevation_m: ground_floor_m,
        ridge_elevation_m: ridge,
        facade_points,
    })
}

// ---------------------------------------------------------------------------
// Connected-component opening extraction
// ---------------------------------------------------------------------------

#[allow(clippy::cast_precision_loss)]
fn extract_openings(
    candidate: &[bool],
    nh: usize,
    nv: usize,
    bin_mm: f32,
    min_opening_mm: f32,
) -> Vec<AsBuiltOpening> {
    let mut visited = vec![false; nh * nv];
    let mut openings = Vec::new();
    let mut stack: Vec<(usize, usize)> = Vec::new();

    for sh in 0..nh {
        for sv in 0..nv {
            let idx = sh * nv + sv;
            if !candidate[idx] || visited[idx] {
                continue;
            }
            // Flood-fill this component, tracking its cell bbox.
            let (mut h_lo, mut h_hi) = (sh, sh);
            let (mut v_lo, mut v_hi) = (sv, sv);
            let mut count = 0usize;
            stack.clear();
            stack.push((sh, sv));
            visited[idx] = true;
            while let Some((h, v)) = stack.pop() {
                count += 1;
                h_lo = h_lo.min(h);
                h_hi = h_hi.max(h);
                v_lo = v_lo.min(v);
                v_hi = v_hi.max(v);
                let neighbours = [
                    (h.wrapping_sub(1), v, h > 0),
                    (h + 1, v, h + 1 < nh),
                    (h, v.wrapping_sub(1), v > 0),
                    (h, v + 1, v + 1 < nv),
                ];
                for (nhh, nvv, ok) in neighbours {
                    if !ok {
                        continue;
                    }
                    let nidx = nhh * nv + nvv;
                    if candidate[nidx] && !visited[nidx] {
                        visited[nidx] = true;
                        stack.push((nhh, nvv));
                    }
                }
            }

            // Cell bbox → mm. A run of cells [lo, hi] spans (hi-lo+1) bins.
            let w = (h_hi - h_lo + 1) as f32 * bin_mm;
            let ht = (v_hi - v_lo + 1) as f32 * bin_mm;
            if w >= min_opening_mm && ht >= min_opening_mm {
                openings.push(AsBuiltOpening {
                    min_mm: Vec2::new(h_lo as f32 * bin_mm, v_lo as f32 * bin_mm),
                    max_mm: Vec2::new((h_hi + 1) as f32 * bin_mm, (v_hi + 1) as f32 * bin_mm),
                    cell_count: count,
                });
            }
        }
    }

    // Stable order: bottom-left first.
    openings.sort_by(|a, b| {
        a.min_mm
            .x
            .partial_cmp(&b.min_mm.x)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then(a.min_mm.y.partial_cmp(&b.min_mm.y).unwrap_or(std::cmp::Ordering::Equal))
    });
    openings
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    /// Build a single south-facing wall (z=0 plane) as a point grid in metres,
    /// width `w` × height `h`, sampled every `step`, punching out the given
    /// rectangular openings (h0,v0,h1,v1 in metres).
    fn wall_with_openings(
        w: f32, h: f32, step: f32, openings: &[(f32, f32, f32, f32)],
    ) -> Vec<Vec3> {
        let mut pts = Vec::new();
        let mut x = 0.0;
        while x <= w + 1e-6 {
            let mut y = 0.0;
            while y <= h + 1e-6 {
                let in_opening = openings.iter().any(|&(h0, v0, h1, v1)| {
                    x > h0 && x < h1 && y > v0 && y < v1
                });
                if !in_opening {
                    pts.push(Vec3::new(x, y, 0.0));
                }
                y += step;
            }
            x += step;
        }
        pts
    }

    fn nearly(a: f32, b: f32, tol: f32) -> bool {
        (a - b).abs() <= tol
    }

    #[test]
    fn empty_cloud_errors() {
        let err = project_all_elevations(&[], &ElevationParams::default()).unwrap_err();
        assert!(matches!(err, ElevationError::EmptyCloud));
    }

    #[test]
    fn blank_wall_has_no_openings() {
        let wall = wall_with_openings(6.0, 2.7, 0.1, &[]);
        let e = project_elevation(&wall, Facade::South, 0.0, &ElevationParams::default()).unwrap();
        assert!(nearly(e.width_mm, 6000.0, 100.0), "width {}", e.width_mm);
        assert!(nearly(e.height_mm, 2700.0, 100.0), "height {}", e.height_mm);
        assert_eq!(e.openings.len(), 0, "got {:#?}", e.openings);
    }

    #[test]
    fn detects_a_window_and_a_door() {
        // 6 m × 2.7 m wall. Window 1 m² floating at (1..2, 1..2).
        // Door 0.9 m × 2.1 m on the ground at (3.5..4.4, ground..2.1) — the
        // bottom edge dips below 0 so the door reaches the ground datum (a real
        // doorway has no threshold returns).
        let wall = wall_with_openings(
            6.0, 2.7, 0.05,
            &[(1.0, 1.0, 2.0, 2.0), (3.5, -0.1, 4.4, 2.1)],
        );
        let e = project_elevation(&wall, Facade::South, 0.0, &ElevationParams::default()).unwrap();
        assert_eq!(e.openings.len(), 2, "got {:#?}", e.openings);

        // Sorted by h: window first (h≈1000), door second (h≈3500).
        let win = &e.openings[0];
        let door = &e.openings[1];
        assert!(!win.is_door(), "window should float: {win:?}");
        assert!(nearly(win.width_mm(), 1000.0, 250.0), "win w {}", win.width_mm());
        assert!(nearly(win.height_mm(), 1000.0, 250.0), "win h {}", win.height_mm());

        assert!(door.is_door(), "door should reach ground: {door:?}");
        assert!(nearly(door.height_mm(), 2100.0, 250.0), "door h {}", door.height_mm());
        assert!(door.min_mm.x > win.max_mm.x, "door right of window");
    }

    #[test]
    fn projects_all_four_facades_of_a_box() {
        // A closed box: 4 walls, 8 m (x) × 5 m (z) × 2.7 m tall.
        let mut pts = Vec::new();
        let step = 0.1;
        let mut x = 0.0;
        while x <= 8.0 + 1e-6 {
            let mut y = 0.0;
            while y <= 2.7 + 1e-6 {
                pts.push(Vec3::new(x, y, 0.0)); // south
                pts.push(Vec3::new(x, y, 5.0)); // north
                y += step;
            }
            x += step;
        }
        let mut z = 0.0;
        while z <= 5.0 + 1e-6 {
            let mut y = 0.0;
            while y <= 2.7 + 1e-6 {
                pts.push(Vec3::new(0.0, y, z)); // west
                pts.push(Vec3::new(8.0, y, z)); // east
                y += step;
            }
            z += step;
        }

        let els = project_all_elevations(&pts, &ElevationParams::default()).unwrap();
        assert_eq!(els.len(), 4);
        for e in &els {
            let expect_w = match e.facade {
                Facade::South | Facade::North => 8000.0,
                Facade::East | Facade::West => 5000.0,
            };
            assert!(
                nearly(e.width_mm, expect_w, 150.0),
                "{:?} width {} expected {expect_w}",
                e.facade, e.width_mm
            );
            assert!(nearly(e.height_mm, 2700.0, 150.0));
        }
    }

    #[test]
    fn opening_on_east_facade_uses_z_as_horizontal() {
        // A box whose east wall (x=8) carries one window; detection on the
        // east facade must measure the opening along z, not x.
        let mut pts = Vec::new();
        let step = 0.05;
        // South + north walls (no openings) to give the box depth.
        let mut x = 0.0;
        while x <= 8.0 + 1e-6 {
            let mut y = 0.0;
            while y <= 2.7 + 1e-6 {
                pts.push(Vec3::new(x, y, 0.0));
                pts.push(Vec3::new(x, y, 5.0));
                y += step;
            }
            x += step;
        }
        // West wall solid; east wall with a window at z 2..3, y 1..2.
        let mut z = 0.0;
        while z <= 5.0 + 1e-6 {
            let mut y = 0.0;
            while y <= 2.7 + 1e-6 {
                pts.push(Vec3::new(0.0, y, z));
                let win = z > 2.0 && z < 3.0 && y > 1.0 && y < 2.0;
                if !win {
                    pts.push(Vec3::new(8.0, y, z));
                }
                y += step;
            }
            z += step;
        }

        let e = project_elevation(&pts, Facade::East, 0.0, &ElevationParams::default()).unwrap();
        assert!(nearly(e.width_mm, 5000.0, 150.0), "east width {}", e.width_mm);
        assert_eq!(e.openings.len(), 1, "got {:#?}", e.openings);
        let win = &e.openings[0];
        assert!(!win.is_door());
        // Window centred around z≈2500 mm horizontally.
        assert!(
            nearly((win.min_mm.x + win.max_mm.x) / 2.0, 2500.0, 250.0),
            "window h-centre {}",
            (win.min_mm.x + win.max_mm.x) / 2.0
        );
    }
}
