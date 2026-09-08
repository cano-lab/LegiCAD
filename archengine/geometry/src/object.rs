//! Parametric object model — the heart of the kernel.
//!
//! A consumer describes its scene as `Object`s (kind + params + constraints),
//! registers an `ObjectGenerator` per kind and `ValidationRule`s for its
//! domain, optionally sets a `Solver`, then calls `Registry::build` to get
//! world-space geometry and `Registry::validate` to get violations.
//!
//! Scope (per PARAMETRIC_KERNEL_SPEC.md §0): the kernel's own resolver
//! handles only the EXPLICIT placement constraints `FixedAt` and
//! `AttachedTo` (hardpoints). Everything needing search — `InsideRegion`,
//! `AdjacentTo`, `AlignedWith`, `OffsetFrom` — is the consumer `Solver`'s
//! job. Mech needs no solver (parts are fixed/attached); Legible plugs its
//! room-layout solver in.

use std::collections::HashMap;

use glam::{Mat4, Vec2, Vec4};
use crate::mesh::{Mesh, Transform};
use serde::{Deserialize, Serialize};

/// Stable identifier for an object within a scene.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord, Serialize, Deserialize)]
pub struct ObjectId(pub u64);

/// Identifier for a sketched region (e.g. a lot boundary).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct RegionId(pub u64);

/// Free-form, type-specific parameters. `serde_json::Value` keeps the kernel
/// agnostic to each consumer's parameter shapes.
pub type ParamMap = std::collections::BTreeMap<String, serde_json::Value>;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum Side {
    Left,
    Right,
    Front,
    Back,
    Top,
    Bottom,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum Axis {
    X,
    Y,
    Z,
}

/// A named attachment point on an object, in the object's local space.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Hardpoint {
    pub id: String,
    pub transform: Transform,
    pub tags: Vec<String>,
}

/// How an object is placed/related. The kernel resolves `FixedAt` and
/// `AttachedTo`; the rest are hints for a consumer `Solver`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum Constraint {
    FixedAt(Transform),
    AttachedTo { parent: ObjectId, hardpoint: String },
    InsideRegion(RegionId),
    AdjacentTo { other: ObjectId, side: Side },
    AlignedWith { other: ObjectId, axis: Axis },
    OffsetFrom { other: ObjectId, distance: f32 },
    Custom(String),
}

/// A placeable, generatable thing. Domain-agnostic.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Object {
    pub id: ObjectId,
    pub kind: String,
    #[serde(default)]
    pub params: ParamMap,
    #[serde(default)]
    pub transform: Transform,
    #[serde(default)]
    pub constraints: Vec<Constraint>,
    #[serde(default)]
    pub children: Vec<ObjectId>,
}

impl Object {
    #[must_use]
    pub fn new(id: u64, kind: impl Into<String>) -> Self {
        Self {
            id: ObjectId(id),
            kind: kind.into(),
            params: ParamMap::new(),
            transform: Transform::identity(),
            constraints: Vec::new(),
            children: Vec::new(),
        }
    }
    #[must_use]
    pub fn with_param(mut self, key: &str, value: serde_json::Value) -> Self {
        self.params.insert(key.to_string(), value);
        self
    }
    #[must_use]
    pub fn with_constraint(mut self, c: Constraint) -> Self {
        self.constraints.push(c);
        self
    }
}

/// A sketched region — a 2D boundary polygon a `Solver` can place objects within.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Region {
    pub id: RegionId,
    pub polygon: Vec<Vec2>,
}

/// The mutable world a `Solver` operates on and `build` consumes.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Scene {
    pub objects: Vec<Object>,
    pub regions: Vec<Region>,
}

impl Scene {
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }
    pub fn add(&mut self, obj: Object) -> ObjectId {
        let id = obj.id;
        self.objects.push(obj);
        id
    }
    #[must_use]
    pub fn get(&self, id: ObjectId) -> Option<&Object> {
        self.objects.iter().find(|o| o.id == id)
    }
}

