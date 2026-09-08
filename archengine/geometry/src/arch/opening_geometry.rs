//! Door and window geometry generators.
//!
//! Port of `Shared/ArchGeometry/src/opening_geometry.cpp`.
//!
//! Each opening contributes a frame mesh, a panel/glass mesh, and a 2D
//! plan symbol. The wall's mesh-side cutout is bookkeeping only — actual
//! cutout subtraction happens inside `wall_geometry::mesh_with_cutouts`.

use crate::arch::geometry_types::{
    Arc2D, DoorGeometry, Geometry2D, Line2D, Mesh3D, OpeningCutout, Point2D, WindowGeometry,
};
use crate::arch::schema_types::{SchemaDoor, SchemaWall, SchemaWindow};
use glam::{Vec2, Vec3};

/// `3.14159f` literal used by the C++ for radians→degrees in door swing
/// arc computation (`opening_geometry.cpp:198`). Match exactly so the
/// `atan2 * 180 / PI` byte-equality survives.
#[allow(clippy::approx_constant)] // deliberate — match C++ literal, not full PI
const C_PI_LITERAL: f32 = 3.14159;

// ---------------------------------------------------------------------------
// Door
// ---------------------------------------------------------------------------

/// Door cutout rectangle — same data the wall generator already collects,
/// but exposed as a free function for callers that want it independently.
#[must_use]
pub fn door_cutout(door: &SchemaDoor) -> OpeningCutout {
    OpeningCutout {
        start_offset: door.offset,
        bottom_height: 0.0,
        width: door.width,
        height: door.height,
        opening_type: "door".to_string(),
        opening_index: 0,
    }
}

/// Full door geometry: frame + panel + plan symbol.
#[must_use]
pub fn generate_door(door: &SchemaDoor, wall: &SchemaWall, wall_thickness: f32) -> DoorGeometry {
    let position = opening_position(door.offset, wall);
    let wall_dir = wall.direction();
    let wall_perp = wall_dir.perp();

    let mut frame = generate_door_frame(
        position,
        wall_dir,
        wall_perp,
        door.width,
        door.height,
        wall_thickness,
    );
    frame.element_type = "door_frame".to_string();
    frame.lod_hint = 2;

    let mut panel = generate_door_panel(
        position,
        wall_dir,
        wall_perp,
        door.width,
        door.height,
        &door.swing,
    );
    panel.element_type = "door_panel".to_string();
    panel.lod_hint = 2;

    let plan_symbol = generate_door_symbol(door, wall);

    DoorGeometry {
        mesh_3d: Mesh3D::default(), // C++ doesn't populate the combined mesh
        frame_mesh: frame,
        panel_mesh: panel,
        plan_symbol,
        cutout: door_cutout(door),
        door_id: String::new(),
        door_type: door.door_type.clone(),
        door_index: -1,
    }
}

/// Door frame: two jambs + head. Matches `opening_geometry.cpp:63`.
#[must_use]
pub fn generate_door_frame(
    position: Vec3,
    wall_dir: Vec2,
    wall_perp: Vec2,
    width: f32,
    height: f32,
    _wall_thickness: f32,
) -> Mesh3D {
    let mut mesh = Mesh3D::default();
    let frame_color = Vec3::new(0.45, 0.35, 0.25);
    let frame_width = 50.0;
    let frame_depth = 25.0;
    let half_width = width * 0.5;

    let left_base = Vec3::new(
        position.x - wall_dir.x * half_width,
        position.y,
        position.z - wall_dir.y * half_width,
    );
    push_frame_member(
        &mut mesh,
        left_base,
        frame_width,
        height,
        frame_depth,
        wall_dir,
        wall_perp,
        frame_color,
    );

    let right_base = Vec3::new(
        position.x + wall_dir.x * half_width,
        position.y,
        position.z + wall_dir.y * half_width,
    );
    push_frame_member(
        &mut mesh,
        right_base,
        frame_width,
        height,
        frame_depth,
        wall_dir,
        wall_perp,
        frame_color,
    );

    let head_base = Vec3::new(
        position.x - wall_dir.x * half_width,
        position.y + height - frame_width,
        position.z - wall_dir.y * half_width,
    );
    push_frame_member_horizontal(
        &mut mesh,
        head_base,
        width,
        frame_width,
        frame_depth,
        wall_dir,
        wall_perp,
        frame_color,
    );

    mesh
}

