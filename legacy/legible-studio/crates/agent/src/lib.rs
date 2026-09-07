//! Agent/harness-facing OBC design runtime.
//!
//! This crate is the shared service layer for both HTTP and MCP adapters. It
//! keeps LLM-facing operations typed and deterministic: solve/template,
//! validate, suggest fixes, apply constrained patches, iterate, and export.

mod layout_quality;
mod service;

pub use layout_quality::*;
pub use service::*;
