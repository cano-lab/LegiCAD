//! In-app sheet-layout editor.
//!
//! Arrange drawings from the building's catalogue onto fixed-size permit sheets:
//! click a thumbnail in the left palette to drop it on the current sheet, drag
//! to move, `[`/`]` (or scroll) to resize, `x` to delete, `,`/`.` to switch
//! sheets, `n` to add a sheet, `e` to export composed SVG+PDF sheets.
//!
//! The editor previews each drawing by rasterising its SVG once (resvg); export
//! re-renders the real vector SVG via `drawing::compose_freeform`, so what you
//! arrange is what you get.

use resvg::usvg;
use tiny_skia::{
    Color, FillRule, Paint, PathBuilder, Pixmap, PixmapPaint, Stroke, Transform,
};

use drawing::{FreePlacement, PaperSize};
use qbd::CatalogDrawing;

const PALETTE_W: f32 = 220.0;
const PALETTE_PAD: f32 = 6.0;
const ROW_H: f32 = 44.0; // palette row height (thumb + label)
const THUMB_W: f32 = 58.0; // palette thumbnail box width
const THUMB_BOX_H: f32 = 36.0; // palette thumbnail box height
/// Default placed-drawing width as a fraction of paper width.
const DEFAULT_W_FRAC: f32 = 0.32;

struct CatItem {
    title: String,
    svg: String,
    thumb: Pixmap,
    aspect: f32,    // w / h
    real_w_mm: f32, // real-world drawing width (0 = not to scale)
}

#[derive(Clone)]
struct Placement {
    cat: usize,
    x_mm: f32,
    y_mm: f32,
    w_mm: f32, // height = w_mm / aspect
    locked: bool,
}

/// A running export. SVGs are written up front; the slow PDF renders run on a
/// background thread that bumps `done`, so the UI thread can animate the bar.
struct ExportJob {
    dir: std::path::PathBuf,
    done: std::sync::Arc<std::sync::atomic::AtomicUsize>,
    total: usize,
    _handle: std::thread::JoinHandle<()>,
}

/// Screen↔paper mapping for the sheet (fit to the area right of the palette).
#[derive(Clone, Copy)]
struct SheetView {
    s: f32,
    ox: f32,
    oy: f32,
}

impl SheetView {
    fn to_screen(self, x: f32, y: f32) -> (f32, f32) {
        (self.ox + x * self.s, self.oy + y * self.s)
    }
    fn to_mm(self, sx: f32, sy: f32) -> (f32, f32) {
        ((sx - self.ox) / self.s, (sy - self.oy) / self.s)
    }
}

pub struct Layout {
    paper: PaperSize,
    catalog: Vec<CatItem>,
    sheets: Vec<Vec<Placement>>,
    current: usize,
    selected: Option<usize>,
    drag_off: Option<(f32, f32)>, // pointer offset within the placement (mm)
    project: drawing::ProjectInfo,
    out_dir: std::path::PathBuf,
    font: Option<fontdue::Font>,
    export_job: Option<ExportJob>,
}

impl Layout {
    /// Build the editor from a drawing catalogue, rasterising thumbnails.
    #[must_use]
    pub fn new(
        catalog: Vec<CatalogDrawing>,
        project: drawing::ProjectInfo,
        out_dir: std::path::PathBuf,
    ) -> Self {
        let mut opt = usvg::Options::default();
        opt.fontdb_mut().load_system_fonts();
        let items: Vec<CatItem> = catalog
            .into_iter()
            .filter_map(|c| {
                let (thumb, aspect) = rasterize(&c.svg, &opt, 700)?;
                // Real-world width = SVG viewBox width / authored units-per-mm.
                let real_w_mm = if c.model_units_per_mm > 0.0 {
                    viewbox_w(&c.svg).map_or(0.0, |w| w / c.model_units_per_mm)
                } else {
                    0.0
                };
                Some(CatItem { title: c.title, svg: c.svg, thumb, aspect, real_w_mm })
            })
            .collect();
        eprintln!("sheet editor: {} drawing(s) in palette", items.len());
        Self {
            paper: PaperSize::ARCH_D,
            catalog: items,
            sheets: vec![Vec::new()],
            current: 0,
            selected: None,
            drag_off: None,
            project,
            out_dir,
            font: load_ui_font(),
            export_job: None,
        }
    }

