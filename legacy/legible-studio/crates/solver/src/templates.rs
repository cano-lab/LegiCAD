//! Reusable building-program templates.
//!
//! A template is a parameterized recipe that expands into a
//! [`ProgramManifest`]. It lets users start from a known program (small office,
//! neighbourhood retail, mixed-use podium, …) instead of hand-authoring JSON.

use crate::{
    manifest::{AdjacencySpec, FloorManifest, ProgramManifest, RoomManifest},
    BuildingMode,
};

/// Named building program that can be expanded into a manifest.
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum BuildingTemplate {
    /// Part 9 detached house.
    Part9House { bedrooms: u32, bathrooms: u32, sqft: f32 },
    /// 1–4 storey business occupancy with corridor spine.
    SmallOffice { storeys: u32, sqft: f32 },
    /// Single-storey mercantile with rear service band.
    NeighbourhoodRetail { sqft: f32 },
    /// Single-storey assembly occupancy (lobby + auditorium + classroom).
    CommunityAssembly { sqft: f32 },
    /// Single-storey industrial (loading dock + warehouse + office).
    LightIndustrial { sqft: f32 },
    /// Retail/lobby ground floor + residential upper floors.
    MixedUsePodium { retail_sqft: f32, residential_floors: u32 },
    /// Multi-storey student residence with dorm rooms and shared amenities.
    CollegeResidence { floors: u32, rooms_per_floor: u32, sqft: f32 },
}

impl BuildingTemplate {
    /// Human-readable name for UI lists / CLI help.
    #[must_use]
    pub const fn name(&self) -> &'static str {
        match self {
            BuildingTemplate::Part9House { .. } => "Part 9 House",
            BuildingTemplate::SmallOffice { .. } => "Small Office",
            BuildingTemplate::NeighbourhoodRetail { .. } => "Neighbourhood Retail",
            BuildingTemplate::CommunityAssembly { .. } => "Community Assembly Hall",
            BuildingTemplate::LightIndustrial { .. } => "Light Industrial Unit",
            BuildingTemplate::MixedUsePodium { .. } => "Mixed-Use Retail + Residential Podium",
            BuildingTemplate::CollegeResidence { .. } => "College Residence",
        }
    }

    /// Short description shown in the template picker.
    #[must_use]
    pub const fn description(&self) -> &'static str {
        match self {
            BuildingTemplate::Part9House { .. } => "Detached house, Part 9 residential.",
            BuildingTemplate::SmallOffice { .. } => {
                "Business occupancy office, 1–4 storeys, corridor spine."
            }
            BuildingTemplate::NeighbourhoodRetail { .. } => {
                "Single-storey mercantile with rear service rooms."
            }
            BuildingTemplate::CommunityAssembly { .. } => {
                "Assembly hall with lobby, auditorium and classrooms."
            }
            BuildingTemplate::LightIndustrial { .. } => {
                "Warehouse / loading dock / office, single storey."
            }
            BuildingTemplate::MixedUsePodium { .. } => {
                "Retail ground floor with residential apartments above."
            }
            BuildingTemplate::CollegeResidence { .. } => {
                "Student residence with shared washrooms and amenity spaces."
            }
        }
    }

    /// All available templates for the UI picker.
    #[must_use]
    pub fn all() -> Vec<Self> {
        vec![
            BuildingTemplate::Part9House {
                bedrooms: 3,
                bathrooms: 2,
                sqft: 1600.0,
            },
            BuildingTemplate::SmallOffice {
                storeys: 2,
                sqft: 6000.0,
            },
            BuildingTemplate::NeighbourhoodRetail {
                sqft: 4000.0,
            },
            BuildingTemplate::CommunityAssembly {
                sqft: 4500.0,
            },
            BuildingTemplate::LightIndustrial {
                sqft: 5000.0,
            },
            BuildingTemplate::MixedUsePodium {
                retail_sqft: 3000.0,
                residential_floors: 2,
            },
            BuildingTemplate::CollegeResidence {
                floors: 3,
                rooms_per_floor: 10,
                sqft: 15_000.0,
            },
        ]
    }

    /// Expand the template into a [`ProgramManifest`].
    #[must_use]
    pub fn manifest(&self) -> ProgramManifest {
        let manifest = match self {
            BuildingTemplate::Part9House {
                bedrooms,
                bathrooms,
                sqft,
            } => part9_house(*bedrooms, *bathrooms, *sqft),
            BuildingTemplate::SmallOffice { storeys, sqft } => small_office(*storeys, *sqft),
            BuildingTemplate::NeighbourhoodRetail { sqft } => neighbourhood_retail(*sqft),
            BuildingTemplate::CommunityAssembly { sqft } => community_assembly(*sqft),
            BuildingTemplate::LightIndustrial { sqft } => light_industrial(*sqft),
            BuildingTemplate::MixedUsePodium {
                retail_sqft,
                residential_floors,
            } => mixed_use_podium(*retail_sqft, *residential_floors),
            BuildingTemplate::CollegeResidence {
                floors,
                rooms_per_floor,
                sqft,
            } => college_residence(*floors, *rooms_per_floor, *sqft),
        };
        // Templates are authored to be valid; this catches drift.
        if let Err(errors) = manifest.validate() {
            eprintln!("template validation failed: {errors:?}");
        }
        manifest
    }
}

