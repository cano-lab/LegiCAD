"""ASCII visualizer for LegiQBD.

Renders floor plan layouts as ASCII art for terminal display.
Supports multiple detail levels and styling options.
"""

from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
import math


@dataclass
class RoomRect:
    """A room rectangle for visualization."""
    id: str
    name: str
    room_type: str
    x: float
    y: float
    width: float
    depth: float


class ASCIIVisualizer:
    """Render layouts as ASCII art."""

    def __init__(
        self,
        width: int = 60,
        height: int = 30,
        use_unicode: bool = True
    ):
        self.width = width
        self.height = height
        self.use_unicode = use_unicode

        # Box drawing characters
        if use_unicode:
            self.H_LINE = "─"
            self.V_LINE = "│"
            self.TL_CORNER = "┌"
            self.TR_CORNER = "┐"
            self.BL_CORNER = "└"
            self.BR_CORNER = "┘"
            self.T_JOIN = "┬"
            self.B_JOIN = "┴"
            self.L_JOIN = "├"
            self.R_JOIN = "┤"
            self.CROSS = "┼"
            self.DOOR = "░"
        else:
            self.H_LINE = "-"
            self.V_LINE = "|"
            self.TL_CORNER = "+"
            self.TR_CORNER = "+"
            self.BL_CORNER = "+"
            self.BR_CORNER = "+"
            self.T_JOIN = "+"
            self.B_JOIN = "+"
            self.L_JOIN = "+"
            self.R_JOIN = "+"
            self.CROSS = "+"
            self.DOOR = "="

        # Room type abbreviations
        self.ABBREVS = {
            "living": "LIV",
            "kitchen": "KIT",
            "dining": "DIN",
            "bedroom": "BED",
            "primary_bedroom": "MBA",
            "bathroom": "BTH",
            "ensuite": "ENS",
            "powder_room": "PWD",
            "office": "OFC",
            "laundry": "LAU",
            "mudroom": "MUD",
            "garage_1car": "GAR",
            "garage_2car": "GAR",
            "entry": "ENT",
            "hallway": "HAL",
            "closet": "CLO",
            "walk_in_closet": "WIC",
            "pantry": "PAN",
        }

    def render(self, layout: Dict[str, Any]) -> str:
        """Render a solved layout as ASCII.

        Args:
            layout: Solved layout with rooms and positions

        Returns:
            ASCII string representation
        """
        rooms = layout.get("rooms", [])
        if not rooms:
            return self._render_empty()

        # Convert to room rects
        rects = self._layout_to_rects(rooms)

        # Calculate bounds
        bounds = self._calculate_bounds(rects)

        # Create grid
        grid = self._create_grid()

        # Draw rooms
        for rect in rects:
            self._draw_room(grid, rect, bounds)

        # Convert to string
        return self._grid_to_string(grid, bounds)

    def render_simple(self, rooms: List[Dict[str, Any]]) -> str:
        """Render a simple room list without positions.

        Uses automatic layout for rooms that don't have positions.
        """
        # Create simple grid layout
        rects = self._auto_layout(rooms)

        if not rects:
            return self._render_empty()

        bounds = self._calculate_bounds(rects)
        grid = self._create_grid()

        for rect in rects:
            self._draw_room(grid, rect, bounds)

        return self._grid_to_string(grid, bounds)

    # =========================================================================
    # Layout Processing
    # =========================================================================

    def _layout_to_rects(self, rooms: List[Dict]) -> List[RoomRect]:
        """Convert layout rooms to rectangles."""
        rects = []
        for room in rooms:
            pos = room.get("position", {})
            size = room.get("size", {})

            rects.append(RoomRect(
                id=room.get("id", ""),
                name=room.get("name", "Room"),
                room_type=room.get("type", "room"),
                x=pos.get("x", 0),
                y=pos.get("y", 0),
                width=size.get("width", 3),
                depth=size.get("depth", 3)
            ))

        return rects

    def _auto_layout(self, rooms: List[Dict]) -> List[RoomRect]:
        """Create automatic layout for rooms without positions."""
        rects = []
        x, y = 0, 0
        row_height = 0
        max_width = 20  # meters

        for room in rooms:
            width = 4  # default width
            depth = 4  # default depth

            # Try to get area from room
            area = room.get("area", 12)
            side = math.sqrt(area)
            width = depth = max(3, min(6, side))

            # Wrap to next row if needed
            if x + width > max_width:
                x = 0
                y += row_height + 0.5
                row_height = 0

            rects.append(RoomRect(
                id=room.get("id", ""),
                name=room.get("name", "Room"),
                room_type=room.get("type", "room"),
                x=x,
                y=y,
                width=width,
                depth=depth
            ))

            x += width + 0.5
            row_height = max(row_height, depth)

        return rects

    def _calculate_bounds(self, rects: List[RoomRect]) -> Tuple[float, float, float, float]:
        """Calculate bounding box of all rooms."""
        if not rects:
            return (0, 0, 10, 10)

        min_x = min(r.x for r in rects)
        min_y = min(r.y for r in rects)
        max_x = max(r.x + r.width for r in rects)
        max_y = max(r.y + r.depth for r in rects)

        return (min_x, min_y, max_x, max_y)

    # =========================================================================
    # Grid Operations
    # =========================================================================

    def _create_grid(self) -> List[List[str]]:
        """Create empty character grid."""
        return [[" " for _ in range(self.width)] for _ in range(self.height)]

    def _draw_room(
        self,
        grid: List[List[str]],
        rect: RoomRect,
        bounds: Tuple[float, float, float, float]
    ):
        """Draw a room on the grid."""
        min_x, min_y, max_x, max_y = bounds

        # Scale factors
        scale_x = (self.width - 4) / max(1, max_x - min_x)
        scale_y = (self.height - 4) / max(1, max_y - min_y)

        # Room coordinates on grid
        x1 = int((rect.x - min_x) * scale_x) + 2
        y1 = int((rect.y - min_y) * scale_y) + 2
        x2 = int((rect.x + rect.width - min_x) * scale_x) + 2
        y2 = int((rect.y + rect.depth - min_y) * scale_y) + 2

        # Clamp to grid
        x1 = max(0, min(x1, self.width - 1))
        y1 = max(0, min(y1, self.height - 1))
        x2 = max(0, min(x2, self.width - 1))
        y2 = max(0, min(y2, self.height - 1))

        # Ensure minimum size
        if x2 - x1 < 4:
            x2 = min(self.width - 1, x1 + 4)
        if y2 - y1 < 3:
            y2 = min(self.height - 1, y1 + 3)

        # Draw box
        self._draw_box(grid, x1, y1, x2, y2)

        # Draw label
        abbrev = self.ABBREVS.get(rect.room_type, rect.room_type[:3].upper())
        label = abbrev

        # Center label in room
        label_x = x1 + (x2 - x1 - len(label)) // 2
        label_y = y1 + (y2 - y1) // 2

        if 0 <= label_y < self.height and label_x >= 0:
            for i, char in enumerate(label):
                if label_x + i < self.width:
                    grid[label_y][label_x + i] = char

    def _draw_box(
        self,
        grid: List[List[str]],
        x1: int, y1: int,
        x2: int, y2: int
    ):
        """Draw a box on the grid."""
        # Corners
        if 0 <= y1 < self.height and 0 <= x1 < self.width:
            grid[y1][x1] = self.TL_CORNER
        if 0 <= y1 < self.height and 0 <= x2 < self.width:
            grid[y1][x2] = self.TR_CORNER
        if 0 <= y2 < self.height and 0 <= x1 < self.width:
            grid[y2][x1] = self.BL_CORNER
        if 0 <= y2 < self.height and 0 <= x2 < self.width:
            grid[y2][x2] = self.BR_CORNER

        # Top and bottom edges
        for x in range(x1 + 1, x2):
            if 0 <= x < self.width:
                if 0 <= y1 < self.height:
                    grid[y1][x] = self.H_LINE
                if 0 <= y2 < self.height:
                    grid[y2][x] = self.H_LINE

        # Left and right edges
        for y in range(y1 + 1, y2):
            if 0 <= y < self.height:
                if 0 <= x1 < self.width:
                    grid[y][x1] = self.V_LINE
                if 0 <= x2 < self.width:
                    grid[y][x2] = self.V_LINE

    def _grid_to_string(
        self,
        grid: List[List[str]],
        bounds: Tuple[float, float, float, float]
    ) -> str:
        """Convert grid to string with scale."""
        lines = []

        # Header
        min_x, min_y, max_x, max_y = bounds
        width = max_x - min_x
        height = max_y - min_y
        lines.append(f"Floor Plan ({width:.1f}m x {height:.1f}m)")
        lines.append("")

        # Grid
        for row in grid:
            lines.append("".join(row))

        # Legend
        lines.append("")
        lines.append("Legend: " + " | ".join(
            f"{v}={k}" for k, v in list(self.ABBREVS.items())[:6]
        ))

        return "\n".join(lines)

    def _render_empty(self) -> str:
        """Render empty layout message."""
        lines = []
        lines.append("Floor Plan")
        lines.append("")
        lines.append("  " + self.TL_CORNER + self.H_LINE * 20 + self.TR_CORNER)
        for _ in range(5):
            lines.append("  " + self.V_LINE + " " * 20 + self.V_LINE)
        lines.append("  " + self.V_LINE + "   No rooms yet    " + self.V_LINE)
        for _ in range(5):
            lines.append("  " + self.V_LINE + " " * 20 + self.V_LINE)
        lines.append("  " + self.BL_CORNER + self.H_LINE * 20 + self.BR_CORNER)

        return "\n".join(lines)


# =============================================================================
# Convenience Functions
# =============================================================================

def render_layout(layout: Dict[str, Any], width: int = 60) -> str:
    """Convenience function to render a layout."""
    viz = ASCIIVisualizer(width=width)
    return viz.render(layout)


def render_rooms(rooms: List[Dict[str, Any]], width: int = 60) -> str:
    """Convenience function to render a room list."""
    viz = ASCIIVisualizer(width=width)
    return viz.render_simple(rooms)


# =============================================================================
# Simple Box Layout (for quick previews)
# =============================================================================

def quick_preview(rooms: List[Dict[str, Any]]) -> str:
    """Generate a quick text preview of rooms."""
    if not rooms:
        return "No rooms defined."

    lines = []
    lines.append("Room Summary:")
    lines.append("-" * 40)

    # Group by type
    by_type = {}
    for room in rooms:
        rtype = room.get("type", "other")
        by_type.setdefault(rtype, []).append(room)

    for rtype, room_list in sorted(by_type.items()):
        names = [r.get("name", "?") for r in room_list]
        lines.append(f"  [{rtype.upper():^12}] {', '.join(names)}")

    lines.append("-" * 40)
    lines.append(f"Total: {len(rooms)} rooms")

    return "\n".join(lines)
