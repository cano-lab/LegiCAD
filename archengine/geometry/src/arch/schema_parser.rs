//! JSON → `SchemaDocument` parsing.
//!
//! Port of `Shared/ArchGeometry/{include,src}/archgeometry/schema_parser.{hpp,cpp}`.
//! The C++ implementation is ~442 LOC of manual `nlohmann::json` access;
//! serde collapses it to a single derive — see `schema_types.rs`.

use crate::arch::schema_types::SchemaDocument;
use std::path::Path;

/// Errors returned by the parser.
#[derive(Debug, thiserror::Error)]
pub enum ParseError {
    #[error("failed to read file {path}: {source}")]
    Io {
        path: String,
        #[source]
        source: std::io::Error,
    },

    #[error("failed to parse JSON: {0}")]
    Json(#[from] serde_json::Error),
}

/// Parse a JSON string into a `SchemaDocument`.
pub fn parse_json(json: &str) -> Result<SchemaDocument, ParseError> {
    Ok(serde_json::from_str(json)?)
}

/// Parse a JSON file at `path` into a `SchemaDocument`.
pub fn parse_file(path: impl AsRef<Path>) -> Result<SchemaDocument, ParseError> {
    let path = path.as_ref();
    let bytes = std::fs::read(path).map_err(|source| ParseError::Io {
        path: path.display().to_string(),
        source,
    })?;
    Ok(serde_json::from_slice(&bytes)?)
}

#[cfg(test)]
mod tests {
    use super::*;
    use glam::Vec3;

    #[test]
    fn parses_minimal_schema_string() {
        let json = r#"{
            "version": "1.0.0",
            "building_id": "test",
            "unit": "mm",
            "width": 10000,
            "depth": 8000,
            "walls_batch": [
                {
                    "start": [0, 0, 0],
                    "end": [5000, 0, 0],
                    "height": 2700,
                    "wall_type": "exterior_2x6",
                    "category": "exterior"
                }
            ]
        }"#;
        let doc = parse_json(json).unwrap();
        assert_eq!(doc.version, "1.0.0");
        assert_eq!(doc.building_id, "test");
        assert_eq!(doc.width, 10000.0);
        assert_eq!(doc.depth, 8000.0);
        assert_eq!(doc.walls.len(), 1);
        assert_eq!(doc.walls[0].end, Vec3::new(5000.0, 0.0, 0.0));
    }

    #[test]
    fn rejects_malformed_json() {
        let err = parse_json("{ not valid json").unwrap_err();
        assert!(matches!(err, ParseError::Json(_)));
    }
}
