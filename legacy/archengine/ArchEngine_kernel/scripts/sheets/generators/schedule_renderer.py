"""
SVGBuilder-based schedule renderer for viewport integration.

Renders door, window, and room finish schedules as tables
using the existing generator logic for data extraction.
"""

from typing import Dict, Any, List, Tuple
from xml.etree.ElementTree import Element

from ..svg_builder import SVGBuilder
from .generator_adapters import (
    get_schedule_data,
    DoorEntry,
    WindowEntry,
    RoomFinishEntry,
)


# Schedule column definitions
DOOR_SCHEDULE_COLS: List[Tuple[str, int]] = [
    ("MARK", 40),
    ("LOCATION", 120),
    ("WIDTH", 50),
    ("HEIGHT", 50),
    ("TYPE", 80),
    ("FRAME", 80),
    ("HARDWARE", 80),
]

WINDOW_SCHEDULE_COLS: List[Tuple[str, int]] = [
    ("MARK", 40),
    ("LOCATION", 120),
    ("WIDTH", 50),
    ("HEIGHT", 50),
    ("SILL", 50),
    ("TYPE", 80),
    ("GLAZING", 80),
]

ROOM_SCHEDULE_COLS: List[Tuple[str, int]] = [
    ("NO.", 40),
    ("NAME", 120),
    ("FLOOR", 80),
    ("BASE", 60),
    ("WALLS", 80),
    ("CEILING", 80),
    ("HT.", 50),
]


def render_schedule(
    builder: SVGBuilder,
    parent: Element,
    data: Dict[str, Any],
    schedule_type: str,
    scale: float,
    offset_x: float,
    offset_y: float,
) -> None:
    """
    Render a schedule table into a viewport using SVGBuilder.

    Args:
        builder: SVGBuilder instance
        parent: Parent element (viewport content group)
        data: Building JSON data
        schedule_type: "door", "window", or "room"
        scale: Viewport scale factor (ignored - schedules use fixed scale)
        offset_x, offset_y: Transform offsets for positioning
    """
    # Schedules use fixed drawing scale, not model scale
    # Use 1.0 for direct point-based rendering
    drawing_scale = 1.0

    # Get schedule data
    try:
        entries = get_schedule_data(data, schedule_type)
    except Exception as e:
        _render_error(builder, parent, f"Schedule error: {e}", offset_x, offset_y)
        return

    # Create main group - position at viewport origin with small margin
    g = builder.group(
        parent=parent,
        id=f"schedule-{schedule_type}",
        class_="schedule-content",
        transform=f"translate({offset_x + 10}, {offset_y + 10})",
    )

    # Get column definitions and title
    if schedule_type == "door":
        columns = DOOR_SCHEDULE_COLS
        title = "DOOR SCHEDULE"
        rows = _format_door_rows(entries)
    elif schedule_type == "window":
        columns = WINDOW_SCHEDULE_COLS
        title = "WINDOW SCHEDULE"
        rows = _format_window_rows(entries)
    else:  # room
        columns = ROOM_SCHEDULE_COLS
        title = "ROOM FINISH SCHEDULE"
        rows = _format_room_rows(entries)

    # Render table with fixed scale
    _render_table(builder, g, title, columns, rows, drawing_scale)


def _format_door_rows(entries: List[DoorEntry]) -> List[List[str]]:
    """Format door entries for table display."""
    rows = []
    for entry in entries:
        rows.append([
            entry.mark,
            entry.room,
            f"{entry.width}",
            f"{entry.height}",
            entry.door_type,
            entry.frame,
            entry.hardware,
        ])
    return rows


def _format_window_rows(entries: List[WindowEntry]) -> List[List[str]]:
    """Format window entries for table display."""
    rows = []
    for entry in entries:
        rows.append([
            entry.mark,
            entry.room,
            f"{entry.width}",
            f"{entry.height}",
            f"{entry.sill_height}",
            entry.window_type,
            entry.glazing,
        ])
    return rows


