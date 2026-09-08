"""
Plan View - Main 2D floor plan editor
"""
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass
from enum import Enum
import math

from PyQt6.QtWidgets import (
    QGraphicsItem, QGraphicsRectItem, QGraphicsLineItem,
    QGraphicsTextItem, QGraphicsEllipseItem
)
from PyQt6.QtCore import Qt, QRectF, QPointF, QLineF, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QPainterPath, QFont, QPolygonF

from views.base_view import BaseView
from core.document import ArchDocument, Wall, Door, Window, Room
from core.events import event_bus
from app.config import Config


# =============================================================================
# Snap System
# =============================================================================

class SnapType(Enum):
    """Types of snap points."""
    ENDPOINT = "endpoint"
    MIDPOINT = "midpoint"
    PERPENDICULAR = "perpendicular"
    PARALLEL = "parallel"
    EXTENSION = "extension"
    ANGULAR = "angular"  # 45°, 30°, 60° etc
    INTERSECTION = "intersection"


@dataclass
class SnapPoint:
    """Represents a potential snap target."""
    x: float
    y: float
    snap_type: SnapType
    source_wall_idx: int = -1  # Index of wall this snap comes from
    angle: float = 0.0  # Angle in degrees (for perpendicular snaps)

    @property
    def point(self) -> QPointF:
        return QPointF(self.x, self.y)


class SnapIndicator(QGraphicsItem):
    """Visual indicator for active snap point."""

    SIZE = 200  # mm

    def __init__(self, parent=None):
        super().__init__(parent)
        self._snap_type: Optional[SnapType] = None
        self._angle: float = 0.0
        self._font = QFont("Arial", 120)
        self.setZValue(3000)  # Above grips
        self.hide()

    def set_snap(self, point: QPointF, snap_type: SnapType, angle: float = 0.0):
        """Show snap indicator at point."""
        self.setPos(point)
        self._snap_type = snap_type
        self._angle = angle
        self.show()
        self.update()

    def clear(self):
        """Hide snap indicator."""
        self.hide()
        self._snap_type = None
        self._angle = 0.0

    def boundingRect(self) -> QRectF:
        s = self.SIZE
        return QRectF(-s * 2, -s * 2, s * 4, s * 4)

    def paint(self, painter: QPainter, option, widget):
        if not self._snap_type:
            return

        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = self.SIZE

        if self._snap_type == SnapType.ENDPOINT:
            # Square for endpoints
            pen = QPen(QColor(0, 255, 0), 20)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(QRectF(-s/2, -s/2, s, s))

        elif self._snap_type == SnapType.MIDPOINT:
            # Triangle for midpoints
            pen = QPen(QColor(0, 255, 255), 20)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            path = QPainterPath()
            path.moveTo(0, -s/2)
            path.lineTo(-s/2, s/2)
            path.lineTo(s/2, s/2)
            path.closeSubpath()
            painter.drawPath(path)

        elif self._snap_type == SnapType.PERPENDICULAR:
            # Right angle symbol for perpendicular
            pen = QPen(QColor(255, 128, 0), 20)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawLine(QPointF(-s/2, 0), QPointF(0, 0))
            painter.drawLine(QPointF(0, 0), QPointF(0, -s/2))

            # Draw angle text
            painter.setFont(self._font)
            angle_text = f"{self._angle:.4f}°"
            painter.drawText(QPointF(s/2 + 50, s/2), angle_text)

        elif self._snap_type == SnapType.PARALLEL:
            # Two parallel lines symbol
            pen = QPen(QColor(0, 200, 255), 20)
            painter.setPen(pen)
            painter.drawLine(QPointF(-s/2, -s/4), QPointF(s/2, -s/4))
            painter.drawLine(QPointF(-s/2, s/4), QPointF(s/2, s/4))

        elif self._snap_type == SnapType.EXTENSION:
            # Dashed line extending symbol
            pen = QPen(QColor(255, 200, 0), 20, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawLine(QPointF(-s, 0), QPointF(s, 0))
            # Small square at snap point
            pen.setStyle(Qt.PenStyle.SolidLine)
            painter.setPen(pen)
            painter.drawRect(QRectF(-s/4, -s/4, s/2, s/2))

        elif self._snap_type == SnapType.ANGULAR:
            # Arc symbol for angular snap
            pen = QPen(QColor(200, 100, 255), 20)
            painter.setPen(pen)
            painter.drawArc(QRectF(-s/2, -s/2, s, s), 0, int(self._angle * 16))
            # Draw angle text
            painter.setFont(self._font)
            painter.drawText(QPointF(s/2 + 50, 0), f"{self._angle:.0f}°")

        elif self._snap_type == SnapType.INTERSECTION:
            # X for intersections
            pen = QPen(QColor(255, 0, 255), 20)
            painter.setPen(pen)
            painter.drawLine(QPointF(-s/2, -s/2), QPointF(s/2, s/2))
            painter.drawLine(QPointF(-s/2, s/2), QPointF(s/2, -s/2))


class SnapManager:
    """Manages snap points and snapping logic."""

    SNAP_TOLERANCE = 500  # mm - distance within which to snap

    def __init__(self, document: ArchDocument, config: Config = None):
        self.document = document
        self.config = config
        self._snap_points: List[SnapPoint] = []
        self._excluded_wall_idx: int = -1  # Wall being edited (exclude from snapping)

    def set_excluded_wall(self, wall_idx: int):
        """Set wall to exclude from snap point collection."""
        self._excluded_wall_idx = wall_idx

    def collect_snap_points(self):
        """Collect all snap points from document."""
        self._snap_points.clear()

        for i, wall in enumerate(self.document.walls):
            if i == self._excluded_wall_idx:
                continue

            x1, z1 = wall.start[0], wall.start[2]
            x2, z2 = wall.end[0], wall.end[2]
            cx, cz = (x1 + x2) / 2, (z1 + z2) / 2

            # Endpoints (if enabled)
            if not self.config or self.config.snap_endpoint:
                self._snap_points.append(SnapPoint(x1, z1, SnapType.ENDPOINT, i))
                self._snap_points.append(SnapPoint(x2, z2, SnapType.ENDPOINT, i))

            # Midpoint (if enabled)
            if not self.config or self.config.snap_midpoint:
                self._snap_points.append(SnapPoint(cx, cz, SnapType.MIDPOINT, i))

    def find_perpendicular_snap(self, point: QPointF, from_point: Optional[QPointF] = None,
                                  fixed_point: Optional[QPointF] = None) -> Optional[SnapPoint]:
        """
        Find perpendicular snap point.

        If fixed_point is provided: Find position where the line from fixed_point to
        the snap position would be perpendicular to a target wall (makes your wall ⊥ to another).

        Otherwise (legacy): Find where a 90° line from from_point hits a wall.
        """
        # New behavior: make wall perpendicular to another wall
        if fixed_point:
            return self._find_make_wall_perpendicular(point, fixed_point)

        # Legacy behavior
        if not from_point:
            return None

        best_snap = None
        best_dist = self.SNAP_TOLERANCE

        for i, wall in enumerate(self.document.walls):
            if i == self._excluded_wall_idx:
                continue

            x1, z1 = wall.start[0], wall.start[2]
            x2, z2 = wall.end[0], wall.end[2]

            wall_dx = x2 - x1
            wall_dz = z2 - z1
            wall_len = math.sqrt(wall_dx**2 + wall_dz**2)
            if wall_len < 1:
                continue

            wall_ux = wall_dx / wall_len
            wall_uz = wall_dz / wall_len
            perp_ux = -wall_uz
            perp_uz = wall_ux

            denom = perp_ux * wall_uz - perp_uz * wall_ux
            if abs(denom) < 0.0001:
                continue

            dx = x1 - from_point.x()
            dz = z1 - from_point.y()

            t = (dx * wall_uz - dz * wall_ux) / denom
            s = (dx * perp_uz - dz * perp_ux) / denom

            if s < -0.01 or s > wall_len + 0.01:
                continue

            snap_x = from_point.x() + t * perp_ux
            snap_z = from_point.y() + t * perp_uz

            dist = self._distance(point.x(), point.y(), snap_x, snap_z)
            if dist < best_dist:
                best_dist = dist
                best_snap = SnapPoint(snap_x, snap_z, SnapType.PERPENDICULAR, i, 90.0)

        return best_snap

    def _find_make_wall_perpendicular(self, point: QPointF, fixed_point: QPointF) -> Optional[SnapPoint]:
        """
        Find snap position where the wall being edited becomes perpendicular to another wall.

        fixed_point: The other endpoint of the wall being edited (stays fixed)
        point: Current drag position

        Returns snap position where fixed_point → snap_pos is ⊥ to a target wall.
        """
        best_snap = None
        best_dist = self.SNAP_TOLERANCE

        # Current distance from fixed point (we keep the same length)
        dx = point.x() - fixed_point.x()
        dz = point.y() - fixed_point.y()
        current_len = math.sqrt(dx * dx + dz * dz)

        if current_len < 10:
            return None  # Too close to fixed point

        for i, wall in enumerate(self.document.walls):
            if i == self._excluded_wall_idx:
                continue

            x1, z1 = wall.start[0], wall.start[2]
            x2, z2 = wall.end[0], wall.end[2]

            # Target wall direction
            wall_dx = x2 - x1
            wall_dz = z2 - z1
            wall_len = math.sqrt(wall_dx * wall_dx + wall_dz * wall_dz)
            if wall_len < 1:
                continue

            # Normalized target wall direction
            wall_ux = wall_dx / wall_len
            wall_uz = wall_dz / wall_len

            # Two perpendicular directions to the target wall
            perp_dirs = [
                (-wall_uz, wall_ux),   # +90°
                (wall_uz, -wall_ux),   # -90°
            ]

            for perp_ux, perp_uz in perp_dirs:
                # Snap position: fixed_point + current_len * perp_dir
                snap_x = fixed_point.x() + current_len * perp_ux
                snap_z = fixed_point.y() + current_len * perp_uz

                # Check if this is close to where user is dragging
                dist = self._distance(point.x(), point.y(), snap_x, snap_z)
                if dist < best_dist:
                    best_dist = dist
                    best_snap = SnapPoint(snap_x, snap_z, SnapType.PERPENDICULAR, i, 90.0)

        return best_snap

    def find_parallel_snap(self, point: QPointF, fixed_point: Optional[QPointF] = None) -> Optional[SnapPoint]:
        """
        Find snap position where the wall being edited becomes parallel to another wall.
        Similar to perpendicular but at 0° instead of 90°.
        """
        if not fixed_point:
            return None

        best_snap = None
        best_dist = self.SNAP_TOLERANCE

        # Current distance from fixed point
        dx = point.x() - fixed_point.x()
        dz = point.y() - fixed_point.y()
        current_len = math.sqrt(dx * dx + dz * dz)

        if current_len < 10:
            return None

        for i, wall in enumerate(self.document.walls):
            if i == self._excluded_wall_idx:
                continue

            x1, z1 = wall.start[0], wall.start[2]
            x2, z2 = wall.end[0], wall.end[2]

            wall_dx = x2 - x1
            wall_dz = z2 - z1
            wall_len = math.sqrt(wall_dx * wall_dx + wall_dz * wall_dz)
            if wall_len < 1:
                continue

            # Normalized target wall direction (parallel directions)
            wall_ux = wall_dx / wall_len
            wall_uz = wall_dz / wall_len

            # Two parallel directions (same as wall, or opposite)
            parallel_dirs = [
                (wall_ux, wall_uz),    # Same direction
                (-wall_ux, -wall_uz),  # Opposite direction
            ]

            for par_ux, par_uz in parallel_dirs:
                snap_x = fixed_point.x() + current_len * par_ux
                snap_z = fixed_point.y() + current_len * par_uz

                dist = self._distance(point.x(), point.y(), snap_x, snap_z)
                if dist < best_dist:
                    best_dist = dist
                    best_snap = SnapPoint(snap_x, snap_z, SnapType.PARALLEL, i, 0.0)

        return best_snap

    def find_extension_snap(self, point: QPointF) -> Optional[SnapPoint]:
        """
        Find snap to extension lines of existing walls.
        Snaps to where wall centerlines would extend beyond their endpoints.
        """
        best_snap = None
        best_dist = self.SNAP_TOLERANCE

        for i, wall in enumerate(self.document.walls):
            if i == self._excluded_wall_idx:
                continue

            x1, z1 = wall.start[0], wall.start[2]
            x2, z2 = wall.end[0], wall.end[2]

            wall_dx = x2 - x1
            wall_dz = z2 - z1
            wall_len = math.sqrt(wall_dx * wall_dx + wall_dz * wall_dz)
            if wall_len < 1:
                continue

            wall_ux = wall_dx / wall_len
            wall_uz = wall_dz / wall_len

            # Project point onto the infinite line of this wall
            # Vector from wall start to point
            px = point.x() - x1
            pz = point.y() - z1

            # Parameter t along wall direction
            t = (px * wall_ux + pz * wall_uz)

            # Only snap if in extension zone (before start or after end)
            if 0 <= t <= wall_len:
                continue  # Point is alongside the wall, not in extension

            # Calculate snap point on the extension line
            snap_x = x1 + t * wall_ux
            snap_z = z1 + t * wall_uz

            # Check perpendicular distance to extension line
            perp_dist = abs(px * (-wall_uz) + pz * wall_ux)
            if perp_dist > self.SNAP_TOLERANCE:
                continue

            dist = self._distance(point.x(), point.y(), snap_x, snap_z)
            if dist < best_dist:
                best_dist = dist
                best_snap = SnapPoint(snap_x, snap_z, SnapType.EXTENSION, i, 0.0)

        return best_snap

    def find_angular_snap(self, point: QPointF, fixed_point: Optional[QPointF] = None) -> Optional[SnapPoint]:
        """
        Snap to common architectural angles: 30°, 45°, 60° (and their multiples).
        """
        if not fixed_point:
            return None

        dx = point.x() - fixed_point.x()
        dz = point.y() - fixed_point.y()
        current_len = math.sqrt(dx * dx + dz * dz)

        if current_len < 10:
            return None

        # Current angle in degrees
        current_angle = math.degrees(math.atan2(dz, dx))

        # Common angles to snap to (excluding 0, 90, 180, -90 which are handled by ortho)
        snap_angles = [30, 45, 60, 120, 135, 150, -30, -45, -60, -120, -135, -150]

        best_snap = None
        best_diff = 10  # degrees tolerance for angular snap

        for target_angle in snap_angles:
            diff = abs(current_angle - target_angle)
            if diff > 180:
                diff = 360 - diff

            if diff < best_diff:
                best_diff = diff
                rad = math.radians(target_angle)
                snap_x = fixed_point.x() + current_len * math.cos(rad)
                snap_z = fixed_point.y() + current_len * math.sin(rad)
                best_snap = SnapPoint(snap_x, snap_z, SnapType.ANGULAR, -1, abs(target_angle))

        return best_snap

    def _project_point_to_line(self, point: QPointF, x1: float, y1: float, x2: float, y2: float) -> Optional[Tuple[float, float]]:
        """Project point onto line segment, return None if outside segment."""
        dx = x2 - x1
        dy = y2 - y1
        length_sq = dx * dx + dy * dy

        if length_sq < 1:  # Degenerate line
            return None

        # Parameter t for projection onto infinite line
        t = ((point.x() - x1) * dx + (point.y() - y1) * dy) / length_sq

        # Only snap if projection is on the segment (with small margin)
        if t < -0.01 or t > 1.01:
            return None

        # Clamp to segment
        t = max(0, min(1, t))

        proj_x = x1 + t * dx
        proj_y = y1 + t * dy

        return (proj_x, proj_y)

    def find_nearest_snap(self, point: QPointF, include_perpendicular: bool = True,
                          from_point: Optional[QPointF] = None,
                          fixed_point: Optional[QPointF] = None) -> Optional[SnapPoint]:
        """
        Find nearest snap point within tolerance.

        fixed_point: For perpendicular/parallel/angular snaps, the fixed endpoint of the wall being edited.
        """
        # Check if snapping is globally enabled
        if self.config and not self.config.snap_enabled:
            return None

        best_snap = None
        best_dist = self.SNAP_TOLERANCE

        # Priority 1: Check collected snap points (endpoints, midpoints) - highest priority
        # These are already filtered in collect_snap_points based on config
        for snap in self._snap_points:
            dist = self._distance(point.x(), point.y(), snap.x, snap.y)
            if dist < best_dist:
                best_dist = dist
                best_snap = snap

        # Priority 2: Extension snaps (align to wall extensions)
        if not self.config or self.config.snap_extension:
            ext_snap = self.find_extension_snap(point)
            if ext_snap:
                dist = self._distance(point.x(), point.y(), ext_snap.x, ext_snap.y)
                if dist < best_dist:
                    best_dist = dist
                    best_snap = ext_snap

        # Priority 3: Perpendicular snaps (make wall ⊥ to another)
        if (not self.config or self.config.snap_perpendicular) and include_perpendicular and fixed_point:
            perp_snap = self.find_perpendicular_snap(point, from_point, fixed_point)
            if perp_snap:
                dist = self._distance(point.x(), point.y(), perp_snap.x, perp_snap.y)
                if dist < best_dist:
                    best_dist = dist
                    best_snap = perp_snap

        # Priority 4: Parallel snaps (make wall ∥ to another)
        if (not self.config or self.config.snap_parallel) and fixed_point:
            par_snap = self.find_parallel_snap(point, fixed_point)
            if par_snap:
                dist = self._distance(point.x(), point.y(), par_snap.x, par_snap.y)
                if dist < best_dist:
                    best_dist = dist
                    best_snap = par_snap

        # Priority 5: Angular snaps (30°, 45°, 60° etc) - lowest priority geometry snap
        if (not self.config or self.config.snap_angular) and fixed_point:
            ang_snap = self.find_angular_snap(point, fixed_point)
            if ang_snap:
                dist = self._distance(point.x(), point.y(), ang_snap.x, ang_snap.y)
                if dist < best_dist:
                    best_snap = ang_snap

        return best_snap

    def _distance(self, x1: float, y1: float, x2: float, y2: float) -> float:
        """Calculate distance between two points."""
        return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)


