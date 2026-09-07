//! Part 3 fire separation between major occupancies (OBC 3.1).

use crate::part3::engine::{FloorInput, RoomInput};
use crate::part3::occupancy::{dominant_occupancy, occupancy_from_room_type};
use crate::part3::tables::{FireSeparation, MajorOccupancy};
use crate::report::{ComplianceCheck, ComplianceStatus};

/// Check whether adjacent floors with different occupancies require a fire
/// separation. Returns one check per unique adjacent pair.
#[must_use]
pub fn check_fire_separations(
    separations: &[FireSeparation],
    floor_occupancies: &[(usize, MajorOccupancy)],
) -> Vec<ComplianceCheck> {
    let mut out = Vec::new();
    let mut seen = std::collections::HashSet::new();
    for window in floor_occupancies.windows(2) {
        let (a_level, a) = window[0];
        let (b_level, b) = window[1];
        if a == b {
            continue;
        }
        let key = sorted_key(a, b, a_level, b_level);
        if !seen.insert(key) {
            continue;
        }
        let rating = find_rating(separations, a, b);
        out.push(ComplianceCheck {
            rule_name: format!(
                "OBC 3.1 fire separation between Level {a_level} ({}) and Level {b_level} ({})",
                a.as_str(),
                b.as_str()
            ),
            code_section: "OBC 3.1".into(),
            status: if rating.is_some() {
                ComplianceStatus::Pass
            } else {
                ComplianceStatus::DataMissing
            },
            actual: format!(
                "required rating {}",
                rating.map_or("unknown".into(), |r| format!("{r:.1} h"))
            ),
            requirement: "fire separation between different major occupancies".into(),
            message: String::new(),
        });
    }
    out
}

/// Check whether rooms on the same floor with different major occupancies that
/// share a wall require a horizontal fire separation. Returns one check per
/// unique occupancy pair per floor.
#[must_use]
pub fn check_horizontal_fire_separations(
    separations: &[FireSeparation],
    floor: &FloorInput,
) -> Vec<ComplianceCheck> {
    if floor.wall_adjacencies.is_empty() {
        return Vec::new();
    }

    // Circulation spaces take the dominant occupancy of the rooms they serve.
    let served_occ = dominant_occupancy(
        &floor
            .rooms
            .iter()
            .map(|r| (r.room_type.clone(), r.area_m2))
            .collect::<Vec<_>>(),
    );

    fn room_occ(room: &RoomInput, served: MajorOccupancy) -> MajorOccupancy {
        if is_circulation(&room.room_type) {
            served
        } else {
            room.major_occupancy
                .unwrap_or_else(|| occupancy_from_room_type(&room.room_type))
        }
    }

    let occ_by_id: std::collections::HashMap<&str, MajorOccupancy> = floor
        .rooms
        .iter()
        .map(|r| (r.id.as_str(), room_occ(r, served_occ)))
        .collect();

    let mut out = Vec::new();
    let mut seen = std::collections::HashSet::new();
    for (a_id, b_id) in &floor.wall_adjacencies {
        let &occ_a = match occ_by_id.get(a_id.as_str()) {
            Some(o) => o,
            None => continue,
        };
        let &occ_b = match occ_by_id.get(b_id.as_str()) {
            Some(o) => o,
            None => continue,
        };
        if occ_a == occ_b {
            continue;
        }
        let key = if occ_a.as_str() <= occ_b.as_str() {
            (occ_a, occ_b)
        } else {
            (occ_b, occ_a)
        };
        if !seen.insert(key) {
            continue;
        }
        let rating = find_rating(separations, occ_a, occ_b);
        out.push(ComplianceCheck {
            rule_name: format!(
                "OBC 3.1 horizontal fire separation — Level {} ({}) / ({})",
                floor.level,
                occ_a.as_str(),
                occ_b.as_str()
            ),
            code_section: "OBC 3.1".into(),
            status: if rating.is_some() {
                ComplianceStatus::Pass
            } else {
                ComplianceStatus::DataMissing
            },
            actual: format!(
                "required rating {}",
                rating.map_or("unknown".into(), |r| format!("{r:.1} h"))
            ),
            requirement: "fire separation between different major occupancies on the same floor".into(),
            message: String::new(),
        });
    }
    out
}

fn is_circulation(room_type: &str) -> bool {
    matches!(
        room_type,
        "corridor" | "hallway" | "stairs" | "elevator" | "shaft"
    )
}

fn sorted_key(
    a: MajorOccupancy,
    b: MajorOccupancy,
    a_level: usize,
    b_level: usize,
) -> (MajorOccupancy, MajorOccupancy, usize, usize) {
    if a.as_str() <= b.as_str() {
        (a, b, a_level, b_level)
    } else {
        (b, a, b_level, a_level)
    }
}

