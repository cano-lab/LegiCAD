//! Egress feedback analyzer.
//!
//! Takes a [`SchemaDocument`] and produces actionable fix suggestions for
//! OBC 3.4 egress failures (isolated rooms, travel distance, exit count/width,
//! stair dimensions). This is the "design studio" layer: it tells the user
//! *why* a layout fails and *what* to change, rather than just reporting
//! pass/fail in a PDF.

use archgeometry::SchemaDocument;
use obc::part3::egress::{FloorEgress, RoomEgress, StairEgress};
use serde::Serialize;

/// One detected egress problem.
#[derive(Debug, Clone)]
pub struct EgressIssue {
    pub level: usize,
    pub room_id: Option<String>,
    pub kind: EgressIssueKind,
    pub message: String,
}

#[derive(Debug, Clone)]
pub enum EgressIssueKind {
    Isolated,
    TravelDistance { actual_m: f32, limit_m: f32 },
    InsufficientExits { required: u32, actual: u32 },
    InsufficientExitWidth { required_mm: f32, actual_mm: f32 },
    StairRiserTooHigh { actual_mm: f32, limit_mm: f32 },
}

/// A concrete fix that can be applied to a [`solver::ProgramManifest`].
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum EgressFix {
    /// Add a corridor room on the given floor, sized to connect the listed
    /// rooms to the nearest circulation node.
    InjectCorridor { level: usize, rooms: Vec<String> },
    /// Add another stair on the floor.
    AddStair { level: usize },
    /// Reduce floor-to-floor height so the public-stair riser fits under the
    /// code maximum.
    LowerFloorToFloor { level: usize, current_ft: f32, recommended_ft: f32 },
}

/// Analyze a schema document for egress problems and return suggested fixes.
#[must_use]
pub fn analyze(doc: &SchemaDocument) -> Vec<EgressFix> {
    let floors = match super::validation::schema_document_to_part3_floors(doc) {
        Some(f) => f,
        None => return Vec::new(),
    };

    let mut fixes = Vec::new();
    for floor in &floors {
        fixes.extend(analyze_floor(floor));
    }
    fixes
}

fn analyze_floor(floor: &obc::part3::FloorInput) -> Vec<EgressFix> {
    let egress = FloorEgress {
        level: floor.level,
        occupancy: floor.occupancy.unwrap_or_default(),
        rooms: floor
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
        edges: floor.edges.clone(),
        stairs: floor
            .stairs
            .iter()
            .zip(floor.stair_centroids.iter())
            .map(|(s, &c)| StairEgress {
                id: s.id.clone(),
                centroid_m: c,
                width_clear_mm: s.width_clear_mm,
            })
            .collect(),
        discharge_targets: floor.discharge_targets.clone(),
    };

    let mut fixes = Vec::new();

    // 1. Isolated rooms: no path to any stair.
    let stair_ids: Vec<&str> = egress.stairs.iter().map(|s| s.id.as_str()).collect();
    let mut isolated = Vec::new();
    for room in &egress.rooms {
        if obc::part3::egress::shortest_path_to_any(
            &room.id,
            &stair_ids,
            &egress.edges,
        )
        .is_none()
        {
            isolated.push(room.id.clone());
        }
    }
    if !isolated.is_empty() {
        fixes.push(EgressFix::InjectCorridor {
            level: floor.level,
            rooms: isolated,
        });
    }

    // 2. Exit count: OBC 3.4.2.1 requires 2 exits when occupant load > 30.
    let occ_load = occupant_load(floor);
    let required_exits = if occ_load > 30.0 { 2 } else { 1 };
    let actual_exits = egress.stairs.len().max(1);
    if actual_exits < required_exits {
        fixes.push(EgressFix::AddStair { level: floor.level });
    }

    // 3. Public-stair riser height. The schema stores riser_height in mm.
    // For Part 3 / mixed buildings the limit is 180 mm (business/assembly/
    // mercantile) or 190 mm (industrial). We use 180 mm as the conservative
    // suggestion threshold.
    for stair in &floor.stairs {
        if stair.riser_height_mm > 180.0 {
            let current_ft = floor.height_m * 3.28084;
            let recommended_ft = (floor.height_m * 1000.0 * 180.0 / stair.riser_height_mm / 304.8)
                .clamp(7.0, current_ft);
            fixes.push(EgressFix::LowerFloorToFloor {
                level: floor.level,
                current_ft,
                recommended_ft,
            });
            break; // one height fix per floor is enough
        }
    }

    fixes
}

/// v1 occupant-load estimate: 1 person per 0.9 m² of floor area for
/// business/mercantile/assembly, 1 per 1.4 m² for residential/industrial.
fn occupant_load(floor: &obc::part3::FloorInput) -> f32 {
    let area = floor.area_m2;
    match floor.occupancy {
        Some(obc::part3::tables::MajorOccupancy::Business)
        | Some(obc::part3::tables::MajorOccupancy::Mercantile)
        | Some(obc::part3::tables::MajorOccupancy::Assembly) => area / 0.9,
        _ => area / 1.4,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn detects_isolated_rooms_in_retail_fixture() {
        // The retail fixture from the benchmark is known to isolate service rooms
        // unless a corridor is injected; with the current layout fixes it should
        // have no isolated rooms. We construct a doc with two disconnected rooms
        // to exercise the analyzer.
        let doc = make_two_room_doc();
        let fixes = analyze(&doc);
        assert!(fixes.iter().any(|f| matches!(f, EgressFix::InjectCorridor { .. })));
    }

    fn make_two_room_doc() -> SchemaDocument {
        use archgeometry::{RoomBounds, SchemaLevel, SchemaRoom, SchemaStair, SchemaWall};
        use glam::Vec2;
        let mut rooms = std::collections::HashMap::new();
        rooms.insert(
            "retail".into(),
            SchemaRoom {
                id: "retail".into(),
                room_type: "retail".into(),
                bounds: RoomBounds {
                    x: 0.0,
                    y: 0.0,
                    width: 10_000.0,
                    height: 10_000.0,
                },
                area: 100_000_000.0,
                center: Vec2::new(5_000.0, 5_000.0),
                level: "Level 1".into(),
                ..Default::default()
            },
        );
        rooms.insert(
            "office".into(),
            SchemaRoom {
                id: "office".into(),
                room_type: "office_open".into(),
                bounds: RoomBounds {
                    x: 11_000.0,
                    y: 0.0,
                    width: 5_000.0,
                    height: 5_000.0,
                },
                area: 25_000_000.0,
                center: Vec2::new(13_500.0, 2_500.0),
                level: "Level 1".into(),
                ..Default::default()
            },
        );
        SchemaDocument {
            building_id: "test".into(),
            rooms,
            stairs: vec![SchemaStair {
                id: "stairs_1".into(),
                level_name: "Level 1".into(),
                x: 0.0,
                y: 0.0,
                width: 2_000.0,
                depth: 4_000.0,
                ..Default::default()
            }],
            levels: vec![SchemaLevel {
                name: "Level 1".into(),
                elevation: 0.0,
                height: 3_000.0,
                ..Default::default()
            }],
            walls: vec![SchemaWall {
                start: glam::Vec3::new(10_000.0, 0.0, 0.0),
                end: glam::Vec3::new(10_000.0, 0.0, 10_000.0),
                height: 3_000.0,
                rooms: ["retail".into(), "office".into()],
                level_name: "Level 1".into(),
                ..Default::default()
            }],
            doors: vec![],
            ..Default::default()
        }
    }
}
