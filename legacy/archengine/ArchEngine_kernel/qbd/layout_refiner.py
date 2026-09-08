"""
Layout Refiner - Post-Solver Refining Pass

Takes a PlacedLayout from any solver and applies intelligent refinements:
1. Remove walls between rooms that should be open (open plan)
2. Add doors between adjacent rooms based on circulation patterns
3. Add openings (windows) to exterior walls
4. Remove redundant/dead-end walls

Usage:
    from layout_refiner import LayoutRefiner, DesignFragment
    
    refiner = LayoutRefiner(layout)
    refiner.apply_fragment(DesignFragment.OPEN_PLAN, ["kitchen", "living", "dining"])
    refiner.add_doors_between(["hallway", "bedroom"])
    refiner.add_windows_to_exterior()
    refined_layout = refiner.get_refined_layout()
"""

from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from enum import Enum, auto
import math
from collections import defaultdict

from coordinate_solver import PlacedLayout, PlacedRoom, WallCoordinate, Point
from wall_graph import WallSegment, WallOpening, WallType, OpeningType


class DesignFragment(Enum):
    """High-level design patterns that can be applied to layouts."""
    OPEN_PLAN = "open_plan"           # Combine rooms into single open space
    PRIVATE_WING = "private_wing"     # Group bedrooms away from public areas  
    WORKSHOP_LAYOUT = "workshop"      # Optimize tool workflow
    GARAGE_ACCESS = "garage"          # Optimize garage entry flow
    EFFICIENT_CIRCULATION = "efficient"  # Minimize hallway space
    MAXIMIZE_LIGHT = "light"          # Prioritize window placement
    STORAGE_OPTIMIZED = "storage"     # Maximize closet/storage


@dataclass
class RoomGroup:
    """A group of rooms that form a functional zone."""
    name: str
    room_ids: Set[str]
    is_open: bool = False  # If True, remove interior walls between these rooms


@dataclass
class DoorPlacement:
    """Specification for a door between two rooms."""
    room1: str
    room2: str
    door_type: OpeningType = OpeningType.DOOR
    width: float = 3.0  # feet
    position: float = 0.5  # 0-1 along wall (0.5 = center)
    priority: int = 1  # Higher = more important


@dataclass
class WindowPlacement:
    """Specification for a window on an exterior wall."""
    room_id: str
    wall_edge: str  # north, south, east, west
    width: float = 4.0  # feet
    position: float = 0.5  # 0-1 along wall
    sill_height: float = 3.0  # feet


