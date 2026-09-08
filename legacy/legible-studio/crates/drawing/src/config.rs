//! Layer + material-hatch defaults — port of `initDefaults` (`slicer_2d.cpp:26`).
//!
//! `Config` is a value-type carrying the lookup tables. The C++ embeds
//! these in the `Slicer2D` instance; in Rust they're an independent
//! struct that the slicer takes by reference.

use glam::Vec3;
use std::collections::BTreeMap;

/// Per-element-type layer configuration: CAD layer name, colour, line
/// type, line weight.
#[derive(Debug, Clone, PartialEq)]
pub struct LayerConfig {
    pub name: String,
    pub color: Vec3,
    pub line_type: String,
    pub line_weight: f32,
}

/// Pattern + scale lookup for material hatches.
#[derive(Debug, Clone, PartialEq, Default)]
pub struct HatchSpec {
    pub pattern: String,
    pub scale: f32,
}

/// Drawing configuration. Use [`Config::with_defaults`] to get the
/// industry-default layer set ported from `slicer_2d.cpp:27-50`.
///
/// Backed by [`BTreeMap`] so iteration order is stable — important for
/// diff-clean DXF/SVG output. The C++ uses `std::unordered_map` which
/// is hash-ordered; the `dxfTables` function emits layers in that
/// arbitrary order. For Rust we choose deterministic ordering and the
/// diff harness handles the line-order difference where it occurs.
#[derive(Debug, Clone, Default)]
pub struct Config {
    pub layer_configs: BTreeMap<String, LayerConfig>,
    pub material_hatches: BTreeMap<String, HatchSpec>,
}

impl Config {
    /// Load the same defaults as the C++ `Slicer2D::initDefaults`.
    #[must_use]
    #[allow(clippy::too_many_lines)] // Mirrors the C++ initDefaults table literally.
    pub fn with_defaults() -> Self {
        let mut c = Self::default();

        // Layer configs.
        c.layer_configs.insert(
            "wall".into(),
            LayerConfig {
                name: "A-WALL".into(),
                color: Vec3::ZERO,
                line_type: "continuous".into(),
                line_weight: 0.35,
            },
        );
        c.layer_configs.insert(
            "wall_hidden".into(),
            LayerConfig {
                name: "A-WALL-HIDN".into(),
                color: Vec3::splat(0.5),
                line_type: "dashed".into(),
                line_weight: 0.18,
            },
        );
        c.layer_configs.insert(
            "column".into(),
            LayerConfig {
                name: "S-COLS".into(),
                color: Vec3::ZERO,
                line_type: "continuous".into(),
                line_weight: 0.50,
            },
        );
        c.layer_configs.insert(
            "beam".into(),
            LayerConfig {
                name: "S-BEAM".into(),
                color: Vec3::ZERO,
                line_type: "continuous".into(),
                line_weight: 0.35,
            },
        );
        c.layer_configs.insert(
            "floor".into(),
            LayerConfig {
                name: "A-FLOR".into(),
                color: Vec3::splat(0.3),
                line_type: "continuous".into(),
                line_weight: 0.25,
            },
        );
        c.layer_configs.insert(
            "door".into(),
            LayerConfig {
                name: "A-DOOR".into(),
                color: Vec3::ZERO,
                line_type: "continuous".into(),
                line_weight: 0.25,
            },
        );
        c.layer_configs.insert(
            "window".into(),
            LayerConfig {
                name: "A-GLAZ".into(),
                color: Vec3::ZERO,
                line_type: "continuous".into(),
                line_weight: 0.25,
            },
        );
        c.layer_configs.insert(
            "dimension".into(),
            LayerConfig {
                name: "A-DIMS".into(),
                color: Vec3::ZERO,
                line_type: "continuous".into(),
                line_weight: 0.18,
            },
        );
        c.layer_configs.insert(
            "text".into(),
            LayerConfig {
                name: "A-NOTE".into(),
                color: Vec3::ZERO,
                line_type: "continuous".into(),
                line_weight: 0.18,
            },
        );
        c.layer_configs.insert(
            "hatch".into(),
            LayerConfig {
                name: "A-PATT".into(),
                color: Vec3::splat(0.7),
                line_type: "continuous".into(),
                line_weight: 0.13,
            },
        );

        // Material hatches.
        c.material_hatches.insert(
            "wood".into(),
            HatchSpec {
                pattern: "ANSI31".into(),
                scale: 1.0,
            },
        );
        c.material_hatches.insert(
            "concrete".into(),
            HatchSpec {
                pattern: "AR-CONC".into(),
                scale: 1.0,
            },
        );
        c.material_hatches.insert(
            "steel".into(),
            HatchSpec {
                pattern: "STEEL".into(),
                scale: 1.0,
            },
        );
        c.material_hatches.insert(
            "insulation".into(),
            HatchSpec {
                pattern: "INSUL".into(),
                scale: 1.0,
            },
        );
        c.material_hatches.insert(
            "fiberglass".into(),
            HatchSpec {
                pattern: "INSUL".into(),
                scale: 0.5,
            },
        );
        c.material_hatches.insert(
            "gypsum".into(),
            HatchSpec {
                pattern: "SOLID".into(),
                scale: 1.0,
            },
        );
        c.material_hatches.insert(
            "drywall".into(),
            HatchSpec {
                pattern: "SOLID".into(),
                scale: 1.0,
            },
        );
        c.material_hatches.insert(
            "osb".into(),
            HatchSpec {
                pattern: "PLYWOOD".into(),
                scale: 1.0,
            },
        );
        c.material_hatches.insert(
            "plywood".into(),
            HatchSpec {
                pattern: "PLYWOOD".into(),
                scale: 1.0,
            },
        );
        c.material_hatches.insert(
            "brick".into(),
            HatchSpec {
                pattern: "AR-BRSTD".into(),
                scale: 1.0,
            },
        );
        c.material_hatches.insert(
            "air".into(),
            HatchSpec {
                pattern: String::new(),
                scale: 0.0,
            },
        );

        c
    }

