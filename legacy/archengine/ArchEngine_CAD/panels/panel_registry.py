"""
Panel Registry - Defines all smart panels and their visibility conditions.

Each panel is defined with:
- ID and name
- Widget class to instantiate
- Visibility conditions (workflow, LOD, gravity, selection, etc.)
"""
from typing import List

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QGroupBox
)
from PyQt6.QtCore import Qt, pyqtSignal

from panels.smart_panels import (
    PanelDefinition, PanelConditions, GravityCondition,
    SelectionCondition, StateCondition, TaskCondition,
    WorkflowStage, SchemaState, TaskType, ElementType, LODLevel
)


# =============================================================================
# Placeholder Panel Widgets
# =============================================================================

class PlaceholderPanel(QWidget):
    """Base placeholder panel for development."""

    def __init__(self, title: str, description: str, color: str = "#4a4a55", parent=None):
        super().__init__(parent)
        self._setup_ui(title, description, color)

    def _setup_ui(self, title: str, description: str, color: str):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        # Title
        title_label = QLabel(title)
        title_label.setStyleSheet(f"font-weight: bold; color: {color}; font-size: 11px;")
        layout.addWidget(title_label)

        # Description
        desc_label = QLabel(description)
        desc_label.setStyleSheet("color: #888; font-size: 10px;")
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)

        # Placeholder content
        placeholder = QLabel("[Panel Content]")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setStyleSheet(
            f"background: {color}22; border: 1px dashed {color}; "
            "border-radius: 4px; padding: 20px; color: #666;"
        )
        layout.addWidget(placeholder)

        layout.addStretch()


class RoomTypeButton(QPushButton):
    """Draggable room type button for the blob palette."""
    room_type_selected = pyqtSignal(str, str)  # room_type, name

    ROOM_TYPES = {
        "entrance": ("Entrance", "#FF6B6B"),  # Anchor entrance with front door
        "porch": ("Porch", "#4ECDC4"),         # Front porch
        "living": ("Living Room", "#7CB9E8"),
        "bedroom": ("Bedroom", "#9370DB"),
        "bathroom": ("Bathroom", "#5DADE2"),
        "kitchen": ("Kitchen", "#F5B041"),
        "dining": ("Dining Room", "#58D68D"),
        "office": ("Office", "#AF7AC5"),
        "garage": ("Garage", "#95A5A6"),
        "hallway": ("Hallway", "#D5DBDB"),
        "closet": ("Closet", "#BFC9CA"),
        "laundry": ("Laundry", "#85C1E9"),
        "entry": ("Entry", "#EDBB99"),
        "utility": ("Utility", "#A9A9A9"),
    }

    def __init__(self, room_type: str, parent=None):
        name, color = self.ROOM_TYPES.get(room_type, (room_type.title(), "#888888"))
        super().__init__(name, parent)
        self._room_type = room_type
        self._name = name
        self._color = color
        self._drag_start_pos = None

        self.setFixedSize(80, 50)
        self.setStyleSheet(f"""
            QPushButton {{
                background: {color}44;
                border: 2px solid {color};
                border-radius: 6px;
                color: white;
                font-size: 9px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: {color}88;
                border-color: white;
            }}
            QPushButton:pressed {{
                background: {color}CC;
            }}
        """)
        self.setToolTip(f"Drag to add {name}")
        self.clicked.connect(self._on_clicked)

    def _on_clicked(self):
        self.room_type_selected.emit(self._room_type, self._name)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_start_pos is None:
            return
        # Check if moved enough to start drag
        if (event.pos() - self._drag_start_pos).manhattanLength() < 10:
            return

        # Start drag
        from PyQt6.QtGui import QDrag
        from PyQt6.QtCore import QMimeData

        drag = QDrag(self)
        mime_data = QMimeData()
        mime_data.setText(f"room:{self._room_type}:{self._name}:{self._color}")
        drag.setMimeData(mime_data)

        # Execute drag
        drag.exec(Qt.DropAction.CopyAction)
        self._drag_start_pos = None

    def mouseReleaseEvent(self, event):
        self._drag_start_pos = None
        super().mouseReleaseEvent(event)


