//! OBC 9.8 — stairs serving a single dwelling unit (private stairs).
//!
//! Pure rule geometry: given a floor-to-floor height, how many risers and
//! treads, the rise and run, and whether a candidate stair's rise/run/width
//! comply with Part 9. The *shape* (straight vs switchback) and *placement*
//! are the solver's job; this module answers "what does the code require, and
//! does this comply" — the same split the detector / window / electrical rule
//! modules use.

use crate::report::{ComplianceCheck, ComplianceStatus};

/// Maximum riser height, private stair (OBC 9.8.4.2, "stairs … serving a
/// single dwelling unit").
pub const MAX_RISER_MM: f32 = 200.0;
/// Minimum riser height (OBC 9.8.4.2).
pub const MIN_RISER_MM: f32 = 125.0;
/// Minimum tread run, private stair (OBC 9.8.4.2).
pub const MIN_RUN_MM: f32 = 255.0;
/// Maximum tread run (OBC 9.8.4.2).
pub const MAX_RUN_MM: f32 = 355.0;
/// Minimum clear width of a stair serving a single dwelling unit
/// (OBC 9.8.2.1).
pub const MIN_WIDTH_MM: f32 = 860.0;
/// Minimum headroom measured vertically over a stair within a dwelling unit
/// (OBC 9.8.2.2).
pub const MIN_HEADROOM_MM: f32 = 1950.0;
/// A handrail is required on at least one side of a stair with this many or
/// more risers (OBC 9.8.7.1).
pub const HANDRAIL_RISER_THRESHOLD: u32 = 3;

/// Solved riser/tread geometry for the flight system spanning one storey.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct StairSpec {
    /// Number of equal risers between the two finished floors.
    pub num_risers: u32,
    /// Number of treads — one fewer than the risers (the top riser arrives at
    /// the floor above, which is not itself a tread).
    pub num_treads: u32,
    /// Actual rise of each riser (mm) — the floor-to-floor height divided
    /// equally among the risers.
    pub riser_height_mm: f32,
    /// Tread run / going (mm).
    pub tread_run_mm: f32,
    /// Floor-to-floor height this spec spans (mm).
    pub floor_to_floor_mm: f32,
}

impl StairSpec {
    /// Total horizontal run of a single straight flight (treads × run).
    #[must_use]
    pub fn total_run_mm(&self) -> f32 {
        #[allow(clippy::cast_precision_loss)]
        let treads = self.num_treads as f32;
        treads * self.tread_run_mm
    }

    /// Whether a handrail is required (≥ 3 risers, OBC 9.8.7.1).
    #[must_use]
    pub fn requires_handrail(&self) -> bool {
        self.num_risers >= HANDRAIL_RISER_THRESHOLD
    }
}

/// Solve the rise/run for a storey height: the fewest equal risers that keep
/// each rise at or under the 200 mm private-stair maximum, with treads at the
/// code-minimum run (the most compact compliant going). One fewer tread than
/// risers — the top riser lands on the floor above.
///
/// `floor_to_floor_mm` is the finished-floor to finished-floor height.
#[must_use]
pub fn solve_stair(floor_to_floor_mm: f32) -> StairSpec {
    let h = floor_to_floor_mm.max(1.0);
    #[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)]
    let n = ((h / MAX_RISER_MM).ceil() as u32).max(1);
    #[allow(clippy::cast_precision_loss)]
    let riser = h / n as f32;
    StairSpec {
        num_risers: n,
        num_treads: n.saturating_sub(1),
        riser_height_mm: riser,
        tread_run_mm: MIN_RUN_MM,
        floor_to_floor_mm: h,
    }
}

