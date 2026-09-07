//! Roof geometry generator.
//!
//! Port of `Shared/ArchGeometry/src/roof_geometry.cpp`.
//!
//! Two paths:
//! - If the schema provides explicit `RoofSurface` polygons, triangulate
//!   each (fan from vertex 0) and emit top, underside, and fascia faces.
//! - Otherwise generate a procedural default (gable or hip) from building
//!   bounds. The procedural path isn't called by `generate_from_schema` —
//!   it's an API surface for callers who already have the bounds.

use crate::geometry_types::{Geometry2D, Mesh3D, Point2D, Polygon2D, RoofGeometry};
use crate::schema_types::{RoofSurface, SchemaRoof};
use glam::Vec3;

/// Roof thickness in mm — used for the underside and fascia faces. Matches
/// the constant in `roof_geometry.cpp:71` and `:97`.
const ROOF_THICKNESS: f32 = 200.0;

/// Material name → render colour. Matches `roof_geometry.cpp:139`.
#[must_use]
pub fn material_color(material: &str) -> Vec3 {
    match material {
        "asphalt_shingle" | "shingle" => Vec3::new(0.3, 0.3, 0.32),
        "metal" | "standing_seam" => Vec3::new(0.5, 0.52, 0.55),
        "tile" | "clay_tile" => Vec3::new(0.7, 0.35, 0.25),
        "slate" => Vec3::new(0.35, 0.38, 0.42),
        "wood_shake" => Vec3::new(0.5, 0.4, 0.3),
        "copper" => Vec3::new(0.6, 0.45, 0.35),
        _ => Vec3::new(0.4, 0.4, 0.42),
    }
}

/// Convert rise:12 pitch to radians.
#[must_use]
pub fn pitch_to_angle(pitch: f32) -> f32 {
    (pitch / 12.0).atan()
}

/// Ridge height above eaves for a given pitch and total span.
#[must_use]
pub fn ridge_height(pitch: f32, span: f32) -> f32 {
    let half_span = span * 0.5;
    half_span * pitch_to_angle(pitch).tan()
}

/// Slope length (rafter length) from pitch and span.
#[must_use]
pub fn slope_length(pitch: f32, span: f32) -> f32 {
    let half_span = span * 0.5;
    let rh = ridge_height(pitch, span);
    (half_span * half_span + rh * rh).sqrt()
}

/// Top-level entry: build a `RoofGeometry` from a `SchemaRoof`.
#[must_use]
pub fn generate(roof: &SchemaRoof) -> RoofGeometry {
    let mut mesh = if roof.surfaces.is_empty() {
        // C++ leaves the fallback empty too — needs bounds. See
        // `generate_gable_default` / `generate_hip_default` for callers
        // that have them.
        Mesh3D::default()
    } else {
        generate_from_surfaces(roof)
    };
    mesh.element_type = "roof".to_string();
    mesh.lod_hint = 1;

    let mut plan = Geometry2D {
        element_type: "roof".to_string(),
        ..Default::default()
    };
    for surface in &roof.surfaces {
        plan.polygons
            .push(generate_plan_polygon(surface, &roof.material));
    }

    RoofGeometry {
        mesh_3d: mesh,
        plan_view: plan,
        roof_id: roof.id.clone(),
        roof_index: -1,
        ..Default::default()
    }
}

/// Build the 3D mesh from per-surface vertex polygons.
#[must_use]
pub fn generate_from_surfaces(roof: &SchemaRoof) -> Mesh3D {
    let mut mesh = Mesh3D::default();
    let color = material_color(&roof.material);

    // 1) Top faces: fan-triangulate each surface from vertex 0.
    for surface in &roof.surfaces {
        if surface.vertices.len() < 3 {
            continue;
        }
        let v0 = surface.vertices[0];
        for i in 1..surface.vertices.len() - 1 {
            let v1 = surface.vertices[i];
            let v2 = surface.vertices[i + 1];
            let edge1 = v1 - v0;
            let edge2 = v2 - v0;
            let normal = edge1.cross(edge2).normalize();
            mesh.add_triangle(v0, v1, v2, normal, color);
        }
    }

    // 2) Underside (offset down by ROOF_THICKNESS, reversed winding).
    for surface in &roof.surfaces {
        if surface.vertices.len() < 3 {
            continue;
        }
        let offset = Vec3::new(0.0, -ROOF_THICKNESS, 0.0);
        let v0 = surface.vertices[0] + offset;
        for i in 1..surface.vertices.len() - 1 {
            let v1 = surface.vertices[i] + offset;
            let v2 = surface.vertices[i + 1] + offset;
            let edge1 = v1 - v0;
            let edge2 = v2 - v0;
            // Reversed cross order for underside normal.
            let normal = edge2.cross(edge1).normalize();
            mesh.add_triangle(v0, v2, v1, normal, color);
        }
    }

    // 3) Fascia (edge faces connecting top to underside).
    for surface in &roof.surfaces {
        if surface.vertices.len() < 3 {
            continue;
        }
        let n = surface.vertices.len();
        for i in 0..n {
            let j = (i + 1) % n;
            let t0 = surface.vertices[i];
            let t1 = surface.vertices[j];
            let b0 = Vec3::new(t0.x, t0.y - ROOF_THICKNESS, t0.z);
            let b1 = Vec3::new(t1.x, t1.y - ROOF_THICKNESS, t1.z);
            let edge = t1 - t0;
            let down = Vec3::new(0.0, -1.0, 0.0);
            let normal = edge.cross(down).normalize();
            mesh.add_quad(t0, b0, b1, t1, normal, color);
        }
    }

    mesh
}

