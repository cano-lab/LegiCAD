//! SAH-based BVH builder for GPU path tracing.
//!
//! Port of `ArchEngine_kernel/{include/bvh.hpp, src/bvh.cpp}`.
//!
//! The output is GPU-layout exact: [`GpuBvhNode`] is 32 bytes and
//! [`GpuTriangle`] 48 bytes, with the same bit-packed `w` channels as the
//! C++ (child indices / leaf markers stored as float bits). The path-tracer
//! shader contract is unchanged.
//!
//! Deliberate divergences from the C++:
//! - The build tree uses an arena (`Vec<BuildNode>`) instead of raw `new`/
//!   `delete`, and tree depth is computed during flattening rather than via
//!   the C++'s function-`static` depth counter (not thread-safe).
//! - The material map is an explicit [`MaterialTable`] passed in, not
//!   lazily-loaded globals.
//! - `buildSceneBVH` returns a [`SceneBvh`] struct instead of out-params.

use crate::domain::{ElementType, StructuralElement, TerrainMesh};
use glam::{Vec3, Vec4};

// ============================================================================
// AABB
// ============================================================================

/// Axis-aligned bounding box. Default construction is *invalid* (min > max)
/// so `expand` builds up from nothing — same semantics as the C++.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Aabb {
    pub min: Vec3,
    pub max: Vec3,
}

impl Default for Aabb {
    fn default() -> Self {
        Self { min: Vec3::splat(f32::MAX), max: Vec3::splat(f32::MIN) }
    }
}

impl Aabb {
    #[must_use]
    pub fn new(min: Vec3, max: Vec3) -> Self {
        Self { min, max }
    }

    /// Expand to include a point.
    pub fn expand_point(&mut self, point: Vec3) {
        self.min = self.min.min(point);
        self.max = self.max.max(point);
    }

    /// Expand to include another box.
    pub fn expand(&mut self, other: &Aabb) {
        self.min = self.min.min(other.min);
        self.max = self.max.max(other.max);
    }

    /// Surface area (for SAH).
    #[must_use]
    pub fn surface_area(&self) -> f32 {
        let d = self.max - self.min;
        2.0 * (d.x * d.y + d.y * d.z + d.z * d.x)
    }

    #[must_use]
    pub fn centroid(&self) -> Vec3 {
        (self.min + self.max) * 0.5
    }

    #[must_use]
    pub fn diagonal(&self) -> Vec3 {
        self.max - self.min
    }

    /// Longest axis: 0 = X, 1 = Y, 2 = Z.
    #[must_use]
    pub fn longest_axis(&self) -> usize {
        let d = self.diagonal();
        if d.x > d.y && d.x > d.z {
            0
        } else if d.y > d.z {
            1
        } else {
            2
        }
    }

    /// Valid iff min <= max on every axis.
    #[must_use]
    pub fn is_valid(&self) -> bool {
        self.min.x <= self.max.x && self.min.y <= self.max.y && self.min.z <= self.max.z
    }
}

// ============================================================================
// GPU layouts
// ============================================================================

/// GPU-friendly BVH node (32 bytes, 16-aligned).
///
/// Internal nodes: `bounds_min.w` = left child index (as float bits),
/// `bounds_max.w` = right child index. Leaf nodes: `bounds_min.w` =
/// `-(prim_offset + 1)` (negative marks a leaf), `bounds_max.w` = prim count.
#[derive(Debug, Clone, Copy, PartialEq)]
#[repr(C, align(16))]
pub struct GpuBvhNode {
    pub bounds_min: Vec4,
    pub bounds_max: Vec4,
}

impl GpuBvhNode {
    pub fn set_internal_node(&mut self, bounds: &Aabb, left_child: u32, right_child: u32) {
        self.bounds_min = bounds.min.extend(0.0);
        self.bounds_max = bounds.max.extend(0.0);
        self.bounds_min.w = f32::from_bits(left_child);
        self.bounds_max.w = f32::from_bits(right_child);
    }

    pub fn set_leaf_node(&mut self, bounds: &Aabb, prim_offset: u32, prim_count: u32) {
        self.bounds_min = bounds.min.extend(0.0);
        self.bounds_max = bounds.max.extend(0.0);
        let neg_offset = -((prim_offset + 1) as i32);
        self.bounds_min.w = f32::from_bits(neg_offset as u32);
        self.bounds_max.w = f32::from_bits(prim_count);
    }

    #[must_use]
    pub fn is_leaf(&self) -> bool {
        (self.bounds_min.w.to_bits() as i32) < 0
    }

    #[must_use]
    pub fn left_child(&self) -> u32 {
        self.bounds_min.w.to_bits()
    }

    #[must_use]
    pub fn right_child(&self) -> u32 {
        self.bounds_max.w.to_bits()
    }

    #[must_use]
    pub fn prim_offset(&self) -> u32 {
        (-(self.bounds_min.w.to_bits() as i32) - 1) as u32
    }

    #[must_use]
    pub fn prim_count(&self) -> u32 {
        self.bounds_max.w.to_bits()
    }

    #[must_use]
    pub fn bounds(&self) -> Aabb {
        Aabb::new(self.bounds_min.xyz(), self.bounds_max.xyz())
    }
}

// Vec3 extraction from Vec4 without the swizzle import at module scope.
trait Vec4Xyz {
    fn xyz(&self) -> Vec3;
}
impl Vec4Xyz for Vec4 {
    fn xyz(&self) -> Vec3 {
        Vec3::new(self.x, self.y, self.z)
    }
}

/// GPU triangle for path tracing (48 bytes). `v0.w` = material index (float
/// bits), `v1.w`/`v2.w` = packed face normal x/y (z derived by the shader).
#[derive(Debug, Clone, Copy, PartialEq)]
#[repr(C, align(16))]
pub struct GpuTriangle {
    pub v0: Vec4,
    pub v1: Vec4,
    pub v2: Vec4,
}

impl GpuTriangle {
    #[must_use]
    pub fn new(p0: Vec3, p1: Vec3, p2: Vec3, material_index: u32) -> Self {
        let mut tri = Self {
            v0: p0.extend(0.0),
            v1: p1.extend(0.0),
            v2: p2.extend(0.0),
        };
        tri.v0.w = f32::from_bits(material_index);

        // Pack the face normal (z reconstructed as sqrt(1 − x² − y²)).
        let edge1 = p1 - p0;
        let edge2 = p2 - p0;
        let normal = edge1.cross(edge2).normalize();
        tri.v1.w = normal.x;
        tri.v2.w = normal.y;
        tri
    }

    #[must_use]
    pub fn position0(&self) -> Vec3 {
        self.v0.xyz()
    }
    #[must_use]
    pub fn position1(&self) -> Vec3 {
        self.v1.xyz()
    }
    #[must_use]
    pub fn position2(&self) -> Vec3 {
        self.v2.xyz()
    }

    #[must_use]
    pub fn material_index(&self) -> u32 {
        self.v0.w.to_bits()
    }

