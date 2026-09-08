//! SVG emission for `SliceResult`.
//!
//! Ported from `slicer_2d.cpp:487-666`. Output format:
//! - Y is flipped (multiplied by -1) since SVG Y grows downward.
//! - Bounding box computed from lines + polyline points only (circles,
//!   arcs, text ignored — matches the C++ behaviour at `:603-619`).
//! - 10 mm margin around the bounding box.
//! - White background rect, then hatches, lines, polylines, circles,
//!   arcs, text in that order (matches `:632-663`).
//!
//! Float formatting matches the C++ default `std::ostream<<` precision
//! (6 significant digits) via [`cpp_double`]. Diff-clean against the
//! C++ output for typical building.json inputs.

use crate::primitives::{Arc2D, Circle2D, Hatch2D, Line2D, Polyline2D, SliceResult, Text2D};
use glam::Vec3;
use std::fmt::Write;

/// Mirrors C++ default `std::ostream` formatting for floats:
/// `%g` with precision 6 (significant digits). Strips trailing zeros
/// and never emits a trailing `.`.
///
/// Examples:
/// - `10363.2` → `"10363.2"`
/// - `838.2`   → `"838.2"`
/// - `0.25`    → `"0.25"`
/// - `1.0`     → `"1"`
/// - `0.0`     → `"0"`
/// - `-0.0`    → `"-0"` (preserves sign of zero, matches C++)
#[must_use]
#[allow(
    clippy::cast_precision_loss,
    clippy::cast_possible_truncation,
    clippy::cast_sign_loss
)]
pub fn cpp_double(x: f32) -> String {
    // Promote to f64 to match C++ where stream operators convert through
    // double regardless of input type.
    let x = f64::from(x);

    // Preserve sign of zero — MSVC's `cout << -0.0` emits "-0"
    // (confirmed by the M4 diff oracle).
    if x == 0.0 {
        return if x.is_sign_negative() {
            "-0".to_string()
        } else {
            "0".to_string()
        };
    }

    // Decide fixed vs scientific the same way %g does: scientific if the
    // exponent is < -4 or >= precision (6).
    let exp = x.abs().log10().floor() as i32;
    let precision_g = 6_i32;
    let use_scientific = exp < -4 || exp >= precision_g;

    if use_scientific {
        let s = format!("{x:.*e}", (precision_g - 1) as usize);
        strip_scientific_trailing_zeros(&s)
    } else {
        let after_decimal = (precision_g - exp - 1).max(0) as usize;
        let s = format!("{x:.after_decimal$}");
        strip_trailing_zeros(&s)
    }
}

fn strip_trailing_zeros(s: &str) -> String {
    if !s.contains('.') {
        return s.to_string();
    }
    let trimmed = s.trim_end_matches('0').trim_end_matches('.');
    trimmed.to_string()
}

fn strip_scientific_trailing_zeros(s: &str) -> String {
    // Split into mantissa and exponent on 'e'.
    let Some(e_idx) = s.find('e') else {
        return s.to_string();
    };
    let (mantissa, exponent) = s.split_at(e_idx);
    let mantissa_clean = strip_trailing_zeros(mantissa);
    format!("{mantissa_clean}{exponent}")
}

/// `rgb(r,g,b)` with integer-truncation conversion (matches
/// `static_cast<int>(color.r * 255)` at `slicer_2d.cpp:487`).
#[must_use]
#[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)]
pub fn color_to_svg(color: Vec3) -> String {
    let r = (color.x * 255.0) as i32;
    let g = (color.y * 255.0) as i32;
    let b = (color.z * 255.0) as i32;
    format!("rgb({r},{g},{b})")
}

