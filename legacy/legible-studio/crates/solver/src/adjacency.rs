//! Mode-aware adjacency graph.
//!
//! Replaces the hardcoded residential `affinity()` lookup table. Each
//! [`BuildingMode`] carries its own type-level relationship graph; a
//! [`ProgramManifest`] can add instance-level overrides (room-id to room-id
//! or room-type to room-type) and per-room `adjacent_to` requests.
//!
//! The graph is symmetric: edges are stored with sorted keys and lookups
//! normalize the order.

use crate::manifest::ProgramManifest;
use crate::mode::BuildingMode;
use crate::Zone;
use std::collections::{HashMap, HashSet};

/// Weighted relationship graph used to order rooms during layout.
#[derive(Debug, Clone)]
pub struct AdjacencyGraph {
    /// Type-level default weights for the mode.
    type_weights: HashMap<(String, String), f32>,
    /// Instance-level overrides from the manifest (by room id or room type).
    instance_weights: HashMap<(String, String), f32>,
    /// Bonus applied when two rooms share a zone.
    same_zone_bonus: f32,
    /// Penalty applied when two rooms are in different zones.
    cross_zone_penalty: f32,
}

impl AdjacencyGraph {
    /// Build the default graph for a mode.
    #[must_use]
    pub fn new_for_mode(mode: BuildingMode) -> Self {
        let (type_weights, same_zone_bonus, cross_zone_penalty) = match mode {
            BuildingMode::Part9 => (part9_type_weights(), 0.3, 0.05),
            BuildingMode::Part3 => (part3_type_weights(), 0.25, 0.04),
            BuildingMode::Mixed => (mixed_type_weights(), 0.25, 0.04),
        };
        Self {
            type_weights,
            instance_weights: HashMap::new(),
            same_zone_bonus,
            cross_zone_penalty,
        }
    }

    /// Add overrides from a manifest. `adjacency` entries and per-room
    /// `adjacent_to` items are treated as instance-level edges when they match
    /// a room id, otherwise as type-level edges.
    #[must_use]
    pub fn with_manifest(mut self, manifest: &ProgramManifest) -> Self {
        let ids: HashSet<String> = manifest
            .floors
            .iter()
            .flat_map(|f| f.rooms.iter().map(|r| r.id.clone()))
            .collect();

        for spec in &manifest.adjacency {
            self.add_manifest_edge(&spec.a, &spec.b, spec.weight, &ids);
        }
        for floor in &manifest.floors {
            for room in &floor.rooms {
                for other in &room.adjacent_to {
                    self.add_manifest_edge(&room.id, other, 0.95, &ids);
                }
            }
        }
        self
    }

    fn add_manifest_edge(
        &mut self,
        a: &str,
        b: &str,
        weight: f32,
        ids: &HashSet<String>,
    ) {
        // If both endpoints are room ids, store as an instance edge.
        // Otherwise store as a type-level edge.
        if ids.contains(a) && ids.contains(b) {
            self.instance_weights
                .insert(sorted_key(a, b), weight.clamp(0.0, 1.0));
        } else {
            self.type_weights
                .insert(sorted_key(a, b), weight.clamp(0.0, 1.0));
        }
    }

    /// Relationship weight between two rooms. Combines type-level defaults,
    /// instance overrides, and zone bonus/penalty. An explicit instance edge
    /// (by room id) takes precedence over type-level defaults.
    #[must_use]
    pub fn affinity(
        &self,
        a_id: &str,
        a_type: &str,
        b_id: &str,
        b_type: &str,
        zone_a: Zone,
        zone_b: Zone,
    ) -> f32 {
        // Instance edge by id has highest priority.
        if let Some(&weight) = self.instance_weights.get(&sorted_key(a_id, b_id)) {
            return weight;
        }

        // Type-level edge: prefer explicit entry, then same-zone fallback.
        let type_key = sorted_key(a_type, b_type);
        self.type_weights
            .get(&type_key)
            .copied()
            .unwrap_or_else(|| {
                if zone_a == zone_b {
                    self.same_zone_bonus
                } else {
                    self.cross_zone_penalty
                }
            })
    }

