//! Legible Studio's object catalog, registered against the parametric-kernel.
//!
//! This is the consumer side of `pk-object`: Legible's building-element
//! `ObjectGenerator`s and `ValidationRule`s plug into the kernel `Registry`,
//! exactly the way Mech Arena plugs in its part generators. It proves the
//! catalog/registry pattern end-to-end with a real, kernel-typed generator.
//!
//! Scope note: this hosts a **kernel-native** wall generator (params → a
//! world-space box `pk_geom::Mesh`). Migrating archgeometry's richer
//! generators (door/window cutouts, 2D plan output, structural `stress`)
//! into the kernel is a separate follow-up gated on unifying
//! `archgeometry::Mesh3D` with `pk_geom::Mesh` (the `stress`-field
//! decision). The 2D permit-drawing pipeline stays in `ls-drawing`.

use archgeometry::{SchemaDocument, SchemaWall};
use glam::{Vec2, Vec3};
use pk_geom::{Mesh, Transform};
use pk_object::{
    Constraint, GenContext, GeneratedGeometry, Object, ObjectGenerator, Registry, Scene, Severity,
    Solver, ValidationRule, Violation,
};

/// JSON key under which a wall `Object` carries its `SchemaWall`.
const WALL_PARAM: &str = "wall";

/// JSON key under which a room `Object` carries its `[x, y, w, h]` rect (mm).
pub const ROOM_PARAM: &str = "rect";

/// Default exterior/interior wall thickness in mm (mirrors archgeometry's
/// 150 mm default wall type).
const DEFAULT_THICKNESS: f32 = 150.0;

/// Wrap a `SchemaWall` as a kernel `Object` of kind `"wall"`.
#[must_use]
pub fn wall_object(id: u64, wall: &SchemaWall) -> Object {
    let value = serde_json::to_value(wall).unwrap_or(serde_json::Value::Null);
    Object::new(id, "wall").with_param(WALL_PARAM, value)
}

/// Build a kernel `Scene` from a parsed schema document's walls.
#[must_use]
pub fn scene_from_schema(doc: &SchemaDocument) -> Scene {
    let mut scene = Scene::new();
    for (i, wall) in doc.walls.iter().enumerate() {
        scene.add(wall_object(i as u64, wall));
    }
    scene
}

/// A registry wired with Legible's building catalog + rules.
#[must_use]
pub fn building_registry() -> Registry {
    let mut r = Registry::new();
    r.register_generator(Box::new(WallGenerator));
    r.register_validator(Box::new(WallLengthRule));
    r
}

/// Generates a wall as a 6-face box in **world space** (built directly from
/// the wall's start/end, so no object transform is needed). Winding +
/// per-category colour mirror archgeometry's `solid_mesh` so the shape is
/// the canonical Legible wall.
pub struct WallGenerator;

impl ObjectGenerator for WallGenerator {
    #[allow(clippy::unnecessary_literal_bound)] // trait sig is `-> &str`; we return a literal
    fn kind(&self) -> &str {
        "wall"
    }

    fn generate(&self, obj: &Object, _ctx: &GenContext) -> GeneratedGeometry {
        let Some(wall) = wall_from(obj) else {
            return GeneratedGeometry::default();
        };
        let color = category_color(&wall.category);
        let mesh = wall_box(wall.start, wall.end, wall.height, DEFAULT_THICKNESS, color);
        GeneratedGeometry { mesh: Some(mesh) }
    }
}

/// Flags degenerate (near-zero-length) walls.
pub struct WallLengthRule;

impl ValidationRule for WallLengthRule {
    fn applies_to(&self, kind: &str) -> bool {
        kind == "wall"
    }
    fn check(&self, obj: &Object, _scene: &Scene) -> Vec<Violation> {
        let Some(wall) = wall_from(obj) else {
            return Vec::new();
        };
        let len = (wall.end - wall.start).length();
        if len < 1.0 {
            vec![Violation {
                object: obj.id,
                rule: "catalog.wall_length".into(),
                message: format!("degenerate wall: length {len:.2} mm"),
                severity: Severity::Critical,
            }]
        } else {
            Vec::new()
        }
    }
}

