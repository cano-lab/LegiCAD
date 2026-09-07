//! OBC Part 3 commercial / mid-rise / mixed-use rules engine.

pub mod egress;
pub mod elevators;
pub mod engine;
pub mod fire_separation;
pub mod occupant_load;
pub mod occupancy;
pub mod stairs;
pub mod suite_separation;
pub mod tables;

pub use engine::{FloorInput, Part3Engine, RoomInput};
pub use stairs::StairInput;
pub use tables::MajorOccupancy;