/// Door panel — closed-position rectangular slab. Matches
/// `opening_geometry.cpp:101`.
#[must_use]
pub fn generate_door_panel(
    position: Vec3,
    wall_dir: Vec2,
    wall_perp: Vec2,
    width: f32,
    height: f32,
    _swing: &str,
) -> Mesh3D {
    let mut mesh = Mesh3D::default();
    let panel_color = Vec3::new(0.55, 0.45, 0.35);
    let panel_thickness = 44.0;
    let half_width = width * 0.5;
    let half_thick = panel_thickness * 0.5;

    let panel_base = Vec3::new(
        position.x - wall_dir.x * half_width + wall_perp.x * half_thick,
        position.y,
        position.z - wall_dir.y * half_width + wall_perp.y * half_thick,
    );

    let b0 = panel_base;
    let b1 = Vec3::new(b0.x + wall_dir.x * width, b0.y, b0.z + wall_dir.y * width);
    let b2 = Vec3::new(
        b1.x - wall_perp.x * panel_thickness,
        b1.y,
        b1.z - wall_perp.y * panel_thickness,
    );
    let b3 = Vec3::new(
        b0.x - wall_perp.x * panel_thickness,
        b0.y,
        b0.z - wall_perp.y * panel_thickness,
    );

    let t0 = Vec3::new(b0.x, b0.y + height, b0.z);
    let t1 = Vec3::new(b1.x, b1.y + height, b1.z);
    let t2 = Vec3::new(b2.x, b2.y + height, b2.z);
    let t3 = Vec3::new(b3.x, b3.y + height, b3.z);

    let front_normal = Vec3::new(wall_perp.x, 0.0, wall_perp.y);
    mesh.add_quad(b0, t0, t1, b1, front_normal, panel_color);

    let back_normal = Vec3::new(-wall_perp.x, 0.0, -wall_perp.y);
    mesh.add_quad(b2, t2, t3, b3, back_normal, panel_color);

    mesh.add_quad(
        b0,
        b3,
        t3,
        t0,
        Vec3::new(-wall_dir.x, 0.0, -wall_dir.y),
        panel_color,
    );
    mesh.add_quad(
        b1,
        t1,
        t2,
        b2,
        Vec3::new(wall_dir.x, 0.0, wall_dir.y),
        panel_color,
    );
    mesh.add_quad(t0, t3, t2, t1, Vec3::new(0.0, 1.0, 0.0), panel_color);

    mesh
}

/// 2D door swing arc in plan view. Matches `opening_geometry.cpp:147`.
#[must_use]
pub fn generate_door_symbol(door: &SchemaDoor, wall: &SchemaWall) -> Geometry2D {
    let mut symbol = Geometry2D {
        element_type: "door_symbol".to_string(),
        ..Default::default()
    };

    let wall_dir = wall.direction();
    let _wall_perp = wall_dir.perp();
    let half_width = door.width * 0.5;
    let offset = door.offset;

    let door_center = Point2D::new(
        wall.start.x + wall_dir.x * offset,
        wall.start.z + wall_dir.y * offset,
    );

    let opening = Line2D {
        layer: "doors".to_string(),
        line_type: "continuous".to_string(),
        line_weight: 0.25,
        start: Point2D::new(
            door_center.x - wall_dir.x * half_width,
            door_center.y - wall_dir.y * half_width,
        ),
        end: Point2D::new(
            door_center.x + wall_dir.x * half_width,
            door_center.y + wall_dir.y * half_width,
        ),
    };
    symbol.lines.push(opening.clone());

    let mut swing = Arc2D {
        layer: "doors".to_string(),
        radius: door.width,
        ..Default::default()
    };

    let hinge_left = door.swing.contains("left");
    let swing_in = door.swing.contains("in");

    if hinge_left {
        swing.center = opening.start;
        swing.start_angle = if swing_in { 0.0 } else { 180.0 };
        swing.end_angle = if swing_in { 90.0 } else { 270.0 };
    } else {
        swing.center = opening.end;
        swing.start_angle = if swing_in { 90.0 } else { 270.0 };
        swing.end_angle = if swing_in { 180.0 } else { 360.0 };
    }

    // Match C++ exactly: uses literal 3.14159f, NOT std::f32::consts::PI.
    let wall_angle = wall_dir.y.atan2(wall_dir.x) * 180.0 / C_PI_LITERAL;
    swing.start_angle += wall_angle;
    swing.end_angle += wall_angle;

    symbol.arcs.push(swing);

    // Panel-closed line (duplicate of `opening`).
    symbol.lines.push(Line2D {
        layer: "doors".to_string(),
        line_type: "continuous".to_string(),
        line_weight: 0.25,
        start: opening.start,
        end: opening.end,
    });

    symbol
}

