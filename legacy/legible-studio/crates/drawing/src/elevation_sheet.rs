//! Elevation-sheet generator (one drawing per cardinal direction).
//!
//! Port of `ArchEngine_kernel/scripts/generate_elevations.py` (855 LOC),
//! scoped to the permit-drawing critical path: wall outline + openings
//! (doors/windows projected onto the elevation plane) + simple gable roof
//! profile + grade line + title. The Python's optional layers (materials,
//! detailed level markers, surface-based roof projection) are deferred.

use std::fmt::Write as _;

use glam::{Vec2, Vec3};

/// Which cardinal direction the viewer is looking from.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Direction {
    North,
    South,
    East,
    West,
}

impl Direction {
    fn as_str(self) -> &'static str {
        match self {
            Direction::North => "north",
            Direction::South => "south",
            Direction::East => "east",
            Direction::West => "west",
        }
    }
    fn label(self) -> &'static str {
        match self {
            Direction::North => "NORTH",
            Direction::South => "SOUTH",
            Direction::East => "EAST",
            Direction::West => "WEST",
        }
    }
    /// All four cardinal directions in the conventional order.
    pub const ALL: [Direction; 4] = [
        Direction::North,
        Direction::South,
        Direction::East,
        Direction::West,
    ];
}

/// Minimal wall description for elevation projection: centreline + height,
/// plus the floor `base` elevation (mm) the wall sits on — non-zero for upper
/// storeys so the elevation stacks.
#[derive(Debug, Clone)]
pub struct ElevationWallInput {
    pub start: Vec3,
    pub end: Vec3,
    pub height: f32,
    pub base: f32,
}

/// Door or window on a specific wall.
#[derive(Debug, Clone)]
pub struct ElevationOpeningInput {
    pub wall_index: usize,
    /// Distance along wall from start to opening centre, in mm.
    pub offset: f32,
    pub width: f32,
    pub height: f32,
    pub sill_height: f32,
    pub is_door: bool,
}

/// Building-level inputs for elevation generation.
#[derive(Debug, Clone, Default)]
pub struct ElevationInput {
    /// Building width in mm (X extent — used for South/North projection).
    pub width: f32,
    /// Building depth in mm (Z extent — used for East/West projection).
    pub depth: f32,
    pub walls: Vec<ElevationWallInput>,
    pub openings: Vec<ElevationOpeningInput>,
    /// If > 0, draw a gable roof of this ridge height above the wall plate
    /// (mm). 0 disables.
    pub gable_ridge_above_plate: f32,
    /// True if the ridge runs along the building **width** (X) — then the
    /// East/West faces are gable ends (triangle) and North/South are eave
    /// sides (sloped band). False = ridge along depth, ends face N/S.
    pub ridge_along_width: bool,
    /// Hip roof: eave sides render as a trapezoid (the slope narrows to the
    /// inset ridge) rather than a gable's rectangle band. Ends stay triangles.
    pub hip: bool,
    /// Elevations (mm) at which to draw a horizontal floor line — the base of
    /// each storey above grade, so a multi-storey elevation reads as stacked.
    pub floor_lines: Vec<f32>,
    /// Irregular building footprint as CCW `(x, z)` mm vertices. When
    /// non-empty, the renderer decomposes it into axis-aligned wings and
    /// overlays a per-wing hip roof silhouette so the elevation reads as a
    /// stepped L/T/U/cross instead of a single rectangle.
    pub footprint_polygon_mm: Vec<(f32, f32)>,
    /// Roof pitch (rise/run); only used by the polygon path to size each
    /// wing's ridge height. Defaults to 6:12 if 0.
    pub roof_pitch: f32,
    /// Eave/rake overhang projected beyond the wall (mm). 0 = roof flush with
    /// the wall (legacy). Drives how far the roof silhouette extends past the
    /// wall horizontally and how far the eave/fascia drops below the plate.
    pub eave_overhang_mm: f32,
}

struct WallSegment {
    start_x: f32,
    end_x: f32,
    top_y: f32,
}

/// Decompose an axis-aligned CCW rectilinear polygon into axis-aligned
/// rectangular wings by sweeping along one axis. `by_x = true` sweeps in x
/// (yields rects spanning consecutive unique x values); `by_x = false` sweeps
/// in z. Returns `((x0, z0), (x1, z1))` pairs.
#[allow(clippy::many_single_char_names)]
fn decompose_rectilinear(poly: &[(f32, f32)], by_x: bool) -> Vec<((f32, f32), (f32, f32))> {
    if poly.len() < 4 {
        return Vec::new();
    }
    let key = |p: &(f32, f32)| if by_x { p.0 } else { p.1 };
    let mut keys: Vec<f32> = poly.iter().map(key).collect();
    keys.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    keys.dedup_by(|a, b| (*a - *b).abs() < 0.01);
    let mut rects = Vec::new();
    for w in keys.windows(2) {
        let (k0, k1) = (w[0], w[1]);
        let km = (k0 + k1) * 0.5;
        let crossings = perpendicular_crossings(poly, km, by_x);
        // Each `(in, out)` pair marks one interior strip.
        for chunk in crossings.chunks(2) {
            if chunk.len() == 2 {
                let (a, b) = (chunk[0], chunk[1]);
                if by_x {
                    rects.push(((k0, a), (k1, b)));
                } else {
                    rects.push(((a, k0), (b, k1)));
                }
            }
        }
    }
    rects
}

/// For an axis-aligned rectilinear polygon, find the perpendicular-axis
/// coordinates where a sweep line at `coord` along the chosen axis enters
/// or leaves the polygon interior. `by_x = true` means the sweep line is at
/// `x = coord` and we look at z-crossings on horizontal edges.
fn perpendicular_crossings(poly: &[(f32, f32)], coord: f32, by_x: bool) -> Vec<f32> {
    let mut out = Vec::new();
    let n = poly.len();
    for i in 0..n {
        let a = poly[i];
        let b = poly[(i + 1) % n];
        let (parallel_a, parallel_b, span_a, span_b, perp_a) = if by_x {
            // sweep along x → look at horizontal edges (constant z), use x-span.
            (a.1, b.1, a.0, b.0, a.1)
        } else {
            // sweep along z → look at vertical edges (constant x), use z-span.
            (a.0, b.0, a.1, b.1, a.0)
        };
        if (parallel_a - parallel_b).abs() > 0.01 {
            continue; // not a candidate edge for this sweep direction
        }
        let (lo, hi) = if span_a < span_b { (span_a, span_b) } else { (span_b, span_a) };
        if coord > lo - 0.01 && coord < hi + 0.01 {
            out.push(perp_a);
        }
    }
    out.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    out.dedup_by(|a, b| (*a - *b).abs() < 0.01);
    out
}

