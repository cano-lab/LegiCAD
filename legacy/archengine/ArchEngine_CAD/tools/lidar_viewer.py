#!/usr/bin/env python
"""
LiDAR Tile Viewer
=================
Visualize GeoTIFF LiDAR tiles and property boundaries to verify coordinate alignment.

Usage:
    python lidar_viewer.py
    python lidar_viewer.py /path/to/lidar/folder
"""

import sys
import os

# Add parent for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QListWidget, QListWidgetItem,
    QSplitter, QGroupBox, QLineEdit, QFormLayout, QMessageBox,
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QGraphicsEllipseItem,
    QGraphicsRectItem, QGraphicsPolygonItem
)
from PyQt6.QtCore import Qt, QRectF, QPointF
from PyQt6.QtGui import QPixmap, QImage, QPen, QBrush, QColor, QPolygonF, QPainter

import numpy as np

try:
    import rasterio
    from pyproj import Transformer
    HAS_RASTERIO = True
except ImportError:
    HAS_RASTERIO = False
    print("WARNING: rasterio not installed. pip install rasterio pyproj")


class LidarViewer(QMainWindow):
    def __init__(self, initial_folder=None):
        super().__init__()
        self.setWindowTitle("LiDAR Tile Viewer")
        self.setMinimumSize(1200, 800)

        self.tiles = []  # List of tile info dicts
        self.current_tile = None
        self.property_lat = 46.2616  # Default - Lake Nipissing area
        self.property_lng = -80.4547

        self._setup_ui()

        if initial_folder and os.path.isdir(initial_folder):
            self._load_folder(initial_folder)

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        layout = QHBoxLayout(central)

        # Left panel - tile list and controls
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_panel.setMaximumWidth(400)

        # Folder selection
        folder_group = QGroupBox("LiDAR Folder")
        folder_layout = QVBoxLayout(folder_group)

        folder_btn = QPushButton("Select Folder...")
        folder_btn.clicked.connect(self._select_folder)
        folder_layout.addWidget(folder_btn)

        self.folder_label = QLabel("No folder selected")
        self.folder_label.setWordWrap(True)
        folder_layout.addWidget(self.folder_label)

        left_layout.addWidget(folder_group)

        # Property coordinates
        coord_group = QGroupBox("Property Coordinates (WGS84)")
        coord_layout = QFormLayout(coord_group)

        self.lat_input = QLineEdit(str(self.property_lat))
        self.lng_input = QLineEdit(str(self.property_lng))
        coord_layout.addRow("Latitude:", self.lat_input)
        coord_layout.addRow("Longitude:", self.lng_input)

        update_btn = QPushButton("Update Property Location")
        update_btn.clicked.connect(self._update_property_location)
        coord_layout.addRow(update_btn)

        left_layout.addWidget(coord_group)

        # Tile list
        tiles_group = QGroupBox("Available Tiles")
        tiles_layout = QVBoxLayout(tiles_group)

        self.tile_list = QListWidget()
        self.tile_list.currentRowChanged.connect(self._on_tile_selected)
        tiles_layout.addWidget(self.tile_list)

        self.tile_info_label = QLabel("")
        self.tile_info_label.setWordWrap(True)
        tiles_layout.addWidget(self.tile_info_label)

        left_layout.addWidget(tiles_group)

        layout.addWidget(left_panel)

        # Right panel - visualization
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)

        # Graphics view for tile visualization
        self.scene = QGraphicsScene()
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.view.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        right_layout.addWidget(self.view)

        # Zoom controls
        zoom_layout = QHBoxLayout()
        zoom_in_btn = QPushButton("Zoom In")
        zoom_in_btn.clicked.connect(lambda: self.view.scale(1.2, 1.2))
        zoom_out_btn = QPushButton("Zoom Out")
        zoom_out_btn.clicked.connect(lambda: self.view.scale(0.8, 0.8))
        fit_btn = QPushButton("Fit View")
        fit_btn.clicked.connect(self._fit_view)
        zoom_layout.addWidget(zoom_in_btn)
        zoom_layout.addWidget(zoom_out_btn)
        zoom_layout.addWidget(fit_btn)
        right_layout.addLayout(zoom_layout)

        # Status
        self.status_label = QLabel("Load a LiDAR folder to begin")
        self.status_label.setStyleSheet("font-weight: bold; padding: 5px;")
        right_layout.addWidget(self.status_label)

        layout.addWidget(right_panel, stretch=1)

    def _select_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select LiDAR GeoTIFF Folder")
        if folder:
            self._load_folder(folder)

    def _load_folder(self, folder):
        if not HAS_RASTERIO:
            QMessageBox.warning(self, "Missing Library",
                "rasterio is required. Install with: pip install rasterio pyproj")
            return

        self.folder_label.setText(folder)
        self.tiles = []
        self.tile_list.clear()
        self.scene.clear()

        # Find all TIFF files
        tiff_files = []
        for root, dirs, files in os.walk(folder):
            for f in files:
                if f.lower().endswith(('.tif', '.tiff')):
                    tiff_files.append(os.path.join(root, f))

        if not tiff_files:
            self.status_label.setText("No GeoTIFF files found in folder")
            return

        print(f"[LidarViewer] Found {len(tiff_files)} TIFF files")
        self.status_label.setText(f"Loading {len(tiff_files)} tiles...")
        QApplication.processEvents()

        # Load tile info
        for tiff_path in tiff_files:
            try:
                with rasterio.open(tiff_path) as src:
                    bounds = src.bounds
                    crs = src.crs

                    # Transform to lat/lng
                    transformer = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
                    lng_min, lat_min = transformer.transform(bounds.left, bounds.bottom)
                    lng_max, lat_max = transformer.transform(bounds.right, bounds.top)

                    tile_info = {
                        'path': tiff_path,
                        'name': os.path.basename(tiff_path),
                        'crs': str(crs),
                        'resolution': src.res[0],
                        'width': src.width,
                        'height': src.height,
                        'bounds_native': bounds,
                        'lat_min': lat_min,
                        'lat_max': lat_max,
                        'lng_min': lng_min,
                        'lng_max': lng_max,
                    }
                    self.tiles.append(tile_info)
                    print(f"[LidarViewer] Loaded: {os.path.basename(tiff_path)} - lat: {lat_min:.5f} to {lat_max:.5f}, lng: {lng_min:.5f} to {lng_max:.5f}")

                    # Check if contains property
                    contains = (lat_min <= self.property_lat <= lat_max and
                               lng_min <= self.property_lng <= lng_max)

                    prefix = "✓ " if contains else "  "
                    item = QListWidgetItem(f"{prefix}{tile_info['name']}")
                    if contains:
                        item.setBackground(QColor(144, 238, 144))  # Light green
                    self.tile_list.addItem(item)

            except Exception as e:
                print(f"[LidarViewer] Error loading {os.path.basename(tiff_path)}: {e}")
                import traceback
                traceback.print_exc()

        self.status_label.setText(f"Loaded {len(self.tiles)} tiles")

        # Show overview of all tiles
        self._show_overview()

    def _show_overview(self):
        """Show overview map of all tiles with property marker."""
        self.scene.clear()

        if not self.tiles:
            return

        # Find overall bounds
        all_lat_min = min(t['lat_min'] for t in self.tiles)
        all_lat_max = max(t['lat_max'] for t in self.tiles)
        all_lng_min = min(t['lng_min'] for t in self.tiles)
        all_lng_max = max(t['lng_max'] for t in self.tiles)

        # Scale factor (pixels per degree)
        scale = 50000  # Adjust for reasonable display

        # Draw each tile as a rectangle
        for i, tile in enumerate(self.tiles):
            x = (tile['lng_min'] - all_lng_min) * scale
            y = (all_lat_max - tile['lat_max']) * scale  # Flip Y
            w = (tile['lng_max'] - tile['lng_min']) * scale
            h = (tile['lat_max'] - tile['lat_min']) * scale

            # Check if contains property
            contains = (tile['lat_min'] <= self.property_lat <= tile['lat_max'] and
                       tile['lng_min'] <= self.property_lng <= tile['lng_max'])

            rect = QGraphicsRectItem(x, y, w, h)
            if contains:
                rect.setBrush(QBrush(QColor(144, 238, 144, 150)))  # Light green
                rect.setPen(QPen(QColor(0, 128, 0), 2))
            else:
                rect.setBrush(QBrush(QColor(200, 200, 200, 100)))
                rect.setPen(QPen(QColor(100, 100, 100), 1))
            rect.setToolTip(f"{tile['name']}\n{tile['lat_min']:.5f} to {tile['lat_max']:.5f}\n{tile['lng_min']:.5f} to {tile['lng_max']:.5f}")
            self.scene.addItem(rect)

        # Draw property marker
        prop_x = (self.property_lng - all_lng_min) * scale
        prop_y = (all_lat_max - self.property_lat) * scale

        # Red cross for property
        marker_size = 15
        pen = QPen(QColor(255, 0, 0), 3)
        self.scene.addLine(prop_x - marker_size, prop_y, prop_x + marker_size, prop_y, pen)
        self.scene.addLine(prop_x, prop_y - marker_size, prop_x, prop_y + marker_size, pen)

        # Red circle
        circle = QGraphicsEllipseItem(prop_x - marker_size, prop_y - marker_size,
                                       marker_size * 2, marker_size * 2)
        circle.setPen(QPen(QColor(255, 0, 0), 2))
        circle.setBrush(QBrush(QColor(255, 0, 0, 50)))
        self.scene.addItem(circle)

        # Add coordinate labels
        coord_text = self.scene.addText(f"Property: ({self.property_lat:.5f}, {self.property_lng:.5f})")
        coord_text.setPos(prop_x + 20, prop_y - 30)
        coord_text.setDefaultTextColor(QColor(255, 0, 0))

        self._fit_view()

        # Update status
        matching = [t for t in self.tiles if
                   t['lat_min'] <= self.property_lat <= t['lat_max'] and
                   t['lng_min'] <= self.property_lng <= t['lng_max']]
        if matching:
            self.status_label.setText(f"✓ Property found in {len(matching)} tile(s): {', '.join(t['name'] for t in matching)}")
            self.status_label.setStyleSheet("color: green; font-weight: bold; padding: 5px;")
        else:
            self.status_label.setText(f"⚠ Property NOT in any tile! Check coordinates or download correct tile.")
            self.status_label.setStyleSheet("color: red; font-weight: bold; padding: 5px;")

    def _on_tile_selected(self, row):
        if row < 0 or row >= len(self.tiles):
            return

        tile = self.tiles[row]
        self.current_tile = tile

        # Show tile info
        info = (f"<b>{tile['name']}</b><br>"
                f"CRS: {tile['crs']}<br>"
                f"Resolution: {tile['resolution']:.2f}m<br>"
                f"Size: {tile['width']}x{tile['height']}<br>"
                f"<br><b>Bounds (Lat/Lng):</b><br>"
                f"Lat: {tile['lat_min']:.6f} to {tile['lat_max']:.6f}<br>"
                f"Lng: {tile['lng_min']:.6f} to {tile['lng_max']:.6f}<br>"
                f"<br><b>Native bounds:</b><br>"
                f"X: {tile['bounds_native'].left:.0f} to {tile['bounds_native'].right:.0f}<br>"
                f"Y: {tile['bounds_native'].bottom:.0f} to {tile['bounds_native'].top:.0f}")

        # Check if contains property
        contains = (tile['lat_min'] <= self.property_lat <= tile['lat_max'] and
                   tile['lng_min'] <= self.property_lng <= tile['lng_max'])
        if contains:
            info += "<br><br><span style='color: green;'><b>✓ Contains your property!</b></span>"
        else:
            info += "<br><br><span style='color: red;'><b>✗ Does NOT contain your property</b></span>"

        self.tile_info_label.setText(info)

        # Load and display tile elevation data
        self._display_tile(tile)

    def _display_tile(self, tile):
        """Display elevation data for selected tile."""
        self.scene.clear()

        try:
            with rasterio.open(tile['path']) as src:
                # Read elevation data
                elevation = src.read(1)
                nodata = src.nodata

                # Normalize to 0-255 for display
                if nodata is not None:
                    valid_mask = elevation != nodata
                    valid_data = elevation[valid_mask]
                else:
                    valid_data = elevation.flatten()

                if len(valid_data) == 0:
                    self.status_label.setText("No valid elevation data in tile")
                    return

                min_elev = valid_data.min()
                max_elev = valid_data.max()

                # Downsample for display if large
                display_max = 1000
                step = max(1, max(elevation.shape) // display_max)
                display_data = elevation[::step, ::step]

                # Normalize
                if max_elev > min_elev:
                    normalized = ((display_data - min_elev) / (max_elev - min_elev) * 255).astype(np.uint8)
                else:
                    normalized = np.zeros_like(display_data, dtype=np.uint8)

                # Handle nodata
                if nodata is not None:
                    normalized[display_data == nodata] = 0

                # Create QImage
                h, w = normalized.shape
                image = QImage(normalized.data, w, h, w, QImage.Format.Format_Grayscale8)
                pixmap = QPixmap.fromImage(image)

                # Add to scene
                pixmap_item = QGraphicsPixmapItem(pixmap)
                self.scene.addItem(pixmap_item)

                # Calculate property position in pixel coordinates
                lng_range = tile['lng_max'] - tile['lng_min']
                lat_range = tile['lat_max'] - tile['lat_min']

                if lng_range > 0 and lat_range > 0:
                    prop_x = (self.property_lng - tile['lng_min']) / lng_range * w
                    prop_y = (tile['lat_max'] - self.property_lat) / lat_range * h  # Flip Y

                    # Draw property marker
                    marker_size = max(5, min(w, h) // 50)
                    pen = QPen(QColor(255, 0, 0), 2)
                    self.scene.addLine(prop_x - marker_size, prop_y, prop_x + marker_size, prop_y, pen)
                    self.scene.addLine(prop_x, prop_y - marker_size, prop_x, prop_y + marker_size, pen)

                    circle = QGraphicsEllipseItem(prop_x - marker_size, prop_y - marker_size,
                                                   marker_size * 2, marker_size * 2)
                    circle.setPen(QPen(QColor(255, 0, 0), 2))
                    self.scene.addItem(circle)

                self._fit_view()

                self.status_label.setText(f"Elevation: {min_elev:.1f}m to {max_elev:.1f}m (range: {max_elev-min_elev:.1f}m)")

        except Exception as e:
            self.status_label.setText(f"Error loading tile: {e}")
            import traceback
            traceback.print_exc()

    def _update_property_location(self):
        try:
            self.property_lat = float(self.lat_input.text())
            self.property_lng = float(self.lng_input.text())

            # Refresh display
            if self.tiles:
                # Update tile list highlighting
                for i, tile in enumerate(self.tiles):
                    contains = (tile['lat_min'] <= self.property_lat <= tile['lat_max'] and
                               tile['lng_min'] <= self.property_lng <= tile['lng_max'])
                    item = self.tile_list.item(i)
                    prefix = "✓ " if contains else "  "
                    item.setText(f"{prefix}{tile['name']}")
                    if contains:
                        item.setBackground(QColor(144, 238, 144))
                    else:
                        item.setBackground(QColor(255, 255, 255))

                self._show_overview()

        except ValueError:
            QMessageBox.warning(self, "Invalid Input", "Please enter valid latitude and longitude values.")

    def _fit_view(self):
        self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)


def main():
    app = QApplication(sys.argv)

    # Check for folder argument
    initial_folder = None
    if len(sys.argv) > 1:
        initial_folder = sys.argv[1]

    viewer = LidarViewer(initial_folder)
    viewer.show()

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
