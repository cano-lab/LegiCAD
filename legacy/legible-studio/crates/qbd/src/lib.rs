//! QBD orchestration — converts an `archgeometry::SchemaDocument` into a
//! `domain::Building`, runs floor-plan generation with door/window
//! enhancements, and produces final permit-set SVG/DXF output.
//!
//! Port of `ArchEngine_kernel/{include,src}/qbd_interface.{hpp,cpp}`.
//! Per port plan §8 — the legacy custom JSON parser is collapsed; this
//! crate consumes `SchemaDocument` from `archgeometry` directly. The
//! per-layer wall CSG mesh path is also skipped (3D-render only, not
//! needed for permit drawings).

pub mod compliance_report;
pub mod convert;
pub mod documentation;
pub mod egress_feedback;
pub mod floor_plan;
pub mod ifc;
pub mod raster;
pub mod schedule;
pub mod terrain;
pub mod validation;
pub mod wall_types;

pub use compliance_report::compliance_report_to_svg;
pub use convert::{layout_to_building, wall_type_for_wall, walls_to_parametric};
pub use documentation::{
    CatalogDrawing, Documentation, DocumentationOptions, PdfError, drawing_catalog,
    floor_plan_sheet, generate_documentation, generate_documentation_for_project,
    generate_documentation_for_project_with_options, generate_documentation_with_options,
    generate_documentation_with_validation, generate_documentation_with_validation_and_options,
    generate_documentation_with_validation_for_project, plans_sheet, svg_to_pdf,
    svgs_to_pdf,
};
pub use egress_feedback::{EgressFix, EgressIssue, analyze};
pub use floor_plan::generate_floor_plan_with_openings;
pub use raster::{RasterError, Rasterizer, svg_to_png};
pub use schedule::{door_entries, window_entries};
pub use validation::{ValidationResult, validate_layout, validate_layout_with_part3, validate_wall};
pub use wall_types::{exterior_2x6_r21, for_category, interior_2x4, wet_2x6};
