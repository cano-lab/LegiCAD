//! QBD validation orchestration.
//!
//! Ported from `QBDInterface::validateLayout` / `validateWall`
//! (`qbd_interface.cpp:883-931`). Wraps the `obc` engine: per-wall
//! compliance reports + an overall pass/fail with thermal aggregation.

use archgeometry::{SchemaDocument, SchemaWall};
use obc::{ComplianceReport, OBCEngine};
use serde::{Deserialize, Serialize};

use crate::wall_types;

/// Aggregated validation result. Mirrors the C++ `QBDValidationResult`.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ValidationResult {
    pub overall_pass: bool,
    pub wall_reports: Vec<ComplianceReport>,
    /// Stair compliance (OBC 9.8) — one report per stair shaft.
    pub stair_reports: Vec<ComplianceReport>,
    /// Part 3 compliance (area/height/storeys, egress, fire separation,
    /// public stairs) for Part 3 / mixed-mode buildings.
    pub part3_reports: Vec<ComplianceReport>,

    // Thermal summary.
    pub total_exterior_wall_area: f32,
    pub average_r_value: f32,
    pub thermal_compliance: bool,

    // Structural summary.
    pub walls_checked: i32,
    pub walls_passed: i32,
    pub walls_failed: i32,
}

impl ValidationResult {
    /// Human-readable summary matching `QBDValidationResult::getSummary`.
    #[must_use]
    pub fn summary(&self) -> String {
        use std::fmt::Write as _;
        let mut out = String::from("=== QBD Validation Summary ===\n");
        let pass_label = if self.overall_pass { "PASS" } else { "FAIL" };
        let thermal_label = if self.thermal_compliance {
            "PASS"
        } else {
            "FAIL"
        };
        #[allow(clippy::cast_possible_truncation)]
        let r_int = self.average_r_value as i32;
        let _ = writeln!(out, "Overall: {pass_label}");
        let _ = writeln!(
            out,
            "Walls: {}/{} passed",
            self.walls_passed, self.walls_checked
        );
        let _ = writeln!(out, "Thermal: R-{r_int} ({thermal_label})");
        let _ = writeln!(
            out,
            "Exterior Wall Area: {} sqft",
            self.total_exterior_wall_area
        );
        if !self.part3_reports.is_empty() {
            let p3_pass = self.part3_reports.iter().all(ComplianceReport::passes);
            let _ = writeln!(
                out,
                "Part 3 checks: {} ({})",
                self.part3_reports.len(),
                if p3_pass { "PASS" } else { "FAIL" }
            );
        }
        out
    }
}

/// Millimetres per imperial foot — used to convert schema wall heights
/// (mm) into the foot-based units the OBC stud-span tables expect.
const MM_PER_FT: f32 = 304.8;

/// Validate one wall against the OBC engine using the default wall-type
/// for its category. Matches `QBDInterface::validateWall`
/// (`qbd_interface.cpp:923`).
///
/// `wall_height_mm` is the schema-native millimetre height; the OBC engine
/// works in feet, so the conversion happens at the boundary.
#[must_use]
pub fn validate_wall(
    obc: &OBCEngine,
    wall: &SchemaWall,
    wall_height_mm: f32,
    climate_zone: &str,
) -> ComplianceReport {
    let wall_type = wall_types::for_category(&wall.category);
    obc.validate_wall_assembly(
        &wall_type,
        wall_height_mm / MM_PER_FT,
        wall.category == "exterior",
        climate_zone,
    )
}

/// Validate every wall in the schema and return an aggregated result.
/// Matches `QBDInterface::validateLayout` (`qbd_interface.cpp:883`).
///
/// Part 3 checks are skipped. Use [`validate_layout_with_part3`] when the
/// building mode is `part3` or `mixed`.
#[must_use]
pub fn validate_layout(
    obc: &OBCEngine,
    doc: &SchemaDocument,
    climate_zone: &str,
) -> ValidationResult {
    validate_layout_with_part3(obc, None, doc, climate_zone)
}

