#![recursion_limit = "256"] // the json! bundle literals in emit.rs are huge

//! Room-layout solver — the live `qbd_layout_generator` path, ported lean.
//!
//! Replaces a ~4,000-LOC Python live path (and skips ~5,300 LOC of dead
//! exploratory solvers — `coordinate_solver`, `solver_suite`,
//! `advanced_solvers`, `layout_refiner`, none of which the default
//! `solver_mode="subdivision"` path imports) with a clean, zoned,
//! top-down BSP.
//!
//! Pipeline: `Answers → program_from_answers → auto_size → subdivide`.
//! Wired behind `archengine_geometry::object::Solver` as [`SubdivisionRoomSolver`], the same
//! seam Increment 3's grid placeholder used — so the app upgrades from a
//! grid to real program-driven zoning with no other change.
//!
//! Not yet ported (next slice): wall/door/dimension emission to the full
//! `qbd_output.schema.json` (`layout_to_walls/doors/dimensions`).

pub mod adjacency;
pub mod catalog;
pub mod emit;
pub mod floors;
pub mod layout;
pub mod manifest;
pub mod mode;
pub mod templates;

pub use adjacency::AdjacencyGraph;
pub use catalog::{RoomCatalog, RoomCatalogEntry};
pub use floors::{FloorPlanInput, FloorStrategy, plan_floors};
pub use layout::layout_floor;
pub use manifest::{ProgramManifest, ManifestError};
pub use mode::BuildingMode;
pub use templates::BuildingTemplate;
pub use emit::{building_json, building_json_from_manifest};

use archengine_geometry::mesh::Transform;
use archengine_geometry::object::{Constraint, Object, Scene, Solver};

/// Errors returned by the public solver API.
#[derive(Debug, thiserror::Error)]
pub enum SolverError {
    /// The questionnaire (`Answers`) path only supports Part 9 residential.
    /// Part 3 and mixed-mode buildings must be supplied as a [`ProgramManifest`].
    #[error("Part 3 / mixed-mode buildings require a ProgramManifest; use a BuildingTemplate or provide a manifest")]
    AnswersNotSupportedForMode,
}

/// Functional zone a room belongs to. Drives the top-level partition
/// (public near the entry, private at the back).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Zone {
    Public,
    Circulation,
    Service,
    Private,
}

impl Zone {
    #[must_use]
    pub fn of(room_type: &str) -> Zone {
        match room_type {
            "entry" | "living" | "great_room" | "dining" | "kitchen" | "office" | "foyer"
            | "common_room" | "dining_hall" | "lounge" | "fitness_room" => {
                Zone::Public
            }
            "hallway" | "corridor" | "stairs" | "elevator" | "shaft" => Zone::Circulation,
            "mudroom" | "pantry" | "mechanical" | "laundry" | "garage" | "mail_room"
            | "storage_locker" | "laundry_room" | "management_office" => Zone::Service,
            _ => Zone::Private, // bedrooms, baths, closets, powder room, studio, etc.
        }
    }

    #[must_use]
    pub fn as_str(self) -> &'static str {
        match self {
            Zone::Public => "public",
            Zone::Circulation => "circulation",
            Zone::Service => "service",
            Zone::Private => "private",
        }
    }
}

/// One room in the program: identity, a relative size `weight`, and an
/// absolute `min_area` floor (sqft). Final area is a floored-proportional
/// share of the footprint (see [`allocate_areas`]) — high-weight rooms
/// (living, bedrooms) absorb the slack; low-weight rooms (closets, baths,
/// garage) pin to their minimum.
#[derive(Debug, Clone, PartialEq, serde::Serialize)]
pub struct RoomSpec {
    pub id: String,
    pub room_type: String,
    pub weight: f32,
    pub min_area: f32,
    /// Optional dwelling-unit id; used by multi-unit residential layouts to
    /// keep unit rooms together.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub unit: Option<String>,
}

impl RoomSpec {
    fn new(id: &str, room_type: &str, weight: f32, min_area: f32) -> Self {
        Self {
            id: id.into(),
            room_type: room_type.into(),
            weight,
            min_area,
            unit: None,
        }
    }
    #[must_use]
    pub fn zone(&self) -> Zone {
        Zone::of(&self.room_type)
    }
}

/// QBD answers — the questionnaire inputs. Mirrors the fields
/// `create_spatial_graph_from_qbd` reads.
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
#[serde(default)]
pub struct Answers {
    /// Building code mode: Part 9 residential, Part 3 commercial, or mixed.
    pub mode: BuildingMode,
    pub bedrooms: u32,
    pub bathrooms: u32,
    pub sqft: f32,
    pub garage: String, // "none" | "1car" | "2car" | "3car"
    pub special_rooms: Vec<String>,
    /// Storeys: `0` = auto (2 when 3+ bedrooms, else 1), or an explicit `1`/`2`.
    pub storeys: u32,
    /// Window intent: `"balanced"` (default), `"more_light"`, `"privacy"`,
    /// `"south_bank"`. Scales glazing above the OBC minimum and biases
    /// placement; the legal minimum + egress are always enforced.
    pub window_intent: String,
    /// Architectural style driving window banking/type/proportion per wall:
    /// `"balanced"` (default), `"ranch"`, `"colonial"`, `"contemporary"`.
    pub style: String,
    /// Lot frontage (ft) along the street — the site plan's width.
    pub lot_width_ft: f32,
    /// Lot depth (ft).
    pub lot_depth_ft: f32,
    /// Municipal zone (Sudbury): `"R1"`, `"R2"`, … — drives setbacks.
    pub zone: String,
    /// Name of the street the lot fronts (drawn on the site plan).
    pub street: String,
    /// Roof type: `"gable"` (default) or `"hip"`.
    pub roof_type: String,
    /// Stair configuration for multi-storey houses: `"switchback"` (default,
    /// U / half-turn), `"straight"`, or `"l_shaped"` (quarter-turn). Sizes the
    /// buildable stair bay the floor is laid out around. Ignored single-storey.
    pub stair_config: String,
}

impl Answers {
    /// Resolved number of storeys: the explicit value, or the auto rule
    /// (3+ bedrooms → 2, else 1). `sqft` is the **total** across all storeys.
    #[must_use]
    pub fn floor_count(&self) -> u32 {
        match self.storeys {
            1 | 2 => self.storeys,
            _ if self.bedrooms >= 3 => 2,
            _ => 1,
        }
    }
}

impl Default for Answers {
    fn default() -> Self {
        Self {
            mode: BuildingMode::Part9,
            bedrooms: 3,
            bathrooms: 2,
            sqft: 1800.0,
            garage: "none".into(),
            special_rooms: Vec::new(),
            storeys: 0,
            window_intent: "balanced".into(),
            style: "balanced".into(),
            lot_width_ft: 50.0,
            lot_depth_ft: 100.0,
            zone: "R1".into(),
            street: "Street".into(),
            roof_type: "gable".into(),
            stair_config: "switchback".into(),
        }
    }
}

/// Build the room program from answers: each room carries a relative size
/// `weight` and an absolute `min_area` floor. High-weight rooms (living,
/// bedrooms, kitchen) grow with the house; low-weight service rooms (closets,
/// baths, garage, laundry) stay near their minimum. Final areas come from
/// [`allocate_areas`] over the chosen footprint — no fraction summing, so the
/// program can't over- or under-subscribe the envelope.
///
/// **Note:** this path is Part 9 only. Part 3 and mixed-mode buildings must
/// be supplied via [`ProgramManifest`] (see [`BuildingTemplate`] and
/// [`building_json_from_manifest`]).
pub fn program_from_answers(a: &Answers) -> Result<Vec<RoomSpec>, SolverError> {
    match a.mode {
        BuildingMode::Part9 => Ok(program_from_answers_part9(a)),
        BuildingMode::Part3 | BuildingMode::Mixed => Err(SolverError::AnswersNotSupportedForMode),
    }
}

