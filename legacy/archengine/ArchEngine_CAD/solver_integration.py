"""
Integrated Solver Module for ArchEngine CAD

Connects the new solver suite to the CAD document model and drawing generation.
Provides:
- Solver selection UI integration
- Layout generation from document data
- Drawing generation from solver layouts
- Visual feedback during solving
"""

import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from enum import Enum

from PyQt6.QtCore import QObject, pyqtSignal, QThread
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QProgressBar, QTextEdit, QGroupBox, QGridLayout
)

# Add solver paths
_solver_path = Path(__file__).parent
if str(_solver_path) not in sys.path:
    sys.path.insert(0, str(_solver_path))

try:
    from complete_solver_suite import CompleteSolverSuite, SolverType, SOLVER_INFO
    from visual_comparison import TeachingComparator
    SOLVERS_AVAILABLE = True
except ImportError:
    SOLVERS_AVAILABLE = False
    print("[SolverIntegration] Warning: New solvers not available")

from room_relationships import SpatialGraph, RoomNode, Zone


# =============================================================================
# SOLVER WORKER THREAD
# =============================================================================

class SolverWorker(QThread):
    """Background worker for running solvers without blocking UI."""
    
    progress = pyqtSignal(str, int)  # message, percent
    layout_ready = pyqtSignal(dict, str)  # layout_data, solver_name
    error = pyqtSignal(str)
    
    def __init__(self, graph: SpatialGraph, width: float, depth: float, 
                 solver_type: SolverType, parent=None):
        super().__init__(parent)
        self.graph = graph
        self.width = width
        self.depth = depth
        self.solver_type = solver_type
        self.suite = CompleteSolverSuite(graph, width, depth)
    
    def run(self):
        """Run solver in background."""
        try:
            self.progress.emit(f"Running {self.solver_type.value} solver...", 10)
            
            layout = self.suite.solve(self.solver_type, max_iterations=10000)
            
            self.progress.emit("Converting layout...", 90)
            
            # Convert to CAD-compatible format
            layout_data = self._convert_layout(layout)
            
            solver_name = SOLVER_INFO[self.solver_type].name
            self.layout_ready.emit(layout_data, solver_name)
            
        except Exception as e:
            self.error.emit(str(e))
    
    def _convert_layout(self, layout) -> Dict:
        """Convert solver layout to CAD document format."""
        return {
            "rooms": {
                room_id: {
                    "x": room.rect.x,
                    "y": 0,  # Ground level
                    "z": room.rect.y,
                    "width": room.rect.width,
                    "depth": room.rect.height,
                    "height": 2700,  # Default ceiling height
                }
                for room_id, room in layout.rooms.items()
            },
            "walls": self._generate_walls(layout),
            "metadata": {
                "solver": self.solver_type.value,
                "score": layout.score,
                "complete": layout.is_complete,
            }
        }
    
    def _generate_walls(self, layout) -> List[Dict]:
        """Generate wall data from room layout."""
        walls = []
        wall_id = 0
        
        for room_id, room in layout.rooms.items():
            r = room.rect
            # Four walls per room
            wall_segments = [
                ((r.x, r.y), (r.x2, r.y)),  # South
                ((r.x2, r.y), (r.x2, r.y2)),  # East
                ((r.x2, r.y2), (r.x, r.y2)),  # North
                ((r.x, r.y2), (r.x, r.y)),  # West
            ]
            
            for (x1, y1), (x2, y2) in wall_segments:
                walls.append({
                    "id": wall_id,
                    "start": [x1, 0, y1],
                    "end": [x2, 0, y2],
                    "height": 2700,
                    "room": room_id,
                })
                wall_id += 1
        
        return walls


# =============================================================================
# SOLVER SELECTION DIALOG
# =============================================================================

