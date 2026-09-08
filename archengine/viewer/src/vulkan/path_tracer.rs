//! Port of `path_tracer.hpp/.cpp` — compute shader-based path tracer.
//!
//! Progressive Monte Carlo path tracing on any Vulkan GPU (no
//! `VK_KHR_ray_tracing_pipeline`): the `path_trace.comp` shader traverses the
//! SAH BVH built by [`archengine_geometry::bvh::build_scene_bvh`] — the GPU
//! layouts (`GpuBvhNode` 32B, `GpuTriangle` 48B, `GpuPtMaterial` 64B) were
//! designed for this shader and port verbatim.
//!
//! Deferred from the C++ (tracked in the port notes):
//! - Polyhaven texture array (`loadMaterialTextures`) — materials currently
//!   carry flat albedo/roughness from the material table.
//! - OIDN denoising — the C++ only ships the 3×3 edge-aware CPU filter,
//!   which is ported verbatim.
//!
//! Unlike the C++, descriptor bindings 5 (env map) and 6 (texture array)
//! are always written with valid placeholder textures (a 1×1 cubemap / 2D
//! array) when nothing real is bound — the C++ left them unwritten, which
//! is invalid Vulkan and trips MoltenVK validation.

use std::ffi::c_void;
use std::path::Path;

use anyhow::{Context as _, Result, anyhow, bail};
use ash::vk;
use glam::{Mat4, Vec3, Vec4};

use archengine_geometry::bvh::{MaterialTable, SceneBvh, build_scene_bvh};
use archengine_geometry::domain::{StructuralElement, TerrainMesh};

use super::context::VulkanContext;
use super::environment::EnvironmentMap;
use crate::camera::Camera;

/// SPIR-V for `path_trace.comp`, compiled from the verbatim GLSL by build.rs.
const PATH_TRACE_SPV: &[u8] =
    include_bytes!(concat!(env!("OUT_DIR"), "/spirv/path_trace.comp.spv"));

/// Path tracer configuration — defaults verbatim from C++ `PathTracerConfig`.
#[derive(Debug, Clone)]
pub struct PathTracerConfig {
    pub width: u32,
    pub height: u32,
    /// Total samples per pixel.
    pub samples_per_pixel: u32,
    pub max_bounces: u32,
    /// Samples per progressive frame.
    pub samples_per_frame: u32,
    /// Apply the 3×3 edge-aware filter to the final result.
    pub enable_denoising: bool,
    /// Next Event Estimation (direct light sampling).
    pub enable_nee: bool,
    /// Russian Roulette path termination.
    pub enable_rr: bool,
    /// Depth at which RR starts.
    pub rr_start_depth: u32,
    pub exposure: f32,
    /// 0 = Reinhard, 1 = ACES, 2 = Uncharted2.
    pub tonemap_mode: u32,
}

impl Default for PathTracerConfig {
    fn default() -> Self {
        Self {
            width: 1920,
            height: 1080,
            samples_per_pixel: 64,
            max_bounces: 8,
            samples_per_frame: 1,
            enable_denoising: true,
            enable_nee: true,
            enable_rr: true,
            rr_start_depth: 3,
            exposure: 1.0,
            tonemap_mode: 1,
        }
    }
}

/// GPU uniform buffer — layout must match C++ `PathTraceUBO` and the
/// shader's UBO block exactly (std140-style packing, 272 bytes:
/// 2×mat4 + 5×vec4 + 15 scalars + 1 pad word).
#[repr(C)]
#[derive(Debug, Clone, Copy)]
pub struct PathTraceUbo {
    pub camera_inv_view: Mat4,
    pub camera_inv_proj: Mat4,
    /// xyz = camera world position.
    pub camera_position: Vec4,
    /// xyz = directional light, w = intensity.
    pub light_direction: Vec4,
    pub light_color: Vec4,
    /// x = has env map, y = intensity, z = rotation.
    pub env_map_info: Vec4,
    /// xyz = normal, w = distance (section clipping).
    pub clip_plane: Vec4,
    pub frame_index: u32,
    pub sample_count: u32,
    pub max_bounces: u32,
    pub triangle_count: u32,
    pub node_count: u32,
    pub material_count: u32,
    pub enable_nee: u32,
    pub enable_rr: u32,
    pub rr_start_depth: u32,
    pub exposure: f32,
    pub tonemap_mode: u32,
    pub width: u32,
    pub height: u32,
    pub enable_clipping: u32,
    /// UV scale to match the live renderer (base = 0.001 * this).
    pub uv_scale: f32,
    pub _pad: [u32; 1],
}

const _: () = assert!(std::mem::size_of::<PathTraceUbo>() == 272);

/// Reinterpret a POD value as bytes for a mapped-memory upload.
fn as_bytes<T>(v: &T) -> &[u8] {
    unsafe { std::slice::from_raw_parts((v as *const T).cast::<u8>(), std::mem::size_of::<T>()) }
}

/// `enum class PathTracerState`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PathTracerState {
    Idle,
    Rendering,
    Complete,
    Error,
}

struct SceneBuffers {
    triangle_buffer: vk::Buffer,
    triangle_memory: vk::DeviceMemory,
    bvh_buffer: vk::Buffer,
    bvh_memory: vk::DeviceMemory,
    material_buffer: vk::Buffer,
    material_memory: vk::DeviceMemory,
}

struct RenderResources {
    pipeline: vk::Pipeline,
    pipeline_layout: vk::PipelineLayout,
    descriptor_set_layout: vk::DescriptorSetLayout,
    descriptor_pool: vk::DescriptorPool,
    descriptor_set: vk::DescriptorSet,
    ubo_buffer: vk::Buffer,
    ubo_memory: vk::DeviceMemory,
    ubo_mapped: *mut c_void,
    staging_buffer: vk::Buffer,
    staging_memory: vk::DeviceMemory,
    accum_image: vk::Image,
    accum_memory: vk::DeviceMemory,
    accum_view: vk::ImageView,
}

// Raw mapped pointer is only used under &mut self / device-local sync.
unsafe impl Send for RenderResources {}