fn find_rating(separations: &[FireSeparation], a: MajorOccupancy, b: MajorOccupancy) -> Option<f32> {
    separations
        .iter()
        .find(|s| {
            (s.occupancy_a == a && s.occupancy_b == b)
                || (s.occupancy_a == b && s.occupancy_b == a)
        })
        .map(|s| s.rating_hours)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fire_separation_between_different_occupancies() {
        let seps = vec![FireSeparation {
            occupancy_a: MajorOccupancy::Residential,
            occupancy_b: MajorOccupancy::Mercantile,
            rating_hours: 2.0,
        }];
        let floors = vec![
            (1, MajorOccupancy::Mercantile),
            (2, MajorOccupancy::Residential),
        ];
        let checks = check_fire_separations(&seps, &floors);
        assert_eq!(checks.len(), 1);
        assert_eq!(checks[0].status, ComplianceStatus::Pass);
        assert!(checks[0].actual.contains("2.0"));
    }

    #[test]
    fn no_separation_for_same_occupancy() {
        let floors = vec![
            (1, MajorOccupancy::Business),
            (2, MajorOccupancy::Business),
        ];
        let checks = check_fire_separations(&[], &floors);
        assert!(checks.is_empty());
    }

    #[test]
    fn horizontal_separation_for_different_occupancies() {
        let seps = vec![FireSeparation {
            occupancy_a: MajorOccupancy::Mercantile,
            occupancy_b: MajorOccupancy::Business,
            rating_hours: 2.0,
        }];
        let floor = FloorInput {
            level: 1,
            area_m2: 200.0,
            height_m: 4.0,
            rooms: vec![
                RoomInput {
                    id: "retail".into(),
                    room_type: "retail".into(),
                    area_m2: 120.0,
                    center_m: (0.0, 0.0),
                    major_occupancy: None,
                    unit: None,
                },
                RoomInput {
                    id: "office".into(),
                    room_type: "office_open".into(),
                    area_m2: 80.0,
                    center_m: (10.0, 0.0),
                    major_occupancy: None,
                    unit: None,
                },
            ],
            edges: vec![],
            wall_adjacencies: vec![("retail".into(), "office".into())],
            discharge_targets: vec![],
            stair_centroids: vec![],
            stairs: vec![],
            elevators: vec![],
            occupancy: None,
        };
        let checks = check_horizontal_fire_separations(&seps, &floor);
        assert_eq!(checks.len(), 1);
        assert_eq!(checks[0].status, ComplianceStatus::Pass);
        assert!(checks[0].actual.contains("2.0"));
    }

    #[test]
    fn horizontal_separation_deduplicates_same_occupancy_pair() {
        let seps = vec![FireSeparation {
            occupancy_a: MajorOccupancy::Mercantile,
            occupancy_b: MajorOccupancy::Business,
            rating_hours: 2.0,
        }];
        let floor = FloorInput {
            level: 1,
            area_m2: 200.0,
            height_m: 4.0,
            rooms: vec![
                RoomInput {
                    id: "retail".into(),
                    room_type: "retail".into(),
                    area_m2: 120.0,
                    center_m: (0.0, 0.0),
                    major_occupancy: None,
                    unit: None,
                },
                RoomInput {
                    id: "office".into(),
                    room_type: "office_open".into(),
                    area_m2: 80.0,
                    center_m: (10.0, 0.0),
                    major_occupancy: None,
                    unit: None,
                },
            ],
            edges: vec![],
            wall_adjacencies: vec![
                ("retail".into(), "office".into()),
                ("office".into(), "retail".into()),
            ],
            discharge_targets: vec![],
            stair_centroids: vec![],
            stairs: vec![],
            elevators: vec![],
            occupancy: None,
        };
        let checks = check_horizontal_fire_separations(&seps, &floor);
        assert_eq!(checks.len(), 1, "same occupancy pair should be deduplicated");
    }

    #[test]
    fn horizontal_separation_data_missing_when_table_lacks_pair() {
        let floor = FloorInput {
            level: 1,
            area_m2: 200.0,
            height_m: 4.0,
            rooms: vec![
                RoomInput {
                    id: "retail".into(),
                    room_type: "retail".into(),
                    area_m2: 120.0,
                    center_m: (0.0, 0.0),
                    major_occupancy: None,
                    unit: None,
                },
                RoomInput {
                    id: "classroom".into(),
                    room_type: "classroom".into(),
                    area_m2: 80.0,
                    center_m: (10.0, 0.0),
                    major_occupancy: None,
                    unit: None,
                },
            ],
            edges: vec![],
            wall_adjacencies: vec![("retail".into(), "classroom".into())],
            discharge_targets: vec![],
            stair_centroids: vec![],
            stairs: vec![],
            elevators: vec![],
            occupancy: None,
        };
        let checks = check_horizontal_fire_separations(&[], &floor);
        assert_eq!(checks.len(), 1);
        assert_eq!(checks[0].status, ComplianceStatus::DataMissing);
    }

    #[test]
    fn horizontal_separation_skips_same_occupancy_adjacent_rooms() {
        let floor = FloorInput {
            level: 1,
            area_m2: 200.0,
            height_m: 4.0,
            rooms: vec![
                RoomInput {
                    id: "office_a".into(),
                    room_type: "office_open".into(),
                    area_m2: 100.0,
                    center_m: (0.0, 0.0),
                    major_occupancy: None,
                    unit: None,
                },
                RoomInput {
                    id: "office_b".into(),
                    room_type: "office_open".into(),
                    area_m2: 100.0,
                    center_m: (10.0, 0.0),
                    major_occupancy: None,
                    unit: None,
                },
            ],
            edges: vec![],
            wall_adjacencies: vec![("office_a".into(), "office_b".into())],
            discharge_targets: vec![],
            stair_centroids: vec![],
            stairs: vec![],
            elevators: vec![],
            occupancy: None,
        };
        let checks = check_horizontal_fire_separations(&[], &floor);
        assert!(checks.is_empty());
    }
}
