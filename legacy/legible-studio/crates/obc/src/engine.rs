//! OBCEngine — span lookups + compliance validation.
//!
//! Ported from `obc_engine.hpp:166-316` and `obc_engine.cpp:40-721`.
//!
//! Span/height bucketing matches the C++ exactly (12 / 16 / 24 inch
//! buckets, smallest-first for required-size lookups). Compliance
//! message formatting uses `format::cpp_float` to match the C++
//! `std::to_string(float)` output (six decimal places).

use crate::format::{cpp_float, cpp_int};
use crate::report::{ComplianceCheck, ComplianceReport, ComplianceStatus};
use crate::tables::{
    HeaderEntry, SpanTable, StudTable, load_header_tables_from_json, load_joist_tables_from_json,
    load_rafter_tables_from_json, load_stud_tables_from_json, make_table_key,
};
use domain::{Building, ElementType, LayerFunction, WallType};
use std::collections::HashMap;
use std::path::Path;

/// Errors from `OBCEngine::initialize`.
#[derive(Debug, thiserror::Error)]
pub enum InitError {
    #[error("OBC tables directory not found: {0}")]
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
pub struct OBCEngine {
    library_path: String,
    initialized: bool,
    joist_tables: HashMap<String, SpanTable>,
    rafter_tables: HashMap<String, SpanTable>,
    stud_tables: HashMap<String, StudTable>,
    header_table: Vec<HeaderEntry>,
    /// `[zone][assembly_type] → minimum R-value`.
    thermal_requirements: HashMap<String, HashMap<String, f32>>,
}

impl OBCEngine {
    /// Construct with thermal requirements preloaded (the C++ does this in
    /// its constructor). Span/stud/header tables are still empty until
    /// `initialize` is called.
    #[must_use]
    pub fn new() -> Self {
        let mut engine = Self::default();
        engine.load_thermal_requirements();
        engine
    }

    /// True once `initialize` has successfully loaded the table files.
    #[must_use]
    pub fn is_initialized(&self) -> bool {
        self.initialized
    }

    #[must_use]
    pub fn library_path(&self) -> &str {
        &self.library_path
    }

    /// Load all known tables under `<path>/tables/`. Missing files are
    /// silently skipped (matches the C++ which only loads when the file
    /// exists). Returns the loaded engine on success.
    pub fn initialize(&mut self, library_path: &Path) -> Result<(), InitError> {
        self.library_path = library_path.display().to_string();
        let tables_dir = library_path.join("tables");
        if !tables_dir.exists() {
            return Err(InitError::TablesDirNotFound(
                tables_dir.display().to_string(),
            ));
        }

        for (filename, kind) in [
            ("obc_9.23_joists.json", TableKind::Joists),
            ("obc_9.23_studs.json", TableKind::Studs),
            ("obc_9.23_headers.json", TableKind::Headers),
            ("obc_9.23_rafters.json", TableKind::Rafters),
        ] {
            let path = tables_dir.join(filename);
            if !path.exists() {
                continue;
            }
            let text = std::fs::read_to_string(&path).map_err(|source| InitError::Io {
                path: path.display().to_string(),
                source,
            })?;
            self.load_table_kind(kind, &text)
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
            TableKind::Joists => {
                for (k, v) in load_joist_tables_from_json(json_str)? {
                    self.joist_tables.insert(k, v);
                }
            }
            TableKind::Rafters => {
                for (k, v) in load_rafter_tables_from_json(json_str)? {
                    self.rafter_tables.insert(k, v);
                }
            }
            TableKind::Studs => {
                for (k, v) in load_stud_tables_from_json(json_str)? {
                    self.stud_tables.insert(k, v);
                }
            }
            TableKind::Headers => {
                self.header_table = load_header_tables_from_json(json_str)?;
            }
        }
        Ok(())
    }

    fn load_thermal_requirements(&mut self) {
        // OBC SB-12 thermal requirements by climate zone. The canonical values
        // live in the free function `sb12_minimum_r`; mirror them into the
        // instance map so `minimum_r_value` keeps its existing behaviour.
        for zone in ["Zone 4", "Zone 5", "Zone 6", "Zone 7A"] {
            let mut m: HashMap<String, f32> = HashMap::new();
            for assembly in ["wall", "ceiling", "floor", "basement_wall"] {
                m.insert(assembly.into(), sb12_minimum_r(zone, assembly));
            }
            self.thermal_requirements.insert(zone.into(), m);
        }
    }