/// Compute the roof silhouette for an irregular footprint as seen from
/// `dir`. Returns a closed polygon of `(x, y)` vertices in elevation
/// coordinates, walking the wings in order and stepping the roof between
/// them. The first and last vertices sit on the wall plate so the polygon
/// closes into the wall envelope.
#[allow(clippy::many_single_char_names)]
fn polygon_roof_silhouette(
    input: &ElevationInput,
    dir: Direction,
    plate_y: f32,
) -> Vec<(f32, f32)> {
    let pitch = if input.roof_pitch > 0.0 { input.roof_pitch } else { 0.5 };
    // For N/S we sweep along x; for E/W along z. The sweep axis becomes the
    // elevation's x-axis.
    let by_x = matches!(dir, Direction::North | Direction::South);
    let rects = decompose_rectilinear(&input.footprint_polygon_mm, by_x);
    if rects.is_empty() {
        return Vec::new();
    }
    // Building extent on the sweep axis — for North/East we mirror.
    let extent = if by_x { input.width } else { input.depth };
    let mirror = matches!(dir, Direction::North | Direction::East);
    let map_x = |v: f32| if mirror { extent - v } else { v };

    // Per-wing silhouette contribution: each wing contributes a trapezoid (if
    // the ridge runs along the view) or a triangle (ridge perpendicular).
    let mut pts: Vec<(f32, f32)> = Vec::with_capacity(rects.len() * 4 + 2);
    // Walk wings in sweep-axis order so the silhouette goes left → right.
    let mut sorted: Vec<_> = rects.iter().collect();
    sorted.sort_by(|a, b| {
        let ka = if by_x { a.0.0 } else { a.0.1 };
        let kb = if by_x { b.0.0 } else { b.0.1 };
        ka.partial_cmp(&kb).unwrap_or(std::cmp::Ordering::Equal)
    });
    let first = sorted.first().expect("non-empty sorted wings");
    let last = sorted.last().expect("non-empty sorted wings");
    let (first_lo, _) = wing_view_extent(first, by_x);
    let (_, last_hi) = wing_view_extent(last, by_x);
    pts.push((map_x(first_lo), plate_y));
    let mut prev_hi: Option<f32> = None;
    for &r in &sorted {
        let (lo, hi) = wing_view_extent(r, by_x);
        // Dip to the plate between adjacent wings whose roofs don't share
        // a continuous ridge (every step transitions through plate level).
        if let Some(p_hi) = prev_hi {
            pts.push((map_x(p_hi), plate_y));
            pts.push((map_x(lo), plate_y));
        }
        let (wing_view_w, wing_depth) = wing_dims(r, by_x);
        let short = wing_view_w.min(wing_depth);
        let ridge = short * 0.5 * pitch;
        // If the view width is the longer axis, the ridge runs ALONG the
        // view → trapezoid (eave side, two ridge vertices). Otherwise the
        // ridge runs INTO the view → triangle (hip end, one peak vertex).
        if wing_view_w > wing_depth + 1.0 {
            let inset = wing_depth * 0.5;
            pts.push((map_x(lo + inset), plate_y + ridge));
            pts.push((map_x(hi - inset), plate_y + ridge));
        } else {
            let mid = (lo + hi) * 0.5;
            pts.push((map_x(mid), plate_y + ridge));
        }
        prev_hi = Some(hi);
    }
    pts.push((map_x(last_hi), plate_y));
    // For mirrored views (North/East) the points come out right-to-left;
    // reverse so the polygon winds CCW in screen space.
    if mirror {
        pts.reverse();
    }
    pts
}

fn wing_view_extent(r: &((f32, f32), (f32, f32)), by_x: bool) -> (f32, f32) {
    if by_x { (r.0.0, r.1.0) } else { (r.0.1, r.1.1) }
}

fn wing_dims(r: &((f32, f32), (f32, f32)), by_x: bool) -> (f32, f32) {
    let dx = r.1.0 - r.0.0;
    let dz = r.1.1 - r.0.1;
    if by_x { (dx, dz) } else { (dz, dx) }
}

struct Opening {
    center_x: f32,
    width: f32,
    bottom_y: f32,
    top_y: f32,
    is_door: bool,
}

fn project_wall(wall: &ElevationWallInput, dir: Direction, input: &ElevationInput) -> WallSegment {
    let (s, e) = (wall.start, wall.end);
    let (mut start_x, mut end_x) = match dir {
        Direction::South | Direction::North => (s.x.min(e.x), s.x.max(e.x)),
        Direction::East | Direction::West => (s.z.min(e.z), s.z.max(e.z)),
    };
    if dir == Direction::North {
        let bw = input.width;
        let (a, b) = (bw - end_x, bw - start_x);
        start_x = a;
        end_x = b;
    } else if dir == Direction::East {
        let bd = input.depth;
        let (a, b) = (bd - end_x, bd - start_x);
        start_x = a;
        end_x = b;
    }
    WallSegment {
        start_x,
        end_x,
        top_y: wall.base + wall.height,
    }
}

/// Building plan bounds `(min_x, max_x, min_z, max_z)` from the walls.
fn building_bounds(input: &ElevationInput) -> (f32, f32, f32, f32) {
    let mut b = (f32::INFINITY, f32::NEG_INFINITY, f32::INFINITY, f32::NEG_INFINITY);
    for w in &input.walls {
        b.0 = b.0.min(w.start.x).min(w.end.x);
        b.1 = b.1.max(w.start.x).max(w.end.x);
        b.2 = b.2.min(w.start.z).min(w.end.z);
        b.3 = b.3.max(w.start.z).max(w.end.z);
    }
    if b.0 > b.1 {
        (0.0, input.width, 0.0, input.depth)
    } else {
        b
    }
}

/// True if `wall` is the perimeter exterior wall facing `dir` — i.e. roughly
/// perpendicular to the view AND sitting on the matching side of the footprint.
/// This is what keeps a south elevation from drawing the *north* wall's and
/// interior partitions' openings.
fn wall_faces(wall: &ElevationWallInput, dir: Direction, b: (f32, f32, f32, f32)) -> bool {
    const T: f32 = 400.0; // mm: a wall-thickness-ish tolerance to the perimeter
    let (min_x, max_x, min_z, max_z) = b;
    let xc = (wall.start.x + wall.end.x) * 0.5;
    let zc = (wall.start.z + wall.end.z) * 0.5;
    let runs_x = (wall.end.x - wall.start.x).abs() >= (wall.end.z - wall.start.z).abs();
    match dir {
        Direction::South => runs_x && (zc - min_z).abs() < T,
        Direction::North => runs_x && (zc - max_z).abs() < T,
        Direction::West => !runs_x && (xc - min_x).abs() < T,
        Direction::East => !runs_x && (xc - max_x).abs() < T,
    }
}

