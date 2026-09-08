//! `legible-aswall` — interior LiDAR point cloud → as-built wall centrelines.
//!
//! ```text
//! legible-aswall --cloud scan.xyz --out aswalls.json
//! legible-aswall --cloud scan.xyz --out aswalls.json --level "Ground Floor" \
//!     --band-low 0.6 --band-high 1.6 --min-len 0.8
//! ```
//!
//! Input is an ASCII XYZ point cloud: one `x y z` triple per line, metres,
//! **y up** (x east, z north — the `SchemaWall` convention). Lines starting
//! with `#` and blank lines are ignored; a 4th+ column (intensity, rgb) is
//! tolerated and dropped.
//!
//! Output is a JSON object whose `walls` array is `SchemaWall`-shaped with
//! `category: "as_built"`, ready to merge into a building document or feed the
//! design-overlay renderer (Phase 3.4).

use std::path::PathBuf;

use anyhow::{Context, anyhow};
use ls_site::{WallDetectParams, detect_walls, parse_xyz};

const USAGE: &str = "usage: legible-aswall --cloud <scan.xyz> --out <aswalls.json> \
[--level <name>] [--band-low <m>] [--band-high <m>] [--min-len <m>] [--voxel <m>]";

fn main() -> anyhow::Result<()> {
    let mut args = std::env::args().skip(1);
    let mut cloud: Option<PathBuf> = None;
    let mut out: Option<PathBuf> = None;
    let mut level = "Level 1".to_string();
    let mut params = WallDetectParams::default();

    while let Some(a) = args.next() {
        match a.as_str() {
            "--cloud" => cloud = Some(PathBuf::from(next(&mut args)?)),
            "--out" => out = Some(PathBuf::from(next(&mut args)?)),
            "--level" => level = next(&mut args)?,
            "--band-low" => params.band_low_m = parse(&mut args, "--band-low")?,
            "--band-high" => params.band_high_m = parse(&mut args, "--band-high")?,
            "--min-len" => params.min_wall_len_mm = parse::<f32>(&mut args, "--min-len")? * 1000.0,
            "--voxel" => params.voxel_mm = parse::<f32>(&mut args, "--voxel")? * 1000.0,
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
    let points = parse_xyz(&text)
        .map_err(|e| anyhow!("parse {}: {e}", cloud.display()))?;
    eprintln!("read {} points from {}", points.len(), cloud.display());

    let res = detect_walls(&points, &params)
        .map_err(|e| anyhow!("wall detection failed: {e}"))?;

    eprintln!(
        "floor {:.2} m, ceiling {:.2} m (height {:.2} m); {} band points → {} voxels",
        res.floor_elevation_m, res.ceiling_elevation_m, res.wall_height_m,
        res.band_points, res.voxels,
    );
    eprintln!("detected {} wall(s)", res.walls.len());

    // SchemaWall-shaped JSON. start/end are [x, y, z] mm with y = floor.
    let floor_mm = res.floor_elevation_m * 1000.0;
    let height_mm = res.wall_height_m * 1000.0;
    let walls: Vec<serde_json::Value> = res
        .walls
        .iter()
        .map(|w| {
            serde_json::json!({
                "start": [w.start_mm.x, floor_mm, w.start_mm.y],
                "end":   [w.end_mm.x,   floor_mm, w.end_mm.y],
                "height": height_mm,
                "wall_type": "as_built",
                "category": "as_built",
                "existing": true,
                "level_name": level,
                "rooms": ["", ""],
                "is_pinned": false,
                "locked_properties": [],
                // Extra as-built metadata (ignored by SchemaWall's serde).
                "thickness_mm": w.thickness_mm,
                "point_count": w.point_count,
            })
        })
        .collect();

    let json = serde_json::to_string_pretty(&serde_json::json!({
        "walls": walls,
        "floor_elevation_m": res.floor_elevation_m,
        "ceiling_elevation_m": res.ceiling_elevation_m,
        "wall_height_m": res.wall_height_m,
        "band_points": res.band_points,
        "voxels": res.voxels,
    }))
    .context("serialize as-built JSON")?;

    if let Some(parent) = out.parent() {
        std::fs::create_dir_all(parent).ok();
    }
    std::fs::write(&out, &json).with_context(|| format!("write {}", out.display()))?;
    eprintln!("wrote {} ({} walls)", out.display(), walls.len());
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