    fn view(&self, vp_w: f32, vp_h: f32) -> SheetView {
        let area_w = (vp_w - PALETTE_W).max(1.0);
        let margin = 24.0;
        let sx = (area_w - 2.0 * margin) / self.paper.w_mm;
        let sy = (vp_h - 2.0 * margin) / self.paper.h_mm;
        let s = sx.min(sy).max(0.0001);
        let ox = PALETTE_W + (area_w - self.paper.w_mm * s) * 0.5;
        let oy = (vp_h - self.paper.h_mm * s) * 0.5;
        SheetView { s, ox, oy }
    }

    /// Palette row under a screen point (one catalogue drawing per row).
    fn palette_hit(&self, x: f32, y: f32) -> Option<usize> {
        if x < 0.0 || x > PALETTE_W {
            return None;
        }
        let idx = ((y - PALETTE_PAD) / ROW_H).floor();
        if idx < 0.0 {
            return None;
        }
        #[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)]
        let i = idx as usize;
        (i < self.catalog.len()).then_some(i)
    }

    /// Placement under a screen point on the current sheet (topmost first).
    fn placement_hit(&self, view: SheetView, x: f32, y: f32) -> Option<usize> {
        let (mx, my) = view.to_mm(x, y);
        for (i, p) in self.sheets[self.current].iter().enumerate().rev() {
            let h = p.w_mm / p.aspect(self);
            if mx >= p.x_mm && mx <= p.x_mm + p.w_mm && my >= p.y_mm && my <= p.y_mm + h {
                return Some(i);
            }
        }
        None
    }

    // ----- input -----

    pub fn on_pointer_down(&mut self, x: f32, y: f32, vp_w: f32, vp_h: f32) {
        if let Some(ci) = self.palette_hit(x, y) {
            // Drop a new placement near the top-left of the sheet, cascaded.
            let n = self.sheets[self.current].len() as f32;
            let w = self.paper.w_mm * DEFAULT_W_FRAC;
            let p = Placement {
                cat: ci,
                x_mm: 30.0 + n * 12.0,
                y_mm: 30.0 + n * 12.0,
                w_mm: w,
                locked: false,
            };
            self.sheets[self.current].push(p);
            self.selected = Some(self.sheets[self.current].len() - 1);
            return;
        }
        let view = self.view(vp_w, vp_h);
        if let Some(pi) = self.placement_hit(view, x, y) {
            self.selected = Some(pi);
            let p = &self.sheets[self.current][pi];
            // Locked drawings can be selected but not dragged.
            if p.locked {
                self.drag_off = None;
            } else {
                let (mx, my) = view.to_mm(x, y);
                self.drag_off = Some((mx - p.x_mm, my - p.y_mm));
            }
        } else {
            self.selected = None;
        }
    }

    pub fn on_pointer_move(&mut self, x: f32, y: f32, vp_w: f32, vp_h: f32) {
        let Some((ox, oy)) = self.drag_off else { return };
        let Some(sel) = self.selected else { return };
        let view = self.view(vp_w, vp_h);
        let (mx, my) = view.to_mm(x, y);
        let p = &mut self.sheets[self.current][sel];
        p.x_mm = mx - ox;
        p.y_mm = my - oy;
    }

    pub fn on_pointer_up(&mut self) {
        self.drag_off = None;
    }

    /// Resize the selected drawing by a factor (e.g. 1.1 / 0.9). No-op if locked.
    pub fn resize_selected(&mut self, factor: f32) {
        if let Some(sel) = self.selected {
            let p = &mut self.sheets[self.current][sel];
            if p.locked {
                return;
            }
            p.w_mm = (p.w_mm * factor).clamp(20.0, self.paper.w_mm);
        }
    }

    /// Lock/unlock the selected drawing's size + position.
    pub fn toggle_lock_selected(&mut self) {
        if let Some(sel) = self.selected {
            let p = &mut self.sheets[self.current][sel];
            p.locked = !p.locked;
            if p.locked {
                self.drag_off = None;
            }
        }
    }

    pub fn delete_selected(&mut self) {
        if let Some(sel) = self.selected {
            self.sheets[self.current].remove(sel);
            self.selected = None;
        }
    }

