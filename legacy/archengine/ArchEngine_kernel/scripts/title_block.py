#!/usr/bin/env python3
"""
title_block.py - Standard architectural title block for all drawings

Generates SVG title blocks with:
- Drawing border
- Project information
- Drawing title and number
- Scale, date, revision info
- Company/architect information
"""

from datetime import datetime
from typing import Dict, Optional

def generate_title_block(
    width: float,
    height: float,
    project_info: Dict,
    drawing_info: Dict,
    scale: float = 0.05,
    margin: float = 500
) -> str:
    """
    Generate an SVG title block.

    Args:
        width: Drawing width in mm (model space)
        height: Drawing height in mm (model space)
        project_info: Dict with project details
        drawing_info: Dict with drawing-specific info
        scale: Drawing scale factor
        margin: Margin around drawing in mm

    Returns:
        SVG string for title block
    """

    # Title block dimensions (in mm, model space)
    tb_width = 4000   # Title block width
    tb_height = 1200  # Title block height
    border_margin = 300  # Margin from edge to border

    # Calculate positions
    border_x = -margin + border_margin
    border_y = -margin + border_margin
    border_w = width + 2 * margin - 2 * border_margin
    border_h = height + 2 * margin - 2 * border_margin

    # Title block position (bottom right)
    tb_x = border_x + border_w - tb_width - 100
    tb_y = border_y + border_h - tb_height - 100

    # Extract info with defaults
    project_name = project_info.get('name', 'RESIDENTIAL PROJECT')
    project_address = project_info.get('address', '')
    client_name = project_info.get('client', '')
    project_number = project_info.get('number', 'P-001')

    drawing_title = drawing_info.get('title', 'FLOOR PLAN')
    drawing_number = drawing_info.get('number', 'A-101')
    drawing_scale = drawing_info.get('scale', '1:100')
    revision = drawing_info.get('revision', '-')
    drawn_by = drawing_info.get('drawn_by', 'ARCHENGINE')
    checked_by = drawing_info.get('checked_by', '')

    date_str = datetime.now().strftime('%Y-%m-%d')

    svg = f'''<!-- Title Block -->
<g id="title-block">
  <!-- Drawing Border -->
  <rect x="{border_x}" y="{border_y}" width="{border_w}" height="{border_h}"
        fill="none" stroke="#000" stroke-width="8"/>

  <!-- Inner Border -->
  <rect x="{border_x + 50}" y="{border_y + 50}" width="{border_w - 100}" height="{border_h - 100}"
        fill="none" stroke="#000" stroke-width="2"/>

  <!-- Title Block Box -->
  <rect x="{tb_x}" y="{tb_y}" width="{tb_width}" height="{tb_height}"
        fill="white" stroke="#000" stroke-width="4"/>

  <!-- Title Block Grid Lines -->
  <!-- Horizontal dividers -->
  <line x1="{tb_x}" y1="{tb_y + 300}" x2="{tb_x + tb_width}" y2="{tb_y + 300}" stroke="#000" stroke-width="2"/>
  <line x1="{tb_x}" y1="{tb_y + 600}" x2="{tb_x + tb_width}" y2="{tb_y + 600}" stroke="#000" stroke-width="2"/>
  <line x1="{tb_x}" y1="{tb_y + 900}" x2="{tb_x + tb_width}" y2="{tb_y + 900}" stroke="#000" stroke-width="2"/>

  <!-- Vertical dividers -->
  <line x1="{tb_x + 2000}" y1="{tb_y + 600}" x2="{tb_x + 2000}" y2="{tb_y + tb_height}" stroke="#000" stroke-width="2"/>
  <line x1="{tb_x + 3000}" y1="{tb_y + 600}" x2="{tb_x + 3000}" y2="{tb_y + tb_height}" stroke="#000" stroke-width="2"/>

  <!-- Project Name (large, top row) -->
  <text x="{tb_x + tb_width/2}" y="{tb_y + 200}"
        font-family="Arial" font-size="200" font-weight="bold" text-anchor="middle">{project_name}</text>

  <!-- Project Address -->
  <text x="{tb_x + tb_width/2}" y="{tb_y + 450}"
        font-family="Arial" font-size="120" text-anchor="middle" fill="#333">{project_address}</text>

  <!-- Client Name -->
  <text x="{tb_x + tb_width/2}" y="{tb_y + 550}"
        font-family="Arial" font-size="100" text-anchor="middle" fill="#666">{client_name}</text>

  <!-- Drawing Title (large) -->
  <text x="{tb_x + 1000}" y="{tb_y + 800}"
        font-family="Arial" font-size="180" font-weight="bold" text-anchor="middle">{drawing_title}</text>

  <!-- Labels and Values Row -->
  <!-- Scale -->
  <text x="{tb_x + 100}" y="{tb_y + 970}"
        font-family="Arial" font-size="80" fill="#666">SCALE</text>
  <text x="{tb_x + 100}" y="{tb_y + 1100}"
        font-family="Arial" font-size="120" font-weight="bold">{drawing_scale}</text>

  <!-- Date -->
  <text x="{tb_x + 700}" y="{tb_y + 970}"
        font-family="Arial" font-size="80" fill="#666">DATE</text>
  <text x="{tb_x + 700}" y="{tb_y + 1100}"
        font-family="Arial" font-size="120">{date_str}</text>

  <!-- Drawn By -->
  <text x="{tb_x + 1400}" y="{tb_y + 970}"
        font-family="Arial" font-size="80" fill="#666">DRAWN</text>
  <text x="{tb_x + 1400}" y="{tb_y + 1100}"
        font-family="Arial" font-size="120">{drawn_by}</text>

  <!-- Drawing Number -->
  <text x="{tb_x + 2100}" y="{tb_y + 700}"
        font-family="Arial" font-size="80" fill="#666">DWG NO.</text>
  <text x="{tb_x + 2500}" y="{tb_y + 850}"
        font-family="Arial" font-size="200" font-weight="bold" text-anchor="middle">{drawing_number}</text>

  <!-- Project Number -->
  <text x="{tb_x + 2100}" y="{tb_y + 970}"
        font-family="Arial" font-size="80" fill="#666">PROJECT</text>
  <text x="{tb_x + 2100}" y="{tb_y + 1100}"
        font-family="Arial" font-size="100">{project_number}</text>

  <!-- Revision -->
  <text x="{tb_x + 3100}" y="{tb_y + 700}"
        font-family="Arial" font-size="80" fill="#666">REV</text>
  <text x="{tb_x + 3500}" y="{tb_y + 850}"
        font-family="Arial" font-size="200" font-weight="bold" text-anchor="middle">{revision}</text>

  <!-- Sheet Info -->
  <text x="{tb_x + 3100}" y="{tb_y + 970}"
        font-family="Arial" font-size="80" fill="#666">SHEET</text>
  <text x="{tb_x + 3100}" y="{tb_y + 1100}"
        font-family="Arial" font-size="100">{drawing_info.get('sheet', '1 OF 8')}</text>

  <!-- Solver Info (small text, top left of title block) -->
  <text x="{tb_x + 50}" y="{tb_y + 50}"
        font-family="Arial" font-size="60" fill="#999">{drawing_info.get('solver', 'QBD Layout')}</text>

</g>'''

    return svg


