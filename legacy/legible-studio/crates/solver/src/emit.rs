//! Emit a placed layout as a `qbd_output.schema.json` building bundle.
//!
//! Port of `qbd_layout_generator`'s `layout_to_walls/doors/rooms_data/
//! levels/dimensions` + `subdivision_solver::_generate_walls`. Walls are
//! the envelope perimeter (exterior, with an entry door) plus interior
//! partitions along each adjacent-room boundary (each with a centred
//! door). Output is ARCHENGINE format (mm) — feet × 304.8.
//!
//! This completes the pure-Rust `answers → schema-valid bundle` path; no
//! Python in the loop.

use crate::{
    footprint_for, layout_floor, plan_floors, program_from_answers, shape_envelope, split_floors,
    subdivide, AdjacencyGraph, Answers, BuildingMode, PlacedRoom, Rect, Zone,
};
use serde_json::{json, Value};

const FEET_TO_MM: f32 = 304.8;
const WALL_HEIGHT_FT: f32 = 9.0; // 9' plate
const DOOR_WIDTH_FT: f32 = 3.0;
const DOOR_HEIGHT_FT: f32 = 6.67; // 6'8"
const EPS: f32 = 0.01;

struct Opening {
    start: (f32, f32),
    end: (f32, f32),
}

struct Wall {
    start: (f32, f32),
    end: (f32, f32),
    category: &'static str, // "exterior" | "interior"
    room1: String,
    room2: String,
    openings: Vec<Opening>,
}

/// One laid-out storey: its rooms, walls and windows in the shared footprint.
struct Floor {
    level: usize, // 1-based
    rooms: Vec<PlacedRoom>,
    walls: Vec<Wall>,
    windows: Vec<WindowOut>,
}

/// Full pipeline: answers → program → split across storeys → per-floor
/// auto-size/subdivide/walls/windows → combined bundle JSON. `sqft` is the
/// **total** across storeys, so each floor targets `sqft / storeys`; all
/// floors share one (stacked) footprint sized to the largest floor's program.
#[must_use]
pub fn building_json(answers: &Answers) -> Value {
    let program = match program_from_answers(answers) {
        Ok(p) => p,
        Err(e) => {
            return json!({
                "success": false,
                "error": e.to_string(),
            });
        }
    };
    let floors_n = answers.floor_count();
    let programs = split_floors(&program, floors_n);
    #[allow(clippy::cast_precision_loss)]
    let per_floor_target = answers.sqft / floors_n as f32;

    // One footprint, big enough for every floor's program.
    let footprint = programs
        .iter()
        .map(|p| footprint_for(p, per_floor_target))
        .fold(per_floor_target, f32::max);
    let (w, d) = shape_envelope(footprint);
    let envelope = Rect { x: 0.0, y: 0.0, w, h: d };

    let graph = AdjacencyGraph::new_for_mode(answers.mode);
    let floors: Vec<Floor> = programs
        .iter()
        .enumerate()
        .map(|(i, pgm)| {
            let rooms = subdivide(envelope, pgm, "south", &answers.stair_config, &graph);
            let is_ground = i == 0;
            let walls = generate_walls(&rooms, envelope, is_ground);
            let windows = generate_windows(&rooms, envelope, &answers.window_intent, &answers.style);
            Floor { level: i + 1, rooms, walls, windows }
        })
        .collect();

    to_json(answers, envelope, &floors)
}

/// Manifest-driven pipeline: ProgramManifest → per-floor plan inputs → layout
/// strategies → walls/doors/windows → schema-valid building JSON. This is the
/// Part 3 / mixed-use entry point; it intentionally skips residential-only
/// annotations (smoke/CO detectors, electrical spacing) for non-Part 9 floors.
#[must_use]
pub fn building_json_from_manifest(manifest: &crate::ProgramManifest) -> Value {
    let plans = plan_floors(manifest);
    let envelope = plans.first().map_or(
        Rect { x: 0.0, y: 0.0, w: 40.0, h: 40.0 },
        |p| p.envelope,
    );
    let graph = AdjacencyGraph::new_for_mode(manifest.mode).with_manifest(manifest);

    let floors: Vec<Floor> = plans
        .iter()
        .map(|plan| {
            let rooms = layout_floor(plan, &graph);
            let is_ground = plan.level == 1;
            let walls = generate_walls(&rooms, plan.envelope, is_ground);
            // Part 3 windows: use a balanced intent and contemporary style by
            // default; egress rules are deferred to the Part 3 rules engine.
            let window_intent = "balanced";
            let style = "contemporary";
            let windows = generate_windows(&rooms, plan.envelope, window_intent, style);
            Floor {
                level: plan.level,
                rooms,
                walls,
                windows,
            }
        })
        .collect();

    to_json_manifest(manifest, envelope, &floors, &plans)
}

/// Perimeter (exterior) + interior partition walls. On the ground floor, an
/// entry door sits on whichever exterior edge the `entry` room touches
/// (preferring the south/front wall); upper floors have no exterior door (the
/// stair is their access). Each interior wall gets a centred door.
fn generate_walls(rooms: &[PlacedRoom], env: Rect, is_ground: bool) -> Vec<Wall> {
    let (x0, y0, x1, y1) = (env.x, env.y, env.x + env.w, env.y + env.h);
    let half = DOOR_WIDTH_FT * 0.5;
    let mut walls = Vec::new();

    // On a dedicated bedroom floor, only door rooms that should connect (so the
    // hall reaches every bedroom and we don't door bedroom-to-bedroom or
    // closet-to-hall). The main floor keeps a door on every shared wall.
    let bed_floor = rooms.iter().any(|r| r.room_type.contains("bedroom"))
        && rooms.iter().any(|r| r.room_type == "hallway")
        && !rooms
            .iter()
            .any(|r| matches!(r.room_type.as_str(), "entry" | "living" | "kitchen" | "great_room"));

    // Exterior perimeter, CCW from south-west: indices 0=south, 1=east,
    // 2=north, 3=west.
    for (s, e) in [
        ((x0, y0), (x1, y0)),
        ((x1, y0), (x1, y1)),
        ((x1, y1), (x0, y1)),
        ((x0, y1), (x0, y0)),
    ] {
        walls.push(Wall {
            start: s,
            end: e,
            category: "exterior",
            room1: "exterior".into(),
            room2: "exterior".into(),
            openings: Vec::new(),
        });
    }

    // Entry door (ground floor only) on whichever exterior edge the entry room
    // touches — preferring south (front), then east, west, north.
    if let Some(entry) = rooms.iter().find(|r| is_ground && r.id == "entry") {
        const EPS: f32 = 0.5;
        let e = entry.rect;
        let (cx, cy) = (e.x + e.w * 0.5, e.y + e.h * 0.5);
        let door = if (e.y - y0).abs() < EPS {
            Some((0, Opening { start: (cx - half, y0), end: (cx + half, y0) }))
        } else if ((e.x + e.w) - x1).abs() < EPS {
            Some((1, Opening { start: (x1, cy - half), end: (x1, cy + half) }))
        } else if (e.x - x0).abs() < EPS {
            Some((3, Opening { start: (x0, cy - half), end: (x0, cy + half) }))
        } else if ((e.y + e.h) - y1).abs() < EPS {
            Some((2, Opening { start: (cx - half, y1), end: (cx + half, y1) }))
        } else {
            None // entry somehow interior — no phantom door
        };
        if let Some((wi, op)) = door {
            walls[wi].openings.push(op);
        }
    }

    // Garage overhead door (ground floor) on whichever street-facing exterior
    // wall the garage fronts — preferring south, so it shares the facade with
    // the front door. Wider than a person door (most of the garage frontage).
    if let Some(g) = rooms.iter().find(|r| is_ground && r.room_type == "garage") {
        const EPS: f32 = 0.5;
        let gr = g.rect;
        let (cx, cy) = (gr.x + gr.w * 0.5, gr.y + gr.h * 0.5);
        let hw = (gr.w * 0.82).clamp(8.0, 18.0) * 0.5; // half overhead-door width
        let hh = (gr.h * 0.82).clamp(8.0, 18.0) * 0.5; // when it fronts a side wall
        let door = if (gr.y - y0).abs() < EPS {
            Some((0, Opening { start: (cx - hw, y0), end: (cx + hw, y0) }))
        } else if ((gr.x + gr.w) - x1).abs() < EPS {
            Some((1, Opening { start: (x1, cy - hh), end: (x1, cy + hh) }))
        } else if (gr.x - x0).abs() < EPS {
            Some((3, Opening { start: (x0, cy - hh), end: (x0, cy + hh) }))
        } else if ((gr.y + gr.h) - y1).abs() < EPS {
            Some((2, Opening { start: (cx - hw, y1), end: (cx + hw, y1) }))
        } else {
            None
        };
        if let Some((wi, op)) = door {
            walls[wi].openings.push(op);
        }
    }

    // Interior partitions: for each adjacent room pair, the shared boundary.
    for i in 0..rooms.len() {
        for j in (i + 1)..rooms.len() {
            if let Some((s, e)) = shared_edge(&rooms[i].rect, &rooms[j].rect) {
                let mut wall = Wall {
                    start: s,
                    end: e,
                    category: "interior",
                    room1: rooms[i].id.clone(),
                    room2: rooms[j].id.clone(),
                    openings: Vec::new(),
                };
                // Centred door if the shared edge is wide enough — and, on a
                // bedroom floor, only between rooms that should connect. The
                // garage reaches the house through a single service/entry door,
                // never straight into the living/kitchen.
                let len = ((e.0 - s.0).powi(2) + (e.1 - s.1).powi(2)).sqrt();
                let (ta, tb) = (&rooms[i].room_type, &rooms[j].room_type);
                let wants_door = if ta == "garage" || tb == "garage" {
                    false // garage doors are added in a post-pass: exactly one
                } else if bed_floor {
                    door_between(ta, tb)
                } else {
                    true
                };
                if wants_door && len > DOOR_WIDTH_FT + 1.0 {
                    let t0 = (len * 0.5 - half) / len;
                    let t1 = (len * 0.5 + half) / len;
                    let lerp = |t: f32| (s.0 + (e.0 - s.0) * t, s.1 + (e.1 - s.1) * t);
                    wall.openings.push(Opening {
                        start: lerp(t0),
                        end: lerp(t1),
                    });
                }
                walls.push(wall);
            }
        }
    }

    // Garage → house: exactly one pedestrian door, on the widest interior wall
    // the garage shares with a service/circulation room (mudroom/entry/foyer/
    // hallway/kitchen/laundry), falling back to its widest interior wall. Done
    // as a post-pass so the garage never opens straight into the living/dining
    // yet always has one door (for access + its light switch).
    if let Some(garage) = rooms.iter().find(|r| r.room_type == "garage") {
        let gid = garage.id.clone();
        let room_type = |id: &str| rooms.iter().find(|r| r.id == id).map_or("", |r| r.room_type.as_str());
        let preferred = |t: &str| {
            matches!(t, "mudroom" | "entry" | "foyer" | "hallway" | "kitchen" | "laundry")
        };
        let wall_len = |w: &Wall| ((w.end.0 - w.start.0).powi(2) + (w.end.1 - w.start.1).powi(2)).sqrt();
        let other = |w: &Wall| -> &str {
            if w.room1 == gid { room_type(&w.room2) } else { room_type(&w.room1) }
        };
        let pick = walls
            .iter()
            .enumerate()
            .filter(|(_, w)| {
                w.category == "interior"
                    && (w.room1 == gid || w.room2 == gid)
                    && wall_len(w) > DOOR_WIDTH_FT + 1.0
            })
            .max_by(|(_, a), (_, b)| {
                preferred(other(a))
                    .cmp(&preferred(other(b)))
                    .then(wall_len(a).total_cmp(&wall_len(b)))
            })
            .map(|(idx, _)| idx);
        if let Some(idx) = pick {
            let (s, e) = (walls[idx].start, walls[idx].end);
            let len = ((e.0 - s.0).powi(2) + (e.1 - s.1).powi(2)).sqrt();
            let t0 = (len * 0.5 - half) / len;
            let t1 = (len * 0.5 + half) / len;
            let lerp = |t: f32| (s.0 + (e.0 - s.0) * t, s.1 + (e.1 - s.1) * t);
            walls[idx].openings.push(Opening { start: lerp(t0), end: lerp(t1) });
        }
    }

    walls
}