/// Validate every wall in the schema and run optional Part 3 checks.
#[must_use]
pub fn validate_layout_with_part3(
    obc: &OBCEngine,
    part3: Option<&obc::Part3Engine>,
    doc: &SchemaDocument,
    climate_zone: &str,
) -> ValidationResult {
    let mut result = ValidationResult::default();
    let mut exterior_wall_count = 0_usize;

    for wall in &doc.walls {
        let report = validate_wall(obc, wall, wall.height, climate_zone);
        let passed = report.passes();
        result.walls_checked += 1;
        if passed {
            result.walls_passed += 1;
        } else {
            result.walls_failed += 1;
        }
        result.wall_reports.push(report);

        if wall.category == "exterior" {
            result.total_exterior_wall_area += wall.length() * wall.height;
            exterior_wall_count += 1;
        }
    }

    if exterior_wall_count > 0 {
        let exterior_default = wall_types::for_category("exterior");
        result.average_r_value = exterior_default.total_r_value();
        let required_r = obc.minimum_r_value(climate_zone, "wall");
        result.thermal_compliance = result.average_r_value >= required_r;
    } else {
        // No exterior walls → thermal isn't applicable; don't fail on it.
        result.thermal_compliance = true;
    }

    // Stair compliance (OBC 9.8): rise/run/width per stair shaft.
    result.stair_reports = stair_reports(doc);
    let stairs_pass = result.stair_reports.iter().all(ComplianceReport::passes);

    // Part 3 compliance for commercial / mixed-use buildings only.
    if let Some(p3) = part3 {
        let mode = doc.qbd_answers.mode.as_str();
        if mode == "part3" || mode == "mixed" {
            if let Some(floors) = schema_document_to_part3_floors(doc) {
                // Mid-rise alternative-solution buildings are assumed sprinklered.
                let alternative_solution = floors.len() > 4;
                let sprinklered = alternative_solution;
                let mut report = p3.validate(&floors, sprinklered, alternative_solution); // sprinklered status deferred
                report.element_id = doc.building_id.clone();
                report.element_type = "part3_building".into();
                result.part3_reports.push(report);
            }
        }
    }
    let part3_pass = result.part3_reports.iter().all(ComplianceReport::passes);

    result.overall_pass =
        result.walls_failed == 0 && result.thermal_compliance && stairs_pass && part3_pass;
    result
}

/// One compliance report per stair, checking the solved rise/run/width against
/// OBC 9.8. The element id reads `"Stair … Level n (shape)"` so it groups
/// cleanly in the report table.
fn stair_reports(doc: &SchemaDocument) -> Vec<ComplianceReport> {
    doc.stairs
        .iter()
        .map(|st| {
            let spec = obc::stairs::StairSpec {
                num_risers: st.num_risers,
                num_treads: st.num_treads,
                riser_height_mm: st.riser_height,
                tread_run_mm: st.tread_run,
                floor_to_floor_mm: st.floor_to_floor,
            };
            let shape = if st.shape.is_empty() { "straight" } else { &st.shape };
            let mut report = ComplianceReport {
                element_id: format!("{} ({shape})", st.level_name),
                element_type: "stair".into(),
                checks: obc::stairs::check_stair(&spec, st.width_clear),
                ..Default::default()
            };
            report.compute_overall_status();
            report
        })
        .collect()
}

