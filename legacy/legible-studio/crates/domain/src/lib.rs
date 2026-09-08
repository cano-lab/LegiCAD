//! Semantic domain types — port of the non-GPU half of `include/types.hpp`.
//!
//! The C++ `types.hpp` is a kitchen sink: GPU vertex layouts, std140 UBOs,
//! and semantic domain types all in one file. The Rust port splits it:
//! - Semantic types live here.
//! - GPU layouts (Vertex with VkVertexInputBindingDescription, UBO,
//!   PushConstants, GPULight) move to the future renderer crate.
//!
//! See `docs/VULKAN_KERNEL_PORT_PLAN.md` §4 for the rationale.

pub mod analysis;
pub mod building;
pub mod colors;
pub mod culling;
pub mod enums;
pub mod material;
pub mod mesh;
pub mod walls;

pub use analysis::{AcousticData, LightingData, ThermalData};
pub use building::{Building, ROTATION_UNSET, StructuralElement};
pub use colors::{AcousticColors, LightingColors, StressColors, ThermalColors};
pub use culling::{AABB, Frustum, Plane};
pub use enums::{
    CameraView, ConstraintType, CornerType, ElementType, FastenerType, IntentCategory,
    LayerFunction, LightType, MaterialStyle, VisualizationMode,
};
pub use material::{MaterialPreset, materials};
pub use mesh::{MeshData, TerrainMesh, Vertex};
pub use walls::{
    AssemblyConstraint, IntentBlock, LayerFastener, ParametricWall, WallCorner, WallLayer,
    WallType, WallTypeIntent,
};