# =============================================================================
# Grip Items for interactive editing
# =============================================================================

class GripItem(QGraphicsEllipseItem):
    """Draggable grip for editing geometry."""

    GRIP_SIZE = 150  # mm - visual size (small, subtle)
    HIT_SIZE = 800   # mm - clickable area (large, easy to grab)

    def __init__(self, grip_type: str, parent_item, callback, snap_manager=None, snap_indicator=None, wall_idx: int = -1, config=None, on_drag_start=None, on_drag_end=None, parent=None):
        size = self.GRIP_SIZE
        super().__init__(-size/2, -size/2, size, size, parent)
        self.grip_type = grip_type  # 'start', 'end', 'center'
        self.parent_item = parent_item
        self.callback = callback
        self.snap_manager = snap_manager
        self.snap_indicator = snap_indicator
        self.wall_idx = wall_idx  # Index of wall this grip belongs to
        self.config = config  # For ortho mode
        self.on_drag_start = on_drag_start  # Callback when drag starts
        self.on_drag_end = on_drag_end  # Callback when drag ends

        # Appearance - blue fill, white border
        self.setBrush(QBrush(QColor(50, 150, 255)))
        self.setPen(QPen(QColor(255, 255, 255), 15))
        self.setZValue(2000)  # Always on top

        # Behavior - movable but NOT selectable (so parent item stays selected)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setAcceptHoverEvents(True)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setCursor(Qt.CursorShape.SizeAllCursor)

        self._dragging = False
        self._current_snap: Optional[SnapPoint] = None
        self._drag_start: Optional[QPointF] = None  # For ortho mode

    def boundingRect(self) -> QRectF:
        """Return larger bounding rect for easier clicking."""
        hit = self.HIT_SIZE
        return QRectF(-hit/2, -hit/2, hit, hit)

    def shape(self) -> QPainterPath:
        """Return larger shape for hit testing."""
        path = QPainterPath()
        hit = self.HIT_SIZE
        path.addEllipse(-hit/2, -hit/2, hit, hit)
        return path

    def paint(self, painter: QPainter, option, widget):
        """Paint the visible grip (smaller than hit area)."""
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        size = self.GRIP_SIZE
        painter.setBrush(self.brush())
        painter.setPen(self.pen())
        painter.drawEllipse(QRectF(-size/2, -size/2, size, size))

    def hoverEnterEvent(self, event):
        self.setBrush(QBrush(QColor(255, 200, 0)))
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.setBrush(QBrush(QColor(0, 150, 255)))
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        self._dragging = True
        self._current_snap = None
        self._drag_start = self.pos()  # Store start position for ortho

        # Notify drag start
        if self.on_drag_start:
            self.on_drag_start(self.grip_type)

        # Select the parent item (wall) if it's selectable
        if self.parent_item and hasattr(self.parent_item, 'setSelected'):
            self.parent_item.setSelected(True)

        # Prepare snap manager
        if self.snap_manager:
            self.snap_manager.set_excluded_wall(self.wall_idx)
            self.snap_manager.collect_snap_points()

        event.accept()  # Stop event propagation to items underneath
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self._dragging = False

        # Apply final snap if active
        if self._current_snap:
            # Move to exact snap position
            self._dragging = False  # Prevent callback during setPos
            super().setPos(self._current_snap.x, self._current_snap.y)
            # Now trigger callback with snapped position
            if self.callback:
                self.callback(self.grip_type, QPointF(self._current_snap.x, self._current_snap.y))

        # Clear snap indicator
        if self.snap_indicator:
            self.snap_indicator.clear()

        # Notify drag end (for undo command creation)
        if self.on_drag_end:
            self.on_drag_end(self.grip_type)

        self._current_snap = None
        super().mouseReleaseEvent(event)

    def _get_fixed_point(self) -> Optional[QPointF]:
        """Get the fixed endpoint of the wall (the one NOT being dragged)."""
        if not self.parent_item or not hasattr(self.parent_item, 'wall'):
            return None
        wall = self.parent_item.wall
        if self.grip_type == 'start':
            # Dragging start, so end is fixed
            return QPointF(wall.end[0], wall.end[2])
        elif self.grip_type == 'end':
            # Dragging end, so start is fixed
            return QPointF(wall.start[0], wall.start[2])
        else:
            # Center grip - no fixed point
            return None

    def itemChange(self, change, value):
        # Use ItemPositionChange to modify position BEFORE it's applied
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            if self._dragging and self._drag_start:
                new_pos = value

                # Check for snap points first
                snap_found = False
                if self.snap_manager:
                    # Get the fixed point for perpendicular snaps
                    fixed_point = self._get_fixed_point()
                    snap = self.snap_manager.find_nearest_snap(new_pos, from_point=self._drag_start, fixed_point=fixed_point)
                    if snap:
                        self._current_snap = snap
                        # Show snap indicator
                        if self.snap_indicator:
                            self.snap_indicator.set_snap(snap.point, snap.snap_type, snap.angle)
                        # Use snapped position
                        new_pos = snap.point
                        snap_found = True
                    else:
                        self._current_snap = None
                        if self.snap_indicator:
                            self.snap_indicator.clear()

                # Apply ortho as a SOFT snap (only if no other snap found)
                if not snap_found and self.config and self.config.ortho_mode:
                    dx = new_pos.x() - self._drag_start.x()
                    dy = new_pos.y() - self._drag_start.y()
                    dist = math.sqrt(dx*dx + dy*dy)

                    if dist > 10:  # Only snap if moved a bit
                        # Calculate angle from start (0 = right, 90 = down, etc)
                        angle = math.degrees(math.atan2(dy, dx))

                        # Snap to ortho if within tolerance of H/V
                        ortho_tolerance = 15  # degrees
                        snapped_angle = None

                        # Check each cardinal direction with proper wraparound
                        for target in [0, 90, -90, 180]:
                            diff = abs(angle - target)
                            # Handle wraparound at ±180
                            if diff > 180:
                                diff = 360 - diff
                            if diff < ortho_tolerance:
                                snapped_angle = target
                                break

                        if snapped_angle is not None:
                            # Snap to ortho
                            rad = math.radians(snapped_angle)
                            new_pos = QPointF(
                                self._drag_start.x() + dist * math.cos(rad),
                                self._drag_start.y() + dist * math.sin(rad)
                            )
                            # Show ortho indicator
                            if self.snap_indicator:
                                self.snap_indicator.set_snap(new_pos, SnapType.PERPENDICULAR, 90.0)

                # Trigger callback with final position
                if self.callback:
                    self.callback(self.grip_type, new_pos)

                return new_pos

        return super().itemChange(change, value)

    def setPos(self, *args):
        """Override setPos to not trigger callback."""
        was_dragging = self._dragging
        self._dragging = False
        super().setPos(*args)
        self._dragging = was_dragging


class RoomLabelItem(QGraphicsItem):
    """Text label for room names."""

    def __init__(self, room: Room, parent=None):
        super().__init__(parent)
        self.room = room
        self._font = QFont("Arial", 200)  # Large font for mm scale
        self._color = QColor(200, 200, 200, 180)

        # Position at room center
        if room.center:
            self.setPos(room.center.get('x', 0), room.center.get('y', 0))
        elif room.bounds:
            cx = room.bounds.get('x', 0) + room.bounds.get('width', 0) / 2
            cy = room.bounds.get('y', 0) + room.bounds.get('height', 0) / 2
            self.setPos(cx, cy)

    def boundingRect(self) -> QRectF:
        return QRectF(-2000, -500, 4000, 1000)

    def paint(self, painter: QPainter, option, widget):
        painter.setFont(self._font)
        painter.setPen(QPen(self._color))

        # Draw room name centered
        name = self.room.name or self.room.room_type
        rect = self.boundingRect()
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, name)


class WallLayerItem(QGraphicsItem):
    """
    Graphics item representing a single layer of a wall.
    Each layer can be selected and edited independently.
    """

    def __init__(self, wall, layer_index: int, layer_data, offset_from_center: float,
                 document=None, parent_wall_item=None, parent=None):
        super().__init__(parent)
        self.wall = wall
        self.layer_index = layer_index
        self.layer_data = layer_data  # WallLayer dataclass
        self.offset_from_center = offset_from_center  # Offset to layer center from wall centerline
        self.document = document
        self.parent_wall_item = parent_wall_item

        # Layer-specific extension adjustments (user can override)
        self.start_extension = 0.0  # mm to extend/retract at start
        self.end_extension = 0.0    # mm to extend/retract at end

        # Grips
        self._grips: List[GripItem] = []
        self._selected = False

        # Colors - clamp to valid range to prevent QColor errors
        r, g, b, a = layer_data.color
        r, g, b, a = max(0, min(1, r)), max(0, min(1, g)), max(0, min(1, b)), max(0, min(1, a))
        self._fill_color = QColor(int(r * 255), int(g * 255), int(b * 255), int(a * 255))
        self._selection_color = QColor("#00ffff")

        # Layers are non-selectable - clicks pass through to parent wall
        # But they enable precise hover detection for grips
        self.setAcceptHoverEvents(True)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)  # Pass clicks through
        self.setZValue(100 + layer_index)  # Outer layers on top

    def _get_geometry(self) -> Tuple[QPointF, QPointF, QPointF, QPointF]:
        """Calculate the four corner points of this layer."""
        x1, z1 = self.wall.start[0], self.wall.start[2]
        x2, z2 = self.wall.end[0], self.wall.end[2]

        dx = x2 - x1
        dz = z2 - z1
        length = math.sqrt(dx**2 + dz**2)
        if length < 1:
            return None

        # Unit vectors
        ux, uz = dx / length, dz / length
        px, pz = -uz, ux

        # Layer edges (offset from centerline)
        half_thick = self.layer_data.thickness / 2
        outer_offset = self.offset_from_center + half_thick
        inner_offset = self.offset_from_center - half_thick

        # Apply extensions
        ext_start = self.start_extension
        ext_end = self.end_extension

        # Corner points
        p1 = QPointF(x1 + px * outer_offset - ux * ext_start, z1 + pz * outer_offset - uz * ext_start)
        p2 = QPointF(x1 + px * inner_offset - ux * ext_start, z1 + pz * inner_offset - uz * ext_start)
        p3 = QPointF(x2 + px * inner_offset + ux * ext_end, z2 + pz * inner_offset + uz * ext_end)
        p4 = QPointF(x2 + px * outer_offset + ux * ext_end, z2 + pz * outer_offset + uz * ext_end)

        return (p1, p2, p3, p4)

    def boundingRect(self) -> QRectF:
        geom = self._get_geometry()
        if not geom:
            return QRectF()
        p1, p2, p3, p4 = geom
        min_x = min(p1.x(), p2.x(), p3.x(), p4.x()) - 100
        max_x = max(p1.x(), p2.x(), p3.x(), p4.x()) + 100
        min_y = min(p1.y(), p2.y(), p3.y(), p4.y()) - 100
        max_y = max(p1.y(), p2.y(), p3.y(), p4.y()) + 100
        return QRectF(min_x, min_y, max_x - min_x, max_y - min_y)

    def shape(self) -> QPainterPath:
        # Minimal shape for layers - they're visual only
        # Mouse events should pass to parent wall
        geom = self._get_geometry()
        if not geom:
            return QPainterPath()
        p1, p2, p3, p4 = geom
        path = QPainterPath()
        path.moveTo(p1)
        path.lineTo(p2)
        path.lineTo(p3)
        path.lineTo(p4)
        path.closeSubpath()
        return path

    def paint(self, painter: QPainter, option, widget):
        geom = self._get_geometry()
        if not geom:
            return

        p1, p2, p3, p4 = geom

        path = QPainterPath()
        path.moveTo(p1)
        path.lineTo(p2)
        path.lineTo(p3)
        path.lineTo(p4)
        path.closeSubpath()

        painter.fillPath(path, QBrush(self._fill_color))

        # Edge lines
        pen = QPen(Qt.GlobalColor.darkGray)
        pen.setWidth(1)
        painter.setPen(pen)
        painter.drawPath(path)

        # Selection highlight
        if self.isSelected():
            pen = QPen(self._selection_color)
            pen.setWidth(3)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)

    def _create_grips(self):
        """Layer grips disabled - use wall grips instead."""
        pass

    def _remove_grips(self):
        """Layer grips disabled."""
        for grip in self._grips:
            if grip.scene():
                grip.scene().removeItem(grip)
        self._grips.clear()

    def hoverEnterEvent(self, event):
        """Forward hover to parent wall to show grips."""
        if self.parent_wall_item:
            # Show grips on parent wall when hovering any layer
            if not self.parent_wall_item._grips:
                self.parent_wall_item._create_grips()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        """Check if we should hide parent wall grips."""
        if self.parent_wall_item:
            # Only hide grips if parent wall isn't selected and no grip is being dragged
            if not self.parent_wall_item.isSelected():
                dragging = any(grip._dragging for grip in self.parent_wall_item._grips) if self.parent_wall_item._grips else False
                # Check if another layer of the same wall is being hovered
                other_layer_hovered = any(
                    layer.isUnderMouse() for layer in self.parent_wall_item._layer_items
                    if layer is not self
                )
                # Check if parent wall itself or a grip is under mouse
                parent_hovered = self.parent_wall_item.isUnderMouse()
                grip_hovered = any(grip.isUnderMouse() for grip in self.parent_wall_item._grips) if self.parent_wall_item._grips else False

                if not dragging and not other_layer_hovered and not parent_hovered and not grip_hovered:
                    self.parent_wall_item._remove_grips()
        super().hoverLeaveEvent(event)

    def itemChange(self, change, value):
        return super().itemChange(change, value)