// ============================================================================
// Sketch-driven room layout (Increment 3): a Region (sketched boundary) is
// subdivided into room Objects. This is a kernel `Solver` impl — the same
// hook the full Python room-solver port (Increment 4) will land behind.
// ============================================================================

/// Grid-subdivide an axis-aligned box into ~`target` room rects `[x, y, w, h]`.
/// Picks a near-square `cols × rows` grid. Non-rectangular boundaries use
/// their bounding box for v1.
#[must_use]
pub fn grid_subdivide(min_x: f32, min_y: f32, max_x: f32, max_y: f32, target: usize) -> Vec<[f32; 4]> {
    let w = max_x - min_x;
    let h = max_y - min_y;
    if w <= 0.0 || h <= 0.0 || target == 0 {
        return Vec::new();
    }
    #[allow(clippy::cast_precision_loss, clippy::cast_sign_loss, clippy::cast_possible_truncation)]
    let cols = ((target as f32 * w / h).sqrt().ceil().max(1.0)) as usize;
    #[allow(clippy::cast_precision_loss, clippy::cast_sign_loss, clippy::cast_possible_truncation)]
    let rows = ((target as f32 / cols as f32).ceil().max(1.0)) as usize;
    #[allow(clippy::cast_precision_loss)]
    let cw = w / cols as f32;
    #[allow(clippy::cast_precision_loss)]
    let ch = h / rows as f32;
    let mut rects = Vec::with_capacity(cols * rows);
    for r in 0..rows {
        for c in 0..cols {
            #[allow(clippy::cast_precision_loss)]
            let x = min_x + c as f32 * cw;
            #[allow(clippy::cast_precision_loss)]
            let y = min_y + r as f32 * ch;
            rects.push([x, y, cw, ch]);
        }
    }
    rects
}

fn polygon_bbox(poly: &[Vec2]) -> Option<(f32, f32, f32, f32)> {
    if poly.is_empty() {
        return None;
    }
    let mut min = Vec2::splat(f32::INFINITY);
    let mut max = Vec2::splat(f32::NEG_INFINITY);
    for p in poly {
        min = min.min(*p);
        max = max.max(*p);
    }
    Some((min.x, min.y, max.x, max.y))
}

/// Lays out a grid of rooms inside the first sketched `Region`. Adds one
/// `Object` of kind `"room"` per cell, carrying its `[x, y, w, h]` rect in
/// params. A placeholder for the real room-layout solver (Increment 4),
/// but enough to prove the sketch → constraint → solve → render loop.
pub struct GridRoomSolver {
    pub target_rooms: usize,
}

impl Default for GridRoomSolver {
    fn default() -> Self {
        Self { target_rooms: 6 }
    }
}

impl Solver for GridRoomSolver {
    fn solve(&self, scene: &mut Scene) {
        // Clear any rooms from a previous solve so re-solving is idempotent.
        scene.objects.retain(|o| o.kind != "room");

        let Some(region) = scene.regions.first() else {
            return;
        };
        let Some((min_x, min_y, max_x, max_y)) = polygon_bbox(&region.polygon) else {
            return;
        };
        let rects = grid_subdivide(min_x, min_y, max_x, max_y, self.target_rooms);
        let mut next_id = scene.objects.iter().map(|o| o.id.0).max().unwrap_or(0) + 1;
        for rect in rects {
            let obj = Object::new(next_id, "room")
                .with_param(ROOM_PARAM, serde_json::json!(rect))
                .with_constraint(Constraint::FixedAt(Transform::identity()));
            scene.add(obj);
            next_id += 1;
        }
    }
}

/// Read a room `Object`'s `[x, y, w, h]` rect, if present.
#[must_use]
pub fn room_rect(obj: &Object) -> Option<[f32; 4]> {
    obj.params
        .get(ROOM_PARAM)
        .and_then(|v| serde_json::from_value(v.clone()).ok())
}

// ============================================================================
// "Design anything" generators (Increment 5): kernel-native object types that
// are NOT building elements. They prove the catalog is open — adding a new
// designable thing is just registering a generator, no kernel change. The
// generic `PrimitiveGenerator` is exactly what a non-architecture consumer
// (e.g. a Mech Arena part catalog) would register against the same kernel.
// ============================================================================

