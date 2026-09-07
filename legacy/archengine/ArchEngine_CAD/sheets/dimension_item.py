"""
Editable dimension item for CAD drawings.

DimensionItem represents a dimension annotation that can be:
- Selected and highlighted
- Double-clicked to edit the text value
- Overridden with custom text while preserving the original value
"""
from typing import Optional, Dict, Any, Callable
from dataclasses import dataclass

from PyQt6.QtWidgets import (
    QGraphicsTextItem, QGraphicsItem, QLineEdit,
    QGraphicsProxyWidget, QStyle
)
from PyQt6.QtCore import Qt, QRectF, pyqtSignal, QObject
from PyQt6.QtGui import (
    QFont, QColor, QPainter, QPen, QBrush,
    QFocusEvent, QKeyEvent
)


@dataclass
class DimensionData:
    """Data extracted from an SVG dimension element."""
    id: str                    # Unique identifier
    x: float                   # X position in SVG coordinates
    y: float                   # Y position
    original_text: str         # Original dimension text (e.g., "3500")
    override_text: Optional[str] = None  # User-overridden text
    font_size: float = 300     # Font size in SVG units
    font_family: str = "Arial"
    font_weight: str = "bold"
    text_anchor: str = "middle"
    rotation: float = 0        # Rotation angle in degrees
    transform: Optional[str] = None  # Original SVG transform

    @property
    def display_text(self) -> str:
        """Get the text to display (override or original)."""
        return self.override_text if self.override_text else self.original_text

    @property
    def is_overridden(self) -> bool:
        """Check if dimension has been overridden."""
        return self.override_text is not None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            'id': self.id,
            'x': self.x,
            'y': self.y,
            'original_text': self.original_text,
            'override_text': self.override_text,
            'font_size': self.font_size,
            'rotation': self.rotation,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DimensionData':
        """Deserialize from dictionary."""
        return cls(
            id=data['id'],
            x=data['x'],
            y=data['y'],
            original_text=data['original_text'],
            override_text=data.get('override_text'),
            font_size=data.get('font_size', 300),
            rotation=data.get('rotation', 0),
        )


