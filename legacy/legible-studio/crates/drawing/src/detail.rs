//! Wall section details — per-layer drawings showing the assembly
//! recipe (thickness, material, hatch pattern, fastener notes).
//!
//! Ported from `slicer_2d.cpp:398-463` (`Slicer2D::generateWallDetail`)
//! and `:802-817` (`Slicer2D::wallDetailToSVG`).

use crate::config::Config;
use crate::primitives::{Dimension2D, Hatch2D, Polyline2D, SliceResult, Text2D};
use crate::slice::create_material_hatch;
use crate::svg::export_to_svg;
use domain::WallType;
use glam::Vec2;

/// Per-layer detail block.
#[derive(Debug, Clone, PartialEq, Default)]
pub struct LayerDetail {
    pub name: String,
    pub material: String,
    pub thickness: f32,
    pub outline: Polyline2D,
    pub hatch: Hatch2D,
    pub labels: Vec<Text2D>,
}

/// Detail view of a wall assembly section.
#[derive(Debug, Clone, PartialEq, Default)]
pub struct WallSectionDetail {
    pub wall_type_id: String,
    pub wall_type_name: String,
    pub total_thickness: f32,
    /// Typically 1.5 (= 1-1/2" = 1'-0"). Multiplied into the SVG scale.
    pub detail_scale: f32,
    pub layers: Vec<LayerDetail>,
    pub fastener_notes: Vec<Text2D>,
    pub dimensions: Vec<Dimension2D>,
}

/// Generate the section detail for `wall_type` at a given wall height
/// (in feet; matches the C++ default of 9.0). Per `slicer_2d.cpp:398`.
#[must_use]
pub fn generate_wall_detail(
    wall_type: &WallType,
    wall_height_ft: f32,
    config: &Config,
) -> WallSectionDetail {
    let total = wall_type.total_thickness();
    let mut detail = WallSectionDetail {
        wall_type_id: wall_type.id.clone(),
        wall_type_name: wall_type.name.clone(),
        total_thickness: total,
        detail_scale: 1.5, // 1-1/2" = 1'-0"
        layers: Vec::with_capacity(wall_type.layers.len()),
        fastener_notes: Vec::new(),
        dimensions: Vec::new(),
    };

    let mut current_x = 0.0_f32;
    for layer in &wall_type.layers {
        // Per-layer outline = rectangle stacked horizontally from left to right.
        let outline = Polyline2D {
            points: vec![
                Vec2::new(current_x, 0.0),
                Vec2::new(current_x + layer.thickness, 0.0),
                Vec2::new(current_x + layer.thickness, wall_height_ft),
                Vec2::new(current_x, wall_height_ft),
            ],
            closed: true,
            layer: "A-DETL".into(),
            line_type: "continuous".into(),
            line_weight: 0.25,
            color: glam::Vec3::ZERO,
        };

        let hatch = create_material_hatch(&outline, &layer.material, config);

        let layer_label = Text2D {
            position: Vec2::new(current_x + layer.thickness * 0.5, wall_height_ft + 0.5),
            text: layer.name.clone(),
            height: 0.1,
            rotation: 0.0,
            layer: "A-NOTE".into(),
            style: "Standard".into(),
            justification: "center".into(),
            color: glam::Vec3::ZERO,
        };
        // Thickness annotation in inches below the layer (matches C++
        // `slicer_2d.cpp:438-444` — thickness × 12).
        let thickness_note = Text2D {
            position: Vec2::new(current_x + layer.thickness * 0.5, -0.3),
            text: format!("{:.2}\"", layer.thickness * 12.0),
            height: 0.08,
            rotation: 0.0,
            layer: "A-DIMS".into(),
            style: "Standard".into(),
            justification: "center".into(),
            color: glam::Vec3::ZERO,
        };

        detail.layers.push(LayerDetail {
            name: layer.name.clone(),
            material: layer.material.clone(),
            thickness: layer.thickness,
            outline,
            hatch,
            labels: vec![layer_label, thickness_note],
        });

        current_x += layer.thickness;
    }

    // Overall thickness dimension along the bottom edge.
    detail.dimensions.push(Dimension2D {
        point1: Vec2::new(0.0, -0.5),
        point2: Vec2::new(total, -0.5),
        text_position: Vec2::new(total * 0.5, -0.7),
        text: format!("{:.2}\" TOTAL", total * 12.0),
        text_height: 0.1,
        layer: "A-DIMS".into(),
        style: "Standard".into(),
    });

    detail
}

