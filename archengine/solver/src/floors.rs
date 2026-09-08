//! Floor strategy selection from a manifest.
//!
//! Takes a [`ProgramManifest`] and decides, for each floor, which layout
//! strategy to use and what envelope it gets. Mixed-use buildings get a Part 3
//! podium strategy on lower floors and Part 9 residential above; vertical
//! circulation cores are aligned by reserving the same core bay on every floor.

use crate::{
    manifest::{FloorManifest, ProgramManifest, RoomManifest},
    mode::BuildingMode,
    Rect, RoomSpec,
};

/// How a single floor should be laid out.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FloorStrategy {
    /// Standard Part 9 residential BSP suite layout.
    ResidentialBsp,
    /// Part 3 office / business: central corridor with rooms on both sides.
    CorridorSpine,
    /// Part 3 retail / restaurant: one large open space plus service rooms.
    OpenRetail,
    /// Part 3 multi-unit residential: corridor spine with apartment-unit bays.
    CorridorResidential,
}

/// One circulation core block (stairs/elevator/shaft cluster) with its
/// landing clearance. Mid-rise floors may have two blocks at opposite corners
/// so exits are distributed instead of clustered.
#[derive(Debug, Clone, Copy)]
pub struct CoreBlock {
    pub rect: Rect,
    pub clearance: Rect,
}

/// One floor ready for layout.
#[derive(Debug, Clone)]
pub struct FloorPlanInput {
    pub level: usize,
    pub name: String,
    pub occupancy: Option<String>,
    pub mode: BuildingMode,
    pub program: Vec<RoomSpec>,
    pub envelope: Rect,
    pub strategy: FloorStrategy,
    /// Reserved circulation core(s). Usually one; mid-rise buildings with 2+
    /// stairs get two blocks at opposite front corners so the corridor spine
    /// can connect them.
    pub cores: Vec<CoreBlock>,
}

/// Minimum landing depth in front of a stair, in feet. OBC requires a landing
/// at least as long as the stair width; we use 40" (~3.33 ft) as a practical
/// minimum approach depth.
const STAIR_LANDING_DEPTH_FT: f32 = 40.0 / 12.0;
/// Build per-floor plan inputs from a manifest.
#[must_use]
pub fn plan_floors(manifest: &ProgramManifest) -> Vec<FloorPlanInput> {
    // The footprint is the plate size for a single floor. `sqft` in the manifest
    // is the total across storeys, so the per-floor target is total / storeys.
    // We also ensure the plate is large enough for the biggest floor's program.
    let floor_areas: Vec<f32> = manifest
        .floors
        .iter()
        .map(|f| f.rooms.iter().map(|r| r.min_area.unwrap_or(0.0)).sum::<f32>())
        .collect();
    let total_sqft: f32 = floor_areas.iter().copied().sum();
    let requested = manifest.sqft.unwrap_or(total_sqft);
    #[allow(clippy::cast_precision_loss)]
    let requested_per_floor = requested / manifest.floors.len() as f32;
    let max_floor_area = floor_areas.iter().copied().fold(0.0, f32::max);
    let footprint = requested_per_floor.max(max_floor_area);

    // Choose a footprint shape. For Part 3 / mixed we use a squarer aspect
    // than the Part 9 golden ratio because commercial floor plates are usually
    // closer to square.
    let (w, d) = shape_envelope(footprint, manifest.mode);
    let envelope = Rect { x: 0.0, y: 0.0, w, h: d };

    // Mid-rise buildings need a minimum number of stairs/elevators per floor
    // even if the manifest omits them. Compute once so the core and the
    // injected rooms stay consistent.
    let (required_stairs, required_elevators) = required_circulation_counts(manifest);

    // Reserve vertical circulation core(s) on every floor. Their size and
    // count are the same on every floor so stairs/elevators align; they are
    // subtracted from the envelope before the rest of the rooms are laid out.
    let cores = circulation_cores(manifest, envelope, required_stairs, required_elevators);

    manifest
        .floors
        .iter()
        .map(|floor| {
            // Resolve the effective mode first (occupancy overrides room-type
            // heuristics in mixed buildings), then choose a strategy consistent
            // with that mode.
            let mode = floor_mode(manifest.mode, floor);
            let strategy = choose_strategy(mode, floor, required_stairs);
            let mut program: Vec<RoomSpec> = floor
                .rooms
                .iter()
                .map(|r| room_manifest_to_spec(r, mode))
                .collect();
            inject_circulation_rooms(
                &mut program,
                floor.level,
                mode,
                required_stairs,
                required_elevators,
            );
            FloorPlanInput {
                level: floor.level,
                name: floor.name.clone(),
                occupancy: floor.occupancy.clone(),
                mode,
                program,
                envelope,
                strategy,
                cores: cores.clone(),
            }
        })
        .collect()
}

