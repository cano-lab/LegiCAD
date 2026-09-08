#!/usr/bin/env python3
"""
generate_details.py - Generate architectural detail drawings

Creates typical construction details showing:
- Wall section (foundation to roof)
- Eave/fascia detail
- Window head, jamb, and sill details
- Door head, jamb, and threshold details
"""

import json
import argparse
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass

from title_block import generate_title_block, get_project_info_from_json, get_drawing_info

# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class Layer:
    """A material layer in a wall or roof assembly."""
    name: str
    thickness: float  # mm
    material: str     # wood, insulation, gypsum, concrete, etc.

@dataclass
class Detail:
    """A single detail drawing."""
    name: str
    number: str
    scale: str
    width: float   # mm in model space
    height: float  # mm in model space
    svg_content: str

# =============================================================================
# MATERIAL PATTERNS
# =============================================================================

def generate_hatch_patterns(scale: float = 1.0) -> str:
    """
    Generate SVG hatch patterns - minimal and subtle for legibility.

    Args:
        scale: Scale factor to apply to patterns (use detail_scale value)

    Returns:
        SVG pattern definitions string
    """
    s = scale  # Shorthand

    # Using very light, subtle fills to differentiate materials
    # without overwhelming the linework
    return f'''
    <!-- Wood - light tan solid -->
    <pattern id="hatch-wood" patternUnits="userSpaceOnUse" width="{4*s}" height="{4*s}">
      <rect width="{4*s}" height="{4*s}" fill="#F5E6D3"/>
    </pattern>
    <!-- Insulation - very light pink with subtle wave -->
    <pattern id="hatch-insulation" patternUnits="userSpaceOnUse" width="{20*s}" height="{10*s}">
      <rect width="{20*s}" height="{10*s}" fill="#FDF5F7"/>
      <path d="M0,{5*s} Q{5*s},0 {10*s},{5*s} Q{15*s},{10*s} {20*s},{5*s}" stroke="#E8C8D0" stroke-width="{0.3*s}" fill="none"/>
    </pattern>
    <!-- Plywood/OSB - light wood tone -->
    <pattern id="hatch-plywood" patternUnits="userSpaceOnUse" width="{4*s}" height="{4*s}">
      <rect width="{4*s}" height="{4*s}" fill="#EDE4D4"/>
    </pattern>
    <!-- Gypsum/Drywall - very light gray -->
    <pattern id="hatch-gypsum" patternUnits="userSpaceOnUse" width="{4*s}" height="{4*s}">
      <rect width="{4*s}" height="{4*s}" fill="#F0F0F0"/>
    </pattern>
    <!-- Concrete - light gray with minimal stipple -->
    <pattern id="hatch-concrete" patternUnits="userSpaceOnUse" width="{12*s}" height="{12*s}">
      <rect width="{12*s}" height="{12*s}" fill="#E8E8E8"/>
      <circle cx="{3*s}" cy="{3*s}" r="{0.5*s}" fill="#D0D0D0"/>
      <circle cx="{9*s}" cy="{8*s}" r="{0.4*s}" fill="#D0D0D0"/>
    </pattern>
    <!-- Earth/Gravel - light brown -->
    <pattern id="hatch-earth" patternUnits="userSpaceOnUse" width="{4*s}" height="{4*s}">
      <rect width="{4*s}" height="{4*s}" fill="#E8DDD0"/>
    </pattern>
    <!-- Rigid insulation - light blue -->
    <pattern id="hatch-rigid" patternUnits="userSpaceOnUse" width="{4*s}" height="{4*s}">
      <rect width="{4*s}" height="{4*s}" fill="#E8F4FA"/>
    </pattern>
    <!-- Metal - light gray solid -->
    <pattern id="hatch-metal" patternUnits="userSpaceOnUse" width="{4*s}" height="{4*s}">
      <rect width="{4*s}" height="{4*s}" fill="#D8D8D8"/>
    </pattern>
    <!-- Air gap - white -->
    <pattern id="hatch-air" patternUnits="userSpaceOnUse" width="{4*s}" height="{4*s}">
      <rect width="{4*s}" height="{4*s}" fill="#FFFFFF"/>
    </pattern>
    <!-- Siding - off-white -->
    <pattern id="hatch-siding" patternUnits="userSpaceOnUse" width="{4*s}" height="{4*s}">
      <rect width="{4*s}" height="{4*s}" fill="#F8F6F2"/>
    </pattern>
    <!-- Brick - light terra cotta -->
    <pattern id="hatch-brick" patternUnits="userSpaceOnUse" width="{4*s}" height="{4*s}">
      <rect width="{4*s}" height="{4*s}" fill="#EBDCD5"/>
    </pattern>
    <!-- Roofing/Shingles - medium gray -->
    <pattern id="hatch-roofing" patternUnits="userSpaceOnUse" width="{4*s}" height="{4*s}">
      <rect width="{4*s}" height="{4*s}" fill="#A0A0A0"/>
    </pattern>
'''

# Default patterns for backward compatibility
HATCH_PATTERNS = generate_hatch_patterns(1.0)

MATERIAL_TO_PATTERN = {
    'wood': 'hatch-wood',
    'framing': 'hatch-wood',
    'stud': 'hatch-wood',
    'insulation': 'hatch-insulation',
    'batt': 'hatch-insulation',
    'plywood': 'hatch-plywood',
    'osb': 'hatch-plywood',
    'sheathing': 'hatch-plywood',
    'gypsum': 'hatch-gypsum',
    'drywall': 'hatch-gypsum',
    'concrete': 'hatch-concrete',
    'foundation': 'hatch-concrete',
    'earth': 'hatch-earth',
    'gravel': 'hatch-earth',
    'rigid': 'hatch-rigid',
    'foam': 'hatch-rigid',
    'metal': 'hatch-metal',
    'flashing': 'hatch-metal',
    'air': 'hatch-air',
    'cavity': 'hatch-air',
    'siding': 'hatch-siding',
    'brick': 'hatch-brick',
    'roofing': 'hatch-roofing',
    'shingles': 'hatch-roofing',
}

def get_pattern(material: str) -> str:
    """Get SVG pattern ID for a material."""
    return MATERIAL_TO_PATTERN.get(material.lower(), 'hatch-wood')


# =============================================================================
# DIMENSION HELPERS
# =============================================================================

def dim_horizontal(x1: float, x2: float, y: float, text: str,
                   extension_above: float = 10, extension_below: float = 3,
                   text_offset: float = 15, tick_size: float = 5) -> str:
    """
    Generate SVG for a horizontal dimension with ticks.

    Args:
        x1, x2: X coordinates of dimension points
        y: Y position of dimension line
        text: Dimension text
        extension_above: How far extension lines go above dimension line
        extension_below: How far extension lines go below dimension line
        text_offset: Text offset above dimension line
        tick_size: Size of tick marks

    Returns:
        SVG string for the dimension
    """
    lines = []

    # Ensure x1 < x2
    if x1 > x2:
        x1, x2 = x2, x1

    # Extension lines
    lines.append(f'<line x1="{x1}" y1="{y - extension_above}" x2="{x1}" y2="{y + extension_below}" stroke="#000" stroke-width="0.5"/>')
    lines.append(f'<line x1="{x2}" y1="{y - extension_above}" x2="{x2}" y2="{y + extension_below}" stroke="#000" stroke-width="0.5"/>')

    # Dimension line
    lines.append(f'<line x1="{x1}" y1="{y}" x2="{x2}" y2="{y}" stroke="#000" stroke-width="0.5"/>')

    # Tick marks (45-degree slashes)
    lines.append(f'<line x1="{x1 - tick_size/2}" y1="{y + tick_size/2}" x2="{x1 + tick_size/2}" y2="{y - tick_size/2}" stroke="#000" stroke-width="1"/>')
    lines.append(f'<line x1="{x2 - tick_size/2}" y1="{y + tick_size/2}" x2="{x2 + tick_size/2}" y2="{y - tick_size/2}" stroke="#000" stroke-width="1"/>')

    # Text
    mid_x = (x1 + x2) / 2
    lines.append(f'<text x="{mid_x}" y="{y - text_offset}" font-family="Arial" font-size="10" text-anchor="middle" class="dimension">{text}</text>')

    return '\n'.join(lines)


