//! Real-time raster renderer — the interactive "game" half of the viewer.
//!
//! Port of the C++ `Renderer` core draw path (`renderer.cpp`), reduced to
//! what the demo milestone needs: one graphics pipeline (`simple.vert/frag`
//! — a minimal stand-in for `structural.*` until the texture/shadow/IBL
//! stack is re-added; see questions.md A4), MSAA + depth render pass
//! straight to the swapchain, per-frame uniform buffers, push-constant
//! model/color per draw.
//!
//! Conventions carried over from the C++:
//! - Positive viewport height with `proj[1][1] *= -1` applied by the
//!   caller (renderer.cpp:1507) — NOT inside the camera.
//! - Back-face culling off (renderer.cpp:1083 tolerates the kernel's mixed
//!   winding conventions).

use anyhow::{Context as _, Result};
use ash::vk;
use glam::{Mat4, Vec3, Vec4};

use archengine_geometry::domain::mesh::Vertex;
use archengine_geometry::mesh_gen::PrimitiveMesh;

use super::context::VulkanContext;
use super::environment::EnvironmentMap;
use super::ubo::SharedUbo;
#[cfg(feature = "ui")]
use crate::ui::overlay::UiFrame;
use crate::camera::Camera;

const SIMPLE_VERT_SPV: &[u8] =
    include_bytes!(concat!(env!("OUT_DIR"), "/spirv/simple.vert.spv"));
const SIMPLE_FRAG_SPV: &[u8] =
    include_bytes!(concat!(env!("OUT_DIR"), "/spirv/simple.frag.spv"));
const SKY_VERT_SPV: &[u8] =
    include_bytes!(concat!(env!("OUT_DIR"), "/spirv/sky.vert.spv"));
const SKY_FRAG_SPV: &[u8] =
    include_bytes!(concat!(env!("OUT_DIR"), "/spirv/sky.frag.spv"));

/// GPU vertex — the 48-byte layout the shaders and the C++
/// `Vertex::getAttributeDescriptions` expect. The CPU-side
/// [`archengine_geometry::domain::mesh::Vertex`] uses glam types (padded);
/// convert with [`From`].
#[repr(C)]
#[derive(Debug, Clone, Copy)]
pub struct GpuVertex {
    pub position: [f32; 3],
    pub normal: [f32; 3],
    pub color: [f32; 3],
    pub tex_coord: [f32; 2],
    pub stress: f32,
}

const _: () = assert!(std::mem::size_of::<GpuVertex>() == 48);

impl From<&Vertex> for GpuVertex {
    fn from(v: &Vertex) -> Self {
        Self {
            position: v.position.to_array(),
            normal: v.normal.to_array(),
            color: v.color.to_array(),
            tex_coord: v.tex_coord.to_array(),
            stress: v.stress,
        }
    }
}

/// Matches `simple.vert`'s `SimpleUbo` block (std140).
#[repr(C)]
#[derive(Debug, Clone, Copy)]
pub struct SimpleUbo {
    pub view: Mat4,
    pub proj: Mat4,
    /// xyz = sun direction, w = intensity (same default as the path tracer).
    pub light_direction: Vec4,
}

/// Matches `simple.vert`'s push-constant block.
#[repr(C)]
#[derive(Debug, Clone, Copy)]
pub struct PushConstants {
    pub model: Mat4,
    /// RGB = albedo override, A = stress (C++ convention).
    pub color: Vec4,
}

/// An uploaded mesh: device-local vertex + index buffers.
pub struct GpuMesh {
    vertex_buffer: vk::Buffer,
    vertex_memory: vk::DeviceMemory,
    index_buffer: vk::Buffer,
    index_memory: vk::DeviceMemory,
    pub index_count: u32,
}

/// One draw call: mesh + model transform + color/stress override.
/// A zero-ish color RGB falls back to the vertex colors (as
/// `structural.vert`).
pub struct DrawItem<'a> {
    pub mesh: &'a GpuMesh,
    pub model: Mat4,
    pub color: Vec4,
}

struct FrameSync {
    image_available: vk::Semaphore,
    render_finished: vk::Semaphore,
    in_flight: vk::Fence,
    command_buffer: vk::CommandBuffer,
    ubo_buffer: vk::Buffer,
    ubo_memory: vk::DeviceMemory,
    ubo_mapped: *mut std::ffi::c_void,
    sky_ubo_buffer: vk::Buffer,
    sky_ubo_memory: vk::DeviceMemory,
    sky_ubo_mapped: *mut std::ffi::c_void,
}

unsafe impl Send for FrameSync {}

/// The raster renderer. Holds a raw pointer to the windowed
/// [`VulkanContext`], mirroring the C++ (`Renderer` keeps `VulkanContext*`).
///
/// # Safety invariants (upheld by the caller, e.g. `app::App`)
/// - the context must outlive the renderer (drop renderer first), and
/// - it must not be moved (store it in a `Box`),
/// - while the renderer is alive the caller must not create other
///   references that alias across renderer calls — the event loop is
///   single-threaded, so a `&mut` handed to [`Renderer::new`] suffices.
pub struct Renderer {
    ctx: *mut VulkanContext,
    render_pass: vk::RenderPass,
    descriptor_set_layout: vk::DescriptorSetLayout,
    descriptor_pool: vk::DescriptorPool,
    pipeline_layout: vk::PipelineLayout,
    pipeline: vk::Pipeline,
    framebuffers: Vec<vk::Framebuffer>,
    frames: Vec<FrameSync>,
    descriptor_sets: Vec<vk::DescriptorSet>,
    current_frame: usize,

    // Sky pass (sky.vert/frag, verbatim): fullscreen triangle at the far
    // plane, procedural gradient or env cubemap (sunDirection.w selects).
    sky_ds_layout: vk::DescriptorSetLayout,
    sky_pipeline_layout: vk::PipelineLayout,
    sky_pipeline: vk::Pipeline,
    sky_descriptor_pool: vk::DescriptorPool,
    sky_descriptor_sets: Vec<vk::DescriptorSet>,
    /// 1×1 placeholder so sky binding 1 is always valid. Only read during
    /// setup — kept alive by this field for the renderer's lifetime.
    #[allow(dead_code)]
    default_cube: EnvironmentMap,
    /// xyz = sun direction (matches `SimpleUbo::light_direction`), w = use HDR cubemap.
    sky_push: Vec4,
    /// Draw the sky pass (UI: Render Settings → Environment → Draw sky).
    sky_enabled: bool,