    /// Relationship weight using room specs (convenience).
    #[must_use]
    pub fn affinity_for_specs(
        &self,
        a: &crate::RoomSpec,
        b: &crate::RoomSpec,
    ) -> f32 {
        self.affinity(
            &a.id,
            &a.room_type,
            &b.id,
            &b.room_type,
            a.zone(),
            b.zone(),
        )
    }
}

fn sorted_key(a: &str, b: &str) -> (String, String) {
    if a <= b {
        (a.to_string(), b.to_string())
    } else {
        (b.to_string(), a.to_string())
    }
}

/// Part 9 type-level weights. Reconstructed from the original hardcoded
/// `affinity()` table so behaviour is identical when no manifest overrides
/// are present.
fn part9_type_weights() -> HashMap<(String, String), f32> {
    let mut m = HashMap::new();
    let mut insert = |a: &str, b: &str, w: f32| {
        m.insert(sorted_key(a, b), w);
    };
    // Public core.
    insert("entry", "living", 0.9);
    insert("entry", "foyer", 0.9);
    insert("foyer", "living", 0.9);
    insert("dining", "living", 0.85);
    insert("dining", "kitchen", 0.95);
    insert("kitchen", "living", 0.5);
    insert("living", "powder_room", 0.5);
    insert("entry", "powder_room", 0.5);
    // Service links.
    insert("garage", "mudroom", 0.95);
    insert("kitchen", "mudroom", 0.7);
    insert("kitchen", "pantry", 0.9);
    insert("kitchen", "laundry", 0.5);
    insert("laundry", "mudroom", 0.5);
    insert("entry", "hallway", 0.7);
    insert("hallway", "living", 0.7);
    // Stairs anchor circulation.
    insert("entry", "stairs", 0.85);
    insert("hallway", "stairs", 0.85);
    insert("living", "stairs", 0.4);
    // Private suite.
    insert("primary_bath", "primary_bedroom", 0.95);
    insert("primary_bedroom", "walk_in_closet", 0.9);
    insert("bedroom", "closet", 0.9);
    insert("bathroom", "bedroom", 0.6);
    insert("bathroom", "hallway", 0.7);
    insert("hallway", "primary_bedroom", 0.7);
    insert("bedroom", "hallway", 0.75);
    m
}

/// Part 3 type-level weights. Commercial room relationships: public spaces
/// cluster around lobbies/corridors; service rooms cluster together.
fn part3_type_weights() -> HashMap<(String, String), f32> {
    let mut m = HashMap::new();
    let mut insert = |a: &str, b: &str, w: f32| {
        m.insert(sorted_key(a, b), w);
    };

    // Public / front-of-house cluster around the lobby.
    insert("lobby", "entry", 0.95);
    insert("lobby", "reception", 0.95);
    insert("lobby", "foyer", 0.9);
    insert("lobby", "retail", 0.95);
    insert("lobby", "restaurant", 0.9);
    insert("lobby", "corridor", 0.95);
    insert("lobby", "hallway", 0.9);
    insert("lobby", "stairs", 0.95);
    insert("lobby", "elevator", 0.95);

    // Retail / restaurant want street frontage and adjacency to lobby/corridor.
    insert("retail", "corridor", 0.85);
    insert("retail", "restaurant", 0.6);
    insert("restaurant", "kitchenette", 0.9);
    insert("retail", "washroom", 0.5);
    insert("restaurant", "washroom", 0.6);

    // Office cluster.
    insert("office_open", "corridor", 0.95);
    insert("office_private", "corridor", 0.9);
    insert("office_open", "office_private", 0.7);
    insert("office_open", "conference", 0.85);
    insert("office_private", "conference", 0.75);
    insert("office_open", "kitchenette", 0.7);
    insert("conference", "kitchenette", 0.6);

    // Assembly / education.
    insert("classroom", "corridor", 0.9);
    insert("auditorium", "corridor", 0.85);
    insert("classroom", "auditorium", 0.5);

    // Circulation core.
    insert("corridor", "stairs", 0.95);
    insert("corridor", "elevator", 0.95);
    insert("corridor", "hallway", 0.9);
    insert("stairs", "elevator", 0.95);
    insert("stairs", "shaft", 0.9);
    insert("elevator", "shaft", 0.9);

    // Service rooms (keep near each other, away from public frontage).
    insert("washroom", "corridor", 0.9);
    insert("washroom", "hallway", 0.85);
    insert("mechanical", "electrical", 0.8);
    insert("mechanical", "storage", 0.7);
    insert("storage", "loading_dock", 0.9);
    insert("storage", "parking", 0.7);
    insert("janitor", "storage", 0.7);
    insert("janitor", "washroom", 0.6);

    m
}

