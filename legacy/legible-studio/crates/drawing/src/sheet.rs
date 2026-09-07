//! Sheet layout: compose drawings onto a fixed-size permit sheet at true
//! architectural scale, with a reserved title block that never overlaps the
//! drawing.
//!
//! The rest of the drawing crate emits each drawing as its own SVG authored in
//! a per-drawing unit space (plan millimetres × an export factor). This module
//! treats those as *viewports*: it parses a drawing's `viewBox`, scales it so
//! the real-world geometry lands at a chosen paper scale (e.g. 1:50), and
//! places it inside the drawing area of a fixed paper size (default ARCH D),
//! with a title block in the bottom-right corner.
//!
//! The sheet itself is authored in **paper millimetres** (1 user unit = 1 mm),
//! so [`crate::sheet::PaperSize`] dimensions are the real page size. Render to
//! PDF with a 25.4-DPI page (1 unit → 1 mm) for a true-to-scale plot.

use std::fmt::Write as _;

use crate::title_block::{DrawingInfo, ProjectInfo};

/// A fixed paper size in landscape millimetres (`w_mm >= h_mm`).
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct PaperSize {
    pub w_mm: f32,
    pub h_mm: f32,
    pub name: &'static str,
}

impl PaperSize {
    /// ARCH D — 24" × 36", landscape. The standard residential permit sheet.
    pub const ARCH_D: PaperSize = PaperSize { w_mm: 914.0, h_mm: 610.0, name: "ARCH D" };
    /// ARCH C — 18" × 24", landscape.
    pub const ARCH_C: PaperSize = PaperSize { w_mm: 610.0, h_mm: 457.0, name: "ARCH C" };
    /// ANSI B / Tabloid — 11" × 17", landscape.
    pub const ANSI_B: PaperSize = PaperSize { w_mm: 432.0, h_mm: 279.0, name: "ANSI B" };
    /// ISO A1 — 841 × 594 mm, landscape.
    pub const A1: PaperSize = PaperSize { w_mm: 841.0, h_mm: 594.0, name: "A1" };
}

impl Default for PaperSize {
    fn default() -> Self {
        Self::ARCH_D
    }
}

/// Sheet layout constants (paper millimetres).
const BORDER_MM: f32 = 12.0; // outer margin to the sheet edge
const GUTTER_MM: f32 = 8.0; // gap between drawing area and the title block

/// One drawing to place on a sheet.
#[derive(Debug, Clone)]
pub struct SheetDrawing {
    /// A complete drawing SVG (no title block) authored by one of the crate's
    /// generators.
    pub svg: String,
    /// The drawing's authored model units per real-world millimetre — i.e. the
    /// `scale` passed to its exporter (floor plan = 10.0, section = 0.05, …).
    pub model_units_per_mm: f32,
    /// Paper scale denominator: 50 for 1:50, 20 for 1:20.
    pub scale_denominator: f32,
    /// Sub-title shown under the drawing when several share a sheet.
    pub caption: String,
}

impl SheetDrawing {
    /// Scale label, e.g. `"1 : 50"`.
    #[must_use]
    pub fn scale_label(&self) -> String {
        format!("1 : {}", self.scale_denominator.round() as i64)
    }
}

/// The drawing-area rectangle (paper mm) inside the borders, above the title
/// strip: `(x, y, w, h)`.
#[must_use]
fn drawing_area(paper: PaperSize) -> (f32, f32, f32, f32) {
    let x = BORDER_MM;
    let y = BORDER_MM;
    let w = paper.w_mm - 2.0 * BORDER_MM;
    // Reserve the corner-block height along the bottom so auto-laid drawings
    // clear it (the block itself only occupies the bottom-right corner).
    let h = paper.h_mm - 2.0 * BORDER_MM - TB_H - GUTTER_MM;
    (x, y, w, h)
}

