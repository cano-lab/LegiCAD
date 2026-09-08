//! Milestone M1a: parse the C++ test JSON corpus into `SchemaDocument`s
//! without losing or corrupting data.
//!
//! Fixtures live in `rust/test-data/` (copies of the kernel's
//! `ArchEngine_kernel/test_building*.json`). If a kernel-side update
//! changes the schema, refresh the copies via:
//!
//! ```powershell
//! Copy-Item F:/Software/ArchEngine_Suite_Kernel/ArchEngine_kernel/test_building*.json `
//!           F:/Software/LegibleStudios/rust/test-data/
//! ```

use archgeometry::parse_file;
use glam::Vec3;
use std::path::PathBuf;

fn fixture(name: &str) -> PathBuf {
    // CARGO_MANIFEST_DIR is the crate root (crates/archgeometry/), so go
    // up two to the workspace root, then down to test-data/.
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .join("test-data")
        .join(name)
}

#[test]
fn parses_test_building_qbd() {
    let doc = parse_file(fixture("test_building_qbd.json"))
        .expect("test_building_qbd.json must parse without error");

    // Verify the values from the JSON file directly.
    assert_eq!(doc.width, 9144.0);
    assert_eq!(doc.depth, 12192.0);
    assert_eq!(doc.sqft, 1200.0);

    // 8 walls (4 on each of 2 levels).
    assert_eq!(doc.walls.len(), 8, "expected 8 walls");

    // First wall: ground floor, X axis, brick exterior.
    let w0 = &doc.walls[0];
    assert_eq!(w0.start, Vec3::new(0.0, 0.0, 0.0));
    assert_eq!(w0.end, Vec3::new(9144.0, 0.0, 0.0));
    assert_eq!(w0.height, 3048.0);
    assert_eq!(w0.wall_type, "brick");
    assert_eq!(w0.category, "exterior");

    // 3 floors total (Level 1, Level 2, Roof).
    assert_eq!(doc.floors.len(), 3, "expected 3 floors");
    assert_eq!(doc.floors[0].level_name, "Level 1");
    assert_eq!(doc.floors[1].level_name, "Level 2");
    assert_eq!(doc.floors[2].level_name, "Roof");
    assert_eq!(doc.floors[0].thickness, 200.0);

    // No rooms / doors / windows / roofs / wall_types in this fixture.
    assert!(doc.rooms.is_empty());
    assert!(doc.doors.is_empty());
    assert!(doc.windows.is_empty());
    assert!(doc.roofs.is_empty());
    assert!(doc.wall_types.is_empty());
}

#[test]
fn computes_wall_lengths_from_corpus() {
    let doc = parse_file(fixture("test_building_qbd.json")).unwrap();

    // The 4 ground-floor walls form a 9144 × 12192 rectangle.
    let mut total_perimeter = 0.0_f32;
    for w in &doc.walls[..4] {
        total_perimeter += w.length();
    }
    let expected = 2.0 * (9144.0 + 12192.0);
    assert!(
        (total_perimeter - expected).abs() < 0.01,
        "ground-floor perimeter mismatch: got {total_perimeter}, expected {expected}"
    );
}