    // -----------------------------------------------------------------
    // Span lookups
    // -----------------------------------------------------------------

    #[must_use]
    pub fn joist_max_span(
        &self,
        species: &str,
        grade: &str,
        size: &str,
        spacing_inches: i32,
        live_load_psf: f32,
    ) -> Option<f32> {
        let key = make_table_key(species, grade, live_load_psf);
        self.joist_tables
            .get(&key)?
            .find_by_size(size)
            .map(|e| e.span_for_spacing(spacing_inches))
    }

    #[must_use]
    pub fn required_joist_size(
        &self,
        species: &str,
        grade: &str,
        span_ft: f32,
        spacing_inches: i32,
        live_load_psf: f32,
    ) -> Option<String> {
        let key = make_table_key(species, grade, live_load_psf);
        self.joist_tables
            .get(&key)?
            .find_for_span(span_ft, spacing_inches)
            .map(|e| e.size.clone())
    }

    #[must_use]
    pub fn stud_max_height(
        &self,
        size: &str,
        spacing_inches: i32,
        is_load_bearing: bool,
        stories_supported: i32,
    ) -> Option<f32> {
        let table_key = if is_load_bearing {
            "load_bearing_exterior"
        } else {
            "non_load_bearing"
        };
        let entry = self.stud_tables.get(table_key)?.find_by_size(size)?;
        if entry.max_stories_supported < stories_supported {
            return None;
        }
        Some(entry.max_height_for_spacing(spacing_inches))
    }

    #[must_use]
    pub fn required_stud_size(
        &self,
        height_ft: f32,
        spacing_inches: i32,
        is_load_bearing: bool,
        stories_supported: i32,
    ) -> Option<String> {
        let table_key = if is_load_bearing {
            "load_bearing_exterior"
        } else {
            "non_load_bearing"
        };
        self.stud_tables
            .get(table_key)?
            .find_for_height(height_ft, spacing_inches, stories_supported)
            .map(|e| e.size.clone())
    }

    #[must_use]
    pub fn header_max_span(&self, size: &str, stories_supported: i32) -> Option<f32> {
        for entry in &self.header_table {
            if entry.size == size {
                return Some(if stories_supported <= 1 {
                    entry.max_span_1_story
                } else {
                    entry.max_span_2_story
                });
            }
        }
        None
    }

    #[must_use]
    pub fn required_header_size(
        &self,
        opening_width_ft: f32,
        stories_supported: i32,
    ) -> Option<String> {
        for entry in &self.header_table {
            let max_span = if stories_supported <= 1 {
                entry.max_span_1_story
            } else {
                entry.max_span_2_story
            };
            if max_span >= opening_width_ft {
                return Some(entry.size.clone());
            }
        }
        None
    }

    #[must_use]
    pub fn rafter_max_span(
        &self,
        species: &str,
        grade: &str,
        size: &str,
        spacing_inches: i32,
        snow_load_psf: f32,
    ) -> Option<f32> {
        let key = make_table_key(species, grade, snow_load_psf);
        self.rafter_tables
            .get(&key)?
            .find_by_size(size)
            .map(|e| e.span_for_spacing(spacing_inches))
    }

    // -----------------------------------------------------------------
    // Validation
    // -----------------------------------------------------------------

    /// Validate a floor joist against `OBC 9.23.9.2`.
    #[must_use]
    pub fn validate_joist(
        &self,
        species: &str,
        grade: &str,
        size: &str,
        span_ft: f32,
        spacing_inches: i32,
        live_load_psf: f32,
    ) -> ComplianceReport {
        let mut report = ComplianceReport {
            element_type: "joist".into(),
            element_id: format!("{size} @ {spacing_inches}\" o.c."),
            ..Default::default()
        };

        let max_span = self.joist_max_span(species, grade, size, spacing_inches, live_load_psf);

        let mut check = ComplianceCheck {
            rule_name: "Maximum Joist Span".into(),
            code_section: "OBC 9.23.9.2".into(),
            ..Default::default()
        };

        match max_span {
            None => {
                check.status = ComplianceStatus::DataMissing;
                check.message = format!("No span data found for {species} {grade} {size}");
                check.requirement = "N/A".into();
                check.actual = format!("{} ft", cpp_float(span_ft));
            }
            Some(max) if span_ft <= max => {
                check.status = ComplianceStatus::Pass;
                check.requirement = format!("Max span: {} ft", cpp_float(max));
                check.actual = format!("{} ft", cpp_float(span_ft));
                check.message = "Joist span is within allowable limits".into();
            }
            Some(max) => {
                check.status = ComplianceStatus::Fail;
                check.requirement = format!("Max span: {} ft", cpp_float(max));
                check.actual = format!("{} ft", cpp_float(span_ft));
                let deficit = span_ft - max;
                let mut msg = format!(
                    "Joist span exceeds maximum by {} ft. Consider larger size or closer spacing.",
                    cpp_float(deficit)
                );
                if let Some(required) =
                    self.required_joist_size(species, grade, span_ft, spacing_inches, live_load_psf)
                {
                    msg = format!("{msg} Recommended: {required}");
                }
                check.message = msg;
            }
        }

        report.checks.push(check);
        report.compute_overall_status();
        report
    }

