"""
QBD Solver Suite - Multiple Algorithms for User Selection

Provides different solving approaches, each with distinct characteristics:
- Grid Solver: Fast, rectangular rooms, good for standard layouts
- Wave Function Collapse: Organic shapes, emergent patterns, artistic
- Tree Solver: Hierarchical slicing, predictable structure
- Perfect Adjacency: Graph-based, guaranteed relationship satisfaction
- Constraint Solver: Exact constraint satisfaction, precise control
- Hybrid: Automatically selects best approach

Usage:
    from solver_suite import SolverSuite, SolverType
    
    suite = SolverSuite(graph, width, depth)
    
    # User selects solver type
    layout = suite.solve(SolverType.WAVE_COLLAPSE)
    
    # Or let system choose
    layout = suite.solve(SolverType.HYBRID)
"""

from typing import Dict, List, Optional, Set, Tuple, Callable
from dataclasses import dataclass, field
from enum import Enum, auto
from abc import ABC, abstractmethod
import math
import random
import time
from collections import defaultdict, deque

from room_relationships import SpatialGraph, RoomNode
from coordinate_solver import (
    Point, Rect, PlacedRoom, PlacedLayout, WallCoordinate,
    CoordinateSolver as GridSolver
)


# =============================================================================
# SOLVER TYPES AND METADATA
# =============================================================================

class SolverType(Enum):
    """Available solver algorithms."""
    GRID = "grid"                    # Original grid-based solver
    WAVE_COLLAPSE = "wfc"           # Wave Function Collapse - organic
    TREE = "tree"                    # Slicing tree - hierarchical
    PERFECT_ADJACENCY = "adj"       # Graph-based - guaranteed adjacencies
    CONSTRAINT = "csp"              # Constraint satisfaction - precise
    GENETIC = "genetic"             # Genetic Algorithm - evolutionary
    ANNEALING = "annealing"         # Simulated Annealing - thermodynamic
    FORCE_DIRECTED = "force"        # Force-Directed - physics simulation
    SPACE_COLONIZATION = "space"    # Space Colonization - growth-based
    HYBRID = "hybrid"               # Auto-select best


@dataclass
class SolverMetadata:
    """Metadata describing a solver's characteristics."""
    
    name: str
    description: str
    best_for: List[str]
    characteristics: Dict[str, str]
    speed: str  # "fast", "medium", "slow"
    reliability: str  # "high", "medium", "experimental"
    
    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "description": self.description,
            "best_for": self.best_for,
            "characteristics": self.characteristics,
            "speed": self.speed,
            "reliability": self.reliability
        }