/// Placeholder 2D texture array (1×1 white) for descriptor binding 6 until
/// the Polyhaven material texture array is ported (questions.md A4). Keeps
/// the descriptor set valid without `PARTIALLY_BOUND`.
struct PlaceholderTextureArray {
    image: vk::Image,
    memory: vk::DeviceMemory,
    view: vk::ImageView,
    sampler: vk::Sampler,
}

impl PlaceholderTextureArray {
    fn create(ctx: &VulkanContext) -> Result<Self> {
        let device = ctx.device();
        let (image, memory) = ctx.create_image(
            1,
            1,
            vk::Format::R8G8B8A8_UNORM,
            vk::ImageTiling::OPTIMAL,
            vk::ImageUsageFlags::TRANSFER_DST | vk::ImageUsageFlags::SAMPLED,
            vk::MemoryPropertyFlags::DEVICE_LOCAL,
            vk::SampleCountFlags::TYPE_1,
        )?;
        ctx.transition_image_layout(
            image,
            vk::Format::R8G8B8A8_UNORM,
            vk::ImageLayout::UNDEFINED,
            vk::ImageLayout::TRANSFER_DST_OPTIMAL,
            1,
            1,
        )?;
        let (staging, staging_mem) = ctx.create_buffer(
            4,
            vk::BufferUsageFlags::TRANSFER_SRC,
            vk::MemoryPropertyFlags::HOST_VISIBLE | vk::MemoryPropertyFlags::HOST_COHERENT,
        )?;
        unsafe {
            let mapped = device.map_memory(staging_mem, 0, 4, vk::MemoryMapFlags::empty())?;
            std::ptr::copy_nonoverlapping([255u8; 4].as_ptr(), mapped.cast::<u8>(), 4);
            device.unmap_memory(staging_mem);
        }
        ctx.copy_buffer_to_image(staging, image, 1, 1)?;
        ctx.transition_image_layout(
            image,
            vk::Format::R8G8B8A8_UNORM,
            vk::ImageLayout::TRANSFER_DST_OPTIMAL,
            vk::ImageLayout::SHADER_READ_ONLY_OPTIMAL,
            1,
            1,
        )?;
        unsafe {
            device.destroy_buffer(staging, None);
            device.free_memory(staging_mem, None);
        }
        let view_info = vk::ImageViewCreateInfo::default()
            .image(image)
            .view_type(vk::ImageViewType::TYPE_2D_ARRAY)
            .format(vk::Format::R8G8B8A8_UNORM)
            .subresource_range(vk::ImageSubresourceRange {
                aspect_mask: vk::ImageAspectFlags::COLOR,
                base_mip_level: 0,
                level_count: 1,
                base_array_layer: 0,
                layer_count: 1,
            });
        let view = unsafe { device.create_image_view(&view_info, None) }
            .context("placeholder texture array view")?;
        let sampler_info = vk::SamplerCreateInfo::default()
            .mag_filter(vk::Filter::LINEAR)
            .min_filter(vk::Filter::LINEAR);
        let sampler = unsafe { device.create_sampler(&sampler_info, None) }
            .context("placeholder texture array sampler")?;
        Ok(Self { image, memory, view, sampler })
    }

    fn descriptor_info(&self) -> vk::DescriptorImageInfo {
        vk::DescriptorImageInfo::default()
            .sampler(self.sampler)
            .image_view(self.view)
            .image_layout(vk::ImageLayout::SHADER_READ_ONLY_OPTIMAL)
    }

    fn destroy(self, ctx: &VulkanContext) {
        let device = ctx.device();
        unsafe {
            device.destroy_sampler(self.sampler, None);
            device.destroy_image_view(self.view, None);
            device.destroy_image(self.image, None);
            device.free_memory(self.memory, None);
        }
    }
}


/// Compute-shader path tracer. Borrows the [`VulkanContext`]; scene data
/// survives [`Self::start_render`] cycles, render resources do not
/// (mirrors `cleanupRenderResources` vs `cleanup`).
pub struct PathTracer<'ctx> {
    ctx: &'ctx VulkanContext,
    config: PathTracerConfig,
    camera: Camera,
    clip_plane: Vec4,
    enable_clipping: bool,
    uv_scale: f32,

    state: PathTracerState,
    frame_index: u32,
    current_sample: u32,
    stop_requested: bool,

    scene: Option<SceneBvh>,
    scene_buffers: Option<SceneBuffers>,
    render: Option<RenderResources>,

    env_map: Option<EnvironmentMap>,
    env_intensity: f32,
    env_rotation: f32,
    placeholder_cube: Option<EnvironmentMap>,
    placeholder_tex_array: Option<PlaceholderTextureArray>,

    hdr_pixels: Vec<f32>,
    ldr_pixels: Vec<u8>,

    progress_callback: Option<Box<dyn FnMut(f32) + Send>>,
}

impl<'ctx> PathTracer<'ctx> {
    pub fn new(ctx: &'ctx VulkanContext) -> Self {
        tracing::info!("[PathTracer] initialized");
        Self {
            ctx,
            config: PathTracerConfig::default(),
            camera: Camera::default(),
            clip_plane: Vec4::ZERO,
            enable_clipping: false,
            uv_scale: 1.0,
            state: PathTracerState::Idle,
            frame_index: 0,
            current_sample: 0,
            stop_requested: false,
            scene: None,
            scene_buffers: None,
            render: None,
            env_map: None,
            env_intensity: 1.0,
            env_rotation: 0.0,
            placeholder_cube: None,
            placeholder_tex_array: None,
            hdr_pixels: Vec::new(),
            ldr_pixels: Vec::new(),
            progress_callback: None,
        }
    }

