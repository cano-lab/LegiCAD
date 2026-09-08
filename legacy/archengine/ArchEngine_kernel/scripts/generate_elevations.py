#!/usr/bin/env python3
"""
generate_elevations.py - Generate 2D elevation drawings from building JSON

Creates North, South, East, West elevation views showing:
- Exterior wall faces with proper heights
- Windows with sill heights and headers
- Doors with proper heights
- Roof profiles
- Level markers (floor, ceiling, plate heights)
"""

import json
import math
import argparse
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional

from title_block import generate_title_block, get_project_info_from_json, get_drawing_info

# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class Point2D:
    x: float
    y: float

@dataclass
class WallSegment:
    """A wall segment projected onto an elevation plane"""
    start_x: float      # Horizontal position (along elevation)
    end_x: float        # Horizontal end position
    bottom_y: float     # Vertical position (usually 0 for ground floor)
    top_y: float        # Top of wall
    wall_index: int     # Original wall index for door/window matching

@dataclass
class Opening:
    """Door or window opening"""
    center_x: float     # Horizontal center position
    width: float
    bottom_y: float     # Sill height (0 for doors)
    top_y: float        # Header height
    is_door: bool
    opening_type: str   # "entry", "swing", "double_hung", etc.

@dataclass
class RoofEdge:
    """Roof edge/profile line"""
    start: Point2D
    end: Point2D

@dataclass
class LevelMarker:
    """Horizontal level marker"""
    y: float
    label: str
    is_major: bool = True

@dataclass
class Elevation:
    """Complete elevation data for one direction"""
    direction: str      # "north", "south", "east", "west"
    walls: List[WallSegment]
    openings: List[Opening]
    roof_edges: List[RoofEdge]
    level_markers: List[LevelMarker]
    width: float        # Total width of elevation
    height: float       # Total height including roof

# =============================================================================
# GEOMETRY HELPERS
# =============================================================================

def get_wall_direction(start: List[float], end: List[float]) -> Optional[str]:
    """
    Determine which direction a wall faces based on its orientation.
    Walls are defined in XZ plane (Y is up in kernel coords).

    Returns: 'north', 'south', 'east', 'west', or None for angled walls
    """
    dx = end[0] - start[0]
    dz = end[2] - start[2]

    # Threshold for considering a wall axis-aligned
    threshold = 50  # mm

    if abs(dz) < threshold and abs(dx) > threshold:
        # Wall runs along X axis - faces North or South
        # Normal points in +Z or -Z direction
        # Convention: exterior is on the side with larger Z (north-facing)
        # This is simplified - actual direction depends on room placement
        return 'south' if dx > 0 else 'south'  # South-facing wall (front)
    elif abs(dx) < threshold and abs(dz) > threshold:
        # Wall runs along Z axis - faces East or West
        return 'east' if dz > 0 else 'west'

    return None  # Angled wall - skip for now

def get_wall_facing(wall: dict, all_walls: List[dict], building_bounds: dict) -> Optional[str]:
    """
    Determine wall facing direction based on position relative to building center.
    """
    start = wall['start']
    end = wall['end']

    dx = end[0] - start[0]
    dz = end[2] - start[2]

    # Calculate wall center
    wall_cx = (start[0] + end[0]) / 2
    wall_cz = (start[2] + end[2]) / 2

    # Building center
    bld_cx = building_bounds['width'] / 2
    bld_cz = building_bounds['depth'] / 2

    threshold = 50  # mm

    if abs(dz) < threshold and abs(dx) > threshold:
        # Wall runs along X axis (horizontal in plan)
        # Check if it's at the front (south, low Z) or back (north, high Z)
        if wall_cz < bld_cz:
            return 'south'
        else:
            return 'north'
    elif abs(dx) < threshold and abs(dz) > threshold:
        # Wall runs along Z axis (vertical in plan)
        # Check if it's on the left (west) or right (east)
        if wall_cx < bld_cx:
            return 'west'
        else:
            return 'east'

    return None