    pub fn next_sheet(&mut self) {
        if !self.sheets.is_empty() {
            self.current = (self.current + 1) % self.sheets.len();
            self.selected = None;
        }
    }

    pub fn prev_sheet(&mut self) {
        if !self.sheets.is_empty() {
            self.current = (self.current + self.sheets.len() - 1) % self.sheets.len();
            self.selected = None;
        }
    }

    pub fn add_sheet(&mut self) {
        self.sheets.push(Vec::new());
        self.current = self.sheets.len() - 1;
        self.selected = None;
    }

    /// Begin export: prompt for a folder, compose + write every non-empty
    /// sheet's SVG immediately (fast), and queue the slow PDF renders so they
    /// run one-per-frame with a progress bar (see [`Layout::export_tick`]).
    pub fn begin_export(&mut self) {
        if self.sheets.iter().all(Vec::is_empty) {
            eprintln!("sheet export: nothing placed yet");
            return;
        }
        let dir = rfd::FileDialog::new()
            .set_title("Export permit sheets to folder")
            .set_directory(if self.out_dir.exists() {
                self.out_dir.clone()
            } else {
                std::env::current_dir().unwrap_or_else(|_| ".".into())
            })
            .pick_folder();
        let Some(dir) = dir else {
            eprintln!("sheet export: cancelled");
            return;
        };
        let mut pdfs: Vec<(String, String)> = Vec::new();
        for sheet in self.sheets.iter().filter(|s| !s.is_empty()) {
            let n = pdfs.len() + 1;
            let items: Vec<FreePlacement> = sheet
                .iter()
                .map(|p| {
                    let item = &self.catalog[p.cat];
                    FreePlacement {
                        svg: item.svg.clone(),
                        x_mm: p.x_mm,
                        y_mm: p.y_mm,
                        w_mm: p.w_mm,
                        h_mm: p.w_mm / p.aspect(self),
                        caption: format!("{}   {}", item.title, scale_label(item.real_w_mm, p.w_mm)),
                    }
                })
                .collect();
            let info = drawing::DrawingInfo {
                title: format!("SHEET {n}"),
                number: format!("A-1{n:02}"),
                scale: "AS NOTED".into(),
                date: qbd_today(),
                ..Default::default()
            };
            let svg = drawing::compose_freeform(&items, self.paper, &self.project, &info);
            let _ = std::fs::write(dir.join(format!("sheet_{n:02}.svg")), &svg);
            pdfs.push((format!("sheet_{n:02}.pdf"), svg));
        }
        let total = pdfs.len();
        eprintln!("sheet export: {total} sheet(s) → {}", dir.display());

        // Render PDFs on a background thread, bumping `done` so the UI thread
        // can animate the bar (svg_to_pdf is hundreds of ms per complex sheet).
        use std::sync::atomic::{AtomicUsize, Ordering};
        use std::sync::Arc;
        let done = Arc::new(AtomicUsize::new(0));
        let done_bg = Arc::clone(&done);
        let dir_bg = dir.clone();
        let handle = std::thread::spawn(move || {
            for (fname, svg) in pdfs {
                match qbd::svg_to_pdf(&svg) {
                    Ok(pdf) => {
                        let _ = std::fs::write(dir_bg.join(&fname), pdf);
                    }
                    Err(e) => eprintln!("{fname}: pdf failed — {e}"),
                }
                done_bg.fetch_add(1, Ordering::SeqCst);
            }
        });
        self.export_job = Some(ExportJob { dir, done, total, _handle: handle });
    }

    /// Clear the export job once the background thread has rendered every PDF.
    pub fn export_tick(&mut self) {
        use std::sync::atomic::Ordering;
        if let Some(job) = &self.export_job {
            if job.done.load(Ordering::SeqCst) >= job.total {
                eprintln!("sheet export: wrote {} sheet(s) to {}", job.total, job.dir.display());
                self.export_job = None;
            }
        }
    }

    // ----- render -----

