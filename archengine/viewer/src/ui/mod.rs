//! egui overlay — pure-Rust replacement for the legacy Dear ImGui layer
//! (`imgui_layer.cpp`, 3,314 LOC C++/Dear ImGui).
//!
//! Port decision (questions.md A4 checklist): imgui-rs is a Rust API over
//! the C++ Dear ImGui core; egui is 100% Rust, so the overlay becomes Rust
//! end-to-end (`egui` + `egui-winit` + `egui-ash-renderer` on our ash
//! 0.38 / winit 0.30 / MoltenVK stack).
//!
//! Scope: the demo-critical panels — menu bar, performance, render
//! settings (environment/exposure), help, compass. The C++ layer's
//! authoring surfaces (geometry editor, wall editor, material library /
//! inspector / test windows, async material-generation status) are studio
//! tooling and deliberately deferred — they depend on systems that do not
//! exist in the Rust port yet.
//!
//! The GPU half (Vulkan render pass + [`egui_ash_renderer::Renderer`])
//! lives in [`overlay`].

pub mod overlay;

use std::path::PathBuf;

use glam::Vec3;

/// Per-frame numbers the app feeds into the panels (C++:
/// `drawPerformancePanel(fps, drawCalls, triangles, culledElements)`).
pub struct FrameStats {
    pub fps: f32,
    pub frame_ms: f32,
    pub draw_calls: u32,
    pub triangles: u32,
    pub camera_pos: Vec3,
    /// Radians, 0 = -Z (north), increasing clockwise (C++ cameraYaw).
    pub camera_yaw: f32,
}

/// Commands the overlay sends back to the app after each frame.
#[derive(Default)]
pub struct UiActions {
    /// User asked to load an HDRI environment (Render Settings → Load).
    pub load_env: Option<PathBuf>,
    /// User toggled cursor capture from the Tools menu.
    pub toggle_cursor_grab: bool,
    /// User asked to quit from the Tools menu.
    pub quit: bool,
}

/// Render settings mirrored into the overlay. Only settings that the
/// current raster path actually consumes appear here — the C++ panel's
/// env intensity/rotation/exposure sliders drive the path tracer and
/// post chain, which the interactive viewer does not embed yet (they are
/// archrender CLI flags in the port; see todo #8).
#[derive(Default)]
pub struct RenderSettings {
    /// Draw the sky pass at all.
    pub show_sky: bool,
}

impl RenderSettings {
    fn new() -> Self {
        Self { show_sky: true }
    }
}

/// Overlay state — window visibility toggles + mirrored settings.
/// C++ equivalent: the `show*` booleans scattered through the viewer app.
pub struct UiState {
    /// Master toggle for the whole overlay (F1, like the C++ `uiVisible`).
    pub visible: bool,
    pub show_performance: bool,
    pub show_render_settings: bool,
    pub show_help: bool,
    pub show_compass: bool,
    pub settings: RenderSettings,
    /// Editable HDRI path in the render settings panel.
    pub env_path_input: String,
}

impl Default for UiState {
    fn default() -> Self {
        Self {
            visible: true,
            show_performance: true,
            show_render_settings: false,
            show_help: false,
            show_compass: true,
            settings: RenderSettings::new(),
            env_path_input: String::new(),
        }
    }
}

impl UiState {
    /// Build all UI for one frame; returns the actions the app should run.
    /// Call inside `egui::Context::run_ui` (egui 0.36: panels attach to the
    /// root `Ui`, windows/areas attach to the `Context`).
    pub fn draw(&mut self, ui: &mut egui::Ui, stats: &FrameStats) -> UiActions {
        let mut actions = UiActions::default();
        if !self.visible {
            return actions;
        }

        self.draw_menu_bar(ui, &mut actions);
        let ctx = ui.ctx().clone();
        if self.show_performance {
            self.draw_performance(&ctx, stats);
        }
        if self.show_render_settings {
            self.draw_render_settings(&ctx, &mut actions);
        }
        if self.show_help {
            self.draw_help(&ctx);
        }
        if self.show_compass {
            self.draw_compass(&ctx, stats.camera_yaw);
        }
        actions
    }