def get_project_info_from_json(data: Dict) -> Dict:
    """Extract project information from building JSON."""

    qbd = data.get('qbd_answers', {})

    # Build project name from description or building type
    description = qbd.get('description', '')
    bedrooms = qbd.get('bedrooms', '')
    bathrooms = qbd.get('bathrooms', '')

    if description:
        project_name = description.upper()[:40]  # Truncate if too long
    elif bedrooms and bathrooms:
        project_name = f"{bedrooms} BED {bathrooms} BATH RESIDENCE"
    else:
        project_name = "RESIDENTIAL PROJECT"

    # Get solver info
    solver_used = data.get('_solver_used', 'qbd')
    solver_labels = {
        'grid': 'Grid Solver',
        'wave_collapse': 'WFC Solver',
        'tree': 'Tree Solver',
        'perfect_adjacency': 'Adjacency Solver',
        'constraint': 'Constraint Solver',
        'genetic': 'Genetic Solver',
        'annealing': 'Annealing Solver',
        'force_directed': 'Force Solver',
        'space_colonization': 'Growth Solver',
        'qbd': 'QBD Layout',
    }
    solver_display = solver_labels.get(solver_used, solver_used.upper())

    return {
        'name': project_name,
        'address': qbd.get('address', ''),
        'client': qbd.get('client_name', ''),
        'number': data.get('building_id', 'P-001'),
        'solver': solver_display,
    }


# Drawing number mapping
DRAWING_NUMBERS = {
    'floor_plan': ('A-101', 'FLOOR PLAN - LEVEL 1', '1 OF 8'),
    'roof_plan': ('A-102', 'ROOF PLAN', '2 OF 8'),
    'elevation_south': ('A-201', 'SOUTH ELEVATION', '3 OF 8'),
    'elevation_north': ('A-202', 'NORTH ELEVATION', '4 OF 8'),
    'elevation_east': ('A-203', 'EAST ELEVATION', '5 OF 8'),
    'elevation_west': ('A-204', 'WEST ELEVATION', '6 OF 8'),
    'section_a': ('A-301', 'SECTION A-A', '7 OF 8'),
    'section_b': ('A-302', 'SECTION B-B', '8 OF 8'),
}


def get_drawing_info(drawing_type: str, scale: str = '1:100') -> Dict:
    """Get drawing info for a specific drawing type."""

    number, title, sheet = DRAWING_NUMBERS.get(drawing_type, ('A-000', 'DRAWING', '1 OF 1'))

    return {
        'title': title,
        'number': number,
        'scale': scale,
        'sheet': sheet,
        'revision': '-',
        'drawn_by': 'AE',  # ArchEngine
    }
