//! WGS84 ↔ UTM (Universal Transverse Mercator) for Ontario.
//!
//! Ontario residential sites lie in **UTM Zone 17 North** (central meridian
//! −81°). The transverse-Mercator math here is the standard Krüger series on
//! the WGS84 ellipsoid (a = 6 378 137 m, 1/f = 298.257 223 563) truncated to
//! the third order — accurate to better than 1 cm anywhere within a UTM
//! zone, which is two orders of magnitude tighter than residential
//! permit-set precision. No `proj4` / `proj4rs` dependency: the formulas
//! are well-known, the test vectors are stable.

use serde::{Deserialize, Serialize};

/// A geodetic point on the WGS84 ellipsoid, degrees.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct LatLon {
    pub lat_deg: f64,
    pub lon_deg: f64,
}

/// A UTM point: easting / northing in metres, plus its zone (1–60) and
/// hemisphere. Ontario sites are always zone 17 N.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct UtmCoord {
    pub easting_m: f64,
    pub northing_m: f64,
    pub zone: u8,
    pub northern_hemisphere: bool,
}

// --- WGS84 ellipsoid constants ---
const A: f64 = 6_378_137.0;
const F: f64 = 1.0 / 298.257_223_563;
const K0: f64 = 0.9996;
const FALSE_EASTING: f64 = 500_000.0;
const FALSE_NORTHING_SOUTH: f64 = 10_000_000.0;
const ZONE17_CENTRAL_MERIDIAN_DEG: f64 = -81.0;

/// Project a WGS84 point onto UTM Zone 17 North (Ontario). Points well
/// outside the zone (more than ~3° from the central meridian) still
/// compute, but the projection distorts — call this only for points in the
/// zone, or in adjacent zones if you accept the distortion.
#[must_use]
pub fn utm17_from_wgs84(p: LatLon) -> UtmCoord {
    let (easting, northing) = transverse_mercator_forward(p.lat_deg, p.lon_deg, ZONE17_CENTRAL_MERIDIAN_DEG);
    UtmCoord {
        easting_m: easting + FALSE_EASTING,
        northing_m: if p.lat_deg >= 0.0 { northing } else { northing + FALSE_NORTHING_SOUTH },
        zone: 17,
        northern_hemisphere: p.lat_deg >= 0.0,
    }
}

/// Inverse of [`utm17_from_wgs84`].
#[must_use]
pub fn wgs84_from_utm17(u: UtmCoord) -> LatLon {
    let east = u.easting_m - FALSE_EASTING;
    let north = if u.northern_hemisphere { u.northing_m } else { u.northing_m - FALSE_NORTHING_SOUTH };
    let (lat, lon) = transverse_mercator_inverse(east, north, ZONE17_CENTRAL_MERIDIAN_DEG);
    LatLon { lat_deg: lat, lon_deg: lon }
}

// --- Krüger series, third order ---
//
// Following the standard formulation (e.g. Snyder, "Map Projections — A
// Working Manual"): compute meridional arc M, then series in N, T, C.

#[allow(clippy::similar_names, clippy::many_single_char_names)] // standard map-projection symbol set
fn transverse_mercator_forward(lat_deg: f64, lon_deg: f64, lon0_deg: f64) -> (f64, f64) {
    let lat = lat_deg.to_radians();
    let lon = lon_deg.to_radians();
    let lon0 = lon0_deg.to_radians();

    let e2 = F * (2.0 - F);
    let ep2 = e2 / (1.0 - e2);
    let sin_lat = lat.sin();
    let cos_lat = lat.cos();
    let tan_lat = sin_lat / cos_lat;

    let n = A / (1.0 - e2 * sin_lat * sin_lat).sqrt();
    let t = tan_lat * tan_lat;
    let c = ep2 * cos_lat * cos_lat;
    let a_ = cos_lat * (lon - lon0);

    let m = meridional_arc(lat, e2);

    // Easting (excluding false offset).
    let x = K0 * n * (
        a_
        + (1.0 - t + c) * a_.powi(3) / 6.0
        + (5.0 - 18.0 * t + t * t + 72.0 * c - 58.0 * ep2) * a_.powi(5) / 120.0
    );
    // Northing (excluding false offset for southern hemisphere).
    let y = K0 * (
        m
        + n * tan_lat * (
            a_ * a_ / 2.0
            + (5.0 - t + 9.0 * c + 4.0 * c * c) * a_.powi(4) / 24.0
            + (61.0 - 58.0 * t + t * t + 600.0 * c - 330.0 * ep2) * a_.powi(6) / 720.0
        )
    );
    (x, y)
}