    /// egui overlay (dedicated 1-sample pass over the resolved swapchain
    /// image — see `ui::overlay`). Created lazily by [`Self::init_ui`].
    #[cfg(feature = "ui")]
    ui: Option<crate::ui::overlay::UiOverlay>,
}

impl Renderer {
    pub fn new(ctx: &mut VulkanContext) -> Result<Self> {
        let device = ctx.device();
        let render_pass = create_render_pass(ctx)?;
        let descriptor_set_layout = create_descriptor_set_layout(device)?;
        let descriptor_pool = create_descriptor_pool(device, ctx.max_frames_in_flight())?;
        let (pipeline_layout, pipeline) =
            create_pipeline(ctx, render_pass, descriptor_set_layout)?;

        // Per-frame uniform buffers (persistently mapped) + sync + commands.
        let mut frames = Vec::new();
        let cmd_alloc = vk::CommandBufferAllocateInfo::default()
            .command_pool(ctx.command_pool())
            .level(vk::CommandBufferLevel::PRIMARY)
            .command_buffer_count(ctx.max_frames_in_flight());
        let command_buffers = unsafe { device.allocate_command_buffers(&cmd_alloc) }
            .context("allocate frame command buffers")?;
        for i in 0..ctx.max_frames_in_flight() {
            let (ubo_buffer, ubo_memory) = ctx.create_buffer(
                std::mem::size_of::<SimpleUbo>() as vk::DeviceSize,
                vk::BufferUsageFlags::UNIFORM_BUFFER,
                vk::MemoryPropertyFlags::HOST_VISIBLE | vk::MemoryPropertyFlags::HOST_COHERENT,
            )?;
            let ubo_mapped = unsafe {
                device.map_memory(
                    ubo_memory,
                    0,
                    std::mem::size_of::<SimpleUbo>() as vk::DeviceSize,
                    vk::MemoryMapFlags::empty(),
                )?
            };
            let (sky_ubo_buffer, sky_ubo_memory) = ctx.create_buffer(
                std::mem::size_of::<SharedUbo>() as vk::DeviceSize,
                vk::BufferUsageFlags::UNIFORM_BUFFER,
                vk::MemoryPropertyFlags::HOST_VISIBLE | vk::MemoryPropertyFlags::HOST_COHERENT,
            )?;
            let sky_ubo_mapped = unsafe {
                device.map_memory(
                    sky_ubo_memory,
                    0,
                    std::mem::size_of::<SharedUbo>() as vk::DeviceSize,
                    vk::MemoryMapFlags::empty(),
                )?
            };
            let semaphore_info = vk::SemaphoreCreateInfo::default();
            let fence_info =
                vk::FenceCreateInfo::default().flags(vk::FenceCreateFlags::SIGNALED);
            frames.push(FrameSync {
                image_available: unsafe { device.create_semaphore(&semaphore_info, None) }?,
                render_finished: unsafe { device.create_semaphore(&semaphore_info, None) }?,
                in_flight: unsafe { device.create_fence(&fence_info, None) }?,
                command_buffer: command_buffers[i as usize],
                ubo_buffer,
                ubo_memory,
                ubo_mapped,
                sky_ubo_buffer,
                sky_ubo_memory,
                sky_ubo_mapped,
            });
        }

        // One descriptor set per frame, each pointing at its own UBO.
        let layouts = vec![descriptor_set_layout; ctx.max_frames_in_flight() as usize];
        let set_alloc = vk::DescriptorSetAllocateInfo::default()
            .descriptor_pool(descriptor_pool)
            .set_layouts(&layouts);
        let descriptor_sets = unsafe { device.allocate_descriptor_sets(&set_alloc) }
            .context("allocate raster descriptor sets")?;
        for (i, &set) in descriptor_sets.iter().enumerate() {
            let info = [vk::DescriptorBufferInfo::default()
                .buffer(frames[i].ubo_buffer)
                .offset(0)
                .range(std::mem::size_of::<SimpleUbo>() as vk::DeviceSize)];
            let write = [vk::WriteDescriptorSet::default()
                .dst_set(set)
                .dst_binding(0)
                .descriptor_type(vk::DescriptorType::UNIFORM_BUFFER)
                .buffer_info(&info)];
            unsafe { device.update_descriptor_sets(&write, &[]) };
        }

        // ── Sky pass resources ──────────────────────────────────────────
        // Placeholder cubemap keeps sky binding 1 valid until a real HDRI
        // is bound via `set_environment`.
        let mut default_cube = EnvironmentMap::new(ctx)?;
        default_cube.create_solid([0.05, 0.07, 0.1])?;
        let sky_push = Vec3::new(-0.5, -1.0, -0.3).normalize().extend(0.0);

        let sky_ds_layout = create_sky_descriptor_set_layout(device)?;
        let (sky_pipeline_layout, sky_pipeline) =
            create_sky_pipeline(ctx, render_pass, sky_ds_layout)?;
        let sky_pool_sizes = [
            vk::DescriptorPoolSize::default()
                .ty(vk::DescriptorType::UNIFORM_BUFFER)
                .descriptor_count(ctx.max_frames_in_flight()),
            vk::DescriptorPoolSize::default()
                .ty(vk::DescriptorType::COMBINED_IMAGE_SAMPLER)
                .descriptor_count(ctx.max_frames_in_flight()),
        ];
        let sky_pool_info = vk::DescriptorPoolCreateInfo::default()
            .pool_sizes(&sky_pool_sizes)
            .max_sets(ctx.max_frames_in_flight());
        let sky_descriptor_pool = unsafe { device.create_descriptor_pool(&sky_pool_info, None) }
            .context("sky descriptor pool")?;
        let sky_layouts = vec![sky_ds_layout; ctx.max_frames_in_flight() as usize];
        let sky_alloc = vk::DescriptorSetAllocateInfo::default()
            .descriptor_pool(sky_descriptor_pool)
            .set_layouts(&sky_layouts);
        let sky_descriptor_sets = unsafe { device.allocate_descriptor_sets(&sky_alloc) }
            .context("sky descriptor sets")?;
        for (i, &set) in sky_descriptor_sets.iter().enumerate() {
            let ubo_info = [vk::DescriptorBufferInfo::default()
                .buffer(frames[i].sky_ubo_buffer)
                .offset(0)
                .range(std::mem::size_of::<SharedUbo>() as vk::DeviceSize)];
            let env_info = [default_cube.descriptor_info()];
            let writes = [
                vk::WriteDescriptorSet::default()
                    .dst_set(set)
                    .dst_binding(0)
                    .descriptor_type(vk::DescriptorType::UNIFORM_BUFFER)
                    .buffer_info(&ubo_info),
                vk::WriteDescriptorSet::default()
                    .dst_set(set)
                    .dst_binding(1)
                    .descriptor_type(vk::DescriptorType::COMBINED_IMAGE_SAMPLER)
                    .image_info(&env_info),
            ];
            unsafe { device.update_descriptor_sets(&writes, &[]) };
        }

        let mut renderer = Self {
            ctx: ctx as *mut VulkanContext,
            render_pass,
            descriptor_set_layout,
            descriptor_pool,
            pipeline_layout,
            pipeline,
            framebuffers: Vec::new(),
            frames,
            descriptor_sets,
            current_frame: 0,
            sky_ds_layout,
            sky_pipeline_layout,
            sky_pipeline,
            sky_descriptor_pool,
            sky_descriptor_sets,
            default_cube,
            sky_push,
            sky_enabled: true,
            #[cfg(feature = "ui")]
            ui: None,
        };
        renderer.create_framebuffers()?;
        Ok(renderer)
    }

