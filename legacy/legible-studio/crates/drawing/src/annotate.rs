//! Plan-generator annotations — text labels, dimensions, grids, symbols,
//! and roof markers.
//!
//! Ported from `ArchEngine_kernel/include/plan_generator.hpp` (560 LOC
//! header-only). Per port plan §8 Q1, this is merged into the `drawing`
//! crate rather than living as a separate `plan_generator` module — but
//! kept in its own sub-module since the responsibilities are distinct
//! from `slice::*`.
//!
//! Pipeline:
//! 1. `generate_floor_plan` / `generate_roof_plan` build an
//!    `AnnotationSet` from a `Building`.
//! 2. `to_slice_result` flattens that set into `SliceResult` primitives
//!    (Lines, Polylines, Arcs, Text) which the existing
//!    `svg::export_to_svg` renders.
//!
//! Note on complex symbols (north arrow, section marker arrow heads,
//! roof pitch indicators): the C++ `plan_generator::svgXxx` helpers
//! emit SVG `<path>` primitives that this Rust primitive set can't
//! express today. Those symbols are still flattened — as their
//! constituent lines + text — but they look schematic, not pictorial.
//! Flagged for follow-up when a path primitive is added.

use crate::primitives::{
    Arc2D, Circle2D, Dimension2D, Line2D, Point2D, Polyline2D, SliceResult, Text2D,
};
use domain::Building;
use glam::Vec2;

// ---------------------------------------------------------------------------
// Annotation primitive types
// ---------------------------------------------------------------------------

/// Categorisation of plan views. Mirrors `plan_generator.hpp:14`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Default)]
#[repr(u32)]
pub enum PlanType {
    #[default]
    FloorPlan,
    RoofPlan,
    ReflectedCeilingPlan,
    SitePlan,
    FoundationPlan,
    FramingPlan,
    Elevation,
    Section,
}

/// Symbol types used on plan drawings. Mirrors `plan_generator.hpp:26`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Default)]
#[repr(u32)]
pub enum SymbolType {
    #[default]
    NorthArrow,
    SectionMarker,
    DetailMarker,
    ElevationMarker,
    DoorTag,
    WindowTag,
    RoomTag,
    ColumnGrid,
    LevelMarker,
}

/// Roof-specific annotation type.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Default)]
#[repr(u32)]
pub enum RoofAnnotationType {
    #[default]
    PitchIndicator,
    DrainageArrow,
    RidgeLine,
    ValleyLine,
    HipLine,
    EaveLine,
    RakeLine,
    SlopeArrow,
}

#[derive(Debug, Clone, PartialEq)]
pub struct TextLabel {
    pub id: String,
    pub text: String,
    pub position: Vec2,
    pub rotation: f32,
    pub text_height: f32,
    pub font_style: String,
    pub justification: String,
    pub show_border: bool,
    pub show_background: bool,
}

