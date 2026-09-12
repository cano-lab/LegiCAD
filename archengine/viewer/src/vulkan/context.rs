//! Port of `vulkan_context.hpp/.cpp` — device and resource management.
//!
//! Handles instance/device/queue creation, swapchain management, buffer and
//! image helpers, single-use command buffers, pipeline caching, and debug
//! markers. Two modes, mirroring the C++:
//!
//! - **Windowed** ([`VulkanContext::new`]): instance + surface + swapchain.
//! - **Headless** ([`VulkanContext::new_headless`]): compute-only, no
//!   surface/swapchain — used for offline path-traced renders.
//!
//! The C++ "embedded" constructor (external instance/surface) is not ported
//! yet — no consumer in the Rust workspace.

use std::ffi::{CStr, CString, c_void};
use std::path::PathBuf;

use anyhow::{Context as _, Result, anyhow, bail};
use ash::{Device, Entry, Instance, vk};

/// Queue family indices discovered during device selection.
#[derive(Debug, Clone, Copy, Default)]
pub struct QueueFamilyIndices {
    pub graphics_family: Option<u32>,
    pub present_family: Option<u32>,
}

impl QueueFamilyIndices {
    pub fn is_complete(&self) -> bool {
        self.graphics_family.is_some() && self.present_family.is_some()
    }
}

/// Surface capabilities, formats, and present modes for swapchain setup.
pub struct SwapchainSupportDetails {
    pub capabilities: vk::SurfaceCapabilitiesKHR,
    pub formats: Vec<vk::SurfaceFormatKHR>,
    pub present_modes: Vec<vk::PresentModeKHR>,
}

/// Configuration options, mirroring `VulkanConfig`.
#[derive(Debug, Clone)]
pub struct VulkanConfig {
    /// Enable `VK_LAYER_KHRONOS_validation` + debug utils messenger.
    pub enable_validation: bool,
    /// Number of frames that can be in flight.
    pub max_frames_in_flight: u32,
    /// Compute-only mode: no surface, swapchain, depth, or MSAA.
    pub headless: bool,
    /// MSAA sample count cap (windowed only).
    pub msaa_samples: vk::SampleCountFlags,
    pub enable_msaa: bool,
    /// Path for the pipeline cache file.
    pub pipeline_cache_path: PathBuf,
}

impl Default for VulkanConfig {
    fn default() -> Self {
        Self {
            enable_validation: cfg!(debug_assertions),
            max_frames_in_flight: 2,
            headless: false,
            msaa_samples: vk::SampleCountFlags::TYPE_4,
            enable_msaa: true,
            pipeline_cache_path: PathBuf::from("pipeline_cache.bin"),
        }
    }
}

struct MsaaResources {
    image: vk::Image,
    memory: vk::DeviceMemory,
    view: vk::ImageView,
}

struct DepthResources {
    image: vk::Image,
    memory: vk::DeviceMemory,
    view: vk::ImageView,
}

/// Vulkan device and resource management — port of C++ `arch::VulkanContext`.
///
/// Only one should exist per application. Cleanup happens in `Drop`, in the
/// reverse order of the C++ destructor.
pub struct VulkanContext {
    config: VulkanConfig,
    /// Supplies the current framebuffer size (windowed mode; winit owns the
    /// window). Headless mode stores a constant.
    window_size: Box<dyn Fn() -> (u32, u32) + Send>,

    /// Kept alive so the Vulkan loader stays loaded; never read directly.
    #[allow(dead_code)]
    entry: Entry,
    instance: Instance,
    debug_utils: Option<(ash::ext::debug_utils::Instance, vk::DebugUtilsMessengerEXT)>,
    debug_device: Option<ash::ext::debug_utils::Device>,
    surface_loader: Option<ash::khr::surface::Instance>,
    surface: vk::SurfaceKHR,
    physical_device: vk::PhysicalDevice,
    device: Device,
    device_features: vk::PhysicalDeviceFeatures,
    max_sampler_anisotropy: f32,

    pipeline_cache: vk::PipelineCache,

    msaa_samples: vk::SampleCountFlags,
    msaa: Option<MsaaResources>,

    graphics_queue: vk::Queue,
    present_queue: vk::Queue,
    queue_families: QueueFamilyIndices,

    swapchain_loader: Option<ash::khr::swapchain::Device>,
    swapchain: vk::SwapchainKHR,
    swapchain_images: Vec<vk::Image>,
    swapchain_image_views: Vec<vk::ImageView>,
    swapchain_format: vk::Format,
    swapchain_extent: vk::Extent2D,

    depth: Option<DepthResources>,
    command_pool: vk::CommandPool,
}

impl VulkanContext {
    /// Windowed context: creates the instance (with the surface extensions
    /// required for `display_handle`), a surface for `window_handle`, and the
    /// full swapchain/depth/MSAA stack.
    ///
    /// `window_size` is polled for the initial extent and on
    /// [`Self::recreate_swapchain`].
    #[cfg(feature = "windowed")]
    pub fn new(
        display_handle: raw_window_handle::RawDisplayHandle,
        window_handle: raw_window_handle::RawWindowHandle,
        window_size: impl Fn() -> (u32, u32) + Send + 'static,
        config: VulkanConfig,
    ) -> Result<Self> {
        let entry = unsafe {
            #[cfg(target_os = "macos")]
            {
                // On macOS, explicitly load MoltenVK since it's not in the standard search path
                Entry::from_static_loading(ash::Loading::Dynamic)
                    .or_else(|_| Entry::load())
                    .context("failed to load Vulkan loader (MoltenVK)")?
            }
            #[cfg(not(target_os = "macos"))]
            {
                Entry::load().context("failed to load Vulkan loader")?
            }
        };
        let extensions = ash_window::enumerate_required_extensions(display_handle)
            .context("enumerate required instance extensions")?
            .to_vec();
        let instance = create_instance(&entry, &config, extensions)?;
        let debug_utils = setup_debug_messenger(&entry, &instance, &config)?;
        let surface_loader = ash::khr::surface::Instance::new(&entry, &instance);
        let surface = unsafe {
            ash_window::create_surface(&entry, &instance, display_handle, window_handle, None)
        }
        .context("failed to create window surface")?;

        Self::finish_init(
            entry,
            instance,
            debug_utils,
            Some((surface_loader, surface)),
            Box::new(window_size),
            config,
        )
    }

