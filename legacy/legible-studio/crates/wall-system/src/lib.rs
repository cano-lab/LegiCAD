//! Parametric walls, corner detection, L-corner adjustment.
//!
//! Port of `ArchEngine_kernel/include/wall_system.hpp`.
//!
//! Note: the C++ wall_system emits faces in both winding orders to work
//! around inconsistent normals. The Rust port fixes this — single-sided
//! faces with computed-and-corrected normals. See port plan §7 / §8 Q8.
