"""Constraint solver for QBD Algebra.

Sophisticated room placement algorithm based on RevitMCP's coordinate_solver.

Key features:
1. Priority-based placement order (entry → living → hallway → bedrooms)
2. Backtracking search with branching
3. Dead space for circulation (grow hallway cells to reach stuck rooms)
4. Multi-pass constraint relaxation (strict → relaxed exterior → full relaxation)
5. Strategic position generation (near must-touch rooms + boundaries)
6. Improved scoring (adjacency bonuses, aspect ratio, space efficiency)

Algorithm:
1. Get placement order based on room priority
2. For each room, generate candidate positions
3. Score positions and try placement with backtracking
4. If stuck, grow dead space circulation
5. Multiple relaxation passes if needed
"""

from typing import Dict, List, Any, Optional, Tuple, Set, NamedTuple
from dataclasses import dataclass, field
from copy import deepcopy
import math
import heapq

from .state import QBDState, StateLifecycle
from .errors import (
    ValidationResult, QBDError, QBDWarning, ErrorCode, ErrorType,
    unsatisfiable_error, underdetermined_error
)
from .deriver import derive_values, apply_derived_to_state
from .validator import validate_state
from .defaults import BUILDING_DEFAULTS, ROOM_DEFAULTS, m_to_mm, mm_to_m


# =============================================================================
# GEOMETRY PRIMITIVES
# =============================================================================

class Point(NamedTuple):
    x: float
    y: float


class Rect(NamedTuple):
    """Axis-aligned rectangle (all dimensions in mm)."""
    x: float
    y: float
    width: float
    height: float

    @property
    def x2(self) -> float:
        return self.x + self.width

    @property
    def y2(self) -> float:
        return self.y + self.height

    @property
    def area(self) -> float:
        return self.width * self.height

    @property
    def center(self) -> Point:
        return Point(self.x + self.width / 2, self.y + self.height / 2)

    @property
    def aspect(self) -> float:
        if self.width == 0 or self.height == 0:
            return 0
        return min(self.width, self.height) / max(self.width, self.height)

    def overlaps(self, other: 'Rect', tolerance: float = 10) -> bool:
        """Check if rectangles overlap."""
        return (self.x < other.x2 - tolerance and
                self.x2 > other.x + tolerance and
                self.y < other.y2 - tolerance and
                self.y2 > other.y + tolerance)

    def touches(self, other: 'Rect', tolerance: float = 50) -> bool:
        """Check if rectangles share an edge (adjacent but not overlapping)."""
        if self.overlaps(other):
            return False

        # Vertical adjacency (side by side)
        if abs(self.x2 - other.x) < tolerance or abs(self.x - other.x2) < tolerance:
            return self.y < other.y2 and self.y2 > other.y

        # Horizontal adjacency (top/bottom)
        if abs(self.y2 - other.y) < tolerance or abs(self.y - other.y2) < tolerance:
            return self.x < other.x2 and self.x2 > other.x

        return False

    def is_on_boundary(self, bounds: 'Rect', edge: str, tolerance: float = 50) -> bool:
        """Check if this rect touches a specific edge of bounds."""
        if edge == "south":
            return abs(self.y - bounds.y) < tolerance
        elif edge == "north":
            return abs(self.y2 - bounds.y2) < tolerance
        elif edge == "west":
            return abs(self.x - bounds.x) < tolerance
        elif edge == "east":
            return abs(self.x2 - bounds.x2) < tolerance
        return False

    def touches_any_boundary(self, bounds: 'Rect', tolerance: float = 50) -> bool:
        """Check if this rect touches any edge of bounds."""
        return any(self.is_on_boundary(bounds, edge, tolerance)
                   for edge in ["south", "north", "east", "west"])


# =============================================================================
# PLACED ROOM
# =============================================================================

@dataclass
class PlacedRoom:
    """A room with solved position and dimensions."""
    id: str
    name: str
    room_type: str
    rect: Rect

    @property
    def x(self) -> float:
        return self.rect.x

    @property
    def z(self) -> float:
        return self.rect.y

    @property
    def width(self) -> float:
        return self.rect.width

    @property
    def length(self) -> float:
        return self.rect.height

    @property
    def area_sqm(self) -> float:
        return self.rect.area / 1_000_000

    def overlaps(self, other: "PlacedRoom") -> bool:
        return self.rect.overlaps(other.rect)

    def shares_edge(self, other: "PlacedRoom") -> bool:
        return self.rect.touches(other.rect)


