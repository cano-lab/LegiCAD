//! `legible-stitch` — bbox + DEM directory → `terrain.json`.
//!
//! Closes the map-sketch → permit-set round trip when the Python LiDAR
//! downloader has already pulled DEMs to disk:
//!
//! ```text
//! legible-stitch --site site.json --dems C:\ontario_dems --out terrain.json
//! ```
//!
//! Reads `bbox` from a `site.json` written by the map widget (Increment 3),
//! scans `--dems` for Ontario `1km*.tif` tiles, samples a uniform grid over
//! the bbox, and writes a `{"terrain_mesh": …}` JSON that
//! `qbd_dump --terrain` consumes directly.
//!
//! After this runs, the full pipeline is:
//!
//! ```text
//! legible              → site.json (map sketch)
//! [python lidar dl]    → DEMs in <dir>
//! legible-stitch       → terrain.json
//! qbd_dump --parcel site.json --terrain terrain.json --bundle out/
//! ```

use std::path::PathBuf;

use anyhow::{Context, anyhow};
use ls_site::{
    DEFAULT_GRID_N, LatLon, LocalTileIndex, StitchError, stitch, to_terrain_json,
};

const USAGE: &str =
    "usage: legible-stitch --site <site.json> --dems <dir> --out <terrain.json> [--grid <N>]";

fn main() -> anyhow::Result<()> {
    let mut args = std::env::args().skip(1);
    let mut site: Option<PathBuf> = None;
    let mut dems: Option<PathBuf> = None;
    let mut out: Option<PathBuf> = None;
    let mut grid_n = DEFAULT_GRID_N;

    while let Some(a) = args.next() {
        match a.as_str() {
            "--site" => site = Some(PathBuf::from(args.next().ok_or_else(|| anyhow!(USAGE))?)),
            "--dems" => dems = Some(PathBuf::from(args.next().ok_or_else(|| anyhow!(USAGE))?)),
            "--out" => out = Some(PathBuf::from(args.next().ok_or_else(|| anyhow!(USAGE))?)),
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
    let dems = dems.ok_or_else(|| anyhow!("--dems required\n{USAGE}"))?;
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
    let nw = LatLon { lat_deg: lat_max, lon_deg: lon_min };
    let se = LatLon { lat_deg: lat_min, lon_deg: lon_max };

    // Scan the DEM directory.
    eprintln!("scanning {} for Ontario tiles…", dems.display());
    let index = LocalTileIndex::scan(&dems)
        .with_context(|| format!("scan {}", dems.display()))?;
    eprintln!("  found {} tile(s)", index.len());

    // Stitch.
    let res = stitch(nw, se, &index, grid_n).map_err(|e| match e {
        StitchError::DegenerateBbox => anyhow!("bbox in site.json is degenerate"),
        StitchError::OutOfZone => anyhow!("bbox is outside UTM zone 17 N"),
        StitchError::BadGridN => anyhow!("--grid must be ≥ 2"),
        StitchError::Geotiff(g) => anyhow!("geotiff error: {g}"),
    })?;
    eprintln!(
        "  grid {grid_n}x{grid_n} = {} samples, {} missed, {} tiles missing",
        res.samples_taken, res.samples_missed, res.missing.len(),
    );
    for t in &res.missing {
        eprintln!("    missing: {}  (zone {}, e {}, n {})", t.name_prefix(), t.zone, t.easting_m, t.northing_m);
    }

    // Write the terrain JSON.
    let json = to_terrain_json(&res.mesh);
    if let Some(parent) = out.parent() {
        std::fs::create_dir_all(parent).ok();
    }
    std::fs::write(&out, &json)
        .with_context(|| format!("write {}", out.display()))?;
    eprintln!(
        "wrote {} ({} vertices, elev {:.2}..{:.2} m, {:.0}'x{:.0}')",
        out.display(),
        res.mesh.vertices.len(),
        res.mesh.min_elevation,
        res.mesh.max_elevation,
        res.mesh.width_ft,
        res.mesh.depth_ft,
    );
    Ok(())
}
