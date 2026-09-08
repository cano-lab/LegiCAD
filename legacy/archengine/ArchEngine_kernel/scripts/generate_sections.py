#!/usr/bin/env python3
"""
generate_sections.py - Generate building section drawings

Creates cross-sections through the building at specified locations,
showing cut walls, floor structure, roof, and interior spaces.
"""

import json
import math
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional


@dataclass
class SectionCut:
    """A section cut through the building."""
    name: str
    cut_x: float  # X coordinate of cut plane (mm)
    cut_z: float  # Z coordinate of cut plane (mm) - for longitudinal sections
    direction: str  # 'transverse' (X-cut) or 'longitudinal' (Z-cut)
    view_direction: str  # Which way to look: 'east', 'west', 'north', 'south'


@dataclass
class SectionElement:
    """Element visible in section."""
    element_type: str  # 'wall', 'floor', 'ceiling', 'roof', 'opening', 'grade'
    x: float  # Horizontal position in section view
    y_bottom: float  # Vertical bottom
    y_top: float  # Vertical top
    width: float  # For openings
    label: str = ""


def generate_section(data: dict, cut: SectionCut) -> List[SectionElement]:
    """Generate section elements for a cut through the building."""
    
    elements = []
    walls = data.get('walls_batch', [])
    
    tolerance = 100  # mm tolerance for cut plane
    
    # Find walls intersected by the cut plane
    cut_walls = []
    for wall in walls:
        start = wall.get('start', [0, 0, 0])
        end = wall.get('end', [0, 0, 0])
        
        if cut.direction == 'transverse':
            # Cut is perpendicular to X axis - wall runs in Z direction
            # Check if wall spans the cut X coordinate
            wall_min_x = min(start[0], end[0])
            wall_max_x = max(start[0], end[0])
            
            if wall_min_x - tolerance <= cut.cut_x <= wall_max_x + tolerance:
                cut_walls.append(wall)
        else:
            # Cut is perpendicular to Z axis - wall runs in X direction
            wall_min_z = min(start[2], end[2])
            wall_max_z = max(start[2], end[2])
            
            if wall_min_z - tolerance <= cut.cut_z <= wall_max_z + tolerance:
                cut_walls.append(wall)
    
    # Add cut walls as elements
    for wall in cut_walls:
        start = wall.get('start', [0, 0, 0])
        end = wall.get('end', [0, 0, 0])
        height = wall.get('height', 2700)
        
        # Position in section view depends on cut direction
        if cut.direction == 'transverse':
            # For transverse cut, Z becomes the horizontal axis
            pos = (start[2] + end[2]) / 2
        else:
            # For longitudinal cut, X becomes the horizontal axis
            pos = (start[0] + end[0]) / 2
        
        thickness = 150 if wall.get('category') == 'exterior' else 100
        
        elements.append(SectionElement(
            element_type='wall',
            x=pos,
            y_bottom=0,
            y_top=height,
            width=thickness,
            label=wall.get('category', 'wall')
        ))
    
    # Add floor slab
    elements.append(SectionElement(
        element_type='floor',
        x=0,  # Will be positioned based on view
        y_bottom=-150,  # 150mm thick slab
        y_top=0,
        width=0,
        label='Floor'
    ))
    
    # Add roof from roof data
    for roof in data.get('roofs', []):
        base_height = roof.get('base_height', 2700)
        ridge_height = base_height + roof.get('ridge_height', 1000)
        
        elements.append(SectionElement(
            element_type='roof',
            x=0,
            y_bottom=base_height,
            y_top=ridge_height,
            width=0,
            label='Roof'
        ))
    
    # Sort elements by X position
    elements.sort(key=lambda e: e.x)
    
    return elements


