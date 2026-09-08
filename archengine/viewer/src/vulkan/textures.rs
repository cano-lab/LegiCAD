//! Polyhaven material texture array — port of `PathTracer::loadMaterialTextures`
//! / `updateMaterialTextureIndices` / `getTextureIndex` (path_tracer.cpp:962+).
//!
//! Loads every `polyhaven/*` material referenced by `material_map.json` (plus
//! any extra folders under `polyhaven/`), packs 4 maps per material
//! (albedo, normal, roughness, AO — in that layer order, as
//! `path_trace.comp`'s `texIndex + 0..3` expects) into an R8G8B8A8_UNORM 2D
//! texture array at one shared resolution (max found, capped at 2048).

use std::collections::HashMap;
use std::path::{Path, PathBuf};

use anyhow::{Context as _, Result};
use ash::vk;
use glam::Vec4;

use archengine_geometry::domain::{ElementType, StructuralElement};

use super::context::VulkanContext;

/// Layers per material: albedo, normal, roughness, AO.
pub const LAYERS_PER_MATERIAL: u32 = 4;

/// One packed GPU texture array + the material-name → base-layer map.
pub struct TextureArray {
    image: vk::Image,
    memory: vk::DeviceMemory,
    view: vk::ImageView,
    sampler: vk::Sampler,
    /// Shared square resolution (max found, capped at 2048).
    pub resolution: u32,
    pub layer_count: u32,
    /// Material name → base layer index (i * LAYERS_PER_MATERIAL).
    indices: HashMap<String, i32>,
    /// Names in load order (C++ `m_loadedMaterials`).
    pub loaded_materials: Vec<String>,
}

/// One material's four texture paths (C++ `TextureToLoad`).
#[derive(Debug)]
struct TextureToLoad {
    material_name: String,
    albedo_path: PathBuf,
    normal_path: PathBuf,
    roughness_path: PathBuf,
    ao_path: PathBuf,
}

/// CPU-side RGBA8 image (C++ `LoadedTexture`).
struct LoadedTexture {
    data: Vec<u8>,
    width: u32,
    height: u32,
}

