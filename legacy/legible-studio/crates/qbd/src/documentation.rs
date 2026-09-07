//! Top-level documentation pipeline: SchemaDocument → permit-set SVG +
//! per-wall-type section details.
//!
//! Ported from `QBDInterface::generateDocumentation`
//! (`qbd_interface.cpp:948`) + `generateWallDetails` (`:1131-1156`).

use archgeometry::SchemaDocument;
use std::fmt::Write as _;
use drawing::{
    Config, DrawingInfo, DrawingType, ElevationDirection, ElevationInput, ElevationOpeningInput,
    ElevationWallInput, FootingSpec, JoistSpec, ProjectInfo, SectionInput, SectionWallInput,
    SitePlan, WallSectionDetail, drawing_info_for, export_to_svg_padded,
    generate_elevation_sheet_svg, generate_footing_detail_svg, generate_foundation_plan_svg,
    generate_framing_plan_svg, generate_obc_notes_block, generate_section_sheet_svg,
    generate_site_plan_svg, generate_stair_section_svg, generate_wall_detail, notes_block_size_mm,
    title_block_box, wall_detail_to_svg, StairSectionSpec, TITLE_BLOCK_H, TITLE_BLOCK_W,
};

use crate::floor_plan::generate_floor_plan_with_openings;
use crate::wall_types;

/// One wall-section detail with its rendered SVG.
#[derive(Debug, Clone, Default)]
pub struct WallDetail {
    pub detail: WallSectionDetail,
    pub svg: String,
}

/// One elevation drawing.
#[derive(Debug, Clone)]
pub struct Elevation {
    pub direction: ElevationDirection,
    pub svg: String,
    /// ASCII DXF bytes for the same elevation geometry (no annotations).
    pub dxf: Vec<u8>,
}

/// Options controlling which sheets are produced in the documentation bundle.
///
/// The defaults produce the full permit set; callers can opt out of sheets
/// that are deferred to other consultants (e.g. the framing plan, which is
/// typically engineered separately).
#[derive(Debug, Clone)]
pub struct DocumentationOptions {
    /// Include the framing-plan sheet. Default: `true`.
    pub include_framing_plan: bool,
}

impl Default for DocumentationOptions {
    fn default() -> Self {
        Self {
            include_framing_plan: true,
        }
    }
}

impl DocumentationOptions {
    /// Full permit set.
    #[must_use]
    pub fn all() -> Self {
        Self::default()
    }

    /// Omit sheets typically produced by the structural engineer.
    #[must_use]
    pub fn without_engineer_sheets() -> Self {
        Self {
            include_framing_plan: false,
        }
    }
}

/// Permit-set bundle. Carries the floor-plan SVG plus the surrounding
/// permit-set sheets (site plan, elevations, section, wall details) for
/// the parts the Rust pipeline ports today.
#[derive(Debug, Clone, Default)]
pub struct Documentation {
    pub project_name: String,
    pub generated_date: String,
    pub site_plan_svg: String,
    /// Roof plan (gable/hip): ridge, hips, pitch.
    pub roof_plan_svg: String,
    /// Ground-floor (Level 1) plan — kept for back-compat / single-storey.
    pub floor_plan_svg: String,
    /// ASCII DXF for the ground-floor plan geometry (walls, openings, hatches).
    pub floor_plan_dxf: Vec<u8>,
    /// One `(level name, SVG)` per storey; `floor_plan_svg` is the first.
    pub floor_plans: Vec<(String, String)>,
    pub elevations: Vec<Elevation>,
    pub section_svg: String,
    pub wall_details: Vec<WallDetail>,
    /// Door schedule SVG, empty string if the building has no doors.
    pub door_schedule_svg: String,
    /// Window schedule SVG, empty string if the building has no windows.
    pub window_schedule_svg: String,
    /// Foundation plan — footing outline under exterior walls, slab edge.
    pub foundation_plan_svg: String,
    /// Framing plan — joist direction + spacing per room, midspan beams.
    pub framing_plan_svg: String,
    /// Typical footing detail — section through gravel/footing/wall + rebar.
    pub footing_detail_svg: String,
    /// Typical stair section — rise/run sawtooth + headroom + handrail.
    /// Empty when the building has no stairs (single storey).
    pub stair_section_svg: String,
    /// Code compliance report — tabular wall-by-wall pass/fail summary.
    pub compliance_report_svg: String,
}

/// Convert an SVG string to a PDF byte vector using `svg2pdf`.
///
/// Page size is derived from the SVG's `viewBox` (mm units, 1 user unit = 1 mm).
/// Text is embedded as selectable text by default.
///
/// # Errors
///
/// Returns `svg2pdf::ConversionError` if the SVG is malformed or contains
/// unsupported features.
/// Errors from SVG → PDF conversion.
#[derive(Debug, thiserror::Error)]
pub enum PdfError {
    /// The SVG parser rejected the input.
    #[error("svg parse: {0}")]
    Parse(String),
    /// The PDF conversion failed.
    #[error("pdf conversion: {0}")]
    Conversion(String),
}

/// Longest page side, in PDF points, for a normalised sheet (≈19.4").
///
/// svg2pdf maps 1 user-unit -> 1 pt at 72 dpi. Our sheets are authored in
/// millimetres, so the raw size would produce absurd multi-metre pages (e.g. a
/// floor plan at ~167000 pt ≈ 59 m wide) that PDF viewers can't render. We
/// normalise every page so its longest side is `TARGET_PT`, preserving aspect.
const TARGET_PT: f32 = 1400.0;

/// Parse an SVG sheet into a usvg `Tree` with system fonts loaded.
fn parse_sheet(svg: &str) -> Result<svg2pdf::usvg::Tree, PdfError> {
    let mut opts = svg2pdf::usvg::Options::default();
    opts.fontdb_mut().load_system_fonts();
    svg2pdf::usvg::Tree::from_str(svg, &opts).map_err(|e| PdfError::Parse(e.to_string()))
}

/// Convert an SVG string to a single-page PDF byte vector using `svg2pdf`.
///
/// Page size is derived from the SVG's natural size (viewBox or width/height),
/// normalised to [`TARGET_PT`]. Text is embedded as selectable text by default.
pub fn svg_to_pdf(svg: &str) -> Result<Vec<u8>, PdfError> {
    use svg2pdf::{ConversionOptions, PageOptions};
    let tree = parse_sheet(svg)?;
    let size = tree.size();
    let max_side = size.width().max(size.height());
    let dpi = if max_side > TARGET_PT { max_side * 72.0 / TARGET_PT } else { 72.0 };
    let page = PageOptions { dpi, ..PageOptions::default() };
    svg2pdf::to_pdf(&tree, ConversionOptions::default(), page)
        .map_err(|e| PdfError::Conversion(e.to_string()))
}

/// Assemble many SVG sheets into one multi-page PDF — the permit set as a single
/// document. Each sheet becomes one page, sized to [`TARGET_PT`] on its longest
/// side (aspect preserved). Pure Rust: `svg2pdf::to_chunk` turns each sheet into
/// an embeddable XObject and `pdf-writer` lays them out across pages. Sheets that
/// fail to parse are skipped (their `name` is returned in the error only if *all*
/// fail).
///
/// `sheets` is a list of `(name, svg)`; `name` currently just documents order
/// (and feeds the page label / errors).
pub fn svgs_to_pdf(sheets: &[(String, String)]) -> Result<Vec<u8>, PdfError> {
    use pdf_writer::{Content, Finish, Name, Pdf, Rect, Ref};
    use svg2pdf::ConversionOptions;

    let mut alloc = Ref::new(1);
    let catalog_id = alloc.bump();
    let page_tree_id = alloc.bump();

    // Convert each sheet to a chunk + page now so we know the page count and
    // can collect their refs for the page tree's /Kids.
    struct Page {
        page_id: Ref,
        content_id: Ref,
        svg_id: Ref,
        chunk: pdf_writer::Chunk,
        w: f32,
        h: f32,
    }
    let mut pages: Vec<Page> = Vec::new();
    for (name, svg) in sheets {
        let tree = match parse_sheet(svg) {
            Ok(t) => t,
            Err(e) => {
                eprintln!("  skipping unparseable sheet {name}: {e}");
                continue;
            }
        };
        let size = tree.size();
        let max_side = size.width().max(size.height()).max(1.0);
        let k = TARGET_PT / max_side;
        let (w, h) = (size.width() * k, size.height() * k);

        let (chunk, svg_ref) = svg2pdf::to_chunk(&tree, ConversionOptions::default())
            .map_err(|e| PdfError::Conversion(e.to_string()))?;
        // Renumber the chunk's objects into our document's id space.
        let mut map = std::collections::HashMap::new();
        let chunk = chunk.renumber(|old| *map.entry(old).or_insert_with(|| alloc.bump()));
        let svg_id = *map.get(&svg_ref).expect("renumbered svg root present");

        pages.push(Page {
            page_id: alloc.bump(),
            content_id: alloc.bump(),
            svg_id,
            chunk,
            w,
            h,
        });
    }
    if pages.is_empty() {
        return Err(PdfError::Conversion("no sheets could be converted".into()));
    }

    let mut pdf = Pdf::new();
    pdf.catalog(catalog_id).pages(page_tree_id);
    pdf.pages(page_tree_id)
        .kids(pages.iter().map(|p| p.page_id))
        .count(pages.len() as i32);

    let svg_name = Name(b"S1");
    for p in &pages {
        // The to_chunk XObject is a 1pt unit square; scale it to fill the page
        // (aspect already baked into w/h, so no distortion).
        let mut page = pdf.page(p.page_id);
        page.media_box(Rect::new(0.0, 0.0, p.w, p.h));
        page.parent(page_tree_id);
        page.resources().x_objects().pair(svg_name, p.svg_id);
        page.contents(p.content_id);
        page.finish();

        let mut content = Content::new();
        content.transform([p.w, 0.0, 0.0, p.h, 0.0, 0.0]).x_object(svg_name);
        pdf.stream(p.content_id, &content.finish());

        pdf.extend(&p.chunk);
    }
    Ok(pdf.finish())
}

