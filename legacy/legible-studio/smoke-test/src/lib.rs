//! End-to-end smoke test — pure Rust, no Python.
//!
//! Replaces `python smoke_test.py --use-rust` with a hermetic Rust test
//! that exercises the full pipeline: Answers → building JSON →
//! SchemaDocument → documentation bundle → SVG + PDF sheets.
//!
//! Run: `cargo test --release --test smoke_test -- --nocapture`

use std::path::PathBuf;
use std::time::Instant;

// ---------------------------------------------------------------------------
// Stage helpers
// ---------------------------------------------------------------------------

fn elapsed(start: Instant) -> String {
    format!("{:.1}ms", start.elapsed().as_secs_f64() * 1000.0)
}

fn library_path() -> PathBuf {
    // CARGO_MANIFEST_DIR is rust/smoke-test/; tables live two levels up in rust/OBC_Library
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .join("OBC_Library")
}

// ---------------------------------------------------------------------------
// 1. Synthesize answers
// ---------------------------------------------------------------------------

fn small_answers() -> solver::Answers {
    solver::Answers {
        bedrooms: 1,
        bathrooms: 1,
        sqft: 800.0,
        garage: "none".into(),
        storeys: 1,
        window_intent: "balanced".into(),
        style: "ranch".into(),
        ..Default::default()
    }
}

fn large_answers() -> solver::Answers {
    solver::Answers {
        bedrooms: 3,
        bathrooms: 3,
        sqft: 1800.0,
        garage: "2car".into(),
        storeys: 0, // auto → 2 (3+ bedrooms)
        window_intent: "balanced".into(),
        style: "ranch".into(),
        ..Default::default()
    }
}

// ---------------------------------------------------------------------------
// 2. Solver → building JSON
// ---------------------------------------------------------------------------

fn stage_solve(answers: &solver::Answers) -> serde_json::Value {
    let t0 = Instant::now();
    let value = solver::building_json(answers);
    println!("  [solver] building_id={} walls={} doors={} windows={} detectors={} electrical={} ({})",
        value["building_id"].as_str().unwrap_or("?"),
        value["summary"]["total_walls"].as_u64().unwrap_or(0),
        value["summary"]["doors"].as_u64().unwrap_or(0),
        value["summary"]["windows"].as_u64().unwrap_or(0),
        value["summary"]["detectors"].as_u64().unwrap_or(0),
        value["summary"]["electrical"].as_u64().unwrap_or(0),
        elapsed(t0)
    );
    value
}

// ---------------------------------------------------------------------------
// 3. Parse JSON → SchemaDocument
// ---------------------------------------------------------------------------

fn stage_parse(value: &serde_json::Value) -> archgeometry::SchemaDocument {
    let t0 = Instant::now();
    let json = serde_json::to_string(value).expect("serde_json round-trip");
    let doc = archgeometry::parse_json(&json).expect("schema parse");
    println!("  [parse]  rooms={} walls={} doors={} windows={} ({})",
        doc.rooms.len(), doc.walls.len(), doc.doors.len(), doc.windows.len(),
        elapsed(t0)
    );
    doc
}

// ---------------------------------------------------------------------------
// 4. Generate documentation bundle
// ---------------------------------------------------------------------------

fn stage_documentation(
    doc: &archgeometry::SchemaDocument,
    validation: &qbd::ValidationResult,
) -> qbd::Documentation {
    let t0 = Instant::now();
    let docs = qbd::generate_documentation_with_validation(doc, "Smoke Test", validation);
    let sheet_count = 1 + 1 + docs.floor_plans.len() + docs.elevations.len() + 1
        + docs.wall_details.len()
        + (if docs.door_schedule_svg.is_empty() { 0 } else { 1 })
        + (if docs.window_schedule_svg.is_empty() { 0 } else { 1 })
        + (if docs.compliance_report_svg.is_empty() { 0 } else { 1 });
    println!("  [docs]   {} sheets: site + roof + {} floor + {} elev + section + {} details + {} schedules + {} report ({})",
        sheet_count,
        docs.floor_plans.len(),
        docs.elevations.len(),
        docs.wall_details.len(),
        (if docs.door_schedule_svg.is_empty() { 0 } else { 1 })
            + (if docs.window_schedule_svg.is_empty() { 0 } else { 1 }),
        if docs.compliance_report_svg.is_empty() { 0 } else { 1 },
        elapsed(t0)
    );
    docs
}

