//! IFC4 export — a focused, Revit-importable subset.
//!
//! Emits the spatial hierarchy (`IfcProject` → `IfcSite` → `IfcBuilding` →
//! `IfcBuildingStorey`) plus `IfcWall` / `IfcSpace` / `IfcDoor` / `IfcWindow`
//! / `IfcSlab` (one floor per storey) / `IfcFooting` (one strip per exterior
//! wall on the lowest storey) as placed extruded solids, units in
//! millimetres. Doors and windows cut a through-wall `IfcOpeningElement`
//! (`IfcRelVoidsElement`) and fill it (`IfcRelFillsElement`) so Revit
//! imports them as proper openings.

use archgeometry::SchemaDocument;
use std::fmt::Write as _;

/// Compress a 128-bit value into IFC's 22-char base64 GUID encoding.
fn ifc_guid(value: u128) -> String {
    const ALPHABET: &[u8; 64] =
        b"0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_$";
    let mut digits = [0u8; 22];
    let mut v = value;
    for d in digits.iter_mut().rev() {
        *d = ALPHABET[(v & 0x3f) as usize];
        v >>= 6;
    }
    String::from_utf8_lossy(&digits).into_owned()
}

/// STEP physical-file builder: an entity buffer with an incrementing id and a
/// per-entity GUID source.
struct Spf {
    body: String,
    next_id: usize,
    guid_seed: u128,
}

impl Spf {
    fn new() -> Self {
        Self { body: String::new(), next_id: 1, guid_seed: 1 }
    }

    /// Append one entity line (without the leading `#id=`); returns its id.
    fn add(&mut self, entity: &str) -> usize {
        let id = self.next_id;
        self.next_id += 1;
        let _ = writeln!(self.body, "#{id}={entity};");
        id
    }

    fn guid(&mut self) -> String {
        let g = ifc_guid(self.guid_seed);
        self.guid_seed += 1;
        g
    }
}

/// Reference list `(#a,#b,...)`.
fn refs(ids: &[usize]) -> String {
    let inner: Vec<String> = ids.iter().map(|i| format!("#{i}")).collect();
    format!("({})", inner.join(","))
}

/// A 3D cartesian point literal.
fn pt(x: f32, y: f32, z: f32) -> String {
    format!("IFCCARTESIANPOINT(({x:.3},{y:.3},{z:.3}))")
}

