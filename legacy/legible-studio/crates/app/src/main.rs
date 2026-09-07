//! Legible Studio desktop head — sketch pad (Increment 3) + floor-plan view.
//!
//! Bare-metal: window via `pk-surface-winit`, software rasterization via
//! tiny-skia. No Python, no GPU, no webview.
//!
//! Sketch a lot boundary; the room solver (a kernel `Solver`) lays out
//! rooms inside it, re-rendered live. Optionally underlay an existing
//! permit floor plan by passing a building.json.
//!
//! Usage:
//!     legible [building.json]      (building.json is an optional underlay)
//!
//! Controls:
//!   (opens in View mode — clicks just navigate)
//!   b            enter boundary mode (sketch the lot → solve rooms)
//!   f            enter freeform mode (draw shapes → freeform objects)
//!   m            enter map mode (OSM tiles → sketch parcel polygon)
//!   v            back to view mode (also closes map)
//!   left-click   sketch a vertex (boundary/freeform/map modes)
//!   Enter        close & solve (boundary), bank shape (freeform),
//!                save site.json (map)
//!   g            (map) fire fetch+stitch pipeline for the parcel — runs
//!                LidarDownloader + stitcher on a background thread,
//!                writes ./dems/ + ./terrain.json. Status bar shows progress.
//!   Backspace    undo last map vertex
//!   c            clear active mode's strokes
//!   right-drag   pan      scroll  zoom      Esc  quit

mod layout;
mod map;
mod render;
mod sketch;

use catalog::room_rect;
use map::Map;
use pk_object::Solver;
use pk_surface::{Button, InputEvent, KeyCode, Surface};
use pk_surface_winit::WinitSurface;
use sketch::Sketch;
use solver::{Answers, SubdivisionRoomSolver};
use tiny_skia::Pixmap;