    /// Shared access to the context. Valid per the invariants on [`Renderer`].
    #[allow(clippy::wrong_self_convention)]
    fn ctx(&self) -> &VulkanContext {
        // SAFETY: caller guarantees the context outlives the renderer and
        // is not moved; calls are single-threaded.
        unsafe { &*self.ctx }
    }

    /// Exclusive access (swapchain recreation).
    #[allow(clippy::wrong_self_convention)]
    fn ctx_mut(&mut self) -> &mut VulkanContext {
        // SAFETY: `draw_frame`/`recreate` take `&mut self`, so no other
        // renderer method is active; the caller holds no live references
        // into the context while the renderer is in use.
        unsafe { &mut *self.ctx }
    }

    /// Bind an environment cubemap for the sky pass (binding 1 of the sky
    /// descriptor sets). `use_hdr` selects the cubemap path in `sky.frag`;
    /// `false` keeps the procedural gradient sky (the cubemap stays bound
    /// but unused). The caller keeps the [`EnvironmentMap`] alive.
    pub fn set_environment(&mut self, info: vk::DescriptorImageInfo, use_hdr: bool) {
        self.ctx().wait_idle();
        self.sky_push.w = if use_hdr { 1.0 } else { 0.0 };
        let image_info = [info];
        for &set in &self.sky_descriptor_sets {
            let write = [vk::WriteDescriptorSet::default()
                .dst_set(set)
                .dst_binding(1)
                .descriptor_type(vk::DescriptorType::COMBINED_IMAGE_SAMPLER)
                .image_info(&image_info)];
            unsafe { self.ctx().device().update_descriptor_sets(&write, &[]) };
        }
    }

    /// Enable/disable the sky pass (UI Render Settings → Draw sky).
    pub fn set_sky_enabled(&mut self, enabled: bool) {
        self.sky_enabled = enabled;
    }

    /// Create the egui overlay: dedicated 1-sample render pass + egui
    /// renderer. Call once after [`Renderer::new`] when the `ui` feature
    /// is on. Must be called again only if the context is rebuilt.
    #[cfg(feature = "ui")]
    pub fn init_ui(&mut self) -> Result<()> {
        let in_flight = self.frames.len().max(1);
        let overlay = crate::ui::overlay::UiOverlay::new(self.ctx(), in_flight)?;
        self.ui = Some(overlay);
        tracing::info!("[Renderer] egui overlay initialized");
        Ok(())
    }

    /// Upload a mesh to device-local memory (staging copy, as the C++).
    pub fn upload_mesh(&self, mesh: &PrimitiveMesh) -> Result<GpuMesh> {
        let vertices: Vec<GpuVertex> = mesh.vertices.iter().map(GpuVertex::from).collect();
        let device = self.ctx().device();

        let upload = |data: &[u8],
                      usage: vk::BufferUsageFlags|
         -> Result<(vk::Buffer, vk::DeviceMemory)> {
            let size = data.len() as vk::DeviceSize;
            let (staging, staging_mem) = self.ctx().create_buffer(
                size,
                vk::BufferUsageFlags::TRANSFER_SRC,
                vk::MemoryPropertyFlags::HOST_VISIBLE | vk::MemoryPropertyFlags::HOST_COHERENT,
            )?;
            unsafe {
                let mapped =
                    device.map_memory(staging_mem, 0, size, vk::MemoryMapFlags::empty())?;
                std::ptr::copy_nonoverlapping(data.as_ptr(), mapped.cast::<u8>(), data.len());
                device.unmap_memory(staging_mem);
            }
            let (buffer, memory) = self.ctx().create_buffer(
                size,
                usage | vk::BufferUsageFlags::TRANSFER_DST,
                vk::MemoryPropertyFlags::DEVICE_LOCAL,
            )?;
            self.ctx().copy_buffer(staging, buffer, size)?;
            unsafe {
                device.destroy_buffer(staging, None);
                device.free_memory(staging_mem, None);
            }
            Ok((buffer, memory))
        };

        let as_bytes = |v: &[GpuVertex]| unsafe {
            std::slice::from_raw_parts(v.as_ptr().cast::<u8>(), std::mem::size_of_val(v))
        };
        let idx_bytes = unsafe {
            std::slice::from_raw_parts(
                mesh.indices.as_ptr().cast::<u8>(),
                std::mem::size_of_val(&mesh.indices[..]),
            )
        };

        let (vertex_buffer, vertex_memory) =
            upload(as_bytes(&vertices), vk::BufferUsageFlags::VERTEX_BUFFER)?;
        let (index_buffer, index_memory) =
            upload(idx_bytes, vk::BufferUsageFlags::INDEX_BUFFER)?;
        Ok(GpuMesh {
            vertex_buffer,
            vertex_memory,
            index_buffer,
            index_memory,
            index_count: mesh.indices.len() as u32,
        })
    }

