//! Integration test for the kernel's `test_building.json` legacy fixture.

use domain::ElementType;
use geometry_loader::parse_file;
use std::path::PathBuf;

fn fixture() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .join("test-data")
        .join("test_building.json")
}

#[test]
fn legacy_test_building_loads_with_expected_element_counts() {
    let b = parse_file(fixture()).expect("test_building.json must parse");
    assert_eq!(b.name, "Test Building with Terrain");
    // From the fixture: 8 walls (2 levels x 4 sides) + 3 slabs + 4 columns = 15.
    assert_eq!(b.elements.len(), 15);

    let walls = b
        .elements
        .iter()
        .filter(|e| e.element_type == ElementType::Wall)
        .count();
    let floors = b
        .elements
        .iter()
        .filter(|e| e.element_type == ElementType::Floor) // "slab" maps to Floor
        .count();
    let columns = b
        .elements
        .iter()
        .filter(|e| e.element_type == ElementType::Column)
        .count();
    assert_eq!(walls, 8);
    assert_eq!(floors, 3);
    assert_eq!(columns, 4);
}

#[test]
fn legacy_test_building_preserves_materials() {
    let b = parse_file(fixture()).unwrap();
    let wall_materials: Vec<_> = b
        .elements
        .iter()
        .filter(|e| e.element_type == ElementType::Wall)
        .map(|e| e.material.as_str())
        .collect();
    assert!(wall_materials.iter().all(|m| *m == "brick"));
}
