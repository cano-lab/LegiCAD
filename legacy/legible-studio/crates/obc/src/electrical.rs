//! Residential electrical placement rules. Receptacle spacing follows the
//! Ontario Electrical Safety Code (OESC / CEC 26-712): in finished areas, no
//! point along the floor line of a wall may be more than **1.8 m** from a
//! receptacle — i.e. receptacles at most **3.6 m** apart, and wall sections
//! under ~0.9 m don't require one. GFCI protection is required at wet and
//! garage/outdoor locations.
//!
//! Pure rule predicates/constants; placement is the consumer's job.

/// Max distance (m) from any point on a wall to a receptacle (OESC 26-712).
pub const MAX_DIST_TO_RECEPTACLE_M: f32 = 1.8;

/// Therefore receptacles are spaced at most this far apart (m).
pub const MAX_RECEPTACLE_SPACING_M: f32 = 2.0 * MAX_DIST_TO_RECEPTACLE_M;

/// Wall sections shorter than this (m) don't require a receptacle.
pub const MIN_WALL_FOR_RECEPTACLE_M: f32 = 0.9;

/// Each room with a lighting outlet needs a wall switch controlling it,
/// located at the entrance to the room (OBC 9.34.2.2 / OESC). Placement (which
/// door, which side) is the consumer's job.
pub const SWITCH_AT_ROOM_ENTRANCE: bool = true;

/// Whether receptacles in this room type must be GFCI-protected (wet areas,
/// garage, exterior — OESC 26-700/26-710).
#[must_use]
pub fn requires_gfci(room_type: &str) -> bool {
    matches!(
        room_type,
        "bathroom" | "primary_bath" | "powder_room" | "kitchen" | "laundry" | "mudroom" | "garage"
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn spacing_is_twice_the_reach() {
        assert!((MAX_RECEPTACLE_SPACING_M - 3.6).abs() < 1e-6);
    }

    #[test]
    fn gfci_at_wet_and_garage_locations() {
        for rt in ["bathroom", "primary_bath", "powder_room", "kitchen", "laundry", "garage"] {
            assert!(requires_gfci(rt), "{rt} should be GFCI");
        }
        for rt in ["bedroom", "living", "dining", "hallway", "closet"] {
            assert!(!requires_gfci(rt), "{rt} should not be GFCI");
        }
    }
}
