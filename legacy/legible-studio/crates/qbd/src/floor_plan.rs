//! Floor-plan generation with door + window primitives layered on top of
//! the base slicer output.
//!
//! Ported from `QBDInterface::generateFloorPlan` (`qbd_interface.cpp:973`).

use crate::convert::layout_to_building;
use archgeometry::{SchemaDocument, SchemaDoor, SchemaWall, SchemaWindow};
use domain::Building;
use drawing::{
    Arc2D, Config, Hatch2D, Line2D, Point2D, Polyline2D, SliceResult, generate_floor_plan,
};
use glam::{Vec2, Vec3};

/// Wall thickness assumed for door/window-on-wall geometry when the
/// schema doesn't pin one. Matches `qbd_interface.cpp:994` (exterior)
/// and `:995` (interior).
fn wall_thickness_for(category: &str) -> f32 {
    if category == "interior" { 115.0 } else { 175.0 }
}

/// Mid-grey for existing (as-built) openings on the design overlay, matching
/// the as-built wall colour in `drawing::slice`.
const EXISTING_GREY: Vec3 = Vec3::new(0.5, 0.5, 0.5);

/// Generate the full floor-plan SliceResult, including doors and windows.
#[must_use]
pub fn generate_floor_plan_with_openings(
    doc: &SchemaDocument,
    cut_height: f32,
    config: &Config,
) -> SliceResult {
    let building = layout_to_building(doc);
    let mut result = generate_floor_plan(&building, cut_height, config);

    for door in &doc.doors {
        add_door_primitives(&mut result, door, &doc.walls);
    }
    for window in &doc.windows {
        add_window_primitives(&mut result, window, &doc.walls);
    }

    result
}

/// Same as above but reuses a pre-converted `Building` (saves a conversion
/// when the caller already has it).
pub fn add_openings_to_floor_plan(
    result: &mut SliceResult,
    doc: &SchemaDocument,
    _building: &Building,
) {
    for door in &doc.doors {
        add_door_primitives(result, door, &doc.walls);
    }
    for window in &doc.windows {
        add_window_primitives(result, window, &doc.walls);
    }
}

fn add_door_primitives(result: &mut SliceResult, door: &SchemaDoor, walls: &[SchemaWall]) {
    let Ok(wall_idx) = usize::try_from(door.wall_index) else {
        return;
    };
    let Some(wall) = walls.get(wall_idx) else {
        return;
    };

    let wall_start_2d = Vec2::new(wall.start.x, wall.start.z);
    let wall_end_2d = Vec2::new(wall.end.x, wall.end.z);
    let wall_dir = (wall_end_2d - wall_start_2d).normalize_or_zero();
    let wall_normal = Vec2::new(-wall_dir.y, wall_dir.x);

    let door_center = wall_start_2d + wall_dir * door.offset;
    let half_width = door.width * 0.5;
    let wall_thick = wall_thickness_for(&wall.category);
    let half_thick = wall_thick * 0.5;

    // Existing (as-built) openings render as grey, dashed reference linework to
    // match the as-built walls; new doors stay solid black.
    let existing = door.is_existing();
    let leaf_color = if existing { EXISTING_GREY } else { Vec3::ZERO };
    let leaf_line_type = if existing { "dashed" } else { "continuous" };

    // White rectangle that "cuts" the wall outline.
    let p1 = door_center - wall_dir * half_width - wall_normal * half_thick;
    let p2 = door_center + wall_dir * half_width - wall_normal * half_thick;
    let p3 = door_center + wall_dir * half_width + wall_normal * half_thick;
    let p4 = door_center - wall_dir * half_width + wall_normal * half_thick;

    let door_opening = Polyline2D {
        points: vec![p1, p2, p3, p4],
        closed: true,
        layer: "A-DOOR".into(),
        line_type: "continuous".into(),
        line_weight: 0.0,
        color: Vec3::ONE, // white
    };
    result.hatches.push(Hatch2D {
        boundaries: vec![door_opening],
        pattern: "SOLID".into(),
        scale: 1.0,
        angle: 0.0,
        layer: "A-DOOR".into(),
        color: Vec3::ONE,
    });

    // Pocket / sliding doors: dashed line through the wall, no leaf or arc.
    if door.door_type == "pocket"
        || door.door_type == "pocket_door"
        || door.door_type == "sliding"
        || door.door_type == "sliding_door"
    {
        result.lines.push(Line2D {
            start: door_center - wall_dir * half_width,
            end: door_center + wall_dir * half_width,
            layer: "A-DOOR".into(),
            line_type: "dashed".into(),
            line_weight: 15.0,
            color: leaf_color,
        });
        return;
    }

    // Swing door: leaf line + 90° arc from the hinge.
    let swing_left = door.swing == "left_in" || door.swing == "left_out" || door.swing == "left";
    let swing_in = door.swing == "left_in" || door.swing == "right_in";

    let (hinge_pos, swing_dir) = if swing_left {
        (door_center - wall_dir * half_width, wall_dir)
    } else {
        (door_center + wall_dir * half_width, -wall_dir)
    };
    let swing_normal = if swing_in { wall_normal } else { -wall_normal };

    result.lines.push(Line2D {
        start: hinge_pos,
        end: hinge_pos + swing_normal * door.width,
        layer: "A-DOOR".into(),
        line_type: leaf_line_type.into(),
        line_weight: 20.0,
        color: leaf_color,
    });
    result.arcs.push(Arc2D {
        center: hinge_pos,
        radius: door.width,
        start_angle: swing_dir.y.atan2(swing_dir.x),
        end_angle: swing_normal.y.atan2(swing_normal.x),
        layer: "A-DOOR".into(),
        line_weight: 15.0,
        color: leaf_color,
    });
}