def render_section_svg(elements: List[SectionElement], cut: SectionCut, 
                       scale: float = 0.05) -> str:
    """Render section elements to SVG."""
    
    # Calculate bounds
    all_x = [e.x for e in elements]
    all_y = [e.y_bottom for e in elements] + [e.y_top for e in elements]
    
    min_x, max_x = min(all_x) if all_x else 0, max(all_x) if all_x else 10000
    min_y, max_y = min(all_y) if all_y else -200, max(all_y) if all_y else 5000
    
    # Add margins
    margin_x = 1000
    margin_y = 500
    
    vb_x = min_x - margin_x
    vb_y = min_y - margin_y
    vb_w = (max_x - min_x) + 2 * margin_x
    vb_h = (max_y - min_y) + 2 * margin_y
    
    # SVG pixel size
    px_width = int(vb_w * scale)
    px_height = int(vb_h * scale)
    
    lines = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    lines.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{px_width}" height="{px_height}" viewBox="{vb_x} {vb_y} {vb_w} {vb_h}">')
    lines.append(f'  <title>Section {cut.name}</title>')
    lines.append('  <rect width="100%" height="100%" fill="white"/>')
    
    # Styles
    lines.append('  <style>')
    lines.append('    .wall-cut { fill: #666; stroke: #000; stroke-width: 8; }')
    lines.append('    .wall-below { fill: url(#earth-hatch); stroke: #000; stroke-width: 4; }')
    lines.append('    .floor { fill: #999; stroke: #000; stroke-width: 4; }')
    lines.append('    .roof { fill: url(#shingle-pattern); stroke: #000; stroke-width: 6; }')
    lines.append('    .grade { stroke: #666; stroke-width: 6; fill: none; }')
    lines.append('    .level-line { stroke: #999; stroke-width: 2; stroke-dasharray: 50,25; }')
    lines.append('    .level-text { font-family: Arial, sans-serif; font-size: 200px; fill: #666; }')
    lines.append('    .title { font-family: Arial, sans-serif; font-size: 400px; font-weight: bold; fill: #333; }')
    lines.append('    .dimension { font-family: Arial, sans-serif; font-size: 180px; fill: #333; }')
    lines.append('    .label { font-family: Arial, sans-serif; font-size: 250px; fill: #333; }')
    lines.append('    .cut-line { stroke: #c00; stroke-width: 4; stroke-dasharray: 20,10; }')
    lines.append('  </style>')
    
    # Patterns
    lines.append('  <defs>')
    lines.append('    <pattern id="earth-hatch" patternUnits="userSpaceOnUse" width="200" height="200">')
    lines.append('      <rect width="200" height="200" fill="#d4c9b8"/>')
    lines.append('      <line x1="0" y1="200" x2="200" y2="0" stroke="#b0a080" stroke-width="6"/>')
    lines.append('    </pattern>')
    lines.append('    <pattern id="shingle-pattern" patternUnits="userSpaceOnUse" width="400" height="200">')
    lines.append('      <rect width="400" height="200" fill="#5a5a5a"/>')
    lines.append('      <line x1="0" y1="100" x2="400" y2="100" stroke="#484848" stroke-width="6"/>')
    lines.append('      <line x1="0" y1="200" x2="400" y2="200" stroke="#484848" stroke-width="6"/>')
    lines.append('    </pattern>')
    lines.append('  </defs>')
    
    # Flip Y axis for elevation-style drawing
    flip_y = max_y + min_y
    lines.append(f'<g transform="translate(0, {flip_y}) scale(1, -1)">')
    
    # Render elements
    for elem in elements:
        if elem.element_type == 'wall':
            # Wall cut - show hatch pattern
            w = elem.width
            x = elem.x - w/2
            h = elem.y_top - elem.y_bottom
            lines.append(f'    <rect x="{x}" y="{elem.y_bottom}" width="{w}" height="{h}" class="wall-cut"/>')
            
        elif elem.element_type == 'floor':
            # Floor slab - span full width
            lines.append(f'    <rect x="{min_x - 500}" y="{elem.y_bottom}" width="{max_x - min_x + 1000}" height="{elem.y_top - elem.y_bottom}" class="floor"/>')
            
        elif elem.element_type == 'roof':
            # Roof as triangle for gable
            center_x = (min_x + max_x) / 2
            lines.append(f'    <polygon points="{min_x},{elem.y_bottom} {center_x},{elem.y_top} {max_x},{elem.y_bottom}" class="roof"/>')
    
    # Grade line
    lines.append(f'    <line x1="{min_x - 500}" y1="0" x2="{max_x + 500}" y2="0" class="grade"/>')
    
    # Level markers
    lines.append(f'    <line x1="{min_x - 800}" y1="0" x2="{max_x + 800}" y2="0" class="level-line"/>')
    lines.append(f'    <text x="{min_x - 1000}" y="100" class="level-text">0.0m</text>')
    lines.append(f'    <text x="{min_x - 1200}" y="300" class="level-text">Grade</text>')
    
    # Close flipped group
    lines.append('  </g>')
    
    # Title (not flipped)
    title_y = vb_y + vb_h - 200
    lines.append(f'  <text x="{(vb_x + vb_w/2):.0f}" y="{title_y}" text-anchor="middle" class="title">SECTION {cut.name}</text>')
    
    # Cut indicator
    lines.append(f'  <text x="{vb_x + 200}" y="{vb_y + 300}" class="label">View: Looking {cut.view_direction}</text>')
    
    lines.append('</svg>')
    return '\n'.join(lines)


def main():
    """Generate example section."""
    test_json = Path('/root/.openclaw/workspace/test_pipeline/test_house.json')
    
    with open(test_json) as f:
        data = json.load(f)
    
    # Convert to kernel format
    kernel_data = {
        'name': data.get('name', 'Test House'),
        'width': data.get('width_m', 10) * 1000,
        'depth': data.get('depth_m', 10) * 1000,
        'walls_batch': [],
        'roofs': [{
            'type': 'gable',
            'base_height': 2700,
            'ridge_height': 1000
        }]
    }
    
    for wall in data.get('walls', []):
        kernel_data['walls_batch'].append({
            'start': wall.get('start', [0, 0, 0]),
            'end': wall.get('end', [0, 0, 0]),
            'category': wall.get('category', 'interior'),
            'height': 2700
        })
    
    # Create section cut through center of building
    cut = SectionCut(
        name='A-A',
        cut_x=kernel_data['width'] / 2,
        cut_z=0,
        direction='transverse',
        view_direction='east'
    )
    
    elements = generate_section(kernel_data, cut)
    svg = render_section_svg(elements, cut)
    
    output_dir = Path('/root/.openclaw/workspace/test_pipeline/permit_set/sections')
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / 'section_aa.svg'
    
    with open(output_path, 'w') as f:
        f.write(svg)
    
    print(f"Section generated: {output_path}")
    print(f"Elements in section: {len(elements)}")
    for e in elements:
        print(f"  {e.element_type}: x={e.x:.0f}, y={e.y_bottom:.0f}-{e.y_top:.0f}")


if __name__ == '__main__':
    main()