    /// Validate wall studs against `OBC 9.23.10.1`.
    #[must_use]
    pub fn validate_studs(
        &self,
        size: &str,
        height_ft: f32,
        spacing_inches: i32,
        is_load_bearing: bool,
        stories_supported: i32,
    ) -> ComplianceReport {
        let suffix = if is_load_bearing {
            " (load-bearing)"
        } else {
            " (non-load-bearing)"
        };
        let mut report = ComplianceReport {
            element_type: "stud".into(),
            element_id: format!("{size}{suffix}"),
            ..Default::default()
        };

        // Height check
        let max_height =
            self.stud_max_height(size, spacing_inches, is_load_bearing, stories_supported);
        let mut height_check = ComplianceCheck {
            rule_name: "Maximum Wall Height".into(),
            code_section: "OBC 9.23.10.1".into(),
            ..Default::default()
        };
        match max_height {
            None => {
                height_check.status = ComplianceStatus::DataMissing;
                height_check.message = format!("No height data found for {size} studs");
                height_check.requirement = "N/A".into();
                height_check.actual = format!("{} ft", cpp_float(height_ft));
            }
            Some(max) if height_ft <= max => {
                height_check.status = ComplianceStatus::Pass;
                height_check.requirement = format!("Max height: {} ft", cpp_float(max));
                height_check.actual = format!("{} ft", cpp_float(height_ft));
                height_check.message = "Wall height is within allowable limits".into();
            }
            Some(max) => {
                height_check.status = ComplianceStatus::Fail;
                height_check.requirement = format!("Max height: {} ft", cpp_float(max));
                height_check.actual = format!("{} ft", cpp_float(height_ft));
                let mut msg = String::from("Wall height exceeds maximum. ");
                if let Some(required) = self.required_stud_size(
                    height_ft,
                    spacing_inches,
                    is_load_bearing,
                    stories_supported,
                ) {
                    msg = format!("{msg}Recommended: {required}");
                }
                height_check.message = msg;
            }
        }
        report.checks.push(height_check);

        // Stories-supported check
        let table_key = if is_load_bearing {
            "load_bearing_exterior"
        } else {
            "non_load_bearing"
        };
        let mut stories_check = ComplianceCheck {
            rule_name: "Stories Supported".into(),
            code_section: "OBC 9.23.10.1".into(),
            requirement: format!("{} stor(ies)", cpp_int(stories_supported)),
            actual: size.into(),
            ..Default::default()
        };
        if let Some(table) = self.stud_tables.get(table_key) {
            if let Some(entry) = table.find_by_size(size) {
                if entry.max_stories_supported >= stories_supported {
                    stories_check.status = ComplianceStatus::Pass;
                    stories_check.message = format!(
                        "{size} can support {} stor(ies)",
                        cpp_int(stories_supported)
                    );
                } else {
                    stories_check.status = ComplianceStatus::Fail;
                    stories_check.message = format!(
                        "{size} cannot support {} stor(ies)",
                        cpp_int(stories_supported)
                    );
                }
            } else {
                stories_check.status = ComplianceStatus::DataMissing;
                stories_check.message = "No stud data available".into();
            }
        } else {
            stories_check.status = ComplianceStatus::DataMissing;
            stories_check.message = "No stud data available".into();
        }
        report.checks.push(stories_check);

        // Stud rollup: fail-only (matches C++ `validateStuds:528`).
        let mut status = ComplianceStatus::Pass;
        for c in &report.checks {
            if c.status == ComplianceStatus::Fail {
                status = ComplianceStatus::Fail;
                break;
            }
        }
        report.overall_status = status;
        report
    }