    pub fn state(&self) -> PathTracerState {
        self.state
    }
    pub fn set_camera(&mut self, camera: Camera) {
        self.camera = camera;
    }
    pub fn camera_mut(&mut self) -> &mut Camera {
        &mut self.camera
    }
    pub fn set_clip_plane(&mut self, plane: Vec4, enabled: bool) {
        self.clip_plane = plane;
        self.enable_clipping = enabled;
    }
    pub fn set_config(&mut self, config: PathTracerConfig) {
        self.config = config;
    }
    pub fn config(&self) -> &PathTracerConfig {
        &self.config
    }
    pub fn set_uv_scale(&mut self, scale: f32) {
        self.uv_scale = scale;
    }
    pub fn set_progress_callback(&mut self, callback: impl FnMut(f32) + Send + 'static) {
        self.progress_callback = Some(Box::new(callback));
    }
    pub fn hdr_pixels(&self) -> &[f32] {
        &self.hdr_pixels
    }
    pub fn ldr_pixels(&self) -> &[u8] {
        &self.ldr_pixels
    }

    /// C++ `setEnvironmentMap` — bind an environment cubemap for
    /// background + environment lighting (binding 5, `envMapInfo`).
    /// If a render is in progress its descriptor set is rewritten under
    /// `wait_idle`; call [`Self::start_render`] again to re-accumulate
    /// from zero with the new environment.
    pub fn set_environment_map(
        &mut self,
        env_map: EnvironmentMap,
        intensity: f32,
        rotation: f32,
    ) -> Result<()> {
        self.env_intensity = intensity;
        self.env_rotation = rotation;
        self.env_map = Some(env_map);
        if let Some(render) = &self.render {
            self.ctx.wait_idle();
            let env = self.env_map.as_ref().unwrap();
            let info = [env.descriptor_info()];
            let write = [vk::WriteDescriptorSet::default()
                .dst_set(render.descriptor_set)
                .dst_binding(5)
                .descriptor_type(vk::DescriptorType::COMBINED_IMAGE_SAMPLER)
                .image_info(&info)];
            unsafe { self.ctx.device().update_descriptor_sets(&write, &[]) };
        }
        Ok(())
    }

    /// Lazily create the placeholder cubemap / texture array so descriptor
    /// bindings 5/6 are always valid (see module docs).
    fn ensure_placeholders(&mut self) -> Result<()> {
        if self.placeholder_cube.is_none() {
            let mut cube = EnvironmentMap::new(self.ctx)?;
            cube.create_solid([0.0, 0.0, 0.0])?;
            self.placeholder_cube = Some(cube);
        }
        if self.placeholder_tex_array.is_none() {
            self.placeholder_tex_array = Some(PlaceholderTextureArray::create(self.ctx)?);
        }
        Ok(())
    }

    /// Build the scene BVH and upload triangle/node/material buffers.
    /// Mirrors C++ `setScene(elements, terrain, terrainMaterialName)`;
    /// returns `Ok(false)` where the C++ returns `false`.
    pub fn set_scene(
        &mut self,
        elements: &[StructuralElement],
        terrain: Option<(&TerrainMesh, &str)>,
        materials: &MaterialTable,
    ) -> Result<bool> {
        let scene = match build_scene_bvh(elements, terrain, materials) {
            Some(s) => s,
            None => {
                tracing::error!("[PathTracer] failed to build scene BVH");
                return Ok(false);
            }
        };
        tracing::info!(
            triangles = scene.triangles.len(),
            nodes = scene.nodes.len(),
            materials = scene.materials.len(),
            "[PathTracer] scene built"
        );

        let device = self.ctx.device();
        self.destroy_scene_buffers();

        // Triangle buffer — HOST_VISIBLE for direct upload (as C++).
        let triangle_size = std::mem::size_of_val(&scene.triangles[..]) as vk::DeviceSize;
        let (triangle_buffer, triangle_memory) = self.ctx.create_buffer(
            triangle_size,
            vk::BufferUsageFlags::STORAGE_BUFFER,
            vk::MemoryPropertyFlags::HOST_VISIBLE | vk::MemoryPropertyFlags::HOST_COHERENT,
        )?;
        unsafe {
            let data = device.map_memory(triangle_memory, 0, triangle_size, vk::MemoryMapFlags::empty())?;
            std::ptr::copy_nonoverlapping(
                scene.triangles.as_ptr().cast::<u8>(),
                data.cast::<u8>(),
                triangle_size as usize,
            );
            device.unmap_memory(triangle_memory);
        }

        // BVH buffer — DEVICE_LOCAL via staging (as C++).
        let bvh_size = std::mem::size_of_val(&scene.nodes[..]) as vk::DeviceSize;
        let (bvh_buffer, bvh_memory) = self.ctx.create_buffer(
            bvh_size,
            vk::BufferUsageFlags::STORAGE_BUFFER | vk::BufferUsageFlags::TRANSFER_DST,
            vk::MemoryPropertyFlags::DEVICE_LOCAL,
        )?;
        let (staging_buffer, staging_memory) = self.ctx.create_buffer(
            bvh_size,
            vk::BufferUsageFlags::TRANSFER_SRC,
            vk::MemoryPropertyFlags::HOST_VISIBLE | vk::MemoryPropertyFlags::HOST_COHERENT,
        )?;
        unsafe {
            let data = device.map_memory(staging_memory, 0, bvh_size, vk::MemoryMapFlags::empty())?;
            std::ptr::copy_nonoverlapping(
                scene.nodes.as_ptr().cast::<u8>(),
                data.cast::<u8>(),
                bvh_size as usize,
            );
            device.unmap_memory(staging_memory);
        }
        self.ctx.copy_buffer(staging_buffer, bvh_buffer, bvh_size)?;
        unsafe {
            device.destroy_buffer(staging_buffer, None);
            device.free_memory(staging_memory, None);
        }

        // Material buffer — HOST_VISIBLE (as C++, "for reliability").
        let material_size = std::mem::size_of_val(&scene.materials[..]) as vk::DeviceSize;
        let (material_buffer, material_memory) = self.ctx.create_buffer(
            material_size,
            vk::BufferUsageFlags::STORAGE_BUFFER,
            vk::MemoryPropertyFlags::HOST_VISIBLE | vk::MemoryPropertyFlags::HOST_COHERENT,
        )?;
        unsafe {
            let data =
                device.map_memory(material_memory, 0, material_size, vk::MemoryMapFlags::empty())?;
            std::ptr::copy_nonoverlapping(
                scene.materials.as_ptr().cast::<u8>(),
                data.cast::<u8>(),
                material_size as usize,
            );
            device.unmap_memory(material_memory);
        }

        self.scene_buffers = Some(SceneBuffers {
            triangle_buffer,
            triangle_memory,
            bvh_buffer,
            bvh_memory,
            material_buffer,
            material_memory,
        });
        self.scene = Some(scene);
        Ok(true)
    }

