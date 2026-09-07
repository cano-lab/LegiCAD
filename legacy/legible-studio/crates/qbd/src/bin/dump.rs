//! `qbd_dump` — end-user CLI for the M5 permit-set pipeline.
//!
//! Loads a QBD-format JSON file via `archgeometry::parse_file`, runs
//! `qbd::generate_documentation`, and prints the resulting floor-plan
//! SVG to stdout. Optionally writes the SVG to a file with `--out`.
//!
//! Usage:
//!     qbd_dump <building.json>
//!     qbd_dump <building.json> --out floor_plan.svg

use anyhow::Context;
use std::path::PathBuf;

const USAGE: &str = "usage: qbd_dump <building.json> [--out <floor_plan.svg>] [--bundle <dir>] [--pdf <dir>] [--pdf-combined <set.pdf>] [--png <dir>] [--png-width <px>] [--dxf <dir>] [--ifc <out.ifc>] [--terrain <terrain.json>] [--parcel <parcel.json>] [--streets <streets.json>] [--footprint <poly.json>] [--obc <library-dir>] [--climate-zone <zone>] [--roof-overhang <mm>] [--project <name>] [--designer <name>] [--bcin <number>] [--egress-feedback <json_path>] [--no-framing-plan] [--bare]";

/// Climate zone fed to OBC thermal compliance when `--climate-zone` isn't passed.
const DEFAULT_CLIMATE_ZONE: &str = "Zone 6";

/// Longer-edge resolution (px) for `--png` sheets when `--png-width` isn't given.
const DEFAULT_PNG_WIDTH: u32 = 2200;

/// Longest displayed edge, in CSS px, for a written sheet.
const DISPLAY_MAX_PX: f32 = 1100.0;

/// Default elevation step between LiDAR contour lines on the site plan.
const CONTOUR_INTERVAL_M: f32 = 0.5;

/// Cap an SVG's displayed size. The geometry is exported in millimetres (often
/// ×10), so the raw `width`/`height` attributes are hundreds of thousands of
/// units — a browser renders that at that many *pixels*. We rewrite only the
/// `width`/`height` attributes (keeping the `viewBox`, so the drawing is
/// untouched) to fit `DISPLAY_MAX_PX` at the viewBox aspect ratio.
fn fit_display(svg: &str) -> String {
    let Some(start) = svg.find("<svg") else {
        return svg.to_string();
    };
    let Some(rel_end) = svg[start..].find('>') else {
        return svg.to_string();
    };
    let end = start + rel_end; // index of '>'
    let tag = &svg[start..end];
    // Parse the viewBox "minx miny w h".
    let Some(vb) = tag.split("viewBox=\"").nth(1).and_then(|s| s.split('"').next()) else {
        return svg.to_string();
    };
    let nums: Vec<f32> = vb.split_whitespace().filter_map(|n| n.parse().ok()).collect();
    if nums.len() != 4 {
        return svg.to_string();
    }
    let (vw, vh) = (nums[2].abs(), nums[3].abs());
    if vw <= 0.0 || vh <= 0.0 {
        return svg.to_string();
    }
    let (w, h) = if vw >= vh {
        (DISPLAY_MAX_PX, DISPLAY_MAX_PX * vh / vw)
    } else {
        (DISPLAY_MAX_PX * vw / vh, DISPLAY_MAX_PX)
    };
    let replace_attr = |tag: &str, name: &str, val: f32| -> String {
        let pat = format!("{name}=\"");
        if let Some(s) = tag.find(&pat) {
            let after = s + pat.len();
            if let Some(rel) = tag[after..].find('"') {
                return format!("{}{:.1}{}", &tag[..after], val, &tag[after + rel..]);
            }
        }
        tag.to_string()
    };
    let new_tag = replace_attr(&replace_attr(tag, "width", w), "height", h);
    format!("{}{}{}", &svg[..start], new_tag, &svg[end..])
}