    /// Validate a header against `OBC 9.23.12.1`.
    #[must_use]
    pub fn validate_header(
        &self,
        size: &str,
        opening_width_ft: f32,
        stories_supported: i32,
    ) -> ComplianceReport {
        let mut report = ComplianceReport {
            element_type: "header".into(),
            element_id: size.into(),
            ..Default::default()
        };

        let max_span = self.header_max_span(size, stories_supported);
        let mut check = ComplianceCheck {
            rule_name: "Maximum Header Span".into(),
            code_section: "OBC 9.23.12.1".into(),
            ..Default::default()
        };
        match max_span {
            None => {
                check.status = ComplianceStatus::DataMissing;
                check.message = format!("No span data found for {size} header");
            }
            Some(max) if opening_width_ft <= max => {
                check.status = ComplianceStatus::Pass;
                check.requirement = format!("Max span: {} ft", cpp_float(max));
                check.actual = format!("{} ft", cpp_float(opening_width_ft));
                check.message = "Header span is within allowable limits".into();
            }
            Some(max) => {
                check.status = ComplianceStatus::Fail;
                check.requirement = format!("Max span: {} ft", cpp_float(max));
                check.actual = format!("{} ft", cpp_float(opening_width_ft));
                check.message = match self.required_header_size(opening_width_ft, stories_supported)
                {
                    Some(required) => format!("Header undersized. Recommended: {required}"),
                    None => {
                        "No standard header size available for this span. Engineering required."
                            .into()
                    }
                };
            }
        }
        let status = check.status;
        report.checks.push(check);
        report.overall_status = status;
        report
    }

    // -----------------------------------------------------------------
    // Thermal compliance
    // -----------------------------------------------------------------

    /// Minimum R-value for a climate zone + assembly type. Falls back to
    /// Zone 6 when the requested zone isn't found (matches C++).
    #[must_use]
    pub fn minimum_r_value(&self, climate_zone: &str, assembly_type: &str) -> f32 {
        let zone = self
            .thermal_requirements
            .get(climate_zone)
            .or_else(|| self.thermal_requirements.get("Zone 6"));
        let Some(zone) = zone else { return 0.0 };
        zone.get(assembly_type).copied().unwrap_or(0.0)
    }

    /// Check an assembly's R-value against the climate-zone requirement.
    /// Status: Pass if ≥ required; Warning if ≥ 90% of required;
    /// Fail otherwise.
    #[must_use]
    pub fn check_thermal_compliance(
        &self,
        assembly_r_value: f32,
        climate_zone: &str,
        assembly_type: &str,
    ) -> ComplianceCheck {
        let required_r = self.minimum_r_value(climate_zone, assembly_type);
        #[allow(clippy::cast_possible_truncation)]
        let required_int = required_r as i32;
        #[allow(clippy::cast_possible_truncation)]
        let actual_int = assembly_r_value as i32;

        let mut check = ComplianceCheck {
            rule_name: "Thermal Performance (R-value)".into(),
            code_section: "OBC SB-12".into(),
            requirement: format!("R-{}", cpp_int(required_int)),
            actual: format!("R-{}", cpp_int(actual_int)),
            ..Default::default()
        };

        if assembly_r_value >= required_r {
            check.status = ComplianceStatus::Pass;
            check.message = format!("Assembly meets thermal requirements for {climate_zone}");
        } else if assembly_r_value >= required_r * 0.9 {
            check.status = ComplianceStatus::Warning;
            check.message =
                "Assembly is marginally below thermal requirements. Consider additional insulation."
                    .into();
        } else {
            check.status = ComplianceStatus::Fail;
            let deficit = required_r - assembly_r_value;
            #[allow(clippy::cast_possible_truncation)]
            let deficit_int = deficit as i32;
            check.message = format!(
                "Assembly is R-{} below minimum. Add insulation.",
                cpp_int(deficit_int)
            );
        }
        check
    }