/// Emit one `<line>` element. Mirrors `Slicer2D::svgLine`.
#[must_use]
pub fn svg_line(line: &Line2D, scale: f32) -> String {
    let mut out = String::new();
    let _ = write!(
        out,
        r#"<line x1="{}" y1="{}" x2="{}" y2="{}" stroke="{}" stroke-width="{}"#,
        cpp_double(line.start.x * scale),
        cpp_double(-line.start.y * scale),
        cpp_double(line.end.x * scale),
        cpp_double(-line.end.y * scale),
        color_to_svg(line.color),
        cpp_double(line.line_weight * scale),
    );
    match line.line_type.as_str() {
        "dashed" => {
            let _ = write!(
                out,
                r#"" stroke-dasharray="{},{}"#,
                cpp_double(4.0 * scale),
                cpp_double(2.0 * scale),
            );
        }
        "hidden" => {
            let _ = write!(
                out,
                r#"" stroke-dasharray="{},{}"#,
                cpp_double(2.0 * scale),
                cpp_double(2.0 * scale),
            );
        }
        _ => {}
    }
    let _ = writeln!(out, "\"/>");
    out
}

/// Emit one polyline / polygon. Mirrors `Slicer2D::svgPolyline`.
#[must_use]
pub fn svg_polyline(poly: &Polyline2D, scale: f32) -> String {
    if poly.points.len() < 2 {
        return String::new();
    }
    let tag = if poly.closed { "polygon" } else { "polyline" };
    let mut out = String::new();
    let _ = write!(out, r#"<{tag} points=""#);
    for p in &poly.points {
        let _ = write!(
            out,
            "{},{} ",
            cpp_double(p.x * scale),
            cpp_double(-p.y * scale)
        );
    }
    let _ = write!(
        out,
        r#"" fill="none" stroke="{}" stroke-width="{}"#,
        color_to_svg(poly.color),
        cpp_double(poly.line_weight * scale),
    );
    match poly.line_type.as_str() {
        "dashed" => {
            let _ = write!(
                out,
                r#"" stroke-dasharray="{},{}"#,
                cpp_double(4.0 * scale),
                cpp_double(2.0 * scale),
            );
        }
        "hidden" => {
            let _ = write!(
                out,
                r#"" stroke-dasharray="{},{}"#,
                cpp_double(2.0 * scale),
                cpp_double(2.0 * scale),
            );
        }
        _ => {}
    }
    out.push_str("\"/>\n");
    out
}

/// Emit one `<circle>`. Mirrors `Slicer2D::svgCircle`.
#[must_use]
pub fn svg_circle(circle: &Circle2D, scale: f32) -> String {
    format!(
        "<circle cx=\"{}\" cy=\"{}\" r=\"{}\" fill=\"none\" stroke=\"{}\" stroke-width=\"{}\"/>\n",
        cpp_double(circle.center.x * scale),
        cpp_double(-circle.center.y * scale),
        cpp_double(circle.radius * scale),
        color_to_svg(circle.color),
        cpp_double(circle.line_weight * scale),
    )
}

/// Emit one arc as an SVG `<path>`. Mirrors `Slicer2D::svgArc`.
#[must_use]
pub fn svg_arc(arc: &Arc2D, scale: f32) -> String {
    let start_x = arc.center.x + arc.radius * arc.start_angle.cos();
    let start_y = arc.center.y + arc.radius * arc.start_angle.sin();
    let end_x = arc.center.x + arc.radius * arc.end_angle.cos();
    let end_y = arc.center.y + arc.radius * arc.end_angle.sin();

    let mut angle_diff = arc.end_angle - arc.start_angle;
    while angle_diff < 0.0 {
        angle_diff += std::f32::consts::TAU;
    }
    let large_arc_flag = i32::from(angle_diff > std::f32::consts::PI);
    // The exporter negates Y (`-start_y`/`-end_y`), mirroring the arc, which
    // reverses the visual sweep. Compensate so the angle range `start→end`
    // (CCW in model space) renders correctly — door swings bulge away from the
    // hinge instead of caving toward it.
    let sweep_flag = 0;

    format!(
        "<path d=\"M {} {} A {} {} 0 {} {} {} {}\" fill=\"none\" stroke=\"{}\" stroke-width=\"{}\"/>\n",
        cpp_double(start_x * scale),
        cpp_double(-start_y * scale),
        cpp_double(arc.radius * scale),
        cpp_double(arc.radius * scale),
        large_arc_flag,
        sweep_flag,
        cpp_double(end_x * scale),
        cpp_double(-end_y * scale),
        color_to_svg(arc.color),
        cpp_double(arc.line_weight * scale),
    )
}

/// Emit one `<text>`. Mirrors `Slicer2D::svgText`.
#[must_use]
pub fn svg_text(text: &Text2D, scale: f32) -> String {
    let mut out = String::new();
    let _ = write!(
        out,
        r#"<text x="{}" y="{}" font-size="{}" fill="{}""#,
        cpp_double(text.position.x * scale),
        cpp_double(-text.position.y * scale),
        cpp_double(text.height * scale),
        color_to_svg(text.color),
    );
    match text.justification.as_str() {
        "center" => out.push_str(r#" text-anchor="middle""#),
        "right" => out.push_str(r#" text-anchor="end""#),
        _ => {}
    }
    if text.rotation != 0.0 {
        let _ = write!(
            out,
            r#" transform="rotate({} {} {})""#,
            cpp_double(text.rotation.to_degrees()),
            cpp_double(text.position.x * scale),
            cpp_double(-text.position.y * scale),
        );
    }
    let _ = writeln!(out, ">{}</text>", xml_escape(&text.text));
    out
}

/// Minimal XML-text escaping — required so callouts containing `&`, `<`,
/// or `>` survive `svg2pdf::usvg::Tree::from_str`. We only escape what's
/// strictly disallowed inside a text node.
pub(crate) fn xml_escape(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for ch in s.chars() {
        match ch {
            '&' => out.push_str("&amp;"),
            '<' => out.push_str("&lt;"),
            '>' => out.push_str("&gt;"),
            _ => out.push(ch),
        }
    }
    out
}

/// Emit hatches as semi-transparent filled polygons (`fill-opacity=0.3`).
/// Pattern names are ignored — the C++ does the same simplification at
/// `slicer_2d.cpp:582`.
#[must_use]
pub fn svg_hatch(hatch: &Hatch2D, scale: f32) -> String {
    if hatch.boundaries.is_empty() {
        return String::new();
    }
    let mut out = String::new();
    for boundary in &hatch.boundaries {
        if boundary.points.len() < 3 {
            continue;
        }
        let _ = write!(out, r#"<polygon points=""#);
        for p in &boundary.points {
            let _ = write!(
                out,
                "{},{} ",
                cpp_double(p.x * scale),
                cpp_double(-p.y * scale)
            );
        }
        let _ = write!(
            out,
            r#"" fill="{}" fill-opacity="0.3" stroke="none"/>"#,
            color_to_svg(hatch.color),
        );
        out.push('\n');
    }
    out
}

/// Top-level SVG export. Mirrors `Slicer2D::exportToSVG`
/// (`slicer_2d.cpp:602`).
#[must_use]
pub fn export_to_svg(result: &SliceResult, scale: f32) -> String {
    export_to_svg_padded(result, scale, 0.0)
}

/// As [`export_to_svg`], but reserves `pad_world` extra units (in pre-scale
/// world space) around the geometry bounding box. Use this when annotations
/// (dimension lines, labels) sit *outside* the geometry footprint and would
/// otherwise be clipped by the tight viewBox.
#[must_use]
#[allow(clippy::cast_precision_loss)]
pub fn export_to_svg_padded(result: &SliceResult, scale: f32, pad_world: f32) -> String {
    // Bounding box from lines + polyline points (matches C++ scope).
    let mut min_x = 1e9_f32;
    let mut min_y = 1e9_f32;
    let mut max_x = -1e9_f32;
    let mut max_y = -1e9_f32;
    for line in &result.lines {
        min_x = min_x.min(line.start.x).min(line.end.x);
        min_y = min_y.min(line.start.y).min(line.end.y);
        max_x = max_x.max(line.start.x).max(line.end.x);
        max_y = max_y.max(line.start.y).max(line.end.y);
    }
    for poly in &result.polylines {
        for p in &poly.points {
            min_x = min_x.min(p.x);
            min_y = min_y.min(p.y);
            max_x = max_x.max(p.x);
            max_y = max_y.max(p.y);
        }
    }
    // Reserve room for out-of-footprint annotations (only when non-degenerate).
    if pad_world > 0.0 && max_x >= min_x && max_y >= min_y {
        min_x -= pad_world;
        min_y -= pad_world;
        max_x += pad_world;
        max_y += pad_world;
    }

    let margin = 10.0_f32;
    let width = (max_x - min_x) * scale + 2.0 * margin;
    let height = (max_y - min_y) * scale + 2.0 * margin;

    let mut svg = String::new();
    svg.push_str("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n");
    let _ = writeln!(
        svg,
        "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"{}\" height=\"{}\" viewBox=\"{} {} {} {}\">",
        cpp_double(width),
        cpp_double(height),
        cpp_double(min_x * scale - margin),
        cpp_double(-max_y * scale - margin),
        cpp_double(width),
        cpp_double(height),
    );
    svg.push_str("<rect width=\"100%\" height=\"100%\" fill=\"white\"/>\n");

    // Hatches first (background).
    for hatch in &result.hatches {
        svg.push_str(&svg_hatch(hatch, scale));
    }
    for line in &result.lines {
        svg.push_str(&svg_line(line, scale));
    }
    for poly in &result.polylines {
        svg.push_str(&svg_polyline(poly, scale));
    }
    for circle in &result.circles {
        svg.push_str(&svg_circle(circle, scale));
    }
    for arc in &result.arcs {
        svg.push_str(&svg_arc(arc, scale));
    }
    for text in &result.annotations {
        svg.push_str(&svg_text(text, scale));
    }
    svg.push_str("</svg>\n");
    svg
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::primitives::{Hatch2D, Line2D, Polyline2D};
    use glam::Vec2;

    #[test]
    fn cpp_double_matches_default_ostream_for_common_values() {
        assert_eq!(cpp_double(0.0), "0");
        assert_eq!(cpp_double(-0.0), "-0"); // MSVC preserves sign of zero
        assert_eq!(cpp_double(1.0), "1");
        assert_eq!(cpp_double(0.25), "0.25");
        assert_eq!(cpp_double(10363.2), "10363.2");
        assert_eq!(cpp_double(838.2), "838.2");
        assert_eq!(cpp_double(-150.5), "-150.5");
    }

    #[test]
    fn cpp_double_uses_six_significant_digits() {
        // 10 million has 8 sig figs as a literal but is exactly representable.
        // %g precision 6 keeps 6 and switches to scientific notation
        // (exponent >= precision).
        let s = cpp_double(10_000_000.0);
        assert!(s.contains('e'), "got {s}");
    }

    #[test]
    fn cpp_double_strips_trailing_zeros() {
        // 0.1 → exact %g(6) → "0.1"
        assert_eq!(cpp_double(0.1), "0.1");
        // 1.5 → "1.5"
        assert_eq!(cpp_double(1.5), "1.5");
    }

    #[test]
    fn color_truncates_not_rounds() {
        // 0.5 * 255 = 127.5 → 127 (truncated, NOT 128 rounded).
        assert_eq!(color_to_svg(Vec3::splat(0.5)), "rgb(127,127,127)");
        // 1.0 * 255 = 255 exactly.
        assert_eq!(color_to_svg(Vec3::ONE), "rgb(255,255,255)");
        assert_eq!(color_to_svg(Vec3::ZERO), "rgb(0,0,0)");
    }

    #[test]
    fn svg_line_basic() {
        let line = Line2D {
            start: Vec2::ZERO,
            end: Vec2::new(100.0, 200.0),
            color: Vec3::ZERO,
            line_weight: 0.35,
            line_type: "continuous".into(),
            ..Default::default()
        };
        let s = svg_line(&line, 1.0);
        // Y is flipped (negated) — and -0.0 prints as "-0" (MSVC compat).
        assert!(s.contains(r#"x1="0" y1="-0""#));
        assert!(s.contains(r#"x2="100" y2="-200""#));
        assert!(s.contains(r#"stroke="rgb(0,0,0)""#));
        assert!(s.contains(r#"stroke-width="0.35""#));
        assert!(!s.contains("stroke-dasharray"));
    }

    #[test]
    fn svg_line_dashed_includes_dasharray() {
        let line = Line2D {
            start: Vec2::ZERO,
            end: Vec2::new(100.0, 0.0),
            line_type: "dashed".into(),
            ..Default::default()
        };
        let s = svg_line(&line, 1.0);
        // dash pattern: 4,2.
        assert!(s.contains(r#"stroke-dasharray="4,2""#));
    }

    #[test]
    fn svg_polyline_emits_polygon_when_closed() {
        let poly = Polyline2D {
            points: vec![Vec2::ZERO, Vec2::new(10.0, 0.0), Vec2::new(10.0, 10.0)],
            closed: true,
            ..Default::default()
        };
        let s = svg_polyline(&poly, 1.0);
        assert!(s.starts_with("<polygon"));
        assert!(s.contains(r#"fill="none""#));
    }

    #[test]
    fn svg_polyline_emits_polyline_when_open() {
        let poly = Polyline2D {
            points: vec![Vec2::ZERO, Vec2::X],
            closed: false,
            ..Default::default()
        };
        let s = svg_polyline(&poly, 1.0);
        assert!(s.starts_with("<polyline"));
    }

    #[test]
    fn svg_polyline_dashed_includes_dasharray() {
        let poly = Polyline2D {
            points: vec![Vec2::ZERO, Vec2::new(10.0, 0.0), Vec2::new(10.0, 10.0)],
            closed: true,
            line_type: "dashed".into(),
            ..Default::default()
        };
        let s = svg_polyline(&poly, 1.0);
        assert!(s.starts_with("<polygon"));
        assert!(s.contains(r#"stroke-dasharray="4,2""#), "got {s}");
        assert!(s.trim_end().ends_with("/>"), "got {s}");
    }

    #[test]
    fn svg_polyline_continuous_has_no_dasharray() {
        let poly = Polyline2D {
            points: vec![Vec2::ZERO, Vec2::new(10.0, 0.0)],
            closed: false,
            ..Default::default()
        };
        let s = svg_polyline(&poly, 1.0);
        assert!(!s.contains("stroke-dasharray"));
    }

    #[test]
    fn svg_polyline_skips_when_fewer_than_two_points() {
        let poly = Polyline2D {
            points: vec![Vec2::ZERO],
            ..Default::default()
        };
        assert_eq!(svg_polyline(&poly, 1.0), "");
    }

    #[test]
    fn svg_hatch_emits_semi_transparent_polygon() {
        let hatch = Hatch2D {
            boundaries: vec![Polyline2D {
                points: vec![Vec2::ZERO, Vec2::new(10.0, 0.0), Vec2::new(10.0, 10.0)],
                closed: true,
                ..Default::default()
            }],
            color: Vec3::new(0.5, 0.5, 0.5),
            ..Default::default()
        };
        let s = svg_hatch(&hatch, 1.0);
        assert!(s.contains(r#"fill-opacity="0.3""#));
        assert!(s.contains(r#"fill="rgb(127,127,127)""#));
    }

    #[test]
    fn export_to_svg_includes_header_and_white_background() {
        let result = SliceResult {
            lines: vec![Line2D {
                start: Vec2::ZERO,
                end: Vec2::new(100.0, 100.0),
                ..Default::default()
            }],
            ..Default::default()
        };
        let svg = export_to_svg(&result, 1.0);
        assert!(svg.starts_with("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"));
        assert!(svg.contains("<svg xmlns=\"http://www.w3.org/2000/svg\""));
        assert!(svg.contains(r#"<rect width="100%" height="100%" fill="white"/>"#));
        assert!(svg.ends_with("</svg>\n"));
    }

    #[test]
    fn export_to_svg_orders_primitives_correctly() {
        // Hatches before lines before polylines before … (matches C++).
        let result = SliceResult {
            hatches: vec![Hatch2D {
                boundaries: vec![Polyline2D {
                    points: vec![Vec2::ZERO, Vec2::new(10.0, 0.0), Vec2::new(10.0, 10.0)],
                    closed: true,
                    ..Default::default()
                }],
                color: Vec3::splat(0.5),
                ..Default::default()
            }],
            lines: vec![Line2D::default()],
            polylines: vec![Polyline2D {
                points: vec![Vec2::ZERO, Vec2::X],
                ..Default::default()
            }],
            ..Default::default()
        };
        let svg = export_to_svg(&result, 1.0);
        let hatch_pos = svg.find("<polygon").unwrap();
        let line_pos = svg.find("<line").unwrap();
        let poly_pos = svg.find("<polyline").unwrap();
        assert!(hatch_pos < line_pos);
        assert!(line_pos < poly_pos);
    }
}
