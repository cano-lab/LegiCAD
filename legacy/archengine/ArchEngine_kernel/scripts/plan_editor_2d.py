"""
ArchEngine 2D Plan Editor
Live editing of floor plans with real-time JSON sync to UE5 viewer

Author: ArchEngine Team
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import json
import math
import asyncio
import threading
import websockets
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set
from dataclasses import dataclass, field
from enum import Enum

# Tolerance for snapping/joining (in mm)
SNAP_TOLERANCE = 50.0
ENDPOINT_HIT_RADIUS = 150.0  # For clicking on endpoints
GRID_SIZE = 100.0  # Grid snap size in mm (100mm = ~4 inches)

class EditMode(Enum):
    SELECT = "select"
    MOVE_WALL = "move_wall"
    MOVE_ENDPOINT = "move_endpoint"
    MOVE_ROOM = "move_room"
    TRIM_EXTEND = "trim_extend"
    DISCONNECT = "disconnect"  # Break wall from joint
    ADD_WALL = "add_wall"
    ADD_DOOR = "add_door"
    ADD_WINDOW = "add_window"

@dataclass
class Wall:
    """Represents an editable wall"""
    id: int
    start: Tuple[float, float]  # (x, z) in mm
    end: Tuple[float, float]
    height: float = 2700
    thickness: float = 140
    wall_type: str = "int_2x4"
    category: str = "interior"
    canvas_id: Optional[int] = None
    start_handle_id: Optional[int] = None
    end_handle_id: Optional[int] = None

@dataclass
class Joint:
    """Represents a corner joint where walls meet"""
    position: Tuple[float, float]
    wall_endpoints: List[Tuple[int, str]]  # List of (wall_id, "start"|"end")

@dataclass
class Room:
    """Represents an editable room"""
    id: str
    name: str
    bounds: Dict  # x, y, width, height in mm
    room_type: str = "living"
    canvas_id: Optional[int] = None
    label_id: Optional[int] = None

@dataclass
class Door:
    """Represents a door"""
    wall_index: int
    offset: float
    width: float = 914
    height: float = 2134
    door_type: str = "swing"
    canvas_id: Optional[int] = None

@dataclass
class Window:
    """Represents a window"""
    wall_index: int
    offset: float
    width: float = 1200
    height: float = 1200
    sill_height: float = 900
    canvas_id: Optional[int] = None

class PlanEditor2D:
    """2D Plan Editor with real-time sync"""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("ArchEngine 2D Plan Editor")
        self.root.geometry("1400x900")

        # Data
        self.building_data: Optional[Dict] = None
        self.walls: List[Wall] = []
        self.joints: List[Joint] = []  # Corner joints
        self.rooms: Dict[str, Room] = {}
        self.doors: List[Door] = []
        self.windows: List[Window] = []

        # Canvas state
        self.scale = 0.05  # mm to pixels (1m = 50px at this scale)
        self.offset_x = 100
        self.offset_y = 100
        self.edit_mode = EditMode.SELECT

        # Selection
        self.selected_wall: Optional[Wall] = None
        self.selected_room: Optional[Room] = None
        self.selected_endpoint: Optional[Tuple[Wall, str]] = None  # (wall, "start"|"end")
        self.drag_start: Optional[Tuple[float, float]] = None
        self.drag_start_mm: Optional[Tuple[float, float]] = None

        # Trim/extend state
        self.trim_source_wall: Optional[Wall] = None

        # Ortho/Grid settings
        self.ortho_mode = True  # Constrain to H/V
        self.grid_snap = True   # Snap to grid
        self.grid_size = GRID_SIZE

        # Undo stack
        self.undo_stack: List[str] = []  # JSON snapshots
        self.max_undo = 50

        # WebSocket
        self.ws_server = None
        self.ws_clients: Set = set()
        self.ws_thread: Optional[threading.Thread] = None

        # File path
        self.current_file: Optional[Path] = None
        self.modified = False

        self._setup_ui()
        self._bind_events()

    def _setup_ui(self):
        """Setup the UI layout"""
        # Main container
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Toolbar
        toolbar = ttk.Frame(main_frame)
        toolbar.pack(fill=tk.X, padx=5, pady=5)

        # File operations
        ttk.Button(toolbar, text="Open", command=self._open_file).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Save", command=self._save_file).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Reload", command=self._reload_file).pack(side=tk.LEFT, padx=2)

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)

        # Edit mode buttons
        self.mode_var = tk.StringVar(value="select")
        modes = [
            ("Select", "select"),
            ("Move Wall", "move_wall"),
            ("Move Corner", "move_endpoint"),
            ("Disconnect", "disconnect"),
            ("Trim/Extend", "trim_extend"),
        ]
        for text, mode in modes:
            ttk.Radiobutton(toolbar, text=text, variable=self.mode_var,
                          value=mode, command=self._on_mode_change).pack(side=tk.LEFT, padx=2)

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)

        # Ortho/Grid toggles
        self.ortho_var = tk.BooleanVar(value=True)
        self.grid_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(toolbar, text="Ortho", variable=self.ortho_var,
                       command=self._on_ortho_toggle).pack(side=tk.LEFT, padx=2)
        ttk.Checkbutton(toolbar, text="Grid", variable=self.grid_var,
                       command=self._on_grid_toggle).pack(side=tk.LEFT, padx=2)

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)

        # Tools
        ttk.Button(toolbar, text="Fix Corners", command=self._fix_all_corners).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Clean Joints", command=self._clean_joints).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Undo", command=self._undo).pack(side=tk.LEFT, padx=2)

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)

        # Zoom controls
        ttk.Button(toolbar, text="Zoom +", command=lambda: self._zoom(1.2)).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Zoom -", command=lambda: self._zoom(0.8)).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Fit", command=self._fit_view).pack(side=tk.LEFT, padx=2)

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)

        # WebSocket controls
        self.ws_status = ttk.Label(toolbar, text="WS: Disconnected", foreground="gray")
        self.ws_status.pack(side=tk.RIGHT, padx=5)
        ttk.Button(toolbar, text="Start Sync", command=self._toggle_websocket).pack(side=tk.RIGHT, padx=2)

        # Main content area
        content = ttk.PanedWindow(main_frame, orient=tk.HORIZONTAL)
        content.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Canvas frame
        canvas_frame = ttk.Frame(content)
        content.add(canvas_frame, weight=3)

        # Canvas with scrollbars
        self.canvas = tk.Canvas(canvas_frame, bg="#1a1a2e", highlightthickness=0)
        v_scroll = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=self.canvas.yview)
        h_scroll = ttk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL, command=self.canvas.xview)

        self.canvas.configure(yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)

        v_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        h_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        # Properties panel
        props_frame = ttk.Frame(content, width=300)
        content.add(props_frame, weight=1)

        ttk.Label(props_frame, text="Properties", font=("", 12, "bold")).pack(pady=10)

        self.props_text = tk.Text(props_frame, width=35, height=20, wrap=tk.WORD)
        self.props_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Help text
        help_frame = ttk.LabelFrame(props_frame, text="Help")
        help_frame.pack(fill=tk.X, padx=5, pady=5)

        help_text = """Select: Click to select walls/rooms