impl TextureArray {
    /// C++ `loadMaterialTextures`. Returns `Ok(None)` when no
    /// `material_map.json` or no Polyhaven textures are found (the C++
    /// returns `false`/`true` respectively — both mean "keep the
    /// placeholder binding").
    pub fn load(ctx: &VulkanContext, materials_dir: &Path) -> Result<Option<Self>> {
        // Find material_map.json (C++ search path list).
        let candidates = [
            materials_dir.join("material_map.json"),
            PathBuf::from("materials/material_map.json"),
            PathBuf::from("../materials/material_map.json"),
            PathBuf::from("../../materials/material_map.json"),
            PathBuf::from("../../../ArchEngine_kernel/materials/material_map.json"),
        ];
        let map_path = candidates.iter().find(|p| p.exists());
        let Some(map_path) = map_path else {
            tracing::warn!("[PathTracer] could not find material_map.json in any search path");
            return Ok(None);
        };
        let base_path = map_path
            .parent()
            .map(Path::to_path_buf)
            .unwrap_or_else(|| PathBuf::from("."));
        tracing::info!(path = %map_path.display(), "[PathTracer] found material_map.json");

        let text = std::fs::read_to_string(map_path).context("reading material_map.json")?;
        let map: serde_json::Value =
            serde_json::from_str(&text).context("parsing material_map.json")?;

        // Collect polyhaven materials referenced by the map.
        let mut to_load: Vec<TextureToLoad> = Vec::new();
        if let Some(materials) = map.get("materials").and_then(|v| v.as_object()) {
            for (key, value) in materials {
                if !key.starts_with("polyhaven/") {
                    continue;
                }
                let Some(folder) = value.get("folder").and_then(|f| f.as_str()) else {
                    continue;
                };
                let folder = base_path.join(folder);
                if !folder.exists() {
                    continue;
                }
                let textures = value.get("textures").cloned().unwrap_or_default();
                let name = |k: &str, default: &str| {
                    textures
                        .get(k)
                        .and_then(|v| v.as_str())
                        .unwrap_or(default)
                        .to_string()
                };
                let tex = TextureToLoad {
                    material_name: key.clone(),
                    albedo_path: folder.join(name("albedo", "albedo.jpg")),
                    normal_path: folder.join(name("normal", "normal.jpg")),
                    roughness_path: folder.join(name("roughness", "roughness.jpg")),
                    ao_path: folder.join(name("ao", "ao.jpg")),
                };
                if tex.albedo_path.exists() {
                    to_load.push(tex);
                }
            }
        }

        // Scan the polyhaven folder for materials not in the map.
        let polyhaven_dir = base_path.join("polyhaven");
        if polyhaven_dir.is_dir() {
            let mut existing: std::collections::HashSet<String> = to_load
                .iter()
                .map(|t| t.material_name.clone())
                .collect();
            for entry in std::fs::read_dir(&polyhaven_dir)?.flatten() {
                let path = entry.path();
                if !path.is_dir() {
                    continue;
                }
                let mat_name = format!("polyhaven/{}", entry.file_name().to_string_lossy());
                if !existing.insert(mat_name.clone()) {
                    continue;
                }
                let mut albedo_path = None;
                for ext in [".jpg", ".png", ".jpeg"] {
                    let candidate = path.join(format!("albedo{ext}"));
                    if candidate.exists() {
                        albedo_path = Some(candidate);
                        break;
                    }
                }
                let Some(albedo_path) = albedo_path else {
                    continue;
                };
                let ext = albedo_path
                    .extension()
                    .map(|e| format!(".{}", e.to_string_lossy()))
                    .unwrap_or_else(|| ".jpg".into());
                let with_fallback = |name: &str| {
                    let primary = path.join(format!("{name}{ext}"));
                    if primary.exists() {
                        primary
                    } else {
                        path.join(format!("{name}.jpg"))
                    }
                };
                to_load.push(TextureToLoad {
                    material_name: mat_name.clone(),
                    albedo_path,
                    normal_path: with_fallback("normal"),
                    roughness_path: with_fallback("roughness"),
                    ao_path: with_fallback("ao"),
                });
                tracing::info!(material = %mat_name, "[PathTracer] found additional material");
            }
        }

        if to_load.is_empty() {
            tracing::info!("[PathTracer] no Poly Haven textures found to load");
            return Ok(None);
        }
        let total_layers = to_load.len() as u32 * LAYERS_PER_MATERIAL;
        tracing::info!(
            materials = to_load.len(),
            layers = total_layers,
            "[PathTracer] loading Poly Haven materials"
        );

        // Load every map to CPU memory (missing → default tile, verbatim).
        let mut loaded: Vec<LoadedTexture> = Vec::with_capacity(total_layers as usize);
        let mut max_width = 0u32;
        let mut max_height = 0u32;
        for tex in &to_load {
            for (j, path) in [
                &tex.albedo_path,
                &tex.normal_path,
                &tex.roughness_path,
                &tex.ao_path,
            ]
            .iter()
            .enumerate()
            {
                let decoded = image::ImageReader::open(path)
                    .ok()
                    .and_then(|r| r.decode().ok());
                match decoded {
                    Some(img) => {
                        let rgba = img.to_rgba8();
                        let (w, h) = rgba.dimensions();
                        max_width = max_width.max(w);
                        max_height = max_height.max(h);
                        loaded.push(LoadedTexture {
                            data: rgba.into_raw(),
                            width: w,
                            height: h,
                        });
                    }
                    None => {
                        // Default 64×64 tile — values verbatim from the C++.
                        let default_val: u8 = match j {
                            0 => 128,
                            1 => 127,
                            2 => 128,
                            _ => 255,
                        };
                        let mut data = vec![0u8; 64 * 64 * 4];
                        for p in 0..64 * 64usize {
                            data[p * 4] = default_val;
                            data[p * 4 + 1] = if j == 1 { 127 } else { default_val };
                            data[p * 4 + 2] = if j == 1 { 255 } else { default_val };
                            data[p * 4 + 3] = 255;
                        }
                        loaded.push(LoadedTexture {
                            data,
                            width: 64,
                            height: 64,
                        });
                    }
                }
            }
        }

        let resolution = max_width.max(max_height).min(2048);
        let array = Self::upload(ctx, &loaded, resolution, total_layers)?;

        let mut indices = HashMap::new();
        let mut loaded_materials = Vec::new();
        for (i, tex) in to_load.iter().enumerate() {
            indices.insert(tex.material_name.clone(), (i as u32 * LAYERS_PER_MATERIAL) as i32);
            loaded_materials.push(tex.material_name.clone());
        }
        tracing::info!(
            resolution,
            "[PathTracer] materials loaded into texture array"
        );
        Ok(Some(Self {
            indices,
            loaded_materials,
            ..array
        }))
    }

