"""
ArchEngine CAD Main Application Window
"""
from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import (
    QMainWindow, QDockWidget, QToolBar, QStatusBar,
    QFileDialog, QMessageBox, QWidget, QVBoxLayout,
    QSplitter, QLabel, QTabWidget, QDialog
)
from PyQt6.QtCore import Qt, QSettings, QTimer
from PyQt6.QtGui import QAction, QIcon, QKeySequence

from app.config import Config
from core.document import ArchDocument
from core.events import event_bus
from core.config import is_api_enabled, get_config

# Diagnostics
try:
    from core.diagnostics import get_diagnostics, log_memory, diag_log
    HAS_DIAGNOSTICS = True
except ImportError:
    HAS_DIAGNOSTICS = False
    def get_diagnostics(): return None
    def log_memory(label=""): pass
    def diag_log(msg): pass

# API backend support
try:
    from client import APIDocumentAdapter
    HAS_API_BACKEND = True
except ImportError:
    HAS_API_BACKEND = False

# API server process (for auto-start)
_api_server_process = None

# Sheet system imports
from sheets.sheet_registry import SheetRegistry
from panels.sheet_manager import SheetManagerPanel
from panels.chat_panel import ChatPanel
from panels.materials_panel import MaterialsPanel
from panels.onboarding_overlay import OnboardingOverlay
from panels.smart_panel_container import SmartPanelContainer
from generators.generator_service import GeneratorService
from dialogs.qbd_questionnaire import QBDQuestionnaireDialog
# Use simplified site dialog (interactive map + LiDAR only)
from dialogs.site_dialog_simple import SimpleSiteDialog as SiteDialog

# Viewport import (Vulkan only - UE5 viewport removed)
try:
    from viewport import VulkanViewportWidget, HAS_VULKAN_WIDGET
    HAS_VIEWPORT = HAS_VULKAN_WIDGET
except ImportError:
    HAS_VIEWPORT = False
    HAS_VULKAN_WIDGET = False

# Sync modules disabled - not needed with embedded viewport
HAS_LIVESYNC = False
HAS_VULKAN_SYNC = False


