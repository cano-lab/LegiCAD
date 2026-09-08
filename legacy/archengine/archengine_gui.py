#!/usr/bin/env python3
"""
archengine_gui.py - GUI frontend for Archengine permit drawing generator

Simple PyQt6 interface for:
- Site location/constraints input
- Building parameters
- Generate permit drawing set
- Launch Vulkan viewer
"""

import sys
import json
import subprocess
from pathlib import Path
from dataclasses import dataclass, asdict

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QSpinBox, QDoubleSpinBox,
    QComboBox, QGroupBox, QFormLayout, QTabWidget, QFileDialog,
    QMessageBox, QProgressBar, QTextEdit, QCheckBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal


@dataclass
class SiteConstraints:
    """Site constraints and location."""
    address: str = ""
    lot_width_ft: float = 60.0
    lot_depth_ft: float = 120.0
    front_setback_ft: float = 25.0
    side_setback_ft: float = 6.0
    rear_setback_ft: float = 25.0
    max_height_ft: float = 35.0
    max_floors: int = 2
    driveway_width_ft: float = 12.0
    
    # Constraints
    has_septic: bool = False
    has_well: bool = False
    flood_zone: str = "None"
    slope_pct: float = 0.0


@dataclass
class BuildingSpec:
    """Building specification."""
    name: str = "My House"
    building_type: str = "residential"
    target_area_sqm: float = 150.0
    num_bedrooms: int = 3
    num_bathrooms: float = 2.0
    num_floors: int = 1
    style: str = "modern"
    
    # Room preferences
    has_garage: bool = False
    has_basement: bool = False
    open_plan: bool = True


class GenerationWorker(QThread):
    """Background worker for drawing generation."""
    
    progress = pyqtSignal(str, int)  # message, percent
    finished = pyqtSignal(bool, str)  # success, message
    
    def __init__(self, site: SiteConstraints, building: BuildingSpec, output_dir: Path):
        super().__init__()
        self.site = site
        self.building = building
        self.output_dir = output_dir
    
    def run(self):
        try:
            self.progress.emit("Initializing...", 10)
            
            # Import and run generation
            sys.path.insert(0, str(Path(__file__).parent))
            from permit_drawing_set import create_permit_drawing_set
            
            self.progress.emit("Generating building layout...", 30)
            
            # Create dummy building JSON (in real app, this would come from solver)
            building_json = self.output_dir / 'building_spec.json'
            
            # Save inputs
            inputs = {
                'site': asdict(self.site),
                'building': asdict(self.building)
            }
            with open(self.output_dir / 'inputs.json', 'w') as f:
                json.dump(inputs, f, indent=2)
            
            self.progress.emit("Generating drawings...", 60)
            
            # Generate permit set
            create_permit_drawing_set(
                building_json,
                self.output_dir / 'drawings',
                lot_width_ft=self.site.lot_width_ft,
                lot_depth_ft=self.site.lot_depth_ft
            )
            
            self.progress.emit("Complete!", 100)
            self.finished.emit(True, f"Drawings saved to {self.output_dir / 'drawings'}")
            
        except Exception as e:
            self.finished.emit(False, str(e))


