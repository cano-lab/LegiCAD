//! Interactive viewer application — winit event loop with a fly camera
//! (WASD + Q/E) and orbit-on-click rotation: right-press raycasts the scene
//! and the hit point becomes the orbit pivot for the drag; scroll dollies
//! while orbiting, adjusts fly speed otherwise. Esc releases cursor / quits.

use std::collections::HashSet;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Instant;

use anyhow::{Context as _, Result};
use glam::{Mat4, Vec3, Vec4};
use raw_window_handle::{HasDisplayHandle, HasWindowHandle};
use winit::application::ApplicationHandler;
use winit::event::{DeviceEvent, ElementState, MouseButton, WindowEvent};
use winit::event_loop::{ActiveEventLoop, ControlFlow, EventLoop};
use winit::keyboard::{KeyCode, PhysicalKey};
use winit::window::{CursorGrabMode, Window, WindowId};

use archengine_geometry::domain::StructuralElement;

use crate::camera::Camera;
use crate::scene;
use crate::ui::overlay::UiFrame;
use crate::ui::{FrameStats, UiActions, UiState};
use crate::vulkan::context::{VulkanConfig, VulkanContext};
use crate::vulkan::environment::EnvironmentMap;
use crate::vulkan::raster::{DrawItem, GpuMesh, Renderer};

struct SceneMesh {
    gpu: GpuMesh,
    stress: f32,
    /// Albedo push colour (`scene::material_color` palette) — structural.*
    /// ignores vertex colours, so the per-element colour rides the push
    /// constant instead.
    color: Vec3,
    /// PBR multipliers (`scene::material_props`): metallic, roughness, ao,
    /// emission.
    material: Vec4,
    /// CPU-side copy for pivot raycasting (orbit-on-click).
    cpu: archengine_geometry::mesh_gen::PrimitiveMesh,
}

/// The renderer holds a raw pointer to the Vulkan context (mirroring the
/// C++ `Renderer`'s `VulkanContext*`). The context lives in a `Box` (stable
/// heap address) and is dropped *after* the renderer via `Drop for App` —
/// the invariants documented on [`Renderer`].
struct App {
    window: Option<Arc<Window>>,
    ctx: Option<Box<VulkanContext>>,
    renderer: Option<Renderer>,
    env: Option<EnvironmentMap>,
    env_path: Option<PathBuf>,
    meshes: Vec<SceneMesh>,
    camera: Camera,
    keys: HashSet<KeyCode>,
    yaw: f32,
    pitch: f32,
    cursor_grabbed: bool,
    last_frame: Instant,
    last_dt: f32,
    fps_smooth: f32,
    quit_requested: bool,

    // Orbit-on-click: right-press raycasts the scene and the hit point
    // becomes the pivot the camera orbits while dragging.
    cursor_pos: (f64, f64),
    pivot: Option<Vec3>,
    orbit_distance: f32,
    scene_center: Vec3,
    scene_radius: f32,

    // egui overlay (pure-Rust replacement for the legacy ImGui layer).
    egui_ctx: egui::Context,
    egui_state: Option<egui_winit::State>,
    ui: UiState,
}

impl Drop for App {
    fn drop(&mut self) {
        // Renderer + env map (reference ctx resources) must die before ctx.
        self.renderer.take();
        self.env.take();
        self.ctx.take();
        self.window.take();
    }
}