/// JSON key holding a freeform object's `[[x, z], ...]` plan profile (mm).
const FREEFORM_PROFILE: &str = "profile";
/// JSON key holding a freeform object's extrusion height (mm, along +Y).
const FREEFORM_HEIGHT: &str = "height";
/// JSON key naming the primitive shape.
const PRIMITIVE_SHAPE: &str = "shape";
/// Extrusion height used when a freeform object omits one.
const DEFAULT_FREEFORM_HEIGHT: f32 = 1000.0;

/// Wrap a sketched 2D `profile` (XZ plan points, mm) as a freeform `Object`
/// extruded `height` mm along +Y. This is the kernel object behind the sketch
/// pad's freeform mode: draw a shape, get geometry.
#[must_use]
pub fn freeform_object(id: u64, profile: &[Vec2], height: f32) -> Object {
    let pts: Vec<[f32; 2]> = profile.iter().map(|p| [p.x, p.y]).collect();
    Object::new(id, "freeform")
        .with_param(FREEFORM_PROFILE, serde_json::json!(pts))
        .with_param(FREEFORM_HEIGHT, serde_json::json!(height))
        .with_constraint(Constraint::FixedAt(Transform::identity()))
}

/// A parametric primitive `Object`, placed at `at` (world mm). `spec` is a
/// JSON object carrying `"shape"` plus that shape's dims (see
/// [`PrimitiveGenerator`]). The generic "design anything" building block.
#[must_use]
pub fn primitive_object(id: u64, spec: &serde_json::Value, at: Vec3) -> Object {
    let mut obj = Object::new(id, "primitive");
    if let serde_json::Value::Object(map) = spec {
        for (k, v) in map {
            obj = obj.with_param(k, v.clone());
        }
    }
    obj.with_constraint(Constraint::FixedAt(Transform::from_translation(at)))
}

/// Registry with the building catalog plus the open "design anything"
/// generators (freeform extrusion + parametric primitives). A mixed scene of
/// walls, rooms, freeform shapes and primitives all build through this.
#[must_use]
pub fn design_registry() -> Registry {
    let mut r = building_registry();
    r.register_generator(Box::new(FreeformGenerator));
    r.register_generator(Box::new(PrimitiveGenerator));
    r
}

/// Extrudes a sketched 2D profile into a prism `Mesh` (local space; the
/// registry bakes the object's `FixedAt` transform afterward).
pub struct FreeformGenerator;

impl ObjectGenerator for FreeformGenerator {
    #[allow(clippy::unnecessary_literal_bound)]
    fn kind(&self) -> &str {
        "freeform"
    }

    fn generate(&self, obj: &Object, _ctx: &GenContext) -> GeneratedGeometry {
        let Some(profile) = freeform_profile(obj) else {
            return GeneratedGeometry::default();
        };
        if profile.len() < 3 {
            return GeneratedGeometry::default();
        }
        #[allow(clippy::cast_possible_truncation)]
        let height = obj
            .params
            .get(FREEFORM_HEIGHT)
            .and_then(serde_json::Value::as_f64)
            .map_or(DEFAULT_FREEFORM_HEIGHT, |h| h as f32);
        let mesh = extrude_profile(&profile, height, Vec3::new(0.72, 0.78, 0.86));
        GeneratedGeometry { mesh: Some(mesh) }
    }
}

/// Dispatches a `"shape"` param to a `pk_primitives` builder. The proof that
/// "design anything" is just data + a generic generator — no per-shape kernel
/// code, and the same generator any consumer reuses.
pub struct PrimitiveGenerator;

impl ObjectGenerator for PrimitiveGenerator {
    #[allow(clippy::unnecessary_literal_bound)]
    fn kind(&self) -> &str {
        "primitive"
    }

