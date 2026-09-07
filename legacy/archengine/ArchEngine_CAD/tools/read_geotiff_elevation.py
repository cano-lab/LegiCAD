#!/usr/bin/env python
"""
GeoTIFF Elevation Reader
========================
Reads elevation data from Ontario LiDAR GeoTIFF files.

Usage:
    python read_geotiff_elevation.py path/to/elevation.tif
    python read_geotiff_elevation.py path/to/elevation.tif --lat 46.2615 --lng -80.4548
"""

import sys
import os

# Try to import rasterio (preferred) or fall back to alternatives
try:
    import rasterio
    HAS_RASTERIO = True
except ImportError:
    HAS_RASTERIO = False

try:
    from osgeo import gdal
    HAS_GDAL = True
except ImportError:
    HAS_GDAL = False

try:
    import tifffile
    import numpy as np
    HAS_TIFFFILE = True
except ImportError:
    HAS_TIFFFILE = False


def read_with_rasterio(tiff_path, lat=None, lng=None):
    """Read GeoTIFF using rasterio."""
    with rasterio.open(tiff_path) as src:
        print(f"\n=== GeoTIFF Info ===")
        print(f"File: {tiff_path}")
        print(f"Size: {src.width} x {src.height} pixels")
        print(f"CRS: {src.crs}")
        print(f"Bounds: {src.bounds}")
        print(f"Resolution: {src.res[0]:.2f} x {src.res[1]:.2f} units per pixel")
        print(f"Data type: {src.dtypes[0]}")

        # Read the elevation data
        elevation = src.read(1)

        # Get stats
        valid_data = elevation[elevation != src.nodata] if src.nodata else elevation
        print(f"\n=== Elevation Stats ===")
        print(f"Min elevation: {valid_data.min():.2f}m")
        print(f"Max elevation: {valid_data.max():.2f}m")
        print(f"Elevation range: {valid_data.max() - valid_data.min():.2f}m")

        # If lat/lng provided, get elevation at that point
        if lat is not None and lng is not None:
            # Transform lat/lng to pixel coordinates
            row, col = src.index(lng, lat)
            if 0 <= row < src.height and 0 <= col < src.width:
                elev = elevation[row, col]
                print(f"\n=== Point Query ===")
                print(f"Lat/Lng: ({lat}, {lng})")
                print(f"Pixel: ({col}, {row})")
                print(f"Elevation: {elev:.2f}m ({elev * 3.28084:.2f}ft)")
            else:
                print(f"\nPoint ({lat}, {lng}) is outside the raster bounds")

        return elevation, src


def read_with_gdal(tiff_path, lat=None, lng=None):
    """Read GeoTIFF using GDAL."""
    ds = gdal.Open(tiff_path)
    if ds is None:
        print(f"Could not open {tiff_path}")
        return None, None

    print(f"\n=== GeoTIFF Info ===")
    print(f"File: {tiff_path}")
    print(f"Size: {ds.RasterXSize} x {ds.RasterYSize} pixels")
    print(f"Projection: {ds.GetProjection()[:80]}...")

    gt = ds.GetGeoTransform()
    print(f"Origin: ({gt[0]:.2f}, {gt[3]:.2f})")
    print(f"Pixel size: {gt[1]:.2f} x {gt[5]:.2f}")

    band = ds.GetRasterBand(1)
    elevation = band.ReadAsArray()
    nodata = band.GetNoDataValue()

    valid_data = elevation[elevation != nodata] if nodata else elevation
    print(f"\n=== Elevation Stats ===")
    print(f"Min elevation: {valid_data.min():.2f}m")
    print(f"Max elevation: {valid_data.max():.2f}m")
    print(f"Elevation range: {valid_data.max() - valid_data.min():.2f}m")

    if lat is not None and lng is not None:
        # Convert lat/lng to pixel
        col = int((lng - gt[0]) / gt[1])
        row = int((lat - gt[3]) / gt[5])
        if 0 <= row < ds.RasterYSize and 0 <= col < ds.RasterXSize:
            elev = elevation[row, col]
            print(f"\n=== Point Query ===")
            print(f"Lat/Lng: ({lat}, {lng})")
            print(f"Pixel: ({col}, {row})")
            print(f"Elevation: {elev:.2f}m ({elev * 3.28084:.2f}ft)")
        else:
            print(f"\nPoint ({lat}, {lng}) is outside the raster bounds")

    return elevation, ds


