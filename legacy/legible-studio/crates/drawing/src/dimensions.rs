//! Architectural dimension annotations — overall + opening tiers only.
//!
//! Simplified port of `ArchEngine_kernel/scripts/intelligent_dimensions.py`
//! (617 LOC). The Python implements a full 4-tier hierarchy with per-room
//! chains, interior-face logic, and overlap avoidance. This module ports
//! the two tiers most useful for permit drawings:
//!
//! - **Tier 1 (overall)**: building-envelope dimensions on each side
//! - **Tier 3 (opening)**: door/window dimensions per wall
//!
//! Tier 2 (structural grid) and Tier 4 (per-room interior) are deferred
//! to a later port. The simpler scope here matches the visual richness of
//! a basic permit floor plan / elevation; the more granular layers are
//! valuable but not blocking.

use std::fmt::Write as _;

/// A single linear dimension between two points along one axis.
#[derive(Debug, Clone)]
pub struct LinearDim {
    /// Start coordinate along the dimensioned axis (mm).
    pub from: f32,
    /// End coordinate along the dimensioned axis (mm).
    pub to: f32,
    /// Offset perpendicular to the axis where the dimension line sits (mm).
    /// For horizontal dimensions this is the Y; for vertical dimensions it
    /// is the X.
    pub offset: f32,
    /// Display value — usually formatted as `<value> mm` or `<value/304.8> ft`.
    /// Caller decides the units convention.
    pub value: String,
}

impl LinearDim {
    /// Make a horizontal dimension labelled in mm to the nearest integer.
    #[must_use]
    #[allow(clippy::cast_possible_truncation)] // building dims are bounded; rounding is intentional.
    pub fn horizontal_mm(from: f32, to: f32, y: f32) -> Self {
        let value = format!("{} mm", (to - from).abs().round() as i32);
        Self {
            from,
            to,
            offset: y,
            value,
        }
    }

    /// Make a vertical dimension labelled in mm.
    #[must_use]
    #[allow(clippy::cast_possible_truncation)] // building dims are bounded; rounding is intentional.
    pub fn vertical_mm(from: f32, to: f32, x: f32) -> Self {
        let value = format!("{} mm", (to - from).abs().round() as i32);
        Self {
            from,
            to,
            offset: x,
            value,
        }
    }
}

/// Render a horizontal linear dimension to an SVG fragment. Emits:
/// - dimension line between the two extension stops
/// - two extension lines (vertical ticks at `from` and `to`)
/// - a centred text label
#[must_use]
pub fn render_horizontal(dim: &LinearDim, text_height: f32) -> String {
    let (lo, hi) = if dim.from <= dim.to {
        (dim.from, dim.to)
    } else {
        (dim.to, dim.from)
    };
    let mid_x = (lo + hi) * 0.5;
    let y = dim.offset;
    let tick = text_height * 0.5;

    let mut s = String::with_capacity(256);
    // Dimension line.
    let _ = writeln!(
        s,
        r##"    <line x1="{lo}" y1="{y}" x2="{hi}" y2="{y}" stroke="#333" stroke-width="2"/>"##,
    );
    // Extension lines (perpendicular ticks at each end).
    let _ = writeln!(
        s,
        r##"    <line x1="{lo}" y1="{y1}" x2="{lo}" y2="{y2}" stroke="#333" stroke-width="2"/>"##,
        y1 = y - tick,
        y2 = y + tick,
    );
    let _ = writeln!(
        s,
        r##"    <line x1="{hi}" y1="{y1}" x2="{hi}" y2="{y2}" stroke="#333" stroke-width="2"/>"##,
        y1 = y - tick,
        y2 = y + tick,
    );
    // Centred value.
    let label_y = y - tick * 0.4;
    let _ = writeln!(
        s,
        r##"    <text x="{mid_x}" y="{label_y}" font-family="Arial, sans-serif" font-size="{text_height}" text-anchor="middle" fill="#333">{value}</text>"##,
        value = dim.value,
    );
    s
}

/// Render a vertical linear dimension. Mirrors `render_horizontal` but
/// the dimension line runs along Y at X = `dim.offset`.
#[must_use]
pub fn render_vertical(dim: &LinearDim, text_height: f32) -> String {
    let (lo, hi) = if dim.from <= dim.to {
        (dim.from, dim.to)
    } else {
        (dim.to, dim.from)
    };
    let mid_y = (lo + hi) * 0.5;
    let x = dim.offset;
    let tick = text_height * 0.5;

    let mut s = String::with_capacity(256);
    let _ = writeln!(
        s,
        r##"    <line x1="{x}" y1="{lo}" x2="{x}" y2="{hi}" stroke="#333" stroke-width="2"/>"##,
    );
    let _ = writeln!(
        s,
        r##"    <line x1="{x1}" y1="{lo}" x2="{x2}" y2="{lo}" stroke="#333" stroke-width="2"/>"##,
        x1 = x - tick,
        x2 = x + tick,
    );
    let _ = writeln!(
        s,
        r##"    <line x1="{x1}" y1="{hi}" x2="{x2}" y2="{hi}" stroke="#333" stroke-width="2"/>"##,
        x1 = x - tick,
        x2 = x + tick,
    );
    // Rotated text: 90 degrees CCW so it reads bottom-to-top.
    let label_x = x - tick * 0.4;
    let _ = writeln!(
        s,
        r##"    <text x="{label_x}" y="{mid_y}" transform="rotate(-90 {label_x} {mid_y})" font-family="Arial, sans-serif" font-size="{text_height}" text-anchor="middle" fill="#333">{value}</text>"##,
        value = dim.value,
    );
    s
}

