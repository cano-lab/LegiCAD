//! Slicing operations: wall / element / building → SliceResult.
//!
//! Ported from `slicer_2d.cpp:187-392`.
//!
//! M4 critical path: `slice_wall` at a horizontal plane (= floor plan)
//! and `generate_floor_plan` which iterates the building's parametric
//! walls. Section-cut + element-slicing logic ports along for free.

use crate::config::Config;
use crate::primitives::{Hatch2D, Line2D, Polyline2D, SliceResult};
use crate::slice_plane::{SlicePlane, SlicePlaneType};
use domain::{Building, ElementType, ParametricWall, StructuralElement, WallType};
use glam::{Vec2, Vec3};

/// Mid-grey used for as-built (existing) reference linework on the design
/// overlay. New-design walls render in the configured (black) wall colour.
const AS_BUILT_GREY: Vec3 = Vec3::new(0.5, 0.5, 0.5);

/// Slice a parametric wall against `plane`. Matches `Slicer2D::sliceWall`
/// (`slicer_2d.cpp:256`).
///
/// - **Horizontal plane** → wall outline polyline + hatch fill, but only
///   if the cut height is within the wall's vertical extent. Returns an
///   empty result otherwise.
/// - **Vertical plane** → section through wall layers (one rectangle
///   per layer + per-material hatch).
#[must_use]
pub fn slice_wall(
    wall: &ParametricWall,
    wall_type: &WallType,
    plane: &SlicePlane,
    config: &Config,
) -> SliceResult {
    let mut result = SliceResult {
        element_id: wall.id.clone(),
        element_type: "wall".to_string(),
        ..Default::default()
    };

    let wall_layer = config.layer_for("wall").clone();
    let total_thickness = wall_type.total_thickness();

    let wall_normal = wall.normal();

    if plane.plane_type == SlicePlaneType::Horizontal {
        // Plan view: outline + hatch, but only if plane intersects wall height.
        if plane.position < wall.base_height || plane.position > wall.top_height {
            return result;
        }

        let half_thick = total_thickness * 0.5;
        let p1 = wall.start_point + wall_normal * half_thick;
        let p2 = wall.end_point + wall_normal * half_thick;
        let p3 = wall.end_point - wall_normal * half_thick;
        let p4 = wall.start_point - wall_normal * half_thick;

        // As-built (existing) walls are reference linework: dashed, grey, and
        // unhatched, so a new design drawn on the same plan reads as the solid
        // black foreground. New-design walls keep the configured layer style.
        let is_as_built = wall.existing || wall.category == "as_built";

        let outline = Polyline2D {
            points: vec![p1, p2, p3, p4],
            closed: true,
            layer: if is_as_built {
                "A-WALL-EXST".to_string()
            } else {
                wall_layer.name.clone()
            },
            line_type: if is_as_built {
                "dashed".to_string()
            } else {
                wall_layer.line_type.clone()
            },
            line_weight: wall_layer.line_weight,
            color: if is_as_built {
                AS_BUILT_GREY
            } else {
                wall_layer.color
            },
        };

        result.polylines.push(outline.clone());

        if !is_as_built {
            let hatch_layer = config.layer_for("hatch");
            result.hatches.push(Hatch2D {
                boundaries: vec![outline],
                pattern: "ANSI31".to_string(),
                scale: 1.0,
                angle: 0.0,
                layer: hatch_layer.name.clone(),
                color: hatch_layer.color,
            });
        }
    } else {
        // Section view: stack of layer rectangles in the cut plane.
        let mut current_offset = -total_thickness * 0.5;
        for layer in &wall_type.layers {
            let x1 = current_offset;
            let x2 = current_offset + layer.thickness;
            let y1 = wall.base_height;
            let y2 = wall.top_height;

            let layer_outline = Polyline2D {
                points: vec![
                    Vec2::new(x1, y1),
                    Vec2::new(x2, y1),
                    Vec2::new(x2, y2),
                    Vec2::new(x1, y2),
                ],
                closed: true,
                layer: wall_layer.name.clone(),
                line_type: "continuous".to_string(),
                line_weight: 0.25,
                color: wall_layer.color,
            };

            let hatch = create_material_hatch(&layer_outline, &layer.material, config);
            if !hatch.pattern.is_empty() {
                result.hatches.push(hatch);
            }
            result.polylines.push(layer_outline);

            current_offset += layer.thickness;
        }
    }

    result
}

