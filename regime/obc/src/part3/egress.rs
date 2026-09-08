//! Part 3 egress checks (OBC 3.3 / 3.4).
//!
//! v1 checks:
//! - maximum travel distance from each room to the nearest exit stair using a
//!   door-graph shortest path through rooms and corridors (OBC 3.4.2.5)
//! - minimum number of exits per floor based on occupant load (OBC 3.4.2.1)
//! - aggregate exit width against the calculated occupant load (OBC 3.4.3)
//!
//! Travel distance is computed per floor. Stairs are treated as exit nodes and
//! are assumed to open onto corridor / hallway / lobby rooms on the same floor.

use crate::part3::{
    occupant_load::{self, RoomInput as OccupantRoomInput},
    tables::{MajorOccupancy, TravelDistanceLimit},
};
use crate::report::{ComplianceCheck, ComplianceStatus};
use std::collections::{BinaryHeap, HashMap};
use std::cmp::Ordering;

/// Minimum aggregate exit width per person, in millimetres (OBC 3.4.3).
/// Level exits and public stairs both use 6.1 mm/person for v1.
const EXIT_WIDTH_MM_PER_PERSON: f32 = 6.1;

/// Room types that serve as suite exits when stairs are fire-rated.
const SUITE_EXIT_ROOM_TYPES: &[&str] = &["corridor", "hallway", "lobby"];

/// Check that every room on each floor is within the maximum travel distance
/// to an exit stair. The distance is the shortest path through the door graph
/// (room-to-room edges) from the room to the nearest stair node.
#[must_use]
pub fn check_travel_distance(
    limits: &std::collections::HashMap<MajorOccupancy, TravelDistanceLimit>,
    floors: &[FloorEgress],
) -> Vec<ComplianceCheck> {
    let mut out = Vec::new();
    for floor in floors {
        let limit = limits
            .get(&floor.occupancy)
            .map(|l| l.max_distance_m)
            .unwrap_or(45.0);
        let stair_ids: Vec<&str> = floor.stairs.iter().map(|s| s.id.as_str()).collect();
        for room in &floor.rooms {
            let goals = egress_goals_for_room(room, &floor.rooms, &stair_ids);
            let (path_m, pass, message) =
                match shortest_path_to_any(&room.id, &goals, &floor.edges) {
                    Some(d) => {
                        let pass = d <= limit;
                        let message = if goals.is_empty() {
                            "No stairs or suite exits on floor; path distance computed to empty goal set."
                                .to_string()
                        } else {
                            "Shortest path distance through the door/corridor network.".to_string()
                        };
                        (d, pass, message)
                    }
                    None => {
                        let msg = if goals.is_empty() {
                            "No stairs or suite exits on floor.".to_string()
                        } else {
                            "No egress path found — room is isolated from exits.".to_string()
                        };
                        (f32::INFINITY, false, msg)
                    }
                };
            out.push(ComplianceCheck {
                rule_name: format!("OBC 3.4.2.5 travel distance — {}", room.id),
                code_section: "OBC 3.4.2.5".into(),
                status: if pass { ComplianceStatus::Pass } else { ComplianceStatus::Fail },
                actual: format!("approx {path_m:.1} m to nearest stair"),
                requirement: format!("≤ {limit:.1} m for {}", floor.occupancy.as_str()),
                message,
            });
        }
    }
    out
}

/// Build the list of goal node ids for a room.
///
/// - Common rooms (no unit) must reach a stair.
/// - Rooms inside a suite may also terminate at a corridor/hallway/lobby when
///   the stair is fire-rated, so those circulation rooms are added as goals.
fn egress_goals_for_room<'a>(
    room: &RoomEgress,
    floor_rooms: &'a [RoomEgress],
    stair_ids: &[&'a str],
) -> Vec<&'a str> {
    let mut goals = stair_ids.to_vec();
    if room.unit.is_some() {
        for other in floor_rooms {
            if other.id == room.id {
                continue;
            }
            if SUITE_EXIT_ROOM_TYPES.contains(&other.room_type.as_str()) {
                goals.push(other.id.as_str());
            }
        }
    }
    goals
}