impl ApplicationHandler for App {
    fn resumed(&mut self, event_loop: &ActiveEventLoop) {
        if self.window.is_some() {
            return;
        }
        let attrs = Window::default_attributes()
            .with_title("ArchEngine — LegiCAD")
            .with_inner_size(winit::dpi::LogicalSize::new(1600.0, 900.0));
        let window = Arc::new(
            event_loop
                .create_window(attrs)
                .expect("failed to create window"),
        );

        let size_window = Arc::clone(&window);
        let ctx = Box::new(
            VulkanContext::new(
                window.display_handle().unwrap().as_raw(),
                window.window_handle().unwrap().as_raw(),
                move || {
                    let size = size_window.inner_size();
                    (size.width, size.height)
                },
                VulkanConfig::default(),
            )
            .expect("failed to initialize Vulkan"),
        );

        // Store the context first so the renderer points at the stable heap
        // location, then create the renderer.
        self.ctx = Some(ctx);
        self.renderer = Some(
            Renderer::new(self.ctx.as_mut().unwrap()).expect("failed to create renderer"),
        );

        // Environment: HDRI when --env was given, otherwise the C++
        // procedural sky (bound as cubemap but rendered procedurally).
        let mut env =
            EnvironmentMap::new(self.ctx.as_ref().unwrap()).expect("failed to create env map");
        let use_hdr = match &self.env_path {
            Some(path) => {
                env.load_from_file(path).expect("failed to load HDRI");
                true
            }
            None => {
                env.create_procedural_sky().expect("failed to create sky");
                false
            }
        };
        self.renderer
            .as_mut()
            .unwrap()
            .set_environment(&env, use_hdr);
        self.env = Some(env);

        // egui overlay: GPU side (render pass + pipelines) then the
        // winit-egui bridge (needs the window for scale factor + events).
        self.renderer
            .as_mut()
            .unwrap()
            .init_ui()
            .expect("failed to init egui overlay");
        self.egui_state = Some(egui_winit::State::new(
            self.egui_ctx.clone(),
            egui::ViewportId::ROOT,
            window.as_ref(),
            Some(window.scale_factor() as f32),
            None,
            None,
        ));

        self.window = Some(window);
        self.last_frame = Instant::now();
    }

    fn window_event(&mut self, event_loop: &ActiveEventLoop, _id: WindowId, event: WindowEvent) {
        // egui sees every event first; when it consumes one (clicks on
        // panels, typing in fields) the game camera must not act on it.
        if let (Some(state), Some(window)) = (&mut self.egui_state, &self.window) {
            let response = state.on_window_event(window, &event);
            if response.consumed {
                return;
            }
        }

        match event {
            WindowEvent::CloseRequested => event_loop.exit(),
            WindowEvent::KeyboardInput { event, .. } => {
                let pressed = event.state == ElementState::Pressed;
                if let PhysicalKey::Code(code) = event.physical_key {
                    if pressed {
                        if code == KeyCode::Escape {
                            if self.cursor_grabbed {
                                self.set_cursor_grab(false);
                            } else {
                                event_loop.exit();
                            }
                            return;
                        }
                        if code == KeyCode::F1 {
                            self.ui.visible = !self.ui.visible;
                            return;
                        }
                        if code == KeyCode::KeyF {
                            self.frame_scene();
                            return;
                        }
                        // Don't fly the camera while typing in a UI field.
                        if self.egui_ctx.egui_wants_keyboard_input() {
                            return;
                        }
                        self.keys.insert(code);
                    } else {
                        self.keys.remove(&code);
                    }
                }
            }
            WindowEvent::CursorMoved { position, .. } => {
                self.cursor_pos = (position.x, position.y);
            }
            WindowEvent::MouseInput { state, button, .. } => {
                if button == MouseButton::Right && !self.egui_ctx.egui_wants_pointer_input() {
                    if state == ElementState::Pressed {
                        // Orbit-on-click: the point under the cursor becomes
                        // the pivot for this drag.
                        let pivot = self.pick_pivot();
                        self.orbit_distance =
                            self.camera.position.distance(pivot).max(0.1);
                        self.pivot = Some(pivot);
                    } else {
                        self.pivot = None;
                    }
                    self.set_cursor_grab(state == ElementState::Pressed);
                }
            }
            WindowEvent::MouseWheel { delta, .. } => {
                if self.egui_ctx.egui_wants_pointer_input() {
                    return;
                }
                let amount = match delta {
                    winit::event::MouseScrollDelta::LineDelta(_, y) => y,
                    winit::event::MouseScrollDelta::PixelDelta(p) => p.y as f32 * 0.1,
                };
                if self.pivot.is_some() {
                    // While orbiting, scroll dollies toward/away from the pivot.
                    self.orbit_distance =
                        (self.orbit_distance * (1.0 - amount * 0.1)).clamp(0.1, 1.0e7);
                } else {
                    // Zoom toward the point under the cursor: it stays fixed
                    // on screen as the camera slides along the pick ray.
                    let dir = self.cursor_ray();
                    let target = self.cursor_point(dir);
                    let factor = (1.0 - amount * 0.15).clamp(0.5, 2.0);
                    self.camera.position = target + (self.camera.position - target) * factor;
                }
            }
            WindowEvent::RedrawRequested => {
                self.update_camera();
                self.draw();
                if self.quit_requested {
                    event_loop.exit();
                }
            }
            _ => {}
        }
    }

