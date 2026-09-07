"""
Site Definition Dialog
=======================
First step in building design - define the site before generating the building.
Import topography, set boundaries, identify road, views, and constraints.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.terrain import generate_terrain_from_site, TerrainMesh

# LiDAR extraction library
try:
    from tools.lidar import LidarExtractor, PropertyBounds, ElevationData
    HAS_LIDAR_LIB = True
except ImportError:
    HAS_LIDAR_LIB = False
    LidarExtractor = None
    print("[SiteDialog] LiDAR library not available, using fallback")

# Numpy for LiDAR processing
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    np = None

# Embedded map widget - lazy import to avoid crashes at startup
HAS_EMBEDDED_MAP = True  # Will check on actual use

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QSpinBox, QDoubleSpinBox, QComboBox, QPushButton, QGroupBox,
    QFormLayout, QTabWidget, QWidget, QFileDialog, QMessageBox,
    QGridLayout, QCheckBox, QTextEdit, QSlider, QProgressBar, QApplication,
    QDialogButtonBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QSettings, QTimer
from PyQt6.QtGui import QDoubleValidator
from pathlib import Path
import json
import os
import requests


class TerrainGeneratorWorker(QThread):
    """Worker thread for terrain mesh generation to prevent UI freezing."""

    # Signals
    progress = pyqtSignal(int, str)  # (percent, status_message)
    finished = pyqtSignal(object)    # terrain_mesh or None
    error = pyqtSignal(str)          # error message

    def __init__(self, site_data: dict, parent=None):
        super().__init__(parent)
        self._site_data = site_data
        self._cancelled = False

    def cancel(self):
        """Cancel the generation."""
        self._cancelled = True

    def run(self):
        """Generate terrain in background thread."""
        try:
            from core.terrain import generate_terrain_from_site

            self.progress.emit(10, "Preparing elevation data...")

            if self._cancelled:
                self.finished.emit(None)
                return

            self.progress.emit(30, "Generating mesh vertices...")

            # Run the terrain generation
            mesh = generate_terrain_from_site(self._site_data)

            if self._cancelled:
                self.finished.emit(None)
                return

            self.progress.emit(90, "Finalizing mesh...")

            if mesh:
                self.progress.emit(100, "Complete")
                self.finished.emit(mesh)
            else:
                self.error.emit("Terrain generation returned no mesh")
                self.finished.emit(None)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.error.emit(str(e))
            self.finished.emit(None)


class LidarImportSettingsDialog(QDialog):
    """Dialog for configuring LiDAR import quality settings."""

    # Quality presets: (max_points, grid_resolution, description)
    QUALITY_PRESETS = {
        "Draft": (50000, 100, "Fast preview (~20k triangles)"),
        "Low": (100000, 150, "Quick import (~45k triangles)"),
        "Medium": (200000, 250, "Balanced quality (~125k triangles)"),
        "High": (500000, 350, "High detail (~245k triangles)"),
        "Ultra": (1000000, 500, "Maximum detail (~500k triangles)"),
        "Custom": (None, None, "Custom settings"),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("LiDAR Import Settings")
        self.setMinimumWidth(400)

        self._setup_ui()
        self._load_settings()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Info
        info = QLabel(
            "Configure terrain quality and performance.\n"
            "Higher quality = more detail but slower generation."
        )
        info.setStyleSheet("color: #888;")
        info.setWordWrap(True)
        layout.addWidget(info)

        # Quality preset
        preset_group = QGroupBox("Quality Preset")
        preset_layout = QVBoxLayout(preset_group)

        self._preset_combo = QComboBox()
        for name, (pts, res, desc) in self.QUALITY_PRESETS.items():
            self._preset_combo.addItem(f"{name} - {desc}", name)
        self._preset_combo.setCurrentIndex(2)  # Default to Medium
        self._preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        preset_layout.addWidget(self._preset_combo)

        layout.addWidget(preset_group)

        # Advanced settings
        advanced_group = QGroupBox("Advanced Settings")
        advanced_layout = QFormLayout(advanced_group)

        # Max elevation points
        self._max_points_spin = QSpinBox()
        self._max_points_spin.setRange(10000, 2000000)
        self._max_points_spin.setSingleStep(50000)
        self._max_points_spin.setValue(200000)
        self._max_points_spin.valueChanged.connect(self._on_custom_changed)
        points_layout = QHBoxLayout()
        points_layout.addWidget(self._max_points_spin)
        points_label = QLabel("(surface detail)")
        points_label.setStyleSheet("color: #888; font-size: 10px;")
        points_layout.addWidget(points_label)
        advanced_layout.addRow("Max Elevation Points:", points_layout)

        # Mesh resolution (grid_res)
        self._grid_res_spin = QSpinBox()
        self._grid_res_spin.setRange(50, 1000)
        self._grid_res_spin.setSingleStep(50)
        self._grid_res_spin.setValue(250)
        self._grid_res_spin.valueChanged.connect(self._on_custom_changed)
        res_layout = QHBoxLayout()
        res_layout.addWidget(self._grid_res_spin)
        res_label = QLabel("(mesh smoothness)")
        res_label.setStyleSheet("color: #888; font-size: 10px;")
        res_layout.addWidget(res_label)
        advanced_layout.addRow("Mesh Resolution:", res_layout)

        # Expected output
        self._estimate_label = QLabel()
        self._estimate_label.setStyleSheet("color: #0af; font-weight: bold;")
        advanced_layout.addRow("Estimated:", self._estimate_label)

        layout.addWidget(advanced_group)

        # Remember settings checkbox
        self._remember_check = QCheckBox("Remember these settings")
        self._remember_check.setChecked(True)
        layout.addWidget(self._remember_check)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._update_estimate()

    def _on_preset_changed(self, index):
        """Handle preset selection."""
        preset_name = self._preset_combo.currentData()
        pts, res, _ = self.QUALITY_PRESETS[preset_name]

        if pts is not None and res is not None:
            self._max_points_spin.blockSignals(True)
            self._grid_res_spin.blockSignals(True)
            self._max_points_spin.setValue(pts)
            self._grid_res_spin.setValue(res)
            self._max_points_spin.blockSignals(False)
            self._grid_res_spin.blockSignals(False)

        self._update_estimate()

    def _on_custom_changed(self):
        """Handle custom value changes - switch to Custom preset."""
        # Check if values match any preset
        pts = self._max_points_spin.value()
        res = self._grid_res_spin.value()

        for i, (name, (p, r, _)) in enumerate(self.QUALITY_PRESETS.items()):
            if p == pts and r == res:
                self._preset_combo.blockSignals(True)
                self._preset_combo.setCurrentIndex(i)
                self._preset_combo.blockSignals(False)
                break
        else:
            # Switch to Custom
            custom_idx = list(self.QUALITY_PRESETS.keys()).index("Custom")
            self._preset_combo.blockSignals(True)
            self._preset_combo.setCurrentIndex(custom_idx)
            self._preset_combo.blockSignals(False)

        self._update_estimate()

    def _update_estimate(self):
        """Update the estimated output label."""
        grid_res = self._grid_res_spin.value()
        triangles = 2 * grid_res * grid_res
        vertices = (grid_res + 1) * (grid_res + 1)

        self._estimate_label.setText(
            f"~{triangles:,} triangles, ~{vertices:,} vertices"
        )

    def _load_settings(self):
        """Load saved settings."""
        settings = QSettings("ArchEngine", "CAD")
        max_pts = settings.value("lidar/max_points", 200000, type=int)
        grid_res = settings.value("lidar/grid_resolution", 250, type=int)

        self._max_points_spin.setValue(max_pts)
        self._grid_res_spin.setValue(grid_res)
        self._on_custom_changed()  # Update preset if matches

    def _save_settings(self):
        """Save current settings."""
        if self._remember_check.isChecked():
            settings = QSettings("ArchEngine", "CAD")
            settings.setValue("lidar/max_points", self._max_points_spin.value())
            settings.setValue("lidar/grid_resolution", self._grid_res_spin.value())

    def accept(self):
        """Save settings and close."""
        self._save_settings()
        super().accept()

    def get_settings(self) -> dict:
        """Get the configured settings."""
        return {
            "max_points": self._max_points_spin.value(),
            "grid_resolution": self._grid_res_spin.value(),
        }


# Sample sites for testing
SAMPLE_SITES = {
    "Suburban Family Lot": {
        "property_width_ft": 100,
        "property_depth_ft": 120,
        "road_location": "Front (South)",
        "road_width_ft": 30,
        "driveway_required": True,
        "setback_front_ft": 20,
        "setback_rear_ft": 25,
        "setback_side_ft": 10,
        "max_coverage_percent": 40,
        "max_height_ft": 35,
        "slope": "Flat (0-5%)",
        "elevation_change_ft": 2,
        "solar_orientation": "South-facing (optimal)",
        "solar_access": True,
        "views": {"north": False, "east": False, "south": True, "west": False},
        "feature_notes": "Flat suburban lot with mature oak tree in rear. Neighbors on both sides.",
        "imported_files": {"survey": "No survey loaded", "topography": "No topography loaded", "map": "No map loaded", "cad": "No CAD file loaded"},
    },
    "Urban Corner Lot": {
        "property_width_ft": 50,
        "property_depth_ft": 80,
        "road_location": "Corner Lot",
        "road_width_ft": 40,
        "driveway_required": False,
        "setback_front_ft": 15,
        "setback_rear_ft": 20,
        "setback_side_ft": 5,
        "max_coverage_percent": 60,
        "max_height_ft": 45,
        "slope": "Flat (0-5%)",
        "elevation_change_ft": 0,
        "solar_orientation": "Southeast-facing",
        "solar_access": False,
        "views": {"north": True, "east": True, "south": False, "west": False},
        "feature_notes": "Urban infill lot. Two street frontages. Adjacent to commercial mixed-use to the east.",
        "imported_files": {"survey": "No survey loaded", "topography": "No topography loaded", "map": "No map loaded", "cad": "No CAD file loaded"},
    },
    "Sloped Rural Lot": {
        "property_width_ft": 200,
        "property_depth_ft": 300,
        "road_location": "Front (North)",
        "road_width_ft": 20,
        "driveway_required": True,
        "setback_front_ft": 50,
        "setback_rear_ft": 50,
        "setback_side_ft": 25,
        "max_coverage_percent": 20,
        "max_height_ft": 35,
        "slope": "Moderate Slope (15-25%)",
        "elevation_change_ft": 40,
        "solar_orientation": "South-facing (optimal)",
        "solar_access": True,
        "views": {"north": False, "east": False, "south": True, "west": True},
        "feature_notes": "Sloped lot with mountain views to south and west. Creek at rear property line. Requires walkout basement design.",
        "imported_files": {"survey": "No survey loaded", "topography": "No topography loaded", "map": "No map loaded", "cad": "No CAD file loaded"},
    },
    "Lakeside Property": {
        "property_width_ft": 80,
        "property_depth_ft": 150,
        "road_location": "Rear (North)",
        "road_width_ft": 25,
        "driveway_required": True,
        "setback_front_ft": 20,
        "setback_rear_ft": 10,
        "setback_side_ft": 10,
        "max_coverage_percent": 35,
        "max_height_ft": 30,
        "slope": "Gentle Slope (5-15%)",
        "elevation_change_ft": 8,
        "solar_orientation": "Southwest-facing",
        "solar_access": True,
        "views": {"north": False, "east": False, "south": True, "west": False},
        "feature_notes": "Waterfront property on south side. Lake views from all main rooms. Wetlands setback on east side.",
        "imported_files": {"survey": "No survey loaded", "topography": "No topography loaded", "map": "No map loaded", "cad": "No CAD file loaded"},
    },
}


class ElevationFetcher(QThread):
    """Background thread for fetching elevation data from Google Maps API."""

    progress = pyqtSignal(str)  # Progress updates
    finished = pyqtSignal(dict)  # Results: {lat: {lng: elevation}}
    error = pyqtSignal(str)  # Error message

    def __init__(self, lat_center, lng_center, lat_span, lng_span, api_key, grid_points=10):
        super().__init__()
        self.lat_center = lat_center
        self.lng_center = lng_center
        self.lat_span = lat_span  # Degrees to span (property depth)
        self.lng_span = lng_span  # Degrees to span (property width)
        self.api_key = api_key
        self.grid_points = grid_points  # Points per side (10x10 = 100 points)

    def run(self):
        """Fetch elevation grid from Google Maps API."""
        try:
            self.progress.emit("Initializing elevation grid...")

            # Calculate grid bounds
            lat_start = self.lat_center - (self.lat_span / 2)
            lat_end = self.lat_center + (self.lat_span / 2)
            lng_start = self.lng_center - (self.lng_span / 2)
            lng_end = self.lng_center + (self.lng_span / 2)

            # Calculate step size
            lat_step = self.lat_span / (self.grid_points - 1)
            lng_step = self.lng_span / (self.grid_points - 1)

            # Generate elevation grid
            elevation_data = {}
            points_to_fetch = []

            # Build list of points
            for i in range(self.grid_points):
                lat = lat_start + (i * lat_step)
                for j in range(self.grid_points):
                    lng = lng_start + (j * lng_step)
                    points_to_fetch.append((lat, lng))

            # Google Maps Elevation API allows up to 512 points per request
            # However, GET requests have URL length limits (8192 chars typically)
            # We use a conservative batch size to avoid issues
            batch_size = 100  # Safe limit for GET requests with lat,lng locations
            total_batches = (len(points_to_fetch) + batch_size - 1) // batch_size

            self.progress.emit(f"Fetching {len(points_to_fetch)} elevation points...")

            for batch_num in range(total_batches):
                start_idx = batch_num * batch_size
                end_idx = min(start_idx + batch_size, len(points_to_fetch))
                batch = points_to_fetch[start_idx:end_idx]

                # Prepare request
                locations = "|".join([f"{lat},{lng}" for lat, lng in batch])

                url = f"https://maps.googleapis.com/maps/api/elevation/json"
                params = {
                    "locations": locations,
                    "key": self.api_key
                }

                # Debug: print request info
                print(f"[ElevationAPI] Request URL: {url}")
                print(f"[ElevationAPI] Locations count: {len(batch)}")
                print(f"[ElevationAPI] First location: {batch[0]}")

                # Make request
                response = requests.get(url, params=params, timeout=30)

                # Debug: print response info
                print(f"[ElevationAPI] Batch {batch_num + 1}/{total_batches}")
                print(f"[ElevationAPI] Response status: {response.status_code}")
                print(f"[ElevationAPI] URL length: {len(response.url)} chars")

                # Check for HTTP errors before processing
                if response.status_code != 200:
                    error_text = response.text[:500]
                    print(f"[ElevationAPI] Error response: {error_text}")
                    self.error.emit(
                        f"HTTP {response.status_code} - Bad Request\n\n"
                        f"This usually means:\n"
                        f"• Invalid API key\n"
                        f"• Elevation API not enabled\n"
                        f"• URL too long (try reducing grid density)\n"
                        f"• API quota exceeded"
                    )
                    return

                data = response.json()

                # Process results
                if data["status"] == "OK":
                    for idx, result in enumerate(data["results"]):
                        lat, lng = batch[idx]
                        elevation_m = result["elevation"]
                        elevation_ft = elevation_m * 3.28084  # Convert to feet
                        elevation_data[f"{lat:.6f},{lng:.6f}"] = {
                            "lat": lat,
                            "lng": lng,
                            "elevation_m": elevation_m,
                            "elevation_ft": elevation_ft,
                            "resolution": result.get("resolution", 0)
                        }
                else:
                    error_msg = data.get('error_message', data['status'])
                    status = data.get('status', 'UNKNOWN')
                    self.error.emit(f"API Error ({status}): {error_msg}")
                    return

                # Progress update
                progress_pct = int(((batch_num + 1) / total_batches) * 100)
                self.progress.emit(f"Fetching elevation data... {progress_pct}%")

            self.progress.emit(f"Complete! Retrieved {len(elevation_data)} elevation points.")
            self.finished.emit(elevation_data)

        except requests.exceptions.HTTPError as e:
            # Get response body for more details
            response_text = ""
            if hasattr(e.response, 'text'):
                response_text = e.response.text[:500]
            self.error.emit(f"HTTP {e.response.status_code}: {response_text}")
        except requests.exceptions.Timeout as e:
            self.error.emit(f"Request timeout - server took too long to respond.\nTry reducing the grid density.")
        except requests.exceptions.ConnectionError as e:
            self.error.emit(f"Connection error - check your internet connection.")
        except requests.exceptions.RequestException as e:
            self.error.emit(f"Network error: {str(e)}")
        except KeyError as e:
            self.error.emit(f"Invalid API response format - missing key: {e}")
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.error.emit(f"Error fetching elevation: {str(e)}")


class SiteDialog(QDialog):
    """
    Dialog for defining site characteristics before building design.

    Site information collected:
    - Dimensions and boundaries
    - Road location and access
    - Topography and terrain
    - Solar orientation
    - Views and features
    - Setbacks and constraints
    """

    # Signal emitted when site is defined
    site_defined = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Define Site - Step 1 of 2")
        self.setMinimumSize(700, 650)

        self.site_data = {}
        self._elevation_data = {}  # Store elevation grid from Google Maps
        self._elevation_fetcher = None  # Background thread
        self._map_boundary = None  # Boundary drawn on map
        self._building_origin = None  # Building placement on terrain
        self._existing_site = self._load_existing_site()

        # Google Maps disabled - manual inputs only
        self._has_google_maps = False
        self._map_widget = None
        self._map_placeholder = None
        self._site_editor = None  # Will be created in UI
        self._site_size_label = None  # Will be created in UI
        self._open_editor_btn = None  # Will be created in UI
        self._webview_map = None  # WebView2 map widget
        self._static_map = None  # Static map widget

        self._setup_ui()
        self._connect_signals()

        # Load existing site if found
        if self._existing_site:
            self._load_site_to_ui(self._existing_site)
            self.setWindowTitle("Edit Site - Step 1 of 2")

        # Load saved API key (defer until after UI is created)
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(100, self._load_api_key_from_settings)

    def _check_google_maps_available(self):
        """Check if Google Maps widget is available (lazy import)."""
        # Try to import, but don't fail if it doesn't work
        try:
            _init_google_maps()
        except Exception as e:
            print(f"[SiteDialog] Google Maps check failed: {e}")
            global HAS_GOOGLE_MAPS_WIDGET
            HAS_GOOGLE_MAPS_WIDGET = False

    def _setup_ui(self):
        """Setup the UI layout."""
        layout = QVBoxLayout(self)
        layout.setSpacing(15)

        # Header
        header = QLabel("Define Your Site")
        header.setStyleSheet("font-size: 18px; font-weight: bold; color: #2196F3;")
        layout.addWidget(header)

        subtitle = QLabel(
            "Import site data and define boundaries before designing your building. "
            "This ensures the design responds to its location."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(subtitle)

        # Tab widget for different site aspects
        tabs = QTabWidget()
        tabs.addTab(self._create_boundary_tab(), "Boundaries")
        tabs.addTab(self._create_terrain_tab(), "Terrain & Features")
        tabs.addTab(self._create_import_tab(), "Location & Elevation")
        layout.addWidget(tabs)

        # Site preview
        preview_group = QGroupBox("Site Preview")
        preview_layout = QVBoxLayout()
        self._preview_label = QLabel(
            "No site data yet. Fill in the form above to see preview."
        )
        self._preview_label.setStyleSheet(
            "background: #f5f5f5; padding: 15px; border-radius: 4px; "
            "color: #666; font-size: 11px;"
        )
        self._preview_label.setWordWrap(True)
        self._preview_label.setMinimumHeight(80)
        preview_layout.addWidget(self._preview_label)
        preview_group.setLayout(preview_layout)
        layout.addWidget(preview_group)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.back_btn = QPushButton("← Back")
        self.back_btn.clicked.connect(self.reject)
        button_layout.addWidget(self.back_btn)

        self.next_btn = QPushButton("Next: Design Building →")
        self.next_btn.setStyleSheet(
            "background-color: #4CAF50; color: white; "
            "padding: 10px 20px; font-weight: bold;"
        )
        self.next_btn.clicked.connect(self._on_next)
        button_layout.addWidget(self.next_btn)

        layout.addLayout(button_layout)

    def _get_site_file_path(self):
        """Get the path to the site data file."""
        config_dir = Path.home() / ".archengine"
        config_dir.mkdir(exist_ok=True)
        return config_dir / "site.json"

    def _load_existing_site(self):
        """Load existing site data from file if it exists."""
        site_file = self._get_site_file_path()
        if site_file.exists():
            try:
                with open(site_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"[SiteDialog] Error loading site: {e}")
        return None

    def _save_site(self, site_data):
        """Save site data to file for future use."""
        site_file = self._get_site_file_path()
        try:
            with open(site_file, 'w') as f:
                json.dump(site_data, f, indent=2)
            print(f"[SiteDialog] Site saved to {site_file}")
        except Exception as e:
            print(f"[SiteDialog] Error saving site: {e}")

    def _load_site_to_ui(self, site_data):
        """Populate UI fields from existing site data."""
        # Block signals to prevent triggering updates during load
        self.blockSignals(True)

        try:
            self._width_input.setValue(site_data.get("property_width_ft", 100))
            self._depth_input.setValue(site_data.get("property_depth_ft", 120))

            road_loc = site_data.get("road_location", "Front (South)")
            idx = self._road_side_combo.findText(road_loc)
            if idx >= 0:
                self._road_side_combo.setCurrentIndex(idx)

            self._road_width_input.setValue(site_data.get("road_width_ft", 30))
            self._driveway_check.setChecked(site_data.get("driveway_required", True))
            self._front_setback.setValue(site_data.get("setback_front_ft", 20))
            self._rear_setback.setValue(site_data.get("setback_rear_ft", 25))
            self._side_setback.setValue(site_data.get("setback_side_ft", 10))
            self._max_coverage.setValue(site_data.get("max_coverage_percent", 40))
            self._max_height.setValue(site_data.get("max_height_ft", 35))

            slope = site_data.get("slope", "Flat (0-5%)")
            idx = self._slope_combo.findText(slope)
            if idx >= 0:
                self._slope_combo.setCurrentIndex(idx)

            self._elevation_change.setValue(site_data.get("elevation_change_ft", 0))

            orientation = site_data.get("solar_orientation", "South-facing (optimal)")
            idx = self._orientation_combo.findText(orientation)
            if idx >= 0:
                self._orientation_combo.setCurrentIndex(idx)

            self._solar_access.setChecked(site_data.get("solar_access", True))

            views = site_data.get("views", {})
            self._view_north.setChecked(views.get("north", False))
            self._view_east.setChecked(views.get("east", False))
            self._view_south.setChecked(views.get("south", False))
            self._view_west.setChecked(views.get("west", False))

            self._feature_notes.setPlainText(site_data.get("feature_notes", ""))

            # Load Google Maps data if available
            google_maps = site_data.get("google_maps", {})
            if google_maps:
                self._api_key_input.setText(google_maps.get("api_key", ""))
                self._lat_input.setValue(google_maps.get("latitude", 45.4215))
                self._lng_input.setValue(google_maps.get("longitude", -75.6972))
                self._elevation_data = google_maps.get("elevation_grid", {})

                # Show elevation summary if data exists
                if self._elevation_data:
                    try:
                        # Handle different data formats
                        elevations_ft = []
                        for pt in self._elevation_data.values():
                            if isinstance(pt, dict):
                                if "elevation_ft" in pt:
                                    elevations_ft.append(pt["elevation_ft"])
                                elif "elevation_m" in pt:
                                    elevations_ft.append(pt["elevation_m"] * 3.28084)
                            elif isinstance(pt, (int, float)):
                                elevations_ft.append(pt * 3.28084)  # Assume meters

                        if elevations_ft:
                            min_elev = min(elevations_ft)
                            max_elev = max(elevations_ft)
                            self._elevation_results.setText(
                                f"✓ Loaded {len(self._elevation_data)} elevation points\n"
                                f"  Elevation range: {min_elev:.1f}' to {max_elev:.1f}'"
                            )
                    except Exception as e:
                        print(f"[SiteDialog] Error parsing elevation data: {e}")

            self._update_preview()

        finally:
            self.blockSignals(False)

    def _create_boundary_tab(self):
        """Create the boundary/property tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(12)

        # Property dimensions
        dim_group = QGroupBox("Property Dimensions")
        dim_layout = QFormLayout()

        self._width_input = QDoubleSpinBox()
        self._width_input.setRange(10, 1000)
        self._width_input.setValue(100)  # 100 ft default
        self._width_input.setSuffix(" ft")
        self._width_input.setSingleStep(5)
        dim_layout.addRow("Property Width:", self._width_input)

        self._depth_input = QDoubleSpinBox()
        self._depth_input.setRange(10, 1000)
        self._depth_input.setValue(120)  # 120 ft default
        self._depth_input.setSuffix(" ft")
        self._depth_input.setSingleStep(5)
        dim_layout.addRow("Property Depth:", self._depth_input)

        dim_group.setLayout(dim_layout)
        layout.addWidget(dim_group)

        # Road location
        road_group = QGroupBox("Road & Access")
        road_layout = QFormLayout()

        self._road_side_combo = QComboBox()
        self._road_side_combo.addItems([
            "Front (South)",
            "Front (North)",
            "Front (East)",
            "Front (West)",
            "Rear (South)",
            "Rear (North)",
            "Rear (East)",
            "Rear (West)",
            "Left Side",
            "Right Side",
            "Corner Lot"
        ])
        road_layout.addRow("Road Location:", self._road_side_combo)

        self._road_width_input = QDoubleSpinBox()
        self._road_width_input.setRange(10, 100)
        self._road_width_input.setValue(30)
        self._road_width_input.setSuffix(" ft")
        road_layout.addRow("Road Width:", self._road_width_input)

        self._driveway_check = QCheckBox("Driveway required")
        self._driveway_check.setChecked(True)
        road_layout.addRow("", self._driveway_check)

        road_group.setLayout(road_layout)
        layout.addWidget(road_group)

        # Setbacks
        setback_group = QGroupBox("Setbacks (from property lines)")
        setback_layout = QGridLayout()

        self._front_setback = QDoubleSpinBox()
        self._front_setback.setRange(0, 100)
        self._front_setback.setValue(20)
        self._front_setback.setSuffix(" ft")
        setback_layout.addWidget(QLabel("Front:"), 0, 0)
        setback_layout.addWidget(self._front_setback, 0, 1)

        self._rear_setback = QDoubleSpinBox()
        self._rear_setback.setRange(0, 100)
        self._rear_setback.setValue(25)
        self._rear_setback.setSuffix(" ft")
        setback_layout.addWidget(QLabel("Rear:"), 0, 2)
        setback_layout.addWidget(self._rear_setback, 0, 3)

        self._side_setback = QDoubleSpinBox()
        self._side_setback.setRange(0, 100)
        self._side_setback.setValue(10)
        self._side_setback.setSuffix(" ft")
        setback_layout.addWidget(QLabel("Side:"), 1, 0)
        setback_layout.addWidget(self._side_setback, 1, 1)

        setback_group.setLayout(setback_layout)
        layout.addWidget(setback_group)

        # Building area constraints
        area_group = QGroupBox("Building Area Limits")
        area_layout = QFormLayout()

        self._max_coverage = QSpinBox()
        self._max_coverage.setRange(10, 100)
        self._max_coverage.setValue(40)
        self._max_coverage.setSuffix(" %")
        area_layout.addRow("Max Lot Coverage:", self._max_coverage)

        self._max_height = QSpinBox()
        self._max_height.setRange(10, 100)
        self._max_height.setValue(35)
        self._max_height.setSuffix(" ft")
        area_layout.addRow("Max Building Height:", self._max_height)

        area_group.setLayout(area_layout)
        layout.addWidget(area_group)

        layout.addStretch()
        return widget

    def _create_terrain_tab(self):
        """Create the terrain/features tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(12)

        # Topography
        topo_group = QGroupBox("Topography")
        topo_layout = QFormLayout()

        self._slope_combo = QComboBox()
        self._slope_combo.addItems([
            "Flat (0-5%)",
            "Gentle Slope (5-15%)",
            "Moderate Slope (15-25%)",
            "Steep Slope (25%+)"
        ])
        topo_layout.addRow("Terrain Slope:", self._slope_combo)

        self._elevation_change = QDoubleSpinBox()
        self._elevation_change.setRange(0, 200)
        self._elevation_change.setValue(0)
        self._elevation_change.setSuffix(" ft")
        topo_layout.addRow("Elevation Change:", self._elevation_change)

        topo_group.setLayout(topo_layout)
        layout.addWidget(topo_group)

        # Solar orientation
        solar_group = QGroupBox("Solar Orientation")
        solar_layout = QFormLayout()

        self._orientation_combo = QComboBox()
        self._orientation_combo.addItems([
            "South-facing (optimal)",
            "Southeast-facing",
            "Southwest-facing",
            "East-facing (morning sun)",
            "West-facing (afternoon sun)",
            "North-facing (least sun)"
        ])
        solar_layout.addRow("Primary Orientation:", self._orientation_combo)

        self._solar_access = QCheckBox("Good solar access (no shading)")
        self._solar_access.setChecked(True)
        solar_layout.addRow("", self._solar_access)

        solar_group.setLayout(solar_layout)
        layout.addWidget(solar_group)

        # Views
        view_group = QGroupBox("Views & Features")
        view_layout = QVBoxLayout()

        view_label = QLabel("Select desirable view directions:")
        view_layout.addWidget(view_label)

        view_check_layout = QHBoxLayout()
        self._view_north = QCheckBox("North")
        self._view_east = QCheckBox("East")
        self._view_south = QCheckBox("South")
        self._view_west = QCheckBox("West")
        view_check_layout.addWidget(self._view_north)
        view_check_layout.addWidget(self._view_east)
        view_check_layout.addWidget(self._view_south)
        view_check_layout.addWidget(self._view_west)
        view_layout.addLayout(view_check_layout)

        self._feature_notes = QTextEdit()
        self._feature_notes.setPlaceholderText(
            "Note any important site features:\n"
            "- Trees to preserve\n"
            "- Water features\n"
            "- Neighboring buildings\n"
            "- Noise sources\n"
            "- prevailing winds\n"
            "- etc."
        )
        self._feature_notes.setMaximumHeight(100)
        view_layout.addWidget(QLabel("Site Features Notes:"))
        view_layout.addWidget(self._feature_notes)

        view_group.setLayout(view_layout)
        layout.addWidget(view_group)

        layout.addStretch()
        return widget

    def _create_import_tab(self):
        """Create the location & elevation tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(15)

        # Description
        desc = QLabel(
            "Define your site location using the interactive map. "
            "Draw property boundaries and import elevation data from Google or LiDAR."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(desc)

        # Location & Elevation section
        google_group = QGroupBox("Site Location & Elevation")
        google_layout = QVBoxLayout()

        # Instructions with "Get API Key" button
        instructions_layout = QHBoxLayout()

        google_desc = QLabel(
            "<b>Steps:</b> "
            "<span style='color:#2196F3'>1)</span> Get a free Google Maps API key &nbsp; "
            "<span style='color:#2196F3'>2)</span> Enter it below &nbsp; "
            "<span style='color:#2196F3'>3)</span> Search/click map &nbsp; "
            "<span style='color:#2196F3'>4)</span> Draw boundary &nbsp; "
            "<span style='color:#2196F3'>5)</span> Fetch elevation"
        )
        google_desc.setWordWrap(True)
        google_desc.setStyleSheet("color: #666; font-size: 10px;")
        instructions_layout.addWidget(google_desc, 1)

        get_api_btn = QPushButton("Get API Key")
        get_api_btn.setMaximumWidth(100)
        get_api_btn.setStyleSheet("background-color: #4CAF50; color: white; padding: 5px 10px;")
        get_api_btn.setToolTip("Open Google Cloud Console to create an API key")
        get_api_btn.clicked.connect(self._on_get_api_key)
        instructions_layout.addWidget(get_api_btn)

        google_layout.addLayout(instructions_layout)

        # Info box explaining what's needed
        info_text = QLabel(
            "<i>Required APIs: Maps JavaScript API + Maps Elevation API (free tier: $200 credit/month)</i>"
        )
        info_text.setStyleSheet("color: #FF9800; font-size: 9px; padding: 5px; background: #FFF3E0; border-radius: 3px;")
        info_text.setWordWrap(True)
        google_layout.addWidget(info_text)

        # API key input row
        api_row = QHBoxLayout()
        api_row.addWidget(QLabel("API Key:"))
        self._api_key_input = QLineEdit()
        self._api_key_input.setPlaceholderText("Enter your Google Maps API key (starts with AIza...)")
        self._api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        api_row.addWidget(self._api_key_input)

        verify_btn = QPushButton("Verify")
        verify_btn.setMaximumWidth(80)
        verify_btn.setToolTip("Test if your API key works")
        verify_btn.clicked.connect(self._on_verify_api_key)
        api_row.addWidget(verify_btn)

        google_layout.addLayout(api_row)

        self._api_key_status = QLabel("API key not verified")
        self._api_key_status.setStyleSheet("color: #999; font-size: 10px; font-style: italic;")
        google_layout.addWidget(self._api_key_status)

        # Interactive Map Widget - OpenStreetMap with drawing
        print(f"[SiteDialog] Creating Interactive Map section...")
        map_group = QGroupBox("Interactive Map (draw property boundary)")
        map_layout = QVBoxLayout()

        # Controls row
        controls_row = QHBoxLayout()
        controls_row.addWidget(QLabel("Zoom:"))
        self._map_zoom_spin = QSpinBox()
        self._map_zoom_spin.setRange(15, 21)
        self._map_zoom_spin.setValue(18)
        self._map_zoom_spin.setSuffix("x")
        self._map_zoom_spin.valueChanged.connect(self._on_map_zoom_changed)
        controls_row.addWidget(self._map_zoom_spin)

        self._clear_map_btn = QPushButton("Clear Boundary")
        self._clear_map_btn.clicked.connect(self._on_clear_map_boundary)
        controls_row.addWidget(self._clear_map_btn)

        controls_row.addStretch()
        map_layout.addLayout(controls_row)

        # Open map button
        self._open_map_btn = QPushButton("Open Interactive Map")
        self._open_map_btn.setStyleSheet("background-color: #2196F3; color: white; padding: 10px; font-size: 12px;")
        self._open_map_btn.clicked.connect(self._on_open_interactive_map)
        map_layout.addWidget(self._open_map_btn)

        # Boundary info label
        self._map_boundary_info = QLabel("Click 'Open Interactive Map' to define property boundary")
        self._map_boundary_info.setStyleSheet("color: #666; font-style: italic; padding: 10px;")
        self._map_boundary_info.setWordWrap(True)
        map_layout.addWidget(self._map_boundary_info)

        # Instructions
        instructions = QLabel(
            "<b>Instructions:</b><br>"
            "1. Click 'Open Interactive Map' to launch the map in a new window<br>"
            "2. Pan and zoom to find your property<br>"
            "3. Click 'Start Drawing' and click on map to place polygon points<br>"
            "4. Click 'Finish' to complete the polygon<br>"
            "5. Click 'Save & Close' - the dimensions will populate below"
        )
        instructions.setWordWrap(True)
        instructions.setStyleSheet("color: #333; font-size: 10px; padding: 5px; background-color: #f5f5f5; border-radius: 4px;")
        map_layout.addWidget(instructions)

        map_group.setLayout(map_layout)
        google_layout.addWidget(map_group)

        # Manual location input
        coords_group = QGroupBox("Location Coordinates")
        coords_layout = QFormLayout()

        self._lat_input = QDoubleSpinBox()
        self._lat_input.setRange(-90, 90)
        self._lat_input.setValue(45.4215)
        self._lat_input.setDecimals(6)
        self._lat_input.setSingleStep(0.0001)
        self._lat_input.setSuffix("°")
        coords_layout.addRow("Latitude:", self._lat_input)

        self._lng_input = QDoubleSpinBox()
        self._lng_input.setRange(-180, 180)
        self._lng_input.setValue(-75.6972)
        self._lng_input.setDecimals(6)
        self._lng_input.setSingleStep(0.0001)
        self._lng_input.setSuffix("°")
        coords_layout.addRow("Longitude:", self._lng_input)

        coords_group.setLayout(coords_layout)
        google_layout.addWidget(coords_group)

        # Grid density and fetch button row
        controls_row = QHBoxLayout()
        controls_row.addWidget(QLabel("Grid Density:"))
        self._grid_density_combo = QComboBox()
        self._grid_density_combo.addItem("10x10 (100 points)", 10)
        self._grid_density_combo.addItem("15x15 (225 points)", 15)
        self._grid_density_combo.addItem("20x20 (400 points)", 20)
        self._grid_density_combo.addItem("25x25 (625 points)", 25)
        self._grid_density_combo.setCurrentIndex(1)  # Default to 15x15
        controls_row.addWidget(self._grid_density_combo)
        controls_row.addStretch()

        self._fetch_elevation_btn = QPushButton("Fetch Elevation (Google)")
        self._fetch_elevation_btn.setStyleSheet("background-color: #4CAF50; color: white; padding: 8px;")
        self._fetch_elevation_btn.clicked.connect(self._on_fetch_elevation)
        controls_row.addWidget(self._fetch_elevation_btn)

        # LiDAR import button
        self._import_lidar_btn = QPushButton("Import LiDAR (GeoTIFF)")
        self._import_lidar_btn.setStyleSheet("background-color: #2196F3; color: white; padding: 8px;")
        self._import_lidar_btn.clicked.connect(self._on_import_lidar)
        self._import_lidar_btn.setToolTip("Import high-resolution elevation from Ontario LiDAR GeoTIFF files (0.5m resolution)")
        controls_row.addWidget(self._import_lidar_btn)

        google_layout.addLayout(controls_row)

        # Progress bar
        self._elevation_progress = QProgressBar()
        self._elevation_progress.setVisible(False)
        self._elevation_progress.setTextVisible(True)
        google_layout.addWidget(self._elevation_progress)

        # Results label
        self._elevation_results = QLabel("No elevation data fetched yet.")
        self._elevation_results.setWordWrap(True)
        self._elevation_results.setStyleSheet("color: #666; font-size: 10px;")
        google_layout.addWidget(self._elevation_results)

        google_group.setLayout(google_layout)
        layout.addWidget(google_group)

        layout.addStretch()
        return widget

    def _connect_signals(self):
        """Connect signals."""
        # Update preview when any value changes
        self._width_input.valueChanged.connect(self._update_preview)
        self._depth_input.valueChanged.connect(self._update_preview)
        self._road_side_combo.currentTextChanged.connect(self._update_preview)
        self._front_setback.valueChanged.connect(self._update_preview)
        self._rear_setback.valueChanged.connect(self._update_preview)
        self._side_setback.valueChanged.connect(self._update_preview)

    def _update_preview(self):
        """Update the site preview text."""
        width = self._width_input.value()
        depth = self._depth_input.value()
        road = self._road_side_combo.currentText()
        front_setback = self._front_setback.value()
        rear_setback = self._rear_setback.value()
        side_setback = self._side_setback.value()

        # Calculate buildable area
        buildable_width = width - (2 * side_setback)
        buildable_depth = depth - (front_setback + rear_setback)
        max_building_area = (buildable_width * buildable_depth)

        preview_text = f"""
<b>Site:</b> {width:.0f}' × {depth:.0f}' ({width * depth:.0f} sq ft)
<b>Road:</b> {road}
<b>Buildable Area:</b> {buildable_width:.0f}' × {buildable_depth:.0f}' ({max_building_area:.0f} sq ft)
<b>Max Coverage:</b> {self._max_coverage.value()}% = {max_building_area * self._max_coverage.value() / 100:.0f} sq ft building footprint
"""
        self._preview_label.setText(preview_text)

    def _on_get_api_key(self):
        """Open Google Cloud Console to help user create an API key."""
        import webbrowser
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QPushButton

        # Create dialog with instructions
        dialog = QDialog(self)
        dialog.setWindowTitle("How to Get a Google Maps API Key")
        dialog.setMinimumSize(600, 500)

        layout = QVBoxLayout(dialog)

        instructions = QTextEdit()
        instructions.setReadOnly(True)
        instructions.setHtml("""
        <h2>Getting Your Free Google Maps API Key</h2>

        <ol>
        <li><b>Create a Google Cloud Project</b>
            <ul>
            <li>Go to <a href="https://console.cloud.google.com/">Google Cloud Console</a></li>
            <li>Click the project dropdown and select "New Project"</li>
            <li>Enter a project name (e.g., "ArchEngine") and click "Create"</li>
            </ul>
        </li>

        <li><b>Enable Required APIs</b>
            <ul>
            <li>Go to <a href="https://console.cloud.google.com/apis/library">APIs & Services → Library</a></li>
            <li>Search for and enable: <b>Maps JavaScript API</b></li>
            <li>Search for and enable: <b>Maps Elevation API</b></li>
            </ul>
        </li>

        <li><b>Create API Key</b>
            <ul>
            <li>Go to <a href="https://console.cloud.google.com/apis/credentials">APIs & Services → Credentials</a></li>
            <li>Click "Create Credentials" → "API Key"</li>
            <li>Copy the API key (starts with "AIza...")</li>
            </ul>
        </li>

        <li><b>Configure API Key</b>
            <ul>
            <li>Click the edit icon (pencil) next to your API key</li>
            <li>Under "Application restrictions", select <b>None</b></li>
            <li>Under "API restrictions", select:
                <ul>
                <li>Maps JavaScript API</li>
                <li>Maps Elevation API</li>
                </ul>
            </li>
            <li>Click "Save"</li>
            </ul>
        </li>
        </ol>

        <h3>Important Notes:</h3>
        <ul>
        <li>Google provides <b>$200 free credit/month</b> - more than enough for personal use</li>
        <li>Keep your API key private - don't share it publicly</li>
        <li>The key will be saved locally on your computer</li>
        <li>Both APIs must be enabled for the feature to work</li>
        </ul>
        """)
        layout.addWidget(instructions)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        open_console_btn = QPushButton("Open Google Cloud Console")
        open_console_btn.setStyleSheet("background-color: #4CAF50; color: white; padding: 8px 16px;")
        open_console_btn.clicked.connect(lambda: webbrowser.open("https://console.cloud.google.com/apis/credentials"))
        button_layout.addWidget(open_console_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        button_layout.addWidget(close_btn)

        layout.addLayout(button_layout)

        dialog.exec()

    def _on_verify_api_key(self):
        """Verify the Google Maps API key by making a test request."""
        api_key = self._api_key_input.text().strip()
        if not api_key:
            QMessageBox.warning(self, "API Key Required",
                "Please enter your Google Maps API key first.")
            return

        self._api_key_status.setText("Verifying...")
        self._api_key_status.setStyleSheet("color: #FFA500; font-size: 10px;")
        QApplication.processEvents()

        try:
            # Test request to Elevation API with a single location
            url = "https://maps.googleapis.com/maps/api/elevation/json"
            params = {
                "locations": "45.4215,-75.6972",  # Ottawa
                "key": api_key
            }

            response = requests.get(url, params=params, timeout=10)

            print(f"[VerifyAPI] Status: {response.status_code}")
            print(f"[VerifyAPI] Response: {response.text[:200]}")

            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "OK":
                    elevation = data["results"][0]["elevation"]
                    self._api_key_status.setText(
                        f"✓ API key verified! Elevation: {elevation:.1f}m"
                    )
                    self._api_key_status.setStyleSheet(
                        "color: #4CAF50; font-size: 10px; font-weight: bold;"
                    )
                    QMessageBox.information(self, "API Key Verified",
                        f"Your API key is working!\n\n"
                        f"Test elevation (Ottawa): {elevation:.1f}m ({elevation * 3.28:.1f} ft)\n\n"
                        f"You can now fetch elevation data for your site.")
                else:
                    error_msg = data.get('error_message', data.get('status', 'Unknown error'))
                    self._api_key_status.setText(f"✗ API error: {error_msg}")
                    self._api_key_status.setStyleSheet("color: #f44336; font-size: 10px;")
                    QMessageBox.critical(self, "API Error",
                        f"API returned an error:\n\n{error_msg}\n\n"
                        f"Common fixes:\n"
                        f"• Enable 'Maps Elevation API' in Google Cloud Console\n"
                        f"• Check API restrictions (set to 'None' for testing)\n"
                        f"• Ensure billing is enabled")
            else:
                self._api_key_status.setText(f"✗ HTTP {response.status_code}")
                self._api_key_status.setStyleSheet("color: #f44336; font-size: 10px;")
                QMessageBox.critical(self, "HTTP Error",
                    f"Server returned HTTP {response.status_code}\n\n"
                    f"{response.text[:200]}")

        except requests.exceptions.RequestException as e:
            self._api_key_status.setText("✗ Network error")
            self._api_key_status.setStyleSheet("color: #f44336; font-size: 10px;")
            QMessageBox.critical(self, "Network Error",
                f"Could not connect to Google Maps API:\n\n{str(e)}\n\n"
                f"Please check your internet connection.")
        except Exception as e:
            self._api_key_status.setText("✗ Error")
            self._api_key_status.setStyleSheet("color: #f44336; font-size: 10px;")
            QMessageBox.critical(self, "Error",
                f"Unexpected error:\n\n{str(e)}")

    def _on_api_key_changed(self, text: str):
        """Update map widget when API key changes."""
        print(f"[SiteDialog] API key changed, length: {len(text.strip())}")
        if self._map_widget and text.strip():
            print(f"[SiteDialog] Calling set_api_key on map widget...")
            self._map_widget.set_api_key(text.strip())
        else:
            print(f"[SiteDialog] Map widget exists: {self._map_widget is not None}, text is empty: {not text.strip()}")

        # Save API key to settings for next time
        self._save_api_key_to_settings()

    def _on_open_site_editor(self):
        """Open site editor in a popup dialog."""
        if not HAS_SITE_EDITOR:
            QMessageBox.warning(self, "Not Available",
                "Site editor widget is not available.")
            return

        try:
            # Create a dialog for the site editor
            editor_dialog = QDialog(self)
            editor_dialog.setWindowTitle("Draw Site Boundary")
            editor_dialog.setMinimumSize(600, 500)

            layout = QVBoxLayout(editor_dialog)

            # Instructions
            instructions = QLabel(
                "Drag the corners to set your property size. "
                "Click OK when done."
            )
            instructions.setStyleSheet("color: #666; font-size: 11px; padding: 5px;")
            layout.addWidget(instructions)

            # Create site editor widget
            site_editor = SiteEditorWidget()
            site_editor.setMinimumHeight(400)

            # Set initial size if already set
            try:
                if hasattr(self, '_width_input') and self._width_input:
                    initial_width = self._width_input.value()
                else:
                    initial_width = 100

                if hasattr(self, '_depth_input') and self._depth_input:
                    initial_depth = self._depth_input.value()
                else:
                    initial_depth = 120

                site_editor.set_size_ft(initial_width, initial_depth)
            except Exception as e:
                print(f"[SiteDialog] Error setting initial size: {e}")
                site_editor.set_size_ft(100, 120)

            layout.addWidget(site_editor)

            # Buttons
            button_row = QHBoxLayout()
            button_row.addStretch()

            cancel_btn = QPushButton("Cancel")
            cancel_btn.clicked.connect(editor_dialog.reject)
            button_row.addWidget(cancel_btn)

            ok_btn = QPushButton("OK")
            ok_btn.setStyleSheet("background-color: #4CAF50; color: white; padding: 8px;")
            ok_btn.clicked.connect(editor_dialog.accept)
            button_row.addWidget(ok_btn)

            layout.addLayout(button_row)

            # Show dialog
            result = editor_dialog.exec()

            if result == QDialog.DialogCode.Accepted:
                # Get the size from the editor
                width_ft, depth_ft = site_editor.get_size_ft()

                # Update the width/depth inputs if they exist
                try:
                    if hasattr(self, '_width_input') and self._width_input:
                        self._width_input.blockSignals(True)
                        self._width_input.setValue(int(width_ft))
                        self._width_input.blockSignals(False)

                    if hasattr(self, '_depth_input') and self._depth_input:
                        self._depth_input.blockSignals(True)
                        self._depth_input.setValue(int(depth_ft))
                        self._depth_input.blockSignals(False)
                except Exception as e:
                    print(f"[SiteDialog] Error updating width/depth inputs: {e}")

                # Update label
                area_sqft = width_ft * depth_ft
                if self._site_size_label:
                    self._site_size_label.setText(
                        f"Current size: {width_ft:.0f}' × {depth_ft:.0f}' = {area_sqft:.0f} sq ft"
                    )

                print(f"[SiteDialog] Site size set to {width_ft:.0f}' x {depth_ft:.0f}'")

        except Exception as e:
            QMessageBox.critical(self, "Error",
                f"Could not open site editor:\n\n{str(e)}")
            print(f"[SiteDialog] Error opening site editor: {e}")

    def _on_clear_map_boundary(self):
        """Clear the boundary on the static map."""
        if hasattr(self, '_static_map') and self._static_map:
            self._static_map.clear_boundary()
        if hasattr(self, '_webview_map') and self._webview_map:
            self._webview_map.clear_boundary()

        self._map_boundary = None
        if hasattr(self, '_map_boundary_info'):
            self._map_boundary_info.setText("Click 'Open Interactive Map' to define property boundary")
        print(f"[SiteDialog] Map boundary cleared")

    def _on_open_interactive_map(self):
        """Open the interactive OpenStreetMap/Leaflet map."""
        lat = self._lat_input.value()
        lng = self._lng_input.value()
        zoom = self._map_zoom_spin.value()
        api_key = self._api_key_input.text().strip()  # Get API key for elevation probing

        print(f"[SiteDialog] Opening interactive map at ({lat}, {lng}), zoom {zoom}")
        if api_key:
            print(f"[SiteDialog] Elevation probe enabled with API key")

        try:
            # Lazy import to avoid startup crashes
            print("[SiteDialog] Attempting to import EmbeddedMapWidget...")
            from widgets.embedded_map_widget import EmbeddedMapWidget
            print("[SiteDialog] EmbeddedMapWidget imported successfully")

            # Create embedded map widget as a dialog (top-level window, not parented)
            # This prevents the map from closing if SiteDialog closes or has issues
            print("[SiteDialog] Creating map dialog...")
            from PyQt6.QtWidgets import QDialog
            map_dialog = QDialog()  # Top-level window (no parent)
            map_dialog.setWindowTitle("Property Boundary Map - Legible Studio")
            map_dialog.setMinimumSize(900, 700)
            map_dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)  # Don't auto-delete
            print("[SiteDialog] Map dialog created")

            dialog_layout = QVBoxLayout(map_dialog)
            dialog_layout.setContentsMargins(0, 0, 0, 0)

            # Create embedded map widget with API key for elevation probing
            print("[SiteDialog] Creating EmbeddedMapWidget...")
            try:
                self._embedded_map = EmbeddedMapWidget(lat, lng, zoom, api_key=api_key, parent=map_dialog)
                print("[SiteDialog] EmbeddedMapWidget created successfully")
            except Exception as widget_err:
                print(f"[SiteDialog] ERROR creating EmbeddedMapWidget: {widget_err}")
                import traceback
                traceback.print_exc()
                QMessageBox.critical(self, "Map Error",
                    f"Failed to create map widget:\n{widget_err}")
                return

            print("[SiteDialog] Adding EmbeddedMapWidget to layout...")
            dialog_layout.addWidget(self._embedded_map)
            print("[SiteDialog] EmbeddedMapWidget added to layout")

            # Connect signals
            self._embedded_map.boundary_changed.connect(self._on_map_boundary_changed_with_dims)
            self._embedded_map.building_placed.connect(self._on_building_placed)
            print("[SiteDialog] Signals connected")

            # Connect close signal to close the map dialog (accept for modal dialogs)
            self._embedded_map.close_requested.connect(map_dialog.accept)

            # Store reference to dialog so it doesn't get garbage collected
            self._map_dialog = map_dialog
            self._embedded_map_ref = self._embedded_map  # Extra reference

            # Show the dialog as a MODAL window so it stays open
            # Using exec() instead of show() to ensure the dialog stays open
            print("[SiteDialog] Showing map dialog (modal)...")

            # Force process events before showing to ensure widget is fully initialized
            QApplication.processEvents()

            # Execute the dialog modally - this blocks until user closes it
            result = map_dialog.exec()
            print(f"[SiteDialog] Map dialog closed with result: {result}")

        except ImportError as e:
            QMessageBox.warning(self, "Not Available",
                f"Interactive map is not available.\n\n"
                f"Error: {str(e)}\n\n"
                f"Required: PyQt6-WebEngine\n"
                f"pip install PyQt6-WebEngine")
            print(f"[SiteDialog] Cannot import embedded map: {e}")
            import traceback
            traceback.print_exc()
        except Exception as e:
            QMessageBox.critical(self, "Error",
                f"Could not open map:\n{str(e)}")
            print(f"[SiteDialog] Error opening map: {e}")
            import traceback
            traceback.print_exc()

    def _on_map_boundary_changed_with_dims(self, lat_min, lat_max, lng_min, lng_max, width_ft, depth_ft, vertices=None, vertices_ft=None):
        """Handle boundary changed with dimensions and polygon vertices."""
        num_verts = len(vertices) if vertices else 0
        print(f"[SiteDialog] Boundary received: {width_ft:.0f}' x {depth_ft:.0f}' ({num_verts} vertices)")
        print(f"[SiteDialog] Lat/Lng bounds: lat=[{lat_min:.6f}, {lat_max:.6f}], lng=[{lng_min:.6f}, {lng_max:.6f}]")

        # Update UI with dimensions
        self._width_input.setValue(int(width_ft))
        self._depth_input.setValue(int(depth_ft))

        # Update info label
        if hasattr(self, '_map_boundary_info'):
            lat_center = (lat_min + lat_max) / 2
            lng_center = (lng_min + lng_max) / 2
            shape_info = f" ({num_verts}-sided)" if num_verts > 0 else ""
            self._map_boundary_info.setText(
                f"Boundary set: {width_ft:.0f}' x {depth_ft:.0f}'{shape_info} at "
                f"({lat_center:.4f}, {lng_center:.4f})"
            )

        # Store boundary for elevation fetching (including actual polygon shape)
        self._map_boundary = {
            'lat_min': lat_min,
            'lat_max': lat_max,
            'lng_min': lng_min,
            'lng_max': lng_max,
            'width_ft': width_ft,
            'depth_ft': depth_ft,
            'vertices': vertices,        # [[lat, lng], ...] - actual polygon
            'vertices_ft': vertices_ft   # [[x_ft, z_ft], ...] - in local coords
        }

        # Info label already shows the boundary - no popup needed

    def _on_building_placed(self, lat: float, lng: float, x_ft: float, z_ft: float, rotation_deg: float):
        """Handle building placement from map."""
        print(f"[SiteDialog] Building center at ({x_ft:.0f}', {z_ft:.0f}'), rotation={rotation_deg:.0f}°")

        # Store building origin (center position and rotation)
        self._building_origin = {
            'lat': lat,
            'lng': lng,
            'x_ft': x_ft,
            'z_ft': z_ft,
            'rotation_deg': rotation_deg
        }

        # Update info label - no popup needed, label shows current values
        if hasattr(self, '_map_boundary_info') and self._map_boundary:
            self._map_boundary_info.setText(
                f"Boundary: {self._map_boundary['width_ft']:.0f}' x {self._map_boundary['depth_ft']:.0f}' | "
                f"Building center: ({x_ft:.0f}', {z_ft:.0f}') rot={rotation_deg:.0f}°"
            )

    def _on_navigate_to_location(self):
        """Navigate the map to the current coordinates."""
        if hasattr(self, '_webview_map') and self._webview_map:
            lat = self._lat_input.value()
            lng = self._lng_input.value()
            zoom = self._map_zoom_spin.value()
            self._webview_map.set_location(lat, lng, zoom)
            print(f"[SiteDialog] Navigating map to ({lat}, {lng}), zoom {zoom}")

    def _on_map_zoom_changed(self, value):
        """Handle zoom level change."""
        if hasattr(self, '_webview_map') and self._webview_map:
            self._webview_map.set_zoom(value)

    def _on_map_boundary_changed(self, lat_min, lat_max, lng_min, lng_max):
        """Handle boundary drawn on the interactive map."""
        # Calculate width and depth from lat/lng bounds
        # Approximate: 1 degree latitude ≈ 69 miles, 1 degree longitude ≈ 69 miles * cos(latitude)
        lat_center = (lat_min + lat_max) / 2
        lat_deg_to_ft = 364000  # Approximate feet per degree latitude
        lng_deg_to_ft = 364000 * 0.7071  # Approximate feet per degree longitude at 45° latitude

        width_ft = abs(lng_max - lng_min) * lng_deg_to_ft
        depth_ft = abs(lat_max - lat_min) * lat_deg_to_ft

        # Update UI
        self._width_input.setValue(int(width_ft))
        self._depth_input.setValue(int(depth_ft))

        # Update info label
        if hasattr(self, '_map_boundary_info'):
            self._map_boundary_info.setText(
                f"Boundary set: {width_ft:.0f}' x {depth_ft:.0f}' at "
                f"({lat_center:.4f}, {(lng_min + lng_max)/2:.4f})"
            )

        # Store boundary for elevation fetching
        self._map_boundary = {
            'lat_min': lat_min,
            'lat_max': lat_max,
            'lng_min': lng_min,
            'lng_max': lng_max,
            'width_ft': width_ft,
            'depth_ft': depth_ft
        }

        print(f"[SiteDialog] Map boundary changed: {width_ft:.0f}' x {depth_ft:.0f}'")

    def _load_api_key_from_settings(self):
        """Load API key from QSettings if previously saved."""
        settings = QSettings("ArchEngine", "CAD")
        saved_key = settings.value("google_maps_api_key", "", str)
        if saved_key and hasattr(self, '_api_key_input'):
            self._api_key_input.setText(saved_key)
            print(f"[SiteDialog] Loaded saved API key (length: {len(saved_key)})")

    def _save_api_key_to_settings(self):
        """Save API key to QSettings for future use."""
        if not hasattr(self, '_api_key_input'):
            return
        api_key = self._api_key_input.text().strip()
        settings = QSettings("ArchEngine", "CAD")
        settings.setValue("google_maps_api_key", api_key)
        print(f"[SiteDialog] Saved API key to settings (length: {len(api_key)})")

    def _on_boundary_drawn(self, boundary: dict):
        """Handle boundary drawn on map - auto-populate width/depth."""
        if not boundary:
            return

        # Auto-populate width/depth from boundary
        width_ft = boundary.get('width_ft', 0)
        depth_ft = boundary.get('depth_ft', 0)

        if width_ft > 0 and depth_ft > 0:
            self._width_input.setValue(int(width_ft))
            self._depth_input.setValue(int(depth_ft))
            print(f"[SiteDialog] Auto-populated dimensions from map: {width_ft:.0f}' x {depth_ft:.0f}'")

        # Store boundary data for elevation fetching
        self._map_boundary = boundary

    def _on_site_boundary_changed(self, lat_min, lat_max, lng_min, lng_max):
        """Handle boundary changed from site editor."""
        # Site editor disabled - this method is no longer used
        pass

    def _on_fetch_elevation(self):
        """Fetch elevation data from Google Maps API."""
        api_key = self._api_key_input.text().strip()
        if not api_key:
            QMessageBox.warning(self, "API Key Required",
                "Please enter your Google Maps API key.\n\n"
                "Get one at: https://console.cloud.google.com/\n"
                "Enable 'Maps JavaScript API' and 'Maps Elevation API'")
            return

        # Use boundary coordinates if available from map widget
        if self._map_widget and hasattr(self, '_map_boundary') and self._map_boundary:
            boundary = self._map_boundary
            lat = (boundary['lat_min'] + boundary['lat_max']) / 2
            lng = (boundary['lng_min'] + boundary['lng_max']) / 2
            lat_span_deg = boundary['lat_max'] - boundary['lat_min']
            lng_span_deg = boundary['lng_max'] - boundary['lng_min']
            print(f"[SiteDialog] Using map boundary for elevation: {lat:.4f}, {lng:.4f}")
        else:
            # Fallback to manual inputs
            if hasattr(self, '_lat_input'):
                lat = self._lat_input.value()
                lng = self._lng_input.value()
            elif self._map_widget:
                lat, lng = self._map_widget.get_coordinates()
            else:
                QMessageBox.warning(self, "Location Required",
                    "Please select a location on the map or enter coordinates.")
                return

            width_ft = self._width_input.value()
            depth_ft = self._depth_input.value()

            # Convert property dimensions to degrees (approximate)
            # 1 degree latitude ≈ 69 miles (364,000 ft)
            # 1 degree longitude varies by latitude
            lat_span_deg = (depth_ft / 364000.0)
            lng_span_deg = (width_ft / 364000.0) / max(0.01, abs(lat))

        grid_points = self._grid_density_combo.currentData()
        total_points = grid_points * grid_points
        estimated_batches = (total_points + 99) // 100  # 100 point batch size

        print(f"[SiteDialog] Fetching elevation: {total_points} points in ~{estimated_batches} batches")

        # Warn user if using very high density
        if total_points > 400:
            reply = QMessageBox.question(
                self,
                "Large Grid Warning",
                f"You're about to fetch {total_points} elevation points.\n\n"
                f"This will make ~{estimated_batches} API requests and may take a while.\n\n"
                f"Would you like to use a smaller grid (15x15 or less) for faster results?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._grid_density_combo.setCurrentIndex(1)  # Switch to 15x15
                grid_points = 15
                total_points = 225

        # Disable button and show progress
        self._fetch_elevation_btn.setEnabled(False)
        self._elevation_progress.setVisible(True)
        self._elevation_progress.setRange(0, 100)  # Indeterminate
        self._elevation_progress.setValue(0)
        self._elevation_results.setText("Initializing...")

        # Start background fetcher
        self._elevation_fetcher = ElevationFetcher(
            lat, lng, lat_span_deg, lng_span_deg, api_key, grid_points
        )
        self._elevation_fetcher.progress.connect(self._on_elevation_progress)
        self._elevation_fetcher.finished.connect(self._on_elevation_finished)
        self._elevation_fetcher.error.connect(self._on_elevation_error)
        self._elevation_fetcher.start()

    def _on_elevation_progress(self, message):
        """Handle elevation fetch progress updates."""
        self._elevation_results.setText(message)
        self._elevation_progress.setValue(self._elevation_progress.value() + 1)

    def _on_elevation_finished(self, elevation_data):
        """Handle successful elevation fetch."""
        self._elevation_data = elevation_data

        # Calculate statistics
        elevations_ft = [pt["elevation_ft"] for pt in elevation_data.values()]
        min_elev = min(elevations_ft)
        max_elev = max(elevations_ft)
        elev_change = max_elev - min_elev

        # Determine slope category
        if elev_change < 2:
            slope = "Flat (0-5%)"
        elif elev_change < 10:
            slope = "Gentle Slope (5-15%)"
        elif elev_change < 25:
            slope = "Moderate Slope (15-25%)"
        else:
            slope = "Steep Slope (25%+)"

        # Update UI with results
        self._elevation_results.setText(
            f"✓ Fetched {len(elevation_data)} elevation points\n"
            f"  Elevation range: {min_elev:.1f}' to {max_elev:.1f}' (change: {elev_change:.1f}')\n"
            f"  Terrain: {slope}"
        )
        self._elevation_progress.setValue(100)
        self._fetch_elevation_btn.setEnabled(True)

        # Auto-update terrain tab with fetched data
        self._elevation_change.setValue(int(elev_change))
        idx = self._slope_combo.findText(slope)
        if idx >= 0:
            self._slope_combo.setCurrentIndex(idx)

        # Store in site data
        print(f"[SiteDialog] Elevation data fetched: {len(elevation_data)} points")
        print(f"[SiteDialog]   Min: {min_elev:.1f}', Max: {max_elev:.1f}', Change: {elev_change:.1f}'")

        # Generate terrain mesh
        print("[SiteDialog] Generating terrain mesh...")
        try:
            # Build boundary data with polygon vertices if available
            boundary_data = {}
            if hasattr(self, '_map_boundary') and self._map_boundary:
                boundary_data = {
                    "lat_min": self._map_boundary.get("lat_min", 0),
                    "lat_max": self._map_boundary.get("lat_max", 0),
                    "lng_min": self._map_boundary.get("lng_min", 0),
                    "lng_max": self._map_boundary.get("lng_max", 0),
                    "width_ft": self._map_boundary.get("width_ft", 0),
                    "depth_ft": self._map_boundary.get("depth_ft", 0),
                }
                # Include polygon vertices if available
                if self._map_boundary.get("vertices_ft"):
                    boundary_data["vertices_ft"] = self._map_boundary["vertices_ft"]
                    boundary_data["vertices_mm"] = [
                        [v[0] * 304.8, v[1] * 304.8] for v in self._map_boundary["vertices_ft"]
                    ]
                    print(f"[SiteDialog] Including polygon with {len(boundary_data['vertices_mm'])} vertices")

            # Create temporary site dict for terrain generation
            temp_site = {
                "property_width_ft": self._width_input.value(),
                "property_depth_ft": self._depth_input.value(),
                "google_maps": {
                    "elevation_grid": self._elevation_data,
                    "boundary": boundary_data
                }
            }

            mesh = generate_terrain_from_site(temp_site)
            if mesh:
                self._terrain_mesh = mesh
                print(f"[SiteDialog] Terrain mesh generated: {len(mesh.vertices)} vertices, {len(mesh.indices)//3} triangles")
                self._elevation_results.setText(
                    self._elevation_results.text() + f"\n  ✓ 3D mesh generated ({len(mesh.vertices)} vertices)"
                )
        except Exception as e:
            print(f"[SiteDialog] Error generating terrain mesh: {e}")
            import traceback
            traceback.print_exc()

    def _on_elevation_error(self, error_msg):
        """Handle elevation fetch error."""
        self._elevation_results.setText(f"Error: {error_msg}")
        self._elevation_progress.setVisible(False)
        self._fetch_elevation_btn.setEnabled(True)
        QMessageBox.critical(self, "Elevation Fetch Failed",
            f"Could not fetch elevation data:\n{error_msg}\n\n"
            "Please check:\n"
            "• API key is correct\n"
            "• Elevation API is enabled\n"
            "• Internet connection is active")

    def _on_import_lidar(self):
        """Import elevation data from LiDAR GeoTIFF files."""
        # Check for rasterio
        try:
            import rasterio
            from pyproj import Transformer
        except ImportError:
            QMessageBox.critical(self, "Missing Libraries",
                "LiDAR import requires additional libraries.\n\n"
                "Please install them:\n"
                "  pip install rasterio pyproj")
            return

        # Select folder with GeoTIFF files
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select LiDAR GeoTIFF Folder",
            "",
            QFileDialog.Option.ShowDirsOnly
        )

        if not folder:
            return

        # Show import settings dialog
        settings_dialog = LidarImportSettingsDialog(self)
        if settings_dialog.exec() != QDialog.DialogCode.Accepted:
            return

        # Get user's quality settings
        self._lidar_import_settings = settings_dialog.get_settings()
        print(f"[SiteDialog] LiDAR import settings: {self._lidar_import_settings}")

        print(f"[SiteDialog] LiDAR folder selected: {folder}")
        self._elevation_results.setText("Scanning for GeoTIFF files...")

        # Use new library if available for cleaner processing
        if HAS_LIDAR_LIB:
            QTimer.singleShot(100, lambda: self._import_lidar_with_library(folder))
        else:
            # Fallback to original implementation
            QTimer.singleShot(100, lambda: self._preview_lidar_folder(folder))

    def _import_lidar_with_library(self, folder):
        """Import LiDAR using the lidar library (cleaner implementation)."""
        try:
            extractor = LidarExtractor()

            # Scan folder with progress
            self._elevation_results.setText("Scanning tiles...")
            QApplication.processEvents()

            count = extractor.scan_folder(folder)
            if count == 0:
                self._elevation_results.setText("No GeoTIFF tiles found in folder.")
                return

            # Get property bounds
            if hasattr(self, '_map_boundary') and self._map_boundary:
                bounds = PropertyBounds.from_bounds(
                    lat_min=self._map_boundary['lat_min'],
                    lat_max=self._map_boundary['lat_max'],
                    lng_min=self._map_boundary['lng_min'],
                    lng_max=self._map_boundary['lng_max'],
                )
            else:
                # Use property dimensions to estimate bounds
                # Default to a reasonable location if not set
                QMessageBox.warning(self, "No Property Boundary",
                    "Please draw a property boundary on the map first,\n"
                    "or enter coordinates manually.")
                return

            # Find overlapping tiles
            overlapping = extractor.find_overlapping_tiles(bounds)
            if not overlapping:
                self._elevation_results.setText(
                    f"Found {count} tiles, but none overlap your property.\n"
                    "Check that the property boundary is correct."
                )
                return

            self._elevation_results.setText(
                f"Found {len(overlapping)} tile(s) covering your property.\n"
                "Extracting elevation data..."
            )
            QApplication.processEvents()

            # Extract elevation
            def progress_cb(current, total, msg):
                self._elevation_results.setText(f"Processing {current}/{total}: {msg}")
                QApplication.processEvents()

            data = extractor.extract_elevation(
                overlapping,
                bounds,
                max_points=150000,
                progress_callback=progress_cb
            )

            if data.count == 0:
                self._elevation_results.setText("No elevation data found in the property area.")
                return

            # Convert to internal format expected by terrain generator
            # Format: {"lat,lng": {"lat": lat, "lng": lng, "elevation_m": m, "elevation_ft": ft}}
            self._elevation_data = {}
            for key, pt in data.points.items():
                data_key = f"{pt.lat:.7f},{pt.lng:.7f}"
                self._elevation_data[data_key] = {
                    "lat": pt.lat,
                    "lng": pt.lng,
                    "elevation_m": pt.elevation_m,
                    "elevation_ft": pt.elevation_ft
                }

            # Update UI
            self._elevation_results.setText(
                f"✓ LiDAR data imported!\n"
                f"  Points: {data.count:,}\n"
                f"  Elevation: {data.min_elevation_m:.1f}m to {data.max_elevation_m:.1f}m\n"
                f"  Range: {data.elevation_range_m:.2f}m ({data.elevation_range_ft:.1f}ft)\n"
                f"  Tiles: {len(data.source_tiles)}"
            )

            # Generate terrain mesh
            self._generate_lidar_terrain_mesh(data.min_elevation_m)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self._elevation_results.setText(f"Error: {e}")

    def _parse_ontario_lidar_filename(self, filename):
        """
        Parse Ontario LiDAR filename to extract approximate UTM coordinates.
        Format: 1km{zone}{easting_km}{northing}...
        Example: 1km175420512303030LLAKENIPISSING_DSM.tif
                 -> zone 17, easting ~542000, northing ~5123030
        Returns (easting, northing) or None if can't parse.
        """
        import re
        basename = os.path.basename(filename)

        # Try to match Ontario LiDAR naming pattern
        # The format appears to be: 1km + zone(2) + easting(3-4) + northing(7+) + name
        # Example: 1km 17 542 0512303 030 LLAKENIPISSING
        match = re.match(r'1km(\d{2})(\d{3,4})(\d{7})', basename)
        if match:
            try:
                zone = int(match.group(1))
                easting_km = int(match.group(2))
                northing_coded = int(match.group(3))

                # Easting: multiply km by 1000 to get meters
                easting = easting_km * 1000

                # Northing: the 7-digit code represents the northing
                # 0512303 -> 5123030 (shift decimal)
                northing = northing_coded * 10

                print(f"[SiteDialog] Parsed {basename}: zone={zone}, E={easting}, N={northing}")
                return (easting, northing)
            except Exception as e:
                print(f"[SiteDialog] Parse error for {basename}: {e}")
        else:
            print(f"[SiteDialog] Could not parse filename: {basename}")
        return None

    def _preview_lidar_folder(self, folder):
        """Preview available LiDAR tiles in folder."""
        import os
        try:
            import rasterio
            from pyproj import Transformer
        except ImportError as e:
            self._elevation_results.setText(f"Import error: {e}")
            return

        # Check if we have a boundary to filter by
        has_boundary = hasattr(self, '_map_boundary') and self._map_boundary
        property_utm = None

        if has_boundary:
            boundary = self._map_boundary
            center_lat = (boundary['lat_min'] + boundary['lat_max']) / 2
            center_lng = (boundary['lng_min'] + boundary['lng_max']) / 2
            print(f"[SiteDialog] Property center: ({center_lat:.6f}, {center_lng:.6f})")

            # Convert property center to UTM for quick filtering
            try:
                # Determine UTM zone (rough estimate for Ontario)
                utm_zone = int((center_lng + 180) / 6) + 1
                utm_crs = f"EPSG:{32600 + utm_zone}" if center_lat >= 0 else f"EPSG:{32700 + utm_zone}"
                to_utm = Transformer.from_crs("EPSG:4326", utm_crs, always_xy=True)
                prop_easting, prop_northing = to_utm.transform(center_lng, center_lat)
                property_utm = (prop_easting, prop_northing, utm_zone)
                print(f"[SiteDialog] Property UTM (zone {utm_zone}): E={prop_easting:.0f}, N={prop_northing:.0f}")
            except Exception as e:
                print(f"[SiteDialog] Could not convert property to UTM: {e}")

        # Find all TIFF files
        tiff_files = []
        for root, dirs, files in os.walk(folder):
            for f in files:
                if f.lower().endswith(('.tif', '.tiff')):
                    tiff_files.append(os.path.join(root, f))

        if not tiff_files:
            self._elevation_results.setText("No GeoTIFF files found in folder.")
            return

        print(f"[SiteDialog] Found {len(tiff_files)} TIFF files in folder")

        # Quick filter: parse filenames to find potentially matching tiles
        # This avoids opening every single file
        candidate_files = []
        parsed_count = 0
        for tiff_path in tiff_files:
            coords = self._parse_ontario_lidar_filename(tiff_path)
            if coords:
                parsed_count += 1
                if property_utm:
                    easting, northing = coords
                    prop_e, prop_n, _ = property_utm
                    # Check if within ~2km (tiles are 1km, property might be on edge)
                    if abs(easting - prop_e) < 2000 and abs(northing - prop_n) < 2000:
                        candidate_files.append(tiff_path)
                        print(f"[SiteDialog] ✓ Candidate: {os.path.basename(tiff_path)} - E={easting}, N={northing} (dist: E={abs(easting-prop_e):.0f}, N={abs(northing-prop_n):.0f})")
                    else:
                        print(f"[SiteDialog]   Skipping {os.path.basename(tiff_path)} - too far (dist: E={abs(easting-prop_e):.0f}, N={abs(northing-prop_n):.0f})")
                else:
                    # No property UTM, can't filter, include all parsed
                    candidate_files.append(tiff_path)
            else:
                # Can't parse filename, include as candidate to be safe
                candidate_files.append(tiff_path)
                print(f"[SiteDialog] Including unparseable file: {os.path.basename(tiff_path)}")

        print(f"[SiteDialog] Parsed {parsed_count}/{len(tiff_files)} filenames, {len(candidate_files)} candidates")

        # If we filtered down, use candidates; otherwise limit to first 100
        if len(candidate_files) > 0 and len(candidate_files) < len(tiff_files):
            files_to_scan = candidate_files
            print(f"[SiteDialog] Filtered to {len(candidate_files)} candidate tiles")
        elif len(candidate_files) > 0:
            files_to_scan = candidate_files[:100]  # Limit if too many
            if len(candidate_files) > 100:
                print(f"[SiteDialog] Limited to first 100 of {len(candidate_files)} candidates")
        else:
            files_to_scan = tiff_files[:50]  # Fallback
            print(f"[SiteDialog] No candidates, using first 50 tiles as fallback")

        # Gather detailed info from candidate files
        tile_info = []
        for tiff_path in files_to_scan:
            try:
                with rasterio.open(tiff_path) as src:
                    bounds = src.bounds
                    crs = src.crs
                    res = src.res[0]

                    tile_lat_min = None
                    tile_lat_max = None
                    tile_lng_min = None
                    tile_lng_max = None
                    try:
                        transformer = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
                        tile_lng_min, tile_lat_min = transformer.transform(bounds.left, bounds.bottom)
                        tile_lng_max, tile_lat_max = transformer.transform(bounds.right, bounds.top)
                        bounds_str = f"({tile_lat_min:.4f}, {tile_lng_min:.4f}) to ({tile_lat_max:.4f}, {tile_lng_max:.4f})"
                    except Exception as e:
                        bounds_str = f"CRS: {crs}"
                        print(f"[SiteDialog] Could not transform bounds for {os.path.basename(tiff_path)}: {e}")

                    tile_info.append({
                        'path': tiff_path,
                        'name': os.path.basename(tiff_path),
                        'resolution': res,
                        'size': f"{src.width}x{src.height}",
                        'bounds': bounds_str,
                        'lat_min': tile_lat_min,
                        'lat_max': tile_lat_max,
                        'lng_min': tile_lng_min,
                        'lng_max': tile_lng_max,
                    })
                    print(f"[SiteDialog] Tile: {os.path.basename(tiff_path)} - lat: {tile_lat_min:.6f} to {tile_lat_max:.6f}, lng: {tile_lng_min:.6f} to {tile_lng_max:.6f}")
            except Exception as e:
                print(f"[SiteDialog] Could not read {os.path.basename(tiff_path)}: {e}")
                continue

        if not tile_info:
            self._elevation_results.setText("Could not read any GeoTIFF files.")
            return

        # Show dialog with available tiles
        self._show_lidar_preview_dialog(folder, tile_info)

    def _show_lidar_preview_dialog(self, folder, tile_info):
        """Show dialog with available LiDAR tiles."""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QListWidget, QListWidgetItem, QDialogButtonBox, QHBoxLayout

        dialog = QDialog(self)
        dialog.setWindowTitle("Available LiDAR Tiles")
        dialog.setMinimumSize(600, 400)

        layout = QVBoxLayout(dialog)

        # Header
        header = QLabel(f"<b>Found {len(tile_info)} GeoTIFF files in:</b><br>{folder}")
        header.setWordWrap(True)
        layout.addWidget(header)

        # Check if we have a boundary
        has_boundary = hasattr(self, '_map_boundary') and self._map_boundary
        if has_boundary:
            boundary = self._map_boundary
            center_lat = (boundary['lat_min'] + boundary['lat_max']) / 2
            center_lng = (boundary['lng_min'] + boundary['lng_max']) / 2
            boundary_label = QLabel(f"<b>Your property:</b> ({center_lat:.5f}, {center_lng:.5f})")
            layout.addWidget(boundary_label)
        else:
            boundary_label = QLabel("<span style='color: orange;'><b>Note:</b> Draw a property boundary first to auto-find the right tile.</span>")
            boundary_label.setWordWrap(True)
            layout.addWidget(boundary_label)

        # Tile list
        list_label = QLabel("<b>Available tiles:</b> (select one to import)")
        layout.addWidget(list_label)

        tile_list = QListWidget()
        tile_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        overlapping_tiles = []

        for idx, info in enumerate(tile_info):
            # Check if this tile OVERLAPS with the property boundary (not just center)
            overlaps_property = False
            if has_boundary and info.get('lat_min') is not None:
                try:
                    # Check for rectangle overlap (tile overlaps property bounding box)
                    prop_lat_min = boundary['lat_min']
                    prop_lat_max = boundary['lat_max']
                    prop_lng_min = boundary['lng_min']
                    prop_lng_max = boundary['lng_max']

                    # Two rectangles overlap if they intersect on both axes
                    lat_overlap = info['lat_min'] <= prop_lat_max and info['lat_max'] >= prop_lat_min
                    lng_overlap = info['lng_min'] <= prop_lng_max and info['lng_max'] >= prop_lng_min

                    if lat_overlap and lng_overlap:
                        overlaps_property = True
                        overlapping_tiles.append(info['path'])
                        print(f"[SiteDialog] ✓ MATCH: {info['name']} overlaps property")
                except:
                    pass

            prefix = "✓ " if overlaps_property else "  "
            item_text = f"{prefix}{info['name']} | {info['resolution']:.2f}m | {info['size']} | {info['bounds']}"
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, info['path'])
            if overlaps_property:
                item.setBackground(Qt.GlobalColor.green)
                item.setSelected(True)  # Auto-select overlapping tiles
            tile_list.addItem(item)

        layout.addWidget(tile_list)

        # Show info about overlapping tiles
        if overlapping_tiles:
            if len(overlapping_tiles) == 1:
                info_label = QLabel("<span style='color: green;'><b>✓ Found 1 tile covering your property!</b></span>")
            else:
                info_label = QLabel(f"<span style='color: green;'><b>✓ Found {len(overlapping_tiles)} tiles covering your property!</b></span><br>"
                                   f"All overlapping tiles are auto-selected and will be merged.")
            info_label.setWordWrap(True)
            layout.addWidget(info_label)
        elif has_boundary:
            # No overlapping tile - warn user
            info_label = QLabel(
                f"<span style='color: red;'><b>⚠ None of these tiles overlap your property!</b></span><br>"
                f"Your property bounds: ({boundary['lat_min']:.5f}, {boundary['lng_min']:.5f}) to ({boundary['lat_max']:.5f}, {boundary['lng_max']:.5f}).<br>"
                f"You need to download the correct LiDAR tile from Ontario GeoHub."
            )
            info_label.setWordWrap(True)
            layout.addWidget(info_label)

        # Store overlapping tiles for import
        self._overlapping_lidar_tiles = overlapping_tiles

        # Buttons
        button_box = QDialogButtonBox()
        import_btn = button_box.addButton("Import Selected", QDialogButtonBox.ButtonRole.AcceptRole)
        cancel_btn = button_box.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)

        import_btn.setEnabled(len(tile_list.selectedItems()) > 0)
        tile_list.itemSelectionChanged.connect(lambda: import_btn.setEnabled(len(tile_list.selectedItems()) > 0))

        layout.addWidget(button_box)

        # Store for access in slot
        self._lidar_tile_list = tile_list
        self._lidar_folder = folder

        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            # Get ALL selected tiles
            selected_paths = []
            for item in tile_list.selectedItems():
                path = item.data(Qt.ItemDataRole.UserRole)
                if path:
                    selected_paths.append(path)

            if selected_paths:
                print(f"[SiteDialog] Selected {len(selected_paths)} tile(s): {[os.path.basename(p) for p in selected_paths]}")

                # Check if we have boundary
                if not has_boundary:
                    QMessageBox.warning(self, "Boundary Required",
                        "Please draw a property boundary on the map first.\n\n"
                        "The LiDAR importer needs to know the area to extract.")
                    return

                if len(selected_paths) == 1:
                    self._elevation_results.setText(f"Importing from {os.path.basename(selected_paths[0])}...")
                else:
                    self._elevation_results.setText(f"Importing from {len(selected_paths)} tiles...")

                self._elevation_progress.setVisible(True)
                self._elevation_progress.setRange(0, 0)
                QTimer.singleShot(100, lambda: self._process_lidar_files(selected_paths))

    def _process_lidar_files(self, tiff_paths):
        """Process multiple LiDAR GeoTIFF files and merge elevation data."""
        import os
        import math
        try:
            import rasterio
            from pyproj import Transformer
            from core.terrain import TerrainMesh, TerrainVertex
        except ImportError as e:
            self._elevation_results.setText(f"Import error: {e}")
            self._elevation_progress.setVisible(False)
            return

        if not tiff_paths:
            return

        # Get property boundary
        boundary = self._map_boundary
        prop_lat_min = boundary['lat_min']
        prop_lat_max = boundary['lat_max']
        prop_lng_min = boundary['lng_min']
        prop_lng_max = boundary['lng_max']
        center_lat = (prop_lat_min + prop_lat_max) / 2
        center_lng = (prop_lng_min + prop_lng_max) / 2

        # Calculate property size in meters
        lat_range = prop_lat_max - prop_lat_min
        lng_range = prop_lng_max - prop_lng_min
        height_m = lat_range * 111000
        width_m = lng_range * 111000 * math.cos(math.radians(center_lat))

        print(f"[SiteDialog] Processing {len(tiff_paths)} tiles for property")
        print(f"[SiteDialog] Property bounds: ({prop_lat_min:.6f}, {prop_lng_min:.6f}) to ({prop_lat_max:.6f}, {prop_lng_max:.6f})")
        print(f"[SiteDialog] Property size: {width_m:.1f}m x {height_m:.1f}m")

        # Merged elevation data from all tiles
        merged_elevation_data = {}
        min_elev_global = float('inf')
        max_elev_global = float('-inf')
        total_points = 0
        resolution = None

        for tiff_path in tiff_paths:
            try:
                print(f"[SiteDialog] Processing tile: {os.path.basename(tiff_path)}")

                with rasterio.open(tiff_path) as src:
                    raster_crs = src.crs
                    resolution = src.res[0]
                    transformer = Transformer.from_crs("EPSG:4326", raster_crs, always_xy=True)
                    reverse_transformer = Transformer.from_crs(raster_crs, "EPSG:4326", always_xy=True)

                    # Convert property bounds to raster CRS
                    min_x, min_y = transformer.transform(prop_lng_min, prop_lat_min)
                    max_x, max_y = transformer.transform(prop_lng_max, prop_lat_max)

                    # Add small buffer
                    buffer = 5
                    min_x -= buffer
                    max_x += buffer
                    min_y -= buffer
                    max_y += buffer

                    # Check if this tile overlaps with property in raster CRS
                    tile_bounds = src.bounds
                    if (max_x < tile_bounds.left or min_x > tile_bounds.right or
                        max_y < tile_bounds.bottom or min_y > tile_bounds.top):
                        print(f"[SiteDialog]   Tile doesn't overlap property, skipping")
                        continue

                    # Clamp to tile bounds
                    extract_min_x = max(min_x, tile_bounds.left)
                    extract_max_x = min(max_x, tile_bounds.right)
                    extract_min_y = max(min_y, tile_bounds.bottom)
                    extract_max_y = min(max_y, tile_bounds.top)

                    # Get pixel coordinates
                    row_start, col_start = src.index(extract_min_x, extract_max_y)
                    row_end, col_end = src.index(extract_max_x, extract_min_y)

                    # Clamp to valid range
                    row_start = max(0, min(row_start, src.height - 1))
                    row_end = max(0, min(row_end + 1, src.height))
                    col_start = max(0, min(col_start, src.width - 1))
                    col_end = max(0, min(col_end + 1, src.width))

                    if row_end <= row_start or col_end <= col_start:
                        print(f"[SiteDialog]   No valid pixel range, skipping")
                        continue

                    # Read elevation window
                    elevation = src.read(1)
                    window_data = elevation[row_start:row_end, col_start:col_end]
                    nodata = src.nodata

                    print(f"[SiteDialog]   Extracted {window_data.shape[1]}x{window_data.shape[0]} pixels")

                    # Subsample if needed
                    max_points_per_tile = 75000
                    tile_total = window_data.shape[0] * window_data.shape[1]
                    step = max(1, int(math.sqrt(tile_total / max_points_per_tile)))

                    # Extract elevation points
                    tile_points = 0
                    for row_idx in range(0, window_data.shape[0], step):
                        for col_idx in range(0, window_data.shape[1], step):
                            elev = float(window_data[row_idx, col_idx])
                            if nodata is not None and elev == nodata:
                                continue

                            # Convert pixel to geographic coordinates
                            px = extract_min_x + (col_idx + 0.5) * resolution
                            py = extract_max_y - (row_idx + 0.5) * resolution
                            plng, plat = reverse_transformer.transform(px, py)

                            # Only include points within property bounds
                            if prop_lat_min <= plat <= prop_lat_max and prop_lng_min <= plng <= prop_lng_max:
                                key = f"{plat:.7f},{plng:.7f}"
                                merged_elevation_data[key] = {
                                    "lat": plat,
                                    "lng": plng,
                                    "elevation_m": elev,
                                    "elevation_ft": elev * 3.28084
                                }
                                tile_points += 1
                                min_elev_global = min(min_elev_global, elev)
                                max_elev_global = max(max_elev_global, elev)

                    print(f"[SiteDialog]   Added {tile_points} points from this tile")
                    total_points += tile_points

            except Exception as e:
                print(f"[SiteDialog] Error processing {os.path.basename(tiff_path)}: {e}")
                import traceback
                traceback.print_exc()
                continue

        # Check if we got any data
        if not merged_elevation_data:
            self._elevation_results.setText("No elevation data found in property area.")
            self._elevation_progress.setVisible(False)
            return

        elev_range = max_elev_global - min_elev_global
        print(f"[SiteDialog] Total merged: {len(merged_elevation_data)} elevation points")
        print(f"[SiteDialog] Elevation range: {min_elev_global:.2f}m to {max_elev_global:.2f}m (range: {elev_range:.2f}m)")

        # Store the merged elevation data
        self._elevation_data = merged_elevation_data

        # Update UI
        self._elevation_progress.setVisible(False)
        self._elevation_results.setText(
            f"✓ LiDAR data imported from {len(tiff_paths)} tile(s)!\n"
            f"  Resolution: {resolution:.2f}m\n"
            f"  Points: {len(merged_elevation_data)}\n"
            f"  Elevation: {min_elev_global:.1f}m to {max_elev_global:.1f}m\n"
            f"  Range: {elev_range:.2f}m ({elev_range * 3.28084:.1f}ft)"
        )

        # Generate terrain mesh
        self._generate_lidar_terrain_mesh(min_elev_global)

    def _process_lidar_file(self, tiff_path):
        """Process a specific LiDAR GeoTIFF file and extract elevation."""
        # Delegate to multi-file processor
        self._process_lidar_files([tiff_path])
        return

    def _process_lidar_file_old(self, tiff_path):
        """Process a specific LiDAR GeoTIFF file and extract elevation (old single-file version)."""
        import os
        import math
        try:
            import rasterio
            from pyproj import Transformer
            from core.terrain import TerrainMesh, TerrainVertex
        except ImportError as e:
            self._elevation_results.setText(f"Import error: {e}")
            self._elevation_progress.setVisible(False)
            return

        # Get property boundary
        boundary = self._map_boundary
        center_lat = (boundary['lat_min'] + boundary['lat_max']) / 2
        center_lng = (boundary['lng_min'] + boundary['lng_max']) / 2

        # Calculate property size in meters
        lat_range = boundary['lat_max'] - boundary['lat_min']
        lng_range = boundary['lng_max'] - boundary['lng_min']
        height_m = lat_range * 111000
        width_m = lng_range * 111000 * math.cos(math.radians(center_lat))

        print(f"[SiteDialog] Extracting from: {os.path.basename(tiff_path)}")
        print(f"[SiteDialog] Property center: ({center_lat:.6f}, {center_lng:.6f})")
        print(f"[SiteDialog] Property size: {width_m:.1f}m x {height_m:.1f}m")

        try:
            print(f"[SiteDialog] Opening raster: {tiff_path}")
            with rasterio.open(tiff_path) as src:
                raster_crs = src.crs
                resolution = src.res[0]
                print(f"[SiteDialog] Raster CRS: {raster_crs}, resolution: {resolution}m")
                print(f"[SiteDialog] Raster bounds: {src.bounds}")

                transformer = Transformer.from_crs("EPSG:4326", raster_crs, always_xy=True)
                reverse_transformer = Transformer.from_crs(raster_crs, "EPSG:4326", always_xy=True)

                # Convert center to raster CRS
                center_x, center_y = transformer.transform(center_lng, center_lat)
                print(f"[SiteDialog] Center in raster CRS: ({center_x:.2f}, {center_y:.2f})")

                # Calculate bounds with buffer
                buffer = 5
                half_w = (width_m / 2) + buffer
                half_h = (height_m / 2) + buffer

                min_x = center_x - half_w
                max_x = center_x + half_w
                min_y = center_y - half_h
                max_y = center_y + half_h
                print(f"[SiteDialog] Extract bounds: X=[{min_x:.2f}, {max_x:.2f}], Y=[{min_y:.2f}, {max_y:.2f}]")

                # Get pixel coordinates
                row_start, col_start = src.index(min_x, max_y)
                row_end, col_end = src.index(max_x, min_y)
                print(f"[SiteDialog] Pixel indices (raw): rows=[{row_start}, {row_end}], cols=[{col_start}, {col_end}]")

                # Clamp to valid range
                row_start = max(0, min(row_start, src.height - 1))
                row_end = max(0, min(row_end, src.height))
                col_start = max(0, min(col_start, src.width - 1))
                col_end = max(0, min(col_end, src.width))
                print(f"[SiteDialog] Pixel indices (clamped): rows=[{row_start}, {row_end}], cols=[{col_start}, {col_end}]")

                if row_end <= row_start or col_end <= col_start:
                    self._elevation_results.setText("Property area is outside the raster bounds.")
                    self._elevation_progress.setVisible(False)
                    return

                # Read elevation window
                elevation = src.read(1)
                window_data = elevation[row_start:row_end, col_start:col_end]
                nodata = src.nodata

                print(f"[SiteDialog] Extracted {window_data.shape[1]}x{window_data.shape[0]} pixels")

                # Calculate stats
                if nodata is not None:
                    valid_mask = window_data != nodata
                else:
                    valid_mask = np.ones_like(window_data, dtype=bool)
                valid_data = window_data[valid_mask]

                if len(valid_data) == 0:
                    self._elevation_results.setText("No valid elevation data in property area.")
                    self._elevation_progress.setVisible(False)
                    return

                min_elev = float(valid_data.min())
                max_elev = float(valid_data.max())
                elev_range = max_elev - min_elev

                print(f"[SiteDialog] Elevation: {min_elev:.2f}m to {max_elev:.2f}m (range: {elev_range:.2f}m)")

                # Convert to elevation grid format
                self._elevation_data = {}
                point_count = 0

                # Subsample if too many points - use custom setting if available
                # Higher max_points = more surface detail but slower processing
                if hasattr(self, '_lidar_import_settings') and self._lidar_import_settings:
                    max_points = self._lidar_import_settings.get("max_points", 200000)
                else:
                    max_points = 200000  # Default
                total_points = window_data.shape[0] * window_data.shape[1]
                step = max(1, int(math.sqrt(total_points / max_points)))
                print(f"[SiteDialog] Total pixels: {total_points}, using step={step} for ~{total_points // (step*step)} points")

                for row_idx in range(0, window_data.shape[0], step):
                    for col_idx in range(0, window_data.shape[1], step):
                        elev = float(window_data[row_idx, col_idx])
                        if nodata is not None and elev == nodata:
                            continue

                        # Convert pixel to geographic coordinates
                        px = min_x + (col_idx + 0.5) * resolution
                        py = max_y - (row_idx + 0.5) * resolution
                        plng, plat = reverse_transformer.transform(px, py)

                        key = f"{plat:.7f},{plng:.7f}"
                        self._elevation_data[key] = {
                            "lat": plat,
                            "lng": plng,
                            "elevation_m": elev,
                            "elevation_ft": elev * 3.28084
                        }
                        point_count += 1

                print(f"[SiteDialog] Created {point_count} elevation points (step={step})")

                # Update UI
                self._elevation_progress.setVisible(False)
                self._elevation_results.setText(
                    f"✓ LiDAR data imported!\n"
                    f"  Source: {os.path.basename(tiff_path)}\n"
                    f"  Resolution: {resolution:.2f}m\n"
                    f"  Points: {point_count}\n"
                    f"  Elevation: {min_elev:.1f}m to {max_elev:.1f}m\n"
                    f"  Range: {elev_range:.2f}m ({elev_range * 3.28084:.1f}ft)"
                )

                # Generate terrain mesh
                self._generate_lidar_terrain_mesh(min_elev)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self._elevation_results.setText(f"Error reading LiDAR: {e}")
            self._elevation_progress.setVisible(False)

    def _process_lidar_folder(self, folder):
        """Process LiDAR GeoTIFF folder and extract elevation."""
        import os
        try:
            import rasterio
            from pyproj import Transformer
            from core.terrain import TerrainMesh, TerrainVertex
        except ImportError as e:
            self._elevation_results.setText(f"Import error: {e}")
            self._elevation_progress.setVisible(False)
            return

        # Find all TIFF files
        tiff_files = []
        for root, dirs, files in os.walk(folder):
            for f in files:
                if f.lower().endswith(('.tif', '.tiff')):
                    tiff_files.append(os.path.join(root, f))

        if not tiff_files:
            self._elevation_results.setText("No GeoTIFF files found in folder.")
            self._elevation_progress.setVisible(False)
            return

        print(f"[SiteDialog] Found {len(tiff_files)} GeoTIFF files")
        self._elevation_results.setText(f"Found {len(tiff_files)} GeoTIFF files. Searching for your property...")

        # Get property center from boundary
        boundary = self._map_boundary
        center_lat = (boundary['lat_min'] + boundary['lat_max']) / 2
        center_lng = (boundary['lng_min'] + boundary['lng_max']) / 2

        # Calculate property size in meters (approximate)
        lat_range = boundary['lat_max'] - boundary['lat_min']
        lng_range = boundary['lng_max'] - boundary['lng_min']
        # 1 degree lat ≈ 111,000m, 1 degree lng ≈ 111,000m * cos(lat)
        import math
        height_m = lat_range * 111000
        width_m = lng_range * 111000 * math.cos(math.radians(center_lat))

        print(f"[SiteDialog] Property center: ({center_lat:.6f}, {center_lng:.6f})")
        print(f"[SiteDialog] Property size: {width_m:.1f}m x {height_m:.1f}m")

        # Find tile containing property
        found_tile = None
        for tiff_path in tiff_files:
            try:
                with rasterio.open(tiff_path) as src:
                    raster_crs = src.crs
                    transformer = Transformer.from_crs("EPSG:4326", raster_crs, always_xy=True)
                    x, y = transformer.transform(center_lng, center_lat)

                    bounds = src.bounds
                    if bounds.left <= x <= bounds.right and bounds.bottom <= y <= bounds.top:
                        found_tile = tiff_path
                        print(f"[SiteDialog] Found tile: {os.path.basename(tiff_path)}")
                        print(f"[SiteDialog] Resolution: {src.res[0]:.2f}m")
                        break
            except Exception as e:
                continue

        if not found_tile:
            self._elevation_results.setText(
                f"No tile covers your property location.\n"
                f"Center: ({center_lat:.6f}, {center_lng:.6f})\n"
                f"Downloaded data may be for a different area.")
            self._elevation_progress.setVisible(False)
            return

        # Extract elevation data
        self._elevation_results.setText(f"Extracting elevation from {os.path.basename(found_tile)}...")

        try:
            with rasterio.open(found_tile) as src:
                raster_crs = src.crs
                transformer = Transformer.from_crs("EPSG:4326", raster_crs, always_xy=True)
                reverse_transformer = Transformer.from_crs(raster_crs, "EPSG:4326", always_xy=True)

                # Convert center to raster CRS
                center_x, center_y = transformer.transform(center_lng, center_lat)

                # Calculate bounds with some buffer
                buffer = 5  # 5m buffer
                half_w = (width_m / 2) + buffer
                half_h = (height_m / 2) + buffer

                min_x = center_x - half_w
                max_x = center_x + half_w
                min_y = center_y - half_h
                max_y = center_y + half_h

                # Get pixel coordinates
                row_start, col_start = src.index(min_x, max_y)
                row_end, col_end = src.index(max_x, min_y)

                # Clamp to valid range
                row_start = max(0, min(row_start, src.height - 1))
                row_end = max(0, min(row_end, src.height))
                col_start = max(0, min(col_start, src.width - 1))
                col_end = max(0, min(col_end, src.width))

                if row_end <= row_start or col_end <= col_start:
                    self._elevation_results.setText("Property area is outside the raster bounds.")
                    self._elevation_progress.setVisible(False)
                    return

                # Read elevation window
                elevation = src.read(1)
                window_data = elevation[row_start:row_end, col_start:col_end]
                resolution = src.res[0]
                nodata = src.nodata

                print(f"[SiteDialog] Extracted {window_data.shape[1]}x{window_data.shape[0]} pixels")

                # Calculate stats
                valid_mask = window_data != nodata if nodata else np.ones_like(window_data, dtype=bool)
                valid_data = window_data[valid_mask]

                if len(valid_data) == 0:
                    self._elevation_results.setText("No valid elevation data in property area.")
                    self._elevation_progress.setVisible(False)
                    return

                min_elev = float(valid_data.min())
                max_elev = float(valid_data.max())
                elev_range = max_elev - min_elev

                print(f"[SiteDialog] Elevation: {min_elev:.2f}m to {max_elev:.2f}m (range: {elev_range:.2f}m)")

                # Convert to elevation grid format for terrain generator
                self._elevation_data = {}
                point_count = 0

                # Subsample if too many points - use custom setting if available
                if hasattr(self, '_lidar_import_settings') and self._lidar_import_settings:
                    max_points = self._lidar_import_settings.get("max_points", 200000)
                else:
                    max_points = 200000  # Default
                total_points = window_data.shape[0] * window_data.shape[1]
                step = max(1, int(math.sqrt(total_points / max_points)))

                for row_idx in range(0, window_data.shape[0], step):
                    for col_idx in range(0, window_data.shape[1], step):
                        elev = float(window_data[row_idx, col_idx])
                        if nodata and elev == nodata:
                            continue

                        # Convert pixel to geographic coordinates
                        px = min_x + (col_idx + 0.5) * resolution
                        py = max_y - (row_idx + 0.5) * resolution
                        plng, plat = reverse_transformer.transform(px, py)

                        key = f"{plat:.7f},{plng:.7f}"
                        self._elevation_data[key] = {
                            "lat": plat,
                            "lng": plng,
                            "elevation_m": elev,
                            "elevation_ft": elev * 3.28084
                        }
                        point_count += 1

                print(f"[SiteDialog] Created {point_count} elevation points (step={step})")

                # Update UI
                self._elevation_progress.setVisible(False)
                self._elevation_results.setText(
                    f"✓ LiDAR data imported!\n"
                    f"  Source: {os.path.basename(found_tile)}\n"
                    f"  Resolution: {resolution:.2f}m\n"
                    f"  Points: {point_count}\n"
                    f"  Elevation: {min_elev:.1f}m to {max_elev:.1f}m\n"
                    f"  Range: {elev_range:.2f}m ({elev_range * 3.28084:.1f}ft)"
                )

                # Generate terrain mesh
                self._generate_lidar_terrain_mesh(min_elev)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self._elevation_results.setText(f"Error reading LiDAR: {e}")
            self._elevation_progress.setVisible(False)

    def _generate_lidar_terrain_mesh(self, min_elevation_m):
        """
        Prepare terrain data for C++ generation (skips slow Python preview).

        The actual mesh generation happens in the viewport using fast C++ code
        when the project is loaded.
        """
        num_points = len(self._elevation_data) if self._elevation_data else 0
        grid_res = 250
        if hasattr(self, '_lidar_import_settings') and self._lidar_import_settings:
            grid_res = self._lidar_import_settings.get("grid_resolution", 250)
        expected_tris = 2 * grid_res * grid_res

        print(f"[SiteDialog] Terrain data ready for C++ generation:")
        print(f"  - {num_points:,} elevation points")
        print(f"  - Grid resolution: {grid_res} (~{expected_tris:,} triangles)")
        print(f"  - Mesh will be generated by viewport using C++")

        # Update UI - no preview, just confirmation
        self._elevation_results.setText(
            self._elevation_results.text() +
            f"\n\n✓ Terrain data ready ({num_points:,} points)\n"
            f"   3D mesh will be generated when project loads (C++)"
        )

        # Don't generate mesh here - viewport will do it with C++
        # Just ensure the settings flag is set
        if not hasattr(self, '_lidar_import_settings'):
            self._lidar_import_settings = {}
        self._lidar_import_settings['use_cpp_generation'] = True
        self._lidar_import_settings['grid_resolution'] = grid_res

    def _on_next(self):
        """Handle Next button - validate and emit site data."""
        # Validate
        if self._width_input.value() <= 0 or self._depth_input.value() <= 0:
            QMessageBox.warning(self, "Invalid Dimensions", "Please enter valid property dimensions.")
            return

        # Collect site data
        self.site_data = {
            "property_width_ft": self._width_input.value(),
            "property_depth_ft": self._depth_input.value(),
            "road_location": self._road_side_combo.currentText(),
            "road_width_ft": self._road_width_input.value(),
            "driveway_required": self._driveway_check.isChecked(),
            "setback_front_ft": self._front_setback.value(),
            "setback_rear_ft": self._rear_setback.value(),
            "setback_side_ft": self._side_setback.value(),
            "max_coverage_percent": self._max_coverage.value(),
            "max_height_ft": self._max_height.value(),
            "slope": self._slope_combo.currentText(),
            "elevation_change_ft": self._elevation_change.value(),
            "solar_orientation": self._orientation_combo.currentText(),
            "solar_access": self._solar_access.isChecked(),
            "views": {
                "north": self._view_north.isChecked(),
                "east": self._view_east.isChecked(),
                "south": self._view_south.isChecked(),
                "west": self._view_west.isChecked(),
            },
            "feature_notes": self._feature_notes.toPlainText(),
        }

        # Calculate buildable area
        buildable_width = (self._width_input.value() -
                          2 * self._side_setback.value())
        buildable_depth = (self._depth_input.value() -
                          (self._front_setback.value() + self._rear_setback.value()))
        self.site_data["buildable_width_ft"] = buildable_width
        self.site_data["buildable_depth_ft"] = buildable_depth
        self.site_data["buildable_area_sqft"] = buildable_width * buildable_depth
        self.site_data["max_building_footprint_sqft"] = (
            buildable_width * buildable_depth * self._max_coverage.value() / 100
        )

        # Add Google Maps data
        google_maps_data = {
            "api_key": self._api_key_input.text().strip(),
            "elevation_grid": self._elevation_data if self._elevation_data else {}
        }

        # Add coordinates (from map widget or manual input)
        if self._map_widget:
            lat, lng = self._map_widget.get_coordinates()
            google_maps_data["latitude"] = lat
            google_maps_data["longitude"] = lng
        elif hasattr(self, '_lat_input'):
            google_maps_data["latitude"] = self._lat_input.value()
            google_maps_data["longitude"] = self._lng_input.value()

        # Add boundary data if drawn on map (including polygon vertices)
        print(f"[SiteDialog] _map_boundary exists: {hasattr(self, '_map_boundary')}, value: {getattr(self, '_map_boundary', None)}")
        if hasattr(self, '_map_boundary') and self._map_boundary:
            print(f"[SiteDialog] Saving boundary: lat=[{self._map_boundary['lat_min']:.6f}, {self._map_boundary['lat_max']:.6f}], lng=[{self._map_boundary['lng_min']:.6f}, {self._map_boundary['lng_max']:.6f}]")
            boundary_data = {
                "lat_min": self._map_boundary["lat_min"],
                "lat_max": self._map_boundary["lat_max"],
                "lng_min": self._map_boundary["lng_min"],
                "lng_max": self._map_boundary["lng_max"],
                "width_ft": self._map_boundary.get("width_ft", 0),
                "depth_ft": self._map_boundary.get("depth_ft", 0)
            }
            # Include actual polygon vertices if available
            if self._map_boundary.get("vertices"):
                boundary_data["vertices"] = self._map_boundary["vertices"]
                boundary_data["vertices_ft"] = self._map_boundary.get("vertices_ft")
                # Convert to mm for terrain generator
                boundary_data["vertices_mm"] = [
                    [v[0] * 304.8, v[1] * 304.8] for v in self._map_boundary.get("vertices_ft", [])
                ]
                print(f"[SiteDialog] Polygon boundary saved: {len(boundary_data['vertices'])} vertices")
            google_maps_data["boundary"] = boundary_data

        self.site_data["google_maps"] = google_maps_data

        # Add building origin if placed on map
        if self._building_origin:
            rotation_deg = self._building_origin.get("rotation_deg", 0.0)
            self.site_data["building_origin"] = {
                "lat": self._building_origin["lat"],
                "lng": self._building_origin["lng"],
                "x_ft": self._building_origin["x_ft"],
                "z_ft": self._building_origin["z_ft"],
                "rotation_deg": rotation_deg,
                # Convert to mm for renderer (building coordinates are in mm)
                "x_mm": self._building_origin["x_ft"] * 304.8,
                "z_mm": self._building_origin["z_ft"] * 304.8,
                "rotation_rad": rotation_deg * 3.14159265 / 180.0
            }
            print(f"[SiteDialog] Building origin saved: center=({self._building_origin['x_ft']:.0f}', {self._building_origin['z_ft']:.0f}'), rotation={rotation_deg:.0f}°")
        else:
            print(f"[SiteDialog] WARNING: No building origin set (_building_origin is None/empty)")

        # Add terrain mesh if generated (Python fallback)
        if hasattr(self, '_terrain_mesh') and self._terrain_mesh:
            self.site_data["terrain_mesh"] = self._terrain_mesh.to_dict()
            print(f"[SiteDialog] Terrain mesh saved to site data")

        # Add terrain generation settings for C++ generation (faster)
        # The viewport will use this to generate terrain directly in C++
        if self._elevation_data:
            terrain_settings = {
                "use_cpp_generation": True,  # Always use C++ for speed
                "grid_resolution": 250,  # Default
            }
            if hasattr(self, '_lidar_import_settings') and self._lidar_import_settings:
                terrain_settings["grid_resolution"] = self._lidar_import_settings.get("grid_resolution", 250)
                terrain_settings["use_cpp_generation"] = self._lidar_import_settings.get("use_cpp_generation", True)
            self.site_data["terrain_generation_settings"] = terrain_settings
            print(f"[SiteDialog] C++ terrain generation: grid_resolution={terrain_settings['grid_resolution']}, points={len(self._elevation_data)}")

        # Save site for future use
        self._save_site(self.site_data)

        # Emit signal and accept
        self.site_defined.emit(self.site_data)
        self.accept()


def show_site_dialog(parent=None):
    """
    Show the site definition dialog and return site data.

    Returns:
        dict: Site data if user clicked Next, None if cancelled
    """
    dialog = SiteDialog(parent)
    result = dialog.exec()

    if result == QDialog.DialogCode.Accepted:
        return dialog.site_data
    return None
