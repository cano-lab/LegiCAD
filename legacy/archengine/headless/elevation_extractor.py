"""
Elevation Extractor from 3D Model

Generates orthographic elevation views from the Vulkan 3D model.
Uses the same data that feeds the viewport, but renders orthographic instead of perspective.
"""

import json
import math
from typing import List, Dict, Any, Tuple
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ElevationView:
    """Configuration for an elevation view."""
    direction: str  # north, south, east, west
    camera_pos: Tuple[float, float, float]
    look_at: Tuple[float, float, float]
    up_vector: Tuple[float, float, float]
    width_m: float
    height_m: float


def get_building_bounds(walls: List[Dict]) -> Tuple[float, float, float, float, float, float]:
    """
    Get 3D bounding box of building.
    
    Returns:
        (min_x, min_y, min_z, max_x, max_y, max_z) in mm
    """
    min_x = min_y = min_z = float('inf')
    max_x = max_y = max_z = float('-inf')
    
    for wall in walls:
        start = wall.get("start", [0, 0, 0])
        end = wall.get("end", [0, 0, 0])
        height = wall.get("height", 2700)
        
        min_x = min(min_x, start[0], end[0])
        max_x = max(max_x, start[0], end[0])
        min_y = min(min_y, 0)
        max_y = max(max_y, height)
        min_z = min(min_z, start[2], end[2])
        max_z = max(max_z, start[2], end[2])
    
    return (min_x, min_y, min_z, max_x, max_y, max_z)


def calculate_elevation_views(walls: List[Dict]) -> Dict[str, ElevationView]:
    """
    Calculate camera positions for 4 elevation views.
    
    Returns:
        Dict mapping direction to ElevationView
    """
    min_x, min_y, min_z, max_x, max_y, max_z = get_building_bounds(walls)
    
    # Building center
    center_x = (min_x + max_x) / 2
    center_y = (min_y + max_y) / 2
    center_z = (min_z + max_z) / 2
    
    # Building dimensions
    width = max_x - min_x
    depth = max_z - min_z
    height = max_y - min_y
    
    # Distance from building for camera (2x largest dimension)
    distance = max(width, depth, height) * 2
    
    views = {}
    
    # North elevation (looking from +Z toward -Z)
    views["north"] = ElevationView(
        direction="north",
        camera_pos=(center_x, center_y, max_z + distance),
        look_at=(center_x, center_y, center_z),
        up_vector=(0, 1, 0),
        width_m=width / 1000,
        height_m=height / 1000
    )
    
    # South elevation (looking from -Z toward +Z)
    views["south"] = ElevationView(
        direction="south",
        camera_pos=(center_x, center_y, min_z - distance),
        look_at=(center_x, center_y, center_z),
        up_vector=(0, 1, 0),
        width_m=width / 1000,
        height_m=height / 1000
    )
    
    # East elevation (looking from +X toward -X)
    views["east"] = ElevationView(
        direction="east",
        camera_pos=(max_x + distance, center_y, center_z),
        look_at=(center_x, center_y, center_z),
        up_vector=(0, 1, 0),
        width_m=depth / 1000,
        height_m=height / 1000
    )
    
    # West elevation (looking from -X toward +X)
    views["west"] = ElevationView(
        direction="west",
        camera_pos=(min_x - distance, center_y, center_z),
        look_at=(center_x, center_y, center_z),
        up_vector=(0, 1, 0),
        width_m=depth / 1000,
        height_m=height / 1000
    )
    
    return views


def project_3d_to_2d(
    point_3d: Tuple[float, float, float],
    view: ElevationView
) -> Tuple[float, float]:
    """
    Project 3D point to 2D elevation plane.
    
    For orthographic projection onto the view plane.
    Returns (x, y) in mm relative to view origin.
    """
    # Calculate basis vectors for view plane
    # Forward = look_at - camera_pos (normalized)
    fx = view.look_at[0] - view.camera_pos[0]
    fy = view.look_at[1] - view.camera_pos[1]
    fz = view.look_at[2] - view.camera_pos[2]
    
    # Normalize
    length = math.sqrt(fx*fx + fy*fy + fz*fz)
    if length > 0:
        fx, fy, fz = fx/length, fy/length, fz/length
    
    # Up vector (normalized)
    ux, uy, uz = view.up_vector
    
    # Right vector = forward × up
    rx = fy * uz - fz * uy
    ry = fz * ux - fx * uz
    rz = fx * uy - fy * ux
    
    # Vector from camera to point
    dx = point_3d[0] - view.camera_pos[0]
    dy = point_3d[1] - view.camera_pos[1]
    dz = point_3d[2] - view.camera_pos[2]
    
    # Project onto view plane basis vectors
    # x = dot(d, right)
    x_2d = dx * rx + dy * ry + dz * rz
    
    # y = dot(d, up)
    y_2d = dx * ux + dy * uy + dz * uz
    
    return (x_2d, y_2d)


