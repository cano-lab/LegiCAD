"""
Enhanced dimensioning system for Archengine.

Features:
- Dimensions on all 4 sides (top, bottom, left, right)
- Metric units (millimeters and meters)
- Consolidated chains (skips small segments < 300mm)
- Clean spacing to avoid crowding
"""

import math
from typing import List, Dict, Any, Tuple, Optional
from xml.etree.ElementTree import Element

from ..svg_builder import SVGBuilder
from ..lod_layers import get_element_style
from .walls import get_wall_bounds


# Constants for metric dimensioning (in mm at 1:1 scale)
MIN_DIMENSION_SPACING = 300  # Skip segments smaller than 300mm (1 foot)
EXTENSION_LINE_GAP = 100     # Gap from wall to extension line
EXTENSION_LINE_OVERSHOOT = 50  # How far extension line extends past dimension
DIMENSION_LINE_OFFSET = 25   # Distance between dimension lines in a chain
ARROW_SIZE = 30              # Size of dimension arrows
TEXT_OFFSET = 60             # Distance from dimension line to text
OUTER_MARGIN = 200           # Distance for outermost dimension line


def format_metric_dimension(length_mm: float, use_meters: bool = True) -> str:
    """
    Format dimension in metric units.
    
    Args:
        length_mm: Length in millimeters
        use_meters: If True, use meters for lengths >= 1000mm
    
    Returns:
        Formatted string (e.g., "2400", "3.6 m", "450")
    """
    if use_meters and length_mm >= 1000:
        meters = length_mm / 1000
        # Show 1 decimal for non-whole meters
        if meters == int(meters):
            return f"{int(meters)} m"
        return f"{meters:.1f} m"
    else:
        # Millimeters, no decimals
        return f"{int(round(length_mm))}"


def get_unique_positions(walls: List[Dict[str, Any]], axis: str, min_spacing: float = MIN_DIMENSION_SPACING) -> List[float]:
    """
    Get unique positions along an axis, filtering out points too close together.
    
    Args:
        walls: List of wall dictionaries
        axis: "x" or "z"
        min_spacing: Minimum spacing between dimension points
    
    Returns:
        Sorted list of unique positions
    """
    positions = set()
    
    for wall in walls:
        start = wall.get("start", [0, 0, 0])
        end = wall.get("end", [0, 0, 0])
        
        if axis == "x":
            positions.add(round(start[0]))
            positions.add(round(end[0]))
        else:
            positions.add(round(start[2]))  # Z coordinate
            positions.add(round(end[2]))
    
    # Sort and filter
    sorted_positions = sorted(positions)
    if not sorted_positions:
        return []
    
    filtered = [sorted_positions[0]]
    for pos in sorted_positions[1:]:
        if pos - filtered[-1] >= min_spacing:
            filtered.append(pos)
    
    return filtered