/// Export `doc` to an IFC4 STEP file string.
#[must_use]
#[allow(clippy::too_many_lines)] // one cohesive STEP assembly; splitting hides the entity graph
pub fn to_ifc(doc: &SchemaDocument, project_name: &str, date: &str) -> String {
    let mut s = Spf::new();

    // --- Owner history (minimal but valid) ---
    let person = s.add("IFCPERSON($,$,'',$,$,$,$,$)");
    let org = s.add("IFCORGANIZATION($,'Legible Studio',$,$,$)");
    let p_and_o = s.add(&format!("IFCPERSONANDORGANIZATION(#{person},#{org},$)"));
    let app = s.add(&format!(
        "IFCAPPLICATION(#{org},'1.0','Legible Studio','legible')"
    ));
    #[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)]
    let ts = 1_700_000_000_i64; // fixed stamp; deterministic output
    let owner = s.add(&format!(
        "IFCOWNERHISTORY(#{p_and_o},#{app},$,.ADDED.,$,$,$,{ts})"
    ));

    // --- Units: millimetre length, square/cubic mm ---
    let len = s.add("IFCSIUNIT(*,.LENGTHUNIT.,.MILLI.,.METRE.)");
    let area = s.add("IFCSIUNIT(*,.AREAUNIT.,$,.SQUARE_METRE.)");
    let vol = s.add("IFCSIUNIT(*,.VOLUMEUNIT.,$,.CUBIC_METRE.)");
    let units = s.add(&format!("IFCUNITASSIGNMENT({})", refs(&[len, area, vol])));

    // --- Geometric context ---
    let origin = s.add(&pt(0.0, 0.0, 0.0));
    let axis_z = s.add("IFCDIRECTION((0.,0.,1.))");
    let axis_x = s.add("IFCDIRECTION((1.,0.,0.))");
    let world = s.add(&format!("IFCAXIS2PLACEMENT3D(#{origin},#{axis_z},#{axis_x})"));
    let ctx = s.add(&format!(
        "IFCGEOMETRICREPRESENTATIONCONTEXT($,'Model',3,1.0E-5,#{world},$)"
    ));

    // --- Spatial hierarchy ---
    let g = s.guid();
    let project = s.add(&format!(
        "IFCPROJECT('{g}',#{owner},'{project_name}',$,$,$,$,({}),#{units})",
        format_args!("#{ctx}")
    ));
    let site_plc = local_placement(&mut s, None, 0.0, 0.0, 0.0);
    let g = s.guid();
    let site = s.add(&format!(
        "IFCSITE('{g}',#{owner},'Site',$,$,#{site_plc},$,$,.ELEMENT.,$,$,$,$,$)"
    ));
    let bldg_plc = local_placement(&mut s, Some(site_plc), 0.0, 0.0, 0.0);
    let g = s.guid();
    let building = s.add(&format!(
        "IFCBUILDING('{g}',#{owner},'Building',$,$,#{bldg_plc},$,$,.ELEMENT.,$,$,$)"
    ));

    // Levels (storeys), excluding roof.
    let storeys: Vec<(String, f32)> = if doc.levels.is_empty() {
        vec![("Level 1".to_string(), 0.0)]
    } else {
        doc.levels
            .iter()
            .filter(|l| !l.name.to_lowercase().contains("roof"))
            .map(|l| (l.name.clone(), l.elevation))
            .collect()
    };

    let mut storey_ids: Vec<(String, usize)> = Vec::new();
    let mut contained: Vec<(usize, Vec<usize>)> = Vec::new(); // storey -> elements
    for (name, elev) in &storeys {
        let plc = local_placement(&mut s, Some(bldg_plc), 0.0, 0.0, *elev);
        let g = s.guid();
        let st = s.add(&format!(
            "IFCBUILDINGSTOREY('{g}',#{owner},'{name}',$,$,#{plc},$,$,.ELEMENT.,{elev:.3})"
        ));
        storey_ids.push((name.clone(), st));
        contained.push((st, Vec::new()));
    }
    let storey_of = |level: &str| -> usize {
        storey_ids
            .iter()
            .find(|(n, _)| n == level)
            .or_else(|| storey_ids.first())
            .map_or(0, |(_, id)| *id)
    };
    let contained_idx = |st: usize| storey_ids.iter().position(|(_, id)| *id == st).unwrap_or(0);

    // --- Walls (extruded box: length x thickness x height) ---
    // Track each schema wall's IFC id so openings can void their host wall.
    let mut wall_ifc: Vec<Option<usize>> = Vec::with_capacity(doc.walls.len());
    for w in &doc.walls {
        let (sx, sz) = (w.start.x, w.start.z);
        let (ex, ez) = (w.end.x, w.end.z);
        let len_mm = ((ex - sx).powi(2) + (ez - sz).powi(2)).sqrt();
        if len_mm < 1.0 {
            wall_ifc.push(None);
            continue;
        }
        let (mx, mz) = ((sx + ex) * 0.5, (sz + ez) * 0.5);
        let (dx, dz) = ((ex - sx) / len_mm, (ez - sz) / len_mm);
        let thick = if w.category == "exterior" { 175.0 } else { 115.0 };
        let base = w.start.y; // walls carry their storey base in y
        let plc = placement_dir(&mut s, Some(bldg_plc), mx, mz, base, dx, dz);
        let solid = extruded_box(&mut s, len_mm, thick, w.height);
        let shape = shape_rep(&mut s, ctx, solid);
        let prod = s.add(&format!("IFCPRODUCTDEFINITIONSHAPE($,$,(#{shape}))"));
        let g = s.guid();
        let id = s.add(&format!(
            "IFCWALL('{g}',#{owner},'Wall',$,$,#{plc},#{prod},$,.NOTDEFINED.)"
        ));
        wall_ifc.push(Some(id));
        let st = storey_of(&w.level_name);
        contained[contained_idx(st)].1.push(id);
    }

    // --- Spaces (room footprints) ---
    for (rid, r) in &doc.rooms {
        let b = &r.bounds;
        if b.width < 1.0 || b.height < 1.0 {
            continue;
        }
        let (cx, cz) = (b.x + b.width * 0.5, b.y + b.height * 0.5);
        let base = doc
            .levels
            .iter()
            .find(|l| l.name == r.level)
            .map_or(0.0, |l| l.elevation);
        let plc = placement_dir(&mut s, Some(bldg_plc), cx, cz, base, 1.0, 0.0);
        let solid = extruded_box(&mut s, b.width, b.height, 2700.0);
        let shape = shape_rep(&mut s, ctx, solid);
        let prod = s.add(&format!("IFCPRODUCTDEFINITIONSHAPE($,$,(#{shape}))"));
        let g = s.guid();
        let name = if r.name.is_empty() { rid } else { &r.name };
        let id = s.add(&format!(
            "IFCSPACE('{g}',#{owner},'{name}',$,$,#{plc},#{prod},$,.ELEMENT.,.INTERNAL.,$)"
        ));
        let st = storey_of(&r.level);
        contained[contained_idx(st)].1.push(id);
    }

    // --- Slabs: one IfcSlab per storey, sized to the building footprint.
    // The slab's top face sits at the storey elevation so wall feet land on
    // it; thickness extrudes downward.
    const SLAB_THICKNESS_MM: f32 = 150.0;
    if doc.width >= 1.0 && doc.depth >= 1.0 {
        for (name, st_id) in &storey_ids {
            let elev = doc
                .levels
                .iter()
                .find(|l| &l.name == name)
                .map_or(0.0, |l| l.elevation);
            let cx = doc.width * 0.5;
            let cz = doc.depth * 0.5;
            let plc = placement_dir(&mut s, Some(bldg_plc), cx, cz, elev - SLAB_THICKNESS_MM, 1.0, 0.0);
            let solid = extruded_box(&mut s, doc.width, doc.depth, SLAB_THICKNESS_MM);
            let shape = shape_rep(&mut s, ctx, solid);
            let prod = s.add(&format!("IFCPRODUCTDEFINITIONSHAPE($,$,(#{shape}))"));
            let g = s.guid();
            let id = s.add(&format!(
                "IFCSLAB('{g}',#{owner},'Slab - {name}',$,$,#{plc},#{prod},$,.FLOOR.)"
            ));
            contained[contained_idx(*st_id)].1.push(id);
        }
    }

    // --- Footings: one strip footing per exterior wall on the lowest storey.
    // Width matches drawing::footing_detail (500 mm); positioned below the
    // ground-floor slab so its top supports the foundation wall above.
    const FOOTING_WIDTH_MM: f32 = 500.0;
    const FOOTING_THICKNESS_MM: f32 = 200.0;
    const GRAVEL_DEPTH_MM: f32 = 150.0;
    let ground_storey_id = storey_ids.first().map(|(_, id)| *id);
    let ground_storey_elev = storey_ids
        .first()
        .map(|(name, _)| name.clone())
        .and_then(|n| doc.levels.iter().find(|l| l.name == n).map(|l| l.elevation))
        .unwrap_or(0.0);
    for w in &doc.walls {
        if w.category != "exterior" {
            continue;
        }
        if !(w.level_name.is_empty() || Some(&w.level_name) == storey_ids.first().map(|(n, _)| n)) {
            continue;
        }
        let (sx, sz, ex, ez) = (w.start.x, w.start.z, w.end.x, w.end.z);
        let len_mm = ((ex - sx).powi(2) + (ez - sz).powi(2)).sqrt();
        if len_mm < 1.0 {
            continue;
        }
        let (mx, mz) = ((sx + ex) * 0.5, (sz + ez) * 0.5);
        let (dx, dz) = ((ex - sx) / len_mm, (ez - sz) / len_mm);
        let z = ground_storey_elev - SLAB_THICKNESS_MM - GRAVEL_DEPTH_MM - FOOTING_THICKNESS_MM;
        let plc = placement_dir(&mut s, Some(bldg_plc), mx, mz, z, dx, dz);
        let solid = extruded_box(&mut s, len_mm, FOOTING_WIDTH_MM, FOOTING_THICKNESS_MM);
        let shape = shape_rep(&mut s, ctx, solid);
        let prod = s.add(&format!("IFCPRODUCTDEFINITIONSHAPE($,$,(#{shape}))"));
        let g = s.guid();
        let id = s.add(&format!(
            "IFCFOOTING('{g}',#{owner},'Strip Footing',$,$,#{plc},#{prod},$,.STRIP_FOOTING.)"
        ));
        if let Some(st_id) = ground_storey_id {
            contained[contained_idx(st_id)].1.push(id);
        }
    }

    // --- Stairs: one IfcStair per *up* flight. Each physical run appears in the
    // schema twice — an "up" stair on the lower storey and a "down" stair on the
    // storey above (same shaft) — so the "down" copies are skipped to avoid
    // doubling. The IfcStair aggregates a single IfcStairFlight that carries the
    // riser/tread semantics + a bay-box solid spanning floor-to-floor; the turn
    // (straight vs switchback) is the IfcStair predefined type. A true two-flight
    // switchback with a landing slab is a v2 refinement.
    for stair in &doc.stairs {
        if stair.going == "down" {
            continue; // same physical run as the storey-below's "up" stair
        }
        // Bay footprint: width is across the run, depth along it.
        let (bx, bz) = if matches!(stair.run_dir.as_str(), "+x" | "-x") {
            (stair.depth, stair.width)
        } else {
            (stair.width, stair.depth)
        };
        if bx < 1.0 || bz < 1.0 {
            continue;
        }
        let (cx, cz) = (stair.x + bx * 0.5, stair.y + bz * 0.5);
        let base = doc
            .levels
            .iter()
            .find(|l| l.name == stair.level_name)
            .map_or(0.0, |l| l.elevation);
        let ff = if stair.floor_to_floor > 0.0 { stair.floor_to_floor } else { 3048.0 };
        let predef = match stair.shape.as_str() {
            "switchback" => ".HALF_TURN_STAIR.",
            "l_shaped" | "l" | "quarter_turn" => ".QUARTER_TURN_STAIR.",
            _ => ".STRAIGHT_RUN_STAIR.",
        };

        // IfcStair (assembly; its geometry is the aggregate of its flights).
        let stair_plc = placement_dir(&mut s, Some(bldg_plc), cx, cz, base, 1.0, 0.0);
        let g = s.guid();
        let stair_id = s.add(&format!(
            "IFCSTAIR('{g}',#{owner},'Stair',$,$,#{stair_plc},$,$,{predef})"
        ));

        // IfcStairFlight with the riser/tread attributes + a bay-box solid.
        let f_plc = placement_dir(&mut s, Some(bldg_plc), cx, cz, base, 1.0, 0.0);
        let f_solid = extruded_box(&mut s, bx, bz, ff);
        let f_shape = shape_rep(&mut s, ctx, f_solid);
        let f_prod = s.add(&format!("IFCPRODUCTDEFINITIONSHAPE($,$,(#{f_shape}))"));
        let g = s.guid();
        let flight_id = s.add(&format!(
            "IFCSTAIRFLIGHT('{g}',#{owner},'Stair Flight',$,$,#{f_plc},#{f_prod},$,{nr},{nt},{rh:.1},{tl:.1},.STRAIGHT.)",
            nr = stair.num_risers,
            nt = stair.num_treads,
            rh = stair.riser_height,
            tl = stair.tread_run,
        ));
        let g = s.guid();
        s.add(&format!(
            "IFCRELAGGREGATES('{g}',#{owner},$,$,#{stair_id},(#{flight_id}))"
        ));

        // The IfcStair (not its flight) is contained in the storey.
        let st = storey_of(&stair.level_name);
        contained[contained_idx(st)].1.push(stair_id);
    }

    // --- Doors + windows: each cuts an IfcOpeningElement that voids its host
    // wall (IfcRelVoidsElement) and is then filled by the door/window
    // (IfcRelFillsElement). Wall-aligned boxes; not spatially contained — the
    // host-wall relationship carries them.
    #[allow(clippy::many_single_char_names, clippy::too_many_arguments)]
    let place_opening =
        |s: &mut Spf, kind: &str, wall_id: usize, cx: f32, cz: f32, z: f32, dx: f32, dz: f32, thick: f32, w: f32, h: f32| {
            // The opening: a box voiding the full wall thickness (+slop).
            let o_plc = placement_dir(s, Some(bldg_plc), cx, cz, z, dx, dz);
            let o_solid = extruded_box(s, w, thick + 100.0, h);
            let o_shape = shape_rep(s, ctx, o_solid);
            let o_prod = s.add(&format!("IFCPRODUCTDEFINITIONSHAPE($,$,(#{o_shape}))"));
            let g = s.guid();
            let opening = s.add(&format!(
                "IFCOPENINGELEMENT('{g}',#{owner},'Opening',$,$,#{o_plc},#{o_prod},$,.OPENING.)"
            ));
            let g = s.guid();
            s.add(&format!("IFCRELVOIDSELEMENT('{g}',#{owner},$,$,#{wall_id},#{opening})"));

            // The filling element, sized to the opening (thinner than the void).
            let e_plc = placement_dir(s, Some(bldg_plc), cx, cz, z, dx, dz);
            let e_solid = extruded_box(s, w, thick, h);
            let e_shape = shape_rep(s, ctx, e_solid);
            let e_prod = s.add(&format!("IFCPRODUCTDEFINITIONSHAPE($,$,(#{e_shape}))"));
            let g = s.guid();
            let elem = if kind == "door" {
                s.add(&format!(
                    "IFCDOOR('{g}',#{owner},'Door',$,$,#{e_plc},#{e_prod},$,{h:.1},{w:.1},.DOOR.,.SINGLE_SWING_LEFT.,$)"
                ))
            } else {
                s.add(&format!(
                    "IFCWINDOW('{g}',#{owner},'Window',$,$,#{e_plc},#{e_prod},$,{h:.1},{w:.1},.WINDOW.,.NOTDEFINED.,$)"
                ))
            };
            let g = s.guid();
            s.add(&format!("IFCRELFILLSELEMENT('{g}',#{owner},$,$,#{opening},#{elem})"));
        };

    let wall_thick = |cat: &str| if cat == "exterior" { 175.0 } else { 115.0 };
    for d in &doc.doors {
        let Some(idx) = usize::try_from(d.wall_index).ok() else { continue };
        let (Some(wall), Some(Some(wid))) = (doc.walls.get(idx), wall_ifc.get(idx)) else { continue };
        let (sx, sz, ex, ez) = (wall.start.x, wall.start.z, wall.end.x, wall.end.z);
        let len = ((ex - sx).powi(2) + (ez - sz).powi(2)).sqrt().max(1.0);
        let (cx, cz) = (sx + (ex - sx) / len * d.offset, sz + (ez - sz) / len * d.offset);
        place_opening(&mut s, "door", *wid, cx, cz, wall.start.y, (ex - sx) / len, (ez - sz) / len, wall_thick(&wall.category), d.width, d.height);
    }
    for win in &doc.windows {
        let Some(idx) = usize::try_from(win.wall_index).ok() else { continue };
        let (Some(wall), Some(Some(wid))) = (doc.walls.get(idx), wall_ifc.get(idx)) else { continue };
        let (sx, sz, ex, ez) = (wall.start.x, wall.start.z, wall.end.x, wall.end.z);
        let len = ((ex - sx).powi(2) + (ez - sz).powi(2)).sqrt().max(1.0);
        let along = win.offset + win.width * 0.5;
        let (cx, cz) = (sx + (ex - sx) / len * along, sz + (ez - sz) / len * along);
        place_opening(&mut s, "window", *wid, cx, cz, wall.start.y + win.sill_height, (ex - sx) / len, (ez - sz) / len, wall_thick(&wall.category), win.width, win.height);
    }

    // --- Aggregation + containment relationships ---
    let g = s.guid();
    s.add(&format!("IFCRELAGGREGATES('{g}',#{owner},$,$,#{project},({}))", format_args!("#{site}")));
    let g = s.guid();
    s.add(&format!("IFCRELAGGREGATES('{g}',#{owner},$,$,#{site},({}))", format_args!("#{building}")));
    let storey_id_list: Vec<usize> = storey_ids.iter().map(|(_, id)| *id).collect();
    let g = s.guid();
    s.add(&format!("IFCRELAGGREGATES('{g}',#{owner},$,$,#{building},{})", refs(&storey_id_list)));
    for (st, elems) in &contained {
        if elems.is_empty() {
            continue;
        }
        let g = s.guid();
        s.add(&format!(
            "IFCRELCONTAINEDINSPATIALSTRUCTURE('{g}',#{owner},$,$,{},#{st})",
            refs(elems)
        ));
    }

    // --- Assemble the STEP file ---
    format!(
        "ISO-10303-21;\n\
         HEADER;\n\
         FILE_DESCRIPTION(('ViewDefinition [CoordinationView]'),'2;1');\n\
         FILE_NAME('{project_name}.ifc','{date}',(''),(''),'Legible Studio','Legible Studio','');\n\
         FILE_SCHEMA(('IFC4'));\n\
         ENDSEC;\n\
         DATA;\n\
         {}\
         ENDSEC;\n\
         END-ISO-10303-21;\n",
        s.body
    )
}