    /// Validate a wall assembly: thermal check (if exterior) + studs +
    /// any existing constraints attached to the wall type.
    #[must_use]
    pub fn validate_wall_assembly(
        &self,
        wall_type: &WallType,
        wall_height_ft: f32,
        is_exterior: bool,
        climate_zone: &str,
    ) -> ComplianceReport {
        let mut report = ComplianceReport {
            element_type: "wall_assembly".into(),
            element_id: wall_type.name.clone(),
            ..Default::default()
        };

        // Thermal (exterior only)
        if is_exterior {
            let total_r = wall_type.total_r_value();
            report
                .checks
                .push(self.check_thermal_compliance(total_r, climate_zone, "wall"));
        }

        // Structural — first Structure-layer's studs
        for layer in &wall_type.layers {
            if layer.function == LayerFunction::Structure {
                // Extract stud size + spacing from layer name (best effort, matches C++).
                let stud_size = if layer.name.contains("2x4") {
                    "2x4"
                } else if layer.name.contains("2x8") {
                    "2x8"
                } else {
                    "2x6"
                };
                let spacing = if layer.name.contains("24\"") {
                    24
                } else if layer.name.contains("12\"") {
                    12
                } else {
                    16
                };
                let is_load_bearing = wall_type.intent.structural_role == "load_bearing"
                    || wall_type.intent.structural_role == "shear";
                let stud_report =
                    self.validate_studs(stud_size, wall_height_ft, spacing, is_load_bearing, 1);
                report.checks.extend(stud_report.checks);
                break;
            }
        }

        // Existing constraints carried by the WallType
        for constraint in &wall_type.constraints {
            report.checks.push(ComplianceCheck {
                rule_name: constraint.name.clone(),
                code_section: constraint.code_section.clone(),
                requirement: constraint.value.clone(),
                status: if constraint.is_met {
                    ComplianceStatus::Pass
                } else {
                    ComplianceStatus::Fail
                },
                message: constraint.description.clone(),
                actual: String::new(),
            });
        }

        report.compute_overall_status();
        report
    }

