"""
LOD Indicator Widget - Shows current Level of Detail based on camera distance.

Based on ESCHER_IMPLEMENTATION_SPEC.md - maps camera elevation/zoom to LOD levels.
"""
from enum import IntEnum
from typing import Tuple, Optional

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QFrame
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QFont, QLinearGradient


class LODLevel(IntEnum):
    """LOD levels from ESCHER spec."""
    TOPOLOGY = 1       # Blobs, massing - high above
    WALLS = 2          # Walls, doors, windows - mid height
    FIXTURES = 3       # Fixtures, furniture - eye level
    VIEWPORTS = 4      # 2D drawing views - close up
    DOCUMENTATION = 5  # Specs, codes - very close


# LOD level metadata
LOD_INFO = {
    LODLevel.TOPOLOGY: {
        "name": "Topology",
        "description": "Massing & relationships",
        "color": QColor(100, 149, 237),  # Cornflower blue
    },
    LODLevel.WALLS: {
        "name": "Walls",
        "description": "Structure & openings",
        "color": QColor(144, 238, 144),  # Light green
    },
    LODLevel.FIXTURES: {
        "name": "Fixtures",
        "description": "Details & furniture",
        "color": QColor(255, 215, 0),  # Gold
    },
    LODLevel.VIEWPORTS: {
        "name": "Viewports",
        "description": "2D drawing views",
        "color": QColor(255, 165, 0),  # Orange
    },
    LODLevel.DOCUMENTATION: {
        "name": "Documentation",
        "description": "Specs & codes",
        "color": QColor(255, 99, 71),  # Tomato
    },
}


# Distance thresholds (in world units, roughly meters * 3.28 for feet)
# Based on ESCHER spec elevation thresholds
LOD_THRESHOLDS = {
    # camera_distance >= threshold → this LOD
    LODLevel.TOPOLOGY: 65.0,      # ~20m
    LODLevel.WALLS: 33.0,         # ~10m
    LODLevel.FIXTURES: 10.0,      # ~3m
    LODLevel.VIEWPORTS: 3.0,      # ~1m
    LODLevel.DOCUMENTATION: 0.0,  # <1m
}


def calculate_lod_from_distance(distance: float) -> Tuple[LODLevel, float]:
    """
    Calculate LOD level and transition progress from camera distance.

    Args:
        distance: Camera distance from target in world units

    Returns:
        Tuple of (current LOD level, transition progress 0-1 to next level)
    """
    # Find current level
    current_level = LODLevel.DOCUMENTATION
    for level in [LODLevel.TOPOLOGY, LODLevel.WALLS, LODLevel.FIXTURES, LODLevel.VIEWPORTS]:
        if distance >= LOD_THRESHOLDS[level]:
            current_level = level
            break

    # Calculate transition progress to next level
    transition = 0.0
    if current_level < LODLevel.DOCUMENTATION:
        next_level = LODLevel(current_level + 1)
        current_threshold = LOD_THRESHOLDS[current_level]
        next_threshold = LOD_THRESHOLDS[next_level]

        if current_threshold > next_threshold:
            range_size = current_threshold - next_threshold
            dist_into_range = current_threshold - distance
            transition = min(1.0, max(0.0, dist_into_range / range_size))

    return current_level, transition


