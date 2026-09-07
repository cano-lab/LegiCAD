"""
SVGBuilder-based detail renderer for viewport integration.

Renders construction details (wall sections, eave, window, door)
using the existing generator logic for assembly information.
"""

from typing import Dict, Any, List
from xml.etree.ElementTree import Element

from ..svg_builder import SVGBuilder
from .generator_adapters import get_detail_data, Detail, Layer
from .patterns import add_material_patterns, get_pattern_url


def render_detail(
    builder: SVGBuilder,
    parent: Element,
    data: Dict[str, Any],
    detail_id: str,
    scale: float,
    offset_x: float,
    offset_y: float,
) -> None:
    """
    Render a construction detail into a viewport using SVGBuilder.

    Args:
        builder: SVGBuilder instance
        parent: Parent element (viewport content group)
        data: Building JSON data
        detail_id: Detail identifier ("1", "2", "3", "4" or name)
        scale: Viewport scale factor (ignored - details use fixed scale)
        offset_x, offset_y: Transform offsets for positioning
    """
    # Ensure patterns are available
    add_material_patterns(builder)

    # Details use fixed drawing scale, not model scale
    # Use 1.0 for direct point-based rendering
    drawing_scale = 1.0

    # Get detail data
    try:
        detail = get_detail_data(data, detail_id)
    except Exception as e:
        _render_error(builder, parent, f"Detail error: {e}", offset_x, offset_y)
        return

    # Create main group - position at viewport origin with margin
    g = builder.group(
        parent=parent,
        id=f"detail-{detail_id}",
        class_="detail-content",
        transform=f"translate({offset_x + 20}, {offset_y + 20})",
    )

    # Render based on detail type
    if "wall" in detail.name.lower() or detail_id == "1":
        _render_wall_section_detail(builder, g, data, drawing_scale)
    elif "eave" in detail.name.lower() or detail_id == "2":
        _render_eave_detail(builder, g, drawing_scale)
    elif "window" in detail.name.lower() or detail_id == "3":
        _render_window_detail(builder, g, drawing_scale)
    elif "door" in detail.name.lower() or detail_id == "4":
        _render_door_detail(builder, g, drawing_scale)
    else:
        # Generic detail placeholder
        _render_generic_detail(builder, g, detail, drawing_scale)


def _render_wall_section_detail(
    builder: SVGBuilder,
    parent: Element,
    data: Dict[str, Any],
    scale: float,
) -> None:
    """Render a typical wall section detail from foundation to eave."""
    # Get wall layers from data
    wall_types = data.get('wall_types', [])
    layers = _get_wall_layers(wall_types)

    total_thickness = sum(l.thickness for l in layers)

    # Detail dimensions (scaled)
    detail_width = 400 * scale
    detail_height = 600 * scale

    # Key positions
    center_x = detail_width / 2
    wall_left = center_x - (total_thickness * scale) / 2

    # Vertical positions
    roof_top = 20 * scale
    wall_top = 80 * scale
    floor_level = 380 * scale
    grade_level = 420 * scale
    foundation_bottom = 540 * scale

    # Draw layers
    layer_x = wall_left
    for layer in layers:
        layer_w = layer.thickness * scale
        layer_h = floor_level - wall_top

        # Get pattern for material
        fill = get_pattern_url(layer.material)

        builder.rect(
            x=layer_x,
            y=wall_top,
            width=layer_w,
            height=layer_h,
            parent=parent,
            stroke="#333333",
            stroke_width=0.5,
            fill=fill,
        )

        layer_x += layer_w

    # Floor/foundation line
    builder.rect(
        x=wall_left - 20 * scale,
        y=floor_level,
        width=total_thickness * scale + 40 * scale,
        height=40 * scale,
        parent=parent,
        stroke="#333333",
        stroke_width=1,
        fill=get_pattern_url("concrete"),
    )

    # Foundation wall
    foundation_width = 200 * scale
    builder.rect(
        x=center_x - foundation_width / 2,
        y=grade_level,
        width=foundation_width,
        height=foundation_bottom - grade_level,
        parent=parent,
        stroke="#333333",
        stroke_width=1,
        fill=get_pattern_url("concrete"),
    )

    # Grade line
    builder.line(
        0, grade_level,
        wall_left - 30 * scale, grade_level,
        parent=parent,
        stroke="#666666",
        stroke_width=1,
    )
    builder.line(
        layer_x + 30 * scale, grade_level,
        detail_width, grade_level,
        parent=parent,
        stroke="#666666",
        stroke_width=1,
    )

    # Dimension labels
    _render_dimension_vertical(
        builder, parent,
        layer_x + 40 * scale,
        wall_top, floor_level,
        "WALL",
        scale,
    )

    # Title
    builder.text(
        content="WALL SECTION",
        x=center_x,
        y=detail_height - 20 * scale,
        parent=parent,
        font_size=10 * scale,
        font_weight="bold",
        text_anchor="middle",
        fill="#333333",
    )