/// Slice a single `StructuralElement` (fallback for buildings without
/// parametric walls). Matches `Slicer2D::sliceElement` (`slicer_2d.cpp:187`).
///
/// Builds a box at the element's centroid with extents derived from its
/// type, then intersects every edge with the slice plane and connects
/// the intersection points in angular order around the centroid.
#[must_use]
pub fn slice_element(
    element: &StructuralElement,
    plane: &SlicePlane,
    config: &Config,
) -> SliceResult {
    let mut result = SliceResult {
        element_type: "element".to_string(),
        ..Default::default()
    };

    let center = (element.start + element.end) * 0.5;
    let length = (element.end - element.start).length();

    let extents = match element.element_type {
        ElementType::Column => Vec3::new(element.width * 0.5, length * 0.5, element.depth * 0.5),
        ElementType::Beam => Vec3::new(length * 0.5, element.depth * 0.5, element.width * 0.5),
        ElementType::Wall => Vec3::new(
            length * 0.5,
            (element.end.y - element.start.y) * 0.5,
            element.depth * 0.5,
        ),
        ElementType::Floor | ElementType::Roof => Vec3::new(
            (element.end.x - element.start.x).abs() * 0.5,
            element.depth * 0.5,
            (element.end.z - element.start.z).abs() * 0.5,
        ),
        // Same as Column for any other element type — matches the C++ default branch.
        _ => Vec3::new(
            element.width * 0.5,
            element.depth * 0.5,
            element.width * 0.5,
        ),
    };
    #[allow(clippy::match_same_arms)] // intentional: keep arms parallel to the C++ switch

    // The C++ rotates beams to align with their direction; we skip the
    // rotation for now (the kernel sets `transform = mat4(1.0f)` for all
    // non-beam types anyway, and the beam path is rarely exercised).
    let lines = slice_box(center, extents, plane);

    #[allow(clippy::match_same_arms)]
    let layer_key = match element.element_type {
        ElementType::Column => "column",
        ElementType::Beam => "beam",
        ElementType::Wall => "wall",
        ElementType::Floor => "floor",
        _ => "wall", // catch-all defaults to wall, kept distinct from the Wall arm for clarity
    };
    let layer_cfg = config.layer_for(layer_key);

    for mut line in lines {
        line.layer.clone_from(&layer_cfg.name);
        line.color = layer_cfg.color;
        line.line_weight = layer_cfg.line_weight;
        line.line_type.clone_from(&layer_cfg.line_type);
        result.lines.push(line);
    }
    result
}

/// Intersect every edge of an axis-aligned box with `plane` and connect
/// the intersection points (sorted by angle around their centroid) into
/// a polygon outline.
#[must_use]
pub fn slice_box(center: Vec3, extents: Vec3, plane: &SlicePlane) -> Vec<Line2D> {
    // 8 corners.
    let corners = [
        center + Vec3::new(-extents.x, -extents.y, -extents.z),
        center + Vec3::new(extents.x, -extents.y, -extents.z),
        center + Vec3::new(extents.x, extents.y, -extents.z),
        center + Vec3::new(-extents.x, extents.y, -extents.z),
        center + Vec3::new(-extents.x, -extents.y, extents.z),
        center + Vec3::new(extents.x, -extents.y, extents.z),
        center + Vec3::new(extents.x, extents.y, extents.z),
        center + Vec3::new(-extents.x, extents.y, extents.z),
    ];

    // 12 edges.
    let edges: [(usize, usize); 12] = [
        (0, 1),
        (1, 2),
        (2, 3),
        (3, 0), // bottom face
        (4, 5),
        (5, 6),
        (6, 7),
        (7, 4), // top face
        (0, 4),
        (1, 5),
        (2, 6),
        (3, 7), // vertical edges
    ];

    let mut intersections: Vec<Vec2> = Vec::with_capacity(12);
    for (i, j) in edges {
        if let Some(pt) =
            crate::slice_plane::intersect_line_with_plane(corners[i], corners[j], plane)
        {
            intersections.push(pt);
        }
    }

    if intersections.len() < 2 {
        return Vec::new();
    }

    // Sort by angle around centroid for a clean polygon perimeter.
    #[allow(clippy::cast_precision_loss)]
    let centroid = intersections.iter().copied().sum::<Vec2>() / intersections.len() as f32;
    intersections.sort_by(|a, b| {
        let aa = (a.y - centroid.y).atan2(a.x - centroid.x);
        let bb = (b.y - centroid.y).atan2(b.x - centroid.x);
        aa.partial_cmp(&bb).unwrap_or(std::cmp::Ordering::Equal)
    });

    let mut lines = Vec::with_capacity(intersections.len());
    for i in 0..intersections.len() {
        let next = (i + 1) % intersections.len();
        lines.push(Line2D {
            start: intersections[i],
            end: intersections[next],
            layer: "0".to_string(),
            line_type: "continuous".to_string(),
            line_weight: 0.35,
            color: Vec3::ZERO,
        });
    }
    lines
}