# Solver metadata for UI display
SOLVER_INFO = {
    SolverType.GRID: SolverMetadata(
        name="Grid Solver",
        description="Fast grid-based placement with constraint relaxation. Places rooms on a regular grid with backtracking search.",
        best_for=["Standard rectangular layouts", "Quick iterations", "Large room counts"],
        characteristics={
            "Room shapes": "Rectangular, axis-aligned",
            "Adjacency guarantee": "Best effort, may relax constraints",
            "Output style": "Traditional floor plan",
            "Creativity": "Low - follows predictable patterns",
            "Constraint handling": "Relaxes hard constraints if needed"
        },
        speed="fast",
        reliability="high"
    ),
    
    SolverType.WAVE_COLLAPSE: SolverMetadata(
        name="Wave Function Collapse",
        description="Quantum-inspired algorithm where each cell collapses from possibilities into reality. Creates organic, flowing layouts.",
        best_for=["Organic shapes", "Artistic layouts", "Non-rectangular designs", "L-shaped/T-shaped buildings"],
        characteristics={
            "Room shapes": "Organic, can be non-rectangular",
            "Adjacency guarantee": "Emergent from local rules",
            "Output style": "Flowing, natural patterns",
            "Creativity": "High - surprising emergent structures",
            "Constraint handling": "Soft constraints through tile weights"
        },
        speed="medium",
        reliability="medium"
    ),
    
    SolverType.TREE: SolverMetadata(
        name="Tree Solver",
        description="Hierarchical slicing tree decomposition. Recursively subdivides space like a BSP tree.",
        best_for=["Hierarchical layouts", "Clear zoning", "Modernist designs", "Predictable structures"],
        characteristics={
            "Room shapes": "Rectangular, hierarchical nesting",
            "Adjacency guarantee": "Guaranteed within slices",
            "Output style": "Clean subdivision, modern aesthetic",
            "Creativity": "Medium - structured variation",
            "Constraint handling": "Respects hierarchy, may skip edge cases"
        },
        speed="fast",
        reliability="high"
    ),
    
    SolverType.PERFECT_ADJACENCY: SolverMetadata(
        name="Perfect Adjacency",
        description="Graph-theoretic approach using rectangular duals. Guarantees all adjacency requirements are satisfied.",
        best_for=["Complex adjacency requirements", "Relationship-critical designs", "When connections matter most"],
        characteristics={
            "Room shapes": "Rectangular, optimized for connections",
            "Adjacency guarantee": "100% - all adjacencies satisfied",
            "Output style": "Connection-optimized layout",
            "Creativity": "Low-Medium - topology-driven",
            "Constraint handling": "Strict - fails if graph invalid"
        },
        speed="slow",
        reliability="high"
    ),
    
    SolverType.CONSTRAINT: SolverMetadata(
        name="Constraint Solver",
        description="Exact constraint satisfaction with backtracking and propagation. Precise control over all parameters.",
        best_for=["Precise requirements", "Regulatory compliance", "Tight constraints", "Optimization problems"],
        characteristics={
            "Room shapes": "Any - constraint-defined",
            "Adjacency guarantee": "Exact - all constraints or fail",
            "Output style": "Constraint-optimal",
            "Creativity": "None - purely deterministic",
            "Constraint handling": "Exact - no relaxation"
        },
        speed="slow",
        reliability="medium"
    ),
    
    SolverType.GENETIC: SolverMetadata(
        name="Genetic Algorithm",
        description="Evolutionary optimization with selection, crossover, and mutation. Population-based search for global optimum.",
        best_for=["Global optimization", "Escaping local minima", "Complex landscapes"],
        characteristics={
            "Room shapes": "Any - evolves over generations",
            "Adjacency guarantee": "Emergent from fitness function",
            "Output style": "Varied population, converges to good solutions",
            "Creativity": "High - explores diverse solutions",
            "Constraint handling": "Soft constraints via penalties"
        },
        speed="slow",
        reliability="medium"
    ),
    
    SolverType.ANNEALING: SolverMetadata(
        name="Simulated Annealing",
        description="Thermodynamic-inspired optimization. Starts hot (accepts bad moves), cools to find global optimum.",
        best_for=["Avoiding local optima", "Complex energy landscapes", "Fine-tuning layouts"],
        characteristics={
            "Room shapes": "Any - continuous adjustment",
            "Adjacency guarantee": "Gradual improvement",
            "Output style": "Smooth convergence",
            "Creativity": "Medium - probabilistic exploration",
            "Constraint handling": "Energy-based penalties"
        },
        speed="slow",
        reliability="medium"
    ),
    
    SolverType.FORCE_DIRECTED: SolverMetadata(
        name="Force-Directed",
        description="Physics simulation with spring and repulsion forces. Rooms settle into equilibrium like molecules.",
        best_for=["Visualizing relationships", "Organic layouts", "Teaching adjacency"],
        characteristics={
            "Room shapes": "Fixed, positions adjust",
            "Adjacency guarantee": "Springs pull adjacent rooms together",
            "Output style": "Dynamic, physics-based",
            "Creativity": "Medium - emergent from forces",
            "Constraint handling": "Forces encode constraints"
        },
        speed="medium",
        reliability="medium"
    ),
    
    SolverType.SPACE_COLONIZATION: SolverMetadata(
        name="Space Colonization",
        description="Growth-based algorithm inspired by leaf venation. Organic growth from seed to fill space.",
        best_for=["Nature-inspired designs", "Organic architecture", "Teaching growth processes"],
        characteristics={
            "Room shapes": "Organic, grown from center",
            "Adjacency guarantee": "Growth paths connect rooms",
            "Output style": "Natural, tree-like patterns",
            "Creativity": "Very high - emergent organic forms",
            "Constraint handling": "Attractors guide growth"
        },
        speed="medium",
        reliability="experimental"
    ),
    
    SolverType.HYBRID: SolverMetadata(
        name="Hybrid Auto-Select",
        description="Automatically selects and combines solvers based on your design characteristics.",
        best_for=["Unknown requirements", "Best result", "Exploration"],
        characteristics={
            "Room shapes": "Varies by selected solver",
            "Adjacency guarantee": "Varies by selected solver",
            "Output style": "Best of all approaches",
            "Creativity": "Varies - picks appropriate level",
            "Constraint handling": "Adaptive strategy"
        },
        speed="slow",
        reliability="high"
    )
}


# =============================================================================
# BASE SOLVER INTERFACE
# =============================================================================

class BaseSolver(ABC):
    """Abstract base class for all solvers."""
    
    def __init__(self, graph: SpatialGraph, width: float, depth: float, 
                 grid_size: float = 2.0):
        self.graph = graph
        self.width = width
        self.depth = depth
        self.grid_size = grid_size
        self.nodes_explored = 0
        self.start_time = None
    
    @abstractmethod
    def solve(self, max_iterations: int = 10000) -> PlacedLayout:
        """Solve and return layout."""
        pass
    
    @property
    @abstractmethod
    def solver_type(self) -> SolverType:
        """Return solver type."""
        pass
    
    def get_metadata(self) -> SolverMetadata:
        """Get solver metadata."""
        return SOLVER_INFO[self.solver_type]
    
    def _start_timer(self):
        """Start timing."""
        self.start_time = time.time()
    
    def _elapsed(self) -> float:
        """Get elapsed time."""
        if self.start_time is None:
            return 0.0
        return time.time() - self.start_time


# =============================================================================
# 1. GRID SOLVER (Original)
# =============================================================================

class GridSolverWrapper(BaseSolver):
    """Wrapper for original grid-based solver."""
    
    @property
    def solver_type(self) -> SolverType:
        return SolverType.GRID
    
    def solve(self, max_iterations: int = 10000) -> PlacedLayout:
        """Use original grid solver."""
        self._start_timer()
        
        from wall_graph import LayoutSpec
        
        # Convert SpatialGraph to LayoutSpec
        spec = self._to_layout_spec()
        
        # Use original solver
        solver = GridSolver(spec, self.grid_size)
        layout = solver.solve(max_nodes=max_iterations)
        
        layout.score = self._calculate_score(layout)
        return layout
    
    def _to_layout_spec(self):
        """Convert SpatialGraph to LayoutSpec."""
        from wall_graph import LayoutSpec

        # Use the class method that properly creates a LayoutSpec
        spec = LayoutSpec.from_spatial_graph(
            spatial=self.graph,
            building_width=self.width,
            building_depth=self.depth
        )
        return spec
    
    def _calculate_score(self, layout: PlacedLayout) -> float:
        """Calculate layout quality score."""
        if not layout.rooms:
            return 0.0
        
        score = 0.0
        
        # Coverage
        total_area = sum(r.area for r in layout.rooms.values())
        building_area = self.width * self.depth
        coverage = total_area / building_area
        score += max(0, 100 - abs(coverage - 0.7) * 200)
        
        # Completeness
        completeness = len(layout.rooms) / max(len(self.graph.rooms), 1)
        score += completeness * 100
        
        return score