def project_to_elevation(wall: dict, direction: str, building_bounds: dict) -> WallSegment:
    """
    Project a 3D wall onto a 2D elevation plane.

    For South/North elevations: X position maps to horizontal, Y/height maps to vertical
    For East/West elevations: Z position maps to horizontal, Y/height maps to vertical
    """
    start = wall['start']
    end = wall['end']
    height = wall.get('height', 2700)  # Default 9' ceiling

    if direction in ['south', 'north']:
        # Project onto XY plane (looking from south or north)
        start_x = min(start[0], end[0])
        end_x = max(start[0], end[0])
        if direction == 'north':
            # Flip horizontally for north view (mirror)
            bw = building_bounds['width']
            start_x, end_x = bw - end_x, bw - start_x
    else:
        # Project onto ZY plane (looking from east or west)
        start_x = min(start[2], end[2])
        end_x = max(start[2], end[2])
        if direction == 'east':
            # Flip horizontally for east view
            bd = building_bounds['depth']
            start_x, end_x = bd - end_x, bd - start_x

    return WallSegment(
        start_x=start_x,
        end_x=end_x,
        bottom_y=start[1],  # Usually 0
        top_y=start[1] + height,
        wall_index=wall.get('_index', -1)
    )

def project_opening(opening: dict, wall: dict, direction: str,
                    building_bounds: dict, is_door: bool) -> Optional[Opening]:
    """Project a door or window onto the elevation plane."""

    wall_start = wall['start']
    wall_end = wall['end']

    # Calculate wall direction vector
    wall_dx = wall_end[0] - wall_start[0]
    wall_dz = wall_end[2] - wall_start[2]
    wall_length = math.sqrt(wall_dx**2 + wall_dz**2)

    if wall_length < 1:
        return None

    # Opening position along wall
    offset = opening['offset']  # Distance from wall start to opening center

    # Calculate 3D position of opening center
    t = offset / wall_length
    opening_x = wall_start[0] + t * wall_dx
    opening_z = wall_start[2] + t * wall_dz

    # Project to elevation
    if direction in ['south', 'north']:
        center_x = opening_x
        if direction == 'north':
            center_x = building_bounds['width'] - center_x
    else:
        center_x = opening_z
        if direction == 'east':
            center_x = building_bounds['depth'] - center_x

    width = opening['width']
    height = opening['height']
    sill_height = opening.get('sill_height', 0) if not is_door else 0

    return Opening(
        center_x=center_x,
        width=width,
        bottom_y=sill_height,
        top_y=sill_height + height,
        is_door=is_door,
        opening_type=opening.get('type', 'unknown')
    )

