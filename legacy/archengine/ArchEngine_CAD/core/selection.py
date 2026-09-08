"""
Selection Manager - Handles element selection, picking, and Tab cycling.

Provides:
- Python-side ray-AABB picking for 3D viewport
- Tab cycling through overlapping elements
- Selection sync between 2D and 3D viewports
"""
import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict, Any, Callable
from PyQt6.QtCore import QObject, pyqtSignal


@dataclass
class PickHit:
    """Represents a hit from a pick operation."""
    element_type: str  # 'wall', 'door', 'window', 'room', 'floor', 'roof'
    element_id: Any  # Index or ID
    distance: float  # Distance from camera
    world_pos: Tuple[float, float, float]  # Hit position in world space
    priority: int = 0  # Higher = more likely to be selected (walls > rooms > floors)
    volume: float = 0.0  # Bounding box volume - smaller = more precise


# Element type priority - higher values are selected first when overlapping
ELEMENT_PRIORITY = {
    'door': 100,      # Highest - small, precise
    'window': 100,    # Highest - small, precise
    'wall': 80,       # High - linear elements
    'room': 20,       # Low - large floor areas
    'floor': 5,       # Very low - huge horizontal planes
    'roof': 5,        # Very low - huge planes
}


@dataclass
class AABB:
    """Axis-aligned bounding box."""
    min_x: float
    min_y: float
    min_z: float
    max_x: float
    max_y: float
    max_z: float

    def volume(self) -> float:
        """Calculate bounding box volume."""
        return ((self.max_x - self.min_x) *
                (self.max_y - self.min_y) *
                (self.max_z - self.min_z))


@dataclass
class OrientedBox:
    """Oriented bounding box for walls (actual geometry)."""
    center: Tuple[float, float, float]
    half_extents: Tuple[float, float, float]  # half-size along each local axis
    axes: Tuple[Tuple[float, float, float], ...]  # 3 orthonormal axis vectors


@dataclass
class Polygon3D:
    """3D polygon for floor/ceiling planes."""
    vertices: List[Tuple[float, float, float]]
    normal: Tuple[float, float, float]


