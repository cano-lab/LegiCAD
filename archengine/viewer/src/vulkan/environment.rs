//! Environment map + IBL — port of `environment_map.hpp/.cpp` (1,454 LOC).
//!
//! Loads an equirectangular HDR (or builds the C++ procedural sky), converts
//! it to an R16G16B16A16_SFLOAT cubemap on the GPU, and generates the IBL
//! set (irradiance cubemap, prefiltered GGX mip chain, BRDF LUT) with the
//! verbatim `brdf_lut.comp` / `irradiance_convolve.comp` /
//! `prefilter_envmap.comp` compute shaders.
//!
//! Deliberate divergence from the C++: the C++ transitions the IBL images to
//! SHADER_READ_ONLY at creation and then re-transitions them from UNDEFINED
//! in the compute runs (stale layout bookkeeping — tolerated by most desktop
//! drivers, flagged by strict ones). This port leaves IBL images UNDEFINED
//! until their compute pass, which performs UNDEFINED → GENERAL →
//! SHADER_READ_ONLY per image/mip. Contents are discarded either way.

use std::path::Path;

use anyhow::{Context as _, Result, bail};
use ash::vk;
use ash::vk::Handle; // `.is_null()` on handle types
use glam::Vec3;

use super::context::VulkanContext;

const BRDF_LUT_SPV: &[u8] =
    include_bytes!(concat!(env!("OUT_DIR"), "/spirv/brdf_lut.comp.spv"));
const IRRADIANCE_SPV: &[u8] =
    include_bytes!(concat!(env!("OUT_DIR"), "/spirv/irradiance_convolve.comp.spv"));
const PREFILTER_SPV: &[u8] =
    include_bytes!(concat!(env!("OUT_DIR"), "/spirv/prefilter_envmap.comp.spv"));

const HDR_FORMAT: vk::Format = vk::Format::R16G16B16A16_SFLOAT;
const BRDF_FORMAT: vk::Format = vk::Format::R16G16_SFLOAT;

/// IBL configuration — defaults verbatim from C++ `IBLConfig`.
#[derive(Debug, Clone, Copy)]
pub struct IblConfig {
    /// Size of irradiance cubemap faces.
    pub irradiance_size: u32,
    /// Size of prefiltered cubemap faces (mip 0).
    pub prefiltered_size: u32,
    /// Number of mip levels for roughness.
    pub prefiltered_mip_levels: u32,
    /// Size of the BRDF LUT texture.
    pub brdf_lut_size: u32,
    /// Monte Carlo samples for convolution.
    pub sample_count: u32,
}

impl Default for IblConfig {
    fn default() -> Self {
        Self {
            irradiance_size: 64,
            prefiltered_size: 256,
            prefiltered_mip_levels: 6,
            brdf_lut_size: 512,
            sample_count: 1024,
        }
    }
}

/// float32 → float16 bit conversion, verbatim from the C++ lambda.
fn float_to_half(f: f32) -> u16 {
    let x = f.to_bits();
    let sign = (x >> 16) & 0x8000;
    let exp = (((x >> 23) & 0xFF) as i32) - 127 + 15;
    let mant = x & 0x007F_FFFF;
    if exp <= 0 {
        sign as u16
    } else if exp >= 31 {
        (sign | 0x7C00) as u16
    } else {
        (sign | ((exp as u32) << 10) | (mant >> 13)) as u16
    }
}

/// Standard cubemap face directions — verbatim from
/// `EnvironmentMap::getCubemapDirection`.
pub fn cubemap_direction(face: u32, u: f32, v: f32) -> Vec3 {
    match face {
        0 => Vec3::new(1.0, -v, -u),  // +X
        1 => Vec3::new(-1.0, -v, u),  // -X
        2 => Vec3::new(u, 1.0, v),    // +Y
        3 => Vec3::new(u, -1.0, -v),  // -Y
        4 => Vec3::new(u, -v, 1.0),   // +Z
        5 => Vec3::new(-u, -v, -1.0), // -Z
        _ => Vec3::Y,
    }
}

/// One GPU image + backing memory owned by this map.
struct GpuImage {
    image: vk::Image,
    memory: vk::DeviceMemory,
    view: vk::ImageView,
}

/// Environment map (cubemap + optional IBL textures). Holds a raw pointer
/// to the [`VulkanContext`], mirroring the C++ `EnvironmentMap(VulkanContext&)`.
///
/// # Safety invariants (upheld by the caller)
/// - the context must outlive the map (drop the map first), and must not
///   be moved (store it in a `Box`),
/// - all methods take `&self`/`&mut self`; calls are single-threaded.
pub struct EnvironmentMap {
    ctx: *const VulkanContext,

    cubemap: Option<GpuImage>,
    sampler: vk::Sampler,
    cubemap_size: u32,
    loaded: bool,

    irradiance: Option<GpuImage>,
    prefiltered: Option<GpuImage>,
    brdf_lut: Option<GpuImage>,
    ibl_sampler: vk::Sampler,
    prefiltered_mip_levels: u32,
    ibl_generated: bool,

    // Compute pipelines (lazily created, once).
    brdf_ds_layout: vk::DescriptorSetLayout,
    brdf_pipeline_layout: vk::PipelineLayout,
    brdf_pipeline: vk::Pipeline,
    irradiance_ds_layout: vk::DescriptorSetLayout,
    irradiance_pipeline_layout: vk::PipelineLayout,
    irradiance_pipeline: vk::Pipeline,
    prefilter_ds_layout: vk::DescriptorSetLayout,
    prefilter_pipeline_layout: vk::PipelineLayout,
    prefilter_pipeline: vk::Pipeline,
    compute_descriptor_pool: vk::DescriptorPool,
    compute_pipelines_created: bool,
}

