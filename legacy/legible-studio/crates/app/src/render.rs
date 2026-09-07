//! Render a floor-plan `SliceResult` into a tiny-skia pixmap.
//!
//! Pure software rasterization — no GPU. The same drawing logic will run
//! on the Semantic OS kernel once `pk-surface-kernel` exists; only the
//! present/input shim differs (here it's `pk-surface-winit`).
#![allow(clippy::cast_precision_loss)] // window dims as f32 — values are tiny

use drawing::SliceResult;
use tiny_skia::{Color, FillRule, Paint, PathBuilder, Pixmap, Stroke, Transform};

/// World→screen mapping. `scale` is px-per-mm; the origin offset places the
/// content and flips Y (world is Y-up, the framebuffer is Y-down).
#[derive(Debug, Clone, Copy)]
pub struct View {
    pub scale: f32,
    pub offset_x: f32,
    pub offset_y: f32,
}

impl View {
    fn map(&self, x: f32, y: f32) -> (f32, f32) {
        (x * self.scale + self.offset_x, self.offset_y - y * self.scale)
    }

    /// Inverse of [`map`](Self::map): screen px → world mm. Used to turn
    /// sketch-pad clicks into world-space boundary points.
    #[must_use]
    pub fn unmap(&self, sx: f32, sy: f32) -> (f32, f32) {
        ((sx - self.offset_x) / self.scale, (self.offset_y - sy) / self.scale)
    }

    /// Apply a zoom factor about a screen-space pivot (for scroll-to-zoom).
    pub fn zoom_about(&mut self, factor: f32, px: f32, py: f32) {
        // Keep the world point under (px,py) fixed across the zoom.
        let wx = (px - self.offset_x) / self.scale;
        let wy = (self.offset_y - py) / self.scale;
        self.scale = (self.scale * factor).clamp(1e-6, 1e6);
        self.offset_x = px - wx * self.scale;
        self.offset_y = py + wy * self.scale;
    }

    pub fn pan(&mut self, dx: f32, dy: f32) {
        self.offset_x += dx;
        self.offset_y += dy;
    }
}

#[derive(Debug, Clone, Copy)]
struct Bounds {
    min_x: f32,
    min_y: f32,
    max_x: f32,
    max_y: f32,
}

fn bounds(r: &SliceResult) -> Option<Bounds> {
    let mut b = Bounds {
        min_x: f32::INFINITY,
        min_y: f32::INFINITY,
        max_x: f32::NEG_INFINITY,
        max_y: f32::NEG_INFINITY,
    };
    let mut seen = false;
    let mut acc = |x: f32, y: f32| {
        b.min_x = b.min_x.min(x);
        b.min_y = b.min_y.min(y);
        b.max_x = b.max_x.max(x);
        b.max_y = b.max_y.max(y);
    };
    for l in &r.lines {
        acc(l.start.x, l.start.y);
        acc(l.end.x, l.end.y);
        seen = true;
    }
    for pl in &r.polylines {
        for p in &pl.points {
            acc(p.x, p.y);
            seen = true;
        }
    }
    for h in &r.hatches {
        for bnd in &h.boundaries {
            for p in &bnd.points {
                acc(p.x, p.y);
                seen = true;
            }
        }
    }
    seen.then_some(b)
}

/// Compute a `View` that fits the slice result into a `w`×`h` framebuffer
/// with `margin` px on all sides. Returns a default 1:1 view if empty.
#[must_use]
pub fn fit_view(r: &SliceResult, w: u32, h: u32, margin: f32) -> View {
    let Some(b) = bounds(r) else {
        return View {
            scale: 1.0,
            offset_x: margin,
            offset_y: h as f32 - margin,
        };
    };
    let bw = (b.max_x - b.min_x).max(1.0);
    let bh = (b.max_y - b.min_y).max(1.0);
    let avail_w = (w as f32 - 2.0 * margin).max(1.0);
    let avail_h = (h as f32 - 2.0 * margin).max(1.0);
    let scale = (avail_w / bw).min(avail_h / bh);
    // Centre the content within the available area.
    let used_w = bw * scale;
    let used_h = bh * scale;
    let pad_x = (avail_w - used_w) * 0.5;
    let pad_y = (avail_h - used_h) * 0.5;
    View {
        scale,
        offset_x: margin + pad_x - b.min_x * scale,
        offset_y: margin + pad_y + b.max_y * scale,
    }
}