/// Plan polygon for a single roof surface (just the XZ projection).
#[must_use]
pub fn generate_plan_polygon(surface: &RoofSurface, material: &str) -> Polygon2D {
    let points: Vec<Point2D> = surface
        .vertices
        .iter()
        .map(|v| Point2D::new(v.x, v.z))
        .collect();
    let color = material_color(material);
    Polygon2D {
        points,
        closed: true,
        layer: "roof".to_string(),
        fill_pattern: "hatch_diagonal".to_string(),
        fill_color: [color.x, color.y, color.z, 0.2],
    }
}

/// Procedural gable roof from building min/max bounds. Not currently called
/// by `generate_from_schema` (the schema-driven path uses surfaces).
#[must_use]
pub fn generate_gable_default(
    min: Vec3,
    max: Vec3,
    pitch: f32,
    overhang: f32,
    material: &str,
) -> Mesh3D {
    let mut mesh = Mesh3D::default();
    let color = material_color(material);

    let building_width = max.x - min.x;
    let eave_height = max.y;
    let rh = ridge_height(pitch, building_width);
    let ridge_x = (min.x + max.x) * 0.5;
    let ridge_y = eave_height + rh;

    let eave_min_x = min.x - overhang;
    let eave_max_x = max.x + overhang;
    let eave_min_z = min.z - overhang;
    let eave_max_z = max.z + overhang;

    // Left slope (quad).
    let l0 = Vec3::new(eave_min_x, eave_height, eave_min_z);
    let l1 = Vec3::new(eave_min_x, eave_height, eave_max_z);
    let l2 = Vec3::new(ridge_x, ridge_y, eave_max_z);
    let l3 = Vec3::new(ridge_x, ridge_y, eave_min_z);
    let left_normal = (l1 - l0).cross(l3 - l0).normalize();
    mesh.add_quad(l0, l1, l2, l3, left_normal, color);

    // Right slope (quad).
    let r0 = Vec3::new(ridge_x, ridge_y, eave_min_z);
    let r1 = Vec3::new(ridge_x, ridge_y, eave_max_z);
    let r2 = Vec3::new(eave_max_x, eave_height, eave_max_z);
    let r3 = Vec3::new(eave_max_x, eave_height, eave_min_z);
    let right_normal = (r1 - r0).cross(r3 - r0).normalize();
    mesh.add_quad(r0, r1, r2, r3, right_normal, color);

    // Front gable triangle.
    mesh.add_triangle(
        Vec3::new(eave_min_x, eave_height, eave_min_z),
        Vec3::new(ridge_x, ridge_y, eave_min_z),
        Vec3::new(eave_max_x, eave_height, eave_min_z),
        Vec3::new(0.0, 0.0, -1.0),
        color,
    );

    // Back gable triangle.
    mesh.add_triangle(
        Vec3::new(eave_max_x, eave_height, eave_max_z),
        Vec3::new(ridge_x, ridge_y, eave_max_z),
        Vec3::new(eave_min_x, eave_height, eave_max_z),
        Vec3::new(0.0, 0.0, 1.0),
        color,
    );

    mesh
}