class DimensionEditBox(QLineEdit):
    """
    Line edit for inline dimension editing.

    Emits finished signal when editing is complete (Enter or focus lost).
    """

    editing_finished = pyqtSignal(str)  # New text value
    editing_cancelled = pyqtSignal()

    def __init__(self, initial_text: str, parent=None):
        super().__init__(initial_text, parent)
        self._original_text = initial_text

        # Style the edit box
        self.setFrame(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.selectAll()

        # Style
        self.setStyleSheet("""
            QLineEdit {
                background: white;
                border: 2px solid #2196F3;
                border-radius: 2px;
                padding: 2px 4px;
                font-weight: bold;
            }
        """)

    def focusOutEvent(self, event: QFocusEvent):
        """Handle focus loss - finish editing."""
        super().focusOutEvent(event)
        self._finish_editing()

    def keyPressEvent(self, event: QKeyEvent):
        """Handle key events."""
        if event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
            self._finish_editing()
        elif event.key() == Qt.Key.Key_Escape:
            self.editing_cancelled.emit()
        else:
            super().keyPressEvent(event)

    def _finish_editing(self):
        """Complete editing and emit signal."""
        new_text = self.text().strip()
        if new_text:
            self.editing_finished.emit(new_text)
        else:
            self.editing_cancelled.emit()


class DimensionItem(QGraphicsTextItem):
    """
    Editable dimension annotation item.

    Features:
    - Displays dimension text
    - Can be selected (highlights in blue)
    - Double-click to edit text inline
    - Shows indicator when overridden
    - Stores original value for reference
    """

    def __init__(self, data: DimensionData, on_changed: Optional[Callable] = None, parent=None):
        super().__init__(parent)

        self._data = data
        self._on_changed = on_changed
        self._editing = False
        self._edit_proxy: Optional[QGraphicsProxyWidget] = None

        # Set up item
        self.setPlainText(data.display_text)
        self._update_font()
        self._update_position()

        # Enable interaction
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable |
            QGraphicsItem.GraphicsItemFlag.ItemIsFocusable
        )
        self.setAcceptHoverEvents(True)

        # Colors
        self._normal_color = QColor("#000000")
        self._override_color = QColor("#1565C0")  # Blue for overridden
        self._selected_color = QColor("#2196F3")

        self._update_color()

    @property
    def data(self) -> DimensionData:
        """Get the dimension data."""
        return self._data

    @property
    def dimension_id(self) -> str:
        """Get the dimension ID."""
        return self._data.id

    def _update_font(self):
        """Update font from data."""
        font = QFont(self._data.font_family)
        # Scale font size - SVG units to screen pixels (approximate)
        font.setPointSizeF(self._data.font_size * 0.03)
        if self._data.font_weight == "bold":
            font.setBold(True)
        self.setFont(font)

    def _update_position(self):
        """Update position from data."""
        # Adjust position based on text anchor
        rect = self.boundingRect()
        x = self._data.x
        y = self._data.y

        if self._data.text_anchor == "middle":
            x -= rect.width() / 2
        elif self._data.text_anchor == "end":
            x -= rect.width()

        # Adjust Y to center vertically (SVG text baseline vs Qt top-left)
        y -= rect.height() * 0.8

        self.setPos(x, y)

        # Apply rotation if any
        if self._data.rotation != 0:
            self.setRotation(self._data.rotation)

    def _update_color(self):
        """Update text color based on state."""
        if self.isSelected():
            self.setDefaultTextColor(self._selected_color)
        elif self._data.is_overridden:
            self.setDefaultTextColor(self._override_color)
        else:
            self.setDefaultTextColor(self._normal_color)

    def set_override(self, text: Optional[str]):
        """Set or clear the override text."""
        if text and text.strip():
            self._data.override_text = text.strip()
        else:
            self._data.override_text = None

        self.setPlainText(self._data.display_text)
        self._update_color()
        self._update_position()

        if self._on_changed:
            self._on_changed(self._data)

    def clear_override(self):
        """Clear any override and restore original value."""
        self.set_override(None)

    # =========================================================================
    # Qt Event Overrides
    # =========================================================================

    def paint(self, painter: QPainter, option, widget=None):
        """Custom paint with selection highlight."""
        if self.isSelected():
            # Draw selection highlight background
            rect = self.boundingRect()
            painter.fillRect(rect, QBrush(QColor(33, 150, 243, 40)))
            painter.setPen(QPen(QColor(33, 150, 243), 1, Qt.PenStyle.DashLine))
            painter.drawRect(rect)

        # Draw override indicator
        if self._data.is_overridden and not self.isSelected():
            rect = self.boundingRect()
            indicator_size = 6
            painter.setBrush(QBrush(self._override_color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(
                int(rect.right() - indicator_size - 2),
                int(rect.top() + 2),
                indicator_size,
                indicator_size
            )

        # Draw the text
        super().paint(painter, option, widget)

    def itemChange(self, change, value):
        """Handle item state changes."""
        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedChange:
            # Update color when selection changes
            self._update_color()
        return super().itemChange(change, value)

    def mouseDoubleClickEvent(self, event):
        """Handle double-click to start editing."""
        if not self._editing:
            self._start_editing()
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event: QKeyEvent):
        """Handle key events."""
        if event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_F2:
            if not self._editing:
                self._start_editing()
        elif event.key() == Qt.Key.Key_Delete:
            if self._data.is_overridden:
                self.clear_override()
        else:
            super().keyPressEvent(event)

    # =========================================================================
    # Inline Editing
    # =========================================================================

    def _start_editing(self):
        """Start inline text editing."""
        if self._editing:
            return

        self._editing = True

        # Hide the text item
        self.setVisible(False)

        # Create edit box
        edit_box = DimensionEditBox(self._data.display_text)
        edit_box.setMinimumWidth(60)

        # Calculate size based on content
        fm = edit_box.fontMetrics()
        width = max(60, fm.horizontalAdvance(self._data.display_text) + 20)
        edit_box.setFixedWidth(width)

        # Connect signals
        edit_box.editing_finished.connect(self._finish_editing)
        edit_box.editing_cancelled.connect(self._cancel_editing)

        # Create proxy widget
        self._edit_proxy = QGraphicsProxyWidget(self.parentItem())
        self._edit_proxy.setWidget(edit_box)

        # Position the edit box
        pos = self.pos()
        self._edit_proxy.setPos(pos.x(), pos.y())
        if self._data.rotation != 0:
            self._edit_proxy.setRotation(self._data.rotation)

        # Focus the edit box
        edit_box.setFocus()

    def _finish_editing(self, new_text: str):
        """Complete editing with new value."""
        self._cleanup_editing()

        # Only set override if different from original
        if new_text != self._data.original_text:
            self.set_override(new_text)
        else:
            self.clear_override()

    def _cancel_editing(self):
        """Cancel editing without changes."""
        self._cleanup_editing()

    def _cleanup_editing(self):
        """Clean up editing state."""
        if self._edit_proxy:
            scene = self.scene()
            if scene:
                scene.removeItem(self._edit_proxy)
            self._edit_proxy = None

        self._editing = False
        self.setVisible(True)
        self.setFocus()
