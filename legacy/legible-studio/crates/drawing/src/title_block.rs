//! Standard architectural title block.
//!
//! Port of `ArchEngine_kernel/scripts/title_block.py` (228 LOC). Emits an
//! SVG `<g>` group that wraps a drawing border + inner border + the
//! title-block box (bottom-right corner) with project name, drawing
//! title, scale, date, drawn-by, project number, drawing number,
//! revision, sheet number. Goes inside another SVG; not a standalone
//! `<svg>` document.

use std::fmt::Write as _;

/// Project-level metadata that's the same across all sheets in a permit set.
#[derive(Debug, Clone, Default)]
pub struct ProjectInfo {
    pub name: String,
    pub address: String,
    pub client: String,
    pub number: String,
    /// Free-text label for the solver — "QBD Layout", "Grid Solver", etc.
    pub solver: String,
    /// Qualified designer name (Ontario Part 9 designs must be stamped by a
    /// qualified designer or P.Eng).
    pub designer: String,
    /// Building Code Identification Number — Ontario MMAH registration
    /// number for the qualified designer (e.g. `"BCIN 12345"`).
    pub designer_bcin: String,
    /// OBC SB-12 climate zone for the project site (e.g. `"Zone 6"`). Drives
    /// the section's thermal R-value callouts. Empty → treated as Zone 6.
    pub climate_zone: String,
}

/// Per-sheet metadata. Different for each drawing in the set.
#[derive(Debug, Clone, Default)]
pub struct DrawingInfo {
    pub title: String,
    pub number: String,
    pub scale: String,
    pub sheet: String,
    pub revision: String,
    pub drawn_by: String,
    pub checked_by: String,
    /// `YYYY-MM-DD`. The C++ side uses the system clock; pass it in here
    /// so the title block stays deterministic for tests + diff oracles.
    pub date: String,
}

/// Canonical drawing-type identifier — picks the standard sheet number
/// + title + sheet count for each permit-set drawing.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DrawingType {
    SitePlan,
    FoundationPlan,
    FloorPlan,
    RoofPlan,
    ElevationSouth,
    ElevationNorth,
    ElevationEast,
    ElevationWest,
    SectionA,
    SectionB,
    FramingPlan,
    FootingDetail,
    StairSection,
    ComplianceReport,
}

impl DrawingType {
    /// Lookup matching `title_block.py:204` (DRAWING_NUMBERS).
    /// Returns `(number, title, sheet)`.
    #[must_use] 
    pub fn default_info(self) -> (&'static str, &'static str, &'static str) {
        match self {
            DrawingType::SitePlan => ("A-001", "SITE PLAN", "1 OF 13"),
            DrawingType::FoundationPlan => ("A-002", "FOUNDATION PLAN", "2 OF 13"),
            DrawingType::FloorPlan => ("A-101", "FLOOR PLAN - LEVEL 1", "3 OF 13"),
            DrawingType::RoofPlan => ("A-102", "ROOF PLAN", "4 OF 13"),
            DrawingType::ElevationSouth => ("A-201", "SOUTH ELEVATION", "5 OF 13"),
            DrawingType::ElevationNorth => ("A-202", "NORTH ELEVATION", "6 OF 13"),
            DrawingType::ElevationEast => ("A-203", "EAST ELEVATION", "7 OF 13"),
            DrawingType::ElevationWest => ("A-204", "WEST ELEVATION", "8 OF 13"),
            DrawingType::SectionA => ("A-301", "SECTION A-A", "9 OF 13"),
            DrawingType::SectionB => ("A-302", "SECTION B-B", "10 OF 13"),
            DrawingType::FramingPlan => ("A-103", "FRAMING PLAN - LEVEL 1", "11 OF 13"),
            DrawingType::FootingDetail => ("A-501", "TYPICAL FOOTING DETAIL", "12 OF 14"),
            DrawingType::StairSection => ("A-502", "TYPICAL STAIR SECTION", "13 OF 14"),
            DrawingType::ComplianceReport => ("A-401", "CODE COMPLIANCE REPORT", "14 OF 14"),
        }
    }
}

/// Build a per-drawing info struct from a DrawingType + a scale string.
/// Matches `get_drawing_info` (`title_block.py:216`).
#[must_use]
pub fn drawing_info_for(dt: DrawingType, scale: &str, date: &str) -> DrawingInfo {
    let (number, title, sheet) = dt.default_info();
    DrawingInfo {
        title: title.to_string(),
        number: number.to_string(),
        scale: scale.to_string(),
        sheet: sheet.to_string(),
        revision: "-".to_string(),
        drawn_by: "AE".to_string(),
        checked_by: String::new(),
        date: date.to_string(),
    }
}

