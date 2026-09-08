//! Schema element types — port of `Shared/ArchGeometry/include/archgeometry/schema_types.hpp`.
//!
//! These types mirror the JSON wire format produced by the Python QBD
//! generator. Field names use `snake_case` to match the JSON keys directly,
//! so most types need no `#[serde(rename)]`.
//!
//! Per port plan §8: the C++ has TWO JSON paths (`QBDInterface::loadFromJSON`
//! and `QBDInterface::parseWithArchGeometry`). The Rust port collapses to
//! this one — these types ARE the wire format.

use crate::arch::wire::{map_or_empty_array, vec2_xy_object, vec3_array, vec3_array_vec};
use glam::{Vec2, Vec3};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

// ---------------------------------------------------------------------------
// Wall types (schema-side; distinct from `crate::domain::WallType`).
// ---------------------------------------------------------------------------

/// Wall layer (schema-side). The schema stores `function` as a free-form
/// string and `color` as RGBA — both differ from `crate::domain::WallLayer`
/// (which uses the `LayerFunction` enum and RGB only).
#[derive(Debug, Clone, PartialEq, Default, Serialize, Deserialize)]
pub struct WallLayer {
    pub name: String,
    pub material: String,
    #[serde(default)]
    pub thickness: f32,
    /// Layer function as a free-form string: `"structure"`, `"insulation"`,
    /// `"finish"`, … See `crate::domain::LayerFunction` for the canonical set.
    #[serde(default)]
    pub function: String,
    /// RGBA. Default `[0.9, 0.9, 0.9, 1.0]`.
    #[serde(default = "default_layer_color")]
    pub color: [f32; 4],
    #[serde(default)]
    pub r_value: f32,
}

fn default_layer_color() -> [f32; 4] {
    [0.9, 0.9, 0.9, 1.0]
}

/// Wall type — an assembly recipe (schema-side).
#[derive(Debug, Clone, PartialEq, Default, Serialize, Deserialize)]
pub struct WallType {
    pub id: String,
    pub name: String,
    #[serde(default)]
    pub layers: Vec<WallLayer>,
}

impl WallType {
    /// Sum of layer thicknesses.
    #[must_use]
    pub fn total_thickness(&self) -> f32 {
        self.layers.iter().map(|l| l.thickness).sum()
    }

    /// Sum of layer R-values.
    #[must_use]
    pub fn total_r_value(&self) -> f32 {
        self.layers.iter().map(|l| l.r_value).sum()
    }
}

// ---------------------------------------------------------------------------
// Schema elements.
// ---------------------------------------------------------------------------

/// Wall element from the schema. Centerline-based.
#[derive(Debug, Clone, PartialEq, Default, Serialize, Deserialize)]
pub struct SchemaWall {
    #[serde(with = "vec3_array")]
    pub start: Vec3,
    #[serde(with = "vec3_array")]
    pub end: Vec3,
    #[serde(default = "default_wall_height")]
    pub height: f32,
    #[serde(default)]
    pub wall_type: String,
    #[serde(default)]
    pub category: String,
    #[serde(default)]
    pub level_name: String,
    /// Adjacent room IDs (two sides). Defaults to `["", ""]`.
    #[serde(default)]
    pub rooms: [String; 2],

    #[serde(default)]
    pub is_pinned: bool,
    #[serde(default)]
    pub locked_properties: Vec<String>,

    /// Renovation lifecycle: `true` for an existing (as-built) wall captured
    /// from a survey, `false` (default) for new construction. Kept separate
    /// from `category` (which is the construction type). Part 11 work reads
    /// this to split existing-vs-new; Part 9 new builds leave it `false`.
    #[serde(default)]
    pub existing: bool,
}

fn default_wall_height() -> f32 {
    2700.0
}

impl SchemaWall {
    /// True if this wall is existing (as-built). Honours the legacy
    /// `category == "as_built"` convention as well as the explicit flag.
    #[must_use]
    pub fn is_existing(&self) -> bool {
        self.existing || self.category == "as_built"
    }

    /// Wall length in the XZ plane (ignores Y).
    #[must_use]
    pub fn length(&self) -> f32 {
        let dx = self.end.x - self.start.x;
        let dz = self.end.z - self.start.z;
        (dx * dx + dz * dz).sqrt()
    }