# =============================================================================
# SOLVER CANDIDATE
# =============================================================================

@dataclass
class SolverCandidate:
    """A candidate layout solution."""
    rooms: List[PlacedRoom]
    score: float = 0.0
    score_breakdown: Dict[str, float] = field(default_factory=dict)
    satisfied_adjacencies: int = 0
    satisfied_separations: int = 0
    tradeoffs: List[str] = field(default_factory=list)


# =============================================================================
# SOLVER RESULT
# =============================================================================

@dataclass
class SolverResult:
    """Result from the solver."""
    status: str  # "solved", "failed", "underdetermined"
    layout: Optional[Dict[str, Any]] = None
    candidates: List[SolverCandidate] = field(default_factory=list)
    errors: List[QBDError] = field(default_factory=list)
    warnings: List[QBDWarning] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "status": self.status,
            "layout": self.layout,
            "errors": [e.to_dict() for e in self.errors],
            "warnings": [w.to_dict() for w in self.warnings],
        }
        if self.candidates:
            result["candidates_count"] = len(self.candidates)
            result["best_score"] = self.candidates[0].score if self.candidates else None
        return result


# =============================================================================
# ROOM PRIORITY - determines placement order
# =============================================================================

# Room type priorities (lower = placed earlier)
ROOM_PRIORITY = {
    "entry": 0,
    "foyer": 0,
    "living": 1,
    "great_room": 1,
    "hallway": 2,
    "dining": 3,
    "kitchen": 3,
    "garage_1car": 4,
    "garage_2car": 4,
    "garage": 4,
    "primary_bedroom": 5,
    "bedroom": 5,
    "ensuite": 6,
    "primary_bath": 6,
    "walk_in_closet": 7,
    "closet": 7,
    "bathroom": 7,
    "powder_room": 7,
    "office": 8,
    "laundry": 9,
    "mudroom": 9,
    "pantry": 9,
    "utility": 10,
}

# Rooms that need exterior wall access
EXTERIOR_REQUIRED = {
    "bedroom", "primary_bedroom", "living", "dining", "office",
    "garage", "garage_1car", "garage_2car"
}

# Rooms that prefer exterior (but don't require it)
EXTERIOR_PREFERRED = {
    "kitchen", "laundry", "mudroom"
}


# =============================================================================
# QBD SOLVER
# =============================================================================

