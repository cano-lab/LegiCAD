"""
Path Tracer Render Dialog

Provides UI for configuring and running offline path traced renders.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QSpinBox, QDoubleSpinBox, QComboBox, QPushButton,
    QProgressBar, QLabel, QFileDialog, QGroupBox,
    QMessageBox
)
from PyQt6.QtCore import Qt, QTimer


class PathTracerDialog(QDialog):
    """Dialog for configuring and running path traced renders."""

    def __init__(self, viewport, parent=None):
        super().__init__(parent)
        self.viewport = viewport
        self._render_timer = None

        self.setWindowTitle("Path Traced Render")
        self.setMinimumWidth(400)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Check if path tracer is available
        if not self.viewport.has_path_tracer():
            layout.addWidget(QLabel(
                "Path Tracer API not available.\n"
                "Please rebuild the DLL with path tracer support."
            ))
            close_btn = QPushButton("Close")
            close_btn.clicked.connect(self.close)
            layout.addWidget(close_btn)
            return

        # Resolution group
        res_group = QGroupBox("Resolution")
        res_layout = QFormLayout(res_group)

        self.width_spin = QSpinBox()
        self.width_spin.setRange(320, 8192)
        self.width_spin.setValue(1920)
        self.width_spin.setSingleStep(160)
        res_layout.addRow("Width:", self.width_spin)

        self.height_spin = QSpinBox()
        self.height_spin.setRange(240, 8192)
        self.height_spin.setValue(1080)
        self.height_spin.setSingleStep(120)
        res_layout.addRow("Height:", self.height_spin)

        layout.addWidget(res_group)

        # Quality group
        quality_group = QGroupBox("Quality")
        quality_layout = QFormLayout(quality_group)

        self.samples_spin = QSpinBox()
        self.samples_spin.setRange(16, 4096)
        self.samples_spin.setValue(256)
        self.samples_spin.setSingleStep(64)
        self.samples_spin.setToolTip("Samples per pixel (higher = less noise, longer render)")
        quality_layout.addRow("Samples:", self.samples_spin)

        self.bounces_spin = QSpinBox()
        self.bounces_spin.setRange(1, 32)
        self.bounces_spin.setValue(8)
        self.bounces_spin.setToolTip("Maximum light bounces (higher = more accurate GI)")
        quality_layout.addRow("Bounces:", self.bounces_spin)

        layout.addWidget(quality_group)

        # Post-processing group
        post_group = QGroupBox("Post-Processing")
        post_layout = QFormLayout(post_group)

        self.exposure_spin = QDoubleSpinBox()
        self.exposure_spin.setRange(0.1, 10.0)
        self.exposure_spin.setValue(1.0)
        self.exposure_spin.setSingleStep(0.1)
        self.exposure_spin.setDecimals(2)
        post_layout.addRow("Exposure:", self.exposure_spin)

        self.tonemap_combo = QComboBox()
        self.tonemap_combo.addItems(["Reinhard", "ACES (Recommended)", "Uncharted 2"])
        self.tonemap_combo.setCurrentIndex(1)
        post_layout.addRow("Tonemap:", self.tonemap_combo)

        self.denoise_check = QPushButton("Apply Denoise After Render")
        self.denoise_check.setCheckable(True)
        self.denoise_check.setChecked(True)
        post_layout.addRow(self.denoise_check)

        layout.addWidget(post_group)

        # Progress
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        # Buttons
        btn_layout = QHBoxLayout()

        self.render_btn = QPushButton("Start Render")
        self.render_btn.clicked.connect(self._start_render)
        btn_layout.addWidget(self.render_btn)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self._stop_render)
        self.stop_btn.setEnabled(False)
        btn_layout.addWidget(self.stop_btn)

        self.save_btn = QPushButton("Save PNG...")
        self.save_btn.clicked.connect(self._save_png)
        self.save_btn.setEnabled(False)
        btn_layout.addWidget(self.save_btn)

        self.save_hdr_btn = QPushButton("Save HDR...")
        self.save_hdr_btn.clicked.connect(self._save_hdr)
        self.save_hdr_btn.setEnabled(False)
        btn_layout.addWidget(self.save_hdr_btn)

        layout.addLayout(btn_layout)

        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)

    def _start_render(self):
        """Start the path traced render."""
        # Configure
        width = self.width_spin.value()
        height = self.height_spin.value()
        samples = self.samples_spin.value()
        bounces = self.bounces_spin.value()

        if not self.viewport.pt_configure(width, height, samples, bounces):
            QMessageBox.critical(self, "Error", "Failed to configure path tracer")
            return

        # Set post-processing
        self.viewport.pt_set_exposure(self.exposure_spin.value())
        self.viewport.pt_set_tonemap_mode(self.tonemap_combo.currentIndex())

        # Start render
        if not self.viewport.pt_start_render():
            QMessageBox.critical(self, "Error", "Failed to start render")
            return

        # UI state
        self.render_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.save_btn.setEnabled(False)
        self.save_hdr_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)

        # Start progress timer
        self._render_timer = QTimer()
        self._render_timer.timeout.connect(self._update_render)
        self._render_timer.start(100)  # Update every 100ms

    def _update_render(self):
        """Update render progress."""
        if not self.viewport.pt_is_rendering():
            self._finish_render()
            return

        # Render one frame
        result = self.viewport.pt_render_frame()
        if result == 0:
            # Complete
            self._finish_render()
            return
        elif result == -1:
            # Error
            self._stop_render()
            QMessageBox.critical(self, "Error", "Render failed")
            return

        # Update progress
        progress = self.viewport.pt_get_progress()
        self.progress_bar.setValue(int(progress * 100))
        samples = self.viewport.pt_get_sample_count()
        self.status_label.setText(f"Rendering... {samples} samples ({progress*100:.1f}%)")

    def _finish_render(self):
        """Handle render completion."""
        if self._render_timer:
            self._render_timer.stop()
            self._render_timer = None

        # Apply denoise if requested
        if self.denoise_check.isChecked():
            self.status_label.setText("Applying denoise...")
            self.viewport.pt_apply_denoise()

        self.progress_bar.setValue(100)
        self.status_label.setText("Render complete!")

        # UI state
        self.render_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.save_btn.setEnabled(True)
        self.save_hdr_btn.setEnabled(True)

    def _stop_render(self):
        """Stop the render early."""
        if self._render_timer:
            self._render_timer.stop()
            self._render_timer = None

        self.viewport.pt_stop()
        self.status_label.setText("Render stopped")

        # UI state
        self.render_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.save_btn.setEnabled(True)
        self.save_hdr_btn.setEnabled(True)
        self.progress_bar.setVisible(False)

    def _save_png(self):
        """Save render as PNG."""
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Render", "", "PNG Files (*.png)"
        )
        if path:
            if not path.lower().endswith('.png'):
                path += '.png'
            exposure = self.exposure_spin.value()
            if self.viewport.pt_save_png(path, exposure):
                self.status_label.setText(f"Saved: {path}")
            else:
                QMessageBox.critical(self, "Error", "Failed to save PNG")

    def _save_hdr(self):
        """Save render as HDR."""
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Render", "", "HDR Files (*.hdr)"
        )
        if path:
            if not path.lower().endswith('.hdr'):
                path += '.hdr'
            if self.viewport.pt_save_hdr(path):
                self.status_label.setText(f"Saved: {path}")
            else:
                QMessageBox.critical(self, "Error", "Failed to save HDR")

    def closeEvent(self, event):
        """Stop render when dialog closes."""
        if self._render_timer:
            self._render_timer.stop()
            self.viewport.pt_stop()
        super().closeEvent(event)
