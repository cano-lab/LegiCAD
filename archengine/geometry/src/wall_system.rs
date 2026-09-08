//! Parametric walls — layer mesh generation, corner detection, L-corner
//! adjustment.
//!
//! Port of `ArchEngine_kernel/include/wall_system.hpp`.
//!
//! Deliberate divergence from the C++ (port plan §7 / §8 Q8): the original
//! [`generate_layer_mesh`] emits every face in *both* winding orders (24
//! triangles) to work around inconsistent normals. This port emits 12
//! single-sided triangles with correct outward normals — winding verified
//! per-face against the vertex layout. Renderers can cull back-faces.

use crate::domain::{
    CornerType, ElementType, LayerFunction, MeshData, ParametricWall, StructuralElement,
    WallCorner, WallLayer, WallType,
};
use glam::{Vec2, Vec3};

/// Default wall assemblies. Ports of the `create*Wall()` factories in
/// `wall_system.hpp`. Thicknesses in feet, matching the C++ value space.
pub mod defaults {
    use crate::domain::{LayerFunction, WallLayer, WallType};
    use glam::Vec3;

    fn layer(
        name: &str,
        material: &str,
        function: LayerFunction,
        thickness: f32,
        color: Vec3,
        r_value: f32,
    ) -> WallLayer {
        WallLayer {
            name: name.into(),
            material: material.into(),
            function,
            thickness,
            color,
            r_value,
            ..Default::default()
        }
    }

    /// 2x6 exterior wall: siding → wrap → sheathing → insulation/stud → drywall.
    #[must_use]
    pub fn exterior_2x6() -> WallType {
        WallType {
            name: "2x6 Exterior Wall".into(),
            layers: vec![
                layer("Siding", "wood", LayerFunction::ExteriorFinish, 0.0625, Vec3::new(0.6, 0.5, 0.4), 0.8),
                layer("House Wrap", "membrane", LayerFunction::Membrane, 0.005, Vec3::splat(0.9), 0.0),
                layer("Sheathing", "osb", LayerFunction::Sheathing, 0.0417, Vec3::new(0.8, 0.7, 0.5), 0.6),
                layer("Insulation", "fiberglass", LayerFunction::Insulation, 0.458, Vec3::new(0.95, 0.8, 0.9), 19.0),
                layer("2x6 Stud", "wood", LayerFunction::Structure, 0.458, Vec3::new(0.9, 0.8, 0.6), 6.9),
                layer("Drywall", "gypsum", LayerFunction::InteriorFinish, 0.0417, Vec3::new(0.95, 0.95, 0.92), 0.5),
            ],
            ..Default::default()
        }
    }

    /// 2x4 exterior wall.
    #[must_use]
    pub fn exterior_2x4() -> WallType {
        WallType {
            name: "2x4 Exterior Wall".into(),
            layers: vec![
                layer("Siding", "wood", LayerFunction::ExteriorFinish, 0.0625, Vec3::new(0.6, 0.5, 0.4), 0.8),
                layer("House Wrap", "membrane", LayerFunction::Membrane, 0.005, Vec3::splat(0.9), 0.0),
                layer("Sheathing", "osb", LayerFunction::Sheathing, 0.0417, Vec3::new(0.8, 0.7, 0.5), 0.6),
                layer("Insulation", "fiberglass", LayerFunction::Insulation, 0.292, Vec3::new(0.95, 0.8, 0.9), 13.0),
                layer("2x4 Stud", "wood", LayerFunction::Structure, 0.292, Vec3::new(0.9, 0.8, 0.6), 4.4),
                layer("Drywall", "gypsum", LayerFunction::InteriorFinish, 0.0417, Vec3::new(0.95, 0.95, 0.92), 0.5),
            ],
            ..Default::default()
        }
    }