    fn device_event(
        &mut self,
        _event_loop: &ActiveEventLoop,
        _id: winit::event::DeviceId,
        event: DeviceEvent,
    ) {
        if self.cursor_grabbed {
            if let DeviceEvent::MouseMotion { delta: (dx, dy) } = event {
                let sensitivity = self.camera.sensitivity * 0.0025;
                self.yaw -= dx as f32 * sensitivity;
                self.pitch = (self.pitch - dy as f32 * sensitivity).clamp(-1.55, 1.55);
            }
        }
    }

    fn about_to_wait(&mut self, _event_loop: &ActiveEventLoop) {
        if let Some(window) = &self.window {
            window.request_redraw();
        }
    }
}

impl App {
    fn set_cursor_grab(&mut self, grabbed: bool) {
        if let Some(window) = &self.window {
            if grabbed {
                // Locked is unsupported on some platforms (incl. macOS) —
                // fall back to Confined, as the C++ does with GLFW raw input.
                window
                    .set_cursor_grab(CursorGrabMode::Locked)
                    .or_else(|_| window.set_cursor_grab(CursorGrabMode::Confined))
                    .ok();
                // winit 0.30's invisible cursor crashes on macOS 26
                // (EXC_ARM_DA_ALIGN in ImageIO parsing winit's embedded
                // cursor GIF) — keep the cursor visible there.
                #[cfg(not(target_os = "macos"))]
                window.set_cursor_visible(false);
            } else {
                window.set_cursor_grab(CursorGrabMode::None).ok();
                window.set_cursor_visible(true);
            }
        }
        self.cursor_grabbed = grabbed;
    }

    /// Ray from the camera through the cursor, in world space (view-space
    /// construction avoids projection Y-flip conventions).
    fn cursor_ray(&self) -> Vec3 {
        let Some(window) = &self.window else {
            return self.scene_center - self.camera.position;
        };
        let size = window.inner_size();
        let (w, h) = (size.width.max(1) as f32, size.height.max(1) as f32);
        let (cx, cy) = (self.cursor_pos.0 as f32, self.cursor_pos.1 as f32);

        let (sin_yaw, cos_yaw) = self.yaw.sin_cos();
        let (sin_pitch, cos_pitch) = self.pitch.sin_cos();
        let forward = Vec3::new(cos_yaw * cos_pitch, sin_pitch, sin_yaw * cos_pitch);
        let right = forward.cross(Vec3::Y).normalize_or_zero();
        let up = right.cross(forward);

        let ndc_x = 2.0 * cx / w - 1.0;
        let ndc_y = 1.0 - 2.0 * cy / h;
        let tan_half = (self.camera.fov.to_radians() * 0.5).tan();
        (forward + right * (ndc_x * tan_half * w / h) + up * (ndc_y * tan_half))
            .normalize_or_zero()
    }

    /// Point under the cursor: nearest triangle hit, or a point at the
    /// scene-centre distance along the ray when nothing is hit.
    fn cursor_point(&self, dir: Vec3) -> Vec3 {
        match raycast_meshes(&self.meshes, self.camera.position, dir) {
            Some(t) => self.camera.position + dir * t,
            None => {
                let fallback = self.camera.position.distance(self.scene_center).max(1.0);
                self.camera.position + dir * fallback
            }
        }
    }

