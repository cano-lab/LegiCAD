"""
Sheet Manager Panel - Drawing sheet tree view and management.

Provides a tree view of all drawing sheets organized by category,
with context menus for common operations. Supports LegiDoc preset
system for configurable viewport layouts.
"""
from typing import Optional, Dict, List, Any
import sys
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QPushButton, QMenu, QToolButton, QLabel, QLineEdit, QComboBox,
    QProgressBar, QFrame, QDialog, QDialogButtonBox, QFormLayout,
    QSpinBox, QGroupBox, QScrollArea, QSizePolicy, QCheckBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QRectF
from PyQt6.QtGui import QIcon, QAction, QFont, QPainter, QColor, QPen, QBrush

from sheets.models import SheetType, SheetConfig, SHEET_DEFAULTS
from sheets.sheet_registry import SheetRegistry

# Add kernel scripts path for sheet_types imports
kernel_scripts = Path(__file__).parent.parent.parent / "ArchEngine_kernel" / "scripts"
if str(kernel_scripts) not in sys.path:
    sys.path.insert(0, str(kernel_scripts))

try:
    from sheets.sheet_types import (
        DrawingType, SheetType as PresetSheetType, ViewportContent,
        ViewportConfig, SheetPreset, get_preset, list_presets,
    )
    from sheets.sheet_sizes import get_sheet_size
    HAS_PRESETS = True
except ImportError:
    HAS_PRESETS = False




# ============================================================================
# Preset Sheet Dialog
# ============================================================================

