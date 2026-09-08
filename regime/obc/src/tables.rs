//! Span / stud / header table types + JSON loaders.
//!
//! Ported from `obc_engine.hpp:58-160` (types) and `obc_engine.cpp:99-245`
//! (loaders). JSON shapes documented at `OBC_Library/tables/*.json`.

use serde::Deserialize;

/// Floor joist or rafter span entry.
#[derive(Debug, Clone, PartialEq, Default)]
pub struct SpanEntry {
    /// `"2x6"`, `"2x8"`, etc.
    pub size: String,
    pub depth_inches: f32,
    /// Max span at 12" o.c. (in feet).
    pub span12: f32,
    /// Max span at 16" o.c.
    pub span16: f32,
    /// Max span at 24" o.c.
    pub span24: f32,
}

impl SpanEntry {
    /// Max span for the given spacing. Bucketed at 12 / 16 / 24 inches —
    /// anything in between is rounded UP to the next bucket (per the C++).
    #[must_use]
    pub fn span_for_spacing(&self, spacing_inches: i32) -> f32 {
        if spacing_inches <= 12 {
            self.span12
        } else if spacing_inches <= 16 {
            self.span16
        } else {
            self.span24
        }
    }
}

/// Stud height entry.
#[derive(Debug, Clone, PartialEq, Default)]
pub struct StudEntry {
    pub size: String,
    pub depth_inches: f32,
    /// 0.0 = no data for this spacing.
    pub max_height12: f32,
    pub max_height16: f32,
    pub max_height24: f32,
    /// 1 = single story only.
    pub max_stories_supported: i32,
    pub notes: String,
}

impl StudEntry {
    #[must_use]
    pub fn max_height_for_spacing(&self, spacing_inches: i32) -> f32 {
        if spacing_inches <= 12 {
            self.max_height12
        } else if spacing_inches <= 16 {
            self.max_height16
        } else {
            self.max_height24
        }
    }
}

/// Header / lintel sizing entry.
#[derive(Debug, Clone, PartialEq, Default)]
pub struct HeaderEntry {
    /// Plies-prefixed (e.g. `"2-2x6"`) — the C++ default builds double-ply.
    pub size: String,
    pub depth_inches: f32,
    /// Max opening span supporting 1 story (roof only).
    pub max_span_1_story: f32,
    /// Max opening span supporting 2 stories (roof + one floor).
    pub max_span_2_story: f32,
    /// `"roof_ceiling_only"`, `"one_floor_roof_ceiling"`, …
    pub support_type: String,
}

/// Container for joist (or rafter) tables keyed by species+grade+load.
#[derive(Debug, Clone, PartialEq, Default)]
pub struct SpanTable {
    pub species: String,
    pub grade: String,
    pub live_load_psf: f32,
    pub entries: Vec<SpanEntry>,
}

impl SpanTable {
    /// First entry whose `size` matches, or `None`.
    #[must_use]
    pub fn find_by_size(&self, size: &str) -> Option<&SpanEntry> {
        self.entries.iter().find(|e| e.size == size)
    }

    /// Smallest entry whose span at the given spacing meets `required_span_ft`.
    /// Iterates in array order (matches the C++).
    #[must_use]
    pub fn find_for_span(&self, required_span_ft: f32, spacing_inches: i32) -> Option<&SpanEntry> {
        self.entries
            .iter()
            .find(|e| e.span_for_spacing(spacing_inches) >= required_span_ft)
    }
}

/// Container for stud tables keyed by category (load_bearing_exterior / non_load_bearing).
#[derive(Debug, Clone, PartialEq, Default)]
pub struct StudTable {
    pub category: String,
    pub entries: Vec<StudEntry>,
}

impl StudTable {
    #[must_use]
    pub fn find_by_size(&self, size: &str) -> Option<&StudEntry> {
        self.entries.iter().find(|e| e.size == size)
    }

