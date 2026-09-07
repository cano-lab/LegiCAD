//! Section-cut markers for the floor plan (Phase 2.5).
//!
//! Renders the conventional architectural section symbol: a chained dashed
//! line spanning the building at the cut location, with a labelled bubble
//! at each end carrying the section name (`A`, `B`, …) and the sheet
//! number where the section drawing lives (`A-301`). A small triangle
//! beside each bubble points in the view direction.
//!
//! The output is a self-contained `<g>` fragment in plan-mm coordinates
//! — callers inject it into the floor-plan SVG with the same lift
//! transform as the other annotation overlays.

use std::fmt::Write as _;

use crate::section_sheet::{CutDirection, SectionCut, ViewDirection};

/// Outer ring radius of the section-marker bubble, in plan-mm.
const BUBBLE_RADIUS_MM: f32 = 400.0;
/// How far past the building edge the cut line extends so the bubbles
/// don't overlap the wall outline.
const BUBBLE_OFFSET_MM: f32 = 800.0;
/// Length of the small triangular arrow that indicates view direction.
const ARROW_LEN_MM: f32 = 350.0;

/// Generate an SVG `<g>` fragment for one section cut on the floor plan.
///
/// `building_width_mm` / `building_depth_mm` are the floor-plan extent —
/// they place the end bubbles just outside the building outline. The
/// sheet number (e.g. `"A-301"`) is shown on each bubble's lower row so
/// readers know which sheet carries the section drawing.
#[must_use]
pub fn generate_section_marker(
    cut: &SectionCut,
    building_width_mm: f32,
    building_depth_mm: f32,
    sheet_number: &str,
) -> String {
    let mut s = String::with_capacity(1024);
    s.push_str("<!-- Section Cut Marker -->\n");
    s.push_str("<g id=\"section-marker\">\n");

    // The label is the first character of the section name (`A-A` → `A`).
    let mark_label = cut.name.chars().next().unwrap_or('A');

    // End points of the cut line, in plan-mm.
    let ((x1, y1), (x2, y2)) = endpoints(cut, building_width_mm, building_depth_mm);

    // The cut line itself — a long dash pattern reads as a section cut.
    let _ = writeln!(
        s,
        r##"  <line x1="{x1:.0}" y1="{y1:.0}" x2="{x2:.0}" y2="{y2:.0}" stroke="#000" stroke-width="6" stroke-dasharray="200,80,40,80"/>"##,
    );

    // Bubbles + arrows at each end.
    push_bubble(&mut s, x1, y1, mark_label, sheet_number);
    push_bubble(&mut s, x2, y2, mark_label, sheet_number);
    push_arrow(&mut s, x1, y1, cut.view_direction, cut.direction);
    push_arrow(&mut s, x2, y2, cut.view_direction, cut.direction);

    s.push_str("</g>\n");
    s
}

/// Compute the endpoints of the cut line in plan-mm. For a transverse cut
/// the line runs along Y (top-to-bottom of plan); a longitudinal cut runs
/// along X.
///
/// Y values are *pre-negated* to match the annotation-overlay convention
/// used by [`crate::room_labels`] and foundation/framing plans: callers
/// inject the fragment into a `<g transform="scale(N)">` group that does
/// not flip Y, so the fragment itself has to compensate for the geometry
/// exporter's Y-negate.
fn endpoints(
    cut: &SectionCut,
    width_mm: f32,
    depth_mm: f32,
) -> ((f32, f32), (f32, f32)) {
    match cut.direction {
        CutDirection::Transverse => (
            (cut.cut_x, BUBBLE_OFFSET_MM),
            (cut.cut_x, -(depth_mm + BUBBLE_OFFSET_MM)),
        ),
        CutDirection::Longitudinal => (
            (-BUBBLE_OFFSET_MM, -cut.cut_z),
            (width_mm + BUBBLE_OFFSET_MM, -cut.cut_z),
        ),
    }
}

fn push_bubble(s: &mut String, cx: f32, cy: f32, label: char, sheet: &str) {
    // Outer circle.
    let _ = writeln!(
        s,
        r##"  <circle cx="{cx:.0}" cy="{cy:.0}" r="{r}" fill="white" stroke="#000" stroke-width="6"/>"##,
        r = BUBBLE_RADIUS_MM,
    );
    // Horizontal divider through the centre — top half = section letter,
    // bottom half = sheet number.
    let _ = writeln!(
        s,
        r##"  <line x1="{x1:.0}" y1="{cy:.0}" x2="{x2:.0}" y2="{cy:.0}" stroke="#000" stroke-width="4"/>"##,
        x1 = cx - BUBBLE_RADIUS_MM,
        x2 = cx + BUBBLE_RADIUS_MM,
    );
    // Section letter (top half).
    let _ = writeln!(
        s,
        r#"  <text x="{cx:.0}" y="{ty:.0}" font-family="Arial" font-size="280" font-weight="bold" text-anchor="middle">{label}</text>"#,
        ty = cy - 60.0,
    );
    // Sheet number (bottom half).
    let _ = writeln!(
        s,
        r#"  <text x="{cx:.0}" y="{ty:.0}" font-family="Arial" font-size="160" text-anchor="middle">{sheet}</text>"#,
        ty = cy + 240.0,
    );
}

