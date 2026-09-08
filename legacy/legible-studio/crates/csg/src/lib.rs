//! CSG — re-export shim over the shared `pk-csg` (parametric-kernel).
//!
//! The implementation (BSP union/intersection/difference) lives in the
//! sibling `parametric-kernel` repo so it's shared with Mech Arena and
//! future Semantic OS apps instead of duplicated. Existing `use csg::...`
//! call sites keep working through this re-export.
//!
//! See `docs/PARAMETRIC_KERNEL_SPEC.md`.

pub use pk_csg::*;