def dim_vertical(x: float, y1: float, y2: float, text: str,
                 extension_left: float = 3, extension_right: float = 10,
                 text_offset: float = 15, tick_size: float = 5,
                 text_anchor: str = "end") -> str:
    """
    Generate SVG for a vertical dimension with ticks.

    Args:
        x: X position of dimension line
        y1, y2: Y coordinates of dimension points
        text: Dimension text
        extension_left: How far extension lines go left of dimension line
        extension_right: How far extension lines go right of dimension line
        text_offset: Text offset from dimension line
        tick_size: Size of tick marks
        text_anchor: Text anchor (end for left side, start for right side)

    Returns:
        SVG string for the dimension
    """
    lines = []

    # Ensure y1 < y2
    if y1 > y2:
        y1, y2 = y2, y1

    # Extension lines
    lines.append(f'<line x1="{x - extension_left}" y1="{y1}" x2="{x + extension_right}" y2="{y1}" stroke="#000" stroke-width="0.5"/>')
    lines.append(f'<line x1="{x - extension_left}" y1="{y2}" x2="{x + extension_right}" y2="{y2}" stroke="#000" stroke-width="0.5"/>')

    # Dimension line
    lines.append(f'<line x1="{x}" y1="{y1}" x2="{x}" y2="{y2}" stroke="#000" stroke-width="0.5"/>')

    # Tick marks (45-degree slashes)
    lines.append(f'<line x1="{x - tick_size/2}" y1="{y1 + tick_size/2}" x2="{x + tick_size/2}" y2="{y1 - tick_size/2}" stroke="#000" stroke-width="1"/>')
    lines.append(f'<line x1="{x - tick_size/2}" y1="{y2 + tick_size/2}" x2="{x + tick_size/2}" y2="{y2 - tick_size/2}" stroke="#000" stroke-width="1"/>')

    # Text (rotated 90 degrees)
    mid_y = (y1 + y2) / 2
    text_x = x - text_offset if text_anchor == "end" else x + text_offset
    lines.append(f'<text x="{text_x}" y="{mid_y}" font-family="Arial" font-size="10" text-anchor="middle" transform="rotate(-90 {text_x} {mid_y})" class="dimension">{text}</text>')

    return '\n'.join(lines)


def leader_line(start_x: float, start_y: float, end_x: float, end_y: float,
                text: str, dot_radius: float = 2, font_size: float = 9) -> str:
    """
    Generate SVG for a leader line with text.

    Args:
        start_x, start_y: Start point (at the item being labeled)
        end_x, end_y: End point (where text will be placed)
        text: Label text
        dot_radius: Radius of dot at start point
        font_size: Font size for text

    Returns:
        SVG string for the leader line
    """
    lines = []

    # Dot at start
    lines.append(f'<circle cx="{start_x}" cy="{start_y}" r="{dot_radius}" fill="#666"/>')

    # Leader line
    lines.append(f'<line x1="{start_x}" y1="{start_y}" x2="{end_x}" y2="{end_y}" stroke="#666" stroke-width="0.5"/>')

    # Text (right or left aligned based on direction)
    anchor = "start" if end_x > start_x else "end"
    text_x = end_x + 5 if anchor == "start" else end_x - 5
    lines.append(f'<text x="{text_x}" y="{end_y + 4}" font-family="Arial" font-size="{font_size}" fill="#333" text-anchor="{anchor}">{text}</text>')

    return '\n'.join(lines)

# =============================================================================
# DETAIL GENERATORS
# =============================================================================

