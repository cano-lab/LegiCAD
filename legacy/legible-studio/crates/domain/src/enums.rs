//! Enums ported from `include/types.hpp`.
//!
//! All derived with `Serialize`/`Deserialize` (renamed to snake_case strings
//! to match the JSON schema convention used by the Python QBD generator).

use serde::{Deserialize, Serialize};

/// Structural element types (`types.hpp:111`).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
#[repr(u32)]
pub enum ElementType {
    Beam = 0,
    Column = 1,
    Floor = 2,
    Wall = 3,
    Foundation = 4,
    Connection = 5,
    Door = 6,
    Window = 7,
    Roof = 8,
}

/// Camera view modes (`types.hpp:171`).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
#[repr(u32)]
pub enum CameraView {
    #[default]
    Perspective,
    Top,
    Front,
    Right,
    Left,
    Back,
}

/// Light types for the multi-light system (`types.hpp:264`).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
#[repr(u32)]
pub enum LightType {
    Directional = 0,
    Point = 1,
    Spot = 2,
}

/// Visualization modes for stress/thermal/lighting/acoustic overlays (`types.hpp:353`).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
#[repr(u32)]
pub enum VisualizationMode {
    #[default]
    Structural,
    Thermal,
    Lighting,
    Acoustic,
    Material,
    Wireframe,
}

/// Material rendering style (`types.hpp:363`).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
#[repr(u32)]
pub enum MaterialStyle {
    #[default]
    Realistic,
    Clean,
    Schematic,
    Blueprint,
}

/// Wall layer functions (`types.hpp:504`).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
#[repr(u32)]
pub enum LayerFunction {
    ExteriorFinish,
    Sheathing,
    Insulation,
    Structure,
    InteriorFinish,
    AirGap,
    Membrane,
}

/// Fastener types for assembly connections (`types.hpp:519`).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
#[repr(u32)]
pub enum FastenerType {
    #[default]
    Nail,
    Screw,
    Bolt,
    Staple,
    Anchor,
    Strap,
    Hanger,
    Clip,
    Adhesive,
}

/// Constraint types for code compliance (`types.hpp:546`).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
#[repr(u32)]
pub enum ConstraintType {
    StructuralBearing,
    FireRating,
    ThermalPerformance,
    SoundTransmission,
    MoistureControl,
    AirBarrier,
    WindResistance,
    SeismicCategory,
    MaxSpan,
    MinThickness,
    #[default]
    CodeSection,
}

/// Intent categories for design rationale (`types.hpp:571`).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
#[repr(u32)]
pub enum IntentCategory {
    #[default]
    Performance,
    Constructability,
    Cost,
    Sustainability,
    Durability,
    Aesthetic,
    CodeCompliance,
}

/// Corner joint types (`types.hpp:647`).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
#[repr(u32)]
pub enum CornerType {
    #[default]
    None,
    Butt,
    Miter,
    LCorner,
    TIntersection,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn element_type_discriminants_match_cpp() {
        // The C++ assigns explicit discriminants 0..=8.
        // Both sides must agree so any binary-format crossings (e.g. push
        // constants, project files written by the C++ engine) stay valid.
        assert_eq!(ElementType::Beam as u32, 0);
        assert_eq!(ElementType::Column as u32, 1);
        assert_eq!(ElementType::Floor as u32, 2);
        assert_eq!(ElementType::Wall as u32, 3);
        assert_eq!(ElementType::Foundation as u32, 4);
        assert_eq!(ElementType::Connection as u32, 5);
        assert_eq!(ElementType::Door as u32, 6);
        assert_eq!(ElementType::Window as u32, 7);
        assert_eq!(ElementType::Roof as u32, 8);
    }

    #[test]
    fn light_type_discriminants_match_cpp() {
        assert_eq!(LightType::Directional as u32, 0);
        assert_eq!(LightType::Point as u32, 1);
        assert_eq!(LightType::Spot as u32, 2);
    }

    #[test]
    fn enum_round_trips_snake_case_json() {
        let elem = ElementType::Foundation;
        let s = serde_json::to_string(&elem).unwrap();
        assert_eq!(s, "\"foundation\"");
        let back: ElementType = serde_json::from_str(&s).unwrap();
        assert_eq!(back, ElementType::Foundation);
    }
}