impl EnvironmentMap {
    pub fn new(ctx: &VulkanContext) -> Result<Self> {
        let sampler = create_sampler(ctx, 1.0)?;
        Ok(Self {
            ctx: ctx as *const VulkanContext,
            cubemap: None,
            sampler,
            cubemap_size: 512,
            loaded: false,
            irradiance: None,
            prefiltered: None,
            brdf_lut: None,
            ibl_sampler: vk::Sampler::null(),
            prefiltered_mip_levels: 1,
            ibl_generated: false,
            brdf_ds_layout: vk::DescriptorSetLayout::null(),
            brdf_pipeline_layout: vk::PipelineLayout::null(),
            brdf_pipeline: vk::Pipeline::null(),
            irradiance_ds_layout: vk::DescriptorSetLayout::null(),
            irradiance_pipeline_layout: vk::PipelineLayout::null(),
            irradiance_pipeline: vk::Pipeline::null(),
            prefilter_ds_layout: vk::DescriptorSetLayout::null(),
            prefilter_pipeline_layout: vk::PipelineLayout::null(),
            prefilter_pipeline: vk::Pipeline::null(),
            compute_descriptor_pool: vk::DescriptorPool::null(),
            compute_pipelines_created: false,
        })
    }

    /// Shared access to the context. Valid per the invariants on
    /// [`EnvironmentMap`]; calls are single-threaded.
    fn ctx(&self) -> &VulkanContext {
        // SAFETY: caller guarantees the context outlives the map and is
        // not moved.
        unsafe { &*self.ctx }
    }

    pub fn is_loaded(&self) -> bool {
        self.loaded
    }
    pub fn has_ibl_textures(&self) -> bool {
        self.ibl_generated
    }
    pub fn cubemap_size(&self) -> u32 {
        self.cubemap_size
    }
    pub fn prefiltered_mip_levels(&self) -> u32 {
        self.prefiltered_mip_levels
    }
    pub fn cubemap_view(&self) -> vk::ImageView {
        self.cubemap.as_ref().map(|g| g.view).unwrap_or_default()
    }
    pub fn sampler(&self) -> vk::Sampler {
        self.sampler
    }
    pub fn irradiance_view(&self) -> vk::ImageView {
        self.irradiance.as_ref().map(|g| g.view).unwrap_or_default()
    }
    pub fn prefiltered_view(&self) -> vk::ImageView {
        self.prefiltered.as_ref().map(|g| g.view).unwrap_or_default()
    }
    pub fn brdf_lut_view(&self) -> vk::ImageView {
        self.brdf_lut.as_ref().map(|g| g.view).unwrap_or_default()
    }
    pub fn ibl_sampler(&self) -> vk::Sampler {
        self.ibl_sampler
    }

    /// `getDescriptorInfo` — cubemap for `path_trace.comp` binding 5 /
    /// `sky.frag`.
    pub fn descriptor_info(&self) -> vk::DescriptorImageInfo {
        vk::DescriptorImageInfo::default()
            .sampler(self.sampler)
            .image_view(self.cubemap_view())
            .image_layout(vk::ImageLayout::SHADER_READ_ONLY_OPTIMAL)
    }

    pub fn irradiance_descriptor_info(&self) -> vk::DescriptorImageInfo {
        vk::DescriptorImageInfo::default()
            .sampler(self.ibl_sampler)
            .image_view(self.irradiance_view())
            .image_layout(vk::ImageLayout::SHADER_READ_ONLY_OPTIMAL)
    }

    pub fn prefiltered_descriptor_info(&self) -> vk::DescriptorImageInfo {
        vk::DescriptorImageInfo::default()
            .sampler(self.ibl_sampler)
            .image_view(self.prefiltered_view())
            .image_layout(vk::ImageLayout::SHADER_READ_ONLY_OPTIMAL)
    }

    pub fn brdf_lut_descriptor_info(&self) -> vk::DescriptorImageInfo {
        vk::DescriptorImageInfo::default()
            .sampler(self.ibl_sampler)
            .image_view(self.brdf_lut_view())
            .image_layout(vk::ImageLayout::SHADER_READ_ONLY_OPTIMAL)
    }

    /// Load an HDR environment map from an equirectangular file
    /// (`stbi_loadf` in the C++; here the `image` crate's HDR decoder).
    pub fn load_from_file(&mut self, path: impl AsRef<Path>) -> Result<()> {
        let path = path.as_ref();
        let img = image::ImageReader::open(path)
            .with_context(|| format!("opening {}", path.display()))?
            .decode()
            .with_context(|| format!("decoding HDR {}", path.display()))?;
        let rgb = img.to_rgb32f();
        let (width, height) = rgb.dimensions();
        tracing::info!(width, height, "[EnvironmentMap] HDR loaded");
        self.create_cubemap_from_equirectangular(rgb.as_raw(), width as i32, height as i32)?;
        self.loaded = true;
        Ok(())
    }

    /// The C++ `createProceduralSky` — simple gradient sky + ground, no file.
    pub fn create_procedural_sky(&mut self) -> Result<()> {
        let size = self.cubemap_size;
        let mut pixels = vec![0u16; (size * size) as usize * 4 * 6];
        for face in 0..6u32 {
            let face_base = (face as usize) * (size * size) as usize * 4;
            for y in 0..size {
                for x in 0..size {
                    let u = (x as f32 + 0.5) / size as f32 * 2.0 - 1.0;
                    let v = (y as f32 + 0.5) / size as f32 * 2.0 - 1.0;
                    let dir = cubemap_direction(face, u, v).normalize();
                    let color = if dir.y > 0.0 {
                        let zenith = Vec3::new(0.4, 0.6, 0.9);
                        let horizon = Vec3::new(0.7, 0.8, 0.95);
                        horizon.lerp(zenith, dir.y.powf(0.8))
                    } else {
                        let ground = Vec3::new(0.35, 0.45, 0.3);
                        let ground_far = Vec3::new(0.4, 0.5, 0.45);
                        ground_far.lerp(ground, (-dir.y).powf(0.5))
                    };
                    let idx = face_base + ((y * size + x) as usize) * 4;
                    pixels[idx] = float_to_half(color.x);
                    pixels[idx + 1] = float_to_half(color.y);
                    pixels[idx + 2] = float_to_half(color.z);
                    pixels[idx + 3] = float_to_half(1.0);
                }
            }
        }
        self.upload_cubemap(&pixels, size)?;
        self.loaded = true;
        Ok(())
    }