    /// Unit direction in the XZ plane.
    #[must_use]
    pub fn direction(&self) -> Vec2 {
        let dx = self.end.x - self.start.x;
        let dz = self.end.z - self.start.z;
        let dir = Vec2::new(dx, dz);
        let len = dir.length();
        if len > 0.0001 { dir / len } else { Vec2::ZERO }
    }
}

/// Floor element from the schema.
#[derive(Debug, Clone, PartialEq, Default, Serialize, Deserialize)]
pub struct SchemaFloor {
    #[serde(with = "vec3_array")]
    pub start: Vec3,
    #[serde(with = "vec3_array")]
    pub end: Vec3,
    #[serde(default = "default_floor_thickness")]
    pub thickness: f32,
    #[serde(default)]
    pub level_name: String,
    #[serde(default)]
    pub room: Option<String>,
    #[serde(default = "default_floor_material")]
    pub material: String,
}

fn default_floor_thickness() -> f32 {
    150.0
}

fn default_floor_material() -> String {
    "concrete".to_string()
}

impl SchemaFloor {
    #[must_use]
    pub fn width(&self) -> f32 {
        (self.end.x - self.start.x).abs()
    }

    #[must_use]
    pub fn depth(&self) -> f32 {
        (self.end.z - self.start.z).abs()
    }

    #[must_use]
    pub fn elevation(&self) -> f32 {
        self.start.y
    }

    #[must_use]
    pub fn area(&self) -> f32 {
        self.width() * self.depth()
    }
}

/// Door element from the schema.
#[derive(Debug, Clone, PartialEq, Default, Serialize, Deserialize)]
pub struct SchemaDoor {
    #[serde(default)]
    pub wall_index: i32,
    #[serde(default)]
    pub offset: f32,
    #[serde(default = "default_door_width")]
    pub width: f32,
    #[serde(default = "default_door_height")]
    pub height: f32,
    #[serde(default = "default_door_type", rename = "type")]
    pub door_type: String,
    #[serde(default = "default_door_swing")]
    pub swing: String,
    #[serde(default)]
    pub room1: String,
    #[serde(default)]
    pub room2: String,

    #[serde(default)]
    pub is_pinned: bool,
    #[serde(default)]
    pub locked_properties: Vec<String>,

    /// Renovation lifecycle: `true` for an existing (as-built) door,
    /// `false` (default) for a new one. See [`SchemaWall::existing`].
    #[serde(default)]
    pub existing: bool,
}

impl SchemaDoor {
    /// True if this door is existing (as-built).
    #[must_use]
    pub fn is_existing(&self) -> bool {
        self.existing
    }
}

fn default_door_width() -> f32 {
    914.0
}
fn default_door_height() -> f32 {
    2134.0
}
fn default_door_type() -> String {
    "swing".to_string()
}
fn default_door_swing() -> String {
    "left_in".to_string()
}

/// Window element from the schema.
#[derive(Debug, Clone, PartialEq, Default, Serialize, Deserialize)]
pub struct SchemaWindow {
    #[serde(default)]
    pub wall_index: i32,
    #[serde(default)]
    pub offset: f32,
    #[serde(default = "default_window_width")]
    pub width: f32,
    #[serde(default = "default_window_height")]
    pub height: f32,
    #[serde(default = "default_window_sill")]
    pub sill_height: f32,
    #[serde(default = "default_window_type", rename = "type")]
    pub window_type: String,
    #[serde(default)]
    pub room: String,

    #[serde(default)]
    pub is_pinned: bool,
    #[serde(default)]
    pub locked_properties: Vec<String>,

    /// Renovation lifecycle: `true` for an existing (as-built) window,
    /// `false` (default) for a new one. See [`SchemaWall::existing`].
    #[serde(default)]
    pub existing: bool,
}

impl SchemaWindow {
    /// True if this window is existing (as-built).
    #[must_use]
    pub fn is_existing(&self) -> bool {
        self.existing
    }
}

fn default_window_width() -> f32 {
    1200.0
}
fn default_window_height() -> f32 {
    1200.0
}
fn default_window_sill() -> f32 {
    900.0
}
fn default_window_type() -> String {
    "double_hung".to_string()
}