Move Wall: Drag wall (joints connected)
Move Corner: Drag corners (joints move)
Disconnect: Click corner to free it
Trim/Extend: Click wall, then boundary

Ortho: Constrain to H/V lines
Grid: Snap to 100mm grid
Ctrl+Z: Undo last change"""

        ttk.Label(help_frame, text=help_text, justify=tk.LEFT).pack(padx=5, pady=5)

        # Status bar
        self.status_bar = ttk.Label(main_frame, text="Ready", relief=tk.SUNKEN)
        self.status_bar.pack(fill=tk.X, side=tk.BOTTOM)

    def _bind_events(self):
        """Bind canvas events"""
        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<MouseWheel>", self._on_scroll)
        self.canvas.bind("<Button-3>", self._on_right_click)
        self.canvas.bind("<Motion>", self._on_mouse_move)

        # Pan with middle mouse or shift+left
        self.canvas.bind("<Button-2>", self._start_pan)
        self.canvas.bind("<B2-Motion>", self._on_pan)
        self.canvas.bind("<Shift-Button-1>", self._start_pan)
        self.canvas.bind("<Shift-B1-Motion>", self._on_pan)

        # Keyboard shortcuts
        self.root.bind("<Control-o>", lambda e: self._open_file())
        self.root.bind("<Control-s>", lambda e: self._save_file())
        self.root.bind("<Control-z>", lambda e: self._undo())
        self.root.bind("<Escape>", lambda e: self._deselect_all())
        self.root.bind("<Delete>", lambda e: self._delete_selected())
        self.root.bind("<o>", lambda e: self._toggle_ortho())  # O key toggles ortho
        self.root.bind("<g>", lambda e: self._toggle_grid())   # G key toggles grid

    def _on_mode_change(self):
        """Handle edit mode change"""
        mode = self.mode_var.get()
        self.edit_mode = EditMode(mode)
        self._deselect_all()
        self.trim_source_wall = None
        self._update_status(f"Mode: {mode.replace('_', ' ').title()}")
        self._redraw()

    def _on_ortho_toggle(self):
        """Handle ortho checkbox toggle"""
        self.ortho_mode = self.ortho_var.get()
        self._update_status(f"Ortho: {'ON' if self.ortho_mode else 'OFF'}")

    def _on_grid_toggle(self):
        """Handle grid checkbox toggle"""
        self.grid_snap = self.grid_var.get()
        self._update_status(f"Grid Snap: {'ON' if self.grid_snap else 'OFF'}")

    def _toggle_ortho(self):
        """Toggle ortho mode via keyboard"""
        self.ortho_mode = not self.ortho_mode
        self.ortho_var.set(self.ortho_mode)
        self._update_status(f"Ortho: {'ON' if self.ortho_mode else 'OFF'}")

    def _toggle_grid(self):
        """Toggle grid snap via keyboard"""
        self.grid_snap = not self.grid_snap
        self.grid_var.set(self.grid_snap)
        self._update_status(f"Grid Snap: {'ON' if self.grid_snap else 'OFF'}")

    # ==================== UNDO ====================

    def _save_undo_state(self):
        """Save current state to undo stack"""
        if self.building_data:
            self._update_building_data()
            state = json.dumps(self.building_data)
            self.undo_stack.append(state)
            if len(self.undo_stack) > self.max_undo:
                self.undo_stack.pop(0)

    def _undo(self):
        """Restore previous state"""
        if not self.undo_stack:
            self._update_status("Nothing to undo")
            return

        state = self.undo_stack.pop()
        self.building_data = json.loads(state)
        self._parse_building_data()
        self._build_joints()
        self._redraw()
        self._update_status(f"Undo - {len(self.undo_stack)} states remaining")

    # ==================== SNAP HELPERS ====================

    def _snap_to_grid(self, value: float) -> float:
        """Snap value to grid"""
        if self.grid_snap:
            return round(value / self.grid_size) * self.grid_size
        return value

    def _constrain_ortho(self, start_pos: Tuple[float, float],
                         current_pos: Tuple[float, float]) -> Tuple[float, float]:
        """Constrain movement to horizontal or vertical"""
        if not self.ortho_mode:
            return current_pos

        dx = abs(current_pos[0] - start_pos[0])
        dy = abs(current_pos[1] - start_pos[1])

        if dx > dy:
            # Horizontal movement
            return (current_pos[0], start_pos[1])
        else:
            # Vertical movement
            return (start_pos[0], current_pos[1])

    # ==================== JOINT/CORNER MANAGEMENT ====================

    def _build_joints(self):
        """Build joint connections from wall endpoints"""
        self.joints.clear()

        # Map positions to wall endpoints
        endpoint_map: Dict[Tuple[int, int], List[Tuple[int, str]]] = {}

        for wall in self.walls:
            # Round to snap tolerance for grouping
            start_key = (round(wall.start[0] / SNAP_TOLERANCE),
                        round(wall.start[1] / SNAP_TOLERANCE))
            end_key = (round(wall.end[0] / SNAP_TOLERANCE),
                      round(wall.end[1] / SNAP_TOLERANCE))

            if start_key not in endpoint_map:
                endpoint_map[start_key] = []
            endpoint_map[start_key].append((wall.id, "start"))

            if end_key not in endpoint_map:
                endpoint_map[end_key] = []
            endpoint_map[end_key].append((wall.id, "end"))

        # Create joints where multiple endpoints meet
        for key, endpoints in endpoint_map.items():
            if len(endpoints) >= 1:  # Even single endpoints get a joint for dragging
                # Calculate actual center position
                positions = []
                for wall_id, end_type in endpoints:
                    wall = self.walls[wall_id]
                    pos = wall.start if end_type == "start" else wall.end
                    positions.append(pos)

                avg_x = sum(p[0] for p in positions) / len(positions)
                avg_y = sum(p[1] for p in positions) / len(positions)

                self.joints.append(Joint(
                    position=(avg_x, avg_y),
                    wall_endpoints=endpoints
                ))

    def _find_joint_at(self, mm_x: float, mm_y: float) -> Optional[Joint]:
        """Find joint near the given position"""
        for joint in self.joints:
            dist = math.sqrt((joint.position[0] - mm_x)**2 +
                           (joint.position[1] - mm_y)**2)
            if dist < ENDPOINT_HIT_RADIUS:
                return joint
        return None

    def _find_endpoint_at(self, mm_x: float, mm_y: float) -> Optional[Tuple[Wall, str]]:
        """Find wall endpoint near position"""
        best_dist = ENDPOINT_HIT_RADIUS
        best_endpoint = None

        for wall in self.walls:
            for end_type in ["start", "end"]:
                pos = wall.start if end_type == "start" else wall.end
                dist = math.sqrt((pos[0] - mm_x)**2 + (pos[1] - mm_y)**2)
                if dist < best_dist:
                    best_dist = dist
                    best_endpoint = (wall, end_type)

        return best_endpoint

    def _move_joint(self, joint: Joint, new_pos: Tuple[float, float]):
        """Move all wall endpoints connected to this joint"""
        for wall_id, end_type in joint.wall_endpoints:
            wall = self.walls[wall_id]
            if end_type == "start":
                wall.start = new_pos
            else:
                wall.end = new_pos

        joint.position = new_pos

    def _fix_all_corners(self):
        """Auto-connect nearby wall endpoints"""
        # Find endpoints that are close but not exactly matching
        changes = 0

        for i, wall1 in enumerate(self.walls):
            for end1 in ["start", "end"]:
                pos1 = wall1.start if end1 == "start" else wall1.end

                for j, wall2 in enumerate(self.walls):
                    if i >= j:
                        continue

                    for end2 in ["start", "end"]:
                        pos2 = wall2.start if end2 == "start" else wall2.end

                        dist = math.sqrt((pos1[0] - pos2[0])**2 +
                                       (pos1[1] - pos2[1])**2)

                        if 0 < dist < SNAP_TOLERANCE * 2:
                            # Snap to average position
                            avg = ((pos1[0] + pos2[0]) / 2,
                                  (pos1[1] + pos2[1]) / 2)

                            if end1 == "start":
                                wall1.start = avg
                            else:
                                wall1.end = avg

                            if end2 == "start":
                                wall2.start = avg
                            else:
                                wall2.end = avg

                            changes += 1

        self._build_joints()
        self._redraw()
        self.modified = True
        self._update_status(f"Fixed {changes} corner connections")

    def _clean_joints(self):
        """Remove duplicate joints and merge very close ones"""
        self._build_joints()
        self._redraw()
        self._update_status(f"Cleaned joints: {len(self.joints)} joints total")

    def _disconnect_endpoint(self, mm_x: float, mm_y: float):
        """Disconnect a wall endpoint from its joint (makes it independent)"""
        # Find the endpoint closest to click
        endpoint = self._find_endpoint_at(mm_x, mm_y)
        if not endpoint:
            self._update_status("Click on a wall endpoint to disconnect it")
            return

        wall, end_type = endpoint
        pos = wall.start if end_type == "start" else wall.end

        # Find the joint at this position
        joint = self._find_joint_at(pos[0], pos[1])
        if not joint or len(joint.wall_endpoints) < 2:
            self._update_status("This endpoint is not connected to other walls")
            return

        # Save undo state
        self._save_undo_state()

        # Move this endpoint slightly to disconnect it
        offset = 50.0  # 50mm offset
        if end_type == "start":
            # Move away from wall direction
            dx = wall.end[0] - wall.start[0]
            dy = wall.end[1] - wall.start[1]
            length = math.sqrt(dx*dx + dy*dy)
            if length > 0:
                wall.start = (wall.start[0] - (dx/length) * offset,
                            wall.start[1] - (dy/length) * offset)
        else:
            dx = wall.start[0] - wall.end[0]
            dy = wall.start[1] - wall.end[1]
            length = math.sqrt(dx*dx + dy*dy)
            if length > 0:
                wall.end = (wall.end[0] - (dx/length) * offset,
                          wall.end[1] - (dy/length) * offset)

        self._build_joints()
        self._redraw()
        self.modified = True
        self._update_status(f"Disconnected wall {wall.id} {end_type} endpoint")

    # ==================== TRIM/EXTEND ====================

    def _trim_wall_to_boundary(self, wall: Wall, boundary_wall: Wall):
        """Trim or extend wall to meet boundary wall"""
        # Calculate intersection point
        intersection = self._line_intersection(
            wall.start, wall.end,
            boundary_wall.start, boundary_wall.end
        )

        if intersection is None:
            self._update_status("Walls are parallel - no intersection")
            return

        # Determine which endpoint to move (closest to intersection)
        dist_start = math.sqrt((wall.start[0] - intersection[0])**2 +
                               (wall.start[1] - intersection[1])**2)
        dist_end = math.sqrt((wall.end[0] - intersection[0])**2 +
                            (wall.end[1] - intersection[1])**2)

        if dist_start < dist_end:
            wall.start = intersection
        else:
            wall.end = intersection

        self._build_joints()
        self._redraw()
        self.modified = True
        self._update_status(f"Trimmed wall {wall.id} to intersection")

    def _line_intersection(self, p1: Tuple[float, float], p2: Tuple[float, float],
                          p3: Tuple[float, float], p4: Tuple[float, float]) -> Optional[Tuple[float, float]]:
        """Calculate intersection point of two line segments (extended to infinite lines)"""
        x1, y1 = p1
        x2, y2 = p2
        x3, y3 = p3
        x4, y4 = p4

        denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)

        if abs(denom) < 1e-10:  # Lines are parallel
            return None

        t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom

        x = x1 + t * (x2 - x1)
        y = y1 + t * (y2 - y1)

        return (x, y)

    # ==================== FILE OPERATIONS ====================

    def _open_file(self):
        """Open a JSON file"""
        default_dir = Path("X:/ARCH/Software/ArchEngine_Suite/Shared/TestData/output")
        filepath = filedialog.askopenfilename(
            initialdir=str(default_dir),
            filetypes=[("JSON files", "*.json"), ("QBD files", "*.qbd"), ("All files", "*.*")]
        )
        if filepath:
            self._load_file(Path(filepath))

    def _load_file(self, filepath: Path):
        """Load building data from JSON file"""
        try:
            with open(filepath, 'r') as f:
                self.building_data = json.load(f)

            self.current_file = filepath
            self._parse_building_data()
            self._build_joints()
            self._redraw()
            self._fit_view()
            self._update_status(f"Loaded: {filepath.name} ({len(self.walls)} walls, {len(self.joints)} joints)")
            self.modified = False

        except Exception as e:
            messagebox.showerror("Error", f"Failed to load file: {e}")

    def _reload_file(self):
        """Reload current file"""
        if self.current_file:
            self._load_file(self.current_file)

    def _save_file(self):
        """Save changes to JSON file"""
        if not self.building_data:
            return

        if not self.current_file:
            filepath = filedialog.asksaveasfilename(
                defaultextension=".json",
                filetypes=[("JSON files", "*.json"), ("QBD files", "*.qbd")]
            )
            if not filepath:
                return
            self.current_file = Path(filepath)

        try:
            self._update_building_data()

            with open(self.current_file, 'w') as f:
                json.dump(self.building_data, f, indent=2)

            self._update_status(f"Saved: {self.current_file.name}")
            self.modified = False
            self._send_ws_update()

        except Exception as e:
            messagebox.showerror("Error", f"Failed to save file: {e}")

    def _parse_building_data(self):
        """Parse building data into editor objects"""
        self.walls.clear()
        self.rooms.clear()
        self.doors.clear()
        self.windows.clear()

        if not self.building_data:
            return

        # Parse walls from walls_batch
        walls_batch = self.building_data.get("walls_batch", [])
        for i, w in enumerate(walls_batch):
            start = w.get("start", [0, 0, 0])
            end = w.get("end", [0, 0, 0])

            wall = Wall(
                id=i,
                start=(start[0], start[2]),  # Use X and Z (depth) for 2D
                end=(end[0], end[2]),
                height=w.get("height", 2700),
                wall_type=w.get("wall_type", "int_2x4"),
                category=w.get("category", "interior")
            )
            self.walls.append(wall)

        # Parse rooms
        rooms_data = self.building_data.get("rooms", {})
        for room_id, r in rooms_data.items():
            room = Room(
                id=room_id,
                name=r.get("name", room_id),
                bounds=r.get("bounds", {"x": 0, "y": 0, "width": 1000, "height": 1000}),
                room_type=r.get("room_type", "living")
            )
            self.rooms[room_id] = room

        # Parse doors
        for d in self.building_data.get("doors", []):
            door = Door(
                wall_index=d.get("wall_index", 0),
                offset=d.get("offset", 0),
                width=d.get("width", 914),
                height=d.get("height", 2134),
                door_type=d.get("type", "swing")
            )
            self.doors.append(door)

        # Parse windows
        for w in self.building_data.get("windows", []):
            window = Window(
                wall_index=w.get("wall_index", 0),
                offset=w.get("offset", 0),
                width=w.get("width", 1200),
                height=w.get("height", 1200),
                sill_height=w.get("sill_height", 900)
            )
            self.windows.append(window)

    def _update_building_data(self):
        """Update building data from editor state"""
        if not self.building_data:
            return

        # Update walls_batch
        walls_batch = self.building_data.get("walls_batch", [])
        for wall in self.walls:
            if wall.id < len(walls_batch):
                walls_batch[wall.id]["start"] = [wall.start[0], 0, wall.start[1]]
                walls_batch[wall.id]["end"] = [wall.end[0], 0, wall.end[1]]

        # Update rooms
        rooms_data = self.building_data.get("rooms", {})
        for room_id, room in self.rooms.items():
            if room_id in rooms_data:
                rooms_data[room_id]["bounds"] = room.bounds
                rooms_data[room_id]["center"] = {
                    "x": room.bounds["x"] + room.bounds["width"] / 2,
                    "y": room.bounds["y"] + room.bounds["height"] / 2
                }

    # ==================== DRAWING ====================

    def _redraw(self):
        """Redraw the entire canvas"""
        self.canvas.delete("all")

        if not self.building_data:
            return

        # Draw grid
        self._draw_grid()

        # Draw rooms (filled)
        for room in self.rooms.values():
            self._draw_room(room)

        # Draw walls
        for wall in self.walls:
            self._draw_wall(wall)

        # Draw joints/corners (in endpoint mode)
        if self.edit_mode == EditMode.MOVE_ENDPOINT:
            self._draw_joints()

        # Draw doors
        for door in self.doors:
            self._draw_door(door)

        # Draw windows
        for window in self.windows:
            self._draw_window(window)

    def _draw_grid(self):
        """Draw background grid (1m spacing)"""
        grid_spacing = 1000 * self.scale  # 1m in pixels

        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()

        # Draw vertical lines
        x = self.offset_x % grid_spacing
        while x < w:
            self.canvas.create_line(x, 0, x, h, fill="#2a2a4a", tags="grid")
            x += grid_spacing

        # Draw horizontal lines
        y = self.offset_y % grid_spacing
        while y < h:
            self.canvas.create_line(0, y, w, y, fill="#2a2a4a", tags="grid")
            y += grid_spacing

    def _draw_room(self, room: Room):
        """Draw a room fill"""
        b = room.bounds
        x1 = self._to_canvas_x(b["x"])
        y1 = self._to_canvas_y(b["y"])
        x2 = self._to_canvas_x(b["x"] + b["width"])
        y2 = self._to_canvas_y(b["y"] + b["height"])

        colors = {
            "living": "#2d4a3d",
            "kitchen": "#4a3d2d",
            "bedroom": "#3d2d4a",
            "master_bedroom": "#4a2d3d",
            "bathroom": "#2d3d4a",
            "master_bath": "#2d4a4a",
            "hallway": "#3a3a3a",
            "garage": "#2a2a2a"
        }
        fill = colors.get(room.room_type, "#333344")

        room.canvas_id = self.canvas.create_rectangle(
            x1, y1, x2, y2,
            fill=fill, outline="",
            tags=("room", f"room_{room.id}")
        )

        cx = (x1 + x2) / 2
        cy = (y1 + y2) / 2
        room.label_id = self.canvas.create_text(
            cx, cy,
            text=room.name,
            fill="#888888",
            font=("Arial", 10),
            tags=("room_label", f"label_{room.id}")
        )

    def _draw_wall(self, wall: Wall):
        """Draw a wall"""
        x1 = self._to_canvas_x(wall.start[0])
        y1 = self._to_canvas_y(wall.start[1])
        x2 = self._to_canvas_x(wall.end[0])
        y2 = self._to_canvas_y(wall.end[1])

        colors = {
            "exterior": "#e0e0e0",
            "interior": "#a0a0a0",
            "wet_wall": "#80a0c0"
        }
        color = colors.get(wall.category, "#a0a0a0")

        # Highlight if selected
        if wall == self.selected_wall:
            color = "#ffff00"
        elif wall == self.trim_source_wall:
            color = "#ff8800"

        thickness = max(2, wall.thickness * self.scale * 0.5)

        wall.canvas_id = self.canvas.create_line(
            x1, y1, x2, y2,
            fill=color,
            width=thickness,
            tags=("wall", f"wall_{wall.id}")
        )

    def _draw_joints(self):
        """Draw joint handles for endpoint editing"""
        handle_radius = 6

        for joint in self.joints:
            x = self._to_canvas_x(joint.position[0])
            y = self._to_canvas_y(joint.position[1])

            # Color based on number of connections
            if len(joint.wall_endpoints) >= 3:
                color = "#00ff00"  # Green for T-joints or more
            elif len(joint.wall_endpoints) == 2:
                color = "#ffff00"  # Yellow for corners
            else:
                color = "#ff6600"  # Orange for endpoints

            self.canvas.create_oval(
                x - handle_radius, y - handle_radius,
                x + handle_radius, y + handle_radius,
                fill=color, outline="white",
                tags="joint"
            )

    def _draw_door(self, door: Door):
        """Draw a door on its wall"""
        if door.wall_index >= len(self.walls):
            return

        wall = self.walls[door.wall_index]
        dx = wall.end[0] - wall.start[0]
        dz = wall.end[1] - wall.start[1]
        wall_len = math.sqrt(dx*dx + dz*dz)

        if wall_len == 0:
            return

        t = door.offset / wall_len
        door_x = wall.start[0] + dx * t
        door_z = wall.start[1] + dz * t

        x = self._to_canvas_x(door_x)
        y = self._to_canvas_y(door_z)

        radius = door.width * self.scale * 0.5
        door.canvas_id = self.canvas.create_arc(
            x - radius, y - radius, x + radius, y + radius,
            start=0, extent=90,
            outline="#8080ff",
            style=tk.ARC,
            width=2,
            tags=("door", f"door_{door.wall_index}")
        )

    def _draw_window(self, window: Window):
        """Draw a window on its wall"""
        if window.wall_index >= len(self.walls):
            return

        wall = self.walls[window.wall_index]
        dx = wall.end[0] - wall.start[0]
        dz = wall.end[1] - wall.start[1]
        wall_len = math.sqrt(dx*dx + dz*dz)

        if wall_len == 0:
            return

        t = window.offset / wall_len
        win_x = wall.start[0] + dx * t
        win_z = wall.start[1] + dz * t

        x = self._to_canvas_x(win_x)
        y = self._to_canvas_y(win_z)

        half_w = window.width * self.scale * 0.25
        window.canvas_id = self.canvas.create_rectangle(
            x - half_w, y - 3, x + half_w, y + 3,
            fill="#80c0ff",
            outline="#4080c0",
            tags=("window", f"window_{window.wall_index}")
        )

    # ==================== COORDINATE CONVERSION ====================

    def _to_canvas_x(self, mm_x: float) -> float:
        return mm_x * self.scale + self.offset_x

    def _to_canvas_y(self, mm_z: float) -> float:
        return mm_z * self.scale + self.offset_y

    def _from_canvas_x(self, cx: float) -> float:
        return (cx - self.offset_x) / self.scale

    def _from_canvas_y(self, cy: float) -> float:
        return (cy - self.offset_y) / self.scale

    # ==================== VIEW CONTROLS ====================

    def _zoom(self, factor: float):
        self.scale *= factor
        self.scale = max(0.01, min(0.5, self.scale))
        self._redraw()

    def _fit_view(self):
        if not self.building_data:
            return

        width = self.building_data.get("width", 10000)
        depth = self.building_data.get("depth", 10000)

        canvas_w = self.canvas.winfo_width()
        canvas_h = self.canvas.winfo_height()

        margin = 100
        scale_x = (canvas_w - 2 * margin) / width
        scale_y = (canvas_h - 2 * margin) / depth
        self.scale = min(scale_x, scale_y)

        self.offset_x = (canvas_w - width * self.scale) / 2
        self.offset_y = (canvas_h - depth * self.scale) / 2

        self._redraw()

    # ==================== MOUSE EVENTS ====================

    def _on_click(self, event):
        """Handle mouse click"""
        mm_x = self._from_canvas_x(event.x)
        mm_y = self._from_canvas_y(event.y)

        if self.edit_mode == EditMode.SELECT:
            self._select_at(event.x, event.y)

        elif self.edit_mode == EditMode.MOVE_WALL:
            self._save_undo_state()
            self._start_wall_drag(event.x, event.y)

        elif self.edit_mode == EditMode.MOVE_ENDPOINT:
            # Find joint at click position
            joint = self._find_joint_at(mm_x, mm_y)
            if joint:
                self._save_undo_state()
                self.drag_start = (event.x, event.y)
                self.drag_start_mm = joint.position
                self.selected_endpoint = joint
            else:
                self.selected_endpoint = None

        elif self.edit_mode == EditMode.DISCONNECT:
            self._disconnect_endpoint(mm_x, mm_y)

        elif self.edit_mode == EditMode.TRIM_EXTEND:
            self._save_undo_state()
            self._handle_trim_click(mm_x, mm_y)

        elif self.edit_mode == EditMode.MOVE_ROOM:
            self._save_undo_state()
            self._start_room_drag(event.x, event.y)

    def _on_drag(self, event):
        """Handle mouse drag"""
        if self.drag_start is None:
            return

        if self.edit_mode == EditMode.MOVE_WALL and self.selected_wall:
            dx = event.x - self.drag_start[0]
            dy = event.y - self.drag_start[1]

            # Apply grid snap to delta
            if self.grid_snap:
                mm_dx = dx / self.scale
                mm_dy = dy / self.scale
                mm_dx = self._snap_to_grid(mm_dx)
                mm_dy = self._snap_to_grid(mm_dy)
                dx = mm_dx * self.scale
                dy = mm_dy * self.scale

            # Apply ortho constraint
            if self.ortho_mode:
                if abs(dx) > abs(dy):
                    dy = 0
                else:
                    dx = 0

            self._drag_wall(dx, dy)
            self.drag_start = (event.x, event.y)

        elif self.edit_mode == EditMode.MOVE_ENDPOINT and self.selected_endpoint:
            mm_x = self._from_canvas_x(event.x)
            mm_y = self._from_canvas_y(event.y)

            # Apply grid snap
            mm_x = self._snap_to_grid(mm_x)
            mm_y = self._snap_to_grid(mm_y)

            # Apply ortho constraint from original position
            if self.ortho_mode and self.drag_start_mm:
                mm_x, mm_y = self._constrain_ortho(self.drag_start_mm, (mm_x, mm_y))
                # Re-snap after ortho
                mm_x = self._snap_to_grid(mm_x)
                mm_y = self._snap_to_grid(mm_y)

            self._move_joint(self.selected_endpoint, (mm_x, mm_y))
            self._redraw()

        elif self.edit_mode == EditMode.MOVE_ROOM and self.selected_room:
            dx = event.x - self.drag_start[0]
            dy = event.y - self.drag_start[1]

            # Apply grid snap to delta
            if self.grid_snap:
                mm_dx = dx / self.scale
                mm_dy = dy / self.scale
                mm_dx = self._snap_to_grid(mm_dx)
                mm_dy = self._snap_to_grid(mm_dy)
                dx = mm_dx * self.scale
                dy = mm_dy * self.scale

            self._drag_room(dx, dy)
            self.drag_start = (event.x, event.y)

    def _on_release(self, event):
        """Handle mouse release"""
        if self.drag_start:
            self.modified = True
            self._build_joints()
            self._send_ws_update()
        self.drag_start = None
        self.drag_start_mm = None

    def _on_scroll(self, event):
        factor = 1.1 if event.delta > 0 else 0.9
        self._zoom(factor)

    def _on_right_click(self, event):
        """Context menu"""
        pass

    def _on_mouse_move(self, event):
        """Handle mouse move for hover effects"""
        mm_x = self._from_canvas_x(event.x)
        mm_y = self._from_canvas_y(event.y)

        # Update status with coordinates
        self.status_bar.config(
            text=f"X: {mm_x/1000:.2f}m  Y: {mm_y/1000:.2f}m | Mode: {self.edit_mode.value}"
        )

    def _start_pan(self, event):
        self.drag_start = (event.x, event.y)

    def _on_pan(self, event):
        if self.drag_start:
            dx = event.x - self.drag_start[0]
            dy = event.y - self.drag_start[1]
            self.offset_x += dx
            self.offset_y += dy
            self.drag_start = (event.x, event.y)
            self._redraw()

    # ==================== SELECTION ====================

    def _select_at(self, cx: float, cy: float):
        """Select item at canvas position"""
        self._deselect_all()

        items = self.canvas.find_closest(cx, cy)
        if items:
            tags = self.canvas.gettags(items[0])
            for tag in tags:
                if tag.startswith("wall_"):
                    wall_id = int(tag.split("_")[1])
                    if wall_id < len(self.walls):
                        self.selected_wall = self.walls[wall_id]
                        self._show_wall_props(self.selected_wall)
                        self._redraw()
                        return
                elif tag.startswith("room_"):
                    room_id = tag.split("_", 1)[1]
                    if room_id in self.rooms:
                        self.selected_room = self.rooms[room_id]
                        self._show_room_props(self.selected_room)
                        return

    def _deselect_all(self):
        """Clear selection"""
        self.selected_wall = None
        self.selected_room = None
        self.selected_endpoint = None
        self.props_text.delete(1.0, tk.END)
        self._redraw()

    def _delete_selected(self):
        """Delete selected item"""
        if self.selected_wall:
            self.walls.remove(self.selected_wall)
            self.selected_wall = None
            self._build_joints()
            self._redraw()
            self.modified = True

    # ==================== WALL DRAGGING ====================

    def _start_wall_drag(self, cx: float, cy: float):
        self._select_at(cx, cy)
        if self.selected_wall:
            self.drag_start = (cx, cy)

    def _drag_wall(self, dx: float, dy: float):
        """Drag wall - moves entire wall and connected joints"""
        if not self.selected_wall:
            return

        mm_dx = dx / self.scale
        mm_dy = dy / self.scale

        wall = self.selected_wall

        # Find joints at both ends
        start_joint = self._find_joint_at(wall.start[0], wall.start[1])
        end_joint = self._find_joint_at(wall.end[0], wall.end[1])

        # Move joints (which moves all connected walls)
        if start_joint:
            new_pos = (start_joint.position[0] + mm_dx, start_joint.position[1] + mm_dy)
            self._move_joint(start_joint, new_pos)

        if end_joint and end_joint != start_joint:
            new_pos = (end_joint.position[0] + mm_dx, end_joint.position[1] + mm_dy)
            self._move_joint(end_joint, new_pos)

        self._redraw()

    # ==================== ROOM DRAGGING ====================

    def _start_room_drag(self, cx: float, cy: float):
        self._select_at(cx, cy)
        if self.selected_room:
            self.drag_start = (cx, cy)

    def _drag_room(self, dx: float, dy: float):
        if not self.selected_room:
            return

        mm_dx = dx / self.scale
        mm_dy = dy / self.scale

        room = self.selected_room
        room.bounds["x"] += mm_dx
        room.bounds["y"] += mm_dy

        self._redraw()

    # ==================== TRIM/EXTEND ====================

    def _handle_trim_click(self, mm_x: float, mm_y: float):
        """Handle click in trim/extend mode"""
        # Find wall near click
        clicked_wall = self._find_wall_at(mm_x, mm_y)

        if clicked_wall is None:
            self.trim_source_wall = None
            self._redraw()
            self._update_status("Click on a wall to select for trim/extend")
            return

        if self.trim_source_wall is None:
            # First click - select source wall
            self.trim_source_wall = clicked_wall
            self._redraw()
            self._update_status(f"Selected wall {clicked_wall.id} - now click boundary wall")
        else:
            # Second click - trim to boundary
            if clicked_wall != self.trim_source_wall:
                self._trim_wall_to_boundary(self.trim_source_wall, clicked_wall)
            self.trim_source_wall = None
            self._redraw()

    def _find_wall_at(self, mm_x: float, mm_y: float) -> Optional[Wall]:
        """Find wall nearest to position"""
        best_dist = 500  # Max distance to wall in mm
        best_wall = None

        for wall in self.walls:
            dist = self._point_to_line_distance(
                (mm_x, mm_y), wall.start, wall.end
            )
            if dist < best_dist:
                best_dist = dist
                best_wall = wall

        return best_wall

    def _point_to_line_distance(self, point: Tuple[float, float],
                                line_start: Tuple[float, float],
                                line_end: Tuple[float, float]) -> float:
        """Calculate perpendicular distance from point to line segment"""
        px, py = point
        x1, y1 = line_start
        x2, y2 = line_end

        dx = x2 - x1
        dy = y2 - y1

        if dx == 0 and dy == 0:
            return math.sqrt((px - x1)**2 + (py - y1)**2)

        t = max(0, min(1, ((px - x1) * dx + (py - y1) * dy) / (dx*dx + dy*dy)))

        proj_x = x1 + t * dx
        proj_y = y1 + t * dy

        return math.sqrt((px - proj_x)**2 + (py - proj_y)**2)

    # ==================== PROPERTIES ====================

    def _show_wall_props(self, wall: Wall):
        self.props_text.delete(1.0, tk.END)

        length = math.sqrt(
            (wall.end[0] - wall.start[0])**2 +
            (wall.end[1] - wall.start[1])**2
        )

        # Find connected walls
        start_joint = self._find_joint_at(wall.start[0], wall.start[1])
        end_joint = self._find_joint_at(wall.end[0], wall.end[1])

        start_connections = len(start_joint.wall_endpoints) if start_joint else 0
        end_connections = len(end_joint.wall_endpoints) if end_joint else 0

        props = f"""Wall {wall.id}

