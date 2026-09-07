//! Slippy-map tile schema — the XYZ projection used by OSM, Mapbox, and
//! every other web map. At zoom `z` the world is divided into `2^z × 2^z`
//! square tiles of 256×256 pixels using a Mercator-cylindrical projection.
//! Tiles run x→east starting from x=0 at lon −180°, y→south starting from
//! y=0 at the top of the projection (lat ≈ +85.05°).
//!
//! Spec: <https://wiki.openstreetmap.org/wiki/Slippy_map_tilenames>
//!
//! This module is pure math — fetching the tile pixels is increment 2.

use serde::{Deserialize, Serialize};

use crate::coord::LatLon;

/// One tile in the XYZ schema. `z` is the zoom level (0 = whole world in
/// one tile, ~19 is the typical max).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct TileCoord {
    pub z: u8,
    pub x: u32,
    pub y: u32,
}

/// Project a WGS84 lat/lon to the *fractional* tile coordinate at zoom `z`
/// (Mercator). The integer part is the tile to fetch; the fractional part
/// is the offset inside the 256-pixel tile.
#[must_use]
#[allow(clippy::similar_names, clippy::many_single_char_names)] // standard slippy-map symbol set
pub fn lat_lon_to_tile_f64(p: LatLon, z: u8) -> (f64, f64) {
    let n = f64::from(1u32 << u32::from(z));
    let x = (p.lon_deg + 180.0) / 360.0 * n;
    let lat_rad = p.lat_deg.to_radians();
    let y = (1.0 - (lat_rad.tan() + 1.0 / lat_rad.cos()).ln() / std::f64::consts::PI) / 2.0 * n;
    (x, y)
}

/// Convenience: floor the fractional coords into a [`TileCoord`].
#[must_use]
#[allow(
    clippy::cast_possible_truncation,
    clippy::cast_sign_loss,
)]
pub fn lat_lon_to_tile(p: LatLon, z: u8) -> TileCoord {
    let (x, y) = lat_lon_to_tile_f64(p, z);
    TileCoord { z, x: x.floor() as u32, y: y.floor() as u32 }
}

/// Inverse: NW corner of tile `t`. (The slippy-map convention treats the
/// tile coords as integer corners; lat decreases going down.)
#[must_use]
pub fn tile_to_lat_lon(t: TileCoord) -> LatLon {
    let n = f64::from(1u32 << u32::from(t.z));
    let lon = f64::from(t.x) / n * 360.0 - 180.0;
    let lat_rad = (std::f64::consts::PI * (1.0 - 2.0 * f64::from(t.y) / n)).sinh().atan();
    LatLon { lat_deg: lat_rad.to_degrees(), lon_deg: lon }
}

/// Pixel-space size of one tile, in CSS pixels. Used by the tile compositor
/// to lay tiles into a viewport pixmap.
pub const TILE_SIZE_PX: u32 = 256;

/// World-pixel coordinate of `p` at zoom `z`: tile coord × `TILE_SIZE_PX`.
/// This is the global pixel grid the slippy schema implicitly defines —
/// `(0, 0)` is the NW corner of tile `(0, 0)`, `(2^z * 256 - 1, ...)` is
/// the SE corner of the world.
#[must_use]
pub fn lat_lon_to_world_pixel(p: LatLon, z: u8) -> (f64, f64) {
    let (tx, ty) = lat_lon_to_tile_f64(p, z);
    let s = f64::from(TILE_SIZE_PX);
    (tx * s, ty * s)
}

/// Inverse of [`lat_lon_to_world_pixel`].
#[must_use]
#[allow(clippy::many_single_char_names)] // x/y/n/s/lon/lat are the standard Mercator symbols
pub fn world_pixel_to_lat_lon(x: f64, y: f64, z: u8) -> LatLon {
    let s = f64::from(TILE_SIZE_PX);
    let n = f64::from(1u32 << u32::from(z));
    let lon = x / s / n * 360.0 - 180.0;
    let lat_rad = (std::f64::consts::PI * (1.0 - 2.0 * (y / s) / n)).sinh().atan();
    LatLon { lat_deg: lat_rad.to_degrees(), lon_deg: lon }
}

/// Convert a fractional tile coordinate to a pixel offset inside a
/// `TILE_SIZE_PX`-square tile. Used when projecting a lat/lon onto the
/// tile's bitmap (e.g. drawing the parcel polygon).
#[must_use]
#[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)]
pub fn tile_to_pixel(tile_frac: (f64, f64)) -> (u32, u32) {
    let s = f64::from(TILE_SIZE_PX);
    (
        ((tile_frac.0.fract() + 1.0).fract() * s) as u32,
        ((tile_frac.1.fract() + 1.0).fract() * s) as u32,
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Property-based check: for any in-range point, the containing tile's
    /// NW corner must be NW of the point (smaller-or-equal lon, greater-or-
    /// equal lat), and the SE corner of the next tile must be SE of it. This
    /// is what the slippy schema guarantees and is robust to the choice of
    /// reference values.
    #[test]
    fn containing_tile_brackets_the_point_at_high_zoom() {
        let berlin = LatLon { lat_deg: 52.5074, lon_deg: 13.3850 };
        let t = lat_lon_to_tile(berlin, 18);
        let nw = tile_to_lat_lon(t);
        let se = tile_to_lat_lon(TileCoord { z: t.z, x: t.x + 1, y: t.y + 1 });
        assert!(nw.lon_deg <= berlin.lon_deg && berlin.lon_deg < se.lon_deg, "lon");
        assert!(se.lat_deg <= berlin.lat_deg && berlin.lat_deg < nw.lat_deg, "lat");
    }

    /// Sudbury at zoom 16 should round-trip back to the same tile.
    #[test]
    fn sudbury_round_trips_through_tile() {
        let sudbury = LatLon { lat_deg: 46.4917, lon_deg: -80.9930 };
        let t = lat_lon_to_tile(sudbury, 16);
        let nw = tile_to_lat_lon(t);
        // The NW corner of the containing tile is just to the NW of Sudbury.
        assert!(nw.lat_deg >= sudbury.lat_deg && nw.lat_deg - sudbury.lat_deg < 0.01);
        assert!(nw.lon_deg <= sudbury.lon_deg && sudbury.lon_deg - nw.lon_deg < 0.01);
    }

    /// World-pixel coords round-trip back to the same lat/lon.
    #[test]
    fn world_pixel_round_trips() {
        let p = LatLon { lat_deg: 46.4917, lon_deg: -80.9930 };
        for z in [8_u8, 12, 16, 18] {
            let (x, y) = lat_lon_to_world_pixel(p, z);
            let back = world_pixel_to_lat_lon(x, y, z);
            assert!((back.lat_deg - p.lat_deg).abs() < 1e-8, "lat at z={z}");
            assert!((back.lon_deg - p.lon_deg).abs() < 1e-8, "lon at z={z}");
        }
    }

    /// At zoom 0 there is exactly one tile covering the whole world.
    #[test]
    fn zoom_zero_is_one_global_tile() {
        let origin = LatLon { lat_deg: 0.0, lon_deg: 0.0 };
        let t = lat_lon_to_tile(origin, 0);
        assert_eq!(t, TileCoord { z: 0, x: 0, y: 0 });
        let antimeridian = LatLon { lat_deg: 0.0, lon_deg: 179.9999 };
        let t = lat_lon_to_tile(antimeridian, 0);
        assert_eq!(t.x, 0);
    }
}
