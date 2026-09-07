//! Roof geometry + roof-plan drawing for a rectangular footprint.
//!
//! Computes a gable or hip roof analytically from the footprint `width`×`depth`
//! and a pitch (rise/run): the ridge segment, hip lines (hip only), and ridge
//! height. The straight skeleton for non-rectangular (L/T/U) footprints is a
//! later step; this covers the common rectangular house. Truss *design* stays
//! manual/engineer — this is geometry only.

use std::fmt::Write as _;

/// Gable (ridge runs the long axis, eave-to-eave) or hip (ridge inset, four
/// hips to the corners).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RoofType {
    Gable,
    Hip,
}

/// A roof over a footprint (mm). The rectangular path uses `width`/`depth`;
/// the irregular path uses `footprint_polygon_mm` (CCW, axis-aligned) and
/// drives the straight-skeleton solver. When the polygon has fewer than four
/// vertices the rectangular path is used.
#[derive(Debug, Clone)]
pub struct RoofPlan {
    pub width: f32,
    pub depth: f32,
    pub roof_type: RoofType,
    /// Pitch as rise/run (e.g. 0.5 = 6:12).
    pub pitch: f32,
    /// Eave overhang beyond the footprint (mm).
    pub overhang: f32,
    /// Irregular footprint as CCW `(x, z)` mm vertices. Empty → rectangular.
    pub footprint_polygon_mm: Vec<(f32, f32)>,
}

impl RoofPlan {
    /// Ridge endpoints `((x1,z1),(x2,z2))` in plan mm. Runs along the longer
    /// axis, centred. Gable ridges span the full length; hip ridges inset by
    /// half the short span (a square hip ridge is a point).
    #[must_use]
    pub fn ridge(&self) -> ((f32, f32), (f32, f32)) {
        let (w, d) = (self.width, self.depth);
        let short = w.min(d);
        let inset = if self.roof_type == RoofType::Hip { short * 0.5 } else { 0.0 };
        if w >= d {
            ((inset, d * 0.5), (w - inset, d * 0.5))
        } else {
            ((w * 0.5, inset), (w * 0.5, d - inset))
        }
    }

    /// Ridge height above the wall plate (mm) = half the short span × pitch.
    #[must_use]
    pub fn ridge_height(&self) -> f32 {
        self.width.min(self.depth) * 0.5 * self.pitch
    }

    /// Hip lines (corner → nearest ridge endpoint), in plan mm. Empty for a
    /// gable.
    #[must_use]
    pub fn hips(&self) -> Vec<((f32, f32), (f32, f32))> {
        if self.roof_type != RoofType::Hip {
            return Vec::new();
        }
        let (w, d) = (self.width, self.depth);
        let (r1, r2) = self.ridge();
        let corners = [(0.0, 0.0), (w, 0.0), (w, d), (0.0, d)];
        corners
            .iter()
            .map(|&c| {
                // connect to whichever ridge endpoint is nearer
                let d1 = (c.0 - r1.0).powi(2) + (c.1 - r1.1).powi(2);
                let d2 = (c.0 - r2.0).powi(2) + (c.1 - r2.1).powi(2);
                (c, if d1 <= d2 { r1 } else { r2 })
            })
            .collect()
    }
}

