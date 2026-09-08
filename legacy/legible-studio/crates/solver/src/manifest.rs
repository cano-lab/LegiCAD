//! Program manifest import.
//!
//! A manifest is a JSON document that describes a building program directly:
//! mode, floors, rooms per floor with optional area/weight overrides, and
//! explicit adjacency requests. It replaces the residential questionnaire for
//! Part 3 and mixed-use buildings, and can also be used for bespoke Part 9
//! houses driven from Claude Code.

use crate::catalog::RoomCatalog;
use crate::mode::BuildingMode;
use crate::RoomSpec;
use serde::{Deserialize, Serialize};
use std::collections::HashSet;

/// Top-level manifest.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct ProgramManifest {
    /// Design mode. Defaults to Part 9 for backward compatibility.
    pub mode: BuildingMode,
    /// Human-readable building name.
    pub building_name: String,
    /// Total requested footprint area, sqft. If omitted, the solver grows the
    /// envelope to fit the room minimums.
    pub sqft: Option<f32>,
    /// Floor-to-floor height in feet. Defaults to 10 ft.
    pub floor_to_floor_ft: f32,
    /// Floors, ordered from lowest to highest level.
    pub floors: Vec<FloorManifest>,
    /// Global adjacency overrides between room ids or room types.
    pub adjacency: Vec<AdjacencySpec>,
}

impl Default for ProgramManifest {
    fn default() -> Self {
        Self {
            mode: BuildingMode::Part9,
            building_name: "Building".into(),
            sqft: None,
            floor_to_floor_ft: 10.0,
            floors: Vec::new(),
            adjacency: Vec::new(),
        }
    }
}

impl ProgramManifest {
    /// Parse a manifest from JSON bytes.
    pub fn from_json(s: &str) -> Result<Self, ManifestError> {
        serde_json::from_str(s).map_err(ManifestError::Parse)
    }

    /// Validate the manifest against the room catalog for its mode. Returns a
    /// list of human-readable errors, or an empty vector if valid.
    pub fn validate(&self,
    ) -> Result<(), Vec<String>> {
        let mut errors = Vec::new();
        let catalog = RoomCatalog::for_mode(self.mode);

        if self.floors.is_empty() {
            errors.push("manifest must contain at least one floor".into());
        }

        let mut seen_ids = HashSet::new();
        for (fi, floor) in self.floors.iter().enumerate() {
            if floor.rooms.is_empty() {
                errors.push(format!("floor {} ({}) has no rooms", fi, floor.name));
            }
            for room in &floor.rooms {
                if !seen_ids.insert(room.id.clone()) {
                    errors.push(format!("duplicate room id '{}'", room.id));
                }
                if !catalog.contains(&room.room_type) {
                    errors.push(format!(
                        "floor {} room '{}' has unknown room type '{}' for mode {}",
                        fi, room.id, room.room_type, self.mode
                    ));
                }
            }
        }

        // Unit validation: a unit id may only appear on one floor and should
        // contain at least one sleeping / living room.
        let mut unit_to_floor: std::collections::HashMap<String, usize> = std::collections::HashMap::new();
        let mut unit_has_dwelling_room: std::collections::HashMap<String, bool> =
            std::collections::HashMap::new();
        for (fi, floor) in self.floors.iter().enumerate() {
            for room in &floor.rooms {
                if let Some(unit) = &room.unit {
                    if unit.is_empty() {
                        errors.push(format!("floor {} room '{}' has empty unit id", fi, room.id));
                        continue;
                    }
                    if let Some(prev_floor) = unit_to_floor.get(unit) {
                        if *prev_floor != fi {
                            errors.push(format!(
                                "unit '{}' appears on floor {} and floor {}; units must stay on one floor",
                                unit, prev_floor + 1, fi + 1
                            ));
                        }
                    } else {
                        unit_to_floor.insert(unit.clone(), fi);
                    }
                    let is_dwelling = matches!(
                        room.room_type.as_str(),
                        "studio"
                            | "one_bedroom"
                            | "two_bedroom"
                            | "three_bedroom"
                            | "suite"
                            | "bedroom"
                            | "primary_bedroom"
                            | "living"
                    );
                    *unit_has_dwelling_room.entry(unit.clone()).or_insert(false) |= is_dwelling;
                }
            }
        }
        for (unit, has_dwelling) in &unit_has_dwelling_room {
            if !has_dwelling {
                errors.push(format!(
                    "unit '{}' does not contain a bedroom or living room",
                    unit
                ));
            }
        }

        // Mode-specific required rooms.
        match self.mode {
            BuildingMode::Part9 => {
                // Nothing strictly required at manifest validation time;
                // the Part 9 solver can add missing stairs/hallways.
            }
            BuildingMode::Part3 | BuildingMode::Mixed => {
                let has_stairs = self.floors.iter().any(|f| {
                    f.rooms.iter().any(|r| r.room_type == "stairs")
                });
                if !has_stairs {
                    errors.push("Part 3 / mixed buildings require at least one stair".into());
                }
            }
        }

        if errors.is_empty() {
            Ok(())
        } else {
            Err(errors)
        }
    }

