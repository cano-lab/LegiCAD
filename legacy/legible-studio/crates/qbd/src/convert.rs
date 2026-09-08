//! `SchemaDocument` → `domain::Building` conversion.
//!
//! Ported from `QBDInterface::toBuilding` (`qbd_interface.cpp:528`).
//!
//! Scope note: the C++ runs each wall through
//! `Geometry::CSG::wallWithMultipleOpenings` to emit per-layer
//! `StructuralElement`s with mesh data. That path is **3D-render only**
//! — the floor-plan slicer reads from `parametric_walls` + `wall_types`,
//! not from element meshes. We skip the per-layer mesh generation here
//! to keep the conversion light. If the renderer ever needs the meshes,
//! `wall_geometry::generate` already produces them and can be wired in.

use archgeometry::{
    SchemaDocument, SchemaDoor, SchemaFloor, SchemaRoof, SchemaWall, SchemaWindow,
    WallType as SchemaWallType,
};
use domain::{Building, ElementType, ParametricWall, StructuralElement, WallType, materials};
use glam::{Vec2, Vec3};

use crate::wall_types;

// ---------------------------------------------------------------------------
// Wall types
// ---------------------------------------------------------------------------

/// Map an `archgeometry::WallType` (wire format with string `function`,
/// RGBA color) into a `domain::WallType` (enum `LayerFunction`, RGB
/// color). Used when the schema supplies its own wall types.
#[must_use]
pub fn schema_wall_type_to_domain(swt: &SchemaWallType) -> WallType {
    use domain::{LayerFunction, WallLayer};

    let layers = swt
        .layers
        .iter()
        .map(|l| WallLayer {
            name: l.name.clone(),
            material: l.material.clone(),
            function: match l.function.as_str() {
                "exterior_finish" | "siding" => LayerFunction::ExteriorFinish,
                "sheathing" => LayerFunction::Sheathing,
                "insulation" => LayerFunction::Insulation,
                "membrane" | "vapor_barrier" => LayerFunction::Membrane,
                "interior_finish" | "finish" => LayerFunction::InteriorFinish,
                "air_gap" | "air" => LayerFunction::AirGap,
                _ => LayerFunction::Structure,
            },
            thickness: l.thickness,
            color: Vec3::new(l.color[0], l.color[1], l.color[2]),
            r_value: l.r_value,
            fasteners: Vec::new(),
        })
        .collect();

    WallType {
        id: swt.id.clone(),
        name: swt.name.clone(),
        layers,
        ..Default::default()
    }
}

/// Resolve the wall type a `SchemaWall` should use:
/// - The wall's `wall_type` id, if it matches an entry in `building.wall_types`.
/// - Otherwise the default for the wall's `category` (`exterior` / `interior` /
///   `wet_wall`), inserted into `building.wall_types` if not already there.
///
/// Returns the index into `building.wall_types`.
pub fn wall_type_for_wall(building: &mut Building, wall: &SchemaWall) -> u32 {
    if !wall.wall_type.is_empty()
        && let Some(idx) = building
            .wall_types
            .iter()
            .position(|wt| wt.id == wall.wall_type || wt.name == wall.wall_type)
    {
        return u32::try_from(idx).expect("wall_type index fits in u32");
    }

    // Fall back to the category default — inject into wall_types if absent.
    let default = wall_types::for_category(&wall.category);
    if let Some(idx) = building
        .wall_types
        .iter()
        .position(|wt| wt.id == default.id)
    {
        u32::try_from(idx).expect("wall_type index fits in u32")
    } else {
        building.wall_types.push(default);
        u32::try_from(building.wall_types.len() - 1).expect("wall_type index fits in u32")
    }
}

// ---------------------------------------------------------------------------
// Parametric walls
// ---------------------------------------------------------------------------

/// Convert every `SchemaWall` into a `ParametricWall`. The wall-type
/// index is resolved against `building.wall_types` (which is mutated as
/// new defaults are injected).
pub fn walls_to_parametric(building: &mut Building, walls: &[SchemaWall]) {
    for (i, wall) in walls.iter().enumerate() {
        let wt_idx = wall_type_for_wall(building, wall);
        building.parametric_walls.push(ParametricWall {
            id: format!("wall_{i}"),
            // The schema's Vec3 has Y as elevation, Z as depth (plan-view Y).
            start_point: Vec2::new(wall.start.x, wall.start.z),
            end_point: Vec2::new(wall.end.x, wall.end.z),
            base_height: wall.start.y,
            top_height: wall.start.y + wall.height,
            wall_type_index: wt_idx,
            category: wall.category.clone(),
            existing: wall.is_existing(),
            ..Default::default()
        });
    }
}

