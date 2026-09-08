//! Shared geometry types for the parametric kernel.
//!
//! The canonical render mesh (`Mesh` of `Vertex` + `Triangle`) plus the
//! supporting `Aabb` and `Transform`. Domain- and render-neutral: this is
//! what `pk-primitives` produces, what consumers' `ObjectGenerator`s return,
//! and what gets fed to whatever renderer the consumer picks.
//!
//! Generalized from LegibleStudios' `archgeometry::geometry_types`
//! (`Mesh3D`/`Vertex3D`/`Triangle`).

use glam::{Mat4, Quat, Vec2, Vec3};
use serde::{Deserialize, Serialize};

/// A single mesh vertex: position, normal, vertex colour, UV.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct Vertex {
    pub position: Vec3,
    pub normal: Vec3,
    pub color: Vec3,
    pub uv: Vec2,
}

impl Vertex {
    #[must_use]
    pub fn new(position: Vec3, normal: Vec3, color: Vec3, uv: Vec2) -> Self {
        Self {
            position,
            normal,
            color,
            uv,
        }
    }
}

/// A triangle as three indices into a [`Mesh`]'s vertex array.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct Triangle(pub u32, pub u32, pub u32);

/// A render mesh: vertices + index triangles.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct Mesh {
    pub vertices: Vec<Vertex>,
    pub faces: Vec<Triangle>,
}

impl Mesh {
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    #[must_use]
    pub fn vertex_count(&self) -> usize {
        self.vertices.len()
    }

    #[must_use]
    pub fn triangle_count(&self) -> usize {
        self.faces.len()
    }

    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.vertices.is_empty()
    }

    /// Add a quad as two triangles (winding 0-1-2, 0-2-3). UVs are the unit
    /// square corners `[(0,0), (1,0), (1,1), (0,1)]`.
    pub fn add_quad(&mut self, p0: Vec3, p1: Vec3, p2: Vec3, p3: Vec3, normal: Vec3, color: Vec3) {
        #[allow(clippy::cast_possible_truncation)]
        let base = self.vertices.len() as u32;
        self.vertices.push(Vertex::new(p0, normal, color, Vec2::new(0.0, 0.0)));
        self.vertices.push(Vertex::new(p1, normal, color, Vec2::new(1.0, 0.0)));
        self.vertices.push(Vertex::new(p2, normal, color, Vec2::new(1.0, 1.0)));
        self.vertices.push(Vertex::new(p3, normal, color, Vec2::new(0.0, 1.0)));
        self.faces.push(Triangle(base, base + 1, base + 2));
        self.faces.push(Triangle(base, base + 2, base + 3));
    }

    /// Add a single triangle.
    pub fn add_triangle(&mut self, p0: Vec3, p1: Vec3, p2: Vec3, normal: Vec3, color: Vec3) {
        #[allow(clippy::cast_possible_truncation)]
        let base = self.vertices.len() as u32;
        self.vertices.push(Vertex::new(p0, normal, color, Vec2::new(0.0, 0.0)));
        self.vertices.push(Vertex::new(p1, normal, color, Vec2::new(1.0, 0.0)));
        self.vertices.push(Vertex::new(p2, normal, color, Vec2::new(0.5, 1.0)));
        self.faces.push(Triangle(base, base + 1, base + 2));
    }

    /// Append another mesh, offsetting its indices.
    pub fn merge(&mut self, other: &Mesh) {
        #[allow(clippy::cast_possible_truncation)]
        let offset = self.vertices.len() as u32;
        self.vertices.extend_from_slice(&other.vertices);
        self.faces.extend(
            other
                .faces
                .iter()
                .map(|t| Triangle(t.0 + offset, t.1 + offset, t.2 + offset)),
        );
    }

    /// Axis-aligned bounding box over all vertex positions. Returns a
    /// zero-sized box at the origin for an empty mesh.
    #[must_use]
    pub fn aabb(&self) -> Aabb {
        if self.vertices.is_empty() {
            return Aabb {
                min: Vec3::ZERO,
                max: Vec3::ZERO,
            };
        }
        let mut min = Vec3::splat(f32::INFINITY);
        let mut max = Vec3::splat(f32::NEG_INFINITY);
        for v in &self.vertices {
            min = min.min(v.position);
            max = max.max(v.position);
        }
        Aabb { min, max }
    }
}

/// Axis-aligned bounding box.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct Aabb {
    pub min: Vec3,
    pub max: Vec3,
}