/// Output of a single object's generator (world-space mesh after `build`).
#[derive(Debug, Clone, Default)]
pub struct GeneratedGeometry {
    pub mesh: Option<Mesh>,
}

/// Read-only context handed to generators: the scene + resolved world
/// transforms so a generator can look up its parent's placement.
pub struct GenContext<'a> {
    pub scene: &'a Scene,
    pub world: &'a HashMap<ObjectId, Mat4>,
}

impl GenContext<'_> {
    #[must_use]
    pub fn world_of(&self, id: ObjectId) -> Mat4 {
        self.world.get(&id).copied().unwrap_or(Mat4::IDENTITY)
    }
}

pub trait ObjectGenerator: Send + Sync {
    fn kind(&self) -> &str;
    /// Generate this object's geometry in its **local** space. `build`
    /// bakes the resolved world transform in afterward.
    fn generate(&self, obj: &Object, ctx: &GenContext) -> GeneratedGeometry;
    /// Named attachment points, in local space. Default: none.
    fn hardpoints(&self, _obj: &Object) -> Vec<Hardpoint> {
        Vec::new()
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Severity {
    Info,
    Warning,
    Critical,
}

#[derive(Debug, Clone)]
pub struct Violation {
    pub object: ObjectId,
    pub rule: String,
    pub message: String,
    pub severity: Severity,
}

pub trait ValidationRule: Send + Sync {
    fn applies_to(&self, kind: &str) -> bool;
    fn check(&self, obj: &Object, scene: &Scene) -> Vec<Violation>;
}

/// Consumer hook for domain layout solving (search-based constraints).
pub trait Solver: Send + Sync {
    fn solve(&self, scene: &mut Scene);
}

/// World-space geometry for the whole scene, in object order.
#[derive(Debug, Clone, Default)]
pub struct SceneGeometry {
    pub per_object: Vec<(ObjectId, GeneratedGeometry)>,
}

impl SceneGeometry {
    /// Flatten every object's mesh into one merged mesh.
    #[must_use]
    pub fn merged(&self) -> Mesh {
        let mut m = Mesh::new();
        for (_, g) in &self.per_object {
            if let Some(mesh) = &g.mesh {
                m.merge(mesh);
            }
        }
        m
    }
}

#[derive(Default)]
pub struct Registry {
    generators: HashMap<String, Box<dyn ObjectGenerator>>,
    validators: Vec<Box<dyn ValidationRule>>,
    solver: Option<Box<dyn Solver>>,
}

impl Registry {
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }
    pub fn register_generator(&mut self, g: Box<dyn ObjectGenerator>) {
        self.generators.insert(g.kind().to_string(), g);
    }
    pub fn register_validator(&mut self, v: Box<dyn ValidationRule>) {
        self.validators.push(v);
    }
    pub fn set_solver(&mut self, s: Box<dyn Solver>) {
        self.solver = Some(s);
    }

    /// Pipeline: (a) run the solver if any, (b) resolve world transforms
    /// from the explicit placement graph, (c) run generators, baking the
    /// resolved world transform into each mesh.
    pub fn build(&self, scene: &mut Scene) -> SceneGeometry {
        if let Some(s) = &self.solver {
            s.solve(scene);
        }
        let world = self.resolve_world_transforms(scene);
        let ctx = GenContext {
            scene,
            world: &world,
        };
        let mut out = SceneGeometry::default();
        for obj in &scene.objects {
            if let Some(g) = self.generators.get(&obj.kind) {
                let mut geo = g.generate(obj, &ctx);
                let m = world.get(&obj.id).copied().unwrap_or(Mat4::IDENTITY);
                if let Some(mesh) = geo.mesh.as_mut() {
                    bake_transform(mesh, m);
                }
                out.per_object.push((obj.id, geo));
            }
        }
        out
    }

    #[must_use]
    pub fn validate(&self, scene: &Scene) -> Vec<Violation> {
        let mut out = Vec::new();
        for obj in &scene.objects {
            for v in &self.validators {
                if v.applies_to(&obj.kind) {
                    out.extend(v.check(obj, scene));
                }
            }
        }
        out
    }

    /// Resolve each object's world transform from `FixedAt` / `AttachedTo`
    /// (memoized, cycle-guarded). Objects with neither use their local
    /// `transform`. Named-hardpoint offsets are looked up from the parent's
    /// generator. Search constraints are ignored here — the `Solver` is
    /// expected to have baked their results into `transform`/`FixedAt`.
    fn resolve_world_transforms(&self, scene: &Scene) -> HashMap<ObjectId, Mat4> {
        let by_id: HashMap<ObjectId, &Object> =
            scene.objects.iter().map(|o| (o.id, o)).collect();
        let mut world: HashMap<ObjectId, Mat4> = HashMap::new();
        for o in &scene.objects {
            let mut stack = Vec::new();
            self.resolve_one(o.id, &by_id, &mut world, &mut stack);
        }
        world
    }

    fn resolve_one(
        &self,
        id: ObjectId,
        by_id: &HashMap<ObjectId, &Object>,
        world: &mut HashMap<ObjectId, Mat4>,
        stack: &mut Vec<ObjectId>,
    ) -> Mat4 {
        if let Some(m) = world.get(&id) {
            return *m;
        }
        if stack.contains(&id) {
            // cycle — fall back to identity, don't loop forever
            return Mat4::IDENTITY;
        }
        let Some(obj) = by_id.get(&id) else {
            return Mat4::IDENTITY;
        };
        stack.push(id);

        let local = obj.transform.to_mat4();
        let m = match obj.constraints.iter().find_map(placement_of) {
            Some(Placement::Fixed(t)) => t.to_mat4(),
            Some(Placement::Attached { parent, hardpoint }) => {
                let pw = self.resolve_one(parent, by_id, world, stack);
                let hp = by_id
                    .get(&parent)
                    .and_then(|p| self.generators.get(&p.kind).map(|g| g.hardpoints(p)))
                    .unwrap_or_default()
                    .into_iter()
                    .find(|h| h.id == hardpoint)
                    .map_or(Mat4::IDENTITY, |h| h.transform.to_mat4());
                pw * hp * local
            }
            None => local,
        };
        stack.pop();
        world.insert(id, m);
        m
    }
}

enum Placement {
    Fixed(Transform),
    Attached { parent: ObjectId, hardpoint: String },
}

fn placement_of(c: &Constraint) -> Option<Placement> {
    match c {
        Constraint::FixedAt(t) => Some(Placement::Fixed(*t)),
        Constraint::AttachedTo { parent, hardpoint } => Some(Placement::Attached {
            parent: *parent,
            hardpoint: hardpoint.clone(),
        }),
        _ => None,
    }
}

/// Bake a world transform into a mesh's vertices in place. Normals use the
/// rotation/linear part only (correct for rigid + uniform scale; non-uniform
/// scale normals are a v2 refinement).
fn bake_transform(mesh: &mut Mesh, m: Mat4) {
    if m == Mat4::IDENTITY {
        return;
    }
    let normal_mat = Mat4::from_cols(m.x_axis, m.y_axis, m.z_axis, Vec4::W);
    for v in &mut mesh.vertices {
        let p = m * v.position.extend(1.0);
        v.position = p.truncate();
        let n = normal_mat * v.normal.extend(0.0);
        v.normal = n.truncate().normalize_or_zero();
    }
}

#[cfg(test)]
#[allow(clippy::unnecessary_literal_bound)] // test generators return &str literals to satisfy the trait
mod tests {
    use super::*;
    use glam::Vec3;