/// Generate a floor plan by cutting at `cut_height` (in the building's
/// vertical units). Matches `Slicer2D::generateFloorPlan`
/// (`slicer_2d.cpp:344`):
/// - Prefers parametric walls (true 2D representation).
/// - Falls back to structural elements only when no parametric walls exist.
#[must_use]
pub fn generate_floor_plan(building: &Building, cut_height: f32, config: &Config) -> SliceResult {
    let plane = SlicePlane::horizontal(cut_height, "Floor Plan");
    let mut result = SliceResult::default();

    if building.parametric_walls.is_empty() {
        for elem in &building.elements {
            result.merge(slice_element(elem, &plane, config));
        }
    } else {
        for wall in &building.parametric_walls {
            let idx = wall.wall_type_index as usize;
            if idx < building.wall_types.len() {
                result.merge(slice_wall(wall, &building.wall_types[idx], &plane, config));
            }
        }
    }

    result
}

/// Generate a section view at `plane`. Iterates all structural elements
/// AND all parametric walls (the C++ sections both at once;
/// `slicer_2d.cpp:368`).
#[must_use]
pub fn generate_section(building: &Building, plane: &SlicePlane, config: &Config) -> SliceResult {
    let mut result = SliceResult::default();
    for elem in &building.elements {
        result.merge(slice_element(elem, plane, config));
    }
    for wall in &building.parametric_walls {
        let idx = wall.wall_type_index as usize;
        if idx < building.wall_types.len() {
            result.merge(slice_wall(wall, &building.wall_types[idx], plane, config));
        }
    }
    result
}

/// Dispatch on plane type: horizontal → floor plan, else → section.
#[must_use]
pub fn slice_building(building: &Building, plane: &SlicePlane, config: &Config) -> SliceResult {
    if plane.plane_type == SlicePlaneType::Horizontal {
        generate_floor_plan(building, plane.position, config)
    } else {
        generate_section(building, plane, config)
    }
}