    /// Draw one frame. `draws` are rendered front-to-back in order.
    /// Returns `Ok(true)` if the swapchain was recreated (window resized).
    pub fn draw_frame(
        &mut self,
        camera: &Camera,
        draws: &[DrawItem],
        #[cfg(feature = "ui")] ui_frame: Option<UiFrame>,
    ) -> Result<bool> {
        let device = self.ctx().device().clone();
        let frame = &self.frames[self.current_frame];

        unsafe {
            device.wait_for_fences(&[frame.in_flight], true, u64::MAX)?;
        }

        // The frame slot's previous work has completed — safe to free egui
        // textures that aged out of the in-flight window.
        #[cfg(feature = "ui")]
        if let Some(overlay) = &mut self.ui {
            overlay.flush_due_frees();
        }

        // Raw-pointer read: not tied to a `&self` borrow, so it can coexist
        // with `&mut self.ui` below (same pattern as environment.rs).
        #[cfg(feature = "ui")]
        let ui_ctx: &VulkanContext = unsafe { &*self.ctx };

        // Upload egui textures (font atlas on frame 1) before recording.
        #[cfg(feature = "ui")]
        if let (Some(overlay), Some(frame_data)) = (&mut self.ui, &ui_frame) {
            overlay.set_textures(ui_ctx, &frame_data.textures_delta)?;
        }

        let acquire = unsafe {
            self.ctx().swapchain_loader().acquire_next_image(
                self.ctx().swapchain(),
                u64::MAX,
                frame.image_available,
                vk::Fence::null(),
            )
        };
        let image_index = match acquire {
            Ok((index, _)) => index,
            Err(vk::Result::ERROR_OUT_OF_DATE_KHR) => {
                self.recreate()?;
                return Ok(true);
            }
            Err(e) => return Err(e.into()),
        };

        unsafe { device.reset_fences(&[frame.in_flight])? };

        // Upload this frame's UBO. Y-flip at the call site (C++ convention).
        let extent = self.ctx().swapchain_extent();
        let aspect = extent.width as f32 / extent.height as f32;
        let mut proj = camera.projection_matrix(aspect);
        proj.y_axis.y *= -1.0; // Vulkan Y-flip (renderer.cpp:1507)
        let ubo = SimpleUbo {
            view: camera.view_matrix(),
            proj,
            light_direction: Vec3::new(-0.5, -1.0, -0.3).normalize().extend(1.0),
        };
        unsafe {
            std::ptr::copy_nonoverlapping(
                (&ubo as *const SimpleUbo).cast::<u8>(),
                frame.ubo_mapped.cast::<u8>(),
                std::mem::size_of::<SimpleUbo>(),
            );
        }

        // Sky UBO — full shared layout; only the fields sky.vert/frag read.
        let sky_ubo = SharedUbo {
            view: ubo.view,
            proj: ubo.proj,
            light_direction: self.sky_push,
            output_linear_hdr: 0,
            exposure: 1.0,
            ..Default::default()
        };
        unsafe {
            std::ptr::copy_nonoverlapping(
                (&sky_ubo as *const SharedUbo).cast::<u8>(),
                frame.sky_ubo_mapped.cast::<u8>(),
                std::mem::size_of::<SharedUbo>(),
            );
        }

        // Record.
        let cmd = frame.command_buffer;
        unsafe {
            device.reset_command_buffer(cmd, vk::CommandBufferResetFlags::empty())?;
            device.begin_command_buffer(cmd, &vk::CommandBufferBeginInfo::default())?;
        }

        let clear = [
            // Sky-ish clear, matching the C++ default background.
            vk::ClearValue {
                color: vk::ClearColorValue {
                    float32: [0.53, 0.71, 0.92, 1.0],
                },
            },
            vk::ClearValue {
                depth_stencil: vk::ClearDepthStencilValue {
                    depth: 1.0,
                    stencil: 0,
                },
            },
            vk::ClearValue {
                color: vk::ClearColorValue {
                    float32: [0.0, 0.0, 0.0, 0.0],
                },
            },
        ];
        let render_area = vk::Rect2D {
            offset: vk::Offset2D { x: 0, y: 0 },
            extent,
        };
        let pass_info = vk::RenderPassBeginInfo::default()
            .render_pass(self.render_pass)
            .framebuffer(self.framebuffers[image_index as usize])
            .render_area(render_area)
            .clear_values(&clear[..self.attachment_count()]);
        unsafe {
            device.cmd_begin_render_pass(cmd, &pass_info, vk::SubpassContents::INLINE);

            let viewport = vk::Viewport {
                x: 0.0,
                y: 0.0,
                width: extent.width as f32,
                height: extent.height as f32,
                min_depth: 0.0,
                max_depth: 1.0,
            };
            device.cmd_set_viewport(cmd, 0, &[viewport]);
            device.cmd_set_scissor(cmd, 0, &[render_area]);

            // Sky first: fullscreen triangle at the far plane, no depth
            // write — the scene draws over it.
            if self.sky_enabled {
                device.cmd_bind_pipeline(cmd, vk::PipelineBindPoint::GRAPHICS, self.sky_pipeline);
            device.cmd_bind_descriptor_sets(
                cmd,
                vk::PipelineBindPoint::GRAPHICS,
                self.sky_pipeline_layout,
                0,
                &[self.sky_descriptor_sets[self.current_frame]],
                &[],
            );
            let sun = [self.sky_push.x, self.sky_push.y, self.sky_push.z, self.sky_push.w];
            device.cmd_push_constants(
                cmd,
                self.sky_pipeline_layout,
                vk::ShaderStageFlags::FRAGMENT,
                0,
                std::slice::from_raw_parts(sun.as_ptr().cast::<u8>(), 16),
            );
            device.cmd_draw(cmd, 3, 1, 0, 0);
            }

            device.cmd_bind_pipeline(cmd, vk::PipelineBindPoint::GRAPHICS, self.pipeline);
            device.cmd_bind_descriptor_sets(
                cmd,
                vk::PipelineBindPoint::GRAPHICS,
                self.pipeline_layout,
                0,
                &[self.descriptor_sets[self.current_frame]],
                &[],
            );

            for draw in draws {
                let push = PushConstants {
                    model: draw.model,
                    color: draw.color,
                };
                let push_bytes = std::slice::from_raw_parts(
                    (&push as *const PushConstants).cast::<u8>(),
                    std::mem::size_of::<PushConstants>(),
                );
                device.cmd_push_constants(
                    cmd,
                    self.pipeline_layout,
                    vk::ShaderStageFlags::VERTEX | vk::ShaderStageFlags::FRAGMENT,
                    0,
                    push_bytes,
                );
                device.cmd_bind_vertex_buffers(cmd, 0, &[draw.mesh.vertex_buffer], &[0]);
                device.cmd_bind_index_buffer(
                    cmd,
                    draw.mesh.index_buffer,
                    0,
                    vk::IndexType::UINT32,
                );
                device.cmd_draw_indexed(cmd, draw.mesh.index_count, 1, 0, 0, 0);
            }

            device.cmd_end_render_pass(cmd);

            // UI overlay: separate 1-sample pass over the resolved image.
            #[cfg(feature = "ui")]
            if let (Some(overlay), Some(frame_data)) = (&mut self.ui, ui_frame) {
                overlay.record(
                    &device,
                    cmd,
                    image_index,
                    extent,
                    frame_data.pixels_per_point,
                    &frame_data.primitives,
                )?;
                overlay.defer_free(frame_data.textures_delta.free.iter().copied().collect());
            }

            device.end_command_buffer(cmd)?;
        }

        // Submit + present.
        let wait_semaphores = [frame.image_available];
        let signal_semaphores = [frame.render_finished];
        let wait_stages = [vk::PipelineStageFlags::COLOR_ATTACHMENT_OUTPUT];
        let command_buffers = [cmd];
        let submit = vk::SubmitInfo::default()
            .wait_semaphores(&wait_semaphores)
            .wait_dst_stage_mask(&wait_stages)
            .command_buffers(&command_buffers)
            .signal_semaphores(&signal_semaphores);
        unsafe { device.queue_submit(self.ctx().graphics_queue(), &[submit], frame.in_flight)? };

        let swapchains = [self.ctx().swapchain()];
        let image_indices = [image_index];
        let present = vk::PresentInfoKHR::default()
            .wait_semaphores(&signal_semaphores)
            .swapchains(&swapchains)
            .image_indices(&image_indices);
        let presented = unsafe {
            self.ctx()
                .swapchain_loader()
                .queue_present(self.ctx().present_queue(), &present)
        };
        match presented {
            Ok(_) => {}
            Err(vk::Result::ERROR_OUT_OF_DATE_KHR | vk::Result::SUBOPTIMAL_KHR) => {
                self.recreate()?;
                self.current_frame =
                    (self.current_frame + 1) % self.frames.len();
                return Ok(true);
            }
            Err(e) => return Err(e.into()),
        }

        self.current_frame = (self.current_frame + 1) % self.frames.len();
        Ok(false)
    }

