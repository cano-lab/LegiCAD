//! Layout-quality checks — aesthetic / plausibility heuristics that sit on top
//! of OBC compliance. These are warnings, not code failures: a layout can pass
//! every OBC rule and still be awkward (hallway to nowhere, isolated room, etc.).

use archgeometry::SchemaDocument;
use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};

/// Kinds of layout-quality issue. Kept orthogonal from code-compliance issues
/// so callers can surface them separately.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum LayoutQualityIssueKind {
    /// A hallway/corridor that touches only one room (or only other hallways).
    DeadEndHallway,
    /// A hallway/corridor with no adjacent habitable/service rooms — it exists
    /// but does not serve anything.
    HallwayToNowhere,
    /// A room that cannot be reached from any entry or stair via door-connected
    /// adjacencies.
    IsolatedRoom,
    /// A room with an extreme aspect ratio (very long and narrow).
    SkinnyRoom,
    /// A plumbing-bearing room (bathroom, kitchen, laundry, etc.) that is far
    /// from the nearest other wet room. Long plumbing runs are expensive and
    /// harder to vent/stack.
    RoomFarFromPlumbingCore,
}

/// One layout-quality finding.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LayoutQualityIssue {
    pub id: String,
    pub kind: LayoutQualityIssueKind,
    pub element_ids: Vec<String>,
    pub level: Option<String>,
    pub message: String,
}

/// Run a focused set of layout-quality checks on a parsed building document.
#[must_use]
pub fn check(doc: &SchemaDocument) -> Vec<LayoutQualityIssue> {
    let mut out = Vec::new();
    let adj = build_adjacency(doc);
    let circulation: HashSet<String> = doc
        .rooms
        .values()
        .filter(|r| is_circulation(&r.room_type))
        .map(|r| r.id.clone())
        .collect();

    out.extend(dead_end_hallways(doc, &adj, &circulation));
    out.extend(hallways_to_nowhere(doc, &adj, &circulation));
    out.extend(isolated_rooms(doc, &adj));
    out.extend(skinny_rooms(doc));
    out.extend(rooms_far_from_plumbing_core(doc));
    out
}

fn is_circulation(room_type: &str) -> bool {
    matches!(
        room_type,
        "hallway" | "corridor" | "stairs" | "elevator" | "shaft" | "landing" | "foyer"
    )
}

fn is_wet_room(room_type: &str) -> bool {
    matches!(
        room_type,
        "kitchen"
            | "bathroom"
            | "bath"
            | "ensuite"
            | "powder"
            | "water_closet"
            | "toilet"
            | "laundry"
            | "utility"
            | "washroom"
            | "mudroom"
    )
}

fn is_door_connected_wall(wall: &archgeometry::SchemaWall) -> bool {
    // A wall with an empty or "exterior" room side is not a door-connected
    // interior partition. We treat any wall whose both sides name real rooms as
    // an adjacency; the door list refines passability below.
    let a = wall.rooms.first().map_or("", String::as_str);
    let b = wall.rooms.get(1).map_or("", String::as_str);
    !a.is_empty() && a != "exterior" && !b.is_empty() && b != "exterior" && a != b
}

/// Undirected adjacency graph: room id → set of adjacent room ids.
/// Built from interior walls, then filtered to only edges that have at least one
/// door between the two rooms.
#[must_use]
fn build_adjacency(doc: &SchemaDocument) -> HashMap<String, HashSet<String>> {
    let mut adj: HashMap<String, HashSet<String>> = HashMap::new();

    // Seed every known room so isolated rooms show up with empty neighbour sets.
    for id in doc.rooms.keys() {
        adj.entry(id.clone()).or_default();
    }

    // Wall adjacencies.
    for wall in &doc.walls {
        if !is_door_connected_wall(wall) {
            continue;
        }
        let a = wall.rooms[0].clone();
        let b = wall.rooms[1].clone();
        adj.entry(a.clone()).or_default().insert(b.clone());
        adj.entry(b).or_default().insert(a);
    }

    // Door adjacencies refine passability.
    for door in &doc.doors {
        let a = door.room1.clone();
        let b = door.room2.clone();
        if a.is_empty() || b.is_empty() || a == b {
            continue;
        }
        adj.entry(a.clone()).or_default().insert(b.clone());
        adj.entry(b).or_default().insert(a);
    }

    adj
}