// ---------------------------------------------------------------------------
// Structural elements (floors, roofs, doors, windows)
// ---------------------------------------------------------------------------

fn floor_to_element(floor: &SchemaFloor) -> StructuralElement {
    // Matches `qbd_interface.cpp:679-697`: start = bottom-left corner with
    // y = floor elevation; end's Y is elevation + thickness (the top of
    // the slab above the elevation reference). width/depth are XZ extents.
    StructuralElement {
        element_type: ElementType::Floor,
        start: floor.start,
        end: Vec3::new(floor.end.x, floor.start.y + floor.thickness, floor.end.z),
        width: (floor.end.x - floor.start.x).abs(),
        depth: (floor.end.z - floor.start.z).abs(),
        material: "floor_slab".into(),
        ..Default::default()
    }
}

fn door_to_element(door: &SchemaDoor, walls: &[SchemaWall]) -> Option<StructuralElement> {
    let wall_idx = usize::try_from(door.wall_index).ok()?;
    let wall = walls.get(wall_idx)?;

    let wall_dir = (wall.end - wall.start).normalize_or_zero();
    let wall_length_xz = Vec2::new(wall.end.x - wall.start.x, wall.end.z - wall.start.z).length();

    let door_offset = door
        .offset
        .clamp(0.0, (wall_length_xz - door.width).max(0.0));
    let door_center = wall.start + wall_dir * (door_offset + door.width * 0.5);

    let start = Vec3::new(
        door_center.x - wall_dir.x * door.width * 0.5,
        wall.start.y,
        door_center.z - wall_dir.z * door.width * 0.5,
    );
    let end = Vec3::new(
        door_center.x + wall_dir.x * door.width * 0.5,
        wall.start.y + door.height,
        door_center.z + wall_dir.z * door.width * 0.5,
    );

    Some(StructuralElement {
        element_type: ElementType::Door,
        start,
        end,
        width: door.width,
        depth: 100.0, // door thickness ~100mm (matches C++)
        material: "door".into(),
        rotation: wall_dir.z.atan2(wall_dir.x),
        ..Default::default()
    })
}

fn window_to_element(window: &SchemaWindow, walls: &[SchemaWall]) -> Option<StructuralElement> {
    let wall_idx = usize::try_from(window.wall_index).ok()?;
    let wall = walls.get(wall_idx)?;

    let wall_dir = (wall.end - wall.start).normalize_or_zero();
    let wall_length_xz = Vec2::new(wall.end.x - wall.start.x, wall.end.z - wall.start.z).length();

    let win_offset = window
        .offset
        .clamp(0.0, (wall_length_xz - window.width).max(0.0));
    let win_center = wall.start + wall_dir * (win_offset + window.width * 0.5);
    let sill_y = wall.start.y + window.sill_height;

    let start = Vec3::new(
        win_center.x - wall_dir.x * window.width * 0.5,
        sill_y,
        win_center.z - wall_dir.z * window.width * 0.5,
    );
    let end = Vec3::new(
        win_center.x + wall_dir.x * window.width * 0.5,
        sill_y + window.height,
        win_center.z + wall_dir.z * window.width * 0.5,
    );

    Some(StructuralElement {
        element_type: ElementType::Window,
        start,
        end,
        width: window.width,
        depth: 50.0, // window thickness ~50mm (matches C++)
        material: "window".into(),
        rotation: wall_dir.z.atan2(wall_dir.x),
        ..Default::default()
    })
}

/// Convert one roof surface to a `StructuralElement` with mesh data.
/// Preserves the C++ winding-fix at `qbd_interface.cpp:728-751`: derive
/// the surface normal from the first triangle, reverse the fan winding
/// if it points down so triangles always face up.
fn roof_surface_to_element(surface: &archgeometry::RoofSurface) -> Option<StructuralElement> {
    if surface.vertices.len() < 3 {
        return None;
    }

    let v0 = surface.vertices[0];
    let v1 = surface.vertices[1];
    let v2 = surface.vertices[2];
    let normal = (v1 - v0).cross(v2 - v0);
    let reverse_winding = normal.y < 0.0;

    let mut min = Vec3::splat(f32::MAX);
    let mut max = Vec3::splat(f32::MIN);
    for v in &surface.vertices {
        min = min.min(*v);
        max = max.max(*v);
    }

    let mut mesh = domain::MeshData::default();
    mesh.vertices.extend_from_slice(&surface.vertices);
    for i in 1..surface.vertices.len() - 1 {
        let i_u32 = u32::try_from(i).expect("vertex count fits in u32");
        let i_plus = i_u32 + 1;
        let face = if reverse_winding {
            [0, i_plus, i_u32]
        } else {
            [0, i_u32, i_plus]
        };
        mesh.faces.push(face);
    }

    Some(StructuralElement {
        element_type: ElementType::Roof,
        start: min,
        end: max,
        width: max.x - min.x,
        depth: max.z - min.z,
        material: "roof_shingle".into(),
        mesh,
        ..Default::default()
    })
}