fn part9_house(bedrooms: u32, bathrooms: u32, sqft: f32) -> ProgramManifest {
    let storeys = if sqft >= 2000.0 || bedrooms >= 3 { 2 } else { 1 };
    let mut floors = Vec::new();

    // Main floor rooms.
    let mut main_rooms = vec![
        RoomManifest {
            id: "entry".into(),
            room_type: "entry".into(),
            min_area: Some(40.0),
            ..Default::default()
        },
        RoomManifest {
            id: "living".into(),
            room_type: "living".into(),
            min_area: Some(200.0),
            ..Default::default()
        },
        RoomManifest {
            id: "dining".into(),
            room_type: "dining".into(),
            min_area: Some(120.0),
            ..Default::default()
        },
        RoomManifest {
            id: "kitchen".into(),
            room_type: "kitchen".into(),
            min_area: Some(120.0),
            ..Default::default()
        },
        RoomManifest {
            id: "primary_bedroom".into(),
            room_type: "primary_bedroom".into(),
            min_area: Some(160.0),
            ..Default::default()
        },
        RoomManifest {
            id: "primary_bath".into(),
            room_type: "primary_bath".into(),
            min_area: Some(60.0),
            ..Default::default()
        },
        RoomManifest {
            id: "stairs".into(),
            room_type: "stairs".into(),
            min_area: Some(70.0),
            ..Default::default()
        },
    ];
    if bathrooms > bedrooms {
        main_rooms.push(RoomManifest {
            id: "powder_room".into(),
            room_type: "powder_room".into(),
            min_area: Some(25.0),
            ..Default::default()
        });
    }
    floors.push(FloorManifest {
        level: 1,
        name: "Main Floor".into(),
        occupancy: None,
        rooms: main_rooms,
    });

    // Upper floor for multi-storey houses.
    if storeys > 1 {
        let mut upper_rooms = vec![
            RoomManifest {
                id: "hallway".into(),
                room_type: "hallway".into(),
                min_area: Some(50.0),
                ..Default::default()
            },
            RoomManifest {
                id: "laundry".into(),
                room_type: "laundry".into(),
                min_area: Some(40.0),
                ..Default::default()
            },
        ];
        let upper_beds = bedrooms.saturating_sub(1).max(1);
        for i in 1..=upper_beds {
            upper_rooms.push(RoomManifest {
                id: format!("bedroom_{i}"),
                room_type: "bedroom".into(),
                min_area: Some(100.0),
                ..Default::default()
            });
        }
        let upper_baths = bathrooms.saturating_sub(1).max(1);
        for i in 1..=upper_baths {
            upper_rooms.push(RoomManifest {
                id: format!("bathroom_{i}"),
                room_type: "bathroom".into(),
                min_area: Some(40.0),
                ..Default::default()
            });
        }
        floors.push(FloorManifest {
            level: 2,
            name: "Upper Floor".into(),
            occupancy: None,
            rooms: upper_rooms,
        });
    }

    ProgramManifest {
        mode: BuildingMode::Part9,
        building_name: format!("{bedrooms}-bed {bathrooms}-bath house"),
        sqft: Some(sqft),
        floor_to_floor_ft: 10.0,
        floors,
        adjacency: vec![],
    }
}