/// Compliance checks for a solved stair plus its actual clear width
/// (OBC 9.8). Returns one [`ComplianceCheck`] per rule: riser height, tread
/// run, clear width, handrail, and a headroom design-assumption note (the
/// 1950 mm clearance is verified on the section, not the plan). The caller
/// rolls these into a [`crate::ComplianceReport`].
#[must_use]
pub fn check_stair(spec: &StairSpec, width_clear_mm: f32) -> Vec<ComplianceCheck> {
    use ComplianceStatus::{Fail, NotApplicable, Pass};
    const EPS: f32 = 0.5;

    let riser_ok =
        spec.riser_height_mm <= MAX_RISER_MM + EPS && spec.riser_height_mm >= MIN_RISER_MM - EPS;
    let run_ok = spec.tread_run_mm >= MIN_RUN_MM - EPS;
    let width_ok = width_clear_mm >= MIN_WIDTH_MM - EPS;

    let mut checks = vec![
        ComplianceCheck {
            rule_name: "Riser height".into(),
            code_section: "OBC 9.8.4.2".into(),
            status: if riser_ok { Pass } else { Fail },
            requirement: format!("{MIN_RISER_MM:.0}–{MAX_RISER_MM:.0} mm"),
            actual: format!("{:.0} mm × {} risers", spec.riser_height_mm, spec.num_risers),
            message: if riser_ok {
                "Equal risers within the private-stair range".into()
            } else {
                "Rise outside 125–200 mm — adjust riser count or storey height".into()
            },
        },
        ComplianceCheck {
            rule_name: "Tread run".into(),
            code_section: "OBC 9.8.4.2".into(),
            status: if run_ok { Pass } else { Fail },
            requirement: format!("≥ {MIN_RUN_MM:.0} mm"),
            actual: format!("{:.0} mm × {} treads", spec.tread_run_mm, spec.num_treads),
            message: if run_ok {
                "Going meets the private-stair minimum".into()
            } else {
                "Run below 255 mm — deepen the stair or add a landing".into()
            },
        },
        ComplianceCheck {
            rule_name: "Clear width".into(),
            code_section: "OBC 9.8.2.1".into(),
            status: if width_ok { Pass } else { Fail },
            requirement: format!("≥ {MIN_WIDTH_MM:.0} mm"),
            actual: format!("{width_clear_mm:.0} mm"),
            message: if width_ok {
                "Clear width meets the single-dwelling minimum".into()
            } else {
                "Stair narrower than 860 mm — widen the stair well".into()
            },
        },
    ];

    if spec.requires_handrail() {
        checks.push(ComplianceCheck {
            rule_name: "Handrail".into(),
            code_section: "OBC 9.8.7.1".into(),
            status: Pass,
            requirement: "≥ 1 side (3+ risers)".into(),
            actual: format!("{} risers", spec.num_risers),
            message: "Handrail required on at least one side; see notes".into(),
        });
    }

    checks.push(ComplianceCheck {
        rule_name: "Headroom".into(),
        code_section: "OBC 9.8.2.2".into(),
        status: NotApplicable,
        requirement: format!("≥ {MIN_HEADROOM_MM:.0} mm"),
        actual: "verify on section".into(),
        message: "Floor-opening headroom is confirmed on the building section".into(),
    });

    checks
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ten_foot_storey_solves_to_sixteen_compliant_risers() {
        // 10 ft floor-to-floor = 3048 mm.
        let spec = solve_stair(3048.0);
        assert_eq!(spec.num_risers, 16);
        assert_eq!(spec.num_treads, 15);
        // 3048 / 16 = 190.5 mm — under the 200 mm max.
        assert!((spec.riser_height_mm - 190.5).abs() < 0.1);
        assert!(spec.riser_height_mm <= MAX_RISER_MM);
        assert!(spec.requires_handrail());
    }

    #[test]
    fn riser_count_is_minimal_under_the_max() {
        // Fewest risers keeping rise ≤ 200: dropping one would exceed it.
        let spec = solve_stair(3048.0);
        #[allow(clippy::cast_precision_loss)]
        let one_fewer = spec.floor_to_floor_mm / (spec.num_risers as f32 - 1.0);
        assert!(one_fewer > MAX_RISER_MM, "one fewer riser would exceed 200 mm");
    }

    #[test]
    fn total_run_is_treads_times_going() {
        let spec = solve_stair(3048.0);
        // 15 treads × 255 mm.
        assert!((spec.total_run_mm() - 15.0 * 255.0).abs() < 0.1);
    }

    #[test]
    fn compliant_stair_passes_every_check() {
        let spec = solve_stair(3048.0);
        // A tight-but-legal switchback flight in a 6 ft well: ~864 mm clear.
        let checks = check_stair(&spec, 864.0);
        assert!(checks.iter().all(|c| c.status != ComplianceStatus::Fail));
        assert!(checks.iter().any(|c| c.rule_name == "Riser height" && c.status == ComplianceStatus::Pass));
        assert!(checks.iter().any(|c| c.rule_name == "Clear width" && c.status == ComplianceStatus::Pass));
    }

    #[test]
    fn narrow_stair_fails_width_check() {
        let spec = solve_stair(3048.0);
        let checks = check_stair(&spec, 700.0);
        let width = checks.iter().find(|c| c.rule_name == "Clear width").unwrap();
        assert_eq!(width.status, ComplianceStatus::Fail);
    }

    #[test]
    fn headroom_is_a_section_assumption_not_a_failure() {
        let spec = solve_stair(3048.0);
        let checks = check_stair(&spec, 900.0);
        let hr = checks.iter().find(|c| c.rule_name == "Headroom").unwrap();
        assert_eq!(hr.status, ComplianceStatus::NotApplicable);
    }

    #[test]
    fn tiny_height_still_yields_a_stair() {
        let spec = solve_stair(0.0);
        assert!(spec.num_risers >= 1);
    }
}