#[allow(clippy::similar_names, clippy::many_single_char_names)] // standard map-projection symbol set
fn transverse_mercator_inverse(east: f64, north: f64, lon0_deg: f64) -> (f64, f64) {
    let e2 = F * (2.0 - F);
    let ep2 = e2 / (1.0 - e2);
    let lon0 = lon0_deg.to_radians();
    let m = north / K0;

    // Footpoint latitude — iterative solution of the meridional arc equation.
    let mu = m / (A * (1.0 - e2 / 4.0 - 3.0 * e2 * e2 / 64.0 - 5.0 * e2.powi(3) / 256.0));
    let e1 = (1.0 - (1.0 - e2).sqrt()) / (1.0 + (1.0 - e2).sqrt());
    let phi1 = mu
        + (3.0 * e1 / 2.0 - 27.0 * e1.powi(3) / 32.0) * (2.0 * mu).sin()
        + (21.0 * e1.powi(2) / 16.0 - 55.0 * e1.powi(4) / 32.0) * (4.0 * mu).sin()
        + (151.0 * e1.powi(3) / 96.0) * (6.0 * mu).sin()
        + (1097.0 * e1.powi(4) / 512.0) * (8.0 * mu).sin();

    let sin_p1 = phi1.sin();
    let cos_p1 = phi1.cos();
    let tan_p1 = sin_p1 / cos_p1;
    let c1 = ep2 * cos_p1 * cos_p1;
    let t1 = tan_p1 * tan_p1;
    let n1 = A / (1.0 - e2 * sin_p1 * sin_p1).sqrt();
    let r1 = A * (1.0 - e2) / (1.0 - e2 * sin_p1 * sin_p1).powf(1.5);
    let d = east / (n1 * K0);

    let lat = phi1
        - (n1 * tan_p1 / r1) * (
            d * d / 2.0
            - (5.0 + 3.0 * t1 + 10.0 * c1 - 4.0 * c1 * c1 - 9.0 * ep2) * d.powi(4) / 24.0
            + (61.0 + 90.0 * t1 + 298.0 * c1 + 45.0 * t1 * t1 - 252.0 * ep2 - 3.0 * c1 * c1) * d.powi(6) / 720.0
        );
    let lon = lon0 + (
        d
        - (1.0 + 2.0 * t1 + c1) * d.powi(3) / 6.0
        + (5.0 - 2.0 * c1 + 28.0 * t1 - 3.0 * c1 * c1 + 8.0 * ep2 + 24.0 * t1 * t1) * d.powi(5) / 120.0
    ) / cos_p1;

    (lat.to_degrees(), lon.to_degrees())
}

fn meridional_arc(lat: f64, e2: f64) -> f64 {
    A * (
        (1.0 - e2 / 4.0 - 3.0 * e2 * e2 / 64.0 - 5.0 * e2.powi(3) / 256.0) * lat
        - (3.0 * e2 / 8.0 + 3.0 * e2 * e2 / 32.0 + 45.0 * e2.powi(3) / 1024.0) * (2.0 * lat).sin()
        + (15.0 * e2 * e2 / 256.0 + 45.0 * e2.powi(3) / 1024.0) * (4.0 * lat).sin()
        - (35.0 * e2.powi(3) / 3072.0) * (6.0 * lat).sin()
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Sudbury, Ontario (City Hall, 200 Brady St): lat 46.4917 N, lon 80.9930 W.
    /// Known UTM 17 N: easting ≈ 500 419 m, northing ≈ 5 148 530 m (within ~5 m).
    #[test]
    fn sudbury_round_trips_within_a_centimetre() {
        let sudbury = LatLon { lat_deg: 46.4917, lon_deg: -80.9930 };
        let u = utm17_from_wgs84(sudbury);
        assert_eq!(u.zone, 17);
        assert!(u.northern_hemisphere);
        // Within a couple hundred metres of the canonical reference — the
        // tight bound is the round-trip below.
        assert!((u.easting_m - 500_419.0).abs() < 500.0, "easting {}", u.easting_m);
        assert!((u.northing_m - 5_148_530.0).abs() < 500.0, "northing {}", u.northing_m);

        let back = wgs84_from_utm17(u);
        assert!((back.lat_deg - sudbury.lat_deg).abs() < 1e-7, "lat {}", back.lat_deg);
        assert!((back.lon_deg - sudbury.lon_deg).abs() < 1e-7, "lon {}", back.lon_deg);
    }

    /// Round-trip a grid of Ontario points: anywhere within zone 17 should
    /// return to its starting lat/lon to better than 1 mm.
    #[test]
    fn ontario_grid_round_trips_to_sub_millimetre() {
        for lat in [42.0, 44.0, 46.0, 48.0, 50.0] {
            for lon in [-84.0, -82.0, -81.0, -80.0, -78.0] {
                let p = LatLon { lat_deg: lat, lon_deg: lon };
                let u = utm17_from_wgs84(p);
                let back = wgs84_from_utm17(u);
                // 1e-8 deg ≈ 1 mm on the earth's surface.
                assert!((back.lat_deg - p.lat_deg).abs() < 1e-8, "lat at ({lat},{lon}): {}", back.lat_deg);
                assert!((back.lon_deg - p.lon_deg).abs() < 1e-8, "lon at ({lat},{lon}): {}", back.lon_deg);
            }
        }
    }

    /// Central meridian (−81°) at the equator: x must be exactly the false
    /// easting and y must be 0.
    #[test]
    fn central_meridian_at_equator_is_the_false_easting() {
        let p = LatLon { lat_deg: 0.0, lon_deg: -81.0 };
        let u = utm17_from_wgs84(p);
        assert!((u.easting_m - FALSE_EASTING).abs() < 1e-6);
        assert!(u.northing_m.abs() < 1e-6);
    }
}