// ---------------------------------------------------------------------------
// Window
// ---------------------------------------------------------------------------

#[must_use]
pub fn window_cutout(window: &SchemaWindow) -> OpeningCutout {
    OpeningCutout {
        start_offset: window.offset,
        bottom_height: window.sill_height,
        width: window.width,
        height: window.height,
        opening_type: "window".to_string(),
        opening_index: 0,
    }
}

#[must_use]
pub fn generate_window(
    window: &SchemaWindow,
    wall: &SchemaWall,
    wall_thickness: f32,
) -> WindowGeometry {
    let mut position = opening_position(window.offset, wall);
    position.y += window.sill_height;

    let wall_dir = wall.direction();
    let wall_perp = wall_dir.perp();

    let mut frame = generate_window_frame(
        position,
        wall_dir,
        wall_perp,
        window.width,
        window.height,
        wall_thickness,
    );
    frame.element_type = "window_frame".to_string();
    frame.lod_hint = 2;

    let mut glass =
        generate_window_glass(position, wall_dir, wall_perp, window.width, window.height);
    glass.element_type = "window_glass".to_string();
    glass.lod_hint = 3;

    let plan_symbol = generate_window_symbol(window, wall);

    WindowGeometry {
        mesh_3d: Mesh3D::default(), // C++ doesn't populate the combined mesh
        frame_mesh: frame,
        glass_mesh: glass,
        plan_symbol,
        cutout: window_cutout(window),
        window_id: String::new(),
        window_type: window.window_type.clone(),
        window_index: -1,
    }
}

/// Window frame: 2 jambs + sill + head. Matches `opening_geometry.cpp:267`.
#[must_use]
pub fn generate_window_frame(
    position: Vec3,
    wall_dir: Vec2,
    wall_perp: Vec2,
    width: f32,
    height: f32,
    _wall_thickness: f32,
) -> Mesh3D {
    let mut mesh = Mesh3D::default();
    let frame_color = Vec3::new(0.9, 0.9, 0.92);
    let frame_width = 60.0;
    let frame_depth = 80.0;
    let half_width = width * 0.5;

    let left_base = Vec3::new(
        position.x - wall_dir.x * half_width,
        position.y,
        position.z - wall_dir.y * half_width,
    );
    push_frame_member(
        &mut mesh,
        left_base,
        frame_width,
        height,
        frame_depth,
        wall_dir,
        wall_perp,
        frame_color,
    );

    let right_base = Vec3::new(
        position.x + wall_dir.x * half_width,
        position.y,
        position.z + wall_dir.y * half_width,
    );
    push_frame_member(
        &mut mesh,
        right_base,
        frame_width,
        height,
        frame_depth,
        wall_dir,
        wall_perp,
        frame_color,
    );

    let sill_base = Vec3::new(
        position.x - wall_dir.x * half_width,
        position.y,
        position.z - wall_dir.y * half_width,
    );
    push_frame_member_horizontal(
        &mut mesh,
        sill_base,
        width,
        frame_width,
        frame_depth,
        wall_dir,
        wall_perp,
        frame_color,
    );

    let head_base = Vec3::new(
        position.x - wall_dir.x * half_width,
        position.y + height - frame_width,
        position.z - wall_dir.y * half_width,
    );
    push_frame_member_horizontal(
        &mut mesh,
        head_base,
        width,
        frame_width,
        frame_depth,
        wall_dir,
        wall_perp,
        frame_color,
    );

    mesh
}