    #[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)]
    fn generate(&self, obj: &Object, _ctx: &GenContext) -> GeneratedGeometry {
        let shape = obj
            .params
            .get(PRIMITIVE_SHAPE)
            .and_then(serde_json::Value::as_str)
            .unwrap_or("box");
        let f = |k: &str, d: f32| {
            obj.params
                .get(k)
                .and_then(serde_json::Value::as_f64)
                .map_or(d, |x| x as f32)
        };
        let seg = |d: u32| {
            obj.params
                .get("segments")
                .and_then(serde_json::Value::as_u64)
                .map_or(d, |x| x as u32)
        };
        let dims = read_vec3(obj, "dims", Vec3::splat(1000.0));
        let mesh = match shape {
            "wedge" => pk_primitives::wedge(dims, f("angle_deg", 45.0)),
            "cylinder" => pk_primitives::cylinder(f("radius", 500.0), f("height", 1000.0), seg(24)),
            "cone" => {
                pk_primitives::cone(f("radius", 500.0), f("top_radius", 0.0), f("height", 1000.0), seg(24))
            }
            "sphere" => pk_primitives::sphere(f("radius", 500.0), seg(24)),
            "capsule" => pk_primitives::capsule(f("radius", 300.0), f("length", 1000.0), seg(24)),
            _ => pk_primitives::rounded_box(dims, f("chamfer", 0.0)), // "box" + fallback
        };
        GeneratedGeometry { mesh: Some(mesh) }
    }
}

/// Read a freeform object's `[[x, z], ...]` plan profile as `Vec2`s.
fn freeform_profile(obj: &Object) -> Option<Vec<Vec2>> {
    let raw: Vec<[f32; 2]> = obj
        .params
        .get(FREEFORM_PROFILE)
        .and_then(|v| serde_json::from_value(v.clone()).ok())?;
    Some(raw.into_iter().map(|[x, z]| Vec2::new(x, z)).collect())
}

/// Read a `[x, y, z]` param as a `Vec3`, falling back to `default`.
fn read_vec3(obj: &Object, key: &str, default: Vec3) -> Vec3 {
    obj.params
        .get(key)
        .and_then(|v| serde_json::from_value::<[f32; 3]>(v.clone()).ok())
        .map_or(default, Vec3::from_array)
}

/// Extrude a closed plan `profile` (XZ) into a prism: 4 side faces per edge,
/// fan-triangulated top (+Y) and bottom (−Y). Fan triangulation assumes a
/// roughly convex profile (fine for v1 sketch shapes).
#[allow(clippy::many_single_char_names)]
fn extrude_profile(profile: &[Vec2], height: f32, color: Vec3) -> Mesh {
    let mut m = Mesh::new();
    let n = profile.len();
    if n < 3 {
        return m;
    }
    let bot = |p: Vec2| Vec3::new(p.x, 0.0, p.y);
    let top = |p: Vec2| Vec3::new(p.x, height, p.y);
    for i in 0..n {
        let a = profile[i];
        let b = profile[(i + 1) % n];
        let edge = b - a;
        let len = edge.length();
        if len < 1e-3 {
            continue;
        }
        let d = edge / len;
        let normal = Vec3::new(-d.y, 0.0, d.x); // outward for CCW winding
        m.add_quad(bot(a), top(a), top(b), bot(b), normal, color);
    }
    // Caps: ear-clip the profile so concave shapes triangulate correctly
    // (a fan from vertex 0 only works for convex polygons). Top winds CCW
    // (+Y), bottom reverses (−Y).
    for [i, j, k] in pk_geom::triangulate(profile) {
        m.add_triangle(top(profile[i]), top(profile[j]), top(profile[k]), Vec3::Y, color);
        m.add_triangle(bot(profile[i]), bot(profile[k]), bot(profile[j]), Vec3::NEG_Y, color);
    }
    m
}

fn wall_from(obj: &Object) -> Option<SchemaWall> {
    obj.params
        .get(WALL_PARAM)
        .and_then(|v| serde_json::from_value(v.clone()).ok())
}

fn category_color(category: &str) -> Vec3 {
    match category {
        "exterior" => Vec3::new(0.85, 0.85, 0.8),
        "wet_wall" => Vec3::new(0.7, 0.85, 0.9),
        _ => Vec3::new(0.9, 0.9, 0.88),
    }
}