/// Part 9 residential program from the questionnaire. Kept as the original
/// implementation so existing tests and the Part 9 path are unchanged.
#[must_use]
fn program_from_answers_part9(a: &Answers) -> Vec<RoomSpec> {
    // (id, type, weight, min_area_sqft)
    let mut p = vec![
        RoomSpec::new("entry", "entry", 2.0, 40.0),
        RoomSpec::new("living", "living", 18.0, 160.0),
        RoomSpec::new("kitchen", "kitchen", 10.0, 100.0),
    ];
    if a.sqft > 800.0 {
        p.push(RoomSpec::new("dining", "dining", 8.0, 90.0));
    }
    if a.bedrooms > 1 {
        p.push(RoomSpec::new("hallway", "hallway", 5.0, 40.0));
    }
    if a.bedrooms > 0 {
        p.push(RoomSpec::new("primary_bedroom", "primary_bedroom", 12.0, 140.0));
        p.push(RoomSpec::new("primary_bath", "primary_bath", 3.0, 50.0));
        p.push(RoomSpec::new("primary_closet", "walk_in_closet", 2.0, 25.0));
    }
    for i in 2..=a.bedrooms {
        p.push(RoomSpec::new(&format!("bedroom_{i}"), "bedroom", 9.0, 100.0));
        p.push(RoomSpec::new(&format!("closet_{i}"), "closet", 1.0, 15.0));
    }
    if a.bathrooms > 1 {
        p.push(RoomSpec::new("bathroom_2", "bathroom", 2.0, 40.0));
    }
    if a.bathrooms > 2 {
        p.push(RoomSpec::new("powder_room", "powder_room", 1.0, 20.0));
    }
    p.push(RoomSpec::new("laundry", "laundry", 2.0, 35.0));
    if a.garage != "none" {
        // Low weight → the garage pins to its size minimum rather than
        // ballooning with the house.
        let (wt, min) = match a.garage.as_str() {
            "1car" => (8.0, 220.0),
            "3car" => (16.0, 660.0),
            _ => (10.0, 440.0),
        };
        p.push(RoomSpec::new("garage", "garage", wt, min));
        p.push(RoomSpec::new("mudroom", "mudroom", 2.0, 40.0));
    }
    if a.special_rooms.iter().any(|s| s == "office") {
        p.push(RoomSpec::new("office", "office", 6.0, 90.0));
    }
    if a.special_rooms.iter().any(|s| s == "pantry") {
        p.push(RoomSpec::new("pantry", "pantry", 1.0, 25.0));
    }
    p
}

/// Convert a validated [`ProgramManifest`] to one program per floor. This is the
/// Part 3 / mixed-use entry point; Part 9 can also use it for bespoke houses.
#[must_use]
pub fn manifest_to_programs(manifest: &ProgramManifest) -> Vec<Vec<RoomSpec>> {
    manifest.to_programs()
}

/// Floored-proportional area allocation (sqft), aligned with `program`. Each
/// room gets at least its `min_area`; the remaining footprint is split among
/// the rest by `weight`. Rooms whose proportional share falls below their
/// minimum are pinned to it and removed from the pool, then the remainder is
/// redistributed — iterated to a fixed point.
#[must_use]
pub fn allocate_areas(program: &[RoomSpec], footprint: f32) -> Vec<f32> {
    let n = program.len();
    let mut areas = vec![0.0_f32; n];
    let mut pinned = vec![false; n];
    loop {
        let pinned_area: f32 = (0..n).filter(|&i| pinned[i]).map(|i| program[i].min_area).sum();
        let free_weight: f32 = (0..n).filter(|&i| !pinned[i]).map(|i| program[i].weight).sum();
        let free_area = (footprint - pinned_area).max(0.0);
        let mut changed = false;
        for i in 0..n {
            if pinned[i] {
                areas[i] = program[i].min_area;
                continue;
            }
            let share = if free_weight > 0.0 {
                program[i].weight / free_weight * free_area
            } else {
                program[i].min_area
            };
            if share < program[i].min_area {
                pinned[i] = true;
                areas[i] = program[i].min_area;
                changed = true;
            } else {
                areas[i] = share;
            }
        }
        if !changed {
            break;
        }
    }
    areas
}

/// The building footprint (sqft): the requested area, grown only if the
/// program's minimum areas don't fit inside it.
#[must_use]
pub fn footprint_for(program: &[RoomSpec], requested_sqft: f32) -> f32 {
    let min_total: f32 = program.iter().map(|r| r.min_area).sum();
    requested_sqft.max(min_total)
}

/// Shape a footprint area (sqft) into envelope `(width, depth)` feet at a
/// golden-ish 1.4 aspect ratio.
#[must_use]
pub fn shape_envelope(footprint: f32) -> (f32, f32) {
    let ratio = 1.4_f32;
    let depth = (footprint / ratio).sqrt();
    let width = footprint / depth;
    (width.round(), depth.round())
}

/// Envelope `(width, depth)` in feet for the program: the footprint is the
/// requested area (grown only to fit the program minimums — see
/// [`footprint_for`]), shaped to a golden-ish 1.4 aspect ratio. The rooms
/// then tile this footprint, so there is no separate overhead factor — the
/// area the user asked for is the area they get.
#[must_use]
pub fn auto_size(program: &[RoomSpec], requested_sqft: f32) -> (f32, f32) {
    shape_envelope(footprint_for(program, requested_sqft))
}

/// Room types that live on the private upper floor of a multi-storey house.
fn is_upper_floor(room_type: &str) -> bool {
    matches!(
        room_type,
        "primary_bedroom" | "primary_bath" | "walk_in_closet" | "bedroom" | "closet" | "bathroom"
    )
}

/// Split a program across `floors`. One storey → the whole program. Two →
/// private rooms (bedrooms + their baths/closets) go upstairs; public + service
/// stay down; each floor gets its own stair, and the upper floor its own
/// circulation hallway.
#[must_use]
pub fn split_floors(program: &[RoomSpec], floors: u32) -> Vec<Vec<RoomSpec>> {
    if floors <= 1 {
        return vec![program.to_vec()];
    }
    let mut ground: Vec<RoomSpec> = program
        .iter()
        .filter(|r| !is_upper_floor(&r.room_type))
        .cloned()
        .collect();
    let mut upper: Vec<RoomSpec> = program
        .iter()
        .filter(|r| is_upper_floor(&r.room_type))
        .cloned()
        .collect();
    ground.push(RoomSpec::new("stairs_1", "stairs", 4.0, 70.0));
    upper.insert(0, RoomSpec::new("hallway_2", "hallway", 5.0, 40.0));
    upper.push(RoomSpec::new("stairs_2", "stairs", 4.0, 70.0));
    vec![ground, upper]
}

/// Floor-to-floor height (ft) for multi-storey layouts. Shared by the stair
/// geometry here and the level elevations emitted in `emit.rs`.
pub const FLOOR_TO_FLOOR_FT: f32 = 10.0;

/// Buildable stair geometry for one configuration, in millimetres. The single
/// source of truth shared by the layout (which reserves `width_mm × depth_mm`
/// as the bay the floor is built around) and the emitter (which reports the
/// `shape` + `flight_clear_mm` onto `SchemaStair`).
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct StairBay {
    /// `"switchback"` | `"straight"` | `"l_shaped"`.
    pub shape: &'static str,
    /// Bay extent across the run, mm.
    pub width_mm: f32,
    /// Bay extent along the run, mm.
    pub depth_mm: f32,
    /// Clear width of a single flight, mm.
    pub flight_clear_mm: f32,
    /// Central well between the two flights (switchback), else 0, mm.
    pub well_mm: f32,
}

/// Treads in the short return flight of an L (quarter-turn) stair. A shared rule
/// so the solver footprint and the drawn plan symbol agree on the turn point.
#[must_use]
pub fn l_return_treads(num_treads: u32) -> u32 {
    3.min(num_treads.saturating_sub(1)).max(1)
}