    /// Headless context for compute-only work (offline path tracing).
    /// No surface, swapchain, depth, or MSAA.
    pub fn new_headless(mut config: VulkanConfig) -> Result<Self> {
        config.headless = true;
        config.enable_msaa = false;
        let entry = unsafe {
            #[cfg(target_os = "macos")]
            {
                // On macOS, explicitly load MoltenVK since it's not in the standard search path
                Entry::from_static_loading(ash::Loading::Dynamic)
                    .or_else(|_| Entry::load())
                    .context("failed to load Vulkan loader (MoltenVK)")?
            }
            #[cfg(not(target_os = "macos"))]
            {
                Entry::load().context("failed to load Vulkan loader")?
            }
        };
        // Headless: no window/surface extensions.
        let instance = create_instance(&entry, &config, Vec::new())?;
        let debug_utils = setup_debug_messenger(&entry, &instance, &config)?;
        Self::finish_init(
            entry,
            instance,
            debug_utils,
            None,
            Box::new(|| (0, 0)),
            config,
        )
    }

    /// Shared tail of both constructors: physical device, logical device,
    /// swapchain stack (windowed), command pool, pipeline cache.
    fn finish_init(
        entry: Entry,
        instance: Instance,
        debug_utils: Option<(ash::ext::debug_utils::Instance, vk::DebugUtilsMessengerEXT)>,
        surface: Option<(ash::khr::surface::Instance, vk::SurfaceKHR)>,
        window_size: Box<dyn Fn() -> (u32, u32) + Send>,
        config: VulkanConfig,
    ) -> Result<Self> {
        let (surface_loader, surface) = match &surface {
            Some((loader, s)) => (Some(loader.clone()), *s),
            None => (None, vk::SurfaceKHR::null()),
        };

        let physical_device = pick_physical_device(&instance, surface_loader.as_ref(), surface, &config)?;
        let props = unsafe { instance.get_physical_device_properties(physical_device) };
        let name = unsafe { CStr::from_ptr(props.device_name.as_ptr()) };
        tracing::info!(gpu = %name.to_string_lossy(), headless = config.headless, "selected GPU");

        let queue_families =
            find_queue_families(&instance, surface_loader.as_ref(), physical_device, surface, &config);
        let (device, device_features, debug_device) =
            create_logical_device(&instance, physical_device, &queue_families, &config)?;
        let graphics_queue =
            unsafe { device.get_device_queue(queue_families.graphics_family.unwrap(), 0) };
        let present_queue =
            unsafe { device.get_device_queue(queue_families.present_family.unwrap(), 0) };

        let mut ctx = Self {
            max_sampler_anisotropy: props.limits.max_sampler_anisotropy,
            entry,
            instance,
            debug_utils,
            debug_device,
            surface_loader,
            surface,
            physical_device,
            device,
            device_features,
            pipeline_cache: vk::PipelineCache::null(),
            msaa_samples: vk::SampleCountFlags::TYPE_1,
            msaa: None,
            graphics_queue,
            present_queue,
            queue_families,
            swapchain_loader: None,
            swapchain: vk::SwapchainKHR::null(),
            swapchain_images: Vec::new(),
            swapchain_image_views: Vec::new(),
            swapchain_format: vk::Format::UNDEFINED,
            swapchain_extent: vk::Extent2D::default(),
            depth: None,
            command_pool: vk::CommandPool::null(),
            config,
            window_size,
        };

        if !ctx.config.headless {
            ctx.swapchain_loader =
                Some(ash::khr::swapchain::Device::new(&ctx.instance, &ctx.device));
            ctx.create_swapchain()?;
            ctx.create_image_views()?;
        }
        ctx.create_command_pool()?;
        ctx.create_pipeline_cache();

        if ctx.config.enable_msaa && !ctx.config.headless {
            ctx.msaa_samples = ctx
                .max_usable_sample_count()
                .min_samples_capped(ctx.config.msaa_samples);
            tracing::info!(samples = ctx.msaa_samples.as_raw(), "MSAA enabled");
        }
        if !ctx.config.headless {
            ctx.create_depth_resources()?;
            if ctx.config.enable_msaa {
                ctx.create_msaa_resources()?;
            }
        }
        Ok(ctx)
    }

    // ── Accessors ────────────────────────────────────────────────────────