/// Render the slice result into `pixmap` (cleared to white first).
pub fn render(r: &SliceResult, pixmap: &mut Pixmap, view: View) {
    pixmap.fill(Color::WHITE);

    // Hatches first (filled wall fills, light grey), then strokes on top.
    let mut fill = Paint::default();
    fill.set_color_rgba8(178, 178, 178, 120);
    fill.anti_alias = true;
    for hatch in &r.hatches {
        for bnd in &hatch.boundaries {
            if let Some(path) = polyline_path(&bnd.points, true, view) {
                pixmap.fill_path(&path, &fill, FillRule::Winding, Transform::identity(), None);
            }
        }
    }

    let mut stroke_paint = Paint::default();
    stroke_paint.set_color_rgba8(0, 0, 0, 255);
    stroke_paint.anti_alias = true;
    let stroke = Stroke {
        width: 1.5,
        ..Stroke::default()
    };

    for pl in &r.polylines {
        if let Some(path) = polyline_path(&pl.points, pl.closed, view) {
            pixmap.stroke_path(&path, &stroke_paint, &stroke, Transform::identity(), None);
        }
    }
    for l in &r.lines {
        let mut pb = PathBuilder::new();
        let (x0, y0) = view.map(l.start.x, l.start.y);
        let (x1, y1) = view.map(l.end.x, l.end.y);
        pb.move_to(x0, y0);
        pb.line_to(x1, y1);
        if let Some(path) = pb.finish() {
            pixmap.stroke_path(&path, &stroke_paint, &stroke, Transform::identity(), None);
        }
    }
}

/// Clear a pixmap to white (for sketch mode with no underlying floor plan).
pub fn fill_white(pixmap: &mut Pixmap) {
    pixmap.fill(Color::WHITE);
}

/// Draw the sketched boundary: a red polyline through `points` (closed if
/// `closed`), with a dot at each vertex. `points` are world mm.
pub fn draw_boundary(points: &[(f32, f32)], closed: bool, pixmap: &mut Pixmap, view: View) {
    if points.is_empty() {
        return;
    }
    let mut paint = Paint::default();
    paint.set_color_rgba8(200, 30, 30, 255);
    paint.anti_alias = true;
    let stroke = Stroke {
        width: 2.0,
        ..Stroke::default()
    };
    if points.len() >= 2 {
        let mut pb = PathBuilder::new();
        let (x0, y0) = view.map(points[0].0, points[0].1);
        pb.move_to(x0, y0);
        for p in &points[1..] {
            let (x, y) = view.map(p.0, p.1);
            pb.line_to(x, y);
        }
        if closed {
            pb.close();
        }
        if let Some(path) = pb.finish() {
            pixmap.stroke_path(&path, &paint, &stroke, Transform::identity(), None);
        }
    }
    // Vertex dots.
    for p in points {
        let (x, y) = view.map(p.0, p.1);
        if let Some(circle) = PathBuilder::from_circle(x, y, 4.0) {
            pixmap.fill_path(&circle, &paint, FillRule::Winding, Transform::identity(), None);
        }
    }
}