    /// A trivial generator: emits a unit-cube-ish single triangle so we can
    /// see the world transform get baked in.
    struct MarkerGen;
    impl ObjectGenerator for MarkerGen {
        fn kind(&self) -> &str {
            "marker"
        }
        fn generate(&self, _obj: &Object, _ctx: &GenContext) -> GeneratedGeometry {
            let mut m = Mesh::new();
            m.add_triangle(Vec3::ZERO, Vec3::X, Vec3::Y, Vec3::Z, Vec3::ONE);
            GeneratedGeometry { mesh: Some(m) }
        }
        fn hardpoints(&self, _obj: &Object) -> Vec<Hardpoint> {
            vec![Hardpoint {
                id: "top".into(),
                transform: Transform::from_translation(Vec3::new(0.0, 10.0, 0.0)),
                tags: vec![],
            }]
        }
    }

    fn registry() -> Registry {
        let mut r = Registry::new();
        r.register_generator(Box::new(MarkerGen));
        r
    }

    #[test]
    fn build_runs_generator_for_registered_kind() {
        let mut scene = Scene::new();
        scene.add(Object::new(1, "marker"));
        scene.add(Object::new(2, "unregistered"));
        let geo = registry().build(&mut scene);
        // Only the registered kind produced geometry.
        assert_eq!(geo.per_object.len(), 1);
        assert_eq!(geo.per_object[0].0, ObjectId(1));
        assert_eq!(geo.merged().triangle_count(), 1);
    }

