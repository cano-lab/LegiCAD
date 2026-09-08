//! `SlicePlane` and 3D → 2D projection math.
//!
//! Ported from `slicer_2d.hpp:108-153` and `slicer_2d.cpp:57-111`.

use crate::primitives::Point2D;
use glam::{Vec2, Vec3};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Default)]
#[repr(u32)]
pub enum SlicePlaneType {
    /// Plan view at a given Y (height).
    #[default]
    Horizontal,
    /// Section looking north-south (XZ plane at Y).
    VerticalNS,
    /// Section looking east-west (YZ plane at X).
    VerticalEW,
    /// Arbitrary plane defined by `normal` + `origin`.
    Custom,
}

#[derive(Debug, Clone, PartialEq)]
pub struct SlicePlane {
    pub plane_type: SlicePlaneType,
    /// Y for Horizontal, Z for VerticalNS, X for VerticalEW.
    pub position: f32,
    /// Normal for the Custom case.
    pub normal: Vec3,
    /// Origin for the Custom case.
    pub origin: Vec3,
    pub name: String,
}

impl Default for SlicePlane {
    fn default() -> Self {
        Self {
            plane_type: SlicePlaneType::Horizontal,
            position: 0.0,
            normal: Vec3::Z,
            origin: Vec3::ZERO,
            name: String::new(),
        }
    }
}

impl SlicePlane {
    /// Horizontal cut at the given height (Y).
    #[must_use]
    pub fn horizontal(height: f32, name: impl Into<String>) -> Self {
        Self {
            plane_type: SlicePlaneType::Horizontal,
            position: height,
            normal: Vec3::Y,
            origin: Vec3::new(0.0, height, 0.0),
            name: name.into(),
        }
    }

    /// Vertical section (N-S) at the given Z.
    #[must_use]
    pub fn section_ns(z_position: f32, name: impl Into<String>) -> Self {
        Self {
            plane_type: SlicePlaneType::VerticalNS,
            position: z_position,
            normal: Vec3::Z,
            origin: Vec3::new(0.0, 0.0, z_position),
            name: name.into(),
        }
    }

    /// Vertical section (E-W) at the given X.
    #[must_use]
    pub fn section_ew(x_position: f32, name: impl Into<String>) -> Self {
        Self {
            plane_type: SlicePlaneType::VerticalEW,
            position: x_position,
            normal: Vec3::X,
            origin: Vec3::new(x_position, 0.0, 0.0),
            name: name.into(),
        }
    }
}

/// Project a 3D point onto the plane's 2D coordinate system.
/// - Horizontal:   `(X, Z)`
/// - VerticalNS:   `(X, Y)`
/// - VerticalEW:   `(Z, Y)`
/// - Custom:       falls through to `(X, Y)` (placeholder)
#[must_use]
#[allow(clippy::match_same_arms)] // VerticalNS and Custom both fall through to (X, Y)
pub fn project_to_2d(point3d: Vec3, plane: &SlicePlane) -> Point2D {
    match plane.plane_type {
        SlicePlaneType::Horizontal => Vec2::new(point3d.x, point3d.z),
        SlicePlaneType::VerticalNS => Vec2::new(point3d.x, point3d.y),
        SlicePlaneType::VerticalEW => Vec2::new(point3d.z, point3d.y),
        // Same shape as VerticalNS (XY) — matches the C++ default branch.
        SlicePlaneType::Custom => Vec2::new(point3d.x, point3d.y),
    }
}

/// Compute the 2D intersection point between a 3D line segment `p1 → p2`
/// and a slice plane. `None` when the segment doesn't cross.
#[must_use]
pub fn intersect_line_with_plane(p1: Vec3, p2: Vec3, plane: &SlicePlane) -> Option<Point2D> {
    let (d1, d2) = match plane.plane_type {
        SlicePlaneType::Horizontal => (p1.y - plane.position, p2.y - plane.position),
        SlicePlaneType::VerticalNS => (p1.z - plane.position, p2.z - plane.position),
        SlicePlaneType::VerticalEW => (p1.x - plane.position, p2.x - plane.position),
        SlicePlaneType::Custom => (
            (p1 - plane.origin).dot(plane.normal),
            (p2 - plane.origin).dot(plane.normal),
        ),
    };

    // Both on the same side → no crossing.
    if d1 * d2 > 0.0 {
        return None;
    }

    // Linear interpolation along the segment.
    let denom = d1 - d2;
    // Guard against degenerate input (both vertices on the plane).
    if denom == 0.0 {
        return Some(project_to_2d(p1, plane));
    }
    let t = d1 / denom;
    let intersection = p1 + (p2 - p1) * t;
    Some(project_to_2d(intersection, plane))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn horizontal_plane_projects_xz() {
        let plane = SlicePlane::horizontal(2.0, "Test");
        let p = project_to_2d(Vec3::new(1.0, 2.0, 3.0), &plane);
        assert_eq!(p, Vec2::new(1.0, 3.0));
    }

    #[test]
    fn vertical_ns_plane_projects_xy() {
        let plane = SlicePlane::section_ns(5.0, "Test");
        let p = project_to_2d(Vec3::new(1.0, 2.0, 3.0), &plane);
        assert_eq!(p, Vec2::new(1.0, 2.0));
    }

    #[test]
    fn vertical_ew_plane_projects_zy() {
        let plane = SlicePlane::section_ew(5.0, "Test");
        let p = project_to_2d(Vec3::new(1.0, 2.0, 3.0), &plane);
        assert_eq!(p, Vec2::new(3.0, 2.0));
    }

    #[test]
    fn intersect_horizontal_returns_midpoint_for_crossing_segment() {
        // Vertical segment from y=0 to y=10, plane at y=5 → midpoint.
        let plane = SlicePlane::horizontal(5.0, "Cut");
        let p =
            intersect_line_with_plane(Vec3::new(0.0, 0.0, 0.0), Vec3::new(2.0, 10.0, 4.0), &plane);
        let p = p.unwrap();
        // Y=5 is halfway, so x=1, z=2.
        assert!((p - Vec2::new(1.0, 2.0)).length() < 1e-6);
    }

    #[test]
    fn intersect_returns_none_when_segment_does_not_cross() {
        let plane = SlicePlane::horizontal(5.0, "Cut");
        let p =
            intersect_line_with_plane(Vec3::new(0.0, 10.0, 0.0), Vec3::new(0.0, 20.0, 0.0), &plane);
        assert!(p.is_none());
    }

    #[test]
    fn intersect_segment_with_one_endpoint_on_plane_returns_that_endpoint() {
        let plane = SlicePlane::horizontal(0.0, "Cut");
        // p1 at y=0 (on plane), p2 at y=5 → d1=0, d2=5, d1*d2=0 (not strictly > 0).
        let p =
            intersect_line_with_plane(Vec3::new(3.0, 0.0, 4.0), Vec3::new(3.0, 5.0, 4.0), &plane);
        assert_eq!(p, Some(Vec2::new(3.0, 4.0)));
    }
}