// ---------------------------------------------------------------------------
// 5. Validate against OBC
// ---------------------------------------------------------------------------

fn stage_validate(doc: &archgeometry::SchemaDocument) -> qbd::ValidationResult {
    let t0 = Instant::now();
    let mut obc = obc::OBCEngine::new();
    obc.initialize(&library_path()).expect("OBC tables must load");
    let result = qbd::validate_layout(&obc, doc, "Zone 6");
    println!("  [obc]    walls={}/{} passed thermal={} ({})",
        result.walls_passed, result.walls_checked,
        if result.thermal_compliance { "PASS" } else { "FAIL" },
        elapsed(t0)
    );
    result
}

// ---------------------------------------------------------------------------
// 6. Convert one sheet to PDF
// ---------------------------------------------------------------------------

fn stage_pdf(docs: &qbd::Documentation) {
    let t0 = Instant::now();
    let pdf = qbd::svg_to_pdf(&docs.floor_plan_svg).expect("PDF conversion");
    println!("  [pdf]    floor_plan.pdf {} bytes ({})", pdf.len(), elapsed(t0));
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[test]
fn smoke_small_building() {
    println!("\n=== smoke_small_building ===");
    let t_total = Instant::now();

    let answers = small_answers();
    let value = stage_solve(&answers);

    // Assertions on the raw JSON.
    assert!(value["success"].as_bool().unwrap_or(false));
    assert_eq!(value["storeys"].as_u64(), Some(1));
    assert!(value["detectors"].as_array().map_or(false, |a| !a.is_empty()));
    assert!(value["electrical"].as_array().map_or(false, |a| !a.is_empty()));

    let doc = stage_parse(&value);
    let validation = stage_validate(&doc);
    let docs = stage_documentation(&doc, &validation);
    stage_pdf(&docs);

    // SVG well-formedness.
    assert!(docs.floor_plan_svg.starts_with("<?xml"));
    assert!(docs.floor_plan_svg.contains("</svg>"));
    assert!(docs.site_plan_svg.contains("</svg>"));
    assert!(docs.section_svg.contains("</svg>"));
    assert!(
        docs.foundation_plan_svg.contains("</svg>"),
        "foundation plan must be generated"
    );
    assert!(
        docs.foundation_plan_svg.contains("FOUNDATION PLAN"),
        "foundation plan must have title block"
    );
    assert!(
        docs.compliance_report_svg.contains("</svg>"),
        "compliance report must be generated"
    );
    assert!(
        docs.compliance_report_svg.contains("CODE COMPLIANCE REPORT"),
        "compliance report must have title"
    );
    assert!(
        docs.compliance_report_svg.contains("WALLS CHECKED"),
        "compliance report must show wall check summary"
    );
    assert!(
        docs.framing_plan_svg.contains("</svg>"),
        "framing plan must be generated"
    );
    assert!(
        docs.framing_plan_svg.contains("FRAMING PLAN"),
        "framing plan must have title block"
    );
    assert!(
        docs.framing_plan_svg.contains("FLOOR JOISTS"),
        "framing plan legend missing"
    );
    assert!(
        docs.footing_detail_svg.contains("</svg>"),
        "footing detail must be generated"
    );
    assert!(
        docs.footing_detail_svg.contains("TYPICAL FOOTING DETAIL"),
        "footing detail must have title text"
    );
    assert!(
        docs.footing_detail_svg.contains("2-15M"),
        "footing detail must carry rebar callout"
    );
    // OBC general-notes block must appear on the floor plan with both
    // required code sections (Phase 2.4).
    assert!(
        docs.floor_plan_svg.contains("obc-notes"),
        "OBC notes block must be injected on the floor plan"
    );
    assert!(
        docs.floor_plan_svg.contains("9.10.19"),
        "OBC smoke-alarm note reference missing"
    );
    assert!(
        docs.floor_plan_svg.contains("9.33.4"),
        "OBC CO-alarm note reference missing"
    );
    // Phase 2.5 — cross-sheet references.
    assert!(
        docs.floor_plan_svg.contains("section-marker"),
        "section cut marker must be injected on the floor plan"
    );
    assert!(
        docs.floor_plan_svg.contains(">A-301</text>"),
        "section marker must reference the section sheet number"
    );
    // Level markers on at least one elevation.
    let first_elev_svg = &docs.elevations[0].svg;
    assert!(
        first_elev_svg.contains("level-markers"),
        "elevation must include level-markers group"
    );
    assert!(
        first_elev_svg.contains("T.O. FOUNDATION"),
        "elevation must label T.O. FOUNDATION"
    );
    assert!(
        first_elev_svg.contains("T.O. PLATE"),
        "elevation must label T.O. PLATE"
    );

    // Detectors rendered on floor plan.
    let detector_count = docs.floor_plan_svg.matches("fill=\"#c00\">S</text>").count();
    assert!(detector_count > 0, "smoke detectors must appear on floor plan");

    // Elevations: one per direction.
    assert_eq!(docs.elevations.len(), 4, "N/S/E/W elevations required");

    // Wall details: at least exterior + interior.
    assert!(
        docs.wall_details.len() >= 1,
        "at least one wall detail expected"
    );

    // OBC validation ran.
    assert_eq!(validation.walls_checked, doc.walls.len() as i32);

    println!("  TOTAL    {}", elapsed(t_total));
}

#[test]
fn smoke_large_building() {
    println!("\n=== smoke_large_building ===");
    let t_total = Instant::now();

    let answers = large_answers();
    let value = stage_solve(&answers);

    // Auto-storeys: 3 bedrooms → 2 storeys.
    assert_eq!(value["storeys"].as_u64(), Some(2));

    let doc = stage_parse(&value);
    let validation = stage_validate(&doc);
    let docs = stage_documentation(&doc, &validation);
    stage_pdf(&docs);

    // Multi-storey: floor plan per level.
    assert!(
        docs.floor_plans.len() >= 2,
        "2-storey building needs ≥2 floor plans"
    );

    println!("  TOTAL    {}", elapsed(t_total));
}

#[test]
fn smoke_pdf_conversion_for_every_sheet() {
    println!("\n=== smoke_pdf_conversion_for_every_sheet ===");
    let answers = small_answers();
    let value = stage_solve(&answers);
    let doc = stage_parse(&value);
    let validation = stage_validate(&doc);
    let docs = stage_documentation(&doc, &validation);

    let mut sheets: Vec<(&str, &str)> = vec![
        ("site_plan", &docs.site_plan_svg),
        ("roof_plan", &docs.roof_plan_svg),
        ("floor_plan", &docs.floor_plan_svg),
        ("section", &docs.section_svg),
    ];
    for e in &docs.elevations {
        let name = match e.direction {
            drawing::ElevationDirection::North => "elevation_north",
            drawing::ElevationDirection::South => "elevation_south",
            drawing::ElevationDirection::East => "elevation_east",
            drawing::ElevationDirection::West => "elevation_west",
        };
        sheets.push((name, &e.svg));
    }

    let mut total_bytes = 0usize;
    for (name, svg) in &sheets {
        let pdf = qbd::svg_to_pdf(svg).unwrap_or_else(|e| panic!("{name} PDF failed: {e}"));
        assert!(!pdf.is_empty(), "{name} PDF must not be empty");
        total_bytes += pdf.len();
        println!("  {name:20} PDF {} bytes", pdf.len());
    }
    println!("  TOTAL PDFs: {} sheets, {} bytes", sheets.len(), total_bytes);
}

// ---------------------------------------------------------------------------
// Part 3 / mixed-mode smoke tests
// ---------------------------------------------------------------------------

fn stage_solve_manifest(manifest: &solver::ProgramManifest) -> serde_json::Value {
    let t0 = Instant::now();
    let value = solver::building_json_from_manifest(manifest);
    println!(
        "  [solver] building_id={} mode={} storeys={} walls={} ({})",
        value["building_id"].as_str().unwrap_or("?"),
        value["qbd_answers"]["mode"].as_str().unwrap_or("?"),
        value["storeys"].as_u64().unwrap_or(0),
        value["summary"]["total_walls"].as_u64().unwrap_or(0),
        elapsed(t0)
    );
    value
}

fn stage_validate_part3(doc: &archgeometry::SchemaDocument) -> qbd::ValidationResult {
    let t0 = Instant::now();
    let mut obc = obc::OBCEngine::new();
    obc.initialize(&library_path()).expect("OBC Part 9 tables must load");
    let mut part3 = obc::Part3Engine::new();
    part3
        .initialize(&library_path())
        .expect("OBC Part 3 tables must load");
    let result = qbd::validate_layout_with_part3(&obc,
        Some(&part3),
        doc,
        "Zone 6",
    );
    let p3_summary = if result.part3_reports.is_empty() {
        "no Part 3 report".into()
    } else {
        format!(
            "{} Part 3 report(s), {}",
            result.part3_reports.len(),
            if result.part3_reports.iter().all(|r| r.passes()) {
                "PASS"
            } else {
                "FAIL"
            }
        )
    };
    println!(
        "  [obc]    walls={}/{} passed thermal={} {} ({})",
        result.walls_passed,
        result.walls_checked,
        if result.thermal_compliance { "PASS" } else { "FAIL" },
        p3_summary,
        elapsed(t0)
    );
    result
}

fn part3_report_has_category(result: &qbd::ValidationResult, needle: &str) -> bool {
    result.part3_reports.iter().any(|report| {
        report
            .checks
            .iter()
            .any(|check| check.code_section.contains(needle) || check.rule_name.contains(needle))
    })
}

#[test]
fn smoke_part3_small_office() {
    println!("\n=== smoke_part3_small_office ===");
    let t_total = Instant::now();

    let manifest = solver::BuildingTemplate::SmallOffice {
        storeys: 2,
        sqft: 6000.0,
    }
    .manifest();
    let value = stage_solve_manifest(&manifest);
    assert_eq!(value["qbd_answers"]["mode"].as_str(), Some("part3"));

    let doc = stage_parse(&value);
    let validation = stage_validate_part3(&doc);

    assert!(
        !validation.part3_reports.is_empty(),
        "Part 3 report must be generated"
    );
    assert!(
        part3_report_has_category(&validation, "3.2.2.1"),
        "Part 3 area/height checks expected"
    );
    assert!(
        part3_report_has_category(&validation, "3.4.2.5"),
        "Part 3 egress travel-distance checks expected"
    );
    assert!(
        part3_report_has_category(&validation, "3.4.6"),
        "Part 3 public-stair checks expected"
    );
    assert!(
        validation.overall_pass,
        "small office should pass Part 3 validation"
    );

    println!("  TOTAL    {}", elapsed(t_total));
}

#[test]
fn smoke_part3_mixed_use_podium() {
    println!("\n=== smoke_part3_mixed_use_podium ===");
    let t_total = Instant::now();

    let manifest = solver::BuildingTemplate::MixedUsePodium {
        retail_sqft: 3000.0,
        residential_floors: 2,
    }
    .manifest();
    let value = stage_solve_manifest(&manifest);
    assert_eq!(value["qbd_answers"]["mode"].as_str(), Some("mixed"));

    let doc = stage_parse(&value);
    let validation = stage_validate_part3(&doc);

    assert!(
        !validation.part3_reports.is_empty(),
        "Part 3 report must be generated for mixed mode"
    );
    assert!(
        part3_report_has_category(&validation, "3.2.2.1"),
        "Part 3 area/height checks expected"
    );
    assert!(
        part3_report_has_category(&validation, "3.4.2.5"),
        "Part 3 egress checks expected"
    );
    assert!(
        validation.overall_pass,
        "mixed-use podium should pass Part 3 validation"
    );

    println!("  TOTAL    {}", elapsed(t_total));
}

#[test]
fn smoke_part3_college_residence() {
    println!("\n=== smoke_part3_college_residence ===");
    let t_total = Instant::now();

    let manifest = solver::BuildingTemplate::CollegeResidence {
        floors: 3,
        rooms_per_floor: 10,
        sqft: 15_000.0,
    }
    .manifest();
    let value = stage_solve_manifest(&manifest);
    assert_eq!(value["qbd_answers"]["mode"].as_str(), Some("part3"));

    let doc = stage_parse(&value);
    let validation = stage_validate_part3(&doc);

    assert!(
        !validation.part3_reports.is_empty(),
        "Part 3 report must be generated for college residence"
    );
    assert!(
        part3_report_has_category(&validation, "3.4.2.5"),
        "Part 3 egress checks expected for dorm floors"
    );
    assert!(
        validation.overall_pass,
        "college residence should pass Part 3 validation"
    );

    println!("  TOTAL    {}", elapsed(t_total));
}
