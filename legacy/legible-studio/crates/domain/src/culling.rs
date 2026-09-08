//! Axis-aligned bounding box, plane, and view frustum.
//!
//! Port of `types.hpp:699-810` (Plane, Frustum, getElementAABB helper) +
//! `bvh.hpp:22-69` (AABB). AABB lives here rather than in `bvh` because
//! the BVH builder, the frustum culler, and `StructuralElement::aabb()`
//! all need the same shape.

use glam::{Mat4, Vec3};

/// Axis-aligned bounding box.
///
/// `Default::default()` returns the empty box (min = +∞, max = −∞) so that
/// the first `expand_point`/`expand_aabb` call initialises correctly.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct AABB {
    pub min: Vec3,
    pub max: Vec3,
}

impl Default for AABB {
    fn default() -> Self {
        Self::EMPTY
    }
}

impl AABB {
    /// Empty bounding box. Use as the starting accumulator before `expand_*`.
    pub const EMPTY: Self = Self {
        min: Vec3::splat(f32::MAX),
        max: Vec3::splat(f32::MIN),
    };

    #[must_use]
    pub const fn new(min: Vec3, max: Vec3) -> Self {
        Self { min, max }
    }

    /// Grow the box to include `point`.
    pub fn expand_point(&mut self, point: Vec3) {
        self.min = self.min.min(point);
        self.max = self.max.max(point);
    }

    /// Grow the box to include `other`.
    pub fn expand_aabb(&mut self, other: &AABB) {
        self.min = self.min.min(other.min);
        self.max = self.max.max(other.max);
    }

    /// Surface area. Used by the SAH BVH builder.
    #[must_use]
    pub fn surface_area(&self) -> f32 {
        let d = self.max - self.min;
        2.0 * (d.x * d.y + d.y * d.z + d.z * d.x)
    }

    #[must_use]
    pub fn centroid(&self) -> Vec3 {
        (self.min + self.max) * 0.5
    }

    #[must_use]
    pub fn diagonal(&self) -> Vec3 {
        self.max - self.min
    }

    /// Longest axis: 0=X, 1=Y, 2=Z. Tie-breaks toward lower-indexed axis.
    #[must_use]
    pub fn longest_axis(&self) -> u32 {
        let d = self.diagonal();
        if d.x > d.y && d.x > d.z {
            0
        } else if d.y > d.z {
            1
        } else {
            2
        }
    }

    /// True iff `min ≤ max` on every axis.
    #[must_use]
    pub fn is_valid(&self) -> bool {
        self.min.x <= self.max.x && self.min.y <= self.max.y && self.min.z <= self.max.z
    }
}

/// Plane in Hessian normal form: `dot(normal, p) + distance = 0`.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Plane {
    pub normal: Vec3,
    pub distance: f32,
}

impl Plane {
    /// Signed distance from `point` to plane. Positive = in front of the plane.
    #[must_use]
    pub fn distance_to_point(&self, point: Vec3) -> f32 {
        self.normal.dot(point) + self.distance
    }
}

/// View frustum — six planes in world space.
///
/// Plane order matches the C++ enum at `types.hpp:715`: Left, Right,
/// Bottom, Top, Near, Far.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Frustum {
    pub planes: [Plane; 6],
}

impl Frustum {
    pub const LEFT: usize = 0;
    pub const RIGHT: usize = 1;
    pub const BOTTOM: usize = 2;
    pub const TOP: usize = 3;
    pub const NEAR: usize = 4;
    pub const FAR: usize = 5;