/// Geometry export scale for the floor plan: `export_to_svg` maps plan
/// `(x, y)` to SVG `(x*scale, -y*scale)`. Annotations are authored in plan-mm
/// and lifted into this space by [`lift`].
const FP_SCALE: f32 = 10.0;
/// Pre-scale padding (mm) so dimensions that sit outside the building footprint
/// (overall + structural-grid tiers) aren't clipped by the tight viewBox.
const FP_PAD: f32 = 2500.0;

/// Lift a plan-mm annotation fragment into the floor plan's exported space.
/// Y is pre-negated in the dim inputs (keeping glyphs upright), so all that
/// remains is the uniform magnitude scale — a positive `scale()` group, which
/// does not mirror text.
fn lift(fragment: &str) -> String {
    if fragment.is_empty() {
        return String::new();
    }
    format!("<g transform=\"scale({FP_SCALE})\">\n{fragment}</g>\n")
}

/// Flip a horizontal dim's perpendicular offset (its Y) to match the geometry's
/// negated Y. The dimensioned axis (`from`/`to`) is X and is left untouched.
fn flip_h(mut d: drawing::LinearDim) -> drawing::LinearDim {
    d.offset = -d.offset;
    d
}

/// Flip a vertical dim's Y endpoints; its offset is X and is left untouched.
fn flip_v(mut d: drawing::LinearDim) -> drawing::LinearDim {
    d.from = -d.from;
    d.to = -d.to;
    d
}

/// Non-roof level names in document order. Falls back to a single
/// `"Level 1"` for documents that predate the `levels` array.
fn level_names(doc: &SchemaDocument) -> Vec<String> {
    let names: Vec<String> = doc
        .levels
        .iter()
        .map(|l| l.name.clone())
        .filter(|n| !n.to_lowercase().contains("roof"))
        .collect();
    if names.is_empty() {
        vec!["Level 1".to_string()]
    } else {
        names
    }
}

/// A view of `doc` restricted to one `level`: only that level's walls, rooms,
/// and the doors/windows on those walls. Wall indices are remapped to the
/// filtered list so door/window `wall_index` references stay valid.
fn filter_doc_to_level(doc: &SchemaDocument, level: &str) -> SchemaDocument {
    use std::collections::HashMap;
    let mut remap: HashMap<usize, usize> = HashMap::new();
    let mut walls = Vec::new();
    for (gi, w) in doc.walls.iter().enumerate() {
        if w.level_name == level {
            remap.insert(gi, walls.len());
            walls.push(w.clone());
        }
    }
    let map_idx = |gi: i32| -> Option<i32> {
        usize::try_from(gi)
            .ok()
            .and_then(|u| remap.get(&u))
            .and_then(|&l| i32::try_from(l).ok())
    };
    let doors = doc
        .doors
        .iter()
        .filter_map(|d| {
            map_idx(d.wall_index).map(|li| {
                let mut d2 = d.clone();
                d2.wall_index = li;
                d2
            })
        })
        .collect();
    let windows = doc
        .windows
        .iter()
        .filter_map(|w| {
            map_idx(w.wall_index).map(|li| {
                let mut w2 = w.clone();
                w2.wall_index = li;
                w2
            })
        })
        .collect();
    let rooms = doc
        .rooms
        .iter()
        .filter(|(_, r)| r.level == level)
        .map(|(k, v)| (k.clone(), v.clone()))
        .collect();
    let detectors = doc.detectors.iter().filter(|d| d.level_name == level).cloned().collect();
    let electrical = doc.electrical.iter().filter(|e| e.level_name == level).cloned().collect();
    let headers = doc.headers.iter().filter(|h| h.level_name == level).cloned().collect();
    let stairs = doc.stairs.iter().filter(|s| s.level_name == level).cloned().collect();
    SchemaDocument {
        walls,
        doors,
        windows,
        rooms,
        detectors,
        electrical,
        headers,
        stairs,
        ..doc.clone()
    }
}

/// Build the raw [`SliceResult`] for a floor plan (walls, openings, hatches).
/// Used by the DXF export path which needs editable geometry, not annotated
/// SVG.
/// Build a typical stair-section spec from the building's stairs, or `None`
/// when there are none (single-storey). All shafts share the same rise/run, so
/// one section is representative — take the first stair.
fn stair_section_for(doc: &SchemaDocument) -> Option<StairSectionSpec> {
    let st = doc.stairs.first()?;
    Some(StairSectionSpec {
        num_risers: st.num_risers,
        num_treads: st.num_treads,
        riser_height_mm: if st.riser_height > 0.0 { st.riser_height } else { 190.5 },
        tread_run_mm: if st.tread_run > 0.0 { st.tread_run } else { 255.0 },
        floor_to_floor_mm: if st.floor_to_floor > 0.0 { st.floor_to_floor } else { 3048.0 },
        headroom_min_mm: obc::stairs::MIN_HEADROOM_MM,
        ..StairSectionSpec::default()
    })
}

fn build_floor_plan_slice_result(doc: &SchemaDocument, config: &Config) -> drawing::SliceResult {
    let cut_height = 1219.0;
    generate_floor_plan_with_openings(doc, cut_height, config)
}

