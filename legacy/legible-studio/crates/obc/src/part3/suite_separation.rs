//! Part 3 suite / dwelling-unit fire separation (OBC 3.1.3.1 / 3.1.3.4).
//!
//! v1 is a flag check: residential floors containing more than one dwelling
//! unit require 1-hour fire separation between units and between each unit and
//! the public corridor. The rules engine does not yet model rated wall
//! assemblies, so the check surfaces the requirement as `DataMissing` when
//! multiple units are present, prompting engineer verification.

use crate::part3::tables::MajorOccupancy;
use crate::report::{ComplianceCheck, ComplianceStatus};
use std::collections::HashMap;

/// Check suite separation requirements for each floor.
#[must_use]
pub fn check_suite_separation(floors: &[FloorInput]) -> Vec<ComplianceCheck> {
    let mut out = Vec::new();
    for floor in floors {
        if floor.occupancy != MajorOccupancy::Residential {
            continue;
        }
        let units = group_rooms_by_unit(&floor.rooms);
        if units.len() <= 1 {
            continue;
        }
        let unit_ids: Vec<String> = units
            .keys()
            .filter_map(|k| k.clone())
            .collect();
        out.push(ComplianceCheck {
            rule_name: format!("OBC 3.1.3.1 suite separation — Level {}", floor.level),
            code_section: "OBC 3.1.3.1".into(),
            status: ComplianceStatus::DataMissing,
            actual: format!("{} dwelling units on floor", units.len()),
            requirement: "1-hour fire separation between units and between units and corridor".into(),
            message: format!(
                "Units on this floor: {}. Rated assemblies must be verified.",
                unit_ids.join(", ")
            ),
        });
    }
    out
}

fn group_rooms_by_unit(rooms: &[RoomInput]) -> HashMap<Option<String>, Vec<&RoomInput>> {
    let mut map: HashMap<Option<String>, Vec<&RoomInput>> = HashMap::new();
    for room in rooms {
        map.entry(room.unit.clone()).or_default().push(room);
    }
    // Remove the ungrouped (None) bucket from the unit count.
    let _ = map.remove(&None);
    map
}

/// Input shape expected by the suite-separation check.
#[derive(Debug, Clone)]
pub struct RoomInput {
    pub id: String,
    pub room_type: String,
    pub unit: Option<String>,
}

/// Summary of units found on one floor.
#[derive(Debug, Clone)]
pub struct FloorInput {
    pub level: usize,
    pub occupancy: MajorOccupancy,
    pub rooms: Vec<RoomInput>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn single_unit_floor_has_no_suite_check() {
        let floor = FloorInput {
            level: 1,
            occupancy: MajorOccupancy::Residential,
            rooms: vec![
                RoomInput {
                    id: "u1_a".into(),
                    room_type: "bedroom".into(),
                    unit: Some("u1".into()),
                },
                RoomInput {
                    id: "u1_b".into(),
                    room_type: "bathroom".into(),
                    unit: Some("u1".into()),
                },
            ],
        };
        let checks = check_suite_separation(&[floor]);
        assert!(checks.is_empty());
    }

    #[test]
    fn multiple_units_surface_data_missing() {
        let floor = FloorInput {
            level: 1,
            occupancy: MajorOccupancy::Residential,
            rooms: vec![
                RoomInput {
                    id: "u1_a".into(),
                    room_type: "bedroom".into(),
                    unit: Some("u1".into()),
                },
                RoomInput {
                    id: "u2_a".into(),
                    room_type: "bedroom".into(),
                    unit: Some("u2".into()),
                },
            ],
        };
        let checks = check_suite_separation(&[floor]);
        assert_eq!(checks.len(), 1);
        assert_eq!(checks[0].status, ComplianceStatus::DataMissing);
    }

    #[test]
    fn non_residential_floor_is_skipped() {
        let floor = FloorInput {
            level: 1,
            occupancy: MajorOccupancy::Business,
            rooms: vec![
                RoomInput {
                    id: "u1_a".into(),
                    room_type: "office_open".into(),
                    unit: Some("u1".into()),
                },
                RoomInput {
                    id: "u2_a".into(),
                    room_type: "office_open".into(),
                    unit: Some("u2".into()),
                },
            ],
        };
        let checks = check_suite_separation(&[floor]);
        assert!(checks.is_empty());
    }
}
