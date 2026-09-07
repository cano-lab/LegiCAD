//! Building design mode: Part 9 residential, Part 3 commercial/mid-rise,
//! or a mixed-use building combining both.
//!
//! The mode is the top-level switch that selects the room catalog, the
//! adjacency graph, the layout engine, and the OBC rules engine. It is
//! intentionally separate from architectural style or occupancy class —
//! `BuildingMode` says *which code part drives the design*, while the catalog
//! and manifest supply the specific room types and occupancy.

use serde::{Deserialize, Serialize};
use std::str::FromStr;

/// Top-level design mode. New modes can be added as the engine grows;
/// `full_obc` is reserved for a future unified engine.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Default, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum BuildingMode {
    /// OBC Part 9 low-rise residential — the existing house path.
    #[default]
    Part9,
    /// OBC Part 3 commercial / mid-rise / assembly / business / mercantile.
    Part3,
    /// Mixed-use: Part 3 podium/lower floors plus Part 9 residential above.
    Mixed,
}

impl BuildingMode {
    /// String label used in CLI flags, API query params, and JSON manifests.
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            BuildingMode::Part9 => "part9",
            BuildingMode::Part3 => "part3",
            BuildingMode::Mixed => "mixed",
        }
    }

    /// True when the building contains any Part 3 regulated spaces.
    #[must_use]
    pub const fn has_part3(&self) -> bool {
        matches!(self, BuildingMode::Part3 | BuildingMode::Mixed)
    }

    /// True when the building contains any Part 9 regulated spaces.
    #[must_use]
    pub const fn has_part9(&self) -> bool {
        matches!(self, BuildingMode::Part9 | BuildingMode::Mixed)
    }
}

impl FromStr for BuildingMode {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.to_ascii_lowercase().as_str() {
            "part9" | "part_9" | "residential" | "house" => Ok(BuildingMode::Part9),
            "part3" | "part_3" | "commercial" => Ok(BuildingMode::Part3),
            "mixed" | "mixed_use" | "mixed-use" => Ok(BuildingMode::Mixed),
            _ => Err(format!(
                "unknown building mode '{s}', expected part9, part3, or mixed"
            )),
        }
    }
}

impl std::fmt::Display for BuildingMode {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.as_str())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_is_part9() {
        assert_eq!(BuildingMode::default(), BuildingMode::Part9);
    }

    #[test]
    fn from_str_accepts_aliases() {
        for s in ["part9", "Part9", "PART_9", "residential", "house"] {
            assert_eq!(BuildingMode::from_str(s).unwrap(), BuildingMode::Part9);
        }
        for s in ["part3", "Part3", "PART_3", "commercial"] {
            assert_eq!(BuildingMode::from_str(s).unwrap(), BuildingMode::Part3);
        }
        for s in ["mixed", "MIXED_USE", "mixed-use"] {
            assert_eq!(BuildingMode::from_str(s).unwrap(), BuildingMode::Mixed);
        }
    }

    #[test]
    fn from_str_rejects_garbage() {
        assert!(BuildingMode::from_str("skyscraper").is_err());
    }

    #[test]
    fn serde_round_trip() {
        for mode in [BuildingMode::Part9, BuildingMode::Part3, BuildingMode::Mixed] {
            let s = serde_json::to_string(&mode).unwrap();
            let back: BuildingMode = serde_json::from_str(&s).unwrap();
            assert_eq!(back, mode);
        }
    }
}
