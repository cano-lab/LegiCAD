//! High-level generation: `SchemaDocument` → `BuildingGeometry`.
//!
//! Port of `ArchGeometry::generateFromSchema` (`Shared/ArchGeometry/src/archgeometry.cpp:75`).
//!
//! Behaviour intentionally identical to the C++:
//! - Walls without a matching entry in `wall_types` fall back to a 150 mm
//!   "default" wall type (`generateFromSchema:80-87`).
//! - Doors/windows are filtered onto their host wall by `wall_index`.
//! - `BuildingGeometry::bounds_min/bounds_max` are NOT computed here (they
//!   stay at the default `Vec3::ZERO`) to mirror the C++ behaviour — the
//!   M1 diff oracle depends on the same bytes coming out.

use crate::arch::geometry_types::BuildingGeometry;
use crate::arch::schema_types::{SchemaDocument, SchemaRoom, WallLayer, WallType};
use crate::arch::{floor_geometry, opening_geometry, roof_geometry, room_geometry, wall_geometry};

/// Generate full building geometry from a parsed schema document.
#[must_use]
pub fn generate_from_schema(doc: &SchemaDocument) -> BuildingGeometry {
    let mut result = BuildingGeometry {
        building_id: doc.building_id.clone(),
        ..Default::default()
    };

    let default_wall_type = WallType {
        id: "default".into(),
        name: "Default Wall".into(),
        layers: vec![WallLayer {
            name: "structure".into(),
            thickness: 150.0,
            ..Default::default()
        }],
    };

    // Walls. The schema's `wall_types` is a Vec; the C++ uses a map keyed
    // by id, so look up by id linearly here.
    let wall_type_by_id =
        |id: &str| -> Option<&WallType> { doc.wall_types.iter().find(|wt| wt.id == id) };

    for (i, wall) in doc.walls.iter().enumerate() {
        let wt = wall_type_by_id(&wall.wall_type).unwrap_or(&default_wall_type);

        let i_i32 = i32::try_from(i).expect("wall index fits in i32");
        let doors_on_wall: Vec<_> = doc
            .doors
            .iter()
            .filter(|d| d.wall_index == i_i32)
            .cloned()
            .collect();
        let windows_on_wall: Vec<_> = doc
            .windows
            .iter()
            .filter(|w| w.wall_index == i_i32)
            .cloned()
            .collect();

        let geom = wall_geometry::generate(wall, wt, &doors_on_wall, &windows_on_wall);
        result.walls.push(geom);
    }

    // Floors.
    for floor in &doc.floors {
        result.floors.push(floor_geometry::generate(floor));
    }

    // Roofs.
    for roof in &doc.roofs {
        result.roofs.push(roof_geometry::generate(roof));
    }

    // Doors — only those whose `wall_index` references a valid wall.
    for door in &doc.doors {
        if door.wall_index < 0 {
            continue;
        }
        let Ok(idx) = usize::try_from(door.wall_index) else {
            continue;
        };
        if idx >= doc.walls.len() {
            continue;
        }
        let wall = &doc.walls[idx];
        let thickness = wall_type_by_id(&wall.wall_type).map_or(150.0, WallType::total_thickness);
        result
            .doors
            .push(opening_geometry::generate_door(door, wall, thickness));
    }

    // Windows.
    for window in &doc.windows {
        if window.wall_index < 0 {
            continue;
        }
        let Ok(idx) = usize::try_from(window.wall_index) else {
            continue;
        };
        if idx >= doc.walls.len() {
            continue;
        }
        let wall = &doc.walls[idx];
        let thickness = wall_type_by_id(&wall.wall_type).map_or(150.0, WallType::total_thickness);
        result
            .windows
            .push(opening_geometry::generate_window(window, wall, thickness));
    }

    // Rooms — iterate the schema map. The JSON encodes room ids as map keys,
    // not as fields inside each room object, so SchemaRoom.id deserializes to
    // "" by default. Inject the key here so the generated RoomBoundary.room_id
    // is populated (matches C++ parseRoom() which sets room.id = key). Without
    // this, all rooms share an empty id and the dump's sort-by-id becomes
    // non-deterministic.
    for (id, room) in &doc.rooms {
        let room_with_id = if room.id.is_empty() {
            SchemaRoom {
                id: id.clone(),
                ..room.clone()
            }
        } else {
            room.clone()
        };
        result
            .rooms
            .push(room_geometry::generate_boundary(&room_with_id, &doc.walls));
    }

    result
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::arch::parse_file;
    use std::path::PathBuf;

    fn fixture(name: &str) -> PathBuf {
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../..")
            .join("test-data")
            .join(name)
    }

    #[test]
    fn corpus_generates_walls_and_floors() {
        let doc = parse_file(fixture("test_building_qbd.json")).unwrap();
        let g = generate_from_schema(&doc);

        // 8 walls × 24 verts each (no openings in this fixture, default thickness).
        assert_eq!(g.walls.len(), 8);
        for w in &g.walls {
            assert_eq!(w.mesh_3d.vertex_count(), 24);
        }
        // 3 floors.
        assert_eq!(g.floors.len(), 3);
        // No roofs / doors / windows / rooms in this fixture.
        assert!(g.roofs.is_empty());
        assert!(g.doors.is_empty());
        assert!(g.windows.is_empty());
        assert!(g.rooms.is_empty());
    }
}
