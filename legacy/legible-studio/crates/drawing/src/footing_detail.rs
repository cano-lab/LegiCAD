//! Typical footing detail (Phase 1.5).
//!
//! Section through a Part 9 strip footing: compacted gravel base, concrete
//! footing wider than the foundation wall, foundation wall above, and
//! horizontal rebar callouts. All dimensions in mm.
//!
//! This is a **typical** detail — one drawing covers the default soil
//! condition for every exterior wall. Per-wall variation (step footings,
//! pier footings, geotech-driven widths) is a v2 refinement.

use crate::primitives::{Dimension2D, Hatch2D, Polyline2D, SliceResult, Text2D};
use glam::{Vec2, Vec3};

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

/// All the geometry needed to draw a strip-footing section. Defaults match
/// a typical Ontario Part 9 detached dwelling on undisturbed soil.
#[derive(Debug, Clone)]
pub struct FootingSpec {
    pub footing_width_mm: f32,
    pub footing_thickness_mm: f32,
    pub foundation_wall_thickness_mm: f32,
    pub foundation_wall_height_mm: f32,
    pub gravel_depth_mm: f32,
    /// Cover (mm) from footing bottom/top face to the centre of the rebar.
    pub rebar_cover_mm: f32,
    /// Rebar designation shown in the callout (e.g. "2-#4 CONT.").
    pub rebar_callout: String,
}

impl Default for FootingSpec {
    fn default() -> Self {
        Self {
            footing_width_mm: 500.0,
            footing_thickness_mm: 200.0,
            foundation_wall_thickness_mm: 200.0,
            foundation_wall_height_mm: 1200.0,
            gravel_depth_mm: 150.0,
            rebar_cover_mm: 75.0,
            rebar_callout: "2-15M CONT., TOP & BOTTOM".into(),
        }
    }
}

// ---------------------------------------------------------------------------
// Colour palette
// ---------------------------------------------------------------------------

