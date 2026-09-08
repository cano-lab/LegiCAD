//! Floor slab geometry generator.
//!
//! Port of `Shared/ArchGeometry/src/floor_geometry.cpp`.
//!
//! Coordinate convention (unchanged from C++):
//! - `start` / `end` define the XZ bounds (the plan-view rectangle).
//! - `start.y` is the elevation — i.e. the *top* of the slab.
//! - `thickness` is the Y dimension (slab depth), counted *downward* from
//!   the top — bottom = `start.y - thickness`.

use crate::arch::geometry_types::{FloorGeometry, Geometry2D, Mesh3D, Point2D, Polygon2D};
use crate::arch::schema_types::SchemaFloor;
use glam::Vec3;

/// Material name → render colour. Match the dispatch in `floor_geometry.cpp:94`.
#[must_use]
pub fn material_color(material: &str) -> Vec3 {
    match material {
        "hardwood" | "wood" => Vec3::new(0.65, 0.45, 0.25),
        "tile" | "ceramic" => Vec3::new(0.85, 0.85, 0.8),
        "carpet" => Vec3::new(0.6, 0.55, 0.5),
        "concrete" => Vec3::new(0.7, 0.7, 0.7),
        "marble" => Vec3::new(0.95, 0.95, 0.92),
        "vinyl" | "lvp" => Vec3::new(0.75, 0.6, 0.45),
        _ => Vec3::new(0.8, 0.8, 0.78),
    }
}

/// Generate the full `FloorGeometry` (3D mesh + 2D plan view).
#[must_use]
pub fn generate(floor: &SchemaFloor) -> FloorGeometry {
    let min_x = floor.start.x.min(floor.end.x);
    let max_x = floor.start.x.max(floor.end.x);
    let min_z = floor.start.z.min(floor.end.z);
    let max_z = floor.start.z.max(floor.end.z);

    let top_y = floor.start.y;
    let bottom_y = top_y - floor.thickness;

    let mut mesh = generate_mesh(min_x, max_x, min_z, max_z, bottom_y, top_y, &floor.material);
    mesh.element_type = "floor".to_string();
    mesh.lod_hint = 0;

    let mut plan = Geometry2D {
        element_type: "floor".to_string(),
        ..Default::default()
    };
    plan.polygons.push(generate_plan_polygon(floor));

    FloorGeometry {
        mesh_3d: mesh,
        plan_view: plan,
        floor_id: floor.level_name.clone(),
        room_id: floor.room.clone().unwrap_or_default(),
        floor_index: -1,
    }
}

/// Generate the slab mesh (6 quads = 12 triangles).
#[must_use]
pub fn generate_mesh(
    min_x: f32,
    max_x: f32,
    min_z: f32,
    max_z: f32,
    bottom_y: f32,
    top_y: f32,
    material: &str,
) -> Mesh3D {
    let mut mesh = Mesh3D::default();
    let color = material_color(material);

    // Bottom corners.
    let b0 = Vec3::new(min_x, bottom_y, min_z);
    let b1 = Vec3::new(max_x, bottom_y, min_z);
    let b2 = Vec3::new(max_x, bottom_y, max_z);
    let b3 = Vec3::new(min_x, bottom_y, max_z);

    // Top corners.
    let t0 = Vec3::new(min_x, top_y, min_z);
    let t1 = Vec3::new(max_x, top_y, min_z);
    let t2 = Vec3::new(max_x, top_y, max_z);
    let t3 = Vec3::new(min_x, top_y, max_z);

    // Top face (visible from above).
    mesh.add_quad(t0, t1, t2, t3, Vec3::new(0.0, 1.0, 0.0), color);
    // Bottom face.
    mesh.add_quad(b3, b2, b1, b0, Vec3::new(0.0, -1.0, 0.0), color);
    // Side faces.
    mesh.add_quad(t0, b0, b1, t1, Vec3::new(0.0, 0.0, -1.0), color); // front
    mesh.add_quad(t2, b2, b3, t3, Vec3::new(0.0, 0.0, 1.0), color); // back
    mesh.add_quad(t3, b3, b0, t0, Vec3::new(-1.0, 0.0, 0.0), color); // left
    mesh.add_quad(t1, b1, b2, t2, Vec3::new(1.0, 0.0, 0.0), color); // right

    mesh
}

