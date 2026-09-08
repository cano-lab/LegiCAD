"""
Solver Comparison Dialog
========================

Shows multiple solver results side-by-side in a grid.
Allows users to compare algorithms and select the best result.
"""
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGridLayout, QWidget, QScrollArea, QFrame, QProgressBar,
    QCheckBox, QSpinBox, QComboBox, QMessageBox, QSplitter
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread
from PyQt6.QtGui import QColor, QPixmap, QPainter, QFont

from complete_solver_suite import CompleteSolverSuite, SolverType, SOLVER_INFO
from room_relationships import SpatialGraph


@dataclass
class SolverResult:
    """Result from running a solver."""
    solver_type: SolverType
    layout: Optional['PlacedLayout']
    success: bool
    error: Optional[str] = None
    solve_time_ms: float = 0


class SolverWorker(QThread):
    """Worker thread to run a solver without blocking UI."""

    finished = pyqtSignal(SolverResult)
    progress = pyqtSignal(str, str)  # solver_name, status

    def __init__(self, solver_type: SolverType, suite: CompleteSolverSuite,
                 max_iterations: int = 5000):
        super().__init__()
        self.solver_type = solver_type
        self.suite = suite
        self.max_iterations = max_iterations

    def run(self):
        """Run the solver."""
        info = SOLVER_INFO.get(self.solver_type)
        name = info.name if info else self.solver_type.value

        self.progress.emit(name, "Running...")
        start_time = time.time()

        try:
            layout = self.suite.solve(self.solver_type, max_iterations=self.max_iterations)
            solve_time = (time.time() - start_time) * 1000

            result = SolverResult(
                solver_type=self.solver_type,
                layout=layout,
                success=True,
                solve_time_ms=solve_time
            )
            self.progress.emit(name, f"Complete - {len(layout.rooms)} rooms")

        except Exception as e:
            result = SolverResult(
                solver_type=self.solver_type,
                layout=None,
                success=False,
                error=str(e)
            )
            self.progress.emit(name, f"Failed: {e}")

        self.finished.emit(result)


