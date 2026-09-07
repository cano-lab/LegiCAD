"""
ArchDocument - Central document model

Single source of truth for building data.
Wraps JSON building data with change tracking and signals.

Now integrates with shared ArchGeometry library for geometry queries
while maintaining mutable model for CAD editing.
"""
import json
import copy
import sys
from pathlib import Path
from typing import Optional, Dict, List, Any, Tuple
from dataclasses import dataclass, field

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QUndoStack

from core.events import event_bus
from core.version_control import VersionControl
from core.terrain import generate_test_terrain

# Try to import furniture module
_FURNITURE_AVAILABLE = False
try:
    from furniture.models import FurnitureItem, FurniturePlacement, FurnitureCategory
    from furniture.catalog import get_default_catalog
    _FURNITURE_AVAILABLE = True
except ImportError:
    FurnitureItem = None
    FurniturePlacement = None
    FurnitureCategory = None
    get_default_catalog = None

# Try to import shared geometry library
_ARCHGEOMETRY_AVAILABLE = False
try:
    # Add shared library path
    _lib_path = Path(__file__).parent.parent.parent / "Shared" / "ArchGeometry" / "python"
    if _lib_path.exists() and str(_lib_path) not in sys.path:
        sys.path.insert(0, str(_lib_path))
    import archgeometry_py as archgeometry
    _ARCHGEOMETRY_AVAILABLE = True
except ImportError:
    archgeometry = None


@dataclass
class Wall:
    """Wall data structure."""
    index: int
    start: Tuple[float, float, float]  # x, y, z
    end: Tuple[float, float, float]
    height: float = 2700
    category: str = "interior"  # exterior, interior, wet_wall
    wall_type: str = ""
    material_override: str = ""  # Material ID override (empty = use wall_type default)
    # Structural binding - walls bound to room boundaries at LOD 1-2
    is_structural: bool = True  # Structural walls define room boundaries
    bound_room_id: str = ""  # Room this wall belongs to (empty = unbound partition)
    edge_index: int = -1  # Which edge of the room polygon (-1 = not bound)
    # Constraint fields
    is_pinned: bool = False
    locked_properties: List[str] = field(default_factory=list)

    @property
    def start_2d(self) -> Tuple[float, float]:
        """Get 2D start point (X, Z)."""
        return (self.start[0], self.start[2])

    @property
    def end_2d(self) -> Tuple[float, float]:
        """Get 2D end point (X, Z)."""
        return (self.end[0], self.end[2])

    @property
    def length(self) -> float:
        """Calculate wall length."""
        dx = self.end[0] - self.start[0]
        dz = self.end[2] - self.start[2]
        return (dx**2 + dz**2) ** 0.5


@dataclass
class Door:
    """Door data structure."""
    index: int
    wall_index: int
    offset: float
    width: float = 914
    height: float = 2134
    door_type: str = "swing"
    swing: str = "left_in"
    # Constraint fields
    is_pinned: bool = False
    locked_properties: List[str] = field(default_factory=list)


@dataclass
class Window:
    """Window data structure."""
    index: int
    wall_index: int
    offset: float
    width: float = 1200
    height: float = 1200
    sill_height: float = 900
    # Constraint fields
    is_pinned: bool = False
    locked_properties: List[str] = field(default_factory=list)


@dataclass
class Floor:
    """Floor slab data structure."""
    index: int
    vertices: List[List[float]]  # Polygon vertices [[x, z], ...]
    thickness: float = 150  # mm (typical slab thickness)
    elevation: float = 0  # Y position (bottom of slab)
    material: str = "concrete"
    room_ids: List[str] = field(default_factory=list)  # Rooms this floor covers

    @property
    def area(self) -> float:
        """Calculate floor area using shoelace formula."""
        if not self.vertices or len(self.vertices) < 3:
            return 0
        area = 0
        n = len(self.vertices)
        for i in range(n):
            j = (i + 1) % n
            area += self.vertices[i][0] * self.vertices[j][1]
            area -= self.vertices[j][0] * self.vertices[i][1]
        return abs(area) / 2.0 / 1_000_000.0  # mm² to m²


@dataclass
class Roof:
    """Roof data structure."""
    index: int
    roof_type: str  # 'hip', 'gable', 'flat', 'shed', 'mansard'
    base_vertices: List[List[float]]  # Base polygon [[x, z], ...]
    ridge_vertices: List[List[float]]  # Ridge line(s) [[x, z], ...]
    base_height: float  # Y position at eaves (top of walls)
    ridge_height: float  # Y position at ridge peak
    pitch: float = 30.0  # Roof pitch in degrees
    overhang: float = 300  # Eave overhang in mm
    material: str = "shingle"

    @property
    def slope_height(self) -> float:
        """Height from eave to ridge."""
        return self.ridge_height - self.base_height


@dataclass
class WallLayer:
    """Single layer of a wall assembly."""
    name: str
    material: str
    thickness: float  # mm
    function: str  # exterior_finish, membrane, sheathing, structure, insulation, interior_finish
    color: Tuple[float, float, float, float]  # RGBA 0-1
    r_value: float = 0.0


@dataclass
class WallType:
    """Wall type definition with layers."""
    id: str
    name: str
    layers: List[WallLayer]
    total_thickness: float = 0.0

    def __post_init__(self):
        self.total_thickness = sum(layer.thickness for layer in self.layers)


@dataclass
class Room:
    """Room data structure."""
    id: str
    name: str
    room_type: str
    bounds: Dict[str, float]  # x, y, width, height (bounding box)
    area: float = 0
    center: Optional[Dict[str, float]] = None
    vertices: Optional[List[List[float]]] = None  # Polygon vertices [[x,z], ...]
    index: int = -1  # Index in rooms list
    # Constraint fields
    is_pinned: bool = False
    locked_properties: List[str] = field(default_factory=list)
    # Floor elevation for terrain placement
    floor_z: float = 0.0


# Room types that default to 'open' connections with each other
# These are circulation spaces and open-plan living areas
OPEN_ROOM_TYPES = {
    'hallway', 'corridor', 'foyer', 'entry',  # Circulation
    'living', 'dining', 'kitchen', 'great_room',  # Open-plan living
    'open', 'gallery', 'loft'  # Explicitly open spaces
}


@dataclass
class RoomConnection:
    """Connection between two adjacent rooms."""
    room_a_id: str
    room_b_id: str
    connection_type: str  # 'structural', 'open', 'mechanical', 'insulated', 'undefined', 'wall', 'wet_wall'
    shared_edge: Optional[List[List[float]]] = None  # [[x1,y1], [x2,y2]] where rooms meet
    wall_id: Optional[str] = None  # Generated wall if applicable

    def other_room(self, room_id: str) -> Optional[str]:
        """Get the other room in this connection."""
        if room_id == self.room_a_id:
            return self.room_b_id
        elif room_id == self.room_b_id:
            return self.room_a_id
        return None


@dataclass
class ReferencePlane:
    """
    Reference plane (grid line) for aligning building elements.

    Reference planes define the building grid - typically labeled
    A, B, C... for one direction and 1, 2, 3... for the other.
    Exterior walls align to these planes.
    """
    id: str
    label: str  # Display label (A, B, 1, 2, etc.)
    direction: str  # 'horizontal' or 'vertical'
    position: float  # Offset from origin (X for vertical, Z for horizontal)
    is_exterior: bool = True  # True if this defines building boundary
    bound_walls: List[str] = field(default_factory=list)  # Wall indices bound to this plane

    @property
    def is_horizontal(self) -> bool:
        return self.direction == 'horizontal'

    @property
    def is_vertical(self) -> bool:
        return self.direction == 'vertical'


