"""
Sheet Properties Panel - Edit sheet configuration.

Provides controls for editing individual sheet properties like
title, number, scale, and revision.
"""
from typing import Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QComboBox, QCheckBox, QPushButton,
    QGroupBox, QTextEdit, QSpinBox, QScrollArea, QFrame
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from sheets.models import SheetConfig, SheetType, TitleBlockInfo
from sheets.sheet_registry import SheetRegistry


class SheetPropertiesPanel(QWidget):
    """
    Panel for editing sheet properties.

    Shows and allows editing of the selected sheet's configuration.
    """

    # Signals
    regenerate_requested = pyqtSignal(str)  # sheet_id
    text_sizes_changed = pyqtSignal(dict)   # {dim_text_size, room_text_size, room_area_size}
    dimension_settings_changed = pyqtSignal(dict)  # dimension_settings dict

    def __init__(self, registry: SheetRegistry, parent=None):
        super().__init__(parent)
        self._registry = registry
        self._current_sheet_id: Optional[str] = None
        self._updating = False  # Prevent signal loops

        self._setup_ui()
        self._connect_signals()
        self._clear()

    def _setup_ui(self):
        # Main layout with scroll area
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # Content widget inside scroll area
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(12)

        # Header
        header = QLabel("Sheet Properties")
        header.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        layout.addWidget(header)

        # Sheet info group
        sheet_group = QGroupBox("Sheet")
        sheet_layout = QFormLayout(sheet_group)
        sheet_layout.setSpacing(6)

        self._title_edit = QLineEdit()
        self._title_edit.editingFinished.connect(self._on_title_changed)
        sheet_layout.addRow("Title:", self._title_edit)

        self._number_edit = QLineEdit()
        self._number_edit.editingFinished.connect(self._on_number_changed)
        sheet_layout.addRow("Number:", self._number_edit)

        self._scale_combo = QComboBox()
        self._scale_combo.addItems([
            "1:10", "1:20", "1:25", "1:50", "1:75",
            "1:100", "1:125", "1:150", "1:200", "1:250", "1:500"
        ])
        self._scale_combo.setEditable(True)
        self._scale_combo.currentTextChanged.connect(self._on_scale_changed)
        sheet_layout.addRow("Scale:", self._scale_combo)

        self._revision_edit = QLineEdit()
        self._revision_edit.setMaxLength(3)
        self._revision_edit.setMaximumWidth(50)
        self._revision_edit.editingFinished.connect(self._on_revision_changed)
        sheet_layout.addRow("Revision:", self._revision_edit)

        self._enabled_check = QCheckBox("Auto-regenerate")
        self._enabled_check.toggled.connect(self._on_enabled_changed)
        sheet_layout.addRow("", self._enabled_check)

        layout.addWidget(sheet_group)

        # Status group
        status_group = QGroupBox("Status")
        status_layout = QVBoxLayout(status_group)

        self._status_label = QLabel()
        self._status_label.setWordWrap(True)
        self._status_label.setStyleSheet("color: #666;")
        status_layout.addWidget(self._status_label)

        # Regenerate button
        self._regen_btn = QPushButton("Regenerate Now")
        self._regen_btn.clicked.connect(self._on_regenerate)
        status_layout.addWidget(self._regen_btn)

        layout.addWidget(status_group)

        # Text sizes group
        text_group = QGroupBox("Text Sizes")
        text_layout = QFormLayout(text_group)
        text_layout.setSpacing(6)

        self._dim_text_spin = QSpinBox()
        self._dim_text_spin.setRange(100, 800)
        self._dim_text_spin.setValue(300)
        self._dim_text_spin.setSingleStep(25)
        self._dim_text_spin.valueChanged.connect(self._on_text_size_changed)
        text_layout.addRow("Dimensions:", self._dim_text_spin)

        self._room_text_spin = QSpinBox()
        self._room_text_spin.setRange(100, 800)
        self._room_text_spin.setValue(500)
        self._room_text_spin.setSingleStep(25)
        self._room_text_spin.valueChanged.connect(self._on_text_size_changed)
        text_layout.addRow("Room Labels:", self._room_text_spin)

        self._area_text_spin = QSpinBox()
        self._area_text_spin.setRange(100, 600)
        self._area_text_spin.setValue(350)
        self._area_text_spin.setSingleStep(25)
        self._area_text_spin.valueChanged.connect(self._on_text_size_changed)
        text_layout.addRow("Room Areas:", self._area_text_spin)

        layout.addWidget(text_group)

        # Dimension settings group
        dim_group = QGroupBox("Dimension Settings")
        dim_layout = QFormLayout(dim_group)
        dim_layout.setSpacing(6)

        # Auto-dimension checkboxes
        self._auto_exterior_check = QCheckBox("Exterior walls")
        self._auto_exterior_check.setChecked(True)
        self._auto_exterior_check.toggled.connect(self._on_dimension_settings_changed)
        dim_layout.addRow("Auto-dim:", self._auto_exterior_check)

        self._auto_openings_check = QCheckBox("Openings (doors/windows)")
        self._auto_openings_check.setChecked(True)
        self._auto_openings_check.toggled.connect(self._on_dimension_settings_changed)
        dim_layout.addRow("", self._auto_openings_check)

        self._auto_rooms_check = QCheckBox("Room dimensions")
        self._auto_rooms_check.setChecked(True)
        self._auto_rooms_check.toggled.connect(self._on_dimension_settings_changed)
        dim_layout.addRow("", self._auto_rooms_check)

        # Display format dropdown
        self._display_format_combo = QComboBox()
        self._display_format_combo.addItems(["Metric (mm)", "Imperial (ft-in)"])
        self._display_format_combo.currentIndexChanged.connect(self._on_dimension_settings_changed)
        dim_layout.addRow("Format:", self._display_format_combo)

        # Dimension offset from wall
        self._dim_offset_spin = QSpinBox()
        self._dim_offset_spin.setRange(200, 1500)
        self._dim_offset_spin.setValue(600)
        self._dim_offset_spin.setSingleStep(50)
        self._dim_offset_spin.setSuffix(" mm")
        self._dim_offset_spin.valueChanged.connect(self._on_dimension_settings_changed)
        dim_layout.addRow("Offset:", self._dim_offset_spin)

        layout.addWidget(dim_group)

        # Title block group
        title_block_group = QGroupBox("Title Block")
        tb_layout = QFormLayout(title_block_group)
        tb_layout.setSpacing(6)

        self._project_name_edit = QLineEdit()
        self._project_name_edit.editingFinished.connect(self._on_title_block_changed)
        tb_layout.addRow("Project:", self._project_name_edit)

        self._project_number_edit = QLineEdit()
        self._project_number_edit.editingFinished.connect(self._on_title_block_changed)
        tb_layout.addRow("Project #:", self._project_number_edit)

        self._client_edit = QLineEdit()
        self._client_edit.editingFinished.connect(self._on_title_block_changed)
        tb_layout.addRow("Client:", self._client_edit)

        self._architect_edit = QLineEdit()
        self._architect_edit.editingFinished.connect(self._on_title_block_changed)
        tb_layout.addRow("Architect:", self._architect_edit)

        layout.addWidget(title_block_group)

        layout.addStretch()

        # Complete scroll area setup
        scroll.setWidget(content)
        main_layout.addWidget(scroll)

    def _connect_signals(self):
        """Connect registry signals."""
        self._registry.sheet_updated.connect(self._on_sheet_updated)
        self._registry.sheet_content_changed.connect(self._on_sheet_updated)

    # =========================================================================
    # Public API
    # =========================================================================

    def set_sheet(self, sheet_id: Optional[str]):
        """
        Set the sheet to display properties for.

        Args:
            sheet_id: Sheet ID, or None to clear
        """
        self._current_sheet_id = sheet_id

        if sheet_id:
            sheet = self._registry.get_sheet(sheet_id)
            if sheet:
                self._update_from_sheet(sheet)
                self.setEnabled(True)
                return

        self._clear()

    def _clear(self):
        """Clear all fields."""
        self._updating = True

        self._title_edit.clear()
        self._number_edit.clear()
        self._scale_combo.setCurrentText("1:100")
        self._revision_edit.clear()
        self._enabled_check.setChecked(True)
        self._status_label.setText("No sheet selected")

        # Clear title block
        self._project_name_edit.clear()
        self._project_number_edit.clear()
        self._client_edit.clear()
        self._architect_edit.clear()

        # Clear dimension settings
        self._auto_exterior_check.setChecked(True)
        self._auto_openings_check.setChecked(True)
        self._auto_rooms_check.setChecked(True)
        self._display_format_combo.setCurrentIndex(0)
        self._dim_offset_spin.setValue(600)

        self._updating = False
        self.setEnabled(False)

    def _update_from_sheet(self, sheet: SheetConfig):
        """Update fields from sheet."""
        self._updating = True

        self._title_edit.setText(sheet.title)
        self._number_edit.setText(sheet.number)
        self._scale_combo.setCurrentText(sheet.scale)
        self._revision_edit.setText(sheet.revision)
        self._enabled_check.setChecked(sheet.enabled)

        # Status
        status_lines = [f"Type: {sheet.sheet_type.value}"]
        if sheet.has_content:
            status_lines.append("Content: Generated")
            if sheet.last_generated:
                status_lines.append(f"Last: {sheet.last_generated.strftime('%Y-%m-%d %H:%M')}")
        else:
            status_lines.append("Content: Not generated")

        self._status_label.setText("\n".join(status_lines))

        # Title block
        tb = self._registry.title_block
        self._project_name_edit.setText(tb.project_name)
        self._project_number_edit.setText(tb.project_number)
        self._client_edit.setText(tb.client_name)
        self._architect_edit.setText(tb.architect_name)

        self._updating = False

    # =========================================================================
    # Event Handlers
    # =========================================================================

    def _on_title_changed(self):
        if self._updating or not self._current_sheet_id:
            return
        self._registry.update_sheet(self._current_sheet_id, title=self._title_edit.text())

    def _on_number_changed(self):
        if self._updating or not self._current_sheet_id:
            return
        self._registry.renumber_sheet(self._current_sheet_id, self._number_edit.text())

    def _on_scale_changed(self, scale: str):
        if self._updating or not self._current_sheet_id:
            return
        self._registry.update_sheet(self._current_sheet_id, scale=scale)

    def _on_revision_changed(self):
        if self._updating or not self._current_sheet_id:
            return
        self._registry.update_sheet(self._current_sheet_id, revision=self._revision_edit.text())

    def _on_enabled_changed(self, enabled: bool):
        if self._updating or not self._current_sheet_id:
            return
        self._registry.update_sheet(self._current_sheet_id, enabled=enabled)

    def _on_regenerate(self):
        if self._current_sheet_id:
            self.regenerate_requested.emit(self._current_sheet_id)

    def _on_title_block_changed(self):
        if self._updating:
            return

        tb = TitleBlockInfo(
            project_name=self._project_name_edit.text(),
            project_number=self._project_number_edit.text(),
            client_name=self._client_edit.text(),
            architect_name=self._architect_edit.text(),
        )
        self._registry.title_block = tb

    def _on_sheet_updated(self, sheet_id: str):
        if sheet_id == self._current_sheet_id:
            sheet = self._registry.get_sheet(sheet_id)
            if sheet:
                self._update_from_sheet(sheet)

    def _on_text_size_changed(self):
        if self._updating:
            return

        sizes = {
            'dim_text_size': self._dim_text_spin.value(),
            'room_text_size': self._room_text_spin.value(),
            'room_area_size': self._area_text_spin.value(),
        }
        self._registry.text_sizes = sizes
        self.text_sizes_changed.emit(sizes)

    def get_text_sizes(self) -> dict:
        """Get current text size settings."""
        return {
            'dim_text_size': self._dim_text_spin.value(),
            'room_text_size': self._room_text_spin.value(),
            'room_area_size': self._area_text_spin.value(),
        }

    def set_text_sizes(self, sizes: dict):
        """Set text size values from a dictionary."""
        self._updating = True
        if 'dim_text_size' in sizes:
            self._dim_text_spin.setValue(sizes['dim_text_size'])
        if 'room_text_size' in sizes:
            self._room_text_spin.setValue(sizes['room_text_size'])
        if 'room_area_size' in sizes:
            self._area_text_spin.setValue(sizes['room_area_size'])
        self._updating = False

    def _on_dimension_settings_changed(self):
        """Handle changes to dimension settings."""
        if self._updating:
            return

        settings = self.get_dimension_settings()
        self._registry.dimension_settings = settings
        self.dimension_settings_changed.emit(settings)

    def get_dimension_settings(self) -> dict:
        """Get current dimension settings."""
        display_format = 'metric' if self._display_format_combo.currentIndex() == 0 else 'imperial'
        return {
            'auto_exterior_walls': self._auto_exterior_check.isChecked(),
            'auto_openings': self._auto_openings_check.isChecked(),
            'auto_rooms': self._auto_rooms_check.isChecked(),
            'auto_heights': True,  # Default, no UI yet
            'unit': 'mm',
            'display_format': display_format,
            'text_size': self._dim_text_spin.value(),
            'line_width': 3,
            'tick_length': 150,
            'offset_from_wall': self._dim_offset_spin.value(),
            'chain_spacing': 400,
        }

    def set_dimension_settings(self, settings: dict):
        """Set dimension settings from a dictionary."""
        self._updating = True
        if 'auto_exterior_walls' in settings:
            self._auto_exterior_check.setChecked(settings['auto_exterior_walls'])
        if 'auto_openings' in settings:
            self._auto_openings_check.setChecked(settings['auto_openings'])
        if 'auto_rooms' in settings:
            self._auto_rooms_check.setChecked(settings['auto_rooms'])
        if 'display_format' in settings:
            self._display_format_combo.setCurrentIndex(
                0 if settings['display_format'] == 'metric' else 1
            )
        if 'offset_from_wall' in settings:
            self._dim_offset_spin.setValue(settings['offset_from_wall'])
        self._updating = False
