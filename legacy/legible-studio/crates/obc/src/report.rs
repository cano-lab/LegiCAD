//! Compliance status, checks, and reports.
//!
//! Ported from `obc_engine.hpp:17-52`.

use serde::{Deserialize, Serialize};

/// Result status for a compliance check.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
#[repr(u32)]
pub enum ComplianceStatus {
    #[default]
    Pass,
    Fail,
    Warning,
    NotApplicable,
    DataMissing,
}

/// A single compliance check result.
#[derive(Debug, Clone, PartialEq, Default, Serialize, Deserialize)]
pub struct ComplianceCheck {
    /// e.g. `"Maximum Joist Span"`.
    pub rule_name: String,
    /// e.g. `"OBC 9.23.9.2"`.
    pub code_section: String,
    pub status: ComplianceStatus,
    /// What the code requires.
    pub requirement: String,
    /// What the design has.
    pub actual: String,
    /// Human-readable explanation.
    pub message: String,
}

/// Full compliance report for an assembly or element.
#[derive(Debug, Clone, PartialEq, Default, Serialize, Deserialize)]
pub struct ComplianceReport {
    pub element_id: String,
    /// `"joist"`, `"stud"`, `"header"`, `"rafter"`, `"wall_assembly"`.
    pub element_type: String,
    pub checks: Vec<ComplianceCheck>,
    pub overall_status: ComplianceStatus,
}

impl ComplianceReport {
    #[must_use]
    pub fn passes(&self) -> bool {
        self.overall_status == ComplianceStatus::Pass
    }

    /// Count checks with the given status.
    #[must_use]
    pub fn count_by_status(&self, status: ComplianceStatus) -> usize {
        self.checks.iter().filter(|c| c.status == status).count()
    }

    /// Derive overall status from individual check statuses. Matches the
    /// C++ rollup in `validateJoist` etc. (`obc_engine.cpp:446`):
    /// - Any `Fail` → `Fail`
    /// - Else any `Warning` → `Warning`
    /// - Otherwise → `Pass`.
    pub fn compute_overall_status(&mut self) {
        let mut status = ComplianceStatus::Pass;
        for check in &self.checks {
            if check.status == ComplianceStatus::Fail {
                status = ComplianceStatus::Fail;
                break;
            }
            if check.status == ComplianceStatus::Warning && status != ComplianceStatus::Fail {
                status = ComplianceStatus::Warning;
            }
        }
        self.overall_status = status;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_check(status: ComplianceStatus) -> ComplianceCheck {
        ComplianceCheck {
            status,
            ..Default::default()
        }
    }

    #[test]
    fn empty_report_passes() {
        let r = ComplianceReport::default();
        assert!(r.passes());
    }

    #[test]
    fn count_by_status_works() {
        let r = ComplianceReport {
            checks: vec![
                make_check(ComplianceStatus::Pass),
                make_check(ComplianceStatus::Fail),
                make_check(ComplianceStatus::Pass),
                make_check(ComplianceStatus::Warning),
            ],
            ..Default::default()
        };
        assert_eq!(r.count_by_status(ComplianceStatus::Pass), 2);
        assert_eq!(r.count_by_status(ComplianceStatus::Fail), 1);
        assert_eq!(r.count_by_status(ComplianceStatus::Warning), 1);
    }

    #[test]
    fn overall_fail_dominates_warning_and_pass() {
        let mut r = ComplianceReport {
            checks: vec![
                make_check(ComplianceStatus::Pass),
                make_check(ComplianceStatus::Warning),
                make_check(ComplianceStatus::Fail),
            ],
            ..Default::default()
        };
        r.compute_overall_status();
        assert_eq!(r.overall_status, ComplianceStatus::Fail);
    }

    #[test]
    fn overall_warning_when_no_fail() {
        let mut r = ComplianceReport {
            checks: vec![
                make_check(ComplianceStatus::Pass),
                make_check(ComplianceStatus::Warning),
                make_check(ComplianceStatus::Pass),
            ],
            ..Default::default()
        };
        r.compute_overall_status();
        assert_eq!(r.overall_status, ComplianceStatus::Warning);
    }

    #[test]
    fn overall_pass_when_all_pass() {
        let mut r = ComplianceReport {
            checks: vec![
                make_check(ComplianceStatus::Pass),
                make_check(ComplianceStatus::Pass),
            ],
            ..Default::default()
        };
        r.compute_overall_status();
        assert_eq!(r.overall_status, ComplianceStatus::Pass);
    }

    #[test]
    fn status_round_trips_json() {
        let s = serde_json::to_string(&ComplianceStatus::DataMissing).unwrap();
        assert_eq!(s, "\"data_missing\"");
        let back: ComplianceStatus = serde_json::from_str(&s).unwrap();
        assert_eq!(back, ComplianceStatus::DataMissing);
    }
}
