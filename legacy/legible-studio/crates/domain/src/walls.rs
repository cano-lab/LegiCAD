//! Wall assembly types — layers, fasteners, constraints, intents,
//! wall types, corners, parametric walls.
//!
//! Port of `types.hpp:519-696`.

use crate::enums::{ConstraintType, CornerType, FastenerType, IntentCategory, LayerFunction};
use crate::mesh::MeshData;
use glam::{Vec2, Vec3};
use serde::{Deserialize, Serialize};

/// Fastener spec for a layer connection. Port of `types.hpp:532-543`.
#[derive(Debug, Clone, PartialEq, Default, Serialize, Deserialize)]
pub struct LayerFastener {
    /// e.g. `"3\" 16d Common Nail"`.
    pub name: String,
    #[serde(rename = "type")]
    pub fastener_type: FastenerType,
    /// `"steel"`, `"galvanized"`, `"stainless"`, …
    pub material: String,
    /// Diameter in inches.
    pub diameter: f32,
    /// Length in inches.
    pub length: f32,
    /// On-center field spacing in inches.
    pub field_spacing: f32,
    /// On-center edge spacing in inches.
    pub edge_spacing: f32,
    /// e.g. `"OBC 9.23.3.4"`.
    pub code_reference: String,
    /// Allowable shear in lbs.
    pub shear_capacity: f32,
    /// Allowable withdrawal in lbs.
    pub withdrawal_capacity: f32,
}

/// Code requirement an assembly must meet. Port of `types.hpp:561-568`.
#[derive(Debug, Clone, PartialEq, Default, Serialize, Deserialize)]
pub struct AssemblyConstraint {
    #[serde(rename = "type")]
    pub constraint_type: ConstraintType,
    pub name: String,
    /// Target value as a free-form string, e.g. `"R-24"`, `"1-hour"`.
    pub value: String,
    /// e.g. `"OBC 9.25.2.1"`.
    pub code_section: String,
    pub description: String,
    #[serde(default)]
    pub is_met: bool,
}

/// Design rationale entry. Port of `types.hpp:582-589`.
#[derive(Debug, Clone, PartialEq, Default, Serialize, Deserialize)]
pub struct IntentBlock {
    pub category: IntentCategory,
    pub title: String,
    pub description: String,
    pub target: String,
    #[serde(default)]
    pub related_codes: Vec<String>,
    #[serde(default)]
    pub validated: bool,
}

/// Single layer in a wall assembly. Port of `types.hpp:596-606`.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct WallLayer {
    /// e.g. `"2x6 Stud"`.
    pub name: String,
    /// e.g. `"wood"`, `"fiberglass"`.
    pub material: String,
    pub function: LayerFunction,
    /// Thickness in feet (units chosen to match C++ value space).
    pub thickness: f32,
    /// Render colour.
    pub color: Vec3,
    /// R-value for thermal calculations.
    #[serde(default)]
    pub r_value: f32,
    /// Fasteners used to attach this layer.
    #[serde(default)]
    pub fasteners: Vec<LayerFastener>,
}

impl Default for WallLayer {
    fn default() -> Self {
        Self {
            name: String::new(),
            material: String::new(),
            function: LayerFunction::Structure,
            thickness: 0.0,
            color: Vec3::splat(0.8),
            r_value: 0.0,
            fasteners: Vec::new(),
        }
    }
}

/// Primary design target for a wall type. This is the C++ `WallType::Intent`
/// nested struct (`types.hpp:619-623`) — distinct from the `IntentBlock`
/// list which carries multiple rationale entries.
#[derive(Debug, Clone, PartialEq, Default, Serialize, Deserialize)]
pub struct WallTypeIntent {
    #[serde(default)]
    pub r_value_target: f32,
    /// `"load_bearing"`, `"non_bearing"`, `"shear"`.
    #[serde(default)]
    pub structural_role: String,
    /// OBC climate zone.
    #[serde(default)]
    pub climate_zone: String,
}

/// Wall type — an assembly recipe of layers, with constraints and intents.
/// Port of `types.hpp:609-644`.
#[derive(Debug, Clone, PartialEq, Default, Serialize, Deserialize)]
pub struct WallType {
    /// Unique identifier used in JSON references.
    pub id: String,
    pub name: String,
    /// Layers ordered exterior → interior.
    #[serde(default)]
    pub layers: Vec<WallLayer>,
    #[serde(default)]
    pub constraints: Vec<AssemblyConstraint>,
    #[serde(default)]
    pub intents: Vec<IntentBlock>,
    #[serde(default)]
    pub intent: WallTypeIntent,
}

impl WallType {
    /// Sum of layer thicknesses (feet).
    #[must_use]
    pub fn total_thickness(&self) -> f32 {
        self.layers.iter().map(|l| l.thickness).sum()
    }

    /// Sum of layer R-values.
    #[must_use]
    pub fn total_r_value(&self) -> f32 {
        self.layers.iter().map(|l| l.r_value).sum()
    }

