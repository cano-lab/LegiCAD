"""
Wall Graph Generator
====================
Converts a SpatialGraph (room relationships) into a WallGraph (wall topology).

Flow:
1. SpatialGraph defines room relationships
2. WallGraph defines what walls exist (topology)
3. Coordinate solver places walls in space (geometry)

The WallGraph is an intermediate representation that captures:
- Which walls exist
- What rooms each wall separates
- What openings are in each wall
- Wall categories (exterior, interior, wet)
"""

from typing import Dict, List, Optional, Set, Tuple, NamedTuple
from dataclasses import dataclass, field
from enum import Enum
import math

from room_relationships import (
    SpatialGraph, RoomNode, Relationship, RelationType,
    WallType, OpeningType, Zone, ExteriorRequirement,
    ROOM_TYPES
)


# =============================================================================
# WALL SEGMENT (Topological, no coordinates yet)
# =============================================================================

@dataclass
class WallOpening:
    """An opening in a wall (door, cased opening, etc.)"""
    opening_type: OpeningType
    width: float = 3.0              # Width in feet
    position: float = 0.5           # 0-1 along wall length (0.5 = center)

    @property
    def is_door(self) -> bool:
        return self.opening_type in {
            OpeningType.DOOR,
            OpeningType.DOUBLE_DOOR,
            OpeningType.POCKET_DOOR,
            OpeningType.BARN_DOOR,
            OpeningType.FRENCH_DOOR
        }


@dataclass
class WallSegment:
    """
    A wall segment between two rooms (or room and exterior).

    This is topological - it knows WHAT rooms it separates,
    but not yet WHERE it is in space.
    """
    id: str
    room1: str                      # Room on one side (or "exterior")
    room2: str                      # Room on other side (or "exterior")
    wall_type: WallType
    openings: List[WallOpening] = field(default_factory=list)

    # Constraints from relationships
    required: bool = True           # Must this wall exist?
    min_length: float = 0.0         # Minimum wall length

    @property
    def is_exterior(self) -> bool:
        return self.room1 == "exterior" or self.room2 == "exterior"

    @property
    def is_wet_wall(self) -> bool:
        return self.wall_type == WallType.WET

    @property
    def has_door(self) -> bool:
        return any(o.is_door for o in self.openings)

    @property
    def is_open(self) -> bool:
        """Is this an open wall (no physical wall)?"""
        return self.wall_type == WallType.NONE

    def get_interior_room(self) -> Optional[str]:
        """Get the non-exterior room if this is an exterior wall"""
        if self.room1 == "exterior":
            return self.room2
        elif self.room2 == "exterior":
            return self.room1
        return None

    def involves_room(self, room_id: str) -> bool:
        return self.room1 == room_id or self.room2 == room_id

    def other_room(self, room_id: str) -> str:
        """Get the room on the other side of this wall"""
        if self.room1 == room_id:
            return self.room2
        return self.room1


# =============================================================================
# WALL GRAPH
# =============================================================================

