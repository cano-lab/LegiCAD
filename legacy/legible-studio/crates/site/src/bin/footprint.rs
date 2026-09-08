//! `legible-footprint` — bbox + DSM/DTM tiles → building footprint polygon.
//!
//! Simple height-threshold + convex-hull extraction:
//!
//! ```text
//! legible-footprint --site site.json --dsm C:\ontario_dsm --out footprint.json
//! legible-footprint --site site.json --dsm C:\ontario_dsm --dtm C:\ontario_dtm --out footprint.json
//! ```
//!
//! Reads `bbox` from a `site.json` written by the map widget, scans the
//! DSM (and optionally DTM) directories for Ontario `1km*.tif` tiles,
//! samples a uniform grid, thresholds points that are taller than
//! `--threshold` metres above ground, and writes the 2-D convex hull as a
//! polygon JSON that `qbd_dump --footprint` consumes directly.

use std::path::PathBuf;

use anyhow::{Context, anyhow};
use ls_site::{LatLon, LocalTileIndex, extract_footprint};

const USAGE: &str = "usage: legible-footprint --site <site.json> --dsm <dir> [--dtm <dir>] --out <footprint.json> [--threshold <m>] [--grid <N>]";

fn main() -> anyhow::Result<()> {
    let mut args = std::env::args().skip(1);
    let mut site: Option<PathBuf> = None;
    let mut dsm_dir: Option<PathBuf> = None;
    let mut dtm_dir: Option<PathBuf> = None;
    let mut out: Option<PathBuf> = None;
    let mut threshold_m = 2.0_f32;
    let mut grid_n = 65usize;

    while let Some(a) = args.next() {
        match a.as_str() {
            "--site" => {
                site = Some(PathBuf::from(args.next().ok_or_else(|| anyhow!(USAGE))?));
            }
            "--dsm" => {
                dsm_dir = Some(PathBuf::from(args.next().ok_or_else(|| anyhow!(USAGE))?));
            }
            "--dtm" => {
                dtm_dir = Some(PathBuf::from(args.next().ok_or_else(|| anyhow!(USAGE))?));
            }
            "--out" => {
                out = Some(PathBuf::from(args.next().ok_or_else(|| anyhow!(USAGE))?));
            }
            "--threshold" => {
                threshold_m = args
                    .next()
                    .and_then(|s| s.parse().ok())
                    .ok_or_else(|| anyhow!("--threshold expects a positive number"))?;
            }
            "--grid" => {
                grid_n = args
                    .next()
                    .and_then(|s| s.parse().ok())
                    .ok_or_else(|| anyhow!("--grid expects a positive integer"))?;
            }
            "-h" | "--help" => {
                println!("{USAGE}");
                return Ok(());
            }
            other => return Err(anyhow!("unknown flag {other}\n{USAGE}")),
        }
    }

    let site = site.ok_or_else(|| anyhow!("--site required\n{USAGE}"))?;
    let dsm_dir = dsm_dir.ok_or_else(|| anyhow!("--dsm required\n{USAGE}"))?;
    let out = out.ok_or_else(|| anyhow!("--out required\n{USAGE}"))?;

    // Read bbox from the map widget's site.json.
    let site_text = std::fs::read_to_string(&site)
        .with_context(|| format!("read {}", site.display()))?;
    let site_v: serde_json::Value = serde_json::from_str(&site_text)
        .with_context(|| format!("parse {}", site.display()))?;
    let bbox = site_v
        .get("bbox")
        .ok_or_else(|| anyhow!("missing bbox in {}", site.display()))?;
    let lat_max = bbox["lat_max"].as_f64().ok_or_else(|| anyhow!("bbox.lat_max"))?;
    let lat_min = bbox["lat_min"].as_f64().ok_or_else(|| anyhow!("bbox.lat_min"))?;
    let lon_min = bbox["lon_min"].as_f64().ok_or_else(|| anyhow!("bbox.lon_min"))?;
    let lon_max = bbox["lon_max"].as_f64().ok_or_else(|| anyhow!("bbox.lon_max"))?;
    let nw = LatLon {
        lat_deg: lat_max,
        lon_deg: lon_min,
    };
    let se = LatLon {
        lat_deg: lat_min,
        lon_deg: lon_max,
    };

    // Scan tile directories.
    eprintln!("scanning {} for DSM tiles…", dsm_dir.display());
    let dsm_index = LocalTileIndex::scan(&dsm_dir)
        .with_context(|| format!("scan {}", dsm_dir.display()))?;
    eprintln!("  found {} DSM tile(s)", dsm_index.len());

    let dtm_index = if let Some(ref d) = dtm_dir {
        eprintln!("scanning {} for DTM tiles…", d.display());
        let idx = LocalTileIndex::scan(d).with_context(|| format!("scan {}", d.display()))?;
        eprintln!("  found {} DTM tile(s)", idx.len());
        Some(idx)
    } else {
        None
    };

    let dtm_ref = dtm_index.as_ref();

    let res = extract_footprint(nw, se, &dsm_index, dtm_ref, grid_n, threshold_m)
        .map_err(|e| anyhow!("footprint extraction failed: {e}"))?;

    eprintln!(
        "  grid {grid_n}x{grid_n} = {} samples, {} above {threshold_m} m",
        res.total_samples, res.samples_above_threshold,
    );
    eprintln!(
        "  ground elev {:.2} m, max height {:.2} m, hull has {} vertices",
        res.ground_elevation_m, res.max_height_above_ground_m, res.polygon_mm.len(),
    );

    // Write JSON — bare array is accepted by qbd_dump --footprint, but we
    // also emit the keyed form for clarity.
    let poly: Vec<[f32; 2]> = res
        .polygon_mm
        .iter()
        .map(|v| [v.x, v.y])
        .collect();
    let json = serde_json::to_string_pretty(&serde_json::json!({
        "footprint_polygon_mm": poly,
        "ground_elevation_m": res.ground_elevation_m,
        "max_height_above_ground_m": res.max_height_above_ground_m,
        "samples_above_threshold": res.samples_above_threshold,
        "total_samples": res.total_samples,
    }))
    .context("serialize footprint JSON")?;

    if let Some(parent) = out.parent() {
        std::fs::create_dir_all(parent).ok();
    }
    std::fs::write(&out, &json)
        .with_context(|| format!("write {}", out.display()))?;
    eprintln!("wrote {} ({} vertices)", out.display(), poly.len());
    Ok(())
}
