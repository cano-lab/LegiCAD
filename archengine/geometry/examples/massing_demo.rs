//! Demo: Generate massing options from zoning constraints and convert to 3D meshes.
//!
//! Run with: cargo run --example massing_demo

use glam::{Vec2, Vec3};

fn main() {
    println!("=== Massing Options Generator Demo ===\n");
    
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
    
    // Create program brief for a duplex
    let brief = regime_params::ProgramBrief {
        unit_count: 2,
        target_unit_sqm: 125.0,
        parking_spaces: 2,
        storeys: None,
    };
    
    let input = regime_params::RegimeInput {
        site,
        brief,
        answers: vec![],
    };
    
    // Get Sudbury R1 zoning rules
    let rules = regime_zoning::ZoningRules::sudbury("R1");
    
    println!("Zoning Rules (Sudbury R1):");
    println!("  Front setback: {:.1}m", rules.front_setback);
    println!("  Rear setback: {:.1}m", rules.rear_setback);
    println!("  Side setback: {:.1}m", rules.side_setback);
    println!("  Max height: {:.1}m", rules.max_height);
    println!("  Max FSR: {:.2}", rules.max_fsr);
    println!("  Max coverage: {:.2}\n", rules.max_coverage);
    
    // Solve for massing options
    let solver = regime_params::MassingSolver::default();
    let options = solver.solve(&input, &rules);
    
    println!("Generated {} massing options:\n", options.len());
    
    for (i, opt) in options.iter().enumerate() {
        println!("Option {}:", i + 1);
        println!("  Storeys: {}", opt.storeys);
        println!("  Height: {:.1}m", opt.height_m);
        println!("  GFA: {:.0} m²", opt.gross_floor_area);
        println!("  Footprint area: {:.0} m²", opt.footprint_area);
        println!("  FSR achieved: {:.2}", opt.fsr);
        println!("  Coverage: {:.2}", opt.coverage);
        println!("  Footprint vertices: {}", opt.footprint.len());
        
        // Convert to 3D building mass
        let building_mass = archengine_geometry::massing_bridge::massing_to_building_mass(
            opt,
            Some(Vec3::new(0.9 - i as f32 * 0.1, 0.85, 0.8)),
        );
        
        println!("  Mesh vertices: {}", building_mass.mesh.vertices.len());
        println!("  Mesh indices: {}", building_mass.mesh.indices.len());
        println!("  Floor levels: {:?}\n", building_mass.floor_levels);
    }
    
    if options.is_empty() {
        println!("No valid massing options found for the given constraints.");
    } else {
        println!("✓ Successfully generated and converted {} massing option(s) to 3D geometry!", options.len());
    }
}