    /// Begin a progressive render. Scene must be uploaded first.
    pub fn start_render(&mut self) -> Result<()> {
        let Some(scene) = &self.scene else {
            tracing::error!("[PathTracer] cannot start render — no valid scene");
            self.state = PathTracerState::Error;
            bail!("no valid scene");
        };
        let (triangle_count, node_count, material_count) = (
            scene.triangles.len() as u32,
            scene.nodes.len() as u32,
            scene.materials.len() as u32,
        );

        self.cleanup_render_resources();
        self.ensure_placeholders()?;
        let render = self.create_render_resources(triangle_count, node_count, material_count)?;

        self.current_sample = 0;
        self.frame_index = 0;
        self.stop_requested = false;
        self.state = PathTracerState::Rendering;

        // Clear the accumulation buffer.
        let cmd = self.ctx.begin_single_time_commands()?;
        let clear = vk::ClearColorValue { float32: [0.0; 4] };
        let range = vk::ImageSubresourceRange {
            aspect_mask: vk::ImageAspectFlags::COLOR,
            base_mip_level: 0,
            level_count: 1,
            base_array_layer: 0,
            layer_count: 1,
        };
        unsafe {
            self.ctx.device().cmd_clear_color_image(
                cmd,
                render.accum_image,
                vk::ImageLayout::GENERAL,
                &clear,
                &[range],
            )
        };
        self.ctx.end_single_time_commands(cmd)?;

        self.render = Some(render);
        tracing::info!(
            width = self.config.width,
            height = self.config.height,
            spp = self.config.samples_per_pixel,
            "[PathTracer] started render"
        );
        Ok(())
    }

    /// Render one progressive frame. Returns `false` when the render is
    /// complete, stopped, or not running (mirrors C++ `renderFrame`).
    pub fn render_frame(&mut self) -> Result<bool> {
        if self.state != PathTracerState::Rendering {
            return Ok(false);
        }
        if self.stop_requested {
            self.state = PathTracerState::Idle;
            return Ok(false);
        }
        if self.current_sample >= self.config.samples_per_pixel {
            self.download_result()?;
            if self.config.enable_denoising {
                self.apply_denoising();
            }
            self.tonemap_result();
            self.state = PathTracerState::Complete;
            if let Some(cb) = &mut self.progress_callback {
                cb(1.0);
            }
            return Ok(false);
        }

        self.update_ubo();

        let render = self.render.as_ref().unwrap();
        let cmd = self.ctx.begin_single_time_commands()?;
        unsafe {
            let device = self.ctx.device();
            device.cmd_bind_pipeline(cmd, vk::PipelineBindPoint::COMPUTE, render.pipeline);
            device.cmd_bind_descriptor_sets(
                cmd,
                vk::PipelineBindPoint::COMPUTE,
                render.pipeline_layout,
                0,
                &[render.descriptor_set],
                &[],
            );
            // 16×16 workgroups, as the shader's local_size.
            device.cmd_dispatch(
                cmd,
                self.config.width.div_ceil(16),
                self.config.height.div_ceil(16),
                1,
            );
        }
        self.ctx.end_single_time_commands(cmd)?;

        self.current_sample += self.config.samples_per_frame;
        self.frame_index += 1;
        if self.progress_callback.is_some() {
            let progress = self.progress();
            if let Some(cb) = &mut self.progress_callback {
                cb(progress);
            }
        }
        Ok(true)
    }

    /// Render to completion in a loop (headless batch use).
    pub fn render_to_completion(&mut self) -> Result<()> {
        while self.render_frame()? {}
        if self.state != PathTracerState::Complete {
            bail!("render did not complete (state: {:?})", self.state);
        }
        Ok(())
    }

    pub fn stop_render(&mut self) {
        self.stop_requested = true;
    }

    pub fn progress(&self) -> f32 {
        if self.config.samples_per_pixel == 0 {
            0.0
        } else {
            self.current_sample as f32 / self.config.samples_per_pixel as f32
        }
    }

    // ── Resource creation (C++: createAccumulationImage / createBuffers /
    //    createComputePipeline / createDescriptorSets) ────────────────────

