//! Part 3 public stair dimensional checks (OBC 3.4.6).

use crate::part3::tables::{MajorOccupancy, StairRequirement};
use crate::report::{ComplianceCheck, ComplianceStatus};

/// Default public-stair limits for Business occupancies (OBC 3.4.6).
pub const PUBLIC_MAX_RISER_MM: f32 = 180.0;
pub const PUBLIC_MIN_TREAD_MM: f32 = 280.0;
pub const PUBLIC_MIN_WIDTH_MM: f32 = 1100.0;

/// Solve the rise/run for a public stair: the fewest equal risers that keep
/// each rise at or under `PUBLIC_MAX_RISER_MM`, with treads at the
/// code-minimum going. Reuses the shared [`crate::stairs::StairSpec`] so the
/// drawing and compliance layers can consume it directly.
#[must_use]
pub fn solve_public_stair(floor_to_floor_mm: f32) -> crate::stairs::StairSpec {
    let h = floor_to_floor_mm.max(1.0);
    #[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)]
    let n = ((h / PUBLIC_MAX_RISER_MM).ceil() as u32).max(1);
    #[allow(clippy::cast_precision_loss)]
    let riser = h / n as f32;
    crate::stairs::StairSpec {
        num_risers: n,
        num_treads: n.saturating_sub(1),
        riser_height_mm: riser,
        tread_run_mm: PUBLIC_MIN_TREAD_MM,
        floor_to_floor_mm: h,
    }
}

/// Check each stair against the public stair requirements for the floor's
/// dominant occupancy.
#[must_use]
pub fn check_public_stairs(
    requirements: &std::collections::HashMap<MajorOccupancy, StairRequirement>,
    stairs: &[StairInput],
    occupancy: MajorOccupancy,
) -> Vec<ComplianceCheck> {
    let mut out = Vec::new();
    let req = requirements.get(&occupancy).cloned().unwrap_or(StairRequirement {
        occupancy,
        min_width_mm: 1100.0,
        max_riser_mm: 180.0,
        min_tread_mm: 280.0,
    });
    for stair in stairs {
        let width_ok = stair.width_clear_mm >= req.min_width_mm;
        let riser_ok = stair.riser_height_mm > 0.0 && stair.riser_height_mm <= req.max_riser_mm;
        let tread_ok = stair.tread_run_mm >= req.min_tread_mm;
        let pass = width_ok && riser_ok && tread_ok;
        out.push(ComplianceCheck {
            rule_name: format!("OBC 3.4.6 public stair — {}", stair.id),
            code_section: "OBC 3.4.6".into(),
            status: if pass { ComplianceStatus::Pass } else { ComplianceStatus::Fail },
            actual: format!(
                "width {} mm, riser {} mm, tread {} mm",
                stair.width_clear_mm, stair.riser_height_mm, stair.tread_run_mm
            ),
            requirement: format!(
                "width ≥ {} mm, riser ≤ {} mm, tread ≥ {} mm",
                req.min_width_mm, req.max_riser_mm, req.min_tread_mm
            ),
            message: String::new(),
        });
    }
    out
}

#[derive(Debug, Clone)]
pub struct StairInput {
    pub id: String,
    pub width_clear_mm: f32,
    pub riser_height_mm: f32,
    pub tread_run_mm: f32,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn public_stair_passes_and_fails() {
        let mut req = std::collections::HashMap::new();
        req.insert(
            MajorOccupancy::Business,
            StairRequirement {
                occupancy: MajorOccupancy::Business,
                min_width_mm: 1100.0,
                max_riser_mm: 180.0,
                min_tread_mm: 280.0,
            },
        );
        let stairs = vec![StairInput {
            id: "stairs_1".into(),
            width_clear_mm: 1200.0,
            riser_height_mm: 175.0,
            tread_run_mm: 280.0,
        }];
        let checks = check_public_stairs(&req, &stairs, MajorOccupancy::Business);
        assert_eq!(checks[0].status, ComplianceStatus::Pass);

        let narrow = vec![StairInput {
            id: "stairs_1".into(),
            width_clear_mm: 900.0,
            riser_height_mm: 175.0,
            tread_run_mm: 280.0,
        }];
        let checks_narrow = check_public_stairs(&req, &narrow, MajorOccupancy::Business);
        assert_eq!(checks_narrow[0].status, ComplianceStatus::Fail);
    }

    #[test]
    fn public_stair_tall_riser_fails() {
        let mut req = std::collections::HashMap::new();
        req.insert(
            MajorOccupancy::Business,
            StairRequirement {
                occupancy: MajorOccupancy::Business,
                min_width_mm: 1100.0,
                max_riser_mm: 180.0,
                min_tread_mm: 280.0,
            },
        );
        let tall_riser = vec![StairInput {
            id: "stairs_1".into(),
            width_clear_mm: 1200.0,
            riser_height_mm: 190.0,
            tread_run_mm: 280.0,
        }];
        let checks = check_public_stairs(&req, &tall_riser, MajorOccupancy::Business);
        assert_eq!(checks[0].status, ComplianceStatus::Fail);
    }

    #[test]
    fn solve_public_stair_for_ten_foot_storey() {
        // 10 ft = 3048 mm; max riser 180 mm → 17 risers at ~179.3 mm.
        let spec = solve_public_stair(3048.0);
        assert_eq!(spec.num_risers, 17);
        assert_eq!(spec.num_treads, 16);
        assert!(spec.riser_height_mm <= PUBLIC_MAX_RISER_MM);
        assert!((spec.tread_run_mm - PUBLIC_MIN_TREAD_MM).abs() < 0.1);
    }
}
