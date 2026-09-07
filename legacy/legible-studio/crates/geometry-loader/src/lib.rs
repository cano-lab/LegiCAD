//! Legacy kernel `Building` JSON loader.
//!
//! Port of `ArchEngine_kernel/{include,src}/geometry_loader.{hpp,cpp}`.
//!
//! Scope:
//! - **In:** `parse_file` / `parse_json` for the kernel's
//!   `{name, units, elements:[{type, start, end, width, depth, material}]}`
//!   wire format. Supports both string (`"wall"`) and integer (`3`) type
//!   tags — the C++ uses int via `static_cast<ElementType>(e.value("type", 0))`
//!   but `test_building.json` uses strings, so both are accepted.
//! - **Out (deferred):** sample builders (`createSimpleFrame` etc.) —
//!   these construct programmatic test scenes, not used by the permit-
//!   drawing pipeline. IFC import — calls Python externally. Material
//!   override loading — renderer-only concern.

use domain::{Building, ElementType, MeshData, StructuralElement};
use glam::Vec3;
use serde::Deserialize;
use std::path::Path;

/// Errors returned by the loader.
#[derive(Debug, thiserror::Error)]
pub enum LoadError {
    #[error("failed to read file {path}: {source}")]
    Io {
        path: String,
        #[source]
        source: std::io::Error,
    },

    #[error("failed to parse JSON: {0}")]
    Json(#[from] serde_json::Error),
}

/// Wire-format element. Mirrors the JSON object shape directly.
///
/// `type` is the string-or-int variant (see `TypeField` below). Most
/// other fields have defaults matching `geometry_loader.cpp:590`.
#[derive(Debug, Deserialize)]
struct WireElement {
    #[serde(rename = "type")]
    type_field: TypeField,

    #[serde(default)]
    start: [f32; 3],
    #[serde(default)]
    end: [f32; 3],
    #[serde(default = "default_width")]
    width: f32,
    #[serde(default = "default_depth")]
    depth: f32,
    #[serde(default = "default_material")]
    material: String,
    #[serde(default)]
    stress: f32,
    #[serde(default)]
    deflection: f32,
    #[serde(default)]
    failed: bool,

    #[serde(default)]
    mesh: Option<WireMeshData>,