/// Return the set of room ids that serve as circulation roots: entries and
/// stairs. A hallway must ultimately connect back to one of these.
#[must_use]
fn roots(doc: &SchemaDocument) -> HashSet<String> {
    let mut roots = HashSet::new();
    for room in doc.rooms.values() {
        if room.room_type == "entry" || room.room_type == "foyer" {
            roots.insert(room.id.clone());
        }
    }
    for stair in &doc.stairs {
        roots.insert(stair.id.clone());
    }
    roots
}

#[must_use]
fn reachable_from(roots: &HashSet<String>, adj: &HashMap<String, HashSet<String>>) -> HashSet<String> {
    let mut visited = HashSet::new();
    let mut stack: Vec<String> = roots.iter().cloned().collect();
    while let Some(id) = stack.pop() {
        if !visited.insert(id.clone()) {
            continue;
        }
        if let Some(neighbors) = adj.get(&id) {
            for n in neighbors {
                if !visited.contains(n) {
                    stack.push(n.clone());
                }
            }
        }
    }
    visited
}

fn dead_end_hallways(
    doc: &SchemaDocument,
    adj: &HashMap<String, HashSet<String>>,
    circulation: &HashSet<String>,
) -> Vec<LayoutQualityIssue> {
    let mut out = Vec::new();
    for room in doc.rooms.values() {
        if room.room_type != "hallway" && room.room_type != "corridor" {
            continue;
        }
        let neighbors = adj.get(&room.id).map_or_else(HashSet::new, Clone::clone);
        let non_circ = neighbors.difference(circulation).count();
        if non_circ <= 1 && neighbors.len() <= 2 {
            out.push(LayoutQualityIssue {
                id: format!("lq_dead_end_hallway_{}", sanitize(&room.id)),
                kind: LayoutQualityIssueKind::DeadEndHallway,
                element_ids: vec![room.id.clone()],
                level: Some(room.level.clone()),
                message: format!(
                    "Hallway '{}' is a dead end: it connects to only {} non-circulation room(s).",
                    room.id,
                    non_circ
                ),
            });
        }
    }
    out
}

fn hallways_to_nowhere(
    doc: &SchemaDocument,
    adj: &HashMap<String, HashSet<String>>,
    circulation: &HashSet<String>,
) -> Vec<LayoutQualityIssue> {
    let mut out = Vec::new();
    for room in doc.rooms.values() {
        if room.room_type != "hallway" && room.room_type != "corridor" {
            continue;
        }
        let neighbors = adj.get(&room.id).map_or_else(HashSet::new, Clone::clone);
        let non_circ = neighbors.difference(circulation).count();
        if non_circ == 0 {
            out.push(LayoutQualityIssue {
                id: format!("lq_hallway_to_nowhere_{}", sanitize(&room.id)),
                kind: LayoutQualityIssueKind::HallwayToNowhere,
                element_ids: vec![room.id.clone()],
                level: Some(room.level.clone()),
                message: format!(
                    "Hallway '{}' does not serve any rooms; it only touches other circulation spaces.",
                    room.id
                ),
            });
        }
    }
    out
}

fn isolated_rooms(
    doc: &SchemaDocument,
    adj: &HashMap<String, HashSet<String>>,
) -> Vec<LayoutQualityIssue> {
    let root_set = roots(doc);
    let reachable = reachable_from(&root_set, adj);
    let mut out = Vec::new();
    for room in doc.rooms.values() {
        if is_circulation(&room.room_type) {
            continue;
        }
        if !reachable.contains(&room.id) {
            out.push(LayoutQualityIssue {
                id: format!("lq_isolated_room_{}", sanitize(&room.id)),
                kind: LayoutQualityIssueKind::IsolatedRoom,
                element_ids: vec![room.id.clone()],
                level: Some(room.level.clone()),
                message: format!(
                    "Room '{}' is not reachable from any entry or stair.",
                    room.id
                ),
            });
        }
    }
    out
}

