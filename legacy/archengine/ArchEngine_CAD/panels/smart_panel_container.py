"""
Smart Panel Container - Widget that manages context-aware panels.

Panels fade in/out based on workflow, LOD, gravity, and selection.
"""
from typing import Dict, Optional, List

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QStackedWidget, QGraphicsOpacityEffect
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QColor

from panels.smart_panels import (
    PanelManager, PanelDefinition, PanelContext, PanelState,
    GravityState, LODState, Selection, WorkflowStage, TaskType,
    ElementType, detect_workflow_stage, LODLevel
)
from panels.panel_registry import get_panel_registry


class ContextIndicator(QFrame):
    """
    Shows current context (Gravity + LOD) so users always know
    why panels are visible/hidden.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._design = 0.33
        self._client = 0.33
        self._build = 0.34
        self._lod = 2
        self._workflow = "legi_cad"

        self._setup_ui()

    def _setup_ui(self):
        self.setStyleSheet("""
            ContextIndicator {
                background: rgba(30, 30, 35, 0.9);
                border: 1px solid rgba(255, 255, 255, 0.15);
                border-radius: 4px;
            }
        """)
        self.setFixedHeight(50)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(12)

        # Gravity indicators
        gravity_frame = QFrame()
        gravity_layout = QHBoxLayout(gravity_frame)
        gravity_layout.setContentsMargins(0, 0, 0, 0)
        gravity_layout.setSpacing(8)

        # Design (blue)
        self._design_label = self._create_gravity_label("D", "#6495ED")
        gravity_layout.addWidget(self._design_label)

        # Client (green)
        self._client_label = self._create_gravity_label("C", "#90EE90")
        gravity_layout.addWidget(self._client_label)

        # Build (orange)
        self._build_label = self._create_gravity_label("B", "#FFA500")
        gravity_layout.addWidget(self._build_label)

        layout.addWidget(gravity_frame)

        # Separator
        sep = QLabel("│")
        sep.setStyleSheet("color: rgba(255, 255, 255, 0.2);")
        layout.addWidget(sep)

        # LOD indicator
        self._lod_label = QLabel("LOD 2")
        self._lod_label.setStyleSheet("""
            font-size: 11px;
            font-weight: bold;
            color: rgba(255, 255, 255, 0.9);
        """)
        layout.addWidget(self._lod_label)

        # LOD description
        self._lod_desc = QLabel("Walls")
        self._lod_desc.setStyleSheet("""
            font-size: 10px;
            color: rgba(255, 255, 255, 0.5);
        """)
        layout.addWidget(self._lod_desc)

        layout.addStretch()

        # Workflow stage indicator
        self._workflow_label = QLabel("LegiCAD")
        self._workflow_label.setStyleSheet("""
            font-size: 10px;
            font-weight: bold;
            color: rgba(255, 255, 255, 0.6);
            text-transform: uppercase;
            letter-spacing: 1px;
        """)
        layout.addWidget(self._workflow_label)

    def _create_gravity_label(self, letter: str, color: str) -> QLabel:
        """Create a gravity percentage label."""
        label = QLabel(f"{letter}: 33%")
        label.setStyleSheet(f"""
            font-size: 10px;
            font-weight: bold;
            color: {color};
        """)
        return label

    def update_gravity(self, design: float, client: float, build: float):
        """Update gravity display."""
        self._design = design
        self._client = client
        self._build = build

        self._design_label.setText(f"D: {int(design * 100)}%")
        self._client_label.setText(f"C: {int(client * 100)}%")
        self._build_label.setText(f"B: {int(build * 100)}%")

        # Highlight dominant gravity
        dominant = max(design, client, build)
        self._design_label.setStyleSheet(f"""
            font-size: 10px;
            font-weight: bold;
            color: {'#6495ED' if design < dominant else 'rgba(100, 149, 237, 0.5)'};
        """)
        self._client_label.setStyleSheet(f"""
            font-size: 10px;
            font-weight: bold;
            color: {'#90EE90' if client < dominant else 'rgba(144, 238, 144, 0.5)'};
        """)
        self._build_label.setStyleSheet(f"""
            font-size: 10px;
            font-weight: bold;
            color: {'#FFA500' if build < dominant else 'rgba(255, 165, 0, 0.5)'};
        """)

        # Actually highlight the dominant one
        if design >= client and design >= build:
            self._design_label.setStyleSheet("font-size: 10px; font-weight: bold; color: #6495ED;")
        if client >= design and client >= build:
            self._client_label.setStyleSheet("font-size: 10px; font-weight: bold; color: #90EE90;")
        if build >= design and build >= client:
            self._build_label.setStyleSheet("font-size: 10px; font-weight: bold; color: #FFA500;")

    def update_lod(self, level: int):
        """Update LOD display."""
        self._lod = level
        self._lod_label.setText(f"LOD {level}")

        # LOD descriptions
        lod_names = {
            1: "Topology",
            2: "Walls",
            3: "Fixtures",
            4: "Viewports",
            5: "Documentation"
        }
        self._lod_desc.setText(lod_names.get(level, ""))

        # Update workflow stage based on LOD
        workflow = detect_workflow_stage(level)
        workflow_names = {
            WorkflowStage.LEGI_QBD: "LegiQBD",
            WorkflowStage.LEGI_CAD: "LegiCAD",
            WorkflowStage.LEGI_DOC: "LegiDoc"
        }
        self._workflow_label.setText(workflow_names.get(workflow, ""))


class SmartPanelWidget(QFrame):
    """
    Wrapper for a smart panel with header and opacity control.

    Escher-inspired: panels that aren't in current context rotate back
    on a hinge like in Relativity - still visible but in a different plane.
    """

    minimize_clicked = pyqtSignal(str)  # panel_id
    pin_clicked = pyqtSignal(str)  # panel_id
    panel_hovered = pyqtSignal(str)  # panel_id - emitted when hovering a dimmed panel

    def __init__(self, panel_id: str, name: str, content_widget: QWidget, can_minimize: bool = True, parent=None):
        super().__init__(parent)
        self._panel_id = panel_id
        self._name = name
        self._can_minimize = can_minimize
        self._is_ghost = False
        self._is_dimmed = False  # Any opacity < 1.0
        self._why_hidden = ""
        self._content_widget = content_widget
        self._hover_emitted = False

        # Hinge animation state (0 = facing, 1 = rotated back)
        self._hinge_angle = 0.0
        self._target_hinge = 0.0
        self._hinge_timer = None

        # Hover state - when hovering, panel is fully active
        self._hover_active = False

        self._setup_ui(content_widget)
        self._setup_opacity()
        self._setup_hinge_animation()
        self.setMouseTracking(True)

    def _setup_ui(self, content_widget: QWidget):
        """Set up the panel UI."""
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet("""
            SmartPanelWidget {
                background: rgba(35, 35, 40, 0.95);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 6px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QFrame()
        header.setStyleSheet("""
            QFrame {
                background: rgba(255, 255, 255, 0.05);
                border-bottom: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 6px 6px 0 0;
            }
        """)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 6, 6, 6)
        header_layout.setSpacing(4)

        # Title
        title = QLabel(self._name)
        title.setStyleSheet("""
            font-size: 11px;
            font-weight: bold;
            color: rgba(255, 255, 255, 0.8);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        """)
        header_layout.addWidget(title)
        header_layout.addStretch()

        # Ghost indicator (shows why hidden)
        self._ghost_label = QLabel("")
        self._ghost_label.setStyleSheet("""
            font-size: 9px;
            color: rgba(255, 200, 100, 0.8);
            font-style: italic;
        """)
        self._ghost_label.hide()
        header_layout.addWidget(self._ghost_label)

        # Pin button (keep visible regardless of context)
        self._pin_btn = QPushButton("📌")
        self._pin_btn.setFixedSize(20, 20)
        self._pin_btn.setCheckable(True)
        self._pin_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                color: rgba(255, 255, 255, 0.3);
                font-size: 11px;
            }
            QPushButton:hover {
                color: rgba(255, 255, 255, 0.7);
            }
            QPushButton:checked {
                color: rgba(100, 200, 255, 0.9);
            }
        """)
        self._pin_btn.setToolTip("Pin panel (keep visible)")
        self._pin_btn.clicked.connect(lambda: self.pin_clicked.emit(self._panel_id))
        header_layout.addWidget(self._pin_btn)

        # Minimize button
        if self._can_minimize:
            minimize_btn = QPushButton("−")
            minimize_btn.setFixedSize(20, 20)
            minimize_btn.setStyleSheet("""
                QPushButton {
                    background: transparent;
                    border: none;
                    color: rgba(255, 255, 255, 0.5);
                    font-size: 14px;
                }
                QPushButton:hover {
                    color: rgba(255, 255, 255, 0.9);
                }
            """)
            minimize_btn.clicked.connect(lambda: self.minimize_clicked.emit(self._panel_id))
            header_layout.addWidget(minimize_btn)

        layout.addWidget(header)

        # Content
        content_widget.setStyleSheet("""
            background: transparent;
            color: rgba(255, 255, 255, 0.9);
        """)
        layout.addWidget(content_widget)

    def _setup_opacity(self):
        """Set up opacity effect for fading."""
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(1.0)
        self.setGraphicsEffect(self._opacity_effect)

    def _setup_hinge_animation(self):
        """Set up hinge rotation animation timer."""
        self._hinge_timer = QTimer(self)
        self._hinge_timer.timeout.connect(self._update_hinge)
        self._hinge_timer.setInterval(16)  # ~60fps

    def _update_hinge(self):
        """Animate hinge rotation."""
        # Ease toward target
        diff = self._target_hinge - self._hinge_angle
        if abs(diff) < 0.01:
            self._hinge_angle = self._target_hinge
            self._hinge_timer.stop()
        else:
            self._hinge_angle += diff * 0.15  # Smooth easing

        self._apply_hinge_transform()

    def _apply_hinge_transform(self):
        """Apply the hinge rotation effect using 2D transforms.

        Simulates 3D rotation by:
        - Horizontal scale (narrower = more rotated)
        - Horizontal offset (perspective shift)
        - Slight vertical squish
        - Shadow/depth styling
        """
        angle = self._hinge_angle  # 0 = facing, 1 = rotated 75°

        # Scale: 1.0 facing -> 0.4 when rotated back
        scale_x = 1.0 - (angle * 0.6)

        # Horizontal offset to simulate perspective pivot point
        # Panel appears to rotate from its left edge (like a door hinge)
        width = self.width()
        offset_x = int(width * angle * 0.3)

        # Apply transform via stylesheet margins and scaling
        # We use negative margin + reduced width to simulate the rotation
        if angle > 0.05:
            # Rotated back - show depth
            depth_shadow = int(angle * 20)
            border_fade = int(255 * (1 - angle * 0.5))

            self.setStyleSheet(f"""
                SmartPanelWidget {{
                    background: rgba(35, 35, 40, {0.95 - angle * 0.3});
                    border: 1px solid rgba({border_fade}, {border_fade}, {int(border_fade * 1.1)}, 0.15);
                    border-left: 3px solid rgba(100, 100, 120, {0.3 + angle * 0.3});
                    border-radius: 6px;
                    margin-left: {offset_x}px;
                    margin-right: {int(offset_x * 0.5)}px;
                }}
            """)

            # Reduce effective width to simulate perspective compression
            # This creates the "turning away" visual
            if hasattr(self, '_original_max_width'):
                compressed_width = int(self._original_max_width * scale_x)
                self.setMaximumWidth(max(100, compressed_width))
        else:
            # Facing forward - normal style
            self.setStyleSheet("""
                SmartPanelWidget {
                    background: rgba(35, 35, 40, 0.95);
                    border: 1px solid rgba(255, 255, 255, 0.1);
                    border-radius: 6px;
                    margin-left: 0px;
                    margin-right: 0px;
                }
            """)
            if hasattr(self, '_original_max_width'):
                self.setMaximumWidth(self._original_max_width)

    def set_hinge_angle(self, angle: float):
        """Set target hinge angle (0 = facing, 1 = rotated back ~75°).

        The panel will animate smoothly to this angle.
        """
        # Store original width on first call
        if not hasattr(self, '_original_max_width'):
            self._original_max_width = self.maximumWidth()
            if self._original_max_width > 10000:  # QWIDGETSIZE_MAX
                self._original_max_width = 300

        # Don't update hinge if hovering (except when called from enterEvent with angle=0)
        if self._hover_active and angle > 0:
            return

        new_target = max(0.0, min(1.0, angle))

        # Only update if target changed significantly (prevents jitter)
        if abs(new_target - self._target_hinge) < 0.02:
            return

        self._target_hinge = new_target

        if not self._hinge_timer.isActive():
            self._hinge_timer.start()

    def set_opacity(self, opacity: float):
        """Set panel opacity (0-1)."""
        # Don't update if hovering - panel stays fully visible
        if self._hover_active:
            return

        # Only update if changed significantly (prevents jitter)
        current = self._opacity_effect.opacity()
        if abs(opacity - current) < 0.02:
            return

        self._opacity_effect.setOpacity(opacity)
        self._is_dimmed = opacity < 0.95  # Track if panel is dimmed

        # Hide completely when fully transparent
        if opacity < 0.01:
            self.hide()
        else:
            self.show()

    def get_opacity(self) -> float:
        """Get current opacity."""
        return self._opacity_effect.opacity()

    def set_ghost_mode(self, is_ghost: bool, why_hidden: str = ""):
        """Set ghost mode - shows panel faintly with reason why it's hidden."""
        self._is_ghost = is_ghost
        self._why_hidden = why_hidden

        if is_ghost and why_hidden:
            self._ghost_label.setText(why_hidden)
            self._ghost_label.show()
            # Dim the content when in ghost mode
            self._content_widget.setEnabled(False)
            self.setStyleSheet("""
                SmartPanelWidget {
                    background: rgba(35, 35, 40, 0.5);
                    border: 1px dashed rgba(255, 200, 100, 0.3);
                    border-radius: 6px;
                }
            """)
            self.setToolTip(f"Panel hidden: {why_hidden}")
        else:
            self._ghost_label.hide()
            self._content_widget.setEnabled(True)
            self.setStyleSheet("""
                SmartPanelWidget {
                    background: rgba(35, 35, 40, 0.95);
                    border: 1px solid rgba(255, 255, 255, 0.1);
                    border-radius: 6px;
                }
            """)
            self.setToolTip("")

    def set_pinned(self, pinned: bool):
        """Update pin button state."""
        self._pin_btn.setChecked(pinned)

    def enterEvent(self, event):
        """When hovering a panel, fully activate it temporarily."""
        # Emit signal to center gravity
        self.panel_hovered.emit(self._panel_id)

        # Temporarily make panel fully visible and facing
        self._hover_active = True
        self._opacity_effect.setOpacity(1.0)
        self.set_hinge_angle(0.0)  # Face forward
        self._content_widget.setEnabled(True)

        # Visual feedback - highlight border
        self.setStyleSheet("""
            SmartPanelWidget {
                background: rgba(35, 35, 40, 0.98);
                border: 2px solid rgba(100, 200, 255, 0.5);
                border-radius: 6px;
            }
        """)

        super().enterEvent(event)

    def leaveEvent(self, event):
        """Reset hover state on leave - panel returns to its computed state."""
        self._hover_active = False
        # Let the update loop restore the correct opacity/hinge
        super().leaveEvent(event)

    @property
    def is_ghost(self) -> bool:
        return self._is_ghost

    @property
    def is_dimmed(self) -> bool:
        return self._is_dimmed

    @property
    def panel_id(self) -> str:
        return self._panel_id


