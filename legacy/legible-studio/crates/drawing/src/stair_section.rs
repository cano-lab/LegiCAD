//! Typical stair section (OBC 9.8).
//!
//! A side-on section through the stair: the riser/tread sawtooth between the
//! two finished floors, the stringer beneath it, a handrail, the stairwell
//! opening above with the **1950 mm headroom** clearance dimensioned, plus
//! floor-to-floor, total-run, and a single rise/run step callout. This is the
//! sheet a permit reviewer looks for to confirm the stair is climbable and the
//! head clearance is met — the elevation companion to the floor-plan symbol.
//!
//! One **typical** section covers the building: every storey shares the same
//! rise/run (the solver gives them all the same `StairSpec`). A true cut
//! through a switchback's two flights is a v2 refinement.
//!
//! Authoring frame: origin at the bottom of the first riser on the lower
//! finished floor, **X positive along the run (right), Y positive up**. The SVG
//! exporter negates Y, so up is up on the sheet; text is authored in the same
//! Y-up frame (no manual flip) and kept inside the line/polyline bounds that
//! drive the viewBox.

use crate::primitives::{Hatch2D, Line2D, Polyline2D, SliceResult, Text2D};
use glam::{Vec2, Vec3};

/// Everything needed to draw a typical stair section. Defaults match the
/// solver's default 10 ft storey (16 risers @ 190.5 mm, 255 mm going).
#[derive(Debug, Clone)]
pub struct StairSectionSpec {
    pub num_risers: u32,
    pub num_treads: u32,
    pub riser_height_mm: f32,
    pub tread_run_mm: f32,
    pub floor_to_floor_mm: f32,
    /// Minimum headroom to demonstrate (OBC 9.8.2.2, 1950 mm in a dwelling).
    pub headroom_min_mm: f32,
    /// Handrail height above the nosing line (OBC 9.8.7, 865–965 mm).
    pub handrail_height_mm: f32,
    /// Depth of the upper-floor assembly (finished floor down to the ceiling
    /// over the stair) — sets where the stairwell opening clears headroom.
    pub floor_assembly_mm: f32,
}

impl Default for StairSectionSpec {
    fn default() -> Self {
        Self {
            num_risers: 16,
            num_treads: 15,
            riser_height_mm: 190.5,
            tread_run_mm: 255.0,
            floor_to_floor_mm: 3048.0,
            headroom_min_mm: 1950.0,
            handrail_height_mm: 900.0,
            floor_assembly_mm: 300.0,
        }
    }
}

const INK: Vec3 = Vec3::ZERO;
const STRINGER_COLOUR: Vec3 = Vec3::new(0.35, 0.35, 0.35);
const RAIL_COLOUR: Vec3 = Vec3::new(0.20, 0.35, 0.65);
const FLOOR_COLOUR: Vec3 = Vec3::new(0.62, 0.62, 0.62);
const DIM_COLOUR: Vec3 = Vec3::new(0.15, 0.15, 0.15);