/// Window glass pane — one quad with both winding orders for see-through.
/// Matches `opening_geometry.cpp:313`.
#[must_use]
pub fn generate_window_glass(
    position: Vec3,
    wall_dir: Vec2,
    wall_perp: Vec2,
    width: f32,
    height: f32,
) -> Mesh3D {
    let mut mesh = Mesh3D::default();
    let glass_color = Vec3::new(0.7, 0.85, 0.95);
    let glass_inset = 60.0_f32;
    let half_width = (width - 2.0 * glass_inset) * 0.5;
    let glass_height = height - 2.0 * glass_inset;

    let glass_base = Vec3::new(
        position.x - wall_dir.x * half_width,
        position.y + glass_inset,
        position.z - wall_dir.y * half_width,
    );

    let g0 = glass_base;
    let g1 = Vec3::new(
        g0.x + wall_dir.x * (width - 2.0 * glass_inset),
        g0.y,
        g0.z + wall_dir.y * (width - 2.0 * glass_inset),
    );
    let g2 = Vec3::new(g1.x, g1.y + glass_height, g1.z);
    let g3 = Vec3::new(g0.x, g0.y + glass_height, g0.z);

    let front_normal = Vec3::new(wall_perp.x, 0.0, wall_perp.y);
    let back_normal = Vec3::new(-wall_perp.x, 0.0, -wall_perp.y);

    mesh.add_quad(g0, g1, g2, g3, front_normal, glass_color);
    mesh.add_quad(g1, g0, g3, g2, back_normal, glass_color);

    mesh
}