    /// Recreate swapchain-dependent resources after a resize.
    pub fn recreate(&mut self) -> Result<()> {
        self.ctx_mut().recreate_swapchain()?;
        self.create_framebuffers()?;
        #[cfg(feature = "ui")]
        if let Some(overlay) = &mut self.ui {
            let ui_ctx: &VulkanContext = unsafe { &*self.ctx };
            overlay.recreate_framebuffers(ui_ctx)?;
        }
        Ok(())
    }

    fn attachment_count(&self) -> usize {
        if self.ctx().msaa_samples() != vk::SampleCountFlags::TYPE_1 {
            3 // MSAA color + depth + resolve
        } else {
            2 // color + depth
        }
    }

    fn create_framebuffers(&mut self) -> Result<()> {
        // Clone the device handle so no borrow of `self` outlives this line.
        let device = self.ctx().device().clone();
        unsafe {
            for &fb in &self.framebuffers {
                device.destroy_framebuffer(fb, None);
            }
        }
        self.framebuffers.clear();

        // Copy everything needed from the context up front, so no borrow of
        // `self` is live while `self.framebuffers` is mutated.
        let (extent, msaa, views, msaa_view, depth_view) = {
            let ctx = self.ctx();
            (
                ctx.swapchain_extent(),
                ctx.msaa_samples() != vk::SampleCountFlags::TYPE_1,
                ctx.swapchain_image_views().to_vec(),
                ctx.msaa_color_image_view(),
                ctx.depth_image_view(),
            )
        };
        for view in views {
            let attachments: Vec<vk::ImageView> = if msaa {
                vec![msaa_view, depth_view, view]
            } else {
                vec![view, depth_view]
            };
            let info = vk::FramebufferCreateInfo::default()
                .render_pass(self.render_pass)
                .attachments(&attachments)
                .width(extent.width)
                .height(extent.height)
                .layers(1);
            self.framebuffers
                .push(unsafe { device.create_framebuffer(&info, None) }?);
        }
        Ok(())
    }
}

impl Drop for Renderer {
    fn drop(&mut self) {
        let device = self.ctx().device().clone();
        self.ctx().wait_idle();
        // Overlay render pass + framebuffers first (the egui renderer's own
        // Drop frees its pipeline/textures when the field drops below).
        #[cfg(feature = "ui")]
        {
            let ui_ctx: &VulkanContext = unsafe { &*self.ctx };
            if let Some(overlay) = &mut self.ui {
                overlay.destroy(ui_ctx);
            }
        }
        unsafe {
            for frame in &self.frames {
                device.unmap_memory(frame.ubo_memory);
                device.destroy_buffer(frame.ubo_buffer, None);
                device.free_memory(frame.ubo_memory, None);
                device.unmap_memory(frame.sky_ubo_memory);
                device.destroy_buffer(frame.sky_ubo_buffer, None);
                device.free_memory(frame.sky_ubo_memory, None);
                device.destroy_semaphore(frame.image_available, None);
                device.destroy_semaphore(frame.render_finished, None);
                device.destroy_fence(frame.in_flight, None);
            }
            for &fb in &self.framebuffers {
                device.destroy_framebuffer(fb, None);
            }
            device.destroy_pipeline(self.pipeline, None);
            device.destroy_pipeline_layout(self.pipeline_layout, None);
            device.destroy_descriptor_pool(self.descriptor_pool, None);
            device.destroy_descriptor_set_layout(self.descriptor_set_layout, None);
            device.destroy_pipeline(self.sky_pipeline, None);
            device.destroy_pipeline_layout(self.sky_pipeline_layout, None);
            device.destroy_descriptor_pool(self.sky_descriptor_pool, None);
            device.destroy_descriptor_set_layout(self.sky_ds_layout, None);
            device.destroy_render_pass(self.render_pass, None);
        }
    }
}

