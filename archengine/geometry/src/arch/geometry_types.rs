//! Output geometry types — port of
//! `Shared/ArchGeometry/include/archgeometry/geometry_types.hpp`.
//!
//! These types represent the *computed* geometry produced by the
//! generators (wall, floor, roof, opening, room). Consumers use them for
//! 3D rendering (`Mesh3D`) or 2D drawings (`Geometry2D`).
//!
//! The C++ duplicates some fields under alias names (`polygon`/`boundary`,
//! `centroid`/`center`, `room_name`/`label`) for "compatibility." The
//! Rust port keeps a single canonical field per concept.

use crate::arch::wire::{vec2_array, vec3_array};
use glam::{Vec2, Vec3};
use serde::{Deserialize, Serialize};

/// 2D point alias.
pub type Point2D = Vec2;

// ---------------------------------------------------------------------------
// 3D Mesh Types
// ---------------------------------------------------------------------------

/// Vertex for 3D mesh output (CPU-side; renderer crate adapts to GPU layout).
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct Vertex3D {
    #[serde(with = "vec3_array")]
    pub position: Vec3,
    #[serde(with = "vec3_array")]
    pub normal: Vec3,
    #[serde(default = "default_vertex_color", with = "vec3_array")]
    pub color: Vec3,
    #[serde(default, with = "vec2_array")]
    pub uv: Vec2,
    /// Stress / utilisation value for structural visualisation.
    #[serde(default)]
    pub stress: f32,
}

fn default_vertex_color() -> Vec3 {
    Vec3::splat(0.9)
}

impl Default for Vertex3D {
    fn default() -> Self {
        Self {
            position: Vec3::ZERO,
            normal: Vec3::Y,
            color: default_vertex_color(),
            uv: Vec2::ZERO,
            stress: 0.0,
        }
    }
}

/// Triangle face — three indices into a `Mesh3D::vertices` array.
#[derive(Debug, Clone, Copy, PartialEq, Default, Serialize, Deserialize)]
pub struct Triangle {
    pub v0: u32,
    pub v1: u32,
    pub v2: u32,
}

impl Triangle {
    #[must_use]
    pub const fn new(v0: u32, v1: u32, v2: u32) -> Self {
        Self { v0, v1, v2 }
    }
}

/// 3D mesh — vertices + triangle faces + element metadata.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct Mesh3D {
    #[serde(default)]
    pub vertices: Vec<Vertex3D>,
    #[serde(default)]
    pub faces: Vec<Triangle>,

    #[serde(default)]
    pub element_id: String,
    /// `"wall"`, `"floor"`, `"roof"`, `"door"`, `"window"`.
    #[serde(default)]
    pub element_type: String,
    /// LOD level where this mesh first appears.
    #[serde(default)]
    pub lod_hint: i32,
}