class BlobPalettePanel(QWidget):
    """Room/blob palette for LegiQBD - shows room types to add to the design."""
    room_type_selected = pyqtSignal(str, str)  # room_type, name

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        from PyQt6.QtWidgets import QGridLayout

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Title
        title = QLabel("Room Types")
        title.setStyleSheet("font-weight: bold; color: #6495ED; font-size: 11px;")
        layout.addWidget(title)

        # Description
        desc = QLabel("Click a room type to add it to your design")
        desc.setStyleSheet("color: #888; font-size: 10px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # Grid of room type buttons
        grid = QGridLayout()
        grid.setSpacing(6)

        room_types = list(RoomTypeButton.ROOM_TYPES.keys())
        for i, room_type in enumerate(room_types):
            btn = RoomTypeButton(room_type)
            btn.room_type_selected.connect(self.room_type_selected.emit)
            row = i // 2
            col = i % 2
            grid.addWidget(btn, row, col)

        layout.addLayout(grid)
        layout.addStretch()


class RelationshipToolsPanel(PlaceholderPanel):
    """Relationship editing tools for LegiQBD."""
    def __init__(self, parent=None):
        super().__init__(
            "Relationships",
            "Define how rooms connect",
            "#6495ED",
            parent
        )


class ScorePanel(PlaceholderPanel):
    """Design score/feedback panel."""
    def __init__(self, parent=None):
        super().__init__(
            "Design Score",
            "How well does this meet requirements?",
            "#6495ED",
            parent
        )


class WallToolsPanel(QWidget):
    """Wall editing tools for LegiCAD - shows controls for selected walls."""

    def __init__(self, parent=None):
        super().__init__(parent)
        from core.events import event_bus
        self._selected_walls = []
        self._updating = False
        self._setup_ui()
        event_bus.selection_changed.connect(self._on_selection_changed)

    def _setup_ui(self):
        from PyQt6.QtWidgets import QComboBox, QSpinBox, QCheckBox, QFormLayout

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Category selector
        category_group = QGroupBox("Category")
        category_layout = QVBoxLayout(category_group)
        self._category_combo = QComboBox()
        self._category_combo.addItems(["exterior", "interior", "wet_wall"])
        self._category_combo.currentTextChanged.connect(self._on_category_changed)
        category_layout.addWidget(self._category_combo)
        layout.addWidget(category_group)

        # Wall type selector
        type_group = QGroupBox("Wall Type")
        type_layout = QVBoxLayout(type_group)
        self._type_combo = QComboBox()
        self._type_combo.addItem("(default)", "")
        self._type_combo.currentIndexChanged.connect(self._on_type_changed)
        type_layout.addWidget(self._type_combo)
        layout.addWidget(type_group)

        # Height control
        height_group = QGroupBox("Height")
        height_layout = QFormLayout(height_group)
        self._height_spin = QSpinBox()
        self._height_spin.setRange(1000, 10000)
        self._height_spin.setSingleStep(100)
        self._height_spin.setSuffix(" mm")
        self._height_spin.setValue(2700)
        self._height_spin.valueChanged.connect(self._on_height_changed)
        height_layout.addRow("Height:", self._height_spin)
        layout.addWidget(height_group)

        # Structural binding
        struct_group = QGroupBox("Structure")
        struct_layout = QVBoxLayout(struct_group)
        self._structural_check = QCheckBox("Structural (bound to room)")
        self._structural_check.toggled.connect(self._on_structural_toggled)
        struct_layout.addWidget(self._structural_check)
        self._bound_room_label = QLabel("Room: -")
        self._bound_room_label.setStyleSheet("color: #888; font-size: 10px;")
        struct_layout.addWidget(self._bound_room_label)
        layout.addWidget(struct_group)

        # Pin control
        pin_group = QGroupBox("Constraints")
        pin_layout = QVBoxLayout(pin_group)
        self._pin_check = QCheckBox("Pin wall (prevent modifications)")
        self._pin_check.toggled.connect(self._on_pin_toggled)
        pin_layout.addWidget(self._pin_check)
        layout.addWidget(pin_group)

        # Status label
        self._status_label = QLabel("Select a wall to edit")
        self._status_label.setStyleSheet("color: #888; font-style: italic;")
        layout.addWidget(self._status_label)

        layout.addStretch()

    def _on_selection_changed(self, selected_items):
        """Update panel when selection changes."""
        self._selected_walls = []
        for item in selected_items:
            if type(item).__name__ == "WallItem" and hasattr(item, 'wall'):
                self._selected_walls.append(item)

        self._update_ui()

    def _update_ui(self):
        """Update UI to reflect selected wall(s)."""
        self._updating = True
        try:
            if not self._selected_walls:
                self._status_label.setText("Select a wall to edit")
                self._category_combo.setEnabled(False)
                self._type_combo.setEnabled(False)
                self._height_spin.setEnabled(False)
                self._structural_check.setEnabled(False)
                self._bound_room_label.setText("Room: -")
                self._pin_check.setEnabled(False)
                return

            wall = self._selected_walls[0].wall
            count = len(self._selected_walls)
            self._status_label.setText(f"{count} wall(s) selected")

            self._category_combo.setEnabled(True)
            self._type_combo.setEnabled(True)
            self._height_spin.setEnabled(True)
            self._structural_check.setEnabled(True)
            self._pin_check.setEnabled(True)

            # Set values from first selected wall
            idx = self._category_combo.findText(wall.category)
            if idx >= 0:
                self._category_combo.setCurrentIndex(idx)

            self._height_spin.setValue(int(wall.height))
            self._pin_check.setChecked(wall.is_pinned)

            # Structural binding info
            self._structural_check.setChecked(wall.is_structural)
            if wall.bound_room_id:
                self._bound_room_label.setText(f"Room: {wall.bound_room_id}")
                self._bound_room_label.setStyleSheet("color: #4CAF50; font-size: 10px;")
            else:
                self._bound_room_label.setText("Room: (unbound partition)")
                self._bound_room_label.setStyleSheet("color: #888; font-size: 10px;")
        finally:
            self._updating = False

    def _on_category_changed(self, category: str):
        if self._updating or not self._selected_walls:
            return
        from core.events import event_bus
        for item in self._selected_walls:
            item.wall.category = category
        event_bus.document_modified.emit()

    def _on_type_changed(self, index: int):
        if self._updating or not self._selected_walls:
            return
        from core.events import event_bus
        wall_type = self._type_combo.currentData() or ""
        for item in self._selected_walls:
            item.wall.wall_type = wall_type
        event_bus.document_modified.emit()

    def _on_height_changed(self, height: int):
        if self._updating or not self._selected_walls:
            return
        from core.events import event_bus
        for item in self._selected_walls:
            item.wall.height = height
        event_bus.document_modified.emit()

    def _on_structural_toggled(self, checked: bool):
        if self._updating or not self._selected_walls:
            return
        from core.events import event_bus
        for item in self._selected_walls:
            item.wall.is_structural = checked
            if not checked:
                # Unbind from room when marking as non-structural
                item.wall.bound_room_id = ""
                item.wall.edge_index = -1
        self._update_ui()  # Refresh to show updated binding
        event_bus.document_modified.emit()

    def _on_pin_toggled(self, checked: bool):
        if self._updating or not self._selected_walls:
            return
        from core.events import event_bus
        for item in self._selected_walls:
            item.wall.is_pinned = checked
        event_bus.document_modified.emit()


class OpeningToolsPanel(QWidget):
    """Door/window editing tools - shows controls for selected openings."""

    def __init__(self, parent=None):
        super().__init__(parent)
        from core.events import event_bus
        self._selected_doors = []
        self._selected_windows = []
        self._updating = False
        self._setup_ui()
        event_bus.selection_changed.connect(self._on_selection_changed)

    def _setup_ui(self):
        from PyQt6.QtWidgets import QComboBox, QSpinBox, QCheckBox, QFormLayout, QStackedWidget

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Stacked widget for door/window specific controls
        self._stack = QStackedWidget()

        # Door controls page
        door_page = QWidget()
        door_layout = QVBoxLayout(door_page)
        door_layout.setContentsMargins(0, 0, 0, 0)

        door_type_group = QGroupBox("Door Type")
        door_type_layout = QVBoxLayout(door_type_group)
        self._door_type_combo = QComboBox()
        self._door_type_combo.addItems(["swing", "sliding", "pocket", "bifold", "double"])
        self._door_type_combo.currentTextChanged.connect(self._on_door_type_changed)
        door_type_layout.addWidget(self._door_type_combo)
        door_layout.addWidget(door_type_group)

        swing_group = QGroupBox("Swing Direction")
        swing_layout = QVBoxLayout(swing_group)
        self._swing_combo = QComboBox()
        self._swing_combo.addItems(["left_in", "right_in", "left_out", "right_out"])
        self._swing_combo.currentTextChanged.connect(self._on_swing_changed)
        swing_layout.addWidget(self._swing_combo)
        door_layout.addWidget(swing_group)

        door_layout.addStretch()
        self._stack.addWidget(door_page)

        # Window controls page
        window_page = QWidget()
        window_layout = QVBoxLayout(window_page)
        window_layout.setContentsMargins(0, 0, 0, 0)

        sill_group = QGroupBox("Sill Height")
        sill_layout = QFormLayout(sill_group)
        self._sill_spin = QSpinBox()
        self._sill_spin.setRange(0, 2000)
        self._sill_spin.setSingleStep(50)
        self._sill_spin.setSuffix(" mm")
        self._sill_spin.setValue(900)
        self._sill_spin.valueChanged.connect(self._on_sill_changed)
        sill_layout.addRow("Height:", self._sill_spin)
        window_layout.addWidget(sill_group)

        window_layout.addStretch()
        self._stack.addWidget(window_page)

        layout.addWidget(self._stack)

        # Common controls for both doors and windows
        dims_group = QGroupBox("Dimensions")
        dims_layout = QFormLayout(dims_group)

        self._width_spin = QSpinBox()
        self._width_spin.setRange(300, 5000)
        self._width_spin.setSingleStep(50)
        self._width_spin.setSuffix(" mm")
        self._width_spin.valueChanged.connect(self._on_width_changed)
        dims_layout.addRow("Width:", self._width_spin)

        self._height_spin = QSpinBox()
        self._height_spin.setRange(300, 3000)
        self._height_spin.setSingleStep(50)
        self._height_spin.setSuffix(" mm")
        self._height_spin.valueChanged.connect(self._on_height_changed)
        dims_layout.addRow("Height:", self._height_spin)

        layout.addWidget(dims_group)

        # Pin control
        pin_group = QGroupBox("Constraints")
        pin_layout = QVBoxLayout(pin_group)
        self._pin_check = QCheckBox("Pin opening (prevent modifications)")
        self._pin_check.toggled.connect(self._on_pin_toggled)
        pin_layout.addWidget(self._pin_check)
        layout.addWidget(pin_group)

        # Status label
        self._status_label = QLabel("Select a door or window to edit")
        self._status_label.setStyleSheet("color: #888; font-style: italic;")
        layout.addWidget(self._status_label)

        layout.addStretch()

    def _on_selection_changed(self, selected_items):
        """Update panel when selection changes."""
        self._selected_doors = []
        self._selected_windows = []
        for item in selected_items:
            item_type = type(item).__name__
            if item_type == "DoorItem" and hasattr(item, 'door'):
                self._selected_doors.append(item)
            elif item_type == "WindowItem" and hasattr(item, 'window'):
                self._selected_windows.append(item)

        self._update_ui()

    def _update_ui(self):
        """Update UI to reflect selected opening(s)."""
        self._updating = True
        try:
            has_doors = len(self._selected_doors) > 0
            has_windows = len(self._selected_windows) > 0

            if not has_doors and not has_windows:
                self._status_label.setText("Select a door or window to edit")
                self._stack.setEnabled(False)
                self._width_spin.setEnabled(False)
                self._height_spin.setEnabled(False)
                self._pin_check.setEnabled(False)
                return

            self._stack.setEnabled(True)
            self._width_spin.setEnabled(True)
            self._height_spin.setEnabled(True)
            self._pin_check.setEnabled(True)

            if has_doors and not has_windows:
                self._stack.setCurrentIndex(0)  # Door page
                door = self._selected_doors[0].door
                self._status_label.setText(f"{len(self._selected_doors)} door(s) selected")

                idx = self._door_type_combo.findText(door.door_type)
                if idx >= 0:
                    self._door_type_combo.setCurrentIndex(idx)
                idx = self._swing_combo.findText(door.swing)
                if idx >= 0:
                    self._swing_combo.setCurrentIndex(idx)
                self._width_spin.setValue(int(door.width))
                self._height_spin.setValue(int(door.height))
                self._pin_check.setChecked(door.is_pinned)

            elif has_windows and not has_doors:
                self._stack.setCurrentIndex(1)  # Window page
                window = self._selected_windows[0].window
                self._status_label.setText(f"{len(self._selected_windows)} window(s) selected")

                self._sill_spin.setValue(int(window.sill_height))
                self._width_spin.setValue(int(window.width))
                self._height_spin.setValue(int(window.height))
                self._pin_check.setChecked(window.is_pinned)

            else:
                # Mixed selection
                self._status_label.setText(f"{len(self._selected_doors)} door(s), {len(self._selected_windows)} window(s)")
        finally:
            self._updating = False

    def _on_door_type_changed(self, door_type: str):
        if self._updating or not self._selected_doors:
            return
        from core.events import event_bus
        for item in self._selected_doors:
            item.door.door_type = door_type
        event_bus.document_modified.emit()

    def _on_swing_changed(self, swing: str):
        if self._updating or not self._selected_doors:
            return
        from core.events import event_bus
        for item in self._selected_doors:
            item.door.swing = swing
        event_bus.document_modified.emit()

    def _on_sill_changed(self, sill_height: int):
        if self._updating or not self._selected_windows:
            return
        from core.events import event_bus
        for item in self._selected_windows:
            item.window.sill_height = sill_height
        event_bus.document_modified.emit()

    def _on_width_changed(self, width: int):
        if self._updating:
            return
        from core.events import event_bus
        for item in self._selected_doors:
            item.door.width = width
        for item in self._selected_windows:
            item.window.width = width
        event_bus.document_modified.emit()

    def _on_height_changed(self, height: int):
        if self._updating:
            return
        from core.events import event_bus
        for item in self._selected_doors:
            item.door.height = height
        for item in self._selected_windows:
            item.window.height = height
        event_bus.document_modified.emit()

    def _on_pin_toggled(self, checked: bool):
        if self._updating:
            return
        from core.events import event_bus
        for item in self._selected_doors:
            item.door.is_pinned = checked
        for item in self._selected_windows:
            item.window.is_pinned = checked
        event_bus.document_modified.emit()


class FixturePalettePanel(PlaceholderPanel):
    """Fixture library panel."""
    def __init__(self, parent=None):
        super().__init__(
            "Fixtures",
            "Drag fixtures onto the floor plan",
            "#90EE90",
            parent
        )


class MaterialPickerPanel(QWidget):
    """Material selection panel - uses the real MaterialsPanel implementation."""

    # Forward signal from materials panel
    material_assigned = pyqtSignal(str, str)  # element_type, material_id

    def __init__(self, parent=None):
        super().__init__(parent)
        # Import and wrap the actual MaterialsPanel
        from panels.materials_panel import MaterialsPanel

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._materials_panel = MaterialsPanel(parent)
        # Forward the material_assigned signal
        self._materials_panel.material_assigned.connect(self.material_assigned.emit)
        layout.addWidget(self._materials_panel)

    def set_document(self, document):
        """Forward document to the materials panel."""
        if hasattr(self._materials_panel, 'set_document'):
            self._materials_panel.set_document(document)

    def set_viewport(self, viewport):
        """Forward viewport to the materials panel."""
        if hasattr(self._materials_panel, 'set_viewport'):
            self._materials_panel.set_viewport(viewport)


class CoordinatesPanel(PlaceholderPanel):
    """Coordinate display for Build gravity."""
    def __init__(self, parent=None):
        super().__init__(
            "Coordinates",
            "Element positions and dimensions",
            "#FFA500",  # Orange (Build)
            parent
        )


class SpecEditorPanel(PlaceholderPanel):
    """Specification editing panel."""
    def __init__(self, parent=None):
        super().__init__(
            "Specifications",
            "Edit construction specs and notes",
            "#FFA500",
            parent
        )


class ViewportToolsPanel(PlaceholderPanel):
    """Viewport creation tools for LegiDoc."""
    def __init__(self, parent=None):
        super().__init__(
            "Viewports",
            "Create plan, section, elevation views",
            "#9370DB",  # Medium purple
            parent
        )


class SheetManagerPanel(PlaceholderPanel):
    """Sheet management for LegiDoc."""
    def __init__(self, parent=None):
        super().__init__(
            "Sheets",
            "Manage drawing sheets",
            "#9370DB",
            parent
        )


class CodeChecklistPanel(PlaceholderPanel):
    """Code compliance checklist."""
    def __init__(self, parent=None):
        super().__init__(
            "Code Compliance",
            "Building code requirements",
            "#FFA500",
            parent
        )


# =============================================================================
# Core Panel Widgets (Always Visible or Special)
# =============================================================================

class NavigationPanel(QWidget):
    """
    Navigation panel - combines Gravity Triangle and LOD indicator.
    Always visible - this is the core navigation for the entire app.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        from panels.gravity_triangle import GravityTriangleWidget
        from panels.lod_indicator import LODIndicatorWidget

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(12)

        # Title
        title = QLabel("Navigation")
        title.setStyleSheet("font-weight: bold; font-size: 12px; color: #ddd;")
        layout.addWidget(title, alignment=Qt.AlignmentFlag.AlignCenter)

        # Gravity Triangle
        self.gravity_triangle = GravityTriangleWidget()
        layout.addWidget(self.gravity_triangle, alignment=Qt.AlignmentFlag.AlignCenter)

        # Quick preset buttons for gravity
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(3)

        btn_design = QPushButton("D")
        btn_design.setFixedSize(28, 22)
        btn_design.setToolTip("Design Focus")
        btn_design.setStyleSheet("font-size: 10px; font-weight: bold; color: #6495ED;")
        btn_design.clicked.connect(self.gravity_triangle.set_design)
        btn_layout.addWidget(btn_design)

        btn_client = QPushButton("C")
        btn_client.setFixedSize(28, 22)
        btn_client.setToolTip("Client Focus")
        btn_client.setStyleSheet("font-size: 10px; font-weight: bold; color: #90EE90;")
        btn_client.clicked.connect(self.gravity_triangle.set_client)
        btn_layout.addWidget(btn_client)

        btn_build = QPushButton("B")
        btn_build.setFixedSize(28, 22)
        btn_build.setToolTip("Build Focus")
        btn_build.setStyleSheet("font-size: 10px; font-weight: bold; color: #FFA500;")
        btn_build.clicked.connect(self.gravity_triangle.set_build)
        btn_layout.addWidget(btn_build)

        layout.addLayout(btn_layout)

        # LOD Indicator
        self.lod_indicator = LODIndicatorWidget()
        layout.addWidget(self.lod_indicator)

        layout.addStretch()


class DesignChatPanel(QWidget):
    """
    Design Chat panel wrapper for smart panel system.
    Always visible - core communication tool.
    Uses a placeholder until connected to the app document.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.chat_widget = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Title
        title = QLabel("Design Chat")
        title.setStyleSheet("font-weight: bold; font-size: 11px; color: #9370DB;")
        layout.addWidget(title)

        # Placeholder chat interface
        self._chat_display = QLabel("Chat with AI to design your building.\n\nType a description below...")
        self._chat_display.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._chat_display.setWordWrap(True)
        self._chat_display.setStyleSheet(
            "background: rgba(147, 112, 219, 0.1); "
            "border: 1px solid rgba(147, 112, 219, 0.3); "
            "border-radius: 4px; padding: 10px; color: #aaa;"
        )
        self._chat_display.setMinimumHeight(100)
        layout.addWidget(self._chat_display, 1)

        # Input area
        from PyQt6.QtWidgets import QLineEdit
        self._input = QLineEdit()
        self._input.setPlaceholderText("Describe your building...")
        self._input.setStyleSheet(
            "background: rgba(50, 50, 55, 0.9); "
            "border: 1px solid rgba(147, 112, 219, 0.5); "
            "border-radius: 4px; padding: 8px; color: #ddd;"
        )
        layout.addWidget(self._input)

    def set_document(self, document):
        """Connect to the application document for real chat functionality."""
        # This can be called later to enable full chat
        pass


class SelectionPropertiesPanel(QWidget):
    """
    Properties panel - shows when elements are selected.
    Context-aware based on selection type.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # Title
        title = QLabel("Properties")
        title.setStyleSheet("font-weight: bold; font-size: 11px; color: #90EE90;")
        layout.addWidget(title)

        # Placeholder - in production, embed PropertiesPanel
        self.content = QLabel("Select an element\nto view properties")
        self.content.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.content.setStyleSheet(
            "color: #666; padding: 20px; "
            "background: rgba(144, 238, 144, 0.1); "
            "border: 1px dashed #90EE90; border-radius: 4px;"
        )
        layout.addWidget(self.content)
        layout.addStretch()


# =============================================================================
# Panel Definitions
# =============================================================================

# Core panels (always visible - no workflow/LOD/gravity restrictions)
PANEL_NAVIGATION = PanelDefinition(
    id='navigation',
    name='Navigation',
    widget_class=NavigationPanel,
    conditions=PanelConditions(
        # No restrictions - always visible
        lod_min=1,
        lod_max=5,
    ),
    z_index=100,  # Highest priority - always on top
    can_minimize=False,  # Cannot be minimized
)

PANEL_CHAT = PanelDefinition(
    id='chat',
    name='Design Chat',
    widget_class=DesignChatPanel,
    conditions=PanelConditions(
        # No restrictions - always visible
        lod_min=1,
        lod_max=5,
    ),
    z_index=95,
    can_minimize=True,
)

PANEL_PROPERTIES = PanelDefinition(
    id='properties',
    name='Properties',
    widget_class=SelectionPropertiesPanel,
    conditions=PanelConditions(
        lod_min=1,
        lod_max=5,
        selection=SelectionCondition(
            required=True,  # Only show when something is selected
        ),
    ),
    z_index=90,
)

# LegiQBD Panels
PANEL_BLOB_PALETTE = PanelDefinition(
    id='blob_palette',
    name='Rooms',
    widget_class=BlobPalettePanel,
    conditions=PanelConditions(
        workflow_stages=[WorkflowStage.LEGI_QBD],
        lod_min=1,
        lod_max=1,
        gravity=GravityCondition(design_min=0.3),
    ),
    z_index=80
)

PANEL_RELATIONSHIP_TOOLS = PanelDefinition(
    id='relationship_tools',
    name='Relationships',
    widget_class=RelationshipToolsPanel,
    conditions=PanelConditions(
        workflow_stages=[WorkflowStage.LEGI_QBD],
        lod_min=1,
        lod_max=1,
        gravity=GravityCondition(design_min=0.3),
        selection=SelectionCondition(
            required=True,
            element_types=[ElementType.BLOB, ElementType.RELATIONSHIP]
        ),
    ),
    z_index=85
)

PANEL_SCORE = PanelDefinition(
    id='score',
    name='Design Score',
    widget_class=ScorePanel,
    conditions=PanelConditions(
        workflow_stages=[WorkflowStage.LEGI_QBD, WorkflowStage.LEGI_CAD],
        lod_min=1,
        lod_max=3,
        gravity=GravityCondition(design_min=0.2),
        state=StateCondition(
            schema_states=[SchemaState.ACCUMULATING, SchemaState.COMPLETE, SchemaState.SOLVED]
        ),
    ),
    z_index=75
)

# LegiCAD Panels
PANEL_WALL_TOOLS = PanelDefinition(
    id='wall_tools',
    name='Wall',
    widget_class=WallToolsPanel,
    conditions=PanelConditions(
        workflow_stages=[WorkflowStage.LEGI_CAD],
        lod_min=2,
        lod_max=4,
        selection=SelectionCondition(
            required=True,
            element_types=[ElementType.WALL]
        ),
    ),
    z_index=80
)

PANEL_OPENING_TOOLS = PanelDefinition(
    id='opening_tools',
    name='Opening',
    widget_class=OpeningToolsPanel,
    conditions=PanelConditions(
        workflow_stages=[WorkflowStage.LEGI_CAD],
        lod_min=2,
        lod_max=4,
        selection=SelectionCondition(
            required=True,
            element_types=[ElementType.DOOR, ElementType.WINDOW]
        ),
    ),
    z_index=80
)

PANEL_FIXTURE_PALETTE = PanelDefinition(
    id='fixture_palette',
    name='Fixtures',
    widget_class=FixturePalettePanel,
    conditions=PanelConditions(
        workflow_stages=[WorkflowStage.LEGI_CAD],
        lod_min=3,
        lod_max=5,
        task=TaskCondition(not_during=[TaskType.DRAGGING_FIXTURE]),
    ),
    z_index=80
)

PANEL_MATERIAL_PICKER = PanelDefinition(
    id='material_picker',
    name='Materials',
    widget_class=MaterialPickerPanel,
    conditions=PanelConditions(
        workflow_stages=[WorkflowStage.LEGI_CAD],
        lod_min=2,
        lod_max=5,
        gravity=GravityCondition(client_min=0.4),
        selection=SelectionCondition(
            required=True,
            element_types=[ElementType.WALL, ElementType.FIXTURE, ElementType.FURNITURE]
        ),
    ),
    z_index=70
)

PANEL_COORDINATES = PanelDefinition(
    id='coordinates',
    name='Coordinates',
    widget_class=CoordinatesPanel,
    conditions=PanelConditions(
        workflow_stages=[WorkflowStage.LEGI_CAD, WorkflowStage.LEGI_DOC],
        lod_min=2,
        lod_max=5,
        gravity=GravityCondition(build_min=0.3),
        selection=SelectionCondition(
            required=True,
            element_types=[ElementType.WALL, ElementType.CONTROL_POINT, ElementType.COORDINATE_MARKER]
        ),
    ),
    z_index=60
)

PANEL_SPEC_EDITOR = PanelDefinition(
    id='spec_editor',
    name='Specifications',
    widget_class=SpecEditorPanel,
    conditions=PanelConditions(
        workflow_stages=[WorkflowStage.LEGI_CAD, WorkflowStage.LEGI_DOC],
        lod_min=3,
        lod_max=5,
        gravity=GravityCondition(build_min=0.5),
        selection=SelectionCondition(
            required=True,
            element_types=[ElementType.WALL, ElementType.DOOR, ElementType.WINDOW, ElementType.FIXTURE]
        ),
    ),
    z_index=65
)

# LegiDoc Panels
PANEL_VIEWPORT_TOOLS = PanelDefinition(
    id='viewport_tools',
    name='Viewports',
    widget_class=ViewportToolsPanel,
    conditions=PanelConditions(
        workflow_stages=[WorkflowStage.LEGI_DOC],
        lod_min=4,
        lod_max=5,
    ),
    z_index=80
)

PANEL_SHEET_MANAGER = PanelDefinition(
    id='sheet_manager',
    name='Sheets',
    widget_class=SheetManagerPanel,
    conditions=PanelConditions(
        workflow_stages=[WorkflowStage.LEGI_DOC],
        lod_min=4,
        lod_max=5,
    ),
    z_index=75
)

PANEL_CODE_CHECKLIST = PanelDefinition(
    id='code_checklist',
    name='Code Compliance',
    widget_class=CodeChecklistPanel,
    conditions=PanelConditions(
        workflow_stages=[WorkflowStage.LEGI_DOC],
        lod_min=5,
        lod_max=5,
        gravity=GravityCondition(build_min=0.3),
    ),
    z_index=85
)


# =============================================================================
# Panel Registry
# =============================================================================

PANEL_REGISTRY: List[PanelDefinition] = [
    # Note: Navigation and Chat are now separate dock widgets (not in smart panels)

    # Properties (shows when element selected)
    PANEL_PROPERTIES,

    # LegiQBD
    PANEL_BLOB_PALETTE,
    PANEL_RELATIONSHIP_TOOLS,
    PANEL_SCORE,

    # LegiCAD
    PANEL_WALL_TOOLS,
    PANEL_OPENING_TOOLS,
    PANEL_FIXTURE_PALETTE,
    PANEL_MATERIAL_PICKER,
    PANEL_COORDINATES,
    PANEL_SPEC_EDITOR,

    # LegiDoc
    PANEL_VIEWPORT_TOOLS,
    PANEL_SHEET_MANAGER,
    PANEL_CODE_CHECKLIST,
]


def get_panel_registry() -> List[PanelDefinition]:
    """Get the full panel registry."""
    return PANEL_REGISTRY.copy()