impl GpuMesh {
    /// Destroy the GPU buffers (context must outlive the mesh).
    pub fn destroy(self, ctx: &VulkanContext) {
        let device = ctx.device();
        ctx.wait_idle();
        unsafe {
            device.destroy_buffer(self.vertex_buffer, None);
            device.free_memory(self.vertex_memory, None);
            device.destroy_buffer(self.index_buffer, None);
            device.free_memory(self.index_memory, None);
        }
    }
}

// ── Free-function helpers ────────────────────────────────────────────────

fn create_render_pass(ctx: &VulkanContext) -> Result<vk::RenderPass> {
    let device = ctx.device();
    let samples = ctx.msaa_samples();
    let msaa = samples != vk::SampleCountFlags::TYPE_1;

    let mut attachments = Vec::new();
    let color_ref;
    let depth_ref;
    let resolve_ref;

    if msaa {
        // 0: MSAA color, 1: MSAA depth, 2: resolve → swapchain.
        attachments.push(
            vk::AttachmentDescription::default()
                .format(ctx.swapchain_format())
                .samples(samples)
                .load_op(vk::AttachmentLoadOp::CLEAR)
                .store_op(vk::AttachmentStoreOp::STORE)
                .stencil_load_op(vk::AttachmentLoadOp::DONT_CARE)
                .stencil_store_op(vk::AttachmentStoreOp::DONT_CARE)
                .initial_layout(vk::ImageLayout::UNDEFINED)
                .final_layout(vk::ImageLayout::COLOR_ATTACHMENT_OPTIMAL),
        );
        attachments.push(depth_attachment(ctx, samples));
        attachments.push(
            vk::AttachmentDescription::default()
                .format(ctx.swapchain_format())
                .samples(vk::SampleCountFlags::TYPE_1)
                .load_op(vk::AttachmentLoadOp::DONT_CARE)
                .store_op(vk::AttachmentStoreOp::STORE)
                .stencil_load_op(vk::AttachmentLoadOp::DONT_CARE)
                .stencil_store_op(vk::AttachmentStoreOp::DONT_CARE)
                .initial_layout(vk::ImageLayout::UNDEFINED)
                .final_layout(vk::ImageLayout::PRESENT_SRC_KHR),
        );
        color_ref = vk::AttachmentReference {
            attachment: 0,
            layout: vk::ImageLayout::COLOR_ATTACHMENT_OPTIMAL,
        };
        depth_ref = vk::AttachmentReference {
            attachment: 1,
            layout: vk::ImageLayout::DEPTH_STENCIL_ATTACHMENT_OPTIMAL,
        };
        resolve_ref = Some(vk::AttachmentReference {
            attachment: 2,
            layout: vk::ImageLayout::COLOR_ATTACHMENT_OPTIMAL,
        });
    } else {
        // 0: color (swapchain), 1: depth.
        attachments.push(
            vk::AttachmentDescription::default()
                .format(ctx.swapchain_format())
                .samples(vk::SampleCountFlags::TYPE_1)
                .load_op(vk::AttachmentLoadOp::CLEAR)
                .store_op(vk::AttachmentStoreOp::STORE)
                .stencil_load_op(vk::AttachmentLoadOp::DONT_CARE)
                .stencil_store_op(vk::AttachmentStoreOp::DONT_CARE)
                .initial_layout(vk::ImageLayout::UNDEFINED)
                .final_layout(vk::ImageLayout::PRESENT_SRC_KHR),
        );
        attachments.push(depth_attachment(ctx, samples));
        color_ref = vk::AttachmentReference {
            attachment: 0,
            layout: vk::ImageLayout::COLOR_ATTACHMENT_OPTIMAL,
        };
        depth_ref = vk::AttachmentReference {
            attachment: 1,
            layout: vk::ImageLayout::DEPTH_STENCIL_ATTACHMENT_OPTIMAL,
        };
        resolve_ref = None;
    }

    let color_refs = [color_ref];
    let resolve_refs: &[vk::AttachmentReference] =
        resolve_ref.as_slice();
    let mut subpass = vk::SubpassDescription::default()
        .pipeline_bind_point(vk::PipelineBindPoint::GRAPHICS)
        .color_attachments(&color_refs)
        .depth_stencil_attachment(&depth_ref);
    if msaa {
        subpass = subpass.resolve_attachments(resolve_refs);
    }

    let dependency = [vk::SubpassDependency::default()
        .src_subpass(vk::SUBPASS_EXTERNAL)
        .dst_subpass(0)
        .src_stage_mask(
            vk::PipelineStageFlags::COLOR_ATTACHMENT_OUTPUT
                | vk::PipelineStageFlags::EARLY_FRAGMENT_TESTS,
        )
        .dst_stage_mask(
            vk::PipelineStageFlags::COLOR_ATTACHMENT_OUTPUT
                | vk::PipelineStageFlags::EARLY_FRAGMENT_TESTS,
        )
        .dst_access_mask(
            vk::AccessFlags::COLOR_ATTACHMENT_WRITE
                | vk::AccessFlags::DEPTH_STENCIL_ATTACHMENT_WRITE,
        )];

    let subpasses = [subpass];
    let info = vk::RenderPassCreateInfo::default()
        .attachments(&attachments)
        .subpasses(&subpasses)
        .dependencies(&dependency);
    unsafe { device.create_render_pass(&info, None) }.context("render pass")
}

fn depth_attachment(ctx: &VulkanContext, samples: vk::SampleCountFlags) -> vk::AttachmentDescription {
    vk::AttachmentDescription::default()
        .format(ctx.depth_format())
        .samples(samples)
        .load_op(vk::AttachmentLoadOp::CLEAR)
        .store_op(vk::AttachmentStoreOp::DONT_CARE)
        .stencil_load_op(vk::AttachmentLoadOp::DONT_CARE)
        .stencil_store_op(vk::AttachmentStoreOp::DONT_CARE)
        .initial_layout(vk::ImageLayout::UNDEFINED)
        .final_layout(vk::ImageLayout::DEPTH_STENCIL_ATTACHMENT_OPTIMAL)
}