    /// Interior partition: drywall / 2x4 stud / drywall.
    #[must_use]
    pub fn interior() -> WallType {
        WallType {
            name: "Interior Partition".into(),
            layers: vec![
                layer("Drywall", "gypsum", LayerFunction::InteriorFinish, 0.0417, Vec3::new(0.95, 0.95, 0.92), 0.5),
                layer("2x4 Stud", "wood", LayerFunction::Structure, 0.292, Vec3::new(0.9, 0.8, 0.6), 4.4),
                layer("Drywall", "gypsum", LayerFunction::InteriorFinish, 0.0417, Vec3::new(0.95, 0.95, 0.92), 0.5),
            ],
            ..Default::default()
        }
    }
}

/// Generate layer meshes for a single wall. Insulation layers share space
/// with the structure layer and are skipped (matches the C++).
pub fn generate_wall_geometry(wall: &mut ParametricWall, wall_type: &WallType) {
    wall.layer_meshes.clear();

    // Total thickness excludes insulation (shares the stud space).
    let total_thickness: f32 = wall_type
        .layers
        .iter()
        .filter(|l| l.function != LayerFunction::Insulation)
        .map(|l| l.thickness)
        .sum();

    // Start from the exterior side.
    let mut current_offset = -total_thickness / 2.0;

    for layer in &wall_type.layers {
        if layer.function == LayerFunction::Insulation {
            continue;
        }
        let mesh = generate_layer_mesh(wall, layer, current_offset, layer.thickness);
        wall.layer_meshes.push(mesh);
        current_offset += layer.thickness;
    }
}

/// Generate one layer's mesh: an 8-vertex box between the layer's exterior
/// and interior faces, from `base_height` to `top_height`.
///
/// `layer_offset` is the distance from the centerline to the layer's
/// exterior face (negative = exterior of centerline).
///
/// Single-sided faces with outward normals (see module docs). Vertex order
/// matches the C++ exactly so hashes/diffs against legacy output still line
/// up on the vertex arrays:
///
/// ```text
/// Looking down (Y up):   ext1---ext2   (exterior, offset)
///                         |      |
///                        int1---int2   (interior, offset + thickness)
/// 0..3 = bottom (ext1, ext2, int2, int1) · 4..7 = top, same order
/// ```
#[must_use]
pub fn generate_layer_mesh(
    wall: &ParametricWall,
    _layer: &WallLayer, // layer info reserved for colour in future (as in C++)
    layer_offset: f32,
    layer_thickness: f32,
) -> MeshData {
    let mut mesh = MeshData::default();

    // C++ sentinel: adjusted == (0,0) means "not adjusted".
    let start = if wall.adjusted_start != Vec2::ZERO { wall.adjusted_start } else { wall.start_point };
    let end = if wall.adjusted_end != Vec2::ZERO { wall.adjusted_end } else { wall.end_point };

    let delta = end - start;
    let length = delta.length();
    if length < 0.001 {
        return mesh;
    }

    let dir = delta / length;
    let normal = Vec2::new(-dir.y, dir.x); // perpendicular, points left of travel

    // Layer extents from the centerline.
    let ext1 = start + normal * layer_offset;
    let ext2 = end + normal * layer_offset;
    let int1 = start + normal * (layer_offset + layer_thickness);
    let int2 = end + normal * (layer_offset + layer_thickness);

    let base = wall.base_height;
    let top = wall.top_height;

    // Same vertex order as the C++ (see layout above).
    mesh.vertices = vec![
        Vec3::new(ext1.x, base, ext1.y), // 0 exterior start bottom
        Vec3::new(ext2.x, base, ext2.y), // 1 exterior end bottom
        Vec3::new(int2.x, base, int2.y), // 2 interior end bottom
        Vec3::new(int1.x, base, int1.y), // 3 interior start bottom
        Vec3::new(ext1.x, top, ext1.y),  // 4 exterior start top
        Vec3::new(ext2.x, top, ext2.y),  // 5 exterior end top
        Vec3::new(int2.x, top, int2.y),  // 6 interior end top
        Vec3::new(int1.x, top, int1.y),  // 7 interior start top
    ];

    // 12 single-sided triangles, outward normals (CCW from outside):
    mesh.faces = vec![
        [0, 4, 5], [0, 5, 1], // exterior face (−normal side)
        [3, 2, 6], [3, 6, 7], // interior face (+normal side)
        [0, 3, 7], [0, 7, 4], // start cap
        [1, 5, 6], [1, 6, 2], // end cap
        [0, 1, 2], [0, 2, 3], // bottom
        [4, 7, 6], [4, 6, 5], // top
    ];

    mesh
}

