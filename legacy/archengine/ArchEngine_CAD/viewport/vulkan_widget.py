"""
VulkanViewportWidget - Qt widget embedding the Vulkan renderer.

Uses ctypes to call into ArchEngineLib.dll for real-time 3D visualization
of the building model directly in the CAD application.
"""

import ctypes
import json
import os
import sys
import threading
from pathlib import Path
from typing import Optional

# Diagnostics
try:
    from core.diagnostics import get_diagnostics, diag_log
    HAS_DIAGNOSTICS = True
except ImportError:
    HAS_DIAGNOSTICS = False
    def get_diagnostics(): return None
    def diag_log(msg): pass

# Selection manager for Python-side picking
try:
    from core.selection import get_selection_manager, SelectionManager
    HAS_SELECTION = True
except ImportError:
    HAS_SELECTION = False
    def get_selection_manager(): return None

from PyQt6.QtWidgets import QWidget, QApplication
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QSize
from PyQt6.QtGui import QPainter, QColor


# ctypes structure matching ArchRoomData in arch_api.h
class ArchRoomData(ctypes.Structure):
    _fields_ = [
        ("id", ctypes.c_char * 64),
        ("name", ctypes.c_char * 128),
        ("room_type", ctypes.c_char * 64),
        ("bounds_x", ctypes.c_float),
        ("bounds_y", ctypes.c_float),
        ("bounds_width", ctypes.c_float),
        ("bounds_height", ctypes.c_float),
        ("center_x", ctypes.c_float),
        ("center_y", ctypes.c_float),
        ("area", ctypes.c_float),
        ("zone", ctypes.c_int),
    ]


# Find the DLL
def _get_app_root() -> Path:
    """Get the application root directory, handling both dev and frozen modes."""
    if getattr(sys, 'frozen', False):
        # Running as PyInstaller bundle - use the _internal directory
        return Path(sys._MEIPASS)
    else:
        # Running as script
        return Path(__file__).parent.parent


def _find_dll() -> Optional[Path]:
    """Search for ArchEngineLib.dll - prioritize local/updated DLL first."""
    # Debug info
    print(f"[DLL] CWD: {Path.cwd()}")
    print(f"[DLL] __file__: {__file__}")

    # Handle frozen PyInstaller app
    if getattr(sys, 'frozen', False):
        # In frozen mode, DLL is bundled in _internal/dll/
        bundle_dir = Path(sys._MEIPASS)
        dll_path = bundle_dir / "dll" / "ArchEngineLib.dll"
        if dll_path.exists():
            print(f"[DLL] Found bundled: {dll_path}")
            return dll_path
        # Also check directly in bundle
        dll_path = bundle_dir / "ArchEngineLib.dll"
        if dll_path.exists():
            print(f"[DLL] Found bundled: {dll_path}")
            return dll_path
        print(f"[DLL] Not found in bundle: {bundle_dir}")
        return None

    # Development mode - search multiple paths
    # Use resolve() to get absolute paths
    try:
        cad_root = Path(__file__).parent.parent.resolve()  # ArchEngine_CAD folder
        suite_root = cad_root.parent.resolve()  # ArchEngine_Suite folder
    except Exception as e:
        print(f"[DLL] Path resolution error: {e}")
        # Fallback to cwd
        cad_root = Path.cwd()
        suite_root = cad_root.parent

    print(f"[DLL] CAD root: {cad_root}")
    print(f"[DLL] Suite root: {suite_root}")

    search_paths = [
        # 1. Direct DLL override (for testing new builds)
        cad_root / "dll",  # ArchEngine_CAD/dll/
        cad_root / "bin",  # ArchEngine_CAD/bin/

        # 2. Local kernel directory (same worktree - most common)
        suite_root / "ArchEngine_kernel" / "build" / "Release",
        suite_root / "ArchEngine_kernel" / "build" / "Debug",

        # 3. CWD-based search (when running from different locations)
        Path.cwd() / "ArchEngine_kernel" / "build" / "Release",
        Path.cwd() / "build" / "Release",
        Path.cwd().parent / "ArchEngine_kernel" / "build" / "Release",

        # 4. Kernel branch worktree (for latest kernel features)
        Path(r"X:\ARCH\Software\ArchEngine_Suite_Kernel\ArchEngine_kernel\build\Release"),
        Path(r"X:\ARCH\Software\ArchEngine_Suite_Kernel\ArchEngine_kernel\build\Debug"),

        # 5. UE5 worktree paths (explicit fallback)
        Path(r"X:\ARCH\Software\ArchEngine_suite_ue5\ArchEngine_kernel\build\Release"),
        Path(r"X:\ARCH\Software\ArchEngine_suite_ue5\ArchEngine_kernel\build\Debug"),
    ]

    print(f"[DLL] Searching {len(search_paths)} paths...")
    for i, path in enumerate(search_paths):
        dll_path = path / "ArchEngineLib.dll"
        print(f"[DLL] [{i}] {dll_path} - exists: {dll_path.exists()}")
        if dll_path.exists():
            print(f"[DLL] Found: {dll_path}")
            return dll_path

    print("[DLL] ArchEngineLib.dll not found in any search path")
    return None