    /// C++ `drawMainMenuBar` — View/Tools menus.
    fn draw_menu_bar(&mut self, root: &mut egui::Ui, actions: &mut UiActions) {
        egui::Panel::top("menu_bar").show(root, |ui| {
            egui::MenuBar::new().ui(ui, |ui| {
                ui.menu_button("View", |ui| {
                    ui.checkbox(&mut self.show_performance, "Performance");
                    ui.checkbox(&mut self.show_render_settings, "Render Settings");
                    ui.checkbox(&mut self.show_help, "Help");
                    ui.checkbox(&mut self.show_compass, "Compass");
                });
                ui.menu_button("Tools", |ui| {
                    if ui.button("Release/Capture Cursor").clicked() {
                        actions.toggle_cursor_grab = true;
                        ui.close();
                    }
                    if ui.button("Quit").clicked() {
                        actions.quit = true;
                        ui.close();
                    }
                });
            });
        });
    }

    /// C++ `drawPerformancePanel` — fps / frame time / draw stats.
    fn draw_performance(&self, ctx: &egui::Context, stats: &FrameStats) {
        egui::Window::new("Performance")
            .resizable(false)
            .default_pos([10.0, 40.0])
            .show(ctx, |ui| {
                ui.label(format!("FPS: {:.1}", stats.fps));
                ui.label(format!("Frame: {:.2} ms", stats.frame_ms));
                ui.label(format!("Draw calls: {}", stats.draw_calls));
                ui.label(format!("Triangles: {}", stats.triangles));
                ui.separator();
                ui.label(format!(
                    "Camera: ({:.1}, {:.1}, {:.1})",
                    stats.camera_pos.x, stats.camera_pos.y, stats.camera_pos.z
                ));
            });
    }

    /// C++ `drawRenderSettingsPanel` (subset: Environment + Tonemapping
    /// sections — the parts the current renderer supports).
    fn draw_render_settings(&mut self, ctx: &egui::Context, actions: &mut UiActions) {
        egui::Window::new("Render Settings")
            .default_pos([10.0, 220.0])
            .show(ctx, |ui| {
                egui::CollapsingHeader::new("Environment")
                    .default_open(true)
                    .show(ui, |ui| {
                        ui.checkbox(&mut self.settings.show_sky, "Draw sky");
                        ui.horizontal(|ui| {
                            ui.label("HDRI:");
                            ui.add(
                                egui::TextEdit::singleline(&mut self.env_path_input)
                                    .desired_width(220.0)
                                    .hint_text("path/to/sky.hdr"),
                            );
                            if ui.button("Load").clicked() && !self.env_path_input.is_empty() {
                                actions.load_env =
                                    Some(PathBuf::from(self.env_path_input.trim()));
                            }
                        });
                    });
            });
    }

    /// C++ `drawHelpPanel` — controls reference.
    fn draw_help(&mut self, ctx: &egui::Context) {
        egui::Window::new("Help")
            .open(&mut self.show_help)
            .default_pos([400.0, 80.0])
            .show(ctx, |ui| {
                ui.heading("Controls");
                ui.separator();
                for (key, what) in [
                    ("W A S D", "Move (pan while orbiting)"),
                    ("Q / E", "Down / Up"),
                    ("Right mouse drag", "Orbit around clicked point"),
                    ("Scroll", "Zoom to cursor"),
                    ("F", "Frame scene (zoom to fit)"),
                    ("F1", "Toggle overlay"),
                    ("Esc", "Release cursor / quit"),
                ] {
                    ui.horizontal(|ui| {
                        ui.monospace(format!("{key:>18}"));
                        ui.label(what);
                    });
                }
            });
    }

    /// C++ `drawCompassOverlay` — cardinal direction from camera yaw.
    /// Simplified to a small centred readout (the C++ draws a tick ring on
    /// an overlay draw list; the information content is the heading).
    fn draw_compass(&self, ctx: &egui::Context, yaw: f32) {
        const DIRS: [&str; 8] = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
        // yaw: 0 = north (-Z), increasing clockwise.
        let idx = (((-yaw).to_degrees() / 45.0).round() as i32).rem_euclid(8) as usize;
        egui::Area::new(egui::Id::new("compass"))
            .anchor(egui::Align2::CENTER_TOP, [0.0, 34.0])
            .show(ctx, |ui| {
                egui::Frame::window(&ctx.style_of(ctx.theme()))
                    .inner_margin(egui::Margin::symmetric(12, 4))
                    .show(ui, |ui| {
                        ui.heading(DIRS[idx]);
                    });
            });
    }
}