    #[must_use]
    pub fn normal(&self) -> Vec3 {
        let nx = self.v1.w;
        let ny = self.v2.w;
        let nz2 = 1.0 - nx * nx - ny * ny;
        let nz = if nz2 > 0.0 { nz2.sqrt() } else { 0.0 };
        Vec3::new(nx, ny, nz)
    }

    #[must_use]
    pub fn bounds(&self) -> Aabb {
        let mut b = Aabb::default();
        b.expand_point(self.position0());
        b.expand_point(self.position1());
        b.expand_point(self.position2());
        b
    }

    #[must_use]
    pub fn centroid(&self) -> Vec3 {
        (self.position0() + self.position1() + self.position2()) / 3.0
    }
}

/// GPU path-tracing material (64 bytes).
#[derive(Debug, Clone, Copy, PartialEq)]
#[repr(C, align(16))]
pub struct GpuPtMaterial {
    /// rgb = albedo, a = alpha.
    pub albedo: Vec4,
    /// rgb = emission colour, a = intensity.
    pub emission: Vec4,
    /// x = roughness, y = metallic, z = ior, w = transmission.
    pub properties: Vec4,
    /// x = albedo tex, y = roughness tex, z = normal tex, w = emission tex.
    pub tex_indices: Vec4,
}

impl Default for GpuPtMaterial {
    fn default() -> Self {
        Self {
            albedo: Vec4::new(0.8, 0.8, 0.8, 1.0),
            emission: Vec4::ZERO,
            properties: Vec4::new(0.5, 0.0, 1.5, 0.0),
            tex_indices: Vec4::splat(-1.0),
        }
    }
}

// ============================================================================
// BVH builder
// ============================================================================

/// Build configuration.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct BvhConfig {
    /// Max primitives per leaf.
    pub max_prims_in_node: u32,
    /// Relative cost of traversal vs intersection.
    pub traversal_cost: f32,
    pub intersect_cost: f32,
}

impl Default for BvhConfig {
    fn default() -> Self {
        Self { max_prims_in_node: 4, traversal_cost: 1.0, intersect_cost: 1.0 }
    }
}

/// SAH bucket count (fixed at 12, as in the C++).
const SAH_BUCKETS: usize = 12;

/// Primitive info during construction.
#[derive(Debug, Clone, Copy)]
struct BvhPrimitive {
    /// Original triangle index.
    index: u32,
    bounds: Aabb,
    centroid: Vec3,
}

/// Build-tree node, stored in the builder's arena.
#[derive(Debug, Clone, Copy, Default)]
struct BuildNode {
    bounds: Aabb,
    /// Arena indices of children, `[left, right]`; `None` for leaves.
    children: Option<[usize; 2]>,
    first_prim_offset: u32,
    prim_count: u32,
}

impl BuildNode {
    fn is_leaf(&self) -> bool {
        self.prim_count > 0
    }
}

#[derive(Debug, Clone, Copy, Default)]
struct SahBucket {
    count: u32,
    bounds: Aabb,
}

/// SAH-based BVH builder. Outputs a flat node array for GPU traversal.
#[derive(Debug, Default)]
pub struct BvhBuilder {
    config: BvhConfig,
    nodes: Vec<GpuBvhNode>,
    ordered_prim_indices: Vec<u32>,
    tree_depth: u32,
    leaf_count: u32,
}

impl BvhBuilder {
    #[must_use]
    pub fn new(config: BvhConfig) -> Self {
        Self { config, ..Default::default() }
    }

    /// Build from triangles. Returns `false` for an empty input (as C++).
    pub fn build(&mut self, triangles: &[GpuTriangle]) -> bool {
        if triangles.is_empty() {
            return false;
        }

        self.nodes.clear();
        self.ordered_prim_indices.clear();
        self.tree_depth = 0;
        self.leaf_count = 0;

        let mut primitives: Vec<BvhPrimitive> = triangles
            .iter()
            .enumerate()
            .map(|(i, tri)| BvhPrimitive {
                index: i as u32,
                bounds: tri.bounds(),
                centroid: tri.centroid(),
            })
            .collect();

        let mut arena: Vec<BuildNode> = Vec::new();
        let mut ordered_prims: Vec<u32> = Vec::with_capacity(triangles.len());
        let root = self.build_recursive(&mut arena, &mut primitives, &mut ordered_prims);

        self.nodes = vec![GpuBvhNode {
            bounds_min: Vec4::ZERO,
            bounds_max: Vec4::ZERO,
        }; arena.len()];
        self.ordered_prim_indices = ordered_prims;

        let mut offset = 0usize;
        self.tree_depth = 0;
        self.flatten(&arena, root, &mut offset, 1);

        true
    }

    #[must_use]
    pub fn nodes(&self) -> &[GpuBvhNode] {
        &self.nodes
    }

    /// Reordered triangle indices (cache-friendly leaf access).
    #[must_use]
    pub fn ordered_prim_indices(&self) -> &[u32] {
        &self.ordered_prim_indices
    }

    #[must_use]
    pub fn node_count(&self) -> u32 {
        self.nodes.len() as u32
    }

    #[must_use]
    pub fn tree_depth(&self) -> u32 {
        self.tree_depth
    }

    #[must_use]
    pub fn leaf_count(&self) -> u32 {
        self.leaf_count
    }