fn small_office(storeys: u32, sqft: f32) -> ProgramManifest {
    let storeys = storeys.clamp(1, 4);
    let sqft_per_floor = sqft / storeys as f32;
    let mut floors = Vec::new();
    for level in 1..=storeys {
        let is_ground = level == 1;
        let mut rooms = vec![
            RoomManifest {
                id: format!("corridor_{level}"),
                room_type: "corridor".into(),
                min_area: Some(200.0),
                ..Default::default()
            },
            RoomManifest {
                id: format!("stairs_{level}"),
                room_type: "stairs".into(),
                min_area: Some(140.0),
                ..Default::default()
            },
            RoomManifest {
                id: format!("stairs_{level}_b"),
                room_type: "stairs".into(),
                min_area: Some(140.0),
                ..Default::default()
            },
            RoomManifest {
                id: format!("elevator_{level}"),
                room_type: "elevator".into(),
                min_area: Some(25.0),
                ..Default::default()
            },
            RoomManifest {
                id: format!("washroom_{level}"),
                room_type: "washroom".into(),
                min_area: Some(80.0),
                ..Default::default()
            },
            RoomManifest {
                id: format!("office_open_{level}"),
                room_type: "office_open".into(),
                min_area: Some(sqft_per_floor * 0.55),
                ..Default::default()
            },
        ];
        if is_ground {
            rooms.push(RoomManifest {
                id: "lobby".into(),
                room_type: "lobby".into(),
                min_area: Some(200.0),
                ..Default::default()
            });
            rooms.push(RoomManifest {
                id: "reception".into(),
                room_type: "reception".into(),
                min_area: Some(100.0),
                ..Default::default()
            });
        } else {
            rooms.push(RoomManifest {
                id: format!("conf_{level}"),
                room_type: "conference".into(),
                min_area: Some(200.0),
                ..Default::default()
            });
            rooms.push(RoomManifest {
                id: format!("office_private_{level}"),
                room_type: "office_private".into(),
                min_area: Some(120.0),
                ..Default::default()
            });
        }
        floors.push(FloorManifest {
            level: level as usize,
            name: if is_ground {
                "Ground".into()
            } else {
                format!("Level {level}")
            },
            occupancy: Some("business".into()),
            rooms,
        });
    }
    ProgramManifest {
        mode: BuildingMode::Part3,
        building_name: format!("{storeys}-storey small office"),
        sqft: Some(sqft),
        floor_to_floor_ft: 12.0,
        floors,
        adjacency: vec![
            adjacency("lobby", "reception", 1.0),
            adjacency("lobby", "stairs_1", 1.0),
        ],
    }
}