    pub fn instance(&self) -> &Instance {
        &self.instance
    }
    pub fn device(&self) -> &Device {
        &self.device
    }
    pub fn physical_device(&self) -> vk::PhysicalDevice {
        self.physical_device
    }
    pub fn graphics_queue(&self) -> vk::Queue {
        self.graphics_queue
    }
    pub fn present_queue(&self) -> vk::Queue {
        self.present_queue
    }
    pub fn command_pool(&self) -> vk::CommandPool {
        self.command_pool
    }
    pub fn surface(&self) -> vk::SurfaceKHR {
        self.surface
    }
    pub fn queue_families(&self) -> QueueFamilyIndices {
        self.queue_families
    }
    pub fn graphics_queue_family(&self) -> u32 {
        self.queue_families.graphics_family.unwrap()
    }
    pub fn max_frames_in_flight(&self) -> u32 {
        self.config.max_frames_in_flight
    }
    pub fn pipeline_cache(&self) -> vk::PipelineCache {
        self.pipeline_cache
    }
    pub fn msaa_samples(&self) -> vk::SampleCountFlags {
        self.msaa_samples
    }
    pub fn msaa_color_image_view(&self) -> vk::ImageView {
        self.msaa.as_ref().map_or(vk::ImageView::null(), |m| m.view)
    }
    pub fn config(&self) -> &VulkanConfig {
        &self.config
    }
    pub fn is_headless(&self) -> bool {
        self.config.headless
    }
    pub fn swapchain(&self) -> vk::SwapchainKHR {
        self.swapchain
    }
    pub fn swapchain_loader(&self) -> &ash::khr::swapchain::Device {
        self.swapchain_loader.as_ref().expect("headless context has no swapchain")
    }
    pub fn swapchain_format(&self) -> vk::Format {
        self.swapchain_format
    }
    pub fn swapchain_extent(&self) -> vk::Extent2D {
        self.swapchain_extent
    }
    pub fn swapchain_image_views(&self) -> &[vk::ImageView] {
        &self.swapchain_image_views
    }
    pub fn swapchain_image_count(&self) -> u32 {
        self.swapchain_images.len() as u32
    }
    pub fn depth_image_view(&self) -> vk::ImageView {
        self.depth.as_ref().map_or(vk::ImageView::null(), |d| d.view)
    }
    pub fn depth_format(&self) -> vk::Format {
        vk::Format::D32_SFLOAT
    }

    // ── Feature queries (C++ supportsXxx accessors) ─────────────────────

    pub fn supports_sampler_anisotropy(&self) -> bool {
        self.device_features.sampler_anisotropy == vk::TRUE
    }
    pub fn max_sampler_anisotropy(&self) -> f32 {
        self.max_sampler_anisotropy
    }
    pub fn supports_tessellation(&self) -> bool {
        self.device_features.tessellation_shader == vk::TRUE
    }
    pub fn supports_wide_lines(&self) -> bool {
        self.device_features.wide_lines == vk::TRUE
    }
    pub fn supports_fill_mode_non_solid(&self) -> bool {
        self.device_features.fill_mode_non_solid == vk::TRUE
    }
    pub fn supports_shader_clip_distance(&self) -> bool {
        self.device_features.shader_clip_distance == vk::TRUE
    }

    /// Wait for all device operations to complete.
    pub fn wait_idle(&self) {
        unsafe { self.device.device_wait_idle() }.expect("device_wait_idle");
    }

    // ── Swapchain management ─────────────────────────────────────────────

    /// Recreate the swapchain after a window resize (windowed mode only).
    pub fn recreate_swapchain(&mut self) -> Result<()> {
        assert!(!self.config.headless, "headless context has no swapchain");
        let (mut w, mut h) = (self.window_size)();
        while w == 0 || h == 0 {
            // C++ blocks on glfwWaitEvents here; the winit event loop drives
            // resizes, so a zero size simply defers recreation.
            std::thread::yield_now();
            let size = (self.window_size)();
            w = size.0;
            h = size.1;
        }
        self.wait_idle();
        self.cleanup_swapchain();
        self.create_swapchain()?;
        self.create_image_views()?;
        self.create_depth_resources()?;
        if self.config.enable_msaa {
            self.create_msaa_resources()?;
        }
        Ok(())
    }

    fn create_swapchain(&mut self) -> Result<()> {
        let support = self.query_swapchain_support(self.physical_device)?;
        let surface_format = choose_swap_surface_format(&support.formats);
        let present_mode = choose_swap_present_mode(&support.present_modes);
        let extent = choose_swap_extent(&support.capabilities, (self.window_size)());

        let mut image_count = support.capabilities.min_image_count + 1;
        if support.capabilities.max_image_count > 0 {
            image_count = image_count.min(support.capabilities.max_image_count);
        }

        let queue_indices = [
            self.queue_families.graphics_family.unwrap(),
            self.queue_families.present_family.unwrap(),
        ];
        let (sharing_mode, family_slice): (vk::SharingMode, &[u32]) =
            if queue_indices[0] != queue_indices[1] {
                (vk::SharingMode::CONCURRENT, &queue_indices)
            } else {
                (vk::SharingMode::EXCLUSIVE, &[])
            };

        let create_info = vk::SwapchainCreateInfoKHR::default()
            .surface(self.surface)
            .min_image_count(image_count)
            .image_format(surface_format.format)
            .image_color_space(surface_format.color_space)
            .image_extent(extent)
            .image_array_layers(1)
            .image_usage(vk::ImageUsageFlags::COLOR_ATTACHMENT)
            .image_sharing_mode(sharing_mode)
            .queue_family_indices(family_slice)
            .pre_transform(support.capabilities.current_transform)
            .composite_alpha(vk::CompositeAlphaFlagsKHR::OPAQUE)
            .present_mode(present_mode)
            .clipped(true);

        let loader = self.swapchain_loader.as_ref().unwrap();
        self.swapchain = unsafe { loader.create_swapchain(&create_info, None) }
            .context("failed to create swapchain")?;
        self.swapchain_images =
            unsafe { loader.get_swapchain_images(self.swapchain) }.context("swapchain images")?;
        self.swapchain_format = surface_format.format;
        self.swapchain_extent = extent;
        Ok(())
    }

    fn create_image_views(&mut self) -> Result<()> {
        self.swapchain_image_views = self
            .swapchain_images
            .iter()
            .map(|&image| self.create_image_view(image, self.swapchain_format, vk::ImageAspectFlags::COLOR))
            .collect::<Result<Vec<_>>>()?;
        Ok(())
    }

    fn create_command_pool(&mut self) -> Result<()> {
        let pool_info = vk::CommandPoolCreateInfo::default()
            .flags(vk::CommandPoolCreateFlags::RESET_COMMAND_BUFFER)
            .queue_family_index(self.queue_families.graphics_family.unwrap());
        self.command_pool = unsafe { self.device.create_command_pool(&pool_info, None) }
            .context("failed to create command pool")?;
        Ok(())
    }