fn room_manifest_to_spec(r: &RoomManifest, mode: BuildingMode) -> RoomSpec {
    use crate::catalog::RoomCatalog;
    let cat = RoomCatalog::for_mode(mode);
    let entry = cat.get(&r.room_type);
    RoomSpec {
        id: r.id.clone(),
        room_type: r.room_type.clone(),
        weight: r.weight.unwrap_or_else(|| entry.map_or(1.0, |e| e.default_weight)),
        min_area: r.min_area.unwrap_or_else(|| entry.map_or(50.0, |e| e.default_min_area)),
        unit: r.unit.clone(),
    }
}

fn shape_envelope(footprint: f32, mode: BuildingMode) -> (f32, f32) {
    let ratio = match mode {
        BuildingMode::Part9 => 1.4,
        BuildingMode::Part3 | BuildingMode::Mixed => 1.15,
    };
    let depth = (footprint / ratio).sqrt();
    let width = footprint / depth;
    (width.round(), depth.round())
}

fn choose_strategy(mode: BuildingMode, floor: &FloorManifest, required_stairs: usize) -> FloorStrategy {
    let has_apartment_units = floor.rooms.iter().any(is_apartment_room_type);
    let is_dorm_style = floor
        .rooms
        .iter()
        .filter(|r| r.room_type == "bedroom")
        .count()
        >= 4;

    // Apartment-unit floors and dorm-style residential floors with 2+ required
    // stairs get a corridor-residential layout so the hallway can connect
    // opposite-corner stairs to every room. Office / retail floors with a
    // corridor fall through to the normal Part 3 strategy.
    if has_apartment_units || (is_dorm_style && required_stairs >= 2) {
        return FloorStrategy::CorridorResidential;
    }
    match mode {
        BuildingMode::Part9 => FloorStrategy::ResidentialBsp,
        BuildingMode::Part3 => part3_strategy(floor),
        BuildingMode::Mixed => {
            if is_residential_floor(floor) {
                FloorStrategy::ResidentialBsp
            } else {
                part3_strategy(floor)
            }
        }
    }
}

fn part3_strategy(floor: &FloorManifest) -> FloorStrategy {
    let has_open_retail = floor
        .rooms
        .iter()
        .any(|r| r.room_type == "retail" || r.room_type == "restaurant");
    let has_corridor = floor.rooms.iter().any(|r| r.room_type == "corridor" || r.room_type == "hallway");
    if has_open_retail && !has_corridor {
        FloorStrategy::OpenRetail
    } else {
        FloorStrategy::CorridorSpine
    }
}

fn is_apartment_room_type(r: &RoomManifest) -> bool {
    matches!(
        r.room_type.as_str(),
        "studio" | "one_bedroom" | "two_bedroom" | "three_bedroom" | "suite"
    )
}

fn is_residential_floor(floor: &FloorManifest) -> bool {
    floor
        .rooms
        .iter()
        .any(|r| {
            r.room_type.contains("bedroom")
                || r.room_type == "living"
                || r.room_type == "kitchen"
                || is_apartment_room_type(r)
        })
}

fn floor_mode(building_mode: BuildingMode, floor: &FloorManifest) -> BuildingMode {
    match building_mode {
        BuildingMode::Part9 | BuildingMode::Part3 => building_mode,
        BuildingMode::Mixed => {
            // Honour an explicit occupancy annotation first so a mixed-use
            // podium floor with a commercial kitchen/dining still routes through
            // the Part 3 layout engine.
            if let Some(ref occ) = floor.occupancy {
                match occ.as_str() {
                    "business"
                    | "mercantile"
                    | "assembly"
                    | "institutional"
                    | "industrial"
                    | "storage" => return BuildingMode::Part3,
                    "residential" => return BuildingMode::Part9,
                    _ => {}
                }
            }
            if is_residential_floor(floor) {
                BuildingMode::Part9
            } else {
                BuildingMode::Part3
            }
        }
    }
}