/// Convenience: compute Tier-1 overall dimensions for a rectangular extent.
/// Returns (overall-width-dim, overall-depth-dim) placed `offset` mm
/// outside the bounding rectangle.
#[must_use]
pub fn overall_envelope_dims(
    min_x: f32,
    max_x: f32,
    min_y: f32,
    max_y: f32,
    offset: f32,
) -> (LinearDim, LinearDim) {
    let width = LinearDim::horizontal_mm(min_x, max_x, min_y - offset);
    let height = LinearDim::vertical_mm(min_y, max_y, min_x - offset);
    (width, height)
}

/// Tier-4 (per-room interior) dimensions: width along the top inside
/// edge + height along the left inside edge for each room rect. Useful
/// for the floor plan where each room gets its own dim pair.
#[must_use]
pub fn room_interior_dims(
    room_x: f32,
    room_y: f32,
    room_width: f32,
    room_height: f32,
    inset: f32,
) -> (LinearDim, LinearDim) {
    let width = LinearDim::horizontal_mm(room_x, room_x + room_width, room_y + inset);
    let height = LinearDim::vertical_mm(room_y, room_y + room_height, room_x + inset);
    (width, height)
}

/// Tier-2 (structural grid) chain dimensions: given a sorted list of
/// stop positions along an axis and a fixed perpendicular offset, emit
/// one dimension per adjacent pair. Useful for showing wall-to-wall
/// spacings along an exterior wall.
///
/// Returns one LinearDim per gap. Sort the input first if it isn't
/// already; consecutive duplicates produce zero-length dims and should
/// be deduped by the caller.
#[must_use]
pub fn chain_dims(stops: &[f32], offset: f32, horizontal: bool) -> Vec<LinearDim> {
    if stops.len() < 2 {
        return Vec::new();
    }
    stops
        .windows(2)
        .map(|w| {
            if horizontal {
                LinearDim::horizontal_mm(w[0], w[1], offset)
            } else {
                LinearDim::vertical_mm(w[0], w[1], offset)
            }
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn horizontal_dim_at_label_value() {
        let d = LinearDim::horizontal_mm(0.0, 5000.0, -800.0);
        assert_eq!(d.value, "5000 mm");
        assert_eq!(d.from, 0.0);
        assert_eq!(d.to, 5000.0);
        assert_eq!(d.offset, -800.0);
    }

    #[test]
    fn vertical_dim_at_label_value() {
        let d = LinearDim::vertical_mm(0.0, 3000.0, -800.0);
        assert_eq!(d.value, "3000 mm");
    }

    #[test]
    fn render_horizontal_emits_3_lines_and_1_text() {
        let d = LinearDim::horizontal_mm(0.0, 4000.0, -500.0);
        let svg = render_horizontal(&d, 150.0);
        // dim line + 2 extension ticks = 3 lines.
        assert_eq!(svg.matches("<line").count(), 3);
        assert_eq!(svg.matches("<text").count(), 1);
        assert!(svg.contains("4000 mm"));
    }

    #[test]
    fn render_vertical_rotates_text() {
        let d = LinearDim::vertical_mm(0.0, 3000.0, -500.0);
        let svg = render_vertical(&d, 150.0);
        assert!(svg.contains("rotate(-90"));
        assert!(svg.contains("3000 mm"));
    }

    #[test]
    fn overall_envelope_produces_both_dims_outside_bbox() {
        let (w, h) = overall_envelope_dims(0.0, 5000.0, 0.0, 4000.0, 800.0);
        assert_eq!(w.value, "5000 mm");
        assert_eq!(h.value, "4000 mm");
        // Width dim is below the bbox (y < 0).
        assert!(w.offset < 0.0);
        // Height dim is to the left of the bbox (x < 0).
        assert!(h.offset < 0.0);
    }

    #[test]
    fn negative_endpoints_handled() {
        let d = LinearDim::horizontal_mm(-100.0, 100.0, 0.0);
        assert_eq!(d.value, "200 mm");
    }

    #[test]
    fn room_interior_dims_inset_inside_the_room_rect() {
        let (w, h) = room_interior_dims(1000.0, 2000.0, 4000.0, 3000.0, 100.0);
        assert_eq!(w.value, "4000 mm");
        assert_eq!(h.value, "3000 mm");
        // Width dim runs along y = room_y + inset = 2100 (just inside top edge).
        assert_eq!(w.offset, 2100.0);
        // Height dim runs along x = room_x + inset = 1100.
        assert_eq!(h.offset, 1100.0);
    }

    #[test]
    fn chain_dims_emits_one_dim_per_gap() {
        let stops = vec![0.0_f32, 1000.0, 3000.0, 5000.0];
        let dims = chain_dims(&stops, -800.0, true);
        assert_eq!(dims.len(), 3);
        assert_eq!(dims[0].value, "1000 mm");
        assert_eq!(dims[1].value, "2000 mm");
        assert_eq!(dims[2].value, "2000 mm");
        // All sit at the same perpendicular offset.
        for d in &dims {
            assert_eq!(d.offset, -800.0);
        }
    }

    #[test]
    fn chain_dims_with_fewer_than_2_stops_is_empty() {
        assert!(chain_dims(&[], 0.0, true).is_empty());
        assert!(chain_dims(&[100.0], 0.0, true).is_empty());
    }
}