impl Default for TextLabel {
    fn default() -> Self {
        Self {
            id: String::new(),
            text: String::new(),
            position: Vec2::ZERO,
            rotation: 0.0,
            text_height: 100.0,
            font_style: "regular".into(),
            justification: "center".into(),
            show_border: false,
            show_background: false,
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct Dimension {
    pub id: String,
    pub start_point: Vec2,
    pub end_point: Vec2,
    pub offset_distance: f32,
    pub text_height: f32,
    pub unit: String,
    pub precision: i32,
    pub show_value: bool,
}

impl Default for Dimension {
    fn default() -> Self {
        Self {
            id: String::new(),
            start_point: Vec2::ZERO,
            end_point: Vec2::ZERO,
            offset_distance: 200.0,
            text_height: 80.0,
            unit: "mm".into(),
            precision: 0,
            show_value: true,
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct Leader {
    pub id: String,
    pub arrow_point: Vec2,
    pub text_position: Vec2,
    pub bend_points: Vec<Vec2>,
    pub text: String,
    pub text_height: f32,
    pub arrow_style: String,
}

impl Default for Leader {
    fn default() -> Self {
        Self {
            id: String::new(),
            arrow_point: Vec2::ZERO,
            text_position: Vec2::ZERO,
            bend_points: Vec::new(),
            text: String::new(),
            text_height: 80.0,
            arrow_style: "closed".into(),
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct Symbol {
    pub id: String,
    pub symbol_type: SymbolType,
    pub position: Vec2,
    pub rotation: f32,
    pub scale: f32,
    pub label: String,
    pub sheet_reference: String,
    pub direction: Vec2,
}

impl Default for Symbol {
    fn default() -> Self {
        Self {
            id: String::new(),
            symbol_type: SymbolType::NorthArrow,
            position: Vec2::ZERO,
            rotation: 0.0,
            scale: 1.0,
            label: String::new(),
            sheet_reference: String::new(),
            direction: Vec2::new(0.0, 1.0),
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct RoofAnnotation {
    pub id: String,
    pub annotation_type: RoofAnnotationType,
    pub position: Vec2,
    pub end_position: Vec2,
    pub rotation: f32,
    /// Rise per 12 run.
    pub pitch: f32,
    pub slope_percent: f32,
    pub label: String,
    pub roof_surface_id: String,
}

impl Default for RoofAnnotation {
    fn default() -> Self {
        Self {
            id: String::new(),
            annotation_type: RoofAnnotationType::PitchIndicator,
            position: Vec2::ZERO,
            end_position: Vec2::ZERO,
            rotation: 0.0,
            pitch: 4.0,
            slope_percent: 0.0,
            label: String::new(),
            roof_surface_id: String::new(),
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct GridLine {
    pub id: String,
    pub label: String,
    pub start_point: Vec2,
    pub end_point: Vec2,
    pub is_primary: bool,
    pub show_bubble: bool,
}

impl Default for GridLine {
    fn default() -> Self {
        Self {
            id: String::new(),
            label: String::new(),
            start_point: Vec2::ZERO,
            end_point: Vec2::ZERO,
            is_primary: true,
            show_bubble: true,
        }
    }
}

/// Collection of all annotations for a single plan view. Mirrors
/// `plan_generator.hpp:122`.
#[derive(Debug, Clone, PartialEq)]
pub struct AnnotationSet {
    pub id: String,
    pub name: String,
    pub plan_type: PlanType,
    pub level: String,
    /// Drawing scale (e.g. 48 = 1/4" = 1'-0").
    pub scale: f32,
    pub dimensions: Vec<Dimension>,
    pub labels: Vec<TextLabel>,
    pub leaders: Vec<Leader>,
    pub symbols: Vec<Symbol>,
    pub roof_annotations: Vec<RoofAnnotation>,
    pub grid_lines: Vec<GridLine>,
    pub viewport_center: Vec2,
    pub viewport_width: f32,
    pub viewport_height: f32,
}

impl Default for AnnotationSet {
    fn default() -> Self {
        Self {
            id: String::new(),
            name: String::new(),
            plan_type: PlanType::FloorPlan,
            level: String::new(),
            scale: 48.0,
            dimensions: Vec::new(),
            labels: Vec::new(),
            leaders: Vec::new(),
            symbols: Vec::new(),
            roof_annotations: Vec::new(),
            grid_lines: Vec::new(),
            viewport_center: Vec2::ZERO,
            viewport_width: 10_000.0,
            viewport_height: 8_000.0,
        }
    }
}

// ---------------------------------------------------------------------------
// Generators
// ---------------------------------------------------------------------------

/// Plan-view bounding box (X, Z extents projected to 2D).
fn building_bounds(building: &Building) -> (Vec2, Vec2) {
    let mut min = Vec2::splat(f32::MAX);
    let mut max = Vec2::splat(f32::MIN);
    for elem in &building.elements {
        for &v in &[elem.start, elem.end] {
            min.x = min.x.min(v.x);
            max.x = max.x.max(v.x);
            min.y = min.y.min(v.z); // plan view: Y axis = 3D Z
            max.y = max.y.max(v.z);
        }
    }
    for wall in &building.parametric_walls {
        for &v in &[wall.start_point, wall.end_point] {
            min.x = min.x.min(v.x);
            max.x = max.x.max(v.x);
            min.y = min.y.min(v.y);
            max.y = max.y.max(v.y);
        }
    }
    if min.x > max.x {
        // Empty building — no elements OR parametric walls touched the bounds.
        (Vec2::ZERO, Vec2::new(10_000.0, 10_000.0))
    } else {
        (min, max)
    }
}

/// One dimension per parametric wall, offset perpendicular to the wall.
/// Matches `PlanGenerator::generateWallDimensions` (`plan_generator.hpp:269`).
#[must_use]
pub fn generate_wall_dimensions(building: &Building, offset: f32) -> Vec<Dimension> {
    building
        .parametric_walls
        .iter()
        .enumerate()
        .map(|(i, w)| Dimension {
            id: format!("dim_{i}"),
            start_point: w.start_point,
            end_point: w.end_point,
            offset_distance: offset,
            text_height: 80.0,
            unit: "mm".into(),
            precision: 0,
            show_value: true,
        })
        .collect()
}

/// Numbered horizontal + lettered vertical grid lines on the standard
/// 10'-spacing structural grid. Matches `PlanGenerator::generateStructuralGrid`
/// (`plan_generator.hpp:289`).
#[must_use]
pub fn generate_structural_grid(building: &Building, grid_spacing: f32) -> Vec<GridLine> {
    let (min, max) = building_bounds(building);
    let min_x = min.x - 500.0;
    let min_y = min.y - 500.0;
    let max_x = max.x + 500.0;
    let max_y = max.y + 500.0;

    let mut grids = Vec::new();

    // Horizontal grids (numbered).
    let mut grid_num = 1;
    let mut y = min_y;
    while y <= max_y {
        grids.push(GridLine {
            id: format!("grid_h_{grid_num}"),
            label: grid_num.to_string(),
            start_point: Vec2::new(min_x - 300.0, y),
            end_point: Vec2::new(max_x + 300.0, y),
            is_primary: true,
            show_bubble: true,
        });
        grid_num += 1;
        y += grid_spacing;
    }

    // Vertical grids (lettered, starting at 'A').
    let mut grid_letter = b'A';
    let mut x = min_x;
    while x <= max_x {
        let label = char::from(grid_letter).to_string();
        grids.push(GridLine {
            id: format!("grid_v_{label}"),
            label,
            start_point: Vec2::new(x, min_y - 300.0),
            end_point: Vec2::new(x, max_y + 300.0),
            is_primary: true,
            show_bubble: true,
        });
        grid_letter = grid_letter.saturating_add(1);
        x += grid_spacing;
    }

    grids
}

/// Floor plan annotations — dimensions + grid + a north-arrow symbol.
/// Matches `PlanGenerator::generateFloorPlan` (`plan_generator.hpp:206`).
#[must_use]
pub fn generate_floor_plan(building: &Building, level_name: impl Into<String>) -> AnnotationSet {
    let level = level_name.into();
    let (min, max) = building_bounds(building);

    let mut set = AnnotationSet {
        id: format!("floor_plan_{level}"),
        name: format!("Floor Plan - {level}"),
        plan_type: PlanType::FloorPlan,
        level,
        scale: 48.0,
        dimensions: generate_wall_dimensions(building, 300.0),
        grid_lines: generate_structural_grid(building, 3048.0),
        viewport_center: (min + max) * 0.5,
        viewport_width: (max.x - min.x) + 2000.0,
        viewport_height: (max.y - min.y) + 2000.0,
        ..Default::default()
    };

    set.symbols.push(Symbol {
        id: "north_arrow".into(),
        symbol_type: SymbolType::NorthArrow,
        position: Vec2::new(max.x + 1000.0, max.y - 500.0),
        scale: 1.0,
        ..Default::default()
    });

    set
}

/// Roof plan — same dimensions / grid / north arrow as floor plan but
/// labelled `"Roof Plan"` and `plan_type = RoofPlan`. Matches
/// `PlanGenerator::generateRoofPlan` (`plan_generator.hpp:239`).
#[must_use]
pub fn generate_roof_plan(building: &Building) -> AnnotationSet {
    let (min, max) = building_bounds(building);

    let mut set = AnnotationSet {
        id: "roof_plan".into(),
        name: "Roof Plan".into(),
        plan_type: PlanType::RoofPlan,
        level: "Roof".into(),
        scale: 48.0,
        grid_lines: generate_structural_grid(building, 3048.0),
        viewport_center: (min + max) * 0.5,
        viewport_width: (max.x - min.x) + 2000.0,
        viewport_height: (max.y - min.y) + 2000.0,
        ..Default::default()
    };

    set.symbols.push(Symbol {
        id: "north_arrow".into(),
        symbol_type: SymbolType::NorthArrow,
        position: Vec2::new(max.x + 1000.0, max.y - 500.0),
        scale: 1.0,
        ..Default::default()
    });

    set
}

// ---------------------------------------------------------------------------
// Flatten AnnotationSet → SliceResult primitives
// ---------------------------------------------------------------------------

/// Format a dimension value the way the C++ does (`plan_generator.hpp:539`):
/// - `unit == "feet"|"ft"` → feet-inches `"<f>'-<i>\""`.
/// - Otherwise → mm rounded / formatted to `precision`.
#[must_use]
pub fn format_dimension_value(value: f32, unit: &str, precision: i32) -> String {
    if unit == "feet" || unit == "ft" {
        let feet = value.floor();
        let inches = (value - feet) * 12.0;
        if precision == 0 {
            #[allow(clippy::cast_possible_truncation)]
            let f_int = feet as i32;
            #[allow(clippy::cast_possible_truncation)]
            let i_int = inches.round() as i32;
            return format!("{f_int}'-{i_int}\"");
        }
        let p = usize::try_from(precision.max(0)).unwrap_or(0);
        #[allow(clippy::cast_possible_truncation)]
        let f_int = feet as i32;
        return format!("{f_int}'-{inches:.p$}\"");
    }
    if precision == 0 {
        #[allow(clippy::cast_possible_truncation)]
        let v_int = value.round() as i32;
        v_int.to_string()
    } else {
        let p = usize::try_from(precision.max(0)).unwrap_or(0);
        format!("{value:.p$}")
    }
}

/// Convert a `Dimension` into the lines + text that render it:
/// - 1 dimension line (offset perpendicular to the segment)
/// - 2 extension lines (from endpoints to the dimension line)
/// - 1 text label at the midpoint of the dimension line
fn flatten_dimension(d: &Dimension, out: &mut SliceResult) {
    let dx = d.end_point.x - d.start_point.x;
    let dy = d.end_point.y - d.start_point.y;
    let len = (dx * dx + dy * dy).sqrt();
    if len < 0.001 {
        return;
    }
    let nx = -dy / len * d.offset_distance;
    let ny = dx / len * d.offset_distance;

    let dim_line = Line2D {
        start: Vec2::new(d.start_point.x + nx, d.start_point.y + ny),
        end: Vec2::new(d.end_point.x + nx, d.end_point.y + ny),
        layer: "A-DIMS".into(),
        line_weight: 0.5,
        ..Default::default()
    };
    let ext1 = Line2D {
        start: d.start_point,
        end: dim_line.start,
        layer: "A-DIMS".into(),
        line_weight: 0.3,
        ..Default::default()
    };
    let ext2 = Line2D {
        start: d.end_point,
        end: dim_line.end,
        layer: "A-DIMS".into(),
        line_weight: 0.3,
        ..Default::default()
    };

    let mid = dim_line.midpoint();
    let text = if d.show_value {
        format_dimension_value(len, &d.unit, d.precision)
    } else {
        String::new()
    };

    out.lines.push(dim_line);
    out.lines.push(ext1);
    out.lines.push(ext2);
    out.annotations.push(Text2D {
        position: mid,
        text,
        height: d.text_height,
        rotation: 0.0,
        layer: "A-DIMS".into(),
        justification: "center".into(),
        ..Default::default()
    });
}

fn flatten_grid_line(g: &GridLine, out: &mut SliceResult) {
    out.lines.push(Line2D {
        start: g.start_point,
        end: g.end_point,
        layer: "A-GRID".into(),
        line_weight: 0.3,
        line_type: "dashed".into(),
        ..Default::default()
    });
    if g.show_bubble {
        // Bubble = circle + centered label at the START end.
        out.circles.push(Circle2D {
            center: g.start_point,
            radius: 150.0,
            layer: "A-GRID".into(),
            line_weight: 0.3,
            ..Default::default()
        });
        out.annotations.push(Text2D {
            position: g.start_point,
            text: g.label.clone(),
            height: 100.0,
            layer: "A-GRID".into(),
            justification: "center".into(),
            ..Default::default()
        });
    }
}

fn flatten_label(l: &TextLabel, out: &mut SliceResult) {
    out.annotations.push(Text2D {
        position: l.position,
        text: l.text.clone(),
        height: l.text_height,
        rotation: l.rotation,
        layer: "A-NOTE".into(),
        justification: l.justification.clone(),
        ..Default::default()
    });
}

fn flatten_symbol(s: &Symbol, out: &mut SliceResult) {
    match s.symbol_type {
        SymbolType::NorthArrow => {
            // Schematic north arrow: a circle + "N" label. The C++ draws
            // an arrow PATH which our Line2D set can't express; a future
            // primitive can replace this.
            let radius = 150.0 * s.scale;
            out.circles.push(Circle2D {
                center: s.position,
                radius,
                layer: "A-SYMB".into(),
                line_weight: 0.5,
                ..Default::default()
            });
            out.annotations.push(Text2D {
                position: s.position,
                text: "N".into(),
                height: radius * 0.8,
                layer: "A-SYMB".into(),
                justification: "center".into(),
                ..Default::default()
            });
        }
        SymbolType::SectionMarker => {
            let radius = 100.0 * s.scale;
            out.circles.push(Circle2D {
                center: s.position,
                radius,
                layer: "A-SYMB".into(),
                line_weight: 0.5,
                ..Default::default()
            });
            if !s.label.is_empty() {
                out.annotations.push(Text2D {
                    position: s.position,
                    text: s.label.clone(),
                    height: radius * 0.8,
                    layer: "A-SYMB".into(),
                    justification: "center".into(),
                    ..Default::default()
                });
            }
        }
        _ => {
            // Other symbols (DetailMarker, ElevationMarker, DoorTag, etc.)
            // need richer primitives; we render their label only for now.
            if !s.label.is_empty() {
                out.annotations.push(Text2D {
                    position: s.position,
                    text: s.label.clone(),
                    height: 100.0,
                    layer: "A-SYMB".into(),
                    justification: "center".into(),
                    ..Default::default()
                });
            }
        }
    }
}

fn flatten_roof_annotation(r: &RoofAnnotation, out: &mut SliceResult) {
    match r.annotation_type {
        RoofAnnotationType::PitchIndicator => {
            // Show as text only (the C++ draws a small triangle + label).
            out.annotations.push(Text2D {
                position: r.position,
                text: format!("{:.0}:12", r.pitch),
                height: 80.0,
                layer: "A-ROOF".into(),
                justification: "center".into(),
                ..Default::default()
            });
        }
        RoofAnnotationType::RidgeLine
        | RoofAnnotationType::HipLine
        | RoofAnnotationType::ValleyLine => {
            out.lines.push(Line2D {
                start: r.position,
                end: r.end_position,
                layer: "A-ROOF".into(),
                line_weight: 0.5,
                line_type: if r.annotation_type == RoofAnnotationType::RidgeLine {
                    "continuous".into()
                } else {
                    "dashed".into()
                },
                ..Default::default()
            });
        }
        _ => {
            // Drainage / slope arrows etc. — render as a line for now.
            out.lines.push(Line2D {
                start: r.position,
                end: r.end_position,
                layer: "A-ROOF".into(),
                line_weight: 0.3,
                ..Default::default()
            });
        }
    }
}

/// Flatten the whole `AnnotationSet` into a `SliceResult`. Compose with
/// `slice::generate_floor_plan` output via `SliceResult::merge` to get a
/// full annotated plan, then `svg::export_to_svg`.
#[must_use]
pub fn to_slice_result(set: &AnnotationSet) -> SliceResult {
    let mut out = SliceResult::default();
    for g in &set.grid_lines {
        flatten_grid_line(g, &mut out);
    }
    for d in &set.dimensions {
        flatten_dimension(d, &mut out);
    }
    for l in &set.labels {
        flatten_label(l, &mut out);
    }
    for s in &set.symbols {
        flatten_symbol(s, &mut out);
    }
    for r in &set.roof_annotations {
        flatten_roof_annotation(r, &mut out);
    }
    out
}

// Unused-import shim so the doc-link to Arc2D resolves.
#[allow(dead_code)]
fn _unused_imports(_: &Arc2D, _: &Polyline2D, _: &Dimension2D, _: Point2D) {}

#[cfg(test)]
mod tests {
    use super::*;
    use domain::{ParametricWall, WallType};

    fn three_wall_building() -> Building {
        let mut b = Building::default();
        b.wall_types.push(WallType::default());
        b.parametric_walls.push(ParametricWall {
            id: "w0".into(),
            start_point: Vec2::ZERO,
            end_point: Vec2::new(5000.0, 0.0),
            base_height: 0.0,
            top_height: 3000.0,
            wall_type_index: 0,
            ..Default::default()
        });
        b.parametric_walls.push(ParametricWall {
            id: "w1".into(),
            start_point: Vec2::new(5000.0, 0.0),
            end_point: Vec2::new(5000.0, 4000.0),
            base_height: 0.0,
            top_height: 3000.0,
            wall_type_index: 0,
            ..Default::default()
        });
        b.parametric_walls.push(ParametricWall {
            id: "w2".into(),
            start_point: Vec2::new(5000.0, 4000.0),
            end_point: Vec2::ZERO,
            base_height: 0.0,
            top_height: 3000.0,
            wall_type_index: 0,
            ..Default::default()
        });
        b
    }

    #[test]
    fn format_dimension_value_mm_default() {
        assert_eq!(format_dimension_value(5000.4, "mm", 0), "5000");
        assert_eq!(format_dimension_value(5000.4, "mm", 2), "5000.40");
    }

    #[test]
    fn format_dimension_value_feet_inches() {
        assert_eq!(format_dimension_value(10.5, "feet", 0), "10'-6\"");
        assert_eq!(format_dimension_value(8.0, "ft", 0), "8'-0\"");
    }

    #[test]
    fn generate_wall_dimensions_one_per_wall() {
        let b = three_wall_building();
        let dims = generate_wall_dimensions(&b, 300.0);
        assert_eq!(dims.len(), 3);
        assert_eq!(dims[0].id, "dim_0");
        assert_eq!(dims[0].start_point, Vec2::ZERO);
        assert_eq!(dims[0].end_point, Vec2::new(5000.0, 0.0));
        assert_eq!(dims[0].offset_distance, 300.0);
    }

    #[test]
    fn generate_structural_grid_lettered_and_numbered() {
        let b = three_wall_building();
        let grids = generate_structural_grid(&b, 3048.0);
        // Should be at least one horizontal + one vertical line.
        assert!(grids.iter().any(|g| g.label == "1"));
        assert!(grids.iter().any(|g| g.label == "A"));
        // Every grid line should have a bubble enabled.
        for g in &grids {
            assert!(g.show_bubble);
        }
    }

    #[test]
    fn generate_floor_plan_contains_dimensions_grid_and_north_arrow() {
        let b = three_wall_building();
        let set = generate_floor_plan(&b, "Level 1");
        assert_eq!(set.plan_type, PlanType::FloorPlan);
        assert_eq!(set.level, "Level 1");
        assert_eq!(set.name, "Floor Plan - Level 1");
        assert_eq!(set.dimensions.len(), 3);
        assert!(!set.grid_lines.is_empty());
        assert!(
            set.symbols
                .iter()
                .any(|s| s.symbol_type == SymbolType::NorthArrow)
        );
    }

    #[test]
    fn generate_roof_plan_has_grid_and_north_arrow_but_no_dimensions() {
        let b = three_wall_building();
        let set = generate_roof_plan(&b);
        assert_eq!(set.plan_type, PlanType::RoofPlan);
        assert_eq!(set.level, "Roof");
        assert!(set.dimensions.is_empty());
        assert!(!set.grid_lines.is_empty());
        assert!(
            set.symbols
                .iter()
                .any(|s| s.symbol_type == SymbolType::NorthArrow)
        );
    }

    #[test]
    fn to_slice_result_emits_lines_plus_circles_plus_text() {
        let b = three_wall_building();
        let set = generate_floor_plan(&b, "Level 1");
        let result = to_slice_result(&set);

        // Each dimension expands to 3 lines + 1 text label.
        let expected_dim_lines = set.dimensions.len() * 3;
        // Each grid line emits 1 line.
        let expected_grid_lines = set.grid_lines.len();
        assert_eq!(result.lines.len(), expected_dim_lines + expected_grid_lines);

        // Each grid bubble emits a circle.
        let bubbles = set.grid_lines.iter().filter(|g| g.show_bubble).count();
        // Plus 1 circle for the north arrow.
        assert_eq!(result.circles.len(), bubbles + 1);

        // Dimension texts + grid bubble labels + north arrow "N".
        let expected_texts = set.dimensions.len() + bubbles + 1;
        assert_eq!(result.annotations.len(), expected_texts);
    }

    #[test]
    fn empty_building_falls_back_to_default_bounds() {
        let b = Building::default();
        let set = generate_floor_plan(&b, "Level 1");
        // Default bounds give a 10k × 10k viewport plus 2k margin → 12k.
        assert!(set.viewport_width > 0.0);
        assert!(set.viewport_height > 0.0);
    }
}
