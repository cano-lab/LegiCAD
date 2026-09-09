//! GPU half of the egui overlay: a dedicated 1-sample render pass that
//! loads the already-resolved swapchain image, plus the
//! [`egui_ash_renderer::Renderer`] that draws the tessellated UI into it.
//!
//! A separate pass is required (rather than drawing into the main pass,
//! as the C++ Dear ImGui backend did) because egui-ash-renderer builds a
//! 1-sample pipeline while the main subpass renders with MSAA — pipeline
//! and subpass sample counts must match. Cost is one extra render pass
//! per frame; the separation also keeps the egui pipeline independent of
//! the main pass's attachment layout.

use std::collections::VecDeque;

use anyhow::{Context as _, Result};
use ash::vk;
use egui::{ClippedPrimitive, TextureId};
use egui_ash_renderer::{
    Options, RenderMode, Renderer as EguiRenderer, allocator::DefaultAllocator,
};

use crate::vulkan::context::VulkanContext;

/// UI data produced by the app each frame (egui output, ready to upload
/// and draw).
pub struct UiFrame {
    /// `FullOutput::textures_delta` (egui 0.36: per-texture delta lists +
    /// a free set; frees are deferred by `in_flight` frames).
    pub textures_delta: egui::TexturesDelta,
    /// Tessellated primitives (`Context::tessellate`).
    pub primitives: Vec<ClippedPrimitive>,
    pub pixels_per_point: f32,
}

/// Owns the UI render pass, per-swapchain-image framebuffers, and the
/// egui renderer. Lives inside the raster [`Renderer`](crate::vulkan::raster::Renderer)
/// so it is recreated with the swapchain and dropped before the context.
pub struct UiOverlay {
    render_pass: vk::RenderPass,
    framebuffers: Vec<vk::Framebuffer>,
    egui: EguiRenderer<DefaultAllocator>,
    /// Frees deferred until no in-flight frame can reference the texture:
    /// (frame counter at defer time, ids).
    pending_free: VecDeque<(u64, Vec<TextureId>)>,
    frame_counter: u64,
    in_flight: u64,
}

impl UiOverlay {
    /// Create the overlay for the current swapchain. `in_flight` is the
    /// app's max frames in flight (egui buffers vertex data per frame).
    pub fn new(ctx: &VulkanContext, in_flight: usize) -> Result<Self> {
        let device = ctx.device().clone();
        let render_pass = create_ui_render_pass(ctx.swapchain_format(), &device)?;

        let srgb = ctx
            .swapchain_format()
            .as_raw()
            .to_string()
            .contains("SRGB");
        let egui = EguiRenderer::with_default_allocator(
            ctx.instance(),
            ctx.physical_device(),
            device.clone(),
            RenderMode::RenderPass(render_pass),
            Options {
                in_flight_frames: in_flight,
                enable_depth_test: false,
                enable_depth_write: false,
                srgb_framebuffer: srgb,
            },
        )
        .map_err(|e| anyhow::anyhow!("egui renderer init: {e}"))?;

        let mut overlay = Self {
            render_pass,
            framebuffers: Vec::new(),
            egui,
            pending_free: VecDeque::new(),
            frame_counter: 0,
            in_flight: in_flight as u64,
        };
        overlay.create_framebuffers(ctx)?;
        Ok(overlay)
    }

    /// Upload new/changed egui textures (font atlas on first frame).
    /// egui 0.36: each texture may carry several partial deltas.
    pub fn set_textures(&mut self, ctx: &VulkanContext, delta: &egui::TexturesDelta) -> Result<()> {
        for (id, deltas) in &delta.set {
            for d in deltas {
                self.egui
                    .set_texture(ctx.graphics_queue(), ctx.command_pool(), *id, d)
                    .map_err(|e| anyhow::anyhow!("egui set_texture: {e}"))?;
            }
        }
        Ok(())
    }

    /// Record the UI render pass into `cmd` for swapchain `image_index`.
    /// `cmd` must be in the recording state (outside any render pass).
    pub fn record(
        &mut self,
        device: &ash::Device,
        cmd: vk::CommandBuffer,
        image_index: u32,
        extent: vk::Extent2D,
        pixels_per_point: f32,
        primitives: &[ClippedPrimitive],
    ) -> Result<()> {
        self.frame_counter += 1;
        let pass_info = vk::RenderPassBeginInfo::default()
            .render_pass(self.render_pass)
            .framebuffer(self.framebuffers[image_index as usize])
            .render_area(vk::Rect2D {
                offset: vk::Offset2D { x: 0, y: 0 },
                extent,
            })
            // LOAD_OP_LOAD: no clear values.
            .clear_values(&[]);
        unsafe {
            device.cmd_begin_render_pass(cmd, &pass_info, vk::SubpassContents::INLINE);
        }
        self.egui
            .cmd_draw(cmd, extent, pixels_per_point, primitives)
            .map_err(|e| anyhow::anyhow!("egui cmd_draw: {e}"))?;
        unsafe {
            device.cmd_end_render_pass(cmd);
        }
        Ok(())
    }