class SelectionManager(QObject):
    """
    Manages element selection across viewports.

    Features:
    - Python-side ray picking for 3D viewport
    - Tab cycling through overlapping/nearby elements
    - Selection sync between 2D and 3D viewports
    """

    # Signals
    selection_changed = pyqtSignal(list)  # List of (element_type, element_id) tuples
    element_highlighted = pyqtSignal(str, object)  # Highlight without selection (hover)

    def __init__(self, parent=None):
        super().__init__(parent)

        # Current selection
        self._selected: List[Tuple[str, Any]] = []  # [(type, id), ...]

        # Pick state for Tab cycling
        self._last_pick_hits: List[PickHit] = []
        self._cycle_index: int = 0
        self._last_screen_pos: Tuple[int, int] = (0, 0)

        # Document reference (set externally)
        self._document = None

        # Camera parameters (set externally for 3D picking)
        self._camera_pos = [0.0, 5000.0, 5000.0]
        self._camera_yaw = 0.0
        self._camera_pitch = -45.0
        self._camera_distance = 8000.0
        self._viewport_width = 800
        self._viewport_height = 600
        self._fov = 60.0

    def set_document(self, document):
        """Set document reference for element data."""
        self._document = document

    def set_camera(self, yaw: float, pitch: float, distance: float):
        """Update camera parameters for ray calculation."""
        self._camera_yaw = yaw
        self._camera_pitch = pitch
        self._camera_distance = distance

        # Calculate camera position
        rad_yaw = math.radians(yaw)
        rad_pitch = math.radians(pitch)

        self._camera_pos = [
            -distance * math.cos(rad_pitch) * math.sin(rad_yaw),
            distance * math.sin(rad_pitch),
            distance * math.cos(rad_pitch) * math.cos(rad_yaw)
        ]

    def set_viewport_size(self, width: int, height: int):
        """Update viewport dimensions."""
        self._viewport_width = width
        self._viewport_height = height

    # =========================================================================
    # Selection Operations
    # =========================================================================

    def select(self, element_type: str, element_id: Any, add: bool = False):
        """Select an element."""
        item = (element_type, element_id)

        if add:
            if item not in self._selected:
                self._selected.append(item)
        else:
            self._selected = [item]

        self.selection_changed.emit(self._selected.copy())

    def deselect(self, element_type: str, element_id: Any):
        """Remove element from selection."""
        item = (element_type, element_id)
        if item in self._selected:
            self._selected.remove(item)
            self.selection_changed.emit(self._selected.copy())

    def clear_selection(self):
        """Clear all selection."""
        if self._selected:
            self._selected.clear()
            self.selection_changed.emit([])

    def get_selection(self) -> List[Tuple[str, Any]]:
        """Get current selection."""
        return self._selected.copy()

    def is_selected(self, element_type: str, element_id: Any) -> bool:
        """Check if element is selected."""
        return (element_type, element_id) in self._selected

    # =========================================================================
    # 3D Picking
    # =========================================================================

    def pick_at_screen(self, screen_x: int, screen_y: int) -> List[PickHit]:
        """
        Pick elements at screen coordinates using ray casting.
        Returns all elements hit, sorted by priority (walls before floors/rooms).
        """
        if not self._document:
            return []

        # Convert screen to normalized device coordinates
        ndc_x = (2.0 * screen_x / self._viewport_width) - 1.0
        ndc_y = 1.0 - (2.0 * screen_y / self._viewport_height)

        # Calculate ray direction in world space
        ray_origin, ray_dir = self._screen_to_ray(ndc_x, ndc_y)

        hits = []

        # Test walls using actual geometry (faces, not AABB)
        for i, wall in enumerate(self._document.walls):
            # Use oriented box for precise intersection
            obb = self._wall_to_oriented_box(wall)
            if obb:
                t = self._ray_oriented_box_intersect(ray_origin, ray_dir, obb)
                if t is not None and t > 0:
                    hit_pos = (
                        ray_origin[0] + ray_dir[0] * t,
                        ray_origin[1] + ray_dir[1] * t,
                        ray_origin[2] + ray_dir[2] * t
                    )
                    # Calculate actual wall volume for sorting
                    volume = obb.half_extents[0] * obb.half_extents[1] * obb.half_extents[2] * 8
                    hits.append(PickHit(
                        'wall', wall.index, t, hit_pos,
                        priority=ELEMENT_PRIORITY['wall'],
                        volume=volume
                    ))

        # Test doors (highest priority - small elements)
        for i, door in enumerate(self._document.doors):
            obb = self._door_to_oriented_box(door)
            if obb:
                t = self._ray_oriented_box_intersect(ray_origin, ray_dir, obb)
                if t is not None and t > 0:
                    hit_pos = (
                        ray_origin[0] + ray_dir[0] * t,
                        ray_origin[1] + ray_dir[1] * t,
                        ray_origin[2] + ray_dir[2] * t
                    )
                    volume = obb.half_extents[0] * obb.half_extents[1] * obb.half_extents[2] * 8
                    hits.append(PickHit(
                        'door', i, t, hit_pos,
                        priority=ELEMENT_PRIORITY['door'],
                        volume=volume
                    ))

        # Test windows (highest priority - small elements)
        for i, window in enumerate(self._document.windows):
            obb = self._window_to_oriented_box(window)
            if obb:
                t = self._ray_oriented_box_intersect(ray_origin, ray_dir, obb)
                if t is not None and t > 0:
                    hit_pos = (
                        ray_origin[0] + ray_dir[0] * t,
                        ray_origin[1] + ray_dir[1] * t,
                        ray_origin[2] + ray_dir[2] * t
                    )
                    volume = obb.half_extents[0] * obb.half_extents[1] * obb.half_extents[2] * 8
                    hits.append(PickHit(
                        'window', i, t, hit_pos,
                        priority=ELEMENT_PRIORITY['window'],
                        volume=volume
                    ))

        # Test rooms using actual floor polygon (not bounding box)
        # This provides precise selection - only hits if clicking exactly on the floor
        for room_id, room in self._document._rooms.items():
            floor_poly = self._room_to_floor_polygon(room)
            if floor_poly:
                t = self._ray_polygon_intersect(ray_origin, ray_dir, floor_poly)
                if t is not None and t > 0:
                    hit_pos = (
                        ray_origin[0] + ray_dir[0] * t,
                        ray_origin[1] + ray_dir[1] * t,
                        ray_origin[2] + ray_dir[2] * t
                    )
                    # Calculate area as a proxy for volume (floors are thin)
                    area = self._polygon_area(floor_poly.vertices)
                    hits.append(PickHit(
                        'room', room_id, t, hit_pos,
                        priority=ELEMENT_PRIORITY['room'],
                        volume=area * 10  # Thin floor slab
                    ))

        # Sort by: priority (descending), then volume (ascending - smaller is better),
        # then distance (ascending - closer is better)
        hits.sort(key=lambda h: (-h.priority, h.volume, h.distance))

        return hits

    def pick_and_select(self, screen_x: int, screen_y: int, add: bool = False) -> Optional[PickHit]:
        """
        Pick element at screen position and select it.
        Stores hits for Tab cycling.
        """
        # Check if picking at same position - might be Tab cycling
        same_pos = (abs(screen_x - self._last_screen_pos[0]) < 5 and
                    abs(screen_y - self._last_screen_pos[1]) < 5)

        if not same_pos:
            # New position - get fresh hits
            self._last_pick_hits = self.pick_at_screen(screen_x, screen_y)
            self._cycle_index = 0
            self._last_screen_pos = (screen_x, screen_y)

        if not self._last_pick_hits:
            if not add:
                self.clear_selection()
            return None

        # Select the current hit
        hit = self._last_pick_hits[self._cycle_index]
        self.select(hit.element_type, hit.element_id, add)

        return hit

    def cycle_selection(self, forward: bool = True) -> Optional[PickHit]:
        """
        Cycle through overlapping elements at last pick position.
        Call this when Tab is pressed.
        """
        if not self._last_pick_hits:
            return None

        # Cycle index
        if forward:
            self._cycle_index = (self._cycle_index + 1) % len(self._last_pick_hits)
        else:
            self._cycle_index = (self._cycle_index - 1) % len(self._last_pick_hits)

        # Select new element
        hit = self._last_pick_hits[self._cycle_index]
        self.select(hit.element_type, hit.element_id, add=False)

        return hit

    def get_cycle_info(self) -> Tuple[int, int]:
        """Get current cycle position (current_index, total_count)."""
        return (self._cycle_index + 1, len(self._last_pick_hits))

    # =========================================================================
    # Ray Casting Helpers
    # =========================================================================

    def _screen_to_ray(self, ndc_x: float, ndc_y: float) -> Tuple[List[float], List[float]]:
        """Convert NDC coordinates to world-space ray (origin, direction)."""
        # Calculate view direction
        rad_yaw = math.radians(self._camera_yaw)
        rad_pitch = math.radians(self._camera_pitch)

        # Camera forward direction (looking at origin)
        forward = [
            math.cos(rad_pitch) * math.sin(rad_yaw),
            -math.sin(rad_pitch),
            -math.cos(rad_pitch) * math.cos(rad_yaw)
        ]

        # Camera right direction
        right = [
            math.cos(rad_yaw),
            0,
            math.sin(rad_yaw)
        ]

        # Camera up direction
        up = [
            forward[1] * right[2] - forward[2] * right[1],
            forward[2] * right[0] - forward[0] * right[2],
            forward[0] * right[1] - forward[1] * right[0]
        ]

        # Calculate ray direction based on FOV
        aspect = self._viewport_width / max(1, self._viewport_height)
        fov_rad = math.radians(self._fov)
        tan_half_fov = math.tan(fov_rad / 2)

        ray_dir = [
            forward[0] + right[0] * ndc_x * tan_half_fov * aspect + up[0] * ndc_y * tan_half_fov,
            forward[1] + right[1] * ndc_x * tan_half_fov * aspect + up[1] * ndc_y * tan_half_fov,
            forward[2] + right[2] * ndc_x * tan_half_fov * aspect + up[2] * ndc_y * tan_half_fov
        ]

        # Normalize
        length = math.sqrt(ray_dir[0]**2 + ray_dir[1]**2 + ray_dir[2]**2)
        if length > 0:
            ray_dir = [ray_dir[0]/length, ray_dir[1]/length, ray_dir[2]/length]

        return (self._camera_pos.copy(), ray_dir)

    def _ray_aabb_intersect(self, origin: List[float], direction: List[float],
                           aabb: AABB) -> Optional[float]:
        """
        Ray-AABB intersection test.
        Returns distance to intersection or None if no hit.
        """
        t_min = float('-inf')
        t_max = float('inf')

        bounds_min = [aabb.min_x, aabb.min_y, aabb.min_z]
        bounds_max = [aabb.max_x, aabb.max_y, aabb.max_z]

        for i in range(3):
            if abs(direction[i]) < 1e-8:
                # Ray parallel to slab
                if origin[i] < bounds_min[i] or origin[i] > bounds_max[i]:
                    return None
            else:
                t1 = (bounds_min[i] - origin[i]) / direction[i]
                t2 = (bounds_max[i] - origin[i]) / direction[i]

                if t1 > t2:
                    t1, t2 = t2, t1

                t_min = max(t_min, t1)
                t_max = min(t_max, t2)

                if t_min > t_max:
                    return None

        return t_min if t_min >= 0 else t_max

    def _ray_oriented_box_intersect(self, origin: List[float], direction: List[float],
                                    box: OrientedBox) -> Optional[float]:
        """
        Ray-oriented box intersection test using the slab method.
        More precise than AABB for rotated walls.
        """
        t_min = float('-inf')
        t_max = float('inf')

        # Vector from box center to ray origin
        delta = [origin[i] - box.center[i] for i in range(3)]

        for i in range(3):
            axis = box.axes[i]
            half_extent = box.half_extents[i]

            # Project delta and direction onto this axis
            e = sum(axis[j] * delta[j] for j in range(3))
            f = sum(axis[j] * direction[j] for j in range(3))

            if abs(f) > 1e-8:
                t1 = (-half_extent - e) / f
                t2 = (half_extent - e) / f

                if t1 > t2:
                    t1, t2 = t2, t1

                t_min = max(t_min, t1)
                t_max = min(t_max, t2)

                if t_min > t_max:
                    return None
            elif abs(e) > half_extent:
                # Ray parallel to slab and outside
                return None

        return t_min if t_min >= 0 else (t_max if t_max >= 0 else None)

    def _ray_polygon_intersect(self, origin: List[float], direction: List[float],
                               polygon: Polygon3D) -> Optional[float]:
        """
        Ray-polygon intersection test.
        First tests ray-plane, then checks if point is inside polygon.
        """
        if len(polygon.vertices) < 3:
            return None

        normal = polygon.normal
        v0 = polygon.vertices[0]

        # Ray-plane intersection
        denom = sum(normal[i] * direction[i] for i in range(3))
        if abs(denom) < 1e-8:
            return None  # Ray parallel to plane

        d = sum(normal[i] * v0[i] for i in range(3))
        t = (d - sum(normal[i] * origin[i] for i in range(3))) / denom

        if t < 0:
            return None  # Intersection behind ray

        # Hit point on plane
        hit = [origin[i] + direction[i] * t for i in range(3)]

        # Point-in-polygon test using winding number (works for convex and concave)
        if not self._point_in_polygon_3d(hit, polygon):
            return None

        return t

    def _point_in_polygon_3d(self, point: List[float], polygon: Polygon3D) -> bool:
        """
        Check if a point on a polygon's plane is inside the polygon.
        Uses the crossing number algorithm projected onto the dominant axis.
        """
        vertices = polygon.vertices
        normal = polygon.normal
        n = len(vertices)

        # Find dominant axis of normal for 2D projection
        abs_normal = [abs(normal[i]) for i in range(3)]
        if abs_normal[0] >= abs_normal[1] and abs_normal[0] >= abs_normal[2]:
            # Project onto YZ plane
            proj_i, proj_j = 1, 2
        elif abs_normal[1] >= abs_normal[2]:
            # Project onto XZ plane
            proj_i, proj_j = 0, 2
        else:
            # Project onto XY plane
            proj_i, proj_j = 0, 1

        # 2D point-in-polygon test (crossing number)
        px, py = point[proj_i], point[proj_j]
        crossings = 0

        for i in range(n):
            v1 = vertices[i]
            v2 = vertices[(i + 1) % n]
            x1, y1 = v1[proj_i], v1[proj_j]
            x2, y2 = v2[proj_i], v2[proj_j]

            # Check if edge crosses the horizontal ray from point
            if (y1 <= py < y2) or (y2 <= py < y1):
                # Calculate x intersection
                t_edge = (py - y1) / (y2 - y1) if abs(y2 - y1) > 1e-8 else 0
                x_intersect = x1 + t_edge * (x2 - x1)
                if px < x_intersect:
                    crossings += 1

        return (crossings % 2) == 1

    def _ray_quad_intersect(self, origin: List[float], direction: List[float],
                            corners: List[Tuple[float, float, float]]) -> Optional[float]:
        """
        Ray-quad intersection (4 corners defining a planar quad).
        Used for wall faces.
        """
        if len(corners) < 4:
            return None

        # Calculate normal from first 3 corners
        v0, v1, v2 = corners[0], corners[1], corners[2]
        e1 = [v1[i] - v0[i] for i in range(3)]
        e2 = [v2[i] - v0[i] for i in range(3)]

        normal = (
            e1[1] * e2[2] - e1[2] * e2[1],
            e1[2] * e2[0] - e1[0] * e2[2],
            e1[0] * e2[1] - e1[1] * e2[0]
        )
        length = math.sqrt(sum(n * n for n in normal))
        if length < 1e-8:
            return None
        normal = tuple(n / length for n in normal)

        # Create polygon and test
        poly = Polygon3D(vertices=list(corners), normal=normal)
        return self._ray_polygon_intersect(origin, direction, poly)

    def _polygon_area(self, vertices: List[Tuple[float, float, float]]) -> float:
        """Calculate area of a 3D polygon using the shoelace formula."""
        if len(vertices) < 3:
            return 0.0

        # Calculate normal to determine projection plane
        v0, v1, v2 = vertices[0], vertices[1], vertices[2]
        e1 = [v1[i] - v0[i] for i in range(3)]
        e2 = [v2[i] - v0[i] for i in range(3)]

        normal = (
            e1[1] * e2[2] - e1[2] * e2[1],
            e1[2] * e2[0] - e1[0] * e2[2],
            e1[0] * e2[1] - e1[1] * e2[0]
        )

        # Find dominant axis for 2D projection
        abs_normal = [abs(n) for n in normal]
        if abs_normal[0] >= abs_normal[1] and abs_normal[0] >= abs_normal[2]:
            proj_i, proj_j = 1, 2
        elif abs_normal[1] >= abs_normal[2]:
            proj_i, proj_j = 0, 2
        else:
            proj_i, proj_j = 0, 1

        # Shoelace formula in 2D projection
        n = len(vertices)
        area = 0.0
        for i in range(n):
            j = (i + 1) % n
            area += vertices[i][proj_i] * vertices[j][proj_j]
            area -= vertices[j][proj_i] * vertices[i][proj_j]

        return abs(area) / 2.0

    # =========================================================================
    # Actual Geometry Calculators
    # =========================================================================

    def _wall_to_oriented_box(self, wall) -> Optional[OrientedBox]:
        """Calculate oriented bounding box for a wall (actual geometry)."""
        if not wall.start or not wall.end:
            return None

        x1, y1, z1 = wall.start
        x2, y2, z2 = wall.end

        # Wall properties
        thickness = getattr(wall, 'thickness', 200)  # Default 200mm
        height = getattr(wall, 'height', 3000)  # Default 3m

        # Calculate wall direction
        dx = x2 - x1
        dz = z2 - z1
        length = math.sqrt(dx * dx + dz * dz)
        if length < 1:
            return None

        # Local axes
        # Axis 0: Along wall length
        axis_length = (dx / length, 0.0, dz / length)
        # Axis 1: Up (Y direction)
        axis_up = (0.0, 1.0, 0.0)
        # Axis 2: Perpendicular to wall (thickness direction)
        axis_thick = (-dz / length, 0.0, dx / length)

        # Center of wall box
        center = (
            (x1 + x2) / 2,
            y1 + height / 2,
            (z1 + z2) / 2
        )

        # Half extents
        half_extents = (
            length / 2,      # Along wall
            height / 2,      # Height
            thickness / 2    # Thickness
        )

        return OrientedBox(
            center=center,
            half_extents=half_extents,
            axes=(axis_length, axis_up, axis_thick)
        )

    def _wall_to_faces(self, wall) -> List[List[Tuple[float, float, float]]]:
        """
        Get the 6 faces of a wall box as quads.
        Returns list of 4-corner quads for each face.
        """
        if not wall.start or not wall.end:
            return []

        x1, y1, z1 = wall.start
        x2, y2, z2 = wall.end

        thickness = getattr(wall, 'thickness', 200)
        height = getattr(wall, 'height', 3000)

        # Wall direction
        dx = x2 - x1
        dz = z2 - z1
        length = math.sqrt(dx * dx + dz * dz)
        if length < 1:
            return []

        # Perpendicular offset (half thickness)
        half_thick = thickness / 2
        px = -dz / length * half_thick
        pz = dx / length * half_thick

        # 8 corners of the wall box
        # Bottom corners
        b1 = (x1 + px, y1, z1 + pz)  # start, +perp
        b2 = (x1 - px, y1, z1 - pz)  # start, -perp
        b3 = (x2 + px, y1, z2 + pz)  # end, +perp
        b4 = (x2 - px, y1, z2 - pz)  # end, -perp

        # Top corners
        top_y = y1 + height
        t1 = (x1 + px, top_y, z1 + pz)
        t2 = (x1 - px, top_y, z1 - pz)
        t3 = (x2 + px, top_y, z2 + pz)
        t4 = (x2 - px, top_y, z2 - pz)

        # 6 faces as quads (CCW winding when viewed from outside)
        faces = [
            # Front face (+perp side)
            [b1, b3, t3, t1],
            # Back face (-perp side)
            [b4, b2, t2, t4],
            # Start cap
            [b2, b1, t1, t2],
            # End cap
            [b3, b4, t4, t3],
            # Top
            [t1, t3, t4, t2],
            # Bottom
            [b2, b4, b3, b1],
        ]

        return faces

    def _room_to_floor_polygon(self, room) -> Optional[Polygon3D]:
        """Get room floor as a 3D polygon for precise intersection."""
        vertices = getattr(room, 'vertices', None)
        if not vertices or len(vertices) < 3:
            return None

        # Convert 2D vertices to 3D (on floor plane Y=0)
        vertices_3d = [(v[0], 0.0, v[1]) for v in vertices]

        # Normal is up (Y+)
        normal = (0.0, 1.0, 0.0)

        return Polygon3D(vertices=vertices_3d, normal=normal)

    def _door_to_oriented_box(self, door) -> Optional[OrientedBox]:
        """Calculate oriented bounding box for a door (actual geometry)."""
        wall_idx = getattr(door, 'wall_index', None)
        if wall_idx is None or not self._document:
            return None

        walls = self._document.walls
        if wall_idx >= len(walls):
            return None

        wall = walls[wall_idx]
        if not wall.start or not wall.end:
            return None

        x1, y1, z1 = wall.start
        x2, y2, z2 = wall.end

        # Door properties
        position = getattr(door, 'position', 0.5)
        width = getattr(door, 'width', 900)
        height = getattr(door, 'height', 2100)

        # Wall direction
        dx = x2 - x1
        dz = z2 - z1
        length = math.sqrt(dx * dx + dz * dz)
        if length < 1:
            return None

        # Wall thickness (door extends through wall)
        wall_thickness = getattr(wall, 'thickness', 200)

        # Door center along wall
        cx = x1 + dx * position
        cz = z1 + dz * position

        # Local axes (same as wall)
        axis_length = (dx / length, 0.0, dz / length)
        axis_up = (0.0, 1.0, 0.0)
        axis_thick = (-dz / length, 0.0, dx / length)

        center = (cx, y1 + height / 2, cz)
        half_extents = (width / 2, height / 2, wall_thickness / 2)

        return OrientedBox(center=center, half_extents=half_extents, axes=(axis_length, axis_up, axis_thick))

    def _window_to_oriented_box(self, window) -> Optional[OrientedBox]:
        """Calculate oriented bounding box for a window (actual geometry)."""
        wall_idx = getattr(window, 'wall_index', None)
        if wall_idx is None or not self._document:
            return None

        walls = self._document.walls
        if wall_idx >= len(walls):
            return None

        wall = walls[wall_idx]
        if not wall.start or not wall.end:
            return None

        x1, y1, z1 = wall.start
        x2, y2, z2 = wall.end

        # Window properties
        position = getattr(window, 'position', 0.5)
        width = getattr(window, 'width', 1200)
        height = getattr(window, 'height', 1200)
        sill_height = getattr(window, 'sill_height', 900)

        # Wall direction
        dx = x2 - x1
        dz = z2 - z1
        length = math.sqrt(dx * dx + dz * dz)
        if length < 1:
            return None

        wall_thickness = getattr(wall, 'thickness', 200)

        # Window center along wall
        cx = x1 + dx * position
        cz = z1 + dz * position

        # Local axes
        axis_length = (dx / length, 0.0, dz / length)
        axis_up = (0.0, 1.0, 0.0)
        axis_thick = (-dz / length, 0.0, dx / length)

        center = (cx, y1 + sill_height + height / 2, cz)
        half_extents = (width / 2, height / 2, wall_thickness / 2)

        return OrientedBox(center=center, half_extents=half_extents, axes=(axis_length, axis_up, axis_thick))

    def _wall_to_aabb(self, wall) -> Optional[AABB]:
        """Calculate AABB for a wall."""
        if not wall.start or not wall.end:
            return None

        # Wall coordinates - note: document uses X, Z for 2D, Y is height
        x1, y1, z1 = wall.start
        x2, y2, z2 = wall.end

        # Calculate wall thickness offset
        thickness = getattr(wall, 'thickness', 200)  # Default 200mm
        half_thick = thickness / 2

        # Wall direction and perpendicular
        dx = x2 - x1
        dz = z2 - z1
        length = math.sqrt(dx*dx + dz*dz)
        if length < 1:
            return None

        px = -dz / length * half_thick
        pz = dx / length * half_thick

        # Calculate all corners
        corners_x = [x1 + px, x1 - px, x2 + px, x2 - px]
        corners_z = [z1 + pz, z1 - pz, z2 + pz, z2 - pz]

        # Get height from wall or default
        height = getattr(wall, 'height', 3000)  # Default 3m

        return AABB(
            min_x=min(corners_x),
            min_y=y1,  # Floor level
            min_z=min(corners_z),
            max_x=max(corners_x),
            max_y=y1 + height,  # Top
            max_z=max(corners_z)
        )

    def _room_to_aabb(self, room) -> Optional[AABB]:
        """Calculate AABB for a room (floor plane with height)."""
        vertices = getattr(room, 'vertices', None)
        if not vertices or len(vertices) < 3:
            # Fall back to bounds
            bounds = getattr(room, 'bounds', None)
            if bounds:
                return AABB(
                    min_x=bounds['x'],
                    min_y=0,  # Floor
                    min_z=bounds['y'],
                    max_x=bounds['x'] + bounds['width'],
                    max_y=3000,  # Default ceiling
                    max_z=bounds['y'] + bounds['height']
                )
            return None

        xs = [v[0] for v in vertices]
        zs = [v[1] for v in vertices]  # Note: vertices are [x, z] pairs

        return AABB(
            min_x=min(xs),
            min_y=0,  # Floor
            min_z=min(zs),
            max_x=max(xs),
            max_y=3000,  # Default ceiling height
            max_z=max(zs)
        )

    def _door_to_aabb(self, door) -> Optional[AABB]:
        """Calculate AABB for a door."""
        # Get door position from wall
        wall_idx = getattr(door, 'wall_index', None)
        if wall_idx is None or not self._document:
            return None

        walls = self._document.walls
        if wall_idx >= len(walls):
            return None

        wall = walls[wall_idx]
        if not wall.start or not wall.end:
            return None

        x1, y1, z1 = wall.start
        x2, y2, z2 = wall.end

        # Calculate door position along wall
        position = getattr(door, 'position', 0.5)  # 0-1 along wall
        width = getattr(door, 'width', 900)  # Default 900mm
        height = getattr(door, 'height', 2100)  # Default 2.1m

        # Wall vector
        dx = x2 - x1
        dz = z2 - z1
        length = math.sqrt(dx*dx + dz*dz)
        if length < 1:
            return None

        # Door center
        cx = x1 + dx * position
        cz = z1 + dz * position

        # Perpendicular for thickness
        half_width = width / 2
        px = -dz / length * half_width
        pz = dx / length * half_width

        # Along wall extent
        ax = dx / length * half_width
        az = dz / length * half_width

        return AABB(
            min_x=cx - abs(px) - abs(ax),
            min_y=y1,  # Floor
            min_z=cz - abs(pz) - abs(az),
            max_x=cx + abs(px) + abs(ax),
            max_y=y1 + height,
            max_z=cz + abs(pz) + abs(az)
        )

    def _window_to_aabb(self, window) -> Optional[AABB]:
        """Calculate AABB for a window."""
        # Similar to door but with sill height
        wall_idx = getattr(window, 'wall_index', None)
        if wall_idx is None or not self._document:
            return None

        walls = self._document.walls
        if wall_idx >= len(walls):
            return None

        wall = walls[wall_idx]
        if not wall.start or not wall.end:
            return None

        x1, y1, z1 = wall.start
        x2, y2, z2 = wall.end

        position = getattr(window, 'position', 0.5)
        width = getattr(window, 'width', 1200)  # Default 1.2m
        height = getattr(window, 'height', 1200)  # Default 1.2m
        sill_height = getattr(window, 'sill_height', 900)  # Default 0.9m

        dx = x2 - x1
        dz = z2 - z1
        length = math.sqrt(dx*dx + dz*dz)
        if length < 1:
            return None

        cx = x1 + dx * position
        cz = z1 + dz * position

        half_width = width / 2
        px = -dz / length * half_width
        pz = dx / length * half_width
        ax = dx / length * half_width
        az = dz / length * half_width

        return AABB(
            min_x=cx - abs(px) - abs(ax),
            min_y=y1 + sill_height,  # Sill
            min_z=cz - abs(pz) - abs(az),
            max_x=cx + abs(px) + abs(ax),
            max_y=y1 + sill_height + height,  # Top
            max_z=cz + abs(pz) + abs(az)
        )


# Singleton instance
_selection_manager: Optional[SelectionManager] = None

def get_selection_manager() -> SelectionManager:
    """Get the global selection manager instance."""
    global _selection_manager
    if _selection_manager is None:
        _selection_manager = SelectionManager()
    return _selection_manager