    /// A 1×1 solid-color cubemap — used as a *valid placeholder* for
    /// descriptor bindings when no real environment is set (the C++ bound
    /// the accumulation image with a null sampler, which is invalid).
    pub fn create_solid(&mut self, rgb: [f32; 3]) -> Result<()> {
        let mut pixels = vec![0u16; 4 * 6];
        for face in 0..6usize {
            pixels[face * 4] = float_to_half(rgb[0]);
            pixels[face * 4 + 1] = float_to_half(rgb[1]);
            pixels[face * 4 + 2] = float_to_half(rgb[2]);
            pixels[face * 4 + 3] = float_to_half(1.0);
        }
        self.cubemap_size = 1;
        self.upload_cubemap(&pixels, 1)?;
        self.loaded = true;
        Ok(())
    }

    /// Equirectangular RGB32F → cubemap staging pixels (nearest sampling,
    /// as the C++), then upload.
    fn create_cubemap_from_equirectangular(
        &mut self,
        hdr: &[f32],
        width: i32,
        height: i32,
    ) -> Result<()> {
        let size = self.cubemap_size;
        let mut pixels = vec![0u16; (size * size) as usize * 4 * 6];
        for face in 0..6u32 {
            let face_base = (face as usize) * (size * size) as usize * 4;
            for y in 0..size {
                for x in 0..size {
                    let u = (x as f32 + 0.5) / size as f32 * 2.0 - 1.0;
                    let v = (y as f32 + 0.5) / size as f32 * 2.0 - 1.0;
                    let dir = cubemap_direction(face, u, v).normalize();

                    let phi = dir.z.atan2(dir.x);
                    let theta = dir.y.clamp(-1.0, 1.0).asin();
                    let eq_u = (phi + std::f32::consts::PI) / (2.0 * std::f32::consts::PI);
                    let eq_v = (theta + std::f32::consts::FRAC_PI_2) / std::f32::consts::PI;

                    let px = ((eq_u * width as f32) as i32).rem_euclid(width);
                    let py = (((1.0 - eq_v) * height as f32) as i32).clamp(0, height - 1);
                    let src = ((py * width + px) * 3) as usize;

                    let idx = face_base + ((y * size + x) as usize) * 4;
                    pixels[idx] = float_to_half(hdr[src]);
                    pixels[idx + 1] = float_to_half(hdr[src + 1]);
                    pixels[idx + 2] = float_to_half(hdr[src + 2]);
                    pixels[idx + 3] = float_to_half(1.0);
                }
            }
        }
        self.upload_cubemap(&pixels, size)
    }

    /// Shared tail: destroy old cubemap, create image, stage-copy the 6
    /// faces, transition, create the cube view.
    fn upload_cubemap(&mut self, half_pixels: &[u16], size: u32) -> Result<()> {
        let device = self.ctx().device().clone();
        self.ctx().wait_idle();
        if let Some(old) = self.cubemap.take() {
            destroy_gpu_image(&device, old);
        }

        let image = create_image(
            self.ctx(),
            size,
            size,
            HDR_FORMAT,
            1,
            6,
            vk::ImageUsageFlags::TRANSFER_DST | vk::ImageUsageFlags::SAMPLED,
            vk::ImageCreateFlags::CUBE_COMPATIBLE,
        )?;

        // Staging buffer for all 6 faces.
        let byte_len = (half_pixels.len() * 2) as vk::DeviceSize;
        let (staging, staging_mem) = self.ctx().create_buffer(
            byte_len,
            vk::BufferUsageFlags::TRANSFER_SRC,
            vk::MemoryPropertyFlags::HOST_VISIBLE | vk::MemoryPropertyFlags::HOST_COHERENT,
        )?;
        unsafe {
            let mapped =
                device.map_memory(staging_mem, 0, byte_len, vk::MemoryMapFlags::empty())?;
            std::ptr::copy_nonoverlapping(
                half_pixels.as_ptr().cast::<u8>(),
                mapped.cast::<u8>(),
                byte_len as usize,
            );
            device.unmap_memory(staging_mem);
        }

        let cmd = self.ctx().begin_single_time_commands()?;
        // UNDEFINED → TRANSFER_DST (all 6 layers).
        let barrier = vk::ImageMemoryBarrier::default()
            .old_layout(vk::ImageLayout::UNDEFINED)
            .new_layout(vk::ImageLayout::TRANSFER_DST_OPTIMAL)
            .src_queue_family_index(vk::QUEUE_FAMILY_IGNORED)
            .dst_queue_family_index(vk::QUEUE_FAMILY_IGNORED)
            .image(image.image)
            .subresource_range(cube_range(0, 1))
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

        let face_size = (size * size * 4 * 2) as vk::DeviceSize;
        let regions: Vec<vk::BufferImageCopy> = (0..6u32)
            .map(|face| vk::BufferImageCopy {
                buffer_offset: face as vk::DeviceSize * face_size,
                buffer_row_length: 0,
                buffer_image_height: 0,
                image_subresource: vk::ImageSubresourceLayers {
                    aspect_mask: vk::ImageAspectFlags::COLOR,
                    mip_level: 0,
                    base_array_layer: face,
                    layer_count: 1,
                },
                image_offset: vk::Offset3D { x: 0, y: 0, z: 0 },
                image_extent: vk::Extent3D { width: size, height: size, depth: 1 },
            })
            .collect();
        unsafe {
            device.cmd_copy_buffer_to_image(
                cmd,
                staging,
                image.image,
                vk::ImageLayout::TRANSFER_DST_OPTIMAL,
                &regions,
            );
        }

        // TRANSFER_DST → SHADER_READ, visible to fragment AND compute
        // (compute runs the IBL generation).
        let barrier = vk::ImageMemoryBarrier::default()
            .old_layout(vk::ImageLayout::TRANSFER_DST_OPTIMAL)
            .new_layout(vk::ImageLayout::SHADER_READ_ONLY_OPTIMAL)
            .src_queue_family_index(vk::QUEUE_FAMILY_IGNORED)
            .dst_queue_family_index(vk::QUEUE_FAMILY_IGNORED)
            .image(image.image)
            .subresource_range(cube_range(0, 1))
            .src_access_mask(vk::AccessFlags::TRANSFER_WRITE)
            .dst_access_mask(vk::AccessFlags::SHADER_READ);
        unsafe {
            device.cmd_pipeline_barrier(
                cmd,
                vk::PipelineStageFlags::TRANSFER,
                vk::PipelineStageFlags::FRAGMENT_SHADER
                    | vk::PipelineStageFlags::COMPUTE_SHADER,
                vk::DependencyFlags::empty(),
                &[],
                &[],
                &[barrier],
            );
        }
        self.ctx().end_single_time_commands(cmd)?;

        unsafe {
            device.destroy_buffer(staging, None);
            device.free_memory(staging_mem, None);
        }

        let view = create_view(
            &device,
            image.image,
            HDR_FORMAT,
            vk::ImageViewType::CUBE,
            0,
            1,
            6,
        )?;
        self.cubemap = Some(GpuImage { view, ..image });
        Ok(())
    }
}

