//! Part 3 / mixed layout strategies.
//!
//! These are intentionally simpler than the Part 9 BSP suite engine: they
//! reserve a vertical circulation core, then lay out the remaining rooms with
//! a strategy matched to the floor type (corridor-spine office, open retail,
//! or residential BSP for mixed upper floors).

use crate::{
    adjacency::AdjacencyGraph,
    floors::{CoreBlock, FloorPlanInput},
    subdivide, PlacedRoom, Rect, RoomSpec, Zone,
};

/// Lay out one floor according to its strategy.
#[must_use]
pub fn layout_floor(input: &FloorPlanInput, graph: &AdjacencyGraph) -> Vec<PlacedRoom> {
    match input.strategy {
        crate::floors::FloorStrategy::ResidentialBsp => layout_residential_bsp(input, graph),
        crate::floors::FloorStrategy::CorridorSpine => layout_corridor_spine(input, graph),
        crate::floors::FloorStrategy::OpenRetail => layout_open_retail(input),
        crate::floors::FloorStrategy::CorridorResidential => layout_corridor_residential(input),
    }
}

fn mk_room(spec: &RoomSpec, rect: Rect) -> PlacedRoom {
    PlacedRoom {
        id: spec.id.clone(),
        room_type: spec.room_type.clone(),
        zone: Zone::of(&spec.room_type),
        rect,
        unit: spec.unit.clone(),
    }
}

/// Split program into core rooms (stairs/elevator/shaft) and other rooms.
fn split_core(program: &[RoomSpec]) -> (Vec<RoomSpec>, Vec<RoomSpec>) {
    program.iter().cloned().partition(|r| {
        matches!(
            r.room_type.as_str(),
            "stairs" | "elevator" | "shaft"
        )
    })
}

/// Place core rooms into the reserved core block(s). Stairs are distributed
/// one per block first so opposite-corner exits actually land in opposite
/// corners; elevators/shafts fill in afterwards.
fn place_core_rooms(placed: &mut Vec<PlacedRoom>, core_specs: &[RoomSpec], cores: &[CoreBlock]) {
    if core_specs.is_empty() || cores.is_empty() {
        return;
    }
    let mut per_core: Vec<Vec<&RoomSpec>> = vec![Vec::new(); cores.len()];

    // Stairs first, one per core, so they end up in opposite corners.
    let stairs: Vec<&RoomSpec> = core_specs.iter().filter(|r| r.room_type == "stairs").collect();
    for (i, stair) in stairs.iter().enumerate() {
        per_core[i % cores.len()].push(stair);
    }
    // Then elevators/shafts.
    for spec in core_specs.iter().filter(|r| r.room_type != "stairs") {
        // Put the next non-stair in the core with the fewest items so far.
        let idx = per_core
            .iter()
            .enumerate()
            .min_by_key(|(_, specs)| specs.len())
            .map(|(i, _)| i)
            .unwrap_or(0);
        per_core[idx].push(spec);
    }

    for (core, specs) in cores.iter().zip(per_core.iter()) {
        place_core_rooms_in_block(placed, specs, core.rect);
    }
}

fn place_core_rooms_in_block(placed: &mut Vec<PlacedRoom>, core_specs: &[&RoomSpec], core: Rect) {
    if core_specs.is_empty() || core.w <= 0.0 || core.h <= 0.0 {
        return;
    }
    let total_area: f32 = core_specs.iter().map(|r| r.min_area).sum::<f32>().max(1.0);
    let mut x = core.x;
    for spec in core_specs {
        let bw = core.w * spec.min_area / total_area;
        placed.push(mk_room(
            spec,
            Rect {
                x,
                y: core.y,
                w: bw,
                h: core.h,
            },
        ));
        x += bw;
    }
}

/// Returns the union of all core clearances plus any space between them, so
/// other rooms can treat it as a single reserved band at the front of the floor.
fn core_clearance_union(cores: &[CoreBlock], env: Rect) -> Rect {
    if cores.is_empty() {
        return Rect {
            x: env.x,
            y: env.y,
            w: 0.0,
            h: 0.0,
        };
    }
    let min_x = cores.iter().map(|c| c.clearance.x).fold(f32::INFINITY, f32::min);
    let max_x = cores
        .iter()
        .map(|c| c.clearance.x + c.clearance.w)
        .fold(f32::NEG_INFINITY, f32::max);
    let y = cores[0].clearance.y;
    let h = cores.iter().map(|c| c.clearance.h).fold(0.0, f32::max);
    Rect {
        x: min_x,
        y,
        w: max_x - min_x,
        h,
    }
}