    fn create_depth_resources(&mut self) -> Result<()> {
        let format = self.depth_format();
        let (image, memory) = self.create_image(
            self.swapchain_extent.width,
            self.swapchain_extent.height,
            format,
            vk::ImageTiling::OPTIMAL,
            vk::ImageUsageFlags::DEPTH_STENCIL_ATTACHMENT,
            vk::MemoryPropertyFlags::DEVICE_LOCAL,
            self.msaa_samples,
        )?;
        let view = self.create_image_view(image, format, vk::ImageAspectFlags::DEPTH)?;
        self.depth = Some(DepthResources { image, memory, view });
        Ok(())
    }

    fn create_msaa_resources(&mut self) -> Result<()> {
        let (image, memory) = self.create_image(
            self.swapchain_extent.width,
            self.swapchain_extent.height,
            self.swapchain_format,
            vk::ImageTiling::OPTIMAL,
            vk::ImageUsageFlags::TRANSIENT_ATTACHMENT | vk::ImageUsageFlags::COLOR_ATTACHMENT,
            vk::MemoryPropertyFlags::DEVICE_LOCAL,
            self.msaa_samples,
        )?;
        let view = self.create_image_view(image, self.swapchain_format, vk::ImageAspectFlags::COLOR)?;
        self.msaa = Some(MsaaResources { image, memory, view });
        Ok(())
    }

    fn cleanup_swapchain(&mut self) {
        unsafe {
            if let Some(msaa) = self.msaa.take() {
                self.device.destroy_image_view(msaa.view, None);
                self.device.destroy_image(msaa.image, None);
                self.device.free_memory(msaa.memory, None);
            }
            if let Some(depth) = self.depth.take() {
                self.device.destroy_image_view(depth.view, None);
                self.device.destroy_image(depth.image, None);
                self.device.free_memory(depth.memory, None);
            }
            for &view in &self.swapchain_image_views {
                self.device.destroy_image_view(view, None);
            }
            self.swapchain_image_views.clear();
            if let Some(loader) = &self.swapchain_loader {
                if self.swapchain != vk::SwapchainKHR::null() {
                    loader.destroy_swapchain(self.swapchain, None);
                    self.swapchain = vk::SwapchainKHR::null();
                }
            }
        }
    }

    fn query_swapchain_support(&self, device: vk::PhysicalDevice) -> Result<SwapchainSupportDetails> {
        let loader = self.surface_loader.as_ref().expect("headless context has no surface");
        unsafe {
            Ok(SwapchainSupportDetails {
                capabilities: loader
                    .get_physical_device_surface_capabilities(device, self.surface)
                    .context("surface capabilities")?,
                formats: loader
                    .get_physical_device_surface_formats(device, self.surface)
                    .context("surface formats")?,
                present_modes: loader
                    .get_physical_device_surface_present_modes(device, self.surface)
                    .context("surface present modes")?,
            })
        }
    }

    fn max_usable_sample_count(&self) -> vk::SampleCountFlags {
        let props = unsafe { self.instance.get_physical_device_properties(self.physical_device) };
        let counts = props.limits.framebuffer_color_sample_counts
            & props.limits.framebuffer_depth_sample_counts;
        for flag in [
            vk::SampleCountFlags::TYPE_64,
            vk::SampleCountFlags::TYPE_32,
            vk::SampleCountFlags::TYPE_16,
            vk::SampleCountFlags::TYPE_8,
            vk::SampleCountFlags::TYPE_4,
            vk::SampleCountFlags::TYPE_2,
        ] {
            if counts.contains(flag) {
                return flag;
            }
        }
        vk::SampleCountFlags::TYPE_1
    }

    // ── Pipeline cache ───────────────────────────────────────────────────

    fn create_pipeline_cache(&mut self) {
        let cache_data = std::fs::read(&self.config.pipeline_cache_path).unwrap_or_default();
        if !cache_data.is_empty() {
            tracing::info!(bytes = cache_data.len(), "loaded pipeline cache");
        }
        let create_info = vk::PipelineCacheCreateInfo::default().initial_data(&cache_data);
        match unsafe { self.device.create_pipeline_cache(&create_info, None) } {
            Ok(cache) => self.pipeline_cache = cache,
            Err(e) => tracing::warn!("failed to create pipeline cache: {e}"),
        }
    }

    fn save_pipeline_cache(&self) {
        if self.pipeline_cache == vk::PipelineCache::null() {
            return;
        }
        if let Ok(data) = unsafe { self.device.get_pipeline_cache_data(self.pipeline_cache) } {
            if std::fs::write(&self.config.pipeline_cache_path, &data).is_ok() {
                tracing::info!(bytes = data.len(), "saved pipeline cache");
            }
        }
    }

    // ── Single-use command buffers ───────────────────────────────────────

    /// Begin a single-use command buffer for one-time operations
    /// (buffer copies, image transitions). Pair with
    /// [`Self::end_single_time_commands`].
    pub fn begin_single_time_commands(&self) -> Result<vk::CommandBuffer> {
        let alloc_info = vk::CommandBufferAllocateInfo::default()
            .level(vk::CommandBufferLevel::PRIMARY)
            .command_pool(self.command_pool)
            .command_buffer_count(1);
        let cmd = unsafe { self.device.allocate_command_buffers(&alloc_info) }
            .context("allocate single-use command buffer")?[0];
        let begin_info = vk::CommandBufferBeginInfo::default()
            .flags(vk::CommandBufferUsageFlags::ONE_TIME_SUBMIT);
        unsafe { self.device.begin_command_buffer(cmd, &begin_info) }
            .context("begin single-use command buffer")?;
        Ok(cmd)
    }