// ── IBL generation ───────────────────────────────────────────────────────

impl EnvironmentMap {
    /// `generateIBLTextures` — create irradiance/prefiltered/BRDF-LUT
    /// images and run the three compute shaders.
    pub fn generate_ibl_textures(&mut self, config: &IblConfig) -> Result<()> {
        if !self.loaded {
            bail!("[EnvironmentMap] cannot generate IBL: no environment map loaded");
        }
        tracing::info!("[EnvironmentMap] generating IBL textures");
        self.cleanup_ibl();

        self.prefiltered_mip_levels = config.prefiltered_mip_levels;
        self.ibl_sampler = create_sampler(self.ctx(), config.prefiltered_mip_levels as f32)?;
        self.create_compute_pipelines()?;
        self.create_ibl_images(config)?;

        self.run_brdf_lut_compute(config)?;
        self.run_irradiance_compute(config)?;
        self.run_prefilter_compute(config)?;

        self.ibl_generated = true;
        tracing::info!("[EnvironmentMap] IBL textures generated");
        Ok(())
    }

    /// Create the three IBL images. Unlike the C++, no layout transitions
    /// happen here — each compute run transitions UNDEFINED → GENERAL →
    /// SHADER_READ_ONLY itself (correct old-layout bookkeeping).
    fn create_ibl_images(&mut self, config: &IblConfig) -> Result<()> {
        let device = self.ctx().device().clone();
        let usage = vk::ImageUsageFlags::STORAGE
            | vk::ImageUsageFlags::SAMPLED
            | vk::ImageUsageFlags::TRANSFER_DST;

        let irradiance = create_image(
            self.ctx(),
            config.irradiance_size,
            config.irradiance_size,
            HDR_FORMAT,
            1,
            6,
            usage,
            vk::ImageCreateFlags::CUBE_COMPATIBLE,
        )?;
        let irradiance_view = create_view(
            &device,
            irradiance.image,
            HDR_FORMAT,
            vk::ImageViewType::CUBE,
            0,
            1,
            6,
        )?;
        self.irradiance = Some(GpuImage { view: irradiance_view, ..irradiance });

        let prefiltered = create_image(
            self.ctx(),
            config.prefiltered_size,
            config.prefiltered_size,
            HDR_FORMAT,
            config.prefiltered_mip_levels,
            6,
            usage,
            vk::ImageCreateFlags::CUBE_COMPATIBLE,
        )?;
        let prefiltered_view = create_view(
            &device,
            prefiltered.image,
            HDR_FORMAT,
            vk::ImageViewType::CUBE,
            0,
            config.prefiltered_mip_levels,
            6,
        )?;
        self.prefiltered = Some(GpuImage { view: prefiltered_view, ..prefiltered });

        let brdf = create_image(
            self.ctx(),
            config.brdf_lut_size,
            config.brdf_lut_size,
            BRDF_FORMAT,
            1,
            1,
            usage,
            vk::ImageCreateFlags::empty(),
        )?;
        let brdf_view = create_view(
            &device,
            brdf.image,
            BRDF_FORMAT,
            vk::ImageViewType::TYPE_2D,
            0,
            1,
            1,
        )?;
        self.brdf_lut = Some(GpuImage { view: brdf_view, ..brdf });
        Ok(())
    }

    fn cleanup_ibl(&mut self) {
        let device = self.ctx().device().clone();
        self.ctx().wait_idle();
        if !self.compute_descriptor_pool.is_null() {
            unsafe {
                device.reset_descriptor_pool(self.compute_descriptor_pool, vk::DescriptorPoolResetFlags::empty()).ok();
            }
        }
        if !self.ibl_sampler.is_null() {
            unsafe { device.destroy_sampler(self.ibl_sampler, None) };
            self.ibl_sampler = vk::Sampler::null();
        }
        for slot in [&mut self.irradiance, &mut self.prefiltered, &mut self.brdf_lut] {
            if let Some(img) = slot.take() {
                destroy_gpu_image(&device, img);
            }
        }
        self.ibl_generated = false;
    }