/// Helper: build a hatch from a boundary + material lookup.
/// Matches `Slicer2D::createMaterialHatch` (`slicer_2d.cpp:465`).
#[must_use]
#[allow(clippy::needless_pass_by_value)] // shape mirrors the C++ overload
pub fn create_material_hatch(boundary: &Polyline2D, material: &str, config: &Config) -> Hatch2D {
    let hatch_layer = config.layer_for("hatch");
    let spec = config.hatch_for(material);
    Hatch2D {
        boundaries: vec![boundary.clone()],
        pattern: spec.pattern,
        scale: spec.scale,
        angle: 0.0,
        layer: hatch_layer.name.clone(),
        color: hatch_layer.color,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use domain::WallLayer;

    fn straight_wall() -> ParametricWall {
        ParametricWall {
            id: "w0".into(),
            start_point: Vec2::new(0.0, 0.0),
            end_point: Vec2::new(5000.0, 0.0),
            base_height: 0.0,
            top_height: 3000.0,
            wall_type_index: 0,
            ..Default::default()
        }
    }

    fn simple_wall_type() -> WallType {
        WallType {
            id: "wt0".into(),
            name: "Test".into(),
            layers: vec![WallLayer {
                name: "structure".into(),
                thickness: 150.0,
                ..Default::default()
            }],
            ..Default::default()
        }
    }

    #[test]
    fn horizontal_slice_below_wall_returns_empty() {
        let plane = SlicePlane::horizontal(-100.0, "Below");
        let r = slice_wall(
            &straight_wall(),
            &simple_wall_type(),
            &plane,
            &Config::with_defaults(),
        );
        assert!(r.is_empty());
    }

    #[test]
    fn horizontal_slice_above_wall_returns_empty() {
        let plane = SlicePlane::horizontal(5000.0, "Above");
        let r = slice_wall(
            &straight_wall(),
            &simple_wall_type(),
            &plane,
            &Config::with_defaults(),
        );
        assert!(r.is_empty());
    }

    #[test]
    fn horizontal_slice_at_wall_height_produces_outline_and_hatch() {
        let plane = SlicePlane::horizontal(1500.0, "Plan");
        let r = slice_wall(
            &straight_wall(),
            &simple_wall_type(),
            &plane,
            &Config::with_defaults(),
        );
        assert_eq!(r.polylines.len(), 1);
        assert_eq!(r.polylines[0].points.len(), 4);
        assert_eq!(r.polylines[0].layer, "A-WALL");
        assert!(r.polylines[0].closed);
        assert_eq!(r.hatches.len(), 1);
        assert_eq!(r.hatches[0].pattern, "ANSI31");
    }

    #[test]
    fn as_built_wall_is_dashed_grey_and_unhatched() {
        let mut wall = straight_wall();
        wall.category = "as_built".into();
        let plane = SlicePlane::horizontal(1500.0, "Plan");
        let r = slice_wall(&wall, &simple_wall_type(), &plane, &Config::with_defaults());

        assert_eq!(r.polylines.len(), 1);
        let outline = &r.polylines[0];
        assert_eq!(outline.line_type, "dashed", "as-built outline should be dashed");
        assert_eq!(outline.layer, "A-WALL-EXST");
        assert_eq!(outline.color, AS_BUILT_GREY);
        assert!(r.hatches.is_empty(), "as-built walls carry no fill hatch");
    }

    #[test]
    fn existing_flag_alone_styles_wall_as_overlay() {
        // The renovation `existing` flag styles a wall dashed/grey even when
        // its category is a normal construction type (not "as_built").
        let mut wall = straight_wall();
        wall.category = "exterior".into();
        wall.existing = true;
        let plane = SlicePlane::horizontal(1500.0, "Plan");
        let r = slice_wall(&wall, &simple_wall_type(), &plane, &Config::with_defaults());
        assert_eq!(r.polylines[0].line_type, "dashed");
        assert_eq!(r.polylines[0].color, AS_BUILT_GREY);
        assert!(r.hatches.is_empty());
    }

    #[test]
    fn new_design_wall_keeps_solid_hatched_style() {
        // No category → new design: solid layer style + hatch (regression).
        let plane = SlicePlane::horizontal(1500.0, "Plan");
        let r = slice_wall(&straight_wall(), &simple_wall_type(), &plane, &Config::with_defaults());
        assert_eq!(r.polylines.len(), 1);
        assert_ne!(r.polylines[0].line_type, "dashed");
        assert_eq!(r.polylines[0].layer, "A-WALL");
        assert_eq!(r.hatches.len(), 1);
    }

    #[test]
    fn vertical_section_emits_one_polyline_per_layer() {
        let mut wt = simple_wall_type();
        wt.layers.push(WallLayer {
            name: "insulation".into(),
            thickness: 90.0,
            material: "fiberglass".into(),
            ..Default::default()
        });
        wt.layers.push(WallLayer {
            name: "drywall".into(),
            thickness: 12.0,
            material: "drywall".into(),
            ..Default::default()
        });
        let plane = SlicePlane::section_ns(0.0, "Section");
        let r = slice_wall(&straight_wall(), &wt, &plane, &Config::with_defaults());
        assert_eq!(r.polylines.len(), 3, "one polyline per layer");
        // All polylines are 4-point rectangles.
        for poly in &r.polylines {
            assert_eq!(poly.points.len(), 4);
            assert!(poly.closed);
        }
    }

    #[test]
    fn generate_floor_plan_iterates_parametric_walls() {
        let mut building = Building::default();
        building.wall_types.push(simple_wall_type());
        building.parametric_walls.push(straight_wall());
        building.parametric_walls.push(ParametricWall {
            id: "w1".into(),
            start_point: Vec2::new(5000.0, 0.0),
            end_point: Vec2::new(5000.0, 3000.0),
            base_height: 0.0,
            top_height: 3000.0,
            wall_type_index: 0,
            ..Default::default()
        });

        let r = generate_floor_plan(&building, 1500.0, &Config::with_defaults());
        assert_eq!(r.polylines.len(), 2);
        assert_eq!(r.hatches.len(), 2);
    }

    #[test]
    fn generate_floor_plan_falls_back_to_elements_when_no_walls() {
        let mut building = Building::default();
        building.elements.push(StructuralElement {
            element_type: ElementType::Wall,
            start: Vec3::ZERO,
            end: Vec3::new(5000.0, 3000.0, 0.0),
            width: 150.0,
            depth: 150.0,
            ..Default::default()
        });
        let r = generate_floor_plan(&building, 1500.0, &Config::with_defaults());
        // Element-slice path emits lines, not polylines.
        assert!(r.lines.iter().all(|l| l.layer == "A-WALL"));
    }
}