    /// Submit a single-use command buffer and wait for completion.
    pub fn end_single_time_commands(&self, cmd: vk::CommandBuffer) -> Result<()> {
        unsafe {
            self.device.end_command_buffer(cmd)?;
            let cmds = [cmd];
            let submit = vk::SubmitInfo::default().command_buffers(&cmds);
            self.device
                .queue_submit(self.graphics_queue, &[submit], vk::Fence::null())?;
            self.device.queue_wait_idle(self.graphics_queue)?;
            self.device.free_command_buffers(self.command_pool, &cmds);
        }
        Ok(())
    }

    // ── Buffer helpers ───────────────────────────────────────────────────

    /// Create a buffer with bound memory. Mirrors C++ `createBuffer`
    /// (out-params → returned tuple).
    pub fn create_buffer(
        &self,
        size: vk::DeviceSize,
        usage: vk::BufferUsageFlags,
        properties: vk::MemoryPropertyFlags,
    ) -> Result<(vk::Buffer, vk::DeviceMemory)> {
        let buffer_info = vk::BufferCreateInfo::default()
            .size(size)
            .usage(usage)
            .sharing_mode(vk::SharingMode::EXCLUSIVE);
        let buffer = unsafe { self.device.create_buffer(&buffer_info, None) }
            .context("failed to create buffer")?;

        let requirements = unsafe { self.device.get_buffer_memory_requirements(buffer) };
        let alloc_info = vk::MemoryAllocateInfo::default()
            .allocation_size(requirements.size)
            .memory_type_index(self.find_memory_type(requirements.memory_type_bits, properties)?);
        let memory = unsafe { self.device.allocate_memory(&alloc_info, None) }
            .context("failed to allocate buffer memory")?;
        unsafe { self.device.bind_buffer_memory(buffer, memory, 0) }?;
        Ok((buffer, memory))
    }

    pub fn copy_buffer(&self, src: vk::Buffer, dst: vk::Buffer, size: vk::DeviceSize) -> Result<()> {
        let cmd = self.begin_single_time_commands()?;
        let region = vk::BufferCopy::default().size(size);
        unsafe { self.device.cmd_copy_buffer(cmd, src, dst, &[region]) };
        self.end_single_time_commands(cmd)
    }

    pub fn copy_buffer_to_image(
        &self,
        buffer: vk::Buffer,
        image: vk::Image,
        width: u32,
        height: u32,
    ) -> Result<()> {
        let cmd = self.begin_single_time_commands()?;
        let region = vk::BufferImageCopy::default()
            .image_subresource(vk::ImageSubresourceLayers {
                aspect_mask: vk::ImageAspectFlags::COLOR,
                mip_level: 0,
                base_array_layer: 0,
                layer_count: 1,
            })
            .image_extent(vk::Extent3D { width, height, depth: 1 });
        unsafe {
            self.device.cmd_copy_buffer_to_image(
                cmd,
                buffer,
                image,
                vk::ImageLayout::TRANSFER_DST_OPTIMAL,
                &[region],
            )
        };
        self.end_single_time_commands(cmd)
    }

    /// Find a suitable memory type. Mirrors C++ `findMemoryType`.
    pub fn find_memory_type(
        &self,
        type_filter: u32,
        properties: vk::MemoryPropertyFlags,
    ) -> Result<u32> {
        let mem_props =
            unsafe { self.instance.get_physical_device_memory_properties(self.physical_device) };
        for i in 0..mem_props.memory_type_count {
            if type_filter & (1 << i) != 0
                && mem_props.memory_types[i as usize]
                    .property_flags
                    .contains(properties)
            {
                return Ok(i);
            }
        }
        Err(anyhow!("failed to find suitable memory type"))
    }

    // ── Image helpers ────────────────────────────────────────────────────

    /// Create an image with bound memory. Mirrors C++ `createImage`.
    pub fn create_image(
        &self,
        width: u32,
        height: u32,
        format: vk::Format,
        tiling: vk::ImageTiling,
        usage: vk::ImageUsageFlags,
        properties: vk::MemoryPropertyFlags,
        samples: vk::SampleCountFlags,
    ) -> Result<(vk::Image, vk::DeviceMemory)> {
        let image_info = vk::ImageCreateInfo::default()
            .image_type(vk::ImageType::TYPE_2D)
            .extent(vk::Extent3D { width, height, depth: 1 })
            .mip_levels(1)
            .array_layers(1)
            .format(format)
            .tiling(tiling)
            .initial_layout(vk::ImageLayout::UNDEFINED)
            .usage(usage)
            .samples(samples)
            .sharing_mode(vk::SharingMode::EXCLUSIVE);
        let image = unsafe { self.device.create_image(&image_info, None) }
            .context("failed to create image")?;

        let requirements = unsafe { self.device.get_image_memory_requirements(image) };
        let alloc_info = vk::MemoryAllocateInfo::default()
            .allocation_size(requirements.size)
            .memory_type_index(self.find_memory_type(requirements.memory_type_bits, properties)?);
        let memory = unsafe { self.device.allocate_memory(&alloc_info, None) }
            .context("failed to allocate image memory")?;
        unsafe { self.device.bind_image_memory(image, memory, 0) }?;
        Ok((image, memory))
    }

    /// Create a 2D image view (single mip, single layer).
    pub fn create_image_view(
        &self,
        image: vk::Image,
        format: vk::Format,
        aspect: vk::ImageAspectFlags,
    ) -> Result<vk::ImageView> {
        let view_info = vk::ImageViewCreateInfo::default()
            .image(image)
            .view_type(vk::ImageViewType::TYPE_2D)
            .format(format)
            .subresource_range(vk::ImageSubresourceRange {
                aspect_mask: aspect,
                base_mip_level: 0,
                level_count: 1,
                base_array_layer: 0,
                layer_count: 1,
            });
        unsafe { self.device.create_image_view(&view_info, None) }.context("failed to create image view")
    }

