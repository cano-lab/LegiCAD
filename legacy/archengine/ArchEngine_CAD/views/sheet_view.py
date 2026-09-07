"""
Sheet View - SVG drawing viewer with zoom/pan support.

Displays generated drawing sheets with:
- SVG rendering using QSvgRenderer
- Zoom/pan controls matching PlanView
- Clickable reference markers for navigation
- Editable dimension annotations
"""
from typing import Optional, List, Dict

from PyQt6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsRectItem,
    QLabel, QVBoxLayout, QWidget
)
from PyQt6.QtCore import Qt, QRectF, pyqtSignal, QByteArray
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QFont
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtSvgWidgets import QGraphicsSvgItem

from sheets.models import SheetConfig
from sheets.dimension_item import DimensionItem, DimensionData
from sheets.svg_parser import parse_svg_dimensions, remove_dimensions_from_svg, apply_dimension_overrides
from app.config import Config


class SheetView(QGraphicsView):
    """
    SVG drawing viewer with zoom/pan support.

    Displays generated SVG content from drawing sheets with
    interactive navigation features and editable dimensions.
    """

    # Signals
    reference_clicked = pyqtSignal(str)  # target_sheet_id
    dimension_changed = pyqtSignal(str, str, str)  # sheet_id, dimension_id, new_value

    def __init__(self, config: Config, parent=None):
        super().__init__(parent)
        self._config = config
        self._sheet: Optional[SheetConfig] = None
        self._svg_item: Optional[QGraphicsSvgItem] = None
        self._renderer: Optional[QSvgRenderer] = None

        # Editable dimensions
        self._dimension_items: List[DimensionItem] = []
        self._dimensions_enabled = True  # Toggle for editable dimensions

        # Create scene
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)

        # View settings
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing |
            QPainter.RenderHint.SmoothPixmapTransform |
            QPainter.RenderHint.TextAntialiasing
        )
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)

        # State
        self._zoom = 1.0
        self._min_zoom = 0.001  # Allow much more zoom out
        self._max_zoom = 100.0  # Allow much more zoom in
        self._panning = False

        # Colors
        self._bg_color = QColor("#f8f8f8")
        self.setBackgroundBrush(self._bg_color)

        # Enable scroll bars for panning
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        # Placeholder for empty state
        self._placeholder_text = None
        self._show_placeholder("No drawing loaded")

    # =========================================================================
    # Public API
    # =========================================================================

    @property
    def sheet(self) -> Optional[SheetConfig]:
        """Get current sheet."""
        return self._sheet

    def set_sheet(self, sheet: Optional[SheetConfig]):
        """
        Set the sheet to display.

        Args:
            sheet: Sheet configuration, or None to clear
        """
        self._sheet = sheet

        if sheet and sheet.svg_content:
            self._load_svg(sheet.svg_content)
        else:
            self._clear()
            if sheet:
                self._show_placeholder(f"'{sheet.title}' not yet generated")
            else:
                self._show_placeholder("No drawing loaded")

    def update_content(self):
        """Refresh content from current sheet's SVG."""
        if self._sheet and self._sheet.svg_content:
            self._load_svg(self._sheet.svg_content)

    def clear(self):
        """Clear the view."""
        self._sheet = None
        self._clear()
        self._show_placeholder("No drawing loaded")

    # =========================================================================
    # Dimension Editing
    # =========================================================================

    @property
    def dimensions_enabled(self) -> bool:
        """Check if editable dimensions are enabled."""
        return self._dimensions_enabled

    @dimensions_enabled.setter
    def dimensions_enabled(self, enabled: bool):
        """Enable or disable editable dimensions."""
        if self._dimensions_enabled != enabled:
            self._dimensions_enabled = enabled
            # Reload if we have content
            if self._sheet and self._sheet.svg_content:
                self._load_svg(self._sheet.svg_content)

    @property
    def dimension_items(self) -> List[DimensionItem]:
        """Get list of dimension items."""
        return list(self._dimension_items)

    def get_dimension_overrides(self) -> Dict[str, str]:
        """Get all dimension overrides for the current sheet."""
        if self._sheet:
            return dict(self._sheet.dimension_overrides)
        return {}

    def clear_all_overrides(self):
        """Clear all dimension overrides and restore original values."""
        if self._sheet:
            self._sheet.dimension_overrides.clear()
            # Reload to apply
            if self._sheet.svg_content:
                self._load_svg(self._sheet.svg_content)

    def clear_selected_overrides(self):
        """Clear overrides for selected dimension items."""
        for item in self._dimension_items:
            if item.isSelected():
                item.clear_override()

    # =========================================================================
    # Zoom/Pan
    # =========================================================================

    @property
    def zoom_level(self) -> float:
        """Get current zoom level."""
        return self._zoom

    def zoom_in(self):
        """Zoom in by 25%."""
        self._zoom_by(1.25)

    def zoom_out(self):
        """Zoom out by 25%."""
        self._zoom_by(0.8)

    def zoom_fit(self):
        """Zoom to fit the drawing including dimensions."""
        if self._svg_item:
            # Get bounding rect of SVG item and all dimension items
            rect = self._svg_item.boundingRect()

            # Include dimension items in bounding rect
            for dim_item in self._dimension_items:
                dim_rect = dim_item.mapRectToScene(dim_item.boundingRect())
                rect = rect.united(dim_rect)

            if not rect.isEmpty():
                # Add margin
                margin = min(rect.width(), rect.height()) * 0.05
                rect.adjust(-margin, -margin, margin, margin)
                self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
                self._zoom = self.transform().m11()
        else:
            # Fit to scene
            rect = self._scene.itemsBoundingRect()
            if not rect.isEmpty():
                self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
                self._zoom = self.transform().m11()

    def zoom_100(self):
        """Reset to 100% zoom."""
        self.resetTransform()
        self._zoom = 1.0

    def _zoom_by(self, factor: float, center_on_mouse: bool = False, mouse_pos=None):
        """Zoom by a factor."""
        new_zoom = self._zoom * factor
        if self._min_zoom <= new_zoom <= self._max_zoom:
            if center_on_mouse and mouse_pos is not None:
                old_scene_pos = self.mapToScene(mouse_pos)
                self._zoom = new_zoom
                self.scale(factor, factor)
                new_pos = self.mapFromScene(old_scene_pos)
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


    # =========================================================================
    # Internal Methods
    # =========================================================================

    def _load_svg(self, svg_content: str, preserve_transform: bool = False):
        """Load SVG content into the view.

        Args:
            svg_content: Raw SVG string
            preserve_transform: If True, maintain current zoom/pan (for LOD reload)
        """
        # Store raw content for LOD re-injection
        self._raw_svg_content = svg_content

        # Save current transform if preserving
        old_transform = self.transform() if preserve_transform else None
        old_scroll_h = self.horizontalScrollBar().value() if preserve_transform else 0
        old_scroll_v = self.verticalScrollBar().value() if preserve_transform else 0

        self._clear()

        try:
            # Extract dimensions for editable overlay
            if self._dimensions_enabled:
                dimensions = parse_svg_dimensions(svg_content)

                # Apply any saved overrides
                if self._sheet and self._sheet.dimension_overrides:
                    apply_dimension_overrides(dimensions, self._sheet.dimension_overrides)

                # Remove dimensions from base SVG to avoid double-rendering
                svg_content = remove_dimensions_from_svg(svg_content)
            else:
                dimensions = []


            # Create renderer from SVG content
            svg_bytes = QByteArray(svg_content.encode('utf-8'))
            self._renderer = QSvgRenderer(svg_bytes)

            if not self._renderer.isValid():
                self._show_placeholder("Invalid SVG content")
                return

            # Create SVG item
            self._svg_item = QGraphicsSvgItem()
            self._svg_item.setSharedRenderer(self._renderer)
            self._scene.addItem(self._svg_item)

            # Create editable dimension items (with coordinate transformation)
            self._create_dimension_items(dimensions, svg_content)

            # Restore transform or fit to view
            if preserve_transform and old_transform:
                self.setTransform(old_transform)
                self.horizontalScrollBar().setValue(old_scroll_h)
                self.verticalScrollBar().setValue(old_scroll_v)
            else:
                self.zoom_fit()


        except Exception as e:
            self._show_placeholder(f"Error loading SVG: {e}")

    def _clear(self):
        """Clear all items from the scene."""
        if self._svg_item:
            self._scene.removeItem(self._svg_item)
            self._svg_item = None
        self._renderer = None

        # Clear dimension items
        for dim_item in self._dimension_items:
            if dim_item.scene():
                self._scene.removeItem(dim_item)
        self._dimension_items.clear()

        # Clear placeholder if any
        if self._placeholder_text:
            self._scene.removeItem(self._placeholder_text)
            self._placeholder_text = None

        self._scene.clear()

    def _create_dimension_items(self, dimensions: List[DimensionData], svg_content: str = None):
        """Create editable dimension overlay items with coordinate transformation."""
        # Get SVG viewBox for coordinate transformation
        viewbox = self._parse_viewbox(svg_content) if svg_content else None
        svg_rect = self._svg_item.boundingRect() if self._svg_item else None

        for dim_data in dimensions:
            # Transform coordinates from SVG viewBox to scene pixels
            if viewbox and svg_rect:
                x = (dim_data.x - viewbox[0]) / viewbox[2] * svg_rect.width()
                y = (dim_data.y - viewbox[1]) / viewbox[3] * svg_rect.height()
                dim_data.x = x
                dim_data.y = y

            dim_item = DimensionItem(dim_data, on_changed=self._on_dimension_changed)
            self._scene.addItem(dim_item)
            self._dimension_items.append(dim_item)

    def _parse_viewbox(self, svg_content: str) -> Optional[Tuple[float, float, float, float]]:
        """Parse viewBox from SVG content."""
        import re
        match = re.search(r'viewBox="([^"]+)"', svg_content)
        if match:
            parts = match.group(1).split()
            if len(parts) == 4:
                try:
                    return tuple(float(p) for p in parts)
                except ValueError:
                    pass
        return None

    def _on_dimension_changed(self, dim_data: DimensionData):
        """Handle dimension value change."""
        if not self._sheet:
            return

        # Update the sheet's dimension overrides
        if dim_data.is_overridden:
            self._sheet.dimension_overrides[dim_data.id] = dim_data.override_text
        else:
            # Remove override if cleared
            self._sheet.dimension_overrides.pop(dim_data.id, None)

        # Emit signal for external handlers
        self.dimension_changed.emit(
            self._sheet.id,
            dim_data.id,
            dim_data.override_text or dim_data.original_text
        )

    def _show_placeholder(self, message: str):
        """Show a placeholder message."""
        self._clear()

        # Create text item
        from PyQt6.QtWidgets import QGraphicsTextItem

        self._placeholder_text = QGraphicsTextItem(message)
        self._placeholder_text.setDefaultTextColor(QColor("#999"))
        font = QFont("Arial", 14)
        self._placeholder_text.setFont(font)

        # Center in view
        rect = self._placeholder_text.boundingRect()
        self._placeholder_text.setPos(-rect.width() / 2, -rect.height() / 2)

        self._scene.addItem(self._placeholder_text)

    # =========================================================================
    # Keyboard Events
    # =========================================================================

    def keyPressEvent(self, event):
        """Handle keyboard shortcuts."""
        if event.key() == Qt.Key.Key_H:
            self.zoom_fit()
        elif event.key() == Qt.Key.Key_Plus or event.key() == Qt.Key.Key_Equal:
            self.zoom_in()
        elif event.key() == Qt.Key.Key_Minus:
            self.zoom_out()
        elif event.key() == Qt.Key.Key_0:
            self.zoom_100()
        else:
            super().keyPressEvent(event)

    # =========================================================================
    # Mouse Events
    # =========================================================================

    def wheelEvent(self, event):
        """Handle mouse wheel for zooming."""
        mouse_pos = event.position().toPoint()
        # More aggressive zoom for faster navigation
        if event.angleDelta().y() > 0:
            self._zoom_by(1.25, center_on_mouse=True, mouse_pos=mouse_pos)
        else:
            self._zoom_by(0.8, center_on_mouse=True, mouse_pos=mouse_pos)

    def mousePressEvent(self, event):
        """Handle mouse press - left or middle button for panning."""
        if event.button() in (Qt.MouseButton.MiddleButton, Qt.MouseButton.LeftButton):
            self._panning = True
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            # Fake left button for drag mode
            fake_event = type(event)(
                event.type(),
                event.position(),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                event.modifiers()
            )
            super().mousePressEvent(fake_event)
        else:
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        """Handle mouse release."""
        if event.button() in (Qt.MouseButton.MiddleButton, Qt.MouseButton.LeftButton) and self._panning:
            fake_event = type(event)(
                event.type(),
                event.position(),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                event.modifiers()
            )
            super().mouseReleaseEvent(fake_event)
            self._panning = False
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
        else:
            super().mouseReleaseEvent(event)