    /// True iff every constraint reports met.
    #[must_use]
    pub fn all_constraints_met(&self) -> bool {
        self.constraints.iter().all(|c| c.is_met)
    }
}

/// Connection between two parametric walls at an endpoint.
/// Port of `types.hpp:657-664`.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct WallCorner {
    pub wall1_index: u32,
    pub wall2_index: u32,
    /// XZ position of corner.
    pub location: Vec2,
    #[serde(rename = "type")]
    pub corner_type: CornerType,
    /// True if this is at the *start* of wall1.
    pub is_start1: bool,
    pub is_start2: bool,
}

/// Centerline-based parametric wall. Port of `types.hpp:666-696`.
///
/// The C++ uses `adjustedStart == (0,0)` as a sentinel for "not adjusted yet";
/// we'd normally use `Option<Vec2>` but keep the sentinel here for byte-compat
/// with the JSON written by the C++ engine. Convert to Option in a future
/// migration pass.
#[derive(Debug, Clone, PartialEq, Default, Serialize, Deserialize)]
pub struct ParametricWall {
    /// XZ start of centerline.
    pub start_point: Vec2,
    /// XZ end of centerline.
    pub end_point: Vec2,
    /// Bottom of wall (Y).
    pub base_height: f32,
    /// Top of wall (Y).
    pub top_height: f32,
    pub wall_type_index: u32,
    pub id: String,
    /// Computed geometry per layer (generated from centerline).
    #[serde(default)]
    pub layer_meshes: Vec<MeshData>,
    /// Start point after corner cleanup.
    #[serde(default)]
    pub adjusted_start: Vec2,
    /// End point after corner cleanup.
    #[serde(default)]
    pub adjusted_end: Vec2,
    /// Schema wall category (`exterior` / `interior` / `wet_wall` / `as_built`).
    /// Carried through from `SchemaWall` so the slicer can style existing
    /// (as-built) walls distinctly. Empty for C++-written walls; not emitted
    /// when empty to preserve byte-compatibility with the kernel's JSON.
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub category: String,
    /// Renovation lifecycle: `true` for an existing (as-built) wall. Carried
    /// from `SchemaWall::is_existing`. Not emitted when false (the C++ default).
    #[serde(default, skip_serializing_if = "std::ops::Not::not")]
    pub existing: bool,
}

impl ParametricWall {
    #[must_use]
    pub fn length(&self) -> f32 {
        (self.end_point - self.start_point).length()
    }

    /// Unit vector from start → end. Returns `(1, 0)` for degenerate walls
    /// (matches the C++ behaviour).
    #[must_use]
    pub fn direction(&self) -> Vec2 {
        let diff = self.end_point - self.start_point;
        let len = self.length();
        if len > 0.0001 {
            diff / len
        } else {
            Vec2::new(1.0, 0.0)
        }
    }

    /// Perpendicular to `direction()` — points to the left of travel.
    #[must_use]
    pub fn normal(&self) -> Vec2 {
        let d = self.direction();
        Vec2::new(-d.y, d.x)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn wall_type_aggregates_layer_thickness_and_r_value() {
        let wt = WallType {
            id: "test".into(),
            name: "Test".into(),
            layers: vec![
                WallLayer {
                    thickness: 0.5,
                    r_value: 13.0,
                    ..Default::default()
                },
                WallLayer {
                    thickness: 0.04,
                    r_value: 0.5,
                    ..Default::default()
                },
            ],
            ..Default::default()
        };
        assert!((wt.total_thickness() - 0.54).abs() < 1e-6);
        assert!((wt.total_r_value() - 13.5).abs() < 1e-6);
    }

    #[test]
    fn empty_constraint_list_passes_trivially() {
        let wt = WallType::default();
        assert!(wt.all_constraints_met());
    }

    #[test]
    fn constraint_unmet_fails_wall_type() {
        let wt = WallType {
            constraints: vec![
                AssemblyConstraint {
                    is_met: true,
                    ..Default::default()
                },
                AssemblyConstraint {
                    is_met: false,
                    ..Default::default()
                },
            ],
            ..Default::default()
        };
        assert!(!wt.all_constraints_met());
    }

    #[test]
    fn parametric_wall_length_and_direction() {
        let w = ParametricWall {
            start_point: Vec2::new(0.0, 0.0),
            end_point: Vec2::new(3.0, 4.0),
            ..Default::default()
        };
        assert_eq!(w.length(), 5.0);
        assert!((w.direction() - Vec2::new(0.6, 0.8)).length() < 1e-6);
    }

    #[test]
    fn degenerate_wall_returns_default_direction() {
        let w = ParametricWall {
            start_point: Vec2::ZERO,
            end_point: Vec2::ZERO,
            ..Default::default()
        };
        assert_eq!(w.direction(), Vec2::new(1.0, 0.0));
    }

    #[test]
    fn normal_is_perpendicular_to_direction() {
        let w = ParametricWall {
            start_point: Vec2::ZERO,
            end_point: Vec2::new(1.0, 0.0),
            ..Default::default()
        };
        assert!(w.direction().dot(w.normal()).abs() < 1e-6);
    }
}