    /// Layer config for `element_type`. Falls back to the "wall" config.
    #[must_use]
    pub fn layer_for(&self, element_type: &str) -> &LayerConfig {
        self.layer_configs
            .get(element_type)
            .or_else(|| self.layer_configs.get("wall"))
            .expect("default config always has 'wall'")
    }

    /// Hatch for `material`. Returns an `(ANSI31, 1.0)` fallback when no
    /// match — matches the C++ default in `createMaterialHatch`
    /// (`slicer_2d.cpp:476`).
    #[must_use]
    pub fn hatch_for(&self, material: &str) -> HatchSpec {
        self.material_hatches
            .get(material)
            .cloned()
            .unwrap_or(HatchSpec {
                pattern: "ANSI31".into(),
                scale: 1.0,
            })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn defaults_include_canonical_layers() {
        let c = Config::with_defaults();
        assert_eq!(c.layer_for("wall").name, "A-WALL");
        assert_eq!(c.layer_for("column").name, "S-COLS");
        assert_eq!(c.layer_for("hatch").name, "A-PATT");
    }

    #[test]
    fn layer_for_unknown_falls_back_to_wall() {
        let c = Config::with_defaults();
        assert_eq!(c.layer_for("never_heard_of").name, "A-WALL");
    }

    #[test]
    fn hatch_for_known_material() {
        let c = Config::with_defaults();
        let h = c.hatch_for("concrete");
        assert_eq!(h.pattern, "AR-CONC");
        assert_eq!(h.scale, 1.0);
    }

    #[test]
    fn hatch_for_unknown_material_falls_back_to_ansi31() {
        let c = Config::with_defaults();
        let h = c.hatch_for("unobtainium");
        assert_eq!(h.pattern, "ANSI31");
    }

    #[test]
    fn fiberglass_uses_insul_at_half_scale() {
        let c = Config::with_defaults();
        let h = c.hatch_for("fiberglass");
        assert_eq!(h.pattern, "INSUL");
        assert_eq!(h.scale, 0.5);
    }

    #[test]
    fn air_has_empty_pattern() {
        let c = Config::with_defaults();
        let h = c.hatch_for("air");
        assert!(h.pattern.is_empty());
    }
}
