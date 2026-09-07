"""
Selection tool for selecting and manipulating elements
"""
from typing import Optional, List

from PyQt6.QtCore import Qt, QPointF, QRectF
from PyQt6.QtGui import QMouseEvent, QKeyEvent, QPen, QColor, QBrush
from PyQt6.QtWidgets import QGraphicsItem, QGraphicsRectItem

from tools.base_tool import BaseTool, ToolType
from core.events import event_bus


class SelectTool(BaseTool):
    """
    Selection tool for picking and manipulating elements.
    Supports click selection and box selection.
    """

    def __init__(self, view, document):
        super().__init__(view, document)
        self._cursor = Qt.CursorShape.ArrowCursor

        # Selection state
        self._selection_start: Optional[QPointF] = None
        self._selection_rect: Optional[QGraphicsRectItem] = None
        self._dragging = False

    @property
    def tool_type(self) -> ToolType:
        return ToolType.SELECT

    def activate(self):
        super().activate()
        # Clear any pending selection
        self._selection_start = None
        self._cleanup_selection_rect()

    def deactivate(self):
        super().deactivate()
        self._cleanup_selection_rect()

    def mouse_press(self, event: QMouseEvent, scene_pos: QPointF):
        """Start selection or begin drag."""
        if event.button() != Qt.MouseButton.LeftButton:
            return

        # Check if clicking on an item
        item = self.view.scene.itemAt(scene_pos, self.view.transform())

        if item:
            # Clicked on item
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                # Toggle selection with Shift
                item.setSelected(not item.isSelected())
            elif event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                # Add to selection with Ctrl
                item.setSelected(True)
            else:
                # Regular click - select only this
                if not item.isSelected():
                    self._clear_selection()
                    item.setSelected(True)
            self._dragging = True
        else:
            # Clicked on empty space - start box selection
            if not (event.modifiers() & (Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.ControlModifier)):
                self._clear_selection()
            self._start_box_selection(scene_pos)

        self._emit_selection_changed()

    def mouse_move(self, event: QMouseEvent, scene_pos: QPointF):
        """Update box selection or drag."""
        if self._selection_start and self._selection_rect:
            # Update box selection
            self._update_box_selection(scene_pos)

    def mouse_release(self, event: QMouseEvent, scene_pos: QPointF):
        """Complete selection."""
        if event.button() != Qt.MouseButton.LeftButton:
            return

        if self._selection_rect:
            # Complete box selection
            self._complete_box_selection(event.modifiers())

        self._dragging = False
        self._emit_selection_changed()

    def key_press(self, event: QKeyEvent):
        """Handle key events."""
        if event.key() == Qt.Key.Key_Escape:
            self.cancel()
        elif event.key() == Qt.Key.Key_Delete:
            self._delete_selected()
        elif event.key() == Qt.Key.Key_A and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._select_all()

    def cancel(self):
        """Cancel current selection operation."""
        self._cleanup_selection_rect()
        self._selection_start = None

    def _start_box_selection(self, pos: QPointF):
        """Start box selection."""
        self._selection_start = pos

        # Create selection rectangle
        self._selection_rect = QGraphicsRectItem()
        self._selection_rect.setPen(QPen(QColor(100, 150, 255), 1, Qt.PenStyle.DashLine))
        self._selection_rect.setBrush(QBrush(QColor(100, 150, 255, 30)))
        self._selection_rect.setRect(QRectF(pos, pos))
        self._selection_rect.setZValue(1000)
        self.view.scene.addItem(self._selection_rect)

    def _update_box_selection(self, pos: QPointF):
        """Update box selection rectangle."""
        if not self._selection_start or not self._selection_rect:
            return

        rect = QRectF(self._selection_start, pos).normalized()
        self._selection_rect.setRect(rect)

    def _complete_box_selection(self, modifiers):
        """Complete box selection and select enclosed items."""
        if not self._selection_rect:
            return

        rect = self._selection_rect.rect()

        # Find items in rect
        items = self.view.scene.items(rect)

        # Filter to selectable items
        selectable_items = [
            item for item in items
            if item.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            and item != self._selection_rect
        ]

        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            # Add to selection
            for item in selectable_items:
                item.setSelected(True)
        elif modifiers & Qt.KeyboardModifier.ControlModifier:
            # Toggle selection
            for item in selectable_items:
                item.setSelected(not item.isSelected())
        else:
            # Replace selection
            for item in selectable_items:
                item.setSelected(True)

        self._cleanup_selection_rect()

    def _cleanup_selection_rect(self):
        """Remove selection rectangle from scene."""
        if self._selection_rect:
            self.view.scene.removeItem(self._selection_rect)
            self._selection_rect = None
        self._selection_start = None

    def _clear_selection(self):
        """Clear all selected items."""
        for item in self.view.scene.selectedItems():
            item.setSelected(False)

    def _select_all(self):
        """Select all selectable items."""
        for item in self.view.scene.items():
            if item.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsSelectable:
                item.setSelected(True)
        self._emit_selection_changed()

    def _delete_selected(self):
        """Delete selected items."""
        try:
            selected = list(self.view.scene.selectedItems())
            if not selected:
                return

            # Clear selection first to avoid issues during scene rebuild
            for item in selected:
                try:
                    item.setSelected(False)
                except:
                    pass

            # Group items by type and collect indices
            walls_to_delete = []
            doors_to_delete = []
            windows_to_delete = []
            rooms_to_delete = []

            for item in selected:
                try:
                    item_type = type(item).__name__

                    # Skip grip items and helper graphics
                    if item_type in ("GripItem", "QGraphicsRectItem"):
                        continue

                    if item_type == "WallItem":
                        if hasattr(item, 'wall') and item.wall is not None:
                            walls_to_delete.append(item.wall.index)
                    elif item_type == "DoorItem":
                        if hasattr(item, 'door') and item.door is not None:
                            doors_to_delete.append(item.door.index)
                    elif item_type == "WindowItem":
                        if hasattr(item, 'window') and item.window is not None:
                            windows_to_delete.append(item.window.index)
                    elif item_type == "RoomItem":
                        if hasattr(item, 'room') and item.room is not None:
                            rooms_to_delete.append(item.room.id)
                except Exception:
                    pass

            # Remove duplicates
            walls_to_delete = list(set(walls_to_delete))
            doors_to_delete = list(set(doors_to_delete))
            windows_to_delete = list(set(windows_to_delete))
            rooms_to_delete = list(set(rooms_to_delete))

            # Delete in reverse index order to avoid index shifting issues
            for idx in sorted(walls_to_delete, reverse=True):
                self.document.delete_wall_undoable(idx)

            for idx in sorted(doors_to_delete, reverse=True):
                self.document.delete_door_undoable(idx)

            for idx in sorted(windows_to_delete, reverse=True):
                self.document.delete_window_undoable(idx)

            for room_id in rooms_to_delete:
                self.document.delete_room_undoable(room_id)

            total_deleted = len(walls_to_delete) + len(doors_to_delete) + len(windows_to_delete) + len(rooms_to_delete)
            if total_deleted > 0:
                event_bus.status_message.emit(f"Deleted {total_deleted} item(s)", 3000)
            self._emit_selection_changed()
        except Exception as e:
            event_bus.status_message.emit(f"Delete failed: {e}", 5000)

    def _emit_selection_changed(self):
        """Emit selection changed signal."""
        selected = self.view.scene.selectedItems()
        event_bus.selection_changed.emit(selected)