/// Part 9 residential BSP on the envelope minus the circulation core(s).
fn layout_residential_bsp(input: &FloorPlanInput, graph: &AdjacencyGraph) -> Vec<PlacedRoom> {
    let (core_specs, other_specs) = split_core(&input.program);
    let env = input.envelope;
    let cores = &input.cores;

    // Treat the union of all cores as the reserved band on the left. For the
    // rare case of a 2-stair residential BSP floor, this keeps both stairs
    // approachable from the left while the rest of the floor subdivides to the
    // right.
    let reserved_w = cores
        .iter()
        .map(|c| c.rect.x + c.rect.w)
        .fold(0.0, f32::max);
    let usable = Rect {
        x: env.x + reserved_w,
        y: env.y,
        w: env.w - reserved_w,
        h: env.h,
    };
    let mut placed = if other_specs.is_empty() {
        Vec::new()
    } else {
        subdivide(usable, &other_specs, "south", "switchback", graph)
    };
    place_core_rooms(&mut placed, &core_specs, cores);
    placed
}

/// Part 3 office: circulation core(s) at the front (opposite corners when 2+
/// stairs), a full-width corridor spine connecting them, and vertical bays for
/// the remaining rooms above the corridor.
fn layout_corridor_spine(input: &FloorPlanInput, _graph: &AdjacencyGraph) -> Vec<PlacedRoom> {
    let (core_specs, other_specs) = split_core(&input.program);
    let env = input.envelope;
    let cores = &input.cores;

    let mut placed = Vec::new();
    place_core_rooms(&mut placed, &core_specs, cores);

    // Corridor height: ~8 ft clear, capped at 15% of floor depth. The corridor
    // must also swallow the core clearance landing so every stair remains
    // accessible from the approach side. Place the corridor so its top edge
    // touches the bottom of the shallowest core (i.e. it fills the clearance
    // band), not below the clearance band where stairs would be isolated.
    let clearance_union = core_clearance_union(cores, env);
    let corridor_h = (env.h * 0.12)
        .clamp(6.0, 12.0)
        .max(clearance_union.h);
    let corridor_y = if cores.is_empty() {
        env.y
    } else {
        cores
            .iter()
            .map(|c| c.rect.y + c.rect.h)
            .fold(f32::INFINITY, f32::min)
    };
    let remaining_h = env.h - (corridor_y - env.y) - corridor_h;

    let corridor_pos = other_specs
        .iter()
        .position(|r| r.room_type == "corridor" || r.room_type == "hallway")
        // A lobby can serve as the stair landing / approach zone when no explicit
        // corridor is provided (common on mixed-use ground floors).
        .or_else(|| other_specs.iter().position(|r| r.room_type == "lobby"));
    let corridor_spec = if let Some(pos) = corridor_pos {
        Some(other_specs[pos].clone())
    } else if !other_specs.is_empty() || cores.len() >= 2 {
        // Inject a corridor so every room can reach the stair core(s).
        Some(RoomSpec {
            id: format!("corridor_{}_auto", input.level),
            room_type: "corridor".into(),
            weight: 1.0,
            min_area: 120.0,
            unit: None,
        })
    } else {
        None
    };
    let other_without_corridor: Vec<RoomSpec> = other_specs
        .iter()
        .enumerate()
        .filter(|(i, _)| Some(*i) != corridor_pos)
        .map(|(_, r)| r.clone())
        .collect();

    if let Some(spec) = corridor_spec {
        placed.push(mk_room(
            &spec,
            Rect {
                x: env.x,
                y: corridor_y,
                w: env.w,
                h: corridor_h,
            },
        ));
    }

    if remaining_h > 0.0 && !other_without_corridor.is_empty() {
        let upper = Rect {
            x: env.x,
            y: corridor_y + corridor_h,
            w: env.w,
            h: remaining_h,
        };
        tile_bays(&mut placed,
            &other_without_corridor,
            upper,
            true, // bays run full depth of the upper band
        );
    }

    placed
}