/// Roof ridge line.
#[derive(Debug, Clone, PartialEq, Default, Serialize, Deserialize)]
pub struct RoofRidge {
    #[serde(default)]
    pub id: String,
    #[serde(with = "vec3_array")]
    pub start_point: Vec3,
    #[serde(with = "vec3_array")]
    pub end_point: Vec3,
    #[serde(default)]
    pub height: f32,
}

/// Roof surface (one slope).
#[derive(Debug, Clone, PartialEq, Default, Serialize, Deserialize)]
pub struct RoofSurface {
    #[serde(default)]
    pub id: String,
    /// 3D polygon vertices.
    #[serde(default, with = "vec3_array_vec")]
    pub vertices: Vec<Vec3>,
    /// Pitch in degrees or rise:12 (consumer decides).
    #[serde(default)]
    pub pitch: f32,
    #[serde(default)]
    pub orientation: String,
}

/// Roof element from the schema.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SchemaRoof {
    #[serde(default)]
    pub id: String,
    #[serde(default = "default_roof_type", rename = "type")]
    pub roof_type: String,
    #[serde(default = "default_roof_pitch")]
    pub pitch: f32,
    #[serde(default = "default_roof_overhang")]
    pub overhang: f32,
    #[serde(default = "default_roof_material")]
    pub material: String,
    #[serde(default)]
    pub level_name: String,
    #[serde(default)]
    pub ridges: Vec<RoofRidge>,
    #[serde(default)]
    pub surfaces: Vec<RoofSurface>,
    #[serde(default)]
    pub dormers: Vec<String>,
    #[serde(default)]
    pub skylights: Vec<String>,
}

fn default_roof_type() -> String {
    "gable".to_string()
}
/// Document-level eave overhang default (16", matching the roof plan). Distinct
/// from `default_roof_overhang` below, which is the per-`SchemaRoof` default.
fn default_doc_roof_overhang() -> f32 {
    400.0
}
fn default_roof_pitch() -> f32 {
    6.0
}
fn default_roof_overhang() -> f32 {
    600.0
}
fn default_roof_material() -> String {
    "asphalt_shingle".to_string()
}

impl Default for SchemaRoof {
    fn default() -> Self {
        Self {
            id: String::new(),
            roof_type: default_roof_type(),
            pitch: default_roof_pitch(),
            overhang: default_roof_overhang(),
            material: default_roof_material(),
            level_name: String::new(),
            ridges: Vec::new(),
            surfaces: Vec::new(),
            dormers: Vec::new(),
            skylights: Vec::new(),
        }
    }
}

/// Room bounds in plan view. NOTE: `y` here is Z in 3D space (plan
/// convention from the C++).
#[derive(Debug, Clone, Copy, PartialEq, Default, Serialize, Deserialize)]
pub struct RoomBounds {
    #[serde(default)]
    pub x: f32,
    #[serde(default)]
    pub y: f32,
    #[serde(default)]
    pub width: f32,
    #[serde(default)]
    pub height: f32,
}

/// Room element from the schema.
#[derive(Debug, Clone, PartialEq, Default, Serialize, Deserialize)]
pub struct SchemaRoom {
    #[serde(default)]
    pub id: String,
    #[serde(default)]
    pub name: String,
    #[serde(default)]
    pub room_type: String,
    #[serde(default)]
    pub bounds: RoomBounds,
    #[serde(default)]
    pub area: f32,
    /// Wire format is `{"x": …, "y": …}` object (per the locked
    /// `qbd_output.schema.json`), unlike the wall/floor coordinate vectors
    /// which are JSON arrays.
    #[serde(default, with = "vec2_xy_object")]
    pub center: Vec2,
    #[serde(default)]
    pub zone: String,
    #[serde(default = "default_level_name")]
    pub level: String,

    #[serde(default)]
    pub is_pinned: bool,
    #[serde(default)]
    pub locked_properties: Vec<String>,
    /// Optional dwelling-unit id. Backward-compatible — absent in older JSON.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub unit: Option<String>,
}

fn default_level_name() -> String {
    "Level 1".to_string()
}