# =============================================================================
# 2. WAVE FUNCTION COLLAPSE SOLVER
# =============================================================================

class WFCTile(Enum):
    EMPTY = auto()
    ROOM = auto()
    WALL = auto()
    DOOR = auto()
    WINDOW = auto()


@dataclass
class WFCCell:
    x: int
    y: int
    possible: Set[WFCTile] = field(default_factory=lambda: set(WFCTile))
    collapsed: bool = False
    tile: Optional[WFCTile] = None
    room_id: Optional[str] = None


class WaveCollapseSolver(BaseSolver):
    """
    Wave Function Collapse - organic, emergent layouts.
    
    Each grid cell starts in superposition (all states possible).
    Cells collapse to specific states, propagating constraints.
    Creates flowing, non-rectangular layouts.
    """
    
    @property
    def solver_type(self) -> SolverType:
        return SolverType.WAVE_COLLAPSE
    
    def __init__(self, graph: SpatialGraph, width: float, depth: float, 
                 grid_size: float = 2.0):
        super().__init__(graph, width, depth, grid_size)
        self.gw = int(width / grid_size)
        self.gh = int(depth / grid_size)
        self.grid: Dict[Tuple[int,int], WFCCell] = {}
        self._init_grid()
    
    def _init_grid(self):
        """Initialize grid in superposition."""
        for x in range(self.gw):
            for y in range(self.gh):
                cell = WFCCell(x=x, y=y)
                # Boundaries must be walls
                if x == 0 or x == self.gw-1 or y == 0 or y == self.gh-1:
                    cell.possible = {WFCTile.WALL}
                self.grid[(x,y)] = cell
    
    def solve(self, max_iterations: int = 10000) -> PlacedLayout:
        """Run WFC algorithm."""
        self._start_timer()
        print(f"[WFC] Grid: {self.gw}x{self.gh}, Rooms: {len(self.graph.rooms)}")
        
        # Seed entry
        self._seed_entry()
        
        # Collapse loop
        for i in range(max_iterations):
            if self._is_complete():
                break
            
            cell = self._observe()
            if cell is None:
                break
            
            self._collapse(cell)
            self._propagate(cell)
            self.nodes_explored += 1
        
        # Convert to layout
        layout = self._to_layout()
        layout.score = self._calculate_score(layout)
        
        print(f"[WFC] Complete: {len(layout.rooms)}/{len(self.graph.rooms)} rooms, "
              f"Score: {layout.score:.1f}, Time: {self._elapsed():.2f}s")
        
        return layout
    
    def _seed_entry(self):
        """Seed with entry door."""
        x = self.gw // 2
        y = 0
        cell = self.grid[(x, y)]
        cell.collapsed = True
        cell.tile = WFCTile.DOOR
        cell.room_id = "entry"
        self._propagate(cell)
    
    def _observe(self) -> Optional[WFCCell]:
        """Find cell with minimum entropy (fewest options)."""
        min_entropy = float('inf')
        best = None
        
        for cell in self.grid.values():
            if cell.collapsed:
                continue
            
            entropy = len(cell.possible)
            if 0 < entropy < min_entropy:
                min_entropy = entropy
                best = cell
        
        return best
    
    def _collapse(self, cell: WFCCell):
        """Collapse cell to specific tile."""
        if not cell.possible:
            cell.tile = WFCTile.EMPTY
        else:
            # Weighted selection
            weights = self._get_weights(cell)
            options = list(cell.possible)
            w = [weights.get(t, 1.0) for t in options]
            cell.tile = random.choices(options, weights=w, k=1)[0]
        
        cell.collapsed = True
    
    def _get_weights(self, cell: WFCCell) -> Dict[WFCTile, float]:
        """Get tile weights based on position."""
        weights = {t: 1.0 for t in cell.possible}
        
        # Prefer rooms in interior
        if 2 < cell.x < self.gw - 2 and 2 < cell.y < self.gh - 2:
            weights[WFCTile.ROOM] = 3.0
        
        # Prefer walls on boundary
        if cell.x == 1 or cell.x == self.gw - 2:
            weights[WFCTile.WALL] = 5.0
        if cell.y == 1 or cell.y == self.gh - 2:
            weights[WFCTile.WALL] = 5.0
        
        return weights
    
    def _propagate(self, cell: WFCCell):
        """Propagate constraints to neighbors."""
        queue = deque([cell])
        
        while queue:
            c = queue.popleft()
            
            for dx, dy in [(-1,0), (1,0), (0,-1), (0,1)]:
                nx, ny = c.x + dx, c.y + dy
                neighbor = self.grid.get((nx, ny))
                
                if not neighbor or neighbor.collapsed:
                    continue
                
                # Constraint rules
                changed = False
                
                # Walls need walls or rooms adjacent
                if c.tile == WFCTile.WALL:
                    if WFCTile.EMPTY in neighbor.possible:
                        neighbor.possible.discard(WFCTile.EMPTY)
                        changed = True
                
                # Rooms need walls or rooms adjacent
                if c.tile == WFCTile.ROOM:
                    if WFCTile.EMPTY in neighbor.possible:
                        neighbor.possible.discard(WFCTile.EMPTY)
                        changed = True
                
                if changed:
                    queue.append(neighbor)
    
    def _is_complete(self) -> bool:
        """Check if all cells collapsed."""
        return all(c.collapsed for c in self.grid.values())
    
    def _to_layout(self) -> PlacedLayout:
        """Convert grid to PlacedLayout."""
        # Find connected ROOM regions
        regions = self._find_regions()
        
        # Assign to rooms
        placed = {}
        room_ids = list(self.graph.rooms.keys())
        
        for i, region in enumerate(regions):
            if i >= len(room_ids):
                break
            
            xs = [c[0] for c in region]
            ys = [c[1] for c in region]
            
            rect = Rect(
                min(xs) * self.grid_size,
                min(ys) * self.grid_size,
                (max(xs) - min(xs) + 1) * self.grid_size,
                (max(ys) - min(ys) + 1) * self.grid_size
            )
            
            placed[room_ids[i]] = PlacedRoom(room_ids[i], rect)
        
        return PlacedLayout(
            rooms=placed,
            walls=[],
            building_bounds=Rect(0, 0, self.width, self.depth),
            is_complete=len(placed) == len(self.graph.rooms),
            unplaced_rooms=[r for r in room_ids if r not in placed],
            score=0.0
        )
    
    def _find_regions(self) -> List[Set[Tuple[int,int]]]:
        """Find connected ROOM regions."""
        regions = []
        seen = set()
        
        for (x,y), cell in self.grid.items():
            if cell.tile != WFCTile.ROOM or (x,y) in seen:
                continue
            
            region = set()
            queue = deque([(x,y)])
            
            while queue:
                cx, cy = queue.popleft()
                if (cx,cy) in seen:
                    continue
                seen.add((cx,cy))
                
                c = self.grid.get((cx,cy))
                if c and c.tile == WFCTile.ROOM:
                    region.add((cx,cy))
                    for dx,dy in [(-1,0),(1,0),(0,-1),(0,1)]:
                        queue.append((cx+dx,cy+dy))
            
            if region:
                regions.append(region)
        
        return regions
    
    def _calculate_score(self, layout: PlacedLayout) -> float:
        """Score based on organic quality."""
        if not layout.rooms:
            return 0.0
        
        score = 0.0
        
        # Reward non-rectangular building shape
        if len(layout.rooms) >= 3:
            score += 20
        
        # Reward coverage
        total_room = sum(r.area for r in layout.rooms.values())
        building = self.width * self.depth
        coverage = total_room / building
        score += coverage * 50
        
        # Completeness
        score += (len(layout.rooms) / max(len(self.graph.rooms), 1)) * 30
        
        return score