/// Every produced sheet as `(name, svg)` in plan-set order. Shared by the
/// combined-PDF (`--pdf-combined`) and PNG (`--png`) bundles so both stay in
/// lockstep.
fn collect_sheets(docs: &qbd::Documentation) -> Vec<(String, String)> {
    let mut sheets: Vec<(String, String)> = Vec::new();
    let mut push = |name: &str, svg: &str| {
        if !svg.is_empty() {
            sheets.push((name.to_string(), svg.to_string()));
        }
    };
    push("01_site_plan", &docs.site_plan_svg);
    push("08_foundation_plan", &docs.foundation_plan_svg);
    if docs.floor_plans.len() <= 1 {
        push("02_floor_plan", &docs.floor_plan_svg);
    } else {
        for (i, (_level, svg)) in docs.floor_plans.iter().enumerate() {
            let name =
                if i == 0 { "02_floor_plan".to_string() } else { format!("02_floor_plan_l{}", i + 1) };
            push(&name, svg);
        }
    }
    push("06_roof_plan", &docs.roof_plan_svg);
    push("10_framing_plan", &docs.framing_plan_svg);
    for elev in &docs.elevations {
        let name = drawing::elevation_sheet_name(elev.direction).replace(".svg", "");
        push(&name, &elev.svg);
    }
    push("04_section_aa", &docs.section_svg);
    for (i, detail) in docs.wall_details.iter().enumerate() {
        let name = format!("07_wall_detail_{:02}_{}", i + 1, detail.detail.wall_type_id);
        push(&name, &detail.svg);
    }
    push("11_footing_detail", &docs.footing_detail_svg);
    push("12_stair_section", &docs.stair_section_svg);
    push("05_door_schedule", &docs.door_schedule_svg);
    push("05_window_schedule", &docs.window_schedule_svg);
    push("09_compliance_report", &docs.compliance_report_svg);
    sheets
}

