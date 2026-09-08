"""
Simplified Site Dialog
======================
Shows only interactive map and LiDAR data selection.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QProgressBar, QFileDialog, QMessageBox, QWidget,
    QDialogButtonBox
)
from PyQt6.QtCore import Qt, QTimer, QSettings
from pathlib import Path
import json

# LiDAR extraction library
try:
    from tools.lidar import LidarExtractor
    HAS_LIDAR_LIB = True
except ImportError:
    HAS_LIDAR_LIB = False


class SimpleSiteDialog(QDialog):
    """Simplified site dialog with map and LiDAR only."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Site Location")
        self.setMinimumSize(900, 700)

        # Load saved settings
        self._settings = QSettings('LegibleStudios', 'ArchEngine')
        self._last_lidar_folder = self._settings.value('last_lidar_folder', '')
        self._last_map_lat = float(self._settings.value('last_map_lat', 43.6532))
        self._last_map_lng = float(self._settings.value('last_map_lng', -79.3832))
        self._last_map_zoom = int(self._settings.value('last_map_zoom', 18))

        self.site_data = {
            'width': 100,
            'depth': 100,
            'address': '',
            'boundary': None,
            'elevation_data': None,
            'terrain_mesh': None
        }
        self._map_widget = None  # Will hold the EmbeddedMapWidget
        self._map_boundary = None
        self._lidar_data = None

        self._setup_ui()
        print("[SiteDialog] Initialized")

    def _save_settings(self):
        """Save current settings for next time."""
        if self._last_lidar_folder:
            self._settings.setValue('last_lidar_folder', self._last_lidar_folder)
        self._settings.setValue('last_map_lat', self._last_map_lat)
        self._settings.setValue('last_map_lng', self._last_map_lng)
        self._settings.setValue('last_map_zoom', self._last_map_zoom)
        print(f"[SiteDialog] Settings saved: lat={self._last_map_lat}, lng={self._last_map_lng}")

    def _setup_ui(self):
        """Create simplified UI."""
        layout = QVBoxLayout(self)
        layout.setSpacing(15)

        # Header
        header = QLabel("Select Site Location")
        header.setStyleSheet("font-size: 18px; font-weight: bold; color: #2196F3;")
        layout.addWidget(header)

        desc = QLabel(
            "Use the interactive map to navigate to your site, draw the property boundary, "
            "and import LiDAR elevation data if available."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #666;")
        layout.addWidget(desc)

        # Map Group
        map_group = QGroupBox("Interactive Map")
        map_layout = QVBoxLayout()

        # Map controls
        controls = QHBoxLayout()

        self._open_map_btn = QPushButton("Open Interactive Map")
        self._open_map_btn.setStyleSheet(
            "background-color: #2196F3; color: white; padding: 10px; font-size: 12px;"
        )
        self._open_map_btn.clicked.connect(self._on_open_map)
        controls.addWidget(self._open_map_btn)

        # Add "Use Last Location" button if we have saved settings
        if self._last_map_lat != 43.6532 or self._last_map_lng != -79.3832:
            self._use_last_loc_btn = QPushButton("Use Last Location")
            self._use_last_loc_btn.setStyleSheet(
                "background-color: #FF9800; color: white; padding: 10px; font-size: 12px;"
            )
            self._use_last_loc_btn.setToolTip(f"Lat: {self._last_map_lat:.4f}, Lng: {self._last_map_lng:.4f}")
            self._use_last_loc_btn.clicked.connect(self._on_use_last_location)
            controls.addWidget(self._use_last_loc_btn)

        self._clear_boundary_btn = QPushButton("Clear Boundary")
        self._clear_boundary_btn.clicked.connect(self._on_clear_boundary)
        self._clear_boundary_btn.setEnabled(False)
        controls.addWidget(self._clear_boundary_btn)

        controls.addStretch()

        self._boundary_status = QLabel("No boundary drawn")
        self._boundary_status.setStyleSheet("color: #999; font-style: italic;")
        controls.addWidget(self._boundary_status)

        map_layout.addLayout(controls)

        # Last location info (if available)
        if self._last_map_lat != 43.6532 or self._last_map_lng != -79.3832:
            last_loc_label = QLabel(
                f"Last location: {self._last_map_lat:.4f}, {self._last_map_lng:.4f} "
                f"(LiDAR: {Path(self._last_lidar_folder).name if self._last_lidar_folder else 'None'})"
            )
            last_loc_label.setStyleSheet("color: #666; font-size: 11px; font-style: italic;")
            map_layout.addWidget(last_loc_label)

        # Status
        self._map_status = QLabel(
            "Optional: Click 'Open Interactive Map' to draw site boundary and place building. "
            "If skipped, a default 100' x 100' site with centered building will be used."
        )
        self._map_status.setWordWrap(True)
        self._map_status.setStyleSheet(
            "background: #f5f5f5; padding: 10px; border-radius: 4px; color: #666;"
        )
        map_layout.addWidget(self._map_status)

        map_group.setLayout(map_layout)
        layout.addWidget(map_group)

        # LiDAR Group
        lidar_group = QGroupBox("LiDAR Elevation Data (Optional)")
        lidar_layout = QVBoxLayout()

        lidar_desc = QLabel(
            "Import high-resolution elevation data from LiDAR GeoTIFF files. "
            "This provides accurate terrain modeling for your site."
        )
        lidar_desc.setWordWrap(True)
        lidar_desc.setStyleSheet("color: #666; font-size: 11px;")
        lidar_layout.addWidget(lidar_desc)

        lidar_controls = QHBoxLayout()

        self._import_lidar_btn = QPushButton("Import LiDAR Data")
        self._import_lidar_btn.setStyleSheet(
            "background-color: #4CAF50; color: white; padding: 10px;"
        )
        self._import_lidar_btn.clicked.connect(self._on_import_lidar)
        lidar_controls.addWidget(self._import_lidar_btn)

        self._lidar_status = QLabel("No LiDAR data imported")
        self._lidar_status.setStyleSheet("color: #999; font-style: italic;")
        lidar_controls.addWidget(self._lidar_status)

        lidar_controls.addStretch()

        lidar_layout.addLayout(lidar_controls)

        # Progress bar
        self._progress = QProgressBar()
        self._progress.setVisible(False)
        lidar_layout.addWidget(self._progress)

        lidar_group.setLayout(lidar_layout)
        layout.addWidget(lidar_group)

        # Buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        button_box.accepted.connect(self._on_accept)
        button_box.rejected.connect(self.reject)

        # Customize OK button
        ok_btn = button_box.button(QDialogButtonBox.StandardButton.Ok)
        ok_btn.setText("Continue to Building Design →")
        ok_btn.setStyleSheet("background-color: #4CAF50; color: white; padding: 10px 20px;")
        ok_btn.setEnabled(True)  # Always enabled - will use defaults if no boundary
        self._ok_btn = ok_btn

        layout.addWidget(button_box)

    def _on_use_last_location(self):
        """Quickly open map at last used location without needing to navigate."""
        print("[SiteDialog] Using last location")
        self._on_open_map(use_saved=True)

    def _on_open_map(self, use_saved=False):
        """Open the interactive map."""
        print("[SiteDialog] _on_open_map called")
        try:
            print("[SiteDialog] Importing EmbeddedMapWidget...")
            from widgets.embedded_map_widget import EmbeddedMapWidget
            print("[SiteDialog] EmbeddedMapWidget imported")

            # Close existing map if open
            if self._map_widget is not None:
                print("[SiteDialog] Closing existing map")
                try:
                    self._map_widget.hide()
                    self._map_widget.deleteLater()
                except Exception as e:
                    print(f"[SiteDialog] Error closing old map: {e}")
                self._map_widget = None

            # Use saved location or default to Toronto
            if use_saved:
                lat, lng = self._last_map_lat, self._last_map_lng
                zoom = self._last_map_zoom
                print(f"[SiteDialog] Using saved location: {lat}, {lng}, zoom={zoom}")
            else:
                lat, lng = 43.6532, -79.3832
                zoom = 18
                print(f"[SiteDialog] Using default Toronto location")

            print(f"[SiteDialog] Creating EmbeddedMapWidget...")
            # Create as independent top-level window (no parent) for proper modality
            self._map_widget = EmbeddedMapWidget(lat, lng, zoom, parent=None)
            print(f"[SiteDialog] EmbeddedMapWidget created")

            print("[SiteDialog] Connecting signals...")
            self._map_widget.boundary_changed.connect(self._on_boundary_changed)
            self._map_widget.building_placed.connect(self._on_building_placed)
            self._map_widget.close_requested.connect(self._on_map_close)
            print("[SiteDialog] Signals connected")

            # Set window properties BEFORE showing
            self._map_widget.setWindowTitle("Draw Site Boundary")
            self._map_widget.resize(1200, 800)
            self._map_widget.setMinimumSize(800, 600)

            print("[SiteDialog] Setting window properties...")

            # Store reference to prevent garbage collection
            self._map_widget.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

            print("[SiteDialog] Showing map window...")
            # Use exec to run as modal dialog - ensures it stays open and interactive
            self._map_widget.exec()
            print("[SiteDialog] Map dialog finished")

        except Exception as e:
            print(f"[SiteDialog] ERROR opening map: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Error", f"Could not open map: {e}")

    def _on_map_close(self):
        """Handle map window closing."""
        print("[SiteDialog] Map close requested")
        # Close the map dialog (this will cause exec() to return)
        if self._map_widget:
            self._map_widget.accept()
        self._map_widget = None
        print("[SiteDialog] Map closed")

    def _on_building_placed(self, lat, lng, x_ft, z_ft, rotation_deg):
        """Handle building placement on map."""
        try:
            print(f"[SiteDialog] Building placed at ({x_ft:.1f}', {z_ft:.1f}'), rotation={rotation_deg:.1f}°")
            building_data = {
                'lat': lat,
                'lng': lng,
                'x_ft': x_ft,
                'z_ft': z_ft,
                'rotation_deg': rotation_deg,
                # C++ kernel expects these field names
                'x_mm': x_ft * 304.8,
                'z_mm': z_ft * 304.8,
                'rotation_rad': rotation_deg * 3.14159 / 180.0
            }
            # Store as 'building_origin' to match what application.py expects
            self.site_data['building_origin'] = building_data
            self._map_status.setText(
                f"Site boundary and building placement defined. "
                f"Building at ({x_ft:.0f}', {z_ft:.0f}'), rotated {rotation_deg:.0f}°. "
                f"Click OK to continue."
            )
        except Exception as e:
            print(f"[SiteDialog] Error in _on_building_placed: {e}")
            import traceback
            traceback.print_exc()

    def _on_boundary_changed(self, lat_min, lat_max, lng_min, lng_max, width_ft, depth_ft, vertices, vertices_ft):
        """Handle boundary drawn on map."""
        try:
            print(f"[SiteDialog] Boundary changed: {width_ft:.0f}' x {depth_ft:.0f}'")
            boundary_data = {
                'lat_min': lat_min,
                'lat_max': lat_max,
                'lng_min': lng_min,
                'lng_max': lng_max,
                'width_ft': width_ft,
                'depth_ft': depth_ft,
                'vertices': vertices,
                'vertices_ft': vertices_ft
            }
            self._map_boundary = boundary_data
            self.site_data['boundary'] = boundary_data

            # Update site dimensions
            self.site_data['width'] = width_ft
            self.site_data['depth'] = depth_ft

            # Update status
            self._boundary_status.setText(f"Boundary set: {width_ft:.0f}' × {depth_ft:.0f}'")
            self._boundary_status.setStyleSheet("color: #4CAF50; font-weight: bold;")

            self._map_status.setText(
                f"Site boundary defined: {width_ft:.0f}' × {depth_ft:.0f}'. "
                "You can now import LiDAR data or proceed to building design."
            )
            self._map_status.setStyleSheet(
                "background: #E8F5E9; padding: 10px; border-radius: 4px; color: #2E7D32;"
            )

            self._clear_boundary_btn.setEnabled(True)
            self._ok_btn.setEnabled(True)

            # Save map location for next time
            self._last_map_lat = (lat_min + lat_max) / 2
            self._last_map_lng = (lng_min + lng_max) / 2
        except Exception as e:
            print(f"[SiteDialog] Error in _on_boundary_changed: {e}")
            import traceback
            traceback.print_exc()

    def _on_clear_boundary(self):
        """Clear the boundary."""
        self._map_boundary = None
        self.site_data['boundary'] = None

        self._boundary_status.setText("No boundary drawn")
        self._boundary_status.setStyleSheet("color: #999; font-style: italic;")

        self._map_status.setText(
            "Click 'Open Interactive Map' to select your site location and draw boundaries."
        )
        self._map_status.setStyleSheet(
            "background: #f5f5f5; padding: 10px; border-radius: 4px; color: #666;"
        )

        self._clear_boundary_btn.setEnabled(False)
        self._ok_btn.setEnabled(False)

    def _on_import_lidar(self):
        """Import LiDAR data."""
        # Use last folder if available
        start_dir = self._last_lidar_folder if self._last_lidar_folder and os.path.exists(self._last_lidar_folder) else ""

        folder = QFileDialog.getExistingDirectory(
            self,
            "Select LiDAR Data Folder",
            start_dir,
            QFileDialog.Option.ShowDirsOnly
        )

        if not folder:
            return

        # Save folder for next time
        self._last_lidar_folder = folder

        self._progress.setVisible(True)
        self._progress.setRange(0, 0)  # Indeterminate
        self._lidar_status.setText("Processing LiDAR data...")

        # Process in background
        QTimer.singleShot(100, lambda: self._process_lidar(folder))

    def _process_lidar(self, folder):
        """Process LiDAR files."""
        try:
            if HAS_LIDAR_LIB:
                # Use library
                from tools.lidar import LidarExtractor, PropertyBounds

                extractor = LidarExtractor()

                # Scan folder for tiles
                print(f"[SiteDialog] Scanning {folder} for LiDAR tiles...")
                tile_count = extractor.scan_folder(folder)
                print(f"[SiteDialog] Found {tile_count} tiles")

                if tile_count == 0:
                    self._lidar_status.setText("No GeoTIFF files found in folder")
                    return

                # Create bounds from map boundary or use default
                if self._map_boundary:
                    print(f"[SiteDialog] Using map boundary: lat=[{self._map_boundary['lat_min']:.6f}, {self._map_boundary['lat_max']:.6f}], lng=[{self._map_boundary['lng_min']:.6f}, {self._map_boundary['lng_max']:.6f}]")
                    bounds = PropertyBounds.from_bounds(
                        self._map_boundary['lat_min'],
                        self._map_boundary['lat_max'],
                        self._map_boundary['lng_min'],
                        self._map_boundary['lng_max']
                    )
                else:
                    # Default 100x100m bounds
                    print("[SiteDialog] No map boundary, using default Toronto bounds")
                    bounds = PropertyBounds(lat=43.6532, lng=-79.3832, width_m=100, height_m=100)

                print(f"[SiteDialog] Searching for tiles in bounds: lat=[{bounds.lat_min:.6f}, {bounds.lat_max:.6f}], lng=[{bounds.lng_min:.6f}, {bounds.lng_max:.6f}]")

                # Find overlapping tiles
                tiles = extractor.find_overlapping_tiles(bounds)
                print(f"[SiteDialog] Found {len(tiles)} overlapping tiles")

                # Debug: show first few scanned tiles
                if extractor.tiles:
                    print(f"[SiteDialog] First 3 scanned tiles:")
                    for i, tile in enumerate(extractor.tiles[:3]):
                        print(f"  Tile {i}: {tile.name}")
                        print(f"    WGS84 lat=[{tile.lat_min:.6f}, {tile.lat_max:.6f}], lng=[{tile.lng_min:.6f}, {tile.lng_max:.6f}]")
                        print(f"    Native bounds: left={tile.bounds_native[0]:.1f}, bottom={tile.bounds_native[1]:.1f}, right={tile.bounds_native[2]:.1f}, top={tile.bounds_native[3]:.1f}")

                if not tiles and extractor.tiles:
                    print("[SiteDialog] No overlapping tiles found. Checking for coordinate issues...")
                    # Try to find the closest tile
                    closest_dist = float('inf')
                    closest_tile = None
                    for tile in extractor.tiles:
                        # Calculate distance from tile center to bounds center
                        tile_lat_c = (tile.lat_min + tile.lat_max) / 2
                        tile_lng_c = (tile.lng_min + tile.lng_max) / 2
                        bounds_lat_c = (bounds.lat_min + bounds.lat_max) / 2
                        bounds_lng_c = (bounds.lng_min + bounds.lng_max) / 2
                        dist = ((tile_lat_c - bounds_lat_c)**2 + (tile_lng_c - bounds_lng_c)**2)**0.5
                        if dist < closest_dist:
                            closest_dist = dist
                            closest_tile = tile
                    if closest_tile:
                        print(f"[SiteDialog] Closest tile: {closest_tile.name} at distance {closest_dist:.6f} degrees")
                        print(f"  Tile center: lat={((closest_tile.lat_min + closest_tile.lat_max)/2):.6f}, lng={((closest_tile.lng_min + closest_tile.lng_max)/2):.6f}")
                        print(f"  Bounds center: lat={((bounds.lat_min + bounds.lat_max)/2):.6f}, lng={((bounds.lng_min + bounds.lng_max)/2):.6f}")

                if not tiles:
                    self._lidar_status.setText("No LiDAR tiles overlap with site boundary")
                    return

                # Extract elevation data
                self._lidar_status.setText(f"Extracting from {len(tiles)} tiles...")
                data = extractor.extract_elevation(tiles, bounds)

                if data and data.points:
                    self._lidar_data = data
                    self.site_data['elevation_data'] = {
                        'min_elevation': data.min_elevation_m,
                        'max_elevation': data.max_elevation_m,
                        'point_count': len(data.points)
                    }
                    self.site_data['terrain_generation_settings'] = {
                        'source': 'lidar',
                        'folder': folder,
                        'point_count': len(data.points),
                        'use_cpp_generation': True  # Use fast C++ terrain generation
                    }

                    # Convert LiDAR data to elevation_grid format for terrain generator
                    elevation_grid = {}
                    for key, pt in data.points.items():
                        elevation_grid[key] = {
                            'lat': pt.lat,
                            'lng': pt.lng,
                            'elevation_ft': pt.elevation_ft
                        }

                    # Convert vertices from feet to mm for terrain generator
                    vertices_ft = self._map_boundary.get('vertices_ft', []) if self._map_boundary else []
                    vertices_mm = [[v[0] * 304.8, v[1] * 304.8] for v in vertices_ft] if vertices_ft else []

                    # Calculate property dimensions
                    if vertices_ft:
                        xs = [v[0] for v in vertices_ft]
                        zs = [v[1] for v in vertices_ft]
                        width_ft = max(xs) - min(xs)
                        depth_ft = max(zs) - min(zs)
                    else:
                        width_ft = bounds.width_m * 3.28084
                        depth_ft = bounds.height_m * 3.28084

                    self.site_data['property_width_ft'] = width_ft
                    self.site_data['property_depth_ft'] = depth_ft

                    self.site_data['google_maps'] = {
                        'elevation_grid': elevation_grid,
                        'boundary': {
                            'lat_min': bounds.lat_min,
                            'lat_max': bounds.lat_max,
                            'lng_min': bounds.lng_min,
                            'lng_max': bounds.lng_max,
                            'vertices_ft': vertices_ft,
                            'vertices_mm': vertices_mm
                        }
                    }

                    # Skip Python terrain generation - use fast C++ generation in viewport instead
                    # This avoids the slow Python mesh generation (50-100x slower than C++)
                    print(f"[SiteDialog] Using C++ terrain generation for {len(data.points):,} points")

                    self._lidar_status.setText(
                        f"LiDAR loaded: {len(data.points):,} points, "
                        f"elev: {data.min_elevation_m:.1f}-{data.max_elevation_m:.1f}m"
                    )
                    self._lidar_status.setStyleSheet("color: #4CAF50; font-weight: bold;")
                else:
                    self._lidar_status.setText("No elevation data extracted")
            else:
                # Fallback - just note that folder was selected
                self._lidar_data = {'folder': folder}
                self.site_data['elevation_data'] = {'folder': folder}
                self._lidar_status.setText(f"LiDAR folder: {Path(folder).name}")

        except Exception as e:
            print(f"[SiteDialog] LiDAR error: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.warning(self, "LiDAR Import", f"Could not import LiDAR: {e}")
            self._lidar_status.setText("LiDAR import failed")

        finally:
            self._progress.setVisible(False)

    def _on_accept(self):
        """Validate and accept."""
        # If no boundary drawn, use default site dimensions
        if not self._map_boundary:
            print("[SiteDialog] No boundary drawn, using default site")
            self.site_data['width'] = 100
            self.site_data['depth'] = 100
            self.site_data['boundary'] = {
                'width_ft': 100,
                'depth_ft': 100,
                'vertices': [],
                'vertices_ft': []
            }

        # If no building placed, use center of site
        if 'building_origin' not in self.site_data:
            print("[SiteDialog] No building placed, using center placement")
            width = self.site_data.get('width', 100)
            depth = self.site_data.get('depth', 100)
            self.site_data['building_origin'] = {
                'x_ft': width / 2,
                'z_ft': depth / 2,
                'rotation_deg': 0,
                'x_mm': (width / 2) * 304.8,
                'z_mm': (depth / 2) * 304.8,
                'rotation_rad': 0
            }

        print(f"[SiteDialog] Accepting with site_data: {self.site_data}")

        # Save settings for next time
        self._save_settings()

        self.accept()

    def get_site_data(self):
        """Return the collected site data."""
        return self.site_data


def show_site_dialog(parent=None):
    """Show the simplified site dialog and return site data."""
    dialog = SimpleSiteDialog(parent)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        return dialog.get_site_data()
    return None


if __name__ == "__main__":
    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    dialog = SimpleSiteDialog()

    if dialog.exec() == QDialog.DialogCode.Accepted:
        data = dialog.get_site_data()
        print("Site data:")
        print(json.dumps(data, indent=2, default=str))
    else:
        print("Cancelled")
