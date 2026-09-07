"""
Properties Panel - Shows and edits properties of selected elements.
"""
from typing import Optional, List, Any

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPushButton,
    QGroupBox, QScrollArea, QFrame
)
from PyQt6.QtCore import Qt, pyqtSignal

from core.document import ArchDocument, Wall, Door, Window, Room
from core.events import event_bus


class PropertiesPanel(QWidget):
    """
    Panel showing properties of selected elements with edit capability.
    """

    def __init__(self, document: ArchDocument, parent=None):
        super().__init__(parent)
        self.document = document
        self._selected_items = []
        self._updating = False  # Prevent feedback loops

        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        """Set up the panel UI."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)

        # Header
        header = QLabel("Properties")
        header.setStyleSheet("font-weight: bold; font-size: 12px;")
        main_layout.addWidget(header)

        # Scroll area for properties
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        self.scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll_layout.setSpacing(5)
        scroll.setWidget(self.scroll_content)

        main_layout.addWidget(scroll)

        # Create property groups (initially hidden)
        self._create_wall_group()
        self._create_door_group()
        self._create_window_group()
        self._create_room_group()

        # No selection label
        self.no_selection_label = QLabel("No element selected")
        self.no_selection_label.setStyleSheet("color: #888; font-style: italic;")
        self.no_selection_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll_layout.addWidget(self.no_selection_label)

        self.scroll_layout.addStretch()

    def _create_wall_group(self):
        """Create wall properties group."""
        self.wall_group = QGroupBox("Wall Properties")
        layout = QFormLayout(self.wall_group)
        layout.setSpacing(5)

        # Pin toggle at top
        pin_layout = QHBoxLayout()
        self.wall_pin_btn = QPushButton("Pin")
        self.wall_pin_btn.setCheckable(True)
        self.wall_pin_btn.setToolTip("Pin this wall to prevent LLM modifications")
        self.wall_pin_btn.toggled.connect(self._on_wall_pin_toggled)
        pin_layout.addWidget(self.wall_pin_btn)
        pin_layout.addStretch()
        layout.addRow("", pin_layout)

        # Start X
        self.wall_start_x = QDoubleSpinBox()
        self.wall_start_x.setRange(-1e9, 1e9)
        self.wall_start_x.setDecimals(1)
        self.wall_start_x.setSuffix(" mm")
        self.wall_start_x.valueChanged.connect(self._on_wall_changed)
        layout.addRow("Start X:", self.wall_start_x)

        # Start Z
        self.wall_start_z = QDoubleSpinBox()
        self.wall_start_z.setRange(-1e9, 1e9)
        self.wall_start_z.setDecimals(1)
        self.wall_start_z.setSuffix(" mm")
        self.wall_start_z.valueChanged.connect(self._on_wall_changed)
        layout.addRow("Start Z:", self.wall_start_z)

        # End X
        self.wall_end_x = QDoubleSpinBox()
        self.wall_end_x.setRange(-1e9, 1e9)
        self.wall_end_x.setDecimals(1)
        self.wall_end_x.setSuffix(" mm")
        self.wall_end_x.valueChanged.connect(self._on_wall_changed)
        layout.addRow("End X:", self.wall_end_x)

        # End Z
        self.wall_end_z = QDoubleSpinBox()
        self.wall_end_z.setRange(-1e9, 1e9)
        self.wall_end_z.setDecimals(1)
        self.wall_end_z.setSuffix(" mm")
        self.wall_end_z.valueChanged.connect(self._on_wall_changed)
        layout.addRow("End Z:", self.wall_end_z)

        # Height
        self.wall_height = QSpinBox()
        self.wall_height.setRange(100, 20000)
        self.wall_height.setSuffix(" mm")
        self.wall_height.valueChanged.connect(self._on_wall_changed)
        layout.addRow("Height:", self.wall_height)

        # Length (read-only)
        self.wall_length = QLabel("0 mm")
        layout.addRow("Length:", self.wall_length)

        # Category
        self.wall_category = QComboBox()
        self.wall_category.addItems(["exterior", "interior", "foundation"])
        self.wall_category.currentTextChanged.connect(self._on_wall_changed)
        layout.addRow("Category:", self.wall_category)

        self.scroll_layout.addWidget(self.wall_group)
        self.wall_group.hide()

    def _create_door_group(self):
        """Create door properties group."""
        self.door_group = QGroupBox("Door Properties")
        layout = QFormLayout(self.door_group)
        layout.setSpacing(5)

        # Pin toggle at top
        pin_layout = QHBoxLayout()
        self.door_pin_btn = QPushButton("Pin")
        self.door_pin_btn.setCheckable(True)
        self.door_pin_btn.setToolTip("Pin this door to prevent LLM modifications")
        self.door_pin_btn.toggled.connect(self._on_door_pin_toggled)
        pin_layout.addWidget(self.door_pin_btn)
        pin_layout.addStretch()
        layout.addRow("", pin_layout)

        # Wall index (read-only)
        self.door_wall = QLabel("0")
        layout.addRow("Wall:", self.door_wall)

        # Offset
        self.door_offset = QDoubleSpinBox()
        self.door_offset.setRange(0, 1e9)
        self.door_offset.setDecimals(1)
        self.door_offset.setSuffix(" mm")
        self.door_offset.valueChanged.connect(self._on_door_changed)
        layout.addRow("Offset:", self.door_offset)

        # Width
        self.door_width = QSpinBox()
        self.door_width.setRange(300, 5000)
        self.door_width.setSuffix(" mm")
        self.door_width.valueChanged.connect(self._on_door_changed)
        layout.addRow("Width:", self.door_width)

        # Height
        self.door_height = QSpinBox()
        self.door_height.setRange(500, 5000)
        self.door_height.setSuffix(" mm")
        self.door_height.valueChanged.connect(self._on_door_changed)
        layout.addRow("Height:", self.door_height)

        # Swing direction
        self.door_swing = QComboBox()
        self.door_swing.addItems(["left_in", "left_out", "right_in", "right_out"])
        self.door_swing.currentTextChanged.connect(self._on_door_changed)
        layout.addRow("Swing:", self.door_swing)

        self.scroll_layout.addWidget(self.door_group)
        self.door_group.hide()

    def _create_window_group(self):
        """Create window properties group."""
        self.window_group = QGroupBox("Window Properties")
        layout = QFormLayout(self.window_group)
        layout.setSpacing(5)

        # Pin toggle at top
        pin_layout = QHBoxLayout()
        self.window_pin_btn = QPushButton("Pin")
        self.window_pin_btn.setCheckable(True)
        self.window_pin_btn.setToolTip("Pin this window to prevent LLM modifications")
        self.window_pin_btn.toggled.connect(self._on_window_pin_toggled)
        pin_layout.addWidget(self.window_pin_btn)
        pin_layout.addStretch()
        layout.addRow("", pin_layout)

        # Wall index (read-only)
        self.window_wall = QLabel("0")
        layout.addRow("Wall:", self.window_wall)

        # Offset
        self.window_offset = QDoubleSpinBox()
        self.window_offset.setRange(0, 1e9)
        self.window_offset.setDecimals(1)
        self.window_offset.setSuffix(" mm")
        self.window_offset.valueChanged.connect(self._on_window_changed)
        layout.addRow("Offset:", self.window_offset)

        # Width
        self.window_width = QSpinBox()
        self.window_width.setRange(200, 5000)
        self.window_width.setSuffix(" mm")
        self.window_width.valueChanged.connect(self._on_window_changed)
        layout.addRow("Width:", self.window_width)

        # Height
        self.window_height = QSpinBox()
        self.window_height.setRange(200, 5000)
        self.window_height.setSuffix(" mm")
        self.window_height.valueChanged.connect(self._on_window_changed)
        layout.addRow("Height:", self.window_height)

        # Sill height
        self.window_sill = QSpinBox()
        self.window_sill.setRange(0, 3000)
        self.window_sill.setSuffix(" mm")
        self.window_sill.valueChanged.connect(self._on_window_changed)
        layout.addRow("Sill Height:", self.window_sill)

        self.scroll_layout.addWidget(self.window_group)
        self.window_group.hide()

    def _create_room_group(self):
        """Create room properties group."""
        self.room_group = QGroupBox("Room Properties")
        layout = QFormLayout(self.room_group)
        layout.setSpacing(5)

        # Pin toggle at top
        pin_layout = QHBoxLayout()
        self.room_pin_btn = QPushButton("Pin")
        self.room_pin_btn.setCheckable(True)
        self.room_pin_btn.setToolTip("Pin this room to prevent LLM modifications")
        self.room_pin_btn.toggled.connect(self._on_room_pin_toggled)
        pin_layout.addWidget(self.room_pin_btn)
        pin_layout.addStretch()
        layout.addRow("", pin_layout)

        # Name
        self.room_name = QLineEdit()
        self.room_name.textChanged.connect(self._on_room_changed)
        layout.addRow("Name:", self.room_name)

        # Type
        self.room_type = QComboBox()
        self.room_type.addItems([
            "generic", "living", "bedroom", "kitchen", "bathroom",
            "dining", "office", "garage", "hallway", "closet"
        ])
        self.room_type.currentTextChanged.connect(self._on_room_changed)
        layout.addRow("Type:", self.room_type)

        # Area (read-only)
        self.room_area = QLabel("0.00 m²")
        layout.addRow("Area:", self.room_area)

        self.scroll_layout.addWidget(self.room_group)
        self.room_group.hide()

    def _connect_signals(self):
        """Connect to document and event signals."""
        event_bus.selection_changed.connect(self._on_selection_changed)
        event_bus.element_modified.connect(self._on_element_modified)

    def _on_selection_changed(self, selected_items: List):
        """Handle selection change."""
        self._selected_items = selected_items
        self._update_display()

    def _update_display(self):
        """Update the displayed properties based on selection."""
        # Hide all groups
        self.wall_group.hide()
        self.door_group.hide()
        self.window_group.hide()
        self.room_group.hide()

        if not self._selected_items:
            self.no_selection_label.show()
            return

        self.no_selection_label.hide()

        # Get first selected item and show appropriate properties
        item = self._selected_items[0]
        item_type = type(item).__name__

        if item_type == "WallItem":
            self._show_wall_properties(item.wall)
        elif item_type == "DoorItem":
            self._show_door_properties(item.door)
        elif item_type == "WindowItem":
            self._show_window_properties(item.window)
        elif item_type == "RoomItem":
            self._show_room_properties(item.room)

    def _show_wall_properties(self, wall: Wall):
        """Display wall properties."""
        self._updating = True

        # Update pin button state
        self.wall_pin_btn.setChecked(wall.is_pinned)
        self.wall_pin_btn.setText("Pinned" if wall.is_pinned else "Pin")

        self.wall_start_x.setValue(wall.start[0])
        self.wall_start_z.setValue(wall.start[2])
        self.wall_end_x.setValue(wall.end[0])
        self.wall_end_z.setValue(wall.end[2])
        self.wall_height.setValue(int(wall.height))
        self.wall_length.setText(f"{wall.length:.0f} mm")

        idx = self.wall_category.findText(wall.category)
        if idx >= 0:
            self.wall_category.setCurrentIndex(idx)

        # Disable editing if pinned
        pinned = wall.is_pinned
        self.wall_start_x.setEnabled(not pinned)
        self.wall_start_z.setEnabled(not pinned)
        self.wall_end_x.setEnabled(not pinned)
        self.wall_end_z.setEnabled(not pinned)
        self.wall_height.setEnabled(not pinned)
        self.wall_category.setEnabled(not pinned)

        self._updating = False
        self.wall_group.show()

    def _show_door_properties(self, door: Door):
        """Display door properties."""
        self._updating = True

        # Update pin button state
        self.door_pin_btn.setChecked(door.is_pinned)
        self.door_pin_btn.setText("Pinned" if door.is_pinned else "Pin")

        self.door_wall.setText(str(door.wall_index))
        self.door_offset.setValue(door.offset)
        self.door_width.setValue(int(door.width))
        self.door_height.setValue(int(door.height))

        idx = self.door_swing.findText(door.swing)
        if idx >= 0:
            self.door_swing.setCurrentIndex(idx)

        # Disable editing if pinned
        pinned = door.is_pinned
        self.door_offset.setEnabled(not pinned)
        self.door_width.setEnabled(not pinned)
        self.door_height.setEnabled(not pinned)
        self.door_swing.setEnabled(not pinned)

        self._updating = False
        self.door_group.show()

    def _show_window_properties(self, window: Window):
        """Display window properties."""
        self._updating = True

        # Update pin button state
        self.window_pin_btn.setChecked(window.is_pinned)
        self.window_pin_btn.setText("Pinned" if window.is_pinned else "Pin")

        self.window_wall.setText(str(window.wall_index))
        self.window_offset.setValue(window.offset)
        self.window_width.setValue(int(window.width))
        self.window_height.setValue(int(window.height))
        self.window_sill.setValue(int(window.sill_height))

        # Disable editing if pinned
        pinned = window.is_pinned
        self.window_offset.setEnabled(not pinned)
        self.window_width.setEnabled(not pinned)
        self.window_height.setEnabled(not pinned)
        self.window_sill.setEnabled(not pinned)

        self._updating = False
        self.window_group.show()

    def _show_room_properties(self, room: Room):
        """Display room properties."""
        self._updating = True

        # Update pin button state
        self.room_pin_btn.setChecked(room.is_pinned)
        self.room_pin_btn.setText("Pinned" if room.is_pinned else "Pin")

        self.room_name.setText(room.name or "")

        idx = self.room_type.findText(room.room_type)
        if idx >= 0:
            self.room_type.setCurrentIndex(idx)

        area_m2 = room.area / 1e6 if room.area else 0
        self.room_area.setText(f"{area_m2:.2f} m²")

        # Disable editing if pinned
        pinned = room.is_pinned
        self.room_name.setEnabled(not pinned)
        self.room_type.setEnabled(not pinned)

        self._updating = False
        self.room_group.show()

    def _on_wall_changed(self):
        """Handle wall property change from UI."""
        if self._updating or not self._selected_items:
            return

        item = self._selected_items[0]
        if type(item).__name__ != "WallItem":
            return

        wall = item.wall
        new_start = (self.wall_start_x.value(), wall.start[1], self.wall_start_z.value())
        new_end = (self.wall_end_x.value(), wall.end[1], self.wall_end_z.value())

        self.document.modify_wall_undoable(
            wall.index,
            start=new_start,
            end=new_end,
            height=self.wall_height.value(),
            category=self.wall_category.currentText()
        )

        # Update length display
        import math
        dx = new_end[0] - new_start[0]
        dz = new_end[2] - new_start[2]
        length = math.sqrt(dx**2 + dz**2)
        self.wall_length.setText(f"{length:.0f} mm")

    def _on_door_changed(self):
        """Handle door property change from UI."""
        if self._updating or not self._selected_items:
            return

        item = self._selected_items[0]
        if type(item).__name__ != "DoorItem":
            return

        door = item.door
        self.document.modify_door_undoable(
            door.index,
            offset=self.door_offset.value(),
            width=self.door_width.value(),
            height=self.door_height.value(),
            swing=self.door_swing.currentText()
        )

    def _on_window_changed(self):
        """Handle window property change from UI."""
        if self._updating or not self._selected_items:
            return

        item = self._selected_items[0]
        if type(item).__name__ != "WindowItem":
            return

        window = item.window
        self.document.modify_window_undoable(
            window.index,
            offset=self.window_offset.value(),
            width=self.window_width.value(),
            height=self.window_height.value(),
            sill_height=self.window_sill.value()
        )

    def _on_room_changed(self):
        """Handle room property change from UI."""
        if self._updating or not self._selected_items:
            return

        item = self._selected_items[0]
        if type(item).__name__ != "RoomItem":
            return

        # Room modifications would go here
        # For now, rooms are read-only since they're defined by vertices
        pass

    def _on_wall_pin_toggled(self, checked: bool):
        """Handle wall pin toggle."""
        if self._updating or not self._selected_items:
            return

        item = self._selected_items[0]
        if type(item).__name__ != "WallItem":
            return

        self.document.pin_element("wall", str(item.wall.index), checked)
        self.wall_pin_btn.setText("Pinned" if checked else "Pin")
        # Update field enabled states
        self._show_wall_properties(item.wall)

    def _on_door_pin_toggled(self, checked: bool):
        """Handle door pin toggle."""
        if self._updating or not self._selected_items:
            return

        item = self._selected_items[0]
        if type(item).__name__ != "DoorItem":
            return

        self.document.pin_element("door", str(item.door.index), checked)
        self.door_pin_btn.setText("Pinned" if checked else "Pin")
        # Update field enabled states
        self._show_door_properties(item.door)

    def _on_window_pin_toggled(self, checked: bool):
        """Handle window pin toggle."""
        if self._updating or not self._selected_items:
            return

        item = self._selected_items[0]
        if type(item).__name__ != "WindowItem":
            return

        self.document.pin_element("window", str(item.window.index), checked)
        self.window_pin_btn.setText("Pinned" if checked else "Pin")
        # Update field enabled states
        self._show_window_properties(item.window)

    def _on_room_pin_toggled(self, checked: bool):
        """Handle room pin toggle."""
        if self._updating or not self._selected_items:
            return

        item = self._selected_items[0]
        if type(item).__name__ != "RoomItem":
            return

        self.document.pin_element("room", item.room.id, checked)
        self.room_pin_btn.setText("Pinned" if checked else "Pin")
        # Update field enabled states
        self._show_room_properties(item.room)

    def _on_element_modified(self, element_type: str, element_id: str, changes: dict):
        """Handle external element modification."""
        # Refresh display if our selected element was modified
        if self._selected_items:
            item = self._selected_items[0]
            item_type = type(item).__name__

            if item_type == "WallItem" and element_type == "wall":
                if str(item.wall.index) == element_id:
                    self._show_wall_properties(item.wall)
            elif item_type == "DoorItem" and element_type == "door":
                if str(item.door.index) == element_id:
                    self._show_door_properties(item.door)
            elif item_type == "WindowItem" and element_type == "window":
                if str(item.window.index) == element_id:
                    self._show_window_properties(item.window)

    def set_selection(self, items: List):
        """Manually set selection (called from plan view)."""
        self._selected_items = items
        self._update_display()
