//! GeoTIFF reader for single-band float32 DEMs.
//!
//! Ontario's LiDAR-derived DEMs ship as `.tif` files in the GeoTIFF format:
//! a regular TIFF carrying three georeferencing tags that pin the raster
//! to its coordinate reference system (CRS).
//!
//! - **`ModelTiepointTag` (33922)** — anchor pair
//!   `[raster_x, raster_y, raster_z, model_x, model_y, model_z]` mapping a
//!   raster pixel to a CRS coordinate. We use the simple single-tiepoint
//!   form (anchor at raster `(0, 0)`).
//! - **`ModelPixelScaleTag` (33550)** — `[scale_x, scale_y, scale_z]` in
//!   CRS units per pixel (metres for UTM Ontario DEMs).
//! - **`GeoKeyDirectoryTag` (34735)** — keyed metadata; we parse just
//!   enough to read `ProjectedCSTypeGeoKey` (3072) to verify UTM 17 N
//!   (EPSG 26917 NAD83 or 32617 WGS84). Mismatches log but don't fail.
//!
//! From `(scale_x, scale_y)` and the tiepoint, any raster pixel `(rx, ry)`
//! projects to model coordinates:
//!
//! ```text
//! model_x = tie.model_x + (rx - tie.raster_x) * scale_x
//! model_y = tie.model_y - (ry - tie.raster_y) * scale_y   // y flips: raster top→down, model north→up
//! ```
//!
//! The reverse — sampling a model coordinate — is the inverse plus a
//! nearest-neighbour pickup from the raster.

use std::fs::File;
use std::io::BufReader;
use std::path::Path;

use tiff::decoder::{Decoder, DecodingResult};
use tiff::tags::Tag;

use crate::coord::{LatLon, utm17_from_wgs84};

