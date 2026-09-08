#!/usr/bin/env python
"""
LiDAR Topography Extractor
==========================
Standalone tool for extracting elevation data from Ontario LiDAR GeoTIFF tiles.

Features:
- Visual tile browser with property overlay
- Multi-tile merging for properties on tile edges
- Export to multiple formats (Revit, ArchEngine, OBJ, CSV)

Usage:
    python lidar_extractor.py
    python lidar_extractor.py /path/to/lidar/folder
"""

import sys
import os
import json
import math
import re

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QListWidget, QListWidgetItem,
    QGroupBox, QLineEdit, QFormLayout, QMessageBox, QProgressBar,
    QGraphicsView, QGraphicsScene, QGraphicsEllipseItem,
    QGraphicsRectItem, QComboBox, QSpinBox, QDoubleSpinBox,
    QTabWidget, QTextEdit, QSplitter
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QPen, QBrush, QColor, QPainter

import numpy as np

try:
    import rasterio
    from pyproj import Transformer
    HAS_RASTERIO = True
except ImportError:
    HAS_RASTERIO = False
    print("WARNING: rasterio not installed. Run: pip install rasterio pyproj")


class TileLoaderThread(QThread):
    """Background thread for loading tile metadata."""
    progress = pyqtSignal(int, int, str)  # current, total, message
    tile_loaded = pyqtSignal(dict)  # tile info
    finished_loading = pyqtSignal(int)  # total count

    def __init__(self, tiff_files):
        super().__init__()
        self.tiff_files = tiff_files
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        total = len(self.tiff_files)
        loaded = 0

        for i, tiff_path in enumerate(self.tiff_files):
            if self._stop:
                break

            self.progress.emit(i + 1, total, os.path.basename(tiff_path))

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
                        'bounds_native': {
                            'left': bounds.left,
                            'right': bounds.right,
                            'bottom': bounds.bottom,
                            'top': bounds.top
                        },
                        'lat_min': lat_min,
                        'lat_max': lat_max,
                        'lng_min': lng_min,
                        'lng_max': lng_max,
                    }
                    self.tile_loaded.emit(tile_info)
                    loaded += 1

            except Exception as e:
                print(f"Error loading {os.path.basename(tiff_path)}: {e}")

        self.finished_loading.emit(loaded)