fn neighbourhood_retail(sqft: f32) -> ProgramManifest {
    ProgramManifest {
        mode: BuildingMode::Part3,
        building_name: "Neighbourhood Retail".into(),
        sqft: Some(sqft),
        floor_to_floor_ft: 14.0,
        floors: vec![FloorManifest {
            level: 1,
            name: "Retail Floor".into(),
            occupancy: Some("mercantile".into()),
            rooms: vec![
                RoomManifest {
                    id: "retail_floor".into(),
                    room_type: "retail".into(),
                    min_area: Some(sqft * 0.55),
                    ..Default::default()
                },
                RoomManifest {
                    id: "stock_room".into(),
                    room_type: "storage".into(),
                    min_area: Some(400.0),
                    ..Default::default()
                },
                RoomManifest {
                    id: "washroom_a".into(),
                    room_type: "washroom".into(),
                    min_area: Some(80.0),
                    ..Default::default()
                },
                RoomManifest {
                    id: "washroom_b".into(),
                    room_type: "washroom".into(),
                    min_area: Some(80.0),
                    ..Default::default()
                },
                RoomManifest {
                    id: "mechanical".into(),
                    room_type: "mechanical".into(),
                    min_area: Some(100.0),
                    ..Default::default()
                },
                RoomManifest {
                    id: "office".into(),
                    room_type: "management_office".into(),
                    min_area: Some(120.0),
                    ..Default::default()
                },
                RoomManifest {
                    id: "stairs_1".into(),
                    room_type: "stairs".into(),
                    min_area: Some(140.0),
                    ..Default::default()
                },
                RoomManifest {
                    id: "stairs_1_b".into(),
                    room_type: "stairs".into(),
                    min_area: Some(140.0),
                    ..Default::default()
                },
            ],
        }],
        adjacency: vec![
            adjacency("retail_floor", "stock_room", 0.8),
            adjacency("retail_floor", "office", 0.6),
        ],
    }
}

fn community_assembly(sqft: f32) -> ProgramManifest {
    ProgramManifest {
        mode: BuildingMode::Part3,
        building_name: "Community Assembly Hall".into(),
        sqft: Some(sqft),
        floor_to_floor_ft: 18.0,
        floors: vec![FloorManifest {
            level: 1,
            name: "Hall Floor".into(),
            occupancy: Some("assembly".into()),
            rooms: vec![
                RoomManifest {
                    id: "lobby".into(),
                    room_type: "lobby".into(),
                    min_area: Some(300.0),
                    ..Default::default()
                },
                RoomManifest {
                    id: "foyer".into(),
                    room_type: "foyer".into(),
                    min_area: Some(200.0),
                    ..Default::default()
                },
                RoomManifest {
                    id: "auditorium".into(),
                    room_type: "auditorium".into(),
                    min_area: Some(sqft * 0.45),
                    ..Default::default()
                },
                RoomManifest {
                    id: "classroom_a".into(),
                    room_type: "classroom".into(),
                    min_area: Some(600.0),
                    ..Default::default()
                },
                RoomManifest {
                    id: "washroom_a".into(),
                    room_type: "washroom".into(),
                    min_area: Some(100.0),
                    ..Default::default()
                },
                RoomManifest {
                    id: "washroom_b".into(),
                    room_type: "washroom".into(),
                    min_area: Some(100.0),
                    ..Default::default()
                },
                RoomManifest {
                    id: "kitchenette".into(),
                    room_type: "kitchenette".into(),
                    min_area: Some(80.0),
                    ..Default::default()
                },
                RoomManifest {
                    id: "storage".into(),
                    room_type: "storage".into(),
                    min_area: Some(200.0),
                    ..Default::default()
                },
                RoomManifest {
                    id: "stairs_1".into(),
                    room_type: "stairs".into(),
                    min_area: Some(140.0),
                    ..Default::default()
                },
                RoomManifest {
                    id: "stairs_1_b".into(),
                    room_type: "stairs".into(),
                    min_area: Some(140.0),
                    ..Default::default()
                },
            ],
        }],
        adjacency: vec![
            adjacency("lobby", "foyer", 1.0),
            adjacency("lobby", "auditorium", 0.9),
            adjacency("auditorium", "classroom_a", 0.5),
        ],
    }
}

