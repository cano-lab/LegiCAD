"""
Room Relationship Model
=======================
Defines spatial relationships between rooms that drive wall generation.

Architecture:
1. Relationships define topology (how rooms connect)
2. Topology translates to wall graph (what walls exist)
3. Wall graph + constraints = wall coordinates

This is relationship-first design: we define connections, walls emerge from that.
"""

from enum import Enum, auto
from typing import Dict, List, Optional, Set, Tuple, NamedTuple
from dataclasses import dataclass, field


# =============================================================================
# RELATIONSHIP TYPES
# =============================================================================

class RelationType(Enum):
    """
    Types of spatial relationships between rooms.
    Each implies specific wall/opening behavior.
    """
    # Direct connections (door required)
    CONNECTS_TO = "connects_to"      # Must have door between rooms
    ACCESSED_VIA = "accessed_via"    # Must pass through other room to reach

    # Adjacency (shared wall)
    ADJACENT_TO = "adjacent_to"      # Shares wall, door optional
    ATTACHED_TO = "attached_to"      # Direct access (ensuite), door required

    # Open relationships (no wall)
    OPEN_TO = "open_to"              # No wall, continuous space
    PARTIAL_WALL = "partial_wall"    # Half wall or peninsula

    # Separation constraints
    ISOLATED_FROM = "isolated_from"  # Cannot share wall
    BUFFERED_FROM = "buffered_from"  # Needs hallway/room between

    # Grouping
    GROUPED_WITH = "grouped_with"    # Should be near each other
    SAME_ZONE = "same_zone"          # Must be in same zone


class OpeningType(Enum):
    """Types of openings in walls"""
    NONE = "none"                    # Solid wall
    DOOR = "door"                    # Standard door
    DOUBLE_DOOR = "double_door"      # Double doors
    CASED_OPENING = "cased_opening"  # No door, trimmed opening
    ARCHWAY = "archway"              # Arched opening
    POCKET_DOOR = "pocket_door"      # Sliding pocket door
    BARN_DOOR = "barn_door"          # Sliding barn door
    FRENCH_DOOR = "french_door"      # Glass french doors
    WINDOW = "window"                # Window opening


class WallType(Enum):
    """Types of walls"""
    NONE = "none"                    # No wall (open)
    FULL = "full"                    # Full height wall
    PARTIAL = "partial"              # Half wall / pony wall
    EXTERIOR = "exterior"            # Exterior wall
    WET = "wet"                      # Plumbing wall (thicker)


class Zone(Enum):
    """Zones for room organization"""
    PUBLIC = "public"                # Entry, Living, Dining, Kitchen
    PRIVATE = "private"              # Bedrooms, Bathrooms, Office
    SERVICE = "service"              # Laundry, Mechanical, Garage, Mudroom
    CIRCULATION = "circulation"      # Hallways, Stairs


class ExteriorRequirement(Enum):
    """Exterior wall requirements"""
    REQUIRED = "required"            # Must have exterior wall (bedroom egress)
    PREFERRED = "preferred"          # Better with exterior (living, office)
    NONE = "none"                    # No preference
    INTERIOR_ONLY = "interior"       # Should be interior (bathroom, closet)


# =============================================================================
# ROOM TYPE DEFINITIONS
# =============================================================================

@dataclass
class RoomTypeSpec:
    """Specification for a room type with default properties"""
    name: str
    zone: Zone
    exterior: ExteriorRequirement
    is_wet: bool = False
    min_area: int = 50               # Default minimum sqft
    typical_ratio: float = 0.75      # Typical width/depth ratio (0.5-1.0)

    # Default relationships (can be overridden)
    default_connections: List[str] = field(default_factory=list)
    default_adjacencies: List[str] = field(default_factory=list)
    default_groupings: List[str] = field(default_factory=list)