    #[allow(clippy::cast_precision_loss)]
    pub fn render(&self, pix: &mut Pixmap) {
        let vp_w = pix.width() as f32;
        let vp_h = pix.height() as f32;
        pix.fill(Color::from_rgba8(235, 235, 238, 255));

        let view = self.view(vp_w, vp_h);
        let sheet_w = self.paper.w_mm * view.s;
        let sheet_h = self.paper.h_mm * view.s;

        // Sheet paper + border.
        let (px, py) = view.to_screen(0.0, 0.0);
        fill_rect(pix, px, py, sheet_w, sheet_h, Color::WHITE);
        stroke_rect(pix, px, py, sheet_w, sheet_h, Color::from_rgba8(0, 0, 0, 255), 1.5);
        // Title-block corner box (bottom-right) — matches drawing::sheet's
        // corner_title_block (TB 195 × 64 mm, 12 mm border).
        const TB_W: f32 = 195.0;
        const TB_H: f32 = 64.0;
        const TB_BORDER: f32 = 12.0;
        let (tbx, tby) = view.to_screen(
            self.paper.w_mm - TB_BORDER - TB_W,
            self.paper.h_mm - TB_BORDER - TB_H,
        );
        let tbw = TB_W * view.s;
        let tbh = TB_H * view.s;
        fill_rect(pix, tbx, tby, tbw, tbh, Color::WHITE);
        stroke_rect(pix, tbx, tby, tbw, tbh, Color::from_rgba8(80, 80, 80, 255), 1.0);
        self.text(pix, &self.project.name, tbx + 5.0, tby + 14.0, 11.0, (20, 20, 20));
        self.text(pix, "TITLE BLOCK", tbx + 5.0, tby + tbh - 6.0, 8.0, (130, 130, 130));

        // Placements.
        for (i, p) in self.sheets[self.current].iter().enumerate() {
            let item = &self.catalog[p.cat];
            let (dx, dy) = view.to_screen(p.x_mm, p.y_mm);
            let dw = p.w_mm * view.s;
            let dh = (p.w_mm / item.aspect) * view.s;
            fill_rect(pix, dx, dy, dw, dh, Color::WHITE);
            let sc_x = dw / item.thumb.width() as f32;
            let sc_y = dh / item.thumb.height() as f32;
            let t = Transform::from_row(sc_x, 0.0, 0.0, sc_y, dx, dy);
            pix.draw_pixmap(0, 0, item.thumb.as_ref(), &PixmapPaint::default(), t, None);

            let sel = self.selected == Some(i);
            let (col, wdt) = if p.locked {
                (Color::from_rgba8(0, 160, 90, 255), if sel { 2.5 } else { 1.6 })
            } else if sel {
                (Color::from_rgba8(0, 120, 215, 255), 2.5)
            } else {
                (Color::from_rgba8(90, 90, 90, 255), 1.0)
            };
            stroke_rect(pix, dx, dy, dw, dh, col, wdt);

            // Caption under the drawing: "TITLE   1:50" (+ LOCKED).
            let scale = scale_label(item.real_w_mm, p.w_mm);
            let cap = if p.locked {
                format!("{}   {scale}   [LOCKED]", item.title)
            } else {
                format!("{}   {scale}", item.title)
            };
            let tcol = if p.locked { (0, 130, 70) } else { (40, 40, 40) };
            self.text(pix, &cap, dx, dy + dh + 12.0, 10.0, tcol);
        }

        // Palette (left strip): one row per drawing = thumbnail + label.
        fill_rect(pix, 0.0, 0.0, PALETTE_W, vp_h, Color::from_rgba8(248, 248, 250, 255));
        stroke_line(pix, PALETTE_W, 0.0, PALETTE_W, vp_h, Color::from_rgba8(180, 180, 180, 255));
        let mut ty = PALETTE_PAD;
        for item in &self.catalog {
            if ty + ROW_H > vp_h {
                break;
            }
            let (bw, bh) = fit_box(item.aspect, THUMB_W, THUMB_BOX_H);
            let bx = PALETTE_PAD + (THUMB_W - bw) * 0.5;
            let by = ty + (ROW_H - bh) * 0.5;
            fill_rect(pix, bx, by, bw, bh, Color::WHITE);
            let sc_x = bw / item.thumb.width() as f32;
            let sc_y = bh / item.thumb.height() as f32;
            let t = Transform::from_row(sc_x, 0.0, 0.0, sc_y, bx, by);
            pix.draw_pixmap(0, 0, item.thumb.as_ref(), &PixmapPaint::default(), t, None);
            stroke_rect(pix, bx, by, bw, bh, Color::from_rgba8(150, 150, 150, 255), 0.8);
            // Label to the right of the thumbnail (wrapped to two short lines).
            let label_x = PALETTE_PAD + THUMB_W + 6.0;
            let avail = PALETTE_W - label_x - 4.0;
            let (l1, l2) = self.wrap_two(&item.title, 8.5, avail);
            self.text(pix, &l1, label_x, ty + ROW_H * 0.5 - 2.0, 8.5, (30, 30, 30));
            if !l2.is_empty() {
                self.text(pix, &l2, label_x, ty + ROW_H * 0.5 + 9.0, 8.5, (30, 30, 30));
            }
            ty += ROW_H;
        }

        // Help line along the very bottom.
        let sheet_no = format!(
            "SHEET {}/{}    click=place  drag=move  [ ]=size  l=lock  x=del  <-/->=sheet  n=new  e=export  v=exit",
            self.current + 1,
            self.sheets.len(),
        );
        self.text(pix, &sheet_no, PALETTE_W + 8.0, vp_h - 8.0, 10.0, (60, 60, 60));

        // Export progress bar (modal overlay).
        if let Some(job) = &self.export_job {
            let done = job.done.load(std::sync::atomic::Ordering::SeqCst).min(job.total);
            let pw = 420.0_f32;
            let ph = 90.0_f32;
            let px0 = (vp_w - pw) * 0.5;
            let py0 = (vp_h - ph) * 0.5;
            // Dim the canvas, then the panel.
            fill_rect(pix, 0.0, 0.0, vp_w, vp_h, Color::from_rgba8(0, 0, 0, 90));
            fill_rect(pix, px0, py0, pw, ph, Color::from_rgba8(40, 40, 46, 255));
            stroke_rect(pix, px0, py0, pw, ph, Color::from_rgba8(0, 120, 215, 255), 2.0);
            self.text(
                pix,
                &format!("Exporting PDFs…  {done}/{}", job.total),
                px0 + 20.0,
                py0 + 30.0,
                14.0,
                (235, 235, 235),
            );
            // Bar track + fill.
            let bx = px0 + 20.0;
            let by = py0 + 48.0;
            let bw = pw - 40.0;
            let bh = 18.0;
            fill_rect(pix, bx, by, bw, bh, Color::from_rgba8(70, 70, 78, 255));
            #[allow(clippy::cast_precision_loss)]
            let frac = if job.total > 0 {
                (done as f32 / job.total as f32).clamp(0.0, 1.0)
            } else {
                1.0
            };
            fill_rect(pix, bx, by, bw * frac, bh, Color::from_rgba8(0, 150, 90, 255));
            stroke_rect(pix, bx, by, bw, bh, Color::from_rgba8(20, 20, 24, 255), 1.0);
        }
    }