/// Convert the schema document into Part 3 `FloorInput`s grouped by level.
/// Returns `None` when no rooms can be mapped (empty document or malformed
/// level strings).
pub fn schema_document_to_part3_floors(doc: &SchemaDocument) -> Option<Vec<obc::part3::FloorInput>> {
    use obc::part3::{FloorInput, RoomInput, StairInput};
    use std::collections::HashMap;

    // Level name → height in metres and optional explicit occupancy.
    let level_heights: HashMap<&str, f32> = doc
        .levels
        .iter()
        .map(|lvl| (lvl.name.as_str(), lvl.height / 1000.0))
        .collect();
    let level_occupancy: HashMap<&str, Option<obc::part3::tables::MajorOccupancy>> = doc
        .levels
        .iter()
        .map(|lvl| {
            let occ = lvl
                .occupancy
                .as_deref()
                .and_then(obc::part3::tables::MajorOccupancy::from_str);
            (lvl.name.as_str(), occ)
        })
        .collect();

    // Group rooms by level number parsed from "Level N". The solver stores the
    // room id as the `rooms` map key, while `SchemaRoom.id` is currently empty
    // in emitted JSON, so we use the map key as the canonical id.
    let mut rooms_by_level: HashMap<usize, Vec<RoomInput>> = HashMap::new();
    let mut room_level: HashMap<&str, usize> = HashMap::new();
    for (room_id, room) in doc.rooms.iter() {
        let level_num = parse_level_number(&room.level)?;
        room_level.insert(room_id.as_str(), level_num);
        let area_m2 = if room.area > 0.0 {
            room.area
        } else {
            room.bounds.width * room.bounds.height
        };
        let area_m2 = area_m2 / 1_000_000.0;
        let center_m = (room.center.x / 1000.0, room.center.y / 1000.0);
        rooms_by_level.entry(level_num).or_default().push(RoomInput {
            id: room_id.clone(),
            room_type: room.room_type.clone(),
            area_m2,
            center_m,
            major_occupancy: None,
            unit: room.unit.clone(),
        });
    }

    // Group stairs by level.
    let mut stairs_by_level: HashMap<usize, Vec<StairInput>> = HashMap::new();
    let mut stair_centroids_by_level: HashMap<usize, Vec<(f32, f32)>> = HashMap::new();
    for stair in &doc.stairs {
        let level_num = parse_level_number(&stair.level_name)?;
        stairs_by_level.entry(level_num).or_default().push(StairInput {
            id: stair.id.clone(),
            width_clear_mm: stair.width_clear,
            riser_height_mm: stair.riser_height,
            tread_run_mm: stair.tread_run,
        });
        let cx_m = (stair.x + stair.width * 0.5) / 1000.0;
        let cy_m = (stair.y + stair.depth * 0.5) / 1000.0;
        stair_centroids_by_level
            .entry(level_num)
            .or_default()
            .push((cx_m, cy_m));
    }

    // Collect elevator rooms by level (any room whose type contains "elevator").
    let mut elevators_by_level: HashMap<usize, Vec<(f32, f32)>> = HashMap::new();
    for (room_id, room) in doc.rooms.iter() {
        if room.room_type.to_ascii_lowercase().contains("elevator") {
            let level_num = parse_level_number(&room.level)?;
            elevators_by_level
                .entry(level_num)
                .or_default()
                .push((room.center.x / 1000.0, room.center.y / 1000.0));
        }
    }

    // Build door-graph edges per level. Each door sits on a wall; the wall's
    // `rooms` array gives the two rooms it separates. We create one edge per
    // wall that carries at least one door, weighted by the centroid-to-centroid
    // distance of the two adjacent rooms.
    let mut walls_with_doors: std::collections::HashSet<i32> = std::collections::HashSet::new();
    for door in &doc.doors {
        walls_with_doors.insert(door.wall_index);
    }
    let mut edges_by_level: HashMap<usize, Vec<obc::part3::egress::RoomEdge>> = HashMap::new();
    let room_centres_mm: HashMap<&str, (f32, f32)> = doc
        .rooms
        .iter()
        .map(|(id, r)| (id.as_str(), (r.center.x, r.center.y)))
        .collect();
    for (idx, wall) in doc.walls.iter().enumerate() {
        if !walls_with_doors.contains(&(idx as i32)) {
            continue;
        }
        if wall.rooms[0].is_empty() || wall.rooms[1].is_empty() {
            continue;
        }
        let level_a = match room_level.get(wall.rooms[0].as_str()) {
            Some(&l) => l,
            None => continue,
        };
        let level_b = match room_level.get(wall.rooms[1].as_str()) {
            Some(&l) => l,
            None => continue,
        };
        if level_a != level_b {
            continue;
        }
        let (ax, ay) = match room_centres_mm.get(wall.rooms[0].as_str()) {
            Some(&c) => c,
            None => continue,
        };
        let (bx, by) = match room_centres_mm.get(wall.rooms[1].as_str()) {
            Some(&c) => c,
            None => continue,
        };
        let dx = (ax - bx) / 1000.0;
        let dy = (ay - by) / 1000.0;
        edges_by_level.entry(level_a).or_default().push(
            obc::part3::egress::RoomEdge {
                room_a: wall.rooms[0].clone(),
                room_b: wall.rooms[1].clone(),
                distance_m: (dx * dx + dy * dy).sqrt(),
            },
        );
    }

    // Connect each stair node to its corresponding stair room on the same
    // level. The stair room is already part of the door graph via its walls,
    // so this anchors the exit node into the circulation network.
    let stair_room_ids: std::collections::HashMap<(usize, &str), &str> = doc
        .rooms
        .iter()
        .filter(|(_, r)| r.room_type == "stairs")
        .filter_map(|(id, r)| {
            let level_num = parse_level_number(&r.level)?;
            Some(((level_num, id.as_str()), id.as_str()))
        })
        .collect();
    for stair in &doc.stairs {
        let level_num = parse_level_number(&stair.level_name)?;
        let room_id = match stair_room_ids.get(&(level_num, stair.id.as_str())) {
            Some(id) => id.to_string(),
            None => continue,
        };
        edges_by_level.entry(level_num).or_default().push(
            obc::part3::egress::RoomEdge {
                room_a: room_id,
                room_b: stair.id.clone(),
                distance_m: 0.0,
            },
        );
    }

    // Fallback: for corridor-spine and corridor-residential layouts, some
    // adjacencies are not expressed as walls with doors (e.g., unit bays that
    // open onto a corridor landing). Connect every non-circulation room to the
    // nearest corridor/hallway/lobby on the same floor so the egress graph
    // reflects the design intent.
    let circulation_types: std::collections::HashSet<&str> =
        ["corridor", "hallway", "lobby"].iter().copied().collect();
    let mut circulation_by_level: HashMap<usize, Vec<(&str, f32, f32)>> = HashMap::new();
    for (room_id, room) in doc.rooms.iter() {
        if !circulation_types.contains(room.room_type.as_str()) {
            continue;
        }
        let Some(&level_num) = room_level.get(room_id.as_str()) else {
            continue;
        };
        circulation_by_level
            .entry(level_num)
            .or_default()
            .push((room_id.as_str(), room.center.x / 1000.0, room.center.y / 1000.0));
    }
    for (room_id, room) in doc.rooms.iter() {
        if circulation_types.contains(room.room_type.as_str()) {
            continue;
        }
        let Some(&level_num) = room_level.get(room_id.as_str()) else {
            continue;
        };
        let candidates = match circulation_by_level.get(&level_num) {
            Some(v) => v,
            None => continue,
        };
        let rx = room.center.x / 1000.0;
        let ry = room.center.y / 1000.0;
        let nearest = candidates
            .iter()
            .map(|(id, cx, cy)| {
                let dx = rx - cx;
                let dy = ry - cy;
                (id, (dx * dx + dy * dy).sqrt())
            })
            .min_by(|a, b| a.1.partial_cmp(&b.1).unwrap_or(std::cmp::Ordering::Equal));
        if let Some((&cid, dist)) = nearest {
            edges_by_level.entry(level_num).or_default().push(
                obc::part3::egress::RoomEdge {
                    room_a: room_id.clone(),
                    room_b: cid.to_string(),
                    distance_m: dist,
                },
            );
        }
    }

    // Also anchor each stair to the nearest corridor/hallway/lobby on the same
    // floor so the stair exit node is reachable from the circulation spine.
    for stair in &doc.stairs {
        let level_num = parse_level_number(&stair.level_name)?;
        let candidates = match circulation_by_level.get(&level_num) {
            Some(v) => v,
            None => continue,
        };
        let sx = (stair.x + stair.width * 0.5) / 1000.0;
        let sy = (stair.y + stair.depth * 0.5) / 1000.0;
        let nearest = candidates
            .iter()
            .map(|(id, cx, cy)| {
                let dx = sx - cx;
                let dy = sy - cy;
                (id, (dx * dx + dy * dy).sqrt())
            })
            .min_by(|a, b| a.1.partial_cmp(&b.1).unwrap_or(std::cmp::Ordering::Equal));
        if let Some((&cid, dist)) = nearest {
            edges_by_level.entry(level_num).or_default().push(
                obc::part3::egress::RoomEdge {
                    room_a: cid.to_string(),
                    room_b: stair.id.clone(),
                    distance_m: dist,
                },
            );
        }
    }

    // Build physical wall adjacencies per level for horizontal fire-separation
    // checks. Unlike the egress door graph, this includes all shared walls,
    // with or without doors.
    let mut wall_adjacencies_by_level: HashMap<usize, Vec<(String, String)>> = HashMap::new();
    for wall in &doc.walls {
        if wall.rooms[0].is_empty() || wall.rooms[1].is_empty() {
            continue;
        }
        let level_a = match room_level.get(wall.rooms[0].as_str()) {
            Some(&l) => l,
            None => continue,
        };
        let level_b = match room_level.get(wall.rooms[1].as_str()) {
            Some(&l) => l,
            None => continue,
        };
        if level_a != level_b {
            continue;
        }
        // Normalize so (a,b) and (b,a) deduplicate.
        let pair = if wall.rooms[0] <= wall.rooms[1] {
            (wall.rooms[0].clone(), wall.rooms[1].clone())
        } else {
            (wall.rooms[1].clone(), wall.rooms[0].clone())
        };
        let level_adjs = wall_adjacencies_by_level.entry(level_a).or_default();
        if !level_adjs.contains(&pair) {
            level_adjs.push(pair);
        }
    }

    // Identify ground-floor (Level 1) exit-discharge targets: rooms with a door
    // on an exterior wall, plus lobby/vestibule/entry rooms.
    let mut discharge_targets_by_level: HashMap<usize, Vec<String>> = HashMap::new();
    let mut exterior_door_rooms = std::collections::HashSet::new();
    for door in &doc.doors {
        let wall_index = door.wall_index as usize;
        let wall = match doc.walls.get(wall_index) {
            Some(w) => w,
            None => continue,
        };
        if wall.category != "exterior" {
            continue;
        }
        for room_id in &wall.rooms {
            if room_id.is_empty() {
                continue;
            }
            if let Some(&level_num) = room_level.get(room_id.as_str()) {
                if level_num == 1 {
                    exterior_door_rooms.insert(room_id.clone());
                }
            }
        }
    }
    for (room_id, room) in doc.rooms.iter() {
        if matches!(
            room.room_type.as_str(),
            "lobby" | "vestibule" | "entry"
        ) {
            if let Some(&level_num) = room_level.get(room_id.as_str()) {
                if level_num == 1 {
                    exterior_door_rooms.insert(room_id.clone());
                }
            }
        }
    }
    if !exterior_door_rooms.is_empty() {
        discharge_targets_by_level.insert(
            1,
            exterior_door_rooms.into_iter().collect(),
        );
    }

    let mut floors: Vec<FloorInput> = rooms_by_level
        .into_iter()
        .map(|(level, rooms)| {
            let level_name = format!("Level {level}");
            let area_m2 = rooms.iter().map(|r| r.area_m2).sum();
            let height_m = level_heights
                .get(level_name.as_str())
                .copied()
                .unwrap_or(3.0);
            let occupancy = level_occupancy
                .get(level_name.as_str())
                .copied()
                .flatten();
            FloorInput {
                level,
                area_m2,
                height_m,
                rooms,
                edges: edges_by_level.remove(&level).unwrap_or_default(),
                wall_adjacencies: wall_adjacencies_by_level
                    .remove(&level)
                    .unwrap_or_default(),
                discharge_targets: discharge_targets_by_level
                    .remove(&level)
                    .unwrap_or_default(),
                stair_centroids: stair_centroids_by_level.remove(&level).unwrap_or_default(),
                stairs: stairs_by_level.remove(&level).unwrap_or_default(),
                elevators: elevators_by_level.remove(&level).unwrap_or_default(),
                occupancy,
            }
        })
        .collect();
    floors.sort_by_key(|f| f.level);
    Some(floors)
}

