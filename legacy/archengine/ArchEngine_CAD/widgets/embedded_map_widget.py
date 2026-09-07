"""
Embedded OpenStreetMap Widget for PyQt6
========================================
Interactive map widget using QWebEngineView with Leaflet.js.
Works in both development and frozen (PyInstaller) modes.
"""

import sys
import json
from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import QDialog, QVBoxLayout, QMessageBox
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot, QUrl, Qt
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebChannel import QWebChannel


class MapBridge(QObject):
    """Bridge object for JavaScript to call Python methods."""

    # Signals emitted when JS calls methods
    boundary_set = pyqtSignal(float, float, float, float, float, float, str, str)  # lat bounds, dimensions, vertices JSON
    building_set = pyqtSignal(float, float, float, float, float)  # lat, lng, x_ft, z_ft, rotation
    save_requested = pyqtSignal()

    def __init__(self, api_key: str = "", parent=None):
        super().__init__(parent)
        self.api_key = api_key
        self.boundary_data = None
        self.building_data = None

    @pyqtSlot(float, float, float, float, float, float, str, str)
    def set_boundary(self, lat_min, lat_max, lng_min, lng_max, width_ft, depth_ft, vertices_json, vertices_ft_json):
        """Called from JavaScript when boundary is drawn."""
        try:
            print(f"[MapBridge] Boundary set: {width_ft:.0f}' x {depth_ft:.0f}'")
            self.boundary_data = {
                'lat_min': lat_min,
                'lat_max': lat_max,
                'lng_min': lng_min,
                'lng_max': lng_max,
                'width_ft': width_ft,
                'depth_ft': depth_ft,
                'vertices': json.loads(vertices_json) if vertices_json else None,
                'vertices_ft': json.loads(vertices_ft_json) if vertices_ft_json else None
            }
            self.boundary_set.emit(lat_min, lat_max, lng_min, lng_max, width_ft, depth_ft, vertices_json, vertices_ft_json)
        except Exception as e:
            print(f"[MapBridge] Error in set_boundary: {e}")

    @pyqtSlot(float, float, float, float, float)
    def set_building_origin(self, lat, lng, x_ft, z_ft, rotation_deg):
        """Called from JavaScript when building placement is set."""
        try:
            print(f"[MapBridge] Building origin: ({x_ft:.1f}', {z_ft:.1f}') rotation={rotation_deg:.1f}°")
            self.building_data = {
                'lat': lat,
                'lng': lng,
                'x_ft': x_ft,
                'z_ft': z_ft,
                'rotation_deg': rotation_deg
            }
            self.building_set.emit(lat, lng, x_ft, z_ft, rotation_deg)
        except Exception as e:
            print(f"[MapBridge] Error in set_building_origin: {e}")

    @pyqtSlot()
    def save_and_close(self):
        """Called from JavaScript when user clicks Save & Close."""
        try:
            print("[MapBridge] Save requested")
            self.save_requested.emit()
        except Exception as e:
            print(f"[MapBridge] Error in save_and_close: {e}")

    @pyqtSlot(str)
    def log(self, message):
        """Log message from JavaScript."""
        print(f"[MapJS] {message}")