/// Generate a typical stair section as a `SliceResult` (mm, Y-up).
#[must_use]
#[allow(clippy::cast_precision_loss, clippy::too_many_lines, clippy::many_single_char_names)]
pub fn generate_stair_section(spec: &StairSectionSpec) -> SliceResult {
    let mut r = SliceResult { element_type: "stair_section".into(), ..Default::default() };

    let n = spec.num_risers.max(1);
    let t = spec.num_treads.min(n.saturating_sub(1)).max(1);
    let rise = spec.riser_height_mm.max(1.0);
    let run = spec.tread_run_mm.max(1.0);
    let ff = spec.floor_to_floor_mm.max(rise);
    let total_run = t as f32 * run;
    let fa = spec.floor_assembly_mm;
    let ceiling_y = ff - fa; // underside of the upper floor over the stair

    // -- Lower + upper finished floors, with floor-assembly bands -------------
    let lower_l = -700.0;
    let upper_r = total_run + 900.0;
    // Lower floor slab band.
    floor_band(&mut r, lower_l, 0.0, -fa, 0.0);
    line(&mut r, (lower_l, 0.0), (0.0, 0.0), INK, 0.5); // lower finished floor

    // Stairwell opening: the upper floor starts (cut edge) at the x where the
    // nosing line clears exactly the headroom minimum, so the dimension lands on
    // the binding point.
    let nosing_slope = rise / run; // nosing line: y = slope*x + rise
    let open_x =
        (((ceiling_y - spec.headroom_min_mm - rise) / nosing_slope).clamp(0.0, total_run)).max(0.0);
    let open_nosing_y = nosing_slope * open_x + rise;

    // Upper floor band, finished line, and ceiling line — right of the opening.
    floor_band(&mut r, open_x, upper_r, ceiling_y, ff);
    line(&mut r, (open_x, ff), (upper_r, ff), INK, 0.5); // upper finished floor
    line(&mut r, (open_x, ceiling_y), (upper_r, ceiling_y), INK, 0.35); // ceiling
    line(&mut r, (open_x, ceiling_y), (open_x, ff), INK, 0.5); // opening cut edge

    // -- Tread / riser sawtooth (the walking profile) ------------------------
    let mut pts: Vec<Vec2> = vec![Vec2::new(0.0, 0.0)];
    let mut x = 0.0;
    for i in 0..n {
        let y = (i + 1) as f32 * rise;
        pts.push(Vec2::new(x, y)); // riser up
        if i < t {
            x += run;
            pts.push(Vec2::new(x, y)); // tread out
        }
    }
    r.polylines.push(Polyline2D {
        points: pts,
        closed: false,
        layer: "A-STRS".into(),
        line_type: "continuous".into(),
        line_weight: 0.6,
        color: INK,
    });

    // -- Stringer (underside of the flight) ----------------------------------
    let sd = 300.0; // vertical drop to the stringer soffit
    line(&mut r, (0.0, -sd), (total_run, t as f32 * rise - sd), STRINGER_COLOUR, 0.5);
    line(&mut r, (0.0, 0.0), (0.0, -sd), STRINGER_COLOUR, 0.4);
    line(&mut r, (total_run, t as f32 * rise), (total_run, t as f32 * rise - sd), STRINGER_COLOUR, 0.4);

    // -- Handrail (parallel to the nosing line, offset up) -------------------
    let hh = spec.handrail_height_mm;
    let rail_lo = (0.0, rise + hh);
    let rail_hi = (total_run, nosing_slope * total_run + rise + hh);
    line(&mut r, rail_lo, rail_hi, RAIL_COLOUR, 0.6);
    line(&mut r, (0.0, rise), rail_lo, RAIL_COLOUR, 0.4); // bottom post
    line(&mut r, (total_run, nosing_slope * total_run + rise), rail_hi, RAIL_COLOUR, 0.4); // top post

    // -- Dimensions ----------------------------------------------------------
    // Floor-to-floor on the left.
    dim_v(&mut r, lower_l - 300.0, 0.0, ff, &format!("{ff:.0} F-F"), true);
    // Total run along the bottom.
    dim_h(&mut r, 0.0, total_run, -sd - 350.0, &format!("TOTAL RUN {total_run:.0}"));
    // Headroom at the binding nosing, up to the ceiling over the stair — the
    // value only; the OBC reference lives in the notes block.
    dim_v(&mut r, open_x, open_nosing_y, ceiling_y, &format!("{:.0}", ceiling_y - open_nosing_y), true);
    // One step's rise + run, called out on the third step.
    let k = 2.min(t.saturating_sub(1)) as f32;
    let sx = k * run;
    let sy = (k + 1.0) * rise;
    dim_v(&mut r, sx - 220.0, sy, sy + rise, &format!("{rise:.0}"), true);
    dim_h(&mut r, sx, sx + run, sy + rise + 160.0, &format!("{run:.0}"));

    // -- Labels (Y-up, kept within the line bounds) --------------------------
    let mut label = |x: f32, y: f32, text: &str, h: f32, just: &str, color: Vec3| {
        r.annotations.push(Text2D {
            position: Vec2::new(x, y),
            text: text.to_string(),
            height: h,
            justification: just.into(),
            color,
            ..Default::default()
        });
    };
    label(total_run * 0.5, ff + 450.0, "STAIR SECTION", 220.0, "center", INK);
    label(lower_l + 50.0, -fa * 0.5, "LOWER FLOOR", 110.0, "left", INK);
    label(upper_r - 50.0, ff + 130.0, "UPPER FLOOR", 110.0, "right", INK);
    label(open_x + 130.0, (open_nosing_y + ceiling_y) * 0.5, "HEADROOM", 110.0, "left", INK);
    label(
        total_run * 0.55,
        nosing_slope * total_run * 0.55 + rise + hh + 140.0,
        "HANDRAIL",
        110.0,
        "center",
        RAIL_COLOUR,
    );

    // Notes block in the open space under the stair (lower-right).
    let notes = [
        format!("{n} RISERS @ {rise:.0} mm = {ff:.0} mm"),
        format!("{t} TREADS @ {run:.0} mm RUN = {total_run:.0} mm"),
        format!("HEADROOM {:.0} mm (1950 MIN, OBC 9.8.2.2)", ceiling_y - open_nosing_y),
        format!("HANDRAIL {hh:.0} mm (865-965, OBC 9.8.7)"),
        "RISE/RUN PER OBC 9.8.4.2".to_string(),
    ];
    // The open wedge under the stringer (lower-right) widens down and right, so
    // a left-justified downward stack stays clear of the flight.
    let nx = total_run * 0.60;
    let mut ny = rise * 6.0;
    for (i, note) in notes.iter().enumerate() {
        let color = if i == 0 { INK } else { DIM_COLOUR };
        label(nx, ny, note, 125.0, "left", color);
        ny -= 230.0;
    }

    r
}