// Drawing math uses s/e for start/end and dx/dz for axis deltas; renaming
// to satisfy clippy::pedantic would obscure the geometry vocabulary.
#[allow(clippy::similar_names, clippy::many_single_char_names)]
fn project_opening(
    op: &ElevationOpeningInput,
    wall: &ElevationWallInput,
    dir: Direction,
    input: &ElevationInput,
) -> Option<Opening> {
    let (s, e) = (wall.start, wall.end);
    let wall_dx = e.x - s.x;
    let wall_dz = e.z - s.z;
    let wall_len = (wall_dx * wall_dx + wall_dz * wall_dz).sqrt();
    if wall_len < 1.0 {
        return None;
    }
    let t = op.offset / wall_len;
    let opening_x = s.x + t * wall_dx;
    let opening_z = s.z + t * wall_dz;

    let mut center_x = match dir {
        Direction::South | Direction::North => opening_x,
        Direction::East | Direction::West => opening_z,
    };
    if dir == Direction::North {
        center_x = input.width - center_x;
    } else if dir == Direction::East {
        center_x = input.depth - center_x;
    }

    // Openings sit on their wall's floor: doors at the floor, windows at their
    // sill, both lifted by the wall's storey base.
    let sill = wall.base + if op.is_door { 0.0 } else { op.sill_height };
    Some(Opening {
        center_x,
        width: op.width,
        bottom_y: sill,
        top_y: sill + op.height,
        is_door: op.is_door,
    })
}

/// Build a [`SliceResult`] from the same projected geometry used by the SVG
/// elevation.  Y is grade-at-zero, positive-up (no flip) so the DXF exports
/// in a conventional engineering coordinate system.
fn elevation_to_slice_result(input: &ElevationInput, dir: Direction) -> crate::SliceResult {
    use crate::primitives::{Line2D, Polyline2D};
    let mut result = crate::SliceResult::default();

    let walls: Vec<WallSegment> = input
        .walls
        .iter()
        .map(|w| project_wall(w, dir, input))
        .filter(|w| (w.end_x - w.start_x).abs() > 1.0)
        .collect();

    let bounds = building_bounds(input);
    let openings: Vec<Opening> = input
        .openings
        .iter()
        .filter_map(|op| {
            let wall = input.walls.get(op.wall_index)?;
            // Only openings on the perimeter wall facing this elevation.
            if !wall_faces(wall, dir, bounds) {
                return None;
            }
            project_opening(op, wall, dir, input)
        })
        .collect();

    // Bounds
    let (mut min_x, mut max_x, mut max_y) =
        (f32::INFINITY, f32::NEG_INFINITY, f32::NEG_INFINITY);
    for w in &walls {
        min_x = min_x.min(w.start_x);
        max_x = max_x.max(w.end_x);
        max_y = max_y.max(w.top_y);
    }
    for op in &openings {
        max_y = max_y.max(op.top_y);
    }
    let max_wall_top = walls.iter().map(|w| w.top_y).fold(0.0_f32, f32::max);
    let gable_top_y = if !input.footprint_polygon_mm.is_empty() {
        let by_x = matches!(dir, Direction::North | Direction::South);
        let rects = decompose_rectilinear(&input.footprint_polygon_mm, by_x);
        let pitch = if input.roof_pitch > 0.0 { input.roof_pitch } else { 0.5 };
        let max_ridge = rects
            .iter()
            .map(|r| {
                let (w, d) = wing_dims(r, by_x);
                w.min(d) * 0.5 * pitch
            })
            .fold(0.0_f32, f32::max);
        max_wall_top + max_ridge
    } else if input.gable_ridge_above_plate > 0.0 {
        max_wall_top + input.gable_ridge_above_plate
    } else {
        0.0
    };
    if gable_top_y > max_y {
        max_y = gable_top_y;
    }
    if !min_x.is_finite() {
        min_x = 0.0;
        max_x = match dir {
            Direction::South | Direction::North => input.width.max(10_000.0),
            Direction::East | Direction::West => input.depth.max(10_000.0),
        };
    }
    if !max_y.is_finite() || max_y <= 0.0 {
        max_y = 2700.0;
    }

    let plate_y = walls.iter().map(|w| w.top_y).fold(0.0_f32, f32::max);

    // Wall envelope
    if !walls.is_empty() {
        result.polylines.push(Polyline2D {
            points: vec![
                Vec2::new(min_x, 0.0),
                Vec2::new(max_x, 0.0),
                Vec2::new(max_x, plate_y),
                Vec2::new(min_x, plate_y),
            ],
            closed: true,
            layer: "A-WALL".into(),
            line_type: "continuous".into(),
            line_weight: 0.35,
            color: Vec3::new(0.9, 0.9, 0.85),
        });
    }

    // Floor lines
    if !walls.is_empty() {
        for &fy in &input.floor_lines {
            if fy > 0.0 && fy < max_y {
                result.lines.push(Line2D {
                    start: Vec2::new(min_x, fy),
                    end: Vec2::new(max_x, fy),
                    layer: "A-FLOR".into(),
                    line_type: "dashed".into(),
                    line_weight: 0.25,
                    color: Vec3::new(0.4, 0.4, 0.4),
                });
            }
        }
    }

    // Roof silhouette
    if !input.footprint_polygon_mm.is_empty() && !walls.is_empty() {
        let silhouette = polygon_roof_silhouette(input, dir, plate_y);
        if !silhouette.is_empty() {
            let pts: Vec<Vec2> = silhouette.iter().map(|(x, y)| Vec2::new(*x, *y)).collect();
            result.polylines.push(Polyline2D {
                points: pts,
                closed: true,
                layer: "A-ROOF".into(),
                line_type: "continuous".into(),
                line_weight: 0.35,
                color: Vec3::new(0.5, 0.5, 0.5),
            });
        }
    } else if input.gable_ridge_above_plate > 0.0 && !walls.is_empty() {
        let ridge_y = plate_y + input.gable_ridge_above_plate;
        let is_gable_end = match dir {
            Direction::East | Direction::West => input.ridge_along_width,
            Direction::North | Direction::South => !input.ridge_along_width,
        };
        if is_gable_end {
            let cx = (min_x + max_x) * 0.5;
            result.polylines.push(Polyline2D {
                points: vec![
                    Vec2::new(min_x, plate_y),
                    Vec2::new(cx, ridge_y),
                    Vec2::new(max_x, plate_y),
                ],
                closed: true,
                layer: "A-ROOF".into(),
                line_type: "continuous".into(),
                line_weight: 0.35,
                color: Vec3::new(0.5, 0.5, 0.5),
            });
        } else if input.hip {
            let inset = input.width.min(input.depth) * 0.5;
            let (rl, rr) = (min_x + inset, max_x - inset);
            result.polylines.push(Polyline2D {
                points: vec![
                    Vec2::new(min_x, plate_y),
                    Vec2::new(max_x, plate_y),
                    Vec2::new(rr, ridge_y),
                    Vec2::new(rl, ridge_y),
                ],
                closed: true,
                layer: "A-ROOF".into(),
                line_type: "continuous".into(),
                line_weight: 0.35,
                color: Vec3::new(0.5, 0.5, 0.5),
            });
        } else {
            result.polylines.push(Polyline2D {
                points: vec![
                    Vec2::new(min_x, plate_y),
                    Vec2::new(max_x, plate_y),
                    Vec2::new(max_x, ridge_y),
                    Vec2::new(min_x, ridge_y),
                ],
                closed: true,
                layer: "A-ROOF".into(),
                line_type: "continuous".into(),
                line_weight: 0.35,
                color: Vec3::new(0.5, 0.5, 0.5),
            });
            result.lines.push(Line2D {
                start: Vec2::new(min_x, ridge_y),
                end: Vec2::new(max_x, ridge_y),
                layer: "A-ROOF".into(),
                line_type: "continuous".into(),
                line_weight: 0.35,
                color: Vec3::ZERO,
            });
        }
    }

    // Openings
    for op in &openings {
        result.polylines.push(Polyline2D {
            points: vec![
                Vec2::new(op.center_x - op.width * 0.5, op.bottom_y),
                Vec2::new(op.center_x + op.width * 0.5, op.bottom_y),
                Vec2::new(op.center_x + op.width * 0.5, op.top_y),
                Vec2::new(op.center_x - op.width * 0.5, op.top_y),
            ],
            closed: true,
            layer: if op.is_door { "A-DOOR".into() } else { "A-WIND".into() },
            line_type: "continuous".into(),
            line_weight: 0.25,
            color: Vec3::ONE,
        });
    }

    // Grade line
    if max_x > min_x {
        result.lines.push(Line2D {
            start: Vec2::new(min_x - 500.0, 0.0),
            end: Vec2::new(max_x + 500.0, 0.0),
            layer: "A-GRADE".into(),
            line_type: "continuous".into(),
            line_weight: 0.5,
            color: Vec3::new(0.4, 0.4, 0.4),
        });
    }

    result
}