def get_roof_profile(roof: dict, direction: str, building_bounds: dict) -> List[RoofEdge]:
    """
    Extract the roof profile visible from the given direction.

    For each direction, we filter to surfaces facing that direction,
    then extract their silhouette edges.
    """
    edges = []

    # First, try to use surfaces if available
    if 'surfaces' in roof and roof['surfaces']:
        # Get surfaces that face this direction
        facing_surfaces = []
        for surface in roof['surfaces']:
            surface_name = surface.get('name', '')
            # Match surface name to direction (e.g., 'hip_south' faces south)
            if direction in surface_name or surface_name == direction:
                facing_surfaces.append(surface)

        # If no directly facing surfaces, use all surfaces (fallback)
        if not facing_surfaces:
            facing_surfaces = roof['surfaces']

        for surface in facing_surfaces:
            vertices = surface.get('vertices', [])
            if len(vertices) < 3:
                continue

            # Extract perimeter edges of this surface
            for i in range(len(vertices)):
                v1 = vertices[i]
                v2 = vertices[(i + 1) % len(vertices)]

                # Project vertices based on viewing direction
                if direction in ['south', 'north']:
                    # South/North elevation: X is horizontal, Y is vertical
                    x1, y1 = v1[0], v1[1]
                    x2, y2 = v2[0], v2[1]
                    if direction == 'north':
                        # Mirror for north view
                        x1 = building_bounds['width'] - x1
                        x2 = building_bounds['width'] - x2
                else:
                    # East/West elevation: Z is horizontal, Y is vertical
                    x1, y1 = v1[2], v1[1]
                    x2, y2 = v2[2], v2[1]
                    if direction == 'east':
                        # Mirror for east view
                        x1 = building_bounds['depth'] - x1
                        x2 = building_bounds['depth'] - x2

                edges.append(RoofEdge(
                    start=Point2D(x1, y1),
                    end=Point2D(x2, y2)
                ))
    else:
        # Fallback: Generate roof profile from building bounds
        # Create base vertices from building dimensions if not provided
        base = roof.get('base_vertices', [])
        if not base:
            # Generate base rectangle from building bounds
            width = building_bounds.get('width', 10000)
            depth = building_bounds.get('depth', 10000)
            base = [
                [0, 0],  # x, z
                [width, 0],
                [width, depth],
                [0, depth]
            ]
        ridge = roof.get('ridge_vertices', [])
        base_height = roof.get('base_height', 2700)
        ridge_height = base_height + roof.get('ridge_height', 1000)

        if not base or len(base) < 3:
            return edges

        # Get bounding box of base
        xs = [p[0] for p in base]
        zs = [p[1] for p in base]
        min_x, max_x = min(xs), max(xs)
        min_z, max_z = min(zs), max(zs)
        center_x = (min_x + max_x) / 2
        center_z = (min_z + max_z) / 2

        roof_type = roof.get('type', 'hip')

        # Generate profile based on roof type and direction
        if direction in ['south', 'north']:
            # Looking at X dimension, Z is depth
            if roof_type in ['gable', 'hip']:
                # Ridge runs along longer dimension
                if (max_x - min_x) >= (max_z - min_z):
                    # Ridge along X - we see gable end from S/N
                    profile_pts = [
                        (min_x, base_height),
                        (center_x, ridge_height),
                        (max_x, base_height)
                    ]
                else:
                    # Ridge along Z - we see slope from S/N
                    profile_pts = [
                        (min_x, base_height),
                        (min_x, ridge_height),
                        (max_x, ridge_height),
                        (max_x, base_height)
                    ]
            elif roof_type == 'shed':
                profile_pts = [
                    (min_x, base_height),
                    (max_x, ridge_height)
                ]
            else:  # flat
                profile_pts = [
                    (min_x, ridge_height),
                    (max_x, ridge_height)
                ]

            # Apply mirror for north view
            if direction == 'north':
                profile_pts = [(building_bounds['width'] - x, y) for x, y in profile_pts]
        else:
            # Looking at Z dimension, X is depth
            if roof_type in ['gable', 'hip']:
                if (max_z - min_z) >= (max_x - min_x):
                    # Ridge along Z - we see gable end from E/W
                    profile_pts = [
                        (min_z, base_height),
                        (center_z, ridge_height),
                        (max_z, base_height)
                    ]
                else:
                    # Ridge along X - we see slope from E/W
                    profile_pts = [
                        (min_z, base_height),
                        (min_z, ridge_height),
                        (max_z, ridge_height),
                        (max_z, base_height)
                    ]
            elif roof_type == 'shed':
                profile_pts = [
                    (min_z, base_height),
                    (max_z, ridge_height)
                ]
            else:  # flat
                profile_pts = [
                    (min_z, ridge_height),
                    (max_z, ridge_height)
                ]

            # Apply mirror for east view
            if direction == 'east':
                profile_pts = [(building_bounds['depth'] - x, y) for x, y in profile_pts]

        # Convert points to edges
        for i in range(len(profile_pts) - 1):
            edges.append(RoofEdge(
                start=Point2D(profile_pts[i][0], profile_pts[i][1]),
                end=Point2D(profile_pts[i+1][0], profile_pts[i+1][1])
            ))

    return edges

# =============================================================================
# ELEVATION GENERATOR
# =============================================================================

