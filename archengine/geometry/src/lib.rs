//! ArchEngine geometry kernel — semantic domain types, schema-driven
//! architectural geometry, triangle meshes, and the parametric object model.
//!
//! Ported from the legacy Legible Studio workspace (`legacy/legible-studio`):
//! - [`domain`] — port of `ls-domain` (non-GPU half of the C++ `types.hpp`)
//! - [`arch`] — port of `ls-archgeometry` (`Shared/ArchGeometry`)
//! - [`mesh`] — vendored `pk-geom` (Vertex, Mesh, Aabb, Transform)
//! - [`object`] — vendored `pk-object` (Object, Constraint, Scene, Solver traits)
//!
//! The `pk-*` crates from the sibling `parametric-kernel` repo are vendored
//! here so LegiCAD is self-contained while the kernel decision
//! (`questions.md` Q1: build vs. integrate) is open.

pub mod arch;
pub mod bvh;
pub mod domain;
pub mod mesh;
pub mod mesh_gen;
pub mod object;
pub mod wall_system;