class ElevationExtractorThread(QThread):
    """Background thread for extracting elevation data."""
    progress = pyqtSignal(int, int, str)
    finished_extraction = pyqtSignal(dict)  # elevation data
    error = pyqtSignal(str)

    def __init__(self, tile_paths, bounds_latlon, max_points=150000):
        super().__init__()
        self.tile_paths = tile_paths
        self.bounds = bounds_latlon  # (lat_min, lat_max, lng_min, lng_max)
        self.max_points = max_points

    def run(self):
        lat_min, lat_max, lng_min, lng_max = self.bounds
        merged_data = {}
        min_elev = float('inf')
        max_elev = float('-inf')
        resolution = None

        for i, tiff_path in enumerate(self.tile_paths):
            self.progress.emit(i + 1, len(self.tile_paths), f"Processing {os.path.basename(tiff_path)}")

            try:
                with rasterio.open(tiff_path) as src:
                    raster_crs = src.crs
                    resolution = src.res[0]

                    # Transform bounds to raster CRS
                    to_raster = Transformer.from_crs("EPSG:4326", raster_crs, always_xy=True)
                    from_raster = Transformer.from_crs(raster_crs, "EPSG:4326", always_xy=True)

                    raster_min_x, raster_min_y = to_raster.transform(lng_min, lat_min)
                    raster_max_x, raster_max_y = to_raster.transform(lng_max, lat_max)

                    # Add buffer
                    buffer = 5
                    raster_min_x -= buffer
                    raster_max_x += buffer
                    raster_min_y -= buffer
                    raster_max_y += buffer

                    # Clamp to tile bounds
                    tile_bounds = src.bounds
                    extract_min_x = max(raster_min_x, tile_bounds.left)
                    extract_max_x = min(raster_max_x, tile_bounds.right)
                    extract_min_y = max(raster_min_y, tile_bounds.bottom)
                    extract_max_y = min(raster_max_y, tile_bounds.top)

                    if extract_max_x <= extract_min_x or extract_max_y <= extract_min_y:
                        continue

                    # Get pixel coordinates
                    row_start, col_start = src.index(extract_min_x, extract_max_y)
                    row_end, col_end = src.index(extract_max_x, extract_min_y)

                    row_start = max(0, min(row_start, src.height - 1))
                    row_end = max(0, min(row_end + 1, src.height))
                    col_start = max(0, min(col_start, src.width - 1))
                    col_end = max(0, min(col_end + 1, src.width))

                    if row_end <= row_start or col_end <= col_start:
                        continue

                    # Read data
                    elevation = src.read(1)
                    window_data = elevation[row_start:row_end, col_start:col_end]
                    nodata = src.nodata

                    # Subsample if needed
                    tile_total = window_data.shape[0] * window_data.shape[1]
                    max_per_tile = self.max_points // max(1, len(self.tile_paths))
                    step = max(1, int(math.sqrt(tile_total / max_per_tile)))

                    for row_idx in range(0, window_data.shape[0], step):
                        for col_idx in range(0, window_data.shape[1], step):
                            elev = float(window_data[row_idx, col_idx])
                            if nodata is not None and elev == nodata:
                                continue

                            px = extract_min_x + (col_idx + 0.5) * resolution
                            py = extract_max_y - (row_idx + 0.5) * resolution
                            plng, plat = from_raster.transform(px, py)

                            if lat_min <= plat <= lat_max and lng_min <= plng <= lng_max:
                                key = f"{plat:.7f},{plng:.7f}"
                                merged_data[key] = {
                                    "lat": plat,
                                    "lng": plng,
                                    "elevation_m": elev,
                                    "elevation_ft": elev * 3.28084
                                }
                                min_elev = min(min_elev, elev)
                                max_elev = max(max_elev, elev)

            except Exception as e:
                print(f"Error processing {tiff_path}: {e}")
                import traceback
                traceback.print_exc()

        if not merged_data:
            self.error.emit("No elevation data found in the specified area.")
            return

        result = {
            'points': merged_data,
            'count': len(merged_data),
            'min_elevation_m': min_elev,
            'max_elevation_m': max_elev,
            'resolution_m': resolution,
            'bounds': self.bounds
        }
        self.finished_extraction.emit(result)