    /// Returns the new node's arena index.
    fn build_recursive(
        &mut self,
        arena: &mut Vec<BuildNode>,
        prims: &mut [BvhPrimitive],
        ordered_prims: &mut Vec<u32>,
    ) -> usize {
        let node_index = arena.len();
        arena.push(BuildNode::default());

        // Bounds of all primitives.
        let mut bounds = Aabb::default();
        for prim in prims.iter() {
            bounds.expand(&prim.bounds);
        }

        let num_prims = prims.len() as u32;

        // Leaf if few primitives.
        if num_prims <= self.config.max_prims_in_node {
            self.leaf_count += 1;
            arena[node_index].bounds = bounds;
            arena[node_index].first_prim_offset = ordered_prims.len() as u32;
            arena[node_index].prim_count = num_prims;
            ordered_prims.extend(prims.iter().map(|p| p.index));
            return node_index;
        }

        // Centroid bounds for partitioning.
        let mut centroid_bounds = Aabb::default();
        for prim in prims.iter() {
            centroid_bounds.expand_point(prim.centroid);
        }

        let axis = centroid_bounds.longest_axis();
        let axis_min = centroid_bounds.min[axis];
        let axis_max = centroid_bounds.max[axis];

        // Coincident centroids → leaf.
        if axis_max == axis_min {
            self.leaf_count += 1;
            arena[node_index].bounds = bounds;
            arena[node_index].first_prim_offset = ordered_prims.len() as u32;
            arena[node_index].prim_count = num_prims;
            ordered_prims.extend(prims.iter().map(|p| p.index));
            return node_index;
        }

        // Assign primitives to SAH buckets.
        let mut buckets = [SahBucket::default(); SAH_BUCKETS];
        let bucket_of = |centroid: f32| -> usize {
            let offset = (centroid - axis_min) / (axis_max - axis_min);
            ((SAH_BUCKETS as f32 * offset) as usize).min(SAH_BUCKETS - 1)
        };
        for prim in prims.iter() {
            let b = bucket_of(prim.centroid[axis]);
            buckets[b].count += 1;
            buckets[b].bounds.expand(&prim.bounds);
        }

        // Cost of splitting after each bucket.
        let bounds_area = bounds.surface_area();
        let mut costs = [0.0f32; SAH_BUCKETS - 1];
        for (i, cost) in costs.iter_mut().enumerate() {
            let mut b0 = Aabb::default();
            let mut b1 = Aabb::default();
            let mut count0 = 0u32;
            let mut count1 = 0u32;
            for bucket in buckets.iter().take(i + 1) {
                b0.expand(&bucket.bounds);
                count0 += bucket.count;
            }
            for bucket in buckets.iter().skip(i + 1) {
                b1.expand(&bucket.bounds);
                count1 += bucket.count;
            }
            let area0 = if b0.is_valid() { b0.surface_area() } else { 0.0 };
            let area1 = if b1.is_valid() { b1.surface_area() } else { 0.0 };
            *cost = self.config.traversal_cost
                + (count0 as f32 * area0 + count1 as f32 * area1) / bounds_area
                    * self.config.intersect_cost;
        }

        // Best split.
        let mut min_cost = costs[0];
        let mut min_cost_split = 0usize;
        for (i, &c) in costs.iter().enumerate().skip(1) {
            if c < min_cost {
                min_cost = c;
                min_cost_split = i;
            }
        }

        let leaf_cost = self.config.intersect_cost * num_prims as f32;

        if num_prims > self.config.max_prims_in_node || min_cost < leaf_cost {
            // Partition primitives around the chosen bucket.
            let mid = {
                let mut left = 0usize;
                let mut right = prims.len();
                // std::partition analogue: stable enough for identical output
                // ordering is not guaranteed in C++ either.
                while left < right {
                    if bucket_of(prims[left].centroid[axis]) <= min_cost_split {
                        left += 1;
                    } else {
                        right -= 1;
                        prims.swap(left, right);
                    }
                }
                left
            };

            // Edge case: partition failed → median split on the axis.
            let mid = if mid == 0 || mid == prims.len() {
                let m = prims.len() / 2;
                prims.select_nth_unstable_by(m, |a, b| {
                    a.centroid[axis]
                        .partial_cmp(&b.centroid[axis])
                        .unwrap_or(std::cmp::Ordering::Equal)
                });
                m
            } else {
                mid
            };

            let (left_prims, right_prims) = prims.split_at_mut(mid);
            let left_child = self.build_recursive(arena, left_prims, ordered_prims);
            let right_child = self.build_recursive(arena, right_prims, ordered_prims);

            arena[node_index].bounds = bounds;
            arena[node_index].children = Some([left_child, right_child]);
        } else {
            self.leaf_count += 1;
            arena[node_index].bounds = bounds;
            arena[node_index].first_prim_offset = ordered_prims.len() as u32;
            arena[node_index].prim_count = num_prims;
            ordered_prims.extend(prims.iter().map(|p| p.index));
        }

        node_index
    }

    /// Flatten the build tree into `self.nodes`. Returns the node's flat
    /// offset; tracks depth (the C++ uses a function-static counter — this
    /// version threads `depth` through the recursion instead).
    fn flatten(
        &mut self,
        arena: &[BuildNode],
        node_index: usize,
        offset: &mut usize,
        depth: u32,
    ) -> usize {
        self.tree_depth = self.tree_depth.max(depth);

        let node = &arena[node_index];
        let my_offset = *offset;
        *offset += 1;

        if node.is_leaf() {
            self.nodes[my_offset].set_leaf_node(
                &node.bounds,
                node.first_prim_offset,
                node.prim_count,
            );
        } else {
            let [left, right] = node.children.expect("internal node has children");
            self.flatten(arena, left, offset, depth + 1);
            let right_offset = self.flatten(arena, right, offset, depth + 1);
            // The C++ sets the node's fields *after* recursing; keep that
            // order so the flat layout is identical.
            let bounds = arena[node_index].bounds;
            self.nodes[my_offset].set_internal_node(&bounds, my_offset as u32 + 1, right_offset as u32);
        }

        my_offset
    }
}

// ============================================================================
// Materials
// ============================================================================

/// Material lookup table — the C++ reads `materials/material_map.json` into
/// lazily-initialized globals; here it's an explicit value.
///
/// JSON shape (all keys optional):
/// ```json
/// {
///   "name_overrides":   { "material name": "polyhaven/..." },
///   "category_defaults":{ "Walls_Exterior": "polyhaven/..." },
///   "materials":        { "polyhaven/x": { "folder": "..." } }
/// }
/// ```
/// Each `polyhaven/` material occupies 4 consecutive texture layers; the
/// texture index assigned is the running count in JSON iteration order.
#[derive(Debug, Clone, Default)]
pub struct MaterialTable {
    pub texture_indices: std::collections::HashMap<String, i32>,
    pub name_overrides: std::collections::HashMap<String, String>,
    pub category_defaults: std::collections::HashMap<String, String>,
}

impl MaterialTable {
    /// Load from a directory containing `material_map.json`. Missing or
    /// malformed files yield an empty table (the C++ logs and continues).
    #[must_use]
    pub fn load(materials_dir: &std::path::Path) -> Self {
        let path = materials_dir.join("material_map.json");
        let Ok(text) = std::fs::read_to_string(path) else {
            return Self::default();
        };
        let Ok(map) = serde_json::from_str::<serde_json::Value>(&text) else {
            return Self::default();
        };

        let mut table = Self::default();

        if let Some(overrides) = map.get("name_overrides").and_then(|v| v.as_object()) {
            for (k, v) in overrides {
                if let Some(s) = v.as_str() {
                    table.name_overrides.insert(k.clone(), s.to_string());
                }
            }
        }
        if let Some(defaults) = map.get("category_defaults").and_then(|v| v.as_object()) {
            for (k, v) in defaults {
                if let Some(s) = v.as_str() {
                    table.category_defaults.insert(k.clone(), s.to_string());
                }
            }
        }
        if let Some(materials) = map.get("materials").and_then(|v| v.as_object()) {
            let mut tex_index = 0;
            for (key, value) in materials {
                if key.starts_with("polyhaven/") && value.get("folder").is_some() {
                    table.texture_indices.insert(key.clone(), tex_index);
                    tex_index += 4; // 4 texture layers per polyhaven material
                }
            }
        }

        table
    }

