//! Schema-bound schedule-entry builders.
//!
//! Pure rendering lives in `drawing::schedule`; this module bridges the
//! `archgeometry::SchemaDocument` shape to `drawing::ScheduleEntry`.
//!
//! Reads top-level `doors` / `windows` arrays (the canonical qbd
//! schema), not the bugged `wall.openings` path the Python
//! `extract_openings` uses.

use std::collections::HashMap;

use archgeometry::SchemaDocument;
use drawing::{ScheduleEntry, door_type_for_width, window_type_for_width};

/// `"Living - Kitchen"` if both rooms known; one-sided if only one;
/// `"Wall <idx>"` fallback when neither is set. Matches the Python
/// `wall_rooms` join (`generate_schedules.py:42-48`).
fn location_for(
    wall_idx: i32,
    room1: &str,
    room2: &str,
    room_names: &HashMap<String, String>,
) -> String {
    let lookup = |id: &str| -> Option<String> {
        if id.is_empty() {
            None
        } else {
            Some(
                room_names
                    .get(id)
                    .cloned()
                    .unwrap_or_else(|| id.to_string()),
            )
        }
    };
    match (lookup(room1), lookup(room2)) {
        (Some(r1), Some(r2)) => format!("{r1} - {r2}"),
        (Some(r), None) | (None, Some(r)) => r,
        (None, None) => format!("Wall {wall_idx}"),
    }
}

fn room_name_map(doc: &SchemaDocument) -> HashMap<String, String> {
    doc.rooms
        .iter()
        .map(|(id, r)| {
            let name = if r.name.is_empty() {
                id.clone()
            } else {
                r.name.clone()
            };
            (id.clone(), name)
        })
        .collect()
}

/// One row per door, in document order. Mark codes `D1, D2, ...`.
#[must_use]
pub fn door_entries(doc: &SchemaDocument) -> Vec<ScheduleEntry> {
    let names = room_name_map(doc);
    doc.doors
        .iter()
        .enumerate()
        .map(|(i, d)| ScheduleEntry {
            mark: format!("D{}", i + 1),
            qty: 1,
            width_mm: d.width,
            height_mm: d.height,
            type_name: door_type_for_width(d.width).to_string(),
            location: location_for(d.wall_index, &d.room1, &d.room2, &names),
            remarks: String::new(),
        })
        .collect()
}

/// One row per window. Mark codes `W1, W2, ...`. Remarks carry the sill
/// height (Python convention).
#[must_use]
pub fn window_entries(doc: &SchemaDocument) -> Vec<ScheduleEntry> {
    let names = room_name_map(doc);
    doc.windows
        .iter()
        .enumerate()
        .map(|(i, w)| {
            #[allow(clippy::cast_possible_truncation)]
            let sill = w.sill_height as i32;
            ScheduleEntry {
                mark: format!("W{}", i + 1),
                qty: 1,
                width_mm: w.width,
                height_mm: w.height,
                type_name: window_type_for_width(w.width).to_string(),
                location: location_for(w.wall_index, &w.room, "", &names),
                remarks: format!("Sill {sill}mm"),
            }
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use archgeometry::{SchemaDoor, SchemaWindow};

    fn doc_with(doors: Vec<SchemaDoor>, windows: Vec<SchemaWindow>) -> SchemaDocument {
        SchemaDocument {
            doors,
            windows,
            ..Default::default()
        }
    }

    #[test]
    fn door_entries_label_by_width() {
        let doc = doc_with(
            vec![
                SchemaDoor {
                    wall_index: 0,
                    width: 800.0,
                    height: 2100.0,
                    ..Default::default()
                },
                SchemaDoor {
                    wall_index: 1,
                    width: 1500.0,
                    height: 2100.0,
                    ..Default::default()
                },
                SchemaDoor {
                    wall_index: 2,
                    width: 2200.0,
                    height: 2100.0,
                    ..Default::default()
                },
            ],
            vec![],
        );
        let rows = door_entries(&doc);
        assert_eq!(rows.len(), 3);
        assert_eq!(rows[0].mark, "D1");
        assert_eq!(rows[0].type_name, "Single Door");
        assert_eq!(rows[1].type_name, "Double Door");
        assert_eq!(rows[2].type_name, "Sliding Door");
    }

    #[test]
    fn window_entries_label_by_width_and_carry_sill() {
        let doc = doc_with(
            vec![],
            vec![
                SchemaWindow {
                    wall_index: 0,
                    width: 600.0,
                    sill_height: 1100.0,
                    ..Default::default()
                },
                SchemaWindow {
                    wall_index: 1,
                    width: 1000.0,
                    sill_height: 900.0,
                    ..Default::default()
                },
                SchemaWindow {
                    wall_index: 2,
                    width: 1800.0,
                    sill_height: 600.0,
                    ..Default::default()
                },
            ],
        );
        let rows = window_entries(&doc);
        assert_eq!(rows[0].type_name, "Casement");
        assert_eq!(rows[1].type_name, "Double Hung");
        assert_eq!(rows[2].type_name, "Picture Window");
        assert_eq!(rows[0].remarks, "Sill 1100mm");
    }

    #[test]
    fn empty_doc_produces_empty_entries() {
        let doc = SchemaDocument::default();
        assert!(door_entries(&doc).is_empty());
        assert!(window_entries(&doc).is_empty());
    }

    #[test]
    fn missing_room_info_falls_back_to_wall_index() {
        let doc = doc_with(
            vec![SchemaDoor {
                wall_index: 7,
                width: 900.0,
                ..Default::default()
            }],
            vec![],
        );
        assert_eq!(door_entries(&doc)[0].location, "Wall 7");
    }
}