fn skinny_rooms(doc: &SchemaDocument) -> Vec<LayoutQualityIssue> {
    let mut out = Vec::new();
    for room in doc.rooms.values() {
        let bounds = &room.bounds;
        let w = bounds.width;
        let d = bounds.height;
        let min_dim = w.min(d);
        let max_dim = w.max(d);
        if min_dim > 0.0 && max_dim / min_dim > 6.0 {
            out.push(LayoutQualityIssue {
                id: format!("lq_skinny_room_{}", sanitize(&room.id)),
                kind: LayoutQualityIssueKind::SkinnyRoom,
                element_ids: vec![room.id.clone()],
                level: Some(room.level.clone()),
                message: format!(
                    "Room '{}' is very elongated (aspect ratio {:.1}:1).",
                    room.id,
                    max_dim / min_dim
                ),
            });
        }
    }
    out
}

/// Maximum acceptable center-to-center distance between two plumbing-bearing
/// rooms before we warn about long plumbing runs. In millimetres.
const WET_ROOM_CLUSTER_THRESHOLD_MM: f32 = 6000.0;

fn rooms_far_from_plumbing_core(doc: &SchemaDocument) -> Vec<LayoutQualityIssue> {
    let wet_rooms: Vec<&archgeometry::SchemaRoom> = doc
        .rooms
        .values()
        .filter(|r| is_wet_room(&r.room_type))
        .collect();

    if wet_rooms.len() < 2 {
        return Vec::new();
    }

    let mut out = Vec::new();
    for (i, room) in wet_rooms.iter().enumerate() {
        let mut nearest = f32::INFINITY;
        for (j, other) in wet_rooms.iter().enumerate() {
            if i == j {
                continue;
            }
            let dist = room.center.distance(other.center);
            if dist < nearest {
                nearest = dist;
            }
        }
        if nearest > WET_ROOM_CLUSTER_THRESHOLD_MM {
            out.push(LayoutQualityIssue {
                id: format!("lq_far_from_plumbing_core_{}", sanitize(&room.id)),
                kind: LayoutQualityIssueKind::RoomFarFromPlumbingCore,
                element_ids: vec![room.id.clone()],
                level: Some(room.level.clone()),
                message: format!(
                    "Wet room '{}' is {:.1} m from the nearest other wet room; consider clustering plumbing rooms to reduce runs.",
                    room.id,
                    nearest / 1000.0
                ),
            });
        }
    }
    out
}

fn sanitize(s: &str) -> String {
    let mut out = String::new();
    for ch in s.chars() {
        if ch.is_ascii_alphanumeric() {
            out.push(ch.to_ascii_lowercase());
        } else if !out.ends_with('_') {
            out.push('_');
        }
    }
    out.trim_matches('_').to_string()
}

#[cfg(test)]
mod tests {
    use super::*;
    use archgeometry::{RoomBounds, SchemaRoom};

    fn empty_doc() -> SchemaDocument {
        SchemaDocument::default()
    }

    fn make_room(id: &str, room_type: &str, level: &str, x: f32, z: f32, w: f32, d: f32) -> SchemaRoom {
        SchemaRoom {
            id: id.into(),
            name: id.into(),
            room_type: room_type.into(),
            bounds: RoomBounds {
                x,
                y: z,
                width: w,
                height: d,
            },
            center: glam::Vec2::new(x + w / 2.0, z + d / 2.0),
            area: w * d / 1_000_000.0,
            zone: "private".into(),
            level: level.into(),
            ..Default::default()
        }
    }

    fn add_wall(doc: &mut SchemaDocument, a: &str, b: &str) {
        doc.walls.push(archgeometry::SchemaWall {
            rooms: [a.into(), b.into()],
            ..Default::default()
        });
    }

    fn add_door(doc: &mut SchemaDocument, a: &str, b: &str) {
        doc.doors.push(archgeometry::SchemaDoor {
            room1: a.into(),
            room2: b.into(),
            ..Default::default()
        });
    }

