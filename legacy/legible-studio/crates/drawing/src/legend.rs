//! Symbols legend: a self-contained key explaining the floor-plan symbols
//! (doors, windows, life-safety alarms, electrical, section cut). Authored in a
//! plain y-down SVG space so it can be placed on a sheet like any drawing.

use std::fmt::Write as _;

/// Render the standard symbols legend as an SVG string.
#[must_use]
pub fn generate_symbols_legend_svg() -> String {
    // Row layout (legend units ≈ px).
    const W: f32 = 900.0;
    const TITLE_H: f32 = 90.0;
    const ROW_H: f32 = 92.0;
    const GX: f32 = 95.0; // glyph column centre
    const LX: f32 = 210.0; // label left

    let rows: &[&str] = &[
        "door", "window", "smoke", "co", "light", "switch", "receptacle", "gfci", "section",
    ];
    let h = TITLE_H + ROW_H * rows.len() as f32 + 20.0;

    let mut s = String::with_capacity(4096);
    s.push_str("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n");
    let _ = writeln!(
        s,
        r#"<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{h}" viewBox="0 0 {W} {h}">"#,
    );
    s.push_str("<rect width=\"100%\" height=\"100%\" fill=\"white\"/>\n");
    // Outer border.
    let _ = writeln!(
        s,
        r#"<rect x="4" y="4" width="{w}" height="{hh}" fill="none" stroke="black" stroke-width="3"/>"#,
        w = W - 8.0,
        hh = h - 8.0,
    );
    // Title.
    let _ = writeln!(
        s,
        r#"<text x="{tx}" y="58" font-family="Arial, sans-serif" font-size="44" font-weight="bold" text-anchor="middle" fill="black">SYMBOLS LEGEND</text>"#,
        tx = W * 0.5,
    );
    let _ = writeln!(
        s,
        r#"<line x1="12" y1="{y}" x2="{x2}" y2="{y}" stroke="black" stroke-width="2"/>"#,
        y = TITLE_H,
        x2 = W - 12.0,
    );

    for (i, kind) in rows.iter().enumerate() {
        let cy = TITLE_H + ROW_H * (i as f32 + 0.5);
        draw_glyph(&mut s, kind, GX, cy);
        let label = label_for(kind);
        let _ = writeln!(
            s,
            r#"<text x="{LX}" y="{ly}" font-family="Arial, sans-serif" font-size="34" fill="black">{label}</text>"#,
            ly = cy + 12.0,
        );
        // Row divider.
        if i + 1 < rows.len() {
            let _ = writeln!(
                s,
                r#"<line x1="12" y1="{y}" x2="{x2}" y2="{y}" stroke="rgb(200,200,200)" stroke-width="1"/>"#,
                y = TITLE_H + ROW_H * (i as f32 + 1.0),
                x2 = W - 12.0,
            );
        }
    }

    s.push_str("</svg>\n");
    s
}

fn label_for(kind: &str) -> &'static str {
    match kind {
        "door" => "DOOR — swing direction",
        "window" => "WINDOW",
        "smoke" => "SMOKE ALARM (OBC 9.10.19)",
        "co" => "CARBON-MONOXIDE ALARM (OBC 9.33.4)",
        "light" => "LIGHT FIXTURE",
        "switch" => "WALL SWITCH",
        "receptacle" => "DUPLEX RECEPTACLE",
        "gfci" => "GFCI RECEPTACLE",
        "section" => "SECTION CUT / SHEET REF.",
        _ => "",
    }
}