    /// Create the three compute pipelines + shared descriptor pool (once).
    fn create_compute_pipelines(&mut self) -> Result<()> {
        if self.compute_pipelines_created {
            return Ok(());
        }
        // Read the pointer by value so the derived reference does not hold
        // a borrow of `self` across the `&mut self.<field>` arguments below.
        // SAFETY: per the EnvironmentMap invariants the context outlives us.
        let ctx: &VulkanContext = unsafe { &*self.ctx };
        let device = self.ctx().device().clone();

        let pool_sizes = [
            vk::DescriptorPoolSize::default()
                .ty(vk::DescriptorType::COMBINED_IMAGE_SAMPLER)
                .descriptor_count(10),
            vk::DescriptorPoolSize::default()
                .ty(vk::DescriptorType::STORAGE_IMAGE)
                .descriptor_count(10),
        ];
        let pool_info = vk::DescriptorPoolCreateInfo::default()
            .pool_sizes(&pool_sizes)
            .max_sets(10);
        self.compute_descriptor_pool =
            unsafe { device.create_descriptor_pool(&pool_info, None) }
                .context("IBL compute descriptor pool")?;

        // Push-constant sizes: brdf/irradiance = 4×u32, prefilter = 8×f32.
        self.brdf_pipeline = build_ibl_pipeline(
            &device,
            ctx,
            self.compute_descriptor_pool,
            BRDF_LUT_SPV,
            &[vk::DescriptorType::STORAGE_IMAGE],
            16,
            &mut self.brdf_ds_layout,
            &mut self.brdf_pipeline_layout,
        )?;
        self.irradiance_pipeline = build_ibl_pipeline(
            &device,
            ctx,
            self.compute_descriptor_pool,
            IRRADIANCE_SPV,
            &[
                vk::DescriptorType::COMBINED_IMAGE_SAMPLER,
                vk::DescriptorType::STORAGE_IMAGE,
            ],
            16,
            &mut self.irradiance_ds_layout,
            &mut self.irradiance_pipeline_layout,
        )?;
        self.prefilter_pipeline = build_ibl_pipeline(
            &device,
            ctx,
            self.compute_descriptor_pool,
            PREFILTER_SPV,
            &[
                vk::DescriptorType::COMBINED_IMAGE_SAMPLER,
                vk::DescriptorType::STORAGE_IMAGE,
            ],
            32,
            &mut self.prefilter_ds_layout,
            &mut self.prefilter_pipeline_layout,
        )?;

        self.compute_pipelines_created = true;
        tracing::info!("[EnvironmentMap] compute pipelines created");
        Ok(())
    }

    fn run_brdf_lut_compute(&mut self, config: &IblConfig) -> Result<()> {
        let device = self.ctx().device().clone();
        let lut = self.brdf_lut.as_ref().unwrap();
        let set = alloc_compute_set(&device, self.compute_descriptor_pool, self.brdf_ds_layout)?;
        write_storage_image(&device, set, 0, lut.view);

        let cmd = self.ctx().begin_single_time_commands()?;
        record_transition(
            &device,
            cmd,
            lut.image,
            vk::ImageLayout::UNDEFINED,
            vk::ImageLayout::GENERAL,
            vk::AccessFlags::empty(),
            vk::AccessFlags::SHADER_WRITE,
            vk::PipelineStageFlags::TOP_OF_PIPE,
            vk::PipelineStageFlags::COMPUTE_SHADER,
            vk::ImageSubresourceRange {
                aspect_mask: vk::ImageAspectFlags::COLOR,
                base_mip_level: 0,
                level_count: 1,
                base_array_layer: 0,
                layer_count: 1,
            },
        );
        unsafe {
            device.cmd_bind_pipeline(cmd, vk::PipelineBindPoint::COMPUTE, self.brdf_pipeline);
            device.cmd_bind_descriptor_sets(
                cmd,
                vk::PipelineBindPoint::COMPUTE,
                self.brdf_pipeline_layout,
                0,
                &[set],
                &[],
            );
            let push: [u32; 4] = [config.brdf_lut_size, config.sample_count, 0, 0];
            device.cmd_push_constants(
                cmd,
                self.brdf_pipeline_layout,
                vk::ShaderStageFlags::COMPUTE,
                0,
                bytemuck_u32(&push),
            );
            let groups = config.brdf_lut_size.div_ceil(16);
            device.cmd_dispatch(cmd, groups, groups, 1);
        }
        record_transition(
            &device,
            cmd,
            lut.image,
            vk::ImageLayout::GENERAL,
            vk::ImageLayout::SHADER_READ_ONLY_OPTIMAL,
            vk::AccessFlags::SHADER_WRITE,
            vk::AccessFlags::SHADER_READ,
            vk::PipelineStageFlags::COMPUTE_SHADER,
            vk::PipelineStageFlags::FRAGMENT_SHADER | vk::PipelineStageFlags::COMPUTE_SHADER,
            vk::ImageSubresourceRange {
                aspect_mask: vk::ImageAspectFlags::COLOR,
                base_mip_level: 0,
                level_count: 1,
                base_array_layer: 0,
                layer_count: 1,
            },
        );
        self.ctx().end_single_time_commands(cmd)?;
        tracing::info!(size = config.brdf_lut_size, "[EnvironmentMap] BRDF LUT generated");
        Ok(())
    }