def generate_wall_section_detail(wall_types: List[dict], wall_height: float = 2700) -> Detail:
    """
    Generate a typical wall section detail from foundation to eave.
    Shows all layers with dimensions and labels.
    """

    # Default exterior wall assembly if none provided
    if not wall_types:
        layers = [
            Layer("Lap Siding", 20, "siding"),
            Layer("1\" Air Gap", 25, "air"),
            Layer("Building Wrap", 1, "air"),
            Layer("7/16\" OSB", 11, "plywood"),
            Layer("2x6 Stud w/ R-21", 140, "insulation"),
            Layer("6 mil Poly V.B.", 1, "air"),
            Layer("5/8\" Gypsum", 16, "gypsum"),
        ]
    else:
        # Use first exterior wall type
        ext_wall = None
        for wt in wall_types:
            if wt.get('category') == 'exterior':
                ext_wall = wt
                break
        if ext_wall and ext_wall.get('layers'):
            layers = [Layer(l['name'], l.get('thickness', 20),
                          l.get('material', 'wood')) for l in ext_wall['layers']]
        else:
            layers = [
                Layer("Lap Siding", 20, "siding"),
                Layer("7/16\" OSB", 11, "plywood"),
                Layer("2x6 Stud w/ R-21", 140, "insulation"),
                Layer("5/8\" Gypsum", 16, "gypsum"),
            ]

    # Calculate total wall thickness
    total_thickness = sum(l.thickness for l in layers)

    # Detail dimensions (mm in model space)
    detail_width = 550
    detail_height = 900

    # Scale for detail
    scale = "1:10"

    svg_lines = []

    # Key positions
    wall_center_x = detail_width / 2
    wall_left = wall_center_x - total_thickness / 2

    # Vertical positions (from top)
    roof_top = 30
    wall_top = 120
    floor_level = 550
    grade_level = 620
    foundation_bottom = 820
    footing_bottom = 880

    # Foundation dimensions
    foundation_width = 200
    footing_width = 400
    footing_height = 60
    slab_thickness = 100

    foundation_left = wall_center_x - foundation_width / 2
    footing_left = wall_center_x - footing_width / 2

    # =========== FOUNDATION ===========
    # Footing
    svg_lines.append(f'  <rect x="{footing_left}" y="{foundation_bottom}" width="{footing_width}" height="{footing_height}" fill="url(#hatch-concrete)" stroke="#000" stroke-width="1.5"/>')

    # Foundation wall
    svg_lines.append(f'  <rect x="{foundation_left}" y="{grade_level}" width="{foundation_width}" height="{foundation_bottom - grade_level}" fill="url(#hatch-concrete)" stroke="#000" stroke-width="1.5"/>')

    # Slab on grade
    svg_lines.append(f'  <rect x="{foundation_left}" y="{floor_level}" width="{foundation_width}" height="{slab_thickness}" fill="url(#hatch-concrete)" stroke="#000" stroke-width="1"/>')

    # Gravel under slab
    svg_lines.append(f'  <rect x="{foundation_left + 10}" y="{floor_level + slab_thickness}" width="{foundation_width - 20}" height="{30}" fill="url(#hatch-earth)" stroke="none"/>')

    # Earth on sides
    svg_lines.append(f'  <rect x="0" y="{grade_level}" width="{foundation_left - 30}" height="{footing_bottom - grade_level}" fill="url(#hatch-earth)" stroke="none"/>')
    svg_lines.append(f'  <rect x="{foundation_left + foundation_width + 30}" y="{grade_level}" width="{detail_width - foundation_left - foundation_width - 30}" height="{footing_bottom - grade_level}" fill="url(#hatch-earth)" stroke="none"/>')

    # Grade line
    svg_lines.append(f'  <line x1="0" y1="{grade_level}" x2="{foundation_left - 10}" y2="{grade_level}" stroke="#000" stroke-width="1.5"/>')
    svg_lines.append(f'  <line x1="{foundation_left + foundation_width + 10}" y1="{grade_level}" x2="{detail_width}" y2="{grade_level}" stroke="#000" stroke-width="1.5"/>')

    # Foundation waterproofing (dashed line on exterior)
    svg_lines.append(f'  <line x1="{foundation_left - 5}" y1="{grade_level + 10}" x2="{foundation_left - 5}" y2="{foundation_bottom - 10}" stroke="#000" stroke-width="2" stroke-dasharray="8,4"/>')

    # Sill plate
    sill_y = floor_level - 38
    svg_lines.append(f'  <rect x="{wall_left + 20}" y="{sill_y}" width="{total_thickness - 40}" height="{38}" fill="url(#hatch-wood)" stroke="#000" stroke-width="1"/>')

    # Anchor bolt (circle)
    bolt_x = wall_center_x
    svg_lines.append(f'  <circle cx="{bolt_x}" cy="{floor_level - 19}" r="6" fill="none" stroke="#000" stroke-width="1"/>')
    svg_lines.append(f'  <line x1="{bolt_x}" y1="{floor_level - 13}" x2="{bolt_x}" y2="{floor_level + 60}" stroke="#000" stroke-width="1.5"/>')

    # =========== WALL ASSEMBLY ===========
    # Draw wall layers from exterior to interior
    current_x = wall_left
    wall_height_section = floor_level - sill_y - 38 - wall_top

    for layer in layers:
        pattern = get_pattern(layer.material)
        svg_lines.append(f'  <rect x="{current_x}" y="{wall_top}" width="{layer.thickness}" height="{wall_height_section}" fill="url(#{pattern})" stroke="#000" stroke-width="0.5"/>')
        current_x += layer.thickness

    # Wall outline
    svg_lines.append(f'  <rect x="{wall_left}" y="{wall_top}" width="{total_thickness}" height="{wall_height_section}" fill="none" stroke="#000" stroke-width="1.5"/>')

    # Studs indication (dashed lines inside insulation layer)
    stud_spacing = 400  # 16" o.c.
    insulation_x = wall_left
    for l in layers:
        if 'stud' in l.name.lower() or 'batt' in l.name.lower():
            break
        insulation_x += l.thickness

    # Show two stud indications
    for stud_offset in [50, 150]:
        svg_lines.append(f'  <line x1="{insulation_x + 5}" y1="{wall_top + stud_offset}" x2="{insulation_x + 5}" y2="{wall_top + stud_offset + 100}" stroke="#8B4513" stroke-width="2"/>')
        svg_lines.append(f'  <line x1="{insulation_x + 135}" y1="{wall_top + stud_offset}" x2="{insulation_x + 135}" y2="{wall_top + stud_offset + 100}" stroke="#8B4513" stroke-width="2"/>')

    # Double top plate
    plate_h = 38
    svg_lines.append(f'  <rect x="{wall_left + 20}" y="{wall_top}" width="{total_thickness - 40}" height="{plate_h}" fill="url(#hatch-wood)" stroke="#000" stroke-width="1"/>')
    svg_lines.append(f'  <rect x="{wall_left + 20}" y="{wall_top + plate_h}" width="{total_thickness - 40}" height="{plate_h}" fill="url(#hatch-wood)" stroke="#000" stroke-width="1"/>')

    # =========== ROOF/CEILING ===========
    # Rafter/truss indication
    rafter_depth = 50
    svg_lines.append(f'  <rect x="{wall_left - 30}" y="{roof_top}" width="{total_thickness + 100}" height="{rafter_depth}" fill="url(#hatch-wood)" stroke="#000" stroke-width="1"/>')

    # Ceiling insulation indication
    svg_lines.append(f'  <rect x="{wall_left + total_thickness}" y="{wall_top + plate_h * 2}" width="{80}" height="{60}" fill="url(#hatch-insulation)" stroke="#000" stroke-width="0.5"/>')

    # Ceiling drywall
    ceiling_y = wall_top + plate_h * 2 + 60
    svg_lines.append(f'  <rect x="{wall_left + total_thickness - 16}" y="{ceiling_y}" width="{100}" height="{16}" fill="url(#hatch-gypsum)" stroke="#000" stroke-width="0.5"/>')

    # =========== BREAK LINES ===========
    # Top break
    svg_lines.append(f'  <path d="M 0,{roof_top - 5} l 10,5 l -10,5 l 10,5 l -10,5 h {detail_width} l -10,-5 l 10,-5 l -10,-5 l 10,-5" fill="none" stroke="#000" stroke-width="1"/>')

    # Bottom break (at footing)
    svg_lines.append(f'  <path d="M {footing_left - 10},{footing_bottom + 5} l 10,-5 l -10,-5 l 10,-5 l -10,-5 h {footing_width + 20} l -10,5 l 10,5 l -10,5 l 10,5" fill="none" stroke="#000" stroke-width="1"/>')

    # =========== DIMENSIONS ===========
    dim_x = wall_left - 50

    # Wall thickness (horizontal dimension)
    svg_lines.append(dim_horizontal(wall_left, wall_left + total_thickness, floor_level - 80,
                                     f'{total_thickness:.0f}mm', tick_size=6))

    # Floor to ceiling height (vertical dimension on left)
    ceiling_ht = floor_level - ceiling_y - 16
    svg_lines.append(dim_vertical(dim_x, ceiling_y + 16, floor_level,
                                   f'{ceiling_ht:.0f} CLG HT', tick_size=6))

    # Foundation depth (vertical dimension)
    svg_lines.append(dim_vertical(dim_x - 40, grade_level, footing_bottom,
                                   f'{footing_bottom - grade_level:.0f}', tick_size=6))

    # Footing width (horizontal dimension)
    svg_lines.append(dim_horizontal(footing_left, footing_left + footing_width, footing_bottom + 25,
                                     f'{footing_width:.0f}', extension_above=3, extension_below=10, tick_size=6))

    # =========== LABELS ===========
    label_x = wall_left + total_thickness + 30

    # Layer labels with leader lines
    spacing = (floor_level - sill_y - wall_top - 150) / max(len(layers), 1)

    for i, layer in enumerate(layers):
        y_pos = wall_top + 100 + i * spacing
        svg_lines.append(leader_line(wall_left + total_thickness, y_pos, label_x, y_pos, layer.name))

    # Top plate label
    svg_lines.append(leader_line(wall_left + total_thickness, wall_top + plate_h, label_x, wall_top + plate_h, "DBL TOP PLATE"))

    # Sill plate label
    svg_lines.append(leader_line(wall_left + total_thickness, sill_y + 19, label_x, sill_y + 19, "P.T. SILL w/ 1/2\" A.B."))

    # Foundation labels (left side)
    svg_lines.append(leader_line(footing_left + footing_width/2, foundation_bottom + footing_height/2,
                                  footing_left - 20, foundation_bottom + footing_height/2, "CONT. FTG"))
    svg_lines.append(leader_line(foundation_left + foundation_width/2, (grade_level + foundation_bottom)/2,
                                  foundation_left - 20, (grade_level + foundation_bottom)/2, "STEM WALL"))
    svg_lines.append(leader_line(foundation_left + foundation_width/2, floor_level + slab_thickness/2,
                                  foundation_left - 20, floor_level + slab_thickness/2, "4\" SLAB"))

    # Waterproofing label
    svg_lines.append(leader_line(foundation_left - 5, (grade_level + foundation_bottom)/2 + 30,
                                  foundation_left - 40, (grade_level + foundation_bottom)/2 + 60, "DAMPPROOF"))

    # Grade label with symbol
    svg_lines.append(f'  <text x="{10}" y="{grade_level - 5}" font-family="Arial" font-size="9" fill="#333">GRADE</text>')
    # Grade symbol (circle with X)
    svg_lines.append(f'  <circle cx="{55}" cy="{grade_level - 8}" r="8" fill="none" stroke="#000" stroke-width="1"/>')
    svg_lines.append(f'  <line x1="{49}" y1="{grade_level - 14}" x2="{61}" y2="{grade_level - 2}" stroke="#000" stroke-width="0.8"/>')
    svg_lines.append(f'  <line x1="{49}" y1="{grade_level - 2}" x2="{61}" y2="{grade_level - 14}" stroke="#000" stroke-width="0.8"/>')

    return Detail(
        name="TYPICAL WALL SECTION",
        number="1",
        scale=scale,
        width=detail_width,
        height=detail_height,
        svg_content='\n'.join(svg_lines)
    )