/// Plan-view polygon for a floor (semi-transparent solid fill).
#[must_use]
pub fn generate_plan_polygon(floor: &SchemaFloor) -> Polygon2D {
    let min_x = floor.start.x.min(floor.end.x);
    let max_x = floor.start.x.max(floor.end.x);
    let min_z = floor.start.z.min(floor.end.z);
    let max_z = floor.start.z.max(floor.end.z);

    let color = material_color(&floor.material);

    Polygon2D {
        points: vec![
            Point2D::new(min_x, min_z),
            Point2D::new(max_x, min_z),
            Point2D::new(max_x, max_z),
            Point2D::new(min_x, max_z),
        ],
        closed: true,
        layer: "floors".to_string(),
        fill_pattern: "solid".to_string(),
        fill_color: [color.x, color.y, color.z, 0.3],
    }
}

/// 3D bounding box: min in XZ × `start.y - thickness`, max in XZ × `start.y`.
#[must_use]
pub fn bounds(floor: &SchemaFloor) -> (Vec3, Vec3) {
    let min = Vec3::new(
        floor.start.x.min(floor.end.x),
        floor.start.y - floor.thickness,
        floor.start.z.min(floor.end.z),
    );
    let max = Vec3::new(
        floor.start.x.max(floor.end.x),
        floor.start.y,
        floor.start.z.max(floor.end.z),
    );
    (min, max)
}

/// Plan-view centre point.
#[must_use]
pub fn center(floor: &SchemaFloor) -> Point2D {
    Point2D::new(
        (floor.start.x + floor.end.x) * 0.5,
        (floor.start.z + floor.end.z) * 0.5,
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    fn rect_floor() -> SchemaFloor {
        SchemaFloor {
            start: Vec3::new(0.0, 3048.0, 0.0),
            end: Vec3::new(9144.0, 3048.0, 12192.0),
            thickness: 200.0,
            level_name: "Level 2".to_string(),
            material: "concrete".to_string(),
            ..Default::default()
        }
    }

    #[test]
    fn material_color_falls_through_to_default() {
        // Unknown materials get the default light-gray.
        assert_eq!(material_color("unobtainium"), Vec3::new(0.8, 0.8, 0.78));
    }

    #[test]
    fn generate_emits_24_verts_and_12_triangles() {
        // 6 quads × add_quad emits 4 verts + 2 tris each.
        let f = rect_floor();
        let g = generate(&f);
        assert_eq!(g.mesh_3d.vertex_count(), 24);
        assert_eq!(g.mesh_3d.triangle_count(), 12);
        assert_eq!(g.mesh_3d.element_type, "floor");
        assert_eq!(g.floor_id, "Level 2");
    }

    #[test]
    fn bounds_use_thickness_down_from_start_y() {
        let f = rect_floor();
        let (min, max) = bounds(&f);
        assert_eq!(min.x, 0.0);
        assert_eq!(max.x, 9144.0);
        assert_eq!(min.z, 0.0);
        assert_eq!(max.z, 12192.0);
        // Slab top at start.y=3048, bottom 200 below.
        assert_eq!(max.y, 3048.0);
        assert_eq!(min.y, 2848.0);
    }

    #[test]
    fn plan_polygon_has_4_corners_in_xz_order() {
        let f = rect_floor();
        let p = generate_plan_polygon(&f);
        assert_eq!(p.points.len(), 4);
        assert_eq!(p.points[0], Point2D::new(0.0, 0.0));
        assert_eq!(p.points[1], Point2D::new(9144.0, 0.0));
        assert_eq!(p.points[2], Point2D::new(9144.0, 12192.0));
        assert_eq!(p.points[3], Point2D::new(0.0, 12192.0));
        assert!(p.closed);
        assert_eq!(p.fill_pattern, "solid");
        // Concrete: rgb(0.7, 0.7, 0.7) + alpha 0.3.
        assert_eq!(p.fill_color, [0.7, 0.7, 0.7, 0.3]);
    }

    #[test]
    fn center_is_midpoint_in_xz() {
        let f = rect_floor();
        let c = center(&f);
        assert_eq!(c, Point2D::new(4572.0, 6096.0));
    }

    #[test]
    fn handles_reversed_corners() {
        // start > end on both axes; min/max logic should still produce
        // the same slab.
        let f = SchemaFloor {
            start: Vec3::new(9144.0, 0.0, 12192.0),
            end: Vec3::new(0.0, 0.0, 0.0),
            thickness: 200.0,
            ..Default::default()
        };
        let g = generate(&f);
        assert_eq!(g.mesh_3d.vertex_count(), 24);
        let (min, max) = bounds(&f);
        assert_eq!(min.x, 0.0);
        assert_eq!(max.x, 9144.0);
        assert_eq!(min.z, 0.0);
        assert_eq!(max.z, 12192.0);
    }
}