    /// Draw left-anchored text with `y` as the baseline (no-op if no font).
    fn text(&self, pix: &mut Pixmap, s: &str, x: f32, y: f32, size: f32, color: (u8, u8, u8)) {
        if let Some(font) = &self.font {
            draw_text(pix, font, s, x, y, size, color);
        }
    }

    /// Split a label into at most two lines that each fit `max_w` px at `size`.
    fn wrap_two(&self, s: &str, size: f32, max_w: f32) -> (String, String) {
        let Some(font) = &self.font else {
            return (s.to_string(), String::new());
        };
        let width = |t: &str| text_width(font, t, size);
        if width(s) <= max_w {
            return (s.to_string(), String::new());
        }
        let mut l1 = String::new();
        let mut l2 = String::new();
        for word in s.split_whitespace() {
            let target = if l1.is_empty() || width(&format!("{l1} {word}")) <= max_w {
                &mut l1
            } else {
                &mut l2
            };
            if target.is_empty() {
                *target = word.to_string();
            } else {
                target.push(' ');
                target.push_str(word);
            }
        }
        // Ellipsize line 2 if still too wide.
        while !l2.is_empty() && width(&l2) > max_w {
            l2.pop();
        }
        (l1, l2)
    }
}

impl Placement {
    fn aspect(&self, l: &Layout) -> f32 {
        l.catalog[self.cat].aspect.max(0.01)
    }
}

