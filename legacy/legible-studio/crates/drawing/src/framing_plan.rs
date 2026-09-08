//! Framing-plan SVG generator (Phase 1.4 v1).
//!
//! Emits a Part 9 permit-style framing plan for floor/ceiling joists:
//! - For each room, picks the short-axis as the joist span direction
//! - Draws joist run lines at the requested o.c. spacing across the room
//! - Annotates the run with size + spacing (e.g. `2x10 @ 16" o.c.`)
//! - Drops a beam line at midspan when the span exceeds `max_span_ft`
//!
//! Joist sizing is intentionally simple in v1 — the caller passes a single
//! `JoistSpec` that applies to every room. OBC-table-driven per-room sizing
//! (varying species/grade/load) is a v2 refinement; the API already accepts
//! a lookup-style `max_span_ft` so the upgrade is local.

use crate::primitives::{Line2D, SliceResult, Text2D};
use archgeometry::SchemaDocument;
use glam::{Vec2, Vec3};

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

/// One joist run specification — what to draw and how to label it. v1 uses a
/// single spec for the whole plan; v2 can vary per room.
#[derive(Debug, Clone)]
pub struct JoistSpec {
    /// Nominal joist size string used in the annotation, e.g. "2x10".
    pub size: String,
    /// On-centre spacing in inches (16, 19.2, 24 are typical).
    pub spacing_in: f32,
    /// On-centre spacing in millimetres — drives the actual line spacing on
    /// the plan. Kept separate from `spacing_in` so the annotation reads as
    /// the architect intends rather than as a float conversion.
    pub spacing_mm: f32,
    /// Maximum clear span for this joist size, in feet. When a room's short
    /// dimension exceeds this, a beam is drawn at mid-span.
    pub max_span_ft: f32,
}

impl Default for JoistSpec {
    /// Sensible default: SPF #2 2x10 @ 16" o.c., 40 psf live, max span ≈ 17 ft.
    fn default() -> Self {
        Self {
            size: "2x10".into(),
            spacing_in: 16.0,
            spacing_mm: 406.4,
            max_span_ft: 17.0,
        }
    }
}

// ---------------------------------------------------------------------------
// Geometry constants (mm)
// ---------------------------------------------------------------------------

const JOIST_COLOUR: Vec3 = Vec3::new(0.0, 0.3, 0.6);
const BEAM_COLOUR: Vec3 = Vec3::new(0.7, 0.2, 0.0);
const LABEL_COLOUR: Vec3 = Vec3::ZERO;
const FT_PER_MM: f32 = 1.0 / 304.8;

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/// Generate a framing-plan `SliceResult` for the supplied schema document.
///
/// Joist runs are emitted for every room on the supplied `level_name`.
/// Pass `""` to include rooms with no level tag (single-storey docs).
#[must_use]
pub fn generate_framing_plan(
    doc: &SchemaDocument,
    spec: &JoistSpec,
    level_name: &str,
) -> SliceResult {
    let mut result = SliceResult {
        element_type: "framing_plan".to_string(),
        ..Default::default()
    };

    let rooms: Vec<&archgeometry::SchemaRoom> = doc
        .rooms
        .values()
        .filter(|r| level_name.is_empty() || r.level == level_name || r.level.is_empty())
        .collect();

    if rooms.is_empty() {
        result.annotations.push(Text2D {
            position: Vec2::new(doc.width * 0.5, -doc.depth * 0.5),
            text: "NO ROOMS ON THIS LEVEL — FRAMING NOT DEFINED".to_string(),
            height: 250.0,
            justification: "center".to_string(),
            color: Vec3::new(0.8, 0.0, 0.0),
            ..Default::default()
        });
        return result;
    }

    for room in rooms {
        emit_room_framing(&mut result, room, spec);
    }

    // Single legend annotation at the top — declares the default spec used.
    result.annotations.push(Text2D {
        position: Vec2::new(doc.width * 0.5, 400.0),
        text: format!(
            "FLOOR JOISTS: {} @ {}\" o.c. (TYP., UNLESS NOTED)",
            spec.size, fmt_in(spec.spacing_in),
        ),
        height: 200.0,
        justification: "center".to_string(),
        color: LABEL_COLOUR,
        ..Default::default()
    });

    result
}