    /// Texture index for a material name, checking name overrides, then the
    /// direct polyhaven name, then category defaults by element type.
    /// `-1` = no texture.
    #[must_use]
    pub fn texture_index_for(&self, material_name: &str, elem_type: ElementType) -> i32 {
        if let Some(mapped) = self.name_overrides.get(material_name) {
            if let Some(&idx) = self.texture_indices.get(mapped) {
                return idx;
            }
        }
        if let Some(&idx) = self.texture_indices.get(material_name) {
            return idx;
        }

        let category = match elem_type {
            ElementType::Wall => {
                if material_name.contains("Ext")
                    || material_name.contains("brick")
                    || material_name.contains("Brick")
                {
                    "Walls_Exterior"
                } else {
                    "Walls"
                }
            }
            ElementType::Floor => {
                if material_name.contains("Wood") || material_name.contains("wood") {
                    "Floors_Wood"
                } else {
                    "Floors"
                }
            }
            ElementType::Roof => {
                if material_name.contains("Metal") || material_name.contains("metal") {
                    "Roofs_Metal"
                } else {
                    "Roofs"
                }
            }
            _ => "",
        };

        if !category.is_empty() {
            if let Some(mapped) = self.category_defaults.get(category) {
                if let Some(&idx) = self.texture_indices.get(mapped) {
                    return idx;
                }
            }
        }

        -1
    }
}

/// Map a material keyword to a Poly Haven texture name (same rules as the
/// legacy renderer's `resolveMaterialName`).
#[must_use]
pub fn map_material_keyword(key: &str, elem_type: ElementType) -> String {
    let lower = key.to_lowercase();

    if lower.contains("brick") {
        return "polyhaven/brick_wall_006".into();
    }
    if lower.contains("concrete") || lower.contains("cement") || lower.contains("stone") {
        return "polyhaven/concrete_wall_008".into();
    }
    if lower.contains("drywall")
        || lower.contains("plaster")
        || lower.contains("gypsum")
        || lower.contains("paint")
        || lower.contains("stucco")
        || lower.contains("interior")
        || lower.contains("tyvek")
        || lower.contains("membrane")
        || lower.contains("poly")
        || lower.contains("vapor")
    {
        return "polyhaven/concrete_wall_008".into(); // interior walls & membranes
    }
    if lower.contains("tile") || lower.contains("ceramic") {
        return "polyhaven/concrete_floor_003".into(); // tiles use floor concrete
    }
    if lower.contains("wood")
        || lower.contains("timber")
        || lower.contains("osb")
        || lower.contains("plywood")
    {
        return "polyhaven/wood_floor_deck".into();
    }
    if lower.contains("vinyl") || lower.contains("siding") {
        return "polyhaven/concrete_wall_008".into();
    }
    if lower.contains("glass") || lower.contains("glazing") {
        return "glass".into();
    }
    if lower.contains("metal") || lower.contains("steel") || lower.contains("aluminum") {
        return "polyhaven/metal_plate_02".into();
    }
    if lower.contains("shingle")
        || lower.contains("asphalt")
        || lower.contains("roof")
        || lower.contains("slate")
    {
        return "polyhaven/roof_slates_02".into();
    }
    if lower.contains("grass") || lower.contains("lawn") {
        return "polyhaven/grass_path_2".into();
    }
    if lower.contains("gravel") || lower.contains("patio") {
        return "polyhaven/gravel_concrete".into();
    }
    if lower.contains("pavement") {
        return "polyhaven/asphalt_04".into();
    }

    // Generic "wall" without a specific material.
    if lower == "wall" || lower == "interior" || lower == "partition" {
        return "polyhaven/concrete_wall_008".into();
    }

    // Default by element type.
    match elem_type {
        ElementType::Wall => "polyhaven/brick_wall_006".into(),
        ElementType::Floor => "polyhaven/concrete_floor_003".into(),
        ElementType::Roof => "polyhaven/roof_slates_02".into(),
        ElementType::Door | ElementType::Beam | ElementType::Column => {
            "polyhaven/wood_floor_deck".into()
        }
        ElementType::Window => "glass".into(),
        _ => "polyhaven/concrete_wall_008".into(),
    }
}

/// Resolve an element's material name the way the renderer does.
#[must_use]
pub fn resolve_path_tracer_material(elem: &StructuralElement) -> String {
    let mat_name = &elem.material;
    if mat_name.contains("polyhaven/") {
        return mat_name.clone();
    }
    if !mat_name.is_empty() && mat_name != "default" {
        return map_material_keyword(mat_name, elem.element_type);
    }
    map_material_keyword("", elem.element_type)
}

/// Material properties for an element, matched to Poly Haven colours so the
/// path tracer agrees with the real-time renderer.
#[must_use]
pub fn material_for_element(elem: &StructuralElement, table: &MaterialTable) -> GpuPtMaterial {
    let mut mat = GpuPtMaterial::default();
    let mat_name = resolve_path_tracer_material(elem);
    mat.tex_indices.x = table.texture_index_for(&mat_name, elem.element_type) as f32;

    if mat_name.contains("brick") || mat_name.contains("Brick") {
        mat.albedo = Vec4::new(0.45, 0.28, 0.22, 1.0); // brick_wall_006
        mat.properties.x = 0.85;
    } else if mat_name.contains("concrete") || mat_name.contains("Concrete") {
        mat.albedo = Vec4::new(0.5, 0.48, 0.45, 1.0); // concrete_wall_008
        mat.properties.x = 0.9;
    } else if mat_name.contains("wood") || mat_name.contains("Wood") {
        mat.albedo = Vec4::new(0.4, 0.28, 0.18, 1.0); // wood_floor_deck
        mat.properties.x = 0.65;
    } else if mat_name.contains("roof_slates") || mat_name.contains("polyhaven/roof") {
        mat.albedo = Vec4::new(0.25, 0.24, 0.23, 1.0); // roof_slates_02
        mat.properties.x = 0.75;
    } else if mat_name.contains("asphalt") {
        mat.albedo = Vec4::new(0.15, 0.15, 0.15, 1.0); // asphalt_04
        mat.properties.x = 0.9;
    } else if mat_name.contains("grass") {
        mat.albedo = Vec4::new(0.25, 0.35, 0.15, 1.0); // grass_path_2
        mat.properties.x = 0.9;
    } else if mat_name.contains("gravel") {
        mat.albedo = Vec4::new(0.45, 0.42, 0.4, 1.0); // gravel_concrete
        mat.properties.x = 0.95;
    } else if mat_name.contains("metal") || mat_name.contains("steel") || mat_name.contains("Steel") {
        mat.albedo = Vec4::new(0.55, 0.55, 0.55, 1.0); // metal_plate_02
        mat.properties.x = 0.35;
        mat.properties.y = 0.9; // metallic
    } else if mat_name.contains("glass") || mat_name.contains("Glass") {
        mat.albedo = Vec4::new(0.9, 0.9, 0.95, 0.3);
        mat.properties.x = 0.05;
        mat.properties.z = 1.5; // IOR
        mat.properties.w = 0.9; // transmission
    } else {
        // Defaults by element type, Poly Haven-matched.
        match elem.element_type {
            ElementType::Wall => {
                mat.albedo = Vec4::new(0.45, 0.28, 0.22, 1.0);
                mat.properties.x = 0.85;
            }
            ElementType::Floor => {
                mat.albedo = Vec4::new(0.5, 0.48, 0.45, 1.0);
                mat.properties.x = 0.85;
            }
            ElementType::Roof => {
                mat.albedo = Vec4::new(0.25, 0.24, 0.23, 1.0);
                mat.properties.x = 0.75;
            }
            ElementType::Window => {
                mat.albedo = Vec4::new(0.9, 0.95, 1.0, 0.2);
                mat.properties.x = 0.02;
                mat.properties.z = 1.5;
                mat.properties.w = 0.95;
            }
            _ => {
                mat.albedo = Vec4::new(0.5, 0.5, 0.5, 1.0);
                mat.properties.x = 0.7;
            }
        }
    }

    mat
}

