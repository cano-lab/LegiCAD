//! Division B Part 3 table types and JSON loaders.
//!
//! Tables follow the same wire → domain pattern as the Part 9 tables in
//! `crate::tables`. All dimensions are metric (metres / square metres) unless
//! noted.

use serde::Deserialize;
use std::collections::HashMap;

/// Major occupancy classification from OBC 3.1.2.1 / 3.2.2.1.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
pub enum MajorOccupancy {
    #[default]
    Residential, // Group C
    Business,    // Group D
    Assembly,    // Group E
    Industrial,  // Group F
    Mercantile,  // Group M
    Parking,     // Group U — parking garages
}

impl MajorOccupancy {
    #[must_use]
    pub fn from_str(s: &str) -> Option<Self> {
        let normalized = s.to_ascii_lowercase().replace(' ', "_");
        match normalized.as_str() {
            "residential" | "group_c" | "c" => Some(MajorOccupancy::Residential),
            "business" | "office" | "group_d" | "d" => Some(MajorOccupancy::Business),
            "assembly" | "group_e" | "e" => Some(MajorOccupancy::Assembly),
            "industrial" | "group_f" | "f" => Some(MajorOccupancy::Industrial),
            "mercantile" | "retail" | "group_m" | "m" => Some(MajorOccupancy::Mercantile),
            "parking" | "group_u" | "u" => Some(MajorOccupancy::Parking),
            _ => None,
        }
    }

    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            MajorOccupancy::Residential => "residential",
            MajorOccupancy::Business => "business",
            MajorOccupancy::Assembly => "assembly",
            MajorOccupancy::Industrial => "industrial",
            MajorOccupancy::Mercantile => "mercantile",
            MajorOccupancy::Parking => "parking",
        }
    }
}

/// Building area / height / storey limits for one occupancy × sprinkler
/// combination (OBC Table 3.2.2.1).
#[derive(Debug, Clone, PartialEq, Default)]
pub struct AreaHeightLimit {
    pub occupancy: MajorOccupancy,
    pub sprinklered: bool,
    /// True when this row represents an alternative-solution compliance path
    /// (e.g. mid-rise residential beyond the as-of-right table limits).
    pub alternative_solution: bool,
    /// Maximum building area per storey, m².
    pub max_area_per_storey_m2: f32,
    /// Maximum building height, m.
    pub max_height_m: f32,
    /// Maximum number of storeys.
    pub max_storeys: u32,
}

/// Maximum travel distance by occupancy (OBC 3.4.2.5), in metres.
#[derive(Debug, Clone, PartialEq, Default)]
pub struct TravelDistanceLimit {
    pub occupancy: MajorOccupancy,
    pub max_distance_m: f32,
}

/// Public stair dimensional requirements (OBC 3.4.6), in mm where linear.
#[derive(Debug, Clone, PartialEq, Default)]
pub struct StairRequirement {
    pub occupancy: MajorOccupancy,
    /// Minimum clear width between handrails, mm.
    pub min_width_mm: f32,
    pub max_riser_mm: f32,
    pub min_tread_mm: f32,
}

/// Required fire-resistance rating between two major occupancies (OBC 3.1).
#[derive(Debug, Clone, PartialEq, Default)]
pub struct FireSeparation {
    pub occupancy_a: MajorOccupancy,
    pub occupancy_b: MajorOccupancy,
    /// Required rating in hours.
    pub rating_hours: f32,
}

// ---------------------------------------------------------------------------
// JSON wire types
// ---------------------------------------------------------------------------

#[derive(Debug, Deserialize)]
struct WireAreaHeightEntry {
    occupancy: String,
    #[serde(default)]
    sprinklered: bool,
    #[serde(default)]
    alternative_solution: bool,
    max_area_per_storey_m2: f32,
    max_height_m: f32,
    max_storeys: u32,
}

#[derive(Debug, Deserialize)]
struct WireTravelDistanceEntry {
    occupancy: String,
    max_distance_m: f32,
}

#[derive(Debug, Deserialize)]
struct WireStairEntry {
    occupancy: String,
    min_width_mm: f32,
    max_riser_mm: f32,
    min_tread_mm: f32,
}

#[derive(Debug, Deserialize)]
struct WireFireSeparationEntry {
    occupancy_a: String,
    occupancy_b: String,
    rating_hours: f32,
}

#[derive(Debug, Deserialize)]
struct WireAreaHeightFile {
    entries: Vec<WireAreaHeightEntry>,
}

#[derive(Debug, Deserialize)]
struct WireTravelDistanceFile {
    entries: Vec<WireTravelDistanceEntry>,
}

#[derive(Debug, Deserialize)]
struct WireStairFile {
    entries: Vec<WireStairEntry>,
}