def _format_room_rows(entries: List[RoomFinishEntry]) -> List[List[str]]:
    """Format room finish entries for table display."""
    rows = []
    for entry in entries:
        rows.append([
            entry.number,
            entry.name,
            entry.floor,
            entry.base,
            entry.walls,
            entry.ceiling,
            entry.ceiling_height,
        ])
    return rows


def _render_table(
    builder: SVGBuilder,
    parent: Element,
    title: str,
    columns: List[Tuple[str, int]],
    rows: List[List[str]],
    scale: float,
) -> None:
    """
    Render a complete schedule table.

    Args:
        builder: SVGBuilder instance
        parent: Parent group element
        title: Table title
        columns: List of (header, width) tuples
        rows: List of row data (list of strings)
        scale: Scale factor
    """
    row_height = 18 * scale
    title_height = 24 * scale
    header_height = 20 * scale

    # Calculate total width
    total_width = sum(w * scale for _, w in columns)

    # Title bar
    builder.rect(
        x=0,
        y=0,
        width=total_width,
        height=title_height,
        parent=parent,
        fill="#4a4a4a",
        stroke="#333333",
        stroke_width=1,
    )
    builder.text(
        content=title,
        x=total_width / 2,
        y=title_height / 2,
        parent=parent,
        font_size=10 * scale,
        font_weight="bold",
        fill="white",
        text_anchor="middle",
        dominant_baseline="middle",
    )

    # Header row
    y = title_height
    x = 0
    for header, width in columns:
        w = width * scale
        builder.rect(
            x=x,
            y=y,
            width=w,
            height=header_height,
            parent=parent,
            fill="#e0e0e0",
            stroke="#333333",
            stroke_width=0.5,
        )
        builder.text(
            content=header,
            x=x + w / 2,
            y=y + header_height / 2,
            parent=parent,
            font_size=7 * scale,
            font_weight="bold",
            fill="#333333",
            text_anchor="middle",
            dominant_baseline="middle",
        )
        x += w

    # Data rows
    y += header_height
    for row_idx, row in enumerate(rows):
        x = 0
        # Alternating row background
        fill = "#ffffff" if row_idx % 2 == 0 else "#f5f5f5"

        for (_, width), cell in zip(columns, row):
            w = width * scale
            builder.rect(
                x=x,
                y=y,
                width=w,
                height=row_height,
                parent=parent,
                fill=fill,
                stroke="#cccccc",
                stroke_width=0.5,
            )
            # Truncate long text
            display_text = cell[:15] if len(cell) > 15 else cell
            builder.text(
                content=display_text,
                x=x + 4 * scale,
                y=y + row_height / 2,
                parent=parent,
                font_size=6 * scale,
                fill="#333333",
                text_anchor="start",
                dominant_baseline="middle",
            )
            x += w
        y += row_height

    # Bottom border
    builder.line(
        0, y, total_width, y,
        parent=parent,
        stroke="#333333",
        stroke_width=1,
    )


def _render_error(
    builder: SVGBuilder,
    parent: Element,
    message: str,
    offset_x: float,
    offset_y: float,
) -> None:
    """Render an error message placeholder."""
    g = builder.group(parent=parent, class_="schedule-error")

    builder.text(
        content=f"[{message}]",
        x=offset_x + 50,
        y=offset_y + 50,
        parent=g,
        font_size=12,
        fill="#cc0000",
        font_style="italic",
    )


def get_schedule_bounds(schedule_type: str, entry_count: int = 10) -> tuple:
    """
    Get estimated bounds for a schedule table.

    Args:
        schedule_type: "door", "window", or "room"
        entry_count: Expected number of entries

    Returns:
        (min_x, min_y, max_x, max_y) in viewport units
    """
    # Get column definitions
    if schedule_type == "door":
        columns = DOOR_SCHEDULE_COLS
    elif schedule_type == "window":
        columns = WINDOW_SCHEDULE_COLS
    else:
        columns = ROOM_SCHEDULE_COLS

    total_width = sum(w for _, w in columns)
    row_height = 18
    header_height = 24 + 20  # title + header
    total_height = header_height + (entry_count * row_height)

    return (0, 0, total_width, total_height)
