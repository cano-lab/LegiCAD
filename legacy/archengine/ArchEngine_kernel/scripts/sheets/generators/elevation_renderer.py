"""
SVGBuilder-based elevation renderer for viewport integration.

Renders building elevations (North, South, East, West) using
the existing generator logic for geometry calculation.
"""

from typing import Dict, Any
from xml.etree.ElementTree import Element

from ..svg_builder import SVGBuilder
from .generator_adapters import get_elevation_data, Elevation
from .patterns import add_material_patterns, get_pattern_url


def render_elevation(
    builder: SVGBuilder,
    parent: Element,
    data: Dict[str, Any],
    direction: str,
    scale: float,
    offset_x: float,
    offset_y: float,
) -> None:
    """
    Render an elevation into a viewport using SVGBuilder.

    Args:
        builder: SVGBuilder instance
        parent: Parent element (viewport content group)
        data: Building JSON data
        direction: "north", "south", "east", or "west"
        scale: Viewport scale factor (mm to points)
        offset_x, offset_y: Transform offsets for centering
    """
    # Ensure patterns are available
    add_material_patterns(builder)

    # Get elevation data using existing generator logic
    try:
        elevation = get_elevation_data(data, direction)
    except Exception as e:
        # If elevation generation fails, render error placeholder
        _render_error(builder, parent, f"Elevation error: {e}", offset_x, offset_y)
        return

    # Create main group with transform
    # Y-axis flip: elevation Y=0 at ground (bottom), SVG Y=0 at top
    g = builder.group(
        parent=parent,
        id=f"elevation-{direction}",
        class_="elevation-content",
        transform=f"translate({offset_x}, {offset_y})",
    )

    # Render LOD layers
    _render_lod1(builder, g, elevation, scale)
    _render_lod2(builder, g, elevation, scale)
    _render_lod3(builder, g, elevation, scale)


def _render_lod1(
    builder: SVGBuilder,
    parent: Element,
    elevation: Elevation,
    scale: float,
) -> None:
    """
    LOD 1: Basic geometry - wall outlines, ground line, roof outline.
    """
    g = builder.group(
        parent=parent,
        id="lod-1",
        class_="lod-layer lod-1",
        data={"lod": "1"},
    )

    # Calculate flip height (elevation height in SVG coords)
    flip_h = elevation.height * scale

    # Ground line
    ground_margin = 200 * scale
    builder.line(
        -ground_margin, flip_h,
        (elevation.width * scale) + ground_margin, flip_h,
        parent=g,
        stroke="#666666",
        stroke_width=1.5,
    )

    # Wall outlines
    for wall in elevation.walls:
        x = wall.start_x * scale
        w = (wall.end_x - wall.start_x) * scale
        # Flip Y: SVG y = flip_h - elevation_y
        y = flip_h - (wall.top_y * scale)
        h = (wall.top_y - wall.bottom_y) * scale

        builder.rect(
            x=x,
            y=y,
            width=w,
            height=h,
            parent=g,
            stroke="#333333",
            stroke_width=1.5,
            fill="white",
            data={"type": "wall"},
        )

    # Roof outline
    if elevation.roof_edges:
        for edge in elevation.roof_edges:
            x1 = edge.start.x * scale
            y1 = flip_h - (edge.start.y * scale)
            x2 = edge.end.x * scale
            y2 = flip_h - (edge.end.y * scale)

            builder.line(
                x1, y1, x2, y2,
                parent=g,
                stroke="#333333",
                stroke_width=1.5,
            )