def generate_eave_detail() -> Detail:
    """Generate a typical eave/fascia detail."""

    detail_width = 450
    detail_height = 400

    svg_lines = []

    # Roof pitch (4:12)
    pitch = 4/12

    # Key dimensions
    rafter_depth = 184  # 2x8 actual depth
    rafter_width = 38   # 2x8 actual width
    sheathing = 12      # 1/2" OSB
    roofing = 8         # Shingles
    fascia_width = 19   # 1x8 actual
    fascia_height = 184 # 1x8 height
    soffit_thick = 12   # Plywood soffit
    wall_thick = 140    # 2x6 wall
    plate_height = 38   # 2x4 plate
    overhang = 400      # Eave overhang

    # Starting point - wall exterior face
    wall_ext_x = 180
    wall_top_y = 280

    # Rafter bearing point on wall
    rafter_start_x = wall_ext_x - 30  # Bird's mouth setback
    rafter_start_y = wall_top_y - plate_height * 2  # Top of double plate

    # Rafter end (at fascia)
    rafter_end_x = rafter_start_x - overhang
    rafter_end_y = rafter_start_y + overhang * pitch

    # Draw wall (partial, with break line)
    wall_height = 100
    svg_lines.append(f'  <rect x="{wall_ext_x}" y="{wall_top_y}" width="{wall_thick}" height="{wall_height}" fill="url(#hatch-insulation)" stroke="#000" stroke-width="1"/>')

    # Exterior sheathing
    svg_lines.append(f'  <rect x="{wall_ext_x - sheathing}" y="{wall_top_y - plate_height * 2}" width="{sheathing}" height="{wall_height + plate_height * 2}" fill="url(#hatch-plywood)" stroke="#000" stroke-width="0.5"/>')

    # Interior drywall
    svg_lines.append(f'  <rect x="{wall_ext_x + wall_thick}" y="{wall_top_y}" width="{16}" height="{wall_height}" fill="url(#hatch-gypsum)" stroke="#000" stroke-width="0.5"/>')

    # Double top plate
    svg_lines.append(f'  <rect x="{wall_ext_x}" y="{wall_top_y - plate_height}" width="{wall_thick}" height="{plate_height}" fill="url(#hatch-wood)" stroke="#000" stroke-width="1"/>')
    svg_lines.append(f'  <rect x="{wall_ext_x}" y="{wall_top_y - plate_height * 2}" width="{wall_thick}" height="{plate_height}" fill="url(#hatch-wood)" stroke="#000" stroke-width="1"/>')

    # Ceiling joist / rafter tie
    ceiling_y = wall_top_y - plate_height * 2 + 10
    svg_lines.append(f'  <rect x="{wall_ext_x + 20}" y="{ceiling_y}" width="{wall_thick + 50}" height="{rafter_width}" fill="url(#hatch-wood)" stroke="#000" stroke-width="1"/>')

    # Ceiling drywall
    svg_lines.append(f'  <rect x="{wall_ext_x + 20}" y="{ceiling_y + rafter_width}" width="{wall_thick + 80}" height="{16}" fill="url(#hatch-gypsum)" stroke="#000" stroke-width="0.5"/>')

    # Rafter (angled)
    import math
    angle = math.atan(pitch)
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)

    # Rafter polygon points
    r1_x, r1_y = rafter_end_x, rafter_end_y
    r2_x, r2_y = rafter_start_x + 100, rafter_start_y - 100 * pitch
    r3_x = r2_x + rafter_depth * sin_a
    r3_y = r2_y + rafter_depth * cos_a
    r4_x = r1_x + rafter_depth * sin_a
    r4_y = r1_y + rafter_depth * cos_a

    svg_lines.append(f'  <polygon points="{r1_x:.1f},{r1_y:.1f} {r2_x:.1f},{r2_y:.1f} {r3_x:.1f},{r3_y:.1f} {r4_x:.1f},{r4_y:.1f}" fill="url(#hatch-wood)" stroke="#000" stroke-width="1"/>')

    # Roof sheathing
    s1_x, s1_y = r1_x, r1_y - sheathing / cos_a
    s2_x, s2_y = r2_x, r2_y - sheathing / cos_a
    svg_lines.append(f'  <polygon points="{r1_x:.1f},{r1_y:.1f} {r2_x:.1f},{r2_y:.1f} {s2_x:.1f},{s2_y:.1f} {s1_x:.1f},{s1_y:.1f}" fill="url(#hatch-plywood)" stroke="#000" stroke-width="0.5"/>')

    # Roofing/shingles
    t1_x, t1_y = s1_x, s1_y - roofing / cos_a
    t2_x, t2_y = s2_x, s2_y - roofing / cos_a
    svg_lines.append(f'  <polygon points="{s1_x:.1f},{s1_y:.1f} {s2_x:.1f},{s2_y:.1f} {t2_x:.1f},{t2_y:.1f} {t1_x:.1f},{t1_y:.1f}" fill="url(#hatch-roofing)" stroke="#000" stroke-width="0.5"/>')

    # Drip edge
    svg_lines.append(f'  <path d="M {t1_x:.1f},{t1_y:.1f} L {t1_x - 8:.1f},{t1_y:.1f} L {t1_x - 8:.1f},{r1_y + 15:.1f}" fill="none" stroke="#000" stroke-width="1.5"/>')

    # Fascia board
    svg_lines.append(f'  <rect x="{r1_x - fascia_width}" y="{r1_y}" width="{fascia_width}" height="{fascia_height}" fill="url(#hatch-wood)" stroke="#000" stroke-width="1"/>')

    # Sub-fascia (behind fascia)
    svg_lines.append(f'  <rect x="{r1_x}" y="{r1_y + 10}" width="{rafter_width}" height="{fascia_height - 20}" fill="url(#hatch-wood)" stroke="#000" stroke-width="0.5"/>')

    # Soffit
    soffit_y = r1_y + fascia_height - soffit_thick
    soffit_length = wall_ext_x - sheathing - (r1_x - fascia_width) + 10
    svg_lines.append(f'  <rect x="{r1_x - fascia_width}" y="{soffit_y}" width="{soffit_length}" height="{soffit_thick}" fill="url(#hatch-plywood)" stroke="#000" stroke-width="0.5"/>')

    # Frieze board (at wall)
    svg_lines.append(f'  <rect x="{wall_ext_x - sheathing - 19}" y="{rafter_start_y + 30}" width="{19}" height="{soffit_y - rafter_start_y - 30}" fill="url(#hatch-wood)" stroke="#000" stroke-width="0.5"/>')

    # Vent strip in soffit (indicated with dashed line)
    vent_x = r1_x + 50
    svg_lines.append(f'  <rect x="{vent_x}" y="{soffit_y + 2}" width="{60}" height="{soffit_thick - 4}" fill="none" stroke="#000" stroke-width="0.5" stroke-dasharray="3,2"/>')

    # Bird's mouth cut indication
    svg_lines.append(f'  <line x1="{r4_x - 30}" y1="{r4_y}" x2="{r4_x - 30}" y2="{wall_top_y - plate_height * 2}" stroke="#000" stroke-width="0.5"/>')
    svg_lines.append(f'  <line x1="{r4_x - 30}" y1="{wall_top_y - plate_height * 2}" x2="{wall_ext_x + 30}" y2="{wall_top_y - plate_height * 2}" stroke="#000" stroke-width="0.5"/>')

    # Labels with leader lines
    # Shingles
    svg_lines.append(f'  <line x1="{(t1_x + t2_x)/2}" y1="{(t1_y + t2_y)/2 - 5}" x2="{(t1_x + t2_x)/2 + 30}" y2="{(t1_y + t2_y)/2 - 40}" stroke="#333" stroke-width="0.5"/>')
    svg_lines.append(f'  <text x="{(t1_x + t2_x)/2 + 35}" y="{(t1_y + t2_y)/2 - 42}" font-family="Arial" font-size="10" fill="#333">ASPHALT SHINGLES</text>')

    # Rafter
    svg_lines.append(f'  <line x1="{(r1_x + r2_x)/2 + 20}" y1="{(r1_y + r2_y)/2 + 60}" x2="{(r1_x + r2_x)/2 + 60}" y2="{(r1_y + r2_y)/2 + 90}" stroke="#333" stroke-width="0.5"/>')
    svg_lines.append(f'  <text x="{(r1_x + r2_x)/2 + 65}" y="{(r1_y + r2_y)/2 + 93}" font-family="Arial" font-size="10" fill="#333">2x8 RAFTER @ 16" O.C.</text>')

    # Fascia
    svg_lines.append(f'  <line x1="{r1_x - fascia_width/2}" y1="{r1_y + fascia_height/2}" x2="{r1_x - fascia_width - 40}" y2="{r1_y + fascia_height/2}" stroke="#333" stroke-width="0.5"/>')
    svg_lines.append(f'  <text x="{r1_x - fascia_width - 45}" y="{r1_y + fascia_height/2 + 3}" font-family="Arial" font-size="10" fill="#333" text-anchor="end">1x8 FASCIA</text>')

    # Soffit
    svg_lines.append(f'  <line x1="{r1_x + 80}" y1="{soffit_y + soffit_thick/2}" x2="{r1_x + 80}" y2="{soffit_y + 35}" stroke="#333" stroke-width="0.5"/>')
    svg_lines.append(f'  <text x="{r1_x + 85}" y="{soffit_y + 38}" font-family="Arial" font-size="10" fill="#333">VENTED SOFFIT</text>')

    # Top plates
    svg_lines.append(f'  <line x1="{wall_ext_x + wall_thick + 20}" y1="{wall_top_y - plate_height}" x2="{wall_ext_x + wall_thick + 50}" y2="{wall_top_y - plate_height}" stroke="#333" stroke-width="0.5"/>')
    svg_lines.append(f'  <text x="{wall_ext_x + wall_thick + 55}" y="{wall_top_y - plate_height + 3}" font-family="Arial" font-size="10" fill="#333">DBL 2x4 TOP PLATE</text>')

    # Insulation
    svg_lines.append(f'  <text x="{wall_ext_x + wall_thick/2}" y="{wall_top_y + wall_height/2}" font-family="Arial" font-size="9" fill="#333" text-anchor="middle">R-21 BATT</text>')

    # Break line at bottom
    break_y = wall_top_y + wall_height
    svg_lines.append(f'  <path d="M {wall_ext_x - sheathing - 5},{break_y} l 5,-8 l 5,16 l 5,-16 l 5,16 l 5,-8 l {wall_thick + 30},0 l 5,-8 l 5,16 l 5,-16 l 5,16 l 5,-8" fill="none" stroke="#000" stroke-width="1"/>')

    return Detail(
        name="EAVE DETAIL",
        number="2",
        scale="1:5",
        width=detail_width,
        height=detail_height,
        svg_content='\n'.join(svg_lines)
    )


