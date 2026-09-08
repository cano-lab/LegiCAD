//! Part 3 rules engine.
//!
//! Loads Division B tables from `OBC_Library/part3/` and runs OBC Part 3
//! compliance checks: occupancy area/height limits, egress travel distance,
//! fire separation, and public stair dimensions.

use crate::part3::{
    egress::{FloorEgress, RoomEgress, StairEgress},
    occupancy::{FloorSummary, check_area_height_limits, dominant_occupancy},
    stairs::StairInput,
    tables::{
        load_area_height_limits_from_json, load_fire_separations_from_json,
        load_stair_requirements_from_json, load_travel_distance_limits_from_json,
        AreaHeightLimit, FireSeparation, MajorOccupancy, StairRequirement,
        TravelDistanceLimit,
    },
};
use crate::report::ComplianceReport;
use std::collections::HashMap;
use std::path::Path;

#[derive(Debug, thiserror::Error)]
pub enum InitError {
    #[error("Part 3 tables directory not found: {0}")]
    TablesDirNotFound(String),
    #[error("I/O error reading {path}: {source}")]
    Io {
        path: String,
        #[source]
        source: std::io::Error,
    },
    #[error("JSON parse error in {path}: {source}")]
    Json {
        path: String,
        #[source]
        source: serde_json::Error,
    },
}

#[derive(Debug, Clone, Default)]
pub struct Part3Engine {
    library_path: String,
    initialized: bool,
    area_height_limits: HashMap<(MajorOccupancy, bool, bool), AreaHeightLimit>,
    travel_distance_limits: HashMap<MajorOccupancy, TravelDistanceLimit>,
    stair_requirements: HashMap<MajorOccupancy, StairRequirement>,
    fire_separations: Vec<FireSeparation>,
}

impl Part3Engine {
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    #[must_use]
    pub fn is_initialized(&self) -> bool {
        self.initialized
    }

    /// Load Part 3 Division B tables from `<path>/part3/`.
    pub fn initialize(&mut self, library_path: &Path) -> Result<(), InitError> {
        self.library_path = library_path.display().to_string();
        let part3_dir = library_path.join("part3");
        if !part3_dir.exists() {
            return Err(InitError::TablesDirNotFound(
                part3_dir.display().to_string(),
            ));
        }

        for (filename, loader) in [
            ("obc_3.2.2.1_area_height.json", TableKind::AreaHeight),
            ("obc_3.4.2.5_travel_distance.json", TableKind::TravelDistance),
            ("obc_3.4.6_stairs.json", TableKind::Stairs),
            ("obc_3.1_fire_separation.json", TableKind::FireSeparation),
        ] {
            let path = part3_dir.join(filename);
            if !path.exists() {
                continue;
            }
            let text = std::fs::read_to_string(&path).map_err(|source| InitError::Io {
                path: path.display().to_string(),
                source,
            })?;
            self.load_table_kind(loader, &text)
                .map_err(|source| InitError::Json {
                    path: path.display().to_string(),
                    source,
                })?;
        }

        self.initialized = true;
        Ok(())
    }

    fn load_table_kind(
        &mut self,
        kind: TableKind,
        json_str: &str,
    ) -> Result<(), serde_json::Error> {
        match kind {
            TableKind::AreaHeight => {
                self.area_height_limits = load_area_height_limits_from_json(json_str)?;
            }
            TableKind::TravelDistance => {
                self.travel_distance_limits = load_travel_distance_limits_from_json(json_str)?;
            }
            TableKind::Stairs => {
                self.stair_requirements = load_stair_requirements_from_json(json_str)?;
            }
            TableKind::FireSeparation => {
                self.fire_separations = load_fire_separations_from_json(json_str)?;
            }
        }
        Ok(())
    }

