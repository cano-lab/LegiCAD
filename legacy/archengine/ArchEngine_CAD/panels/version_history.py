"""
Version History Panel - Shows git-based version history of the document.
"""
from typing import Optional, List, Dict
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QTextEdit, QSplitter, QMessageBox, QFrame
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QColor

from core.document import ArchDocument
from core.events import event_bus


class VersionHistoryPanel(QWidget):
    """
    Panel showing version history with ability to view diffs and revert.
    """

    version_reverted = pyqtSignal(str)  # commit_hash

    def __init__(self, document: ArchDocument, parent=None):
        super().__init__(parent)
        self.document = document
        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        """Set up the panel UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)

        # Header
        header = QLabel("Version History")
        header.setStyleSheet("font-weight: bold; font-size: 12px;")
        layout.addWidget(header)

        # Refresh button
        btn_layout = QHBoxLayout()
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh_history)
        btn_layout.addWidget(self.refresh_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # Splitter for list and details
        splitter = QSplitter(Qt.Orientation.Vertical)

        # Version list
        self.version_list = QListWidget()
        self.version_list.setAlternatingRowColors(True)
        self.version_list.currentItemChanged.connect(self._on_version_selected)
        splitter.addWidget(self.version_list)

        # Details frame
        details_frame = QFrame()
        details_layout = QVBoxLayout(details_frame)
        details_layout.setContentsMargins(0, 5, 0, 0)

        # Changes summary
        self.changes_label = QLabel("Select a version to see details")
        self.changes_label.setWordWrap(True)
        self.changes_label.setStyleSheet("color: #888;")
        details_layout.addWidget(self.changes_label)

        # Diff view
        self.diff_view = QTextEdit()
        self.diff_view.setReadOnly(True)
        self.diff_view.setFont(QFont("Consolas", 9))
        self.diff_view.setMaximumHeight(150)
        self.diff_view.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                border: 1px solid #333;
            }
        """)
        details_layout.addWidget(self.diff_view)

        # Revert button
        self.revert_btn = QPushButton("Revert to This Version")
        self.revert_btn.setEnabled(False)
        self.revert_btn.clicked.connect(self._on_revert)
        self.revert_btn.setStyleSheet("""
            QPushButton {
                background-color: #c44;
                color: white;
                padding: 5px 15px;
                border: none;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #d55;
            }
            QPushButton:disabled {
                background-color: #666;
                color: #999;
            }
        """)
        details_layout.addWidget(self.revert_btn)

        splitter.addWidget(details_frame)
        splitter.setSizes([200, 100])

        layout.addWidget(splitter)

        # Status label
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #666; font-size: 10px;")
        layout.addWidget(self.status_label)

    def _connect_signals(self):
        """Connect to document events."""
        event_bus.document_loaded.connect(self._on_document_loaded)
        event_bus.document_saved.connect(self._on_document_saved)

    def _on_document_loaded(self, path: str):
        """Handle document loaded."""
        self.refresh_history()

    def _on_document_saved(self, path: str):
        """Handle document saved."""
        self.refresh_history()

    def refresh_history(self):
        """Refresh the version history list."""
        self.version_list.clear()
        self.diff_view.clear()
        self.changes_label.setText("Select a version to see details")
        self.revert_btn.setEnabled(False)

        history = self.document.get_history()

        if not history:
            self.status_label.setText("No version history available")
            return

        for i, entry in enumerate(history):
            # Format the date nicely
            try:
                dt = datetime.fromisoformat(entry['date'].replace(' ', 'T').split('+')[0])
                date_str = dt.strftime("%Y-%m-%d %H:%M")
            except:
                date_str = entry['date'][:16]

            # Create list item
            item = QListWidgetItem()

            # First entry is current version
            if i == 0:
                item.setText(f"[Current] {date_str}")
                item.setForeground(QColor("#4a9"))
            else:
                item.setText(f"{date_str} - {entry['message'][:30]}")

            item.setData(Qt.ItemDataRole.UserRole, entry)
            self.version_list.addItem(item)

        self.status_label.setText(f"{len(history)} versions")

    def _on_version_selected(self, current: QListWidgetItem, previous: QListWidgetItem):
        """Handle version selection."""
        if not current:
            return

        entry = current.data(Qt.ItemDataRole.UserRole)
        if not entry:
            return

        # Get version control
        vc = self.document._version_control
        if not vc:
            return

        # Get diff from this version to current (if not current version)
        history = self.document.get_history()
        is_current = (history and history[0]['hash'] == entry['hash'])

        if is_current:
            self.changes_label.setText("This is the current version")
            self.diff_view.clear()
            self.revert_btn.setEnabled(False)
        else:
            # Show what would change if we revert
            self.changes_label.setText(f"Version: {entry['hash'][:8]}\n{entry['message']}")

            # Get diff
            success, diff = vc._run_git('diff', '--stat', entry['hash'], 'HEAD', '--', vc.file_path.name)
            if success and diff.strip():
                self.diff_view.setPlainText(diff)
            else:
                self.diff_view.setPlainText("No differences")

            self.revert_btn.setEnabled(True)

    def _on_revert(self):
        """Revert to selected version."""
        current = self.version_list.currentItem()
        if not current:
            return

        entry = current.data(Qt.ItemDataRole.UserRole)
        if not entry:
            return

        # Confirm
        result = QMessageBox.question(
            self,
            "Revert Version",
            f"Revert to version from {entry['date'][:16]}?\n\n"
            f"This will create a new version with the reverted content.\n"
            f"Your current changes will be preserved in history.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if result != QMessageBox.StandardButton.Yes:
            return

        # Perform revert
        if self.document.revert_to_version(entry['hash']):
            self.status_label.setText(f"Reverted to {entry['hash'][:8]}")
            self.version_reverted.emit(entry['hash'])
            QMessageBox.information(
                self,
                "Reverted",
                f"Successfully reverted to version {entry['hash'][:8]}"
            )
            self.refresh_history()
        else:
            QMessageBox.warning(
                self,
                "Error",
                "Failed to revert to selected version"
            )