/// Part 3 multi-unit residential: circulation core(s) at the front, a
/// full-width corridor spine connecting them, and bays opening off the corridor.
/// Rooms sharing a `unit` id are grouped into the same bay; every other room
/// becomes its own corridor-facing bay so dorm-style floors (bedrooms off a
/// common hall) are reachable without long rear service bands.
fn layout_corridor_residential(input: &FloorPlanInput) -> Vec<PlacedRoom> {
    let (core_specs, other_specs) = split_core(&input.program);
    let env = input.envelope;
    let cores = &input.cores;

    let mut placed = Vec::new();
    place_core_rooms(&mut placed, &core_specs, cores);

    // Corridor runs full width just below the core(s), deep enough to serve as
    // the stair landing / approach zone for both cores. Its top edge must
    // touch the bottom of the shallowest core so stairs open directly onto the
    // corridor; the depth is at least the landing clearance height.
    let clearance_union = core_clearance_union(cores, env);
    let corridor_h = (env.h * 0.12)
        .clamp(6.0, 12.0)
        .max(clearance_union.h);
    let corridor_y = if cores.is_empty() {
        env.y
    } else {
        cores
            .iter()
            .map(|c| c.rect.y + c.rect.h)
            .fold(f32::INFINITY, f32::min)
    };
    let corridor_spec = other_specs
        .iter()
        .find(|r| r.room_type == "corridor" || r.room_type == "hallway");
    if let Some(spec) = corridor_spec {
        placed.push(mk_room(
            spec,
            Rect {
                x: env.x,
                y: corridor_y,
                w: env.w,
                h: corridor_h,
            },
        ));
    }

    let usable_top = corridor_y + corridor_h;
    let usable_h = env.h - (usable_top - env.y);
    if usable_h <= 0.0 {
        return placed;
    }

    // Group rooms with a unit id; every other room becomes its own bay so it
    // opens directly off the corridor. This keeps dorm-style bedrooms close to
    // the exit stairs instead of pushing them to a distant rear service band.
    let mut unit_map: std::collections::HashMap<Option<String>, Vec<&RoomSpec>> =
        std::collections::HashMap::new();
    let mut bays: Vec<Vec<&RoomSpec>> = Vec::new();
    for spec in &other_specs {
        if spec.room_type == "corridor" || spec.room_type == "hallway" {
            continue;
        }
        if spec.unit.is_some() {
            unit_map.entry(spec.unit.clone()).or_default().push(spec);
        } else {
            bays.push(vec![spec]);
        }
    }
    for unit in unit_map.values() {
        bays.push(unit.clone());
    }

    if bays.is_empty() {
        return placed;
    }

    let unit_band = Rect {
        x: env.x,
        y: usable_top,
        w: env.w,
        h: usable_h,
    };
    let total_bay_area: f32 = bays
        .iter()
        .map(|b| b.iter().map(|r| r.min_area).sum::<f32>())
        .sum::<f32>()
        .max(1.0);

    let mut x = unit_band.x;
    for bay_specs in bays {
        let bay_area: f32 = bay_specs.iter().map(|r| r.min_area).sum();
        let bw = unit_band.w * bay_area / total_bay_area;
        let bay = Rect {
            x,
            y: unit_band.y,
            w: bw,
            h: unit_band.h,
        };
        if bay_specs.len() == 1 {
            placed.push(mk_room(bay_specs[0], bay));
        } else {
            // Split the unit's rooms horizontally across the bay; each room is
            // full depth so every room in the unit touches the corridor.
            tile_bays(
                &mut placed,
                &bay_specs.iter().copied().cloned().collect::<Vec<_>>(),
                bay,
                false,
            );
        }
        x += bw;
    }

    placed
}