fn create_descriptor_set_layout(device: &ash::Device) -> Result<vk::DescriptorSetLayout> {
    let bindings = [vk::DescriptorSetLayoutBinding::default()
        .binding(0)
        .descriptor_type(vk::DescriptorType::UNIFORM_BUFFER)
        .descriptor_count(1)
        .stage_flags(vk::ShaderStageFlags::VERTEX | vk::ShaderStageFlags::FRAGMENT)];
    let info = vk::DescriptorSetLayoutCreateInfo::default().bindings(&bindings);
    unsafe { device.create_descriptor_set_layout(&info, None) }
        .context("raster descriptor set layout")
}

fn create_descriptor_pool(device: &ash::Device, frames: u32) -> Result<vk::DescriptorPool> {
    let sizes = [vk::DescriptorPoolSize::default()
        .ty(vk::DescriptorType::UNIFORM_BUFFER)
        .descriptor_count(frames)];
    let info = vk::DescriptorPoolCreateInfo::default()
        .pool_sizes(&sizes)
        .max_sets(frames);
    unsafe { device.create_descriptor_pool(&info, None) }.context("raster descriptor pool")
}

fn create_pipeline(
    ctx: &VulkanContext,
    render_pass: vk::RenderPass,
    set_layout: vk::DescriptorSetLayout,
) -> Result<(vk::PipelineLayout, vk::Pipeline)> {
    let device = ctx.device();

    let set_layouts = [set_layout];
    let push_range = [vk::PushConstantRange::default()
        .stage_flags(vk::ShaderStageFlags::VERTEX | vk::ShaderStageFlags::FRAGMENT)
        .offset(0)
        .size(std::mem::size_of::<PushConstants>() as u32)];
    let layout_info = vk::PipelineLayoutCreateInfo::default()
        .set_layouts(&set_layouts)
        .push_constant_ranges(&push_range);
    let pipeline_layout = unsafe { device.create_pipeline_layout(&layout_info, None) }
        .context("raster pipeline layout")?;

    let load_module = |spv: &[u8]| -> Result<vk::ShaderModule> {
        let code: Vec<u32> = spv
            .chunks_exact(4)
            .map(|c| u32::from_le_bytes([c[0], c[1], c[2], c[3]]))
            .collect();
        let info = vk::ShaderModuleCreateInfo::default().code(&code);
        unsafe { device.create_shader_module(&info, None) }.context("shader module")
    };
    let vert = load_module(SIMPLE_VERT_SPV)?;
    let frag = load_module(SIMPLE_FRAG_SPV)?;
    let stages = [
        vk::PipelineShaderStageCreateInfo::default()
            .stage(vk::ShaderStageFlags::VERTEX)
            .module(vert)
            .name(c"main"),
        vk::PipelineShaderStageCreateInfo::default()
            .stage(vk::ShaderStageFlags::FRAGMENT)
            .module(frag)
            .name(c"main"),
    ];

    // Vertex input — mirrors C++ Vertex::getBindingDescriptions /
    // getAttributeDescriptions (48-byte stride, five attributes).
    let bindings = [vk::VertexInputBindingDescription::default()
        .binding(0)
        .stride(std::mem::size_of::<GpuVertex>() as u32)
        .input_rate(vk::VertexInputRate::VERTEX)];
    let attributes = [
        vk::VertexInputAttributeDescription::default()
            .location(0)
            .binding(0)
            .format(vk::Format::R32G32B32_SFLOAT)
            .offset(0),
        vk::VertexInputAttributeDescription::default()
            .location(1)
            .binding(0)
            .format(vk::Format::R32G32B32_SFLOAT)
            .offset(12),
        vk::VertexInputAttributeDescription::default()
            .location(2)
            .binding(0)
            .format(vk::Format::R32G32B32_SFLOAT)
            .offset(24),
        vk::VertexInputAttributeDescription::default()
            .location(3)
            .binding(0)
            .format(vk::Format::R32G32_SFLOAT)
            .offset(36),
        vk::VertexInputAttributeDescription::default()
            .location(4)
            .binding(0)
            .format(vk::Format::R32_SFLOAT)
            .offset(44),
    ];
    let vertex_input = vk::PipelineVertexInputStateCreateInfo::default()
        .vertex_binding_descriptions(&bindings)
        .vertex_attribute_descriptions(&attributes);

    let input_assembly = vk::PipelineInputAssemblyStateCreateInfo::default()
        .topology(vk::PrimitiveTopology::TRIANGLE_LIST);

    let viewport_state = vk::PipelineViewportStateCreateInfo::default()
        .viewport_count(1)
        .scissor_count(1);
    let dynamic_states = [vk::DynamicState::VIEWPORT, vk::DynamicState::SCISSOR];
    let dynamic_state =
        vk::PipelineDynamicStateCreateInfo::default().dynamic_states(&dynamic_states);

    // C++ main pipeline: no back-face culling (mixed winding in the kernel),
    // CCW front face, depth test on.
    let rasterizer = vk::PipelineRasterizationStateCreateInfo::default()
        .polygon_mode(vk::PolygonMode::FILL)
        .cull_mode(vk::CullModeFlags::NONE)
        .front_face(vk::FrontFace::COUNTER_CLOCKWISE)
        .line_width(1.0);

    let multisample = vk::PipelineMultisampleStateCreateInfo::default()
        .rasterization_samples(ctx.msaa_samples());

    let depth_stencil = vk::PipelineDepthStencilStateCreateInfo::default()
        .depth_test_enable(true)
        .depth_write_enable(true)
        .depth_compare_op(vk::CompareOp::LESS);

    let blend_attachment = [vk::PipelineColorBlendAttachmentState::default()
        .color_write_mask(vk::ColorComponentFlags::RGBA)
        .blend_enable(false)];
    let color_blend =
        vk::PipelineColorBlendStateCreateInfo::default().attachments(&blend_attachment);

    let pipeline_info = [vk::GraphicsPipelineCreateInfo::default()
        .stages(&stages)
        .vertex_input_state(&vertex_input)
        .input_assembly_state(&input_assembly)
        .viewport_state(&viewport_state)
        .rasterization_state(&rasterizer)
        .multisample_state(&multisample)
        .depth_stencil_state(&depth_stencil)
        .color_blend_state(&color_blend)
        .dynamic_state(&dynamic_state)
        .layout(pipeline_layout)
        .render_pass(render_pass)
        .subpass(0)];

    let pipeline = unsafe {
        device.create_graphics_pipelines(ctx.pipeline_cache(), &pipeline_info, None)
    }
    .map_err(|(_, e)| e)
    .context("raster graphics pipeline")?[0];

    unsafe {
        device.destroy_shader_module(vert, None);
        device.destroy_shader_module(frag, None);
    }
    Ok((pipeline_layout, pipeline))
}