class SolverSelectionDialog(QDialog):
    """Dialog for selecting and running solvers."""
    
    layout_generated = pyqtSignal(dict, str)  # layout_data, solver_name
    
    def __init__(self, document, parent=None):
        super().__init__(parent)
        self.document = document
        self.worker = None
        self._setup_ui()
    
    def _setup_ui(self):
        """Set up the dialog UI."""
        self.setWindowTitle("Generate Layout - Select Solver")
        self.setMinimumWidth(600)
        self.setMinimumHeight(500)
        
        layout = QVBoxLayout(self)
        
        # Header
        header = QLabel("Select a solver algorithm to generate the building layout.")
        header.setWordWrap(True)
        layout.addWidget(header)
        
        # Solver selection
        solver_group = QGroupBox("Solver Selection")
        solver_layout = QGridLayout()
        
        self.solver_combo = QComboBox()
        self._populate_solvers()
        self.solver_combo.currentIndexChanged.connect(self._on_solver_changed)
        
        solver_layout.addWidget(QLabel("Algorithm:"), 0, 0)
        solver_layout.addWidget(self.solver_combo, 0, 1)
        
        # Solver info display
        self.info_text = QTextEdit()
        self.info_text.setReadOnly(True)
        self.info_text.setMaximumHeight(150)
        solver_layout.addWidget(self.info_text, 1, 0, 1, 2)
        
        solver_group.setLayout(solver_layout)
        layout.addWidget(solver_group)
        
        # Progress
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        self.status_label = QLabel("")
        layout.addWidget(self.status_label)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.generate_btn = QPushButton("Generate Layout")
        self.generate_btn.clicked.connect(self._on_generate)
        button_layout.addWidget(self.generate_btn)
        
        self.compare_btn = QPushButton("Compare All Solvers")
        self.compare_btn.clicked.connect(self._on_compare)
        button_layout.addWidget(self.compare_btn)
        
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_btn)
        
        layout.addLayout(button_layout)
        
        # Initial update
        self._on_solver_changed(0)
    
    def _populate_solvers(self):
        """Populate solver dropdown."""
        if not SOLVERS_AVAILABLE:
            self.solver_combo.addItem("Solvers not available", None)
            return
        
        for solver_type in SolverType:
            if solver_type == SolverType.HYBRID:
                continue  # Skip hybrid for single selection
            
            info = SOLVER_INFO.get(solver_type)
            if info:
                display = f"{info.name} ({info.speed}, {info.reliability})"
                self.solver_combo.addItem(display, solver_type)
    
    def _on_solver_changed(self, index):
        """Update info when solver selection changes."""
        if not SOLVERS_AVAILABLE:
            self.info_text.setPlainText("Solver module not available.")
            return
        
        solver_type = self.solver_combo.currentData()
        if not solver_type:
            return
        
        info = SOLVER_INFO.get(solver_type)
        if info:
            text = f"""<b>{info.name}</b><br>
<br>
{info.description}<br>
<br>
<b>Best for:</b> {', '.join(info.best_for)}<br>
<b>Speed:</b> {info.speed} | <b>Reliability:</b> {info.reliability}<br>
<br>
<b>Characteristics:</b><br>"""
            for key, value in info.characteristics.items():
                text += f"• <b>{key}:</b> {value}<br>"
            
            self.info_text.setHtml(text)
    
    def _on_generate(self):
        """Generate layout with selected solver."""
        if not SOLVERS_AVAILABLE:
            self.status_label.setText("Error: Solvers not available")
            return
        
        solver_type = self.solver_combo.currentData()
        if not solver_type:
            return
        
        # Build graph from document
        graph = self._build_graph_from_document()
        if not graph or not graph.rooms:
            self.status_label.setText("Error: No rooms in document")
            return
        
        # Get building dimensions
        bounds = self.document.get_building_bounds()
        width = bounds.get("width", 10000) / 1000  # mm to meters
        depth = bounds.get("depth", 10000) / 1000
        
        # Start worker
        self.worker = SolverWorker(graph, width, depth, solver_type, self)
        self.worker.progress.connect(self._on_progress)
        self.worker.layout_ready.connect(self._on_layout_ready)
        self.worker.error.connect(self._on_error)
        
        self.generate_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        
        self.worker.start()
    
    def _on_compare(self):
        """Open comparison view."""
        # TODO: Open visual comparison dialog
        self.status_label.setText("Comparison view not yet implemented")
    
    def _on_progress(self, message: str, percent: int):
        """Update progress."""
        self.status_label.setText(message)
        self.progress_bar.setValue(percent)
    
    def _on_layout_ready(self, layout_data: Dict, solver_name: str):
        """Handle completed layout."""
        self.progress_bar.setValue(100)
        self.status_label.setText(f"Layout generated with {solver_name}")
        
        self.layout_generated.emit(layout_data, solver_name)
        self.accept()
    
    def _on_error(self, error_msg: str):
        """Handle error."""
        self.status_label.setText(f"Error: {error_msg}")
        self.generate_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
    
    def _build_graph_from_document(self) -> Optional[SpatialGraph]:
        """Build spatial graph from CAD document."""
        graph = SpatialGraph()
        
        # Add rooms from document
        for room_id, room_data in self.document.rooms.items():
            graph.add_room(
                room_id=room_id,
                room_type=room_data.get("type", "room"),
                min_area=room_data.get("area", 100),
            )
        
        # Add adjacencies
        for adj in self.document.adjacencies:
            graph.connect(adj["room_a"], adj["room_b"])
        
        return graph


# =============================================================================
# DOCUMENT INTEGRATION
# =============================================================================

