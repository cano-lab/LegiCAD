"""
Window rendering for architectural floor plans.

Renders windows with proper wall openings and glass indication.
"""

import math
from typing import List, Dict, Any, Tuple
from xml.etree.ElementTree import Element

from ..svg_builder import SVGBuilder
from ..lod_layers import get_element_style


# Default window dimensions (in mm)
DEFAULT_WINDOW_WIDTH = 1200   # 1200mm standard window


def render_window_symbol(builder: SVGBuilder) -> None:
    """
    Create reusable window symbol in SVG defs.

    The symbol is a 1x1 unit that gets scaled when used.
    """
    symbol = builder.symbol("window-symbol", viewbox="0 0 100 20")

    from xml.etree.ElementTree import SubElement

    # Window frame (outer rectangle)
    rect = SubElement(symbol, "rect")
    rect.set("x", "0")
    rect.set("y", "0")
    rect.set("width", "100")
    rect.set("height", "20")
    rect.set("stroke", "#000000")
    rect.set("stroke-width", "1")
    rect.set("fill", "#e6f3ff")

    # Glass panes (center lines)
    line = SubElement(symbol, "line")
    line.set("x1", "50")
    line.set("y1", "0")
    line.set("x2", "50")
    line.set("y2", "20")
    line.set("stroke", "#000000")
    line.set("stroke-width", "0.5")


def calculate_window_position(
    wall_start: Tuple[float, float],
    wall_end: Tuple[float, float],
    offset: float,
    window_width: float,
) -> Tuple[Tuple[float, float], float]:
    """
    Calculate window center position and rotation angle.

    Args:
        wall_start: (x, z) wall start point
        wall_end: (x, z) wall end point
        offset: Distance from wall start to window center
        window_width: Width of window

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


def render_windows(
    builder: SVGBuilder,
    windows: List[Dict[str, Any]],
    walls: List[Dict[str, Any]],
    parent: Element,
    scale: float = 1.0,
    transform_y: bool = True,
    height: float = 0,
) -> Element:
    """
    Render windows in floor plan (LOD 2).

    Args:
        builder: SVG builder instance
        windows: List of window dictionaries from JSON
        walls: List of wall dictionaries (for position reference)
        parent: Parent SVG element
        scale: Scale factor (mm to points)
        transform_y: Whether to flip Y axis
        height: SVG height for Y transformation

    Returns:
        Group element containing all windows
    """
    window_style = get_element_style("windows")

    g = builder.group(parent=parent, class_="windows")

    for i, window in enumerate(windows):
        window_id = f"window-{i}"
        wall_idx = window.get("wall_index", 0)
        offset = window.get("offset", 0)
        width = window.get("width", DEFAULT_WINDOW_WIDTH)

        # Get wall reference
        if wall_idx >= len(walls):
            continue

        wall = walls[wall_idx]
        start = wall.get("start", [0, 0, 0])
        end = wall.get("end", [0, 0, 0])

        # Calculate position
        wall_start = (start[0], start[2])
        wall_end = (end[0], end[2])
        (cx, cz), angle = calculate_window_position(wall_start, wall_end, offset, width)

        # Apply scale
        cx_scaled = cx * scale
        cz_scaled = cz * scale
        width_scaled = width * scale
        wall_thickness = 10 * scale  # Simplified wall thickness for window display

        if transform_y:
            cz_scaled = height - cz_scaled
            angle = -angle

        # Create window group
        window_g = builder.group(
            parent=g,
            id=window_id,
            class_="window",
            transform=f"translate({cx_scaled}, {cz_scaled}) rotate({angle})",
            data={
                "window-id": window_id,
                "wall-index": str(wall_idx),
                "width": str(width),
            },
        )

        half_width = width_scaled / 2

        # Window opening (gap in wall)
        builder.line(
            -half_width, 0, half_width, 0,
            parent=window_g,
            stroke="#ffffff",
            stroke_width=wall_thickness + 4,
        )

        # Window frame rectangle
        builder.rect(
            x=-half_width,
            y=-wall_thickness / 2,
            width=width_scaled,
            height=wall_thickness,
            parent=window_g,
            stroke=window_style.get("stroke", "#000000"),
            stroke_width=window_style.get("stroke-width", 1),
            fill=window_style.get("fill", "#e6f3ff"),
        )

        # Glass pane dividers (for multi-pane windows)
        pane_count = max(1, int(width / 600))  # One pane per 600mm
        if pane_count > 1:
            pane_width = width_scaled / pane_count
            for p in range(1, pane_count):
                px = -half_width + p * pane_width
                builder.line(
                    px, -wall_thickness / 2,
                    px, wall_thickness / 2,
                    parent=window_g,
                    stroke="#000000",
                    stroke_width=0.5,
                )

        # Sill lines (outside edge indicators)
        builder.line(
            -half_width - 2, -wall_thickness / 2 - 2,
            half_width + 2, -wall_thickness / 2 - 2,
            parent=window_g,
            stroke="#000000",
            stroke_width=0.5,
        )

    return g