def generate_window_detail() -> Detail:
    """Generate window head, jamb, and sill details."""

    detail_width = 480
    detail_height = 380

    svg_lines = []

    # Three sub-details arranged horizontally
    section_width = 130
    section_height = 150
    spacing = 25

    # Common dimensions
    wall_thick = 140      # 2x6 wall
    sheathing = 12        # OSB
    siding = 20           # Exterior finish
    drywall = 16          # Interior gypsum
    frame_width = 38      # Window frame
    glass_thick = 25      # IGU thickness

    # =========== HEAD DETAIL ===========
    head_x = 25
    head_y = 40

    svg_lines.append(f'  <text x="{head_x + section_width/2}" y="{head_y - 8}" font-family="Arial" font-size="12" font-weight="bold" text-anchor="middle">HEAD</text>')

    # Draw from exterior (left) to interior (right)
    current_x = head_x

    # Exterior siding
    svg_lines.append(f'  <rect x="{current_x}" y="{head_y}" width="{siding}" height="{60}" fill="url(#hatch-siding)" stroke="#000" stroke-width="0.5"/>')
    current_x += siding

    # Sheathing
    svg_lines.append(f'  <rect x="{current_x}" y="{head_y}" width="{sheathing}" height="{section_height}" fill="url(#hatch-plywood)" stroke="#000" stroke-width="0.5"/>')
    current_x += sheathing

    # Header (double 2x10)
    header_depth = 235  # Double 2x10
    svg_lines.append(f'  <rect x="{current_x}" y="{head_y}" width="{wall_thick}" height="{38}" fill="url(#hatch-wood)" stroke="#000" stroke-width="1"/>')
    svg_lines.append(f'  <rect x="{current_x}" y="{head_y + 38}" width="{wall_thick}" height="{38}" fill="url(#hatch-wood)" stroke="#000" stroke-width="1"/>')

    # Insulation above header
    svg_lines.append(f'  <rect x="{current_x}" y="{head_y + 76}" width="{wall_thick}" height="{section_height - 76}" fill="url(#hatch-insulation)" stroke="#000" stroke-width="0.5"/>')

    # Drywall
    svg_lines.append(f'  <rect x="{current_x + wall_thick}" y="{head_y}" width="{drywall}" height="{section_height}" fill="url(#hatch-gypsum)" stroke="#000" stroke-width="0.5"/>')

    # Window frame
    frame_y = head_y + 82
    svg_lines.append(f'  <rect x="{current_x + 10}" y="{frame_y}" width="{wall_thick - 20}" height="{frame_width}" fill="url(#hatch-wood)" stroke="#000" stroke-width="1"/>')

    # Glass (double pane indicated)
    glass_y = frame_y + frame_width + 5
    svg_lines.append(f'  <rect x="{current_x + 20}" y="{glass_y}" width="{wall_thick - 40}" height="{section_height - glass_y + head_y - 5}" fill="#E8F4FC" stroke="#000" stroke-width="1"/>')
    svg_lines.append(f'  <line x1="{current_x + 25}" y1="{glass_y + 5}" x2="{current_x + wall_thick - 25}" y2="{glass_y + 5}" stroke="#666" stroke-width="0.5"/>')
    svg_lines.append(f'  <line x1="{current_x + 25}" y1="{glass_y + glass_thick - 5}" x2="{current_x + wall_thick - 25}" y2="{glass_y + glass_thick - 5}" stroke="#666" stroke-width="0.5"/>')

    # Casing (interior)
    svg_lines.append(f'  <rect x="{current_x + wall_thick + drywall}" y="{frame_y - 10}" width="{15}" height="{section_height - frame_y + head_y + 15}" fill="url(#hatch-wood)" stroke="#000" stroke-width="0.5"/>')

    # Head flashing
    svg_lines.append(f'  <path d="M {head_x + siding - 3},{head_y + 55} L {head_x + siding - 3},{head_y + 62} L {head_x + siding + sheathing + 15},{head_y + 62}" fill="none" stroke="#000" stroke-width="1.5"/>')

    # Labels
    svg_lines.append(f'  <text x="{head_x - 3}" y="{head_y + 50}" font-family="Arial" font-size="7" fill="#333" text-anchor="end">SIDING</text>')
    svg_lines.append(f'  <text x="{head_x + section_width + 20}" y="{head_y + 50}" font-family="Arial" font-size="7" fill="#333">(2) 2x10 HDR</text>')
    svg_lines.append(f'  <text x="{head_x + section_width + 20}" y="{head_y + 100}" font-family="Arial" font-size="7" fill="#333">HEAD FLASH</text>')

    # =========== JAMB DETAIL ===========
    jamb_x = head_x + section_width + spacing
    jamb_y = head_y

    svg_lines.append(f'  <text x="{jamb_x + section_width/2}" y="{jamb_y - 8}" font-family="Arial" font-size="12" font-weight="bold" text-anchor="middle">JAMB</text>')

    current_x = jamb_x

    # Exterior siding
    svg_lines.append(f'  <rect x="{current_x}" y="{jamb_y}" width="{siding}" height="{section_height}" fill="url(#hatch-siding)" stroke="#000" stroke-width="0.5"/>')
    current_x += siding

    # Sheathing
    svg_lines.append(f'  <rect x="{current_x}" y="{jamb_y}" width="{sheathing}" height="{section_height}" fill="url(#hatch-plywood)" stroke="#000" stroke-width="0.5"/>')
    current_x += sheathing

    # King stud
    svg_lines.append(f'  <rect x="{current_x}" y="{jamb_y}" width="{38}" height="{section_height}" fill="url(#hatch-wood)" stroke="#000" stroke-width="1"/>')

    # Jack stud
    svg_lines.append(f'  <rect x="{current_x + 40}" y="{jamb_y + 20}" width="{38}" height="{section_height - 20}" fill="url(#hatch-wood)" stroke="#000" stroke-width="1"/>')

    # Insulation cavity
    svg_lines.append(f'  <rect x="{current_x + 80}" y="{jamb_y}" width="{60}" height="{section_height}" fill="url(#hatch-insulation)" stroke="#000" stroke-width="0.5"/>')

    # Drywall
    svg_lines.append(f'  <rect x="{current_x + wall_thick}" y="{jamb_y}" width="{drywall}" height="{section_height}" fill="url(#hatch-gypsum)" stroke="#000" stroke-width="0.5"/>')

    # Window frame
    svg_lines.append(f'  <rect x="{current_x + 80}" y="{jamb_y + 25}" width="{frame_width}" height="{section_height - 50}" fill="url(#hatch-wood)" stroke="#000" stroke-width="1"/>')

    # Glass
    svg_lines.append(f'  <rect x="{current_x + 80 + frame_width + 5}" y="{jamb_y + 30}" width="{25}" height="{section_height - 60}" fill="#E8F4FC" stroke="#000" stroke-width="1"/>')

    # Interior casing
    svg_lines.append(f'  <rect x="{current_x + wall_thick + drywall}" y="{jamb_y + 20}" width="{15}" height="{section_height - 40}" fill="url(#hatch-wood)" stroke="#000" stroke-width="0.5"/>')

    # Labels
    svg_lines.append(f'  <text x="{jamb_x + 50}" y="{jamb_y + section_height + 12}" font-family="Arial" font-size="7" fill="#333" text-anchor="middle">KING</text>')
    svg_lines.append(f'  <text x="{jamb_x + 90}" y="{jamb_y + section_height + 12}" font-family="Arial" font-size="7" fill="#333" text-anchor="middle">JACK</text>')

    # =========== SILL DETAIL ===========
    sill_x = jamb_x + section_width + spacing
    sill_y = head_y

    svg_lines.append(f'  <text x="{sill_x + section_width/2}" y="{sill_y - 8}" font-family="Arial" font-size="12" font-weight="bold" text-anchor="middle">SILL</text>')

    current_x = sill_x

    # Exterior siding (partial - sill interrupts)
    svg_lines.append(f'  <rect x="{current_x}" y="{sill_y + 70}" width="{siding}" height="{section_height - 70}" fill="url(#hatch-siding)" stroke="#000" stroke-width="0.5"/>')

    # Sheathing
    svg_lines.append(f'  <rect x="{current_x + siding}" y="{sill_y + 55}" width="{sheathing}" height="{section_height - 55}" fill="url(#hatch-plywood)" stroke="#000" stroke-width="0.5"/>')

    # Wall framing
    svg_lines.append(f'  <rect x="{current_x + siding + sheathing}" y="{sill_y + 55}" width="{wall_thick}" height="{section_height - 55}" fill="url(#hatch-insulation)" stroke="#000" stroke-width="0.5"/>')

    # Rough sill (2x)
    svg_lines.append(f'  <rect x="{current_x + siding + sheathing}" y="{sill_y + 55}" width="{100}" height="{38}" fill="url(#hatch-wood)" stroke="#000" stroke-width="1"/>')

    # Drywall
    svg_lines.append(f'  <rect x="{current_x + siding + sheathing + wall_thick}" y="{sill_y + 55}" width="{drywall}" height="{section_height - 55}" fill="url(#hatch-gypsum)" stroke="#000" stroke-width="0.5"/>')

    # Sloped exterior sill
    sill_ext_y = sill_y + 50
    svg_lines.append(f'  <polygon points="{current_x},{sill_ext_y + 20} {current_x + siding + sheathing + 20},{sill_ext_y + 20} {current_x + siding + sheathing + 25},{sill_ext_y} {current_x},{sill_ext_y}" fill="url(#hatch-metal)" stroke="#000" stroke-width="1"/>')

    # Window frame
    svg_lines.append(f'  <rect x="{current_x + siding + sheathing + 15}" y="{sill_y + 10}" width="{wall_thick - 30}" height="{frame_width}" fill="url(#hatch-wood)" stroke="#000" stroke-width="1"/>')

    # Glass
    svg_lines.append(f'  <rect x="{current_x + siding + sheathing + 25}" y="{sill_y}" width="{wall_thick - 50}" height="{10}" fill="#E8F4FC" stroke="#000" stroke-width="1"/>')

    # Interior stool
    stool_y = sill_y + 48
    svg_lines.append(f'  <rect x="{current_x + siding + sheathing + wall_thick - 20}" y="{stool_y}" width="{55}" height="{18}" fill="url(#hatch-wood)" stroke="#000" stroke-width="1"/>')

    # Apron
    svg_lines.append(f'  <rect x="{current_x + siding + sheathing + wall_thick + drywall}" y="{stool_y + 18}" width="{15}" height="{40}" fill="url(#hatch-wood)" stroke="#000" stroke-width="0.5"/>')

    # Labels
    svg_lines.append(f'  <text x="{sill_x + section_width + 18}" y="{sill_y + 55}" font-family="Arial" font-size="7" fill="#333">SLOPED SILL</text>')
    svg_lines.append(f'  <text x="{sill_x + section_width + 18}" y="{sill_y + 80}" font-family="Arial" font-size="7" fill="#333">STOOL</text>')
    svg_lines.append(f'  <text x="{sill_x + section_width + 18}" y="{sill_y + 110}" font-family="Arial" font-size="7" fill="#333">APRON</text>')

    # =========== OVERALL LABELS ===========
    svg_lines.append(f'  <text x="{detail_width/2}" y="{head_y + section_height + 35}" font-family="Arial" font-size="9" fill="#666" text-anchor="middle">SCALE: 1:5  |  EXTERIOR AT LEFT</text>')

    return Detail(
        name="WINDOW DETAILS",
        number="3",
        scale="1:5",
        width=detail_width,
        height=detail_height,
        svg_content='\n'.join(svg_lines)
    )