/// Six-face box from `start` to `end` (in the XZ plane), `height` along Y,
/// `thickness` perpendicular. Returns an empty mesh for a zero-length wall.
fn wall_box(start: Vec3, end: Vec3, height: f32, thickness: f32, color: Vec3) -> Mesh {
    let dir = Vec2::new(end.x - start.x, end.z - start.z);
    let len = dir.length();
    let mut m = Mesh::new();
    if len < 1e-3 {
        return m;
    }
    let d = dir / len;
    let perp = Vec2::new(-d.y, d.x);
    let ht = thickness * 0.5;

    let b0 = Vec3::new(start.x + perp.x * ht, start.y, start.z + perp.y * ht);
    let b1 = Vec3::new(start.x - perp.x * ht, start.y, start.z - perp.y * ht);
    let b2 = Vec3::new(end.x - perp.x * ht, start.y, end.z - perp.y * ht);
    let b3 = Vec3::new(end.x + perp.x * ht, start.y, end.z + perp.y * ht);
    let top_y = start.y + height;
    let t0 = Vec3::new(b0.x, top_y, b0.z);
    let t1 = Vec3::new(b1.x, top_y, b1.z);
    let t2 = Vec3::new(b2.x, top_y, b2.z);
    let t3 = Vec3::new(b3.x, top_y, b3.z);

    m.add_quad(b0, t0, t3, b3, Vec3::new(perp.x, 0.0, perp.y), color); // front
    m.add_quad(b1, b2, t2, t1, Vec3::new(-perp.x, 0.0, -perp.y), color); // back
    m.add_quad(b0, b1, t1, t0, Vec3::new(-d.x, 0.0, -d.y), color); // left end
    m.add_quad(b3, t3, t2, b2, Vec3::new(d.x, 0.0, d.y), color); // right end
    m.add_quad(t0, t1, t2, t3, Vec3::new(0.0, 1.0, 0.0), color); // top
    m.add_quad(b0, b3, b2, b1, Vec3::new(0.0, -1.0, 0.0), color); // bottom
    m
}

#[cfg(test)]
mod tests {
    use super::*;

    fn rect_walls() -> Vec<SchemaWall> {
        [
            ((0.0, 0.0), (5000.0, 0.0)),
            ((5000.0, 0.0), (5000.0, 4000.0)),
            ((5000.0, 4000.0), (0.0, 4000.0)),
            ((0.0, 4000.0), (0.0, 0.0)),
        ]
        .into_iter()
        .map(|((sx, sz), (ex, ez))| SchemaWall {
            start: Vec3::new(sx, 0.0, sz),
            end: Vec3::new(ex, 0.0, ez),
            height: 2700.0,
            category: "exterior".into(),
            ..Default::default()
        })
        .collect()
    }

    fn scene_of(walls: &[SchemaWall]) -> Scene {
        let mut s = Scene::new();
        for (i, w) in walls.iter().enumerate() {
            s.add(wall_object(i as u64, w));
        }
        s
    }

    #[test]
    fn registry_builds_one_box_mesh_per_wall() {
        let walls = rect_walls();
        let mut scene = scene_of(&walls);
        let geo = building_registry().build(&mut scene);
        assert_eq!(geo.per_object.len(), 4);
        for (_, g) in &geo.per_object {
            let m = g.mesh.as_ref().unwrap();
            assert_eq!(m.vertex_count(), 24); // 6 faces * 4
            assert_eq!(m.triangle_count(), 12);
        }
        let merged = geo.merged();
        assert_eq!(merged.vertex_count(), 96);
        assert_eq!(merged.triangle_count(), 48);
    }

    #[test]
    fn wall_mesh_is_world_placed_from_start_end() {
        let walls = vec![SchemaWall {
            start: Vec3::new(0.0, 0.0, 0.0),
            end: Vec3::new(5000.0, 0.0, 0.0),
            height: 2700.0,
            category: "exterior".into(),
            ..Default::default()
        }];
        let mut scene = scene_of(&walls);
        let geo = building_registry().build(&mut scene);
        let bb = geo.merged().aabb();
        // Spans the wall length in X, thickness in Z, height in Y.
        assert!((bb.size().x - 5000.0).abs() < 1.0);
        assert!((bb.size().y - 2700.0).abs() < 1.0);
        assert!((bb.size().z - DEFAULT_THICKNESS).abs() < 1.0);
    }