/// Whether two rooms on a bedroom floor should share a door. Circulation
/// (hall/stairs) reaches habitable rooms but not closets or the ensuite; a
/// closet opens to its bedroom (or the bath it sits behind); the ensuite opens
/// to the bedroom. Bedrooms never door to each other.
fn door_between(a: &str, b: &str) -> bool {
    fn circ(t: &str) -> bool {
        matches!(t, "hallway" | "corridor" | "stairs" | "entry" | "foyer" | "mudroom" | "landing")
    }
    let closet = |t: &str| t.contains("closet");
    let bedroom = |t: &str| t.contains("bedroom");
    let connect = |a: &str, b: &str| -> bool {
        if a == "stairs" {
            return matches!(b, "hallway" | "corridor" | "landing" | "foyer"); // stairs reach the hall/corridor
        }
        if circ(a) {
            return !closet(b) && b != "primary_bath"; // hall/corridor → bedroom/bath/stair
        }
        if closet(a) {
            return bedroom(b); // a closet opens only to its bedroom, never the
                               // bath it backs onto
        }
        if a == "primary_bath" {
            return bedroom(b); // ensuite → the bedroom
        }
        // A shared bathroom opens off the hall (handled by the circ branch),
        // never directly into a bedroom.
        false
    };
    connect(a, b) || connect(b, a)
}

/// The shared boundary segment between two axis-aligned rects, if they abut
/// with a non-trivial overlap (vertical or horizontal).
fn shared_edge(a: &Rect, b: &Rect) -> Option<((f32, f32), (f32, f32))> {
    let (ax1, ay1, ax2, ay2) = (a.x, a.y, a.x + a.w, a.y + a.h);
    let (bx1, by1, bx2, by2) = (b.x, b.y, b.x + b.w, b.y + b.h);

    // Vertical shared edge (a.right == b.left or vice-versa).
    for &x in &[(ax2, bx1), (bx2, ax1)] {
        if (x.0 - x.1).abs() < EPS {
            let lo = ay1.max(by1);
            let hi = ay2.min(by2);
            if hi - lo > 1.0 {
                return Some(((x.0, lo), (x.0, hi)));
            }
        }
    }
    // Horizontal shared edge (a.top == b.bottom or vice-versa).
    for &y in &[(ay2, by1), (by2, ay1)] {
        if (y.0 - y.1).abs() < EPS {
            let lo = ax1.max(bx1);
            let hi = ax2.min(bx2);
            if hi - lo > 1.0 {
                return Some(((lo, y.0), (hi, y.0)));
            }
        }
    }
    None
}

/// A window placed on one of the four exterior perimeter walls.
struct WindowOut {
    wall_index: usize,
    offset: f32, // mm along the wall from its start point
    width: f32,  // mm
    height: f32, // mm
    sill: f32,   // mm above floor
    win_type: &'static str,
    room: String,
}

/// OBC-driven window pass (Part 9). For every room with a daylight or egress
/// duty ([`obc::windows`]), place one window on the longest exterior edge the
/// room touches, sized to satisfy the glazing fraction (and the egress minimum
/// for bedrooms). Rooms with no exterior wall get none — a real OBC gap for
/// interior habitable rooms, surfaced rather than papered over.
///
/// This is the placement seam the window-design work plugs into: the *rules*
/// live in `obc`, the *strategy* (which wall, how big, where along it) is here
/// and can be replaced wholesale without touching either side.
fn generate_windows(rooms: &[PlacedRoom], env: Rect, intent: &str, style: &str) -> Vec<WindowOut> {
    use obc::windows as w;
    const SILL_MM: f32 = 900.0;
    const EDGE_EPS: f32 = 0.5; // feet — room edge ≈ envelope edge

    // Layer-3 user intent: scale glazing above the OBC minimum and bias which
    // exterior walls get windows. The legal minimum + egress always hold.
    let mult = match intent {
        "privacy" => 1.0,
        "more_light" => 1.7,
        "south_bank" => 1.4,
        _ => 1.2, // "balanced" / default — a small comfort margin over the min
    };

    // Layer-2 architectural style: how many windows bank along a wall, their
    // type, and their proportion (head height, mm). Egress overrides the type
    // with an openable casement.
    let (bank, style_type, win_h) = match style {
        "ranch" => (2, "sliding", 1000.0),        // wide, low horizontal bands
        "colonial" => (2, "double_hung", 1500.0), // tall, symmetric pairs
        "contemporary" => (1, "fixed", 1700.0),   // a single large pane
        _ => (1, "double_hung", 1200.0),          // "balanced" / default
    };

    let s = FEET_TO_MM;
    let (x0, y0, x1, y1) = (env.x, env.y, env.x + env.w, env.y + env.h);
    let mut out = Vec::new();
    for r in rooms {
        if !w::needs_window(&r.room_type) {
            continue;
        }
        // Required glazing area (m²): the OBC fraction × intent, floored by
        // egress for bedrooms.
        let area_m2 = (r.rect.w * s / 1000.0) * (r.rect.h * s / 1000.0);
        let egress = w::requires_egress(&r.room_type);
        let mut need_m2 = area_m2 * w::glazing_fraction(&r.room_type) * mult;
        if egress {
            need_m2 = need_m2.max(w::EGRESS_MIN_AREA_M2);
        }
        if need_m2 <= 0.0 {
            continue;
        }

        // Exterior edges this room touches: (wall_index, span_ft, dist_from_wall_start_ft).
        let (cx, cy) = (r.rect.x + r.rect.w * 0.5, r.rect.y + r.rect.h * 0.5);
        let mut cands: Vec<(usize, f32, f32)> = Vec::new();
        if (r.rect.y - y0).abs() < EDGE_EPS {
            cands.push((0, r.rect.w, cx - x0)); // south: +x from x0
        }
        if ((r.rect.x + r.rect.w) - x1).abs() < EDGE_EPS {
            cands.push((1, r.rect.h, cy - y0)); // east: +y from y0
        }
        if ((r.rect.y + r.rect.h) - y1).abs() < EDGE_EPS {
            cands.push((2, r.rect.w, x1 - cx)); // north: -x from x1
        }
        if (r.rect.x - x0).abs() < EDGE_EPS {
            cands.push((3, r.rect.h, y1 - cy)); // west: -y from y1
        }
        if cands.is_empty() {
            continue; // interior room, no exterior wall
        }
        let longest = |c: &[(usize, f32, f32)]| {
            *c.iter()
                .max_by(|a, b| a.1.partial_cmp(&b.1).unwrap_or(std::cmp::Ordering::Equal))
                .unwrap()
        };

        // Which exterior wall(s) get windows, per intent.
        let chosen: Vec<(usize, f32, f32)> = match intent {
            // Spread across every exterior wall the room touches.
            "more_light" => cands.clone(),
            // Concentrate on the south wall (wall_index 0) when available.
            "south_bank" => vec![cands.iter().find(|c| c.0 == 0).copied().unwrap_or_else(|| longest(&cands))],
            // Default / privacy: one window on the longest exterior wall.
            _ => vec![longest(&cands)],
        };

        // Split the glazing across the chosen walls.
        #[allow(clippy::cast_precision_loss)]
        let per_m2 = need_m2 / chosen.len() as f32;
        let win_type = if egress { "casement" } else { style_type };
        let sill = if egress { SILL_MM.min(w::EGRESS_MAX_SILL_MM) } else { SILL_MM };
        for &(wall_index, span_ft, dist_ft) in &chosen {
            let wall_len_mm = if wall_index % 2 == 0 { env.w * s } else { env.h * s };
            // Bank `n` windows evenly along the room's run of this wall (style),
            // but never more than fit at ~700mm slots.
            #[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)]
            let max_fit = ((span_ft * s * 0.8) / 700.0) as usize;
            let n = bank.min(max_fit).max(1);
            // Total glazing width on this wall, split into n equal panes.
            let total_w = (per_m2 / (win_h / 1000.0)) * 1000.0;
            #[allow(clippy::cast_precision_loss)]
            let each_w = (total_w / n as f32)
                .max(w::EGRESS_MIN_DIMENSION_MM)
                .min(span_ft * s * 0.8 / n as f32);
            // The room's run along this wall starts half a span before its centre.
            let room_left_mm = (dist_ft - span_ft * 0.5) * s;
            let span_mm = span_ft * s;
            for k in 0..n {
                #[allow(clippy::cast_precision_loss)]
                let centre = room_left_mm + span_mm * ((k as f32 + 0.5) / n as f32);
                let offset = (centre - each_w * 0.5).clamp(0.0, (wall_len_mm - each_w).max(0.0));
                out.push(WindowOut {
                    wall_index,
                    offset,
                    width: each_w,
                    height: win_h,
                    sill,
                    win_type,
                    room: r.id.clone(),
                });
            }
        }
    }
    out
}