    /// Extract world-space frustum planes from a view-projection matrix.
    ///
    /// Uses the standard "subtract rows" technique (Gribb-Hartmann). Planes
    /// are normalised so `distance_to_point` returns metric distance.
    #[must_use]
    pub fn from_view_projection(vp: Mat4) -> Self {
        // glam Mat4 is column-major: vp.col(i) is column i, vp.col(i)[j] is row j of column i.
        // The C++ uses `vp[col][row]` (glm is column-major too), so vp[0][3] in the C++
        // is column 0, row 3 — which in glam is `vp.col(0).w`.
        let c0 = vp.col(0);
        let c1 = vp.col(1);
        let c2 = vp.col(2);
        let c3 = vp.col(3);

        let mut planes = [Plane {
            normal: Vec3::ZERO,
            distance: 0.0,
        }; 6];

        // Left: row3 + row0
        planes[Self::LEFT] = Plane {
            normal: Vec3::new(c0.w + c0.x, c1.w + c1.x, c2.w + c2.x),
            distance: c3.w + c3.x,
        };
        // Right: row3 - row0
        planes[Self::RIGHT] = Plane {
            normal: Vec3::new(c0.w - c0.x, c1.w - c1.x, c2.w - c2.x),
            distance: c3.w - c3.x,
        };
        // Bottom: row3 + row1
        planes[Self::BOTTOM] = Plane {
            normal: Vec3::new(c0.w + c0.y, c1.w + c1.y, c2.w + c2.y),
            distance: c3.w + c3.y,
        };
        // Top: row3 - row1
        planes[Self::TOP] = Plane {
            normal: Vec3::new(c0.w - c0.y, c1.w - c1.y, c2.w - c2.y),
            distance: c3.w - c3.y,
        };
        // Near: row3 + row2
        planes[Self::NEAR] = Plane {
            normal: Vec3::new(c0.w + c0.z, c1.w + c1.z, c2.w + c2.z),
            distance: c3.w + c3.z,
        };
        // Far: row3 - row2
        planes[Self::FAR] = Plane {
            normal: Vec3::new(c0.w - c0.z, c1.w - c1.z, c2.w - c2.z),
            distance: c3.w - c3.z,
        };

        // Normalise — port plan §7: keep this; metric distance matters for
        // AABB tests with a tolerance later.
        for p in &mut planes {
            let len = p.normal.length();
            if len > 0.0001 {
                p.normal /= len;
                p.distance /= len;
            }
        }

        Self { planes }
    }

    /// True if the AABB is fully or partially inside the frustum.
    ///
    /// Uses the standard "positive vertex" trick: for each plane, find the
    /// AABB corner furthest along the plane normal; if that corner is
    /// behind the plane, the box is fully outside.
    #[must_use]
    pub fn test_aabb(&self, min: Vec3, max: Vec3) -> bool {
        for plane in &self.planes {
            let p_vertex = Vec3::new(
                if plane.normal.x >= 0.0 { max.x } else { min.x },
                if plane.normal.y >= 0.0 { max.y } else { min.y },
                if plane.normal.z >= 0.0 { max.z } else { min.z },
            );
            if plane.distance_to_point(p_vertex) < 0.0 {
                return false;
            }
        }
        true
    }

    /// True if the point is inside or on every frustum plane.
    #[must_use]
    pub fn test_point(&self, point: Vec3) -> bool {
        self.planes
            .iter()
            .all(|p| p.distance_to_point(point) >= 0.0)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_aabb_initialises_first_expand() {
        let mut b = AABB::default();
        assert!(!b.is_valid());
        b.expand_point(Vec3::new(1.0, 2.0, 3.0));
        assert_eq!(b.min, Vec3::new(1.0, 2.0, 3.0));
        assert_eq!(b.max, Vec3::new(1.0, 2.0, 3.0));
        assert!(b.is_valid());
    }

    #[test]
    fn aabb_expand_grows_correctly() {
        let mut b = AABB::new(Vec3::ZERO, Vec3::ONE);
        b.expand_point(Vec3::new(2.0, -1.0, 0.5));
        assert_eq!(b.min, Vec3::new(0.0, -1.0, 0.0));
        assert_eq!(b.max, Vec3::new(2.0, 1.0, 1.0));
    }

    #[test]
    fn aabb_surface_area() {
        // Unit cube: SA = 6.
        let b = AABB::new(Vec3::ZERO, Vec3::ONE);
        assert_eq!(b.surface_area(), 6.0);
    }

    #[test]
    fn aabb_longest_axis() {
        let b = AABB::new(Vec3::ZERO, Vec3::new(1.0, 5.0, 3.0));
        assert_eq!(b.longest_axis(), 1);
    }

    #[test]
    fn plane_distance_sign() {
        let plane = Plane {
            normal: Vec3::Y,
            distance: 0.0,
        };
        assert!(plane.distance_to_point(Vec3::new(0.0, 5.0, 0.0)) > 0.0);
        assert!(plane.distance_to_point(Vec3::new(0.0, -5.0, 0.0)) < 0.0);
    }

    #[test]
    fn frustum_from_perspective_culls_far_box() {
        let proj = Mat4::perspective_rh(45.0_f32.to_radians(), 1.0, 0.1, 100.0);
        let view = Mat4::look_at_rh(Vec3::new(0.0, 0.0, 10.0), Vec3::ZERO, Vec3::Y);
        let f = Frustum::from_view_projection(proj * view);

        // Box near origin is visible.
        assert!(f.test_aabb(Vec3::splat(-1.0), Vec3::splat(1.0)));
        // Box behind the camera is culled.
        assert!(!f.test_aabb(Vec3::new(-1.0, -1.0, 50.0), Vec3::new(1.0, 1.0, 60.0)));
        // Box well past the far plane is culled.
        assert!(!f.test_aabb(Vec3::new(-1.0, -1.0, -1000.0), Vec3::new(1.0, 1.0, -990.0)));
    }
}