/// Part 3 retail: circulation core(s) at the front (opposite corners when 2+
/// stairs), one large open retail space flowing between/behind them, and
/// service rooms tucked into the remaining rear band.
fn layout_open_retail(input: &FloorPlanInput) -> Vec<PlacedRoom> {
    let (core_specs, other_specs) = split_core(&input.program);
    let env = input.envelope;
    let cores = &input.cores;

    let mut placed = Vec::new();
    place_core_rooms(&mut placed, &core_specs, cores);

    let retail_pos = other_specs
        .iter()
        .position(|r| r.room_type == "retail" || r.room_type == "restaurant");
    let retail_spec = retail_pos.map(|i| other_specs[i].clone());
    let service_specs: Vec<RoomSpec> = other_specs
        .iter()
        .enumerate()
        .filter(|(i, _)| Some(*i) != retail_pos)
        .map(|(_, r)| r.clone())
        .collect();

    // Open-plan floors need a circulation band that connects the core(s) to
    // the big retail space and any service rooms at the rear. If the manifest
    // already supplies a corridor/hallway/lobby we use it; otherwise inject a
    // small corridor so the egress graph can reach every room.
    let corridor_pos = service_specs
        .iter()
        .position(|r| r.room_type == "corridor" || r.room_type == "hallway" || r.room_type == "lobby");
    let (corridor_spec, service_without_corridor): (Option<RoomSpec>, Vec<RoomSpec>) =
        if let Some(pos) = corridor_pos {
            let mut rest = service_specs.clone();
            let c = rest.remove(pos);
            (Some(c), rest)
        } else if !service_specs.is_empty() || cores.len() >= 2 {
            let c = RoomSpec {
                id: format!("corridor_{}_auto", input.level),
                room_type: "corridor".into(),
                weight: 1.0,
                min_area: 120.0,
                unit: None,
            };
            (Some(c), service_specs.clone())
        } else {
            (None, service_specs.clone())
        };

    // Place the corridor in the core clearance band, touching the bottom of
    // the shallowest core. This is the same rule used by corridor_spine and
    // corridor_residential so stairs always open onto circulation.
    let corridor_y = if cores.is_empty() {
        env.y
    } else {
        cores
            .iter()
            .map(|c| c.rect.y + c.rect.h)
            .fold(f32::INFINITY, f32::min)
    };
    let clearance_h = core_clearance_union(cores, env).h;
    let corridor_h = (env.h * 0.12).clamp(6.0, 12.0).max(clearance_h);

    if let Some(spec) = corridor_spec {
        placed.push(mk_room(
            &spec,
            Rect {
                x: env.x,
                y: corridor_y,
                w: env.w,
                h: corridor_h,
            },
        ));
    }

    // Service band at the rear. Height ~15% of floor depth, capped so it never
    // swallows the corridor/retail entirely.
    let service_band_h = if service_without_corridor.is_empty() {
        0.0
    } else {
        (env.h * 0.15).clamp(8.0, 18.0)
    };

    // Retail sits between the corridor and the service band. If there is no
    // corridor (no cores, no service rooms) it occupies the whole envelope.
    let retail_top = corridor_y + corridor_h;
    let retail_bottom = (env.y + env.h - service_band_h).min(env.y + env.h);
    let retail_h = (retail_bottom - retail_top).max(0.0);

    if let Some(spec) = retail_spec {
        if retail_h > 0.0 {
            placed.push(mk_room(
                &spec,
                Rect {
                    x: env.x,
                    y: retail_top,
                    w: env.w,
                    h: retail_h,
                },
            ));
        }
    }

    if service_band_h > 0.0 {
        let service_y = retail_top + retail_h;
        let service_h = (env.y + env.h - service_y).max(0.0);
        if service_h > 0.0 {
            let service_band = Rect {
                x: env.x,
                y: service_y,
                w: env.w,
                h: service_h,
            };
            tile_bays(&mut placed, &service_without_corridor, service_band, false);
        }
    }

    placed
}

