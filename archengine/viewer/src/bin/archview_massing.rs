//! archview-massing — interactive viewer for zoning-generated massing options.
//!
//! This tool demonstrates the full pipeline from zoning constraints to 3D 
//! visualization:
//!
//! ```sh
//! # Generate massing options for a rectangular lot with Sudbury R1 zoning
//! archview-massing --lot-width 20 --lot-depth 40 --zone R1
//!
//! # Or load from JSON site definition
//! archview-massing --site site.json
//! ```
//!
//! Controls: WASD move, Q/E down/up, right mouse orbit, scroll zoom, 
//! F frame scene, Esc quit. Use number keys 1-5 to switch between massing options.

use std::path::PathBuf;
use anyhow::{Context, Result};
use glam::{Vec2, Vec3};

#[derive(Default)]
struct Args {
    site: Option<PathBuf>,
    lot_width: Option<f32>,
    lot_depth: Option<f32>,
    zone: String,
    jurisdiction: String,
    street: Option<String>,
    unit_count: u32,
    target_unit_sqm: f32,
    parking_spaces: u32,
}

fn parse_args() -> Result<Args> {
    let mut args = Args {
        zone: "R1".to_string(),
        jurisdiction: "Greater Sudbury".to_string(),
        ..Default::default()
    };
    
    let mut it = std::env::args().skip(1);
    while let Some(arg) = it.next() {
        match arg.as_str() {
            "--site" => {
                args.site = Some(PathBuf::from(it.next().context("--site needs a value")?));
            }
            "--lot-width" => {
                args.lot_width = Some(it.next().context("--lot-width needs a value")?
                    .parse().context("invalid lot width")?);
            }
            "--lot-depth" => {
                args.lot_depth = Some(it.next().context("--lot-depth needs a value")?
                    .parse().context("invalid lot depth")?);
            }
            "--zone" => {
                args.zone = it.next().context("--zone needs a value")?;
            }
            "--jurisdiction" => {
                args.jurisdiction = it.next().context("--jurisdiction needs a value")?;
            }
            "--street" => {
                args.street = Some(it.next().context("--street needs a value")?);
            }
            "--units" => {
                args.unit_count = it.next().context("--units needs a value")?
                    .parse().context("invalid unit count")?;
            }
            "--unit-size" => {
                args.target_unit_sqm = it.next().context("--unit-size needs a value")?
                    .parse().context("invalid unit size")?;
            }
            "--parking" => {
                args.parking_spaces = it.next().context("--parking needs a value")?
                    .parse().context("invalid parking spaces")?;
            }
            "-h" | "--help" => {
                eprintln!(
                    "archview-massing — Visualize zoning-generated massing options\n\n\
                     Usage:\n\
                     archview-massing --lot-width 20 --lot-depth 40 --zone R1\n\
                     archview-massing --site site.json\n\n\
                     Options:\n\
                     --lot-width <m>       Lot width in metres (default: auto from site)\n\
                     --lot-depth <m>       Lot depth in metres (default: auto from site)\n\
                     --zone <code>         Zoning code (default: R1)\n\
                     --jurisdiction <name> Jurisdiction (default: Greater Sudbury)\n\
                     --street <name>       Street name for front yard orientation\n\
                     --units <count>       Number of dwelling units (default: 2)\n\
                     --unit-size <sqm>     Target unit size in m² (default: 125)\n\
                     --parking <count>     Parking spaces (default: 2)\n\
                     -h, --help            Show this help message\n\n\
                     Controls:\n\
                     WASD          Move camera\n\
                     Q/E           Move down/up\n\
                     Right mouse   Orbit camera\n\
                     Scroll        Zoom\n\
                     1-5           Switch massing option\n\
                     F             Frame scene\n\
                     Esc           Quit"
                );
                std::process::exit(0);
            }
            other => anyhow::bail!("unknown argument: {other}"),
        }
    }
    
    // Validate: either --site or both --lot-width and --lot-depth required
    if args.site.is_none() {
        if args.lot_width.is_none() || args.lot_depth.is_none() {
            anyhow::bail!("Either --site <file.json> or both --lot-width and --lot-depth are required");
        }
    }
    
    Ok(args)
}

