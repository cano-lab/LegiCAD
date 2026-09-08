//! M5 end-to-end: load the canonical QBD fixture, run the full
//! conversion + floor-plan pipeline, verify the permit SVG.
//!
//! Also writes the SVG to `target/m5_output/` for manual inspection.

use archgeometry::parse_file;
use qbd::{generate_documentation, layout_to_building, validate_layout};
use std::path::PathBuf;

fn fixture() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .join("test-data")
        .join("test_building_qbd.json")
}

fn fixture_with_openings() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .join("test-data")
        .join("test_building_with_openings.json")
}

#[test]
fn fixture_parses_and_converts_to_building() {
    let doc = parse_file(fixture()).expect("test_building_qbd.json must parse");
    assert_eq!(doc.walls.len(), 8);
    assert_eq!(doc.floors.len(), 3);

    let building = layout_to_building(&doc);
    assert_eq!(building.parametric_walls.len(), 8, "8 walls → 8 parametric");
    assert_eq!(
        building.elements.len(),
        3,
        "3 floors → 3 floor elements (no doors/windows in fixture)"
    );
    // All walls are exterior in the fixture → single default wall type.
    assert_eq!(building.wall_types.len(), 1);
    assert_eq!(building.wall_types[0].id, "ext_2x6_r22_ci");
}

#[test]
fn fixture_generates_permit_floor_plan_svg() {
    let doc = parse_file(fixture()).unwrap();
    let docs = generate_documentation(&doc, "Test Building");

    // Smoke checks on the SVG.
    assert!(docs.floor_plan_svg.starts_with("<?xml version=\"1.0\""));
    assert!(
        docs.floor_plan_svg
            .contains("<svg xmlns=\"http://www.w3.org/2000/svg\"")
    );
    assert!(docs.floor_plan_svg.ends_with("</svg>\n"));
    // The fixture has 8 walls but they're split across two levels (Y=0
    // and Y=3048). The default 1219mm cut height (≈4 ft) only intersects
    // the ground-floor 4 walls → 4 outlines + 4 hatches = 8 wall polygons.
    // Phase 2.5 adds a section-marker overlay with 2 arrow triangles → 10.
    let polygon_count = docs.floor_plan_svg.matches("<polygon").count();
    assert_eq!(
        polygon_count, 10,
        "4 outlines + 4 hatches + 2 section-marker arrows"
    );

    // viewBox present.
    assert!(docs.floor_plan_svg.contains("viewBox="));

    // Persist a copy under target/ for manual inspection.
    let out_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .join("target")
        .join("m5_output");
    let _ = std::fs::create_dir_all(&out_dir);
    let _ = std::fs::write(out_dir.join("test_building_qbd.svg"), &docs.floor_plan_svg);
}

#[test]
fn fixture_validates_walls_through_obc() {
    let doc = parse_file(fixture()).unwrap();
    let obc = obc::OBCEngine::new();
    let r = validate_layout(&obc, &doc, "Zone 6");
    assert_eq!(r.walls_checked, 8);
    // All walls are exterior and use the default R-28.45 type (2x6 + R-22
    // batt + R-5 c.i.) → meets Zone 6's R-24 requirement.
    assert!(r.thermal_compliance);
    // Per-wall reports exist for each input wall.
    assert_eq!(r.wall_reports.len(), 8);
}

#[test]
fn fixture_documentation_includes_metadata() {
    let doc = parse_file(fixture()).unwrap();
    let docs = generate_documentation(&doc, "Permit-Set Test");
    assert_eq!(docs.project_name, "Permit-Set Test");
    // generated_date is YYYY-MM-DD.
    assert_eq!(docs.generated_date.len(), 10);
}

#[test]
fn openings_fixture_produces_both_schedule_sheets() {
    // The main qbd fixture has zero doors/windows, so the schedule code
    // paths never run. This fixture has 3 doors + 3 windows and asserts
    // both schedules emit non-empty SVG with one row per opening plus
    // the canonical headers (MARK / WIDTH / TYPE / LOCATION / etc.).
    let doc = parse_file(fixture_with_openings()).expect("fixture must parse");
    assert_eq!(doc.doors.len(), 3, "fixture should have 3 doors");
    assert_eq!(doc.windows.len(), 3, "fixture should have 3 windows");

    let docs = generate_documentation(&doc, "Openings Test");

    // Door schedule.
    let ds = &docs.door_schedule_svg;
    assert!(!ds.is_empty(), "door_schedule_svg must be non-empty");
    assert!(ds.contains("DOOR SCHEDULE"));
    assert!(ds.contains(">D1<"));
    assert!(ds.contains(">D2<"));
    assert!(ds.contains(">D3<"));
    // Width 914mm → "Single Door" (per the C++ thresholds), 1800mm →
    // "Double Door", 2400mm → "Sliding Door".
    assert!(ds.contains(">Single Door<"));
    assert!(ds.contains(">Double Door<"));
    assert!(ds.contains(">Sliding Door<"));

    // Window schedule.
    let ws = &docs.window_schedule_svg;
    assert!(!ws.is_empty(), "window_schedule_svg must be non-empty");
    assert!(ws.contains("WINDOW SCHEDULE"));
    assert!(ws.contains(">W1<"));
    assert!(ws.contains(">W2<"));
    assert!(ws.contains(">W3<"));
    // 600mm → "Casement", 1200mm → "Double Hung", 1800mm → "Picture Window".
    assert!(ws.contains(">Casement<"));
    assert!(ws.contains(">Double Hung<"));
    assert!(ws.contains(">Picture Window<"));
    // Sill heights show up in remarks.
    assert!(ws.contains("Sill 1100mm"));
}
