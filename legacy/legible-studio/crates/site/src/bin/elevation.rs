//! `legible-elevation` — exterior LiDAR point cloud → as-built elevations.
//!
//! ```text
//! legible-elevation --cloud exterior.xyz --out elevations.json
//! legible-elevation --cloud exterior.xyz --out elevations.json \
//!     --depth 0.5 --bin 0.1 --min-opening 0.5
//! ```
//!
//! Input is an ASCII XYZ point cloud (metres, **y up** — see [`ls_site::cloud`]).
//! Output is a JSON object with one entry per cardinal facade: bounding-rect
//! outline plus detected window/door openings in plane millimetres, ready for
//! the design-overlay renderer (Phase 3.4) and the elevation drawing path.

use std::path::PathBuf;

use anyhow::{Context, anyhow};
use ls_site::{ElevationParams, parse_xyz, project_all_elevations};

const USAGE: &str = "usage: legible-elevation --cloud <exterior.xyz> --out <elevations.json> \
[--depth <m>] [--bin <m>] [--min-opening <m>]";

fn main() -> anyhow::Result<()> {
    let mut args = std::env::args().skip(1);
    let mut cloud: Option<PathBuf> = None;
    let mut out: Option<PathBuf> = None;
    let mut params = ElevationParams::default();

    while let Some(a) = args.next() {
        match a.as_str() {
            "--cloud" => cloud = Some(PathBuf::from(next(&mut args)?)),
            "--out" => out = Some(PathBuf::from(next(&mut args)?)),
            "--depth" => params.facade_depth_m = parse(&mut args, "--depth")?,
            "--bin" => params.bin_mm = parse::<f32>(&mut args, "--bin")? * 1000.0,
            "--min-opening" => {
                params.min_opening_mm = parse::<f32>(&mut args, "--min-opening")? * 1000.0;
            }
            "-h" | "--help" => {
                println!("{USAGE}");
                return Ok(());
            }
            other => return Err(anyhow!("unknown flag {other}\n{USAGE}")),
        }
    }

    let cloud = cloud.ok_or_else(|| anyhow!("--cloud required\n{USAGE}"))?;
    let out = out.ok_or_else(|| anyhow!("--out required\n{USAGE}"))?;

    let text = std::fs::read_to_string(&cloud)
        .with_context(|| format!("read {}", cloud.display()))?;
    let points = parse_xyz(&text).map_err(|e| anyhow!("parse {}: {e}", cloud.display()))?;
    eprintln!("read {} points from {}", points.len(), cloud.display());

    let elevations = project_all_elevations(&points, &params)
        .map_err(|e| anyhow!("elevation projection failed: {e}"))?;

    let mut facades = serde_json::Map::new();
    for e in &elevations {
        eprintln!(
            "{:>5}: {:.0} × {:.0} mm, {} opening(s) ({} facade points)",
            e.facade.tag(), e.width_mm, e.height_mm, e.openings.len(), e.facade_points,
        );
        let outline: Vec<[f32; 2]> = e.outline_mm.iter().map(|v| [v.x, v.y]).collect();
        let openings: Vec<serde_json::Value> = e
            .openings
            .iter()
            .map(|o| {
                serde_json::json!({
                    "min_mm": [o.min_mm.x, o.min_mm.y],
                    "max_mm": [o.max_mm.x, o.max_mm.y],
                    "width_mm": o.width_mm(),
                    "height_mm": o.height_mm(),
                    "kind": if o.is_door() { "door" } else { "window" },
                    "cell_count": o.cell_count,
                })
            })
            .collect();
        facades.insert(
            e.facade.tag().to_string(),
            serde_json::json!({
                "width_mm": e.width_mm,
                "height_mm": e.height_mm,
                "outline_mm": outline,
                "openings": openings,
                "ground_elevation_m": e.ground_elevation_m,
                "ridge_elevation_m": e.ridge_elevation_m,
                "facade_points": e.facade_points,
            }),
        );
    }

    let json = serde_json::to_string_pretty(&serde_json::json!({ "facades": facades }))
        .context("serialize elevations JSON")?;

    if let Some(parent) = out.parent() {
        std::fs::create_dir_all(parent).ok();
    }
    std::fs::write(&out, &json).with_context(|| format!("write {}", out.display()))?;
    eprintln!("wrote {}", out.display());
    Ok(())
}

fn next(args: &mut impl Iterator<Item = String>) -> anyhow::Result<String> {
    args.next().ok_or_else(|| anyhow!(USAGE))
}

fn parse<T: std::str::FromStr>(
    args: &mut impl Iterator<Item = String>,
    flag: &str,
) -> anyhow::Result<T> {
    next(args)?
        .parse()
        .map_err(|_| anyhow!("{flag} expects a number"))
}