/// Minimum required number of stairs and elevators for the whole building.
///
/// Part 3 / mixed buildings with 4+ storeys need at least 2 exits per floor
/// (stairs) and at least 1 elevator. If the manifest already provides more,
/// we keep the higher count so the core sizes to the busiest floor.
fn required_circulation_counts(manifest: &ProgramManifest) -> (usize, usize) {
    let mut max_stairs = 0usize;
    let mut max_elevators = 0usize;
    for floor in &manifest.floors {
        let stairs = floor.rooms.iter().filter(|r| r.room_type == "stairs").count();
        let elevators = floor.rooms.iter().filter(|r| r.room_type == "elevator").count();
        max_stairs = max_stairs.max(stairs);
        max_elevators = max_elevators.max(elevators);
    }

    if manifest.floors.len() >= 4 {
        max_stairs = max_stairs.max(2);
        max_elevators = max_elevators.max(1);
    }

    (max_stairs, max_elevators)
}

/// Inject missing stair/elevator rooms into a floor program so every floor
/// meets the required circulation count. The injected rooms get sensible
/// default areas from the catalog (or match the largest existing stair/elevator
/// on that floor) and unique ids like `stairs_2_auto_1`.
fn inject_circulation_rooms(
    program: &mut Vec<RoomSpec>,
    level: usize,
    mode: BuildingMode,
    required_stairs: usize,
    required_elevators: usize,
) {
    use crate::catalog::RoomCatalog;
    let cat = RoomCatalog::for_mode(mode);

    let existing_stair_areas: Vec<f32> = program
        .iter()
        .filter(|r| r.room_type == "stairs")
        .map(|r| r.min_area)
        .collect();
    let existing_elevator_areas: Vec<f32> = program
        .iter()
        .filter(|r| r.room_type == "elevator")
        .map(|r| r.min_area)
        .collect();

    let stair_area = existing_stair_areas
        .iter()
        .copied()
        .fold(cat.get("stairs").map_or(120.0, |e| e.default_min_area), f32::max)
        .max(1.0);
    for i in 0..required_stairs.saturating_sub(existing_stair_areas.len()) {
        program.push(RoomSpec {
            id: format!("stairs_{level}_auto_{}", i + 1),
            room_type: "stairs".into(),
            weight: 1.0,
            min_area: stair_area,
            unit: None,
        });
    }

    let elevator_area = existing_elevator_areas
        .iter()
        .copied()
        .fold(cat.get("elevator").map_or(25.0, |e| e.default_min_area), f32::max)
        .max(1.0);
    for i in 0..required_elevators.saturating_sub(existing_elevator_areas.len()) {
        program.push(RoomSpec {
            id: format!("elevator_{level}_auto_{}", i + 1),
            room_type: "elevator".into(),
            weight: 1.0,
            min_area: elevator_area,
            unit: None,
        });
    }
}

/// Reserved circulation core(s) (stairs + elevator + shaft) plus landing
/// clearance zones. Cores are pinned to the front of the envelope; when 2+
/// stairs are required they split to opposite front corners so the corridor
/// spine can connect them. If the manifest has no circulation rooms and the
/// building is low-rise, the returned vector is empty and layout uses the full
/// envelope.
///
/// `required_stairs`/`required_elevators` come from
/// [`required_circulation_counts`] and already include mid-rise minimums.
fn circulation_cores(
    manifest: &ProgramManifest,
    envelope: Rect,
    required_stairs: usize,
    required_elevators: usize,
) -> Vec<CoreBlock> {
    if required_stairs == 0 && required_elevators == 0 {
        return Vec::new();
    }

    let (stair_w, stair_d) = stair_core_size_ft(manifest.mode);

    // Count the maximum number of shafts on any single floor.
    let max_shafts = manifest
        .floors
        .iter()
        .map(|f| f.rooms.iter().filter(|r| r.room_type == "shaft").count())
        .max()
        .unwrap_or(0);

    // Landing / approach clearance depth below each core. The corridor that
    // runs in front of the core provides the actual approach width; the depth
    // should be at least the stair width plus 40" when the floor plate allows,
    // but never more than a quarter of the floor depth so small buildings don't
    // disappear.
    let landing_depth = if required_stairs > 0 {
        (stair_w + STAIR_LANDING_DEPTH_FT).min(envelope.h * 0.25)
    } else {
        0.0
    }
    .max(0.0);

    // Single core: everything sits in one front-left block.
    if required_stairs <= 1 {
        let core_w = (required_stairs as f32 * stair_w)
            + (required_elevators as f32 * 5.0)
            + (max_shafts as f32 * 4.0);
        let core_d = stair_d.max(if required_elevators > 0 { 5.0 } else { 0.0 });
        let total_w = core_w.min(envelope.w * 0.35);
        let total_d = core_d.max(5.0).min(envelope.h * 0.35);
        if total_w <= 0.0 || total_d <= 0.0 {
            return Vec::new();
        }
        let core = Rect {
            x: envelope.x,
            y: envelope.y,
            w: total_w,
            h: total_d,
        };
        let clearance = Rect {
            x: envelope.x,
            y: envelope.y + total_d,
            w: total_w,
            h: landing_depth,
        };
        return vec![CoreBlock { rect: core, clearance }];
    }

    // Two+ stairs: split them into two front-corner cores so a corridor can
    // connect opposite exits. Each core gets one stair plus its share of
    // elevators/shafts. Keep the total frontage bounded but leave enough room
    // for the core contents in smaller footprints.
    let elevators_per_core = (required_elevators as f32 / 2.0).ceil() as usize;
    let shafts_per_core = (max_shafts as f32 / 2.0).ceil() as usize;
    let half_w = (stair_w
        + (elevators_per_core as f32 * 5.0)
        + (shafts_per_core as f32 * 4.0))
    .min(envelope.w * 0.40);
    let core_d = stair_d.max(if required_elevators > 0 { 5.0 } else { 0.0 });
    let total_d = core_d.max(5.0).min(envelope.h * 0.35);
    if half_w <= 0.0 || total_d <= 0.0 {
        return Vec::new();
    }

    let left = Rect {
        x: envelope.x,
        y: envelope.y,
        w: half_w,
        h: total_d,
    };
    let right = Rect {
        x: envelope.x + envelope.w - half_w,
        y: envelope.y,
        w: half_w,
        h: total_d,
    };
    vec![
        CoreBlock {
            rect: left,
            clearance: Rect {
                x: left.x,
                y: left.y + left.h,
                w: left.w,
                h: landing_depth,
            },
        },
        CoreBlock {
            rect: right,
            clearance: Rect {
                x: right.x,
                y: right.y + right.h,
                w: right.w,
                h: landing_depth,
            },
        },
    ]
}

