"""
Action Parser - Extract structured actions from natural language.

Instead of having the LLM generate entire JSON schemas, this module:
1. Parses user intent into structured actions
2. Applies changes using deterministic code

This is much faster and more reliable with local/smaller LLMs.
"""

import json
import re
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from copy import deepcopy

from .config import LLMConfig
from .provider import Message, LLMProvider


# Action definitions for the LLM
ACTIONS_SCHEMA = """
Available actions (output ONE as JSON):

1. resize_room - Change room dimensions
   {"action": "resize_room", "room": "living|bedroom|kitchen|...", "scale": 1.2}
   {"action": "resize_room", "room": "master_bedroom", "width_mm": 4000, "depth_mm": 5000}

2. move_wall - Move a wall
   {"action": "move_wall", "wall_index": 0, "direction": "north|south|east|west", "amount_mm": 500}

3. add_window - Add window to wall
   {"action": "add_window", "wall_index": 2, "width_mm": 1200, "height_mm": 1400}

4. add_door - Add door to wall
   {"action": "add_door", "wall_index": 1, "width_mm": 900, "door_type": "interior|exterior"}

5. remove_element - Delete an element
   {"action": "remove_element", "element_type": "window|door|wall", "index": 3}

6. add_room - Add a new room
   {"action": "add_room", "room_type": "bathroom|bedroom|closet", "adjacent_to": "master_bedroom", "size_sqft": 50}

7. modify_opening - Change door/window properties
   {"action": "modify_opening", "element_type": "door|window", "index": 0, "width_mm": 1000}

Output ONLY the JSON action, no explanation.
"""

PARSE_PROMPT = """Given the building context and user request, output a single JSON action.

Building has:
- Rooms: {rooms}
- Walls: {wall_count} walls
- Doors: {door_count} doors
- Windows: {window_count} windows

{actions_schema}

User request: {request}

Output the JSON action:"""


@dataclass
class ParsedAction:
    """Represents a parsed action from user input."""
    action: str
    params: Dict[str, Any]
    confidence: float = 1.0


class ActionParser:
    """Parse natural language into structured actions."""

    def __init__(self, provider: LLMProvider = None):
        self.provider = provider

    def _get_provider(self) -> LLMProvider:
        if self.provider:
            return self.provider
        provider = LLMConfig.get_active()
        if not provider:
            raise RuntimeError("No LLM provider available")
        return provider

    def _get_room_names(self, schema: Dict[str, Any]) -> List[str]:
        """Extract room names/types from schema."""
        rooms = schema.get("rooms", {})
        if isinstance(rooms, dict):
            return [f"{r.get('name', r.get('type', k))}" for k, r in rooms.items()]
        return []

    def parse(self, request: str, schema: Dict[str, Any]) -> ParsedAction:
        """Parse a natural language request into a structured action.

        Args:
            request: User's natural language request
            schema: Current building schema (for context)

        Returns:
            ParsedAction with action type and parameters
        """
        provider = self._get_provider()

        prompt = PARSE_PROMPT.format(
            rooms=", ".join(self._get_room_names(schema)) or "unknown",
            wall_count=len(schema.get("walls_batch", [])),
            door_count=len(schema.get("doors", [])),
            window_count=len(schema.get("windows", [])),
            actions_schema=ACTIONS_SCHEMA,
            request=request
        )

        messages = [Message(role="user", content=prompt)]

        response = provider.chat(
            messages,
            temperature=0.1,  # Low temp for consistent parsing
            max_tokens=200    # Small output - just the action JSON
        )

        # Extract JSON from response
        content = response.content.strip()

        # Try to find JSON in response
        json_match = re.search(r'\{[^{}]*\}', content, re.DOTALL)
        if json_match:
            content = json_match.group(0)

        try:
            action_data = json.loads(content)
            action_type = action_data.pop("action", "unknown")
            return ParsedAction(action=action_type, params=action_data)
        except json.JSONDecodeError:
            # Fallback: try to infer action from keywords
            return self._fallback_parse(request)

    def _fallback_parse(self, request: str) -> ParsedAction:
        """Simple keyword-based fallback parsing."""
        request_lower = request.lower()

        if any(w in request_lower for w in ["bigger", "larger", "expand", "increase"]):
            # Try to find room name
            for room in ["living", "bedroom", "kitchen", "bathroom", "dining", "office"]:
                if room in request_lower:
                    return ParsedAction(
                        action="resize_room",
                        params={"room": room, "scale": 1.2},
                        confidence=0.6
                    )

        if any(w in request_lower for w in ["smaller", "reduce", "shrink"]):
            for room in ["living", "bedroom", "kitchen", "bathroom", "dining", "office"]:
                if room in request_lower:
                    return ParsedAction(
                        action="resize_room",
                        params={"room": room, "scale": 0.8},
                        confidence=0.6
                    )

        if "add window" in request_lower:
            return ParsedAction(
                action="add_window",
                params={"wall_index": 0, "width_mm": 1200, "height_mm": 1400},
                confidence=0.5
            )

        if "add door" in request_lower:
            return ParsedAction(
                action="add_door",
                params={"wall_index": 0, "width_mm": 900},
                confidence=0.5
            )

        return ParsedAction(action="unknown", params={"request": request}, confidence=0.0)