Type: {wall.wall_type}
Category: {wall.category}
Height: {wall.height}mm ({wall.height/304.8:.1f}ft)
Length: {length:.0f}mm ({length/304.8:.1f}ft)

Start: ({wall.start[0]:.0f}, {wall.start[1]:.0f})
  Connected walls: {start_connections}
End: ({wall.end[0]:.0f}, {wall.end[1]:.0f})
  Connected walls: {end_connections}
"""
        self.props_text.insert(1.0, props)

    def _show_room_props(self, room: Room):
        self.props_text.delete(1.0, tk.END)

        area_sqm = (room.bounds["width"] * room.bounds["height"]) / 1e6
        area_sqft = area_sqm * 10.764

        props = f"""Room: {room.name}

Type: {room.room_type}
Area: {area_sqm:.1f} sqm ({area_sqft:.0f} sqft)

Position: ({room.bounds['x']:.0f}, {room.bounds['y']:.0f})
Size: {room.bounds['width']:.0f} x {room.bounds['height']:.0f} mm
"""
        self.props_text.insert(1.0, props)

    def _update_status(self, message: str):
        self.status_bar.config(text=message)

    # ==================== WEBSOCKET ====================

    def _toggle_websocket(self):
        if self.ws_thread and self.ws_thread.is_alive():
            self.ws_status.config(text="WS: Disconnected", foreground="gray")
        else:
            self._start_websocket_server()

    def _start_websocket_server(self):
        async def handler(websocket, path):
            self.ws_clients.add(websocket)
            try:
                if self.building_data:
                    await websocket.send(json.dumps(self.building_data))
                async for message in websocket:
                    pass
            finally:
                self.ws_clients.remove(websocket)

        async def start_server():
            async with websockets.serve(handler, "localhost", 8765):
                await asyncio.Future()

        def run_server():
            asyncio.run(start_server())

        self.ws_thread = threading.Thread(target=run_server, daemon=True)
        self.ws_thread.start()
        self.ws_status.config(text="WS: Listening :8765", foreground="green")
        self._update_status("WebSocket server started on port 8765")

    def _send_ws_update(self):
        if not self.ws_clients or not self.building_data:
            return

        self._update_building_data()
        message = json.dumps(self.building_data)

        async def send_all():
            for client in self.ws_clients.copy():
                try:
                    await client.send(message)
                except:
                    self.ws_clients.discard(client)

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(send_all())
            else:
                asyncio.run(send_all())
        except:
            pass


def main():
    root = tk.Tk()
    app = PlanEditor2D(root)

    default_file = Path("X:/ARCH/Software/ArchEngine_Suite/Shared/TestData/output/generated_building.json")
    if default_file.exists():
        root.after(100, lambda: app._load_file(default_file))

    root.mainloop()


if __name__ == "__main__":
    main()
