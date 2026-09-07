"""
Door rendering for architectural floor plans.

Renders doors with proper swing arcs and wall openings.
"""

import math
from typing import List, Dict, Any, Tuple, Optional
from xml.etree.ElementTree import Element

from ..svg_builder import SVGBuilder
from ..lod_layers import get_element_style


# Default door dimensions (in mm)
DEFAULT_DOOR_WIDTH = 900   # 900mm standard door
DEFAULT_DOOR_DEPTH = 50    # Door thickness


def render_door_symbol(builder: SVGBuilder) -> None:
    """
    Create reusable door symbol in SVG defs.

    The symbol is a 1x1 unit that gets scaled when used.
    """
    symbol = builder.symbol("door-symbol", viewbox="0 0 100 100")

    # Door panel (line representing the door in open position)
    from xml.etree.ElementTree import SubElement
    line = SubElement(symbol, "line")
    line.set("x1", "0")
    line.set("y1", "0")
    line.set("x2", "100")
    line.set("y2", "0")
    line.set("stroke", "#000000")
    line.set("stroke-width", "3")

    # Swing arc (90 degree arc)
    path = SubElement(symbol, "path")
    path.set("d", "M 100,0 A 100,100 0 0,1 0,100")
    path.set("stroke", "#666666")
    path.set("stroke-width", "1")
    path.set("stroke-dasharray", "4,2")
    path.set("fill", "none")


def calculate_door_position(
    wall_start: Tuple[float, float],
    wall_end: Tuple[float, float],
    offset: float,
    door_width: float,
) -> Tuple[Tuple[float, float], float]:
    """
    Calculate door center position and rotation angle.

    Args:
        wall_start: (x, z) wall start point
        wall_end: (x, z) wall end point
        offset: Distance from wall start to door center
        door_width: Width of door

    Returns:
        ((x, z), angle) - center position and rotation in degrees
    """
    dx = wall_end[0] - wall_start[0]
    dz = wall_end[1] - wall_start[1]
    wall_length = math.sqrt(dx * dx + dz * dz)

    if wall_length == 0:
        return ((wall_start[0], wall_start[1]), 0)

    # Normalize direction
    ux = dx / wall_length
    uz = dz / wall_length

    # Position along wall
    cx = wall_start[0] + ux * offset
    cz = wall_start[1] + uz * offset

    # Angle (in degrees, for SVG rotation)
    angle = math.degrees(math.atan2(uz, ux))

    return ((cx, cz), angle)


def render_doors(
    builder: SVGBuilder,
    doors: List[Dict[str, Any]],
    walls: List[Dict[str, Any]],
    parent: Element,
    scale: float = 1.0,
    transform_y: bool = True,
    height: float = 0,
) -> Element:
    """
    Render doors in floor plan (LOD 2).

    Args:
        builder: SVG builder instance
        doors: List of door dictionaries from JSON
        walls: List of wall dictionaries (for position reference)
        parent: Parent SVG element
        scale: Scale factor (mm to points)
        transform_y: Whether to flip Y axis
        height: SVG height for Y transformation

    Returns:
        Group element containing all doors
    """
    door_style = get_element_style("doors")
    swing_style = get_element_style("door-swings")

    g = builder.group(parent=parent, class_="doors")

    for i, door in enumerate(doors):
        door_id = f"door-{i}"
        wall_idx = door.get("wall_index", 0)
        offset = door.get("offset", 0)
        width = door.get("width", DEFAULT_DOOR_WIDTH)
        swing = door.get("swing", "left")  # left, right, double

        # Get wall reference
        if wall_idx >= len(walls):
            continue

        wall = walls[wall_idx]
        start = wall.get("start", [0, 0, 0])
        end = wall.get("end", [0, 0, 0])

        # Calculate position
        wall_start = (start[0], start[2])
        wall_end = (end[0], end[2])
        (cx, cz), angle = calculate_door_position(wall_start, wall_end, offset, width)

        # Apply scale
        cx_scaled = cx * scale
        cz_scaled = cz * scale
        width_scaled = width * scale

        if transform_y:
            cz_scaled = height - cz_scaled
            angle = -angle  # Flip rotation for Y transform

        # Create door group
        door_g = builder.group(
            parent=g,
            id=door_id,
            class_="door",
            transform=f"translate({cx_scaled}, {cz_scaled}) rotate({angle})",
            data={
                "door-id": door_id,
                "wall-index": str(wall_idx),
                "width": str(width),
                "swing": swing,
            },
        )

        # Door opening (gap in wall) - white line to "cut" wall
        half_width = width_scaled / 2
        builder.line(
            -half_width, 0, half_width, 0,
            parent=door_g,
            stroke="#ffffff",
            stroke_width=12 * scale,  # Wall thickness
        )

        # Parse swing direction: "left_in", "right_in", "left_out", "right_out", "double"
        swing_lower = swing.lower() if swing else "left_in"
        is_left = "left" in swing_lower
        is_inward = "in" in swing_lower
        is_double = "double" in swing_lower

        # Door panel and swing arc
        if is_double:
            # Double door - two panels opening outward
            builder.line(
                -half_width, 0, 0, -half_width * 0.9,
                parent=door_g,
                stroke=door_style.get("stroke", "#000000"),
                stroke_width=door_style.get("stroke-width", 1) * 2,
            )
            builder.line(
                half_width, 0, 0, -half_width * 0.9,
                parent=door_g,
                stroke=door_style.get("stroke", "#000000"),
                stroke_width=door_style.get("stroke-width", 1) * 2,
            )
        else:
            # Single door - hinge at one end, swings to show open position
            # Door panel: line from hinge to door edge (90 degrees open)
            door_length = width_scaled * 0.9

            # Hinge position (left or right side of opening)
            hinge_x = -half_width if is_left else half_width

            # Door swings perpendicular to wall
            # Inward = negative Y (into room), Outward = positive Y
            swing_y = -door_length if is_inward else door_length

            # Draw door panel (line from hinge to door end)
            builder.line(
                hinge_x, 0,
                hinge_x, swing_y,
                parent=door_g,
                stroke=door_style.get("stroke", "#000000"),
                stroke_width=door_style.get("stroke-width", 1) * 2,
            )

            # Swing arc (quarter circle showing door path)
            # Arc from closed position (along wall) to open position (perpendicular)
            start_angle = 0 if is_left else 180  # Along wall
            if is_inward:
                end_angle = -90 if is_left else 270  # Perpendicular inward
            else:
                end_angle = 90 if is_left else -90  # Perpendicular outward

            arc_path = builder.arc_path(
                hinge_x, 0,
                door_length,
                start_angle,
                end_angle,
            )
            builder.path(
                arc_path,
                parent=door_g,
                stroke=swing_style.get("stroke", "#666666"),
                stroke_width=swing_style.get("stroke-width", 0.5),
                stroke_dasharray=swing_style.get("stroke-dasharray", "4,2"),
            )

    return g