#[derive(Debug, Deserialize)]
struct WireFireSeparationFile {
    entries: Vec<WireFireSeparationEntry>,
}

// ---------------------------------------------------------------------------
// Loaders
// ---------------------------------------------------------------------------

pub fn load_area_height_limits_from_json(
    json_str: &str,
) -> Result<HashMap<(MajorOccupancy, bool, bool), AreaHeightLimit>, serde_json::Error> {
    let wire: WireAreaHeightFile = serde_json::from_str(json_str)?;
    let mut out = HashMap::new();
    for e in wire.entries {
        if let Some(occ) = MajorOccupancy::from_str(&e.occupancy) {
            out.insert(
                (occ, e.sprinklered, e.alternative_solution),
                AreaHeightLimit {
                    occupancy: occ,
                    sprinklered: e.sprinklered,
                    alternative_solution: e.alternative_solution,
                    max_area_per_storey_m2: e.max_area_per_storey_m2,
                    max_height_m: e.max_height_m,
                    max_storeys: e.max_storeys,
                },
            );
        }
    }
    Ok(out)
}

pub fn load_travel_distance_limits_from_json(
    json_str: &str,
) -> Result<HashMap<MajorOccupancy, TravelDistanceLimit>, serde_json::Error> {
    let wire: WireTravelDistanceFile = serde_json::from_str(json_str)?;
    let mut out = HashMap::new();
    for e in wire.entries {
        if let Some(occ) = MajorOccupancy::from_str(&e.occupancy) {
            out.insert(
                occ,
                TravelDistanceLimit {
                    occupancy: occ,
                    max_distance_m: e.max_distance_m,
                },
            );
        }
    }
    Ok(out)
}

pub fn load_stair_requirements_from_json(
    json_str: &str,
) -> Result<HashMap<MajorOccupancy, StairRequirement>, serde_json::Error> {
    let wire: WireStairFile = serde_json::from_str(json_str)?;
    let mut out = HashMap::new();
    for e in wire.entries {
        if let Some(occ) = MajorOccupancy::from_str(&e.occupancy) {
            out.insert(
                occ,
                StairRequirement {
                    occupancy: occ,
                    min_width_mm: e.min_width_mm,
                    max_riser_mm: e.max_riser_mm,
                    min_tread_mm: e.min_tread_mm,
                },
            );
        }
    }
    Ok(out)
}

pub fn load_fire_separations_from_json(
    json_str: &str,
) -> Result<Vec<FireSeparation>, serde_json::Error> {
    let wire: WireFireSeparationFile = serde_json::from_str(json_str)?;
    let mut out = Vec::new();
    for e in wire.entries {
        if let (Some(a), Some(b)) = (
            MajorOccupancy::from_str(&e.occupancy_a),
            MajorOccupancy::from_str(&e.occupancy_b),
        ) {
            out.push(FireSeparation {
                occupancy_a: a,
                occupancy_b: b,
                rating_hours: e.rating_hours,
            });
        }
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn major_occupancy_from_str() {
        assert_eq!(MajorOccupancy::from_str("business"), Some(MajorOccupancy::Business));
        assert_eq!(MajorOccupancy::from_str("Group D"), Some(MajorOccupancy::Business));
        assert_eq!(MajorOccupancy::from_str("retail"), Some(MajorOccupancy::Mercantile));
        assert!(MajorOccupancy::from_str("unknown").is_none());
    }

    #[test]
    fn load_area_height_table() {
        let json = r#"{
            "entries": [
                {"occupancy": "business", "sprinklered": false, "max_area_per_storey_m2": 6000, "max_height_m": 36, "max_storeys": 6},
                {"occupancy": "business", "sprinklered": true, "max_area_per_storey_m2": 12000, "max_height_m": 60, "max_storeys": 12}
            ]
        }"#;
        let map = load_area_height_limits_from_json(json).unwrap();
        let unsprinklered = map.get(&(MajorOccupancy::Business, false, false)).unwrap();
        assert_eq!(unsprinklered.max_storeys, 6);
        let sprinklered = map.get(&(MajorOccupancy::Business, true, false)).unwrap();
        assert_eq!(sprinklered.max_storeys, 12);
    }

    #[test]
    fn load_travel_distance_table() {
        let json = r#"{
            "entries": [
                {"occupancy": "business", "max_distance_m": 45},
                {"occupancy": "mercantile", "max_distance_m": 30}
            ]
        }"#;
        let map = load_travel_distance_limits_from_json(json).unwrap();
        assert_eq!(map[&MajorOccupancy::Business].max_distance_m, 45.0);
        assert_eq!(map[&MajorOccupancy::Mercantile].max_distance_m, 30.0);
    }
}
