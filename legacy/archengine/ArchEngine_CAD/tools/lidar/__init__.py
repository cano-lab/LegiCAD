"""
LiDAR Processing Library
========================
Extract and process elevation data from GeoTIFF LiDAR tiles.

This library provides:
- GeoTIFF tile discovery and metadata extraction
- Property-based elevation extraction
- Multi-tile merging
- Export to various formats (ArchEngine, Revit CSV, OBJ, etc.)

Usage:
    from tools.lidar import LidarExtractor, PropertyBounds

    extractor = LidarExtractor()
    extractor.scan_folder("/path/to/lidar/tiles")

    bounds = PropertyBounds(lat=46.2615, lng=-80.4548, width_m=100, height_m=100)
    tiles = extractor.find_overlapping_tiles(bounds)

    elevation = extractor.extract_elevation(tiles, bounds)
    extractor.export_archengine(elevation, "terrain.json")
"""

from .extractor import (
    LidarExtractor,
    PropertyBounds,
    TileInfo,
    ElevationData,
)

from .transform import (
    UtmTransformer,
    wgs84_to_utm,
    utm_to_wgs84,
)

from .geotiff import (
    read_geotiff_info,
    read_geotiff_elevation,
    parse_ontario_filename,
)

from .downloader import (
    LidarDownloader,
    PackageInfo,
    find_available_regions,
    get_region_bounds,
)

from .ontario_vectors import (
    OntarioVectorDownloader,
    VectorDataset,
    VectorFeature,
    download_ontario_site_context,
)

__version__ = "0.1.0"
__all__ = [
    # Main classes
    "LidarExtractor",
    "PropertyBounds",
    "TileInfo",
    "ElevationData",
    # Transforms
    "UtmTransformer",
    "wgs84_to_utm",
    "utm_to_wgs84",
    # GeoTIFF utilities
    "read_geotiff_info",
    "read_geotiff_elevation",
    "parse_ontario_filename",
    # Downloader
    "LidarDownloader",
    "PackageInfo",
    "find_available_regions",
    "get_region_bounds",
]
