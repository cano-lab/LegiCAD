"""
SVGBuilder-based section renderer for viewport integration.

Renders building sections using the existing generator logic
for geometry calculation and wall layer analysis.
"""

from typing import Dict, Any, Optional
from xml.etree.ElementTree import Element

from ..svg_builder import SVGBuilder
from .generator_adapters import get_section_data, Section
from .patterns import add_material_patterns, get_pattern_url


def render_section(
    builder: SVGBuilder,
    parent: Element,
    data: Dict[str, Any],
    direction: str,
    section_id: str,
    scale: float,
    offset_x: float,
    offset_y: float,
) -> None:
    """
    Render a building section into a viewport using SVGBuilder.

    Args:
        builder: SVGBuilder instance
        parent: Parent element (viewport content group)
        data: Building JSON data
        direction: "longitudinal" or "transverse"
        section_id: Section identifier (e.g., "A", "B")
        scale: Viewport scale factor (mm to points)
        offset_x, offset_y: Transform offsets for centering
    """
    # Ensure patterns are available
    add_material_patterns(builder)

    # Get section data using existing generator logic
    try:
        section = get_section_data(data, direction, None, section_id)
    except Exception as e:
        _render_error(builder, parent, f"Section error: {e}", offset_x, offset_y)
        return

    # Calculate section extents for Y-flip
    max_height = _get_section_height(section)
    flip_h = max_height * scale

    # Create main group with transform
    g = builder.group(
        parent=parent,
        id=f"section-{section_id}",
        class_="section-content",
        transform=f"translate({offset_x}, {offset_y})",
    )

    # Render LOD layers
    _render_lod1(builder, g, section, scale, flip_h)
    _render_lod2(builder, g, section, scale, flip_h)
    _render_lod3(builder, g, section, scale, flip_h)


def _get_section_height(section: Section) -> float:
    """Calculate the maximum height of the section for Y-flip."""
    max_h = 3000  # Default 3m

    # Check wall heights
    for wall in section.walls_cut:
        if wall.top_y > max_h:
            max_h = wall.top_y

    for wall in section.walls_beyond:
        if wall.top_y > max_h:
            max_h = wall.top_y

    # Check roof height
    if section.roof and section.roof.ridge_height > max_h:
        max_h = section.roof.ridge_height

    return max_h + 500  # Add margin


def _render_lod1(
    builder: SVGBuilder,
    parent: Element,
    section: Section,
    scale: float,
    flip_h: float,
) -> None:
    """
    LOD 1: Basic geometry - cut walls (poche), ground, roof outline.
    """
    g = builder.group(
        parent=parent,
        id="lod-1",
        class_="lod-layer lod-1",
        data={"lod": "1"},
    )

    # Ground line
    min_x = _get_section_min_x(section)
    max_x = _get_section_max_x(section)
    ground_y = flip_h  # Ground at bottom

    builder.line(
        (min_x - 500) * scale, ground_y,
        (max_x + 500) * scale, ground_y,
        parent=g,
        stroke="#666666",
        stroke_width=1.5,
    )

    # Cut walls (poche - filled solid or hatched)
    for wall in section.walls_cut:
        x = wall.x * scale
        y = flip_h - (wall.top_y * scale)
        w = wall.thickness * scale
        h = (wall.top_y - wall.bottom_y) * scale

        # Wall fill - solid gray for cut walls
        builder.rect(
            x=x,
            y=y,
            width=w,
            height=h,
            parent=g,
            stroke="#333333",
            stroke_width=1.5,
            fill="#e0e0e0",
            data={"type": "wall-cut", "exterior": str(wall.is_exterior)},
        )

    # Roof outline with fill
    if section.roof and section.roof.points:
        # Sort points by x to ensure proper polygon
        sorted_pts = sorted(section.roof.points, key=lambda p: p.x)

        # Create closed polygon for roof
        roof_points = []
        for pt in sorted_pts:
            px = pt.x * scale
            py = flip_h - (pt.y * scale)
            roof_points.append((px, py))

        if len(roof_points) >= 3:
            # Draw filled roof polygon
            builder.polygon(
                points=roof_points,
                parent=g,
                stroke="#333333",
                stroke_width=1.5,
                fill="#f0f0f0",
            )

            # Draw roof ridge line (thicker)
            ridge_idx = len(roof_points) // 2
            if ridge_idx > 0 and ridge_idx < len(roof_points):
                # Left slope
                builder.line(
                    roof_points[0][0], roof_points[0][1],
                    roof_points[ridge_idx][0], roof_points[ridge_idx][1],
                    parent=g,
                    stroke="#333333",
                    stroke_width=2,
                )
                # Right slope
                builder.line(
                    roof_points[ridge_idx][0], roof_points[ridge_idx][1],
                    roof_points[-1][0], roof_points[-1][1],
                    parent=g,
                    stroke="#333333",
                    stroke_width=2,
                )


