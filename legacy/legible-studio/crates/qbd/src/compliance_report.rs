//! Code compliance report SVG renderer.
//!
//! Emits a permit-style compliance report sheet: summary header +
//! wall-by-wall table (status, rule, requirement, actual, message) +
//! thermal aggregate.  Feeds directly into the documentation bundle.

use crate::ValidationResult;
use obc::ComplianceStatus;
use std::fmt::Write as _;

/// One row in the checks table.
#[derive(Debug, Clone, Default)]
struct CheckRow {
    /// First-column label (e.g. `"W3 exterior"` or `"Level 1 (switchback)"`).
    tag: String,
    status: ComplianceStatus,
    rule: String,
    code: String,
    requirement: String,
    actual: String,
    message: String,
}

/// Flatten one report's checks into rows under a shared first-column `tag`.
fn rows_for(report: &obc::ComplianceReport, tag: &str, rows: &mut Vec<CheckRow>) {
    if report.checks.is_empty() {
        rows.push(CheckRow {
            tag: tag.to_string(),
            status: report.overall_status,
            rule: "—".into(),
            code: "—".into(),
            requirement: "—".into(),
            actual: "—".into(),
            message: "No checks performed".into(),
        });
    } else {
        for check in &report.checks {
            rows.push(CheckRow {
                tag: tag.to_string(),
                status: check.status,
                rule: check.rule_name.clone(),
                code: check.code_section.clone(),
                requirement: check.requirement.clone(),
                actual: check.actual.clone(),
                message: check.message.clone(),
            });
        }
    }
}

