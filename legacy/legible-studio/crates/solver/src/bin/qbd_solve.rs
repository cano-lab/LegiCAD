//! `qbd_solve` — pure-Rust answers → `qbd_output.schema.json` bundle.
//!
//! The end of the Increment-4 path: no Python in answers → drawings.
//! Prints the building JSON to stdout.
//!
//! Usage:
//!     qbd_solve [--mode part9|part3|mixed]
//!               [--bedrooms N] [--bathrooms N] [--sqft N]
//!               [--garage none|1car|2car|3car] [--storeys 0|1|2]
//!               [--windows balanced|more_light|privacy|south_bank]
//!               [--style balanced|ranch|colonial|contemporary]
//!               [--lot WxD (ft)] [--zone R1|R2|R3] [--street "Name"]
//!               [--roof gable|hip]
//!               [--stair-config switchback|straight|l_shaped]
//!     qbd_solve --manifest <path>
//!     qbd_solve --template <name> [--storeys N] [--sqft N]
//!     qbd_solve --catalog <mode>
//!     (--storeys 0 = auto: 2 when 3+ bedrooms, else 1)

use solver::{building_json, building_json_from_manifest, Answers, BuildingMode, BuildingTemplate, ProgramManifest, RoomCatalog};

fn main() {
    let mut a = Answers::default();
    let mut manifest_path: Option<String> = None;
    let mut catalog_mode: Option<String> = None;
    let mut template_name: Option<String> = None;
    let mut template_storeys: u32 = 2;
    let mut template_sqft: f32 = 4000.0;
    let mut template_rooms_per_floor: u32 = 20;

    let args: Vec<String> = std::env::args().collect();
    let mut i = 1;
    while i + 1 < args.len() {
        match args[i].as_str() {
            "--mode" => {
                if let Ok(mode) = args[i + 1].parse::<BuildingMode>() {
                    a.mode = mode;
                }
            }
            "--bedrooms" => a.bedrooms = args[i + 1].parse().unwrap_or(a.bedrooms),
            "--bathrooms" => a.bathrooms = args[i + 1].parse().unwrap_or(a.bathrooms),
            "--sqft" => {
                a.sqft = args[i + 1].parse().unwrap_or(a.sqft);
                template_sqft = args[i + 1].parse().unwrap_or(template_sqft);
            }
            "--garage" => a.garage.clone_from(&args[i + 1]),
            "--storeys" => {
                a.storeys = args[i + 1].parse().unwrap_or(a.storeys);
                template_storeys = args[i + 1].parse().unwrap_or(template_storeys);
            }
            "--rooms-per-floor" => {
                template_rooms_per_floor = args[i + 1].parse().unwrap_or(template_rooms_per_floor);
            }
            "--windows" => a.window_intent.clone_from(&args[i + 1]),
            "--style" => a.style.clone_from(&args[i + 1]),
            "--zone" => a.zone.clone_from(&args[i + 1]),
            "--street" => a.street.clone_from(&args[i + 1]),
            "--roof" => a.roof_type.clone_from(&args[i + 1]),
            "--stair-config" => a.stair_config.clone_from(&args[i + 1]),
            "--lot" => {
                if let Some((w, d)) = args[i + 1].split_once('x') {
                    a.lot_width_ft = w.parse().unwrap_or(a.lot_width_ft);
                    a.lot_depth_ft = d.parse().unwrap_or(a.lot_depth_ft);
                }
            }
            "--manifest" => manifest_path = Some(args[i + 1].clone()),
            "--template" => template_name = Some(args[i + 1].clone()),
            "--catalog" => catalog_mode = Some(args[i + 1].clone()),
            _ => {}
        }
        i += 2;
    }

    if let Some(mode_str) = catalog_mode {
        let mode = mode_str.parse::<BuildingMode>().unwrap_or(BuildingMode::Part9);
        let cat = RoomCatalog::for_mode(mode);
        println!(
            "{}",
            serde_json::to_string_pretty(&serde_json::json!({
                "mode": mode.as_str(),
                "room_types": cat.room_types(),
            })
            )
            .unwrap_or_default()
        );
        return;
    }

    if let Some(path) = manifest_path {
        let contents = std::fs::read_to_string(&path).unwrap_or_else(|e| {
            eprintln!("failed to read manifest {path}: {e}");
            std::process::exit(1);
        });
        let manifest = ProgramManifest::from_json(&contents).unwrap_or_else(|e| {
            eprintln!("failed to parse manifest: {e}");
            std::process::exit(1);
        });
        if let Err(errors) = manifest.validate() {
            println!(
                "{}",
                serde_json::to_string_pretty(
                    &serde_json::json!({ "success": false, "errors": errors })
                )
                .unwrap_or_default()
            );
            return;
        }
        let value = building_json_from_manifest(&manifest);
        println!("{}", serde_json::to_string_pretty(&value).unwrap_or_default());
        return;
    }

    if let Some(name) = template_name {
        let template = parse_template(
            &name,
            template_storeys,
            template_sqft,
            template_rooms_per_floor,
            a.bedrooms,
            a.bathrooms,
        );
        let manifest = template.manifest();
        if let Err(errors) = manifest.validate() {
            println!(
                "{}",
                serde_json::to_string_pretty(
                    &serde_json::json!({ "success": false, "errors": errors })
                )
                .unwrap_or_default()
            );
            return;
        }
        let value = building_json_from_manifest(&manifest);
        println!("{}", serde_json::to_string_pretty(&value).unwrap_or_default());
        return;
    }

    let value = building_json(&a);
    println!("{}", serde_json::to_string_pretty(&value).unwrap_or_default());
}

fn parse_template(
    name: &str,
    storeys: u32,
    sqft: f32,
    rooms_per_floor: u32,
    bedrooms: u32,
    bathrooms: u32,
) -> BuildingTemplate {
    match name.to_ascii_lowercase().as_str() {
        "house" | "part9_house" | "part9-house" | "residential" => BuildingTemplate::Part9House {
            bedrooms,
            bathrooms,
            sqft,
        },
        "office" | "small_office" | "small-office" => BuildingTemplate::SmallOffice { storeys, sqft },
        "retail" | "neighbourhood_retail" | "neighbourhood-retail" => {
            BuildingTemplate::NeighbourhoodRetail { sqft }
        }
        "assembly" | "community_assembly" | "community-assembly" | "hall" => {
            BuildingTemplate::CommunityAssembly { sqft }
        }
        "industrial" | "light_industrial" | "light-industrial" | "warehouse" => {
            BuildingTemplate::LightIndustrial { sqft }
        }
        "mixed" | "mixed_use" | "mixed-use" | "podium" => BuildingTemplate::MixedUsePodium {
            retail_sqft: sqft,
            residential_floors: storeys.clamp(1, 6),
        },
        "college" | "college_residence" | "college-residence" | "dorm" => {
            BuildingTemplate::CollegeResidence {
                floors: storeys.clamp(2, 6),
                rooms_per_floor: rooms_per_floor.clamp(4, 40),
                sqft,
            }
        }
        other => {
            eprintln!("unknown template '{other}'. Available templates:");
            for t in BuildingTemplate::all() {
                eprintln!("  {} - {}", t.name(), t.description());
            }
            std::process::exit(1);
        }
    }
}
