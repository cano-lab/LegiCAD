"""JSON Templates for QBD Algebra.

Defines the fixed structure that the LLM fills in.
The LLM can only fill null values and append to arrays.
"""

from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from copy import deepcopy
import uuid


def generate_id(prefix: str) -> str:
    """Generate a unique ID with a prefix."""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# =============================================================================
# Template Factories
# =============================================================================

def create_master_template() -> Dict[str, Any]:
    """Create the master project template."""
    return {
        "version": "1.0.0",
        "metadata": {
            "project_name": None,
            "project_type": None,
            "units": "metric",
            "code_jurisdiction": None,
        },
        "site": {
            "width": None,
            "depth": None,
            "setbacks": {
                "front": None,
                "rear": None,
                "left": None,
                "right": None,
            },
            "orientation": {
                "front_faces": None,
            },
            "features": [],
            "views": [],
        },
        "rooms": [],
        "adjacencies": [],
        "separations": [],
        "priorities": {
            "natural_light": 5,
            "privacy": 5,
            "open_plan": 5,
            "circulation_efficiency": 5,
            "outdoor_connection": 5,
            "views": 5,
            "minimize_hallways": 5,
            "compact_footprint": 5,
        },
        "constraints": {
            "footprint_max": None,
            "footprint_min": None,
            "stories_max": None,
            "budget_max": None,
            "accessibility": "none",
        },
        "character": {
            "style": None,
            "keywords": [],
            "avoid": [],
        },
        "extensions": {},
    }


def create_room_template(
    room_id: str = None,
    name: str = None,
    room_type: str = None
) -> Dict[str, Any]:
    """Create a room template."""
    return {
        "id": room_id or generate_id("room"),
        "name": name,
        "type": room_type,
        "level": None,
        "area_min": None,
        "area_max": None,
        "width_min": None,
        "width_max": None,
        "length_min": None,
        "length_max": None,
        "ceiling_height": None,
        "furniture": [],
        "features": [],
        "window_preferences": {
            "orientation": None,
            "priority": "normal",
        },
        "constraints": {
            "pinned": False,
            "locked_properties": [],
        },
    }


def create_furniture_template(
    furniture_type: str = None,
    size: str = None
) -> Dict[str, Any]:
    """Create a furniture template."""
    return {
        "type": furniture_type,
        "size": size,
        "width": None,
        "length": None,
        "clearance": {
            "front": None,
            "back": None,
            "left": None,
            "right": None,
        },
        "placement": None,
    }


def create_adjacency_template(
    room_a: str = None,
    room_b: str = None,
    strength: str = "required",
    connection_type: str = "door"
) -> Dict[str, Any]:
    """Create an adjacency relationship template."""
    return {
        "room_a": room_a,
        "room_b": room_b,
        "strength": strength,  # required, preferred, optional
        "connection_type": connection_type,  # open, door, visual
    }


def create_separation_template(
    room_a: str = None,
    room_b: str = None,
    strength: str = "required",
    buffer: int = None
) -> Dict[str, Any]:
    """Create a separation relationship template."""
    return {
        "room_a": room_a,
        "room_b": room_b,
        "strength": strength,
        "buffer": buffer,
    }


def create_site_feature_template(
    feature_type: str = None
) -> Dict[str, Any]:
    """Create a site feature template."""
    return {
        "type": feature_type,
        "location": {"x": None, "y": None},
        "dimensions": {},
        "protect": False,
        "notes": None,
    }


def create_view_template(
    direction: str = None,
    quality: str = None
) -> Dict[str, Any]:
    """Create a view template."""
    return {
        "direction": direction,
        "quality": quality,
        "description": None,
    }


# =============================================================================
# Solved State Templates (output of solver)
# =============================================================================

def create_solved_room_template(
    room_id: str,
    position: tuple = None,
    dimensions: tuple = None
) -> Dict[str, Any]:
    """Create a solved room with position and dimensions."""
    return {
        "id": room_id,
        "position": {
            "x": position[0] if position else None,
            "z": position[1] if position else None,
        },
        "dimensions": {
            "width": dimensions[0] if dimensions else None,
            "length": dimensions[1] if dimensions else None,
        },
        "rotation": 0,
    }


def create_solved_layout_template() -> Dict[str, Any]:
    """Create a solved layout template."""
    return {
        "status": "pending",  # pending, solved, failed
        "rooms": [],
        "building_footprint": {
            "width": None,
            "depth": None,
            "area": None,
        },
        "walls": [],
        "doors": [],
        "windows": [],
        "circulation": [],
        "score": None,
        "score_breakdown": {},
        "tradeoffs_made": [],
    }


# =============================================================================
# Template Validation
# =============================================================================

def validate_template_structure(data: Dict, template: Dict) -> List[str]:
    """Validate that data matches template structure.

    Returns list of error messages (empty if valid).
    """
    errors = []

    def check_keys(data_obj: Dict, template_obj: Dict, path: str = ""):
        if not isinstance(data_obj, dict):
            errors.append(f"{path}: expected object, got {type(data_obj).__name__}")
            return

        # Check for unknown keys (LLM added structure it shouldn't)
        for key in data_obj:
            if key not in template_obj and key != "extensions":
                errors.append(f"{path}.{key}: unknown key (not in template)")

        # Recursively check nested objects
        for key, template_value in template_obj.items():
            if key in data_obj:
                data_value = data_obj[key]
                new_path = f"{path}.{key}" if path else key

                if isinstance(template_value, dict) and template_value:
                    check_keys(data_value, template_value, new_path)

    check_keys(data, template)
    return errors


# =============================================================================
# Template Application
# =============================================================================

def apply_defaults_to_room(room: Dict[str, Any]) -> Dict[str, Any]:
    """Apply type-based defaults to a room."""
    from .defaults import get_room_defaults

    room_type = room.get("type")
    if not room_type:
        return room

    defaults = get_room_defaults(room_type)
    result = deepcopy(room)

    # Apply area defaults if not specified
    if result.get("area_min") is None:
        result["area_min"] = defaults.area_min
    if result.get("area_max") is None:
        result["area_max"] = defaults.area_max
    if result.get("ceiling_height") is None:
        result["ceiling_height"] = defaults.ceiling_height

    # Apply default features if empty
    if not result.get("features"):
        result["features"] = list(defaults.default_features)

    return result


def merge_with_template(data: Dict[str, Any], template: Dict[str, Any]) -> Dict[str, Any]:
    """Merge data with template, filling in missing fields."""
    result = deepcopy(template)

    def merge_recursive(target: Dict, source: Dict):
        for key, value in source.items():
            if key in target:
                if isinstance(target[key], dict) and isinstance(value, dict):
                    merge_recursive(target[key], value)
                elif value is not None:
                    target[key] = value
            else:
                target[key] = value

    merge_recursive(result, data)
    return result
