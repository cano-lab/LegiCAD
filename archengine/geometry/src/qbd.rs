//! QBD building-file loader — scoped port of `qbd_interface.cpp`.
//!
//! The QBD generator (Python) emits building JSON in **millimetres** with
//! walls/floors as batches, element heights as separate fields (never in
//! `start`/`end`), and doors/windows positioned by `(wall_index, offset)`
//! along their host wall. Feeding that straight into the flat
//! [`StructuralElement`] path drops the height field and produces the
//! classic "slanted walls" — this module converts properly, like the C++
//! `QBDInterface::toBuilding`.
//!
//! Scope notes (smaller than the C++):
//! - Layered wall assemblies are collapsed to a single slab per wall:
//!   exterior/wet 170 mm (the C++ default 2×6 assembly's geometric
//!   layers), interior 100 mm. Insulation/membrane layers carried no
//!   geometry upstream either.
//! - Roofs: only explicit `surfaces[].vertices` polygons (fan
//!   triangulated, C++ winding fix). Pitch/ridge synthesis is not ported.
//! - `terrain_mesh`, building placement, and parametric walls are skipped.
//! - Doors/windows are positioned panels; the wall behind them IS cut
//!   (via [`crate::mesh_gen::wall_with_multiple_openings`]), as upstream.

use anyhow::{Context as _, Result};
use glam::{Vec3, Vec3Swizzles};
use serde::Deserialize;

use crate::domain::{ElementType, MeshData, StructuralElement};

/// Load a scene JSON as either the flat element array (C++ debug/export
/// format) or a QBD building file. Flat wins when both would parse.
pub fn elements_from_json(text: &str) -> Result<Vec<StructuralElement>> {
    if let Ok(elements) = serde_json::from_str::<Vec<StructuralElement>>(text) {
        if !elements.is_empty() {
            return Ok(elements);
        }
    }
    let building: QbdBuilding = serde_json::from_str(text)
        .context("scene is neither a flat StructuralElement array nor a QBD building file")?;
    let elements = building.to_elements();
    if elements.is_empty() {
        anyhow::bail!("QBD building file produced no elements");
    }
    Ok(elements)
}

fn default_wall_height() -> f32 {
    2700.0 // mm — C++ default
}
fn default_floor_thickness() -> f32 {
    300.0
}
fn default_door_width() -> f32 {
    900.0
}
fn default_door_height() -> f32 {
    2100.0
}
fn default_window_size() -> f32 {
    1200.0
}
fn default_sill_height() -> f32 {
    900.0
}
fn level_one() -> String {
    "Level 1".to_string()
}

#[derive(Debug, Deserialize)]
struct QbdWall {
    start: [f32; 3],
    end: [f32; 3],
    #[serde(default = "default_wall_height")]
    height: f32,
    #[serde(default)]
    wall_type: String,
    #[serde(default = "level_one")]
    #[allow(dead_code)]
    level_name: String,
    #[serde(default)]
    category: String,
    #[serde(default)]
    material_override: String,
}

#[derive(Debug, Deserialize)]
struct QbdFloor {
    start: [f32; 3],
    end: [f32; 3],
    #[serde(default = "default_floor_thickness")]
    thickness: f32,
    #[serde(default)]
    material: String,
}

#[derive(Debug, Deserialize)]
struct QbdDoor {
    #[serde(default)]
    wall_index: i32,
    #[serde(default)]
    offset: f32,
    #[serde(default = "default_door_width")]
    width: f32,
    #[serde(default = "default_door_height")]
    height: f32,
}

#[derive(Debug, Deserialize)]
struct QbdWindow {
    #[serde(default)]
    wall_index: i32,
    #[serde(default)]
    offset: f32,
    #[serde(default = "default_window_size")]
    width: f32,
    #[serde(default = "default_window_size")]
    height: f32,
    #[serde(default = "default_sill_height")]
    sill_height: f32,
}

#[derive(Debug, Deserialize)]
struct QbdRoofSurface {
    #[serde(default)]
    vertices: Vec<[f32; 3]>,
}

