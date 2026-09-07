//! Schedule-table SVG renderer.
//!
//! Port of `generate_schedule_svg` from
//! `ArchEngine_kernel/scripts/generate_schedules.py:115`. This crate
//! provides only the rendering side; the schema-bound entry builders
//! (`door_entries` / `window_entries`) live in `ls-qbd` because they
//! require `archgeometry::SchemaDocument`.

/// One row in a schedule table. Mirrors Python's `ScheduleEntry`.
#[derive(Debug, Clone, Default)]
pub struct ScheduleEntry {
    /// Mark code (`D1`, `D2`, ... or `W1`, `W2`, ...).
    pub mark: String,
    pub qty: u32,
    pub width_mm: f32,
    pub height_mm: f32,
    /// Human-readable type (e.g. `"Single Door"`, `"Double Hung"`).
    pub type_name: String,
    /// `"Living - Kitchen"` style room-pair string. Falls back to
    /// `"Wall <idx>"` when room info is missing.
    pub location: String,
    pub remarks: String,
}

/// Determine the door type from its width (mm). Matches Python
/// `generate_schedules.py:64-71`.
#[must_use]
pub fn door_type_for_width(width_mm: f32) -> &'static str {
    if width_mm < 1000.0 {
        "Single Door"
    } else if width_mm < 2000.0 {
        "Double Door"
    } else {
        "Sliding Door"
    }
}

/// Window type from width (mm). Matches Python `generate_schedules.py:88-93`.
#[must_use]
pub fn window_type_for_width(width_mm: f32) -> &'static str {
    if width_mm < 800.0 {
        "Casement"
    } else if width_mm < 1500.0 {
        "Double Hung"
    } else {
        "Picture Window"
    }
}

/// Format mm in metres when ≥ 1000, mm otherwise. Mirrors Python's
/// `format_dim_mm` (`generate_schedules.py:108-112`).
#[must_use]
pub fn format_dim_mm(mm: f32) -> String {
    if mm >= 1000.0 {
        format!("{:.2} m", mm / 1000.0)
    } else {
        format!("{mm:.0} mm")
    }
}