/// A placed life-safety alarm (smoke / CO), centred in its room (ceiling
/// fixture); position in mm.
struct DetectorOut {
    kind: &'static str, // "smoke" | "co"
    x: f32,
    y: f32,
    level: usize,
    room: String,
}

/// Deterministic smoke/CO alarm placement (OBC 9.10.19 + 9.33.4) — the first
/// rules-engine annotation category. A smoke alarm in every bedroom and one
/// per storey (in the hall serving the bedrooms, else the largest room); a CO
/// alarm by the sleeping area on bedroom storeys when there's an attached
/// garage. Rules live in `obc::detectors`; placement (room centre) is here.
fn generate_detectors(floors: &[Floor], answers: &Answers) -> Vec<DetectorOut> {
    let s = FEET_TO_MM;
    let co_required = obc::detectors::requires_co_alarm(answers.garage != "none", false);
    let is_bed = |rt: &str| rt == "bedroom" || rt == "primary_bedroom";
    let centre = |r: &PlacedRoom| ((r.rect.x + r.rect.w * 0.5) * s, (r.rect.y + r.rect.h * 0.5) * s);

    let mut out = Vec::new();
    for floor in floors {
        // One smoke alarm in each bedroom.
        for r in floor.rooms.iter().filter(|r| is_bed(&r.room_type)) {
            let (x, y) = centre(r);
            out.push(DetectorOut { kind: "smoke", x, y, level: floor.level, room: r.id.clone() });
        }
        // One serving the storey: the hall if present, else the largest room.
        let storey_room = floor.rooms.iter().find(|r| r.room_type == "hallway").or_else(|| {
            floor
                .rooms
                .iter()
                .max_by(|a, b| a.rect.area().partial_cmp(&b.rect.area()).unwrap_or(std::cmp::Ordering::Equal))
        });
        if let Some(r) = storey_room {
            let (x, y) = centre(r);
            out.push(DetectorOut { kind: "smoke", x, y, level: floor.level, room: r.id.clone() });
            // CO by the sleeping area on bedroom storeys (attached garage).
            if co_required && floor.rooms.iter().any(|r| is_bed(&r.room_type)) {
                out.push(DetectorOut { kind: "co", x: x + 450.0, y, level: floor.level, room: r.id.clone() });
            }
        }
    }
    out
}

/// A placed electrical device (receptacle / gfci / light); position in mm.
struct ElectricalOut {
    kind: &'static str,
    x: f32,
    y: f32,
    level: usize,
    room: String,
}

/// Deterministic electrical layout (OESC 26-712 spacing + GFCI) — second
/// rules-engine category. Per room: a ceiling light at the centre, and
/// receptacles along each wall so no point is >1.8 m from one (spacing ≤3.6 m;
/// walls under 0.9 m skipped). Wet/garage rooms get GFCI receptacles. Rules
/// live in `obc::electrical`; placement is here.
#[allow(clippy::many_single_char_names)]
fn generate_electrical(floors: &[Floor]) -> Vec<ElectricalOut> {
    use obc::electrical as el;
    const FT_TO_M: f32 = 0.3048;
    let s = FEET_TO_MM;
    let mut out = Vec::new();
    for floor in floors {
        for r in &floor.rooms {
            let recep_kind = if el::requires_gfci(&r.room_type) { "gfci" } else { "receptacle" };
            // Ceiling light at the room centre.
            out.push(ElectricalOut {
                kind: "light",
                x: (r.rect.x + r.rect.w * 0.5) * s,
                y: (r.rect.y + r.rect.h * 0.5) * s,
                level: floor.level,
                room: r.id.clone(),
            });
            // Wall switch beside the room's entry (the first interior door that
            // borders it), controlling the light — OBC 9.34.2.2.
            if obc::electrical::SWITCH_AT_ROOM_ENTRANCE {
                for w in &floor.walls {
                    if w.room1 != r.id && w.room2 != r.id {
                        continue;
                    }
                    if let Some(op) = w.openings.first() {
                        let (dx, dy) = (op.end.0 - op.start.0, op.end.1 - op.start.1);
                        let len = (dx * dx + dy * dy).sqrt().max(1e-3);
                        // ~0.5 ft beyond the door's far edge, on the wall line.
                        out.push(ElectricalOut {
                            kind: "switch",
                            x: (op.end.0 + dx / len * 0.5) * s,
                            y: (op.end.1 + dy / len * 0.5) * s,
                            level: floor.level,
                            room: r.id.clone(),
                        });
                        break;
                    }
                }
            }
            // Receptacles along each of the four walls (skip stubs <0.9 m).
            let (x0, y0, x1, y1) = (r.rect.x, r.rect.y, r.rect.x + r.rect.w, r.rect.y + r.rect.h);
            // (along-length ft, fixed coord, horizontal?) per edge.
            let edges = [
                (r.rect.w, y0, true),  // south
                (r.rect.w, y1, true),  // north
                (r.rect.h, x0, false), // west
                (r.rect.h, x1, false), // east
            ];
            for (len_ft, fixed, horizontal) in edges {
                if len_ft * FT_TO_M < el::MIN_WALL_FOR_RECEPTACLE_M {
                    continue;
                }
                #[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)]
                let n = ((len_ft * FT_TO_M) / el::MAX_RECEPTACLE_SPACING_M).ceil().max(1.0) as usize;
                for k in 0..n {
                    #[allow(clippy::cast_precision_loss)]
                    let t = (k as f32 + 0.5) / n as f32;
                    let (x, y) = if horizontal {
                        (x0 + (x1 - x0) * t, fixed)
                    } else {
                        (fixed, y0 + (y1 - y0) * t)
                    };
                    out.push(ElectricalOut {
                        kind: recep_kind,
                        x: x * s,
                        y: y * s,
                        level: floor.level,
                        room: r.id.clone(),
                    });
                }
            }
        }
    }
    out
}

/// Floor-to-floor height (ft) — matches the 10 ft the `levels` use, so the
/// riser geometry agrees with the storey elevations.
const FLOOR_TO_FLOOR_FT: f32 = 10.0;
/// Central well between the two flights of a switchback (mm). Two flights plus
/// this well fit across the stair bay; each flight's clear width is the rest,
/// split in two.
const SWITCHBACK_WELL_MM: f32 = 100.0;
/// Side finish/stringer allowance deducted from a straight stair's bay width to
/// give its clear width (mm, both sides combined).
const STAIR_SIDE_FINISH_MM: f32 = 80.0;
/// Target clear-width minimum for Part 9 private stairs (mm).
const PART9_MIN_WIDTH_MM: f32 = 860.0;
/// Target clear-width minimum for Part 3 public stairs (mm).
const PART3_MIN_WIDTH_MM: f32 = 1100.0;

/// Stair geometry pass. Each storey's `stairs` room becomes a `SchemaStair`:
/// the riser/tread count comes from the appropriate OBC rules (Part 9 private
/// vs Part 3 public), and the *shape* is driven by `stair_config` when set,
/// falling back to a fit heuristic (straight when it fits, else switchback).
/// The drawing layer reads this to render the plan symbol; the compliance pass
/// reads it to check rise/run/width.
///
/// `going` is `"up"` on every storey that climbs to the one above and `"down"`
/// on the topmost storey's stair (the arrival from below).
fn generate_stairs(
    floors: &[Floor],
    ff_mm: f32,
    stair_config: &str,
    mode_for_floor: &dyn Fn(usize) -> BuildingMode,
) -> Vec<Value> {
    let s = FEET_TO_MM;
    let top_level = floors.iter().map(|f| f.level).max().unwrap_or(1);

    let mut out = Vec::new();
    for floor in floors {
        let mode = mode_for_floor(floor.level);
        let spec = match mode {
            BuildingMode::Part9 => obc::stairs::solve_stair(ff_mm),
            BuildingMode::Part3 | BuildingMode::Mixed => obc::part3::stairs::solve_public_stair(ff_mm),
        };
        let straight_run = spec.total_run_mm();
        let min_width = if mode.has_part3() {
            PART3_MIN_WIDTH_MM
        } else {
            PART9_MIN_WIDTH_MM
        };
        let going = if floor.level == top_level && top_level > 1 { "down" } else { "up" };
        for r in floor.rooms.iter().filter(|r| r.room_type == "stairs") {
            let w_mm = r.rect.w * s; // X extent of the bay
            let d_mm = r.rect.h * s; // Z extent of the bay
            // Run along the longer axis; the bay's front (low-Z / low-X) is the
            // bottom of the climb.
            let (run_dir, across, run_len) =
                if d_mm >= w_mm { ("+y", w_mm, d_mm) } else { ("+x", d_mm, w_mm) };
            let shape = match stair_config {
                "switchback" => "switchback",
                "l_shaped" | "l" | "quarter_turn" => "l_shaped",
                "straight" => "straight",
                // Default: pick the simplest shape that fits the bay.
                _ => if straight_run <= run_len + 1.0 { "straight" } else { "switchback" },
            };
            let width_clear = match shape {
                "switchback" => ((across - SWITCHBACK_WELL_MM) * 0.5).max(0.0),
                "l_shaped" => {
                    let ret = crate::l_return_treads(spec.num_treads) as f32 * spec.tread_run_mm;
                    (across - ret - STAIR_SIDE_FINISH_MM).max(0.0)
                }
                _ => (across - STAIR_SIDE_FINISH_MM).max(0.0),
            };
            // Clamp to the code minimum so a too-small bay is reported as a
            // compliance failure rather than silently under-sizing the stair.
            let width_clear = width_clear.max(min_width);
            out.push(json!({
                "id": r.id.clone(),
                "level_name": format!("Level {}", floor.level),
                "x": r.rect.x * s,
                "y": r.rect.y * s,
                "width": across,
                "depth": run_len,
                "run_dir": run_dir,
                "num_risers": spec.num_risers,
                "num_treads": spec.num_treads,
                "riser_height": spec.riser_height_mm,
                "tread_run": spec.tread_run_mm,
                "width_clear": width_clear,
                "floor_to_floor": ff_mm,
                "shape": shape,
                "going": going,
            }));
        }
    }
    out
}

