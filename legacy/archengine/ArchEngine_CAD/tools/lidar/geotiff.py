"""
GeoTIFF reading utilities.

Handles:
- Ontario LiDAR filename parsing (UTM coordinate encoding)
- GeoTIFF metadata extraction
- Elevation data reading
"""

import os
import re
from dataclasses import dataclass
from typing import Optional, Tuple, Dict, Any

import numpy as np

# Optional rasterio import
try:
    import rasterio
    from rasterio.crs import CRS
    HAS_RASTERIO = True
except ImportError:
    HAS_RASTERIO = False


@dataclass
class TileCoordinate:
    """
    Parsed coordinate from Ontario LiDAR filename.

    Ontario LiDAR files encode UTM coordinates:
    Format: `1km{zone}{easting_km}{northing}...`
    Example: `1km175420512303030LLAKENIPISSING_DSM.tif`
    """
    zone: int
    easting: int  # In meters
    northing: int  # In meters

    @property
    def utm_bounds(self) -> Tuple[float, float, float, float]:
        """Return (min_x, max_x, min_y, max_y) in UTM meters."""
        return (
            float(self.easting),
            float(self.easting + 1000),  # 1km tiles
            float(self.northing),
            float(self.northing + 1000),
        )


def parse_ontario_filename(filename: str) -> Optional[TileCoordinate]:
    """
    Parse Ontario LiDAR filename to extract UTM coordinates.

    Filename format: `1km{zone:2}{easting_km:3}{northing:7}...`

    Examples:
        - `1km175420512303030LLAKENIPISSING_DSM.tif` -> zone 17, easting 542000, northing 5123030
        - `1km175410512103010LLAKENIPISSING_DSM.tif` -> zone 17, easting 541000, northing 5121030

    Args:
        filename: The filename (with or without path)

    Returns:
        TileCoordinate if parsed successfully, None otherwise
    """
    basename = os.path.basename(filename)

    # Pattern: 1km{zone:2}{easting_km:3}{northing:7}
    match = re.match(r'^1km(\d{2})(\d{3})(\d{7})', basename)
    if match:
        zone = int(match.group(1))
        easting_km = int(match.group(2))
        northing = int(match.group(3))

        return TileCoordinate(
            zone=zone,
            easting=easting_km * 1000,
            northing=northing,
        )

    # Alternative pattern with 4-digit easting
    match = re.match(r'^1km(\d{2})(\d{4})(\d{7})', basename)
    if match:
        zone = int(match.group(1))
        easting_km = int(match.group(2))
        northing = int(match.group(3))

        return TileCoordinate(
            zone=zone,
            easting=easting_km * 1000,
            northing=northing,
        )

    return None


@dataclass
class GeoTiffInfo:
    """Metadata from a GeoTIFF file."""
    path: str
    width: int
    height: int
    crs: str
    resolution: Tuple[float, float]
    bounds_native: Tuple[float, float, float, float]  # left, bottom, right, top
    nodata: Optional[float]
    dtype: str


def read_geotiff_info(path: str) -> Optional[GeoTiffInfo]:
    """
    Read metadata from a GeoTIFF file.

    Args:
        path: Path to the GeoTIFF file

    Returns:
        GeoTiffInfo if successful, None otherwise
    """
    if not HAS_RASTERIO:
        return None

    try:
        with rasterio.open(path) as src:
            return GeoTiffInfo(
                path=path,
                width=src.width,
                height=src.height,
                crs=str(src.crs),
                resolution=src.res,
                bounds_native=(
                    src.bounds.left,
                    src.bounds.bottom,
                    src.bounds.right,
                    src.bounds.top,
                ),
                nodata=src.nodata,
                dtype=str(src.dtypes[0]),
            )
    except Exception as e:
        print(f"Error reading GeoTIFF info from {path}: {e}")
        return None


@dataclass
class ElevationWindow:
    """A window of elevation data from a GeoTIFF."""
    data: np.ndarray
    origin_x: float  # UTM X of top-left pixel
    origin_y: float  # UTM Y of top-left pixel
    pixel_size_x: float
    pixel_size_y: float  # Usually negative
    nodata: Optional[float]
    crs: str


def read_geotiff_elevation(
    path: str,
    bounds: Optional[Tuple[float, float, float, float]] = None,
) -> Optional[ElevationWindow]:
    """
    Read elevation data from a GeoTIFF file.

    Args:
        path: Path to the GeoTIFF file
        bounds: Optional (min_x, min_y, max_x, max_y) in native CRS to clip

    Returns:
        ElevationWindow with the data, or None on error
    """
    if not HAS_RASTERIO:
        return None

    try:
        with rasterio.open(path) as src:
            if bounds:
                # Calculate pixel window for bounds
                min_x, min_y, max_x, max_y = bounds

                # Clamp to file bounds
                tile_bounds = src.bounds
                min_x = max(min_x, tile_bounds.left)
                max_x = min(max_x, tile_bounds.right)
                min_y = max(min_y, tile_bounds.bottom)
                max_y = min(max_y, tile_bounds.top)

                # Get pixel coordinates
                row_start, col_start = src.index(min_x, max_y)
                row_end, col_end = src.index(max_x, min_y)

                # Ensure valid range
                row_start = max(0, min(row_start, src.height - 1))
                row_end = max(row_start + 1, min(row_end + 1, src.height))
                col_start = max(0, min(col_start, src.width - 1))
                col_end = max(col_start + 1, min(col_end + 1, src.width))

                # Read window
                data = src.read(1)[row_start:row_end, col_start:col_end]

                # Calculate origin for window
                transform = src.transform
                origin_x = transform.c + col_start * transform.a
                origin_y = transform.f + row_start * transform.e

            else:
                # Read entire file
                data = src.read(1)
                origin_x = src.transform.c
                origin_y = src.transform.f

            return ElevationWindow(
                data=data,
                origin_x=origin_x,
                origin_y=origin_y,
                pixel_size_x=src.res[0],
                pixel_size_y=-src.res[1],  # Y is usually negative going down
                nodata=src.nodata,
                crs=str(src.crs),
            )

    except Exception as e:
        print(f"Error reading elevation from {path}: {e}")
        import traceback
        traceback.print_exc()
        return None


def get_elevation_at_point(
    window: ElevationWindow,
    x: float,
    y: float,
) -> Optional[float]:
    """
    Get elevation value at a specific coordinate.

    Args:
        window: ElevationWindow data
        x: X coordinate in native CRS
        y: Y coordinate in native CRS

    Returns:
        Elevation value or None if outside bounds or nodata
    """
    col = int((x - window.origin_x) / window.pixel_size_x)
    row = int((y - window.origin_y) / window.pixel_size_y)

    if 0 <= row < window.data.shape[0] and 0 <= col < window.data.shape[1]:
        value = float(window.data[row, col])
        if window.nodata is not None and value == window.nodata:
            return None
        return value

    return None


def elevation_statistics(window: ElevationWindow) -> Dict[str, float]:
    """
    Calculate statistics for elevation data.

    Args:
        window: ElevationWindow data

    Returns:
        Dict with min, max, mean, std, count
    """
    data = window.data.flatten()

    if window.nodata is not None:
        valid = data[data != window.nodata]
    else:
        valid = data

    if len(valid) == 0:
        return {
            "min": 0.0,
            "max": 0.0,
            "mean": 0.0,
            "std": 0.0,
            "count": 0,
        }

    return {
        "min": float(np.min(valid)),
        "max": float(np.max(valid)),
        "mean": float(np.mean(valid)),
        "std": float(np.std(valid)),
        "count": int(len(valid)),
    }