class EmbeddedMapWidget(QDialog):
    """
    Qt dialog with embedded OpenStreetMap using QWebEngineView.
    """

    boundary_changed = pyqtSignal(float, float, float, float, float, float, object, object)
    building_placed = pyqtSignal(float, float, float, float, float)
    close_requested = pyqtSignal()

    def __init__(self, lat=45.4215, lng=-75.6972, zoom=16, api_key=None, parent=None):
        print("[EmbeddedMapWidget] __init__ starting...")
        super().__init__(parent)

        # Ensure it's a proper window, not a popup/tool
        self.setWindowFlag(Qt.WindowType.Tool, False)
        self.setWindowFlag(Qt.WindowType.Dialog, False)

        self._lat = lat
        self._lng = lng
        self._zoom = zoom
        self._api_key = api_key or ''
        self._initialized = False
        self._web_view = None
        self._channel = None
        self._bridge = None

        print(f"[EmbeddedMapWidget] Initializing at ({lat}, {lng}), zoom={zoom}")

        # Setup UI
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        try:
            # Create web view
            print("[EmbeddedMapWidget] Creating QWebEngineView...")
            self._web_view = QWebEngineView()
            print("[EmbeddedMapWidget] QWebEngineView created")

            # Set minimum size to ensure visibility
            self._web_view.setMinimumSize(400, 300)

            layout.addWidget(self._web_view)
            print("[EmbeddedMapWidget] QWebEngineView added to layout")

            # Setup web channel for JS<->Python communication
            print("[EmbeddedMapWidget] Setting up QWebChannel...")
            self._channel = QWebChannel()
            print("[EmbeddedMapWidget] QWebChannel created")

            self._bridge = MapBridge(self._api_key)
            print("[EmbeddedMapWidget] MapBridge created")

            self._channel.registerObject('pyBridge', self._bridge)
            print("[EmbeddedMapWidget] Bridge registered")

            self._web_view.page().setWebChannel(self._channel)
            print("[EmbeddedMapWidget] QWebChannel configured")

            # Connect bridge signals
            print("[EmbeddedMapWidget] Connecting bridge signals...")
            self._bridge.boundary_set.connect(self._on_boundary_set)
            self._bridge.building_set.connect(self._on_building_set)
            self._bridge.save_requested.connect(self._on_save_requested)
            print("[EmbeddedMapWidget] Bridge signals connected")

            # Load the map
            print("[EmbeddedMapWidget] Loading map...")
            self._load_map()
            self._initialized = True
            print("[EmbeddedMapWidget] Initialization complete")

        except Exception as e:
            print(f"[EmbeddedMapWidget] ERROR during initialization: {e}")
            import traceback
            traceback.print_exc()
            # Show error in the widget
            from PyQt6.QtWidgets import QLabel
            error_label = QLabel(f"Map failed to load:\n{e}")
            error_label.setStyleSheet("color: red; padding: 20px;")
            layout.addWidget(error_label)

    def _on_boundary_set(self, lat_min, lat_max, lng_min, lng_max, width_ft, depth_ft, vertices_json, vertices_ft_json):
        """Handle boundary set from JS."""
        try:
            vertices = json.loads(vertices_json) if vertices_json else None
            vertices_ft = json.loads(vertices_ft_json) if vertices_ft_json else None
            print(f"[EmbeddedMapWidget] Emitting boundary_changed")
            self.boundary_changed.emit(lat_min, lat_max, lng_min, lng_max, width_ft, depth_ft, vertices, vertices_ft)
        except Exception as e:
            print(f"[EmbeddedMapWidget] Error in _on_boundary_set: {e}")

    def _on_building_set(self, lat, lng, x_ft, z_ft, rotation_deg):
        """Handle building placement from JS."""
        self.building_placed.emit(lat, lng, x_ft, z_ft, rotation_deg)

    def _on_save_requested(self):
        """Handle save request from JS."""
        print("[EmbeddedMapWidget] Save requested, emitting close_requested")
        try:
            self.close_requested.emit()
        except Exception as e:
            print(f"[EmbeddedMapWidget] Error emitting close_requested: {e}")

    def get_boundary_data(self):
        """Get the current boundary data."""
        return self._bridge.boundary_data

    def get_building_data(self):
        """Get the current building placement data."""
        return self._bridge.building_data

    def closeEvent(self, event):
        """Handle window close event (X button)."""
        print("[EmbeddedMapWidget] closeEvent called")
        self.close_requested.emit()
        event.accept()

    def _load_map(self):
        """Load the Leaflet map HTML."""
        print("[EmbeddedMapWidget] Loading map HTML...")
        try:
            html = self._get_map_html()
            print(f"[EmbeddedMapWidget] HTML generated ({len(html)} chars)")
            self._web_view.setHtml(html, QUrl("about:blank"))
            print("[EmbeddedMapWidget] HTML set on QWebEngineView")
        except Exception as e:
            print(f"[EmbeddedMapWidget] ERROR loading map: {e}")
            import traceback
            traceback.print_exc()
            raise

    def _get_map_html(self):
        """Generate the Leaflet/OpenStreetMap HTML with QWebChannel support."""
        return f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
    <style>
        body {{ margin: 0; padding: 0; font-family: Arial, sans-serif; }}
        #map {{ width: 100vw; height: 100vh; }}
        .controls {{
            position: absolute;
            top: 10px;
            left: 10px;
            z-index: 1000;
            background: white;
            padding: 12px;
            border-radius: 8px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
            max-width: 300px;
            font-size: 12px;
        }}
        .controls h3 {{ margin: 0 0 8px 0; font-size: 14px; color: #333; }}
        .controls p {{ margin: 4px 0; font-size: 11px; color: #666; }}
        .controls button {{
            margin: 3px;
            padding: 8px 12px;
            cursor: pointer;
            background: #4CAF50;
            color: white;
            border: none;
            border-radius: 4px;
            font-size: 12px;
        }}
        .controls button:hover {{ background: #45a049; }}
        .controls button.secondary {{ background: #6c757d; }}
        .controls button.secondary:hover {{ background: #5a6268; }}
        .controls button.success {{ background: #28a745; }}
        .controls button.success:hover {{ background: #218838; }}
        .controls button.building {{ background: #2196F3; }}
        .controls button.building:hover {{ background: #1976D2; }}
        .controls button:disabled {{ background: #ccc; cursor: not-allowed; }}
        .section {{ margin: 8px 0; padding: 8px; background: #f5f5f5; border-radius: 4px; }}
        .section-title {{ font-weight: bold; font-size: 12px; margin-bottom: 6px; color: #333; }}
        .info {{
            position: absolute;
            bottom: 15px;
            left: 50%;
            transform: translateX(-50%);
            z-index: 1000;
            background: rgba(0,0,0,0.85);
            color: white;
            padding: 10px 16px;
            border-radius: 6px;
            font-size: 12px;
            max-width: 400px;
            text-align: center;
        }}
        .status-badge {{
            display: inline-block;
            padding: 2px 6px;
            border-radius: 3px;
            font-size: 10px;
            margin-left: 4px;
        }}
        .status-pending {{ background: #FFC107; color: #333; }}
        .status-done {{ background: #4CAF50; color: white; }}
    </style>
</head>
<body>
    <div class="controls">
        <h3>Site & Building Placement</h3>

        <div class="section">
            <div class="section-title">Step 1: Draw Property <span id="boundaryStatus" class="status-badge status-pending">pending</span></div>
            <p>Click points around your property line</p>
            <button onclick="startDrawing()">Start Drawing</button>
            <button onclick="finishPolygon()" class="secondary">Finish</button>
            <button onclick="clearBoundary()" class="secondary">Clear</button>
        </div>

        <div class="section">
            <div class="section-title">Step 2: Place Building <span id="buildingStatus" class="status-badge status-pending">pending</span></div>
            <p>Click inside boundary to set building center</p>
            <button id="placeBuildingBtn" onclick="startPlaceBuilding()" class="building" disabled>Place Building</button>
            <button onclick="clearBuilding()" class="secondary">Clear</button>
            <div id="rotationControl" style="display: none; margin-top: 8px;">
                <label style="font-size: 11px;">Rotation: <span id="rotationValue">0</span>°</label>
                <input type="range" id="rotationSlider" min="0" max="360" value="0" style="width: 100%;" oninput="onRotationChange(this.value)">
            </div>
        </div>

        <hr style="margin: 10px 0; border: none; border-top: 1px solid #ddd;">
        <button onclick="saveAndClose()" class="success" style="width: calc(100% - 6px);">Save & Close</button>
    </div>
    <div id="map"></div>
    <div class="info" id="info">Loading map...</div>

    <script>
        var pyBridge = null;
        var map;
        var drawnItems;
        var buildingLayer;
        var polygonPoints = [];
        var polygon = null;
        var hasBoundary = false;
        var buildingMarker = null;
        var buildingFootprint = null;
        var hasBuilding = false;
        var isPlacingBuilding = false;
        var buildingRotation = 0;
        var buildingLatLng = null;
        var lat = {self._lat};
        var lng = {self._lng};
        var zoom = {self._zoom};

        // Initialize QWebChannel
        try {{
            new QWebChannel(qt.webChannelTransport, function(channel) {{
                pyBridge = channel.objects.pyBridge;
                console.log('QWebChannel connected');
                try {{
                    initMap();
                }} catch(e) {{
                    console.error('Error initializing map:', e);
                    document.getElementById('info').innerHTML = 'Error loading map: ' + e.message;
                }}
            }});
        }} catch(e) {{
            console.error('QWebChannel error:', e);
            document.getElementById('info').innerHTML = 'Error connecting to Python: ' + e.message;
        }}

        function initMap() {{
            map = L.map('map').setView([lat, lng], zoom);

            // OpenStreetMap layer
            L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
                attribution: '© OpenStreetMap contributors',
                maxZoom: 19
            }}).addTo(map);

            // Satellite layer (Esri)
            L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}', {{
                attribution: 'Tiles © Esri',
                maxZoom: 19
            }}).addTo(map);

            drawnItems = L.featureGroup().addTo(map);
            buildingLayer = L.featureGroup().addTo(map);

            updateInfo('Map ready! Draw your property boundary.');
        }}

        function startDrawing() {{
            if (polygon) clearBoundary();
            isPlacingBuilding = false;
            updateInfo('Click on map to place boundary points. Click Finish when done.');
            map.on('click', onBoundaryClick);
            map.doubleClickZoom.disable();
        }}

        function onBoundaryClick(e) {{
            var latlng = e.latlng;
            polygonPoints.push(latlng);

            L.circleMarker(latlng, {{
                radius: 5, fillColor: '#00FF00', fillOpacity: 0.8,
                color: '#FFFFFF', weight: 2
            }}).addTo(drawnItems);

            if (polygonPoints.length >= 2) {{
                if (polygon) drawnItems.removeLayer(polygon);
                polygon = L.polygon(polygonPoints, {{
                    color: '#00FF00', fillColor: '#00FF00',
                    fillOpacity: 0.2, weight: 3
                }}).addTo(drawnItems);
            }}

            updateInfo('Points: ' + polygonPoints.length + ' (click Finish when done)');
        }}

        function finishPolygon() {{
            if (polygonPoints.length < 3) {{
                updateInfo('Need at least 3 points!');
                return;
            }}

            map.off('click', onBoundaryClick);
            map.doubleClickZoom.enable();
            hasBoundary = true;

            var bounds = L.latLngBounds(polygonPoints);
            var latMin = bounds.getSouth();
            var latMax = bounds.getNorth();
            var lngMin = bounds.getWest();
            var lngMax = bounds.getEast();

            var latDiff = latMax - latMin;
            var lngDiff = lngMax - lngMin;
            var centerLat = (latMin + latMax) / 2;
            var depthFt = Math.abs(latDiff) * 364000;
            var widthFt = Math.abs(lngDiff) * 364000 * Math.cos(centerLat * Math.PI / 180);

            document.getElementById('boundaryStatus').className = 'status-badge status-done';
            document.getElementById('boundaryStatus').textContent = 'done';
            document.getElementById('placeBuildingBtn').disabled = false;

            updateInfo('Property: ' + widthFt.toFixed(0) + "' x " + depthFt.toFixed(0) + "' - Now place building!");

            var vertices = polygonPoints.map(function(p) {{ return [p.lat, p.lng]; }});
            var verticesFt = polygonPoints.map(function(p) {{
                var xFt = (p.lng - lngMin) * 364000 * Math.cos(centerLat * Math.PI / 180);
                var zFt = (p.lat - latMin) * 364000;
                return [xFt, zFt];
            }});

            window.boundaryData = {{
                latMin: latMin, latMax: latMax, lngMin: lngMin, lngMax: lngMax,
                widthFt: widthFt, depthFt: depthFt, centerLat: centerLat,
                vertices: vertices, verticesFt: verticesFt
            }};

            if (pyBridge) {{
                pyBridge.set_boundary(latMin, latMax, lngMin, lngMax, widthFt, depthFt,
                    JSON.stringify(vertices), JSON.stringify(verticesFt));
            }}
        }}

        function clearBoundary() {{
            drawnItems.clearLayers();
            polygon = null;
            polygonPoints = [];
            hasBoundary = false;
            window.boundaryData = null;
            map.off('click', onBoundaryClick);
            map.doubleClickZoom.enable();

            document.getElementById('boundaryStatus').className = 'status-badge status-pending';
            document.getElementById('boundaryStatus').textContent = 'pending';
            document.getElementById('placeBuildingBtn').disabled = true;

            clearBuilding();
            updateInfo('Boundary cleared. Click Start Drawing to begin.');
        }}

        function startPlaceBuilding() {{
            if (!hasBoundary) {{
                updateInfo('Draw a property boundary first!');
                return;
            }}
            isPlacingBuilding = true;
            map.off('click', onBoundaryClick);
            map.on('click', onBuildingClick);
            updateInfo('Click inside your property to place the building center');
        }}

        function onBuildingClick(e) {{
            if (!isPlacingBuilding || !window.boundaryData) return;

            var latlng = e.latlng;
            var b = window.boundaryData;

            if (latlng.lat < b.latMin || latlng.lat > b.latMax ||
                latlng.lng < b.lngMin || latlng.lng > b.lngMax) {{
                updateInfo('Click INSIDE the property boundary!');
                return;
            }}

            buildingLayer.clearLayers();
            buildingLatLng = latlng;
            buildingRotation = 0;

            createBuildingVisualization();

            hasBuilding = true;
            isPlacingBuilding = false;
            map.off('click', onBuildingClick);

            document.getElementById('rotationControl').style.display = 'block';
            document.getElementById('rotationSlider').value = 0;
            document.getElementById('rotationValue').textContent = '0';

            document.getElementById('buildingStatus').className = 'status-badge status-done';
            document.getElementById('buildingStatus').textContent = 'done';

            sendBuildingData();
        }}

        function createBuildingVisualization() {{
            if (!buildingLatLng || !window.boundaryData) return;

            buildingLayer.clearLayers();
            var b = window.boundaryData;

            buildingMarker = L.marker(buildingLatLng, {{
                icon: L.divIcon({{
                    className: 'building-icon',
                    html: '<div style="width:16px;height:16px;background:#2196F3;border:3px solid white;border-radius:50%;box-shadow:0 2px 6px rgba(0,0,0,0.5);"></div>',
                    iconSize: [22, 22], iconAnchor: [11, 11]
                }}),
                draggable: true
            }}).addTo(buildingLayer);

            var latScale = (b.latMax - b.latMin) / b.depthFt;
            var lngScale = (b.lngMax - b.lngMin) / b.widthFt;
            var halfWidth = 20 * lngScale;
            var halfDepth = 15 * latScale;

            var footprintPoints = getRotatedRectangle(buildingLatLng, halfWidth, halfDepth, buildingRotation);
            buildingFootprint = L.polygon(footprintPoints, {{
                color: '#2196F3', fillColor: '#2196F3',
                fillOpacity: 0.3, weight: 2
            }}).addTo(buildingLayer);

            var frontPoint = rotatePoint(buildingLatLng, 0, halfDepth * 1.5, buildingRotation);
            L.polyline([buildingLatLng, frontPoint], {{
                color: '#FF5722', weight: 3, dashArray: '5, 5'
            }}).addTo(buildingLayer);

            buildingMarker.on('drag', function(e) {{
                buildingLatLng = e.target.getLatLng();
                createBuildingVisualization();
            }});

            buildingMarker.on('dragend', function(e) {{
                buildingLatLng = e.target.getLatLng();
                createBuildingVisualization();
                sendBuildingData();
            }});

            updateBuildingInfo();
        }}

        function getRotatedRectangle(center, halfWidth, halfDepth, angleDeg) {{
            var corners = [
                [-halfWidth, -halfDepth], [halfWidth, -halfDepth],
                [halfWidth, halfDepth], [-halfWidth, halfDepth]
            ];
            return corners.map(function(c) {{ return rotatePoint(center, c[0], c[1], angleDeg); }});
        }}

        function rotatePoint(center, dx, dy, angleDeg) {{
            var angleRad = angleDeg * Math.PI / 180;
            var cosA = Math.cos(angleRad);
            var sinA = Math.sin(angleRad);
            return L.latLng(center.lat + dx * sinA + dy * cosA, center.lng + dx * cosA - dy * sinA);
        }}

        function onRotationChange(value) {{
            buildingRotation = parseInt(value);
            document.getElementById('rotationValue').textContent = value;
            if (hasBuilding && buildingLatLng) {{
                createBuildingVisualization();
                sendBuildingData();
            }}
        }}

        function updateBuildingInfo() {{
            if (!buildingLatLng || !window.boundaryData) return;
            var b = window.boundaryData;
            var xFt = ((buildingLatLng.lng - b.lngMin) / (b.lngMax - b.lngMin)) * b.widthFt;
            var zFt = ((buildingLatLng.lat - b.latMin) / (b.latMax - b.latMin)) * b.depthFt;
            updateInfo('Building: (' + xFt.toFixed(0) + "', " + zFt.toFixed(0) + "') Rotation: " + buildingRotation + "°");
        }}

        function sendBuildingData() {{
            if (!buildingLatLng || !window.boundaryData) return;
            var b = window.boundaryData;
            var xFt = ((buildingLatLng.lng - b.lngMin) / (b.lngMax - b.lngMin)) * b.widthFt;
            var zFt = ((buildingLatLng.lat - b.latMin) / (b.latMax - b.latMin)) * b.depthFt;

            if (pyBridge) {{
                pyBridge.set_building_origin(buildingLatLng.lat, buildingLatLng.lng, xFt, zFt, buildingRotation);
            }}
            updateBuildingInfo();
        }}

        function clearBuilding() {{
            buildingLayer.clearLayers();
            buildingMarker = null;
            buildingFootprint = null;
            buildingLatLng = null;
            buildingRotation = 0;
            hasBuilding = false;
            isPlacingBuilding = false;
            map.off('click', onBuildingClick);

            document.getElementById('rotationControl').style.display = 'none';
            document.getElementById('buildingStatus').className = 'status-badge status-pending';
            document.getElementById('buildingStatus').textContent = 'pending';

            if (hasBoundary) updateInfo('Building cleared. Click Place Building to set location.');
        }}

        function saveAndClose() {{
            if (!hasBoundary || !window.boundaryData) {{
                updateInfo('Draw a boundary first!');
                return;
            }}

            if (!hasBuilding) {{
                var b = window.boundaryData;
                var defaultX = b.widthFt / 2;
                var defaultZ = b.depthFt / 2;
                var centerLat = (b.latMin + b.latMax) / 2;
                var centerLng = (b.lngMin + b.lngMax) / 2;
                if (pyBridge) {{
                    pyBridge.set_building_origin(centerLat, centerLng, defaultX, defaultZ, 0);
                }}
            }}

            updateInfo('Saving...');
            if (pyBridge) pyBridge.save_and_close();
        }}

        function updateInfo(text) {{
            document.getElementById('info').textContent = text;
        }}
    </script>
</body>
</html>'''