    /// GPU upload: create the array image, stage-copy each layer (nearest
    /// resize, verbatim), transition to shader-read (compute stage), create
    /// the 2D-array view + REPEAT sampler.
    fn upload(
        ctx: &VulkanContext,
        loaded: &[LoadedTexture],
        resolution: u32,
        layer_count: u32,
    ) -> Result<Self> {
        let device = ctx.device();
        let layer_size = (resolution * resolution * 4) as vk::DeviceSize;

        let info = vk::ImageCreateInfo::default()
            .image_type(vk::ImageType::TYPE_2D)
            .format(vk::Format::R8G8B8A8_UNORM)
            .extent(vk::Extent3D { width: resolution, height: resolution, depth: 1 })
            .mip_levels(1)
            .array_layers(layer_count)
            .samples(vk::SampleCountFlags::TYPE_1)
            .tiling(vk::ImageTiling::OPTIMAL)
            .usage(vk::ImageUsageFlags::SAMPLED | vk::ImageUsageFlags::TRANSFER_DST)
            .sharing_mode(vk::SharingMode::EXCLUSIVE)
            .initial_layout(vk::ImageLayout::UNDEFINED);
        let image = unsafe { device.create_image(&info, None) }
            .context("texture array image")?;
        let requirements = unsafe { device.get_image_memory_requirements(image) };
        let alloc = vk::MemoryAllocateInfo::default()
            .allocation_size(requirements.size)
            .memory_type_index(ctx.find_memory_type(
                requirements.memory_type_bits,
                vk::MemoryPropertyFlags::DEVICE_LOCAL,
            )?);
        let memory = unsafe { device.allocate_memory(&alloc, None) }
            .context("texture array memory")?;
        unsafe { device.bind_image_memory(image, memory, 0) }?;

        let (staging, staging_mem) = ctx.create_buffer(
            layer_size,
            vk::BufferUsageFlags::TRANSFER_SRC,
            vk::MemoryPropertyFlags::HOST_VISIBLE | vk::MemoryPropertyFlags::HOST_COHERENT,
        )?;

        // UNDEFINED → TRANSFER_DST for all layers.
        let cmd = ctx.begin_single_time_commands()?;
        let range = vk::ImageSubresourceRange {
            aspect_mask: vk::ImageAspectFlags::COLOR,
            base_mip_level: 0,
            level_count: 1,
            base_array_layer: 0,
            layer_count,
        };
        let barrier = vk::ImageMemoryBarrier::default()
            .old_layout(vk::ImageLayout::UNDEFINED)
            .new_layout(vk::ImageLayout::TRANSFER_DST_OPTIMAL)
            .src_queue_family_index(vk::QUEUE_FAMILY_IGNORED)
            .dst_queue_family_index(vk::QUEUE_FAMILY_IGNORED)
            .image(image)
            .subresource_range(range)
            .src_access_mask(vk::AccessFlags::empty())
            .dst_access_mask(vk::AccessFlags::TRANSFER_WRITE);
        unsafe {
            device.cmd_pipeline_barrier(
                cmd,
                vk::PipelineStageFlags::TOP_OF_PIPE,
                vk::PipelineStageFlags::TRANSFER,
                vk::DependencyFlags::empty(),
                &[],
                &[],
                &[barrier],
            );
        }
        ctx.end_single_time_commands(cmd)?;

        // Upload each layer (nearest-neighbor resize to the shared
        // resolution, verbatim from the C++).
        for (layer, tex) in loaded.iter().enumerate() {
            let mut resized;
            let pixels: &[u8] = if tex.width == resolution && tex.height == resolution {
                &tex.data
            } else {
                resized = vec![0u8; layer_size as usize];
                for y in 0..resolution {
                    for x in 0..resolution {
                        let src_x = (x * tex.width / resolution) as usize;
                        let src_y = (y * tex.height / resolution) as usize;
                        let src = (src_y * tex.width as usize + src_x) * 4;
                        let dst = ((y * resolution + x) * 4) as usize;
                        resized[dst..dst + 4].copy_from_slice(&tex.data[src..src + 4]);
                    }
                }
                &resized
            };

            unsafe {
                let mapped =
                    device.map_memory(staging_mem, 0, layer_size, vk::MemoryMapFlags::empty())?;
                std::ptr::copy_nonoverlapping(
                    pixels.as_ptr(),
                    mapped.cast::<u8>(),
                    layer_size as usize,
                );
                device.unmap_memory(staging_mem);
            }

            let region = [vk::BufferImageCopy {
                buffer_offset: 0,
                buffer_row_length: 0,
                buffer_image_height: 0,
                image_subresource: vk::ImageSubresourceLayers {
                    aspect_mask: vk::ImageAspectFlags::COLOR,
                    mip_level: 0,
                    base_array_layer: layer as u32,
                    layer_count: 1,
                },
                image_offset: vk::Offset3D { x: 0, y: 0, z: 0 },
                image_extent: vk::Extent3D { width: resolution, height: resolution, depth: 1 },
            }];
            let cmd = ctx.begin_single_time_commands()?;
            unsafe {
                device.cmd_copy_buffer_to_image(
                    cmd,
                    staging,
                    image,
                    vk::ImageLayout::TRANSFER_DST_OPTIMAL,
                    &region,
                );
            }
            ctx.end_single_time_commands(cmd)?;
        }

        unsafe {
            device.destroy_buffer(staging, None);
            device.free_memory(staging_mem, None);
        }

        // TRANSFER_DST → SHADER_READ (compute stage, as the C++).
        let cmd = ctx.begin_single_time_commands()?;
        let barrier = vk::ImageMemoryBarrier::default()
            .old_layout(vk::ImageLayout::TRANSFER_DST_OPTIMAL)
            .new_layout(vk::ImageLayout::SHADER_READ_ONLY_OPTIMAL)
            .src_queue_family_index(vk::QUEUE_FAMILY_IGNORED)
            .dst_queue_family_index(vk::QUEUE_FAMILY_IGNORED)
            .image(image)
            .subresource_range(range)
            .src_access_mask(vk::AccessFlags::TRANSFER_WRITE)
            .dst_access_mask(vk::AccessFlags::SHADER_READ);
        unsafe {
            device.cmd_pipeline_barrier(
                cmd,
                vk::PipelineStageFlags::TRANSFER,
                vk::PipelineStageFlags::COMPUTE_SHADER,
                vk::DependencyFlags::empty(),
                &[],
                &[],
                &[barrier],
            );
        }
        ctx.end_single_time_commands(cmd)?;

        let view_info = vk::ImageViewCreateInfo::default()
            .image(image)
            .view_type(vk::ImageViewType::TYPE_2D_ARRAY)
            .format(vk::Format::R8G8B8A8_UNORM)
            .subresource_range(range);
        let view = unsafe { device.create_image_view(&view_info, None) }
            .context("texture array view")?;

        let sampler_info = vk::SamplerCreateInfo::default()
            .mag_filter(vk::Filter::LINEAR)
            .min_filter(vk::Filter::LINEAR)
            .mipmap_mode(vk::SamplerMipmapMode::LINEAR)
            .address_mode_u(vk::SamplerAddressMode::REPEAT)
            .address_mode_v(vk::SamplerAddressMode::REPEAT)
            .address_mode_w(vk::SamplerAddressMode::REPEAT)
            .anisotropy_enable(ctx.supports_sampler_anisotropy())
            .max_anisotropy(if ctx.supports_sampler_anisotropy() {
                8.0f32.min(ctx.max_sampler_anisotropy())
            } else {
                1.0
            })
            .border_color(vk::BorderColor::FLOAT_OPAQUE_WHITE);
        let sampler = unsafe { device.create_sampler(&sampler_info, None) }
            .context("texture array sampler")?;

        Ok(Self {
            image,
            memory,
            view,
            sampler,
            resolution,
            layer_count,
            indices: HashMap::new(),
            loaded_materials: Vec::new(),
        })
    }