class SolverDocumentIntegration:
    """Integrates solvers with ArchDocument."""
    
    def __init__(self, document):
        self.document = document
    
    def generate_layout_with_solver(self, solver_type: SolverType, parent_widget=None):
        """Open dialog and generate layout."""
        dialog = SolverSelectionDialog(self.document, parent_widget)
        dialog.layout_generated.connect(self._apply_layout)
        
        result = dialog.exec()
        return result == QDialog.DialogCode.Accepted
    
    def _apply_layout(self, layout_data: Dict, solver_name: str):
        """Apply generated layout to document."""
        # Update room positions
        for room_id, room_pos in layout_data.get("rooms", {}).items():
            if room_id in self.document.rooms:
                self.document.rooms[room_id]["position"] = {
                    "x": room_pos["x"],
                    "y": room_pos["y"],
                    "z": room_pos["z"],
                }
                self.document.rooms[room_id]["dimensions"] = {
                    "width": room_pos["width"],
                    "depth": room_pos["depth"],
                    "height": room_pos["height"],
                }
        
        # Add walls
        for wall_data in layout_data.get("walls", []):
            self.document.add_wall(wall_data)
        
        # Mark as modified
        self.document.mark_modified()
        
        print(f"[SolverIntegration] Applied layout from {solver_name}")


# =============================================================================
# DRAWING GENERATION INTEGRATION
# =============================================================================

class SolverDrawingIntegration:
    """Integrates solver layouts with drawing generation."""
    
    def __init__(self, document):
        self.document = document
    
    def generate_solver_comparison_sheet(self) -> str:
        """Generate a drawing sheet comparing all solvers."""
        if not SOLVERS_AVAILABLE:
            return ""
        
        # Build graph
        graph = self._build_graph()
        bounds = self.document.get_building_bounds()
        width = bounds.get("width", 10000) / 1000
        depth = bounds.get("depth", 10000) / 1000
        
        # Run all solvers
        suite = CompleteSolverSuite(graph, width, depth)
        results = suite.solve_all(max_iterations=3000)
        
        # Generate comparison SVG
        return self._create_comparison_svg(results)
    
    def _build_graph(self) -> SpatialGraph:
        """Build graph from document."""
        graph = SpatialGraph()
        
        for room_id, room_data in self.document.rooms.items():
            graph.add_room(
                room_id=room_id,
                room_type=room_data.get("type", "room"),
                min_area=room_data.get("area", 100),
            )
        
        return graph
    
    def _create_comparison_svg(self, results: Dict) -> str:
        """Create SVG comparing solver results."""
        # Simple grid layout
        cols = 3
        rows = (len(results) + cols - 1) // cols
        
        cell_width = 250
        cell_height = 200
        total_width = cols * cell_width + 50
        total_height = rows * cell_height + 100
        
        svg = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg width="{total_width}" height="{total_height}" xmlns="http://www.w3.org/2000/svg">
  <rect width="100%" height="100%" fill="#f5f5f5"/>
  <text x="{total_width/2}" y="30" text-anchor="middle" font-size="16" font-weight="bold">
    Solver Comparison
  </text>
'''
        
        colors = ["#4CAF50", "#2196F3", "#FF9800", "#9C27B0", "#f44336", "#00BCD4"]
        
        for idx, (solver_type, layout) in enumerate(results.items()):
            row = idx // cols
            col = idx % cols
            x = 25 + col * cell_width
            y = 60 + row * cell_height
            
            info = SOLVER_INFO.get(solver_type)
            color = colors[idx % len(colors)]
            
            # Cell background
            svg += f'''
  <rect x="{x}" y="{y}" width="{cell_width-10}" height="{cell_height-10}" 
        fill="white" stroke="#ddd"/>
'''
            
            # Title
            svg += f'''
  <text x="{x + (cell_width-10)/2}" y="{y + 20}" text-anchor="middle" 
        font-size="12" font-weight="bold">{info.name if info else solver_type.value}</text>
'''
            
            # Mini layout visualization
            scale = 0.15
            for room_id, room in layout.rooms.items():
                r = room.rect
                svg += f'''
  <rect x="{x + 10 + r.x * scale}" y="{y + 35 + r.y * scale}" 
        width="{r.width * scale}" height="{r.height * scale}" 
        fill="{color}" fill-opacity="0.5" stroke="none"/>
'''
            
            # Stats
            svg += f'''
  <text x="{x + 10}" y="{y + cell_height - 25}" font-size="10" fill="#666">
    Score: {layout.score:.0f}
  </text>
  <text x="{x + 10}" y="{y + cell_height - 10}" font-size="10" fill="#666">
    Rooms: {len(layout.rooms)}
  </text>
'''
        
        svg += '</svg>'
        return svg


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def show_solver_dialog(document, parent=None):
    """Show solver selection dialog."""
    integration = SolverDocumentIntegration(document)
    return integration.generate_layout_with_solver(parent_widget=parent)


def generate_solver_comparison(document) -> str:
    """Generate solver comparison drawing."""
    integration = SolverDrawingIntegration(document)
    return integration.generate_solver_comparison_sheet()


if __name__ == "__main__":
    print("Solver integration module loaded.")
    print(f"Solvers available: {SOLVERS_AVAILABLE}")
    if SOLVERS_AVAILABLE:
        print(f"Number of solvers: {len([s for s in SolverType if s != SolverType.HYBRID])}")