fn add_window_primitives(result: &mut SliceResult, window: &SchemaWindow, walls: &[SchemaWall]) {
    let Ok(wall_idx) = usize::try_from(window.wall_index) else {
        return;
    };
    let Some(wall) = walls.get(wall_idx) else {
        return;
    };

    let wall_start_2d = Vec2::new(wall.start.x, wall.start.z);
    let wall_end_2d = Vec2::new(wall.end.x, wall.end.z);
    let wall_dir = (wall_end_2d - wall_start_2d).normalize_or_zero();
    let wall_normal = Vec2::new(-wall_dir.y, wall_dir.x);

    let win_center = wall_start_2d + wall_dir * window.offset;
    let half_width = window.width * 0.5;
    // The C++ uses a fixed 175mm exterior thickness × 0.3 = 52.5mm line offset.
    let line_offset = wall_thickness_for("exterior") * 0.3;

    // Existing windows render grey + dashed like the as-built walls.
    let existing = window.is_existing();
    let glaz_color = if existing { EXISTING_GREY } else { Vec3::ZERO };
    let glaz_line_type = if existing { "dashed" } else { "continuous" };

    let push_line = |result: &mut SliceResult, start: Point2D, end: Point2D| {
        result.lines.push(Line2D {
            start,
            end,
            layer: "A-GLAZ".into(),
            line_type: glaz_line_type.into(),
            line_weight: 20.0,
            color: glaz_color,
        });
    };

    // Outer line (offset +normal).
    push_line(
        result,
        win_center - wall_dir * half_width + wall_normal * line_offset,
        win_center + wall_dir * half_width + wall_normal * line_offset,
    );
    // Inner line (offset -normal).
    push_line(
        result,
        win_center - wall_dir * half_width - wall_normal * line_offset,
        win_center + wall_dir * half_width - wall_normal * line_offset,
    );
    // Left + right caps.
    push_line(
        result,
        win_center - wall_dir * half_width + wall_normal * line_offset,
        win_center - wall_dir * half_width - wall_normal * line_offset,
    );
    push_line(
        result,
        win_center + wall_dir * half_width + wall_normal * line_offset,
        win_center + wall_dir * half_width - wall_normal * line_offset,
    );
}

#[cfg(test)]
mod tests {
    use super::*;
    use archgeometry::{SchemaDoor, SchemaWall, SchemaWindow};

    fn x_wall() -> SchemaWall {
        SchemaWall {
            start: Vec3::ZERO,
            end: Vec3::new(5000.0, 0.0, 0.0),
            height: 2700.0,
            category: "exterior".into(),
            ..Default::default()
        }
    }

    #[test]
    fn door_with_swing_emits_leaf_line_and_arc() {
        let mut r = SliceResult::default();
        let walls = vec![x_wall()];
        add_door_primitives(
            &mut r,
            &SchemaDoor {
                wall_index: 0,
                offset: 2500.0,
                width: 900.0,
                height: 2100.0,
                door_type: "swing".into(),
                swing: "left_in".into(),
                ..Default::default()
            },
            &walls,
        );
        // 1 hatch (the white wall cut), 1 leaf line, 1 arc.
        assert_eq!(r.hatches.len(), 1);
        assert_eq!(r.lines.len(), 1);
        assert_eq!(r.arcs.len(), 1);
    }

    #[test]
    fn existing_door_renders_grey_dashed_leaf_and_arc() {
        let mut r = SliceResult::default();
        let walls = vec![x_wall()];
        add_door_primitives(
            &mut r,
            &SchemaDoor {
                wall_index: 0,
                offset: 2500.0,
                width: 900.0,
                height: 2100.0,
                door_type: "swing".into(),
                swing: "left_in".into(),
                existing: true,
                ..Default::default()
            },
            &walls,
        );
        assert_eq!(r.lines.len(), 1);
        assert_eq!(r.lines[0].line_type, "dashed", "existing door leaf dashed");
        assert_eq!(r.lines[0].color, EXISTING_GREY);
        assert_eq!(r.arcs.len(), 1);
        assert_eq!(r.arcs[0].color, EXISTING_GREY);
    }

