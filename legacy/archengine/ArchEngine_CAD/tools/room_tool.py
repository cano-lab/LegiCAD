"""
Room Tool - for defining room boundaries
"""
import math
from typing import Optional, List

from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtGui import QMouseEvent, QKeyEvent, QPen, QColor, QBrush, QPolygonF
from PyQt6.QtWidgets import QGraphicsPolygonItem, QGraphicsEllipseItem, QGraphicsLineItem

from tools.base_tool import BaseTool, ToolType
from core.events import event_bus


class RoomTool(BaseTool):
    """
    Tool for defining room boundaries.
    Click to add points, double-click or Enter to close polygon.
    """

    def __init__(self, view, document, config=None):
        super().__init__(view, document)
        self._cursor = Qt.CursorShape.CrossCursor
        self.config = config

        # Polygon points
        self._points: List[QPointF] = []

        # Preview graphics
        self._preview_polygon: Optional[QGraphicsPolygonItem] = None
        self._preview_line: Optional[QGraphicsLineItem] = None
        self._point_markers: List[QGraphicsEllipseItem] = []

        # Room type (could be set via properties panel)
        self._room_type = "generic"

    @property
    def tool_type(self) -> ToolType:
        return ToolType.ROOM

    def activate(self):
        super().activate()
        self._cleanup_all()
        event_bus.status_message.emit(
            "Room Tool: Click to add points, double-click or Enter to close",
            0
        )

    def deactivate(self):
        super().deactivate()
        self._cleanup_all()

    def mouse_press(self, event: QMouseEvent, scene_pos: QPointF):
        """Handle mouse press - add point to polygon."""
        if event.button() != Qt.MouseButton.LeftButton:
            return

        # Apply snapping
        pos = self._apply_snapping(scene_pos)

        # Add point
        self._points.append(pos)
        self._add_point_marker(pos)
        self._update_preview(pos)

        point_count = len(self._points)
        if point_count == 1:
            event_bus.status_message.emit(
                "Click to add more points, double-click or Enter to close polygon",
                0
            )
        else:
            area = self._calculate_area()
            event_bus.status_message.emit(
                f"{point_count} points, Area: {area/1e6:.2f} m². Double-click or Enter to finish",
                0
            )

    def mouse_move(self, event: QMouseEvent, scene_pos: QPointF):
        """Update preview as mouse moves."""
        if not self._points:
            return

        pos = self._apply_snapping(scene_pos)

        # Apply ortho constraint if enabled
        if self.config and self.config.ortho_mode and len(self._points) > 0:
            pos = self.snap_to_ortho(self._points[-1], pos)

        # Update preview line to current mouse position
        self._update_preview_line(pos)

    def mouse_release(self, event: QMouseEvent, scene_pos: QPointF):
        """Handle mouse release."""
        pass

    def mouse_double_click(self, event: QMouseEvent, scene_pos: QPointF):
        """Handle double-click - close polygon."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._complete_room()

    def key_press(self, event: QKeyEvent):
        """Handle key events."""
        if event.key() == Qt.Key.Key_Escape:
            self.cancel()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._complete_room()
        elif event.key() == Qt.Key.Key_Backspace:
            # Remove last point
            if self._points:
                self._points.pop()
                if self._point_markers:
                    marker = self._point_markers.pop()
                    self.view.scene.removeItem(marker)
                self._update_preview(self._points[-1] if self._points else None)
                event_bus.status_message.emit(
                    f"Removed point. {len(self._points)} points remaining",
                    2000
                )

    def cancel(self):
        """Cancel room drawing."""
        self._cleanup_all()
        event_bus.status_message.emit(
            "Room Tool: Click to add points, double-click or Enter to close",
            0
        )

    def _apply_snapping(self, pos: QPointF) -> QPointF:
        """Apply grid snapping if enabled."""
        if self.config and self.config.snap_enabled:
            return self.snap_to_grid(pos, self.config.grid_size)
        return pos

    def _add_point_marker(self, pos: QPointF):
        """Add visual marker for a polygon point."""
        marker = QGraphicsEllipseItem(-50, -50, 100, 100)
        marker.setPos(pos)
        marker.setPen(QPen(QColor(100, 200, 255), 20))
        marker.setBrush(QBrush(QColor(100, 200, 255, 100)))
        marker.setZValue(1001)
        self.view.scene.addItem(marker)
        self._point_markers.append(marker)

    def _update_preview(self, current_pos: Optional[QPointF]):
        """Update the preview polygon."""
        if not self._points:
            self._cleanup_preview()
            return

        # Create or update polygon preview
        if self._preview_polygon is None:
            self._preview_polygon = QGraphicsPolygonItem()
            pen = QPen(QColor(100, 200, 255), 20, Qt.PenStyle.DashLine)
            self._preview_polygon.setPen(pen)
            brush = QBrush(QColor(100, 200, 255, 30))
            self._preview_polygon.setBrush(brush)
            self._preview_polygon.setZValue(999)
            self.view.scene.addItem(self._preview_polygon)

        # Build polygon from points
        polygon = QPolygonF()
        for pt in self._points:
            polygon.append(pt)

        self._preview_polygon.setPolygon(polygon)

    def _update_preview_line(self, mouse_pos: QPointF):
        """Update the line from last point to mouse position."""
        if not self._points:
            return

        last_point = self._points[-1]

        # Create preview line if needed
        if self._preview_line is None:
            self._preview_line = QGraphicsLineItem()
            pen = QPen(QColor(100, 200, 255), 20, Qt.PenStyle.DashLine)
            self._preview_line.setPen(pen)
            self._preview_line.setZValue(1000)
            self.view.scene.addItem(self._preview_line)

        from PyQt6.QtCore import QLineF
        self._preview_line.setLine(QLineF(last_point, mouse_pos))

    def _cleanup_preview(self):
        """Remove preview graphics."""
        if self._preview_polygon:
            self.view.scene.removeItem(self._preview_polygon)
            self._preview_polygon = None

        if self._preview_line:
            self.view.scene.removeItem(self._preview_line)
            self._preview_line = None

    def _cleanup_all(self):
        """Remove all preview graphics and reset state."""
        self._cleanup_preview()

        for marker in self._point_markers:
            self.view.scene.removeItem(marker)
        self._point_markers.clear()

        self._points.clear()

    def _calculate_area(self) -> float:
        """Calculate polygon area using shoelace formula."""
        if len(self._points) < 3:
            return 0

        n = len(self._points)
        area = 0

        for i in range(n):
            j = (i + 1) % n
            area += self._points[i].x() * self._points[j].y()
            area -= self._points[j].x() * self._points[i].y()

        return abs(area) / 2

    def _complete_room(self):
        """Complete room creation and add to document."""
        if len(self._points) < 3:
            event_bus.status_message.emit(
                "Need at least 3 points to create a room",
                3000
            )
            return

        # Calculate area
        area = self._calculate_area()

        # Convert points to list format [x, z]
        vertices = [[pt.x(), pt.y()] for pt in self._points]

        # Create room data
        room_data = {
            'name': f'Room {len(self.document.rooms) + 1}',
            'room_type': self._room_type,
            'vertices': vertices,
            'area': area
        }

        # Add room via undoable command
        room_id = self.document.add_room_undoable(room_data)

        event_bus.status_message.emit(
            f"Room created: {area/1e6:.2f} m². Click to start new room.",
            3000
        )

        # Clean up and prepare for next room
        self._cleanup_all()