    /// Convert the manifest to one `Vec<RoomSpec>` per floor, preserving floor
    /// order. Areas/weights fall back to the catalog defaults.
    #[must_use]
    pub fn to_programs(&self,
    ) -> Vec<Vec<RoomSpec>> {
        let catalog = RoomCatalog::for_mode(self.mode);
        self.floors
            .iter()
            .map(|floor| {
                floor
                    .rooms
                    .iter()
                    .map(|r| {
                        let (default_weight, default_min_area) = catalog
                            .get(&r.room_type)
                            .map_or((1.0, 50.0), |e| (e.default_weight, e.default_min_area));
                        RoomSpec {
                            id: r.id.clone(),
                            room_type: r.room_type.clone(),
                            weight: r.weight.unwrap_or(default_weight),
                            min_area: r.min_area.unwrap_or(default_min_area),
                            unit: r.unit.clone(),
                        }
                    })
                    .collect()
            })
            .collect()
    }
}

/// One floor in a manifest.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct FloorManifest {
    /// 1-based level index.
    pub level: usize,
    /// Display name, e.g. "Ground" or "Level 2".
    pub name: String,
    /// Part 3 major occupancy for this floor (e.g. "mercantile", "business").
    pub occupancy: Option<String>,
    /// Rooms on this floor.
    pub rooms: Vec<RoomManifest>,
}

impl Default for FloorManifest {
    fn default() -> Self {
        Self {
            level: 1,
            name: "Level 1".into(),
            occupancy: None,
            rooms: Vec::new(),
        }
    }
}

/// One room in a manifest.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct RoomManifest {
    /// Unique id across the whole building.
    pub id: String,
    /// Room type from the catalog.
    pub room_type: String,
    /// Optional override of the catalog default weight.
    pub weight: Option<f32>,
    /// Optional override of the catalog default minimum area (sqft).
    pub min_area: Option<f32>,
    /// Room ids or room types this room should be adjacent to.
    #[serde(default)]
    pub adjacent_to: Vec<String>,
    /// If true, the solver should try to place this room on an exterior wall.
    #[serde(default)]
    pub needs_exterior: Option<bool>,
    /// Optional dwelling-unit id. Rooms sharing a unit id are treated as one
    /// apartment / suite for layout and code checks.
    #[serde(default)]
    pub unit: Option<String>,
}

/// Explicit adjacency override between two room ids or room types.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AdjacencySpec {
    pub a: String,
    pub b: String,
    /// 0 = unrelated, 1 = strongly want to share a wall.
    pub weight: f32,
}

#[derive(Debug)]
pub enum ManifestError {
    Parse(serde_json::Error),
}

impl std::fmt::Display for ManifestError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ManifestError::Parse(e) => write!(f, "JSON parse error: {e}"),
        }
    }
}

