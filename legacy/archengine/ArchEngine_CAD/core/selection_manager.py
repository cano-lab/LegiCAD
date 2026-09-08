"""
Unified Selection Manager - Single source of truth for element selection.

Provides consistent selection behavior across 2D plan view and 3D viewport.
Replaces the previous bidirectional sync approach with a centralized selection state.
"""
from typing import List, Tuple, Set, Optional, Dict, Any
from PyQt6.QtCore import QObject, pyqtSignal
from dataclasses import dataclass


@dataclass
class SelectionItem:
    """Represents a selected element."""
    element_type: str  # 'wall', 'room', 'door', 'window', etc.
    element_id: str  # ID (could be index, room_id, etc.)

    def __hash__(self):
        return hash((self.element_type, self.element_id))

    def __eq__(self, other):
        if not isinstance(other, SelectionItem):
            return False
        return self.element_type == other.element_type and self.element_id == other.element_id


class SelectionManager(QObject):
    """
    Unified selection manager - single source of truth for selection state.

    Both 2D plan view and 3D viewport subscribe to selection changes
    and update their visual state accordingly.
    """

    # Signals
    selection_changed = pyqtSignal()  # Emitted when selection changes
    selection_cleared = pyqtSignal()  # Emitted when all selection is cleared
    element_selected = pyqtSignal(str, str)  # element_type, element_id
    element_deselected = pyqtSignal(str, str)  # element_type, element_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self._selected_items: Set[SelectionItem] = set()
        self._last_selection: Optional[SelectionItem] = None

    def clear(self) -> None:
        """Clear all selection."""
        if not self._selected_items:
            return  # Already empty

        # Emit deselect signals for all items
        for item in list(self._selected_items):
            self.element_deselected.emit(item.element_type, item.element_id)

        self._selected_items.clear()
        self._last_selection = None
        self.selection_cleared.emit()
        self.selection_changed.emit()

    def select(self, element_type: str, element_id: str, additive: bool = False,
              notify: bool = True) -> None:
        """
        Select an element.

        Args:
            element_type: Type of element ('wall', 'room', 'door', 'window', etc.)
            element_id: ID of the element (could be index as string, room_id, etc.)
            additive: If True, add to selection. If False, replace selection.
            notify: If False, suppress signals (for batch operations)
        """
        new_item = SelectionItem(element_type, element_id)

        if additive:
            # Add to existing selection
            if new_item in self._selected_items:
                return  # Already selected

            self._selected_items.add(new_item)
            self._last_selection = new_item
            if notify:
                self.element_selected.emit(element_type, element_id)
                self.selection_changed.emit()
        else:
            # Replace selection
            if new_item in self._selected_items and len(self._selected_items) == 1:
                return  # Already the only selected item

            # Deselect all current items
            for item in list(self._selected_items):
                if notify:
                    self.element_deselected.emit(item.element_type, item.element_id)

            self._selected_items.clear()
            self._selected_items.add(new_item)
            self._last_selection = new_item

            if notify:
                self.element_selected.emit(element_type, element_id)
                self.selection_cleared.emit()  # Signal that old selection was cleared
                self.selection_changed.emit()

    def deselect(self, element_type: str = None, element_id: str = None,
                 notify: bool = True) -> None:
        """
        Deselect element(s).

        Args:
            element_type: Type of element to deselect. If None, deselect all.
            element_id: ID of element to deselect. If None (with element_type), deselect all of that type.
            notify: If False, suppress signals
        """
        if element_type is None:
            # Clear all
            self.clear()
            return

        items_to_remove = []
        for item in self._selected_items:
            if item.element_type == element_type:
                if element_id is None or item.element_id == element_id:
                    items_to_remove.append(item)

        for item in items_to_remove:
            self._selected_items.remove(item)
            if notify:
                self.element_deselected.emit(item.element_type, item.element_id)

        if items_to_remove and notify:
            if not self._selected_items:
                self.selection_cleared.emit()
            self.selection_changed.emit()

    def is_selected(self, element_type: str, element_id: str) -> bool:
        """Check if an element is selected."""
        return SelectionItem(element_type, element_id) in self._selected_items

    def get_selected(self) -> List[Tuple[str, str]]:
        """
        Get current selection as list of (element_type, element_id) tuples.

        Returns:
            List of (type, id) tuples
        """
        return [(item.element_type, item.element_id) for item in self._selected_items]

    def get_selected_by_type(self, element_type: str) -> List[str]:
        """
        Get all selected elements of a specific type.

        Args:
            element_type: Type to filter by

        Returns:
            List of element_ids
        """
        return [item.element_id for item in self._selected_items if item.element_type == element_type]

    def get_count(self) -> int:
        """Get number of selected items."""
        return len(self._selected_items)

    def is_empty(self) -> bool:
        """Check if selection is empty."""
        return len(self._selected_items) == 0

    def get_last_selected(self) -> Optional[Tuple[str, str]]:
        """
        Get the most recently selected item.

        Returns:
            (element_type, element_id) or None
        """
        if self._last_selection:
            return (self._last_selection.element_type, self._last_selection.element_id)
        return None

    def toggle(self, element_type: str, element_id: str) -> None:
        """
        Toggle selection of an element.

        If selected, deselect it. If not selected, select it (additive).
        """
        if self.is_selected(element_type, element_id):
            self.deselect(element_type, element_id)
        else:
            self.select(element_type, element_id, additive=True)

    def select_all(self, element_type: str = None, element_ids: List[str] = None) -> None:
        """
        Select multiple elements at once.

        Args:
            element_type: Type of elements to select
            element_ids: List of element IDs to select. If None, requires manual building.
        """
        if not element_ids:
            return

        # Batch operation - don't emit for each item
        for elem_id in element_ids:
            new_item = SelectionItem(element_type, elem_id)
            self._selected_items.add(new_item)
            self._last_selection = new_item

        # Emit one signal for all items
        self.selection_changed.emit()

    def get_selection_info(self) -> Dict[str, Any]:
        """
        Get information about current selection.

        Returns:
            Dict with selection metadata
        """
        counts = {}
        for item in self._selected_items:
            counts[item.element_type] = counts.get(item.element_type, 0) + 1

        return {
            'total_count': len(self._selected_items),
            'counts_by_type': counts,
            'last_selected': self.get_last_selected(),
            'is_empty': self.is_empty()
        }