/// Errors the reader can produce.
#[derive(Debug, thiserror::Error)]
pub enum GeoTiffError {
    #[error("I/O error: {0}")]
    Io(#[from] std::io::Error),
    #[error("TIFF decode error: {0}")]
    Tiff(#[from] tiff::TiffError),
    #[error("missing required GeoTIFF tag: {0}")]
    MissingTag(&'static str),
    #[error("unsupported sample format (expected single-band float32, got {0})")]
    Unsupported(&'static str),
}

/// Affine that maps raster pixel `(rx, ry)` to model coordinate
/// `(model_x, model_y)` in the CRS's units. For Ontario DEMs the CRS is
/// UTM 17 N and the units are metres.
#[derive(Debug, Clone, Copy)]
pub struct GeoAffine {
    /// Tiepoint's raster position (almost always `(0.0, 0.0)`).
    pub raster_origin: (f64, f64),
    /// Tiepoint's model position — i.e. the CRS coord at `raster_origin`.
    pub model_origin: (f64, f64),
    /// CRS units per raster pixel along x and y.
    pub pixel_scale: (f64, f64),
}

impl GeoAffine {
    /// Project a raster pixel to model coords.
    #[must_use]
    pub fn raster_to_model(&self, rx: f64, ry: f64) -> (f64, f64) {
        (
            self.model_origin.0 + (rx - self.raster_origin.0) * self.pixel_scale.0,
            // y flips: raster y grows DOWN, model y (northing) grows UP.
            self.model_origin.1 - (ry - self.raster_origin.1) * self.pixel_scale.1,
        )
    }

    /// Inverse: project a model coord to fractional raster pixel.
    #[must_use]
    pub fn model_to_raster(&self, mx: f64, my: f64) -> (f64, f64) {
        (
            self.raster_origin.0 + (mx - self.model_origin.0) / self.pixel_scale.0,
            self.raster_origin.1 + (self.model_origin.1 - my) / self.pixel_scale.1,
        )
    }
}

/// Header view of a GeoTIFF: dimensions, the model-to-raster affine, and
/// the CRS code (if it was readable). Cheap to read — only touches tags,
/// not pixel data.
#[derive(Debug, Clone)]
pub struct GeoTiffInfo {
    pub width: u32,
    pub height: u32,
    pub affine: GeoAffine,
    /// EPSG code from `ProjectedCSTypeGeoKey` (3072) — 26917 (NAD83 UTM 17N)
    /// or 32617 (WGS84 UTM 17N) on Ontario DEMs. `None` if the key wasn't
    /// present in the GeoKey directory.
    pub epsg: Option<u16>,
}

/// Full DEM: header + the float32 elevation raster (row-major, raster
/// origin top-left, units metres for Ontario).
#[derive(Debug, Clone)]
pub struct ElevationRaster {
    pub info: GeoTiffInfo,
    /// `width * height` float32 elevations, row-major.
    pub samples: Vec<f32>,
}

impl ElevationRaster {
    /// Sample the elevation at a model coordinate via nearest-neighbour
    /// lookup. Returns `None` if `(mx, my)` is outside the raster — bounds
    /// are checked AFTER rounding so floating-point drift within a half
    /// pixel of an edge still hits the nearest cell.
    #[must_use]
    #[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)]
    pub fn sample_model(&self, mx: f64, my: f64) -> Option<f32> {
        let (rxf, ryf) = self.info.affine.model_to_raster(mx, my);
        // Reject far-outside; tolerate half-pixel drift at the edges.
        if rxf < -0.5 || ryf < -0.5 {
            return None;
        }
        let rx = rxf.round();
        let ry = ryf.round();
        if rx < 0.0 || ry < 0.0 {
            return None;
        }
        let rx = rx as u32;
        let ry = ry as u32;
        if rx >= self.info.width || ry >= self.info.height {
            return None;
        }
        let idx = (ry as usize) * (self.info.width as usize) + (rx as usize);
        self.samples.get(idx).copied()
    }

    /// Sample the elevation at a WGS84 point, projecting through UTM 17 N.
    /// Callers responsible for verifying the raster's CRS is compatible
    /// (`info.epsg == Some(26917 or 32617)`); the projection is identical
    /// to sub-cm at NAD83 vs WGS84 inside Ontario, so we treat them as one.
    #[must_use]
    pub fn sample_wgs84(&self, p: LatLon) -> Option<f32> {
        let utm = utm17_from_wgs84(p);
        self.sample_model(utm.easting_m, utm.northing_m)
    }
}

/// Read just the header (dimensions + affine + CRS code), without
/// decoding the pixels. Useful for the tile index / fetch planner.
pub fn read_info(path: &Path) -> Result<GeoTiffInfo, GeoTiffError> {
    let file = BufReader::new(File::open(path)?);
    let mut dec = Decoder::new(file)?;
    let (width, height) = dec.dimensions()?;
    let affine = read_affine(&mut dec)?;
    let epsg = read_epsg_from_geokeys(&mut dec).ok();
    Ok(GeoTiffInfo { width, height, affine, epsg })
}

/// Read the full DEM (header + float32 samples). Errors if the TIFF isn't
/// single-band float32.
#[allow(clippy::cast_possible_truncation)]
pub fn read_elevation(path: &Path) -> Result<ElevationRaster, GeoTiffError> {
    let file = BufReader::new(File::open(path)?);
    let mut dec = Decoder::new(file)?;
    let (width, height) = dec.dimensions()?;
    let affine = read_affine(&mut dec)?;
    let epsg = read_epsg_from_geokeys(&mut dec).ok();
    // Wildcard arm is deliberate: any non-f32 decode (current or future
    // tiff variants) is unsupported on a DEM. Held open instead of an
    // exhaustive match so the crate compiles against tiff minor bumps.
    #[allow(clippy::match_wildcard_for_single_variants)]
    let samples = match dec.read_image()? {
        DecodingResult::F32(v) => v,
        other => return Err(GeoTiffError::Unsupported(decoding_kind_name(&other))),
    };
    let info = GeoTiffInfo { width, height, affine, epsg };
    Ok(ElevationRaster { info, samples })
}

/// Short label naming an unsupported `DecodingResult` variant.
#[allow(clippy::match_wildcard_for_single_variants)] // wildcard covers tiff variants the crate adds later
fn decoding_kind_name(d: &DecodingResult) -> &'static str {
    match d {
        DecodingResult::U8(_) => "u8",
        DecodingResult::U16(_) => "u16",
        DecodingResult::I16(_) => "i16",
        DecodingResult::U32(_) => "u32",
        DecodingResult::I32(_) => "i32",
        DecodingResult::U64(_) => "u64",
        DecodingResult::I64(_) => "i64",
        DecodingResult::F32(_) => "f32",
        DecodingResult::F64(_) => "f64",
        DecodingResult::I8(_) => "i8",
        _ => "unknown",
    }
}

fn read_affine<R: std::io::Read + std::io::Seek>(
    dec: &mut Decoder<R>,
) -> Result<GeoAffine, GeoTiffError> {
    let tie = dec
        .find_tag(Tag::ModelTiepointTag)?
        .ok_or(GeoTiffError::MissingTag("ModelTiepointTag"))?
        .into_f64_vec()?;
    let scale = dec
        .find_tag(Tag::ModelPixelScaleTag)?
        .ok_or(GeoTiffError::MissingTag("ModelPixelScaleTag"))?
        .into_f64_vec()?;
    if tie.len() < 6 {
        return Err(GeoTiffError::MissingTag("ModelTiepointTag too short"));
    }
    if scale.len() < 2 {
        return Err(GeoTiffError::MissingTag("ModelPixelScaleTag too short"));
    }
    Ok(GeoAffine {
        raster_origin: (tie[0], tie[1]),
        model_origin: (tie[3], tie[4]),
        pixel_scale: (scale[0], scale[1]),
    })
}

/// Parse the GeoKey directory to find `ProjectedCSTypeGeoKey` (key 3072).
/// The directory is laid out as a flat `u16` array: 4-entry header + 4-entry
/// records `(key, location, count, value)`. When `location == 0` the value is
/// inline; otherwise we'd have to read another tag — Ontario DEMs use the
/// inline form.
#[allow(clippy::cast_possible_truncation)]
fn read_epsg_from_geokeys<R: std::io::Read + std::io::Seek>(
    dec: &mut Decoder<R>,
) -> Result<u16, GeoTiffError> {
    let dir = dec
        .find_tag(Tag::GeoKeyDirectoryTag)?
        .ok_or(GeoTiffError::MissingTag("GeoKeyDirectoryTag"))?
        .into_u16_vec()?;
    if dir.len() < 4 {
        return Err(GeoTiffError::MissingTag("GeoKeyDirectory too short"));
    }
    let count = dir[3] as usize;
    for i in 0..count {
        let off = 4 + i * 4;
        if off + 3 >= dir.len() {
            break;
        }
        let (key, location, _count, value) = (dir[off], dir[off + 1], dir[off + 2], dir[off + 3]);
        // 3072 = ProjectedCSTypeGeoKey. Inline value when location == 0.
        if key == 3072 && location == 0 {
            return Ok(value);
        }
    }
    Err(GeoTiffError::MissingTag("ProjectedCSTypeGeoKey"))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;
    use tiff::encoder::{Rational, TiffEncoder, colortype};

    /// Encode a synthetic GeoTIFF in memory, write it to a temp file, then
    /// read it back via our reader. Confirms the full round trip: tags
    /// parsed, affine reconstructed, samples readable.
    fn write_sample_geotiff(path: &Path, ramp_origin_m: f64) -> Result<(), GeoTiffError> {
        // 8x8 raster, scale = 100 m/pixel, model origin (500000, 5000000) —
        // a tiny UTM 17 N tile somewhere in Ontario.
        let width: u32 = 8;
        let height: u32 = 8;
        let scale_xy: f64 = 100.0;
        let origin_x: f64 = 500_000.0;
        let origin_y: f64 = 5_000_000.0;
        let samples: Vec<f32> = (0..(width * height))
            .map(|i| ramp_origin_m as f32 + i as f32)
            .collect();

        let mut buf = Cursor::new(Vec::<u8>::new());
        {
            let mut enc = TiffEncoder::new(&mut buf)?;
            let mut img = enc.new_image::<colortype::Gray32Float>(width, height)?;
            // GeoTIFF tags.
            img.encoder().write_tag(
                Tag::ModelTiepointTag,
                &[0.0_f64, 0.0, 0.0, origin_x, origin_y, 0.0][..],
            )?;
            img.encoder().write_tag(
                Tag::ModelPixelScaleTag,
                &[scale_xy, scale_xy, 0.0][..],
            )?;
            // GeoKey directory: 1 key — ProjectedCSTypeGeoKey = 26917 (NAD83 UTM 17N).
            img.encoder().write_tag(
                Tag::GeoKeyDirectoryTag,
                &[1_u16, 1, 0, 1, 3072, 0, 1, 26917][..],
            )?;
            img.write_data(&samples)?;
        }
        // Silence unused `Rational` import warning under some feature combos.
        let _ = Rational { n: 1, d: 1 };
        std::fs::write(path, buf.into_inner())?;
        Ok(())
    }

    fn tmp_tif(name: &str) -> std::path::PathBuf {
        std::env::temp_dir().join(format!("ls-site-geotiff-test-{name}.tif"))
    }

    #[test]
    fn reads_dimensions_affine_and_epsg() {
        let p = tmp_tif("info");
        write_sample_geotiff(&p, 100.0).unwrap();
        let info = read_info(&p).unwrap();
        assert_eq!(info.width, 8);
        assert_eq!(info.height, 8);
        assert_eq!(info.affine.model_origin, (500_000.0, 5_000_000.0));
        assert_eq!(info.affine.pixel_scale, (100.0, 100.0));
        assert_eq!(info.epsg, Some(26917));
    }

    #[test]
    fn samples_round_trip_through_model_coords() {
        let p = tmp_tif("samples");
        write_sample_geotiff(&p, 200.0).unwrap();
        let r = read_elevation(&p).unwrap();
        assert_eq!(r.samples.len(), 64);
        // Pixel (0, 0) → model origin (500000, 5000000), sample = 200.0.
        let s = r.sample_model(500_000.0, 5_000_000.0).unwrap();
        assert!((s - 200.0).abs() < 1e-3, "got {s}");
        // Pixel (3, 2) (zero-indexed) → samples[2*8 + 3] = 200 + 19 = 219.
        // In model coords: x = 500000 + 3*100 = 500300, y = 5000000 - 2*100 = 4999800.
        let s = r.sample_model(500_300.0, 4_999_800.0).unwrap();
        assert!((s - 219.0).abs() < 1e-3, "got {s}");
    }

    #[test]
    fn samples_outside_the_raster_return_none() {
        let p = tmp_tif("outside");
        write_sample_geotiff(&p, 0.0).unwrap();
        let r = read_elevation(&p).unwrap();
        // West of origin and north of origin are both out of bounds.
        assert!(r.sample_model(400_000.0, 5_000_000.0).is_none());
        assert!(r.sample_model(500_000.0, 5_999_999.0).is_none());
    }

    #[test]
    fn wgs84_sampling_projects_through_utm17() {
        let p = tmp_tif("wgs84");
        write_sample_geotiff(&p, 0.0).unwrap();
        let r = read_elevation(&p).unwrap();
        // Project (500000, 5000000) UTM 17 N back to WGS84 and sample.
        let ll = crate::wgs84_from_utm17(crate::UtmCoord {
            easting_m: 500_000.0,
            northing_m: 5_000_000.0,
            zone: 17,
            northern_hemisphere: true,
        });
        let s = r.sample_wgs84(ll);
        assert!(s.is_some(), "round-trip sample missing");
    }
}