#[derive(Debug, Deserialize)]
struct QbdRoof {
    #[serde(default)]
    material: String,
    #[serde(default)]
    surfaces: Vec<QbdRoofSurface>,
}

/// The QBD building payload (`success`, `width`, `depth`, batches).
#[derive(Debug, Default, Deserialize)]
pub struct QbdBuilding {
    #[serde(default)]
    walls_batch: Vec<QbdWall>,
    #[serde(default)]
    floors_batch: Vec<QbdFloor>,
    #[serde(default)]
    doors: Vec<QbdDoor>,
    #[serde(default)]
    windows: Vec<QbdWindow>,
    #[serde(default)]
    roofs: Vec<QbdRoof>,
}

/// Wall slab thickness by category (C++ default assemblies, geometric
/// layers only): exterior/wet 170 mm, interior 100 mm.
fn wall_thickness(category: &str) -> f32 {
    match category {
        "exterior" | "wet_wall" | "wetwall" => 170.0,
        _ => 100.0,
    }
}

fn base_element(element_type: ElementType) -> StructuralElement {
    StructuralElement {
        element_type,
        ..Default::default()
    }
}

impl QbdBuilding {
    /// Convert to flat elements — C++ `QBDInterface::toBuilding`.
    #[must_use]
    pub fn to_elements(&self) -> Vec<StructuralElement> {
        let mut elements = Vec::new();

        // Walls — height becomes end.y; openings from doors/windows on
        // this wall are cut into the mesh (C++: CSG wallWithMultipleOpenings).
        for (wall_idx, wall) in self.walls_batch.iter().enumerate() {
            let start = Vec3::from(wall.start);
            let end_plan = Vec3::from(wall.end);
            let thickness = wall_thickness(&wall.category);

            // Extend the wall geometry half a thickness past each end so
            // perpendicular walls overlap at corners instead of leaving a
            // butt-joint notch. Opening offsets shift by the same amount to
            // stay in place (door/window panel placement below still uses
            // the logical wall run, which keeps panels aligned with holes).
            let wall_vec = end_plan - start;
            let wall_len = wall_vec.xz().length();
            let (geo_start, geo_end, off_shift) = if wall_len > 0.01 {
                let d = Vec3::new(wall_vec.x / wall_len, 0.0, wall_vec.z / wall_len);
                let ext = thickness * 0.5;
                (start - d * ext, end_plan + d * ext, ext)
            } else {
                (start, end_plan, 0.0)
            };

            let mut openings: Vec<[f32; 4]> = Vec::new(); // {offset, width, bottom, height}
            for door in &self.doors {
                if door.wall_index == wall_idx as i32 {
                    openings.push([door.offset + off_shift, door.width, 0.0, door.height]);
                }
            }
            for window in &self.windows {
                if window.wall_index == wall_idx as i32 {
                    openings.push([
                        window.offset + off_shift,
                        window.width,
                        window.sill_height,
                        window.height,
                    ]);
                }
            }

            let mut elem = base_element(ElementType::Wall);
            elem.start = geo_start;
            elem.end = Vec3::new(geo_end.x, geo_start.y + wall.height, geo_end.z);
            elem.width = thickness;
            elem.depth = thickness;
            elem.material = if !wall.material_override.is_empty() {
                wall.material_override.clone()
            } else if !wall.wall_type.is_empty() {
                wall.wall_type.clone()
            } else {
                "wall".to_string()
            };

            let mesh = crate::mesh_gen::csg::wall_with_multiple_openings(
                geo_start,
                geo_end,
                wall.height,
                thickness,
                &openings,
                Vec3::ONE, // vertex color unused — material_color wins downstream
            );
            if !mesh.is_empty() {
                elem.mesh = MeshData {
                    vertices: mesh.vertices.iter().map(|v| v.position).collect(),
                    faces: mesh
                        .indices
                        .chunks_exact(3)
                        .map(|c| [c[0], c[1], c[2]])
                        .collect(),
                    ..Default::default()
                };
            }
            elements.push(elem);
        }

        // Floors — start/end are the plan rectangle, Y is elevation,
        // thickness goes up (C++: vec3(end.x, start.y + thickness, end.z)).
        for floor in &self.floors_batch {
            let start = Vec3::from(floor.start);
            let end = Vec3::from(floor.end);
            let mut elem = base_element(ElementType::Floor);
            elem.start = start;
            elem.end = Vec3::new(end.x, start.y + floor.thickness, end.z);
            elem.width = (end.x - start.x).abs();
            elem.depth = (end.z - start.z).abs();
            elem.material = if floor.material.is_empty() {
                "floor_slab".to_string()
            } else {
                floor.material.clone()
            };
            elements.push(elem);
        }

        // Doors — positioned along the host wall (C++ verbatim: offset is
        // clamped to the wall run, centre at offset + width/2, sill at
        // floor level, rotation = wall yaw).
        for door in &self.doors {
            let Some(wall) = self
                .walls_batch
                .get(usize::try_from(door.wall_index).unwrap_or(usize::MAX))
            else {
                continue;
            };
            let wall_start = Vec3::from(wall.start);
            let wall_end = Vec3::from(wall.end);
            let wall_len = (wall_end - wall_start).xz().length();
            if wall_len < 0.01 {
                continue;
            }
            let dir2 = (wall_end - wall_start).xz() / wall_len;
            let wall_dir = Vec3::new(dir2.x, 0.0, dir2.y);

            let door_offset = door.offset.clamp(0.0, (wall_len - door.width).max(0.0));
            let center = wall_start + wall_dir * (door_offset + door.width * 0.5);

            let mut elem = base_element(ElementType::Door);
            elem.start = center - wall_dir * (door.width * 0.5);
            elem.start.y = wall_start.y;
            elem.end = center + wall_dir * (door.width * 0.5);
            elem.end.y = wall_start.y + door.height;
            elem.width = door.width;
            elem.depth = 100.0; // door slab ~100mm (C++)
            elem.material = "door".to_string();
            elem.rotation = dir2.y.atan2(dir2.x);
            elements.push(elem);
        }

        // Windows — same as doors but elevated by sill_height, depth 50mm.
        for window in &self.windows {
            let Some(wall) = self
                .walls_batch
                .get(usize::try_from(window.wall_index).unwrap_or(usize::MAX))
            else {
                continue;
            };
            let wall_start = Vec3::from(wall.start);
            let wall_end = Vec3::from(wall.end);
            let wall_len = (wall_end - wall_start).xz().length();
            if wall_len < 0.01 {
                continue;
            }
            let dir2 = (wall_end - wall_start).xz() / wall_len;
            let wall_dir = Vec3::new(dir2.x, 0.0, dir2.y);

            let offset = window
                .offset
                .clamp(0.0, (wall_len - window.width).max(0.0));
            let center = wall_start + wall_dir * (offset + window.width * 0.5);

            let mut elem = base_element(ElementType::Window);
            elem.start = center - wall_dir * (window.width * 0.5);
            elem.start.y = wall_start.y + window.sill_height;
            elem.end = center + wall_dir * (window.width * 0.5);
            elem.end.y = wall_start.y + window.sill_height + window.height;
            elem.width = window.width;
            elem.depth = 50.0; // window panel ~50mm (C++)
            elem.material = "window".to_string();
            elem.rotation = dir2.y.atan2(dir2.x);
            elements.push(elem);
        }

        // Roofs — explicit surface polygons, fan-triangulated with the C++
        // winding fix (normals must point up).
        for roof in &self.roofs {
            for surface in &roof.surfaces {
                if surface.vertices.len() < 3 {
                    continue;
                }
                let verts: Vec<Vec3> = surface.vertices.iter().map(|&v| Vec3::from(v)).collect();

                let mut reverse_winding = false;
                {
                    let (v0, v1, v2) = (verts[0], verts[1], verts[2]);
                    let normal = (v1 - v0).cross(v2 - v0);
                    if normal.y < 0.0 {
                        reverse_winding = true;
                    }
                }

                let mut min = Vec3::splat(f32::MAX);
                let mut max = Vec3::splat(f32::MIN);
                for v in &verts {
                    min = min.min(*v);
                    max = max.max(*v);
                }

                let mut elem = base_element(ElementType::Roof);
                elem.start = min;
                elem.end = max;
                elem.width = max.x - min.x;
                elem.depth = max.z - min.z;
                elem.material = if roof.material.is_empty() {
                    "roof_shingle".to_string()
                } else {
                    roof.material.clone()
                };

                let mut faces = Vec::new();
                for i in 1..verts.len() - 1 {
                    if reverse_winding {
                        faces.push([0, (i + 1) as u32, i as u32]);
                    } else {
                        faces.push([0, i as u32, (i + 1) as u32]);
                    }
                }
                elem.mesh = MeshData {
                    vertices: verts,
                    faces,
                    ..Default::default()
                };
                elements.push(elem);
            }
        }

        elements
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_wall10_fixture() {
        let text = std::fs::read_to_string(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../test-data/wall10_only.json"
        ))
        .expect("fixture readable");
        let elements = elements_from_json(&text).expect("QBD parse");
        // Fixture: 1 wall + 1 door.
        assert_eq!(elements.len(), 2);
        let wall = elements
            .iter()
            .find(|e| e.element_type == ElementType::Wall)
            .expect("a wall");
        // 3048mm height lands in end.y — the flat-format bug dropped it.
        assert!((wall.end.y - wall.start.y - 3048.0).abs() < 0.01);
        assert!(wall.mesh.has_data(), "wall slab mesh generated");
    }