def extract_walls_for_elevation(
    walls: List[Dict],
    doors: List[Dict],
    windows: List[Dict],
    view: ElevationView
) -> Dict[str, List[Dict]]:
    """
    Extract walls, doors, windows visible from this elevation view.
    
    Returns:
        Dict with 'walls', 'doors', 'windows' lists
    """
    visible = {
        "walls": [],
        "doors": [],
        "windows": []
    }
    
    # Determine which walls are facing this view
    # A wall is visible if its normal points toward the camera
    
    for wall in walls:
        start = wall.get("start", [0, 0, 0])
        end = wall.get("end", [0, 0, 0])
        
        # Wall vector
        wx = end[0] - start[0]
        wz = end[2] - start[2]
        
        # Wall normal (perpendicular in XZ plane)
        # For a wall from (x1,z1) to (x2,z2), normal is (z2-z1, 0, x1-x2)
        nx = wz
        nz = -wx
        
        # Normalize
        length = math.sqrt(nx*nx + nz*nz)
        if length > 0:
            nx, nz = nx/length, nz/length
        
        # Vector from wall center to camera
        center_x = (start[0] + end[0]) / 2
        center_z = (start[2] + end[2]) / 2
        
        cx = view.camera_pos[0] - center_x
        cz = view.camera_pos[2] - center_z
        
        # Normalize
        length = math.sqrt(cx*cx + cz*cz)
        if length > 0:
            cx, cz = cx/length, cz/length
        
        # Dot product - positive means facing camera
        dot = nx * cx + nz * cz
        
        if dot > 0.1:  # Facing camera (with tolerance)
            # Project wall endpoints to 2D
            p1 = project_3d_to_2d(start, view)
            p2 = project_3d_to_2d(end, view)
            
            visible["walls"].append({
                "original": wall,
                "projected_start": p1,
                "projected_end": p2,
                "height": wall.get("height", 2700),
                "category": wall.get("category", "interior")
            })
    
    # TODO: Project doors and windows similarly
    
    return visible


def generate_elevation_svg(
    building_data: Dict,
    direction: str,
    scale: str = "1:50",
    sheet_size: str = "ARCH_C"
) -> str:
    """
    Generate elevation SVG from 3D model.
    
    This bridges the Vulkan 3D data to 2D elevation drawings.
    """
    walls = building_data.get("walls", [])
    doors = building_data.get("doors", [])
    windows = building_data.get("windows", [])
    
    # Calculate view parameters
    views = calculate_elevation_views(walls)
    view = views.get(direction, views["north"])
    
    # Extract visible elements
    visible = extract_walls_for_elevation(walls, doors, windows, view)
    
    # TODO: Generate actual SVG using SVGBuilder
    # For now, return metadata about what would be drawn
    
    svg_content = f"""\u003c?xml version="1.0" encoding="UTF-8"?\u003e
\u003csvg xmlns="http://www.w3.org/2000/svg"
     width="{view.width_m * 1000}"
     height="{view.height_m * 1000}"
     viewBox="0 0 {view.width_m * 1000} {view.height_m * 1000}"\u003e
\u003cdefs\u003e
\u003cstyle\u003e
.wall {{ fill: none; stroke: #000; stroke-width: 4; }}
.door {{ fill: none; stroke: #000; stroke-width: 2; }}
.window {{ fill: white; stroke: #000; stroke-width: 2; }}
\u003c/style\u003e
\u003c/defs\u003e
\u003crect width="100%" height="100%" fill="white"/\u003e
\u003ctext x="50%" y="50" text-anchor="middle" font-size="24"\u003e{direction.upper()} ELEVATION\u003c/text\u003e
\u003ctext x="50%" y="80" text-anchor="middle" font-size="14"\u003eScale: {scale} | {len(visible['walls'])} walls visible\u003c/text\u003e
\u003c/svg\u003e"""
    
    return svg_content


def test_elevation_extraction():
    """Test elevation extraction from sample building."""
    print("=" * 60)
    print("Elevation Extraction Test")
    print("=" * 60)
    
    # Load test building from dimension test
    test_json = Path("/root/ArchEngine/headless/test_output/small_house.json")
    
    if not test_json.exists():
        print(f"❌ Test file not found: {test_json}")
        print("Run test_dimensions.py first to generate test data.")
        return False
    
    with open(test_json) as f:
        building = json.load(f)
    
    # Calculate views
    views = calculate_elevation_views(building["walls"])
    
    print(f"\nBuilding dimensions:")
    min_x, min_y, min_z, max_x, max_y, max_z = get_building_bounds(building["walls"])
    print(f"  Width:  {(max_x - min_x)/1000:.1f}m")
    print(f"  Depth:  {(max_z - min_z)/1000:.1f}m")
    print(f"  Height: {(max_y - min_y)/1000:.1f}m")
    
    print(f"\nElevation views:")
    for direction, view in views.items():
        print(f"  {direction:6s}: {view.width_m:.1f}m × {view.height_m:.1f}m")
    
    # Generate elevation SVGs
    output_dir = Path("/root/ArchEngine/headless/test_output/elevations")
    output_dir.mkdir(exist_ok=True)
    
    for direction in ["north", "south", "east", "west"]:
        svg = generate_elevation_svg(building, direction)
        output_path = output_dir / f"elevation_{direction}.svg"
        with open(output_path, 'w') as f:
            f.write(svg)
        print(f"  Generated: {output_path}")
    
    print("\n✅ Elevation extraction test complete.")
    print(f"Output: {output_dir}")
    
    return True


if __name__ == "__main__":
    test_elevation_extraction()