    fn run_irradiance_compute(&mut self, config: &IblConfig) -> Result<()> {
        let device = self.ctx().device().clone();
        let set = alloc_compute_set(&device, self.compute_descriptor_pool, self.irradiance_ds_layout)?;
        write_combined_image(&device, set, 0, self.sampler, self.cubemap_view());
        write_storage_image(&device, set, 1, self.irradiance.as_ref().unwrap().view);

        let cmd = self.ctx().begin_single_time_commands()?;
        record_transition(
            &device,
            cmd,
            self.irradiance.as_ref().unwrap().image,
            vk::ImageLayout::UNDEFINED,
            vk::ImageLayout::GENERAL,
            vk::AccessFlags::empty(),
            vk::AccessFlags::SHADER_WRITE,
            vk::PipelineStageFlags::TOP_OF_PIPE,
            vk::PipelineStageFlags::COMPUTE_SHADER,
            cube_range(0, 1),
        );
        unsafe {
            device.cmd_bind_pipeline(cmd, vk::PipelineBindPoint::COMPUTE, self.irradiance_pipeline);
            device.cmd_bind_descriptor_sets(
                cmd,
                vk::PipelineBindPoint::COMPUTE,
                self.irradiance_pipeline_layout,
                0,
                &[set],
                &[],
            );
            let push: [u32; 4] = [config.irradiance_size, config.sample_count, 0, 0];
            device.cmd_push_constants(
                cmd,
                self.irradiance_pipeline_layout,
                vk::ShaderStageFlags::COMPUTE,
                0,
                bytemuck_u32(&push),
            );
            let groups = config.irradiance_size.div_ceil(16);
            device.cmd_dispatch(cmd, groups, groups, 1);
        }
        record_transition(
            &device,
            cmd,
            self.irradiance.as_ref().unwrap().image,
            vk::ImageLayout::GENERAL,
            vk::ImageLayout::SHADER_READ_ONLY_OPTIMAL,
            vk::AccessFlags::SHADER_WRITE,
            vk::AccessFlags::SHADER_READ,
            vk::PipelineStageFlags::COMPUTE_SHADER,
            vk::PipelineStageFlags::FRAGMENT_SHADER | vk::PipelineStageFlags::COMPUTE_SHADER,
            cube_range(0, 1),
        );
        self.ctx().end_single_time_commands(cmd)?;
        tracing::info!(size = config.irradiance_size, "[EnvironmentMap] irradiance map generated");
        Ok(())
    }

    fn run_prefilter_compute(&mut self, config: &IblConfig) -> Result<()> {
        let device = self.ctx().device().clone();
        let prefiltered = self.prefiltered.as_ref().unwrap();

        for mip in 0..config.prefiltered_mip_levels {
            let mip_size = config.prefiltered_size >> mip;
            let roughness = mip as f32 / (config.prefiltered_mip_levels - 1) as f32;

            let set =
                alloc_compute_set(&device, self.compute_descriptor_pool, self.prefilter_ds_layout)?;
            // Per-mip storage view of the cubemap.
            let storage_view = create_view(
                &device,
                prefiltered.image,
                HDR_FORMAT,
                vk::ImageViewType::CUBE,
                mip,
                1,
                6,
            )?;
            write_combined_image(&device, set, 0, self.sampler, self.cubemap_view());
            write_storage_image(&device, set, 1, storage_view);

            let range = cube_range(mip, 1);
            let cmd = self.ctx().begin_single_time_commands()?;
            record_transition(
                &device,
                cmd,
                prefiltered.image,
                vk::ImageLayout::UNDEFINED,
                vk::ImageLayout::GENERAL,
                vk::AccessFlags::empty(),
                vk::AccessFlags::SHADER_WRITE,
                vk::PipelineStageFlags::TOP_OF_PIPE,
                vk::PipelineStageFlags::COMPUTE_SHADER,
                range,
            );
            unsafe {
                device.cmd_bind_pipeline(cmd, vk::PipelineBindPoint::COMPUTE, self.prefilter_pipeline);
                device.cmd_bind_descriptor_sets(
                    cmd,
                    vk::PipelineBindPoint::COMPUTE,
                    self.prefilter_pipeline_layout,
                    0,
                    &[set],
                    &[],
                );
                #[repr(C)]
                struct PrefilterPush {
                    face_size: u32,
                    sample_count: u32,
                    roughness: f32,
                    mip_level: u32,
                    env_map_size: f32,
                    pad1: f32,
                    pad2: f32,
                    pad3: f32,
                }
                let push = PrefilterPush {
                    face_size: mip_size,
                    sample_count: config.sample_count,
                    roughness,
                    mip_level: mip,
                    env_map_size: self.cubemap_size as f32,
                    pad1: 0.0,
                    pad2: 0.0,
                    pad3: 0.0,
                };
                let bytes = std::slice::from_raw_parts(
                    (&push as *const PrefilterPush).cast::<u8>(),
                    std::mem::size_of::<PrefilterPush>(),
                );
                device.cmd_push_constants(
                    cmd,
                    self.prefilter_pipeline_layout,
                    vk::ShaderStageFlags::COMPUTE,
                    0,
                    bytes,
                );
                let groups = mip_size.div_ceil(16);
                device.cmd_dispatch(cmd, groups, groups, 1);
            }
            record_transition(
                &device,
                cmd,
                prefiltered.image,
                vk::ImageLayout::GENERAL,
                vk::ImageLayout::SHADER_READ_ONLY_OPTIMAL,
                vk::AccessFlags::SHADER_WRITE,
                vk::AccessFlags::SHADER_READ,
                vk::PipelineStageFlags::COMPUTE_SHADER,
                vk::PipelineStageFlags::FRAGMENT_SHADER | vk::PipelineStageFlags::COMPUTE_SHADER,
                range,
            );
            self.ctx().end_single_time_commands(cmd)?;
            unsafe { device.destroy_image_view(storage_view, None) };
        }
        tracing::info!(
            size = config.prefiltered_size,
            mips = config.prefiltered_mip_levels,
            "[EnvironmentMap] prefiltered map generated"
        );
        Ok(())
    }
}