// ── Sky pass helpers ─────────────────────────────────────────────────────

fn create_sky_descriptor_set_layout(
    device: &ash::Device,
) -> Result<vk::DescriptorSetLayout> {
    let bindings = [
        // 0: shared UBO (ubo.glsl)
        vk::DescriptorSetLayoutBinding::default()
            .binding(0)
            .descriptor_type(vk::DescriptorType::UNIFORM_BUFFER)
            .descriptor_count(1)
            .stage_flags(vk::ShaderStageFlags::VERTEX | vk::ShaderStageFlags::FRAGMENT),
        // 1: environment cubemap (HDR sky mode)
        vk::DescriptorSetLayoutBinding::default()
            .binding(1)
            .descriptor_type(vk::DescriptorType::COMBINED_IMAGE_SAMPLER)
            .descriptor_count(1)
            .stage_flags(vk::ShaderStageFlags::FRAGMENT),
    ];
    let info = vk::DescriptorSetLayoutCreateInfo::default().bindings(&bindings);
    unsafe { device.create_descriptor_set_layout(&info, None) }
        .context("sky descriptor set layout")
}

fn create_sky_pipeline(
    ctx: &VulkanContext,
    render_pass: vk::RenderPass,
    set_layout: vk::DescriptorSetLayout,
) -> Result<(vk::PipelineLayout, vk::Pipeline)> {
    let device = ctx.device();

    let set_layouts = [set_layout];
    // sky.frag: vec4 sunDirection (xyz = direction, w = useHdr).
    let push_range = [vk::PushConstantRange::default()
        .stage_flags(vk::ShaderStageFlags::FRAGMENT)
        .offset(0)
        .size(16)];
    let layout_info = vk::PipelineLayoutCreateInfo::default()
        .set_layouts(&set_layouts)
        .push_constant_ranges(&push_range);
    let pipeline_layout = unsafe { device.create_pipeline_layout(&layout_info, None) }
        .context("sky pipeline layout")?;

    let load_module = |spv: &[u8]| -> Result<vk::ShaderModule> {
        let code: Vec<u32> = spv
            .chunks_exact(4)
            .map(|c| u32::from_le_bytes([c[0], c[1], c[2], c[3]]))
            .collect();
        let info = vk::ShaderModuleCreateInfo::default().code(&code);
        unsafe { device.create_shader_module(&info, None) }.context("sky shader module")
    };
    let vert = load_module(SKY_VERT_SPV)?;
    let frag = load_module(SKY_FRAG_SPV)?;
    let stages = [
        vk::PipelineShaderStageCreateInfo::default()
            .stage(vk::ShaderStageFlags::VERTEX)
            .module(vert)
            .name(c"main"),
        vk::PipelineShaderStageCreateInfo::default()
            .stage(vk::ShaderStageFlags::FRAGMENT)
            .module(frag)
            .name(c"main"),
    ];

    // No vertex input — sky.vert generates a fullscreen triangle from
    // gl_VertexIndex.
    let vertex_input = vk::PipelineVertexInputStateCreateInfo::default();
    let input_assembly = vk::PipelineInputAssemblyStateCreateInfo::default()
        .topology(vk::PrimitiveTopology::TRIANGLE_LIST);
    let viewport_state = vk::PipelineViewportStateCreateInfo::default()
        .viewport_count(1)
        .scissor_count(1);
    let dynamic_states = [vk::DynamicState::VIEWPORT, vk::DynamicState::SCISSOR];
    let dynamic_state =
        vk::PipelineDynamicStateCreateInfo::default().dynamic_states(&dynamic_states);
    let rasterizer = vk::PipelineRasterizationStateCreateInfo::default()
        .polygon_mode(vk::PolygonMode::FILL)
        .cull_mode(vk::CullModeFlags::NONE)
        .front_face(vk::FrontFace::COUNTER_CLOCKWISE)
        .line_width(1.0);
    let multisample = vk::PipelineMultisampleStateCreateInfo::default()
        .rasterization_samples(ctx.msaa_samples());
    // Depth test on (sky sits at z=0.9999), but never writes depth.
    let depth_stencil = vk::PipelineDepthStencilStateCreateInfo::default()
        .depth_test_enable(true)
        .depth_write_enable(false)
        .depth_compare_op(vk::CompareOp::LESS_OR_EQUAL);
    let blend_attachment = [vk::PipelineColorBlendAttachmentState::default()
        .color_write_mask(vk::ColorComponentFlags::RGBA)
        .blend_enable(false)];
    let color_blend =
        vk::PipelineColorBlendStateCreateInfo::default().attachments(&blend_attachment);

    let pipeline_info = [vk::GraphicsPipelineCreateInfo::default()
        .stages(&stages)
        .vertex_input_state(&vertex_input)
        .input_assembly_state(&input_assembly)
        .viewport_state(&viewport_state)
        .rasterization_state(&rasterizer)
        .multisample_state(&multisample)
        .depth_stencil_state(&depth_stencil)
        .color_blend_state(&color_blend)
        .dynamic_state(&dynamic_state)
        .layout(pipeline_layout)
        .render_pass(render_pass)
        .subpass(0)];
    let pipeline = unsafe {
        device.create_graphics_pipelines(ctx.pipeline_cache(), &pipeline_info, None)
    }
    .map_err(|(_, e)| e)
    .context("sky graphics pipeline")?[0];

    unsafe {
        device.destroy_shader_module(vert, None);
        device.destroy_shader_module(frag, None);
    }
    Ok((pipeline_layout, pipeline))
}