/// Parse `viewBox="x y w h"` → `(x, y, w, h)`.
fn parse_viewbox(svg: &str) -> Option<(f32, f32, f32, f32)> {
    let vb = svg.split("viewBox=\"").nth(1)?.split('"').next()?;
    let n: Vec<f32> = vb.split_whitespace().filter_map(|t| t.parse().ok()).collect();
    if n.len() == 4 {
        Some((n[0], n[1], n[2], n[3]))
    } else {
        None
    }
}

/// Extract the body of a drawing SVG: everything between the opening `<svg …>`
/// tag and `</svg>`, with the full-bleed white background rect removed (it
/// would otherwise paint over the whole sheet once nested in a group).
fn svg_body(svg: &str) -> String {
    // Strip the XML declaration and the opening `<svg …>` tag (NOT just the
    // first `>`, which would be the `?>` of `<?xml?>` and leave the inner
    // `<svg>` element — a nested viewport that ignores our placement transform).
    let after_open = svg
        .find("<svg")
        .and_then(|i| svg[i..].find('>').map(|j| i + j + 1));
    let body = match (after_open, svg.rfind("</svg>")) {
        (Some(start), Some(close)) if start <= close => &svg[start..close],
        _ => svg,
    };
    body.replace(
        "<rect width=\"100%\" height=\"100%\" fill=\"white\"/>\n",
        "",
    )
    .replace("<rect width=\"100%\" height=\"100%\" fill=\"white\"/>", "")
}

/// How a placed drawing turned out — lets callers warn when a chosen scale
/// overflows the drawing area.
#[derive(Debug, Clone, Copy)]
pub struct Placement {
    /// Placed width/height on paper (mm) at the requested scale.
    pub content_w_mm: f32,
    pub content_h_mm: f32,
    /// True if the drawing exceeds the drawing area at this scale.
    pub overflows: bool,
}

/// Emit the sheet shell: SVG header, white background, and border. Caller
/// continues appending placed drawings + the title block, then `</svg>`.
fn sheet_open(paper: PaperSize) -> String {
    let mut s = String::with_capacity(8192);
    s.push_str("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n");
    let _ = writeln!(
        s,
        r#"<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">"#,
        w = paper.w_mm,
        h = paper.h_mm,
    );
    s.push_str("<rect width=\"100%\" height=\"100%\" fill=\"white\"/>\n");
    let _ = writeln!(
        s,
        r#"<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="none" stroke="black" stroke-width="1.2"/>"#,
        x = BORDER_MM * 0.5,
        y = BORDER_MM * 0.5,
        w = paper.w_mm - BORDER_MM,
        h = paper.h_mm - BORDER_MM,
    );
    s
}

