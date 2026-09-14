//! Sudbury Zoning By-law 2010-100Z implementation
//! Source: https://greaterSudbury.ca/bylaws

use crate::{Constraint, ConstraintType, Regime};

pub fn get_r1_regime() -> Regime {
    let mut regime = Regime::new("R1");
    
    // Max height: 10m (3 storeys typically)
    regime.add(ConstraintType::HeightMax, 10.0, "m", "Max building height");
    
    // Front setback: 6.0m
    regime.add(ConstraintType::SetbackFront, 6.0, "m", "Front yard setback");
    
    // Rear setback: 7.5m
    regime.add(ConstraintType::SetbackRear, 7.5, "m", "Rear yard setback");
    
    // Side setback: 1.2m
    regime.add(ConstraintType::SetbackSide, 1.2, "m", "Side yard setback");
    
    // Max coverage: 35%
    regime.add(ConstraintType::CoverageMax, 35.0, "%", "Max lot coverage");
    
    // Max FSR: 0.50
    regime.add(ConstraintType::FSRMax, 0.50, "", "Max Floor Space Ratio");
    
    regime
}

pub fn get_r2_regime() -> Regime {
    let mut regime = Regime::new("R2");
    
    // Max height: 11m
    regime.add(ConstraintType::HeightMax, 11.0, "m", "Max building height");
    
    // Front setback: 6.0m
    regime.add(ConstraintType::SetbackFront, 6.0, "m", "Front yard setback");
    
    // Rear setback: 7.5m
    regime.add(ConstraintType::SetbackRear, 7.5, "m", "Rear yard setback");
    
    // Side setback: 1.5m
    regime.add(ConstraintType::SetbackSide, 1.5, "m", "Side yard setback");
    
    // Max coverage: 40%
    regime.add(ConstraintType::CoverageMax, 40.0, "%", "Max lot coverage");
    
    // Max FSR: 0.70 (typical for R2)
    regime.add(ConstraintType::FSRMax, 0.70, "", "Max Floor Space Ratio");
    
    regime
}

pub fn get_regime_by_name(zone: &str) -> Option<Regime> {
    match zone.to_uppercase().as_str() {
        "R1" => Some(get_r1_regime()),
        "R2" => Some(get_r2_regime()),
        _ => None,
    }
}
