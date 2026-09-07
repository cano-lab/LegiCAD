"""State management and lifecycle for QBD Algebra.

State progresses through: EMPTY → ACCUMULATING → COMPLETE → SOLVED → LOCKED
"""

from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from enum import Enum
from copy import deepcopy
from datetime import datetime
import json

from .templates import (
    create_master_template,
    create_room_template,
    create_adjacency_template,
    create_separation_template,
    apply_defaults_to_room,
)
from .fragments import Fragment, FragmentAction
from .errors import (
    QBDError, QBDWarning, ValidationResult,
    locked_state_error, unknown_reference_error
)


class StateLifecycle(Enum):
    """State lifecycle stages."""
    EMPTY = "empty"
    ACCUMULATING = "accumulating"
    COMPLETE = "complete"
    SOLVED = "solved"
    LOCKED = "locked"


@dataclass
class StateVersion:
    """A version snapshot of the state."""
    version: int
    timestamp: str
    lifecycle: StateLifecycle
    fragments_count: int
    score: Optional[float] = None
    changes_from_previous: List[str] = field(default_factory=list)


@dataclass
class Assumption:
    """A default value used in place of user input."""
    question_id: str
    default_used: Any
    timestamp: str
    can_revisit: bool = True


class QBDState:
    """The main state container for QBD Algebra."""

    def __init__(self):
        """Initialize empty state."""
        self._schema: Dict[str, Any] = create_master_template()
        self._lifecycle: StateLifecycle = StateLifecycle.EMPTY
        self._fragments: List[Fragment] = []
        self._versions: List[StateVersion] = []
        self._assumptions: List[Assumption] = []
        self._solved_layout: Optional[Dict[str, Any]] = None
        self._current_version: int = 0

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def lifecycle(self) -> StateLifecycle:
        """Current lifecycle stage."""
        return self._lifecycle

    @property
    def schema(self) -> Dict[str, Any]:
        """Current schema (read-only copy)."""
        return deepcopy(self._schema)

    @property
    def rooms(self) -> List[Dict[str, Any]]:
        """List of rooms."""
        return self._schema.get("rooms", [])

    @property
    def adjacencies(self) -> List[Dict[str, Any]]:
        """List of adjacency relationships."""
        return self._schema.get("adjacencies", [])

    @property
    def separations(self) -> List[Dict[str, Any]]:
        """List of separation relationships."""
        return self._schema.get("separations", [])

    @property
    def site(self) -> Dict[str, Any]:
        """Site configuration."""
        return self._schema.get("site", {})

    @property
    def constraints(self) -> Dict[str, Any]:
        """Building constraints."""
        return self._schema.get("constraints", {})

    @property
    def priorities(self) -> Dict[str, int]:
        """Priority weights."""
        return self._schema.get("priorities", {})

    @property
    def solved_layout(self) -> Optional[Dict[str, Any]]:
        """The solved layout (if solved)."""
        return deepcopy(self._solved_layout) if self._solved_layout else None

    @property
    def fragment_count(self) -> int:
        """Number of fragments applied."""
        return len(self._fragments)

    # =========================================================================
    # Lifecycle Management
    # =========================================================================

    def _update_lifecycle(self):
        """Update lifecycle based on current state."""
        if self._lifecycle == StateLifecycle.LOCKED:
            return  # Can't change from locked without explicit unlock

        if not self._fragments:
            self._lifecycle = StateLifecycle.EMPTY
        elif self._is_complete():
            if self._solved_layout:
                self._lifecycle = StateLifecycle.SOLVED
            else:
                self._lifecycle = StateLifecycle.COMPLETE
        else:
            self._lifecycle = StateLifecycle.ACCUMULATING

    def _is_complete(self) -> bool:
        """Check if state has minimum requirements for solving."""
        # Need at least one room
        if not self.rooms:
            return False

        # Need site dimensions OR footprint constraint
        site = self.site
        constraints = self.constraints

        has_site_dims = (
            site.get("width") is not None and
            site.get("depth") is not None
        )
        has_footprint = constraints.get("footprint_max") is not None

        if not (has_site_dims or has_footprint):
            return False

        return True

    def lock(self):
        """Lock the state."""
        if self._lifecycle != StateLifecycle.SOLVED:
            raise ValueError("Can only lock a solved state")
        self._lifecycle = StateLifecycle.LOCKED
        self._save_version()

    def unlock(self):
        """Unlock the state (creates new version)."""
        if self._lifecycle != StateLifecycle.LOCKED:
            raise ValueError("State is not locked")
        self._lifecycle = StateLifecycle.SOLVED
        self._current_version += 1

    def _save_version(self):
        """Save current state as a version."""
        self._versions.append(StateVersion(
            version=self._current_version,
            timestamp=datetime.now().isoformat(),
            lifecycle=self._lifecycle,
            fragments_count=len(self._fragments),
            score=self._solved_layout.get("score") if self._solved_layout else None,
        ))

    # =========================================================================
    # Room Operations
    # =========================================================================

    def get_room(self, room_id: str) -> Optional[Dict[str, Any]]:
        """Get a room by ID."""
        for room in self.rooms:
            if room.get("id") == room_id:
                return deepcopy(room)
        return None

    def get_room_by_type(self, room_type: str) -> List[Dict[str, Any]]:
        """Get all rooms of a specific type."""
        return [r for r in self.rooms if r.get("type") == room_type]

    def _add_room(self, room_data: Dict[str, Any]) -> str:
        """Internal: Add a room to state."""
        room = create_room_template(
            name=room_data.get("name"),
            room_type=room_data.get("type")
        )

        # Merge additional fields
        for key, value in room_data.items():
            if key in room and value is not None:
                room[key] = value

        # Apply type defaults
        room = apply_defaults_to_room(room)

        self._schema["rooms"].append(room)
        return room["id"]

    def _remove_room(self, room_id: str):
        """Internal: Remove a room and cascade to relationships."""
        # Remove the room
        self._schema["rooms"] = [
            r for r in self._schema["rooms"] if r.get("id") != room_id
        ]

        # Remove adjacencies involving this room
        self._schema["adjacencies"] = [
            a for a in self._schema["adjacencies"]
            if a.get("room_a") != room_id and a.get("room_b") != room_id
        ]

        # Remove separations involving this room
        self._schema["separations"] = [
            s for s in self._schema["separations"]
            if s.get("room_a") != room_id and s.get("room_b") != room_id
        ]

    def _update_room(self, room_id: str, updates: Dict[str, Any]):
        """Internal: Update room properties."""
        for room in self._schema["rooms"]:
            if room.get("id") == room_id:
                for key, value in updates.items():
                    if key in room:
                        room[key] = value
                break

    # =========================================================================
    # Relationship Operations
    # =========================================================================

    def _set_adjacency(
        self,
        room_a: str,
        room_b: str,
        strength: str = "required",
        connection_type: str = "door"
    ):
        """Internal: Set an adjacency relationship."""
        # Remove existing adjacency between these rooms
        self._schema["adjacencies"] = [
            a for a in self._schema["adjacencies"]
            if not (
                (a["room_a"] == room_a and a["room_b"] == room_b) or
                (a["room_a"] == room_b and a["room_b"] == room_a)
            )
        ]

        # Add new adjacency
        adjacency = create_adjacency_template(room_a, room_b, strength, connection_type)
        self._schema["adjacencies"].append(adjacency)

    def _remove_adjacency(self, room_a: str, room_b: str):
        """Internal: Remove an adjacency relationship."""
        self._schema["adjacencies"] = [
            a for a in self._schema["adjacencies"]
            if not (
                (a["room_a"] == room_a and a["room_b"] == room_b) or
                (a["room_a"] == room_b and a["room_b"] == room_a)
            )
        ]

    def _set_separation(
        self,
        room_a: str,
        room_b: str,
        strength: str = "required",
        buffer: int = None
    ):
        """Internal: Set a separation relationship."""
        # Remove existing separation
        self._schema["separations"] = [
            s for s in self._schema["separations"]
            if not (
                (s["room_a"] == room_a and s["room_b"] == room_b) or
                (s["room_a"] == room_b and s["room_b"] == room_a)
            )
        ]

        # Add new separation
        separation = create_separation_template(room_a, room_b, strength, buffer)
        self._schema["separations"].append(separation)

    # =========================================================================
    # Fragment Application
    # =========================================================================

    def apply_fragment(self, fragment: Fragment) -> ValidationResult:
        """Apply a fragment to the state.

        Args:
            fragment: The fragment to apply

        Returns:
            ValidationResult with any errors or warnings
        """
        result = ValidationResult(valid=True)

        # Check if locked
        if self._lifecycle == StateLifecycle.LOCKED:
            result.add_error(locked_state_error())
            return result

        # Apply based on action type
        try:
            self._apply_fragment_internal(fragment, result)
        except Exception as e:
            result.add_error(QBDError(
                code="FRAGMENT_FAILED",
                error_type="structural",
                message=str(e),
                fragment_id=fragment.id
            ))
            return result

        if result.valid:
            self._fragments.append(fragment)
            self._update_lifecycle()
            # Clear solved layout since state changed
            if self._lifecycle != StateLifecycle.LOCKED:
                self._solved_layout = None

        return result

    def _apply_fragment_internal(self, fragment: Fragment, result: ValidationResult):
        """Internal fragment application logic."""
        action = fragment.action
        data = fragment.data

        if action == FragmentAction.ADD_ROOM:
            room_id = self._add_room(data["room"])
            # Store generated ID for reference
            fragment.data["_generated_id"] = room_id

        elif action == FragmentAction.REMOVE_ROOM:
            room_id = data["room_id"]
            if not self.get_room(room_id):
                result.add_error(unknown_reference_error("room", room_id, fragment.id))
                return
            # Check if pinned
            room = self.get_room(room_id)
            if room.get("constraints", {}).get("pinned"):
                from .errors import pinned_element_error
                result.add_error(pinned_element_error("room", room_id, "remove"))
                return
            self._remove_room(room_id)

        elif action == FragmentAction.UPDATE_ROOM:
            room_id = data["room_id"]
            if not self.get_room(room_id):
                result.add_error(unknown_reference_error("room", room_id, fragment.id))
                return
            self._update_room(room_id, data["updates"])

        elif action == FragmentAction.ADD_FURNITURE:
            room_id = data["room_id"]
            room = self.get_room(room_id)
            if not room:
                result.add_error(unknown_reference_error("room", room_id, fragment.id))
                return
            # Add furniture to room
            for r in self._schema["rooms"]:
                if r["id"] == room_id:
                    r.setdefault("furniture", []).append(data["furniture"])
                    break

        elif action == FragmentAction.SET_ADJACENCY:
            room_a, room_b = data["room_a"], data["room_b"]
            if not self.get_room(room_a):
                result.add_error(unknown_reference_error("room", room_a, fragment.id))
                return
            if not self.get_room(room_b):
                result.add_error(unknown_reference_error("room", room_b, fragment.id))
                return
            self._set_adjacency(
                room_a, room_b,
                data.get("strength", "required"),
                data.get("connection_type", "door")
            )

        elif action == FragmentAction.REMOVE_ADJACENCY:
            self._remove_adjacency(data["room_a"], data["room_b"])

        elif action == FragmentAction.SET_SEPARATION:
            room_a, room_b = data["room_a"], data["room_b"]
            if not self.get_room(room_a):
                result.add_error(unknown_reference_error("room", room_a, fragment.id))
                return
            if not self.get_room(room_b):
                result.add_error(unknown_reference_error("room", room_b, fragment.id))
                return
            self._set_separation(
                room_a, room_b,
                data.get("strength", "required"),
                data.get("buffer")
            )

        elif action == FragmentAction.SET_SITE:
            updates = data["updates"]
            site = self._schema["site"]
            for key, value in updates.items():
                if key in site:
                    if isinstance(site[key], dict) and isinstance(value, dict):
                        site[key].update(value)
                    else:
                        site[key] = value

        elif action == FragmentAction.SET_CONSTRAINT:
            target = data["target"]
            value = data["value"]
            if target in self._schema["constraints"]:
                self._schema["constraints"][target] = value

        elif action == FragmentAction.SET_PRIORITY:
            factor = data["factor"]
            value = data["value"]
            if factor in self._schema["priorities"]:
                self._schema["priorities"][factor] = max(1, min(10, value))

        elif action == FragmentAction.SET_STYLE:
            self._schema["character"]["style"] = data["style"]
            if "keywords" in data:
                self._schema["character"]["keywords"] = data["keywords"]
            if "avoid" in data:
                self._schema["character"]["avoid"] = data["avoid"]

        elif action == FragmentAction.PIN_ROOM:
            room_id = data["room_id"]
            for room in self._schema["rooms"]:
                if room["id"] == room_id:
                    room["constraints"]["pinned"] = True
                    if "locked_properties" in data:
                        room["constraints"]["locked_properties"] = data["locked_properties"]
                    break

        elif action == FragmentAction.UNPIN_ROOM:
            room_id = data["room_id"]
            for room in self._schema["rooms"]:
                if room["id"] == room_id:
                    room["constraints"]["pinned"] = False
                    room["constraints"]["locked_properties"] = []
                    break

    # =========================================================================
    # Serialization
    # =========================================================================

    def to_dict(self) -> Dict[str, Any]:
        """Export full state to dictionary."""
        return {
            "schema": self._schema,
            "lifecycle": self._lifecycle.value,
            "fragments": [f.to_dict() for f in self._fragments],
            "versions": [
                {
                    "version": v.version,
                    "timestamp": v.timestamp,
                    "lifecycle": v.lifecycle.value,
                    "fragments_count": v.fragments_count,
                    "score": v.score,
                }
                for v in self._versions
            ],
            "solved_layout": self._solved_layout,
            "current_version": self._current_version,
        }

    def to_json(self, indent: int = 2) -> str:
        """Export state to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "QBDState":
        """Load state from dictionary."""
        state = cls()
        state._schema = data.get("schema", create_master_template())
        state._lifecycle = StateLifecycle(data.get("lifecycle", "empty"))
        state._solved_layout = data.get("solved_layout")
        state._current_version = data.get("current_version", 0)
        # Note: fragments not restored (would need to re-parse)
        return state

    @classmethod
    def from_json(cls, json_str: str) -> "QBDState":
        """Load state from JSON string."""
        return cls.from_dict(json.loads(json_str))