/// Stair-core footprint in feet. Part 3 / mixed public stairs need a wider
/// and deeper bay than Part 9 private stairs so the clear width meets the
/// 1100 mm Business minimum and a switchback flight can fit the longer
/// public-stair going.
fn stair_core_size_ft(mode: BuildingMode) -> (f32, f32) {
    match mode {
        BuildingMode::Part9 => (7.0, 10.0),
        BuildingMode::Part3 | BuildingMode::Mixed => (10.0, 14.0),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample_office_manifest() -> ProgramManifest {
        ProgramManifest::from_json(
            r#"{
                "mode": "part3",
                "building_name": "Office",
                "sqft": 5000,
                "floors": [
                    {
                        "level": 1,
                        "name": "Ground",
                        "occupancy": "business",
                        "rooms": [
                            {"id": "lobby", "room_type": "lobby", "min_area": 200},
                            {"id": "corridor", "room_type": "corridor", "min_area": 150},
                            {"id": "stairs_1", "room_type": "stairs", "min_area": 120},
                            {"id": "elevator_1", "room_type": "elevator", "min_area": 25},
                            {"id": "office_open", "room_type": "office_open", "min_area": 1200},
                            {"id": "washroom_1", "room_type": "washroom", "min_area": 80}
                        ]
                    }
                ]
            }"#,
        )
        .unwrap()
    }

    #[test]
    fn plan_floors_makes_corridor_spine_for_office() {
        let manifest = sample_office_manifest();
        let plans = plan_floors(&manifest);
        assert_eq!(plans.len(), 1);
        assert_eq!(plans[0].strategy, FloorStrategy::CorridorSpine);
        assert!(!plans[0].cores.is_empty());
        assert!(plans[0].cores[0].rect.w > 0.0);
        assert!(plans[0].cores[0].rect.h > 0.0);
    }

    #[test]
    fn plan_floors_makes_open_retail_for_retail_floor() {
        let manifest = ProgramManifest::from_json(
            r#"{
                "mode": "part3",
                "floors": [
                    {
                        "level": 1,
                        "rooms": [
                            {"id": "retail_1", "room_type": "retail", "min_area": 1500},
                            {"id": "lobby", "room_type": "lobby", "min_area": 200},
                            {"id": "stairs_1", "room_type": "stairs", "min_area": 120},
                            {"id": "washroom_1", "room_type": "washroom", "min_area": 80}
                        ]
                    }
                ]
            }"#,
        )
        .unwrap();
        let plans = plan_floors(&manifest);
        assert_eq!(plans[0].strategy, FloorStrategy::OpenRetail);
    }

    #[test]
    fn mid_rise_core_scales_with_multiple_stairs_and_elevators() {
        let manifest = ProgramManifest::from_json(
            r#"{
                "mode": "part3",
                "sqft": 12000,
                "floors": [
                    {"level": 1, "rooms": [
                        {"id": "lobby", "room_type": "lobby", "min_area": 300},
                        {"id": "corridor", "room_type": "corridor", "min_area": 200},
                        {"id": "stairs_1", "room_type": "stairs", "min_area": 120},
                        {"id": "stairs_2", "room_type": "stairs", "min_area": 120},
                        {"id": "elevator_1", "room_type": "elevator", "min_area": 25},
                        {"id": "elevator_2", "room_type": "elevator", "min_area": 25},
                        {"id": "office_open", "room_type": "office_open", "min_area": 2000}
                    ]}
                ]
            }"#,
        )
        .unwrap();
        let plans = plan_floors(&manifest);
        let total_core_w: f32 = plans[0].cores.iter().map(|c| c.rect.w).sum();
        // Two 10-ft stairs + two 5-ft elevators = at least 30 ft wide total.
        assert!(
            total_core_w >= 30.0,
            "cores should be wide enough for 2 stairs + 2 elevators, got {}",
            total_core_w
        );
    }

    #[test]
    fn tall_building_enforces_minimum_core() {
        let floors: Vec<String> = (1..=6)
            .map(|i| {
                format!(
                    r#"{{"level": {i}, "rooms": [
                        {{"id": "corridor_{i}", "room_type": "corridor", "min_area": 200}},
                        {{"id": "stairs_{i}", "room_type": "stairs", "min_area": 120}},
                        {{"id": "u{i}_a", "room_type": "one_bedroom", "min_area": 500, "unit": "u{i}_a"}}
                    ]}}"#
                )
            })
            .collect();
        let json = format!(
            r#"{{"mode": "part3", "sqft": 8000, "floors": [{}]}}"#,
            floors.join(",")
        );
        let manifest = ProgramManifest::from_json(&json).unwrap();
        let plans = plan_floors(&manifest);
        let total_core_w: f32 = plans[0].cores.iter().map(|c| c.rect.w).sum();
        // Minimum 2 stairs + 1 elevator enforced for 4+ storeys.
        assert!(
            total_core_w >= 25.0,
            "6-storey cores should fit at least 2 stairs + 1 elevator, got {}",
            total_core_w
        );
    }

    #[test]
    fn tall_building_injects_second_stair_and_elevator_when_missing() {
        let floors: Vec<String> = (1..=6)
            .map(|i| {
                format!(
                    r#"{{"level": {i}, "rooms": [
                        {{"id": "corridor_{i}", "room_type": "corridor", "min_area": 200}},
                        {{"id": "stairs_{i}", "room_type": "stairs", "min_area": 120}},
                        {{"id": "office_{i}", "room_type": "office_open", "min_area": 800}}
                    ]}}"#
                )
            })
            .collect();
        let json = format!(
            r#"{{"mode": "part3", "sqft": 8000, "floors": [{}]}}"#,
            floors.join(",")
        );
        let manifest = ProgramManifest::from_json(&json).unwrap();
        let plans = plan_floors(&manifest);
        assert_eq!(plans.len(), 6);
        for plan in &plans {
            let stair_count = plan.program.iter().filter(|r| r.room_type == "stairs").count();
            let elevator_count = plan.program.iter().filter(|r| r.room_type == "elevator").count();
            assert_eq!(stair_count, 2, "level {} should have 2 stairs", plan.level);
            assert_eq!(elevator_count, 1, "level {} should have 1 elevator", plan.level);
        }
        // Both stairs should be the same width because they share the same
        // min_area.
        let total_core_w: f32 = plans[0].cores.iter().map(|c| c.rect.w).sum();
        assert!(
            total_core_w >= 25.0,
            "cores should fit 2 stairs + 1 elevator, got {}",
            total_core_w
        );
    }

    #[test]
    fn injection_preserves_existing_multiple_stairs() {
        let manifest = ProgramManifest::from_json(
            r#"{
                "mode": "part3",
                "sqft": 6000,
                "floors": [
                    {"level": 1, "rooms": [
                        {"id": "stairs_1", "room_type": "stairs", "min_area": 120},
                        {"id": "stairs_2", "room_type": "stairs", "min_area": 120},
                        {"id": "stairs_3", "room_type": "stairs", "min_area": 120},
                        {"id": "office", "room_type": "office_open", "min_area": 1000}
                    ]}
                ]
            }"#,
        )
        .unwrap();
        let plans = plan_floors(&manifest);
        let stair_count = plans[0].program.iter().filter(|r| r.room_type == "stairs").count();
        assert_eq!(stair_count, 3, "should keep all 3 stairs, not add more");
    }
}
