//! `archrender` — headless path-traced renderer (the demo money shot).
//!
//! Reads a scene JSON (an array of `StructuralElement`, as produced by
//! `qbd_solve`), builds the BVH via `archengine_geometry::bvh`, and renders
//! a progressive Monte Carlo path-traced image with the compute shader
//! ported verbatim from the C++ kernel.
//!
//! ```sh
//! archrender --scene building.json --out render.png \
//!     --width 1920 --height 1080 --spp 64 \
//!     --camera "0,5,20:0,2,0" --exposure 1.0 \
//!     --env sky.hdr --env-intensity 1.0
//! ```

use std::path::PathBuf;
use std::process::ExitCode;

use anyhow::{Context as _, Result, bail};
use glam::Vec3;

use archengine_geometry::bvh::MaterialTable;
use archengine_geometry::domain::StructuralElement;
use archengine_viewer::camera::Camera;
use archengine_viewer::vulkan::{PathTracer, PathTracerConfig, VulkanConfig, VulkanContext};

fn parse_camera(s: &str) -> Result<(Vec3, Vec3)> {
    let (pos, target) = s
        .split_once(':')
        .context("camera format: px,py,pz:tx,ty,tz")?;
    let parse_vec = |v: &str| -> Result<Vec3> {
        let parts: Vec<f32> = v
            .split(',')
            .map(|x| x.trim().parse::<f32>())
            .collect::<std::result::Result<_, _>>()?;
        if parts.len() != 3 {
            bail!("expected 3 components, got {}", parts.len());
        }
        Ok(Vec3::new(parts[0], parts[1], parts[2]))
    };
    Ok((parse_vec(pos)?, parse_vec(target)?))
}

fn main() -> ExitCode {
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("archrender: {e:#}");
            ExitCode::FAILURE
        }
    }
}

fn run() -> Result<()> {
    let mut scene_path: Option<PathBuf> = None;
    let mut out_path = PathBuf::from("render.png");
    let mut hdr_path: Option<PathBuf> = None;
    let mut env_path: Option<PathBuf> = None;
    let mut env_intensity: f32 = 1.0;
    let mut materials_dir = PathBuf::from("materials");
    let mut config = PathTracerConfig {
        // Friendlier default for interactive demo runs; the library default
        // stays at the C++ value (64 spp).
        samples_per_pixel: 32,
        ..Default::default()
    };
    let mut camera = Camera::default();
    let mut validation = cfg!(debug_assertions);

    let args: Vec<String> = std::env::args().collect();
    let mut i = 1;
    while i < args.len() {
        let next = |i: &mut usize| -> Result<String> {
            *i += 1;
            args.get(*i).cloned().context("missing value")
        };
        match args[i].as_str() {
            "--scene" => scene_path = Some(PathBuf::from(next(&mut i)?)),
            "--out" => out_path = PathBuf::from(next(&mut i)?),
            "--hdr" => hdr_path = Some(PathBuf::from(next(&mut i)?)),
            "--env" => env_path = Some(PathBuf::from(next(&mut i)?)),
            "--env-intensity" => env_intensity = next(&mut i)?.parse()?,
            "--materials" => materials_dir = PathBuf::from(next(&mut i)?),
            "--width" => config.width = next(&mut i)?.parse()?,
            "--height" => config.height = next(&mut i)?.parse()?,
            "--spp" => config.samples_per_pixel = next(&mut i)?.parse()?,
            "--bounces" => config.max_bounces = next(&mut i)?.parse()?,
            "--exposure" => config.exposure = next(&mut i)?.parse()?,
            "--tonemap" => config.tonemap_mode = next(&mut i)?.parse()?,
            "--camera" => {
                let (pos, target) = parse_camera(&next(&mut i)?)?;
                camera.position = pos;
                camera.target = target;
            }
            "--fov" => camera.fov = next(&mut i)?.parse()?,
            "--no-validation" => validation = false,
            other => bail!("unknown argument: {other}"),
        }
        i += 1;
    }

    let scene_path = scene_path.context("--scene <building.json> is required")?;
    let scene_json = std::fs::read_to_string(&scene_path)
        .with_context(|| format!("reading {}", scene_path.display()))?;
    let elements: Vec<StructuralElement> = serde_json::from_str(&scene_json)
        .with_context(|| format!("parsing {}", scene_path.display()))?;
    println!("archrender: {} elements", elements.len());

    let materials = MaterialTable::load(&materials_dir);

    let ctx = VulkanContext::new_headless(VulkanConfig {
        enable_validation: validation,
        ..Default::default()
    })?;
    let mut tracer = PathTracer::new(&ctx);
    tracer.set_config(config);

    // Optional HDRI environment (equirectangular .hdr) — also runs the IBL
    // compute chain to validate it end-to-end.
    if let Some(env_path) = env_path {
        let t_ibl = std::time::Instant::now();
        let mut env = archengine_viewer::vulkan::EnvironmentMap::new(&ctx)?;
        env.load_from_file(&env_path)?;
        env.generate_ibl_textures(&archengine_viewer::vulkan::IblConfig::default())?;
        println!("archrender: env map + IBL in {:.1?}", t_ibl.elapsed());
        tracer.set_environment_map(env, env_intensity, 0.0)?;
    }

    if !tracer.set_scene(&elements, None, &materials)? {
        bail!("scene produced no geometry");
    }
    tracer.set_camera(camera);

    let t0 = std::time::Instant::now();
    let mut last_pct = -1i32;
    tracer.set_progress_callback(move |p| {
        let pct = (p * 100.0) as i32;
        if pct / 10 != last_pct / 10 {
            last_pct = pct;
            println!("  {pct}%");
        }
    });

    tracer.start_render()?;
    tracer.render_to_completion()?;
    println!("archrender: rendered in {:.1?}", t0.elapsed());

    tracer.save_png(&out_path, tracer.config().exposure)?;
    if let Some(hdr) = hdr_path {
        tracer.save_hdr(&hdr)?;
    }
    println!("archrender: wrote {}", out_path.display());
    Ok(())
}