/// Place one drawing at true scale, centred in the rect `(ax, ay, aw, ah)`,
/// clipped to that rect. `idx` makes the clip-path id unique on the sheet.
fn place_into(
    s: &mut String,
    idx: usize,
    drawing: &SheetDrawing,
    ax: f32,
    ay: f32,
    aw: f32,
    ah: f32,
) -> Placement {
    let (vbx, vby, vbw, vbh) = parse_viewbox(&drawing.svg).unwrap_or((0.0, 0.0, aw, ah));
    // paper_mm = model_units / (model_units_per_mm * N).
    let denom = (drawing.model_units_per_mm * drawing.scale_denominator).max(1e-6);
    let g = 1.0 / denom;
    let content_w = g * vbw;
    let content_h = g * vbh;
    let overflows = content_w > aw + 0.5 || content_h > ah + 0.5;
    let off_x = ax + ((aw - content_w) * 0.5).max(0.0) - g * vbx;
    let off_y = ay + ((ah - content_h) * 0.5).max(0.0) - g * vby;

    let _ = writeln!(
        s,
        r#"<clipPath id="area{idx}"><rect x="{ax}" y="{ay}" width="{aw}" height="{ah}"/></clipPath>"#,
    );
    let _ = writeln!(s, r#"<g clip-path="url(#area{idx})">"#);
    let _ = writeln!(s, r#"<g transform="translate({off_x} {off_y}) scale({g})">"#);
    s.push_str(&svg_body(&drawing.svg));
    s.push_str("</g>\n</g>\n");

    Placement { content_w_mm: content_w, content_h_mm: content_h, overflows }
}

/// Place one drawing scaled to *fit* the rect `(x, y, w, h)` (paper mm),
/// preserving aspect and centred — used by the freeform layout editor where the
/// user sizes each drawing's box directly.
fn place_fit(s: &mut String, idx: usize, svg: &str, x: f32, y: f32, w: f32, h: f32) {
    let (vbx, vby, vbw, vbh) = parse_viewbox(svg).unwrap_or((0.0, 0.0, w, h));
    if vbw <= 0.0 || vbh <= 0.0 {
        return;
    }
    let g = (w / vbw).min(h / vbh);
    let cw = g * vbw;
    let ch = g * vbh;
    let off_x = x + (w - cw) * 0.5 - g * vbx;
    let off_y = y + (h - ch) * 0.5 - g * vby;
    let _ = writeln!(
        s,
        r#"<clipPath id="fit{idx}"><rect x="{x}" y="{y}" width="{w}" height="{h}"/></clipPath>"#,
    );
    let _ = writeln!(s, r#"<g clip-path="url(#fit{idx})">"#);
    let _ = writeln!(s, r#"<g transform="translate({off_x} {off_y}) scale({g})">"#);
    s.push_str(&svg_body(svg));
    s.push_str("</g>\n</g>\n");
}

/// One drawing placed at an explicit rect on the sheet (paper mm). The layout
/// editor produces these; the drawing is scaled to fit the box.
#[derive(Debug, Clone)]
pub struct FreePlacement {
    pub svg: String,
    pub x_mm: f32,
    pub y_mm: f32,
    pub w_mm: f32,
    pub h_mm: f32,
    pub caption: String,
}

/// Compose a freeform sheet: each drawing scaled to fit its own box at the
/// position the editor placed it, with a caption beneath, sharing one bottom
/// title block. This renders exactly what the in-app sheet editor shows.
#[must_use]
pub fn compose_freeform(
    items: &[FreePlacement],
    paper: PaperSize,
    project: &ProjectInfo,
    info: &DrawingInfo,
) -> String {
    let mut s = sheet_open(paper);
    for (i, it) in items.iter().enumerate() {
        place_fit(&mut s, i, &it.svg, it.x_mm, it.y_mm, it.w_mm, it.h_mm);
        if !it.caption.is_empty() {
            let _ = writeln!(
                s,
                r#"<text x="{tx}" y="{ty}" font-family="Arial, sans-serif" font-size="5" font-weight="bold" fill="black" text-anchor="middle">{cap}</text>"#,
                tx = it.x_mm + it.w_mm * 0.5,
                ty = it.y_mm + it.h_mm + 6.0,
                cap = crate::svg::xml_escape(&it.caption),
            );
        }
    }
    s.push_str(&corner_title_block(paper, project, info, "AS NOTED"));
    s.push_str("</svg>\n");
    s
}

/// Compose a single drawing onto a sheet at its true scale, with a bottom
/// title block. Returns the sheet SVG (paper millimetres) and the
/// [`Placement`] for overflow reporting.
#[must_use]
pub fn compose_sheet(
    drawing: &SheetDrawing,
    paper: PaperSize,
    project: &ProjectInfo,
    info: &DrawingInfo,
) -> (String, Placement) {
    let (ax, ay, aw, ah) = drawing_area(paper);
    let mut s = sheet_open(paper);
    let place = place_into(&mut s, 0, drawing, ax, ay, aw, ah);
    s.push_str(&corner_title_block(paper, project, info, &drawing.scale_label()));
    s.push_str("</svg>\n");
    (s, place)
}

/// Compose several drawings onto one sheet in a `cols`-wide grid, each at its
/// own true scale with a caption beneath it, sharing one bottom title block.
/// This is the "multi-up" layout — e.g. four elevations 2×2, or two floor
/// plans side by side — so a fixed scale fills a large sheet instead of
/// floating in white space.
#[must_use]
#[allow(clippy::cast_precision_loss)]
pub fn compose_multi(
    drawings: &[SheetDrawing],
    cols: usize,
    paper: PaperSize,
    project: &ProjectInfo,
    info: &DrawingInfo,
) -> (String, Vec<Placement>) {
    let (ax, ay, aw, ah) = drawing_area(paper);
    let mut s = sheet_open(paper);

    let n = drawings.len().max(1);
    let cols = cols.clamp(1, n);
    let rows = n.div_ceil(cols);
    let cell_w = aw / cols as f32;
    let cell_h = ah / rows as f32;
    const CELL_PAD: f32 = 6.0;
    const CAPTION_H: f32 = 12.0;

    let mut placements = Vec::with_capacity(drawings.len());
    for (i, d) in drawings.iter().enumerate() {
        let c = (i % cols) as f32;
        let r = (i / cols) as f32;
        let cx = ax + c * cell_w;
        let cy = ay + r * cell_h;
        let dx = cx + CELL_PAD;
        let dy = cy + CELL_PAD;
        let dw = cell_w - 2.0 * CELL_PAD;
        let dh = cell_h - 2.0 * CELL_PAD - CAPTION_H;
        let p = place_into(&mut s, i, d, dx, dy, dw.max(1.0), dh.max(1.0));

        // Caption: drawing title + scale, centred under the cell.
        let caption = if d.caption.is_empty() {
            d.scale_label()
        } else {
            format!("{}    {}", d.caption, d.scale_label())
        };
        let _ = writeln!(
            s,
            r#"<text x="{tx}" y="{ty}" font-family="Arial, sans-serif" font-size="5.5" font-weight="bold" fill="black" text-anchor="middle">{cap}</text>"#,
            tx = cx + cell_w * 0.5,
            ty = cy + cell_h - 4.0,
            cap = crate::svg::xml_escape(&caption),
        );
        placements.push(p);
    }

    s.push_str(&corner_title_block(paper, project, info, "AS NOTED"));
    s.push_str("</svg>\n");
    (s, placements)
}

/// Title-block corner box dimensions (paper mm).
const TB_W: f32 = 195.0;
const TB_H: f32 = 64.0;

/// Render the title block as a compact box in the **bottom-right corner**
/// (paper-mm coordinates, paper-sized text): project info on top, the drawing
/// title centred, and a SHEET / SCALE / DATE cell row along the bottom.
fn corner_title_block(
    paper: PaperSize,
    project: &ProjectInfo,
    info: &DrawingInfo,
    scale_label: &str,
) -> String {
    let x0 = paper.w_mm - BORDER_MM - TB_W;
    let y0 = paper.h_mm - BORDER_MM - TB_H;
    let esc = crate::svg::xml_escape;
    let mut s = String::with_capacity(1024);

    // Outer box.
    let _ = writeln!(
        s,
        r#"<rect x="{x0}" y="{y0}" width="{TB_W}" height="{TB_H}" fill="white" stroke="black" stroke-width="1"/>"#,
    );
    // Project name + address + qualified designer.
    let _ = writeln!(
        s,
        r#"<text x="{x}" y="{y}" font-family="Arial, sans-serif" font-size="7" font-weight="bold" fill="black">{name}</text>"#,
        x = x0 + 5.0, y = y0 + 11.0, name = esc(&project.name),
    );
    if !project.address.is_empty() {
        let _ = writeln!(
            s,
            r#"<text x="{x}" y="{y}" font-family="Arial, sans-serif" font-size="4.2" fill="rgb(51,51,51)">{a}</text>"#,
            x = x0 + 5.0, y = y0 + 18.0, a = esc(&project.address),
        );
    }
    let designer_line = if project.designer.is_empty() {
        String::new()
    } else if project.designer_bcin.is_empty() {
        format!("QUALIFIED DESIGNER: {}", project.designer)
    } else {
        format!("QUALIFIED DESIGNER: {}   {}", project.designer, project.designer_bcin)
    };
    if !designer_line.is_empty() {
        let _ = writeln!(
            s,
            r#"<text x="{x}" y="{y}" font-family="Arial, sans-serif" font-size="4.2" fill="rgb(51,51,51)">{d}</text>"#,
            x = x0 + 5.0, y = y0 + 25.0, d = esc(&designer_line),
        );
    }
    // Divider, then the drawing title (large, centred).
    let _ = writeln!(
        s,
        r#"<line x1="{x0}" y1="{y}" x2="{x1}" y2="{y}" stroke="black" stroke-width="0.6"/>"#,
        y = y0 + 30.0, x1 = x0 + TB_W,
    );
    let _ = writeln!(
        s,
        r#"<text x="{cx}" y="{y}" font-family="Arial, sans-serif" font-size="9" font-weight="bold" fill="black" text-anchor="middle">{t}</text>"#,
        cx = x0 + TB_W * 0.5, y = y0 + 43.0, t = esc(&info.title),
    );
    // Divider, then SHEET / SCALE / DATE cells.
    let cells_y = y0 + 48.0;
    let _ = writeln!(
        s,
        r#"<line x1="{x0}" y1="{cells_y}" x2="{x1}" y2="{cells_y}" stroke="black" stroke-width="0.6"/>"#,
        x1 = x0 + TB_W,
    );
    let cw = TB_W / 3.0;
    for (i, (label, value)) in [
        ("SHEET", info.number.as_str()),
        ("SCALE", scale_label),
        ("DATE", info.date.as_str()),
    ]
    .into_iter()
    .enumerate()
    {
        let cx = x0 + (i as f32) * cw;
        if i > 0 {
            let _ = writeln!(
                s,
                r#"<line x1="{cx}" y1="{cells_y}" x2="{cx}" y2="{y2}" stroke="black" stroke-width="0.6"/>"#,
                y2 = y0 + TB_H,
            );
        }
        let _ = writeln!(
            s,
            r#"<text x="{lx}" y="{ly}" font-family="Arial, sans-serif" font-size="3.2" fill="rgb(102,102,102)">{label}</text>"#,
            lx = cx + 3.0, ly = cells_y + 6.0,
        );
        let _ = writeln!(
            s,
            r#"<text x="{vx}" y="{vy}" font-family="Arial, sans-serif" font-size="5.5" font-weight="bold" fill="black">{v}</text>"#,
            vx = cx + 3.0, vy = cells_y + 13.5, v = esc(value),
        );
    }
    s
}

#[cfg(test)]
mod tests {
    use super::*;

    fn dummy_drawing(scale_denominator: f32) -> SheetDrawing {
        // A 10 m × 8 m plan authored at 10 units/mm (floor-plan convention):
        // viewBox is 100000 × 80000 units.
        let svg = concat!(
            "<?xml version=\"1.0\"?>\n",
            "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"1000\" height=\"800\" ",
            "viewBox=\"0 0 100000 80000\">\n",
            "<rect width=\"100%\" height=\"100%\" fill=\"white\"/>\n",
            "<rect x=\"0\" y=\"0\" width=\"100000\" height=\"80000\" fill=\"none\" stroke=\"#000\"/>\n",
            "</svg>\n",
        );
        SheetDrawing {
            svg: svg.to_string(),
            model_units_per_mm: 10.0,
            scale_denominator,
            caption: String::new(),
        }
    }

    fn info() -> DrawingInfo {
        DrawingInfo {
            title: "FLOOR PLAN - LEVEL 1".into(),
            number: "A-101".into(),
            scale: "1:50".into(),
            date: "2026-06-08".into(),
            ..Default::default()
        }
    }

    #[test]
    fn arch_d_is_default_landscape() {
        let p = PaperSize::default();
        assert_eq!(p.name, "ARCH D");
        assert!(p.w_mm > p.h_mm);
    }

    #[test]
    fn sheet_has_paper_size_viewbox_and_title_block() {
        let (svg, _) = compose_sheet(
            &dummy_drawing(50.0),
            PaperSize::ARCH_D,
            &ProjectInfo { name: "Test House".into(), ..Default::default() },
            &info(),
        );
        assert!(svg.contains(r#"viewBox="0 0 914 610""#), "ARCH D page");
        assert!(svg.contains("FLOOR PLAN - LEVEL 1"));
        assert!(svg.contains("1 : 50"));
        assert!(svg.contains("Test House"));
        assert!(svg.ends_with("</svg>\n"));
        // The drawing's full-bleed white rect must be stripped.
        assert!(!svg.contains(r#"<rect width="100%" height="100%" fill="white"/>
<rect x="0" y="0" width="100000""#));
    }

    #[test]
    fn true_scale_sizing_is_correct() {
        // 10 m wide at 1:50 → 200 mm on paper.
        let (_, place) = compose_sheet(
            &dummy_drawing(50.0),
            PaperSize::ARCH_D,
            &ProjectInfo::default(),
            &info(),
        );
        assert!((place.content_w_mm - 200.0).abs() < 0.5, "w={}", place.content_w_mm);
        assert!((place.content_h_mm - 160.0).abs() < 0.5, "h={}", place.content_h_mm);
        assert!(!place.overflows, "10 m plan at 1:50 fits ARCH D");
    }

    #[test]
    fn overflow_is_flagged_when_scale_too_large() {
        // Same plan at 1:10 → 1000 mm wide, far past ARCH D's ~890 mm area.
        let (_, place) = compose_sheet(
            &dummy_drawing(10.0),
            PaperSize::ARCH_D,
            &ProjectInfo::default(),
            &info(),
        );
        assert!(place.overflows, "1:10 should overflow ARCH D");
    }

    #[test]
    fn multi_up_places_each_drawing_with_a_caption() {
        let a = SheetDrawing { caption: "PLAN L1".into(), ..dummy_drawing(100.0) };
        let b = SheetDrawing { caption: "PLAN L2".into(), ..dummy_drawing(100.0) };
        let (svg, places) = compose_multi(
            &[a, b],
            2,
            PaperSize::ARCH_D,
            &ProjectInfo { name: "Test".into(), ..Default::default() },
            &DrawingInfo { title: "FLOOR PLANS".into(), number: "A-101".into(), date: "2026-06-08".into(), ..Default::default() },
        );
        assert_eq!(places.len(), 2);
        // Each cell gets its own clip id.
        assert!(svg.contains("area0") && svg.contains("area1"));
        // Per-drawing captions with scale, plus the sheet title in the block.
        assert!(svg.contains("PLAN L1"), "missing L1 caption");
        assert!(svg.contains("PLAN L2"), "missing L2 caption");
        assert!(svg.contains("FLOOR PLANS"), "missing sheet title");
        // At 1:100 a 10 m plan = 100 mm, easily inside a half-width D cell.
        assert!(places.iter().all(|p| !p.overflows));
    }

    #[test]
    fn title_block_sits_in_the_bottom_right_corner() {
        let (svg, _) = compose_sheet(
            &dummy_drawing(50.0),
            PaperSize::ARCH_D,
            &ProjectInfo::default(),
            &info(),
        );
        // Corner box: top edge h-border-TB_H = 610-12-64 = 534;
        // left edge w-border-TB_W = 914-12-195 = 707.
        assert!(svg.contains(r#"y="534""#), "corner block not at expected y: {svg}");
        assert!(svg.contains(r#"x="707""#), "corner block not at expected x: {svg}");
    }
}