    /// Run all Part 3 checks on a building described by floor summaries.
    #[must_use]
    pub fn validate(
        &self,
        floors: &[FloorInput],
        sprinklered: bool,
        alternative_solution: bool,
    ) -> ComplianceReport {
        let mut checks = Vec::new();

        let floor_occupancy = |f: &FloorInput| -> MajorOccupancy {
            f.occupancy.unwrap_or_else(|| {
                dominant_occupancy(
                    &f.rooms.iter().map(|r| (r.room_type.clone(), r.area_m2)).collect::<Vec<_>>()
                )
            })
        };

        let area_height_floors: Vec<FloorSummary> = floors
            .iter()
            .map(|f| FloorSummary {
                level: f.level,
                occupancy: floor_occupancy(f),
                area_m2: f.area_m2,
                height_m: f.height_m,
                storey_count: floors.len() as u32,
            })
            .collect();
        checks.extend(check_area_height_limits(
            &self.area_height_limits,
            &area_height_floors,
            sprinklered,
            alternative_solution,
        ));

        let egress_floors: Vec<FloorEgress> = floors
            .iter()
            .map(|f| FloorEgress {
                level: f.level,
                occupancy: floor_occupancy(f),
                rooms: f
                    .rooms
                    .iter()
                    .map(|r| RoomEgress {
                        id: r.id.clone(),
                        room_type: r.room_type.clone(),
                        area_m2: r.area_m2,
                        unit: r.unit.clone(),
                        center_m: r.center_m,
                    })
                    .collect(),
                edges: f.edges.clone(),
                stairs: f
                    .stairs
                    .iter()
                    .zip(f.stair_centroids.iter())
                    .map(|(s, &c)| StairEgress {
                        id: s.id.clone(),
                        centroid_m: c,
                        width_clear_mm: s.width_clear_mm,
                    })
                    .collect(),
                discharge_targets: f.discharge_targets.clone(),
            })
            .collect();
        checks.extend(crate::part3::egress::check_travel_distance(
            &self.travel_distance_limits,
            &egress_floors,
        ));
        checks.extend(crate::part3::egress::check_exit_count(&egress_floors,
        ));
        checks.extend(crate::part3::egress::check_exit_width(&egress_floors,
        ));
        checks.extend(crate::part3::egress::check_exit_discharge(&egress_floors,
        ));

        let floor_occupancies: Vec<(usize, MajorOccupancy)> = area_height_floors
            .iter()
            .map(|f| (f.level, f.occupancy))
            .collect();
        checks.extend(crate::part3::fire_separation::check_fire_separations(
            &self.fire_separations,
            &floor_occupancies,
        ));
        for floor in floors {
            checks.extend(crate::part3::fire_separation::check_horizontal_fire_separations(
                &self.fire_separations,
                floor,
            ));
        }

        let all_elevators: Vec<(f32, f32)> = floors
            .iter()
            .flat_map(|f| f.elevators.clone())
            .collect();
        checks.extend(crate::part3::elevators::check_elevators(
            floors.len(),
            &all_elevators,
        ));

        // Suite / dwelling-unit separation for residential floors.
        let suite_floors: Vec<crate::part3::suite_separation::FloorInput> = floors
            .iter()
            .map(|f| crate::part3::suite_separation::FloorInput {
                level: f.level,
                occupancy: floor_occupancy(f),
                rooms: f
                    .rooms
                    .iter()
                    .map(|r| crate::part3::suite_separation::RoomInput {
                        id: r.id.clone(),
                        room_type: r.room_type.clone(),
                        unit: r.unit.clone(),
                    })
                    .collect(),
            })
            .collect();
        checks.extend(crate::part3::suite_separation::check_suite_separation(
            &suite_floors,
        ));

        for floor in floors {
            let occ = floor_occupancy(floor);
            checks.extend(crate::part3::stairs::check_public_stairs(
                &self.stair_requirements,
                &floor.stairs,
                occ,
            ));
        }

        let mut report = ComplianceReport {
            element_id: "part3_building".into(),
            element_type: "building".into(),
            checks,
            ..Default::default()
        };
        report.compute_overall_status();
        report
    }
}

#[derive(Debug, Clone)]
pub struct FloorInput {
    pub level: usize,
    pub area_m2: f32,
    pub height_m: f32,
    pub rooms: Vec<RoomInput>,
    /// Navigable room-to-room edges (doors) on this floor.
    pub edges: Vec<crate::part3::egress::RoomEdge>,
    /// Physical wall adjacencies on this floor, regardless of whether the
    /// wall has a door. Used for horizontal fire-separation checks.
    pub wall_adjacencies: Vec<(String, String)>,
    /// Ground-floor room IDs that are acceptable exit-discharge targets.
    pub discharge_targets: Vec<String>,
    pub stair_centroids: Vec<(f32, f32)>,
    pub stairs: Vec<StairInput>,
    pub elevators: Vec<(f32, f32)>,
    /// Optional explicit major occupancy for the floor. When present it
    /// overrides the room-type heuristic in `dominant_occupancy`.
    pub occupancy: Option<crate::part3::tables::MajorOccupancy>,
}

#[derive(Debug, Clone)]
pub struct RoomInput {
    pub id: String,
    pub room_type: String,
    pub area_m2: f32,
    pub center_m: (f32, f32),
    /// Optional explicit major occupancy. When absent, the engine resolves
    /// it from `room_type` via `occupancy_from_room_type`.
    pub major_occupancy: Option<crate::part3::tables::MajorOccupancy>,
    /// Optional dwelling-unit id for suite-separation checks.
    pub unit: Option<String>,
}

enum TableKind {
    AreaHeight,
    TravelDistance,
    Stairs,
    FireSeparation,
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    #[test]
    fn engine_loads_part3_tables() {
        let mut engine = Part3Engine::new();
        let dir: PathBuf = [
            env!("CARGO_MANIFEST_DIR"),
            "..",
            "..",
            "OBC_Library",
        ]
        .iter()
        .collect();
        engine.initialize(&dir).expect("OBC_Library/part3 should load");
        assert!(engine.is_initialized());
        assert!(!engine.area_height_limits.is_empty());
        assert!(!engine.travel_distance_limits.is_empty());
        assert!(!engine.stair_requirements.is_empty());
        assert!(!engine.fire_separations.is_empty());
    }

