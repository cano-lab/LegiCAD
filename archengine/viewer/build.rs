//! Compiles the GLSL shaders (copied verbatim from
//! `legacy/archengine/ArchEngine_kernel/shaders/`) to SPIR-V at build time.
//!
//! Output lands in `OUT_DIR/spirv/<name>.spv`; crate code embeds them with
//! `include_bytes!(concat!(env!("OUT_DIR"), "/spirv/<name>.spv"))`.

use std::path::{Path, PathBuf};

fn shader_kind(path: &Path) -> Option<shaderc::ShaderKind> {
    Some(match path.extension()?.to_str()? {
        "vert" => shaderc::ShaderKind::Vertex,
        "frag" => shaderc::ShaderKind::Fragment,
        "comp" => shaderc::ShaderKind::Compute,
        "tesc" => shaderc::ShaderKind::TessControl,
        "tese" => shaderc::ShaderKind::TessEvaluation,
        "rgen" => shaderc::ShaderKind::RayGeneration,
        "rchit" => shaderc::ShaderKind::ClosestHit,
        "rmiss" => shaderc::ShaderKind::Miss,
        _ => return None,
    })
}

fn main() -> anyhow::Result<()> {
    let shader_dir = PathBuf::from(std::env::var("CARGO_MANIFEST_DIR")?).join("shaders");
    let out_dir = PathBuf::from(std::env::var("OUT_DIR")?).join("spirv");
    std::fs::create_dir_all(&out_dir)?;

    println!("cargo:rerun-if-changed={}", shader_dir.display());

    let compiler = shaderc::Compiler::new().expect("shaderc compiler");
    let mut options = shaderc::CompileOptions::new().expect("shaderc options");
    options.set_target_env(
        shaderc::TargetEnv::Vulkan,
        shaderc::EnvVersion::Vulkan1_2 as u32,
    );
    options.set_optimization_level(shaderc::OptimizationLevel::Performance);
    // Shaders use `#include "include/ubo.glsl"` relative to shaders/.
    let include_root = shader_dir.clone();
    options.set_include_callback(move |name, _kind, _source, _depth| {
        let path = include_root.join(name);
        std::fs::read_to_string(&path)
            .map(|content| shaderc::ResolvedInclude {
                resolved_name: path.to_string_lossy().into_owned(),
                content,
            })
            .map_err(|e| format!("include {name}: {e}"))
    });

    let mut entries: Vec<PathBuf> = std::fs::read_dir(&shader_dir)?
        .filter_map(|e| e.ok().map(|e| e.path()))
        .filter(|p| shader_kind(p).is_some())
        .collect();
    entries.sort();

    for path in entries {
        let name = path.file_name().unwrap().to_string_lossy().into_owned();
        let source = std::fs::read_to_string(&path)?;
        let kind = shader_kind(&path).unwrap();
        let spv = compiler
            .compile_into_spirv(&source, kind, &name, "main", Some(&options))
            .map_err(|e| anyhow::anyhow!("{name}: {e}"))?;
        std::fs::write(out_dir.join(format!("{name}.spv")), spv.as_binary_u8())?;
    }
    Ok(())
}
