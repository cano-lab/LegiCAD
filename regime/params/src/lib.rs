//! Regime engine — parametric inputs: the site, the program brief, and the
//! question-based narrowing that steers generation.
//!
//! This is the "questions" side of the regime (`VISION.md`: "Site →
//! Questions → Constraints → Masses → Sculpt"). Geometry and rule tables
//! live in `archengine-geometry` / `regime-obc` / `regime-zoning`; this
//! crate is the serde boundary that collects user intent into one document
//! the solver can consume.
//!
//! Schemas follow `START_HERE.md` Phase 1/2 (site boundary + zoning rules +
//! program brief). Everything is plain data — no logic beyond validation.

use glam::Vec2;
use serde::{Deserialize, Serialize};

/// A building site: boundary polygon + where in the world it is.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Site {
    /// Closed polygon (XZ plan, metres). First point need not repeat at the
    /// end; the loop closes implicitly.
    pub boundary: Vec<Vec2>,
    /// e.g. `"Greater Sudbury"`.
    pub jurisdiction: String,
    /// Zone code within the jurisdiction, e.g. `"R1"`.
    pub zone: String,
    /// Street the front lot line faces (for front-yard orientation).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub street: Option<String>,
}

impl Site {
    /// Lot area via the shoelace formula (m²).
    #[must_use]
    pub fn area(&self) -> f32 {
        let n = self.boundary.len();
        if n < 3 {
            return 0.0;
        }
        let mut sum = 0.0;
        for i in 0..n {
            let a = self.boundary[i];
            let b = self.boundary[(i + 1) % n];
            sum += a.x * b.y - b.x * a.y;
        }
        sum.abs() / 2.0
    }
}

/// What the user wants to build — the "program brief" sliders from
/// `START_HERE.md` Step 1.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ProgramBrief {
    /// Number of dwelling units.
    pub unit_count: u32,
    /// Target size per unit (m²).
    pub target_unit_sqm: f32,
    /// Parking spaces the user wants (may exceed the zoning minimum).
    #[serde(default)]
    pub parking_spaces: u32,
    /// Preferred storeys, if the user has one (`None` = let the regime decide).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub storeys: Option<u32>,
}

impl ProgramBrief {
    /// Gross floor area the program asks for (m²).
    #[must_use]
    pub fn gross_floor_area(&self) -> f32 {
        self.unit_count as f32 * self.target_unit_sqm
    }
}

/// One narrowing answer in the question-based flow (`VISION.md` §3:
/// "Each answer narrows the parametric space").
///
/// Questions are free-form key/value so the UX can evolve without schema
/// churn (`questions.md` Q7 — granularity is still open).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Answer {
    /// Stable question key, e.g. `"construction"`, `"target_rent_sqm"`.
    pub key: String,
    /// The user's answer, e.g. `"mass_timber"`, `"28"`.
    pub value: String,
}

/// The complete regime input: site + program + narrowing answers.
/// This is the document sent into the constraint/generation loop.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RegimeInput {
    pub site: Site,
    pub brief: ProgramBrief,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub answers: Vec<Answer>,
}

#[cfg(test)]
mod tests {
    use super::*;

    fn rect_site(w: f32, d: f32) -> Site {
        Site {
            boundary: vec![
                Vec2::new(0.0, 0.0),
                Vec2::new(w, 0.0),
                Vec2::new(w, d),
                Vec2::new(0.0, d),
            ],
            jurisdiction: "Greater Sudbury".into(),
            zone: "R1".into(),
            street: None,
        }
    }

    #[test]
    fn shoelace_area_of_rectangle() {
        assert!((rect_site(15.0, 30.0).area() - 450.0).abs() < 1e-4);
    }

    #[test]
    fn degenerate_boundary_has_zero_area() {
        assert_eq!(rect_site(0.0, 0.0).area(), 0.0);
    }

    #[test]
    fn brief_gross_floor_area() {
        let brief = ProgramBrief {
            unit_count: 4,
            target_unit_sqm: 148.6, // ~1600 sqft
            parking_spaces: 6,
            storeys: Some(2),
        };
        assert!((brief.gross_floor_area() - 594.4).abs() < 1e-3);
    }

    #[test]
    fn regime_input_round_trips_json() {
        let input = RegimeInput {
            site: rect_site(15.0, 30.0),
            brief: ProgramBrief {
                unit_count: 2,
                target_unit_sqm: 120.0,
                parking_spaces: 4,
                storeys: None,
            },
            answers: vec![Answer {
                key: "construction".into(),
                value: "stick".into(),
            }],
        };
        let json = serde_json::to_string(&input).unwrap();
        let back: RegimeInput = serde_json::from_str(&json).unwrap();
        assert_eq!(input, back);
    }
}
