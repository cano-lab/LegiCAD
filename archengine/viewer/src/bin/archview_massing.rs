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
//!
//! # With terrain data (GeoTIFF DEM or simple JSON terrain)
//! archview-massing --lot-width 20 --lot-depth 40 --zone R1 --terrain dem.tif
//! archview-massing --lot-width 20 --lot-depth 40 --zone R1 --terrain terrain.json
//! ```
//!
//! Controls: WASD move, Q/E down/up, right mouse orbit, scroll zoom, 
//! F frame scene, Esc quit. Use number keys 1-5 to switch between massing options.

use std::path::PathBuf;
use anyhow::{Context, Result};
use glam::{Vec2, Vec3};
use archengine_geometry::domain::MeshData;

/// Simple terrain JSON format for quick site topography
#[derive(serde::Deserialize, Debug)]
struct SimpleTerrain {
    /// Width of terrain in metres
    width_m: f32,
    /// Depth of terrain in metres  
    depth_m: f32,
    /// Grid dimensions (samples along each axis)
    grid_width: usize,
    grid_depth: usize,
    /// Elevation samples in row-major order (meters above datum)
    elevations: Vec<f32>,
}

/// Load terrain from either GeoTIFF DEM or simple JSON format
fn load_terrain(terrain_path: &PathBuf, lot_bounds: (Vec2, Vec2)) -> Result<Option<TerrainData>> {
    let extension = terrain_path.extension().and_then(|e| e.to_str()).unwrap_or("");
    
    match extension.to_lowercase().as_str() {
        "tif" | "tiff" => {
            // Load GeoTIFF DEM using legsite
            let raster = ls_site::read_elevation(terrain_path)
                .with_context(|| format!("Failed to read GeoTIFF: {}", terrain_path.display()))?;
            
            // Extract terrain mesh for the lot bounds
            // For simplicity, we'll sample the DEM at the lot corners
            let (min_bound, max_bound) = lot_bounds;
            let lot_width = max_bound.x - min_bound.x;
            let lot_depth = max_bound.y - min_bound.y;
            
            // Sample elevation at lot center as reference
            let center_x = (min_bound.x + max_bound.x) / 2.0;
            let center_y = (min_bound.y + max_bound.y) / 2.0;
            
            // TODO: Proper UTM projection for GeoTIFF sampling
            // For now, return basic terrain info
            Ok(Some(TerrainData {
                width_m: lot_width,
                depth_m: lot_depth,
                grid_width: 10,
                grid_depth: 10,
                elevations: vec![0.0; 100], // Placeholder
                base_elevation: 0.0,
            }))
        }
        "json" => {
            // Load simple JSON terrain
            let text = std::fs::read_to_string(terrain_path)
                .with_context(|| format!("reading {}", terrain_path.display()))?;
            let simple: SimpleTerrain = serde_json::from_str(&text)
                .with_context(|| format!("parsing terrain JSON from {}", terrain_path.display()))?;
            
            Ok(Some(TerrainData {
                width_m: simple.width_m,
                depth_m: simple.depth_m,
                grid_width: simple.grid_width,
                grid_depth: simple.grid_depth,
                elevations: simple.elevations,
                base_elevation: simple.elevations.iter().cloned().fold(f32::INFINITY, f32::min),
            }))
        }
        _ => {
            anyhow::bail!("Unsupported terrain file format: {}. Use .tif/.tiff for GeoTIFF DEM or .json for simple terrain.", extension);
        }
    }
}

