//! `drawing_dump` — Rust counterpart to the kernel's `drawing_dump`.
//!
//! Reads the shared fixture JSON, builds an equivalent `Building` (one
//! `WallType` + one `ParametricWall` per wall, parallel arrays), runs
//! the slicer, prints the SVG to stdout. Output is line-by-line
//! diffable against the C++ tool — see `rust/tests/m4_diff.py`.
//!
//! Usage:
//!     drawing_dump <fixture.json>

use domain::{Building, LayerFunction, ParametricWall, WallLayer, WallType};
use drawing::{Config, export_to_svg, generate_floor_plan};
use glam::{Vec2, Vec3};
use serde::Deserialize;
use std::fs;
use std::path::PathBuf;

#[derive(Debug, Deserialize)]
struct WallJson {
    start: [f32; 2],
    end: [f32; 2],
    #[serde(default = "default_thickness")]
    thickness: f32,
    #[serde(default = "default_height")]
    height: f32,
}

fn default_thickness() -> f32 {
    150.0
}
fn default_height() -> f32 {
    3000.0
}

#[derive(Debug, Deserialize)]
struct FixtureJson {
    #[serde(default = "default_scale")]
    scale: f32,
    #[serde(default = "default_cut_height")]
    cut_height: f32,
    walls: Vec<WallJson>,
}

fn default_scale() -> f32 {
    0.01
}
fn default_cut_height() -> f32 {
    1500.0
}

fn main() -> anyhow::Result<()> {
    let path: PathBuf = std::env::args()
        .nth(1)
        .ok_or_else(|| anyhow::anyhow!("usage: drawing_dump <fixture.json>"))?
        .into();

    let bytes =
        fs::read(&path).map_err(|e| anyhow::anyhow!("cannot read {}: {e}", path.display()))?;
    let fixture: FixtureJson = serde_json::from_slice(&bytes)?;

    let mut building = Building::default();
    for (i, w) in fixture.walls.iter().enumerate() {
        let wt = WallType {
            id: format!("wt_{i}"),
            name: format!("wt_{i}"),
            layers: vec![WallLayer {
                name: "structure".into(),
                material: String::new(),
                function: LayerFunction::Structure,
                thickness: w.thickness,
                color: Vec3::splat(0.8),
                r_value: 0.0,
                fasteners: Vec::new(),
            }],
            ..Default::default()
        };
        building.wall_types.push(wt);
        building.parametric_walls.push(ParametricWall {
            id: format!("pw_{i}"),
            start_point: Vec2::new(w.start[0], w.start[1]),
            end_point: Vec2::new(w.end[0], w.end[1]),
            base_height: 0.0,
            top_height: w.height,
            wall_type_index: u32::try_from(i)?,
            ..Default::default()
        });
    }

    let result = generate_floor_plan(&building, fixture.cut_height, &Config::with_defaults());
    let svg = export_to_svg(&result, fixture.scale);
    print!("{svg}");
    Ok(())
}
