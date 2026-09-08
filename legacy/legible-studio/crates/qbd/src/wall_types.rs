//! Default wall-type definitions used when the schema doesn't supply
//! its own. Ported verbatim from
//! `qbd_interface.cpp:31-73` (`QBDInterface::initDefaultWallTypes`).
//!
//! All thicknesses are in mm (matching the QBD wire format).

use domain::{LayerFunction, WallLayer, WallType, WallTypeIntent};
use glam::Vec3;

/// 2x6 exterior wall with R-21 insulation. 5 layers + R-21 thermal target.
#[must_use]
pub fn exterior_2x6_r21() -> WallType {
    WallType {
        id: "ext_2x6_r21".into(),
        name: "2x6 Exterior Wall R-21".into(),
        layers: vec![
            WallLayer {
                name: "Vinyl Siding".into(),
                material: "vinyl".into(),
                function: LayerFunction::ExteriorFinish,
                thickness: 6.0,
                color: Vec3::new(0.8, 0.8, 0.85),
                r_value: 0.5,
                fasteners: Vec::new(),
            },
            WallLayer {
                name: "OSB Sheathing".into(),
                material: "osb".into(),
                function: LayerFunction::Sheathing,
                thickness: 11.0,
                color: Vec3::new(0.7, 0.6, 0.4),
                r_value: 0.5,
                fasteners: Vec::new(),
            },
            WallLayer {
                name: "2x6 Stud + R-21 Batt".into(),
                material: "fiberglass".into(),
                function: LayerFunction::Structure,
                thickness: 140.0,
                color: Vec3::new(1.0, 0.9, 0.7),
                r_value: 21.0,
                fasteners: Vec::new(),
            },
            WallLayer {
                name: "6mil Poly Vapor Barrier".into(),
                material: "polyethylene".into(),
                function: LayerFunction::Membrane,
                thickness: 0.15,
                color: Vec3::new(0.9, 0.9, 0.95),
                r_value: 0.0,
                fasteners: Vec::new(),
            },
            WallLayer {
                name: "1/2\" Drywall".into(),
                material: "gypsum".into(),
                function: LayerFunction::InteriorFinish,
                thickness: 13.0,
                color: Vec3::new(0.95, 0.95, 0.95),
                r_value: 0.45,
                fasteners: Vec::new(),
            },
        ],
        constraints: Vec::new(),
        intents: Vec::new(),
        intent: WallTypeIntent {
            r_value_target: 21.0,
            structural_role: "load_bearing".into(),
            climate_zone: "Zone 6".into(),
        },
    }
}

/// 2x4 interior partition. 3 layers (drywall, stud, drywall), no thermal target.
#[must_use]
pub fn interior_2x4() -> WallType {
    WallType {
        id: "int_2x4".into(),
        name: "2x4 Interior Partition".into(),
        layers: vec![
            WallLayer {
                name: "1/2\" Drywall".into(),
                material: "gypsum".into(),
                function: LayerFunction::InteriorFinish,
                thickness: 13.0,
                color: Vec3::new(0.95, 0.95, 0.95),
                r_value: 0.45,
                fasteners: Vec::new(),
            },
            WallLayer {
                name: "2x4 Stud".into(),
                material: "wood".into(),
                function: LayerFunction::Structure,
                thickness: 89.0,
                color: Vec3::new(0.9, 0.8, 0.6),
                r_value: 0.0,
                fasteners: Vec::new(),
            },
            WallLayer {
                name: "1/2\" Drywall".into(),
                material: "gypsum".into(),
                function: LayerFunction::InteriorFinish,
                thickness: 13.0,
                color: Vec3::new(0.95, 0.95, 0.95),
                r_value: 0.45,
                fasteners: Vec::new(),
            },
        ],
        constraints: Vec::new(),
        intents: Vec::new(),
        intent: WallTypeIntent {
            r_value_target: 0.0,
            structural_role: "non_bearing".into(),
            climate_zone: String::new(),
        },
    }
}

/// 2x6 wet wall (plumbing chase). 3 layers: moisture-resistant drywall,
/// 2x6 stud, moisture-resistant drywall.
#[must_use]
pub fn wet_2x6() -> WallType {
    WallType {
        id: "wet_2x6".into(),
        name: "2x6 Plumbing Wall".into(),
        layers: vec![
            WallLayer {
                name: "1/2\" Moisture Resistant Drywall".into(),
                material: "gypsum".into(),
                function: LayerFunction::InteriorFinish,
                thickness: 13.0,
                color: Vec3::new(0.9, 0.95, 0.9),
                r_value: 0.45,
                fasteners: Vec::new(),
            },
            WallLayer {
                name: "2x6 Stud (Plumbing Chase)".into(),
                material: "wood".into(),
                function: LayerFunction::Structure,
                thickness: 140.0,
                color: Vec3::new(0.9, 0.8, 0.6),
                r_value: 0.0,
                fasteners: Vec::new(),
            },
            WallLayer {
                name: "1/2\" Moisture Resistant Drywall".into(),
                material: "gypsum".into(),
                function: LayerFunction::InteriorFinish,
                thickness: 13.0,
                color: Vec3::new(0.9, 0.95, 0.9),
                r_value: 0.45,
                fasteners: Vec::new(),
            },
        ],
        constraints: Vec::new(),
        intents: Vec::new(),
        intent: WallTypeIntent {
            r_value_target: 0.0,
            structural_role: "non_bearing".into(),
            climate_zone: String::new(),
        },
    }
}