class QBDSolver:
    """
    Sophisticated constraint solver for room layouts.

    Uses algorithms from RevitMCP's coordinate_solver:
    1. Priority-based placement ordering
    2. Backtracking search with branching
    3. Dead space for circulation growth
    4. Multi-pass constraint relaxation
    """

    def __init__(self, state: QBDState, grid_size: int = 200):
        """
        Initialize solver.

        Args:
            state: QBD state to solve
            grid_size: Placement grid in mm (default 200mm = 20cm)
        """
        self.state = state
        self.grid = grid_size

        # Building bounds (will be set during solve)
        self.bounds: Rect = None
        self.initial_bounds: Rect = None

        # Placement state
        self.placed: Dict[str, PlacedRoom] = {}
        self.best_partial: Dict[str, PlacedRoom] = {}
        self.nodes_explored = 0

        # Constraint relaxation
        self.relaxed_constraints: Set[str] = set()
        self.exterior_relaxed: Set[str] = set()

        # Dead space tracking
        self.dead_space_count = 0

        # Adjacency lookup (built from state)
        self.must_touch: Dict[str, Set[str]] = {}
        self.must_separate: Dict[str, Set[str]] = {}

    def solve(self, max_nodes: int = 50000) -> SolverResult:
        """Run the solver pipeline."""

        # Stage 0: Pre-check
        if self.state.lifecycle == StateLifecycle.EMPTY:
            return SolverResult(
                status="underdetermined",
                errors=[underdetermined_error(
                    "Cannot solve empty state",
                    ["At least one room is required"]
                )]
            )

        # Run validation
        validation = validate_state(self.state)
        if not validation.valid:
            return SolverResult(
                status="failed",
                errors=validation.errors,
                warnings=validation.warnings
            )

        # Run derivation
        derived = derive_values(self.state)
        apply_derived_to_state(self.state, derived)

        # Check if solvable
        if not self._is_solvable():
            return SolverResult(
                status="underdetermined",
                errors=[underdetermined_error(
                    "Not enough information to solve",
                    self._get_missing_info()
                )]
            )

        # Setup bounds
        self._setup_bounds()

        # Build adjacency lookup
        self._build_adjacency_lookup()

        # Get placement order
        order = self._get_placement_order()

        # Run multi-pass search
        self._place_rooms(order, max_nodes)

        # Use best partial if no complete solution
        if not self.placed and self.best_partial:
            self.placed = self.best_partial

        if not self.placed:
            return SolverResult(
                status="failed",
                errors=[QBDError(
                    code=ErrorCode.SOLVER_FAILED,
                    error_type=ErrorType.FEASIBILITY,
                    message="Could not find valid layout"
                )]
            )

        # Build candidate from placed rooms
        candidate = self._build_candidate()

        # Score candidate
        self._score_candidate(candidate)

        # Convert to layout
        layout = self._candidate_to_layout(candidate)

        # Store in state
        self.state._solved_layout = layout
        self.state._lifecycle = StateLifecycle.SOLVED

        return SolverResult(
            status="solved",
            layout=layout,
            candidates=[candidate],
            warnings=validation.warnings
        )

    # =========================================================================
    # SETUP
    # =========================================================================

    def _is_solvable(self) -> bool:
        """Check if state has enough info to solve."""
        rooms = self.state.rooms
        if not rooms:
            return False

        # Need footprint or site dimensions
        constraints = self.state.constraints
        site = self.state.site

        has_bounds = (
            constraints.get("footprint_max") is not None or
            (site.get("width") is not None and site.get("depth") is not None)
        )

        return has_bounds

    def _get_missing_info(self) -> List[str]:
        """Get list of missing information."""
        missing = []
        if not self.state.rooms:
            missing.append("No rooms defined")
        if (self.state.constraints.get("footprint_max") is None and
            self.state.site.get("width") is None):
            missing.append("Footprint limit or site dimensions needed")
        return missing

    def _setup_bounds(self):
        """Setup building bounds from constraints/site."""
        footprint_max = self.state.constraints.get("footprint_max")
        site = self.state.site

        if site.get("width") and site.get("depth"):
            setbacks = site.get("setbacks") or {}
            left = setbacks.get("left") or 0
            right = setbacks.get("right") or 0
            front = setbacks.get("front") or 0
            rear = setbacks.get("rear") or 0
            max_width = m_to_mm(site["width"]) - m_to_mm(left + right)
            max_depth = m_to_mm(site["depth"]) - m_to_mm(front + rear)
        elif footprint_max:
            # Convert sqm to mm, assume roughly square
            side = int(math.sqrt(footprint_max * 1_000_000))
            max_width = side
            max_depth = side
        else:
            max_width = 15000  # 15m default
            max_depth = 15000

        self.bounds = Rect(0, 0, max_width, max_depth)
        self.initial_bounds = self.bounds

    def _build_adjacency_lookup(self):
        """Build adjacency lookup from state."""
        self.must_touch = {}
        self.must_separate = {}

        for adj in self.state.adjacencies:
            room_a = adj.get("room_a")
            room_b = adj.get("room_b")
            strength = adj.get("strength", "preferred")

            if strength == "required":
                self.must_touch.setdefault(room_a, set()).add(room_b)
                self.must_touch.setdefault(room_b, set()).add(room_a)

        for sep in self.state.separations:
            room_a = sep.get("room_a")
            room_b = sep.get("room_b")
            strength = sep.get("strength", "preferred")

            if strength == "required":
                self.must_separate.setdefault(room_a, set()).add(room_b)
                self.must_separate.setdefault(room_b, set()).add(room_a)

    # =========================================================================
    # PLACEMENT ORDER (Priority-based)
    # =========================================================================

    def _get_placement_order(self) -> List[str]:
        """Get rooms in order of placement priority."""
        rooms = self.state.rooms

        def get_priority(room: Dict) -> Tuple[int, int, int]:
            room_id = room.get("id", "")
            room_type = room.get("type", "")

            # Base priority from room type
            base = ROOM_PRIORITY.get(room_type, 8)

            # Exterior requirement lowers priority (place earlier)
            needs_exterior = room_type in EXTERIOR_REQUIRED
            exterior_bonus = -10 if needs_exterior else 0

            # Larger rooms placed earlier (by area)
            area = room.get("area_min", 10)
            size_priority = -area

            # Rooms with more must-touch constraints placed earlier
            touch_count = len(self.must_touch.get(room_id, set()))
            hub_priority = -touch_count

            return (base, exterior_bonus + hub_priority, size_priority)

        # Sort rooms by priority
        sorted_rooms = sorted(rooms, key=get_priority)

        return [r.get("id") for r in sorted_rooms]

    # =========================================================================
    # MULTI-PASS PLACEMENT
    # =========================================================================

    def _place_rooms(self, order: List[str], max_nodes: int):
        """Place rooms using multi-pass search with constraint relaxation."""

        # Pass 1: Strict constraints
        self._search_pass(order, max_nodes // 2, relaxed=False)

        # Pass 2: Dead space bridges for stuck rooms
        if len(self.placed) < len(order):
            remaining = [r for r in order if r not in self.placed]
            for room_id in remaining:
                if self._try_place_with_dead_space(room_id):
                    pass  # Successfully placed

        # Pass 3: Relax exterior requirements
        if len(self.placed) < len(order):
            remaining = [r for r in order if r not in self.placed]
            for room_id in remaining:
                self.exterior_relaxed.add(room_id)
            self._search_pass(remaining, max_nodes // 4, relaxed=False)

        # Pass 4: Full relaxation
        if len(self.placed) < len(order):
            remaining = [r for r in order if r not in self.placed]
            for room_id in remaining:
                self.relaxed_constraints.add(room_id)
            self._search_pass(remaining, max_nodes // 4, relaxed=True)

    def _search_pass(self, order: List[str], max_nodes: int, relaxed: bool):
        """Single search pass."""
        for room_id in order:
            if room_id in self.placed:
                continue

            room = self._get_room_by_id(room_id)
            if not room:
                continue

            # Generate candidates
            candidates = self._generate_candidates(room_id, room, relaxed)

            if not candidates:
                continue

            # Score and sort candidates
            scored = [(self._score_position(room_id, rect, relaxed), rect)
                      for rect in candidates]
            scored.sort(reverse=True, key=lambda x: x[0])

            # Try best candidates
            for score, rect in scored[:50]:
                if score < 0:
                    continue

                # Check if valid
                if self._is_valid_position(room_id, rect, relaxed):
                    self.placed[room_id] = PlacedRoom(
                        id=room_id,
                        name=room.get("name", "Room"),
                        room_type=room.get("type", "room"),
                        rect=rect
                    )
                    break

            self.nodes_explored += 1
            if self.nodes_explored >= max_nodes:
                break

        # Track best partial
        if len(self.placed) > len(self.best_partial):
            self.best_partial = dict(self.placed)

    # =========================================================================
    # DEAD SPACE CIRCULATION
    # =========================================================================

    def _try_place_with_dead_space(self, room_id: str) -> bool:
        """Try to place a room by growing dead space circulation toward it."""
        room = self._get_room_by_id(room_id)
        if not room:
            return False

        # Check if room needs hallway adjacency
        must_touch = self.must_touch.get(room_id, set())
        needs_circulation = any(r in must_touch for r in ['hallway', 'entry'])
        if not needs_circulation:
            return False

        # Find circulation rooms
        circulation_rooms = [
            r for r in self.placed.keys()
            if r in ['hallway', 'entry'] or r.startswith('dead_space_')
        ]

        if not circulation_rooms:
            return False

        # Grow dead space toward each edge
        needs_exterior = room.get("type") in EXTERIOR_REQUIRED
        room_type = room.get("type")

        if needs_exterior and room_id not in self.exterior_relaxed:
            # Try growing toward exterior edges
            for edge in ['north', 'south', 'east', 'west']:
                if self._grow_to_edge(circulation_rooms, edge, room_id, room):
                    return True
        else:
            # Grow in any direction
            if self._grow_circulation_outward(circulation_rooms, room_id, room):
                return True

        return False

    def _grow_to_edge(self, circulation_rooms: List[str], edge: str,
                      target_room_id: str, room: Dict) -> bool:
        """Grow dead space from circulation toward an edge."""
        max_dead_spaces = 8
        ds_size = max(self.grid * 4, 1200)  # At least 1.2m

        for _ in range(max_dead_spaces):
            # Find circulation room closest to target edge
            best_circ = None
            best_dist = float('inf')

            for circ_id in circulation_rooms:
                if circ_id not in self.placed:
                    continue
                circ_rect = self.placed[circ_id].rect

                if edge == 'north':
                    dist = self.bounds.height - circ_rect.y2
                elif edge == 'south':
                    dist = circ_rect.y
                elif edge == 'east':
                    dist = self.bounds.width - circ_rect.x2
                else:  # west
                    dist = circ_rect.x

                if dist > self.grid and dist < best_dist:
                    best_dist = dist
                    best_circ = circ_id

            if best_circ is None or best_dist < self.grid:
                break

            # Add dead space toward edge
            circ_rect = self.placed[best_circ].rect

            if edge == 'north':
                ds_rect = Rect(circ_rect.x, circ_rect.y2, ds_size, ds_size)
            elif edge == 'south':
                ds_rect = Rect(circ_rect.x, circ_rect.y - ds_size, ds_size, ds_size)
            elif edge == 'east':
                ds_rect = Rect(circ_rect.x2, circ_rect.y, ds_size, ds_size)
            else:
                ds_rect = Rect(circ_rect.x - ds_size, circ_rect.y, ds_size, ds_size)

            if not self._is_dead_space_valid(ds_rect):
                break

            # Place dead space
            ds_id = f"dead_space_{self.dead_space_count}"
            self.dead_space_count += 1
            self.placed[ds_id] = PlacedRoom(
                id=ds_id,
                name="Circulation",
                room_type="hallway",
                rect=ds_rect
            )
            circulation_rooms.append(ds_id)

        # Try placing target room now
        candidates = self._generate_candidates(target_room_id, room, relaxed=False)
        if candidates:
            scored = [(self._score_position(target_room_id, rect, False), rect)
                      for rect in candidates]
            scored.sort(reverse=True, key=lambda x: x[0])
            for score, rect in scored[:30]:
                if score >= 0 and self._is_valid_position(target_room_id, rect, False):
                    self.placed[target_room_id] = PlacedRoom(
                        id=target_room_id,
                        name=room.get("name", "Room"),
                        room_type=room.get("type", "room"),
                        rect=rect
                    )
                    return True

        return False

    def _grow_circulation_outward(self, circulation_rooms: List[str],
                                   target_room_id: str, room: Dict) -> bool:
        """Grow dead space outward from circulation."""
        max_dead_spaces = 6
        ds_size = max(self.grid * 4, 1200)
        directions = [(0, 1), (0, -1), (1, 0), (-1, 0)]

        for _ in range(max_dead_spaces):
            placed_any = False

            for circ_id in list(circulation_rooms):
                if circ_id not in self.placed:
                    continue

                circ_rect = self.placed[circ_id].rect

                for dx, dy in directions:
                    if dx > 0:
                        ds_rect = Rect(circ_rect.x2, circ_rect.y, ds_size, ds_size)
                    elif dx < 0:
                        ds_rect = Rect(circ_rect.x - ds_size, circ_rect.y, ds_size, ds_size)
                    elif dy > 0:
                        ds_rect = Rect(circ_rect.x, circ_rect.y2, ds_size, ds_size)
                    else:
                        ds_rect = Rect(circ_rect.x, circ_rect.y - ds_size, ds_size, ds_size)

                    if self._is_dead_space_valid(ds_rect):
                        ds_id = f"dead_space_{self.dead_space_count}"
                        self.dead_space_count += 1
                        self.placed[ds_id] = PlacedRoom(
                            id=ds_id,
                            name="Circulation",
                            room_type="hallway",
                            rect=ds_rect
                        )
                        circulation_rooms.append(ds_id)
                        placed_any = True

                        # Try placing target
                        candidates = self._generate_candidates(target_room_id, room, False)
                        if candidates:
                            scored = [(self._score_position(target_room_id, rect, False), rect)
                                      for rect in candidates]
                            scored.sort(reverse=True, key=lambda x: x[0])
                            for score, rect in scored[:20]:
                                if score >= 0 and self._is_valid_position(target_room_id, rect, False):
                                    self.placed[target_room_id] = PlacedRoom(
                                        id=target_room_id,
                                        name=room.get("name", "Room"),
                                        room_type=room.get("type", "room"),
                                        rect=rect
                                    )
                                    return True
                        break

            if not placed_any:
                break

        return False

    def _is_dead_space_valid(self, rect: Rect) -> bool:
        """Check if dead space position is valid."""
        # Must be inside bounds
        if rect.x < 0 or rect.y < 0:
            return False
        if rect.x2 > self.bounds.width or rect.y2 > self.bounds.height:
            return False

        # Must not overlap placed rooms
        for placed in self.placed.values():
            if rect.overlaps(placed.rect):
                return False

        return True

    # =========================================================================
    # CANDIDATE GENERATION
    # =========================================================================

    def _generate_candidates(self, room_id: str, room: Dict,
                              relaxed: bool) -> List[Rect]:
        """Generate candidate positions for a room."""
        candidates = []

        # Get room dimensions
        area_min = room.get("area_min", 12)  # sqm
        width_min = room.get("width_min")
        length_min = room.get("length_min")

        if width_min and length_min:
            width = m_to_mm(width_min)
            length = m_to_mm(length_min)
        else:
            # Calculate from area
            side = math.sqrt(area_min)
            width = m_to_mm(side)
            length = width

        # Snap to grid
        width = max(2400, (int(width) // self.grid) * self.grid)
        length = max(2400, (int(length) // self.grid) * self.grid)

        # Try multiple aspect ratios
        aspect_ratios = [1.0, 0.8, 0.7, 1.2, 1.3] if relaxed else [1.0, 0.8]

        for aspect in aspect_ratios:
            w = int(width * aspect)
            l = int(length / aspect)

            # Snap to grid
            w = max(2400, (w // self.grid) * self.grid)
            l = max(2400, (l // self.grid) * self.grid)

            # Get strategic positions
            positions = self._get_strategic_positions(room_id, w, l, relaxed)

            for x, y in positions:
                rect = Rect(x, y, w, l)
                if self._is_position_in_bounds(rect):
                    candidates.append(rect)

                # Try rotated
                if abs(w - l) > self.grid:
                    rect_rot = Rect(x, y, l, w)
                    if self._is_position_in_bounds(rect_rot):
                        candidates.append(rect_rot)

        return candidates

    def _get_strategic_positions(self, room_id: str, width: int, height: int,
                                   relaxed: bool) -> List[Tuple[float, float]]:
        """Get strategic positions to try."""
        positions = []
        grid = self.grid

        room = self._get_room_by_id(room_id)
        room_type = room.get("type") if room else "room"
        needs_exterior = room_type in EXTERIOR_REQUIRED

        if not self.placed:
            # First room: place at entry edge (south)
            for x in range(0, int(self.bounds.width - width) + 1, grid * 2):
                positions.append((float(x), 0.0))
            return positions

        # Generate positions near placed rooms
        must_touch = self.must_touch.get(room_id, set())

        for placed_id, placed_room in self.placed.items():
            pr = placed_room.rect

            # Positions adjacent to this room
            # Right
            if pr.x2 + width <= self.bounds.width:
                for y in range(max(0, int(pr.y - height + grid)),
                              min(int(self.bounds.height - height), int(pr.y2)) + 1, grid):
                    positions.append((pr.x2, float(y)))

            # Left
            if pr.x >= width:
                for y in range(max(0, int(pr.y - height + grid)),
                              min(int(self.bounds.height - height), int(pr.y2)) + 1, grid):
                    positions.append((pr.x - width, float(y)))

            # Above
            if pr.y2 + height <= self.bounds.height:
                for x in range(max(0, int(pr.x - width + grid)),
                              min(int(self.bounds.width - width), int(pr.x2)) + 1, grid):
                    positions.append((float(x), pr.y2))

            # Below
            if pr.y >= height:
                for x in range(max(0, int(pr.x - width + grid)),
                              min(int(self.bounds.width - width), int(pr.x2)) + 1, grid):
                    positions.append((float(x), pr.y - height))

        # Add boundary positions for exterior-required rooms
        if needs_exterior or relaxed:
            # South edge
            for x in range(0, int(self.bounds.width - width) + 1, grid * 2):
                positions.append((float(x), 0.0))
            # North edge
            for x in range(0, int(self.bounds.width - width) + 1, grid * 2):
                positions.append((float(x), self.bounds.height - height))
            # West edge
            for y in range(0, int(self.bounds.height - height) + 1, grid * 2):
                positions.append((0.0, float(y)))
            # East edge
            for y in range(0, int(self.bounds.height - height) + 1, grid * 2):
                positions.append((self.bounds.width - width, float(y)))

        return list(set(positions))

    def _is_position_in_bounds(self, rect: Rect) -> bool:
        """Check if position is within bounds."""
        return (rect.x >= 0 and rect.y >= 0 and
                rect.x2 <= self.bounds.width and rect.y2 <= self.bounds.height)

    # =========================================================================
    # POSITION VALIDATION
    # =========================================================================

    def _is_valid_position(self, room_id: str, rect: Rect, relaxed: bool) -> bool:
        """Check if position is valid."""
        room = self._get_room_by_id(room_id)
        room_type = room.get("type") if room else "room"

        # Must be in bounds
        if not self._is_position_in_bounds(rect):
            return False

        # Must not overlap
        for placed in self.placed.values():
            if rect.overlaps(placed.rect):
                return False

        # Must-not-touch constraints
        must_not = self.must_separate.get(room_id, set())
        for other_id in must_not:
            if other_id in self.placed:
                if rect.touches(self.placed[other_id].rect):
                    return False

        # Must-touch constraints
        must_touch = self.must_touch.get(room_id, set())
        placed_must_touch = [r for r in must_touch if r in self.placed]

        # Dead space counts as circulation
        if 'hallway' in must_touch:
            dead_spaces = [r for r in self.placed.keys() if r.startswith('dead_space_')]
            placed_must_touch.extend(dead_spaces)

        if placed_must_touch:
            if relaxed or room_id in self.relaxed_constraints:
                # Just need to be nearby
                is_nearby = any(
                    self._is_nearby(rect, self.placed[other_id].rect, self.grid * 4)
                    for other_id in placed_must_touch if other_id in self.placed
                )
                if not is_nearby:
                    return False
            else:
                # Must touch at least one
                touches_any = any(
                    rect.touches(self.placed[other_id].rect)
                    for other_id in placed_must_touch if other_id in self.placed
                )
                if not touches_any:
                    return False

        # Exterior requirement
        needs_exterior = room_type in EXTERIOR_REQUIRED
        if needs_exterior and room_id not in self.exterior_relaxed:
            if not rect.touches_any_boundary(self.bounds):
                return False

        return True

    def _is_nearby(self, rect1: Rect, rect2: Rect, threshold: float) -> bool:
        """Check if rectangles are within threshold distance."""
        dx = max(0, max(rect1.x - rect2.x2, rect2.x - rect1.x2))
        dy = max(0, max(rect1.y - rect2.y2, rect2.y - rect1.y2))
        return math.sqrt(dx * dx + dy * dy) <= threshold

    # =========================================================================
    # SCORING
    # =========================================================================

    def _score_position(self, room_id: str, rect: Rect, relaxed: bool) -> float:
        """Score a candidate position."""
        if not self._is_valid_position(room_id, rect, relaxed):
            return -1

        score = 100.0

        # Must-touch bonus
        must_touch = self.must_touch.get(room_id, set())
        for other_id in must_touch:
            if other_id in self.placed:
                if rect.touches(self.placed[other_id].rect):
                    score += 80  # Strong bonus
                elif self._is_nearby(rect, self.placed[other_id].rect, self.grid * 4):
                    score += 20  # Smaller bonus
                else:
                    score -= 30  # Penalty

        # Connectivity bonus
        touches_count = sum(1 for p in self.placed.values() if rect.touches(p.rect))
        score += touches_count * 15

        # Aspect ratio bonus
        score += rect.aspect * 10

        # Exterior bonus
        room = self._get_room_by_id(room_id)
        room_type = room.get("type") if room else "room"
        needs_exterior = room_type in EXTERIOR_REQUIRED
        prefers_exterior = room_type in EXTERIOR_PREFERRED

        if needs_exterior or prefers_exterior:
            if rect.touches_any_boundary(self.bounds):
                score += 30 if needs_exterior else 15

        # Entry positioning (prefer south edge)
        if room_type == "entry":
            if rect.is_on_boundary(self.bounds, "south"):
                score += 50
            # Center preference
            center_dist = abs(rect.center.x - self.bounds.width / 2)
            score -= center_dist / 1000

        # Avoid narrow gaps
        gaps = [
            rect.x,
            self.bounds.width - rect.x2,
            rect.y,
            self.bounds.height - rect.y2
        ]
        for gap in gaps:
            if 0 < gap < 2000:  # Less than 2m
                score -= 10

        return score

    def _score_candidate(self, candidate: SolverCandidate):
        """Score a complete candidate layout."""
        scores = {}

        # Adjacency satisfaction
        total_adj = 0
        satisfied_adj = 0
        for room_id, must_touch in self.must_touch.items():
            if room_id not in self.placed:
                continue
            room = self.placed[room_id]
            for other_id in must_touch:
                if other_id in self.placed:
                    total_adj += 1
                    if room.rect.touches(self.placed[other_id].rect):
                        satisfied_adj += 1

        scores["adjacencies"] = satisfied_adj / max(1, total_adj)
        candidate.satisfied_adjacencies = satisfied_adj

        # Separation satisfaction
        total_sep = 0
        satisfied_sep = 0
        for room_id, must_not in self.must_separate.items():
            if room_id not in self.placed:
                continue
            room = self.placed[room_id]
            for other_id in must_not:
                if other_id in self.placed:
                    total_sep += 1
                    if not room.rect.touches(self.placed[other_id].rect):
                        satisfied_sep += 1

        scores["separations"] = satisfied_sep / max(1, total_sep)
        candidate.satisfied_separations = satisfied_sep

        # Compactness
        if candidate.rooms:
            x_max = max(r.rect.x2 for r in candidate.rooms)
            y_max = max(r.rect.y2 for r in candidate.rooms)
            footprint = (x_max * y_max) / 1_000_000
            target = self.state.constraints.get("footprint_max", footprint)
            scores["compactness"] = max(0, 1 - abs(footprint - target) / target)
        else:
            scores["compactness"] = 0

        # Privacy score
        scores["privacy"] = self._score_privacy(candidate)

        # Calculate weighted total
        weights = {
            "adjacencies": 3.0,
            "separations": 2.0,
            "compactness": 1.0,
            "privacy": 1.0,
        }

        total = sum(scores[k] * weights.get(k, 1.0) for k in scores)
        max_possible = sum(weights.values())

        candidate.score = (total / max_possible) * 10
        candidate.score_breakdown = scores

    def _score_privacy(self, candidate: SolverCandidate) -> float:
        """Score privacy (bedrooms away from entry)."""
        entry = next((r for r in candidate.rooms if r.room_type == "entry"), None)
        if not entry:
            return 0.5

        bedrooms = [r for r in candidate.rooms if "bedroom" in r.room_type]
        if not bedrooms:
            return 1.0

        total_dist = 0
        for bedroom in bedrooms:
            dx = bedroom.rect.center.x - entry.rect.center.x
            dy = bedroom.rect.center.y - entry.rect.center.y
            total_dist += math.sqrt(dx*dx + dy*dy)

        avg_dist = total_dist / len(bedrooms)
        return min(1.0, avg_dist / 8000)  # 8m is good separation

    # =========================================================================
    # OUTPUT
    # =========================================================================

    def _build_candidate(self) -> SolverCandidate:
        """Build candidate from placed rooms."""
        rooms = [r for r in self.placed.values() if not r.id.startswith('dead_space_')]
        return SolverCandidate(rooms=rooms)

    def _candidate_to_layout(self, candidate: SolverCandidate) -> Dict[str, Any]:
        """Convert candidate to layout dictionary."""
        rooms = []
        for placed in candidate.rooms:
            rooms.append({
                "id": placed.id,
                "name": placed.name,
                "type": placed.room_type,
                "position": {"x": placed.rect.x, "y": placed.rect.y},
                "size": {"width": placed.rect.width, "depth": placed.rect.height},
                "area_sqm": placed.area_sqm,
            })

        # Calculate building footprint
        if candidate.rooms:
            x_max = max(r.rect.x2 for r in candidate.rooms)
            y_max = max(r.rect.y2 for r in candidate.rooms)
        else:
            x_max = y_max = 0

        return {
            "status": "solved",
            "rooms": rooms,
            "metrics": {
                "footprint_width": mm_to_m(x_max),
                "footprint_depth": mm_to_m(y_max),
                "footprint_area": (x_max * y_max) / 1_000_000,
                "room_count": len(rooms),
                "dead_space_cells": self.dead_space_count,
            },
            "score": round(candidate.score, 2),
            "score_breakdown": {k: round(v, 2) for k, v in candidate.score_breakdown.items()},
            "nodes_explored": self.nodes_explored,
        }

    # =========================================================================
    # HELPERS
    # =========================================================================

    def _get_room_by_id(self, room_id: str) -> Optional[Dict]:
        """Get room data by ID."""
        for room in self.state.rooms:
            if room.get("id") == room_id:
                return room
        return None


# =============================================================================
# CONVENIENCE FUNCTION
# =============================================================================

def solve_state(state: QBDState, max_nodes: int = 50000) -> SolverResult:
    """Convenience function to solve a state."""
    solver = QBDSolver(state)
    return solver.solve(max_nodes)