fn parse_level_number(level: &str) -> Option<usize> {
    level
        .strip_prefix("Level ")
        .and_then(|s| s.parse::<usize>().ok())
}

#[cfg(test)]
mod tests {
    use super::*;
    use archgeometry::SchemaWall;
    use glam::Vec3;

    #[test]
    fn empty_layout_passes_trivially() {
        let obc = OBCEngine::new();
        let doc = SchemaDocument::default();
        let r = validate_layout(&obc, &doc, "Zone 6");
        assert_eq!(r.walls_checked, 0);
        assert!(r.overall_pass);
    }

    #[test]
    fn one_exterior_wall_aggregates_area_and_r_value() {
        let obc = OBCEngine::new();
        let doc = SchemaDocument {
            walls: vec![SchemaWall {
                start: Vec3::ZERO,
                end: Vec3::new(5000.0, 0.0, 0.0),
                height: 2700.0,
                category: "exterior".into(),
                ..Default::default()
            }],
            ..Default::default()
        };
        let r = validate_layout(&obc, &doc, "Zone 6");
        assert_eq!(r.walls_checked, 1);
        // Area = 5000mm × 2700mm = 13_500_000 (mm² in this aggregation).
        assert!((r.total_exterior_wall_area - 13_500_000.0).abs() < 1.0);
        // Default exterior wall type (R-22 batt + R-5 c.i.) has total R = 28.45.
        assert!((r.average_r_value - 28.45).abs() < 0.01);
        // Zone 6 requires R-24 → passes thermal with R-28.45.
        assert!(r.thermal_compliance);
    }