    /// World-space point under the cursor, for orbit-on-click.
    fn pick_pivot(&self) -> Vec3 {
        self.cursor_point(self.cursor_ray())
    }

    /// Reset the camera to frame the whole scene (F key) — the recovery
    /// move when you've zoomed or flown off into empty space.
    fn frame_scene(&mut self) {
        let radius = self.scene_radius;
        self.camera.position = self.scene_center + Vec3::new(radius, radius * 0.5, radius);
        self.camera.target = self.scene_center;
        let d = (self.camera.target - self.camera.position).normalize();
        self.yaw = d.z.atan2(d.x);
        self.pitch = d.y.asin();
    }

    fn update_camera(&mut self) {
        let now = Instant::now();
        let dt = (now - self.last_frame).as_secs_f32();
        self.last_frame = now;
        self.last_dt = dt;
        let fps = if dt > 0.0 { 1.0 / dt } else { 0.0 };
        self.fps_smooth = if self.fps_smooth == 0.0 {
            fps
        } else {
            0.9 * self.fps_smooth + 0.1 * fps
        };

        let (sin_yaw, cos_yaw) = self.yaw.sin_cos();
        let (sin_pitch, cos_pitch) = self.pitch.sin_cos();
        let forward = Vec3::new(cos_yaw * cos_pitch, sin_pitch, sin_yaw * cos_pitch);
        let right = forward.cross(Vec3::Y).normalize_or_zero();

        let mut movement = Vec3::ZERO;
        for (key, dir) in [
            (KeyCode::KeyW, forward),
            (KeyCode::KeyS, -forward),
            (KeyCode::KeyD, right),
            (KeyCode::KeyA, -right),
            (KeyCode::KeyE, Vec3::Y),
            (KeyCode::KeyQ, Vec3::NEG_Y),
        ] {
            if self.keys.contains(&key) {
                movement += dir;
            }
        }
        let delta = if movement != Vec3::ZERO {
            movement.normalize() * self.camera.speed * dt
        } else {
            Vec3::ZERO
        };

        if let Some(pivot) = self.pivot {
            // Orbit mode: WASD pans the pivot (camera follows), mouse drag
            // rotates around it at the captured distance.
            let pivot = pivot + delta;
            self.pivot = Some(pivot);
            self.camera.position = pivot - forward * self.orbit_distance;
            self.camera.target = pivot;
        } else {
            self.camera.position += delta;
            self.camera.target = self.camera.position + forward;
        }
    }

    fn draw(&mut self) {
        // Build the egui frame (input → panel code → tessellated output).
        let ui_frame = self.build_ui_frame();

        // Apply settings the raster path consumes.
        if let Some(renderer) = &mut self.renderer {
            renderer.set_sky_enabled(self.ui.settings.show_sky);
        }

        let Some(renderer) = &mut self.renderer else {
            return;
        };
        let draws: Vec<DrawItem> = self
            .meshes
            .iter()
            .map(|m| DrawItem {
                mesh: &m.gpu,
                model: Mat4::IDENTITY, // meshes are built in world space
                color: m.color.extend(m.stress),
                material: m.material,
            })
            .collect();
        if let Err(e) = renderer.draw_frame(&self.camera, &draws, ui_frame) {
            tracing::error!("draw_frame failed: {e:#}");
        }
    }