/// `IfcLocalPlacement` at `(x,y,z)` (IFC X=plan-x, Y=plan-z, Z=elevation),
/// default axes, optionally relative to a parent placement.
#[allow(clippy::many_single_char_names)]
fn local_placement(s: &mut Spf, parent: Option<usize>, x: f32, y: f32, z: f32) -> usize {
    let p = s.add(&pt(x, y, z));
    let a = s.add(&format!("IFCAXIS2PLACEMENT3D(#{p},$,$)"));
    let rel = parent.map_or_else(|| "$".to_string(), |id| format!("#{id}"));
    s.add(&format!("IFCLOCALPLACEMENT({rel},#{a})"))
}

/// `IfcLocalPlacement` at `(x,y,z)` with the local X axis aligned to plan
/// direction `(dx,dz)` and Z up.
#[allow(clippy::many_single_char_names, clippy::too_many_arguments)]
fn placement_dir(s: &mut Spf, parent: Option<usize>, x: f32, y: f32, z: f32, dx: f32, dz: f32) -> usize {
    let p = s.add(&pt(x, y, z));
    let zaxis = s.add("IFCDIRECTION((0.,0.,1.))");
    let xaxis = s.add(&format!("IFCDIRECTION(({dx:.6},{dz:.6},0.))"));
    let a = s.add(&format!("IFCAXIS2PLACEMENT3D(#{p},#{zaxis},#{xaxis})"));
    let rel = parent.map_or_else(|| "$".to_string(), |id| format!("#{id}"));
    s.add(&format!("IFCLOCALPLACEMENT({rel},#{a})"))
}