class SmartPanelContainer(QWidget):
    """
    Container that manages smart panels based on context.

    Connect to gravity_changed and lod_changed signals to update context.
    """

    # Signals
    context_changed = pyqtSignal()
    request_gravity_center = pyqtSignal()  # Emitted when user hovers a dimmed panel
    request_lod_change = pyqtSignal(int)  # Emitted with the LOD level the panel needs
    material_assigned = pyqtSignal(str, str)  # Emitted when material is assigned (element_type, material_id)

    def __init__(self, parent=None):
        super().__init__(parent)

        self._panel_manager = PanelManager()
        self._panel_widgets: Dict[str, SmartPanelWidget] = {}
        self._update_timer: Optional[QTimer] = None

        self._setup_ui()
        self._register_panels()
        self._start_update_loop()

    def _setup_ui(self):
        """Set up the container UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)

        # Context indicator at top - always shows current gravity/LOD
        self._context_indicator = ContextIndicator()
        layout.addWidget(self._context_indicator)

        # Scroll area for panels
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._panel_area = QWidget()
        self._panel_layout = QVBoxLayout(self._panel_area)
        self._panel_layout.setContentsMargins(0, 0, 0, 0)
        self._panel_layout.setSpacing(8)
        self._panel_layout.addStretch()

        scroll.setWidget(self._panel_area)
        layout.addWidget(scroll)

    def _register_panels(self):
        """Register all panels from registry."""
        for definition in get_panel_registry():
            self._panel_manager.register_panel(definition)
            self._create_panel_widget(definition)

    def _create_panel_widget(self, definition: PanelDefinition):
        """Create widget for a panel definition."""
        # Instantiate the content widget
        content = definition.widget_class()

        # Special handling for Navigation panel - connect signals
        if definition.id == 'navigation':
            self._connect_navigation_panel(content)

        # Special handling for Material picker panel - forward signal
        if definition.id == 'material_picker' and hasattr(content, 'material_assigned'):
            content.material_assigned.connect(self.material_assigned.emit)

        # Wrap in smart panel widget
        panel_widget = SmartPanelWidget(
            panel_id=definition.id,
            name=definition.name,
            content_widget=content,
            can_minimize=definition.can_minimize
        )
        panel_widget.minimize_clicked.connect(self._on_minimize_clicked)
        panel_widget.pin_clicked.connect(self._on_pin_clicked)
        panel_widget.panel_hovered.connect(self._on_panel_hovered)

        # Start hidden (except core panels)
        if definition.id in ('navigation', 'chat'):
            panel_widget.set_opacity(1.0)
            panel_widget.show()
        else:
            panel_widget.set_opacity(0.0)
            panel_widget.hide()

        # Add to layout (before stretch)
        self._panel_layout.insertWidget(self._panel_layout.count() - 1, panel_widget)
        self._panel_widgets[definition.id] = panel_widget

    def _connect_navigation_panel(self, nav_panel):
        """Connect Navigation panel's gravity and LOD signals."""
        # Connect gravity triangle
        if hasattr(nav_panel, 'gravity_triangle'):
            nav_panel.gravity_triangle.gravity_changed.connect(self._on_gravity_changed)

        # Connect LOD indicator
        if hasattr(nav_panel, 'lod_indicator'):
            nav_panel.lod_indicator.lod_changed.connect(self._on_lod_changed)

    def _on_gravity_changed(self, design: float, client: float, build: float):
        """Handle gravity changes from Navigation panel."""
        self.update_gravity(design, client, build)

    def _on_lod_changed(self, level: int, transition: float):
        """Handle LOD changes from Navigation panel."""
        self.update_lod(level, transition)

    def _start_update_loop(self):
        """Start the panel update timer."""
        self._update_timer = QTimer(self)
        self._update_timer.timeout.connect(self._update_panels)
        self._update_timer.start(33)  # ~30 FPS

    def _update_panels(self):
        """Update panel visibility based on context."""
        # Get updated opacities, ghost states, and reasons
        results = self._panel_manager.update()

        # Apply to widgets
        for panel_id, (opacity, is_ghost, why_hidden) in results.items():
            widget = self._panel_widgets.get(panel_id)
            if widget:
                widget.set_opacity(opacity)
                widget.set_ghost_mode(is_ghost, why_hidden)

                # Escher hinge effect: less relevant panels rotate back
                # opacity 1.0 = facing (angle 0), opacity 0.3 = rotated back (angle ~0.7)
                if opacity >= 0.95:
                    hinge_angle = 0.0  # Fully facing
                elif opacity <= 0.3:
                    hinge_angle = 0.7  # Rotated back significantly
                else:
                    # Interpolate: lower opacity = more rotation
                    hinge_angle = (0.95 - opacity) / 0.65 * 0.7

                widget.set_hinge_angle(hinge_angle)

    def _on_minimize_clicked(self, panel_id: str):
        """Handle panel minimize button click."""
        self._panel_manager.toggle_minimize(panel_id)

    def _on_pin_clicked(self, panel_id: str):
        """Handle panel pin button click."""
        is_pinned = self._panel_manager.toggle_pin(panel_id)
        widget = self._panel_widgets.get(panel_id)
        if widget:
            widget.set_pinned(is_pinned)

    def _on_panel_hovered(self, panel_id: str):
        """Handle hover on a dimmed panel - request gravity center and LOD change."""
        # When user hovers a dimmed panel, request gravity to center
        self.request_gravity_center.emit()

        # Also request LOD change to what the panel needs
        definition = self._panel_manager._definitions.get(panel_id)
        if definition and definition.conditions:
            # Use the minimum LOD the panel requires
            target_lod = definition.conditions.lod_min
            self.request_lod_change.emit(target_lod)

    # =========================================================================
    # Public API - Context Updates
    # =========================================================================

    def update_gravity(self, design: float, client: float, build: float):
        """Update gravity state from Gravity Triangle."""
        self._panel_manager.update_gravity(design, client, build)
        self._context_indicator.update_gravity(design, client, build)
        self.context_changed.emit()

    def update_lod(self, level: int, transition: float = 0.0):
        """Update LOD state from LOD indicator."""
        self._panel_manager.update_lod(level, transition)
        self._context_indicator.update_lod(level)

        # Auto-detect workflow stage from LOD
        workflow = detect_workflow_stage(level)
        self._panel_manager.update_workflow(workflow)

        self.context_changed.emit()

    def update_selection(self, element_ids: List[str], element_types: List[str]):
        """Update selection state."""
        # Convert string types to ElementType enum
        types = []
        for t in element_types:
            try:
                types.append(ElementType(t.lower()))
            except ValueError:
                pass

        self._panel_manager.update_selection(element_ids, types)
        self.context_changed.emit()

    def update_task(self, task: str):
        """Update active task."""
        try:
            task_type = TaskType(task.lower())
        except ValueError:
            task_type = TaskType.IDLE

        self._panel_manager.update_task(task_type)
        self.context_changed.emit()

    def get_visible_panel_count(self) -> int:
        """Get number of currently visible panels."""
        return len(self._panel_manager.get_visible_panels())

    def get_workflow_stage(self) -> str:
        """Get current workflow stage name."""
        return self._panel_manager._context.workflow_stage.value

    def initialize_panel(self, panel_id: str, **kwargs):
        """Initialize a panel with dependencies (document, viewport, etc.).

        This allows passing document/viewport to panels that need them.
        The panel must have corresponding set_* methods.

        Example:
            container.initialize_panel('material_picker', document=self.document, viewport=self.viewport_3d)
        """
        widget = self._panel_widgets.get(panel_id)
        if not widget:
            return

        # Get the content widget (first child of SmartPanelWidget's layout)
        content_widget = None
        for child in widget.findChildren(type(widget._content_widget)):
            content_widget = child
            break

        if not content_widget:
            content_widget = widget._content_widget

        # Call set_* methods for each keyword argument
        for key, value in kwargs.items():
            setter_name = f'set_{key}'
            if hasattr(content_widget, setter_name):
                getattr(content_widget, setter_name)(value)
            # Also try on the wrapper panel (for MaterialPickerPanel)
            elif hasattr(widget, setter_name):
                getattr(widget, setter_name)(value)