    /// Smallest entry that supports the given height + stories at this spacing.
    /// Matches `StudTable::findForHeight` in C++.
    #[must_use]
    pub fn find_for_height(
        &self,
        height_ft: f32,
        spacing_inches: i32,
        stories_supported: i32,
    ) -> Option<&StudEntry> {
        self.entries.iter().find(|e| {
            e.max_height_for_spacing(spacing_inches) >= height_ft
                && e.max_stories_supported >= stories_supported
        })
    }
}

// ---------------------------------------------------------------------------
// Span-string parsing
// ---------------------------------------------------------------------------

/// Parse `"10-6"` (feet-inches) → 10.5 decimal feet. A plain `"12.0"` is
/// also accepted as already-decimal-feet. Matches `OBCEngine::parseSpanString`.
#[must_use]
pub fn parse_span_string(span: &str) -> f32 {
    if let Some(dash_pos) = span.find('-') {
        let feet: i32 = span[..dash_pos].parse().unwrap_or(0);
        let inches: i32 = span[dash_pos + 1..].parse().unwrap_or(0);
        #[allow(clippy::cast_precision_loss)]
        return feet as f32 + (inches as f32) / 12.0;
    }
    span.parse::<f32>().unwrap_or(0.0)
}

// ---------------------------------------------------------------------------
// JSON loaders
// ---------------------------------------------------------------------------

/// Wire format for one entry inside a joist or rafter table. All span
/// fields are strings like `"10-6"`.
#[derive(Debug, Deserialize)]
struct WireJoistEntry {
    size: String,
    depth_in: f32,
    spacing_12_span: String,
    spacing_16_span: String,
    spacing_24_span: String,
}

#[derive(Debug, Deserialize)]
struct WireJoistTable {
    species: String,
    grade: String,
    #[serde(default)]
    live_load_psf: f32,
    #[serde(default)]
    snow_load_psf: f32,
    entries: Vec<WireJoistEntry>,
}

#[derive(Debug, Deserialize)]
struct WireFile<T> {
    tables: std::collections::HashMap<String, T>,
}

#[derive(Debug, Deserialize)]
struct WireStudEntry {
    size: String,
    depth_in: f32,
    #[serde(default)]
    spacing_12_max_height_ft: f32,
    #[serde(default)]
    spacing_16_max_height_ft: f32,
    #[serde(default)]
    spacing_24_max_height_ft: f32,
    #[serde(default = "default_stories")]
    max_stories_supported: i32,
    #[serde(default)]
    notes: String,
}

fn default_stories() -> i32 {
    1
}

#[derive(Debug, Deserialize)]
struct WireStudTable {
    entries: Vec<WireStudEntry>,
}

#[derive(Debug, Deserialize)]
struct WireHeaderEntry {
    size: String,
    depth_in: f32,
    double_ply_span_ft: f32,
}

#[derive(Debug, Deserialize)]
struct WireHeaderTable {
    entries: Vec<WireHeaderEntry>,
}

#[derive(Debug, Deserialize)]
struct WireHeaderFile {
    tables: HeaderTables,
}

#[derive(Debug, Deserialize)]
struct HeaderTables {
    roof_ceiling_only: Option<WireHeaderTable>,
    one_floor_roof_ceiling: Option<WireHeaderTable>,
}

/// Parse a joist-table file and return entries keyed by `species_grade_load`.
pub fn load_joist_tables_from_json(
    json_str: &str,
) -> Result<Vec<(String, SpanTable)>, serde_json::Error> {
    let wire: WireFile<WireJoistTable> = serde_json::from_str(json_str)?;
    let mut out = Vec::with_capacity(wire.tables.len());
    for (_table_key, table_data) in wire.tables {
        let load = if table_data.live_load_psf > 0.0 {
            table_data.live_load_psf
        } else {
            table_data.snow_load_psf
        };
        let key = make_table_key(&table_data.species, &table_data.grade, load);
        let entries = table_data
            .entries
            .into_iter()
            .map(|e| SpanEntry {
                size: e.size,
                depth_inches: e.depth_in,
                span12: parse_span_string(&e.spacing_12_span),
                span16: parse_span_string(&e.spacing_16_span),
                span24: parse_span_string(&e.spacing_24_span),
            })
            .collect();
        out.push((
            key,
            SpanTable {
                species: table_data.species,
                grade: table_data.grade,
                live_load_psf: load,
                entries,
            },
        ));
    }
    Ok(out)
}