impl Aabb {
    #[must_use]
    pub fn size(&self) -> Vec3 {
        self.max - self.min
    }

    #[must_use]
    pub fn center(&self) -> Vec3 {
        (self.min + self.max) * 0.5
    }
}

/// Rigid + scale transform (translation, rotation, non-uniform scale).
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct Transform {
    pub translation: Vec3,
    pub rotation: Quat,
    pub scale: Vec3,
}

impl Default for Transform {
    fn default() -> Self {
        Self::identity()
    }
}

impl Transform {
    #[must_use]
    pub fn identity() -> Self {
        Self {
            translation: Vec3::ZERO,
            rotation: Quat::IDENTITY,
            scale: Vec3::ONE,
        }
    }

    #[must_use]
    pub fn from_translation(t: Vec3) -> Self {
        Self {
            translation: t,
            ..Self::identity()
        }
    }

    /// Apply this transform to a point: `translation + rotation * (scale * p)`.
    #[must_use]
    pub fn apply(&self, p: Vec3) -> Vec3 {
        self.translation + self.rotation * (self.scale * p)
    }

    #[must_use]
    pub fn to_mat4(&self) -> Mat4 {
        Mat4::from_scale_rotation_translation(self.scale, self.rotation, self.translation)
    }
}

/// Signed area of a polygon (CCW positive). Twice the area, but only the sign
/// and relative magnitude matter for triangulation.
fn signed_area2(poly: &[Vec2]) -> f32 {
    let n = poly.len();
    (0..n)
        .map(|i| {
            let a = poly[i];
            let b = poly[(i + 1) % n];
            a.x * b.y - b.x * a.y
        })
        .sum()
}

/// Is point `p` inside triangle `a,b,c` (CCW)? Inclusive of edges.
#[allow(clippy::many_single_char_names)]
fn point_in_tri(p: Vec2, a: Vec2, b: Vec2, c: Vec2) -> bool {
    let d = |u: Vec2, v: Vec2, w: Vec2| (v.x - u.x) * (w.y - u.y) - (v.y - u.y) * (w.x - u.x);
    let s = d(a, b, p);
    let t = d(b, c, p);
    let u = d(c, a, p);
    // All non-negative (CCW) — allow a tiny epsilon so shared vertices count.
    s >= -1e-6 && t >= -1e-6 && u >= -1e-6
}