/// Render the stair section to an SVG string for title-block injection.
#[must_use]
pub fn generate_stair_section_svg(spec: &StairSectionSpec, scale: f32, pad_world: f32) -> String {
    crate::svg::export_to_svg_padded(&generate_stair_section(spec), scale, pad_world)
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

fn line(r: &mut SliceResult, a: (f32, f32), b: (f32, f32), color: Vec3, weight: f32) {
    r.lines.push(Line2D {
        start: Vec2::new(a.0, a.1),
        end: Vec2::new(b.0, b.1),
        layer: "A-STRS".into(),
        line_type: "continuous".into(),
        line_weight: weight,
        color,
    });
}

/// A light-grey floor-assembly band (outline + hatch) between two heights.
fn floor_band(r: &mut SliceResult, x0: f32, x1: f32, y0: f32, y1: f32) {
    let pts = vec![
        Vec2::new(x0, y0),
        Vec2::new(x1, y0),
        Vec2::new(x1, y1),
        Vec2::new(x0, y1),
    ];
    r.polylines.push(Polyline2D {
        points: pts.clone(),
        closed: true,
        layer: "A-FLOR".into(),
        line_type: "continuous".into(),
        line_weight: 0.3,
        color: FLOOR_COLOUR,
    });
    r.hatches.push(Hatch2D {
        boundaries: vec![Polyline2D {
            points: pts,
            closed: true,
            layer: "A-FLOR".into(),
            line_type: "continuous".into(),
            line_weight: 0.13,
            color: FLOOR_COLOUR,
        }],
        pattern: "ANSI31".into(),
        scale: 1.0,
        angle: 0.0,
        layer: "A-FLOR".into(),
        color: FLOOR_COLOUR,
    });
}

/// 45° architectural tick at a dimension-line end.
fn tick(r: &mut SliceResult, at: (f32, f32)) {
    let d = 60.0;
    line(r, (at.0 - d, at.1 - d), (at.0 + d, at.1 + d), DIM_COLOUR, 0.35);
}

/// Horizontal dimension between `x1` and `x2` at height `y`, text centred above.
fn dim_h(r: &mut SliceResult, x1: f32, x2: f32, y: f32, text: &str) {
    line(r, (x1, y), (x2, y), DIM_COLOUR, 0.3);
    tick(r, (x1, y));
    tick(r, (x2, y));
    r.annotations.push(Text2D {
        position: Vec2::new((x1 + x2) * 0.5, y + 90.0),
        text: text.to_string(),
        height: 120.0,
        justification: "center".into(),
        color: DIM_COLOUR,
        ..Default::default()
    });
}

/// Vertical dimension between `y1` and `y2` at `x`; text sits to one side.
fn dim_v(r: &mut SliceResult, x: f32, y1: f32, y2: f32, text: &str, text_left: bool) {
    line(r, (x, y1), (x, y2), DIM_COLOUR, 0.3);
    tick(r, (x, y1));
    tick(r, (x, y2));
    let (tx, just) = if text_left { (x - 120.0, "right") } else { (x + 120.0, "left") };
    r.annotations.push(Text2D {
        position: Vec2::new(tx, (y1 + y2) * 0.5),
        text: text.to_string(),
        height: 120.0,
        justification: just.into(),
        color: DIM_COLOUR,
        ..Default::default()
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sawtooth_has_one_riser_per_riser_and_reaches_the_upper_floor() {
        let spec = StairSectionSpec::default();
        let res = generate_stair_section(&spec);
        let saw = res.polylines.iter().find(|p| p.layer == "A-STRS").expect("sawtooth");
        // n risers + t treads + the start point.
        let expected = 1 + spec.num_risers as usize + spec.num_treads as usize;
        assert_eq!(saw.points.len(), expected);
        // Last point lands on the upper finished floor (x=total_run, y=ff).
        let last = *saw.points.last().unwrap();
        assert!((last.y - spec.floor_to_floor_mm).abs() < 1.0, "top of stair = floor-to-floor");
        assert!((last.x - spec.num_treads as f32 * spec.tread_run_mm).abs() < 1.0);
    }

    #[test]
    fn headroom_dimension_meets_the_minimum() {
        let spec = StairSectionSpec::default();
        let res = generate_stair_section(&spec);
        // The notes block reports a clearance at or above the 1950 mm minimum.
        let note = res
            .annotations
            .iter()
            .find(|a| a.text.starts_with("HEADROOM") && a.text.contains("OBC 9.8.2.2"))
            .expect("headroom note");
        let val: f32 = note.text.split_whitespace().nth(1).unwrap().parse().unwrap();
        assert!(val >= spec.headroom_min_mm - 1.0, "headroom {val} below minimum");
    }

    #[test]
    fn carries_the_key_permit_callouts_and_title() {
        let res = generate_stair_section(&StairSectionSpec::default());
        let texts: Vec<&str> = res.annotations.iter().map(|a| a.text.as_str()).collect();
        assert!(texts.iter().any(|s| s.contains("STAIR SECTION")));
        assert!(texts.iter().any(|s| s.contains("16 RISERS")));
        assert!(texts.iter().any(|s| s.contains("OBC 9.8.2.2"))); // headroom
        assert!(texts.iter().any(|s| s.contains("HANDRAIL")));
        assert!(texts.iter().any(|s| s.contains("F-F")));
    }

    #[test]
    fn svg_is_well_formed() {
        let svg = generate_stair_section_svg(&StairSectionSpec::default(), 1.0, 600.0);
        assert!(svg.starts_with("<?xml"));
        assert!(svg.contains("<svg"));
        assert!(svg.contains("</svg>"));
    }
}