/// Detect corners between walls: any two endpoints within `tolerance`.
#[must_use]
pub fn detect_corners(walls: &[ParametricWall], tolerance: f32) -> Vec<WallCorner> {
    let mut corners = Vec::new();

    for (i, w1) in walls.iter().enumerate() {
        for (j, w2) in walls.iter().enumerate().skip(i + 1) {
            let endpoints1 = [w1.start_point, w1.end_point];
            let endpoints2 = [w2.start_point, w2.end_point];

            for (e1, &p1) in endpoints1.iter().enumerate() {
                for (e2, &p2) in endpoints2.iter().enumerate() {
                    if p1.distance(p2) >= tolerance {
                        continue;
                    }

                    let is_start1 = e1 == 0;
                    let is_start2 = e2 == 0;

                    // Corner type from the angle between the wall directions
                    // (flipped so both point away from the corner).
                    let mut dir1 = w1.direction();
                    let mut dir2 = w2.direction();
                    if !is_start1 {
                        dir1 = -dir1;
                    }
                    if !is_start2 {
                        dir2 = -dir2;
                    }

                    let dot = dir1.dot(dir2);
                    let corner_type = if dot.abs() < 0.1 {
                        CornerType::LCorner // ~90 degrees
                    } else if dot < -0.7 {
                        CornerType::Butt // ~180 degrees (continuation)
                    } else {
                        CornerType::Miter // other angles
                    };

                    corners.push(WallCorner {
                        wall1_index: i as u32,
                        wall2_index: j as u32,
                        location: (p1 + p2) * 0.5,
                        corner_type,
                        is_start1,
                        is_start2,
                    });
                }
            }
        }
    }

    corners
}

/// Process corners: adjust wall endpoints for proper layer connections,
/// then regenerate geometry. L-corners extend each wall past the corner
/// point by the *other* wall's half-thickness so outer faces meet.
pub fn process_corners(
    walls: &mut [ParametricWall],
    types: &[WallType],
    corners: &[WallCorner],
) {
    // Initialize adjusted points to the original centerline endpoints.
    for wall in walls.iter_mut() {
        wall.adjusted_start = wall.start_point;
        wall.adjusted_end = wall.end_point;
    }

    for corner in corners {
        let (i, j) = (corner.wall1_index as usize, corner.wall2_index as usize);
        // Split borrow: i < j is guaranteed by detect_corners.
        let (w1, w2) = if i < j {
            let (a, b) = walls.split_at_mut(j);
            (&mut a[i], &mut b[0])
        } else {
            let (a, b) = walls.split_at_mut(i);
            (&mut b[0], &mut a[j])
        };

        let half_thick1 = types[w1.wall_type_index as usize].total_thickness() / 2.0;
        let half_thick2 = types[w2.wall_type_index as usize].total_thickness() / 2.0;

        let dir1 = w1.direction();
        let dir2 = w2.direction();

        if corner.corner_type == CornerType::LCorner {
            // Extend/trim wall 1.
            if corner.is_start1 {
                w1.adjusted_start = corner.location - dir1 * half_thick2;
            } else {
                w1.adjusted_end = corner.location + dir1 * half_thick2;
            }
            // Extend/trim wall 2.
            if corner.is_start2 {
                w2.adjusted_start = corner.location - dir2 * half_thick1;
            } else {
                w2.adjusted_end = corner.location + dir2 * half_thick1;
            }
        }
    }

    // Regenerate geometry with the adjusted endpoints.
    for wall in walls.iter_mut() {
        let wall_type = &types[wall.wall_type_index as usize];
        generate_wall_geometry(wall, wall_type);
    }
}