class WallItem(QGraphicsItem):
    """Graphics item representing a wall."""

    def __init__(self, wall: Wall, thickness: float = 150, document=None, snap_manager=None, snap_indicator=None, config=None, parent=None):
        super().__init__(parent)
        self.wall = wall
        self.thickness = thickness
        self.document = document
        self.snap_manager = snap_manager
        self.snap_indicator = snap_indicator
        self.config = config
        self._selected = False

        # Layer items (for individual layer editing)
        self._layer_items: List[WallLayerItem] = []

        # Colors
        self._color_exterior = QColor("#e0e0e0")
        self._color_interior = QColor("#a0a0a0")
        self._color_wet = QColor("#8080ff")
        self._color_selection = QColor("#ffff00")
        self._color_hover = QColor("#80c0ff")  # Light blue hover highlight
        self._is_hovered = False

        # Grips
        self._grips: List[GripItem] = []

        # Undo tracking - stores wall state at drag start
        self._drag_old_start: Optional[tuple] = None
        self._drag_old_end: Optional[tuple] = None
        self._drag_grip_type: Optional[str] = None
        # Co-moved walls — other walls whose endpoint coincides with the
        # dragged grip, captured at drag start so they follow the move and
        # the corner stays attached. Format: list of dicts with wall_idx,
        # which_end ('start'|'end'), and pre-drag start/end tuples for undo.
        self._drag_connected: List[dict] = []

        # Enable selection
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setAcceptHoverEvents(True)

    def _create_grips(self):
        """Create grip items for this wall."""
        self._remove_grips()

        x1, z1 = self.wall.start[0], self.wall.start[2]
        x2, z2 = self.wall.end[0], self.wall.end[2]
        cx, cz = (x1 + x2) / 2, (z1 + z2) / 2

        wall_idx = self.wall.index

        # Start grip
        start_grip = GripItem('start', self, self._on_grip_moved,
                              self.snap_manager, self.snap_indicator, wall_idx, self.config,
                              on_drag_start=self._on_drag_start, on_drag_end=self._on_drag_end)
        start_grip.setPos(x1, z1)
        self.scene().addItem(start_grip)
        self._grips.append(start_grip)

        # End grip
        end_grip = GripItem('end', self, self._on_grip_moved,
                            self.snap_manager, self.snap_indicator, wall_idx, self.config,
                            on_drag_start=self._on_drag_start, on_drag_end=self._on_drag_end)
        end_grip.setPos(x2, z2)
        self.scene().addItem(end_grip)
        self._grips.append(end_grip)

        # Center grip
        center_grip = GripItem('center', self, self._on_grip_moved,
                               self.snap_manager, self.snap_indicator, wall_idx, self.config,
                               on_drag_start=self._on_drag_start, on_drag_end=self._on_drag_end)
        center_grip.setPos(cx, cz)
        self.scene().addItem(center_grip)
        self._grips.append(center_grip)

    def _remove_grips(self):
        """Remove all grips."""
        for grip in self._grips:
            if grip.scene():
                grip.scene().removeItem(grip)
        self._grips.clear()

    def create_layer_items(self, scene):
        """Create individual WallLayerItem for each layer of this wall."""
        self.remove_layer_items()

        wall_type = None
        if self.document and self.wall.wall_type:
            wall_type = self.document.get_wall_type(self.wall.wall_type)

        if not wall_type or not wall_type.layers:
            return

        total_thickness = wall_type.total_thickness
        current_offset = -total_thickness / 2

        for i, layer in enumerate(wall_type.layers):
            layer_center = current_offset + layer.thickness / 2
            layer_item = WallLayerItem(
                self.wall, i, layer, layer_center,
                document=self.document, parent_wall_item=self
            )
            scene.addItem(layer_item)
            self._layer_items.append(layer_item)
            current_offset += layer.thickness

    def remove_layer_items(self):
        """Remove all layer items and clean up memory."""
        for item in self._layer_items:
            if hasattr(item, '_grips') and item._grips:
                item._remove_grips()
            if item.scene():
                item.scene().removeItem(item)
        self._layer_items.clear()

    def update_layer_items(self):
        """Update layer item positions after wall geometry changes."""
        for layer_item in self._layer_items:
            layer_item.prepareGeometryChange()
            layer_item.update()

    def _on_drag_start(self, grip_type: str):
        """Called when grip drag starts - store original positions for undo."""
        self._drag_old_start = self.wall.start
        self._drag_old_end = self.wall.end
        self._drag_grip_type = grip_type

        # Find OTHER walls whose endpoint coincides with the dragged grip,
        # so they can follow the corner and stay attached. Only meaningful
        # for endpoint grips ('start' / 'end') — center drags translate the
        # whole wall and would cascade unhelpfully through the network.
        self._drag_connected = []
        if grip_type not in ('start', 'end') or self.document is None:
            return
        if grip_type == 'start':
            ax, az = self.wall.start[0], self.wall.start[2]
        else:
            ax, az = self.wall.end[0], self.wall.end[2]
        tol = 50.0  # mm — well below any realistic wall thickness
        for w in self.document.walls:
            if w.index == self.wall.index:
                continue
            if abs(w.start[0] - ax) < tol and abs(w.start[2] - az) < tol:
                self._drag_connected.append({
                    'wall_idx': w.index, 'which_end': 'start',
                    'old_start': w.start, 'old_end': w.end,
                })
            if abs(w.end[0] - ax) < tol and abs(w.end[2] - az) < tol:
                self._drag_connected.append({
                    'wall_idx': w.index, 'which_end': 'end',
                    'old_start': w.start, 'old_end': w.end,
                })

    def _on_drag_end(self, grip_type: str):
        """Called when grip drag ends - create undo command(s)."""
        if self._drag_old_start is None or self._drag_old_end is None:
            return

        # Check if position actually changed
        if (self._drag_old_start == self.wall.start and
            self._drag_old_end == self.wall.end):
            self._drag_connected = []
            return  # No change, no undo needed

        # Create undo command(s). When the corner had connected walls, group
        # them into a single macro so one Ctrl+Z undoes the whole corner move.
        if self.document:
            from core.commands import MoveWallCommand
            using_macro = bool(self._drag_connected)
            if using_macro:
                self.document.undo_stack.beginMacro("Move Corner")
            try:
                cmd = MoveWallCommand(
                    self.document,
                    self.wall.index,
                    grip_type,
                    self._drag_old_start,
                    self._drag_old_end,
                    self.wall.start,
                    self.wall.end
                )
                self.document.undo_stack.push(cmd)

                walls = self.document._walls
                for conn in self._drag_connected:
                    idx = conn['wall_idx']
                    if not (0 <= idx < len(walls)):
                        continue
                    w = walls[idx]
                    # Skip if nothing changed (defensive — shouldn't normally hit)
                    if w.start == conn['old_start'] and w.end == conn['old_end']:
                        continue
                    self.document.undo_stack.push(MoveWallCommand(
                        self.document,
                        idx,
                        conn['which_end'],
                        conn['old_start'],
                        conn['old_end'],
                        w.start,
                        w.end,
                    ))
            finally:
                if using_macro:
                    self.document.undo_stack.endMacro()

            # Notify 3D viewport of change
            self.document.document_changed.emit()

        # Clear tracking
        self._drag_old_start = None
        self._drag_old_end = None
        self._drag_grip_type = None
        self._drag_connected = []

    def _on_grip_moved(self, grip_type: str, new_pos: QPointF):
        """Handle grip movement (visual feedback, no undo yet)."""
        x, z = new_pos.x(), new_pos.y()

        if grip_type == 'start':
            new_start = (x, self.wall.start[1], z)
            if self.document:
                # Use direct modify (no undo) during drag
                self.document.modify_wall(self.wall.index, start=new_start)
                self._propagate_endpoint(x, z)
        elif grip_type == 'end':
            new_end = (x, self.wall.end[1], z)
            if self.document:
                self.document.modify_wall(self.wall.index, end=new_end)
                self._propagate_endpoint(x, z)
        elif grip_type == 'center':
            # Move both endpoints by delta
            old_cx = (self.wall.start[0] + self.wall.end[0]) / 2
            old_cz = (self.wall.start[2] + self.wall.end[2]) / 2
            dx = x - old_cx
            dz = z - old_cz
            new_start = (self.wall.start[0] + dx, self.wall.start[1], self.wall.start[2] + dz)
            new_end = (self.wall.end[0] + dx, self.wall.end[1], self.wall.end[2] + dz)
            if self.document:
                self.document.modify_wall(self.wall.index, start=new_start, end=new_end)

        self.update()

    def _propagate_endpoint(self, x: float, z: float):
        """Drag the matching endpoint of every co-moved wall to (x, z) so the
        corner stays welded together as the grip moves."""
        if not self._drag_connected or self.document is None:
            return
        walls = self.document._walls
        for conn in self._drag_connected:
            idx = conn['wall_idx']
            if not (0 <= idx < len(walls)):
                continue
            w = walls[idx]
            if conn['which_end'] == 'start':
                self.document.modify_wall(idx, start=(x, w.start[1], z))
            else:
                self.document.modify_wall(idx, end=(x, w.end[1], z))

    def hoverEnterEvent(self, event):
        """Show grips and highlight when hovering over wall."""
        self._is_hovered = True
        if not self._grips:  # Only create if not already showing
            self._create_grips()
        # Force immediate repaint
        if self.scene():
            self.scene().update(self.boundingRect())
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        """Hide grips and highlight when leaving wall (unless selected, dragging, or hovering layer)."""
        self._is_hovered = False
        # Force immediate repaint
        if self.scene():
            self.scene().update(self.boundingRect())
        # Don't remove grips if any grip is being dragged
        dragging = any(grip._dragging for grip in self._grips) if self._grips else False
        # Check if any layer is currently being hovered
        layer_hovered = any(layer.isUnderMouse() for layer in self._layer_items) if self._layer_items else False
        if not self.isSelected() and not dragging and not layer_hovered:
            self._remove_grips()
        super().hoverLeaveEvent(event)

    def itemChange(self, change, value):
        """Handle selection changes to show/hide grips."""
        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            if value:
                # Selected - ensure grips are visible
                if not self._grips:
                    self._create_grips()
            else:
                # Deselected - remove grips (hover will recreate if still hovering)
                self._remove_grips()
        return super().itemChange(change, value)

    HIT_MARGIN = 400  # mm - extra clickable area around wall

    def _get_total_thickness(self) -> float:
        """Get total wall thickness including all layers."""
        if self.document and self.wall.wall_type:
            wall_type = self.document.get_wall_type(self.wall.wall_type)
            if wall_type:
                return wall_type.total_thickness
        return self.thickness

    def boundingRect(self) -> QRectF:
        """Return bounding rectangle."""
        margin = max(self.HIT_MARGIN, self._get_total_thickness() / 2 + 50)
        x1, z1 = self.wall.start[0], self.wall.start[2]
        x2, z2 = self.wall.end[0], self.wall.end[2]

        return QRectF(
            min(x1, x2) - margin,
            min(z1, z2) - margin,
            abs(x2 - x1) + margin * 2,
            abs(z2 - z1) + margin * 2
        )

    def shape(self) -> QPainterPath:
        """Return larger shape for easier clicking."""
        x1, z1 = self.wall.start[0], self.wall.start[2]
        x2, z2 = self.wall.end[0], self.wall.end[2]

        dx = x2 - x1
        dz = z2 - z1
        length = (dx**2 + dz**2) ** 0.5

        if length < 1:
            # Very short wall - use a circle for hit area
            path = QPainterPath()
            path.addEllipse(QPointF(x1, z1), self.HIT_MARGIN, self.HIT_MARGIN)
            return path

        # Perpendicular unit vector
        px = -dz / length
        pz = dx / length

        # Use larger hit margin for clickable area
        half_hit = max(self.HIT_MARGIN, self._get_total_thickness() / 2 + 100)

        # Hit area polygon (wider than visual)
        p1 = QPointF(x1 + px * half_hit, z1 + pz * half_hit)
        p2 = QPointF(x1 - px * half_hit, z1 - pz * half_hit)
        p3 = QPointF(x2 - px * half_hit, z2 - pz * half_hit)
        p4 = QPointF(x2 + px * half_hit, z2 + pz * half_hit)

        path = QPainterPath()
        path.moveTo(p1)
        path.lineTo(p2)
        path.lineTo(p3)
        path.lineTo(p4)
        path.closeSubpath()
        return path

    def _get_butt_joint_points(self, my_endpoint: str, other_wall, other_endpoint: str,
                                 layer_outer_offset: float, layer_inner_offset: float,
                                 total_thickness: float) -> Tuple[QPointF, QPointF]:
        """
        Calculate corner points for a layer using butt joint (realistic construction).

        The secondary wall (this wall if other has lower index) butts into the primary wall's face.
        Primary wall continues with square cut, secondary wall terminates at primary's face.

        Args:
            my_endpoint: 'start' or 'end' of this wall
            other_wall: The connected wall
            other_endpoint: 'start' or 'end' of the other wall
            layer_outer_offset: Distance from wall centerline to layer outer edge
            layer_inner_offset: Distance from wall centerline to layer inner edge
            total_thickness: Total wall thickness

        Returns:
            (outer_point, inner_point) or None if this wall is primary (no change needed)
        """
        # Determine which wall is primary (continues through) vs secondary (butts in)
        # Lower index = primary, or if same type, longer wall = primary
        i_am_primary = self.wall.index < other_wall.index

        if i_am_primary:
            # I'm primary - my layers continue with square cut, no modification needed
            return None

        # I'm secondary - my layers butt into the primary wall's face

        # Get my wall geometry
        x1, z1 = self.wall.start[0], self.wall.start[2]
        x2, z2 = self.wall.end[0], self.wall.end[2]
        dx = x2 - x1
        dz = z2 - z1
        length = math.sqrt(dx**2 + dz**2)
        if length < 1:
            return None

        # My unit vectors
        ux, uz = dx / length, dz / length  # Along wall
        px, pz = -uz, ux  # Perpendicular

        # Get primary (other) wall geometry
        ox1, oz1 = other_wall.start[0], other_wall.start[2]
        ox2, oz2 = other_wall.end[0], other_wall.end[2]
        odx = ox2 - ox1
        odz = oz2 - oz1
        olength = math.sqrt(odx**2 + odz**2)
        if olength < 1:
            return None

        # Primary wall perpendicular (its face direction)
        opx, opz = -odz / olength, odx / olength

        # Get primary wall's thickness
        other_wall_type = None
        if self.document and other_wall.wall_type:
            other_wall_type = self.document.get_wall_type(other_wall.wall_type)
        other_thickness = other_wall_type.total_thickness if other_wall_type else total_thickness
        other_half = other_thickness / 2

        # Corner point (where wall centerlines meet)
        if my_endpoint == 'start':
            corner_x, corner_z = x1, z1
        else:
            corner_x, corner_z = x2, z2

        # Determine which face of the primary wall we butt into
        # Check which side of the primary wall our wall is approaching from
        # by seeing which direction we're coming from relative to primary wall's perpendicular

        # Direction we're approaching the corner from
        if my_endpoint == 'start':
            approach_x, approach_z = -ux, -uz  # Coming from our interior toward start
        else:
            approach_x, approach_z = ux, uz  # Coming from our interior toward end

        # Dot product with primary's perpendicular tells us which side
        dot = approach_x * opx + approach_z * opz

        # The face we butt into
        if dot > 0:
            # We approach from the positive perp side - butt into negative face
            face_offset = -other_half
        else:
            # We approach from negative perp side - butt into positive face
            face_offset = other_half

        # The primary wall's face line passes through:
        face_x = corner_x + opx * face_offset
        face_z = corner_z + opz * face_offset

        # Primary wall direction
        oux, ouz = odx / olength, odz / olength

        # Find where my layer edges intersect the primary wall's face
        # Face line: (face_x, face_z) + t * (oux, ouz)
        # My outer edge: corner + px*layer_outer_offset, going in direction (ux, uz)
        # My inner edge: corner + px*layer_inner_offset, going in direction (ux, uz)

        # For outer edge intersection
        outer_start_x = corner_x + px * layer_outer_offset
        outer_start_z = corner_z + pz * layer_outer_offset

        # For inner edge intersection
        inner_start_x = corner_x + px * layer_inner_offset
        inner_start_z = corner_z + pz * layer_inner_offset

        # Find intersection with face line
        # Line: start + t * (ux, uz) intersects face_pt + s * (oux, ouz)
        denom = ux * ouz - uz * oux
        if abs(denom) < 0.001:
            # Parallel walls - shouldn't happen at a corner, but handle gracefully
            return None

        # Outer edge intersection
        t_outer = ((face_x - outer_start_x) * ouz - (face_z - outer_start_z) * oux) / denom
        outer_pt = QPointF(outer_start_x + t_outer * ux, outer_start_z + t_outer * uz)

        # Inner edge intersection
        t_inner = ((face_x - inner_start_x) * ouz - (face_z - inner_start_z) * oux) / denom
        inner_pt = QPointF(inner_start_x + t_inner * ux, inner_start_z + t_inner * uz)

        return (outer_pt, inner_pt)

    def paint(self, painter: QPainter, option, widget):
        """Paint the wall with layers if wall type is defined."""
        # Get wall endpoints
        x1, z1 = self.wall.start[0], self.wall.start[2]
        x2, z2 = self.wall.end[0], self.wall.end[2]

        # Calculate perpendicular offset for thickness
        dx = x2 - x1
        dz = z2 - z1
        length = (dx**2 + dz**2) ** 0.5
        if length == 0:
            return

        # Unit vectors
        ux, uz = dx / length, dz / length  # Along wall
        px, pz = -dz / length, dx / length  # Perpendicular

        # Get wall type for layers
        wall_type = None
        if self.document and self.wall.wall_type:
            wall_type = self.document.get_wall_type(self.wall.wall_type)

        # Find connected walls at each endpoint for corner processing
        start_connections = []
        end_connections = []
        if self.document:
            # Check start endpoint
            start_walls = self.document.get_walls_at_point(x1, z1, tolerance=50)
            for wall_idx, endpoint in start_walls:
                if wall_idx != self.wall.index:
                    other_wall = self.document.walls[wall_idx]
                    start_connections.append((other_wall, endpoint))

            # Check end endpoint
            end_walls = self.document.get_walls_at_point(x2, z2, tolerance=50)
            for wall_idx, endpoint in end_walls:
                if wall_idx != self.wall.index:
                    other_wall = self.document.walls[wall_idx]
                    end_connections.append((other_wall, endpoint))

        if wall_type and wall_type.layers and self._layer_items:
            # Layers are drawn by individual WallLayerItem objects
            # WallItem only draws selection highlight (below)
            pass
        elif wall_type and wall_type.layers:
            # Fallback: Draw layers directly (shouldn't happen normally)
            total_thickness = wall_type.total_thickness
            current_offset = -total_thickness / 2

            for layer in wall_type.layers:
                layer_start = current_offset
                layer_end = current_offset + layer.thickness

                p1 = QPointF(x1 + px * layer_end, z1 + pz * layer_end)
                p2 = QPointF(x1 + px * layer_start, z1 + pz * layer_start)
                p3 = QPointF(x2 + px * layer_start, z2 + pz * layer_start)
                p4 = QPointF(x2 + px * layer_end, z2 + pz * layer_end)

                path = QPainterPath()
                path.moveTo(p1)
                path.lineTo(p2)
                path.lineTo(p3)
                path.lineTo(p4)
                path.closeSubpath()

                r, g, b, a = layer.color
                r, g, b, a = max(0, min(1, r)), max(0, min(1, g)), max(0, min(1, b)), max(0, min(1, a))
                fill_color = QColor(int(r * 255), int(g * 255), int(b * 255), int(a * 255))
                painter.fillPath(path, QBrush(fill_color))

                pen = QPen(Qt.GlobalColor.darkGray)
                pen.setWidth(1)
                painter.setPen(pen)
                painter.drawPath(path)

                current_offset = layer_end
        else:
            # Fallback: simple single-color wall
            half_thick = self.thickness / 2
            p1 = QPointF(x1 + px * half_thick, z1 + pz * half_thick)
            p2 = QPointF(x1 - px * half_thick, z1 - pz * half_thick)
            p3 = QPointF(x2 - px * half_thick, z2 - pz * half_thick)
            p4 = QPointF(x2 + px * half_thick, z2 + pz * half_thick)

            path = QPainterPath()
            path.moveTo(p1)
            path.lineTo(p2)
            path.lineTo(p3)
            path.lineTo(p4)
            path.closeSubpath()

            # Choose color based on category
            if self.wall.category == "exterior":
                fill_color = self._color_exterior
            elif self.wall.category == "wet_wall":
                fill_color = self._color_wet
            else:
                fill_color = self._color_interior

            painter.fillPath(path, QBrush(fill_color))

            pen = QPen(Qt.GlobalColor.black)
            pen.setWidth(2)
            painter.setPen(pen)
            painter.drawPath(path)

        # Draw hover highlight (clean cyan outline)
        if self._is_hovered and not self.isSelected():
            total_thick = wall_type.total_thickness if wall_type else self.thickness
            half = total_thick / 2 + 60  # Slight margin around wall
            p1 = QPointF(x1 + px * half, z1 + pz * half)
            p2 = QPointF(x1 - px * half, z1 - pz * half)
            p3 = QPointF(x2 - px * half, z2 - pz * half)
            p4 = QPointF(x2 + px * half, z2 + pz * half)

            hover_path = QPainterPath()
            hover_path.moveTo(p1)
            hover_path.lineTo(p2)
            hover_path.lineTo(p3)
            hover_path.lineTo(p4)
            hover_path.closeSubpath()

            # Clean cyan outline, no fill
            pen = QPen(QColor(0, 200, 255))  # Cyan
            pen.setWidth(4)
            pen.setStyle(Qt.PenStyle.SolidLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(hover_path)

        # Draw selection highlight
        if self.isSelected():
            # Draw outer boundary highlight
            total_thick = wall_type.total_thickness if wall_type else self.thickness
            half = total_thick / 2
            p1 = QPointF(x1 + px * half, z1 + pz * half)
            p2 = QPointF(x1 - px * half, z1 - pz * half)
            p3 = QPointF(x2 - px * half, z2 - pz * half)
            p4 = QPointF(x2 + px * half, z2 + pz * half)

            sel_path = QPainterPath()
            sel_path.moveTo(p1)
            sel_path.lineTo(p2)
            sel_path.lineTo(p3)
            sel_path.lineTo(p4)
            sel_path.closeSubpath()

            pen = QPen(self._color_selection)
            pen.setWidth(3)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(sel_path)

        # Draw pin indicator if pinned
        if self.wall.is_pinned:
            self._draw_pin_indicator(painter, x1, z1, x2, z2)

    def _draw_pin_indicator(self, painter: QPainter, x1: float, z1: float, x2: float, z2: float):
        """Draw a pin icon at the center of the wall."""
        # Calculate wall center
        cx = (x1 + x2) / 2
        cz = (z1 + z2) / 2

        # Draw pin icon (red circle with white dot)
        painter.save()
        painter.setPen(QPen(QColor(255, 100, 100), 30))
        painter.setBrush(QBrush(QColor(255, 100, 100, 180)))
        painter.drawEllipse(QPointF(cx, cz), 120, 120)
        painter.setPen(QPen(Qt.GlobalColor.white, 40))
        painter.drawPoint(QPointF(cx, cz))
        painter.restore()


class DoorItem(QGraphicsItem):
    """Graphics item representing a door."""

    def __init__(self, door: Door, walls: List[Wall], document=None, parent=None):
        super().__init__(parent)
        self.door = door
        self.walls = walls
        self.document = document
        self._wall: Optional[Wall] = None
        self._grips: List[GripItem] = []
        self._is_hovered = False
        self._color_hover = QColor("#80c0ff")

        if 0 <= door.wall_index < len(walls):
            self._wall = walls[door.wall_index]

        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setAcceptHoverEvents(True)

    def hoverEnterEvent(self, event):
        self._is_hovered = True
        if self.scene():
            self.scene().update(self.boundingRect())
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self._is_hovered = False
        if self.scene():
            self.scene().update(self.boundingRect())
        super().hoverLeaveEvent(event)

    def _create_grips(self):
        """Create center grip for moving door along wall."""
        self._remove_grips()
        pos = self._get_position()

        grip = GripItem('center', self, self._on_grip_moved)
        grip.setPos(pos)
        self.scene().addItem(grip)
        self._grips.append(grip)

    def _remove_grips(self):
        for grip in self._grips:
            if grip.scene():
                grip.scene().removeItem(grip)
        self._grips.clear()

    def _on_grip_moved(self, grip_type: str, new_pos: QPointF):
        """Move door along wall based on grip position."""
        if not self._wall:
            return

        # Project new position onto wall line
        x1, z1 = self._wall.start[0], self._wall.start[2]
        x2, z2 = self._wall.end[0], self._wall.end[2]
        wall_len = self._wall.length

        # Vector from wall start to new pos
        vx, vz = new_pos.x() - x1, new_pos.y() - z1
        # Wall direction
        dx, dz = x2 - x1, z2 - z1

        # Project onto wall (dot product / length)
        new_offset = (vx * dx + vz * dz) / wall_len if wall_len > 0 else 0
        new_offset = max(0, min(wall_len, new_offset))

        if self.document:
            self.document.modify_door(self.door.index, offset=new_offset)
        self.update()

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            if value:
                self._create_grips()
            else:
                self._remove_grips()
        return super().itemChange(change, value)

    def boundingRect(self) -> QRectF:
        """Return bounding rectangle."""
        if not self._wall:
            return QRectF()

        pos = self._get_position()
        # Make bounding rect large enough for door swing arc
        size = self.door.width + 100
        return QRectF(pos.x() - size, pos.y() - size, size * 2, size * 2)

    def shape(self) -> QPainterPath:
        """Return shape for hit testing - larger clickable area."""
        path = QPainterPath()
        if not self._wall:
            return path

        pos = self._get_position()
        # Create a larger clickable area around the door
        click_size = max(self.door.width / 2, 300)
        path.addEllipse(pos, click_size, click_size)
        return path

    def _get_position(self) -> QPointF:
        """Calculate door position along wall."""
        if not self._wall:
            return QPointF(0, 0)

        x1, z1 = self._wall.start[0], self._wall.start[2]
        x2, z2 = self._wall.end[0], self._wall.end[2]

        # Parametric position along wall
        t = self.door.offset / self._wall.length if self._wall.length > 0 else 0
        x = x1 + (x2 - x1) * t
        z = z1 + (z2 - z1) * t

        return QPointF(x, z)

    def paint(self, painter: QPainter, option, widget):
        """Paint the door."""
        if not self._wall:
            return

        pos = self._get_position()

        # Calculate wall direction
        dx = self._wall.end[0] - self._wall.start[0]
        dz = self._wall.end[2] - self._wall.start[2]
        length = (dx**2 + dz**2) ** 0.5
        if length == 0:
            return

        # Unit vectors
        ux, uz = dx / length, dz / length  # Along wall
        px, pz = -uz, ux  # Perpendicular

        # Door opening (gap in wall)
        half_width = self.door.width / 2

        # Draw door opening as white rectangle (gap)
        pen = QPen(QColor("#1a1a2e"))  # Background color
        pen.setWidth(160)  # Wall thickness
        painter.setPen(pen)
        painter.drawLine(
            QPointF(pos.x() - ux * half_width, pos.y() - uz * half_width),
            QPointF(pos.x() + ux * half_width, pos.y() + uz * half_width)
        )

        # Draw door swing symbol
        # 4 configurations: left_in, left_out, right_in, right_out
        # Symbol: hinge at one edge, panel line perpendicular to wall,
        # arc from closed position sweeping to open position

        import math

        pen = QPen(Qt.GlobalColor.cyan if self.isSelected() else Qt.GlobalColor.darkGray)
        pen.setWidth(30)
        painter.setPen(pen)

        # Parse swing setting
        swing = self.door.swing.lower() if self.door.swing else "left_in"
        is_left = "left" in swing
        is_in = "in" in swing

        # Calculate hinge and free edge positions in world coordinates
        # Hinge is at one edge of opening, free edge at other edge when closed
        if is_left:
            # Hinge at "start" side of opening (negative offset direction)
            hinge_x = pos.x() - ux * half_width
            hinge_y = pos.y() - uz * half_width
            free_closed_x = pos.x() + ux * half_width
            free_closed_y = pos.y() + uz * half_width
        else:
            # Hinge at "end" side of opening (positive offset direction)
            hinge_x = pos.x() + ux * half_width
            hinge_y = pos.y() + uz * half_width
            free_closed_x = pos.x() - ux * half_width
            free_closed_y = pos.y() - uz * half_width

        # Perpendicular direction for swing (px, pz = -uz, ux)
        # "in" swings in +perpendicular direction, "out" in -perpendicular
        swing_mult = 1 if is_in else -1

        # Free edge when door is open (90 degrees from closed)
        # Panel length = door width = opening width
        free_open_x = hinge_x + px * self.door.width * swing_mult
        free_open_y = hinge_y + pz * self.door.width * swing_mult

        # Draw door panel line from hinge to open free edge position
        painter.drawLine(QPointF(hinge_x, hinge_y), QPointF(free_open_x, free_open_y))

        # Draw swing arc from closed position to open position
        # Use QPainterPath for more control
        path = QPainterPath()
        path.moveTo(free_closed_x, free_closed_y)

        # Arc needs control point - approximate with quadratic bezier
        # Control point is at the corner of the swing rectangle
        ctrl_x = hinge_x + ux * self.door.width * (1 if is_left else -1) * 0.55 + px * self.door.width * swing_mult * 0.55
        ctrl_y = hinge_y + uz * self.door.width * (1 if is_left else -1) * 0.55 + pz * self.door.width * swing_mult * 0.55

        # Actually, let's just draw a proper arc using multiple line segments
        num_segments = 16
        for i in range(1, num_segments + 1):
            t = i / num_segments
            # Interpolate angle from 0 (closed) to 90 degrees (open)
            angle = t * math.pi / 2

            # Position along arc: rotate from closed position around hinge
            if is_left:
                # Rotate closed_to_hinge vector by angle
                dx_ch = free_closed_x - hinge_x
                dy_ch = free_closed_y - hinge_y
            else:
                dx_ch = free_closed_x - hinge_x
                dy_ch = free_closed_y - hinge_y

            # Rotation matrix (swing direction affects rotation sign)
            cos_a = math.cos(angle * swing_mult)
            sin_a = math.sin(angle * swing_mult)

            # For perpendicular calculation, we need to rotate in the plane perpendicular to wall
            # The perpendicular axis is (px, pz), wall axis is (ux, uz)
            # Rotate the vector from hinge to closed free edge
            # New position = hinge + rotated(closed_to_hinge)

            # Using 2D rotation in the wall's local coordinate system
            # Project onto wall and perp axes
            wall_component = dx_ch * ux + dy_ch * uz  # Component along wall
            perp_component = dx_ch * px + dy_ch * pz  # Component perpendicular

            # Rotate in wall-perp plane
            new_wall = wall_component * cos_a - perp_component * sin_a * swing_mult
            new_perp = wall_component * sin_a * swing_mult + perp_component * cos_a

            # Convert back to world coordinates
            arc_x = hinge_x + new_wall * ux + new_perp * px
            arc_y = hinge_y + new_wall * uz + new_perp * pz

            path.lineTo(arc_x, arc_y)

        painter.drawPath(path)

        # Draw hover highlight (clean cyan circle)
        if self._is_hovered and not self.isSelected():
            pen = QPen(QColor(0, 200, 255))  # Cyan
            pen.setWidth(4)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(pos, half_width + 80, half_width + 80)

        # Draw pin indicator if pinned
        if self.door.is_pinned:
            painter.save()
            painter.setPen(QPen(QColor(255, 100, 100), 30))
            painter.setBrush(QBrush(QColor(255, 100, 100, 180)))
            painter.drawEllipse(pos, 100, 100)
            painter.setPen(QPen(Qt.GlobalColor.white, 40))
            painter.drawPoint(pos)
            painter.restore()


class WindowItem(QGraphicsItem):
    """Graphics item representing a window."""

    def __init__(self, window: Window, walls: List[Wall], document=None, parent=None):
        super().__init__(parent)
        self.window = window
        self.walls = walls
        self.document = document
        self._wall: Optional[Wall] = None
        self._grips: List[GripItem] = []
        self._is_hovered = False
        self._color_hover = QColor("#80c0ff")

        if 0 <= window.wall_index < len(walls):
            self._wall = walls[window.wall_index]

        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setAcceptHoverEvents(True)

    def hoverEnterEvent(self, event):
        self._is_hovered = True
        if self.scene():
            self.scene().update(self.boundingRect())
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self._is_hovered = False
        if self.scene():
            self.scene().update(self.boundingRect())
        super().hoverLeaveEvent(event)

    def _create_grips(self):
        """Create center grip for moving window along wall."""
        self._remove_grips()
        pos = self._get_position()

        grip = GripItem('center', self, self._on_grip_moved)
        grip.setPos(pos)
        self.scene().addItem(grip)
        self._grips.append(grip)

    def _remove_grips(self):
        for grip in self._grips:
            if grip.scene():
                grip.scene().removeItem(grip)
        self._grips.clear()

    def _on_grip_moved(self, grip_type: str, new_pos: QPointF):
        """Move window along wall based on grip position."""
        if not self._wall:
            return

        x1, z1 = self._wall.start[0], self._wall.start[2]
        x2, z2 = self._wall.end[0], self._wall.end[2]
        wall_len = self._wall.length

        vx, vz = new_pos.x() - x1, new_pos.y() - z1
        dx, dz = x2 - x1, z2 - z1

        new_offset = (vx * dx + vz * dz) / wall_len if wall_len > 0 else 0
        new_offset = max(0, min(wall_len, new_offset))

        if self.document:
            self.document.modify_window(self.window.index, offset=new_offset)
        self.update()

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            if value:
                self._create_grips()
            else:
                self._remove_grips()
        return super().itemChange(change, value)

    def boundingRect(self) -> QRectF:
        """Return bounding rectangle."""
        if not self._wall:
            return QRectF()

        pos = self._get_position()
        margin = 200
        return QRectF(pos.x() - margin, pos.y() - margin, margin * 2, margin * 2)

    def _get_position(self) -> QPointF:
        """Calculate window position along wall."""
        if not self._wall:
            return QPointF(0, 0)

        x1, z1 = self._wall.start[0], self._wall.start[2]
        x2, z2 = self._wall.end[0], self._wall.end[2]

        t = self.window.offset / self._wall.length if self._wall.length > 0 else 0
        x = x1 + (x2 - x1) * t
        z = z1 + (z2 - z1) * t

        return QPointF(x, z)

    def paint(self, painter: QPainter, option, widget):
        """Paint the window."""
        if not self._wall:
            return

        pos = self._get_position()

        # Calculate wall direction
        dx = self._wall.end[0] - self._wall.start[0]
        dz = self._wall.end[2] - self._wall.start[2]
        length = (dx**2 + dz**2) ** 0.5
        if length == 0:
            return

        ux, uz = dx / length, dz / length
        px, pz = -uz, ux

        half_width = self.window.width / 2
        thickness = 80

        # Draw window opening (gap)
        pen = QPen(QColor("#1a1a2e"))
        pen.setWidth(160)
        painter.setPen(pen)
        painter.drawLine(
            QPointF(pos.x() - ux * half_width, pos.y() - uz * half_width),
            QPointF(pos.x() + ux * half_width, pos.y() + uz * half_width)
        )

        # Draw window frame (two parallel lines)
        pen = QPen(Qt.GlobalColor.cyan if self.isSelected() else QColor("#4080ff"))
        pen.setWidth(3)
        painter.setPen(pen)

        # Glass lines
        for side in [-1, 1]:
            offset = thickness * 0.3 * side
            p1 = QPointF(
                pos.x() - ux * half_width + px * offset,
                pos.y() - uz * half_width + pz * offset
            )
            p2 = QPointF(
                pos.x() + ux * half_width + px * offset,
                pos.y() + uz * half_width + pz * offset
            )
            painter.drawLine(p1, p2)

        # Draw hover highlight (clean cyan box around window)
        if self._is_hovered and not self.isSelected():
            pen = QPen(QColor(0, 200, 255))  # Cyan
            pen.setWidth(4)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            # Draw highlight box around window
            margin = 80
            hp1 = QPointF(pos.x() - ux * (half_width + margin) + px * margin,
                          pos.y() - uz * (half_width + margin) + pz * margin)
            hp2 = QPointF(pos.x() - ux * (half_width + margin) - px * margin,
                          pos.y() - uz * (half_width + margin) - pz * margin)
            hp3 = QPointF(pos.x() + ux * (half_width + margin) - px * margin,
                          pos.y() + uz * (half_width + margin) - pz * margin)
            hp4 = QPointF(pos.x() + ux * (half_width + margin) + px * margin,
                          pos.y() + uz * (half_width + margin) + pz * margin)
            hover_path = QPainterPath()
            hover_path.moveTo(hp1)
            hover_path.lineTo(hp2)
            hover_path.lineTo(hp3)
            hover_path.lineTo(hp4)
            hover_path.closeSubpath()
            painter.drawPath(hover_path)

        # Draw pin indicator if pinned
        if self.window.is_pinned:
            painter.save()
            painter.setPen(QPen(QColor(255, 100, 100), 30))
            painter.setBrush(QBrush(QColor(255, 100, 100, 180)))
            painter.drawEllipse(pos, 100, 100)
            painter.setPen(QPen(Qt.GlobalColor.white, 40))
            painter.drawPoint(pos)
            painter.restore()


class ReferencePlaneItem(QGraphicsItem):
    """Graphics item representing a reference plane (grid line)."""

    def __init__(self, plane, view=None, parent=None):
        super().__init__(parent)
        self.plane = plane
        self._view = view
        self.setZValue(5)  # Behind most elements but visible
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)

    def boundingRect(self) -> QRectF:
        """Return bounding rectangle - extends across entire view."""
        # Use a large extent for the infinite line
        extent = 100000  # 100 meters
        margin = 200

        if self.plane.is_vertical:
            return QRectF(self.plane.position - margin, -extent, margin * 2, extent * 2)
        else:  # Horizontal
            return QRectF(-extent, self.plane.position - margin, extent * 2, margin * 2)

    def paint(self, painter: QPainter, option, widget):
        """Paint the reference plane line."""
        # Only show at LOD 1 or 2
        if self._view and self._view.lod_level > 2:
            return

        extent = 100000  # Large extent for "infinite" line

        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Reference plane style - cyan dashed line
        color = QColor("#00AAAA")
        pen = QPen(color, 30)  # 30mm line
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)

        if self.plane.is_vertical:
            # Vertical line at X = position
            painter.drawLine(
                QPointF(self.plane.position, -extent),
                QPointF(self.plane.position, extent)
            )
        else:
            # Horizontal line at Z = position
            painter.drawLine(
                QPointF(-extent, self.plane.position),
                QPointF(extent, self.plane.position)
            )

        # Draw label
        label_size = 300
        label_offset = 100

        painter.setBrush(QBrush(color))
        painter.setPen(QPen(Qt.GlobalColor.white, 10))

        if self.plane.is_vertical:
            # Label at top of visible area
            label_y = -extent + 1000 if self._view else 0
            painter.drawEllipse(
                QPointF(self.plane.position, label_y),
                label_size, label_size
            )
            # Draw label text
            painter.setPen(QPen(Qt.GlobalColor.white))
            font = painter.font()
            font.setPixelSize(250)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(
                QRectF(self.plane.position - label_size,
                       label_y - label_size,
                       label_size * 2, label_size * 2),
                Qt.AlignmentFlag.AlignCenter,
                self.plane.label
            )
        else:
            # Label at left of visible area
            label_x = -extent + 1000 if self._view else 0
            painter.drawEllipse(
                QPointF(label_x, self.plane.position),
                label_size, label_size
            )
            # Draw label text
            painter.setPen(QPen(Qt.GlobalColor.white))
            font = painter.font()
            font.setPixelSize(250)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(
                QRectF(label_x - label_size,
                       self.plane.position - label_size,
                       label_size * 2, label_size * 2),
                Qt.AlignmentFlag.AlignCenter,
                self.plane.label
            )