def _render_lod2(
    builder: SVGBuilder,
    parent: Element,
    elevation: Elevation,
    scale: float,
) -> None:
    """
    LOD 2: Openings - doors and windows with basic representation.
    """
    g = builder.group(
        parent=parent,
        id="lod-2",
        class_="lod-layer lod-2",
        data={"lod": "2"},
    )

    flip_h = elevation.height * scale

    for opening in elevation.openings:
        x = (opening.center_x - opening.width / 2) * scale
        w = opening.width * scale
        # Flip Y
        y = flip_h - (opening.top_y * scale)
        h = (opening.top_y - opening.bottom_y) * scale

        if opening.is_door:
            # Door - wood color fill
            builder.rect(
                x=x,
                y=y,
                width=w,
                height=h,
                parent=g,
                stroke="#333333",
                stroke_width=1,
                fill="#d4a574",
                data={"type": "door", "opening-type": opening.opening_type},
            )
            # Door panel lines
            panel_inset = 3 * scale
            builder.rect(
                x=x + panel_inset,
                y=y + panel_inset,
                width=w - 2 * panel_inset,
                height=h * 0.4,
                parent=g,
                stroke="#8b6914",
                stroke_width=0.5,
                fill="none",
            )
            builder.rect(
                x=x + panel_inset,
                y=y + h * 0.5,
                width=w - 2 * panel_inset,
                height=h * 0.45,
                parent=g,
                stroke="#8b6914",
                stroke_width=0.5,
                fill="none",
            )
        else:
            # Window - glass fill
            builder.rect(
                x=x,
                y=y,
                width=w,
                height=h,
                parent=g,
                stroke="#333333",
                stroke_width=1,
                fill="#cce5ff",
                data={"type": "window"},
            )
            # Window frame
            frame = 2 * scale
            builder.rect(
                x=x + frame,
                y=y + frame,
                width=w - 2 * frame,
                height=h - 2 * frame,
                parent=g,
                stroke="#666666",
                stroke_width=0.5,
                fill="none",
            )
            # Window mullion (center vertical)
            builder.line(
                x + w / 2, y + frame,
                x + w / 2, y + h - frame,
                parent=g,
                stroke="#666666",
                stroke_width=0.5,
            )


def _render_lod3(
    builder: SVGBuilder,
    parent: Element,
    elevation: Elevation,
    scale: float,
) -> None:
    """
    LOD 3: Details - level markers, material indications.
    """
    g = builder.group(
        parent=parent,
        id="lod-3",
        class_="lod-layer lod-3",
        data={"lod": "3"},
    )

    flip_h = elevation.height * scale
    marker_offset = -80 * scale  # Position markers to the left

    for marker in elevation.level_markers:
        y = flip_h - (marker.y * scale)

        # Level line (dashed for non-major)
        if marker.is_major:
            builder.line(
                marker_offset + 20 * scale, y,
                (elevation.width * scale) + 50 * scale, y,
                parent=g,
                stroke="#666666",
                stroke_width=0.5,
            )
        else:
            builder.line(
                marker_offset + 20 * scale, y,
                (elevation.width * scale) + 50 * scale, y,
                parent=g,
                stroke="#999999",
                stroke_width=0.3,
                stroke_dasharray="4,2",
            )

        # Level circle marker
        builder.circle(
            cx=marker_offset,
            cy=y,
            r=8 * scale,
            parent=g,
            stroke="#333333",
            stroke_width=0.5,
            fill="white",
        )

        # Level text
        builder.text(
            content=marker.label[:3],  # Abbreviate
            x=marker_offset,
            y=y,
            parent=g,
            font_size=5 * scale,
            text_anchor="middle",
            dominant_baseline="middle",
            fill="#333333",
        )

        # Elevation value
        height_m = marker.y / 1000
        builder.text(
            content=f"{height_m:.2f}",
            x=marker_offset,
            y=y + 12 * scale,
            parent=g,
            font_size=4 * scale,
            text_anchor="middle",
            fill="#666666",
        )


def _render_error(
    builder: SVGBuilder,
    parent: Element,
    message: str,
    offset_x: float,
    offset_y: float,
) -> None:
    """Render an error message placeholder."""
    g = builder.group(parent=parent, class_="elevation-error")

    builder.text(
        content=f"[{message}]",
        x=offset_x + 50,
        y=offset_y + 50,
        parent=g,
        font_size=12,
        fill="#cc0000",
        font_style="italic",
    )


def get_elevation_bounds(data: Dict[str, Any], direction: str) -> tuple:
    """
    Get the bounds of an elevation for viewport sizing.

    Returns:
        (min_x, min_y, max_x, max_y) in model units (mm)
    """
    try:
        elevation = get_elevation_data(data, direction)
        # Add margin around elevation
        margin = 300  # mm
        return (
            -margin,
            -margin,
            elevation.width + margin,
            elevation.height + margin,
        )
    except Exception:
        # Default bounds if elevation fails
        return (0, 0, 10000, 5000)
