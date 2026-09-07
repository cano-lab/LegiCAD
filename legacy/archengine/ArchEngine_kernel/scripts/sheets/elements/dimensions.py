"""
Dimension line rendering for architectural floor plans.

Renders dimension lines with extension lines, arrows, and text labels.

Per DIMENSIONING.md spec:
- Dimension centerlines, not faces
- Reference points are building corner (0,0) by default
- Face-to-face/clear dimensions are computed, not stored
- LOD 1: Overall extents only
- LOD 2: Overall + major partition centerlines
- LOD 3: All centerlines, all openings
"""

import math
from typing import List, Dict, Any, Tuple, Optional, Set
from xml.etree.ElementTree import Element

from ..svg_builder import SVGBuilder
from ..lod_layers import get_element_style


# Dimension line constants (in points at 1:1 scale)
EXTENSION_LINE_GAP = 2       # Gap from object to extension line
EXTENSION_LINE_OVERSHOOT = 3  # How far extension line goes past dimension
ARROW_SIZE = 4               # Size of dimension arrows
TEXT_OFFSET = 6              # Distance from dimension line to text


def format_dimension(length_mm: float, show_units: bool = True) -> str:
    """
    Format dimension length to architectural notation.

    Args:
        length_mm: Length in millimeters
        show_units: Whether to show unit suffix

    Returns:
        Formatted string (e.g., "3,500" or "3.5m")
    """
    if length_mm >= 1000:
        # Show in meters for large dimensions
        meters = length_mm / 1000
        if meters == int(meters):
            return f"{int(meters)}m" if show_units else f"{int(meters)}"
        return f"{meters:.2f}m" if show_units else f"{meters:.2f}"
    else:
        # Show in millimeters
        return f"{int(length_mm)}mm" if show_units else f"{int(length_mm)}"


def get_centerline_position(wall: Dict[str, Any]) -> Tuple[float, float, float, float]:
    """
    Get wall centerline start and end positions.

    Args:
        wall: Wall dictionary with start/end coordinates

    Returns:
        (start_x, start_z, end_x, end_z) in mm - centerline coordinates
    """
    start = wall.get("start", [0, 0, 0])
    end = wall.get("end", [0, 0, 0])
    return (start[0], start[2], end[0], end[2])


def render_arrow(
    builder: SVGBuilder,
    x: float,
    y: float,
    angle: float,
    parent: Element,
    size: float = ARROW_SIZE,
) -> Element:
    """
    Render a dimension arrow head.

    Args:
        builder: SVG builder instance
        x, y: Arrow tip position
        angle: Arrow direction in degrees
        parent: Parent element
        size: Arrow size

    Returns:
        Polygon element
    """
    # Arrow points (pointing right, then rotated)
    rad = math.radians(angle)
    cos_a, sin_a = math.cos(rad), math.sin(rad)

    # Three points: tip, left barb, right barb
    points = [
        (x, y),
        (x - size * cos_a + size * 0.4 * sin_a, y - size * sin_a - size * 0.4 * cos_a),
        (x - size * cos_a - size * 0.4 * sin_a, y - size * sin_a + size * 0.4 * cos_a),
    ]

    dim_style = get_element_style("dimensions")
    return builder.polygon(
        points=points,
        parent=parent,
        fill=dim_style.get("stroke", "#0066cc"),
        stroke="none",
    )