/// Parse a rafter-table file. Same shape as joist tables — defaults to
/// 40 psf when `snow_load_psf` is missing (matches C++ `obc_engine.cpp:223`).
pub fn load_rafter_tables_from_json(
    json_str: &str,
) -> Result<Vec<(String, SpanTable)>, serde_json::Error> {
    let wire: WireFile<WireJoistTable> = serde_json::from_str(json_str)?;
    let mut out = Vec::with_capacity(wire.tables.len());
    for (_, table_data) in wire.tables {
        let load = if table_data.snow_load_psf > 0.0 {
            table_data.snow_load_psf
        } else if table_data.live_load_psf > 0.0 {
            table_data.live_load_psf
        } else {
            40.0
        };
        let key = make_table_key(&table_data.species, &table_data.grade, load);
        let entries = table_data
            .entries
            .into_iter()
            .map(|e| SpanEntry {
                size: e.size,
                depth_inches: e.depth_in,
                span12: parse_span_string(&e.spacing_12_span),
                span16: parse_span_string(&e.spacing_16_span),
                span24: parse_span_string(&e.spacing_24_span),
            })
            .collect();
        out.push((
            key,
            SpanTable {
                species: table_data.species,
                grade: table_data.grade,
                live_load_psf: load,
                entries,
            },
        ));
    }
    Ok(out)
}

/// Parse a stud-table file. Returns entries keyed by category (the table key in JSON).
pub fn load_stud_tables_from_json(
    json_str: &str,
) -> Result<Vec<(String, StudTable)>, serde_json::Error> {
    let wire: WireFile<WireStudTable> = serde_json::from_str(json_str)?;
    let mut out = Vec::with_capacity(wire.tables.len());
    for (table_key, table_data) in wire.tables {
        let entries = table_data
            .entries
            .into_iter()
            .map(|e| StudEntry {
                size: e.size,
                depth_inches: e.depth_in,
                max_height12: e.spacing_12_max_height_ft,
                max_height16: e.spacing_16_max_height_ft,
                max_height24: e.spacing_24_max_height_ft,
                max_stories_supported: e.max_stories_supported,
                notes: e.notes,
            })
            .collect();
        out.push((
            table_key.clone(),
            StudTable {
                category: table_key,
                entries,
            },
        ));
    }
    Ok(out)
}

/// Parse a header-table file. Returns a flat list of HeaderEntry (the
/// C++ stores them in `m_headerTable` as a Vec, not a map). Matches the
/// C++ join logic: each entry from `roof_ceiling_only` is paired with
/// the same-size entry from `one_floor_roof_ceiling` (if any) to fill
/// in `max_span_2_story`.
pub fn load_header_tables_from_json(json_str: &str) -> Result<Vec<HeaderEntry>, serde_json::Error> {
    let wire: WireHeaderFile = serde_json::from_str(json_str)?;
    let Some(roof_only) = wire.tables.roof_ceiling_only else {
        return Ok(Vec::new());
    };
    let two_story = wire.tables.one_floor_roof_ceiling;
    let mut out = Vec::with_capacity(roof_only.entries.len());
    for entry in roof_only.entries {
        let two_story_span = two_story
            .as_ref()
            .and_then(|t| t.entries.iter().find(|e| e.size == entry.size))
            .map_or(0.0, |e| e.double_ply_span_ft);
        out.push(HeaderEntry {
            size: format!("2-{}", entry.size), // double-ply default per C++
            depth_inches: entry.depth_in,
            max_span_1_story: entry.double_ply_span_ft,
            max_span_2_story: two_story_span,
            support_type: "roof_ceiling_only".to_string(),
        });
    }
    Ok(out)
}