/// Build one floor-plan SVG (geometry + dimension tiers + room labels, no
/// title block) for the given document view. Pass a level-filtered doc for a
/// single storey; the footprint dims come from `doc.width`/`doc.depth`.
#[allow(clippy::too_many_lines, clippy::uninlined_format_args)] // sequential annotation injection
fn build_floor_plan_svg(doc: &SchemaDocument, config: &Config) -> String {
    let cut_height = 1219.0;
    let result = generate_floor_plan_with_openings(doc, cut_height, config);
    // Pad the viewBox so the out-of-footprint dimension tiers below aren't
    // clipped. Annotations are injected in plan-mm + lifted via `lift`.
    let mut floor_plan_raw = export_to_svg_padded(&result, FP_SCALE, FP_PAD);
    // Tier-1 overall dimensions: width below the footprint, depth to the left.
    if doc.width > 0.0 && doc.depth > 0.0 {
        let width_dim = flip_h(drawing::LinearDim::horizontal_mm(0.0, doc.width, doc.depth + 500.0));
        let depth_dim = flip_v(drawing::LinearDim::vertical_mm(0.0, doc.depth, -500.0));
        let mut dims = String::new();
        dims.push_str(&drawing::render_horizontal_dim(&width_dim, 250.0));
        dims.push_str(&drawing::render_vertical_dim(&depth_dim, 250.0));
        floor_plan_raw = inject_before_svg_close(&floor_plan_raw, &lift(&dims));
    }
    // Room labels + per-room (tier-4) + structural-grid (tier-2) dimensions.
    if !doc.rooms.is_empty() {
        let mut rooms: Vec<_> = doc.rooms.iter().collect();
        rooms.sort_by(|a, b| a.0.cmp(b.0));

        let room_labels: Vec<drawing::RoomLabelInput> = rooms
            .iter()
            .map(|(_id, r)| drawing::RoomLabelInput {
                name: if r.name.is_empty() { r.id.clone() } else { r.name.clone() },
                bounds_x: r.bounds.x,
                // Flip Y into the export's negated-Y space.
                bounds_y: -(r.bounds.y + r.bounds.height),
                width: r.bounds.width,
                height: r.bounds.height,
                area_mm2: r.area,
            })
            .collect();
        let labels_svg = drawing::render_room_labels(&room_labels, 250.0);
        floor_plan_raw = inject_before_svg_close(&floor_plan_raw, &lift(&labels_svg));

        let mut tier4 = String::new();
        for (_id, r) in &rooms {
            if r.bounds.width < 600.0 || r.bounds.height < 600.0 {
                continue;
            }
            let (w_dim, h_dim) =
                drawing::room_interior_dims(r.bounds.x, r.bounds.y, r.bounds.width, r.bounds.height, 150.0);
            tier4.push_str(&drawing::render_horizontal_dim(&flip_h(w_dim), 140.0));
            tier4.push_str(&drawing::render_vertical_dim(&flip_v(h_dim), 140.0));
        }
        if !tier4.is_empty() {
            floor_plan_raw = inject_before_svg_close(&floor_plan_raw, &lift(&tier4));
        }

        let dedup = |mut vs: Vec<f32>| -> Vec<f32> {
            vs.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
            vs.dedup_by(|a, b| (*a - *b).abs() < 1.0);
            vs
        };
        let xs: Vec<f32> = dedup(
            rooms.iter().flat_map(|(_, r)| [r.bounds.x, r.bounds.x + r.bounds.width]).collect(),
        );
        let zs: Vec<f32> = dedup(
            rooms.iter().flat_map(|(_, r)| [r.bounds.y, r.bounds.y + r.bounds.height]).collect(),
        );
        let mut tier2 = String::new();
        for d in drawing::chain_dims(&xs, -1100.0, true) {
            tier2.push_str(&drawing::render_horizontal_dim(&flip_h(d), 180.0));
        }
        for d in drawing::chain_dims(&zs, doc.width + 1100.0, false) {
            tier2.push_str(&drawing::render_vertical_dim(&flip_v(d), 180.0));
        }
        if !tier2.is_empty() {
            floor_plan_raw = inject_before_svg_close(&floor_plan_raw, &lift(&tier2));
        }
    }

    // Tier-3: opening-location dimensions — locate each door/window along its
    // exterior wall, chained from the corners, on a line outside that wall.
    {
        const EPS: f32 = 1.0;
        const OFF: f32 = 2000.0; // mm outside the wall (within FP_PAD)
        let mut t3 = String::new();
        for (wi, w) in doc.walls.iter().enumerate() {
            if w.category != "exterior" {
                continue;
            }
            let (sx, sz, ex, ez) = (w.start.x, w.start.z, w.end.x, w.end.z);
            let horizontal = (sz - ez).abs() < EPS;
            if !horizontal && (sx - ex).abs() >= EPS {
                continue; // not axis-aligned
            }
            // Opening centres along this wall (doors carry absolute x/y;
            // windows are offset along the wall).
            let on_wall = |idx: i32| usize::try_from(idx).ok() == Some(wi);
            let len = ((ex - sx).powi(2) + (ez - sz).powi(2)).sqrt().max(1.0);
            // Centre of an opening, projected to the dimensioned axis. Doors
            // carry offset-to-centre; windows offset-to-start (+half width).
            let project = |along: f32| {
                if horizontal {
                    sx + (ex - sx) / len * along
                } else {
                    sz + (ez - sz) / len * along
                }
            };
            let mut stops: Vec<f32> = Vec::new();
            for d in doc.doors.iter().filter(|d| on_wall(d.wall_index)) {
                stops.push(project(d.offset));
            }
            for win in doc.windows.iter().filter(|w| on_wall(w.wall_index)) {
                stops.push(project(win.offset + win.width * 0.5));
            }
            if stops.is_empty() {
                continue;
            }
            // Chain from corner to corner through the openings.
            let (lo, hi) = if horizontal { (sx.min(ex), sx.max(ex)) } else { (sz.min(ez), sz.max(ez)) };
            stops.push(lo);
            stops.push(hi);
            stops.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
            stops.dedup_by(|a, b| (*a - *b).abs() < 1.0);
            if horizontal {
                let line = if sz < doc.depth * 0.5 { sz - OFF } else { sz + OFF };
                for d in drawing::chain_dims(&stops, line, true) {
                    t3.push_str(&drawing::render_horizontal_dim(&flip_h(d), 150.0));
                }
            } else {
                let line = if sx < doc.width * 0.5 { sx - OFF } else { sx + OFF };
                for d in drawing::chain_dims(&stops, line, false) {
                    t3.push_str(&drawing::render_vertical_dim(&flip_v(d), 150.0));
                }
            }
        }
        if !t3.is_empty() {
            floor_plan_raw = inject_before_svg_close(&floor_plan_raw, &lift(&t3));
        }
    }

    // Stairs (OBC 9.8): tread nosings + a direction arrow + UP/DN label drawn
    // from the solved riser/tread geometry. `render_stair_symbol` already bakes
    // in the negated-Y plan convention, so it injects like the other passes.
    if !doc.stairs.is_empty() {
        let mut stairs = String::new();
        for st in &doc.stairs {
            let plan = drawing::StairPlan {
                x: st.x,
                y: st.y,
                across: st.width,
                run: st.depth,
                run_dir: if st.run_dir.is_empty() { "+y".into() } else { st.run_dir.clone() },
                num_treads: st.num_treads,
                tread_run: if st.tread_run > 0.0 { st.tread_run } else { 255.0 },
                shape: st.shape.clone(),
                going: st.going.clone(),
            };
            stairs.push_str(&drawing::render_stair_symbol(&plan, 280.0));
        }
        floor_plan_raw = inject_before_svg_close(&floor_plan_raw, &lift(&stairs));
    }

    // Life-safety alarms (rules-engine annotation): smoke = S, CO = CO, drawn
    // as a labelled disc at the device's plan position (Y pre-negated for the
    // export's flipped space).
    if !doc.detectors.is_empty() {
        let mut det = String::new();
        for d in &doc.detectors {
            let (cx, cy) = (d.x, -d.y);
            let label = if d.kind == "co" { "CO" } else { "S" };
            let _ = write!(
                det,
                concat!(
                    r##"    <circle cx="{cx}" cy="{cy}" r="200" fill="#fff" stroke="#c00" stroke-width="25"/>"##,
                    "\n",
                    r##"    <text x="{cx}" y="{ty}" font-family="Arial, sans-serif" font-size="220" font-weight="bold" text-anchor="middle" fill="#c00">{label}</text>"##,
                    "\n",
                ),
                cx = cx,
                cy = cy,
                ty = cy + 80.0,
                label = label,
            );
        }
        floor_plan_raw = inject_before_svg_close(&floor_plan_raw, &lift(&det));
    }

    // Electrical (rules-engine annotation): receptacle = small open circle on
    // the wall (GFCI labelled "G"), light = a circle-with-cross at the centre.
    if !doc.electrical.is_empty() {
        let mut elec = String::new();
        for e in &doc.electrical {
            let (cx, cy) = (e.x, -e.y);
            match e.kind.as_str() {
                "light" => {
                    let _ = write!(
                        elec,
                        concat!(
                            r##"    <circle cx="{cx}" cy="{cy}" r="160" fill="none" stroke="#d80" stroke-width="22"/>"##,
                            "\n",
                            r##"    <line x1="{l}" y1="{cy}" x2="{r}" y2="{cy}" stroke="#d80" stroke-width="22"/>"##,
                            "\n",
                            r##"    <line x1="{cx}" y1="{t}" x2="{cx}" y2="{b}" stroke="#d80" stroke-width="22"/>"##,
                            "\n",
                        ),
                        cx = cx, cy = cy,
                        l = cx - 160.0, r = cx + 160.0, t = cy - 160.0, b = cy + 160.0,
                    );
                }
                "switch" => {
                    // Wall switch: blue "S" (no disc — the smoke alarm's S is a
                    // red disc, so these don't collide).
                    let _ = write!(
                        elec,
                        r##"    <text x="{cx}" y="{ty}" font-family="Arial, sans-serif" font-size="200" font-weight="bold" text-anchor="middle" fill="#06c">S</text>"##,
                        cx = cx, ty = cy + 70.0,
                    );
                    elec.push('\n');
                }
                kind => {
                    // receptacle / gfci
                    let _ = write!(
                        elec,
                        r##"    <circle cx="{cx}" cy="{cy}" r="110" fill="#fff" stroke="#06c" stroke-width="22"/>"##,
                        cx = cx, cy = cy,
                    );
                    elec.push('\n');
                    if kind == "gfci" {
                        let _ = write!(
                            elec,
                            r##"    <text x="{cx}" y="{ty}" font-family="Arial, sans-serif" font-size="150" font-weight="bold" text-anchor="middle" fill="#06c">G</text>"##,
                            cx = cx, ty = cy + 55.0,
                        );
                        elec.push('\n');
                    }
                }
            }
        }
        floor_plan_raw = inject_before_svg_close(&floor_plan_raw, &lift(&elec));
    }

    // Section-cut marker (Phase 2.5): a dashed line at the default cut
    // with A-A bubbles at each end referencing sheet A-301. Only sensible
    // when the building has a real footprint.
    if doc.width > 0.0 && doc.depth > 0.0 {
        let section_input = drawing::SectionInput {
            width: doc.width,
            ..Default::default()
        };
        let cut = drawing::default_cut(&section_input);
        let marker = drawing::generate_section_marker(
            &cut,
            doc.width,
            doc.depth,
            DrawingType::SectionA.default_info().0,
        );
        floor_plan_raw = inject_before_svg_close(&floor_plan_raw, &lift(&marker));
    }

    // Header callouts (rules-engine annotation): the OBC member size over each
    // opening, labelled at the opening centre (red if flagged for engineer
    // review). Y pre-negated for the export's flipped space.
    if !doc.headers.is_empty() {
        let mut hdr = String::new();
        for h in &doc.headers {
            let fill = if h.needs_review { "#c00" } else { "#333" };
            let _ = write!(
                hdr,
                r#"    <text x="{cx}" y="{cy}" font-family="Arial, sans-serif" font-size="170" text-anchor="middle" fill="{fill}">{size}</text>"#,
                cx = h.x,
                cy = -h.y,
                fill = fill,
                size = h.size,
            );
            hdr.push('\n');
        }
        floor_plan_raw = inject_before_svg_close(&floor_plan_raw, &lift(&hdr));
    }
    floor_plan_raw
}

