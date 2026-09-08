"""
Solver Parameters Panel
=========================
UI for adjusting QBD solver parameters and seeing their effects on layouts.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSlider, QSpinBox, QDoubleSpinBox,
    QGroupBox, QScrollArea, QPushButton, QCheckBox, QComboBox, QTextEdit, QSplitter
)
from PyQt6.QtCore import Qt, pyqtSignal
import json
from pathlib import Path


class SolverParamsPanel(QWidget):
    """Panel for adjusting solver scoring parameters"""

    params_changed = pyqtSignal(dict)  # Emitted when parameters change

    def __init__(self, config_path=None, parent=None):
        super().__init__(parent)
        self.config_path = config_path or self._find_config_path()
        self.params = self._load_params()

        self._setup_ui()
        self._connect_signals()

    def _find_config_path(self):
        """Find the scoring config file"""
        kernel_path = Path(__file__).parent.parent.parent / "ArchEngine_kernel" / "render_server" / "scoring_config.json"
        if kernel_path.exists():
            return str(kernel_path)
        return None

    def _load_params(self):
        """Load parameters from config file"""
        if not self.config_path:
            return self._get_default_params()

        try:
            with open(self.config_path, 'r') as f:
                config = json.load(f)
                return self._extract_editable_params(config)
        except Exception as e:
            print(f"[SolverPanel] Error loading config: {e}")
            return self._get_default_params()

    def _extract_editable_params(self, config):
        """Extract user-editable parameters from full config"""
        params = {}

        # Extract scoring weights
        weights = config.get("scoring_weights", {})
        for category, values in weights.items():
            if category != "description":
                params[f"weight_{category}"] = {
                    "value": values.get("weight", 0),
                    "description": values.get("description", category),
                    "enabled": values.get("enabled", True)
                }

        # Extract placement scoring
        placement = config.get("placement_scoring", {})
        for key, value in placement.items():
            if key != "description":
                params[f"placement_{key}"] = {
                    "value": value,
                    "description": self._format_param_name(key)
                }

        # Extract solver parameters
        solver = config.get("solver_parameters", {})
        for key, value in solver.items():
            params[f"solver_{key}"] = {
                "value": value,
                "description": self._format_param_name(key)
            }

        return params

    def _get_default_params(self):
        """Get default parameters"""
        return {
            "weight_circulation_completeness": {"value": 300, "description": "All rooms connect to circulation"},
            "weight_constraint_satisfaction": {"value": 200, "description": "Rooms touch as required"},
            "weight_circulation_efficiency": {"value": 15, "description": "Related rooms close together"},
            "weight_zone_organization": {"value": 2, "description": "Public/private zones separated"},
            "weight_room_shape_quality": {"value": 3, "description": "Room proportions reasonable"},
            "weight_exterior_access": {"value": 10, "description": "Rooms get exterior walls"},
            "solver_grid_size": {"value": 2.0, "description": "Placement grid size (ft)"},
            "solver_max_branching_critical": {"value": 500, "description": "Search branches for critical rooms"},
            "solver_max_branching_standard": {"value": 300, "description": "Search branches for standard rooms"},
        }

    def _format_param_name(self, key):
        """Format parameter name for display"""
        return key.replace("_", " ").title()

    def _setup_ui(self):
        """Setup the UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Title and description
        title = QLabel("Solver Parameters")
        title.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(title)

        desc = QLabel("Adjust parameters to control layout generation behavior")
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(desc)

        # Scroll area for parameters
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(10)

        # Scoring Weights Group
        weights_group = QGroupBox("Scoring Weights (Priority)")
        weights_layout = QVBoxLayout()
        self._add_weight_controls(weights_layout)
        weights_group.setLayout(weights_layout)
        content_layout.addWidget(weights_group)

        # Solver Behavior Group
        solver_group = QGroupBox("Solver Behavior")
        solver_layout = QVBoxLayout()
        self._add_solver_controls(solver_layout)
        solver_group.setLayout(solver_layout)
        content_layout.addWidget(solver_group)

        # Description box
        self._add_description_box(content_layout)

        content_layout.addStretch()

        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        # Apply/Reset buttons
        button_layout = QHBoxLayout()
        apply_btn = QPushButton("Apply & Regenerate")
        apply_btn.setStyleSheet("background-color: #4CAF50; color: white; padding: 8px;")
        apply_btn.clicked.connect(self._on_apply)
        button_layout.addWidget(apply_btn)

        reset_btn = QPushButton("Reset to Defaults")
        reset_btn.clicked.connect(self._on_reset)
        button_layout.addWidget(reset_btn)

        layout.addLayout(button_layout)

    def _add_weight_controls(self, layout):
        """Add weight parameter controls"""
        self.weight_sliders = {}

        for param_key, param_data in self.params.items():
            if param_key.startswith("weight_"):
                category = param_key.replace("weight_", "")
                value = param_data["value"]
                description = param_data["description"]

                # Param row
                param_layout = QVBoxLayout()
                param_layout.setSpacing(2)

                # Label with value
                label_layout = QHBoxLayout()
                label = QLabel(f"{category.replace('_', ' ').title()}:")
                label.setStyleSheet("font-weight: bold;")
                value_label = QLabel(f"{value}")
                value_label.setStyleSheet("color: #2196F3; font-weight: bold;")
                value_label.setMinimumWidth(40)
                label_layout.addWidget(label)
                label_layout.addStretch()
                label_layout.addWidget(value_label)
                param_layout.addLayout(label_layout)

                # Description
                desc = QLabel(f"  {description}")
                desc.setStyleSheet("color: #666; font-size: 10px;")
                desc.setWordWrap(True)
                param_layout.addWidget(desc)

                # Slider
                slider = QSlider(Qt.Orientation.Horizontal)
                slider.setRange(0, 500)  # 0 to 500
                slider.setValue(int(value))
                slider.valueChanged.connect(lambda v, k=category, l=value_label: self._on_weight_changed(k, v, l))
                param_layout.addWidget(slider)

                self.weight_sliders[category] = slider
                layout.addLayout(param_layout)

    def _add_solver_controls(self, layout):
        """Add solver behavior controls"""
        self.solver_controls = {}

        for param_key, param_data in self.params.items():
            if param_key.startswith("solver_"):
                param_name = param_key.replace("solver_", "")
                value = param_data["value"]
                description = param_data["description"]

                # Param row
                param_layout = QVBoxLayout()
                param_layout.setSpacing(2)

                # Label
                label = QLabel(f"{param_name.replace('_', ' ').title()}:")
                label.setStyleSheet("font-weight: bold;")
                param_layout.addWidget(label)

                # Description
                desc = QLabel(f"  {description}")
                desc.setStyleSheet("color: #666; font-size: 10px;")
                desc.setWordWrap(True)
                param_layout.addWidget(desc)

                # Control based on type
                if isinstance(value, float):
                    control = QDoubleSpinBox()
                    control.setRange(0.5, 10.0)
                    control.setSingleStep(0.5)
                    control.setValue(float(value))
                else:
                    control = QSpinBox()
                    control.setRange(50, 1000)
                    control.setSingleStep(50)
                    control.setValue(int(value))

                control.valueChanged.connect(lambda v, k=param_name: self._on_solver_param_changed(k, v))
                param_layout.addWidget(control)

                self.solver_controls[param_name] = control
                layout.addLayout(param_layout)

    def _add_description_box(self, layout):
        """Add description text box showing what each parameter does"""
        desc_group = QGroupBox("Parameter Guide")
        desc_layout = QVBoxLayout()

        guide = QTextEdit()
        guide.setReadOnly(True)
        guide.setMaximumHeight(150)
        guide.setHtml("""
        <h3>How Parameters Affect Layout</h3>
        <ul>
        <li><b>Circulation Completeness</b>: Higher = All rooms must connect to hallways (300-500)</li>
        <li><b>Constraint Satisfaction</b>: Higher = Rooms must touch as specified (100-300)</li>
        <li><b>Circulation Efficiency</b>: Higher = Related rooms closer together (5-50)</li>
        <li><b>Zone Organization</b>: Higher = Public/private areas separated (1-10)</li>
        <li><b>Room Shape Quality</b>: Higher = Better room proportions (1-20)</li>
        <li><b>Exterior Access</b>: Higher = More rooms get outside walls (5-30)</li>
        <li><b>Grid Size</b>: Smaller = More precise placement, slower (1.0-4.0)</li>
        <li><b>Branching</b>: Higher = More options explored, slower (100-500)</li>
        </ul>
        """)
        desc_layout.addWidget(guide)
        desc_group.setLayout(desc_layout)
        layout.addWidget(desc_group)

    def _connect_signals(self):
        """Connect signals"""
        pass

    def _on_weight_changed(self, category, value, label):
        """Handle weight slider change"""
        label.setText(str(value))

    def _on_solver_param_changed(self, param_name, value):
        """Handle solver parameter change"""
        pass

    def _on_apply(self):
        """Apply parameters and regenerate"""
        # Collect all current values
        overrides = {"scoring_weights": {}, "solver_parameters": {}}

        for category, slider in self.weight_sliders.items():
            overrides["scoring_weights"][category] = {"weight": slider.value()}

        for param_name, control in self.solver_controls.items():
            overrides["solver_parameters"][param_name] = control.value()

        self.params_changed.emit(overrides)

        # Show feedback
        self._show_feedback_message()

    def _on_reset(self):
        """Reset to default parameters"""
        self.params = self._get_default_params()
        # Update all controls
        # TODO: Implement UI update
        self._show_feedback_message("Reset to defaults")

    def _show_feedback_message(self, msg="Parameters updated. Generate new layout to see effects."):
        """Show feedback in status area"""
        # Could emit signal or show in status bar
        print(f"[SolverPanel] {msg}")