# Standard room type definitions
ROOM_TYPES: Dict[str, RoomTypeSpec] = {
    # PUBLIC ZONE
    "entry": RoomTypeSpec(
        name="Entry",
        zone=Zone.PUBLIC,
        exterior=ExteriorRequirement.REQUIRED,  # Has front door
        min_area=40,
        typical_ratio=0.8,
        default_connections=["living", "hallway"],
        default_adjacencies=["coat_closet"],
    ),
    "living": RoomTypeSpec(
        name="Living Room",
        zone=Zone.PUBLIC,
        exterior=ExteriorRequirement.PREFERRED,
        min_area=180,
        typical_ratio=0.7,
        default_connections=["entry", "hallway"],
        default_adjacencies=["dining", "kitchen"],
    ),
    "dining": RoomTypeSpec(
        name="Dining Room",
        zone=Zone.PUBLIC,
        exterior=ExteriorRequirement.PREFERRED,
        min_area=100,
        typical_ratio=0.8,
        default_adjacencies=["living", "kitchen"],
    ),
    "kitchen": RoomTypeSpec(
        name="Kitchen",
        zone=Zone.PUBLIC,
        exterior=ExteriorRequirement.PREFERRED,
        is_wet=True,
        min_area=100,
        typical_ratio=0.7,
        default_adjacencies=["dining", "living"],
        default_groupings=["pantry"],
    ),
    "great_room": RoomTypeSpec(
        name="Great Room",
        zone=Zone.PUBLIC,
        exterior=ExteriorRequirement.PREFERRED,
        min_area=300,
        typical_ratio=0.6,
        default_connections=["entry", "hallway"],
    ),

    # PRIVATE ZONE
    "primary_bedroom": RoomTypeSpec(
        name="Primary Bedroom",
        zone=Zone.PRIVATE,
        exterior=ExteriorRequirement.REQUIRED,  # Egress
        min_area=150,
        typical_ratio=0.75,
        default_connections=["hallway", "primary_bath", "walk_in_closet"],
    ),
    "bedroom": RoomTypeSpec(
        name="Bedroom",
        zone=Zone.PRIVATE,
        exterior=ExteriorRequirement.REQUIRED,  # Egress
        min_area=100,
        typical_ratio=0.8,
        default_connections=["hallway"],
        default_adjacencies=["closet"],
    ),
    "primary_bath": RoomTypeSpec(
        name="Primary Bath",
        zone=Zone.PRIVATE,
        exterior=ExteriorRequirement.NONE,
        is_wet=True,
        min_area=60,
        typical_ratio=0.7,
        default_connections=["primary_bedroom"],
    ),
    "bathroom": RoomTypeSpec(
        name="Bathroom",
        zone=Zone.PRIVATE,
        exterior=ExteriorRequirement.NONE,
        is_wet=True,
        min_area=40,
        typical_ratio=0.8,
        default_connections=["hallway"],
    ),
    "powder_room": RoomTypeSpec(
        name="Powder Room",
        zone=Zone.PUBLIC,  # Guest bathroom
        exterior=ExteriorRequirement.NONE,
        is_wet=True,
        min_area=25,
        typical_ratio=0.6,
        default_connections=["hallway", "entry"],
    ),
    "office": RoomTypeSpec(
        name="Office",
        zone=Zone.PRIVATE,
        exterior=ExteriorRequirement.PREFERRED,
        min_area=100,
        typical_ratio=0.8,
        default_connections=["hallway"],
    ),

    # CIRCULATION
    "hallway": RoomTypeSpec(
        name="Hallway",
        zone=Zone.CIRCULATION,
        exterior=ExteriorRequirement.NONE,
        min_area=40,
        typical_ratio=0.3,  # Long and narrow
    ),
    "foyer": RoomTypeSpec(
        name="Foyer",
        zone=Zone.CIRCULATION,
        exterior=ExteriorRequirement.REQUIRED,
        min_area=50,
        typical_ratio=0.8,
        default_connections=["living", "hallway", "dining"],
    ),

    # SERVICE ZONE
    "laundry": RoomTypeSpec(
        name="Laundry",
        zone=Zone.SERVICE,
        exterior=ExteriorRequirement.NONE,
        is_wet=True,
        min_area=35,
        typical_ratio=0.7,
        default_connections=["hallway"],
        default_groupings=["bathroom", "kitchen"],  # Near wet rooms
    ),
    "mudroom": RoomTypeSpec(
        name="Mudroom",
        zone=Zone.SERVICE,
        exterior=ExteriorRequirement.REQUIRED,  # Has exterior door
        min_area=40,
        typical_ratio=0.6,
        default_connections=["garage", "kitchen"],
    ),
    "garage": RoomTypeSpec(
        name="Garage",
        zone=Zone.SERVICE,
        exterior=ExteriorRequirement.REQUIRED,
        min_area=200,  # 1 car
        typical_ratio=0.6,
        default_connections=["mudroom", "entry"],
    ),
    "mechanical": RoomTypeSpec(
        name="Mechanical",
        zone=Zone.SERVICE,
        exterior=ExteriorRequirement.NONE,
        min_area=30,
        typical_ratio=0.8,
    ),
    "pantry": RoomTypeSpec(
        name="Pantry",
        zone=Zone.SERVICE,
        exterior=ExteriorRequirement.NONE,
        min_area=25,
        typical_ratio=0.5,
        default_connections=["kitchen"],
    ),

    # STORAGE
    "closet": RoomTypeSpec(
        name="Closet",
        zone=Zone.PRIVATE,
        exterior=ExteriorRequirement.INTERIOR_ONLY,
        min_area=15,
        typical_ratio=0.5,
    ),
    "walk_in_closet": RoomTypeSpec(
        name="Walk-in Closet",
        zone=Zone.PRIVATE,
        exterior=ExteriorRequirement.INTERIOR_ONLY,
        min_area=40,
        typical_ratio=0.7,
        default_connections=["primary_bedroom"],
    ),
    "coat_closet": RoomTypeSpec(
        name="Coat Closet",
        zone=Zone.PUBLIC,
        exterior=ExteriorRequirement.INTERIOR_ONLY,
        min_area=10,
        typical_ratio=0.4,
        default_connections=["entry"],
    ),
}


