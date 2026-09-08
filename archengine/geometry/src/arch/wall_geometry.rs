//! Wall geometry generator.
//!
//! Port of `Shared/ArchGeometry/src/wall_geometry.cpp`.
//!
//! Generates the wall mesh (6-face box, or segments around door/window
//! cutouts), the 2D plan-view polygon, and bookkeeping for the cutouts
//! themselves.

use crate::arch::geometry_types::{Geometry2D, Mesh3D, OpeningCutout, Point2D, Polygon2D, WallGeometry};
use crate::arch::schema_types::{SchemaDoor, SchemaWall, SchemaWindow, WallType};
use glam::{Vec2, Vec3};

/// Wall category → render colour. Matches `wall_geometry.cpp:130`.
#[must_use]
pub fn category_color(category: &str) -> Vec3 {
    match category {
        "exterior" => Vec3::new(0.85, 0.85, 0.8),
        "wet_wall" => Vec3::new(0.7, 0.85, 0.9),
        _ => Vec3::new(0.9, 0.9, 0.88),
    }
}

/// Total wall thickness from the assembly.
#[must_use]
pub fn thickness(wall_type: &WallType) -> f32 {
    wall_type.total_thickness()
}

/// Centreline endpoints.
#[must_use]
pub fn centerline(wall: &SchemaWall) -> (Vec3, Vec3) {
    (wall.start, wall.end)
}

/// 3D perpendicular offset (Y = 0).
#[must_use]
pub fn perpendicular_offset(wall: &SchemaWall, distance: f32) -> Vec3 {
    let perp = wall.direction().perp();
    Vec3::new(perp.x * distance, 0.0, perp.y * distance)
}

/// Generate the full `WallGeometry`, including cutouts for any doors and
/// windows that live on this wall.
#[must_use]
pub fn generate(
    wall: &SchemaWall,
    wall_type: &WallType,
    doors: &[SchemaDoor],
    windows: &[SchemaWindow],
) -> WallGeometry {
    let t = thickness(wall_type);
    let color = category_color(&wall.category);

    let mut cutouts: Vec<OpeningCutout> = doors
        .iter()
        .enumerate()
        .map(|(i, d)| OpeningCutout {
            start_offset: d.offset,
            bottom_height: 0.0, // doors start at floor
            width: d.width,
            height: d.height,
            opening_type: "door".to_string(),
            opening_index: i32::try_from(i).expect("opening index fits in i32"),
        })
        .collect();

    cutouts.extend(windows.iter().enumerate().map(|(i, w)| OpeningCutout {
        start_offset: w.offset,
        bottom_height: w.sill_height,
        width: w.width,
        height: w.height,
        opening_type: "window".to_string(),
        opening_index: i32::try_from(i).expect("opening index fits in i32"),
    }));

    let mut mesh = if cutouts.is_empty() {
        solid_mesh(wall.start, wall.end, wall.height, t, color)
    } else {
        mesh_with_cutouts(wall.start, wall.end, wall.height, t, color, &cutouts)
    };
    mesh.element_type = "wall".to_string();
    mesh.lod_hint = 0;

    let mut plan = Geometry2D {
        element_type: "wall".to_string(),
        ..Default::default()
    };
    plan.polygons.push(generate_plan_polygon(wall, t));

    WallGeometry {
        mesh_3d: mesh,
        plan_view: plan,
        section_view: Geometry2D::default(),
        cutouts,
        wall_id: wall.wall_type.clone(),
        wall_index: -1,
    }
}

/// Convenience: generate the wall without any door/window cutouts.
#[must_use]
pub fn generate_solid(wall: &SchemaWall, wall_type: &WallType) -> WallGeometry {
    generate(wall, wall_type, &[], &[])
}