/// Buildable footprint + flight dimensions for a stair configuration at the
/// standard floor-to-floor height. Derives the riser/tread count from
/// [`regime_obc::stairs::solve_stair`] and lays out a genuinely buildable stair: real
/// ≥860 mm flights, a central well for switchbacks, and a top landing. Unknown
/// configs default to the switchback.
#[must_use]
#[allow(clippy::cast_precision_loss)] // tread counts are small (≈15)
pub fn stair_bay(config: &str) -> StairBay {
    const MM_PER_FT: f32 = 304.8;
    const FLIGHT_CLEAR_MM: f32 = 900.0; // comfortable, above the OBC 860 min
    const WELL_MM: f32 = 200.0; // open well between switchback flights
    const FINISH_MM: f32 = 100.0; // stringer/finish allowance (both sides)
    let spec = regime_obc::stairs::solve_stair(FLOOR_TO_FLOOR_FT * MM_PER_FT);
    let run = spec.tread_run_mm;
    let treads = spec.num_treads as f32;
    let landing = FLIGHT_CLEAR_MM.max(regime_obc::stairs::MIN_WIDTH_MM); // landing ≥ stair width

    match config {
        "straight" => StairBay {
            shape: "straight",
            width_mm: FLIGHT_CLEAR_MM + FINISH_MM,
            depth_mm: treads * run + landing,
            flight_clear_mm: FLIGHT_CLEAR_MM,
            well_mm: 0.0,
        },
        "l_shaped" | "l" | "quarter_turn" => {
            let ret = l_return_treads(spec.num_treads) as f32;
            let main = treads - ret;
            StairBay {
                shape: "l_shaped",
                width_mm: FLIGHT_CLEAR_MM + ret * run + FINISH_MM,
                depth_mm: main * run + landing,
                flight_clear_mm: FLIGHT_CLEAR_MM,
                well_mm: 0.0,
            }
        }
        // Switchback (default): two flights + a well; depth = longer flight run
        // plus a half-landing.
        _ => {
            let longer = (treads / 2.0).ceil();
            StairBay {
                shape: "switchback",
                width_mm: 2.0 * FLIGHT_CLEAR_MM + WELL_MM + FINISH_MM,
                depth_mm: longer * run + landing,
                flight_clear_mm: FLIGHT_CLEAR_MM,
                well_mm: WELL_MM,
            }
        }
    }
}

/// Stair-bay footprint in feet `(width, depth)` for the layout.
#[must_use]
pub fn stair_bay_ft(config: &str) -> (f32, f32) {
    let b = stair_bay(config);
    (b.width_mm / 304.8, b.depth_mm / 304.8)
}

/// An axis-aligned rectangle (feet), origin at min corner.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Rect {
    pub x: f32,
    pub y: f32,
    pub w: f32,
    pub h: f32,
}

impl Rect {
    #[must_use]
    pub fn area(&self) -> f32 {
        self.w * self.h
    }
    /// Split into two along the given fraction of the longer side.
    fn split(&self, frac: f32) -> (Rect, Rect) {
        if self.w >= self.h {
            let wa = self.w * frac;
            (
                Rect { x: self.x, y: self.y, w: wa, h: self.h },
                Rect { x: self.x + wa, y: self.y, w: self.w - wa, h: self.h },
            )
        } else {
            let ha = self.h * frac;
            (
                Rect { x: self.x, y: self.y, w: self.w, h: ha },
                Rect { x: self.x, y: self.y + ha, w: self.w, h: self.h - ha },
            )
        }
    }
    /// Split along Y (depth) at the given fraction — used for the zone bands.
    fn split_y(&self, frac: f32) -> (Rect, Rect) {
        let ha = self.h * frac;
        (
            Rect { x: self.x, y: self.y, w: self.w, h: ha },
            Rect { x: self.x, y: self.y + ha, w: self.w, h: self.h - ha },
        )
    }
}

/// A placed room: its spec plus the rect it occupies.
#[derive(Debug, Clone)]
pub struct PlacedRoom {
    pub id: String,
    pub room_type: String,
    pub zone: Zone,
    pub rect: Rect,
    /// Optional dwelling-unit id for multi-unit residential layouts.
    pub unit: Option<String>,
}

/* Adjacency affinity is now computed by AdjacencyGraph in
   crate::adjacency. The hardcoded table has been moved there so each
   BuildingMode can carry its own relationship graph. */

/// Instance-level pairing bonus: a numbered bedroom and the closet sharing its
/// index (`bedroom_2` ↔ `closet_2`) belong together, beyond the generic
/// bedroom↔closet type affinity. Without this, the seriation would attach a
/// bedroom to whichever closet sorts first.
fn pair_bonus(a: &str, b: &str) -> f32 {
    let matched = |x: &str, y: &str| {
        x.strip_prefix("bedroom_")
            .zip(y.strip_prefix("closet_"))
            .is_some_and(|(i, j)| i == j)
    };
    if matched(a, b) || matched(b, a) {
        0.4
    } else {
        0.0
    }
}

/// Order the program so high-affinity rooms are contiguous: a greedy
/// nearest-neighbour walk over the affinity graph, seeded at the entry (so the
/// order flows entry → public → service → private). Deterministic — ties keep
/// the lower program index. Returns indices into `program`.
fn seriate(program: &[RoomSpec], graph: &AdjacencyGraph) -> Vec<usize> {
    let n = program.len();
    if n == 0 {
        return Vec::new();
    }
    // Seed at the stair when present (multi-storey): both floors then grow
    // their layout from the same anchor, so the stacked stairs land in the
    // same corner. Otherwise seed at the entry, then living.
    let seed = program
        .iter()
        .position(|r| r.room_type == "stairs")
        .or_else(|| program.iter().position(|r| r.room_type == "entry"))
        .or_else(|| program.iter().position(|r| r.room_type == "living"))
        .unwrap_or(0);
    let mut visited = vec![false; n];
    let mut order = Vec::with_capacity(n);
    order.push(seed);
    visited[seed] = true;
    for _ in 1..n {
        let last = *order.last().unwrap();
        let mut best = usize::MAX;
        let mut best_aff = f32::NEG_INFINITY;
        for j in 0..n {
            if visited[j] {
                continue;
            }
            let aff = graph.affinity_for_specs(&program[last], &program[j])
                + pair_bonus(&program[last].id, &program[j].id);
            if aff > best_aff + 1e-6 {
                best_aff = aff;
                best = j;
            }
        }
        order.push(best);
        visited[best] = true;
    }
    order
}

/// How many of `r`'s four edges lie on the `env` boundary (0–4). A room needs
/// only one such edge to reach an exterior wall (for a window).
fn perim_edges(r: Rect, env: Rect) -> i32 {
    const E: f32 = 0.5;
    i32::from((r.x - env.x).abs() < E)
        + i32::from((r.y - env.y).abs() < E)
        + i32::from(((r.x + r.w) - (env.x + env.w)).abs() < E)
        + i32::from(((r.y + r.h) - (env.y + env.h)).abs() < E)
}

/// Count rooms in `items` that want an exterior wall: window-needing rooms
/// (daylight or egress) plus the entry, which must reach an exterior wall for
/// its front door.
fn window_count(items: &[(usize, f32)], program: &[RoomSpec]) -> i32 {
    items
        .iter()
        .filter(|(i, _)| {
            let rt = &program[*i].room_type;
            regime_obc::windows::needs_window(rt) || rt == "entry"
        })
        .count()
        .try_into()
        .unwrap_or(i32::MAX)
}

/// Recursively slice `rect` among the seriated `items` (index, area), keeping
/// adjacency clusters together AND pushing window-needing rooms to the
/// envelope perimeter. The list is split at its cumulative-area midpoint (a
/// weak link in the seriation); the two groups are then assigned to the low/
/// high sub-rect by whichever assignment gives window-needing rooms more
/// perimeter exposure. The top split runs along depth (`y_first`) and is left
/// un-flipped so the entry cluster anchors to the front; deeper splits take
/// the longer side for sane aspect ratios.
fn slice_seriated(
    env: Rect,
    rect: Rect,
    items: &[(usize, f32)],
    program: &[RoomSpec],
    y_first: bool,
) -> Vec<(usize, Rect)> {
    match items {
        [] => Vec::new(),
        [(only, _)] => vec![(*only, rect)],
        _ => {
            let total: f32 = items.iter().map(|(_, w)| *w).sum();
            let half = total * 0.5;
            let mut acc = 0.0;
            let mut split = 1;
            for (i, (_, w)) in items.iter().enumerate() {
                acc += *w;
                if acc >= half {
                    split = (i + 1).min(items.len() - 1);
                    break;
                }
            }
            let (a, b) = items.split_at(split);
            let wa: f32 = a.iter().map(|(_, w)| *w).sum();
            let wb = total - wa;
            let frac_a = if total > 0.0 { wa / total } else { 0.5 };
            let frac_b = if total > 0.0 { wb / total } else { 0.5 };
            let cut = |f: f32| if y_first { rect.split_y(f) } else { rect.split(f) };

            // Default: group `a` (front of the order) takes the low sub-rect.
            // Deeper than the top, consider swapping so the more
            // window-hungry group lands on the more-exposed rect.
            let (la, lb) = cut(frac_a); // a → la (low), b → lb (high)
            let mut a_rect = la;
            let mut b_rect = lb;
            if !y_first {
                let (sb, sa) = cut(frac_b); // b → sb (low), a → sa (high)
                let aw = window_count(a, program);
                let bw = window_count(b, program);
                let keep = aw * perim_edges(la, env) + bw * perim_edges(lb, env);
                let swap = bw * perim_edges(sb, env) + aw * perim_edges(sa, env);
                if swap > keep {
                    a_rect = sa;
                    b_rect = sb;
                }
            }
            let mut out = slice_seriated(env, a_rect, a, program, false);
            out.extend(slice_seriated(env, b_rect, b, program, false));
            out
        }
    }
}

