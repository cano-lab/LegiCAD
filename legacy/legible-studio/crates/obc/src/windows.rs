//! OBC Part 9 window requirements: natural light (9.7.2.3) and bedroom
//! egress (9.9.10.1).
//!
//! Pure rule lookups — *where* a window goes is a placement decision left to
//! the consumer (the solver); this module only answers "how much glazing does
//! this room need" and "what makes a legal egress window". Keeping the rules
//! here means the OBC engine stays the single source of code truth, and the
//! placement strategy above it can be swapped without touching the code.

/// Glazing area as a fraction of a room's floor area required for natural
/// light (OBC 9.7.2.3): 10% for living/dining spaces, 5% for bedrooms and
/// other habitable rooms, and 0 where daylight isn't mandated (kitchens may
/// use artificial light; bathrooms/service/circulation have no minimum).
#[must_use]
pub fn glazing_fraction(room_type: &str) -> f32 {
    match room_type {
        "living" | "dining" | "great_room" | "family" => 0.10,
        "bedroom" | "primary_bedroom" | "office" | "den" => 0.05,
        _ => 0.0,
    }
}

/// Whether a room must have an egress window (OBC 9.9.10.1 — bedrooms).
#[must_use]
pub fn requires_egress(room_type: &str) -> bool {
    matches!(room_type, "bedroom" | "primary_bedroom")
}

/// Whether a room needs any window at all (it has a daylight or egress duty).
#[must_use]
pub fn needs_window(room_type: &str) -> bool {
    glazing_fraction(room_type) > 0.0 || requires_egress(room_type)
}

/// Minimum unobstructed openable area for an egress window, in m² (9.9.10.1).
pub const EGRESS_MIN_AREA_M2: f32 = 0.35;
/// Minimum egress opening dimension (height or width), in mm (≈15 in).
pub const EGRESS_MIN_DIMENSION_MM: f32 = 380.0;
/// Maximum sill height above the floor for an egress window, in mm.
pub const EGRESS_MAX_SILL_MM: f32 = 1000.0;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn living_and_dining_need_ten_percent() {
        assert!((glazing_fraction("living") - 0.10).abs() < 1e-6);
        assert!((glazing_fraction("dining") - 0.10).abs() < 1e-6);
    }

    #[test]
    fn bedrooms_need_five_percent_and_egress() {
        assert!((glazing_fraction("bedroom") - 0.05).abs() < 1e-6);
        assert!((glazing_fraction("primary_bedroom") - 0.05).abs() < 1e-6);
        assert!(requires_egress("bedroom"));
        assert!(requires_egress("primary_bedroom"));
    }

    #[test]
    fn service_rooms_have_no_daylight_minimum_and_no_egress() {
        for rt in ["kitchen", "bathroom", "laundry", "hallway", "closet", "garage"] {
            assert_eq!(glazing_fraction(rt), 0.0, "{rt}");
            assert!(!requires_egress(rt), "{rt}");
        }
    }

    #[test]
    fn needs_window_covers_daylight_or_egress() {
        assert!(needs_window("living")); // daylight
        assert!(needs_window("bedroom")); // both
        assert!(!needs_window("hallway"));
    }
}