/// Render a `ValidationResult` to a standalone SVG compliance report.
///
/// Layout:
/// - Title + project name
/// - Summary box (overall, thermal, walls checked/passed/failed)
/// - Wall-by-wall checks table (one row per check, collapsed by wall)
///
/// Page size is fixed at 850×1100 (letter-ish portrait, px) so the title
/// block fit logic in `documentation.rs` can scale it like the site plan.
#[must_use]
#[allow(clippy::too_many_lines)] // SVG layout is clearer flat.
pub fn compliance_report_to_svg(result: &ValidationResult, project_name: &str) -> String {
    // ------------------------------------------------------------------
    // Flatten reports into rows.
    // ------------------------------------------------------------------
    let mut rows: Vec<CheckRow> = Vec::new();
    for (wi, report) in result.wall_reports.iter().enumerate() {
        // First column: "W{idx}" plus the wall category when present.
        let tag = if report.element_id.is_empty() || report.element_id == "—" {
            format!("W{wi}")
        } else {
            format!("W{wi} {}", report.element_id)
        };
        rows_for(report, &tag, &mut rows);
    }
    // Stair checks (OBC 9.8) share the table, tagged by storey + shape.
    for report in &result.stair_reports {
        rows_for(report, &report.element_id, &mut rows);
    }
    // Part 3 checks (area/height, egress, fire separation, public stairs).
    for report in &result.part3_reports {
        rows_for(report, &report.element_id, &mut rows);
    }

    // ------------------------------------------------------------------
    // Layout constants (px, portrait page).
    // ------------------------------------------------------------------
    const PAGE_W: i32 = 850;
    const PAGE_H: i32 = 1100;
    const MARGIN: i32 = 40;
    const ROW_H: i32 = 28;
    const HDR_H: i32 = 36;

    let cols: [(&str, i32); 6] = [
        ("ELEMENT", 120),
        ("STATUS", 75),
        ("RULE", 150),
        ("CODE", 90),
        ("REQUIREMENT / ACTUAL", 235),
        ("NOTES", 150),
    ];
    let table_w: i32 = cols.iter().map(|(_, w)| *w).sum();
    let table_x: i32 = (PAGE_W - table_w) / 2;

    // Summary box height depends on whether we show thermal data.
    let summary_h: i32 = if result.total_exterior_wall_area > 0.0 { 140 } else { 100 };
    let table_y: i32 = MARGIN + 80 + summary_h + 20;
    let table_h: i32 = HDR_H + (rows.len() as i32) * ROW_H;

    // If the table is taller than the page, extend the page height.
    let svg_h: i32 = (table_y + table_h + MARGIN).max(PAGE_H);

    let mut out = String::with_capacity(4096);
    out.push_str("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n");
    let _ = writeln!(
        out,
        "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"{PAGE_W}\" \
         height=\"{svg_h}\" viewBox=\"0 0 {PAGE_W} {svg_h}\">"
    );
    out.push_str("  <rect width=\"100%\" height=\"100%\" fill=\"white\"/>\n");

    // Styles.
    out.push_str("  <style>\n");
    out.push_str("    .title { font-family: Arial, sans-serif; font-size: 22px; font-weight: bold; fill: #333; }\n");
    out.push_str("    .subtitle { font-family: Arial, sans-serif; font-size: 14px; fill: #666; }\n");
    out.push_str("    .summary-box { fill: #f8f8f8; stroke: #ccc; stroke-width: 1; }\n");
    out.push_str("    .summary-label { font-family: Arial, sans-serif; font-size: 12px; fill: #666; }\n");
    out.push_str("    .summary-value { font-family: Arial, sans-serif; font-size: 14px; font-weight: bold; fill: #333; }\n");
    out.push_str("    .pass { fill: #2e7d32; }\n");
    out.push_str("    .fail { fill: #c62828; }\n");
    out.push_str("    .warn { fill: #f9a825; }\n");
    out.push_str("    .na   { fill: #999; }\n");
    out.push_str("    .header { font-family: Arial, sans-serif; font-size: 12px; font-weight: bold; fill: #fff; }\n");
    out.push_str("    .cell { font-family: Arial, sans-serif; font-size: 11px; fill: #333; }\n");
    out.push_str("    .header-bg { fill: #333; }\n");
    out.push_str("    .cell-bg { fill: #fff; }\n");
    out.push_str("    .cell-bg-alt { fill: #f5f5f5; }\n");
    out.push_str("    .border { stroke: #333; stroke-width: 1; fill: none; }\n");
    out.push_str("  </style>\n");

    // Title.
    let _ = writeln!(
        out,
        "  <text x=\"{}\" y=\"{}\" text-anchor=\"middle\" class=\"title\">CODE COMPLIANCE REPORT</text>",
        PAGE_W / 2,
        MARGIN + 30
    );
    let _ = writeln!(
        out,
        "  <text x=\"{}\" y=\"{}\" text-anchor=\"middle\" class=\"subtitle\">{project_name}</text>",
        PAGE_W / 2,
        MARGIN + 55
    );

    // Summary box.
    let sb_x = table_x;
    let sb_y = MARGIN + 70;
    let _ = writeln!(
        out,
        "  <rect x=\"{sb_x}\" y=\"{sb_y}\" width=\"{table_w}\" height=\"{summary_h}\" class=\"summary-box\"/>"
    );

    let overall_class = if result.overall_pass { "pass" } else { "fail" };
    let overall_text = if result.overall_pass { "PASS" } else { "FAIL" };
    let thermal_class = if result.thermal_compliance { "pass" } else { "fail" };
    let thermal_text = if result.thermal_compliance { "PASS" } else { "FAIL" };

    // Summary grid: 2 cols × 3 rows.
    let col1_x = sb_x + 20;
    let col2_x = sb_x + table_w / 2 + 20;
    let mut sy = sb_y + 25;

    let _ = writeln!(
        out,
        "  <text x=\"{col1_x}\" y=\"{sy}\" class=\"summary-label\">OVERALL STATUS</text>"
    );
    let _ = writeln!(
        out,
        "  <text x=\"{col1_x}\" y=\"{}\" class=\"summary-value {overall_class}\">{overall_text}</text>",
        sy + 18
    );
    let _ = writeln!(
        out,
        "  <text x=\"{col2_x}\" y=\"{sy}\" class=\"summary-label\">WALLS CHECKED</text>"
    );
    let _ = writeln!(
        out,
        "  <text x=\"{col2_x}\" y=\"{}\" class=\"summary-value\">{} passed / {} checked</text>",
        sy + 18,
        result.walls_passed,
        result.walls_checked
    );
    sy += 50;

    let _ = writeln!(
        out,
        "  <text x=\"{col1_x}\" y=\"{sy}\" class=\"summary-label\">THERMAL COMPLIANCE</text>"
    );
    let _ = writeln!(
        out,
        "  <text x=\"{col1_x}\" y=\"{}\" class=\"summary-value {thermal_class}\">{thermal_text}  (R-{:.1})</text>",
        sy + 18,
        result.average_r_value
    );

    if result.total_exterior_wall_area > 0.0 {
        let area_m2 = result.total_exterior_wall_area / 1_000_000.0;
        let _ = writeln!(
            out,
            "  <text x=\"{col2_x}\" y=\"{sy}\" class=\"summary-label\">EXTERIOR WALL AREA</text>"
        );
        let _ = writeln!(
            out,
            "  <text x=\"{col2_x}\" y=\"{}\" class=\"summary-value\">{area_m2:.1} m²</text>",
            sy + 18
        );
    }

    // Table header.
    let mut y = table_y;
    let _ = writeln!(
        out,
        "  <rect x=\"{table_x}\" y=\"{y}\" width=\"{table_w}\" height=\"{HDR_H}\" class=\"header-bg\"/>"
    );
    let mut x = table_x;
    for (header, width) in cols {
        let cx = x + width / 2;
        let cy = y + HDR_H / 2 + 4;
        let _ = writeln!(
            out,
            "  <text x=\"{cx}\" y=\"{cy}\" text-anchor=\"middle\" class=\"header\">{header}</text>"
        );
        x += width;
    }
    y += HDR_H;

    // Data rows.
    for (i, row) in rows.iter().enumerate() {
        let bg_class = if i % 2 == 1 { "cell-bg-alt" } else { "cell-bg" };
        let _ = writeln!(
            out,
            "  <rect x=\"{table_x}\" y=\"{y}\" width=\"{table_w}\" height=\"{ROW_H}\" class=\"{bg_class}\"/>"
        );

        let status_class = match row.status {
            ComplianceStatus::Pass => "pass",
            ComplianceStatus::Fail => "fail",
            ComplianceStatus::Warning => "warn",
            _ => "na",
        };
        let status_text = match row.status {
            ComplianceStatus::Pass => "PASS",
            ComplianceStatus::Fail => "FAIL",
            ComplianceStatus::Warning => "WARN",
            ComplianceStatus::NotApplicable => "N/A",
            ComplianceStatus::DataMissing => "MISSING",
        };

        // REQUIREMENT / ACTUAL combined.
        let req_act = if row.requirement == "—" && row.actual == "—" {
            "—".into()
        } else {
            format!("{} / {}", row.requirement, row.actual)
        };

        let cells: [String; 6] = [
            row.tag.clone(),
            status_text.into(),
            row.rule.clone(),
            row.code.clone(),
            req_act,
            row.message.clone(),
        ];
        let mut x = table_x;
        for (cell, (_, width)) in cells.iter().zip(cols.iter()) {
            let cx = x + 5;
            let cy = y + ROW_H / 2 + 4;
            let class = if x == table_x + cols[0].1 {
                // STATUS column gets the colour class.
                status_class
            } else {
                "cell"
            };
            let _ = writeln!(
                out,
                "  <text x=\"{cx}\" y=\"{cy}\" class=\"{class}\">{}</text>",
                xml_escape(cell)
            );
            x += width;
        }
        y += ROW_H;
    }

    // Borders.
    let _ = writeln!(
        out,
        "  <rect x=\"{table_x}\" y=\"{table_y}\" width=\"{table_w}\" height=\"{table_h}\" class=\"border\"/>"
    );
    let mut x = table_x;
    for (_, width) in &cols[..cols.len() - 1] {
        x += width;
        let y2 = table_y + table_h;
        let _ = writeln!(
            out,
            "  <line x1=\"{x}\" y1=\"{table_y}\" x2=\"{x}\" y2=\"{y2}\" class=\"border\"/>"
        );
    }
    let mut ry = table_y + HDR_H;
    for _ in 0..rows.len() {
        let x2 = table_x + table_w;
        let _ = writeln!(
            out,
            "  <line x1=\"{table_x}\" y1=\"{ry}\" x2=\"{x2}\" y2=\"{ry}\" class=\"border\"/>"
        );
        ry += ROW_H;
    }

    out.push_str("</svg>\n");
    out
}

