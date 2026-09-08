#!/usr/bin/env python3
"""Debug launcher for ArchEngine CAD"""
import sys
import traceback
from pathlib import Path

# Add the package directory to path
sys.path.insert(0, str(Path(__file__).parent))

def main():
    try:
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore import Qt

        print("Creating QApplication...")
        sys.stdout.flush()

        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
        app = QApplication(sys.argv)

        print("Loading config...")
        sys.stdout.flush()
        from app.config import Config
        config = Config()

        print("Creating main window...")
        sys.stdout.flush()
        from app.application import ArchEngineApplication
        arch_app = ArchEngineApplication(config)

        print("Showing window...")
        sys.stdout.flush()
        arch_app.show()

        # Load project
        if len(sys.argv) > 1:
            print(f"Loading project: {sys.argv[1]}")
            sys.stdout.flush()
            arch_app.open_project(Path(sys.argv[1]))

        print("Starting event loop...")
        sys.stdout.flush()

        # Install exception hook
        def excepthook(exc_type, exc_value, exc_tb):
            print("=" * 50)
            print("UNHANDLED EXCEPTION:")
            traceback.print_exception(exc_type, exc_value, exc_tb)
            print("=" * 50)
            sys.stdout.flush()

        sys.excepthook = excepthook

        sys.exit(app.exec())

    except Exception as e:
        print("=" * 50)
        print(f"STARTUP ERROR: {e}")
        traceback.print_exc()
        print("=" * 50)
        sys.stdout.flush()
        sys.exit(1)

if __name__ == "__main__":
    main()
