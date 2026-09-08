#!/usr/bin/env python3
"""
ArchEngine Plan Generator
Generates annotated floor plans and roof plans from QBD JSON output.
Plans update automatically when JSON changes.

Now uses shared ArchGeometry library for consistent geometry interpretation.
"""

import json
import math
import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional

from title_block import generate_title_block, get_project_info_from_json, get_drawing_info

# Import intelligent dimensioning
try:
    from intelligent_dimensions import generate_intelligent_dimensions, DimTier
    _INTELLIGENT_DIM_AVAILABLE = True
except ImportError:
    _INTELLIGENT_DIM_AVAILABLE = False

# Try to import shared geometry library
_ARCHGEOMETRY_AVAILABLE = False
try:
    # Add shared library path
    _lib_path = Path(__file__).parent.parent.parent / "Shared" / "ArchGeometry" / "python"
    if _lib_path.exists() and str(_lib_path) not in sys.path:
        sys.path.insert(0, str(_lib_path))
    import archgeometry_py as archgeometry
    _ARCHGEOMETRY_AVAILABLE = True
except ImportError:
    archgeometry = None

# Local dataclasses (kept for compatibility, will be replaced by archgeometry types when available)
@dataclass
class Wall:
    start: Tuple[float, float, float]
    end: Tuple[float, float, float]
    height: float
    category: str
    wall_type: str
    index: int

@dataclass
class Door:
    wall_index: int
    offset: float
    width: float
    height: float
    door_type: str
    swing: str

@dataclass
class Window:
    wall_index: int
    offset: float
    width: float
    height: float
    sill_height: float

@dataclass
class Room:
    name: str
    room_type: str
    bounds: Dict
    area: float
    center: Dict

@dataclass
class Roof:
    id: str
    roof_type: str  # gable, hip, flat, shed, mansard, gambrel
    pitch: float  # Rise over 12" run (e.g., 4 for 4:12)
    overhang: float  # Eave overhang in mm
    ridges: List[Dict] = field(default_factory=list)
    surfaces: List[Dict] = field(default_factory=list)
    skylights: List[Dict] = field(default_factory=list)
    dormers: List[Dict] = field(default_factory=list)