class LidarExtractor(QMainWindow):
    def __init__(self, initial_folder=None):
        super().__init__()
        self.setWindowTitle("LiDAR Topography Extractor")
        self.setMinimumSize(1400, 900)

        self.tiles = []
        self.elevation_data = None
        self.loader_thread = None

        # Default property location (Lake Nipissing area)
        self.property_bounds = {
            'lat_min': 46.260,
            'lat_max': 46.263,
            'lng_min': -80.456,
            'lng_max': -80.453
        }

        self._setup_ui()

        if initial_folder and os.path.isdir(initial_folder):
            self._load_folder(initial_folder)

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)

        # Left panel
        left_panel = QWidget()
        left_panel.setMaximumWidth(450)
        left_layout = QVBoxLayout(left_panel)

        # Folder selection
        folder_group = QGroupBox("1. Select LiDAR Folder")
        folder_layout = QVBoxLayout(folder_group)
        folder_btn = QPushButton("Browse for GeoTIFF Folder...")
        folder_btn.clicked.connect(self._select_folder)
        folder_layout.addWidget(folder_btn)
        self.folder_label = QLabel("No folder selected")
        self.folder_label.setWordWrap(True)
        folder_layout.addWidget(self.folder_label)
        self.load_progress = QProgressBar()
        self.load_progress.setVisible(False)
        folder_layout.addWidget(self.load_progress)
        self.tile_count_label = QLabel("")
        folder_layout.addWidget(self.tile_count_label)
        left_layout.addWidget(folder_group)

        # Download from Ontario GeoHub
        download_group = QGroupBox("Or Download from Ontario GeoHub")
        download_layout = QVBoxLayout(download_group)

        download_info = QLabel(
            "Download LiDAR data directly from Ontario's open data portal.\n"
            "Enter coordinates and select data type."
        )
        download_info.setWordWrap(True)
        download_info.setStyleSheet("color: #666; font-size: 11px;")
        download_layout.addWidget(download_info)

        coord_layout = QFormLayout()
        self.dl_lat_input = QDoubleSpinBox()
        self.dl_lat_input.setRange(41, 57)  # Ontario latitude range
        self.dl_lat_input.setDecimals(6)
        self.dl_lat_input.setValue(46.2615)
        coord_layout.addRow("Latitude:", self.dl_lat_input)

        self.dl_lng_input = QDoubleSpinBox()
        self.dl_lng_input.setRange(-96, -74)  # Ontario longitude range
        self.dl_lng_input.setDecimals(6)
        self.dl_lng_input.setValue(-80.4548)
        coord_layout.addRow("Longitude:", self.dl_lng_input)
        download_layout.addLayout(coord_layout)

        self.dl_type_combo = QComboBox()
        self.dl_type_combo.addItems(["DTM (bare ground)", "DSM (with trees/buildings)", "Both"])
        download_layout.addWidget(self.dl_type_combo)

        self.download_btn = QPushButton("Download LiDAR Data")
        self.download_btn.setStyleSheet("background-color: #4CAF50; color: white; padding: 8px;")
        self.download_btn.clicked.connect(self._on_download)
        download_layout.addWidget(self.download_btn)

        self.download_status = QLabel("")
        self.download_status.setWordWrap(True)
        download_layout.addWidget(self.download_status)

        self.download_progress = QProgressBar()
        self.download_progress.setVisible(False)
        download_layout.addWidget(self.download_progress)

        left_layout.addWidget(download_group)

        # Property bounds
        bounds_group = QGroupBox("2. Define Property Bounds (WGS84)")
        bounds_layout = QFormLayout(bounds_group)

        self.lat_min_input = QDoubleSpinBox()
        self.lat_min_input.setRange(-90, 90)
        self.lat_min_input.setDecimals(6)
        self.lat_min_input.setValue(self.property_bounds['lat_min'])
        bounds_layout.addRow("Lat Min:", self.lat_min_input)

        self.lat_max_input = QDoubleSpinBox()
        self.lat_max_input.setRange(-90, 90)
        self.lat_max_input.setDecimals(6)
        self.lat_max_input.setValue(self.property_bounds['lat_max'])
        bounds_layout.addRow("Lat Max:", self.lat_max_input)

        self.lng_min_input = QDoubleSpinBox()
        self.lng_min_input.setRange(-180, 180)
        self.lng_min_input.setDecimals(6)
        self.lng_min_input.setValue(self.property_bounds['lng_min'])
        bounds_layout.addRow("Lng Min:", self.lng_min_input)

        self.lng_max_input = QDoubleSpinBox()
        self.lng_max_input.setRange(-180, 180)
        self.lng_max_input.setDecimals(6)
        self.lng_max_input.setValue(self.property_bounds['lng_max'])
        bounds_layout.addRow("Lng Max:", self.lng_max_input)

        update_btn = QPushButton("Update View")
        update_btn.clicked.connect(self._update_property_bounds)
        bounds_layout.addRow(update_btn)

        left_layout.addWidget(bounds_group)

        # Overlapping tiles
        tiles_group = QGroupBox("3. Overlapping Tiles")
        tiles_layout = QVBoxLayout(tiles_group)
        self.overlap_list = QListWidget()
        self.overlap_list.setMaximumHeight(150)
        tiles_layout.addWidget(self.overlap_list)
        left_layout.addWidget(tiles_group)

        # Extract
        extract_group = QGroupBox("4. Extract Elevation")
        extract_layout = QVBoxLayout(extract_group)

        self.max_points_input = QSpinBox()
        self.max_points_input.setRange(1000, 500000)
        self.max_points_input.setValue(150000)
        self.max_points_input.setSingleStep(10000)
        extract_layout.addWidget(QLabel("Max points:"))
        extract_layout.addWidget(self.max_points_input)

        self.extract_btn = QPushButton("Extract Elevation Data")
        self.extract_btn.clicked.connect(self._extract_elevation)
        self.extract_btn.setEnabled(False)
        extract_layout.addWidget(self.extract_btn)

        self.extract_progress = QProgressBar()
        self.extract_progress.setVisible(False)
        extract_layout.addWidget(self.extract_progress)

        self.extract_status = QLabel("")
        self.extract_status.setWordWrap(True)
        extract_layout.addWidget(self.extract_status)

        left_layout.addWidget(extract_group)

        # Export
        export_group = QGroupBox("5. Export")
        export_layout = QVBoxLayout(export_group)

        self.export_format = QComboBox()
        self.export_format.addItems([
            "Revit Points (X Y Z in feet)",
            "Revit CSV (X,Y,Z in feet)",
            "Revit CSV (X,Y,Z in meters)",
            "ArchEngine JSON (terrain mesh)",
            "OBJ Mesh",
            "Raw JSON (elevation grid)"
        ])
        export_layout.addWidget(self.export_format)

        self.export_btn = QPushButton("Export...")
        self.export_btn.clicked.connect(self._export_data)
        self.export_btn.setEnabled(False)
        export_layout.addWidget(self.export_btn)

        left_layout.addWidget(export_group)
        left_layout.addStretch()

        layout.addWidget(left_panel)

        # Right panel - visualization
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)

        self.scene = QGraphicsScene()
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.view.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        right_layout.addWidget(self.view)

        # Zoom controls
        zoom_layout = QHBoxLayout()
        zoom_in = QPushButton("Zoom In")
        zoom_in.clicked.connect(lambda: self.view.scale(1.2, 1.2))
        zoom_out = QPushButton("Zoom Out")
        zoom_out.clicked.connect(lambda: self.view.scale(0.8, 0.8))
        fit_btn = QPushButton("Fit View")
        fit_btn.clicked.connect(self._fit_view)
        zoom_layout.addWidget(zoom_in)
        zoom_layout.addWidget(zoom_out)
        zoom_layout.addWidget(fit_btn)
        right_layout.addLayout(zoom_layout)

        layout.addWidget(right_panel, stretch=1)

    def _on_download(self):
        """Download LiDAR data from Ontario GeoHub."""
        try:
            from lidar.downloader import LidarDownloader, find_available_regions
        except ImportError:
            try:
                # Try relative import
                import sys
                sys.path.insert(0, os.path.dirname(__file__))
                from lidar.downloader import LidarDownloader, find_available_regions
            except ImportError:
                QMessageBox.warning(self, "Import Error",
                    "Could not import downloader module.\n"
                    "Make sure the lidar library is installed.")
                return

        lat = self.dl_lat_input.value()
        lng = self.dl_lng_input.value()

        # Determine data types
        type_idx = self.dl_type_combo.currentIndex()
        if type_idx == 0:
            data_types = ["DTM"]
        elif type_idx == 1:
            data_types = ["DSM"]
        else:
            data_types = ["DTM", "DSM"]

        # Select output directory
        output_dir = QFileDialog.getExistingDirectory(
            self,
            "Select Download Location",
            os.path.expanduser("~"),
        )
        if not output_dir:
            return

        self.download_status.setText("Initializing download...")
        self.download_progress.setVisible(True)
        self.download_progress.setRange(0, 100)
        self.download_btn.setEnabled(False)
        QApplication.processEvents()

        try:
            downloader = LidarDownloader(output_dir)

            # Check which regions cover this location
            regions = downloader.find_packages(lat, lng)
            if not regions:
                self.download_status.setText(
                    f"No LiDAR data found for coordinates ({lat:.4f}, {lng:.4f}).\n"
                    "Data may not be available for this area yet."
                )
                self.download_progress.setVisible(False)
                self.download_btn.setEnabled(True)
                return

            self.download_status.setText(f"Found regions: {', '.join(regions)}")
            QApplication.processEvents()

            def progress_cb(current, total, msg):
                if total > 0:
                    pct = int(current * 100 / total)
                    self.download_progress.setValue(pct)
                self.download_status.setText(msg)
                QApplication.processEvents()

            # Download
            downloaded = downloader.download_for_location(
                lat, lng,
                data_types=data_types,
                progress_callback=progress_cb
            )

            if downloaded:
                self.download_status.setText(
                    f"✓ Downloaded {len(downloaded)} package(s)!\n"
                    f"Location: {downloaded[0]}\n\n"
                    "Click 'Browse for GeoTIFF Folder' to load the data."
                )
                # Auto-load the first downloaded folder
                self._load_folder(str(downloaded[0]))
            else:
                self.download_status.setText(
                    "Could not download data. The package may not exist\n"
                    "or your coordinates may be outside coverage area."
                )

        except Exception as e:
            self.download_status.setText(f"Error: {e}")
            import traceback
            traceback.print_exc()

        self.download_progress.setVisible(False)
        self.download_btn.setEnabled(True)

    def _select_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select LiDAR GeoTIFF Folder")
        if folder:
            self._load_folder(folder)

    def _load_folder(self, folder):
        if not HAS_RASTERIO:
            QMessageBox.warning(self, "Missing Library",
                "rasterio is required.\nInstall with: pip install rasterio pyproj")
            return

        self.folder_label.setText(folder)
        self.tiles = []
        self.scene.clear()
        self.overlap_list.clear()

        # Find TIFF files
        tiff_files = []
        for root, dirs, files in os.walk(folder):
            for f in files:
                if f.lower().endswith(('.tif', '.tiff')):
                    tiff_files.append(os.path.join(root, f))

        if not tiff_files:
            self.tile_count_label.setText("No GeoTIFF files found")
            return

        self.tile_count_label.setText(f"Found {len(tiff_files)} files, loading...")
        self.load_progress.setVisible(True)
        self.load_progress.setRange(0, len(tiff_files))

        # Start background loading
        self.loader_thread = TileLoaderThread(tiff_files)
        self.loader_thread.progress.connect(self._on_load_progress)
        self.loader_thread.tile_loaded.connect(self._on_tile_loaded)
        self.loader_thread.finished_loading.connect(self._on_loading_finished)
        self.loader_thread.start()

    def _on_load_progress(self, current, total, name):
        self.load_progress.setValue(current)
        self.tile_count_label.setText(f"Loading {current}/{total}: {name}")

    def _on_tile_loaded(self, tile_info):
        self.tiles.append(tile_info)

    def _on_loading_finished(self, count):
        self.load_progress.setVisible(False)
        self.tile_count_label.setText(f"Loaded {count} tiles")
        self._update_view()

    def _update_property_bounds(self):
        self.property_bounds = {
            'lat_min': self.lat_min_input.value(),
            'lat_max': self.lat_max_input.value(),
            'lng_min': self.lng_min_input.value(),
            'lng_max': self.lng_max_input.value()
        }
        self._update_view()

    def _update_view(self):
        self.scene.clear()
        self.overlap_list.clear()

        if not self.tiles:
            return

        # Find overall bounds
        all_lat_min = min(t['lat_min'] for t in self.tiles)
        all_lat_max = max(t['lat_max'] for t in self.tiles)
        all_lng_min = min(t['lng_min'] for t in self.tiles)
        all_lng_max = max(t['lng_max'] for t in self.tiles)

        scale = 50000

        overlapping = []

        # Draw tiles
        for tile in self.tiles:
            x = (tile['lng_min'] - all_lng_min) * scale
            y = (all_lat_max - tile['lat_max']) * scale
            w = (tile['lng_max'] - tile['lng_min']) * scale
            h = (tile['lat_max'] - tile['lat_min']) * scale

            # Check overlap with property
            overlaps = (
                tile['lat_min'] <= self.property_bounds['lat_max'] and
                tile['lat_max'] >= self.property_bounds['lat_min'] and
                tile['lng_min'] <= self.property_bounds['lng_max'] and
                tile['lng_max'] >= self.property_bounds['lng_min']
            )

            rect = QGraphicsRectItem(x, y, w, h)
            if overlaps:
                rect.setBrush(QBrush(QColor(144, 238, 144, 150)))
                rect.setPen(QPen(QColor(0, 128, 0), 2))
                overlapping.append(tile)
                self.overlap_list.addItem(f"✓ {tile['name']}")
            else:
                rect.setBrush(QBrush(QColor(200, 200, 200, 80)))
                rect.setPen(QPen(QColor(150, 150, 150), 1))

            rect.setToolTip(f"{tile['name']}\n{tile['lat_min']:.5f} to {tile['lat_max']:.5f}")
            self.scene.addItem(rect)

        # Draw property bounds
        prop_x = (self.property_bounds['lng_min'] - all_lng_min) * scale
        prop_y = (all_lat_max - self.property_bounds['lat_max']) * scale
        prop_w = (self.property_bounds['lng_max'] - self.property_bounds['lng_min']) * scale
        prop_h = (self.property_bounds['lat_max'] - self.property_bounds['lat_min']) * scale

        prop_rect = QGraphicsRectItem(prop_x, prop_y, prop_w, prop_h)
        prop_rect.setPen(QPen(QColor(255, 0, 0), 3))
        prop_rect.setBrush(QBrush(QColor(255, 0, 0, 50)))
        self.scene.addItem(prop_rect)

        self._fit_view()

        # Enable extract if we have overlapping tiles
        self.extract_btn.setEnabled(len(overlapping) > 0)
        self._overlapping_tiles = overlapping

        if overlapping:
            self.extract_status.setText(f"Ready: {len(overlapping)} tile(s) overlap property")
        else:
            self.extract_status.setText("No tiles overlap property bounds")

    def _fit_view(self):
        self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def _extract_elevation(self):
        if not hasattr(self, '_overlapping_tiles') or not self._overlapping_tiles:
            return

        tile_paths = [t['path'] for t in self._overlapping_tiles]
        bounds = (
            self.property_bounds['lat_min'],
            self.property_bounds['lat_max'],
            self.property_bounds['lng_min'],
            self.property_bounds['lng_max']
        )

        self.extract_progress.setVisible(True)
        self.extract_progress.setRange(0, len(tile_paths))
        self.extract_btn.setEnabled(False)

        self.extractor_thread = ElevationExtractorThread(
            tile_paths, bounds, self.max_points_input.value()
        )
        self.extractor_thread.progress.connect(self._on_extract_progress)
        self.extractor_thread.finished_extraction.connect(self._on_extraction_finished)
        self.extractor_thread.error.connect(self._on_extraction_error)
        self.extractor_thread.start()

    def _on_extract_progress(self, current, total, msg):
        self.extract_progress.setValue(current)
        self.extract_status.setText(msg)

    def _on_extraction_finished(self, data):
        self.extract_progress.setVisible(False)
        self.extract_btn.setEnabled(True)
        self.elevation_data = data

        elev_range = data['max_elevation_m'] - data['min_elevation_m']
        self.extract_status.setText(
            f"✓ Extracted {data['count']} points\n"
            f"Elevation: {data['min_elevation_m']:.1f}m to {data['max_elevation_m']:.1f}m\n"
            f"Range: {elev_range:.2f}m ({elev_range * 3.28084:.1f}ft)"
        )
        self.export_btn.setEnabled(True)

    def _on_extraction_error(self, msg):
        self.extract_progress.setVisible(False)
        self.extract_btn.setEnabled(True)
        self.extract_status.setText(f"Error: {msg}")

    def _export_data(self):
        if not self.elevation_data:
            return

        format_idx = self.export_format.currentIndex()
        formats = [
            ("Revit Points", "*.txt", lambda p: self._export_revit_points(p, "feet")),
            ("Revit CSV (feet)", "*.csv", lambda p: self._export_revit_csv(p, "feet")),
            ("Revit CSV (meters)", "*.csv", lambda p: self._export_revit_csv(p, "meters")),
            ("ArchEngine JSON", "*.json", self._export_archengine),
            ("OBJ", "*.obj", self._export_obj),
            ("JSON", "*.json", self._export_raw_json)
        ]

        name, ext, export_func = formats[format_idx]
        file_path, _ = QFileDialog.getSaveFileName(self, f"Export {name}", "", f"{name} ({ext})")

        if file_path:
            try:
                export_func(file_path)
                QMessageBox.information(self, "Export Complete",
                    f"Saved to:\n{file_path}\n\n"
                    f"Points: {self.elevation_data['count']}\n"
                    f"For Revit: Massing & Site > Toposurface > Create from Import")
            except Exception as e:
                QMessageBox.warning(self, "Export Error", str(e))

    def _export_archengine(self, path):
        """Export as ArchEngine terrain mesh JSON."""
        points = self.elevation_data['points']
        bounds = self.elevation_data['bounds']

        # Create terrain mesh format
        lat_min, lat_max, lng_min, lng_max = bounds
        width_m = (lng_max - lng_min) * 111000 * math.cos(math.radians((lat_min + lat_max) / 2))
        height_m = (lat_max - lat_min) * 111000

        output = {
            "source": "Ontario LiDAR GeoTIFF",
            "resolution_m": self.elevation_data['resolution_m'],
            "bounds": {
                "lat_min": lat_min,
                "lat_max": lat_max,
                "lng_min": lng_min,
                "lng_max": lng_max
            },
            "width_ft": width_m * 3.28084,
            "depth_ft": height_m * 3.28084,
            "min_elevation_m": self.elevation_data['min_elevation_m'],
            "max_elevation_m": self.elevation_data['max_elevation_m'],
            "elevation_grid": points
        }

        with open(path, 'w') as f:
            json.dump(output, f, indent=2)

    def _export_revit_csv(self, path, units="feet"):
        """Export as CSV for Revit topography (X,Y,Z local coordinates)."""
        points = self.elevation_data['points']
        bounds = self.elevation_data['bounds']
        lat_min, lat_max, lng_min, lng_max = bounds

        center_lat = (lat_min + lat_max) / 2
        lat_to_m = 111000
        lng_to_m = 111000 * math.cos(math.radians(center_lat))
        m_to_units = 3.28084 if units == "feet" else 1.0

        min_elev = self.elevation_data['min_elevation_m']

        with open(path, 'w') as f:
            f.write("X,Y,Z\n")
            for key, pt in points.items():
                x = (pt['lng'] - lng_min) * lng_to_m * m_to_units
                y = (pt['lat'] - lat_min) * lat_to_m * m_to_units
                z = (pt['elevation_m'] - min_elev) * m_to_units
                f.write(f"{x:.4f},{y:.4f},{z:.4f}\n")

    def _export_revit_points(self, path, units="feet"):
        """Export as Revit points file (X Y Z space-separated)."""
        points = self.elevation_data['points']
        bounds = self.elevation_data['bounds']
        lat_min, lat_max, lng_min, lng_max = bounds

        center_lat = (lat_min + lat_max) / 2
        lat_to_m = 111000
        lng_to_m = 111000 * math.cos(math.radians(center_lat))
        m_to_units = 3.28084 if units == "feet" else 1.0

        min_elev = self.elevation_data['min_elevation_m']

        with open(path, 'w') as f:
            for key, pt in points.items():
                x = (pt['lng'] - lng_min) * lng_to_m * m_to_units
                y = (pt['lat'] - lat_min) * lat_to_m * m_to_units
                z = (pt['elevation_m'] - min_elev) * m_to_units
                f.write(f"{x:.4f} {y:.4f} {z:.4f}\n")

    def _export_obj(self, path):
        """Export as OBJ mesh."""
        points = list(self.elevation_data['points'].values())
        bounds = self.elevation_data['bounds']
        lat_min, lat_max, lng_min, lng_max = bounds

        # Sort points into grid
        lats = sorted(set(p['lat'] for p in points))
        lngs = sorted(set(p['lng'] for p in points))

        # Create vertex lookup
        vertex_map = {}
        for p in points:
            vertex_map[(p['lat'], p['lng'])] = p

        with open(path, 'w') as f:
            f.write("# LiDAR Terrain Mesh\n")
            f.write(f"# Points: {len(points)}\n\n")

            # Write vertices
            idx = 1
            vertex_indices = {}
            for lat in lats:
                for lng in lngs:
                    if (lat, lng) in vertex_map:
                        p = vertex_map[(lat, lng)]
                        x = (lng - lng_min) * 111000 * math.cos(math.radians(lat))
                        z = (lat - lat_min) * 111000
                        y = p['elevation_m']
                        f.write(f"v {x:.3f} {y:.3f} {z:.3f}\n")
                        vertex_indices[(lat, lng)] = idx
                        idx += 1

            f.write("\n# Faces\n")
            # Generate faces
            for i, lat in enumerate(lats[:-1]):
                for j, lng in enumerate(lngs[:-1]):
                    lat2 = lats[i + 1]
                    lng2 = lngs[j + 1]

                    v1 = vertex_indices.get((lat, lng))
                    v2 = vertex_indices.get((lat, lng2))
                    v3 = vertex_indices.get((lat2, lng))
                    v4 = vertex_indices.get((lat2, lng2))

                    if v1 and v2 and v3:
                        f.write(f"f {v1} {v3} {v2}\n")
                    if v2 and v3 and v4:
                        f.write(f"f {v2} {v3} {v4}\n")

    def _export_raw_json(self, path):
        """Export raw elevation data as JSON."""
        with open(path, 'w') as f:
            json.dump(self.elevation_data, f, indent=2)

    def closeEvent(self, event):
        if self.loader_thread and self.loader_thread.isRunning():
            self.loader_thread.stop()
            self.loader_thread.wait()
        event.accept()


def main():
    app = QApplication(sys.argv)

    initial_folder = sys.argv[1] if len(sys.argv) > 1 else None
    window = LidarExtractor(initial_folder)
    window.show()

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
