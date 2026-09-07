//! Foundation plan SVG generator.
//!
//! Emits a Part 9 permit-style foundation plan:
//! - Footing outline under exterior walls (concrete, wider than wall)
//! - Slab edge / grade beam at wall centerlines
//! - Step footing annotations when grade changes (placeholder for now)
//! - Overall dimensions + title block via the standard pipeline.

use crate::primitives::{Hatch2D, Line2D, Polyline2D, SliceResult, Text2D};
use crate::svg::{color_to_svg, cpp_double, export_to_svg_padded};
use archgeometry::SchemaDocument;
use glam::{Vec2, Vec3};
use std::fmt::Write as _;

// ---------------------------------------------------------------------------
// Geometry constants (mm)
// ---------------------------------------------------------------------------

/// Footing extends this far beyond the wall face on each side.
const FOOTING_PROJECTION: f32 = 150.0;
/// Footing thickness (vertical) — drawn as a second, outer polyline.
const FOOTING_THICKNESS: f32 = 200.0;
/// Concrete hatch colour.
const CONCRETE_COLOUR: Vec3 = Vec3::new(0.65, 0.65, 0.65);
/// Wall centreline colour.
const WALL_CL_COLOUR: Vec3 = Vec3::new(0.0, 0.0, 0.0);

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/// Generate a foundation-plan `SliceResult` from the schema document.
///
/// Only exterior walls on the ground floor (`level_name == ""` or
/// `"Level 1"`) are considered. The footing outline is derived by
/// offsetting each exterior wall segment outward by `FOOTING_PROJECTION`.
///
/// The returned `SliceResult` can be fed directly into `export_to_svg_padded`
/// and then wrapped with a title block, just like the floor plan.
#[must_use]
pub fn generate_foundation_plan(doc: &SchemaDocument) -> SliceResult {
    let mut result = SliceResult {
        element_type: "foundation_plan".to_string(),
        ..Default::default()
    };

    // Collect ground-floor exterior walls.
    let ext_walls: Vec<&archgeometry::SchemaWall> = doc
        .walls
        .iter()
        .filter(|w| {
            w.category == "exterior"
                && (w.level_name.is_empty() || w.level_name == "Level 1")
        })
        .collect();

    if ext_walls.is_empty() {
        // No exterior walls — emit a placeholder note.
        result.annotations.push(Text2D {
            position: Vec2::new(doc.width * 0.5, -doc.depth * 0.5),
            text: "NO EXTERIOR WALLS — FOUNDATION NOT DEFINED".to_string(),
            height: 250.0,
            justification: "center".to_string(),
            color: Vec3::new(0.8, 0.0, 0.0),
            ..Default::default()
        });
        return result;
    }

    // Build footing outline: offset each wall segment outward by the
    // footing projection.  For a closed rectangular footprint we want
    // exactly one point per corner (4 pts + closing repeat).
    let mut footing_pts: Vec<Vec2> = Vec::new();
    for w in &ext_walls {
        let dir = w.direction();
        let normal = Vec2::new(-dir.y, dir.x); // perpendicular, CCW from dir
        let offset = normal * (wall_thickness_for(w) * 0.5 + FOOTING_PROJECTION);

        let p1 = Vec2::new(w.start.x, w.start.z) + offset;

        if footing_pts.is_empty() {
            footing_pts.push(p1);
        } else {
            let last = *footing_pts.last().unwrap();
            if (p1 - last).length() > 1.0 {
                footing_pts.push(p1);
            }
        }
    }

    // Close the loop.
    if footing_pts.len() >= 3 {
        let first = footing_pts[0];
        let last = *footing_pts.last().unwrap();
        if (last - first).length() > 1.0 {
            footing_pts.push(first);
        }
    }

    // Footing outline polyline.
    if footing_pts.len() >= 3 {
        result.polylines.push(Polyline2D {
            points: footing_pts.clone(),
            closed: true,
            layer: "A-FOOT".to_string(),
            line_type: "continuous".to_string(),
            line_weight: 0.5,
            color: CONCRETE_COLOUR,
        });

        // Concrete hatch fill.
        result.hatches.push(Hatch2D {
            boundaries: vec![Polyline2D {
                points: footing_pts.clone(),
                closed: true,
                layer: "A-PATT".to_string(),
                line_type: "continuous".to_string(),
                line_weight: 0.13,
                color: CONCRETE_COLOUR,
            }],
            pattern: "AR-CONC".to_string(),
            scale: 1.0,
            angle: 0.0,
            layer: "A-PATT".to_string(),
            color: CONCRETE_COLOUR,
        });
    }

    // Wall centrelines (thin, for reference).
    for w in &ext_walls {
        result.lines.push(Line2D {
            start: Vec2::new(w.start.x, w.start.z),
            end: Vec2::new(w.end.x, w.end.z),
            layer: "A-WALL-CL".to_string(),
            line_type: "center".to_string(),
            line_weight: 0.18,
            color: WALL_CL_COLOUR,
        });
    }

    // Annotation: footing width callout at the midpoint of the first wall.
    if let Some(w) = ext_walls.first() {
        let mid = Vec2::new(
            (w.start.x + w.end.x) * 0.5,
            (w.start.z + w.end.z) * 0.5,
        );
        let thick = wall_thickness_for(w);
        let fw = thick + FOOTING_PROJECTION * 2.0;
        result.annotations.push(Text2D {
            position: Vec2::new(mid.x, -mid.y - 400.0),
            text: format!("TYP. FOOTING {}mm WIDE", fw.round()),
            height: 180.0,
            justification: "center".to_string(),
            color: Vec3::ZERO,
            ..Default::default()
        });
    }

    result
}

