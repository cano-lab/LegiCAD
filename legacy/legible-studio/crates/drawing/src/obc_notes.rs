//! Standard OBC notes block (Phase 2.4).
//!
//! Emits an SVG `<g>` group with the boilerplate Ontario Building Code
//! notes that have to appear on every Part 9 residential permit set:
//! - **OBC 9.10.19** — smoke alarm placement + wiring requirements.
//! - **OBC 9.33.4** — carbon-monoxide alarm placement adjacent to sleeping
//!   areas.
//!
//! The block is meant to be injected onto the floor plan (and optionally
//! elevations) by the documentation pipeline, positioned in mm model
//! space so it can sit alongside the existing title block.

use std::fmt::Write as _;

/// Width of the notes block in mm. Sized so the body text reads at
/// 80-pt model-space type on a standard 1:100 sheet.
const NOTES_WIDTH_MM: f32 = 4000.0;
/// Height in mm — line spacing × line count, with header.
const NOTES_HEIGHT_MM: f32 = 1400.0;

/// One numbered note entry on the block.
struct Note {
    title: &'static str,
    body: &'static str,
}

const OBC_NOTES: &[Note] = &[
    Note {
        title: "1. SMOKE ALARMS — O.B.C. 9.10.19",
        body: "PROVIDE INTERCONNECTED HARDWIRED SMOKE ALARMS WITH BATTERY \
               BACKUP ON EACH STOREY AND IN EACH SLEEPING ROOM. INSTALL PER \
               MANUFACTURER'S INSTRUCTIONS.",
    },
    Note {
        title: "2. CARBON MONOXIDE ALARMS — O.B.C. 9.33.4",
        body: "PROVIDE A CO ALARM ADJACENT TO EACH SLEEPING AREA WHERE A FUEL-\
               BURNING APPLIANCE OR ATTACHED GARAGE IS PRESENT. ALARMS MAY BE \
               BATTERY-OPERATED OR HARDWIRED.",
    },
    Note {
        title: "3. THERMAL ENVELOPE",
        body: "WALL ASSEMBLIES PER PLAN MEET OR EXCEED MINIMUM R-VALUE FOR \
               CLIMATE ZONE — SEE A-401 COMPLIANCE REPORT.",
    },
];

/// Generate the OBC general-notes SVG block, anchored at `(origin_x_mm,
/// origin_y_mm)` in the surrounding sheet's coordinate system.
///
/// Returns just the `<g>...</g>` fragment — the caller is responsible for
/// injecting it into the host `<svg>` before its closing tag (mirrors how
/// the title block is composed).
#[must_use]
pub fn generate_obc_notes_block(origin_x_mm: f32, origin_y_mm: f32) -> String {
    let mut s = String::with_capacity(1024);
    s.push_str("<!-- OBC General Notes -->\n");
    s.push_str("<g id=\"obc-notes\">\n");

    // Border box.
    let _ = writeln!(
        s,
        r##"  <rect x="{x}" y="{y}" width="{w}" height="{h}" fill="white" stroke="#000" stroke-width="3"/>"##,
        x = origin_x_mm,
        y = origin_y_mm,
        w = NOTES_WIDTH_MM,
        h = NOTES_HEIGHT_MM,
    );

    // Header bar.
    let header_h = 200.0_f32;
    let _ = writeln!(
        s,
        r##"  <rect x="{x}" y="{y}" width="{w}" height="{h}" fill="#222"/>"##,
        x = origin_x_mm,
        y = origin_y_mm,
        w = NOTES_WIDTH_MM,
        h = header_h,
    );
    let _ = writeln!(
        s,
        r##"  <text x="{cx}" y="{ty}" font-family="Arial" font-size="120" font-weight="bold" fill="white" text-anchor="middle">GENERAL NOTES — ONTARIO BUILDING CODE</text>"##,
        cx = origin_x_mm + NOTES_WIDTH_MM * 0.5,
        ty = origin_y_mm + header_h * 0.7,
    );

    // Numbered notes — title in bold, body wrapped to two lines.
    let line_height = 110.0_f32;
    let mut cursor = origin_y_mm + header_h + line_height;
    for note in OBC_NOTES {
        let _ = writeln!(
            s,
            r##"  <text x="{x}" y="{y}" font-family="Arial" font-size="80" font-weight="bold" fill="#000">{title}</text>"##,
            x = origin_x_mm + 80.0,
            y = cursor,
            title = note.title,
        );
        cursor += line_height * 0.9;
        for line in wrap_at(note.body, 70) {
            let _ = writeln!(
                s,
                r##"  <text x="{x}" y="{y}" font-family="Arial" font-size="70" fill="#222">{line}</text>"##,
                x = origin_x_mm + 200.0,
                y = cursor,
                line = line,
            );
            cursor += line_height * 0.8;
        }
        cursor += line_height * 0.2;
    }

    s.push_str("</g>\n");
    s
}

/// Convenience constant for the notes block's footprint, in case the
/// caller wants to position it relative to a known size.
#[must_use]
pub fn notes_block_size_mm() -> (f32, f32) {
    (NOTES_WIDTH_MM, NOTES_HEIGHT_MM)
}

/// Simple greedy word-wrap to ~`max_chars` per line. Preserves the input
/// text content — we just split on whitespace and re-pack.
fn wrap_at(text: &str, max_chars: usize) -> Vec<String> {
    let mut lines: Vec<String> = Vec::new();
    let mut current = String::new();
    for word in text.split_whitespace() {
        if current.is_empty() {
            current.push_str(word);
        } else if current.len() + 1 + word.len() <= max_chars {
            current.push(' ');
            current.push_str(word);
        } else {
            lines.push(std::mem::take(&mut current));
            current.push_str(word);
        }
    }
    if !current.is_empty() {
        lines.push(current);
    }
    lines
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn notes_block_contains_both_required_obc_sections() {
        let svg = generate_obc_notes_block(0.0, 0.0);
        assert!(svg.contains("9.10.19"), "smoke alarm OBC reference");
        assert!(svg.contains("9.33.4"), "CO alarm OBC reference");
    }

    #[test]
    fn notes_block_has_header_and_body_text() {
        let svg = generate_obc_notes_block(0.0, 0.0);
        assert!(svg.contains("GENERAL NOTES"));
        assert!(svg.contains("SMOKE ALARMS"));
        assert!(svg.contains("CARBON MONOXIDE"));
    }

    #[test]
    fn wraps_long_lines_at_word_boundaries() {
        let lines = wrap_at("ONE TWO THREE FOUR FIVE SIX SEVEN", 12);
        // Greedy packing.
        assert!(lines.iter().all(|l| l.len() <= 12));
        // Together they reconstruct the input modulo whitespace runs.
        assert_eq!(
            lines.join(" "),
            "ONE TWO THREE FOUR FIVE SIX SEVEN"
        );
    }

    #[test]
    fn block_size_matches_constants() {
        let (w, h) = notes_block_size_mm();
        assert!((w - 4000.0).abs() < 1e-3);
        assert!((h - 1400.0).abs() < 1e-3);
    }

    #[test]
    fn block_is_well_formed_g_fragment() {
        let svg = generate_obc_notes_block(0.0, 0.0);
        assert!(svg.contains(r#"<g id="obc-notes">"#));
        assert!(svg.trim_end().ends_with("</g>"));
    }
}