/// Window plan symbol: 3 parallel lines (two outer wall edges + glass centre).
/// Matches `opening_geometry.cpp:345`.
#[must_use]
pub fn generate_window_symbol(window: &SchemaWindow, wall: &SchemaWall) -> Geometry2D {
    let mut symbol = Geometry2D {
        element_type: "window_symbol".to_string(),
        ..Default::default()
    };

    let wall_dir = wall.direction();
    let wall_perp = wall_dir.perp();
    let half_width = window.width * 0.5;

    let center = Point2D::new(
        wall.start.x + wall_dir.x * window.offset,
        wall.start.z + wall_dir.y * window.offset,
    );

    let wall_half_thick = 75.0_f32;

    let line1 = Line2D {
        layer: "windows".to_string(),
        line_type: "continuous".to_string(),
        line_weight: 0.25,
        start: Point2D::new(
            center.x - wall_dir.x * half_width + wall_perp.x * wall_half_thick,
            center.y - wall_dir.y * half_width + wall_perp.y * wall_half_thick,
        ),
        end: Point2D::new(
            center.x + wall_dir.x * half_width + wall_perp.x * wall_half_thick,
            center.y + wall_dir.y * half_width + wall_perp.y * wall_half_thick,
        ),
    };
    symbol.lines.push(line1);

    let line2 = Line2D {
        layer: "windows".to_string(),
        line_type: "continuous".to_string(),
        line_weight: 0.25,
        start: Point2D::new(
            center.x - wall_dir.x * half_width,
            center.y - wall_dir.y * half_width,
        ),
        end: Point2D::new(
            center.x + wall_dir.x * half_width,
            center.y + wall_dir.y * half_width,
        ),
    };
    symbol.lines.push(line2);

    let line3 = Line2D {
        layer: "windows".to_string(),
        line_type: "continuous".to_string(),
        line_weight: 0.25,
        start: Point2D::new(
            center.x - wall_dir.x * half_width - wall_perp.x * wall_half_thick,
            center.y - wall_dir.y * half_width - wall_perp.y * wall_half_thick,
        ),
        end: Point2D::new(
            center.x + wall_dir.x * half_width - wall_perp.x * wall_half_thick,
            center.y + wall_dir.y * half_width - wall_perp.y * wall_half_thick,
        ),
    };
    symbol.lines.push(line3);

    symbol
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

#[must_use]
pub fn opening_position(offset: f32, wall: &SchemaWall) -> Vec3 {
    let dir = wall.direction();
    Vec3::new(
        wall.start.x + dir.x * offset,
        wall.start.y,
        wall.start.z + dir.y * offset,
    )
}

/// Vertical frame member (jamb). 6 faces. Matches
/// `opening_geometry.cpp:420`.
#[allow(clippy::too_many_arguments)]
fn push_frame_member(
    mesh: &mut Mesh3D,
    base: Vec3,
    width: f32,
    height: f32,
    depth: f32,
    wall_dir: Vec2,
    wall_perp: Vec2,
    color: Vec3,
) {
    let half_depth = depth * 0.5;

    let b0 = Vec3::new(
        base.x - wall_perp.x * half_depth,
        base.y,
        base.z - wall_perp.y * half_depth,
    );
    let b1 = Vec3::new(
        base.x + wall_perp.x * half_depth,
        base.y,
        base.z + wall_perp.y * half_depth,
    );
    let b2 = Vec3::new(b1.x + wall_dir.x * width, b1.y, b1.z + wall_dir.y * width);
    let b3 = Vec3::new(b0.x + wall_dir.x * width, b0.y, b0.z + wall_dir.y * width);

    let t0 = Vec3::new(b0.x, b0.y + height, b0.z);
    let t1 = Vec3::new(b1.x, b1.y + height, b1.z);
    let t2 = Vec3::new(b2.x, b2.y + height, b2.z);
    let t3 = Vec3::new(b3.x, b3.y + height, b3.z);

    mesh.add_quad(
        b0,
        t0,
        t1,
        b1,
        Vec3::new(-wall_perp.x, 0.0, -wall_perp.y),
        color,
    );
    mesh.add_quad(
        b1,
        t1,
        t2,
        b2,
        Vec3::new(wall_dir.x, 0.0, wall_dir.y),
        color,
    );
    mesh.add_quad(
        b2,
        t2,
        t3,
        b3,
        Vec3::new(wall_perp.x, 0.0, wall_perp.y),
        color,
    );
    mesh.add_quad(
        b3,
        t3,
        t0,
        b0,
        Vec3::new(-wall_dir.x, 0.0, -wall_dir.y),
        color,
    );
    mesh.add_quad(t0, t3, t2, t1, Vec3::new(0.0, 1.0, 0.0), color);
    mesh.add_quad(b0, b1, b2, b3, Vec3::new(0.0, -1.0, 0.0), color);
}

/// Horizontal frame member (sill or head). 6 faces, slightly different
/// face winding/normals than the vertical jamb. Matches
/// `opening_geometry.cpp:449`.
#[allow(clippy::too_many_arguments)]
fn push_frame_member_horizontal(
    mesh: &mut Mesh3D,
    base: Vec3,
    width: f32,
    height: f32,
    depth: f32,
    wall_dir: Vec2,
    wall_perp: Vec2,
    color: Vec3,
) {
    let half_depth = depth * 0.5;

    let b0 = Vec3::new(
        base.x - wall_perp.x * half_depth,
        base.y,
        base.z - wall_perp.y * half_depth,
    );
    let b1 = Vec3::new(
        base.x + wall_perp.x * half_depth,
        base.y,
        base.z + wall_perp.y * half_depth,
    );
    let b2 = Vec3::new(b1.x + wall_dir.x * width, b1.y, b1.z + wall_dir.y * width);
    let b3 = Vec3::new(b0.x + wall_dir.x * width, b0.y, b0.z + wall_dir.y * width);

    let t0 = Vec3::new(b0.x, b0.y + height, b0.z);
    let t1 = Vec3::new(b1.x, b1.y + height, b1.z);
    let t2 = Vec3::new(b2.x, b2.y + height, b2.z);
    let t3 = Vec3::new(b3.x, b3.y + height, b3.z);

    mesh.add_quad(
        b0,
        t0,
        t1,
        b1,
        Vec3::new(-wall_dir.x, 0.0, -wall_dir.y),
        color,
    );
    mesh.add_quad(
        b2,
        t2,
        t3,
        b3,
        Vec3::new(wall_dir.x, 0.0, wall_dir.y),
        color,
    );
    mesh.add_quad(
        b0,
        b3,
        t3,
        t0,
        Vec3::new(-wall_perp.x, 0.0, -wall_perp.y),
        color,
    );
    mesh.add_quad(
        b1,
        t1,
        t2,
        b2,
        Vec3::new(wall_perp.x, 0.0, wall_perp.y),
        color,
    );
    mesh.add_quad(t0, t3, t2, t1, Vec3::new(0.0, 1.0, 0.0), color);
    mesh.add_quad(b0, b1, b2, b3, Vec3::new(0.0, -1.0, 0.0), color);
}

#[cfg(test)]
mod tests {
    use super::*;

    fn x_axis_wall() -> SchemaWall {
        SchemaWall {
            start: Vec3::new(0.0, 0.0, 0.0),
            end: Vec3::new(5000.0, 0.0, 0.0),
            height: 2700.0,
            ..Default::default()
        }
    }

    #[test]
    fn door_frame_two_jambs_plus_head_means_3_frame_members() {
        // 3 frame members × 6 quads × (4 verts + 2 tris) = 72 verts, 36 tris.
        let frame = generate_door_frame(
            Vec3::new(2500.0, 0.0, 0.0),
            Vec2::new(1.0, 0.0),
            Vec2::new(0.0, 1.0),
            900.0,
            2100.0,
            150.0,
        );
        assert_eq!(frame.vertex_count(), 72);
        assert_eq!(frame.triangle_count(), 36);
    }

    #[test]
    fn door_panel_has_5_quads() {
        // 5 quads = 20 verts, 10 tris (skips one side — the back is reachable through the opening).
        let panel = generate_door_panel(
            Vec3::new(2500.0, 0.0, 0.0),
            Vec2::new(1.0, 0.0),
            Vec2::new(0.0, 1.0),
            900.0,
            2100.0,
            "left_in",
        );
        assert_eq!(panel.vertex_count(), 20);
        assert_eq!(panel.triangle_count(), 10);
    }

    #[test]
    fn window_frame_4_members_means_24_quads() {
        // 4 frame members × 6 quads × (4 verts + 2 tris) = 96 verts, 48 tris.
        let frame = generate_window_frame(
            Vec3::new(2500.0, 900.0, 0.0),
            Vec2::new(1.0, 0.0),
            Vec2::new(0.0, 1.0),
            1200.0,
            1200.0,
            150.0,
        );
        assert_eq!(frame.vertex_count(), 96);
        assert_eq!(frame.triangle_count(), 48);
    }

    #[test]
    fn window_glass_has_2_quads_both_winding_orders() {
        // 2 quads = 8 verts, 4 tris.
        let glass = generate_window_glass(
            Vec3::new(2500.0, 900.0, 0.0),
            Vec2::new(1.0, 0.0),
            Vec2::new(0.0, 1.0),
            1200.0,
            1200.0,
        );
        assert_eq!(glass.vertex_count(), 8);
        assert_eq!(glass.triangle_count(), 4);
    }

    #[test]
    fn door_symbol_has_2_lines_and_1_arc() {
        let door = SchemaDoor {
            offset: 2500.0,
            width: 900.0,
            height: 2100.0,
            swing: "left_in".to_string(),
            ..Default::default()
        };
        let sym = generate_door_symbol(&door, &x_axis_wall());
        assert_eq!(sym.lines.len(), 2);
        assert_eq!(sym.arcs.len(), 1);
        // Hinge-left + swing-in starts at angle 0, ends at 90 (+ wall_angle = 0 for X axis).
        let arc = &sym.arcs[0];
        assert!((arc.start_angle - 0.0).abs() < 0.01);
        assert!((arc.end_angle - 90.0).abs() < 0.01);
    }

    #[test]
    fn window_symbol_has_3_parallel_lines() {
        let win = SchemaWindow {
            offset: 2500.0,
            width: 1200.0,
            height: 1200.0,
            sill_height: 900.0,
            ..Default::default()
        };
        let sym = generate_window_symbol(&win, &x_axis_wall());
        assert_eq!(sym.lines.len(), 3);
        // For an X-axis wall, all three lines should have the same X extent.
        for line in &sym.lines {
            assert!((line.end.x - line.start.x - 1200.0).abs() < 1e-3);
        }
    }

    #[test]
    fn opening_position_offsets_along_wall_direction() {
        let w = x_axis_wall();
        let p = opening_position(2500.0, &w);
        assert_eq!(p, Vec3::new(2500.0, 0.0, 0.0));
    }

    #[test]
    fn cutout_helpers_round_trip_through_door_and_window() {
        let d = SchemaDoor {
            offset: 500.0,
            width: 900.0,
            height: 2100.0,
            ..Default::default()
        };
        let c = door_cutout(&d);
        assert_eq!(c.opening_type, "door");
        assert_eq!(c.bottom_height, 0.0);

        let w = SchemaWindow {
            offset: 1000.0,
            width: 1200.0,
            height: 1500.0,
            sill_height: 900.0,
            ..Default::default()
        };
        let c2 = window_cutout(&w);
        assert_eq!(c2.opening_type, "window");
        assert_eq!(c2.bottom_height, 900.0);
    }
}