/// Stair element (OBC 9.8) — one per storey shaft, carrying the solved
/// riser/tread geometry and the plan footprint the drawing layer renders into
/// a stair symbol. A rules-engine annotation like detectors/electrical: the
/// solver computes it, the drawing reads it, and it round-trips through the
/// building JSON. Backward-compatible — absent in older JSON (the field
/// defaults to empty) and every member has a serde default.
#[derive(Debug, Clone, PartialEq, Default, Serialize, Deserialize)]
pub struct SchemaStair {
    #[serde(default)]
    pub id: String,
    #[serde(default = "default_level_name")]
    pub level_name: String,
    /// Bay minimum-corner in plan mm. `y` is Z in 3D (the plan convention
    /// shared with [`RoomBounds`]).
    #[serde(default)]
    pub x: f32,
    #[serde(default)]
    pub y: f32,
    /// Bay extent across the run direction (perpendicular), mm.
    #[serde(default)]
    pub width: f32,
    /// Bay extent along the run direction, mm.
    #[serde(default)]
    pub depth: f32,
    /// Ascent direction in plan: `"+y"` (north), `"-y"`, `"+x"`, `"-x"`.
    /// Empty is treated as `"+y"`.
    #[serde(default)]
    pub run_dir: String,
    #[serde(default)]
    pub num_risers: u32,
    #[serde(default)]
    pub num_treads: u32,
    /// Rise of each riser, mm.
    #[serde(default)]
    pub riser_height: f32,
    /// Tread run / going, mm.
    #[serde(default)]
    pub tread_run: f32,
    /// Clear width of the stair (one flight), mm.
    #[serde(default)]
    pub width_clear: f32,
    /// Floor-to-floor height this stair spans, mm.
    #[serde(default)]
    pub floor_to_floor: f32,
    /// Flight arrangement: `"straight"` or `"switchback"`. Empty is treated
    /// as `"straight"`.
    #[serde(default)]
    pub shape: String,
    /// `"up"` (climbs to the storey above) or `"down"`. Empty is `"up"`.
    #[serde(default)]
    pub going: String,
}

/// Level definition (a floor of the building).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SchemaLevel {
    pub name: String,
    #[serde(default)]
    pub elevation: f32,
    #[serde(default = "default_wall_height")]
    pub height: f32,
    /// Optional major occupancy for the floor. When present, Part 3 checks use
    /// this instead of inferring occupancy from room types.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub occupancy: Option<String>,
}

impl Default for SchemaLevel {
    fn default() -> Self {
        Self {
            name: String::new(),
            elevation: 0.0,
            height: default_wall_height(),
            occupancy: None,
        }
    }
}

/// QBD design parameters from the conversation.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct QBDAnswers {
    #[serde(default)]
    pub description: String,
    #[serde(default = "default_building_type")]
    pub building_type: String,
    #[serde(default = "default_mode")]
    pub mode: String,
    #[serde(default = "default_style")]
    pub style: String,
    #[serde(default = "default_stories")]
    pub stories: i32,
    #[serde(default)]
    pub garage: String,
    #[serde(default = "default_roof_type")]
    pub roof_type: String,
    #[serde(default = "default_roof_pitch")]
    pub roof_pitch: f32,
    #[serde(default = "default_roof_material")]
    pub roof_material: String,
    #[serde(default)]
    pub sqft: i32,
    #[serde(default)]
    pub bedrooms: i32,
    #[serde(default)]
    pub bathrooms: i32,
}

fn default_building_type() -> String {
    "residential".to_string()
}
fn default_mode() -> String {
    "part9".to_string()
}
fn default_style() -> String {
    "traditional".to_string()
}
fn default_stories() -> i32 {
    1
}

impl Default for QBDAnswers {
    fn default() -> Self {
        Self {
            description: String::new(),
            building_type: default_building_type(),
            mode: default_mode(),
            style: default_style(),
            stories: default_stories(),
            garage: String::new(),
            roof_type: default_roof_type(),
            roof_pitch: default_roof_pitch(),
            roof_material: default_roof_material(),
            sqft: 0,
            bedrooms: 0,
            bathrooms: 0,
        }
    }
}

// ---------------------------------------------------------------------------
// Schema document — top-level.
// ---------------------------------------------------------------------------

/// Summary statistics from the QBD generator.
#[derive(Debug, Clone, Copy, PartialEq, Default, Serialize, Deserialize)]
pub struct SchemaSummary {
    #[serde(default)]
    pub total_walls: i32,
    #[serde(default)]
    pub exterior_walls: i32,
    #[serde(default)]
    pub interior_walls: i32,
    #[serde(default)]
    pub doors_count: i32,
    #[serde(default)]
    pub windows_count: i32,
    #[serde(default)]
    pub rooms_placed: i32,
}