class SolverCard(QFrame):
    """Card showing a single solver result."""

    selected = pyqtSignal(SolverType)

    def __init__(self, result: SolverResult, width_m: float, depth_m: float, parent=None):
        super().__init__(parent)
        self.result = result
        self.width_m = width_m
        self.depth_m = depth_m
        self._setup_ui()

    def _setup_ui(self):
        """Create the card UI."""
        info = SOLVER_INFO.get(self.result.solver_type)

        # Card styling
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        self.setStyleSheet(f"""
            SolverCard {{
                background: {'#e8f5e9' if self.result.success else '#ffebee'};
                border: 2px solid {'#4CAF50' if self.result.success else '#f44336'};
                border-radius: 8px;
                padding: 8px;
            }}
            SolverCard:hover {{
                border: 3px solid #2196F3;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(4)

        # Header
        header = QLabel(f"<b>{info.name if info else self.result.solver_type.value}</b>")
        header.setStyleSheet("font-size: 14px;")
        layout.addWidget(header)

        # Algorithm type tag
        if info:
            tag = QLabel(f"<small>{info.algorithm_type}</small>")
            tag.setStyleSheet(f"""
                color: {info.characteristics.get('color', '#666')};
                background: rgba(0,0,0,0.1);
                padding: 2px 6px;
                border-radius: 3px;
            """)
            layout.addWidget(tag)

        # Visualization
        viz = self._create_visualization()
        layout.addWidget(viz)

        # Stats
        if self.result.success and self.result.layout:
            layout_stats = self._create_stats()
            layout.addLayout(layout_stats)
        elif self.result.error:
            error_label = QLabel(f"<small style='color: red;'>{self.result.error[:50]}...</small>")
            error_label.setWordWrap(True)
            layout.addWidget(error_label)

        # Select button
        if self.result.success:
            select_btn = QPushButton("Use This Layout")
            select_btn.setStyleSheet("""
                QPushButton {
                    background: #2196F3;
                    color: white;
                    border: none;
                    padding: 8px;
                    border-radius: 4px;
                }
                QPushButton:hover {
                    background: #1976D2;
                }
            """)
            select_btn.clicked.connect(lambda: self.selected.emit(self.result.solver_type))
            layout.addWidget(select_btn)

        layout.addStretch()

    def _create_visualization(self) -> QLabel:
        """Create a visualization of the layout."""
        label = QLabel()
        label.setFixedSize(280, 200)
        label.setStyleSheet("background: white; border: 1px solid #ddd;")

        if not self.result.success or not self.result.layout:
            label.setText("<center><i>No valid layout</i></center>")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            return label

        # Create pixmap with layout
        pixmap = QPixmap(280, 200)
        pixmap.fill(QColor("white"))

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Scale to fit
        margin = 10
        scale_x = (280 - 2 * margin) / self.width_m
        scale_y = (200 - 2 * margin) / self.depth_m
        scale = min(scale_x, scale_y)

        offset_x = (280 - self.width_m * scale) / 2
        offset_y = (200 - self.depth_m * scale) / 2

        # Draw building outline
        painter.setPen(QColor("#333"))
        painter.setBrush(QColor("#fafafa"))
        painter.drawRect(
            int(offset_x), int(offset_y),
            int(self.width_m * scale), int(self.depth_m * scale)
        )

        # Draw rooms
        colors = [
            QColor("#4CAF50"), QColor("#2196F3"), QColor("#FF9800"),
            QColor("#9C27B0"), QColor("#00BCD4"), QColor("#E91E63"),
            QColor("#FFEB3B"), QColor("#795548"), QColor("#607D8B")
        ]

        for i, (room_id, room) in enumerate(self.result.layout.rooms.items()):
            r = room.rect
            x = int(offset_x + r.x * scale)
            y = int(offset_y + r.y * scale)
            w = int(r.width * scale)
            h = int(r.height * scale)

            color = colors[i % len(colors)]
            painter.setBrush(color)
            painter.setPen(QColor("#333"))
            painter.drawRect(x, y, w, h)

            # Room label if big enough
            if w > 30 and h > 20:
                painter.setPen(QColor("white"))
                painter.setFont(QFont("Arial", 8))
                painter.drawText(x, y, w, h, Qt.AlignmentFlag.AlignCenter, room_id[:6])

        painter.end()
        label.setPixmap(pixmap)

        return label

    def _create_stats(self) -> QHBoxLayout:
        """Create stats layout."""
        layout = QHBoxLayout()
        layout.setSpacing(10)

        layout_data = self.result.layout

        # Score
        score_widget = self._stat_box("Score", f"{layout_data.score:.0f}")
        layout.addWidget(score_widget)

        # Rooms
        rooms_widget = self._stat_box("Rooms", f"{len(layout_data.rooms)}")
        layout.addWidget(rooms_widget)

        # Time
        time_widget = self._stat_box("Time", f"{self.result.solve_time_ms:.0f}ms")
        layout.addWidget(time_widget)

        return layout

    def _stat_box(self, label: str, value: str) -> QFrame:
        """Create a stat box."""
        frame = QFrame()
        frame.setStyleSheet("""
            background: rgba(255,255,255,0.7);
            border-radius: 4px;
            padding: 4px;
        """)
        layout = QVBoxLayout(frame)
        layout.setSpacing(0)
        layout.setContentsMargins(4, 4, 4, 4)

        value_label = QLabel(f"<b>{value}</b>")
        value_label.setStyleSheet("font-size: 12px; color: #333;")
        value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(value_label)

        label_label = QLabel(f"<small>{label}</small>")
        label_label.setStyleSheet("color: #666;")
        label_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label_label)

        return frame


class SolverComparisonDialog(QDialog):
    """
    Dialog to compare multiple solver algorithms side-by-side.

    Shows a grid of solver results with visualizations and statistics.
    User can select the best result to use.
    """

    layout_selected = pyqtSignal(SolverType, 'PlacedLayout')  # Solver type and layout

    def __init__(self, graph: SpatialGraph, width_m: float, depth_m: float,
                 parent=None):
        super().__init__(parent)
        self.graph = graph
        self.width_m = width_m
        self.depth_m = depth_m
        self.results: Dict[SolverType, SolverResult] = {}
        self.workers: List[SolverWorker] = []

        self.setWindowTitle("Solver Comparison - Choose the Best Layout")
        self.setMinimumSize(1200, 800)
        self._setup_ui()

    def _setup_ui(self):
        """Create the dialog UI."""
        layout = QVBoxLayout(self)

        # Header
        header = QLabel("<h2>Solver Comparison</h2>")
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(header)

        desc = QLabel("Running multiple algorithms to find the best room layout. "
                      "Compare results and select your preferred layout.")
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # Controls
        controls = QHBoxLayout()

        self.max_iter_spin = QSpinBox()
        self.max_iter_spin.setRange(1000, 50000)
        self.max_iter_spin.setValue(5000)
        self.max_iter_spin.setSingleStep(1000)
        self.max_iter_spin.setSuffix(" iterations")
        controls.addWidget(QLabel("Max Iterations:"))
        controls.addWidget(self.max_iter_spin)

        controls.addStretch()

        self.parallel_check = QCheckBox("Run in parallel")
        self.parallel_check.setChecked(True)
        controls.addWidget(self.parallel_check)

        self.run_btn = QPushButton("🚀 Run All Solvers")
        self.run_btn.setStyleSheet("""
            QPushButton {
                background: #4CAF50;
                color: white;
                padding: 10px 20px;
                font-size: 14px;
                border-radius: 4px;
            }
            QPushButton:hover { background: #45a049; }
        """)
        self.run_btn.clicked.connect(self._run_solvers)
        controls.addWidget(self.run_btn)

        layout.addLayout(controls)

        # Progress bar
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        # Status label
        self.status_label = QLabel("Click 'Run All Solvers' to start comparison")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)

        # Scroll area for results grid
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: #f5f5f5; }")

        self.results_widget = QWidget()
        self.results_layout = QGridLayout(self.results_widget)
        self.results_layout.setSpacing(15)

        scroll.setWidget(self.results_widget)
        layout.addWidget(scroll, 1)

        # Bottom buttons
        buttons = QHBoxLayout()

        buttons.addStretch()

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        buttons.addWidget(close_btn)

        layout.addLayout(buttons)

    def _run_solvers(self):
        """Run all solvers."""
        # Clear previous results
        self.results.clear()
        for i in reversed(range(self.results_layout.count())):
            self.results_layout.itemAt(i).widget().deleteLater()

        # Setup
        max_iter = self.max_iter_spin.value()
        suite = CompleteSolverSuite(self.graph, self.width_m, self.depth_m)

        # Get solvers to run (exclude HYBRID)
        solvers = [st for st in SolverType if st != SolverType.HYBRID]

        self.progress.setMaximum(len(solvers))
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.run_btn.setEnabled(False)

        self.status_label.setText(f"Running {len(solvers)} solvers...")

        # Run solvers
        if self.parallel_check.isChecked():
            self._run_parallel(solvers, suite, max_iter)
        else:
            self._run_sequential(solvers, suite, max_iter)

    def _run_sequential(self, solvers: List[SolverType], suite: CompleteSolverSuite,
                        max_iter: int):
        """Run solvers one at a time."""
        for solver_type in solvers:
            worker = SolverWorker(solver_type, suite, max_iter)
            worker.finished.connect(self._on_solver_finished)
            worker.progress.connect(self._on_solver_progress)
            worker.start()
            self.workers.append(worker)

    def _run_parallel(self, solvers: List[SolverType], suite: CompleteSolverSuite,
                      max_iter: int):
        """Run solvers in parallel."""
        for solver_type in solvers:
            worker = SolverWorker(solver_type, suite, max_iter)
            worker.finished.connect(self._on_solver_finished)
            worker.progress.connect(self._on_solver_progress)
            worker.start()
            self.workers.append(worker)

    def _on_solver_progress(self, name: str, status: str):
        """Update status."""
        self.status_label.setText(f"{name}: {status}")

    def _on_solver_finished(self, result: SolverResult):
        """Handle solver completion."""
        self.results[result.solver_type] = result

        # Add card to grid
        row = len(self.results) // 3
        col = len(self.results) % 3

        card = SolverCard(result, self.width_m, self.depth_m)
        card.selected.connect(self._on_card_selected)
        self.results_layout.addWidget(card, row, col)

        # Update progress
        self.progress.setValue(len(self.results))

        # Check if all done
        total_solvers = len([st for st in SolverType if st != SolverType.HYBRID])
        if len(self.results) >= total_solvers:
            self._on_all_finished()

    def _on_all_finished(self):
        """Handle all solvers finishing."""
        self.run_btn.setEnabled(True)
        self.progress.setVisible(False)

        success_count = sum(1 for r in self.results.values() if r.success)
        self.status_label.setText(
            f"Complete! {success_count}/{len(self.results)} solvers succeeded. "
            "Click a solver card to select that layout."
        )

    def _on_card_selected(self, solver_type: SolverType):
        """Handle solver card selection."""
        result = self.results.get(solver_type)
        if result and result.success and result.layout:
            self.layout_selected.emit(solver_type, result.layout)
            self.accept()

    def closeEvent(self, event):
        """Clean up workers on close."""
        for worker in self.workers:
            if worker.isRunning():
                worker.terminate()
                worker.wait()
        event.accept()


def show_solver_comparison(graph: SpatialGraph, width_m: float, depth_m: float,
                           parent=None) -> Optional[tuple]:
    """
    Show solver comparison dialog.

    Args:
        graph: Room graph to solve
        width_m: Building width in meters
        depth_m: Building depth in meters
        parent: Parent widget

    Returns:
        (solver_type, layout) tuple if user selected a layout, None otherwise
    """
    dialog = SolverComparisonDialog(graph, width_m, depth_m, parent)

    if dialog.exec() == QDialog.DialogCode.Accepted:
        # This will be set via the signal
        return getattr(dialog, '_selected_result', None)

    return None


if __name__ == "__main__":
    import sys
    from PyQt6.QtWidgets import QApplication
    from room_relationships import SpatialGraph, Zone

    app = QApplication(sys.argv)

    # Create test graph
    graph = SpatialGraph()
    graph.add_room("living", "living", 20, target_area=25, zone=Zone.PUBLIC)
    graph.add_room("kitchen", "kitchen", 12, target_area=15, zone=Zone.PUBLIC)
    graph.add_room("bed1", "bedroom", 12, target_area=15, zone=Zone.PRIVATE)
    graph.add_room("bed2", "bedroom", 10, target_area=12, zone=Zone.PRIVATE)
    graph.add_room("bath", "bathroom", 6, target_area=8, zone=Zone.PRIVATE)

    graph.connect("living", "kitchen", 2.0)
    graph.connect("living", "bed1", 1.0)
    graph.connect("living", "bed2", 1.0)

    dialog = SolverComparisonDialog(graph, 15, 12)
    dialog.show()

    sys.exit(app.exec())