    /// Transition an image between layouts. Merges both C++ overloads: the
    /// aspect mask is derived from `format` (depth formats get DEPTH, plus
    /// STENCIL for combined formats), and mip/layer counts are parameters.
    /// Same supported transition set as the C++.
    pub fn transition_image_layout(
        &self,
        image: vk::Image,
        format: vk::Format,
        old_layout: vk::ImageLayout,
        new_layout: vk::ImageLayout,
        mip_levels: u32,
        layer_count: u32,
    ) -> Result<()> {
        let aspect = match format {
            vk::Format::D32_SFLOAT | vk::Format::D16_UNORM => vk::ImageAspectFlags::DEPTH,
            vk::Format::D32_SFLOAT_S8_UINT | vk::Format::D24_UNORM_S8_UINT => {
                vk::ImageAspectFlags::DEPTH | vk::ImageAspectFlags::STENCIL
            }
            _ => vk::ImageAspectFlags::COLOR,
        };
        let mut barrier = vk::ImageMemoryBarrier::default()
            .old_layout(old_layout)
            .new_layout(new_layout)
            .src_queue_family_index(vk::QUEUE_FAMILY_IGNORED)
            .dst_queue_family_index(vk::QUEUE_FAMILY_IGNORED)
            .image(image)
            .subresource_range(vk::ImageSubresourceRange {
                aspect_mask: aspect,
                base_mip_level: 0,
                level_count: mip_levels,
                base_array_layer: 0,
                layer_count,
            });

        use vk::{AccessFlags as A, ImageLayout as L, PipelineStageFlags as P};
        let (src_stage, dst_stage) = match (old_layout, new_layout) {
            (L::UNDEFINED, L::TRANSFER_DST_OPTIMAL) => {
                barrier.dst_access_mask = A::TRANSFER_WRITE;
                (P::TOP_OF_PIPE, P::TRANSFER)
            }
            (L::TRANSFER_DST_OPTIMAL, L::SHADER_READ_ONLY_OPTIMAL) => {
                barrier.src_access_mask = A::TRANSFER_WRITE;
                barrier.dst_access_mask = A::SHADER_READ;
                (P::TRANSFER, P::FRAGMENT_SHADER)
            }
            (L::UNDEFINED, L::SHADER_READ_ONLY_OPTIMAL) => {
                barrier.dst_access_mask = A::SHADER_READ;
                (P::TOP_OF_PIPE, P::FRAGMENT_SHADER)
            }
            (L::UNDEFINED, L::GENERAL) => {
                barrier.dst_access_mask = A::SHADER_WRITE;
                (P::TOP_OF_PIPE, P::COMPUTE_SHADER)
            }
            (L::GENERAL, L::SHADER_READ_ONLY_OPTIMAL) => {
                barrier.src_access_mask = A::SHADER_WRITE;
                barrier.dst_access_mask = A::SHADER_READ;
                (P::COMPUTE_SHADER, P::FRAGMENT_SHADER)
            }
            // Placeholder shadow map: cleared via transfer, then sampled by
            // the comparison sampler in the fragment shader.
            (L::TRANSFER_DST_OPTIMAL, L::DEPTH_STENCIL_READ_ONLY_OPTIMAL) => {
                barrier.src_access_mask = A::TRANSFER_WRITE;
                barrier.dst_access_mask = A::SHADER_READ;
                (P::TRANSFER, P::FRAGMENT_SHADER)
            }
            _ => bail!("unsupported layout transition: {old_layout:?} -> {new_layout:?}"),
        };

        let cmd = self.begin_single_time_commands()?;
        unsafe {
            self.device.cmd_pipeline_barrier(
                cmd,
                src_stage,
                dst_stage,
                vk::DependencyFlags::empty(),
                &[],
                &[],
                &[barrier],
            )
        };
        self.end_single_time_commands(cmd)
    }

    // ── Debug markers (RenderDoc/NSight) ─────────────────────────────────

    pub fn begin_debug_label(&self, cmd: vk::CommandBuffer, name: &CStr, color: [f32; 4]) {
        if let Some(debug) = &self.debug_device {
            let label = vk::DebugUtilsLabelEXT::default()
                .label_name(name)
                .color(color);
            unsafe { debug.cmd_begin_debug_utils_label(cmd, &label) };
        }
    }

    pub fn end_debug_label(&self, cmd: vk::CommandBuffer) {
        if let Some(debug) = &self.debug_device {
            unsafe { debug.cmd_end_debug_utils_label(cmd) };
        }
    }

    pub fn insert_debug_label(&self, cmd: vk::CommandBuffer, name: &CStr, color: [f32; 4]) {
        if let Some(debug) = &self.debug_device {
            let label = vk::DebugUtilsLabelEXT::default()
                .label_name(name)
                .color(color);
            unsafe { debug.cmd_insert_debug_utils_label(cmd, &label) };
        }
    }
}

impl Drop for VulkanContext {
    fn drop(&mut self) {
        unsafe {
            let _ = self.device.device_wait_idle();
            self.save_pipeline_cache();
            self.cleanup_swapchain();
            if self.pipeline_cache != vk::PipelineCache::null() {
                self.device.destroy_pipeline_cache(self.pipeline_cache, None);
            }
            if self.command_pool != vk::CommandPool::null() {
                self.device.destroy_command_pool(self.command_pool, None);
            }
            self.device.destroy_device(None);
            if let Some((debug, messenger)) = self.debug_utils.take() {
                debug.destroy_debug_utils_messenger(messenger, None);
            }
            if let Some(loader) = &self.surface_loader {
                if self.surface != vk::SurfaceKHR::null() {
                    loader.destroy_surface(self.surface, None);
                }
            }
            self.instance.destroy_instance(None);
        }
    }
}

/// ash `SampleCountFlags` lacks `min` semantics — C++ clamps with `>`.
trait SampleCountMin {
    fn min_samples_capped(self, cap: vk::SampleCountFlags) -> vk::SampleCountFlags;
}