class ActionApplier:
    """Apply parsed actions to building schemas."""

    def apply(self, schema: Dict[str, Any], action: ParsedAction,
              pinned: Dict[str, List[str]] = None) -> Tuple[Dict[str, Any], str]:
        """Apply an action to a schema.

        Args:
            schema: Current building schema
            action: Parsed action to apply
            pinned: Pinned elements that cannot be modified

        Returns:
            Tuple of (modified_schema, description of what was done)
        """
        pinned = pinned or {}
        result = deepcopy(schema)

        method = getattr(self, f"_apply_{action.action}", None)
        if method:
            return method(result, action.params, pinned)
        else:
            return result, f"Unknown action: {action.action}"

    def _apply_resize_room(self, schema: Dict[str, Any], params: Dict[str, Any],
                           pinned: Dict[str, List[str]]) -> Tuple[Dict[str, Any], str]:
        """Resize a room by scaling its walls."""
        room_name = params.get("room", "").lower()
        scale = params.get("scale", 1.0)

        # Find the room
        rooms = schema.get("rooms", {})
        target_room = None
        target_room_id = None

        for room_id, room_data in rooms.items():
            name = room_data.get("name", room_data.get("type", "")).lower()
            if room_name in name or room_name in room_id.lower():
                # Check if pinned
                if room_id in pinned.get("rooms", []):
                    return schema, f"Cannot resize {room_name} - it is pinned"
                target_room = room_data
                target_room_id = room_id
                break

        if not target_room:
            return schema, f"Room '{room_name}' not found"

        # Get room bounds
        bounds = target_room.get("bounds", {})
        if not bounds:
            return schema, f"Room '{room_name}' has no bounds defined"

        # Calculate room center
        cx = bounds.get("x", 0) + bounds.get("width", 0) / 2
        cy = bounds.get("y", 0) + bounds.get("height", 0) / 2

        # Find walls that belong to this room and scale them
        walls = schema.get("walls_batch", [])
        modified_walls = 0

        for i, wall in enumerate(walls):
            if str(i) in pinned.get("walls", []):
                continue

            # Check if wall is near room bounds
            start = wall.get("start", [0, 0, 0])
            end = wall.get("end", [0, 0, 0])

            wall_cx = (start[0] + end[0]) / 2
            wall_cz = (start[2] + end[2]) / 2

            # If wall center is within room bounds, scale it
            if (bounds.get("x", 0) <= wall_cx <= bounds.get("x", 0) + bounds.get("width", 0) and
                bounds.get("y", 0) <= wall_cz <= bounds.get("y", 0) + bounds.get("height", 0)):

                # Scale wall endpoints relative to room center
                new_start = [
                    cx + (start[0] - cx) * scale,
                    start[1],
                    cy + (start[2] - cy) * scale
                ]
                new_end = [
                    cx + (end[0] - cx) * scale,
                    end[1],
                    cy + (end[2] - cy) * scale
                ]

                wall["start"] = new_start
                wall["end"] = new_end
                modified_walls += 1

        # Update room bounds
        new_width = bounds.get("width", 0) * scale
        new_height = bounds.get("height", 0) * scale
        target_room["bounds"] = {
            "x": cx - new_width / 2,
            "y": cy - new_height / 2,
            "width": new_width,
            "height": new_height
        }

        action_desc = "increased" if scale > 1 else "decreased"
        percent = abs(int((scale - 1) * 100))
        return schema, f"{room_name.title()} {action_desc} by {percent}% ({modified_walls} walls adjusted)"

    def _apply_add_window(self, schema: Dict[str, Any], params: Dict[str, Any],
                          pinned: Dict[str, List[str]]) -> Tuple[Dict[str, Any], str]:
        """Add a window to a wall."""
        wall_idx = params.get("wall_index", 0)
        width = params.get("width_mm", 1200)
        height = params.get("height_mm", 1400)

        walls = schema.get("walls_batch", [])
        if wall_idx >= len(walls):
            return schema, f"Wall {wall_idx} does not exist"

        if str(wall_idx) in pinned.get("walls", []):
            return schema, f"Cannot add window to wall {wall_idx} - wall is pinned"

        wall = walls[wall_idx]
        start = wall.get("start", [0, 0, 0])
        end = wall.get("end", [0, 0, 0])

        # Calculate wall length and midpoint offset
        import math
        wall_length = math.sqrt((end[0] - start[0])**2 + (end[2] - start[2])**2)
        offset = (wall_length - width) / 2  # Center the window

        windows = schema.get("windows", [])
        new_window = {
            "wall_index": wall_idx,
            "offset": offset,
            "width": width,
            "height": height,
            "sill_height": 900
        }
        windows.append(new_window)
        schema["windows"] = windows

        return schema, f"Added {width}mm x {height}mm window to wall {wall_idx}"

    def _apply_add_door(self, schema: Dict[str, Any], params: Dict[str, Any],
                        pinned: Dict[str, List[str]]) -> Tuple[Dict[str, Any], str]:
        """Add a door to a wall."""
        wall_idx = params.get("wall_index", 0)
        width = params.get("width_mm", 900)
        height = params.get("height_mm", 2100)
        door_type = params.get("door_type", "interior")

        walls = schema.get("walls_batch", [])
        if wall_idx >= len(walls):
            return schema, f"Wall {wall_idx} does not exist"

        if str(wall_idx) in pinned.get("walls", []):
            return schema, f"Cannot add door to wall {wall_idx} - wall is pinned"

        wall = walls[wall_idx]
        start = wall.get("start", [0, 0, 0])
        end = wall.get("end", [0, 0, 0])

        import math
        wall_length = math.sqrt((end[0] - start[0])**2 + (end[2] - start[2])**2)
        offset = (wall_length - width) / 2

        doors = schema.get("doors", [])
        new_door = {
            "wall_index": wall_idx,
            "offset": offset,
            "width": width,
            "height": height,
            "type": door_type,
            "swing": "left_in"
        }
        doors.append(new_door)
        schema["doors"] = doors

        return schema, f"Added {width}mm {door_type} door to wall {wall_idx}"

    def _apply_remove_element(self, schema: Dict[str, Any], params: Dict[str, Any],
                              pinned: Dict[str, List[str]]) -> Tuple[Dict[str, Any], str]:
        """Remove an element."""
        elem_type = params.get("element_type", "")
        idx = params.get("index", 0)

        type_map = {
            "window": "windows",
            "door": "doors",
            "wall": "walls_batch"
        }

        key = type_map.get(elem_type)
        if not key:
            return schema, f"Unknown element type: {elem_type}"

        if str(idx) in pinned.get(elem_type + "s", []):
            return schema, f"Cannot remove {elem_type} {idx} - it is pinned"

        elements = schema.get(key, [])
        if idx >= len(elements):
            return schema, f"{elem_type.title()} {idx} does not exist"

        elements.pop(idx)
        schema[key] = elements

        return schema, f"Removed {elem_type} {idx}"

    def _apply_unknown(self, schema: Dict[str, Any], params: Dict[str, Any],
                       pinned: Dict[str, List[str]]) -> Tuple[Dict[str, Any], str]:
        """Handle unknown actions."""
        return schema, f"Could not understand request: {params.get('request', 'unknown')}"


class TemplateModifier:
    """High-level interface for template-based modifications."""

    def __init__(self, provider: LLMProvider = None):
        self.parser = ActionParser(provider)
        self.applier = ActionApplier()

    def modify(self, schema: Dict[str, Any], request: str,
               pinned_elements: Dict[str, List[str]] = None) -> Tuple[Dict[str, Any], str]:
        """Modify schema based on natural language request.

        This is the main entry point. It:
        1. Parses the request into a structured action (fast LLM call)
        2. Applies the action using deterministic code

        Args:
            schema: Current building schema
            request: Natural language request
            pinned_elements: Elements that cannot be modified

        Returns:
            Tuple of (modified_schema, description)
        """
        # Step 1: Parse request into action (small LLM output)
        action = self.parser.parse(request, schema)

        # Step 2: Apply action deterministically
        modified, description = self.applier.apply(schema, action, pinned_elements)

        return modified, description
