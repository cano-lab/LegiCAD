/// Simple CLI tool to test massing generation without GPU requirements
/// Outputs massing options as JSON or formatted text

use regime_params::massing::{MassingSolver, solve_massing};
use regime_zoning::ZoningRule;

fn main() {
    println!("🏗️  LegiCAD Massing Generator (CLI Test)\n");

    // Default lot: 20m x 40m (typical urban infill)
    let lot_width = 20.0;
    let lot_depth = 40.0;
    
    // Sudbury R1 zoning rules
    let zoning = ZoningRule {
        front_setback: 7.5,
        rear_setback: 7.5,
        side_setback_left: 3.0,
        side_setback_right: 3.0,
        max_height: 11.0,
        max_storeys: 3,
        fsr_max: 0.7,
        lot_coverage_max: 0.4,
        min_lot_width: 15.0,
    };

    println!("📍 Lot: {}m × {}m ({:.1} m²)", lot_width, lot_depth, lot_width * lot_depth);
    println!("📋 Zoning: R1 (Sudbury By-law 2010-100Z)");
    println!("   Front/Rear setback: {:.1}m", zoning.front_setback);
    println!("   Side setbacks: {:.1}m each", zoning.side_setback_left);
    println!("   Max height: {:.1}m", zoning.max_height);
    println!("   Max storeys: {}", zoning.max_storeys);
    println!("   Max FSR: {:.2}", zoning.fsr_max);
    println!("   Max coverage: {:.0}%", zoning.lot_coverage_max * 100.0);
    println!();

    // Solve for massing options
    let solver = MassingSolver::new()
        .with_num_options(5)
        .with_min_storeys(1)
        .with_max_storeys(zoning.max_storeys);

    match solver.solve(lot_width, lot_depth, &zoning, None) {
        Some(options) => {
            println!("✅ Generated {} massing option(s):\n", options.len());
            
            for (i, opt) in options.iter().enumerate() {
                println!("┌─────────────────────────────────────┐");
                println!("│  Option {:<34} │", i + 1);
                println!("├─────────────────────────────────────┤");
                println!("│  Storeys: {:<29} │", opt.storeys);
                println!("│  Height: {:.2}m{:<26} │", opt.height, "");
                println!("│  GFA: {:.1} m²{:<27} │", opt.gfa, "");
                println!("│  FSR: {:.3}{:<30} │", opt.fsr, "");
                println!("│  Coverage: {:.1}%{:<24} │", opt.coverage * 100.0, "");
                println!("│  Footprint vertices: {}{:<22} │", opt.footprint.len(), "");
                
                // Show footprint bounds
                if let Some(bounds) = get_footprint_bounds(&opt.footprint) {
                    println!("│  Footprint: {:.1}×{:.1}m{:<20} │", 
                        bounds.1.x - bounds.0.x, 
                        bounds.1.y - bounds.0.y, 
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
        None => {
            eprintln!("❌ No valid massing options found!");
            eprintln!("   The lot may be too small for the given setbacks.");
            std::process::exit(1);
        }
    }
}

fn get_footprint_bounds(footprint: &[[f32; 2]]) -> Option<([f32; 2], [f32; 2])> {
    if footprint.is_empty() {
        return None;
    }
    
    let mut min_x = footprint[0][0];
    let mut max_x = footprint[0][0];
    let mut min_y = footprint[0][1];
    let mut max_y = footprint[0][1];
    
    for vertex in footprint.iter() {
        min_x = min_x.min(vertex[0]);
        max_x = max_x.max(vertex[0]);
        min_y = min_y.min(vertex[1]);
        max_y = max_y.max(vertex[1]);
    }
    
    Some(([min_x, min_y], [max_x, max_y]))
}