impl SampleCountMin for vk::SampleCountFlags {
    fn min_samples_capped(self, cap: vk::SampleCountFlags) -> vk::SampleCountFlags {
        if self.as_raw() > cap.as_raw() { cap } else { self }
    }
}

// ── Free-function ports (C++ private methods that don't need &self) ──────

fn create_instance(
    entry: &Entry,
    config: &VulkanConfig,
    mut extensions: Vec<*const i8>,
) -> Result<Instance> {
    let app_name = CString::new("ArchEngine")?;
    let app_info = vk::ApplicationInfo::default()
        .application_name(&app_name)
        .application_version(vk::make_api_version(0, 1, 0, 0))
        .engine_name(&app_name)
        .engine_version(vk::make_api_version(0, 1, 0, 0))
        .api_version(vk::API_VERSION_1_2);

    if config.enable_validation {
        extensions.push(ash::ext::debug_utils::NAME.as_ptr());
    }

    // MoltenVK is a portability driver: the Vulkan loader hides portability
    // ICDs unless the instance opts in via ENUMERATE_PORTABILITY_KHR +
    // VK_KHR_portability_enumeration (required on macOS).
    #[cfg(target_os = "macos")]
    {
        extensions.push(c"VK_KHR_portability_enumeration".as_ptr());
        extensions.push(ash::khr::get_physical_device_properties2::NAME.as_ptr());
    }

    let layers: Vec<*const i8> = if config.enable_validation {
        vec![c"VK_LAYER_KHRONOS_validation".as_ptr()]
    } else {
        Vec::new()
    };

    let create_info = vk::InstanceCreateInfo::default()
        .application_info(&app_info)
        .enabled_extension_names(&extensions)
        .enabled_layer_names(&layers);

    #[cfg(target_os = "macos")]
    let create_info = create_info.flags(vk::InstanceCreateFlags::ENUMERATE_PORTABILITY_KHR);

    unsafe { entry.create_instance(&create_info, None) }.context("failed to create Vulkan instance")
}

fn setup_debug_messenger(
    entry: &Entry,
    instance: &Instance,
    config: &VulkanConfig,
) -> Result<Option<(ash::ext::debug_utils::Instance, vk::DebugUtilsMessengerEXT)>> {
    if !config.enable_validation {
        return Ok(None);
    }
    let create_info = vk::DebugUtilsMessengerCreateInfoEXT::default()
        .message_severity(
            vk::DebugUtilsMessageSeverityFlagsEXT::WARNING
                | vk::DebugUtilsMessageSeverityFlagsEXT::ERROR,
        )
        .message_type(
            vk::DebugUtilsMessageTypeFlagsEXT::GENERAL
                | vk::DebugUtilsMessageTypeFlagsEXT::VALIDATION
                | vk::DebugUtilsMessageTypeFlagsEXT::PERFORMANCE,
        )
        .pfn_user_callback(Some(debug_callback));
    let loader = ash::ext::debug_utils::Instance::new(entry, instance);
    let messenger = unsafe { loader.create_debug_utils_messenger(&create_info, None) }
        .context("failed to set up debug messenger")?;
    Ok(Some((loader, messenger)))
}

unsafe extern "system" fn debug_callback(
    severity: vk::DebugUtilsMessageSeverityFlagsEXT,
    _type: vk::DebugUtilsMessageTypeFlagsEXT,
    data: *const vk::DebugUtilsMessengerCallbackDataEXT,
    _user: *mut c_void,
) -> vk::Bool32 {
    if severity >= vk::DebugUtilsMessageSeverityFlagsEXT::WARNING {
        let msg = unsafe { CStr::from_ptr((*data).p_message) };
        eprintln!("[Vulkan] {}", msg.to_string_lossy());
    }
    vk::FALSE
}

fn pick_physical_device(
    instance: &Instance,
    surface_loader: Option<&ash::khr::surface::Instance>,
    surface: vk::SurfaceKHR,
    config: &VulkanConfig,
) -> Result<vk::PhysicalDevice> {
    let devices =
        unsafe { instance.enumerate_physical_devices() }.context("enumerate physical devices")?;
    if devices.is_empty() {
        bail!("no GPUs with Vulkan support found");
    }
    devices
        .into_iter()
        .find(|&d| is_device_suitable(instance, surface_loader, d, surface, config))
        .ok_or_else(|| anyhow!("failed to find a suitable GPU"))
}

fn is_device_suitable(
    instance: &Instance,
    surface_loader: Option<&ash::khr::surface::Instance>,
    device: vk::PhysicalDevice,
    surface: vk::SurfaceKHR,
    config: &VulkanConfig,
) -> bool {
    let indices = find_queue_families(instance, surface_loader, device, surface, config);
    if config.headless {
        // Compute uses the graphics queue; no present family needed.
        return indices.graphics_family.is_some();
    }
    let extensions_ok = check_device_extension_support(instance, device);
    let swapchain_adequate = if extensions_ok {
        let loader = surface_loader.expect("windowed mode has a surface loader");
        let (formats, modes) = unsafe {
            (
                loader.get_physical_device_surface_formats(device, surface),
                loader.get_physical_device_surface_present_modes(device, surface),
            )
        };
        matches!(formats, Ok(f) if !f.is_empty()) && matches!(modes, Ok(m) if !m.is_empty())
    } else {
        false
    };
    indices.is_complete() && extensions_ok && swapchain_adequate
}

fn check_device_extension_support(instance: &Instance, device: vk::PhysicalDevice) -> bool {
    let available = unsafe { instance.enumerate_device_extension_properties(device) }
        .unwrap_or_default();
    let has_swapchain = available.iter().any(|ext| {
        let name = unsafe { CStr::from_ptr(ext.extension_name.as_ptr()) };
        name == ash::khr::swapchain::NAME
    });
    has_swapchain
}