/// Minimal XML escape for cell text.
fn xml_escape(s: &str) -> String {
    s.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::ValidationResult;
    use obc::{ComplianceCheck, ComplianceReport, ComplianceStatus};

    fn sample_result() -> ValidationResult {
        let mut result = ValidationResult::default();
        result.overall_pass = false;
        result.walls_checked = 2;
        result.walls_passed = 1;
        result.walls_failed = 1;
        result.thermal_compliance = false;
        result.average_r_value = 18.5;
        result.total_exterior_wall_area = 10_000_000.0;

        result.wall_reports.push(ComplianceReport {
            element_id: "exterior".into(),
            element_type: "wall_assembly".into(),
            overall_status: ComplianceStatus::Fail,
            checks: vec![
                ComplianceCheck {
                    rule_name: "Thermal Resistance".into(),
                    code_section: "OBC 9.36.2.2".into(),
                    status: ComplianceStatus::Fail,
                    requirement: "R-24".into(),
                    actual: "R-18.5".into(),
                    message: "Add continuous insulation".into(),
                },
            ],
        });
        result.wall_reports.push(ComplianceReport {
            element_id: "interior".into(),
            element_type: "wall_assembly".into(),
            overall_status: ComplianceStatus::Pass,
            checks: vec![ComplianceCheck {
                rule_name: "Fire Separation".into(),
                code_section: "OBC 9.10.9.2".into(),
                status: ComplianceStatus::Pass,
                requirement: "45 min".into(),
                actual: "45 min".into(),
                message: "OK".into(),
            }],
        });
        result
    }

    #[test]
    fn report_svg_is_well_formed() {
        let svg = compliance_report_to_svg(&sample_result(), "Test House");
        assert!(svg.starts_with("<?xml"));
        assert!(svg.contains("<svg"));
        assert!(svg.contains("</svg>"));
    }

    #[test]
    fn report_contains_title_and_project() {
        let svg = compliance_report_to_svg(&sample_result(), "Test House");
        assert!(svg.contains("CODE COMPLIANCE REPORT"));
        assert!(svg.contains("Test House"));
    }

    #[test]
    fn report_shows_overall_fail() {
        let svg = compliance_report_to_svg(&sample_result(), "Test House");
        assert!(svg.contains("FAIL"));
        assert!(svg.contains("R-18.5"));
    }

    #[test]
    fn report_shows_wall_rows() {
        let svg = compliance_report_to_svg(&sample_result(), "Test House");
        assert!(svg.contains("Thermal Resistance"));
        assert!(svg.contains("OBC 9.36.2.2"));
        assert!(svg.contains("Add continuous insulation"));
    }

    #[test]
    fn stair_reports_render_in_the_table() {
        let mut result = sample_result();
        let mut stair = ComplianceReport {
            element_id: "Level 1 (switchback)".into(),
            element_type: "stair".into(),
            checks: vec![ComplianceCheck {
                rule_name: "Riser height".into(),
                code_section: "OBC 9.8.4.2".into(),
                status: ComplianceStatus::Pass,
                requirement: "125–200 mm".into(),
                actual: "190 mm × 16 risers".into(),
                message: "OK".into(),
            }],
            ..Default::default()
        };
        stair.compute_overall_status();
        result.stair_reports.push(stair);

        let svg = compliance_report_to_svg(&result, "Stair House");
        assert!(svg.contains("Level 1 (switchback)"), "stair element missing");
        assert!(svg.contains("OBC 9.8.4.2"), "stair code section missing");
        assert!(svg.contains("Riser height"));
    }

    #[test]
    fn empty_result_still_renders() {
        let mut result = ValidationResult::default();
        result.overall_pass = true;
        let svg = compliance_report_to_svg(&result, "Empty");
        assert!(svg.contains("CODE COMPLIANCE REPORT"));
        assert!(svg.contains("PASS"), "should show PASS when overall_pass=true");
    }
}