def render_dimension_line(
    builder: SVGBuilder,
    start: Tuple[float, float],
    end: Tuple[float, float],
    offset: float,
    parent: Element,
    dimension_id: str,
    scale: float = 1.0,
) -> Element:
    """
    Render a single dimension line with extension lines and text.

    Args:
        builder: SVG builder instance
        start: (x, y) start point
        end: (x, y) end point
        offset: Distance to offset dimension line from object
        parent: Parent element
        dimension_id: ID for the dimension group
        scale: Scale factor

    Returns:
        Group element containing the dimension
    """
    dim_style = get_element_style("dimensions")
    text_style = get_element_style("dimension-text")

    # Calculate dimension geometry
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = math.sqrt(dx * dx + dy * dy)

    if length == 0:
        return builder.group(parent=parent)

    # Perpendicular direction for offset
    px = -dy / length
    py = dx / length

    # Offset points
    s_off = (start[0] + px * offset, start[1] + py * offset)
    e_off = (end[0] + px * offset, end[1] + py * offset)

    # Create dimension group
    g = builder.group(
        parent=parent,
        id=dimension_id,
        class_="dimension",
        data={
            "dim-id": dimension_id,
            "length": str(length / scale),  # Store in mm
        },
    )

    stroke_color = dim_style.get("stroke", "#0066cc")
    stroke_width = dim_style.get("stroke-width", 0.5)

    # Extension lines
    ext_start = (start[0] + px * EXTENSION_LINE_GAP, start[1] + py * EXTENSION_LINE_GAP)
    ext_end_s = (s_off[0] + px * EXTENSION_LINE_OVERSHOOT, s_off[1] + py * EXTENSION_LINE_OVERSHOOT)

    builder.line(
        ext_start[0], ext_start[1], ext_end_s[0], ext_end_s[1],
        parent=g,
        stroke=stroke_color,
        stroke_width=stroke_width,
    )

    ext_start2 = (end[0] + px * EXTENSION_LINE_GAP, end[1] + py * EXTENSION_LINE_GAP)
    ext_end_e = (e_off[0] + px * EXTENSION_LINE_OVERSHOOT, e_off[1] + py * EXTENSION_LINE_OVERSHOOT)

    builder.line(
        ext_start2[0], ext_start2[1], ext_end_e[0], ext_end_e[1],
        parent=g,
        stroke=stroke_color,
        stroke_width=stroke_width,
    )

    # Main dimension line
    builder.line(
        s_off[0], s_off[1], e_off[0], e_off[1],
        parent=g,
        stroke=stroke_color,
        stroke_width=stroke_width,
    )

    # Arrows
    angle = math.degrees(math.atan2(dy, dx))
    render_arrow(builder, s_off[0], s_off[1], angle, g, ARROW_SIZE * scale)
    render_arrow(builder, e_off[0], e_off[1], angle + 180, g, ARROW_SIZE * scale)

    # Dimension text
    mid_x = (s_off[0] + e_off[0]) / 2
    mid_y = (s_off[1] + e_off[1]) / 2

    # Offset text perpendicular to line
    text_x = mid_x + px * TEXT_OFFSET
    text_y = mid_y + py * TEXT_OFFSET

    # Format length (in mm)
    length_mm = length / scale
    text_content = format_dimension(length_mm)

    # Rotate text to follow dimension line
    text_angle = angle
    if text_angle > 90 or text_angle < -90:
        text_angle += 180  # Keep text readable

    builder.text(
        content=text_content,
        x=text_x,
        y=text_y,
        parent=g,
        font_size=text_style.get("font-size", 10),
        fill=text_style.get("fill", "#0066cc"),
        text_anchor=text_style.get("text-anchor", "middle"),
        dominant_baseline="middle",
        transform=f"rotate({text_angle}, {text_x}, {text_y})",
    )

    return g


def render_dimensions(
    builder: SVGBuilder,
    walls: List[Dict[str, Any]],
    parent: Element,
    scale: float = 1.0,
    transform_y: bool = True,
    height: float = 0,
    offset: float = 30,
) -> Element:
    """
    Auto-generate dimensions for all walls (LOD 3).

    Args:
        builder: SVG builder instance
        walls: List of wall dictionaries from JSON
        parent: Parent SVG element
        scale: Scale factor
        transform_y: Whether to flip Y axis
        height: SVG height for Y transformation
        offset: Distance to offset dimensions from walls

    Returns:
        Group element containing all dimensions
    """
    g = builder.group(parent=parent, class_="dimensions")

    for i, wall in enumerate(walls):
        start = wall.get("start", [0, 0, 0])
        end = wall.get("end", [0, 0, 0])

        # Use X and Z for plan view
        x1, z1 = start[0] * scale, start[2] * scale
        x2, z2 = end[0] * scale, end[2] * scale

        if transform_y:
            z1 = height - z1
            z2 = height - z2

        render_dimension_line(
            builder,
            start=(x1, z1),
            end=(x2, z2),
            offset=offset * scale,
            parent=g,
            dimension_id=f"dim-wall-{i}",
            scale=scale,
        )

    return g