#[allow(clippy::too_many_lines)] // CLI dispatch + bundle emission read top-down.
#[allow(clippy::format_collect)] // Manifest JSON assembly is one-shot; iterator-format is fine here.
#[allow(clippy::cast_possible_truncation)] // parcel coords are bounded lot dimensions
fn main() -> anyhow::Result<()> {
    let args: Vec<String> = std::env::args().collect();
    let mut path: Option<PathBuf> = None;
    let mut out: Option<PathBuf> = None;
    let mut bundle_dir: Option<PathBuf> = None;
    let mut pdf_dir: Option<PathBuf> = None;
    let mut pdf_combined: Option<PathBuf> = None;
    let mut png_dir: Option<PathBuf> = None;
    let mut png_width: u32 = DEFAULT_PNG_WIDTH;
    let mut dxf_dir: Option<PathBuf> = None;
    let mut ifc_out: Option<PathBuf> = None;
    let mut terrain_path: Option<PathBuf> = None;
    let mut parcel_path: Option<PathBuf> = None;
    let mut streets_path: Option<PathBuf> = None;
    let mut footprint_path: Option<PathBuf> = None;
    let mut obc_path: Option<PathBuf> = None;
    let mut climate_zone = String::from(DEFAULT_CLIMATE_ZONE);
    let mut roof_overhang: Option<f32> = None;
    let mut project = String::from("QBD Project");
    let mut designer = String::new();
    let mut bcin = String::new();
    // `--no-framing-plan`: omit the structural framing-plan sheet. Engineers
    // typically produce this; the flag lets the permit set stay architectural.
    let mut no_framing_plan = false;
    // `--bare`: emit just the slicer's raw floor-plan SVG (no dimensions,
    // no title block, no room labels). The m5_cpp_diff oracle relies on
    // this — the C++ QBDInterface doesn't add annotations, so a fair
    // byte-comparison must strip Rust's annotation overlay.
    let mut bare = false;

    // `--egress-feedback <json_path>`: analyze egress and write suggested fixes
    // as JSON instead of generating drawings.
    let mut egress_feedback: Option<PathBuf> = None;

    let mut i = 1;
    while i < args.len() {
        match args[i].as_str() {
            "--out" if i + 1 < args.len() => {
                out = Some(PathBuf::from(&args[i + 1]));
                i += 2;
            }
            "--bundle" if i + 1 < args.len() => {
                bundle_dir = Some(PathBuf::from(&args[i + 1]));
                i += 2;
            }
            "--pdf" if i + 1 < args.len() => {
                pdf_dir = Some(PathBuf::from(&args[i + 1]));
                i += 2;
            }
            "--pdf-combined" if i + 1 < args.len() => {
                pdf_combined = Some(PathBuf::from(&args[i + 1]));
                i += 2;
            }
            "--png" if i + 1 < args.len() => {
                png_dir = Some(PathBuf::from(&args[i + 1]));
                i += 2;
            }
            "--png-width" if i + 1 < args.len() => {
                png_width = args[i + 1].parse().unwrap_or(DEFAULT_PNG_WIDTH).max(1);
                i += 2;
            }
            "--dxf" if i + 1 < args.len() => {
                dxf_dir = Some(PathBuf::from(&args[i + 1]));
                i += 2;
            }
            "--project" if i + 1 < args.len() => {
                project.clone_from(&args[i + 1]);
                i += 2;
            }
            "--ifc" if i + 1 < args.len() => {
                ifc_out = Some(PathBuf::from(&args[i + 1]));
                i += 2;
            }
            "--terrain" if i + 1 < args.len() => {
                terrain_path = Some(PathBuf::from(&args[i + 1]));
                i += 2;
            }
            "--parcel" if i + 1 < args.len() => {
                parcel_path = Some(PathBuf::from(&args[i + 1]));
                i += 2;
            }
            "--streets" if i + 1 < args.len() => {
                streets_path = Some(PathBuf::from(&args[i + 1]));
                i += 2;
            }
            "--footprint" if i + 1 < args.len() => {
                footprint_path = Some(PathBuf::from(&args[i + 1]));
                i += 2;
            }
            "--obc" if i + 1 < args.len() => {
                obc_path = Some(PathBuf::from(&args[i + 1]));
                i += 2;
            }
            "--climate-zone" if i + 1 < args.len() => {
                climate_zone.clone_from(&args[i + 1]);
                i += 2;
            }
            "--roof-overhang" if i + 1 < args.len() => {
                roof_overhang = args[i + 1].parse().ok();
                i += 2;
            }
            "--designer" if i + 1 < args.len() => {
                designer.clone_from(&args[i + 1]);
                i += 2;
            }
            "--bcin" if i + 1 < args.len() => {
                bcin.clone_from(&args[i + 1]);
                i += 2;
            }
            "--no-framing-plan" => {
                no_framing_plan = true;
                i += 1;
            }
            "--bare" => {
                bare = true;
                i += 1;
            }
            "--egress-feedback" if i + 1 < args.len() => {
                egress_feedback = Some(PathBuf::from(&args[i + 1]));
                i += 2;
            }
            "-h" | "--help" => {
                eprintln!("{USAGE}");
                return Ok(());
            }
            arg => {
                if path.is_none() {
                    path = Some(PathBuf::from(arg));
                }
                i += 1;
            }
        }
    }

    let path = path.ok_or_else(|| anyhow::anyhow!("{USAGE}"))?;

    let mut doc = archgeometry::parse_file(&path)
        .with_context(|| format!("failed to parse {}", path.display()))?;

    // `--egress-feedback <json_path>`: analyze the schema for OBC 3.4 egress
    // problems and emit actionable fixes as JSON.
    if let Some(out_path) = egress_feedback {
        let fixes = qbd::analyze(&doc);
        let json = serde_json::to_string_pretty(&fixes)
            .context("failed to serialize egress feedback")?;
        std::fs::write(&out_path, json)
            .with_context(|| format!("failed to write {}", out_path.display()))?;
        eprintln!(
            "  egress feedback: {} fix(es) written to {}",
            fixes.len(),
            out_path.display()
        );
        return Ok(());
    }

    // `--roof-overhang <mm>` overrides the building's eave overhang (the schema
    // default is 400 mm); it drives the elevation/section roof projection and
    // the roof-plan eave outline.
    if let Some(oh) = roof_overhang {
        doc.roof_overhang_mm = oh;
        eprintln!("  roof overhang: {oh:.0} mm");
    }

    // Raw contour segments (per cell) — kept out of the schema until they've
    // been clipped to the parcel and stitched into polylines below.
    let mut raw_contours: Vec<qbd::terrain::Contour> = Vec::new();
    // LiDAR terrain: lot size + corner grade from the extracted property.
    if let Some(tpath) = &terrain_path {
        let json = std::fs::read_to_string(tpath)
            .with_context(|| format!("failed to read {}", tpath.display()))?;
        if let Some(t) = qbd::terrain::from_json(&json) {
            doc.site.lot_width_ft = t.lot_width_ft;
            doc.site.lot_depth_ft = t.lot_depth_ft;
            doc.site.grade_corners_m = t.corners_m.to_vec();
            raw_contours = qbd::terrain::contours(&t, CONTOUR_INTERVAL_M);
            doc.site.contour_interval_m = CONTOUR_INTERVAL_M;
            eprintln!(
                "  terrain: lot {:.0}x{:.0} ft, grade {:.1}-{:.1} m, {} contour level(s) @ {:.1} m",
                t.lot_width_ft,
                t.lot_depth_ft,
                t.corners_m.iter().copied().fold(f32::INFINITY, f32::min),
                t.corners_m.iter().copied().fold(f32::NEG_INFINITY, f32::max),
                raw_contours.len(),
                CONTOUR_INTERVAL_M,
            );
        } else {
            eprintln!("  terrain: no usable mesh in {}", tpath.display());
        }
    }

    // Parcel polygon: the real lot outline the user drew on the map widget
    // (CAD's `vertices_ft`). Accepts a top-level `vertices_ft`/`lot_polygon_ft`
    // array of `[x, y]` ft pairs, or a bare array of pairs.
    if let Some(ppath) = &parcel_path {
        let json = std::fs::read_to_string(ppath)
            .with_context(|| format!("failed to read {}", ppath.display()))?;
        let v: serde_json::Value = serde_json::from_str(&json)
            .with_context(|| format!("failed to parse {}", ppath.display()))?;
        let arr = v
            .get("vertices_ft")
            .or_else(|| v.get("lot_polygon_ft"))
            .or(Some(&v))
            .and_then(serde_json::Value::as_array);
        if let Some(arr) = arr {
            let poly: Vec<[f32; 2]> = arr
                .iter()
                .filter_map(|p| {
                    let a = p.as_array()?;
                    Some([a.first()?.as_f64()? as f32, a.get(1)?.as_f64()? as f32])
                })
                .collect();
            if poly.len() >= 3 {
                eprintln!("  parcel: {} vertices", poly.len());
                doc.site.lot_polygon_ft = poly;
            } else {
                eprintln!("  parcel: no usable polygon in {}", ppath.display());
            }
        }
    }

    // OSM street network around the parcel (legible-streets --out).
    if let Some(spath) = &streets_path {
        let json = std::fs::read_to_string(spath)
            .with_context(|| format!("failed to read {}", spath.display()))?;
        let v: serde_json::Value = serde_json::from_str(&json)
            .with_context(|| format!("failed to parse {}", spath.display()))?;
        let arr = v.get("streets_ft").or(Some(&v)).and_then(serde_json::Value::as_array);
        if let Some(arr) = arr {
            let streets: Vec<archgeometry::SchemaStreet> = arr
                .iter()
                .filter_map(|s| {
                    let pts = s.get("points_ft")?.as_array()?;
                    let points_ft: Vec<[f32; 2]> = pts
                        .iter()
                        .filter_map(|p| {
                            let a = p.as_array()?;
                            Some([a.first()?.as_f64()? as f32, a.get(1)?.as_f64()? as f32])
                        })
                        .collect();
                    if points_ft.len() < 2 {
                        return None;
                    }
                    Some(archgeometry::SchemaStreet {
                        name: s.get("name").and_then(|n| n.as_str()).unwrap_or("").to_string(),
                        kind: s.get("kind").and_then(|n| n.as_str()).unwrap_or("local").to_string(),
                        points_ft,
                    })
                })
                .collect();
            eprintln!("  streets: {} way(s)", streets.len());
            doc.site.streets_ft = streets;
        }
    }

    // Irregular building footprint (mm, CCW) for the rectilinear straight-
    // skeleton roof. Accepts a top-level `footprint_polygon_mm` array or a
    // bare `[[x, z], ...]` array.
    if let Some(fpath) = &footprint_path {
        let json = std::fs::read_to_string(fpath)
            .with_context(|| format!("failed to read {}", fpath.display()))?;
        let v: serde_json::Value = serde_json::from_str(&json)
            .with_context(|| format!("failed to parse {}", fpath.display()))?;
        let arr = v
            .get("footprint_polygon_mm")
            .or(Some(&v))
            .and_then(serde_json::Value::as_array);
        if let Some(arr) = arr {
            let poly: Vec<[f32; 2]> = arr
                .iter()
                .filter_map(|p| {
                    let a = p.as_array()?;
                    Some([a.first()?.as_f64()? as f32, a.get(1)?.as_f64()? as f32])
                })
                .collect();
            if poly.len() >= 4 {
                eprintln!("  footprint: {} vertices (mm)", poly.len());
                doc.footprint_polygon_mm = poly;
            } else {
                eprintln!("  footprint: need ≥4 vertices in {}", fpath.display());
            }
        }
    }

    // Finalise contours: (optionally) clip to the parcel polygon, then stitch
    // unstitched marching-squares segments into polylines so each chain can
    // carry one elevation label on the site plan.
    if !raw_contours.is_empty() {
        let poly: Option<Vec<(f32, f32)>> = if doc.site.lot_polygon_ft.is_empty() {
            None
        } else {
            Some(doc.site.lot_polygon_ft.iter().map(|p| (p[0], p[1])).collect())
        };
        let mut before = 0usize;
        let mut after = 0usize;
        let mut chains = 0usize;
        let mut out_levels = Vec::with_capacity(raw_contours.len());
        for c in &raw_contours {
            before += c.segments_ft.len();
            let segs = if let Some(p) = &poly {
                qbd::terrain::clip_segments_to_polygon(&c.segments_ft, p)
            } else {
                c.segments_ft.clone()
            };
            after += segs.len();
            let polylines = qbd::terrain::stitch_to_polylines(&segs);
            if polylines.is_empty() {
                continue;
            }
            chains += polylines.len();
            out_levels.push(archgeometry::SchemaContour {
                elevation_m: c.elevation_m,
                polylines_ft: polylines
                    .into_iter()
                    .map(|chain| chain.into_iter().map(|(x, y)| [x, y]).collect())
                    .collect(),
            });
        }
        if poly.is_some() {
            eprintln!("  contours: clipped {before} → {after} seg, stitched into {chains} chain(s)");
        } else {
            eprintln!("  contours: stitched {after} seg into {chains} chain(s)");
        }
        doc.site.contours_ft = out_levels;
    }

    // IFC4 export (decoupled Revit-import bridge).
    if let Some(ifc_path) = &ifc_out {
        let ifc = qbd::ifc::to_ifc(&doc, &project, &qbd::documentation::today_iso());
        std::fs::write(ifc_path, &ifc)
            .with_context(|| format!("failed to write {}", ifc_path.display()))?;
        eprintln!("  wrote {} ({} bytes)", ifc_path.display(), ifc.len());
        if bundle_dir.is_none() && out.is_none() && !bare {
            return Ok(());
        }
    }

    // `--bare` short-circuits before generate_documentation runs, so we
    // don't pay the cost of building elevations / sections / details.
    if bare {
        let config = drawing::Config::with_defaults();
        let result = qbd::generate_floor_plan_with_openings(&doc, 1219.0, &config);
        let svg = drawing::export_to_svg(&result, 10.0);
        print!("{svg}");
        return Ok(());
    }

    // Run OBC validation when `--obc <library>` was supplied so the bundle
    // can include the compliance-report sheet. Without it, the rest of the
    // pipeline still runs — just with an empty compliance section.
    let validation = if let Some(lib) = &obc_path {
        let mut engine = obc::OBCEngine::new();
        engine
            .initialize(lib)
            .with_context(|| format!("failed to initialize OBC from {}", lib.display()))?;
        let mut part3_engine = obc::Part3Engine::new();
        let part3_ok = part3_engine.initialize(lib).is_ok();
        let v = if part3_ok {
            qbd::validate_layout_with_part3(&engine, Some(&part3_engine), &doc, &climate_zone)
        } else {
            qbd::validate_layout(&engine, &doc, &climate_zone)
        };
        let part3_label = if v.part3_reports.is_empty() {
            "n/a"
        } else if v.part3_reports.iter().all(obc::ComplianceReport::passes) {
            "PASS"
        } else {
            "FAIL"
        };
        eprintln!(
            "  obc: {}/{} walls passed, thermal {} ({}), part3 {}",
            v.walls_passed,
            v.walls_checked,
            if v.thermal_compliance { "PASS" } else { "FAIL" },
            climate_zone,
            part3_label,
        );
        Some(v)
    } else {
        None
    };

    // Carry CLI-provided project identity into every sheet's title block.
    let project_info = drawing::ProjectInfo {
        name: project.clone(),
        number: doc.building_id.clone(),
        solver: "QBD Layout".into(),
        designer: designer.clone(),
        designer_bcin: bcin.clone(),
        climate_zone: climate_zone.clone(),
        ..Default::default()
    };
    let doc_options = qbd::DocumentationOptions {
        include_framing_plan: !no_framing_plan,
    };
    let docs = match &validation {
        Some(v) => qbd::generate_documentation_with_validation_and_options(
            &doc,
            project_info,
            v,
            doc_options,
        ),
        None => qbd::generate_documentation_for_project_with_options(
            &doc,
            project_info,
            doc_options,
        ),
    };

    if let Some(dir) = &bundle_dir {
        std::fs::create_dir_all(dir)
            .with_context(|| format!("failed to create bundle dir {}", dir.display()))?;

        // Rust-side bundle: all 8 sheets that the Rust pipeline can produce
        // today (site plan, floor plan, 4 elevations, section, plus
        // per-category wall section details). The Python's 9-sheet bundle
        // adds 2 schedule sheets that the Rust pipeline doesn't yet emit
        // (schedule generator is M5+ scope; the Python pipeline doesn't
        // actually write them today either due to a `extract_openings` bug
        // — see m5_diff.py for the picture).
        let write_sheet = |name: &str, body: &str| -> anyhow::Result<()> {
            let p = dir.join(name);
            let body = fit_display(body);
            std::fs::write(&p, &body).with_context(|| format!("failed to write {}", p.display()))?;
            eprintln!("  wrote {} ({} bytes)", p.display(), body.len());
            Ok(())
        };

        write_sheet("01_site_plan.svg", &docs.site_plan_svg)?;
        if !docs.foundation_plan_svg.is_empty() {
            write_sheet("08_foundation_plan.svg", &docs.foundation_plan_svg)?;
        }
        if !docs.framing_plan_svg.is_empty() {
            write_sheet("10_framing_plan.svg", &docs.framing_plan_svg)?;
        }
        write_sheet("06_roof_plan.svg", &docs.roof_plan_svg)?;
        // Floor plans: ground floor keeps the canonical name; upper storeys
        // get their own sheet so the storeys aren't overlaid.
        if docs.floor_plans.len() <= 1 {
            write_sheet("02_floor_plan.svg", &docs.floor_plan_svg)?;
        } else {
            for (i, (level, svg)) in docs.floor_plans.iter().enumerate() {
                let name = if i == 0 {
                    "02_floor_plan.svg".to_string()
                } else {
                    format!("02_floor_plan_l{}.svg", i + 1)
                };
                eprintln!("  ({level})");
                write_sheet(&name, svg)?;
            }
        }
        for elev in &docs.elevations {
            let name = drawing::elevation_sheet_name(elev.direction);
            write_sheet(&name, &elev.svg)?;
        }
        write_sheet("04_section_aa.svg", &docs.section_svg)?;

        // Schedules: only emit when non-empty (parity with permit
        // convention — no blank schedule sheets).
        if !docs.door_schedule_svg.is_empty() {
            write_sheet("05_door_schedule.svg", &docs.door_schedule_svg)?;
        }
        if !docs.window_schedule_svg.is_empty() {
            write_sheet("05_window_schedule.svg", &docs.window_schedule_svg)?;
        }

        for (i, detail) in docs.wall_details.iter().enumerate() {
            let name = format!(
                "07_wall_detail_{:02}_{}.svg",
                i + 1,
                detail.detail.wall_type_id
            );
            write_sheet(&name, &detail.svg)?;
        }

        if !docs.footing_detail_svg.is_empty() {
            write_sheet("11_footing_detail.svg", &docs.footing_detail_svg)?;
        }
        if !docs.stair_section_svg.is_empty() {
            write_sheet("12_stair_section.svg", &docs.stair_section_svg)?;
        }
        if !docs.compliance_report_svg.is_empty() {
            write_sheet("09_compliance_report.svg", &docs.compliance_report_svg)?;
        }

        // Manifest declaring what's present vs M5+ deferred.
        let elev_lines: String = docs
            .elevations
            .iter()
            .map(|e| format!(",\n    \"{}\"", drawing::elevation_sheet_name(e.direction)))
            .collect();
        let detail_lines: String = (0..docs.wall_details.len())
            .map(|i| {
                format!(
                    ",\n    \"07_wall_detail_{:02}_{}.svg\"",
                    i + 1,
                    docs.wall_details[i].detail.wall_type_id
                )
            })
            .collect();
        let foundation_line = if docs.foundation_plan_svg.is_empty() {
            String::new()
        } else {
            String::from(",\n    \"08_foundation_plan.svg\"")
        };
        let framing_line = if docs.framing_plan_svg.is_empty() {
            String::new()
        } else {
            String::from(",\n    \"10_framing_plan.svg\"")
        };
        let footing_line = if docs.footing_detail_svg.is_empty() {
            String::new()
        } else {
            String::from(",\n    \"11_footing_detail.svg\"")
        };
        let compliance_line = if docs.compliance_report_svg.is_empty() {
            String::new()
        } else {
            String::from(",\n    \"09_compliance_report.svg\"")
        };
        let manifest = format!(
            "{{\n  \"project\": \"{}\",\n  \"generated_date\": \"{}\",\n  \"produced\": [\n    \"01_site_plan.svg\"{foundation_line},\n    \"02_floor_plan.svg\"{elev_lines},\n    \"04_section_aa.svg\"{detail_lines}{framing_line}{footing_line}{compliance_line}\n  ],\n  \"deferred_to_m5_plus\": [\n    \"05_door_schedule.svg\",\n    \"05_window_schedule.svg\"\n  ]\n}}\n",
            docs.project_name, docs.generated_date,
        );
        std::fs::write(dir.join("manifest.json"), manifest)?;
        eprintln!("  wrote {}/manifest.json", dir.display());
    }

    // PDF bundle: one PDF per sheet, same naming as SVG bundle. Runs in
    // addition to `--bundle` so one invocation can emit both.
    if let Some(dir) = &pdf_dir {
        std::fs::create_dir_all(dir)
            .with_context(|| format!("failed to create pdf dir {}", dir.display()))?;

        let write_pdf = |name: &str, svg: &str| -> anyhow::Result<()> {
            let pdf = qbd::svg_to_pdf(svg)
                .with_context(|| format!("failed to convert {name} to PDF"))?;
            let p = dir.join(name);
            std::fs::write(&p, &pdf)
                .with_context(|| format!("failed to write {}", p.display()))?;
            eprintln!("  wrote {} ({} bytes)", p.display(), pdf.len());
            Ok(())
        };

        write_pdf("01_site_plan.pdf", &docs.site_plan_svg)?;
        if !docs.foundation_plan_svg.is_empty() {
            write_pdf("08_foundation_plan.pdf", &docs.foundation_plan_svg)?;
        }
        if !docs.framing_plan_svg.is_empty() {
            write_pdf("10_framing_plan.pdf", &docs.framing_plan_svg)?;
        }
        write_pdf("06_roof_plan.pdf", &docs.roof_plan_svg)?;
        if docs.floor_plans.len() <= 1 {
            write_pdf("02_floor_plan.pdf", &docs.floor_plan_svg)?;
        } else {
            for (i, (level, svg)) in docs.floor_plans.iter().enumerate() {
                let name = if i == 0 {
                    "02_floor_plan.pdf".to_string()
                } else {
                    format!("02_floor_plan_l{}.pdf", i + 1)
                };
                eprintln!("  ({level})");
                write_pdf(&name, svg)?;
            }
        }
        for elev in &docs.elevations {
            let name = format!("{}.pdf", drawing::elevation_sheet_name(elev.direction).replace(".svg", ""));
            write_pdf(&name, &elev.svg)?;
        }
        write_pdf("04_section_aa.pdf", &docs.section_svg)?;
        if !docs.door_schedule_svg.is_empty() {
            write_pdf("05_door_schedule.pdf", &docs.door_schedule_svg)?;
        }
        if !docs.window_schedule_svg.is_empty() {
            write_pdf("05_window_schedule.pdf", &docs.window_schedule_svg)?;
        }
        for (i, detail) in docs.wall_details.iter().enumerate() {
            let name = format!(
                "07_wall_detail_{:02}_{}.pdf",
                i + 1,
                detail.detail.wall_type_id
            );
            write_pdf(&name, &detail.svg)?;
        }
        if !docs.footing_detail_svg.is_empty() {
            write_pdf("11_footing_detail.pdf", &docs.footing_detail_svg)?;
        }
        if !docs.stair_section_svg.is_empty() {
            write_pdf("12_stair_section.pdf", &docs.stair_section_svg)?;
        }
        if !docs.compliance_report_svg.is_empty() {
            write_pdf("09_compliance_report.pdf", &docs.compliance_report_svg)?;
        }
    }

    // Combined permit set: every sheet as one multi-page PDF, in plan-set order.
    if let Some(out_path) = &pdf_combined {
        let sheets = collect_sheets(&docs);

        let pdf = qbd::svgs_to_pdf(&sheets)
            .with_context(|| "failed to assemble combined permit-set PDF")?;
        if let Some(parent) = out_path.parent() {
            if !parent.as_os_str().is_empty() {
                std::fs::create_dir_all(parent).ok();
            }
        }
        std::fs::write(out_path, &pdf)
            .with_context(|| format!("failed to write {}", out_path.display()))?;
        eprintln!(
            "  wrote {} ({} pages, {} bytes)",
            out_path.display(),
            sheets.len(),
            pdf.len()
        );
    }

    // PNG bundle: each sheet rasterised in-house (resvg + tiny-skia) — no
    // external rasteriser. Same sheet set + order as the combined PDF.
    if let Some(dir) = &png_dir {
        std::fs::create_dir_all(dir)
            .with_context(|| format!("failed to create png dir {}", dir.display()))?;
        let sheets = collect_sheets(&docs);
        let raster = qbd::Rasterizer::new();
        for (name, svg) in &sheets {
            let png = raster
                .to_png(svg, png_width)
                .with_context(|| format!("failed to rasterise {name}"))?;
            let p = dir.join(format!("{name}.png"));
            std::fs::write(&p, &png)
                .with_context(|| format!("failed to write {}", p.display()))?;
            eprintln!("  wrote {} ({} bytes)", p.display(), png.len());
        }
        eprintln!("  {} PNG sheet(s) @ {} px", sheets.len(), png_width);
    }

    // DXF bundle: floor plan + elevations as editable geometry.
    if let Some(dir) = &dxf_dir {
        std::fs::create_dir_all(dir)
            .with_context(|| format!("failed to create dxf dir {}", dir.display()))?;

        let write_dxf = |name: &str, bytes: &[u8]| -> anyhow::Result<()> {
            let p = dir.join(name);
            std::fs::write(&p, bytes)
                .with_context(|| format!("failed to write {}", p.display()))?;
            eprintln!("  wrote {} ({} bytes)", p.display(), bytes.len());
            Ok(())
        };

        if !docs.floor_plan_dxf.is_empty() {
            write_dxf("02_floor_plan.dxf", &docs.floor_plan_dxf)?;
        }
        for elev in &docs.elevations {
            if !elev.dxf.is_empty() {
                let name = drawing::elevation_sheet_name(elev.direction).replace(".svg", ".dxf");
                write_dxf(&name, &elev.dxf)?;
            }
        }
    }

    // Single-sheet emit only runs when nothing else has produced output —
    // otherwise `--bundle` invocations would also dump a 60 KB floor plan
    // to stdout.
    if bundle_dir.is_none() && pdf_dir.is_none() && pdf_combined.is_none() && dxf_dir.is_none() {
        match out {
            Some(out_path) => {
                std::fs::write(&out_path, &docs.floor_plan_svg)
                    .with_context(|| format!("failed to write {}", out_path.display()))?;
                eprintln!(
                    "wrote {} ({} bytes)",
                    out_path.display(),
                    docs.floor_plan_svg.len()
                );
            }
            None => {
                print!("{}", docs.floor_plan_svg);
            }
        }
    }

    Ok(())
}