@dataclass
class WallGraph:
    """
    Graph of all walls in a floor plan.

    This captures the topology of walls - which rooms they separate,
    what openings they have - without specific coordinates.
    """
    walls: Dict[str, WallSegment] = field(default_factory=dict)
    rooms: Set[str] = field(default_factory=set)

    # Building info
    exterior_rooms: Set[str] = field(default_factory=set)  # Rooms that touch exterior

    def add_wall(self, wall: WallSegment) -> 'WallGraph':
        """Add a wall to the graph"""
        self.walls[wall.id] = wall
        if wall.room1 != "exterior":
            self.rooms.add(wall.room1)
        if wall.room2 != "exterior":
            self.rooms.add(wall.room2)
        return self

    def get_wall(self, room1: str, room2: str) -> Optional[WallSegment]:
        """Get wall between two rooms (order independent)"""
        for wall in self.walls.values():
            if (wall.room1 == room1 and wall.room2 == room2) or \
               (wall.room1 == room2 and wall.room2 == room1):
                return wall
        return None

    def get_room_walls(self, room_id: str) -> List[WallSegment]:
        """Get all walls that touch a room"""
        return [w for w in self.walls.values() if w.involves_room(room_id)]

    def get_exterior_walls(self) -> List[WallSegment]:
        """Get all exterior walls"""
        return [w for w in self.walls.values() if w.is_exterior]

    def get_interior_walls(self) -> List[WallSegment]:
        """Get all interior walls"""
        return [w for w in self.walls.values() if not w.is_exterior]

    def get_wet_walls(self) -> List[WallSegment]:
        """Get all wet walls"""
        return [w for w in self.walls.values() if w.is_wet_wall]

    def get_adjacent_rooms(self, room_id: str) -> Set[str]:
        """Get all rooms adjacent to a room (sharing a wall)"""
        adjacent = set()
        for wall in self.get_room_walls(room_id):
            if not wall.is_open:  # Only count physical walls
                other = wall.other_room(room_id)
                if other != "exterior":
                    adjacent.add(other)
        return adjacent

    def get_connected_rooms(self, room_id: str) -> Set[str]:
        """Get rooms connected via doors"""
        connected = set()
        for wall in self.get_room_walls(room_id):
            if wall.has_door:
                other = wall.other_room(room_id)
                if other != "exterior":
                    connected.add(other)
        return connected

    def room_has_exterior(self, room_id: str) -> bool:
        """Check if room has an exterior wall"""
        return room_id in self.exterior_rooms

    def validate(self) -> List[str]:
        """Validate the wall graph"""
        issues = []

        # Check all rooms have at least one wall
        for room in self.rooms:
            walls = self.get_room_walls(room)
            if not walls:
                issues.append(f"Room '{room}' has no walls")

        # Check rooms are reachable from entry (via doors OR open connections)
        reachable = self._find_reachable_rooms("entry")
        for room in self.rooms:
            if room not in reachable:
                issues.append(f"Room '{room}' is not reachable from entry")

        return issues

    def _find_reachable_rooms(self, start: str) -> Set[str]:
        """Find all rooms reachable from start via doors or open connections"""
        reachable = set()
        to_visit = [start]

        while to_visit:
            current = to_visit.pop()
            if current in reachable:
                continue
            reachable.add(current)

            for wall in self.get_room_walls(current):
                other = wall.other_room(current)
                if other == "exterior":
                    continue
                # Reachable if there's a door OR wall is open
                if wall.has_door or wall.is_open:
                    if other not in reachable:
                        to_visit.append(other)

        return reachable

    def summary(self) -> str:
        """Get a text summary"""
        lines = [
            f"Wall Graph: {len(self.walls)} walls, {len(self.rooms)} rooms",
            f"Exterior rooms: {self.exterior_rooms}",
            "",
            "Walls:",
        ]

        for wall in self.walls.values():
            openings = ", ".join(o.opening_type.value for o in wall.openings) or "none"
            wall_str = "OPEN" if wall.is_open else wall.wall_type.value
            lines.append(f"  {wall.id}: {wall.room1} -- {wall.room2} [{wall_str}] openings: {openings}")

        return "\n".join(lines)


# =============================================================================
# WALL GRAPH GENERATOR
# =============================================================================

class WallGraphGenerator:
    """
    Generates a WallGraph from a SpatialGraph.

    This translates room relationships into wall topology.
    """

    def __init__(self, spatial_graph: SpatialGraph):
        self.spatial = spatial_graph
        self.wall_graph = WallGraph()
        self._wall_counter = 0

    def generate(self) -> WallGraph:
        """Generate the wall graph from relationships"""

        # Step 1: Create walls from relationships
        self._generate_relationship_walls()

        # Step 2: Identify exterior rooms and create exterior walls
        self._generate_exterior_walls()

        # Step 3: Mark wet walls
        self._mark_wet_walls()

        return self.wall_graph

    def _next_wall_id(self) -> str:
        self._wall_counter += 1
        return f"wall_{self._wall_counter}"

    def _generate_relationship_walls(self):
        """Create walls from room relationships"""

        processed_pairs = set()

        for room_id, room in self.spatial.rooms.items():
            for rel in room.relationships:
                # Skip if already processed (bidirectional)
                pair = tuple(sorted([rel.from_room, rel.to_room]))
                if pair in processed_pairs:
                    continue
                processed_pairs.add(pair)

                # Skip if target room doesn't exist
                if rel.to_room not in self.spatial.rooms:
                    continue

                # Get wall and opening type from relationship
                wall_type, opening_type = rel.get_wall_result()

                # Create openings list
                openings = []
                if opening_type != OpeningType.NONE:
                    openings.append(WallOpening(
                        opening_type=opening_type,
                        width=rel.opening_width
                    ))

                # Create wall segment
                wall = WallSegment(
                    id=self._next_wall_id(),
                    room1=rel.from_room,
                    room2=rel.to_room,
                    wall_type=wall_type,
                    openings=openings,
                    required=not rel.implies_separation  # Separation means NO wall
                )

                # Don't add walls that shouldn't exist
                if not rel.implies_separation:
                    self.wall_graph.add_wall(wall)

    def _generate_exterior_walls(self):
        """
        Identify which rooms need exterior walls and create them.

        Rooms with ExteriorRequirement.REQUIRED must touch exterior.
        """
        exterior_rooms = set()

        for room_id, room in self.spatial.rooms.items():
            if room.exterior_requirement == ExteriorRequirement.REQUIRED:
                exterior_rooms.add(room_id)
            elif room.exterior_requirement == ExteriorRequirement.PREFERRED:
                # Preferred rooms get exterior if possible
                # For now, add them to exterior set
                exterior_rooms.add(room_id)

        # Create exterior wall segments for these rooms
        for room_id in exterior_rooms:
            wall = WallSegment(
                id=self._next_wall_id(),
                room1="exterior",
                room2=room_id,
                wall_type=WallType.EXTERIOR,
                openings=[],
                required=True
            )
            self.wall_graph.add_wall(wall)
            self.wall_graph.exterior_rooms.add(room_id)

        # Entry always has exterior (front door)
        if self.spatial.entry_room and self.spatial.entry_room not in exterior_rooms:
            entry_wall = WallSegment(
                id=self._next_wall_id(),
                room1="exterior",
                room2=self.spatial.entry_room,
                wall_type=WallType.EXTERIOR,
                openings=[WallOpening(OpeningType.DOOR, width=3.0)],  # Front door
                required=True
            )
            self.wall_graph.add_wall(entry_wall)
            self.wall_graph.exterior_rooms.add(self.spatial.entry_room)

    def _mark_wet_walls(self):
        """Mark walls between wet rooms as wet walls"""

        wet_rooms = set(self.spatial.get_wet_rooms())

        for wall in self.wall_graph.walls.values():
            if wall.is_exterior:
                continue

            # If both rooms are wet, this is definitely a wet wall
            if wall.room1 in wet_rooms and wall.room2 in wet_rooms:
                wall.wall_type = WallType.WET

            # If one room is wet and wall has plumbing, mark as wet
            # (simplified: any wall touching a wet room could be wet)
            elif wall.room1 in wet_rooms or wall.room2 in wet_rooms:
                # Only mark as wet if it's currently a full wall
                if wall.wall_type == WallType.FULL:
                    wall.wall_type = WallType.WET