/// Draw solved rooms: each `[x, y, w, h]` rect (world mm) filled light blue
/// with a dark outline.
pub fn draw_rooms(rooms: &[[f32; 4]], pixmap: &mut Pixmap, view: View) {
    let mut fill = Paint::default();
    fill.set_color_rgba8(120, 160, 220, 90);
    fill.anti_alias = true;
    let mut outline = Paint::default();
    outline.set_color_rgba8(40, 60, 110, 255);
    outline.anti_alias = true;
    let stroke = Stroke {
        width: 1.5,
        ..Stroke::default()
    };
    for &[x, y, w, h] in rooms {
        let corners = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)];
        let mut pb = PathBuilder::new();
        let (x0, y0) = view.map(corners[0].0, corners[0].1);
        pb.move_to(x0, y0);
        for c in &corners[1..] {
            let (cx, cy) = view.map(c.0, c.1);
            pb.line_to(cx, cy);
        }
        pb.close();
        if let Some(path) = pb.finish() {
            pixmap.fill_path(&path, &fill, FillRule::Winding, Transform::identity(), None);
            pixmap.stroke_path(&path, &outline, &stroke, Transform::identity(), None);
        }
    }
}

/// Draw freeform shapes: each polygon (world mm) filled green with an
/// outline, plus the in-progress profile as an open green polyline so the
/// user sees the stroke as they place points.
pub fn draw_freeforms(shapes: &[Vec<(f32, f32)>], current: &[(f32, f32)], pixmap: &mut Pixmap, view: View) {
    let mut fill = Paint::default();
    fill.set_color_rgba8(70, 170, 110, 110);
    fill.anti_alias = true;
    let mut outline = Paint::default();
    outline.set_color_rgba8(30, 110, 70, 255);
    outline.anti_alias = true;
    let stroke = Stroke {
        width: 1.8,
        ..Stroke::default()
    };
    for poly in shapes {
        if let Some(path) = poly_path(poly, true, view) {
            pixmap.fill_path(&path, &fill, FillRule::Winding, Transform::identity(), None);
            pixmap.stroke_path(&path, &outline, &stroke, Transform::identity(), None);
        }
    }
    // The stroke being drawn: open polyline + vertex dots.
    if let Some(path) = poly_path(current, false, view) {
        pixmap.stroke_path(&path, &outline, &stroke, Transform::identity(), None);
    }
    for p in current {
        let (x, y) = view.map(p.0, p.1);
        if let Some(circle) = PathBuilder::from_circle(x, y, 4.0) {
            pixmap.fill_path(&circle, &outline, FillRule::Winding, Transform::identity(), None);
        }
    }
}

/// Build a path through world-mm `(x, y)` points, optionally closed.
fn poly_path(points: &[(f32, f32)], closed: bool, view: View) -> Option<tiny_skia::Path> {
    if points.len() < 2 {
        return None;
    }
    let mut pb = PathBuilder::new();
    let (x0, y0) = view.map(points[0].0, points[0].1);
    pb.move_to(x0, y0);
    for p in &points[1..] {
        let (x, y) = view.map(p.0, p.1);
        pb.line_to(x, y);
    }
    if closed {
        pb.close();
    }
    pb.finish()
}

fn polyline_path(points: &[drawing::Point2D], closed: bool, view: View) -> Option<tiny_skia::Path> {
    if points.len() < 2 {
        return None;
    }
    let mut pb = PathBuilder::new();
    let (x0, y0) = view.map(points[0].x, points[0].y);
    pb.move_to(x0, y0);
    for p in &points[1..] {
        let (x, y) = view.map(p.x, p.y);
        pb.line_to(x, y);
    }
    if closed {
        pb.close();
    }
    pb.finish()
}