#[allow(
    clippy::cast_possible_truncation,
    clippy::cast_sign_loss,
    clippy::cast_precision_loss,
    clippy::too_many_lines
)]
fn to_json(answers: &Answers, env: Rect, floors: &[Floor]) -> Value {
    let s = FEET_TO_MM;
    let p3 = |x: f32, y: f32| json!([x * s, 0.0, y * s]); // plan (x,y) → 3D (x,0,z)

    let mut walls_batch: Vec<Value> = Vec::new();
    let mut doors: Vec<Value> = Vec::new();
    let mut windows_json: Vec<Value> = Vec::new();
    let mut egress_warnings: Vec<Value> = Vec::new();
    let mut headers: Vec<Value> = Vec::new();
    let mut rooms_map = serde_json::Map::new();
    let mut wall_offset = 0usize; // walls_batch is global; per-floor indices shift by this

    for floor in floors {
        let level_name = format!("Level {}", floor.level);
        // Storeys bearing on this floor's headers: roof + every floor above.
        let stories_above = i32::try_from(floors.len() - floor.level + 1).unwrap_or(1);
        // Header (OBC 9.23.12) sized from an opening's width + storeys above.
        let mut header = |width_mm: f32, x: f32, y: f32, opening: &str| {
            let (size, review) = obc::headers::header_size_for(width_mm / s, stories_above);
            headers.push(json!({
                "size": size, "x": x, "y": y, "level_name": level_name,
                "opening": opening, "width": width_mm, "needs_review": review,
            }));
        };

        // Walls (global index = wall_offset + local).
        for (i, w) in floor.walls.iter().enumerate() {
            walls_batch.push(json!({
                "start": p3(w.start.0, w.start.1),
                "end": p3(w.end.0, w.end.1),
                "height": WALL_HEIGHT_FT * s,
                "wall_type": if w.category == "exterior" { "ext_2x6_r21" } else { "int_2x4" },
                "category": w.category,
                "level_name": level_name,
                "rooms": [w.room1.clone(), w.room2.clone()],
                "wall_index": wall_offset + i,
            }));
        }

        // Doors from wall openings (global wall_index).
        for (wi, w) in floor.walls.iter().enumerate() {
            for o in &w.openings {
                let (mx, my) = ((o.start.0 + o.end.0) * 0.5, (o.start.1 + o.end.1) * 0.5);
                let (cx, cy) = (mx * s, my * s);
                let width = ((o.end.0 - o.start.0).powi(2) + (o.end.1 - o.start.1).powi(2)).sqrt() * s;
                // Offset = distance from the wall start to the door centre (mm),
                // which is what add_door_primitives projects along the wall.
                let offset = ((mx - w.start.0).powi(2) + (my - w.start.1).powi(2)).sqrt() * s;
                doors.push(json!({
                    "x": cx, "y": cy, "width": width, "type": "door",
                    "height": DOOR_HEIGHT_FT * s, "wall_index": wall_offset + wi, "offset": offset,
                }));
                header(width, cx, cy, "door");
            }
        }

        // Windows (perimeter walls are the first of each floor's list, so the
        // local wall_index shifts by the same offset).
        for w in &floor.windows {
            windows_json.push(json!({
                "wall_index": wall_offset + w.wall_index,
                "offset": w.offset,
                "width": w.width,
                "height": w.height,
                "sill_height": w.sill,
                "type": w.win_type,
                "room": w.room,
                "level_name": level_name,
            }));
            // Header over the window: project its centre along the wall.
            if let Some(wall) = floor.walls.get(w.wall_index) {
                let (sx, sy) = (wall.start.0 * s, wall.start.1 * s);
                let (dx, dy) = ((wall.end.0 - wall.start.0) * s, (wall.end.1 - wall.start.1) * s);
                let len = (dx * dx + dy * dy).sqrt().max(1.0);
                let along = w.offset + w.width * 0.5;
                header(w.width, sx + dx / len * along, sy + dy / len * along, "window");
            }
        }

        // Egress flag: bedrooms on this floor with no exterior wall (OBC 9.9.10.1).
        for r in &floor.rooms {
            if obc::windows::requires_egress(&r.room_type)
                && !floor.windows.iter().any(|w| w.room == r.id)
            {
                egress_warnings.push(json!({
                    "room": r.id,
                    "level": level_name,
                    "code": "OBC 9.9.10.1",
                    "issue": "bedroom has no exterior wall for an egress window",
                }));
            }
        }

        // Rooms map (ids are unique across floors).
        for r in &floor.rooms {
            let zone = match r.zone {
                Zone::Public => "public",
                Zone::Circulation => "circulation",
                Zone::Service => "service",
                Zone::Private => "private",
            };
            let mut room_json = json!({
                "id": r.id,
                "name": title_case(&r.id),
                "level": level_name,
                "bounds": { "x": r.rect.x * s, "y": r.rect.y * s, "width": r.rect.w * s, "height": r.rect.h * s },
                "area": r.rect.area() * s * s,
                "center": { "x": (r.rect.x + r.rect.w * 0.5) * s, "y": (r.rect.y + r.rect.h * 0.5) * s },
                "room_type": r.room_type,
                "zone": zone,
            });
            if let Some(unit) = &r.unit {
                room_json["unit"] = json!(unit);
            }
            rooms_map.insert(
                r.id.clone(),
                room_json,
            );
        }

        wall_offset += floor.walls.len();
    }

    // Levels: one per storey + a roof on top, 10 ft floor-to-floor.
    let mut levels_v: Vec<Value> = (0..floors.len())
        .map(|i| {
            json!({
                "id": format!("level_{}", i + 1),
                "name": format!("Level {}", i + 1),
                "elevation": i as f32 * 10.0 * s,
                "floor_to_floor_height": 10.0 * s,
            })
        })
        .collect();
    levels_v.push(json!({
        "id": "roof_level", "name": "Roof Level",
        "elevation": floors.len() as f32 * 10.0 * s, "floor_to_floor_height": 0.0,
    }));
    let levels = Value::Array(levels_v);

    // dimensions: overall width + depth (shared footprint).
    let dimensions = json!([
        {
            "id": "dim_overall_w", "type": "linear",
            "start_point": p3(env.x, env.y), "end_point": p3(env.x + env.w, env.y),
            "value": env.w * s, "unit": "mm", "label": "Overall Width", "level": "Level 1",
        },
        {
            "id": "dim_overall_d", "type": "linear",
            "start_point": p3(env.x, env.y), "end_point": p3(env.x, env.y + env.h),
            "value": env.h * s, "unit": "mm", "label": "Overall Depth", "level": "Level 1",
        },
    ]);

    // Rules-engine annotations: life-safety alarms (OBC 9.10.19 / 9.33.4).
    let detectors = generate_detectors(floors, answers);
    let detectors_json: Vec<Value> = detectors
        .iter()
        .map(|d| {
            json!({
                "type": d.kind,
                "x": d.x,
                "y": d.y,
                "level_name": format!("Level {}", d.level),
                "room": d.room,
            })
        })
        .collect();

    // Rules-engine annotations: electrical (OESC receptacle spacing + GFCI).
    let electrical = generate_electrical(floors);
    let electrical_json: Vec<Value> = electrical
        .iter()
        .map(|e| {
            json!({
                "type": e.kind,
                "x": e.x,
                "y": e.y,
                "level_name": format!("Level {}", e.level),
                "room": e.room,
            })
        })
        .collect();

    // Rules-engine annotations: stairs (OBC 9.8 / 3.4.6 rise/run/width).
    let mode = answers.mode;
    let ff_mm = FLOOR_TO_FLOOR_FT * s;
    let stairs_json = generate_stairs(floors, ff_mm, &answers.stair_config, &move |_| mode);

    let circulation_graph = build_circulation_graph(floors);

    let total_walls: usize = floors.iter().map(|f| f.walls.len()).sum();
    let total_windows: usize = floors.iter().map(|f| f.windows.len()).sum();
    let total_rooms: usize = floors.iter().map(|f| f.rooms.len()).sum();
    let total_doors: usize = floors.iter().map(|f| doors_count(&f.walls)).sum();
    let ext = walls_batch.iter().filter(|w| w["category"] == "exterior").count();
    let int = total_walls - ext;
    let storeys = floors.len() as f32;
    let headers_len = headers.len();
    let headers_review = headers.iter().filter(|h| h["needs_review"] == json!(true)).count();

    json!({
        "success": true,
        "building_id": building_id(answers),
        "width": env.w * s,
        "depth": env.h * s,
        // Total built area across storeys (each floor tiles the footprint).
        "sqft": env.w * env.h * storeys,
        "storeys": floors.len(),
        "output_format": "archengine",
        "unit": "mm",
        "creative_mode": false,
        "walls_batch": walls_batch,
        "doors": doors,
        "windows": windows_json,
        "egress_warnings": egress_warnings,
        "detectors": detectors_json,
        "electrical": electrical_json,
        "headers": headers,
        "stairs": stairs_json,
        "levels": levels,
        "dimensions": dimensions,
        "circulation_graph": circulation_graph,
        "rooms": Value::Object(rooms_map),
        "is_complete": true,
        "unplaced_rooms": [],
        "score": 1.0,
        "summary": {
            "total_walls": total_walls,
            "exterior_walls": ext,
            "interior_walls": int,
            "wet_walls": 0,
            "doors": total_doors,
            "windows": total_windows,
            "egress_violations": egress_warnings.len(),
            "rooms_placed": total_rooms,
            "rooms_requested": total_rooms,
            "storeys": floors.len(),
            "detectors": detectors.len(),
            "electrical": electrical.len(),
            "stairs": stairs_json.len(),
            "headers": headers_len,
            "headers_need_review": headers_review,
        },
        "site": {
            "lot_width_ft": answers.lot_width_ft,
            "lot_depth_ft": answers.lot_depth_ft,
            "zone": answers.zone,
            "street": answers.street,
        },
        "roof_type": answers.roof_type,
        "qbd_answers": {
            "mode": answers.mode.as_str(),
            "building_type": "residential",
            "bedrooms": answers.bedrooms,
            "bathrooms": answers.bathrooms,
            // archgeometry's QBDAnswers.sqft is i32 — emit an integer (the
            // locked schema accepts string|number, but the Rust parser is
            // stricter, so round to keep the qbd_dump chain happy).
            "sqft": answers.sqft as i32,
            "garage": answers.garage,
        },
    })
}