fn find_queue_families(
    instance: &Instance,
    surface_loader: Option<&ash::khr::surface::Instance>,
    device: vk::PhysicalDevice,
    surface: vk::SurfaceKHR,
    config: &VulkanConfig,
) -> QueueFamilyIndices {
    let families = unsafe { instance.get_physical_device_queue_family_properties(device) };
    let mut indices = QueueFamilyIndices::default();
    for (i, family) in families.iter().enumerate() {
        let i = i as u32;
        if family.queue_flags.contains(vk::QueueFlags::GRAPHICS) {
            indices.graphics_family = Some(i);
        }
        if config.headless {
            // Headless: graphics queue doubles as "present".
            indices.present_family = indices.graphics_family;
        } else if let Some(loader) = surface_loader {
            let supported = unsafe {
                loader
                    .get_physical_device_surface_support(device, i, surface)
                    .unwrap_or(false)
            };
            if supported {
                indices.present_family = Some(i);
            }
        }
        if indices.is_complete() {
            break;
        }
    }
    indices
}

fn create_logical_device(
    instance: &Instance,
    physical_device: vk::PhysicalDevice,
    queue_families: &QueueFamilyIndices,
    config: &VulkanConfig,
) -> Result<(Device, vk::PhysicalDeviceFeatures, Option<ash::ext::debug_utils::Device>)> {
    let mut unique_families = vec![queue_families.graphics_family.unwrap()];
    let present = queue_families.present_family.unwrap();
    if !unique_families.contains(&present) {
        unique_families.push(present);
    }

    let queue_priority = [1.0f32];
    let queue_infos: Vec<_> = unique_families
        .iter()
        .map(|&family| {
            vk::DeviceQueueCreateInfo::default()
                .queue_family_index(family)
                .queue_priorities(&queue_priority)
        })
        .collect();

    let supported = unsafe { instance.get_physical_device_features(physical_device) };
    let mut features = vk::PhysicalDeviceFeatures::default();
    // Divergence from the C++ (which requests these unconditionally): gate
    // every optional feature on device support. MoltenVK (Vulkan-on-Metal,
    // the target on Apple silicon) lacks `wideLines` and historically
    // `fillModeNonSolid` — requesting them unconditionally fails device
    // creation. Unavailable features degrade gracefully: lines render at
    // width 1, wireframe falls back to solid, clipping/MSAA shading/tess
    // paths check `supports_*()` before use.
    features.fill_mode_non_solid = supported.fill_mode_non_solid; // wireframe
    features.wide_lines = supported.wide_lines; // thick lines (absent on Metal)
    features.sample_rate_shading = supported.sample_rate_shading; // MSAA sample shading
    features.shader_clip_distance = supported.shader_clip_distance; // section clipping
    features.sampler_anisotropy = supported.sampler_anisotropy;
    features.tessellation_shader = supported.tessellation_shader; // displacement mapping
    for (name, on) in [
        ("fillModeNonSolid", supported.fill_mode_non_solid),
        ("wideLines", supported.wide_lines),
        ("sampleRateShading", supported.sample_rate_shading),
        ("shaderClipDistance", supported.shader_clip_distance),
        ("samplerAnisotropy", supported.sampler_anisotropy),
        ("tessellationShader", supported.tessellation_shader),
    ] {
        if on != vk::TRUE {
            tracing::warn!("device feature {name} not supported — degraded path active");
        }
    }

    // Descriptor indexing (UPDATE_AFTER_BIND) used by post-processing.
    let mut indexing = vk::PhysicalDeviceDescriptorIndexingFeatures::default();
    indexing.descriptor_binding_sampled_image_update_after_bind = vk::TRUE;
    indexing.descriptor_binding_uniform_buffer_update_after_bind = vk::TRUE;

    // Headless: no swapchain extension.
    let mut device_extensions: Vec<*const i8> = if config.headless {
        Vec::new()
    } else {
        vec![ash::khr::swapchain::NAME.as_ptr()]
    };
    // MoltenVK exposes VK_KHR_portability_subset; when present the spec
    // requires it to be enabled (macOS).
    #[cfg(target_os = "macos")]
    {
        device_extensions.push(c"VK_KHR_portability_subset".as_ptr());
    }

    let create_info = vk::DeviceCreateInfo::default()
        .queue_create_infos(&queue_infos)
        .enabled_features(&features)
        .enabled_extension_names(&device_extensions)
        .push_next(&mut indexing);

    let device = unsafe { instance.create_device(physical_device, &create_info, None) }
        .context("failed to create logical device")?;

    let debug_device = if config.enable_validation {
        Some(ash::ext::debug_utils::Device::new(instance, &device))
    } else {
        None
    };
    Ok((device, features, debug_device))
}

fn choose_swap_surface_format(formats: &[vk::SurfaceFormatKHR]) -> vk::SurfaceFormatKHR {
    for format in formats {
        if format.format == vk::Format::B8G8R8A8_SRGB
            && format.color_space == vk::ColorSpaceKHR::SRGB_NONLINEAR
        {
            return *format;
        }
    }
    formats[0]
}

fn choose_swap_present_mode(modes: &[vk::PresentModeKHR]) -> vk::PresentModeKHR {
    if modes.contains(&vk::PresentModeKHR::MAILBOX) {
        vk::PresentModeKHR::MAILBOX // triple buffering
    } else {
        vk::PresentModeKHR::FIFO // v-sync
    }
}

fn choose_swap_extent(
    capabilities: &vk::SurfaceCapabilitiesKHR,
    window_size: (u32, u32),
) -> vk::Extent2D {
    if capabilities.current_extent.width != u32::MAX {
        return capabilities.current_extent;
    }
    vk::Extent2D {
        width: window_size.0.clamp(
            capabilities.min_image_extent.width,
            capabilities.max_image_extent.width,
        ),
        height: window_size.1.clamp(
            capabilities.min_image_extent.height,
            capabilities.max_image_extent.height,
        ),
    }
}