impl Drop for EnvironmentMap {
    fn drop(&mut self) {
        let device = self.ctx().device().clone();
        // IBL images + sampler.
        self.cleanup_ibl();
        // Compute pipelines.
        for (pipeline, layout, ds_layout) in [
            (self.brdf_pipeline, self.brdf_pipeline_layout, self.brdf_ds_layout),
            (
                self.irradiance_pipeline,
                self.irradiance_pipeline_layout,
                self.irradiance_ds_layout,
            ),
            (
                self.prefilter_pipeline,
                self.prefilter_pipeline_layout,
                self.prefilter_ds_layout,
            ),
        ] {
            unsafe {
                if !pipeline.is_null() {
                    device.destroy_pipeline(pipeline, None);
                }
                if !layout.is_null() {
                    device.destroy_pipeline_layout(layout, None);
                }
                if !ds_layout.is_null() {
                    device.destroy_descriptor_set_layout(ds_layout, None);
                }
            }
        }
        unsafe {
            if !self.compute_descriptor_pool.is_null() {
                device.destroy_descriptor_pool(self.compute_descriptor_pool, None);
            }
            device.destroy_sampler(self.sampler, None);
        }
        if let Some(cubemap) = self.cubemap.take() {
            destroy_gpu_image(&device, cubemap);
        }
    }
}

// ── Free helpers ─────────────────────────────────────────────────────────

fn cube_range(base_mip: u32, level_count: u32) -> vk::ImageSubresourceRange {
    vk::ImageSubresourceRange {
        aspect_mask: vk::ImageAspectFlags::COLOR,
        base_mip_level: base_mip,
        level_count,
        base_array_layer: 0,
        layer_count: 6,
    }
}

fn bytemuck_u32(data: &[u32]) -> &[u8] {
    unsafe { std::slice::from_raw_parts(data.as_ptr().cast::<u8>(), std::mem::size_of_val(data)) }
}

fn destroy_gpu_image(device: &ash::Device, img: GpuImage) {
    unsafe {
        device.destroy_image_view(img.view, None);
        device.destroy_image(img.image, None);
        device.free_memory(img.memory, None);
    }
}

/// `createSampler` / `createIBLSampler` — linear, clamp-to-edge, anisotropy
/// when supported (always supported on Metal; gated anyway).
fn create_sampler(ctx: &VulkanContext, max_lod: f32) -> Result<vk::Sampler> {
    let mut info = vk::SamplerCreateInfo::default()
        .mag_filter(vk::Filter::LINEAR)
        .min_filter(vk::Filter::LINEAR)
        .mipmap_mode(vk::SamplerMipmapMode::LINEAR)
        .address_mode_u(vk::SamplerAddressMode::CLAMP_TO_EDGE)
        .address_mode_v(vk::SamplerAddressMode::CLAMP_TO_EDGE)
        .address_mode_w(vk::SamplerAddressMode::CLAMP_TO_EDGE)
        .border_color(vk::BorderColor::FLOAT_OPAQUE_BLACK)
        .min_lod(0.0)
        .max_lod(max_lod);
    if ctx.supports_sampler_anisotropy() {
        info = info
            .anisotropy_enable(true)
            .max_anisotropy(ctx.max_sampler_anisotropy());
    }
    unsafe { ctx.device().create_sampler(&info, None) }.context("environment map sampler")
}

/// Create a cube-compatible / mip-chained image (context's `create_image`
/// only covers 2D 1-layer 1-mip, so this lives here, as inline in the C++).
fn create_image(
    ctx: &VulkanContext,
    width: u32,
    height: u32,
    format: vk::Format,
    mip_levels: u32,
    array_layers: u32,
    usage: vk::ImageUsageFlags,
    flags: vk::ImageCreateFlags,
) -> Result<GpuImage> {
    let device = ctx.device();
    let info = vk::ImageCreateInfo::default()
        .image_type(vk::ImageType::TYPE_2D)
        .format(format)
        .extent(vk::Extent3D { width, height, depth: 1 })
        .mip_levels(mip_levels)
        .array_layers(array_layers)
        .samples(vk::SampleCountFlags::TYPE_1)
        .tiling(vk::ImageTiling::OPTIMAL)
        .usage(usage)
        .sharing_mode(vk::SharingMode::EXCLUSIVE)
        .initial_layout(vk::ImageLayout::UNDEFINED)
        .flags(flags);
    let image = unsafe { device.create_image(&info, None) }.context("create IBL image")?;
    let requirements = unsafe { device.get_image_memory_requirements(image) };
    let alloc = vk::MemoryAllocateInfo::default()
        .allocation_size(requirements.size)
        .memory_type_index(
            ctx.find_memory_type(requirements.memory_type_bits, vk::MemoryPropertyFlags::DEVICE_LOCAL)?,
        );
    let memory = unsafe { device.allocate_memory(&alloc, None) }.context("IBL image memory")?;
    unsafe { device.bind_image_memory(image, memory, 0) }?;
    Ok(GpuImage { image, memory, view: vk::ImageView::null() })
}

#[allow(clippy::too_many_arguments)]
fn create_view(
    device: &ash::Device,
    image: vk::Image,
    format: vk::Format,
    view_type: vk::ImageViewType,
    base_mip: u32,
    level_count: u32,
    layer_count: u32,
) -> Result<vk::ImageView> {
    let info = vk::ImageViewCreateInfo::default()
        .image(image)
        .view_type(view_type)
        .format(format)
        .subresource_range(vk::ImageSubresourceRange {
            aspect_mask: vk::ImageAspectFlags::COLOR,
            base_mip_level: base_mip,
            level_count,
            base_array_layer: 0,
            layer_count,
        });
    unsafe { device.create_image_view(&info, None) }.context("IBL image view")
}