/// Generate documentation from a parsed schema. `scale` follows the C++
/// default of `10.0` (used at `qbd_interface.cpp:964`).
#[must_use]
#[allow(clippy::too_many_lines)] // Sequential sheet assembly; splitting hides the data flow.
pub fn generate_documentation(
    doc: &SchemaDocument,
    project_name: impl Into<String>,
) -> Documentation {
    generate_documentation_with_options(doc, project_name, DocumentationOptions::default())
}

/// Variant of [`generate_documentation`] with full sheet-selection control.
#[must_use]
#[allow(clippy::too_many_lines)]
pub fn generate_documentation_with_options(
    doc: &SchemaDocument,
    project_name: impl Into<String>,
    options: DocumentationOptions,
) -> Documentation {
    let project_name: String = project_name.into();
    let project = ProjectInfo {
        name: project_name,
        number: doc.building_id.clone(),
        solver: "QBD Layout".into(),
        ..Default::default()
    };
    generate_documentation_for_project_with_options(doc, project, options)
}

/// Variant of [`generate_documentation`] that takes the full
/// `ProjectInfo` — lets callers populate qualified-designer + BCIN fields
/// that flow into every sheet's title block.
#[must_use]
#[allow(clippy::too_many_lines)]
pub fn generate_documentation_for_project(
    doc: &SchemaDocument,
    project: ProjectInfo,
) -> Documentation {
    generate_documentation_for_project_with_options(doc, project, DocumentationOptions::default())
}

/// Variant of [`generate_documentation_for_project`] with full sheet-selection
/// control.
#[must_use]
#[allow(clippy::too_many_lines)]
pub fn generate_documentation_for_project_with_options(
    doc: &SchemaDocument,
    project: ProjectInfo,
    options: DocumentationOptions,
) -> Documentation {
    let config = Config::with_defaults();
    let project_name = project.name.clone();
    let date = today_iso();

    // Every sheet gets the same border + title block, sized as a fixed fraction
    // of that sheet's own page (uniform scale, bottom-right anchored) so the
    // block reads identically regardless of the drawing's scale or aspect.
    let with_tb = |svg: String, dt: DrawingType, scale: &str| -> String {
        let info = drawing_info_for(dt, scale, &date);
        inject_sheet_titleblock(&svg, &project, &info, false)
    };
    // Floor-plan variant: also stacks the OBC general-notes block immediately
    // above the title block. Permit convention puts the OBC 9.10.19 / 9.33.4
    // notes on the plan sheet itself.
    let with_tb_and_obc_notes = |svg: String, dt: DrawingType, scale: &str| -> String {
        let info = drawing_info_for(dt, scale, &date);
        inject_sheet_titleblock(&svg, &project, &info, true)
    };
    // Site and roof plans use the same consistent injector.
    let with_fitted_tb = |svg: String, dt: DrawingType, scale: &str| -> String {
        let info = drawing_info_for(dt, scale, &date);
        inject_sheet_titleblock(&svg, &project, &info, false)
    };

    // One floor plan per storey when the walls genuinely span multiple levels
    // (a single combined plan would overlay the floors on the shared
    // footprint). Single-storey / untagged documents render one combined plan,
    // preserving the legacy behaviour.
    let distinct: std::collections::HashSet<&str> = doc
        .walls
        .iter()
        .map(|w| w.level_name.as_str())
        .filter(|s| !s.is_empty())
        .collect();
    let floor_plans: Vec<(String, String)> = if distinct.len() > 1 {
        level_names(doc)
            .into_iter()
            .map(|ln| {
                let view = filter_doc_to_level(doc, &ln);
                let svg = with_tb_and_obc_notes(
                    build_floor_plan_svg(&view, &config),
                    DrawingType::FloorPlan,
                    "1:100",
                );
                (ln, svg)
            })
            .collect()
    } else {
        vec![(
            "Level 1".to_string(),
            with_tb_and_obc_notes(
                build_floor_plan_svg(doc, &config),
                DrawingType::FloorPlan,
                "1:100",
            ),
        )]
    };
    let floor_plan_svg = floor_plans.first().map_or_else(String::new, |(_, s)| s.clone());

    // DXF for the ground-floor plan (Level 1 view).
    let floor_plan_dxf = {
        let slice = if distinct.len() > 1 {
            let first_level = level_names(doc).into_iter().next();
            match first_level {
                Some(ln) => build_floor_plan_slice_result(&filter_doc_to_level(doc, &ln), &config),
                None => build_floor_plan_slice_result(doc, &config),
            }
        } else {
            build_floor_plan_slice_result(doc, &config)
        };
        drawing::export_to_dxf(&slice).unwrap_or_default()
    };

    let framing_plan_svg = if options.include_framing_plan {
        with_tb(
            generate_framing_plan_svg(doc, &JoistSpec::default(), "Level 1", FP_SCALE, FP_PAD),
            DrawingType::FramingPlan,
            "1:100",
        )
    } else {
        String::new()
    };

    Documentation {
        project_name: project_name.clone(),
        generated_date: date.clone(),
        site_plan_svg: with_fitted_tb(generate_site_plan(doc), DrawingType::SitePlan, "1:200"),
        roof_plan_svg: with_fitted_tb(generate_roof_plan(doc), DrawingType::RoofPlan, "1:100"),
        floor_plan_svg,
        floor_plan_dxf,
        floor_plans,
        elevations: generate_elevations(doc)
            .into_iter()
            .map(|e| Elevation {
                direction: e.direction,
                svg: with_tb(e.svg, drawing_type_for_direction(e.direction), "1:100"),
                dxf: e.dxf,
            })
            .collect(),
        section_svg: with_tb(
            generate_section(doc, &project.climate_zone),
            DrawingType::SectionA,
            "1:100",
        ),
        wall_details: generate_wall_details(doc, &config),
        door_schedule_svg: render_schedule_svg(
            &crate::schedule::door_entries(doc),
            "DOOR SCHEDULE",
        ),
        window_schedule_svg: render_schedule_svg(
            &crate::schedule::window_entries(doc),
            "WINDOW SCHEDULE",
        ),
        foundation_plan_svg: with_tb(
            generate_foundation_plan_svg(doc, FP_SCALE, FP_PAD),
            DrawingType::FoundationPlan,
            "1:100",
        ),
        framing_plan_svg,
        footing_detail_svg: with_fitted_tb(
            // 1.5× viewport scale + a healthy pad makes the rebar dots and
            // callout text legible at sheet scale.
            generate_footing_detail_svg(&FootingSpec::default(), 1.5, 400.0),
            DrawingType::FootingDetail,
            "1:20",
        ),
        stair_section_svg: stair_section_for(doc).map_or_else(String::new, |spec| {
            with_fitted_tb(
                generate_stair_section_svg(&spec, 1.0, 700.0),
                DrawingType::StairSection,
                "1:50",
            )
        }),
        compliance_report_svg: String::new(), // filled by caller after validation
    }
}

/// Generate documentation **and** the compliance report sheet in one call.
///
/// This is the preferred entry point when OBC validation has already been
/// run; it injects the compliance report SVG (with title block) into the
/// returned `Documentation`.
#[must_use]
pub fn generate_documentation_with_validation(
    doc: &SchemaDocument,
    project_name: impl Into<String>,
    validation: &crate::ValidationResult,
) -> Documentation {
    let project_name: String = project_name.into();
    let project = ProjectInfo {
        name: project_name,
        number: doc.building_id.clone(),
        solver: "QBD Layout".into(),
        ..Default::default()
    };
    generate_documentation_with_validation_for_project(doc, project, validation)
}