    #[test]
    fn compliant_stair_adds_a_passing_report() {
        let obc = OBCEngine::new();
        let doc = SchemaDocument {
            stairs: vec![archgeometry::SchemaStair {
                level_name: "Level 1".into(),
                num_risers: 16,
                num_treads: 15,
                riser_height: 190.5,
                tread_run: 255.0,
                width_clear: 864.0,
                floor_to_floor: 3048.0,
                shape: "switchback".into(),
                going: "up".into(),
                ..Default::default()
            }],
            ..Default::default()
        };
        let r = validate_layout(&obc, &doc, "Zone 6");
        assert_eq!(r.stair_reports.len(), 1);
        assert!(r.stair_reports[0].passes());
        assert!(r.overall_pass, "compliant stair keeps the layout passing");
    }

    #[test]
    fn narrow_stair_fails_the_layout() {
        let obc = OBCEngine::new();
        let doc = SchemaDocument {
            stairs: vec![archgeometry::SchemaStair {
                level_name: "Level 1".into(),
                num_risers: 16,
                num_treads: 15,
                riser_height: 190.5,
                tread_run: 255.0,
                width_clear: 700.0, // below the 860 mm minimum
                floor_to_floor: 3048.0,
                shape: "switchback".into(),
                ..Default::default()
            }],
            ..Default::default()
        };
        let r = validate_layout(&obc, &doc, "Zone 6");
        assert!(!r.stair_reports[0].passes());
        assert!(!r.overall_pass, "a non-compliant stair must fail the layout");
    }