fn roofs_to_elements(roofs: &[SchemaRoof]) -> Vec<StructuralElement> {
    let mut out = Vec::new();
    for roof in roofs {
        for surface in &roof.surfaces {
            if let Some(elem) = roof_surface_to_element(surface) {
                out.push(elem);
            }
        }
    }
    out
}

// ---------------------------------------------------------------------------
// Top-level: SchemaDocument → Building
// ---------------------------------------------------------------------------

/// Convert a parsed `SchemaDocument` into a `domain::Building` ready for
/// floor-plan generation. The output's `wall_types` always contains at
/// least the wall types each wall actually references (defaults injected
/// as needed) — no orphan entries.
#[must_use]
pub fn layout_to_building(doc: &SchemaDocument) -> Building {
    let mut building = Building {
        name: "QBD Generated Building".into(),
        ..Default::default()
    };

    // Seed wall_types from the schema (if any). Walls without an explicit
    // wall_type fall back to category defaults injected by
    // wall_type_for_wall below.
    for swt in &doc.wall_types {
        building.wall_types.push(schema_wall_type_to_domain(swt));
    }

    // Parametric walls — sets wall_type_index, injects defaults.
    walls_to_parametric(&mut building, &doc.walls);

    // Floors, doors, windows as structural elements.
    for floor in &doc.floors {
        building.elements.push(floor_to_element(floor));
    }
    for door in &doc.doors {
        if let Some(elem) = door_to_element(door, &doc.walls) {
            building.elements.push(elem);
        }
    }
    for window in &doc.windows {
        if let Some(elem) = window_to_element(window, &doc.walls) {
            building.elements.push(elem);
        }
    }
    building.elements.extend(roofs_to_elements(&doc.roofs));

    // Hint to the renderer about typical room material.
    let _ = materials::DRYWALL; // silence unused import for now

    building
}

#[cfg(test)]
mod tests {
    use super::*;
    use archgeometry::{SchemaDoor, SchemaFloor, SchemaWall, SchemaWindow};

    fn ext_wall(start_x: f32, end_x: f32, end_z: f32) -> SchemaWall {
        SchemaWall {
            start: Vec3::new(start_x, 0.0, 0.0),
            end: Vec3::new(end_x, 0.0, end_z),
            height: 2700.0,
            wall_type: String::new(),
            category: "exterior".into(),
            ..Default::default()
        }
    }

    #[test]
    fn wall_type_for_wall_injects_category_default_when_missing() {
        let mut b = Building::default();
        let wall = ext_wall(0.0, 5000.0, 0.0);
        let idx = wall_type_for_wall(&mut b, &wall);
        // Default exterior wall type was added.
        assert_eq!(b.wall_types.len(), 1);
        assert_eq!(b.wall_types[idx as usize].id, "ext_2x6_r22_ci");
        // Second exterior wall reuses the same index.
        let idx2 = wall_type_for_wall(&mut b, &wall);
        assert_eq!(idx, idx2);
        assert_eq!(b.wall_types.len(), 1, "no duplicate default added");
    }

    #[test]
    fn wall_type_for_wall_uses_named_type_when_present() {
        let mut b = Building::default();
        b.wall_types.push(wall_types::exterior_2x6_r21());
        let mut wall = ext_wall(0.0, 5000.0, 0.0);
        wall.wall_type = "ext_2x6_r21".into();
        let idx = wall_type_for_wall(&mut b, &wall);
        assert_eq!(idx, 0);
        assert_eq!(b.wall_types.len(), 1);
    }

    #[test]
    fn walls_to_parametric_one_per_wall_with_xz_projection() {
        let mut b = Building::default();
        let walls = vec![ext_wall(0.0, 5000.0, 0.0), ext_wall(5000.0, 5000.0, 4000.0)];
        walls_to_parametric(&mut b, &walls);
        assert_eq!(b.parametric_walls.len(), 2);
        assert_eq!(b.parametric_walls[0].start_point, Vec2::ZERO);
        assert_eq!(b.parametric_walls[0].end_point, Vec2::new(5000.0, 0.0));
        // base/top heights derived from Y + height.
        assert_eq!(b.parametric_walls[0].base_height, 0.0);
        assert_eq!(b.parametric_walls[0].top_height, 2700.0);
    }