    fn create_render_resources(
        &self,
        _triangle_count: u32,
        _node_count: u32,
        _material_count: u32,
    ) -> Result<RenderResources> {
        let device = self.ctx.device();
        let scene = self.scene_buffers.as_ref().expect("scene uploaded");

        // Accumulation image: RGBA32F storage + transfer-src.
        let (accum_image, accum_memory) = self.ctx.create_image(
            self.config.width,
            self.config.height,
            vk::Format::R32G32B32A32_SFLOAT,
            vk::ImageTiling::OPTIMAL,
            vk::ImageUsageFlags::STORAGE | vk::ImageUsageFlags::TRANSFER_SRC,
            vk::MemoryPropertyFlags::DEVICE_LOCAL,
            vk::SampleCountFlags::TYPE_1,
        )?;
        let accum_view = self.ctx.create_image_view(
            accum_image,
            vk::Format::R32G32B32A32_SFLOAT,
            vk::ImageAspectFlags::COLOR,
        )?;
        self.ctx.transition_image_layout(
            accum_image,
            vk::Format::R32G32B32A32_SFLOAT,
            vk::ImageLayout::UNDEFINED,
            vk::ImageLayout::GENERAL,
            1,
            1,
        )?;

        // UBO (persistently mapped) + result staging buffer.
        let (ubo_buffer, ubo_memory) = self.ctx.create_buffer(
            std::mem::size_of::<PathTraceUbo>() as vk::DeviceSize,
            vk::BufferUsageFlags::UNIFORM_BUFFER,
            vk::MemoryPropertyFlags::HOST_VISIBLE | vk::MemoryPropertyFlags::HOST_COHERENT,
        )?;
        let ubo_mapped = unsafe {
            device.map_memory(
                ubo_memory,
                0,
                std::mem::size_of::<PathTraceUbo>() as vk::DeviceSize,
                vk::MemoryMapFlags::empty(),
            )?
        };
        let staging_size =
            self.config.width as u64 * self.config.height as u64 * 4 * size_of::<f32>() as u64;
        let (staging_buffer, staging_memory) = self.ctx.create_buffer(
            staging_size,
            vk::BufferUsageFlags::TRANSFER_DST,
            vk::MemoryPropertyFlags::HOST_VISIBLE | vk::MemoryPropertyFlags::HOST_COHERENT,
        )?;

        // Descriptor set layout — bindings verbatim from C++.
        let bindings = [
            // 0: accumulation image
            vk::DescriptorSetLayoutBinding::default()
                .binding(0)
                .descriptor_type(vk::DescriptorType::STORAGE_IMAGE)
                .descriptor_count(1)
                .stage_flags(vk::ShaderStageFlags::COMPUTE),
            // 1: UBO
            vk::DescriptorSetLayoutBinding::default()
                .binding(1)
                .descriptor_type(vk::DescriptorType::UNIFORM_BUFFER)
                .descriptor_count(1)
                .stage_flags(vk::ShaderStageFlags::COMPUTE),
            // 2: triangles
            vk::DescriptorSetLayoutBinding::default()
                .binding(2)
                .descriptor_type(vk::DescriptorType::STORAGE_BUFFER)
                .descriptor_count(1)
                .stage_flags(vk::ShaderStageFlags::COMPUTE),
            // 3: BVH nodes
            vk::DescriptorSetLayoutBinding::default()
                .binding(3)
                .descriptor_type(vk::DescriptorType::STORAGE_BUFFER)
                .descriptor_count(1)
                .stage_flags(vk::ShaderStageFlags::COMPUTE),
            // 4: materials
            vk::DescriptorSetLayoutBinding::default()
                .binding(4)
                .descriptor_type(vk::DescriptorType::STORAGE_BUFFER)
                .descriptor_count(1)
                .stage_flags(vk::ShaderStageFlags::COMPUTE),
            // 5: environment map (bound when loaded)
            vk::DescriptorSetLayoutBinding::default()
                .binding(5)
                .descriptor_type(vk::DescriptorType::COMBINED_IMAGE_SAMPLER)
                .descriptor_count(1)
                .stage_flags(vk::ShaderStageFlags::COMPUTE),
            // 6: texture array (bound when loaded)
            vk::DescriptorSetLayoutBinding::default()
                .binding(6)
                .descriptor_type(vk::DescriptorType::COMBINED_IMAGE_SAMPLER)
                .descriptor_count(1)
                .stage_flags(vk::ShaderStageFlags::COMPUTE),
        ];
        let layout_info = vk::DescriptorSetLayoutCreateInfo::default().bindings(&bindings);
        let descriptor_set_layout =
            unsafe { device.create_descriptor_set_layout(&layout_info, None) }
                .context("path tracer descriptor set layout")?;

        let set_layouts = [descriptor_set_layout];
        let pipeline_layout_info =
            vk::PipelineLayoutCreateInfo::default().set_layouts(&set_layouts);
        let pipeline_layout =
            unsafe { device.create_pipeline_layout(&pipeline_layout_info, None) }
                .context("path tracer pipeline layout")?;

        // Compute pipeline from the verbatim GLSL (SPIR-V baked in by build.rs).
        let spv: Vec<u32> = PATH_TRACE_SPV
            .chunks_exact(4)
            .map(|c| u32::from_le_bytes([c[0], c[1], c[2], c[3]]))
            .collect();
        let module_info = vk::ShaderModuleCreateInfo::default().code(&spv);
        let shader_module = unsafe { device.create_shader_module(&module_info, None) }
            .context("path_trace shader module")?;
        let stage = vk::PipelineShaderStageCreateInfo::default()
            .stage(vk::ShaderStageFlags::COMPUTE)
            .module(shader_module)
            .name(c"main");
        let pipeline_info = vk::ComputePipelineCreateInfo::default()
            .stage(stage)
            .layout(pipeline_layout);
        let pipeline = unsafe {
            device.create_compute_pipelines(
                self.ctx.pipeline_cache(),
                &[pipeline_info],
                None,
            )
        }
        .map_err(|(_, e)| e)
        .context("path tracer compute pipeline")?[0];
        unsafe { device.destroy_shader_module(shader_module, None) };

        // Descriptor pool + set.
        let pool_sizes = [
            vk::DescriptorPoolSize::default()
                .ty(vk::DescriptorType::STORAGE_IMAGE)
                .descriptor_count(1),
            vk::DescriptorPoolSize::default()
                .ty(vk::DescriptorType::UNIFORM_BUFFER)
                .descriptor_count(1),
            vk::DescriptorPoolSize::default()
                .ty(vk::DescriptorType::STORAGE_BUFFER)
                .descriptor_count(3),
            vk::DescriptorPoolSize::default()
                .ty(vk::DescriptorType::COMBINED_IMAGE_SAMPLER)
                .descriptor_count(2),
        ];
        let pool_info = vk::DescriptorPoolCreateInfo::default()
            .pool_sizes(&pool_sizes)
            .max_sets(1);
        let descriptor_pool = unsafe { device.create_descriptor_pool(&pool_info, None) }
            .context("path tracer descriptor pool")?;
        let alloc_info = vk::DescriptorSetAllocateInfo::default()
            .descriptor_pool(descriptor_pool)
            .set_layouts(&set_layouts);
        let descriptor_set = unsafe { device.allocate_descriptor_sets(&alloc_info) }
            .context("path tracer descriptor set")?[0];

        // Writes — bindings 5/6 always carry a valid texture: the real env
        // map when set, otherwise placeholders (the shader guards on
        // envMapInfo.x / texture index).
        let accum_info = [vk::DescriptorImageInfo::default()
            .image_view(accum_view)
            .image_layout(vk::ImageLayout::GENERAL)];
        let ubo_info = [vk::DescriptorBufferInfo::default()
            .buffer(ubo_buffer)
            .offset(0)
            .range(std::mem::size_of::<PathTraceUbo>() as vk::DeviceSize)];
        let triangle_info = [vk::DescriptorBufferInfo::default()
            .buffer(scene.triangle_buffer)
            .offset(0)
            .range(vk::WHOLE_SIZE)];
        let bvh_info = [vk::DescriptorBufferInfo::default()
            .buffer(scene.bvh_buffer)
            .offset(0)
            .range(vk::WHOLE_SIZE)];
        let material_info = [vk::DescriptorBufferInfo::default()
            .buffer(scene.material_buffer)
            .offset(0)
            .range(vk::WHOLE_SIZE)];
        let env_info = [match &self.env_map {
            Some(env) if env.is_loaded() => env.descriptor_info(),
            _ => self
                .placeholder_cube
                .as_ref()
                .expect("placeholders created")
                .descriptor_info(),
        }];
        let tex_array_info = [self
            .placeholder_tex_array
            .as_ref()
            .expect("placeholders created")
            .descriptor_info()];
        let writes = [
            vk::WriteDescriptorSet::default()
                .dst_set(descriptor_set)
                .dst_binding(0)
                .descriptor_type(vk::DescriptorType::STORAGE_IMAGE)
                .image_info(&accum_info),
            vk::WriteDescriptorSet::default()
                .dst_set(descriptor_set)
                .dst_binding(1)
                .descriptor_type(vk::DescriptorType::UNIFORM_BUFFER)
                .buffer_info(&ubo_info),
            vk::WriteDescriptorSet::default()
                .dst_set(descriptor_set)
                .dst_binding(2)
                .descriptor_type(vk::DescriptorType::STORAGE_BUFFER)
                .buffer_info(&triangle_info),
            vk::WriteDescriptorSet::default()
                .dst_set(descriptor_set)
                .dst_binding(3)
                .descriptor_type(vk::DescriptorType::STORAGE_BUFFER)
                .buffer_info(&bvh_info),
            vk::WriteDescriptorSet::default()
                .dst_set(descriptor_set)
                .dst_binding(4)
                .descriptor_type(vk::DescriptorType::STORAGE_BUFFER)
                .buffer_info(&material_info),
            vk::WriteDescriptorSet::default()
                .dst_set(descriptor_set)
                .dst_binding(5)
                .descriptor_type(vk::DescriptorType::COMBINED_IMAGE_SAMPLER)
                .image_info(&env_info),
            vk::WriteDescriptorSet::default()
                .dst_set(descriptor_set)
                .dst_binding(6)
                .descriptor_type(vk::DescriptorType::COMBINED_IMAGE_SAMPLER)
                .image_info(&tex_array_info),
        ];
        unsafe { device.update_descriptor_sets(&writes, &[]) };

        Ok(RenderResources {
            pipeline,
            pipeline_layout,
            descriptor_set_layout,
            descriptor_pool,
            descriptor_set,
            ubo_buffer,
            ubo_memory,
            ubo_mapped,
            staging_buffer,
            staging_memory,
            accum_image,
            accum_memory,
            accum_view,
        })
    }