/// Render an elevation drawing to a DXF byte vector.
pub fn generate_elevation_dxf(input: &ElevationInput, dir: Direction) -> Result<Vec<u8>, String> {
    let slice = elevation_to_slice_result(input, dir);
    crate::export_to_dxf(&slice)
}

/// Render an elevation drawing to an SVG string. `scale` is mm-to-pixels
/// (the Python default is 0.05, i.e. 1 px per 20 mm).
#[must_use]
#[allow(clippy::too_many_lines)]
pub fn generate_elevation_sheet_svg(input: &ElevationInput, dir: Direction, scale: f32) -> String {
    // Project all walls; keep those facing this direction by virtue of
    // having a horizontal extent. Walls aligned with the view direction
    // collapse to a vertical edge (start_x == end_x) and are filtered.
    let walls: Vec<WallSegment> = input
        .walls
        .iter()
        .map(|w| project_wall(w, dir, input))
        .filter(|w| (w.end_x - w.start_x).abs() > 1.0)
        .collect();

    // Project only the openings on the perimeter wall that faces this
    // elevation — not the back wall or interior partitions.
    let bounds = building_bounds(input);
    let openings: Vec<Opening> = input
        .openings
        .iter()
        .filter_map(|op| {
            let wall = input.walls.get(op.wall_index)?;
            if !wall_faces(wall, dir, bounds) {
                return None;
            }
            project_opening(op, wall, dir, input)
        })
        .collect();

    // Compute bounds across all elements (walls + openings + roof if any).
    let (mut min_x, mut max_x, min_y, mut max_y) =
        (f32::INFINITY, f32::NEG_INFINITY, 0.0_f32, f32::NEG_INFINITY);
    for w in &walls {
        min_x = min_x.min(w.start_x);
        max_x = max_x.max(w.end_x);
        max_y = max_y.max(w.top_y);
    }
    for op in &openings {
        max_y = max_y.max(op.top_y);
    }
    let max_wall_top = walls.iter().map(|w| w.top_y).fold(0.0_f32, f32::max);
    let gable_top_y = if !input.footprint_polygon_mm.is_empty() {
        // Polygon path: tallest wing's ridge sets the top.
        let by_x = matches!(dir, Direction::North | Direction::South);
        let rects = decompose_rectilinear(&input.footprint_polygon_mm, by_x);
        let pitch = if input.roof_pitch > 0.0 { input.roof_pitch } else { 0.5 };
        let max_ridge = rects
            .iter()
            .map(|r| {
                let (w, d) = wing_dims(r, by_x);
                w.min(d) * 0.5 * pitch
            })
            .fold(0.0_f32, f32::max);
        max_wall_top + max_ridge
    } else if input.gable_ridge_above_plate > 0.0 {
        max_wall_top + input.gable_ridge_above_plate
    } else {
        0.0
    };
    if gable_top_y > max_y {
        max_y = gable_top_y;
    }

    if !min_x.is_finite() {
        min_x = 0.0;
        max_x = match dir {
            Direction::South | Direction::North => input.width.max(10_000.0),
            Direction::East | Direction::West => input.depth.max(10_000.0),
        };
    }
    if !max_y.is_finite() || max_y <= 0.0 {
        max_y = 2700.0;
    }

    // Keep the side margin wide enough that the roof's rake/eave overhang
    // (which projects `eave_overhang_mm` past the wall) stays inside the sheet.
    let margin_x = 1000.0_f32.max(input.eave_overhang_mm.max(0.0) + 700.0);
    let margin_y = 800.0_f32;
    // Extra room on the right edge for level-marker callouts (Phase 2.5
    // adds T.O. FOUNDATION / SUBFLOOR / PLATE labels off the building).
    let right_extra = if max_y > 0.0 { 5500.0_f32 } else { 0.0 };
    // Extra room below grade so the width dimension (≈500 below grade) and the
    // centred drawing title (at the very bottom) get their own bands instead of
    // overlapping each other.
    let bottom_extra = 1400.0_f32;
    let vb_x = min_x - margin_x;
    let vb_y = min_y - margin_y;
    let vb_w = (max_x - min_x) + 2.0 * margin_x + right_extra;
    let vb_h = (max_y - min_y) + 2.0 * margin_y + bottom_extra;

    #[allow(clippy::cast_possible_truncation)]
    let px_w = (vb_w * scale) as i32;
    #[allow(clippy::cast_possible_truncation)]
    let px_h = (vb_h * scale) as i32;

    let mut s = String::with_capacity(4096);
    s.push_str("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n");
    let _ = writeln!(
        s,
        r#"<svg xmlns="http://www.w3.org/2000/svg" width="{px_w}" height="{px_h}" viewBox="{vb_x} {vb_y} {vb_w} {vb_h}">"#,
    );
    let _ = writeln!(s, "  <title>{} Elevation</title>", dir.label());
    s.push_str("  <rect width=\"100%\" height=\"100%\" fill=\"white\"/>\n");

    // Styles.
    s.push_str("  <style>\n");
    s.push_str("    .wall-face { fill: #e8e4d8; stroke: #000; stroke-width: 4; }\n");
    s.push_str("    .siding { stroke: #cfc7b6; stroke-width: 2; }\n");
    s.push_str("    .opening { fill: white; stroke: #000; stroke-width: 3; }\n");
    s.push_str("    .door { fill: #c8c0b0; stroke: #000; stroke-width: 3; }\n");
    s.push_str("    .roof { fill: #888; stroke: #000; stroke-width: 4; }\n");
    s.push_str("    .shingle { stroke: #565656; stroke-width: 4; }\n");
    // Window glazing, frame, muntins, sill/head.
    s.push_str("    .glass { fill: #d9e6ef; stroke: #000; stroke-width: 3; }\n");
    s.push_str("    .frame { fill: none; stroke: #000; stroke-width: 6; }\n");
    s.push_str("    .muntin { stroke: #000; stroke-width: 3; }\n");
    s.push_str("    .trim { fill: #f3efe6; stroke: #000; stroke-width: 3; }\n");
    s.push_str("    .panel { fill: none; stroke: #000; stroke-width: 3; }\n");
    s.push_str("    .grade { stroke: #666; stroke-width: 6; fill: none; }\n");
    s.push_str("    .title { font-family: Arial, sans-serif; font-size: 350px; font-weight: bold; fill: #333; }\n");
    s.push_str("    .label { font-family: Arial, sans-serif; font-size: 200px; fill: #333; }\n");
    s.push_str("    .note-h { font-family: Arial, sans-serif; font-size: 190px; font-weight: bold; fill: #222; }\n");
    s.push_str("    .note { font-family: Arial, sans-serif; font-size: 150px; fill: #333; }\n");
    s.push_str("  </style>\n");

    // Flip Y so 0 is at the bottom (grade) and ridges go up the page. Geometry
    // is drawn in this flipped (positive-up) space; text/dimensions are emitted
    // upright afterwards in screen coordinates via `sy`.
    let flip_y = max_y + min_y;
    let sy = |model_y: f32| flip_y - model_y;
    let _ = writeln!(s, r#"<g transform="translate(0, {flip_y}) scale(1, -1)">"#);

    // Wall plate height — the wall stops here; the roof sits above it (so the
    // gable's flanks read as roof/sky, not wall).
    let plate_y = walls.iter().map(|w| w.top_y).fold(0.0_f32, f32::max);

    // Walls — single envelope rect from grade up to the plate.
    if !walls.is_empty() {
        let _ = writeln!(
            s,
            r#"    <rect x="{x}" y="0" width="{w}" height="{plate_y}" class="wall-face"/>"#,
            x = min_x,
            w = max_x - min_x,
        );
        // Horizontal lap-siding courses across the wall face. Drawn before the
        // openings so the window/door rects mask the lines that fall behind
        // them. SIDING_COURSE is a typical exposed lap height.
        const SIDING_COURSE: f32 = 200.0;
        let mut cy = SIDING_COURSE;
        while cy < plate_y {
            let _ = writeln!(
                s,
                r#"    <line x1="{min_x}" y1="{cy}" x2="{max_x}" y2="{cy}" class="siding"/>"#,
            );
            cy += SIDING_COURSE;
        }
    }

    // Floor lines between storeys, so a multi-storey elevation reads as stacked.
    if !walls.is_empty() {
        for &fy in &input.floor_lines {
            if fy > 0.0 && fy < max_y {
                let _ = writeln!(
                    s,
                    r#"    <line x1="{min_x}" y1="{fy}" x2="{max_x}" y2="{fy}" class="grade"/>"#,
                );
            }
        }
    }

    // Roof — capture its silhouette polygon so shingle courses can be clipped
    // to whatever shape (gable triangle, hip trapezoid, eave-side band, or a
    // decomposed polygon footprint). The wall envelope stays a single rect.
    let mut roof_poly: Option<String> = None;
    let mut roof_top = plate_y;
    // Eave/rake overhang: the roof projects past the wall by `oh` horizontally;
    // on eave sides the fascia also drops `eave_drop` below the plate (the slope
    // run over the overhang plus a fascia board). 0 = roof flush with the wall.
    let oh = input.eave_overhang_mm.max(0.0);
    let pitch_e = if input.roof_pitch > 0.0 { input.roof_pitch } else { 0.5 };
    let eave_drop = if oh > 0.0 { oh * pitch_e + 150.0 } else { 0.0 };
    let (xl, xr) = (min_x - oh, max_x + oh);
    let eave_y = plate_y - eave_drop;
    if !input.footprint_polygon_mm.is_empty() && !walls.is_empty() {
        let silhouette = polygon_roof_silhouette(input, dir, plate_y);
        if !silhouette.is_empty() {
            roof_top = silhouette.iter().map(|&(_, y)| y).fold(plate_y, f32::max);
            roof_poly = Some(
                silhouette
                    .iter()
                    .map(|(x, y)| format!("{x},{y}"))
                    .collect::<Vec<_>>()
                    .join(" "),
            );
        }
    } else if input.gable_ridge_above_plate > 0.0 && !walls.is_empty() {
        let ridge_y = plate_y + input.gable_ridge_above_plate;
        roof_top = ridge_y;
        let is_gable_end = match dir {
            Direction::East | Direction::West => input.ridge_along_width,
            Direction::North | Direction::South => !input.ridge_along_width,
        };
        roof_poly = Some(if is_gable_end {
            // Gable end: the rake overhangs sideways at plate level; the apex
            // stays centred over the wall.
            let cx = (min_x + max_x) * 0.5;
            format!("{xl},{plate_y} {cx},{ridge_y} {xr},{plate_y}")
        } else if input.hip {
            // Hip eave side: trapezoid — eaves overhang out + down, ridge inset
            // by half the short span at each end.
            let inset = input.width.min(input.depth) * 0.5;
            let (rl, rr) = (min_x + inset, max_x - inset);
            format!("{xl},{eave_y} {xr},{eave_y} {rr},{ridge_y} {rl},{ridge_y}")
        } else {
            // Gable eave side: a plate→ridge band; the eave overhangs out + down.
            format!("{xl},{eave_y} {xr},{eave_y} {xr},{ridge_y} {xl},{ridge_y}")
        });
    }
    if let Some(pts) = &roof_poly {
        let _ = writeln!(s, r#"    <polygon points="{pts}" class="roof"/>"#);
        // Shingle courses, clipped to the roof silhouette so they read as a
        // shingled slope rather than crossing the sky.
        let _ = writeln!(
            s,
            r#"    <clipPath id="roofclip"><polygon points="{pts}"/></clipPath>"#,
        );
        s.push_str("    <g clip-path=\"url(#roofclip)\">\n");
        const COURSE: f32 = 320.0;
        let mut ry = eave_y + COURSE;
        while ry < roof_top {
            let _ = writeln!(
                s,
                r#"      <line x1="{xl}" y1="{ry}" x2="{xr}" y2="{ry}" class="shingle"/>"#,
            );
            ry += COURSE;
        }
        s.push_str("    </g>\n");
    }

    // Openings — drawn as real architectural elements: windows get glazing +
    // frame + muntins + a projecting sill/head; doors get a slab with panels.
    for op in &openings {
        let x0 = op.center_x - op.width * 0.5;
        let x1 = op.center_x + op.width * 0.5;
        let (yb, yt) = (op.bottom_y, op.top_y);
        let h = yt - yb;
        if op.is_door {
            // Door slab + two recessed panels.
            let _ = writeln!(
                s,
                r#"    <rect x="{x0}" y="{yb}" width="{w}" height="{h}" class="door"/>"#,
                w = op.width,
            );
            let inset = (op.width * 0.18).min(150.0);
            let pw = op.width - 2.0 * inset;
            // Lower (tall) and upper (short) panels.
            let _ = writeln!(
                s,
                r#"    <rect x="{px}" y="{py}" width="{pw}" height="{ph}" class="panel"/>"#,
                px = x0 + inset,
                py = yb + inset,
                ph = h * 0.5 - inset * 1.5,
            );
            let _ = writeln!(
                s,
                r#"    <rect x="{px}" y="{py}" width="{pw}" height="{ph}" class="panel"/>"#,
                px = x0 + inset,
                py = yb + h * 0.5 + inset * 0.5,
                ph = h * 0.5 - inset * 1.5,
            );
        } else {
            // Projecting sill below and head trim above, slightly wider.
            let ext = 90.0_f32;
            let band = 80.0_f32;
            let _ = writeln!(
                s,
                r#"    <rect x="{x}" y="{y}" width="{w}" height="{band}" class="trim"/>"#,
                x = x0 - ext,
                y = yb - band,
                w = op.width + 2.0 * ext,
            );
            let _ = writeln!(
                s,
                r#"    <rect x="{x}" y="{y}" width="{w}" height="{band}" class="trim"/>"#,
                x = x0 - ext,
                y = yt,
                w = op.width + 2.0 * ext,
            );
            // Glazing + frame.
            let _ = writeln!(
                s,
                r#"    <rect x="{x0}" y="{yb}" width="{w}" height="{h}" class="glass"/>"#,
                w = op.width,
            );
            let _ = writeln!(
                s,
                r#"    <rect x="{x0}" y="{yb}" width="{w}" height="{h}" class="frame"/>"#,
                w = op.width,
            );
            // Muntins: one horizontal at mid-height, and vertical mullions every
            // ~600 mm so wide windows read as ganged units, not one big pane.
            let my = yb + h * 0.5;
            let _ = writeln!(s, r#"    <line x1="{x0}" y1="{my}" x2="{x1}" y2="{my}" class="muntin"/>"#);
            #[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)]
            let lites = ((op.width / 600.0).round() as i32).max(1);
            for i in 1..lites {
                #[allow(clippy::cast_precision_loss)]
                let mx = x0 + op.width * (i as f32) / (lites as f32);
                let _ = writeln!(s, r#"    <line x1="{mx}" y1="{yb}" x2="{mx}" y2="{yt}" class="muntin"/>"#);
            }
        }
    }

    // Grade line at Y=0.
    let _ = writeln!(
        s,
        r#"    <line x1="{x1}" y1="0" x2="{x2}" y2="0" class="grade"/>"#,
        x1 = min_x - 500.0,
        x2 = max_x + 500.0,
    );

    s.push_str("  </g>\n");

    // Dimensions — emitted OUTSIDE the flip group (screen coordinates via `sy`)
    // so the value text reads upright instead of mirrored. Grade is model-Y 0.
    // Overall envelope (Tier-1): width along the bottom, height along the left.
    if max_x > min_x {
        let width_dim = crate::dimensions::LinearDim::horizontal_mm(min_x, max_x, sy(0.0) + 500.0);
        s.push_str(&crate::dimensions::render_horizontal(&width_dim, 250.0));
    }
    if max_y > 0.0 {
        let height_dim =
            crate::dimensions::LinearDim::vertical_mm(sy(max_y), sy(0.0), min_x - 500.0);
        s.push_str(&crate::dimensions::render_vertical(&height_dim, 250.0));
    }

    // Per-opening width dimensions (Tier-3): each door/window gets a small width
    // callout just below the elevation grade line.
    for op in &openings {
        let dim = crate::dimensions::LinearDim::horizontal_mm(
            op.center_x - op.width * 0.5,
            op.center_x + op.width * 0.5,
            sy(0.0) + 200.0,
        );
        s.push_str(&crate::dimensions::render_horizontal(&dim, 150.0));
    }

    // Level markers (Phase 2.5) — drawn OUTSIDE the flip group so the
    // labels read upright. Each marker is a short leader off the right
    // edge of the building with a filled triangle bubble at the level
    // line, plus a `T.O. ...` callout in feet-inches + mm.
    if !walls.is_empty() && max_y > 0.0 {
        let leader_x_start = max_x + 250.0;
        let leader_x_end = max_x + 1800.0;
        // Build the list of levels to label.
        let mut levels: Vec<(f32, String)> = Vec::new();
        levels.push((0.0, "T.O. FOUNDATION".to_string()));
        for (i, &fy) in input.floor_lines.iter().enumerate() {
            if fy > 0.0 && fy < plate_y {
                levels.push((fy, format!("T.O. SUBFLOOR L{}", i + 2)));
            }
        }
        if plate_y > 0.0 {
            levels.push((plate_y, "T.O. PLATE".to_string()));
        }

        s.push_str("  <g id=\"level-markers\">\n");
        for (y_mm, label) in &levels {
            // Convert flipped (positive-up) Y to the surrounding SVG's
            // positive-down Y. `flip_y = max_y + min_y`.
            let svg_y = flip_y - y_mm;
            // Leader line.
            let _ = writeln!(
                s,
                r##"    <line x1="{x1}" y1="{y}" x2="{x2}" y2="{y}" stroke="#222" stroke-width="3"/>"##,
                x1 = leader_x_start,
                x2 = leader_x_end,
                y = svg_y,
            );
            // Triangle bubble at the building edge.
            let tri_y = svg_y;
            let _ = writeln!(
                s,
                r##"    <polygon points="{p1x},{p1y} {p2x},{p2y} {p3x},{p3y}" fill="#222"/>"##,
                p1x = leader_x_start,
                p1y = tri_y,
                p2x = leader_x_start + 140.0,
                p2y = tri_y - 80.0,
                p3x = leader_x_start + 140.0,
                p3y = tri_y + 80.0,
            );
            // Label + elevation in ft-in and mm.
            let _ = writeln!(
                s,
                r#"    <text x="{tx}" y="{ty}" class="label">{label}</text>"#,
                tx = leader_x_end + 80.0,
                ty = svg_y - 40.0,
            );
            let _ = writeln!(
                s,
                r#"    <text x="{tx}" y="{ty}" class="label">EL. {ftin}  [{mm:.0} mm]</text>"#,
                tx = leader_x_end + 80.0,
                ty = svg_y + 220.0,
                ftin = format_ft_in(*y_mm),
                mm = y_mm,
            );
        }
        s.push_str("  </g>\n");
    }

    // Exterior-finish / assembly notes (top-left, upright — the sky area is
    // free). Complements the section's SB-12 R-value assemblies with the
    // finishes a builder reads off the elevation.
    if !walls.is_empty() {
        let nx = vb_x + 250.0;
        let mut ny = vb_y + 450.0;
        let _ = writeln!(
            s,
            r#"  <text x="{nx}" y="{ny}" class="note-h">EXTERIOR FINISHES</text>"#,
        );
        for line in [
            "ROOF: asphalt shingles o/ ice &amp; water o/ 12.7mm sheathing",
            "WALLS: siding o/ building wrap o/ 2x6 studs @ 406mm o.c.",
            "         R-22 batt + R-5 c.i. (OBC SB-12, zone-dependent)",
            "FOUNDATION: parging o/ damp-proofing on conc. wall",
        ] {
            ny += 280.0;
            let _ = writeln!(s, r#"  <text x="{nx}" y="{ny}" class="note">{line}</text>"#);
        }
    }

    // Title (NOT flipped).
    let title_y = vb_y + vb_h - 200.0;
    let title_x = vb_x + vb_w * 0.5;
    let _ = writeln!(
        s,
        r#"  <text x="{title_x:.0}" y="{title_y}" text-anchor="middle" class="title">{label} ELEVATION</text>"#,
        label = dir.label(),
    );

    s.push_str("</svg>\n");
    s
}

/// Format a millimetre height as `<feet>'-<inches>"` (rounded to nearest inch).
fn format_ft_in(mm: f32) -> String {
    const MM_PER_INCH: f32 = 25.4;
    let total_inches = (mm / MM_PER_INCH).round() as i32;
    let feet = total_inches / 12;
    let inches = total_inches.rem_euclid(12);
    format!("{feet}'-{inches}\"")
}

/// Sheet number prefix for the elevation drawing — matches the Python
/// permit-set's naming convention (03_elevation_{direction}.svg).
#[must_use]
pub fn sheet_name(dir: Direction) -> String {
    format!("03_elevation_{}.svg", dir.as_str())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn decompose_rectilinear_l_yields_two_wings() {
        // L-shape: main wing 6×8, side wing 4×4.
        let l = vec![
            (0.0, 0.0), (10.0, 0.0), (10.0, 4.0),
            (6.0, 4.0), (6.0, 8.0), (0.0, 8.0),
        ];
        let rects = decompose_rectilinear(&l, true);
        assert_eq!(rects.len(), 2, "L should decompose into 2 wings, got {}", rects.len());
        // Sweep along x → strips at x∈[0,6] and x∈[6,10].
        let mut sorted = rects.clone();
        sorted.sort_by(|a, b| a.0.0.partial_cmp(&b.0.0).unwrap());
        assert!((sorted[0].1.0 - 6.0).abs() < 0.01); // first strip x: 0..6
        assert!((sorted[0].1.1 - 8.0).abs() < 0.01); // first strip z: 0..8
        assert!((sorted[1].0.0 - 6.0).abs() < 0.01); // second strip x: 6..10
        assert!((sorted[1].1.1 - 4.0).abs() < 0.01); // second strip z: 0..4
    }

    #[test]
    fn decompose_rectilinear_t_yields_three_wings() {
        let t = vec![
            (0.0, 0.0), (12.0, 0.0), (12.0, 4.0),
            (8.0, 4.0), (8.0, 10.0), (4.0, 10.0),
            (4.0, 4.0), (0.0, 4.0),
        ];
        let rects = decompose_rectilinear(&t, true);
        assert_eq!(rects.len(), 3, "T should decompose into 3 wings, got {}", rects.len());
    }

    #[test]
    fn polygon_silhouette_has_one_peak_per_wing() {
        // L-shape, viewed from south (looking towards +z). Sweep by x.
        let mut input = ElevationInput {
            width: 10_000.0,
            depth: 8_000.0,
            roof_pitch: 0.5,
            footprint_polygon_mm: vec![
                (0.0, 0.0), (10_000.0, 0.0), (10_000.0, 4_000.0),
                (6_000.0, 4_000.0), (6_000.0, 8_000.0), (0.0, 8_000.0),
            ],
            ..Default::default()
        };
        input.walls.push(ElevationWallInput {
            start: Vec3::new(0.0, 0.0, 0.0),
            end: Vec3::new(10_000.0, 0.0, 0.0),
            height: 2_700.0,
            base: 0.0,
        });
        let sil = polygon_roof_silhouette(&input, Direction::South, 2_700.0);
        // Expected: plate start, main-wing peak(s), step, side-wing peak(s),
        // plate end. Both wings here are square-ish on the view axis so each
        // contributes a single triangle peak → 2 ridge vertices between the
        // two plate vertices.
        assert!(sil.len() >= 4, "silhouette has {} pts", sil.len());
        // First and last vertices sit on the plate.
        assert!((sil[0].1 - 2_700.0).abs() < 1.0);
        assert!((sil.last().unwrap().1 - 2_700.0).abs() < 1.0);
        // Main wing's short span = 6000 → ridge 1500; side wing 4000 → 1000.
        // The tallest peak in the silhouette should be ≈ plate + 1500.
        let peak = sil.iter().map(|(_, y)| *y).fold(0.0_f32, f32::max);
        assert!((peak - (2_700.0 + 1_500.0)).abs() < 50.0, "peak {peak}");
    }

    fn rectangular_input() -> ElevationInput {
        let mut input = ElevationInput {
            width: 5000.0,
            depth: 4000.0,
            gable_ridge_above_plate: 1200.0,
            ..Default::default()
        };
        for ((sx, sz), (ex, ez)) in [
            ((0.0, 0.0), (5000.0, 0.0)),
            ((5000.0, 0.0), (5000.0, 4000.0)),
            ((5000.0, 4000.0), (0.0, 4000.0)),
            ((0.0, 4000.0), (0.0, 0.0)),
        ] {
            input.walls.push(ElevationWallInput {
                start: Vec3::new(sx, 0.0, sz),
                end: Vec3::new(ex, 0.0, ez),
                height: 2700.0,
                base: 0.0,
            });
        }
        // Door on wall 0 (south face), centred.
        input.openings.push(ElevationOpeningInput {
            wall_index: 0,
            offset: 2500.0,
            width: 900.0,
            height: 2100.0,
            sill_height: 0.0,
            is_door: true,
        });
        // Window on wall 1 (east face), 1.5m up.
        input.openings.push(ElevationOpeningInput {
            wall_index: 1,
            offset: 2000.0,
            width: 1200.0,
            height: 1200.0,
            sill_height: 900.0,
            is_door: false,
        });
        input
    }

    #[test]
    fn two_storeys_stack_taller_with_a_floor_line() {
        // Ground + upper exterior wall on the south face; upper based at 3000mm.
        let mut input = ElevationInput {
            width: 5000.0,
            depth: 4000.0,
            floor_lines: vec![3000.0],
            ..Default::default()
        };
        for base in [0.0, 3000.0] {
            input.walls.push(ElevationWallInput {
                start: Vec3::new(0.0, 0.0, 0.0),
                end: Vec3::new(5000.0, 0.0, 0.0),
                height: 2700.0,
                base,
            });
        }
        let svg = generate_elevation_sheet_svg(&input, Direction::South, 0.05);
        // Silhouette reaches the upper wall's top (3000 + 2700 = 5700), well
        // above a single 2700 storey — i.e. the floors stacked.
        assert!(svg.contains("height=\"5700\""), "envelope should span both storeys: {svg}");
        // A floor line is drawn between the storeys.
        assert!(svg.contains(r#"y1="3000""#), "missing inter-storey floor line");
    }

    #[test]
    fn all_four_directions_emit_well_formed_svg() {
        let input = rectangular_input();
        for dir in Direction::ALL {
            let svg = generate_elevation_sheet_svg(&input, dir, 0.05);
            assert!(svg.starts_with("<?xml version=\"1.0\""), "{dir:?}");
            assert!(svg.ends_with("</svg>\n"), "{dir:?}");
            assert!(svg.contains(dir.label()), "{dir:?}");
            assert!(svg.contains("scale(1, -1)"));
            assert!(svg.contains(r#"class="wall-face""#));
            assert!(svg.contains(r#"class="roof""#));
        }
    }

    #[test]
    fn dimensions_and_labels_render_upright_outside_the_flip_group() {
        // All text (dimensions, level markers, drawing title) must be emitted
        // AFTER the flipped geometry group closes, otherwise scale(1,-1) mirrors
        // the glyphs and the value text reads upside down.
        let input = rectangular_input();
        for dir in Direction::ALL {
            let svg = generate_elevation_sheet_svg(&input, dir, 0.05);
            let flip_close = svg.find("</g>").expect("flip group should close");
            if let Some(first_text) = svg.find("<text") {
                assert!(
                    first_text > flip_close,
                    "{dir:?}: text at {first_text} precedes </g> at {flip_close} — would mirror"
                );
            }
        }
    }

    #[test]
    fn south_elevation_shows_the_door_not_the_east_window() {
        let input = rectangular_input();
        let svg = generate_elevation_sheet_svg(&input, Direction::South, 0.05);
        assert!(svg.contains(r#"class="door""#), "south view must show door");
        // Window is on east-facing wall — should not appear in south view.
        assert!(
            !svg.contains(r#"class="glass""#),
            "south view should not show east-facing window: {svg}"
        );
    }

    #[test]
    fn east_elevation_shows_the_window_not_the_south_door() {
        let input = rectangular_input();
        let svg = generate_elevation_sheet_svg(&input, Direction::East, 0.05);
        assert!(svg.contains(r#"class="glass""#));
        assert!(
            !svg.contains(r#"class="door""#),
            "east view should not show south-facing door: {svg}"
        );
    }

    #[test]
    fn back_wall_and_interior_openings_dont_appear_on_the_front() {
        // Rectangular building + a window on the NORTH (back) wall and an
        // opening on an INTERIOR east-west partition. Neither may show on the
        // south elevation — only the south wall's door does.
        let mut input = rectangular_input(); // walls 0=S 1=E 2=N 3=W, door on S
        // Window on wall 2 (north, z=4000).
        input.openings.push(ElevationOpeningInput {
            wall_index: 2,
            offset: 2500.0,
            width: 1000.0,
            height: 1000.0,
            sill_height: 900.0,
            is_door: false,
        });
        // Interior partition (E-W) at mid-depth + a door on it (wall 4).
        input.walls.push(ElevationWallInput {
            start: Vec3::new(0.0, 0.0, 2000.0),
            end: Vec3::new(5000.0, 0.0, 2000.0),
            height: 2700.0,
            base: 0.0,
        });
        input.openings.push(ElevationOpeningInput {
            wall_index: 4,
            offset: 1000.0,
            width: 800.0,
            height: 2100.0,
            sill_height: 0.0,
            is_door: true,
        });

        let south = generate_elevation_sheet_svg(&input, Direction::South, 0.05);
        // Exactly one door (the south wall's), and no windows (north window hidden).
        assert_eq!(south.matches(r#"class="door""#).count(), 1, "only the south door: {south}");
        assert!(!south.contains(r#"class="glass""#), "north/interior windows hidden");

        // The north window does show on the north elevation.
        let north = generate_elevation_sheet_svg(&input, Direction::North, 0.05);
        assert!(north.contains(r#"class="glass""#), "north window shows on north view");
    }

    #[test]
    fn sheet_name_matches_python_pattern() {
        assert_eq!(sheet_name(Direction::North), "03_elevation_north.svg");
        assert_eq!(sheet_name(Direction::South), "03_elevation_south.svg");
        assert_eq!(sheet_name(Direction::East), "03_elevation_east.svg");
        assert_eq!(sheet_name(Direction::West), "03_elevation_west.svg");
    }

    #[test]
    fn format_ft_in_handles_round_and_fractional_values() {
        assert_eq!(format_ft_in(0.0), "0'-0\"");
        assert_eq!(format_ft_in(2438.4), "8'-0\""); // 8 ft = 2438.4 mm
        assert_eq!(format_ft_in(3048.0), "10'-0\""); // 10 ft
        // 100 inches = 8 ft 4 in.
        assert_eq!(format_ft_in(100.0 * 25.4), "8'-4\"");
    }

    #[test]
    fn level_markers_appear_at_foundation_subfloor_and_plate() {
        let mut input = ElevationInput {
            width: 5000.0,
            depth: 4000.0,
            floor_lines: vec![3000.0],
            ..Default::default()
        };
        for base in [0.0, 3000.0] {
            input.walls.push(ElevationWallInput {
                start: Vec3::new(0.0, 0.0, 0.0),
                end: Vec3::new(5000.0, 0.0, 0.0),
                height: 2700.0,
                base,
            });
        }
        let svg = generate_elevation_sheet_svg(&input, Direction::South, 0.05);
        assert!(svg.contains(r#"id="level-markers""#));
        assert!(svg.contains("T.O. FOUNDATION"));
        assert!(svg.contains("T.O. SUBFLOOR L2"));
        assert!(svg.contains("T.O. PLATE"));
        // Foundation is at 0 → 0'-0".
        assert!(svg.contains("EL. 0'-0\"  [0 mm]"));
    }

    #[test]
    fn no_level_markers_for_empty_walls() {
        let input = ElevationInput::default();
        let svg = generate_elevation_sheet_svg(&input, Direction::South, 0.05);
        assert!(!svg.contains("level-markers"));
        assert!(!svg.contains("T.O. FOUNDATION"));
    }
}
