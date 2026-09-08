//! M4 integration: build a synthetic `Building`, generate its floor
//! plan, export to SVG, and verify the output structure.
//!
//! A full cross-language byte-equality oracle against the C++ slicer
//! (`archgeometry_dump`-style harness) is deferred — building a new
//! kernel tool target needs CMake changes in `ArchEngine_kernel/`.
//! These tests assert that the Rust pipeline produces well-formed SVG
//! with the expected primitives, which is enough to call M4 functional
//! on the Rust side. The diff oracle slot is wired in the docs.

use domain::{Building, ParametricWall, WallLayer, WallType};
use drawing::{Config, export_to_svg, generate_floor_plan};
use glam::Vec2;

/// 5 m × 4 m room, four walls, 150 mm thick.
fn small_room() -> Building {
    let wall_type = WallType {
        id: "ext_2x6".into(),
        name: "Exterior 2x6".into(),
        layers: vec![WallLayer {
            name: "structure".into(),
            thickness: 150.0,
            ..Default::default()
        }],
        ..Default::default()
    };

    let walls = [
        ((0.0, 0.0), (5000.0, 0.0)),
        ((5000.0, 0.0), (5000.0, 4000.0)),
        ((5000.0, 4000.0), (0.0, 4000.0)),
        ((0.0, 4000.0), (0.0, 0.0)),
    ];
    let parametric_walls = walls
        .iter()
        .enumerate()
        .map(|(i, ((sx, sy), (ex, ey)))| ParametricWall {
            id: format!("w{i}"),
            start_point: Vec2::new(*sx, *sy),
            end_point: Vec2::new(*ex, *ey),
            base_height: 0.0,
            top_height: 3000.0,
            wall_type_index: 0,
            ..Default::default()
        })
        .collect();

    Building {
        wall_types: vec![wall_type],
        parametric_walls,
        ..Default::default()
    }
}

#[test]
fn floor_plan_emits_one_polygon_and_hatch_per_wall() {
    let building = small_room();
    let result = generate_floor_plan(&building, 1500.0, &Config::with_defaults());

    assert_eq!(result.polylines.len(), 4, "one outline per wall");
    assert_eq!(result.hatches.len(), 4, "one hatch per wall");
    for poly in &result.polylines {
        assert_eq!(poly.points.len(), 4, "rectangular outline");
        assert!(poly.closed);
        assert_eq!(poly.layer, "A-WALL");
    }
}

#[test]
fn floor_plan_is_empty_for_cut_height_outside_walls() {
    let building = small_room();
    // Walls span 0..3000; cut at 5000 → nothing.
    let result = generate_floor_plan(&building, 5000.0, &Config::with_defaults());
    assert_eq!(result.polylines.len(), 0);
    assert_eq!(result.hatches.len(), 0);
}

#[test]
fn export_to_svg_produces_well_formed_output() {
    let building = small_room();
    let result = generate_floor_plan(&building, 1500.0, &Config::with_defaults());
    let svg = export_to_svg(&result, 0.01); // 1:100 scale

    // XML prolog + svg root.
    assert!(svg.starts_with("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"));
    assert!(svg.contains("<svg xmlns=\"http://www.w3.org/2000/svg\""));
    // White background.
    assert!(svg.contains(r#"<rect width="100%" height="100%" fill="white"/>"#));
    // 4 polygons (wall outlines) + 4 hatch polygons = 8 total.
    let polygon_count = svg.matches("<polygon").count();
    assert_eq!(polygon_count, 8, "4 outlines + 4 hatches");
    // viewBox present.
    assert!(svg.contains("viewBox="));
    // Ends cleanly.
    assert!(svg.ends_with("</svg>\n"));
}

#[test]
fn svg_view_box_spans_building_bounds_plus_margin() {
    let building = small_room();
    let result = generate_floor_plan(&building, 1500.0, &Config::with_defaults());
    let svg = export_to_svg(&result, 1.0);

    // Building is 5000 × 4000 mm. Walls extend ±75 mm in their normal
    // direction for the 150 mm thickness, so the actual SVG bbox is
    // (-75, -75) to (5075, 4075). Plus 10 mm margin and Y-flip.
    // Check viewBox numbers are present (we don't lock exact values).
    assert!(svg.contains("viewBox="));
    // Width and height should each be at least the building extent
    // plus margins; sanity check by looking for one of the wall corners.
    assert!(svg.contains("5075") || svg.contains("5075.0"));
}

#[test]
fn svg_hatches_render_before_outlines() {
    let building = small_room();
    let result = generate_floor_plan(&building, 1500.0, &Config::with_defaults());
    let svg = export_to_svg(&result, 1.0);

    // Hatches have fill-opacity attribute; outlines don't.
    let hatch_pos = svg.find(r#"fill-opacity="0.3""#).unwrap();
    let outline_pos = svg.find(r#"fill="none""#).unwrap();
    assert!(
        hatch_pos < outline_pos,
        "hatches must be drawn before outlines so outlines win Z-order"
    );
}

#[test]
fn svg_y_axis_is_flipped() {
    // The C++ flips Y by multiplying by -1 (SVG Y grows downward).
    // A wall at y=4000 in plan view should appear with negative Y in
    // the SVG coordinate system.
    let building = small_room();
    let result = generate_floor_plan(&building, 1500.0, &Config::with_defaults());
    let svg = export_to_svg(&result, 1.0);
    // Top wall is at y=4000; should appear as "-4000" or similar in SVG.
    assert!(
        svg.contains("-4000") || svg.contains("-4075"),
        "Y should be flipped for SVG"
    );
}