/// Check that each floor has enough exits for its occupant load.
/// OBC 3.4.2.1: floors with occupant load > 30 require at least 2 exits.
#[must_use]
pub fn check_exit_count(floors: &[FloorEgress]) -> Vec<ComplianceCheck> {
    let mut out = Vec::new();
    for floor in floors {
        let load = occupant_load::occupant_load(
            &floor
                .rooms
                .iter()
                .map(|r| OccupantRoomInput {
                    room_type: r.room_type.clone(),
                    area_m2: r.area_m2,
                })
                .collect::<Vec<_>>(),
            floor.occupancy,
        );
        let required = if load > 30.0 { 2 } else { 1 };
        let actual = floor.stairs.len();
        let pass = actual >= required;
        out.push(ComplianceCheck {
            rule_name: format!("OBC 3.4.2.1 exit count — Level {}", floor.level),
            code_section: "OBC 3.4.2.1".into(),
            status: if pass { ComplianceStatus::Pass } else { ComplianceStatus::Fail },
            actual: format!("{actual} exit(s), {load:.0} occupants"),
            requirement: format!("≥ {required} exit(s) for {load:.0} occupants"),
            message: "Stairs are treated as exits for v1.".into(),
        });
    }
    out
}

/// Check that aggregate exit width across all stairs on a floor can handle the
/// occupant load (OBC 3.4.3).
#[must_use]
pub fn check_exit_width(floors: &[FloorEgress]) -> Vec<ComplianceCheck> {
    let mut out = Vec::new();
    for floor in floors {
        let load = occupant_load::occupant_load(
            &floor
                .rooms
                .iter()
                .map(|r| OccupantRoomInput {
                    room_type: r.room_type.clone(),
                    area_m2: r.area_m2,
                })
                .collect::<Vec<_>>(),
            floor.occupancy,
        );
        let required_width_mm = load * EXIT_WIDTH_MM_PER_PERSON;
        let total_width_mm: f32 = floor.stairs.iter().map(|s| s.width_clear_mm).sum();
        let pass = total_width_mm >= required_width_mm;
        out.push(ComplianceCheck {
            rule_name: format!("OBC 3.4.3 exit width — Level {}", floor.level),
            code_section: "OBC 3.4.3".into(),
            status: if pass { ComplianceStatus::Pass } else { ComplianceStatus::Fail },
            actual: format!("{total_width_mm:.0} mm total stair width, {load:.0} occupants"),
            requirement: format!(
                "≥ {required_width_mm:.0} mm ({EXIT_WIDTH_MM_PER_PERSON} mm/person)"
            ),
            message: "Aggregate clear width across all stairs on the floor.".into(),
        });
    }
    out
}

/// Verify that every ground-floor stair discharges to an acceptable target
/// (lobby, vestibule, entry, or a room with a door on an exterior wall).
/// Upper floors are skipped because the model does not yet represent vertical
/// stair shafts.
#[must_use]
pub fn check_exit_discharge(floors: &[FloorEgress]) -> Vec<ComplianceCheck> {
    let mut out = Vec::new();
    for floor in floors {
        if floor.level != 1 {
            continue;
        }
        if floor.discharge_targets.is_empty() {
            out.push(ComplianceCheck {
                rule_name: format!("OBC 3.4.2 exit discharge — Level {}", floor.level),
                code_section: "OBC 3.4.2".into(),
                status: ComplianceStatus::Fail,
                actual: "no discharge targets identified".into(),
                requirement: "ground-floor stairs must discharge to exterior, lobby, vestibule, or entry".into(),
                message: "No ground-floor room has an exterior door and no lobby/vestibule/entry room was found.".into(),
            });
            continue;
        }
        let targets: Vec<&str> = floor
            .discharge_targets
            .iter()
            .map(String::as_str)
            .collect();
        for stair in &floor.stairs {
            let pass = shortest_path_to_any(&stair.id,&targets, &floor.edges)
                .is_some();
            out.push(ComplianceCheck {
                rule_name: format!("OBC 3.4.2 exit discharge — {}", stair.id),
                code_section: "OBC 3.4.2".into(),
                status: if pass {
                    ComplianceStatus::Pass
                } else {
                    ComplianceStatus::Fail
                },
                actual: if pass {
                    "stair reaches discharge target".into()
                } else {
                    "stair cannot reach any discharge target".into()
                },
                requirement: "discharge to exterior, lobby, vestibule, or entry".into(),
                message: String::new(),
            });
        }
    }
    out
}