#[allow(clippy::too_many_lines)] // the event loop reads better as one piece
fn main() -> anyhow::Result<()> {
    // Panic hook: if anything in the UI thread or a worker panics, write the
    // panic info + a backtrace to legible-crash.log next to the binary so we
    // see the cause even when stderr gets eaten by the windowing layer.
    std::panic::set_hook(Box::new(|info| {
        let bt = std::backtrace::Backtrace::force_capture();
        let line = format!("=== legible panic ===\n{info}\n--- backtrace ---\n{bt}\n");
        let _ = std::fs::write("legible-crash.log", &line);
        eprintln!("{line}");
    }));
    // Parse CLI: <building.json> [--dems <dir>] [--out <bundle_dir>].
    // Positional first arg is the optional floor-plan underlay; --dems
    // and --out control where the fetch+stitch pipeline puts tiles and
    // the final permit-set bundle.
    let mut building: Option<std::path::PathBuf> = None;
    let mut dems_override: Option<std::path::PathBuf> = None;
    let mut bundle_override: Option<std::path::PathBuf> = None;
    {
        let mut it = std::env::args().skip(1);
        while let Some(a) = it.next() {
            match a.as_str() {
                "--dems" => dems_override = it.next().map(std::path::PathBuf::from),
                "--out" => bundle_override = it.next().map(std::path::PathBuf::from),
                _ if building.is_none() => building = Some(std::path::PathBuf::from(a)),
                other => eprintln!("warning: ignoring unknown arg {other}"),
            }
        }
    }
    // Parsed building doc (for the floor-plan underlay AND the sheet editor's
    // drawing catalogue).
    let doc = building.as_ref().and_then(|p| archgeometry::parse_file(p).ok());
    let slice = doc.as_ref().map(|d| {
        qbd::generate_floor_plan_with_openings(d, 1219.0, &drawing::Config::with_defaults())
    });

    let mut surface = WinitSurface::new(1000, 800, "Legible Studio — Sketch")
        .map_err(|e| anyhow::anyhow!("window init failed: {e}"))?;

    let (w0, h0) = surface.size();
    // If we have a floor plan, fit to it; otherwise a sketch canvas at
    // 1px = 20mm with the origin near the bottom-left.
    let mut view = match &slice {
        Some(s) => render::fit_view(s, w0, h0, 40.0),
        None => render::View {
            scale: 0.05,
            offset_x: 60.0,
            offset_y: f32::from(u16::try_from(h0).unwrap_or(u16::MAX)) - 60.0,
        },
    };

    let mut sketch = Sketch::new();
    let mut rooms: Vec<[f32; 4]> = Vec::new();
    // Map mode: a separate top-level stage with its own renderer + coord
    // system. Lazily instantiated on first `m` press (the tile fetcher
    // touches the filesystem to create the cache dir, so don't pay that
    // unless the user opens the map).
    let mut map: Option<Map> = None;
    // Sheet-layout editor (key `s`). Lazily built from the building doc.
    let mut sheet: Option<layout::Layout> = None;
    // Real program-driven zoned layout (3-bed/2-bath default program). The
    // sketched boundary is the envelope; rooms tile it proportionally.
    let solver = SubdivisionRoomSolver::from_answers(&Answers::default());

    let mut panning = false;
    let mut last = (0.0f32, 0.0f32);

    let resolve = |sketch: &Sketch| -> Vec<[f32; 4]> {
        let mut scene = sketch.to_scene();
        solver.solve(&mut scene);
        scene
            .objects
            .iter()
            .filter(|o| o.kind == "room")
            .filter_map(room_rect)
            .collect()
    };

    while !surface.should_close() {
        for ev in surface.poll_input() {
            // Sheet-layout editor intercepts all input while active.
            if let Some(sh) = sheet.as_mut() {
                let (w, h) = surface.size();
                let (w, h) = (w as f32, h as f32);
                match ev {
                    InputEvent::Key { code: KeyCode::Escape, pressed: true, .. } => {
                        return Ok(());
                    }
                    InputEvent::Key { code: KeyCode::Char('v'), pressed: true, .. } => {
                        sheet = None;
                    }
                    InputEvent::Key { code: KeyCode::Char('['), pressed: true, .. } => {
                        sh.resize_selected(0.9);
                    }
                    InputEvent::Key { code: KeyCode::Char(']'), pressed: true, .. } => {
                        sh.resize_selected(1.1);
                    }
                    InputEvent::Key { code: KeyCode::Char('x'), pressed: true, .. } => {
                        sh.delete_selected();
                    }
                    InputEvent::Key { code: KeyCode::Char('l'), pressed: true, .. } => {
                        sh.toggle_lock_selected();
                    }
                    InputEvent::Key { code: KeyCode::Char(','), pressed: true, .. }
                    | InputEvent::Key { code: KeyCode::ArrowLeft, pressed: true, .. } => {
                        sh.prev_sheet();
                    }
                    InputEvent::Key { code: KeyCode::Char('.'), pressed: true, .. }
                    | InputEvent::Key { code: KeyCode::ArrowRight, pressed: true, .. } => {
                        sh.next_sheet();
                    }
                    InputEvent::Key { code: KeyCode::Char('n'), pressed: true, .. } => {
                        sh.add_sheet();
                    }
                    InputEvent::Key { code: KeyCode::Char('e'), pressed: true, .. } => {
                        sh.begin_export();
                    }
                    InputEvent::Scroll { dy, .. } => {
                        sh.resize_selected(if dy > 0.0 { 1.1 } else { 0.9 });
                    }
                    InputEvent::PointerDown { button: Button::Left, x, y } => {
                        sh.on_pointer_down(x, y, w, h);
                        last = (x, y);
                    }
                    InputEvent::PointerMove { x, y } => {
                        sh.on_pointer_move(x, y, w, h);
                        last = (x, y);
                    }
                    InputEvent::PointerUp { button: Button::Left, .. } => {
                        sh.on_pointer_up();
                    }
                    _ => {}
                }
                continue;
            }
            match ev {
                InputEvent::Key {
                    code: KeyCode::Escape,
                    pressed: true,
                    ..
                } => return Ok(()),
                InputEvent::Key {
                    code: KeyCode::Enter,
                    pressed: true,
                    ..
                } => {
                    if let Some(m) = &map {
                        match m.save_site_json() {
                            Ok(()) => eprintln!(
                                "map: wrote {} ({} vertices)",
                                m.out_path().display(),
                                m.polygon.len(),
                            ),
                            Err(e) => eprintln!("map: write failed — {e}"),
                        }
                    } else if sketch.close() {
                        rooms = resolve(&sketch);
                    }
                }
                InputEvent::Key {
                    code: KeyCode::Backspace,
                    pressed: true,
                    ..
                } => {
                    if let Some(m) = &mut map {
                        m.undo_vertex();
                    }
                }
                InputEvent::Key {
                    code: KeyCode::Char('b'),
                    pressed: true,
                    ..
                } => sketch.set_mode(sketch::Mode::Boundary),
                InputEvent::Key {
                    code: KeyCode::Char('f'),
                    pressed: true,
                    ..
                } => sketch.set_mode(sketch::Mode::Freeform),
                InputEvent::Key {
                    code: KeyCode::Char('v'),
                    pressed: true,
                    ..
                } => {
                    sketch.set_mode(sketch::Mode::View);
                    map = None;
                }
                InputEvent::Key {
                    code: KeyCode::Char('g'),
                    pressed: true,
                    ..
                } => {
                    if let Some(m) = &mut map {
                        m.run_pipeline();
                    }
                }
                InputEvent::Key {
                    code: KeyCode::Char('m'),
                    pressed: true,
                    ..
                } => {
                    if map.is_none() {
                        match Map::new(std::path::PathBuf::from("site.json")) {
                            Ok(mut m) => {
                                if let Some(d) = &dems_override {
                                    d.clone_into(&mut m.dems_dir);
                                }
                                if let Some(o) = &bundle_override {
                                    o.clone_into(&mut m.bundle_dir);
                                }
                                m.building_path.clone_from(&building);
                                eprintln!(
                                    "map: opened (site.json on Enter, dems → {}, bundle → {}, building → {})",
                                    m.dems_dir.display(),
                                    m.bundle_dir.display(),
                                    m.building_path.as_ref().map_or("(none)", |p| p.to_str().unwrap_or("?")),
                                );
                                map = Some(m);
                            }
                            Err(e) => eprintln!("map: failed to init tile fetcher — {e}"),
                        }
                    }
                }
                InputEvent::Key {
                    code: KeyCode::Char('s'),
                    pressed: true,
                    ..
                } => {
                    if sheet.is_none() {
                        match &doc {
                            Some(d) => {
                                let name = building
                                    .as_ref()
                                    .and_then(|p| p.file_stem())
                                    .map_or_else(|| "Sheet Set".to_string(), |s| s.to_string_lossy().into_owned());
                                let project = drawing::ProjectInfo {
                                    name,
                                    climate_zone: "Zone 6".into(),
                                    ..Default::default()
                                };
                                let cat = qbd::drawing_catalog(d, "Zone 6");
                                sheet = Some(layout::Layout::new(
                                    cat,
                                    project,
                                    std::path::PathBuf::from("sheets"),
                                ));
                                eprintln!(
                                    "sheet editor: click a palette thumbnail to place it; \
                                     drag to move, [/] resize, x delete, ,/. switch sheet, \
                                     n new sheet, e export, v exit"
                                );
                            }
                            None => eprintln!(
                                "sheet mode needs a building.json — pass it as the first arg"
                            ),
                        }
                    }
                }
                InputEvent::Key {
                    code: KeyCode::Char('c'),
                    pressed: true,
                    ..
                } => {
                    if let Some(m) = &mut map {
                        m.clear_polygon();
                    } else {
                        let was_boundary = sketch.mode == sketch::Mode::Boundary;
                        sketch.clear();
                        if was_boundary {
                            rooms.clear();
                        }
                    }
                }
                InputEvent::Scroll { dy, .. } => {
                    if let Some(m) = &mut map {
                        let (w, h) = surface.size();
                        let steps = if dy > 0.0 { 1 } else { -1 };
                        m.zoom_about(steps, last.0, last.1, w, h);
                    } else {
                        let factor = if dy > 0.0 { 1.1 } else { 0.9 };
                        view.zoom_about(factor, last.0, last.1);
                    }
                }
                InputEvent::PointerDown {
                    button: Button::Left,
                    x,
                    y,
                } => {
                    if let Some(m) = &mut map {
                        let (w, h) = surface.size();
                        m.add_vertex(x, y, w, h);
                    } else {
                        let (wx, wy) = view.unmap(x, y);
                        sketch.add_point(wx, wy);
                    }
                    last = (x, y);
                }
                InputEvent::PointerDown {
                    button: Button::Right,
                    x,
                    y,
                } => {
                    panning = true;
                    last = (x, y);
                }
                InputEvent::PointerUp {
                    button: Button::Right,
                    ..
                } => panning = false,
                InputEvent::PointerMove { x, y } => {
                    if panning {
                        if let Some(m) = &mut map {
                            m.pan(x - last.0, y - last.1);
                        } else {
                            view.pan(x - last.0, y - last.1);
                        }
                    }
                    last = (x, y);
                }
                _ => {}
            }
        }

        let (w, h) = surface.size();
        if w == 0 || h == 0 {
            continue;
        }
        let mut pixmap = Pixmap::new(w, h).ok_or_else(|| anyhow::anyhow!("pixmap alloc"))?;
        if let Some(sh) = sheet.as_mut() {
            sh.export_tick(); // renders one queued PDF per frame, drives the bar
            sh.render(&mut pixmap);
        } else if let Some(m) = &mut map {
            m.render(&mut pixmap);
        } else {
            match &slice {
                Some(s) => render::render(s, &mut pixmap, view),
                None => render::fill_white(&mut pixmap),
            }
            render::draw_rooms(&rooms, &mut pixmap, view);
            render::draw_boundary(&sketch.points, sketch.closed, &mut pixmap, view);
            render::draw_freeforms(&sketch.freeforms, &sketch.current, &mut pixmap, view);
        }
        render::pixmap_to_argb(&pixmap, surface.pixels_mut());
        surface.present();
    }

    Ok(())
}