/// Generate the title-block SVG fragment. Embeds in the surrounding sheet
/// SVG; not a standalone document. Coordinates are in mm (model space)
/// like the Python.
///
/// `width` and `height` are the drawing's content extent in mm. `margin`
/// is the margin around the drawing.
#[must_use]
#[allow(clippy::too_many_lines)]
pub fn generate_title_block(
    width: f32,
    height: f32,
    project: &ProjectInfo,
    drawing: &DrawingInfo,
    margin: f32,
) -> String {
    let border_margin = 300.0_f32;

    let border_x = -margin + border_margin;
    let border_y = -margin + border_margin;
    let border_w = width + 2.0 * margin - 2.0 * border_margin;
    let border_h = height + 2.0 * margin - 2.0 * border_margin;

    // Title block bottom-right of the border.
    let tb_x = border_x + border_w - TITLE_BLOCK_W - 100.0;
    let tb_y = border_y + border_h - TITLE_BLOCK_H - 100.0;

    let mut s = String::with_capacity(2048);
    s.push_str("<!-- Title Block -->\n");
    s.push_str("<g id=\"title-block\">\n");

    // Drawing border (outer).
    let _ = writeln!(
        s,
        r##"  <rect x="{border_x}" y="{border_y}" width="{border_w}" height="{border_h}" fill="none" stroke="#000" stroke-width="8"/>"##,
    );
    // Inner border.
    let _ = writeln!(
        s,
        r##"  <rect x="{ibx}" y="{iby}" width="{ibw}" height="{ibh}" fill="none" stroke="#000" stroke-width="2"/>"##,
        ibx = border_x + 50.0,
        iby = border_y + 50.0,
        ibw = border_w - 100.0,
        ibh = border_h - 100.0,
    );
    // Title-block box (bottom-right of the border).
    s.push_str(&title_block_box(tb_x, tb_y, project, drawing));
    s.push_str("</g>\n");
    s
}

/// Natural dimensions of the title-block box (model mm). Its internal text
/// layout is tuned to this size; resize it by scaling uniformly, never by
/// changing these (which would not move the text with the box).
pub const TITLE_BLOCK_W: f32 = 4000.0;
/// Natural height of the title-block box (model mm). See [`TITLE_BLOCK_W`].
pub const TITLE_BLOCK_H: f32 = 1200.0;