fn distance(a: (f32, f32), b: (f32, f32)) -> f32 {
    ((a.0 - b.0).powi(2) + (a.1 - b.1).powi(2)).sqrt()
}

/// One traversable connection between two rooms on the same floor.
#[derive(Debug, Clone)]
pub struct RoomEdge {
    pub room_a: String,
    pub room_b: String,
    /// Distance between the two room centroids, in metres.
    pub distance_m: f32,
}

/// Dijkstra shortest path from `start` to any node in `goals` through the
/// undirected weighted graph described by `edges`. Returns `None` when `goals`
/// is empty or no path exists.
pub fn shortest_path_to_any(start: &str, goals: &[&str], edges: &[RoomEdge]) -> Option<f32> {
    if goals.is_empty() {
        return None;
    }
    let goal_set: std::collections::HashSet<&str> = goals.iter().copied().collect();
    if goal_set.contains(start) {
        return Some(0.0);
    }

    let mut adj: HashMap<&str, Vec<(&str, f32)>> = HashMap::new();
    for e in edges {
        adj.entry(e.room_a.as_str()).or_default().push((e.room_b.as_str(), e.distance_m));
        adj.entry(e.room_b.as_str()).or_default().push((e.room_a.as_str(), e.distance_m));
    }

    #[derive(Debug, Clone, Copy, PartialEq)]
    struct State {
        dist: f32,
        node: usize,
    }
    impl Eq for State {}
    impl PartialOrd for State {
        fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
            other.dist.partial_cmp(&self.dist)
        }
    }
    impl Ord for State {
        fn cmp(&self, other: &Self) -> Ordering {
            other.dist.partial_cmp(&self.dist).unwrap_or(Ordering::Equal)
        }
    }

    // Map node ids to indices so the heap does not own strings.
    let nodes: Vec<&str> = {
        let mut set = std::collections::HashSet::new();
        set.insert(start);
        for g in goals {
            set.insert(*g);
        }
        for e in edges {
            set.insert(e.room_a.as_str());
            set.insert(e.room_b.as_str());
        }
        set.into_iter().collect()
    };
    let index_of: HashMap<&str, usize> = nodes.iter().enumerate().map(|(i, n)| (*n, i)).collect();

    let mut best: Vec<f32> = vec![f32::INFINITY; nodes.len()];
    let mut heap: BinaryHeap<State> = BinaryHeap::new();
    let start_idx = index_of[start];
    best[start_idx] = 0.0;
    heap.push(State { dist: 0.0, node: start_idx });

    while let Some(State { dist, node }) = heap.pop() {
        if dist > best[node] {
            continue;
        }
        let node_id = nodes[node];
        if goal_set.contains(node_id) {
            return Some(dist);
        }
        for (neighbor, weight) in adj.get(node_id).unwrap_or(&Vec::new()) {
            let n_idx = match index_of.get(*neighbor) {
                Some(&i) => i,
                None => continue,
            };
            let next_dist = dist + weight;
            if next_dist < best[n_idx] {
                best[n_idx] = next_dist;
                heap.push(State { dist: next_dist, node: n_idx });
            }
        }
    }

    None
}