    #[test]
    fn engine_validates_small_office() {
        let mut engine = Part3Engine::new();
        let dir: PathBuf = [
            env!("CARGO_MANIFEST_DIR"),
            "..",
            "..",
            "OBC_Library",
        ]
        .iter()
        .collect();
        engine.initialize(&dir).expect("OBC_Library/part3 should load");

        let floors = vec![FloorInput {
            level: 1,
            area_m2: 450.0,
            height_m: 12.0,
            rooms: vec![
                RoomInput {
                    id: "lobby".into(),
                    room_type: "lobby".into(),
                    area_m2: 50.0,
                    center_m: (5.0, 5.0),
                    major_occupancy: None,
                    unit: None,
                },
                RoomInput {
                    id: "office".into(),
                    room_type: "office_open".into(),
                    area_m2: 200.0,
                    center_m: (20.0, 15.0),
                    major_occupancy: None,
                    unit: None,
                },
            ],
            edges: vec![
                crate::part3::egress::RoomEdge {
                    room_a: "lobby".into(),
                    room_b: "stairs_1".into(),
                    distance_m: 7.07,
                },
                crate::part3::egress::RoomEdge {
                    room_a: "office".into(),
                    room_b: "stairs_1".into(),
                    distance_m: 11.18,
                },
            ],
            wall_adjacencies: vec![],
            discharge_targets: vec!["lobby".into()],
            stair_centroids: vec![(10.0, 10.0)],
            stairs: vec![crate::part3::StairInput {
                id: "stairs_1".into(),
                width_clear_mm: 1200.0,
                riser_height_mm: 175.0,
                tread_run_mm: 280.0,
            }],
            elevators: vec![(12.0, 12.0)],
            occupancy: None,
        }];
        let report = engine.validate(&floors, false, false);
        assert!(!report.checks.is_empty());
        assert!(report.passes(), "small office should pass Part 3 limits");
    }

    #[test]
    fn horizontal_fire_separation_between_mixed_occupancies() {
        let mut engine = Part3Engine::new();
        let dir: PathBuf = [
            env!("CARGO_MANIFEST_DIR"),
            "..",
            "..",
            "OBC_Library",
        ]
        .iter()
        .collect();
        engine.initialize(&dir).expect("OBC_Library/part3 should load");

        let floors = vec![FloorInput {
            level: 1,
            area_m2: 450.0,
            height_m: 4.0,
            rooms: vec![
                RoomInput {
                    id: "retail".into(),
                    room_type: "retail".into(),
                    area_m2: 200.0,
                    center_m: (5.0, 5.0),
                    major_occupancy: None,
                    unit: None,
                },
                RoomInput {
                    id: "office".into(),
                    room_type: "office_open".into(),
                    area_m2: 200.0,
                    center_m: (15.0, 5.0),
                    major_occupancy: None,
                    unit: None,
                },
            ],
            edges: vec![],
            wall_adjacencies: vec![("office".into(), "retail".into())],
            discharge_targets: vec![],
            stair_centroids: vec![],
            stairs: vec![],
            elevators: vec![],
            occupancy: None,
        }];
        let report = engine.validate(&floors, false, false);
        let horizontal = report
            .checks
            .iter()
            .any(|c| c.rule_name.contains("horizontal fire separation"));
        assert!(horizontal, "mixed-occupancy floor should trigger horizontal fire-separation check");
    }

    #[test]
    fn exit_discharge_for_ground_floor_stair() {
        let mut engine = Part3Engine::new();
        let dir: PathBuf = [
            env!("CARGO_MANIFEST_DIR"),
            "..",
            "..",
            "OBC_Library",
        ]
        .iter()
        .collect();
        engine.initialize(&dir).expect("OBC_Library/part3 should load");

        let floors = vec![FloorInput {
            level: 1,
            area_m2: 450.0,
            height_m: 4.0,
            rooms: vec![
                RoomInput {
                    id: "lobby".into(),
                    room_type: "lobby".into(),
                    area_m2: 50.0,
                    center_m: (5.0, 5.0),
                    major_occupancy: None,
                    unit: None,
                },
            ],
            edges: vec![crate::part3::egress::RoomEdge {
                room_a: "stairs_1".into(),
                room_b: "lobby".into(),
                distance_m: 2.0,
            }],
            wall_adjacencies: vec![],
            discharge_targets: vec!["lobby".into()],
            stair_centroids: vec![(10.0, 10.0)],
            stairs: vec![crate::part3::StairInput {
                id: "stairs_1".into(),
                width_clear_mm: 1200.0,
                riser_height_mm: 175.0,
                tread_run_mm: 280.0,
            }],
            elevators: vec![],
            occupancy: None,
        }];
        let report = engine.validate(&floors, false, false);
        let discharge = report
            .checks
            .iter()
            .any(|c| c.rule_name.contains("exit discharge"));
        assert!(discharge, "ground-floor stair should trigger exit-discharge check");
        assert!(report.passes(), "lobby-connected stair should pass exit discharge");
    }
}
