/// Simple CLI tool to test massing generation without GPU requirements
/// Outputs massing options as JSON or formatted text

use regime_params::{RegimeInput, ProgramBrief, Site};
use regime_params::massing::MassingSolver;
use regime_zoning::ZoningRules;

fn main() {
    println!("🏗️  LegiCAD Massing Generator (CLI Test)\n");

    // Default lot: 20m x 40m (typical urban infill)
    let lot_width = 20.0;
    let lot_depth = 40.0;
    
    // Create site and brief
    let site = Site {
        boundary: vec![
            glam::Vec2::new(0.0, 0.0),
            glam::Vec2::new(lot_width, 0.0),
            glam::Vec2::new(lot_width, lot_depth),
            glam::Vec2::new(0.0, lot_depth),
        ],
        jurisdiction: "Greater Sudbury".into(),
        zone: "R1".into(),
        street: Some("Main St".into()),
    };
    
    let brief = ProgramBrief {
        unit_count: 2,
        target_unit_sqm: 148.6,
        parking_spaces: 2,
        storeys: None,
    };
    
    let input = RegimeInput {
        site,
        brief,
        answers: vec![],
    };
    
    // Sudbury R1 zoning rules
    let zoning = ZoningRules::sudbury("R1");

    println!("📍 Lot: {}m × {}m ({:.1} m²)", lot_width, lot_depth, lot_width * lot_depth);
    println!("📋 Zoning: R1 (Sudbury By-law 2010-100Z)");
    println!("   Front/Rear setback: {:.1}m / {:.1}m", zoning.front_setback, zoning.rear_setback);
    println!("   Side setbacks: {:.1}m", zoning.side_setback);
    println!("   Max height: {:.1}m", zoning.max_height);
    println!("   Max FSR: {:.2}", zoning.max_fsr);
    println!("   Max coverage: {:.0}%", zoning.max_coverage * 100.0);
    println!();

    // Solve for massing options
    let solver = MassingSolver {
        option_count: 5,
        min_storeys: 1,
        max_storeys: 3,
        ..Default::default()
    };

    let options = solver.solve(&input, &zoning);
    
    if options.is_empty() {
        eprintln!("❌ No valid massing options found!");
        eprintln!("   The lot may be too small for the given setbacks.");
        std::process::exit(1);
    }
    
    println!("✅ Generated {} massing option(s):\n", options.len());
    
    for (i, opt) in options.iter().enumerate() {
        println!("┌─────────────────────────────────────┐");
        println!("│  Option {:<34} │", i + 1);
        println!("├─────────────────────────────────────┤");
        println!("│  Storeys: {:<29} │", opt.storeys);
        println!("│  Height: {:.2}m{:<26} │", opt.height_m, "");
        println!("│  GFA: {:.1} m²{:<27} │", opt.gross_floor_area, "");
        println!("│  FSR: {:.3}{:<30} │", opt.fsr, "");
        println!("│  Coverage: {:.1}%{:<24} │", opt.coverage * 100.0, "");
        println!("│  Footprint vertices: {}{:<22} │", opt.footprint.len(), "");
        
        // Show footprint bounds
        if let Some(bounds) = get_footprint_bounds(&opt.footprint) {
            println!("│  Footprint: {:.1}×{:.1}m{:<20} │", 
                bounds.1[0] - bounds.0[0], 
                bounds.1[1] - bounds.0[1], 
                "");
        }
        println!("└─────────────────────────────────────┘");
        println!();
    }

    // Output as JSON if requested
    let args: Vec<String> = std::env::args().collect();
    if args.contains(&"--json".to_string()) {
        println!("\n📄 JSON Output:");
        println!("{}", serde_json::to_string_pretty(&options).unwrap_or_else(|e| format!("Error: {}", e)));
    }
}

fn get_footprint_bounds(footprint: &[glam::Vec2]) -> Option<([f32; 2], [f32; 2])> {
    if footprint.is_empty() {
        return None;
    }
    
    let mut min_x = footprint[0].x;
    let mut max_x = footprint[0].x;
    let mut min_y = footprint[0].y;
    let mut max_y = footprint[0].y;
    
    for vertex in footprint.iter() {
        min_x = min_x.min(vertex.x);
        max_x = max_x.max(vertex.x);
        min_y = min_y.min(vertex.y);
        max_y = max_y.max(vertex.y);
    }
    
    Some(([min_x, min_y], [max_x, max_y]))
}