/// Terrain material: colour from the material name, `tex_indices.w = 1`
/// flags simple XZ UV projection for the shader.
#[must_use]
pub fn terrain_material(material_name: &str, table: &MaterialTable) -> GpuPtMaterial {
    let mut mat = GpuPtMaterial::default();

    let mut tex_index = -1;
    if !material_name.is_empty() {
        if let Some(&idx) = table.texture_indices.get(material_name) {
            tex_index = idx;
        } else if let Some(&idx) = table.texture_indices.get(&format!("polyhaven/{material_name}")) {
            tex_index = idx;
        }
    }
    mat.tex_indices.x = tex_index as f32;

    let lower = material_name.to_lowercase();
    if lower.contains("grass") {
        mat.albedo = Vec4::new(0.25, 0.35, 0.15, 1.0);
        mat.properties.x = 0.9;
    } else if lower.contains("gravel") {
        mat.albedo = Vec4::new(0.45, 0.42, 0.4, 1.0);
        mat.properties.x = 0.95;
    } else if lower.contains("asphalt") {
        mat.albedo = Vec4::new(0.15, 0.15, 0.15, 1.0);
        mat.properties.x = 0.9;
    } else if lower.contains("sand") {
        mat.albedo = Vec4::new(0.76, 0.70, 0.50, 1.0);
        mat.properties.x = 0.95;
    } else if lower.contains("mud") || lower.contains("dirt") {
        mat.albedo = Vec4::new(0.35, 0.25, 0.18, 1.0);
        mat.properties.x = 0.9;
    } else if lower.contains("rock") || lower.contains("stone") {
        mat.albedo = Vec4::new(0.4, 0.38, 0.35, 1.0);
        mat.properties.x = 0.85;
    } else if lower.contains("snow") {
        mat.albedo = Vec4::new(0.95, 0.95, 0.98, 1.0);
        mat.properties.x = 0.7;
    } else if lower.contains("concrete") {
        mat.albedo = Vec4::new(0.5, 0.48, 0.45, 1.0);
        mat.properties.x = 0.9;
    } else {
        mat.albedo = Vec4::new(0.35, 0.32, 0.22, 1.0); // default greenish-brown
        mat.properties.x = 0.85;
    }

    mat.properties.y = 0.0; // non-metallic
    mat.tex_indices.w = 1.0; // terrain flag for the shader
    mat
}

// ============================================================================
// Element → triangles
// ============================================================================