class LODIndicatorWidget(QWidget):
    """
    Visual indicator showing current LOD level.

    Displays as a vertical bar with 5 segments, highlighting the current level.
    """

    lod_changed = pyqtSignal(int, float)  # level, transition

    def __init__(self, parent=None):
        super().__init__(parent)

        self._current_lod = LODLevel.WALLS
        self._transition = 0.0
        self._camera_distance = 60.0

        self.setMinimumSize(60, 120)
        self.setMaximumSize(80, 160)

        self.setToolTip(
            "Level of Detail\n"
            "Based on camera distance:\n"
            "1. Topology (far)\n"
            "2. Walls\n"
            "3. Fixtures\n"
            "4. Viewports\n"
            "5. Documentation (close)"
        )

    def set_camera_distance(self, distance: float):
        """Update LOD based on camera distance (auto mode)."""
        self._camera_distance = distance
        new_lod, transition = calculate_lod_from_distance(distance)

        if new_lod != self._current_lod or abs(transition - self._transition) > 0.01:
            self._current_lod = new_lod
            self._transition = transition
            self.lod_changed.emit(int(new_lod), transition)
            self.update()

    def set_lod_level(self, level: int):
        """Set LOD level directly (manual mode via shift+scroll)."""
        if 1 <= level <= 5:
            new_lod = LODLevel(level)
            if new_lod != self._current_lod:
                self._current_lod = new_lod
                self._transition = 0.0
                self.lod_changed.emit(level, 0.0)
                self.update()

    def get_lod(self) -> Tuple[LODLevel, float]:
        """Get current LOD level and transition progress."""
        return self._current_lod, self._transition

    def get_lod_level(self) -> int:
        """Get current LOD level as integer (1-5)."""
        return int(self._current_lod)

    def paintEvent(self, event):
        """Draw the LOD indicator."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()

        # Layout
        bar_width = 20
        bar_x = 10
        bar_height = h - 40
        bar_top = 25
        segment_height = bar_height / 5

        # Draw title
        painter.setPen(QPen(QColor(200, 200, 200)))
        font = QFont()
        font.setPointSize(8)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(0, 0, w, 20, Qt.AlignmentFlag.AlignCenter, "LOD")

        # Draw segments (bottom to top = LOD 5 to 1)
        for i, level in enumerate(reversed(list(LODLevel))):
            y = bar_top + i * segment_height
            info = LOD_INFO[level]
            color = info["color"]

            # Determine if this is the current level
            is_current = level == self._current_lod

            # Draw segment background
            if is_current:
                # Highlight current level
                painter.setBrush(QBrush(color))
                painter.setPen(QPen(color.lighter(120), 2))
            else:
                # Dim other levels
                dim_color = QColor(color)
                dim_color.setAlpha(60)
                painter.setBrush(QBrush(dim_color))
                painter.setPen(QPen(QColor(80, 80, 80), 1))

            painter.drawRoundedRect(
                int(bar_x), int(y), bar_width, int(segment_height - 2), 3, 3
            )

            # Draw level number
            painter.setPen(QPen(QColor(220, 220, 220) if is_current else QColor(120, 120, 120)))
            font.setPointSize(7)
            font.setBold(is_current)
            painter.setFont(font)
            painter.drawText(
                bar_x + bar_width + 5, int(y),
                w - bar_x - bar_width - 10, int(segment_height),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                f"{level}"
            )

        # Draw current level name below
        info = LOD_INFO[self._current_lod]
        painter.setPen(QPen(info["color"]))
        font.setPointSize(7)
        font.setBold(False)
        painter.setFont(font)
        painter.drawText(
            0, h - 15, w, 15,
            Qt.AlignmentFlag.AlignCenter,
            info["name"]
        )


class LODControlWidget(QWidget):
    """
    Combined LOD display with indicator and info.
    """

    lod_changed = pyqtSignal(int, float)

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)

        # LOD indicator
        self.indicator = LODIndicatorWidget()
        self.indicator.lod_changed.connect(self._on_lod_changed)
        layout.addWidget(self.indicator, alignment=Qt.AlignmentFlag.AlignCenter)

        # Info label
        self.info_label = QLabel("Structure & openings")
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.info_label.setStyleSheet("color: #888; font-size: 9px;")
        self.info_label.setWordWrap(True)
        layout.addWidget(self.info_label)

    def _on_lod_changed(self, level: int, transition: float):
        """Handle LOD change."""
        lod = LODLevel(level)
        info = LOD_INFO[lod]
        self.info_label.setText(info["description"])
        self.lod_changed.emit(level, transition)

    def set_camera_distance(self, distance: float):
        """Update from camera distance (auto mode)."""
        self.indicator.set_camera_distance(distance)

    def set_lod_level(self, level: int):
        """Set LOD level directly (manual mode)."""
        self.indicator.set_lod_level(level)

    def get_lod(self) -> Tuple[LODLevel, float]:
        """Get current LOD."""
        return self.indicator.get_lod()

    def get_lod_level(self) -> int:
        """Get current LOD level as integer."""
        return self.indicator.get_lod_level()
