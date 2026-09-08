//! Schema parser + canonical geometry generators.
//!
//! Port of `Shared/ArchGeometry/`. See `docs/VULKAN_KERNEL_PORT_PLAN.md` §2.

pub mod dump_hash;
pub mod floor_geometry;
pub mod generate;
pub mod geometry_types;
pub mod opening_geometry;
pub mod roof_geometry;
pub mod room_geometry;
pub mod schema_parser;
pub mod schema_types;
pub mod wall_geometry;
pub mod wire;

pub use generate::generate_from_schema;
pub use geometry_types::{
    Arc2D, BuildingGeometry, DoorGeometry, FloorGeometry, Geometry2D, Line2D, Mesh3D,
    OpeningCutout, Point2D, Polygon2D, RoofGeometry, RoomBoundary, Text2D, Triangle, Vertex3D,
    WallGeometry, WindowGeometry,
};
pub use schema_parser::{ParseError, parse_file, parse_json};
pub use schema_types::{
    QBDAnswers, RoofRidge, RoofSurface, RoomBounds, SchemaContour, SchemaDetector, SchemaDocument,
    SchemaDoor, SchemaElectrical, SchemaFloor, SchemaHeader, SchemaLevel, SchemaRoof, SchemaRoom,
    SchemaSite, SchemaStair, SchemaStreet, SchemaWall, SchemaWindow, WallLayer, WallType,
};