    /// C++ `getTextureIndex` — base layer for a material name, -1 if none.
    pub fn get_texture_index(&self, material_name: &str) -> i32 {
        self.indices.get(material_name).copied().unwrap_or(-1)
    }

    pub fn descriptor_info(&self) -> vk::DescriptorImageInfo {
        vk::DescriptorImageInfo::default()
            .sampler(self.sampler)
            .image_view(self.view)
            .image_layout(vk::ImageLayout::SHADER_READ_ONLY_OPTIMAL)
    }

    pub fn destroy(self, ctx: &VulkanContext) {
        let device = ctx.device();
        unsafe {
            device.destroy_sampler(self.sampler, None);
            device.destroy_image_view(self.view, None);
            device.destroy_image(self.image, None);
            device.free_memory(self.memory, None);
        }
    }
}

/// C++ `resolveMaterialName` (path_tracer.cpp:1372+) — keyword-based
/// mapping from an element's material string to a `polyhaven/*` name.
pub fn resolve_material_name(elem: &StructuralElement) -> String {
    let mat_name = &elem.material;
    if !mat_name.is_empty() && mat_name != "default" {
        if mat_name.starts_with("polyhaven/") {
            return mat_name.clone();
        }
        let lower = mat_name.to_lowercase();
        let has = |needle: &str| lower.contains(needle);
        if has("brick") {
            return "polyhaven/brick_wall_006".into();
        }
        if has("concrete") || has("cement") || has("stone") {
            return "polyhaven/concrete_wall_008".into();
        }
        if has("drywall")
            || has("plaster")
            || has("gypsum")
            || has("paint")
            || has("stucco")
            || has("interior")
            || has("tyvek")
            || has("membrane")
            || has("poly")
            || has("vapor")
        {
            return "polyhaven/concrete_wall_008".into();
        }
        if has("tile") || has("ceramic") {
            return "polyhaven/concrete_floor_003".into();
        }
        if has("wood") || has("timber") || has("osb") || has("plywood") {
            return "polyhaven/wood_floor_deck".into();
        }
        if has("vinyl") || has("siding") {
            return "polyhaven/concrete_wall_008".into();
        }
        if has("glass") || has("glazing") || has("window") {
            return "glass".into();
        }
        if has("metal") || has("steel") || has("aluminum") {
            return "polyhaven/metal_plate_02".into();
        }
        if has("shingle") || has("asphalt") || has("roof") || has("slate") {
            return "polyhaven/roof_slates_02".into();
        }
        if has("grass") || has("lawn") {
            return "polyhaven/grass_path_2".into();
        }
        if has("gravel") || has("patio") {
            return "polyhaven/gravel_concrete".into();
        }
        if has("door") {
            return "polyhaven/wood_floor_deck".into();
        }
        if lower == "wall" || lower == "partition" {
            return "polyhaven/concrete_wall_008".into();
        }
    }

    // Default based on element type.
    match elem.element_type {
        ElementType::Wall => "polyhaven/brick_wall_006".into(),
        ElementType::Floor => "polyhaven/concrete_floor_003".into(),
        ElementType::Roof => "polyhaven/roof_slates_02".into(),
        ElementType::Door | ElementType::Beam | ElementType::Column => {
            "polyhaven/wood_floor_deck".into()
        }
        ElementType::Window => "glass".into(),
        _ => "polyhaven/concrete_wall_008".into(),
    }
}

