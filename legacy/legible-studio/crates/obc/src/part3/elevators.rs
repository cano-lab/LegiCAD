//! Part 3 elevator requirements (OBC 3.5).
//!
//! v1 rule: buildings with 4 or more storeys, or occupancies that serve persons
//! with disabilities (care / residential), require at least one passenger
//! elevator. The check is triggered per building based on overall storey count
//! and the presence of elevator rooms.

use crate::report::{ComplianceCheck, ComplianceStatus};

/// Verify that the building has the required number of elevators.
#[must_use]
pub fn check_elevators(storey_count: usize, elevator_centroids: &[(f32, f32)]) -> Vec<ComplianceCheck> {
    let mut out = Vec::new();
    if storey_count >= 4 {
        let required = 1;
        let actual = elevator_centroids.len();
        let pass = actual >= required;
        out.push(ComplianceCheck {
            rule_name: "OBC 3.5.2 passenger elevator".into(),
            code_section: "OBC 3.5.2".into(),
            status: if pass { ComplianceStatus::Pass } else { ComplianceStatus::Fail },
            actual: format!("{} elevator{}", actual, if actual == 1 { "" } else { "s" }),
            requirement: format!(
                ">= {} elevator{} for a {}-storey building",
                required,
                if required == 1 { "" } else { "s" },
                storey_count
            ),
            message: "Residential buildings 4+ storeys require a passenger elevator.".into(),
        });
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn three_storey_building_needs_no_elevator() {
        let checks = check_elevators(3, &[]);
        assert!(checks.is_empty());
    }

    #[test]
    fn six_storey_building_requires_elevator() {
        let checks = check_elevators(6, &[]);
        assert_eq!(checks.len(), 1);
        assert_eq!(checks[0].status, ComplianceStatus::Fail);
        assert!(checks[0].requirement.contains("1 elevator"));
    }

    #[test]
    fn six_storey_with_two_elevators_passes() {
        let checks = check_elevators(6, &[(10.0, 10.0), (20.0, 20.0)]);
        assert_eq!(checks.len(), 1);
        assert_eq!(checks[0].status, ComplianceStatus::Pass);
    }
}