    #[test]
    fn existing_window_renders_grey_dashed_lines() {
        let mut r = SliceResult::default();
        let walls = vec![x_wall()];
        add_window_primitives(
            &mut r,
            &SchemaWindow {
                wall_index: 0,
                offset: 2500.0,
                width: 1200.0,
                height: 1200.0,
                sill_height: 900.0,
                existing: true,
                ..Default::default()
            },
            &walls,
        );
        assert_eq!(r.lines.len(), 4);
        for line in &r.lines {
            assert_eq!(line.line_type, "dashed");
            assert_eq!(line.color, EXISTING_GREY);
        }
    }

    #[test]
    fn pocket_door_emits_dashed_line_no_arc() {
        let mut r = SliceResult::default();
        let walls = vec![x_wall()];
        add_door_primitives(
            &mut r,
            &SchemaDoor {
                wall_index: 0,
                offset: 2500.0,
                width: 900.0,
                height: 2100.0,
                door_type: "pocket".into(),
                swing: "left".into(),
                ..Default::default()
            },
            &walls,
        );
        assert_eq!(r.hatches.len(), 1, "still gets the white cut");
        assert_eq!(r.arcs.len(), 0, "no swing arc for pocket");
        assert_eq!(r.lines.len(), 1);
        assert_eq!(r.lines[0].line_type, "dashed");
    }

    #[test]
    fn window_emits_two_parallel_lines_plus_two_caps() {
        let mut r = SliceResult::default();
        let walls = vec![x_wall()];
        add_window_primitives(
            &mut r,
            &SchemaWindow {
                wall_index: 0,
                offset: 2500.0,
                width: 1200.0,
                height: 1200.0,
                sill_height: 900.0,
                ..Default::default()
            },
            &walls,
        );
        // outer + inner + left cap + right cap = 4 lines.
        assert_eq!(r.lines.len(), 4);
        for line in &r.lines {
            assert_eq!(line.layer, "A-GLAZ");
        }
    }

    #[test]
    fn door_with_invalid_wall_index_is_no_op() {
        let mut r = SliceResult::default();
        let walls = vec![x_wall()];
        add_door_primitives(
            &mut r,
            &SchemaDoor {
                wall_index: 99,
                offset: 1500.0,
                ..Default::default()
            },
            &walls,
        );
        assert!(r.hatches.is_empty());
        assert!(r.lines.is_empty());
        assert!(r.arcs.is_empty());
    }

    #[test]
    fn as_built_overlay_renders_existing_walls_dashed_grey() {
        // A new-design wall plus an existing (as-built) wall on the same plan.
        let doc = SchemaDocument {
            walls: vec![
                x_wall(), // category "exterior" → new design
                SchemaWall {
                    start: Vec3::new(0.0, 0.0, 3000.0),
                    end: Vec3::new(5000.0, 0.0, 3000.0),
                    height: 2700.0,
                    category: "as_built".into(),
                    ..Default::default()
                },
            ],
            ..Default::default()
        };

        let r = generate_floor_plan_with_openings(&doc, 1500.0, &Config::with_defaults());
        // Two wall outlines; only the new-design wall is hatched.
        assert_eq!(r.polylines.len(), 2);
        assert_eq!(r.hatches.len(), 1, "as-built wall must not be hatched");

        let dashed: Vec<_> = r.polylines.iter().filter(|p| p.line_type == "dashed").collect();
        assert_eq!(dashed.len(), 1, "exactly one as-built (dashed) wall");
        assert_eq!(dashed[0].layer, "A-WALL-EXST");
        // Grey, not black.
        assert!(dashed[0].color.x > 0.4 && dashed[0].color.x < 0.6);
    }

    #[test]
    fn generate_floor_plan_with_openings_combines_walls_doors_windows() {
        let doc = SchemaDocument {
            walls: vec![x_wall()],
            doors: vec![SchemaDoor {
                wall_index: 0,
                offset: 2500.0,
                width: 900.0,
                height: 2100.0,
                door_type: "swing".into(),
                swing: "left_in".into(),
                ..Default::default()
            }],
            windows: vec![SchemaWindow {
                wall_index: 0,
                offset: 4000.0,
                width: 800.0,
                height: 1200.0,
                sill_height: 900.0,
                ..Default::default()
            }],
            ..Default::default()
        };

        let r = generate_floor_plan_with_openings(&doc, 1500.0, &Config::with_defaults());
        // 1 wall outline + 1 wall hatch + 1 door white-fill hatch = 2 hatches.
        assert_eq!(r.hatches.len(), 2);
        // 1 door leaf + 4 window lines = 5.
        assert_eq!(r.lines.len(), 5);
        assert_eq!(r.arcs.len(), 1);
    }
}