/// Pack a tiny-skia pixmap into a `0x00RRGGBB` `u32` buffer (softbuffer /
/// kernel framebuffer format). `out` must be at least `pixmap` length.
pub fn pixmap_to_argb(pixmap: &Pixmap, out: &mut [u32]) {
    for (dst, px) in out.iter_mut().zip(pixmap.pixels().iter()) {
        let r = u32::from(px.red());
        let g = u32::from(px.green());
        let b = u32::from(px.blue());
        *dst = (r << 16) | (g << 8) | b;
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use archgeometry::{SchemaDocument, SchemaWall};
    use drawing::Config;
    use glam::Vec3;

    fn rect_room_floor_plan() -> SliceResult {
        let mut doc = SchemaDocument {
            width: 5000.0,
            depth: 4000.0,
            ..Default::default()
        };
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
        qbd::generate_floor_plan_with_openings(&doc, 1219.0, &Config::with_defaults())
    }

    #[test]
    #[allow(clippy::many_single_char_names)]
    fn fit_view_keeps_geometry_in_bounds() {
        let r = rect_room_floor_plan();
        let (w, h) = (400u32, 300u32);
        let v = fit_view(&r, w, h, 20.0);
        let b = bounds(&r).unwrap();
        // Corners map inside the framebuffer.
        for (x, y) in [
            (b.min_x, b.min_y),
            (b.max_x, b.max_y),
            (b.min_x, b.max_y),
            (b.max_x, b.min_y),
        ] {
            let (sx, sy) = v.map(x, y);
            assert!(sx >= 0.0 && sx <= f32::from(u16::try_from(w).unwrap()), "sx={sx}");
            assert!(sy >= 0.0 && sy <= f32::from(u16::try_from(h).unwrap()), "sy={sy}");
        }
    }

    #[test]
    fn render_draws_non_blank_pixmap() {
        let r = rect_room_floor_plan();
        let (w, h) = (400u32, 300u32);
        let mut pixmap = Pixmap::new(w, h).unwrap();
        let v = fit_view(&r, w, h, 20.0);
        render(&r, &mut pixmap, v);
        // Some pixels must be non-white (the walls drew).
        let non_white = pixmap.pixels().iter().filter(|p| p.red() < 250).count();
        assert!(non_white > 0, "floor plan rendered nothing");
    }

    #[test]
    fn pixmap_to_argb_packs_rgb() {
        let mut pixmap = Pixmap::new(2, 1).unwrap();
        pixmap.fill(Color::from_rgba8(10, 20, 30, 255));
        let mut out = [0u32; 2];
        pixmap_to_argb(&pixmap, &mut out);
        assert_eq!(out[0], (10 << 16) | (20 << 8) | 30);
    }

    #[test]
    fn unmap_is_inverse_of_map() {
        let v = View {
            scale: 0.05,
            offset_x: 50.0,
            offset_y: 750.0,
        };
        let (wx, wy) = (3200.0, 1800.0);
        let (sx, sy) = v.map(wx, wy);
        let (rx, ry) = v.unmap(sx, sy);
        assert!((rx - wx).abs() < 1e-2);
        assert!((ry - wy).abs() < 1e-2);
    }

    #[test]
    fn draw_rooms_and_boundary_paint_pixels() {
        let mut pixmap = Pixmap::new(300, 300).unwrap();
        fill_white(&mut pixmap);
        let view = View {
            scale: 0.05,
            offset_x: 30.0,
            offset_y: 270.0,
        };
        draw_rooms(&[[0.0, 0.0, 3000.0, 2000.0], [3000.0, 0.0, 3000.0, 2000.0]], &mut pixmap, view);
        draw_boundary(&[(0.0, 0.0), (6000.0, 0.0), (6000.0, 2000.0), (0.0, 2000.0)], true, &mut pixmap, view);
        let non_white = pixmap.pixels().iter().filter(|p| p.red() < 250 || p.blue() < 250).count();
        assert!(non_white > 0);
    }

    #[test]
    fn zoom_about_keeps_pivot_world_point_fixed() {
        let mut v = View {
            scale: 2.0,
            offset_x: 50.0,
            offset_y: 200.0,
        };
        let (px, py) = (123.0, 88.0);
        let before = ((px - v.offset_x) / v.scale, (v.offset_y - py) / v.scale);
        v.zoom_about(1.5, px, py);
        let after = ((px - v.offset_x) / v.scale, (v.offset_y - py) / v.scale);
        assert!((before.0 - after.0).abs() < 1e-3);
        assert!((before.1 - after.1).abs() < 1e-3);
    }
}