fn light_industrial(sqft: f32) -> ProgramManifest {
    ProgramManifest {
        mode: BuildingMode::Part3,
        building_name: "Light Industrial Unit".into(),
        sqft: Some(sqft),
        floor_to_floor_ft: 18.0,
        floors: vec![FloorManifest {
            level: 1,
            name: "Warehouse Floor".into(),
            occupancy: Some("industrial".into()),
            rooms: vec![
                RoomManifest {
                    id: "loading_dock".into(),
                    room_type: "loading_dock".into(),
                    min_area: Some(600.0),
                    ..Default::default()
                },
                RoomManifest {
                    id: "warehouse".into(),
                    room_type: "storage".into(),
                    min_area: Some(sqft * 0.45),
                    ..Default::default()
                },
                RoomManifest {
                    id: "office".into(),
                    room_type: "office_open".into(),
                    min_area: Some(400.0),
                    ..Default::default()
                },
                RoomManifest {
                    id: "washroom_a".into(),
                    room_type: "washroom".into(),
                    min_area: Some(80.0),
                    ..Default::default()
                },
                RoomManifest {
                    id: "washroom_b".into(),
                    room_type: "washroom".into(),
                    min_area: Some(80.0),
                    ..Default::default()
                },
                RoomManifest {
                    id: "mechanical".into(),
                    room_type: "mechanical".into(),
                    min_area: Some(120.0),
                    ..Default::default()
                },
                RoomManifest {
                    id: "electrical".into(),
                    room_type: "electrical".into(),
                    min_area: Some(60.0),
                    ..Default::default()
                },
                RoomManifest {
                    id: "janitor".into(),
                    room_type: "janitor".into(),
                    min_area: Some(40.0),
                    ..Default::default()
                },
                RoomManifest {
                    id: "stairs_1".into(),
                    room_type: "stairs".into(),
                    min_area: Some(140.0),
                    ..Default::default()
                },
                RoomManifest {
                    id: "stairs_1_b".into(),
                    room_type: "stairs".into(),
                    min_area: Some(140.0),
                    ..Default::default()
                },
            ],
        }],
        adjacency: vec![
            adjacency("loading_dock", "warehouse", 1.0),
            adjacency("warehouse", "office", 0.7),
        ],
    }
}

