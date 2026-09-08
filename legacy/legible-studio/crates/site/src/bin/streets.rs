//! `legible-streets` — Overpass road network → lot-local feet → JSON.
//!
//! ```text
//! legible-streets --site site.json --out streets.json
//! ```
//!
//! Reads the parcel bbox + UTM origin from a `site.json` written by the
//! map widget, queries Overpass for `highway=*` ways inside the bbox,
//! projects each node from WGS84 → UTM 17 N → lot-local feet, and writes
//! a `streets.json` that `qbd_dump --streets` consumes.

use std::path::PathBuf;

use anyhow::{Context, anyhow};
use ls_site::{
    LatLon, OverpassClient, RoadClass, UtmCoord, utm17_from_wgs84,
};

const USAGE: &str = "usage: legible-streets --site <site.json> --out <streets.json>";
const M_TO_FT: f64 = 3.280_84;

#[allow(clippy::too_many_lines, clippy::cast_possible_truncation, clippy::cast_precision_loss)]
fn main() -> anyhow::Result<()> {
    let mut site: Option<PathBuf> = None;
    let mut out: Option<PathBuf> = None;
    let mut args = std::env::args().skip(1);
    while let Some(a) = args.next() {
        match a.as_str() {
            "--site" => site = Some(PathBuf::from(args.next().ok_or_else(|| anyhow!(USAGE))?)),
            "--out" => out = Some(PathBuf::from(args.next().ok_or_else(|| anyhow!(USAGE))?)),
            "-h" | "--help" => {
                println!("{USAGE}");
                return Ok(());
            }
            other => return Err(anyhow!("unknown flag {other}\n{USAGE}")),
        }
    }
    let site = site.ok_or_else(|| anyhow!("--site required\n{USAGE}"))?;
    let out = out.ok_or_else(|| anyhow!("--out required\n{USAGE}"))?;

    let text = std::fs::read_to_string(&site)
        .with_context(|| format!("read {}", site.display()))?;
    let v: serde_json::Value = serde_json::from_str(&text)
        .with_context(|| format!("parse {}", site.display()))?;
    let bb = v.get("bbox").ok_or_else(|| anyhow!("missing bbox in site.json"))?;
    let nw = LatLon {
        lat_deg: bb["lat_max"].as_f64().ok_or_else(|| anyhow!("bbox.lat_max"))?,
        lon_deg: bb["lon_min"].as_f64().ok_or_else(|| anyhow!("bbox.lon_min"))?,
    };
    let se = LatLon {
        lat_deg: bb["lat_min"].as_f64().ok_or_else(|| anyhow!("bbox.lat_min"))?,
        lon_deg: bb["lon_max"].as_f64().ok_or_else(|| anyhow!("bbox.lon_max"))?,
    };

    // UTM origin: prefer the explicit `utm_origin_m` field if present;
    // otherwise approximate from the bbox NW (will be off by tens of metres
    // for irregular polygons but stays close enough to read).
    let utm_origin = if let Some(o) = v.get("utm_origin_m") {
        UtmCoord {
            easting_m: o["easting_m"].as_f64().ok_or_else(|| anyhow!("utm_origin_m.easting_m"))?,
            northing_m: o["northing_m"].as_f64().ok_or_else(|| anyhow!("utm_origin_m.northing_m"))?,
            zone: 17,
            northern_hemisphere: true,
        }
    } else {
        // Fallback — project the SW corner of the bbox.
        let sw = LatLon { lat_deg: se.lat_deg, lon_deg: nw.lon_deg };
        utm17_from_wgs84(sw)
    };
    eprintln!(
        "bbox NW {:.5},{:.5}  SE {:.5},{:.5}  UTM origin e {:.0}, n {:.0}",
        nw.lat_deg, nw.lon_deg, se.lat_deg, se.lon_deg,
        utm_origin.easting_m, utm_origin.northing_m,
    );

    // Expand the query bbox slightly — Overpass clips ways at the bbox
    // boundary, but for visual context we want a hint of the surrounding
    // block. ~50 m padding.
    let pad_lat = 0.0005;
    let pad_lon = 0.0007;
    let qnw = LatLon { lat_deg: nw.lat_deg + pad_lat, lon_deg: nw.lon_deg - pad_lon };
    let qse = LatLon { lat_deg: se.lat_deg - pad_lat, lon_deg: se.lon_deg + pad_lon };

    let client = OverpassClient::new()?;
    eprintln!("querying Overpass for bbox + padding…");
    let ways = client.fetch_highways(qnw, qse)?;
    eprintln!("got {} highway way(s)", ways.len());

    // Project each way into lot-local feet.
    let mut out_streets: Vec<serde_json::Value> = Vec::with_capacity(ways.len());
    for w in &ways {
        let pts: Vec<[f64; 2]> = w
            .nodes
            .iter()
            .map(|n| {
                let u = utm17_from_wgs84(*n);
                let x_ft = (u.easting_m - utm_origin.easting_m) * M_TO_FT;
                let y_ft = (u.northing_m - utm_origin.northing_m) * M_TO_FT;
                [x_ft, y_ft]
            })
            .collect();
        if pts.len() < 2 {
            continue;
        }
        let kind = match RoadClass::from_highway_tag(&w.highway) {
            RoadClass::Arterial => "arterial",
            RoadClass::Connector => "connector",
            RoadClass::Local => "local",
            RoadClass::Path => "path",
        };
        out_streets.push(serde_json::json!({
            "name": w.name.clone().unwrap_or_default(),
            "kind": kind,
            "points_ft": pts,
        }));
    }

    let body = serde_json::json!({
        "streets_ft": out_streets,
        "source": "overpass-api.de",
    });
    let json = serde_json::to_string_pretty(&body)?;
    if let Some(parent) = out.parent() {
        std::fs::create_dir_all(parent).ok();
    }
    std::fs::write(&out, json).with_context(|| format!("write {}", out.display()))?;
    eprintln!("wrote {} ({} way(s))", out.display(), out_streets.len());
    Ok(())
}