/// A slicing unit: a lead room plus rooms tucked *inside* it — a bedroom and
/// its closet, or the primary bedroom with its bath + walk-in closet. The
/// suite is sliced as one rect, then split so the lead (window-needing) room
/// takes the exterior side and the inboard rooms sit behind it.
#[derive(Clone)]
struct Suite {
    lead: usize,
    inboard: Vec<usize>,
}

/// Group the program into suites: `closet_N` tucks into `bedroom_N`; the
/// primary bath + walk-in closet tuck into the primary bedroom; everything
/// else is its own lead. This is what makes instance pairing exact —
/// `bedroom_2` always ends up next to `closet_2`, never another closet.
fn group_suites(program: &[RoomSpec]) -> Vec<Suite> {
    let idx_of = |id: &str| program.iter().position(|r| r.id == id);
    let parent = |i: usize| -> usize {
        let r = &program[i];
        if let Some(n) = r.id.strip_prefix("closet_") {
            return idx_of(&format!("bedroom_{n}")).unwrap_or(i);
        }
        if r.room_type == "walk_in_closet" || r.room_type == "primary_bath" {
            return idx_of("primary_bedroom").unwrap_or(i);
        }
        i
    };
    (0..program.len())
        .filter(|&i| parent(i) == i)
        .map(|i| Suite {
            lead: i,
            inboard: (0..program.len()).filter(|&j| j != i && parent(j) == i).collect(),
        })
        .collect()
}

/// Place a suite's lead room against an exterior edge of `rect` and tuck its
/// inboard rooms behind it (toward the building interior). A lone room (no
/// inboard) just fills the rect.
#[allow(clippy::many_single_char_names)]
fn place_suite(rect: Rect, suite: &Suite, program: &[RoomSpec], areas: &[f32], env: Rect) -> Vec<PlacedRoom> {
    const E: f32 = 0.5;
    let mk = |i: usize, r: Rect| PlacedRoom {
        id: program[i].id.clone(),
        room_type: program[i].room_type.clone(),
        zone: program[i].zone(),
        rect: r,
        unit: program[i].unit.clone(),
    };
    if suite.inboard.is_empty() {
        return vec![mk(suite.lead, rect)];
    }
    let lead_area = areas[suite.lead];
    let in_area: f32 = suite.inboard.iter().map(|&i| areas[i]).sum();
    let f = (lead_area / (lead_area + in_area)).clamp(0.05, 0.95);
    let (lx, ly, hx, hy) = (env.x, env.y, env.x + env.w, env.y + env.h);

    // Candidate placements — lead against each exterior edge the suite touches,
    // inboard (closet) carved from the opposite, interior side:
    //   S: lead bottom · N: lead top · W: lead left · E: lead right
    let candidates = [
        ((rect.y - ly).abs() < E, // south
         Rect { h: rect.h * f, ..rect },
         Rect { y: rect.y + rect.h * f, h: rect.h * (1.0 - f), ..rect }),
        (((rect.y + rect.h) - hy).abs() < E, // north
         Rect { y: rect.y + rect.h * (1.0 - f), h: rect.h * f, ..rect },
         Rect { h: rect.h * (1.0 - f), ..rect }),
        ((rect.x - lx).abs() < E, // west
         Rect { w: rect.w * f, ..rect },
         Rect { x: rect.x + rect.w * f, w: rect.w * (1.0 - f), ..rect }),
        (((rect.x + rect.w) - hx).abs() < E, // east
         Rect { x: rect.x + rect.w * (1.0 - f), w: rect.w * f, ..rect },
         Rect { w: rect.w * (1.0 - f), ..rect }),
    ];

    // Pick the placement that keeps the inboard rooms (the closet) off exterior
    // walls — those are reserved for the bedroom's egress window. Score: fewest
    // closet perimeter edges first, then the most bedroom perimeter edges. Only
    // edges the suite actually touches are eligible (the lead needs a window).
    let best = candidates
        .iter()
        .filter(|(touches, _, _)| *touches)
        .min_by_key(|(_, lead_r, in_r)| {
            (perim_edges(*in_r, env), -perim_edges(*lead_r, env))
        });
    let (lead_rect, in_rect) = match best {
        Some((_, l, i)) => (*l, *i),
        // Interior suite (rare): split the longer side, lead first.
        None => rect.split(f),
    };

    let mut out = vec![mk(suite.lead, lead_rect)];
    let in_items: Vec<(usize, f32)> = suite.inboard.iter().map(|&i| (i, areas[i])).collect();
    for (i, r) in slice_seriated(env, in_rect, &in_items, program, false) {
        out.push(mk(i, r));
    }
    out
}

/// Total area of a suite (lead + inboard rooms).
fn suite_total(s: &Suite, areas: &[f32]) -> f32 {
    areas[s.lead] + s.inboard.iter().map(|&i| areas[i]).sum::<f32>()
}

/// Lay out a set of suites inside `rect`: seriate their leads, slice the rect
/// among them by area, and split each suite (lead on the exterior). `env` is
/// the full envelope, used for perimeter bias and exterior-edge tests.
fn layout_suites_in(rect: Rect, suites: &[Suite], program: &[RoomSpec], areas: &[f32], env: Rect, graph: &AdjacencyGraph) -> Vec<PlacedRoom> {
    if suites.is_empty() {
        return Vec::new();
    }
    let lead_specs: Vec<RoomSpec> = suites.iter().map(|s| program[s.lead].clone()).collect();
    let suite_area: Vec<f32> = suites.iter().map(|s| suite_total(s, areas)).collect();
    let order = seriate(&lead_specs, graph);
    let items: Vec<(usize, f32)> = order.iter().map(|&i| (i, suite_area[i])).collect();
    slice_seriated(env, rect, &items, &lead_specs, true)
        .into_iter()
        .flat_map(|(si, r)| place_suite(r, &suites[si], program, areas, env))
        .collect()
}

/// Lay out a floor whose program includes a stair: pin the stair to a fixed
/// front-left corner bay (identical on every floor that shares the footprint,
/// so stacked stairs align), then lay the remaining suites out in the two
/// rectangles around it — a shallow front band and the deep main band.
fn layout_with_stair(env: Rect, suites: &[Suite], stair_pos: usize, program: &[RoomSpec], areas: &[f32], stair_config: &str, graph: &AdjacencyGraph) -> Vec<PlacedRoom> {
    // Buildable bay for the chosen configuration. Same footprint on every floor
    // (shared envelope + config) ⇒ stacked stairs land exactly on top of each
    // other. Only shrink below buildable if the envelope genuinely can't fit it.
    let (bay_w, bay_d) = stair_bay_ft(stair_config);
    let stair = &suites[stair_pos];
    let sw = bay_w.min(env.w * 0.7);
    let run = bay_d.min(env.h * 0.85);

    let mk = |i: usize, r: Rect| PlacedRoom {
        id: program[i].id.clone(),
        room_type: program[i].room_type.clone(),
        zone: program[i].zone(),
        rect: r,
        unit: program[i].unit.clone(),
    };
    let stair_rect = Rect { x: env.x, y: env.y, w: sw, h: run };
    let mut placed = vec![mk(stair.lead, stair_rect)];

    let mut others: Vec<Suite> = suites
        .iter()
        .enumerate()
        .filter(|(i, _)| *i != stair_pos)
        .map(|(_, s)| s.clone())
        .collect();

    // Attached garage → pull it onto the street wall as a full-depth side
    // column (opposite the stair) and tuck the entry against it, so the front
    // door and the garage's overhead door sit side by side on the facade.
    // Full depth keeps areas balanced: gw·env.h ≈ the garage area, so the rest
    // of the house keeps its width.
    if let Some(gp) = others.iter().position(|s| program[s.lead].room_type == "garage") {
        let garage = others.remove(gp);
        let gw = (suite_total(&garage, areas) / env.h).clamp(env.w * 0.22, env.w * 0.45);
        let gx = env.x + env.w - gw;
        placed.push(mk(garage.lead, Rect { x: gx, y: env.y, w: gw, h: env.h }));

        let hw = env.w - gw; // house column, left of the garage
        if let Some(ep) = others.iter().position(|s| program[s.lead].room_type == "entry") {
            let entry = others.remove(ep);
            let ew = (areas[entry.lead] / run).clamp(4.0, (hw - sw).max(4.0));
            // Entry against the garage's left edge, on the front wall.
            placed.push(mk(entry.lead, Rect { x: env.x + hw - ew, y: env.y, w: ew, h: run }));
            let fc = Rect { x: env.x + sw, y: env.y, w: (hw - sw - ew).max(0.0), h: run };
            let bk = Rect { x: env.x, y: env.y + run, w: hw, h: env.h - run };
            let (fcs, bks) = partition_front_back(&others, fc.area(), program, areas, graph);
            placed.extend(layout_suites_in(fc, &fcs, program, areas, env, graph));
            placed.extend(layout_suites_in(bk, &bks, program, areas, env, graph));
        } else {
            let front = Rect { x: env.x + sw, y: env.y, w: hw - sw, h: run };
            let back = Rect { x: env.x, y: env.y + run, w: hw, h: env.h - run };
            let (fs, bs) = partition_front_back(&others, front.area(), program, areas, graph);
            placed.extend(layout_suites_in(front, &fs, program, areas, env, graph));
            placed.extend(layout_suites_in(back, &bs, program, areas, env, graph));
        }
        return placed;
    }

    // No garage → the original shallow-front / deep-back split: a front band
    // beside the stair and the deep main band behind both.
    let front = Rect { x: env.x + sw, y: env.y, w: env.w - sw, h: run };
    let back = Rect { x: env.x, y: env.y + run, w: env.w, h: env.h - run };
    let (front_suites, back_suites) = partition_front_back(&others, front.area(), program, areas, graph);
    placed.extend(layout_suites_in(front, &front_suites, program, areas, env, graph));
    placed.extend(layout_suites_in(back, &back_suites, program, areas, env, graph));
    placed
}