def render_overall_dimensions(
    builder: SVGBuilder,
    walls: List[Dict[str, Any]],
    parent: Element,
    scale: float = 1.0,
    transform_y: bool = True,
    height: float = 0,
    margin: float = 60,
) -> Element:
    """
    Render overall building dimensions (LOD 3).

    Args:
        builder: SVG builder instance
        walls: List of wall dictionaries
        parent: Parent SVG element
        scale: Scale factor
        transform_y: Whether to flip Y axis
        height: SVG height for Y transformation
        margin: Distance from building edge

    Returns:
        Group element containing overall dimensions
    """
    from .walls import get_wall_bounds

    g = builder.group(parent=parent, class_="overall-dimensions")

    min_x, min_z, max_x, max_z = get_wall_bounds(walls)

    # Scale bounds
    min_x_s = min_x * scale
    max_x_s = max_x * scale
    min_z_s = min_z * scale
    max_z_s = max_z * scale

    if transform_y:
        min_z_s, max_z_s = height - max_z_s, height - min_z_s

    margin_s = margin * scale

    # Horizontal dimension (bottom)
    render_dimension_line(
        builder,
        start=(min_x_s, max_z_s + margin_s),
        end=(max_x_s, max_z_s + margin_s),
        offset=10,
        parent=g,
        dimension_id="dim-overall-x",
        scale=scale,
    )

    # Vertical dimension (left)
    render_dimension_line(
        builder,
        start=(min_x_s - margin_s, min_z_s),
        end=(min_x_s - margin_s, max_z_s),
        offset=10,
        parent=g,
        dimension_id="dim-overall-z",
        scale=scale,
    )

    return g


def render_centerline_chain(
    builder: SVGBuilder,
    walls: List[Dict[str, Any]],
    parent: Element,
    scale: float = 1.0,
    transform_y: bool = True,
    height: float = 0,
    axis: str = "x",  # "x" or "z"
    offset: float = 40,
    reference_point: Tuple[float, float] = (0, 0),
) -> Element:
    """
    Render a dimension chain showing incremental distances between centerlines.

    Per DIMENSIONING.md: "Dimension the decision (where things go), not the
    consequence (how big spaces end up). Centerlines are the decision."

    Shows distances BETWEEN consecutive centerline positions (like traditional
    dimension chains), not cumulative distances from origin.

    Args:
        builder: SVG builder instance
        walls: List of wall dictionaries
        parent: Parent SVG element
        scale: Scale factor
        transform_y: Whether to flip Y axis
        height: SVG height for Y transformation
        axis: Which axis to dimension ("x" or "z")
        offset: Distance from building edge
        reference_point: (x, z) reference point in mm (default: building corner)

    Returns:
        Group element containing the dimension chain
    """
    from .walls import get_wall_bounds

    dim_style = get_element_style("dimensions")
    text_style = get_element_style("dimension-text")
    g = builder.group(parent=parent, class_=f"centerline-chain-{axis}")

    min_x, min_z, max_x, max_z = get_wall_bounds(walls)

    # Collect unique positions along the axis (filter close duplicates)
    positions: Set[int] = set()  # Use int mm to avoid floating point duplicates
    for wall in walls:
        sx, sz, ex, ez = get_centerline_position(wall)
        if axis == "x":
            positions.add(round(sx))
            positions.add(round(ex))
        else:  # z axis
            positions.add(round(sz))
            positions.add(round(ez))

    # Sort positions and filter out positions too close together (< 500mm)
    sorted_positions = sorted(positions)
    filtered_positions = [sorted_positions[0]] if sorted_positions else []
    for pos in sorted_positions[1:]:
        if pos - filtered_positions[-1] >= 500:  # Min 500mm between dimension points
            filtered_positions.append(pos)

    if len(filtered_positions) < 2:
        return g

    offset_s = offset * scale
    stroke_color = dim_style.get("stroke", "#0066cc")
    stroke_width = dim_style.get("stroke-width", 0.5)
    font_size = text_style.get("font-size", 8)
    text_color = text_style.get("fill", "#0066cc")

    if axis == "x":
        # Horizontal chain along bottom
        chain_y = max_z * scale + offset_s

        # Draw tick marks at each position
        for pos in filtered_positions:
            x_s = pos * scale
            builder.line(
                x_s, chain_y - 4,
                x_s, chain_y + 4,
                parent=g,
                stroke=stroke_color,
                stroke_width=stroke_width,
            )

        # Draw dimension segments between consecutive positions
        for i in range(len(filtered_positions) - 1):
            x1 = filtered_positions[i] * scale
            x2 = filtered_positions[i + 1] * scale
            mid_x = (x1 + x2) / 2
            segment_length = filtered_positions[i + 1] - filtered_positions[i]

            # Dimension line segment
            builder.line(
                x1, chain_y,
                x2, chain_y,
                parent=g,
                stroke=stroke_color,
                stroke_width=stroke_width,
            )

            # Label showing distance between these two positions
            label = format_dimension(segment_length, show_units=False)
            builder.text(
                content=label,
                x=mid_x,
                y=chain_y - 6,
                parent=g,
                font_size=font_size,
                fill=text_color,
                text_anchor="middle",
                dominant_baseline="auto",
            )

    else:  # z axis
        # Vertical chain along left
        chain_x = min_x * scale - offset_s

        # Draw tick marks at each position
        for pos in filtered_positions:
            z_s = pos * scale
            builder.line(
                chain_x - 4, z_s,
                chain_x + 4, z_s,
                parent=g,
                stroke=stroke_color,
                stroke_width=stroke_width,
            )

        # Draw dimension segments between consecutive positions
        for i in range(len(filtered_positions) - 1):
            z1 = filtered_positions[i] * scale
            z2 = filtered_positions[i + 1] * scale
            mid_z = (z1 + z2) / 2
            segment_length = filtered_positions[i + 1] - filtered_positions[i]

            # Dimension line segment
            builder.line(
                chain_x, z1,
                chain_x, z2,
                parent=g,
                stroke=stroke_color,
                stroke_width=stroke_width,
            )

            # Label showing distance between these two positions
            label = format_dimension(segment_length, show_units=False)
            builder.text(
                content=label,
                x=chain_x - 6,
                y=mid_z,
                parent=g,
                font_size=font_size,
                fill=text_color,
                text_anchor="end",
                dominant_baseline="middle",
                transform=f"rotate(-90, {chain_x - 6}, {mid_z})",
            )

    return g


