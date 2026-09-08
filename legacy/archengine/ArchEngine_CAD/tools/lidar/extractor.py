"""
LiDAR Extractor - Main API for elevation data extraction.

This is the primary interface for the lidar library.
"""

import os
import json
import math
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Tuple, Callable

import numpy as np

from .geotiff import (
    read_geotiff_info,
    read_geotiff_elevation,
    parse_ontario_filename,
    GeoTiffInfo,
    TileCoordinate,
)
from .transform import UtmTransformer, meters_to_degrees

# Optional imports
try:
    from pyproj import Transformer
    HAS_PYPROJ = True
except ImportError:
    HAS_PYPROJ = False

try:
    import rasterio
    HAS_RASTERIO = True
except ImportError:
    HAS_RASTERIO = False


@dataclass
class PropertyBounds:
    """
    Property bounds for extraction.

    Can be specified as:
    - Center point + dimensions
    - Min/max lat/lng bounds
    """
    lat: float = 0.0
    lng: float = 0.0
    width_m: float = 100.0
    height_m: float = 100.0

    # Alternative: explicit bounds
    lat_min: Optional[float] = None
    lat_max: Optional[float] = None
    lng_min: Optional[float] = None
    lng_max: Optional[float] = None

    def __post_init__(self):
        """Calculate bounds from center + dimensions if not provided."""
        if self.lat_min is None:
            lat_delta, lng_delta = meters_to_degrees(self.width_m / 2, self.lat)
            _, lng_delta_h = meters_to_degrees(self.height_m / 2, self.lat)

            self.lat_min = self.lat - lat_delta
            self.lat_max = self.lat + lat_delta
            self.lng_min = self.lng - lng_delta
            self.lng_max = self.lng + lng_delta

    @classmethod
    def from_bounds(cls, lat_min: float, lat_max: float, lng_min: float, lng_max: float) -> 'PropertyBounds':
        """Create from explicit bounds."""
        return cls(
            lat=(lat_min + lat_max) / 2,
            lng=(lng_min + lng_max) / 2,
            lat_min=lat_min,
            lat_max=lat_max,
            lng_min=lng_min,
            lng_max=lng_max,
        )

    def to_tuple(self) -> Tuple[float, float, float, float]:
        """Return (lat_min, lat_max, lng_min, lng_max)."""
        return (self.lat_min, self.lat_max, self.lng_min, self.lng_max)

    def to_utm(self, zone: int = 17) -> Tuple[float, float, float, float]:
        """
        Convert to UTM bounds.

        Returns:
            (min_x, max_x, min_y, max_y) in meters
        """
        transformer = UtmTransformer(zone, northern=True)
        min_x, min_y = transformer.wgs84_to_utm(self.lat_min, self.lng_min)
        max_x, max_y = transformer.wgs84_to_utm(self.lat_max, self.lng_max)

        return (min(min_x, max_x), max(min_x, max_x),
                min(min_y, max_y), max(min_y, max_y))


@dataclass
class TileInfo:
    """Information about a GeoTIFF tile."""
    path: str
    name: str
    crs: str
    resolution: float
    width: int
    height: int

    # Bounds in native CRS (UTM)
    bounds_native: Tuple[float, float, float, float]  # left, bottom, right, top

    # Bounds in WGS84
    lat_min: float = 0.0
    lat_max: float = 0.0
    lng_min: float = 0.0
    lng_max: float = 0.0

    # Parsed from filename (if Ontario format)
    tile_coord: Optional[TileCoordinate] = None

    def overlaps(self, bounds: PropertyBounds) -> bool:
        """Check if this tile overlaps with property bounds."""
        return (
            self.lat_min <= bounds.lat_max and
            self.lat_max >= bounds.lat_min and
            self.lng_min <= bounds.lng_max and
            self.lng_max >= bounds.lng_min
        )


@dataclass
class ElevationPoint:
    """A single elevation point."""
    lat: float
    lng: float
    elevation_m: float

    @property
    def elevation_ft(self) -> float:
        return self.elevation_m * 3.28084


@dataclass
class ElevationData:
    """Extracted elevation data."""
    points: Dict[str, ElevationPoint] = field(default_factory=dict)
    min_elevation_m: float = 0.0
    max_elevation_m: float = 0.0
    resolution_m: float = 0.5
    bounds: Optional[PropertyBounds] = None
    source_tiles: List[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.points)

    @property
    def elevation_range_m(self) -> float:
        return self.max_elevation_m - self.min_elevation_m

    @property
    def elevation_range_ft(self) -> float:
        return self.elevation_range_m * 3.28084

    def to_list(self) -> List[Dict[str, float]]:
        """Convert to list of dicts for JSON serialization."""
        return [
            {
                "lat": p.lat,
                "lng": p.lng,
                "elevation_m": p.elevation_m,
                "elevation_ft": p.elevation_ft,
            }
            for p in self.points.values()
        ]