class ConnectionItem(QGraphicsItem):
    """Graphics item representing a connection between two adjacent rooms."""

    # Connection type colors and styles - order matters for cycling
    CONNECTION_TYPES = ['wall', 'open', 'wet_wall', 'structural', 'mechanical', 'insulated']

    CONNECTION_STYLES = {
        'undefined': ("#888888", Qt.PenStyle.DashLine, "?", "Undefined - Click to set"),
        'wall': ("#666666", Qt.PenStyle.SolidLine, "W", "Standard Wall"),
        'open': ("#44DD44", Qt.PenStyle.DotLine, "O", "Open (No Wall)"),
        'wet_wall': ("#4488FF", Qt.PenStyle.SolidLine, "P", "Wet Wall (Plumbing)"),
        'structural': ("#FF4444", Qt.PenStyle.SolidLine, "S", "Structural Wall"),
        'mechanical': ("#FF8800", Qt.PenStyle.DashDotLine, "M", "Mechanical Wall"),
        'insulated': ("#AA44AA", Qt.PenStyle.SolidLine, "I", "Insulated Wall"),
    }

    def __init__(self, connection, document=None, view=None, parent=None):
        super().__init__(parent)
        self.connection = connection
        self.document = document
        self._view = view
        self.setZValue(50)  # Between rooms and UI elements
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton | Qt.MouseButton.RightButton)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)  # Allow selection
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def boundingRect(self) -> QRectF:
        """Return bounding rectangle of the connection line."""
        if not self.connection.shared_edge:
            return QRectF()

        p1, p2 = self.connection.shared_edge
        margin = 50
        x = min(p1[0], p2[0]) - margin
        y = min(p1[1], p2[1]) - margin
        w = abs(p2[0] - p1[0]) + margin * 2
        h = abs(p2[1] - p1[1]) + margin * 2
        return QRectF(x, y, max(w, 100), max(h, 100))

    def paint(self, painter: QPainter, option, widget):
        """Paint the connection line."""
        if not self.connection.shared_edge:
            return

        # Only show at LOD 1 (blob view)
        if self._view and self._view.lod_level != 1:
            return

        p1, p2 = self.connection.shared_edge

        # Get style for connection type (color, pen_style, letter, tooltip)
        style = self.CONNECTION_STYLES.get(
            self.connection.connection_type,
            self.CONNECTION_STYLES['undefined']
        )
        color_hex, pen_style, letter, tooltip = style

        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        is_selected = self.isSelected()

        # Draw selection highlight glow behind the line
        if is_selected:
            glow_pen = QPen(QColor(0, 150, 255, 100), 160)  # Wide blue glow
            glow_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(glow_pen)
            painter.drawLine(QPointF(p1[0], p1[1]), QPointF(p2[0], p2[1]))

        # Draw the shared edge line
        color = QColor(color_hex)
        line_width = 100 if is_selected else 80  # Thicker when selected
        pen = QPen(color, line_width)
        pen.setStyle(pen_style)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLine(QPointF(p1[0], p1[1]), QPointF(p2[0], p2[1]))

        # Draw connection type indicator at midpoint
        mid_x = (p1[0] + p2[0]) / 2
        mid_y = (p1[1] + p2[1]) / 2

        # Draw selection ring behind circle
        if is_selected:
            painter.setPen(QPen(QColor(0, 150, 255), 30))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPointF(mid_x, mid_y), 130, 130)

        # Draw a small circle at midpoint
        painter.setBrush(QBrush(color))
        painter.setPen(QPen(Qt.GlobalColor.white, 20))
        painter.drawEllipse(QPointF(mid_x, mid_y), 100, 100)

        # Draw connection type icon/letter
        painter.setPen(QPen(Qt.GlobalColor.white))
        font = painter.font()
        font.setPixelSize(120)
        font.setBold(True)
        painter.setFont(font)

        # Draw the letter from style
        painter.drawText(
            QRectF(mid_x - 60, mid_y - 60, 120, 120),
            Qt.AlignmentFlag.AlignCenter,
            letter
        )

    def mousePressEvent(self, event):
        """Handle mouse clicks to change connection type."""
        if event.button() == Qt.MouseButton.LeftButton:
            # Left click cycles through types
            self.setSelected(True)  # Select on click
            self._cycle_connection_type()
            event.accept()
        elif event.button() == Qt.MouseButton.RightButton:
            # Right click selects and shows context menu
            # Clear other selections first
            if self.scene():
                self.scene().clearSelection()
            self.setSelected(True)  # Select this connection
            event.accept()
        else:
            super().mousePressEvent(event)

    def contextMenuEvent(self, event):
        """Show context menu for connection type selection."""
        from PyQt6.QtWidgets import QMenu
        from PyQt6.QtCore import QPoint

        try:
            menu = QMenu()
            current_type = self.connection.connection_type or 'undefined'

            # Add connection type options
            for conn_type in self.CONNECTION_TYPES:
                style = self.CONNECTION_STYLES.get(conn_type, self.CONNECTION_STYLES['wall'])
                color_hex, pen_style, letter, tooltip = style

                action = menu.addAction(f"[{letter}] {tooltip}")
                action.setCheckable(True)
                action.setChecked(conn_type == current_type)
                action.setData(conn_type)

            # Add undefined option
            menu.addSeparator()
            undef_style = self.CONNECTION_STYLES['undefined']
            undef_action = menu.addAction(f"[{undef_style[2]}] {undef_style[3]}")
            undef_action.setCheckable(True)
            undef_action.setChecked(current_type == 'undefined')
            undef_action.setData('undefined')

            # Show menu and handle selection
            screen_pos = event.screenPos()
            if hasattr(screen_pos, 'toPoint'):
                screen_pos = screen_pos.toPoint()

            action = menu.exec(screen_pos)
            if action:
                new_type = action.data()
                self._set_connection_type(new_type)
        except Exception as e:
            print(f"[ConnectionItem] Context menu error: {e}", flush=True)

    def _cycle_connection_type(self):
        """Cycle to the next connection type."""
        current = self.connection.connection_type or 'undefined'

        # Build full cycle list: undefined -> types -> undefined
        all_types = ['undefined'] + self.CONNECTION_TYPES

        try:
            current_idx = all_types.index(current)
            next_idx = (current_idx + 1) % len(all_types)
            new_type = all_types[next_idx]
        except ValueError:
            new_type = 'wall'  # Default to wall if unknown

        self._set_connection_type(new_type)

    def _set_connection_type(self, new_type: str):
        """Update the connection type in the document."""
        if self.document:
            self.document.set_connection_type(
                self.connection.room_a_id,
                self.connection.room_b_id,
                new_type
            )
            self.connection.connection_type = new_type
            self.update()  # Trigger repaint


