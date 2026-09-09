//! Scene conversion: `StructuralElement` → indexed meshes with normals for
//! the raster viewer.
//!
//! Mirrors the corner conventions of the C++ real-time renderer's fallback
//! geometry (the same conventions `bvh.rs` ports for the path tracer), but
//! emits indexed meshes with per-face normals instead of raw triangles.
//! Elements carrying a custom [`MeshData`] (IFC/CSG) use it directly, with
//! flat normals computed per face.

use glam::{Vec2, Vec3, Vec4};

use archengine_geometry::domain::mesh::Vertex;
use archengine_geometry::domain::{ElementType, StructuralElement};
use archengine_geometry::mesh_gen::PrimitiveMesh;

fn v(position: Vec3, normal: Vec3, color: Vec3, tex_coord: Vec2, stress: f32) -> Vertex {
    Vertex { position, normal, color, tex_coord, stress }
}

/// Base color per material keyword (subset of the C++ renderer's material
/// palette; the Polyhaven texture array re-add replaces these with real
/// textures — questions.md A4 checklist).
pub fn material_color(material: &str, element_type: ElementType) -> Vec3 {
    let lower = material.to_lowercase();
    if lower.contains("glass") || element_type == ElementType::Window {
        Vec3::new(0.7, 0.85, 0.95)
    } else if lower.contains("brick") {
        Vec3::new(0.62, 0.32, 0.25)
    } else if lower.contains("wood") || lower.contains("timber") {
        Vec3::new(0.55, 0.40, 0.25)
    } else if lower.contains("steel") || lower.contains("metal") {
        Vec3::new(0.65, 0.67, 0.70)
    } else if lower.contains("concrete") {
        Vec3::new(0.75, 0.74, 0.72)
    } else if lower.contains("grass") || lower.contains("terrain") {
        Vec3::new(0.35, 0.55, 0.30)
    } else {
        match element_type {
            ElementType::Wall => Vec3::new(0.85, 0.83, 0.78),
            ElementType::Floor => Vec3::new(0.75, 0.74, 0.72),
            ElementType::Roof => Vec3::new(0.45, 0.40, 0.38),
            ElementType::Beam | ElementType::Column => Vec3::new(0.55, 0.40, 0.25),
            ElementType::Door => Vec3::new(0.45, 0.30, 0.18),
            _ => Vec3::new(0.8, 0.8, 0.8),
        }
    }
}

/// PBR material multipliers per material keyword (x = metallic,
/// y = roughness, z = ao, w = emission), consumed by
/// [`crate::vulkan::raster::DrawItem::material`]. With the placeholder
/// white textures these are the effective PBR values. C++ renderer
/// defaults: metallic 0, roughness 0.5, ao 1, emission 0 (renderer.hpp
/// `m_defaultMetallic` & friends). Glass drops roughness below 0.35 so
/// `structural.frag`'s fresnel transparency path engages; steel is
/// metallic.
pub fn material_props(material: &str, element_type: ElementType) -> Vec4 {
    let lower = material.to_lowercase();
    if lower.contains("glass") || element_type == ElementType::Window {
        Vec4::new(0.0, 0.1, 1.0, 0.0)
    } else if lower.contains("steel") || lower.contains("metal") {
        Vec4::new(0.9, 0.35, 1.0, 0.0)
    } else if lower.contains("wood") || lower.contains("timber")
        || element_type == ElementType::Door
    {
        Vec4::new(0.0, 0.6, 1.0, 0.0)
    } else {
        Vec4::new(0.0, 0.5, 1.0, 0.0)
    }
}