class ArchDocument(QObject):
    """
    Central document model - single source of truth.
    Wraps the JSON building data with change tracking.
    """

    # Signals
    document_changed = pyqtSignal()
    element_added = pyqtSignal(str, str)      # element_type, element_id
    element_modified = pyqtSignal(str, str)   # element_type, element_id
    element_removed = pyqtSignal(str, str)    # element_type, element_id
    element_pinned = pyqtSignal(str, str, bool)  # element_type, element_id, is_pinned

    def __init__(self, parent=None):
        super().__init__(parent)

        # Raw JSON data
        self._data: Dict[str, Any] = {}

        # File path
        self._file_path: Optional[Path] = None

        # Modified flag
        self._modified: bool = False

        # Undo stack
        self._undo_stack = QUndoStack(self)

        # Parsed elements (cached)
        self._walls: List[Wall] = []
        self._doors: List[Door] = []
        self._windows: List[Window] = []
        self._floors: List[Floor] = []  # Floor slabs
        self._roofs: List[Roof] = []  # Roof structures
        self._rooms: Dict[str, Room] = {}
        self._wall_types: Dict[str, WallType] = {}
        self._room_connections: List[RoomConnection] = []  # Room adjacencies
        self._furniture: List[Any] = []  # FurniturePlacement objects
        self._reference_planes: List[ReferencePlane] = []  # Building grid lines

        # Furniture catalog reference
        self._furniture_catalog = get_default_catalog() if _FURNITURE_AVAILABLE else None

        # Version control (git-based)
        self._version_control: Optional[VersionControl] = None

    @property
    def file_path(self) -> Optional[Path]:
        """Get current file path."""
        return self._file_path

    @property
    def modified(self) -> bool:
        """Check if document has unsaved changes."""
        return self._modified

    @property
    def undo_stack(self) -> QUndoStack:
        """Get undo stack."""
        return self._undo_stack

    @property
    def data(self) -> Dict[str, Any]:
        """Get raw JSON data."""
        return self._data

    @property
    def walls(self) -> List[Wall]:
        """Get parsed walls."""
        if len(self._walls) == 0:
            print("[Document] WARNING: walls property accessed but _walls is empty!")
        return self._walls

    @property
    def doors(self) -> List[Door]:
        """Get parsed doors."""
        return self._doors

    @property
    def windows(self) -> List[Window]:
        """Get parsed windows."""
        return self._windows

    @property
    def floors(self) -> List[Floor]:
        """Get parsed floor slabs."""
        return self._floors

    @property
    def roofs(self) -> List[Roof]:
        """Get parsed roof structures."""
        return self._roofs

    @property
    def rooms(self) -> Dict[str, Room]:
        """Get parsed rooms."""
        return self._rooms

    @property
    def room_connections(self) -> List[RoomConnection]:
        """Get room adjacency connections."""
        return self._room_connections

    def get_room_neighbors(self, room_id: str) -> List[str]:
        """Get list of room IDs adjacent to the given room."""
        neighbors = []
        for conn in self._room_connections:
            other = conn.other_room(room_id)
            if other:
                neighbors.append(other)
        return neighbors

    def get_connection(self, room_a_id: str, room_b_id: str) -> Optional[RoomConnection]:
        """Get connection between two specific rooms."""
        for conn in self._room_connections:
            if (conn.room_a_id == room_a_id and conn.room_b_id == room_b_id) or \
               (conn.room_a_id == room_b_id and conn.room_b_id == room_a_id):
                return conn
        return None

    @property
    def reference_planes(self) -> List[ReferencePlane]:
        """Get building reference planes (grid lines)."""
        return self._reference_planes

    def get_reference_plane(self, plane_id: str) -> Optional[ReferencePlane]:
        """Get reference plane by ID."""
        for plane in self._reference_planes:
            if plane.id == plane_id:
                return plane
        return None

    def add_reference_plane(self, plane: ReferencePlane):
        """Add a reference plane."""
        self._reference_planes.append(plane)
        self._modified = True

    def remove_reference_plane(self, plane_id: str):
        """Remove a reference plane by ID."""
        self._reference_planes = [p for p in self._reference_planes if p.id != plane_id]
        self._modified = True

    @property
    def onboarding_completed(self) -> bool:
        """Check if this document has completed the onboarding flow."""
        return self._data.get('onboarding_completed', False)

    def complete_onboarding(self):
        """
        Mark onboarding as completed for this document.

        This flag is saved with the document, so each file remembers
        its own onboarding state. New files start with onboarding not completed.
        """
        self._data['onboarding_completed'] = True
        self._modified = True

    def reset_onboarding(self):
        """
        Reset onboarding for this document.

        Use this to re-run the onboarding flow for an existing document.
        The change must be saved to persist.
        """
        self._data['onboarding_completed'] = False
        self._modified = True

    def generate_reference_planes_from_extents(self):
        """
        Auto-generate reference planes from building extents.
        Creates planes at the min/max X and Z coordinates of all rooms.
        """
        if not self._rooms:
            return

        # Find building extents from room vertices
        min_x = float('inf')
        max_x = float('-inf')
        min_z = float('inf')
        max_z = float('-inf')

        for room in self._rooms.values():
            if not room.vertices:
                continue
            for v in room.vertices:
                min_x = min(min_x, v[0])
                max_x = max(max_x, v[0])
                min_z = min(min_z, v[1])
                max_z = max(max_z, v[1])

        if min_x == float('inf'):
            return

        # Clear existing exterior reference planes
        self._reference_planes = [p for p in self._reference_planes if not p.is_exterior]

        # Create vertical planes (at X positions) - labeled A, B, C...
        # Left edge
        self._reference_planes.append(ReferencePlane(
            id='ref_v_a',
            label='A',
            direction='vertical',
            position=min_x,
            is_exterior=True
        ))
        # Right edge
        self._reference_planes.append(ReferencePlane(
            id='ref_v_b',
            label='B',
            direction='vertical',
            position=max_x,
            is_exterior=True
        ))

        # Create horizontal planes (at Z positions) - labeled 1, 2...
        # Bottom edge
        self._reference_planes.append(ReferencePlane(
            id='ref_h_1',
            label='1',
            direction='horizontal',
            position=min_z,
            is_exterior=True
        ))
        # Top edge
        self._reference_planes.append(ReferencePlane(
            id='ref_h_2',
            label='2',
            direction='horizontal',
            position=max_z,
            is_exterior=True
        ))

        print(f"[RefPlanes] Generated 4 reference planes from building extents")
        print(f"[RefPlanes] X: {min_x:.0f} to {max_x:.0f}, Z: {min_z:.0f} to {max_z:.0f}")
        self._modified = True

    def snap_exterior_walls_to_planes(self, tolerance: float = 500.0):
        """
        Snap exterior wall endpoints to nearest reference planes.
        """
        if not self._reference_planes:
            print("[RefPlanes] No reference planes defined")
            return 0

        snapped_count = 0

        for wall in self._walls:
            if wall.category != 'exterior':
                continue

            # Get wall endpoints (X, Z coordinates)
            start_x, start_z = wall.start[0], wall.start[2]
            end_x, end_z = wall.end[0], wall.end[2]

            # Check vertical planes (snap X coordinates)
            for plane in self._reference_planes:
                if plane.is_vertical:
                    # Snap start X
                    if abs(start_x - plane.position) < tolerance:
                        wall.start = (plane.position, wall.start[1], wall.start[2])
                        snapped_count += 1
                    # Snap end X
                    if abs(end_x - plane.position) < tolerance:
                        wall.end = (plane.position, wall.end[1], wall.end[2])
                        snapped_count += 1
                else:  # Horizontal plane
                    # Snap start Z
                    if abs(start_z - plane.position) < tolerance:
                        wall.start = (wall.start[0], wall.start[1], plane.position)
                        snapped_count += 1
                    # Snap end Z
                    if abs(end_z - plane.position) < tolerance:
                        wall.end = (wall.end[0], wall.end[1], plane.position)
                        snapped_count += 1

        if snapped_count > 0:
            self._modified = True
            print(f"[RefPlanes] Snapped {snapped_count} wall endpoints to reference planes")

        return snapped_count

    def recalculate_room_areas(self):
        """
        Recalculate all room areas from their vertices using the shoelace formula.
        Call this after syncing rooms from the renderer or modifying room geometry.
        """
        updated = 0
        for room in self._rooms.values():
            if not room.vertices or len(room.vertices) < 3:
                continue

            # Shoelace formula for polygon area
            area = 0.0
            n = len(room.vertices)
            for i in range(n):
                j = (i + 1) % n
                area += room.vertices[i][0] * room.vertices[j][1]
                area -= room.vertices[j][0] * room.vertices[i][1]

            # Area is in mm², convert to m²
            room.area = abs(area) / 2.0 / 1_000_000.0  # mm² to m²
            updated += 1

        if updated > 0:
            print(f"[Document] Recalculated areas for {updated} rooms")

        return updated

    def _get_default_connection_type(self, room_a: Room, room_b: Room) -> str:
        """
        Determine default connection type based on room types.

        Open room types (hallway, living, dining, kitchen, etc.) default
        to 'open' connections with each other. Other room combinations
        default to 'wall' (interior partition).

        Args:
            room_a: First room
            room_b: Second room

        Returns:
            'open' if both rooms are open types, otherwise 'wall'
        """
        # Get room types, normalized to lowercase
        type_a = (room_a.room_type or '').lower()
        type_b = (room_b.room_type or '').lower()

        # If both rooms are open types, default to 'open' (no wall)
        if type_a in OPEN_ROOM_TYPES and type_b in OPEN_ROOM_TYPES:
            return 'open'

        # Default to regular interior wall
        return 'wall'

    def detect_room_adjacencies(self, threshold: float = 500.0):
        """
        Detect which rooms are adjacent by checking for overlapping/touching edges.

        Args:
            threshold: Maximum distance (mm) between edges to consider adjacent
        """
        # Preserve existing connection types before clearing
        existing_types = {}
        for conn in self._room_connections:
            # Use sorted tuple as key to handle both orderings
            key = tuple(sorted([conn.room_a_id, conn.room_b_id]))
            # Only preserve explicitly set types (not 'undefined')
            if conn.connection_type and conn.connection_type != 'undefined':
                existing_types[key] = conn.connection_type

        self._room_connections.clear()
        room_ids = list(self._rooms.keys())
        print(f"[Adjacency] Checking {len(room_ids)} rooms for adjacencies (threshold={threshold}mm)")

        for i, room_a_id in enumerate(room_ids):
            room_a = self._rooms[room_a_id]
            if not room_a.vertices or len(room_a.vertices) < 3:
                print(f"[Adjacency] Skipping {room_a.name} - no vertices")
                continue

            for room_b_id in room_ids[i+1:]:
                room_b = self._rooms[room_b_id]
                if not room_b.vertices or len(room_b.vertices) < 3:
                    continue

                # Check for shared/overlapping edges
                shared_edge = self._find_shared_edge(room_a, room_b, threshold)
                if shared_edge:
                    # Restore previous connection type if it existed,
                    # otherwise use smart default based on room types
                    key = tuple(sorted([room_a_id, room_b_id]))
                    if key in existing_types:
                        conn_type = existing_types[key]
                    else:
                        conn_type = self._get_default_connection_type(room_a, room_b)

                    conn = RoomConnection(
                        room_a_id=room_a_id,
                        room_b_id=room_b_id,
                        connection_type=conn_type,
                        shared_edge=shared_edge
                    )
                    self._room_connections.append(conn)
                    print(f"[Adjacency] {room_a.name} <-> {room_b.name} ({conn_type})")

    def _find_shared_edge(self, room_a: Room, room_b: Room, threshold: float) -> Optional[List[List[float]]]:
        """
        Find shared edge between two room polygons.

        Returns the overlapping segment if edges are collinear and overlap,
        or None if rooms don't share an edge.
        """
        # Check each edge of room_a against each edge of room_b
        for i in range(len(room_a.vertices)):
            a1 = room_a.vertices[i]
            a2 = room_a.vertices[(i + 1) % len(room_a.vertices)]

            for j in range(len(room_b.vertices)):
                b1 = room_b.vertices[j]
                b2 = room_b.vertices[(j + 1) % len(room_b.vertices)]

                # Check if edges are parallel and close enough
                overlap = self._edges_overlap(a1, a2, b1, b2, threshold)
                if overlap:
                    return overlap

        return None

    def _edges_overlap(self, a1: List[float], a2: List[float],
                       b1: List[float], b2: List[float],
                       threshold: float) -> Optional[List[List[float]]]:
        """
        Check if two edges overlap (are collinear and share a segment).

        Returns overlapping segment [[x1,y1], [x2,y2]] or None.
        """
        import math

        # Edge vectors
        ax, ay = a2[0] - a1[0], a2[1] - a1[1]
        bx, by = b2[0] - b1[0], b2[1] - b1[1]

        # Edge lengths
        len_a = math.sqrt(ax*ax + ay*ay)
        len_b = math.sqrt(bx*bx + by*by)

        if len_a < 1 or len_b < 1:
            return None

        # Normalize
        ax, ay = ax/len_a, ay/len_a
        bx, by = bx/len_b, by/len_b

        # Check if parallel (dot product of normals close to 1 or -1)
        dot = abs(ax*bx + ay*by)
        if dot < 0.99:  # Not parallel
            return None

        # Project b1 onto line defined by a1-a2 and check distance
        # Vector from a1 to b1
        vx, vy = b1[0] - a1[0], b1[1] - a1[1]

        # Distance from b1 to line a1-a2
        # Cross product gives signed area, divide by length for distance
        cross = ax * vy - ay * vx
        dist = abs(cross)  # Already normalized

        if dist > threshold:
            return None

        # Edges are parallel and close - find overlap
        # Project all points onto the line direction
        def project(p):
            return (p[0] - a1[0]) * ax + (p[1] - a1[1]) * ay

        t_a1, t_a2 = 0, len_a
        t_b1, t_b2 = project(b1), project(b2)

        # Ensure t_b1 < t_b2
        if t_b1 > t_b2:
            t_b1, t_b2 = t_b2, t_b1

        # Find overlap
        t_start = max(t_a1, t_b1)
        t_end = min(t_a2, t_b2)

        if t_end - t_start < 10:  # Minimum overlap of 10mm
            return None

        # Convert back to coordinates
        p1 = [a1[0] + ax * t_start, a1[1] + ay * t_start]
        p2 = [a1[0] + ax * t_end, a1[1] + ay * t_end]

        return [p1, p2]

    def set_connection_type(self, room_a_id: str, room_b_id: str, connection_type: str):
        """Set the connection type between two rooms."""
        conn = self.get_connection(room_a_id, room_b_id)
        if conn:
            conn.connection_type = connection_type
            self._modified = True
            print(f"[Adjacency] Set {room_a_id} <-> {room_b_id} = {connection_type}")

    @property
    def wall_types(self) -> Dict[str, WallType]:
        """Get parsed wall types."""
        return self._wall_types

    def get_wall_type(self, type_id: str) -> Optional[WallType]:
        """Get wall type by ID."""
        return self._wall_types.get(type_id)

    @property
    def building_width(self) -> float:
        """Get building width."""
        return self._data.get('width', 10000)

    @property
    def building_depth(self) -> float:
        """Get building depth."""
        return self._data.get('depth', 10000)

    # =========================================================================
    # File I/O
    # =========================================================================

    def new(self):
        """Create a new empty document."""
        self._data = {
            'building_id': 'new_building',
            'width': 10000,
            'depth': 10000,
            'building_type': 'residential',
            'walls_batch': [],
            'doors': [],
            'windows': [],
            'rooms': {},
            'roofs': [],
            'wall_types': [],
            'onboarding_completed': False,  # Track if this file has completed onboarding
            # Dimension settings for smart auto-dimensioning
            'dimension_settings': {
                # Auto-dimension rules
                'auto_exterior_walls': True,      # Dimension exterior wall chains
                'auto_openings': True,            # Dimension door/window widths
                'auto_rooms': True,               # Dimension room overall dims
                'auto_heights': True,             # Heights on elevations/sections
                # Display settings
                'unit': 'mm',                     # Internal unit
                'display_format': 'metric',       # 'imperial' (3'-6") or 'metric' (1067)
                'text_size': 300,
                'line_width': 3,
                'tick_length': 150,
                'offset_from_wall': 600,          # First chain offset
                'chain_spacing': 400,             # Between stacked chains
            },
            'dimension_overrides': []             # List of override objects
        }

        # Add test terrain for development
        try:
            test_terrain = generate_test_terrain(width_ft=100, depth_ft=100, grid_size=15)
            if test_terrain:
                self._data['terrain_mesh'] = test_terrain.to_dict()
                print(f"[Document] Added test terrain: {len(test_terrain.vertices)} vertices, {len(test_terrain.indices)//3} triangles")
                print(f"[Document] Terrain elevation range: {test_terrain.min_elevation:.1f} to {test_terrain.max_elevation:.1f} ft")
        except Exception as e:
            print(f"[Document] Could not generate test terrain: {e}")
            import traceback
            traceback.print_exc()

        self._file_path = None
        self._modified = False
        self._parse_data()
        self.document_changed.emit()
        event_bus.document_loaded.emit("")

    def load(self, file_path: Path) -> bool:
        """
        Load document from JSON file.

        Args:
            file_path: Path to JSON file

        Returns:
            True if successful, False otherwise
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                self._data = json.load(f)

            self._file_path = Path(file_path)
            self._modified = False
            self._parse_data()
            self._undo_stack.clear()

            # Initialize version control
            self._version_control = VersionControl(self._file_path)
            self._version_control.init()

            self.document_changed.emit()
            event_bus.document_loaded.emit(str(file_path))

            return True

        except (json.JSONDecodeError, IOError) as e:
            print(f"Error loading file: {e}")
            return False

    def save(self, file_path: Optional[Path] = None) -> bool:
        """
        Save document to JSON file with git versioning.

        Args:
            file_path: Path to save to (uses current path if None)

        Returns:
            True if successful, False otherwise
        """
        save_path = Path(file_path) if file_path else self._file_path
        if not save_path:
            return False

        try:
            # Update data from parsed elements
            self._update_data()

            # Convert to JSON string
            content = json.dumps(self._data, indent=2)

            # Show changes summary before saving
            if self._version_control:
                summary = self._version_control.get_changes_summary(content)
                if summary:
                    changes = []
                    if summary['walls_modified']:
                        changes.append(f"{summary['walls_modified']} walls modified")
                    if summary['walls_added']:
                        changes.append(f"{summary['walls_added']} walls added")
                    if summary['walls_removed']:
                        changes.append(f"{summary['walls_removed']} walls removed")
                    if summary['doors_changed']:
                        changes.append(f"{summary['doors_changed']} doors changed")
                    if summary['windows_changed']:
                        changes.append(f"{summary['windows_changed']} windows changed")
                    if changes:
                        print(f"Saving changes: {', '.join(changes)}")

            # Write to file
            with open(save_path, 'w', encoding='utf-8') as f:
                f.write(content)

            # Commit to version control
            if self._version_control:
                self._version_control.commit(content)

            self._file_path = save_path
            self._modified = False

            event_bus.document_saved.emit(str(save_path))

            return True

        except IOError as e:
            print(f"Error saving file: {e}")
            return False

    def get_history(self) -> List[Dict]:
        """Get version history of current file."""
        if self._version_control:
            return self._version_control.get_history()
        return []

    def revert_to_version(self, commit_hash: str) -> bool:
        """Revert to a previous version."""
        if self._version_control:
            if self._version_control.revert_to(commit_hash):
                # Reload the file
                return self.load(self._file_path)
        return False

    # =========================================================================
    # Data Parsing
    # =========================================================================

    def _parse_data(self):
        """Parse JSON data into typed objects."""
        self._walls.clear()
        self._doors.clear()
        self._windows.clear()
        self._rooms.clear()
        self._wall_types.clear()

        # Parse wall types first (needed for wall thickness)
        for wt in self._data.get('wall_types', []):
            layers = []
            for layer_data in wt.get('layers', []):
                layer = WallLayer(
                    name=layer_data.get('name', ''),
                    material=layer_data.get('material', ''),
                    thickness=layer_data.get('thickness', 0),
                    function=layer_data.get('function', ''),
                    color=tuple(layer_data.get('color', [0.5, 0.5, 0.5, 1.0])),
                    r_value=layer_data.get('r_value', 0)
                )
                layers.append(layer)

            wall_type = WallType(
                id=wt.get('id', ''),
                name=wt.get('name', ''),
                layers=layers
            )
            self._wall_types[wall_type.id] = wall_type

        # Parse walls
        for i, w in enumerate(self._data.get('walls_batch', [])):
            wall = Wall(
                index=i,
                start=tuple(w.get('start', [0, 0, 0])),
                end=tuple(w.get('end', [0, 0, 0])),
                height=w.get('height', 2700),
                category=w.get('category', 'interior'),
                wall_type=w.get('wall_type', ''),
                material_override=w.get('material_override', ''),
                is_structural=w.get('is_structural', True),
                bound_room_id=w.get('bound_room_id', ''),
                edge_index=w.get('edge_index', -1),
                is_pinned=w.get('is_pinned', False),
                locked_properties=w.get('locked_properties', [])
            )
            self._walls.append(wall)

        print(f"[Document] Parsed {len(self._walls)} walls from walls_batch")

        # Parse doors
        for i, d in enumerate(self._data.get('doors', [])):
            door = Door(
                index=i,
                wall_index=d.get('wall_index', 0),
                offset=d.get('offset', 0),
                width=d.get('width', 914),
                height=d.get('height', 2134),
                door_type=d.get('type', 'swing'),
                swing=d.get('swing', 'left_in'),
                is_pinned=d.get('is_pinned', False),
                locked_properties=d.get('locked_properties', [])
            )
            self._doors.append(door)

        # Parse windows
        for i, w in enumerate(self._data.get('windows', [])):
            window = Window(
                index=i,
                wall_index=w.get('wall_index', 0),
                offset=w.get('offset', 0),
                width=w.get('width', 1200),
                height=w.get('height', 1200),
                sill_height=w.get('sill_height', 900),
                is_pinned=w.get('is_pinned', False),
                locked_properties=w.get('locked_properties', [])
            )
            self._windows.append(window)

        # Parse rooms
        for room_id, r in self._data.get('rooms', {}).items():
            bounds = r.get('bounds', {'x': 0, 'y': 0, 'width': 0, 'height': 0})

            # Get vertices from data, or generate from bounds if not present
            vertices = r.get('vertices')
            if vertices is None and bounds.get('width', 0) > 0 and bounds.get('height', 0) > 0:
                # Generate rectangular vertices from bounds
                x = bounds['x']
                y = bounds['y']  # This is actually z in world coords
                w = bounds['width']
                h = bounds['height']
                vertices = [
                    [x, y],           # Bottom-left
                    [x + w, y],       # Bottom-right
                    [x + w, y + h],   # Top-right
                    [x, y + h]        # Top-left
                ]

            room = Room(
                id=room_id,
                name=r.get('name', room_id),
                room_type=r.get('room_type', 'room'),
                bounds=bounds,
                area=r.get('area', 0),
                center=r.get('center'),
                vertices=vertices,
                is_pinned=r.get('is_pinned', False),
                locked_properties=r.get('locked_properties', [])
            )
            self._rooms[room_id] = room

        # Load room connections
        for conn_data in self._data.get('room_connections', []):
            conn = RoomConnection(
                room_a_id=conn_data['room_a_id'],
                room_b_id=conn_data['room_b_id'],
                connection_type=conn_data.get('connection_type', 'undefined'),
                shared_edge=conn_data.get('shared_edge'),
                wall_id=conn_data.get('wall_id')
            )
            self._room_connections.append(conn)

        # Detect room adjacencies if not loaded from data
        print(f"[Document] Rooms loaded: {len(self._rooms)}, connections: {len(self._room_connections)}")
        if not self._room_connections and len(self._rooms) > 1:
            self.detect_room_adjacencies()

        # Regenerate walls from room relationships to ensure consistency
        # This ensures walls match connection types (open connections = no wall)
        # BUT skip if walls were already loaded from JSON (e.g., from QBD generator)
        if len(self._rooms) > 0:
            if len(self._walls) == 0:
                # No walls loaded - generate from room edges
                print(f"[Document] No walls loaded - generating from room edges")
                self.generate_walls_from_rooms()
            else:
                print(f"[Document] Walls already loaded ({len(self._walls)}) - skipping regeneration")

        # Lift building to sit on terrain BEFORE generating roof/floors
        # This ensures roof sits on top of lifted walls
        lift_mm = self._lift_building_to_terrain()

        # Store lift amount for new elements (floors generated later)
        if lift_mm > 0:
            self._data['_terrain_lift_mm'] = lift_mm
            print(f"[Document] Stored terrain lift: {lift_mm:.0f} mm for new elements")

        # Generate floors and roof after lifting (so they use correct heights)
        if len(self._rooms) > 0:
            self.generate_floors_from_rooms()
            print(f"[Document] After floor gen: {len(self._walls)} walls, {len(self._floors)} floors")
            # Generate roof at standard wall height (2700mm)
            # C++ will lift the roof along with all other elements
            roof_wall_height = 2700.0
            print(f"[RoofGen] Generating roof at wall_height={roof_wall_height:.0f}mm (C++ will handle terrain lift)")
            self.generate_roof(roof_type='hip', pitch=30.0, wall_height=roof_wall_height)

        # Validate and regenerate terrain if it has buggy data
        # Old terrain data has all Z values = 0 (was a bug in terrain generation)
        self._validate_and_regenerate_terrain()

    def _lift_building_to_terrain(self) -> float:
        """Lift building elements to sit on terrain surface.

        Samples terrain elevation at building origin and lifts all walls,
        doors, windows, and floors to sit on the terrain surface.
        Roof generation depends on correct wall heights, so this must be
        called BEFORE generate_roof().

        Returns:
            Lift amount in mm, or 0 if no lift was applied.
        """
        # Check if we have terrain and building origin
        building_origin = self._data.get('building_origin')
        if not building_origin:
            return 0.0  # No building origin, nothing to lift

        # Check for terrain mesh or elevation data
        terrain_mesh = self._data.get('terrain_mesh')
        elevation_grid = self._data.get('google_maps', {}).get('elevation_grid', {})

        if not terrain_mesh and not elevation_grid:
            return 0.0  # No terrain data

        # Use mm fields if available, otherwise convert from ft
        if 'x_mm' in building_origin:
            origin_x_ft = building_origin['x_mm'] / 304.8
        else:
            origin_x_ft = building_origin.get('x_ft', 0)

        if 'z_mm' in building_origin:
            origin_z_ft = building_origin['z_mm'] / 304.8
        else:
            origin_z_ft = building_origin.get('z_ft', 0)

        # Check if C++ terrain generation will handle the lift
        # If so, skip Python lift to avoid double-lifting
        terrain_settings = self._data.get('terrain_generation_settings', {})
        if terrain_settings.get('use_cpp_generation', False):
            print(f"[Document] C++ terrain generation enabled - skipping Python building lift (C++ will handle it)")
            # Return the expected lift amount so it can be stored for floor generation
            lift_ft = self._sample_terrain_elevation_ft(origin_x_ft, origin_z_ft)
            return lift_ft * 304.8 if lift_ft > 0 else 0.0

        # Sample terrain elevation at building origin
        lift_ft = self._sample_terrain_elevation_ft(origin_x_ft, origin_z_ft)
        if lift_ft == 0:
            return 0.0  # No lift needed

        print(f"[Document] Lifting building by {lift_ft:.2f} ft to sit on terrain")

        MM_PER_FT = 304.8
        lift_mm = lift_ft * MM_PER_FT

        # Lift walls_batch (raw data)
        if 'walls_batch' in self._data:
            for wall in self._data['walls_batch']:
                if 'start' in wall and len(wall['start']) >= 3:
                    wall['start'][1] += lift_mm
                if 'end' in wall and len(wall['end']) >= 3:
                    wall['end'][1] += lift_mm

        # Lift parsed walls
        for wall in self._walls:
            wall.start = (wall.start[0], wall.start[1] + lift_mm, wall.start[2])
            wall.end = (wall.end[0], wall.end[1] + lift_mm, wall.end[2])

        # Lift doors (raw data)
        if 'doors' in self._data:
            for door in self._data['doors']:
                if 'position' in door and len(door['position']) >= 3:
                    door['position'][1] += lift_mm

        # Lift parsed doors
        for door in self._doors:
            # Doors don't store position directly, they're relative to walls
            pass

        # Lift windows (raw data)
        if 'windows' in self._data:
            for window in self._data['windows']:
                if 'position' in window and len(window['position']) >= 3:
                    window['position'][1] += lift_mm
                if 'sill_height' in window:
                    window['sill_height'] += lift_mm

        # Lift rooms (raw data and parsed)
        if 'rooms' in self._data and isinstance(self._data['rooms'], dict):
            for room_id, room in self._data['rooms'].items():
                if 'floor_z' in room:
                    room['floor_z'] += lift_mm
                if 'ceiling_z' in room:
                    room['ceiling_z'] += lift_mm

        for room in self._rooms.values():
            room.floor_z += lift_mm
            room.ceiling_z += lift_mm

        # Lift levels
        if 'levels' in self._data:
            for level in self._data['levels']:
                if 'elevation' in level:
                    level['elevation'] += lift_mm

        print(f"[Document] Building lifted by {lift_ft:.2f} ft ({lift_mm:.0f} mm)")
        return lift_mm

    def _sample_terrain_elevation_ft(self, x_ft: float, z_ft: float) -> float:
        """Sample terrain elevation at a given x_ft, z_ft position.

        Uses IDW interpolation from elevation_grid data.
        Returns elevation in feet, normalized so min_elevation is ~0.
        """
        elevation_grid = self._data.get('google_maps', {}).get('elevation_grid', {})
        if not elevation_grid:
            # Try terrain_mesh vertices
            terrain_mesh = self._data.get('terrain_mesh')
            if terrain_mesh and 'vertices' in terrain_mesh:
                return self._sample_mesh_elevation_ft(terrain_mesh, x_ft, z_ft)
            return 0.0

        elev_points = list(elevation_grid.values())
        if not elev_points:
            return 0.0

        # Get elevation range to compute offset
        elevations = [p.get('elevation_ft', 0) for p in elev_points]
        min_elev = min(elevations)

        # Elevation offset so min_elevation maps to ~0 (same as terrain.py)
        elevation_offset = -min_elev - 0.0328  # -0.0328 ft = -10 mm

        # Find nearest points and interpolate
        import math

        # Convert target position to lat/lng
        # Get bounds from google_maps
        google_maps = self._data.get('google_maps', {})
        boundary = google_maps.get('boundary', {})
        lat_min = boundary.get('lat_min', 0)
        lat_max = boundary.get('lat_max', 0)
        lng_min = boundary.get('lng_min', 0)
        lng_max = boundary.get('lng_max', 0)

        # Get property dimensions
        width_ft = self._data.get('property_width_ft', 100)
        depth_ft = self._data.get('property_depth_ft', 100)

        # Normalize position to [0, 1] within property
        frac_x = x_ft / width_ft if width_ft > 0 else 0.5
        frac_z = z_ft / depth_ft if depth_ft > 0 else 0.5

        # Map to lat/lng
        lat_range = lat_max - lat_min
        lng_range = lng_max - lng_min
        target_lat = lat_min + frac_z * lat_range
        target_lng = lng_min + frac_x * lng_range

        # IDW interpolation
        weights = []
        values = []

        for pt in elev_points:
            pt_lat = pt.get('lat', 0)
            pt_lng = pt.get('lng', 0)
            dist = math.sqrt((pt_lat - target_lat)**2 + (pt_lng - target_lng)**2)

            if dist < 0.000001:  # Very close, use this value directly
                return pt.get('elevation_ft', 0) + elevation_offset

            weight = 1.0 / (dist * dist)
            weights.append(weight)
            values.append(pt.get('elevation_ft', 0))

        if not weights:
            return 0.0

        # Weighted average
        weighted_sum = sum(w * v for w, v in zip(weights, values))
        total_weight = sum(weights)
        sampled_elev = weighted_sum / total_weight

        return sampled_elev + elevation_offset

    def _sample_mesh_elevation_ft(self, terrain_mesh: dict, x_ft: float, z_ft: float) -> float:
        """Sample elevation from terrain mesh vertices."""
        vertices = terrain_mesh.get('vertices', [])
        if not vertices:
            return 0.0

        import math

        # Convert ft to mm for comparison
        x_mm = x_ft * 304.8
        z_mm = z_ft * 304.8

        # Find nearest vertices
        best_dist = float('inf')
        best_elev_mm = 0

        for v in vertices:
            pos = v.get('position', [0, 0, 0])
            vx, vy, vz = pos[0], pos[1], pos[2]
            dist = math.sqrt((vx - x_mm)**2 + (vz - z_mm)**2)
            if dist < best_dist:
                best_dist = dist
                best_elev_mm = vy

        # Convert back to feet
        return best_elev_mm / 304.8

    def _validate_and_regenerate_terrain(self):
        """Check if terrain data is valid, regenerate if buggy."""
        print("[Document] _validate_and_regenerate_terrain called", flush=True)

        # Check if C++ terrain generation is requested (LiDAR data available)
        terrain_settings = self._data.get('terrain_generation_settings', {})
        use_cpp = terrain_settings.get('use_cpp_generation', False)
        google_maps = self._data.get('google_maps', {})
        elevation_grid = google_maps.get('elevation_grid', {})

        if use_cpp and elevation_grid:
            print(f"[Document] C++ terrain generation enabled ({len(elevation_grid)} elevation points)", flush=True)
            print("[Document] Skipping Python terrain - viewport will use C++", flush=True)
            # Remove any existing terrain_mesh so viewport uses C++ generation
            if 'terrain_mesh' in self._data:
                del self._data['terrain_mesh']
            return

        terrain_data = self._data.get('terrain_mesh')
        if not terrain_data:
            # No terrain and no C++ generation, use test terrain
            print("[Document] No terrain data, generating test terrain", flush=True)
            self._regenerate_terrain()
            return

        print(f"[Document] terrain_mesh keys: {list(terrain_data.keys())}", flush=True)
        vertices = terrain_data.get('vertices', [])
        if not vertices:
            print("[Document] Empty terrain vertices, regenerating", flush=True)
            self._regenerate_terrain()
            return
        print(f"[Document] terrain has {len(vertices)} vertices", flush=True)

        # Check if terrain needs regeneration:
        # 1. All Y values (elevation) are 0 (old buggy data)
        # 2. Missing 'version' field (pre-winding-fix terrain)
        # Position format: [x, y (elevation), z]

        # Force regeneration if no version field (old terrain with wrong winding order)
        if 'version' not in terrain_data:
            print(f"[Document] Old terrain format (no version), regenerating with correct winding", flush=True)
            self._regenerate_terrain()
            return

        y_values = set()
        for v in vertices[:min(20, len(vertices))]:  # Check first 20 vertices
            pos = v.get('position', [0, 0, 0])
            if len(pos) >= 3:
                y_values.add(round(pos[1], 1))  # pos[1] is Y (elevation)

        if len(y_values) == 1 and 0.0 in y_values:
            print(f"[Document] Detected buggy terrain (all elevations=0), regenerating", flush=True)
            self._regenerate_terrain()
        else:
            print(f"[Document] Loaded terrain mesh: {len(vertices)} vertices, {terrain_data.get('triangle_count', 0)} triangles")

    def _regenerate_terrain(self):
        """Regenerate terrain using test terrain generator."""
        print("[Document] _regenerate_terrain called", flush=True)
        try:
            test_terrain = generate_test_terrain(width_ft=100, depth_ft=100, grid_size=15)
            if test_terrain:
                terrain_dict = test_terrain.to_dict()
                self._data['terrain_mesh'] = terrain_dict
                print(f"[Document] Regenerated terrain: {len(test_terrain.vertices)} vertices, {len(test_terrain.indices)//3} triangles", flush=True)
                print(f"[Document] Terrain elevation range: {test_terrain.min_elevation:.1f} to {test_terrain.max_elevation:.1f} mm", flush=True)
                print(f"[Document] terrain_mesh stored with keys: {list(terrain_dict.keys())}", flush=True)
                # Print first vertex to verify format
                verts = terrain_dict.get('vertices', [])
                if verts:
                    print(f"[Document] First vertex: {verts[0]}", flush=True)
            else:
                print("[Document] generate_test_terrain returned None!", flush=True)
        except Exception as e:
            print(f"[Document] Could not regenerate terrain: {e}", flush=True)
            import traceback
            traceback.print_exc()

    def _auto_bind_walls_to_rooms(self):
        """
        Automatically bind walls to room edges based on geometric overlap.
        Only binds walls that don't already have a bound_room_id.
        """
        TOLERANCE = 100  # mm tolerance for matching

        for wall in self._walls:
            if wall.bound_room_id:
                continue  # Already bound

            wall_start = (wall.start[0], wall.start[2])
            wall_end = (wall.end[0], wall.end[2])

            # Check each room's edges
            for room_id, room in self._rooms.items():
                if not room.vertices or len(room.vertices) < 3:
                    continue

                num_verts = len(room.vertices)
                for edge_idx in range(num_verts):
                    # Room edge from vertex[i] to vertex[(i+1) % n]
                    v1 = room.vertices[edge_idx]
                    v2 = room.vertices[(edge_idx + 1) % num_verts]

                    # Check if wall matches this edge (in either direction)
                    dist_fwd = (self._point_dist(wall_start, v1) +
                               self._point_dist(wall_end, v2))
                    dist_rev = (self._point_dist(wall_start, v2) +
                               self._point_dist(wall_end, v1))

                    if dist_fwd < TOLERANCE * 2 or dist_rev < TOLERANCE * 2:
                        # Wall matches this room edge
                        wall.bound_room_id = room_id
                        wall.edge_index = edge_idx
                        wall.is_structural = True
                        break

                if wall.bound_room_id:
                    break  # Found a match, stop searching

    def _point_dist(self, p1, p2) -> float:
        """Calculate distance between two 2D points."""
        if isinstance(p1, (list, tuple)) and isinstance(p2, (list, tuple)):
            dx = p1[0] - p2[0]
            dy = p1[1] - p2[1]
            return (dx*dx + dy*dy) ** 0.5
        return float('inf')

    def snap_walls_to_connections(self, snap_threshold: float = 500.0) -> int:
        """
        Snap existing walls to room connection edges.

        For each connection with a shared_edge:
        1. Find walls that are close to this edge
        2. Snap their endpoints to align with the shared edge
        3. Update wall category based on connection_type
        4. Link the wall to the connection

        Returns number of walls snapped.
        """
        CONNECTION_TO_CATEGORY = {
            'wall': 'interior',
            'open': 'opening',  # No physical wall, just opening
            'wet_wall': 'wet_wall',
            'structural': 'structural',
            'mechanical': 'mechanical',
            'insulated': 'insulated',
            'undefined': 'interior',
        }

        snapped_count = 0

        for conn in self._room_connections:
            if not conn.shared_edge:
                continue

            edge_p1 = conn.shared_edge[0]  # [x, z]
            edge_p2 = conn.shared_edge[1]

            # Find the best matching wall for this connection edge
            best_wall = None
            best_distance = float('inf')

            for wall in self._walls:
                wall_start = (wall.start[0], wall.start[2])
                wall_end = (wall.end[0], wall.end[2])

                # Check distance from wall to connection edge
                # Using perpendicular distance from wall midpoint to edge
                wall_mid = ((wall_start[0] + wall_end[0]) / 2,
                           (wall_start[1] + wall_end[1]) / 2)

                dist = self._point_to_line_distance(wall_mid, edge_p1, edge_p2)

                # Also check if the wall overlaps with the edge
                if dist < snap_threshold:
                    # Check overlap along the edge direction
                    overlap = self._segments_overlap(wall_start, wall_end, edge_p1, edge_p2)
                    if overlap > 0.3:  # At least 30% overlap
                        if dist < best_distance:
                            best_distance = dist
                            best_wall = wall

            if best_wall:
                # Snap this wall to the connection edge
                self._snap_wall_to_edge(best_wall, edge_p1, edge_p2)

                # Update wall category based on connection type
                new_category = CONNECTION_TO_CATEGORY.get(conn.connection_type, 'interior')
                if new_category != 'opening':  # Don't set category for openings
                    best_wall.category = new_category

                # Link connection to wall
                conn.wall_id = str(best_wall.index)

                snapped_count += 1
                print(f"[WallSnap] Snapped wall {best_wall.index} to connection "
                      f"{conn.room_a_id} <-> {conn.room_b_id} ({conn.connection_type})")

        if snapped_count > 0:
            self._modified = True

        return snapped_count

    def _point_to_line_distance(self, point, line_p1, line_p2) -> float:
        """Calculate perpendicular distance from point to line segment."""
        px, py = point[0], point[1]
        x1, y1 = line_p1[0], line_p1[1]
        x2, y2 = line_p2[0], line_p2[1]

        # Line segment vector
        dx = x2 - x1
        dy = y2 - y1

        # Handle zero-length segment
        length_sq = dx * dx + dy * dy
        if length_sq < 1e-10:
            return self._point_dist(point, line_p1)

        # Project point onto line
        t = max(0, min(1, ((px - x1) * dx + (py - y1) * dy) / length_sq))

        # Closest point on segment
        closest_x = x1 + t * dx
        closest_y = y1 + t * dy

        return self._point_dist(point, (closest_x, closest_y))

    def _segments_overlap(self, seg1_p1, seg1_p2, seg2_p1, seg2_p2) -> float:
        """
        Calculate how much two line segments overlap (0-1).
        Projects both segments onto their average direction.
        """
        # Get direction vectors
        d1 = (seg1_p2[0] - seg1_p1[0], seg1_p2[1] - seg1_p1[1])
        d2 = (seg2_p2[0] - seg2_p1[0], seg2_p2[1] - seg2_p1[1])

        # Use the longer segment's direction
        len1_sq = d1[0]**2 + d1[1]**2
        len2_sq = d2[0]**2 + d2[1]**2

        if max(len1_sq, len2_sq) < 1e-10:
            return 0.0

        if len1_sq >= len2_sq:
            dir_vec = d1
            dir_len = len1_sq ** 0.5
        else:
            dir_vec = d2
            dir_len = len2_sq ** 0.5

        # Normalize
        dir_vec = (dir_vec[0] / dir_len, dir_vec[1] / dir_len)

        # Project all points onto this direction
        proj1_a = seg1_p1[0] * dir_vec[0] + seg1_p1[1] * dir_vec[1]
        proj1_b = seg1_p2[0] * dir_vec[0] + seg1_p2[1] * dir_vec[1]
        proj2_a = seg2_p1[0] * dir_vec[0] + seg2_p1[1] * dir_vec[1]
        proj2_b = seg2_p2[0] * dir_vec[0] + seg2_p2[1] * dir_vec[1]

        # Get ranges
        min1, max1 = min(proj1_a, proj1_b), max(proj1_a, proj1_b)
        min2, max2 = min(proj2_a, proj2_b), max(proj2_a, proj2_b)

        # Calculate overlap
        overlap_start = max(min1, min2)
        overlap_end = min(max1, max2)

        if overlap_end <= overlap_start:
            return 0.0

        overlap_length = overlap_end - overlap_start
        seg1_length = max1 - min1
        seg2_length = max2 - min2

        # Return overlap as fraction of shorter segment
        shorter_length = min(seg1_length, seg2_length)
        if shorter_length < 1e-10:
            return 0.0

        return min(1.0, overlap_length / shorter_length)

    def _snap_wall_to_edge(self, wall: Wall, edge_p1, edge_p2):
        """Snap a wall's endpoints to align with a connection edge."""
        wall_start = (wall.start[0], wall.start[2])
        wall_end = (wall.end[0], wall.end[2])

        # Determine which direction the wall should go
        # Check both orientations
        dist_fwd = (self._point_dist(wall_start, edge_p1) +
                   self._point_dist(wall_end, edge_p2))
        dist_rev = (self._point_dist(wall_start, edge_p2) +
                   self._point_dist(wall_end, edge_p1))

        if dist_fwd <= dist_rev:
            # Keep same direction
            new_start = edge_p1
            new_end = edge_p2
        else:
            # Reverse direction
            new_start = edge_p2
            new_end = edge_p1

        # Update wall coordinates (keeping Y/height the same)
        wall.start = (new_start[0], wall.start[1], new_start[1])
        wall.end = (new_end[0], wall.end[1], new_end[1])

    def generate_wall_from_connection(self, conn: 'RoomConnection', height: float = 2700) -> Optional[Wall]:
        """
        Generate a new wall from a connection if no matching wall exists.

        Returns the newly created wall, or None if connection has no shared_edge.
        """
        if not conn.shared_edge:
            return None

        if conn.connection_type == 'open':
            # Open connections don't need walls
            return None

        CONNECTION_TO_CATEGORY = {
            'wall': 'interior',
            'wet_wall': 'wet_wall',
            'structural': 'structural',
            'mechanical': 'mechanical',
            'insulated': 'insulated',
            'undefined': 'interior',
        }

        edge_p1 = conn.shared_edge[0]
        edge_p2 = conn.shared_edge[1]

        # Create new wall
        new_index = len(self._walls)
        new_wall = Wall(
            index=new_index,
            start=(edge_p1[0], 0, edge_p1[1]),  # x, y=0, z
            end=(edge_p2[0], 0, edge_p2[1]),
            height=height,
            category=CONNECTION_TO_CATEGORY.get(conn.connection_type, 'interior'),
            is_structural=True,
        )

        self._walls.append(new_wall)
        conn.wall_id = str(new_index)
        self._modified = True

        print(f"[WallGen] Created wall {new_index} for connection "
              f"{conn.room_a_id} <-> {conn.room_b_id} ({conn.connection_type})")

        return new_wall

    def sync_connections_to_walls(self, snap_threshold: float = 500.0):
        """
        Legacy method - redirects to new generate_walls_from_rooms.
        """
        return self.generate_walls_from_rooms()

    def _edge_key(self, p1, p2) -> tuple:
        """
        Create a canonical key for an edge (order-independent).
        Rounds coordinates to avoid floating point issues.
        """
        # Round to nearest mm
        p1_rounded = (round(p1[0]), round(p1[1]))
        p2_rounded = (round(p2[0]), round(p2[1]))
        # Return in consistent order
        if p1_rounded < p2_rounded:
            return (p1_rounded, p2_rounded)
        return (p2_rounded, p1_rounded)

    def _find_connection_for_edge(self, edge_p1, edge_p2, tolerance: float = 100.0):
        """
        Find a RoomConnection that matches this edge.
        Returns (connection, is_reversed) or (None, False).
        """
        for conn in self._room_connections:
            if not conn.shared_edge:
                continue

            conn_p1 = conn.shared_edge[0]
            conn_p2 = conn.shared_edge[1]

            # Check forward match
            dist_fwd = (self._point_dist(edge_p1, conn_p1) +
                       self._point_dist(edge_p2, conn_p2))
            if dist_fwd < tolerance * 2:
                return conn, False

            # Check reverse match
            dist_rev = (self._point_dist(edge_p1, conn_p2) +
                       self._point_dist(edge_p2, conn_p1))
            if dist_rev < tolerance * 2:
                return conn, True

        return None, False

    def generate_walls_from_rooms(self, wall_height: float = 2700.0):
        """
        Generate walls from room edges based on room relationships.

        Wall types derived from room relationships:
        - Exterior walls (structural): Room edges with NO adjacent room
        - Structural interior walls: User-marked 'structural' connections
        - Interior/partition walls: Regular 'wall' connections between rooms
        - Wet walls: 'wet_wall' connections (plumbing walls)
        - No walls: 'open' connections - open-plan spaces stay open

        Rules:
        - Shared edges only create one wall (avoid duplicates)
        - Preserves manually-added partition walls (bound_room_id empty)
        - Open connections between open-plan rooms create no wall

        Returns (exterior_count, interior_count, open_count).
        """
        # Map connection types to wall categories
        CONNECTION_TO_CATEGORY = {
            'wall': 'interior',
            'open': None,  # No wall for open connections
            'wet_wall': 'wet_wall',
            'structural': 'interior',  # Structural interior wall
            'mechanical': 'mechanical',
            'insulated': 'insulated',
            'undefined': 'interior',
        }

        print(f"[WallGen] Generating walls from {len(self._rooms)} rooms...")

        # Only preserve manually-added partition walls (not bound to rooms)
        # These are walls added at LOD 2 that don't correspond to room edges
        manual_walls = [w for w in self._walls if not w.bound_room_id]
        print(f"[WallGen] Preserving {len(manual_walls)} manual walls")

        # Track processed edges to avoid duplicates
        processed_edges = set()

        # New walls list starts with manual walls
        new_walls = list(manual_walls)
        wall_index = len(new_walls)

        exterior_count = 0
        interior_count = 0
        open_count = 0

        for room_id, room in self._rooms.items():
            if not room.vertices or len(room.vertices) < 3:
                continue

            num_verts = len(room.vertices)
            for edge_idx in range(num_verts):
                v1 = room.vertices[edge_idx]
                v2 = room.vertices[(edge_idx + 1) % num_verts]

                # Create edge key to check for duplicates
                edge_key = self._edge_key(v1, v2)
                if edge_key in processed_edges:
                    continue  # Already created wall for this edge

                processed_edges.add(edge_key)

                # Check if this edge has a connection to another room
                conn, is_reversed = self._find_connection_for_edge(v1, v2)

                if conn:
                    # Edge has a connection - use connection_type
                    category = CONNECTION_TO_CATEGORY.get(conn.connection_type, 'interior')

                    if category is None:
                        # 'open' connection - no wall
                        open_count += 1
                        continue

                    interior_count += 1
                else:
                    # No connection = exterior wall
                    category = 'exterior'
                    exterior_count += 1

                # Create the wall - all room-bound walls are structural
                wall = Wall(
                    index=wall_index,
                    start=(v1[0], 0, v1[1]),  # x, y=0, z
                    end=(v2[0], 0, v2[1]),
                    height=wall_height,
                    category=category,
                    is_structural=True,  # Room-bound walls are always structural
                    bound_room_id=room_id,
                    edge_index=edge_idx,
                )

                # Link connection to wall if applicable
                if conn:
                    conn.wall_id = str(wall_index)

                new_walls.append(wall)
                wall_index += 1

        # Replace walls list
        self._walls = new_walls
        self._modified = True

        print(f"[WallGen] Generated: {exterior_count} exterior, "
              f"{interior_count} interior, {open_count} open (no wall)")

        # Merge collinear exterior walls
        merged = self._merge_exterior_walls()
        if merged > 0:
            print(f"[WallGen] Merged {merged} exterior wall segments")
            exterior_count = sum(1 for w in self._walls if w.category == 'exterior')

        print(f"[WallGen] Total walls: {len(self._walls)}")

        self.document_changed.emit()
        return exterior_count, interior_count, open_count

    def generate_floors_from_rooms(self, thickness: float = 150.0):
        """
        Generate floor slabs from room polygons.

        Rooms connected by 'open' connections are merged into single floor slabs.
        This creates unified floors for open-plan areas (living/dining/kitchen).

        Returns number of floor slabs created.
        """
        print(f"[FloorGen] Generating floors from {len(self._rooms)} rooms...")

        # Clear existing floors
        self._floors.clear()

        if not self._rooms:
            return 0

        # Group rooms by 'open' connections using union-find
        room_ids = list(self._rooms.keys())
        parent = {rid: rid for rid in room_ids}

        def find(x):
            if parent[x] != x:
                parent[x] = find(parent[x])
            return parent[x]

        def union(x, y):
            px, py = find(x), find(y)
            if px != py:
                parent[px] = py

        # Union rooms connected by 'open' connections
        open_count = 0
        for conn in self._room_connections:
            if conn.connection_type == 'open':
                union(conn.room_a_id, conn.room_b_id)
                open_count += 1

        print(f"[FloorGen] Found {open_count} open connections")

        # Group rooms by their root parent
        groups = {}
        for rid in room_ids:
            root = find(rid)
            if root not in groups:
                groups[root] = []
            groups[root].append(rid)

        print(f"[FloorGen] Created {len(groups)} floor groups")

        # Generate floor for each group
        floor_index = 0
        for group_root, group_room_ids in groups.items():
            # Collect all vertices from rooms in this group
            all_vertices = []
            for rid in group_room_ids:
                room = self._rooms.get(rid)
                if room and room.vertices:
                    all_vertices.extend(room.vertices)

            if not all_vertices:
                continue

            # For merged floors, compute convex hull
            # For single rooms, use room vertices directly
            if len(group_room_ids) == 1:
                room = self._rooms[group_room_ids[0]]
                floor_vertices = [list(v) for v in room.vertices] if room.vertices else []
            else:
                # Compute convex hull of all vertices
                floor_vertices = self._convex_hull(all_vertices)

            if len(floor_vertices) < 3:
                continue

            # Generate floors at Y=0 - C++ will lift them to terrain height
            floor_elevation = 0

            floor = Floor(
                index=floor_index,
                vertices=floor_vertices,
                thickness=thickness,
                elevation=floor_elevation,
                room_ids=group_room_ids
            )
            self._floors.append(floor)
            floor_index += 1

            room_names = [self._rooms[rid].name for rid in group_room_ids]
            print(f"[FloorGen] Floor {floor_index}: {', '.join(room_names)} ({len(floor_vertices)} vertices, {floor.area:.1f} m²)")

        self._modified = True
        print(f"[FloorGen] Total floors: {len(self._floors)}")
        return len(self._floors)

    def _convex_hull(self, points: List[List[float]]) -> List[List[float]]:
        """
        Compute convex hull of 2D points using Graham scan.
        Returns vertices in counter-clockwise order.
        """
        if len(points) < 3:
            return points

        # Remove duplicates (within tolerance)
        unique = []
        seen = set()
        for p in points:
            key = (round(p[0] / 10) * 10, round(p[1] / 10) * 10)  # 10mm tolerance
            if key not in seen:
                seen.add(key)
                unique.append(p)

        if len(unique) < 3:
            return unique

        # Find bottom-most point (and leftmost if tie)
        start = min(unique, key=lambda p: (p[1], p[0]))

        def cross(o, a, b):
            return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

        def angle_key(p):
            import math
            dx = p[0] - start[0]
            dy = p[1] - start[1]
            return (math.atan2(dy, dx), dx * dx + dy * dy)

        # Sort by polar angle
        sorted_pts = sorted(unique, key=angle_key)

        # Build hull
        hull = []
        for p in sorted_pts:
            while len(hull) >= 2 and cross(hull[-2], hull[-1], p) <= 0:
                hull.pop()
            hull.append(p)

        return hull

    def generate_roof(self, roof_type: str = 'hip', pitch: float = 30.0,
                      wall_height: float = 2700.0, overhang: float = 300.0):
        """
        Generate roof over the building exterior.

        Args:
            roof_type: 'hip', 'gable', 'flat', 'shed'
            pitch: Roof pitch in degrees (for sloped roofs)
            wall_height: Height of walls (eave height)
            overhang: Eave overhang in mm

        Returns:
            Number of roof sections created.
        """
        import math

        print(f"[RoofGen] Generating {roof_type} roof (pitch={pitch}°)...")

        # Clear existing roofs
        self._roofs.clear()

        # Get building exterior boundary from exterior walls
        exterior_points = []
        for wall in self._walls:
            if wall.category == 'exterior':
                exterior_points.append([wall.start[0], wall.start[2]])
                exterior_points.append([wall.end[0], wall.end[2]])

        if not exterior_points:
            # Fallback: use all room vertices
            for room in self._rooms.values():
                if room.vertices:
                    exterior_points.extend(room.vertices)

        if len(exterior_points) < 3:
            print("[RoofGen] Not enough points for roof")
            return 0

        # Get convex hull of exterior
        base_vertices = self._convex_hull(exterior_points)

        # Add overhang to base
        base_with_overhang = self._offset_polygon(base_vertices, overhang)

        # Calculate bounding box to determine ridge direction
        xs = [p[0] for p in base_with_overhang]
        zs = [p[1] for p in base_with_overhang]
        min_x, max_x = min(xs), max(xs)
        min_z, max_z = min(zs), max(zs)
        width = max_x - min_x
        depth = max_z - min_z
        center_x = (min_x + max_x) / 2
        center_z = (min_z + max_z) / 2

        # Ridge runs along the longer dimension
        if width >= depth:
            # Ridge runs along X axis
            ridge_dir = 'x'
            span = depth  # Distance from ridge to eave
        else:
            # Ridge runs along Z axis
            ridge_dir = 'z'
            span = width

        # Calculate ridge height based on pitch
        # For hip roof, the slope goes from eave to ridge
        pitch_rad = math.radians(pitch)
        half_span = span / 2
        ridge_rise = half_span * math.tan(pitch_rad)
        ridge_height = wall_height + ridge_rise

        print(f"[RoofGen] Building: {width:.0f}x{depth:.0f}mm, ridge height: {ridge_height:.0f}mm")

        if roof_type == 'flat':
            # Flat roof - just a slab at wall height
            roof = Roof(
                index=0,
                roof_type='flat',
                base_vertices=base_with_overhang,
                ridge_vertices=[],  # No ridge for flat roof
                base_height=wall_height,
                ridge_height=wall_height + 100,  # Slight pitch for drainage
                pitch=0,
                overhang=overhang,
            )
            self._roofs.append(roof)

        elif roof_type == 'hip':
            # Hip roof - ridge in center, 4 sloping faces
            # Calculate ridge endpoints (inset from building ends)
            hip_inset = half_span  # Hip slope from corners

            if ridge_dir == 'x':
                # Ridge along X
                ridge_start_x = min_x + hip_inset
                ridge_end_x = max_x - hip_inset
                if ridge_start_x >= ridge_end_x:
                    # Building too square - ridge becomes a point (pyramid)
                    ridge_vertices = [[center_x, center_z]]
                else:
                    ridge_vertices = [
                        [ridge_start_x, center_z],
                        [ridge_end_x, center_z]
                    ]
            else:
                # Ridge along Z
                ridge_start_z = min_z + hip_inset
                ridge_end_z = max_z - hip_inset
                if ridge_start_z >= ridge_end_z:
                    # Building too square - ridge becomes a point
                    ridge_vertices = [[center_x, center_z]]
                else:
                    ridge_vertices = [
                        [center_x, ridge_start_z],
                        [center_x, ridge_end_z]
                    ]

            roof = Roof(
                index=0,
                roof_type='hip',
                base_vertices=base_with_overhang,
                ridge_vertices=ridge_vertices,
                base_height=wall_height,
                ridge_height=ridge_height,
                pitch=pitch,
                overhang=overhang,
            )
            self._roofs.append(roof)

        elif roof_type == 'gable':
            # Gable roof - ridge end to end, 2 sloping faces + 2 vertical gable ends
            if ridge_dir == 'x':
                ridge_vertices = [
                    [min_x - overhang, center_z],
                    [max_x + overhang, center_z]
                ]
            else:
                ridge_vertices = [
                    [center_x, min_z - overhang],
                    [center_x, max_z + overhang]
                ]

            roof = Roof(
                index=0,
                roof_type='gable',
                base_vertices=base_with_overhang,
                ridge_vertices=ridge_vertices,
                base_height=wall_height,
                ridge_height=ridge_height,
                pitch=pitch,
                overhang=overhang,
            )
            self._roofs.append(roof)

        elif roof_type == 'shed':
            # Shed roof - single slope
            # High edge on one side, low on opposite
            if ridge_dir == 'x':
                ridge_vertices = [
                    [min_x - overhang, max_z],
                    [max_x + overhang, max_z]
                ]
            else:
                ridge_vertices = [
                    [max_x, min_z - overhang],
                    [max_x, max_z + overhang]
                ]

            roof = Roof(
                index=0,
                roof_type='shed',
                base_vertices=base_with_overhang,
                ridge_vertices=ridge_vertices,
                base_height=wall_height,
                ridge_height=ridge_height,
                pitch=pitch,
                overhang=overhang,
            )
            self._roofs.append(roof)

        self._modified = True
        print(f"[RoofGen] Created {len(self._roofs)} roof section(s)")
        return len(self._roofs)

    def _generate_roof_surfaces(self, roof: Roof) -> List[dict]:
        """
        Generate 3D roof surface polygons for rendering.

        For hip roof: 4 trapezoidal/triangular faces
        For gable roof: 2 rectangular faces + 2 triangular gable ends
        For flat roof: 1 rectangular face
        """
        surfaces = []
        base = roof.base_vertices
        ridge = roof.ridge_vertices
        base_y = roof.base_height
        ridge_y = roof.ridge_height

        if not base or len(base) < 3:
            return surfaces

        # Get bounding box
        xs = [p[0] for p in base]
        zs = [p[1] for p in base]
        min_x, max_x = min(xs), max(xs)
        min_z, max_z = min(zs), max(zs)

        if roof.roof_type == 'flat':
            # Single flat surface
            surfaces.append({
                'id': 'flat_top',
                'name': 'top',
                'pitch': 0,
                'vertices': [
                    [min_x, ridge_y, min_z],
                    [max_x, ridge_y, min_z],
                    [max_x, ridge_y, max_z],
                    [min_x, ridge_y, max_z]
                ]
            })

        elif roof.roof_type == 'hip':
            if len(ridge) == 1:
                # Pyramid roof (square building) - 4 triangular faces
                apex = [ridge[0][0], ridge_y, ridge[0][1]]
                corners = [
                    [min_x, base_y, min_z],
                    [max_x, base_y, min_z],
                    [max_x, base_y, max_z],
                    [min_x, base_y, max_z]
                ]
                names = ['south', 'east', 'north', 'west']
                for i in range(4):
                    surfaces.append({
                        'id': f'hip_{names[i]}',
                        'name': names[i],
                        'pitch': roof.pitch,
                        'vertices': [corners[i], corners[(i+1) % 4], apex]
                    })
            elif len(ridge) >= 2:
                # Standard hip roof with ridge line - 4 faces (2 trapezoids, 2 triangles)
                ridge_start = [ridge[0][0], ridge_y, ridge[0][1]]
                ridge_end = [ridge[1][0], ridge_y, ridge[1][1]]

                # Determine if ridge runs along X or Z
                if abs(ridge[1][0] - ridge[0][0]) > abs(ridge[1][1] - ridge[0][1]):
                    # Ridge along X axis
                    # South face (trapezoid)
                    surfaces.append({
                        'id': 'hip_south',
                        'name': 'south',
                        'pitch': roof.pitch,
                        'vertices': [
                            [min_x, base_y, min_z],
                            [max_x, base_y, min_z],
                            ridge_end,
                            ridge_start
                        ]
                    })
                    # North face (trapezoid)
                    surfaces.append({
                        'id': 'hip_north',
                        'name': 'north',
                        'pitch': roof.pitch,
                        'vertices': [
                            [max_x, base_y, max_z],
                            [min_x, base_y, max_z],
                            ridge_start,
                            ridge_end
                        ]
                    })
                    # West face (triangle)
                    surfaces.append({
                        'id': 'hip_west',
                        'name': 'west',
                        'pitch': roof.pitch,
                        'vertices': [
                            [min_x, base_y, max_z],
                            [min_x, base_y, min_z],
                            ridge_start
                        ]
                    })
                    # East face (triangle)
                    surfaces.append({
                        'id': 'hip_east',
                        'name': 'east',
                        'pitch': roof.pitch,
                        'vertices': [
                            [max_x, base_y, min_z],
                            [max_x, base_y, max_z],
                            ridge_end
                        ]
                    })
                else:
                    # Ridge along Z axis
                    # West face (trapezoid)
                    surfaces.append({
                        'id': 'hip_west',
                        'name': 'west',
                        'pitch': roof.pitch,
                        'vertices': [
                            [min_x, base_y, max_z],
                            [min_x, base_y, min_z],
                            ridge_start,
                            ridge_end
                        ]
                    })
                    # East face (trapezoid)
                    surfaces.append({
                        'id': 'hip_east',
                        'name': 'east',
                        'pitch': roof.pitch,
                        'vertices': [
                            [max_x, base_y, min_z],
                            [max_x, base_y, max_z],
                            ridge_end,
                            ridge_start
                        ]
                    })
                    # South face (triangle)
                    surfaces.append({
                        'id': 'hip_south',
                        'name': 'south',
                        'pitch': roof.pitch,
                        'vertices': [
                            [min_x, base_y, min_z],
                            [max_x, base_y, min_z],
                            ridge_start
                        ]
                    })
                    # North face (triangle)
                    surfaces.append({
                        'id': 'hip_north',
                        'name': 'north',
                        'pitch': roof.pitch,
                        'vertices': [
                            [max_x, base_y, max_z],
                            [min_x, base_y, max_z],
                            ridge_end
                        ]
                    })

        elif roof.roof_type == 'gable':
            if len(ridge) >= 2:
                ridge_start = [ridge[0][0], ridge_y, ridge[0][1]]
                ridge_end = [ridge[1][0], ridge_y, ridge[1][1]]

                # Determine ridge direction
                if abs(ridge[1][0] - ridge[0][0]) > abs(ridge[1][1] - ridge[0][1]):
                    # Ridge along X - gable ends on East/West
                    # South slope
                    surfaces.append({
                        'id': 'gable_south',
                        'name': 'south',
                        'pitch': roof.pitch,
                        'vertices': [
                            [min_x, base_y, min_z],
                            [max_x, base_y, min_z],
                            ridge_end,
                            ridge_start
                        ]
                    })
                    # North slope
                    surfaces.append({
                        'id': 'gable_north',
                        'name': 'north',
                        'pitch': roof.pitch,
                        'vertices': [
                            [max_x, base_y, max_z],
                            [min_x, base_y, max_z],
                            ridge_start,
                            ridge_end
                        ]
                    })
                else:
                    # Ridge along Z - gable ends on North/South
                    # West slope
                    surfaces.append({
                        'id': 'gable_west',
                        'name': 'west',
                        'pitch': roof.pitch,
                        'vertices': [
                            [min_x, base_y, max_z],
                            [min_x, base_y, min_z],
                            ridge_start,
                            ridge_end
                        ]
                    })
                    # East slope
                    surfaces.append({
                        'id': 'gable_east',
                        'name': 'east',
                        'pitch': roof.pitch,
                        'vertices': [
                            [max_x, base_y, min_z],
                            [max_x, base_y, max_z],
                            ridge_end,
                            ridge_start
                        ]
                    })

        return surfaces

    def _offset_polygon(self, vertices: List[List[float]], offset: float) -> List[List[float]]:
        """
        Offset polygon outward by a distance (for eave overhang).
        Simple implementation using vertex normals.
        """
        if len(vertices) < 3:
            return vertices

        import math

        n = len(vertices)
        result = []

        for i in range(n):
            # Get adjacent vertices
            prev_v = vertices[(i - 1) % n]
            curr_v = vertices[i]
            next_v = vertices[(i + 1) % n]

            # Edge vectors
            e1 = [curr_v[0] - prev_v[0], curr_v[1] - prev_v[1]]
            e2 = [next_v[0] - curr_v[0], next_v[1] - curr_v[1]]

            # Normalize
            len1 = math.sqrt(e1[0]**2 + e1[1]**2)
            len2 = math.sqrt(e2[0]**2 + e2[1]**2)
            if len1 < 1 or len2 < 1:
                result.append(curr_v)
                continue

            e1 = [e1[0]/len1, e1[1]/len1]
            e2 = [e2[0]/len2, e2[1]/len2]

            # Outward normals (rotate 90° clockwise for CCW polygon)
            n1 = [e1[1], -e1[0]]
            n2 = [e2[1], -e2[0]]

            # Average normal (bisector)
            avg_n = [n1[0] + n2[0], n1[1] + n2[1]]
            avg_len = math.sqrt(avg_n[0]**2 + avg_n[1]**2)
            if avg_len < 0.001:
                avg_n = n1
            else:
                avg_n = [avg_n[0]/avg_len, avg_n[1]/avg_len]

            # Offset vertex
            # Adjust offset for corner angle
            dot = n1[0]*n2[0] + n1[1]*n2[1]
            corner_factor = 1.0 / max(0.5, (1 + dot) / 2)  # Miter-like adjustment
            actual_offset = offset * min(corner_factor, 2.0)

            new_v = [
                curr_v[0] + avg_n[0] * actual_offset,
                curr_v[1] + avg_n[1] * actual_offset
            ]
            result.append(new_v)

        return result

    def _parse_furniture(self):
        """Parse furniture placements from data."""
        # Parse furniture
        if _FURNITURE_AVAILABLE:
            for f in self._data.get('furniture', []):
                placement = FurniturePlacement.from_dict(f)
                self._furniture.append(placement)

    def _merge_exterior_walls(self, tolerance: float = 100.0) -> int:
        """
        Merge collinear adjacent exterior walls into longer walls.

        Finds exterior walls that:
        1. Share an endpoint (within tolerance)
        2. Are collinear (on the same line)

        Merges them into single longer walls.
        Returns number of walls removed by merging.
        """
        exterior_walls = [w for w in self._walls if w.category == 'exterior']
        if len(exterior_walls) < 2:
            return 0

        def are_collinear(w1, w2, tol=tolerance):
            """Check if two walls are collinear (same line direction)."""
            # Get wall directions in XZ plane
            dx1 = w1.end[0] - w1.start[0]
            dz1 = w1.end[2] - w1.start[2]
            dx2 = w2.end[0] - w2.start[0]
            dz2 = w2.end[2] - w2.start[2]

            # Check if both are vertical (along Z)
            if abs(dx1) < tol and abs(dx2) < tol:
                # Both vertical - check X position
                return abs(w1.start[0] - w2.start[0]) < tol

            # Check if both are horizontal (along X)
            if abs(dz1) < tol and abs(dz2) < tol:
                # Both horizontal - check Z position
                return abs(w1.start[2] - w2.start[2]) < tol

            return False

        def share_endpoint(w1, w2, tol=tolerance):
            """Check if walls share an endpoint. Returns (w1_end, w2_end) or None."""
            pts1 = [(w1.start[0], w1.start[2]), (w1.end[0], w1.end[2])]
            pts2 = [(w2.start[0], w2.start[2]), (w2.end[0], w2.end[2])]

            for i, p1 in enumerate(pts1):
                for j, p2 in enumerate(pts2):
                    if abs(p1[0] - p2[0]) < tol and abs(p1[1] - p2[1]) < tol:
                        return (i, j)  # (w1 endpoint index, w2 endpoint index)
            return None

        merged_count = 0
        walls_to_remove = set()

        # Build adjacency and try to merge
        for i, w1 in enumerate(exterior_walls):
            if i in walls_to_remove:
                continue

            for j, w2 in enumerate(exterior_walls):
                if j <= i or j in walls_to_remove:
                    continue

                if not are_collinear(w1, w2):
                    continue

                shared = share_endpoint(w1, w2)
                if not shared:
                    continue

                # Merge w2 into w1
                w1_end_idx, w2_end_idx = shared

                # Determine new start/end based on which endpoints are shared
                if w1_end_idx == 0:  # w1.start is shared
                    if w2_end_idx == 0:  # w2.start is shared
                        # w1: [shared] -> end1, w2: [shared] -> end2
                        # Result: end2 -> end1
                        w1.start = w2.end
                    else:  # w2.end is shared
                        # w1: [shared] -> end1, w2: start2 -> [shared]
                        # Result: start2 -> end1
                        w1.start = w2.start
                else:  # w1.end is shared
                    if w2_end_idx == 0:  # w2.start is shared
                        # w1: start1 -> [shared], w2: [shared] -> end2
                        # Result: start1 -> end2
                        w1.end = w2.end
                    else:  # w2.end is shared
                        # w1: start1 -> [shared], w2: start2 -> [shared]
                        # Result: start1 -> start2
                        w1.end = w2.start

                walls_to_remove.add(j)
                merged_count += 1

        # Remove merged walls
        if walls_to_remove:
            exterior_indices = [self._walls.index(w) for w in exterior_walls]
            indices_to_remove = {exterior_indices[i] for i in walls_to_remove}
            self._walls = [w for i, w in enumerate(self._walls) if i not in indices_to_remove]

            # Re-index walls
            for i, wall in enumerate(self._walls):
                wall.index = i

        return merged_count

    def _update_data(self):
        """Update JSON data from parsed objects, preserving original fields."""
        # Update walls - preserve original data, only update modified fields
        original_walls = self._data.get('walls_batch', [])
        walls_batch = []
        for i, wall in enumerate(self._walls):
            # Start with original data if available (preserves extra fields)
            if i < len(original_walls):
                wall_data = copy.copy(original_walls[i])
            else:
                wall_data = {}
            # Update fields from our Wall dataclass
            wall_data['start'] = list(wall.start)
            wall_data['end'] = list(wall.end)
            wall_data['height'] = wall.height
            wall_data['category'] = wall.category
            wall_data['wall_type'] = wall.wall_type
            wall_data['material_override'] = wall.material_override
            # Structural binding fields
            wall_data['is_structural'] = wall.is_structural
            wall_data['bound_room_id'] = wall.bound_room_id
            wall_data['edge_index'] = wall.edge_index
            # Constraint fields
            wall_data['is_pinned'] = wall.is_pinned
            wall_data['locked_properties'] = wall.locked_properties
            walls_batch.append(wall_data)
        self._data['walls_batch'] = walls_batch

        # Update doors - preserve original data
        original_doors = self._data.get('doors', [])
        doors = []
        for i, door in enumerate(self._doors):
            if i < len(original_doors):
                door_data = copy.copy(original_doors[i])
            else:
                door_data = {}
            door_data['wall_index'] = door.wall_index
            door_data['offset'] = door.offset
            door_data['width'] = door.width
            door_data['height'] = door.height
            door_data['type'] = door.door_type
            door_data['swing'] = door.swing
            # Constraint fields
            door_data['is_pinned'] = door.is_pinned
            door_data['locked_properties'] = door.locked_properties
            doors.append(door_data)
        self._data['doors'] = doors

        # Update windows - preserve original data
        original_windows = self._data.get('windows', [])
        windows = []
        for i, window in enumerate(self._windows):
            if i < len(original_windows):
                window_data = copy.copy(original_windows[i])
            else:
                window_data = {}
            window_data['wall_index'] = window.wall_index
            window_data['offset'] = window.offset
            window_data['width'] = window.width
            window_data['height'] = window.height
            window_data['sill_height'] = window.sill_height
            # Constraint fields
            window_data['is_pinned'] = window.is_pinned
            window_data['locked_properties'] = window.locked_properties
            windows.append(window_data)
        self._data['windows'] = windows

        # Update floors - convert polygon to bounding box for kernel
        floors_batch = []
        for floor in self._floors:
            if floor.vertices:
                xs = [v[0] for v in floor.vertices]
                zs = [v[1] for v in floor.vertices]
                floor_data = {
                    'start': [min(xs), floor.elevation, min(zs)],
                    'end': [max(xs), floor.elevation, max(zs)],
                    'thickness': floor.thickness,
                    'room': floor.room_ids[0] if floor.room_ids else '',
                    'vertices': floor.vertices,  # Keep polygon for 2D view
                    'material': floor.material
                }
                print(f"[Floor] start={floor_data['start']}, end={floor_data['end']}, thickness={floor.thickness}")
                floors_batch.append(floor_data)
        self._data['floors_batch'] = floors_batch
        print(f"[Floor] Generated {len(floors_batch)} floors in floors_batch")

        # Update roofs - generate surface polygons for kernel
        roofs = []
        for roof in self._roofs:
            roof_data = {
                'id': f'roof_{roof.index}',
                'type': roof.roof_type,
                'pitch': roof.pitch,
                'overhang': roof.overhang,
                'ridge_height': roof.ridge_height - roof.base_height,
                'base_height': roof.base_height,
                'base_vertices': roof.base_vertices,
                'ridge_vertices': roof.ridge_vertices,
                'surfaces': self._generate_roof_surfaces(roof),
                'material': roof.material
            }
            roofs.append(roof_data)
        self._data['roofs'] = roofs

        # Update rooms
        rooms = {}
        for room_id, room in self._rooms.items():
            room_data = {
                'name': room.name,
                'room_type': room.room_type,
                'bounds': room.bounds,
                'area': room.area,
                'center': room.center,
                # Constraint fields
                'is_pinned': room.is_pinned,
                'locked_properties': room.locked_properties
            }
            # Include vertices if present
            if room.vertices:
                room_data['vertices'] = room.vertices
            rooms[room_id] = room_data
        self._data['rooms'] = rooms

        # Update room connections
        connections = []
        for conn in self._room_connections:
            conn_data = {
                'room_a_id': conn.room_a_id,
                'room_b_id': conn.room_b_id,
                'connection_type': conn.connection_type,
                'shared_edge': conn.shared_edge,
                'wall_id': conn.wall_id
            }
            connections.append(conn_data)
        self._data['room_connections'] = connections

    def get_data(self) -> dict:
        """Get current document data as JSON-serializable dict.

        Syncs internal state to _data before returning.
        Use this instead of accessing _data directly.
        """
        self._update_data()
        return self._data

    # =========================================================================
    # Element Modification
    # =========================================================================

    def set_modified(self, modified: bool = True):
        """Set modified flag."""
        self._modified = modified
        if modified:
            event_bus.document_modified.emit()

    def _sync_room_from_wall(self, wall: Wall):
        """
        Update room vertices when a structural wall bound to it moves.

        If wall is structural and bound to a room, update that room's
        polygon edge to match the wall's new position.
        """
        if not wall.is_structural or not wall.bound_room_id:
            return

        room = self._rooms.get(wall.bound_room_id)
        if not room or not room.vertices or wall.edge_index < 0:
            return

        # Update the room polygon edge
        num_verts = len(room.vertices)
        if wall.edge_index >= num_verts:
            return

        # Edge goes from vertex[edge_index] to vertex[(edge_index+1) % n]
        start_idx = wall.edge_index
        end_idx = (wall.edge_index + 1) % num_verts

        # Update vertices - wall endpoints become room edge endpoints
        room.vertices[start_idx] = [wall.start[0], wall.start[2]]
        room.vertices[end_idx] = [wall.end[0], wall.end[2]]

        # Update room center
        xs = [v[0] for v in room.vertices]
        zs = [v[1] for v in room.vertices]
        room.center = {'x': sum(xs) / len(xs), 'z': sum(zs) / len(zs)}

        # Update room area (shoelace formula) - convert mm² to m²
        area = 0.0
        for i in range(num_verts):
            j = (i + 1) % num_verts
            area += room.vertices[i][0] * room.vertices[j][1]
            area -= room.vertices[j][0] * room.vertices[i][1]
        room.area = abs(area) / 2.0 / 1_000_000.0  # mm² to m²

    def move_room_walls(self, room_id: str, dx: float, dy: float,
                        from_drag_start: bool = False,
                        drag_start_vertices: list = None):
        """
        Move all walls bound to a room by the given delta.

        Args:
            room_id: The room being moved
            dx, dy: Movement delta
            from_drag_start: If True, calculate wall positions from drag_start_vertices
            drag_start_vertices: Original room vertices at drag start
        """
        room = self._rooms.get(room_id)
        if not room or not room.vertices:
            return

        # Find all walls bound to this room
        for wall in self._walls:
            if wall.bound_room_id != room_id or wall.edge_index < 0:
                continue

            num_verts = len(room.vertices)
            if wall.edge_index >= num_verts:
                continue

            # Get the room edge vertices (already updated by the caller)
            v1_idx = wall.edge_index
            v2_idx = (wall.edge_index + 1) % num_verts

            # Update wall endpoints from room vertices
            new_start = room.vertices[v1_idx]
            new_end = room.vertices[v2_idx]

            # Keep Y (height) the same
            wall.start = (new_start[0], wall.start[1], new_start[1])
            wall.end = (new_end[0], wall.end[1], new_end[1])

            # Emit element modified for wall items to update
            event_bus.element_modified.emit('wall', str(wall.index), {
                'start': wall.start,
                'end': wall.end
            })

    def modify_wall(self, index: int, **changes):
        """
        Modify a wall's properties (direct, no undo).

        Args:
            index: Wall index
            **changes: Properties to change (start, end, height, category, etc.)
        """
        if 0 <= index < len(self._walls):
            wall = self._walls[index]

            for key, value in changes.items():
                if hasattr(wall, key):
                    setattr(wall, key, value)

            self.set_modified(True)
            self.element_modified.emit('wall', str(index))
            event_bus.element_modified.emit('wall', str(index), changes)
            # Note: Don't emit document_changed here - this is called during drag
            # and would trigger full refresh, destroying grips mid-drag.
            # document_changed is emitted by undoable versions at end of operation.

    def modify_wall_undoable(self, index: int, **changes):
        """
        Modify a wall's properties with undo support.

        Args:
            index: Wall index
            **changes: Properties to change
        """
        from core.commands import ModifyWallCommand

        if 0 <= index < len(self._walls):
            wall = self._walls[index]

            # Capture old values
            old_values = {}
            for key in changes:
                if hasattr(wall, key):
                    old_values[key] = getattr(wall, key)

            # Apply changes directly
            for key, value in changes.items():
                if hasattr(wall, key):
                    setattr(wall, key, value)

            self.set_modified(True)
            self.element_modified.emit('wall', str(index))
            event_bus.element_modified.emit('wall', str(index), changes)
            self.document_changed.emit()

            # Push command to undo stack
            cmd = ModifyWallCommand(self, index, old_values, changes)
            self._undo_stack.push(cmd)

    def move_wall_undoable(self, index: int, grip_type: str,
                           old_start: tuple, old_end: tuple,
                           new_start: tuple, new_end: tuple):
        """
        Move a wall with undo support (merges consecutive moves).
        """
        from core.commands import MoveWallCommand

        if 0 <= index < len(self._walls):
            wall = self._walls[index]
            wall.start = new_start
            wall.end = new_end

            self.set_modified(True)
            self.element_modified.emit('wall', str(index))
            event_bus.element_modified.emit('wall', str(index),
                                           {'start': new_start, 'end': new_end})
            self.document_changed.emit()

            # Push command (will merge with previous if same wall)
            cmd = MoveWallCommand(self, index, grip_type,
                                  old_start, old_end, new_start, new_end)
            self._undo_stack.push(cmd)

    def add_wall_undoable(self, wall_data: Dict) -> int:
        """Add a wall with undo support. Returns wall index."""
        from core.commands import AddWallCommand

        cmd = AddWallCommand(self, wall_data)
        self._undo_stack.push(cmd)
        return len(self._walls) - 1

    def delete_wall_undoable(self, index: int):
        """Delete a wall with undo support."""
        from core.commands import DeleteWallCommand

        if 0 <= index < len(self._walls):
            cmd = DeleteWallCommand(self, index)
            self._undo_stack.push(cmd)

    def add_door_undoable(self, door_data: Dict) -> int:
        """Add a door with undo support. Returns door index."""
        from core.commands import AddDoorCommand

        cmd = AddDoorCommand(self, door_data)
        self._undo_stack.push(cmd)
        return len(self._doors) - 1

    def add_window_undoable(self, window_data: Dict) -> int:
        """Add a window with undo support. Returns window index."""
        from core.commands import AddWindowCommand

        cmd = AddWindowCommand(self, window_data)
        self._undo_stack.push(cmd)
        return len(self._windows) - 1

    def add_room_undoable(self, room_data: Dict) -> str:
        """Add a room with undo support. Returns room ID."""
        from core.commands import AddRoomCommand

        cmd = AddRoomCommand(self, room_data)
        self._undo_stack.push(cmd)
        return cmd.room_id

    def delete_wall_undoable(self, wall_index: int):
        """Delete a wall with undo support."""
        from core.commands import DeleteWallCommand

        if 0 <= wall_index < len(self._walls):
            cmd = DeleteWallCommand(self, wall_index)
            self._undo_stack.push(cmd)

    def delete_door_undoable(self, door_index: int):
        """Delete a door with undo support."""
        from core.commands import DeleteDoorCommand

        if 0 <= door_index < len(self._doors):
            cmd = DeleteDoorCommand(self, door_index)
            self._undo_stack.push(cmd)

    def delete_window_undoable(self, window_index: int):
        """Delete a window with undo support."""
        from core.commands import DeleteWindowCommand

        if 0 <= window_index < len(self._windows):
            cmd = DeleteWindowCommand(self, window_index)
            self._undo_stack.push(cmd)

    def delete_room_undoable(self, room_id: str):
        """Delete a room with undo support."""
        from core.commands import DeleteRoomCommand

        if room_id in self._rooms:
            cmd = DeleteRoomCommand(self, room_id)
            self._undo_stack.push(cmd)

    def modify_door(self, index: int, **changes):
        """Modify a door's properties (direct, no undo)."""
        if 0 <= index < len(self._doors):
            door = self._doors[index]

            for key, value in changes.items():
                if hasattr(door, key):
                    setattr(door, key, value)

            self.set_modified(True)
            self.element_modified.emit('door', str(index))

    def modify_door_undoable(self, index: int, **changes):
        """Modify a door's properties with undo support."""
        from core.commands import ModifyDoorCommand

        if 0 <= index < len(self._doors):
            door = self._doors[index]

            old_values = {}
            for key in changes:
                if hasattr(door, key):
                    old_values[key] = getattr(door, key)

            for key, value in changes.items():
                if hasattr(door, key):
                    setattr(door, key, value)

            self.set_modified(True)
            self.element_modified.emit('door', str(index))

            cmd = ModifyDoorCommand(self, index, old_values, changes)
            self._undo_stack.push(cmd)

    def modify_window(self, index: int, **changes):
        """Modify a window's properties (direct, no undo)."""
        if 0 <= index < len(self._windows):
            window = self._windows[index]

            for key, value in changes.items():
                if hasattr(window, key):
                    setattr(window, key, value)

            self.set_modified(True)
            self.element_modified.emit('window', str(index))

    def modify_window_undoable(self, index: int, **changes):
        """Modify a window's properties with undo support."""
        from core.commands import ModifyWindowCommand

        if 0 <= index < len(self._windows):
            window = self._windows[index]

            old_values = {}
            for key in changes:
                if hasattr(window, key):
                    old_values[key] = getattr(window, key)

            for key, value in changes.items():
                if hasattr(window, key):
                    setattr(window, key, value)

            self.set_modified(True)
            self.element_modified.emit('window', str(index))

            cmd = ModifyWindowCommand(self, index, old_values, changes)
            self._undo_stack.push(cmd)

    def get_wall_types(self) -> List[Dict]:
        """Get available wall types."""
        return self._data.get('wall_types', [])

    def get_project_info(self) -> Dict:
        """Get project information."""
        qbd = self._data.get('qbd_answers', {})
        return {
            'name': qbd.get('description', 'Untitled Project'),
            'building_type': self._data.get('building_type', 'residential'),
            'width': self.building_width,
            'depth': self.building_depth,
            'sqft': self._data.get('sqft', 0)
        }

    def get_walls_at_point(self, x: float, z: float, tolerance: float = 50) -> List[Tuple[int, str]]:
        """
        Find walls that have an endpoint near the given point.

        Args:
            x: X coordinate
            z: Z coordinate (plan view Y)
            tolerance: Distance tolerance for matching

        Returns:
            List of (wall_index, endpoint) tuples where endpoint is 'start' or 'end'
        """
        import math
        result = []

        for wall in self._walls:
            # Check start
            sx, sz = wall.start[0], wall.start[2]
            dist_start = math.sqrt((sx - x) ** 2 + (sz - z) ** 2)
            if dist_start <= tolerance:
                result.append((wall.index, 'start'))

            # Check end
            ex, ez = wall.end[0], wall.end[2]
            dist_end = math.sqrt((ex - x) ** 2 + (ez - z) ** 2)
            if dist_end <= tolerance:
                result.append((wall.index, 'end'))

        return result

    def to_dict(self) -> Dict[str, Any]:
        """
        Export document data as a dictionary.

        This returns the data in the format expected by generators,
        updating from parsed objects to ensure current state.

        Returns:
            Dictionary with all building data
        """
        # Update data from parsed objects first
        self._update_data()

        # Return a copy to prevent external modification
        return copy.deepcopy(self._data)

    def to_json(self) -> Dict[str, Any]:
        """Alias for to_dict() - returns document as JSON-serializable dict."""
        return self.to_dict()

    def load_from_dict(self, data: Dict[str, Any]):
        """
        Load document from dictionary (used by LLM updates).

        Args:
            data: Dictionary containing building data
        """
        self._data = copy.deepcopy(data)
        self._parse_data()
        self._modified = True
        self.document_changed.emit()
        event_bus.document_loaded.emit("")

    # =========================================================================
    # Constraint System (Pin/Lock)
    # =========================================================================

    def get_element(self, element_type: str, element_id: str):
        """
        Get an element by type and ID.

        Args:
            element_type: 'wall', 'door', 'window', or 'room'
            element_id: Element index (as string) or room ID

        Returns:
            The element or None if not found
        """
        try:
            if element_type == 'wall':
                idx = int(element_id)
                if 0 <= idx < len(self._walls):
                    return self._walls[idx]
            elif element_type == 'door':
                idx = int(element_id)
                if 0 <= idx < len(self._doors):
                    return self._doors[idx]
            elif element_type == 'window':
                idx = int(element_id)
                if 0 <= idx < len(self._windows):
                    return self._windows[idx]
            elif element_type == 'room':
                return self._rooms.get(element_id)
        except (ValueError, IndexError):
            pass
        return None

    def pin_element(self, element_type: str, element_id: str, pinned: bool = True):
        """
        Pin or unpin an element.

        Args:
            element_type: 'wall', 'door', 'window', or 'room'
            element_id: Element index (as string) or room ID
            pinned: True to pin, False to unpin
        """
        element = self.get_element(element_type, element_id)
        if element:
            element.is_pinned = pinned
            self.element_pinned.emit(element_type, element_id, pinned)
            self.element_modified.emit(element_type, element_id)
            self._modified = True

    def lock_property(self, element_type: str, element_id: str, property_name: str):
        """
        Lock a specific property on an element.

        Args:
            element_type: 'wall', 'door', 'window', or 'room'
            element_id: Element index (as string) or room ID
            property_name: Name of the property to lock
        """
        element = self.get_element(element_type, element_id)
        if element and property_name not in element.locked_properties:
            element.locked_properties.append(property_name)
            self.element_modified.emit(element_type, element_id)
            self._modified = True

    def unlock_property(self, element_type: str, element_id: str, property_name: str):
        """
        Unlock a specific property on an element.

        Args:
            element_type: 'wall', 'door', 'window', or 'room'
            element_id: Element index (as string) or room ID
            property_name: Name of the property to unlock
        """
        element = self.get_element(element_type, element_id)
        if element and property_name in element.locked_properties:
            element.locked_properties.remove(property_name)
            self.element_modified.emit(element_type, element_id)
            self._modified = True

    def get_pinned_elements(self) -> Dict[str, List[str]]:
        """
        Get all pinned elements by type.

        Returns:
            Dictionary with lists of pinned element IDs by type
        """
        pinned = {"walls": [], "doors": [], "windows": [], "rooms": []}
        for wall in self._walls:
            if wall.is_pinned:
                pinned["walls"].append(str(wall.index))
        for door in self._doors:
            if door.is_pinned:
                pinned["doors"].append(str(door.index))
        for window in self._windows:
            if window.is_pinned:
                pinned["windows"].append(str(window.index))
        for room_id, room in self._rooms.items():
            if room.is_pinned:
                pinned["rooms"].append(room_id)
        return pinned

    def is_property_locked(self, element_type: str, element_id: str, property_name: str) -> bool:
        """
        Check if a property is locked.

        A property is considered locked if:
        - The element is pinned (all properties locked), OR
        - The specific property is in locked_properties

        Args:
            element_type: 'wall', 'door', 'window', or 'room'
            element_id: Element index (as string) or room ID
            property_name: Name of the property to check

        Returns:
            True if the property is locked, False otherwise
        """
        element = self.get_element(element_type, element_id)
        if element:
            return element.is_pinned or property_name in element.locked_properties
        return False

    # =========================================================================
    # Material Assignment
    # =========================================================================

    def set_wall_material(self, wall_index: int, material_id: str):
        """
        Set material override for a specific wall.

        Args:
            wall_index: Index of the wall
            material_id: Material ID to apply (or empty string to clear)
        """
        if 0 <= wall_index < len(self._walls):
            self._walls[wall_index].material_override = material_id
            self.element_modified.emit('wall', str(wall_index))
            self._modified = True

    def set_walls_material_by_category(self, category: str, material_id: str):
        """
        Set material override for all walls of a category.

        Args:
            category: Wall category ('exterior', 'interior', 'wet_wall')
            material_id: Material ID to apply
        """
        for wall in self._walls:
            if wall.category == category:
                wall.material_override = material_id
                self.element_modified.emit('wall', str(wall.index))
        self._modified = True

    # =========================================================================
    # ArchGeometry Integration
    # =========================================================================

    def get_geometry_query(self) -> Optional[Any]:
        """
        Get ArchGeometry QueryAPI for this document.

        Returns a QueryAPI instance for geometry queries, or None if
        the archgeometry library is not available.

        Usage:
            query = doc.get_geometry_query()
            if query:
                wall_length = query.get_wall_length(0)
                room_area = query.get_room_area("living_room")
        """
        if not _ARCHGEOMETRY_AVAILABLE or archgeometry is None:
            return None

        try:
            # Parse current data into archgeometry schema
            self._update_data()
            json_str = json.dumps(self._data)
            schema_doc = archgeometry.parse_json(json_str)
            return archgeometry.QueryAPI(schema_doc)
        except Exception as e:
            print(f"Warning: Could not create geometry query: {e}")
            return None

    def validate_with_archgeometry(self) -> Tuple[bool, List[str]]:
        """
        Validate document using archgeometry library.

        Returns:
            Tuple of (is_valid, list of error messages)
        """
        if not _ARCHGEOMETRY_AVAILABLE or archgeometry is None:
            return (True, ["archgeometry not available for validation"])

        errors = []
        try:
            self._update_data()
            json_str = json.dumps(self._data)
            schema_doc = archgeometry.parse_json(json_str)

            # Check wall lengths
            for i, wall in enumerate(schema_doc.walls):
                if wall.length() < 1.0:
                    errors.append(f"Wall {i} has zero or negative length")

            # Check door/window wall indices
            for i, door in enumerate(schema_doc.doors):
                if door.wall_index < 0 or door.wall_index >= len(schema_doc.walls):
                    errors.append(f"Door {i} has invalid wall_index: {door.wall_index}")

            for i, window in enumerate(schema_doc.windows):
                if window.wall_index < 0 or window.wall_index >= len(schema_doc.walls):
                    errors.append(f"Window {i} has invalid wall_index: {window.wall_index}")

            return (len(errors) == 0, errors)

        except Exception as e:
            return (False, [f"Validation error: {str(e)}"])

    @staticmethod
    def is_archgeometry_available() -> bool:
        """Check if archgeometry library is available."""
        return _ARCHGEOMETRY_AVAILABLE