def read_with_tifffile(tiff_path):
    """Basic TIFF reading without geospatial info."""
    print(f"\n=== GeoTIFF Info (basic) ===")
    print(f"File: {tiff_path}")

    elevation = tifffile.imread(tiff_path)
    print(f"Shape: {elevation.shape}")
    print(f"Data type: {elevation.dtype}")

    print(f"\n=== Elevation Stats ===")
    print(f"Min value: {elevation.min():.2f}")
    print(f"Max value: {elevation.max():.2f}")
    print(f"Range: {elevation.max() - elevation.min():.2f}")
    print("\nNote: Without rasterio/GDAL, cannot determine geographic coordinates.")
    print("Install rasterio: pip install rasterio")

    return elevation, None


def list_tiff_files(directory):
    """List all TIFF files in a directory."""
    tiff_extensions = ('.tif', '.tiff', '.TIF', '.TIFF')
    tiffs = []
    for root, dirs, files in os.walk(directory):
        for f in files:
            if f.endswith(tiff_extensions):
                tiffs.append(os.path.join(root, f))
    return tiffs


def find_tile_for_coordinate(directory, lat, lng):
    """Find which TIFF tile contains the given coordinate."""
    if not HAS_RASTERIO:
        print("Need rasterio to search tiles. Install with: pip install rasterio")
        return None

    from rasterio.crs import CRS
    from pyproj import Transformer

    tiffs = list_tiff_files(directory)
    print(f"\nSearching {len(tiffs)} TIFF files for coordinate ({lat}, {lng})...")

    for tiff_path in tiffs:
        try:
            with rasterio.open(tiff_path) as src:
                # Get the CRS of the raster
                raster_crs = src.crs

                # Transform lat/lng (WGS84) to raster's CRS
                transformer = Transformer.from_crs("EPSG:4326", raster_crs, always_xy=True)
                x, y = transformer.transform(lng, lat)

                # Check if point is within bounds
                bounds = src.bounds
                if bounds.left <= x <= bounds.right and bounds.bottom <= y <= bounds.top:
                    print(f"\n*** FOUND: {os.path.basename(tiff_path)} ***")
                    print(f"  Full path: {tiff_path}")
                    print(f"  CRS: {raster_crs}")
                    print(f"  Bounds: {bounds}")
                    print(f"  Your point in raster CRS: ({x:.2f}, {y:.2f})")

                    # Get elevation at point
                    row, col = src.index(x, y)
                    elevation = src.read(1)
                    elev = elevation[row, col]
                    print(f"  Elevation at point: {elev:.2f}m ({elev * 3.28084:.2f}ft)")

                    return tiff_path
        except Exception as e:
            # Skip files that can't be read
            continue

    print("\nNo tile found containing your coordinates.")
    print("The downloaded data may not cover your property area.")
    return None