    #[test]
    fn layout_to_building_round_trips_a_rectangle_room() {
        let doc = SchemaDocument {
            walls: vec![
                ext_wall(0.0, 5000.0, 0.0),
                ext_wall(5000.0, 5000.0, 4000.0),
                SchemaWall {
                    start: Vec3::new(5000.0, 0.0, 4000.0),
                    end: Vec3::new(0.0, 0.0, 4000.0),
                    height: 2700.0,
                    category: "exterior".into(),
                    ..Default::default()
                },
                SchemaWall {
                    start: Vec3::new(0.0, 0.0, 4000.0),
                    end: Vec3::ZERO,
                    height: 2700.0,
                    category: "exterior".into(),
                    ..Default::default()
                },
            ],
            ..Default::default()
        };
        let b = layout_to_building(&doc);
        assert_eq!(b.parametric_walls.len(), 4);
        assert_eq!(b.wall_types.len(), 1, "single exterior default reused");
        assert_eq!(b.wall_types[0].id, "ext_2x6_r22_ci");
    }

    #[test]
    fn layout_with_floor_emits_floor_element() {
        let doc = SchemaDocument {
            floors: vec![SchemaFloor {
                start: Vec3::new(0.0, 0.0, 0.0),
                end: Vec3::new(5000.0, 0.0, 4000.0),
                thickness: 300.0,
                level_name: "Level 1".into(),
                ..Default::default()
            }],
            ..Default::default()
        };
        let b = layout_to_building(&doc);
        assert_eq!(b.elements.len(), 1);
        assert_eq!(b.elements[0].element_type, ElementType::Floor);
        assert_eq!(b.elements[0].material, "floor_slab");
    }

    #[test]
    fn door_anchored_to_a_wall_emits_door_element_with_rotation() {
        let walls = vec![ext_wall(0.0, 5000.0, 0.0)];
        let doc = SchemaDocument {
            walls: walls.clone(),
            doors: vec![SchemaDoor {
                wall_index: 0,
                offset: 1500.0,
                width: 900.0,
                height: 2100.0,
                ..Default::default()
            }],
            ..Default::default()
        };
        let b = layout_to_building(&doc);
        let door = b
            .elements
            .iter()
            .find(|e| e.element_type == ElementType::Door);
        assert!(door.is_some());
        let door = door.unwrap();
        assert_eq!(door.width, 900.0);
        // X-axis wall → rotation = atan2(0, 1) = 0.
        assert!((door.rotation - 0.0).abs() < 1e-6);
    }

    #[test]
    fn door_with_invalid_wall_index_is_skipped() {
        let doc = SchemaDocument {
            walls: vec![ext_wall(0.0, 5000.0, 0.0)],
            doors: vec![SchemaDoor {
                wall_index: 99,
                offset: 1500.0,
                width: 900.0,
                height: 2100.0,
                ..Default::default()
            }],
            ..Default::default()
        };
        let b = layout_to_building(&doc);
        assert!(
            b.elements
                .iter()
                .all(|e| e.element_type != ElementType::Door)
        );
    }

    #[test]
    fn window_emits_window_element_at_sill_height() {
        let doc = SchemaDocument {
            walls: vec![ext_wall(0.0, 5000.0, 0.0)],
            windows: vec![SchemaWindow {
                wall_index: 0,
                offset: 2000.0,
                width: 1200.0,
                height: 1200.0,
                sill_height: 900.0,
                ..Default::default()
            }],
            ..Default::default()
        };
        let b = layout_to_building(&doc);
        let win = b
            .elements
            .iter()
            .find(|e| e.element_type == ElementType::Window);
        assert!(win.is_some());
        let win = win.unwrap();
        // Start should be at sill height (Y).
        assert!((win.start.y - 900.0).abs() < 1e-6);
        // End should be at sill + window height.
        assert!((win.end.y - 2100.0).abs() < 1e-6);
    }

    #[test]
    fn roof_surface_with_upward_normal_keeps_winding() {
        // CCW triangle in the XZ plane viewed from above (+Y up).
        let surface = archgeometry::RoofSurface {
            id: "s0".into(),
            vertices: vec![
                Vec3::new(0.0, 3000.0, 0.0),
                Vec3::new(1000.0, 3000.0, 0.0),
                Vec3::new(0.0, 3000.0, 1000.0),
            ],
            pitch: 0.0,
            orientation: String::new(),
        };
        let elem = roof_surface_to_element(&surface).unwrap();
        // First face is the natural [0, 1, 2] winding.
        // (1,0,0) × (0,0,1) = (0*1-0*0, 0*0-1*1, 1*0-0*0) = (0,-1,0) — points DOWN.
        // So the reverse path runs and emits [0, 2, 1].
        assert_eq!(elem.mesh.faces[0], [0, 2, 1]);
    }
}