/// Build one IBL compute pipeline: bindings 0..n in order, one push range.
fn build_ibl_pipeline(
    device: &ash::Device,
    ctx: &VulkanContext,
    _pool: vk::DescriptorPool,
    spv: &[u8],
    binding_types: &[vk::DescriptorType],
    push_size: u32,
    out_ds_layout: &mut vk::DescriptorSetLayout,
    out_pipeline_layout: &mut vk::PipelineLayout,
) -> Result<vk::Pipeline> {
    let bindings: Vec<vk::DescriptorSetLayoutBinding> = binding_types
        .iter()
        .enumerate()
        .map(|(i, &ty)| {
            vk::DescriptorSetLayoutBinding::default()
                .binding(i as u32)
                .descriptor_type(ty)
                .descriptor_count(1)
                .stage_flags(vk::ShaderStageFlags::COMPUTE)
        })
        .collect();
    let layout_info = vk::DescriptorSetLayoutCreateInfo::default().bindings(&bindings);
    *out_ds_layout = unsafe { device.create_descriptor_set_layout(&layout_info, None) }
        .context("IBL descriptor set layout")?;

    let push_range = [vk::PushConstantRange::default()
        .stage_flags(vk::ShaderStageFlags::COMPUTE)
        .offset(0)
        .size(push_size)];
    let set_layouts = [*out_ds_layout];
    let pl_info = vk::PipelineLayoutCreateInfo::default()
        .set_layouts(&set_layouts)
        .push_constant_ranges(&push_range);
    *out_pipeline_layout = unsafe { device.create_pipeline_layout(&pl_info, None) }
        .context("IBL pipeline layout")?;

    let code: Vec<u32> = spv
        .chunks_exact(4)
        .map(|c| u32::from_le_bytes([c[0], c[1], c[2], c[3]]))
        .collect();
    let module_info = vk::ShaderModuleCreateInfo::default().code(&code);
    let module = unsafe { device.create_shader_module(&module_info, None) }
        .context("IBL shader module")?;
    let stage = vk::PipelineShaderStageCreateInfo::default()
        .stage(vk::ShaderStageFlags::COMPUTE)
        .module(module)
        .name(c"main");
    let pipeline_info = [vk::ComputePipelineCreateInfo::default()
        .stage(stage)
        .layout(*out_pipeline_layout)];
    let pipeline = unsafe {
        device.create_compute_pipelines(ctx.pipeline_cache(), &pipeline_info, None)
    }
    .map_err(|(_, e)| e)
    .context("IBL compute pipeline")?[0];
    unsafe { device.destroy_shader_module(module, None) };
    Ok(pipeline)
}

fn alloc_compute_set(
    device: &ash::Device,
    pool: vk::DescriptorPool,
    layout: vk::DescriptorSetLayout,
) -> Result<vk::DescriptorSet> {
    let layouts = [layout];
    let info = vk::DescriptorSetAllocateInfo::default()
        .descriptor_pool(pool)
        .set_layouts(&layouts);
    Ok(unsafe { device.allocate_descriptor_sets(&info) }
        .context("IBL descriptor set")?[0])
}

fn write_storage_image(
    device: &ash::Device,
    set: vk::DescriptorSet,
    binding: u32,
    view: vk::ImageView,
) {
    let info = [vk::DescriptorImageInfo::default()
        .image_view(view)
        .image_layout(vk::ImageLayout::GENERAL)];
    let write = [vk::WriteDescriptorSet::default()
        .dst_set(set)
        .dst_binding(binding)
        .descriptor_type(vk::DescriptorType::STORAGE_IMAGE)
        .image_info(&info)];
    unsafe { device.update_descriptor_sets(&write, &[]) };
}

fn write_combined_image(
    device: &ash::Device,
    set: vk::DescriptorSet,
    binding: u32,
    sampler: vk::Sampler,
    view: vk::ImageView,
) {
    let info = [vk::DescriptorImageInfo::default()
        .sampler(sampler)
        .image_view(view)
        .image_layout(vk::ImageLayout::SHADER_READ_ONLY_OPTIMAL)];
    let write = [vk::WriteDescriptorSet::default()
        .dst_set(set)
        .dst_binding(binding)
        .descriptor_type(vk::DescriptorType::COMBINED_IMAGE_SAMPLER)
        .image_info(&info)];
    unsafe { device.update_descriptor_sets(&write, &[]) };
}

#[allow(clippy::too_many_arguments)]
fn record_transition(
    device: &ash::Device,
    cmd: vk::CommandBuffer,
    image: vk::Image,
    old_layout: vk::ImageLayout,
    new_layout: vk::ImageLayout,
    src_access: vk::AccessFlags,
    dst_access: vk::AccessFlags,
    src_stage: vk::PipelineStageFlags,
    dst_stage: vk::PipelineStageFlags,
    range: vk::ImageSubresourceRange,
) {
    let barrier = vk::ImageMemoryBarrier::default()
        .old_layout(old_layout)
        .new_layout(new_layout)
        .src_queue_family_index(vk::QUEUE_FAMILY_IGNORED)
        .dst_queue_family_index(vk::QUEUE_FAMILY_IGNORED)
        .image(image)
        .subresource_range(range)
        .src_access_mask(src_access)
        .dst_access_mask(dst_access);
    unsafe {
        device.cmd_pipeline_barrier(
            cmd,
            src_stage,
            dst_stage,
            vk::DependencyFlags::empty(),
            &[],
            &[],
            &[barrier],
        );
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn float_to_half_basic() {
        assert_eq!(float_to_half(0.0), 0x0000);
        assert_eq!(float_to_half(1.0), 0x3C00);
        assert_eq!(float_to_half(-2.0), 0xC000);
        assert_eq!(float_to_half(65504.0), 0x7BFF); // max half
        assert_eq!(float_to_half(f32::INFINITY), 0x7C00);
    }

    #[test]
    fn cubemap_directions_match_cpp() {
        // Face +X at u=v=0 → (1, 0, 0); face -Z at u=v=0 → (0, 0, -1).
        assert_eq!(cubemap_direction(0, 0.0, 0.0), Vec3::new(1.0, 0.0, 0.0));
        assert_eq!(cubemap_direction(5, 0.0, 0.0), Vec3::new(0.0, 0.0, -1.0));
        // Face +Y at u=1, v=-1 → (1, 1, -1).
        assert_eq!(cubemap_direction(2, 1.0, -1.0), Vec3::new(1.0, 1.0, -1.0));
    }
}