/// Seriate `suites` and split them into a front group (filling up to
/// `front_area`) and a back group, keeping adjacency order. Shared by the
/// stair-floor layouts.
fn partition_front_back(
    suites: &[Suite],
    front_area: f32,
    program: &[RoomSpec],
    areas: &[f32],
    graph: &AdjacencyGraph,
) -> (Vec<Suite>, Vec<Suite>) {
    let lead_specs: Vec<RoomSpec> = suites.iter().map(|s| program[s.lead].clone()).collect();
    let order = seriate(&lead_specs, graph);
    let (mut front, mut back) = (Vec::new(), Vec::new());
    let mut acc = 0.0;
    for &oi in &order {
        if acc < front_area {
            acc += suite_total(&suites[oi], areas);
            front.push(suites[oi].clone());
        } else {
            back.push(suites[oi].clone());
        }
    }
    (front, back)
}

/// True when this program is a dedicated **bedroom floor** (bedrooms + a
/// hallway + a stair, and none of the main-floor public rooms). Such floors get
/// the hall-spine layout so every bedroom opens onto the hallway.
fn is_bedroom_floor(program: &[RoomSpec]) -> bool {
    let has = |t: &str| program.iter().any(|r| r.room_type == t);
    let has_bed = program.iter().any(|r| r.room_type.contains("bedroom"));
    has_bed
        && has("stairs")
        && program.iter().any(|r| r.room_type == "hallway")
        && !has("entry")
        && !has("living")
        && !has("kitchen")
        && !has("great_room")
}

/// Hall-spine bedroom floor: pin the stair to the shared front-left bay, run a
/// hallway corridor across the floor just behind it, and tile every other room
/// as a full-depth bay touching that corridor — so each bedroom opens onto the
/// hall and reaches an exterior wall for its window. Rooms are seriated so a
/// closet lands next to its bedroom.
fn layout_bedroom_floor(env: Rect, program: &[RoomSpec], areas: &[f32], stair_config: &str, graph: &AdjacencyGraph) -> Vec<PlacedRoom> {
    // Keep the corridor's footprint proportional to the floor and no wider than
    // needed: a full-width corridor's share of the floor is just its depth over
    // the floor depth, so target ~9% but never below a ~3 ft (914 mm) code-min
    // clear width.
    const HALL_AREA_RATIO: f32 = 0.09;
    const MIN_HALL_FT: f32 = 3.3; // ≈ 1.0 m clear width (minimum)
    // Same buildable bay as the floor below, so the stacked stairs align.
    let (bay_w, bay_d) = stair_bay_ft(stair_config);
    let sw = bay_w.min(env.w * 0.7);
    let run = bay_d.min(env.h * 0.85);
    let hall_d = (HALL_AREA_RATIO * env.h).clamp(MIN_HALL_FT, (env.h - run) * 0.4);

    let mk = |i: usize, r: Rect| PlacedRoom {
        id: program[i].id.clone(),
        room_type: program[i].room_type.clone(),
        zone: program[i].zone(),
        rect: r,
        unit: program[i].unit.clone(),
    };
    let pos = |t: &str| program.iter().position(|r| r.room_type == t);
    let stair_i = pos("stairs");
    let hall_i = pos("hallway");
    let (Some(stair_i), Some(hall_i)) = (stair_i, hall_i) else {
        // Shouldn't happen (is_bedroom_floor guards), but fall back safely.
        let suites = group_suites(program);
        return layout_suites_in(env, &suites, program, areas, env, graph);
    };

    let mut placed = Vec::new();
    // Stair: same bay as every other floor, so stacked stairs align.
    placed.push(mk(stair_i, Rect { x: env.x, y: env.y, w: sw, h: run }));
    // Hallway corridor across the floor, just north of the stair run (so the
    // stair landing opens onto it).
    let hall_y = env.y + run;
    placed.push(mk(hall_i, Rect { x: env.x, y: hall_y, w: env.w, h: hall_d }));

    // Two bedroom regions: the front band beside the stair (south of the hall)
    // and the deep north band (north of the hall). Every bay in either touches
    // the corridor.
    let front = Rect { x: env.x + sw, y: env.y, w: env.w - sw, h: run };
    let north = Rect {
        x: env.x,
        y: hall_y + hall_d,
        w: env.w,
        h: (env.y + env.h) - (hall_y + hall_d),
    };

    // Keep each bedroom with its closet(s)/ensuite as a suite, seriated so the
    // suites order sensibly along the hall.
    let mut suites: Vec<Suite> = group_suites(program)
        .into_iter()
        .filter(|s| {
            let t = &program[s.lead].room_type;
            t != "stairs" && t != "hallway"
        })
        .collect();
    // Attach standalone *shared* bathrooms to a bedroom suite so the bath stacks
    // with a closet in one bay (rotating their divider) instead of taking a full
    // bay of its own between the bedrooms.
    let shared_baths: Vec<usize> = suites
        .iter()
        .filter(|s| program[s.lead].room_type == "bathroom" && s.inboard.is_empty())
        .map(|s| s.lead)
        .collect();
    suites.retain(|s| !(program[s.lead].room_type == "bathroom" && s.inboard.is_empty()));
    let bed_targets: Vec<usize> = suites
        .iter()
        .enumerate()
        .filter(|(_, s)| program[s.lead].room_type == "bedroom")
        .map(|(i, _)| i)
        .collect();
    for (k, &bath) in shared_baths.iter().enumerate() {
        if bed_targets.is_empty() {
            suites.push(Suite { lead: bath, inboard: Vec::new() });
        } else {
            suites[bed_targets[k % bed_targets.len()]].inboard.push(bath);
        }
    }
    let lead_specs: Vec<RoomSpec> = suites.iter().map(|s| program[s.lead].clone()).collect();
    let order = seriate(&lead_specs, graph);
    let ordered: Vec<&Suite> = order.iter().map(|&o| &suites[o]).collect();

    // Assign whole suites to the front band (up to its area) or the north band,
    // so a bedroom and its closet never split across the hall.
    let af = front.area();
    let (mut fr, mut nr): (Vec<&Suite>, Vec<&Suite>) = (Vec::new(), Vec::new());
    let mut acc = 0.0;
    for s in ordered {
        if acc < af && fr.is_empty() {
            acc += suite_total(s, areas);
            fr.push(s);
        } else {
            nr.push(s);
        }
    }

    // Front band's hall edge is its north (top) side; the north band's is its
    // south (bottom) side.
    place_suite_band(&mut placed, &fr, front, &mk, program, areas, false);
    place_suite_band(&mut placed, &nr, north, &mk, program, areas, true);
    placed
}