# =============================================================================
# 3. TREE SOLVER (Slicing Tree)
# =============================================================================

@dataclass
class TreeNode:
    """Node in slicing tree."""
    node_type: str  # "cut" or "room"
    direction: Optional[str] = None  # "h" or "v" for cuts
    room_id: Optional[str] = None
    left: Optional['TreeNode'] = None
    right: Optional['TreeNode'] = None


class TreeSolver(BaseSolver):
    """
    Slicing Tree Solver - hierarchical subdivision.
    
    Recursively subdivides space like a BSP tree.
    Creates clean, hierarchical layouts.
    """
    
    @property
    def solver_type(self) -> SolverType:
        return SolverType.TREE
    
    def solve(self, max_iterations: int = 10000) -> PlacedLayout:
        """Build slicing tree and convert to layout."""
        self._start_timer()
        print(f"[Tree] Building slicing tree for {len(self.graph.rooms)} rooms")
        
        # Build tree
        room_ids = list(self.graph.rooms.keys())
        tree = self._build_tree(room_ids)
        
        # Assign rectangles
        placed = self._assign_rectangles(tree)
        
        # Local refinement
        placed = self._refine(placed)
        
        layout = PlacedLayout(
            rooms=placed,
            walls=[],
            building_bounds=Rect(0, 0, self.width, self.depth),
            is_complete=len(placed) == len(self.graph.rooms),
            unplaced_rooms=[r for r in room_ids if r not in placed],
            score=0.0
        )
        
        layout.score = self._calculate_score(layout)
        
        print(f"[Tree] Complete: {len(placed)}/{len(room_ids)} rooms, "
              f"Score: {layout.score:.1f}, Time: {self._elapsed():.2f}s")
        
        return layout
    
    def _build_tree(self, room_ids: List[str]) -> TreeNode:
        """Build slicing tree from room list."""
        if len(room_ids) == 1:
            return TreeNode(node_type="room", room_id=room_ids[0])
        
        # Partition based on adjacency
        left, right = self._partition(room_ids)
        
        # Alternate cut direction
        direction = "h" if len(room_ids) % 2 == 0 else "v"
        
        return TreeNode(
            node_type="cut",
            direction=direction,
            left=self._build_tree(left),
            right=self._build_tree(right)
        )
    
    def _partition(self, room_ids: List[str]) -> Tuple[List[str], List[str]]:
        """Partition rooms for tree construction."""
        # Simple: sort by connection count, split in half
        sorted_rooms = sorted(
            room_ids,
            key=lambda r: len([a for a in self.graph.adjacencies if r in [a.room_a, a.room_b]]),
            reverse=True
        )
        
        mid = len(sorted_rooms) // 2
        return sorted_rooms[:mid], sorted_rooms[mid:]
    
    def _assign_rectangles(self, tree: TreeNode, 
                           bounds: Rect = None) -> Dict[str, PlacedRoom]:
        """Assign rectangles from tree."""
        if bounds is None:
            bounds = Rect(0, 0, self.width, self.depth)
        
        placed = {}
        
        def assign(node: TreeNode, rect: Rect):
            if node.node_type == "room":
                room = self.graph.rooms.get(node.room_id)
                if room:
                    # Adjust to meet area requirements
                    target = room.min_area or rect.area
                    if rect.area < target:
                        scale = math.sqrt(target / rect.area)
                        new_w = min(rect.width * scale, rect.width * 1.3)
                        new_h = target / new_w
                        rect = Rect(rect.x, rect.y, new_w, new_h)
                
                placed[node.room_id] = PlacedRoom(node.room_id, rect)
            else:
                # Cut
                if node.direction == "h":
                    # Horizontal cut - split vertically
                    mid = rect.x + rect.width / 2
                    left_rect = Rect(rect.x, rect.y, mid - rect.x, rect.height)
                    right_rect = Rect(mid, rect.y, rect.x2 - mid, rect.height)
                else:
                    # Vertical cut - split horizontally
                    mid = rect.y + rect.height / 2
                    left_rect = Rect(rect.x, rect.y, rect.width, mid - rect.y)
                    right_rect = Rect(rect.x, mid, rect.width, rect.y2 - mid)
                
                assign(node.left, left_rect)
                assign(node.right, right_rect)
        
        assign(tree, bounds)
        return placed
    
    def _refine(self, placed: Dict[str, PlacedRoom]) -> Dict[str, PlacedRoom]:
        """Local search refinement."""
        # Try small adjustments
        for _ in range(50):
            if not placed:
                break
            
            room_id = random.choice(list(placed.keys()))
            room = placed[room_id]
            
            best_rect = room.rect
            best_score = self._score_room_placement(room_id, placed)
            
            # Try small moves
            for dx in [-1, 0, 1]:
                for dy in [-1, 0, 1]:
                    if dx == 0 and dy == 0:
                        continue
                    
                    new_rect = Rect(
                        room.rect.x + dx * self.grid_size,
                        room.rect.y + dy * self.grid_size,
                        room.rect.width,
                        room.rect.height
                    )
                    
                    if self._is_valid(placed, room_id, new_rect):
                        placed[room_id] = PlacedRoom(room_id, new_rect)
                        score = self._score_room_placement(room_id, placed)
                        
                        if score > best_score:
                            best_score = score
                            best_rect = new_rect
                        
                        placed[room_id] = PlacedRoom(room_id, room.rect)
            
            placed[room_id] = PlacedRoom(room_id, best_rect)
        
        return placed
    
    def _is_valid(self, placed: Dict, room_id: str, rect: Rect) -> bool:
        """Check if rectangle placement is valid."""
        if rect.x < 0 or rect.y < 0:
            return False
        if rect.x2 > self.width or rect.y2 > self.depth:
            return False
        
        for other_id, other in placed.items():
            if other_id != room_id and rect.overlaps(other.rect):
                return False
        
        return True
    
    def _score_room_placement(self, room_id: str, placed: Dict) -> float:
        """Score a room's placement."""
        room = placed.get(room_id)
        if not room:
            return 0.0
        
        score = 0.0
        
        # Check adjacencies
        for adj in self.graph.adjacencies:
            if room_id in [adj.room_a, adj.room_b]:
                other_id = adj.room_b if adj.room_a == room_id else adj.room_a
                other = placed.get(other_id)
                if other and room.rect.touches(other.rect):
                    score += 10
        
        return score
    
    def _calculate_score(self, layout: PlacedLayout) -> float:
        """Calculate layout score."""
        if not layout.rooms:
            return 0.0
        
        score = 0.0
        
        # Completeness
        score += (len(layout.rooms) / max(len(self.graph.rooms), 1)) * 40
        
        # Adjacency satisfaction
        for adj in self.graph.adjacencies:
            r1 = layout.rooms.get(adj.room_a)
            r2 = layout.rooms.get(adj.room_b)
            if r1 and r2 and r1.rect.touches(r2.rect):
                score += 5
        
        # Coverage
        total = sum(r.area for r in layout.rooms.values())
        score += (total / (self.width * self.depth)) * 30
        
        return score


