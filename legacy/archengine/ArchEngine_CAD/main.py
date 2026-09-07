#!/usr/bin/env python3
"""
Legible Studio - Architectural Design Application
Main entry point
"""
import sys
import traceback
from pathlib import Path

# Handle frozen (PyInstaller) vs development mode
def _get_app_dir() -> Path:
    """Get application directory for both frozen and dev modes."""
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS)
    return Path(__file__).parent

# Add the package directory to path for imports
_package_dir = _get_app_dir()
if str(_package_dir) not in sys.path:
    sys.path.insert(0, str(_package_dir))

# Global exception handler for frozen apps
def _exception_hook(exc_type, exc_value, exc_tb):
    """Handle uncaught exceptions - keep console open to see errors."""
    print("\n" + "=" * 60)
    print("CRASH REPORT - Legible Studio")
    print("=" * 60)
    traceback.print_exception(exc_type, exc_value, exc_tb)
    print("=" * 60)
    if getattr(sys, 'frozen', False):
        input("\nPress Enter to close...")
    sys.__excepthook__(exc_type, exc_value, exc_tb)

sys.excepthook = _exception_hook

# IMPORTANT: QtWebEngineWidgets must be imported BEFORE QApplication is created
# This is required for the embedded map widget to work
try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    print("[Main] QtWebEngineWidgets imported successfully")
except ImportError as e:
    print(f"[Main] QtWebEngineWidgets not available: {e}")

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from app.application import ArchEngineApplication
from app.config import Config


def main():
    # Required for QtWebEngine - must be set before QApplication creation
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

    # High DPI support
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    # Create Qt application
    app = QApplication(sys.argv)
    app.setApplicationName("Legible Studio")
    app.setOrganizationName("Legible Studios")
    app.setOrganizationDomain("legiblestudios.com")

    # Set default font
    font = QFont("Segoe UI", 9)
    app.setFont(font)

    # Load configuration
    config = Config()

    # Load stylesheet if exists
    style_path = _get_app_dir() / "resources" / "styles" / "archengine.qss"
    if style_path.exists():
        app.setStyleSheet(style_path.read_text())

    # Create main application window
    arch_app = ArchEngineApplication(config)
    arch_app.show()

    # Load project from command line or last opened, otherwise create new document
    if len(sys.argv) > 1:
        arch_app.open_project(Path(sys.argv[1]))
    elif config.last_project and Path(config.last_project).exists():
        arch_app.open_project(Path(config.last_project))
    else:
        # No file to open, create new document (triggers onboarding)
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(100, arch_app._on_new)

    # Run event loop
    sys.exit(app.exec())


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("\n" + "=" * 60)
        print("STARTUP CRASH - Legible Studio")
        print("=" * 60)
        traceback.print_exc()
        print("=" * 60)
        if getattr(sys, 'frozen', False):
            input("\nPress Enter to close...")
        raise