impl Mesh3D {
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.vertices.is_empty()
    }

    #[must_use]
    pub fn vertex_count(&self) -> usize {
        self.vertices.len()
    }

    #[must_use]
    pub fn triangle_count(&self) -> usize {
        self.faces.len()
    }

    /// Add a quad as two triangles (winding: 0-1-2, 0-2-3). UV is set
    /// `[(0,0), (1,0), (1,1), (0,1)]`.
    pub fn add_quad(&mut self, p0: Vec3, p1: Vec3, p2: Vec3, p3: Vec3, normal: Vec3, color: Vec3) {
        #[allow(clippy::cast_possible_truncation)]
        let base = self.vertices.len() as u32;

        self.vertices.push(Vertex3D {
            position: p0,
            normal,
            color,
            uv: Vec2::new(0.0, 0.0),
            stress: 0.0,
        });
        self.vertices.push(Vertex3D {
            position: p1,
            normal,
            color,
            uv: Vec2::new(1.0, 0.0),
            stress: 0.0,
        });
        self.vertices.push(Vertex3D {
            position: p2,
            normal,
            color,
            uv: Vec2::new(1.0, 1.0),
            stress: 0.0,
        });
        self.vertices.push(Vertex3D {
            position: p3,
            normal,
            color,
            uv: Vec2::new(0.0, 1.0),
            stress: 0.0,
        });

        self.faces.push(Triangle::new(base, base + 1, base + 2));
        self.faces.push(Triangle::new(base, base + 2, base + 3));
    }

    /// Add a single triangle. UV is set `[(0,0), (1,0), (0.5,1)]`.
    pub fn add_triangle(&mut self, p0: Vec3, p1: Vec3, p2: Vec3, normal: Vec3, color: Vec3) {
        #[allow(clippy::cast_possible_truncation)]
        let base = self.vertices.len() as u32;

        self.vertices.push(Vertex3D {
            position: p0,
            normal,
            color,
            uv: Vec2::new(0.0, 0.0),
            stress: 0.0,
        });
        self.vertices.push(Vertex3D {
            position: p1,
            normal,
            color,
            uv: Vec2::new(1.0, 0.0),
            stress: 0.0,
        });
        self.vertices.push(Vertex3D {
            position: p2,
            normal,
            color,
            uv: Vec2::new(0.5, 1.0),
            stress: 0.0,
        });

        self.faces.push(Triangle::new(base, base + 1, base + 2));
    }

    /// Merge `other` into this mesh, offsetting face indices.
    pub fn merge(&mut self, other: &Mesh3D) {
        #[allow(clippy::cast_possible_truncation)]
        let offset = self.vertices.len() as u32;
        self.vertices.extend(other.vertices.iter().copied());
        self.faces.extend(other.faces.iter().map(|f| Triangle {
            v0: f.v0 + offset,
            v1: f.v1 + offset,
            v2: f.v2 + offset,
        }));
    }
}

// ---------------------------------------------------------------------------
// 2D Geometry Types
// ---------------------------------------------------------------------------

/// 2D line segment.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Line2D {
    #[serde(with = "vec2_array")]
    pub start: Point2D,
    #[serde(with = "vec2_array")]
    pub end: Point2D,
    #[serde(default = "default_layer")]
    pub layer: String,
    /// `"continuous"`, `"dashed"`, `"hidden"`.
    #[serde(default = "default_line_type")]
    pub line_type: String,
    #[serde(default = "default_line_weight")]
    pub line_weight: f32,
}

fn default_layer() -> String {
    "default".to_string()
}
fn default_line_type() -> String {
    "continuous".to_string()
}
fn default_line_weight() -> f32 {
    0.25
}
fn default_text_layer() -> String {
    "annotation".to_string()
}
fn default_text_anchor() -> String {
    "middle".to_string()
}
fn default_text_alignment() -> String {
    "center".to_string()
}

impl Default for Line2D {
    fn default() -> Self {
        Self {
            start: Point2D::ZERO,
            end: Point2D::ZERO,
            layer: default_layer(),
            line_type: default_line_type(),
            line_weight: default_line_weight(),
        }
    }
}

/// 2D polygon (closed by default).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Polygon2D {
    #[serde(default)]
    pub points: Vec<Point2D>,
    #[serde(default = "yes")]
    pub closed: bool,
    #[serde(default = "default_layer")]
    pub layer: String,
    /// Hatch / fill pattern name; empty = no fill.
    #[serde(default)]
    pub fill_pattern: String,
    /// RGBA.
    #[serde(default = "default_fill_color")]
    pub fill_color: [f32; 4],
}

fn yes() -> bool {
    true
}
fn default_fill_color() -> [f32; 4] {
    [1.0, 1.0, 1.0, 1.0]
}

impl Default for Polygon2D {
    fn default() -> Self {
        Self {
            points: Vec::new(),
            closed: true,
            layer: default_layer(),
            fill_pattern: String::new(),
            fill_color: default_fill_color(),
        }
    }
}