    // ── Per-frame UBO (C++: updateUBO) ───────────────────────────────────

    fn update_ubo(&mut self) {
        let scene = self.scene.as_ref().expect("scene set");
        let render = self.render.as_ref().expect("render resources created");

        let aspect = self.config.width as f32 / self.config.height as f32;
        let ubo = PathTraceUbo {
            camera_inv_view: self.camera.view_matrix().inverse(),
            camera_inv_proj: self.camera.projection_matrix(aspect).inverse(),
            camera_position: self.camera.position.extend(1.0),
            light_direction: Vec3::new(-0.5, -1.0, -0.3).normalize().extend(1.0),
            light_color: Vec4::new(1.0, 0.98, 0.95, 1.0),
            // x = hasEnvMap, y = intensity, z = rotation (C++ layout).
            env_map_info: match &self.env_map {
                Some(env) if env.is_loaded() => {
                    Vec4::new(1.0, self.env_intensity, self.env_rotation, 0.0)
                }
                _ => Vec4::new(0.0, 1.0, 0.0, 0.0),
            },
            clip_plane: self.clip_plane,
            frame_index: self.frame_index,
            sample_count: self.current_sample,
            max_bounces: self.config.max_bounces,
            triangle_count: scene.triangles.len() as u32,
            node_count: scene.nodes.len() as u32,
            material_count: scene.materials.len() as u32,
            enable_nee: self.config.enable_nee as u32,
            enable_rr: self.config.enable_rr as u32,
            rr_start_depth: self.config.rr_start_depth,
            exposure: self.config.exposure,
            tonemap_mode: self.config.tonemap_mode,
            width: self.config.width,
            height: self.config.height,
            enable_clipping: self.enable_clipping as u32,
            uv_scale: self.uv_scale,
            _pad: [0],
        };
        unsafe {
            std::ptr::copy_nonoverlapping(
                as_bytes(&ubo).as_ptr(),
                render.ubo_mapped.cast::<u8>(),
                std::mem::size_of::<PathTraceUbo>(),
            );
        }
    }

    // ── Result readback / filtering / output ─────────────────────────────