/// Simplified JSON assembly for manifest-driven (Part 3 / mixed) buildings.
/// Reuses the wall/door/window/room conversion but omits residential-only
/// detector/electrical/header annotations.
#[allow(
    clippy::cast_possible_truncation,
    clippy::cast_sign_loss,
    clippy::cast_precision_loss,
    clippy::too_many_lines
)]
fn to_json_manifest(
    manifest: &crate::ProgramManifest,
    env: Rect,
    floors: &[Floor],
    plans: &[crate::FloorPlanInput],
) -> Value {
    let s = FEET_TO_MM;
    let p3 = |x: f32, y: f32| json!([x * s, 0.0, y * s]);

    let mut walls_batch: Vec<Value> = Vec::new();
    let mut doors: Vec<Value> = Vec::new();
    let mut windows_json: Vec<Value> = Vec::new();
    let mut rooms_map = serde_json::Map::new();
    let mut wall_offset = 0usize;

    for floor in floors {
        let level_name = format!("Level {}", floor.level);

        for (i, w) in floor.walls.iter().enumerate() {
            walls_batch.push(json!({
                "start": p3(w.start.0, w.start.1),
                "end": p3(w.end.0, w.end.1),
                "height": WALL_HEIGHT_FT * s,
                "wall_type": if w.category == "exterior" { "ext_2x6_r21" } else { "int_2x4" },
                "category": w.category,
                "level_name": level_name,
                "rooms": [w.room1.clone(), w.room2.clone()],
                "wall_index": wall_offset + i,
            }));
        }

        for (wi, w) in floor.walls.iter().enumerate() {
            for o in &w.openings {
                let (mx, my) = ((o.start.0 + o.end.0) * 0.5, (o.start.1 + o.end.1) * 0.5);
                let (cx, cy) = (mx * s, my * s);
                let width = ((o.end.0 - o.start.0).powi(2) + (o.end.1 - o.start.1).powi(2)).sqrt() * s;
                let offset = ((mx - w.start.0).powi(2) + (my - w.start.1).powi(2)).sqrt() * s;
                doors.push(json!({
                    "x": cx, "y": cy, "width": width, "type": "door",
                    "height": DOOR_HEIGHT_FT * s, "wall_index": wall_offset + wi, "offset": offset,
                }));
            }
        }

        for w in &floor.windows {
            windows_json.push(json!({
                "wall_index": wall_offset + w.wall_index,
                "offset": w.offset,
                "width": w.width,
                "height": w.height,
                "sill_height": w.sill,
                "type": w.win_type,
                "room": w.room,
                "level_name": level_name,
            }));
        }

        for r in &floor.rooms {
            let zone = match r.zone {
                Zone::Public => "public",
                Zone::Circulation => "circulation",
                Zone::Service => "service",
                Zone::Private => "private",
            };
            let mut room_json = json!({
                "id": r.id,
                "name": title_case(&r.id),
                "level": level_name,
                "bounds": { "x": r.rect.x * s, "y": r.rect.y * s, "width": r.rect.w * s, "height": r.rect.h * s },
                "area": r.rect.area() * s * s,
                "center": { "x": (r.rect.x + r.rect.w * 0.5) * s, "y": (r.rect.y + r.rect.h * 0.5) * s },
                "room_type": r.room_type,
                "zone": zone,
            });
            if let Some(unit) = &r.unit {
                room_json["unit"] = json!(unit);
            }
            rooms_map.insert(
                r.id.clone(),
                room_json,
            );
        }

        wall_offset += floor.walls.len();
    }

    let floor_to_floor_mm = manifest.floor_to_floor_ft * s;

    let levels_v: Vec<Value> = (0..floors.len())
        .map(|i| {
            let occ = plans.get(i).and_then(|p| p.occupancy.clone());
            let mut lvl = json!({
                "id": format!("level_{}", i + 1),
                "name": format!("Level {}", i + 1),
                "elevation": i as f32 * floor_to_floor_mm,
                "floor_to_floor_height": floor_to_floor_mm,
            });
            if let Some(o) = occ {
                lvl["occupancy"] = json!(o);
            }
            lvl
        })
        .collect();
    let levels = Value::Array(levels_v);

    let dimensions = json!([
        {
            "id": "dim_overall_w", "type": "linear",
            "start_point": p3(env.x, env.y), "end_point": p3(env.x + env.w, env.y),
            "value": env.w * s, "unit": "mm", "label": "Overall Width", "level": "Level 1",
        },
        {
            "id": "dim_overall_d", "type": "linear",
            "start_point": p3(env.x, env.y), "end_point": p3(env.x, env.y + env.h),
            "value": env.h * s, "unit": "mm", "label": "Overall Depth", "level": "Level 1",
        },
    ]);

    // Rules-engine annotations: stairs (OBC 9.8 / 3.4.6 rise/run/width).
    // Manifest-driven buildings default to a switchback public stair; the
    // questionnaire path lets the user pick the configuration.
    let stair_config = "switchback";
    let stair_mode = manifest.mode;
    let stairs_json = generate_stairs(floors, floor_to_floor_mm, stair_config, &|_| stair_mode);

    let circulation_graph = build_circulation_graph(floors);

    let total_walls: usize = floors.iter().map(|f| f.walls.len()).sum();
    let total_windows: usize = floors.iter().map(|f| f.windows.len()).sum();
    let total_rooms: usize = floors.iter().map(|f| f.rooms.len()).sum();
    let total_doors: usize = floors.iter().map(|f| doors_count(&f.walls)).sum();
    let ext = walls_batch.iter().filter(|w| w["category"] == "exterior").count();
    let int = total_walls - ext;
    let storeys = floors.len() as f32;
    let total_sqft = env.w * env.h * storeys;

    json!({
        "success": true,
        "building_id": building_id_manifest(manifest),
        "width": env.w * s,
        "depth": env.h * s,
        "sqft": total_sqft,
        "storeys": floors.len(),
        "output_format": "archengine",
        "unit": "mm",
        "creative_mode": false,
        "walls_batch": walls_batch,
        "doors": doors,
        "windows": windows_json,
        "egress_warnings": [],
        "detectors": [],
        "electrical": [],
        "headers": [],
        "stairs": stairs_json,
        "levels": levels,
        "dimensions": dimensions,
        "circulation_graph": circulation_graph,
        "rooms": Value::Object(rooms_map),
        "is_complete": true,
        "unplaced_rooms": [],
        "score": 1.0,
        "summary": {
            "total_walls": total_walls,
            "exterior_walls": ext,
            "interior_walls": int,
            "wet_walls": 0,
            "doors": total_doors,
            "windows": total_windows,
            "egress_violations": 0,
            "rooms_placed": total_rooms,
            "rooms_requested": total_rooms,
            "storeys": floors.len(),
            "detectors": 0,
            "electrical": 0,
            "stairs": stairs_json.len(),
            "headers": 0,
            "headers_need_review": 0,
        },
        "site": {
            "lot_width_ft": 50.0,
            "lot_depth_ft": 100.0,
            "zone": "R1",
            "street": "Street",
        },
        "roof_type": "gable",
        "qbd_answers": {
            "mode": manifest.mode.as_str(),
            "building_type": if manifest.mode == crate::BuildingMode::Part9 { "residential" } else { "commercial" },
            "bedrooms": 0,
            "bathrooms": 0,
            "sqft": total_sqft as i32,
            "garage": "none",
        },
    })
}

fn doors_count(walls: &[Wall]) -> usize {
    walls.iter().map(|w| w.openings.len()).sum()
}

/// Build a minimal circulation graph from the placed rooms. Nodes are placed at
/// stair/elevator centroids and corridor centroids; vertical edges connect the
/// same stair/elevator shaft across consecutive floors. This is the seed of the
/// path-of-travel graph — future work will add door nodes and wall-following
/// corridor centerlines.
fn build_circulation_graph(floors: &[Floor]) -> Value {
    let s = FEET_TO_MM;
    let mut nodes: Vec<Value> = Vec::new();
    let mut edges: Vec<Value> = Vec::new();
    let mut shaft_nodes: std::collections::HashMap<String, Vec<(String, usize)>> =
        std::collections::HashMap::new();

    for floor in floors {
        let level_name = format!("Level {}", floor.level);
        for room in &floor.rooms {
            let cx = (room.rect.x + room.rect.w * 0.5) * s;
            let cy = (room.rect.y + room.rect.h * 0.5) * s;
            let sanitized_id = room.id.replace(' ', "_");
            let node_id = format!("{}_{}", sanitized_id, floor.level);
            match room.room_type.as_str() {
                "stairs" | "elevator" => {
                    nodes.push(json!({
                        "id": node_id.clone(),
                        "kind": room.room_type,
                        "level": level_name,
                        "x": cx,
                        "y": cy,
                    }));
                    shaft_nodes
                        .entry(room.id.clone())
                        .or_default()
                        .push((node_id, floor.level));
                }
                "corridor" | "hallway" => {
                    nodes.push(json!({
                        "id": node_id.clone(),
                        "kind": "corridor",
                        "level": level_name,
                        "x": cx,
                        "y": cy,
                    }));
                }
                _ => {}
            }
        }
    }

    // Vertical shaft edges: connect the same stair/elevator on consecutive floors.
    let mut shaft_levels: Vec<_> = shaft_nodes.into_iter().collect();
    shaft_levels.sort_by(|a, b| a.0.cmp(&b.0));
    for (_shaft_id, mut levels) in shaft_levels {
        levels.sort_by(|a, b| a.1.cmp(&b.1));
        for pair in levels.windows(2) {
            edges.push(json!({
                "from": pair[0].0,
                "to": pair[1].0,
                "kind": "vertical_shaft",
            }));
        }
    }

    json!({ "nodes": nodes, "edges": edges })
}

/// Deterministic 8-hex id from a manifest (FNV-1a).
fn building_id_manifest(manifest: &crate::ProgramManifest) -> String {
    let mut h: u64 = 0xcbf2_9ce4_8422_2325;
    for byte in manifest.building_name.bytes().chain(manifest.mode.as_str().bytes()) {
        h ^= u64::from(byte);
        h = h.wrapping_mul(0x0000_0100_0000_01b3);
    }
    format!("{:08x}", (h & 0xffff_ffff) as u32)
}