    #[test]
    fn parses_door_and_cuts_opening() {
        let text = std::fs::read_to_string(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../test-data/minimal_1wall_1door.json"
        ))
        .expect("fixture readable");
        let elements = elements_from_json(&text).expect("QBD parse");
        let walls = elements
            .iter()
            .filter(|e| e.element_type == ElementType::Wall)
            .count();
        let doors: Vec<_> = elements
            .iter()
            .filter(|e| e.element_type == ElementType::Door)
            .collect();
        assert_eq!(walls, 1);
        assert_eq!(doors.len(), 1);
        let door = doors[0];
        assert!((door.end.y - door.start.y - 2033.016).abs() < 0.5);
        assert!(door.rotation > -999.0, "door carries host wall yaw");
        // The wall mesh with a cut opening has more triangles than a plain
        // 6-face slab (12 triangles).
        let wall = elements
            .iter()
            .find(|e| e.element_type == ElementType::Wall)
            .unwrap();
        assert!(wall.mesh.faces.len() > 12);
    }

    #[test]
    fn parses_qbd_floors() {
        let text = std::fs::read_to_string(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../test-data/test_building_qbd.json"
        ))
        .expect("fixture readable");
        let elements = elements_from_json(&text).expect("QBD parse");
        let floors: Vec<_> = elements
            .iter()
            .filter(|e| e.element_type == ElementType::Floor)
            .collect();
        // Fixture: slabs for Level 1, Level 2 (y=3048), Roof (y=6096).
        assert_eq!(floors.len(), 3);
        // 200mm slab thickness in end.y; plan extents in width/depth.
        assert!((floors[0].end.y - floors[0].start.y - 200.0).abs() < 0.01);
        assert!((floors[0].width - 9144.0).abs() < 0.01);
        // Storey elevations are preserved.
        assert!((floors[1].start.y - 3048.0).abs() < 0.01);
        assert!((floors[2].start.y - 6096.0).abs() < 0.01);
    }

    #[test]
    fn flat_format_still_wins() {
        let text = r#"[{"type":"wall","start":[0,0,0],"end":[5,3,0],"width":0.2,
            "depth":0.2,"stress":0.0,"deflection":0.0,"material":"brick"}]"#;
        let elements = elements_from_json(text).expect("flat parse");
        assert_eq!(elements.len(), 1);
        assert!((elements[0].end.y - 3.0).abs() < 1e-6); // untouched
    }
}