class RoomResizeGrip(QGraphicsItem):
    """Resize grip for room edges - moves entire edge (both vertices)."""

    def __init__(self, room_item, edge_index, parent=None):
        super().__init__(parent)
        self.room_item = room_item
        self.edge_index = edge_index  # Index of first vertex of edge
        self._dragging = False
        self._drag_start_pos = None
        self._drag_start_v1 = None
        self._drag_start_v2 = None
        self._is_horizontal = False  # True if edge is horizontal

        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
        self.setAcceptHoverEvents(True)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setZValue(200)  # Above everything

    def _get_edge_vertices(self):
        """Get the two vertex indices for this edge."""
        if not self.room_item or not self.room_item.room.vertices:
            return 0, 0
        n = len(self.room_item.room.vertices)
        v1_idx = self.edge_index
        v2_idx = (self.edge_index + 1) % n
        return v1_idx, v2_idx

    def _update_cursor_and_orientation(self):
        """Set cursor based on edge orientation."""
        if not self.room_item or not self.room_item.room.vertices:
            return
        v1_idx, v2_idx = self._get_edge_vertices()
        v1 = self.room_item.room.vertices[v1_idx]
        v2 = self.room_item.room.vertices[v2_idx]

        # Check if horizontal or vertical
        if abs(v1[1] - v2[1]) < abs(v1[0] - v2[0]):
            # Horizontal edge - moves vertically
            self._is_horizontal = True
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        else:
            # Vertical edge - moves horizontally
            self._is_horizontal = False
            self.setCursor(Qt.CursorShape.SizeHorCursor)

    def boundingRect(self) -> QRectF:
        return QRectF(-150, -150, 300, 300)

    def shape(self) -> QPainterPath:
        """Return shape for hit testing."""
        path = QPainterPath()
        # Larger hit area for easier clicking
        path.addEllipse(QRectF(-150, -150, 300, 300))
        return path

    def paint(self, painter: QPainter, option, widget):
        # Safety check - room_item may be invalid during refresh
        if not self.room_item or not hasattr(self.room_item, '_view'):
            return
        # Only show at LOD 1 and when room is selected
        if not self.room_item._view or self.room_item._view.lod_level != 1:
            return
        if not self.room_item.scene():  # Room item removed from scene
            return
        if not self.room_item.isSelected():
            return

        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Draw grip as a rectangle/bar indicating edge direction
        painter.setBrush(QBrush(QColor("#4488FF")))
        painter.setPen(QPen(QColor("#FFFFFF"), 20))

        if self._is_horizontal:
            # Horizontal edge - draw horizontal bar
            painter.drawRoundedRect(QRectF(-80, -40, 160, 80), 20, 20)
            # Draw arrows indicating vertical movement
            painter.setPen(QPen(QColor("#FFFFFF"), 15))
            painter.drawLine(QPointF(0, -60), QPointF(0, -30))
            painter.drawLine(QPointF(0, 30), QPointF(0, 60))
        else:
            # Vertical edge - draw vertical bar
            painter.drawRoundedRect(QRectF(-40, -80, 80, 160), 20, 20)
            # Draw arrows indicating horizontal movement
            painter.setPen(QPen(QColor("#FFFFFF"), 15))
            painter.drawLine(QPointF(-60, 0), QPointF(-30, 0))
            painter.drawLine(QPointF(30, 0), QPointF(60, 0))

    def mousePressEvent(self, event):
        # Ignore middle button - let it pass through for view panning
        if event.button() == Qt.MouseButton.MiddleButton:
            event.ignore()
            return

        if event.button() == Qt.MouseButton.LeftButton:
            # Safety check
            if not self.room_item or not self.room_item.room.vertices:
                event.ignore()
                return

            self._dragging = True
            self._drag_start_pos = event.scenePos()

            v1_idx, v2_idx = self._get_edge_vertices()
            v1 = self.room_item.room.vertices[v1_idx]
            v2 = self.room_item.room.vertices[v2_idx]
            self._drag_start_v1 = [v1[0], v1[1]]
            self._drag_start_v2 = [v2[0], v2[1]]

            self._update_cursor_and_orientation()
            event.accept()

    def mouseMoveEvent(self, event):
        # Ignore middle button moves - let them pass through for view panning
        if event.buttons() & Qt.MouseButton.MiddleButton:
            event.ignore()
            return

        if self._dragging and self._drag_start_pos:
            # Safety check
            if not self.room_item or not self.room_item.room.vertices:
                self._dragging = False
                return

            delta = event.scenePos() - self._drag_start_pos

            v1_idx, v2_idx = self._get_edge_vertices()

            if self._is_horizontal:
                # Horizontal edge moves vertically only
                dy = delta.y()
                self.room_item.room.vertices[v1_idx] = [self._drag_start_v1[0], self._drag_start_v1[1] + dy]
                self.room_item.room.vertices[v2_idx] = [self._drag_start_v2[0], self._drag_start_v2[1] + dy]
            else:
                # Vertical edge moves horizontally only
                dx = delta.x()
                self.room_item.room.vertices[v1_idx] = [self._drag_start_v1[0] + dx, self._drag_start_v1[1]]
                self.room_item.room.vertices[v2_idx] = [self._drag_start_v2[0] + dx, self._drag_start_v2[1]]

            # Update grip position to edge midpoint
            v1 = self.room_item.room.vertices[v1_idx]
            v2 = self.room_item.room.vertices[v2_idx]
            mid_x = (v1[0] + v2[0]) / 2
            mid_y = (v1[1] + v2[1]) / 2
            self.setPos(mid_x, mid_y)

            # Update room item
            self.room_item._update_room_geometry()
            self.room_item._update_grip_positions()
            self.room_item.prepareGeometryChange()
            self.room_item.update()
            event.accept()

    def mouseReleaseEvent(self, event):
        # Ignore middle button - let it pass through for view panning
        if event.button() == Qt.MouseButton.MiddleButton:
            event.ignore()
            return

        if self._dragging:
            self._dragging = False
            self._drag_start_pos = None
            self._drag_start_v1 = None
            self._drag_start_v2 = None
            # At LOD 1, skip wall regeneration - just mark dirty
            if self.room_item and self.room_item._view:
                view = self.room_item._view
                if view.lod_level == 1:
                    view._topology_dirty = True
                    print(f"[RoomResizeGrip] Resize at LOD 1, marked _topology_dirty=True")
                    event_bus.document_modified.emit()
                elif self.room_item.document:
                    # LOD 2+: Defer wall regeneration
                    from PyQt6.QtCore import QTimer
                    doc = self.room_item.document

                    if not getattr(view, '_regeneration_pending', False):
                        view._regeneration_pending = True

                        def do_wall_regeneration():
                            try:
                                doc.detect_room_adjacencies()
                                doc.generate_walls_from_rooms()
                                view._force_refresh()
                                event_bus.document_modified.emit()
                            except Exception as e:
                                print(f"[RoomResizeGrip] Wall regeneration error: {e}")
                            finally:
                                view._regeneration_pending = False

                        QTimer.singleShot(0, do_wall_regeneration)
            event.accept()