/// Tile rooms as vertical bays across a region. If `full_depth` is true each
/// bay is a single room filling the region depth; otherwise rooms are stacked
/// within each bay.
fn tile_bays(placed: &mut Vec<PlacedRoom>, specs: &[RoomSpec], region: Rect, full_depth: bool) {
    if specs.is_empty() || region.w <= 0.0 || region.h <= 0.0 {
        return;
    }
    let total_area: f32 = specs.iter().map(|r| r.min_area).sum::<f32>().max(1.0);
    let region_area = region.w * region.h;
    let mut x = region.x;
    for spec in specs {
        let area = spec.min_area.max(1.0);
        let bw = region.w * area / total_area;
        if full_depth {
            placed.push(mk_room(
                spec,
                Rect {
                    x,
                    y: region.y,
                    w: bw,
                    h: region.h,
                },
            ));
        } else {
            let bay_area = region_area * area / total_area;
            let bh = (bay_area / bw).clamp(1.0, region.h);
            placed.push(mk_room(
                spec,
                Rect {
                    x,
                    y: region.y,
                    w: bw,
                    h: bh,
                },
            ));
        }
        x += bw;
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::floors::{plan_floors, FloorStrategy};
    use crate::manifest::ProgramManifest;
    use crate::mode::BuildingMode;

    #[test]
    fn corridor_spine_places_corridor_and_bays() {
        let manifest = ProgramManifest::from_json(
            r#"{
                "mode": "part3",
                "sqft": 4000,
                "floors": [
                    {
                        "level": 1,
                        "rooms": [
                            {"id": "lobby", "room_type": "lobby", "min_area": 200},
                            {"id": "corridor", "room_type": "corridor", "min_area": 150},
                            {"id": "stairs_1", "room_type": "stairs", "min_area": 120},
                            {"id": "office_open", "room_type": "office_open", "min_area": 1000},
                            {"id": "washroom_1", "room_type": "washroom", "min_area": 80}
                        ]
                    }
                ]
            }"#,
        )
        .unwrap();
        let plans = plan_floors(&manifest);
        let graph = AdjacencyGraph::new_for_mode(BuildingMode::Part3).with_manifest(&manifest);
        let placed = layout_floor(&plans[0], &graph);
        assert!(placed.iter().any(|r| r.room_type == "corridor"));
        assert!(placed.iter().any(|r| r.room_type == "office_open"));
        assert!(placed.iter().any(|r| r.room_type == "stairs"));
    }

    #[test]
    fn open_retail_places_large_retail() {
        let manifest = ProgramManifest::from_json(
            r#"{
                "mode": "part3",
                "sqft": 3000,
                "floors": [
                    {
                        "level": 1,
                        "rooms": [
                            {"id": "retail_1", "room_type": "retail", "min_area": 1800},
                            {"id": "lobby", "room_type": "lobby", "min_area": 150},
                            {"id": "stairs_1", "room_type": "stairs", "min_area": 120},
                            {"id": "washroom_1", "room_type": "washroom", "min_area": 80}
                        ]
                    }
                ]
            }"#,
        )
        .unwrap();
        let plans = plan_floors(&manifest);
        let graph = AdjacencyGraph::new_for_mode(BuildingMode::Part3).with_manifest(&manifest);
        let placed = layout_floor(&plans[0], &graph);
        let retail = placed.iter().find(|r| r.room_type == "retail").unwrap();
        assert!(retail.rect.area() > 600.0, "retail should be the dominant room");
        assert!(
            placed.iter().any(|r| {
                matches!(r.room_type.as_str(), "corridor" | "hallway" | "lobby")
            }),
            "open retail with service rooms should have a circulation room"
        );
    }

    #[test]
    fn corridor_residential_groups_units() {
        let manifest = ProgramManifest::from_json(
            r#"{
                "mode": "part3",
                "sqft": 6000,
                "floors": [
                    {
                        "level": 1,
                        "rooms": [
                            {"id": "corridor", "room_type": "corridor", "min_area": 200},
                            {"id": "stairs_1", "room_type": "stairs", "min_area": 120},
                            {"id": "elevator_1", "room_type": "elevator", "min_area": 25},
                            {"id": "u1_living", "room_type": "one_bedroom", "min_area": 500, "unit": "u1"},
                            {"id": "u1_bath", "room_type": "washroom", "min_area": 80, "unit": "u1"},
                            {"id": "u2_living", "room_type": "one_bedroom", "min_area": 500, "unit": "u2"},
                            {"id": "u2_bath", "room_type": "washroom", "min_area": 80, "unit": "u2"},
                            {"id": "common", "room_type": "common_room", "min_area": 300}
                        ]
                    }
                ]
            }"#,
        )
        .unwrap();
        let plans = plan_floors(&manifest);
        assert_eq!(plans[0].strategy, FloorStrategy::CorridorResidential);
        let graph = AdjacencyGraph::new_for_mode(BuildingMode::Part3).with_manifest(&manifest);
        let placed = layout_floor(&plans[0], &graph);
        assert!(placed.iter().any(|r| r.room_type == "corridor"));
        assert!(placed.iter().any(|r| r.room_type == "common_room"));
        assert!(placed.iter().any(|r| r.room_type == "one_bedroom"));
        assert!(placed.iter().any(|r| r.room_type == "washroom"));
        // Two distinct one-bedroom rooms should be placed.
        let bedrooms: Vec<_> = placed.iter().filter(|r| r.room_type == "one_bedroom").collect();
        assert_eq!(bedrooms.len(), 2);
    }
}