/// Tile suite bays across `region` (each full region depth, sized by suite
/// area). Within a bay the bedroom takes the wide part, full depth (touching the
/// hall and an exterior wall); its closet/bath stack in the leftover column with
/// the bath on the hall side (so a shared bath opens to the hall, a closet sits
/// behind). `hall_at_bottom` says which edge of the bay borders the corridor.
fn place_suite_band(
    placed: &mut Vec<PlacedRoom>,
    suites: &[&Suite],
    region: Rect,
    mk: &impl Fn(usize, Rect) -> PlacedRoom,
    program: &[RoomSpec],
    areas: &[f32],
    hall_at_bottom: bool,
) {
    if suites.is_empty() || region.w <= 0.0 || region.h <= 0.0 {
        return;
    }
    let total: f32 = suites.iter().map(|s| suite_total(s, areas)).sum::<f32>().max(1e-3);
    let mut x = region.x;
    for s in suites {
        let bw = region.w * suite_total(s, areas) / total;
        let bay = Rect { x, y: region.y, w: bw, h: region.h };
        x += bw;

        let bay_total =
            (areas[s.lead] + s.inboard.iter().map(|&i| areas[i]).sum::<f32>()).max(1e-3);
        let lead_w = bay.w * areas[s.lead] / bay_total;
        // Bedroom: full-depth left part.
        placed.push(mk(s.lead, Rect { x: bay.x, y: bay.y, w: lead_w, h: bay.h }));

        if s.inboard.is_empty() {
            continue;
        }
        // Stack the inboard rooms in the leftover column, baths on the hall side.
        let col_x = bay.x + lead_w;
        let col_w = (bay.w - lead_w).max(0.0);
        let in_total: f32 = s.inboard.iter().map(|&i| areas[i]).sum::<f32>().max(1e-3);
        let mut ordered = s.inboard.clone();
        ordered.sort_by_key(|&i| usize::from(!program[i].room_type.contains("bath")));
        let mut frac = 0.0;
        for &i in &ordered {
            let f = areas[i] / in_total;
            let h = bay.h * f;
            let ry = if hall_at_bottom {
                bay.y + bay.h * frac
            } else {
                bay.y + bay.h * (1.0 - frac - f)
            };
            placed.push(mk(i, Rect { x: col_x, y: ry, w: col_w, h }));
            frac += f;
        }
    }
}

/// Lay out the program inside `envelope` (feet) by adjacency. Rooms are
/// allocated real areas and grouped into suites (bedroom + its closet/bath),
/// the suites are seriated along the relationship graph ([`seriate`]) and
/// sliced ([`slice_seriated`]); each suite then splits with its lead room on
/// the exterior wall. A floor with a stair pins it to a fixed bay so stacked
/// stairs align. The entry anchors to the front; a north entry mirrors depth.
#[must_use]
pub fn subdivide(envelope: Rect, program: &[RoomSpec], entry_edge: &str, stair_config: &str, graph: &AdjacencyGraph) -> Vec<PlacedRoom> {
    if program.is_empty() || envelope.area() <= 0.0 {
        return Vec::new();
    }
    let areas = allocate_areas(program, envelope.area());

    // Dedicated bedroom floor → hall-spine layout (every bedroom opens onto the
    // hall). Otherwise the generic suite layout, stair-aware when there's one.
    let mut placed = if is_bedroom_floor(program) {
        layout_bedroom_floor(envelope, program, &areas, stair_config, graph)
    } else {
        let suites = group_suites(program);
        match suites.iter().position(|s| program[s.lead].room_type == "stairs") {
            Some(stair_pos) => layout_with_stair(envelope, &suites, stair_pos, program, &areas, stair_config, graph),
            None => layout_suites_in(envelope, &suites, program, &areas, envelope, graph),
        }
    };

    // For a north entry, mirror depth so the entry cluster sits at high Y.
    if entry_edge == "north" {
        for r in &mut placed {
            r.rect.y = envelope.y + (envelope.y + envelope.h - (r.rect.y + r.rect.h));
        }
    }
    placed
}

/// `archengine_geometry::object::Solver` wrapping the layout. Uses the first sketched
/// `Region`'s bounding box as the envelope if present; otherwise
/// auto-sizes from the program. Adds one `"room"` Object per placed room
/// (rect + room_type + zone in params), the shape `ls-catalog::room_rect`
/// already reads.
pub struct SubdivisionRoomSolver {
    pub program: Vec<RoomSpec>,
    pub entry_edge: String,
    pub stair_config: String,
    pub graph: AdjacencyGraph,
}

impl SubdivisionRoomSolver {
    #[must_use]
    pub fn from_answers(a: &Answers) -> Self {
        Self {
            program: program_from_answers(a)
                .expect("SubdivisionRoomSolver::from_answers requires Part 9 answers; use a manifest for Part 3 / mixed mode"),
            entry_edge: "south".into(),
            stair_config: a.stair_config.clone(),
            graph: AdjacencyGraph::new_for_mode(a.mode),
        }
    }
}

impl Solver for SubdivisionRoomSolver {
    fn solve(&self, scene: &mut Scene) {
        scene.objects.retain(|o| o.kind != "room");

        let envelope = match scene.regions.first() {
            Some(region) if region.polygon.len() >= 2 => {
                let mut min = glam::Vec2::splat(f32::INFINITY);
                let mut max = glam::Vec2::splat(f32::NEG_INFINITY);
                for p in &region.polygon {
                    min = min.min(*p);
                    max = max.max(*p);
                }
                Rect { x: min.x, y: min.y, w: max.x - min.x, h: max.y - min.y }
            }
            _ => {
                let (w, h) = auto_size(&self.program, 0.0);
                Rect { x: 0.0, y: 0.0, w, h }
            }
        };

        let rooms = subdivide(envelope, &self.program, &self.entry_edge, &self.stair_config, &self.graph);
        let mut next_id = scene.objects.iter().map(|o| o.id.0).max().unwrap_or(0) + 1;
        for r in rooms {
            let obj = Object::new(next_id, "room")
                .with_param("rect", serde_json::json!([r.rect.x, r.rect.y, r.rect.w, r.rect.h]))
                .with_param("room_id", serde_json::json!(r.id))
                .with_param("room_type", serde_json::json!(r.room_type))
                .with_param("zone", serde_json::json!(r.zone.as_str()))
                .with_constraint(Constraint::FixedAt(Transform::identity()));
            scene.add(obj);
            next_id += 1;
        }
    }
}

#[cfg(test)]
#[allow(clippy::cast_precision_loss)] // counts → f32 for test averages
mod tests {
    use super::*;

    #[test]
    fn program_for_3bed_2bath_has_expected_rooms() {
        let a = Answers {
            bedrooms: 3,
            bathrooms: 2,
            sqft: 1800.0,
            garage: "none".into(),
            special_rooms: vec![],
            storeys: 1,
            window_intent: "balanced".into(),
            style: "balanced".into(),
            ..Answers::default()
        };
        let p = program_from_answers(&a).unwrap();
        let ids: Vec<&str> = p.iter().map(|r| r.id.as_str()).collect();
        for want in [
            "entry", "living", "kitchen", "dining", "hallway",
            "primary_bedroom", "primary_bath", "primary_closet",
            "bedroom_2", "bedroom_3", "bathroom_2", "laundry",
        ] {
            assert!(ids.contains(&want), "missing room {want}; got {ids:?}");
        }
        // 3 bedrooms → primary + bedroom_2 + bedroom_3.
        assert_eq!(p.iter().filter(|r| r.room_type.contains("bedroom")).count(), 3);
    }

    #[test]
    fn program_from_answers_rejects_part3_and_mixed() {
        for mode in [BuildingMode::Part3, BuildingMode::Mixed] {
            let a = Answers {
                mode,
                ..Answers::default()
            };
            let err = program_from_answers(&a).expect_err("Part 3 / mixed must use a manifest");
            assert!(
                matches!(err, SolverError::AnswersNotSupportedForMode),
                "expected AnswersNotSupportedForMode, got {err:?}"
            );
        }
    }

    #[test]
    fn building_json_reports_error_for_part3_answers() {
        let a = Answers {
            mode: BuildingMode::Part3,
            ..Answers::default()
        };
        let value = building_json(&a);
        assert_eq!(value["success"].as_bool(), Some(false));
        assert!(
            value["error"].as_str().unwrap_or("").contains("ProgramManifest"),
            "error should direct user to ProgramManifest"
        );
    }