/// An extruded box solid: a centred `x_dim × y_dim` rectangle extruded `height`
/// up the local +Z.
fn extruded_box(s: &mut Spf, x_dim: f32, y_dim: f32, height: f32) -> usize {
    let o2 = s.add("IFCCARTESIANPOINT((0.,0.))");
    let d2 = s.add("IFCDIRECTION((1.,0.))");
    let pos2 = s.add(&format!("IFCAXIS2PLACEMENT2D(#{o2},#{d2})"));
    let profile = s.add(&format!(
        "IFCRECTANGLEPROFILEDEF(.AREA.,$,#{pos2},{x_dim:.3},{y_dim:.3})"
    ));
    let o3 = s.add(&pt(0.0, 0.0, 0.0));
    let pos3 = s.add(&format!("IFCAXIS2PLACEMENT3D(#{o3},$,$)"));
    let dir = s.add("IFCDIRECTION((0.,0.,1.))");
    s.add(&format!(
        "IFCEXTRUDEDAREASOLID(#{profile},#{pos3},#{dir},{height:.3})"
    ))
}

/// A `Body`/`SweptSolid` shape representation wrapping one solid.
fn shape_rep(s: &mut Spf, ctx: usize, solid: usize) -> usize {
    s.add(&format!(
        "IFCSHAPEREPRESENTATION(#{ctx},'Body','SweptSolid',(#{solid}))"
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use archgeometry::{SchemaLevel, SchemaRoom, SchemaWall, SchemaWindow};
    use glam::Vec3;

    fn two_storey_doc() -> SchemaDocument {
        let mut doc = SchemaDocument { width: 8000.0, depth: 6000.0, ..Default::default() };
        doc.levels = vec![
            SchemaLevel { name: "Level 1".into(), elevation: 0.0, ..Default::default() },
            SchemaLevel { name: "Level 2".into(), elevation: 3048.0, ..Default::default() },
            SchemaLevel { name: "Roof Level".into(), elevation: 6096.0, ..Default::default() },
        ];
        for (lvl, base) in [("Level 1", 0.0), ("Level 2", 3048.0)] {
            doc.walls.push(SchemaWall {
                start: Vec3::new(0.0, base, 0.0),
                end: Vec3::new(8000.0, base, 0.0),
                height: 2700.0,
                category: "exterior".into(),
                level_name: lvl.into(),
                ..Default::default()
            });
        }
        doc.rooms.insert(
            "living".into(),
            SchemaRoom { id: "living".into(), name: "Living".into(), level: "Level 1".into(), ..Default::default() },
        );
        doc.windows.push(SchemaWindow {
            wall_index: 0,
            offset: 1000.0,
            width: 1200.0,
            height: 1200.0,
            sill_height: 900.0,
            ..Default::default()
        });
        // give the room real bounds
        if let Some(r) = doc.rooms.get_mut("living") {
            r.bounds.x = 0.0;
            r.bounds.y = 0.0;
            r.bounds.width = 4000.0;
            r.bounds.height = 3000.0;
        }
        doc
    }

    #[test]
    fn guid_is_22_chars_from_the_ifc_alphabet() {
        let g = ifc_guid(123_456_789);
        assert_eq!(g.len(), 22);
        assert!(g.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'$'));
        // Distinct seeds give distinct guids.
        assert_ne!(ifc_guid(1), ifc_guid(2));
    }

    #[test]
    fn ifc_has_header_schema_and_spatial_hierarchy() {
        let ifc = to_ifc(&two_storey_doc(), "Test", "2026-05-24");
        assert!(ifc.starts_with("ISO-10303-21;"));
        assert!(ifc.contains("FILE_SCHEMA(('IFC4'))"));
        assert!(ifc.trim_end().ends_with("END-ISO-10303-21;"));
        for e in ["IFCPROJECT(", "IFCSITE(", "IFCBUILDING(", "IFCBUILDINGSTOREY(", "IFCUNITASSIGNMENT("] {
            assert!(ifc.contains(e), "missing {e}");
        }
        // Two non-roof storeys.
        assert_eq!(ifc.matches("IFCBUILDINGSTOREY(").count(), 2);
        // Aggregation: project→site→building→storeys (3 rels) + containment.
        assert_eq!(ifc.matches("IFCRELAGGREGATES(").count(), 3);
        assert!(ifc.contains("IFCRELCONTAINEDINSPATIALSTRUCTURE("));
    }

    #[test]
    fn ifc_emits_walls_spaces_and_openings() {
        let ifc = to_ifc(&two_storey_doc(), "Test", "2026-05-24");
        assert_eq!(ifc.matches("=IFCWALL(").count(), 2);
        assert_eq!(ifc.matches("=IFCSPACE(").count(), 1);
        assert_eq!(ifc.matches("=IFCWINDOW(").count(), 1);
        // Every entity has geometry referencing the shared context.
        assert!(ifc.contains("IFCEXTRUDEDAREASOLID("));
        assert!(ifc.contains("IFCGEOMETRICREPRESENTATIONCONTEXT("));
    }

    #[test]
    fn openings_void_their_host_wall_and_are_filled() {
        let ifc = to_ifc(&two_storey_doc(), "Test", "2026-05-24");
        // One window → one opening that voids the wall and is filled.
        let openings = ifc.matches("=IFCOPENINGELEMENT(").count();
        assert_eq!(openings, 1);
        assert_eq!(ifc.matches("=IFCRELVOIDSELEMENT(").count(), openings);
        assert_eq!(ifc.matches("=IFCRELFILLSELEMENT(").count(), openings);
    }

    #[test]
    fn one_slab_per_storey_with_floor_type() {
        let ifc = to_ifc(&two_storey_doc(), "Test", "2026-06-04");
        // Two non-roof storeys → two IfcSlab entities.
        assert_eq!(ifc.matches("=IFCSLAB(").count(), 2);
        // Predefined type is .FLOOR.
        assert!(ifc.contains(".FLOOR.)"));
        // Each slab carries the storey name in the label.
        assert!(ifc.contains("'Slab - Level 1'"));
        assert!(ifc.contains("'Slab - Level 2'"));
    }

    #[test]
    fn one_strip_footing_per_exterior_wall_on_ground_storey() {
        let ifc = to_ifc(&two_storey_doc(), "Test", "2026-06-04");
        // Fixture has one exterior wall on Level 1, one on Level 2.
        // Only the Level-1 wall gets a footing.
        assert_eq!(ifc.matches("=IFCFOOTING(").count(), 1);
        assert!(ifc.contains(".STRIP_FOOTING.)"));
        assert!(ifc.contains("'Strip Footing'"));
    }

    #[test]
    fn one_stair_per_up_flight_with_flight_attributes_and_aggregate() {
        let mut doc = two_storey_doc();
        // The same shaft appears as an "up" stair on L1 and a "down" stair on L2.
        doc.stairs.push(archgeometry::SchemaStair {
            id: "stairs_1".into(),
            level_name: "Level 1".into(),
            x: 0.0,
            y: 0.0,
            width: 1828.8,
            depth: 3352.8,
            run_dir: "+y".into(),
            num_risers: 16,
            num_treads: 15,
            riser_height: 190.5,
            tread_run: 255.0,
            width_clear: 864.0,
            floor_to_floor: 3048.0,
            shape: "switchback".into(),
            going: "up".into(),
        });
        doc.stairs.push(archgeometry::SchemaStair {
            level_name: "Level 2".into(),
            going: "down".into(),
            ..doc.stairs[0].clone()
        });

        let ifc = to_ifc(&doc, "Test", "2026-06-16");
        // Only the "up" flight becomes a physical stair — no doubling.
        assert_eq!(ifc.matches("=IFCSTAIR(").count(), 1);
        assert_eq!(ifc.matches("=IFCSTAIRFLIGHT(").count(), 1);
        // Switchback → half-turn stair; flight carries the riser/tread counts.
        assert!(ifc.contains(".HALF_TURN_STAIR.)"));
        assert!(ifc.contains("16,15,190.5,255.0,.STRAIGHT.)"), "flight riser/tread attributes");
        // The flight is aggregated under its stair (one extra IfcRelAggregates
        // beyond the 3 spatial ones).
        assert_eq!(ifc.matches("IFCRELAGGREGATES(").count(), 4);
    }

    #[test]
    fn straight_stair_is_a_straight_run_type() {
        let mut doc = two_storey_doc();
        doc.stairs.push(archgeometry::SchemaStair {
            level_name: "Level 1".into(),
            width: 1100.0,
            depth: 4200.0,
            run_dir: "+y".into(),
            num_risers: 16,
            num_treads: 15,
            riser_height: 190.5,
            tread_run: 255.0,
            floor_to_floor: 3048.0,
            shape: "straight".into(),
            going: "up".into(),
            ..Default::default()
        });
        let ifc = to_ifc(&doc, "Test", "2026-06-16");
        assert_eq!(ifc.matches("=IFCSTAIR(").count(), 1);
        assert!(ifc.contains(".STRAIGHT_RUN_STAIR.)"));
    }

    #[test]
    fn l_shaped_stair_is_a_quarter_turn_type() {
        let mut doc = two_storey_doc();
        doc.stairs.push(archgeometry::SchemaStair {
            level_name: "Level 1".into(),
            width: 1765.0,
            depth: 3960.0,
            run_dir: "+y".into(),
            num_risers: 16,
            num_treads: 15,
            riser_height: 190.5,
            tread_run: 255.0,
            floor_to_floor: 3048.0,
            shape: "l_shaped".into(),
            going: "up".into(),
            ..Default::default()
        });
        let ifc = to_ifc(&doc, "Test", "2026-06-16");
        assert_eq!(ifc.matches("=IFCSTAIR(").count(), 1);
        assert!(ifc.contains(".QUARTER_TURN_STAIR.)"));
    }

    #[test]
    fn empty_doc_omits_slabs_and_footings_cleanly() {
        let mut doc = SchemaDocument::default();
        doc.width = 0.0;
        doc.depth = 0.0;
        let ifc = to_ifc(&doc, "Empty", "2026-06-04");
        assert_eq!(ifc.matches("=IFCSLAB(").count(), 0);
        assert_eq!(ifc.matches("=IFCFOOTING(").count(), 0);
        // STEP file is still valid.
        assert!(ifc.starts_with("ISO-10303-21;"));
        assert!(ifc.trim_end().ends_with("END-ISO-10303-21;"));
    }
}