def _render_eave_detail(
    builder: SVGBuilder,
    parent: Element,
    scale: float,
) -> None:
    """Render an eave/fascia detail."""
    # Simplified eave detail
    center_x = 200 * scale
    detail_height = 300 * scale

    # Roof rafters (angled)
    rafter_y = 80 * scale
    for i in range(3):
        x_offset = i * 50 * scale
        builder.line(
            center_x - 100 * scale + x_offset, rafter_y,
            center_x + 50 * scale + x_offset, rafter_y + 100 * scale,
            parent=parent,
            stroke="#333333",
            stroke_width=2,
        )

    # Fascia board
    builder.rect(
        x=center_x + 40 * scale,
        y=rafter_y + 80 * scale,
        width=20 * scale,
        height=80 * scale,
        parent=parent,
        stroke="#333333",
        stroke_width=1,
        fill=get_pattern_url("wood"),
    )

    # Soffit
    builder.rect(
        x=center_x - 60 * scale,
        y=rafter_y + 140 * scale,
        width=120 * scale,
        height=10 * scale,
        parent=parent,
        stroke="#333333",
        stroke_width=0.5,
        fill="#e0e0e0",
    )

    # Title
    builder.text(
        content="EAVE DETAIL",
        x=center_x,
        y=detail_height - 20 * scale,
        parent=parent,
        font_size=10 * scale,
        font_weight="bold",
        text_anchor="middle",
        fill="#333333",
    )


def _render_window_detail(
    builder: SVGBuilder,
    parent: Element,
    scale: float,
) -> None:
    """Render a window head/sill detail."""
    center_x = 200 * scale
    detail_height = 300 * scale

    window_y = 60 * scale
    window_h = 180 * scale

    # Wall section (simplified)
    wall_left = center_x - 80 * scale
    wall_right = center_x + 80 * scale

    builder.rect(
        x=wall_left,
        y=20 * scale,
        width=160 * scale,
        height=40 * scale,
        parent=parent,
        stroke="#333333",
        stroke_width=1,
        fill=get_pattern_url("hatch_45"),
    )

    # Window frame
    builder.rect(
        x=center_x - 60 * scale,
        y=window_y,
        width=120 * scale,
        height=window_h,
        parent=parent,
        stroke="#333333",
        stroke_width=1.5,
        fill="#cce5ff",
    )

    # Frame members
    builder.rect(
        x=center_x - 60 * scale,
        y=window_y,
        width=10 * scale,
        height=window_h,
        parent=parent,
        stroke="#333333",
        stroke_width=0.5,
        fill="#d4a574",
    )
    builder.rect(
        x=center_x + 50 * scale,
        y=window_y,
        width=10 * scale,
        height=window_h,
        parent=parent,
        stroke="#333333",
        stroke_width=0.5,
        fill="#d4a574",
    )

    # Sill section
    builder.rect(
        x=wall_left,
        y=window_y + window_h,
        width=160 * scale,
        height=40 * scale,
        parent=parent,
        stroke="#333333",
        stroke_width=1,
        fill=get_pattern_url("hatch_45"),
    )

    # Title
    builder.text(
        content="WINDOW DETAIL",
        x=center_x,
        y=detail_height - 20 * scale,
        parent=parent,
        font_size=10 * scale,
        font_weight="bold",
        text_anchor="middle",
        fill="#333333",
    )


