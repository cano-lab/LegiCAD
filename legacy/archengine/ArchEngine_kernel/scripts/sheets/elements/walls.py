"""
Wall rendering for architectural floor plans.

Renders walls as filled rectangles with proper thickness,
supporting both exterior and interior wall categories.
"""

import math
from typing import List, Dict, Any, Tuple, Optional
from xml.etree.ElementTree import Element

from ..svg_builder import SVGBuilder
from ..lod_layers import get_element_style


# Wall thickness by category (in mm)
WALL_THICKNESS = {
    "exterior": 200,    # 200mm exterior walls
    "interior": 100,    # 100mm interior walls
    "partition": 75,    # 75mm partitions
}


def get_wall_thickness(category: str) -> float:
    """Get wall thickness for a category."""
    return WALL_THICKNESS.get(category.lower(), 100)


def calculate_wall_corners(
    start: Tuple[float, float],
    end: Tuple[float, float],
    thickness: float,
) -> List[Tuple[float, float]]:
    """
    Calculate the four corners of a wall rectangle.

    Args:
        start: (x, y) start point (centerline)
        end: (x, y) end point (centerline)
        thickness: Wall thickness in mm

    Returns:
        List of 4 corner points [(x1,y1), (x2,y2), (x3,y3), (x4,y4)]
    """
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = math.sqrt(dx * dx + dy * dy)

    if length == 0:
        return [(start[0], start[1])] * 4

    # Perpendicular unit vector
    px = -dy / length
    py = dx / length

    # Half thickness offset
    offset = thickness / 2

    # Four corners
    return [
        (start[0] + px * offset, start[1] + py * offset),  # Start left
        (start[0] - px * offset, start[1] - py * offset),  # Start right
        (end[0] - px * offset, end[1] - py * offset),      # End right
        (end[0] + px * offset, end[1] + py * offset),      # End left
    ]


def render_wall_outline(
    builder: SVGBuilder,
    walls: List[Dict[str, Any]],
    parent: Element,
    scale: float = 1.0,
    transform_y: bool = True,
    height: float = 0,
) -> Element:
    """
    Render building outline from walls (LOD 1).

    Creates a simplified outline path showing just the building footprint.

    Args:
        builder: SVG builder instance
        walls: List of wall dictionaries from JSON
        parent: Parent SVG element
        scale: Scale factor (mm to points)
        transform_y: Whether to flip Y axis (SVG Y goes down)
        height: SVG height for Y transformation
    """
    style = get_element_style("building-outline")
    g = builder.group(parent=parent, class_="building-outline")

    # Collect all exterior wall segments for outline
    outline_points = []

    for wall in walls:
        category = wall.get("category", "interior")
        if category.lower() != "exterior":
            continue

        start = wall.get("start", [0, 0, 0])
        end = wall.get("end", [0, 0, 0])

        # Use X and Z coordinates (plan view)
        x1, y1 = start[0] * scale, start[2] * scale
        x2, y2 = end[0] * scale, end[2] * scale

        if transform_y:
            y1 = height - y1
            y2 = height - y2

        outline_points.append(((x1, y1), (x2, y2)))

    # Draw outline segments
    for (x1, y1), (x2, y2) in outline_points:
        builder.line(
            x1, y1, x2, y2,
            parent=g,
            stroke=style.get("stroke", "#333333"),
            stroke_width=style.get("stroke-width", 2),
        )

    return g


def render_walls(
    builder: SVGBuilder,
    walls: List[Dict[str, Any]],
    parent: Element,
    scale: float = 1.0,
    transform_y: bool = True,
    height: float = 0,
) -> Element:
    """
    Render walls with proper thickness (LOD 2).

    Args:
        builder: SVG builder instance
        walls: List of wall dictionaries from JSON
        parent: Parent SVG element
        scale: Scale factor (mm to points)
        transform_y: Whether to flip Y axis
        height: SVG height for Y transformation

    Returns:
        Group element containing all walls
    """
    wall_style = get_element_style("walls")
    fill_style = get_element_style("wall-fills")

    g = builder.group(parent=parent, class_="walls")

    for i, wall in enumerate(walls):
        wall_id = f"wall-{i}"
        category = wall.get("category", "interior")
        thickness = get_wall_thickness(category) * scale

        start = wall.get("start", [0, 0, 0])
        end = wall.get("end", [0, 0, 0])

        # Use X and Z coordinates (plan view)
        x1, z1 = start[0] * scale, start[2] * scale
        x2, z2 = end[0] * scale, end[2] * scale

        if transform_y:
            z1 = height - z1
            z2 = height - z2

        # Calculate wall rectangle corners
        corners = calculate_wall_corners((x1, z1), (x2, z2), thickness)

        # Create polygon for filled wall
        builder.polygon(
            points=corners,
            parent=g,
            id=wall_id,
            class_=f"wall wall-{category}",
            stroke=wall_style.get("stroke", "#000000"),
            stroke_width=wall_style.get("stroke-width", 1),
            fill=fill_style.get("fill", "#cccccc"),
            data={
                "wall-id": wall_id,
                "category": category,
                "start-x": str(start[0]),
                "start-z": str(start[2]),
                "end-x": str(end[0]),
                "end-z": str(end[2]),
            },
        )

    return g


def get_wall_bounds(walls: List[Dict[str, Any]]) -> Tuple[float, float, float, float]:
    """
    Calculate bounding box of all walls.

    Returns:
        (min_x, min_z, max_x, max_z) in mm
    """
    if not walls:
        return (0, 0, 0, 0)

    min_x = float("inf")
    min_z = float("inf")
    max_x = float("-inf")
    max_z = float("-inf")

    for wall in walls:
        start = wall.get("start", [0, 0, 0])
        end = wall.get("end", [0, 0, 0])

        min_x = min(min_x, start[0], end[0])
        max_x = max(max_x, start[0], end[0])
        min_z = min(min_z, start[2], end[2])
        max_z = max(max_z, start[2], end[2])

    return (min_x, min_z, max_x, max_z)