/// Top-level schema document parsed from a QBD JSON output.
///
/// Note: the JSON uses `walls_batch`/`floors_batch` (legacy naming), but
/// we expose the fields as `walls`/`floors` via `#[serde(rename)]` since
/// the rest of the code shouldn't care about the wire-level name.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct SchemaDocument {
    #[serde(default = "default_version")]
    pub version: String,
    #[serde(default)]
    pub building_id: String,

    /// Overall building width (X axis).
    #[serde(default)]
    pub width: f32,
    /// Overall building depth (Z axis).
    #[serde(default)]
    pub depth: f32,
    #[serde(default)]
    pub sqm: f32,
    #[serde(default)]
    pub sqft: f32,
    #[serde(default = "default_unit")]
    pub unit: String,

    /// JSON key: `walls_batch`.
    #[serde(default, rename = "walls_batch")]
    pub walls: Vec<SchemaWall>,
    /// JSON key: `floors_batch`.
    #[serde(default, rename = "floors_batch")]
    pub floors: Vec<SchemaFloor>,
    #[serde(default)]
    pub doors: Vec<SchemaDoor>,
    #[serde(default)]
    pub windows: Vec<SchemaWindow>,
    #[serde(default)]
    pub roofs: Vec<SchemaRoof>,
    /// Python writes `[]` when empty and `{"room_id": {...}}` when populated.
    #[serde(default, deserialize_with = "map_or_empty_array::deserialize")]
    pub rooms: HashMap<String, SchemaRoom>,
    #[serde(default)]
    pub levels: Vec<SchemaLevel>,
    /// Wire format is an array of `WallType`s (each has its own `id`);
    /// the C++ schema_parser turns this into a map keyed by `id` after
    /// parsing. We keep it as a Vec here and let the query API build the
    /// lookup map if needed.
    #[serde(default)]
    pub wall_types: Vec<WallType>,

    #[serde(default)]
    pub qbd_answers: QBDAnswers,
    #[serde(default)]
    pub summary: SchemaSummary,
    /// Life-safety alarms (smoke / CO) — rules-engine annotation pass.
    #[serde(default)]
    pub detectors: Vec<SchemaDetector>,
    /// Electrical devices (receptacles / lights) — rules-engine annotation.
    #[serde(default)]
    pub electrical: Vec<SchemaElectrical>,
    /// Header (lintel) callouts over openings — rules-engine annotation.
    #[serde(default)]
    pub headers: Vec<SchemaHeader>,
    /// Stairs (OBC 9.8) — one per storey shaft. Rules-engine annotation.
    #[serde(default)]
    pub stairs: Vec<SchemaStair>,
    /// Lot + zoning for the site plan.
    #[serde(default)]
    pub site: SchemaSite,
    /// Roof type for generated roof geometry: `"gable"` (default) or `"hip"`.
    #[serde(default)]
    pub roof_type: String,
    /// Eave/rake overhang projected beyond the wall face (mm). Adjustable;
    /// ~400 mm (16") is a typical residential eave. Drives the roof-plan eave
    /// outline and the elevation/section roof projection. 0 = roof flush with
    /// the wall. Absent in older JSON → defaults to 400 mm.
    #[serde(default = "default_doc_roof_overhang")]
    pub roof_overhang_mm: f32,
    /// Irregular building footprint as CCW `[x, z]` mm vertices. Empty → the
    /// rectangular `width × depth` is used and the roof generator produces a
    /// gable/hip over that rectangle; non-empty triggers the straight-skeleton
    /// roof for rectilinear (L/T/U/cross) footprints.
    #[serde(default)]
    pub footprint_polygon_mm: Vec<[f32; 2]>,
}