/// Deterministic 8-hex id from the answers (FNV-1a), so output is stable.
#[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)] // byte extraction
fn building_id(a: &Answers) -> String {
    let mut h: u64 = 0xcbf2_9ce4_8422_2325;
    for byte in [
        a.bedrooms as u8,
        a.bathrooms as u8,
        (a.sqft as u32 & 0xff) as u8,
        ((a.sqft as u32 >> 8) & 0xff) as u8,
    ] {
        h ^= u64::from(byte);
        h = h.wrapping_mul(0x0000_0100_0000_01b3);
    }
    format!("{:08x}", (h & 0xffff_ffff) as u32)
}

fn title_case(id: &str) -> String {
    id.split('_')
        .map(|w| {
            let mut c = w.chars();
            c.next().map_or_else(String::new, |f| f.to_uppercase().collect::<String>() + c.as_str())
        })
        .collect::<Vec<_>>()
        .join(" ")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn building_json_is_schema_shaped() {
        let v = building_json(&Answers { storeys: 1, ..Answers::default() });
        assert_eq!(v["success"], json!(true));
        assert_eq!(v["unit"], json!("mm"));
        assert_eq!(v["output_format"], json!("archengine"));
        assert!(v["building_id"].as_str().unwrap().len() == 8);
        // 4 exterior walls + interior partitions (single storey).
        let walls = v["walls_batch"].as_array().unwrap();
        assert!(walls.len() >= 4);
        assert_eq!(walls.iter().filter(|w| w["category"] == "exterior").count(), 4);
        // Walls carry the required schema fields.
        let w0 = &walls[0];
        for k in ["start", "end", "height", "wall_type", "category", "level_name", "rooms", "wall_index"] {
            assert!(w0.get(k).is_some(), "wall missing {k}");
        }
        // Rooms map non-empty, each with required fields.
        let rooms = v["rooms"].as_object().unwrap();
        assert!(!rooms.is_empty());
        for (_, r) in rooms {
            for k in ["name", "bounds", "area", "center", "level"] {
                assert!(r.get(k).is_some(), "room missing {k}");
            }
        }
    }

    #[test]
    fn building_json_from_manifest_is_schema_shaped() {
        let manifest = crate::ProgramManifest::from_json(
            r#"{
                "mode": "part3",
                "building_name": "Office Block",
                "sqft": 4000,
                "floors": [
                    {
                        "level": 1,
                        "name": "Ground",
                        "occupancy": "business",
                        "rooms": [
                            {"id": "lobby", "room_type": "lobby", "min_area": 200},
                            {"id": "corridor", "room_type": "corridor", "min_area": 150},
                            {"id": "stairs_1", "room_type": "stairs", "min_area": 120},
                            {"id": "office_open", "room_type": "office_open", "min_area": 1200},
                            {"id": "washroom_1", "room_type": "washroom", "min_area": 80}
                        ]
                    }
                ]
            }"#,
        )
        .unwrap();
        let v = building_json_from_manifest(&manifest);
        assert_eq!(v["success"], json!(true));
        assert_eq!(v["unit"], json!("mm"));
        assert_eq!(v["qbd_answers"]["mode"], json!("part3"));
        let walls = v["walls_batch"].as_array().unwrap();
        assert!(walls.len() >= 4);
        let rooms = v["rooms"].as_object().unwrap();
        assert!(rooms.len() >= 4);
        assert!(rooms.contains_key("office_open"));
        assert!(rooms.contains_key("corridor"));
        assert!(rooms.contains_key("stairs_1"));
    }

    #[test]
    fn mixed_building_aligns_stairs_across_floors() {
        let manifest = crate::ProgramManifest::from_json(
            r#"{
                "mode": "mixed",
                "building_name": "Mixed Podium",
                "sqft": 6000,
                "floors": [
                    {
                        "level": 1,
                        "name": "Retail",
                        "occupancy": "mercantile",
                        "rooms": [
                            {"id": "retail_1", "room_type": "retail", "min_area": 1500},
                            {"id": "lobby", "room_type": "lobby", "min_area": 150},
                            {"id": "stairs_1", "room_type": "stairs", "min_area": 120},
                            {"id": "washroom_1", "room_type": "washroom", "min_area": 80}
                        ]
                    },
                    {
                        "level": 2,
                        "name": "Residential",
                        "occupancy": "residential",
                        "rooms": [
                            {"id": "living", "room_type": "living", "min_area": 250},
                            {"id": "bedroom_2", "room_type": "bedroom", "min_area": 120},
                            {"id": "stairs_2", "room_type": "stairs", "min_area": 120}
                        ]
                    }
                ]
            }"#,
        )
        .unwrap();
        let v = building_json_from_manifest(&manifest);
        assert_eq!(v["success"], json!(true));
        assert_eq!(v["storeys"], 2);
        let rooms = v["rooms"].as_object().unwrap();
        assert!(rooms.contains_key("retail_1"));
        assert!(rooms.contains_key("living"));
        let s1 = &rooms["stairs_1"]["bounds"];
        let s2 = &rooms["stairs_2"]["bounds"];
        for k in ["x", "y", "width", "height"] {
            let (a, b) = (s1[k].as_f64().unwrap(), s2[k].as_f64().unwrap());
            assert!((a - b).abs() < 1.0, "stairs not aligned on {k}: {a} vs {b}");
        }
    }

    #[test]
    fn part3_manifest_emits_public_stair_dimensions() {
        let manifest = crate::ProgramManifest::from_json(
            r#"{
                "mode": "part3",
                "building_name": "Office Block",
                "sqft": 4000,
                "floors": [
                    {
                        "level": 1,
                        "name": "Ground",
                        "occupancy": "business",
                        "rooms": [
                            {"id": "lobby", "room_type": "lobby", "min_area": 200},
                            {"id": "corridor", "room_type": "corridor", "min_area": 150},
                            {"id": "stairs_1", "room_type": "stairs", "min_area": 120},
                            {"id": "office_open", "room_type": "office_open", "min_area": 1200},
                            {"id": "washroom_1", "room_type": "washroom", "min_area": 80}
                        ]
                    }
                ]
            }"#,
        )
        .unwrap();
        let v = building_json_from_manifest(&manifest);
        let stairs = v["stairs"].as_array().unwrap();
        assert_eq!(stairs.len(), 1);
        let stair = &stairs[0];
        let width_clear = stair["width_clear"].as_f64().unwrap() as f32;
        let tread_run = stair["tread_run"].as_f64().unwrap() as f32;
        let riser_height = stair["riser_height"].as_f64().unwrap() as f32;
        assert!(
            width_clear >= obc::part3::stairs::PUBLIC_MIN_WIDTH_MM,
            "public stair width_clear {width_clear} mm is below {} mm",
            obc::part3::stairs::PUBLIC_MIN_WIDTH_MM
        );
        assert!(
            tread_run >= obc::part3::stairs::PUBLIC_MIN_TREAD_MM,
            "public stair tread_run {tread_run} mm is below {} mm",
            obc::part3::stairs::PUBLIC_MIN_TREAD_MM
        );
        assert!(
            riser_height <= obc::part3::stairs::PUBLIC_MAX_RISER_MM,
            "public stair riser_height {riser_height} mm exceeds {} mm",
            obc::part3::stairs::PUBLIC_MAX_RISER_MM
        );
    }

    #[test]
    fn mixed_building_part3_floor_has_public_stairs_and_part9_floor_private() {
        let manifest = crate::ProgramManifest::from_json(
            r#"{
                "mode": "mixed",
                "building_name": "Mixed Podium",
                "sqft": 6000,
                "floors": [
                    {
                        "level": 1,
                        "name": "Retail",
                        "occupancy": "mercantile",
                        "rooms": [
                            {"id": "retail_1", "room_type": "retail", "min_area": 1500},
                            {"id": "lobby", "room_type": "lobby", "min_area": 150},
                            {"id": "stairs_1", "room_type": "stairs", "min_area": 120},
                            {"id": "washroom_1", "room_type": "washroom", "min_area": 80}
                        ]
                    },
                    {
                        "level": 2,
                        "name": "Residential",
                        "occupancy": "residential",
                        "rooms": [
                            {"id": "living", "room_type": "living", "min_area": 250},
                            {"id": "bedroom_2", "room_type": "bedroom", "min_area": 120},
                            {"id": "stairs_2", "room_type": "stairs", "min_area": 120}
                        ]
                    }
                ]
            }"#,
        )
        .unwrap();
        let v = building_json_from_manifest(&manifest);
        let stairs = v["stairs"].as_array().unwrap();
        assert_eq!(stairs.len(), 2);
        for s in stairs {
            let tread = s["tread_run"].as_f64().unwrap() as f32;
            assert!(
                tread >= obc::part3::stairs::PUBLIC_MIN_TREAD_MM,
                "shared stairs in a mixed building must be public: {tread}"
            );
        }
    }

    #[test]
    #[allow(clippy::many_single_char_names)]
    fn entry_is_on_an_exterior_wall_with_its_door() {
        let v = building_json(&Answers::default());
        // The entry room touches an exterior edge of the footprint.
        let entry = &v["rooms"]["entry"];
        let b = &entry["bounds"];
        let (w, d) = (v["width"].as_f64().unwrap(), v["depth"].as_f64().unwrap());
        let (x, y, bw, bh) = (
            b["x"].as_f64().unwrap(),
            b["y"].as_f64().unwrap(),
            b["width"].as_f64().unwrap(),
            b["height"].as_f64().unwrap(),
        );
        let on_perimeter =
            x <= 300.0 || y <= 300.0 || x + bw >= w - 300.0 || y + bh >= d - 300.0;
        assert!(on_perimeter, "entry is interior, can't have a front door");
        // Exactly one exterior (perimeter, wall_index < 4) door — the entry.
        let perimeter_doors = v["doors"]
            .as_array()
            .unwrap()
            .iter()
            .filter(|dr| dr["wall_index"].as_u64().unwrap() < 4)
            .count();
        assert_eq!(perimeter_doors, 1, "expected exactly the entry door on the perimeter");
    }

    #[test]
    fn front_door_and_garage_door_share_the_street_wall() {
        let v = building_json(&Answers {
            bedrooms: 3,
            bathrooms: 2,
            sqft: 1700.0,
            garage: "2car".into(),
            special_rooms: vec![],
            storeys: 2,
            window_intent: "balanced".into(),
            style: "balanced".into(),
            ..Answers::default()
        });
        let rooms = v["rooms"].as_object().unwrap();
        let ground = |rt: &str| {
            rooms
                .values()
                .find(|r| r["room_type"] == json!(rt) && r["level"] == json!("Level 1"))
                .unwrap_or_else(|| panic!("no ground-floor {rt}"))
        };
        let entry = ground("entry");
        let garage = ground("garage");
        let f = |r: &serde_json::Value, k: &str| r["bounds"][k].as_f64().unwrap();
        // Both front the street wall (plan Z ≈ 0).
        assert!(f(entry, "y") < 1.0, "entry is not on the front wall");
        assert!(f(garage, "y") < 1.0, "garage is not on the front wall");
        // The entry sits immediately against the garage (shared vertical edge),
        // so the front door and the garage door are side by side.
        let entry_right = f(entry, "x") + f(entry, "width");
        assert!(
            (entry_right - f(garage, "x")).abs() < 50.0,
            "entry ({entry_right}) is not against the garage ({})",
            f(garage, "x")
        );
        // Exactly two perimeter doors: the front door + the garage overhead door.
        let perim = v["doors"]
            .as_array()
            .unwrap()
            .iter()
            .filter(|d| d["wall_index"].as_u64().unwrap() < 4)
            .count();
        assert_eq!(perim, 2, "expected the front door + garage door on the perimeter");
    }

    #[test]
    fn bedroom_floor_doors_are_circulation_correct() {
        use crate::RoomSpec;
        // A clean upper (bedroom) floor: stair, hall spine, two bedrooms each
        // with a closet, and a shared bath that stacks behind a closet.
        let p = vec![
            RoomSpec::new("stairs", "stairs", 1.0, 60.0),
            RoomSpec::new("hallway_2", "hallway", 1.0, 40.0),
            RoomSpec::new("bedroom_2", "bedroom", 2.5, 120.0),
            RoomSpec::new("closet_2", "closet", 1.0, 16.0),
            RoomSpec::new("bedroom_3", "bedroom", 2.5, 120.0),
            RoomSpec::new("closet_3", "closet", 1.0, 16.0),
            RoomSpec::new("bath_2", "bathroom", 1.0, 45.0),
        ];
        let env = Rect { x: 0.0, y: 0.0, w: 38.0, h: 27.0 };
        let placed = subdivide(env, &p, "south", "switchback", &AdjacencyGraph::new_for_mode(crate::BuildingMode::Part9));
        let walls = generate_walls(&placed, env, /* is_ground */ false);
        let kind = |id: &str| {
            placed.iter().find(|r| r.id == id).map_or("", |r| r.room_type.as_str()).to_string()
        };
        // Every interior wall carrying a door, by the two room *types* it joins.
        let doored: Vec<(String, String)> = walls
            .iter()
            .filter(|w| w.category == "interior" && !w.openings.is_empty())
            .map(|w| (kind(&w.room1), kind(&w.room2)))
            .collect();
        let joins = |a: &str, b: &str| {
            doored.iter().any(|(x, y)| (x == a && y == b) || (x == b && y == a))
        };

        // The stair opens ONLY to the hall — never straight into a bedroom.
        for (a, b) in &doored {
            if a == "stairs" || b == "stairs" {
                let other = if a == "stairs" { b } else { a };
                assert_eq!(other, "hallway", "stairs doored to a {other}, not the hall");
            }
        }
        let stair_doors =
            doored.iter().filter(|(a, b)| a == "stairs" || b == "stairs").count();
        assert_eq!(stair_doors, 1, "stairs should have exactly one (hall) door");

        // A closet never doors into the bath it stacks behind.
        assert!(!joins("closet", "bathroom"), "closet should not open into the bath");
        // The shared bath opens off the hall, not into a bedroom.
        assert!(joins("hallway", "bathroom"), "shared bath should open off the hall");
        assert!(!joins("bedroom", "bathroom"), "shared bath should not open into a bedroom");
        // Every bedroom reaches the hall directly.
        assert!(joins("bedroom", "hallway"), "a bedroom is not doored to the hall");
    }

    #[test]
    fn windows_placed_for_habitable_rooms_meet_obc() {
        let v = building_json(&Answers { storeys: 1, ..Answers::default() });
        let windows = v["windows"].as_array().unwrap();
        assert!(!windows.is_empty(), "no windows emitted");
        let walls = v["walls_batch"].as_array().unwrap().len();
        for win in windows {
            // On a real (exterior) perimeter wall, with required schema fields.
            let wi = win["wall_index"].as_u64().unwrap();
            assert!(wi < 4, "window not on a perimeter wall: {wi}");
            assert!(wi < walls as u64);
            for k in ["wall_index", "offset", "width", "height", "sill_height", "type", "room"] {
                assert!(win.get(k).is_some(), "window missing {k}");
            }
            // Egress-capable opening: never below the OBC minimum dimension.
            assert!(win["width"].as_f64().unwrap() >= 380.0);
        }
        // Every bedroom is EITHER covered by an egress (casement) window OR
        // honestly flagged as an egress violation (interior bedroom). No
        // bedroom is silently left non-compliant.
        let rooms = v["rooms"].as_object().unwrap();
        let warned: Vec<&str> = v["egress_warnings"]
            .as_array()
            .unwrap()
            .iter()
            .map(|w| w["room"].as_str().unwrap())
            .collect();
        for id in rooms.keys().filter(|k| k.contains("bedroom")) {
            let has_egress = windows
                .iter()
                .any(|w| w["room"] == json!(id) && w["type"] == json!("casement"));
            assert!(
                has_egress || warned.contains(&id.as_str()),
                "bedroom {id} neither glazed nor flagged for egress"
            );
        }
        // Summary counts match.
        assert_eq!(v["summary"]["windows"], json!(windows.len()));
        assert_eq!(v["summary"]["egress_violations"], json!(warned.len()));
    }

    #[test]
    fn window_intent_scales_glazing_and_keeps_egress() {
        let glazing = |intent: &str| -> (usize, f64, i64) {
            let a = Answers {
                bedrooms: 3,
                bathrooms: 2,
                sqft: 1600.0,
                garage: "none".into(),
                special_rooms: vec![],
                storeys: 1,
                window_intent: intent.into(),
                style: "balanced".into(),
                ..Answers::default()
            };
            let v = building_json(&a);
            let ws = v["windows"].as_array().unwrap();
            let area: f64 = ws.iter().map(|w| w["width"].as_f64().unwrap() * w["height"].as_f64().unwrap()).sum();
            (ws.len(), area, v["summary"]["egress_violations"].as_i64().unwrap())
        };
        let (_, priv_a, priv_e) = glazing("privacy");
        let (_, bal_a, _) = glazing("balanced");
        let (light_n, light_a, light_e) = glazing("more_light");
        // more_light glazes more than balanced, which beats bare-minimum privacy.
        assert!(light_a > bal_a && bal_a > priv_a, "privacy {priv_a} < balanced {bal_a} < more_light {light_a}");
        // more_light spreads onto extra walls → more window openings.
        let (priv_n, _, _) = glazing("privacy");
        assert!(light_n > priv_n, "more_light {light_n} windows vs privacy {priv_n}");
        // Egress is never sacrificed for intent.
        assert_eq!(priv_e, 0);
        assert_eq!(light_e, 0);
    }

    #[test]
    fn window_style_sets_type_and_banks_but_keeps_egress() {
        let build = |style: &str| {
            building_json(&Answers {
                bedrooms: 3,
                bathrooms: 2,
                sqft: 1600.0,
                garage: "none".into(),
                special_rooms: vec![],
                storeys: 1,
                window_intent: "balanced".into(),
                style: style.into(),
                ..Answers::default()
            })
        };
        let win_types = |v: &serde_json::Value| {
            v["windows"]
                .as_array()
                .unwrap()
                .iter()
                .map(|w| w["type"].as_str().unwrap().to_string())
                .collect::<Vec<_>>()
        };
        // Contemporary uses fixed panes on non-egress rooms…
        let c = build("contemporary");
        assert!(win_types(&c).iter().any(|t| t == "fixed"));
        // …colonial uses double-hungs, ranch sliders.
        assert!(win_types(&build("colonial")).iter().any(|t| t == "double_hung"));
        assert!(win_types(&build("ranch")).iter().any(|t| t == "sliding"));
        // Ranch banks more openings than a single-pane contemporary.
        assert!(win_types(&build("ranch")).len() > win_types(&c).len());
        // Every style still gives bedrooms an openable egress casement.
        for style in ["ranch", "colonial", "contemporary"] {
            let v = build(style);
            assert_eq!(v["summary"]["egress_violations"], json!(0), "{style}");
            assert!(win_types(&v).iter().any(|t| t == "casement"), "{style} has no casement");
        }
    }

    #[test]
    fn south_bank_concentrates_windows_on_the_south_wall() {
        let a = Answers {
            bedrooms: 3,
            bathrooms: 2,
            sqft: 1600.0,
            garage: "none".into(),
            special_rooms: vec![],
            storeys: 1,
            window_intent: "south_bank".into(),
            style: "balanced".into(),
            ..Answers::default()
        };
        let v = building_json(&a);
        let ws = v["windows"].as_array().unwrap();
        // South-facing rooms put their window on wall_index 0 (the south perimeter).
        let on_south = ws.iter().filter(|w| w["wall_index"] == json!(0)).count();
        assert!(on_south >= 1, "south_bank should place windows on the south wall");
    }

    #[test]
    fn multi_storey_splits_public_down_and_bedrooms_up() {
        let a = Answers {
            bedrooms: 4,
            bathrooms: 3,
            sqft: 2400.0,
            garage: "2car".into(),
            special_rooms: vec![],
            storeys: 0, // auto → 2 storeys (4 bedrooms)
            window_intent: "balanced".into(),
            style: "balanced".into(),
            ..Answers::default()
        };
        let v = building_json(&a);
        assert_eq!(v["storeys"], json!(2));
        // Three levels: two storeys + roof.
        assert_eq!(v["levels"].as_array().unwrap().len(), 3);
        let rooms = v["rooms"].as_object().unwrap();
        let level_of = |id: &str| rooms[id]["level"].as_str().unwrap().to_string();
        // Public/service downstairs, bedrooms upstairs.
        assert_eq!(level_of("living"), "Level 1");
        assert_eq!(level_of("garage"), "Level 1");
        assert_eq!(level_of("primary_bedroom"), "Level 2");
        assert_eq!(level_of("bedroom_2"), "Level 2");
        // Each floor has its own stair, stacked at the SAME footprint position.
        assert!(rooms.contains_key("stairs_1") && rooms.contains_key("stairs_2"));
        let s1 = &rooms["stairs_1"]["bounds"];
        let s2 = &rooms["stairs_2"]["bounds"];
        for k in ["x", "y", "width", "height"] {
            let (a, b) = (s1[k].as_f64().unwrap(), s2[k].as_f64().unwrap());
            assert!((a - b).abs() < 1.0, "stairs not aligned on {k}: {a} vs {b}");
        }
        // Total sqft is split across floors: footprint ≈ total/2.
        let footprint = v["width"].as_f64().unwrap() * v["depth"].as_f64().unwrap()
            / (304.8 * 304.8);
        assert!((footprint - 1200.0).abs() < 250.0, "per-floor footprint {footprint}");
        // Walls/windows are level-tagged; bedrooms upstairs still get egress.
        assert!(v["walls_batch"].as_array().unwrap().iter().any(|w| w["level_name"] == "Level 2"));
        assert!(v["windows"].as_array().unwrap().iter().any(|w| w["level_name"] == "Level 2"));
    }

    #[test]
    fn multi_storey_emits_one_compliant_stair_per_floor() {
        let v = building_json(&Answers {
            bedrooms: 4,
            bathrooms: 3,
            sqft: 2400.0,
            garage: "2car".into(),
            special_rooms: vec![],
            storeys: 0, // auto → 2 storeys
            window_intent: "balanced".into(),
            style: "balanced".into(),
            ..Answers::default()
        });
        let stairs = v["stairs"].as_array().unwrap();
        assert_eq!(stairs.len(), 2, "one stair per storey");

        // Lower storey climbs up; the top storey shows the way down.
        let by_level = |lvl: &str| stairs.iter().find(|s| s["level_name"] == json!(lvl)).unwrap();
        assert_eq!(by_level("Level 1")["going"], json!("up"));
        assert_eq!(by_level("Level 2")["going"], json!("down"));

        for s in stairs {
            // 10 ft storey → 16 risers at 190.5 mm, under the 200 mm max.
            assert_eq!(s["num_risers"], json!(16));
            assert_eq!(s["num_treads"], json!(15));
            assert!((s["riser_height"].as_f64().unwrap() - 190.5).abs() < 0.1);
            assert!(s["riser_height"].as_f64().unwrap() <= 200.0);
            assert!(s["tread_run"].as_f64().unwrap() >= 255.0);
            // 6 ft well folds to a switchback whose flights still clear 860 mm.
            assert_eq!(s["shape"], json!("switchback"));
            assert!(s["width_clear"].as_f64().unwrap() >= 860.0);
        }
        assert_eq!(v["summary"]["stairs"], json!(2));
    }

    #[test]
    fn l_shaped_config_emits_l_shaped_stairs() {
        let v = building_json(&Answers {
            bedrooms: 4,
            bathrooms: 3,
            sqft: 2400.0,
            garage: "2car".into(),
            special_rooms: vec![],
            storeys: 2,
            stair_config: "l_shaped".into(),
            ..Answers::default()
        });
        for s in v["stairs"].as_array().unwrap() {
            assert_eq!(s["shape"], json!("l_shaped"));
            assert!(s["width_clear"].as_f64().unwrap() >= 860.0);
        }
    }

    #[test]
    fn single_storey_emits_no_stairs() {
        let v = building_json(&Answers {
            bedrooms: 2,
            bathrooms: 1,
            sqft: 1100.0,
            garage: "none".into(),
            special_rooms: vec![],
            storeys: 0, // auto → 1 storey
            window_intent: "balanced".into(),
            style: "balanced".into(),
            ..Answers::default()
        });
        assert_eq!(v["storeys"], json!(1));
        assert!(v["stairs"].as_array().unwrap().is_empty());
    }

    #[test]
    fn single_storey_for_two_bedrooms() {
        let a = Answers {
            bedrooms: 2,
            bathrooms: 1,
            sqft: 1100.0,
            garage: "none".into(),
            special_rooms: vec![],
            storeys: 0, // auto → 1 storey (< 3 bedrooms)
            window_intent: "balanced".into(),
            style: "balanced".into(),
            ..Answers::default()
        };
        let v = building_json(&a);
        assert_eq!(v["storeys"], json!(1));
        assert_eq!(v["levels"].as_array().unwrap().len(), 2); // Level 1 + roof
    }

    #[test]
    fn smoke_and_co_detectors_placed_per_obc() {
        // 4-bed, 2-storey, attached garage → CO required near sleeping.
        let v = building_json(&Answers {
            bedrooms: 4,
            bathrooms: 3,
            sqft: 2400.0,
            garage: "2car".into(),
            special_rooms: vec![],
            storeys: 0,
            window_intent: "balanced".into(),
            style: "balanced".into(),
            ..Answers::default()
        });
        let det = v["detectors"].as_array().unwrap();
        // A smoke alarm in every bedroom.
        let rooms = v["rooms"].as_object().unwrap();
        for bed in rooms.keys().filter(|k| k.contains("bedroom")) {
            assert!(
                det.iter().any(|d| d["type"] == json!("smoke") && d["room"] == json!(bed)),
                "no smoke alarm in {bed}"
            );
        }
        // A smoke alarm on each storey.
        for lvl in ["Level 1", "Level 2"] {
            assert!(
                det.iter().any(|d| d["type"] == json!("smoke") && d["level_name"] == json!(lvl)),
                "no smoke alarm on {lvl}"
            );
        }
        // A CO alarm exists (attached garage) near the sleeping storey.
        assert!(det.iter().any(|d| d["type"] == json!("co")), "no CO alarm with attached garage");
        assert_eq!(v["summary"]["detectors"], json!(det.len()));
    }

    #[test]
    fn electrical_places_light_and_receptacles_with_gfci_in_wet_rooms() {
        let v = building_json(&Answers {
            bedrooms: 3,
            bathrooms: 2,
            sqft: 1600.0,
            garage: "1car".into(),
            special_rooms: vec![],
            storeys: 1,
            window_intent: "balanced".into(),
            style: "balanced".into(),
            ..Answers::default()
        });
        let el = v["electrical"].as_array().unwrap();
        let rooms = v["rooms"].as_object().unwrap();
        // Exactly one ceiling light per room, and a switch in each room.
        let lights = el.iter().filter(|e| e["type"] == json!("light")).count();
        assert_eq!(lights, rooms.len(), "expected one light per room");
        for id in rooms.keys() {
            assert!(
                el.iter().any(|e| e["type"] == json!("switch") && e["room"] == json!(id)),
                "{id} has no light switch"
            );
        }
        // Every room has at least one receptacle (standard or gfci).
        for id in rooms.keys() {
            let n = el
                .iter()
                .filter(|e| e["room"] == json!(id) && e["type"] != json!("light"))
                .count();
            assert!(n >= 1, "{id} has no receptacle");
        }
        // Wet/garage rooms get GFCI receptacles; bedrooms don't.
        let gfci_rooms: std::collections::HashSet<&str> = el
            .iter()
            .filter(|e| e["type"] == json!("gfci"))
            .map(|e| e["room"].as_str().unwrap())
            .collect();
        assert!(gfci_rooms.iter().any(|r| r.contains("bath") || *r == "kitchen" || *r == "garage"));
        assert!(!gfci_rooms.iter().any(|r| r.contains("bedroom")));
        assert_eq!(v["summary"]["electrical"], json!(el.len()));
    }

    #[test]
    fn headers_sized_per_opening_and_deeper_on_lower_storeys() {
        let v = building_json(&Answers {
            bedrooms: 4,
            bathrooms: 3,
            sqft: 2400.0,
            garage: "2car".into(),
            special_rooms: vec![],
            storeys: 0, // 2-storey
            window_intent: "balanced".into(),
            style: "balanced".into(),
            ..Answers::default()
        });
        let hdr = v["headers"].as_array().unwrap();
        // One header per opening (doors + windows).
        let openings = v["doors"].as_array().unwrap().len() + v["windows"].as_array().unwrap().len();
        assert_eq!(hdr.len(), openings, "a header per opening");
        // Every header has a member size; count matches summary.
        assert!(hdr.iter().all(|h| h["size"].as_str().is_some_and(|s| s.starts_with("2-2x"))));
        assert_eq!(v["summary"]["headers"], json!(hdr.len()));
        // A given door width gets a deeper header on the ground floor (carries
        // the floor above) than on the top floor (roof only).
        let door_size = |lvl: &str| {
            hdr.iter()
                .find(|h| h["opening"] == json!("door") && h["level_name"] == json!(lvl)
                    && (h["width"].as_f64().unwrap() / 304.8 - 3.0).abs() < 0.2)
                .map(|h| h["size"].as_str().unwrap().to_string())
        };
        if let (Some(g), Some(u)) = (door_size("Level 1"), door_size("Level 2")) {
            assert_ne!(g, u, "ground-floor 3ft door header should differ from upper");
        }
    }

    #[test]
    fn no_co_alarm_without_garage_or_fuel() {
        let v = building_json(&Answers {
            bedrooms: 2,
            bathrooms: 1,
            sqft: 1100.0,
            garage: "none".into(),
            special_rooms: vec![],
            storeys: 1,
            window_intent: "balanced".into(),
            style: "balanced".into(),
            ..Answers::default()
        });
        let det = v["detectors"].as_array().unwrap();
        assert!(det.iter().all(|d| d["type"] != json!("co")), "CO alarm without garage/fuel");
        assert!(det.iter().any(|d| d["type"] == json!("smoke")), "expected smoke alarms");
    }

    #[test]
    fn building_id_is_deterministic() {
        let a = Answers::default();
        assert_eq!(building_id(&a), building_id(&a));
    }

    #[test]
    fn shared_edge_detects_vertical_abutment() {
        let a = Rect { x: 0.0, y: 0.0, w: 10.0, h: 10.0 };
        let b = Rect { x: 10.0, y: 0.0, w: 10.0, h: 10.0 };
        let edge = shared_edge(&a, &b).expect("should share a vertical edge");
        assert!((edge.0 .0 - 10.0).abs() < EPS);
        assert!((edge.1 .0 - 10.0).abs() < EPS);
    }

    #[test]
    fn disjoint_rects_share_no_edge() {
        let a = Rect { x: 0.0, y: 0.0, w: 10.0, h: 10.0 };
        let b = Rect { x: 50.0, y: 50.0, w: 10.0, h: 10.0 };
        assert!(shared_edge(&a, &b).is_none());
    }
}