# =============================================================================
# RELATIONSHIP CLASS
# =============================================================================

@dataclass
class Relationship:
    """
    A directed relationship from one room to another.

    Example:
        Relationship("entry", "living", RelationType.CONNECTS_TO)
        means: Entry connects to Living (door required)
    """
    from_room: str
    to_room: str
    relation_type: RelationType

    # Opening specification (for connections)
    opening_type: OpeningType = OpeningType.DOOR
    opening_width: float = 3.0  # feet

    # Wall specification (for adjacencies)
    wall_type: WallType = WallType.FULL

    # Priority (higher = more important to satisfy)
    priority: int = 50

    # Is this relationship bidirectional?
    bidirectional: bool = True

    @property
    def implies_wall(self) -> bool:
        """Does this relationship imply a wall between rooms?"""
        return self.relation_type in {
            RelationType.CONNECTS_TO,
            RelationType.ADJACENT_TO,
            RelationType.ATTACHED_TO,
            RelationType.PARTIAL_WALL,
        }

    @property
    def implies_opening(self) -> bool:
        """Does this relationship require an opening?"""
        return self.relation_type in {
            RelationType.CONNECTS_TO,
            RelationType.ATTACHED_TO,
            RelationType.OPEN_TO,
            RelationType.PARTIAL_WALL,
        }

    @property
    def implies_no_wall(self) -> bool:
        """Does this relationship mean no wall?"""
        return self.relation_type == RelationType.OPEN_TO

    @property
    def implies_separation(self) -> bool:
        """Does this relationship require rooms to NOT be adjacent?"""
        return self.relation_type in {
            RelationType.ISOLATED_FROM,
            RelationType.BUFFERED_FROM,
        }

    def get_wall_result(self) -> Tuple[WallType, OpeningType]:
        """Get the wall and opening type implied by this relationship"""
        if self.relation_type == RelationType.OPEN_TO:
            return WallType.NONE, OpeningType.CASED_OPENING
        elif self.relation_type == RelationType.PARTIAL_WALL:
            return WallType.PARTIAL, OpeningType.NONE
        elif self.relation_type == RelationType.CONNECTS_TO:
            return WallType.FULL, self.opening_type
        elif self.relation_type == RelationType.ATTACHED_TO:
            return WallType.FULL, self.opening_type
        elif self.relation_type == RelationType.ADJACENT_TO:
            return self.wall_type, OpeningType.NONE
        else:
            return WallType.NONE, OpeningType.NONE


# =============================================================================
# ROOM NODE (Room in the graph)
# =============================================================================