class LidarExtractor:
    """
    Main class for extracting elevation data from GeoTIFF LiDAR tiles.

    Usage:
        extractor = LidarExtractor()
        extractor.scan_folder("/path/to/tiles")

        bounds = PropertyBounds(lat=46.2615, lng=-80.4548, width_m=100, height_m=100)
        tiles = extractor.find_overlapping_tiles(bounds)

        data = extractor.extract_elevation(tiles, bounds)
        extractor.export_archengine(data, "terrain.json")
    """

    def __init__(self, utm_zone: int = 17):
        """
        Initialize extractor.

        Args:
            utm_zone: Default UTM zone for coordinate transforms (17 for Ontario)
        """
        self.utm_zone = utm_zone
        self.tiles: List[TileInfo] = []
        self._transformer = UtmTransformer(utm_zone, northern=True)

    def scan_folder(
        self,
        folder: str,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> int:
        """
        Scan a folder for GeoTIFF tiles.

        Args:
            folder: Path to folder containing GeoTIFF files
            progress_callback: Optional callback(current, total, filename)

        Returns:
            Number of tiles found
        """
        if not HAS_RASTERIO:
            raise RuntimeError("rasterio is required. Install with: pip install rasterio pyproj")

        self.tiles = []

        # Find all TIFF files
        tiff_files = []
        for root, dirs, files in os.walk(folder):
            for f in files:
                if f.lower().endswith(('.tif', '.tiff')):
                    tiff_files.append(os.path.join(root, f))

        total = len(tiff_files)
        if total == 0:
            return 0

        for i, path in enumerate(tiff_files):
            if progress_callback:
                progress_callback(i + 1, total, os.path.basename(path))

            tile = self._load_tile_info(path)
            if tile:
                self.tiles.append(tile)

        return len(self.tiles)

    def _load_tile_info(self, path: str) -> Optional[TileInfo]:
        """Load metadata from a single tile."""
        try:
            with rasterio.open(path) as src:
                bounds = src.bounds
                crs = src.crs

                # Transform bounds to WGS84
                if HAS_PYPROJ:
                    transformer = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
                    lng_min, lat_min = transformer.transform(bounds.left, bounds.bottom)
                    lng_max, lat_max = transformer.transform(bounds.right, bounds.top)
                else:
                    # Fallback: assume already WGS84 (will be wrong for UTM)
                    lng_min, lat_min = bounds.left, bounds.bottom
                    lng_max, lat_max = bounds.right, bounds.top

                # Parse Ontario filename
                tile_coord = parse_ontario_filename(os.path.basename(path))

                return TileInfo(
                    path=path,
                    name=os.path.basename(path),
                    crs=str(crs),
                    resolution=src.res[0],
                    width=src.width,
                    height=src.height,
                    bounds_native=(bounds.left, bounds.bottom, bounds.right, bounds.top),
                    lat_min=lat_min,
                    lat_max=lat_max,
                    lng_min=lng_min,
                    lng_max=lng_max,
                    tile_coord=tile_coord,
                )
        except Exception as e:
            print(f"Error loading {path}: {e}")
            return None

    def find_overlapping_tiles(self, bounds: PropertyBounds) -> List[TileInfo]:
        """
        Find tiles that overlap with property bounds.

        Args:
            bounds: Property bounds

        Returns:
            List of overlapping tiles
        """
        return [tile for tile in self.tiles if tile.overlaps(bounds)]

    def extract_elevation(
        self,
        tiles: List[TileInfo],
        bounds: PropertyBounds,
        max_points: int = 150000,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> ElevationData:
        """
        Extract elevation data from tiles within bounds.

        Args:
            tiles: List of tiles to extract from
            bounds: Property bounds
            max_points: Maximum number of points to extract
            progress_callback: Optional callback(current, total, message)

        Returns:
            ElevationData with extracted points
        """
        if not HAS_RASTERIO or not HAS_PYPROJ:
            raise RuntimeError("rasterio and pyproj required")

        result = ElevationData(
            bounds=bounds,
            min_elevation_m=float('inf'),
            max_elevation_m=float('-inf'),
        )

        lat_min, lat_max, lng_min, lng_max = bounds.to_tuple()
        points_per_tile = max_points // max(1, len(tiles))

        for i, tile in enumerate(tiles):
            if progress_callback:
                progress_callback(i + 1, len(tiles), f"Processing {tile.name}")

            try:
                with rasterio.open(tile.path) as src:
                    raster_crs = src.crs
                    resolution = src.res[0]

                    # Transform bounds to raster CRS
                    to_raster = Transformer.from_crs("EPSG:4326", raster_crs, always_xy=True)
                    from_raster = Transformer.from_crs(raster_crs, "EPSG:4326", always_xy=True)

                    raster_min_x, raster_min_y = to_raster.transform(lng_min, lat_min)
                    raster_max_x, raster_max_y = to_raster.transform(lng_max, lat_max)

                    # Add buffer
                    buffer = 5
                    raster_min_x -= buffer
                    raster_max_x += buffer
                    raster_min_y -= buffer
                    raster_max_y += buffer

                    # Clamp to tile bounds
                    tile_bounds = src.bounds
                    extract_min_x = max(raster_min_x, tile_bounds.left)
                    extract_max_x = min(raster_max_x, tile_bounds.right)
                    extract_min_y = max(raster_min_y, tile_bounds.bottom)
                    extract_max_y = min(raster_max_y, tile_bounds.top)

                    if extract_max_x <= extract_min_x or extract_max_y <= extract_min_y:
                        continue

                    # Get pixel coordinates
                    row_start, col_start = src.index(extract_min_x, extract_max_y)
                    row_end, col_end = src.index(extract_max_x, extract_min_y)

                    row_start = max(0, min(row_start, src.height - 1))
                    row_end = max(0, min(row_end + 1, src.height))
                    col_start = max(0, min(col_start, src.width - 1))
                    col_end = max(0, min(col_end + 1, src.width))

                    if row_end <= row_start or col_end <= col_start:
                        continue

                    # Read data window
                    elevation = src.read(1)
                    window_data = elevation[row_start:row_end, col_start:col_end]
                    nodata = src.nodata

                    # Calculate subsampling step
                    tile_total = window_data.shape[0] * window_data.shape[1]
                    step = max(1, int(math.sqrt(tile_total / points_per_tile)))

                    # Extract points
                    for row_idx in range(0, window_data.shape[0], step):
                        for col_idx in range(0, window_data.shape[1], step):
                            elev = float(window_data[row_idx, col_idx])
                            if nodata is not None and elev == nodata:
                                continue

                            # Calculate coordinates
                            px = extract_min_x + (col_idx + 0.5) * resolution
                            py = extract_max_y - (row_idx + 0.5) * resolution
                            plng, plat = from_raster.transform(px, py)

                            # Check if within requested bounds
                            if lat_min <= plat <= lat_max and lng_min <= plng <= lng_max:
                                key = f"{plat:.7f},{plng:.7f}"
                                result.points[key] = ElevationPoint(
                                    lat=plat,
                                    lng=plng,
                                    elevation_m=elev,
                                )
                                result.min_elevation_m = min(result.min_elevation_m, elev)
                                result.max_elevation_m = max(result.max_elevation_m, elev)

                    result.source_tiles.append(tile.name)
                    result.resolution_m = resolution

            except Exception as e:
                print(f"Error processing {tile.path}: {e}")
                import traceback
                traceback.print_exc()

        if result.min_elevation_m == float('inf'):
            result.min_elevation_m = 0.0
            result.max_elevation_m = 0.0

        return result

    # ========== Export Methods ==========

    def export_archengine(self, data: ElevationData, path: str):
        """
        Export as ArchEngine terrain JSON.

        Args:
            data: Elevation data to export
            path: Output file path
        """
        bounds = data.bounds
        if not bounds:
            raise ValueError("ElevationData has no bounds")

        lat_min, lat_max, lng_min, lng_max = bounds.to_tuple()
        width_m = (lng_max - lng_min) * 111000 * math.cos(math.radians((lat_min + lat_max) / 2))
        height_m = (lat_max - lat_min) * 111000

        output = {
            "source": "Ontario LiDAR GeoTIFF",
            "resolution_m": data.resolution_m,
            "bounds": {
                "lat_min": lat_min,
                "lat_max": lat_max,
                "lng_min": lng_min,
                "lng_max": lng_max,
            },
            "width_ft": width_m * 3.28084,
            "depth_ft": height_m * 3.28084,
            "min_elevation_m": data.min_elevation_m,
            "max_elevation_m": data.max_elevation_m,
            "elevation_grid": data.to_list(),
        }

        with open(path, 'w') as f:
            json.dump(output, f, indent=2)

    def export_csv(self, data: ElevationData, path: str):
        """
        Export as CSV with lat/lng coordinates.

        Args:
            data: Elevation data to export
            path: Output file path
        """
        with open(path, 'w') as f:
            f.write("Latitude,Longitude,Elevation_m,Elevation_ft\n")
            for pt in data.points.values():
                f.write(f"{pt.lat},{pt.lng},{pt.elevation_m},{pt.elevation_ft}\n")

    def export_revit_csv(self, data: ElevationData, path: str, units: str = "feet"):
        """
        Export as CSV for Revit topography import.

        Revit expects X, Y, Z coordinates in local units (not lat/lng).
        This converts to local coordinates with origin at the property corner.

        Args:
            data: Elevation data to export
            path: Output file path
            units: "feet" or "meters"
        """
        if not data.bounds:
            raise ValueError("ElevationData has no bounds")

        points = list(data.points.values())
        if not points:
            raise ValueError("No elevation points to export")

        # Use property corner as origin
        lat_min, lat_max, lng_min, lng_max = data.bounds.to_tuple()
        center_lat = (lat_min + lat_max) / 2

        # Conversion factors
        lat_to_m = 111000  # ~111km per degree latitude
        lng_to_m = 111000 * math.cos(math.radians(center_lat))
        m_to_units = 3.28084 if units == "feet" else 1.0

        # Find elevation baseline (lowest point)
        min_elev = data.min_elevation_m

        with open(path, 'w') as f:
            # Header for Revit CSV import
            f.write("X,Y,Z\n")

            for pt in points:
                # Convert to local coordinates (origin at SW corner)
                x = (pt.lng - lng_min) * lng_to_m * m_to_units
                y = (pt.lat - lat_min) * lat_to_m * m_to_units
                z = (pt.elevation_m - min_elev) * m_to_units  # Relative to lowest point

                f.write(f"{x:.4f},{y:.4f},{z:.4f}\n")

    def export_revit_points(self, data: ElevationData, path: str, units: str = "feet"):
        """
        Export as Revit points file (.txt) for direct import.

        Format: X Y Z (space-separated, one point per line)

        Args:
            data: Elevation data to export
            path: Output file path
            units: "feet" or "meters"
        """
        if not data.bounds:
            raise ValueError("ElevationData has no bounds")

        points = list(data.points.values())
        if not points:
            raise ValueError("No elevation points to export")

        lat_min, lat_max, lng_min, lng_max = data.bounds.to_tuple()
        center_lat = (lat_min + lat_max) / 2

        lat_to_m = 111000
        lng_to_m = 111000 * math.cos(math.radians(center_lat))
        m_to_units = 3.28084 if units == "feet" else 1.0

        min_elev = data.min_elevation_m

        with open(path, 'w') as f:
            for pt in points:
                x = (pt.lng - lng_min) * lng_to_m * m_to_units
                y = (pt.lat - lat_min) * lat_to_m * m_to_units
                z = (pt.elevation_m - min_elev) * m_to_units

                f.write(f"{x:.4f} {y:.4f} {z:.4f}\n")

    def export_obj(self, data: ElevationData, path: str):
        """
        Export as OBJ mesh.

        Args:
            data: Elevation data to export
            path: Output file path
        """
        points = list(data.points.values())
        if not data.bounds:
            raise ValueError("ElevationData has no bounds")

        lat_min, lat_max, lng_min, lng_max = data.bounds.to_tuple()

        # Sort points into grid
        lats = sorted(set(p.lat for p in points))
        lngs = sorted(set(p.lng for p in points))

        # Create vertex lookup
        vertex_map = {(p.lat, p.lng): p for p in points}

        with open(path, 'w') as f:
            f.write("# LiDAR Terrain Mesh\n")
            f.write(f"# Points: {len(points)}\n\n")

            # Write vertices
            idx = 1
            vertex_indices = {}
            for lat in lats:
                for lng in lngs:
                    if (lat, lng) in vertex_map:
                        p = vertex_map[(lat, lng)]
                        x = (lng - lng_min) * 111000 * math.cos(math.radians(lat))
                        z = (lat - lat_min) * 111000
                        y = p.elevation_m
                        f.write(f"v {x:.3f} {y:.3f} {z:.3f}\n")
                        vertex_indices[(lat, lng)] = idx
                        idx += 1

            f.write("\n# Faces\n")
            # Generate faces
            for i, lat in enumerate(lats[:-1]):
                for j, lng in enumerate(lngs[:-1]):
                    lat2 = lats[i + 1]
                    lng2 = lngs[j + 1]

                    v1 = vertex_indices.get((lat, lng))
                    v2 = vertex_indices.get((lat, lng2))
                    v3 = vertex_indices.get((lat2, lng))
                    v4 = vertex_indices.get((lat2, lng2))

                    if v1 and v2 and v3:
                        f.write(f"f {v1} {v3} {v2}\n")
                    if v2 and v3 and v4:
                        f.write(f"f {v2} {v3} {v4}\n")

    def export_json(self, data: ElevationData, path: str):
        """
        Export raw elevation data as JSON.

        Args:
            data: Elevation data to export
            path: Output file path
        """
        output = {
            "count": data.count,
            "min_elevation_m": data.min_elevation_m,
            "max_elevation_m": data.max_elevation_m,
            "resolution_m": data.resolution_m,
            "bounds": data.bounds.to_tuple() if data.bounds else None,
            "source_tiles": data.source_tiles,
            "points": data.to_list(),
        }

        with open(path, 'w') as f:
            json.dump(output, f, indent=2)