    /// Copy the accumulation image to host memory and normalize by sample
    /// count (C++: `downloadResult`).
    fn download_result(&mut self) -> Result<()> {
        let render = self.render.as_ref().unwrap();
        let device = self.ctx.device();
        let cmd = self.ctx.begin_single_time_commands()?;

        let range = vk::ImageSubresourceRange {
            aspect_mask: vk::ImageAspectFlags::COLOR,
            base_mip_level: 0,
            level_count: 1,
            base_array_layer: 0,
            layer_count: 1,
        };
        // GENERAL → TRANSFER_SRC
        let to_transfer = vk::ImageMemoryBarrier::default()
            .old_layout(vk::ImageLayout::GENERAL)
            .new_layout(vk::ImageLayout::TRANSFER_SRC_OPTIMAL)
            .src_queue_family_index(vk::QUEUE_FAMILY_IGNORED)
            .dst_queue_family_index(vk::QUEUE_FAMILY_IGNORED)
            .image(render.accum_image)
            .subresource_range(range)
            .src_access_mask(vk::AccessFlags::SHADER_WRITE)
            .dst_access_mask(vk::AccessFlags::TRANSFER_READ);
        unsafe {
            device.cmd_pipeline_barrier(
                cmd,
                vk::PipelineStageFlags::COMPUTE_SHADER,
                vk::PipelineStageFlags::TRANSFER,
                vk::DependencyFlags::empty(),
                &[],
                &[],
                &[to_transfer],
            );
            let region = vk::BufferImageCopy::default()
                .image_subresource(vk::ImageSubresourceLayers {
                    aspect_mask: vk::ImageAspectFlags::COLOR,
                    mip_level: 0,
                    base_array_layer: 0,
                    layer_count: 1,
                })
                .image_extent(vk::Extent3D {
                    width: self.config.width,
                    height: self.config.height,
                    depth: 1,
                });
            device.cmd_copy_image_to_buffer(
                cmd,
                render.accum_image,
                vk::ImageLayout::TRANSFER_SRC_OPTIMAL,
                render.staging_buffer,
                &[region],
            );
            // TRANSFER_SRC → GENERAL
            let to_general = vk::ImageMemoryBarrier::default()
                .old_layout(vk::ImageLayout::TRANSFER_SRC_OPTIMAL)
                .new_layout(vk::ImageLayout::GENERAL)
                .src_queue_family_index(vk::QUEUE_FAMILY_IGNORED)
                .dst_queue_family_index(vk::QUEUE_FAMILY_IGNORED)
                .image(render.accum_image)
                .subresource_range(range)
                .src_access_mask(vk::AccessFlags::TRANSFER_READ)
                .dst_access_mask(vk::AccessFlags::SHADER_WRITE);
            device.cmd_pipeline_barrier(
                cmd,
                vk::PipelineStageFlags::TRANSFER,
                vk::PipelineStageFlags::COMPUTE_SHADER,
                vk::DependencyFlags::empty(),
                &[],
                &[],
                &[to_general],
            );
        }
        self.ctx.end_single_time_commands(cmd)?;

        let pixel_count = (self.config.width * self.config.height) as usize;
        self.hdr_pixels.resize(pixel_count * 4, 0.0);
        unsafe {
            let data = device.map_memory(
                render.staging_memory,
                0,
                vk::WHOLE_SIZE,
                vk::MemoryMapFlags::empty(),
            )?;
            std::ptr::copy_nonoverlapping(
                data.cast::<f32>(),
                self.hdr_pixels.as_mut_ptr(),
                pixel_count * 4,
            );
            device.unmap_memory(render.staging_memory);
        }

        // Normalize by sample count.
        let inv_samples = 1.0 / self.current_sample.max(1) as f32;
        for px in &mut self.hdr_pixels {
            *px *= inv_samples;
        }
        Ok(())
    }

    /// 3×3 edge-aware CPU filter, verbatim from C++ `applyDenoising`
    /// (luminance-weighted bilateral-ish). OIDN remains future work upstream.
    fn apply_denoising(&mut self) {
        let (w, h) = (self.config.width as usize, self.config.height as usize);
        let mut filtered = vec![0.0f32; w * h * 4];
        let lum = |c: Vec3| 0.2126 * c.x + 0.7152 * c.y + 0.0722 * c.z;

        for y in 0..h {
            for x in 0..w {
                let idx = (y * w + x) * 4;
                let center = Vec3::new(
                    self.hdr_pixels[idx],
                    self.hdr_pixels[idx + 1],
                    self.hdr_pixels[idx + 2],
                );
                let center_lum = lum(center);

                let mut sum = Vec3::ZERO;
                let mut total_weight = 0.0f32;
                for dy in -1i32..=1 {
                    for dx in -1i32..=1 {
                        let nx = (x as i32 + dx).clamp(0, w as i32 - 1) as usize;
                        let ny = (y as i32 + dy).clamp(0, h as i32 - 1) as usize;
                        let nidx = (ny * w + nx) * 4;
                        let neighbor = Vec3::new(
                            self.hdr_pixels[nidx],
                            self.hdr_pixels[nidx + 1],
                            self.hdr_pixels[nidx + 2],
                        );
                        let lum_diff = (center_lum - lum(neighbor)).abs();
                        let mut weight = (-lum_diff * 10.0).exp();
                        let dist = ((dx * dx + dy * dy) as f32).sqrt();
                        weight *= (-dist * 0.5).exp();
                        sum += neighbor * weight;
                        total_weight += weight;
                    }
                }
                let result = sum / total_weight.max(0.0001);
                filtered[idx] = result.x;
                filtered[idx + 1] = result.y;
                filtered[idx + 2] = result.z;
                filtered[idx + 3] = self.hdr_pixels[idx + 3];
            }
        }
        self.hdr_pixels = filtered;
    }