    /// Defer texture frees until every in-flight frame has passed
    /// (textures may still be referenced by a frame executing on the GPU).
    pub fn defer_free(&mut self, ids: Vec<TextureId>) {
        if !ids.is_empty() {
            self.pending_free.push_back((self.frame_counter, ids));
        }
    }

    /// Free deferred textures whose defer age exceeds the in-flight count.
    /// Call after the frame fence wait in `draw_frame`.
    pub fn flush_due_frees(&mut self) {
        while let Some((at, _)) = self.pending_free.front() {
            if self.frame_counter.saturating_sub(*at) <= self.in_flight {
                break;
            }
            let (_, ids) = self.pending_free.pop_front().unwrap();
            for id in ids {
                if let Err(e) = self.egui.free_texture(id) {
                    tracing::warn!(error = %e, "[ui] egui free_texture failed");
                }
            }
        }
    }

    /// Recreate the framebuffers after a swapchain resize.
    pub fn recreate_framebuffers(&mut self, ctx: &VulkanContext) -> Result<()> {
        self.destroy_framebuffers(ctx);
        self.create_framebuffers(ctx)
    }

    fn create_framebuffers(&mut self, ctx: &VulkanContext) -> Result<()> {
        let device = ctx.device().clone();
        let extent = ctx.swapchain_extent();
        self.framebuffers = ctx
            .swapchain_image_views()
            .iter()
            .map(|&view| {
                let attachments = [view];
                let info = vk::FramebufferCreateInfo::default()
                    .render_pass(self.render_pass)
                    .attachments(&attachments)
                    .width(extent.width)
                    .height(extent.height)
                    .layers(1);
                unsafe { device.create_framebuffer(&info, None) }
                    .context("ui framebuffer")
            })
            .collect::<Result<Vec<_>>>()?;
        Ok(())
    }

    fn destroy_framebuffers(&mut self, ctx: &VulkanContext) {
        let device = ctx.device();
        unsafe {
            for &fb in &self.framebuffers {
                device.destroy_framebuffer(fb, None);
            }
        }
        self.framebuffers.clear();
    }

    /// Tear down. The context must still be alive; call under `wait_idle`.
    pub fn destroy(&mut self, ctx: &VulkanContext) {
        self.destroy_framebuffers(ctx);
        unsafe {
            ctx.device().destroy_render_pass(self.render_pass, None);
        }
        // The egui renderer frees its pipeline/descriptors/textures in Drop.
    }
}

/// Single 1-sample color pass over the swapchain image: loads what the
/// main pass resolved (PRESENT_SRC → COLOR_ATTACHMENT → PRESENT_SRC).
fn create_ui_render_pass(
    format: vk::Format,
    device: &ash::Device,
) -> Result<vk::RenderPass> {
    let attachment = vk::AttachmentDescription::default()
        .format(format)
        .samples(vk::SampleCountFlags::TYPE_1)
        .load_op(vk::AttachmentLoadOp::LOAD)
        .store_op(vk::AttachmentStoreOp::STORE)
        .stencil_load_op(vk::AttachmentLoadOp::DONT_CARE)
        .stencil_store_op(vk::AttachmentStoreOp::DONT_CARE)
        .initial_layout(vk::ImageLayout::PRESENT_SRC_KHR)
        .final_layout(vk::ImageLayout::PRESENT_SRC_KHR);

    let color_ref = vk::AttachmentReference::default()
        .attachment(0)
        .layout(vk::ImageLayout::COLOR_ATTACHMENT_OPTIMAL);
    let subpass = vk::SubpassDescription::default()
        .pipeline_bind_point(vk::PipelineBindPoint::GRAPHICS)
        .color_attachments(std::slice::from_ref(&color_ref));

    // Transition from the main pass's resolved image (its writes must be
    // visible) and back out to present.
    let dependencies = [
        vk::SubpassDependency::default()
            .src_subpass(vk::SUBPASS_EXTERNAL)
            .dst_subpass(0)
            .src_stage_mask(vk::PipelineStageFlags::COLOR_ATTACHMENT_OUTPUT)
            .src_access_mask(vk::AccessFlags::COLOR_ATTACHMENT_WRITE)
            .dst_stage_mask(vk::PipelineStageFlags::COLOR_ATTACHMENT_OUTPUT)
            .dst_access_mask(
                vk::AccessFlags::COLOR_ATTACHMENT_READ | vk::AccessFlags::COLOR_ATTACHMENT_WRITE,
            ),
        vk::SubpassDependency::default()
            .src_subpass(0)
            .dst_subpass(vk::SUBPASS_EXTERNAL)
            .src_stage_mask(vk::PipelineStageFlags::COLOR_ATTACHMENT_OUTPUT)
            .src_access_mask(vk::AccessFlags::COLOR_ATTACHMENT_WRITE)
            .dst_stage_mask(vk::PipelineStageFlags::COLOR_ATTACHMENT_OUTPUT)
            .dst_access_mask(vk::AccessFlags::empty()),
    ];

    let attachments = [attachment];
    let subpasses = [subpass];
    let info = vk::RenderPassCreateInfo::default()
        .attachments(&attachments)
        .subpasses(&subpasses)
        .dependencies(&dependencies);
    unsafe { device.create_render_pass(&info, None) }.context("ui render pass")
}