/// Render a roof-plan SVG: eave outline (dashed, with overhang), footprint,
/// ridge, hips, and a pitch note.
///
/// When the roof carries an irregular `footprint_polygon_mm` (≥4 vertices),
/// dispatches to the straight-skeleton renderer for rectilinear (L/T/U)
/// roofs. Otherwise uses the rectangular gable/hip path.
#[must_use]
#[allow(clippy::too_many_lines, clippy::many_single_char_names, clippy::uninlined_format_args)]
pub fn generate_roof_plan_svg(roof: &RoofPlan) -> String {
    if roof.footprint_polygon_mm.len() >= 4 {
        return polygon_roof_plan_svg(roof);
    }
    let scale = 0.08; // mm → px (≈1:300)
    let margin = 60.0;
    let oh = roof.overhang;
    let plan_w = (roof.width + 2.0 * oh) * scale;
    let plan_h = (roof.depth + 2.0 * oh) * scale;
    let w = plan_w + 2.0 * margin;
    let h = plan_h + 2.0 * margin;

    // Plan (x, z) mm → SVG px, z flipped (north up).
    let px = |x: f32| margin + (x + oh) * scale;
    let py = |z: f32| h - margin - (z + oh) * scale;

    let mut s = String::with_capacity(2048);
    let _ = writeln!(s, r#"<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">"#);
    let _ = writeln!(s, r#"<rect width="{w}" height="{h}" fill="white"/>"#);

    // Eave outline (footprint + overhang), dashed.
    let _ = writeln!(
        s,
        r##"<rect x="{x}" y="{y}" width="{ew}" height="{eh}" fill="#f7f5ee" stroke="#888" stroke-width="1" stroke-dasharray="6,4"/>"##,
        x = px(-oh),
        y = py(roof.depth + oh),
        ew = (roof.width + 2.0 * oh) * scale,
        eh = (roof.depth + 2.0 * oh) * scale,
    );
    // Footprint (wall line).
    let _ = writeln!(
        s,
        r##"<rect x="{x}" y="{y}" width="{fw}" height="{fh}" fill="none" stroke="#333" stroke-width="1.5"/>"##,
        x = px(0.0),
        y = py(roof.depth),
        fw = roof.width * scale,
        fh = roof.depth * scale,
    );

    let line = |s: &mut String, a: (f32, f32), b: (f32, f32), wdt: f32| {
        let _ = writeln!(
            s,
            r##"<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#000" stroke-width="{wdt}"/>"##,
            x1 = px(a.0), y1 = py(a.1), x2 = px(b.0), y2 = py(b.1),
        );
    };
    // Hips (corner → ridge), then the ridge on top.
    for (a, b) in roof.hips() {
        line(&mut s, a, b, 1.5);
    }
    let (r1, r2) = roof.ridge();
    line(&mut s, r1, r2, 2.5);

    // Labels: title + pitch + type.
    let lbl = r##"font-family="Helvetica, Arial, sans-serif" font-size="12" fill="#333""##;
    let pitch_12 = (roof.pitch * 12.0).round();
    let kind = if roof.roof_type == RoofType::Hip { "HIP" } else { "GABLE" };
    let _ = writeln!(s, r#"<text x="{x}" y="22" {lbl} font-weight="bold">ROOF PLAN — {kind}</text>"#, x = margin);
    let _ = writeln!(
        s,
        r#"<text x="{x}" y="{y}" {lbl}>Pitch {p:.0}:12 · overhang {o:.0} mm</text>"#,
        x = margin, y = h - 20.0, p = pitch_12, o = oh,
    );

    s.push_str("</svg>\n");
    s
}

/// Render a roof-plan SVG for an irregular rectilinear footprint, driven by
/// the straight-skeleton solver. Draws the eave outline, the footprint,
/// then the skeleton arcs classified into hips / valleys / ridges (the
/// skeleton renderer chooses the line style per kind).
#[must_use]
#[allow(clippy::many_single_char_names, clippy::cast_precision_loss)]
fn polygon_roof_plan_svg(roof: &RoofPlan) -> String {
    use crate::skeleton::{rectilinear_straight_skeleton, skeleton_to_svg_fragment};

    let poly = &roof.footprint_polygon_mm;
    let (min_x, max_x) = poly.iter().fold((f32::MAX, f32::MIN), |(a, b), p| (a.min(p.0), b.max(p.0)));
    let (min_z, max_z) = poly.iter().fold((f32::MAX, f32::MIN), |(a, b), p| (a.min(p.1), b.max(p.1)));
    let scale = 0.08;
    let margin = 60.0;
    let oh = roof.overhang;
    let plan_w = (max_x - min_x + 2.0 * oh) * scale;
    let plan_h = (max_z - min_z + 2.0 * oh) * scale;
    let w = plan_w + 2.0 * margin;
    let h = plan_h + 2.0 * margin;

    let px = |x: f32| margin + (x - min_x + oh) * scale;
    let py = |z: f32| h - margin - (z - min_z + oh) * scale;

    let mut s = String::with_capacity(2048);
    let _ = writeln!(
        s,
        r#"<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">"#,
    );
    let _ = writeln!(s, r#"<rect width="{w}" height="{h}" fill="white"/>"#);

    // Eave outline: dashed offset polygon (uniform outward expand by `oh`).
    // For axis-aligned rectilinear footprints we approximate the offset by
    // shifting each vertex outward along the diagonal bisector — visually
    // adequate for the roof plan, which only needs the eave silhouette.
    let n = poly.len() as f32;
    let cx = poly.iter().map(|p| p.0).sum::<f32>() / n;
    let cz = poly.iter().map(|p| p.1).sum::<f32>() / n;
    let eave_pts: Vec<(f32, f32)> = poly
        .iter()
        .map(|&(x, z)| {
            let dx = (x - cx).signum() * oh;
            let dz = (z - cz).signum() * oh;
            (x + dx, z + dz)
        })
        .collect();
    let eave_str = eave_pts
        .iter()
        .map(|(x, z)| format!("{},{}", px(*x), py(*z)))
        .collect::<Vec<_>>()
        .join(" ");
    let _ = writeln!(
        s,
        r##"<polygon points="{eave_str}" fill="#f7f5ee" stroke="#888" stroke-width="1" stroke-dasharray="6,4"/>"##,
    );

    // Footprint outline (wall line).
    let foot_str = poly
        .iter()
        .map(|(x, z)| format!("{},{}", px(*x), py(*z)))
        .collect::<Vec<_>>()
        .join(" ");
    let _ = writeln!(
        s,
        r##"<polygon points="{foot_str}" fill="none" stroke="#333" stroke-width="1.5"/>"##,
    );

    // Straight skeleton: hips / valleys / ridges, with the skeleton helper
    // choosing the line style per kind.
    let arcs = rectilinear_straight_skeleton(poly);
    let frag = skeleton_to_svg_fragment(&arcs, &px, &py);
    s.push_str(&frag);

    // Title + pitch note.
    let lbl = r##"font-family="Helvetica, Arial, sans-serif" font-size="12" fill="#333""##;
    let pitch_12 = (roof.pitch * 12.0).round();
    let _ = writeln!(s, r#"<text x="{margin}" y="22" {lbl} font-weight="bold">ROOF PLAN — RECTILINEAR HIP</text>"#);
    let _ = writeln!(
        s,
        r#"<text x="{x}" y="{y}" {lbl}>Pitch {p:.0}:12 · overhang {o:.0} mm · skeleton arcs {a}</text>"#,
        x = margin, y = h - 20.0, p = pitch_12, o = oh, a = arcs.len(),
    );

    s.push_str("</svg>\n");
    s
}

#[cfg(test)]
mod tests {
    use super::*;

    fn rp(w: f32, d: f32, t: RoofType) -> RoofPlan {
        RoofPlan {
            width: w,
            depth: d,
            roof_type: t,
            pitch: 0.5,
            overhang: 300.0,
            footprint_polygon_mm: Vec::new(),
        }
    }

    #[test]
    fn gable_ridge_spans_full_length_no_hips() {
        let r = rp(12000.0, 8000.0, RoofType::Gable);
        let ((x1, z1), (x2, z2)) = r.ridge();
        assert!((x1 - 0.0).abs() < 1.0 && (x2 - 12000.0).abs() < 1.0);
        assert!((z1 - 4000.0).abs() < 1.0 && (z2 - 4000.0).abs() < 1.0);
        assert!(r.hips().is_empty());
        // 6:12 over an 8 m short span → 2 m ridge height.
        assert!((r.ridge_height() - 2000.0).abs() < 1.0);
    }

    #[test]
    fn hip_ridge_is_inset_with_four_hips() {
        let r = rp(12000.0, 8000.0, RoofType::Hip);
        let ((x1, _), (x2, _)) = r.ridge();
        // inset by half the short span (4 m).
        assert!((x1 - 4000.0).abs() < 1.0 && (x2 - 8000.0).abs() < 1.0);
        assert_eq!(r.hips().len(), 4);
    }

    #[test]
    fn square_hip_ridge_collapses_to_a_point() {
        let r = rp(8000.0, 8000.0, RoofType::Hip);
        let ((x1, z1), (x2, z2)) = r.ridge();
        assert!((x1 - x2).abs() < 1.0 && (z1 - z2).abs() < 1.0); // a point
        assert_eq!(r.hips().len(), 4); // pyramidal
    }

    #[test]
    fn roof_plan_svg_has_ridge_and_hips() {
        let svg = generate_roof_plan_svg(&rp(12000.0, 8000.0, RoofType::Hip));
        assert!(svg.starts_with("<svg xmlns="));
        assert!(svg.ends_with("</svg>\n"));
        assert!(svg.contains("ROOF PLAN — HIP"));
        // footprint + eave = 2 rects (+ bg = 3); ridge + 4 hips = 5 lines.
        assert_eq!(svg.matches("<line").count(), 5);
    }
}
