"""
Base view class for all 2D views
"""
from abc import abstractmethod
from enum import Enum

from PyQt6.QtWidgets import QGraphicsView, QGraphicsScene
from PyQt6.QtCore import Qt, QRectF, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QPen

from core.document import ArchDocument
from app.config import Config


class ViewMode(Enum):
    """2D view modes mirroring the tetrahedron faces."""
    VISION = "vision"      # Design + Client focus - aesthetic, spatial
    BUDGET = "budget"      # Client + Build focus - cost, feasibility
    CRAFT = "craft"        # Build + Design focus - construction, detail
    REALITY = "reality"    # All constraints - balanced view
    WIREFRAME = "wireframe"  # Pure geometry, no fills


class BaseView(QGraphicsView):
    """
    Base class for all 2D views (plan, elevation, section).
    Provides common functionality like zoom, pan, grid.
    """

    # Signal emitted when LOD changes via Shift+scroll
    lod_level_changed = pyqtSignal(int)  # 1-5
    view_mode_changed = pyqtSignal(str)  # ViewMode value

    def __init__(self, document: ArchDocument, config: Config, parent=None):
        super().__init__(parent)
        self.document = document
        self.config = config

        # Create scene
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)

        # View settings
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing |
            QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # State
        self._zoom = 1.0
        self._min_zoom = 0.01
        self._max_zoom = 10.0
        self._panning = False
        self._last_pan_point = None
        self._grid_visible = config.grid_visible
        self._lod_level = 2  # Default LOD level (1-5)
        self._view_mode = ViewMode.REALITY  # Default view mode

        # Colors
        self._bg_color = QColor(self.config.background_color)
        self._grid_color = QColor(self.config.grid_color)

        self.setBackgroundBrush(self._bg_color)

    @property
    def zoom_level(self) -> float:
        """Get current zoom level."""
        return self._zoom

    @property
    def view_mode(self) -> ViewMode:
        """Get current view mode."""
        return self._view_mode

    def set_view_mode(self, mode: ViewMode):
        """Set view mode and refresh."""
        if isinstance(mode, str):
            try:
                mode = ViewMode(mode)
            except ValueError:
                return  # Invalid mode string
        if mode != self._view_mode:
            self._view_mode = mode
            self.view_mode_changed.emit(mode.value)
            self.scene.update()  # Update entire scene to repaint all items
            self.viewport().update()

    @property
    def lod_level(self) -> int:
        """Get current LOD level (1-5)."""
        return self._lod_level

    def set_lod_level(self, level: int):
        """Set LOD level and refresh."""
        level = max(1, min(5, level))
        if level != self._lod_level:
            self._lod_level = level
            self.lod_level_changed.emit(level)
            self.scene.update()  # Update entire scene to repaint all items
            self.viewport().update()

    def set_grid_visible(self, visible: bool):
        """Set grid visibility."""
        self._grid_visible = visible
        self.viewport().update()

    def zoom_in(self):
        """Zoom in by 25%."""
        self._zoom_by(1.25)

    def zoom_out(self):
        """Zoom out by 25%."""
        self._zoom_by(0.8)

    def zoom_fit(self):
        """Zoom to fit all content (items bounding rect)."""
        # Get bounding rect of all items, not the scene rect
        items_rect = self.scene.itemsBoundingRect()
        if items_rect.isNull() or items_rect.isEmpty():
            # No items, center on origin
            items_rect = QRectF(-5000, -5000, 10000, 10000)
        else:
            # Add some margin
            margin = min(items_rect.width(), items_rect.height()) * 0.1
            items_rect.adjust(-margin, -margin, margin, margin)

        self.fitInView(items_rect, Qt.AspectRatioMode.KeepAspectRatio)
        self._zoom = self.transform().m11()

    def _zoom_by(self, factor: float, center_on_mouse: bool = False, mouse_pos=None):
        """Zoom by a factor, optionally centering on mouse position."""
        new_zoom = self._zoom * factor
        if self._min_zoom <= new_zoom <= self._max_zoom:
            if center_on_mouse and mouse_pos is not None:
                # Get scene position under cursor before zoom
                old_scene_pos = self.mapToScene(mouse_pos)

                # Apply zoom
                self._zoom = new_zoom
                self.scale(factor, factor)

                # Get new position of that scene point
                new_pos = self.mapFromScene(old_scene_pos)

                # Calculate delta and adjust scroll
                delta = new_pos - mouse_pos
                self.horizontalScrollBar().setValue(
                    self.horizontalScrollBar().value() + int(delta.x())
                )
                self.verticalScrollBar().setValue(
                    self.verticalScrollBar().value() + int(delta.y())
                )
            else:
                self._zoom = new_zoom
                self.scale(factor, factor)

    @abstractmethod
    def refresh(self):
        """Refresh the view contents. Must be implemented by subclasses."""
        pass

    def drawBackground(self, painter: QPainter, rect: QRectF):
        """Draw background with optional grid."""
        # Fill background
        painter.fillRect(rect, self._bg_color)

        # Draw grid if visible
        if self._grid_visible:
            self._draw_grid(painter, rect)

    def _draw_grid(self, painter: QPainter, rect: QRectF):
        """Draw grid lines."""
        grid_size = self.config.grid_size

        # Get visible area
        left = int(rect.left()) - (int(rect.left()) % grid_size)
        top = int(rect.top()) - (int(rect.top()) % grid_size)

        # Grid pen
        pen = QPen(self._grid_color)
        pen.setWidth(0)  # Cosmetic pen (1px regardless of zoom)
        painter.setPen(pen)

        # Draw vertical lines
        x = left
        while x <= rect.right():
            painter.drawLine(x, int(rect.top()), x, int(rect.bottom()))
            x += grid_size

        # Draw horizontal lines
        y = top
        while y <= rect.bottom():
            painter.drawLine(int(rect.left()), y, int(rect.right()), y)
            y += grid_size

    # =========================================================================
    # Mouse Events
    # =========================================================================

    def wheelEvent(self, event):
        """Handle mouse wheel for zooming - centers on cursor position.

        Shift+scroll changes LOD level instead of zooming.
        """
        delta = event.angleDelta().y()

        # Shift+scroll = LOD change
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            if delta > 0:
                new_lod = max(1, self._lod_level - 1)
            else:
                new_lod = min(5, self._lod_level + 1)
            # Call set_lod_level to trigger visibility updates in subclasses
            self.set_lod_level(new_lod)
            event.accept()
            return

        # Regular scroll = zoom
        mouse_pos = event.position().toPoint()
        if delta > 0:
            self._zoom_by(1.15, center_on_mouse=True, mouse_pos=mouse_pos)
        else:
            self._zoom_by(0.87, center_on_mouse=True, mouse_pos=mouse_pos)

    def mousePressEvent(self, event):
        """Handle mouse press."""
        if event.button() == Qt.MouseButton.MiddleButton:
            # Manual panning - don't forward to items
            self._panning = True
            self._last_pan_point = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """Handle mouse move."""
        if self._panning and self._last_pan_point is not None:
            # Manual panning - scroll the view
            delta = event.position() - self._last_pan_point
            self._last_pan_point = event.position()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - int(delta.x())
            )
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - int(delta.y())
            )
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """Handle mouse release."""
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = False
            self._last_pan_point = None
            self.unsetCursor()
            event.accept()
        else:
            super().mouseReleaseEvent(event)