def render_opening_dimensions(
    builder: SVGBuilder,
    doors: List[Dict[str, Any]],
    windows: List[Dict[str, Any]],
    walls: List[Dict[str, Any]],
    parent: Element,
    scale: float = 1.0,
    transform_y: bool = True,
    height: float = 0,
) -> Element:
    """
    Render dimensions for door and window centerlines.

    Per DIMENSIONING.md: "Doors and windows dimensioned to centerline,
    referenced from nearest wall end or corner."

    Args:
        builder: SVG builder instance
        doors: List of door dictionaries
        windows: List of window dictionaries
        walls: List of wall dictionaries
        parent: Parent SVG element
        scale: Scale factor
        transform_y: Whether to flip Y axis
        height: SVG height for Y transformation

    Returns:
        Group element containing opening dimensions
    """
    dim_style = get_element_style("dimensions")
    text_style = get_element_style("dimension-text")
    g = builder.group(parent=parent, class_="opening-dimensions")

    # Process doors
    for i, door in enumerate(doors):
        wall_idx = door.get("wall_index", 0)
        offset = door.get("offset", 0)  # Distance from wall start to door center

        if wall_idx >= len(walls):
            continue

        wall = walls[wall_idx]
        sx, sz, ex, ez = get_centerline_position(wall)

        # Calculate door centerline position
        wall_dx = ex - sx
        wall_dz = ez - sz
        wall_len = math.sqrt(wall_dx**2 + wall_dz**2)

        if wall_len == 0:
            continue

        # Normalized direction
        ux = wall_dx / wall_len
        uz = wall_dz / wall_len

        # Door center position
        door_x = sx + ux * offset
        door_z = sz + uz * offset

        # Perpendicular offset for dimension
        px, pz = -uz, ux  # Perpendicular

        # Scale positions
        door_x_s = door_x * scale
        door_z_s = door_z * scale
        wall_start_x_s = sx * scale
        wall_start_z_s = sz * scale

        if transform_y:
            door_z_s = height - door_z_s
            wall_start_z_s = height - wall_start_z_s

        # Dimension from wall start to door centerline
        dim_offset = 20 * scale
        dim_y = door_z_s + pz * dim_offset

        # Small dimension annotation
        builder.text(
            content=format_dimension(offset),
            x=wall_start_x_s + (door_x_s - wall_start_x_s) / 2,
            y=dim_y,
            parent=g,
            font_size=text_style.get("font-size", 7),
            fill=text_style.get("fill", "#0066cc"),
            text_anchor="middle",
            dominant_baseline="middle",
            data={"opening-type": "door", "opening-index": str(i)},
        )

    # Similar logic for windows (abbreviated)
    for i, window in enumerate(windows):
        wall_idx = window.get("wall_index", 0)
        offset = window.get("offset", 0)

        if wall_idx >= len(walls):
            continue

        wall = walls[wall_idx]
        sx, sz, ex, ez = get_centerline_position(wall)

        wall_dx = ex - sx
        wall_dz = ez - sz
        wall_len = math.sqrt(wall_dx**2 + wall_dz**2)

        if wall_len == 0:
            continue

        ux = wall_dx / wall_len

        win_x = sx + ux * offset
        win_x_s = win_x * scale
        wall_start_x_s = sx * scale

        # Dimension label
        builder.text(
            content=format_dimension(offset),
            x=wall_start_x_s + (win_x_s - wall_start_x_s) / 2,
            y=height - sz * scale - 25 * scale if transform_y else sz * scale - 25 * scale,
            parent=g,
            font_size=text_style.get("font-size", 7),
            fill="#009900",  # Green for windows
            text_anchor="middle",
            dominant_baseline="middle",
            data={"opening-type": "window", "opening-index": str(i)},
        )

    return g