/// Draw one symbol glyph centred at `(cx, cy)`, matching the floor-plan markers.
fn draw_glyph(s: &mut String, kind: &str, cx: f32, cy: f32) {
    match kind {
        "door" => {
            // Leaf up from the hinge, convex quarter-circle swing to the jamb.
            let (hx, hy) = (cx - 26.0, cy + 28.0);
            let _ = writeln!(
                s,
                r#"<line x1="{hx}" y1="{hy}" x2="{hx}" y2="{ty}" stroke="black" stroke-width="3"/>"#,
                ty = hy - 56.0,
            );
            let _ = writeln!(
                s,
                r#"<path d="M {hx} {ty} A 56 56 0 0 1 {rx} {hy}" fill="none" stroke="black" stroke-width="3"/>"#,
                ty = hy - 56.0,
                rx = hx + 56.0,
            );
        }
        "window" => {
            let _ = writeln!(
                s,
                r#"<line x1="{l}" y1="{y1}" x2="{r}" y2="{y1}" stroke="black" stroke-width="3"/>"#,
                l = cx - 45.0, r = cx + 45.0, y1 = cy - 7.0,
            );
            let _ = writeln!(
                s,
                r#"<line x1="{l}" y1="{y2}" x2="{r}" y2="{y2}" stroke="black" stroke-width="3"/>"#,
                l = cx - 45.0, r = cx + 45.0, y2 = cy + 7.0,
            );
        }
        "smoke" | "co" => {
            let label = if kind == "co" { "CO" } else { "S" };
            let _ = writeln!(
                s,
                r#"<circle cx="{cx}" cy="{cy}" r="30" fill="white" stroke="rgb(204,0,0)" stroke-width="4"/>"#,
            );
            let _ = writeln!(
                s,
                r#"<text x="{cx}" y="{ty}" font-family="Arial, sans-serif" font-size="30" font-weight="bold" text-anchor="middle" fill="rgb(204,0,0)">{label}</text>"#,
                ty = cy + 11.0,
            );
        }
        "light" => {
            let _ = writeln!(
                s,
                r#"<circle cx="{cx}" cy="{cy}" r="24" fill="none" stroke="rgb(221,136,0)" stroke-width="4"/>"#,
            );
            let _ = writeln!(
                s,
                r#"<line x1="{l}" y1="{cy}" x2="{r}" y2="{cy}" stroke="rgb(221,136,0)" stroke-width="4"/>"#,
                l = cx - 24.0, r = cx + 24.0,
            );
            let _ = writeln!(
                s,
                r#"<line x1="{cx}" y1="{t}" x2="{cx}" y2="{b}" stroke="rgb(221,136,0)" stroke-width="4"/>"#,
                t = cy - 24.0, b = cy + 24.0,
            );
        }
        "switch" => {
            let _ = writeln!(
                s,
                r#"<text x="{cx}" y="{ty}" font-family="Arial, sans-serif" font-size="34" font-weight="bold" text-anchor="middle" fill="rgb(0,102,204)">S</text>"#,
                ty = cy + 12.0,
            );
        }
        "receptacle" => {
            let _ = writeln!(
                s,
                r#"<circle cx="{cx}" cy="{cy}" r="18" fill="white" stroke="rgb(0,102,204)" stroke-width="4"/>"#,
            );
        }
        "gfci" => {
            let _ = writeln!(
                s,
                r#"<circle cx="{cx}" cy="{cy}" r="22" fill="white" stroke="rgb(0,102,204)" stroke-width="4"/>"#,
            );
            let _ = writeln!(
                s,
                r#"<text x="{cx}" y="{ty}" font-family="Arial, sans-serif" font-size="26" font-weight="bold" text-anchor="middle" fill="rgb(0,102,204)">G</text>"#,
                ty = cy + 9.0,
            );
        }
        "section" => {
            let _ = writeln!(
                s,
                r#"<line x1="{l}" y1="{cy}" x2="{cx}" y2="{cy}" stroke="black" stroke-width="2" stroke-dasharray="10,5"/>"#,
                l = cx - 50.0,
            );
            let _ = writeln!(
                s,
                r#"<circle cx="{cx}" cy="{cy}" r="26" fill="white" stroke="black" stroke-width="3"/>"#,
            );
            let _ = writeln!(
                s,
                r#"<text x="{cx}" y="{ty}" font-family="Arial, sans-serif" font-size="28" font-weight="bold" text-anchor="middle" fill="black">A</text>"#,
                ty = cy + 10.0,
            );
        }
        _ => {}
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn legend_is_well_formed_and_lists_symbols() {
        let s = generate_symbols_legend_svg();
        assert!(s.starts_with("<?xml"));
        assert!(s.ends_with("</svg>\n"));
        assert!(s.contains("SYMBOLS LEGEND"));
        assert!(s.contains("SMOKE ALARM (OBC 9.10.19)"));
        assert!(s.contains("CARBON-MONOXIDE ALARM (OBC 9.33.4)"));
        assert!(s.contains("GFCI RECEPTACLE"));
        // Door swing arc present.
        assert!(s.contains("<path d=\"M"));
    }
}