/// Zone-6-compliant exterior wall: 2x6 + R-22 batt + R-5 continuous
/// exterior insulation. Total nominal R ≈ 28, comfortably above OBC
/// Zone 6's R-24 wall requirement.
///
/// This is the modern Ontario Part 9 default and what `for_category`
/// returns for new construction. The older [`exterior_2x6_r21`] is kept
/// for compatibility with existing fixtures and as a "legacy retrofit"
/// option but is *not* code-compliant on its own.
#[must_use]
pub fn exterior_2x6_r22_continuous() -> WallType {
    WallType {
        id: "ext_2x6_r22_ci".into(),
        name: "2x6 Exterior Wall R-22 + R-5 c.i.".into(),
        layers: vec![
            WallLayer {
                name: "Vinyl Siding".into(),
                material: "vinyl".into(),
                function: LayerFunction::ExteriorFinish,
                thickness: 6.0,
                color: Vec3::new(0.8, 0.8, 0.85),
                r_value: 0.5,
                fasteners: Vec::new(),
            },
            WallLayer {
                name: "R-5 Continuous Insulation (1\" XPS)".into(),
                material: "xps".into(),
                function: LayerFunction::Insulation,
                thickness: 25.0,
                color: Vec3::new(0.4, 0.6, 0.9),
                r_value: 5.0,
                fasteners: Vec::new(),
            },
            WallLayer {
                name: "OSB Sheathing".into(),
                material: "osb".into(),
                function: LayerFunction::Sheathing,
                thickness: 11.0,
                color: Vec3::new(0.7, 0.6, 0.4),
                r_value: 0.5,
                fasteners: Vec::new(),
            },
            WallLayer {
                name: "2x6 Stud + R-22 Batt".into(),
                material: "fiberglass".into(),
                function: LayerFunction::Structure,
                thickness: 140.0,
                color: Vec3::new(1.0, 0.9, 0.7),
                r_value: 22.0,
                fasteners: Vec::new(),
            },
            WallLayer {
                name: "6mil Poly Vapor Barrier".into(),
                material: "polyethylene".into(),
                function: LayerFunction::Membrane,
                thickness: 0.15,
                color: Vec3::new(0.9, 0.9, 0.95),
                r_value: 0.0,
                fasteners: Vec::new(),
            },
            WallLayer {
                name: "1/2\" Drywall".into(),
                material: "gypsum".into(),
                function: LayerFunction::InteriorFinish,
                thickness: 13.0,
                color: Vec3::new(0.95, 0.95, 0.95),
                r_value: 0.45,
                fasteners: Vec::new(),
            },
        ],
        constraints: Vec::new(),
        intents: Vec::new(),
        intent: WallTypeIntent {
            r_value_target: 27.0,
            structural_role: "load_bearing".into(),
            climate_zone: "Zone 6".into(),
        },
    }
}

/// Convenience: pick the default wall type for a category string. Matches
/// `defaultWallTypeForCategory` (`qbd_interface.cpp:541`) — extended so
/// the exterior default is the Zone-6-compliant assembly.
#[must_use]
pub fn for_category(category: &str) -> WallType {
    match category {
        "exterior" => exterior_2x6_r22_continuous(),
        "wet_wall" => wet_2x6(),
        _ => interior_2x4(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn exterior_has_five_layers_totalling_170_15_mm() {
        let wt = exterior_2x6_r21();
        assert_eq!(wt.layers.len(), 5);
        // 6 + 11 + 140 + 0.15 + 13 = 170.15 mm
        let total: f32 = wt.layers.iter().map(|l| l.thickness).sum();
        assert!((total - 170.15).abs() < 1e-3);
        assert_eq!(wt.id, "ext_2x6_r21");
        assert_eq!(wt.intent.r_value_target, 21.0);
        assert_eq!(wt.intent.structural_role, "load_bearing");
    }

    #[test]
    fn interior_has_three_layers_totalling_115_mm() {
        let wt = interior_2x4();
        assert_eq!(wt.layers.len(), 3);
        let total: f32 = wt.layers.iter().map(|l| l.thickness).sum();
        assert!((total - 115.0).abs() < 1e-3); // 13 + 89 + 13
        assert_eq!(wt.intent.structural_role, "non_bearing");
    }

    #[test]
    fn wet_has_three_layers_totalling_166_mm() {
        let wt = wet_2x6();
        assert_eq!(wt.layers.len(), 3);
        let total: f32 = wt.layers.iter().map(|l| l.thickness).sum();
        assert!((total - 166.0).abs() < 1e-3); // 13 + 140 + 13
    }

    #[test]
    fn for_category_dispatches_correctly() {
        assert_eq!(for_category("exterior").id, "ext_2x6_r22_ci");
        assert_eq!(for_category("wet_wall").id, "wet_2x6");
        assert_eq!(for_category("interior").id, "int_2x4");
        // Unknown categories fall back to interior (matches C++ default).
        assert_eq!(for_category("foobar").id, "int_2x4");
    }

    #[test]
    fn exterior_r_value_sum_matches_design_target() {
        let wt = exterior_2x6_r21();
        // 0.5 + 0.5 + 21.0 + 0.0 + 0.45 = 22.45
        assert!((wt.total_r_value() - 22.45).abs() < 1e-3);
    }

    #[test]
    fn exterior_r22_continuous_meets_zone_6() {
        let wt = exterior_2x6_r22_continuous();
        // 0.5 + 5.0 + 0.5 + 22.0 + 0.0 + 0.45 = 28.45 > Zone 6's R-24 wall.
        assert!((wt.total_r_value() - 28.45).abs() < 1e-3);
        assert!(wt.total_r_value() >= 24.0);
    }
}