    #[test]
    fn fixed_at_bakes_world_translation() {
        let mut scene = Scene::new();
        scene.add(
            Object::new(1, "marker")
                .with_constraint(Constraint::FixedAt(Transform::from_translation(Vec3::new(
                    100.0, 0.0, 0.0,
                )))),
        );
        let geo = registry().build(&mut scene);
        let m = geo.merged();
        // The triangle's first vertex was at origin; FixedAt moves it to x=100.
        assert!((m.vertices[0].position.x - 100.0).abs() < 1e-3);
    }

    #[test]
    fn attached_to_composes_parent_world_and_hardpoint() {
        let mut scene = Scene::new();
        // parent fixed at x=100; child attached to parent's "top" hardpoint (y+10).
        scene.add(
            Object::new(1, "marker").with_constraint(Constraint::FixedAt(
                Transform::from_translation(Vec3::new(100.0, 0.0, 0.0)),
            )),
        );
        scene.add(Object::new(2, "marker").with_constraint(Constraint::AttachedTo {
            parent: ObjectId(1),
            hardpoint: "top".into(),
        }));
        let geo = registry().build(&mut scene);
        // child geometry: origin vertex → parent(100,0,0) ∘ hardpoint(0,10,0) = (100,10,0)
        let child = geo
            .per_object
            .iter()
            .find(|(id, _)| *id == ObjectId(2))
            .unwrap();
        let v0 = child.1.mesh.as_ref().unwrap().vertices[0].position;
        assert!((v0.x - 100.0).abs() < 1e-3, "x={}", v0.x);
        assert!((v0.y - 10.0).abs() < 1e-3, "y={}", v0.y);
    }

    struct AlwaysWarn;
    impl ValidationRule for AlwaysWarn {
        fn applies_to(&self, kind: &str) -> bool {
            kind == "marker"
        }
        fn check(&self, obj: &Object, _scene: &Scene) -> Vec<Violation> {
            vec![Violation {
                object: obj.id,
                rule: "always".into(),
                message: "test".into(),
                severity: Severity::Warning,
            }]
        }
    }

    #[test]
    fn validators_run_for_applicable_kinds_only() {
        let mut r = registry();
        r.register_validator(Box::new(AlwaysWarn));
        let mut scene = Scene::new();
        scene.add(Object::new(1, "marker"));
        scene.add(Object::new(2, "other"));
        let v = r.validate(&scene);
        assert_eq!(v.len(), 1);
        assert_eq!(v[0].object, ObjectId(1));
    }

    struct ShiftSolver;
    impl Solver for ShiftSolver {
        fn solve(&self, scene: &mut Scene) {
            for o in &mut scene.objects {
                o.transform.translation += Vec3::new(5.0, 0.0, 0.0);
            }
        }
    }

    #[test]
    fn solver_runs_before_generation() {
        let mut r = registry();
        r.set_solver(Box::new(ShiftSolver));
        let mut scene = Scene::new();
        scene.add(Object::new(1, "marker")); // local transform identity → solver shifts +5
        let geo = r.build(&mut scene);
        let v0 = geo.merged().vertices[0].position;
        assert!((v0.x - 5.0).abs() < 1e-3, "x={}", v0.x);
    }
}