def generate_door_detail() -> Detail:
    """Generate door head and threshold details."""

    detail_width = 420
    detail_height = 340

    svg_lines = []

    section_width = 170
    section_height = 160

    # Common dimensions
    wall_thick = 140
    sheathing = 12
    siding = 20
    drywall = 16
    door_thick = 44  # 1-3/4" door

    # =========== HEAD DETAIL ===========
    head_x = 25
    head_y = 45

    svg_lines.append(f'  <text x="{head_x + section_width/2}" y="{head_y - 10}" font-family="Arial" font-size="12" font-weight="bold" text-anchor="middle">DOOR HEAD</text>')

    current_x = head_x

    # Exterior siding
    svg_lines.append(f'  <rect x="{current_x}" y="{head_y}" width="{siding}" height="{50}" fill="url(#hatch-siding)" stroke="#000" stroke-width="0.5"/>')

    # Sheathing
    svg_lines.append(f'  <rect x="{current_x + siding}" y="{head_y}" width="{sheathing}" height="{section_height}" fill="url(#hatch-plywood)" stroke="#000" stroke-width="0.5"/>')

    # Header (double 2x10)
    svg_lines.append(f'  <rect x="{current_x + siding + sheathing}" y="{head_y}" width="{wall_thick}" height="{38}" fill="url(#hatch-wood)" stroke="#000" stroke-width="1"/>')
    svg_lines.append(f'  <rect x="{current_x + siding + sheathing}" y="{head_y + 38}" width="{wall_thick}" height="{38}" fill="url(#hatch-wood)" stroke="#000" stroke-width="1"/>')

    # Cripple stud above header (if height allows)
    svg_lines.append(f'  <rect x="{current_x + siding + sheathing + 50}" y="{head_y - 25}" width="{38}" height="{25}" fill="url(#hatch-wood)" stroke="#000" stroke-width="1"/>')

    # Drywall
    svg_lines.append(f'  <rect x="{current_x + siding + sheathing + wall_thick}" y="{head_y}" width="{drywall}" height="{section_height}" fill="url(#hatch-gypsum)" stroke="#000" stroke-width="0.5"/>')

    # Door frame/jamb
    frame_y = head_y + 80
    svg_lines.append(f'  <rect x="{current_x + siding + sheathing + 10}" y="{frame_y}" width="{wall_thick - 20}" height="{30}" fill="url(#hatch-wood)" stroke="#000" stroke-width="1"/>')

    # Door (shown partially)
    door_y = frame_y + 32
    svg_lines.append(f'  <rect x="{current_x + siding + sheathing + 30}" y="{door_y}" width="{door_thick}" height="{section_height - door_y + head_y}" fill="#F5F0E8" stroke="#000" stroke-width="1.5"/>')

    # Interior casing
    svg_lines.append(f'  <rect x="{current_x + siding + sheathing + wall_thick + drywall}" y="{frame_y - 5}" width="{18}" height="{section_height - frame_y + head_y + 10}" fill="url(#hatch-wood)" stroke="#000" stroke-width="0.5"/>')

    # Head flashing (for exterior door)
    svg_lines.append(f'  <path d="M {current_x + siding - 2},{head_y + 45} L {current_x + siding - 2},{head_y + 52} L {current_x + siding + sheathing + 15},{head_y + 52}" fill="none" stroke="#000" stroke-width="1.5"/>')

    # Labels
    svg_lines.append(f'  <text x="{head_x + section_width + 8}" y="{head_y + 30}" font-family="Arial" font-size="8" fill="#333">(2) 2x10 HDR</text>')
    svg_lines.append(f'  <text x="{head_x + section_width + 8}" y="{head_y - 15}" font-family="Arial" font-size="8" fill="#333">CRIPPLE</text>')
    svg_lines.append(f'  <text x="{head_x + section_width + 8}" y="{frame_y + 20}" font-family="Arial" font-size="8" fill="#333">DOOR FRAME</text>')
    svg_lines.append(f'  <text x="{head_x + section_width + 8}" y="{door_y + 30}" font-family="Arial" font-size="8" fill="#333">1-3/4\" DOOR</text>')
    svg_lines.append(f'  <text x="{head_x + section_width + 8}" y="{frame_y + 50}" font-family="Arial" font-size="8" fill="#333">CASING</text>')

    # =========== THRESHOLD DETAIL ===========
    thresh_x = head_x + section_width + 55
    thresh_y = head_y

    svg_lines.append(f'  <text x="{thresh_x + section_width/2}" y="{thresh_y - 10}" font-family="Arial" font-size="12" font-weight="bold" text-anchor="middle">THRESHOLD</text>')

    current_x = thresh_x

    # Exterior side (left) - concrete stoop or porch
    svg_lines.append(f'  <rect x="{current_x}" y="{thresh_y + 70}" width="{50}" height="{section_height - 70}" fill="url(#hatch-concrete)" stroke="#000" stroke-width="1"/>')

    # Threshold/sill pan
    thresh_top = thresh_y + 55
    svg_lines.append(f'  <polygon points="{current_x + 45},{thresh_top + 15} {current_x + 100},{thresh_top + 15} {current_x + 105},{thresh_top} {current_x + 40},{thresh_top}" fill="url(#hatch-metal)" stroke="#000" stroke-width="1"/>')

    # Door sill/frame bottom
    svg_lines.append(f'  <rect x="{current_x + 50}" y="{thresh_top + 15}" width="{60}" height="{20}" fill="url(#hatch-wood)" stroke="#000" stroke-width="1"/>')

    # Subfloor
    subfloor_y = thresh_top + 35
    svg_lines.append(f'  <rect x="{current_x + 80}" y="{subfloor_y}" width="{90}" height="{18}" fill="url(#hatch-plywood)" stroke="#000" stroke-width="1"/>')

    # Floor joists
    svg_lines.append(f'  <rect x="{current_x + 85}" y="{subfloor_y + 18}" width="{38}" height="{section_height - subfloor_y - 18 + thresh_y}" fill="url(#hatch-wood)" stroke="#000" stroke-width="1"/>')
    svg_lines.append(f'  <rect x="{current_x + 130}" y="{subfloor_y + 18}" width="{38}" height="{section_height - subfloor_y - 18 + thresh_y}" fill="url(#hatch-wood)" stroke="#000" stroke-width="1"/>')

    # Rim joist
    svg_lines.append(f'  <rect x="{current_x + 50}" y="{subfloor_y + 18}" width="{30}" height="{50}" fill="url(#hatch-wood)" stroke="#000" stroke-width="1"/>')

    # Sill plate on foundation
    svg_lines.append(f'  <rect x="{current_x + 50}" y="{subfloor_y + 68}" width="{30}" height="{38}" fill="url(#hatch-wood)" stroke="#000" stroke-width="1"/>')

    # Finish floor
    svg_lines.append(f'  <rect x="{current_x + 110}" y="{subfloor_y - 12}" width="{60}" height="{12}" fill="url(#hatch-wood)" stroke="#000" stroke-width="0.5"/>')

    # Door (bottom portion)
    svg_lines.append(f'  <rect x="{current_x + 60}" y="{thresh_y}" width="{door_thick}" height="{thresh_top}" fill="#F5F0E8" stroke="#000" stroke-width="1.5"/>')

    # Weather stripping
    svg_lines.append(f'  <ellipse cx="{current_x + 58}" cy="{thresh_top + 8}" rx="4" ry="6" fill="#333" stroke="none"/>')

    # Interior drywall
    svg_lines.append(f'  <rect x="{current_x + section_width - 20}" y="{thresh_y}" width="{16}" height="{section_height}" fill="url(#hatch-gypsum)" stroke="#000" stroke-width="0.5"/>')

    # Labels
    svg_lines.append(f'  <text x="{current_x - 5}" y="{thresh_y + 100}" font-family="Arial" font-size="8" fill="#333" text-anchor="end">STOOP</text>')
    svg_lines.append(f'  <text x="{thresh_x + section_width + 8}" y="{thresh_top + 10}" font-family="Arial" font-size="8" fill="#333">THRESHOLD</text>')
    svg_lines.append(f'  <text x="{thresh_x + section_width + 8}" y="{thresh_top + 30}" font-family="Arial" font-size="8" fill="#333">DOOR SILL</text>')
    svg_lines.append(f'  <text x="{thresh_x + section_width + 8}" y="{subfloor_y + 10}" font-family="Arial" font-size="8" fill="#333">SUBFLOOR</text>')
    svg_lines.append(f'  <text x="{thresh_x + section_width + 8}" y="{subfloor_y - 5}" font-family="Arial" font-size="8" fill="#333">FIN. FLOOR</text>')
    svg_lines.append(f'  <text x="{thresh_x + section_width + 8}" y="{subfloor_y + 50}" font-family="Arial" font-size="8" fill="#333">RIM JOIST</text>')
    svg_lines.append(f'  <text x="{thresh_x + section_width + 8}" y="{thresh_top - 10}" font-family="Arial" font-size="8" fill="#333">WEATHERSTRIP</text>')

    # =========== OVERALL LABEL ===========
    svg_lines.append(f'  <text x="{detail_width/2}" y="{thresh_y + section_height + 25}" font-family="Arial" font-size="9" fill="#666" text-anchor="middle">SCALE: 1:5  |  EXTERIOR DOOR SHOWN</text>')

    return Detail(
        name="DOOR DETAILS",
        number="4",
        scale="1:5",
        width=detail_width,
        height=detail_height,
        svg_content='\n'.join(svg_lines)
    )