    /// Per-element rotation (radians). The C++ uses `-1000.0` as a
    /// "not set" sentinel; we preserve it for byte-compat.
    #[serde(default = "default_rotation")]
    rotation: f32,
}

fn default_width() -> f32 {
    0.5
}
fn default_depth() -> f32 {
    0.5
}
fn default_material() -> String {
    "steel".to_string()
}
fn default_rotation() -> f32 {
    domain::ROTATION_UNSET
}

#[derive(Debug, Deserialize)]
struct WireMeshData {
    #[serde(default)]
    vertices: Vec<[f32; 3]>,
    #[serde(default)]
    faces: Vec<[u32; 3]>,
}

/// JSON wire-format element-type tag. The kernel writes either an int
/// (`ElementType` enum value, 0-8) or a string (`"wall"`, `"slab"`,
/// etc.). Both are accepted on the read path.
#[derive(Debug, Deserialize)]
#[serde(untagged)]
enum TypeField {
    Str(String),
    Int(u32),
}

impl TypeField {
    // The two match arms below have `_ => Beam` duplicated by design: the
    // C++ enum cast falls back to whatever `ElementType(0)` is for *both*
    // unknown strings and out-of-range ints, and `Beam = 0`. Suppressing
    // match_same_arms keeps the explicit "unknown → default" case.
    #[allow(clippy::match_same_arms)]
    fn to_element_type(&self) -> ElementType {
        match self {
            TypeField::Str(s) => match s.as_str() {
                "beam" => ElementType::Beam,
                "column" => ElementType::Column,
                "floor" | "slab" => ElementType::Floor, // legacy "slab" alias
                "wall" => ElementType::Wall,
                "foundation" => ElementType::Foundation,
                "connection" => ElementType::Connection,
                "door" => ElementType::Door,
                "window" => ElementType::Window,
                "roof" => ElementType::Roof,
                // Unknown strings fall back to Wall (matches the
                // `static_cast<ElementType>(0)` default-on-failure
                // behaviour of the C++ enum int cast).
                _ => ElementType::Beam,
            },
            TypeField::Int(n) => match n {
                0 => ElementType::Beam,
                1 => ElementType::Column,
                2 => ElementType::Floor,
                3 => ElementType::Wall,
                4 => ElementType::Foundation,
                5 => ElementType::Connection,
                6 => ElementType::Door,
                7 => ElementType::Window,
                8 => ElementType::Roof,
                _ => ElementType::Beam,
            },
        }
    }
}

/// Wire-format top-level document.
#[derive(Debug, Deserialize, Default)]
struct WireBuilding {
    #[serde(default)]
    name: String,
    // Consumed by serde to absorb the field — never read by the loader.
    // The kernel format requires it; without it serde would happily
    // deserialize but downstream re-emitters would lose the value.
    #[allow(dead_code)]
    #[serde(default = "default_units")]
    units: String,
    #[serde(default)]
    elements: Vec<WireElement>,
    // wallTypes / parametricWalls / terrain_mesh sections exist in the
    // kernel format but only the legacy-fixture test corpus uses
    // `elements`. Skip the other arrays for now — they can be added if
    // a real consumer needs them.
}

fn default_units() -> String {
    "mm".to_string()
}

fn wire_to_element(w: WireElement) -> StructuralElement {
    let mesh = w
        .mesh
        .map(|m| MeshData {
            vertices: m
                .vertices
                .into_iter()
                .map(|v| Vec3::new(v[0], v[1], v[2]))
                .collect(),
            faces: m.faces,
        })
        .unwrap_or_default();

    StructuralElement {
        element_type: w.type_field.to_element_type(),
        start: Vec3::new(w.start[0], w.start[1], w.start[2]),
        end: Vec3::new(w.end[0], w.end[1], w.end[2]),
        width: w.width,
        depth: w.depth,
        material: w.material,
        stress: w.stress,
        deflection: w.deflection,
        failed: w.failed,
        mesh,
        rotation: w.rotation,
    }
}

/// Parse the kernel-format JSON string. Empty / malformed `elements`
/// arrays yield an empty `Building`.
pub fn parse_json(s: &str) -> Result<Building, LoadError> {
    let wire: WireBuilding = serde_json::from_str(s)?;
    Ok(Building {
        name: wire.name,
        elements: wire.elements.into_iter().map(wire_to_element).collect(),
        ..Default::default()
    })
}

/// Parse the kernel-format JSON file.
pub fn parse_file(path: impl AsRef<Path>) -> Result<Building, LoadError> {
    let path = path.as_ref();
    let bytes = std::fs::read(path).map_err(|source| LoadError::Io {
        path: path.display().to_string(),
        source,
    })?;
    let wire: WireBuilding = serde_json::from_slice(&bytes)?;
    Ok(Building {
        name: wire.name,
        elements: wire.elements.into_iter().map(wire_to_element).collect(),
        ..Default::default()
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_minimal_building_with_string_types() {
        let json = r#"{
            "name": "Test",
            "units": "mm",
            "elements": [
                {"type": "wall", "start": [0, 0, 0], "end": [9144, 0, 0],
                 "width": 152, "material": "brick"},
                {"type": "slab", "start": [0, 0, 0], "end": [9144, 0, 12192],
                 "width": 9144, "material": "concrete"}
            ]
        }"#;
        let b = parse_json(json).unwrap();
        assert_eq!(b.name, "Test");
        assert_eq!(b.elements.len(), 2);
        assert_eq!(b.elements[0].element_type, ElementType::Wall);
        assert_eq!(b.elements[1].element_type, ElementType::Floor); // "slab" → Floor
        assert_eq!(b.elements[0].material, "brick");
    }

    #[test]
    fn parse_with_int_type_tags() {
        // Some kernel writers emit `type` as the enum int value.
        let json = r#"{
            "name": "IntTypes",
            "elements": [
                {"type": 3, "start": [0, 0, 0], "end": [5000, 0, 0], "width": 150},
                {"type": 1, "start": [0, 0, 0], "end": [0, 3000, 0], "width": 300}
            ]
        }"#;
        let b = parse_json(json).unwrap();
        assert_eq!(b.elements[0].element_type, ElementType::Wall);
        assert_eq!(b.elements[1].element_type, ElementType::Column);
    }

    #[test]
    fn defaults_match_cpp_when_fields_omitted() {
        let json = r#"{"elements": [{"type": "wall", "start": [0,0,0], "end": [1,0,0]}]}"#;
        let b = parse_json(json).unwrap();
        let e = &b.elements[0];
        // Width / depth default to 0.5 per `geometry_loader.cpp:590-591`.
        assert!((e.width - 0.5).abs() < 1e-6);
        assert!((e.depth - 0.5).abs() < 1e-6);
        // Material defaults to "steel".
        assert_eq!(e.material, "steel");
    }

    #[test]
    fn rotation_defaults_to_unset_sentinel() {
        let json = r#"{"elements": [{"type": "wall", "start": [0,0,0], "end": [1,0,0]}]}"#;
        let b = parse_json(json).unwrap();
        // The C++ uses -1000.0 as the "not set" sentinel.
        assert_eq!(b.elements[0].rotation, domain::ROTATION_UNSET);
        assert!(!b.elements[0].has_rotation());
    }

    #[test]
    fn empty_building_loads_cleanly() {
        let json = r"{}";
        let b = parse_json(json).unwrap();
        assert_eq!(b.elements.len(), 0);
    }

    #[test]
    fn mesh_data_round_trips() {
        let json = r#"{
            "elements": [{
                "type": "wall",
                "start": [0,0,0], "end": [1,0,0],
                "mesh": {
                    "vertices": [[0,0,0], [1,0,0], [0,1,0]],
                    "faces": [[0,1,2]]
                }
            }]
        }"#;
        let b = parse_json(json).unwrap();
        assert_eq!(b.elements[0].mesh.vertices.len(), 3);
        assert_eq!(b.elements[0].mesh.faces.len(), 1);
        assert_eq!(b.elements[0].mesh.faces[0], [0, 1, 2]);
    }

    #[test]
    fn unknown_string_type_falls_back_to_beam() {
        // The C++'s static_cast<ElementType>(0) maps to Beam.
        let json = r#"{"elements": [{"type": "unknown", "start": [0,0,0], "end": [1,0,0]}]}"#;
        let b = parse_json(json).unwrap();
        assert_eq!(b.elements[0].element_type, ElementType::Beam);
    }

    #[test]
    fn malformed_json_returns_error() {
        let err = parse_json("{ broken").unwrap_err();
        assert!(matches!(err, LoadError::Json(_)));
    }
}