fn qbd_today() -> String {
    // Mirror qbd's date format without exposing the helper.
    use std::time::{SystemTime, UNIX_EPOCH};
    let secs = SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0);
    let days = secs / 86_400;
    // Rough civil date from epoch days (good enough for a sheet date stamp).
    let (y, m, d) = civil_from_days(days as i64);
    format!("{y:04}-{m:02}-{d:02}")
}

#[allow(clippy::many_single_char_names)]
fn civil_from_days(z: i64) -> (i64, u32, u32) {
    let z = z + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let m = (if mp < 10 { mp + 3 } else { mp - 9 }) as u32;
    (if m <= 2 { y + 1 } else { y }, m, d)
}

/// Parse the `viewBox` width (3rd number) from an SVG string.
fn viewbox_w(svg: &str) -> Option<f32> {
    let vb = svg.split("viewBox=\"").nth(1)?.split('"').next()?;
    let n: Vec<f32> = vb.split_whitespace().filter_map(|t| t.parse().ok()).collect();
    (n.len() == 4).then_some(n[2])
}

/// Label a placed drawing's scale: `1:N` where N = real width / paper-box width,
/// snapped to the nearest standard architectural scale when close, else rounded.
/// `real_w_mm == 0` (e.g. the site plan) renders as `NTS`.
#[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss, clippy::cast_precision_loss)]
fn scale_label(real_w_mm: f32, box_w_mm: f32) -> String {
    if real_w_mm <= 0.0 || box_w_mm <= 0.0 {
        return "NTS".to_string();
    }
    let n = real_w_mm / box_w_mm;
    const STD: [f32; 13] =
        [10.0, 20.0, 25.0, 40.0, 50.0, 60.0, 75.0, 100.0, 125.0, 150.0, 200.0, 250.0, 500.0];
    // Snap to a standard scale within 8%.
    if let Some(&s) = STD.iter().min_by(|a, b| {
        (*a - n).abs().partial_cmp(&(*b - n).abs()).unwrap_or(std::cmp::Ordering::Equal)
    }) {
        if (s - n).abs() / n <= 0.08 {
            return format!("1:{}", s as i64);
        }
    }
    // Otherwise round to a tidy step.
    let rounded = if n < 100.0 {
        ((n / 5.0).round() * 5.0) as i64
    } else {
        ((n / 25.0).round() * 25.0) as i64
    };
    format!("1:{}", rounded.max(1))
}

/// Largest (w,h) with the given aspect that fits inside (max_w, max_h).
fn fit_box(aspect: f32, max_w: f32, max_h: f32) -> (f32, f32) {
    let by_w = (max_w, max_w / aspect);
    if by_w.1 <= max_h { by_w } else { (max_h * aspect, max_h) }
}

fn rasterize(svg: &str, opt: &usvg::Options, target: u32) -> Option<(Pixmap, f32)> {
    let tree = usvg::Tree::from_str(svg, opt).ok()?;
    let sz = tree.size();
    let (w, h) = (sz.width(), sz.height());
    if w <= 0.0 || h <= 0.0 {
        return None;
    }
    let aspect = w / h;
    #[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)]
    let (pw, ph) = if aspect >= 1.0 {
        (target, ((target as f32 / aspect).round().max(1.0)) as u32)
    } else {
        (((target as f32 * aspect).round().max(1.0)) as u32, target)
    };
    let mut pm = Pixmap::new(pw, ph)?;
    let ts = Transform::from_scale(pw as f32 / w, ph as f32 / h);
    resvg::render(&tree, ts, &mut pm.as_mut());
    Some((pm, aspect))
}

// ----- text (fontdue) -----

/// Load a system UI font for editor labels. Tries Windows fonts first, then
/// common Linux/macOS paths. Returns `None` if none are found (labels off).
fn load_ui_font() -> Option<fontdue::Font> {
    let mut candidates: Vec<std::path::PathBuf> = Vec::new();
    if let Ok(windir) = std::env::var("WINDIR") {
        for f in ["Fonts\\segoeui.ttf", "Fonts\\arial.ttf", "Fonts\\tahoma.ttf"] {
            candidates.push(std::path::Path::new(&windir).join(f));
        }
    }
    candidates.push("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf".into());
    candidates.push("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf".into());
    candidates.push("/System/Library/Fonts/Supplemental/Arial.ttf".into());
    for c in candidates {
        if let Ok(bytes) = std::fs::read(&c) {
            if let Ok(f) = fontdue::Font::from_bytes(bytes, fontdue::FontSettings::default()) {
                eprintln!("sheet editor: UI font {}", c.display());
                return Some(f);
            }
        }
    }
    eprintln!("sheet editor: no UI font found — labels disabled");
    None
}