fn mixed_use_podium(retail_sqft: f32, residential_floors: u32) -> ProgramManifest {
    let residential_floors = residential_floors.clamp(1, 6);
    let units_per_floor = 4;
    let mut floors = Vec::new();

    // Ground retail floor.
    floors.push(FloorManifest {
        level: 1,
        name: "Retail Ground".into(),
        occupancy: Some("mercantile".into()),
        rooms: vec![
            RoomManifest {
                id: "retail_1".into(),
                room_type: "retail".into(),
                min_area: Some(retail_sqft * 0.55),
                ..Default::default()
            },
            RoomManifest {
                id: "retail_2".into(),
                room_type: "retail".into(),
                min_area: Some(retail_sqft * 0.35),
                ..Default::default()
            },
            RoomManifest {
                id: "lobby".into(),
                room_type: "lobby".into(),
                min_area: Some(200.0),
                ..Default::default()
            },
            RoomManifest {
                id: "washroom_a".into(),
                room_type: "washroom".into(),
                min_area: Some(80.0),
                ..Default::default()
            },
            RoomManifest {
                id: "washroom_b".into(),
                room_type: "washroom".into(),
                min_area: Some(80.0),
                ..Default::default()
            },
            RoomManifest {
                id: "stairs_1".into(),
                room_type: "stairs".into(),
                min_area: Some(140.0),
                ..Default::default()
            },
            RoomManifest {
                id: "stairs_1_b".into(),
                room_type: "stairs".into(),
                min_area: Some(140.0),
                ..Default::default()
            },
            RoomManifest {
                id: "elevator_1".into(),
                room_type: "elevator".into(),
                min_area: Some(25.0),
                ..Default::default()
            },
        ],
    });

    // Residential floors above.
    for floor_idx in 0..residential_floors {
        let level = floor_idx + 2;
        let mut rooms = vec![
            RoomManifest {
                id: format!("corridor_{level}"),
                room_type: "corridor".into(),
                min_area: Some(200.0),
                ..Default::default()
            },
            RoomManifest {
                id: format!("lounge_{level}"),
                room_type: "lounge".into(),
                min_area: Some(200.0),
                ..Default::default()
            },
            RoomManifest {
                id: format!("stairs_{level}"),
                room_type: "stairs".into(),
                min_area: Some(140.0),
                ..Default::default()
            },
            RoomManifest {
                id: format!("stairs_{level}_b"),
                room_type: "stairs".into(),
                min_area: Some(140.0),
                ..Default::default()
            },
            RoomManifest {
                id: format!("elevator_{level}"),
                room_type: "elevator".into(),
                min_area: Some(25.0),
                ..Default::default()
            },
        ];
        for unit in 1..=units_per_floor {
            let unit_id = format!("u{level}_{unit}");
            let (room_type, area) = match unit % 4 {
                0 => ("studio", 400.0),
                1 => ("one_bedroom", 500.0),
                2 => ("two_bedroom", 700.0),
                _ => ("one_bedroom", 500.0),
            };
            rooms.push(RoomManifest {
                id: format!("{unit_id}_living"),
                room_type: room_type.into(),
                min_area: Some(area),
                unit: Some(unit_id.clone()),
                ..Default::default()
            });
            rooms.push(RoomManifest {
                id: format!("{unit_id}_bath"),
                room_type: "washroom".into(),
                min_area: Some(50.0),
                unit: Some(unit_id),
                ..Default::default()
            });
        }
        floors.push(FloorManifest {
            level: level as usize,
            name: format!("Residential {level}"),
            occupancy: Some("residential".into()),
            rooms,
        });
    }

    ProgramManifest {
        mode: BuildingMode::Mixed,
        building_name: "Mixed-Use Retail + Residential Podium".into(),
        sqft: Some(retail_sqft + residential_floors as f32 * 4000.0),
        floor_to_floor_ft: 9.0,
        floors,
        adjacency: vec![
            adjacency("lobby", "retail_1", 0.8),
            adjacency("lobby", "retail_2", 0.8),
        ],
    }
}