/// Emit just the title-block box (no sheet border), top-left corner at
/// `(tb_x, tb_y)`, at its natural [`TITLE_BLOCK_W`]×[`TITLE_BLOCK_H`] size.
///
/// Split out of [`generate_title_block`] so a sheet composer can place the box
/// at a *uniform* scale anywhere in a viewBox — keeping the title block a
/// consistent size and aspect on every sheet regardless of drawing scale.
#[must_use]
pub fn title_block_box(
    tb_x: f32,
    tb_y: f32,
    project: &ProjectInfo,
    drawing: &DrawingInfo,
) -> String {
    let tb_width = TITLE_BLOCK_W;
    let tb_height = TITLE_BLOCK_H;

    let pname = pick(&project.name, "RESIDENTIAL PROJECT");
    let paddr = &project.address;
    let pclient = &project.client;
    let pnum = pick(&project.number, "P-001");
    let psolver = pick(&project.solver, "QBD Layout");
    let pdesigner = project.designer.as_str();
    let pbcin = project.designer_bcin.as_str();

    let dtitle = pick(&drawing.title, "FLOOR PLAN");
    let dnum = pick(&drawing.number, "A-101");
    let dscale = pick(&drawing.scale, "1:100");
    let dsheet = pick(&drawing.sheet, "1 OF 8");
    let drev = pick(&drawing.revision, "-");
    let ddrawn = pick(&drawing.drawn_by, "ARCHENGINE");
    let ddate = pick(&drawing.date, "");

    let mut s = String::with_capacity(1536);
    // Title-block box.
    let _ = writeln!(
        s,
        r##"  <rect x="{tb_x}" y="{tb_y}" width="{tb_width}" height="{tb_height}" fill="white" stroke="#000" stroke-width="4"/>"##,
    );

    // Horizontal dividers.
    for dy in [300.0_f32, 600.0, 900.0] {
        let _ = writeln!(
            s,
            r##"  <line x1="{tb_x}" y1="{y}" x2="{x2}" y2="{y}" stroke="#000" stroke-width="2"/>"##,
            y = tb_y + dy,
            x2 = tb_x + tb_width,
        );
    }
    // Vertical dividers (in the bottom half only).
    for dx in [2000.0_f32, 3000.0] {
        let _ = writeln!(
            s,
            r##"  <line x1="{x}" y1="{y1}" x2="{x}" y2="{y2}" stroke="#000" stroke-width="2"/>"##,
            x = tb_x + dx,
            y1 = tb_y + 600.0,
            y2 = tb_y + tb_height,
        );
    }

    // Project name (large, top row).
    let cx = tb_x + tb_width * 0.5;
    let _ = writeln!(
        s,
        r#"  <text x="{cx}" y="{y}" font-family="Arial" font-size="200" font-weight="bold" text-anchor="middle">{pname}</text>"#,
        y = tb_y + 200.0,
    );
    // Project address.
    let _ = writeln!(
        s,
        r##"  <text x="{cx}" y="{y}" font-family="Arial" font-size="120" text-anchor="middle" fill="#333">{paddr}</text>"##,
        y = tb_y + 450.0,
    );
    // Client name.
    let _ = writeln!(
        s,
        r##"  <text x="{cx}" y="{y}" font-family="Arial" font-size="100" text-anchor="middle" fill="#666">{pclient}</text>"##,
        y = tb_y + 550.0,
    );
    // Drawing title (large).
    let _ = writeln!(
        s,
        r#"  <text x="{x}" y="{y}" font-family="Arial" font-size="180" font-weight="bold" text-anchor="middle">{dtitle}</text>"#,
        x = tb_x + 1000.0,
        y = tb_y + 800.0,
    );

    // Labels + values along bottom row: SCALE, DATE, DRAWN, DWG NO, PROJECT, REV, SHEET.
    write_label_value(&mut s, tb_x + 100.0, tb_y, "SCALE", dscale, false);
    write_label_value(&mut s, tb_x + 700.0, tb_y, "DATE", ddate, false);
    write_label_value(&mut s, tb_x + 1400.0, tb_y, "DRAWN", ddrawn, false);

    // Drawing number — two-line layout with big number above SHEET row.
    let _ = writeln!(
        s,
        r##"  <text x="{x}" y="{y}" font-family="Arial" font-size="80" fill="#666">DWG NO.</text>"##,
        x = tb_x + 2100.0,
        y = tb_y + 700.0,
    );
    let _ = writeln!(
        s,
        r#"  <text x="{x}" y="{y}" font-family="Arial" font-size="200" font-weight="bold" text-anchor="middle">{dnum}</text>"#,
        x = tb_x + 2500.0,
        y = tb_y + 850.0,
    );
    write_label_value(&mut s, tb_x + 2100.0, tb_y, "PROJECT", pnum, true);

    // Revision (big char top-right cell).
    let _ = writeln!(
        s,
        r##"  <text x="{x}" y="{y}" font-family="Arial" font-size="80" fill="#666">REV</text>"##,
        x = tb_x + 3100.0,
        y = tb_y + 700.0,
    );
    let _ = writeln!(
        s,
        r#"  <text x="{x}" y="{y}" font-family="Arial" font-size="200" font-weight="bold" text-anchor="middle">{drev}</text>"#,
        x = tb_x + 3500.0,
        y = tb_y + 850.0,
    );
    write_label_value(&mut s, tb_x + 3100.0, tb_y, "SHEET", dsheet, true);

    // Solver info (small text, top-left corner of TB box).
    let _ = writeln!(
        s,
        r##"  <text x="{x}" y="{y}" font-family="Arial" font-size="60" fill="#999">{psolver}</text>"##,
        x = tb_x + 50.0,
        y = tb_y + 50.0,
    );

    // Qualified designer + BCIN (top-right of TB box). Required on
    // Ontario Part 9 permit drawings — every sheet carries the stamp.
    if !pdesigner.is_empty() || !pbcin.is_empty() {
        let _ = writeln!(
            s,
            r##"  <text x="{x}" y="{y}" font-family="Arial" font-size="60" fill="#555" text-anchor="end">QUALIFIED DESIGNER: {pdesigner}</text>"##,
            x = tb_x + tb_width - 50.0,
            y = tb_y + 50.0,
        );
        let _ = writeln!(
            s,
            r##"  <text x="{x}" y="{y}" font-family="Arial" font-size="60" fill="#555" text-anchor="end">{pbcin}</text>"##,
            x = tb_x + tb_width - 50.0,
            y = tb_y + 130.0,
        );
    }

    s
}

