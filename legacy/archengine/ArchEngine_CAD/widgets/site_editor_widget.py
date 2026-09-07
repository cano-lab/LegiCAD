"""
Site Editor Widget for PyQt6
==============================
Simple 2D widget for drawing/editing site boundaries without QWebEngine.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from PyQt6.QtCore import Qt, QPointF, QRectF, pyqtSignal
from PyQt6.QtGui import QPainter, QBrush, QPen, QColor, QFont, QMouseEvent
import math


class SiteEditorWidget(QWidget):
    """2D widget for drawing and editing site boundaries."""

    # Signals
    boundary_changed = pyqtSignal(float, float, float, float)  # lat_min, lat_max, lng_min, lng_max

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumHeight(400)

        # Site dimensions in feet
        self._width_ft = 100.0
        self._depth_ft = 120.0

        # Visual scale (pixels per foot)
        self._scale = 3.0

        # Corner handles (in local coordinates)
        self._corner_size = 10
        self._dragging_corner = None  # 'tl', 'tr', 'bl', 'br', or None

        # Boundary info
        self._boundary_info = ""

    def set_size_ft(self, width_ft: float, depth_ft: float):
        """Set the site size in feet."""
        self._width_ft = max(10, width_ft)
        self._depth_ft = max(10, depth_ft)
        self._update_boundary_info()
        self.update()

    def get_size_ft(self) -> tuple[float, float]:
        """Get the site size in feet."""
        return self._width_ft, self._depth_ft

    def paintEvent(self, event):
        """Paint the site editor."""
        # Safety check for widget size
        if self.width() <= 0 or self.height() <= 0:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Fill background
        painter.fillRect(self.rect(), QColor(245, 245, 245))

        # Calculate centered rectangle
        center_x = self.width() / 2
        center_y = self.height() / 2
        rect_width = self._width_ft * self._scale
        rect_height = self._depth_ft * self._scale

        rect = QRectF(
            center_x - rect_width / 2,
            center_y - rect_height / 2,
            rect_width,
            rect_height
        )

        # Draw grid
        self._draw_grid(painter)

        # Draw property rectangle
        painter.setPen(QPen(QColor(34, 139, 34), 2))  # Green
        painter.setBrush(QBrush(QColor(76, 175, 80, 50)))  # Semi-transparent green
        painter.drawRect(rect)

        # Draw dimensions
        try:
            self._draw_dimensions(painter, rect)
        except Exception:
            pass  # Skip dimensions if there's an error

        # Draw corner handles
        try:
            self._draw_corners(painter, rect)
        except Exception:
            pass  # Skip corners if there's an error

        # Draw title
        painter.setPen(QColor(66, 66, 66))
        painter.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        painter.drawText(10, 20, "Site Boundary - Drag corners to resize")

        # Draw boundary info
        if self._boundary_info:
            painter.setFont(QFont("Arial", 9))
            painter.drawText(10, int(rect.bottom()) + 30, self._boundary_info)

    def _draw_grid(self, painter):
        """Draw background grid."""
        painter.setPen(QPen(QColor(220, 220, 220), 1))
        grid_spacing = 30  # 10 feet at scale 3.0

        for x in range(0, self.width(), grid_spacing):
            painter.drawLine(x, 0, x, self.height())

        for y in range(0, self.height(), grid_spacing):
            painter.drawLine(0, y, self.width(), y)

    def _draw_dimensions(self, painter, rect):
        """Draw dimension labels."""
        painter.setPen(QColor(66, 66, 66))
        painter.setFont(QFont("Arial", 8))

        # Width label (top)
        width_text = f"{self._width_ft:.0f} ft"
        text_width = painter.fontMetrics().horizontalAdvance(width_text)
        x_pos = int(rect.center().x() - text_width / 2)
        y_pos = int(rect.top()) - 15
        painter.drawText(x_pos, y_pos, width_text)

        # Depth label (left side)
        depth_text = f"{self._depth_ft:.0f} ft"
        painter.save()
        painter.translate(int(rect.left()) - 15, int(rect.center().y()))
        painter.rotate(-90)
        text_width_depth = painter.fontMetrics().horizontalAdvance(depth_text)
        x_pos_depth = int(-text_width_depth / 2)
        painter.drawText(x_pos_depth, 0, depth_text)
        painter.restore()

    def _draw_corners(self, painter, rect):
        """Draw corner handles."""
        painter.setPen(QPen(QColor(33, 150, 243), 2))
        painter.setBrush(QBrush(QColor(255, 255, 255)))

        corners = [
            (rect.topLeft(), 'tl'),
            (rect.topRight(), 'tr'),
            (rect.bottomLeft(), 'bl'),
            (rect.bottomRight(), 'br')
        ]

        for point, name in corners:
            handle = QRectF(
                point.x() - self._corner_size / 2,
                point.y() - self._corner_size / 2,
                self._corner_size,
                self._corner_size
            )
            painter.drawRect(handle)

    def mousePressEvent(self, event: QMouseEvent):
        """Handle mouse press - start dragging."""
        try:
            if event.button() == Qt.MouseButton.LeftButton:
                corner = self._get_corner_at_position(event.position())
                if corner:
                    self._dragging_corner = corner
        except Exception:
            pass

    def mouseMoveEvent(self, event: QMouseEvent):
        """Handle mouse move - resize if dragging."""
        try:
            if self._dragging_corner and event.buttons() & Qt.MouseButton.LeftButton:
                pos = event.position()
                center_x = self.width() / 2
                center_y = self.height() / 2

                # Calculate new size based on which corner is being dragged
                if self._dragging_corner == 'br':  # Bottom right
                    new_width_ft = max(10, (pos.x() - center_x) * 2 / self._scale)
                    new_depth_ft = max(10, (pos.y() - center_y) * 2 / self._scale)
                    self._width_ft = new_width_ft
                    self._depth_ft = new_depth_ft

                elif self._dragging_corner == 'bl':  # Bottom left
                    new_width_ft = max(10, (center_x - pos.x()) * 2 / self._scale)
                    new_depth_ft = max(10, (pos.y() - center_y) * 2 / self._scale)
                    self._width_ft = new_width_ft
                    self._depth_ft = new_depth_ft

                elif self._dragging_corner == 'tr':  # Top right
                    new_width_ft = max(10, (pos.x() - center_x) * 2 / self._scale)
                    new_depth_ft = max(10, (center_y - pos.y()) * 2 / self._scale)
                    self._width_ft = new_width_ft
                    self._depth_ft = new_depth_ft

                elif self._dragging_corner == 'tl':  # Top left
                    new_width_ft = max(10, (center_x - pos.x()) * 2 / self._scale)
                    new_depth_ft = max(10, (center_y - pos.y()) * 2 / self._scale)
                    self._width_ft = new_width_ft
                    self._depth_ft = new_depth_ft

                self._update_boundary_info()
                self.update()
        except Exception:
            pass

    def mouseReleaseEvent(self, event: QMouseEvent):
        """Handle mouse release - stop dragging."""
        try:
            if event.button() == Qt.MouseButton.LeftButton:
                if self._dragging_corner:
                    self._dragging_corner = None
                    # Emit signal with new boundary
                    self._emit_boundary()
        except Exception:
            self._dragging_corner = None

    def _get_corner_at_position(self, pos: QPointF) -> str:
        """Get which corner is at the given position."""
        try:
            center_x = self.width() / 2
            center_y = self.height() / 2
            rect_width = self._width_ft * self._scale
            rect_height = self._depth_ft * self._scale

            corners = {
                'tl': QPointF(center_x - rect_width / 2, center_y - rect_height / 2),
                'tr': QPointF(center_x + rect_width / 2, center_y - rect_height / 2),
                'bl': QPointF(center_x - rect_width / 2, center_y + rect_height / 2),
                'br': QPointF(center_x + rect_width / 2, center_y + rect_height / 2),
            }

            for name, corner_pos in corners.items():
                if (pos - corner_pos).manhattanLength() < self._corner_size * 1.5:
                    return name
        except Exception:
            pass

        return None

    def _update_boundary_info(self):
        """Update boundary info text."""
        area_sqft = self._width_ft * self._depth_ft
        self._boundary_info = f"Area: {self._width_ft:.0f}' × {self._depth_ft:.0f}' = {area_sqft:.0f} sq ft"

    def _emit_boundary(self):
        """Emit boundary changed signal."""
        # For now, emit dummy coordinates
        # In the future, this could calculate actual lat/lng bounds
        self.boundary_changed.emit(0, 0, 0, 0)
