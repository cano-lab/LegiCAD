//! Part 3 occupant load (OBC 3.1.17).
//!
//! v1 uses area-based factors for public/assembly spaces and a per-bed count
//! for residential sleeping rooms. The result feeds egress capacity checks.

use crate::part3::tables::MajorOccupancy;

/// Compute the design occupant load for a collection of rooms on one floor.
#[must_use]
pub fn occupant_load(rooms: &[RoomInput], occupancy: MajorOccupancy) -> f32 {
    let mut load = 0.0_f32;
    for room in rooms {
        if is_sleeping_room(&room.room_type) {
            // Residential sleeping rooms: 2 persons per bedroom / unit.
            load += 2.0;
        } else {
            load += area_based_load(room.area_m2, occupancy);
        }
    }
    load
}

fn is_sleeping_room(room_type: &str) -> bool {
    matches!(
        room_type,
        "bedroom"
            | "primary_bedroom"
            | "studio"
            | "one_bedroom"
            | "two_bedroom"
            | "three_bedroom"
            | "suite"
    )
}

fn area_based_load(area_m2: f32, occupancy: MajorOccupancy) -> f32 {
    let area_per_person = match occupancy {
        MajorOccupancy::Residential => 4.6, // common / amenity areas within residential
        MajorOccupancy::Business => 9.3,
        MajorOccupancy::Assembly => 1.5,
        MajorOccupancy::Mercantile => 3.0,
        MajorOccupancy::Industrial => 10.0,
        MajorOccupancy::Parking => 30.0,
    };
    (area_m2 / area_per_person).max(0.0)
}

/// Input shape used by the occupant-load calculator.
#[derive(Debug, Clone)]
pub struct RoomInput {
    pub room_type: String,
    pub area_m2: f32,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn residential_floor_counts_beds_and_common_area() {
        let rooms = vec![
            RoomInput {
                room_type: "bedroom".into(),
                area_m2: 12.0,
            },
            RoomInput {
                room_type: "bedroom".into(),
                area_m2: 12.0,
            },
            RoomInput {
                room_type: "lounge".into(),
                area_m2: 46.0,
            },
        ];
        let load = occupant_load(&rooms, MajorOccupancy::Residential);
        assert!((load - 14.0).abs() < 0.1, "expected ~14 persons, got {}", load);
    }

    #[test]
    fn business_floor_uses_area_density() {
        let rooms = vec![RoomInput {
            room_type: "office_open".into(),
            area_m2: 93.0,
        }];
        let load = occupant_load(&rooms, MajorOccupancy::Business);
        assert!((load - 10.0).abs() < 0.1);
    }
}
