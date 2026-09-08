"""
SVG pattern definitions for architectural materials.

These patterns can be added to an SVGBuilder's defs section
for use in elevation, section, and detail drawings.
"""

from xml.etree.ElementTree import SubElement, Element
from typing import Dict

from ..svg_builder import SVGBuilder


# Material pattern definitions
MATERIAL_PATTERNS: Dict[str, Dict] = {
    # Masonry
    "brick": {
        "width": 20,
        "height": 10,
        "content": [
            {"type": "rect", "x": 0, "y": 0, "width": 20, "height": 10, "fill": "#d4a574"},
            {"type": "line", "x1": 0, "y1": 5, "x2": 20, "y2": 5, "stroke": "#8b6914", "stroke_width": 0.5},
            {"type": "line", "x1": 10, "y1": 0, "x2": 10, "y2": 5, "stroke": "#8b6914", "stroke_width": 0.5},
            {"type": "line", "x1": 0, "y1": 5, "x2": 0, "y2": 10, "stroke": "#8b6914", "stroke_width": 0.5},
        ],
    },
    "cmu": {
        "width": 16,
        "height": 8,
        "content": [
            {"type": "rect", "x": 0, "y": 0, "width": 16, "height": 8, "fill": "#c0c0c0"},
            {"type": "line", "x1": 0, "y1": 4, "x2": 16, "y2": 4, "stroke": "#808080", "stroke_width": 0.3},
            {"type": "line", "x1": 8, "y1": 0, "x2": 8, "y2": 4, "stroke": "#808080", "stroke_width": 0.3},
        ],
    },
    "stone": {
        "width": 24,
        "height": 16,
        "content": [
            {"type": "rect", "x": 0, "y": 0, "width": 24, "height": 16, "fill": "#b8a88a"},
            {"type": "line", "x1": 0, "y1": 8, "x2": 24, "y2": 8, "stroke": "#6b5c4a", "stroke_width": 0.5},
            {"type": "line", "x1": 12, "y1": 0, "x2": 12, "y2": 8, "stroke": "#6b5c4a", "stroke_width": 0.5},
            {"type": "line", "x1": 6, "y1": 8, "x2": 6, "y2": 16, "stroke": "#6b5c4a", "stroke_width": 0.5},
            {"type": "line", "x1": 18, "y1": 8, "x2": 18, "y2": 16, "stroke": "#6b5c4a", "stroke_width": 0.5},
        ],
    },

    # Siding
    "siding": {
        "width": 40,
        "height": 6,
        "content": [
            {"type": "rect", "x": 0, "y": 0, "width": 40, "height": 6, "fill": "#e8e0d0"},
            {"type": "line", "x1": 0, "y1": 5, "x2": 40, "y2": 5, "stroke": "#a09080", "stroke_width": 0.5},
        ],
    },
    "board_batten": {
        "width": 12,
        "height": 20,
        "content": [
            {"type": "rect", "x": 0, "y": 0, "width": 12, "height": 20, "fill": "#c4a882"},
            {"type": "line", "x1": 6, "y1": 0, "x2": 6, "y2": 20, "stroke": "#6b5c4a", "stroke_width": 1},
        ],
    },
    "stucco": {
        "width": 10,
        "height": 10,
        "content": [
            {"type": "rect", "x": 0, "y": 0, "width": 10, "height": 10, "fill": "#e8dcc8"},
            {"type": "circle", "cx": 2, "cy": 3, "r": 0.5, "fill": "#d0c4b0"},
            {"type": "circle", "cx": 7, "cy": 6, "r": 0.5, "fill": "#d0c4b0"},
            {"type": "circle", "cx": 4, "cy": 8, "r": 0.5, "fill": "#d0c4b0"},
        ],
    },

    # Roofing
    "shingles": {
        "width": 24,
        "height": 8,
        "content": [
            {"type": "rect", "x": 0, "y": 0, "width": 24, "height": 8, "fill": "#4a4a4a"},
            {"type": "line", "x1": 0, "y1": 6, "x2": 24, "y2": 6, "stroke": "#2a2a2a", "stroke_width": 0.5},
            {"type": "line", "x1": 8, "y1": 0, "x2": 8, "y2": 6, "stroke": "#2a2a2a", "stroke_width": 0.3},
            {"type": "line", "x1": 16, "y1": 0, "x2": 16, "y2": 6, "stroke": "#2a2a2a", "stroke_width": 0.3},
        ],
    },
    "metal_roof": {
        "width": 16,
        "height": 10,
        "content": [
            {"type": "rect", "x": 0, "y": 0, "width": 16, "height": 10, "fill": "#708090"},
            {"type": "line", "x1": 8, "y1": 0, "x2": 8, "y2": 10, "stroke": "#5a6a7a", "stroke_width": 1},
        ],
    },

    # Section hatching
    "concrete": {
        "width": 8,
        "height": 8,
        "content": [
            {"type": "rect", "x": 0, "y": 0, "width": 8, "height": 8, "fill": "#d0d0d0"},
            {"type": "circle", "cx": 2, "cy": 2, "r": 1, "fill": "#a0a0a0"},
            {"type": "circle", "cx": 6, "cy": 5, "r": 0.8, "fill": "#a0a0a0"},
            {"type": "circle", "cx": 3, "cy": 7, "r": 0.6, "fill": "#a0a0a0"},
        ],
    },
    "insulation": {
        "width": 16,
        "height": 12,
        "content": [
            {"type": "rect", "x": 0, "y": 0, "width": 16, "height": 12, "fill": "#fffacd"},
            {"type": "path", "d": "M0,6 Q4,0 8,6 Q12,12 16,6", "stroke": "#d4a500", "stroke_width": 0.5, "fill": "none"},
        ],
    },
    "wood_grain": {
        "width": 20,
        "height": 6,
        "content": [
            {"type": "rect", "x": 0, "y": 0, "width": 20, "height": 6, "fill": "#deb887"},
            {"type": "line", "x1": 0, "y1": 2, "x2": 20, "y2": 2, "stroke": "#a0522d", "stroke_width": 0.3},
            {"type": "line", "x1": 0, "y1": 4, "x2": 20, "y2": 4, "stroke": "#a0522d", "stroke_width": 0.3},
        ],
    },
    "earth": {
        "width": 12,
        "height": 8,
        "content": [
            {"type": "rect", "x": 0, "y": 0, "width": 12, "height": 8, "fill": "#8b7355"},
            {"type": "line", "x1": 0, "y1": 4, "x2": 4, "y2": 4, "stroke": "#6b5344", "stroke_width": 0.5},
            {"type": "line", "x1": 8, "y1": 2, "x2": 12, "y2": 2, "stroke": "#6b5344", "stroke_width": 0.5},
            {"type": "line", "x1": 4, "y1": 6, "x2": 10, "y2": 6, "stroke": "#6b5344", "stroke_width": 0.5},
        ],
    },
    "gravel": {
        "width": 10,
        "height": 10,
        "content": [
            {"type": "rect", "x": 0, "y": 0, "width": 10, "height": 10, "fill": "#c0b0a0"},
            {"type": "circle", "cx": 2, "cy": 3, "r": 1, "fill": "#908070"},
            {"type": "circle", "cx": 7, "cy": 2, "r": 0.8, "fill": "#a09080"},
            {"type": "circle", "cx": 5, "cy": 6, "r": 1.2, "fill": "#807060"},
            {"type": "circle", "cx": 8, "cy": 8, "r": 0.7, "fill": "#908070"},
        ],
    },

    # Diagonal hatching for cut materials
    "hatch_45": {
        "width": 8,
        "height": 8,
        "content": [
            {"type": "rect", "x": 0, "y": 0, "width": 8, "height": 8, "fill": "white"},
            {"type": "line", "x1": 0, "y1": 8, "x2": 8, "y2": 0, "stroke": "#333333", "stroke_width": 0.5},
        ],
    },
    "hatch_cross": {
        "width": 8,
        "height": 8,
        "content": [
            {"type": "rect", "x": 0, "y": 0, "width": 8, "height": 8, "fill": "white"},
            {"type": "line", "x1": 0, "y1": 8, "x2": 8, "y2": 0, "stroke": "#333333", "stroke_width": 0.5},
            {"type": "line", "x1": 0, "y1": 0, "x2": 8, "y2": 8, "stroke": "#333333", "stroke_width": 0.5},
        ],
    },
}