    /// Validate every wall type + every floor element in a building.
    /// Matches the simple defaults in C++ `validateBuilding`:
    /// 9 ft wall height, Zone 6, exterior; SPF No.2 2x10 joists @ 16" oc
    /// 40 psf for floors. Floor span uses the diagonal between element
    /// start/end (a known oddity in the C++; preserved for byte-identical).
    #[must_use]
    pub fn validate_building(&self, building: &Building) -> Vec<ComplianceReport> {
        let mut reports = Vec::new();
        for wt in &building.wall_types {
            reports.push(self.validate_wall_assembly(wt, 9.0, true, "Zone 6"));
        }
        for elem in &building.elements {
            if elem.element_type == ElementType::Floor {
                let span = (elem.end - elem.start).length();
                reports.push(self.validate_joist("SPF", "No.2", "2x10", span, 16, 40.0));
            }
        }
        reports
    }
}

#[derive(Debug, Clone, Copy)]
enum TableKind {
    Joists,
    Rafters,
    Studs,
    Headers,
}

/// OBC SB-12 prescriptive minimum effective R-value for an assembly in a
/// climate zone. `assembly_type` is one of `"wall"`, `"ceiling"`, `"floor"`,
/// `"basement_wall"`. Unknown zones fall back to Zone 6 (southern Ontario /
/// GTA); unknown assemblies return 0. Mirrors `obc_engine.cpp:247-275`.
#[must_use]
pub fn sb12_minimum_r(climate_zone: &str, assembly_type: &str) -> f32 {
    // (wall, ceiling, floor, basement_wall)
    let (wall, ceiling, floor, basement) = match climate_zone {
        "Zone 4" => (17.0, 38.0, 28.0, 17.0),
        "Zone 5" => (20.0, 44.0, 28.0, 20.0),
        "Zone 7A" => (27.0, 60.0, 35.0, 24.0),
        // Zone 6 is the default for any unrecognised zone.
        _ => (24.0, 50.0, 31.0, 20.0),
    };
    match assembly_type {
        "wall" => wall,
        "ceiling" => ceiling,
        "floor" => floor,
        "basement_wall" => basement,
        _ => 0.0,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Stand-in engine pre-loaded with a minimal table set, for testing
    /// without filesystem access.
    fn engine_with_minimal_tables() -> OBCEngine {
        let mut e = OBCEngine::new();

        // Joist: SPF No.2 40 psf, 2x10 with realistic spans.
        let key = make_table_key("SPF", "No.2", 40.0);
        let mut table = SpanTable {
            species: "SPF".into(),
            grade: "No.2".into(),
            live_load_psf: 40.0,
            ..Default::default()
        };
        table.entries.push(crate::tables::SpanEntry {
            size: "2x10".into(),
            depth_inches: 9.25,
            span12: 17.0,
            span16: 16.0,
            span24: 13.0,
        });
        e.joist_tables.insert(key, table);

        // Stud: load_bearing_exterior 2x6.
        let mut stud_table = StudTable {
            category: "load_bearing_exterior".into(),
            ..Default::default()
        };
        stud_table.entries.push(crate::tables::StudEntry {
            size: "2x6".into(),
            depth_inches: 5.5,
            max_height12: 14.0,
            max_height16: 12.0,
            max_height24: 10.0,
            max_stories_supported: 2,
            notes: String::new(),
        });
        e.stud_tables
            .insert("load_bearing_exterior".into(), stud_table);

        // Header: 2-2x10 with realistic spans.
        e.header_table.push(HeaderEntry {
            size: "2-2x10".into(),
            depth_inches: 9.25,
            max_span_1_story: 9.0,
            max_span_2_story: 6.0,
            support_type: "roof_ceiling_only".into(),
        });

        e
    }

    #[test]
    fn thermal_requirements_zone_6_wall() {
        let e = OBCEngine::new();
        assert_eq!(e.minimum_r_value("Zone 6", "wall"), 24.0);
        assert_eq!(e.minimum_r_value("Zone 6", "ceiling"), 50.0);
    }

    #[test]
    fn thermal_unknown_zone_falls_back_to_zone_6() {
        let e = OBCEngine::new();
        assert_eq!(e.minimum_r_value("Zone 99", "wall"), 24.0);
    }

    #[test]
    fn joist_max_span_lookup() {
        let e = engine_with_minimal_tables();
        // 2x10 SPF No.2 @ 16" oc → 16 ft.
        assert_eq!(
            e.joist_max_span("SPF", "No.2", "2x10", 16, 40.0),
            Some(16.0)
        );
    }

    #[test]
    fn validate_joist_passes_within_span() {
        let e = engine_with_minimal_tables();
        let r = e.validate_joist("SPF", "No.2", "2x10", 14.0, 16, 40.0);
        assert_eq!(r.overall_status, ComplianceStatus::Pass);
        assert_eq!(r.checks.len(), 1);
        assert_eq!(r.checks[0].status, ComplianceStatus::Pass);
    }

    #[test]
    fn validate_joist_fails_over_span_and_suggests_size() {
        let e = engine_with_minimal_tables();
        // Span 20 ft, 2x10 max 16 → fails.
        let r = e.validate_joist("SPF", "No.2", "2x10", 20.0, 16, 40.0);
        assert_eq!(r.overall_status, ComplianceStatus::Fail);
        // Message contains 6-decimal cpp_float formatting.
        assert!(r.checks[0].requirement.contains("16.000000 ft"));
        assert!(r.checks[0].actual.contains("20.000000 ft"));
    }

    #[test]
    fn validate_joist_data_missing_for_unknown_species() {
        let e = engine_with_minimal_tables();
        let r = e.validate_joist("Cedar", "Premium", "2x10", 10.0, 16, 40.0);
        assert_eq!(r.checks[0].status, ComplianceStatus::DataMissing);
        assert_eq!(r.checks[0].requirement, "N/A");
    }

    #[test]
    fn validate_studs_emits_height_and_stories_checks() {
        let e = engine_with_minimal_tables();
        let r = e.validate_studs("2x6", 10.0, 16, true, 1);
        assert_eq!(r.checks.len(), 2);
        assert_eq!(r.checks[0].rule_name, "Maximum Wall Height");
        assert_eq!(r.checks[1].rule_name, "Stories Supported");
        assert_eq!(r.overall_status, ComplianceStatus::Pass);
    }

    #[test]
    fn validate_header_fails_for_wide_opening() {
        let e = engine_with_minimal_tables();
        // 2-2x10 max 1-story span = 9 ft. 12-ft opening fails.
        let r = e.validate_header("2-2x10", 12.0, 1);
        assert_eq!(r.overall_status, ComplianceStatus::Fail);
        assert!(
            r.checks[0].message.contains("Engineering required")
                || r.checks[0].message.contains("undersized")
        );
    }

    #[test]
    fn check_thermal_compliance_pass_warning_fail_buckets() {
        let e = OBCEngine::new();
        // Zone 6 wall requires R-24.
        let pass = e.check_thermal_compliance(25.0, "Zone 6", "wall");
        assert_eq!(pass.status, ComplianceStatus::Pass);

        // 22 / 24 = 0.917 > 0.9 → Warning.
        let warning = e.check_thermal_compliance(22.0, "Zone 6", "wall");
        assert_eq!(warning.status, ComplianceStatus::Warning);

        // 10 / 24 < 0.9 → Fail.
        let fail = e.check_thermal_compliance(10.0, "Zone 6", "wall");
        assert_eq!(fail.status, ComplianceStatus::Fail);
        // Integer truncation of deficit: R-24 - R-10 = R-14.
        assert!(fail.message.contains("R-14"));
    }
}