fn text_width(font: &fontdue::Font, s: &str, size: f32) -> f32 {
    s.chars().map(|c| font.metrics(c, size).advance_width).sum()
}

/// Composite a string onto the pixmap (left-anchored, `y` = baseline). The
/// destination is treated as opaque, so we blend straight RGB by coverage.
#[allow(
    clippy::cast_possible_truncation,
    clippy::cast_sign_loss,
    clippy::cast_possible_wrap,
    clippy::cast_precision_loss,
)]
fn draw_text(pix: &mut Pixmap, font: &fontdue::Font, s: &str, x: f32, y: f32, size: f32, color: (u8, u8, u8)) {
    let w = pix.width() as i32;
    let h = pix.height() as i32;
    let data = pix.data_mut();
    let mut pen = x;
    for ch in s.chars() {
        let (m, bitmap) = font.rasterize(ch, size);
        if m.width > 0 && m.height > 0 {
            let gx = (pen + m.xmin as f32).round() as i32;
            let gy = (y - (m.height as f32 + m.ymin as f32)).round() as i32;
            for row in 0..m.height {
                for col in 0..m.width {
                    let cov = bitmap[row * m.width + col];
                    if cov == 0 {
                        continue;
                    }
                    let pxp = gx + col as i32;
                    let pyp = gy + row as i32;
                    if pxp < 0 || pyp < 0 || pxp >= w || pyp >= h {
                        continue;
                    }
                    let idx = ((pyp * w + pxp) as usize) * 4;
                    let a = f32::from(cov) / 255.0;
                    let rgb = [color.0, color.1, color.2];
                    for k in 0..3 {
                        let cc = f32::from(rgb[k]);
                        let d = f32::from(data[idx + k]);
                        data[idx + k] = (cc * a + d * (1.0 - a)).round() as u8;
                    }
                    data[idx + 3] = 255;
                }
            }
        }
        pen += m.advance_width;
    }
}

// ----- tiny-skia draw helpers -----

fn fill_rect(pix: &mut Pixmap, x: f32, y: f32, w: f32, h: f32, color: Color) {
    if w <= 0.0 || h <= 0.0 {
        return;
    }
    let mut pb = PathBuilder::new();
    pb.push_rect(tiny_skia::Rect::from_xywh(x, y, w, h).unwrap());
    if let Some(path) = pb.finish() {
        let mut paint = Paint::default();
        paint.set_color(color);
        paint.anti_alias = true;
        pix.fill_path(&path, &paint, FillRule::Winding, Transform::identity(), None);
    }
}

fn stroke_rect(pix: &mut Pixmap, x: f32, y: f32, w: f32, h: f32, color: Color, width: f32) {
    if w <= 0.0 || h <= 0.0 {
        return;
    }
    let mut pb = PathBuilder::new();
    pb.push_rect(tiny_skia::Rect::from_xywh(x, y, w, h).unwrap());
    if let Some(path) = pb.finish() {
        let mut paint = Paint::default();
        paint.set_color(color);
        paint.anti_alias = true;
        let stroke = Stroke { width, ..Default::default() };
        pix.stroke_path(&path, &paint, &stroke, Transform::identity(), None);
    }
}

fn stroke_line(pix: &mut Pixmap, x1: f32, y1: f32, x2: f32, y2: f32, color: Color) {
    let mut pb = PathBuilder::new();
    pb.move_to(x1, y1);
    pb.line_to(x2, y2);
    if let Some(path) = pb.finish() {
        let mut paint = Paint::default();
        paint.set_color(color);
        paint.anti_alias = true;
        let stroke = Stroke { width: 1.0, ..Default::default() };
        pix.stroke_path(&path, &paint, &stroke, Transform::identity(), None);
    }
}