fn pick<'a>(value: &'a str, default: &'a str) -> &'a str {
    if value.is_empty() { default } else { value }
}

fn write_label_value(
    s: &mut String,
    x: f32,
    tb_y: f32,
    label: &str,
    value: &str,
    smaller_value: bool,
) {
    let value_size = if smaller_value { 100 } else { 120 };
    let _ = writeln!(
        s,
        r##"  <text x="{x}" y="{y}" font-family="Arial" font-size="80" fill="#666">{label}</text>"##,
        y = tb_y + 970.0,
    );
    let weight = if smaller_value {
        ""
    } else {
        r#" font-weight="bold""#
    };
    let _ = writeln!(
        s,
        r#"  <text x="{x}" y="{y}" font-family="Arial" font-size="{value_size}"{weight}>{value}</text>"#,
        y = tb_y + 1100.0,
    );
}

#[cfg(test)]
mod tests {
    use super::*;

    fn test_project() -> ProjectInfo {
        ProjectInfo {
            name: "MAPLE HOUSE".into(),
            address: "123 Main St".into(),
            client: "ACME Builders".into(),
            number: "P-042".into(),
            solver: "QBD Layout".into(),
            designer: String::new(),
            designer_bcin: String::new(),
            climate_zone: String::new(),
        }
    }

    #[test]
    fn drawing_type_dispatches_to_canonical_numbers() {
        assert_eq!(DrawingType::FloorPlan.default_info().0, "A-101");
        assert_eq!(DrawingType::ElevationSouth.default_info().0, "A-201");
        assert_eq!(DrawingType::ElevationNorth.default_info().0, "A-202");
        assert_eq!(DrawingType::SectionA.default_info().0, "A-301");
    }

    #[test]
    fn drawing_info_for_floor_plan_at_scale_1_100() {
        let info = drawing_info_for(DrawingType::FloorPlan, "1:100", "2026-05-16");
        assert_eq!(info.title, "FLOOR PLAN - LEVEL 1");
        assert_eq!(info.number, "A-101");
        assert_eq!(info.scale, "1:100");
        assert_eq!(info.sheet, "3 OF 13");
        assert_eq!(info.revision, "-");
        assert_eq!(info.drawn_by, "AE");
        assert_eq!(info.date, "2026-05-16");
    }

    #[test]
    fn generate_title_block_emits_outer_inner_border_and_tb_box() {
        let p = test_project();
        let d = drawing_info_for(DrawingType::FloorPlan, "1:50", "2026-05-16");
        let svg = generate_title_block(10000.0, 8000.0, &p, &d, 500.0);
        // 3 rects: outer border, inner border, TB box.
        assert!(svg.contains(r#"id="title-block""#));
        assert_eq!(svg.matches("<rect").count(), 3);
        // Title block has 3 horizontal + 2 vertical dividers = 5 lines.
        assert_eq!(svg.matches("<line").count(), 5);
        // Project name + address + client + drawing title + sheet labels.
        assert!(svg.contains("MAPLE HOUSE"));
        assert!(svg.contains("123 Main St"));
        assert!(svg.contains("ACME Builders"));
        assert!(svg.contains("FLOOR PLAN - LEVEL 1"));
        assert!(svg.contains("A-101"));
        assert!(svg.contains("2026-05-16"));
        assert!(svg.contains("1:50"));
        assert!(svg.contains("QBD Layout"));
    }

    #[test]
    fn defaults_kick_in_for_empty_project_fields() {
        let p = ProjectInfo::default();
        let d = DrawingInfo::default();
        let svg = generate_title_block(5000.0, 4000.0, &p, &d, 500.0);
        assert!(svg.contains("RESIDENTIAL PROJECT"));
        assert!(svg.contains("FLOOR PLAN")); // dtitle default
        assert!(svg.contains("A-101")); // dnum default
        assert!(svg.contains("P-001")); // pnum default
        assert!(svg.contains("QBD Layout"));
        // Empty designer/BCIN → no QUALIFIED DESIGNER line emitted.
        assert!(!svg.contains("QUALIFIED DESIGNER"));
    }

    #[test]
    fn designer_and_bcin_render_when_populated() {
        let mut p = test_project();
        p.designer = "JANE DOE".into();
        p.designer_bcin = "BCIN 12345".into();
        let d = drawing_info_for(DrawingType::FloorPlan, "1:100", "2026-06-04");
        let svg = generate_title_block(10000.0, 8000.0, &p, &d, 500.0);
        assert!(svg.contains("QUALIFIED DESIGNER: JANE DOE"));
        assert!(svg.contains("BCIN 12345"));
    }
}