def render_coordinate_markers(
    builder: SVGBuilder,
    walls: List[Dict[str, Any]],
    parent: Element,
    scale: float = 1.0,
    transform_y: bool = True,
    height: float = 0,
) -> Element:
    """
    Render coordinate markers at unique wall endpoints.

    Shows (X, Z) coordinates in meters at each wall corner.

    Args:
        builder: SVG builder instance
        walls: List of wall dictionaries
        parent: Parent SVG element
        scale: Scale factor
        transform_y: Whether to flip Y axis
        height: SVG height for Y transformation

    Returns:
        Group element containing coordinate markers
    """
    coord_style = get_element_style("coordinates")
    g = builder.group(parent=parent, class_="coordinate-markers")

    # Collect unique points (within 1mm tolerance)
    unique_points = {}
    for wall in walls:
        start = wall.get("start", [0, 0, 0])
        end = wall.get("end", [0, 0, 0])

        for pt in [(start[0], start[2]), (end[0], end[2])]:
            # Round to nearest mm for uniqueness check
            key = (round(pt[0]), round(pt[1]))
            if key not in unique_points:
                unique_points[key] = pt

    # Render each coordinate marker
    for i, (key, (x_mm, z_mm)) in enumerate(unique_points.items()):
        x_s = x_mm * scale
        z_s = z_mm * scale

        if transform_y:
            z_s = height - z_s

        # Coordinate text (in meters)
        x_m = x_mm / 1000
        z_m = z_mm / 1000
        coord_text = f"({x_m:.2f}, {z_m:.2f})"

        # Small circle marker
        builder.circle(
            cx=x_s,
            cy=z_s,
            r=3,
            parent=g,
            fill=coord_style.get("marker-fill", "#cc0000"),
            stroke="none",
        )

        # Coordinate label
        builder.text(
            content=coord_text,
            x=x_s + 5,
            y=z_s - 5,
            parent=g,
            font_size=coord_style.get("font-size", 7),
            fill=coord_style.get("fill", "#cc0000"),
            text_anchor="start",
            dominant_baseline="auto",
            data={"coord-x": str(x_mm), "coord-z": str(z_mm)},
        )

    return g


