"""
Gravity Triangle Widget - Escher-inspired perspective blending control.

A triangular control with three corners (Design, Client, Build) and a draggable
puck that determines the blend weights between perspectives.

Based on ESCHER_IMPLEMENTATION_SPEC.md - implements smooth transitions and
barycentric coordinate math for gravity blending.
"""
import math
from typing import Tuple, Optional

from PyQt6.QtWidgets import QWidget, QToolTip
from PyQt6.QtCore import Qt, pyqtSignal, QPointF, QRectF, QTimer, QPropertyAnimation, QVariantAnimation
from PyQt6.QtGui import (
    QPainter, QPen, QBrush, QColor, QPainterPath,
    QFont, QFontMetrics, QLinearGradient, QRadialGradient
)


# Transition timing from spec
TRANSITION_CONFIG = {
    'preset_switch': 400,    # ms - clicking preset button
    'drag': 0,               # ms - dragging puck (immediate)
    'keyboard': 300,         # ms - keyboard shortcut
}


class GravityTriangleWidget(QWidget):
    """
    Triangle widget for blending between three perspectives.

    Corners:
        - Top: Design (Architect) - relationships, flow, topology
        - Bottom-Left: Client (Homeowner) - spaces, light, feel
        - Bottom-Right: Build (Contractor) - coordinates, materials

    Signals:
        gravity_changed(design, client, build): Emitted when puck moves.
            Values are 0.0-1.0 weights that sum to 1.0.
    """

    gravity_changed = pyqtSignal(float, float, float)  # design, client, build

    # Corner labels
    DESIGN = "Design"
    CLIENT = "Client"
    BUILD = "Build"

    # Colors for each gravity
    DESIGN_COLOR = QColor(100, 149, 237)   # Cornflower blue
    CLIENT_COLOR = QColor(144, 238, 144)   # Light green
    BUILD_COLOR = QColor(255, 165, 0)      # Orange

    def __init__(self, parent=None):
        super().__init__(parent)

        # Puck position in barycentric coordinates (weights sum to 1)
        self._design_weight = 0.33
        self._client_weight = 0.33
        self._build_weight = 0.34

        # Target weights for animation
        self._target_design = 0.33
        self._target_client = 0.33
        self._target_build = 0.34

        # Interaction state
        self._dragging = False
        self._hover = False
        self._animating = False

        # Animation timer
        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._update_animation)
        self._anim_duration = 0
        self._anim_elapsed = 0
        self._anim_start_design = 0.33
        self._anim_start_client = 0.33
        self._anim_start_build = 0.34

        # Visual settings
        self._padding = 30  # Space for labels
        self._puck_radius = 10

        self.setMinimumSize(150, 130)
        self.setMaximumSize(200, 180)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)  # Enable keyboard input

        self.setToolTip(
            "Drag the puck to blend perspectives:\n"
            "Design: relationships, topology\n"
            "Client: realistic, livable\n"
            "Build: coordinates, specs\n"
            "\nShortcuts: D/C/B keys"
        )

    def _get_triangle_points(self) -> Tuple[QPointF, QPointF, QPointF]:
        """Get the three corner points of the triangle."""
        w = self.width()
        h = self.height()
        pad = self._padding

        # Triangle vertices (top, bottom-left, bottom-right)
        top = QPointF(w / 2, pad)
        bottom_left = QPointF(pad, h - pad)
        bottom_right = QPointF(w - pad, h - pad)

        return top, bottom_left, bottom_right

    def _barycentric_to_cartesian(self, design: float, client: float, build: float) -> QPointF:
        """Convert barycentric coordinates to cartesian point."""
        top, bl, br = self._get_triangle_points()

        x = design * top.x() + client * bl.x() + build * br.x()
        y = design * top.y() + client * bl.y() + build * br.y()

        return QPointF(x, y)

    def _cartesian_to_barycentric(self, point: QPointF) -> Tuple[float, float, float]:
        """Convert cartesian point to barycentric coordinates.

        Uses standard barycentric formula where:
        - top = Design vertex
        - bl = Client vertex (bottom-left)
        - br = Build vertex (bottom-right)

        point = client*bl + build*br + design*top
        """
        top, bl, br = self._get_triangle_points()

        # Vectors from bl (client corner)
        # v0 = vector to br (build)
        # v1 = vector to top (design)
        # v2 = vector to point
        v0x = br.x() - bl.x()
        v0y = br.y() - bl.y()
        v1x = top.x() - bl.x()
        v1y = top.y() - bl.y()
        v2x = point.x() - bl.x()
        v2y = point.y() - bl.y()

        # Dot products
        dot00 = v0x * v0x + v0y * v0y
        dot01 = v0x * v1x + v0y * v1y
        dot02 = v0x * v2x + v0y * v2y
        dot11 = v1x * v1x + v1y * v1y
        dot12 = v1x * v2x + v1y * v2y

        denom = dot00 * dot11 - dot01 * dot01
        if abs(denom) < 0.0001:
            return 0.33, 0.33, 0.34

        inv_denom = 1.0 / denom

        # u = weight for br (build): point moves along v0 direction
        # v = weight for top (design): point moves along v1 direction
        # Standard formula: u = (d11*d02 - d01*d12) / denom, v = (d00*d12 - d01*d02) / denom
        u = (dot11 * dot02 - dot01 * dot12) * inv_denom  # build weight
        v = (dot00 * dot12 - dot01 * dot02) * inv_denom  # design weight
        w = 1.0 - u - v  # client weight (remainder at bl)

        return v, w, u  # design, client, build

    def _clamp_to_triangle(self, design: float, client: float, build: float) -> Tuple[float, float, float]:
        """Clamp barycentric coordinates to stay inside triangle."""
        # Clamp each weight to [0, 1]
        design = max(0.0, min(1.0, design))
        client = max(0.0, min(1.0, client))
        build = max(0.0, min(1.0, build))

        # Normalize to sum to 1
        total = design + client + build
        if total > 0:
            design /= total
            client /= total
            build /= total
        else:
            design, client, build = 0.33, 0.33, 0.34

        return design, client, build

    def _get_blend_color(self) -> QColor:
        """Get the current blended color based on weights."""
        # Clamp weights to valid range [0, 1]
        dw = max(0.0, min(1.0, self._design_weight))
        cw = max(0.0, min(1.0, self._client_weight))
        bw = max(0.0, min(1.0, self._build_weight))

        r = int(dw * self.DESIGN_COLOR.red() +
                cw * self.CLIENT_COLOR.red() +
                bw * self.BUILD_COLOR.red())
        g = int(dw * self.DESIGN_COLOR.green() +
                cw * self.CLIENT_COLOR.green() +
                bw * self.BUILD_COLOR.green())
        b = int(dw * self.DESIGN_COLOR.blue() +
                cw * self.CLIENT_COLOR.blue() +
                bw * self.BUILD_COLOR.blue())

        # Clamp to valid range [0, 255]
        r = max(0, min(255, r))
        g = max(0, min(255, g))
        b = max(0, min(255, b))

        return QColor(r, g, b)

    def paintEvent(self, event):
        """Draw the triangle and puck."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        top, bl, br = self._get_triangle_points()

        # Draw filled triangle with gradient
        path = QPainterPath()
        path.moveTo(top)
        path.lineTo(bl)
        path.lineTo(br)
        path.closeSubpath()

        # Subtle fill
        fill_color = QColor(60, 60, 70, 100)
        painter.fillPath(path, QBrush(fill_color))

        # Draw triangle outline
        pen = QPen(QColor(100, 100, 110), 2)
        painter.setPen(pen)
        painter.drawPath(path)

        # Draw corner indicators with colors
        corner_radius = 6

        # Design corner (top)
        painter.setBrush(QBrush(self.DESIGN_COLOR))
        painter.setPen(QPen(self.DESIGN_COLOR.darker(120), 1))
        painter.drawEllipse(top, corner_radius, corner_radius)

        # Client corner (bottom-left)
        painter.setBrush(QBrush(self.CLIENT_COLOR))
        painter.setPen(QPen(self.CLIENT_COLOR.darker(120), 1))
        painter.drawEllipse(bl, corner_radius, corner_radius)

        # Build corner (bottom-right)
        painter.setBrush(QBrush(self.BUILD_COLOR))
        painter.setPen(QPen(self.BUILD_COLOR.darker(120), 1))
        painter.drawEllipse(br, corner_radius, corner_radius)

        # Draw labels
        font = QFont()
        font.setPointSize(8)
        painter.setFont(font)
        painter.setPen(QPen(QColor(200, 200, 200)))

        fm = QFontMetrics(font)

        # Design label (above top)
        design_rect = fm.boundingRect(self.DESIGN)
        painter.drawText(
            int(top.x() - design_rect.width() / 2),
            int(top.y() - corner_radius - 4),
            self.DESIGN
        )

        # Client label (below bottom-left)
        client_rect = fm.boundingRect(self.CLIENT)
        painter.drawText(
            int(bl.x() - client_rect.width() / 2),
            int(bl.y() + corner_radius + fm.height()),
            self.CLIENT
        )

        # Build label (below bottom-right)
        build_rect = fm.boundingRect(self.BUILD)
        painter.drawText(
            int(br.x() - build_rect.width() / 2),
            int(br.y() + corner_radius + fm.height()),
            self.BUILD
        )

        # Draw puck
        puck_pos = self._barycentric_to_cartesian(
            self._design_weight, self._client_weight, self._build_weight
        )

        # Puck shadow
        shadow_color = QColor(0, 0, 0, 50)
        painter.setBrush(QBrush(shadow_color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(
            puck_pos + QPointF(2, 2),
            self._puck_radius, self._puck_radius
        )

        # Puck body with blend color
        puck_color = self._get_blend_color()
        if self._hover or self._dragging:
            puck_color = puck_color.lighter(120)

        # Gradient for 3D effect
        gradient = QRadialGradient(
            puck_pos - QPointF(3, 3),
            self._puck_radius * 1.5
        )
        gradient.setColorAt(0, puck_color.lighter(130))
        gradient.setColorAt(1, puck_color)

        painter.setBrush(QBrush(gradient))
        painter.setPen(QPen(puck_color.darker(150), 2))
        painter.drawEllipse(puck_pos, self._puck_radius, self._puck_radius)

        # Draw weight percentages if hovering
        if self._hover or self._dragging:
            info_font = QFont()
            info_font.setPointSize(7)
            painter.setFont(info_font)
            painter.setPen(QPen(QColor(180, 180, 180)))

            info_text = f"D:{self._design_weight:.0%} C:{self._client_weight:.0%} B:{self._build_weight:.0%}"
            info_rect = QFontMetrics(info_font).boundingRect(info_text)
            painter.drawText(
                int((self.width() - info_rect.width()) / 2),
                self.height() - 2,
                info_text
            )

    def mousePressEvent(self, event):
        """Start dragging if click is on or near puck."""
        if event.button() == Qt.MouseButton.LeftButton:
            puck_pos = self._barycentric_to_cartesian(
                self._design_weight, self._client_weight, self._build_weight
            )

            # Check if click is near puck
            dx = event.position().x() - puck_pos.x()
            dy = event.position().y() - puck_pos.y()
            dist = math.sqrt(dx * dx + dy * dy)

            if dist <= self._puck_radius * 2:  # Generous click area
                self._dragging = True
                self.update()
            else:
                # Click elsewhere in triangle - move puck there
                design, client, build = self._cartesian_to_barycentric(event.position())
                design, client, build = self._clamp_to_triangle(design, client, build)

                self._design_weight = design
                self._client_weight = client
                self._build_weight = build

                self.gravity_changed.emit(design, client, build)
                self.update()

    def mouseMoveEvent(self, event):
        """Update puck position while dragging."""
        puck_pos = self._barycentric_to_cartesian(
            self._design_weight, self._client_weight, self._build_weight
        )

        # Check hover state
        dx = event.position().x() - puck_pos.x()
        dy = event.position().y() - puck_pos.y()
        dist = math.sqrt(dx * dx + dy * dy)

        was_hover = self._hover
        self._hover = dist <= self._puck_radius * 2

        if was_hover != self._hover:
            self.update()

        if self._dragging:
            design, client, build = self._cartesian_to_barycentric(event.position())
            design, client, build = self._clamp_to_triangle(design, client, build)

            self._design_weight = design
            self._client_weight = client
            self._build_weight = build

            self.gravity_changed.emit(design, client, build)
            self.update()

    def mouseReleaseEvent(self, event):
        """Stop dragging."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            self.update()

    def leaveEvent(self, event):
        """Handle mouse leaving widget."""
        self._hover = False
        self.update()

    def keyPressEvent(self, event):
        """Handle keyboard shortcuts for gravity presets."""
        key = event.key()

        if key == Qt.Key.Key_D:
            self._animate_to(1.0, 0.0, 0.0, TRANSITION_CONFIG['keyboard'])
        elif key == Qt.Key.Key_C:
            self._animate_to(0.0, 1.0, 0.0, TRANSITION_CONFIG['keyboard'])
        elif key == Qt.Key.Key_B:
            self._animate_to(0.0, 0.0, 1.0, TRANSITION_CONFIG['keyboard'])
        elif key == Qt.Key.Key_0 or key == Qt.Key.Key_R:
            # Reset to center
            self._animate_to(0.33, 0.33, 0.34, TRANSITION_CONFIG['keyboard'])
        else:
            super().keyPressEvent(event)

    def _animate_to(self, design: float, client: float, build: float, duration_ms: int):
        """Start animated transition to target weights."""
        if duration_ms <= 0:
            # Immediate change
            self._design_weight = design
            self._client_weight = client
            self._build_weight = build
            self.gravity_changed.emit(design, client, build)
            self.update()
            return

        # Store start and target values
        self._anim_start_design = self._design_weight
        self._anim_start_client = self._client_weight
        self._anim_start_build = self._build_weight
        self._target_design = design
        self._target_client = client
        self._target_build = build

        self._anim_duration = duration_ms
        self._anim_elapsed = 0
        self._animating = True

        # Start timer at ~60fps
        self._anim_timer.start(16)

    def _update_animation(self):
        """Update animation frame."""
        self._anim_elapsed += 16

        # Calculate progress with easing
        t = min(1.0, self._anim_elapsed / self._anim_duration)
        # Ease-in-out quadratic
        if t < 0.5:
            eased_t = 2 * t * t
        else:
            eased_t = 1 - pow(-2 * t + 2, 2) / 2

        # Interpolate weights
        self._design_weight = self._anim_start_design + (self._target_design - self._anim_start_design) * eased_t
        self._client_weight = self._anim_start_client + (self._target_client - self._anim_start_client) * eased_t
        self._build_weight = self._anim_start_build + (self._target_build - self._anim_start_build) * eased_t

        # Emit during animation for live updates
        self.gravity_changed.emit(self._design_weight, self._client_weight, self._build_weight)
        self.update()

        # Check if done
        if t >= 1.0:
            self._anim_timer.stop()
            self._animating = False

    # Public API

    def get_weights(self) -> Tuple[float, float, float]:
        """Get current gravity weights (design, client, build)."""
        return self._design_weight, self._client_weight, self._build_weight

    def set_weights(self, design: float, client: float, build: float, animate: bool = False):
        """Set gravity weights programmatically.

        Args:
            design: Design weight (0-1)
            client: Client weight (0-1)
            build: Build weight (0-1)
            animate: If True, animate to the new position
        """
        design, client, build = self._clamp_to_triangle(design, client, build)

        if animate:
            self._animate_to(design, client, build, TRANSITION_CONFIG['preset_switch'])
        else:
            self._design_weight = design
            self._client_weight = client
            self._build_weight = build
            self.gravity_changed.emit(design, client, build)
            self.update()

    def set_design(self):
        """Animate to Design corner."""
        self._animate_to(1.0, 0.0, 0.0, TRANSITION_CONFIG['preset_switch'])

    def set_client(self):
        """Animate to Client corner."""
        self._animate_to(0.0, 1.0, 0.0, TRANSITION_CONFIG['preset_switch'])

    def set_build(self):
        """Animate to Build corner."""
        self._animate_to(0.0, 0.0, 1.0, TRANSITION_CONFIG['preset_switch'])

    def set_center(self):
        """Animate to center (equal blend)."""
        self._animate_to(0.33, 0.33, 0.34, TRANSITION_CONFIG['preset_switch'])

    def set_design_client(self):
        """Animate to Design-Client edge midpoint."""
        self._animate_to(0.5, 0.5, 0.0, TRANSITION_CONFIG['preset_switch'])

    def set_client_build(self):
        """Animate to Client-Build edge midpoint."""
        self._animate_to(0.0, 0.5, 0.5, TRANSITION_CONFIG['preset_switch'])

    def set_design_build(self):
        """Animate to Design-Build edge midpoint."""
        self._animate_to(0.5, 0.0, 0.5, TRANSITION_CONFIG['preset_switch'])
