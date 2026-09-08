//! DXF emission for [`SliceResult`].
//!
//! Uses the `dxf` crate (v0.6, MIT) to write AutoCAD-compatible ASCII DXF.
//! All coordinates are kept in millimetres (the native plan/section space).
//!
//! Supported primitives:
//! - `Line2D`     → `LINE`
//! - `Polyline2D` → `LWPOLYLINE`
//! - `Circle2D`   → `CIRCLE`
//! - `Arc2D`      → `ARC`
//! - `Text2D`     → `TEXT`
//!
//! Hatches and dimensions are skipped for v1 — they add complexity (pattern
//! definitions, dimension styles) and engineers primarily need editable
//! geometry.

use crate::primitives::SliceResult;
use dxf::entities::{Arc, Circle, Entity, EntityType, Line, LwPolyline, Text};
use dxf::{Color, Drawing, LwPolylineVertex, Point, Vector};
use glam::Vec3;

/// Convert a [`SliceResult`] to an in-memory ASCII DXF byte vector.
///
/// # Errors
///
/// Returns an error string if the underlying `dxf` crate fails to serialize
/// (this is rare and usually indicates an unsupported entity configuration).
pub fn export_to_dxf(result: &SliceResult) -> Result<Vec<u8>, String> {
    let mut drawing = Drawing::new();
    // LWPOLYLINE (and several other entity types) are only written when the
    // drawing version is R14 or newer. The default is R12, which silently
    // drops them.
    drawing.header.version = dxf::enums::AcadVersion::R2000;

    // Hatches are skipped — they need `HATCH` entities + pattern tables.
    // Emit their boundaries as closed polylines on a dedicated layer so the
    // geometry isn't lost entirely.
    for hatch in &result.hatches {
        for boundary in &hatch.boundaries {
            if boundary.points.len() < 3 {
                continue;
            }
            let mut poly = LwPolyline::default();
            poly.set_is_closed(true);
            for p in &boundary.points {
                poly.vertices.push(vertex(p.x, p.y));
            }
            let mut ent = Entity::new(EntityType::LwPolyline(poly));
            ent.common.layer = boundary.layer.clone();
            ent.common.color = rgb_to_aci(hatch.color);
            drawing.add_entity(ent);
        }
    }

    for line in &result.lines {
        let mut ent = Entity::new(EntityType::Line(Line::new(
            point(line.start.x, line.start.y),
            point(line.end.x, line.end.y),
        )));
        ent.common.layer = line.layer.clone();
        ent.common.color = rgb_to_aci(line.color);
        ent.common.line_type_name = dxf_line_type(&line.line_type);
        ent.common.line_type_scale = 1.0;
        drawing.add_entity(ent);
    }

    for poly in &result.polylines {
        if poly.points.len() < 2 {
            continue;
        }
        let mut lp = LwPolyline::default();
        lp.set_is_closed(poly.closed);
        for p in &poly.points {
            lp.vertices.push(vertex(p.x, p.y));
        }
        let mut ent = Entity::new(EntityType::LwPolyline(lp));
        ent.common.layer = poly.layer.clone();
        ent.common.color = rgb_to_aci(poly.color);
        ent.common.line_type_name = dxf_line_type(&poly.line_type);
        ent.common.line_type_scale = 1.0;
        drawing.add_entity(ent);
    }

    for circle in &result.circles {
        let mut ent = Entity::new(EntityType::Circle(Circle::new(
            point(circle.center.x, circle.center.y),
            f64::from(circle.radius),
        )));
        ent.common.layer = circle.layer.clone();
        ent.common.color = rgb_to_aci(circle.color);
        drawing.add_entity(ent);
    }

    for arc in &result.arcs {
        let mut ent = Entity::new(EntityType::Arc(Arc::new(
            point(arc.center.x, arc.center.y),
            f64::from(arc.radius),
            f64::from(arc.start_angle.to_degrees()),
            f64::from(arc.end_angle.to_degrees()),
        )));
        ent.common.layer = arc.layer.clone();
        ent.common.color = rgb_to_aci(arc.color);
        drawing.add_entity(ent);
    }

    for text in &result.annotations {
        let mut t = Text::default();
        t.location = point(text.position.x, text.position.y);
        t.value.clone_from(&text.text);
        t.text_height = f64::from(text.height);
        t.rotation = f64::from(text.rotation.to_degrees());
        t.horizontal_text_justification = dxf_h_just(&text.justification);
        // Keep text upright in the XY plane.
        t.normal = Vector::z_axis();
        let mut ent = Entity::new(EntityType::Text(t));
        ent.common.layer = text.layer.clone();
        ent.common.color = rgb_to_aci(text.color);
        drawing.add_entity(ent);
    }

    // Dimensions are skipped for v1 (no dimstyle setup).

    let mut buf = Vec::new();
    drawing
        .save(&mut buf)
        .map_err(|e| format!("DXF serialization failed: {e}"))?;
    Ok(buf)
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

fn point(x: f32, y: f32) -> Point {
    Point::new(f64::from(x), f64::from(y), 0.0)
}

fn vertex(x: f32, y: f32) -> LwPolylineVertex {
    let mut v = LwPolylineVertex::default();
    v.x = f64::from(x);
    v.y = f64::from(y);
    v
}

fn dxf_line_type(lt: &str) -> String {
    match lt {
        "dashed" => "DASHED".to_string(),
        "hidden" => "HIDDEN".to_string(),
        "center" => "CENTER".to_string(),
        _ => "CONTINUOUS".to_string(),
    }
}

fn dxf_h_just(j: &str) -> dxf::enums::HorizontalTextJustification {
    use dxf::enums::HorizontalTextJustification;
    match j {
        "center" => HorizontalTextJustification::Center,
        "right" => HorizontalTextJustification::Right,
        _ => HorizontalTextJustification::Left,
    }
}

/// Map an RGB triplet to the nearest AutoCAD Colour Index (ACI).
///
/// AutoCAD uses 1-255 indexed colours. 7 is the default (white/black).
/// 256 = ByLayer, 0 = ByBlock. We return 7 for near-black/white and
/// nearest primary/secondary for saturated colours.
fn rgb_to_aci(c: Vec3) -> Color {
    let r = (c.x * 255.0) as i32;
    let g = (c.y * 255.0) as i32;
    let b = (c.z * 255.0) as i32;

    // Greyscale path.
    if (r - g).abs() < 20 && (g - b).abs() < 20 {
        let avg = (r + g + b) / 3;
        let idx = match avg {
            0..=32 => 250_u8,
            33..=80 => 251,
            81..=128 => 252,
            129..=176 => 253,
            177..=220 => 254,
            _ => 7,
        };
        return Color::from_index(idx);
    }

    // Nearest primary / secondary.
    let palette = [
        (1, (255, 0, 0)),
        (2, (255, 255, 0)),
        (3, (0, 255, 0)),
        (4, (0, 255, 255)),
        (5, (0, 0, 255)),
        (6, (255, 0, 255)),
    ];
    let mut best = 7_u8;
    let mut best_dist = i32::MAX;
    for (aci, (pr, pg, pb)) in &palette {
        let d = (r - pr).pow(2) + (g - pg).pow(2) + (b - pb).pow(2);
        if d < best_dist {
            best_dist = d;
            best = *aci;
        }
    }
    Color::from_index(best)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::primitives::{Arc2D, Circle2D, Hatch2D, Line2D, Polyline2D, Text2D};
    use glam::Vec2;

    #[test]
    fn empty_slice_emits_valid_dxf() {
        let result = SliceResult::default();
        let bytes = export_to_dxf(&result).expect("serialize");
        let s = String::from_utf8(bytes).expect("utf8");
        assert!(s.contains("SECTION"));
        assert!(s.contains("ENTITIES"));
        assert!(s.contains("ENDSEC"));
        assert!(s.contains("EOF"));
    }

    #[test]
    fn line_emitted_as_dxf_line() {
        let mut result = SliceResult::default();
        result.lines.push(Line2D {
            start: Vec2::new(0.0, 0.0),
            end: Vec2::new(100.0, 200.0),
            layer: "A-WALL".into(),
            line_type: "dashed".into(),
            line_weight: 0.35,
            color: Vec3::new(1.0, 0.0, 0.0),
        });
        let s = String::from_utf8(export_to_dxf(&result).unwrap()).unwrap();
        assert!(s.contains("LINE"));
        assert!(s.contains("A-WALL"));
        assert!(s.contains("DASHED"));
        assert!(s.contains("100.0"));
        assert!(s.contains("200.0"));
    }

    #[test]
    fn closed_polyline_emitted_as_lwpolyline() {
        let mut result = SliceResult::default();
        result.polylines.push(Polyline2D {
            points: vec![Vec2::ZERO, Vec2::new(10.0, 0.0), Vec2::new(10.0, 10.0)],
            closed: true,
            layer: "A-WALL".into(),
            ..Default::default()
        });
        let s = String::from_utf8(export_to_dxf(&result).unwrap()).unwrap();
        assert!(s.contains("LWPOLYLINE"), "LWPOLYLINE not found in:\n{s}");
        // Closed flag = 1 (group code 70). The dxf crate may emit it as
        // "  70\n1" or " 70\n1" depending on padding; search for the
        // sequence "70" followed by "1" on the next non-empty line.
        let has_closed = s.lines().collect::<Vec<_>>().windows(2).any(|w| {
            w[0].trim() == "70" && w[1].trim() == "1"
        });
        assert!(has_closed, "closed flag (70=1) not found in:\n{s}");
    }

    #[test]
    fn circle_emitted() {
        let mut result = SliceResult::default();
        result.circles.push(Circle2D {
            center: Vec2::new(50.0, 50.0),
            radius: 25.0,
            ..Default::default()
        });
        let s = String::from_utf8(export_to_dxf(&result).unwrap()).unwrap();
        assert!(s.contains("CIRCLE"));
        assert!(s.contains("50.0"));
        assert!(s.contains("25.0"));
    }

    #[test]
    fn arc_uses_degrees() {
        let mut result = SliceResult::default();
        result.arcs.push(Arc2D {
            center: Vec2::ZERO,
            radius: 10.0,
            start_angle: 0.0,
            end_angle: std::f32::consts::FRAC_PI_2,
            ..Default::default()
        });
        let s = String::from_utf8(export_to_dxf(&result).unwrap()).unwrap();
        assert!(s.contains("ARC"));
        // 90 degrees
        assert!(s.contains("90.0"));
    }

    #[test]
    fn text_emitted_with_height_and_rotation() {
        let mut result = SliceResult::default();
        result.annotations.push(Text2D {
            position: Vec2::new(10.0, 20.0),
            text: "HELLO".into(),
            height: 3.5,
            rotation: std::f32::consts::PI,
            justification: "center".into(),
            ..Default::default()
        });
        let s = String::from_utf8(export_to_dxf(&result).unwrap()).unwrap();
        assert!(s.contains("TEXT"));
        assert!(s.contains("HELLO"));
        assert!(s.contains("3.5"));
        assert!(s.contains("180.0")); // π radians = 180°
    }

    #[test]
    fn hatch_boundary_emitted_as_closed_polyline() {
        let mut result = SliceResult::default();
        result.hatches.push(Hatch2D {
            boundaries: vec![Polyline2D {
                points: vec![Vec2::ZERO, Vec2::new(10.0, 0.0), Vec2::new(10.0, 10.0)],
                closed: true,
                ..Default::default()
            }],
            ..Default::default()
        });
        let s = String::from_utf8(export_to_dxf(&result).unwrap()).unwrap();
        assert!(s.contains("LWPOLYLINE"));
        let has_closed = s.lines().collect::<Vec<_>>().windows(2).any(|w| {
            w[0].trim() == "70" && w[1].trim() == "1"
        });
        assert!(has_closed, "closed flag (70=1) not found in:\n{s}");
    }

    #[test]
    fn rgb_to_aci_maps_black_to_250_and_red_to_1() {
        assert_eq!(rgb_to_aci(Vec3::ZERO), Color::from_index(250));
        assert_eq!(rgb_to_aci(Vec3::new(1.0, 0.0, 0.0)), Color::from_index(1));
        assert_eq!(rgb_to_aci(Vec3::new(1.0, 1.0, 1.0)), Color::from_index(7));
    }
}