/// Egress geometry for one floor.
#[derive(Debug, Clone)]
pub struct FloorEgress {
    pub level: usize,
    pub occupancy: MajorOccupancy,
    pub rooms: Vec<RoomEgress>,
    /// Navigable room-to-room edges on this floor (doors).
    pub edges: Vec<RoomEdge>,
    /// Exit stairs on this floor, used for travel distance, count, and width.
    pub stairs: Vec<StairEgress>,
    /// Ground-floor room IDs that are acceptable exit-discharge targets
    /// (lobby, vestibule, entry, or any room with a door on an exterior wall).
    pub discharge_targets: Vec<String>,
}

#[derive(Debug, Clone)]
pub struct RoomEgress {
    pub id: String,
    pub room_type: String,
    pub area_m2: f32,
    /// Optional dwelling-unit / suite id. When present and stairs are
    /// fire-rated, travel distance may be measured to the suite exit (a
    /// corridor/hall/lobby) rather than all the way to the stair.
    pub unit: Option<String>,
    /// Room centroid in metres (plan coordinates).
    pub center_m: (f32, f32),
}

#[derive(Debug, Clone)]
pub struct StairEgress {
    pub id: String,
    /// Stair centroid in metres (plan coordinates).
    pub centroid_m: (f32, f32),
    /// Clear width between handrails, mm.
    pub width_clear_mm: f32,
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::part3::tables::TravelDistanceLimit;

    #[test]
    fn travel_distance_passes_when_room_near_stair() {
        let limits = {
            let mut m = std::collections::HashMap::new();
            m.insert(
                MajorOccupancy::Business,
                TravelDistanceLimit {
                    occupancy: MajorOccupancy::Business,
                    max_distance_m: 45.0,
                },
            );
            m
        };
        let floors = vec![FloorEgress {
            level: 1,
            occupancy: MajorOccupancy::Business,
            rooms: vec![RoomEgress {
                id: "office".into(),
                room_type: "office_open".into(),
                area_m2: 20.0,
                unit: None,
                center_m: (10.0, 5.0),
            }],
            edges: vec![RoomEdge {
                room_a: "office".into(),
                room_b: "stairs_1".into(),
                distance_m: 2.0,
            }],
            discharge_targets: vec![],
            stairs: vec![StairEgress {
                id: "stairs_1".into(),
                centroid_m: (12.0, 5.0),
                width_clear_mm: 1200.0,
            }],
        }];
        let checks = check_travel_distance(&limits, &floors);
        assert_eq!(checks[0].status, ComplianceStatus::Pass);
    }

    #[test]
    fn residential_floor_with_many_beds_requires_two_exits() {
        let rooms: Vec<RoomEgress> = (0..20)
            .map(|i| RoomEgress {
                id: format!("bed_{i}"),
                room_type: "bedroom".into(),
                area_m2: 12.0,
                unit: None,
                center_m: (0.0, 0.0),
            })
            .collect();
        let floor = FloorEgress {
            level: 2,
            occupancy: MajorOccupancy::Residential,
            rooms,
            edges: vec![],
            discharge_targets: vec![],
            stairs: vec![StairEgress {
                id: "stairs_1".into(),
                centroid_m: (0.0, 0.0),
                width_clear_mm: 1100.0,
            }],
        };
        let checks = check_exit_count(&[floor.clone()]);
        assert_eq!(checks[0].status, ComplianceStatus::Fail);

        let floor_two_stairs = FloorEgress {
            discharge_targets: vec![],
            stairs: vec![
                StairEgress {
                    id: "stairs_1".into(),
                    centroid_m: (0.0, 0.0),
                    width_clear_mm: 1100.0,
                },
                StairEgress {
                    id: "stairs_2".into(),
                    centroid_m: (10.0, 0.0),
                    width_clear_mm: 1100.0,
                },
            ],
            ..floor
        };
        let checks = check_exit_count(&[floor_two_stairs]);
        assert_eq!(checks[0].status, ComplianceStatus::Pass);
    }