    #[test]
    fn summary_contains_pass_or_fail_marker() {
        let obc = OBCEngine::new();
        let doc = SchemaDocument::default();
        let r = validate_layout(&obc, &doc, "Zone 6");
        let s = r.summary();
        assert!(s.contains("Overall: PASS") || s.contains("Overall: FAIL"));
        assert!(s.contains("Walls:"));
    }

    #[test]
    fn part3_office_building_produces_part3_report() {
        let obc = OBCEngine::new();
        let mut part3 = obc::Part3Engine::new();
        let dir: std::path::PathBuf = [
            env!("CARGO_MANIFEST_DIR"),
            "..",
            "..",
            "OBC_Library",
        ]
        .iter()
        .collect();
        if part3.initialize(&dir).is_err() {
            return; // OBC_Library not present in this test environment
        }

        let mut rooms = std::collections::HashMap::new();
        rooms.insert(
            "lobby".into(),
            archgeometry::SchemaRoom {
                id: "lobby".into(),
                room_type: "lobby".into(),
                bounds: archgeometry::RoomBounds {
                    x: 0.0,
                    y: 0.0,
                    width: 5_000.0,
                    height: 5_000.0,
                },
                area: 25_000_000.0,
                center: glam::Vec2::new(2_500.0, 2_500.0),
                level: "Level 1".into(),
                ..Default::default()
            },
        );
        rooms.insert(
            "office".into(),
            archgeometry::SchemaRoom {
                id: "office".into(),
                room_type: "office_open".into(),
                bounds: archgeometry::RoomBounds {
                    x: 5_000.0,
                    y: 0.0,
                    width: 10_000.0,
                    height: 20_000.0,
                },
                area: 200_000_000.0,
                center: glam::Vec2::new(10_000.0, 10_000.0),
                level: "Level 1".into(),
                ..Default::default()
            },
        );

        let mut doc = SchemaDocument {
            building_id: "part3-office".into(),
            walls: vec![
                SchemaWall {
                    start: Vec3::new(5_000.0, 0.0, 0.0),
                    end: Vec3::new(5_000.0, 0.0, 20_000.0),
                    height: 2700.0,
                    category: "interior".into(),
                    rooms: ["lobby".into(), "office".into()],
                    level_name: "Level 1".into(),
                    ..Default::default()
                },
                SchemaWall {
                    start: Vec3::new(0.0, 0.0, 0.0),
                    end: Vec3::new(0.0, 0.0, 5_000.0),
                    height: 2700.0,
                    category: "exterior".into(),
                    rooms: ["lobby".into(), "".into()],
                    level_name: "Level 1".into(),
                    ..Default::default()
                },
            ],
            doors: vec![
                archgeometry::SchemaDoor {
                    wall_index: 0,
                    ..Default::default()
                },
                archgeometry::SchemaDoor {
                    wall_index: 1,
                    ..Default::default()
                },
            ],
            stairs: vec![archgeometry::SchemaStair {
                id: "stairs_1".into(),
                level_name: "Level 1".into(),
                num_risers: 18,
                num_treads: 17,
                riser_height: 175.0,
                tread_run: 280.0,
                width_clear: 1200.0,
                floor_to_floor: 3048.0,
                x: 10_000.0,
                y: 10_000.0,
                width: 2_000.0,
                depth: 4_000.0,
                shape: "switchback".into(),
                going: "up".into(),
                ..Default::default()
            }],
            levels: vec![archgeometry::SchemaLevel {
                name: "Level 1".into(),
                elevation: 0.0,
                height: 2700.0,
                ..Default::default()
            }],
            rooms,
            ..Default::default()
        };
        doc.qbd_answers.mode = "part3".into();

        let r = validate_layout_with_part3(&obc, Some(&part3), &doc, "Zone 6");
        assert!(!r.part3_reports.is_empty(), "Part 3 report should be present");
        assert!(
            r.part3_reports[0].passes(),
            "Part 3 office should pass: {:?}",
            r.part3_reports[0].checks
        );
        assert!(r.overall_pass);
        let has_exit_discharge = r.part3_reports.iter().any(|report| {
            report
                .checks
                .iter()
                .any(|c| c.rule_name.contains("exit discharge"))
        });
        assert!(
            has_exit_discharge,
            "ground-floor stair with exterior-door lobby should have an exit-discharge check"
        );
        let summary = r.summary();
        assert!(summary.contains("Part 3 checks:"));
    }