/// 2D arc.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Arc2D {
    #[serde(with = "vec2_array")]
    pub center: Point2D,
    pub radius: f32,
    /// Start angle in radians.
    #[serde(default)]
    pub start_angle: f32,
    /// End angle in radians. Default = 2π (full circle).
    #[serde(default = "two_pi")]
    pub end_angle: f32,
    #[serde(default = "default_layer")]
    pub layer: String,
}

fn two_pi() -> f32 {
    std::f32::consts::TAU
}

impl Default for Arc2D {
    fn default() -> Self {
        Self {
            center: Point2D::ZERO,
            radius: 0.0,
            start_angle: 0.0,
            end_angle: two_pi(),
            layer: default_layer(),
        }
    }
}

/// 2D text annotation.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Text2D {
    #[serde(with = "vec2_array")]
    pub position: Point2D,
    pub text: String,
    /// Text height in mm.
    #[serde(default = "default_text_height")]
    pub height: f32,
    /// Alias of `height` for downstream consumers that already used this name.
    #[serde(default = "default_text_height")]
    pub font_size: f32,
    /// Rotation in radians.
    #[serde(default)]
    pub rotation: f32,
    #[serde(default = "default_text_layer")]
    pub layer: String,
    /// `"left"`, `"middle"`, `"right"`.
    #[serde(default = "default_text_anchor")]
    pub anchor: String,
    /// `"left"`, `"center"`, `"right"`.
    #[serde(default = "default_text_alignment")]
    pub alignment: String,
}

fn default_text_height() -> f32 {
    100.0
}

impl Default for Text2D {
    fn default() -> Self {
        Self {
            position: Point2D::ZERO,
            text: String::new(),
            height: default_text_height(),
            font_size: default_text_height(),
            rotation: 0.0,
            layer: default_text_layer(),
            anchor: default_text_anchor(),
            alignment: default_text_alignment(),
        }
    }
}

/// Collection of 2D geometry — lines, polygons, arcs, text.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct Geometry2D {
    #[serde(default)]
    pub lines: Vec<Line2D>,
    #[serde(default)]
    pub polygons: Vec<Polygon2D>,
    #[serde(default)]
    pub arcs: Vec<Arc2D>,
    #[serde(default)]
    pub texts: Vec<Text2D>,

    #[serde(default)]
    pub element_id: String,
    #[serde(default)]
    pub element_type: String,
    #[serde(default)]
    pub lod_hint: i32,
}

impl Geometry2D {
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.lines.is_empty()
            && self.polygons.is_empty()
            && self.arcs.is_empty()
            && self.texts.is_empty()
    }

    /// Merge `other` into this collection.
    pub fn merge(&mut self, other: &Geometry2D) {
        self.lines.extend(other.lines.iter().cloned());
        self.polygons.extend(other.polygons.iter().cloned());
        self.arcs.extend(other.arcs.iter().cloned());
        self.texts.extend(other.texts.iter().cloned());
    }
}

// ---------------------------------------------------------------------------
// Per-element geometry results
// ---------------------------------------------------------------------------

/// Cutout rectangle for a door or window opening in a wall.
#[derive(Debug, Clone, PartialEq, Default, Serialize, Deserialize)]
pub struct OpeningCutout {
    /// Distance along the wall from start.
    pub start_offset: f32,
    /// Height from the floor (0 for doors).
    pub bottom_height: f32,
    pub width: f32,
    pub height: f32,
    /// `"door"` or `"window"`.
    pub opening_type: String,
    /// Index into the doors/windows array on the owning `SchemaDocument`.
    pub opening_index: i32,
}

/// Generated geometry for a single wall.
#[derive(Debug, Clone, PartialEq, Default, Serialize, Deserialize)]
pub struct WallGeometry {
    #[serde(default)]
    pub mesh_3d: Mesh3D,
    /// Floor plan representation.
    #[serde(default)]
    pub plan_view: Geometry2D,
    /// Section cut representation.
    #[serde(default)]
    pub section_view: Geometry2D,
    #[serde(default)]
    pub cutouts: Vec<OpeningCutout>,