    /// Run one egui frame and pack its GPU-ready output. Returns `None`
    /// when the overlay is hidden or not yet initialized.
    fn build_ui_frame(&mut self) -> Option<UiFrame> {
        if !self.ui.visible {
            return None;
        }
        let (state, window) = (self.egui_state.as_mut()?, self.window.as_ref()?.clone());

        let stats = FrameStats {
            fps: self.fps_smooth,
            frame_ms: self.last_dt * 1000.0,
            draw_calls: self.meshes.len() as u32,
            triangles: self
                .meshes
                .iter()
                .map(|m| m.gpu.index_count / 3)
                .sum(),
            camera_pos: self.camera.position,
            camera_yaw: self.yaw,
        };

        let egui_ctx = self.egui_ctx.clone();
        let input = state.take_egui_input(&window);
        let mut actions = UiActions::default();
        let full_output = egui_ctx.run_ui(input, |ui| {
            actions = self.ui.draw(ui, &stats);
        });
        state.handle_platform_output(&window, full_output.platform_output);

        self.handle_ui_actions(actions);

        let primitives = egui_ctx.tessellate(full_output.shapes, full_output.pixels_per_point);
        Some(UiFrame {
            textures_delta: full_output.textures_delta,
            primitives,
            pixels_per_point: full_output.pixels_per_point,
        })
    }

    /// Execute the commands the overlay produced this frame.
    fn handle_ui_actions(&mut self, actions: UiActions) {
        if actions.toggle_cursor_grab {
            self.set_cursor_grab(!self.cursor_grabbed);
        }
        if actions.quit {
            self.quit_requested = true;
        }
        if let Some(path) = actions.load_env {
            let Some(ctx) = &self.ctx else { return };
            match EnvironmentMap::new(ctx)
                .and_then(|mut env| env.load_from_file(&path).map(|()| env))
            {
                Ok(env) => {
                    if let Some(renderer) = &mut self.renderer {
                        renderer.set_environment(&env, true);
                    }
                    self.env = Some(env);
                    tracing::info!(path = %path.display(), "HDRI environment loaded");
                }
                Err(e) => {
                    tracing::error!(path = %path.display(), "failed to load HDRI: {e:#}");
                }
            }
        }
    }
}

/// Open the interactive viewer on a scene of structural elements.
/// `env_path` optionally points at an equirectangular HDR for the sky.
pub fn run_viewer(elements: &[StructuralElement], env_path: Option<PathBuf>) -> Result<()> {
    let event_loop = EventLoop::new().context("failed to create event loop")?;
    event_loop.set_control_flow(ControlFlow::Poll);

    // Convert the scene to meshes now; upload happens on the first redraw,
    // once the renderer exists (created in `resumed`).
    let primitives: Vec<PrimitiveEntry> = elements
        .iter()
        .filter_map(|e| {
            scene::element_to_mesh(e).map(|m| {
                (
                    m,
                    e.stress,
                    scene::material_color(&e.material, e.element_type),
                    scene::material_props(&e.material, e.element_type),
                )
            })
        })
        .collect();
    if primitives.is_empty() {
        anyhow::bail!("scene produced no geometry");
    }
    tracing::info!(meshes = primitives.len(), "scene converted");

    // Frame the scene: camera looks at the centroid from a 3/4 view.
    let mut min = Vec3::splat(f32::MAX);
    let mut max = Vec3::splat(f32::MIN);
    for (mesh, ..) in &primitives {
        for v in &mesh.vertices {
            min = min.min(v.position);
            max = max.max(v.position);
        }
    }
    let center = (min + max) * 0.5;
    let radius = (max - min).length().max(5.0);
    let mut camera = Camera::default();
    camera.position = center + Vec3::new(radius, radius * 0.5, radius);
    camera.target = center;
    camera.far_plane = (radius * 20.0).max(1000.0);
    // Scale the near plane with the scene: mm-scale scenes (radius ~10⁴)
    // with the 0.1 default push depth precision past the 24-bit buffer and
    // coplanar-ish surfaces (wall faces, door panels) z-fight into sawteeth.
    camera.near_plane = (radius * 0.01).max(0.05);
    let d = (camera.target - camera.position).normalize();
    let (yaw, pitch) = (d.z.atan2(d.x), d.y.asin());

    let mut app = App {
        window: None,
        ctx: None,
        renderer: None,
        env: None,
        env_path,
        meshes: Vec::new(),
        camera,
        keys: HashSet::new(),
        yaw,
        pitch,
        cursor_grabbed: false,
        last_frame: Instant::now(),
        last_dt: 0.0,
        fps_smooth: 0.0,
        quit_requested: false,
        cursor_pos: (0.0, 0.0),
        pivot: None,
        orbit_distance: 0.0,
        scene_center: center,
        scene_radius: radius,
        egui_ctx: egui::Context::default(),
        egui_state: None,
        ui: UiState::default(),
    };
    let mut state = UploadState {
        pending: Some(primitives),
    };

    event_loop
        .run_app(&mut AppRunner {
            app: &mut app,
            state: &mut state,
        })
        .context("event loop error")?;

    // On macOS, winit recommends exiting the process after the loop ends
    // rather than returning to a caller that might create a new loop.
    Ok(())
}