class PresetSheetDialog(QDialog):
    """Dialog for creating a sheet from a preset with viewport configuration."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create Sheet from Preset")
        self.setMinimumSize(700, 500)
        self._preset = None
        self._sheet_width = 1296  # ARCH_D default
        self._sheet_height = 864
        self._setup_ui()
        if HAS_PRESETS:
            presets = list_presets()
            if presets:
                self._preset_combo.setCurrentText(presets[0])
                self._on_preset_changed(presets[0])

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Top row: preset and sheet info
        top_row = QHBoxLayout()

        preset_group = QGroupBox("Preset")
        preset_layout = QFormLayout(preset_group)
        self._preset_combo = QComboBox()
        if HAS_PRESETS:
            self._preset_combo.addItems(list_presets())
        self._preset_combo.currentTextChanged.connect(self._on_preset_changed)
        preset_layout.addRow("Type:", self._preset_combo)

        self._sheet_size_combo = QComboBox()
        self._sheet_size_combo.addItems(["ARCH_A (9x12)", "ARCH_B (12x18)", "ARCH_C (18x24)", "ARCH_D (24x36)", "ARCH_E (36x48)"])
        self._sheet_size_combo.setCurrentText("ARCH_D (24x36)")
        self._sheet_size_combo.currentTextChanged.connect(self._on_sheet_size_changed)
        preset_layout.addRow("Sheet Size:", self._sheet_size_combo)
        top_row.addWidget(preset_group)

        info_group = QGroupBox("Sheet Info")
        info_layout = QFormLayout(info_group)
        self._title_edit = QLineEdit()
        info_layout.addRow("Title:", self._title_edit)
        self._number_edit = QLineEdit()
        self._number_edit.setPlaceholderText("A-101")
        info_layout.addRow("Number:", self._number_edit)
        self._scale_combo = QComboBox()
        self._scale_combo.addItems(["1:10", "1:20", "1:25", "1:50", "1:75", "1:100", "1:200", "1:500"])
        self._scale_combo.setCurrentText("1:100")
        info_layout.addRow("Scale:", self._scale_combo)
        top_row.addWidget(info_group)
        layout.addLayout(top_row)

        # Preview and viewport config
        content_layout = QHBoxLayout()
        preview_group = QGroupBox("Layout Preview")
        preview_layout = QVBoxLayout(preview_group)
        self._preview = ViewportPreviewWidget()
        self._preview.setMinimumSize(400, 280)
        self._preview.viewport_selected.connect(self._on_viewport_selected)
        preview_layout.addWidget(self._preview)
        content_layout.addWidget(preview_group, 2)

        config_group = QGroupBox("Viewport Configuration")
        config_layout = QVBoxLayout(config_group)
        self._viewport_list = QTreeWidget()
        self._viewport_list.setHeaderLabels(["Viewport", "Content"])
        self._viewport_list.setIndentation(0)
        self._viewport_list.itemClicked.connect(self._on_viewport_list_clicked)
        config_layout.addWidget(self._viewport_list)

        content_selector = QFormLayout()
        self._content_type_combo = QComboBox()
        if HAS_PRESETS:
            for dt in DrawingType:
                self._content_type_combo.addItem(dt.name.replace("_", " ").title(), dt)
        self._content_type_combo.currentIndexChanged.connect(self._on_content_type_changed)
        content_selector.addRow("Drawing Type:", self._content_type_combo)
        config_layout.addLayout(content_selector)
        content_layout.addWidget(config_group, 1)
        layout.addLayout(content_layout)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_preset_changed(self, preset_name):
        if not HAS_PRESETS or not preset_name:
            return
        try:
            self._preset = get_preset(preset_name, self._sheet_width, self._sheet_height)
            self._title_edit.setText(self._preset.name)
            self._update_preview()
            self._update_viewport_list()
        except Exception as e:
            print(f"Error loading preset: {e}")

    def _on_sheet_size_changed(self, size_text):
        if not HAS_PRESETS:
            return
        size_name = size_text.split(" ")[0]
        try:
            sheet_size = get_sheet_size(size_name)
            self._sheet_width = sheet_size.width_pt
            self._sheet_height = sheet_size.height_pt
            preset_name = self._preset_combo.currentText()
            if preset_name:
                self._preset = get_preset(preset_name, self._sheet_width, self._sheet_height)
                self._update_preview()
                self._update_viewport_list()
        except Exception as e:
            print(f"Error changing sheet size: {e}")

    def _update_preview(self):
        if self._preset:
            self._preview.set_preset(self._preset, self._sheet_width, self._sheet_height)

    def _update_viewport_list(self):
        self._viewport_list.clear()
        if not self._preset:
            return
        for vc in self._preset.viewports:
            item = QTreeWidgetItem([vc.viewport.title or vc.viewport.id, vc.content.drawing_type.name.replace("_", " ").title()])
            item.setData(0, Qt.ItemDataRole.UserRole, vc.viewport.id)
            self._viewport_list.addTopLevelItem(item)
        self._viewport_list.resizeColumnToContents(0)

    def _on_viewport_selected(self, viewport_id):
        for i in range(self._viewport_list.topLevelItemCount()):
            item = self._viewport_list.topLevelItem(i)
            if item.data(0, Qt.ItemDataRole.UserRole) == viewport_id:
                self._viewport_list.setCurrentItem(item)
                self._update_content_combo_for_viewport(viewport_id)
                break

    def _on_viewport_list_clicked(self, item, column):
        viewport_id = item.data(0, Qt.ItemDataRole.UserRole)
        if viewport_id:
            self._preview.select_viewport(viewport_id)
            self._update_content_combo_for_viewport(viewport_id)

    def _update_content_combo_for_viewport(self, viewport_id):
        if not self._preset:
            return
        vc = self._preset.get_viewport(viewport_id)
        if vc:
            for i in range(self._content_type_combo.count()):
                if self._content_type_combo.itemData(i) == vc.content.drawing_type:
                    self._content_type_combo.setCurrentIndex(i)
                    break

    def _on_content_type_changed(self, index):
        if not self._preset or not HAS_PRESETS:
            return
        current_item = self._viewport_list.currentItem()
        if not current_item:
            return
        viewport_id = current_item.data(0, Qt.ItemDataRole.UserRole)
        drawing_type = self._content_type_combo.itemData(index)
        if viewport_id and drawing_type:
            new_content = ViewportContent(drawing_type=drawing_type)
            self._preset.set_content(viewport_id, new_content)
            current_item.setText(1, drawing_type.name.replace("_", " ").title())
            self._update_preview()

    def get_preset(self):
        return self._preset

    def get_sheet_info(self):
        return {
            "title": self._title_edit.text() or (self._preset.name if self._preset else "Untitled"),
            "number": self._number_edit.text() or "A-001",
            "scale": self._scale_combo.currentText(),
            "sheet_size": self._sheet_size_combo.currentText().split(" ")[0],
        }


# ============================================================================
# Viewport Preview Widget
# ============================================================================

class ViewportPreviewWidget(QWidget):
    """Widget showing a visual preview of sheet layout with clickable viewports."""
    viewport_selected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._preset = None
        self._sheet_width = 1296
        self._sheet_height = 864
        self._selected_viewport = None
        self._viewport_rects = {}
        self.setMouseTracking(True)

    def set_preset(self, preset, sheet_width, sheet_height):
        self._preset = preset
        self._sheet_width = sheet_width
        self._sheet_height = sheet_height
        self._calculate_rects()
        self.update()

    def select_viewport(self, viewport_id):
        self._selected_viewport = viewport_id
        self.update()

    def _calculate_rects(self):
        self._viewport_rects.clear()
        if not self._preset:
            return
        widget_w = self.width() - 20
        widget_h = self.height() - 20
        if widget_w <= 0 or widget_h <= 0:
            return
        scale_x = widget_w / self._sheet_width
        scale_y = widget_h / self._sheet_height
        scale = min(scale_x, scale_y)
        sheet_w = self._sheet_width * scale
        sheet_h = self._sheet_height * scale
        offset_x = (self.width() - sheet_w) / 2
        offset_y = (self.height() - sheet_h) / 2
        for vc in self._preset.viewports:
            vp = vc.viewport
            rect = QRectF(offset_x + vp.x * scale, offset_y + vp.y * scale, vp.width * scale, vp.height * scale)
            self._viewport_rects[vp.id] = rect

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(240, 240, 240))
        if not self._preset:
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No preset selected")
            return
        widget_w = self.width() - 20
        widget_h = self.height() - 20
        if widget_w <= 0 or widget_h <= 0:
            return
        scale_x = widget_w / self._sheet_width
        scale_y = widget_h / self._sheet_height
        scale = min(scale_x, scale_y)
        sheet_w = self._sheet_width * scale
        sheet_h = self._sheet_height * scale
        offset_x = (self.width() - sheet_w) / 2
        offset_y = (self.height() - sheet_h) / 2
        sheet_rect = QRectF(offset_x, offset_y, sheet_w, sheet_h)
        painter.fillRect(sheet_rect, QColor(255, 255, 255))
        painter.setPen(QPen(QColor(0, 0, 0), 2))
        painter.drawRect(sheet_rect)
        # Title block
        title_height = 72 * scale
        title_rect = QRectF(offset_x, offset_y + sheet_h - title_height, sheet_w, title_height)
        painter.fillRect(title_rect, QColor(245, 245, 245))
        painter.setPen(QPen(QColor(100, 100, 100), 1))
        painter.drawRect(title_rect)
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignCenter, "TITLE BLOCK")
        # Draw viewports
        for viewport_id, rect in self._viewport_rects.items():
            vc = self._preset.get_viewport(viewport_id)
            if not vc:
                continue
            if viewport_id == self._selected_viewport:
                fill_color, border_color, border_width = QColor(200, 220, 255), QColor(0, 100, 200), 2
            else:
                fill_color, border_color, border_width = QColor(250, 250, 250), QColor(150, 150, 150), 1
            painter.fillRect(rect, fill_color)
            painter.setPen(QPen(border_color, border_width))
            painter.drawRect(rect)
            label = vc.viewport.title or vc.content.drawing_type.name.replace("_", " ")
            painter.setPen(QColor(50, 50, 50))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._calculate_rects()

    def mousePressEvent(self, event):
        for viewport_id, rect in self._viewport_rects.items():
            if rect.contains(event.position()):
                self._selected_viewport = viewport_id
                self.viewport_selected.emit(viewport_id)
                self.update()
                break


class SheetManagerPanel(QWidget):
    """
    Panel for managing drawing sheets.

    Shows sheets in a tree organized by category, with controls for
    regeneration, adding sheets, and changing settings.
    """

    # Signals
    sheet_selected = pyqtSignal(str)           # sheet_id
    sheet_double_clicked = pyqtSignal(str)     # sheet_id (opens in tab)
    regenerate_requested = pyqtSignal(str)     # sheet_id (empty = all)
    preset_sheet_created = pyqtSignal(object)  # SheetPreset

    def __init__(self, registry: SheetRegistry, parent=None):
        super().__init__(parent)
        self._registry = registry
        self._category_items: Dict[str, QTreeWidgetItem] = {}
        self._sheet_items: Dict[str, QTreeWidgetItem] = {}

        self._setup_ui()
        self._connect_signals()
        self._refresh_tree()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Header with title and buttons
        header = QHBoxLayout()
        header.setSpacing(4)

        title = QLabel("Sheets")
        title.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        header.addWidget(title)

        header.addStretch()

        # Regenerate all button
        self._regen_btn = QToolButton()
        self._regen_btn.setText("âŸ³")
        self._regen_btn.setToolTip("Regenerate All Sheets")
        self._regen_btn.clicked.connect(lambda: self.regenerate_requested.emit(""))
        header.addWidget(self._regen_btn)

        # Add sheet button
        self._add_btn = QToolButton()
        self._add_btn.setText("+")
        self._add_btn.setToolTip("Add Sheet")
        self._add_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._add_btn.setMenu(self._create_add_menu())
        header.addWidget(self._add_btn)

        layout.addLayout(header)

        # Prefix input
        prefix_layout = QHBoxLayout()
        prefix_layout.setSpacing(4)
        prefix_label = QLabel("Prefix:")
        prefix_label.setStyleSheet("color: #666; font-size: 11px;")
        prefix_layout.addWidget(prefix_label)

        self._prefix_edit = QLineEdit(self._registry.prefix)
        self._prefix_edit.setMaximumWidth(60)
        self._prefix_edit.setPlaceholderText("A-")
        self._prefix_edit.editingFinished.connect(self._on_prefix_changed)
        prefix_layout.addWidget(self._prefix_edit)

        prefix_layout.addStretch()

        layout.addLayout(prefix_layout)

        # Tree widget
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setIndentation(16)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._show_context_menu)
        self._tree.itemClicked.connect(self._on_item_clicked)
        self._tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self._tree)

        # Progress bar (hidden by default)
        self._progress = QProgressBar()
        self._progress.setMaximumHeight(16)
        self._progress.hide()
        layout.addWidget(self._progress)

        # Auto-regenerate toggle
        auto_layout = QHBoxLayout()
        auto_layout.setSpacing(4)

        self._auto_check = QCheckBox("Auto-regenerate")
        self._auto_check.setChecked(self._registry.auto_regenerate)
        self._auto_check.setStyleSheet("font-size: 11px; color: #666;")
        self._auto_check.toggled.connect(self._on_auto_toggled)
        auto_layout.addWidget(self._auto_check)

        auto_layout.addStretch()

        layout.addLayout(auto_layout)

    def _create_add_menu(self) -> QMenu:
        """Create the add sheet menu with preset options."""
        menu = QMenu(self)

        # Preset sheets section (if available)
        if HAS_PRESETS:
            menu.addAction("From Preset...", self._show_preset_dialog)
            menu.addSeparator()

        for sheet_type in SheetType:
            defaults = SHEET_DEFAULTS.get(sheet_type, {})
            title = defaults.get('title', sheet_type.value)
            action = menu.addAction(title)
            action.setData(sheet_type)
            action.triggered.connect(lambda checked, st=sheet_type: self._add_sheet(st))

        return menu

    def _show_preset_dialog(self):
        """Show the preset sheet creation dialog."""
        if not HAS_PRESETS:
            return

        dialog = PresetSheetDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            preset = dialog.get_preset()
            sheet_info = dialog.get_sheet_info()

            if preset:
                # Emit signal with preset for external handling
                self.preset_sheet_created.emit({
                    'preset': preset,
                    'info': sheet_info
                })

    def _connect_signals(self):
        """Connect registry signals."""
        self._registry.sheet_added.connect(self._on_sheet_added)
        self._registry.sheet_removed.connect(self._on_sheet_removed)
        self._registry.sheet_updated.connect(self._on_sheet_updated)
        self._registry.sheet_content_changed.connect(self._on_sheet_content_changed)
        self._registry.drawing_set_loaded.connect(self._refresh_tree)
        self._registry.prefix_changed.connect(self._on_prefix_changed_external)

    def _refresh_tree(self):
        """Rebuild the entire tree."""
        self._tree.clear()
        self._category_items.clear()
        self._sheet_items.clear()

        # Get categories
        categories = self._registry.get_categories()

        for category in categories:
            # Create category item
            cat_item = QTreeWidgetItem([category])
            cat_item.setFlags(cat_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            font = cat_item.font(0)
            font.setBold(True)
            cat_item.setFont(0, font)
            self._tree.addTopLevelItem(cat_item)
            self._category_items[category] = cat_item

            # Add sheets in category
            sheets = self._registry.get_sheets_by_category(category)
            for sheet in sheets:
                self._add_sheet_item(cat_item, sheet)

            cat_item.setExpanded(True)

    def _add_sheet_item(self, parent: QTreeWidgetItem, sheet: SheetConfig):
        """Add a sheet item to the tree."""
        text = f"{sheet.number} - {sheet.title}"
        item = QTreeWidgetItem([text])
        item.setData(0, Qt.ItemDataRole.UserRole, sheet.id)

        # Set status indicator
        if not sheet.enabled:
            item.setForeground(0, Qt.GlobalColor.gray)
        elif sheet.has_content:
            item.setForeground(0, Qt.GlobalColor.darkGreen)
        else:
            item.setForeground(0, Qt.GlobalColor.darkRed)

        parent.addChild(item)
        self._sheet_items[sheet.id] = item

    def _update_sheet_item(self, sheet_id: str):
        """Update a sheet item in the tree."""
        item = self._sheet_items.get(sheet_id)
        sheet = self._registry.get_sheet(sheet_id)

        if item and sheet:
            text = f"{sheet.number} - {sheet.title}"
            item.setText(0, text)

            # Update status indicator
            if not sheet.enabled:
                item.setForeground(0, Qt.GlobalColor.gray)
            elif sheet.has_content:
                item.setForeground(0, Qt.GlobalColor.darkGreen)
            else:
                item.setForeground(0, Qt.GlobalColor.darkRed)

    # =========================================================================
    # Event Handlers
    # =========================================================================

    def _on_item_clicked(self, item: QTreeWidgetItem, column: int):
        """Handle item click."""
        sheet_id = item.data(0, Qt.ItemDataRole.UserRole)
        if sheet_id:
            self.sheet_selected.emit(sheet_id)

    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int):
        """Handle item double-click."""
        sheet_id = item.data(0, Qt.ItemDataRole.UserRole)
        if sheet_id:
            self.sheet_double_clicked.emit(sheet_id)

    def _show_context_menu(self, pos):
        """Show context menu for items."""
        item = self._tree.itemAt(pos)
        if not item:
            return

        sheet_id = item.data(0, Qt.ItemDataRole.UserRole)
        if not sheet_id:
            return

        sheet = self._registry.get_sheet(sheet_id)
        if not sheet:
            return

        menu = QMenu(self)

        # Open in tab
        open_action = menu.addAction("Open in Tab")
        open_action.triggered.connect(lambda: self.sheet_double_clicked.emit(sheet_id))

        menu.addSeparator()

        # Regenerate
        regen_action = menu.addAction("Regenerate")
        regen_action.triggered.connect(lambda: self.regenerate_requested.emit(sheet_id))

        menu.addSeparator()

        # Enable/disable
        if sheet.enabled:
            disable_action = menu.addAction("Disable Auto-Regenerate")
            disable_action.triggered.connect(
                lambda: self._registry.update_sheet(sheet_id, enabled=False)
            )
        else:
            enable_action = menu.addAction("Enable Auto-Regenerate")
            enable_action.triggered.connect(
                lambda: self._registry.update_sheet(sheet_id, enabled=True)
            )

        menu.addSeparator()

        # Remove
        remove_action = menu.addAction("Remove Sheet")
        remove_action.triggered.connect(lambda: self._registry.remove_sheet(sheet_id))

        menu.exec(self._tree.mapToGlobal(pos))

    def _add_sheet(self, sheet_type: SheetType):
        """Add a new sheet."""
        self._registry.add_sheet(sheet_type)

    def _on_prefix_changed(self):
        """Handle prefix change from input."""
        new_prefix = self._prefix_edit.text().strip()
        if new_prefix and new_prefix != self._registry.prefix:
            self._registry.prefix = new_prefix

    def _on_prefix_changed_external(self, new_prefix: str):
        """Handle prefix changed externally."""
        self._prefix_edit.setText(new_prefix)
        self._refresh_tree()

    def _on_auto_toggled(self, checked: bool):
        """Handle auto-regenerate toggle."""
        self._registry.auto_regenerate = checked

    def _on_sheet_added(self, sheet_id: str):
        """Handle sheet added."""
        sheet = self._registry.get_sheet(sheet_id)
        if not sheet:
            return

        category = sheet.category
        cat_item = self._category_items.get(category)

        if not cat_item:
            # Create category item
            cat_item = QTreeWidgetItem([category])
            cat_item.setFlags(cat_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            font = cat_item.font(0)
            font.setBold(True)
            cat_item.setFont(0, font)
            self._tree.addTopLevelItem(cat_item)
            self._category_items[category] = cat_item
            cat_item.setExpanded(True)

        self._add_sheet_item(cat_item, sheet)

    def _on_sheet_removed(self, sheet_id: str):
        """Handle sheet removed."""
        item = self._sheet_items.pop(sheet_id, None)
        if item:
            parent = item.parent()
            if parent:
                parent.removeChild(item)
                # Remove empty category
                if parent.childCount() == 0:
                    index = self._tree.indexOfTopLevelItem(parent)
                    if index >= 0:
                        self._tree.takeTopLevelItem(index)
                        # Find and remove from category items
                        for cat, cat_item in list(self._category_items.items()):
                            if cat_item is parent:
                                del self._category_items[cat]
                                break

    def _on_sheet_updated(self, sheet_id: str):
        """Handle sheet updated."""
        self._update_sheet_item(sheet_id)

    def _on_sheet_content_changed(self, sheet_id: str):
        """Handle sheet content changed."""
        self._update_sheet_item(sheet_id)

    # =========================================================================
    # Progress
    # =========================================================================

    def show_progress(self, current: int, total: int):
        """Show generation progress."""
        if total > 0:
            self._progress.setMaximum(total)
            self._progress.setValue(current)
            self._progress.show()
        else:
            self._progress.hide()

    def hide_progress(self):
        """Hide progress bar."""
        self._progress.hide()
