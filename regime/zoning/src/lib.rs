//! Regime engine — municipal **zoning** rules as proactive constraints.
//!
//! Where `regime-obc` encodes the Ontario Building Code (provincial), this
//! crate encodes per-municipality zoning by-laws — scoped to the City of
//! Greater Sudbury Zoning By-law 2010-100Z first, per `VISION.md`
//! ("one zone, one typology, one municipality").
//!
//! Two halves:
//! - **Tables**: [`Setbacks`] / [`setbacks_for`] — per-zone minimum yards
//!   (ported from the legacy `ls-obc` zoning module).
//! - **Envelope**: [`ZoningRules`] + [`rect_envelope`] — turn a rectangular
//!   lot + rules into the feasible building footprint and area caps. This is
//!   the "define the legal space, then sculpt within it" direction: rules
//!   first, geometry second.
//!
//! Values in metres. The Sudbury numbers are approximate residential
//! defaults pending exact confirmation against the by-law tables
//! (`questions.md` Q2).

use glam::Vec2;
use serde::{Deserialize, Serialize};

/// Minimum yard setbacks for a zone, in metres.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
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

/// Machine-readable zoning rules for one zone in one jurisdiction.
/// Matches the Phase-2 JSON schema in `START_HERE.md`.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ZoningRules {
    /// e.g. `"Greater Sudbury"`.
    pub jurisdiction: String,
    /// e.g. `"R1-Residential"`.
    pub zone: String,
    pub front_setback: f32,
    pub rear_setback: f32,
    pub side_setback: f32,
    /// Maximum building height (m).
    pub max_height: f32,
    /// Maximum floor space ratio (gross floor area / lot area).
    pub max_fsr: f32,
    /// Maximum lot coverage (footprint area / lot area), 0–1.
    pub max_coverage: f32,
    /// Required parking spaces per dwelling unit.
    pub parking_per_unit: u32,
}

impl ZoningRules {
    /// Build rules for a Sudbury zone from the setback table, with the
    /// remaining limits at conservative residential defaults. Override the
    /// fields with exact by-law values once confirmed (`questions.md` Q2).
    #[must_use]
    pub fn sudbury(zone: &str) -> Self {
        let s = setbacks_for(zone);
        Self {
            jurisdiction: "Greater Sudbury".into(),
            zone: zone.into(),
            front_setback: s.front,
            rear_setback: s.rear,
            side_setback: s.interior_side,
            max_height: 10.0,
            max_fsr: 0.5,
            max_coverage: 0.35,
            parking_per_unit: 2,
        }
    }
}

/// Feasible building envelope on a rectangular lot.
///
/// The lot is `width` (x, along the street) × `depth` (y, away from the
/// street) metres, origin at the front-left corner. The envelope is the lot
/// inset by the front/rear/side yards; height/FSR/coverage further cap what
/// can be built inside it.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct RectEnvelope {
    /// Footprint corners, front-left origin order: FL, FR, RR, RL.
    pub corners: [Vec2; 4],
    /// Buildable footprint area (m²) after yard setbacks.
    pub footprint_area: f32,
    /// Footprint cap from `max_coverage` × lot area (m²).
    pub coverage_cap: f32,
    /// Gross floor area cap from `max_fsr` × lot area (m²).
    pub gross_floor_cap: f32,
    /// Effective footprint: min(geometric footprint, coverage cap).
    pub effective_footprint: f32,
}

/// Compute the feasible envelope for a `width` × `depth` rectangular lot.
///
/// Returns `None` if the setbacks consume the lot entirely (a signal the
/// lot is unbuildable under this zone — itself useful output).
#[must_use]
pub fn rect_envelope(width: f32, depth: f32, rules: &ZoningRules) -> Option<RectEnvelope> {
    let w = width - 2.0 * rules.side_setback;
    let d = depth - rules.front_setback - rules.rear_setback;
    if w <= 0.0 || d <= 0.0 {
        return None;
    }
    let lot_area = width * depth;
    let footprint_area = w * d;
    let coverage_cap = rules.max_coverage * lot_area;
    let x0 = rules.side_setback;
    let y0 = rules.front_setback;
    Some(RectEnvelope {
        corners: [
            Vec2::new(x0, y0),
            Vec2::new(x0 + w, y0),
            Vec2::new(x0 + w, y0 + d),
            Vec2::new(x0, y0 + d),
        ],
        footprint_area,
        coverage_cap,
        gross_floor_cap: rules.max_fsr * lot_area,
        effective_footprint: footprint_area.min(coverage_cap),
    })
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

    #[test]
    fn envelope_is_lot_minus_yards() {
        // 15 m × 30 m R1 lot: sides 1.2 m, front 6.0 m, rear 7.5 m.
        let rules = ZoningRules::sudbury("R1");
        let env = rect_envelope(15.0, 30.0, &rules).expect("buildable");
        assert!((env.footprint_area - (15.0 - 2.4) * (30.0 - 13.5)).abs() < 1e-4);
        assert!((env.coverage_cap - 0.35 * 450.0).abs() < 1e-4);
        assert!((env.gross_floor_cap - 0.5 * 450.0).abs() < 1e-4);
        assert_eq!(env.corners[0], Vec2::new(1.2, 6.0));
    }

    #[test]
    fn unbuildable_lot_returns_none() {
        let rules = ZoningRules::sudbury("R1");
        assert!(rect_envelope(2.0, 30.0, &rules).is_none());
    }

    #[test]
    fn coverage_cap_bites_on_shallow_lots() {
        // Deep setbacks but tiny coverage → coverage is the binding limit.
        let rules = ZoningRules { max_coverage: 0.10, ..ZoningRules::sudbury("R1") };
        let env = rect_envelope(15.0, 30.0, &rules).expect("buildable");
        assert!(env.effective_footprint < env.footprint_area);
        assert!((env.effective_footprint - 45.0).abs() < 1e-4);
    }
}