/// Procedural hip roof from building min/max bounds.
#[must_use]
pub fn generate_hip_default(
    min: Vec3,
    max: Vec3,
    pitch: f32,
    overhang: f32,
    material: &str,
) -> Mesh3D {
    let mut mesh = Mesh3D::default();
    let color = material_color(material);

    let building_width = max.x - min.x;
    let building_depth = max.z - min.z;
    let eave_height = max.y;
    let min_dim = building_width.min(building_depth);
    let rh = ridge_height(pitch, min_dim);
    let ridge_y = eave_height + rh;

    let eave_min_x = min.x - overhang;
    let eave_max_x = max.x + overhang;
    let eave_min_z = min.z - overhang;
    let eave_max_z = max.z + overhang;

    let ridge_inset = min_dim * 0.5;
    let (ridge_start, ridge_end) = if building_width >= building_depth {
        (
            Vec3::new(min.x + ridge_inset, ridge_y, (min.z + max.z) * 0.5),
            Vec3::new(max.x - ridge_inset, ridge_y, (min.z + max.z) * 0.5),
        )
    } else {
        (
            Vec3::new((min.x + max.x) * 0.5, ridge_y, min.z + ridge_inset),
            Vec3::new((min.x + max.x) * 0.5, ridge_y, max.z - ridge_inset),
        )
    };

    let c0 = Vec3::new(eave_min_x, eave_height, eave_min_z);
    let c1 = Vec3::new(eave_max_x, eave_height, eave_min_z);
    let c2 = Vec3::new(eave_max_x, eave_height, eave_max_z);
    let c3 = Vec3::new(eave_min_x, eave_height, eave_max_z);

    if building_width >= building_depth {
        let front_normal = (c1 - c0).cross(ridge_start - c0).normalize();
        mesh.add_quad(c0, c1, ridge_end, ridge_start, front_normal, color);
        let back_normal = (c3 - c2).cross(ridge_end - c2).normalize();
        mesh.add_quad(c2, c3, ridge_start, ridge_end, back_normal, color);
        let left_normal = (c0 - c3).cross(ridge_start - c3).normalize();
        mesh.add_triangle(c3, c0, ridge_start, left_normal, color);
        let right_normal = (c2 - c1).cross(ridge_end - c1).normalize();
        mesh.add_triangle(c1, c2, ridge_end, right_normal, color);
    } else {
        // Ridge runs along Z — the C++ uses hand-picked approximate normals
        // here rather than re-deriving via cross products (see `roof_geometry.cpp:335`+).
        mesh.add_quad(
            c3,
            c0,
            ridge_start,
            ridge_end,
            Vec3::new(-1.0, 0.5, 0.0).normalize(),
            color,
        );
        mesh.add_quad(
            c1,
            c2,
            ridge_end,
            ridge_start,
            Vec3::new(1.0, 0.5, 0.0).normalize(),
            color,
        );
        mesh.add_triangle(
            c0,
            c1,
            ridge_start,
            Vec3::new(0.0, 0.5, -1.0).normalize(),
            color,
        );
        mesh.add_triangle(
            c2,
            c3,
            ridge_end,
            Vec3::new(0.0, 0.5, 1.0).normalize(),
            color,
        );
    }

    mesh
}

#[cfg(test)]
mod tests {
    use super::*;

    fn flat_square_surface() -> RoofSurface {
        RoofSurface {
            id: "flat".into(),
            vertices: vec![
                Vec3::new(0.0, 1000.0, 0.0),
                Vec3::new(1000.0, 1000.0, 0.0),
                Vec3::new(1000.0, 1000.0, 1000.0),
                Vec3::new(0.0, 1000.0, 1000.0),
            ],
            pitch: 0.0,
            orientation: String::new(),
        }
    }

    #[test]
    fn pitch_to_angle_six_twelve() {
        // 6:12 pitch ≈ atan(0.5) ≈ 26.565°.
        let a = pitch_to_angle(6.0).to_degrees();
        assert!((a - 26.565).abs() < 0.01);
    }

    #[test]
    fn ridge_height_at_six_twelve_over_12000mm() {
        // 6:12 pitch, 12000mm span → rh = 6000 * tan(atan(0.5)) = 3000mm.
        let rh = ridge_height(6.0, 12000.0);
        assert!((rh - 3000.0).abs() < 1e-3);
    }

    #[test]
    fn empty_roof_produces_empty_mesh() {
        let roof = SchemaRoof::default();
        let g = generate(&roof);
        assert_eq!(g.mesh_3d.vertex_count(), 0);
        assert!(g.plan_view.polygons.is_empty());
    }

    #[test]
    fn single_quad_surface_produces_top_under_fascia() {
        // 4-vertex flat surface:
        // - top:  fan triangulation = 2 triangles, 6 verts (add_triangle)
        // - under: 2 triangles, 6 verts
        // - fascia: 4 quads (one per edge) = 4 * (4 verts + 2 tris) = 16 verts, 8 tris
        // Total: 6 + 6 + 16 = 28 verts, 2 + 2 + 8 = 12 triangles.
        let roof = SchemaRoof {
            surfaces: vec![flat_square_surface()],
            ..Default::default()
        };
        let g = generate(&roof);
        assert_eq!(g.mesh_3d.vertex_count(), 28);
        assert_eq!(g.mesh_3d.triangle_count(), 12);
        assert_eq!(g.mesh_3d.element_type, "roof");
        assert_eq!(g.mesh_3d.lod_hint, 1);
        // Plan view has the surface polygon.
        assert_eq!(g.plan_view.polygons.len(), 1);
        assert_eq!(g.plan_view.polygons[0].points.len(), 4);
    }

    #[test]
    fn plan_polygon_drops_y_component() {
        let surface = flat_square_surface();
        let poly = generate_plan_polygon(&surface, "asphalt_shingle");
        assert_eq!(poly.points[0], Point2D::new(0.0, 0.0));
        assert_eq!(poly.points[2], Point2D::new(1000.0, 1000.0));
        assert_eq!(poly.layer, "roof");
        assert_eq!(poly.fill_pattern, "hatch_diagonal");
    }

    #[test]
    fn gable_default_produces_2_quads_and_2_triangles() {
        let m = generate_gable_default(
            Vec3::ZERO,
            Vec3::new(8000.0, 2700.0, 6000.0),
            6.0,
            600.0,
            "asphalt_shingle",
        );
        // 2 quads (4 v + 2 t each) + 2 triangles (3 v + 1 t each)
        // = 8 + 6 verts = 14; 4 + 2 = 6 triangles.
        assert_eq!(m.vertex_count(), 14);
        assert_eq!(m.triangle_count(), 6);
    }
}