fn main() -> Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "info".into()),
        )
        .init();

    let args = parse_args()?;
    
    // Build site from args or load from file
    let site = if let Some(site_path) = args.site {
        let text = std::fs::read_to_string(&site_path)
            .with_context(|| format!("reading {}", site_path.display()))?;
        serde_json::from_str(&text)
            .with_context(|| format!("parsing site JSON from {}", site_path.display()))?
    } else {
        let width = args.lot_width.unwrap();
        let depth = args.lot_depth.unwrap();
        regime_params::Site {
            boundary: vec![
                Vec2::new(0.0, 0.0),
                Vec2::new(width, 0.0),
                Vec2::new(width, depth),
                Vec2::new(0.0, depth),
            ],
            jurisdiction: args.jurisdiction,
            zone: args.zone,
            street: args.street,
        }
    };
    
    // Build program brief
    let brief = regime_params::ProgramBrief {
        unit_count: if args.unit_count > 0 { args.unit_count } else { 2 },
        target_unit_sqm: if args.target_unit_sqm > 0.0 { args.target_unit_sqm } else { 125.0 },
        parking_spaces: args.parking_spaces,
        storeys: None,
    };
    
    // Build regime input
    let input = regime_params::RegimeInput {
        site,
        brief,
        answers: vec![],
    };
    
    // Get zoning rules
    let rules = regime_zoning::ZoningRules::sudbury(&input.site.zone);
    
    // Solve for massing options
    tracing::info!("Solving massing options for {} zone...", input.site.zone);
    let solver = regime_params::MassingSolver::default();
    let options = solver.solve(&input, &rules);
    
    if options.is_empty() {
        anyhow::bail!("No valid massing options could be generated. Try adjusting lot dimensions or program requirements.");
    }
    
    tracing::info!("Generated {} massing option(s)", options.len());
    for (i, opt) in options.iter().enumerate() {
        tracing::info!(
            "Option {}: {} storeys, {:.1}m height, {:.0} m² GFA, FSR {:.2}",
            i + 1,
            opt.storeys,
            opt.height_m,
            opt.gross_floor_area,
            opt.fsr
        );
    }
    
    // Convert massing options to building masses with meshes
    let building_masses: Vec<archengine_geometry::massing_bridge::BuildingMass> = options
        .iter()
        .map(|opt| archengine_geometry::massing_bridge::massing_to_building_mass(opt, None))
        .collect();
    
    // Convert to StructuralElements for the viewer
    let elements: Vec<archengine_geometry::domain::StructuralElement> = building_masses
        .iter()
        .enumerate()
        .flat_map(|(idx, mass)| {
            // Create one structural element per building mass
            // The viewer will render the custom mesh data
            let mut elem = archengine_geometry::domain::StructuralElement {
                element_type: archengine_geometry::domain::ElementType::Floor,
                start: glam::Vec3::ZERO,
                end: glam::Vec3::ZERO,
                width: 0.0,
                depth: 0.0,
                material: format!("massing_option_{}", idx + 1),
                stress: 0.0,
                ..Default::default()
            };
            
            // Attach the generated mesh as custom mesh data
            elem.mesh = mass.mesh.clone();
            
            Some(elem)
        })
        .collect();
    
    // Store which option to display (default: first)
    // For now, show all options side by side with offsets
    let offset_spacing = 30.0; // metres between options
    let mut positioned_elements = Vec::new();
    for (idx, mut elem) in elements.into_iter().enumerate() {
        // Offset each option along X axis for comparison
        let offset = glam::Vec3::new(idx as f32 * offset_spacing, 0.0, 0.0);
        for vert in elem.mesh.vertices.iter_mut() {
            vert.position += offset;
        }
        positioned_elements.push(elem);
    }
    
    // Run the viewer
    tracing::info!("Launching viewer with {} massing option(s)", positioned_elements.len());
    archengine_viewer::app::run_viewer(&positioned_elements, None)
        .context("viewer error")?;
    
    Ok(())
}