def render_dimension_chain(
    builder: SVGBuilder,
    positions: List[float],
    fixed_coord: float,
    is_horizontal: bool,
    offset: float,
    parent: Element,
    scale: float,
    side: str,  # "top", "bottom", "left", "right"
    chain_index: int = 0,
) -> Element:
    """
    Render a single dimension chain.
    
    Args:
        builder: SVG builder
        positions: Sorted list of positions along the chain
        fixed_coord: Fixed coordinate for the chain (y for horizontal, x for vertical)
        is_horizontal: True for X-axis chain, False for Z-axis
        offset: Distance from building edge
        parent: Parent SVG element
        scale: Scale factor
        side: Which side of the building (affects arrow/text direction)
        chain_index: Index of this chain (for stacked chains)
    
    Returns:
        Group element
    """
    if len(positions) < 2:
        return builder.group(parent=parent)
    
    dim_style = get_element_style("dimensions")
    text_style = get_element_style("dimension-text")
    
    g = builder.group(parent=parent, class_=f"dimension-chain-{side}")
    
    # Calculate actual offset based on chain index
    actual_offset = offset + (chain_index * DIMENSION_LINE_OFFSET * scale)
    
    stroke_color = dim_style.get("stroke", "#000000")
    stroke_width = dim_style.get("stroke-width", 2) * scale
    font_size = text_style.get("font-size", 100) * scale
    text_color = text_style.get("fill", "#000000")
    
    if is_horizontal:
        # Horizontal dimension chain (top or bottom)
        y_pos = fixed_coord + (actual_offset if side == "bottom" else -actual_offset)
        
        # Draw dimension line connecting all positions
        x_start = positions[0] * scale
        x_end = positions[-1] * scale
        
        builder.line(
            x_start, y_pos,
            x_end, y_pos,
            parent=g,
            stroke=stroke_color,
            stroke_width=stroke_width,
        )
        
        # Draw arrows at ends
        arrow_y = y_pos
        render_arrow(builder, x_start, arrow_y, 180, g, ARROW_SIZE * scale, stroke_color)
        render_arrow(builder, x_end, arrow_y, 0, g, ARROW_SIZE * scale, stroke_color)
        
        # Draw extension lines and segment labels
        for i, pos in enumerate(positions):
            x_pos = pos * scale
            
            # Extension line (from building to dimension line)
            ext_start_y = fixed_coord + (EXTENSION_LINE_GAP * scale if side == "bottom" else -EXTENSION_LINE_GAP * scale)
            ext_end_y = y_pos + (EXTENSION_LINE_OVERSHOOT * scale if side == "bottom" else -EXTENSION_LINE_OVERSHOOT * scale)
            
            builder.line(
                x_pos, ext_start_y,
                x_pos, ext_end_y,
                parent=g,
                stroke=stroke_color,
                stroke_width=stroke_width * 0.5,
            )
            
            # Draw segment dimension text
            if i < len(positions) - 1:
                next_pos = positions[i + 1]
                segment_length = next_pos - pos
                mid_x = (x_pos + next_pos * scale) / 2
                
                # Skip very small segments
                if segment_length >= MIN_DIMENSION_SPACING:
                    label = format_metric_dimension(segment_length)
                    text_y = y_pos + (TEXT_OFFSET * scale if side == "bottom" else -TEXT_OFFSET * scale)
                    
                    builder.text(
                        content=label,
                        x=mid_x,
                        y=text_y,
                        parent=g,
                        font_size=font_size,
                        fill=text_color,
                        text_anchor="middle",
                        dominant_baseline="middle",
                    )
    
    else:
        # Vertical dimension chain (left or right)
        x_pos = fixed_coord + (actual_offset if side == "right" else -actual_offset)
        
        # Draw dimension line
        y_start = positions[0] * scale
        y_end = positions[-1] * scale
        
        builder.line(
            x_pos, y_start,
            x_pos, y_end,
            parent=g,
            stroke=stroke_color,
            stroke_width=stroke_width,
        )
        
        # Draw arrows
        render_arrow(builder, x_pos, y_start, -90, g, ARROW_SIZE * scale, stroke_color)
        render_arrow(builder, x_pos, y_end, 90, g, ARROW_SIZE * scale, stroke_color)
        
        # Draw extension lines and segment labels
        for i, pos in enumerate(positions):
            y_pos = pos * scale
            
            # Extension line
            ext_start_x = fixed_coord + (EXTENSION_LINE_GAP * scale if side == "right" else -EXTENSION_LINE_GAP * scale)
            ext_end_x = x_pos + (EXTENSION_LINE_OVERSHOOT * scale if side == "right" else -EXTENSION_LINE_OVERSHOOT * scale)
            
            builder.line(
                ext_start_x, y_pos,
                ext_end_x, y_pos,
                parent=g,
                stroke=stroke_color,
                stroke_width=stroke_width * 0.5,
            )
            
            # Draw segment dimension text
            if i < len(positions) - 1:
                next_pos = positions[i + 1]
                segment_length = next_pos - pos
                mid_y = (y_pos + next_pos * scale) / 2
                
                if segment_length >= MIN_DIMENSION_SPACING:
                    label = format_metric_dimension(segment_length)
                    text_x = x_pos + (TEXT_OFFSET * scale if side == "right" else -TEXT_OFFSET * scale)
                    
                    builder.text(
                        content=label,
                        x=text_x,
                        y=mid_y,
                        parent=g,
                        font_size=font_size,
                        fill=text_color,
                        text_anchor="middle",
                        dominant_baseline="middle",
                        transform=f"rotate(-90, {text_x}, {mid_y})",
                    )
    
    return g


