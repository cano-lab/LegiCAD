//! Approaches Milestone M1: generate `WallGeometry` + `FloorGeometry` from
//! the parsed test corpus and check the structural properties hold.
//!
//! When more generators land (rooms / roofs / openings) this test grows.
//! Bit-identical vertex/coordinate diff against the C++ output is a future
//! milestone — for now we assert counts, bounds, and that no generator
//! returns empty output for a non-degenerate input.

use archgeometry::geometry_types::{Mesh3D, WallGeometry};
use archgeometry::schema_types::{WallLayer, WallType};
use archgeometry::{floor_geometry, parse_file, wall_geometry};
use glam::Vec3;
use std::path::PathBuf;

fn fixture(name: &str) -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .join("test-data")
        .join(name)
}

/// Synthetic 150mm-thick wall type used in lieu of the missing `wall_types`
/// entries in the test fixture. The point of this test is to exercise the
/// generators, not to validate the schema's `wall_types` resolution.
fn synthetic_brick_wall() -> WallType {
    WallType {
        id: "brick".into(),
        name: "Brick (synthetic)".into(),
        layers: vec![WallLayer {
            name: "brick".into(),
            material: "brick".into(),
            thickness: 150.0,
            ..Default::default()
        }],
    }
}

#[test]
fn every_wall_in_corpus_generates_a_non_empty_mesh() {
    let doc = parse_file(fixture("test_building_qbd.json")).unwrap();
    let wt = synthetic_brick_wall();

    assert!(!doc.walls.is_empty(), "fixture must have walls");

    for (i, wall) in doc.walls.iter().enumerate() {
        let g = wall_geometry::generate(wall, &wt, &[], &[]);
        assert_eq!(
            g.mesh_3d.vertex_count(),
            24,
            "wall {i}: solid wall = 24 verts"
        );
        assert_eq!(
            g.mesh_3d.triangle_count(),
            12,
            "wall {i}: solid wall = 12 tris"
        );
        assert!(
            g.cutouts.is_empty(),
            "wall {i}: no doors/windows in fixture"
        );
        assert_eq!(g.mesh_3d.element_type, "wall");
        // The plan polygon must have 4 corners.
        assert_eq!(g.plan_view.polygons.len(), 1);
        assert_eq!(g.plan_view.polygons[0].points.len(), 4);
    }
}

#[test]
fn corpus_walls_aggregate_to_expected_totals() {
    let doc = parse_file(fixture("test_building_qbd.json")).unwrap();
    let wt = synthetic_brick_wall();

    let walls: Vec<WallGeometry> = doc
        .walls
        .iter()
        .map(|w| wall_geometry::generate(w, &wt, &[], &[]))
        .collect();

    // 8 walls × 24 verts / 12 tris.
    let total_verts: usize = walls.iter().map(|w| w.mesh_3d.vertex_count()).sum();
    let total_tris: usize = walls.iter().map(|w| w.mesh_3d.triangle_count()).sum();
    assert_eq!(total_verts, 8 * 24);
    assert_eq!(total_tris, 8 * 12);

    // All 8 walls are exterior in the fixture.
    for w in &walls {
        assert_eq!(w.plan_view.polygons[0].layer, "walls_exterior");
    }
}

#[test]
fn every_floor_in_corpus_generates_a_non_empty_mesh() {
    let doc = parse_file(fixture("test_building_qbd.json")).unwrap();
    assert!(!doc.floors.is_empty(), "fixture must have floors");

    for (i, floor) in doc.floors.iter().enumerate() {
        let g = floor_geometry::generate(floor);
        assert_eq!(
            g.mesh_3d.vertex_count(),
            24,
            "floor {i}: 6 quads = 24 verts"
        );
        assert_eq!(
            g.mesh_3d.triangle_count(),
            12,
            "floor {i}: 6 quads = 12 tris"
        );
        assert_eq!(g.mesh_3d.element_type, "floor");
        assert_eq!(g.plan_view.polygons.len(), 1);
        assert_eq!(g.plan_view.polygons[0].points.len(), 4);
    }
}

#[test]
fn corpus_floor_elevations_match_levels() {
    let doc = parse_file(fixture("test_building_qbd.json")).unwrap();

    // Fixture: Level 1 at y=0, Level 2 at y=3048, Roof at y=6096.
    let elevations: Vec<f32> = doc.floors.iter().map(|f| f.start.y).collect();
    assert_eq!(elevations, vec![0.0, 3048.0, 6096.0]);

    // Slabs are 200mm thick: each floor's mesh bottom = start.y - 200.
    for floor in &doc.floors {
        let (min, max) = floor_geometry::bounds(floor);
        assert_eq!(max.y, floor.start.y);
        assert!((min.y - (floor.start.y - 200.0)).abs() < 1e-3);
    }
}

#[test]
fn corpus_walls_form_a_closed_perimeter_on_each_level() {
    // Sanity check: the 4 ground-floor walls cover the rectangle bounds
    // exactly. Sum of |start - end| should equal the perimeter 2*(W+D).
    let doc = parse_file(fixture("test_building_qbd.json")).unwrap();

    let ground_floor_walls: Vec<_> = doc.walls.iter().filter(|w| w.start.y == 0.0).collect();
    assert_eq!(ground_floor_walls.len(), 4);

    let total: f32 = ground_floor_walls.iter().map(|w| w.length()).sum();
    let expected = 2.0 * (doc.width + doc.depth);
    assert!(
        (total - expected).abs() < 0.01,
        "got {total}, expected {expected}"
    );
}

#[test]
fn aggregated_building_mesh_grows_linearly_with_walls() {
    // The all-walls merged mesh should have exactly the sum of vertex
    // counts (Mesh3D::merge doesn't deduplicate, by design).
    let doc = parse_file(fixture("test_building_qbd.json")).unwrap();
    let wt = synthetic_brick_wall();

    let mut combined = Mesh3D::default();
    for wall in &doc.walls {
        let g = wall_geometry::generate(wall, &wt, &[], &[]);
        combined.merge(&g.mesh_3d);
    }

    assert_eq!(combined.vertex_count(), doc.walls.len() * 24);
    assert_eq!(combined.triangle_count(), doc.walls.len() * 12);
}

#[test]
fn wall_plan_polygons_have_correct_perp_offset_for_axis_aligned_walls() {
    // For a wall along +X at y=0,z=0 with thickness 150, the four polygon
    // corners must be at (x_start, ±75) and (x_end, ∓75).
    let doc = parse_file(fixture("test_building_qbd.json")).unwrap();
    let wall0 = &doc.walls[0];
    assert_eq!(wall0.start, Vec3::ZERO);
    assert_eq!(wall0.end, Vec3::new(9144.0, 0.0, 0.0));

    let poly = wall_geometry::generate_plan_polygon(wall0, 150.0);
    let pts = &poly.points;
    // Sort by (x, z) so the assertion order is stable.
    let mut xs: Vec<(f32, f32)> = pts.iter().map(|p| (p.x, p.y)).collect();
    xs.sort_by(|a, b| {
        a.0.partial_cmp(&b.0)
            .unwrap()
            .then(a.1.partial_cmp(&b.1).unwrap())
    });
    assert_eq!(xs[0], (0.0, -75.0));
    assert_eq!(xs[1], (0.0, 75.0));
    assert_eq!(xs[2], (9144.0, -75.0));
    assert_eq!(xs[3], (9144.0, 75.0));
}