# =============================================================================
# SVG RENDERER
# =============================================================================

def render_details_svg(details: List[Detail], project_info: Dict = None) -> str:
    """Render all details to a single SVG sheet."""

    # Sheet layout
    margin = 500  # mm
    sheet_width = 16000   # ~A1 width in mm at 1:1
    sheet_height = 12000  # ~A1 height

    # Calculate detail positions (2x2 grid)
    detail_positions = [
        (margin + 500, margin + 1500),      # Top left
        (sheet_width/2 + 500, margin + 1500),  # Top right
        (margin + 500, sheet_height/2 + 500),  # Bottom left
        (sheet_width/2 + 500, sheet_height/2 + 500),  # Bottom right
    ]

    # Scale details to fit
    detail_scale = 8  # Scale up from detail model space to sheet space

    lines = []
    lines.append(f'<?xml version="1.0" encoding="UTF-8"?>')
    lines.append(f'<svg xmlns="http://www.w3.org/2000/svg"')
    lines.append(f'     width="1000" height="750"')
    # Extend viewBox to include title block border at negative coordinates
    lines.append(f'     viewBox="-300 -300 {sheet_width + 600} {sheet_height + 600}">')

    # Background (covers entire viewBox including negative area)
    lines.append(f'<rect x="-300" y="-300" width="{sheet_width + 600}" height="{sheet_height + 600}" fill="white"/>')

    # Patterns (scaled to match detail_scale)
    lines.append('<defs>')
    lines.append(generate_hatch_patterns(detail_scale))
    lines.append('</defs>')

    # Styles
    lines.append('''<style>
    .detail-title { font-family: Arial, sans-serif; font-size: 200px; font-weight: bold; fill: #333; }
    .detail-scale { font-family: Arial, sans-serif; font-size: 120px; fill: #666; }
    .detail-number { font-family: Arial, sans-serif; font-size: 160px; font-weight: bold; fill: #333; }
</style>''')

    # Sheet title
    lines.append(f'<text x="{sheet_width/2}" y="{margin - 100}" text-anchor="middle" class="detail-title">CONSTRUCTION DETAILS</text>')

    # Render each detail
    for i, detail in enumerate(details):
        if i >= len(detail_positions):
            break

        x, y = detail_positions[i]

        # Detail border
        detail_w = detail.width * detail_scale
        detail_h = detail.height * detail_scale
        lines.append(f'<rect x="{x - 100}" y="{y - 100}" width="{detail_w + 200}" height="{detail_h + 400}" fill="none" stroke="#ccc" stroke-width="2"/>')

        # Detail title
        lines.append(f'<text x="{x + detail_w/2}" y="{y - 50}" text-anchor="middle" class="detail-number">{detail.number}</text>')
        lines.append(f'<text x="{x + detail_w/2}" y="{y + detail_h + 150}" text-anchor="middle" font-family="Arial" font-size="140" font-weight="bold">{detail.name}</text>')
        lines.append(f'<text x="{x + detail_w/2}" y="{y + detail_h + 280}" text-anchor="middle" class="detail-scale">SCALE: {detail.scale}</text>')

        # Detail content (scaled and translated)
        lines.append(f'<g transform="translate({x}, {y}) scale({detail_scale})">')
        lines.append(detail.svg_content)
        lines.append('</g>')

    # Title block
    if project_info:
        drawing_info = {
            'title': 'CONSTRUCTION DETAILS',
            'number': 'A-501',
            'scale': 'AS NOTED',
            'sheet': '1 OF 1',
            'revision': '-',
            'drawn_by': 'AE',
        }
        lines.append(generate_title_block(sheet_width - 2*margin, sheet_height - 2*margin,
                                          project_info, drawing_info, scale=1.0, margin=margin))

    lines.append('</svg>')

    return '\n'.join(lines)