    #[serde(default)]
    pub wall_id: String,
    #[serde(default = "neg_one")]
    pub wall_index: i32,
}

fn neg_one() -> i32 {
    -1
}

/// Generated geometry for a single floor.
#[derive(Debug, Clone, PartialEq, Default, Serialize, Deserialize)]
pub struct FloorGeometry {
    #[serde(default)]
    pub mesh_3d: Mesh3D,
    #[serde(default)]
    pub plan_view: Geometry2D,
    #[serde(default)]
    pub floor_id: String,
    /// Optional — room this floor belongs to.
    #[serde(default)]
    pub room_id: String,
    #[serde(default = "neg_one")]
    pub floor_index: i32,
}

/// Generated geometry for a single roof.
#[derive(Debug, Clone, PartialEq, Default, Serialize, Deserialize)]
pub struct RoofGeometry {
    #[serde(default)]
    pub mesh_3d: Mesh3D,
    /// Roof plan with ridge / hip lines.
    #[serde(default)]
    pub plan_view: Geometry2D,
    #[serde(default)]
    pub ridge_lines: Vec<Line2D>,
    #[serde(default)]
    pub hip_lines: Vec<Line2D>,
    #[serde(default)]
    pub eave_lines: Vec<Line2D>,
    #[serde(default)]
    pub rake_lines: Vec<Line2D>,
    #[serde(default)]
    pub roof_id: String,
    #[serde(default = "neg_one")]
    pub roof_index: i32,
}

/// Generated geometry for a door.
#[derive(Debug, Clone, PartialEq, Default, Serialize, Deserialize)]
pub struct DoorGeometry {
    /// Combined 3D mesh (frame + panel).
    #[serde(default)]
    pub mesh_3d: Mesh3D,
    #[serde(default)]
    pub frame_mesh: Mesh3D,
    #[serde(default)]
    pub panel_mesh: Mesh3D,
    /// Plan symbol — door swing arc, etc.
    #[serde(default)]
    pub plan_symbol: Geometry2D,
    /// Cutout info for the parent wall.
    #[serde(default)]
    pub cutout: OpeningCutout,
    #[serde(default)]
    pub door_id: String,
    /// `"swing"`, `"pocket"`, …
    #[serde(default)]
    pub door_type: String,
    #[serde(default = "neg_one")]
    pub door_index: i32,
}

/// Generated geometry for a window.
#[derive(Debug, Clone, PartialEq, Default, Serialize, Deserialize)]
pub struct WindowGeometry {
    #[serde(default)]
    pub mesh_3d: Mesh3D,
    #[serde(default)]
    pub frame_mesh: Mesh3D,
    #[serde(default)]
    pub glass_mesh: Mesh3D,
    #[serde(default)]
    pub plan_symbol: Geometry2D,
    #[serde(default)]
    pub cutout: OpeningCutout,
    #[serde(default)]
    pub window_id: String,
    /// `"casement"`, `"double_hung"`, …
    #[serde(default)]
    pub window_type: String,
    #[serde(default = "neg_one")]
    pub window_index: i32,
}

/// Room boundary result. (The C++ aliases `boundary`/`polygon` and
/// `center`/`centroid`; we keep only the canonical names here.)
#[derive(Debug, Clone, PartialEq, Default, Serialize, Deserialize)]
pub struct RoomBoundary {
    #[serde(default)]
    pub boundary: Polygon2D,
    #[serde(default, with = "vec2_array")]
    pub center: Point2D,
    /// Computed area in mm².
    #[serde(default)]
    pub area: f32,
    /// Room name (display label).
    #[serde(default)]
    pub label: String,
    /// Room type — `"living"`, `"bedroom"`, …
    #[serde(default)]
    pub room_type: String,
    #[serde(default)]
    pub room_id: String,
}