def extract_property_elevation(tiff_path, center_lat, center_lng, width_m, height_m, output_json=None):
    """Extract elevation grid for a property area."""
    if not HAS_RASTERIO:
        print("Need rasterio. Install with: pip install rasterio")
        return None

    from pyproj import Transformer
    import json

    with rasterio.open(tiff_path) as src:
        raster_crs = src.crs
        transformer = Transformer.from_crs("EPSG:4326", raster_crs, always_xy=True)
        reverse_transformer = Transformer.from_crs(raster_crs, "EPSG:4326", always_xy=True)

        # Convert center to raster CRS
        center_x, center_y = transformer.transform(center_lng, center_lat)

        # Calculate bounds
        half_w = width_m / 2
        half_h = height_m / 2
        min_x = center_x - half_w
        max_x = center_x + half_w
        min_y = center_y - half_h
        max_y = center_y + half_h

        # Get pixel coordinates
        row_start, col_start = src.index(min_x, max_y)
        row_end, col_end = src.index(max_x, min_y)

        # Ensure valid bounds
        row_start = max(0, row_start)
        col_start = max(0, col_start)
        row_end = min(src.height, row_end)
        col_end = min(src.width, col_end)

        # Read the elevation window
        elevation = src.read(1)
        window_data = elevation[row_start:row_end, col_start:col_end]

        print(f"\n=== Property Elevation Extract ===")
        print(f"Center: ({center_lat}, {center_lng})")
        print(f"Area: {width_m}m x {height_m}m")
        print(f"Grid size: {window_data.shape[1]} x {window_data.shape[0]} pixels")
        print(f"Resolution: {src.res[0]:.2f}m per pixel")
        print(f"Total points: {window_data.size}")

        nodata = src.nodata
        valid_data = window_data[window_data != nodata] if nodata else window_data.flatten()

        print(f"\nElevation stats for your property:")
        print(f"  Min: {valid_data.min():.2f}m ({valid_data.min() * 3.28084:.2f}ft)")
        print(f"  Max: {valid_data.max():.2f}m ({valid_data.max() * 3.28084:.2f}ft)")
        print(f"  Range: {valid_data.max() - valid_data.min():.2f}m ({(valid_data.max() - valid_data.min()) * 3.28084:.2f}ft)")

        # Create elevation grid for export
        if output_json:
            elevation_points = []
            for row_idx in range(window_data.shape[0]):
                for col_idx in range(window_data.shape[1]):
                    elev = float(window_data[row_idx, col_idx])
                    if nodata and elev == nodata:
                        continue

                    # Convert pixel to geographic coordinates
                    px = min_x + (col_idx + 0.5) * src.res[0]
                    py = max_y - (row_idx + 0.5) * src.res[1]
                    plng, plat = reverse_transformer.transform(px, py)

                    elevation_points.append({
                        "lat": round(plat, 7),
                        "lng": round(plng, 7),
                        "elevation_m": round(elev, 2),
                        "elevation_ft": round(elev * 3.28084, 2)
                    })

            output_data = {
                "source": "Ontario LiDAR GeoTIFF",
                "resolution_m": src.res[0],
                "center_lat": center_lat,
                "center_lng": center_lng,
                "width_m": width_m,
                "height_m": height_m,
                "min_elevation_m": float(valid_data.min()),
                "max_elevation_m": float(valid_data.max()),
                "points": elevation_points
            }

            with open(output_json, 'w') as f:
                json.dump(output_data, f, indent=2)
            print(f"\nExported {len(elevation_points)} points to: {output_json}")

        return window_data


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Read GeoTIFF elevation data')
    parser.add_argument('path', help='Path to GeoTIFF file or directory')
    parser.add_argument('--lat', type=float, help='Latitude to query')
    parser.add_argument('--lng', type=float, help='Longitude to query')
    parser.add_argument('--find-tile', action='store_true', help='Find which tile contains the lat/lng')
    parser.add_argument('--extract', action='store_true', help='Extract elevation for property area')
    parser.add_argument('--width', type=float, default=50, help='Property width in meters (for --extract)')
    parser.add_argument('--height', type=float, default=50, help='Property height in meters (for --extract)')
    parser.add_argument('--output', type=str, help='Output JSON file (for --extract)')
    parser.add_argument('--list', action='store_true', help='List all TIFF files in directory')

    args = parser.parse_args()

    # Check what libraries are available
    print("=== Available Libraries ===")
    print(f"rasterio: {'YES' if HAS_RASTERIO else 'NO (pip install rasterio)'}")
    print(f"GDAL: {'YES' if HAS_GDAL else 'NO (pip install gdal)'}")
    print(f"tifffile: {'YES' if HAS_TIFFFILE else 'NO (pip install tifffile)'}")

    # Find tile mode
    if args.find_tile and args.lat and args.lng:
        if os.path.isdir(args.path):
            tile = find_tile_for_coordinate(args.path, args.lat, args.lng)
            if tile and args.extract:
                extract_property_elevation(tile, args.lat, args.lng, args.width, args.height, args.output)
            return
        else:
            print("--find-tile requires a directory path")
            return

    # Extract mode with specific file
    if args.extract and args.lat and args.lng and os.path.isfile(args.path):
        extract_property_elevation(args.path, args.lat, args.lng, args.width, args.height, args.output)
        return

    if os.path.isdir(args.path):
        tiffs = list_tiff_files(args.path)
        print(f"\n=== Found {len(tiffs)} TIFF files ===")
        for t in tiffs[:20]:  # Show first 20
            print(f"  {t}")
        if len(tiffs) > 20:
            print(f"  ... and {len(tiffs) - 20} more")

        if args.lat and args.lng:
            print(f"\nTip: Use --find-tile to locate which TIFF contains your coordinates:")
            print(f"  python {sys.argv[0]} \"{args.path}\" --find-tile --lat {args.lat} --lng {args.lng}")

        if tiffs and not args.list and not args.lat:
            print(f"\nReading first file: {tiffs[0]}")
            args.path = tiffs[0]
        else:
            return

    if not os.path.exists(args.path):
        print(f"File not found: {args.path}")
        return

    # Try to read the file
    if HAS_RASTERIO:
        read_with_rasterio(args.path, args.lat, args.lng)
    elif HAS_GDAL:
        read_with_gdal(args.path, args.lat, args.lng)
    elif HAS_TIFFFILE:
        read_with_tifffile(args.path)
    else:
        print("\nNo GeoTIFF libraries available!")
        print("Install one of:")
        print("  pip install rasterio")
        print("  pip install gdal")
        print("  pip install tifffile numpy")


if __name__ == '__main__':
    main()