/// Build a render mesh for one element. Returns `None` for zero-size
/// elements (same skip conditions as the C++/BVH fallbacks).
pub fn element_to_mesh(elem: &StructuralElement) -> Option<PrimitiveMesh> {
    // Custom mesh data (IFC, CSG, terrain) wins, as in the BVH path.
    if elem.mesh.has_data() {
        return Some(mesh_data_to_primitive(elem));
    }

    let color = material_color(&elem.material, elem.element_type);
    let stress = elem.stress;
    let (start, end, w, d) = (elem.start, elem.end, elem.width, elem.depth);
    let mut mesh = PrimitiveMesh::default();

    // Append a quad as two triangles with a shared flat normal.
    let add_quad = |mesh: &mut PrimitiveMesh, corners: &[Vec3; 8], a: usize, b: usize, c: usize, dd: usize| {
        let normal = (corners[b] - corners[a])
            .cross(corners[dd] - corners[a])
            .normalize_or_zero();
        let base = mesh.vertices.len() as u32;
        for &i in &[a, b, c, dd] {
            mesh.vertices
                .push(v(corners[i], normal, color, Vec2::ZERO, stress));
        }
        mesh.indices
            .extend_from_slice(&[base, base + 1, base + 2, base, base + 2, base + 3]);
    };

    match elem.element_type {
        ElementType::Beam => {
            let dir = end - start;
            let len = dir.length();
            if len < 0.001 {
                return None;
            }
            let dir = dir / len;
            let mut up = Vec3::Y;
            if dir.dot(up).abs() > 0.99 {
                up = Vec3::X;
            }
            let right = dir.cross(up).normalize();
            let local_up = right.cross(dir);
            let hw = right * (w * 0.5);
            let hd = local_up * (d * 0.5);
            let corners = [
                start - hw - hd, start + hw - hd, start + hw + hd, start - hw + hd,
                end - hw - hd, end + hw - hd, end + hw + hd, end - hw + hd,
            ];
            add_quad(&mut mesh, &corners, 0, 1, 2, 3);
            add_quad(&mut mesh, &corners, 5, 4, 7, 6);
            add_quad(&mut mesh, &corners, 0, 4, 5, 1);
            add_quad(&mut mesh, &corners, 2, 6, 7, 3);
            add_quad(&mut mesh, &corners, 1, 5, 6, 2);
            add_quad(&mut mesh, &corners, 4, 0, 3, 7);
        }
        ElementType::Column => {
            let base = start;
            let mut height = end.y - start.y;
            if height < 0.001 {
                height = 1.0;
            }
            let hw = Vec3::new(w * 0.5, 0.0, 0.0);
            let hd = Vec3::new(0.0, 0.0, d * 0.5);
            let h = Vec3::new(0.0, height, 0.0);
            let corners = [
                base - hw - hd, base + hw - hd, base + hw + hd, base - hw + hd,
                base - hw - hd + h, base + hw - hd + h, base + hw + hd + h, base - hw + hd + h,
            ];
            add_quad(&mut mesh, &corners, 0, 1, 2, 3);
            add_quad(&mut mesh, &corners, 5, 4, 7, 6);
            add_quad(&mut mesh, &corners, 0, 4, 5, 1);
            add_quad(&mut mesh, &corners, 2, 6, 7, 3);
            add_quad(&mut mesh, &corners, 1, 5, 6, 2);
            add_quad(&mut mesh, &corners, 4, 0, 3, 7);
        }
        ElementType::Floor | ElementType::Roof => {
            let slab_width = end.x - start.x;
            let slab_depth = end.z - start.z;
            let mut thickness = end.y - start.y;
            if thickness.abs() < 0.01 {
                thickness = 0.3;
            }
            if slab_width.abs() < 0.01 || slab_depth.abs() < 0.01 {
                return None;
            }
            let corners = [
                Vec3::new(start.x, start.y, start.z),
                Vec3::new(end.x, start.y, start.z),
                Vec3::new(end.x, start.y, end.z),
                Vec3::new(start.x, start.y, end.z),
                Vec3::new(start.x, start.y + thickness, start.z),
                Vec3::new(end.x, start.y + thickness, start.z),
                Vec3::new(end.x, start.y + thickness, end.z),
                Vec3::new(start.x, start.y + thickness, end.z),
            ];
            add_quad(&mut mesh, &corners, 0, 3, 2, 1); // bottom (normal down)
            add_quad(&mut mesh, &corners, 4, 7, 6, 5); // top
            add_quad(&mut mesh, &corners, 0, 1, 5, 4);
            add_quad(&mut mesh, &corners, 2, 3, 7, 6);
            add_quad(&mut mesh, &corners, 1, 2, 6, 5);
            add_quad(&mut mesh, &corners, 3, 0, 4, 7);
        }
        ElementType::Wall => {
            let wall_dir = end - start;
            let wall_len = (wall_dir.x * wall_dir.x + wall_dir.z * wall_dir.z).sqrt();
            if wall_len < 0.001 {
                return None;
            }
            let dir = Vec3::new(wall_dir.x / wall_len, 0.0, wall_dir.z / wall_len);
            let perp = Vec3::new(-dir.z, 0.0, dir.x);
            let mut height = end.y - start.y;
            if height < 0.001 {
                height = if start.y > 0.0 { start.y } else { 8.0 };
            }
            let hw = perp * (w * 0.5);
            let h = Vec3::new(0.0, height, 0.0);
            let corners = [
                start - hw, start + hw, end + hw, end - hw,
                start - hw + h, start + hw + h, end + hw + h, end - hw + h,
            ];
            add_quad(&mut mesh, &corners, 0, 1, 2, 3);
            add_quad(&mut mesh, &corners, 5, 4, 7, 6);
            add_quad(&mut mesh, &corners, 0, 4, 5, 1);
            add_quad(&mut mesh, &corners, 3, 7, 6, 2);
            add_quad(&mut mesh, &corners, 1, 5, 6, 2);
            add_quad(&mut mesh, &corners, 4, 0, 3, 7);
        }
        ElementType::Window => {
            // Framed glass panel via the mesh_gen creator (richer than the
            // BVH fallback's flat quad), placed at the run's midpoint.
            let width = if w > 0.01 { w } else { 1.0 };
            let mut height = end.y - start.y;
            if height < 0.01 {
                height = 1.5;
            }
            let dir = end - start;
            let len = (dir.x * dir.x + dir.z * dir.z).sqrt();
            let mut center = (start + end) * 0.5;
            center.y = start.y;
            if len < 0.001 {
                return Some(archengine_geometry::mesh_gen::create_window(
                    center,
                    width,
                    height,
                    d.max(0.05),
                    color,
                ));
            }
            // mesh_gen windows are axis-aligned; rotate to the wall run.
            let yaw = (dir.z / len).atan2(dir.x / len);
            let local = archengine_geometry::mesh_gen::create_window(
                Vec3::ZERO,
                width,
                height,
                d.max(0.05),
                color,
            );
            return Some(transform(local, center, yaw));
        }
        ElementType::Door => {
            let door_width = if w > 0.01 { w } else { 0.9 };
            let mut door_height = end.y - start.y;
            if door_height < 0.01 {
                door_height = 2.1;
            }
            let door_thickness = if d > 0.01 { d } else { 0.05 };
            let dir = end - start;
            let len = (dir.x * dir.x + dir.z * dir.z).sqrt();
            let mut center = (start + end) * 0.5;
            center.y = start.y;
            let yaw = if len > 0.001 {
                (dir.z / len).atan2(dir.x / len)
            } else {
                0.0
            };
            let local = archengine_geometry::mesh_gen::create_door(
                Vec3::ZERO,
                door_width,
                door_height,
                door_thickness,
                color,
            );
            return Some(transform(local, center, yaw));
        }
        _ => return None, // other element types are skipped (as the fallback)
    }

    if mesh.is_empty() { None } else { Some(mesh) }
}

