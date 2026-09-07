//! Ontario Building Code: joist/stud/header/rafter span tables,
//! thermal R-value requirements by climate zone, compliance reports,
//! and Part-9 window requirements (natural light + egress).
//!
//! Port of `ArchEngine_kernel/{include,src}/obc_engine.{hpp,cpp}`.
//! Table files (JSON) live at `OBC_Library/tables/` — load on init.

pub mod detectors;
pub mod electrical;
pub mod engine;
pub mod format;
pub mod headers;
pub mod part3;
pub mod report;
pub mod stairs;
pub mod tables;
pub mod windows;
pub mod zoning;

pub use engine::{InitError, OBCEngine, sb12_minimum_r};
pub use format::{cpp_float, cpp_int};
pub use part3::{FloorInput, Part3Engine, RoomInput};
pub use report::{ComplianceCheck, ComplianceReport, ComplianceStatus};
pub use tables::{
    HeaderEntry, SpanEntry, SpanTable, StudEntry, StudTable, load_header_tables_from_json,
    load_joist_tables_from_json, load_rafter_tables_from_json, load_stud_tables_from_json,
    make_table_key, parse_span_string,
};