/// Draw a small filled triangle next to the bubble pointing in the
/// section view direction.
fn push_arrow(s: &mut String, cx: f32, cy: f32, view: ViewDirection, cut: CutDirection) {
    // The arrow head sits a bit outside the bubble, perpendicular to the
    // cut direction so it doesn't sit on the cut line. The view direction
    // tells us which side of the cut line is "into the section".
    let (dx, dy) = arrow_offset(view, cut);
    let tip_x = cx + dx;
    let tip_y = cy + dy;
    let base_x = cx + dx * 0.3;
    let base_y = cy + dy * 0.3;
    // Two base points perpendicular to (dx, dy), each ARROW_LEN/2 either side.
    let (perp_x, perp_y) = (-dy, dx);
    let half = ARROW_LEN_MM * 0.25;
    let len = (perp_x * perp_x + perp_y * perp_y).sqrt().max(1e-3);
    let (ux, uy) = (perp_x / len, perp_y / len);
    let _ = writeln!(
        s,
        r##"  <polygon points="{tx:.0},{ty:.0} {b1x:.0},{b1y:.0} {b2x:.0},{b2y:.0}" fill="#000"/>"##,
        tx = tip_x,
        ty = tip_y,
        b1x = base_x + ux * half,
        b1y = base_y + uy * half,
        b2x = base_x - ux * half,
        b2y = base_y - uy * half,
    );
}

/// Vector from the bubble centre to the arrow tip in *pre-negated* Y
/// space — same convention as [`endpoints`]. North on the plan is +Y
/// here; south is -Y.
fn arrow_offset(view: ViewDirection, cut: CutDirection) -> (f32, f32) {
    // For a transverse cut (vertical line on the plan), the arrow points
    // east or west. For a longitudinal cut (horizontal line), north/south.
    let off = BUBBLE_RADIUS_MM + ARROW_LEN_MM * 1.2;
    match (cut, view) {
        (CutDirection::Transverse, ViewDirection::East) => (off, 0.0),
        (CutDirection::Transverse, ViewDirection::West) => (-off, 0.0),
        // Transverse but the view doesn't match the cut axis → fall back to East.
        (CutDirection::Transverse, _) => (off, 0.0),
        // Y is pre-negated: south on the plan = -Y, north = +Y.
        (CutDirection::Longitudinal, ViewDirection::South) => (0.0, -off),
        (CutDirection::Longitudinal, ViewDirection::North) => (0.0, off),
        (CutDirection::Longitudinal, _) => (0.0, -off),
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    fn transverse_cut(name: &str, x: f32) -> SectionCut {
        SectionCut {
            name: name.into(),
            cut_x: x,
            cut_z: 0.0,
            direction: CutDirection::Transverse,
            view_direction: ViewDirection::East,
        }
    }

    #[test]
    fn transverse_marker_spans_full_building_depth_plus_offsets() {
        let cut = transverse_cut("A-A", 2500.0);
        let svg = generate_section_marker(&cut, 5000.0, 4000.0, "A-301");
        // Y is pre-negated: top end at +offset, bottom end at -(depth+offset).
        assert!(svg.contains(r#"y1="800""#));
        assert!(svg.contains(r#"y2="-4800""#));
        // Cut at x = 2500.
        assert!(svg.contains(r#"x1="2500""#));
        assert!(svg.contains(r#"x2="2500""#));
    }

    #[test]
    fn marker_emits_two_bubbles_with_letter_and_sheet_number() {
        let cut = transverse_cut("A-A", 2500.0);
        let svg = generate_section_marker(&cut, 5000.0, 4000.0, "A-301");
        // Two circles, two letter "A" texts, two "A-301" sheet refs.
        assert_eq!(svg.matches("<circle ").count(), 2);
        assert!(svg.matches(">A</text>").count() >= 2, "{svg}");
        assert!(svg.matches(">A-301</text>").count() >= 2);
    }

    #[test]
    fn marker_emits_two_view_arrows() {
        let cut = transverse_cut("A-A", 2500.0);
        let svg = generate_section_marker(&cut, 5000.0, 4000.0, "A-301");
        assert_eq!(svg.matches("<polygon ").count(), 2);
    }

    #[test]
    fn longitudinal_cut_runs_horizontally() {
        let cut = SectionCut {
            name: "B-B".into(),
            cut_x: 0.0,
            cut_z: 2000.0,
            direction: CutDirection::Longitudinal,
            view_direction: ViewDirection::South,
        };
        let svg = generate_section_marker(&cut, 5000.0, 4000.0, "A-302");
        // Long cut: x spans (with offsets), y constant at the pre-negated
        // cut_z value (-2000).
        assert!(svg.contains(r#"x1="-800""#));
        assert!(svg.contains(r#"x2="5800""#));
        assert!(svg.contains(r#"y1="-2000""#));
        assert!(svg.contains(r#"y2="-2000""#));
        assert!(svg.matches(">B</text>").count() >= 2);
    }

    #[test]
    fn marker_is_well_formed_g_fragment() {
        let cut = transverse_cut("A-A", 2500.0);
        let svg = generate_section_marker(&cut, 5000.0, 4000.0, "A-301");
        assert!(svg.contains(r#"<g id="section-marker">"#));
        assert!(svg.trim_end().ends_with("</g>"));
    }
}
