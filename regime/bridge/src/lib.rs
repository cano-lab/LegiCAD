//! Bridge between regime massing options and archengine geometry.
//!
//! This module converts [`MassingOption`] envelopes from `regime-params` into
//! renderable 3D meshes using `archengine-geometry`, enabling visualization
//! and further geometric processing.

use glam::{Vec2, Vec3};
use archengine_geometry::mesh_gen::{PrimitiveMesh, create_extruded_polygon};
use regime_params::massing::MassingOption;

/// Generated mesh for a massing option with metadata.
#[derive(Debug, Clone, PartialEq)]
pub struct MassingMesh {
    /// The original massing option this mesh represents.
    pub option: MassingOption,
    /// The generated 3D mesh (vertices + indices).
    pub mesh: PrimitiveMesh,
    /// Optional floor plates for each storey (for interior visualization).
    pub floor_plates: Vec<FloorPlate>,
}

/// A single floor plate within a massing option.
#[derive(Debug, Clone, PartialEq)]
pub struct FloorPlate {
    /// Storey index (0 = ground floor).
    pub storey_index: u32,
    /// Height of this floor plate (metres).
    pub height_m: f32,
    /// Floor plate footprint (same as massing footprint).
    pub footprint: Vec<Vec2>,
    /// Mesh for just this floor plate (thin extrusion).
    pub mesh: PrimitiveMesh,
}

/// Convert a massing option into a 3D mesh with optional floor plates.
///
/// # Arguments
/// * `option` - The massing option to convert
/// * `floor_plate_thickness` - Thickness of each floor plate in metres (default: 0.2)
/// * `include_floors` - Whether to generate individual floor plates
///
/// # Returns
/// A [`MassingMesh`] containing the building envelope mesh and optional floor plates.
pub fn massing_to_mesh(
    option: &MassingOption,
    floor_plate_thickness: f32,
    include_floors: bool,
) -> MassingMesh {
    let color = Vec3::new(0.8, 0.8, 0.85); // Light grey-blue for massing
    
    // Generate main envelope mesh
    let mesh = create_extruded_polygon(&option.footprint, option.height_m, color);
    
    // Generate floor plates if requested
    let floor_plates = if include_floors {
        generate_floor_plates(option, floor_plate_thickness)
    } else {
        Vec::new()
    };
    
    MassingMesh {
        option: option.clone(),
        mesh,
        floor_plates,
    }
}

/// Generate floor plates for each storey of a massing option.
fn generate_floor_plates(option: &MassingOption, thickness: f32) -> Vec<FloorPlate> {
    let mut plates = Vec::with_capacity(option.storeys as usize);
    let storey_height = option.height_m / option.storeys as f32;
    
    for i in 0..option.storeys {
        let height = i as f32 * storey_height;
        
        // Create thin extrusion for floor plate
        let plate_mesh = create_extruded_polygon(
            &option.footprint,
            thickness,
            Vec3::new(0.6, 0.6, 0.65),
        );
        
        // Note: In a full implementation, we'd translate the mesh vertices
        // to the correct height. For now, we store the height metadata.
        plates.push(FloorPlate {
            storey_index: i,
            height_m: height,
            footprint: option.footprint.clone(),
            mesh: plate_mesh,
        });
    }
    
    plates
}

/// Generate multiple massing meshes from solver output.
///
/// # Arguments
/// * `options` - Slice of massing options from the solver
/// * `floor_plate_thickness` - Thickness of floor plates
/// * `include_floors` - Whether to include floor plates
///
/// # Returns
/// Vector of [`MassingMesh`] for each valid option.
pub fn generate_massing_options_meshes(
    options: &[MassingOption],
    floor_plate_thickness: f32,
    include_floors: bool,
) -> Vec<MassingMesh> {
    options
        .iter()
        .map(|opt| massing_to_mesh(opt, floor_plate_thickness, include_floors))
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use regime_params::{RegimeInput, Site, ProgramBrief, solve_massing};
    use regime_zoning::ZoningRules;

    fn test_input() -> RegimeInput {
        RegimeInput {
            site: Site {
                boundary: vec![
                    Vec2::new(0.0, 0.0),
                    Vec2::new(20.0, 0.0),
                    Vec2::new(20.0, 30.0),
                    Vec2::new(0.0, 30.0),
                ],
                jurisdiction: "Greater Sudbury".to_string(),
                zone: "R1".to_string(),
                street: None,
            },
            brief: ProgramBrief {
                unit_count: 2,
                target_unit_sqm: 100.0,
                storeys: None,
                parking_spaces: 2,
            },
            answers: Vec::new(),
        }
    }

    #[test]
    fn massing_to_mesh_generates_valid_geometry() {
        let input = test_input();
        let rules = ZoningRules::sudbury("R1");
        let options = solve_massing(&input, &rules);
        
        assert!(!options.is_empty());
        
        let massing_mesh = massing_to_mesh(&options[0], 0.2, false);
        
        assert!(!massing_mesh.mesh.is_empty());
        assert_eq!(massing_mesh.option.footprint, options[0].footprint);
        assert_eq!(massing_mesh.option.height_m, options[0].height_m);
    }

    #[test]
    fn massing_with_floor_plates() {
        let input = test_input();
        let rules = ZoningRules::sudbury("R1");
        let options = solve_massing(&input, &rules);
        
        let massing_mesh = massing_to_mesh(&options[0], 0.2, true);
        
        assert!(!massing_mesh.floor_plates.is_empty());
        assert_eq!(massing_mesh.floor_plates.len(), options[0].storeys as usize);
    }

    #[test]
    fn multiple_massing_meshes_generated() {
        let input = test_input();
        let rules = ZoningRules::sudbury("R1");
        let options = solve_massing(&input, &rules);
        
        let meshes = generate_massing_options_meshes(&options, 0.2, false);
        
        assert_eq!(meshes.len(), options.len());
        for mesh in meshes {
            assert!(!mesh.mesh.is_empty());
        }
    }

    #[test]
    fn floor_plate_heights_correct() {
        let input = test_input();
        let rules = ZoningRules::sudbury("R1");
        let options = solve_massing(&input, &rules);
        
        let massing_mesh = massing_to_mesh(&options[0], 0.2, true);
        
        // Check that floor plates are at increasing heights
        for i in 1..massing_mesh.floor_plates.len() {
            assert!(
                massing_mesh.floor_plates[i].height_m > massing_mesh.floor_plates[i - 1].height_m
            );
        }
    }
}