class RoomItem(QGraphicsItem):
    """Graphics item representing a room.

    At LOD 1 (Topology), rooms become draggable blobs that can be repositioned.
    The room's vertices are updated when dragged.
    """

    def __init__(self, room: Room, document=None, view=None, parent=None):
        super().__init__(parent)
        self.room = room
        self.document = document
        self._view = view

        # Dragging state
        self._dragging = False
        self._drag_start_mouse_pos = None  # Mouse scene position at drag start
        self._drag_start_item_pos = None   # Item position at drag start

        # Resize grips
        self._resize_grips = []

        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setZValue(-10)  # Draw rooms behind walls
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)  # Only accept left button, let middle pass through

        # Calculate center from vertices
        self._update_center()

        # Position item at room center (draw relative to this)
        if self.room.center:
            self.setPos(self.room.center['x'], self.room.center['z'])

        # Check LOD and enable dragging if at LOD 1
        self._update_movable_state()

    def _update_center(self):
        """Calculate room center from vertices."""
        if self.room.vertices:
            xs = [v[0] for v in self.room.vertices]
            zs = [v[1] for v in self.room.vertices]
            self.room.center = {
                'x': (min(xs) + max(xs)) / 2,
                'z': (min(zs) + max(zs)) / 2
            }

    def _update_movable_state(self):
        """Enable/disable dragging based on LOD level."""
        is_lod_1 = self._view and self._view.lod_level == 1
        # Don't use ItemIsMovable - we handle dragging manually
        if is_lod_1:
            self.setCursor(Qt.CursorShape.SizeAllCursor)
            self.setZValue(100)  # Bring to front at LOD 1
        else:
            self.unsetCursor()
            self.setZValue(-10)  # Behind walls at other LODs

    def _create_resize_grips(self):
        """Create resize grips for each edge of the room."""
        self._remove_resize_grips()

        if not self.room.vertices or not self._view:
            return

        scene = self._view.scene
        n = len(self.room.vertices)

        for i in range(n):
            grip = RoomResizeGrip(self, i)
            scene.addItem(grip)
            self._resize_grips.append(grip)
            grip._update_cursor_and_orientation()

        self._update_grip_positions()

    def _remove_resize_grips(self):
        """Remove all resize grips."""
        for grip in self._resize_grips:
            if grip.scene():
                grip.scene().removeItem(grip)
        self._resize_grips.clear()

    def _update_grip_positions(self):
        """Update positions of all resize grips to edge midpoints."""
        if not self.room.vertices:
            return

        n = len(self.room.vertices)
        for i, grip in enumerate(self._resize_grips):
            v1 = self.room.vertices[i]
            v2 = self.room.vertices[(i + 1) % n]
            mid_x = (v1[0] + v2[0]) / 2
            mid_y = (v1[1] + v2[1]) / 2
            grip.setPos(mid_x, mid_y)
            grip._update_cursor_and_orientation()

    def _update_room_geometry(self):
        """Update room center, bounds, and area after resize."""
        self._update_center()

        if self.room.vertices:
            xs = [v[0] for v in self.room.vertices]
            zs = [v[1] for v in self.room.vertices]
            self.room.bounds['x'] = min(xs)
            self.room.bounds['y'] = min(zs)
            self.room.bounds['width'] = max(xs) - min(xs)
            self.room.bounds['height'] = max(zs) - min(zs)

            # Update area (simple polygon area calculation)
            area = 0
            n = len(self.room.vertices)
            for i in range(n):
                j = (i + 1) % n
                area += self.room.vertices[i][0] * self.room.vertices[j][1]
                area -= self.room.vertices[j][0] * self.room.vertices[i][1]
            self.room.area = abs(area) / 2

        # Update item position to new center
        if self.room.center:
            self.setPos(self.room.center['x'], self.room.center['z'])

    def itemChange(self, change, value):
        """Handle item changes - create/remove grips on selection change."""
        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedChange:
            is_selected = value
            is_lod_1 = self._view and self._view.lod_level == 1
            if is_selected and is_lod_1:
                # Defer grip creation to after selection is complete
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(0, self._create_resize_grips)
            else:
                self._remove_resize_grips()
        return super().itemChange(change, value)

    def _get_edges_at_pos(self, pos: QPointF) -> list:
        """Get room edges as line segments at a given position.

        Returns list of tuples: ((x1, y1), (x2, y2), edge_type)
        edge_type is 'left', 'right', 'top', 'bottom' for axis-aligned edges
        """
        if not self.room.vertices or not self.room.center:
            return []

        # Calculate offset from current center to new position
        cx = self.room.center['x']
        cz = self.room.center['z']
        dx = pos.x() - cx
        dz = pos.y() - cz

        edges = []
        verts = self.room.vertices
        n = len(verts)
        for i in range(n):
            v1 = verts[i]
            v2 = verts[(i + 1) % n]
            # Apply offset
            x1, y1 = v1[0] + dx, v1[1] + dz
            x2, y2 = v2[0] + dx, v2[1] + dz

            # Determine edge type based on orientation
            if abs(x1 - x2) < 1:  # Vertical edge
                edge_type = 'left' if x1 < cx + dx else 'right'
            elif abs(y1 - y2) < 1:  # Horizontal edge
                edge_type = 'top' if y1 < cz + dz else 'bottom'
            else:
                edge_type = 'diagonal'

            edges.append(((x1, y1), (x2, y2), edge_type))
        return edges

    def _find_snap(self, new_pos: QPointF, snap_threshold: float = 500) -> QPointF:
        """Find snap position by checking against other rooms.

        Snaps edges of this room to edges of other rooms when close enough.
        Returns adjusted position, or original if no snap found.
        """
        if not self._view or not self.room.vertices:
            return new_pos

        # Get all other room items
        other_rooms = [item for item in self._view._room_items if item != self]
        if not other_rooms:
            return new_pos

        # Get our edges at the proposed new position
        our_edges = self._get_edges_at_pos(new_pos)
        if not our_edges:
            return new_pos

        # Calculate our bounding box at new position
        cx = self.room.center['x']
        cz = self.room.center['z']
        dx = new_pos.x() - cx
        dz = new_pos.y() - cz

        our_xs = [v[0] + dx for v in self.room.vertices]
        our_zs = [v[1] + dz for v in self.room.vertices]
        our_left = min(our_xs)
        our_right = max(our_xs)
        our_top = min(our_zs)
        our_bottom = max(our_zs)

        best_snap_x = None
        best_snap_y = None
        best_dist_x = snap_threshold
        best_dist_y = snap_threshold

        for other in other_rooms:
            if not other.room.vertices:
                continue

            # Get other room's bounding box
            other_xs = [v[0] for v in other.room.vertices]
            other_zs = [v[1] for v in other.room.vertices]
            other_left = min(other_xs)
            other_right = max(other_xs)
            other_top = min(other_zs)
            other_bottom = max(other_zs)

            # Check horizontal snaps (our left to their right, our right to their left)
            # Our right edge to their left edge
            dist = abs(our_right - other_left)
            if dist < best_dist_x:
                best_dist_x = dist
                best_snap_x = new_pos.x() - (our_right - other_left)

            # Our left edge to their right edge
            dist = abs(our_left - other_right)
            if dist < best_dist_x:
                best_dist_x = dist
                best_snap_x = new_pos.x() + (other_right - our_left)

            # Check vertical snaps (our top to their bottom, our bottom to their top)
            # Our bottom edge to their top edge
            dist = abs(our_bottom - other_top)
            if dist < best_dist_y:
                best_dist_y = dist
                best_snap_y = new_pos.y() - (our_bottom - other_top)

            # Our top edge to their bottom edge
            dist = abs(our_top - other_bottom)
            if dist < best_dist_y:
                best_dist_y = dist
                best_snap_y = new_pos.y() + (other_bottom - our_top)

        # Apply snaps
        result_x = best_snap_x if best_snap_x is not None else new_pos.x()
        result_y = best_snap_y if best_snap_y is not None else new_pos.y()

        return QPointF(result_x, result_y)

    def mousePressEvent(self, event):
        """Handle mouse press - prepare for potential drag at LOD 1."""
        # Ignore middle button - let it pass through for view panning
        if event.button() == Qt.MouseButton.MiddleButton:
            event.ignore()
            return

        # Only handle left button at LOD 1
        if self._view and self._view.lod_level == 1 and event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_mouse_pos = event.scenePos()
            self._drag_start_item_pos = self.pos()
            self._dragging = False
            event.accept()
            # Don't call super - we're handling this ourselves
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """Handle mouse move - drag room at LOD 1."""
        # Ignore middle button moves - let them pass through for view panning
        if event.buttons() & Qt.MouseButton.MiddleButton:
            event.ignore()
            return

        if self._drag_start_mouse_pos is not None and self._drag_start_item_pos is not None:
            delta = event.scenePos() - self._drag_start_mouse_pos

            # Only start actual drag if moved more than threshold (in scene units)
            if not self._dragging:
                if abs(delta.x()) > 50 or abs(delta.y()) > 50:
                    self._dragging = True
                    # Hide grips during drag for cleaner experience
                    for grip in self._resize_grips:
                        grip.setVisible(False)
                else:
                    return

            # Calculate new position
            new_pos = self._drag_start_item_pos + delta

            # Apply snapping to other rooms
            snapped_pos = self._find_snap(new_pos)

            self.setPos(snapped_pos)

            # Update grip positions to follow the drag
            self._update_grip_positions_for_drag(snapped_pos)

            event.accept()
        else:
            super().mouseMoveEvent(event)

    def _update_grip_positions_for_drag(self, new_center_pos: QPointF):
        """Update grip positions during drag based on new center position."""
        if not self.room.vertices or not self.room.center:
            return

        # Calculate offset from original center to new position
        dx = new_center_pos.x() - self.room.center['x']
        dy = new_center_pos.y() - self.room.center['z']

        n = len(self.room.vertices)
        for i, grip in enumerate(self._resize_grips):
            v1 = self.room.vertices[i]
            v2 = self.room.vertices[(i + 1) % n]
            mid_x = (v1[0] + v2[0]) / 2 + dx
            mid_y = (v1[1] + v2[1]) / 2 + dy
            grip.setPos(mid_x, mid_y)

    def mouseReleaseEvent(self, event):
        """Handle mouse release - finalize drag by updating vertices."""
        # Ignore middle button - let it pass through for view panning
        if event.button() == Qt.MouseButton.MiddleButton:
            event.ignore()
            return

        was_dragging = self._dragging

        if was_dragging and self._drag_start_item_pos is not None and self.room.vertices:
            # Calculate how much the room moved
            delta = self.pos() - QPointF(self.room.center['x'], self.room.center['z'])
            dx = delta.x()
            dy = delta.y()

            # Update vertices to match new position
            for v in self.room.vertices:
                v[0] += dx
                v[1] += dy

            # Update center and bounds
            self._update_center()
            xs = [v[0] for v in self.room.vertices]
            zs = [v[1] for v in self.room.vertices]
            self.room.bounds['x'] = min(xs)
            self.room.bounds['y'] = min(zs)
            self.room.bounds['width'] = max(xs) - min(xs)
            self.room.bounds['height'] = max(zs) - min(zs)

            # At LOD 1, skip wall regeneration - just mark dirty
            # Walls will be regenerated when switching to LOD 2+
            if self._view and self._view.lod_level == 1:
                self._view._topology_dirty = True
                print(f"[RoomItem] Blob moved at LOD 1, marked _topology_dirty=True")
                # Just emit modified to update title
                from core.events import event_bus
                event_bus.document_modified.emit()
            elif self.document and self._view:
                # LOD 2+: Do immediate wall regeneration (deferred to avoid crash)
                from PyQt6.QtCore import QTimer
                doc = self.document
                view = self._view

                if not getattr(view, '_regeneration_pending', False):
                    view._regeneration_pending = True

                    def do_wall_regeneration():
                        try:
                            doc.detect_room_adjacencies()
                            doc.generate_walls_from_rooms()
                            view._force_refresh()
                            from core.events import event_bus
                            event_bus.document_modified.emit()
                        except Exception as e:
                            print(f"[RoomItem] Wall regeneration error: {e}")
                        finally:
                            view._regeneration_pending = False

                    QTimer.singleShot(0, do_wall_regeneration)

        # Always reset drag state BEFORE deferring work
        self._dragging = False
        self._drag_start_mouse_pos = None
        self._drag_start_item_pos = None

        # Don't call super or update grips - the deferred refresh will recreate everything

    def boundingRect(self) -> QRectF:
        """Return bounding rectangle in local coordinates (relative to item pos)."""
        if not self.room.vertices or not self.room.center:
            # Fallback to bounds centered at origin - include text area
            b = self.room.bounds
            half_w = max(b['width']/2, 2000) + 200
            half_h = max(b['height']/2, 800) + 200
            return QRectF(-half_w, -half_h, half_w * 2, half_h * 2)

        # Calculate bounding rect relative to center (item pos)
        cx = self.room.center['x']
        cz = self.room.center['z']
        xs = [v[0] - cx for v in self.room.vertices]
        zs = [v[1] - cz for v in self.room.vertices]

        # Expand to include text (extends -2000 to 2000 in x)
        # and handles (extends to ~600) and pin indicator (at -700 y)
        min_x = min(min(xs), -2100)
        max_x = max(max(xs), 2100)
        min_z = min(min(zs), -800)  # Pin at -600, handles at -550
        max_z = max(max(zs), 700)   # Area text extends to ~400

        return QRectF(min_x, min_z, max_x - min_x, max_z - min_z)

    def shape(self) -> QPainterPath:
        """Return shape for hit testing in local coordinates."""
        path = QPainterPath()
        if self.room.vertices and self.room.center:
            cx = self.room.center['x']
            cz = self.room.center['z']
            polygon = QPolygonF()
            for v in self.room.vertices:
                polygon.append(QPointF(v[0] - cx, v[1] - cz))
            path.addPolygon(polygon)
        return path

    def paint(self, painter: QPainter, option, widget):
        """Paint the room.

        At LOD 1 (Topology), rooms are shown as prominent draggable blobs.
        At other LOD levels, rooms are shown as subtle background shapes.
        """
        # Sync item position with room center when not dragging
        # This prevents zoom or other operations from affecting position
        # Also check _drag_start_mouse_pos to avoid resetting during drag threshold check
        if not self._dragging and self._drag_start_mouse_pos is None and self.room.center:
            expected_pos = QPointF(self.room.center['x'], self.room.center['z'])
            if self.pos() != expected_pos:
                self.setPos(expected_pos)

        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        is_lod_1 = self._view and self._view.lod_level == 1

        # Room fill color based on type - more saturated at LOD 1
        if is_lod_1:
            # LOD 1: Vibrant blob colors for easy identification
            room_colors = {
                'living': QColor(120, 200, 120, 180),
                'bedroom': QColor(120, 120, 200, 180),
                'kitchen': QColor(200, 180, 100, 180),
                'bathroom': QColor(100, 180, 200, 180),
                'dining': QColor(200, 200, 100, 180),
                'office': QColor(180, 180, 180, 180),
                'garage': QColor(140, 140, 140, 180),
                'generic': QColor(160, 160, 160, 150),
            }
        else:
            # Other LODs: Subtle background colors
            room_colors = {
                'living': QColor(200, 230, 200, 60),
                'bedroom': QColor(200, 200, 230, 60),
                'kitchen': QColor(230, 220, 200, 60),
                'bathroom': QColor(200, 220, 230, 60),
                'dining': QColor(230, 230, 200, 60),
                'office': QColor(220, 220, 220, 60),
                'garage': QColor(180, 180, 180, 60),
                'generic': QColor(210, 210, 210, 40),
            }

        fill_color = room_colors.get(self.room.room_type, room_colors['generic'])
        if self.isSelected():
            fill_color = QColor(100, 200, 255, 180 if is_lod_1 else 80)

        # Draw room polygon (in local coords, relative to center)
        if self.room.vertices and self.room.center:
            cx = self.room.center['x']
            cz = self.room.center['z']
            polygon = QPolygonF()
            for v in self.room.vertices:
                polygon.append(QPointF(v[0] - cx, v[1] - cz))

            # Fill with appropriate style
            painter.setBrush(QBrush(fill_color))
            if is_lod_1:
                # LOD 1: Solid border, thicker line
                pen_color = QColor(255, 255, 255) if self.isSelected() else QColor(80, 80, 80)
                pen = QPen(pen_color, 40, Qt.PenStyle.SolidLine)
            else:
                # Other LODs: Dashed border
                pen = QPen(QColor(100, 200, 255) if self.isSelected() else QColor(100, 100, 100), 20, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawPolygon(polygon)

            # Draw room label at center (0,0 in local coords)
            # Room name - larger at LOD 1, centered on room
            painter.setPen(QPen(Qt.GlobalColor.white))
            font = painter.font()
            font.setPointSize(140 if is_lod_1 else 100)
            font.setBold(True)
            painter.setFont(font)

            name_text = self.room.name or self.room.room_type.capitalize()
            # Create rect centered at origin (item pos is at room center)
            text_rect = QRectF(-2000, -300, 4000, 400)
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, name_text)

            # Area text - centered below name
            font.setPointSize(100 if is_lod_1 else 80)
            font.setBold(False)
            painter.setFont(font)
            area_m2 = self.room.area / 1e6 if self.room.area else 0
            area_rect = QRectF(-2000, 100, 4000, 300)
            painter.drawText(area_rect, Qt.AlignmentFlag.AlignCenter, f"{area_m2:.1f} m²")

            # Draw drag handle at LOD 1 (at center = 0,0 in local coords)
            if is_lod_1:
                painter.save()
                handle_color = QColor(255, 255, 255, 200)
                painter.setPen(QPen(handle_color, 25))
                arrow_size = 150
                # Up arrow
                painter.drawLine(QPointF(0, -400), QPointF(0, -400 - arrow_size))
                painter.drawLine(QPointF(0, -400 - arrow_size), QPointF(-50, -400 - arrow_size + 50))
                painter.drawLine(QPointF(0, -400 - arrow_size), QPointF(50, -400 - arrow_size + 50))
                # Down arrow
                painter.drawLine(QPointF(0, 450), QPointF(0, 450 + arrow_size))
                painter.drawLine(QPointF(0, 450 + arrow_size), QPointF(-50, 450 + arrow_size - 50))
                painter.drawLine(QPointF(0, 450 + arrow_size), QPointF(50, 450 + arrow_size - 50))
                # Left arrow
                painter.drawLine(QPointF(-400, 0), QPointF(-400 - arrow_size, 0))
                painter.drawLine(QPointF(-400 - arrow_size, 0), QPointF(-400 - arrow_size + 50, -50))
                painter.drawLine(QPointF(-400 - arrow_size, 0), QPointF(-400 - arrow_size + 50, 50))
                # Right arrow
                painter.drawLine(QPointF(400, 0), QPointF(400 + arrow_size, 0))
                painter.drawLine(QPointF(400 + arrow_size, 0), QPointF(400 + arrow_size - 50, -50))
                painter.drawLine(QPointF(400 + arrow_size, 0), QPointF(400 + arrow_size - 50, 50))
                painter.restore()

            # Draw pin indicator if pinned (at center = 0,0)
            if self.room.is_pinned:
                painter.save()
                painter.setPen(QPen(QColor(255, 100, 100), 30))
                painter.setBrush(QBrush(QColor(255, 100, 100, 180)))
                painter.drawEllipse(QPointF(0, -600), 120, 120)
                painter.setPen(QPen(Qt.GlobalColor.white, 40))
                painter.drawPoint(QPointF(0, -600))
                painter.restore()


