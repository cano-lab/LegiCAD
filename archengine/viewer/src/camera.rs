//! Port of the C++ `Camera` struct (`include/types.hpp`).
//!
//! GLM conventions carry over: `GLM_FORCE_DEPTH_ZERO_TO_ONE` → glam's
//! `perspective_rh` / `orthographic_rh` (Vulkan depth 0..1), and
//! `glm::lookAt` → `Mat4::look_at_rh`.

use glam::{Mat4, Vec3};

pub use archengine_geometry::domain::CameraView;

/// Scene camera — field-for-field port of C++ `arch::Camera`.
#[derive(Debug, Clone)]
pub struct Camera {
    pub position: Vec3,
    /// Look-at target.
    pub target: Vec3,
    pub up: Vec3,
    pub fov: f32,
    pub near_plane: f32,
    pub far_plane: f32,
    pub speed: f32,
    pub sensitivity: f32,
    pub is_orthographic: bool,
    /// Half-width for orthographic projection.
    pub ortho_size: f32,
    pub view: CameraView,
}

impl Default for Camera {
    fn default() -> Self {
        Self {
            position: Vec3::new(0.0, 5.0, 20.0),
            target: Vec3::ZERO,
            up: Vec3::Y,
            fov: 45.0,
            near_plane: 0.1,
            far_plane: 1000.0,
            speed: 10.0,
            sensitivity: 0.1,
            is_orthographic: false,
            ortho_size: 50.0,
            view: CameraView::Perspective,
        }
    }
}

impl Camera {
    /// `glm::lookAt(position, target, up)`.
    pub fn view_matrix(&self) -> Mat4 {
        Mat4::look_at_rh(self.position, self.target, self.up)
    }

    /// `glm::perspective(radians(fov), aspect, near, far)` with
    /// `GLM_FORCE_DEPTH_ZERO_TO_ONE`, or `glm::ortho(...)` when
    /// `is_orthographic`.
    pub fn projection_matrix(&self, aspect_ratio: f32) -> Mat4 {
        if self.is_orthographic {
            let half_width = self.ortho_size;
            let half_height = self.ortho_size / aspect_ratio;
            Mat4::orthographic_rh(
                -half_width,
                half_width,
                -half_height,
                half_height,
                self.near_plane,
                self.far_plane,
            )
        } else {
            Mat4::perspective_rh(
                self.fov.to_radians(),
                aspect_ratio,
                self.near_plane,
                self.far_plane,
            )
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_camera_matches_cpp() {
        let cam = Camera::default();
        assert_eq!(cam.position, Vec3::new(0.0, 5.0, 20.0));
        assert_eq!(cam.fov, 45.0);
        assert_eq!(cam.near_plane, 0.1);
        assert_eq!(cam.far_plane, 1000.0);
    }

    #[test]
    fn perspective_uses_zero_to_one_depth() {
        // With GLM_FORCE_DEPTH_ZERO_TO_ONE, the near plane maps to z_ndc = 0
        // and the far plane to z_ndc = 1 (clip z in [0, w]).
        let cam = Camera::default();
        let proj = cam.projection_matrix(16.0 / 9.0);
        let near = proj * Vec3::new(0.0, 0.0, -cam.near_plane).extend(1.0);
        let far = proj * Vec3::new(0.0, 0.0, -cam.far_plane).extend(1.0);
        assert!((near.z / near.w).abs() < 1e-5);
        assert!((far.z / far.w - 1.0).abs() < 1e-3);
    }
}