    #[test]
    fn exit_width_scales_with_occupant_load() {
        let rooms: Vec<RoomEgress> = (0..10)
            .map(|i| RoomEgress {
                id: format!("bed_{i}"),
                room_type: "bedroom".into(),
                area_m2: 12.0,
                unit: None,
                center_m: (0.0, 0.0),
            })
            .collect();
        // 10 bedrooms × 2 persons = 20 occupants.
        // Required width = 20 × 6.1 = 122 mm.
        let floor = FloorEgress {
            level: 2,
            occupancy: MajorOccupancy::Residential,
            rooms,
            edges: vec![],
            discharge_targets: vec![],
            stairs: vec![StairEgress {
                id: "stairs_1".into(),
                centroid_m: (0.0, 0.0),
                width_clear_mm: 1100.0,
            }],
        };
        let checks = check_exit_width(&[floor]);
        assert_eq!(checks[0].status, ComplianceStatus::Pass);
    }

    #[test]
    fn travel_distance_passes_via_corridor() {
        let limits = {
            let mut m = std::collections::HashMap::new();
            m.insert(
                MajorOccupancy::Residential,
                TravelDistanceLimit {
                    occupancy: MajorOccupancy::Residential,
                    max_distance_m: 25.0,
                },
            );
            m
        };
        // Room is 30 m straight-line from the stair, but only 12 m via corridor.
        let floor = FloorEgress {
            level: 2,
            occupancy: MajorOccupancy::Residential,
            rooms: vec![
                RoomEgress {
                    id: "bedroom".into(),
                    room_type: "bedroom".into(),
                    area_m2: 12.0,
                    unit: Some("u1".into()),
                    center_m: (0.0, 0.0),
                },
                RoomEgress {
                    id: "corridor".into(),
                    room_type: "corridor".into(),
                    area_m2: 20.0,
                    unit: None,
                    center_m: (10.0, 0.0),
                },
            ],
            edges: vec![
                RoomEdge {
                    room_a: "bedroom".into(),
                    room_b: "corridor".into(),
                    distance_m: 10.0,
                },
                RoomEdge {
                    room_a: "corridor".into(),
                    room_b: "stairs_1".into(),
                    distance_m: 2.0,
                },
            ],
            discharge_targets: vec![],
            stairs: vec![StairEgress {
                id: "stairs_1".into(),
                centroid_m: (30.0, 0.0),
                width_clear_mm: 1100.0,
            }],
        };
        let checks = check_travel_distance(&limits, &[floor]);
        assert_eq!(checks[0].status, ComplianceStatus::Pass);
        assert!(checks[0].actual.contains("10.0"));
    }

    #[test]
    fn isolated_room_fails_no_path() {
        let limits = {
            let mut m = std::collections::HashMap::new();
            m.insert(
                MajorOccupancy::Business,
                TravelDistanceLimit {
                    occupancy: MajorOccupancy::Business,
                    max_distance_m: 45.0,
                },
            );
            m
        };
        let floor = FloorEgress {
            level: 1,
            occupancy: MajorOccupancy::Business,
            rooms: vec![RoomEgress {
                id: "office".into(),
                room_type: "office_open".into(),
                area_m2: 20.0,
                unit: None,
                center_m: (10.0, 5.0),
            }],
            edges: vec![],
            discharge_targets: vec![],
            stairs: vec![StairEgress {
                id: "stairs_1".into(),
                centroid_m: (12.0, 5.0),
                width_clear_mm: 1200.0,
            }],
        };
        let checks = check_travel_distance(&limits, &[floor]);
        assert_eq!(checks[0].status, ComplianceStatus::Fail);
        assert!(checks[0].message.contains("isolated"));
    }