/// Generate path-tracing triangles for one structural element. Custom
/// meshes are used verbatim; otherwise geometry is generated procedurally
/// per element type (matching the C++ fallback logic).
fn generate_element_triangles(
    elem: &StructuralElement,
    material_index: u32,
    triangles: &mut Vec<GpuTriangle>,
) {
    // Custom mesh wins for every element type.
    if elem.mesh.has_data() {
        let vertices = &elem.mesh.vertices;
        for face in &elem.mesh.faces {
            let [a, b, c] = *face;
            if (a as usize) < vertices.len()
                && (b as usize) < vertices.len()
                && (c as usize) < vertices.len()
            {
                triangles.push(GpuTriangle::new(
                    vertices[a as usize],
                    vertices[b as usize],
                    vertices[c as usize],
                    material_index,
                ));
            }
        }
        return;
    }

    let start = elem.start;
    let end = elem.end;
    let w = elem.width;
    let d = elem.depth;

    let add_quad = |corners: &[Vec3], a: usize, b: usize, c: usize, d: usize, triangles: &mut Vec<GpuTriangle>| {
        triangles.push(GpuTriangle::new(corners[a], corners[b], corners[c], material_index));
        triangles.push(GpuTriangle::new(corners[a], corners[c], corners[d], material_index));
    };

    match elem.element_type {
        ElementType::Beam => {
            let dir = end - start;
            let len = dir.length();
            if len < 0.001 {
                return;
            }
            let dir = dir / len;

            let mut up = Vec3::Y;
            if dir.dot(up).abs() > 0.99 {
                up = Vec3::X;
            }
            let right = dir.cross(up).normalize();
            let local_up = right.cross(dir);

            let hw = right * (w * 0.5);
            let hd = local_up * (d * 0.5);

            let corners = [
                start - hw - hd, start + hw - hd, start + hw + hd, start - hw + hd,
                end - hw - hd, end + hw - hd, end + hw + hd, end - hw + hd,
            ];

            add_quad(&corners, 0, 1, 2, 3, triangles); // start face
            add_quad(&corners, 5, 4, 7, 6, triangles); // end face
            add_quad(&corners, 0, 4, 5, 1, triangles); // bottom
            add_quad(&corners, 2, 6, 7, 3, triangles); // top
            add_quad(&corners, 1, 5, 6, 2, triangles); // right
            add_quad(&corners, 4, 0, 3, 7, triangles); // left
        }

        ElementType::Column => {
            let base = start;
            let mut height = end.y - start.y;
            if height < 0.001 {
                height = 1.0;
            }

            let hw = Vec3::new(w * 0.5, 0.0, 0.0);
            let hd = Vec3::new(0.0, 0.0, d * 0.5);
            let h = Vec3::new(0.0, height, 0.0);

            let corners = [
                base - hw - hd, base + hw - hd, base + hw + hd, base - hw + hd,
                base - hw - hd + h, base + hw - hd + h, base + hw + hd + h, base - hw + hd + h,
            ];

            add_quad(&corners, 0, 1, 2, 3, triangles); // bottom
            add_quad(&corners, 5, 4, 7, 6, triangles); // top
            add_quad(&corners, 0, 4, 5, 1, triangles); // front
            add_quad(&corners, 2, 6, 7, 3, triangles); // back
            add_quad(&corners, 1, 5, 6, 2, triangles); // right
            add_quad(&corners, 4, 0, 3, 7, triangles); // left
        }

        ElementType::Floor | ElementType::Roof => {
            // Fallback: thin slab from start to end (the real-time
            // renderer's logic). `end.y - start.y` is the thickness.
            let slab_width = end.x - start.x;
            let slab_depth = end.z - start.z;
            let mut thickness = end.y - start.y;
            if thickness.abs() < 0.01 {
                thickness = 0.3;
            }
            if slab_width.abs() < 0.01 || slab_depth.abs() < 0.01 {
                return; // skip invalid slabs
            }

            let corners = [
                Vec3::new(start.x, start.y, start.z),
                Vec3::new(end.x, start.y, start.z),
                Vec3::new(end.x, start.y, end.z),
                Vec3::new(start.x, start.y, end.z),
                Vec3::new(start.x, start.y + thickness, start.z),
                Vec3::new(end.x, start.y + thickness, start.z),
                Vec3::new(end.x, start.y + thickness, end.z),
                Vec3::new(start.x, start.y + thickness, end.z),
            ];

            add_quad(&corners, 0, 3, 2, 1, triangles); // bottom (normal down)
            add_quad(&corners, 4, 7, 6, 5, triangles); // top (reversed for lighting)
            add_quad(&corners, 0, 1, 5, 4, triangles); // front
            add_quad(&corners, 2, 3, 7, 6, triangles); // back
            add_quad(&corners, 1, 2, 6, 5, triangles); // right
            add_quad(&corners, 3, 0, 4, 7, triangles); // left
        }

        ElementType::Wall => {
            // Fallback: vertical wall slab.
            let wall_dir = end - start;
            let wall_len = (wall_dir.x * wall_dir.x + wall_dir.z * wall_dir.z).sqrt();
            if wall_len < 0.001 {
                return;
            }
            let dir = Vec3::new(wall_dir.x / wall_len, 0.0, wall_dir.z / wall_len);
            let perp = Vec3::new(-dir.z, 0.0, dir.x);

            let mut height = end.y - start.y;
            if height < 0.001 {
                height = if start.y > 0.0 { start.y } else { 8.0 };
            }

            let hw = perp * (w * 0.5);
            let h = Vec3::new(0.0, height, 0.0);

            let corners = [
                start - hw, start + hw, end + hw, end - hw,
                start - hw + h, start + hw + h, end + hw + h, end - hw + h,
            ];

            add_quad(&corners, 0, 1, 2, 3, triangles); // bottom
            add_quad(&corners, 5, 4, 7, 6, triangles); // top
            add_quad(&corners, 0, 4, 5, 1, triangles); // front
            add_quad(&corners, 3, 7, 6, 2, triangles); // back
            add_quad(&corners, 1, 5, 6, 2, triangles); // right (end)
            add_quad(&corners, 4, 0, 3, 7, triangles); // left (start)
        }

        ElementType::Window => {
            // Flat glass quad, oriented parallel to the wall.
            let width = if w > 0.01 { w } else { 1.0 };
            let mut height = end.y - start.y;
            if height < 0.01 {
                height = 1.5;
            }

            let dir = end - start;
            let len = (dir.x * dir.x + dir.z * dir.z).sqrt();

            if len < 0.001 {
                // Vertical window facing along X.
                let corners = [
                    start,
                    start + Vec3::new(width, 0.0, 0.0),
                    start + Vec3::new(width, height, 0.0),
                    start + Vec3::new(0.0, height, 0.0),
                ];
                triangles.push(GpuTriangle::new(corners[0], corners[1], corners[2], material_index));
                triangles.push(GpuTriangle::new(corners[0], corners[2], corners[3], material_index));
            } else {
                let dir_norm = Vec3::new(dir.x / len, 0.0, dir.z / len);
                let along = dir_norm * (width * 0.5);
                let up = Vec3::new(0.0, height, 0.0);
                let mut center = (start + end) * 0.5;
                center.y = start.y;

                let corners = [
                    center - along,
                    center + along,
                    center + along + up,
                    center - along + up,
                ];
                triangles.push(GpuTriangle::new(corners[0], corners[1], corners[2], material_index));
                triangles.push(GpuTriangle::new(corners[0], corners[2], corners[3], material_index));
            }
        }

        ElementType::Door => {
            // Thin box like a wall.
            let door_width = if w > 0.01 { w } else { 0.9 };
            let mut door_height = end.y - start.y;
            if door_height < 0.01 {
                door_height = 2.1;
            }
            let door_thickness = if d > 0.01 { d } else { 0.05 };

            let dir = end - start;
            let len = (dir.x * dir.x + dir.z * dir.z).sqrt();
            let dir_norm = if len > 0.001 {
                Vec3::new(dir.x / len, 0.0, dir.z / len)
            } else {
                Vec3::X
            };
            let perp = Vec3::new(-dir_norm.z, 0.0, dir_norm.x);

            let hw = perp * (door_thickness * 0.5);
            let hd_w = dir_norm * (door_width * 0.5);
            let mut center = (start + end) * 0.5;
            center.y = start.y;
            let h = Vec3::new(0.0, door_height, 0.0);

            let corners = [
                center - hw - hd_w,
                center - hw + hd_w,
                center + hw + hd_w,
                center + hw - hd_w,
                center - hw - hd_w + h,
                center - hw + hd_w + h,
                center + hw + hd_w + h,
                center + hw - hd_w + h,
            ];

            add_quad(&corners, 0, 1, 2, 3, triangles); // bottom
            add_quad(&corners, 5, 4, 7, 6, triangles); // top
            add_quad(&corners, 0, 4, 5, 1, triangles); // front
            add_quad(&corners, 3, 7, 6, 2, triangles); // back
            add_quad(&corners, 1, 5, 6, 2, triangles); // right
            add_quad(&corners, 4, 0, 3, 7, triangles); // left
        }

        _ => {} // other element types are skipped
    }
}

/// Triangles from a terrain mesh.
fn generate_terrain_triangles(
    terrain: &TerrainMesh,
    material_index: u32,
    triangles: &mut Vec<GpuTriangle>,
) {
    let vertices = &terrain.vertices;
    let indices = &terrain.indices;

    if indices.len() < 3 {
        return;
    }

    for tri in indices.chunks_exact(3) {
        let (i0, i1, i2) = (tri[0] as usize, tri[1] as usize, tri[2] as usize);
        if i0 >= vertices.len() || i1 >= vertices.len() || i2 >= vertices.len() {
            continue;
        }
        triangles.push(GpuTriangle::new(
            vertices[i0].position,
            vertices[i1].position,
            vertices[i2].position,
            material_index,
        ));
    }
}

// ============================================================================
// Scene assembly
// ============================================================================

/// Output of [`build_scene_bvh`]: GPU-ready triangles (reordered for the
/// BVH), flat node array, and materials.
#[derive(Debug, Default)]
pub struct SceneBvh {
    pub triangles: Vec<GpuTriangle>,
    pub nodes: Vec<GpuBvhNode>,
    pub materials: Vec<GpuPtMaterial>,
    pub tree_depth: u32,
    pub leaf_count: u32,
}