    #[test]
    fn flags_dead_end_hallway() {
        let mut doc = empty_doc();
        doc.rooms.insert("hall".into(), make_room("hall", "hallway", "Level 1", 0.0, 0.0, 1000.0, 2000.0));
        doc.rooms.insert("bed".into(), make_room("bed", "bedroom", "Level 1", 0.0, 2000.0, 1000.0, 1000.0));
        add_wall(&mut doc, "hall", "bed");
        add_door(&mut doc, "hall", "bed");
        let issues = check(&doc);
        assert!(issues.iter().any(|i| i.kind == LayoutQualityIssueKind::DeadEndHallway));
    }

    #[test]
    fn flags_hallway_to_nowhere() {
        let mut doc = empty_doc();
        doc.rooms.insert("hall1".into(), make_room("hall1", "hallway", "Level 1", 0.0, 0.0, 1000.0, 2000.0));
        doc.rooms.insert("hall2".into(), make_room("hall2", "hallway", "Level 1", 1000.0, 0.0, 1000.0, 2000.0));
        add_wall(&mut doc, "hall1", "hall2");
        add_door(&mut doc, "hall1", "hall2");
        let issues = check(&doc);
        assert!(issues.iter().any(|i| i.kind == LayoutQualityIssueKind::HallwayToNowhere));
    }

    #[test]
    fn flags_isolated_room() {
        let mut doc = empty_doc();
        doc.rooms.insert("entry".into(), make_room("entry", "entry", "Level 1", 0.0, 0.0, 1000.0, 1000.0));
        doc.rooms.insert("bed".into(), make_room("bed", "bedroom", "Level 1", 0.0, 1000.0, 1000.0, 1000.0));
        doc.rooms.insert("loft".into(), make_room("loft", "bedroom", "Level 1", 5000.0, 5000.0, 1000.0, 1000.0));
        add_wall(&mut doc, "entry", "bed");
        add_door(&mut doc, "entry", "bed");
        let issues = check(&doc);
        assert!(issues.iter().any(|i| i.kind == LayoutQualityIssueKind::IsolatedRoom && i.element_ids.contains(&"loft".into())));
    }

    #[test]
    fn flags_skinny_room() {
        let mut doc = empty_doc();
        doc.rooms.insert("entry".into(), make_room("entry", "entry", "Level 1", 0.0, 0.0, 1000.0, 1000.0));
        doc.rooms.insert("hall".into(), make_room("hall", "hallway", "Level 1", 1000.0, 0.0, 100.0, 6000.0));
        let issues = check(&doc);
        assert!(issues.iter().any(|i| i.kind == LayoutQualityIssueKind::SkinnyRoom));
    }

    #[test]
    fn flags_room_far_from_plumbing_core() {
        let mut doc = empty_doc();
        doc.rooms.insert("kitchen".into(), make_room("kitchen", "kitchen", "Level 1", 0.0, 0.0, 3000.0, 3000.0));
        doc.rooms.insert("bath".into(), make_room("bath", "bathroom", "Level 1", 9000.0, 0.0, 2500.0, 2500.0));
        let issues = check(&doc);
        assert!(issues.iter().any(|i| i.kind == LayoutQualityIssueKind::RoomFarFromPlumbingCore));
    }

    #[test]
    fn ignores_clustered_wet_rooms() {
        let mut doc = empty_doc();
        doc.rooms.insert("kitchen".into(), make_room("kitchen", "kitchen", "Level 1", 0.0, 0.0, 3000.0, 3000.0));
        doc.rooms.insert("bath".into(), make_room("bath", "bathroom", "Level 1", 2500.0, 0.0, 2500.0, 2500.0));
        let issues = check(&doc);
        assert!(!issues.iter().any(|i| i.kind == LayoutQualityIssueKind::RoomFarFromPlumbingCore));
    }

    #[test]
    fn single_wet_room_does_not_flag() {
        let mut doc = empty_doc();
        doc.rooms.insert("bath".into(), make_room("bath", "bathroom", "Level 1", 0.0, 0.0, 2500.0, 2500.0));
        let issues = check(&doc);
        assert!(!issues.iter().any(|i| i.kind == LayoutQualityIssueKind::RoomFarFromPlumbingCore));
    }
}