def generate_elevation(data: dict, direction: str) -> Elevation:
    """Generate elevation data for a single direction."""

    building_bounds = {
        'width': data.get('width', 10000),
        'depth': data.get('depth', 10000)
    }

    walls = data.get('walls_batch', [])
    doors = data.get('doors', [])
    windows = data.get('windows', [])
    roofs = data.get('roofs', [])

    # Add index to walls for reference
    for i, wall in enumerate(walls):
        wall['_index'] = i

    # Filter exterior walls facing this direction
    elevation_walls = []
    wall_map = {}  # wall_index -> WallSegment

    for wall in walls:
        if wall.get('category') != 'exterior':
            continue

        facing = get_wall_facing(wall, walls, building_bounds)
        if facing == direction:
            segment = project_to_elevation(wall, direction, building_bounds)
            elevation_walls.append(segment)
            wall_map[wall['_index']] = segment

    # Collect openings for these walls
    elevation_openings = []

    for door in doors:
        wall_idx = door.get('wall_index', -1)
        if wall_idx in wall_map:
            wall = walls[wall_idx]
            opening = project_opening(door, wall, direction, building_bounds, is_door=True)
            if opening:
                elevation_openings.append(opening)

    for window in windows:
        wall_idx = window.get('wall_index', -1)
        if wall_idx in wall_map:
            wall = walls[wall_idx]
            opening = project_opening(window, wall, direction, building_bounds, is_door=False)
            if opening:
                elevation_openings.append(opening)

    # Get roof profile
    roof_edges = []
    for roof in roofs:
        roof_edges.extend(get_roof_profile(roof, direction, building_bounds))

    # Calculate level markers
    wall_height = 2700  # Default, could be extracted from walls
    if elevation_walls:
        wall_height = max(w.top_y - w.bottom_y for w in elevation_walls)

    level_markers = [
        LevelMarker(y=0, label="Floor", is_major=True),
        LevelMarker(y=wall_height, label="Plate", is_major=True),
    ]

    # Add window sill markers
    sill_heights = set()
    for op in elevation_openings:
        if not op.is_door and op.bottom_y > 0:
            sill_heights.add(op.bottom_y)

    for sill in sorted(sill_heights):
        level_markers.append(LevelMarker(y=sill, label=f"Sill {sill:.0f}", is_major=False))

    # Calculate bounds
    if direction in ['south', 'north']:
        width = building_bounds['width']
    else:
        width = building_bounds['depth']

    max_height = wall_height
    for edge in roof_edges:
        max_height = max(max_height, edge.start.y, edge.end.y)

    return Elevation(
        direction=direction,
        walls=elevation_walls,
        openings=elevation_openings,
        roof_edges=roof_edges,
        level_markers=level_markers,
        width=width,
        height=max_height
    )

# =============================================================================
# SVG RENDERER
# =============================================================================

