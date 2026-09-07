//! Part 3 occupancy classification and building area / height / storey limits
//! (OBC 3.1.2.1 / Table 3.2.2.1).

use crate::part3::tables::{AreaHeightLimit, MajorOccupancy};
use crate::report::{ComplianceCheck, ComplianceStatus};

/// Classify a room type string into a major occupancy. This is a pragmatic
/// v1 mapping; room types that don't clearly map fall back to Business.
#[must_use]
pub fn occupancy_from_room_type(room_type: &str) -> MajorOccupancy {
    match room_type {
        "bedroom" | "primary_bedroom" | "living" | "kitchen" | "dining"
        | "primary_bath" | "bathroom" | "powder_room" | "closet"
        | "walk_in_closet" | "laundry" | "mudroom" | "garage"
        | "studio" | "one_bedroom" | "two_bedroom" | "three_bedroom"
        | "suite" | "common_room" | "dining_hall" | "lounge"
        | "fitness_room" | "storage_locker" | "laundry_room"
        | "dorm_single" | "dorm_double" | "shared_washroom" | "study_lounge" => {
            MajorOccupancy::Residential
        }
        "retail" | "restaurant" => MajorOccupancy::Mercantile,
        "office_open" | "office_private" | "conference" | "lobby"
        | "reception" | "foyer" | "entry" | "kitchenette" | "mail_room"
        | "management_office" => MajorOccupancy::Business,
        "classroom" | "auditorium" => MajorOccupancy::Assembly,
        "mechanical" | "electrical" | "storage" | "janitor"
        | "loading_dock" => MajorOccupancy::Industrial,
        "parking" => MajorOccupancy::Parking,
        // Circulation spaces take the occupancy of the floor they serve.
        // Default to Business for Part 3 buildings.
        "corridor" | "hallway" | "stairs" | "elevator" | "shaft" | _ => {
            MajorOccupancy::Business
        }
    }
}

/// True for vertical/circulation spaces that should inherit the dominant
/// occupancy of the rooms they serve.
#[must_use]
fn is_circulation(room_type: &str) -> bool {
    matches!(
        room_type,
        "corridor" | "hallway" | "stairs" | "elevator" | "shaft"
    )
}

/// Determine the dominant major occupancy for a floor from its room types.
/// Circulation spaces (corridor, stairs, elevator, shaft) inherit the
/// occupancy of the non-circulation rooms they serve so that a residential
/// floor with long corridors is not misclassified as Business.
#[must_use]
pub fn dominant_occupancy(rooms: &[(String, f32)]) -> MajorOccupancy {
    // First pass: find the dominant occupancy among non-circulation rooms.
    let mut non_circ_counts: std::collections::HashMap<MajorOccupancy, f32> =
        std::collections::HashMap::new();
    for (rt, area) in rooms {
        if !is_circulation(rt) {
            let occ = occupancy_from_room_type(rt);
            *non_circ_counts.entry(occ).or_insert(0.0) += area;
        }
    }
    let served_occ = non_circ_counts
        .into_iter()
        .max_by(|a, b| a.1.partial_cmp(&b.1).unwrap_or(std::cmp::Ordering::Equal))
        .map(|(occ, _)| occ)
        .unwrap_or(MajorOccupancy::Business);

    // Second pass: circulation spaces take the served occupancy.
    let mut counts: std::collections::HashMap<MajorOccupancy, f32> =
        std::collections::HashMap::new();
    for (rt, area) in rooms {
        let occ = if is_circulation(rt) {
            served_occ
        } else {
            occupancy_from_room_type(rt)
        };
        *counts.entry(occ).or_insert(0.0) += area;
    }
    counts
        .into_iter()
        .max_by(|a, b| a.1.partial_cmp(&b.1).unwrap_or(std::cmp::Ordering::Equal))
        .map(|(occ, _)| occ)
        .unwrap_or(MajorOccupancy::Business)
}