def _render_door_detail(
    builder: SVGBuilder,
    parent: Element,
    scale: float,
) -> None:
    """Render a door head/threshold detail."""
    center_x = 200 * scale
    detail_height = 300 * scale

    door_y = 40 * scale
    door_h = 200 * scale

    # Wall sections
    wall_w = 140 * scale
    builder.rect(
        x=center_x - 80 * scale,
        y=20 * scale,
        width=wall_w,
        height=20 * scale,
        parent=parent,
        stroke="#333333",
        stroke_width=1,
        fill=get_pattern_url("hatch_45"),
    )

    # Door frame
    builder.rect(
        x=center_x - 50 * scale,
        y=door_y,
        width=100 * scale,
        height=door_h,
        parent=parent,
        stroke="#333333",
        stroke_width=1.5,
        fill="#d4a574",
    )

    # Door panel
    builder.rect(
        x=center_x - 45 * scale,
        y=door_y + 10 * scale,
        width=90 * scale,
        height=door_h - 20 * scale,
        parent=parent,
        stroke="#8b6914",
        stroke_width=0.5,
        fill="#c4a882",
    )

    # Threshold
    builder.rect(
        x=center_x - 60 * scale,
        y=door_y + door_h,
        width=120 * scale,
        height=15 * scale,
        parent=parent,
        stroke="#333333",
        stroke_width=1,
        fill=get_pattern_url("wood"),
    )

    # Floor
    builder.rect(
        x=center_x - 80 * scale,
        y=door_y + door_h + 15 * scale,
        width=160 * scale,
        height=20 * scale,
        parent=parent,
        stroke="#333333",
        stroke_width=0.5,
        fill=get_pattern_url("concrete"),
    )

    # Title
    builder.text(
        content="DOOR DETAIL",
        x=center_x,
        y=detail_height - 20 * scale,
        parent=parent,
        font_size=10 * scale,
        font_weight="bold",
        text_anchor="middle",
        fill="#333333",
    )


def _render_generic_detail(
    builder: SVGBuilder,
    parent: Element,
    detail: Detail,
    scale: float,
) -> None:
    """Render a generic detail placeholder."""
    builder.text(
        content=f"[{detail.name}]",
        x=100 * scale,
        y=100 * scale,
        parent=parent,
        font_size=12 * scale,
        font_weight="bold",
        fill="#666666",
        font_style="italic",
    )
    builder.text(
        content=f"Scale: {detail.scale}",
        x=100 * scale,
        y=120 * scale,
        parent=parent,
        font_size=8 * scale,
        fill="#999999",
    )


def _get_wall_layers(wall_types: List[dict]) -> List[Layer]:
    """Extract wall layers from wall types data."""
    # Find first exterior wall type
    for wt in wall_types:
        if wt.get('category') == 'exterior' and wt.get('layers'):
            return [
                Layer(l['name'], l.get('thickness', 20), l.get('material', 'wood'))
                for l in wt['layers']
            ]

    # Default layers if none found
    return [
        Layer("Siding", 20, "siding"),
        Layer("Sheathing", 11, "plywood"),
        Layer("Stud w/ Insulation", 140, "insulation"),
        Layer("Drywall", 16, "gypsum"),
    ]


def _render_dimension_vertical(
    builder: SVGBuilder,
    parent: Element,
    x: float,
    y1: float,
    y2: float,
    label: str,
    scale: float,
) -> None:
    """Render a vertical dimension with label."""
    # Dimension line
    builder.line(
        x, y1, x, y2,
        parent=parent,
        stroke="#333333",
        stroke_width=0.5,
    )

    # Tick marks
    tick_len = 5 * scale
    builder.line(
        x - tick_len, y1, x + tick_len, y1,
        parent=parent,
        stroke="#333333",
        stroke_width=0.5,
    )
    builder.line(
        x - tick_len, y2, x + tick_len, y2,
        parent=parent,
        stroke="#333333",
        stroke_width=0.5,
    )

    # Label
    builder.text(
        content=label,
        x=x + 10 * scale,
        y=(y1 + y2) / 2,
        parent=parent,
        font_size=6 * scale,
        fill="#333333",
        dominant_baseline="middle",
    )


def _render_error(
    builder: SVGBuilder,
    parent: Element,
    message: str,
    offset_x: float,
    offset_y: float,
) -> None:
    """Render an error message placeholder."""
    g = builder.group(parent=parent, class_="detail-error")

    builder.text(
        content=f"[{message}]",
        x=offset_x + 50,
        y=offset_y + 50,
        parent=g,
        font_size=12,
        fill="#cc0000",
        font_style="italic",
    )


def get_detail_bounds(detail_id: str) -> tuple:
    """
    Get estimated bounds for a detail.

    Returns:
        (min_x, min_y, max_x, max_y) in model units
    """
    # Standard detail size
    return (0, 0, 400, 600)