/// 2D plan polygon (4 corners, offset by ±half-thickness perpendicular).
#[must_use]
pub fn generate_plan_polygon(wall: &SchemaWall, thickness: f32) -> Polygon2D {
    let dir = wall.direction();
    let perp = dir.perp();
    let half_t = thickness * 0.5;

    let p1 = Point2D::new(
        wall.start.x + perp.x * half_t,
        wall.start.z + perp.y * half_t,
    );
    let p2 = Point2D::new(
        wall.start.x - perp.x * half_t,
        wall.start.z - perp.y * half_t,
    );
    let p3 = Point2D::new(wall.end.x - perp.x * half_t, wall.end.z - perp.y * half_t);
    let p4 = Point2D::new(wall.end.x + perp.x * half_t, wall.end.z + perp.y * half_t);

    let (layer, fill_color) = if wall.category == "exterior" {
        ("walls_exterior".to_string(), [0.2, 0.2, 0.2, 1.0])
    } else {
        ("walls_interior".to_string(), [0.4, 0.4, 0.4, 1.0])
    };

    Polygon2D {
        points: vec![p1, p2, p3, p4],
        closed: true,
        layer,
        fill_pattern: "solid".to_string(),
        fill_color,
    }
}

/// Solid (no-opening) wall mesh — 6 quads = 12 triangles.
#[must_use]
pub fn solid_mesh(start: Vec3, end: Vec3, height: f32, thickness: f32, color: Vec3) -> Mesh3D {
    let mut mesh = Mesh3D::default();

    let dir = Vec2::new(end.x - start.x, end.z - start.z);
    let len = dir.length();
    if len < 0.001 {
        return mesh;
    }
    // Use `dir * (1.0 / len)` (matches C++ wall_geometry.cpp:155) instead
    // of `dir / len`. For non-integer wall lengths the two patterns yield
    // bit-different `dir` vectors because `x * (1/x)` is not always 1.0 in
    // IEEE-754 even when `x / x` is — and the divergence propagates into
    // downstream vertex Z coordinates. The diff oracle catches it.
    let dir = dir * (1.0 / len);
    let perp = dir.perp();
    let half_t = thickness * 0.5;

    // Bottom corners.
    let b0 = Vec3::new(
        start.x + perp.x * half_t,
        start.y,
        start.z + perp.y * half_t,
    );
    let b1 = Vec3::new(
        start.x - perp.x * half_t,
        start.y,
        start.z - perp.y * half_t,
    );
    let b2 = Vec3::new(end.x - perp.x * half_t, start.y, end.z - perp.y * half_t);
    let b3 = Vec3::new(end.x + perp.x * half_t, start.y, end.z + perp.y * half_t);

    // Top corners.
    let top_y = start.y + height;
    let t0 = Vec3::new(b0.x, top_y, b0.z);
    let t1 = Vec3::new(b1.x, top_y, b1.z);
    let t2 = Vec3::new(b2.x, top_y, b2.z);
    let t3 = Vec3::new(b3.x, top_y, b3.z);

    // Faces (winding chosen to match C++ wall_geometry.cpp:175-197 exactly).
    mesh.add_quad(b0, t0, t3, b3, Vec3::new(perp.x, 0.0, perp.y), color); // front (exterior)
    mesh.add_quad(b1, b2, t2, t1, Vec3::new(-perp.x, 0.0, -perp.y), color); // back (interior)
    mesh.add_quad(b0, b1, t1, t0, Vec3::new(-dir.x, 0.0, -dir.y), color); // left end
    mesh.add_quad(b3, t3, t2, b2, Vec3::new(dir.x, 0.0, dir.y), color); // right end
    mesh.add_quad(t0, t1, t2, t3, Vec3::new(0.0, 1.0, 0.0), color); // top
    mesh.add_quad(b0, b3, b2, b1, Vec3::new(0.0, -1.0, 0.0), color); // bottom

    mesh
}