class PlanGenerator:
    def __init__(self, json_path: str):
        with open(json_path, 'r') as f:
            self.data = json.load(f)

        # Try to use archgeometry for parsing (provides consistent interpretation)
        self._schema_doc = None
        self._query_api = None
        if _ARCHGEOMETRY_AVAILABLE and archgeometry is not None:
            try:
                with open(json_path, 'r') as f:
                    json_str = f.read()
                self._schema_doc = archgeometry.parse_json(json_str)
                self._query_api = archgeometry.QueryAPI(self._schema_doc)
            except Exception as e:
                print(f"Warning: archgeometry parsing failed, using fallback: {e}")
                self._schema_doc = None
                self._query_api = None

        # Parse elements (uses archgeometry types if available, falls back to local)
        self.walls = self._parse_walls()
        self.doors = self._parse_doors()
        self.windows = self._parse_windows()
        self.rooms = self._parse_rooms()
        self.roofs = self._parse_roofs()

        # Get building bounds
        self.width = self.data.get('width', 12000)
        self.depth = self.data.get('depth', 9000)

        # Building type - residential buildings don't need grid lines
        building_type = self.data.get('building_type', 'residential')
        qbd_answers = self.data.get('qbd_answers', {})
        self.is_residential = building_type.lower() in ['residential', 'house', 'home'] or \
                              qbd_answers.get('building_type', '').lower() in ['residential', 'house', 'home'] or \
                              'bedroom' in str(qbd_answers).lower()

        # Wall thickness (mm)
        self.ext_wall_thickness = 175
        self.int_wall_thickness = 115

        # Roof defaults
        self.default_overhang = 600  # 600mm overhang
        self.default_pitch = 4  # 4:12 pitch

        # Text sizes (in viewBox units/mm) - configurable
        self.dim_text_size = self.data.get('dim_text_size', 300)      # Dimension text
        self.room_text_size = self.data.get('room_text_size', 500)    # Room labels
        self.room_area_size = self.data.get('room_area_size', 350)    # Room area text
        self.title_text_size = self.data.get('title_text_size', 500)  # Title text
        self.grid_label_size = self.data.get('grid_label_size', 350)  # Grid bubble labels

    def _parse_walls(self) -> List[Wall]:
        walls = []
        for i, w in enumerate(self.data.get('walls_batch', [])):
            walls.append(Wall(
                start=tuple(w['start']),
                end=tuple(w['end']),
                height=w['height'],
                category=w['category'],
                wall_type=w.get('wall_type', ''),
                index=i
            ))
        return walls

    def _parse_doors(self) -> List[Door]:
        doors = []
        for d in self.data.get('doors', []):
            doors.append(Door(
                wall_index=d['wall_index'],
                offset=d['offset'],
                width=d['width'],
                height=d['height'],
                door_type=d.get('type', 'swing'),
                swing=d.get('swing', 'left_in')
            ))
        return doors

    def _parse_windows(self) -> List[Window]:
        windows = []
        for w in self.data.get('windows', []):
            windows.append(Window(
                wall_index=w['wall_index'],
                offset=w['offset'],
                width=w['width'],
                height=w['height'],
                sill_height=w.get('sill_height', 900)
            ))
        return windows

    def _parse_rooms(self) -> Dict[str, Room]:
        rooms = {}
        for room_id, r in self.data.get('rooms', {}).items():
            rooms[room_id] = Room(
                name=r.get('name', room_id),
                room_type=r.get('room_type', ''),
                bounds=r.get('bounds', {}),
                area=r.get('area', 0),
                center=r.get('center', {})
            )
        return rooms

    def _parse_roofs(self) -> List[Roof]:
        roofs = []
        for r in self.data.get('roofs', []):
            roofs.append(Roof(
                id=r.get('id', 'roof_1'),
                roof_type=r.get('type', 'gable'),
                pitch=r.get('pitch', 4),
                overhang=r.get('overhang', 600),
                ridges=r.get('ridges', []),
                surfaces=r.get('surfaces', []),
                skylights=r.get('skylights', []),
                dormers=r.get('dormers', [])
            ))
        return roofs

    def _get_wall_geometry(self, wall: Wall) -> Dict:
        """Get wall start/end points and direction."""
        sx, sy, sz = wall.start
        ex, ey, ez = wall.end

        # Wall runs along X (horizontal) or Z (vertical in plan)
        dx = ex - sx
        dz = ez - sz
        length = math.sqrt(dx*dx + dz*dz)

        return {
            'start_x': sx,
            'start_z': sz,
            'end_x': ex,
            'end_z': ez,
            'length': length,
            'is_horizontal': abs(dz) < 1,  # Runs along X
            'is_vertical': abs(dx) < 1,    # Runs along Z
        }

    def _get_opening_position(self, wall: Wall, offset: float, width: float) -> Tuple[float, float, float, float, float]:
        """Get opening position on wall (works for diagonal walls).

        Returns: (center_x, center_z, dx, dz, angle) where dx/dz are direction vectors
        """
        geom = self._get_wall_geometry(wall)
        sx, sz = geom['start_x'], geom['start_z']
        ex, ez = geom['end_x'], geom['end_z']
        length = geom['length']

        if length < 1:
            return (sx, sz, 1, 0, 0)

        # Direction along wall
        dx = (ex - sx) / length
        dz = (ez - sz) / length

        # Position along wall at offset
        center_x = sx + dx * offset
        center_z = sz + dz * offset

        # Angle for rotation
        angle = math.degrees(math.atan2(dz, dx))

        return (center_x, center_z, dx, dz, angle)

    def generate_floor_plan_svg(self, scale: float = 0.1) -> str:
        """Generate floor plan SVG with proper annotations."""

        # Margins for dimensions
        margin = 4000

        # Viewbox
        vb_x = -margin
        vb_y = -margin
        vb_w = self.width + 2 * margin
        vb_h = self.depth + 2 * margin

        svg = []
        svg.append(f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg"
     width="{int(vb_w * scale)}" height="{int(vb_h * scale)}"
     viewBox="{vb_x} {vb_y} {vb_w} {vb_h}">
<defs>
<style>
.wall-ext {{ fill: #333; stroke: #000; stroke-width: 2; }}
.wall-int {{ fill: #666; stroke: #000; stroke-width: 1; }}
.wall-wet {{ fill: #5588cc; stroke: #3366aa; stroke-width: 1; }}
.opening {{ fill: white; stroke: none; }}
.door-leaf {{ stroke: #000; stroke-width: 4; fill: none; }}
.door-swing {{ stroke: #000; stroke-width: 2; fill: none; }}
.window {{ fill: white; stroke: #000; stroke-width: 4; }}
.window-glass {{ stroke: #000; stroke-width: 2; }}
.grid-line {{ stroke: #ccc; stroke-width: 2; stroke-dasharray: 60,30; }}
.grid-bubble {{ fill: white; stroke: #000; stroke-width: 4; }}
.grid-label {{ font: bold {self.grid_label_size}px Arial; text-anchor: middle; dominant-baseline: central; }}
.room-label {{ font: 500 {self.room_text_size}px Arial; text-anchor: middle; }}
.room-area {{ font: {self.room_area_size}px Arial; text-anchor: middle; fill: #555; }}
.dim-line {{ stroke: #000; stroke-width: 3; }}
.dim-ext {{ stroke: #000; stroke-width: 2; }}
.dim-text {{ font: bold {self.dim_text_size}px Arial; text-anchor: middle; }}
/* Tier-specific dimension styling */
.tier-1 {{ stroke: #000; stroke-width: 4; }} /* Overall - thicker */
.tier-1.dim-text {{ font: bold {self.dim_text_size}px Arial; fill: #000; }}
.tier-2 {{ stroke: #333; stroke-width: 3; }} /* Structural */
.tier-2.dim-text {{ font: bold {self.dim_text_size}px Arial; fill: #333; }}
.tier-3 {{ stroke: #666; stroke-width: 2; }} /* Opening */
.tier-3.dim-text {{ font: bold {self.dim_text_size}px Arial; fill: #666; }}
.tier-4 {{ stroke: #999; stroke-width: 2; }} /* Interior */
.tier-4.dim-text {{ font: bold {self.dim_text_size}px Arial; fill: #999; }}
.title {{ font: bold {self.title_text_size}px Arial; }}
/* LOD visibility control - hidden by viewer based on zoom */
.lod-hide {{ opacity: 0; pointer-events: none; }}
</style>
</defs>
<rect x="{vb_x}" y="{vb_y}" width="{vb_w}" height="{vb_h}" fill="white"/>
''')

        # === LOD 0: Basic geometry (walls, structure) ===
        svg.append('<g id="lod-0" data-lod="0">')
        svg.append(self._generate_walls())
        svg.append(self._generate_openings())
        svg.append('</g>')

        # === LOD 1: Doors, windows, room names, navigation ===
        svg.append('<g id="lod-1" data-lod="1">')
        svg.append(self._generate_door_symbols())
        svg.append(self._generate_window_symbols())
        svg.append(self._generate_room_labels(names_only=True))
        # Grid lines (only for commercial/non-residential)
        if not self.is_residential:
            svg.append(self._generate_grid_lines())
        svg.append(self._generate_north_arrow(-margin + 800, 1500))
        # Title
        svg.append(f'<text x="{self.width/2}" y="{-margin + 400}" class="title" text-anchor="middle">FLOOR PLAN - LEVEL 1</text>')
        # Title block
        project_info = get_project_info_from_json(self.data)
        drawing_info = get_drawing_info('floor_plan', '1:100')
        svg.append(generate_title_block(self.width, self.depth, project_info, drawing_info, scale, margin))
        svg.append('</g>')

        # === LOD 2: Dimensions, areas, scale ===
        svg.append('<g id="lod-2" data-lod="2">')
        svg.append(self._generate_room_labels(areas_only=True))
        # Use intelligent dimensioning if available
        if _INTELLIGENT_DIM_AVAILABLE:
            svg.append(self._generate_intelligent_dimensions())
        else:
            svg.append(self._generate_ladder_dimensions())
        svg.append(self._generate_scale_bar(-margin + 500, self.depth - 500))
        svg.append('</g>')

        # === LOD 3: Notes, detail callouts (future) ===
        svg.append('<g id="lod-3" data-lod="3">')
        svg.append('<!-- Notes and detail callouts go here -->')
        svg.append('</g>')

        svg.append('</svg>')
        return '\n'.join(svg)

    def generate_roof_plan_svg(self, scale: float = 0.1) -> str:
        """Generate roof plan SVG with annotations."""

        # Get roof info (use first roof or generate default gable)
        if self.roofs:
            roof = self.roofs[0]
            overhang = roof.overhang
            pitch = roof.pitch
            roof_type = roof.roof_type
        else:
            overhang = self.default_overhang
            pitch = self.default_pitch
            roof_type = 'gable'

        # Roof extends beyond building by overhang
        roof_width = self.width + 2 * overhang
        roof_depth = self.depth + 2 * overhang

        # Margins for dimensions and annotations
        margin = 4000

        # Viewbox
        vb_x = -overhang - margin
        vb_y = -overhang - margin
        vb_w = roof_width + 2 * margin
        vb_h = roof_depth + 2 * margin

        svg = []
        svg.append(f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg"
     width="{int(vb_w * scale)}" height="{int(vb_h * scale)}"
     viewBox="{vb_x} {vb_y} {vb_w} {vb_h}">
<defs>
<marker id="arrow-drain" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
  <polygon points="0 0, 10 3.5, 0 7" fill="#2196F3"/>
</marker>
<style>
.roof-outline {{ fill: #f5f5f5; stroke: #333; stroke-width: 6; }}
.building-outline {{ fill: none; stroke: #999; stroke-width: 2; stroke-dasharray: 30,15; }}
.ridge {{ stroke: #000; stroke-width: 8; stroke-linecap: round; }}
.hip {{ stroke: #000; stroke-width: 5; stroke-dasharray: 50,25; }}
.valley {{ stroke: #000; stroke-width: 5; stroke-dasharray: 25,12; }}
.eave {{ stroke: #555; stroke-width: 4; }}
.rake {{ stroke: #555; stroke-width: 4; stroke-dasharray: 40,20; }}
.drainage {{ stroke: #2196F3; stroke-width: 4; }}
.gutter {{ stroke: #795548; stroke-width: 10; stroke-linecap: round; }}
.downspout {{ fill: #795548; stroke: #5D4037; stroke-width: 2; }}
.skylight {{ fill: none; stroke: #00BCD4; stroke-width: 6; }}
.skylight-x {{ stroke: #00BCD4; stroke-width: 2; }}
.grid-line {{ stroke: #ddd; stroke-width: 2; stroke-dasharray: 60,30; }}
.grid-bubble {{ fill: white; stroke: #000; stroke-width: 4; }}
.grid-label {{ font: bold {self.grid_label_size}px Arial; text-anchor: middle; dominant-baseline: central; }}
.title {{ font: bold {self.title_text_size}px Arial; }}
.subtitle {{ font: {self.room_area_size}px Arial; fill: #666; }}
.pitch-label {{ font: bold {self.dim_text_size}px Arial; }}
.annotation {{ font: {self.room_area_size}px Arial; }}
.dim-line {{ stroke: #000; stroke-width: 3; }}
.dim-ext {{ stroke: #000; stroke-width: 2; }}
.dim-text {{ font: bold {self.dim_text_size}px Arial; text-anchor: middle; }}
.legend-text {{ font: {self.dim_text_size}px Arial; }}
.legend-title {{ font: bold {self.room_text_size}px Arial; }}
/* LOD visibility control - hidden by viewer based on zoom */
.lod-hide {{ opacity: 0; pointer-events: none; }}
</style>
</defs>
<rect x="{vb_x}" y="{vb_y}" width="{vb_w}" height="{vb_h}" fill="white"/>
''')

        # === LOD 0: Basic geometry (roof outline, building outline) ===
        svg.append('<g id="lod-0" data-lod="0">')
        svg.append(f'''<!-- Roof Outline -->
<rect x="{-overhang}" y="{-overhang}" width="{roof_width}" height="{roof_depth}" class="roof-outline"/>''')
        svg.append(f'''<!-- Building Outline -->
<rect x="0" y="0" width="{self.width}" height="{self.depth}" class="building-outline"/>''')
        # Roof elements based on type
        if roof_type == 'gable':
            svg.append(self._generate_gable_roof(overhang, pitch))
        elif roof_type == 'hip':
            svg.append(self._generate_hip_roof(overhang, pitch))
        else:
            svg.append(self._generate_gable_roof(overhang, pitch))
        svg.append('</g>')

        # === LOD 1: Features, navigation, titles ===
        svg.append('<g id="lod-1" data-lod="1">')
        svg.append(self._generate_skylights())
        svg.append(self._generate_gutters(overhang))
        # Grid lines (only for commercial/non-residential)
        if not self.is_residential:
            svg.append(self._generate_roof_grid_lines())
        svg.append(self._generate_north_arrow(self.width + overhang + margin - 1000, 1500))
        # Title
        svg.append(f'<text x="{self.width/2}" y="{-overhang - margin + 500}" class="title" text-anchor="middle">ROOF PLAN</text>')
        svg.append(f'<text x="{self.width/2}" y="{-overhang - margin + 900}" class="subtitle" text-anchor="middle">Scale: 1:100 | {roof_type.title()} Roof - {pitch}:12 Pitch</text>')
        # Title block
        project_info = get_project_info_from_json(self.data)
        drawing_info = get_drawing_info('roof_plan', '1:100')
        svg.append(generate_title_block(roof_width, roof_depth, project_info, drawing_info, scale, margin))
        svg.append('</g>')

        # === LOD 2: Dimensions, areas, scale ===
        svg.append('<g id="lod-2" data-lod="2">')
        svg.append(self._generate_roof_dimensions(overhang))
        svg.append(self._generate_roof_areas(overhang, pitch))
        svg.append(self._generate_scale_bar(self.width/2 - 1000, self.depth + overhang + 2500))
        svg.append('</g>')

        # === LOD 3: Legend, notes, details ===
        svg.append('<g id="lod-3" data-lod="3">')
        svg.append(self._generate_roof_legend(-overhang - margin + 500, self.depth + overhang + 800))
        svg.append('</g>')

        svg.append('</svg>')
        return '\n'.join(svg)

    def _generate_roof_grid_lines(self) -> str:
        """Generate grid lines for roof plan."""
        lines = ['<!-- Grid Lines -->']

        x_grids = sorted(set([0, self.width]))
        z_grids = sorted(set([0, self.depth]))

        # Add interior wall positions for grid
        for wall in self.walls:
            geom = self._get_wall_geometry(wall)
            if geom['is_vertical'] and wall.category == 'interior':
                x_grids.append(geom['start_x'])
            if geom['is_horizontal'] and wall.category == 'interior':
                z_grids.append(geom['start_z'])

        x_grids = sorted(set(x_grids))
        z_grids = sorted(set(z_grids))

        # Vertical grid lines
        for i, x in enumerate(x_grids):
            label = chr(65 + i)
            lines.append(f'<line x1="{x}" y1="-2500" x2="{x}" y2="{self.depth + 1500}" class="grid-line"/>')
            lines.append(f'<circle cx="{x}" cy="-3000" r="280" class="grid-bubble"/>')
            lines.append(f'<text x="{x}" y="-3000" class="grid-label">{label}</text>')

        # Horizontal grid lines
        for i, z in enumerate(z_grids):
            label = str(i + 1)
            lines.append(f'<line x1="-2500" y1="{z}" x2="{self.width + 1500}" y2="{z}" class="grid-line"/>')
            lines.append(f'<circle cx="-3000" cy="{z}" r="280" class="grid-bubble"/>')
            lines.append(f'<text x="-3000" y="{z}" class="grid-label">{label}</text>')

        return '\n'.join(lines)

    def _generate_gable_roof(self, overhang: float, pitch: float) -> str:
        """Generate gable roof elements (ridge runs E-W, gable ends on E and W)."""
        elements = ['<!-- Gable Roof Elements -->']

        # Ridge line (center of building, running along X axis)
        ridge_y = self.depth / 2
        elements.append(f'<line x1="{-overhang}" y1="{ridge_y}" x2="{self.width + overhang}" y2="{ridge_y}" class="ridge"/>')

        # Eave lines (north and south)
        elements.append(f'<line x1="{-overhang}" y1="{-overhang}" x2="{self.width + overhang}" y2="{-overhang}" class="eave"/>')
        elements.append(f'<line x1="{-overhang}" y1="{self.depth + overhang}" x2="{self.width + overhang}" y2="{self.depth + overhang}" class="eave"/>')

        # Rake lines (gable ends - east and west)
        elements.append(f'<line x1="{-overhang}" y1="{-overhang}" x2="{-overhang}" y2="{self.depth + overhang}" class="rake"/>')
        elements.append(f'<line x1="{self.width + overhang}" y1="{-overhang}" x2="{self.width + overhang}" y2="{self.depth + overhang}" class="rake"/>')

        # Drainage arrows - North slope (draining toward north eave)
        num_arrows = 3
        for i in range(num_arrows):
            x = (i + 1) * self.width / (num_arrows + 1)
            # Arrow from ridge toward north eave
            elements.append(f'<line x1="{x}" y1="{ridge_y - 500}" x2="{x}" y2="{-overhang + 300}" class="drainage" marker-end="url(#arrow-drain)"/>')

        # Drainage arrows - South slope (draining toward south eave)
        for i in range(num_arrows):
            x = (i + 1) * self.width / (num_arrows + 1)
            # Arrow from ridge toward south eave
            elements.append(f'<line x1="{x}" y1="{ridge_y + 500}" x2="{x}" y2="{self.depth + overhang - 300}" class="drainage" marker-end="url(#arrow-drain)"/>')

        # Pitch indicators
        # North slope
        elements.append(self._pitch_indicator(1500, ridge_y/2 - 200, pitch, 'north'))
        # South slope
        elements.append(self._pitch_indicator(self.width - 2500, ridge_y + ridge_y/2, pitch, 'south'))

        return '\n'.join(elements)

    def _generate_hip_roof(self, overhang: float, pitch: float) -> str:
        """Generate hip roof elements."""
        elements = ['<!-- Hip Roof Elements -->']

        # Ridge line (shorter than building, centered)
        ridge_y = self.depth / 2
        hip_inset = self.depth / 2  # Hip comes in from each end
        ridge_start_x = hip_inset
        ridge_end_x = self.width - hip_inset

        # Main ridge
        elements.append(f'<line x1="{ridge_start_x}" y1="{ridge_y}" x2="{ridge_end_x}" y2="{ridge_y}" class="ridge"/>')

        # Hip lines (from corners to ridge ends)
        # Northwest hip
        elements.append(f'<line x1="{-overhang}" y1="{-overhang}" x2="{ridge_start_x}" y2="{ridge_y}" class="hip"/>')
        # Southwest hip
        elements.append(f'<line x1="{-overhang}" y1="{self.depth + overhang}" x2="{ridge_start_x}" y2="{ridge_y}" class="hip"/>')
        # Northeast hip
        elements.append(f'<line x1="{self.width + overhang}" y1="{-overhang}" x2="{ridge_end_x}" y2="{ridge_y}" class="hip"/>')
        # Southeast hip
        elements.append(f'<line x1="{self.width + overhang}" y1="{self.depth + overhang}" x2="{ridge_end_x}" y2="{ridge_y}" class="hip"/>')

        # Eave lines (all four sides)
        elements.append(f'<line x1="{-overhang}" y1="{-overhang}" x2="{self.width + overhang}" y2="{-overhang}" class="eave"/>')
        elements.append(f'<line x1="{-overhang}" y1="{self.depth + overhang}" x2="{self.width + overhang}" y2="{self.depth + overhang}" class="eave"/>')
        elements.append(f'<line x1="{-overhang}" y1="{-overhang}" x2="{-overhang}" y2="{self.depth + overhang}" class="eave"/>')
        elements.append(f'<line x1="{self.width + overhang}" y1="{-overhang}" x2="{self.width + overhang}" y2="{self.depth + overhang}" class="eave"/>')

        # Drainage arrows for hip roof (4 directions)
        mid_x = self.width / 2
        elements.append(f'<line x1="{mid_x}" y1="{ridge_y - 400}" x2="{mid_x}" y2="{-overhang + 300}" class="drainage" marker-end="url(#arrow-drain)"/>')
        elements.append(f'<line x1="{mid_x}" y1="{ridge_y + 400}" x2="{mid_x}" y2="{self.depth + overhang - 300}" class="drainage" marker-end="url(#arrow-drain)"/>')
        elements.append(f'<line x1="{ridge_start_x - 400}" y1="{ridge_y}" x2="{-overhang + 300}" y2="{ridge_y}" class="drainage" marker-end="url(#arrow-drain)"/>')
        elements.append(f'<line x1="{ridge_end_x + 400}" y1="{ridge_y}" x2="{self.width + overhang - 300}" y2="{ridge_y}" class="drainage" marker-end="url(#arrow-drain)"/>')

        # Pitch indicator
        elements.append(self._pitch_indicator(mid_x - 500, ridge_y/2, pitch, 'north'))

        return '\n'.join(elements)

    def _pitch_indicator(self, x: float, y: float, pitch: float, direction: str) -> str:
        """Generate a pitch indicator triangle with label."""
        # Triangle showing rise/run ratio
        run = 600
        rise = run * pitch / 12

        if direction == 'north':
            # Triangle pointing up (north slope drains north)
            return f'''<g transform="translate({x}, {y})">
  <path d="M 0 {rise} L {run} {rise} L {run} 0 Z" fill="none" stroke="black" stroke-width="4"/>
  <text x="{run/2}" y="{rise + 300}" class="pitch-label" text-anchor="middle">{pitch}:12</text>
</g>'''
        else:
            # Triangle pointing down (south slope drains south)
            return f'''<g transform="translate({x}, {y})">
  <path d="M 0 0 L {run} 0 L {run} {rise} Z" fill="none" stroke="black" stroke-width="4"/>
  <text x="{run/2}" y="{rise + 300}" class="pitch-label" text-anchor="middle">{pitch}:12</text>
</g>'''

    def _generate_skylights(self) -> str:
        """Generate skylight symbols."""
        skylights_svg = ['<!-- Skylights -->']

        # Check for skylights in roof data
        if self.roofs and self.roofs[0].skylights:
            for skylight in self.roofs[0].skylights:
                pos = skylight.get('position', [0, 0, 0])
                w = skylight.get('width', 1000)
                h = skylight.get('height', 800)
                x = pos[0] - w/2
                y = pos[2] - h/2  # Use Z for plan view

                skylights_svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" class="skylight"/>')
                skylights_svg.append(f'<line x1="{x}" y1="{y}" x2="{x+w}" y2="{y+h}" class="skylight-x"/>')
                skylights_svg.append(f'<line x1="{x+w}" y1="{y}" x2="{x}" y2="{y+h}" class="skylight-x"/>')
                skylights_svg.append(f'<text x="{pos[0]}" y="{pos[2] + h/2 + 250}" class="annotation" text-anchor="middle">SKYLIGHT</text>')
                skylights_svg.append(f'<text x="{pos[0]}" y="{pos[2] + h/2 + 450}" class="annotation" text-anchor="middle">{int(w)} x {int(h)}</text>')
        else:
            # Add a sample skylight for demonstration
            # Place it on the south slope, offset from center
            sky_x = self.width * 0.65
            sky_y = self.depth * 0.65
            sky_w = 1200
            sky_h = 900

            skylights_svg.append(f'<rect x="{sky_x - sky_w/2}" y="{sky_y - sky_h/2}" width="{sky_w}" height="{sky_h}" class="skylight"/>')
            skylights_svg.append(f'<line x1="{sky_x - sky_w/2}" y1="{sky_y - sky_h/2}" x2="{sky_x + sky_w/2}" y2="{sky_y + sky_h/2}" class="skylight-x"/>')
            skylights_svg.append(f'<line x1="{sky_x + sky_w/2}" y1="{sky_y - sky_h/2}" x2="{sky_x - sky_w/2}" y2="{sky_y + sky_h/2}" class="skylight-x"/>')
            skylights_svg.append(f'<text x="{sky_x}" y="{sky_y + sky_h/2 + 300}" class="annotation" text-anchor="middle">SKYLIGHT</text>')
            skylights_svg.append(f'<text x="{sky_x}" y="{sky_y + sky_h/2 + 500}" class="annotation" text-anchor="middle">{sky_w} x {sky_h}</text>')

        return '\n'.join(skylights_svg)

    def _generate_gutters(self, overhang: float) -> str:
        """Generate gutters and downspouts."""
        gutters = ['<!-- Gutters and Downspouts -->']

        # Gutters along eaves (north and south for gable)
        gutters.append(f'<line x1="{-overhang}" y1="{-overhang}" x2="{self.width + overhang}" y2="{-overhang}" class="gutter"/>')
        gutters.append(f'<line x1="{-overhang}" y1="{self.depth + overhang}" x2="{self.width + overhang}" y2="{self.depth + overhang}" class="gutter"/>')

        # Downspouts at corners
        ds_positions = [
            (-overhang + 200, -overhang),
            (self.width + overhang - 200, -overhang),
            (-overhang + 200, self.depth + overhang),
            (self.width + overhang - 200, self.depth + overhang)
        ]

        for x, y in ds_positions:
            gutters.append(f'<circle cx="{x}" cy="{y}" r="100" class="downspout"/>')
            # DS label
            label_y = y - 300 if y < self.depth/2 else y + 350
            gutters.append(f'<text x="{x}" y="{label_y}" class="annotation" text-anchor="middle">DS</text>')

        return '\n'.join(gutters)

    def _generate_roof_dimensions(self, overhang: float) -> str:
        """Generate roof dimensions."""
        dims = ['<!-- Roof Dimensions -->']

        roof_width = self.width + 2 * overhang
        roof_depth = self.depth + 2 * overhang

        # Overall width with overhang (top)
        dims.append(self._dim_line(-overhang, -overhang - 800, self.width + overhang, -overhang - 800, roof_width))
        dims.append(f'<text x="{self.width/2}" y="{-overhang - 1100}" class="annotation" text-anchor="middle">(incl. {int(overhang)}mm overhang)</text>')

        # Overall depth with overhang (right side)
        dims.append(self._dim_line_v(self.width + overhang + 800, -overhang, self.depth + overhang, roof_depth))

        # Building width (interior dimension line)
        dims.append(self._dim_line(0, -overhang - 1600, self.width, -overhang - 1600, self.width))

        return '\n'.join(dims)

    def _generate_roof_legend(self, x: float, y: float) -> str:
        """Generate roof plan legend."""
        return f'''<!-- Legend -->
<g transform="translate({x}, {y})">
  <text x="0" y="0" class="legend-title">LEGEND:</text>

  <line x1="0" y1="350" x2="400" y2="350" class="ridge"/>
  <text x="500" y="380" class="legend-text">Ridge</text>

  <line x1="0" y1="550" x2="400" y2="550" class="eave"/>
  <text x="500" y="580" class="legend-text">Eave</text>

  <line x1="0" y1="750" x2="400" y2="750" class="rake"/>
  <text x="500" y="780" class="legend-text">Rake</text>

  <line x1="0" y1="950" x2="400" y2="950" class="hip"/>
  <text x="500" y="980" class="legend-text">Hip/Valley</text>

  <line x1="0" y1="1150" x2="400" y2="1150" class="gutter"/>
  <text x="500" y="1180" class="legend-text">Gutter</text>

  <line x1="0" y1="1350" x2="400" y2="1350" class="drainage" marker-end="url(#arrow-drain)"/>
  <text x="500" y="1380" class="legend-text">Drainage</text>

  <circle cx="80" cy="1550" r="80" class="downspout"/>
  <text x="500" y="1580" class="legend-text">Downspout</text>
</g>'''

    def _generate_roof_areas(self, overhang: float, pitch: float) -> str:
        """Generate roof area calculations."""
        # Calculate actual roof area (accounting for slope)
        # Slope factor = sqrt(1 + (pitch/12)^2)
        slope_factor = math.sqrt(1 + (pitch/12)**2)

        # Plan area of each slope
        plan_area_per_slope = (self.width + 2*overhang) * (self.depth/2 + overhang) / 1_000_000  # m²
        actual_area_per_slope = plan_area_per_slope * slope_factor
        total_area = actual_area_per_slope * 2

        x = self.width/2 + 1500
        y = self.depth + overhang + 800

        return f'''<!-- Roof Areas -->
<g transform="translate({x}, {y})">
  <text x="0" y="0" class="legend-title">ROOF AREAS:</text>
  <text x="0" y="350" class="annotation">North Slope: {actual_area_per_slope:.1f} m&#178; ({pitch}:12 pitch)</text>
  <text x="0" y="550" class="annotation">South Slope: {actual_area_per_slope:.1f} m&#178; ({pitch}:12 pitch)</text>
  <text x="0" y="750" class="annotation">Total Roof Area: {total_area:.1f} m&#178;</text>
  <text x="0" y="950" class="annotation">Slope Factor: {slope_factor:.3f}</text>
</g>'''

    def _generate_grid_lines(self) -> str:
        """Generate structural grid with bubbles."""
        lines = ['<!-- Grid Lines -->']

        # Determine grid positions based on walls
        x_grids = sorted(set([0, self.width]))
        z_grids = sorted(set([0, self.depth]))

        # Add interior wall positions
        for wall in self.walls:
            geom = self._get_wall_geometry(wall)
            if geom['is_vertical'] and wall.category == 'interior':
                x_grids.append(geom['start_x'])
            if geom['is_horizontal'] and wall.category == 'interior':
                z_grids.append(geom['start_z'])

        x_grids = sorted(set(x_grids))
        z_grids = sorted(set(z_grids))

        # Vertical grid lines (letters A, B, C...)
        for i, x in enumerate(x_grids):
            label = chr(65 + i)  # A, B, C...
            lines.append(f'<line x1="{x}" y1="-2000" x2="{x}" y2="{self.depth + 1000}" class="grid-line"/>')
            # Top bubble
            lines.append(f'<circle cx="{x}" cy="-2500" r="280" class="grid-bubble"/>')
            lines.append(f'<text x="{x}" y="-2500" class="grid-label">{label}</text>')

        # Horizontal grid lines (numbers 1, 2, 3...)
        for i, z in enumerate(z_grids):
            label = str(i + 1)
            lines.append(f'<line x1="-2000" y1="{z}" x2="{self.width + 1000}" y2="{z}" class="grid-line"/>')
            # Left bubble
            lines.append(f'<circle cx="-2500" cy="{z}" r="280" class="grid-bubble"/>')
            lines.append(f'<text x="-2500" y="{z}" class="grid-label">{label}</text>')

        return '\n'.join(lines)

    def _generate_walls(self) -> str:
        """Generate walls as polygons to properly handle diagonal walls."""
        walls_svg = ['<!-- Walls -->']

        for wall in self.walls:
            geom = self._get_wall_geometry(wall)
            thickness = self.ext_wall_thickness if wall.category == 'exterior' else self.int_wall_thickness

            css_class = 'wall-ext'
            if wall.category == 'interior':
                css_class = 'wall-int'
            elif wall.category == 'wet_wall':
                css_class = 'wall-wet'

            # Calculate wall polygon points (rectangle with thickness along the wall)
            sx, sz = geom['start_x'], geom['start_z']
            ex, ez = geom['end_x'], geom['end_z']

            # Get perpendicular offset for wall thickness
            length = geom['length']
            if length < 1:
                continue  # Skip zero-length walls

            # Direction vector
            dx = (ex - sx) / length
            dz = (ez - sz) / length

            # Perpendicular vector (rotated 90 degrees)
            px = -dz * thickness / 2
            pz = dx * thickness / 2

            # Four corners of the wall polygon
            p1 = (sx + px, sz + pz)
            p2 = (sx - px, sz - pz)
            p3 = (ex - px, ez - pz)
            p4 = (ex + px, ez + pz)

            # Draw as polygon path
            points = f"{p1[0]},{p1[1]} {p2[0]},{p2[1]} {p3[0]},{p3[1]} {p4[0]},{p4[1]}"
            walls_svg.append(f'<polygon points="{points}" class="{css_class}"/>')

        return '\n'.join(walls_svg)

    def _generate_openings(self) -> str:
        """Generate white polygons to cut openings in walls (works for diagonal walls)."""
        openings = ['<!-- Openings -->']

        # Door openings
        for door in self.doors:
            if door.wall_index < len(self.walls):
                wall = self.walls[door.wall_index]
                thickness = self.ext_wall_thickness if wall.category == 'exterior' else self.int_wall_thickness
                cx, cz, dx, dz, angle = self._get_opening_position(wall, door.offset, door.width)

                # Perpendicular direction
                px, pz = -dz, dx

                # Half dimensions
                hw = door.width / 2
                ht = thickness / 2 + 50  # Extra margin

                # Four corners of opening
                p1 = (cx - dx*hw + px*ht, cz - dz*hw + pz*ht)
                p2 = (cx - dx*hw - px*ht, cz - dz*hw - pz*ht)
                p3 = (cx + dx*hw - px*ht, cz + dz*hw - pz*ht)
                p4 = (cx + dx*hw + px*ht, cz + dz*hw + pz*ht)

                points = f"{p1[0]},{p1[1]} {p2[0]},{p2[1]} {p3[0]},{p3[1]} {p4[0]},{p4[1]}"
                openings.append(f'<polygon points="{points}" class="opening"/>')

        return '\n'.join(openings)

    def _generate_door_symbols(self) -> str:
        """Generate door symbols with swing arcs (works for diagonal walls).

        Uses transform groups to rotate door symbols for diagonal walls.
        """
        doors_svg = ['<!-- Door Symbols -->']

        for door in self.doors:
            if door.wall_index >= len(self.walls):
                continue

            wall = self.walls[door.wall_index]
            cx, cz, dx, dz, angle = self._get_opening_position(wall, door.offset, door.width)

            # Determine hinge side and swing direction
            hinge_left = 'left' in door.swing
            swing_in = 'in' in door.swing or door.swing == 'left'

            # Door width
            w = door.width
            hw = w / 2

            # In local coordinates (before rotation):
            # - Door opening is from -hw to +hw along X
            # - Swing is in +Y direction (or -Y if swing_out)

            if hinge_left:
                hinge_x = -hw
                leaf_end_x = hw
            else:
                hinge_x = hw
                leaf_end_x = -hw

            swing_y = w if swing_in else -w

            # Build door symbol in local coordinates
            # Door leaf (line from hinge perpendicular to wall)
            leaf_line = f'<line x1="{hinge_x}" y1="0" x2="{hinge_x}" y2="{swing_y}" class="door-leaf"/>'

            # Swing arc
            if hinge_left:
                sweep = "1" if swing_in else "0"
            else:
                sweep = "0" if swing_in else "1"

            arc = f'<path d="M {leaf_end_x},0 A {w},{w} 0 0 {sweep} {hinge_x},{swing_y}" class="door-swing"/>'

            # Pocket/sliding door (dashed line)
            if door.door_type in ('pocket', 'sliding'):
                pocket = f'<line x1="{-hw}" y1="0" x2="{hw}" y2="0" stroke="#000" stroke-width="3" stroke-dasharray="40,20"/>'
                doors_svg.append(f'<g transform="translate({cx},{cz}) rotate({angle})">{pocket}</g>')
            else:
                doors_svg.append(f'<g transform="translate({cx},{cz}) rotate({angle})">{leaf_line}{arc}</g>')

        return '\n'.join(doors_svg)

    def _generate_window_symbols(self) -> str:
        """Generate window symbols (works for diagonal walls)."""
        windows_svg = ['<!-- Window Symbols -->']

        for window in self.windows:
            if window.wall_index >= len(self.walls):
                continue

            wall = self.walls[window.wall_index]
            thickness = self.ext_wall_thickness if wall.category == 'exterior' else self.int_wall_thickness
            cx, cz, dx, dz, angle = self._get_opening_position(wall, window.offset, window.width)

            # Window dimensions
            w = window.width
            hw = w / 2
            ht = thickness / 2

            # Build window in local coordinates then rotate
            # Rectangle for window frame
            rect = f'<rect x="{-hw}" y="{-ht}" width="{w}" height="{thickness}" class="window"/>'
            # Center glass line
            glass = f'<line x1="{-hw}" y1="0" x2="{hw}" y2="0" class="window-glass"/>'

            windows_svg.append(f'<g transform="translate({cx},{cz}) rotate({angle})">{rect}{glass}</g>')

        return '\n'.join(windows_svg)

    def _generate_room_labels(self, names_only: bool = False, areas_only: bool = False) -> str:
        """Generate room labels with areas.

        Room centers use x and z coordinates (plan view coordinates).
        In the JSON, 'center' may have 'x', 'y' (height), and 'z' keys,
        or it may use 'x' and 'y' for plan coordinates. We try both.

        Args:
            names_only: If True, only render room names (for LOD 1)
            areas_only: If True, only render room areas (for LOD 2)
        """
        if names_only:
            labels = ['<!-- Room Names (LOD 1) -->']
        elif areas_only:
            labels = ['<!-- Room Areas (LOD 2) -->']
        else:
            labels = ['<!-- Room Labels -->']

        name_size = self.room_text_size
        area_size = self.room_area_size

        for room_id, room in self.rooms.items():
            if room.center:
                # Try to get center coordinates - handle both naming conventions
                cx = room.center.get('x', 0)
                # Use 'z' if available (3D convention), otherwise 'y' (2D plan convention)
                cz = room.center.get('z', room.center.get('y', 0))

                # Convert area from mm² to m²
                area_m2 = room.area / 1_000_000 if room.area > 10000 else room.area

                if not areas_only:
                    labels.append(f'<text x="{cx}" y="{cz - 200}" font-family="Arial" font-size="{name_size}" font-weight="500" text-anchor="middle" class="room-label">{room.name.upper()}</text>')
                if not names_only and area_m2 > 0:
                    labels.append(f'<text x="{cx}" y="{cz + 300}" font-family="Arial" font-size="{area_size}" text-anchor="middle" fill="#555" class="room-area">{area_m2:.1f} m&#178;</text>')

            elif room.bounds:
                # Calculate center from bounds
                bounds = room.bounds
                cx = bounds.get('x', 0) + bounds.get('width', 0) / 2
                cz = bounds.get('y', 0) + bounds.get('height', 0) / 2  # 'y' is Z in plan

                # Convert area from mm² to m²
                area_m2 = room.area / 1_000_000 if room.area > 10000 else room.area

                if not areas_only:
                    labels.append(f'<text x="{cx}" y="{cz - 200}" font-family="Arial" font-size="{name_size}" font-weight="500" text-anchor="middle" class="room-label">{room.name.upper()}</text>')
                if not names_only and area_m2 > 0:
                    labels.append(f'<text x="{cx}" y="{cz + 300}" font-family="Arial" font-size="{area_size}" text-anchor="middle" fill="#555" class="room-area">{area_m2:.1f} m&#178;</text>')

        return '\n'.join(labels)

    def _get_building_bounds(self) -> dict:
        """Calculate actual building bounds from exterior walls."""
        if not self.walls:
            return {'min_x': 0, 'max_x': self.width, 'min_z': 0, 'max_z': self.depth}

        ext_walls = [w for w in self.walls if w.category == 'exterior']
        if not ext_walls:
            ext_walls = self.walls

        min_x = min_z = float('inf')
        max_x = max_z = float('-inf')

        for wall in ext_walls:
            geom = self._get_wall_geometry(wall)
            min_x = min(min_x, geom['start_x'], geom['end_x'])
            max_x = max(max_x, geom['start_x'], geom['end_x'])
            min_z = min(min_z, geom['start_z'], geom['end_z'])
            max_z = max(max_z, geom['start_z'], geom['end_z'])

        return {'min_x': min_x, 'max_x': max_x, 'min_z': min_z, 'max_z': max_z}

    def _find_walls_on_edge(self, edge: str, bounds: dict, tolerance: float = 100) -> list:
        """Find walls along a specific edge of the building."""
        walls_on_edge = []
        for i, wall in enumerate(self.walls):
            if wall.category != 'exterior':
                continue
            geom = self._get_wall_geometry(wall)

            if edge == 'south' and abs(min(geom['start_z'], geom['end_z']) - bounds['min_z']) < tolerance:
                walls_on_edge.append((i, wall, geom))
            elif edge == 'north' and abs(max(geom['start_z'], geom['end_z']) - bounds['max_z']) < tolerance:
                walls_on_edge.append((i, wall, geom))
            elif edge == 'west' and abs(min(geom['start_x'], geom['end_x']) - bounds['min_x']) < tolerance:
                walls_on_edge.append((i, wall, geom))
            elif edge == 'east' and abs(max(geom['start_x'], geom['end_x']) - bounds['max_x']) < tolerance:
                walls_on_edge.append((i, wall, geom))

        return walls_on_edge

    def _get_break_points_on_edge(self, edge: str, bounds: dict) -> list:
        """Get dimension break points: corners and CENTER of openings."""
        tolerance = 200
        breaks = []

        # Start and end of edge (corners)
        if edge in ('south', 'north'):
            breaks.append(bounds['min_x'])
            breaks.append(bounds['max_x'])
        else:  # west, east
            breaks.append(bounds['min_z'])
            breaks.append(bounds['max_z'])

        # Find walls on this edge
        edge_walls = self._find_walls_on_edge(edge, bounds)
        edge_wall_indices = [i for i, w, g in edge_walls]

        # Add door CENTERS on edge walls
        for door in self.doors:
            if door.wall_index in edge_wall_indices:
                wall = self.walls[door.wall_index]
                geom = self._get_wall_geometry(wall)
                if edge in ('south', 'north'):
                    base = min(geom['start_x'], geom['end_x'])
                    breaks.append(base + door.offset)  # Center only
                else:
                    base = min(geom['start_z'], geom['end_z'])
                    breaks.append(base + door.offset)  # Center only

        # Add window CENTERS on edge walls
        for window in self.windows:
            if window.wall_index in edge_wall_indices:
                wall = self.walls[window.wall_index]
                geom = self._get_wall_geometry(wall)
                if edge in ('south', 'north'):
                    base = min(geom['start_x'], geom['end_x'])
                    breaks.append(base + window.offset)  # Center only
                else:
                    base = min(geom['start_z'], geom['end_z'])
                    breaks.append(base + window.offset)  # Center only

        return sorted(set(breaks))

    def _is_dimension_hidden(self, dim_id: str, overrides: List) -> bool:
        """Check if a dimension should be hidden based on overrides."""
        return any(
            o.get('target') == dim_id and o.get('type') == 'hide'
            for o in overrides
        )

    def _get_dimension_text_override(self, dim_id: str, overrides: List) -> Optional[str]:
        """Get text override for a dimension if one exists."""
        for o in overrides:
            if o.get('target') == dim_id and o.get('type') == 'text':
                return o.get('value')
        return None

    def _generate_intelligent_dimensions(self) -> str:
        """Generate three-tiered intelligent dimension chains.
        
        Uses room adjacency graph to create architecturally meaningful dimensions:
        - Tier 1: Overall building envelope
        - Tier 2: Structural grid (major room divisions)  
        - Tier 3: Interior partitions
        """
        from intelligent_dimensions import IntelligentDimensioning, DimTier
        
        # Prepare data for intelligent dimensioning
        rooms_data = []
        # self.rooms is a dict: {room_id: Room}
        for room_id, room in self.rooms.items():
            rooms_data.append({
                'id': room_id,
                'name': room.name,
                'room_type': room.room_type,
                'bounds': room.bounds
            })
        
        walls_data = []
        for i, wall in enumerate(self.walls):
            wall_entry = {
                'start': wall.start,
                'end': wall.end,
                'category': wall.category,
                'wall_type': wall.wall_type,
                'index': i,
                'openings': []
            }
            
            # Add doors on this wall
            for door in self.doors:
                if door.wall_index == i:
                    # Calculate door start/end positions
                    wall_dx = wall.end[0] - wall.start[0]
                    wall_dz = wall.end[2] - wall.start[2]
                    wall_len = (wall_dx**2 + wall_dz**2)**0.5
                    
                    if wall_len > 0:
                        # Door center position
                        door_center_x = wall.start[0] + (wall_dx / wall_len) * door.offset
                        door_center_z = wall.start[2] + (wall_dz / wall_len) * door.offset
                        
                        # Door start/end (perpendicular to wall direction)
                        half_width = door.width / 2
                        if abs(wall_dx) > abs(wall_dz):  # Horizontal wall
                            door_start = [door_center_x - half_width, 0, door_center_z]
                            door_end = [door_center_x + half_width, 0, door_center_z]
                        else:  # Vertical wall
                            door_start = [door_center_x, 0, door_center_z - half_width]
                            door_end = [door_center_x, 0, door_center_z + half_width]
                        
                        wall_entry['openings'].append({
                            'start': door_start,
                            'end': door_end,
                            'type': 'door',
                            'width': door.width
                        })
            
            # Add windows on this wall
            for window in self.windows:
                if window.wall_index == i:
                    wall_dx = wall.end[0] - wall.start[0]
                    wall_dz = wall.end[2] - wall.start[2]
                    wall_len = (wall_dx**2 + wall_dz**2)**0.5
                    
                    if wall_len > 0:
                        window_center_x = wall.start[0] + (wall_dx / wall_len) * window.offset
                        window_center_z = wall.start[2] + (wall_dz / wall_len) * window.offset
                        
                        half_width = window.width / 2
                        if abs(wall_dx) > abs(wall_dz):  # Horizontal wall
                            win_start = [window_center_x - half_width, 0, window_center_z]
                            win_end = [window_center_x + half_width, 0, window_center_z]
                        else:  # Vertical wall
                            win_start = [window_center_x, 0, window_center_z - half_width]
                            win_end = [window_center_x, 0, window_center_z + half_width]
                        
                        wall_entry['openings'].append({
                            'start': win_start,
                            'end': win_end,
                            'type': 'window',
                            'width': window.width
                        })
            
            walls_data.append(wall_entry)
        
        doors_data = []
        for door in self.doors:
            doors_data.append({
                'wall_index': door.wall_index,
                'offset': door.offset,
                'width': door.width
            })
        
        windows_data = []
        for window in self.windows:
            windows_data.append({
                'wall_index': window.wall_index,
                'offset': window.offset,
                'width': window.width
            })
        
        # Create SVG builder class
        class SVGBuilder:
            def __init__(self):
                self.elements = []
            
            def line(self, x1, y1, x2, y2, cls):
                self.elements.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" class="{cls}" />')
            
            def text(self, x, y, text, cls):
                self.elements.append(f'<text x="{x:.1f}" y="{y:.1f}" class="{cls}">{text}</text>')
            
            def to_string(self):
                return '\n'.join(self.elements)
        
        # Get bounds for dimension placement
        min_x = min(w.start[0] for w in self.walls) if self.walls else 0
        min_z = min(w.start[2] for w in self.walls) if self.walls else 0
        max_x = max(w.end[0] for w in self.walls) if self.walls else 10000
        max_z = max(w.end[2] for w in self.walls) if self.walls else 10000
        
        building_width = max_x - min_x
        building_depth = max_z - min_z
        
        # Use raw mm coordinates (same as walls)
        # The viewBox handles the scaling for display
        margin = 2500  # mm margin for dimensions
        base_offset = 1500  # Offset from building edge
        
        # Transform functions (just add margin offset, no scaling)
        def tx(x):
            return x
        def tz(z):
            return z
        
        # Format function
        def format_dim(length_mm):
            if length_mm >= 1000:
                meters = length_mm / 1000
                if meters == int(meters):
                    return f"{int(meters)} m"
                return f"{meters:.1f} m"
            return f"{int(length_mm)}"
        
        # Generate intelligent dimensions
        builder = SVGBuilder()
        
        dim = IntelligentDimensioning(rooms_data, walls_data)
        chains = dim.generate_chains()
        
        # Separate by orientation
        horizontal_chains = [c for c in chains if c.orientation == 'horizontal']
        vertical_chains = [c for c in chains if c.orientation == 'vertical']
        
        tier_spacing = 1200  # mm between tier lines
        
        # --- TOP DIMENSIONS (above building) ---
        # OVERALL and STRUCTURAL tiers go outside the building
        y_pos = min_z - base_offset
        
        for tier in [DimTier.OVERALL, DimTier.STRUCTURAL]:
            tier_chains = [c for c in horizontal_chains if c.tier == tier]
            if not tier_chains:
                y_pos -= tier_spacing
                continue
            
            all_segments = []
            for chain in tier_chains:
                all_segments.extend(chain.segments)
            
            if all_segments:
                all_x_vals = [s[0] for s in all_segments] + [s[1] for s in all_segments]
                line_min_x, line_max_x = min(all_x_vals), max(all_x_vals)
                tier_num = tier.value
                builder.line(tx(line_min_x), y_pos, tx(line_max_x), y_pos, f"dim-line tier-{tier_num}")

                # Extension line down to building edge
                ext_bottom = min_z - 100

                drawn_x = set()
                labeled_dims = set()
                for start, end, value_mm in all_segments:
                    for x in [start, end]:
                        x_key = round(x / 50)
                        if x_key not in drawn_x:
                            drawn_x.add(x_key)
                            builder.line(tx(x), y_pos, tx(x), ext_bottom, f"dim-ext tier-{tier_num}")

                    mid_x = (start + end) / 2
                    dim_key = (round(start/100), round(end/100))
                    if dim_key not in labeled_dims:
                        labeled_dims.add(dim_key)
                        if value_mm > 300 and (tier != DimTier.STRUCTURAL or value_mm > 1000):
                            builder.text(tx(mid_x), y_pos - 12, format_dim(value_mm), f"dim-text tier-{tier_num}")
            
            y_pos -= tier_spacing
        
        # --- OPENING DIMENSIONS (centered on doors/windows) ---
        # These are positioned right at the opening location
        opening_h_chains = [c for c in horizontal_chains if c.tier == DimTier.OPENING]
        for chain in opening_h_chains:
            for start, end, value_mm in chain.segments:
                # Short dimension line just outside the wall at opening location
                # Position it slightly above the building (y = min_z - 200)
                dim_y = min_z - 300
                builder.line(tx(start), dim_y, tx(end), dim_y, "dim-line tier-3")
                # Small ticks reaching to opening edges
                builder.line(tx(start), dim_y - 5, tx(start), dim_y + 5, "dim-ext tier-3")
                builder.line(tx(end), dim_y - 5, tx(end), dim_y + 5, "dim-ext tier-3")
                # Label centered on opening
                builder.text(tx((start + end) / 2), dim_y - 8, format_dim(value_mm), "dim-text tier-3")
        
        # --- INTERIOR DIMENSIONS (inside each room) ---
        interior_h_chains = [c for c in horizontal_chains if c.tier == DimTier.INTERIOR]
        for chain in interior_h_chains:
            # Use the stored y_pos (already positioned inside the room)
            y_pos = chain.y_pos if chain.y_pos > 0 else min_z + 1000  # Fallback

            for start, end, value_mm in chain.segments:
                # Short dimension line inside room
                builder.line(tx(start), y_pos, tx(end), y_pos, "dim-line tier-4")
                # Small ticks at ends
                builder.line(tx(start), y_pos - 5, tx(start), y_pos + 5, "dim-ext tier-4")
                builder.line(tx(end), y_pos - 5, tx(end), y_pos + 5, "dim-ext tier-4")
                # Label above
                if value_mm > 500:
                    builder.text(tx((start + end) / 2), y_pos - 8, format_dim(value_mm), "dim-text tier-4")
        
        # --- BOTTOM DIMENSIONS (below building) ---
        # OVERALL and STRUCTURAL tiers go outside
        y_pos = max_z + base_offset
        
        for tier in [DimTier.OVERALL, DimTier.STRUCTURAL]:
            tier_chains = [c for c in horizontal_chains if c.tier == tier]
            if not tier_chains:
                y_pos += tier_spacing
                continue
            
            all_segments = []
            for chain in tier_chains:
                all_segments.extend(chain.segments)
            
            if all_segments:
                all_x_vals = [s[0] for s in all_segments] + [s[1] for s in all_segments]
                line_min_x, line_max_x = min(all_x_vals), max(all_x_vals)
                builder.line(tx(line_min_x), y_pos, tx(line_max_x), y_pos, "dim-line")
                
                # Extension line up to building edge
                ext_top = max_z + 100
                
                drawn_x = set()
                labeled_dims = set()
                for start, end, value_mm in all_segments:
                    for x in [start, end]:
                        x_key = round(x / 50)
                        if x_key not in drawn_x:
                            drawn_x.add(x_key)
                            builder.line(tx(x), y_pos, tx(x), ext_top, "dim-ext")
                    
                    mid_x = (start + end) / 2
                    dim_key = (round(start/100), round(end/100))
                    if dim_key not in labeled_dims:
                        labeled_dims.add(dim_key)
                        if value_mm > 300 and (tier != DimTier.STRUCTURAL or value_mm > 1000):
                            builder.text(tx(mid_x), y_pos + 20, format_dim(value_mm), "dim-text")
            
            y_pos += tier_spacing
        
        # --- VERTICAL INTERIOR DIMENSIONS (inside each room) ---
        interior_v_chains = [c for c in vertical_chains if c.tier == DimTier.INTERIOR]
        for chain in interior_v_chains:
            # Use the stored y_pos (which is actually x_pos for vertical chains)
            x_pos = chain.y_pos if chain.y_pos > 0 else min_x + 1000
            
            for start, end, value_mm in chain.segments:
                # Short dimension line inside room
                builder.line(x_pos, tz(start), x_pos, tz(end), "dim-line")
                # Small ticks at ends
                builder.line(x_pos - 5, tz(start), x_pos + 5, tz(start), "dim-ext")
                builder.line(x_pos - 5, tz(end), x_pos + 5, tz(end), "dim-ext")
                # Label beside
                if value_mm > 500:
                    builder.text(x_pos - 8, tz((start + end) / 2), format_dim(value_mm), "dim-text")
        
        # --- VERTICAL OPENING DIMENSIONS (centered on doors/windows) ---
        opening_v_chains = [c for c in vertical_chains if c.tier == DimTier.OPENING]
        for chain in opening_v_chains:
            for start, end, value_mm in chain.segments:
                # Short dimension line just outside the wall at opening location
                dim_x = min_x - 300  # Left side of building
                builder.line(dim_x, tz(start), dim_x, tz(end), "dim-line")
                # Small ticks
                builder.line(dim_x - 5, tz(start), dim_x + 5, tz(start), "dim-ext")
                builder.line(dim_x - 5, tz(end), dim_x + 5, tz(end), "dim-ext")
                # Label centered on opening
                builder.text(dim_x - 8, tz((start + end) / 2), format_dim(value_mm), "dim-text")
        
        # --- LEFT DIMENSIONS (left of building) ---
        x_pos = min_x - base_offset
        
        for tier in [DimTier.OVERALL, DimTier.STRUCTURAL]:
            tier_chains = [c for c in vertical_chains if c.tier == tier]
            if not tier_chains:
                x_pos -= tier_spacing
                continue
            
            all_segments = []
            for chain in tier_chains:
                all_segments.extend(chain.segments)
            
            if all_segments:
                all_z_vals = [s[0] for s in all_segments] + [s[1] for s in all_segments]
                line_min_z, line_max_z = min(all_z_vals), max(all_z_vals)
                builder.line(x_pos, tz(line_max_z), x_pos, tz(line_min_z), "dim-line")
                
                # Extension line to building edge
                ext_right = min_x - 100
                
                drawn_z = set()
                labeled_dims = set()
                for start, end, value_mm in all_segments:
                    for z in [start, end]:
                        z_key = round(z / 50)
                        if z_key not in drawn_z:
                            drawn_z.add(z_key)
                            builder.line(x_pos, tz(z), ext_right, tz(z), "dim-ext")
                    
                    mid_z = (start + end) / 2
                    dim_key = (round(start/100), round(end/100))
                    if dim_key not in labeled_dims:
                        labeled_dims.add(dim_key)
                        if value_mm > 300 and (tier != DimTier.STRUCTURAL or value_mm > 1000):
                            builder.text(x_pos - 15, tz(mid_z), format_dim(value_mm), "dim-text")
            
            x_pos -= tier_spacing
        
        # --- RIGHT DIMENSIONS (right of building) ---
        x_pos = max_x + base_offset
        
        for tier in [DimTier.OVERALL, DimTier.STRUCTURAL]:
            tier_chains = [c for c in vertical_chains if c.tier == tier]
            if not tier_chains:
                x_pos += tier_spacing
                continue
            
            all_segments = []
            for chain in tier_chains:
                all_segments.extend(chain.segments)
            
            if all_segments:
                all_z_vals = [s[0] for s in all_segments] + [s[1] for s in all_segments]
                line_min_z, line_max_z = min(all_z_vals), max(all_z_vals)
                builder.line(x_pos, tz(line_max_z), x_pos, tz(line_min_z), "dim-line")
                
                # Extension line to building edge
                ext_left = max_x + 100
                
                drawn_z = set()
                labeled_dims = set()
                for start, end, value_mm in all_segments:
                    for z in [start, end]:
                        z_key = round(z / 50)
                        if z_key not in drawn_z:
                            drawn_z.add(z_key)
                            builder.line(x_pos, tz(z), ext_left, tz(z), "dim-ext")
                    
                    mid_z = (start + end) / 2
                    dim_key = (round(start/100), round(end/100))
                    if dim_key not in labeled_dims:
                        labeled_dims.add(dim_key)
                        if value_mm > 300 and (tier != DimTier.STRUCTURAL or value_mm > 1000):
                            builder.text(x_pos + 15, tz(mid_z), format_dim(value_mm), "dim-text")
            
            x_pos += tier_spacing
        
        return f'<!-- Intelligent Dimensions ({len(chains)} chains) -->\n{builder.to_string()}'

    def _generate_ladder_dimensions(self) -> str:
        """Generate dimension chains on each wall with openings.

        Respects dimension_settings and dimension_overrides from document data.
        Override types:
        - {'type': 'hide', 'target': 'wall_0.seg_0'} - Hide a dimension
        - {'type': 'text', 'target': 'wall_0.seg_0', 'value': '10'-0" TYP'} - Override text
        - {'type': 'add', 'start': [x1, y1], 'end': [x2, y2], 'text': 'CUSTOM', 'view': 'plan'}
        """
        settings = self.data.get('dimension_settings', {})
        overrides = self.data.get('dimension_overrides', [])

        # Check if auto-dimensioning is enabled
        if not settings.get('auto_exterior_walls', True) and not settings.get('auto_openings', True):
            # Only render custom dimensions
            return self._generate_custom_dimensions(overrides)

        dims = ['<!-- Wall Dimension Chains -->']
        dim_offset = settings.get('offset_from_wall', 600)

        # Process each wall
        for wall_idx, wall in enumerate(self.walls):
            # Only dimension exterior walls if auto_exterior_walls is set
            if wall.category != 'exterior' and not settings.get('auto_openings', True):
                continue

            geom = self._get_wall_geometry(wall)

            # Get all openings on this wall
            opening_centers = []

            if settings.get('auto_openings', True):
                for door in self.doors:
                    if door.wall_index == wall_idx:
                        opening_centers.append(door.offset)

                for window in self.windows:
                    if window.wall_index == wall_idx:
                        opening_centers.append(window.offset)

            # Skip walls with no openings (unless we want wall-to-wall dims)
            if not opening_centers and not settings.get('auto_exterior_walls', True):
                continue

            # If no openings but auto_exterior_walls is on, dimension the full wall
            if not opening_centers:
                if wall.category == 'exterior' and settings.get('auto_exterior_walls', True):
                    # Add single dimension for the wall
                    dim_id = f'wall_{wall_idx}.length'
                    if self._is_dimension_hidden(dim_id, overrides):
                        continue

                    text_override = self._get_dimension_text_override(dim_id, overrides)

                    if geom['is_horizontal']:
                        wall_start = min(geom['start_x'], geom['end_x'])
                        wall_end = max(geom['start_x'], geom['end_x'])
                        wall_z = geom['start_z']
                        dim_y = wall_z - dim_offset
                        dims.append(self._dim_line(wall_start, dim_y, wall_end, dim_y,
                                                    wall_end - wall_start, text_override))
                    elif geom['is_vertical']:
                        wall_start = min(geom['start_z'], geom['end_z'])
                        wall_end = max(geom['start_z'], geom['end_z'])
                        wall_x = geom['start_x']
                        dim_x = wall_x + dim_offset
                        dims.append(self._dim_line_v(dim_x, wall_start, wall_end,
                                                      wall_end - wall_start, text_override))
                continue

            opening_centers.sort()

            # Wall start/end positions and length
            if geom['is_horizontal']:
                wall_start = min(geom['start_x'], geom['end_x'])
                wall_end = max(geom['start_x'], geom['end_x'])
                wall_z = geom['start_z']

                # Dimension line position (offset from wall)
                dim_y = wall_z - dim_offset if wall.category == 'exterior' else wall_z + dim_offset

                # Build break points: start, centers, end
                breaks = [wall_start] + [wall_start + c for c in opening_centers] + [wall_end]

                # Create dimension chain
                for i in range(len(breaks) - 1):
                    x1, x2 = breaks[i], breaks[i + 1]
                    if x2 - x1 > 50:
                        dim_id = f'wall_{wall_idx}.seg_{i}'

                        # Check for hide override
                        if self._is_dimension_hidden(dim_id, overrides):
                            continue

                        # Check for text override
                        text_override = self._get_dimension_text_override(dim_id, overrides)

                        dims.append(self._dim_line(x1, dim_y, x2, dim_y, x2 - x1, text_override))

            elif geom['is_vertical']:
                wall_start = min(geom['start_z'], geom['end_z'])
                wall_end = max(geom['start_z'], geom['end_z'])
                wall_x = geom['start_x']

                # Dimension line position (offset from wall)
                dim_x = wall_x + dim_offset if wall.category == 'exterior' else wall_x - dim_offset

                # Build break points: start, centers, end
                breaks = [wall_start] + [wall_start + c for c in opening_centers] + [wall_end]

                # Create dimension chain
                for i in range(len(breaks) - 1):
                    z1, z2 = breaks[i], breaks[i + 1]
                    if z2 - z1 > 50:
                        dim_id = f'wall_{wall_idx}.seg_{i}'

                        # Check for hide override
                        if self._is_dimension_hidden(dim_id, overrides):
                            continue

                        # Check for text override
                        text_override = self._get_dimension_text_override(dim_id, overrides)

                        dims.append(self._dim_line_v(dim_x, z1, z2, z2 - z1, text_override))

        # Add overall building dimensions
        bounds = self._get_building_bounds()
        overall_offset = dim_offset + settings.get('chain_spacing', 400) * 2

        # South overall dimension
        dim_id = 'building.width'
        if not self._is_dimension_hidden(dim_id, overrides):
            text_override = self._get_dimension_text_override(dim_id, overrides)
            dims.append(self._dim_line(
                bounds['min_x'], bounds['min_z'] - overall_offset,
                bounds['max_x'], bounds['min_z'] - overall_offset,
                bounds['max_x'] - bounds['min_x'], text_override
            ))

        # East overall dimension
        dim_id = 'building.depth'
        if not self._is_dimension_hidden(dim_id, overrides):
            text_override = self._get_dimension_text_override(dim_id, overrides)
            dims.append(self._dim_line_v(
                bounds['max_x'] + overall_offset,
                bounds['min_z'], bounds['max_z'],
                bounds['max_z'] - bounds['min_z'], text_override
            ))

        # Add custom dimensions from overrides
        dims.append(self._generate_custom_dimensions(overrides))

        return '\n'.join(dims)

    def _generate_custom_dimensions(self, overrides: List) -> str:
        """Generate custom dimensions from 'add' type overrides."""
        dims = ['<!-- Custom Dimensions -->']

        for override in overrides:
            if override.get('type') != 'add':
                continue
            if override.get('view', 'plan') != 'plan':
                continue

            start = override.get('start', [0, 0])
            end = override.get('end', [0, 0])
            text = override.get('text', '')

            # Determine if horizontal or vertical
            if abs(end[1] - start[1]) < 50:  # Horizontal
                value = abs(end[0] - start[0])
                dims.append(self._dim_line(
                    min(start[0], end[0]), start[1],
                    max(start[0], end[0]), start[1],
                    value, text if text else None
                ))
            else:  # Vertical
                value = abs(end[1] - start[1])
                dims.append(self._dim_line_v(
                    start[0],
                    min(start[1], end[1]), max(start[1], end[1]),
                    value, text if text else None
                ))

        return '\n'.join(dims)

    def _generate_edge_dimensions(self, edge: str, bounds: dict, breaks: list, spacing: float) -> str:
        """Generate multi-layer dimensions for one edge."""
        dims = []

        if edge == 'south':
            base_y = bounds['min_z']
            # Layer 1: Detail (all breaks)
            for i in range(len(breaks) - 1):
                x1, x2 = breaks[i], breaks[i + 1]
                if x2 - x1 > 50:  # Skip tiny gaps
                    dims.append(self._dim_line(x1, base_y - spacing, x2, base_y - spacing, x2 - x1))

            # Layer 2: Wall-to-wall (filter to major breaks only)
            wall_breaks = self._filter_to_wall_breaks(breaks, 'horizontal', bounds)
            if len(wall_breaks) > 1:
                for i in range(len(wall_breaks) - 1):
                    x1, x2 = wall_breaks[i], wall_breaks[i + 1]
                    dims.append(self._dim_line(x1, base_y - spacing * 2, x2, base_y - spacing * 2, x2 - x1))

            # Layer 3: Overall
            dims.append(self._dim_line(
                bounds['min_x'], base_y - spacing * 3,
                bounds['max_x'], base_y - spacing * 3,
                bounds['max_x'] - bounds['min_x']
            ))

        elif edge == 'east':
            base_x = bounds['max_x']
            # Layer 1: Detail
            for i in range(len(breaks) - 1):
                z1, z2 = breaks[i], breaks[i + 1]
                if z2 - z1 > 50:
                    dims.append(self._dim_line_v(base_x + spacing, z1, z2, z2 - z1))

            # Layer 2: Wall-to-wall
            wall_breaks = self._filter_to_wall_breaks(breaks, 'vertical', bounds)
            if len(wall_breaks) > 1:
                for i in range(len(wall_breaks) - 1):
                    z1, z2 = wall_breaks[i], wall_breaks[i + 1]
                    dims.append(self._dim_line_v(base_x + spacing * 2, z1, z2, z2 - z1))

            # Layer 3: Overall
            dims.append(self._dim_line_v(
                base_x + spacing * 3,
                bounds['min_z'], bounds['max_z'],
                bounds['max_z'] - bounds['min_z']
            ))

        return '\n'.join(dims)

    def _filter_to_wall_breaks(self, breaks: list, wall_dir: str, bounds: dict) -> list:
        """Filter break points to only include wall intersections (not openings)."""
        wall_positions = []

        # Always include building corners
        if wall_dir == 'horizontal':
            wall_positions.extend([bounds['min_x'], bounds['max_x']])
        else:
            wall_positions.extend([bounds['min_z'], bounds['max_z']])

        # Add interior wall positions
        for wall in self.walls:
            if wall.category == 'exterior':
                continue
            geom = self._get_wall_geometry(wall)

            if wall_dir == 'horizontal' and geom['is_vertical']:
                wall_positions.append(geom['start_x'])
            elif wall_dir == 'vertical' and geom['is_horizontal']:
                wall_positions.append(geom['start_z'])

        # Filter breaks to only those near wall positions
        tolerance = 100
        filtered = []
        for b in breaks:
            for wp in wall_positions:
                if abs(b - wp) < tolerance:
                    filtered.append(b)
                    break

        return sorted(set(filtered))

    def _format_dimension(self, value_mm: float) -> str:
        """Format dimension value based on display_format setting.

        Args:
            value_mm: Value in millimeters

        Returns:
            Formatted string (e.g., "3'-6\"" for imperial or "1067" for metric)
        """
        settings = self.data.get('dimension_settings', {})
        fmt = settings.get('display_format', 'metric')

        if fmt == 'imperial':
            inches = value_mm / 25.4
            feet = int(inches // 12)
            remaining_inches = inches % 12

            # Round to nearest 1/16"
            sixteenths = round(remaining_inches * 16)
            remaining_inches = sixteenths / 16

            # Handle case where rounding brings us to 12 inches
            if remaining_inches >= 12:
                feet += 1
                remaining_inches = 0

            if remaining_inches == 0:
                return f"{feet}'-0\""
            elif remaining_inches == int(remaining_inches):
                return f"{feet}'-{int(remaining_inches)}\""
            else:
                # Format as fraction for common values
                whole_in = int(remaining_inches)
                frac = remaining_inches - whole_in

                # Common fractions
                if abs(frac - 0.5) < 0.01:
                    frac_str = "1/2"
                elif abs(frac - 0.25) < 0.01:
                    frac_str = "1/4"
                elif abs(frac - 0.75) < 0.01:
                    frac_str = "3/4"
                elif abs(frac - 0.125) < 0.01:
                    frac_str = "1/8"
                elif abs(frac - 0.375) < 0.01:
                    frac_str = "3/8"
                elif abs(frac - 0.625) < 0.01:
                    frac_str = "5/8"
                elif abs(frac - 0.875) < 0.01:
                    frac_str = "7/8"
                else:
                    # Fall back to decimal
                    return f"{feet}'-{remaining_inches:.1f}\""

                if whole_in > 0:
                    return f"{feet}'-{whole_in} {frac_str}\""
                else:
                    return f"{feet}'-{frac_str}\""
        else:
            # Metric: just show millimeters as integer
            return str(int(value_mm))

    def _dim_line(self, x1: float, y: float, x2: float, y2: float, value, text: str = None) -> str:
        """Generate a horizontal dimension line with ticks and text.

        Args:
            x1, y: Start point
            x2, y2: End point (y2 is typically same as y for horizontal)
            value: Numeric value in mm (used if text is None)
            text: Optional override text to display instead of formatted value
        """
        settings = self.data.get('dimension_settings', {})
        tick = settings.get('tick_length', 150)
        text_offset = 120  # Small gap above line
        font_size = self.dim_text_size
        line_width = settings.get('line_width', 3)

        # Use override text or format the value
        display_text = text if text is not None else self._format_dimension(value)

        return f'''<g>
  <line x1="{x1}" y1="{y}" x2="{x2}" y2="{y}" stroke="#000" stroke-width="{line_width}"/>
  <line x1="{x1}" y1="{y + tick}" x2="{x1}" y2="{y - tick}" stroke="#000" stroke-width="2"/>
  <line x1="{x2}" y1="{y + tick}" x2="{x2}" y2="{y - tick}" stroke="#000" stroke-width="2"/>
  <text x="{(x1 + x2)/2}" y="{y - text_offset}" font-family="Arial" font-size="{font_size}" font-weight="bold" text-anchor="middle">{display_text}</text>
</g>'''

    def _dim_line_v(self, x: float, z1: float, z2: float, value, text: str = None) -> str:
        """Generate a vertical dimension line.

        Args:
            x: X position
            z1, z2: Start and end Y positions
            value: Numeric value in mm (used if text is None)
            text: Optional override text to display instead of formatted value
        """
        settings = self.data.get('dimension_settings', {})
        tick = settings.get('tick_length', 150)
        text_offset = 120  # Small gap beside line
        font_size = self.dim_text_size
        line_width = settings.get('line_width', 3)

        # Use override text or format the value
        display_text = text if text is not None else self._format_dimension(value)

        return f'''<g>
  <line x1="{x}" y1="{z1}" x2="{x}" y2="{z2}" stroke="#000" stroke-width="{line_width}"/>
  <line x1="{x - tick}" y1="{z1}" x2="{x + tick}" y2="{z1}" stroke="#000" stroke-width="2"/>
  <line x1="{x - tick}" y1="{z2}" x2="{x + tick}" y2="{z2}" stroke="#000" stroke-width="2"/>
  <text x="{x + text_offset}" y="{(z1 + z2)/2}" font-family="Arial" font-size="{font_size}" font-weight="bold" text-anchor="start" dominant-baseline="middle">{display_text}</text>
</g>'''

    def _generate_north_arrow(self, x: float, y: float) -> str:
        """Generate north arrow symbol."""
        return f'''<!-- North Arrow -->
<g transform="translate({x}, {y})">
  <circle cx="0" cy="0" r="400" fill="none" stroke="#000" stroke-width="4"/>
  <polygon points="0,-300 -80,200 0,80 80,200" fill="black"/>
  <text x="0" y="-450" class="grid-label" text-anchor="middle">N</text>
</g>'''

    def _generate_scale_bar(self, x: float, y: float) -> str:
        """Generate scale bar."""
        return f'''<!-- Scale Bar -->
<g transform="translate({x}, {y})">
  <text x="0" y="-80" style="font: 180px Arial;">SCALE 1:100</text>
  <rect x="0" y="0" width="1000" height="80" fill="black"/>
  <rect x="1000" y="0" width="1000" height="80" fill="white" stroke="black" stroke-width="2"/>
  <text x="0" y="180" style="font: 140px Arial;">0</text>
  <text x="1000" y="180" style="font: 140px Arial;">1m</text>
  <text x="2000" y="180" style="font: 140px Arial;">2m</text>
</g>'''


def main():
    import argparse
    import sys

    parser = argparse.ArgumentParser(description='Generate floor and roof plans from building JSON')
    parser.add_argument('input', nargs='?',
                        default='../../Shared/TestData/output/generated_building.json',
                        help='Input JSON file path')
    parser.add_argument('-o', '--output',
                        default='../../Shared/TestData/output',
                        help='Output directory for SVG files')
    parser.add_argument('-s', '--scale', type=float, default=0.05,
                        help='Scale factor (default: 0.05)')

    args = parser.parse_args()

    json_path = Path(args.input)
    if not json_path.is_absolute():
        json_path = Path(__file__).parent / json_path

    output_dir = Path(args.output)
    if not output_dir.is_absolute():
        output_dir = Path(__file__).parent / output_dir

    if not json_path.exists():
        print(f"Error: JSON file not found: {json_path}")
        return 1

    # Ensure output directory exists
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Generating plans from: {json_path}")

    generator = PlanGenerator(str(json_path))

    # Generate floor plan
    floor_plan_svg = generator.generate_floor_plan_svg(scale=args.scale)
    floor_plan_path = output_dir / "floor_plan.svg"
    with open(floor_plan_path, 'w', encoding='utf-8') as f:
        f.write(floor_plan_svg)
    print(f"  Floor plan: {floor_plan_path}")

    # Generate roof plan
    roof_plan_svg = generator.generate_roof_plan_svg(scale=args.scale)
    roof_plan_path = output_dir / "roof_plan.svg"
    with open(roof_plan_path, 'w', encoding='utf-8') as f:
        f.write(roof_plan_svg)
    print(f"  Roof plan:  {roof_plan_path}")

    print("Done!")
    return 0


if __name__ == "__main__":
    exit(main())