class VulkanViewportWidget(QWidget):
    """
    Qt widget that embeds the Vulkan renderer.

    Usage:
        viewport = VulkanViewportWidget()
        layout.addWidget(viewport)

        # Load building data
        viewport.load_json(building_data)

        # Or load from file
        viewport.load_file("path/to/building.json")
    """

    # Signals
    initialized = pyqtSignal()
    load_complete = pyqtSignal(int)  # element count
    rooms_loaded = pyqtSignal(list)  # list of room dicts
    error_occurred = pyqtSignal(str)
    camera_distance_changed = pyqtSignal(float)  # distance from target
    lod_level_changed = pyqtSignal(int)  # LOD level 1-5 (shift+scroll)
    gravity_changed = pyqtSignal(float, float, float)  # design, client, build
    lod_changed = pyqtSignal(int, float)  # level, transition
    section_changed = pyqtSignal(bool, int, float, bool)  # enabled, axis, height, flipped
    element_selected = pyqtSignal(int)  # element index (-1 for deselect)
    element_hovered = pyqtSignal(str, object)  # element_type, element_id (None for no hover)
    rooms_loaded = pyqtSignal(list)  # list of room data dicts

    def __init__(self, parent=None):
        super().__init__(parent)

        self._lib: Optional[ctypes.CDLL] = None
        self._initialized = False
        self._render_timer: Optional[QTimer] = None

        # Camera state for mouse interaction (distances in FEET - C++ converts mm to ft)
        self._camera_yaw = 0.5
        self._camera_pitch = 0.4
        self._camera_distance = 60.0  # 60 feet from target
        self._camera_target = [26.0, 10.0, 20.0]  # Building center approx (feet)
        self._free_look_mode = False  # Toggle with Spacebar
        self._free_look_cam_pos = None  # Stored camera position in free look mode
        self._last_mouse_pos = None
        self._dragging = False
        self._panning = False  # True for pan, False for orbit

        self._rendering = False  # Prevent concurrent renders
        self._loading = False    # Prevent concurrent loads
        self._api_lock = threading.Lock()  # Prevent load during render
        self._terrain_gen_api_available = False  # Set during library binding

        # Section drag state
        self._section_mode = False  # Press 'S' to toggle
        self._section_dragging = False

        # Move House mode - click on terrain to relocate building
        self._move_house_mode = False  # Press 'M' to toggle

        # Selection manager for Python-side picking + Tab cycling
        self._selection_manager: Optional[SelectionManager] = None
        self._document = None  # Set via set_document()
        self._last_pick_pos = (0, 0)  # For Tab cycling detection

        # Hover state for visual feedback
        self._hovered_element: Optional[tuple] = None  # (element_type, element_id)
        self._hover_update_timer = None  # Throttle hover updates

        # Navigation overlay (optional)
        self._nav_overlay = None

        # Section drag state
        self._section_mode = False  # Press 'S' to toggle
        self._section_dragging = False

        # Selection manager for Python-side picking + Tab cycling
        self._selection_manager: Optional[SelectionManager] = None
        self._document = None  # Set via set_document()
        self._last_pick_pos = (0, 0)  # For Tab cycling detection

        # Hover state for visual feedback
        self._hovered_element: Optional[tuple] = None  # (element_type, element_id)
        self._hover_update_timer = None  # Throttle hover updates

        # Navigation overlay (optional, may be set later)
        self._nav_overlay = None

        # Widget setup
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.setAttribute(Qt.WidgetAttribute.WA_PaintOnScreen, True)
        self.setMouseTracking(True)  # Enable hover detection without button press
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setMinimumSize(400, 300)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # Load the library
        self._load_library()

    def _load_library(self):
        """Load ArchEngineLib.dll and set up function signatures."""
        dll_path = _find_dll()
        if dll_path is None:
            print("[VulkanWidget] ArchEngineLib.dll not found")
            return

        try:
            self._lib = ctypes.CDLL(str(dll_path))

            # Define function signatures
            self._lib.arch_init.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
            self._lib.arch_init.restype = ctypes.c_int

            self._lib.arch_shutdown.argtypes = []
            self._lib.arch_shutdown.restype = None

            self._lib.arch_is_initialized.argtypes = []
            self._lib.arch_is_initialized.restype = ctypes.c_int

            self._lib.arch_load_json.argtypes = [ctypes.c_char_p]
            self._lib.arch_load_json.restype = ctypes.c_int

            self._lib.arch_load_file.argtypes = [ctypes.c_char_p]
            self._lib.arch_load_file.restype = ctypes.c_int

            self._lib.arch_render_frame.argtypes = []
            self._lib.arch_render_frame.restype = ctypes.c_int

            self._lib.arch_resize.argtypes = [ctypes.c_int, ctypes.c_int]
            self._lib.arch_resize.restype = None

            self._lib.arch_set_camera.argtypes = [ctypes.c_float, ctypes.c_float, ctypes.c_float]
            self._lib.arch_set_camera.restype = None

            self._lib.arch_set_camera_target.argtypes = [ctypes.c_float, ctypes.c_float, ctypes.c_float]
            self._lib.arch_set_camera_target.restype = None

            self._lib.arch_set_camera_pose.argtypes = [ctypes.c_float, ctypes.c_float, ctypes.c_float,
                                                       ctypes.c_float, ctypes.c_float, ctypes.c_float]
            self._lib.arch_set_camera_pose.restype = None

            self._lib.arch_reset_camera.argtypes = []
            self._lib.arch_reset_camera.restype = None

            self._lib.arch_get_camera_state.argtypes = [
                ctypes.POINTER(ctypes.c_float),
                ctypes.POINTER(ctypes.c_float),
                ctypes.POINTER(ctypes.c_float),
                ctypes.POINTER(ctypes.c_float)
            ]
            self._lib.arch_get_camera_state.restype = None

            self._lib.arch_set_viz_mode.argtypes = [ctypes.c_int]
            self._lib.arch_set_viz_mode.restype = None

            # LOD API (optional - may not be in all DLL versions)
            try:
                self._lib.arch_set_lod_level.argtypes = [ctypes.c_int]
                self._lib.arch_set_lod_level.restype = None
                self._lib.arch_get_lod_level.argtypes = []
                self._lib.arch_get_lod_level.restype = ctypes.c_int
                self._has_lod_api = True
            except AttributeError:
                self._has_lod_api = False

            self._lib.arch_get_error.argtypes = []
            self._lib.arch_get_error.restype = ctypes.c_char_p

            # Selection API (optional - may not be in all DLL versions)
            try:
                self._lib.arch_select_element.argtypes = [ctypes.c_int]
                self._lib.arch_select_element.restype = None

                self._lib.arch_get_element_count.argtypes = []
                self._lib.arch_get_element_count.restype = ctypes.c_int

                self._lib.arch_get_selected_element.argtypes = []
                self._lib.arch_get_selected_element.restype = ctypes.c_int

                self._lib.arch_pick_element.argtypes = [ctypes.c_int, ctypes.c_int]
                self._lib.arch_pick_element.restype = ctypes.c_int
            except AttributeError:
                print("[VulkanWidget] Selection API not available in this DLL")

            print(f"[VulkanWidget] Loaded {dll_path}")

            # Store DLL directory for shader loading
            self._dll_dir = dll_path.parent

            # Section clipping API (optional)
            try:
                self._lib.arch_set_clipping_enabled.argtypes = [ctypes.c_int]
                self._lib.arch_set_clipping_enabled.restype = None

                self._lib.arch_get_clipping_enabled.argtypes = []
                self._lib.arch_get_clipping_enabled.restype = ctypes.c_int

                self._lib.arch_set_clip_axis.argtypes = [ctypes.c_int]
                self._lib.arch_set_clip_axis.restype = None

                self._lib.arch_get_clip_axis.argtypes = []
                self._lib.arch_get_clip_axis.restype = ctypes.c_int

                self._lib.arch_set_clip_height.argtypes = [ctypes.c_float]
                self._lib.arch_set_clip_height.restype = None

                self._lib.arch_get_clip_height.argtypes = []
                self._lib.arch_get_clip_height.restype = ctypes.c_float

                self._lib.arch_set_clip_flipped.argtypes = [ctypes.c_int]
                self._lib.arch_set_clip_flipped.restype = None

                self._lib.arch_get_clip_flipped.argtypes = []
                self._lib.arch_get_clip_flipped.restype = ctypes.c_int

                self._lib.arch_set_section_floor_plan.argtypes = [ctypes.c_float]
                self._lib.arch_set_section_floor_plan.restype = None

                self._lib.arch_set_section_elevation.argtypes = [ctypes.c_int, ctypes.c_float]
                self._lib.arch_set_section_elevation.restype = None

                # Section box API (multi-plane clipping)
                self._lib.arch_set_section_box.argtypes = [ctypes.c_float, ctypes.c_float, ctypes.c_float,
                                                          ctypes.c_float, ctypes.c_float, ctypes.c_float]
                self._lib.arch_set_section_box.restype = None

                self._lib.arch_clear_section_box.argtypes = []
                self._lib.arch_clear_section_box.restype = None

                self._lib.arch_has_section_box.argtypes = []
                self._lib.arch_has_section_box.restype = ctypes.c_int

                self._lib.arch_get_section_box.argtypes = [ctypes.POINTER(ctypes.c_float)] * 6
                self._lib.arch_get_section_box.restype = ctypes.c_int

                self._lib.arch_set_clip_plane_at.argtypes = [ctypes.c_int, ctypes.c_float, ctypes.c_float,
                                                            ctypes.c_float, ctypes.c_float, ctypes.c_int]
                self._lib.arch_set_clip_plane_at.restype = None

                self._lib.arch_get_clip_plane_at.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_float),
                                                            ctypes.POINTER(ctypes.c_float),
                                                            ctypes.POINTER(ctypes.c_float),
                                                            ctypes.POINTER(ctypes.c_float)]
                self._lib.arch_get_clip_plane_at.restype = ctypes.c_int

                self._lib.arch_get_num_clip_planes.argtypes = []
                self._lib.arch_get_num_clip_planes.restype = ctypes.c_int
            except AttributeError:
                print("[VulkanWidget] Section clipping API not available")

            # Material style API (optional)
            try:
                self._lib.arch_set_material_style.argtypes = [ctypes.c_int]
                self._lib.arch_set_material_style.restype = None

                self._lib.arch_get_material_style.argtypes = []
                self._lib.arch_get_material_style.restype = ctypes.c_int
            except AttributeError:
                print("[VulkanWidget] Material style API not available")

            # Material application API
            try:
                self._lib.arch_apply_material_to_element.argtypes = [ctypes.c_int, ctypes.c_char_p]
                self._lib.arch_apply_material_to_element.restype = ctypes.c_int

                self._lib.arch_apply_material_to_batch.argtypes = [
                    ctypes.POINTER(ctypes.c_int), ctypes.c_int, ctypes.c_char_p
                ]
                self._lib.arch_apply_material_to_batch.restype = ctypes.c_int

                self._lib.arch_get_element_material_name.argtypes = [
                    ctypes.c_int, ctypes.c_char_p, ctypes.c_int
                ]
                self._lib.arch_get_element_material_name.restype = ctypes.c_int

                self._has_material_api = True
                print("[VulkanWidget] Material application API loaded")
            except AttributeError:
                self._has_material_api = False
                print("[VulkanWidget] Material application API not available")

            # Try to load extended post-processing API (may not be in older DLLs)
            try:
                # Shadows & Lighting API
                self._lib.arch_set_shadows_enabled.argtypes = [ctypes.c_int]
                self._lib.arch_set_shadows_enabled.restype = None

                self._lib.arch_get_shadows_enabled.argtypes = []
                self._lib.arch_get_shadows_enabled.restype = ctypes.c_int

                self._lib.arch_set_light_direction.argtypes = [ctypes.c_float, ctypes.c_float, ctypes.c_float]
                self._lib.arch_set_light_direction.restype = None

                self._lib.arch_get_light_direction.argtypes = [
                    ctypes.POINTER(ctypes.c_float),
                    ctypes.POINTER(ctypes.c_float),
                    ctypes.POINTER(ctypes.c_float)
                ]
                self._lib.arch_get_light_direction.restype = None

                # SSAO API
                self._lib.arch_set_ssao_enabled.argtypes = [ctypes.c_int]
                self._lib.arch_set_ssao_enabled.restype = None

                self._lib.arch_get_ssao_enabled.argtypes = []
                self._lib.arch_get_ssao_enabled.restype = ctypes.c_int

                self._lib.arch_set_ssao_radius.argtypes = [ctypes.c_float]
                self._lib.arch_set_ssao_radius.restype = None

                self._lib.arch_get_ssao_radius.argtypes = []
                self._lib.arch_get_ssao_radius.restype = ctypes.c_float

                self._lib.arch_set_ssao_intensity.argtypes = [ctypes.c_float]
                self._lib.arch_set_ssao_intensity.restype = None

                self._lib.arch_get_ssao_intensity.argtypes = []
                self._lib.arch_get_ssao_intensity.restype = ctypes.c_float

                # Bloom API
                self._lib.arch_set_bloom_enabled.argtypes = [ctypes.c_int]
                self._lib.arch_set_bloom_enabled.restype = None

                self._lib.arch_get_bloom_enabled.argtypes = []
                self._lib.arch_get_bloom_enabled.restype = ctypes.c_int

                self._lib.arch_set_bloom_threshold.argtypes = [ctypes.c_float]
                self._lib.arch_set_bloom_threshold.restype = None

                self._lib.arch_get_bloom_threshold.argtypes = []
                self._lib.arch_get_bloom_threshold.restype = ctypes.c_float

                self._lib.arch_set_bloom_intensity.argtypes = [ctypes.c_float]
                self._lib.arch_set_bloom_intensity.restype = None

                self._lib.arch_get_bloom_intensity.argtypes = []
                self._lib.arch_get_bloom_intensity.restype = ctypes.c_float

                # Tonemapping & Exposure API
                self._lib.arch_set_exposure.argtypes = [ctypes.c_float]
                self._lib.arch_set_exposure.restype = None

                self._lib.arch_get_exposure.argtypes = []
                self._lib.arch_get_exposure.restype = ctypes.c_float

                self._lib.arch_set_tonemap_mode.argtypes = [ctypes.c_int]
                self._lib.arch_set_tonemap_mode.restype = None

                self._lib.arch_get_tonemap_mode.argtypes = []
                self._lib.arch_get_tonemap_mode.restype = ctypes.c_int

                # Camera view settings API
                self._lib.arch_set_camera_fov.argtypes = [ctypes.c_float]
                self._lib.arch_set_camera_fov.restype = None

                self._lib.arch_get_camera_fov.argtypes = []
                self._lib.arch_get_camera_fov.restype = ctypes.c_float

                self._lib.arch_set_orthographic.argtypes = [ctypes.c_int]
                self._lib.arch_set_orthographic.restype = None

                self._lib.arch_get_orthographic.argtypes = []
                self._lib.arch_get_orthographic.restype = ctypes.c_int

                # Room export API
                self._lib.arch_get_room_count.argtypes = []
                self._lib.arch_get_room_count.restype = ctypes.c_int

                # TODO: Define ArchRoomData ctypes Structure to enable these APIs
                # self._lib.arch_get_room_data.argtypes = [ctypes.c_int, ctypes.POINTER(ArchRoomData)]
                # self._lib.arch_get_room_data.restype = ctypes.c_int
                # self._lib.arch_get_all_rooms.argtypes = [ctypes.POINTER(ArchRoomData), ctypes.c_int]
                # self._lib.arch_get_all_rooms.restype = ctypes.c_int

                # Material settings API
                self._lib.arch_set_uv_scale.argtypes = [ctypes.c_float, ctypes.c_float]
                self._lib.arch_set_uv_scale.restype = None

                self._lib.arch_get_uv_scale.argtypes = [
                    ctypes.POINTER(ctypes.c_float),
                    ctypes.POINTER(ctypes.c_float)
                ]
                self._lib.arch_get_uv_scale.restype = None

                self._lib.arch_set_roughness_multiplier.argtypes = [ctypes.c_float]
                self._lib.arch_set_roughness_multiplier.restype = None

                self._lib.arch_get_roughness_multiplier.argtypes = []
                self._lib.arch_get_roughness_multiplier.restype = ctypes.c_float

                self._lib.arch_set_metallic_multiplier.argtypes = [ctypes.c_float]
                self._lib.arch_set_metallic_multiplier.restype = None

                self._lib.arch_get_metallic_multiplier.argtypes = []
                self._lib.arch_get_metallic_multiplier.restype = ctypes.c_float

                self._lib.arch_set_ao_strength.argtypes = [ctypes.c_float]
                self._lib.arch_set_ao_strength.restype = None

                self._lib.arch_get_ao_strength.argtypes = []
                self._lib.arch_get_ao_strength.restype = ctypes.c_float

                # Terrain offset API
                self._lib.arch_set_terrain_offset.argtypes = [ctypes.c_float, ctypes.c_float, ctypes.c_float]
                self._lib.arch_set_terrain_offset.restype = None

                self._lib.arch_get_terrain_offset.argtypes = [
                    ctypes.POINTER(ctypes.c_float),
                    ctypes.POINTER(ctypes.c_float),
                    ctypes.POINTER(ctypes.c_float)
                ]
                self._lib.arch_get_terrain_offset.restype = None

                self._lib.arch_get_terrain_info.argtypes = [
                    ctypes.POINTER(ctypes.c_float),  # width
                    ctypes.POINTER(ctypes.c_float),  # depth
                    ctypes.POINTER(ctypes.c_float),  # min_elev
                    ctypes.POINTER(ctypes.c_float)   # max_elev
                ]
                self._lib.arch_get_terrain_info.restype = ctypes.c_int

                self._lib.arch_has_terrain.argtypes = []
                self._lib.arch_has_terrain.restype = ctypes.c_int

                # Terrain material API
                self._lib.arch_set_terrain_material.argtypes = [ctypes.c_float, ctypes.c_float]
                self._lib.arch_set_terrain_material.restype = None

                self._lib.arch_set_terrain_texture.argtypes = [ctypes.c_char_p]
                self._lib.arch_set_terrain_texture.restype = None

                # High-performance terrain generation API (C++)
                try:
                    self._lib.arch_generate_terrain_from_points.argtypes = [
                        ctypes.c_void_p,  # points array (ArchElevationPoint*)
                        ctypes.c_int,     # point_count
                        ctypes.c_void_p,  # boundary_ft array
                        ctypes.c_int,     # boundary_vertex_count
                        ctypes.c_float, ctypes.c_float,  # bounds_lat_min, max
                        ctypes.c_float, ctypes.c_float,  # bounds_lng_min, max
                        ctypes.c_float, ctypes.c_float,  # width_ft, depth_ft
                        ctypes.c_int,     # grid_resolution
                        ctypes.c_float, ctypes.c_float,  # origin_x_ft, origin_z_ft
                        ctypes.c_float    # rotation_deg
                    ]
                    self._lib.arch_generate_terrain_from_points.restype = ctypes.c_int
                    self._terrain_gen_api_available = True
                    print("[VulkanWidget] C++ terrain generation API bound successfully")
                except Exception as e:
                    self._terrain_gen_api_available = False
                    print(f"[VulkanWidget] FAILED to bind terrain generation API: {e}")

                self._lib.arch_get_terrain_generation_progress.argtypes = [
                    ctypes.POINTER(ctypes.c_float),
                    ctypes.POINTER(ctypes.c_char_p)
                ]
                self._lib.arch_get_terrain_generation_progress.restype = ctypes.c_int

                # Building placement API
                self._lib.arch_set_building_position.argtypes = [ctypes.c_float, ctypes.c_float, ctypes.c_float]
                self._lib.arch_set_building_position.restype = None

                self._lib.arch_get_building_position.argtypes = [
                    ctypes.POINTER(ctypes.c_float),
                    ctypes.POINTER(ctypes.c_float),
                    ctypes.POINTER(ctypes.c_float)
                ]
                self._lib.arch_get_building_position.restype = None

                self._lib.arch_get_terrain_elevation_at.argtypes = [
                    ctypes.c_float, ctypes.c_float,
                    ctypes.POINTER(ctypes.c_float)
                ]
                self._lib.arch_get_terrain_elevation_at.restype = ctypes.c_int

                self._lib.arch_place_building_on_terrain.argtypes = [ctypes.c_float, ctypes.c_float]
                self._lib.arch_place_building_on_terrain.restype = ctypes.c_int

                self._lib.arch_screen_to_world_ray.argtypes = [
                    ctypes.c_int, ctypes.c_int,  # screen coords
                    ctypes.POINTER(ctypes.c_float), ctypes.POINTER(ctypes.c_float), ctypes.POINTER(ctypes.c_float),  # origin
                    ctypes.POINTER(ctypes.c_float), ctypes.POINTER(ctypes.c_float), ctypes.POINTER(ctypes.c_float)   # direction
                ]
                self._lib.arch_screen_to_world_ray.restype = None

                self._lib.arch_raycast_terrain.argtypes = [
                    ctypes.c_float, ctypes.c_float, ctypes.c_float,  # origin
                    ctypes.c_float, ctypes.c_float, ctypes.c_float,  # direction
                    ctypes.POINTER(ctypes.c_float), ctypes.POINTER(ctypes.c_float), ctypes.POINTER(ctypes.c_float)  # hit point
                ]
                self._lib.arch_raycast_terrain.restype = ctypes.c_int

                print("[VulkanWidget] Extended post-processing API loaded")

                # Path Tracer API (optional - for offline high-quality renders)
                try:
                    self._lib.arch_pt_set_config.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
                    self._lib.arch_pt_set_config.restype = ctypes.c_int

                    self._lib.arch_pt_start_render.argtypes = []
                    self._lib.arch_pt_start_render.restype = ctypes.c_int

                    self._lib.arch_pt_render_frame.argtypes = []
                    self._lib.arch_pt_render_frame.restype = ctypes.c_int

                    self._lib.arch_pt_get_progress.argtypes = [ctypes.POINTER(ctypes.c_float)]
                    self._lib.arch_pt_get_progress.restype = ctypes.c_int

                    self._lib.arch_pt_stop.argtypes = []
                    self._lib.arch_pt_stop.restype = None

                    self._lib.arch_pt_is_rendering.argtypes = []
                    self._lib.arch_pt_is_rendering.restype = ctypes.c_int

                    self._lib.arch_pt_is_complete.argtypes = []
                    self._lib.arch_pt_is_complete.restype = ctypes.c_int

                    self._lib.arch_pt_get_sample_count.argtypes = []
                    self._lib.arch_pt_get_sample_count.restype = ctypes.c_int

                    self._lib.arch_pt_save_png.argtypes = [ctypes.c_char_p, ctypes.c_float]
                    self._lib.arch_pt_save_png.restype = ctypes.c_int

                    self._lib.arch_pt_save_hdr.argtypes = [ctypes.c_char_p]
                    self._lib.arch_pt_save_hdr.restype = ctypes.c_int

                    self._lib.arch_pt_apply_denoise.argtypes = []
                    self._lib.arch_pt_apply_denoise.restype = ctypes.c_int

                    self._lib.arch_pt_set_exposure.argtypes = [ctypes.c_float]
                    self._lib.arch_pt_set_exposure.restype = None

                    self._lib.arch_pt_get_exposure.argtypes = []
                    self._lib.arch_pt_get_exposure.restype = ctypes.c_float

                    self._lib.arch_pt_set_tonemap_mode.argtypes = [ctypes.c_int]
                    self._lib.arch_pt_set_tonemap_mode.restype = None

                    self._lib.arch_pt_get_tonemap_mode.argtypes = []
                    self._lib.arch_pt_get_tonemap_mode.restype = ctypes.c_int

                    self._has_path_tracer = True
                    print("[VulkanWidget] Path Tracer API loaded")
                except AttributeError:
                    self._has_path_tracer = False

            except AttributeError as e:
                print(f"[VulkanWidget] Extended API not available: {e}")

        except Exception as e:
            print(f"[VulkanWidget] Failed to load library: {e}")
            self._lib = None

    def showEvent(self, event):
        """Initialize renderer when widget is first shown."""
        super().showEvent(event)
        print(f"[VulkanWidget] showEvent: isVisible={self.isVisible()}, _initialized={self._initialized}, _lib={self._lib is not None}")

        if not self._initialized and self._lib is not None:
            print("[VulkanWidget] Scheduling initialization in 100ms...")
            # Defer initialization to allow window to be fully created
            QTimer.singleShot(100, self._initialize_renderer)

    def _initialize_renderer(self):
        """Initialize the Vulkan renderer with our window handle."""
        print(f"[VulkanWidget] _initialize_renderer called, _initialized={self._initialized}, _lib={self._lib is not None}")
        if self._initialized or self._lib is None:
            print(f"[VulkanWidget] Skipping init: _initialized={self._initialized}, _lib={self._lib is not None}")
            return

        try:
            # Get native window handle
            hwnd = int(self.winId())
            width = self.width()
            height = self.height()

            print(f"[VulkanWidget] Initializing renderer: HWND={hwnd}, size={width}x{height}")
            print(f"[VulkanWidget] Window isVisible={self.isVisible()}, winId={self.winId()}")

            # Change to DLL directory so shaders can be found
            original_cwd = os.getcwd()
            if hasattr(self, '_dll_dir') and self._dll_dir.exists():
                os.chdir(self._dll_dir)
                print(f"[VulkanWidget] Changed to DLL dir: {self._dll_dir}")

            result = self._lib.arch_init(ctypes.c_void_p(hwnd), width, height)

            # Restore original working directory
            os.chdir(original_cwd)
            if result != 0:
                error = self._lib.arch_get_error()
                if error:
                    error = error.decode('utf-8')
                else:
                    error = "Unknown error"
                print(f"[VulkanWidget] Init failed: {error}")
                self.error_occurred.emit(f"Init failed: {error}")
                return

            self._initialized = True
            print("[VulkanWidget] Renderer initialized")

            # Start render loop - slow rate for stability
            self._render_timer = QTimer(self)
            self._render_timer.timeout.connect(self._render_frame)
            self._render_timer.start(100)  # 10 FPS for stability

            # Don't render immediately - wait for load_json to provide data first

            self.initialized.emit()
        except Exception as e:
            print(f"[VulkanWidget] Initialization exception: {e}")
            import traceback
            traceback.print_exc()
            self.error_occurred.emit(f"Init exception: {e}")

    def _render_frame(self):
        """Render a single frame."""
        if not self._initialized or self._lib is None:
            return

        # Skip if no data loaded yet (prevents depth buffer issues on empty scene)
        if not getattr(self, '_has_data', False):
            return

        # Skip if already rendering
        if self._rendering:
            return

        # Skip if widget not visible
        if not self.isVisible():
            return

        # Try to acquire lock (non-blocking) - skip frame if load_json is running
        if not self._api_lock.acquire(blocking=False):
            return

        # Track render count for diagnostics
        if not hasattr(self, '_render_count'):
            self._render_count = 0
        self._render_count += 1

        # Log first few frames after restart for debugging
        if not hasattr(self, '_frames_since_load'):
            self._frames_since_load = 0
        self._frames_since_load += 1
        if self._frames_since_load <= 3:
            pass  # Debug: track frames after load

        try:
            self._rendering = True

            # Start frame timing
            diag = get_diagnostics()
            if diag:
                diag.frame_start()

            # Update camera
            # Only call arch_set_camera if NOT in free look mode (free look uses arch_set_camera_pose directly)
            if not self._free_look_mode:
                self._lib.arch_set_camera(
                    ctypes.c_float(self._camera_yaw),
                    ctypes.c_float(self._camera_pitch),
                    ctypes.c_float(self._camera_distance)
                )

            # Render
            result = self._lib.arch_render_frame()

            # End frame timing
            if diag:
                frame_time = diag.frame_end()

            if result != 0:
                # Render failed - stop the render loop
                print("[VulkanWidget] Render failed, stopping render loop")
                if self._render_timer:
                    self._render_timer.stop()
                self._initialized = False
                return

            # FPS logging disabled for performance
            pass
        except Exception as e:
            print(f"[VulkanWidget] Render exception: {e}")
            import traceback
            traceback.print_exc()
            if self._render_timer:
                self._render_timer.stop()
            self._initialized = False
            return
        finally:
            self._rendering = False
            self._api_lock.release()

    def resizeEvent(self, event):
        """Handle widget resize."""
        super().resizeEvent(event)

        # Only resize if data is loaded (prevents depth buffer issues on empty scene)
        if self._initialized and self._lib is not None and getattr(self, '_has_data', False):
            with self._api_lock:
                self._lib.arch_resize(event.size().width(), event.size().height())

    def closeEvent(self, event):
        """Cleanup on close."""
        self._shutdown()
        super().closeEvent(event)

    def _shutdown(self):
        """Shutdown the renderer."""
        if self._render_timer:
            self._render_timer.stop()
            self._render_timer = None

        if self._initialized and self._lib is not None:
            try:
                print("[VulkanWidget] Shutting down renderer...")
                self._lib.arch_shutdown()
                print("[VulkanWidget] Renderer shutdown complete")
            except Exception as e:
                print(f"[VulkanWidget] Shutdown error: {e}")
            finally:
                self._initialized = False

    # =========================================================================
    # Public API
    # =========================================================================

    def load_json(self, data: dict) -> bool:
        """
        Load building data from a dictionary.

        Args:
            data: Building data in QBD JSON format

        Returns:
            True on success
        """
        if not self._initialized or self._lib is None:
            return False

        # Skip if already loading (prevents queue buildup)
        if self._loading:
            return False

        self._loading = True
        self._frames_since_load = 0  # Reset frame counter for debug

        # Stop render timer and acquire lock to ensure no rendering during geometry update
        if self._render_timer:
            self._render_timer.stop()

        rooms_to_emit = None
        load_count = 0
        success = False

        try:
            with self._api_lock:
                # Check for C++ terrain generation option
                terrain_settings = data.get('terrain_generation_settings', {})
                use_cpp_terrain = terrain_settings.get('use_cpp_generation', False)
                google_maps = data.get('google_maps', {})
                elevation_grid = google_maps.get('elevation_grid', {})
                boundary = google_maps.get('boundary', {})
                building_origin = data.get('building_origin', {})

                # Check terrain API availability
                has_api = getattr(self, '_terrain_gen_api_available', False)

                # Use C++ terrain generation if we have elevation data and settings say to use it
                if use_cpp_terrain and elevation_grid and has_api:
                    # Using C++ terrain generation

                    # Remove terrain_mesh from JSON to let C++ generate it
                    data_for_json = {k: v for k, v in data.items() if k != 'terrain_mesh'}

                    # Verify building_origin is in the JSON being sent
                    if 'building_origin' in data_for_json:
                        bo = data_for_json['building_origin']
                        pass  # building_origin present
                    else:
                        pass  # No building_origin in JSON

                    # Load building geometry first (without terrain)
                    json_str = json.dumps(data_for_json).encode('utf-8')
                    result = self._lib.arch_load_json(json_str)

                    if result == 0:
                        # Now generate terrain in C++
                        grid_res = terrain_settings.get('grid_resolution', 250)
                        width_ft = data.get('property_width_ft', 100)
                        depth_ft = data.get('property_depth_ft', 100)
                        origin_x = building_origin.get('x_ft', 0)
                        origin_z = building_origin.get('z_ft', 0)
                        rotation = building_origin.get('rotation_deg', 0)

                        # Compute bounds from elevation data
                        elev_points = list(elevation_grid.values())
                        if elev_points:
                            lats = [p.get('lat', 0) for p in elev_points]
                            lngs = [p.get('lng', 0) for p in elev_points]
                            computed_bounds = {
                                'lat_min': min(lats),
                                'lat_max': max(lats),
                                'lng_min': min(lngs),
                                'lng_max': max(lngs),
                            }
                        else:
                            computed_bounds = {'lat_min': 0, 'lat_max': 0, 'lng_min': 0, 'lng_max': 0}

                        # Use map boundary bounds if available, otherwise computed bounds
                        if boundary.get('lat_min') and boundary.get('lat_max'):
                            bounds_to_use = {
                                'lat_min': boundary['lat_min'],
                                'lat_max': boundary['lat_max'],
                                'lng_min': boundary['lng_min'],
                                'lng_max': boundary['lng_max'],
                            }
                        else:
                            bounds_to_use = computed_bounds

                        self.generate_terrain_from_points(
                            elevation_data=elevation_grid,
                            boundary_ft=boundary.get('vertices_ft'),
                            bounds=bounds_to_use,
                            width_ft=width_ft,
                            depth_ft=depth_ft,
                            grid_resolution=grid_res,
                            origin_x_ft=origin_x,
                            origin_z_ft=origin_z,
                            rotation_deg=rotation
                        )
                else:
                    # Standard path: use pre-computed terrain mesh from Python
                    # Note: Building lift is now done at document level in _lift_building_to_terrain()
                    # to ensure roof generation uses correct wall heights
                    json_str = json.dumps(data).encode('utf-8')
                    result = self._lib.arch_load_json(json_str)

                if result == 0:
                    load_count = self._lib.arch_get_element_count()

                    # Check if terrain was loaded and place building
                    terrain_count = self._lib.arch_has_terrain()
                    if terrain_count > 0:
                        self._place_building_on_terrain(data)

                    # Force a sync render to process new geometry
                    self._lib.arch_render_frame()

                    # Enable render loop now that we have data
                    self._has_data = True

                    # Get rooms while we have the lock, but emit signal AFTER releasing lock
                    rooms_to_emit = self.get_rooms()
                    success = True
                else:
                    error = self._lib.arch_get_error().decode('utf-8')
                    print(f"[VulkanWidget] Load failed: {error}")
                    self.error_occurred.emit(error)
                    return False
        except Exception as e:
            print(f"[VulkanWidget] Exception during load: {e}")
            self._loading = False
            return False
        finally:
            self._loading = False
            # Restart render timer after a delay
            if self._render_timer and self._initialized:
                QTimer.singleShot(100, self._restart_render_timer)

        # Emit signals AFTER releasing the lock
        if success:
            self.load_complete.emit(load_count)
            if rooms_to_emit:
                self.rooms_loaded.emit(rooms_to_emit)
            return True
        return False

    def _restart_render_timer(self):
        """Restart the render timer after load completes."""
        if self._initialized and self._render_timer:
            self._render_timer.start(33)

    def load_file(self, file_path: str) -> bool:
        """
        Load building data from a file.

        Args:
            file_path: Path to JSON file

        Returns:
            True on success
        """
        if not self._initialized or self._lib is None:
            return False

        # Acquire lock to prevent render during load
        with self._api_lock:
            path_bytes = file_path.encode('utf-8')
            result = self._lib.arch_load_file(path_bytes)

            if result == 0:
                count = self._lib.arch_get_element_count()
                print(f"[VulkanWidget] Loaded {count} elements from {file_path}")
                self.load_complete.emit(count)
                return True
            else:
                error = self._lib.arch_get_error().decode('utf-8')
                print(f"[VulkanWidget] Load failed: {error}")
                self.error_occurred.emit(error)
                return False

    def _sample_terrain_elevation_ft(self, data: dict, x_ft: float, z_ft: float) -> float:
        """
        Sample terrain elevation at a given x_ft, z_ft position using IDW interpolation.
        Returns elevation in feet, normalized the same way as C++ terrain generation.
        """
        import math

        google_maps = data.get('google_maps', {})
        elevation_grid = google_maps.get('elevation_grid', {})
        width_ft = data.get('property_width_ft', 100)
        depth_ft = data.get('property_depth_ft', 100)

        if not elevation_grid:
            return 0.0

        elev_points = list(elevation_grid.values())
        if not elev_points:
            return 0.0

        # Get elevation range to compute offset (same logic as TerrainGenerator and C++)
        elevations = [p.get('elevation_ft', 0) for p in elev_points]
        min_elev = min(elevations)

        # Elevation offset so min_elevation maps to ~0 (same as terrain.py line 135)
        elevation_offset = -min_elev - 0.0328  # -0.0328 ft = -10 mm

        # Normalize x_ft, z_ft to 0-1 range
        norm_x = x_ft / width_ft if width_ft > 0 else 0.5
        norm_z = z_ft / depth_ft if depth_ft > 0 else 0.5

        # IDW interpolation: sample from elevation points based on their normalized positions
        # The elevation grid is organized by lat/lng, so we need to map normalized position to grid
        lats = sorted(set(p.get('lat', 0) for p in elev_points))
        lngs = sorted(set(p.get('lng', 0) for p in elev_points))

        lat_min, lat_max = min(lats), max(lats)
        lng_min, lng_max = min(lngs), max(lngs)

        # Map normalized position to lat/lng
        # X maps to lng (east-west), Z maps to lat (north-south)
        target_lng = lng_min + norm_x * (lng_max - lng_min) if lng_max != lng_min else lng_min
        target_lat = lat_min + norm_z * (lat_max - lat_min) if lat_max != lat_min else lat_min

        # IDW interpolation
        total_weight = 0.0
        weighted_elev = 0.0
        search_radius = max(lat_max - lat_min, lng_max - lng_min) * 0.3  # Search 30% of extent

        for point in elev_points:
            plat = point.get('lat', 0)
            plng = point.get('lng', 0)
            pelev = point.get('elevation_ft', 0)

            # Distance in lat/lng space
            dlat = plat - target_lat
            dlng = plng - target_lng
            dist = math.sqrt(dlat * dlat + dlng * dlng)

            if dist < search_radius or search_radius == 0:
                weight = 1.0 / (dist + 0.0001)  # Avoid div by zero
                weighted_elev += pelev * weight
                total_weight += weight

        if total_weight > 0:
            sampled_elev = weighted_elev / total_weight
        else:
            # Fallback: use average elevation
            sampled_elev = sum(elevations) / len(elevations)

        # Apply offset to get the same Y coordinate as terrain mesh
        final_elev_ft = sampled_elev + elevation_offset

        return final_elev_ft

    def _place_building_on_terrain(self, data: dict):
        """Place building on terrain - building is transformed by C++, we update camera to match."""
        try:
            # The C++ code transforms the building to building_origin position
            # Use building_origin for camera target (that's where the building actually is)
            building_origin = data.get('building_origin', {})

            if building_origin and 'x_mm' in building_origin:
                # Use the transformed building center from building_origin
                target_x_mm = building_origin['x_mm']
                target_z_mm = building_origin['z_mm']

                # Convert to feet for camera
                MM_TO_FT = 1 / 304.8
                target_x_ft = target_x_mm * MM_TO_FT
                target_z_ft = target_z_mm * MM_TO_FT

                # Sample terrain elevation at building origin position
                # The C++ code lifts the building by this amount
                terrain_elev_ft = self._sample_terrain_elevation_ft(
                    data,
                    building_origin.get('x_ft', target_x_ft),
                    building_origin.get('z_ft', target_z_ft)
                )

                # Camera target Y = terrain elevation + small offset above building base
                target_y_ft = terrain_elev_ft + 10.0  # 10ft above terrain at building origin

                self._camera_target = [target_x_ft, target_y_ft, target_z_ft]
                self._lib.arch_set_camera_target(
                    ctypes.c_float(target_x_ft),
                    ctypes.c_float(target_y_ft),
                    ctypes.c_float(target_z_ft)
                )

                pass  # Building placed at origin
            else:
                # Fallback: calculate from walls if no building_origin
                walls = data.get('walls_batch', data.get('walls', data.get('elements', [])))
                if walls:
                    min_x = min_z = float('inf')
                    max_x = max_z = float('-inf')
                    for wall in walls:
                        start = wall.get('start', [0, 0, 0])
                        end = wall.get('end', [0, 0, 0])
                        min_x = min(min_x, start[0], end[0])
                        max_x = max(max_x, start[0], end[0])
                        min_z = min(min_z, start[2], end[2])
                        max_z = max(max_z, start[2], end[2])

                    building_center_x = (min_x + max_x) / 2
                    building_center_z = (min_z + max_z) / 2

                    MM_TO_FT = 1 / 304.8
                    target_x_ft = building_center_x * MM_TO_FT
                    target_z_ft = building_center_z * MM_TO_FT

                    # Sample terrain elevation at building center
                    terrain_elev_ft = self._sample_terrain_elevation_ft(
                        data,
                        target_x_ft,
                        target_z_ft
                    )
                    target_y_ft = terrain_elev_ft + 10.0

                    self._camera_target = [target_x_ft, target_y_ft, target_z_ft]
                    self._lib.arch_set_camera_target(
                        ctypes.c_float(target_x_ft),
                        ctypes.c_float(target_y_ft),
                        ctypes.c_float(target_z_ft)
                    )

                    pass  # Camera targeted at building center

        except Exception as e:
            pass  # Silently handle errors in building placement

    def move_building_to(self, screen_x: int, screen_y: int) -> bool:
        """Move building to the terrain point under the screen coordinates."""
        if not self._initialized or not self._lib:
            return False

        # Get ray from screen point
        ox, oy, oz = ctypes.c_float(), ctypes.c_float(), ctypes.c_float()
        dx, dy, dz = ctypes.c_float(), ctypes.c_float(), ctypes.c_float()

        self._lib.arch_screen_to_world_ray(
            ctypes.c_int(screen_x), ctypes.c_int(screen_y),
            ctypes.byref(ox), ctypes.byref(oy), ctypes.byref(oz),
            ctypes.byref(dx), ctypes.byref(dy), ctypes.byref(dz)
        )

        # Raycast against terrain
        hx, hy, hz = ctypes.c_float(), ctypes.c_float(), ctypes.c_float()
        if self._lib.arch_raycast_terrain(
            ox.value, oy.value, oz.value,
            dx.value, dy.value, dz.value,
            ctypes.byref(hx), ctypes.byref(hy), ctypes.byref(hz)
        ):
            # Place building at hit point
            self._lib.arch_set_building_position(
                ctypes.c_float(hx.value),
                ctypes.c_float(hy.value),
                ctypes.c_float(hz.value)
            )
            print(f"[VulkanWidget] Building moved to: ({hx.value:.0f}, {hy.value:.0f}, {hz.value:.0f}) mm")
            return True

        return False

    def set_terrain_material(self, roughness: float = 0.85, metallic: float = 0.0):
        """Set terrain PBR material properties.

        Args:
            roughness: Surface roughness (0.0 = smooth/shiny, 1.0 = rough/matte)
            metallic: Metallic value (0.0 = dielectric, 1.0 = metal)
        """
        if self._initialized and self._lib and hasattr(self._lib, 'arch_set_terrain_material'):
            self._lib.arch_set_terrain_material(
                ctypes.c_float(roughness),
                ctypes.c_float(metallic)
            )

    def set_terrain_texture(self, material_name: str):
        """Set terrain texture/material by name.

        Args:
            material_name: Material name (e.g., "polyhaven/brown_mud_leaves_01_1k")
                          Use empty string "" for elevation-colored terrain
        """
        if self._initialized and self._lib and hasattr(self._lib, 'arch_set_terrain_texture'):
            name_bytes = material_name.encode('utf-8') if material_name else b""
            self._lib.arch_set_terrain_texture(name_bytes)
            print(f"[VulkanWidget] Terrain texture set to: {material_name or '(elevation colors)'}")

    def generate_terrain_from_points(
        self,
        elevation_data: dict,
        boundary_ft: list = None,
        bounds: dict = None,
        width_ft: float = 100,
        depth_ft: float = 100,
        grid_resolution: int = 250,
        origin_x_ft: float = 0,
        origin_z_ft: float = 0,
        rotation_deg: float = 0
    ) -> bool:
        """Generate terrain mesh from elevation points using high-performance C++.

        This is much faster than Python-based terrain generation (50-100x speedup).

        Args:
            elevation_data: Dict of {"lat,lng": {lat, lng, elevation_m, ...}} points
            boundary_ft: List of polygon vertices [[x,z], [x,z], ...] in feet, or None
            bounds: Dict with lat_min, lat_max, lng_min, lng_max
            width_ft: Property width in feet
            depth_ft: Property depth in feet
            grid_resolution: Mesh resolution (100=20k tris, 300=180k, 500=500k)
            origin_x_ft: Building origin X offset in feet
            origin_z_ft: Building origin Z offset in feet
            rotation_deg: Building rotation in degrees

        Returns:
            True on success, False on failure
        """
        if not self._initialized or not self._lib:
            print("[VulkanWidget] Not initialized for terrain generation")
            return False

        if not hasattr(self._lib, 'arch_generate_terrain_from_points'):
            print("[VulkanWidget] Terrain generation API not available")
            return False

        import numpy as np

        # Convert elevation data to numpy array
        points = list(elevation_data.values())
        if not points:
            print("[VulkanWidget] No elevation points provided")
            return False

        # Create structured array for elevation points (lat, lng, elevation_m)
        point_count = len(points)
        point_array = np.zeros((point_count, 3), dtype=np.float32)
        for i, pt in enumerate(points):
            point_array[i, 0] = pt.get('lat', 0)
            point_array[i, 1] = pt.get('lng', 0)
            point_array[i, 2] = pt.get('elevation_m', pt.get('elevation_ft', 0) / 3.28084)

        # Get bounds
        if bounds:
            lat_min = bounds.get('lat_min', point_array[:, 0].min())
            lat_max = bounds.get('lat_max', point_array[:, 0].max())
            lng_min = bounds.get('lng_min', point_array[:, 1].min())
            lng_max = bounds.get('lng_max', point_array[:, 1].max())
        else:
            lat_min, lat_max = point_array[:, 0].min(), point_array[:, 0].max()
            lng_min, lng_max = point_array[:, 1].min(), point_array[:, 1].max()

        # Prepare boundary array
        boundary_array = None
        boundary_count = 0
        if boundary_ft and len(boundary_ft) >= 3:
            boundary_count = len(boundary_ft)
            boundary_array = np.array(boundary_ft, dtype=np.float32).flatten()

        print(f"[VulkanWidget] C++ terrain generation: {point_count} points, grid={grid_resolution}")
        print(f"[VulkanWidget] Lat bounds: [{lat_min:.6f}, {lat_max:.6f}]")
        print(f"[VulkanWidget] Lng bounds: [{lng_min:.6f}, {lng_max:.6f}]")
        print(f"[VulkanWidget] Property: {width_ft:.1f}ft x {depth_ft:.1f}ft")
        print(f"[VulkanWidget] Origin: ({origin_x_ft:.1f}, {origin_z_ft:.1f})ft, rotation: {rotation_deg:.1f} deg")

        # Debug: show first few elevation points being sent
        print(f"[VulkanWidget] First 5 elevation points being sent:")
        for i in range(min(5, point_count)):
            print(f"[VulkanWidget]   [{i}] lat={point_array[i,0]:.6f}, lng={point_array[i,1]:.6f}, elev={point_array[i,2]:.2f}m")

        # Call C++ function
        result = self._lib.arch_generate_terrain_from_points(
            point_array.ctypes.data_as(ctypes.c_void_p),
            ctypes.c_int(point_count),
            boundary_array.ctypes.data_as(ctypes.c_void_p) if boundary_array is not None else None,
            ctypes.c_int(boundary_count),
            ctypes.c_float(lat_min), ctypes.c_float(lat_max),
            ctypes.c_float(lng_min), ctypes.c_float(lng_max),
            ctypes.c_float(width_ft), ctypes.c_float(depth_ft),
            ctypes.c_int(grid_resolution),
            ctypes.c_float(origin_x_ft), ctypes.c_float(origin_z_ft),
            ctypes.c_float(rotation_deg)
        )

        if result == 0:
            print("[VulkanWidget] C++ terrain generation successful")
            return True
        else:
            print(f"[VulkanWidget] C++ terrain generation failed with code {result}")
            return False

    def reset_camera(self):
        """Reset camera to fit the building - uses C++ calculated values."""
        if self._initialized and self._lib:
            # Let C++ calculate proper camera position from building bounds
            self._lib.arch_reset_camera()

            # Get actual values calculated by C++ from building bounds
            try:
                tx, ty, tz, dist = ctypes.c_float(), ctypes.c_float(), ctypes.c_float(), ctypes.c_float()
                self._lib.arch_get_camera_state(
                    ctypes.byref(tx), ctypes.byref(ty), ctypes.byref(tz), ctypes.byref(dist)
                )
                self._camera_target = [tx.value, ty.value, tz.value]
                self._camera_distance = dist.value
                print(f"[Viewport] Camera reset: target=[{tx.value:.0f}, {ty.value:.0f}, {tz.value:.0f}], distance={dist.value:.0f}mm")
            except Exception as e:
                print(f"[Viewport] Could not get camera state: {e}")
                self._camera_distance = 15000.0
                self._camera_target = [8000.0, 3000.0, 6000.0]

            self._camera_yaw = 0.5
            self._camera_pitch = 0.4
            self._free_look_cam_pos = None  # Clear free look camera position
            self.update()  # Trigger repaint

    def set_visualization_mode(self, mode: int):
        """
        Set visualization mode.

        Args:
            mode: 0=Structural, 1=Thermal, 2=Lighting, 3=Acoustic, 4=Material, 5=Wireframe
        """
        if self._initialized and self._lib:
            self._lib.arch_set_viz_mode(mode)

    def set_lod_level(self, level: int):
        """
        Set rendering LOD level. Adjusts tessellation, shadows, SSAO based on level.

        Args:
            level: 1=Topology, 2=Spatial, 3=Assembly, 4=Construction, 5=Fabrication
        """
        # Clamp level to valid range
        level = max(1, min(5, level))
        if self._initialized and self._lib and getattr(self, '_has_lod_api', False):
            try:
                self._lib.arch_set_lod_level(level)
                self.update()  # Request repaint
            except Exception as e:
                print(f"[Viewport] Error setting LOD level: {e}")

    def set_document(self, document):
        """Set document reference for Python-side picking."""
        self._document = document
        if HAS_SELECTION:
            self._selection_manager = get_selection_manager()
            self._selection_manager.set_document(document)
            self._update_selection_camera()

    def _update_selection_camera(self):
        """Update selection manager with current camera parameters."""
        if self._selection_manager:
            self._selection_manager.set_camera(
                self._camera_yaw * 57.2958,  # Convert to degrees
                self._camera_pitch * 57.2958,
                self._camera_distance  # Already in mm
            )
            self._selection_manager.set_viewport_size(self.width(), self.height())

    def select_element(self, index: int):
        """Select an element by index (-1 to clear)."""
        if self._initialized and self._lib:
            self._lib.arch_select_element(index)
            if index >= 0:
                self.element_selected.emit(index)

    def get_selected_element(self) -> int:
        """Get currently selected element index (-1 if none)."""
        if self._initialized and self._lib:
            return self._lib.arch_get_selected_element()
        return -1

    def get_rooms(self) -> list:
        """Get room data from renderer. Returns empty list if not available."""
        # Room data APIs are not yet fully implemented
        # TODO: Implement when ArchRoomData ctypes structure is defined
        return []

    def pick_element(self, screen_x: int, screen_y: int) -> int:
        """
        Pick element at screen coordinates.

        First tries DLL-based picking, then falls back to Python-side ray casting.

        Args:
            screen_x: X coordinate in widget pixels
            screen_y: Y coordinate in widget pixels

        Returns:
            Element index at that position, or -1 if no hit
        """
        # Try DLL picking first
        result = -1
        if self._initialized and self._lib:
            try:
                result = self._lib.arch_pick_element(screen_x, screen_y)
            except Exception:
                pass  # DLL function may not exist

        # Fall back to Python picking if DLL returns -1 and we have selection manager
        if result < 0 and self._selection_manager and self._document:
            self._update_selection_camera()
            hit = self._selection_manager.pick_and_select(screen_x, screen_y, add=False)
            if hit:
                # Convert element type and id to index for compatibility
                result = self._get_element_index(hit.element_type, hit.element_id)
                self._last_pick_pos = (screen_x, screen_y)

        return result

    def pick_all_at(self, screen_x: int, screen_y: int) -> list:
        """
        Pick all elements at screen coordinates (for Tab cycling).

        Returns list of (element_type, element_id, distance) tuples.
        """
        if self._selection_manager and self._document:
            self._update_selection_camera()
            hits = self._selection_manager.pick_at_screen(screen_x, screen_y)
            return [(h.element_type, h.element_id, h.distance) for h in hits]
        return []

    def cycle_selection(self, forward: bool = True) -> bool:
        """
        Cycle through overlapping elements at last pick position.

        Returns True if cycling succeeded, False if no elements to cycle.
        """
        if self._selection_manager:
            hit = self._selection_manager.cycle_selection(forward)
            if hit:
                index = self._get_element_index(hit.element_type, hit.element_id)
                if index >= 0:
                    self.select_element(index)
                current, total = self._selection_manager.get_cycle_info()
                print(f"[Viewport] Selection cycle: {current}/{total} - {hit.element_type} {hit.element_id}")
                return True
        return False

    def _get_element_index(self, element_type: str, element_id) -> int:
        """Convert element type/id to a linear index for the renderer."""
        if not self._document:
            return -1

        # Build index mapping - order matches renderer's element ordering
        offset = 0

        # Walls first
        if element_type == 'wall':
            return element_id if isinstance(element_id, int) else offset
        offset += len(self._document.walls)

        # Then rooms
        if element_type == 'room':
            room_ids = list(self._document._rooms.keys())
            if element_id in room_ids:
                return offset + room_ids.index(element_id)
            return offset
        offset += len(self._document._rooms)

        # Then doors
        if element_type == 'door':
            return offset + (element_id if isinstance(element_id, int) else 0)
        offset += len(self._document.doors)

        # Then windows
        if element_type == 'window':
            return offset + (element_id if isinstance(element_id, int) else 0)

        return -1

    def get_selection_cycle_info(self) -> tuple:
        """Get current selection cycle info (current_index, total_count)."""
        if self._selection_manager:
            return self._selection_manager.get_cycle_info()
        return (0, 0)

    @property
    def element_count(self) -> int:
        """Get number of elements in current building."""
        if self._initialized and self._lib:
            return self._lib.arch_get_element_count()
        return 0

    @property
    def is_initialized(self) -> bool:
        """Check if renderer is ready."""
        return self._initialized

    def get_rooms(self) -> list:
        """Get room data from the renderer via DLL."""
        if not self._initialized or self._lib is None:
            return []

        try:
            room_count = self._lib.arch_get_room_count()
            if room_count <= 0:
                return []

            rooms_array = (ArchRoomData * room_count)()
            result = self._lib.arch_get_all_rooms(rooms_array, room_count)
            if result <= 0:
                return []

            rooms = []
            for i in range(result):
                r = rooms_array[i]
                rooms.append({
                    'id': r.id.decode('utf-8', errors='ignore').rstrip('\x00'),
                    'name': r.name.decode('utf-8', errors='ignore').rstrip('\x00'),
                    'room_type': r.room_type.decode('utf-8', errors='ignore').rstrip('\x00'),
                    'bounds': {
                        'x': r.bounds_x,
                        'y': r.bounds_y,
                        'width': r.bounds_width,
                        'height': r.bounds_height,
                    },
                    'center': {'x': r.center_x, 'y': r.center_y},
                    'area': r.area,
                })
            return rooms
        except Exception as e:
            print(f"[VulkanWidget] get_rooms error: {e}")
            return []

    # =========================================================================
    # Section Clipping
    # =========================================================================

    def set_clipping_enabled(self, enabled: bool):
        """Enable or disable section clipping."""
        if self._initialized and self._lib:
            self._lib.arch_set_clipping_enabled(1 if enabled else 0)

    def get_clipping_enabled(self) -> bool:
        """Check if clipping is enabled."""
        if self._initialized and self._lib:
            return self._lib.arch_get_clipping_enabled() != 0
        return False

    def set_clip_axis(self, axis: int):
        """Set clipping axis (0=X, 1=Y, 2=Z)."""
        if self._initialized and self._lib:
            self._lib.arch_set_clip_axis(axis)

    def get_clip_axis(self) -> int:
        """Get current clipping axis."""
        if self._initialized and self._lib:
            return self._lib.arch_get_clip_axis()
        return 1

    def set_clip_height(self, height: float):
        """Set clipping plane position in feet."""
        if self._initialized and self._lib:
            self._lib.arch_set_clip_height(ctypes.c_float(height))

    def get_clip_height(self) -> float:
        """Get current clipping height in feet."""
        if self._initialized and self._lib:
            return self._lib.arch_get_clip_height()
        return 0.0

    def set_clip_flipped(self, flipped: bool):
        """Flip clipping direction."""
        if self._initialized and self._lib:
            self._lib.arch_set_clip_flipped(1 if flipped else 0)

    def get_clip_flipped(self) -> bool:
        """Check if clipping is flipped."""
        if self._initialized and self._lib:
            return self._lib.arch_get_clip_flipped() != 0
        return False

    def set_section_floor_plan(self, y_height: float):
        """Set up floor plan section at specified height."""
        if self._initialized and self._lib:
            self._lib.arch_set_section_floor_plan(ctypes.c_float(y_height))

    def set_section_elevation(self, axis: int, position: float):
        """Set up elevation section (axis 0=X, 2=Z)."""
        if self._initialized and self._lib:
            self._lib.arch_set_section_elevation(axis, ctypes.c_float(position))

    # =========================================================================
    # Section Box (Multi-Plane Clipping)
    # =========================================================================

    def set_section_box(self, min_x: float, min_y: float, min_z: float,
                        max_x: float, max_y: float, max_z: float):
        """
        Set a section box to isolate a 3D region of the model.

        Args:
            min_x, min_y, min_z: Minimum bounds in feet
            max_x, max_y, max_z: Maximum bounds in feet

        Only geometry within the specified bounds will be visible.
        """
        if self._initialized and self._lib and hasattr(self._lib, 'arch_set_section_box'):
            self._lib.arch_set_section_box(
                ctypes.c_float(min_x), ctypes.c_float(min_y), ctypes.c_float(min_z),
                ctypes.c_float(max_x), ctypes.c_float(max_y), ctypes.c_float(max_z)
            )

    def clear_section_box(self):
        """Clear the section box (disable all clip planes)."""
        if self._initialized and self._lib and hasattr(self._lib, 'arch_clear_section_box'):
            self._lib.arch_clear_section_box()

    def has_section_box(self) -> bool:
        """Check if a section box is currently active."""
        if self._initialized and self._lib and hasattr(self._lib, 'arch_has_section_box'):
            return self._lib.arch_has_section_box() != 0
        return False

    def get_section_box(self) -> tuple:
        """
        Get the current section box bounds.

        Returns:
            Tuple of (min_x, min_y, min_z, max_x, max_y, max_z) or None if no section box
        """
        if self._initialized and self._lib and hasattr(self._lib, 'arch_get_section_box'):
            min_x = ctypes.c_float()
            min_y = ctypes.c_float()
            min_z = ctypes.c_float()
            max_x = ctypes.c_float()
            max_y = ctypes.c_float()
            max_z = ctypes.c_float()

            result = self._lib.arch_get_section_box(
                ctypes.byref(min_x), ctypes.byref(min_y), ctypes.byref(min_z),
                ctypes.byref(max_x), ctypes.byref(max_y), ctypes.byref(max_z)
            )
            if result == 0:
                return (min_x.value, min_y.value, min_z.value,
                        max_x.value, max_y.value, max_z.value)
        return None

    def set_clip_plane_at(self, index: int, a: float, b: float, c: float, d: float, enabled: bool = True):
        """
        Set a specific clip plane directly.

        Args:
            index: Plane index (0-5)
            a, b, c: Plane normal components
            d: Plane distance from origin
            enabled: Whether this plane is active
        """
        if self._initialized and self._lib and hasattr(self._lib, 'arch_set_clip_plane_at'):
            self._lib.arch_set_clip_plane_at(
                index,
                ctypes.c_float(a), ctypes.c_float(b), ctypes.c_float(c), ctypes.c_float(d),
                1 if enabled else 0
            )

    def get_num_clip_planes(self) -> int:
        """Get number of active clip planes."""
        if self._initialized and self._lib and hasattr(self._lib, 'arch_get_num_clip_planes'):
            return self._lib.arch_get_num_clip_planes()
        return 0

    # =========================================================================
    # Material Style
    # =========================================================================

    def set_material_style(self, style: int):
        """
        Set material rendering style.

        Args:
            style: 0=Realistic, 1=Clean, 2=Schematic, 3=Blueprint
        """
        if self._initialized and self._lib:
            self._lib.arch_set_material_style(style)

    def get_material_style(self) -> int:
        """Get current material style (0-3)."""
        if self._initialized and self._lib:
            return self._lib.arch_get_material_style()
        return 1  # Default: Clean

    # =========================================================================
    # Material Settings (UV, roughness, metallic, AO)
    # =========================================================================

    def set_uv_scale(self, scale_u: float, scale_v: float = None):
        """
        Set UV/texture tiling scale.

        Args:
            scale_u: Horizontal tiling (1.0 = original, 2.0 = 2x repetition)
            scale_v: Vertical tiling (defaults to scale_u if not specified)
        """
        if scale_v is None:
            scale_v = scale_u
        if self._initialized and self._lib:
            self._lib.arch_set_uv_scale(ctypes.c_float(scale_u), ctypes.c_float(scale_v))

    def get_uv_scale(self) -> tuple:
        """Get current UV scale as (u, v)."""
        if self._initialized and self._lib:
            u = ctypes.c_float()
            v = ctypes.c_float()
            self._lib.arch_get_uv_scale(ctypes.byref(u), ctypes.byref(v))
            return (u.value, v.value)
        return (1.0, 1.0)

    def set_roughness_multiplier(self, multiplier: float):
        """
        Set roughness multiplier.

        Args:
            multiplier: 1.0 = default, < 1.0 = smoother/shinier, > 1.0 = rougher/matter
        """
        if self._initialized and self._lib:
            self._lib.arch_set_roughness_multiplier(ctypes.c_float(multiplier))

    def get_roughness_multiplier(self) -> float:
        """Get current roughness multiplier."""
        if self._initialized and self._lib:
            return self._lib.arch_get_roughness_multiplier()
        return 1.0

    def set_metallic_multiplier(self, multiplier: float):
        """
        Set metallic multiplier.

        Args:
            multiplier: 1.0 = default, < 1.0 = less metallic, > 1.0 = more metallic
        """
        if self._initialized and self._lib:
            self._lib.arch_set_metallic_multiplier(ctypes.c_float(multiplier))

    def get_metallic_multiplier(self) -> float:
        """Get current metallic multiplier."""
        if self._initialized and self._lib:
            return self._lib.arch_get_metallic_multiplier()
        return 1.0

    def set_ao_strength(self, strength: float):
        """
        Set ambient occlusion strength.

        Args:
            strength: 0.0 = no AO, 1.0 = full AO
        """
        if self._initialized and self._lib:
            self._lib.arch_set_ao_strength(ctypes.c_float(strength))

    def get_ao_strength(self) -> float:
        """Get current AO strength."""
        if self._initialized and self._lib:
            return self._lib.arch_get_ao_strength()
        return 1.0

    # =========================================================================
    # Material Application
    # =========================================================================

    def apply_material_to_element(self, element_index: int, material_name: str) -> bool:
        """
        Apply a material to a specific element.

        Args:
            element_index: Index of the element in the building
            material_name: Name of the material (e.g., "polyhaven/brick_wall_006")

        Returns:
            True if successful, False otherwise
        """
        if not self._initialized or not self._lib:
            return False
        if not getattr(self, '_has_material_api', False):
            print("[VulkanWidget] Material application API not available")
            return False

        result = self._lib.arch_apply_material_to_element(
            ctypes.c_int(element_index),
            material_name.encode('utf-8')
        )
        return result == 0

    def apply_material_to_elements(self, element_indices: list, material_name: str) -> int:
        """
        Apply a material to multiple elements at once.

        Args:
            element_indices: List of element indices
            material_name: Name of the material

        Returns:
            Number of elements successfully updated
        """
        if not self._initialized or not self._lib:
            print("[VulkanWidget] apply_material_to_elements: not initialized")
            return 0
        if not getattr(self, '_has_material_api', False):
            print("[VulkanWidget] Material application API not available")
            return 0

        if not element_indices:
            print("[VulkanWidget] apply_material_to_elements: no indices provided")
            return 0

        try:
            print(f"[VulkanWidget] Applying material '{material_name}' to {len(element_indices)} elements: {element_indices[:5]}...")

            # Create array of indices
            indices_array = (ctypes.c_int * len(element_indices))(*element_indices)

            result = self._lib.arch_apply_material_to_batch(
                indices_array,
                ctypes.c_int(len(element_indices)),
                material_name.encode('utf-8')
            )
            print(f"[VulkanWidget] arch_apply_material_to_batch returned: {result}")
            return result
        except Exception as e:
            print(f"[VulkanWidget] Error applying material: {e}")
            import traceback
            traceback.print_exc()
            return 0

    def get_element_material(self, element_index: int) -> str:
        """
        Get the material name applied to an element.

        Args:
            element_index: Index of the element

        Returns:
            Material name, or empty string if none or error
        """
        if not self._initialized or not self._lib:
            return ""
        if not getattr(self, '_has_material_api', False):
            return ""

        buffer = ctypes.create_string_buffer(256)
        result = self._lib.arch_get_element_material_name(
            ctypes.c_int(element_index),
            buffer,
            ctypes.c_int(256)
        )
        if result == 0:
            return buffer.value.decode('utf-8')
        return ""

    # =========================================================================
    # Shadows & Lighting
    # =========================================================================

    def set_shadows_enabled(self, enabled: bool):
        """Enable or disable shadow mapping."""
        if self._initialized and self._lib:
            self._lib.arch_set_shadows_enabled(1 if enabled else 0)

    def get_shadows_enabled(self) -> bool:
        """Check if shadows are enabled."""
        if self._initialized and self._lib:
            return self._lib.arch_get_shadows_enabled() != 0
        return True

    def set_light_direction(self, x: float, y: float, z: float):
        """Set sun/light direction (normalized)."""
        if self._initialized and self._lib:
            self._lib.arch_set_light_direction(
                ctypes.c_float(x), ctypes.c_float(y), ctypes.c_float(z)
            )

    def get_light_direction(self) -> tuple:
        """Get current light direction as (x, y, z)."""
        if self._initialized and self._lib:
            x = ctypes.c_float()
            y = ctypes.c_float()
            z = ctypes.c_float()
            self._lib.arch_get_light_direction(
                ctypes.byref(x), ctypes.byref(y), ctypes.byref(z)
            )
            return (x.value, y.value, z.value)
        return (-0.5, -0.8, -0.3)

    # =========================================================================
    # SSAO (Screen Space Ambient Occlusion)
    # =========================================================================

    def set_ssao_enabled(self, enabled: bool):
        """Enable or disable SSAO."""
        if self._initialized and self._lib:
            self._lib.arch_set_ssao_enabled(1 if enabled else 0)

    def get_ssao_enabled(self) -> bool:
        """Check if SSAO is enabled."""
        if self._initialized and self._lib:
            return self._lib.arch_get_ssao_enabled() != 0
        return True

    def set_ssao_radius(self, radius: float):
        """Set SSAO sample radius."""
        if self._initialized and self._lib:
            self._lib.arch_set_ssao_radius(ctypes.c_float(radius))

    def get_ssao_radius(self) -> float:
        """Get SSAO radius."""
        if self._initialized and self._lib:
            return self._lib.arch_get_ssao_radius()
        return 0.5

    def set_ssao_intensity(self, intensity: float):
        """Set SSAO intensity."""
        if self._initialized and self._lib:
            self._lib.arch_set_ssao_intensity(ctypes.c_float(intensity))

    def get_ssao_intensity(self) -> float:
        """Get SSAO intensity."""
        if self._initialized and self._lib:
            return self._lib.arch_get_ssao_intensity()
        return 1.0

    # =========================================================================
    # Bloom
    # =========================================================================

    def set_bloom_enabled(self, enabled: bool):
        """Enable or disable bloom effect."""
        if self._initialized and self._lib:
            self._lib.arch_set_bloom_enabled(1 if enabled else 0)

    def get_bloom_enabled(self) -> bool:
        """Check if bloom is enabled."""
        if self._initialized and self._lib:
            return self._lib.arch_get_bloom_enabled() != 0
        return True

    def set_bloom_threshold(self, threshold: float):
        """Set bloom brightness threshold."""
        if self._initialized and self._lib:
            self._lib.arch_set_bloom_threshold(ctypes.c_float(threshold))

    def get_bloom_threshold(self) -> float:
        """Get bloom threshold."""
        if self._initialized and self._lib:
            return self._lib.arch_get_bloom_threshold()
        return 1.0

    def set_bloom_intensity(self, intensity: float):
        """Set bloom intensity."""
        if self._initialized and self._lib:
            self._lib.arch_set_bloom_intensity(ctypes.c_float(intensity))

    def get_bloom_intensity(self) -> float:
        """Get bloom intensity."""
        if self._initialized and self._lib:
            return self._lib.arch_get_bloom_intensity()
        return 0.5

    # =========================================================================
    # Tonemapping & Exposure
    # =========================================================================

    def set_exposure(self, exposure: float):
        """Set camera exposure."""
        if self._initialized and self._lib:
            self._lib.arch_set_exposure(ctypes.c_float(exposure))

    def get_exposure(self) -> float:
        """Get current exposure."""
        if self._initialized and self._lib:
            return self._lib.arch_get_exposure()
        return 1.0

    def set_tonemap_mode(self, mode: int):
        """
        Set tonemapping operator.

        Args:
            mode: 0=Reinhard, 1=ACES, 2=Uncharted2
        """
        if self._initialized and self._lib:
            self._lib.arch_set_tonemap_mode(mode)

    def get_tonemap_mode(self) -> int:
        """Get current tonemap mode (0-2)."""
        if self._initialized and self._lib:
            return self._lib.arch_get_tonemap_mode()
        return 1  # Default: ACES

    # =========================================================================
    # Camera View Settings
    # =========================================================================

    def set_camera_fov(self, fov: float):
        """Set camera field of view in degrees (10-120)."""
        if self._initialized and self._lib:
            try:
                self._lib.arch_set_camera_fov(ctypes.c_float(fov))
            except AttributeError:
                pass

    def get_camera_fov(self) -> float:
        """Get current camera FOV in degrees."""
        if self._initialized and self._lib:
            try:
                return self._lib.arch_get_camera_fov()
            except AttributeError:
                pass
        return 45.0

    def set_orthographic(self, enabled: bool):
        """Enable orthographic projection mode."""
        if self._initialized and self._lib:
            try:
                self._lib.arch_set_orthographic(1 if enabled else 0)
            except AttributeError:
                pass

    def get_orthographic(self) -> bool:
        """Check if orthographic mode is enabled."""
        if self._initialized and self._lib:
            try:
                return self._lib.arch_get_orthographic() != 0
            except AttributeError:
                pass
        return False

    # =========================================================================
    # Frame Capture
    # =========================================================================

    def capture_frame(self, output_path: str) -> bool:
        """
        Capture the current frame to a PNG file.

        Args:
            output_path: Path to save the PNG file

        Returns:
            True if successful, False otherwise
        """
        if not self._initialized or not self._lib:
            print("[Viewport] Cannot capture - not initialized")
            return False

        try:
            # Ensure the capture function is available
            if not hasattr(self._lib, 'arch_capture_frame'):
                self._lib.arch_capture_frame.argtypes = [ctypes.c_char_p]
                self._lib.arch_capture_frame.restype = ctypes.c_int

            result = self._lib.arch_capture_frame(output_path.encode('utf-8'))
            if result == 0:
                print(f"[Viewport] Captured frame to: {output_path}")
                return True
            else:
                print(f"[Viewport] Capture failed with code: {result}")
                return False
        except Exception as e:
            print(f"[Viewport] Capture error: {e}")
            return False

    def capture_elevation(self, output_path: str, direction: str = 'south',
                          section_enabled: bool = False, section_depth: float = 0.0) -> bool:
        """
        Capture an orthogonal elevation view.

        Args:
            output_path: Path to save the PNG file
            direction: 'south', 'north', 'east', or 'west'
            section_enabled: Whether to enable section cut
            section_depth: Section cut depth in feet

        Returns:
            True if successful, False otherwise
        """
        if not self._initialized or not self._lib:
            print("[Viewport] Cannot capture elevation - not initialized")
            return False

        direction_map = {'south': 0, 'north': 1, 'east': 2, 'west': 3}
        dir_code = direction_map.get(direction.lower(), 0)

        try:
            # Ensure the capture function is available
            if not hasattr(self._lib, 'arch_capture_elevation'):
                self._lib.arch_capture_elevation.argtypes = [
                    ctypes.c_char_p, ctypes.c_int, ctypes.c_int, ctypes.c_float
                ]
                self._lib.arch_capture_elevation.restype = ctypes.c_int

            result = self._lib.arch_capture_elevation(
                output_path.encode('utf-8'),
                dir_code,
                1 if section_enabled else 0,
                ctypes.c_float(section_depth)
            )
            if result == 0:
                print(f"[Viewport] Captured {direction} elevation to: {output_path}")
                return True
            else:
                print(f"[Viewport] Elevation capture failed with code: {result}")
                return False
        except Exception as e:
            print(f"[Viewport] Elevation capture error: {e}")
            return False

    def capture_all_elevations(self, output_dir: str, prefix: str = 'elevation') -> dict:
        """
        Capture all four elevation views.

        Args:
            output_dir: Directory to save the PNG files
            prefix: Filename prefix

        Returns:
            Dict mapping direction to file path, or empty dict on failure
        """
        import os
        os.makedirs(output_dir, exist_ok=True)

        results = {}
        for direction in ['south', 'north', 'east', 'west']:
            output_path = os.path.join(output_dir, f"{prefix}_{direction}.png")
            if self.capture_elevation(output_path, direction):
                results[direction] = output_path

        return results

    # =========================================================================
    # Mouse interaction
    # =========================================================================

    def _route_overlay_mouse(self, event) -> bool:
        """Route mouse event to navigation overlay if present. Returns True if consumed."""
        if self._nav_overlay and hasattr(self._nav_overlay, 'handle_mouse'):
            return self._nav_overlay.handle_mouse(event)
        return False

    def mousePressEvent(self, event):
        """Handle mouse press for camera control, section dragging, or element selection."""
        # Ensure widget has focus for keyboard shortcuts
        self.setFocus()
        if self._route_overlay_mouse(event):
            return
        if event.button() == Qt.MouseButton.LeftButton and self._section_mode:
            # Left mouse in section mode = drag section plane
            self._section_dragging = True
            self._last_mouse_pos = event.pos()
            # Enable clipping if not already enabled
            if not self.get_clipping_enabled():
                self.set_clipping_enabled(True)
                self.set_section_floor_plan(4.0)  # Default to floor plan
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and not self._section_mode:
            # Left click = pick/select element
            pos = event.pos()
            element_idx = self.pick_element(pos.x(), pos.y())
            if element_idx >= 0:
                self.select_element(element_idx)
                # Show info about overlapping elements
                current, total = self.get_selection_cycle_info()
                if total > 1:
                    print(f"[Viewport] Selected element {element_idx} ({current}/{total} overlapping - press Tab to cycle)")
                else:
                    print(f"[Viewport] Selected element {element_idx}")
            else:
                # Click on empty space = deselect
                self.select_element(-1)
                self.element_selected.emit(-1)
                # Clear selection manager state
                if self._selection_manager:
                    self._selection_manager.clear_selection()
            event.accept()
            return
        if event.button() == Qt.MouseButton.MiddleButton:
            # Middle mouse = pan
            self._dragging = True
            self._panning = True
            self._last_mouse_pos = event.pos()
            event.accept()
            return
        elif event.button() == Qt.MouseButton.RightButton:
            # Right mouse = orbit
            self._dragging = True
            self._panning = False
            self._last_mouse_pos = event.pos()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        """Handle mouse release."""
        if self._route_overlay_mouse(event):
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._section_dragging = False
        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton):
            self._dragging = False
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event):
        """Handle mouse move for camera orbit/pan or section dragging."""
        if self._route_overlay_mouse(event):
            return

        # Section plane dragging
        if self._section_dragging and self._last_mouse_pos is not None:
            dy = event.pos().y() - self._last_mouse_pos.y()
            # Vertical mouse movement adjusts clip height
            # Negative dy (move up) = increase height
            current_height = self.get_clip_height()
            new_height = current_height - dy * 0.05  # Scale factor for sensitivity
            new_height = max(-10.0, min(50.0, new_height))  # Clamp to reasonable range
            self.set_clip_height(new_height)
            self._last_mouse_pos = event.pos()
            # Emit signal for panel sync
            self.section_changed.emit(
                self.get_clipping_enabled(),
                self.get_clip_axis(),
                new_height,
                self.get_clip_flipped()
            )
            event.accept()
            return

        if self._dragging and self._last_mouse_pos is not None:
            dx = event.pos().x() - self._last_mouse_pos.x()
            dy = event.pos().y() - self._last_mouse_pos.y()

            if self._panning:
                # Pan: move camera in screen space
                import math
                # Pan speed in feet - scale with distance for consistent feel
                base_pan_speed = 0.1  # 0.1 feet per pixel at base distance
                pan_speed = base_pan_speed * (self._camera_distance / 60.0)  # Scale with zoom

                # Right vector (perpendicular to view direction in XZ plane)
                right_x = math.cos(self._camera_yaw)
                right_z = math.sin(self._camera_yaw)

                # Up vector (world Y for now, could be more sophisticated)
                up_y = 1.0

                if self._free_look_mode and self._free_look_cam_pos is not None:
                    # Free look: move BOTH camera position and target together
                    move_x = -dx * pan_speed * right_x
                    move_z = -dx * pan_speed * right_z
                    move_y = dy * pan_speed * up_y

                    # Move camera position
                    self._free_look_cam_pos[0] += move_x
                    self._free_look_cam_pos[1] += move_y
                    self._free_look_cam_pos[2] += move_z

                    # Move target by same amount
                    self._camera_target[0] += move_x
                    self._camera_target[1] += move_y
                    self._camera_target[2] += move_z

                    # Update camera pose in renderer
                    if self._initialized and self._lib:
                        self._lib.arch_set_camera_pose(
                            ctypes.c_float(self._free_look_cam_pos[0]),
                            ctypes.c_float(self._free_look_cam_pos[1]),
                            ctypes.c_float(self._free_look_cam_pos[2]),
                            ctypes.c_float(self._camera_target[0]),
                            ctypes.c_float(self._camera_target[1]),
                            ctypes.c_float(self._camera_target[2])
                        )
                else:
                    # Orbit mode: only move target
                    self._camera_target[0] -= dx * pan_speed * right_x
                    self._camera_target[2] -= dx * pan_speed * right_z
                    self._camera_target[1] += dy * pan_speed * up_y

                    # Update camera target in renderer
                    if self._initialized and self._lib:
                        self._lib.arch_set_camera_target(
                            ctypes.c_float(self._camera_target[0]),
                            ctypes.c_float(self._camera_target[1]),
                            ctypes.c_float(self._camera_target[2])
                        )
            else:
                # Camera rotation
                if self._free_look_mode:
                    # Free look: first time entering, calculate camera position
                    import math
                    if self._free_look_cam_pos is None:
                        cos_yaw = math.cos(self._camera_yaw)
                        sin_yaw = math.sin(self._camera_yaw)
                        cos_pitch = math.cos(self._camera_pitch)
                        sin_pitch = math.sin(self._camera_pitch)
                        # Camera position from current orbit state
                        cam_x = self._camera_target[0] - self._camera_distance * sin_yaw * cos_pitch
                        cam_y = self._camera_target[1] - self._camera_distance * sin_pitch
                        cam_z = self._camera_target[2] - self._camera_distance * cos_yaw * cos_pitch
                        self._free_look_cam_pos = [cam_x, cam_y, cam_z]

                    # Update viewing angles (camera stays fixed)
                    self._camera_yaw -= dx * 0.005  # Faster for free look
                    self._camera_pitch -= dy * 0.005
                    self._camera_pitch = max(-1.57, min(1.57, self._camera_pitch))

                    # Calculate new target from fixed camera position
                    cam_x, cam_y, cam_z = self._free_look_cam_pos
                    cos_yaw_new = math.cos(self._camera_yaw)
                    sin_yaw_new = math.sin(self._camera_yaw)
                    cos_pitch_new = math.cos(self._camera_pitch)
                    sin_pitch_new = math.sin(self._camera_pitch)

                    # target = camera + distance * direction
                    self._camera_target[0] = cam_x + self._camera_distance * sin_yaw_new * cos_pitch_new
                    self._camera_target[1] = cam_y + self._camera_distance * sin_pitch_new
                    self._camera_target[2] = cam_z + self._camera_distance * cos_yaw_new * cos_pitch_new

                    # Update camera using direct pose API
                    if self._initialized and self._lib:
                        self._lib.arch_set_camera_pose(
                            ctypes.c_float(cam_x),
                            ctypes.c_float(cam_y),
                            ctypes.c_float(cam_z),
                            ctypes.c_float(self._camera_target[0]),
                            ctypes.c_float(self._camera_target[1]),
                            ctypes.c_float(self._camera_target[2])
                        )
                else:
                    # Orbit: rotate camera around target (slower, smoother)
                    self._camera_yaw -= dx * 0.002
                    self._camera_pitch -= dy * 0.002
                    self._camera_pitch = max(-1.4, min(1.4, self._camera_pitch))
                    # Clear free look camera position when switching back to orbit
                    self._free_look_cam_pos = None

            self._last_mouse_pos = event.pos()
            event.accept()
            return

        # Hover detection when not dragging
        if not self._dragging and self._selection_manager and self._document:
            try:
                self._update_hover(event.pos().x(), event.pos().y())
            except Exception as e:
                pass  # Ignore hover errors to prevent crashes

        super().mouseMoveEvent(event)

    def _update_hover(self, x: int, y: int):
        """Update hover state based on mouse position."""
        self._update_selection_camera()
        hits = self._selection_manager.pick_at_screen(x, y)

        if hits:
            # Get top hit (highest priority)
            top_hit = hits[0]
            new_hover = (top_hit.element_type, top_hit.element_id)

            if new_hover != self._hovered_element:
                self._hovered_element = new_hover
                self.element_hovered.emit(top_hit.element_type, top_hit.element_id)
                # Change cursor to indicate selectable
                self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            if self._hovered_element is not None:
                self._hovered_element = None
                self.element_hovered.emit('', None)
                self.setCursor(Qt.CursorShape.ArrowCursor)

    def leaveEvent(self, event):
        """Clear hover when mouse leaves widget."""
        if self._hovered_element is not None:
            self._hovered_element = None
            self.element_hovered.emit('', None)
            self.setCursor(Qt.CursorShape.ArrowCursor)
        super().leaveEvent(event)

    def enterEvent(self, event):
        """Grab focus when mouse enters viewport for keyboard shortcuts."""
        self.setFocus()
        super().enterEvent(event)

    def wheelEvent(self, event):
        """Handle mouse wheel for zoom (orbit mode) or movement (free look mode)."""
        import math
        delta = event.angleDelta().y() / 120.0

        if abs(delta) < 0.01:
            super().wheelEvent(event)
            return

        if self._free_look_mode:
            # Free look mode: scroll moves camera forward/backward
            # Calculate forward direction from yaw and pitch
            cos_yaw = math.cos(self._camera_yaw)
            sin_yaw = math.sin(self._camera_yaw)
            cos_pitch = math.cos(self._camera_pitch)
            sin_pitch = math.sin(self._camera_pitch)

            # Forward vector (direction camera is looking)
            forward_x = sin_yaw * cos_pitch
            forward_y = sin_pitch
            forward_z = cos_yaw * cos_pitch

            # Movement speed - scroll up (positive delta) = forward, scroll down = backward
            # Camera system uses FEET - scale speed with distance
            # Far away: move faster, close up: move slower
            base_speed = 0.05  # 5% of distance per scroll tick
            move_speed = max(0.5, self._camera_distance * base_speed)  # Min 0.5 feet
            move_delta = delta * move_speed

            # Update camera position
            if self._free_look_cam_pos is None:
                # Initialize if not set
                self._free_look_cam_pos = [
                    self._camera_target[0] - self._camera_distance * forward_x,
                    self._camera_target[1] - self._camera_distance * forward_y,
                    self._camera_target[2] - self._camera_distance * forward_z
                ]

            self._free_look_cam_pos[0] += move_delta * forward_x
            self._free_look_cam_pos[1] += move_delta * forward_y
            self._free_look_cam_pos[2] += move_delta * forward_z

            # Update target to maintain same distance from camera
            self._camera_target[0] = self._free_look_cam_pos[0] + self._camera_distance * forward_x
            self._camera_target[1] = self._free_look_cam_pos[1] + self._camera_distance * forward_y
            self._camera_target[2] = self._free_look_cam_pos[2] + self._camera_distance * forward_z

            # Update camera in renderer
            if self._initialized and self._lib:
                self._lib.arch_set_camera_pose(
                    ctypes.c_float(self._free_look_cam_pos[0]),
                    ctypes.c_float(self._free_look_cam_pos[1]),
                    ctypes.c_float(self._free_look_cam_pos[2]),
                    ctypes.c_float(self._camera_target[0]),
                    ctypes.c_float(self._camera_target[1]),
                    ctypes.c_float(self._camera_target[2])
                )
        else:
            # Orbit mode: zoom centered on cursor
            # Get cursor position relative to widget center (normalized -1 to 1)
            cursor_pos = event.position()
            ndc_x = (cursor_pos.x() / self.width()) * 2.0 - 1.0
            ndc_y = 1.0 - (cursor_pos.y() / self.height()) * 2.0  # Flip Y

            # Calculate zoom - faster zoom, closer minimum
            zoom_factor = 0.15  # Faster zoom for quicker navigation
            old_distance = self._camera_distance
            new_distance = old_distance * (1.0 - delta * zoom_factor)
            # Allow getting very close (1 foot) to 300 feet out (units are FEET)
            new_distance = max(1.0, min(300.0, new_distance))

            # Debug: print when hitting limits
            if new_distance <= 1.0 or new_distance >= 300.0:
                print(f"[Viewport] Zoom limit hit: distance={new_distance:.1f}ft")

            # How much the distance changed
            distance_delta = old_distance - new_distance

            # Calculate camera vectors
            cos_yaw = math.cos(self._camera_yaw)
            sin_yaw = math.sin(self._camera_yaw)
            cos_pitch = math.cos(self._camera_pitch)
            sin_pitch = math.sin(self._camera_pitch)

            # Camera right vector (in XZ plane)
            right_x = cos_yaw
            right_z = sin_yaw

            # Camera up vector (simplified - just Y for architectural views)
            up_y = 1.0

            # Move target toward cursor position proportional to zoom amount
            # The FOV determines how much screen space maps to world space
            fov_factor = math.tan(math.radians(45.0 / 2.0))  # Approximate FOV
            world_scale = distance_delta * fov_factor

            # Shift target based on cursor offset from center
            self._camera_target[0] += ndc_x * world_scale * right_x
            self._camera_target[2] += ndc_x * world_scale * right_z
            self._camera_target[1] += ndc_y * world_scale * cos_pitch

            # Apply the zoom
            self._camera_distance = new_distance

            # Update camera target in renderer
            if self._initialized and self._lib:
                self._lib.arch_set_camera_target(
                    ctypes.c_float(self._camera_target[0]),
                    ctypes.c_float(self._camera_target[1]),
                    ctypes.c_float(self._camera_target[2])
                )

        super().wheelEvent(event)

    def keyPressEvent(self, event):
        """Handle key press for section mode toggle, Tab cycling, and other shortcuts."""
        from PyQt6.QtCore import Qt

        # Tab = cycle through overlapping elements
        if event.key() == Qt.Key.Key_Tab:
            forward = not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            if self.cycle_selection(forward):
                event.accept()
                return

        if event.key() == Qt.Key.Key_S and not event.modifiers():
            # 'S' key toggles section mode
            self._section_mode = not self._section_mode
            if self._section_mode:
                print("[Viewport] Section mode ON - drag to adjust section plane")
                # Change cursor to indicate section mode
                self.setCursor(Qt.CursorShape.SplitVCursor)
            else:
                print("[Viewport] Section mode OFF")
                self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        elif event.key() == Qt.Key.Key_Escape:
            # Escape exits section mode
            if self._section_mode:
                self._section_mode = False
                self._section_dragging = False
                self.setCursor(Qt.CursorShape.ArrowCursor)
                print("[Viewport] Section mode OFF")
                event.accept()
                return
        elif event.key() == Qt.Key.Key_C and self._section_mode:
            # 'C' cycles axis when in section mode
            current_axis = self.get_clip_axis()
            new_axis = (current_axis + 1) % 3
            self.set_clip_axis(new_axis)
            axis_names = ["X (Left/Right)", "Y (Up/Down)", "Z (Front/Back)"]
            print(f"[Viewport] Section axis: {axis_names[new_axis]}")
            self.section_changed.emit(
                self.get_clipping_enabled(),
                new_axis,
                self.get_clip_height(),
                self.get_clip_flipped()
            )
            event.accept()
            return
        elif event.key() == Qt.Key.Key_F and self._section_mode:
            # 'F' flips section direction
            flipped = not self.get_clip_flipped()
            self.set_clip_flipped(flipped)
            print(f"[Viewport] Section flipped: {flipped}")
            self.section_changed.emit(
                self.get_clipping_enabled(),
                self.get_clip_axis(),
                self.get_clip_height(),
                flipped
            )
            event.accept()
            return
        elif event.key() == Qt.Key.Key_H:
            # 'H' key resets camera to home/default view (ignore modifiers for reliability)
            self._free_look_mode = False  # Exit free look mode
            self._free_look_cam_pos = None  # Clear free look state
            self.reset_camera()
            print("[Viewport] Camera reset to home view (H key)")
            event.accept()
            return
        elif event.key() == Qt.Key.Key_M and not event.modifiers():
            # 'M' key toggles Move House mode
            self._move_house_mode = not self._move_house_mode
            if self._move_house_mode:
                print("[Viewport] MOVE HOUSE mode ON - click on terrain to relocate building")
                self.setCursor(Qt.CursorShape.CrossCursor)
            else:
                print("[Viewport] MOVE HOUSE mode OFF")
                self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        elif event.key() == Qt.Key.Key_Space and not event.modifiers():
            # Spacebar toggles free look mode - always reset to home view first
            self._free_look_mode = not self._free_look_mode
            mode = "FREE LOOK" if self._free_look_mode else "ORBIT"

            # Reset camera to home position when switching modes
            self.reset_camera()
            self._free_look_cam_pos = None  # Clear free look state

            # If entering free look mode, initialize camera position from home
            if self._free_look_mode:
                import math
                cos_yaw = math.cos(self._camera_yaw)
                sin_yaw = math.sin(self._camera_yaw)
                cos_pitch = math.cos(self._camera_pitch)
                sin_pitch = math.sin(self._camera_pitch)
                cam_x = self._camera_target[0] - self._camera_distance * sin_yaw * cos_pitch
                cam_y = self._camera_target[1] - self._camera_distance * sin_pitch
                cam_z = self._camera_target[2] - self._camera_distance * cos_yaw * cos_pitch
                self._free_look_cam_pos = [cam_x, cam_y, cam_z]

            print(f"[Viewport] Camera mode: {mode} (reset to home)")
            self.update()
            event.accept()
            return

        super().keyPressEvent(event)

    # =========================================================================
    # Path Tracer (Offline High-Quality Rendering)
    # =========================================================================

    def has_path_tracer(self) -> bool:
        """Check if path tracer API is available."""
        return getattr(self, '_has_path_tracer', False)

    def pt_configure(self, width: int, height: int, samples: int = 256, bounces: int = 8) -> bool:
        """
        Configure path tracer parameters.

        Args:
            width: Output image width in pixels
            height: Output image height in pixels
            samples: Samples per pixel (higher = less noise)
            bounces: Maximum path bounces (higher = more accurate GI)

        Returns:
            True on success
        """
        if not self.has_path_tracer():
            return False
        return self._lib.arch_pt_set_config(width, height, samples, bounces) == 0

    def pt_start_render(self) -> bool:
        """Start path traced render. Returns True on success."""
        if not self.has_path_tracer():
            return False
        return self._lib.arch_pt_start_render() == 0

    def pt_render_frame(self) -> int:
        """
        Render one progressive frame.

        Returns:
            1 if more frames needed, 0 if complete, -1 on error
        """
        if not self.has_path_tracer():
            return -1
        return self._lib.arch_pt_render_frame()

    def pt_get_progress(self) -> float:
        """Get render progress (0.0 to 1.0)."""
        if not self.has_path_tracer():
            return 0.0
        progress = ctypes.c_float()
        self._lib.arch_pt_get_progress(ctypes.byref(progress))
        return progress.value

    def pt_stop(self):
        """Stop the current render early."""
        if self.has_path_tracer():
            self._lib.arch_pt_stop()

    def pt_is_rendering(self) -> bool:
        """Check if path tracer is currently rendering."""
        if not self.has_path_tracer():
            return False
        return self._lib.arch_pt_is_rendering() != 0

    def pt_is_complete(self) -> bool:
        """Check if render is complete."""
        if not self.has_path_tracer():
            return False
        return self._lib.arch_pt_is_complete() != 0

    def pt_get_sample_count(self) -> int:
        """Get number of samples completed."""
        if not self.has_path_tracer():
            return 0
        return self._lib.arch_pt_get_sample_count()

    def pt_save_png(self, path: str, exposure: float = 1.0) -> bool:
        """
        Save path traced result as PNG.

        Args:
            path: Output file path
            exposure: Exposure adjustment (1.0 = default)

        Returns:
            True on success
        """
        if not self.has_path_tracer():
            return False
        return self._lib.arch_pt_save_png(path.encode('utf-8'), ctypes.c_float(exposure)) == 0

    def pt_save_hdr(self, path: str) -> bool:
        """
        Save path traced result as HDR (Radiance format).

        Args:
            path: Output file path

        Returns:
            True on success
        """
        if not self.has_path_tracer():
            return False
        return self._lib.arch_pt_save_hdr(path.encode('utf-8')) == 0

    def pt_apply_denoise(self) -> bool:
        """Apply denoising to the path traced result."""
        if not self.has_path_tracer():
            return False
        return self._lib.arch_pt_apply_denoise() == 0

    def pt_set_exposure(self, exposure: float):
        """Set path tracer exposure."""
        if self.has_path_tracer():
            self._lib.arch_pt_set_exposure(ctypes.c_float(exposure))

    def pt_get_exposure(self) -> float:
        """Get path tracer exposure."""
        if not self.has_path_tracer():
            return 1.0
        return self._lib.arch_pt_get_exposure()

    def pt_set_tonemap_mode(self, mode: int):
        """Set path tracer tonemap mode (0=Reinhard, 1=ACES, 2=Uncharted2)."""
        if self.has_path_tracer():
            self._lib.arch_pt_set_tonemap_mode(mode)

    def pt_get_tonemap_mode(self) -> int:
        """Get path tracer tonemap mode."""
        if not self.has_path_tracer():
            return 1
        return self._lib.arch_pt_get_tonemap_mode()

    def set_nav_gravity(self, design: float, client: float, build: float):
        """Update the overlay gravity weights."""
        if self._nav_overlay:
            self._nav_overlay.set_gravity(design, client, build)

    def set_nav_lod(self, level: int):
        """Update the overlay LOD display."""
        if self._nav_overlay:
            self._nav_overlay.set_lod_level(level)

    def paintEngine(self):
        """Return None to indicate we're handling our own painting."""
        return None
