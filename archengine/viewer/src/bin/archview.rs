//! archview — interactive game-style viewer for structural scenes.
//!
//! ```sh
//! archview --scene scene.json
//! ```
//!
//! Controls: WASD move, Q/E down/up, hold right mouse for look, scroll for
//! speed, Esc to quit.

use std::fs;
use std::path::PathBuf;

use anyhow::{Context, Result};
use archengine_geometry::domain::StructuralElement;

#[derive(Default)]
struct Args {
    scene: PathBuf,
    env: Option<PathBuf>,
    no_validation: bool,
}

fn parse_args() -> Result<Args> {
    let mut args = Args::default();
    let mut it = std::env::args().skip(1);
    let mut scene_set = false;
    while let Some(arg) = it.next() {
        match arg.as_str() {
            "--scene" => {
                args.scene = PathBuf::from(it.next().context("--scene needs a value")?);
                scene_set = true;
            }
            "--env" => {
                args.env = Some(PathBuf::from(it.next().context("--env needs a value")?));
            }
            "--no-validation" => args.no_validation = true,
            "-h" | "--help" => {
                eprintln!(
                    "archview --scene <scene.json> [--env <sky.hdr>] [--no-validation]\n\n\
                     Interactive WASD + mouse-look viewer (raster pipeline).\n\
                     --env loads an equirectangular HDR for the sky."
                );
                std::process::exit(0);
            }
            other => anyhow::bail!("unknown argument: {other}"),
        }
    }
    if !scene_set {
        anyhow::bail!("--scene <scene.json> is required");
    }
    Ok(args)
}

fn main() -> Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "info".into()),
        )
        .init();

    let args = parse_args()?;
    let text = fs::read_to_string(&args.scene)
        .with_context(|| format!("reading {}", args.scene.display()))?;
    // Flat StructuralElement array or a QBD building file (walls_batch/…) —
    // the loader handles both (QBD is the QBD generator's native output).
    let elements: Vec<StructuralElement> =
        archengine_geometry::qbd::elements_from_json(&text).context("parsing scene JSON")?;

    if args.no_validation {
        // Validation default is tied to debug builds; this flag exists for
        // parity with archrender but release-profile runs already skip it.
        tracing::info!("--no-validation noted (validation follows debug_assertions)");
    }

    archengine_viewer::app::run_viewer(&elements, args.env)
}