    /// Exposure → tonemap (Reinhard / ACES / Uncharted2) → gamma → 8-bit.
    /// Verbatim from C++ `tonemapResult` (writes `self.ldr_pixels`).
    fn tonemap_result(&mut self) {
        let pixel_count = (self.config.width * self.config.height) as usize;
        let mut ldr = vec![0u8; pixel_count * 4];
        let exposure = self.config.exposure;

        for i in 0..pixel_count {
            let hdr = Vec3::new(
                self.hdr_pixels[i * 4],
                self.hdr_pixels[i * 4 + 1],
                self.hdr_pixels[i * 4 + 2],
            ) * exposure;

            let mapped = match self.config.tonemap_mode {
                0 => hdr / (hdr + Vec3::ONE), // Reinhard
                2 => {
                    // Uncharted2
                    fn tonemap(x: Vec3) -> Vec3 {
                        const A: f32 = 0.15;
                        const B: f32 = 0.50;
                        const C: f32 = 0.10;
                        const D: f32 = 0.20;
                        const E: f32 = 0.02;
                        const F: f32 = 0.30;
                        ((x * (A * x + Vec3::splat(C * B)) + Vec3::splat(D * E))
                            / (x * (A * x + Vec3::splat(B)) + Vec3::splat(D * F)))
                            - Vec3::splat(E / F)
                    }
                    const W: f32 = 11.2;
                    tonemap(hdr * 2.0) / tonemap(Vec3::splat(W))
                }
                _ => {
                    // ACES (default, mode 1)
                    const A: f32 = 2.51;
                    const B: f32 = 0.03;
                    const C: f32 = 2.43;
                    const D: f32 = 0.59;
                    const E: f32 = 0.14;
                    ((hdr * (A * hdr + Vec3::splat(B)))
                        / (hdr * (C * hdr + Vec3::splat(D)) + Vec3::splat(E)))
                    .clamp(Vec3::ZERO, Vec3::ONE)
                }
            };

            // Gamma correction.
            let gamma = mapped.powf(1.0 / 2.2);
            ldr[i * 4] = (gamma.x * 255.0).clamp(0.0, 255.0) as u8;
            ldr[i * 4 + 1] = (gamma.y * 255.0).clamp(0.0, 255.0) as u8;
            ldr[i * 4 + 2] = (gamma.z * 255.0).clamp(0.0, 255.0) as u8;
            ldr[i * 4 + 3] = 255;
        }
        self.ldr_pixels = ldr;
    }

    /// Save the LDR result as PNG. Re-tonemaps first if `exposure` differs
    /// from the config (as C++ `savePNG`). The shader already handles the
    /// Vulkan Y-flip, so rows are written top-to-bottom.
    pub fn save_png(&mut self, path: &Path, exposure: f32) -> Result<()> {
        if self.hdr_pixels.is_empty() {
            bail!("no result to save");
        }
        if (exposure - self.config.exposure).abs() > 0.01 {
            let old = self.config.exposure;
            self.config.exposure = exposure;
            self.tonemap_result();
            self.config.exposure = old;
        } else if self.ldr_pixels.is_empty() {
            self.tonemap_result();
        }

        image::save_buffer(
            path,
            &self.ldr_pixels,
            self.config.width,
            self.config.height,
            image::ExtendedColorType::Rgba8,
        )
        .context("failed to write PNG")?;
        tracing::info!(path = %path.display(), "[PathTracer] saved PNG");
        Ok(())
    }

    /// Save the HDR result (Radiance .hdr; `.exr` paths are rewritten, as
    /// C++ `saveEXR` does).
    pub fn save_hdr(&self, path: &Path) -> Result<()> {
        if self.hdr_pixels.is_empty() {
            bail!("no HDR result to save");
        }
        let path = match path.extension().and_then(|e| e.to_str()) {
            Some("exr") => path.with_extension("hdr"),
            _ => path.to_path_buf(),
        };
        let pixel_count = (self.config.width * self.config.height) as usize;
        let mut rgb = vec![0.0f32; pixel_count * 3];
        for i in 0..pixel_count {
            rgb[i * 3] = self.hdr_pixels[i * 4];
            rgb[i * 3 + 1] = self.hdr_pixels[i * 4 + 1];
            rgb[i * 3 + 2] = self.hdr_pixels[i * 4 + 2];
        }
        let img = image::ImageBuffer::<image::Rgb<f32>, _>::from_raw(
            self.config.width,
            self.config.height,
            rgb,
        )
        .ok_or_else(|| anyhow!("HDR buffer size mismatch"))?;
        img.save(&path).context("failed to write HDR")?;
        tracing::info!(path = %path.display(), "[PathTracer] saved HDR");
        Ok(())
    }

    // ── Cleanup (C++: cleanupRenderResources / cleanup) ──────────────────

    /// Destroy render resources but keep scene buffers.
    fn cleanup_render_resources(&mut self) {
        if self.render.is_none() {
            return;
        }
        self.ctx.wait_idle();
        let render = self.render.take().unwrap();
        let device = self.ctx.device();
        unsafe {
            if !render.ubo_mapped.is_null() {
                device.unmap_memory(render.ubo_memory);
            }
            device.destroy_buffer(render.ubo_buffer, None);
            device.free_memory(render.ubo_memory, None);
            device.destroy_buffer(render.staging_buffer, None);
            device.free_memory(render.staging_memory, None);
            device.destroy_image_view(render.accum_view, None);
            device.destroy_image(render.accum_image, None);
            device.free_memory(render.accum_memory, None);
            device.destroy_pipeline(render.pipeline, None);
            device.destroy_pipeline_layout(render.pipeline_layout, None);
            device.destroy_descriptor_set_layout(render.descriptor_set_layout, None);
            device.destroy_descriptor_pool(render.descriptor_pool, None);
        }
    }

    fn destroy_scene_buffers(&mut self) {
        if let Some(scene) = self.scene_buffers.take() {
            let device = self.ctx.device();
            unsafe {
                device.destroy_buffer(scene.triangle_buffer, None);
                device.free_memory(scene.triangle_memory, None);
                device.destroy_buffer(scene.bvh_buffer, None);
                device.free_memory(scene.bvh_memory, None);
                device.destroy_buffer(scene.material_buffer, None);
                device.free_memory(scene.material_memory, None);
            }
        }
    }
}

impl Drop for PathTracer<'_> {
    fn drop(&mut self) {
        self.cleanup_render_resources();
        self.destroy_scene_buffers();
        // Placeholders + env map die before the context (field order is
        // irrelevant — the context is a borrow and outlives `self`).
        self.placeholder_cube.take();
        self.env_map.take();
        if let Some(tex) = self.placeholder_tex_array.take() {
            self.ctx.wait_idle();
            tex.destroy(self.ctx);
        }
    }
}