/// Terrain data for rendering
struct TerrainData {
    width_m: f32,
    depth_m: f32,
    grid_width: usize,
    grid_depth: usize,
    elevations: Vec<f32>,
    base_elevation: f32,
}

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
    terrain: Option<PathBuf>,
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
            "--terrain" => {
                args.terrain = Some(PathBuf::from(it.next().context("--terrain needs a value")?));
            }
            "-h" | "--help" => {
                eprintln!(
                    "archview-massing — Visualize zoning-generated massing options\n\n\
                     Usage:\n\
                     archview-massing --lot-width 20 --lot-depth 40 --zone R1\n\
                     archview-massing --site site.json\n\
                     archview-massing --lot-width 20 --lot-depth 40 --zone R1 --terrain dem.tif\n\n\
                     Options:\n\
                     --lot-width <m>       Lot width in metres (default: auto from site)\n\
                     --lot-depth <m>       Lot depth in metres (default: auto from site)\n\
                     --zone <code>         Zoning code (default: R1)\n\
                     --jurisdiction <name> Jurisdiction (default: Greater Sudbury)\n\
                     --street <name>       Street name for front yard orientation\n\
                     --units <count>       Number of dwelling units (default: 2)\n\
                     --unit-size <sqm>     Target unit size in m² (default: 125)\n\
                     --parking <count>     Parking spaces (default: 2)\n\
                     --terrain <file>      Terrain file (.tif for GeoTIFF DEM, .json for simple terrain)\n\
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
    
    // Calculate lot bounds for terrain sampling
    let lot_bounds = if let Some(site_path) = &args.site {
        let text = std::fs::read_to_string(site_path)?;
        let site: serde_json::Value = serde_json::from_str(&text)?;
        if let Some(boundary) = site.get("boundary").and_then(|b| b.as_array()) {
            let mut min_x = f32::MAX;
            let mut min_y = f32::MAX;
            let mut max_x = f32::MIN;
            let mut max_y = f32::MIN;
            for pt in boundary {
                if let Some(arr) = pt.as_array() {
                    if arr.len() >= 2 {
                        if let (Some(x), Some(y)) = (arr[0].as_f64(), arr[1].as_f64()) {
                            min_x = min_x.min(x as f32);
                            min_y = min_y.min(y as f32);
                            max_x = max_x.max(x as f32);
                            max_y = max_y.max(y as f32);
                        }
                    }
                }
            }
            (Vec2::new(min_x, min_y), Vec2::new(max_x, max_y))
        } else {
            (Vec2::ZERO, Vec2::new(args.lot_width.unwrap_or(20.0), args.lot_depth.unwrap_or(40.0)))
        }
    } else {
        let width = args.lot_width.unwrap_or(20.0);
        let depth = args.lot_depth.unwrap_or(40.0);
        (Vec2::ZERO, Vec2::new(width, depth))
    };
    
    // Load terrain data if specified
    let terrain_data = if let Some(terrain_path) = &args.terrain {
        load_terrain(terrain_path, lot_bounds)?
    } else {
        None
    };
    
    // Convert massing options to building masses with meshes
    let building_masses: Vec<archengine_geometry::massing_bridge::BuildingMass> = options
        .iter()
        .map(|opt| archengine_geometry::massing_bridge::massing_to_building_mass(opt, None))
        .collect();
    
    // Convert to StructuralElements for the viewer
    let mut elements: Vec<archengine_geometry::domain::StructuralElement> = building_masses
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
            elem.mesh = MeshData::from(mass.mesh.clone());
            
            Some(elem)
        })
        .collect();
    
    // Add terrain mesh if available
    if let Some(terrain) = &terrain_data {
        tracing::info!("Adding terrain mesh: {}x{} grid", terrain.grid_width, terrain.grid_depth);
        
        // Create a terrain mesh from elevation data
        let mut terrain_mesh = archengine_geometry::mesh_gen::PrimitiveMesh {
            vertices: Vec::with_capacity(terrain.elevations.len()),
            indices: Vec::new(),
        };
        
        let x_step = terrain.width_m / (terrain.grid_width as f32);
        let z_step = terrain.depth_m / (terrain.grid_depth as f32);
        let base_z = terrain.base_elevation;
        
        // Generate vertices
        for (i, &elev) in terrain.elevations.iter().enumerate() {
            let row = i / terrain.grid_width;
            let col = i % terrain.grid_width;
            let x = col as f32 * x_step;
            let z = row as f32 * z_step;
            let y = elev - base_z; // Relative elevation
            
            terrain_mesh.vertices.push(archengine_geometry::mesh_gen::MeshVertex {
                position: Vec3::new(x, y, z),
                normal: Vec3::Y,
                tangent: Vec3::X,
                uv: Vec2::new(col as f32 / terrain.grid_width as f32, row as f32 / terrain.grid_depth as f32),
            });
        }
        
        // Generate indices for triangle strip
        for row in 0..(terrain.grid_depth - 1) {
            for col in 0..(terrain.grid_width - 1) {
                let i0 = row * terrain.grid_width + col;
                let i1 = i0 + 1;
                let i2 = (row + 1) * terrain.grid_width + col;
                let i3 = i2 + 1;
                
                terrain_mesh.indices.extend_from_slice(&[i0 as u32, i2 as u32, i1 as u32]);
                terrain_mesh.indices.extend_from_slice(&[i1 as u32, i2 as u32, i3 as u32]);
            }
        }
        
        let mut terrain_elem = archengine_geometry::domain::StructuralElement {
            element_type: archengine_geometry::domain::ElementType::Wall,
            start: glam::Vec3::ZERO,
            end: glam::Vec3::ZERO,
            width: 0.0,
            depth: 0.0,
            material: "terrain".to_string(),
            stress: 0.0,
            ..Default::default()
        };
        terrain_elem.mesh = MeshData::from(terrain_mesh);
        elements.push(terrain_elem);
    }
    
    // Store which option to display (default: first)
    // For now, show all options side by side with offsets
    let offset_spacing = 30.0; // metres between options
    let mut positioned_elements = Vec::new();
    for (idx, mut elem) in elements.into_iter().enumerate() {
        // Offset each option along X axis for comparison
        let offset = glam::Vec3::new(idx as f32 * offset_spacing, 0.0, 0.0);
        for vert in elem.mesh.vertices.iter_mut() {
            *vert += offset;
        }
        positioned_elements.push(elem);
    }
    
    // Run the viewer
    tracing::info!("Launching viewer with {} massing option(s)", positioned_elements.len());
    archengine_viewer::app::run_viewer(&positioned_elements, None)
        .context("viewer error")?;
    
    Ok(())
}
