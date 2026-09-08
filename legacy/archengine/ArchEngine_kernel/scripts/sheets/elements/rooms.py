"""
Room rendering for architectural floor plans.

Renders room labels, fills, and area annotations.
"""

from typing import List, Dict, Any, Tuple, Optional, Union
from xml.etree.ElementTree import Element

from ..svg_builder import SVGBuilder
from ..lod_layers import get_element_style


def calculate_room_center(bounds: Dict[str, float]) -> Tuple[float, float]:
    """
    Calculate center point of room bounds.

    Args:
        bounds: Dict with either:
            - min_x, max_x, min_z, max_z format
            - x, y, width, height format

    Returns:
        (center_x, center_z)
    """
    # Handle x, y, width, height format
    if "width" in bounds:
        x = bounds.get("x", 0)
        y = bounds.get("y", 0)
        width = bounds.get("width", 0)
        height = bounds.get("height", 0)
        return (x + width / 2, y + height / 2)

    # Handle min/max format
    min_x = bounds.get("min_x", 0)
    max_x = bounds.get("max_x", 0)
    min_z = bounds.get("min_z", 0)
    max_z = bounds.get("max_z", 0)

    return ((min_x + max_x) / 2, (min_z + max_z) / 2)


def format_area(area_sqmm: float) -> str:
    """
    Format area in square millimeters to readable string.

    Args:
        area_sqmm: Area in square millimeters

    Returns:
        Formatted string like "12.5 sqm"
    """
    area_sqm = area_sqmm / 1_000_000  # Convert mm² to m²
    return f"{area_sqm:.1f} sqm"


def render_room_label(
    builder: SVGBuilder,
    room: Dict[str, Any],
    parent: Element,
    room_id: str,
    scale: float = 1.0,
    transform_y: bool = True,
    height: float = 0,
) -> Element:
    """
    Render a single room label.

    Args:
        builder: SVG builder instance
        room: Room dictionary from JSON
        parent: Parent SVG element
        room_id: Room ID for element identification
        scale: Scale factor
        transform_y: Whether to flip Y axis
        height: SVG height for Y transformation

    Returns:
        Group element for the room label
    """
    label_style = get_element_style("room-labels")

    name = room.get("name", room_id)
    bounds = room.get("bounds", {})
    area = room.get("area", 0)

    # Calculate center
    cx, cz = calculate_room_center(bounds)
    cx_scaled = cx * scale
    cz_scaled = cz * scale

    if transform_y:
        cz_scaled = height - cz_scaled

    # Create room label group
    room_g = builder.group(
        parent=parent,
        id=room_id,
        class_="room-label",
        data={
            "room-id": room_id,
            "name": name,
            "area": str(area),
        },
    )

    # Room name
    builder.text(
        content=name,
        x=cx_scaled,
        y=cz_scaled,
        parent=room_g,
        font_size=label_style.get("font-size", 14),
        font_weight=label_style.get("font-weight", "bold"),
        fill=label_style.get("fill", "#333333"),
        text_anchor=label_style.get("text-anchor", "middle"),
        dominant_baseline="middle",
    )

    # Area (below name)
    if area > 0:
        builder.text(
            content=format_area(area),
            x=cx_scaled,
            y=cz_scaled + 16,
            parent=room_g,
            font_size=10,
            font_weight="normal",
            fill="#666666",
            text_anchor="middle",
            dominant_baseline="middle",
        )

    return room_g


def render_room_fill(
    builder: SVGBuilder,
    room: Dict[str, Any],
    parent: Element,
    room_id: str,
    scale: float = 1.0,
    transform_y: bool = True,
    height: float = 0,
) -> Optional[Element]:
    """
    Render a room fill polygon.

    Args:
        builder: SVG builder instance
        room: Room dictionary from JSON
        parent: Parent SVG element
        room_id: Room ID for element identification
        scale: Scale factor
        transform_y: Whether to flip Y axis
        height: SVG height for Y transformation

    Returns:
        Polygon element or None if no bounds
    """
    fill_style = get_element_style("room-fills")
    bounds = room.get("bounds", {})

    if not bounds:
        return None

    # Handle x, y, width, height format
    if "width" in bounds:
        x = bounds.get("x", 0) * scale
        y = bounds.get("y", 0) * scale
        w = bounds.get("width", 0) * scale
        h = bounds.get("height", 0) * scale

        if transform_y:
            y = height - y - h

        return builder.rect(
            x=x,
            y=y,
            width=w,
            height=h,
            parent=parent,
            id=f"room-fill-{room_id}",
            class_="room-fill",
            stroke="none",
            fill=fill_style.get("fill", "#f5f5f5"),
            data={"room-id": room_id},
        )

    # Handle min/max format
    min_x = bounds.get("min_x", 0) * scale
    max_x = bounds.get("max_x", 0) * scale
    min_z = bounds.get("min_z", 0) * scale
    max_z = bounds.get("max_z", 0) * scale

    if transform_y:
        min_z, max_z = height - max_z, height - min_z

    return builder.rect(
        x=min_x,
        y=min_z,
        width=max_x - min_x,
        height=max_z - min_z,
        parent=parent,
        id=f"room-fill-{room_id}",
        class_="room-fill",
        stroke="none",
        fill=fill_style.get("fill", "#f5f5f5"),
        data={"room-id": room_id},
    )


def render_rooms(
    builder: SVGBuilder,
    rooms: Union[List[Dict[str, Any]], Dict[str, Dict[str, Any]]],
    parent: Element,
    scale: float = 1.0,
    transform_y: bool = True,
    height: float = 0,
    include_fills: bool = True,
) -> Element:
    """
    Render all rooms (LOD 1).

    Args:
        builder: SVG builder instance
        rooms: Room data - either list or dict format
        parent: Parent SVG element
        scale: Scale factor
        transform_y: Whether to flip Y axis
        height: SVG height for Y transformation
        include_fills: Whether to include room fill polygons

    Returns:
        Group element containing all rooms
    """
    g = builder.group(parent=parent, class_="rooms")

    # Normalize rooms to list of (id, room_data) tuples
    if isinstance(rooms, dict):
        room_items = list(rooms.items())
    else:
        room_items = [(f"room-{i}", room) for i, room in enumerate(rooms)]

    # Render fills first (behind labels)
    if include_fills:
        fills_g = builder.group(parent=g, class_="room-fills")
        for room_id, room in room_items:
            render_room_fill(builder, room, fills_g, room_id, scale, transform_y, height)

    # Render labels
    labels_g = builder.group(parent=g, class_="room-labels")
    for room_id, room in room_items:
        render_room_label(builder, room, labels_g, room_id, scale, transform_y, height)

    return g
