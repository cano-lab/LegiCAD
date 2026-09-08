"""
SVGBuilder-based renderers for architectural drawing types.

These renderers integrate existing generator logic with the InteractiveSheet
viewport system, enabling multi-drawing sheets with proper LOD support.
"""

from .generator_adapters import (
    get_elevation_data,
    get_section_data,
    get_schedule_data,
    get_detail_data,
)
from .patterns import add_material_patterns
from .elevation_renderer import render_elevation
from .section_renderer import render_section
from .schedule_renderer import render_schedule
from .detail_renderer import render_detail

__all__ = [
    # Data adapters
    "get_elevation_data",
    "get_section_data",
    "get_schedule_data",
    "get_detail_data",
    # Pattern utilities
    "add_material_patterns",
    # Renderers
    "render_elevation",
    "render_section",
    "render_schedule",
    "render_detail",
]