impl std::error::Error for ManifestError {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_minimal_part3_manifest() {
        let json = r#"{
            "mode": "part3",
            "building_name": "Office Block",
            "floors": [
                {
                    "level": 1,
                    "name": "Ground",
                    "occupancy": "business",
                    "rooms": [
                        {"id": "lobby", "room_type": "lobby", "min_area": 200},
                        {"id": "stairs_1", "room_type": "stairs", "min_area": 120},
                        {"id": "office_open", "room_type": "office_open", "min_area": 800}
                    ]
                }
            ]
        }"#;
        let m = ProgramManifest::from_json(json).unwrap();
        assert_eq!(m.mode, BuildingMode::Part3);
        assert_eq!(m.floors.len(), 1);
        assert_eq!(m.floors[0].rooms.len(), 3);
    }

    #[test]
    fn validation_rejects_unknown_room_type() {
        let json = r#"{
            "mode": "part3",
            "floors": [
                {
                    "level": 1,
                    "rooms": [
                        {"id": "r1", "room_type": "bedroom"},
                        {"id": "stairs_1", "room_type": "stairs"}
                    ]
                }
            ]
        }"#;
        let m = ProgramManifest::from_json(json).unwrap();
        let err = m.validate().unwrap_err();
        assert!(err.iter().any(|e| e.contains("bedroom") && e.contains("unknown")));
    }

    #[test]
    fn validation_requires_stairs_for_part3() {
        let json = r#"{
            "mode": "part3",
            "floors": [
                {
                    "level": 1,
                    "rooms": [
                        {"id": "office", "room_type": "office_open", "min_area": 800}
                    ]
                }
            ]
        }"#;
        let m = ProgramManifest::from_json(json).unwrap();
        let err = m.validate().unwrap_err();
        assert!(err.iter().any(|e| e.contains("stair")));
    }

    #[test]
    fn to_programs_uses_catalog_defaults() {
        let json = r#"{
            "mode": "part3",
            "floors": [
                {
                    "level": 1,
                    "rooms": [
                        {"id": "lobby", "room_type": "lobby"},
                        {"id": "stairs_1", "room_type": "stairs"}
                    ]
                }
            ]
        }"#;
        let m = ProgramManifest::from_json(json).unwrap();
        m.validate().unwrap();
        let programs = m.to_programs();
        assert_eq!(programs.len(), 1);
        let lobby = programs[0].iter().find(|r| r.id == "lobby").unwrap();
        assert_eq!(lobby.min_area, 200.0);
        assert_eq!(lobby.weight, 8.0);
    }

    #[test]
    fn validation_accepts_valid_unit() {
        let json = r#"{
            "mode": "part3",
            "floors": [
                {
                    "level": 1,
                    "rooms": [
                        {"id": "corridor", "room_type": "corridor"},
                        {"id": "stairs_1", "room_type": "stairs"},
                        {"id": "u1_living", "room_type": "one_bedroom", "unit": "u1"},
                        {"id": "u1_bath", "room_type": "washroom", "unit": "u1"}
                    ]
                }
            ]
        }"#;
        let m = ProgramManifest::from_json(json).unwrap();
        assert!(m.validate().is_ok());
    }

    #[test]
    fn validation_rejects_unit_spanning_floors() {
        let json = r#"{
            "mode": "part3",
            "floors": [
                {
                    "level": 1,
                    "rooms": [
                        {"id": "corridor", "room_type": "corridor"},
                        {"id": "stairs_1", "room_type": "stairs"},
                        {"id": "u1_living", "room_type": "one_bedroom", "unit": "u1"}
                    ]
                },
                {
                    "level": 2,
                    "rooms": [
                        {"id": "corridor", "room_type": "corridor"},
                        {"id": "stairs_1", "room_type": "stairs"},
                        {"id": "u1_bed", "room_type": "one_bedroom", "unit": "u1"}
                    ]
                }
            ]
        }"#;
        let m = ProgramManifest::from_json(json).unwrap();
        let err = m.validate().unwrap_err();
        assert!(err.iter().any(|e| e.contains("u1") && e.contains("floor")));
    }

    #[test]
    fn validation_rejects_unit_without_dwelling_room() {
        let json = r#"{
            "mode": "part3",
            "floors": [
                {
                    "level": 1,
                    "rooms": [
                        {"id": "corridor", "room_type": "corridor"},
                        {"id": "stairs_1", "room_type": "stairs"},
                        {"id": "u1_bath", "room_type": "washroom", "unit": "u1"}
                    ]
                }
            ]
        }"#;
        let m = ProgramManifest::from_json(json).unwrap();
        let err = m.validate().unwrap_err();
        assert!(err.iter().any(|e| e.contains("u1") && e.contains("bedroom")));
    }
}