/// `species_grade_load` key used for indexing joist/rafter tables.
/// Truncates load to int — matches `OBCEngine::makeTableKey`.
#[must_use]
pub fn make_table_key(species: &str, grade: &str, load: f32) -> String {
    #[allow(clippy::cast_possible_truncation)]
    let load_int = load as i32;
    format!("{species}_{grade}_{load_int}")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_span_string_decimal_feet() {
        assert!((parse_span_string("10-6") - 10.5).abs() < 1e-6);
        assert!((parse_span_string("21-6") - 21.5).abs() < 1e-6);
        assert!((parse_span_string("7-10") - (7.0 + 10.0 / 12.0)).abs() < 1e-6);
        assert!((parse_span_string("12.0") - 12.0).abs() < 1e-6);
    }

    #[test]
    fn span_entry_bucketing() {
        let e = SpanEntry {
            size: "2x10".into(),
            depth_inches: 9.25,
            span12: 17.0,
            span16: 16.0,
            span24: 13.0,
        };
        assert_eq!(e.span_for_spacing(12), 17.0);
        assert_eq!(e.span_for_spacing(13), 16.0); // > 12 → next bucket
        assert_eq!(e.span_for_spacing(16), 16.0);
        assert_eq!(e.span_for_spacing(20), 13.0); // > 16 → 24-bucket
        assert_eq!(e.span_for_spacing(100), 13.0);
    }

    #[test]
    fn stud_entry_bucketing() {
        let e = StudEntry {
            size: "2x6".into(),
            max_height12: 14.0,
            max_height16: 12.0,
            max_height24: 10.0,
            ..Default::default()
        };
        assert_eq!(e.max_height_for_spacing(12), 14.0);
        assert_eq!(e.max_height_for_spacing(16), 12.0);
        assert_eq!(e.max_height_for_spacing(24), 10.0);
    }

    #[test]
    fn span_table_find_for_span_returns_first_fit() {
        let t = SpanTable {
            entries: vec![
                SpanEntry {
                    size: "2x6".into(),
                    span16: 9.5,
                    ..Default::default()
                },
                SpanEntry {
                    size: "2x8".into(),
                    span16: 12.5,
                    ..Default::default()
                },
                SpanEntry {
                    size: "2x10".into(),
                    span16: 16.0,
                    ..Default::default()
                },
            ],
            ..Default::default()
        };
        // 10 ft span @ 16" → 2x8 is first fit.
        assert_eq!(t.find_for_span(10.0, 16).unwrap().size, "2x8");
        // 8 ft span → 2x6 fits.
        assert_eq!(t.find_for_span(8.0, 16).unwrap().size, "2x6");
        // 17 ft span → nothing fits.
        assert!(t.find_for_span(17.0, 16).is_none());
    }

    #[test]
    fn stud_table_find_for_height_checks_stories() {
        let t = StudTable {
            entries: vec![
                StudEntry {
                    size: "2x4".into(),
                    max_height16: 10.0,
                    max_stories_supported: 1,
                    ..Default::default()
                },
                StudEntry {
                    size: "2x6".into(),
                    max_height16: 12.0,
                    max_stories_supported: 2,
                    ..Default::default()
                },
            ],
            ..Default::default()
        };
        // 9 ft, 16" oc, 1 story → 2x4 fits.
        assert_eq!(t.find_for_height(9.0, 16, 1).unwrap().size, "2x4");
        // 9 ft, 16" oc, 2 stories → 2x4 fails stories, 2x6 wins.
        assert_eq!(t.find_for_height(9.0, 16, 2).unwrap().size, "2x6");
    }

    #[test]
    fn make_table_key_truncates_load() {
        assert_eq!(make_table_key("SPF", "No.2", 40.0), "SPF_No.2_40");
        assert_eq!(make_table_key("SPF", "No.2", 40.7), "SPF_No.2_40");
    }
}