# =============================================================================
# ADJACENCY MATRIX (for solver)
# =============================================================================

@dataclass
class AdjacencyConstraints:
    """
    Adjacency constraints derived from wall graph.
    Used by the coordinate solver.
    """
    must_touch: Dict[str, Set[str]] = field(default_factory=dict)
    must_not_touch: Dict[str, Set[str]] = field(default_factory=dict)
    prefer_touch: Dict[str, Set[str]] = field(default_factory=dict)

    # Exterior constraints
    must_have_exterior: Set[str] = field(default_factory=set)
    prefer_exterior: Set[str] = field(default_factory=set)

    # Grouping constraints
    groups: List[Set[str]] = field(default_factory=list)

    def add_must_touch(self, room1: str, room2: str):
        if room1 not in self.must_touch:
            self.must_touch[room1] = set()
        if room2 not in self.must_touch:
            self.must_touch[room2] = set()
        self.must_touch[room1].add(room2)
        self.must_touch[room2].add(room1)

    def add_must_not_touch(self, room1: str, room2: str):
        if room1 not in self.must_not_touch:
            self.must_not_touch[room1] = set()
        if room2 not in self.must_not_touch:
            self.must_not_touch[room2] = set()
        self.must_not_touch[room1].add(room2)
        self.must_not_touch[room2].add(room1)


def extract_constraints(spatial: SpatialGraph, wall_graph: WallGraph) -> AdjacencyConstraints:
    """Extract adjacency constraints from spatial graph and wall graph"""

    constraints = AdjacencyConstraints()

    # Must-touch: rooms that share a wall (from wall graph)
    for wall in wall_graph.walls.values():
        if wall.is_exterior:
            continue
        if not wall.is_open:  # Physical wall = rooms must touch
            constraints.add_must_touch(wall.room1, wall.room2)

    # Must-not-touch: from isolation relationships
    sep = spatial.get_separation_requirements()
    for room_id, isolated_from in sep.items():
        for other in isolated_from:
            constraints.add_must_not_touch(room_id, other)

    # Exterior requirements
    for room_id, room in spatial.rooms.items():
        if room.exterior_requirement == ExteriorRequirement.REQUIRED:
            constraints.must_have_exterior.add(room_id)
        elif room.exterior_requirement == ExteriorRequirement.PREFERRED:
            constraints.prefer_exterior.add(room_id)

    # Grouping from GROUPED_WITH relationships
    for room in spatial.rooms.values():
        for rel in room.relationships:
            if rel.relation_type == RelationType.GROUPED_WITH:
                # Find or create group
                found_group = None
                for group in constraints.groups:
                    if rel.from_room in group or rel.to_room in group:
                        found_group = group
                        break

                if found_group:
                    found_group.add(rel.from_room)
                    found_group.add(rel.to_room)
                else:
                    constraints.groups.append({rel.from_room, rel.to_room})

    return constraints