/// Wall mesh with rectangular cutouts. Generates segments before, above,
/// below, and after each opening. The 1.0-unit gap threshold is preserved
/// from the C++ for byte-compat (`wall_geometry.cpp:235`).
#[must_use]
pub fn mesh_with_cutouts(
    start: Vec3,
    end: Vec3,
    height: f32,
    thickness: f32,
    color: Vec3,
    cutouts: &[OpeningCutout],
) -> Mesh3D {
    let mut mesh = Mesh3D::default();

    let dir = Vec2::new(end.x - start.x, end.z - start.z);
    let wall_length = dir.length();
    if wall_length < 0.001 {
        return mesh;
    }
    // Match C++'s `dir = dir * (1.0f / wallLength)` (wall_geometry.cpp:216)
    // for bit-identical normalisation. See `solid_mesh` for the why.
    let dir = dir * (1.0 / wall_length);

    // Sort cutouts by offset (stable so duplicates keep insertion order).
    let mut sorted: Vec<OpeningCutout> = cutouts.to_vec();
    sorted.sort_by(|a, b| {
        a.start_offset
            .partial_cmp(&b.start_offset)
            .unwrap_or(std::cmp::Ordering::Equal)
    });

    let mut current_offset = 0.0_f32;

    for cutout in &sorted {
        let cut_start = cutout.start_offset - cutout.width * 0.5;
        let cut_end = cutout.start_offset + cutout.width * 0.5;

        // Segment before opening.
        if cut_start > current_offset + 1.0 {
            let seg_start = Vec3::new(
                start.x + dir.x * current_offset,
                start.y,
                start.z + dir.y * current_offset,
            );
            let seg_end = Vec3::new(
                start.x + dir.x * cut_start,
                start.y,
                start.z + dir.y * cut_start,
            );
            mesh.merge(&solid_mesh(seg_start, seg_end, height, thickness, color));
        }

        // Wall above opening (when opening doesn't reach the ceiling).
        let opening_top = cutout.bottom_height + cutout.height;
        if opening_top < height - 1.0 {
            let above_start = Vec3::new(
                start.x + dir.x * cut_start,
                start.y + opening_top,
                start.z + dir.y * cut_start,
            );
            let above_end = Vec3::new(
                start.x + dir.x * cut_end,
                start.y + opening_top,
                start.z + dir.y * cut_end,
            );
            let above_height = height - opening_top;
            mesh.merge(&solid_mesh(
                above_start,
                above_end,
                above_height,
                thickness,
                color,
            ));
        }

        // Wall below opening (for windows).
        if cutout.bottom_height > 1.0 {
            let below_start = Vec3::new(
                start.x + dir.x * cut_start,
                start.y,
                start.z + dir.y * cut_start,
            );
            let below_end = Vec3::new(
                start.x + dir.x * cut_end,
                start.y,
                start.z + dir.y * cut_end,
            );
            mesh.merge(&solid_mesh(
                below_start,
                below_end,
                cutout.bottom_height,
                thickness,
                color,
            ));
        }

        current_offset = cut_end;
    }

    // Final segment after the last opening.
    if current_offset < wall_length - 1.0 {
        let seg_start = Vec3::new(
            start.x + dir.x * current_offset,
            start.y,
            start.z + dir.y * current_offset,
        );
        mesh.merge(&solid_mesh(seg_start, end, height, thickness, color));
    }

    mesh
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::arch::schema_types::WallLayer;

    fn straight_wall() -> SchemaWall {
        SchemaWall {
            start: Vec3::new(0.0, 0.0, 0.0),
            end: Vec3::new(5000.0, 0.0, 0.0),
            height: 2700.0,
            wall_type: "ext_2x6".to_string(),
            category: "exterior".to_string(),
            ..Default::default()
        }
    }

    fn wall_type_150mm() -> WallType {
        WallType {
            id: "ext_2x6".into(),
            name: "Exterior 2x6".into(),
            layers: vec![WallLayer {
                name: "structure".into(),
                thickness: 150.0,
                ..Default::default()
            }],
        }
    }

    #[test]
    fn category_color_dispatches() {
        assert_eq!(category_color("exterior"), Vec3::new(0.85, 0.85, 0.8));
        assert_eq!(category_color("wet_wall"), Vec3::new(0.7, 0.85, 0.9));
        assert_eq!(category_color("interior"), Vec3::new(0.9, 0.9, 0.88));
    }

    #[test]
    fn solid_wall_has_24_verts_and_12_triangles() {
        // Box: 6 quads * (4 verts + 2 tris) per quad.
        let w = straight_wall();
        let wt = wall_type_150mm();
        let g = generate(&w, &wt, &[], &[]);
        assert_eq!(g.mesh_3d.vertex_count(), 24);
        assert_eq!(g.mesh_3d.triangle_count(), 12);
        assert_eq!(g.mesh_3d.element_type, "wall");
        assert_eq!(g.wall_id, "ext_2x6"); // wall_id stores the wall_type string per C++
        assert!(g.cutouts.is_empty());
    }

    #[test]
    fn degenerate_wall_zero_length_emits_empty_mesh() {
        // Zero-length wall returns an empty mesh (matches C++ early return).
        let w = SchemaWall {
            start: Vec3::ZERO,
            end: Vec3::ZERO,
            height: 2700.0,
            ..Default::default()
        };
        let wt = wall_type_150mm();
        let g = generate_solid(&w, &wt);
        assert_eq!(g.mesh_3d.vertex_count(), 0);
    }

    #[test]
    fn plan_polygon_4_corners_offset_perpendicular() {
        let w = straight_wall();
        let p = generate_plan_polygon(&w, 150.0);
        // Wall is along +X, so perp is (0, 1). Half-thickness = 75.
        // start=(0,0) -> p1=(0,75), p2=(0,-75)
        // end=(5000,0) -> p3=(5000,-75), p4=(5000,75)
        assert_eq!(p.points[0], Point2D::new(0.0, 75.0));
        assert_eq!(p.points[1], Point2D::new(0.0, -75.0));
        assert_eq!(p.points[2], Point2D::new(5000.0, -75.0));
        assert_eq!(p.points[3], Point2D::new(5000.0, 75.0));
        assert_eq!(p.layer, "walls_exterior"); // exterior wall
        assert_eq!(p.fill_color, [0.2, 0.2, 0.2, 1.0]);
    }

    #[test]
    fn plan_polygon_uses_interior_layer_for_interior_wall() {
        let w = SchemaWall {
            category: "interior".to_string(),
            ..straight_wall()
        };
        let p = generate_plan_polygon(&w, 100.0);
        assert_eq!(p.layer, "walls_interior");
        assert_eq!(p.fill_color, [0.4, 0.4, 0.4, 1.0]);
    }

    #[test]
    fn perpendicular_offset_along_y_zero() {
        let w = straight_wall();
        let off = perpendicular_offset(&w, 100.0);
        // Wall along +X, perp = (0,1), offset = 100 -> (0, 0, 100).
        assert_eq!(off.x, 0.0);
        assert_eq!(off.y, 0.0);
        assert_eq!(off.z, 100.0);
    }

    #[test]
    fn cutout_door_produces_two_segments_plus_lintel() {
        // Wall 5m long, door 1m wide centred at 2.5m, 2.1m tall, 2.7m wall.
        // Expect: segment 0..2 (before), lintel 2..3 above door, segment 3..5 (after).
        // That's 3 sub-meshes × 24 verts = 72 verts, 36 triangles.
        let w = straight_wall();
        let wt = wall_type_150mm();
        let door = SchemaDoor {
            offset: 2500.0,
            width: 1000.0,
            height: 2100.0,
            ..Default::default()
        };
        let g = generate(&w, &wt, std::slice::from_ref(&door), &[]);
        assert_eq!(g.cutouts.len(), 1);
        assert_eq!(g.cutouts[0].opening_type, "door");
        assert_eq!(g.cutouts[0].bottom_height, 0.0);
        assert_eq!(g.mesh_3d.vertex_count(), 72);
        assert_eq!(g.mesh_3d.triangle_count(), 36);
    }

    #[test]
    fn cutout_window_adds_sill_segment() {
        // Window has sill_height > 1 → extra "below" sub-mesh.
        // Wall 5m, window 1m wide @ 2.5m, 1.2m tall, sill 900mm.
        // Sub-meshes: before, sill (below), header (above), after = 4 × 24 verts.
        let w = straight_wall();
        let wt = wall_type_150mm();
        let win = SchemaWindow {
            offset: 2500.0,
            width: 1000.0,
            height: 1200.0,
            sill_height: 900.0,
            ..Default::default()
        };
        let g = generate(&w, &wt, &[], std::slice::from_ref(&win));
        assert_eq!(g.cutouts.len(), 1);
        assert_eq!(g.cutouts[0].opening_type, "window");
        assert_eq!(g.cutouts[0].bottom_height, 900.0);
        assert_eq!(g.mesh_3d.vertex_count(), 4 * 24);
        assert_eq!(g.mesh_3d.triangle_count(), 4 * 12);
    }
}
