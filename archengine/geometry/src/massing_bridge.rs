//! Massing-to-mesh bridge — converts regime massing options into 3D geometry.
//!
//! This module provides the critical link between the constraint solver
//! (`regime-params`) and the geometry kernel (`archengine-geometry`),
//! transforming 2D footprints and heights into renderable 3D meshes.

use glam::{Vec2, Vec3};
use serde::{Deserialize, Serialize};

use crate::mesh_gen::PrimitiveMesh;

/// A complete 3D building mass derived from a massing option.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct BuildingMass {
    /// The generated mesh (vertices + indices).
    pub mesh: PrimitiveMesh,
    /// Number of storeys.
    pub storeys: u32,
    /// Total height (metres).
    pub height_m: f32,
    /// Gross floor area (m²).
    pub gross_floor_area: f32,
    /// Footprint area (m²).
    pub footprint_area: f32,
    /// Floor space ratio achieved.
    pub fsr: f32,
    /// Lot coverage achieved.
    pub coverage: f32,
    /// Floor levels (Y coordinates) for reference.
    pub floor_levels: Vec<f32>,
}

impl BuildingMass {
    /// Create a building mass from a 2D footprint polygon and height.
    ///
    /// # Arguments
    /// * `footprint` - Closed 2D polygon in XZ plane (metres)
    /// * `height` - Total building height (metres)
    /// * `storeys` - Number of storeys
    /// * `gross_floor_area` - Total GFA across all floors
    /// * `footprint_area` - Ground footprint area
    /// * `color` - RGB color for visualization
    #[must_use]
    pub fn from_footprint(
        footprint: &[Vec2],
        height: f32,
        storeys: u32,
        gross_floor_area: f32,
        footprint_area: f32,
        color: Vec3,
    ) -> Self {
        // Generate the extruded mesh
        let mesh = crate::mesh_gen::create_extruded_polygon(footprint, height, color);
        
        // Calculate floor levels
        let storey_height = if storeys > 0 { height / storeys as f32 } else { 0.0 };
        let floor_levels: Vec<f32> = (0..=storeys)
            .map(|i| i as f32 * storey_height)
            .collect();
        
        let fsr = if footprint_area > 0.0 {
            gross_floor_area / (footprint_area * storeys as f32 * footprint_area / gross_floor_area).max(1.0)
        } else {
            0.0
        };
        
        let coverage = footprint_area;
        
        Self {
            mesh,
            storeys,
            height_m: height,
            gross_floor_area,
            footprint_area,
            fsr,
            coverage,
            floor_levels,
        }
    }
    
    /// Check if the mass has valid geometry.
    #[must_use]
    pub fn is_valid(&self) -> bool {
        !self.mesh.is_empty() && self.height_m > 0.0 && self.storeys > 0
    }
    
    /// Get the bounding box of the mass (min Y, max Y).
    #[must_use]
    pub fn height_range(&self) -> (f32, f32) {
        (0.0, self.height_m)
    }
}