# =============================================================================
# MAIN
# =============================================================================

def generate_details(input_path: str, output_dir: str):
    """Generate detail drawings from building JSON."""

    # Load building data
    with open(input_path, 'r') as f:
        data = json.load(f)

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Get project info
    project_info = get_project_info_from_json(data)

    # Get wall types from data
    wall_types = data.get('wall_types', [])

    # Generate details
    print("Generating construction details...")

    details = [
        generate_wall_section_detail(wall_types),
        generate_eave_detail(),
        generate_window_detail(),
        generate_door_detail(),
    ]

    # Render to SVG
    svg = render_details_svg(details, project_info)

    out_file = output_path / "details.svg"
    with open(out_file, 'w') as f:
        f.write(svg)

    print(f"  Wrote {out_file}")
    print(f"  - {len(details)} details generated")
    for d in details:
        print(f"    {d.number}. {d.name} ({d.scale})")


def main():
    parser = argparse.ArgumentParser(description='Generate construction detail drawings')
    parser.add_argument('input', nargs='?',
                        default='../../Shared/TestData/output/generated_building.json',
                        help='Input JSON file path')
    parser.add_argument('-o', '--output',
                        default='../../Shared/TestData/output',
                        help='Output directory for SVG files')
    parser.add_argument('-s', '--scale', type=float, default=0.05,
                        help='Scale factor (unused, for compatibility)')

    args = parser.parse_args()

    generate_details(args.input, args.output)


if __name__ == '__main__':
    main()
