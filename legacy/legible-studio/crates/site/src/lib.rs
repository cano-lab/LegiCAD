//! Site / geospatial layer for Legible Studio.
//!
//! Native, dependency-light geo primitives: WGS84 ↔ UTM (Ontario zone 17N
//! today, with a path to other zones) and the slippy-map tile schema
//! (lat/lon ↔ tile XYZ at zoom Z). These two are the foundation the OSM
//! tile fetcher (increment 2), the native map widget (increment 3), and
//! the LiDAR backend (increments 4–6) build on.

pub mod aselevation;
pub mod aswall;
pub mod cloud;
pub mod coord;
pub mod downloader;
pub mod footprint;
pub mod geotiff;
pub mod mesh;
pub mod ontario;
pub mod overpass;
pub mod tile;
pub mod tilefetch;

pub use aselevation::{
    AsBuiltElevation, AsBuiltOpening, ElevationError, ElevationParams, Facade,
    project_all_elevations, project_elevation,
};
pub use aswall::{
    AsBuiltError, AsBuiltResult, AsBuiltWall, WallDetectParams, detect_walls,
};
pub use cloud::parse_xyz;
pub use coord::{LatLon, UtmCoord, utm17_from_wgs84, wgs84_from_utm17};
pub use footprint::{
    FootprintError, FootprintResult, extract_footprint,
};
pub use geotiff::{
    ElevationRaster, GeoAffine, GeoTiffError, GeoTiffInfo, read_elevation, read_info,
};
pub use downloader::{
    DownloadError, KNOWN_PACKAGES, LidarDownloader, PackageDataType, PackageInfo,
    package_numbers_for,
};
pub use mesh::{
    DEFAULT_GRID_N, MeshVertex, StitchError, StitchResult, TerrainMesh, TerrainMeshEnvelope,
    stitch, to_terrain_json,
};
pub use overpass::{OverpassClient, OverpassError, RoadClass, RoadWay, parse_overpass_json};
pub use ontario::{
    ClassifiedTiles, KNOWN_REGIONS, LocalTileIndex, OntarioTile, PACKAGE_BASE_URL,
    PackageResolver, StaticPackageResolver, TILE_SIDE_M, parse_tile_prefix, region_for,
    tiles_for_utm_bbox, tiles_for_wgs84_bbox,
};
pub use tile::{
    TILE_SIZE_PX, TileCoord, lat_lon_to_tile, lat_lon_to_tile_f64,
    lat_lon_to_world_pixel, tile_to_lat_lon, tile_to_pixel, world_pixel_to_lat_lon,
};
pub use tilefetch::{FetchError, TileFetcher, TileImage, decode_png_to_rgba};