/// Mixed mode combines Part 9 and Part 3 type weights. Where a pair exists in
/// both, Part 3 wins (it is the more constrained public/commercial rule).
fn mixed_type_weights() -> HashMap<(String, String), f32> {
    let mut m = part9_type_weights();
    for (k, v) in part3_type_weights() {
        // Mixed: take the higher weight so neither mode's adjacency is lost.
        m.entry(k).and_modify(|e| *e = e.max(v)).or_insert(v);
    }
    m
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn part9_graph_reproduces_original_affinity_table() {
        let g = AdjacencyGraph::new_for_mode(BuildingMode::Part9);
        // Spot-check a few key pairs from the original table.
        assert!(
            g.affinity("", "entry", "", "living", Zone::Public, Zone::Public)
                > 0.8
        );
        assert!(
            g.affinity("", "dining", "", "kitchen", Zone::Public, Zone::Public)
                > 0.9
        );
        assert!(
            g.affinity("", "garage", "", "mudroom", Zone::Service, Zone::Service)
                > 0.9
        );
        assert!(
            g.affinity("", "entry", "", "stairs", Zone::Public, Zone::Circulation)
                > 0.8
        );
        // Unrelated different-zone pair falls back to the cross-zone penalty.
        assert!(
            g.affinity("", "bedroom", "", "kitchen", Zone::Private, Zone::Public)
                < 0.1
        );
    }

    #[test]
    fn part3_graph_prefers_lobby_corridor_and_stairs() {
        let g = AdjacencyGraph::new_for_mode(BuildingMode::Part3);
        assert!(
            g.affinity("", "lobby", "", "corridor", Zone::Public, Zone::Circulation)
                > 0.9
        );
        assert!(
            g.affinity("", "retail", "", "corridor", Zone::Public, Zone::Circulation)
                > 0.8
        );
        assert!(
            g.affinity("", "office_open", "", "corridor", Zone::Public, Zone::Circulation)
                > 0.9
        );
        assert!(
            g.affinity("", "stairs", "", "elevator", Zone::Circulation, Zone::Circulation)
                > 0.9
        );
    }

    #[test]
    fn manifest_instance_override_overrides_type_default() {
        let json = r#"{
            "mode": "part3",
            "floors": [
                {
                    "level": 1,
                    "rooms": [
                        {"id": "lobby", "room_type": "lobby"},
                        {"id": "retail", "room_type": "retail"},
                        {"id": "stairs_1", "room_type": "stairs"}
                    ]
                }
            ],
            "adjacency": [
                {"a": "lobby", "b": "retail", "weight": 0.2}
            ]
        }"#;
        let manifest = ProgramManifest::from_json(json).unwrap();
        let g = AdjacencyGraph::new_for_mode(BuildingMode::Part3).with_manifest(&manifest);
        // Instance edge between lobby and retail overrides the type default.
        assert!(
            g.affinity("lobby", "lobby", "retail", "retail", Zone::Public, Zone::Public)
                < 0.3
        );
        // Stairs still anchor strongly to the lobby.
        assert!(
            g.affinity("lobby", "lobby", "stairs_1", "stairs", Zone::Public, Zone::Circulation)
                > 0.9
        );
    }
}