class LayoutRefiner:
    """
    Refines a PlacedLayout by applying design patterns and adding openings.
    
    This is the "smart pass" after brute-force solver placement:
    - Removes walls between rooms that should be open
    - Adds doors between rooms that need circulation
    - Adds windows to exterior walls based on room type
    - Optimizes wall topology for better flow
    """
    
    def __init__(self, layout: PlacedLayout):
        self.original_layout = layout
        self.rooms = dict(layout.rooms)  # Copy so we can modify
        self.walls = list(layout.walls)  # Copy so we can modify
        
        # Track modifications
        self.removed_walls: Set[str] = set()
        self.added_openings: List[Tuple[str, Point, Point, OpeningType]] = []
        self.merged_rooms: Dict[str, str] = {}  # old_room -> new_room
        
        # Build room adjacency map
        self._build_adjacency()
    
    def _build_adjacency(self):
        """Build map of which rooms touch which other rooms."""
        self.room_adjacency: Dict[str, Set[str]] = defaultdict(set)
        self.wall_map: Dict[Tuple[str, str], WallCoordinate] = {}
        
        for wall in self.walls:
            if wall.room1 != "exterior" and wall.room2 != "exterior":
                # Interior wall between two rooms
                if wall.room1 not in self.removed_walls and wall.room2 not in self.removed_walls:
                    self.room_adjacency[wall.room1].add(wall.room2)
                    self.room_adjacency[wall.room2].add(wall.room1)
                    
                    # Store wall by canonical key
                    key = tuple(sorted([wall.room1, wall.room2]))
                    self.wall_map[key] = wall
    
    # =====================================================================
    # DESIGN FRAGMENTS
    # =====================================================================
    
    def apply_fragment(self, fragment: DesignFragment, room_ids: List[str] = None):
        """
        Apply a design fragment to the layout.
        
        Args:
            fragment: The design pattern to apply
            room_ids: Specific rooms to apply to (if None, applies to all relevant)
        """
        if fragment == DesignFragment.OPEN_PLAN:
            self._apply_open_plan(room_ids or self._get_public_rooms())
        elif fragment == DesignFragment.PRIVATE_WING:
            self._apply_private_wing(room_ids or self._get_bedroom_rooms())
        elif fragment == DesignFragment.EFFICIENT_CIRCULATION:
            self._apply_efficient_circulation()
        elif fragment == DesignFragment.MAXIMIZE_LIGHT:
            self._apply_maximize_light(room_ids)
        elif fragment == DesignFragment.WORKSHOP_LAYOUT:
            self._apply_workshop_layout(room_ids)
        elif fragment == DesignFragment.GARAGE_ACCESS:
            self._apply_garage_access(room_ids)
        elif fragment == DesignFragment.STORAGE_OPTIMIZED:
            self._apply_storage_optimized(room_ids)
    
    def _get_public_rooms(self) -> List[str]:
        """Get rooms that are typically public/open."""
        public_types = {"living", "kitchen", "dining", "great_room", "family_room"}
        return [r for r, room in self.rooms.items() 
                if any(pt in r.lower() for pt in public_types)]
    
    def _get_bedroom_rooms(self) -> List[str]:
        """Get bedroom rooms."""
        return [r for r in self.rooms.keys() if "bedroom" in r.lower()]
    
    def _apply_open_plan(self, room_ids: List[str]):
        """
        Create open plan by removing walls between specified rooms.
        
        Example: kitchen + living + dining = one open space
        """
        if len(room_ids) < 2:
            return
        
        print(f"[Refiner] Applying OPEN PLAN to: {room_ids}")
        
        # Find all walls between these rooms and mark for removal
        removed_count = 0
        for i, room1 in enumerate(room_ids):
            for room2 in room_ids[i+1:]:
                key = tuple(sorted([room1, room2]))
                if key in self.wall_map:
                    wall = self.wall_map[key]
                    self.removed_walls.add(wall.wall_id)
                    removed_count += 1
                    
                    # Update adjacency - these rooms now flow into each other
                    self.room_adjacency[room1].discard(room2)
                    self.room_adjacency[room2].discard(room1)
        
        print(f"[Refiner] Removed {removed_count} walls for open plan")
        
        # Merge room definitions for visualization
        # Keep the first room as the "main" room
        main_room = room_ids[0]
        for room_id in room_ids[1:]:
            self.merged_rooms[room_id] = main_room
    
    def _apply_private_wing(self, bedroom_ids: List[str]):
        """
        Ensure bedrooms are grouped and separated from public areas.
        
        - Adds hallway access to each bedroom
        - Ensures bedrooms don't open directly into living spaces
        """
        if not bedroom_ids:
            return
        
        print(f"[Refiner] Applying PRIVATE WING to: {bedroom_ids}")
        
        # Find or create hallway connection
        hallway = None
        for room_id in self.rooms:
            if "hall" in room_id.lower():
                hallway = room_id
                break
        
        if not hallway:
            # No hallway - try to find a circulation room
            for room_id in self.rooms:
                if any(x in room_id.lower() for x in ["entry", "corridor", "passage"]):
                    hallway = room_id
                    break
        
        if hallway:
            # Ensure each bedroom has a door from hallway
            for bedroom in bedroom_ids:
                if bedroom in self.room_adjacency[hallway]:
                    # Already adjacent - add door if not present
                    self.add_door_between(hallway, bedroom, OpeningType.DOOR, priority=5)
    
    def _apply_efficient_circulation(self):
        """Minimize hallway space by optimizing door placements."""
        print("[Refiner] Applying EFFICIENT CIRCULATION")
        
        # Find hallway rooms
        hallways = [r for r in self.rooms if "hall" in r.lower()]
        
        for hallway in hallways:
            adjacent = self.room_adjacency.get(hallway, set())
            
            # Add doors to all adjacent rooms
            for room in adjacent:
                if room not in ["exterior"]:
                    self.add_door_between(hallway, room, OpeningType.DOOR, priority=3)
    
    def _apply_maximize_light(self, room_ids: List[str] = None):
        """Add windows to rooms that need natural light."""
        priority_rooms = room_ids or self._get_public_rooms() + self._get_bedroom_rooms()
        
        print(f"[Refiner] Applying MAXIMIZE LIGHT to: {priority_rooms}")
        
        for room_id in priority_rooms:
            if room_id in self.rooms:
                self.add_windows_to_room(room_id, count=2)
    
    def _apply_workshop_layout(self, room_ids: List[str] = None):
        """Optimize workshop/tool room with wide openings."""
        workshop_ids = room_ids or [r for r in self.rooms if "workshop" in r.lower()]
        
        for workshop in workshop_ids:
            # Workshop needs wide access - use double doors or open arch
            adjacent = self.room_adjacency.get(workshop, set())
            for adj_room in adjacent:
                self.add_door_between(workshop, adj_room, OpeningType.DOUBLE_DOOR, width=6.0)
    
    def _apply_garage_access(self, room_ids: List[str] = None):
        """Optimize garage entry with mudroom/laundry proximity."""
        garage_ids = room_ids or [r for r in self.rooms if "garage" in r.lower()]
        
        for garage in garage_ids:
            # Find mudroom, laundry, or entry
            for room_id in self.rooms:
                if any(x in room_id.lower() for x in ["mud", "laundry", "entry"]):
                    if room_id in self.room_adjacency.get(garage, set()):
                        self.add_door_between(garage, room_id, OpeningType.DOOR, priority=10)
    
    def _apply_storage_optimized(self, room_ids: List[str] = None):
        """Maximize storage by optimizing closet placements."""
        # Find closets and their parent rooms
        closets = [r for r in self.rooms if "closet" in r.lower()]
        
        for closet in closets:
            # Find parent bedroom
            parent = None
            for bedroom in self._get_bedroom_rooms():
                if closet.replace("closet", "bedroom").replace("_2", "").replace("_3", "") in bedroom:
                    parent = bedroom
                    break
            
            if parent and parent in self.room_adjacency.get(closet, set()):
                # Use pocket door for closets to save space
                self.add_door_between(parent, closet, OpeningType.POCKET_DOOR, width=2.5)
    
    # =====================================================================
    # DOOR PLACEMENT
    # =====================================================================
    
    def add_door_between(self, room1: str, room2: str, 
                         door_type: OpeningType = OpeningType.DOOR,
                         width: float = 3.0,
                         position: float = 0.5,
                         priority: int = 1):
        """
        Add a door between two rooms.
        
        Args:
            room1, room2: Room IDs to connect
            door_type: Type of door/opening
            width: Door width in feet
            position: 0-1 along wall (0.5 = center)
            priority: Higher priority doors are placed first
        """
        key = tuple(sorted([room1, room2]))
        
        if key not in self.wall_map:
            print(f"[Refiner] Warning: No wall between {room1} and {room2}")
            return
        
        wall = self.wall_map[key]
        
        # Check if door already exists (wall.openings is list of tuples: (start, end, opening_type))
        if wall.openings:
            if any(o[2] == door_type for o in wall.openings if len(o) >= 3):
                return
        
        # Add opening to wall
        opening = WallOpening(door_type, width, position)
        
        # For now, store in our added_openings list
        # In actual implementation, we'd modify the wall coordinate
        door_start, door_end = self._calculate_opening_coords(wall, opening)
        if door_start and door_end:
            self.added_openings.append((wall.wall_id, door_start, door_end, door_type))
            print(f"[Refiner] Added {door_type.value} between {room1} and {room2}")
    
    def add_doors_between(self, room_list: List[str], 
                          door_type: OpeningType = OpeningType.DOOR):
        """Add doors between all adjacent rooms in the list."""
        for i, room1 in enumerate(room_list):
            for room2 in room_list[i+1:]:
                if room2 in self.room_adjacency.get(room1, set()):
                    self.add_door_between(room1, room2, door_type)
    
    def _calculate_opening_coords(self, wall: WallCoordinate, 
                                   opening: WallOpening) -> Tuple[Optional[Point], Optional[Point]]:
        """Calculate the coordinates of an opening along a wall."""
        length = wall.length
        if length < opening.width:
            return None, None
        
        # Direction vector
        dx = (wall.end.x - wall.start.x) / length
        dy = (wall.end.y - wall.start.y) / length
        
        # Opening center
        center_dist = length * opening.position
        center_x = wall.start.x + dx * center_dist
        center_y = wall.start.y + dy * center_dist
        
        # Opening start/end
        half_width = opening.width / 2
        start = Point(center_x - dx * half_width, center_y - dy * half_width)
        end = Point(center_x + dx * half_width, center_y + dy * half_width)
        
        return start, end
    
    # =====================================================================
    # WINDOW PLACEMENT
    # =====================================================================
    
    def add_windows_to_room(self, room_id: str, count: int = 1):
        """Add windows to a room's exterior walls."""
        if room_id not in self.rooms:
            return
        
        # Find exterior walls for this room
        exterior_walls = [w for w in self.walls 
                         if (w.room1 == room_id and w.room2 == "exterior") or
                            (w.room2 == room_id and w.room1 == "exterior")]
        
        for i, wall in enumerate(exterior_walls[:count]):
            # Add window opening
            window = WallOpening(OpeningType.WINDOW, width=4.0, position=0.5)
            start, end = self._calculate_opening_coords(wall, window)
            if start and end:
                self.added_openings.append((wall.wall_id, start, end, OpeningType.WINDOW))
                print(f"[Refiner] Added window to {room_id}")
    
    def add_windows_to_exterior(self, room_types: Set[str] = None):
        """
        Add windows to all exterior walls of specified room types.
        
        Args:
            room_types: Set of room types to add windows to (default: all)
        """
        for room_id, room in self.rooms.items():
            if room_types and not any(t in room_id.lower() for t in room_types):
                continue
            
            self.add_windows_to_room(room_id, count=1)
    
    # =====================================================================
    # WALL REMOVAL
    # =====================================================================
    
    def remove_wall(self, room1: str, room2: str):
        """Remove the wall between two rooms."""
        key = tuple(sorted([room1, room2]))
        if key in self.wall_map:
            wall = self.wall_map[key]
            self.removed_walls.add(wall.wall_id)
            print(f"[Refiner] Removed wall between {room1} and {room2}")
    
    def remove_redundant_walls(self):
        """
        Remove walls that serve no structural purpose.
        
        Examples:
        - Walls between merged rooms
        - Walls that create dead-end spaces
        """
        # Find walls that are "orphaned" (one side has no other connections)
        to_remove = []
        
        for wall in self.walls:
            if wall.wall_id in self.removed_walls:
                continue
            
            # Skip exterior walls
            if wall.room1 == "exterior" or wall.room2 == "exterior":
                continue
            
            # Check if either room is isolated
            room1_connections = len(self.room_adjacency.get(wall.room1, set()))
            room2_connections = len(self.room_adjacency.get(wall.room2, set()))
            
            # If removing this wall wouldn't disconnect anything
            if room1_connections > 1 and room2_connections > 1:
                # Check if this wall has no doors (just a blank wall between spaces)
                if not wall.openings:
                    # Could potentially remove for more open feel
                    pass  # For now, keep structural walls
        
        for wall_id in to_remove:
            self.removed_walls.add(wall_id)
    
    # =====================================================================
    # OUTPUT
    # =====================================================================
    
    def get_refined_layout(self) -> PlacedLayout:
        """
        Get the refined layout with all modifications applied.
        
        Returns:
            New PlacedLayout with refined walls and openings
        """
        # Filter out removed walls
        refined_walls = [w for w in self.walls if w.wall_id not in self.removed_walls]
        
        # Add openings to walls
        for wall_id, start, end, opening_type in self.added_openings:
            for wall in refined_walls:
                if wall.wall_id == wall_id:
                    wall.openings.append((start, end, opening_type))
                    break
        
        # Create new layout
        refined_layout = PlacedLayout(
            rooms=self.rooms,
            walls=refined_walls,
            building_bounds=self.original_layout.building_bounds,
            is_complete=self.original_layout.is_complete,
            unplaced_rooms=self.original_layout.unplaced_rooms,
            score=self.original_layout.score
        )
        
        # Add metadata about refinements
        refined_layout.refinements = {
            "removed_walls": list(self.removed_walls),
            "added_openings": len(self.added_openings),
            "merged_rooms": self.merged_rooms
        }
        
        print(f"[Refiner] Refined layout: {len(refined_walls)} walls, {len(self.added_openings)} openings")
        
        return refined_layout
    
    def get_summary(self) -> str:
        """Get summary of refinements applied."""
        lines = [
            "Layout Refiner Summary:",
            f"  Original walls: {len(self.walls)}",
            f"  Removed walls: {len(self.removed_walls)}",
            f"  Added openings: {len(self.added_openings)}",
            f"  Merged room groups: {len(set(self.merged_rooms.values()))}",
        ]
        
        if self.merged_rooms:
            lines.append("  Merges:")
            for old, new in self.merged_rooms.items():
                lines.append(f"    {old} → {new}")
        
        return "\n".join(lines)


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def refine_layout(layout: PlacedLayout, 
                  fragments: List[Tuple[DesignFragment, List[str]]] = None) -> PlacedLayout:
    """
    Convenience function to refine a layout with common defaults.
    
    Args:
        layout: The PlacedLayout from a solver
        fragments: List of (fragment_type, room_ids) to apply
    
    Returns:
        Refined PlacedLayout
    """
    refiner = LayoutRefiner(layout)
    
    # Apply default fragments if none specified
    if fragments is None:
        fragments = [
            (DesignFragment.OPEN_PLAN, None),  # Auto-detect public rooms
            (DesignFragment.PRIVATE_WING, None),  # Auto-detect bedrooms
            (DesignFragment.EFFICIENT_CIRCULATION, None),
        ]
    
    for fragment, room_ids in fragments:
        refiner.apply_fragment(fragment, room_ids)
    
    # Add windows to all exterior rooms
    refiner.add_windows_to_exterior()
    
    return refiner.get_refined_layout()


# =============================================================================
# TEST
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("LAYOUT REFINER TEST")
    print("=" * 60)
    
    # This would normally come from a solver
    print("\nLayoutRefiner module loaded.")
    print("Use: refiner = LayoutRefiner(layout)")
    print("     refiner.apply_fragment(DesignFragment.OPEN_PLAN, ['kitchen', 'living'])")
    print("     refined = refiner.get_refined_layout()")
