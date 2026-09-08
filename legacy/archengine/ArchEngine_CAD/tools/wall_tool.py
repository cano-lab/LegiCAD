"""
Wall Tool - for drawing walls
"""
from typing import Optional

from PyQt6.QtCore import Qt, QPointF, QLineF
from PyQt6.QtGui import QMouseEvent, QKeyEvent, QPen, QColor
from PyQt6.QtWidgets import QGraphicsLineItem

from tools.base_tool import BaseTool, ToolType
from core.events import event_bus


class WallTool(BaseTool):
    """
    Tool for drawing walls.
    Click to start, click again to end. ESC to cancel.
    """

    def __init__(self, view, document, config=None):
        super().__init__(view, document)
        self._cursor = Qt.CursorShape.CrossCursor
        self.config = config

        # Drawing state
        self._start_point: Optional[QPointF] = None
        self._preview_line: Optional[QGraphicsLineItem] = None
        self._wall_thickness = 150  # mm

    @property
    def tool_type(self) -> ToolType:
        return ToolType.WALL

    def activate(self):
        super().activate()
        self._start_point = None
        self._cleanup_preview()
        event_bus.status_message.emit("Wall Tool: Click to start wall, click again to end", 0)

    def deactivate(self):
        super().deactivate()
        self._cleanup_preview()
        self._start_point = None

    def mouse_press(self, event: QMouseEvent, scene_pos: QPointF):
        """Handle mouse press - start or end wall."""
        if event.button() != Qt.MouseButton.LeftButton:
            return

        # Apply snapping
        pos = self._apply_snapping(scene_pos)

        if self._start_point is None:
            # Start new wall
            self._start_point = pos
            self._create_preview(pos)
            event_bus.status_message.emit("Click to place wall end point, ESC to cancel", 0)
        else:
            # Complete wall
            self._complete_wall(pos)

    def mouse_move(self, event: QMouseEvent, scene_pos: QPointF):
        """Update preview line."""
        if self._start_point and self._preview_line:
            pos = self._apply_snapping(scene_pos)

            # Apply ortho constraint if enabled
            if self.config and self.config.ortho_mode:
                pos = self.snap_to_ortho(self._start_point, pos)

            self._preview_line.setLine(QLineF(self._start_point, pos))

    def mouse_release(self, event: QMouseEvent, scene_pos: QPointF):
        """Handle mouse release."""
        pass  # Wall is placed on click, not release

    def key_press(self, event: QKeyEvent):
        """Handle key events."""
        if event.key() == Qt.Key.Key_Escape:
            self.cancel()
        elif event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
            # Finish current wall and stay in wall mode
            if self._start_point:
                self.cancel()

    def cancel(self):
        """Cancel current wall drawing."""
        self._cleanup_preview()
        self._start_point = None
        event_bus.status_message.emit("Wall Tool: Click to start wall", 0)

    def _apply_snapping(self, pos: QPointF) -> QPointF:
        """Apply grid snapping if enabled."""
        if self.config and self.config.snap_enabled:
            return self.snap_to_grid(pos, self.config.grid_size)
        return pos

    def _create_preview(self, start: QPointF):
        """Create preview line."""
        self._preview_line = QGraphicsLineItem()
        pen = QPen(QColor(255, 255, 0), 3, Qt.PenStyle.DashLine)
        self._preview_line.setPen(pen)
        self._preview_line.setLine(QLineF(start, start))
        self._preview_line.setZValue(1000)
        self.view.scene.addItem(self._preview_line)

    def _cleanup_preview(self):
        """Remove preview line."""
        if self._preview_line:
            self.view.scene.removeItem(self._preview_line)
            self._preview_line = None

    def _complete_wall(self, end_pos: QPointF):
        """Complete wall creation and add to document."""
        if not self._start_point:
            return

        # Apply ortho if enabled
        if self.config and self.config.ortho_mode:
            end_pos = self.snap_to_ortho(self._start_point, end_pos)

        # Check minimum length
        dx = end_pos.x() - self._start_point.x()
        dz = end_pos.y() - self._start_point.y()
        length = (dx**2 + dz**2) ** 0.5

        if length < 100:  # Minimum 100mm
            event_bus.status_message.emit("Wall too short (minimum 100mm)", 3000)
            return

        # Add wall to document
        wall_data = {
            'start': [self._start_point.x(), 0, self._start_point.y()],
            'end': [end_pos.x(), 0, end_pos.y()],
            'height': 2700,
            'category': 'interior',
            'wall_type': ''
        }

        # Add to document's raw data
        if 'walls_batch' not in self.document._data:
            self.document._data['walls_batch'] = []

        self.document._data['walls_batch'].append(wall_data)

        # Re-parse and refresh
        self.document._parse_data()
        self.document.set_modified(True)
        self.document.document_changed.emit()

        # Clean up and prepare for next wall
        self._cleanup_preview()

        # Start new wall from end point (continuous drawing)
        self._start_point = end_pos
        self._create_preview(end_pos)

        event_bus.status_message.emit(
            f"Wall added ({length:.0f}mm). Click for next point, ESC to finish",
            0
        )
