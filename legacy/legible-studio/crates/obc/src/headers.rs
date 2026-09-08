//! Header (lintel) sizing over openings, OBC 9.23.12 span tables.
//!
//! The full jurisdiction-exact table loads from `OBC_Library` JSON via
//! [`crate::engine::OBCEngine`]; this module carries an **embedded** default
//! (double-ply SPF No.1/No.2) so the rules engine can size headers
//! deterministically at solve time without file I/O. Approximate Table
//! 9.23.12 values — sensible defaults, refine against the loaded table later.

use crate::tables::HeaderEntry;

/// Embedded default header span table (double-ply members). `max_span_1_story`
/// supports roof + ceiling; `max_span_2_story` supports roof + one floor.
#[must_use]
pub fn default_header_table() -> Vec<HeaderEntry> {
    let mk = |size: &str, depth: f32, s1: f32, s2: f32| HeaderEntry {
        size: size.into(),
        depth_inches: depth,
        max_span_1_story: s1,
        max_span_2_story: s2,
        support_type: "roof_ceiling_only".into(),
    };
    vec![
        mk("2-2x4", 3.5, 3.0, 2.0),
        mk("2-2x6", 5.5, 5.0, 3.5),
        mk("2-2x8", 7.25, 6.5, 4.5),
        mk("2-2x10", 9.25, 9.0, 6.0),
        mk("2-2x12", 11.25, 11.0, 7.5),
    ]
}

/// Smallest header size whose allowable span covers `opening_width_ft` for the
/// number of storeys bearing above it. Openings beyond the table return the
/// largest size flagged for engineer review (`needs_review = true`).
#[must_use]
pub fn header_size_for(opening_width_ft: f32, stories_supported: i32) -> (String, bool) {
    let table = default_header_table();
    let span = |e: &HeaderEntry| {
        if stories_supported <= 1 {
            e.max_span_1_story
        } else {
            e.max_span_2_story
        }
    };
    for e in &table {
        if span(e) >= opening_width_ft {
            return (e.size.clone(), false);
        }
    }
    // Exceeds the table — largest size, flag for an engineer.
    (table.last().map_or_else(String::new, |e| e.size.clone()), true)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn narrow_door_gets_a_small_header() {
        // A 3 ft door, single storey above → smallest size that spans it.
        let (size, review) = header_size_for(3.0, 1);
        assert_eq!(size, "2-2x4");
        assert!(!review);
    }

    #[test]
    fn wider_opening_needs_a_deeper_header() {
        // An 8 ft opening, single storey.
        let (size, _) = header_size_for(8.0, 1);
        assert_eq!(size, "2-2x10");
    }

    #[test]
    fn two_storeys_above_need_a_deeper_header_for_the_same_span() {
        let (one, _) = header_size_for(6.0, 1);
        let (two, _) = header_size_for(6.0, 2);
        // Carrying a floor + roof needs at least as deep a header.
        assert_ne!(one, two);
        assert_eq!(one, "2-2x8");
        assert_eq!(two, "2-2x10");
    }

    #[test]
    fn oversized_opening_is_flagged_for_review() {
        let (_, review) = header_size_for(20.0, 2);
        assert!(review, "20 ft opening should be flagged for an engineer");
    }
}
