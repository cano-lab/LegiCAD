//! Pure-Rust SVG → PNG rasterisation (resvg + tiny-skia).
//!
//! Keeps plan previews in-house — no Inkscape or other external rasteriser.
//! `resvg`/`usvg`/`tiny-skia` are already in the build: the desktop head
//! (`ls-app`) renders sheet thumbnails with them, and the PDF path (`svg2pdf`)
//! pulls the same crates. This is the headless equivalent of the app's
//! thumbnail rasteriser, exposed for the CLI and the API.

use resvg::tiny_skia::{Pixmap, Transform};
use resvg::usvg;

/// Errors from rasterising an SVG sheet.
#[derive(Debug, thiserror::Error)]
pub enum RasterError {
    #[error("invalid SVG: {0}")]
    Parse(#[from] usvg::Error),
    #[error("drawing has zero size")]
    EmptySize,
    #[error("pixmap allocation failed ({0}×{1} px)")]
    Alloc(u32, u32),
    #[error("PNG encode failed: {0}")]
    Encode(String),
}

/// Reusable rasteriser. Loading the system font database is the expensive part
/// (the sheets are text-heavy — room labels, dimensions, schedules, the title
/// block — and need real fonts), so build one and reuse it across a bundle.
pub struct Rasterizer {
    opt: usvg::Options<'static>,
}

impl Default for Rasterizer {
    fn default() -> Self {
        Self::new()
    }
}

impl Rasterizer {
    /// Build a rasteriser with the system fonts loaded.
    #[must_use]
    pub fn new() -> Self {
        let mut opt = usvg::Options::default();
        opt.fontdb_mut().load_system_fonts();
        Self { opt }
    }

    /// Rasterise `svg` so its longer side is `target_px` pixels, preserving the
    /// drawing's aspect ratio. Returns the rendered pixmap.
    pub fn to_pixmap(&self, svg: &str, target_px: u32) -> Result<Pixmap, RasterError> {
        let tree = usvg::Tree::from_str(svg, &self.opt)?;
        let size = tree.size();
        let (w, h) = (size.width(), size.height());
        if w <= 0.0 || h <= 0.0 {
            return Err(RasterError::EmptySize);
        }
        let aspect = w / h;
        let target = target_px.max(1);
        #[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss, clippy::cast_precision_loss)]
        let (pw, ph) = if aspect >= 1.0 {
            (target, ((target as f32 / aspect).round().max(1.0)) as u32)
        } else {
            (((target as f32 * aspect).round().max(1.0)) as u32, target)
        };
        let mut pm = Pixmap::new(pw, ph).ok_or(RasterError::Alloc(pw, ph))?;
        #[allow(clippy::cast_precision_loss)]
        let ts = Transform::from_scale(pw as f32 / w, ph as f32 / h);
        resvg::render(&tree, ts, &mut pm.as_mut());
        Ok(pm)
    }

    /// Rasterise `svg` to PNG bytes at `target_px` on the longer side.
    pub fn to_png(&self, svg: &str, target_px: u32) -> Result<Vec<u8>, RasterError> {
        let pm = self.to_pixmap(svg, target_px)?;
        pm.encode_png().map_err(|e| RasterError::Encode(e.to_string()))
    }
}

/// One-shot convenience: rasterise a single SVG to PNG bytes. Builds a throwaway
/// font database — prefer a reused [`Rasterizer`] for a whole sheet bundle.
pub fn svg_to_png(svg: &str, target_px: u32) -> Result<Vec<u8>, RasterError> {
    Rasterizer::new().to_png(svg, target_px)
}

#[cfg(test)]
mod tests {
    use super::*;

    const SVG: &str = r##"<?xml version="1.0"?>
<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100" viewBox="0 0 200 100">
  <rect width="200" height="100" fill="white"/>
  <line x1="10" y1="10" x2="190" y2="90" stroke="black" stroke-width="4"/>
  <text x="20" y="50" font-family="Arial" font-size="20" fill="black">UP</text>
</svg>"##;

    #[test]
    fn renders_png_with_a_valid_signature_and_aspect() {
        let r = Rasterizer::new();
        let png = r.to_png(SVG, 400).expect("rasterise");
        // PNG magic number.
        assert_eq!(&png[..8], &[0x89, b'P', b'N', b'G', b'\r', b'\n', 0x1a, b'\n']);
        // 2:1 drawing → 400×200 pixmap.
        let pm = r.to_pixmap(SVG, 400).unwrap();
        assert_eq!((pm.width(), pm.height()), (400, 200));
    }

    #[test]
    fn ink_is_actually_drawn_not_a_blank_canvas() {
        // At least one non-white pixel (the diagonal line / glyph).
        let pm = Rasterizer::new().to_pixmap(SVG, 200).unwrap();
        let any_ink = pm.pixels().iter().any(|p| p.red() < 200 || p.green() < 200 || p.blue() < 200);
        assert!(any_ink, "rasterised sheet is blank");
    }

    #[test]
    fn invalid_svg_is_an_error_not_a_panic() {
        assert!(svg_to_png("not an svg at all", 256).is_err());
    }
}