    #[test]
    fn long_corridor_still_fails() {
        let limits = {
            let mut m = std::collections::HashMap::new();
            m.insert(
                MajorOccupancy::Residential,
                TravelDistanceLimit {
                    occupancy: MajorOccupancy::Residential,
                    max_distance_m: 25.0,
                },
            );
            m
        };
        let floor = FloorEgress {
            level: 2,
            occupancy: MajorOccupancy::Residential,
            rooms: vec![
                RoomEgress {
                    id: "bedroom".into(),
                    room_type: "bedroom".into(),
                    area_m2: 12.0,
                    unit: Some("u1".into()),
                    center_m: (0.0, 0.0),
                },
                RoomEgress {
                    id: "corridor".into(),
                    room_type: "corridor".into(),
                    area_m2: 20.0,
                    unit: None,
                    center_m: (30.0, 0.0),
                },
            ],
            edges: vec![
                RoomEdge {
                    room_a: "bedroom".into(),
                    room_b: "corridor".into(),
                    distance_m: 30.0,
                },
            ],
            discharge_targets: vec![],
            stairs: vec![],
        };
        let checks = check_travel_distance(&limits, &[floor]);
        assert_eq!(checks[0].status, ComplianceStatus::Fail);
    }

    #[test]
    fn exit_discharge_passes_when_stair_reaches_lobby() {
        let floor = FloorEgress {
            level: 1,
            occupancy: MajorOccupancy::Business,
            rooms: vec![RoomEgress {
                id: "lobby".into(),
                room_type: "lobby".into(),
                area_m2: 50.0,
                unit: None,
                center_m: (0.0, 0.0),
            }],
            edges: vec![RoomEdge {
                room_a: "stairs_1".into(),
                room_b: "lobby".into(),
                distance_m: 2.0,
            }],
            discharge_targets: vec!["lobby".into()],
            stairs: vec![StairEgress {
                id: "stairs_1".into(),
                centroid_m: (5.0, 0.0),
                width_clear_mm: 1200.0,
            }],
        };
        let checks = check_exit_discharge(&[floor]);
        assert_eq!(checks.len(), 1);
        assert_eq!(checks[0].status, ComplianceStatus::Pass);
    }

    #[test]
    fn exit_discharge_fails_when_stair_isolated() {
        let floor = FloorEgress {
            level: 1,
            occupancy: MajorOccupancy::Business,
            rooms: vec![RoomEgress {
                id: "lobby".into(),
                room_type: "lobby".into(),
                area_m2: 50.0,
                unit: None,
                center_m: (0.0, 0.0),
            }],
            edges: vec![],
            discharge_targets: vec!["lobby".into()],
            stairs: vec![StairEgress {
                id: "stairs_1".into(),
                centroid_m: (5.0, 0.0),
                width_clear_mm: 1200.0,
            }],
        };
        let checks = check_exit_discharge(&[floor]);
        assert_eq!(checks.len(), 1);
        assert_eq!(checks[0].status, ComplianceStatus::Fail);
    }

    #[test]
    fn exit_discharge_skips_upper_floors() {
        let floor = FloorEgress {
            level: 2,
            occupancy: MajorOccupancy::Business,
            rooms: vec![],
            edges: vec![],
            discharge_targets: vec![],
            stairs: vec![StairEgress {
                id: "stairs_1".into(),
                centroid_m: (0.0, 0.0),
                width_clear_mm: 1200.0,
            }],
        };
        let checks = check_exit_discharge(&[floor]);
        assert!(checks.is_empty());
    }

    #[test]
    fn exit_discharge_fails_when_no_targets() {
        let floor = FloorEgress {
            level: 1,
            occupancy: MajorOccupancy::Business,
            rooms: vec![],
            edges: vec![],
            discharge_targets: vec![],
            stairs: vec![StairEgress {
                id: "stairs_1".into(),
                centroid_m: (0.0, 0.0),
                width_clear_mm: 1200.0,
            }],
        };
        let checks = check_exit_discharge(&[floor]);
        assert_eq!(checks.len(), 1);
        assert_eq!(checks[0].status, ComplianceStatus::Fail);
    }
}