/// Variant of [`generate_documentation_with_validation`] that takes the
/// full `ProjectInfo` — same designer/BCIN routing as
/// [`generate_documentation_for_project`].
#[must_use]
pub fn generate_documentation_with_validation_for_project(
    doc: &SchemaDocument,
    project: ProjectInfo,
    validation: &crate::ValidationResult,
) -> Documentation {
    let mut docs = generate_documentation_for_project(doc, project.clone());
    if !validation.wall_reports.is_empty() {
        let report_svg = crate::compliance_report::compliance_report_to_svg(validation, &docs.project_name);
        // Same consistent sheet frame + title block as every other sheet.
        // Reuse the caller's ProjectInfo so the designer/BCIN appear here too.
        let info = drawing_info_for(DrawingType::ComplianceReport, "—", &docs.generated_date);
        docs.compliance_report_svg = inject_sheet_titleblock(&report_svg, &project, &info, false);
    }
    docs
}

/// Variant of [`generate_documentation_with_validation_for_project`] with
/// full sheet-selection control.
#[must_use]
pub fn generate_documentation_with_validation_and_options(
    doc: &SchemaDocument,
    project: ProjectInfo,
    validation: &crate::ValidationResult,
    options: DocumentationOptions,
) -> Documentation {
    let mut docs = generate_documentation_for_project_with_options(doc, project.clone(), options);
    if !validation.wall_reports.is_empty() {
        let report_svg = crate::compliance_report::compliance_report_to_svg(validation, &docs.project_name);
        let info = drawing_info_for(DrawingType::ComplianceReport, "—", &docs.generated_date);
        docs.compliance_report_svg = inject_sheet_titleblock(&report_svg, &project, &info, false);
    }
    docs
}

/// Wrap `drawing::schedule_to_svg` with an empty-input short-circuit:
/// permit sets traditionally suppress empty schedule sheets.
fn render_schedule_svg(entries: &[drawing::ScheduleEntry], title: &str) -> String {
    if entries.is_empty() {
        String::new()
    } else {
        drawing::schedule_to_svg(entries, title)
    }
}

/// Parse an SVG's `viewBox="minx miny w h"` into `(minx, miny, w, h)`.
fn parse_viewbox(svg: &str) -> Option<(f32, f32, f32, f32)> {
    let vb = svg.split("viewBox=\"").nth(1)?.split('"').next()?;
    let n: Vec<f32> = vb.split_whitespace().filter_map(|x| x.parse().ok()).collect();
    if n.len() == 4 { Some((n[0], n[1], n[2], n[3])) } else { None }
}