def render_elevation_svg(elevation: Elevation, scale: float = 0.1,
                         margin: float = 4000, project_info: Dict = None,
                         drawing_type: str = 'elevation_south') -> str:
    """Render an elevation to SVG format using model-space coordinates."""

    # Use model-space viewBox (like floor plan) so title block works correctly
    # Elevation is drawn with Y=0 at ground level, Y increasing upward
    # But SVG Y increases downward, so we flip

    vb_x = -margin
    vb_y = -margin
    vb_w = elevation.width + 2 * margin
    vb_h = elevation.height + 2 * margin + 1000  # Extra space for roof

    lines = []
    lines.append(f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg"
     width="{int(vb_w * scale)}" height="{int(vb_h * scale)}"
     viewBox="{vb_x} {vb_y} {vb_w} {vb_h}">''')
    lines.append(f'  <title>{elevation.direction.title()} Elevation</title>')

    # Pattern definitions for material hatches
    lines.append('''  <defs>
    <!-- Brick pattern -->
    <pattern id="brick-pattern" patternUnits="userSpaceOnUse" width="300" height="150">
      <rect width="300" height="150" fill="#e8d4c4"/>
      <line x1="0" y1="75" x2="300" y2="75" stroke="#c9b8a8" stroke-width="4"/>
      <line x1="150" y1="0" x2="150" y2="75" stroke="#c9b8a8" stroke-width="4"/>
      <line x1="0" y1="75" x2="0" y2="150" stroke="#c9b8a8" stroke-width="4"/>
      <line x1="300" y1="75" x2="300" y2="150" stroke="#c9b8a8" stroke-width="4"/>
    </pattern>

    <!-- Horizontal siding pattern -->
    <pattern id="siding-pattern" patternUnits="userSpaceOnUse" width="400" height="150">
      <rect width="400" height="150" fill="#f0ebe6"/>
      <line x1="0" y1="150" x2="400" y2="150" stroke="#d4cfc8" stroke-width="4"/>
      <line x1="0" y1="145" x2="400" y2="145" stroke="#e8e3dc" stroke-width="8"/>
    </pattern>

    <!-- Stucco/plaster pattern (subtle texture) -->
    <pattern id="stucco-pattern" patternUnits="userSpaceOnUse" width="200" height="200">
      <rect width="200" height="200" fill="#f5f2ef"/>
      <circle cx="30" cy="40" r="2" fill="#e8e5e0"/>
      <circle cx="90" cy="20" r="1.5" fill="#e8e5e0"/>
      <circle cx="150" cy="60" r="2" fill="#e8e5e0"/>
      <circle cx="50" cy="120" r="1.5" fill="#e8e5e0"/>
      <circle cx="120" cy="150" r="2" fill="#e8e5e0"/>
      <circle cx="180" cy="100" r="1.5" fill="#e8e5e0"/>
    </pattern>

    <!-- Roof shingle pattern -->
    <pattern id="shingle-pattern" patternUnits="userSpaceOnUse" width="400" height="200">
      <rect width="400" height="200" fill="#5a5a5a"/>
      <line x1="0" y1="100" x2="400" y2="100" stroke="#484848" stroke-width="6"/>
      <line x1="0" y1="200" x2="400" y2="200" stroke="#484848" stroke-width="6"/>
      <line x1="100" y1="0" x2="100" y2="100" stroke="#4a4a4a" stroke-width="3"/>
      <line x1="300" y1="0" x2="300" y2="100" stroke="#4a4a4a" stroke-width="3"/>
      <line x1="0" y1="100" x2="0" y2="200" stroke="#4a4a4a" stroke-width="3"/>
      <line x1="200" y1="100" x2="200" y2="200" stroke="#4a4a4a" stroke-width="3"/>
    </pattern>

    <!-- Ground/earth hatch -->
    <pattern id="ground-pattern" patternUnits="userSpaceOnUse" width="100" height="100">
      <rect width="100" height="100" fill="#d4c9b8"/>
      <line x1="0" y1="100" x2="100" y2="0" stroke="#c4b9a8" stroke-width="3"/>
      <line x1="50" y1="100" x2="100" y2="50" stroke="#c4b9a8" stroke-width="3"/>
      <line x1="0" y1="50" x2="50" y2="0" stroke="#c4b9a8" stroke-width="3"/>
    </pattern>

    <!-- Shadow filter -->
    <filter id="shadow-filter" x="-50%" y="-50%" width="200%" height="200%">
      <feDropShadow dx="200" dy="150" stdDeviation="100" flood-color="#000" flood-opacity="0.2"/>
    </filter>
  </defs>''')

    # Background
    lines.append(f'  <rect x="{vb_x}" y="{vb_y}" width="{vb_w}" height="{vb_h}" fill="white"/>')

    # Styles - using model-space sizes (mm)
    lines.append('''  <style>
    .wall { fill: url(#siding-pattern); stroke: #333; stroke-width: 8; }
    .wall-brick { fill: url(#brick-pattern); stroke: #333; stroke-width: 8; }
    .wall-stucco { fill: url(#stucco-pattern); stroke: #333; stroke-width: 8; }
    .wall-outline { fill: none; stroke: #333; stroke-width: 10; }
    .opening { fill: white; stroke: #333; stroke-width: 4; }
    .door { fill: #d4a574; stroke: #333; stroke-width: 4; }
    .door-panel { fill: #c49664; stroke: #8b6e4a; stroke-width: 3; }
    .window-frame { fill: none; stroke: #333; stroke-width: 6; }
    .window-glass { fill: #cce5ff; stroke: #666; stroke-width: 2; }
    .window-mullion { stroke: #333; stroke-width: 4; }
    .roof { fill: url(#shingle-pattern); stroke: #333; stroke-width: 10; }
    .roof-line { fill: none; stroke: #333; stroke-width: 10; }
    .level-line { stroke: #999; stroke-width: 2; stroke-dasharray: 50,25; }
    .level-line-major { stroke: #666; stroke-width: 4; stroke-dasharray: none; }
    .level-text { font-family: Arial, sans-serif; font-size: 200px; fill: #666; }
    .title { font-family: Arial, sans-serif; font-size: 400px; font-weight: bold; fill: #333; }
    .dimension { font-family: Arial, sans-serif; font-size: 180px; fill: #333; }
    .ground { fill: url(#ground-pattern); }
    .grade-line { stroke: #666; stroke-width: 8; }
    .shadow { fill: rgba(0,0,0,0.15); }
  </style>''')

    # Use a transform group to flip Y axis (SVG Y goes down, elevation Y goes up)
    # The elevation is drawn with Y=0 at ground, positive Y going up
    # We flip around Y=0 and then translate to position correctly
    flip_y = elevation.height + 500  # Flip point

    lines.append(f'<!-- Elevation drawing (Y-flipped) -->')
    lines.append(f'<g transform="translate(0, {flip_y}) scale(1, -1)">')

    # Calculate shadow offset (sun from upper left)
    shadow_dx = 300
    shadow_dy = -200  # Negative because Y is flipped

    # === LOD 0: Basic geometry (ground, walls, roof outline) ===
    lines.append('<g id="lod-0" data-lod="0">')

    # Draw building shadow on ground first (behind everything)
    if elevation.walls:
        # Get building bounds
        min_x = min(w.start_x for w in elevation.walls)
        max_x = max(w.end_x for w in elevation.walls)
        max_y = max(w.top_y for w in elevation.walls)

        # Shadow polygon on ground
        shadow_points = [
            f"{max_x:.0f},-200",  # Bottom right of building
            f"{max_x + shadow_dx:.0f},-200",  # Shadow extends right
            f"{max_x + shadow_dx:.0f},{-200 - shadow_dy:.0f}",  # Shadow depth
            f"{min_x:.0f},-200"   # Back to building left
        ]
        lines.append(f'  <polygon points="{" ".join(shadow_points)}" class="shadow"/>')

    # Ground indication
    lines.append(f'  <rect x="-200" y="-500" width="{elevation.width + 400}" height="500" class="ground"/>')
    lines.append(f'  <line x1="-200" y1="0" x2="{elevation.width + 200}" y2="0" class="grade-line"/>')

    # Draw wall shadows (cast to the right)
    for wall in elevation.walls:
        x = wall.start_x
        y = wall.bottom_y
        w = wall.end_x - wall.start_x
        h = wall.top_y - wall.bottom_y
        # Shadow offset polygon
        shadow_points = [
            f"{x + w:.0f},{y:.0f}",
            f"{x + w + shadow_dx:.0f},{y + shadow_dy:.0f}",
            f"{x + w + shadow_dx:.0f},{y + h + shadow_dy:.0f}",
            f"{x + w:.0f},{y + h:.0f}"
        ]
        lines.append(f'  <polygon points="{" ".join(shadow_points)}" class="shadow"/>')

    # Draw walls as outlines only (LOD 0 - no fill pattern)
    for wall in elevation.walls:
        x = wall.start_x
        y = wall.bottom_y
        w = wall.end_x - wall.start_x
        h = wall.top_y - wall.bottom_y
        lines.append(f'  <rect x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" class="wall-outline" fill="white"/>')

    # Draw roof outline only (LOD 0 - no fill pattern)
    if elevation.roof_edges:
        # Find roof outline by collecting unique vertices at the top
        roof_vertices = []
        for edge in elevation.roof_edges:
            roof_vertices.append((edge.start.x, edge.start.y))
            roof_vertices.append((edge.end.x, edge.end.y))

        # Get bounding vertices for roof polygon
        if roof_vertices:
            min_x_vertex = min(roof_vertices, key=lambda v: v[0])
            max_x_vertex = max(roof_vertices, key=lambda v: v[0])
            peak_vertex = max(roof_vertices, key=lambda v: v[1])

            # Simple triangular roof outline only
            roof_points = [
                f"{min_x_vertex[0]:.0f},{min_x_vertex[1]:.0f}",
                f"{peak_vertex[0]:.0f},{peak_vertex[1]:.0f}",
                f"{max_x_vertex[0]:.0f},{max_x_vertex[1]:.0f}"
            ]
            lines.append(f'  <polygon points="{" ".join(roof_points)}" fill="white" stroke="#333" stroke-width="10"/>')

    lines.append('</g>')  # End LOD 0

    # === LOD 1: Doors, windows (navigation level) ===
    lines.append('<g id="lod-1" data-lod="1">')

    # Draw openings (basic shapes)
    for opening in elevation.openings:
        x = opening.center_x - opening.width / 2
        y = opening.bottom_y
        w = opening.width
        h = opening.top_y - opening.bottom_y

        if opening.is_door:
            # Door background
            lines.append(f'  <rect x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" class="door"/>')
            # Door frame
            lines.append(f'  <rect x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" class="window-frame"/>')
            # Threshold
            lines.append(f'  <rect x="{x - 30:.0f}" y="{y - 30:.0f}" width="{w + 60:.0f}" height="30" fill="#888"/>')
        else:
            # Window basic
            lines.append(f'  <rect x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" class="window-glass"/>')
            lines.append(f'  <rect x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" class="window-frame"/>')

    lines.append('</g>')  # End LOD 1

    # === LOD 2: Material patterns, details, level markers ===
    lines.append('<g id="lod-2" data-lod="2">')

    # Draw walls with material pattern (overlay on LOD 0 outline)
    for wall in elevation.walls:
        x = wall.start_x
        y = wall.bottom_y
        w = wall.end_x - wall.start_x
        h = wall.top_y - wall.bottom_y
        lines.append(f'  <rect x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" class="wall"/>')

    # Opening details
    for opening in elevation.openings:
        x = opening.center_x - opening.width / 2
        y = opening.bottom_y
        w = opening.width
        h = opening.top_y - opening.bottom_y

        if opening.is_door:
            # Door panels (raised panel effect)
            panel_margin = 60
            panel_h = (h - 3 * panel_margin) / 2
            lines.append(f'  <rect x="{x + panel_margin:.0f}" y="{y + panel_margin:.0f}" width="{w - 2*panel_margin:.0f}" height="{panel_h:.0f}" class="door-panel"/>')
            lines.append(f'  <rect x="{x + panel_margin:.0f}" y="{y + 2*panel_margin + panel_h:.0f}" width="{w - 2*panel_margin:.0f}" height="{panel_h:.0f}" class="door-panel"/>')
            # Door handle
            handle_x = x + w * 0.85
            handle_y = y + h * 0.5
            lines.append(f'  <circle cx="{handle_x:.0f}" cy="{handle_y:.0f}" r="40" fill="#666"/>')
        else:
            # Window with shadow indent effect
            lines.append(f'  <rect x="{x - 20:.0f}" y="{y - 20:.0f}" width="{w + 40:.0f}" height="{h + 40:.0f}" fill="rgba(0,0,0,0.1)"/>')
            # Horizontal mullion
            mid_y = y + h / 2
            lines.append(f'  <line x1="{x:.0f}" y1="{mid_y:.0f}" x2="{x + w:.0f}" y2="{mid_y:.0f}" class="window-mullion"/>')
            # Vertical mullion for double-hung style
            mid_x = x + w / 2
            lines.append(f'  <line x1="{mid_x:.0f}" y1="{y:.0f}" x2="{mid_x:.0f}" y2="{y + h:.0f}" class="window-mullion"/>')
            # Window sill with depth
            lines.append(f'  <rect x="{x - 50:.0f}" y="{y - 40:.0f}" width="{w + 100:.0f}" height="40" fill="#ddd" stroke="#333" stroke-width="4"/>')
            # Window header
            lines.append(f'  <rect x="{x - 30:.0f}" y="{y + h:.0f}" width="{w + 60:.0f}" height="60" fill="#ddd" stroke="#333" stroke-width="4"/>')

    # Draw roof with pattern
    if elevation.roof_edges:
        roof_vertices = []
        for edge in elevation.roof_edges:
            roof_vertices.append((edge.start.x, edge.start.y))
            roof_vertices.append((edge.end.x, edge.end.y))

        if roof_vertices:
            min_x_vertex = min(roof_vertices, key=lambda v: v[0])
            max_x_vertex = max(roof_vertices, key=lambda v: v[0])
            peak_vertex = max(roof_vertices, key=lambda v: v[1])

            roof_points = [
                f"{min_x_vertex[0]:.0f},{min_x_vertex[1]:.0f}",
                f"{peak_vertex[0]:.0f},{peak_vertex[1]:.0f}",
                f"{max_x_vertex[0]:.0f},{max_x_vertex[1]:.0f}"
            ]
            lines.append(f'  <polygon points="{" ".join(roof_points)}" class="roof"/>')

        # Draw roof edge lines on top
        for edge in elevation.roof_edges:
            lines.append(f'  <line x1="{edge.start.x:.0f}" y1="{edge.start.y:.0f}" x2="{edge.end.x:.0f}" y2="{edge.end.y:.0f}" class="roof-line"/>')

    lines.append('</g>')  # End LOD 2

    lines.append('</g>')  # End Y-flipped group

    # === LOD 2: Level markers (outside the flipped group so text is right-side up) ===
    lines.append('<g id="lod-2-markers" data-lod="2">')
    marker_x = -margin + 500
    for marker in elevation.level_markers:
        y = flip_y - marker.y  # Convert to SVG Y
        line_class = "level-line-major" if marker.is_major else "level-line"

        # Level line
        lines.append(f'<line x1="{marker_x}" y1="{y:.0f}" x2="{elevation.width + 200}" y2="{y:.0f}" class="{line_class}"/>')

        # Level symbol
        if marker.is_major:
            lines.append(f'<circle cx="{marker_x}" cy="{y:.0f}" r="150" fill="white" stroke="#333" stroke-width="4"/>')
            lines.append(f'<text x="{marker_x}" y="{y + 60:.0f}" text-anchor="middle" class="dimension">{marker.y/1000:.1f}</text>')

        # Label
        lines.append(f'<text x="{marker_x + 250}" y="{y - 80:.0f}" class="level-text">{marker.label}</text>')

    # Scale bar
    sb_x = elevation.width / 2 - 500
    sb_y = elevation.height + 800
    lines.append(f'<line x1="{sb_x}" y1="{sb_y}" x2="{sb_x + 1000}" y2="{sb_y}" stroke="#333" stroke-width="8"/>')
    lines.append(f'<line x1="{sb_x}" y1="{sb_y - 50}" x2="{sb_x}" y2="{sb_y + 50}" stroke="#333" stroke-width="8"/>')
    lines.append(f'<line x1="{sb_x + 1000}" y1="{sb_y - 50}" x2="{sb_x + 1000}" y2="{sb_y + 50}" stroke="#333" stroke-width="8"/>')
    lines.append(f'<text x="{sb_x + 500}" y="{sb_y - 100}" text-anchor="middle" class="dimension">1m</text>')
    lines.append('</g>')  # End LOD 2 markers

    # === LOD 1: Title (navigation level - visible when zoomed out) ===
    lines.append(f'<text x="{elevation.width/2}" y="{-margin + 600}" text-anchor="middle" class="title" data-lod="1">{elevation.direction.upper()} ELEVATION</text>')

    # Title block
    if project_info:
        drawing_info = get_drawing_info(drawing_type, '1:100')
        lines.append(generate_title_block(elevation.width, elevation.height, project_info, drawing_info, scale, margin))

    lines.append('</svg>')

    return '\n'.join(lines)

# =============================================================================
# MAIN
# =============================================================================

def generate_all_elevations(input_path: str, output_dir: str, scale: float = 0.05):
    """Generate all four elevations from a building JSON file."""

    # Load JSON
    with open(input_path, 'r') as f:
        data = json.load(f)

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Get project info for title blocks
    project_info = get_project_info_from_json(data)

    directions = ['south', 'north', 'east', 'west']

    for direction in directions:
        print(f"Generating {direction} elevation...")

        elevation = generate_elevation(data, direction)
        drawing_type = f'elevation_{direction}'
        svg = render_elevation_svg(elevation, scale=scale, project_info=project_info, drawing_type=drawing_type)

        out_file = output_path / f"elevation_{direction}.svg"
        with open(out_file, 'w') as f:
            f.write(svg)

        print(f"  Wrote {out_file}")
        print(f"  - {len(elevation.walls)} wall segments")
        print(f"  - {len(elevation.openings)} openings")
        print(f"  - {len(elevation.roof_edges)} roof edges")

    print(f"\nGenerated {len(directions)} elevations in {output_dir}")

def main():
    parser = argparse.ArgumentParser(description='Generate 2D elevations from building JSON')
    parser.add_argument('input', nargs='?',
                        default='../../Shared/TestData/output/generated_building.json',
                        help='Input JSON file path')
    parser.add_argument('-o', '--output',
                        default='../../Shared/TestData/output',
                        help='Output directory for SVG files')
    parser.add_argument('-s', '--scale', type=float, default=0.05,
                        help='Scale factor (default: 0.05, meaning 1mm = 0.05px)')

    args = parser.parse_args()

    generate_all_elevations(args.input, args.output, args.scale)

if __name__ == '__main__':
    main()
