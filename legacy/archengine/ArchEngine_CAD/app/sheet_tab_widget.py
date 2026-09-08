"""
Sheet Tab Widget - Tabbed container for plan view and sheet views.

Provides a tab interface with:
- First tab: Edit mode (PlanView)
- Additional tabs: Drawing sheets (SheetView)
"""
from typing import Optional, Dict

from PyQt6.QtWidgets import QTabWidget, QWidget
from PyQt6.QtCore import pyqtSignal

from views.sheet_view import SheetViewContainer
from sheets.models import SheetConfig
from sheets.sheet_registry import SheetRegistry
from app.config import Config


class SheetTabWidget(QTabWidget):
    """
    Tabbed container for plan editing and sheet viewing.

    The first tab is always the plan editor. Additional tabs
    are opened for viewing generated drawing sheets.
    """

    # Signals
    current_sheet_changed = pyqtSignal(str)  # sheet_id (empty for edit tab)
    sheet_tab_closed = pyqtSignal(str)       # sheet_id

    def __init__(self, config: Config, registry: SheetRegistry, parent=None):
        super().__init__(parent)
        self._config = config
        self._registry = registry
        self._plan_view: Optional[QWidget] = None
        self._sheet_views: Dict[str, SheetViewContainer] = {}

        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        self.setTabsClosable(True)
        self.setMovable(True)
        self.setDocumentMode(True)

        # Connect tab close
        self.tabCloseRequested.connect(self._on_tab_close_requested)
        self.currentChanged.connect(self._on_current_changed)

    def _connect_signals(self):
        """Connect registry signals."""
        self._registry.sheet_content_changed.connect(self._on_sheet_content_changed)
        self._registry.sheet_updated.connect(self._on_sheet_updated)
        self._registry.sheet_removed.connect(self._on_sheet_removed)

    # =========================================================================
    # Public API
    # =========================================================================

    def set_plan_view(self, plan_view: QWidget):
        """
        Set the plan view widget for the first tab.

        Args:
            plan_view: The plan view widget
        """
        self._plan_view = plan_view

        # Add as first tab (not closable)
        index = self.insertTab(0, plan_view, "Edit Plan")
        self.tabBar().setTabButton(index, self.tabBar().ButtonPosition.RightSide, None)
        self.setCurrentIndex(0)

    def open_sheet(self, sheet_id: str):
        """
        Open a sheet in a new tab or switch to existing tab.

        Args:
            sheet_id: ID of sheet to open
        """
        # Check if already open
        if sheet_id in self._sheet_views:
            container = self._sheet_views[sheet_id]
            index = self.indexOf(container)
            if index >= 0:
                self.setCurrentIndex(index)
                return

        # Get sheet
        sheet = self._registry.get_sheet(sheet_id)
        if not sheet:
            return

        # Create view container
        container = SheetViewContainer(self._config, self)
        container.set_sheet(sheet)
        container.reference_clicked.connect(self._on_reference_clicked)

        # Add tab
        index = self.addTab(container, sheet.number)
        self.setTabToolTip(index, sheet.title)
        self._sheet_views[sheet_id] = container

        self.setCurrentIndex(index)

    def close_sheet(self, sheet_id: str):
        """
        Close a sheet tab.

        Args:
            sheet_id: ID of sheet to close
        """
        if sheet_id not in self._sheet_views:
            return

        container = self._sheet_views.pop(sheet_id)
        index = self.indexOf(container)
        if index >= 0:
            self.removeTab(index)

        self.sheet_tab_closed.emit(sheet_id)

    def get_current_sheet_id(self) -> Optional[str]:
        """Get the ID of the currently displayed sheet, or None if on edit tab."""
        widget = self.currentWidget()

        if widget is self._plan_view:
            return None

        for sheet_id, container in self._sheet_views.items():
            if container is widget:
                return sheet_id

        return None

    def refresh_sheet(self, sheet_id: str):
        """Refresh a sheet's content."""
        if sheet_id in self._sheet_views:
            sheet = self._registry.get_sheet(sheet_id)
            if sheet:
                self._sheet_views[sheet_id].set_sheet(sheet)

    def get_open_sheet_ids(self):
        """Get list of open sheet IDs."""
        return list(self._sheet_views.keys())

    # =========================================================================
    # Event Handlers
    # =========================================================================

    def _on_tab_close_requested(self, index: int):
        """Handle tab close button."""
        widget = self.widget(index)

        # Don't close edit tab
        if widget is self._plan_view:
            return

        # Find sheet ID
        for sheet_id, container in list(self._sheet_views.items()):
            if container is widget:
                self.close_sheet(sheet_id)
                break

    def _on_current_changed(self, index: int):
        """Handle current tab changed."""
        widget = self.widget(index)

        if widget is self._plan_view:
            self.current_sheet_changed.emit("")
        else:
            for sheet_id, container in self._sheet_views.items():
                if container is widget:
                    self.current_sheet_changed.emit(sheet_id)
                    break

    def _on_sheet_content_changed(self, sheet_id: str):
        """Handle sheet content updated."""
        if sheet_id in self._sheet_views:
            sheet = self._registry.get_sheet(sheet_id)
            if sheet:
                self._sheet_views[sheet_id].set_sheet(sheet)

    def _on_sheet_updated(self, sheet_id: str):
        """Handle sheet metadata updated."""
        if sheet_id in self._sheet_views:
            sheet = self._registry.get_sheet(sheet_id)
            if sheet:
                container = self._sheet_views[sheet_id]
                index = self.indexOf(container)
                if index >= 0:
                    self.setTabText(index, sheet.number)
                    self.setTabToolTip(index, sheet.title)

    def _on_sheet_removed(self, sheet_id: str):
        """Handle sheet removed from registry."""
        if sheet_id in self._sheet_views:
            self.close_sheet(sheet_id)

    def _on_reference_clicked(self, target_sheet_id: str):
        """Handle reference marker clicked - open target sheet."""
        self.open_sheet(target_sheet_id)
