"""
LOD (Level of Detail) layer definitions for architectural drawings.

Defines what content appears at each LOD level and provides
utilities for managing layer visibility in SVG.
"""

from dataclasses import dataclass, field
from typing import List, Set
from enum import IntEnum


class LODLevel(IntEnum):
    """LOD level enumeration."""
    OVERVIEW = 1    # Zoomed out - room names, building outline
    STANDARD = 2    # Normal view - walls, doors, windows
    DETAILED = 3    # Close-up - dimensions, annotations
    CONSTRUCTION = 4  # Full detail - construction notes, specs


@dataclass
class LODLayer:
    """Definition of a single LOD layer."""
    level: LODLevel
    name: str
    description: str
    content_types: Set[str] = field(default_factory=set)
    css_class: str = ""

    def __post_init__(self):
        if not self.css_class:
            self.css_class = f"lod-{self.level}"


# LOD layer definitions
LOD_LAYERS = {
    LODLevel.OVERVIEW: LODLayer(
        level=LODLevel.OVERVIEW,
        name="Overview",
        description="Room names and building outline only",
        content_types={
            "building-outline",
            "room-labels",
            "room-fills",
        },
    ),
    LODLevel.STANDARD: LODLayer(
        level=LODLevel.STANDARD,
        name="Standard",
        description="Wall thickness, door/window locations",
        content_types={
            "walls",
            "wall-fills",
            "doors",
            "windows",
            "door-swings",
        },
    ),
    LODLevel.DETAILED: LODLayer(
        level=LODLevel.DETAILED,
        name="Detailed",
        description="Dimensions, door swings, annotations",
        content_types={
            "dimensions",
            "dimension-text",
            "annotations",
            "grid-lines",
            "level-markers",
        },
    ),
    LODLevel.CONSTRUCTION: LODLayer(
        level=LODLevel.CONSTRUCTION,
        name="Construction",
        description="Construction notes, material specifications",
        content_types={
            "construction-notes",
            "material-specs",
            "detail-callouts",
            "section-marks",
            "wall-types",
        },
    ),
}


def get_lod_layer(level: int) -> LODLayer:
    """Get LOD layer by level number."""
    try:
        return LOD_LAYERS[LODLevel(level)]
    except (ValueError, KeyError):
        raise ValueError(f"Invalid LOD level: {level}. Valid levels: 1-4")


def get_css_for_lod_visibility() -> str:
    """
    Generate CSS rules for LOD layer visibility.

    Each LOD level shows ONLY that level's content (not cumulative).
    - LOD 1: Overview (outline + room labels)
    - LOD 2: Standard (walls + doors + windows)
    - LOD 3: Detailed (dimensions)
    - LOD 4: VR/Field (coordinates)
    - No class: Show all layers
    """
    css_lines = [
        "/* LOD Layer visibility - toggle via JavaScript */",
        ".lod-layer { opacity: 1; transition: opacity 0.2s; }",
        "",
        "/* Default: show all layers (no show-lod-* class) */",
        ".lod-1, .lod-2, .lod-3, .lod-4 { opacity: 1; }",
        "",
        "/* Show ONLY selected LOD level */",
        ".show-lod-1 .lod-2, .show-lod-1 .lod-3, .show-lod-1 .lod-4 { opacity: 0; pointer-events: none; }",
        ".show-lod-2 .lod-1, .show-lod-2 .lod-3, .show-lod-2 .lod-4 { opacity: 0; pointer-events: none; }",
        ".show-lod-3 .lod-1, .show-lod-3 .lod-2, .show-lod-3 .lod-4 { opacity: 0; pointer-events: none; }",
        ".show-lod-4 .lod-1, .show-lod-4 .lod-2, .show-lod-4 .lod-3 { opacity: 0; pointer-events: none; }",
        "",
        "/* Interactive hover effects */",
        "[data-wall-id]:hover, [data-door-id]:hover, [data-window-id]:hover, [data-room-id]:hover {",
        "  stroke: #0066cc !important;",
        "  stroke-width: 2 !important;",
        "  cursor: pointer;",
        "}",
    ]
    return "\n".join(css_lines)


def get_content_lod_level(content_type: str) -> LODLevel:
    """
    Determine which LOD level a content type belongs to.

    Args:
        content_type: Type of content (e.g., "walls", "dimensions")

    Returns:
        LOD level where this content first appears
    """
    for level, layer in LOD_LAYERS.items():
        if content_type in layer.content_types:
            return level

    # Default to standard level if not found
    return LODLevel.STANDARD


# Element style definitions per LOD
ELEMENT_STYLES = {
    # LOD 1 - Overview
    "building-outline": {
        "stroke": "#333333",
        "stroke-width": 2,
        "fill": "none",
    },
    "room-labels": {
        "font-size": 14,
        "font-weight": "bold",
        "fill": "#333333",
        "text-anchor": "middle",
    },
    "room-fills": {
        "fill": "#f5f5f5",
        "stroke": "none",
        "opacity": 0.5,
    },

    # LOD 2 - Standard
    "walls": {
        "stroke": "#000000",
        "stroke-width": 1.5,
        "fill": "none",
    },
    "wall-fills": {
        "fill": "#cccccc",
        "stroke": "none",
    },
    "doors": {
        "stroke": "#000000",
        "stroke-width": 1,
        "fill": "none",
    },
    "windows": {
        "stroke": "#000000",
        "stroke-width": 1,
        "fill": "#e6f3ff",
    },
    "door-swings": {
        "stroke": "#666666",
        "stroke-width": 0.5,
        "stroke-dasharray": "4,2",
        "fill": "none",
    },

    # LOD 3 - Detailed
    "dimensions": {
        "stroke": "#0066cc",
        "stroke-width": 0.5,
        "fill": "none",
    },
    "dimension-text": {
        "font-size": 10,
        "fill": "#0066cc",
        "text-anchor": "middle",
    },
    "annotations": {
        "font-size": 9,
        "fill": "#666666",
        "font-style": "italic",
    },
    "grid-lines": {
        "stroke": "#999999",
        "stroke-width": 0.3,
        "stroke-dasharray": "10,5",
        "bubble-stroke": "#333333",
    },
    "coordinates": {
        "font-size": 7,
        "fill": "#cc0000",
        "marker-fill": "#cc0000",
    },

    # LOD 4 - Construction
    "construction-notes": {
        "font-size": 8,
        "fill": "#333333",
    },
    "material-specs": {
        "font-size": 7,
        "fill": "#666666",
    },
    "wall-types": {
        "font-size": 7,
        "fill": "#999999",
    },
}


def get_element_style(element_type: str) -> dict:
    """Get default style for an element type."""
    return ELEMENT_STYLES.get(element_type, {})
