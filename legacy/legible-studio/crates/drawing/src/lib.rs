//! 2D drawing pipeline — merged port of `slicer_2d` and `plan_generator`.
//!
//! See port plan §8 Q1 for the merge rationale.
//!
//! Module layout:
//! - `primitives` — Line2D, Polyline2D, Arc2D, Circle2D, Text2D,
//!   Dimension2D, Hatch2D, SliceResult.
//! - `slice_plane` — SlicePlane + 3D→2D projection math.
//! - `config` — Layer + material-hatch defaults.
//! - `slice` — element / wall / building slicing into SliceResults.
//! - `svg` — SVG emission.
//! - `dxf` — DXF emission.

pub mod annotate;
pub mod config;
pub mod detail;
pub mod dimensions;
pub mod dxf;
pub mod elevation_sheet;
pub mod footing_detail;
pub mod foundation_plan;
pub mod framing_plan;
pub mod obc_notes;
pub mod primitives;
pub mod roof;
pub mod room_labels;
pub mod schedule;
pub mod legend;
pub mod section_marker;
pub mod section_sheet;
pub mod sheet;
pub mod site_plan;
pub mod slice;
pub mod stair;
pub mod stair_section;
pub mod slice_plane;
pub mod svg;
pub mod title_block;

pub use annotate::{
    AnnotationSet, Dimension, GridLine, Leader, PlanType, RoofAnnotation, RoofAnnotationType,
    Symbol, SymbolType, TextLabel,
};
pub use config::{Config, HatchSpec, LayerConfig};
pub use detail::{
    LayerDetail, WallSectionDetail, detail_to_slice_result, generate_wall_detail,
    wall_detail_to_svg,
};
pub use dimensions::{
    LinearDim, chain_dims, overall_envelope_dims, render_horizontal as render_horizontal_dim,
    render_vertical as render_vertical_dim, room_interior_dims,
};
pub use elevation_sheet::{
    Direction as ElevationDirection, ElevationInput, ElevationOpeningInput, ElevationWallInput,
    generate_elevation_dxf, generate_elevation_sheet_svg, sheet_name as elevation_sheet_name,
};
pub use footing_detail::{
    FootingSpec, generate_footing_detail, generate_footing_detail_svg,
};
pub use foundation_plan::{
    generate_foundation_plan, generate_foundation_plan_svg,
};
pub use framing_plan::{
    JoistSpec, generate_framing_plan, generate_framing_plan_svg,
};
pub use obc_notes::{generate_obc_notes_block, notes_block_size_mm};
pub use primitives::{
    Arc2D, Circle2D, Dimension2D, Hatch2D, Line2D, Point2D, Polyline2D, SliceResult, Text2D,
};
pub use room_labels::{RoomLabelInput, render_room_label, render_room_labels};
pub use schedule::{
    ScheduleEntry, door_type_for_width, format_dim_mm, schedule_to_svg, window_type_for_width,
};
pub use section_marker::generate_section_marker;
pub use section_sheet::{
    AssemblyCallout, CutDirection, SectionCut, SectionInput, SectionWallInput, ViewDirection,
    default_cut, generate_section_sheet_svg,
};
pub use legend::generate_symbols_legend_svg;
pub use sheet::{
    FreePlacement, PaperSize, Placement, SheetDrawing, compose_freeform, compose_multi,
    compose_sheet,
};
pub use roof::{RoofPlan, RoofType, generate_roof_plan_svg};
pub use site_plan::{Contour, SitePlan, StreetClass, StreetWay, generate_site_plan_svg};
pub use stair::{StairPlan, render_stair_symbol};
pub use stair_section::{StairSectionSpec, generate_stair_section, generate_stair_section_svg};
pub mod skeleton;
pub use slice::{
    create_material_hatch, generate_floor_plan, generate_section, slice_box, slice_building,
    slice_element, slice_wall,
};
pub use slice_plane::{SlicePlane, SlicePlaneType, intersect_line_with_plane, project_to_2d};
pub use dxf::export_to_dxf;
pub use svg::{
    color_to_svg, cpp_double, export_to_svg, export_to_svg_padded, svg_arc, svg_circle, svg_hatch,
    svg_line, svg_polyline, svg_text,
};
pub use title_block::{
    DrawingInfo, DrawingType, ProjectInfo, TITLE_BLOCK_H, TITLE_BLOCK_W, drawing_info_for,
    generate_title_block, title_block_box,
};