@dataclass
class RoomNode:
    """
    A room in the relationship graph.
    """
    id: str                          # Unique identifier
    room_type: str                   # Key into ROOM_TYPES
    name: str                        # Display name

    # Area constraints
    min_area: float = None           # Override type default
    max_area: float = None

    # Relationships (populated by SpatialGraph)
    relationships: List[Relationship] = field(default_factory=list)

    @property
    def spec(self) -> RoomTypeSpec:
        """Get the room type specification"""
        return ROOM_TYPES.get(self.room_type, ROOM_TYPES["bedroom"])

    @property
    def zone(self) -> Zone:
        return self.spec.zone

    @property
    def is_wet(self) -> bool:
        return self.spec.is_wet

    @property
    def exterior_requirement(self) -> ExteriorRequirement:
        return self.spec.exterior

    @property
    def effective_min_area(self) -> float:
        return self.min_area if self.min_area else self.spec.min_area

    def get_connections(self) -> List[str]:
        """Get room IDs this room connects to (has door to)"""
        return [r.to_room for r in self.relationships
                if r.relation_type in {RelationType.CONNECTS_TO, RelationType.ATTACHED_TO}]

    def get_adjacencies(self) -> List[str]:
        """Get room IDs this room is adjacent to (shares wall)"""
        return [r.to_room for r in self.relationships
                if r.implies_wall]

    def get_separations(self) -> List[str]:
        """Get room IDs this room must be separated from"""
        return [r.to_room for r in self.relationships
                if r.implies_separation]


# =============================================================================
# SPATIAL GRAPH (Complete relationship model)
# =============================================================================