/// Convenience: emit the framing-plan SVG ready for title-block injection.
#[must_use]
pub fn generate_framing_plan_svg(
    doc: &SchemaDocument,
    spec: &JoistSpec,
    level_name: &str,
    scale: f32,
    pad_world: f32,
) -> String {
    let result = generate_framing_plan(doc, spec, level_name);
    crate::svg::export_to_svg_padded(&result, scale, pad_world)
}

// ---------------------------------------------------------------------------
// Internals
// ---------------------------------------------------------------------------

fn emit_room_framing(
    result: &mut SliceResult,
    room: &archgeometry::SchemaRoom,
    spec: &JoistSpec,
) {
    let bx = room.bounds.x;
    let by = room.bounds.y;
    let bw = room.bounds.width;
    let bh = room.bounds.height;
    if bw <= 0.0 || bh <= 0.0 {
        return;
    }

    // Joist direction = short axis: joists span the shorter dimension so
    // the runs themselves are short (cheap) and bear on the long walls.
    let joists_run_horizontal = bw <= bh;
    let span_mm = if joists_run_horizontal { bw } else { bh };
    let span_ft = span_mm * FT_PER_MM;

    // Lay joists across the long axis at the requested o.c. spacing.
    let (range_start, range_end, perp_start, perp_end) = if joists_run_horizontal {
        (by, by + bh, bx, bx + bw)
    } else {
        (bx, bx + bw, by, by + bh)
    };
    let usable = (range_end - range_start) - spec.spacing_mm;
    let n_joists = (usable / spec.spacing_mm).floor().max(0.0) as usize + 2;
    for i in 0..n_joists {
        let t = range_start + (i as f32) * spec.spacing_mm;
        let t = t.min(range_end);
        let (a, b) = if joists_run_horizontal {
            (Vec2::new(perp_start, t), Vec2::new(perp_end, t))
        } else {
            (Vec2::new(t, perp_start), Vec2::new(t, perp_end))
        };
        result.lines.push(Line2D {
            start: a,
            end: b,
            layer: "A-FRAM-JOIST".into(),
            line_type: "continuous".into(),
            line_weight: 0.18,
            color: JOIST_COLOUR,
        });
    }

    // Span exceeds the joist's allowable max → drop a midspan beam.
    if span_ft > spec.max_span_ft {
        let mid = if joists_run_horizontal {
            // Joists run along X; beam runs perpendicular (along X) at midspan Y.
            // Actually beam bisects the joist span → perpendicular to joist run.
            let y_mid = by + bh * 0.5;
            (Vec2::new(bx, y_mid), Vec2::new(bx + bw, y_mid))
        } else {
            let x_mid = bx + bw * 0.5;
            (Vec2::new(x_mid, by), Vec2::new(x_mid, by + bh))
        };
        result.lines.push(Line2D {
            start: mid.0,
            end: mid.1,
            layer: "A-FRAM-BEAM".into(),
            line_type: "continuous".into(),
            line_weight: 0.5,
            color: BEAM_COLOUR,
        });
        // Beam callout.
        let label_pos = Vec2::new(
            (mid.0.x + mid.1.x) * 0.5,
            -(mid.0.y + mid.1.y) * 0.5 - 80.0,
        );
        result.annotations.push(Text2D {
            position: label_pos,
            text: "BEAM AT MIDSPAN — SEE STRUCTURAL".into(),
            height: 150.0,
            justification: "center".into(),
            color: BEAM_COLOUR,
            ..Default::default()
        });
    }

    // Direction arrow + size label at the room centre.
    let cx = bx + bw * 0.5;
    let cy = by + bh * 0.5;
    let arrow_len = (span_mm * 0.4).min(2000.0).max(600.0);
    let (a, b) = if joists_run_horizontal {
        (Vec2::new(cx, cy - arrow_len * 0.5), Vec2::new(cx, cy + arrow_len * 0.5))
    } else {
        (Vec2::new(cx - arrow_len * 0.5, cy), Vec2::new(cx + arrow_len * 0.5, cy))
    };
    result.lines.push(Line2D {
        start: a,
        end: b,
        layer: "A-FRAM-DIR".into(),
        line_type: "dashed".into(),
        line_weight: 0.25,
        color: JOIST_COLOUR,
    });
    result.annotations.push(Text2D {
        position: Vec2::new(cx, -cy),
        text: format!("{} @ {}\" o.c.", spec.size, fmt_in(spec.spacing_in)),
        height: 200.0,
        justification: "center".into(),
        color: LABEL_COLOUR,
        ..Default::default()
    });
}