/// Möller–Trumbore ray intersection over the CPU-side scene meshes.
/// Returns the nearest hit distance along `dir` (must be normalised).
fn raycast_meshes(meshes: &[SceneMesh], origin: Vec3, dir: Vec3) -> Option<f32> {
    let mut best = f32::MAX;
    for mesh in meshes {
        let verts = &mesh.cpu.vertices;
        for tri in mesh.cpu.indices.chunks_exact(3) {
            let p0 = verts[tri[0] as usize].position;
            let p1 = verts[tri[1] as usize].position;
            let p2 = verts[tri[2] as usize].position;
            let e1 = p1 - p0;
            let e2 = p2 - p0;
            let p = dir.cross(e2);
            let det = e1.dot(p);
            if det.abs() < 1e-8 {
                continue; // ray parallel to triangle
            }
            let inv = 1.0 / det;
            let tvec = origin - p0;
            let u = tvec.dot(p) * inv;
            if !(0.0..=1.0).contains(&u) {
                continue;
            }
            let q = tvec.cross(e1);
            let v = dir.dot(q) * inv;
            if v < 0.0 || u + v > 1.0 {
                continue;
            }
            let t = e2.dot(q) * inv;
            if t > 0.0 && t < best {
                best = t;
            }
        }
    }
    (best < f32::MAX).then_some(best)
}

/// Pending scene geometry: mesh + stress + push-constant colour/material.
type PrimitiveEntry = (
    archengine_geometry::mesh_gen::PrimitiveMesh,
    f32,
    Vec3,
    Vec4,
);

struct UploadState {
    pending: Option<Vec<PrimitiveEntry>>,
}

/// ApplicationHandler that owns the upload-once logic and delegates all
/// events to the real app.
struct AppRunner<'a> {
    app: &'a mut App,
    state: &'a mut UploadState,
}

impl ApplicationHandler for AppRunner<'_> {
    fn resumed(&mut self, event_loop: &ActiveEventLoop) {
        self.app.resumed(event_loop);
        if let (Some(renderer), Some(prims)) = (&self.app.renderer, self.state.pending.take()) {
            self.app.meshes = prims
                .into_iter()
                .filter_map(|(mesh, stress, color, material)| match renderer.upload_mesh(&mesh) {
                    Ok(gpu) => Some(SceneMesh {
                        gpu,
                        stress,
                        color,
                        material,
                        cpu: mesh,
                    }),
                    Err(e) => {
                        tracing::warn!("mesh upload failed: {e:#}");
                        None
                    }
                })
                .collect();
            tracing::info!(uploaded = self.app.meshes.len(), "meshes uploaded");
        }
    }

    fn window_event(&mut self, event_loop: &ActiveEventLoop, id: WindowId, event: WindowEvent) {
        self.app.window_event(event_loop, id, event);
    }

    fn device_event(
        &mut self,
        event_loop: &ActiveEventLoop,
        id: winit::event::DeviceId,
        event: DeviceEvent,
    ) {
        self.app.device_event(event_loop, id, event);
    }

    fn about_to_wait(&mut self, event_loop: &ActiveEventLoop) {
        self.app.about_to_wait(event_loop);
    }
}