@dataclass
class SpatialGraph:
    """
    The complete relationship graph for a floor plan.

    This defines:
    - All rooms and their properties
    - All relationships between rooms
    - Building constraints (entry location, etc.)

    From this graph, we can derive:
    - What walls need to exist
    - What openings are needed
    - Adjacency constraints for the solver
    """
    rooms: Dict[str, RoomNode] = field(default_factory=dict)

    # Building constraints
    entry_room: str = "entry"
    entry_edge: str = "south"        # Which edge has the front door

    # Zone preferences
    public_zone_edge: str = "south"  # Public rooms near front
    private_zone_edge: str = "north" # Private rooms toward back
    service_zone_edge: str = "west"  # Service rooms to side

    def add_room(self, room_id: str, room_type: str, name: str = None,
                 min_area: float = None, max_area: float = None) -> 'SpatialGraph':
        """Add a room to the graph"""
        if name is None:
            name = ROOM_TYPES.get(room_type, RoomTypeSpec("Room", Zone.PRIVATE, ExteriorRequirement.NONE)).name

        self.rooms[room_id] = RoomNode(
            id=room_id,
            room_type=room_type,
            name=name,
            min_area=min_area,
            max_area=max_area
        )
        return self

    def add_relationship(self, from_room: str, to_room: str,
                        relation_type: RelationType,
                        opening_type: OpeningType = OpeningType.DOOR,
                        wall_type: WallType = WallType.FULL,
                        bidirectional: bool = True,
                        priority: int = 50) -> 'SpatialGraph':
        """Add a relationship between two rooms"""
        rel = Relationship(
            from_room=from_room,
            to_room=to_room,
            relation_type=relation_type,
            opening_type=opening_type,
            wall_type=wall_type,
            bidirectional=bidirectional,
            priority=priority
        )

        if from_room in self.rooms:
            self.rooms[from_room].relationships.append(rel)

        if bidirectional and to_room in self.rooms:
            reverse_rel = Relationship(
                from_room=to_room,
                to_room=from_room,
                relation_type=relation_type,
                opening_type=opening_type,
                wall_type=wall_type,
                bidirectional=False,  # Don't create infinite loop
                priority=priority
            )
            self.rooms[to_room].relationships.append(reverse_rel)

        return self

    def connect(self, room1: str, room2: str,
                opening: OpeningType = OpeningType.DOOR) -> 'SpatialGraph':
        """Shorthand: rooms connect with a door"""
        return self.add_relationship(room1, room2, RelationType.CONNECTS_TO, opening_type=opening)

    def open_to(self, room1: str, room2: str) -> 'SpatialGraph':
        """Shorthand: rooms are open to each other (no wall)"""
        return self.add_relationship(room1, room2, RelationType.OPEN_TO)

    def adjacent(self, room1: str, room2: str) -> 'SpatialGraph':
        """Shorthand: rooms share a wall but no door"""
        return self.add_relationship(room1, room2, RelationType.ADJACENT_TO)

    def attached(self, room1: str, room2: str,
                 opening: OpeningType = OpeningType.DOOR) -> 'SpatialGraph':
        """Shorthand: rooms directly connected (ensuite style)"""
        return self.add_relationship(room1, room2, RelationType.ATTACHED_TO, opening_type=opening)

    def isolate(self, room1: str, room2: str) -> 'SpatialGraph':
        """Shorthand: rooms cannot share a wall"""
        return self.add_relationship(room1, room2, RelationType.ISOLATED_FROM, bidirectional=True)

    def group(self, *rooms: str) -> 'SpatialGraph':
        """Shorthand: rooms should be grouped together"""
        for i, room1 in enumerate(rooms):
            for room2 in rooms[i+1:]:
                self.add_relationship(room1, room2, RelationType.GROUPED_WITH)
        return self

    # -------------------------------------------------------------------------
    # ANALYSIS METHODS
    # -------------------------------------------------------------------------

    def get_required_walls(self) -> List[Tuple[str, str, WallType, OpeningType]]:
        """
        Get all walls implied by relationships.
        Returns: [(room1, room2, wall_type, opening_type), ...]
        """
        walls = []
        seen_pairs = set()

        for room in self.rooms.values():
            for rel in room.relationships:
                if rel.implies_wall or rel.implies_opening:
                    pair = tuple(sorted([rel.from_room, rel.to_room]))
                    if pair not in seen_pairs:
                        seen_pairs.add(pair)
                        wall_type, opening_type = rel.get_wall_result()
                        walls.append((rel.from_room, rel.to_room, wall_type, opening_type))

        return walls

    def get_adjacency_requirements(self) -> Dict[str, Set[str]]:
        """Get which rooms MUST be adjacent to which"""
        adj = {room_id: set() for room_id in self.rooms}

        for room in self.rooms.values():
            for rel in room.relationships:
                if rel.implies_wall:  # Shared wall = adjacent
                    adj[room.id].add(rel.to_room)

        return adj

    def get_separation_requirements(self) -> Dict[str, Set[str]]:
        """Get which rooms must NOT be adjacent"""
        sep = {room_id: set() for room_id in self.rooms}

        for room in self.rooms.values():
            for rel in room.relationships:
                if rel.implies_separation:
                    sep[room.id].add(rel.to_room)

        return sep

    def get_rooms_by_zone(self) -> Dict[Zone, List[str]]:
        """Group rooms by zone"""
        by_zone = {zone: [] for zone in Zone}
        for room in self.rooms.values():
            by_zone[room.zone].append(room.id)
        return by_zone

    def get_wet_rooms(self) -> List[str]:
        """Get all wet rooms (need plumbing)"""
        return [r.id for r in self.rooms.values() if r.is_wet]

    def get_exterior_required_rooms(self) -> List[str]:
        """Get rooms that require exterior walls"""
        return [r.id for r in self.rooms.values()
                if r.exterior_requirement == ExteriorRequirement.REQUIRED]

    def validate(self) -> List[str]:
        """Validate the graph for common issues"""
        issues = []

        # Check all relationship targets exist
        for room in self.rooms.values():
            for rel in room.relationships:
                if rel.to_room not in self.rooms:
                    issues.append(f"Room '{room.id}' has relationship to non-existent room '{rel.to_room}'")

        # Check entry room exists
        if self.entry_room and self.entry_room not in self.rooms:
            issues.append(f"Entry room '{self.entry_room}' not found in rooms")

        # Check for conflicting relationships
        for room in self.rooms.values():
            adjacencies = room.get_adjacencies()
            separations = room.get_separations()
            conflicts = set(adjacencies) & set(separations)
            if conflicts:
                issues.append(f"Room '{room.id}' has conflicting adjacent/isolated relationships with: {conflicts}")

        return issues

    def summary(self) -> str:
        """Get a text summary of the graph"""
        lines = [
            f"Spatial Graph: {len(self.rooms)} rooms",
            f"Entry: {self.entry_room} ({self.entry_edge} edge)",
            "",
            "Rooms by Zone:",
        ]

        for zone, room_ids in self.get_rooms_by_zone().items():
            if room_ids:
                lines.append(f"  {zone.value}: {', '.join(room_ids)}")

        lines.append("")
        lines.append("Required Walls:")
        for room1, room2, wall_type, opening_type in self.get_required_walls():
            opening_str = f" + {opening_type.value}" if opening_type != OpeningType.NONE else ""
            lines.append(f"  {room1} -- {room2}: {wall_type.value}{opening_str}")

        return "\n".join(lines)


# =============================================================================
# STANDARD TEMPLATES
# =============================================================================

