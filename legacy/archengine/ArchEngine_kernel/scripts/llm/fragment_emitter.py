"""Fragment emitter for LLM-to-QBD integration.

Translates natural language into QBD fragments.
The LLM's job is translation only - QBD Algebra validates and solves.
"""

import json
import re
from typing import Dict, List, Any, Optional

from .config import LLMConfig
from .provider import Message, LLMProvider

# Import QBD
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from qbd import Fragment, FragmentParser, QBDState


FRAGMENT_SYSTEM_PROMPT = """You are a building design translator. Convert natural language into QBD fragments.

QBD Algebra uses atomic fragments to build designs. Your job is to translate user intent into these fragments.

Available fragment actions:
- add_room: Add a room {"action": "add_room", "room": {"name": "...", "type": "..."}}
- remove_room: Remove a room {"action": "remove_room", "room_id": "..."}
- update_room: Update room properties {"action": "update_room", "room_id": "...", "updates": {...}}
- add_furniture: Add furniture to room {"action": "add_furniture", "room_id": "...", "furniture": {"type": "...", "size": "..."}}
- set_adjacency: Set rooms as adjacent {"action": "set_adjacency", "room_a": "...", "room_b": "...", "strength": "required|preferred|optional", "connection_type": "open|door|visual"}
- remove_adjacency: Remove adjacency {"action": "remove_adjacency", "room_a": "...", "room_b": "..."}
- set_separation: Keep rooms apart {"action": "set_separation", "room_a": "...", "room_b": "...", "strength": "required|preferred|optional"}
- set_site: Set site properties {"action": "set_site", "updates": {"width": ..., "depth": ..., "setbacks": {...}}}
- set_constraint: Set building constraint {"action": "set_constraint", "target": "footprint_max|stories_max|...", "value": ...}
- set_priority: Set design priority {"action": "set_priority", "factor": "natural_light|privacy|open_plan|...", "value": 1-10}
- set_style: Set style {"action": "set_style", "style": "modern|traditional|...", "keywords": [...]}
- pin_room: Lock a room {"action": "pin_room", "room_id": "...", "locked_properties": ["position", "dimensions"]}
- unpin_room: Unlock a room {"action": "unpin_room", "room_id": "..."}

Room types: bedroom, primary_bedroom, bathroom, ensuite, powder_room, kitchen, living, dining, office, laundry, mudroom, garage_1car, garage_2car, entry, hallway, closet, walk_in_closet, pantry

Furniture types: twin_bed, full_bed, queen_bed, king_bed, sofa_2seat, sofa_3seat, sectional, dining_4, dining_6, dining_8, desk, dresser, toilet, vanity_single, vanity_double, tub, shower

Output only a JSON array of fragments. No explanation.

Example:
User: "I need a 3 bedroom 2 bath house with an open kitchen"
Output:
[
  {"action": "add_room", "room": {"name": "Living Room", "type": "living"}},
  {"action": "add_room", "room": {"name": "Kitchen", "type": "kitchen"}},
  {"action": "add_room", "room": {"name": "Primary Bedroom", "type": "primary_bedroom"}},
  {"action": "add_room", "room": {"name": "Bedroom 2", "type": "bedroom"}},
  {"action": "add_room", "room": {"name": "Bedroom 3", "type": "bedroom"}},
  {"action": "add_room", "room": {"name": "Primary Bath", "type": "ensuite"}},
  {"action": "add_room", "room": {"name": "Bathroom", "type": "bathroom"}},
  {"action": "set_adjacency", "room_a": "room-living", "room_b": "room-kitchen", "strength": "required", "connection_type": "open"},
  {"action": "set_adjacency", "room_a": "room-primary_bedroom", "room_b": "room-ensuite", "strength": "required", "connection_type": "door"}
]

IMPORTANT: For adjacencies, use the room type as a placeholder ID (e.g., "room-living", "room-kitchen"). The system will resolve actual IDs.
"""


MODIFICATION_PROMPT = """Current building state:
{state_summary}

Room IDs:
{room_ids}

User request: {request}

Output a JSON array of fragments to fulfill this request. Use actual room IDs from the list above.
Only output JSON, no explanation."""