class PlanView(BaseView):
    """
    Main 2D floor plan view.
    Central editing workspace.
    """

    selection_changed = pyqtSignal(list)  # List of selected item indices
    lod_level_changed = pyqtSignal(int)  # LOD level 1-5

    def __init__(self, document: ArchDocument, config: Config, parent=None):
        super().__init__(document, config, parent)

        # Item collections
        self._wall_items: List[WallItem] = []
        self._door_items: List[DoorItem] = []
        self._window_items: List[WindowItem] = []
        self._room_items: List[RoomItem] = []
        self._room_labels: List[RoomLabelItem] = []
        self._connection_items: List[ConnectionItem] = []
        self._reference_plane_items: List[ReferencePlaneItem] = []

        # Snap system
        self._snap_manager = SnapManager(document, config)
        self._snap_indicator = SnapIndicator()
        self.scene.addItem(self._snap_indicator)

        # Tool manager (created after view is ready)
        self._tool_manager = None

        # Tab cycling state for overlapping elements
        self._click_items: List = []  # Items at last click position
        self._cycle_index: int = 0
        self._last_click_pos = None

        # Guard against overlapping refresh during wall regeneration
        self._regeneration_pending = False
        # Track if topology was modified at LOD 1 (needs wall regen on LOD change)
        self._topology_dirty = False

        # Connect to document changes
        self.document.document_changed.connect(self.refresh)
        event_bus.element_modified.connect(self._on_element_modified)

        # Set large scene rect for unlimited panning
        self.scene.setSceneRect(-1000000, -1000000, 2000000, 2000000)

        # Initial scale (1mm = 0.05 pixels by default, inverted)
        self.scale(config.default_scale, config.default_scale)
        self._zoom = config.default_scale

        # Enable mouse tracking for tool preview
        self.setMouseTracking(True)

    def set_tool_manager(self, tool_manager):
        """Set the tool manager."""
        self._tool_manager = tool_manager

    def set_lod_level(self, level: int):
        """Set LOD level and update item visibility/states."""
        old_level = getattr(self, '_lod_level', 2)
        topology_dirty = getattr(self, '_topology_dirty', False)
        print(f"[PlanView] set_lod_level({level}), old={old_level}, _topology_dirty={topology_dirty}")

        # Manually update _lod_level and emit signal (avoid base class scene.update())
        level = max(1, min(5, level))
        if level != self._lod_level:
            self._lod_level = level
            print(f"[PlanView] Emitting lod_level_changed signal...")
            self.lod_level_changed.emit(level)
            print(f"[PlanView] Signal emitted")

        # If leaving LOD 1 and topology was modified, defer wall regeneration
        if old_level == 1 and level != 1 and topology_dirty:
            self._topology_dirty = False
            if self.document:
                from PyQt6.QtCore import QTimer
                print(f"[PlanView] Scheduling deferred wall regeneration")
                QTimer.singleShot(0, self._deferred_wall_regeneration)
            # Don't apply visibility yet - will be done after regeneration
        else:
            self._apply_lod_visibility()

    def _deferred_wall_regeneration(self):
        """Regenerate walls after LOD 1 edit, called via QTimer.singleShot."""
        if not self.document:
            return
        print(f"[PlanView] Starting deferred wall regeneration")
        try:
            self.document.detect_room_adjacencies()
            print(f"[PlanView] detect_room_adjacencies done")
            self.document.generate_walls_from_rooms()
            print(f"[PlanView] generate_walls_from_rooms done, {len(self.document.walls)} walls")
            self._force_refresh()
            print(f"[PlanView] _force_refresh done")
            self._apply_lod_visibility()
            print(f"[PlanView] _apply_lod_visibility done")
            from core.events import event_bus
            event_bus.document_modified.emit()
        except Exception as e:
            import traceback
            print(f"[PlanView] ERROR during deferred wall regeneration: {e}")
            traceback.print_exc()

    def _apply_lod_visibility(self):
        """Apply visibility settings based on current LOD level."""
        # LOD 1 (Topology): Only show room blobs and connections
        # LOD 2+: Show walls, doors, windows
        is_lod_1 = (self._lod_level == 1)

        # Update room items - they become draggable at LOD 1
        for room_item in self._room_items:
            if room_item and room_item.scene():
                if hasattr(room_item, '_update_movable_state'):
                    room_item._update_movable_state()
                room_item.update()  # Force repaint

        # Hide walls at LOD 1
        for wall_item in self._wall_items:
            if wall_item and wall_item.scene():
                wall_item.setVisible(not is_lod_1)
                # Also hide layer items
                for layer_item in getattr(wall_item, '_layer_items', []):
                    if layer_item and layer_item.scene():
                        layer_item.setVisible(not is_lod_1)

        # Hide doors at LOD 1
        for door_item in self._door_items:
            if door_item and door_item.scene():
                door_item.setVisible(not is_lod_1)

        # Hide windows at LOD 1
        for window_item in self._window_items:
            if window_item and window_item.scene():
                window_item.setVisible(not is_lod_1)

        # Force scene update
        if self.scene:
            self.scene.update()

    def refresh_connections(self):
        """Refresh room connection items from document data.

        Called after room adjacencies change or on initial load.
        Connection items are only visible at LOD 1.
        """
        # Clear existing connection items
        for item in self._connection_items:
            self.scene.removeItem(item)
        self._connection_items.clear()

        # Create connection items from document
        if hasattr(self.document, 'room_connections'):
            for conn in self.document.room_connections:
                item = ConnectionItem(conn, document=self.document, view=self)
                self.scene.addItem(item)
                self._connection_items.append(item)

    def set_view_mode(self, mode: str):
        """Set view mode from tetrahedron navigation (stub)."""
        pass

    @property
    def tool_manager(self):
        """Get tool manager."""
        return self._tool_manager

    def refresh(self):
        """Rebuild the entire view from document data."""
        # Skip if regeneration is pending (another blob move will trigger refresh)
        if getattr(self, '_regeneration_pending', False):
            return
        self._force_refresh()

    def _force_refresh(self):
        """Internal refresh - bypasses regeneration guard."""
        print(f"[PlanView] _force_refresh starting, {len(self._room_items)} room items")
        # Clear existing items - must delete explicitly to prevent memory leaks
        for item in self._wall_items:
            # Remove layer items first
            if hasattr(item, 'remove_layer_items'):
                item.remove_layer_items()
            # Remove grips
            if hasattr(item, '_remove_grips'):
                item._remove_grips()
            if item.scene():
                self.scene.removeItem(item)
        for item in self._door_items:
            if hasattr(item, '_remove_grips'):
                item._remove_grips()
            if item.scene():
                self.scene.removeItem(item)
        for item in self._window_items:
            if hasattr(item, '_remove_grips'):
                item._remove_grips()
            if item.scene():
                self.scene.removeItem(item)
        for item in self._room_items:
            # Remove resize grips first (they're separate scene items)
            if hasattr(item, '_remove_resize_grips'):
                item._remove_resize_grips()
            if item.scene():
                self.scene.removeItem(item)
        for item in self._room_labels:
            if item.scene():
                self.scene.removeItem(item)
        for item in self._connection_items:
            if item.scene():
                self.scene.removeItem(item)

        self._wall_items.clear()
        self._door_items.clear()
        self._window_items.clear()
        self._room_items.clear()
        self._room_labels.clear()
        self._connection_items.clear()

        # Force garbage collection to reclaim memory
        import gc
        gc.collect()

        # Add walls
        for wall in self.document.walls:
            item = WallItem(wall, document=self.document,
                           snap_manager=self._snap_manager,
                           snap_indicator=self._snap_indicator,
                           config=self.config)
            self.scene.addItem(item)
            self._wall_items.append(item)

            # Create individual layer items for this wall
            item.create_layer_items(self.scene)

        # Add doors
        for door in self.document.doors:
            item = DoorItem(door, self.document.walls, document=self.document)
            self.scene.addItem(item)
            self._door_items.append(item)

        # Add windows
        for window in self.document.windows:
            item = WindowItem(window, self.document.walls, document=self.document)
            self.scene.addItem(item)
            self._window_items.append(item)

        # Add rooms (polygon rooms with RoomItem, bounds-only with RoomLabelItem)
        for room_id, room in self.document.rooms.items():
            if room.vertices:
                # Polygon room - use RoomItem (draggable at LOD 1)
                item = RoomItem(room, document=self.document, view=self)
                self.scene.addItem(item)
                self._room_items.append(item)
            else:
                # Bounds-only room - use legacy label
                label = RoomLabelItem(room)
                self.scene.addItem(label)
                self._room_labels.append(label)

        # Add room connections (visible at LOD 1)
        self.refresh_connections()

        # Add reference planes (grid lines)
        for item in self._reference_plane_items:
            self.scene.removeItem(item)
        self._reference_plane_items.clear()

        for plane in self.document.reference_planes:
            item = ReferencePlaneItem(plane, view=self)
            self.scene.addItem(item)
            self._reference_plane_items.append(item)

        # Apply current LOD visibility settings to newly created items
        self._apply_lod_visibility()

        self.viewport().update()

    def _on_element_modified(self, element_type: str, element_id: str, changes: dict):
        """Handle element modification."""
        idx = int(element_id) if element_id.isdigit() else -1

        if element_type == "wall" and 0 <= idx < len(self._wall_items):
            wall_item = self._wall_items[idx]
            # Update grip positions if selected
            if wall_item.isSelected() and wall_item._grips:
                x1, z1 = wall_item.wall.start[0], wall_item.wall.start[2]
                x2, z2 = wall_item.wall.end[0], wall_item.wall.end[2]
                cx, cz = (x1 + x2) / 2, (z1 + z2) / 2
                for grip in wall_item._grips:
                    if grip.grip_type == 'start':
                        grip.setPos(x1, z1)
                    elif grip.grip_type == 'end':
                        grip.setPos(x2, z2)
                    elif grip.grip_type == 'center':
                        grip.setPos(cx, cz)
            wall_item.prepareGeometryChange()
            wall_item.update()

        elif element_type == "door" and 0 <= idx < len(self._door_items):
            door_item = self._door_items[idx]
            door_item.prepareGeometryChange()
            door_item.update()
            # Update grip position
            if door_item.isSelected() and door_item._grips:
                pos = door_item._get_position()
                for grip in door_item._grips:
                    grip.setPos(pos)

        elif element_type == "window" and 0 <= idx < len(self._window_items):
            window_item = self._window_items[idx]
            window_item.prepareGeometryChange()
            window_item.update()
            if window_item.isSelected() and window_item._grips:
                pos = window_item._get_position()
                for grip in window_item._grips:
                    grip.setPos(pos)

        self.scene.update()
        self.viewport().update()

    def get_selected_walls(self) -> List[int]:
        """Get indices of selected walls."""
        return [
            i for i, item in enumerate(self._wall_items)
            if item.isSelected()
        ]

    def get_selected_doors(self) -> List[int]:
        """Get indices of selected doors."""
        return [
            i for i, item in enumerate(self._door_items)
            if item.isSelected()
        ]

    def get_selected_windows(self) -> List[int]:
        """Get indices of selected windows."""
        return [
            i for i, item in enumerate(self._window_items)
            if item.isSelected()
        ]

    # =========================================================================
    # Mouse Event Forwarding to Tools
    # =========================================================================

    def mousePressEvent(self, event):
        """Forward mouse press to active tool."""
        # Check for middle button pan first
        if event.button() == Qt.MouseButton.MiddleButton:
            super().mousePressEvent(event)
            return

        scene_pos = self.mapToScene(event.position().toPoint())

        # Check if clicking on a grip - let QGraphicsView handle it
        item = self.scene.itemAt(scene_pos, self.transform())
        if isinstance(item, (GripItem, RoomResizeGrip)):
            super().mousePressEvent(event)
            return

        # Collect all selectable items at click position for Tab cycling
        if event.button() == Qt.MouseButton.LeftButton:
            self._collect_items_at(scene_pos)

        # For non-grip items, let QGraphicsView handle selection first
        super().mousePressEvent(event)

        # Then also notify tool (for custom handling)
        if self._tool_manager and self._tool_manager.active_tool:
            self._tool_manager.active_tool.mouse_press(event, scene_pos)

    def mouseMoveEvent(self, event):
        """Forward mouse move to active tool."""
        # Check for panning first
        if self._panning:
            super().mouseMoveEvent(event)
            return

        # Check if any item is grabbing the mouse (grips, room items, etc.)
        grabber = self.scene.mouseGrabberItem()
        if grabber is not None:
            super().mouseMoveEvent(event)
            # Still update status bar
            scene_pos = self.mapToScene(event.position().toPoint())
            event_bus.status_message.emit(
                f"X: {scene_pos.x():.0f}mm  Y: {scene_pos.y():.0f}mm",
                0
            )
            return

        # Forward to tool
        if self._tool_manager and self._tool_manager.active_tool:
            scene_pos = self.mapToScene(event.position().toPoint())
            self._tool_manager.active_tool.mouse_move(event, scene_pos)

        # Update status bar with coordinates
        scene_pos = self.mapToScene(event.position().toPoint())
        event_bus.status_message.emit(
            f"X: {scene_pos.x():.0f}mm  Y: {scene_pos.y():.0f}mm",
            0
        )

    def mouseReleaseEvent(self, event):
        """Forward mouse release to active tool."""
        if event.button() == Qt.MouseButton.MiddleButton:
            super().mouseReleaseEvent(event)
            return

        # Check if any item was grabbing the mouse - let Qt handle it
        grabber = self.scene.mouseGrabberItem()
        if grabber is not None:
            super().mouseReleaseEvent(event)
            return

        # Check if click was on a grip
        scene_pos = self.mapToScene(event.position().toPoint())
        item = self.scene.itemAt(scene_pos, self.transform())
        if isinstance(item, (GripItem, RoomResizeGrip)):
            super().mouseReleaseEvent(event)
            return

        if self._tool_manager and self._tool_manager.active_tool:
            self._tool_manager.active_tool.mouse_release(event, scene_pos)
        else:
            super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        """Forward double click to active tool."""
        if self._tool_manager and self._tool_manager.active_tool:
            scene_pos = self.mapToScene(event.position().toPoint())
            self._tool_manager.active_tool.mouse_double_click(event, scene_pos)
        else:
            super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event):
        """Forward key press to active tool, handle Tab cycling."""
        # Tab = cycle through overlapping elements
        if event.key() == Qt.Key.Key_Tab:
            forward = not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            if self._cycle_selection(forward):
                event.accept()
                return

        if self._tool_manager and self._tool_manager.active_tool:
            self._tool_manager.active_tool.key_press(event)

            # Check if tool handled escape
            if event.key() == Qt.Key.Key_Escape:
                return

        super().keyPressEvent(event)

    def _collect_items_at(self, scene_pos):
        """Collect all selectable items at the given scene position for Tab cycling."""
        # Get all items at this position
        items_at_pos = self.scene.items(scene_pos)

        # Filter to only selectable items (walls, rooms, doors, windows, connections)
        # and sort by priority (smaller/more precise elements first)
        selectable_items = []
        for item in items_at_pos:
            if isinstance(item, (WallItem, RoomItem, DoorItem, WindowItem, ConnectionItem)):
                if item.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsSelectable:
                    # Calculate priority and size for sorting
                    if isinstance(item, DoorItem):
                        priority = 100  # Highest - small openings
                        size = item.boundingRect().width() * item.boundingRect().height()
                    elif isinstance(item, WindowItem):
                        priority = 100  # Highest - small openings
                        size = item.boundingRect().width() * item.boundingRect().height()
                    elif isinstance(item, ConnectionItem):
                        priority = 90   # High - connection indicators between rooms
                        size = item.boundingRect().width() * item.boundingRect().height()
                    elif isinstance(item, WallItem):
                        priority = 80   # High - linear elements
                        size = item.boundingRect().width() * item.boundingRect().height()
                    elif isinstance(item, RoomItem):
                        priority = 20   # Low - large floor areas
                        size = item.boundingRect().width() * item.boundingRect().height()
                    else:
                        priority = 10
                        size = 1e9
                    selectable_items.append((item, priority, size))

        # Sort by priority (descending), then size (ascending - smaller first)
        selectable_items.sort(key=lambda x: (-x[1], x[2]))

        # Extract just the items
        self._click_items = [item for item, _, _ in selectable_items]
        self._cycle_index = 0
        self._last_click_pos = scene_pos

        # Show hint if multiple items
        if len(self._click_items) > 1:
            first_type = type(self._click_items[0]).__name__.replace('Item', '')
            event_bus.status_message.emit(
                f"1/{len(self._click_items)} elements ({first_type}) - press Tab to cycle",
                3000
            )

    def _cycle_selection(self, forward: bool = True) -> bool:
        """Cycle through overlapping items at the last click position."""
        if not self._click_items or len(self._click_items) < 2:
            return False

        # Clear current selection
        self.scene.clearSelection()

        # Cycle index
        if forward:
            self._cycle_index = (self._cycle_index + 1) % len(self._click_items)
        else:
            self._cycle_index = (self._cycle_index - 1) % len(self._click_items)

        # Select the new item
        item = self._click_items[self._cycle_index]
        item.setSelected(True)

        # Show status
        item_type = type(item).__name__.replace('Item', '')
        event_bus.status_message.emit(
            f"{self._cycle_index + 1}/{len(self._click_items)} - {item_type}",
            2000
        )

        return True

    def keyReleaseEvent(self, event):
        """Forward key release to active tool."""
        if self._tool_manager and self._tool_manager.active_tool:
            self._tool_manager.active_tool.key_release(event)
        super().keyReleaseEvent(event)