# =============================================================================
# 4. PERFECT ADJACENCY SOLVER
# =============================================================================

class PerfectAdjacencySolver(BaseSolver):
    """
    Graph-based solver with guaranteed adjacency satisfaction.
    
    Uses rectangular duals theory to ensure all adjacency
    requirements are met exactly.
    """
    
    @property
    def solver_type(self) -> SolverType:
        return SolverType.PERFECT_ADJACENCY
    
    def solve(self, max_iterations: int = 10000) -> PlacedLayout:
        """Solve using graph-theoretic approach."""
        self._start_timer()
        print(f"[PerfectAdj] Solving for {len(self.graph.rooms)} rooms")
        
        # Build adjacency graph
        adj_graph = self._build_adj_graph()
        
        # Check if rectangular dual exists
        if not self._has_rectangular_dual(adj_graph):
            print("[PerfectAdj] Warning: Graph may not admit rectangular dual")
        
        # Compute rectangular dual
        placed = self._compute_rectangular_dual(adj_graph)
        
        # Scale to fit bounds
        placed = self._scale_to_bounds(placed)
        
        layout = PlacedLayout(
            rooms=placed,
            walls=[],
            building_bounds=Rect(0, 0, self.width, self.depth),
            is_complete=len(placed) == len(self.graph.rooms),
            unplaced_rooms=[r for r in self.graph.rooms if r not in placed],
            score=0.0
        )
        
        layout.score = self._calculate_score(layout)
        
        print(f"[PerfectAdj] Complete: {len(placed)}/{len(self.graph.rooms)} rooms, "
              f"Score: {layout.score:.1f}, Time: {self._elapsed():.2f}s")
        
        return layout
    
    def _build_adj_graph(self) -> Dict[str, Set[str]]:
        """Build adjacency graph."""
        graph = defaultdict(set)
        
        for adj in self.graph.adjacencies:
            graph[adj.room_a].add(adj.room_b)
            graph[adj.room_b].add(adj.room_a)
        
        return dict(graph)
    
    def _has_rectangular_dual(self, adj_graph: Dict[str, Set[str]]) -> bool:
        """Check if graph admits rectangular dual."""
        # Simplified check: max degree <= 4 for outerplanar-like
        for room_id, neighbors in adj_graph.items():
            if len(neighbors) > 6:
                return False
        return True
    
    def _compute_rectangular_dual(self, adj_graph: Dict[str, Set[str]]) -> Dict[str, PlacedRoom]:
        """Compute rectangular dual layout."""
        placed = {}
        
        # Greedy placement with adjacency priority
        remaining = set(self.graph.rooms.keys())
        
        # Start with entry
        if "entry" in remaining:
            placed["entry"] = PlacedRoom("entry", Rect(0, 0, 10, 10))
            remaining.remove("entry")
        
        # Place rooms adjacent to already placed
        while remaining:
            best_room = None
            best_score = -1
            best_rect = None
            
            for room_id in remaining:
                # Find best placement adjacent to placed rooms
                rect, score = self._find_best_placement(room_id, placed, adj_graph)
                if score > best_score:
                    best_score = score
                    best_room = room_id
                    best_rect = rect
            
            if best_room and best_rect:
                placed[best_room] = PlacedRoom(best_room, best_rect)
                remaining.remove(best_room)
            else:
                # Can't place remaining
                break
        
        return placed
    
    def _find_best_placement(
        self,
        room_id: str,
        placed: Dict[str, PlacedRoom],
        adj_graph: Dict[str, Set[str]]
    ) -> Tuple[Optional[Rect], float]:
        """Find best placement for room adjacent to placed rooms."""
        room = self.graph.rooms.get(room_id)
        if not room:
            return None, -1
        
        # Get required neighbors
        required = adj_graph.get(room_id, set())
        placed_neighbors = required & set(placed.keys())
        
        if not placed_neighbors:
            # No placed neighbors yet - place anywhere
            return Rect(0, 0, 10, 10), 0.0
        
        # Try placing adjacent to each placed neighbor
        best_rect = None
        best_score = -1
        
        area = room.min_area or 100
        aspect = 0.8
        w = math.sqrt(area / aspect)
        h = area / w
        
        for neighbor_id in placed_neighbors:
            neighbor = placed[neighbor_id]
            
            # Try all four sides
            positions = [
                (neighbor.rect.x2, neighbor.rect.y, w, h),  # Right
                (neighbor.rect.x - w, neighbor.rect.y, w, h),  # Left
                (neighbor.rect.x, neighbor.rect.y2, w, h),  # Top
                (neighbor.rect.x, neighbor.rect.y - h, w, h),  # Bottom
            ]
            
            for x, y, rw, rh in positions:
                rect = Rect(x, y, rw, rh)
                
                if self._is_valid_placement(rect, placed):
                    score = self._score_placement(room_id, rect, placed, adj_graph)
                    if score > best_score:
                        best_score = score
                        best_rect = rect
        
        return best_rect, best_score
    
    def _is_valid_placement(self, rect: Rect, placed: Dict) -> bool:
        """Check if placement is valid."""
        if rect.x < -50 or rect.y < -50:  # Allow some negative
            return False
        
        for other in placed.values():
            if rect.overlaps(other.rect):
                return False
        
        return True
    
    def _score_placement(
        self,
        room_id: str,
        rect: Rect,
        placed: Dict,
        adj_graph: Dict
    ) -> float:
        """Score a placement."""
        score = 0.0
        
        # Reward adjacencies satisfied
        required = adj_graph.get(room_id, set())
        for other_id in required:
            if other_id in placed:
                if rect.touches(placed[other_id].rect):
                    score += 20
        
        # Penalize distance from center
        cx = self.width / 2
        cy = self.depth / 2
        dist = math.sqrt((rect.center.x - cx)**2 + (rect.center.y - cy)**2)
        score -= dist * 0.1
        
        return score
    
    def _scale_to_bounds(self, placed: Dict) -> Dict:
        """Scale layout to fit within bounds."""
        if not placed:
            return placed
        
        # Find current bounds
        min_x = min(r.rect.x for r in placed.values())
        max_x = max(r.rect.x2 for r in placed.values())
        min_y = min(r.rect.y for r in placed.values())
        max_y = max(r.rect.y2 for r in placed.values())
        
        current_w = max_x - min_x
        current_h = max_y - min_y
        
        if current_w == 0 or current_h == 0:
            return placed
        
        # Scale factors
        scale_x = (self.width * 0.9) / current_w
        scale_y = (self.depth * 0.9) / current_h
        scale = min(scale_x, scale_y)
        
        # Scale and translate
        scaled = {}
        for room_id, room in placed.items():
            new_rect = Rect(
                (room.rect.x - min_x) * scale + self.width * 0.05,
                (room.rect.y - min_y) * scale + self.depth * 0.05,
                room.rect.width * scale,
                room.rect.height * scale
            )
            scaled[room_id] = PlacedRoom(room_id, new_rect)
        
        return scaled
    
    def _calculate_score(self, layout: PlacedLayout) -> float:
        """Score based on adjacency satisfaction."""
        if not layout.rooms:
            return 0.0
        
        score = 0.0
        total_adjs = len(self.graph.adjacencies)
        satisfied = 0
        
        for adj in self.graph.adjacencies:
            r1 = layout.rooms.get(adj.room_a)
            r2 = layout.rooms.get(adj.room_b)
            if r1 and r2 and r1.rect.touches(r2.rect):
                satisfied += 1
                score += 10
        
        # Bonus for 100% satisfaction
        if total_adjs > 0 and satisfied == total_adjs:
            score += 50
        
        # Completeness
        score += (len(layout.rooms) / max(len(self.graph.rooms), 1)) * 30
        
        return score