class FragmentEmitter:
    """Emit QBD fragments from natural language."""

    def __init__(self, provider: LLMProvider = None):
        self.provider = provider

    def _get_provider(self) -> LLMProvider:
        if self.provider:
            return self.provider
        provider = LLMConfig.get_active()
        if not provider:
            raise RuntimeError("No LLM provider available")
        return provider

    def _extract_json(self, content: str) -> str:
        """Extract JSON from response."""
        content = content.strip()

        if "```json" in content:
            match = re.search(r"```json\s*(.*?)\s*```", content, re.DOTALL)
            if match:
                return match.group(1).strip()

        if "```" in content:
            match = re.search(r"```\s*(.*?)\s*```", content, re.DOTALL)
            if match:
                return match.group(1).strip()

        # Try to find JSON array
        match = re.search(r"\[.*\]", content, re.DOTALL)
        if match:
            return match.group(0)

        return content

    def emit_from_description(
        self,
        description: str,
        temperature: float = 0.3,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """Emit fragments from a natural language description.

        Args:
            description: Natural language building description
            temperature: LLM temperature (lower = more consistent)

        Returns:
            List of fragment dictionaries
        """
        provider = self._get_provider()

        messages = [
            Message(role="system", content=FRAGMENT_SYSTEM_PROMPT),
            Message(role="user", content=description)
        ]

        response = provider.chat(
            messages,
            temperature=temperature,
            max_tokens=4000,
            **kwargs
        )

        json_content = self._extract_json(response.content)
        fragments = json.loads(json_content)

        return fragments

    def emit_for_modification(
        self,
        state: QBDState,
        request: str,
        temperature: float = 0.3,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """Emit fragments to modify an existing state.

        Args:
            state: Current QBD state
            request: Natural language modification request

        Returns:
            List of fragment dictionaries
        """
        provider = self._get_provider()

        # Build state summary
        state_summary = self._summarize_state(state)
        room_ids = self._get_room_ids(state)

        prompt = MODIFICATION_PROMPT.format(
            state_summary=state_summary,
            room_ids=room_ids,
            request=request
        )

        messages = [
            Message(role="system", content=FRAGMENT_SYSTEM_PROMPT),
            Message(role="user", content=prompt)
        ]

        response = provider.chat(
            messages,
            temperature=temperature,
            max_tokens=2000,
            **kwargs
        )

        json_content = self._extract_json(response.content)
        fragments = json.loads(json_content)

        return fragments

    def _summarize_state(self, state: QBDState) -> str:
        """Create a summary of the current state."""
        lines = []

        # Rooms
        rooms = state.rooms
        lines.append(f"Rooms ({len(rooms)}):")
        for room in rooms:
            pinned = " [PINNED]" if room.get("constraints", {}).get("pinned") else ""
            lines.append(f"  - {room['name']} ({room['type']}){pinned}")

        # Adjacencies
        adj = state.adjacencies
        if adj:
            lines.append(f"\nAdjacencies ({len(adj)}):")
            for a in adj[:5]:  # Limit to first 5
                lines.append(f"  - {a['room_a']} <-> {a['room_b']} ({a['strength']}, {a.get('connection_type', 'door')})")

        # Constraints
        constraints = state.constraints
        lines.append(f"\nConstraints:")
        for k, v in constraints.items():
            if v is not None:
                lines.append(f"  - {k}: {v}")

        return "\n".join(lines)

    def _get_room_ids(self, state: QBDState) -> str:
        """Get formatted room ID list."""
        lines = []
        for room in state.rooms:
            lines.append(f"  {room['id']}: {room['name']} ({room['type']})")
        return "\n".join(lines)


def emit_fragments(description: str, **kwargs) -> List[Dict[str, Any]]:
    """Convenience function to emit fragments from description."""
    emitter = FragmentEmitter()
    return emitter.emit_from_description(description, **kwargs)


def apply_fragments_to_state(
    state: QBDState,
    fragments: List[Dict[str, Any]],
    resolve_placeholder_ids: bool = True
) -> Dict[str, Any]:
    """Apply a list of fragments to a state.

    Args:
        state: QBD state to modify
        fragments: List of fragment dictionaries
        resolve_placeholder_ids: If True, resolve placeholder IDs like "room-living"

    Returns:
        Dict with results: {"applied": [...], "errors": [...]}
    """
    results = {"applied": [], "errors": []}

    # First pass: collect room ID mappings if resolving placeholders
    id_map = {}  # placeholder -> actual ID

    for frag_data in fragments:
        action = frag_data.get("action")

        # Apply fragment
        try:
            fragment = FragmentParser.parse(frag_data)
            result = state.apply_fragment(fragment)

            if result.valid:
                results["applied"].append({
                    "fragment_id": fragment.id,
                    "action": action,
                    "success": True
                })

                # Track generated IDs for add_room
                if action == "add_room" and "_generated_id" in fragment.data:
                    room_type = frag_data.get("room", {}).get("type")
                    placeholder = f"room-{room_type}"
                    actual_id = fragment.data["_generated_id"]
                    id_map[placeholder] = actual_id

            else:
                results["errors"].append({
                    "fragment": frag_data,
                    "errors": [e.to_dict() for e in result.errors]
                })

        except Exception as e:
            results["errors"].append({
                "fragment": frag_data,
                "error": str(e)
            })

    return results
