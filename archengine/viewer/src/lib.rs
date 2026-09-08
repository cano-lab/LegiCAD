//! ArchEngine viewer — Vulkan renderer + compute path tracer.
//!
//! **Status: active port.** Decision recorded in `questions.md` A4 (Jer,
//! 2026-09-08): the legacy C++ Vulkan renderer at
//! `legacy/archengine/ArchEngine_kernel/` (~41k LOC C++ + ~3.1k LOC GLSL,
//! raw Vulkan, game-style navigation + compute-shader path tracing) is being
//! ported to Rust on `ash` 0.38. GLSL shaders are kept verbatim and compiled
//! to SPIR-V by `build.rs` (shaderc).
//!
//! Port order (demos first):
//! 1. `vulkan::context` — instance/device/queues/swapchain (this milestone)
//! 2. Raster pipeline (`structural.vert/frag`) + mesh upload from
//!    `archengine_geometry` — real-time "game" navigation
//! 3. Path tracer (`path_trace.comp`) — progressive Monte Carlo, GGX PBR,
//!    NEE, Russian roulette, ACES — traverses the BVH from
//!    `archengine_geometry::bvh` (layouts were designed for these shaders)
//! 4. Post chain (bloom/SSAO/SSR/denoise) + environment-map IBL
//!
//! Deliberate divergences from the C++ source:
//! - `memory.hpp` (CPU-side arena/pool/leak tracking) is **not** ported —
//!   Rust ownership replaces it. Vulkan buffer/image helpers live on
//!   [`vulkan::context::VulkanContext`] as in the C++.
//! - Optional device features are gated on support (C++ requested them
//!   unconditionally) — required for MoltenVK on the M1 target.
//! - Window access: C++ polls a `Window` object for framebuffer size; here
//!   the app supplies a `window_size: impl Fn() -> (u32, u32)` at
//!   construction (winit owns the window).
//!
//! Deferred but committed to re-adding (see `questions.md` A4 checklist):
//! environment-map IBL, Polyhaven texture array, OIDN denoise, ImGui.

pub mod camera;
#[cfg(feature = "windowed")]
pub mod app;
pub mod scene;
pub mod vulkan;