    #[test]
    fn validator_flags_degenerate_wall() {
        let walls = vec![SchemaWall {
            start: Vec3::ZERO,
            end: Vec3::ZERO,
            height: 2700.0,
            category: "interior".into(),
            ..Default::default()
        }];
        let scene = scene_of(&walls);
        let v = building_registry().validate(&scene);
        assert_eq!(v.len(), 1);
        assert_eq!(v[0].rule, "catalog.wall_length");
        assert_eq!(v[0].severity, Severity::Critical);
    }

    #[test]
    fn scene_from_schema_makes_one_object_per_wall() {
        let doc = SchemaDocument {
            walls: rect_walls(),
            ..Default::default()
        };
        let scene = scene_from_schema(&doc);
        assert_eq!(scene.objects.len(), 4);
        assert!(scene.objects.iter().all(|o| o.kind == "wall"));
    }

    #[test]
    fn grid_subdivide_tiles_the_box() {
        let rects = grid_subdivide(0.0, 0.0, 6000.0, 4000.0, 6);
        assert!(!rects.is_empty());
        // Cells cover the whole box area with no gaps/overlap.
        let total: f32 = rects.iter().map(|[_, _, w, h]| w * h).sum();
        assert!((total - 6000.0 * 4000.0).abs() < 1.0, "total area {total}");
        // Roughly the requested room count.
        assert!((4..=9).contains(&rects.len()), "got {} rooms", rects.len());
    }

    #[test]
    fn grid_subdivide_degenerate_box_is_empty() {
        assert!(grid_subdivide(0.0, 0.0, 0.0, 0.0, 6).is_empty());
        assert!(grid_subdivide(0.0, 0.0, 100.0, 100.0, 0).is_empty());
    }

    #[test]
    fn grid_room_solver_populates_rooms_from_region() {
        use pk_object::{Region, RegionId};
        let mut scene = Scene::new();
        scene.regions.push(Region {
            id: RegionId(0),
            polygon: vec![
                Vec2::new(0.0, 0.0),
                Vec2::new(6000.0, 0.0),
                Vec2::new(6000.0, 4000.0),
                Vec2::new(0.0, 4000.0),
            ],
        });
        GridRoomSolver { target_rooms: 6 }.solve(&mut scene);
        let rooms: Vec<_> = scene.objects.iter().filter(|o| o.kind == "room").collect();
        assert!(!rooms.is_empty());
        // Every room carries a readable rect inside the boundary bbox.
        for o in &rooms {
            let [x, y, w, h] = room_rect(o).expect("room has a rect");
            assert!(x >= 0.0 && y >= 0.0 && x + w <= 6000.01 && y + h <= 4000.01);
        }
    }

    #[test]
    fn freeform_extrudes_a_square_profile_into_a_prism() {
        // Unit square in plan (XZ), extruded 1000 mm up.
        let profile = vec![
            Vec2::new(0.0, 0.0),
            Vec2::new(2000.0, 0.0),
            Vec2::new(2000.0, 1500.0),
            Vec2::new(0.0, 1500.0),
        ];
        let mut scene = Scene::new();
        scene.add(freeform_object(0, &profile, 1000.0));
        let geo = design_registry().build(&mut scene);
        let m = geo.per_object[0].1.mesh.as_ref().unwrap();
        // 4 side quads (8 tris) + 2 caps (2 tris each) = 12 tris.
        assert_eq!(m.triangle_count(), 12);
        let bb = m.aabb();
        assert!((bb.size().x - 2000.0).abs() < 1.0);
        assert!((bb.size().z - 1500.0).abs() < 1.0);
        assert!((bb.size().y - 1000.0).abs() < 1.0); // extrusion height
    }