# =============================================================================
# ROOM AREAS (for solver)
# =============================================================================

@dataclass
class RoomAreaSpec:
    """Area specification for a room"""
    room_id: str
    min_area: float
    max_area: float = None
    target_area: float = None       # Ideal area
    aspect_min: float = 0.4         # Min width/height
    aspect_max: float = 2.5         # Max width/height

    def __post_init__(self):
        if self.max_area is None:
            self.max_area = self.min_area * 2.0
        if self.target_area is None:
            self.target_area = self.min_area * 1.2


def extract_room_areas(spatial: SpatialGraph) -> Dict[str, RoomAreaSpec]:
    """Extract room area specifications from spatial graph"""

    areas = {}
    for room_id, room in spatial.rooms.items():
        spec = room.spec
        min_area = room.effective_min_area

        areas[room_id] = RoomAreaSpec(
            room_id=room_id,
            min_area=min_area,
            target_area=min_area * 1.2,
            aspect_min=0.4 if room.room_type != "hallway" else 0.2,
            aspect_max=2.5 if room.room_type != "hallway" else 5.0
        )

    return areas


# =============================================================================
# COMPLETE LAYOUT SPEC (input to coordinate solver)
# =============================================================================

@dataclass
class LayoutSpec:
    """
    Complete specification for layout generation.
    This is the input to the coordinate solver.
    """
    wall_graph: WallGraph
    constraints: AdjacencyConstraints
    room_areas: Dict[str, RoomAreaSpec]

    # Building envelope
    building_width: float
    building_depth: float
    entry_edge: str = "south"
    entry_position: float = 0.5     # 0-1 along entry edge

    @classmethod
    def from_spatial_graph(cls, spatial: SpatialGraph,
                           building_width: float,
                           building_depth: float) -> 'LayoutSpec':
        """Create a complete layout spec from a spatial graph"""

        # Generate wall graph
        generator = WallGraphGenerator(spatial)
        wall_graph = generator.generate()

        # Extract constraints
        constraints = extract_constraints(spatial, wall_graph)

        # Extract room areas
        room_areas = extract_room_areas(spatial)

        return cls(
            wall_graph=wall_graph,
            constraints=constraints,
            room_areas=room_areas,
            building_width=building_width,
            building_depth=building_depth,
            entry_edge=spatial.entry_edge
        )

    def summary(self) -> str:
        """Get a text summary"""
        lines = [
            f"Layout Spec: {self.building_width}x{self.building_depth}ft",
            f"Entry: {self.entry_edge} edge at {self.entry_position}",
            "",
            self.wall_graph.summary(),
            "",
            "Constraints:",
            f"  Must-touch pairs: {sum(len(v) for v in self.constraints.must_touch.values()) // 2}",
            f"  Must-not-touch pairs: {sum(len(v) for v in self.constraints.must_not_touch.values()) // 2}",
            f"  Exterior required: {self.constraints.must_have_exterior}",
            f"  Groups: {len(self.constraints.groups)}",
            "",
            "Room Areas:",
        ]

        for room_id, spec in self.room_areas.items():
            lines.append(f"  {room_id}: {spec.min_area}-{spec.max_area} sqft")

        return "\n".join(lines)


# =============================================================================
# TEST
# =============================================================================

if __name__ == "__main__":
    from room_relationships import create_standard_house

    print("=" * 60)
    print("WALL GRAPH GENERATOR TEST")
    print("=" * 60)

    # Create a 3BR/2BA house
    spatial = create_standard_house(bedrooms=3, bathrooms=2, has_garage=True, open_concept=True)

    # Generate wall graph
    generator = WallGraphGenerator(spatial)
    wall_graph = generator.generate()

    # Validate
    issues = wall_graph.validate()
    if issues:
        print("\nValidation Issues:")
        for issue in issues:
            print(f"  - {issue}")
    else:
        print("\nWall Graph Validation: OK")

    # Summary
    print("\n" + wall_graph.summary())

    # Create full layout spec
    print("\n" + "=" * 60)
    print("LAYOUT SPEC TEST")
    print("=" * 60)

    layout_spec = LayoutSpec.from_spatial_graph(spatial, 50, 40)
    print("\n" + layout_spec.summary())

    # Show adjacency constraints
    print("\nMust-Touch Constraints:")
    for room, others in layout_spec.constraints.must_touch.items():
        if others:
            print(f"  {room}: {others}")

    print("\nMust-Not-Touch Constraints:")
    for room, others in layout_spec.constraints.must_not_touch.items():
        if others:
            print(f"  {room}: {others}")

    print("\nWet Walls:")
    for wall in wall_graph.get_wet_walls():
        print(f"  {wall.id}: {wall.room1} -- {wall.room2}")