def render_arrow(
    builder: SVGBuilder,
    x: float,
    y: float,
    angle: float,
    parent: Element,
    size: float,
    color: str,
) -> Element:
    """Render a dimension arrow head."""
    rad = math.radians(angle)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    
    # Arrow points (pointing along angle)
    points = [
        (x, y),
        (x - size * cos_a + size * 0.3 * sin_a, y - size * sin_a - size * 0.3 * cos_a),
        (x - size * cos_a - size * 0.3 * sin_a, y - size * sin_a + size * 0.3 * cos_a),
    ]
    
    return builder.polygon(
        points=points,
        parent=parent,
        fill=color,
        stroke="none",
    )


def render_complete_dimensions(
    builder: SVGBuilder,
    walls: List[Dict[str, Any]],
    parent: Element,
    scale: float = 1.0,
    transform_y: bool = True,
    height: float = 0,
) -> Element:
    """
    Render complete dimension set on all 4 sides.
    
    Creates:
    - Inner chain: major structural divisions (centerlines)
    - Outer chain: overall building extents
    
    Args:
        builder: SVG builder
        walls: List of wall dictionaries
        parent: Parent SVG element
        scale: Scale factor
        transform_y: Whether to flip Y axis (for SVG coordinate system)
        height: SVG height for Y transformation
    
    Returns:
        Group element containing all dimensions
    """
    g = builder.group(parent=parent, class_="complete-dimensions")
    
    # Get building bounds
    min_x, min_z, max_x, max_z = get_wall_bounds(walls)
    
    # Get unique positions along each axis
    x_positions = get_unique_positions(walls, "x")
    z_positions = get_unique_positions(walls, "z")
    
    if transform_y:
        # Flip for SVG coordinates
        min_z_render = height - max_z
        max_z_render = height - min_z
    else:
        min_z_render = min_z
        max_z_render = max_z
    
    # Scale positions if needed
    if scale != 1.0:
        min_x_s = min_x * scale
        max_x_s = max_x * scale
        min_z_s = min_z * scale
        max_z_s = max_z * scale
    else:
        min_x_s, max_x_s, min_z_s, max_z_s = min_x, max_x, min_z, max_z
    
    # === HORIZONTAL DIMENSIONS (X axis) ===
    
    # Bottom dimension chain (structural divisions)
    if len(x_positions) > 2:  # Only if there are internal divisions
        render_dimension_chain(
            builder, x_positions, max_z_s, True,
            DIMENSION_LINE_OFFSET * 3, g, scale, "bottom", 0
        )
    
    # Bottom overall dimension
    render_dimension_chain(
        builder, [min_x, max_x], max_z_s, True,
        OUTER_MARGIN, g, scale, "bottom", 1
    )
    
    # Top dimension chain (structural divisions)
    if len(x_positions) > 2:
        render_dimension_chain(
            builder, x_positions, min_z_s, True,
            DIMENSION_LINE_OFFSET * 3, g, scale, "top", 0
        )
    
    # Top overall dimension
    render_dimension_chain(
        builder, [min_x, max_x], min_z_s, True,
        OUTER_MARGIN, g, scale, "top", 1
    )
    
    # === VERTICAL DIMENSIONS (Z axis) ===
    
    # Left dimension chain (structural divisions)
    if len(z_positions) > 2:
        render_dimension_chain(
            builder, z_positions, min_x_s, False,
            DIMENSION_LINE_OFFSET * 3, g, scale, "left", 0
        )
    
    # Left overall dimension
    render_dimension_chain(
        builder, [min_z, max_z], min_x_s, False,
        OUTER_MARGIN, g, scale, "left", 1
    )
    
    # Right dimension chain (structural divisions)
    if len(z_positions) > 2:
        render_dimension_chain(
            builder, z_positions, max_x_s, False,
            DIMENSION_LINE_OFFSET * 3, g, scale, "right", 0
        )
    
    # Right overall dimension
    render_dimension_chain(
        builder, [min_z, max_z], max_x_s, False,
        OUTER_MARGIN, g, scale, "right", 1
    )
    
    return g