def create_standard_house(bedrooms: int = 3, bathrooms: int = 2,
                         has_garage: bool = True,
                         open_concept: bool = True) -> SpatialGraph:
    """
    Create a standard house relationship graph.

    Args:
        bedrooms: Number of bedrooms (1-5)
        bathrooms: Number of bathrooms (1-3)
        has_garage: Include garage and mudroom
        open_concept: Open living/dining/kitchen
    """
    graph = SpatialGraph()

    # Entry
    graph.add_room("entry", "entry", min_area=50)

    # Public zone
    graph.add_room("living", "living", min_area=200)
    graph.add_room("dining", "dining", min_area=100)
    graph.add_room("kitchen", "kitchen", min_area=120)

    # Entry connections
    graph.connect("entry", "living")

    # Public zone relationships
    if open_concept:
        graph.open_to("living", "dining")
        graph.open_to("dining", "kitchen")
        graph.adjacent("living", "kitchen")
    else:
        graph.connect("living", "dining", OpeningType.CASED_OPENING)
        graph.connect("dining", "kitchen")

    # Hallway (if multiple bedrooms)
    if bedrooms > 1:
        graph.add_room("hallway", "hallway", min_area=50)
        graph.connect("living", "hallway")

    # Primary bedroom + bath
    graph.add_room("primary_bedroom", "primary_bedroom", min_area=180)
    graph.add_room("primary_bath", "primary_bath", min_area=70)
    graph.add_room("primary_closet", "walk_in_closet", min_area=40)

    if bedrooms > 1:
        graph.connect("hallway", "primary_bedroom")
    else:
        graph.connect("living", "primary_bedroom")

    graph.attached("primary_bedroom", "primary_bath")
    graph.attached("primary_bedroom", "primary_closet")

    # Additional bedrooms
    for i in range(2, bedrooms + 1):
        room_id = f"bedroom_{i}"
        closet_id = f"closet_{i}"
        graph.add_room(room_id, "bedroom", name=f"Bedroom {i}", min_area=120)
        graph.add_room(closet_id, "closet", name=f"Closet {i}", min_area=15)
        graph.connect("hallway", room_id)
        graph.attached(room_id, closet_id)

    # Additional bathrooms
    if bathrooms > 1:
        graph.add_room("bathroom_2", "bathroom", name="Bathroom 2", min_area=50)
        graph.connect("hallway", "bathroom_2")

        # Group wet rooms
        graph.group("primary_bath", "bathroom_2")

    if bathrooms > 2:
        # Powder room near entry
        graph.add_room("powder_room", "powder_room", min_area=25)
        graph.connect("entry", "powder_room")

    # Laundry
    graph.add_room("laundry", "laundry", min_area=40)
    if bedrooms > 1:
        graph.connect("hallway", "laundry")
    else:
        graph.connect("kitchen", "laundry")

    # Group wet rooms for plumbing efficiency
    wet_rooms = ["kitchen", "primary_bath", "laundry"]
    if bathrooms > 1:
        wet_rooms.append("bathroom_2")
    graph.group(*wet_rooms)

    # Garage + mudroom
    if has_garage:
        graph.add_room("garage", "garage", min_area=400)
        graph.add_room("mudroom", "mudroom", min_area=50)
        graph.connect("garage", "mudroom")
        graph.connect("mudroom", "kitchen")

        # Isolate garage from bedrooms (noise, fumes)
        graph.isolate("garage", "primary_bedroom")
        for i in range(2, bedrooms + 1):
            graph.isolate("garage", f"bedroom_{i}")

    return graph


# =============================================================================
# TEST
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("ROOM RELATIONSHIP MODEL TEST")
    print("=" * 60)

    # Create a 3BR/2BA house
    graph = create_standard_house(bedrooms=3, bathrooms=2, has_garage=True, open_concept=True)

    # Validate
    issues = graph.validate()
    if issues:
        print("\nValidation Issues:")
        for issue in issues:
            print(f"  - {issue}")
    else:
        print("\nValidation: OK")

    # Summary
    print("\n" + graph.summary())

    # Show adjacency requirements
    print("\nAdjacency Requirements:")
    for room_id, adjacent_to in graph.get_adjacency_requirements().items():
        if adjacent_to:
            print(f"  {room_id}: must be adjacent to {adjacent_to}")

    # Show separation requirements
    print("\nSeparation Requirements:")
    for room_id, isolated_from in graph.get_separation_requirements().items():
        if isolated_from:
            print(f"  {room_id}: must NOT be adjacent to {isolated_from}")

    # Show exterior requirements
    print("\nExterior Wall Required:")
    for room_id in graph.get_exterior_required_rooms():
        print(f"  {room_id}")

    # Show wet rooms
    print("\nWet Rooms (need plumbing):")
    for room_id in graph.get_wet_rooms():
        print(f"  {room_id}")