    #[test]
    fn part9_seriation_keeps_public_cluster_at_the_front() {
        let a = Answers {
            bedrooms: 3,
            bathrooms: 2,
            sqft: 1800.0,
            garage: "none".into(),
            special_rooms: vec![],
            storeys: 1,
            window_intent: "balanced".into(),
            style: "balanced".into(),
            ..Answers::default()
        };
        let p = program_from_answers(&a).unwrap();
        let graph = AdjacencyGraph::new_for_mode(BuildingMode::Part9);
        let order = seriate(&p, &graph);
        let ordered_ids: Vec<&str> = order.iter().map(|&i| p[i].id.as_str()).collect();
        // The public core must lead, anchored by the entry.
        assert_eq!(ordered_ids[0], "entry", "entry must seed the order");
        let public_set: std::collections::HashSet<&str> =
            ["entry", "living", "dining", "kitchen"].into_iter().collect();
        let public_in_first_four: usize = ordered_ids
            .iter()
            .take(4)
            .filter(|id| public_set.contains(*id))
            .count();
        assert!(
            public_in_first_four >= 3,
            "public cluster should dominate the front of the order: {ordered_ids:?}"
        );
        // Dining and kitchen should be adjacent in the order (high affinity).
        let dining_pos = ordered_ids.iter().position(|id| *id == "dining").unwrap();
        let kitchen_pos = ordered_ids.iter().position(|id| *id == "kitchen").unwrap();
        assert!(
            (dining_pos as isize - kitchen_pos as isize).abs() <= 1,
            "dining and kitchen should be contiguous: {ordered_ids:?}"
        );
    }

    #[test]
    fn part3_seriation_clusters_lobby_retail_and_corridor() {
        let p = vec![
            RoomSpec::new("lobby", "lobby", 8.0, 200.0),
            RoomSpec::new("retail", "retail", 25.0, 800.0),
            RoomSpec::new("corridor", "corridor", 6.0, 120.0),
            RoomSpec::new("office_open", "office_open", 18.0, 600.0),
            RoomSpec::new("stairs_1", "stairs", 5.0, 120.0),
        ];
        let graph = AdjacencyGraph::new_for_mode(BuildingMode::Part3);
        let order = seriate(&p, &graph);
        let ordered_ids: Vec<&str> = order.iter().map(|&i| p[i].id.as_str()).collect();
        // Stairs seed the circulation core so stacked stairs align across floors.
        assert_eq!(ordered_ids[0], "stairs_1", "stairs must seed the Part 3 order");
        // Lobby, retail and corridor should cluster early and be contiguous.
        let lobby_pos = ordered_ids.iter().position(|id| *id == "lobby").unwrap();
        let retail_pos = ordered_ids.iter().position(|id| *id == "retail").unwrap();
        let corridor_pos = ordered_ids.iter().position(|id| *id == "corridor").unwrap();
        assert!(
            lobby_pos <= 3 && retail_pos <= 3 && corridor_pos <= 3,
            "lobby, retail and corridor should cluster near the stairs: {ordered_ids:?}"
        );
        assert!(
            (retail_pos as isize - corridor_pos as isize).abs() <= 1,
            "retail and corridor should be contiguous: {ordered_ids:?}"
        );
        assert!(
            (lobby_pos as isize - retail_pos as isize).abs() <= 1,
            "lobby and retail should be contiguous: {ordered_ids:?}"
        );
    }

    #[test]
    fn garage_adds_garage_and_mudroom() {
        let a = Answers {
            garage: "2car".into(),
            ..Answers::default()
        };
        let p = program_from_answers(&a).unwrap();
        assert!(p.iter().any(|r| r.id == "garage" && (r.min_area - 440.0).abs() < 1.0));
        assert!(p.iter().any(|r| r.id == "mudroom"));
    }

    #[test]
    fn auto_size_uses_requested_footprint_without_overhead() {
        let p = program_from_answers(&Answers::default()).unwrap();
        let min_total: f32 = p.iter().map(|r| r.min_area).sum();
        // A request above the program minimum IS the footprint — no overhead.
        let (w, d) = auto_size(&p, 1800.0);
        assert!((w * d - 1800.0).abs() <= 1800.0 * 0.03, "got {} for 1800", w * d);
        // With no request it falls back to just fitting the minimums (not ×1.35).
        let (w0, d0) = auto_size(&p, 0.0);
        assert!((w0 * d0 - min_total).abs() <= min_total * 0.03, "got {} vs min {}", w0 * d0, min_total);
        assert!(w0 * d0 < min_total * 1.1, "no 35% overhead: {} vs {}", w0 * d0, min_total);
        // Golden-ish aspect.
        assert!((w / d - 1.4).abs() < 0.1);
    }

    #[test]
    fn allocate_areas_floors_small_rooms_and_sums_to_footprint() {
        let p = program_from_answers(&Answers::default()).unwrap();
        let areas = allocate_areas(&p, 1800.0);
        assert_eq!(areas.len(), p.len());
        // Tiles the whole footprint.
        let total: f32 = areas.iter().sum();
        assert!((total - 1800.0).abs() < 1.0, "areas sum {total} != 1800");
        // Every room meets its minimum; high-weight rooms exceed it.
        for (spec, &a) in p.iter().zip(&areas) {
            assert!(a >= spec.min_area - 0.01, "{} below min: {a} < {}", spec.id, spec.min_area);
        }
        let living = areas[p.iter().position(|r| r.id == "living").unwrap()];
        assert!(living > 200.0, "living should absorb slack, got {living}");
    }

    #[test]
    fn subdivide_places_every_room_inside_the_envelope() {
        let a = Answers::default();
        let p = program_from_answers(&a).unwrap();
        let (w, d) = auto_size(&p, 0.0);
        let env = Rect { x: 0.0, y: 0.0, w, h: d };
        let placed = subdivide(env, &p, "south", "switchback", &AdjacencyGraph::new_for_mode(BuildingMode::Part9));
        assert_eq!(placed.len(), p.len(), "every room placed");
        for r in &placed {
            assert!(r.rect.x >= -0.01 && r.rect.y >= -0.01);
            assert!(r.rect.x + r.rect.w <= w + 0.01);
            assert!(r.rect.y + r.rect.h <= d + 0.01);
            assert!(r.rect.area() > 0.0);
        }
        // Placed area tiles the whole envelope (BSP leaves no gaps).
        let total: f32 = placed.iter().map(|r| r.rect.area()).sum();
        assert!((total - w * d).abs() < 1.0, "tiled {total} vs {}", w * d);
    }

    #[test]
    fn bedroom_floor_every_bedroom_opens_onto_the_hall() {
        let p = vec![
            RoomSpec::new("stairs", "stairs", 1.0, 60.0),
            RoomSpec::new("hallway_2", "hallway", 1.0, 40.0),
            RoomSpec::new("primary_bedroom", "primary_bedroom", 3.0, 140.0),
            RoomSpec::new("primary_bath", "primary_bath", 1.0, 50.0),
            RoomSpec::new("primary_closet", "walk_in_closet", 1.0, 25.0),
            RoomSpec::new("bedroom_2", "bedroom", 2.5, 110.0),
            RoomSpec::new("closet_2", "closet", 1.0, 15.0),
            RoomSpec::new("bedroom_3", "bedroom", 2.5, 110.0),
            RoomSpec::new("closet_3", "closet", 1.0, 15.0),
        ];
        assert!(is_bedroom_floor(&p), "should be detected as a bedroom floor");
        let env = Rect { x: 0.0, y: 0.0, w: 38.0, h: 27.0 };
        let placed = subdivide(env, &p, "south", "switchback", &AdjacencyGraph::new_for_mode(BuildingMode::Part9));
        let hall = placed.iter().find(|r| r.room_type == "hallway").expect("hall").rect;
        let abuts = |a: &Rect, b: &Rect| -> bool {
            let vert = ((a.x + a.w - b.x).abs() < 0.6 || (b.x + b.w - a.x).abs() < 0.6)
                && a.y.max(b.y) < (a.y + a.h).min(b.y + b.h) - 0.5;
            let horiz = ((a.y + a.h - b.y).abs() < 0.6 || (b.y + b.h - a.y).abs() < 0.6)
                && a.x.max(b.x) < (a.x + a.w).min(b.x + b.w) - 0.5;
            vert || horiz
        };
        for room in &placed {
            if room.room_type.contains("bedroom") {
                assert!(abuts(&room.rect, &hall), "{} does not open onto the hall", room.id);
            }
        }
    }