def add_material_patterns(builder: SVGBuilder) -> None:
    """
    Add all material patterns to an SVGBuilder's defs section.

    Args:
        builder: SVGBuilder instance to add patterns to
    """
    for pattern_id, pattern_def in MATERIAL_PATTERNS.items():
        _create_pattern(builder.defs, pattern_id, pattern_def)


def add_pattern(builder: SVGBuilder, pattern_id: str) -> bool:
    """
    Add a specific material pattern to an SVGBuilder.

    Args:
        builder: SVGBuilder instance
        pattern_id: ID of pattern to add

    Returns:
        True if pattern was added, False if not found
    """
    if pattern_id not in MATERIAL_PATTERNS:
        return False

    _create_pattern(builder.defs, pattern_id, MATERIAL_PATTERNS[pattern_id])
    return True


def _create_pattern(defs: Element, pattern_id: str, pattern_def: Dict) -> Element:
    """Create a pattern element in the defs section."""
    pattern = SubElement(defs, "pattern")
    pattern.set("id", f"pattern-{pattern_id}")
    pattern.set("patternUnits", "userSpaceOnUse")
    pattern.set("width", str(pattern_def["width"]))
    pattern.set("height", str(pattern_def["height"]))

    for item in pattern_def["content"]:
        item_type = item["type"]

        if item_type == "rect":
            elem = SubElement(pattern, "rect")
            elem.set("x", str(item.get("x", 0)))
            elem.set("y", str(item.get("y", 0)))
            elem.set("width", str(item.get("width", 10)))
            elem.set("height", str(item.get("height", 10)))
            elem.set("fill", item.get("fill", "none"))
            if "stroke" in item:
                elem.set("stroke", item["stroke"])
                elem.set("stroke-width", str(item.get("stroke_width", 1)))

        elif item_type == "line":
            elem = SubElement(pattern, "line")
            elem.set("x1", str(item.get("x1", 0)))
            elem.set("y1", str(item.get("y1", 0)))
            elem.set("x2", str(item.get("x2", 10)))
            elem.set("y2", str(item.get("y2", 10)))
            elem.set("stroke", item.get("stroke", "#000"))
            elem.set("stroke-width", str(item.get("stroke_width", 1)))

        elif item_type == "circle":
            elem = SubElement(pattern, "circle")
            elem.set("cx", str(item.get("cx", 5)))
            elem.set("cy", str(item.get("cy", 5)))
            elem.set("r", str(item.get("r", 2)))
            elem.set("fill", item.get("fill", "#000"))

        elif item_type == "path":
            elem = SubElement(pattern, "path")
            elem.set("d", item.get("d", ""))
            elem.set("stroke", item.get("stroke", "#000"))
            elem.set("stroke-width", str(item.get("stroke_width", 1)))
            elem.set("fill", item.get("fill", "none"))

    return pattern


def get_pattern_url(material: str) -> str:
    """
    Get the URL reference for a material pattern.

    Args:
        material: Material name (e.g., "brick", "siding")

    Returns:
        URL reference string for use in fill attribute
    """
    # Map common material names to pattern IDs
    material_map = {
        "brick": "brick",
        "masonry": "brick",
        "cmu": "cmu",
        "block": "cmu",
        "stone": "stone",
        "siding": "siding",
        "lap_siding": "siding",
        "board_batten": "board_batten",
        "stucco": "stucco",
        "shingles": "shingles",
        "asphalt_shingles": "shingles",
        "metal_roof": "metal_roof",
        "standing_seam": "metal_roof",
        "concrete": "concrete",
        "insulation": "insulation",
        "fiberglass": "insulation",
        "wood": "wood_grain",
        "lumber": "wood_grain",
        "earth": "earth",
        "fill": "earth",
        "gravel": "gravel",
        "aggregate": "gravel",
    }

    pattern_id = material_map.get(material.lower(), "hatch_45")
    return f"url(#pattern-{pattern_id})"
