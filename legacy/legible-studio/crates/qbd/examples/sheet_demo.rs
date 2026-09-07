//! Compose the floor plan onto an ARCH-D sheet at true 1:50 and write the SVG.
//! Empirical check for the sheet-layout system.
//!
//!     cargo run --release -p ls-qbd --example sheet_demo -- <building.json> <out.svg>

fn main() {
    let mut args = std::env::args().skip(1);
    let building = args.next().expect("usage: sheet_demo <building.json> <out.svg>");
    let out = args.next().expect("usage: sheet_demo <building.json> <out.svg>");

    let doc = archgeometry::parse_file(&building).expect("parse building.json");
    let project = drawing::ProjectInfo {
        name: "12 Test St, Toronto".into(),
        address: "Lot 7, Plan 42M-1234".into(),
        designer: "J. Smith".into(),
        designer_bcin: "BCIN 112233".into(),
        climate_zone: "Zone 6".into(),
        ..Default::default()
    };

    // Freeform export: place the first two catalogue drawings in boxes, exactly
    // as the in-app editor's export does (drawing::compose_freeform).
    let cat = qbd::drawing_catalog(&doc, "Zone 6");
    eprintln!("catalogue: {} drawings", cat.len());
    // Dump the symbols legend next to the output for inspection.
    if let Some(l) = cat.iter().find(|c| c.title == "SYMBOLS LEGEND") {
        let lp = std::path::Path::new(&out).with_file_name("_legend.svg");
        std::fs::write(&lp, &l.svg).ok();
        eprintln!("wrote {}", lp.display());
    }
    let mut items = Vec::new();
    if let Some(a) = cat.first() {
        items.push(drawing::FreePlacement {
            svg: a.svg.clone(),
            x_mm: 30.0,
            y_mm: 30.0,
            w_mm: 380.0,
            h_mm: 300.0,
            caption: a.title.clone(),
        });
    }
    if let Some(b) = cat.get(1) {
        items.push(drawing::FreePlacement {
            svg: b.svg.clone(),
            x_mm: 470.0,
            y_mm: 30.0,
            w_mm: 380.0,
            h_mm: 300.0,
            caption: b.title.clone(),
        });
    }
    let info = drawing::DrawingInfo {
        title: "SHEET 1".into(),
        number: "A-101".into(),
        scale: "AS NOTED".into(),
        date: "2026-06-08".into(),
        ..Default::default()
    };
    let svg = drawing::compose_freeform(&items, drawing::PaperSize::ARCH_D, &project, &info);
    std::fs::write(&out, &svg).expect("write svg");
    eprintln!("wrote {out} ({} placement(s))", items.len());
}