/// Convert parametric walls to structural elements for rendering —
/// one element per layer mesh, with a bounding box for selection.
#[must_use]
pub fn to_structural_elements(
    walls: &[ParametricWall],
    types: &[WallType],
) -> Vec<StructuralElement> {
    let mut elements = Vec::new();

    for wall in walls {
        let Some(wall_type) = types.get(wall.wall_type_index as usize) else {
            continue;
        };

        for mesh in &wall.layer_meshes {
            let start = if wall.adjusted_start != Vec2::ZERO { wall.adjusted_start } else { wall.start_point };
            let end = if wall.adjusted_end != Vec2::ZERO { wall.adjusted_end } else { wall.end_point };

            elements.push(StructuralElement {
                element_type: ElementType::Wall,
                material: "composite".into(),
                width: wall_type.total_thickness(),
                depth: wall_type.total_thickness(),
                stress: 0.0,
                deflection: 0.0,
                failed: false,
                mesh: mesh.clone(),
                start: Vec3::new(start.x.min(end.x), wall.base_height, start.y.min(end.y)),
                end: Vec3::new(start.x.max(end.x), wall.top_height, start.y.max(end.y)),
                ..Default::default()
            });
        }
    }

    elements
}

/// Line–line intersection (helper kept from the C++; currently unused by
/// the corner logic but part of the public surface there).
#[must_use]
pub fn line_intersection(p1: Vec2, p2: Vec2, p3: Vec2, p4: Vec2) -> Option<Vec2> {
    let d1 = p2 - p1;
    let d2 = p4 - p3;

    let cross = d1.x * d2.y - d1.y * d2.x;
    if cross.abs() < 0.0001 {
        return None; // parallel
    }

    let d3 = p3 - p1;
    let t = (d3.x * d2.y - d3.y * d2.x) / cross;
    Some(p1 + d1 * t)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn wall(start: Vec2, end: Vec2) -> ParametricWall {
        ParametricWall {
            start_point: start,
            end_point: end,
            base_height: 0.0,
            top_height: 9.0,
            wall_type_index: 0,
            ..Default::default()
        }
    }

    fn face_normal(m: &MeshData, face: [u32; 3]) -> Vec3 {
        let [a, b, c] = face;
        let e1 = m.vertices[b as usize] - m.vertices[a as usize];
        let e2 = m.vertices[c as usize] - m.vertices[a as usize];
        e1.cross(e2).normalize()
    }

    #[test]
    fn layer_mesh_is_single_sided_box_with_outward_normals() {
        // Wall along +X at Z=0; one layer spanning the full thickness.
        let w = wall(Vec2::ZERO, Vec2::new(10.0, 0.0));
        let layers = &defaults::interior().layers;
        let m = generate_layer_mesh(&w, &layers[1], -0.146, 0.292);

        assert_eq!(m.vertices.len(), 8);
        assert_eq!(m.faces.len(), 12); // C++ emitted 24 (both windings)

        // Exterior face (faces 0-1) must point −Z, interior (2-3) +Z.
        assert!(face_normal(&m, m.faces[0]).z < -0.99);
        assert!(face_normal(&m, m.faces[2]).z > 0.99);
        // Top face (faces 10-11) points +Y; bottom (8-9) −Y.
        assert!(face_normal(&m, m.faces[10]).y > 0.99);
        assert!(face_normal(&m, m.faces[8]).y < -0.99);
        // Start cap −X, end cap +X.
        assert!(face_normal(&m, m.faces[4]).x < -0.99);
        assert!(face_normal(&m, m.faces[6]).x > 0.99);
    }

    #[test]
    fn degenerate_wall_yields_empty_mesh() {
        let w = wall(Vec2::ZERO, Vec2::ZERO);
        let layers = &defaults::interior().layers;
        assert!(!generate_layer_mesh(&w, &layers[0], 0.0, 0.05).has_data());
    }

    #[test]
    fn insulation_is_skipped_and_offsets_stack() {
        let mut w = wall(Vec2::ZERO, Vec2::new(10.0, 0.0));
        let wt = defaults::exterior_2x6();
        generate_wall_geometry(&mut w, &wt);
        // 6 layers, one insulation → 5 meshes.
        assert_eq!(w.layer_meshes.len(), 5);
        // Exterior face of the first layer sits at −total/2.
        let total: f32 = wt
            .layers
            .iter()
            .filter(|l| l.function != LayerFunction::Insulation)
            .map(|l| l.thickness)
            .sum();
        let first = &w.layer_meshes[0];
        assert!((first.vertices[0].z - (-total / 2.0)).abs() < 1e-5);
    }

    #[test]
    fn detects_l_corner_and_butt() {
        // Wall A along +X ending at (10,0); wall B starts there heading +Z.
        let a = wall(Vec2::ZERO, Vec2::new(10.0, 0.0));
        let b = wall(Vec2::new(10.0, 0.0), Vec2::new(10.0, 8.0));
        // Wall C continues A's line from its end (butt joint).
        let c = wall(Vec2::new(10.0, 0.0), Vec2::new(20.0, 0.0));

        // All three pairs share the (10,0) endpoint: A–B (90°), A–C
        // (straight), and B–C (90°, both start there).
        let corners = detect_corners(&[a.clone(), b.clone(), c], 0.1);
        assert_eq!(corners.len(), 3);
        let l_count = corners.iter().filter(|c| c.corner_type == CornerType::LCorner).count();
        let butt_count = corners.iter().filter(|c| c.corner_type == CornerType::Butt).count();
        assert_eq!(l_count, 2, "A/B and B/C meet at 90°");
        assert_eq!(butt_count, 1, "A/C continue straight");
    }

    #[test]
    fn process_corners_extends_l_corner_walls() {
        let mut walls = vec![
            wall(Vec2::ZERO, Vec2::new(10.0, 0.0)),
            wall(Vec2::new(10.0, 0.0), Vec2::new(10.0, 8.0)),
        ];
        let types = vec![defaults::interior()];
        walls[0].wall_type_index = 0;
        walls[1].wall_type_index = 0;
        let corners = detect_corners(&walls, 0.1);
        process_corners(&mut walls, &types, &corners);

        let half = types[0].total_thickness() / 2.0;
        // Wall 0's end extended along +X by wall 1's half-thickness.
        assert!((walls[0].adjusted_end.x - (10.0 + half)).abs() < 1e-5);
        // Wall 1's start extended along −Z by wall 0's half-thickness.
        assert!((walls[1].adjusted_start.y - (-half)).abs() < 1e-5);
        // Geometry regenerated from adjusted endpoints.
        assert!(walls[0].layer_meshes.iter().all(MeshData::has_data));
    }

    #[test]
    fn structural_elements_carry_bbox_and_mesh() {
        let mut walls = vec![wall(Vec2::ZERO, Vec2::new(10.0, 0.0))];
        let types = vec![defaults::interior()];
        for w in &mut walls {
            generate_wall_geometry(w, &types[0]);
        }
        let elements = to_structural_elements(&walls, &types);
        // Interior partition: 2 drywall + 1 stud = 3 layer meshes.
        assert_eq!(elements.len(), 3);
        assert_eq!(elements[0].element_type, ElementType::Wall);
        assert_eq!(elements[0].start, Vec3::ZERO);
        assert_eq!(elements[0].end, Vec3::new(10.0, 9.0, 0.0));
    }

    #[test]
    fn line_intersection_crossing_and_parallel() {
        let hit = line_intersection(
            Vec2::new(0.0, 0.0),
            Vec2::new(2.0, 2.0),
            Vec2::new(0.0, 2.0),
            Vec2::new(2.0, 0.0),
        );
        assert!((hit.unwrap() - Vec2::new(1.0, 1.0)).length() < 1e-5);
        assert!(line_intersection(Vec2::ZERO, Vec2::X, Vec2::Y, Vec2::X + Vec2::Y).is_none());
    }
}