class ArchengineGUI(QMainWindow):
    """Main application window."""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Archengine - Permit Drawing Generator")
        self.setMinimumSize(800, 600)
        
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)
        
        self.create_ui()
    
    def create_ui(self):
        """Create the user interface."""
        
        # Title
        title = QLabel("Archengine - Generative CAD for Residential Construction")
        title.setStyleSheet("font-size: 18px; font-weight: bold; margin: 10px;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.layout.addWidget(title)
        
        # Tabs
        tabs = QTabWidget()
        self.layout.addWidget(tabs)
        
        # Site tab
        site_tab = self.create_site_tab()
        tabs.addTab(site_tab, "Site & Constraints")
        
        # Building tab
        building_tab = self.create_building_tab()
        tabs.addTab(building_tab, "Building Spec")
        
        # Output tab
        output_tab = self.create_output_tab()
        tabs.addTab(output_tab, "Generate & View")
        
        # Status bar
        self.status_bar = self.statusBar()
        self.status_bar.showMessage("Ready")
    
    def create_site_tab(self) -> QWidget:
        """Create site input tab."""
        widget = QWidget()
        layout = QFormLayout(widget)
        
        # Location
        self.address_input = QLineEdit()
        self.address_input.setPlaceholderText("123 Main St, City, Province")
        layout.addRow("Site Address:", self.address_input)
        
        # Lot dimensions
        self.lot_width = QDoubleSpinBox()
        self.lot_width.setRange(20, 300)
        self.lot_width.setValue(60)
        self.lot_width.setSuffix(" ft")
        layout.addRow("Lot Width:", self.lot_width)
        
        self.lot_depth = QDoubleSpinBox()
        self.lot_depth.setRange(50, 500)
        self.lot_depth.setValue(120)
        self.lot_depth.setSuffix(" ft")
        layout.addRow("Lot Depth:", self.lot_depth)
        
        # Setbacks
        group = QGroupBox("Setbacks")
        group_layout = QFormLayout(group)
        
        self.front_setback = QDoubleSpinBox()
        self.front_setback.setRange(0, 100)
        self.front_setback.setValue(25)
        self.front_setback.setSuffix(" ft")
        group_layout.addRow("Front:", self.front_setback)
        
        self.side_setback = QDoubleSpinBox()
        self.side_setback.setRange(0, 50)
        self.side_setback.setValue(6)
        self.side_setback.setSuffix(" ft")
        group_layout.addRow("Side:", self.side_setback)
        
        self.rear_setback = QDoubleSpinBox()
        self.rear_setback.setRange(0, 100)
        self.rear_setback.setValue(25)
        self.rear_setback.setSuffix(" ft")
        group_layout.addRow("Rear:", self.rear_setback)
        
        layout.addRow(group)
        
        # Constraints
        self.has_septic = QCheckBox("Site has septic system")
        layout.addRow(self.has_septic)
        
        self.has_well = QCheckBox("Site has well water")
        layout.addRow(self.has_well)
        
        return widget
    
    def create_building_tab(self) -> QWidget:
        """Create building specification tab."""
        widget = QWidget()
        layout = QFormLayout(widget)
        
        # Basic info
        self.building_name = QLineEdit()
        self.building_name.setText("My House")
        layout.addRow("Project Name:", self.building_name)
        
        self.building_type = QComboBox()
        self.building_type.addItems(["Single Family", "Duplex", "Accessory Dwelling"])
        layout.addRow("Building Type:", self.building_type)
        
        # Size
        self.target_area = QDoubleSpinBox()
        self.target_area.setRange(50, 500)
        self.target_area.setValue(150)
        self.target_area.setSuffix(" m²")
        layout.addRow("Target Floor Area:", self.target_area)
        
        # Rooms
        self.num_bedrooms = QSpinBox()
        self.num_bedrooms.setRange(1, 10)
        self.num_bedrooms.setValue(3)
        layout.addRow("Bedrooms:", self.num_bedrooms)
        
        self.num_bathrooms = QDoubleSpinBox()
        self.num_bathrooms.setRange(1, 10)
        self.num_bathrooms.setValue(2)
        layout.addRow("Bathrooms:", self.num_bathrooms)
        
        # Features
        self.has_garage = QCheckBox("Include Garage")
        layout.addRow(self.has_garage)
        
        self.open_plan = QCheckBox("Open Plan Living")
        self.open_plan.setChecked(True)
        layout.addRow(self.open_plan)
        
        return widget
    
    def create_output_tab(self) -> QWidget:
        """Create output and generation tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Output directory
        dir_layout = QHBoxLayout()
        self.output_dir = QLineEdit()
        self.output_dir.setText(str(Path.home() / "Archengine_Output"))
        dir_layout.addWidget(QLabel("Output Directory:"))
        dir_layout.addWidget(self.output_dir)
        
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self.browse_output)
        dir_layout.addWidget(browse_btn)
        
        layout.addLayout(dir_layout)
        
        # Generate button
        self.generate_btn = QPushButton("Generate Permit Drawings")
        self.generate_btn.setStyleSheet("font-size: 16px; padding: 15px; background-color: #4CAF50; color: white;")
        self.generate_btn.clicked.connect(self.generate_drawings)
        layout.addWidget(self.generate_btn)
        
        # Progress
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)
        
        self.status_text = QTextEdit()
        self.status_text.setReadOnly(True)
        self.status_text.setMaximumHeight(100)
        layout.addWidget(self.status_text)
        
        # Launch viewer
        viewer_layout = QHBoxLayout()
        
        self.launch_vulkan_btn = QPushButton("Launch Vulkan Viewer")
        self.launch_vulkan_btn.clicked.connect(self.launch_vulkan)
        viewer_layout.addWidget(self.launch_vulkan_btn)
        
        self.section_box_btn = QPushButton("Section Box Tool")
        self.section_box_btn.clicked.connect(self.launch_section_box)
        viewer_layout.addWidget(self.section_box_btn)
        
        layout.addLayout(viewer_layout)
        
        layout.addStretch()
        return widget
    
    def browse_output(self):
        """Browse for output directory."""
        dir_path = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if dir_path:
            self.output_dir.setText(dir_path)
    
    def generate_drawings(self):
        """Generate the permit drawing set."""
        # Collect inputs
        site = SiteConstraints(
            address=self.address_input.text(),
            lot_width_ft=self.lot_width.value(),
            lot_depth_ft=self.lot_depth.value(),
            front_setback_ft=self.front_setback.value(),
            side_setback_ft=self.side_setback.value(),
            rear_setback_ft=self.rear_setback.value(),
            has_septic=self.has_septic.isChecked(),
            has_well=self.has_well.isChecked()
        )
        
        building = BuildingSpec(
            name=self.building_name.text(),
            target_area_sqm=self.target_area.value(),
            num_bedrooms=self.num_bedrooms.value(),
            num_bathrooms=self.num_bathrooms.value(),
            has_garage=self.has_garage.isChecked(),
            open_plan=self.open_plan.isChecked()
        )
        
        output_dir = Path(self.output_dir.text())
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Start generation
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.generate_btn.setEnabled(False)
        
        self.worker = GenerationWorker(site, building, output_dir)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished.connect(self.on_finished)
        self.worker.start()
    
    def on_progress(self, message: str, percent: int):
        """Update progress."""
        self.progress.setValue(percent)
        self.status_text.append(message)
        self.status_bar.showMessage(message)
    
    def on_finished(self, success: bool, message: str):
        """Generation complete."""
        self.progress.setVisible(False)
        self.generate_btn.setEnabled(True)
        
        if success:
            QMessageBox.information(self, "Success", message)
        else:
            QMessageBox.critical(self, "Error", message)
    
    def launch_vulkan(self):
        """Launch Vulkan viewer."""
        # This would launch the Vulkan engine with the generated model
        QMessageBox.information(self, "Vulkan Viewer", 
            "Launching Vulkan viewer with generated geometry...\n\n"
            "Controls:\n"
            "- WASD: Move\n"
            "- Mouse: Look\n"
            "- Space: Section box tool\n"
            "- Esc: Exit")
        
        # In real implementation:
        # subprocess.Popen(["/path/to/vulkan_viewer", model_path])
    
    def launch_section_box(self):
        """Launch section box tool."""
        QMessageBox.information(self, "Section Box Tool",
            "Section Box Tool:\n\n"
            "1. Drag to create section box\n"
            "2. Move planes to adjust cut\n"
            "3. Export section to SVG\n"
            "4. Update elevations in real-time")


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    # Dark palette option could be added here
    
    window = ArchengineGUI()
    window.show()
    
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
