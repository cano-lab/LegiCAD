"""
Constraint System - Captures and visualizes design constraints

Constraints define WHY elements are positioned where they are.
This enables intent-driven editing instead of manual geometry manipulation.
"""
from typing import Dict, List, Set, Optional, Any
from enum import Enum
from dataclasses import dataclass, field
from PyQt6.QtCore import QObject, pyqtSignal


class ConstraintType(Enum):
    """Types of constraints between elements"""
    # Connection constraints
    CONNECTS_TO = "connects_to"          # Must have door
    ATTACHED_TO = "attached_to"          # Direct access (ensuite)
    OPEN_TO = "open_to"                  # No wall between

    # Separation constraints
    ISOLATED_FROM = "isolated_from"      # Cannot share wall
    BUFFERED_FROM = "buffered_from"      # Needs space between

    # Grouping constraints
    GROUPED_WITH = "grouped_with"        # Should be near (e.g., wet rooms)
    SAME_ZONE = "same_zone"              # Must be in same functional zone

    # Size constraints
    MIN_AREA = "min_area"                # Minimum square footage
    MAX_AREA = "max_area"                # Maximum square footage
    MIN_WIDTH = "min_width"              # Minimum width
    MIN_DEPTH = "min_depth"              # Minimum depth

    # Exterior constraints
    NEEDS_EXTERIOR = "needs_exterior"    # Must have exterior wall
    INTERIOR_ONLY = "interior_only"      # Should not have exterior wall

    # Positional constraints
    FIXED_POSITION = "fixed_position"    # Cannot move
    FIXED_SIZE = "fixed_size"            # Cannot resize


class ConstraintStrength(Enum):
    """How strictly a constraint is enforced"""
    HARD = "hard"        # Cannot be violated (code requirements)
    SOFT = "soft"        # Preferred but can be broken
    SUGGESTED = "suggested"  # Just a suggestion


@dataclass
class Constraint:
    """A single constraint on an element"""
    type: ConstraintType
    strength: ConstraintStrength = ConstraintStrength.SOFT
    target_id: Optional[str] = None     # Room/element this constraint relates to
    value: Optional[Any] = None         # Numerical value for size constraints
    reason: Optional[str] = None       # Why this constraint exists

    def __str__(self):
        """Human-readable description"""
        if self.type == ConstraintType.CONNECTS_TO:
            return f"Must connect to {self._target_name()}"
        elif self.type == ConstraintType.ATTACHED_TO:
            return f"Directly attached to {self._target_name()}"
        elif self.type == ConstraintType.OPEN_TO:
            return f"Open to {self._target_name()}"
        elif self.type == ConstraintType.ISOLATED_FROM:
            return f"Isolated from {self._target_name()}"
        elif self.type == ConstraintType.GROUPED_WITH:
            return f"Grouped with {self._target_name()} (nearby)"
        elif self.type == ConstraintType.MIN_AREA:
            return f"Minimum area: {self.value} sq ft"
        elif self.type == ConstraintType.NEEDS_EXTERIOR:
            return "Must have exterior wall"
        elif self.type == ConstraintType.INTERIOR_ONLY:
            return "Interior location preferred"
        elif self.type == ConstraintType.FIXED_POSITION:
            return "Position is fixed"
        elif self.type == ConstraintType.FIXED_SIZE:
            return "Size is fixed"
        else:
            return f"{self.type.value}"

    def _target_name(self) -> str:
        """Get readable name for target"""
        if self.target_id:
            return self.target_id.replace("_", " ").title()
        return "unknown"


@dataclass
class ElementConstraints:
    """All constraints on a single element (room, wall, door, etc.)"""
    element_id: str
    element_type: str  # "room", "wall", "door", "window"
    constraints: List[Constraint] = field(default_factory=list)

    def add_constraint(self, constraint: Constraint):
        """Add a constraint"""
        # Remove duplicate of same type/target
        self.constraints = [c for c in self.constraints
                           if not (c.type == constraint.type and
                                   c.target_id == constraint.target_id)]
        self.constraints.append(constraint)

    def get_constraints_by_type(self, constraint_type: ConstraintType) -> List[Constraint]:
        """Get all constraints of a specific type"""
        return [c for c in self.constraints if c.type == constraint_type]

    def get_constraints_to(self, target_id: str) -> List[Constraint]:
        """Get all constraints relating to another element"""
        return [c for c in self.constraints if c.target_id == target_id]

    def has_hard_constraint(self, constraint_type: ConstraintType) -> bool:
        """Check if there's a hard constraint of this type"""
        return any(c.type == constraint_type and
                   c.strength == ConstraintStrength.HARD
                   for c in self.constraints)