/// Build a scene BVH from structural elements, optionally including a
/// terrain mesh (with its material name).
///
/// Returns `None` when there are no elements or no triangles could be
/// generated (the C++ returns `false`).
#[must_use]
pub fn build_scene_bvh(
    elements: &[StructuralElement],
    terrain: Option<(&TerrainMesh, &str)>,
    materials: &MaterialTable,
) -> Option<SceneBvh> {
    if elements.is_empty() && terrain.is_none() {
        return None;
    }

    let mut out_triangles = Vec::new();
    let mut out_materials = Vec::new();

    for elem in elements {
        let mat_index = out_materials.len() as u32;
        out_materials.push(material_for_element(elem, materials));
        generate_element_triangles(elem, mat_index, &mut out_triangles);
    }

    if let Some((terrain_mesh, terrain_material_name)) = terrain {
        if terrain_mesh.has_data() {
            let terrain_mat_index = out_materials.len() as u32;
            out_materials.push(terrain_material(terrain_material_name, materials));
            generate_terrain_triangles(terrain_mesh, terrain_mat_index, &mut out_triangles);
        }
    }

    if out_triangles.is_empty() {
        return None;
    }

    let mut builder = BvhBuilder::default();
    if !builder.build(&out_triangles) {
        return None;
    }

    // Reorder triangles for cache-friendly leaf access.
    let reordered: Vec<GpuTriangle> = builder
        .ordered_prim_indices()
        .iter()
        .map(|&idx| out_triangles[idx as usize])
        .collect();

    Some(SceneBvh {
        triangles: reordered,
        nodes: builder.nodes().to_vec(),
        materials: out_materials,
        tree_depth: builder.tree_depth(),
        leaf_count: builder.leaf_count(),
    })
}