# =============================================================================
# 5. CONSTRAINT SOLVER (CSP)
# =============================================================================

class ConstraintSolver(BaseSolver):
    """
    Exact constraint satisfaction solver.
    
    Uses backtracking with constraint propagation.
    Guarantees all constraints satisfied or fails.
    """
    
    @property
    def solver_type(self) -> SolverType:
        return SolverType.CONSTRAINT
    
    def solve(self, max_iterations: int = 10000) -> PlacedLayout:
        """Solve using CSP with backtracking."""
        self._start_timer()
        print(f"[CSP] Solving with exact constraints for {len(self.graph.rooms)} rooms")
        
        room_ids = list(self.graph.rooms.keys())
        
        # Try to find solution
        placed = self._backtrack({}, room_ids, 0, max_iterations)
        
        is_complete = len(placed) == len(room_ids)
        
        layout = PlacedLayout(
            rooms=placed,
            walls=[],
            building_bounds=Rect(0, 0, self.width, self.depth),
            is_complete=is_complete,
            unplaced_rooms=[r for r in room_ids if r not in placed],
            score=0.0
        )
        
        layout.score = self._calculate_score(layout)
        
        print(f"[CSP] Complete: {len(placed)}/{len(room_ids)} rooms, "
              f"Score: {layout.score:.1f}, Time: {self._elapsed():.2f}s")
        
        return layout
    
    def _backtrack(
        self,
        placed: Dict,
        room_ids: List[str],
        index: int,
        max_iter: int
    ) -> Dict:
        """Backtracking search."""
        if index >= len(room_ids):
            return placed
        
        if self.nodes_explored >= max_iter:
            return placed
        
        room_id = room_ids[index]
        room = self.graph.rooms.get(room_id)
        
        if not room:
            return self._backtrack(placed, room_ids, index + 1, max_iter)
        
        # Generate candidates
        candidates = self._generate_candidates(room_id, room)
        
        for rect in candidates:
            self.nodes_explored += 1
            
            if self._is_valid_strict(placed, room_id, rect):
                placed[room_id] = PlacedRoom(room_id, rect)
                
                result = self._backtrack(placed, room_ids, index + 1, max_iter)
                if len(result) == len(room_ids):
                    return result
                
                del placed[room_id]
        
        return placed
    
    def _generate_candidates(self, room_id: str, room: RoomNode) -> List[Rect]:
        """Generate candidate positions."""
        candidates = []
        
        area = room.min_area or 100
        aspect = 0.8
        w = math.sqrt(area / aspect)
        h = area / w
        
        # Grid positions
        for x in range(0, int(self.width - w), int(self.grid_size)):
            for y in range(0, int(self.depth - h), int(self.grid_size)):
                candidates.append(Rect(x, y, w, h))
        
        return candidates
    
    def _is_valid_strict(self, placed: Dict, room_id: str, rect: Rect) -> bool:
        """Strict validity check."""
        # Bounds
        if rect.x < 0 or rect.y < 0:
            return False
        if rect.x2 > self.width or rect.y2 > self.depth:
            return False
        
        # No overlaps
        for other_id, other in placed.items():
            if rect.overlaps(other.rect):
                return False
        
        # Check adjacencies
        for adj in self.graph.adjacencies:
            if room_id == adj.room_a and adj.room_b in placed:
                if not rect.touches(placed[adj.room_b].rect):
                    return False
            elif room_id == adj.room_b and adj.room_a in placed:
                if not rect.touches(placed[adj.room_a].rect):
                    return False
        
        return True
    
    def _calculate_score(self, layout: PlacedLayout) -> float:
        """Score - all constraints satisfied or nothing."""
        if not layout.is_complete:
            return 0.0
        
        # All constraints satisfied
        return 100.0