/// Lot, zone, and street for the site-plan drawing.
#[derive(Debug, Clone, Default, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct SchemaSite {
    #[serde(default)]
    pub lot_width_ft: f32,
    #[serde(default)]
    pub lot_depth_ft: f32,
    #[serde(default)]
    pub zone: String,
    #[serde(default)]
    pub street: String,
    /// Grade spot elevations (m) at the four lot corners, SW/SE/NE/NW order,
    /// sampled from LiDAR terrain. Empty if no terrain wired.
    #[serde(default)]
    pub grade_corners_m: Vec<f32>,
    /// Parcel outline as local `[x, y]` (ft) vertices, from the map boundary
    /// the user draws (CAD's `vertices_ft`). Empty → fall back to a rectangle.
    #[serde(default)]
    pub lot_polygon_ft: Vec<[f32; 2]>,
    /// LiDAR-derived contour lines in lot-local feet, at a fixed interval (see
    /// `contour_interval_m`). Empty → no contours drawn.
    #[serde(default)]
    pub contours_ft: Vec<SchemaContour>,
    /// Elevation step between contour lines, in metres. Default 0.5.
    #[serde(default)]
    pub contour_interval_m: f32,
    /// OSM-sourced street network around the parcel, projected into
    /// lot-local feet. Empty → no streets drawn.
    #[serde(default)]
    pub streets_ft: Vec<SchemaStreet>,
}

/// One OSM way in lot-local feet, plus its display tags.
#[derive(Debug, Clone, Default, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct SchemaStreet {
    #[serde(default)]
    pub name: String,
    /// `arterial` / `connector` / `local` / `path`. Empty defaults to local.
    #[serde(default)]
    pub kind: String,
    /// Polyline `[[x_ft, y_ft], …]` in the same frame as `lot_polygon_ft`.
    #[serde(default)]
    pub points_ft: Vec<[f32; 2]>,
}

/// One contour line at a given elevation, expressed as a list of stitched
/// polylines in lot-local feet. Each polyline is a `Vec<[x, y]>`; closed
/// loops repeat the first point at the end. A single contour level can have
/// multiple disjoint polylines (e.g. when the iso-contour crosses the
/// parcel boundary in several places).
#[derive(Debug, Clone, Default, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct SchemaContour {
    #[serde(default)]
    pub elevation_m: f32,
    /// One entry per disjoint chain; each is an ordered list of `[x, y]` ft.
    #[serde(default)]
    pub polylines_ft: Vec<Vec<[f32; 2]>>,
}

/// A header/lintel callout over a door or window opening. `size` is the OBC
/// member (e.g. `"2-2x10"`); position in mm at the opening centre.
#[derive(Debug, Clone, Default, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct SchemaHeader {
    #[serde(default)]
    pub size: String,
    #[serde(default)]
    pub x: f32,
    #[serde(default)]
    pub y: f32,
    #[serde(default)]
    pub level_name: String,
    #[serde(default)]
    pub opening: String,
    #[serde(default)]
    pub width: f32,
    #[serde(default)]
    pub needs_review: bool,
}

/// A placed electrical device. `kind` is `"receptacle"`, `"gfci"` or
/// `"light"`; position in mm.
#[derive(Debug, Clone, Default, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct SchemaElectrical {
    #[serde(default, rename = "type")]
    pub kind: String,
    #[serde(default)]
    pub x: f32,
    #[serde(default)]
    pub y: f32,
    #[serde(default)]
    pub level_name: String,
    #[serde(default)]
    pub room: String,
}

/// A placed life-safety alarm (smoke or CO). Position is the room/ceiling
/// point in mm; `kind` is `"smoke"` or `"co"`.
#[derive(Debug, Clone, Default, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct SchemaDetector {
    #[serde(default, rename = "type")]
    pub kind: String,
    #[serde(default)]
    pub x: f32,
    #[serde(default)]
    pub y: f32,
    #[serde(default)]
    pub level_name: String,
    #[serde(default)]
    pub room: String,
}

