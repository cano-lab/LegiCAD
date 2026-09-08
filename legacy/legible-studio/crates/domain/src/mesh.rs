//! CPU-side mesh data.
//!
//! Port of `types.hpp:49-71` (Vertex, CPU half), `types.hpp:124-128`
//! (MeshData), `types.hpp:131-153` (TerrainMesh — data shape only;
//! `generateTestTerrain` is deferred to a future port chunk if needed).

use glam::{Vec2, Vec3};
use serde::{Deserialize, Serialize};

/// CPU vertex. The renderer crate keeps a GPU-flavored equivalent with
/// Vulkan/wgpu attribute bindings; these two are kept in sync but live in
/// different crates per the port plan §4.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct Vertex {
    pub position: Vec3,
    pub normal: Vec3,
    /// RGB; reused for stress visualisation colour.
    pub color: Vec3,
    pub tex_coord: Vec2,
    /// Stress / utilisation value in `[0, 1+]`. Drives stress colouring.
    pub stress: f32,
}

impl Default for Vertex {
    fn default() -> Self {
        Self {
            position: Vec3::ZERO,
            normal: Vec3::Y,
            color: Vec3::splat(0.8),
            tex_coord: Vec2::ZERO,
            stress: 0.0,
        }
    }
}

/// Custom mesh data (e.g. from IFC import or CSG output).
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct MeshData {
    pub vertices: Vec<Vec3>,
    /// Triangle indices, three per face.
    pub faces: Vec<[u32; 3]>,
}

impl MeshData {
    #[must_use]
    pub fn has_data(&self) -> bool {
        !self.vertices.is_empty() && !self.faces.is_empty()
    }
}

/// Terrain mesh data (from elevation API or procedural generation).
///
/// Deliberately stores `Vertex` rather than splitting into separate
/// position/colour arrays — matches the C++ shape so renderer upload is a
/// straight memcpy.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct TerrainMesh {
    pub vertices: Vec<Vertex>,
    pub indices: Vec<u32>,
    /// Width in feet (original input to the generator).
    pub width_ft: f32,
    /// Depth in feet.
    pub depth_ft: f32,
    pub min_elevation: f32,
    pub max_elevation: f32,
}

impl TerrainMesh {
    #[must_use]
    pub fn has_data(&self) -> bool {
        !self.vertices.is_empty() && !self.indices.is_empty()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_mesh_has_no_data() {
        assert!(!MeshData::default().has_data());
    }

    #[test]
    fn mesh_with_face_but_no_verts_has_no_data() {
        let m = MeshData {
            vertices: vec![],
            faces: vec![[0, 1, 2]],
        };
        assert!(!m.has_data());
    }

    #[test]
    fn populated_mesh_has_data() {
        let m = MeshData {
            vertices: vec![Vec3::ZERO, Vec3::X, Vec3::Y],
            faces: vec![[0, 1, 2]],
        };
        assert!(m.has_data());
    }
}