    #[test]
    fn window_rooms_reach_the_perimeter_for_typical_programs() {
        // The egress-guarantee bias should put every daylight/egress room on
        // an exterior wall for ordinary 3- and 4-bed houses.
        for (bd, ba, sqft) in [(3, 2, 1800.0), (4, 3, 2400.0), (2, 2, 1400.0)] {
            let a = Answers {
                bedrooms: bd,
                bathrooms: ba,
                sqft,
                garage: "none".into(),
                special_rooms: vec![],
                storeys: 1, // this test exercises single-floor perimeter logic
                window_intent: "balanced".into(),
                style: "balanced".into(),
                ..Answers::default()
            };
            let p = program_from_answers(&a).unwrap();
            let (w, d) = auto_size(&p, sqft);
            let env = Rect { x: 0.0, y: 0.0, w, h: d };
            let placed = subdivide(env, &p, "south", "switchback", &AdjacencyGraph::new_for_mode(BuildingMode::Part9));
            let touches = |r: &Rect| {
                r.x <= 0.5 || r.y <= 0.5 || r.x + r.w >= w - 0.5 || r.y + r.h >= d - 0.5
            };
            for room in &placed {
                if regime_obc::windows::needs_window(&room.room_type) {
                    assert!(
                        touches(&room.rect),
                        "{}-bed: {} needs a window but is interior",
                        bd,
                        room.id
                    );
                }
            }
        }
    }

    #[test]
    #[allow(clippy::many_single_char_names)]
    fn each_bedroom_is_adjacent_to_its_own_closet() {
        let a = Answers {
            bedrooms: 4,
            bathrooms: 3,
            sqft: 2400.0,
            garage: "none".into(),
            special_rooms: vec![],
            storeys: 1,
            window_intent: "balanced".into(),
            style: "balanced".into(),
            ..Answers::default()
        };
        let p = program_from_answers(&a).unwrap();
        let (w, d) = auto_size(&p, a.sqft);
        let placed = subdivide(Rect { x: 0.0, y: 0.0, w, h: d }, &p, "south", "switchback", &AdjacencyGraph::new_for_mode(BuildingMode::Part9));
        let rect_of = |id: &str| placed.iter().find(|r| r.id == id).map(|r| r.rect);
        let adjacent = |x: Rect, y: Rect| {
            let e = 0.5;
            let vshare = (x.y.max(y.y)) < (x.y + x.h).min(y.y + y.h) - e;
            let hshare = (x.x.max(y.x)) < (x.x + x.w).min(y.x + y.w) - e;
            ((x.x + x.w - y.x).abs() < e || (y.x + y.w - x.x).abs() < e) && vshare
                || ((x.y + x.h - y.y).abs() < e || (y.y + y.h - x.y).abs() < e) && hshare
        };
        for (bed, closet) in [
            ("bedroom_2", "closet_2"),
            ("bedroom_3", "closet_3"),
            ("bedroom_4", "closet_4"),
            ("primary_bedroom", "primary_bath"),
            ("primary_bedroom", "primary_closet"),
        ] {
            let (b, c) = (rect_of(bed).unwrap(), rect_of(closet).unwrap());
            assert!(adjacent(b, c), "{bed} not adjacent to {closet}");
        }
    }

    #[test]
    fn public_zone_sits_at_the_entry_edge_south() {
        let a = Answers::default();
        let p = program_from_answers(&a).unwrap();
        let env = Rect { x: 0.0, y: 0.0, w: 60.0, h: 40.0 };
        let placed = subdivide(env, &p, "south", "switchback", &AdjacencyGraph::new_for_mode(BuildingMode::Part9));
        // South entry → public rooms at low Y, private at high Y.
        let public_y: f32 = placed
            .iter()
            .filter(|r| r.zone == Zone::Public)
            .map(|r| r.rect.y)
            .sum::<f32>()
            / placed.iter().filter(|r| r.zone == Zone::Public).count().max(1) as f32;
        let private_y: f32 = placed
            .iter()
            .filter(|r| r.zone == Zone::Private)
            .map(|r| r.rect.y)
            .sum::<f32>()
            / placed.iter().filter(|r| r.zone == Zone::Private).count().max(1) as f32;
        assert!(public_y < private_y, "public {public_y} should be nearer entry than private {private_y}");
    }

    #[test]
    fn solver_populates_scene_rooms_from_answers() {
        let solver = SubdivisionRoomSolver::from_answers(&Answers::default());
        let mut scene = Scene::new();
        solver.solve(&mut scene);
        let rooms = scene.objects.iter().filter(|o| o.kind == "room").count();
        assert_eq!(rooms, solver.program.len());
        // Idempotent.
        solver.solve(&mut scene);
        assert_eq!(scene.objects.iter().filter(|o| o.kind == "room").count(), rooms);
    }

    #[test]
    fn solver_honours_stair_config_from_answers() {
        let a = Answers {
            bedrooms: 3,
            bathrooms: 2,
            sqft: 1800.0,
            storeys: 2,
            stair_config: "straight".into(),
            ..Default::default()
        };
        let solver = SubdivisionRoomSolver::from_answers(&a);
        assert_eq!(solver.stair_config, "straight");
    }

    #[test]
    fn stair_bay_geometries_are_buildable_and_obc_compliant() {
        // 10 ft floor-to-floor.
        let sw = stair_bay("switchback");
        assert_eq!(sw.shape, "switchback");
        assert!(sw.flight_clear_mm >= 860.0, "switchback flight clear {} < 860", sw.flight_clear_mm);
        assert!(sw.well_mm > 0.0);
        // A switchback is deeper than wide (two flights run along the depth).
        assert!(sw.depth_mm > sw.width_mm, "switchback depth {} <= width {}", sw.depth_mm, sw.width_mm);

        let st = stair_bay("straight");
        assert_eq!(st.shape, "straight");
        assert!(st.flight_clear_mm >= 860.0);
        assert_eq!(st.well_mm, 0.0);
        // A straight run is longer than it is wide.
        assert!(st.depth_mm > st.width_mm, "straight should be deeper than wide: {} x {}", st.depth_mm, st.width_mm);

        let l = stair_bay("l_shaped");
        assert_eq!(l.shape, "l_shaped");
        assert!(l.flight_clear_mm >= 860.0);
        // L-shaped bay is roughly square-ish and smaller than switchback.
        assert!(l.width_mm > 0.0 && l.depth_mm > 0.0);
    }

    #[test]
    fn straight_stair_layout_reserves_a_buildable_bay() {
        let a = Answers {
            bedrooms: 3,
            bathrooms: 2,
            sqft: 1800.0,
            garage: "none".into(),
            special_rooms: vec![],
            storeys: 2,
            stair_config: "straight".into(),
            ..Default::default()
        };
        let p = program_from_answers(&a).unwrap();
        let floors = split_floors(&p, 2);
        let ground = &floors[0];
        let (w, d) = auto_size(ground, a.sqft / 2.0); // per-floor footprint
        let placed = subdivide(Rect { x: 0.0, y: 0.0, w, h: d }, ground, "south", "straight", &AdjacencyGraph::new_for_mode(BuildingMode::Part9));
        let stairs = placed.iter().find(|r| r.room_type == "stairs").expect("stairs room");
        // The reserved stair bay is the buildable straight footprint, shrunk only if
        // the envelope genuinely cannot fit it.
        let (bay_w, bay_d) = stair_bay_ft("straight");
        let sw = bay_w.min(w * 0.7);
        let run = bay_d.min(d * 0.85);
        assert!((stairs.rect.w - sw).abs() < 0.5, "stairs width {} != expected {}", stairs.rect.w, sw);
        assert!((stairs.rect.h - run).abs() < 0.5, "stairs depth {} != expected {}", stairs.rect.h, run);
    }

    #[test]
    fn multi_storey_stairs_are_stacked_regardless_of_config() {
        for config in ["switchback", "straight", "l_shaped"] {
            let a = Answers {
                bedrooms: 4,
                bathrooms: 3,
                sqft: 2400.0,
                garage: "2car".into(),
                special_rooms: vec![],
                storeys: 2,
                stair_config: config.into(),
                ..Default::default()
            };
            let v = building_json(&a);
            let rooms = v["rooms"].as_object().unwrap();
            let s1 = &rooms["stairs_1"]["bounds"];
            let s2 = &rooms["stairs_2"]["bounds"];
            for k in ["x", "y", "width", "height"] {
                let (x, y) = (s1[k].as_f64().unwrap(), s2[k].as_f64().unwrap());
                assert!((x - y).abs() < 1.0, "{config}: stairs not aligned on {k}: {x} vs {y}");
            }
        }
    }
}