// ============================================================================
// Tests
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;
    use crate::domain::MeshData;

    #[test]
    fn aabb_default_is_invalid_and_expands() {
        let mut b = Aabb::default();
        assert!(!b.is_valid());
        b.expand_point(Vec3::ZERO);
        b.expand_point(Vec3::new(2.0, 4.0, 6.0));
        assert!(b.is_valid());
        assert_eq!(b.min, Vec3::ZERO);
        assert_eq!(b.max, Vec3::new(2.0, 4.0, 6.0));
        assert!((b.surface_area() - 2.0 * (8.0 + 24.0 + 12.0)).abs() < 1e-4);
        assert_eq!(b.longest_axis(), 2); // Z is longest
        assert_eq!(b.centroid(), Vec3::new(1.0, 2.0, 3.0));
    }

    #[test]
    fn gpu_node_bit_packing_round_trips() {
        let bounds = Aabb::new(Vec3::ZERO, Vec3::ONE);

        let mut internal = GpuBvhNode { bounds_min: Vec4::ZERO, bounds_max: Vec4::ZERO };
        internal.set_internal_node(&bounds, 7, 42);
        assert!(!internal.is_leaf());
        assert_eq!(internal.left_child(), 7);
        assert_eq!(internal.right_child(), 42);
        assert_eq!(internal.bounds().min, Vec3::ZERO);
        assert_eq!(internal.bounds().max, Vec3::ONE);

        let mut leaf = GpuBvhNode { bounds_min: Vec4::ZERO, bounds_max: Vec4::ZERO };
        leaf.set_leaf_node(&bounds, 5, 3);
        assert!(leaf.is_leaf());
        assert_eq!(leaf.prim_offset(), 5);
        assert_eq!(leaf.prim_count(), 3);
    }

    #[test]
    fn gpu_node_layout_is_32_bytes() {
        assert_eq!(std::mem::size_of::<GpuBvhNode>(), 32);
        assert_eq!(std::mem::size_of::<GpuTriangle>(), 48);
        assert_eq!(std::mem::size_of::<GpuPtMaterial>(), 64);
        assert_eq!(std::mem::align_of::<GpuBvhNode>(), 16);
    }

    #[test]
    fn gpu_triangle_packs_material_and_normal() {
        let tri = GpuTriangle::new(Vec3::ZERO, Vec3::X, Vec3::Y, 17);
        assert_eq!(tri.material_index(), 17);
        assert_eq!(tri.position1(), Vec3::X);
        // Face normal is +Z; z is reconstructed from x/y.
        let n = tri.normal();
        assert!(n.x.abs() < 1e-6 && n.y.abs() < 1e-6 && (n.z - 1.0).abs() < 1e-6);
        let b = tri.bounds();
        assert_eq!(b.min, Vec3::ZERO);
        assert_eq!(b.max, Vec3::new(1.0, 1.0, 0.0));
    }

    #[test]
    fn builder_rejects_empty_input() {
        assert!(!BvhBuilder::default().build(&[]));
    }

    #[test]
    fn small_input_is_a_single_leaf() {
        let tris = vec![
            GpuTriangle::new(Vec3::ZERO, Vec3::X, Vec3::Y, 0),
            GpuTriangle::new(Vec3::new(5.0, 0.0, 0.0), Vec3::new(6.0, 0.0, 0.0), Vec3::new(5.0, 1.0, 0.0), 0),
        ];
        let mut builder = BvhBuilder::default();
        assert!(builder.build(&tris));
        assert_eq!(builder.node_count(), 1);
        assert_eq!(builder.leaf_count(), 1);
        assert!(builder.nodes()[0].is_leaf());
        assert_eq!(builder.nodes()[0].prim_count(), 2);
        assert_eq!(builder.ordered_prim_indices(), &[0, 1]);
    }

    /// A grid of separated triangles → a real tree.
    fn grid_triangles(n: u32) -> Vec<GpuTriangle> {
        let mut tris = Vec::new();
        for i in 0..n {
            let x = (i % 8) as f32 * 10.0;
            let z = (i / 8) as f32 * 10.0;
            let p = Vec3::new(x, 0.0, z);
            tris.push(GpuTriangle::new(p, p + Vec3::X, p + Vec3::Z, 0));
        }
        tris
    }

    #[test]
    fn grid_builds_balanced_tree_covering_all_prims() {
        let tris = grid_triangles(64);
        let mut builder = BvhBuilder::default();
        assert!(builder.build(&tris));

        assert!(builder.leaf_count() > 1);
        assert!(builder.tree_depth() >= 2);
        // Full binary tree: nodes = 2 × leaves − 1.
        assert_eq!(builder.node_count(), 2 * builder.leaf_count() - 1);

        // Every triangle appears exactly once in the ordered indices.
        let mut sorted = builder.ordered_prim_indices().to_vec();
        sorted.sort_unstable();
        assert_eq!(sorted, (0..64).collect::<Vec<_>>());

        // Leaf prim counts sum to the input count.
        let leaf_prims: u32 = builder
            .nodes()
            .iter()
            .filter(|n| n.is_leaf())
            .map(GpuBvhNode::prim_count)
            .sum();
        assert_eq!(leaf_prims, 64);

        // Every internal node's bounds contain both children's bounds.
        for node in builder.nodes() {
            if node.is_leaf() {
                continue;
            }
            let parent = node.bounds();
            for child in [node.left_child(), node.right_child()] {
                let cb = builder.nodes()[child as usize].bounds();
                assert!(parent.min.cmple(cb.min).all() && parent.max.cmpge(cb.max).all());
            }
        }
    }

    #[test]
    fn coincident_centroids_force_leaf() {
        // 8 triangles sharing one centroid: more than max_prims_in_node but
        // unsplittable → single leaf.
        let p = Vec3::ZERO;
        let tris = (0..8).map(|_| GpuTriangle::new(p, p, p, 0)).collect::<Vec<_>>();
        let mut builder = BvhBuilder::default();
        assert!(builder.build(&tris));
        assert_eq!(builder.node_count(), 1);
        assert_eq!(builder.nodes()[0].prim_count(), 8);
    }

    fn elem(element_type: ElementType, start: Vec3, end: Vec3, w: f32, d: f32) -> StructuralElement {
        StructuralElement {
            element_type,
            start,
            end,
            width: w,
            depth: d,
            material: "default".into(),
            ..Default::default()
        }
    }

    #[test]
    fn scene_bvh_from_elements() {
        let elements = vec![
            elem(ElementType::Column, Vec3::ZERO, Vec3::new(0.0, 9.0, 0.0), 1.0, 1.0),
            elem(ElementType::Beam, Vec3::ZERO, Vec3::new(10.0, 0.0, 0.0), 0.5, 1.0),
            elem(ElementType::Wall, Vec3::ZERO, Vec3::new(20.0, 9.0, 0.0), 0.5, 0.5),
            elem(ElementType::Floor, Vec3::ZERO, Vec3::new(30.0, 0.3, 40.0), 0.0, 0.0),
            elem(ElementType::Window, Vec3::new(5.0, 3.0, 0.0), Vec3::new(9.0, 6.0, 0.0), 2.0, 0.0),
            elem(ElementType::Door, Vec3::new(2.0, 0.0, 0.0), Vec3::new(4.0, 7.0, 0.0), 3.0, 0.0),
        ];
        let table = MaterialTable::default();
        let scene = build_scene_bvh(&elements, None, &table).expect("scene builds");

        // column 12 + beam 12 + wall 12 + floor 12 + window 2 + door 12 = 62
        assert_eq!(scene.triangles.len(), 62);
        assert_eq!(scene.materials.len(), 6);
        assert!(!scene.nodes.is_empty());

        // Triangles were reordered: every material index 0..6 still present.
        for m in 0..6u32 {
            assert!(scene.triangles.iter().any(|t| t.material_index() == m));
        }
    }

    #[test]
    fn scene_bvh_prefers_custom_mesh() {
        let mut e = elem(ElementType::Wall, Vec3::ZERO, Vec3::new(10.0, 9.0, 0.0), 0.5, 0.5);
        e.mesh = MeshData {
            vertices: vec![Vec3::ZERO, Vec3::X, Vec3::Y],
            faces: vec![[0, 1, 2], [9, 9, 9]], // one valid, one out of range (skipped)
        };
        let table = MaterialTable::default();
        let scene = build_scene_bvh(&[e], None, &table).unwrap();
        assert_eq!(scene.triangles.len(), 1);
    }

    #[test]
    fn scene_bvh_includes_terrain() {
        let elements = vec![elem(ElementType::Column, Vec3::ZERO, Vec3::new(0.0, 9.0, 0.0), 1.0, 1.0)];
        let terrain = TerrainMesh {
            vertices: vec![
                crate::domain::Vertex { position: Vec3::ZERO, ..Default::default() },
                crate::domain::Vertex { position: Vec3::X, ..Default::default() },
                crate::domain::Vertex { position: Vec3::Z, ..Default::default() },
            ],
            indices: vec![0, 1, 2],
            ..Default::default()
        };
        let table = MaterialTable::default();
        let scene = build_scene_bvh(&elements, Some((&terrain, "grass")), &table).unwrap();
        assert_eq!(scene.triangles.len(), 12 + 1);
        assert_eq!(scene.materials.len(), 2);
        // Terrain material: flagged for XZ projection, grass-coloured.
        let tm = scene.materials[1];
        assert_eq!(tm.tex_indices.w, 1.0);
        assert!((tm.albedo.y - 0.35).abs() < 1e-6);
    }

    #[test]
    fn empty_scene_returns_none() {
        assert!(build_scene_bvh(&[], None, &MaterialTable::default()).is_none());
        // Element type that generates no triangles → None.
        let e = elem(ElementType::Foundation, Vec3::ZERO, Vec3::ONE, 1.0, 1.0);
        assert!(build_scene_bvh(&[e], None, &MaterialTable::default()).is_none());
    }

    #[test]
    fn material_keyword_mapping() {
        assert_eq!(map_material_keyword("red Brick", ElementType::Wall), "polyhaven/brick_wall_006");
        assert_eq!(map_material_keyword("drywall", ElementType::Wall), "polyhaven/concrete_wall_008");
        assert_eq!(map_material_keyword("osb", ElementType::Wall), "polyhaven/wood_floor_deck");
        assert_eq!(map_material_keyword("", ElementType::Window), "glass");
        assert_eq!(map_material_keyword("", ElementType::Roof), "polyhaven/roof_slates_02");
        // Explicit polyhaven names pass through.
        let e = elem(ElementType::Wall, Vec3::ZERO, Vec3::ONE, 1.0, 1.0);
        let mut e2 = e.clone();
        e2.material = "polyhaven/custom_x".into();
        assert_eq!(resolve_path_tracer_material(&e2), "polyhaven/custom_x");
    }

    #[test]
    fn material_properties_match_keywords() {
        let mut e = elem(ElementType::Window, Vec3::ZERO, Vec3::ONE, 1.0, 1.0);
        e.material = "glass".into();
        let m = material_for_element(&e, &MaterialTable::default());
        assert!((m.properties.z - 1.5).abs() < 1e-6); // IOR
        assert!(m.properties.w > 0.8); // transmission

        let mut s = elem(ElementType::Beam, Vec3::ZERO, Vec3::ONE, 1.0, 1.0);
        s.material = "steel".into();
        let m = material_for_element(&s, &MaterialTable::default());
        assert!(m.properties.y > 0.8); // metallic
    }

    #[test]
    fn material_table_reads_map_json() {
        let dir = std::env::temp_dir().join("legicad_bvh_materials_test");
        std::fs::create_dir_all(&dir).unwrap();
        std::fs::write(
            dir.join("material_map.json"),
            r#"{
                "name_overrides": { "cedar": "polyhaven/wood_floor_deck" },
                "category_defaults": { "Walls": "polyhaven/concrete_wall_008" },
                "materials": {
                    "polyhaven/wood_floor_deck": { "folder": "wood" },
                    "polyhaven/concrete_wall_008": { "folder": "concrete" },
                    "not-polyhaven": { "folder": "ignored" }
                }
            }"#,
        )
        .unwrap();

        let table = MaterialTable::load(&dir);
        assert_eq!(table.texture_indices.len(), 2);
        // Indices follow sorted JSON key order (same as nlohmann::json's
        // default map): concrete_wall_008 = 0, wood_floor_deck = 4.
        assert_eq!(table.texture_index_for("polyhaven/concrete_wall_008", ElementType::Wall), 0);
        // Override path: "cedar" → wood_floor_deck's index.
        assert_eq!(table.texture_index_for("cedar", ElementType::Wall), 4);
        // Category fallback: "Walls" → concrete_wall_008.
        assert_eq!(table.texture_index_for("mystery", ElementType::Wall), 0);
        // Unknown with no category match → -1.
        assert_eq!(table.texture_index_for("mystery", ElementType::Connection), -1);

        std::fs::remove_dir_all(&dir).ok();
    }
}
