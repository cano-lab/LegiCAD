//! FNV-1a 64-bit hash matching the byte sequence produced by the C++
//! `archgeometry_dump` tool. The bytes hashed are the result of
//! `snprintf("%.4f ", f)` for each float and `snprintf("%u ", n)` for each
//! uint — emitted in the same order the C++ does — so a match here is a
//! byte-for-byte match across the regression oracle.
//!
//! See `Shared/ArchGeometry/tools/archgeometry_dump.cpp:42-71`.

use crate::geometry_types::{Mesh3D, RoomBoundary};
use std::fmt::Write;

const FNV_OFFSET: u64 = 14_695_981_039_346_656_037;
const FNV_PRIME: u64 = 1_099_511_628_211;

pub struct Hasher {
    pub state: u64,
    /// Reusable scratch buffer so per-vertex formatting doesn't allocate.
    scratch: String,
}

impl Default for Hasher {
    fn default() -> Self {
        Self {
            state: FNV_OFFSET,
            scratch: String::with_capacity(32),
        }
    }
}

impl Hasher {
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    pub fn feed_bytes(&mut self, bytes: &[u8]) {
        for &b in bytes {
            self.state ^= u64::from(b);
            self.state = self.state.wrapping_mul(FNV_PRIME);
        }
    }

    pub fn feed_str(&mut self, s: &str) {
        self.feed_bytes(s.as_bytes());
    }

    /// `snprintf("%.4f ", f)`-compatible — including the trailing space.
    /// IEEE-754 `-0.0` is normalised to `+0.0` so the hash is stable.
    pub fn feed_f32(&mut self, mut f: f32) {
        if f == 0.0 {
            f = 0.0;
        }
        self.scratch.clear();
        // Rust's `{:.4}` for f32 uses round-half-to-even, matching MSVC %.4f.
        write!(self.scratch, "{f:.4} ").expect("format to String never fails");
        // Inline the FNV step to avoid borrowing `self.scratch` while also
        // calling `&mut self::feed_bytes`.
        for &b in self.scratch.as_bytes() {
            self.state ^= u64::from(b);
            self.state = self.state.wrapping_mul(FNV_PRIME);
        }
    }

    /// `snprintf("%u ", n)`-compatible — decimal, trailing space.
    pub fn feed_u32(&mut self, n: u32) {
        self.scratch.clear();
        write!(self.scratch, "{n} ").expect("format to String never fails");
        for &b in self.scratch.as_bytes() {
            self.state ^= u64::from(b);
            self.state = self.state.wrapping_mul(FNV_PRIME);
        }
    }
}

/// Feed a mesh's vertex + triangle data in the order the C++ dump uses.
pub fn hash_mesh(h: &mut Hasher, m: &Mesh3D) {
    for v in &m.vertices {
        h.feed_f32(v.position.x);
        h.feed_f32(v.position.y);
        h.feed_f32(v.position.z);
        h.feed_f32(v.normal.x);
        h.feed_f32(v.normal.y);
        h.feed_f32(v.normal.z);
        h.feed_f32(v.color.x);
        h.feed_f32(v.color.y);
        h.feed_f32(v.color.z);
        h.feed_f32(v.uv.x);
        h.feed_f32(v.uv.y);
        h.feed_f32(v.stress);
    }
    for t in &m.faces {
        h.feed_u32(t.v0);
        h.feed_u32(t.v1);
        h.feed_u32(t.v2);
    }
}

/// Feed a room boundary in the same order as the C++ dump:
/// `room_id` " " area center.x center.y, then each boundary point's x y.
pub fn hash_room(h: &mut Hasher, r: &RoomBoundary) {
    h.feed_str(&r.room_id);
    h.feed_str(" ");
    h.feed_f32(r.area);
    h.feed_f32(r.center.x);
    h.feed_f32(r.center.y);
    for p in &r.boundary.points {
        h.feed_f32(p.x);
        h.feed_f32(p.y);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_hasher_state_is_fnv_offset() {
        let h = Hasher::new();
        assert_eq!(h.state, FNV_OFFSET);
    }

    #[test]
    fn empty_mesh_hash_equals_offset() {
        // The C++ dump shows hash=0xcbf29ce484222325 for empty categories
        // (FLOORS count=0 etc.). Confirm our offset matches.
        assert_eq!(FNV_OFFSET, 0xcbf2_9ce4_8422_2325);
    }

    #[test]
    fn negative_zero_normalised_to_positive() {
        let mut a = Hasher::new();
        let mut b = Hasher::new();
        a.feed_f32(-0.0);
        b.feed_f32(0.0);
        assert_eq!(a.state, b.state);
    }

    #[test]
    fn float_formats_with_four_decimals_and_space() {
        let mut h = Hasher::new();
        h.feed_f32(1.5);
        // Hash should match feeding the bytes of "1.5000 " directly.
        let mut h2 = Hasher::new();
        h2.feed_bytes(b"1.5000 ");
        assert_eq!(h.state, h2.state);
    }

    #[test]
    fn u32_formats_decimal_with_space() {
        let mut h = Hasher::new();
        h.feed_u32(42);
        let mut h2 = Hasher::new();
        h2.feed_bytes(b"42 ");
        assert_eq!(h.state, h2.state);
    }

    #[test]
    fn fnv_known_value_abc() {
        // FNV-1a 64-bit("abc") = 0xe71fa2190541574b.
        let mut h = Hasher::new();
        h.feed_bytes(b"abc");
        assert_eq!(h.state, 0xe71f_a219_0541_574b);
    }
}