/// Rotate a mesh around Y by `yaw` and translate to `center`.
fn transform(mesh: PrimitiveMesh, center: Vec3, yaw: f32) -> PrimitiveMesh {
    let (sin, cos) = yaw.sin_cos();
    let rotate = |p: Vec3| Vec3::new(p.x * cos + p.z * sin, p.y, -p.x * sin + p.z * cos);
    let vertices = mesh
        .vertices
        .into_iter()
        .map(|mut vert| {
            vert.position = rotate(vert.position) + center;
            vert.normal = rotate(vert.normal).normalize_or_zero();
            vert
        })
        .collect();
    PrimitiveMesh { vertices, indices: mesh.indices }
}

/// Custom mesh data → primitive with flat per-face normals.
fn mesh_data_to_primitive(elem: &StructuralElement) -> PrimitiveMesh {
    let color = material_color(&elem.material, elem.element_type);
    let mut mesh = PrimitiveMesh::default();
    for face in &elem.mesh.faces {
        let [a, b, c] = *face;
        let (Some(&pa), Some(&pb), Some(&pc)) = (
            elem.mesh.vertices.get(a as usize),
            elem.mesh.vertices.get(b as usize),
            elem.mesh.vertices.get(c as usize),
        ) else {
            continue; // out-of-range index: skipped, as the BVH path does
        };
        let normal = (pb - pa).cross(pc - pa).normalize_or_zero();
        let base = mesh.vertices.len() as u32;
        for p in [pa, pb, pc] {
            mesh.vertices.push(v(p, normal, color, Vec2::ZERO, elem.stress));
        }
        mesh.indices.extend_from_slice(&[base, base + 1, base + 2]);
    }
    mesh
}