/// Check building area / height / storey limits for the dominant occupancy of
/// each floor. Returns one check per floor.
#[must_use]
pub fn check_area_height_limits(
    limits: &std::collections::HashMap<(MajorOccupancy, bool, bool), AreaHeightLimit>,
    floors: &[FloorSummary],
    sprinklered: bool,
    alternative_solution: bool,
) -> Vec<ComplianceCheck> {
    floors
        .iter()
        .map(|floor| {
            let key = (floor.occupancy, sprinklered, alternative_solution);
            if let Some(limit) = limits.get(&key) {
                let area_ok = floor.area_m2 <= limit.max_area_per_storey_m2;
                let height_ok = floor.height_m <= limit.max_height_m;
                let storeys_ok = floor.storey_count <= limit.max_storeys;
                let pass = area_ok && height_ok && storeys_ok;
                ComplianceCheck {
                    rule_name: format!(
                        "OBC 3.2.2.1 {} area/height/storeys ({})",
                        floor.occupancy.as_str(),
                        if sprinklered { "sprinklered" } else { "unsprinklered" }
                    ),
                    code_section: "OBC 3.2.2.1".into(),
                    status: if pass { ComplianceStatus::Pass } else { ComplianceStatus::Fail },
                    actual: format!(
                        "area {:.0} m², height {:.1} m, storeys {}",
                        floor.area_m2, floor.height_m, floor.storey_count
                    ),
                    requirement: format!(
                        "area ≤ {:.0} m², height ≤ {:.1} m, storeys ≤ {}",
                        limit.max_area_per_storey_m2, limit.max_height_m, limit.max_storeys
                    ),
                    message: String::new(),
                }
            } else {
                ComplianceCheck {
                    rule_name: format!("OBC 3.2.2.1 limit for {}", floor.occupancy.as_str()),
                    code_section: "OBC 3.2.2.1".into(),
                    status: ComplianceStatus::DataMissing,
                    actual: "limit not found in table".into(),
                    requirement: "table lookup".into(),
                    message: String::new(),
                }
            }
        })
        .collect()
}

/// Summary of one floor for area/height checks.
#[derive(Debug, Clone)]
pub struct FloorSummary {
    pub level: usize,
    pub occupancy: MajorOccupancy,
    pub area_m2: f32,
    pub height_m: f32,
    pub storey_count: u32,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn dominant_occupancy_picks_largest_area() {
        let rooms = vec![
            ("office_open".into(), 800.0),
            ("corridor".into(), 100.0),
            ("washroom".into(), 50.0),
        ];
        assert_eq!(dominant_occupancy(&rooms), MajorOccupancy::Business);
    }

    #[test]
    fn dominant_occupancy_keeps_residential_despite_corridors() {
        let rooms = vec![
            ("bedroom".into(), 1200.0),
            ("corridor".into(), 800.0),
            ("stairs".into(), 200.0),
        ];
        assert_eq!(dominant_occupancy(&rooms), MajorOccupancy::Residential);
    }

    #[test]
    fn apartment_types_map_to_residential() {
        for rt in ["studio", "one_bedroom", "two_bedroom", "suite", "common_room"] {
            assert_eq!(occupancy_from_room_type(rt), MajorOccupancy::Residential);
        }
    }

    #[test]
    fn area_height_check_passes_and_fails() {
        let mut limits = std::collections::HashMap::new();
        limits.insert(
            (MajorOccupancy::Business, false, false),
            AreaHeightLimit {
                occupancy: MajorOccupancy::Business,
                sprinklered: false,
                alternative_solution: false,
                max_area_per_storey_m2: 6000.0,
                max_height_m: 36.0,
                max_storeys: 6,
            },
        );
        let floors = vec![FloorSummary {
            level: 1,
            occupancy: MajorOccupancy::Business,
            area_m2: 5000.0,
            height_m: 12.0,
            storey_count: 4,
        }];
        let checks = check_area_height_limits(&limits, &floors, false, false);
        assert_eq!(checks[0].status, ComplianceStatus::Pass);

        let floors_big = vec![FloorSummary {
            level: 1,
            occupancy: MajorOccupancy::Business,
            area_m2: 7000.0,
            height_m: 12.0,
            storey_count: 4,
        }];
        let checks_big = check_area_height_limits(&limits, &floors_big, false, false);
        assert_eq!(checks_big[0].status, ComplianceStatus::Fail);
    }
}