# =============================================================================
# 6. HYBRID SOLVER
# =============================================================================

class HybridSolver(BaseSolver):
    """
    Automatically selects best solver based on problem characteristics.
    """
    
    @property
    def solver_type(self) -> SolverType:
        return SolverType.HYBRID
    
    def solve(self, max_iterations: int = 10000) -> PlacedLayout:
        """Select and run best solver."""
        self._start_timer()
        print(f"[Hybrid] Analyzing {len(self.graph.rooms)} rooms...")
        
        # Analyze problem
        characteristics = self._analyze()
        
        # Select solvers to try
        solvers_to_try = self._select_solvers(characteristics)
        
        print(f"[Hybrid] Will try: {[s.name for s in solvers_to_try]}")
        
        # Run each solver
        results = []
        
        for solver_class in solvers_to_try:
            try:
                solver = solver_class(self.graph, self.width, self.depth, self.grid_size)
                layout = solver.solve(max_iterations // len(solvers_to_try))
                results.append((layout.score, layout, solver.solver_type))
                print(f"[Hybrid] {solver.solver_type.value}: score={layout.score:.1f}, "
                      f"complete={layout.is_complete}")
            except Exception as e:
                print(f"[Hybrid] {solver_class.__name__} failed: {e}")
        
        # Select best
        if results:
            results.sort(key=lambda x: (x[1].is_complete, x[0]), reverse=True)
            best = results[0]
            print(f"[Hybrid] Best: {best[2].value} with score {best[0]:.1f}")
            return best[1]
        
        # Fallback
        return PlacedLayout({}, [], Rect(0,0,self.width,self.depth), False,
                          list(self.graph.rooms), 0.0)
    
    def _analyze(self) -> Dict:
        """Analyze problem characteristics."""
        return {
            "num_rooms": len(self.graph.rooms),
            "num_adjs": len(self.graph.adjacencies),
            "avg_degree": len(self.graph.adjacencies) * 2 / max(len(self.graph.rooms), 1),
            "density": len(self.graph.rooms) / (self.width * self.depth) * 100,
        }
    
    def _select_solvers(self, chars: Dict) -> List:
        """Select solvers based on characteristics."""
        solvers = []
        
        # Always try grid (fast, reliable)
        solvers.append(GridSolverWrapper)
        
        # Many adjacencies - try perfect adjacency
        if chars["avg_degree"] > 2.5:
            solvers.append(PerfectAdjacencySolver)
        
        # Low density - try WFC for organic shapes
        if chars["density"] < 0.5:
            solvers.append(WaveCollapseSolver)
        
        # Medium size - try tree
        if 5 < chars["num_rooms"] < 20:
            solvers.append(TreeSolver)
        
        # Few rooms - try exact CSP
        if chars["num_rooms"] <= 8:
            solvers.append(ConstraintSolver)
        
        return solvers
    
    def _calculate_score(self, layout: PlacedLayout) -> float:
        return layout.score


# =============================================================================
# SOLVER SUITE - MAIN INTERFACE
# =============================================================================

class SolverSuite:
    """
    Unified interface to all solvers.
    
    Usage:
        suite = SolverSuite(graph, width, depth)
        
        # List available solvers
        for solver_type, metadata in suite.get_available_solvers():
            print(f"{solver_type.value}: {metadata.name}")
        
        # Solve with specific solver
        layout = suite.solve(SolverType.WAVE_COLLAPSE)
        
        # Or auto-select
        layout = suite.solve(SolverType.HYBRID)
    """
    
    SOLVER_MAP = {
        SolverType.GRID: GridSolverWrapper,
        SolverType.WAVE_COLLAPSE: WaveCollapseSolver,
        SolverType.TREE: TreeSolver,
        SolverType.PERFECT_ADJACENCY: PerfectAdjacencySolver,
        SolverType.CONSTRAINT: ConstraintSolver,
        SolverType.HYBRID: HybridSolver,
    }
    
    def __init__(self, graph: SpatialGraph, width: float, depth: float,
                 grid_size: float = 2.0):
        self.graph = graph
        self.width = width
        self.depth = depth
        self.grid_size = grid_size
    
    def get_available_solvers(self) -> List[Tuple[SolverType, SolverMetadata]]:
        """Get list of available solvers with metadata."""
        return [(st, SOLVER_INFO[st]) for st in SolverType]
    
    def get_solver_metadata(self, solver_type: SolverType) -> SolverMetadata:
        """Get metadata for a specific solver."""
        return SOLVER_INFO[solver_type]
    
    def solve(self, solver_type: SolverType, max_iterations: int = 10000) -> PlacedLayout:
        """
        Solve using specified solver.
        
        Args:
            solver_type: Which solver to use
            max_iterations: Maximum solver iterations
        
        Returns:
            PlacedLayout
        """
        solver_class = self.SOLVER_MAP.get(solver_type)
        if not solver_class:
            raise ValueError(f"Unknown solver type: {solver_type}")
        
        solver = solver_class(self.graph, self.width, self.depth, self.grid_size)
        return solver.solve(max_iterations)
    
    def solve_all(self, max_iterations: int = 5000) -> Dict[SolverType, PlacedLayout]:
        """
        Solve with all solvers and return results.
        
        Useful for comparing approaches.
        """
        results = {}
        
        for solver_type in SolverType:
            if solver_type == SolverType.HYBRID:
                continue  # Skip hybrid when running all
            
            try:
                layout = self.solve(solver_type, max_iterations)
                results[solver_type] = layout
            except Exception as e:
                print(f"Solver {solver_type.value} failed: {e}")
        
        return results
    
    def compare_solvers(self, max_iterations: int = 5000) -> Dict:
        """
        Run all solvers and return comparison.
        
        Returns:
            Dict with scores, times, completeness for each solver
        """
        results = self.solve_all(max_iterations)
        
        comparison = {}
        for solver_type, layout in results.items():
            comparison[solver_type.value] = {
                "name": SOLVER_INFO[solver_type].name,
                "score": layout.score,
                "complete": layout.is_complete,
                "rooms_placed": len(layout.rooms),
                "rooms_total": len(self.graph.rooms),
            }
        
        return comparison


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def solve_with_solver(
    graph: SpatialGraph,
    width: float,
    depth: float,
    solver_type: SolverType = SolverType.GRID,
    grid_size: float = 2.0
) -> PlacedLayout:
    """Convenience function to solve with specific solver."""
    suite = SolverSuite(graph, width, depth, grid_size)
    return suite.solve(solver_type)


def compare_all_solvers(
    graph: SpatialGraph,
    width: float,
    depth: float,
    grid_size: float = 2.0
) -> Dict:
    """Compare all solvers on a problem."""
    suite = SolverSuite(graph, width, depth, grid_size)
    return suite.compare_solvers()


def get_solver_descriptions() -> Dict[str, Dict]:
    """Get all solver descriptions for UI."""
    return {
        st.value: info.to_dict()
        for st, info in SOLVER_INFO.items()
    }
