"""
Base tool class for CAD editing tools
"""
from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional

from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtGui import QMouseEvent, QKeyEvent
from PyQt6.QtWidgets import QGraphicsView

from core.document import ArchDocument


class ToolType(Enum):
    """Available tool types."""
    SELECT = "select"
    WALL = "wall"
    DOOR = "door"
    WINDOW = "window"
    ROOM = "room"
    PAN = "pan"
    ZOOM = "zoom"


class BaseTool(ABC):
    """
    Abstract base class for all CAD tools.
    Implements the Tool pattern for handling different edit modes.
    """

    def __init__(self, view: QGraphicsView, document: ArchDocument):
        self.view = view
        self.document = document
        self._active = False
        self._cursor = Qt.CursorShape.ArrowCursor

    @property
    def name(self) -> str:
        """Tool name for display."""
        return self.__class__.__name__

    @property
    def tool_type(self) -> ToolType:
        """Get the tool type."""
        return ToolType.SELECT

    @property
    def cursor(self) -> Qt.CursorShape:
        """Get cursor for this tool."""
        return self._cursor

    def activate(self):
        """Called when tool becomes active."""
        self._active = True
        self.view.setCursor(self._cursor)

    def deactivate(self):
        """Called when tool becomes inactive."""
        self._active = False
        self.view.setCursor(Qt.CursorShape.ArrowCursor)

    @abstractmethod
    def mouse_press(self, event: QMouseEvent, scene_pos: QPointF):
        """Handle mouse press event."""
        pass

    @abstractmethod
    def mouse_move(self, event: QMouseEvent, scene_pos: QPointF):
        """Handle mouse move event."""
        pass

    @abstractmethod
    def mouse_release(self, event: QMouseEvent, scene_pos: QPointF):
        """Handle mouse release event."""
        pass

    def mouse_double_click(self, event: QMouseEvent, scene_pos: QPointF):
        """Handle mouse double click event."""
        pass

    def key_press(self, event: QKeyEvent):
        """Handle key press event."""
        pass

    def key_release(self, event: QKeyEvent):
        """Handle key release event."""
        pass

    def cancel(self):
        """Cancel current operation."""
        pass

    def snap_to_grid(self, point: QPointF, grid_size: float) -> QPointF:
        """Snap point to grid."""
        x = round(point.x() / grid_size) * grid_size
        y = round(point.y() / grid_size) * grid_size
        return QPointF(x, y)

    def snap_to_ortho(self, start: QPointF, end: QPointF) -> QPointF:
        """Snap to orthogonal (horizontal or vertical)."""
        dx = abs(end.x() - start.x())
        dy = abs(end.y() - start.y())

        if dx > dy:
            # Horizontal
            return QPointF(end.x(), start.y())
        else:
            # Vertical
            return QPointF(start.x(), end.y())