/// Render a schedule table to SVG. Matches the column layout and styling
/// of `generate_schedules.py:115-211`.
#[must_use]
#[allow(clippy::too_many_lines)] // SVG layout is naturally linear and clearer flat.
pub fn schedule_to_svg(entries: &[ScheduleEntry], title: &str) -> String {
    use std::fmt::Write as _;
    let row_height: i32 = 40;
    let header_height: i32 = 50;
    let margin: i32 = 50;

    let cols: [(&str, i32); 7] = [
        ("MARK", 80),
        ("QTY", 60),
        ("WIDTH", 100),
        ("HEIGHT", 100),
        ("TYPE", 200),
        ("LOCATION", 250),
        ("REMARKS", 150),
    ];
    let table_width: i32 = cols.iter().map(|(_, w)| *w).sum();
    #[allow(clippy::cast_possible_truncation, clippy::cast_possible_wrap)]
    let table_height: i32 = header_height + (entries.len() as i32) * row_height;
    let svg_width = table_width + 2 * margin;
    let svg_height = table_height + 3 * margin + 60;

    let mut out = String::with_capacity(2048);
    out.push_str("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n");
    let _ = writeln!(
        out,
        "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"{svg_width}\" \
         height=\"{svg_height}\" viewBox=\"0 0 {svg_width} {svg_height}\">"
    );
    out.push_str("  <rect width=\"100%\" height=\"100%\" fill=\"white\"/>\n");

    // Stylesheet (kept verbatim from Python so the visual output matches).
    out.push_str("  <style>\n");
    out.push_str("    .title { font-family: Arial, sans-serif; font-size: 24px; font-weight: bold; fill: #333; }\n");
    out.push_str("    .header { font-family: Arial, sans-serif; font-size: 14px; font-weight: bold; fill: #fff; }\n");
    out.push_str("    .cell { font-family: Arial, sans-serif; font-size: 12px; fill: #333; }\n");
    out.push_str("    .header-bg { fill: #333; }\n");
    out.push_str("    .cell-bg { fill: #fff; }\n");
    out.push_str("    .cell-bg-alt { fill: #f5f5f5; }\n");
    out.push_str("    .border { stroke: #333; stroke-width: 1; fill: none; }\n");
    out.push_str("  </style>\n");

    // Title.
    let title_y = margin + 30;
    let title_x = svg_width / 2;
    let _ = writeln!(
        out,
        "  <text x=\"{title_x}\" y=\"{title_y}\" text-anchor=\"middle\" \
         class=\"title\">{title}</text>"
    );

    // Table position.
    let table_x = margin;
    let table_y = margin + 60;

    // Header row.
    let _ = writeln!(
        out,
        "  <rect x=\"{table_x}\" y=\"{table_y}\" width=\"{table_width}\" \
         height=\"{header_height}\" class=\"header-bg\"/>"
    );
    let mut x = table_x;
    for (header, width) in cols {
        let cx = x + width / 2;
        let cy = table_y + header_height / 2 + 5;
        let _ = writeln!(
            out,
            "  <text x=\"{cx}\" y=\"{cy}\" text-anchor=\"middle\" \
             class=\"header\">{header}</text>"
        );
        x += width;
    }

    // Data rows.
    let mut y = table_y + header_height;
    for (i, entry) in entries.iter().enumerate() {
        let bg_class = if i % 2 == 1 { "cell-bg-alt" } else { "cell-bg" };
        let _ = writeln!(
            out,
            "  <rect x=\"{table_x}\" y=\"{y}\" width=\"{table_width}\" \
             height=\"{row_height}\" class=\"{bg_class}\"/>"
        );
        let cells: [String; 7] = [
            entry.mark.clone(),
            entry.qty.to_string(),
            format_dim_mm(entry.width_mm),
            format_dim_mm(entry.height_mm),
            entry.type_name.clone(),
            entry.location.clone(),
            entry.remarks.clone(),
        ];
        let mut x = table_x;
        for (cell, (_, width)) in cells.iter().zip(cols.iter()) {
            let cx = x + 5;
            let cy = y + row_height / 2 + 4;
            let _ = writeln!(out, "  <text x=\"{cx}\" y=\"{cy}\" class=\"cell\">{cell}</text>");
            x += width;
        }
        y += row_height;
    }

    // Outer border + column separators + row separators.
    let _ = writeln!(
        out,
        "  <rect x=\"{table_x}\" y=\"{table_y}\" width=\"{table_width}\" \
         height=\"{table_height}\" class=\"border\"/>"
    );
    let mut x = table_x;
    for (_, width) in &cols[..cols.len() - 1] {
        x += width;
        let y2 = table_y + table_height;
        let _ = writeln!(
            out,
            "  <line x1=\"{x}\" y1=\"{table_y}\" x2=\"{x}\" \
             y2=\"{y2}\" class=\"border\"/>"
        );
    }
    let mut y = table_y + header_height;
    for _ in 0..entries.len() {
        let x2 = table_x + table_width;
        let _ = writeln!(
            out,
            "  <line x1=\"{table_x}\" y1=\"{y}\" x2=\"{x2}\" y2=\"{y}\" \
             class=\"border\"/>"
        );
        y += row_height;
    }

    out.push_str("</svg>\n");
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn door_type_for_width_thresholds() {
        assert_eq!(door_type_for_width(800.0), "Single Door");
        assert_eq!(door_type_for_width(999.99), "Single Door");
        assert_eq!(door_type_for_width(1000.0), "Double Door");
        assert_eq!(door_type_for_width(1999.99), "Double Door");
        assert_eq!(door_type_for_width(2000.0), "Sliding Door");
    }

    #[test]
    fn window_type_for_width_thresholds() {
        assert_eq!(window_type_for_width(600.0), "Casement");
        assert_eq!(window_type_for_width(800.0), "Double Hung");
        assert_eq!(window_type_for_width(1500.0), "Picture Window");
    }

    #[test]
    fn format_dim_switches_at_one_metre() {
        assert_eq!(format_dim_mm(900.0), "900 mm");
        assert_eq!(format_dim_mm(1000.0), "1.00 m");
        assert_eq!(format_dim_mm(1500.0), "1.50 m");
    }

    #[test]
    fn schedule_svg_has_header_and_one_row_per_entry() {
        let entries = vec![
            ScheduleEntry {
                mark: "D1".into(),
                qty: 1,
                width_mm: 900.0,
                height_mm: 2100.0,
                type_name: "Single Door".into(),
                location: "Foyer".into(),
                remarks: String::new(),
            },
            ScheduleEntry {
                mark: "D2".into(),
                qty: 1,
                width_mm: 1800.0,
                height_mm: 2100.0,
                type_name: "Double Door".into(),
                location: "Living".into(),
                remarks: String::new(),
            },
        ];
        let svg = schedule_to_svg(&entries, "DOOR SCHEDULE");
        assert!(svg.starts_with("<?xml version=\"1.0\""));
        assert!(svg.contains("DOOR SCHEDULE"));
        assert!(svg.contains(">D1<"));
        assert!(svg.contains(">D2<"));
        // Per Python: alternating row backgrounds.
        assert!(svg.contains("cell-bg-alt"));
        assert!(svg.ends_with("</svg>\n"));
    }

    #[test]
    fn empty_entries_emit_header_only() {
        let svg = schedule_to_svg(&[], "DOOR SCHEDULE");
        assert!(svg.contains("DOOR SCHEDULE"));
        // No data rows ⇒ no `class="cell-bg-alt"` *usage* (the stylesheet
        // still defines the class).
        assert!(!svg.contains(r#"class="cell-bg-alt""#));
    }
}