const CONCRETE_COLOUR: Vec3 = Vec3::new(0.65, 0.65, 0.65);
const GRAVEL_COLOUR: Vec3 = Vec3::new(0.55, 0.45, 0.35);
const REBAR_COLOUR: Vec3 = Vec3::new(0.85, 0.15, 0.15);
const SOIL_COLOUR: Vec3 = Vec3::new(0.40, 0.30, 0.20);
const LABEL_COLOUR: Vec3 = Vec3::ZERO;

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/// Generate a typical-footing section as a `SliceResult` in mm.
///
/// Coordinate frame: origin at the bottom-left corner of the gravel layer,
/// X positive to the right, Y positive UP (so the foundation wall stacks
/// above the footing in increasing Y).
#[must_use]
pub fn generate_footing_detail(spec: &FootingSpec) -> SliceResult {
    let mut result = SliceResult {
        element_type: "footing_detail".to_string(),
        ..Default::default()
    };

    let fw = spec.footing_width_mm;
    let ft_thk = spec.footing_thickness_mm;
    let fw_thk = spec.foundation_wall_thickness_mm;
    let fw_h = spec.foundation_wall_height_mm;
    let gd = spec.gravel_depth_mm;

    // Y-stack: gravel base [0, gd], footing [gd, gd+ft_thk], foundation
    // wall [gd+ft_thk, gd+ft_thk+fw_h]. Foundation wall is centred on the
    // footing.
    let y_footing_bot = gd;
    let y_footing_top = gd + ft_thk;
    let y_wall_top = y_footing_top + fw_h;
    let wall_x_lo = (fw - fw_thk) * 0.5;
    let wall_x_hi = wall_x_lo + fw_thk;

    // -- Gravel base --------------------------------------------------------
    push_filled_rect(
        &mut result,
        Vec2::new(0.0, 0.0),
        Vec2::new(fw, gd),
        "A-FOOT-GRVL",
        "AR-SAND",
        GRAVEL_COLOUR,
    );

    // -- Concrete footing ---------------------------------------------------
    push_filled_rect(
        &mut result,
        Vec2::new(0.0, y_footing_bot),
        Vec2::new(fw, y_footing_top),
        "A-FOOT-CONC",
        "AR-CONC",
        CONCRETE_COLOUR,
    );

    // -- Foundation wall ----------------------------------------------------
    push_filled_rect(
        &mut result,
        Vec2::new(wall_x_lo, y_footing_top),
        Vec2::new(wall_x_hi, y_wall_top),
        "A-FOUN-WALL",
        "AR-CONC",
        CONCRETE_COLOUR,
    );

    // -- Rebar dots ---------------------------------------------------------
    // Two top + two bottom bars symmetric about the footing centre.
    let cover = spec.rebar_cover_mm;
    let bar_y_bot = y_footing_bot + cover;
    let bar_y_top = y_footing_top - cover;
    let bar_x_left = cover;
    let bar_x_right = fw - cover;
    for &(bx, by) in &[
        (bar_x_left, bar_y_bot),
        (bar_x_right, bar_y_bot),
        (bar_x_left, bar_y_top),
        (bar_x_right, bar_y_top),
    ] {
        push_rebar_dot(&mut result, Vec2::new(bx, by));
    }

    // -- Soil hatch outside footing (left + right shoulders) ---------------
    // Just a hint that footing bears on undisturbed soil.
    let soil_w = fw * 0.25;
    push_filled_rect(
        &mut result,
        Vec2::new(-soil_w, 0.0),
        Vec2::new(0.0, y_footing_top),
        "A-SITE-SOIL",
        "EARTH",
        SOIL_COLOUR,
    );
    push_filled_rect(
        &mut result,
        Vec2::new(fw, 0.0),
        Vec2::new(fw + soil_w, y_footing_top),
        "A-SITE-SOIL",
        "EARTH",
        SOIL_COLOUR,
    );

    // -- Dimensions --------------------------------------------------------
    // Footing width along the bottom.
    result.dimensions.push(Dimension2D {
        point1: Vec2::new(0.0, -120.0),
        point2: Vec2::new(fw, -120.0),
        text_position: Vec2::new(fw * 0.5, -200.0),
        text: format!("{:.0} mm", fw),
        text_height: 80.0,
        layer: "A-DIMS".into(),
        style: "Standard".into(),
    });
    // Wall height up the right side.
    result.dimensions.push(Dimension2D {
        point1: Vec2::new(fw + soil_w + 120.0, y_footing_top),
        point2: Vec2::new(fw + soil_w + 120.0, y_wall_top),
        text_position: Vec2::new(fw + soil_w + 220.0, (y_footing_top + y_wall_top) * 0.5),
        text: format!("{:.0} mm", fw_h),
        text_height: 80.0,
        layer: "A-DIMS".into(),
        style: "Standard".into(),
    });

    // -- Callouts ----------------------------------------------------------
    let label = |y: f32, text: &str| Text2D {
        position: Vec2::new(fw + soil_w + 350.0, -y),
        text: text.to_string(),
        height: 90.0,
        justification: "left".into(),
        color: LABEL_COLOUR,
        ..Default::default()
    };
    result.annotations.push(label(
        gd * 0.5,
        &format!("{:.0} mm COMPACTED GRANULAR 'A'", gd),
    ));
    result.annotations.push(label(
        gd + ft_thk * 0.5,
        &format!(
            "{:.0} × {:.0} CONCRETE FOOTING — {}",
            fw, ft_thk, spec.rebar_callout
        ),
    ));
    result.annotations.push(label(
        gd + ft_thk + fw_h * 0.5,
        &format!("{:.0} mm CONCRETE FOUNDATION WALL", fw_thk),
    ));

    // Title strip at the top.
    result.annotations.push(Text2D {
        position: Vec2::new(fw * 0.5, -(y_wall_top + 250.0)),
        text: "TYPICAL FOOTING DETAIL — SCALE 1:20".to_string(),
        height: 110.0,
        justification: "center".into(),
        color: LABEL_COLOUR,
        ..Default::default()
    });

    result
}

