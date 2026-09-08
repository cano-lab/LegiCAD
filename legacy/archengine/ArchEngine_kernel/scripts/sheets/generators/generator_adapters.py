"""
Adapters to extract geometry data from existing generators.

These wrap the existing generator functions to provide data
for SVGBuilder-based renderers in the viewport system.
"""

import sys
from pathlib import Path
from typing import Dict, Any, List, Union, Optional

# Add parent scripts directory to path for imports
_scripts_dir = Path(__file__).parent.parent.parent
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))

# Import from existing generators
from generate_elevations import (
    generate_elevation as _gen_elevation,
    Elevation,
    WallSegment,
    Opening,
    RoofEdge,
    LevelMarker,
    Point2D,
)
from generate_sections import (
    generate_section as _gen_section,
    Section,
    SectionDirection,
    WallSection,
    WallElevation,
    FloorLevel,
    RoofSection,
    RoomLabel,
)
from generate_schedules import (
    extract_door_schedule as _extract_doors,
    extract_window_schedule as _extract_windows,
    extract_room_finish_schedule as _extract_rooms,
    DoorEntry,
    WindowEntry,
    RoomFinishEntry,
)
from generate_details import (
    generate_wall_section_detail as _gen_wall_detail,
    generate_eave_detail as _gen_eave_detail,
    generate_window_detail as _gen_window_detail,
    generate_door_detail as _gen_door_detail,
    Detail,
    Layer,
)


def get_elevation_data(data: Dict[str, Any], direction: str) -> Elevation:
    """
    Extract elevation geometry data for a direction.

    Args:
        data: Building JSON data
        direction: "north", "south", "east", or "west"

    Returns:
        Elevation dataclass with walls, openings, roof edges, markers
    """
    return _gen_elevation(data, direction)


def get_section_data(
    data: Dict[str, Any],
    direction: str,
    cut_position: Optional[float] = None,
    name: str = "A"
) -> Section:
    """
    Extract section geometry data.

    Args:
        data: Building JSON data
        direction: "longitudinal" or "transverse"
        cut_position: Position of cut plane (None for center)
        name: Section identifier (e.g., "A", "B")

    Returns:
        Section dataclass with walls, openings, floors, roof
    """
    section_dir = (SectionDirection.LONGITUDINAL
                   if direction == "longitudinal"
                   else SectionDirection.TRANSVERSE)
    return _gen_section(data, section_dir, cut_position, name)


def get_schedule_data(
    data: Dict[str, Any],
    schedule_type: str
) -> List[Union[DoorEntry, WindowEntry, RoomFinishEntry]]:
    """
    Extract schedule data by type.

    Args:
        data: Building JSON data
        schedule_type: "door", "window", or "room"

    Returns:
        List of schedule entry dataclasses
    """
    if schedule_type == "door":
        return _extract_doors(data)
    elif schedule_type == "window":
        return _extract_windows(data)
    elif schedule_type == "room":
        return _extract_rooms(data)
    else:
        raise ValueError(f"Unknown schedule type: {schedule_type}. "
                        f"Expected: door, window, or room")


def get_detail_data(data: Dict[str, Any], detail_id: str) -> Detail:
    """
    Extract detail drawing data.

    Args:
        data: Building JSON data
        detail_id: Detail identifier ("1" through "4")

    Returns:
        Detail dataclass with name, scale, and content
    """
    wall_types = data.get('wall_types', [])

    detail_map = {
        "1": lambda: _gen_wall_detail(wall_types),
        "2": lambda: _gen_eave_detail(),
        "3": lambda: _gen_window_detail(),
        "4": lambda: _gen_door_detail(),
        "wall": lambda: _gen_wall_detail(wall_types),
        "eave": lambda: _gen_eave_detail(),
        "window": lambda: _gen_window_detail(),
        "door": lambda: _gen_door_detail(),
    }

    if detail_id not in detail_map:
        raise ValueError(f"Unknown detail: {detail_id}. "
                        f"Expected: 1-4 or wall/eave/window/door")

    return detail_map[detail_id]()


# Re-export data classes for type hints
__all__ = [
    # Functions
    "get_elevation_data",
    "get_section_data",
    "get_schedule_data",
    "get_detail_data",
    # Elevation types
    "Elevation",
    "WallSegment",
    "Opening",
    "RoofEdge",
    "LevelMarker",
    "Point2D",
    # Section types
    "Section",
    "SectionDirection",
    "WallSection",
    "WallElevation",
    "FloorLevel",
    "RoofSection",
    "RoomLabel",
    # Schedule types
    "DoorEntry",
    "WindowEntry",
    "RoomFinishEntry",
    # Detail types
    "Detail",
    "Layer",
]