def _render_lod2(
    builder: SVGBuilder,
    parent: Element,
    section: Section,
    scale: float,
    flip_h: float,
) -> None:
    """
    LOD 2: Secondary elements - walls beyond cut, openings, floors.
    """
    g = builder.group(
        parent=parent,
        id="lod-2",
        class_="lod-layer lod-2",
        data={"lod": "2"},
    )

    # Walls beyond cut (shown in elevation, not cut)
    for wall in section.walls_beyond:
        x = wall.start_x * scale
        w = (wall.end_x - wall.start_x) * scale
        y = flip_h - (wall.top_y * scale)
        h = (wall.top_y - wall.bottom_y) * scale

        builder.rect(
            x=x,
            y=y,
            width=w,
            height=h,
            parent=g,
            stroke="#666666",
            stroke_width=0.5,
            fill="white",
            data={"type": "wall-beyond"},
        )

    # Openings in walls beyond
    for opening in section.openings:
        x = (opening.center_x - opening.width / 2) * scale
        w = opening.width * scale
        y = flip_h - (opening.top_y * scale)
        h = (opening.top_y - opening.bottom_y) * scale

        if opening.is_door:
            builder.rect(
                x=x, y=y, width=w, height=h,
                parent=g,
                stroke="#333333",
                stroke_width=0.5,
                fill="#d4a574",
            )
        else:
            builder.rect(
                x=x, y=y, width=w, height=h,
                parent=g,
                stroke="#333333",
                stroke_width=0.5,
                fill="#cce5ff",
            )

    # Floor levels
    for floor in section.floor_levels:
        y = flip_h - (floor.y * scale)
        x1 = floor.start_x * scale
        x2 = floor.end_x * scale

        builder.line(
            x1, y, x2, y,
            parent=g,
            stroke="#333333",
            stroke_width=1,
        )

        # Floor level label
        builder.text(
            content=floor.label,
            x=x1 - 20 * scale,
            y=y,
            parent=g,
            font_size=6 * scale,
            text_anchor="end",
            dominant_baseline="middle",
            fill="#333333",
        )


def _render_lod3(
    builder: SVGBuilder,
    parent: Element,
    section: Section,
    scale: float,
    flip_h: float,
) -> None:
    """
    LOD 3: Details - wall layers with hatching, room labels.
    """
    g = builder.group(
        parent=parent,
        id="lod-3",
        class_="lod-layer lod-3",
        data={"lod": "3"},
    )

    # Wall layers with material hatching
    for wall in section.walls_cut:
        x_offset = wall.x * scale
        wall_bottom = flip_h - (wall.bottom_y * scale)
        wall_top = flip_h - (wall.top_y * scale)
        wall_height = wall_bottom - wall_top

        layer_x = x_offset
        for layer in wall.layers:
            layer_thickness = layer.get('thickness', 100) * scale
            layer_function = layer.get('function', 'structure')

            # Map function to pattern
            pattern_map = {
                'structure': 'hatch_45',
                'insulation': 'insulation',
                'sheathing': 'wood_grain',
                'cladding': 'siding',
                'drywall': 'hatch_45',
                'air_gap': None,
            }
            pattern = pattern_map.get(layer_function)

            fill = get_pattern_url(pattern) if pattern else "none"

            builder.rect(
                x=layer_x,
                y=wall_top,
                width=layer_thickness,
                height=wall_height,
                parent=g,
                stroke="#999999",
                stroke_width=0.25,
                fill=fill,
            )

            layer_x += layer_thickness

    # Room labels
    for room in section.room_labels:
        x = room.center_x * scale
        y = flip_h - (room.center_y * scale)

        builder.text(
            content=room.name.upper(),
            x=x,
            y=y,
            parent=g,
            font_size=8 * scale,
            text_anchor="middle",
            dominant_baseline="middle",
            fill="#333333",
            font_weight="bold",
        )


def _get_section_min_x(section: Section) -> float:
    """Get minimum X coordinate in section."""
    min_x = float('inf')
    for wall in section.walls_cut:
        if wall.x < min_x:
            min_x = wall.x
    for wall in section.walls_beyond:
        if wall.start_x < min_x:
            min_x = wall.start_x
    return min_x if min_x != float('inf') else 0


def _get_section_max_x(section: Section) -> float:
    """Get maximum X coordinate in section."""
    max_x = float('-inf')
    for wall in section.walls_cut:
        if wall.x + wall.thickness > max_x:
            max_x = wall.x + wall.thickness
    for wall in section.walls_beyond:
        if wall.end_x > max_x:
            max_x = wall.end_x
    return max_x if max_x != float('-inf') else 10000


def _render_error(
    builder: SVGBuilder,
    parent: Element,
    message: str,
    offset_x: float,
    offset_y: float,
) -> None:
    """Render an error message placeholder."""
    g = builder.group(parent=parent, class_="section-error")

    builder.text(
        content=f"[{message}]",
        x=offset_x + 50,
        y=offset_y + 50,
        parent=g,
        font_size=12,
        fill="#cc0000",
        font_style="italic",
    )


def get_section_bounds(data: Dict[str, Any], direction: str, section_id: str) -> tuple:
    """
    Get the bounds of a section for viewport sizing.

    Returns:
        (min_x, min_y, max_x, max_y) in model units (mm)
    """
    try:
        section = get_section_data(data, direction, None, section_id)
        min_x = _get_section_min_x(section)
        max_x = _get_section_max_x(section)
        max_h = _get_section_height(section)
        margin = 500

        return (
            min_x - margin,
            -margin,
            max_x + margin,
            max_h + margin,
        )
    except Exception:
        return (0, 0, 15000, 5000)
