"""
Viewport Panel - 3D viewport display controls.

Provides UI for section clipping, material style, and post-processing settings.
"""
from typing import Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
    QCheckBox, QComboBox, QPushButton, QGroupBox, QSlider,
    QDoubleSpinBox, QFrame, QScrollArea
)
from PyQt6.QtCore import Qt, pyqtSignal

from panels.gravity_triangle import GravityTriangleWidget
from panels.lod_indicator import LODControlWidget, LODLevel, LOD_INFO


# Material style constants
MATERIAL_STYLES = ["Realistic", "Clean", "Schematic", "Blueprint"]

# Axis names
AXIS_NAMES = ["X (Left/Right)", "Y (Up/Down)", "Z (Front/Back)"]

# Tonemap modes
TONEMAP_MODES = ["Reinhard", "ACES", "Uncharted2"]

# Visualization modes (must match arch_api.h order)
VIZ_MODES = ["Structural", "Thermal", "Lighting", "Acoustic", "Material", "Wireframe"]



class ViewportPanel(QWidget):
    """
    Panel for controlling 3D viewport display settings.

    Controls section clipping planes and material rendering styles.
    """

    # Signals for when settings change
    material_style_changed = pyqtSignal(int)  # 0-3
    clipping_changed = pyqtSignal()
    gravity_changed = pyqtSignal(float, float, float)  # design, client, build
    lod_changed = pyqtSignal(int, float)  # level (1-5), transition (0-1)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._viewport = None
        self._updating = False
        self._lod_level = 1
        self._gravity = (0.33, 0.33, 0.34)

        self._setup_ui()

    def _setup_ui(self):
        """Set up the panel UI."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Scrollable content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        scroll_content = QWidget()
        content_layout = QVBoxLayout(scroll_content)
        content_layout.setContentsMargins(5, 5, 5, 5)
        content_layout.setSpacing(8)

        # Header
        header = QLabel("3D Controls")
        header.setStyleSheet("font-weight: bold; font-size: 12px;")
        content_layout.addWidget(header)

        # Escher Controls: Gravity + LOD side by side
        escher_layout = QHBoxLayout()
        escher_layout.setSpacing(10)

        # Gravity Triangle (Perspective Blend)
        self._create_gravity_group(escher_layout)

        # LOD Indicator
        self._create_lod_group(escher_layout)

        content_layout.addLayout(escher_layout)

        # Camera Settings Section
        self._create_camera_group(content_layout)

        # Material Style Section
        self._create_material_group(content_layout)

        # Section Clipping Section
        self._create_clipping_group(content_layout)

        # Section Box Section
        self._create_section_box_group(content_layout)

        # Quick Presets Section
        self._create_presets_group(content_layout)

        # Lighting & Shadows Section
        self._create_lighting_group(content_layout)

        # Post-Processing Section
        self._create_postprocess_group(content_layout)

        content_layout.addStretch()
        scroll.setWidget(scroll_content)
        main_layout.addWidget(scroll)

    def _create_gravity_group(self, parent_layout):
        """Create the gravity triangle perspective control."""
        group = QGroupBox("Perspective")
        layout = QVBoxLayout(group)
        layout.setSpacing(5)

        # Gravity triangle widget
        self.gravity_triangle = GravityTriangleWidget()
        self.gravity_triangle.gravity_changed.connect(self._on_gravity_changed)
        layout.addWidget(self.gravity_triangle, alignment=Qt.AlignmentFlag.AlignCenter)

        # Quick preset buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(3)

        btn_design = QPushButton("D")
        btn_design.setToolTip("Design: relationships, topology")
        btn_design.setMaximumWidth(30)
        btn_design.clicked.connect(self.gravity_triangle.set_design)
        btn_layout.addWidget(btn_design)

        btn_client = QPushButton("C")
        btn_client.setToolTip("Client: realistic, materials")
        btn_client.setMaximumWidth(30)
        btn_client.clicked.connect(self.gravity_triangle.set_client)
        btn_layout.addWidget(btn_client)

        btn_build = QPushButton("B")
        btn_build.setToolTip("Build: coordinates, specs")
        btn_build.setMaximumWidth(30)
        btn_build.clicked.connect(self.gravity_triangle.set_build)
        btn_layout.addWidget(btn_build)

        layout.addLayout(btn_layout)

        parent_layout.addWidget(group)

    def _create_lod_group(self, parent_layout):
        """Create the LOD indicator control."""
        group = QGroupBox("LOD")
        layout = QVBoxLayout(group)
        layout.setSpacing(5)

        # LOD indicator widget
        self.lod_indicator = LODControlWidget()
        self.lod_indicator.lod_changed.connect(self._on_lod_changed)
        layout.addWidget(self.lod_indicator)

        parent_layout.addWidget(group)

    def _create_camera_group(self, parent_layout):
        """Create camera view settings controls."""
        group = QGroupBox("Camera")
        layout = QFormLayout(group)
        layout.setSpacing(5)

        # Visualization mode dropdown
        self.viz_combo = QComboBox()
        self.viz_combo.addItems(VIZ_MODES)
        self.viz_combo.setCurrentIndex(0)  # Default: Structural
        self.viz_combo.currentIndexChanged.connect(self._on_viz_mode_changed)
        layout.addRow("View:", self.viz_combo)

        # Orthographic toggle
        self.ortho_check = QCheckBox("Orthographic")
        self.ortho_check.setToolTip("Switch between perspective and orthographic projection")
        self.ortho_check.toggled.connect(self._on_ortho_toggled)
        layout.addRow(self.ortho_check)

        # FOV slider
        fov_row = QHBoxLayout()
        self.fov_slider = QSlider(Qt.Orientation.Horizontal)
        self.fov_slider.setRange(10, 120)  # 10-120 degrees
        self.fov_slider.setValue(45)  # Default: 45 degrees
        self.fov_slider.valueChanged.connect(self._on_fov_changed)
        fov_row.addWidget(self.fov_slider)

        self.fov_label = QLabel("45")
        self.fov_label.setMinimumWidth(25)
        fov_row.addWidget(self.fov_label)

        self.fov_unit = QLabel("\u00b0")  # degree symbol
        fov_row.addWidget(self.fov_unit)

        layout.addRow("FOV:", fov_row)

        parent_layout.addWidget(group)

    def _create_material_group(self, parent_layout):
        """Create material style controls."""
        group = QGroupBox("Material Style")
        layout = QFormLayout(group)
        layout.setSpacing(5)

        # Style dropdown
        self.style_combo = QComboBox()
        self.style_combo.addItems(MATERIAL_STYLES)
        self.style_combo.setCurrentIndex(1)  # Default: Clean
        self.style_combo.currentIndexChanged.connect(self._on_style_changed)
        layout.addRow("Style:", self.style_combo)

        # Style descriptions
        self.style_desc = QLabel("Matte surfaces with subtle shading")
        self.style_desc.setStyleSheet("color: #888; font-size: 10px;")
        self.style_desc.setWordWrap(True)
        layout.addRow("", self.style_desc)

        parent_layout.addWidget(group)

    def _create_clipping_group(self, parent_layout):
        """Create section clipping controls."""
        group = QGroupBox("Section Clipping")
        layout = QVBoxLayout(group)
        layout.setSpacing(5)

        # Enable checkbox
        self.clip_enabled = QCheckBox("Enable Clipping")
        self.clip_enabled.toggled.connect(self._on_clipping_toggled)
        layout.addWidget(self.clip_enabled)

        # Controls container (enabled only when clipping is on)
        self.clip_controls = QWidget()
        controls_layout = QFormLayout(self.clip_controls)
        controls_layout.setSpacing(5)
        controls_layout.setContentsMargins(0, 5, 0, 0)

        # Axis selector
        self.axis_combo = QComboBox()
        self.axis_combo.addItems(AXIS_NAMES)
        self.axis_combo.setCurrentIndex(1)  # Default: Y axis
        self.axis_combo.currentIndexChanged.connect(self._on_axis_changed)
        controls_layout.addRow("Axis:", self.axis_combo)

        # Position slider
        slider_row = QHBoxLayout()
        self.pos_slider = QSlider(Qt.Orientation.Horizontal)
        self.pos_slider.setRange(0, 500)  # 0-50 feet in 0.1 increments
        self.pos_slider.setValue(40)  # 4 feet default
        self.pos_slider.valueChanged.connect(self._on_slider_moved)
        slider_row.addWidget(self.pos_slider)

        self.pos_spin = QDoubleSpinBox()
        self.pos_spin.setRange(-50, 100)
        self.pos_spin.setDecimals(1)
        self.pos_spin.setSuffix(" ft")
        self.pos_spin.setValue(4.0)
        self.pos_spin.valueChanged.connect(self._on_spin_changed)
        slider_row.addWidget(self.pos_spin)

        controls_layout.addRow("Position:", slider_row)

        # Flip direction
        self.flip_check = QCheckBox("Flip Direction")
        self.flip_check.toggled.connect(self._on_flip_toggled)
        controls_layout.addRow("", self.flip_check)

        layout.addWidget(self.clip_controls)
        self.clip_controls.setEnabled(False)

        parent_layout.addWidget(group)

    def _create_section_box_group(self, parent_layout):
        """Create section box controls for 3D clipping region."""
        group = QGroupBox("Section Box")
        layout = QVBoxLayout(group)
        layout.setSpacing(5)

        # Enable checkbox
        self.section_box_enabled = QCheckBox("Enable Section Box")
        self.section_box_enabled.toggled.connect(self._on_section_box_toggled)
        layout.addWidget(self.section_box_enabled)

        # Controls container (enabled only when section box is on)
        self.section_box_controls = QWidget()
        controls_layout = QFormLayout(self.section_box_controls)
        controls_layout.setSpacing(5)
        controls_layout.setContentsMargins(0, 5, 0, 0)

        # Min X
        self.box_min_x = QDoubleSpinBox()
        self.box_min_x.setRange(-500, 500)
        self.box_min_x.setDecimals(1)
        self.box_min_x.setSuffix(" ft")
        self.box_min_x.setValue(-20.0)
        self.box_min_x.valueChanged.connect(self._on_section_box_changed)
        controls_layout.addRow("Min X:", self.box_min_x)

        # Max X
        self.box_max_x = QDoubleSpinBox()
        self.box_max_x.setRange(-500, 500)
        self.box_max_x.setDecimals(1)
        self.box_max_x.setSuffix(" ft")
        self.box_max_x.setValue(50.0)
        self.box_max_x.valueChanged.connect(self._on_section_box_changed)
        controls_layout.addRow("Max X:", self.box_max_x)

        # Min Y
        self.box_min_y = QDoubleSpinBox()
        self.box_min_y.setRange(-100, 500)
        self.box_min_y.setDecimals(1)
        self.box_min_y.setSuffix(" ft")
        self.box_min_y.setValue(0.0)
        self.box_min_y.valueChanged.connect(self._on_section_box_changed)
        controls_layout.addRow("Min Y:", self.box_min_y)

        # Max Y
        self.box_max_y = QDoubleSpinBox()
        self.box_max_y.setRange(-100, 500)
        self.box_max_y.setDecimals(1)
        self.box_max_y.setSuffix(" ft")
        self.box_max_y.setValue(15.0)
        self.box_max_y.valueChanged.connect(self._on_section_box_changed)
        controls_layout.addRow("Max Y:", self.box_max_y)

        # Min Z
        self.box_min_z = QDoubleSpinBox()
        self.box_min_z.setRange(-500, 500)
        self.box_min_z.setDecimals(1)
        self.box_min_z.setSuffix(" ft")
        self.box_min_z.setValue(-20.0)
        self.box_min_z.valueChanged.connect(self._on_section_box_changed)
        controls_layout.addRow("Min Z:", self.box_min_z)

        # Max Z
        self.box_max_z = QDoubleSpinBox()
        self.box_max_z.setRange(-500, 500)
        self.box_max_z.setDecimals(1)
        self.box_max_z.setSuffix(" ft")
        self.box_max_z.setValue(50.0)
        self.box_max_z.valueChanged.connect(self._on_section_box_changed)
        controls_layout.addRow("Max Z:", self.box_max_z)

        layout.addWidget(self.section_box_controls)
        self.section_box_controls.setEnabled(False)

        # Quick presets for section box
        presets_layout = QHBoxLayout()
        presets_layout.setSpacing(3)

        btn_fit_model = QPushButton("Fit to Model")
        btn_fit_model.setToolTip("Set section box to fit the current model bounds")
        btn_fit_model.clicked.connect(self._fit_section_box_to_model)
        presets_layout.addWidget(btn_fit_model)

        btn_clear_box = QPushButton("Clear")
        btn_clear_box.setToolTip("Clear section box")
        btn_clear_box.clicked.connect(self._clear_section_box)
        presets_layout.addWidget(btn_clear_box)

        layout.addLayout(presets_layout)

        parent_layout.addWidget(group)

    def _create_presets_group(self, parent_layout):
        """Create quick preset buttons."""
        group = QGroupBox("Quick Presets")
        layout = QVBoxLayout(group)
        layout.setSpacing(5)

        # Floor plan presets
        floor_row = QHBoxLayout()
        floor_row.setSpacing(3)

        btn_floor1 = QPushButton("Floor Plan (4')")
        btn_floor1.clicked.connect(lambda: self._apply_floor_plan(4.0))
        floor_row.addWidget(btn_floor1)

        btn_floor2 = QPushButton("Roof Plan (10')")
        btn_floor2.clicked.connect(lambda: self._apply_floor_plan(10.0))
        floor_row.addWidget(btn_floor2)

        layout.addLayout(floor_row)

        # Section presets
        section_row = QHBoxLayout()
        section_row.setSpacing(3)

        btn_section_x = QPushButton("Section A-A")
        btn_section_x.setToolTip("Cut looking East-West (X axis)")
        btn_section_x.clicked.connect(lambda: self._apply_elevation(0, 0))
        section_row.addWidget(btn_section_x)

        btn_section_z = QPushButton("Section B-B")
        btn_section_z.setToolTip("Cut looking North-South (Z axis)")
        btn_section_z.clicked.connect(lambda: self._apply_elevation(2, 0))
        section_row.addWidget(btn_section_z)

        layout.addLayout(section_row)

        # Clear clipping
        btn_clear = QPushButton("Clear Clipping")
        btn_clear.clicked.connect(self._clear_clipping)
        layout.addWidget(btn_clear)

        parent_layout.addWidget(group)

    def _create_lighting_group(self, parent_layout):
        """Create lighting and shadows controls."""
        group = QGroupBox("Lighting")
        layout = QVBoxLayout(group)
        layout.setSpacing(5)

        # Shadows toggle
        self.shadows_check = QCheckBox("Enable Shadows")
        self.shadows_check.setChecked(True)
        self.shadows_check.toggled.connect(self._on_shadows_toggled)
        layout.addWidget(self.shadows_check)

        parent_layout.addWidget(group)

    def _create_postprocess_group(self, parent_layout):
        """Create post-processing controls."""
        group = QGroupBox("Post-Processing")
        layout = QFormLayout(group)
        layout.setSpacing(5)

        # SSAO section
        self.ssao_check = QCheckBox("SSAO")
        self.ssao_check.setChecked(True)
        self.ssao_check.toggled.connect(self._on_ssao_toggled)
        layout.addRow(self.ssao_check)

        # SSAO Intensity slider
        ssao_row = QHBoxLayout()
        self.ssao_slider = QSlider(Qt.Orientation.Horizontal)
        self.ssao_slider.setRange(0, 30)  # 0.0-3.0
        self.ssao_slider.setValue(10)  # 1.0
        self.ssao_slider.valueChanged.connect(self._on_ssao_intensity_changed)
        ssao_row.addWidget(self.ssao_slider)
        self.ssao_label = QLabel("1.0")
        self.ssao_label.setMinimumWidth(30)
        ssao_row.addWidget(self.ssao_label)
        layout.addRow("  Intensity:", ssao_row)

        # Bloom section
        self.bloom_check = QCheckBox("Bloom")
        self.bloom_check.setChecked(True)
        self.bloom_check.toggled.connect(self._on_bloom_toggled)
        layout.addRow(self.bloom_check)

        # Bloom Intensity slider
        bloom_row = QHBoxLayout()
        self.bloom_slider = QSlider(Qt.Orientation.Horizontal)
        self.bloom_slider.setRange(0, 20)  # 0.0-2.0
        self.bloom_slider.setValue(5)  # 0.5
        self.bloom_slider.valueChanged.connect(self._on_bloom_intensity_changed)
        bloom_row.addWidget(self.bloom_slider)
        self.bloom_label = QLabel("0.5")
        self.bloom_label.setMinimumWidth(30)
        bloom_row.addWidget(self.bloom_label)
        layout.addRow("  Intensity:", bloom_row)

        # Exposure slider
        exp_row = QHBoxLayout()
        self.exposure_slider = QSlider(Qt.Orientation.Horizontal)
        self.exposure_slider.setRange(1, 40)  # 0.1-4.0
        self.exposure_slider.setValue(10)  # 1.0
        self.exposure_slider.valueChanged.connect(self._on_exposure_changed)
        exp_row.addWidget(self.exposure_slider)
        self.exposure_label = QLabel("1.0")
        self.exposure_label.setMinimumWidth(30)
        exp_row.addWidget(self.exposure_label)
        layout.addRow("Exposure:", exp_row)

        # Tonemap mode
        self.tonemap_combo = QComboBox()
        self.tonemap_combo.addItems(TONEMAP_MODES)
        self.tonemap_combo.setCurrentIndex(1)  # Default: ACES
        self.tonemap_combo.currentIndexChanged.connect(self._on_tonemap_changed)
        layout.addRow("Tonemap:", self.tonemap_combo)

        parent_layout.addWidget(group)

    def set_viewport(self, viewport):
        """
        Connect to a VulkanViewportWidget.

        Args:
            viewport: VulkanViewportWidget instance
        """
        self._viewport = viewport

        # Sync current state from viewport if available
        if viewport and viewport.is_initialized:
            self._sync_from_viewport()

    def set_lod_level(self, level: int):
        """Set the current LOD level (1-5)."""
        self._lod_level = level

    def set_gravity_weights(self, design: float, client: float, build: float):
        """Set gravity weights from external source."""
        self._gravity = (design, client, build)

    def center_gravity(self):
        """Reset gravity to centered (equal weights)."""
        self._gravity = (0.33, 0.33, 0.34)
        self.gravity_changed.emit(0.33, 0.33, 0.34)

    def _sync_from_viewport(self):
        """Sync UI state from viewport."""
        if not self._viewport:
            return

        self._updating = True

        # Camera settings
        try:
            fov = self._viewport.get_camera_fov()
            self.fov_slider.setValue(int(fov))
            self.fov_label.setText(str(int(fov)))

            ortho = self._viewport.get_orthographic()
            self.ortho_check.setChecked(ortho)
        except AttributeError:
            pass  # API not available in this DLL version

        # Material style
        style = self._viewport.get_material_style()
        self.style_combo.setCurrentIndex(style)

        # Clipping state
        enabled = self._viewport.get_clipping_enabled()
        self.clip_enabled.setChecked(enabled)

        axis = self._viewport.get_clip_axis()
        self.axis_combo.setCurrentIndex(axis)

        height = self._viewport.get_clip_height()
        self.pos_spin.setValue(height)
        self.pos_slider.setValue(int(height * 10))

        flipped = self._viewport.get_clip_flipped()
        self.flip_check.setChecked(flipped)

        # Section box state
        try:
            has_box = self._viewport.has_section_box()
            self.section_box_enabled.setChecked(has_box)
            self.section_box_controls.setEnabled(has_box)

            if has_box:
                bounds = self._viewport.get_section_box()
                if bounds:
                    self.box_min_x.setValue(bounds[0])
                    self.box_min_y.setValue(bounds[1])
                    self.box_min_z.setValue(bounds[2])
                    self.box_max_x.setValue(bounds[3])
                    self.box_max_y.setValue(bounds[4])
                    self.box_max_z.setValue(bounds[5])
        except AttributeError:
            pass  # Section box API not available

        self._updating = False

    def _on_style_changed(self, index: int):
        """Handle material style change."""
        # Update description
        descriptions = [
            "Full PBR with metallic and roughness",
            "Matte surfaces with subtle shading",
            "Flat colors for technical views",
            "Classic blue and white blueprint look"
        ]
        if 0 <= index < len(descriptions):
            self.style_desc.setText(descriptions[index])

        if self._updating:
            return

        if self._viewport:
            self._viewport.set_material_style(index)

        self.material_style_changed.emit(index)

    def _on_clipping_toggled(self, checked: bool):
        """Handle clipping enable/disable."""
        self.clip_controls.setEnabled(checked)

        if self._updating:
            return

        if self._viewport:
            self._viewport.set_clipping_enabled(checked)

        self.clipping_changed.emit()

    def _on_axis_changed(self, index: int):
        """Handle axis selection change."""
        if self._updating:
            return

        if self._viewport:
            self._viewport.set_clip_axis(index)

        self.clipping_changed.emit()

    def _on_slider_moved(self, value: int):
        """Handle position slider change."""
        height = value / 10.0

        self._updating = True
        self.pos_spin.setValue(height)
        self._updating = False

        if self._viewport:
            self._viewport.set_clip_height(height)

        self.clipping_changed.emit()

    def _on_spin_changed(self, value: float):
        """Handle position spinbox change."""
        if self._updating:
            return

        self._updating = True
        self.pos_slider.setValue(int(value * 10))
        self._updating = False

        if self._viewport:
            self._viewport.set_clip_height(value)

        self.clipping_changed.emit()

    def _on_flip_toggled(self, checked: bool):
        """Handle flip direction toggle."""
        if self._updating:
            return

        if self._viewport:
            self._viewport.set_clip_flipped(checked)

        self.clipping_changed.emit()

    def _apply_floor_plan(self, height: float):
        """Apply floor plan preset."""
        self._updating = True

        self.clip_enabled.setChecked(True)
        self.axis_combo.setCurrentIndex(1)  # Y axis
        self.pos_spin.setValue(height)
        self.pos_slider.setValue(int(height * 10))
        self.flip_check.setChecked(False)

        self._updating = False

        if self._viewport:
            self._viewport.set_section_floor_plan(height)

        self.clip_controls.setEnabled(True)
        self.clipping_changed.emit()

    def _apply_elevation(self, axis: int, position: float):
        """Apply elevation/section preset."""
        self._updating = True

        self.clip_enabled.setChecked(True)
        self.axis_combo.setCurrentIndex(axis)
        self.pos_spin.setValue(position)
        self.pos_slider.setValue(int(position * 10))
        self.flip_check.setChecked(False)

        self._updating = False

        if self._viewport:
            self._viewport.set_section_elevation(axis, position)

        self.clip_controls.setEnabled(True)
        self.clipping_changed.emit()

    def _clear_clipping(self):
        """Clear/disable clipping."""
        self._updating = True
        self.clip_enabled.setChecked(False)
        self._updating = False

        if self._viewport:
            self._viewport.set_clipping_enabled(False)

        self.clip_controls.setEnabled(False)
        self.clipping_changed.emit()

    # =========================================================================
    # Section Box handlers
    # =========================================================================

    def _on_section_box_toggled(self, checked: bool):
        """Handle section box enable/disable."""
        self.section_box_controls.setEnabled(checked)

        if self._updating:
            return

        if checked:
            # Apply current bounds
            self._apply_section_box()
        else:
            # Clear section box
            if self._viewport:
                self._viewport.clear_section_box()

        self.clipping_changed.emit()

    def _on_section_box_changed(self, value: float):
        """Handle section box dimension change."""
        if self._updating:
            return

        if self.section_box_enabled.isChecked():
            self._apply_section_box()
            self.clipping_changed.emit()

    def _apply_section_box(self):
        """Apply section box with current UI values."""
        if self._viewport:
            self._viewport.set_section_box(
                self.box_min_x.value(), self.box_min_y.value(), self.box_min_z.value(),
                self.box_max_x.value(), self.box_max_y.value(), self.box_max_z.value()
            )

    def _fit_section_box_to_model(self):
        """Fit section box to the current model bounds with some padding."""
        # Default bounds for a typical building
        # TODO: Get actual model bounds from document
        self._updating = True

        self.box_min_x.setValue(-5.0)
        self.box_max_x.setValue(60.0)
        self.box_min_y.setValue(0.0)
        self.box_max_y.setValue(20.0)
        self.box_min_z.setValue(-5.0)
        self.box_max_z.setValue(60.0)

        self._updating = False

        self.section_box_enabled.setChecked(True)
        self._apply_section_box()
        self.clipping_changed.emit()

    def _clear_section_box(self):
        """Clear section box."""
        self._updating = True
        self.section_box_enabled.setChecked(False)
        self._updating = False

        if self._viewport:
            self._viewport.clear_section_box()

        self.section_box_controls.setEnabled(False)
        self.clipping_changed.emit()

    def update_from_section(self, enabled: bool, axis: int, height: float, flipped: bool):
        """Update panel UI from viewport section changes (interactive drag)."""
        self._updating = True

        self.clip_enabled.setChecked(enabled)
        self.clip_controls.setEnabled(enabled)
        self.axis_combo.setCurrentIndex(axis)
        self.pos_spin.setValue(height)
        self.pos_slider.setValue(int(height * 10))
        self.flip_check.setChecked(flipped)

        self._updating = False

    def get_material_style(self) -> int:
        """Get current material style index."""
        return self.style_combo.currentIndex()

    def set_material_style(self, style: int):
        """Set material style programmatically."""
        if 0 <= style < len(MATERIAL_STYLES):
            self.style_combo.setCurrentIndex(style)

    # =========================================================================
    # Gravity handlers
    # =========================================================================

    def _on_gravity_changed(self, design: float, client: float, build: float):
        """Handle gravity triangle changes - map to rendering settings."""
        if self._updating:
            return

        # Emit the raw gravity signal
        self.gravity_changed.emit(design, client, build)

        # Map gravity to rendering settings
        self._apply_gravity_blend(design, client, build)

    def _apply_gravity_blend(self, design: float, client: float, build: float):
        """Apply gravity blend to viewport rendering settings."""
        if not self._viewport:
            return
        try:
            self._apply_gravity_blend_impl(design, client, build)
        except Exception as e:
            print(f"[ViewportPanel] Error in gravity blend: {e}")
            import traceback
            traceback.print_exc()

    def _apply_gravity_blend_impl(self, design: float, client: float, build: float):
        """Implementation of gravity blend (wrapped for error handling)."""

        self._updating = True

        # Determine dominant gravity
        max_weight = max(design, client, build)

        # Material style mapping:
        # Design -> Schematic (flat, analytical)
        # Client -> Realistic (full PBR)
        # Build -> Blueprint (technical)
        if design == max_weight and design > 0.5:
            self.style_combo.setCurrentIndex(2)  # Schematic
            self._viewport.set_material_style(2)
        elif client == max_weight and client > 0.5:
            self.style_combo.setCurrentIndex(0)  # Realistic
            self._viewport.set_material_style(0)
        elif build == max_weight and build > 0.5:
            self.style_combo.setCurrentIndex(3)  # Blueprint
            self._viewport.set_material_style(3)
        else:
            # Blended - use Clean as middle ground
            self.style_combo.setCurrentIndex(1)  # Clean
            self._viewport.set_material_style(1)

        # Visualization mode mapping:
        # Design -> Structural (analytical)
        # Client -> Material (realistic look)
        # Build -> Structural or Wireframe
        if design == max_weight and design > 0.6:
            self.viz_combo.setCurrentIndex(0)  # Structural
            self._viewport.set_visualization_mode(0)
        elif client == max_weight and client > 0.6:
            self.viz_combo.setCurrentIndex(4)  # Material
            self._viewport.set_visualization_mode(4)
        elif build == max_weight and build > 0.6:
            self.viz_combo.setCurrentIndex(5)  # Wireframe
            self._viewport.set_visualization_mode(5)

        # Post-processing adjustments:
        # Design -> Less bloom, more SSAO (analytical)
        # Client -> Full bloom, exposure (pretty)
        # Build -> Minimal effects (clear)
        if hasattr(self._viewport, 'set_bloom_enabled'):
            # Client gets bloom, others don't
            bloom_enabled = client > 0.4
            self.bloom_check.setChecked(bloom_enabled)
            self._viewport.set_bloom_enabled(bloom_enabled)

            if bloom_enabled:
                bloom_intensity = client * 0.8
                self.bloom_slider.setValue(int(bloom_intensity * 10))
                self._viewport.set_bloom_intensity(bloom_intensity)

        if hasattr(self._viewport, 'set_ssao_enabled'):
            # Design and Client get SSAO, Build minimal
            ssao_enabled = build < 0.6
            self.ssao_check.setChecked(ssao_enabled)
            self._viewport.set_ssao_enabled(ssao_enabled)

            if ssao_enabled:
                ssao_intensity = 0.5 + design * 0.5 + client * 0.3
                self.ssao_slider.setValue(int(ssao_intensity * 10))
                self._viewport.set_ssao_intensity(ssao_intensity)

        # Exposure adjustments
        if hasattr(self._viewport, 'set_exposure'):
            # Client gets warmer exposure, Build gets neutral
            exposure = 1.0 + client * 0.3 - build * 0.2
            exposure = max(0.5, min(2.0, exposure))
            self.exposure_slider.setValue(int(exposure * 10))
            self._viewport.set_exposure(exposure)

        self._updating = False

    def set_gravity_weights(self, design: float, client: float, build: float):
        """Update gravity weights from external controls (overlay)."""
        if hasattr(self, 'gravity_triangle'):
            self.gravity_triangle.set_weights(design, client, build)
        self._on_gravity_changed(design, client, build)

    # =========================================================================
    # LOD handlers
    # =========================================================================

    def _on_lod_changed(self, level: int, transition: float):
        """Handle LOD level change - map to rendering settings."""
        if self._updating:
            return

        # Emit the signal
        self.lod_changed.emit(level, transition)

        # Apply LOD-based rendering adjustments
        self._apply_lod_settings(level, transition)

    def _apply_lod_settings(self, level: int, transition: float):
        """Apply rendering settings based on LOD level."""
        if not self._viewport:
            return

        self._updating = True

        # LOD affects visualization mode and detail level
        # Higher LOD (closer) = more detail
        # Lower LOD (farther) = more abstract

        lod = LODLevel(level)

        # Adjust SSAO based on LOD - more occlusion detail at closer LODs
        if hasattr(self._viewport, 'set_ssao_intensity'):
            if lod >= LODLevel.FIXTURES:
                # Close up - full SSAO
                self._viewport.set_ssao_intensity(1.2)
            elif lod == LODLevel.WALLS:
                # Mid range - moderate SSAO
                self._viewport.set_ssao_intensity(0.8)
            else:
                # Far away - minimal SSAO
                self._viewport.set_ssao_intensity(0.4)

        self._updating = False

    def update_from_camera_distance(self, distance: float):
        """Update LOD indicator based on camera distance (auto mode)."""
        if hasattr(self, 'lod_indicator'):
            self.lod_indicator.set_camera_distance(distance)

    def set_lod_level(self, level: int):
        """Set LOD level directly (manual mode via shift+scroll)."""
        if hasattr(self, 'lod_indicator'):
            self.lod_indicator.set_lod_level(level)

    def center_gravity(self):
        """Center gravity (called when user hovers a dimmed panel)."""
        if hasattr(self, 'gravity_triangle'):
            self.gravity_triangle.set_center()

    # =========================================================================
    # Camera handlers
    # =========================================================================

    def _on_viz_mode_changed(self, index: int):
        """Handle visualization mode change."""
        if self._updating:
            return
        if self._viewport:
            self._viewport.set_visualization_mode(index)

    def _on_ortho_toggled(self, checked: bool):
        """Handle orthographic toggle."""
        if self._updating:
            return
        if self._viewport:
            self._viewport.set_orthographic(checked)

    def _on_fov_changed(self, value: int):
        """Handle FOV slider change."""
        self.fov_label.setText(str(value))
        if self._updating:
            return
        if self._viewport:
            self._viewport.set_camera_fov(float(value))

    def get_camera_fov(self) -> float:
        """Get current camera FOV."""
        return float(self.fov_slider.value())

    def set_camera_fov(self, fov: float):
        """Set camera FOV programmatically."""
        if 10 <= fov <= 120:
            self.fov_slider.setValue(int(fov))

    def get_orthographic(self) -> bool:
        """Get orthographic mode state."""
        return self.ortho_check.isChecked()

    def set_orthographic(self, enabled: bool):
        """Set orthographic mode programmatically."""
        self.ortho_check.setChecked(enabled)

    def get_viz_mode(self) -> int:
        """Get current visualization mode."""
        return self.viz_combo.currentIndex()

    def set_viz_mode(self, mode: int):
        """Set visualization mode programmatically."""
        if 0 <= mode < len(VIZ_MODES):
            self.viz_combo.setCurrentIndex(mode)

    # =========================================================================
    # Lighting handlers
    # =========================================================================

    def _on_shadows_toggled(self, checked: bool):
        """Handle shadows toggle."""
        if self._updating:
            return
        if self._viewport:
            self._viewport.set_shadows_enabled(checked)

    # =========================================================================
    # Post-processing handlers
    # =========================================================================

    def _on_ssao_toggled(self, checked: bool):
        """Handle SSAO toggle."""
        if self._updating:
            return
        if self._viewport:
            self._viewport.set_ssao_enabled(checked)

    def _on_ssao_intensity_changed(self, value: int):
        """Handle SSAO intensity slider."""
        intensity = value / 10.0
        self.ssao_label.setText(f"{intensity:.1f}")
        if self._updating:
            return
        if self._viewport:
            self._viewport.set_ssao_intensity(intensity)

    def _on_bloom_toggled(self, checked: bool):
        """Handle bloom toggle."""
        if self._updating:
            return
        if self._viewport:
            self._viewport.set_bloom_enabled(checked)

    def _on_bloom_intensity_changed(self, value: int):
        """Handle bloom intensity slider."""
        intensity = value / 10.0
        self.bloom_label.setText(f"{intensity:.1f}")
        if self._updating:
            return
        if self._viewport:
            self._viewport.set_bloom_intensity(intensity)

    def _on_exposure_changed(self, value: int):
        """Handle exposure slider."""
        exposure = value / 10.0
        self.exposure_label.setText(f"{exposure:.1f}")
        if self._updating:
            return
        if self._viewport:
            self._viewport.set_exposure(exposure)

    def _on_tonemap_changed(self, index: int):
        """Handle tonemap mode change."""
        if self._updating:
            return
        if self._viewport:
            self._viewport.set_tonemap_mode(index)