/// Frame a sheet identically to every other: a border inset from the viewBox,
/// plus a title block anchored bottom-right at a *consistent* size — a fixed
/// fraction (`TB_FRAC_LONG`) of the page's longest side, scaled uniformly so it
/// never distorts or clips no matter the drawing's scale or aspect. Previously
/// the block was a fixed model-mm box tied to the building's plan dimensions,
/// so it came out huge on small/portrait sheets and clipped past the edge on
/// sheets shaped differently than the plan.
///
/// `with_obc_notes` stacks the OBC general-notes block directly above the title
/// block in the same scaled space (floor-plan sheets only).
fn inject_sheet_titleblock(
    svg: &str,
    project: &ProjectInfo,
    info: &DrawingInfo,
    with_obc_notes: bool,
) -> String {
    /// Title-block width as a fraction of the sheet's longest side.
    const TB_FRAC_LONG: f32 = 0.26;
    let Some((vx, vy, vw, vh)) = parse_viewbox(svg) else {
        return svg.to_string();
    };
    if vw <= 0.0 || vh <= 0.0 {
        return svg.to_string();
    }
    let long = vw.max(vh);
    let inset = 0.012 * long;

    let mut frag = String::with_capacity(2048);
    // Sheet border (outer + inner), framing the viewBox.
    let _ = writeln!(
        frag,
        r##"  <rect x="{x:.1}" y="{y:.1}" width="{w:.1}" height="{h:.1}" fill="none" stroke="#000" stroke-width="{sw:.1}"/>"##,
        x = vx + inset,
        y = vy + inset,
        w = vw - 2.0 * inset,
        h = vh - 2.0 * inset,
        sw = long * 0.0007,
    );
    let _ = writeln!(
        frag,
        r##"  <rect x="{x:.1}" y="{y:.1}" width="{w:.1}" height="{h:.1}" fill="none" stroke="#000" stroke-width="{sw:.1}"/>"##,
        x = vx + inset * 1.5,
        y = vy + inset * 1.5,
        w = vw - 3.0 * inset,
        h = vh - 3.0 * inset,
        sw = long * 0.0003,
    );

    // Title block: uniform scale to the target width, bottom-right corner.
    let k = (TB_FRAC_LONG * long) / TITLE_BLOCK_W;
    let gap = inset + 0.006 * long;
    let tb_x = vx + vw - gap - TITLE_BLOCK_W * k;
    let tb_y = vy + vh - gap - TITLE_BLOCK_H * k;
    let _ = writeln!(frag, r#"  <g transform="translate({tb_x:.2} {tb_y:.2}) scale({k:.5})">"#);
    // OBC notes stack directly above the box, sharing this scale + left edge.
    if with_obc_notes {
        let (_nw, nh) = notes_block_size_mm();
        frag.push_str(&generate_obc_notes_block(0.0, -(nh + 200.0)));
    }
    frag.push_str(&title_block_box(0.0, 0.0, project, info));
    frag.push_str("  </g>\n");

    inject_before_svg_close(svg, &frag)
}

/// Inject SVG content before the closing `</svg>` tag. If the input has
/// no `</svg>`, returns the input unchanged.
fn inject_before_svg_close(svg: &str, fragment: &str) -> String {
    if let Some(idx) = svg.rfind("</svg>") {
        let mut out = String::with_capacity(svg.len() + fragment.len() + 1);
        out.push_str(&svg[..idx]);
        out.push_str(fragment);
        out.push_str(&svg[idx..]);
        out
    } else {
        svg.to_string()
    }
}

fn drawing_type_for_direction(d: ElevationDirection) -> DrawingType {
    match d {
        ElevationDirection::North => DrawingType::ElevationNorth,
        ElevationDirection::South => DrawingType::ElevationSouth,
        ElevationDirection::East => DrawingType::ElevationEast,
        ElevationDirection::West => DrawingType::ElevationWest,
    }
}

/// Compute SitePlan from the schema document's overall building footprint
/// (in mm) and render the site-plan SVG.
fn generate_site_plan(doc: &SchemaDocument) -> String {
    const M_TO_FT: f32 = 3.280_84;
    let building_width_ft = doc.width / 1000.0 * M_TO_FT;
    let building_depth_ft = doc.depth / 1000.0 * M_TO_FT;
    // Lot + zone from the document; setbacks from the municipal zoning table.
    let (lot_w, lot_d) = if doc.site.lot_width_ft > 0.0 && doc.site.lot_depth_ft > 0.0 {
        (doc.site.lot_width_ft, doc.site.lot_depth_ft)
    } else {
        (60.0, 120.0) // fallback when the lot isn't specified
    };
    let zone = if doc.site.zone.is_empty() { "R1" } else { &doc.site.zone };
    let street = if doc.site.street.is_empty() { "Street" } else { &doc.site.street };
    let sb = obc::zoning::setbacks_for(zone);
    let setbacks_ft = (sb.front * M_TO_FT, sb.interior_side * M_TO_FT, sb.rear * M_TO_FT);
    let mut site = SitePlan::from_lot(lot_w, lot_d, building_width_ft, building_depth_ft, setbacks_ft, street, zone);
    // LiDAR grade, if wired (qbd_dump --terrain fills site.grade_corners_m).
    site.grade_corners_m.clone_from(&doc.site.grade_corners_m);
    // Real parcel outline, if the map boundary was captured (qbd_dump --parcel
    // or CAD's vertices_ft). When present (≥3), the renderer draws the true lot
    // shape instead of the rectangular envelope.
    site.lot_polygon_ft = doc.site.lot_polygon_ft.iter().map(|p| (p[0], p[1])).collect();
    // LiDAR contour lines (qbd_dump --terrain fills doc.site.contours_ft).
    site.contours_ft = doc
        .site
        .contours_ft
        .iter()
        .map(|c| drawing::Contour {
            elevation_m: c.elevation_m,
            polylines_ft: c
                .polylines_ft
                .iter()
                .map(|chain| chain.iter().map(|p| (p[0], p[1])).collect())
                .collect(),
        })
        .collect();
    if doc.site.contour_interval_m > 0.0 {
        site.contour_interval_m = doc.site.contour_interval_m;
    }
    // OSM street network (qbd_dump --streets fills doc.site.streets_ft).
    site.streets_ft = doc
        .site
        .streets_ft
        .iter()
        .map(|s| drawing::StreetWay {
            points_ft: s.points_ft.iter().map(|p| (p[0], p[1])).collect(),
            name: if s.name.is_empty() { None } else { Some(s.name.clone()) },
            kind: match s.kind.as_str() {
                "arterial" => drawing::StreetClass::Arterial,
                "connector" => drawing::StreetClass::Connector,
                "path" => drawing::StreetClass::Path,
                _ => drawing::StreetClass::Local,
            },
        })
        .collect();
    generate_site_plan_svg(&site)
}

/// Generate the roof-plan SVG (gable or hip) from the footprint + roof type.
fn generate_roof_plan(doc: &SchemaDocument) -> String {
    let roof_type = if doc.roof_type == "hip" {
        drawing::RoofType::Hip
    } else {
        drawing::RoofType::Gable
    };
    let roof = drawing::RoofPlan {
        width: doc.width,
        depth: doc.depth,
        roof_type,
        pitch: 0.5, // 6:12, matches the elevations
        overhang: doc.roof_overhang_mm,
        footprint_polygon_mm: doc
            .footprint_polygon_mm
            .iter()
            .map(|p| (p[0], p[1]))
            .collect(),
    };
    drawing::generate_roof_plan_svg(&roof)
}

/// Compose the ground-floor plan onto a permit sheet at a true paper scale
/// (e.g. 1:50) with a bottom title block. The floor-plan geometry and its
/// dimension/label annotations are authored in plan millimetres, so they land
/// at a legible paper size once scaled to 1:N.
#[must_use]
pub fn floor_plan_sheet(
    doc: &SchemaDocument,
    project: &drawing::ProjectInfo,
    scale_denominator: f32,
    paper: drawing::PaperSize,
) -> (String, drawing::Placement) {
    let config = Config::with_defaults();
    let raw = build_floor_plan_svg(doc, &config);
    let info = drawing_info_for(
        DrawingType::FloorPlan,
        &format!("1:{}", scale_denominator.round() as i64),
        &today_iso(),
    );
    let d = drawing::SheetDrawing {
        svg: raw,
        model_units_per_mm: FP_SCALE,
        scale_denominator,
        caption: String::new(),
    };
    drawing::compose_sheet(&d, paper, project, &info)
}

/// Compose all floor-plan levels onto one multi-up permit sheet at a true
/// paper scale. Each level is placed side by side (one column per level) with
/// a "FLOOR PLAN — {level}" caption, sharing a single bottom title block.
#[must_use]
pub fn plans_sheet(
    doc: &SchemaDocument,
    project: &drawing::ProjectInfo,
    scale_denominator: f32,
    paper: drawing::PaperSize,
) -> (String, Vec<drawing::Placement>) {
    let config = Config::with_defaults();
    let levels = level_names(doc);
    let drawings: Vec<drawing::SheetDrawing> = levels
        .iter()
        .map(|level| {
            let view = if levels.len() > 1 {
                filter_doc_to_level(doc, level)
            } else {
                doc.clone()
            };
            drawing::SheetDrawing {
                svg: build_floor_plan_svg(&view, &config),
                model_units_per_mm: FP_SCALE,
                scale_denominator,
                caption: format!("FLOOR PLAN — {level}"),
            }
        })
        .collect();
    let mut info = drawing_info_for(
        DrawingType::FloorPlan,
        &format!("1:{}", scale_denominator.round() as i64),
        &today_iso(),
    );
    if drawings.len() > 1 {
        info.title = "FLOOR PLANS".to_string();
    }
    let cols = drawings.len().min(2).max(1);
    drawing::compose_multi(&drawings, cols, paper, project, &info)
}

/// One drawing available to place on a sheet: a human title and its raw SVG
/// (no title block). This is the catalogue the in-app sheet-layout editor
/// rasterises into draggable thumbnails.
#[derive(Debug, Clone)]
pub struct CatalogDrawing {
    pub title: String,
    pub svg: String,
    /// Authored SVG units per real-world millimetre (the exporter `scale`).
    /// The editor divides the SVG viewBox by this to recover the real size and
    /// label the placed drawing's scale. `0.0` means "not to scale" (e.g. the
    /// feet-based site plan).
    pub model_units_per_mm: f32,
}

// Per-generator export scales (SVG units per mm).
const SECTION_SCALE: f32 = 0.05;
const ELEVATION_SCALE: f32 = 0.05;
const ROOF_SCALE: f32 = 0.08;
const FOOTING_SCALE: f32 = 1.5;
const WALL_DETAIL_SCALE: f32 = 18.0; // wall_detail_to_svg: 1.0 * detail_scale(1.5) * 12

/// Build the catalogue of every drawing the permit set can contain, as raw
/// SVGs. Order: floor plans (per level), elevations, section, roof, site,
/// foundation, framing, footing detail, wall details.
#[must_use]
pub fn drawing_catalog(doc: &SchemaDocument, climate_zone: &str) -> Vec<CatalogDrawing> {
    let config = Config::with_defaults();
    let mut out: Vec<CatalogDrawing> = Vec::new();

    let levels = level_names(doc);
    for level in &levels {
        let view = if levels.len() > 1 {
            filter_doc_to_level(doc, level)
        } else {
            doc.clone()
        };
        out.push(CatalogDrawing {
            title: format!("FLOOR PLAN — {level}"),
            svg: build_floor_plan_svg(&view, &config),
            model_units_per_mm: FP_SCALE,
        });
    }

    for e in generate_elevations(doc) {
        out.push(CatalogDrawing {
            title: format!("{:?} ELEVATION", e.direction).to_uppercase(),
            svg: e.svg,
            model_units_per_mm: ELEVATION_SCALE,
        });
    }

    out.push(CatalogDrawing {
        title: "SECTION A-A".into(),
        svg: generate_section(doc, climate_zone),
        model_units_per_mm: SECTION_SCALE,
    });
    out.push(CatalogDrawing {
        title: "ROOF PLAN".into(),
        svg: generate_roof_plan(doc),
        model_units_per_mm: ROOF_SCALE,
    });
    out.push(CatalogDrawing {
        title: "SITE PLAN".into(),
        svg: generate_site_plan(doc),
        model_units_per_mm: 0.0, // feet-based, dynamic — labelled NTS
    });
    out.push(CatalogDrawing {
        title: "FOUNDATION PLAN".into(),
        svg: generate_foundation_plan_svg(doc, FP_SCALE, FP_PAD),
        model_units_per_mm: FP_SCALE,
    });
    out.push(CatalogDrawing {
        title: "FRAMING PLAN".into(),
        svg: generate_framing_plan_svg(doc, &JoistSpec::default(), "Level 1", FP_SCALE, FP_PAD),
        model_units_per_mm: FP_SCALE,
    });
    out.push(CatalogDrawing {
        title: "FOOTING DETAIL".into(),
        svg: generate_footing_detail_svg(&FootingSpec::default(), 1.5, 400.0),
        model_units_per_mm: FOOTING_SCALE,
    });
    if let Some(spec) = stair_section_for(doc) {
        out.push(CatalogDrawing {
            title: "STAIR SECTION".into(),
            svg: generate_stair_section_svg(&spec, 1.0, 700.0),
            model_units_per_mm: 1.0,
        });
    }
    for (i, wd) in generate_wall_details(doc, &config).into_iter().enumerate() {
        out.push(CatalogDrawing {
            title: format!("WALL DETAIL {}", i + 1),
            svg: wd.svg,
            model_units_per_mm: WALL_DETAIL_SCALE,
        });
    }

    out.push(CatalogDrawing {
        title: "SYMBOLS LEGEND".into(),
        svg: drawing::generate_symbols_legend_svg(),
        model_units_per_mm: 0.0, // a key, not to scale
    });

    out
}

/// Build a SectionInput from the schema document and render the default
/// (transverse, centre, looking-east) section. `climate_zone` (OBC SB-12,
/// e.g. `"Zone 6"`) drives the envelope thermal R-value callouts.
fn generate_section(doc: &SchemaDocument, climate_zone: &str) -> String {
    let level_base: std::collections::HashMap<&str, f32> =
        doc.levels.iter().map(|l| (l.name.as_str(), l.elevation)).collect();
    let input = SectionInput {
        width: doc.width,
        walls: doc
            .walls
            .iter()
            .map(|w| SectionWallInput {
                start: w.start,
                end: w.end,
                height: w.height,
                category: w.category.clone(),
                base: level_base.get(w.level_name.as_str()).copied().unwrap_or(0.0),
            })
            .collect(),
        // Basic gable over the transverse cut: 6:12 rise over the shorter span
        // (matches the elevations). The default cut is transverse, so it shows
        // the gable cross-section.
        ridge_heights_above_plate: vec![doc.width.min(doc.depth) * 0.5 * 0.5],
        // Intermediate-floor platforms: storey bases above grade, EXCLUDING the
        // roof level (its band would sit at the plate and poke past the roof).
        floor_lines: doc
            .levels
            .iter()
            .filter(|l| !l.name.to_lowercase().contains("roof"))
            .map(|l| l.elevation)
            .filter(|&e| e > 1.0)
            .collect(),
        // Ceiling height auto-derives from the ground-storey wall plate.
        ceiling_height_mm: 0.0,
        assemblies: envelope_assemblies(doc, climate_zone),
        eave_overhang_mm: doc.roof_overhang_mm,
    };
    let cut = drawing::default_cut(&input);
    generate_section_sheet_svg(&input, &cut, 0.05)
}

/// Build the envelope-assembly thermal callouts shown on the section.
/// Wall R is the *design* value of the exterior wall type; roof/ceiling and
/// floor R are the OBC SB-12 prescriptive minimums for the climate zone.
#[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)]
fn envelope_assemblies(doc: &SchemaDocument, climate_zone: &str) -> Vec<drawing::AssemblyCallout> {
    let zone = if climate_zone.is_empty() { "Zone 6" } else { climate_zone };

    // Exterior wall: prefer the schema's own exterior wall type; otherwise the
    // Part-9 default that `convert` injects for the "exterior" category.
    let ext_wt = doc
        .wall_types
        .iter()
        .find(|wt| wt.id == "ext_2x6_r22_ci" || wt.name.to_lowercase().contains("exterior"))
        .map_or_else(
            || crate::wall_types::for_category("exterior"),
            crate::convert::schema_wall_type_to_domain,
        );
    let wall_r = ext_wt.total_r_value();

    let ceiling_r = obc::sb12_minimum_r(zone, "ceiling");
    let floor_r = obc::sb12_minimum_r(zone, "floor");

    vec![
        drawing::AssemblyCallout {
            label: "EXTERIOR WALL".into(),
            spec: ext_wt.name.clone(),
            r_value: wall_r,
        },
        drawing::AssemblyCallout {
            label: "ROOF / CEILING".into(),
            spec: format!("Vented attic — blown insulation to min R-{} ({zone})", ceiling_r.round() as i32),
            r_value: ceiling_r,
        },
        drawing::AssemblyCallout {
            label: "FLOOR (EXPOSED / OVER UNHEATED)".into(),
            spec: format!("Batt insulation to min R-{} ({zone})", floor_r.round() as i32),
            r_value: floor_r,
        },
    ]
}

/// Build an ElevationInput from the schema document and render one
/// elevation per cardinal direction.
fn generate_elevations(doc: &SchemaDocument) -> Vec<Elevation> {
    // Level name → base elevation (mm), so upper-storey walls stack.
    let level_base: std::collections::HashMap<&str, f32> =
        doc.levels.iter().map(|l| (l.name.as_str(), l.elevation)).collect();
    let input = ElevationInput {
        width: doc.width,
        depth: doc.depth,
        walls: doc
            .walls
            .iter()
            .map(|w| ElevationWallInput {
                start: w.start,
                end: w.end,
                height: w.height,
                base: level_base.get(w.level_name.as_str()).copied().unwrap_or(0.0),
            })
            .collect(),
        // wall_index is `i32` in the schema but `usize` in the elevation
        // input; max(0) clamps the negative-index sentinel before the
        // truncate-when-cast.
        #[allow(clippy::cast_sign_loss)]
        openings: doc
            .doors
            .iter()
            .map(|d| ElevationOpeningInput {
                wall_index: d.wall_index.max(0) as usize,
                offset: d.offset,
                width: d.width,
                height: d.height,
                sill_height: 0.0,
                is_door: true,
            })
            .chain(doc.windows.iter().map(|w| ElevationOpeningInput {
                wall_index: w.wall_index.max(0) as usize,
                offset: w.offset,
                width: w.width,
                height: w.height,
                sill_height: w.sill_height,
                is_door: false,
            }))
            .collect(),
        // Basic gable: ridge along the longer footprint axis, rise from a
        // 6:12 pitch over the perpendicular (shorter) span.
        gable_ridge_above_plate: doc.width.min(doc.depth) * 0.5 * 0.5,
        ridge_along_width: doc.width >= doc.depth,
        hip: doc.roof_type == "hip",
        // A floor line at each storey base above grade (Level 2+).
        floor_lines: doc.levels.iter().map(|l| l.elevation).filter(|&e| e > 1.0).collect(),
        // Pass the irregular footprint (if any) so the elevation renders a
        // stepped silhouette per wing instead of one rectangle.
        footprint_polygon_mm: doc
            .footprint_polygon_mm
            .iter()
            .map(|p| (p[0], p[1]))
            .collect(),
        roof_pitch: 0.5,
        eave_overhang_mm: doc.roof_overhang_mm,
    };
    ElevationDirection::ALL
        .iter()
        .map(|&dir| Elevation {
            direction: dir,
            svg: generate_elevation_sheet_svg(&input, dir, 0.05),
            dxf: drawing::generate_elevation_dxf(&input, dir).unwrap_or_default(),
        })
        .collect()
}

/// One detail per wall category actually present in the layout.
/// Matches `QBDInterface::generateWallDetails` (`qbd_interface.cpp:1131`).
#[must_use]
fn generate_wall_details(doc: &SchemaDocument, config: &Config) -> Vec<WallDetail> {
    let mut has_exterior = false;
    let mut has_interior = false;
    let mut has_wet = false;
    for wall in &doc.walls {
        match wall.category.as_str() {
            "exterior" => has_exterior = true,
            "wet_wall" => has_wet = true,
            _ => has_interior = true,
        }
    }

    let mut details = Vec::new();
    if has_exterior {
        details.push(build_detail(wall_types::exterior_2x6_r21(), config));
    }
    if has_interior {
        details.push(build_detail(wall_types::interior_2x4(), config));
    }
    if has_wet {
        details.push(build_detail(wall_types::wet_2x6(), config));
    }
    details
}

// WallType is small and owned (the helpers in `wall_types` return owned
// values); taking it by value mirrors the caller pattern with no extra cost.
#[allow(clippy::needless_pass_by_value)]
fn build_detail(wall_type: domain::WallType, config: &Config) -> WallDetail {
    let detail = generate_wall_detail(&wall_type, 9.0, config);
    let svg = wall_detail_to_svg(&detail, 1.0);
    WallDetail { detail, svg }
}

/// Current date in `YYYY-MM-DD`. Uses `SystemTime` and a small
/// hand-rolled Gregorian-calendar conversion so we don't pull in the
/// `chrono` crate for this single use.
#[must_use]
#[allow(clippy::cast_sign_loss, clippy::cast_possible_truncation)]
pub fn today_iso() -> String {
    use std::time::{SystemTime, UNIX_EPOCH};

    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default();
    let secs = now.as_secs();
    let days_since_epoch = secs / 86_400;

    // Convert days-since-1970-01-01 to (year, month, day) — algorithm
    // from Howard Hinnant's date library, simplified for >= 1970.
    let days = i64::try_from(days_since_epoch).unwrap_or(0);
    let z = days + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    // Post-1970 dates: z >> 0, so the subtraction is non-negative.
    #[allow(clippy::cast_sign_loss)]
    let doe = (z - era * 146_097) as u64;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    #[allow(clippy::cast_possible_wrap)]
    let y = (yoe as i64) + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let m = if mp < 10 { mp + 3 } else { mp - 9 } as u32;
    let y = if m <= 2 { y + 1 } else { y };

    format!("{y:04}-{m:02}-{d:02}")
}

#[cfg(test)]
mod tests {
    use super::*;
    use archgeometry::{SchemaDoor, SchemaWall, SchemaWindow};
    use glam::Vec3;

    fn rect_room_doc() -> SchemaDocument {
        let mut doc = SchemaDocument::default();
        for ((sx, sz), (ex, ez)) in [
            ((0.0, 0.0), (5000.0, 0.0)),
            ((5000.0, 0.0), (5000.0, 4000.0)),
            ((5000.0, 4000.0), (0.0, 4000.0)),
            ((0.0, 4000.0), (0.0, 0.0)),
        ] {
            doc.walls.push(SchemaWall {
                start: Vec3::new(sx, 0.0, sz),
                end: Vec3::new(ex, 0.0, ez),
                height: 2700.0,
                category: "exterior".into(),
                ..Default::default()
            });
        }
        doc
    }

    #[test]
    fn parse_viewbox_reads_four_numbers() {
        let svg = r#"<svg viewBox="0 0 540 730">"#;
        assert_eq!(parse_viewbox(svg), Some((0.0, 0.0, 540.0, 730.0)));
        assert_eq!(parse_viewbox("<svg>"), None);
    }

    #[test]
    fn sheet_title_block_scales_uniformly_into_the_viewbox() {
        // A small-coordinate sheet (like the site plan): the title block is
        // placed at a uniform scale, anchored bottom-right inside the viewBox.
        let svg = "<svg viewBox=\"0 0 540 730\">\n<rect/>\n</svg>\n";
        let project = ProjectInfo { name: "Acme".into(), ..Default::default() };
        let info = drawing_info_for(DrawingType::SitePlan, "1:200", "2026-05-26");
        let out = inject_sheet_titleblock(svg, &project, &info, false);
        // Wrapped in a single uniform scaling transform, not injected raw.
        assert!(out.contains("<g transform=\"translate("));
        assert!(out.contains("scale("));
        assert!(out.contains("SITE PLAN"));
        assert!(out.ends_with("</svg>\n"));
        // Uniform scale: `scale(k)` has one argument, shrinking the 4000-wide
        // box to a fraction of the 730-tall sheet's long side.
        let arg = out.split("scale(").nth(1).and_then(|s| s.split(')').next()).expect("scale");
        assert!(!arg.contains(' '), "scale must be uniform (one arg), got: {arg}");
        let k: f32 = arg.parse().expect("scale k");
        assert!(k < 0.1 && k > 0.0, "k={k}");
    }

    #[test]
    fn title_block_is_a_consistent_fraction_across_sheet_sizes() {
        // The same project/drawing rendered into a small and a large viewBox
        // must produce title blocks at the same fraction of each page — that's
        // the whole point of the uniform-fraction sizing.
        let project = ProjectInfo { name: "Acme".into(), ..Default::default() };
        let info = drawing_info_for(DrawingType::FloorPlan, "1:100", "2026-06-10");
        let scale_for = |vb: &str| -> f32 {
            let svg = format!("<svg viewBox=\"{vb}\">\n<rect/>\n</svg>\n");
            let out = inject_sheet_titleblock(&svg, &project, &info, false);
            out.split("scale(")
                .nth(1)
                .and_then(|s| s.split(')').next())
                .and_then(|s| s.parse().ok())
                .expect("scale k")
        };
        // k is proportional to the long side, so k/long is invariant.
        let small = scale_for("0 0 6000 4000") / 6000.0;
        let large = scale_for("0 0 18000 12000") / 18000.0;
        assert!((small - large).abs() < 1e-4, "small={small} large={large}");
    }

    #[test]
    fn site_plan_title_block_is_labelled_site_plan() {
        let docs = generate_documentation(&rect_room_doc(), "Test Project");
        assert!(docs.site_plan_svg.contains("SITE PLAN"));
        assert!(docs.site_plan_svg.contains("<g transform=\"translate("));
        assert!(docs.roof_plan_svg.contains("ROOF PLAN"));
    }

    #[test]
    fn floor_plan_renders_a_stair_symbol_with_direction() {
        let mut doc = rect_room_doc();
        doc.stairs.push(archgeometry::SchemaStair {
            id: "stairs_1".into(),
            level_name: "Level 1".into(),
            x: 0.0,
            y: 0.0,
            width: 1828.8,
            depth: 3352.8,
            run_dir: "+y".into(),
            num_risers: 16,
            num_treads: 15,
            riser_height: 190.5,
            tread_run: 255.0,
            width_clear: 864.0,
            floor_to_floor: 3048.0,
            shape: "switchback".into(),
            going: "up".into(),
        });
        let docs = generate_documentation(&doc, "Stair House");
        // The UP label + an arrowhead polygon land on the floor plan.
        assert!(docs.floor_plan_svg.contains(">UP</text>"), "no UP label");
        assert!(docs.floor_plan_svg.contains("<polygon"), "no direction arrowhead");
        // And a typical stair section sheet is generated for the storey.
        assert!(docs.stair_section_svg.contains("STAIR SECTION"), "no stair section sheet");
        assert!(docs.stair_section_svg.contains("9.8.2.2"), "headroom note missing");
    }

    #[test]
    fn no_stair_section_without_stairs() {
        // Single-storey (no stairs) → no stair-section sheet.
        let docs = generate_documentation(&rect_room_doc(), "Bungalow");
        assert!(docs.stair_section_svg.is_empty());
    }

    #[test]
    fn generated_documentation_has_floor_plan_svg() {
        let docs = generate_documentation(&rect_room_doc(), "Test Project");
        assert_eq!(docs.project_name, "Test Project");
        assert!(docs.floor_plan_svg.starts_with("<?xml version=\"1.0\""));
        assert!(docs.floor_plan_svg.contains("<svg"));
        assert!(docs.floor_plan_svg.ends_with("</svg>\n"));
    }

    #[test]
    fn section_carries_envelope_assemblies_and_ceiling_height() {
        let docs = generate_documentation(&rect_room_doc(), "Test Project");
        let s = &docs.section_svg;
        // OBC 9.25 / SB-12 thermal demonstration on the section.
        assert!(s.contains("ENVELOPE ASSEMBLIES (OBC SB-12)"), "no thermal block");
        assert!(s.contains("EXTERIOR WALL: R-"), "no wall R-value");
        assert!(s.contains("ROOF / CEILING: R-"), "no ceiling R-value");
        assert!(s.contains("CEILING HT."), "no ceiling-height dimension");
        // Default (empty) climate zone resolves to Zone 6 minimums.
        assert!(s.contains("(Zone 6)"), "expected Zone 6 thermal minimums");
    }

    #[test]
    fn section_uses_the_project_climate_zone() {
        let project = ProjectInfo {
            name: "Cold House".into(),
            climate_zone: "Zone 7A".into(),
            ..Default::default()
        };
        let docs = generate_documentation_for_project(&rect_room_doc(), project);
        // Zone 7A ceiling minimum is R-60 (vs R-50 for Zone 6).
        assert!(docs.section_svg.contains("ROOF / CEILING: R-60"), "got {}", docs.section_svg);
        assert!(docs.section_svg.contains("(Zone 7A)"));
    }

    #[test]
    fn generated_documentation_includes_door_and_window_primitives() {
        let mut doc = rect_room_doc();
        doc.doors.push(SchemaDoor {
            wall_index: 0,
            offset: 2500.0,
            width: 900.0,
            height: 2100.0,
            door_type: "swing".into(),
            swing: "left_in".into(),
            ..Default::default()
        });
        doc.windows.push(SchemaWindow {
            wall_index: 1,
            offset: 2000.0,
            width: 1200.0,
            height: 1200.0,
            sill_height: 900.0,
            ..Default::default()
        });
        let docs = generate_documentation(&doc, "Test");
        // Door white fill → polygon with white fill in SVG.
        assert!(docs.floor_plan_svg.contains(r#"fill="rgb(255,255,255)""#));
        // Window glazing → A-GLAZ — but the SVG layer name isn't in the
        // output (we don't emit class/id). Instead check for the swing
        // arc, which is unique to doors.
        assert!(docs.floor_plan_svg.contains("<path d=\"M"));
    }

    #[test]
    fn today_iso_is_well_formed() {
        let s = today_iso();
        // YYYY-MM-DD = 10 chars, two hyphens.
        assert_eq!(s.len(), 10);
        assert_eq!(s.chars().filter(|&c| c == '-').count(), 2);
    }

    #[test]
    fn exterior_only_layout_yields_one_wall_detail() {
        let docs = generate_documentation(&rect_room_doc(), "Test");
        assert_eq!(docs.wall_details.len(), 1);
        let d = &docs.wall_details[0];
        assert_eq!(d.detail.wall_type_id, "ext_2x6_r21");
        assert!(d.svg.starts_with("<?xml version=\"1.0\""));
        assert!(d.svg.contains("<svg"));
    }

    #[test]
    fn mixed_layout_yields_one_detail_per_category() {
        let mut doc = rect_room_doc();
        // Add one interior + one wet-wall.
        doc.walls.push(SchemaWall {
            start: Vec3::new(2000.0, 0.0, 0.0),
            end: Vec3::new(2000.0, 0.0, 4000.0),
            height: 2700.0,
            category: "interior".into(),
            ..Default::default()
        });
        doc.walls.push(SchemaWall {
            start: Vec3::new(3000.0, 0.0, 0.0),
            end: Vec3::new(3000.0, 0.0, 4000.0),
            height: 2700.0,
            category: "wet_wall".into(),
            ..Default::default()
        });
        let docs = generate_documentation(&doc, "Mixed");
        assert_eq!(docs.wall_details.len(), 3);
        let ids: Vec<_> = docs
            .wall_details
            .iter()
            .map(|d| d.detail.wall_type_id.as_str())
            .collect();
        assert!(ids.contains(&"ext_2x6_r21"));
        assert!(ids.contains(&"int_2x4"));
        assert!(ids.contains(&"wet_2x6"));
    }
}
