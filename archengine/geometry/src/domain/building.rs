//! `StructuralElement` and `Building` — the top-level scene container.
//!
//! Port of `types.hpp:156-168` and `types.hpp:811-826`.

use crate::domain::analysis::{AcousticData, LightingData, ThermalData};
use crate::domain::culling::AABB;
use crate::domain::enums::ElementType;
use crate::domain::mesh::{MeshData, TerrainMesh};
use crate::domain::walls::{ParametricWall, WallCorner, WallType};
use glam::Vec3;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

/// Sentinel for `StructuralElement::rotation` meaning "not set; use the
/// host wall's rotation." Matches the C++ `-1000.0f` magic value.
///
/// TODO: convert to `Option<f32>` once the project-migrate binary lands and
/// we no longer need byte-compat with the C++ JSON wire format.
pub const ROTATION_UNSET: f32 = -1000.0;

/// One drawable element in the scene — a beam, column, wall layer, door,
/// window, roof, etc.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct StructuralElement {
    #[serde(rename = "type")]
    pub element_type: ElementType,
    pub start: Vec3,
    pub end: Vec3,
    pub width: f32,
    pub depth: f32,
    /// `0.0` = no stress; `1.0` = at limit; `> 1.0` = failing.
    pub stress: f32,
    /// Deflection amount (scaled for visualisation).
    pub deflection: f32,
    /// Material name — e.g. `"steel"`, `"concrete"`, `"wood"`.
    pub material: String,
    #[serde(default)]
    pub failed: bool,
    /// Optional explicit mesh geometry (from IFC, CSG, terrain, …).
    #[serde(default)]
    pub mesh: MeshData,
    /// Rotation angle in radians. `ROTATION_UNSET` (-1000) means inherit
    /// from the host wall.
    #[serde(default = "default_rotation")]
    pub rotation: f32,
}

fn default_rotation() -> f32 {
    ROTATION_UNSET
}

impl Default for StructuralElement {
    fn default() -> Self {
        Self {
            element_type: ElementType::Wall,
            start: Vec3::ZERO,
            end: Vec3::ZERO,
            width: 0.0,
            depth: 0.0,
            stress: 0.0,
            deflection: 0.0,
            material: String::new(),
            failed: false,
            mesh: MeshData::default(),
            rotation: ROTATION_UNSET,
        }
    }
}

impl StructuralElement {
    /// True if rotation has been set (i.e. not the sentinel).
    #[must_use]
    pub fn has_rotation(&self) -> bool {
        self.rotation > -999.0
    }

    /// Axis-aligned bounding box derived from `start`/`end` expanded by
    /// half `width` / `depth`. Port of `getElementAABB` (`types.hpp:800`).
    #[must_use]
    pub fn aabb(&self) -> AABB {
        let half = Vec3::new(self.width * 0.5, 0.0, self.depth * 0.5);
        let mut min = self.start.min(self.end) - half;
        let mut max = self.start.max(self.end) + half;
        // Ensure Y bounds are correct (height).
        if min.y > max.y {
            std::mem::swap(&mut min.y, &mut max.y);
        }
        AABB::new(min, max)
    }
}

/// Top-level scene container. Port of `types.hpp:812-826`.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct Building {
    #[serde(default)]
    pub name: String,
    #[serde(default)]
    pub elements: Vec<StructuralElement>,

    /// Keyed by element / space id.
    #[serde(default)]
    pub thermal_data: HashMap<String, ThermalData>,
    #[serde(default)]
    pub lighting_data: HashMap<String, LightingData>,
    #[serde(default)]
    pub acoustic_data: HashMap<String, AcousticData>,

    // Parametric wall system.
    #[serde(default)]
    pub wall_types: Vec<WallType>,
    #[serde(default)]
    pub parametric_walls: Vec<ParametricWall>,
    #[serde(default)]
    pub wall_corners: Vec<WallCorner>,

    /// Terrain mesh from elevation data, if present.
    #[serde(default)]
    pub terrain_mesh: TerrainMesh,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rotation_sentinel_means_unset() {
        let e = StructuralElement::default();
        assert!(!e.has_rotation());

        let e = StructuralElement {
            rotation: 1.57,
            ..Default::default()
        };
        assert!(e.has_rotation());
    }

    #[test]
    fn aabb_includes_width_and_depth() {
        let e = StructuralElement {
            element_type: ElementType::Beam,
            start: Vec3::new(0.0, 5.0, 0.0),
            end: Vec3::new(10.0, 5.0, 0.0),
            width: 2.0,
            depth: 1.0,
            ..Default::default()
        };
        let b = e.aabb();
        // x spans 0..10 expanded by half-width 1 -> -1..11
        assert_eq!(b.min.x, -1.0);
        assert_eq!(b.max.x, 11.0);
        // z spans 0..0 expanded by half-depth 0.5 -> -0.5..0.5
        assert_eq!(b.min.z, -0.5);
        assert_eq!(b.max.z, 0.5);
        // y is just 5..5
        assert_eq!(b.min.y, 5.0);
        assert_eq!(b.max.y, 5.0);
    }

    #[test]
    fn aabb_swaps_y_if_inverted() {
        // Column going down (start above end on Y): AABB should still be
        // valid with min.y < max.y.
        let e = StructuralElement {
            element_type: ElementType::Column,
            start: Vec3::new(0.0, 10.0, 0.0),
            end: Vec3::new(0.0, 0.0, 0.0),
            width: 1.0,
            depth: 1.0,
            ..Default::default()
        };
        let b = e.aabb();
        assert!(b.min.y <= b.max.y);
        assert_eq!(b.min.y, 0.0);
        assert_eq!(b.max.y, 10.0);
    }
}