/// Convert a whole scene, skipping elements with no geometry.
pub fn scene_to_meshes(elements: &[StructuralElement]) -> Vec<PrimitiveMesh> {
    elements.iter().filter_map(element_to_mesh).collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use archengine_geometry::domain::{ElementType, StructuralElement};

    fn elem(ty: ElementType, start: Vec3, end: Vec3, w: f32, d: f32) -> StructuralElement {
        StructuralElement {
            element_type: ty,
            start,
            end,
            width: w,
            depth: d,
            ..Default::default()
        }
    }

    #[test]
    fn beam_produces_box_with_outward_normals() {
        let mesh = element_to_mesh(&elem(
            ElementType::Beam,
            Vec3::ZERO,
            Vec3::new(10.0, 0.0, 0.0),
            0.5,
            1.0,
        ))
        .unwrap();
        assert_eq!(mesh.indices.len(), 36); // 6 quads × 2 triangles
        for vert in &mesh.vertices {
            assert!(vert.normal.length() > 0.99);
        }
    }

    #[test]
    fn degenerate_elements_are_skipped() {
        assert!(element_to_mesh(&elem(
            ElementType::Wall,
            Vec3::ZERO,
            Vec3::ZERO,
            0.5,
            0.5
        ))
        .is_none());
        assert!(element_to_mesh(&elem(
            ElementType::Beam,
            Vec3::ZERO,
            Vec3::ZERO,
            0.5,
            1.0
        ))
        .is_none());
    }

    #[test]
    fn door_window_rotate_to_wall_run() {
        // A door on a wall running along Z must produce geometry spanning Z.
        let mesh = element_to_mesh(&elem(
            ElementType::Door,
            Vec3::new(0.0, 0.0, 0.0),
            Vec3::new(0.0, 0.0, 5.0),
            0.9,
            0.05,
        ))
        .unwrap();
        let max_z = mesh.vertices.iter().map(|v| v.position.z).fold(f32::MIN, f32::max);
        let min_z = mesh.vertices.iter().map(|v| v.position.z).fold(f32::MAX, f32::min);
        assert!(max_z - min_z > 0.5, "door should span the wall run (z)");
    }

    #[test]
    fn custom_mesh_wins_over_fallback() {
        let mut e = elem(ElementType::Wall, Vec3::ZERO, Vec3::new(10.0, 9.0, 0.0), 0.5, 0.5);
        e.mesh = archengine_geometry::domain::mesh::MeshData {
            vertices: vec![Vec3::ZERO, Vec3::X, Vec3::Y],
            faces: vec![[0, 1, 2]],
        };
        let mesh = element_to_mesh(&e).unwrap();
        assert_eq!(mesh.vertices.len(), 3);
        assert_eq!(mesh.indices.len(), 3);
    }
}