/// Convert a regime massing option into a building mass with mesh.
///
/// # Arguments
/// * `massing_option` - The solved massing configuration from regime-params
/// * `color` - RGB color for visualization (default: light gray building)
#[must_use]
pub fn massing_to_building_mass(
    massing_option: &regime_params::MassingOption,
    color: Option<Vec3>,
) -> BuildingMass {
    let color = color.unwrap_or(Vec3::new(0.85, 0.85, 0.9)); // Light gray-blue
    
    BuildingMass::from_footprint(
        &massing_option.footprint,
        massing_option.height_m,
        massing_option.storeys,
        massing_option.gross_floor_area,
        massing_option.footprint_area,
        color,
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use glam::Vec2;
    
    #[test]
    fn test_rectangular_footprint_extrusion() {
        // Simple 10x15m rectangular footprint
        let footprint = vec![
            Vec2::new(0.0, 0.0),
            Vec2::new(10.0, 0.0),
            Vec2::new(10.0, 15.0),
            Vec2::new(0.0, 15.0),
        ];
        
        let mass = BuildingMass::from_footprint(
            &footprint,
            12.0,  // 12m height
            4,     // 4 storeys
            600.0, // 600 m² GFA
            150.0, // 150 m² footprint
            Vec3::new(0.8, 0.8, 0.85),
        );
        
        assert!(mass.is_valid());
        assert_eq!(mass.storeys, 4);
        assert!((mass.height_m - 12.0).abs() < 0.001);
        assert!((mass.gross_floor_area - 600.0).abs() < 0.001);
        assert_eq!(mass.floor_levels.len(), 5); // 0, 3, 6, 9, 12
        assert!((mass.floor_levels[1] - 3.0).abs() < 0.001);
    }
    
    #[test]
    fn test_l_shaped_footprint() {
        // L-shaped footprint
        let footprint = vec![
            Vec2::new(0.0, 0.0),
            Vec2::new(20.0, 0.0),
            Vec2::new(20.0, 10.0),
            Vec2::new(10.0, 10.0),
            Vec2::new(10.0, 20.0),
            Vec2::new(0.0, 20.0),
        ];
        
        let mass = BuildingMass::from_footprint(
            &footprint,
            9.0,
            3,
            450.0,
            300.0,
            Vec3::new(0.7, 0.75, 0.8),
        );
        
        assert!(mass.is_valid());
        assert!(!mass.mesh.vertices.is_empty());
        assert!(!mass.mesh.indices.is_empty());
    }
    
    #[test]
    fn test_invalid_footprint_rejected() {
        // Too few vertices
        let footprint = vec![
            Vec2::new(0.0, 0.0),
            Vec2::new(10.0, 0.0),
        ];
        
        let mass = BuildingMass::from_footprint(
            &footprint,
            10.0,
            3,
            100.0,
            50.0,
            Vec3::X,
        );
        
        assert!(!mass.is_valid());
        assert!(mass.mesh.is_empty());
    }
    
    #[test]
    fn test_floor_levels_calculation() {
        let footprint = vec![
            Vec2::new(0.0, 0.0),
            Vec2::new(10.0, 0.0),
            Vec2::new(10.0, 10.0),
            Vec2::new(0.0, 10.0),
        ];
        
        let mass = BuildingMass::from_footprint(
            &footprint,
            15.0,
            5,
            500.0,
            100.0,
            Vec3::Y,
        );
        
        assert_eq!(mass.floor_levels.len(), 6);
        for (i, &level) in mass.floor_levels.iter().enumerate() {
            let expected = i as f32 * 3.0; // 15m / 5 storeys = 3m per storey
            assert!((level - expected).abs() < 0.001);
        }
    }
}

#[cfg(test)]
mod integration_tests {
    use super::*;
    use glam::Vec3;
    use regime_zoning::ZoningRules;
    
    #[test]
    fn test_regime_to_geometry_pipeline() {
        // Create a sample rectangular lot (20m x 40m = 800 m²)
        let site = regime_params::Site {
            boundary: vec![
                Vec2::new(0.0, 0.0),
                Vec2::new(20.0, 0.0),
                Vec2::new(20.0, 40.0),
                Vec2::new(0.0, 40.0),
            ],
            jurisdiction: "Greater Sudbury".to_string(),
            zone: "R1".to_string(),
            street: Some("Main Street".to_string()),
        };
        
        // Create program brief
        let brief = regime_params::ProgramBrief {
            unit_count: 2,
            target_unit_sqm: 125.0,
            parking_spaces: 2,
            storeys: None,
        };
        
        // Build input
        let input = regime_params::RegimeInput {
            site,
            brief,
            answers: vec![],
        };
        
        // Get zoning rules for Sudbury R1
        let rules = ZoningRules::sudbury("R1");
        
        // Solve for massing options
        let solver = regime_params::MassingSolver::default();
        let options = solver.solve(&input, &rules);
        
        assert!(!options.is_empty(), "Should generate at least one massing option");
        
        // Convert first option to 3D building mass
        let first_option = &options[0];
        let building_mass = massing_to_building_mass(
            first_option,
            Some(Vec3::new(0.9, 0.85, 0.8)),
        );
        
        assert!(building_mass.is_valid());
        assert!(!building_mass.mesh.vertices.is_empty());
        assert!(!building_mass.mesh.indices.is_empty());
        assert_eq!(building_mass.storeys, first_option.storeys);
        assert!((building_mass.height_m - first_option.height_m).abs() < 0.001);
    }
}