def render_opening_dimensions_metric(
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
    Render door and window dimensions in metric.
    
    Shows distance from wall start to opening centerline.
    """
    dim_style = get_element_style("dimensions")
    text_style = get_element_style("dimension-text")
    g = builder.group(parent=parent, class_="opening-dimensions-metric")
    
    stroke_color = dim_style.get("stroke", "#000000")
    font_size = text_style.get("font-size", 80) * scale
    text_color = text_style.get("fill", "#0066cc")
    
    # Process doors
    for i, door in enumerate(doors):
        wall_idx = door.get("wall_index", 0)
        offset = door.get("offset", 0)
        
        if wall_idx >= len(walls):
            continue
        
        wall = walls[wall_idx]
        start = wall.get("start", [0, 0, 0])
        end = wall.get("end", [0, 0, 0])
        
        # Calculate door center position
        sx, sz = start[0], start[2]
        ex, ez = end[0], end[2]
        
        wall_dx = ex - sx
        wall_dz = ez - sz
        wall_len = math.sqrt(wall_dx**2 + wall_dz**2)
        
        if wall_len == 0:
            continue
        
        # Door center
        ux, uz = wall_dx / wall_len, wall_dz / wall_len
        door_x = sx + ux * offset
        door_z = sz + uz * offset
        
        # Position for dimension text (offset from wall)
        px, pz = -uz, ux  # Perpendicular
        text_offset = 150 * scale
        
        door_x_s = door_x * scale
        door_z_s = door_z * scale
        
        if transform_y:
            door_z_s = height - door_z_s
        
        # Door size label
        door_width = door.get("width", 914)
        label = f"D {format_metric_dimension(door_width)}"
        
        builder.text(
            content=label,
            x=door_x_s + px * text_offset,
            y=door_z_s + pz * text_offset,
            parent=g,
            font_size=font_size,
            fill=text_color,
            text_anchor="middle",
            dominant_baseline="middle",
        )
    
    # Process windows (similar logic, abbreviated)
    for i, window in enumerate(windows):
        wall_idx = window.get("wall_index", 0)
        offset = window.get("offset", 0)
        
        if wall_idx >= len(walls):
            continue
        
        wall = walls[wall_idx]
        start = wall.get("start", [0, 0, 0])
        end = wall.get("end", [0, 0, 0])
        
        sx, sz = start[0], start[2]
        ex, ez = end[0], end[2]
        
        wall_dx = ex - sx
        wall_dz = ez - sz
        wall_len = math.sqrt(wall_dx**2 + wall_dz**2)
        
        if wall_len == 0:
            continue
        
        ux, uz = wall_dx / wall_len, wall_dz / wall_len
        win_x = sx + ux * offset
        win_z = sz + uz * offset
        
        px, pz = -uz, ux
        text_offset = 150 * scale
        
        win_x_s = win_x * scale
        win_z_s = win_z * scale
        
        if transform_y:
            win_z_s = height - win_z_s
        
        win_width = window.get("width", 1200)
        label = f"W {format_metric_dimension(win_width)}"
        
        builder.text(
            content=label,
            x=win_x_s + px * text_offset,
            y=win_z_s + pz * text_offset,
            parent=g,
            font_size=font_size,
            fill="#009900",  # Green for windows
            text_anchor="middle",
            dominant_baseline="middle",
        )
    
    return g