#[allow(clippy::cast_precision_loss)] // room/floor counts are small integers
fn college_residence(floors: u32, rooms_per_floor: u32, sqft: f32) -> ProgramManifest {
    let floors = floors.clamp(2, 6);
    let rooms_per_floor = rooms_per_floor.clamp(4, 40);
    let typical_floor_sqft = sqft / floors as f32;
    let room_sqft = (typical_floor_sqft * 0.65 / rooms_per_floor as f32).clamp(100.0, 220.0);

    let mut floor_manifests = Vec::new();

    // Ground floor: shared amenities + two exit stairs + elevator.
    floor_manifests.push(FloorManifest {
        level: 1,
        name: "Ground Floor".into(),
        occupancy: Some("residential".into()),
        rooms: vec![
            RoomManifest {
                id: "lobby".into(),
                room_type: "lobby".into(),
                min_area: Some(300.0),
                ..Default::default()
            },
            RoomManifest {
                id: "dining_hall".into(),
                room_type: "dining_hall".into(),
                min_area: Some(1_200.0),
                ..Default::default()
            },
            RoomManifest {
                id: "common_room".into(),
                room_type: "common_room".into(),
                min_area: Some(600.0),
                ..Default::default()
            },
            RoomManifest {
                id: "stairs_1".into(),
                room_type: "stairs".into(),
                min_area: Some(140.0),
                ..Default::default()
            },
            RoomManifest {
                id: "stairs_1_b".into(),
                room_type: "stairs".into(),
                min_area: Some(140.0),
                ..Default::default()
            },
            RoomManifest {
                id: "elevator_1".into(),
                room_type: "elevator".into(),
                min_area: Some(25.0),
                ..Default::default()
            },
        ],
    });

    // Typical residential floors.
    for level in 2..=floors {
        let mut rooms = vec![
            RoomManifest {
                id: format!("corridor_{level}"),
                room_type: "corridor".into(),
                min_area: Some(400.0),
                ..Default::default()
            },
            RoomManifest {
                id: format!("lounge_{level}"),
                room_type: "lounge".into(),
                min_area: Some(250.0),
                ..Default::default()
            },
            RoomManifest {
                id: format!("study_lounge_{level}"),
                room_type: "study_lounge".into(),
                min_area: Some(250.0),
                ..Default::default()
            },
            RoomManifest {
                id: format!("shared_washroom_{level}_a"),
                room_type: "shared_washroom".into(),
                min_area: Some(120.0),
                ..Default::default()
            },
            RoomManifest {
                id: format!("shared_washroom_{level}_b"),
                room_type: "shared_washroom".into(),
                min_area: Some(120.0),
                ..Default::default()
            },
            RoomManifest {
                id: format!("stairs_{level}"),
                room_type: "stairs".into(),
                min_area: Some(140.0),
                ..Default::default()
            },
            RoomManifest {
                id: format!("stairs_{level}_b"),
                room_type: "stairs".into(),
                min_area: Some(140.0),
                ..Default::default()
            },
            RoomManifest {
                id: format!("elevator_{level}"),
                room_type: "elevator".into(),
                min_area: Some(25.0),
                ..Default::default()
            },
        ];
        for i in 1..=rooms_per_floor {
            let (room_type, area) = if i % 4 == 0 {
                ("dorm_double", room_sqft * 1.5)
            } else {
                ("dorm_single", room_sqft)
            };
            rooms.push(RoomManifest {
                id: format!("dorm_{level}_{i}"),
                room_type: room_type.into(),
                min_area: Some(area),
                ..Default::default()
            });
        }
        floor_manifests.push(FloorManifest {
            level: level as usize,
            name: format!("Residential {level}"),
            occupancy: Some("residential".into()),
            rooms,
        });
    }

    ProgramManifest {
        mode: BuildingMode::Part3,
        building_name: "College Residence".into(),
        sqft: Some(sqft),
        floor_to_floor_ft: 10.0,
        floors: floor_manifests,
        adjacency: vec![
            adjacency("lobby", "dining_hall", 1.0),
            adjacency("lobby", "common_room", 0.8),
        ],
    }
}

fn adjacency(a: &str, b: &str, weight: f32) -> AdjacencySpec {
    AdjacencySpec {
        a: a.into(),
        b: b.into(),
        weight,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn all_templates_validate() {
        for template in BuildingTemplate::all() {
            let manifest = template.manifest();
            assert!(
                manifest.validate().is_ok(),
                "{} template should validate",
                template.name()
            );
        }
    }

    #[test]
    fn college_residence_has_dorms_and_stairs() {
        let manifest = BuildingTemplate::CollegeResidence {
            floors: 3,
            rooms_per_floor: 10,
            sqft: 15_000.0,
        }
        .manifest();
        assert_eq!(manifest.mode, BuildingMode::Part3);
        assert_eq!(manifest.floors.len(), 3);
        assert!(manifest.floors.iter().any(|f| f
            .rooms
            .iter()
            .any(|r| r.room_type == "dorm_single" || r.room_type == "dorm_double")));
        assert!(manifest
            .floors
            .iter()
            .any(|f| f.rooms.iter().any(|r| r.room_type == "shared_washroom")));
        assert!(manifest
            .floors
            .iter()
            .any(|f| f.rooms.iter().any(|r| r.id == "stairs_1_b")));
    }

    #[test]
    fn small_office_has_stairs_and_corridor() {
        let manifest = BuildingTemplate::SmallOffice {
            storeys: 2,
            sqft: 6000.0,
        }
        .manifest();
        assert!(manifest
            .floors
            .iter()
            .any(|f| f.rooms.iter().any(|r| r.room_type == "stairs")));
        assert!(manifest
            .floors
            .iter()
            .any(|f| f.rooms.iter().any(|r| r.room_type == "corridor")));
    }
}
