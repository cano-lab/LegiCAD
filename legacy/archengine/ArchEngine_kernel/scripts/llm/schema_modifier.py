"""Modify building schemas while respecting constraints."""

import json
import re
from pathlib import Path
from typing import Dict, Any, List, Optional
from copy import deepcopy

from .config import LLMConfig
from .provider import Message, LLMProvider


# Default modification prompt
MODIFY_PROMPT = """You are modifying an existing building layout.

CRITICAL: Some elements are PINNED and must NOT be changed:
{pinned_elements}

Current layout:
{current_schema}

Modification request: {request}

Rules:
1. DO NOT modify any pinned elements (walls, doors, windows, rooms listed above)
2. Only change what is necessary to fulfill the request
3. Maintain structural integrity (walls must connect)
4. Ensure doors and windows remain within their wall bounds
5. Keep all dimensions in millimeters
6. Output the complete modified JSON schema

Only output valid JSON, no explanation or markdown."""


class SchemaModifier:
    """Modify building schemas while respecting constraints."""

    def __init__(self, provider: LLMProvider = None, modify_prompt: str = None):
        """Initialize schema modifier.

        Args:
            provider: LLM provider to use (default: active provider from LLMConfig)
            modify_prompt: Custom modification prompt template
        """
        self.provider = provider
        self.modify_prompt = modify_prompt or self._load_modify_prompt()

    def _load_modify_prompt(self) -> str:
        """Load modification prompt from file or use default."""
        prompt_path = Path(__file__).parent / "prompts" / "modify.txt"
        if prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8")
        return MODIFY_PROMPT

    def _get_provider(self) -> LLMProvider:
        """Get the provider to use."""
        if self.provider:
            return self.provider
        provider = LLMConfig.get_active()
        if not provider:
            raise RuntimeError("No LLM provider available")
        return provider

    def _extract_json(self, content: str) -> str:
        """Extract JSON from response content."""
        content = content.strip()

        if "```json" in content:
            match = re.search(r"```json\s*(.*?)\s*```", content, re.DOTALL)
            if match:
                return match.group(1).strip()

        if "```" in content:
            match = re.search(r"```\s*(.*?)\s*```", content, re.DOTALL)
            if match:
                return match.group(1).strip()

        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            return match.group(0)

        return content

    def _format_pinned_elements(self, pinned: Dict[str, List[str]]) -> str:
        """Format pinned elements for the prompt."""
        if not pinned:
            return "None"

        parts = []
        for elem_type, ids in pinned.items():
            if ids:
                parts.append(f"- {elem_type}: {', '.join(str(i) for i in ids)}")

        return "\n".join(parts) if parts else "None"

    def _validate_pinned(
        self,
        original: Dict[str, Any],
        modified: Dict[str, Any],
        pinned: Dict[str, List[str]]
    ) -> Dict[str, Any]:
        """Verify and restore pinned elements that were modified.

        Args:
            original: Original schema
            modified: Modified schema from LLM
            pinned: Dict of element types to list of pinned IDs

        Returns:
            Modified schema with pinned elements restored
        """
        result = deepcopy(modified)

        # Restore pinned walls
        if "walls" in pinned:
            orig_walls = original.get("walls_batch", [])
            mod_walls = result.get("walls_batch", [])

            for wall_idx in pinned["walls"]:
                idx = int(wall_idx)
                if idx < len(orig_walls):
                    # Ensure modified list is long enough
                    while len(mod_walls) <= idx:
                        mod_walls.append({})
                    mod_walls[idx] = deepcopy(orig_walls[idx])

            result["walls_batch"] = mod_walls

        # Restore pinned rooms
        if "rooms" in pinned:
            orig_rooms = original.get("rooms", {})
            mod_rooms = result.get("rooms", {})

            for room_id in pinned["rooms"]:
                if room_id in orig_rooms:
                    mod_rooms[room_id] = deepcopy(orig_rooms[room_id])

            result["rooms"] = mod_rooms

        # Restore pinned doors
        if "doors" in pinned:
            orig_doors = original.get("doors", [])
            mod_doors = result.get("doors", [])

            for door_idx in pinned["doors"]:
                idx = int(door_idx)
                if idx < len(orig_doors):
                    while len(mod_doors) <= idx:
                        mod_doors.append({})
                    mod_doors[idx] = deepcopy(orig_doors[idx])

            result["doors"] = mod_doors

        # Restore pinned windows
        if "windows" in pinned:
            orig_windows = original.get("windows", [])
            mod_windows = result.get("windows", [])

            for window_idx in pinned["windows"]:
                idx = int(window_idx)
                if idx < len(orig_windows):
                    while len(mod_windows) <= idx:
                        mod_windows.append({})
                    mod_windows[idx] = deepcopy(orig_windows[idx])

            result["windows"] = mod_windows

        return result

    def modify(
        self,
        current_schema: Dict[str, Any],
        request: str,
        pinned_elements: Dict[str, List[str]] = None,
        temperature: float = 0.5,
        max_tokens: int = 8000,
        **kwargs
    ) -> Dict[str, Any]:
        """Modify a schema based on a request, respecting pinned elements.

        Args:
            current_schema: Current building schema
            request: Natural language modification request
            pinned_elements: Dict of element types to list of pinned IDs
                e.g. {"walls": ["0", "1"], "rooms": ["room_living"]}
            temperature: Sampling temperature (default: 0.5 for consistency)
            max_tokens: Maximum tokens to generate
            **kwargs: Additional provider options

        Returns:
            Modified building schema

        Raises:
            RuntimeError: If no provider is available
            json.JSONDecodeError: If response is not valid JSON
        """
        provider = self._get_provider()

        # Remove metadata before sending to LLM
        schema_for_llm = {k: v for k, v in current_schema.items() if not k.startswith("_")}

        prompt = self.modify_prompt.format(
            pinned_elements=self._format_pinned_elements(pinned_elements),
            current_schema=json.dumps(schema_for_llm, indent=2),
            request=request
        )

        messages = [
            Message(role="user", content=prompt)
        ]

        response = provider.chat(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        )

        json_content = self._extract_json(response.content)

        try:
            modified = json.loads(json_content)
        except json.JSONDecodeError as e:
            raise json.JSONDecodeError(
                f"Failed to parse LLM response as JSON. Raw content:\n{response.content[:500]}...",
                json_content,
                e.pos
            )

        # Validate and restore any modified pinned elements
        if pinned_elements:
            modified = self._validate_pinned(current_schema, modified, pinned_elements)

        # Add metadata
        modified["_metadata"] = {
            "provider": provider.name,
            "model": response.model,
            "modification": request,
            "pinned": pinned_elements,
            "usage": response.usage
        }

        return modified

    def expand_room(
        self,
        schema: Dict[str, Any],
        room_id: str,
        direction: str,
        amount_mm: int,
        pinned_elements: Dict[str, List[str]] = None
    ) -> Dict[str, Any]:
        """Convenience method to expand a specific room.

        Args:
            schema: Current building schema
            room_id: ID of the room to expand
            direction: Direction to expand (north, south, east, west)
            amount_mm: Amount to expand in millimeters
            pinned_elements: Elements that should not be modified

        Returns:
            Modified schema
        """
        request = f"Expand {room_id} by {amount_mm}mm to the {direction}"
        return self.modify(schema, request, pinned_elements)

    def add_room(
        self,
        schema: Dict[str, Any],
        room_type: str,
        location: str = None,
        size_sqft: int = None,
        pinned_elements: Dict[str, List[str]] = None
    ) -> Dict[str, Any]:
        """Convenience method to add a new room.

        Args:
            schema: Current building schema
            room_type: Type of room to add (bedroom, bathroom, office, etc.)
            location: Where to add the room (e.g., "next to kitchen")
            size_sqft: Desired size in square feet
            pinned_elements: Elements that should not be modified

        Returns:
            Modified schema
        """
        request = f"Add a new {room_type}"
        if size_sqft:
            request += f" of approximately {size_sqft} square feet"
        if location:
            request += f" {location}"

        return self.modify(schema, request, pinned_elements)
