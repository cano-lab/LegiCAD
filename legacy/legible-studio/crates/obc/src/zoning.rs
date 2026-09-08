//! Municipal **zoning** setbacks — distinct from the OBC (zoning is per-city).
//!
//! Scoped to the City of Greater Sudbury Zoning By-law 2010-100Z, per-zone
//! yard minimums. Values in metres. These are approximate residential defaults
//! pending exact confirmation against the by-law tables; the lot's zone is an
//! input. NOT a general 444-municipality layer — one city's table for the
//! site-plan drawing.

/// Minimum yard setbacks for a zone, in metres.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Setbacks {
    /// Front yard (from the street/front lot line).
    pub front: f32,
    /// Interior side yard (shared side lot line).
    pub interior_side: f32,
    /// Exterior side yard (street side of a corner lot).
    pub exterior_side: f32,
    /// Rear yard.
    pub rear: f32,
}

/// Setbacks (metres) for a Greater Sudbury residential zone. Unknown zones
/// fall back to the R1 single-detached standard.
#[must_use]
#[allow(clippy::match_same_arms)] // the fallback intentionally mirrors R1
pub fn setbacks_for(zone: &str) -> Setbacks {
    match zone.to_uppercase().as_str() {
        // Single-detached.
        "R1" => Setbacks { front: 6.0, interior_side: 1.2, exterior_side: 6.0, rear: 7.5 },
        // Two-unit / semi.
        "R2" => Setbacks { front: 6.0, interior_side: 1.2, exterior_side: 4.5, rear: 7.5 },
        // Low-rise multiple.
        "R3" | "R4" => Setbacks { front: 6.0, interior_side: 1.5, exterior_side: 4.5, rear: 7.5 },
        _ => Setbacks { front: 6.0, interior_side: 1.2, exterior_side: 6.0, rear: 7.5 },
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn r1_has_standard_yards() {
        let s = setbacks_for("R1");
        assert!((s.front - 6.0).abs() < 1e-6);
        assert!((s.interior_side - 1.2).abs() < 1e-6);
        assert!((s.rear - 7.5).abs() < 1e-6);
    }

    #[test]
    fn case_insensitive_and_falls_back_to_r1() {
        assert_eq!(setbacks_for("r1"), setbacks_for("R1"));
        assert_eq!(setbacks_for("unknown"), setbacks_for("R1"));
    }
}