class ConstraintSystem(QObject):
    """
    Manages all constraints in the document.

    Captures WHY elements are positioned where they are,
    enabling intent-driven editing.
    """
    changed = pyqtSignal()  # Emitted when constraints change

    def __init__(self, parent=None):
        super().__init__(parent)
        self._constraints: Dict[str, ElementConstraints] = {}

    def get_element_constraints(self, element_id: str) -> ElementConstraints:
        """Get all constraints for an element"""
        if element_id not in self._constraints:
            self._constraints[element_id] = ElementConstraints(
                element_id=element_id,
                element_type="unknown"
            )
        return self._constraints[element_id]

    def add_constraint(self, element_id: str, constraint: Constraint):
        """Add a constraint to an element"""
        element = self.get_element_constraints(element_id)
        element.add_constraint(constraint)
        self.changed.emit()

    def get_relationship_between(self, element1_id: str, element2_id: str) -> Optional[Constraint]:
        """Get the constraint describing the relationship between two elements"""
        elem1 = self.get_element_constraints(element1_id)

        # Check for relationship constraints
        for c in elem1.constraints:
            if c.target_id == element2_id and c.type in [
                ConstraintType.CONNECTS_TO,
                ConstraintType.ATTACHED_TO,
                ConstraintType.OPEN_TO,
                ConstraintType.ISOLATED_FROM,
                ConstraintType.GROUPED_WITH
            ]:
                return c

        return None

    def get_all_related(self, element_id: str) -> List[str]:
        """Get all element IDs that have a relationship with this element"""
        related = set()
        element = self.get_element_constraints(element_id)

        for c in element.constraints:
            if c.target_id:
                related.add(c.target_id)

        # Also check what others have to us
        for other_id, other_elem in self._constraints.items():
            for c in other_elem.constraints:
                if c.target_id == element_id:
                    related.add(other_id)

        return list(related)

    def infer_constraints_from_layout(self, document) -> None:
        """
        Analyze the current layout and infer constraints.

        This is called after loading a QBD layout to capture
        the implicit constraints that were used to generate it.
        """
        if not hasattr(document, 'rooms'):
            return

        # Infer constraints from room adjacencies
        # document.rooms is a dict: {room_id: Room}
        for room_id, room in document.rooms.items():
            room_constraints = self.get_element_constraints(room_id)
            room_constraints.element_type = "room"

            # Check adjacencies
            if hasattr(document, 'adjacency'):
                # Add CONNECTS_TO constraint for each adjacent room
                adjacents = document.adjacency.get_adjacent_rooms(room_id)
                for adj in adjacents:
                    conn = Constraint(
                        type=ConstraintType.CONNECTS_TO,
                        strength=ConstraintStrength.SOFT,
                        target_id=adj,
                        reason="Room adjacency"
                    )
                    room_constraints.add_constraint(conn)

                # Check if room has exterior wall (heuristic from room type)
                if self._room_has_exterior(room_id):
                    room_constraints.add_constraint(Constraint(
                        type=ConstraintType.NEEDS_EXTERIOR,
                        strength=ConstraintStrength.SOFT,
                        reason="Exterior room type"
                    ))
                else:
                    room_constraints.add_constraint(Constraint(
                        type=ConstraintType.INTERIOR_ONLY,
                        strength=ConstraintStrength.SUGGESTED,
                        reason="Interior room type"
                    ))

            # Add minimum area constraint from room size
            current_area = room.area / 1000000.0  # Convert mm² to sq ft
            room_constraints.add_constraint(Constraint(
                type=ConstraintType.MIN_AREA,
                strength=ConstraintStrength.HARD,
                value=int(current_area),
                reason=f"Current size: {int(current_area)} sq ft"
            ))

        self.changed.emit()

    def _room_has_exterior(self, room_id: str) -> bool:
        """Check if a room has an exterior wall (heuristic from room type)"""
        # This is a simple heuristic - in practice we'd check wall positions
        # For now, assume certain room types prefer exterior
        exterior_rooms = {'living', 'dining', 'kitchen', 'office', 'bedroom', 'living_room', 'primary_bedroom'}
        room_type = room_id.split('_')[0] if '_' in room_id else room_id
        return room_type in exterior_rooms


# =============================================================================
# VISUALIZATION HELPERS
# =============================================================================

CONSTRAINT_COLORS = {
    ConstraintType.CONNECTS_TO: "#4CAF50",      # Green - connection
    ConstraintType.ATTACHED_TO: "#2196F3",     # Blue - direct access
    ConstraintType.OPEN_TO: "#00BCD4",         # Cyan - open
    ConstraintType.ISOLATED_FROM: "#F44336",   # Red - separation
    ConstraintType.BUFFERED_FROM: "#FF9800",   # Orange - buffer
    ConstraintType.GROUPED_WITH: "#9C27B0",    # Purple - grouping
    ConstraintType.MIN_AREA: "#607D8B",       # Blue gray - size
    ConstraintType.NEEDS_EXTERIOR: "#795548",  # Brown - exterior
    ConstraintType.INTERIOR_ONLY: "#9E9E9E",  # Gray - interior
    ConstraintType.FIXED_POSITION: "#212121", # Dark - fixed
}

STRENGTH_STYLES = {
    ConstraintStrength.HARD: "●",      # Solid circle
    ConstraintStrength.SOFT: "○",      # Open circle
    ConstraintStrength.SUGGESTED: "◌", # Circle with X
}
