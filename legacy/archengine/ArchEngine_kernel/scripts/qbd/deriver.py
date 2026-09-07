"""Derivation rules for QBD Algebra.

Derivations compute implied values from inputs.
They run after validation, before solving.
"""

from typing import Dict, List, Any, Optional, Tuple
from copy import deepcopy
import math

from .state import QBDState
from .defaults import (
    get_room_defaults, get_furniture_dimensions,
    FURNITURE_DEFAULTS, CIRCULATION_FACTORS,
    mm_to_m, m_to_mm, sqft_to_sqm
)


class QBDDeriver:
    """Derive implied values from state."""

    def __init__(self, state: QBDState):
        self.state = state

    def derive_all(self) -> Dict[str, Any]:
        """Run all derivation rules and return derived values.

        Returns a dictionary of derived values that can be applied to state.
        Does not modify state directly.
        """
        derived = {
            "rooms": {},
            "total_program": {},
            "window_preferences": {},
        }

        # Derive room sizes from furniture
        for room in self.state.rooms:
            room_id = room.get("id")
            room_derived = self._derive_room_size(room)
            if room_derived:
                derived["rooms"][room_id] = room_derived

        # Derive total program area
        derived["total_program"] = self._derive_total_program()

        # Derive window orientation preferences
        derived["window_preferences"] = self._derive_window_preferences()

        # Build adjacency graph
        derived["adjacency_graph"] = self._build_adjacency_graph()

        return derived

    # =========================================================================
    # Room Size Derivation
    # =========================================================================

    def _derive_room_size(self, room: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Derive room size from furniture.

        Formula:
        room.area_min = sum(furniture.bounds) + sum(furniture.clearances) + buffer

        Returns dict with derived area_min, width_min, length_min
        """
        furniture = room.get("furniture", [])
        if not furniture:
            return None

        total_footprint = 0.0

        for item in furniture:
            furniture_type = item.get("type")
            size = item.get("size")

            # Construct lookup key
            lookup_key = furniture_type
            if size:
                lookup_key = f"{size}_{furniture_type}"

            dims = get_furniture_dimensions(lookup_key)
            if not dims:
                # Try just the type
                dims = get_furniture_dimensions(furniture_type)

            if dims:
                total_footprint += dims.total_footprint
            else:
                # Estimate from provided dimensions
                width = item.get("width", 1000)  # mm
                length = item.get("length", 1000)
                clearance = item.get("clearance", {})
                c_front = clearance.get("front", 600)
                c_back = clearance.get("back", 0)
                c_left = clearance.get("left", 300)
                c_right = clearance.get("right", 300)

                total_width = width + c_left + c_right
                total_length = length + c_front + c_back
                total_footprint += (total_width * total_length) / 1_000_000

        # Apply buffer based on room type
        room_type = room.get("type", "bedroom")
        buffer_pct = self._get_buffer_percentage(room_type)
        derived_area = total_footprint * (1 + buffer_pct)

        # Get existing values
        current_area_min = room.get("area_min")

        # Only derive if not already specified or if derived is larger
        if current_area_min is None or derived_area > current_area_min:
            # Derive dimensions from area using aspect ratio
            width, length = self._derive_dimensions_from_area(
                derived_area, room_type
            )

            return {
                "area_min": round(derived_area, 1),
                "width_min": width,
                "length_min": length,
                "_derived_from": "furniture",
            }

        return None

    def _get_buffer_percentage(self, room_type: str) -> float:
        """Get buffer percentage for room type."""
        buffers = {
            "bedroom": 0.15,
            "primary_bedroom": 0.15,
            "bathroom": 0.10,
            "ensuite": 0.10,
            "kitchen": 0.20,
            "living": 0.15,
            "dining": 0.15,
            "office": 0.15,
            "laundry": 0.10,
        }
        return buffers.get(room_type, 0.15)

    def _derive_dimensions_from_area(
        self,
        area_sqm: float,
        room_type: str
    ) -> Tuple[int, int]:
        """Derive width and length from area using aspect ratio rules.

        Returns (width_mm, length_mm)
        """
        defaults = get_room_defaults(room_type)

        # Target middle of aspect ratio range
        target_ratio = (defaults.aspect_ratio_min + defaults.aspect_ratio_max) / 2

        # area = width * length
        # width/length = ratio
        # width = length * ratio
        # area = length * ratio * length = length² * ratio
        # length = sqrt(area / ratio)

        area_mm2 = area_sqm * 1_000_000
        length = math.sqrt(area_mm2 / target_ratio)
        width = length * target_ratio

        # Round to nearest 100mm
        width = round(width / 100) * 100
        length = round(length / 100) * 100

        return (int(width), int(length))

    # =========================================================================
    # Total Program Derivation
    # =========================================================================

    def _derive_total_program(self) -> Dict[str, Any]:
        """Derive total program area requirements."""
        total_min = 0.0
        total_max = 0.0
        rooms_counted = 0

        for room in self.state.rooms:
            area_min = room.get("area_min")
            area_max = room.get("area_max")

            if area_min:
                total_min += area_min
                rooms_counted += 1
            if area_max:
                total_max += area_max

        # Apply circulation factor
        open_plan = self.state.priorities.get("open_plan", 5)
        if open_plan >= 8:
            circ_factor = CIRCULATION_FACTORS["open_plan_high"]
        elif open_plan <= 2:
            circ_factor = CIRCULATION_FACTORS["defined_rooms_high"]
        else:
            circ_factor = CIRCULATION_FACTORS["balanced"]

        return {
            "rooms_area_min": round(total_min, 1),
            "rooms_area_max": round(total_max, 1),
            "circulation_factor": circ_factor,
            "total_with_circulation": round(total_min * circ_factor, 1),
            "rooms_counted": rooms_counted,
        }

    # =========================================================================
    # Window Preference Derivation
    # =========================================================================

    def _derive_window_preferences(self) -> Dict[str, str]:
        """Derive window orientation preferences for rooms."""
        preferences = {}

        # Get site orientation
        site = self.state.site
        front_faces = site.get("orientation", {}).get("front_faces")

        # Get priority weights
        light_priority = self.state.priorities.get("natural_light", 5)

        for room in self.state.rooms:
            room_id = room.get("id")
            room_type = room.get("type")

            # Check if already specified
            explicit = room.get("window_preferences", {}).get("orientation")
            if explicit:
                preferences[room_id] = explicit
                continue

            # Derive based on room type
            if room_type in ("bedroom",):
                # Bedrooms prefer east (morning light)
                preferences[room_id] = "east"
            elif room_type in ("primary_bedroom",):
                # Primary bedroom - depends on light priority
                if light_priority >= 7:
                    preferences[room_id] = "south"  # Maximum light
                else:
                    preferences[room_id] = "east"
            elif room_type in ("living", "great_room", "family_room"):
                # Living spaces prefer south/west (afternoon light)
                preferences[room_id] = "south"
            elif room_type in ("kitchen",):
                # Kitchen prefers east or south
                preferences[room_id] = "east"
            elif room_type in ("dining",):
                # Dining prefers west (dinner time light)
                preferences[room_id] = "west"
            elif room_type in ("office",):
                # Office - north light is even, no glare
                preferences[room_id] = "north"
            elif room_type in ("bathroom", "ensuite", "powder_room", "laundry"):
                # Utility rooms - minimal preference
                preferences[room_id] = None
            else:
                preferences[room_id] = None

        return preferences

    # =========================================================================
    # Adjacency Graph
    # =========================================================================

    def _build_adjacency_graph(self) -> Dict[str, Any]:
        """Build a graph representation of room relationships.

        Returns:
        {
            "nodes": ["room-1", "room-2", ...],
            "edges": [
                {"from": "room-1", "to": "room-2", "type": "adjacency", "strength": "required"},
                ...
            ]
        }
        """
        nodes = [r.get("id") for r in self.state.rooms]
        edges = []

        for adj in self.state.adjacencies:
            edges.append({
                "from": adj.get("room_a"),
                "to": adj.get("room_b"),
                "type": "adjacency",
                "strength": adj.get("strength", "required"),
                "connection": adj.get("connection_type", "door"),
            })

        for sep in self.state.separations:
            edges.append({
                "from": sep.get("room_a"),
                "to": sep.get("room_b"),
                "type": "separation",
                "strength": sep.get("strength", "required"),
                "buffer": sep.get("buffer"),
            })

        return {
            "nodes": nodes,
            "edges": edges,
        }


def derive_values(state: QBDState) -> Dict[str, Any]:
    """Convenience function to derive values from state."""
    deriver = QBDDeriver(state)
    return deriver.derive_all()


def apply_derived_to_state(state: QBDState, derived: Dict[str, Any]):
    """Apply derived values back to state.

    This modifies the state's internal schema with derived values.
    Only applies values that weren't explicitly set.
    """
    for room_id, room_derived in derived.get("rooms", {}).items():
        for room in state._schema["rooms"]:
            if room.get("id") == room_id:
                # Only apply if not already set
                if room.get("area_min") is None and "area_min" in room_derived:
                    room["area_min"] = room_derived["area_min"]
                if room.get("width_min") is None and "width_min" in room_derived:
                    room["width_min"] = room_derived["width_min"]
                if room.get("length_min") is None and "length_min" in room_derived:
                    room["length_min"] = room_derived["length_min"]
                break