def render_grid_system(
    builder: SVGBuilder,
    walls: List[Dict[str, Any]],
    parent: Element,
    scale: float = 1.0,
    transform_y: bool = True,
    height: float = 0,
    grid_spacing: float = 1000,  # Grid spacing in mm (default 1m)
    margin: float = 80,
) -> Element:
    """
    Render architectural grid system with column lines.

    Adds labeled grid lines (A, B, C... for X axis, 1, 2, 3... for Z axis)
    with bubble markers showing grid references.

    Args:
        builder: SVG builder instance
        walls: List of wall dictionaries
        parent: Parent SVG element
        scale: Scale factor
        transform_y: Whether to flip Y axis
        height: SVG height for Y transformation
        grid_spacing: Grid spacing in mm
        margin: Distance from building for grid bubbles

    Returns:
        Group element containing grid system
    """
    from .walls import get_wall_bounds

    grid_style = get_element_style("grid-lines")
    g = builder.group(parent=parent, class_="grid-system")

    min_x, min_z, max_x, max_z = get_wall_bounds(walls)

    # Round bounds to nearest grid
    grid_min_x = math.floor(min_x / grid_spacing) * grid_spacing
    grid_max_x = math.ceil(max_x / grid_spacing) * grid_spacing
    grid_min_z = math.floor(min_z / grid_spacing) * grid_spacing
    grid_max_z = math.ceil(max_z / grid_spacing) * grid_spacing

    margin_s = margin * scale
    bubble_r = 12

    # Vertical grid lines (X direction, labeled A, B, C...)
    x_lines_g = builder.group(parent=g, class_="grid-x-lines")
    x_pos = grid_min_x
    label_idx = 0

    while x_pos <= grid_max_x:
        x_s = x_pos * scale
        z_min_s = grid_min_z * scale
        z_max_s = grid_max_z * scale

        if transform_y:
            z_min_s, z_max_s = height - z_max_s, height - z_min_s

        # Grid line
        builder.line(
            x_s, z_min_s - 20, x_s, z_max_s + 20,
            parent=x_lines_g,
            stroke=grid_style.get("stroke", "#999999"),
            stroke_width=grid_style.get("stroke-width", 0.3),
            stroke_dasharray="10,5",
        )

        # Grid bubble at top
        label = chr(65 + label_idx)  # A, B, C...
        builder.circle(
            cx=x_s,
            cy=z_min_s - margin_s,
            r=bubble_r,
            parent=x_lines_g,
            stroke=grid_style.get("bubble-stroke", "#333333"),
            stroke_width=1.5,
            fill="#ffffff",
        )
        builder.text(
            content=label,
            x=x_s,
            y=z_min_s - margin_s,
            parent=x_lines_g,
            font_size=10,
            font_weight="bold",
            fill="#333333",
            text_anchor="middle",
            dominant_baseline="middle",
        )

        x_pos += grid_spacing
        label_idx += 1

    # Horizontal grid lines (Z direction, labeled 1, 2, 3...)
    z_lines_g = builder.group(parent=g, class_="grid-z-lines")
    z_pos = grid_min_z
    label_num = 1

    while z_pos <= grid_max_z:
        z_s = z_pos * scale
        x_min_s = grid_min_x * scale
        x_max_s = grid_max_x * scale

        if transform_y:
            z_s = height - z_s

        # Grid line
        builder.line(
            x_min_s - 20, z_s, x_max_s + 20, z_s,
            parent=z_lines_g,
            stroke=grid_style.get("stroke", "#999999"),
            stroke_width=grid_style.get("stroke-width", 0.3),
            stroke_dasharray="10,5",
        )

        # Grid bubble at left
        builder.circle(
            cx=x_min_s - margin_s,
            cy=z_s,
            r=bubble_r,
            parent=z_lines_g,
            stroke=grid_style.get("bubble-stroke", "#333333"),
            stroke_width=1.5,
            fill="#ffffff",
        )
        builder.text(
            content=str(label_num),
            x=x_min_s - margin_s,
            y=z_s,
            parent=z_lines_g,
            font_size=10,
            font_weight="bold",
            fill="#333333",
            text_anchor="middle",
            dominant_baseline="middle",
        )

        z_pos += grid_spacing
        label_num += 1

    return g
