"""
Door Tool - for placing doors on walls
"""
import math
from typing import Optional, Tuple

from PyQt6.QtCore import Qt, QPointF, QRectF
from PyQt6.QtGui import QMouseEvent, QKeyEvent, QPen, QColor, QBrush
from PyQt6.QtWidgets import QGraphicsRectItem, QGraphicsLineItem

from tools.base_tool import BaseTool, ToolType
from core.events import event_bus


class DoorTool(BaseTool):
    """
    Tool for placing doors on walls.
    Click on a wall to place a door at that location.
    """

    def __init__(self, view, document, config=None):
        super().__init__(view, document)
        self._cursor = Qt.CursorShape.CrossCursor
        self.config = config

        # Door parameters
        self._door_width = 914  # mm (36 inches)
        self._door_height = 2134  # mm (84 inches)

        # Preview graphics
        self._preview_rect: Optional[QGraphicsRectItem] = None
        self._preview_swing: Optional[QGraphicsLineItem] = None

        # Hover state
        self._hover_wall_index: int = -1
        self._hover_offset: float = 0

    @property
    def tool_type(self) -> ToolType:
        return ToolType.DOOR

    def activate(self):
        super().activate()
        self._cleanup_preview()
        event_bus.status_message.emit("Door Tool: Click on a wall to place a door", 0)

    def deactivate(self):
        super().deactivate()
        self._cleanup_preview()

    def mouse_press(self, event: QMouseEvent, scene_pos: QPointF):
        """Handle mouse press - place door on wall."""
        if event.button() != Qt.MouseButton.LeftButton:
            return

        # Find wall under cursor
        wall_index, offset = self._find_wall_at_point(scene_pos)

        if wall_index < 0:
            event_bus.status_message.emit("Click on a wall to place a door", 3000)
            return

        wall = self.document.walls[wall_index]

        # Check if door fits on wall
        wall_length = self._get_wall_length(wall)
        if offset < self._door_width / 2:
            offset = self._door_width / 2
        elif offset > wall_length - self._door_width / 2:
            offset = wall_length - self._door_width / 2

        if wall_length < self._door_width:
            event_bus.status_message.emit("Wall too short for door", 3000)
            return

        # Create door data
        door_data = {
            'wall_index': wall_index,
            'offset': offset,
            'width': self._door_width,
            'height': self._door_height,
            'type': 'swing',
            'swing': 'left_in'
        }

        # Add door via undoable command
        self.document.add_door_undoable(door_data)

        event_bus.status_message.emit(
            f"Door placed on wall {wall_index}. Click to place another.",
            3000
        )

    def mouse_move(self, event: QMouseEvent, scene_pos: QPointF):
        """Update preview as mouse moves."""
        # Find wall under cursor
        wall_index, offset = self._find_wall_at_point(scene_pos)

        if wall_index >= 0:
            self._hover_wall_index = wall_index
            self._hover_offset = offset
            self._update_preview(wall_index, offset)
        else:
            self._cleanup_preview()
            self._hover_wall_index = -1

    def mouse_release(self, event: QMouseEvent, scene_pos: QPointF):
        """Handle mouse release."""
        pass

    def key_press(self, event: QKeyEvent):
        """Handle key events."""
        if event.key() == Qt.Key.Key_Escape:
            self.cancel()

    def cancel(self):
        """Cancel door placement."""
        self._cleanup_preview()
        event_bus.status_message.emit("Door Tool: Click on a wall to place a door", 0)

    def _find_wall_at_point(self, pos: QPointF) -> Tuple[int, float]:
        """
        Find wall nearest to point and calculate offset along it.

        Returns:
            (wall_index, offset) or (-1, 0) if no wall found
        """
        tolerance = 200  # mm - how close to wall to detect

        best_wall = -1
        best_offset = 0
        best_distance = tolerance

        for i, wall in enumerate(self.document.walls):
            # Wall endpoints in 2D (plan view uses X and Z)
            x1, z1 = wall.start[0], wall.start[2]
            x2, z2 = wall.end[0], wall.end[2]

            # Point to check
            px, pz = pos.x(), pos.y()

            # Calculate distance from point to line segment
            dist, offset = self._point_to_segment_distance(px, pz, x1, z1, x2, z2)

            if dist < best_distance:
                best_distance = dist
                best_wall = i
                best_offset = offset

        return best_wall, best_offset

    def _point_to_segment_distance(self, px, pz, x1, z1, x2, z2) -> Tuple[float, float]:
        """
        Calculate distance from point to line segment and offset along segment.

        Returns:
            (distance, offset_along_segment)
        """
        # Vector from start to end
        dx = x2 - x1
        dz = z2 - z1
        length_sq = dx * dx + dz * dz

        if length_sq == 0:
            # Degenerate segment
            dist = math.sqrt((px - x1) ** 2 + (pz - z1) ** 2)
            return dist, 0

        # Parameter t for projection onto line
        t = max(0, min(1, ((px - x1) * dx + (pz - z1) * dz) / length_sq))

        # Closest point on segment
        closest_x = x1 + t * dx
        closest_z = z1 + t * dz

        # Distance
        dist = math.sqrt((px - closest_x) ** 2 + (pz - closest_z) ** 2)

        # Offset along wall
        offset = t * math.sqrt(length_sq)

        return dist, offset

    def _get_wall_length(self, wall) -> float:
        """Calculate wall length."""
        dx = wall.end[0] - wall.start[0]
        dz = wall.end[2] - wall.start[2]
        return math.sqrt(dx * dx + dz * dz)

    def _update_preview(self, wall_index: int, offset: float):
        """Update or create preview graphics."""
        wall = self.document.walls[wall_index]

        # Calculate door position on wall
        x1, z1 = wall.start[0], wall.start[2]
        x2, z2 = wall.end[0], wall.end[2]

        wall_length = self._get_wall_length(wall)
        if wall_length == 0:
            return

        # Direction along wall
        dx = (x2 - x1) / wall_length
        dz = (z2 - z1) / wall_length

        # Perpendicular direction
        perp_x = -dz
        perp_z = dx

        # Door center position
        center_x = x1 + dx * offset
        center_z = z1 + dz * offset

        # Door rectangle corners (door width along wall, 150mm thick for preview)
        half_width = self._door_width / 2
        thickness = 150

        # Create preview rect if needed
        if self._preview_rect is None:
            self._preview_rect = QGraphicsRectItem()
            pen = QPen(QColor(0, 150, 255), 2, Qt.PenStyle.DashLine)
            self._preview_rect.setPen(pen)
            brush = QBrush(QColor(0, 150, 255, 50))
            self._preview_rect.setBrush(brush)
            self._preview_rect.setZValue(1000)
            self.view.scene.addItem(self._preview_rect)

        # Position the preview rectangle
        # Calculate angle of wall
        angle = math.atan2(dz, dx) * 180 / math.pi

        self._preview_rect.setRect(-half_width, -thickness / 2, self._door_width, thickness)
        self._preview_rect.setPos(center_x, center_z)
        self._preview_rect.setRotation(angle)

    def _cleanup_preview(self):
        """Remove preview graphics."""
        if self._preview_rect:
            self.view.scene.removeItem(self._preview_rect)
            self._preview_rect = None
        if self._preview_swing:
            self.view.scene.removeItem(self._preview_swing)
            self._preview_swing = None