class SheetViewContainer(QWidget):
    """
    Container widget for SheetView with status bar.

    Shows sheet title, scale, and status information.
    """

    reference_clicked = pyqtSignal(str)

    def __init__(self, config: Config, parent=None):
        super().__init__(parent)
        self._config = config
        self._sheet: Optional[SheetConfig] = None

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Sheet view
        self._view = SheetView(self._config, self)
        self._view.reference_clicked.connect(self.reference_clicked.emit)
        layout.addWidget(self._view)

        # Status bar
        self._status_bar = QLabel()
        self._status_bar.setStyleSheet(
            "background: #f0f0f0; padding: 4px 8px; color: #666; font-size: 11px;"
        )
        self._update_status()
        layout.addWidget(self._status_bar)

    @property
    def view(self) -> SheetView:
        """Get the sheet view."""
        return self._view

    def set_sheet(self, sheet: Optional[SheetConfig]):
        """Set the sheet to display."""
        self._sheet = sheet
        self._view.set_sheet(sheet)
        self._update_status()

    def update_content(self):
        """Refresh content."""
        self._view.update_content()
        self._update_status()

    def _update_status(self):
        """Update status bar text."""
        if self._sheet:
            status = f"{self._sheet.number} - {self._sheet.title}"
            status += f"  |  Scale: {self._sheet.scale}"
            status += f"  |  {self._sheet.status}"
            status += f"  |  Zoom: {self._view.zoom_level:.0%}"
        else:
            status = "No sheet selected"

        self._status_bar.setText(status)
