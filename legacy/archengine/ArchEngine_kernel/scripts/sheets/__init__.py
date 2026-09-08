"""
Interactive Sheet System for Architectural Drawings.

Generates SVG floor plans with:
- Standard ARCH sheet sizes (A through E)
- LOD (Level of Detail) layers for zoom-based detail
- Interactive data attributes on elements
- Title blocks with project information

Usage:
    from sheets import InteractiveSheet

    sheet = InteractiveSheet(
        json_path="path/to/building.json",
        sheet_size="ARCH_D",
        scale="1:50"
    )
    svg_content = sheet.generate()

    # Or save directly
    sheet.save("floor_plan.svg")
"""

from .interactive_sheet import InteractiveSheet
from .sheet_sizes import SHEET_SIZES, SheetSize, get_sheet_size, get_scale_factor
from .lod_layers import LODLevel, LOD_LAYERS, get_lod_layer
from .svg_builder import SVGBuilder
from .viewport import Viewport, ViewportBounds, ViewportRenderer, create_standard_layout
from .sheet_types import (
    DrawingType,
    SheetType,
    ViewportContent,
    ViewportConfig,
    SheetPreset,
    get_preset,
    list_presets,
)

__all__ = [
    "InteractiveSheet",
    "SHEET_SIZES",
    "SheetSize",
    "get_sheet_size",
    "get_scale_factor",
    "LODLevel",
    "LOD_LAYERS",
    "get_lod_layer",
    "SVGBuilder",
    "Viewport",
    "ViewportBounds",
    "ViewportRenderer",
    "create_standard_layout",
    "DrawingType",
    "SheetType",
    "ViewportContent",
    "ViewportConfig",
    "SheetPreset",
    "get_preset",
    "list_presets",
]