/// Triangulate a simple polygon (CCW or CW, no self-intersections, no holes)
/// by ear clipping. Returns index triples into `poly`. Handles concave
/// polygons correctly — unlike a fan from one vertex, which only works for
/// convex shapes. Degenerate input (< 3 vertices) yields no triangles.
#[must_use]
#[allow(clippy::many_single_char_names)]
pub fn triangulate(poly: &[Vec2]) -> Vec<[usize; 3]> {
    let n = poly.len();
    if n < 3 {
        return Vec::new();
    }
    // Work on a CCW copy of the index ring.
    let mut idx: Vec<usize> = (0..n).collect();
    if signed_area2(poly) < 0.0 {
        idx.reverse();
    }
    let mut out = Vec::with_capacity(n - 2);
    let mut guard = 0;
    let max_iter = n * n + 1; // bound against pathological/degenerate input
    while idx.len() > 3 && guard < max_iter {
        guard += 1;
        let m = idx.len();
        let mut clipped = false;
        for i in 0..m {
            let (ia, ib, ic) = (idx[(i + m - 1) % m], idx[i], idx[(i + 1) % m]);
            let (a, b, c) = (poly[ia], poly[ib], poly[ic]);
            // Convex (left turn) and an ear (no other vertex inside).
            let cross = (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x);
            if cross <= 0.0 {
                continue; // reflex vertex
            }
            let ear = idx
                .iter()
                .all(|&j| j == ia || j == ib || j == ic || !point_in_tri(poly[j], a, b, c));
            if ear {
                out.push([ia, ib, ic]);
                idx.remove(i);
                clipped = true;
                break;
            }
        }
        if !clipped {
            break; // no ear found (degenerate) — stop rather than loop forever
        }
    }
    if idx.len() == 3 {
        out.push([idx[0], idx[1], idx[2]]);
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn add_quad_makes_4_verts_2_tris() {
        let mut m = Mesh::new();
        m.add_quad(
            Vec3::ZERO,
            Vec3::X,
            Vec3::new(1.0, 1.0, 0.0),
            Vec3::Y,
            Vec3::Z,
            Vec3::ONE,
        );
        assert_eq!(m.vertex_count(), 4);
        assert_eq!(m.triangle_count(), 2);
        assert_eq!(m.faces[0], Triangle(0, 1, 2));
        assert_eq!(m.faces[1], Triangle(0, 2, 3));
    }

    /// Sum the triangle areas (should equal the polygon area for a valid
    /// triangulation that neither overlaps nor leaves gaps).
    fn tri_area_sum(poly: &[Vec2], tris: &[[usize; 3]]) -> f32 {
        tris.iter()
            .map(|[i, j, k]| {
                let (a, b, c) = (poly[*i], poly[*j], poly[*k]);
                ((b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x)).abs() * 0.5
            })
            .sum()
    }

    #[test]
    fn triangulate_square_is_two_triangles() {
        let sq = [
            Vec2::ZERO,
            Vec2::new(2.0, 0.0),
            Vec2::new(2.0, 2.0),
            Vec2::new(0.0, 2.0),
        ];
        let tris = triangulate(&sq);
        assert_eq!(tris.len(), 2);
        assert!((tri_area_sum(&sq, &tris) - 4.0).abs() < 1e-4);
    }

    #[test]
    fn triangulate_concave_l_shape_covers_area_without_overflow() {
        // An L: 6 vertices, one reflex corner. Fan triangulation would spill
        // outside; ear clipping must cover exactly the L's area (3 sq units).
        let l = [
            Vec2::new(0.0, 0.0),
            Vec2::new(2.0, 0.0),
            Vec2::new(2.0, 1.0),
            Vec2::new(1.0, 1.0),
            Vec2::new(1.0, 2.0),
            Vec2::new(0.0, 2.0),
        ];
        let tris = triangulate(&l);
        assert_eq!(tris.len(), 4); // n - 2
        assert!((tri_area_sum(&l, &tris) - 3.0).abs() < 1e-4, "L area mismatch");
    }

    #[test]
    fn triangulate_clockwise_input_is_handled() {
        let cw = [
            Vec2::ZERO,
            Vec2::new(0.0, 2.0),
            Vec2::new(2.0, 2.0),
            Vec2::new(2.0, 0.0),
        ];
        let tris = triangulate(&cw);
        assert_eq!(tris.len(), 2);
        assert!((tri_area_sum(&cw, &tris) - 4.0).abs() < 1e-4);
    }

    #[test]
    fn triangulate_degenerate_is_empty() {
        assert!(triangulate(&[]).is_empty());
        assert!(triangulate(&[Vec2::ZERO, Vec2::X]).is_empty());
    }

    #[test]
    fn merge_offsets_indices() {
        let mut a = Mesh::new();
        a.add_triangle(Vec3::ZERO, Vec3::X, Vec3::Y, Vec3::Z, Vec3::ONE);
        let mut b = Mesh::new();
        b.add_triangle(Vec3::ZERO, Vec3::X, Vec3::Y, Vec3::Z, Vec3::ONE);
        a.merge(&b);
        assert_eq!(a.vertex_count(), 6);
        assert_eq!(a.triangle_count(), 2);
        assert_eq!(a.faces[1], Triangle(3, 4, 5));
    }

    #[test]
    fn aabb_spans_all_vertices() {
        let mut m = Mesh::new();
        m.add_quad(
            Vec3::new(-1.0, 0.0, -2.0),
            Vec3::new(3.0, 0.0, -2.0),
            Vec3::new(3.0, 0.0, 5.0),
            Vec3::new(-1.0, 0.0, 5.0),
            Vec3::Y,
            Vec3::ONE,
        );
        let bb = m.aabb();
        assert_eq!(bb.min, Vec3::new(-1.0, 0.0, -2.0));
        assert_eq!(bb.max, Vec3::new(3.0, 0.0, 5.0));
        assert_eq!(bb.size(), Vec3::new(4.0, 0.0, 7.0));
    }

    #[test]
    fn empty_mesh_aabb_is_origin() {
        let bb = Mesh::new().aabb();
        assert_eq!(bb.min, Vec3::ZERO);
        assert_eq!(bb.max, Vec3::ZERO);
    }

    #[test]
    fn transform_identity_is_noop() {
        let t = Transform::identity();
        let p = Vec3::new(3.0, 4.0, 5.0);
        assert_eq!(t.apply(p), p);
    }

    #[test]
    fn transform_translation_offsets() {
        let t = Transform::from_translation(Vec3::new(10.0, 0.0, 0.0));
        assert_eq!(t.apply(Vec3::ZERO), Vec3::new(10.0, 0.0, 0.0));
    }
}