    #[test]
    fn part3_mixed_occupancy_floor_triggers_horizontal_fire_separation() {
        let obc = OBCEngine::new();
        let mut part3 = obc::Part3Engine::new();
        let dir: std::path::PathBuf = [
            env!("CARGO_MANIFEST_DIR"),
            "..",
            "..",
            "OBC_Library",
        ]
        .iter()
        .collect();
        if part3.initialize(&dir).is_err() {
            return; // OBC_Library not present in this test environment
        }

        let mut rooms = std::collections::HashMap::new();
        rooms.insert(
            "retail".into(),
            archgeometry::SchemaRoom {
                id: "retail".into(),
                room_type: "retail".into(),
                bounds: archgeometry::RoomBounds {
                    x: 0.0,
                    y: 0.0,
                    width: 10_000.0,
                    height: 10_000.0,
                },
                area: 100_000_000.0,
                center: glam::Vec2::new(5_000.0, 5_000.0),
                level: "Level 1".into(),
                ..Default::default()
            },
        );
        rooms.insert(
            "office".into(),
            archgeometry::SchemaRoom {
                id: "office".into(),
                room_type: "office_open".into(),
                bounds: archgeometry::RoomBounds {
                    x: 10_000.0,
                    y: 0.0,
                    width: 10_000.0,
                    height: 10_000.0,
                },
                area: 100_000_000.0,
                center: glam::Vec2::new(15_000.0, 5_000.0),
                level: "Level 1".into(),
                ..Default::default()
            },
        );

        let mut doc = SchemaDocument {
            building_id: "part3-mixed-floor".into(),
            walls: vec![SchemaWall {
                start: Vec3::new(10_000.0, 0.0, 0.0),
                end: Vec3::new(10_000.0, 0.0, 10_000.0),
                height: 2700.0,
                category: "interior".into(),
                rooms: ["retail".into(), "office".into()],
                level_name: "Level 1".into(),
                ..Default::default()
            }],
            doors: vec![],
            stairs: vec![],
            levels: vec![archgeometry::SchemaLevel {
                name: "Level 1".into(),
                elevation: 0.0,
                height: 2700.0,
                ..Default::default()
            }],
            rooms,
            ..Default::default()
        };
        doc.qbd_answers.mode = "part3".into();

        let r = validate_layout_with_part3(&obc, Some(&part3), &doc, "Zone 6");
        assert!(!r.part3_reports.is_empty(), "Part 3 report should be present");
        let has_horizontal = r.part3_reports.iter().any(|report| {
            report
                .checks
                .iter()
                .any(|c| c.rule_name.contains("horizontal fire separation"))
        });
        assert!(
            has_horizontal,
            "retail + office on same floor should trigger a horizontal fire-separation check"
        );
    }
}