fn default_version() -> String {
    "1.0.0".to_string()
}
fn default_unit() -> String {
    "mm".to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn schema_wall_round_trips_through_json() {
        let w = SchemaWall {
            start: Vec3::new(0.0, 0.0, 0.0),
            end: Vec3::new(5000.0, 0.0, 0.0),
            height: 2700.0,
            wall_type: "exterior_2x6".into(),
            category: "exterior".into(),
            ..Default::default()
        };
        let json = serde_json::to_string(&w).unwrap();
        assert!(json.contains(r#""start":[0.0,0.0,0.0]"#));
        assert!(json.contains(r#""end":[5000.0,0.0,0.0]"#));
        let back: SchemaWall = serde_json::from_str(&json).unwrap();
        assert_eq!(back.wall_type, w.wall_type);
        assert_eq!(back.start, w.start);
    }

    #[test]
    fn is_existing_honours_flag_and_legacy_category() {
        // New construction by default.
        let mut w = SchemaWall::default();
        assert!(!w.is_existing());
        // Explicit renovation flag.
        w.existing = true;
        assert!(w.is_existing());
        // Legacy convention: category == "as_built" with no flag.
        let legacy = SchemaWall {
            category: "as_built".into(),
            ..Default::default()
        };
        assert!(legacy.is_existing());
        // Doors and windows: flag only.
        assert!(!SchemaDoor::default().is_existing());
        assert!(SchemaDoor { existing: true, ..Default::default() }.is_existing());
        assert!(!SchemaWindow::default().is_existing());
        assert!(SchemaWindow { existing: true, ..Default::default() }.is_existing());
    }

    #[test]
    fn existing_flag_defaults_false_and_round_trips() {
        let json = r#"{"start":[0,0,0],"end":[1000,0,0]}"#;
        let w: SchemaWall = serde_json::from_str(json).unwrap();
        assert!(!w.existing);
        let w2 = SchemaWall { existing: true, ..w };
        let back: SchemaWall = serde_json::from_str(&serde_json::to_string(&w2).unwrap()).unwrap();
        assert!(back.existing);
    }

    #[test]
    fn schema_wall_parses_minimal_input() {
        // Only the required fields supplied — defaults fill the rest.
        let json = r#"{"start":[0,0,0],"end":[1000,0,0]}"#;
        let w: SchemaWall = serde_json::from_str(json).unwrap();
        assert_eq!(w.start, Vec3::ZERO);
        assert_eq!(w.height, 2700.0); // default
        assert_eq!(w.wall_type, ""); // default
    }

    #[test]
    fn schema_wall_length_xz_ignores_y() {
        // Wall on second floor (Y=3048) should still have correct XZ length.
        let w = SchemaWall {
            start: Vec3::new(0.0, 3048.0, 0.0),
            end: Vec3::new(3000.0, 3048.0, 4000.0),
            ..Default::default()
        };
        assert_eq!(w.length(), 5000.0);
    }

    #[test]
    fn roof_overhang_defaults_to_400_and_round_trips() {
        // Absent in older JSON → the 16" (400 mm) document default.
        let doc: SchemaDocument = serde_json::from_str(r#"{"width":9000,"depth":7000}"#).unwrap();
        assert_eq!(doc.roof_overhang_mm, 400.0);
        // An explicit value (including 0 for a flush roof) round-trips verbatim.
        for set in [0.0_f32, 600.0] {
            let d = SchemaDocument { roof_overhang_mm: set, ..Default::default() };
            let back: SchemaDocument =
                serde_json::from_str(&serde_json::to_string(&d).unwrap()).unwrap();
            assert_eq!(back.roof_overhang_mm, set);
        }
    }

    #[test]
    fn stairs_default_empty_and_round_trip() {
        // Absent in older JSON → empty, no error.
        let doc: SchemaDocument = serde_json::from_str(r#"{"width":9000,"depth":7000}"#).unwrap();
        assert!(doc.stairs.is_empty());

        // A populated stair round-trips verbatim.
        let stair = SchemaStair {
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
        };
        let d = SchemaDocument { stairs: vec![stair.clone()], ..Default::default() };
        let back: SchemaDocument =
            serde_json::from_str(&serde_json::to_string(&d).unwrap()).unwrap();
        assert_eq!(back.stairs.len(), 1);
        assert_eq!(back.stairs[0], stair);
    }

    #[test]
    fn schema_document_parses_walls_batch() {
        let json = r#"{
            "width": 9144,
            "depth": 12192,
            "walls_batch": [
                {"start":[0,0,0],"end":[9144,0,0],"height":3048,"wall_type":"brick","category":"exterior"}
            ]
        }"#;
        let doc: SchemaDocument = serde_json::from_str(json).unwrap();
        assert_eq!(doc.width, 9144.0);
        assert_eq!(doc.walls.len(), 1);
        assert_eq!(doc.walls[0].category, "exterior");
    }

    #[test]
    fn floor_area_uses_width_times_depth() {
        let f = SchemaFloor {
            start: Vec3::new(0.0, 0.0, 0.0),
            end: Vec3::new(5000.0, 0.0, 4000.0),
            ..Default::default()
        };
        assert_eq!(f.area(), 20_000_000.0);
    }
}
