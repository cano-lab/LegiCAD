//! Regime Engine: Generative constraints for zoning and building codes.
//! Instead of "draw -> check", we do "define constraints -> generate valid masses".

use glam::{Vec2, Vec3};
use serde::{Deserialize, Serialize};

pub mod sudbury;

/// Categories of constraints
#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum ConstraintType {
    SetbackFront,
    SetbackRear,
    SetbackSide,
    HeightMax,
    CoverageMax,
    FSRMax,
    MinFloorArea,
}

/// A single constraint rule
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Constraint {
    pub kind: ConstraintType,
    pub value: f32,
    pub unit: String, // "m", "m2", "%"
    pub description: String,
}

/// A collection of constraints for a specific zone (e.g., R1, R2)
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Regime {
    pub zone_name: String,
    pub constraints: Vec<Constraint>,
}

impl Regime {
    pub fn new(zone_name: &str) -> Self {
        Self {
            zone_name: zone_name.to_string(),
            constraints: Vec::new(),
        }
    }

    pub fn add(&mut self, kind: ConstraintType, value: f32, unit: &str, desc: &str) {
        self.constraints.push(Constraint {
            kind,
            value,
            unit: unit.to_string(),
            description: desc.to_string(),
        });
    }
}

/// Solver to evaluate massing options against a regime
pub struct ConstraintSolver<'a> {
    regime: &'a Regime,
}

impl<'a> ConstraintSolver<'a> {
    pub fn new(regime: &'a Regime) -> Self {
        Self { regime }
    }

    /// Check if a proposed massing footprint satisfies the regime
    pub fn validate_footprint(
        &self,
        lot_width: f32,
        lot_depth: f32,
        footprint_area: f32,
        building_height: f32,
        total_gfa: f32,
    ) -> Result<(), Vec<String>> {
        let mut errors = Vec::new();
        let lot_area = lot_width * lot_depth;

        for constraint in &self.regime.constraints {
            match constraint.kind {
                ConstraintType::HeightMax => {
                    if building_height > constraint.value {
                        errors.push(format!(
                            "Height {}m exceeds max {}m",
                            building_height, constraint.value
                        ));
                    }
                }
                ConstraintType::CoverageMax => {
                    let coverage_pct = (footprint_area / lot_area) * 100.0;
                    if coverage_pct > constraint.value {
                        errors.push(format!(
                            "Coverage {:.1}% exceeds max {:.1}%",
                            coverage_pct, constraint.value
                        ));
                    }
                }
                ConstraintType::FSRMax => {
                    let fsr = total_gfa / lot_area;
                    if fsr > constraint.value {
                        errors.push(format!(
                            "FSR {:.2} exceeds max {:.2}",
                            fsr, constraint.value
                        ));
                    }
                }
                _ => {} // Setbacks handled in geometry generation phase
            }
        }

        if errors.is_empty() {
            Ok(())
        } else {
            Err(errors)
        }
    }
}