    #[test]
    fn freeform_extrudes_a_concave_l_shape_with_ear_clipped_caps() {
        // An L-shaped plan (6 verts, one reflex corner) — fan triangulation
        // would spill outside the polygon; ear clipping keeps the caps inside.
        let l = [
            Vec2::new(0.0, 0.0),
            Vec2::new(2000.0, 0.0),
            Vec2::new(2000.0, 1000.0),
            Vec2::new(1000.0, 1000.0),
            Vec2::new(1000.0, 2000.0),
            Vec2::new(0.0, 2000.0),
        ];
        let mut scene = Scene::new();
        scene.add(freeform_object(0, &l, 800.0));
        let geo = design_registry().build(&mut scene);
        let m = geo.per_object[0].1.mesh.as_ref().unwrap();
        // 6 side quads (12 tris) + 2 caps of (n-2)=4 tris each = 20 tris.
        assert_eq!(m.triangle_count(), 20);
        let bb = m.aabb();
        // Bounds match the L's extent — no triangle spills past it.
        assert!((bb.size().x - 2000.0).abs() < 1.0);
        assert!((bb.size().z - 2000.0).abs() < 1.0);
        assert!((bb.size().y - 800.0).abs() < 1.0);
    }

    #[test]
    fn primitive_box_is_placed_at_its_fixed_transform() {
        let spec = serde_json::json!({ "shape": "box", "dims": [800.0, 600.0, 400.0] });
        let mut scene = Scene::new();
        scene.add(primitive_object(0, &spec, Vec3::new(5000.0, 0.0, 3000.0)));
        let geo = design_registry().build(&mut scene);
        let bb = geo.per_object[0].1.mesh.as_ref().unwrap().aabb();
        // rounded_box is centred on origin in local space; FixedAt translates it.
        assert!((bb.center().x - 5000.0).abs() < 1.0, "x center {}", bb.center().x);
        assert!((bb.center().z - 3000.0).abs() < 1.0, "z center {}", bb.center().z);
        assert!((bb.size().x - 800.0).abs() < 1.0);
    }

    #[test]
    fn primitive_dispatch_covers_every_shape() {
        for shape in ["box", "cylinder", "cone", "sphere", "capsule", "wedge"] {
            let spec = serde_json::json!({ "shape": shape });
            let mut scene = Scene::new();
            scene.add(primitive_object(0, &spec, Vec3::ZERO));
            let geo = design_registry().build(&mut scene);
            let m = geo.per_object[0].1.mesh.as_ref().unwrap();
            assert!(m.triangle_count() > 0, "{shape} produced an empty mesh");
        }
    }

    #[test]
    fn design_registry_builds_a_mixed_scene() {
        // walls + a freeform shape + a primitive, all through one registry.
        let mut scene = Scene::new();
        for (i, w) in rect_walls().iter().enumerate() {
            scene.add(wall_object(i as u64, w));
        }
        scene.add(freeform_object(
            100,
            &[Vec2::new(0.0, 0.0), Vec2::new(1000.0, 0.0), Vec2::new(500.0, 1000.0)],
            500.0,
        ));
        scene.add(primitive_object(
            101,
            &serde_json::json!({ "shape": "cylinder", "radius": 300.0, "height": 800.0 }),
            Vec3::new(2500.0, 0.0, 2000.0),
        ));
        let geo = design_registry().build(&mut scene);
        assert_eq!(geo.per_object.len(), 6); // 4 walls + 1 freeform + 1 primitive
        for (_, g) in &geo.per_object {
            assert!(g.mesh.as_ref().is_some_and(|m| m.triangle_count() > 0));
        }
    }

    #[test]
    fn grid_room_solver_is_idempotent() {
        use pk_object::{Region, RegionId};
        let mut scene = Scene::new();
        scene.regions.push(Region {
            id: RegionId(0),
            polygon: vec![
                Vec2::new(0.0, 0.0),
                Vec2::new(5000.0, 0.0),
                Vec2::new(5000.0, 5000.0),
                Vec2::new(0.0, 5000.0),
            ],
        });
        let s = GridRoomSolver { target_rooms: 4 };
        s.solve(&mut scene);
        let first = scene.objects.iter().filter(|o| o.kind == "room").count();
        s.solve(&mut scene); // re-solve must not accumulate
        let second = scene.objects.iter().filter(|o| o.kind == "room").count();
        assert_eq!(first, second);
    }
}