/// Render the footing detail to an SVG string ready for title-block
/// injection by the documentation pipeline.
#[must_use]
pub fn generate_footing_detail_svg(spec: &FootingSpec, scale: f32, pad_world: f32) -> String {
    let result = generate_footing_detail(spec);
    crate::svg::export_to_svg_padded(&result, scale, pad_world)
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

fn push_filled_rect(
    result: &mut SliceResult,
    lo: Vec2,
    hi: Vec2,
    outline_layer: &str,
    pattern: &str,
    colour: Vec3,
) {
    let pts = vec![
        Vec2::new(lo.x, lo.y),
        Vec2::new(hi.x, lo.y),
        Vec2::new(hi.x, hi.y),
        Vec2::new(lo.x, hi.y),
    ];
    result.polylines.push(Polyline2D {
        points: pts.clone(),
        closed: true,
        layer: outline_layer.to_string(),
        line_type: "continuous".to_string(),
        line_weight: 0.35,
        color: colour,
    });
    result.hatches.push(Hatch2D {
        boundaries: vec![Polyline2D {
            points: pts,
            closed: true,
            layer: "A-PATT".to_string(),
            line_type: "continuous".to_string(),
            line_weight: 0.13,
            color: colour,
        }],
        pattern: pattern.to_string(),
        scale: 1.0,
        angle: 0.0,
        layer: "A-PATT".to_string(),
        color: colour,
    });
}

/// Approximate a rebar cross-section dot — a small square outline filled
/// with the rebar colour. svg::export_to_svg has no native circle for
/// SliceResult primitives at this point, so a 4-pt closed polyline reads
/// as a filled dot at print scale.
fn push_rebar_dot(result: &mut SliceResult, centre: Vec2) {
    let r = 18.0; // 15M rebar ≈ 16 mm Ø — fudge a bit so it reads on the sheet.
    let pts = vec![
        Vec2::new(centre.x - r, centre.y - r),
        Vec2::new(centre.x + r, centre.y - r),
        Vec2::new(centre.x + r, centre.y + r),
        Vec2::new(centre.x - r, centre.y + r),
    ];
    result.polylines.push(Polyline2D {
        points: pts.clone(),
        closed: true,
        layer: "A-FOOT-REBAR".to_string(),
        line_type: "continuous".to_string(),
        line_weight: 0.5,
        color: REBAR_COLOUR,
    });
    result.hatches.push(Hatch2D {
        boundaries: vec![Polyline2D {
            points: pts,
            closed: true,
            layer: "A-FOOT-REBAR".to_string(),
            line_type: "continuous".to_string(),
            line_weight: 0.13,
            color: REBAR_COLOUR,
        }],
        pattern: "SOLID".to_string(),
        scale: 1.0,
        angle: 0.0,
        layer: "A-FOOT-REBAR".to_string(),
        color: REBAR_COLOUR,
    });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_spec_emits_three_filled_layers_plus_two_soil_shoulders() {
        let res = generate_footing_detail(&FootingSpec::default());
        // gravel + footing + foundation wall + 2 soil shoulders + 4 rebar = 9 polylines
        assert_eq!(res.polylines.len(), 9);
        // Same count for hatches (every rect + every rebar gets a hatch).
        assert_eq!(res.hatches.len(), 9);
    }

    #[test]
    fn four_rebars_at_corners_within_footing() {
        let s = FootingSpec::default();
        let res = generate_footing_detail(&s);
        let rebar_polylines: Vec<_> = res
            .polylines
            .iter()
            .filter(|p| p.layer == "A-FOOT-REBAR")
            .collect();
        assert_eq!(rebar_polylines.len(), 4, "two-top, two-bottom rebar pattern");
        // Each rebar centre should sit inside [0, footing_width] × [gd, gd+ft_thk]
        for p in &rebar_polylines {
            let cx = (p.points[0].x + p.points[2].x) * 0.5;
            let cy = (p.points[0].y + p.points[2].y) * 0.5;
            assert!(cx > 0.0 && cx < s.footing_width_mm);
            assert!(cy > s.gravel_depth_mm
                && cy < s.gravel_depth_mm + s.footing_thickness_mm);
        }
    }

    #[test]
    fn dimensions_carry_width_and_height_callouts() {
        let s = FootingSpec::default();
        let res = generate_footing_detail(&s);
        assert_eq!(res.dimensions.len(), 2);
        assert!(res.dimensions.iter().any(|d| d.text.contains("500")));
        assert!(res.dimensions.iter().any(|d| d.text.contains("1200")));
    }

    #[test]
    fn annotations_include_rebar_callout_and_title() {
        let s = FootingSpec::default();
        let res = generate_footing_detail(&s);
        let texts: Vec<&str> = res.annotations.iter().map(|a| a.text.as_str()).collect();
        assert!(texts.iter().any(|t| t.contains("2-15M")));
        assert!(texts.iter().any(|t| t.contains("FOUNDATION WALL")));
        assert!(texts.iter().any(|t| t.contains("TYPICAL FOOTING DETAIL")));
    }

    #[test]
    fn svg_is_well_formed() {
        let svg = generate_footing_detail_svg(&FootingSpec::default(), 1.0, 200.0);
        assert!(svg.starts_with("<?xml"));
        assert!(svg.contains("<svg"));
        assert!(svg.contains("</svg>"));
    }

    #[test]
    fn foundation_wall_is_centered_on_footing() {
        let s = FootingSpec::default();
        let res = generate_footing_detail(&s);
        // Foundation-wall polyline is the third filled rect in emit order
        // (gravel, footing, wall). Verify its x-extent is centred.
        let wall = &res.polylines[2];
        let lo_x = wall.points[0].x;
        let hi_x = wall.points[2].x;
        let centre = (lo_x + hi_x) * 0.5;
        assert!((centre - s.footing_width_mm * 0.5).abs() < 1e-3);
        assert!((hi_x - lo_x - s.foundation_wall_thickness_mm).abs() < 1e-3);
    }
}
