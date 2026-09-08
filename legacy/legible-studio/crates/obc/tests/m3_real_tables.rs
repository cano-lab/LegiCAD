//! Milestone M3: load the real OBC tables from disk and verify a few
//! known span values plus end-to-end joist / stud / header validation.
//!
//! Byte-for-byte cross-language diff against the C++ kernel is left as
//! future work — the kernel doesn't ship a standalone `obc_dump` tool
//! like the archgeometry side does. These tests assert the values
//! match the canonical OBC tables, which is the M3 acceptance bar.

use obc::{ComplianceStatus, OBCEngine};
use std::path::PathBuf;

fn library_path() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .join("OBC_Library")
}

fn initialised_engine() -> OBCEngine {
    let mut engine = OBCEngine::new();
    engine
        .initialize(&library_path())
        .expect("OBC tables must load from OBC_Library");
    assert!(engine.is_initialized());
    engine
}

#[test]
fn loads_joist_table_with_known_spans() {
    let e = initialised_engine();
    // From obc_9.23_joists.json (SPF No.2 @ 40 psf):
    //   2x10  spacing_12_span "17-8"  spacing_16_span "16-0"  spacing_24_span "13-2"
    let span12 = e.joist_max_span("SPF", "No.2", "2x10", 12, 40.0).unwrap();
    let span16 = e.joist_max_span("SPF", "No.2", "2x10", 16, 40.0).unwrap();
    let span24 = e.joist_max_span("SPF", "No.2", "2x10", 24, 40.0).unwrap();
    assert!((span12 - (17.0 + 8.0 / 12.0)).abs() < 1e-4);
    assert!((span16 - 16.0).abs() < 1e-4);
    assert!((span24 - (13.0 + 2.0 / 12.0)).abs() < 1e-4);
}

#[test]
fn loads_stud_table_with_known_heights() {
    let e = initialised_engine();
    // From obc_9.23_studs.json (load_bearing_exterior):
    //   2x6  spacing_12 14  spacing_16 12  spacing_24 10  max_stories 2
    let h12 = e.stud_max_height("2x6", 12, true, 1).unwrap();
    let h16 = e.stud_max_height("2x6", 16, true, 1).unwrap();
    let h24 = e.stud_max_height("2x6", 24, true, 1).unwrap();
    assert_eq!(h12, 14.0);
    assert_eq!(h16, 12.0);
    assert_eq!(h24, 10.0);
}

#[test]
fn rejects_studs_beyond_max_stories() {
    let e = initialised_engine();
    // 2x4 max_stories_supported = 1; asking for 2 → None.
    assert!(e.stud_max_height("2x4", 16, true, 2).is_none());
    // 2x6 max_stories_supported = 2; asking for 2 → Some.
    assert!(e.stud_max_height("2x6", 16, true, 2).is_some());
}

#[test]
fn loads_header_table_with_double_ply_default() {
    let e = initialised_engine();
    // From obc_9.23_headers.json (roof_ceiling_only → double_ply_span_ft):
    //   2x10 double_ply_span_ft = 9.0
    // C++ prefixes the size with "2-" for the double-ply default.
    let max = e.header_max_span("2-2x10", 1).unwrap();
    assert_eq!(max, 9.0);
}

#[test]
fn required_joist_size_picks_smallest_fit() {
    let e = initialised_engine();
    // 13 ft span @ 16" oc:
    //   2x6  spacing_16 = 9.5   (too small)
    //   2x8  spacing_16 = 12.5  (too small)
    //   2x10 spacing_16 = 16.0  (fits)
    let size = e
        .required_joist_size("SPF", "No.2", 13.0, 16, 40.0)
        .unwrap();
    assert_eq!(size, "2x10");
}

#[test]
fn required_stud_size_picks_first_satisfying_both_height_and_stories() {
    let e = initialised_engine();
    // 11 ft height, 16" oc, 2 stories:
    //   2x4 height=10 fails on height (10 < 11)
    //   2x6 height=12 ok AND stories=2 ok → fits
    let size = e.required_stud_size(11.0, 16, true, 2).unwrap();
    assert_eq!(size, "2x6");
}

#[test]
fn validate_joist_full_path_passes_for_realistic_design() {
    let e = initialised_engine();
    // 2x10 @ 16" oc, 14 ft span, 40 psf — well within 16 ft max.
    let r = e.validate_joist("SPF", "No.2", "2x10", 14.0, 16, 40.0);
    assert_eq!(r.overall_status, ComplianceStatus::Pass);
    assert_eq!(r.element_type, "joist");
    assert_eq!(r.element_id, "2x10 @ 16\" o.c.");
    assert_eq!(r.checks.len(), 1);
    let check = &r.checks[0];
    assert_eq!(check.rule_name, "Maximum Joist Span");
    assert_eq!(check.code_section, "OBC 9.23.9.2");
    // 6-decimal-place formatting matches std::to_string(float).
    assert_eq!(check.actual, "14.000000 ft");
    assert_eq!(check.requirement, "Max span: 16.000000 ft");
}

#[test]
fn validate_studs_full_path() {
    let e = initialised_engine();
    let r = e.validate_studs("2x6", 9.0, 16, true, 1);
    assert_eq!(r.overall_status, ComplianceStatus::Pass);
    assert_eq!(r.checks.len(), 2);
    // First check: height; second: stories.
    assert_eq!(r.checks[0].rule_name, "Maximum Wall Height");
    assert_eq!(r.checks[1].rule_name, "Stories Supported");
    assert_eq!(r.checks[1].requirement, "1 stor(ies)");
}

#[test]
fn validate_header_for_typical_door_opening() {
    let e = initialised_engine();
    // Standard 3 ft door opening with 2-2x6 header.
    // 2-2x6 max 1-story double_ply span = 5.0 ft (from JSON).
    let r = e.validate_header("2-2x6", 3.0, 1);
    assert_eq!(r.overall_status, ComplianceStatus::Pass);
}