// ---------------------------------------------------------------------------
// Complete building geometry
// ---------------------------------------------------------------------------

/// All computed geometry for a building.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct BuildingGeometry {
    #[serde(default)]
    pub building_id: String,

    #[serde(default)]
    pub walls: Vec<WallGeometry>,
    #[serde(default)]
    pub floors: Vec<FloorGeometry>,
    #[serde(default)]
    pub roofs: Vec<RoofGeometry>,
    #[serde(default)]
    pub doors: Vec<DoorGeometry>,
    #[serde(default)]
    pub windows: Vec<WindowGeometry>,
    #[serde(default)]
    pub rooms: Vec<RoomBoundary>,

    #[serde(default, with = "vec3_array")]
    pub bounds_min: Vec3,
    #[serde(default, with = "vec3_array")]
    pub bounds_max: Vec3,
}

impl BuildingGeometry {
    /// Combined 3D mesh for every wall in the building.
    #[must_use]
    pub fn all_wall_meshes(&self) -> Mesh3D {
        let mut combined = Mesh3D::default();
        for w in &self.walls {
            combined.merge(&w.mesh_3d);
        }
        combined
    }

    /// Combined floor-plan geometry: every wall plan_view, every door
    /// plan_symbol, every window plan_symbol.
    #[must_use]
    pub fn floor_plan(&self) -> Geometry2D {
        let mut combined = Geometry2D::default();
        for w in &self.walls {
            combined.merge(&w.plan_view);
        }
        for d in &self.doors {
            combined.merge(&d.plan_symbol);
        }
        for win in &self.windows {
            combined.merge(&win.plan_symbol);
        }
        combined
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_mesh_is_empty() {
        assert!(Mesh3D::default().is_empty());
    }

    #[test]
    fn add_quad_produces_4_verts_and_2_tris() {
        let mut m = Mesh3D::default();
        m.add_quad(
            Vec3::new(0.0, 0.0, 0.0),
            Vec3::new(1.0, 0.0, 0.0),
            Vec3::new(1.0, 0.0, 1.0),
            Vec3::new(0.0, 0.0, 1.0),
            Vec3::Y,
            Vec3::splat(0.5),
        );
        assert_eq!(m.vertex_count(), 4);
        assert_eq!(m.triangle_count(), 2);
        assert_eq!(m.faces[0], Triangle::new(0, 1, 2));
        assert_eq!(m.faces[1], Triangle::new(0, 2, 3));
    }

    #[test]
    fn merge_offsets_face_indices() {
        let mut a = Mesh3D::default();
        a.add_triangle(Vec3::ZERO, Vec3::X, Vec3::Y, Vec3::Z, Vec3::ONE);

        let mut b = Mesh3D::default();
        b.add_triangle(Vec3::ZERO, Vec3::X, Vec3::Y, Vec3::Z, Vec3::ONE);

        a.merge(&b);
        assert_eq!(a.vertex_count(), 6);
        assert_eq!(a.triangle_count(), 2);
        // Second triangle's indices should be offset by 3.
        assert_eq!(a.faces[1], Triangle::new(3, 4, 5));
    }

    #[test]
    fn building_geometry_aggregates_wall_meshes() {
        let mut wall = WallGeometry::default();
        wall.mesh_3d
            .add_triangle(Vec3::ZERO, Vec3::X, Vec3::Y, Vec3::Z, Vec3::ONE);

        let mut bg = BuildingGeometry::default();
        bg.walls.push(wall.clone());
        bg.walls.push(wall);

        let combined = bg.all_wall_meshes();
        assert_eq!(combined.vertex_count(), 6);
        assert_eq!(combined.triangle_count(), 2);
    }

    #[test]
    fn empty_geometry_2d_is_empty() {
        assert!(Geometry2D::default().is_empty());
    }
}