/// Convenience: emit the full foundation-plan SVG (geometry only, no title
/// block). Use the same scale/padding as the floor plan.
#[must_use]
pub fn generate_foundation_plan_svg(doc: &SchemaDocument, scale: f32, pad_world: f32) -> String {
    let result = generate_foundation_plan(doc);
    export_to_svg_padded(&result, scale, pad_world)
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/// Estimate wall thickness from the wall type name, or fall back to a
/// typical 2×6 exterior wall (140 mm framing + 12.5 mm drywall each side
/// ≈ 165 mm). If the schema carries `wall_types`, we could look it up
/// precisely; this heuristic is good enough for the foundation plan.
fn wall_thickness_for(w: &archgeometry::SchemaWall) -> f32 {
    match w.wall_type.as_str() {
        "exterior_2x6_r21" | "ext_2x6_r21" => 165.0,
        "exterior_2x4_r13" | "ext_2x4_r13" => 140.0,
        "exterior_2x8_r28" | "ext_2x8_r28" => 190.0,
        _ => 165.0,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use archgeometry::{SchemaWall, SchemaDocument};
    use glam::Vec3;

    fn rect_doc() -> SchemaDocument {
        let mut doc = SchemaDocument::default();
        doc.width = 5000.0;
        doc.depth = 4000.0;
        for ((sx, sz), (ex, ez)) in [
            ((0.0, 0.0), (5000.0, 0.0)),
            ((5000.0, 0.0), (5000.0, 4000.0)),
            ((5000.0, 4000.0), (0.0, 4000.0)),
            ((0.0, 4000.0), (0.0, 0.0)),
        ] {
            doc.walls.push(SchemaWall {
                start: Vec3::new(sx, 0.0, sz),
                end: Vec3::new(ex, 0.0, ez),
                height: 2700.0,
                category: "exterior".into(),
                wall_type: "ext_2x6_r21".into(),
                ..Default::default()
            });
        }
        doc
    }

    #[test]
    fn foundation_plan_has_footing_outline() {
        let doc = rect_doc();
        let result = generate_foundation_plan(&doc);
        assert!(!result.polylines.is_empty(), "should have footing polyline");
        let footing = &result.polylines[0];
        assert!(footing.closed, "footing should be closed loop");
        assert_eq!(footing.points.len(), 5, "4 walls + closing point");
    }

    #[test]
    fn foundation_plan_has_concrete_hatch() {
        let doc = rect_doc();
        let result = generate_foundation_plan(&doc);
        assert!(!result.hatches.is_empty(), "should have concrete hatch");
        assert_eq!(result.hatches[0].pattern, "AR-CONC");
    }

    #[test]
    fn foundation_plan_has_wall_centrelines() {
        let doc = rect_doc();
        let result = generate_foundation_plan(&doc);
        assert_eq!(result.lines.len(), 4, "4 exterior wall centrelines");
        assert!(result.lines.iter().all(|l| l.line_type == "center"));
    }

    #[test]
    fn foundation_plan_svg_is_well_formed() {
        let doc = rect_doc();
        let svg = generate_foundation_plan_svg(&doc, 10.0, 2500.0);
        assert!(svg.starts_with("<?xml"));
        assert!(svg.contains("<svg"));
        assert!(svg.contains("</svg>"));
        assert!(svg.contains("fill-opacity=\"0.3\""), "concrete hatch should render as semi-transparent polygon");
    }

    #[test]
    fn no_exterior_walls_yields_placeholder() {
        let doc = SchemaDocument::default();
        let result = generate_foundation_plan(&doc);
        assert!(!result.annotations.is_empty());
        assert!(result.annotations[0].text.contains("NO EXTERIOR WALLS"));
    }
}