fn fmt_in(v: f32) -> String {
    if (v - v.round()).abs() < 1e-3 {
        format!("{:.0}", v)
    } else {
        format!("{:.1}", v)
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use archgeometry::{RoomBounds, SchemaDocument, SchemaRoom};

    fn rect_doc_with_one_room(width: f32, height: f32) -> SchemaDocument {
        let mut doc = SchemaDocument::default();
        doc.width = width;
        doc.depth = height;
        doc.rooms.insert(
            "living".into(),
            SchemaRoom {
                name: "living".into(),
                level: "Level 1".into(),
                bounds: RoomBounds { x: 0.0, y: 0.0, width, height },
                ..Default::default()
            },
        );
        doc
    }

    #[test]
    fn joists_run_across_short_axis() {
        // Wide room (6m × 4m) — joists should run along Y (short side, 4m span).
        let doc = rect_doc_with_one_room(6000.0, 4000.0);
        let res = generate_framing_plan(&doc, &JoistSpec::default(), "Level 1");
        let joist_lines: Vec<_> = res.lines.iter()
            .filter(|l| l.layer == "A-FRAM-JOIST")
            .collect();
        assert!(!joist_lines.is_empty(), "should emit joist lines");
        // Each joist line should be vertical (Δx == 0 ⇒ runs along Y).
        for l in &joist_lines {
            let dx = (l.end.x - l.start.x).abs();
            let dy = (l.end.y - l.start.y).abs();
            assert!(dy > dx, "joist should be the long axis, got dx={dx} dy={dy}");
        }
    }

    #[test]
    fn beam_added_when_span_exceeds_max() {
        // 7m square → ~23 ft each way, exceeds default 17 ft max → beam.
        let doc = rect_doc_with_one_room(7000.0, 7000.0);
        let res = generate_framing_plan(&doc, &JoistSpec::default(), "Level 1");
        assert!(
            res.lines.iter().any(|l| l.layer == "A-FRAM-BEAM"),
            "long span should add a midspan beam"
        );
    }

    #[test]
    fn no_beam_for_short_span() {
        // 3×4 m room, well within max span.
        let doc = rect_doc_with_one_room(3000.0, 4000.0);
        let res = generate_framing_plan(&doc, &JoistSpec::default(), "Level 1");
        assert!(
            res.lines.iter().all(|l| l.layer != "A-FRAM-BEAM"),
            "short span shouldn't need a beam"
        );
    }

    #[test]
    fn legend_annotation_present() {
        let doc = rect_doc_with_one_room(4000.0, 5000.0);
        let res = generate_framing_plan(&doc, &JoistSpec::default(), "Level 1");
        assert!(
            res.annotations.iter().any(|a| a.text.contains("FLOOR JOISTS")),
            "legend annotation expected"
        );
    }

    #[test]
    fn empty_room_set_emits_placeholder() {
        let doc = SchemaDocument::default();
        let res = generate_framing_plan(&doc, &JoistSpec::default(), "Level 1");
        assert!(res.annotations.iter().any(|a| a.text.contains("NO ROOMS")));
    }

    #[test]
    fn svg_is_well_formed() {
        let doc = rect_doc_with_one_room(5000.0, 4000.0);
        let svg = generate_framing_plan_svg(&doc, &JoistSpec::default(), "Level 1", 10.0, 2500.0);
        assert!(svg.starts_with("<?xml"));
        assert!(svg.contains("<svg"));
        assert!(svg.contains("</svg>"));
    }
}