class ArchEngineApplication(QMainWindow):
    """
    Main application window.
    Central hub for all views and panels.
    """

    def __init__(self, config: Config, parent=None):
        super().__init__(parent)
        self.config = config

        # Initialize diagnostics
        if HAS_DIAGNOSTICS:
            diag = get_diagnostics()
            diag.log("Application starting")
            diag.log_memory("startup")
            diag.start_monitoring(interval_seconds=60)  # Log memory every 60s

        # Create document - use API backend if enabled
        if HAS_API_BACKEND and is_api_enabled():
            # Auto-start API server if not running
            self._ensure_api_server()

            self.document = APIDocumentAdapter(
                parent=self,
                use_api=True,
                workspace_id="default"
            )
            self._using_api = True
            print("[App] Using API backend for document storage")
        else:
            self.document = ArchDocument(self)
            self._using_api = False
            if is_api_enabled() and not HAS_API_BACKEND:
                print("[App] API backend requested but client module not available")

        # LiveSync server for UE5 connection - DISABLED (not used with embedded Vulkan viewport)
        self._livesync_server = None
        # LiveSync was causing performance issues and is not needed with embedded viewport
        # if HAS_LIVESYNC:
        #     try:
        #         self._livesync_server = get_livesync_server()
        #         self._livesync_server.start()
        #         self.document.document_changed.connect(self._on_document_changed_livesync)
        #     except Exception as e:
        #         print(f"[App] LiveSync init failed: {e}")

        # VulkanSync client - DISABLED (not needed with embedded Vulkan viewport)
        # VulkanSync was for standalone renderer process, embedded viewport uses DLL directly
        self._vulkan_sync = None
        # if HAS_VULKAN_SYNC:
        #     try:
        #         self._vulkan_sync = get_vulkan_sync_client()
        #         self._vulkan_sync.connected.connect(self._on_vulkan_connected)
        #         self._vulkan_sync.disconnected.connect(self._on_vulkan_disconnected)
        #         self.document.document_changed.connect(self._on_document_changed_vulkan)
        #         self._vulkan_sync.connect_to_renderer()
        #     except Exception as e:
        #         print(f"[App] VulkanSync init failed: {e}")

        # Throttle timer for 3D viewport updates (prevents lag during dragging)
        self._viewport_update_timer = QTimer(self)
        self._viewport_update_timer.setSingleShot(True)
        self._viewport_update_timer.setInterval(500)  # 500ms debounce - prevent rapid updates during dragging
        self._viewport_update_timer.timeout.connect(self._do_viewport_update)

        # Initialize sheet system
        self._sheet_registry = SheetRegistry(self)
        self._generator_service = GeneratorService(
            self._sheet_registry,
            lambda: self.document.to_dict(),
            self
        )

        self._setup_window()
        self._create_actions()
        self._create_menus()
        self._create_toolbars()
        self._create_status_bar()
        self._create_dock_widgets()
        self._create_central_widget()
        self._connect_signals()
        self._restore_state()
        # Don't show onboarding on startup - will show after new/load document

    def _setup_window(self):
        """Configure main window properties."""
        self.setWindowTitle("ArchEngine CAD")
        self.setMinimumSize(1200, 800)
        self.setDockNestingEnabled(True)

    def _show_onboarding_if_needed(self):
        """
        Show onboarding overlay if the current document hasn't completed it.

        Called after creating a new document or loading an existing one.
        """
        # TODO: Temporarily disabled - re-enable after fixing crashes
        return

        # Check if this document has completed onboarding
        if self.document.onboarding_completed:
            # Already completed onboarding for this document
            return

        # Create onboarding overlay with the chat panel
        if hasattr(self, 'onboarding_overlay') and self.onboarding_overlay:
            # Clean up any existing overlay
            self.onboarding_overlay.deleteLater()

        self.onboarding_overlay = OnboardingOverlay(self.chat_panel, self)

        # Connect signals
        # Disconnect any existing connections to avoid duplicates
        try:
            self.chat_panel.message_sent.disconnect(self.onboarding_overlay.increment_question)
        except TypeError:
            pass  # No existing connection

        self.chat_panel.message_sent.connect(self.onboarding_overlay.increment_question)
        self.onboarding_overlay.onboarding_complete.connect(self._on_onboarding_complete)

        # Hide the chat dock during onboarding
        self.chat_dock.hide()

        # Show the overlay after a short delay to ensure window is ready
        QTimer.singleShot(500, self.onboarding_overlay.show_overlay)

    def _on_onboarding_complete(self):
        """Handle onboarding completion."""
        # Mark onboarding as completed for this document
        self.document.complete_onboarding()

        # Show the chat dock in its normal position
        self.chat_dock.show()
        self.chat_dock.raise_()  # Bring to front in tabbed dock

        # Update status bar
        self.status_bar.showMessage("Onboarding complete! Design workspace ready.", 3000)

        # Clean up overlay
        if hasattr(self, 'onboarding_overlay') and self.onboarding_overlay:
            self.onboarding_overlay.deleteLater()
            self.onboarding_overlay = None

        # Note: Document will need to be saved to persist the onboarding completion flag
        if not self.document.file_path:
            # New document - prompt user to save to keep onboarding progress
            self.status_bar.showMessage(
                "Onboarding complete! Save your file to keep your progress.", 5000
            )

    def _on_reset_onboarding(self):
        """Reset onboarding for the current document."""
        if self.document.onboarding_completed:
            reply = QMessageBox.question(
                self,
                "Reset Onboarding",
                "This will reset the onboarding experience for this document. "
                "The welcome screen with 3 questions will show again.\n\nContinue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )

            if reply == QMessageBox.StandardButton.Yes:
                self.document.reset_onboarding()
                self._show_onboarding_if_needed()
                self.status_bar.showMessage(
                    "Onboarding reset for this document.",
                    3000
                )
        else:
            # Already in onboarding mode
            self.status_bar.showMessage(
                "Onboarding is already active for this document.",
                3000
            )

    def _create_actions(self):
        """Create all actions."""
        # File actions
        self.action_new = QAction("&New", self)
        self.action_new.setShortcut(QKeySequence.StandardKey.New)
        self.action_new.triggered.connect(self._on_new)

        self.action_open = QAction("&Open...", self)
        self.action_open.setShortcut(QKeySequence.StandardKey.Open)
        self.action_open.triggered.connect(self._on_open)

        self.action_save = QAction("&Save", self)
        self.action_save.setShortcut(QKeySequence.StandardKey.Save)
        self.action_save.triggered.connect(self._on_save)

        self.action_save_as = QAction("Save &As...", self)
        self.action_save_as.setShortcut(QKeySequence("Ctrl+Shift+S"))
        self.action_save_as.triggered.connect(self._on_save_as)

        # Export/Print actions
        self.action_export_pdf = QAction("Export to &PDF...", self)
        self.action_export_pdf.setShortcut(QKeySequence("Ctrl+P"))
        self.action_export_pdf.setStatusTip("Export current sheet to PDF")
        self.action_export_pdf.triggered.connect(self._on_export_pdf)

        self.action_export_all_pdf = QAction("Export All Sheets to PDF...", self)
        self.action_export_all_pdf.setStatusTip("Export all sheets to a single PDF")
        self.action_export_all_pdf.triggered.connect(self._on_export_all_pdf)

        self.action_print = QAction("&Print...", self)
        self.action_print.setShortcut(QKeySequence("Ctrl+Shift+P"))
        self.action_print.setStatusTip("Print current sheet")
        self.action_print.triggered.connect(self._on_print)

        self.action_define_site = QAction("&Define Site...", self)
        self.action_define_site.setStatusTip("Define site characteristics and fetch terrain elevation data")
        self.action_define_site.triggered.connect(self._on_define_site)

        self.action_exit = QAction("E&xit", self)
        self.action_exit.setShortcut(QKeySequence.StandardKey.Quit)
        self.action_exit.triggered.connect(self.close)

        # Edit actions
        self.action_undo = QAction("&Undo", self)
        self.action_undo.setShortcut(QKeySequence.StandardKey.Undo)
        self.action_undo.triggered.connect(self._on_undo)

        self.action_redo = QAction("&Redo", self)
        self.action_redo.setShortcut(QKeySequence.StandardKey.Redo)
        self.action_redo.triggered.connect(self._on_redo)

        self.action_delete = QAction("&Delete", self)
        self.action_delete.setShortcut(QKeySequence.StandardKey.Delete)
        self.action_delete.triggered.connect(self._on_delete)

        # View actions
        self.action_zoom_in = QAction("Zoom &In", self)
        self.action_zoom_in.setShortcut(QKeySequence.StandardKey.ZoomIn)

        self.action_zoom_out = QAction("Zoom &Out", self)
        self.action_zoom_out.setShortcut(QKeySequence.StandardKey.ZoomOut)

        self.action_zoom_fit = QAction("&Home (Zoom to Fit)", self)
        self.action_zoom_fit.setShortcut(QKeySequence("H"))

        self.action_reset_onboarding = QAction("Reset Onboarding...", self)
        self.action_reset_onboarding.triggered.connect(self._on_reset_onboarding)

        # Tool actions
        self.action_select = QAction("&Select", self)
        self.action_select.setCheckable(True)
        self.action_select.setChecked(True)
        self.action_select.setShortcut(QKeySequence("V"))

        self.action_wall = QAction("&Wall", self)
        self.action_wall.setCheckable(True)
        self.action_wall.setShortcut(QKeySequence("W"))

        self.action_door = QAction("&Door", self)
        self.action_door.setCheckable(True)
        self.action_door.setShortcut(QKeySequence("D"))

        self.action_window = QAction("W&indow", self)
        self.action_window.setCheckable(True)
        self.action_window.setShortcut(QKeySequence("I"))

        self.action_room = QAction("&Room", self)
        self.action_room.setCheckable(True)
        self.action_room.setShortcut(QKeySequence("R"))

        # Sheet actions
        self.action_regenerate_sheets = QAction("Regenerate Sheets", self)
        self.action_regenerate_sheets.setShortcut(QKeySequence("F4"))
        self.action_regenerate_sheets.triggered.connect(lambda: self._on_regenerate_sheet(""))

        # Toggle actions
        self.action_ortho = QAction("&Ortho", self)
        self.action_ortho.setCheckable(True)
        self.action_ortho.setChecked(self.config.ortho_mode)
        self.action_ortho.setShortcut(QKeySequence("F8"))
        self.action_ortho.triggered.connect(self._toggle_ortho)

        self.action_grid = QAction("&Grid", self)
        self.action_grid.setCheckable(True)
        self.action_grid.setChecked(self.config.grid_visible)
        self.action_grid.setShortcut(QKeySequence("F7"))
        self.action_grid.triggered.connect(self._toggle_grid)

        self.action_snap = QAction("&Snap", self)
        self.action_snap.setCheckable(True)
        self.action_snap.setChecked(self.config.snap_enabled)
        self.action_snap.setShortcut(QKeySequence("F9"))
        self.action_snap.triggered.connect(self._toggle_snap)

        # Individual snap type toggles
        self.action_snap_endpoint = QAction("&Endpoint", self)
        self.action_snap_endpoint.setCheckable(True)
        self.action_snap_endpoint.setChecked(self.config.snap_endpoint)
        self.action_snap_endpoint.triggered.connect(lambda: self._toggle_snap_type('endpoint'))

        self.action_snap_midpoint = QAction("&Midpoint", self)
        self.action_snap_midpoint.setCheckable(True)
        self.action_snap_midpoint.setChecked(self.config.snap_midpoint)
        self.action_snap_midpoint.triggered.connect(lambda: self._toggle_snap_type('midpoint'))

        self.action_snap_perpendicular = QAction("Per&pendicular", self)
        self.action_snap_perpendicular.setCheckable(True)
        self.action_snap_perpendicular.setChecked(self.config.snap_perpendicular)
        self.action_snap_perpendicular.triggered.connect(lambda: self._toggle_snap_type('perpendicular'))

        self.action_snap_parallel = QAction("Para&llel", self)
        self.action_snap_parallel.setCheckable(True)
        self.action_snap_parallel.setChecked(self.config.snap_parallel)
        self.action_snap_parallel.triggered.connect(lambda: self._toggle_snap_type('parallel'))

        self.action_snap_extension = QAction("E&xtension", self)
        self.action_snap_extension.setCheckable(True)
        self.action_snap_extension.setChecked(self.config.snap_extension)
        self.action_snap_extension.triggered.connect(lambda: self._toggle_snap_type('extension'))

        self.action_snap_angular = QAction("&Angular", self)
        self.action_snap_angular.setCheckable(True)
        self.action_snap_angular.setChecked(self.config.snap_angular)
        self.action_snap_angular.triggered.connect(lambda: self._toggle_snap_type('angular'))

        # Pin action for LLM workflow
        self.action_pin = QAction("Pin", self)
        self.action_pin.setCheckable(True)
        self.action_pin.setToolTip("Pin selected elements (protected from LLM changes)")
        self.action_pin.setShortcut(QKeySequence("P"))
        self.action_pin.toggled.connect(self._on_pin_toggle)

        # 3D Viewport actions (only if viewport module available)
        if HAS_VIEWPORT:
            self.action_reset_camera = QAction("&Reset Camera", self)
            self.action_reset_camera.setShortcut(QKeySequence("F5"))
            self.action_reset_camera.triggered.connect(self._reset_viewport_camera)

            self.action_toggle_3d_view = QAction("&3D Viewport", self)
            self.action_toggle_3d_view.setCheckable(True)
            self.action_toggle_3d_view.setChecked(True)  # Default on
            self.action_toggle_3d_view.setShortcut(QKeySequence("F6"))
            self.action_toggle_3d_view.triggered.connect(self._toggle_3d_view)

            self.action_3d_split = QAction("Split View (2D | 3D)", self)
            self.action_3d_split.setCheckable(True)
            self.action_3d_split.triggered.connect(self._toggle_split_view)

            # Render menu actions
            self.action_render_realistic = QAction("&Realistic", self)
            self.action_render_realistic.setCheckable(True)
            self.action_render_realistic.triggered.connect(lambda: self._set_material_style(0))

            self.action_render_clean = QAction("&Clean", self)
            self.action_render_clean.setCheckable(True)
            self.action_render_clean.setChecked(True)
            self.action_render_clean.triggered.connect(lambda: self._set_material_style(1))

            self.action_render_schematic = QAction("&Schematic", self)
            self.action_render_schematic.setCheckable(True)
            self.action_render_schematic.triggered.connect(lambda: self._set_material_style(2))

            self.action_render_blueprint = QAction("&Blueprint", self)
            self.action_render_blueprint.setCheckable(True)
            self.action_render_blueprint.triggered.connect(lambda: self._set_material_style(3))

            self.action_shadows = QAction("&Shadows", self)
            self.action_shadows.setCheckable(True)
            self.action_shadows.setChecked(True)
            self.action_shadows.triggered.connect(self._toggle_shadows)

            self.action_ssao = QAction("SS&AO", self)
            self.action_ssao.setCheckable(True)
            self.action_ssao.setChecked(True)
            self.action_ssao.triggered.connect(self._toggle_ssao)

            self.action_bloom = QAction("B&loom", self)
            self.action_bloom.setCheckable(True)
            self.action_bloom.setChecked(True)
            self.action_bloom.triggered.connect(self._toggle_bloom)

    def _create_menus(self):
        """Create menu bar."""
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("&File")
        file_menu.addAction(self.action_new)
        file_menu.addAction(self.action_open)
        file_menu.addSeparator()
        file_menu.addAction(self.action_save)
        file_menu.addAction(self.action_save_as)
        file_menu.addSeparator()
        file_menu.addAction(self.action_export_pdf)
        file_menu.addAction(self.action_export_all_pdf)
        file_menu.addAction(self.action_print)
        file_menu.addSeparator()
        file_menu.addAction(self.action_define_site)
        file_menu.addSeparator()
        file_menu.addAction(self.action_exit)

        # Edit menu
        edit_menu = menubar.addMenu("&Edit")
        edit_menu.addAction(self.action_undo)
        edit_menu.addAction(self.action_redo)
        edit_menu.addSeparator()
        edit_menu.addAction(self.action_delete)

        # View menu
        view_menu = menubar.addMenu("&View")
        view_menu.addAction(self.action_zoom_in)
        view_menu.addAction(self.action_zoom_out)
        view_menu.addAction(self.action_zoom_fit)
        view_menu.addSeparator()
        view_menu.addAction(self.action_grid)
        view_menu.addSeparator()
        view_menu.addAction(self.action_regenerate_sheets)
        view_menu.addSeparator()
        view_menu.addAction(self.action_reset_onboarding)

        # Draw menu
        draw_menu = menubar.addMenu("&Draw")
        draw_menu.addAction(self.action_wall)
        draw_menu.addAction(self.action_door)
        draw_menu.addAction(self.action_window)
        draw_menu.addAction(self.action_room)

        # Design menu
        design_menu = menubar.addMenu("&Design")
        self.action_solver_comparison = QAction("Compare &Solvers...", self)
        self.action_solver_comparison.setShortcut(QKeySequence("Ctrl+Shift+R"))
        self.action_solver_comparison.setStatusTip("Compare room layout algorithms")
        self.action_solver_comparison.triggered.connect(self._on_solver_comparison)
        design_menu.addAction(self.action_solver_comparison)

        # Tools menu
        tools_menu = menubar.addMenu("&Tools")
        tools_menu.addAction(self.action_select)

        # Snap menu
        snap_menu = menubar.addMenu("&Snap")
        snap_menu.addAction(self.action_snap)
        snap_menu.addSeparator()
        snap_menu.addAction(self.action_snap_endpoint)
        snap_menu.addAction(self.action_snap_midpoint)
        snap_menu.addAction(self.action_snap_extension)
        snap_menu.addSeparator()
        snap_menu.addAction(self.action_snap_perpendicular)
        snap_menu.addAction(self.action_snap_parallel)
        snap_menu.addAction(self.action_snap_angular)

        # Window menu
        self.window_menu = menubar.addMenu("&Window")

        # 3D menu (only if viewport module available)
        if HAS_VIEWPORT:
            view_3d_menu = menubar.addMenu("&3D")
            view_3d_menu.addAction(self.action_reset_camera)
            view_3d_menu.addSeparator()
            view_3d_menu.addAction(self.action_toggle_3d_view)
            view_3d_menu.addAction(self.action_3d_split)

            # Render menu
            render_menu = menubar.addMenu("&Render")

            # Style submenu
            style_menu = render_menu.addMenu("Material &Style")
            style_menu.addAction(self.action_render_realistic)
            style_menu.addAction(self.action_render_clean)
            style_menu.addAction(self.action_render_schematic)
            style_menu.addAction(self.action_render_blueprint)

            render_menu.addSeparator()

            # Lighting submenu
            lighting_menu = render_menu.addMenu("&Lighting")
            lighting_menu.addAction(self.action_shadows)

            # Post-processing submenu
            postproc_menu = render_menu.addMenu("&Post-Processing")
            postproc_menu.addAction(self.action_ssao)
            postproc_menu.addAction(self.action_bloom)

            render_menu.addSeparator()

            # Quick access to panels
            self.action_show_3d_controls = QAction("Show 3D &Controls Panel", self)
            self.action_show_3d_controls.triggered.connect(lambda: self.viewport_panel_dock.show() and self.viewport_panel_dock.raise_())
            render_menu.addAction(self.action_show_3d_controls)

            self.action_show_materials = QAction("Show &Materials Panel", self)
            self.action_show_materials.triggered.connect(lambda: self.materials_dock.show() and self.materials_dock.raise_())
            render_menu.addAction(self.action_show_materials)

            render_menu.addSeparator()

            # Path Tracer for high-quality offline renders
            self.action_path_tracer = QAction("&Path Traced Render...", self)
            self.action_path_tracer.setToolTip("Render high-quality image using path tracing")
            self.action_path_tracer.triggered.connect(self._show_path_tracer_dialog)
            render_menu.addAction(self.action_path_tracer)

        # Debug/Diagnostics menu
        if HAS_DIAGNOSTICS:
            debug_menu = menubar.addMenu("&Debug")

            self.action_diag_memory = QAction("Log &Memory Snapshot", self)
            self.action_diag_memory.triggered.connect(self._diag_log_memory)
            debug_menu.addAction(self.action_diag_memory)

            self.action_diag_gc = QAction("Force &Garbage Collection", self)
            self.action_diag_gc.triggered.connect(self._diag_gc_collect)
            debug_menu.addAction(self.action_diag_gc)

            self.action_diag_leaks = QAction("Find Memory &Leaks", self)
            self.action_diag_leaks.triggered.connect(self._diag_find_leaks)
            debug_menu.addAction(self.action_diag_leaks)

            debug_menu.addSeparator()

            self.action_diag_report = QAction("Generate &Report", self)
            self.action_diag_report.triggered.connect(self._diag_generate_report)
            debug_menu.addAction(self.action_diag_report)

            self.action_diag_save_report = QAction("&Save Report to File", self)
            self.action_diag_save_report.triggered.connect(self._diag_save_report)
            debug_menu.addAction(self.action_diag_save_report)

    def _create_toolbars(self):
        """Create toolbars."""
        # Main toolbar
        main_toolbar = QToolBar("Main")
        main_toolbar.setObjectName("main_toolbar")
        main_toolbar.addAction(self.action_new)
        main_toolbar.addAction(self.action_open)
        main_toolbar.addAction(self.action_save)
        main_toolbar.addSeparator()
        main_toolbar.addAction(self.action_undo)
        main_toolbar.addAction(self.action_redo)
        main_toolbar.addSeparator()
        main_toolbar.addAction(self.action_regenerate_sheets)
        self.addToolBar(main_toolbar)

        # Tools toolbar
        tools_toolbar = QToolBar("Tools")
        tools_toolbar.setObjectName("tools_toolbar")
        tools_toolbar.addAction(self.action_select)
        tools_toolbar.addAction(self.action_wall)
        tools_toolbar.addAction(self.action_door)
        tools_toolbar.addAction(self.action_window)
        tools_toolbar.addAction(self.action_room)
        self.addToolBar(tools_toolbar)

        # Options toolbar
        options_toolbar = QToolBar("Options")
        options_toolbar.setObjectName("options_toolbar")
        options_toolbar.addAction(self.action_ortho)
        options_toolbar.addAction(self.action_grid)
        options_toolbar.addAction(self.action_snap)
        options_toolbar.addSeparator()
        options_toolbar.addAction(self.action_pin)
        self.addToolBar(options_toolbar)

        # 3D Viewport toolbar (only if viewport module available)
        if HAS_VIEWPORT:
            viewport_toolbar = QToolBar("3D Viewport")
            viewport_toolbar.setObjectName("viewport_toolbar")
            viewport_toolbar.addAction(self.action_reset_camera)
            viewport_toolbar.addAction(self.action_toggle_3d_view)
            viewport_toolbar.addAction(self.action_3d_split)
            self.addToolBar(viewport_toolbar)

    def _create_status_bar(self):
        """Create status bar."""
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

        # API status indicator
        if self._using_api:
            self._api_status_label = QLabel()
            self._api_status_label.setStyleSheet("padding: 0 8px;")
            self.status_bar.addPermanentWidget(self._api_status_label)
            self._update_api_status()

            # Connect to connection changes
            if hasattr(self.document, 'connection_changed'):
                self.document.connection_changed.connect(self._update_api_status)
            if hasattr(self.document, 'sync_completed'):
                self.document.sync_completed.connect(self._on_sync_completed)

        # Connect status message event
        event_bus.status_message.connect(self._show_status_message)

    def _create_dock_widgets(self):
        """Create dockable panels."""
        from panels.version_history import VersionHistoryPanel
        from panels.properties_panel import PropertiesPanel
        from panels.viewport_panel import ViewportPanel

        # Project Browser dock (left side)
        self.project_dock = QDockWidget("Project Browser", self)
        self.project_dock.setObjectName("project_dock")
        self.project_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea |
            Qt.DockWidgetArea.RightDockWidgetArea
        )
        # Placeholder widget for now
        project_widget = QWidget()
        project_widget.setMinimumWidth(200)
        self.project_dock.setWidget(project_widget)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.project_dock)
        self.window_menu.addAction(self.project_dock.toggleViewAction())

        # Properties dock (right side)
        self.properties_dock = QDockWidget("Properties", self)
        self.properties_dock.setObjectName("properties_dock")
        self.properties_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea |
            Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.properties_panel = PropertiesPanel(self.document)
        self.properties_panel.setMinimumWidth(250)
        self.properties_dock.setWidget(self.properties_panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.properties_dock)
        self.window_menu.addAction(self.properties_dock.toggleViewAction())

        # Sheet Manager dock (left side, tabbed with project browser)
        self.sheets_dock = QDockWidget("Sheets", self)
        self.sheets_dock.setObjectName("sheets_dock")
        self.sheets_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea |
            Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.sheet_manager = SheetManagerPanel(self._sheet_registry, self)
        self.sheet_manager.setMinimumWidth(200)
        self.sheet_manager.regenerate_requested.connect(self._on_regenerate_sheet)
        self.sheet_manager.sheet_double_clicked.connect(self._on_open_sheet)
        self.sheet_manager.preset_sheet_created.connect(self._on_preset_sheet_created)
        self.sheets_dock.setWidget(self.sheet_manager)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.sheets_dock)
        self.tabifyDockWidget(self.project_dock, self.sheets_dock)
        self.sheets_dock.raise_()  # Show sheets dock by default
        self.window_menu.addAction(self.sheets_dock.toggleViewAction())

        # Connect generator service signals
        self._generator_service.generation_started.connect(
            lambda sid: self.status_bar.showMessage(f"Generating {sid}...")
        )
        self._generator_service.generation_completed.connect(
            lambda sid: self.status_bar.showMessage(f"Generated {sid}", 3000)
        )
        self._generator_service.generation_failed.connect(
            lambda sid, err: self.status_bar.showMessage(f"Generation failed: {err}", 5000)
        )
        self._generator_service.progress_updated.connect(self.sheet_manager.show_progress)
        self._generator_service.all_generation_completed.connect(self.sheet_manager.hide_progress)

        # 3D Viewport setup (actual widget created in _create_central_widget)
        if HAS_VIEWPORT:
            # Connect document changes to viewport
            self.document.document_changed.connect(self._on_document_changed_viewport)

            # Create viewport panel (for gravity/LOD/section controls)
            self.viewport_panel = ViewportPanel()

            # Create dock for viewport panel
            self.viewport_panel_dock = QDockWidget("3D Controls", self)
            self.viewport_panel_dock.setObjectName("viewport_panel_dock")
            self.viewport_panel_dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
            self.viewport_panel_dock.setFeatures(
                QDockWidget.DockWidgetFeature.DockWidgetMovable |
                QDockWidget.DockWidgetFeature.DockWidgetFloatable |
                QDockWidget.DockWidgetFeature.DockWidgetClosable
            )
            self.viewport_panel_dock.setWidget(self.viewport_panel)
            self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.viewport_panel_dock)
            self.window_menu.addAction(self.viewport_panel_dock.toggleViewAction())

            # Create materials panel dock
            self.materials_panel = MaterialsPanel()
            self.materials_dock = QDockWidget("Materials", self)
            self.materials_dock.setObjectName("materials_dock")
            self.materials_dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
            self.materials_dock.setFeatures(
                QDockWidget.DockWidgetFeature.DockWidgetMovable |
                QDockWidget.DockWidgetFeature.DockWidgetFloatable |
                QDockWidget.DockWidgetFeature.DockWidgetClosable
            )
            self.materials_dock.setWidget(self.materials_panel)
            self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.materials_dock)
            self.tabifyDockWidget(self.viewport_panel_dock, self.materials_dock)
            self.viewport_panel_dock.raise_()  # Show 3D Controls by default
            self.window_menu.addAction(self.materials_dock.toggleViewAction())

        # =================================================================
        # Version History Dock
        # ==================================================================
        self.history_dock = QDockWidget("Version History", self)
        self.history_dock.setObjectName("history_dock")
        self.history_dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.history_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable |
            QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        self.history_panel = VersionHistoryPanel(self.document)
        self.history_panel.setMinimumWidth(250)
        self.history_dock.setWidget(self.history_panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.history_dock)
        # Tab it with properties dock
        self.tabifyDockWidget(self.properties_dock, self.history_dock)
        self.window_menu.addAction(self.history_dock.toggleViewAction())

        # =================================================================
        # Chat Dock - Design conversation (always visible)
        # ==================================================================
        # Chat panel dock (right side, tabbed with properties)
        self.chat_dock = QDockWidget("Design Chat", self)
        self.chat_dock.setObjectName("chat_dock")
        self.chat_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea |
            Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.chat_panel = ChatPanel(self.document)
        self.chat_panel.setMinimumWidth(280)
        self.chat_panel.message_sent.connect(self._on_chat_message)
        self.chat_panel.schema_updated.connect(self._on_schema_updated)
        self.chat_dock.setWidget(self.chat_panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.chat_dock)
        # Tab it with properties dock
        self.tabifyDockWidget(self.properties_dock, self.chat_dock)
        self.window_menu.addAction(self.chat_dock.toggleViewAction())

        # Smart Panel Container (context-aware panels that show/hide based on workflow/LOD)
        self.smart_panel_dock = QDockWidget("Smart Panels", self)
        self.smart_panel_dock.setObjectName("smart_panel_dock")
        self.smart_panel_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea |
            Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.smart_panel_container = SmartPanelContainer(self)
        self.smart_panel_container.setMinimumWidth(280)
        self.smart_panel_dock.setWidget(self.smart_panel_container)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.smart_panel_dock)
        # Tab it with chat dock
        self.tabifyDockWidget(self.chat_dock, self.smart_panel_dock)
        self.window_menu.addAction(self.smart_panel_dock.toggleViewAction())

        # 3D Viewport dock (Vulkan renderer)
        if HAS_VIEWPORT:
            self.viewport_dock = QDockWidget("3D Viewport", self)
            self.viewport_dock.setObjectName("viewport_dock")
            self.viewport_dock.setAllowedAreas(
                Qt.DockWidgetArea.LeftDockWidgetArea |
                Qt.DockWidgetArea.RightDockWidgetArea |
                Qt.DockWidgetArea.BottomDockWidgetArea
            )
            # Create the Vulkan viewport widget
            self.viewport_3d = VulkanViewportWidget()
            self.viewport_3d.setMinimumSize(400, 300)
            self.viewport_3d.initialized.connect(self._on_viewport_initialized)
            self.viewport_3d.load_complete.connect(self._on_viewport_load_complete)
            self.viewport_3d.error_occurred.connect(self._on_viewport_error)
            self.viewport_dock.setWidget(self.viewport_3d)
            self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.viewport_dock)
            self.viewport_dock.show()  # Show 3D viewport by default
            self.window_menu.addAction(self.viewport_dock.toggleViewAction())

            # Connect document changes to viewport
            self.document.document_changed.connect(self._on_document_changed_viewport)

            # 3D Controls dock (tabbed with properties)
            self.viewport_controls_dock = QDockWidget("3D Controls", self)
            self.viewport_controls_dock.setObjectName("viewport_controls_dock")
            self.viewport_controls_dock.setAllowedAreas(
                Qt.DockWidgetArea.LeftDockWidgetArea |
                Qt.DockWidgetArea.RightDockWidgetArea
            )
            self.viewport_panel = ViewportPanel()
            self.viewport_panel.setMinimumWidth(250)
            self.viewport_controls_dock.setWidget(self.viewport_panel)
            self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.viewport_controls_dock)
            # Tab it with properties dock
            self.tabifyDockWidget(self.properties_dock, self.viewport_controls_dock)
            self.window_menu.addAction(self.viewport_controls_dock.toggleViewAction())

    def _create_central_widget(self):
        """Create the central tabbed widget with plan view and sheet views."""
        from views.plan_view import PlanView
        from tools.tool_manager import ToolManager
        from tools.base_tool import ToolType
        from tools.wall_tool import WallTool
        from tools.door_tool import DoorTool
        from tools.window_tool import WindowTool
        from tools.room_tool import RoomTool

        # Create central tab widget
        self.central_tabs = QTabWidget(self)
        self.central_tabs.setTabsClosable(True)
        self.central_tabs.setMovable(True)
        self.central_tabs.tabCloseRequested.connect(self._on_tab_close_requested)

        # Create the main plan view
        self.plan_view = PlanView(self.document, self.config, self)

        # Create split view container (for 2D | 3D side-by-side mode)
        self._split_mode = False
        self._split_viewport: Optional[VulkanViewportWidget] = None

        # Disable split viewport for now to simplify (use dock viewport only)
        self.central_tabs.addTab(self.plan_view, "Editor")

        # Don't allow closing the Editor tab
        self.central_tabs.tabBar().setTabButton(0, self.central_tabs.tabBar().ButtonPosition.RightSide, None)

        self.setCentralWidget(self.central_tabs)

        # Track open sheet tabs
        self._sheet_tabs: dict = {}  # sheet_id -> tab index

        # Create tool manager
        self.tool_manager = ToolManager(self.plan_view, self.document, self)
        self.plan_view.set_tool_manager(self.tool_manager)

        # Register additional tools
        wall_tool = WallTool(self.plan_view, self.document, self.config)
        self.tool_manager.register_tool(ToolType.WALL, wall_tool)

        door_tool = DoorTool(self.plan_view, self.document, self.config)
        self.tool_manager.register_tool(ToolType.DOOR, door_tool)

        window_tool = WindowTool(self.plan_view, self.document, self.config)
        self.tool_manager.register_tool(ToolType.WINDOW, window_tool)

        room_tool = RoomTool(self.plan_view, self.document, self.config)
        self.tool_manager.register_tool(ToolType.ROOM, room_tool)

        # Connect tool actions
        self.action_select.triggered.connect(lambda: self._set_tool(ToolType.SELECT))
        self.action_wall.triggered.connect(lambda: self._set_tool(ToolType.WALL))
        self.action_door.triggered.connect(lambda: self._set_tool(ToolType.DOOR))
        self.action_window.triggered.connect(lambda: self._set_tool(ToolType.WINDOW))
        self.action_room.triggered.connect(lambda: self._set_tool(ToolType.ROOM))

        # Connect zoom actions
        self.action_zoom_in.triggered.connect(self.plan_view.zoom_in)
        self.action_zoom_out.triggered.connect(self.plan_view.zoom_out)
        self.action_zoom_fit.triggered.connect(self.plan_view.zoom_fit)

        # Update tool action states when tool changes
        self.tool_manager.tool_changed.connect(self._on_tool_changed)

    def _set_tool(self, tool_type):
        """Switch to a tool."""
        from tools.base_tool import ToolType
        self.tool_manager.set_tool(tool_type)

    def _on_tool_changed(self, tool_name: str):
        """Update action check states when tool changes."""
        self.action_select.setChecked(tool_name == "SelectTool")
        self.action_wall.setChecked(tool_name == "WallTool")
        self.action_door.setChecked(tool_name == "DoorTool")
        self.action_window.setChecked(tool_name == "WindowTool")
        self.action_room.setChecked(tool_name == "RoomTool")

    def _connect_signals(self):
        """Connect document and event signals."""
        self.document.document_changed.connect(self._update_title)
        event_bus.document_loaded.connect(self._on_document_loaded)
        event_bus.document_modified.connect(self._on_document_modified)
        event_bus.selection_changed.connect(self._on_selection_changed)

        # Connect generator service to document changes (disabled by default to avoid blocking)
        # Users can enable auto-regenerate in the sheets panel
        self._sheet_registry.auto_regenerate = False
        self._generator_service.connect_to_document(self.document)

    def _on_selection_changed(self, selected_items):
        """Handle selection change - update pin button state, smart panels, and 3D viewport."""
        # Sync to 3D viewport (if available and not already syncing)
        if HAS_VIEWPORT and hasattr(self, 'viewport_3d') and not getattr(self, '_syncing_selection', False):
            self._syncing_selection = True
            try:
                if selected_items:
                    # Get first selected item and sync to 3D
                    item = selected_items[0]
                    item_type = type(item).__name__
                    if item_type == "WallItem" and hasattr(item, 'wall'):
                        idx = item.wall.index
                        if self.viewport_3d.is_initialized:
                            self.viewport_3d.select_element(idx)
                    elif item_type == "RoomItem" and hasattr(item, 'room'):
                        # Rooms are after walls in the element list
                        room_ids = list(self.document._rooms.keys())
                        if item.room.id in room_ids:
                            idx = len(self.document.walls) + room_ids.index(item.room.id)
                            if self.viewport_3d.is_initialized:
                                self.viewport_3d.select_element(idx)
                else:
                    # Clear 3D selection
                    if self.viewport_3d.is_initialized:
                        self.viewport_3d.select_element(-1)
            finally:
                self._syncing_selection = False

        # Update smart panel container with selection info
        if hasattr(self, 'smart_panel_container'):
            element_ids = []
            element_types = []
            for item in selected_items:
                item_type = type(item).__name__
                # Extract element ID and type from graphics items
                if item_type == "WallItem" and hasattr(item, 'wall'):
                    element_ids.append(str(id(item.wall)))
                    element_types.append("wall")
                elif item_type == "DoorItem" and hasattr(item, 'door'):
                    element_ids.append(str(id(item.door)))
                    element_types.append("door")
                elif item_type == "WindowItem" and hasattr(item, 'window'):
                    element_ids.append(str(id(item.window)))
                    element_types.append("window")
                elif item_type == "RoomItem" and hasattr(item, 'room'):
                    element_ids.append(str(id(item.room)))
                    element_types.append("room")
            self.smart_panel_container.update_selection(element_ids, element_types)

        if not selected_items:
            self.action_pin.setChecked(False)
            self.action_pin.setEnabled(False)
            return

        self.action_pin.setEnabled(True)

        # Check if any selected item is pinned
        any_pinned = False
        for item in selected_items:
            item_type = type(item).__name__
            if item_type == "WallItem" and hasattr(item, 'wall') and item.wall.is_pinned:
                any_pinned = True
                break
            elif item_type == "DoorItem" and hasattr(item, 'door') and item.door.is_pinned:
                any_pinned = True
                break
            elif item_type == "WindowItem" and hasattr(item, 'window') and item.window.is_pinned:
                any_pinned = True
                break
            elif item_type == "RoomItem" and hasattr(item, 'room') and item.room.is_pinned:
                any_pinned = True
                break

        # Block signal to prevent triggering toggle while updating
        self.action_pin.blockSignals(True)
        self.action_pin.setChecked(any_pinned)
        self.action_pin.blockSignals(False)

    def _on_3d_element_selected(self, element_index: int):
        """Handle selection from 3D viewport - sync to 2D plan view."""
        if getattr(self, '_syncing_selection', False):
            return  # Prevent infinite loop

        if not hasattr(self, 'plan_view'):
            return

        self._syncing_selection = True
        try:
            # Clear 2D selection first
            self.plan_view.scene.clearSelection()

            if element_index < 0:
                return  # Deselection

            # Determine which element type based on index ranges
            # Order: walls, rooms, doors, windows
            walls = self.document.walls
            rooms = list(self.document._rooms.values())
            doors = self.document.doors
            windows = self.document.windows

            offset = 0

            # Check if wall
            if element_index < offset + len(walls):
                wall_idx = element_index - offset
                # Find and select wall item in 2D
                for wall_item in self.plan_view._wall_items:
                    if hasattr(wall_item, 'wall') and wall_item.wall.index == wall_idx:
                        wall_item.setSelected(True)
                        # Scroll to show selected item
                        self.plan_view.centerOn(wall_item)
                        break
                return

            offset += len(walls)

            # Check if room
            if element_index < offset + len(rooms):
                room_idx = element_index - offset
                if room_idx < len(rooms):
                    room = rooms[room_idx]
                    # Find and select room item in 2D
                    for room_item in self.plan_view._room_items:
                        if hasattr(room_item, 'room') and room_item.room.id == room.id:
                            room_item.setSelected(True)
                            self.plan_view.centerOn(room_item)
                            break
                return

            offset += len(rooms)

            # Check if door
            if element_index < offset + len(doors):
                door_idx = element_index - offset
                # Find and select door item in 2D
                for door_item in self.plan_view._door_items:
                    if hasattr(door_item, 'door') and door_item.door.index == door_idx:
                        door_item.setSelected(True)
                        self.plan_view.centerOn(door_item)
                        break
                return

            offset += len(doors)

            # Check if window
            if element_index < offset + len(windows):
                window_idx = element_index - offset
                # Find and select window item in 2D
                for window_item in self.plan_view._window_items:
                    if hasattr(window_item, 'window') and window_item.window.index == window_idx:
                        window_item.setSelected(True)
                        self.plan_view.centerOn(window_item)
                        break

        finally:
            self._syncing_selection = False

    def _on_material_assigned(self, element_type: str, material_id: str):
        """Handle material assignment from materials panel.

        Updates materials in the document and reloads the 3D view.
        """
        print(f"[App] Applying material '{material_id}' to {element_type}")

        changed = False

        if element_type == "selection":
            # Apply to currently selected walls in plan view
            count = 0
            for item in self.plan_view.scene().selectedItems():
                if hasattr(item, 'wall') and hasattr(item.wall, 'index'):
                    wall_idx = item.wall.index
                    if wall_idx < len(self.document._walls):
                        self.document._walls[wall_idx].material_override = material_id
                        count += 1
                        changed = True
            if count > 0:
                print(f"[App] Applied material to {count} selected walls")
            else:
                print("[App] No walls selected")

        elif element_type == "wall":
            # Apply to all walls
            for wall in self.document._walls:
                wall.material_override = material_id
            print(f"[App] Applied material to {len(self.document._walls)} walls")
            changed = True

        elif element_type == "roof":
            # Apply to all roofs via document's roof material setting
            for roof in self.document._roofs:
                roof.material = material_id
            print(f"[App] Applied material to {len(self.document._roofs)} roofs")
            changed = True

        elif element_type == "floor":
            # Apply to all floors
            for floor in self.document._floors:
                floor.material = material_id
            print(f"[App] Applied material to {len(self.document._floors)} floors")
            changed = True

        # Reload the 3D viewport to show updated materials
        if changed:
            print("[App] Reloading viewport with updated materials...")
            # Update embedded viewport
            self._do_viewport_update()
            # Also update VulkanSync if connected
            if self._vulkan_sync and self._vulkan_sync.is_connected:
                self._on_document_changed_vulkan()

    def _on_tool_changed(self, tool_name: str):
        """Handle tool change - update smart panels task state."""
        if hasattr(self, 'smart_panel_container'):
            # Map tool names to task types
            # Tools like 'wall', 'door', 'window' indicate active drawing/placement
            # The 'select' tool means idle state
            task_map = {
                'select': 'idle',
                'wall': 'dragging_wall',
                'door': 'dragging_opening',
                'window': 'dragging_opening',
                'room': 'dragging_blob',
            }
            task = task_map.get(tool_name.lower(), 'idle')
            self.smart_panel_container.update_task(task)

    def _restore_state(self):
        """Restore window geometry and state."""
        settings = QSettings("ArchEngine", "CAD")
        geometry = settings.value("geometry")
        state = settings.value("state")

        if geometry:
            self.restoreGeometry(geometry)
        if state:
            self.restoreState(state)

    def _save_state(self):
        """Save window geometry and state."""
        settings = QSettings("ArchEngine", "CAD")
        settings.setValue("geometry", self.saveGeometry())
        settings.setValue("state", self.saveState())

    # =========================================================================
    # File Operations
    # =========================================================================

    def _on_new(self):
        """Create new document with site definition and building design."""
        if not self._check_save():
            return

        # Show site dialog first to get location and terrain data
        from dialogs.site_dialog_simple import show_site_dialog

        site_data = show_site_dialog(self)

        if site_data:
            # User completed site dialog - now show QBD questionnaire
            self._pending_site_data = site_data
            self._show_qbd_after_site()
        else:
            # User cancelled - still create empty document
            self.document.new()

    def _show_qbd_after_site(self):
        """Show QBD questionnaire after site is defined."""
        from dialogs.qbd_questionnaire import QBDQuestionnaireDialog

        dialog = QBDQuestionnaireDialog(self)
        dialog.generate_building.connect(self._on_generate_from_qbd_algebra)
        result = dialog.exec()

        if result != QDialog.DialogCode.Accepted:
            # User cancelled questionnaire - create document with just terrain
            self._create_document_with_site(self._pending_site_data, None)

    def _show_path_tracer_dialog(self):
        """Show path tracer render dialog."""
        if not hasattr(self, 'viewport_3d') or not self.viewport_3d.is_initialized:
            QMessageBox.warning(self, "3D Viewport Required",
                "The 3D viewport must be initialized before using the path tracer.")
            return

        from dialogs.path_tracer_dialog import PathTracerDialog
        dialog = PathTracerDialog(self.viewport_3d, self)
        dialog.exec()

    def _on_generate_from_qbd_algebra(self, answers: dict):
        """Generate building using QBD algebra from questionnaire answers."""
        site_data = getattr(self, '_pending_site_data', None)
        self._create_document_with_site(site_data, answers)

    def _create_document_with_site(self, site_data: dict, qbd_answers: dict = None):
        """Create document with site data and optionally generate building from QBD."""
        self.document.new()

        # Add site data including terrain mesh and building origin
        if site_data:
            self.document._data['site'] = site_data

            # Copy terrain generation settings for C++ terrain generation
            if 'terrain_generation_settings' in site_data:
                self.document._data['terrain_generation_settings'] = site_data['terrain_generation_settings']
                print(f"[App] C++ terrain generation enabled: {site_data['terrain_generation_settings']}")

            # Copy google_maps data (contains elevation_grid for terrain)
            if 'google_maps' in site_data:
                self.document._data['google_maps'] = site_data['google_maps']
                elev_grid = site_data['google_maps'].get('elevation_grid', {})
                print(f"[App] Elevation data: {len(elev_grid)} points")

            # Copy property dimensions
            if 'property_width_ft' in site_data:
                self.document._data['property_width_ft'] = site_data['property_width_ft']
            if 'property_depth_ft' in site_data:
                self.document._data['property_depth_ft'] = site_data['property_depth_ft']

            # Handle terrain: either use pre-computed mesh or let C++ generate from elevation data
            terrain_settings = site_data.get('terrain_generation_settings', {})
            use_cpp = terrain_settings.get('use_cpp_generation', False)
            has_elevation = bool(site_data.get('google_maps', {}).get('elevation_grid'))

            if use_cpp and has_elevation:
                # C++ will generate terrain - remove test terrain so viewport uses C++
                if 'terrain_mesh' in self.document._data:
                    del self.document._data['terrain_mesh']
                    print("[App] Removed test terrain - C++ will generate from LiDAR data")
            elif 'terrain_mesh' in site_data and site_data['terrain_mesh'] is not None:
                self.document._data['terrain_mesh'] = site_data['terrain_mesh']
                print(f"[App] New document with site terrain: {site_data['terrain_mesh']['vertex_count']} vertices")

            if 'building_origin' in site_data:
                self.document._data['building_origin'] = site_data['building_origin']
                origin = site_data['building_origin']
                print(f"[App] Building origin: ({origin.get('x_ft', 0):.0f}', {origin.get('z_ft', 0):.0f}') rotation={origin.get('rotation_deg', 0):.0f}°")

        # Generate building from QBD algebra if answers provided
        if qbd_answers:
            self._generate_building_from_qbd_algebra(qbd_answers, site_data)

        # Update 3D viewport
        if HAS_VIEWPORT and self.viewport_3d:
            # Debug: Check terrain data
            if 'terrain_mesh' in self.document._data:
                mesh = self.document._data['terrain_mesh']
                print(f"[App] Passing terrain_mesh to viewport: {mesh.get('vertex_count', 0)} vertices, {mesh.get('triangle_count', 0)} triangles")
            elif 'google_maps' in self.document._data and 'elevation_grid' in self.document._data['google_maps']:
                print(f"[App] Passing elevation_grid to viewport: {len(self.document._data['google_maps']['elevation_grid'])} points")
            else:
                print("[App] No terrain data in document")
            self.viewport_3d.load_json(self.document._data)
            self.viewport_3d.reset_camera()
            print("[App] 3D viewport updated")

    def _generate_building_from_qbd_algebra(self, answers: dict, site_data: dict = None):
        """Generate building layout using QBD algebra system or CLI solver."""
        # Check if user selected a specific solver
        solver = answers.get('solver', 'qbd')
        print(f"[App] Using solver: {solver}")

        # Use CLI solver if selected
        if solver and solver != 'qbd':
            result = self._generate_with_cli_solver(answers, solver, site_data)
        else:
            # Use standard QBD generator
            result = self._generate_with_qbd(answers, site_data)

        # Process result (same for both paths)
        if result.get('success'):
            print(f"[App] Layout generated: {result.get('summary', '')}")

            # Merge generated data into document
            self.document._data['walls_batch'] = result.get('walls_batch', [])
            self.document._data['doors'] = result.get('doors', [])
            self.document._data['windows'] = result.get('windows', [])
            self.document._data['rooms'] = result.get('rooms', {})
            self.document._data['levels'] = result.get('levels', [])
            self.document._data['width'] = result.get('width', 0)
            self.document._data['depth'] = result.get('depth', 0)
            self.document._data['sqft'] = result.get('sqft', 0)
            self.document._data['qbd_answers'] = answers
            self.document._data['is_complete'] = result.get('is_complete', False)
            self.document._data['_solver_used'] = solver  # Track which solver was used

            # Parse the generated data into document objects
            self.document._parse_data()
            self.document.set_modified()
            # Trigger 2D view refresh
            self.document.document_changed.emit()

            self.status_bar.showMessage(
                f"Building generated with {solver} solver: {len(result.get('walls_batch', []))} walls, "
                f"{len(result.get('rooms', {}))} rooms",
                5000
            )
        else:
            error = result.get('error', 'Unknown error')
            print(f"[App] Generation failed: {error}")
            self.status_bar.showMessage(f"Generation failed: {error}", 5000)

    def _generate_with_qbd(self, answers: dict, site_data: dict = None):
        """Generate layout using standard QBD generator."""
        import sys
        import os

        # Handle both development and frozen (PyInstaller) modes
        if getattr(sys, 'frozen', False):
            qbd_path = os.path.join(sys._MEIPASS, 'qbd')
        else:
            qbd_path = os.path.abspath(os.path.join(
                os.path.dirname(__file__), '..', '..', 'ArchEngine_kernel', 'qbd'
            ))

        if qbd_path not in sys.path:
            sys.path.insert(0, qbd_path)

        from qbd_layout_generator import generate_floor_plan_from_qbd, OutputFormat

        print(f"[App] Generating with QBD: {answers}")

        result = generate_floor_plan_from_qbd(
            answers,
            width=None,
            depth=None,
            output_format=OutputFormat.ARCHENGINE
        )
        return result

    def _generate_with_cli_solver(self, answers: dict, solver: str, site_data: dict = None):
        """Generate layout using CLI solver suite."""
        from complete_solver_suite import CompleteSolverSuite, SolverType, SOLVER_INFO
        from room_relationships import SpatialGraph, Zone

        print(f"[App] Generating with CLI solver: {solver}")

        # Calculate building dimensions from sqft
        sqft = answers.get('sqft', 2000)
        # Approximate width/depth from sqft (assume rectangular)
        area_m2 = sqft * 0.0929
        width_m = (area_m2 * 1.3) ** 0.5  # Slightly stretched
        depth_m = (area_m2 / 1.3) ** 0.5

        print(f"[App] Building dimensions: {width_m:.1f}m x {depth_m:.1f}m ({sqft} sqft)")

        # Create room graph from answers
        graph = self._create_room_graph_from_answers(answers)

        # Run selected solver
        try:
            solver_type = SolverType(solver)
        except ValueError:
            print(f"[App] Unknown solver: {solver}, using tree")
            solver_type = SolverType.TREE

        # Show solver info
        info = SOLVER_INFO.get(solver_type)
        if info:
            print(f"[App] Solver: {info.name} - {info.description}")

        suite = CompleteSolverSuite(graph, width_m, depth_m, grid_size=0.5)
        layout = suite.solve(solver_type, max_iterations=10000)

        total_rooms = len(graph.rooms)
        placed_rooms = len(layout.rooms)
        placement_rate = placed_rooms / total_rooms if total_rooms > 0 else 0

        print(f"[App] Solver result: {placed_rooms}/{total_rooms} rooms placed ({placement_rate:.0%}), "
              f"score: {layout.score:.2f}, time: {layout.solve_time_ms:.1f}ms")

        # Fallback to QBD generator if solver placed less than 50% of rooms
        if placement_rate < 0.5:
            print(f"[App] WARNING: {solver} only placed {placed_rooms}/{total_rooms} rooms. "
                  f"Falling back to QBD generator...")
            return self._generate_with_qbd(answers, site_data)

        # Convert solver layout to ArchEngine format
        result = self._convert_solver_layout_to_archengine(layout, answers, width_m, depth_m)
        return result

    def _create_room_graph_from_answers(self, answers: dict) -> 'SpatialGraph':
        """Create a spatial graph from QBD answers."""
        from room_relationships import SpatialGraph, Zone

        graph = SpatialGraph()

        # Add standard rooms based on answers
        bedrooms = answers.get('bedrooms', 3)
        bathrooms = answers.get('bathrooms', 2)
        garage = answers.get('garage', '1 car')
        special_rooms = answers.get('special_rooms', [])

        # Entry/Living
        graph.add_room('entry', 'entry', 6.0, target_area=8.0, zone=Zone.PUBLIC)
        graph.add_room('living', 'living', 20.0, target_area=25.0, zone=Zone.PUBLIC)

        # Kitchen/Dining
        graph.add_room('kitchen', 'kitchen', 12.0, target_area=15.0, zone=Zone.PUBLIC)
        graph.add_room('dining', 'dining', 12.0, target_area=15.0, zone=Zone.PUBLIC)

        # Bedrooms
        for i in range(bedrooms):
            if i == 0:
                graph.add_room(f'bedroom_{i+1}', 'primary_bedroom', 14.0, target_area=18.0, zone=Zone.PRIVATE)
                graph.add_room(f'closet_{i+1}', 'walk_in_closet', 4.0, target_area=6.0, zone=Zone.PRIVATE)
            else:
                graph.add_room(f'bedroom_{i+1}', 'bedroom', 10.0, target_area=12.0, zone=Zone.PRIVATE)
                graph.add_room(f'closet_{i+1}', 'closet', 2.0, target_area=3.0, zone=Zone.PRIVATE)

        # Bathrooms
        for i in range(int(bathrooms)):
            if i == 0:
                graph.add_room(f'bathroom_{i+1}', 'primary_bath', 8.0, target_area=10.0, zone=Zone.PRIVATE)
            else:
                graph.add_room(f'bathroom_{i+1}', 'bathroom', 5.0, target_area=6.0, zone=Zone.PRIVATE)

        # Garage
        if garage and 'car' in garage:
            cars = int(garage.split()[0]) if garage[0].isdigit() else 1
            graph.add_room('garage', 'garage', 20.0 * cars, target_area=24.0 * cars, zone=Zone.SERVICE)

        # Special rooms
        for room_key in special_rooms:
            room_types = {
                'office': ('office', 10.0, Zone.PUBLIC),
                'laundry': ('laundry', 5.0, Zone.SERVICE),
                'guest': ('guest_bedroom', 12.0, Zone.PRIVATE),
                'workshop': ('workshop', 15.0, Zone.SERVICE),
                'gym': ('gym', 15.0, Zone.PRIVATE),
                'library': ('library', 10.0, Zone.PUBLIC),
                'mudroom': ('mudroom', 6.0, Zone.TRANSITION),
                'porch': ('porch', 10.0, Zone.OUTDOOR),
                'deck': ('deck', 15.0, Zone.OUTDOOR),
            }
            if room_key in room_types:
                room_type, area, zone = room_types[room_key]
                graph.add_room(room_key, room_type, area, target_area=area * 1.2, zone=zone)

        # Set up adjacencies
        graph.connect('entry', 'living', weight=2.0)
        graph.connect('living', 'kitchen', weight=2.0)
        graph.connect('kitchen', 'dining', weight=2.0)

        if 'bedroom_1' in graph.rooms:
            graph.connect('bedroom_1', 'bathroom_1', weight=3.0)
            graph.connect('bedroom_1', 'closet_1', weight=3.0)

        for i in range(1, bedrooms):
            if f'bedroom_{i+1}' in graph.rooms:
                graph.connect(f'bedroom_{i+1}', f'closet_{i+1}', weight=2.0)
                bath = 'bathroom_2' if 'bathroom_2' in graph.rooms else 'bathroom_1'
                graph.connect(f'bedroom_{i+1}', bath, weight=1.0)

        if 'mudroom' in graph.rooms:
            graph.connect('mudroom', 'entry', weight=2.0)
            if 'garage' in graph.rooms:
                graph.connect('mudroom', 'garage', weight=2.0)

        if 'laundry' in graph.rooms:
            if 'mudroom' in graph.rooms:
                graph.connect('laundry', 'mudroom', weight=1.5)
            elif 'garage' in graph.rooms:
                graph.connect('laundry', 'garage', weight=1.0)

        return graph

    def _convert_solver_layout_to_archengine(self, layout, answers: dict, width_m: float, depth_m: float):
        """Convert solver layout to ArchEngine walls_batch format."""
        walls_batch = []
        rooms = {}
        doors = []
        room_id_to_idx = {}

        # Convert rooms
        for idx, (room_id, placed) in enumerate(layout.rooms.items()):
            room_id_to_idx[room_id] = idx

            # Room data - C++ expects bounds as object with x, y, width, height
            rooms[room_id] = {
                'name': room_id.replace('_', ' ').title(),
                'room_type': placed.room_type if hasattr(placed, 'room_type') else 'room',
                'bounds': {
                    'x': placed.rect.x,
                    'y': placed.rect.y,
                    'width': placed.rect.width,
                    'height': placed.rect.height
                },
                'area': placed.area if hasattr(placed, 'area') else placed.rect.width * placed.rect.height,
                'vertices': [
                    [placed.rect.x * 1000, placed.rect.y * 1000],
                    [(placed.rect.x + placed.rect.width) * 1000, placed.rect.y * 1000],
                    [(placed.rect.x + placed.rect.width) * 1000, (placed.rect.y + placed.rect.height) * 1000],
                    [placed.rect.x * 1000, (placed.rect.y + placed.rect.height) * 1000],
                ]
            }

            # Generate walls for this room
            x1 = placed.rect.x * 1000
            y1 = placed.rect.y * 1000
            x2 = (placed.rect.x + placed.rect.width) * 1000
            y2 = (placed.rect.y + placed.rect.height) * 1000

            room_walls = [
                {'start': [x1, 0, y1], 'end': [x2, 0, y1], 'category': 'interior'},
                {'start': [x2, 0, y1], 'end': [x2, 0, y2], 'category': 'interior'},
                {'start': [x2, 0, y2], 'end': [x1, 0, y2], 'category': 'interior'},
                {'start': [x1, 0, y2], 'end': [x1, 0, y1], 'category': 'interior'},
            ]

            for wall in room_walls:
                wall['height'] = 2700
                wall['wall_type'] = 'interior'
                wall['is_structural'] = True
                wall['bound_room_id'] = room_id
                walls_batch.append(wall)

        # Mark exterior walls
        margin = 0.1
        for wall in walls_batch:
            x1, z1 = wall['start'][0] / 1000, wall['start'][2] / 1000
            x2, z2 = wall['end'][0] / 1000, wall['end'][2] / 1000

            on_perimeter = (
                abs(x1) < margin or abs(x1 - width_m) < margin or
                abs(x2) < margin or abs(x2 - width_m) < margin or
                abs(z1) < margin or abs(z1 - depth_m) < margin or
                abs(z2) < margin or abs(z2 - depth_m) < margin
            )

            if on_perimeter:
                wall['category'] = 'exterior'
                wall['wall_type'] = 'exterior'

        return {
            'success': len(layout.rooms) > 0,
            'walls_batch': walls_batch,
            'doors': doors,
            'windows': [],
            'rooms': rooms,
            'levels': [{'name': 'Level 1', 'elevation': 0}],
            'width': width_m * 1000,
            'depth': depth_m * 1000,
            'sqft': answers.get('sqft', 2000),
            'is_complete': len(layout.rooms) >= len(layout.rooms) * 0.8 if hasattr(layout, 'rooms') else True,
            'summary': f"{len(walls_batch)} walls, {len(rooms)} rooms"
        }

    def _on_solver_comparison(self):
        """Open solver comparison dialog."""
        try:
            from dialogs.solver_comparison_dialog import SolverComparisonDialog
            from room_relationships import SpatialGraph, Zone

            # Create room graph from current document or use defaults
            if hasattr(self, 'document') and self.document._rooms:
                # Use existing rooms
                graph = SpatialGraph()
                for room_id, room in self.document._rooms.items():
                    graph.add_room(
                        room_id,
                        room.room_type,
                        room.min_area or room.area,
                        target_area=room.area,
                        zone=Zone.PUBLIC if room.room_type in ['living', 'kitchen', 'dining'] else Zone.PRIVATE
                    )
                # Add adjacencies from connections
                for conn in self.document._room_connections:
                    graph.connect(conn.room_a_id, conn.room_b_id, 1.0)
            else:
                # Default test rooms
                graph = SpatialGraph()
                graph.add_room("living", "living", 20, target_area=25, zone=Zone.PUBLIC)
                graph.add_room("kitchen", "kitchen", 12, target_area=15, zone=Zone.PUBLIC)
                graph.add_room("dining", "dining", 12, target_area=15, zone=Zone.PUBLIC)
                graph.add_room("bed1", "bedroom", 12, target_area=15, zone=Zone.PRIVATE)
                graph.add_room("bed2", "bedroom", 10, target_area=12, zone=Zone.PRIVATE)
                graph.add_room("bath", "bathroom", 6, target_area=8, zone=Zone.PRIVATE)

                graph.connect("living", "kitchen", 2.0)
                graph.connect("living", "dining", 2.0)
                graph.connect("kitchen", "dining", 2.0)

            # Calculate dimensions from document or use defaults
            if hasattr(self, 'document') and self.document._data.get('width'):
                width_m = self.document._data.get('width', 15000) / 1000
                depth_m = self.document._data.get('depth', 12000) / 1000
            else:
                width_m = 15
                depth_m = 12

            dialog = SolverComparisonDialog(graph, width_m, depth_m, self)

            # Handle selected layout
            def on_layout_selected(solver_type, layout):
                print(f"[App] Selected {solver_type.value} solver layout with {len(layout.rooms)} rooms")
                # Convert to ArchEngine format and apply
                # TODO: Apply the selected layout to the document

            dialog.layout_selected.connect(on_layout_selected)
            dialog.exec()

        except Exception as e:
            print(f"[App] Solver comparison error: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.warning(self, "Solver Comparison", f"Error: {e}")

    def _old_generate_building_from_qbd_algebra(self, answers: dict, site_data: dict = None):
        """OLD: Generate building layout using QBD algebra system."""
        try:

            # DON'T use site dimensions as building size!
            # The building size should be calculated from sqft in the answers.
            # Site dimensions are only a constraint (max size), not the building size.
            # Let the QBD generator calculate the optimal building dimensions from sqft.
            width = None
            depth = None

            # Generate the layout - building sized from sqft, NOT from site
            result = generate_floor_plan_from_qbd(
                answers,
                width=width,   # None = auto-calculate from sqft
                depth=depth,   # None = auto-calculate from sqft
                output_format=OutputFormat.ARCHENGINE
            )

            if result.get('success'):
                print(f"[App] QBD algebra generated: {result['summary']}")

                # Merge generated data into document
                self.document._data['walls_batch'] = result.get('walls_batch', [])
                self.document._data['doors'] = result.get('doors', [])
                self.document._data['windows'] = result.get('windows', [])
                self.document._data['rooms'] = result.get('rooms', {})
                self.document._data['levels'] = result.get('levels', [])
                self.document._data['width'] = result.get('width', 0)
                self.document._data['depth'] = result.get('depth', 0)
                self.document._data['sqft'] = result.get('sqft', 0)
                self.document._data['qbd_answers'] = answers
                self.document._data['is_complete'] = result.get('is_complete', False)

                # Parse the generated data into document objects
                self.document._parse_data()
                self.document.set_modified()
                # Trigger 2D view refresh (document_changed is what plan_view listens to)
                self.document.document_changed.emit()

                self.status_bar.showMessage(
                    f"Building generated: {len(result.get('walls_batch', []))} walls, "
                    f"{len(result.get('rooms', {}))} rooms",
                    5000
                )
            else:
                error = result.get('error', 'Unknown error')
                print(f"[App] QBD algebra failed: {error}")
                self.status_bar.showMessage(f"Building generation failed: {error}", 5000)

        except ImportError as e:
            print(f"[App] Could not import QBD algebra: {e}")
            import traceback
            traceback.print_exc()
            self.status_bar.showMessage(f"QBD import error: {e}", 5000)
        except Exception as e:
            print(f"[App] Error generating building: {e}")
            import traceback
            traceback.print_exc()
            self.status_bar.showMessage(f"Error: {e}", 5000)

    def _on_qbd_generate(self, answers: dict, site_data: dict = None):
        """Handle QBD questionnaire answers and generate building."""
        print(f"[App] QBD answers: {answers}")
        if site_data:
            print(f"[App] Site data: {site_data.get('address', 'No address')}")

        # Create new document first
        self.document.new()

        # Store site data if provided
        if site_data:
            self.document._data['site'] = site_data

            # If site has terrain mesh, replace the test terrain
            if 'terrain_mesh' in site_data:
                self.document._data['terrain_mesh'] = site_data['terrain_mesh']
                print(f"[App] Using site terrain mesh from elevation data")

            # If site has building origin, store it
            if 'building_origin' in site_data:
                self.document._data['building_origin'] = site_data['building_origin']
                print(f"[App] Building origin: ({site_data['building_origin']['x_ft']:.0f}', {site_data['building_origin']['z_ft']:.0f}')")

        # Generate building layout from answers using the generator service
        try:
            self._generate_from_qbd(answers)
        except Exception as e:
            print(f"[App] Error generating building: {e}")
            import traceback
            traceback.print_exc()

    def _generate_from_qbd(self, answers: dict):
        """Generate building layout from QBD answers."""
        # Build a room list based on answers
        rooms = []

        # Add bedrooms
        for i in range(answers.get('bedrooms', 3)):
            rooms.append({'type': 'bedroom', 'name': f'Bedroom {i+1}'})

        # Add bathrooms
        bath_count = int(answers.get('bathrooms', 2))
        for i in range(bath_count):
            rooms.append({'type': 'bathroom', 'name': f'Bathroom {i+1}'})

        # Add standard rooms
        rooms.extend([
            {'type': 'living_room', 'name': 'Living Room'},
            {'type': 'kitchen', 'name': 'Kitchen'},
            {'type': 'dining_room', 'name': 'Dining Room'},
        ])

        # Add garage if requested
        garage = answers.get('garage', 'no garage')
        if 'car' in garage:
            rooms.append({'type': 'garage', 'name': 'Garage'})

        # Add special rooms
        for special in answers.get('special_rooms', []):
            room_name = special.replace('_', ' ').title()
            rooms.append({'type': special, 'name': room_name})

        # Store answers in document for reference
        self.document._data['qbd_answers'] = answers
        self.document._data['building_type'] = answers.get('building_type', 'residential')
        self.document._data['style'] = answers.get('style', 'modern')
        self.document._data['target_sqft'] = answers.get('sqft', 2000)

        print(f"[App] Generated {len(rooms)} rooms from QBD")

        # Emit document changed to trigger UI updates
        self.document.document_changed.emit()

    def _on_open(self):
        """Open existing document."""
        if not self._check_save():
            return

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Project",
            str(Path.home()),
            "JSON Files (*.json);;All Files (*)"
        )

        if file_path:
            self.open_project(Path(file_path))

    def open_project(self, file_path: Path):
        """Open a project file."""
        if self.document.load(file_path):
            self.config.add_recent_file(file_path)
            self.status_bar.showMessage(f"Loaded: {file_path.name}", 5000)
            # Show onboarding if this document hasn't completed it yet
            QTimer.singleShot(100, self._show_onboarding_if_needed)
        else:
            QMessageBox.warning(
                self,
                "Error",
                f"Could not load file: {file_path}"
            )

    def _on_save(self):
        """Save current document."""
        if self.document.file_path:
            self.document.save()
            self.status_bar.showMessage("Saved", 3000)
        else:
            self._on_save_as()

    def _on_save_as(self):
        """Save document with new name."""
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Project",
            str(Path.home()),
            "JSON Files (*.json);;All Files (*)"
        )

        if file_path:
            if self.document.save(Path(file_path)):
                self.config.add_recent_file(Path(file_path))
                self.status_bar.showMessage(f"Saved: {Path(file_path).name}", 5000)

    def _on_export_pdf(self):
        """Export current sheet to PDF."""
        try:
            from exports.pdf_exporter import PDFExporter
        except ImportError:
            QMessageBox.warning(
                self,
                "Export Not Available",
                "PDF export module not found."
            )
            return

        # Get current sheet from the tab widget
        current_sheet_id = self._get_current_sheet_id()
        if not current_sheet_id:
            QMessageBox.information(
                self,
                "No Sheet Selected",
                "Please open a sheet tab to export."
            )
            return

        sheet = self._sheet_registry.get_sheet(current_sheet_id)
        if not sheet or not sheet.svg_content:
            QMessageBox.warning(
                self,
                "No Content",
                "The selected sheet has no content to export.\nTry regenerating the sheet first."
            )
            return

        # Default filename based on sheet number and title
        default_name = f"{sheet.number}_{sheet.title.replace(' ', '_')}.pdf"

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export to PDF",
            default_name,
            "PDF Files (*.pdf)"
        )

        if file_path:
            exporter = PDFExporter(self)
            if exporter.export_sheet(sheet.svg_content, file_path, title=sheet.title, number=sheet.number):
                self.status_bar.showMessage(f"Exported: {Path(file_path).name}", 5000)

    def _on_export_all_pdf(self):
        """Export all sheets to a single PDF."""
        try:
            from exports.pdf_exporter import PDFExporter
        except ImportError:
            QMessageBox.warning(
                self,
                "Export Not Available",
                "PDF export module not found."
            )
            return

        # Gather all sheets with content
        sheets_data = []
        for sheet in self._sheet_registry.get_all_sheets():
            if sheet.svg_content:
                sheets_data.append({
                    'svg_content': sheet.svg_content,
                    'title': sheet.title,
                    'number': sheet.number
                })

        if not sheets_data:
            QMessageBox.information(
                self,
                "No Content",
                "No sheets have content to export.\nTry regenerating sheets first (F4)."
            )
            return

        # Default filename
        default_name = "drawing_set.pdf"
        if self.document.file_path:
            default_name = f"{self.document.file_path.stem}_sheets.pdf"

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export All Sheets to PDF",
            default_name,
            "PDF Files (*.pdf)"
        )

        if file_path:
            exporter = PDFExporter(self)
            if exporter.export_sheets(sheets_data, file_path):
                self.status_bar.showMessage(
                    f"Exported {len(sheets_data)} sheets to: {Path(file_path).name}",
                    5000
                )

    def _on_print(self):
        """Print current sheet."""
        try:
            from exports.pdf_exporter import PDFExporter
        except ImportError:
            QMessageBox.warning(
                self,
                "Print Not Available",
                "Print module not found."
            )
            return

        # Get current sheet
        current_sheet_id = self._get_current_sheet_id()
        if not current_sheet_id:
            QMessageBox.information(
                self,
                "No Sheet Selected",
                "Please open a sheet tab to print."
            )
            return

        sheet = self._sheet_registry.get_sheet(current_sheet_id)
        if not sheet or not sheet.svg_content:
            QMessageBox.warning(
                self,
                "No Content",
                "The selected sheet has no content to print.\nTry regenerating the sheet first."
            )
            return

        exporter = PDFExporter(self)
        if exporter.print_sheet(sheet.svg_content, f"{sheet.number} - {sheet.title}"):
            self.status_bar.showMessage("Print job sent", 3000)

    def _get_current_sheet_id(self) -> Optional[str]:
        """Get the sheet ID of the currently active tab."""
        if not hasattr(self, 'central_tabs') or not self.central_tabs:
            return None

        current_widget = self.central_tabs.currentWidget()
        if current_widget and hasattr(current_widget, 'sheet_id'):
            return current_widget.sheet_id
        return None

    def _on_define_site(self):
        """Show site definition dialog to fetch terrain elevation data."""
        from dialogs.site_dialog import show_site_dialog

        # Show the site dialog
        site_data = show_site_dialog(self)

        if site_data and 'terrain_mesh' in site_data:
            # User provided terrain data - update the current document
            self.document._data['terrain_mesh'] = site_data['terrain_mesh']
            self.document._data['site'] = site_data

            # Copy building origin to document level if provided
            if 'building_origin' in site_data:
                self.document._data['building_origin'] = site_data['building_origin']
                print(f"[App] Building origin: ({site_data['building_origin']['x_ft']:.0f}', {site_data['building_origin']['z_ft']:.0f}')")

            # Mark document as modified
            self.document.set_modified()

            # Update the 3D viewport
            if HAS_VIEWPORT and self.viewport_3d:
                print(f"[App] Updating viewport with site terrain mesh")
                self.viewport_3d.load_json(self.document._data)

            self.status_bar.showMessage(
                f"Site terrain loaded: {site_data['terrain_mesh']['vertex_count']} vertices",
                5000
            )
        elif site_data:
            # Site data but no terrain
            self.document._data['site'] = site_data
            if 'building_origin' in site_data:
                self.document._data['building_origin'] = site_data['building_origin']
            self.document.set_modified()
            self.status_bar.showMessage("Site data saved (no terrain)", 3000)

    def _check_save(self) -> bool:
        """Check if document should be saved. Returns False to cancel."""
        if not self.document.modified:
            return True

        result = QMessageBox.question(
            self,
            "Save Changes?",
            "The document has been modified. Save changes?",
            QMessageBox.StandardButton.Save |
            QMessageBox.StandardButton.Discard |
            QMessageBox.StandardButton.Cancel
        )

        if result == QMessageBox.StandardButton.Save:
            self._on_save()
            return True
        elif result == QMessageBox.StandardButton.Discard:
            return True
        else:
            return False

    # =========================================================================
    # Edit Operations
    # =========================================================================

    def _on_undo(self):
        """Undo last action."""
        self.document.undo_stack.undo()

    def _on_redo(self):
        """Redo last undone action."""
        self.document.undo_stack.redo()

    def _on_delete(self):
        """Delete selected elements."""
        if self.tool_manager:
            tool = self.tool_manager.active_tool
            if tool and hasattr(tool, '_delete_selected'):
                tool._delete_selected()

    # =========================================================================
    # Toggle Operations
    # =========================================================================

    def _toggle_ortho(self, checked: bool):
        """Toggle orthographic mode."""
        self.config.ortho_mode = checked
        self.config.save()
        self.status_bar.showMessage(f"Ortho: {'On' if checked else 'Off'}", 2000)

    def _toggle_grid(self, checked: bool):
        """Toggle grid visibility."""
        self.config.grid_visible = checked
        self.config.save()
        if hasattr(self, 'plan_view'):
            self.plan_view.set_grid_visible(checked)
        self.status_bar.showMessage(f"Grid: {'On' if checked else 'Off'}", 2000)

    def _toggle_snap(self, checked: bool):
        """Toggle snap mode."""
        self.config.snap_enabled = checked
        self.config.save()
        self.status_bar.showMessage(f"Snap: {'On' if checked else 'Off'}", 2000)

    def _toggle_snap_type(self, snap_type: str):
        """Toggle individual snap type."""
        attr_name = f'snap_{snap_type}'
        action_name = f'action_snap_{snap_type}'

        if hasattr(self.config, attr_name) and hasattr(self, action_name):
            action = getattr(self, action_name)
            new_value = action.isChecked()
            setattr(self.config, attr_name, new_value)
            self.config.save()

            # Update snap manager's cached snap points if endpoint/midpoint changed
            if snap_type in ('endpoint', 'midpoint') and hasattr(self, 'plan_view'):
                self.plan_view._snap_manager.collect_snap_points()

            self.status_bar.showMessage(f"Snap {snap_type.title()}: {'On' if new_value else 'Off'}", 2000)

    # =========================================================================
    # Render Settings
    # =========================================================================

    def _set_material_style(self, style: int):
        """Set material rendering style (0=Realistic, 1=Clean, 2=Schematic, 3=Blueprint)."""
        if not HAS_VIEWPORT:
            return

        # Update action check states
        self.action_render_realistic.setChecked(style == 0)
        self.action_render_clean.setChecked(style == 1)
        self.action_render_schematic.setChecked(style == 2)
        self.action_render_blueprint.setChecked(style == 3)

        # Apply to viewport
        viewport = self._get_active_viewport()
        if viewport and viewport.is_initialized:
            viewport.set_material_style(style)

        # Update viewport panel if available
        if hasattr(self, 'viewport_panel'):
            self.viewport_panel.set_material_style(style)

        style_names = ["Realistic", "Clean", "Schematic", "Blueprint"]
        self.status_bar.showMessage(f"Material Style: {style_names[style]}", 2000)

    def _toggle_shadows(self, checked: bool):
        """Toggle shadow rendering."""
        if not HAS_VIEWPORT:
            return

        viewport = self._get_active_viewport()
        if viewport and viewport.is_initialized:
            viewport.set_shadows_enabled(checked)

        self.status_bar.showMessage(f"Shadows: {'On' if checked else 'Off'}", 2000)

    def _toggle_ssao(self, checked: bool):
        """Toggle screen-space ambient occlusion."""
        if not HAS_VIEWPORT:
            return

        viewport = self._get_active_viewport()
        if viewport and viewport.is_initialized:
            viewport.set_ssao_enabled(checked)

        self.status_bar.showMessage(f"SSAO: {'On' if checked else 'Off'}", 2000)

    def _toggle_bloom(self, checked: bool):
        """Toggle bloom effect."""
        if not HAS_VIEWPORT:
            return

        viewport = self._get_active_viewport()
        if viewport and viewport.is_initialized:
            viewport.set_bloom_enabled(checked)

        self.status_bar.showMessage(f"Bloom: {'On' if checked else 'Off'}", 2000)

    # =========================================================================
    # Diagnostics
    # =========================================================================

    def _diag_log_memory(self):
        """Log a memory snapshot."""
        if HAS_DIAGNOSTICS:
            diag = get_diagnostics()
            snapshot = diag.log_memory("manual")
            self.status_bar.showMessage(
                f"Memory: RSS={snapshot.rss_mb:.1f}MB, Objects={snapshot.gc_objects}", 3000
            )

    def _diag_gc_collect(self):
        """Force garbage collection."""
        if HAS_DIAGNOSTICS:
            diag = get_diagnostics()
            freed = diag.gc_collect()
            self.status_bar.showMessage(f"GC freed {freed} objects", 3000)

    def _diag_find_leaks(self):
        """Find potential memory leaks."""
        if HAS_DIAGNOSTICS:
            diag = get_diagnostics()
            leaks = diag.find_leaks()
            # Show top 5 in status bar
            top = list(leaks.items())[:5]
            msg = ", ".join(f"{k}:{v}" for k, v in top)
            self.status_bar.showMessage(f"Top objects: {msg}", 5000)

    def _diag_generate_report(self):
        """Generate and print diagnostic report."""
        if HAS_DIAGNOSTICS:
            diag = get_diagnostics()
            report = diag.generate_report()
            print(report)
            self.status_bar.showMessage("Diagnostic report printed to console", 3000)

    def _diag_save_report(self):
        """Save diagnostic report to file."""
        if HAS_DIAGNOSTICS:
            diag = get_diagnostics()
            path = diag.save_report()
            self.status_bar.showMessage(f"Report saved to {path}", 3000)
            QMessageBox.information(self, "Diagnostic Report", f"Report saved to:\n{path}")

    # =========================================================================
    # Pin/LLM Operations
    # =========================================================================

    def _on_pin_toggle(self, checked: bool):
        """Toggle pin state on selected elements."""
        selected = self.plan_view.scene.selectedItems() if hasattr(self, 'plan_view') else []
        if not selected:
            self.status_bar.showMessage("No elements selected to pin", 2000)
            return

        count = 0
        for item in selected:
            item_type = type(item).__name__

            if item_type == "WallItem" and hasattr(item, 'wall'):
                self.document.pin_element("wall", str(item.wall.index), checked)
                count += 1
            elif item_type == "DoorItem" and hasattr(item, 'door'):
                self.document.pin_element("door", str(item.door.index), checked)
                count += 1
            elif item_type == "WindowItem" and hasattr(item, 'window'):
                self.document.pin_element("window", str(item.window.index), checked)
                count += 1
            elif item_type == "RoomItem" and hasattr(item, 'room'):
                self.document.pin_element("room", item.room.id, checked)
                count += 1

        if count > 0:
            action = "Pinned" if checked else "Unpinned"
            self.status_bar.showMessage(f"{action} {count} element(s)", 2000)
            # Refresh view to show pin indicators
            if hasattr(self, 'plan_view'):
                self.plan_view.refresh()

    def _on_chat_message(self, message: str):
        """Handle chat message from chat panel."""
        # This is called when user sends a message
        # The chat panel handles LLM integration internally
        self.status_bar.showMessage(f"Processing: {message[:30]}...", 2000)

    def _on_schema_updated(self, schema: dict):
        """Handle schema update from LLM."""
        # Refresh all views
        if hasattr(self, 'plan_view'):
            self.plan_view.refresh()

        # Update 3D viewport
        if HAS_VIEWPORT and hasattr(self, 'viewport_3d'):
            if self.viewport_3d.is_initialized:
                self.viewport_3d.load_json(schema)

        self.status_bar.showMessage("Design updated by LLM", 3000)

    # =========================================================================
    # Event Handlers
    # =========================================================================

    def _update_title(self):
        """Update window title based on document state."""
        title = "ArchEngine CAD"
        if self.document.file_path:
            title = f"{self.document.file_path.name} - {title}"
        if self.document.modified:
            title = f"* {title}"
        self.setWindowTitle(title)

    def _on_document_loaded(self, path: str):
        """Handle document loaded event."""
        self._update_title()
        if hasattr(self, 'plan_view'):
            self.plan_view.refresh()

    def _on_document_modified(self):
        """Handle document modified event."""
        self._update_title()

    def _on_document_changed_livesync(self):
        """Send document changes to UE5 via LiveSync."""
        if self._livesync_server and self._livesync_server.client_count > 0:
            data = self.document.get_data()
            self._livesync_server.send_building_data(data)

    def _on_document_changed_vulkan(self):
        """Send document changes to Vulkan renderer via VulkanSync."""
        if self._vulkan_sync and self._vulkan_sync.is_connected:
            data = self.document.get_data()
            self._vulkan_sync.send_building_data(data)

    def _on_vulkan_connected(self):
        """Handle Vulkan renderer connection."""
        self.status_bar.showMessage("Connected to Vulkan renderer", 5000)
        # Send current building data immediately
        data = self.document.get_data()
        if data:
            self._vulkan_sync.send_building_data(data)

    def _on_vulkan_disconnected(self):
        """Handle Vulkan renderer disconnection."""
        self.status_bar.showMessage("Vulkan renderer disconnected", 3000)

    def _on_document_changed_viewport(self):
        """Schedule throttled update to embedded Vulkan viewport(s)."""
        if HAS_VIEWPORT:
            # Restart timer - only update after 150ms of no changes (prevents lag during dragging)
            self._viewport_update_timer.start()

    def _do_viewport_update(self):
        """Actually send data to viewport(s) (called by throttle timer)."""
        if not HAS_VIEWPORT:
            return

        # Skip 3D updates at LOD 1 (Topology mode) - will update when leaving LOD 1
        if getattr(self, '_global_lod_level', 2) == 1:
            return

        data = self.document.get_data() if hasattr(self.document, 'get_data') else self.document._data
        if not data:
            return

        # Update dock viewport
        if hasattr(self, 'viewport_3d') and self.viewport_3d.is_initialized:
            self.viewport_3d.load_json(data)

        # Update split viewport if in split mode
        if self._split_viewport and self._split_viewport.is_initialized:
            self._split_viewport.load_json(data)

    def _on_viewport_initialized(self):
        """Handle viewport initialization complete."""
        self.status_bar.showMessage("3D Viewport ready", 3000)

        # Connect document for Python-side picking
        if hasattr(self, 'viewport_3d') and self.viewport_3d.is_initialized:
            self.viewport_3d.set_document(self.document)
            # Connect 3D selection to sync to 2D
            self.viewport_3d.element_selected.connect(self._on_3d_element_selected)
        if self._split_viewport and self._split_viewport.is_initialized:
            self._split_viewport.set_document(self.document)
            self._split_viewport.element_selected.connect(self._on_3d_element_selected)

        # Load current document data if available
        data = self.document.get_data() if hasattr(self.document, 'get_data') else self.document._data
        if data:
            # Update whichever viewport just initialized
            if hasattr(self, 'viewport_3d') and self.viewport_3d.is_initialized:
                self.viewport_3d.load_json(data)
            if self._split_viewport and self._split_viewport.is_initialized:
                self._split_viewport.load_json(data)

        # Connect viewport panel to the viewport widget
        if hasattr(self, 'viewport_panel') and hasattr(self, 'viewport_3d'):
            self.viewport_panel.set_viewport(self.viewport_3d)
            # Connect manual LOD changes (shift+scroll) from 3D viewport
            self.viewport_3d.lod_level_changed.connect(
                self.viewport_panel.set_lod_level
            )
            # Connect section changes from viewport (interactive drag)
            self.viewport_3d.section_changed.connect(
                self.viewport_panel.update_from_section
            )

        # Connect materials panel to the viewport widget
        if hasattr(self, 'materials_panel') and hasattr(self, 'viewport_3d'):
            self.materials_panel.set_viewport(self.viewport_3d)
            self.materials_panel.set_document(self.document)
            self.materials_panel.material_assigned.connect(self._on_material_assigned)

            # Connect LOD changes from 2D plan view as well
            if hasattr(self, 'plan_view'):
                self.plan_view.lod_level_changed.connect(
                    self.viewport_panel.set_lod_level
                )
                # Also update 3D viewport rendering quality when 2D LOD changes
                self.plan_view.lod_level_changed.connect(
                    self.viewport_3d.set_lod_level
                )

            # Connect to smart panel container if available
            if hasattr(self, 'smart_panel_container'):
                # Connect gravity changes
                self.viewport_panel.gravity_changed.connect(
                    self.smart_panel_container.update_gravity
                )
                # Connect LOD changes
                self.viewport_panel.lod_changed.connect(
                    lambda level, trans: self.smart_panel_container.update_lod(level, trans)
                )
                # Connect hover-to-center: when user hovers a dimmed panel,
                # auto-center gravity so all panels become accessible
                self.smart_panel_container.request_gravity_center.connect(
                    self._on_request_gravity_center
                )

                # Connect hover-to-LOD: switch to the LOD the panel needs
                self.smart_panel_container.request_lod_change.connect(
                    self._on_request_lod_change
                )

            # Connect floating navigation overlay (tetrahedron) to viewport + panels
            if hasattr(self.viewport_3d, 'gravity_changed'):
                self.viewport_3d.gravity_changed.connect(
                    self.viewport_panel.set_gravity_weights
                )
                if hasattr(self, 'smart_panel_container'):
                    self.viewport_3d.gravity_changed.connect(
                        self.smart_panel_container.update_gravity
                    )
            # Connect tetrahedron mode changes to 2D plan view
            if hasattr(self.viewport_3d, 'mode_changed'):
                self.viewport_3d.mode_changed.connect(
                    lambda mode: self.plan_view.set_view_mode(mode) if hasattr(self, 'plan_view') else None
                )
            if hasattr(self.viewport_3d, 'lod_changed'):
                self.viewport_3d.lod_changed.connect(
                    self.viewport_panel.set_lod_level
                )
                # Also update 2D plan view LOD
                self.viewport_3d.lod_changed.connect(
                    lambda level, trans: self.plan_view.set_lod_level(level) if hasattr(self, 'plan_view') else None
                )
                if hasattr(self, 'smart_panel_container'):
                    self.viewport_3d.lod_changed.connect(
                        lambda level, trans: self.smart_panel_container.update_lod(level, trans)
                    )

            # Keep overlay in sync if controls change elsewhere
            if hasattr(self.viewport_3d, 'set_nav_gravity'):
                self.viewport_panel.gravity_changed.connect(
                    self.viewport_3d.set_nav_gravity
                )
            if hasattr(self.viewport_3d, 'set_nav_lod'):
                self.viewport_panel.lod_changed.connect(
                    lambda level, trans: self.viewport_3d.set_nav_lod(level)
                )

    def _on_request_gravity_center(self):
        """Handle request to center gravity (from hovering a panel)."""
        if hasattr(self, 'viewport_panel'):
            self.viewport_panel.center_gravity()

    def _on_request_lod_change(self, lod_level: int):
        """Handle request to change LOD (from hovering a panel)."""
        old_lod = getattr(self, '_global_lod_level', 2)
        self._global_lod_level = lod_level
        if hasattr(self, 'viewport_panel'):
            self.viewport_panel.set_lod_level(lod_level)
        # Update 3D viewport rendering quality based on LOD
        if hasattr(self, 'viewport_3d') and self.viewport_3d.is_initialized:
            self.viewport_3d.set_lod_level(lod_level)
        if self._split_viewport and self._split_viewport.is_initialized:
            self._split_viewport.set_lod_level(lod_level)
        # If leaving LOD 1, force a viewport update (was skipped during topology editing)
        if old_lod == 1 and lod_level != 1:
            self._do_viewport_update()
        # Show feedback
        lod_names = {1: "Topology", 2: "Walls", 3: "Fixtures", 4: "Viewports", 5: "Documentation"}
        self.status_bar.showMessage(
            f"LOD {lod_level}: {lod_names.get(lod_level, '')} (panel hover)",
            1500
        )

    def _on_viewport_load_complete(self, element_count: int):
        """Handle viewport loaded building data."""
        self.status_bar.showMessage(f"3D View: {element_count} elements", 3000)

    def _on_rooms_loaded(self, rooms: list):
        """Handle rooms loaded from 3D renderer - sync to document."""
        if not rooms:
            return

        # Skip sync if we're in the middle of wall generation (preserves user edits)
        if getattr(self, '_syncing_walls', False):
            print(f"[App] Skipping room sync during wall generation")
            return

        print(f"[App] Syncing {len(rooms)} rooms from renderer to document")

        # Update document with rooms from renderer
        for room_data in rooms:
            room_id = room_data['id']
            bounds = room_data['bounds']

            # Generate vertices from bounds
            x, y = bounds['x'], bounds['y']
            w, h = bounds['width'], bounds['height']
            vertices = [
                [x, y],
                [x + w, y],
                [x + w, y + h],
                [x, y + h]
            ]

            # Check if room exists in document
            if room_id in self.document._rooms:
                # Update existing room
                room = self.document._rooms[room_id]
                room.bounds = bounds
                room.vertices = vertices
                room.center = room_data['center']
                room.name = room_data['name']
                room.room_type = room_data['room_type']
                room.area = room_data['area']
            else:
                # Add new room
                from core.document import Room
                room = Room(
                    id=room_id,
                    name=room_data['name'],
                    room_type=room_data['room_type'],
                    bounds=bounds,
                    area=room_data['area'],
                    center=room_data['center'],
                    vertices=vertices
                )
                self.document._rooms[room_id] = room

        # Auto-bind walls to rooms
        self.document._auto_bind_walls_to_rooms()

        # Recalculate room areas from vertices
        self.document.recalculate_room_areas()

        # Detect room adjacencies
        self.document.detect_room_adjacencies()

        # Refresh plan view
        if hasattr(self, 'plan_view'):
            self.plan_view.refresh()

        self.status_bar.showMessage(f"Synced {len(rooms)} rooms from 3D renderer", 3000)

    def _on_viewport_error(self, error: str):
        """Handle viewport error."""
        self.status_bar.showMessage(f"3D Viewport Error: {error}", 5000)

    def _on_sync_walls_to_connections(self):
        """Generate walls from room edges based on connections."""
        if not self.document:
            self.status_bar.showMessage("No document loaded", 3000)
            return

        # Prevent room positions from being reset during wall sync
        self._syncing_walls = True

        try:
            print("[App] Starting wall generation...", flush=True)

            # Generate reference planes from building extents
            self.document.generate_reference_planes_from_extents()

            # Generate walls from room edges (with exterior wall merging)
            exterior, interior, openings = self.document.generate_walls_from_rooms()
            print(f"[App] Wall generation complete: {exterior} ext, {interior} int, {openings} open", flush=True)

            # Snap exterior walls to reference planes
            snapped = self.document.snap_exterior_walls_to_planes()
            print(f"[App] Snap complete: {snapped} endpoints", flush=True)

            # Switch to LOD 2 to show walls
            self._global_lod_level = 2
            if hasattr(self, 'plan_view'):
                self.plan_view.set_lod_level(2)
            print("[App] Switched to LOD 2", flush=True)

            # Refresh plan view
            print("[App] Refreshing plan view...", flush=True)
            if hasattr(self, 'plan_view'):
                self.plan_view.refresh()
            print("[App] Plan view refreshed", flush=True)

            # Force Qt to process events before continuing
            print("[App] Processing events...", flush=True)
            QApplication.processEvents()
            print("[App] Events processed", flush=True)

            # 3D view auto-reloads via document_changed signal

            print("[App] Setting status bar message...", flush=True)
            self.status_bar.showMessage(
                f"Walls: {exterior} ext, {interior} int | Ref planes: {len(self.document.reference_planes)} | Snapped: {snapped}", 5000
            )

            # Clear syncing flag after viewport update completes (250ms > 150ms throttle)
            QTimer.singleShot(250, self._clear_syncing_walls)
        except Exception as e:
            print(f"[App] Error in wall sync: {e}", flush=True)
            import traceback
            traceback.print_exc()
            self.status_bar.showMessage(f"Wall sync error: {e}", 5000)
            self._syncing_walls = False

    def _clear_syncing_walls(self):
        """Clear the wall syncing flag (called after viewport update delay)."""
        self._syncing_walls = False

    def _show_status_message(self, message: str, timeout: int):
        """Show message in status bar."""
        self.status_bar.showMessage(message, timeout)

    def _update_api_status(self, connected: bool = None):
        """Update API connection status indicator."""
        if not hasattr(self, '_api_status_label'):
            return

        if connected is None and hasattr(self.document, 'is_connected'):
            connected = self.document.is_connected

        if connected:
            self._api_status_label.setText("API: Connected")
            self._api_status_label.setStyleSheet(
                "padding: 0 8px; color: #2e7d32; font-weight: bold;"
            )
        else:
            pending = 0
            if hasattr(self.document, 'get_pending_changes_count'):
                pending = self.document.get_pending_changes_count()

            if pending > 0:
                self._api_status_label.setText(f"API: Offline ({pending} pending)")
                self._api_status_label.setStyleSheet(
                    "padding: 0 8px; color: #f57c00; font-weight: bold;"
                )
            else:
                self._api_status_label.setText("API: Offline")
                self._api_status_label.setStyleSheet(
                    "padding: 0 8px; color: #757575;"
                )

    def _on_sync_completed(self, result: dict):
        """Handle sync completion."""
        synced = result.get('synced', 0)
        failed = result.get('failed', 0)

        if failed > 0:
            self.status_bar.showMessage(f"Sync: {synced} saved, {failed} failed", 5000)
        elif synced > 0:
            self.status_bar.showMessage(f"Synced {synced} changes", 3000)

        self._update_api_status()

    def _ensure_api_server(self):
        """Start API server if not already running."""
        import subprocess
        import socket
        import time

        global _api_server_process

        # Check if server is already running
        api_config = get_config().api
        host = "127.0.0.1"
        port = 8000

        # Parse port from URL if present
        if api_config.base_url:
            try:
                from urllib.parse import urlparse
                parsed = urlparse(api_config.base_url)
                if parsed.port:
                    port = parsed.port
            except Exception:
                pass

        # Try to connect
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex((host, port))
            sock.close()

            if result == 0:
                print(f"[App] API server already running on port {port}")
                return
        except Exception:
            pass

        # Start the server
        print(f"[App] Starting API server on port {port}...")
        try:
            # Get the CAD directory
            import sys
            cad_dir = Path(__file__).parent.parent

            # Start uvicorn as subprocess
            _api_server_process = subprocess.Popen(
                [
                    sys.executable, "-m", "uvicorn",
                    "api.server:app",
                    "--host", host,
                    "--port", str(port),
                ],
                cwd=str(cad_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
            )

            # Wait briefly for server to start
            for _ in range(10):
                time.sleep(0.3)
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(1)
                    if sock.connect_ex((host, port)) == 0:
                        sock.close()
                        print(f"[App] API server started successfully")
                        return
                    sock.close()
                except Exception:
                    pass

            print("[App] API server may still be starting...")

        except Exception as e:
            print(f"[App] Failed to start API server: {e}")

    def closeEvent(self, event):
        """Handle window close."""
        if self._check_save():
            self._save_state()
            self.config.save()

            # Generate diagnostic report on shutdown
            if HAS_DIAGNOSTICS:
                diag = get_diagnostics()
                diag.log_memory("shutdown")
                diag.stop_monitoring()
                report = diag.generate_report()
                print("[App] Diagnostic report saved to logs/")

            # Stop LiveSync server
            if self._livesync_server:
                self._livesync_server.stop()
            # Disconnect from Vulkan renderer
            if self._vulkan_sync:
                self._vulkan_sync.disconnect()
            # Shutdown Vulkan viewports
            if HAS_VIEWPORT:
                if hasattr(self, 'viewport_3d'):
                    try:
                        self.viewport_3d._shutdown()
                    except Exception as e:
                        print(f"Error shutting down viewport: {e}")
                if self._split_viewport:
                    try:
                        self._split_viewport._shutdown()
                    except Exception as e:
                        print(f"Error shutting down split viewport: {e}")
            # Clean up API document adapter
            if self._using_api and hasattr(self.document, 'close'):
                self.document.close()
            # Stop API server if we started it
            global _api_server_process
            if _api_server_process:
                print("[App] Stopping API server...")
                _api_server_process.terminate()
                _api_server_process = None
            event.accept()
        else:
            event.ignore()

    # =========================================================================
    # UE5 3D Viewport Operations
    # =========================================================================

    def _reset_viewport_camera(self):
        """Reset the 3D viewport camera to fit the building."""
        if not HAS_VIEWPORT:
            return

        viewport = self._get_active_viewport()
        if viewport and viewport.is_initialized:
            viewport.reset_camera()
            self.status_bar.showMessage("Camera reset to fit building", 2000)

    def _toggle_3d_view(self, checked: bool):
        """Toggle 3D viewport dock visibility."""
        if not HAS_VIEWPORT:
            return

        if hasattr(self, 'viewport_dock'):
            self.viewport_dock.setVisible(checked)
            if checked:
                self.status_bar.showMessage("3D Viewport visible", 2000)
                # Load document data if viewport just became visible
                if self.viewport_3d.is_initialized and self.document._data:
                    self.viewport_3d.load_json(self.document._data)

    def _toggle_split_view(self, checked: bool):
        """Toggle split view mode (2D | 3D side-by-side)."""
        if not HAS_VIEWPORT or not self._split_viewport:
            return

        self._split_mode = checked
        if checked:
            self._split_viewport.show()
            # Set equal split
            total_width = self.central_splitter.width()
            self.central_splitter.setSizes([total_width // 2, total_width // 2])
            self.status_bar.showMessage("Split view enabled (2D | 3D)", 3000)
            # Load current document into split viewport
            if self._split_viewport.is_initialized and self.document._data:
                self._split_viewport.load_json(self.document._data)
        else:
            self._split_viewport.hide()
            self.central_splitter.setSizes([1, 0])
            self.status_bar.showMessage("Split view disabled", 3000)

    def _get_active_viewport(self) -> Optional['VulkanViewportWidget']:
        """Get the currently active/visible viewport."""
        if not HAS_VIEWPORT:
            return None

        # Prefer split viewport if in split mode
        if self._split_mode and self._split_viewport and self._split_viewport.isVisible():
            return self._split_viewport

        # Otherwise use dock viewport if visible
        if hasattr(self, 'viewport_3d') and hasattr(self, 'viewport_dock'):
            if self.viewport_dock.isVisible():
                return self.viewport_3d

        # Fallback to split viewport even if not visible
        if self._split_viewport:
            return self._split_viewport

        return getattr(self, 'viewport_3d', None)

    # =========================================================================
    # Sheet Operations
    # =========================================================================

    def _on_regenerate_sheet(self, sheet_id: str):
        """Handle sheet regeneration request."""
        if sheet_id:
            # Regenerate single sheet
            self._generator_service.generate_sheet(sheet_id)
        else:
            # Regenerate all sheets
            self._generator_service.generate_all()

    def _on_open_sheet(self, sheet_id: str):
        """Open a sheet in a new tab in the central area."""
        from views.sheet_view import SheetViewContainer

        sheet = self._sheet_registry.get_sheet(sheet_id)
        if not sheet:
            return

        # Check if already open - switch to that tab
        if sheet_id in self._sheet_tabs:
            tab_index = self._sheet_tabs[sheet_id]
            if tab_index < self.central_tabs.count():
                self.central_tabs.setCurrentIndex(tab_index)
                return

        # Generate if needed
        if not sheet.has_content:
            self._generator_service.generate_sheet(sheet_id)

        # Create sheet view container
        view_container = SheetViewContainer(self.config, self)
        view_container.set_sheet(sheet)

        # Add as new tab
        tab_title = f"{sheet.number}"
        tab_index = self.central_tabs.addTab(view_container, tab_title)
        self.central_tabs.setTabToolTip(tab_index, f"{sheet.number} - {sheet.title}")
        self._sheet_tabs[sheet_id] = tab_index

        # Switch to the new tab
        self.central_tabs.setCurrentIndex(tab_index)

    def _on_preset_sheet_created(self, preset_data: dict):
        """Handle preset sheet creation from the sheet manager dialog."""
        from sheets.models import SheetType, SheetConfig
        import uuid

        preset = preset_data.get('preset')
        info = preset_data.get('info', {})

        if not preset:
            return

        # Map preset name to sheet type
        preset_type_map = {
            'Floor Plan Sheet': SheetType.PRESET_FLOOR_PLAN,
            'Elevations Sheet': SheetType.PRESET_ELEVATIONS,
            'Sections Sheet': SheetType.PRESET_SECTIONS,
            'Details Sheet': SheetType.PRESET_DETAILS,
            'Schedules Sheet': SheetType.PRESET_SCHEDULES,
        }

        sheet_type = preset_type_map.get(preset.name, SheetType.PRESET_FLOOR_PLAN)

        # Create unique ID
        sheet_id = f"{sheet_type.value}_{uuid.uuid4().hex[:8]}"

        # Create sheet config
        sheet = SheetConfig(
            id=sheet_id,
            sheet_type=sheet_type,
            title=info.get('title', preset.name),
            number=info.get('number', 'A-001'),
            scale=info.get('scale', '1:100'),
            preset_name=preset.name.lower().replace(' sheet', '').replace(' ', '_'),
        )

        # Add to registry
        self._sheet_registry.add_sheet_config(sheet)

        # Generate the sheet
        self._generator_service.generate_sheet(sheet_id)

        # Open in tab
        self._on_open_sheet(sheet_id)

        self.status_bar.showMessage(f"Created preset sheet: {sheet.title}", 3000)

    def _on_tab_close_requested(self, index: int):
        """Handle tab close request."""
        # Don't close the Editor tab (index 0)
        if index == 0:
            return

        # Find and remove from sheet_tabs tracking
        widget = self.central_tabs.widget(index)
        for sheet_id, tab_idx in list(self._sheet_tabs.items()):
            if tab_idx == index:
                del self._sheet_tabs[sheet_id]
                break

        # Update indices for tabs after the removed one
        for sheet_id, tab_idx in self._sheet_tabs.items():
            if tab_idx > index:
                self._sheet_tabs[sheet_id] = tab_idx - 1

        # Remove the tab
        self.central_tabs.removeTab(index)