/// Flatten the detail into a `SliceResult` ready for SVG export.
#[must_use]
pub fn detail_to_slice_result(detail: &WallSectionDetail) -> SliceResult {
    let mut result = SliceResult::default();
    for layer in &detail.layers {
        result.polylines.push(layer.outline.clone());
        if !layer.hatch.pattern.is_empty() {
            result.hatches.push(layer.hatch.clone());
        }
        for label in &layer.labels {
            result.annotations.push(label.clone());
        }
    }
    for note in &detail.fastener_notes {
        result.annotations.push(note.clone());
    }
    result
}

/// Render a wall detail to SVG. The C++ multiplies the user-supplied
/// scale by `detail.detailScale * 12` so the detail blows up to actual
/// size on the sheet.
#[must_use]
pub fn wall_detail_to_svg(detail: &WallSectionDetail, scale: f32) -> String {
    let result = detail_to_slice_result(detail);
    export_to_svg(&result, scale * detail.detail_scale * 12.0)
}

#[cfg(test)]
mod tests {
    use super::*;
    use domain::{LayerFunction, WallLayer};

    fn three_layer_wall_type() -> WallType {
        WallType {
            id: "test".into(),
            name: "Test 3-layer".into(),
            layers: vec![
                WallLayer {
                    name: "Drywall".into(),
                    material: "gypsum".into(),
                    function: LayerFunction::InteriorFinish,
                    thickness: 0.04,
                    ..Default::default()
                },
                WallLayer {
                    name: "Stud + Insulation".into(),
                    material: "fiberglass".into(),
                    function: LayerFunction::Structure,
                    thickness: 0.46,
                    ..Default::default()
                },
                WallLayer {
                    name: "Siding".into(),
                    material: "wood".into(),
                    function: LayerFunction::ExteriorFinish,
                    thickness: 0.06,
                    ..Default::default()
                },
            ],
            ..Default::default()
        }
    }

    #[test]
    fn generate_emits_one_layer_block_per_input_layer() {
        let wt = three_layer_wall_type();
        let detail = generate_wall_detail(&wt, 9.0, &Config::with_defaults());
        assert_eq!(detail.layers.len(), 3);
        assert_eq!(detail.wall_type_id, "test");
        assert!((detail.total_thickness - 0.56).abs() < 1e-6);
        // Detail scale is 1.5 by default (matches C++).
        assert!((detail.detail_scale - 1.5).abs() < 1e-6);
    }

    #[test]
    fn layer_outlines_stack_horizontally_without_overlap() {
        let wt = three_layer_wall_type();
        let detail = generate_wall_detail(&wt, 9.0, &Config::with_defaults());
        // Each outline is a 4-point rectangle. X starts at 0, 0.04, 0.5.
        assert_eq!(detail.layers[0].outline.points[0].x, 0.0);
        assert!((detail.layers[1].outline.points[0].x - 0.04).abs() < 1e-6);
        assert!((detail.layers[2].outline.points[0].x - 0.5).abs() < 1e-6);
    }

    #[test]
    fn each_layer_carries_two_labels_name_and_thickness() {
        let wt = three_layer_wall_type();
        let detail = generate_wall_detail(&wt, 9.0, &Config::with_defaults());
        for layer in &detail.layers {
            assert_eq!(layer.labels.len(), 2);
            assert_eq!(layer.labels[0].text, layer.name);
            // Second label is "<thickness * 12>\""
            assert!(layer.labels[1].text.ends_with('\"'));
        }
    }

    #[test]
    fn overall_dimension_text_includes_total_in_inches() {
        let wt = three_layer_wall_type();
        let detail = generate_wall_detail(&wt, 9.0, &Config::with_defaults());
        assert_eq!(detail.dimensions.len(), 1);
        // 0.56 ft × 12 = 6.72 in
        assert!(detail.dimensions[0].text.contains("6.72"));
        assert!(detail.dimensions[0].text.contains("TOTAL"));
    }

    #[test]
    fn detail_to_slice_result_carries_polylines_hatches_and_labels() {
        let wt = three_layer_wall_type();
        let detail = generate_wall_detail(&wt, 9.0, &Config::with_defaults());
        let result = detail_to_slice_result(&detail);
        assert_eq!(result.polylines.len(), 3);
        // gypsum / fiberglass / wood — all have non-empty hatch patterns.
        assert_eq!(result.hatches.len(), 3);
        // 2 labels per layer × 3 layers = 6.
        assert_eq!(result.annotations.len(), 6);
    }

    #[test]
    fn wall_detail_to_svg_produces_valid_svg() {
        let wt = three_layer_wall_type();
        let detail = generate_wall_detail(&wt, 9.0, &Config::with_defaults());
        let svg = wall_detail_to_svg(&detail, 1.0);
        assert!(svg.starts_with("<?xml version=\"1.0\""));
        assert!(svg.contains("<svg"));
        assert!(svg.ends_with("</svg>\n"));
    }
}