/// C++ `getPolyHavenColor` — approximate Poly Haven albedo colors.
pub fn polyhaven_color(mat_name: &str) -> Vec4 {
    if mat_name.contains("glass") {
        Vec4::new(0.95, 0.97, 1.0, 0.15) // clear glass, low alpha
    } else if mat_name.contains("brick") {
        Vec4::new(0.45, 0.28, 0.22, 1.0)
    } else if mat_name.contains("concrete") {
        Vec4::new(0.5, 0.48, 0.45, 1.0)
    } else if mat_name.contains("wood") {
        Vec4::new(0.4, 0.28, 0.18, 1.0)
    } else if mat_name.contains("roof") {
        Vec4::new(0.25, 0.24, 0.23, 1.0)
    } else if mat_name.contains("asphalt") {
        Vec4::new(0.15, 0.15, 0.15, 1.0)
    } else if mat_name.contains("grass") {
        Vec4::new(0.25, 0.35, 0.15, 1.0)
    } else if mat_name.contains("gravel") {
        Vec4::new(0.45, 0.42, 0.4, 1.0)
    } else if mat_name.contains("metal") {
        Vec4::new(0.55, 0.55, 0.55, 1.0)
    } else {
        Vec4::new(0.5, 0.5, 0.5, 1.0)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use archengine_geometry::domain::StructuralElement;

    fn elem(material: &str, ty: ElementType) -> StructuralElement {
        StructuralElement {
            material: material.to_string(),
            element_type: ty,
            ..Default::default()
        }
    }

    #[test]
    fn resolve_keyword_mapping() {
        assert_eq!(
            resolve_material_name(&elem("red brick veneer", ElementType::Wall)),
            "polyhaven/brick_wall_006"
        );
        assert_eq!(
            resolve_material_name(&elem("CONCRETE", ElementType::Wall)),
            "polyhaven/concrete_wall_008"
        );
        assert_eq!(
            resolve_material_name(&elem("polyhaven/custom_thing", ElementType::Floor)),
            "polyhaven/custom_thing"
        );
        assert_eq!(
            resolve_material_name(&elem("double glazing", ElementType::Window)),
            "glass"
        );
    }

    #[test]
    fn resolve_element_type_fallback() {
        assert_eq!(
            resolve_material_name(&elem("", ElementType::Roof)),
            "polyhaven/roof_slates_02"
        );
        assert_eq!(
            resolve_material_name(&elem("default", ElementType::Window)),
            "glass"
        );
        assert_eq!(
            resolve_material_name(&elem("", ElementType::Beam)),
            "polyhaven/wood_floor_deck"
        );
    }

    #[test]
    fn polyhaven_colors() {
        assert_eq!(polyhaven_color("glass"), Vec4::new(0.95, 0.97, 1.0, 0.15));
        assert_eq!(polyhaven_color("polyhaven/brick_wall_006").w, 1.0);
    }
}
