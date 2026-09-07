#!/usr/bin/env python3
"""
intelligent_dimensions.py - Architecturally-aware dimensioning

Replaces the "dump all coordinates" approach with intelligent dimension chains:

1. PER-ROOM CHAINS:
   - Each room gets its own dimension set
   - Dimensions run parallel to room edges
   - Interior face to interior face (clear dimensions)

2. THREE-TIER HIERARCHY:
   - Tier 1: Overall building envelope (exterior face to exterior face)
   - Tier 2: Major structural grid (primary room divisions)
   - Tier 3: Interior partitions (secondary divisions, openings)

3. WALL FACE LOGIC:
   - Exterior walls: dimension from interior face
   - Interior partitions: dimension centerline or face-to-face
   - Openings: located from nearest wall intersection

4. BOXED REGION LOGIC:
   - Identify rectangular room regions
   - Create perpendicular dimension chains for each
   - Avoid overlapping dimension lines
"""

import math
from typing import List, Dict, Tuple, Set, Optional
from dataclasses import dataclass, field
from enum import Enum


class WallType(Enum):
    EXTERIOR = "exterior"
    INTERIOR = "interior"
    PARTITION = "partition"


class DimTier(Enum):
    OVERALL = 1    # Building envelope
    STRUCTURAL = 2 # Primary divisions (wall dimensions)
    OPENING = 3    # Door/window dimensions centered on openings
    INTERIOR = 4   # Room dimensions


@dataclass
class WallSegment:
    """A wall segment with architectural metadata."""
    start: Tuple[float, float]  # (x, z) in mm
    end: Tuple[float, float]
    category: str  # "exterior" or "interior"
    thickness: float  # mm
    rooms: List[str]  # Adjacent room IDs
    openings: List[Dict] = field(default_factory=list)  # Door/window openings
    
    @property
    def is_exterior(self) -> bool:
        return self.category == "exterior"
    
    @property
    def is_horizontal(self) -> bool:
        """True if wall runs primarily horizontal (along X)."""
        dx = abs(self.end[0] - self.start[0])
        dz = abs(self.end[1] - self.start[1])
        return dx > dz
    
    def interior_face(self, room_center: Tuple[float, float]) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        """
        Get the interior face line for a given room.
        Returns (start, end) of interior face.
        """
        # Vector from start to end
        dx = self.end[0] - self.start[0]
        dz = self.end[1] - self.start[1]
        length = math.sqrt(dx*dx + dz*dz)
        
        if length == 0:
            return self.start, self.end
        
        # Normalize
        ux, uz = dx / length, dz / length
        
        # Perpendicular pointing "in" (toward room center)
        # Determine which side is interior based on room center
        wall_mid = ((self.start[0] + self.end[0]) / 2, (self.start[1] + self.end[1]) / 2)
        to_center = (room_center[0] - wall_mid[0], room_center[1] - wall_mid[1])
        
        # Perpendicular direction (rotated 90°)
        px, pz = -uz, ux
        
        # Check direction
        dot = px * to_center[0] + pz * to_center[1]
        if dot < 0:
            px, pz = -px, -pz
        
        # Offset by half thickness
        offset = self.thickness / 2
        if self.is_exterior:
            offset = -offset if dot > 0 else offset  # Exterior: offset toward interior
        
        ix = px * offset
        iz = pz * offset
        
        return (
            (self.start[0] + ix, self.start[1] + iz),
            (self.end[0] + ix, self.end[1] + iz)
        )


@dataclass
class RoomBox:
    """A rectangular room region for dimensioning."""
    room_id: str
    name: str
    x: float  # min x
    z: float  # min z
    width: float
    depth: float
    room_type: str
    
    @property
    def center(self) -> Tuple[float, float]:
        return (self.x + self.width / 2, self.z + self.depth / 2)
    
    @property
    def bounds(self) -> Tuple[float, float, float, float]:
        """Returns (min_x, min_z, max_x, max_z)."""
        return (self.x, self.z, self.x + self.width, self.z + self.depth)
    
    def get_walls_for_dimension(self, walls: List[WallSegment]) -> Dict[str, List[WallSegment]]:
        """
        Get walls that bound this room, organized by side.
        Returns dict: 'north', 'south', 'east', 'west' -> wall list
        """
        min_x, min_z, max_x, max_z = self.bounds
        tolerance = 100  # mm
        
        sides = {'north': [], 'south': [], 'east': [], 'west': []}
        
        for wall in walls:
            # Check if wall is on any side of room
            wx1, wz1 = wall.start
            wx2, wz2 = wall.end
            
            # North wall (max_z)
            if abs(max(wz1, wz2) - max_z) < tolerance and \
               min(wx1, wx2) < max_x + tolerance and max(wx1, wx2) > min_x - tolerance:
                sides['north'].append(wall)
            
            # South wall (min_z)
            elif abs(min(wz1, wz2) - min_z) < tolerance and \
                 min(wx1, wx2) < max_x + tolerance and max(wx1, wx2) > min_x - tolerance:
                sides['south'].append(wall)
            
            # East wall (max_x)
            elif abs(max(wx1, wx2) - max_x) < tolerance and \
                 min(wz1, wz2) < max_z + tolerance and max(wz1, wz2) > min_z - tolerance:
                sides['east'].append(wall)
            
            # West wall (min_x)
            elif abs(min(wx1, wx2) - min_x) < tolerance and \
                 min(wz1, wz2) < max_z + tolerance and max(wz1, wz2) > min_z - tolerance:
                sides['west'].append(wall)
        
        return sides


@dataclass
class DimensionChain:
    """A single dimension chain (line with ticks and values)."""
    tier: DimTier
    orientation: str  # 'horizontal' or 'vertical'
    y_pos: float  # Screen Y position for horizontal, X for vertical
    segments: List[Tuple[float, float, float]]  # (start, end, value_mm)
    label: str = ""
    
    def to_svg(self, tx, tz, builder, format_fn):
        """Render this chain to SVG with tier-specific styling."""
        if not self.segments:
            return

        # Create tier-specific CSS classes
        tier_num = self.tier.value
        line_class = f"dim-line tier-{tier_num}"
        ext_class = f"dim-ext tier-{tier_num}"
        text_class = f"dim-text tier-{tier_num}"

        # Draw dimension line
        if self.orientation == 'horizontal':
            # Find full extent
            all_x = [s[0] for s in self.segments] + [s[1] for s in self.segments]
            min_x, max_x = min(all_x), max(all_x)

            y = self.y_pos
            builder.line(tx(min_x), y, tx(max_x), y, line_class)

            # Draw ticks and labels
            drawn_positions = set()
            for start, end, value_mm in self.segments:
                # Ticks at segment boundaries
                for x in [start, end]:
                    x_key = round(x / 10)  # Round to 10mm for dedup
                    if x_key not in drawn_positions:
                        drawn_positions.add(x_key)
                        builder.line(tx(x), y - 5, tx(x), y + 5, ext_class)

                # Label
                mid_x = (start + end) / 2
                if value_mm > 200:  # Only label if significant
                    builder.text(tx(mid_x), y - 12, format_fn(value_mm), text_class)

        else:  # vertical
            all_z = [s[0] for s in self.segments] + [s[1] for s in self.segments]
            min_z, max_z = min(all_z), max(all_z)

            x = self.y_pos  # Actually X position for vertical dims
            builder.line(x, tz(max_z), x, tz(min_z), line_class)

            drawn_positions = set()
            for start, end, value_mm in self.segments:
                for z in [start, end]:
                    z_key = round(z / 10)
                    if z_key not in drawn_positions:
                        drawn_positions.add(z_key)
                        builder.line(x - 5, tz(z), x + 5, tz(z), ext_class)

                mid_z = (start + end) / 2
                if value_mm > 200:
                    builder.text(x - 12, tz(mid_z), format_fn(value_mm), text_class)


class IntelligentDimensioning:
    """Main class for architecturally-aware dimensioning."""
    
    def __init__(self, rooms: List[Dict], walls: List[Dict]):
        self.rooms = self._parse_rooms(rooms)
        self.walls = self._parse_walls(walls)
        self.chains: List[DimensionChain] = []
    
    def _parse_rooms(self, rooms_data: List[Dict]) -> List[RoomBox]:
        """Parse room data into RoomBox objects."""
        rooms = []
        for r in rooms_data:
            bounds = r.get("bounds", {})
            rooms.append(RoomBox(
                room_id=r.get("id", "unknown"),
                name=r.get("name", "Unknown"),
                x=bounds.get("x", 0),
                z=bounds.get("z", 0),
                width=bounds.get("width", 0),
                depth=bounds.get("height", 0),
                room_type=r.get("room_type", "other")
            ))
        return rooms
    
    def _parse_walls(self, walls_data: List[Dict]) -> List[WallSegment]:
        """Parse wall data into WallSegment objects."""
        walls = []
        for w in walls_data:
            start = w.get("start", [0, 0, 0])
            end = w.get("end", [0, 0, 0])
            category = w.get("category", "interior")
            thickness = 150 if category == "exterior" else 100
            openings = w.get("openings", [])  # Store openings
            
            walls.append(WallSegment(
                start=(start[0], start[2]),
                end=(end[0], end[2]),
                category=category,
                thickness=thickness,
                rooms=[],
                openings=openings  # Pass openings to constructor
            ))
        return walls
    
    def generate_chains(self) -> List[DimensionChain]:
        """
        Generate all dimension chains using intelligent logic.
        """
        self.chains = []
        
        # Tier 1: Overall building envelope
        self._add_overall_dimensions()
        
        # Tier 2: Major structural divisions (wall dimensions)
        self._add_structural_grid()
        
        # Tier 3: Opening dimensions (doors/windows centered)
        self._add_opening_dimensions()
        
        # Tier 4: Per-room dimensions for complex rooms
        self._add_room_dimensions()
        
        return self.chains
    
    def _add_overall_dimensions(self):
        """Add Tier 1: Overall building envelope dimensions."""
        # Find building bounds from ALL walls (not just exterior)
        # Interior walls may extend beyond exterior walls at corners
        all_x = [w.start[0] for w in self.walls] + [w.end[0] for w in self.walls]
        all_z = [w.start[1] for w in self.walls] + [w.end[1] for w in self.walls]
        
        min_x, max_x = min(all_x), max(all_x)
        min_z, max_z = min(all_z), max(all_z)
        
        building_width = max_x - min_x
        building_depth = max_z - min_z
        
        # Store bounds for later
        self.building_bounds = (min_x, min_z, max_x, max_z)
        
        # Create overall dimension chains (single segment = full width/depth)
        if building_width > 0:
            self.chains.append(DimensionChain(
                tier=DimTier.OVERALL,
                orientation='horizontal',
                y_pos=0,  # Will be set during rendering
                segments=[(min_x, max_x, building_width)],
                label="Building Width"
            ))
        
        if building_depth > 0:
            self.chains.append(DimensionChain(
                tier=DimTier.OVERALL,
                orientation='vertical',
                y_pos=0,
                segments=[(min_z, max_z, building_depth)],
                label="Building Depth"
            ))
    
    def _merge_overlapping_segments(self, segments: List[Tuple[float, float, float]]) -> List[Tuple[float, float, float]]:
        """Merge segments that represent the same dimension (within tolerance)."""
        if not segments:
            return []
        
        # Sort by start position
        sorted_segs = sorted(segments, key=lambda s: (s[0], s[1]))
        merged = []
        
        tolerance = 100  # mm tolerance for "same" segment
        
        for seg in sorted_segs:
            start, end, value = seg
            start_rounded = round(start / tolerance) * tolerance
            end_rounded = round(end / tolerance) * tolerance
            
            # Check if this overlaps with any existing merged segment
            found = False
            for i, (ms, me, mv) in enumerate(merged):
                ms_r = round(ms / tolerance) * tolerance
                me_r = round(me / tolerance) * tolerance
                
                # Same segment (within tolerance)
                if abs(start_rounded - ms_r) < tolerance and abs(end_rounded - me_r) < tolerance:
                    found = True
                    break
            
            if not found:
                merged.append(seg)
        
        return merged
    
    def _add_structural_grid(self):
        """Add Tier 2: Major structural divisions between room clusters."""
        # Find major X divisions (primary room separations)
        x_divisions = set()
        z_divisions = set()
        
        for room in self.rooms:
            min_x, min_z, max_x, max_z = room.bounds
            x_divisions.add(min_x)
            x_divisions.add(max_x)
            z_divisions.add(min_z)
            z_divisions.add(max_z)
        
        # Sort and create chain segments
        x_sorted = sorted(x_divisions)
        z_sorted = sorted(z_divisions)
        
        # Create horizontal chain (Z-constant, measuring X)
        if len(x_sorted) >= 2:
            x_segments = []
            for i in range(len(x_sorted) - 1):
                x1, x2 = x_sorted[i], x_sorted[i + 1]
                x_segments.append((x1, x2, x2 - x1))
            
            self.chains.append(DimensionChain(
                tier=DimTier.STRUCTURAL,
                orientation='horizontal',
                y_pos=-50,  # Will be set during rendering
                segments=x_segments,
                label="Structural Grid X"
            ))
        
        # Create vertical chain (X-constant, measuring Z)
        if len(z_sorted) >= 2:
            z_segments = []
            for i in range(len(z_sorted) - 1):
                z1, z2 = z_sorted[i], z_sorted[i + 1]
                z_segments.append((z1, z2, z2 - z1))
            
            self.chains.append(DimensionChain(
                tier=DimTier.STRUCTURAL,
                orientation='vertical',
                y_pos=-50,
                segments=z_segments,
                label="Structural Grid Z"
            ))
    
    def _add_opening_dimensions(self):
        """Add Tier 3: Door and window dimensions centered on each opening.
        
        These dimensions show the width of each door and window,
        positioned at the center of the opening for clarity.
        """
        # Collect all openings from walls
        opening_segments = []  # (start, end, width, type, wall_centerline)
        
        for wall in self.walls:
            # Check if wall has openings attribute or data
            if hasattr(wall, 'openings') and wall.openings:
                for o in wall.openings:
                    # Handle both dict-style and tuple-style openings
                    if isinstance(o, dict):
                        start = o.get('start', [0, 0, 0])
                        end = o.get('end', [0, 0, 0])
                        o_type = o.get('type', 'opening')
                    else:  # tuple/list style
                        start, end, o_type = o[0], o[1], o[2] if len(o) > 2 else 'opening'
                    
                    # Calculate opening center and width
                    if abs(end[0] - start[0]) > abs(end[2] - start[2]):
                        # Horizontal opening (along X)
                        o_start = min(start[0], end[0])
                        o_end = max(start[0], end[0])
                        width = o_end - o_start
                        center_x = (o_start + o_end) / 2
                        center_z = start[2]  # Constant Z
                        is_horizontal = True
                    else:
                        # Vertical opening (along Z)
                        o_start = min(start[2], end[2])
                        o_end = max(start[2], end[2])
                        width = o_end - o_start
                        center_x = start[0]  # Constant X
                        center_z = (o_start + o_end) / 2
                        is_horizontal = False
                    
                    opening_segments.append({
                        'start': o_start,
                        'end': o_end,
                        'width': width,
                        'type': o_type,
                        'center_x': center_x,
                        'center_z': center_z,
                        'is_horizontal': is_horizontal
                    })
        
        # Group openings by their orientation and position
        horizontal_openings = [o for o in opening_segments if o['is_horizontal']]
        vertical_openings = [o for o in opening_segments if not o['is_horizontal']]
        
        # Create dimension chains for horizontal openings (doors/windows along X)
        if horizontal_openings:
            h_segments = []
            for o in horizontal_openings:
                h_segments.append((o['start'], o['end'], o['width'], o['type'], o['center_z']))
            
            # Sort by Z position (centerline of wall)
            h_segments.sort(key=lambda s: s[4])
            
            # Create segments (start, end, width) for each opening
            dim_segments = [(s[0], s[1], s[2]) for s in h_segments]
            
            self.chains.append(DimensionChain(
                tier=DimTier.OPENING,
                orientation='horizontal',
                y_pos=-40,  # Between structural and interior
                segments=dim_segments,
                label="Opening Widths X"
            ))
        
        # Create dimension chains for vertical openings (doors/windows along Z)
        if vertical_openings:
            v_segments = []
            for o in vertical_openings:
                v_segments.append((o['start'], o['end'], o['width'], o['type'], o['center_x']))
            
            # Sort by X position (centerline of wall)
            v_segments.sort(key=lambda s: s[4])
            
            # Create segments
            dim_segments = [(s[0], s[1], s[2]) for s in v_segments]
            
            self.chains.append(DimensionChain(
                tier=DimTier.OPENING,
                orientation='vertical',
                y_pos=-40,
                segments=dim_segments,
                label="Opening Widths Z"
            ))
    
    def _add_room_dimensions(self):
        """Add Tier 3: Per-room dimensions inside each room for clarity.
        
        Interior dimensions are placed inside rooms at 1/3 offset from walls,
        making it immediately clear which dimension belongs to which space.
        """
        for room in self.rooms:
            area = room.width * room.depth / 1e6  # sqm
            if area < 5:  # Skip small rooms (closets, etc)
                continue
            
            min_x, min_z, max_x, max_z = room.bounds
            
            # Place horizontal dimension at 1/3 from bottom wall
            # This puts it clearly inside the room, not near any opening
            y_pos = min_z + room.depth / 3
            
            self.chains.append(DimensionChain(
                tier=DimTier.INTERIOR,
                orientation='horizontal',
                y_pos=y_pos,
                segments=[(min_x, max_x, room.width)],
                label=f"{room.name} width"
            ))
            
            # Place vertical dimension at 1/3 from left wall
            x_pos = min_x + room.width / 3
            
            self.chains.append(DimensionChain(
                tier=DimTier.INTERIOR,
                orientation='vertical',
                y_pos=x_pos,
                segments=[(min_z, max_z, room.depth)],
                label=f"{room.name} depth"
            ))
    
    def render_to_svg(self, builder, tx, tz, format_fn):
        """Render all chains to SVG with proper positioning."""
        # Get building bounds
        if hasattr(self, 'building_bounds'):
            min_x, min_z, max_x, max_z = self.building_bounds
        else:
            # Calculate from rooms
            all_x = [r.x for r in self.rooms] + [r.x + r.width for r in self.rooms]
            all_z = [r.z for r in self.rooms] + [r.z + r.depth for r in self.rooms]
            min_x, max_x = min(all_x), max(all_x)
            min_z, max_z = min(all_z), max(all_z)
        
        # Position chains by tier
        base_offset = 60  # pixels from building
        line_spacing = 30
        
        # Group by orientation and tier
        horizontal_chains = [c for c in self.chains if c.orientation == 'horizontal']
        vertical_chains = [c for c in self.chains if c.orientation == 'vertical']
        
        # Position horizontal chains (above building)
        y_pos = tz(max_z) - base_offset
        for chain in sorted(horizontal_chains, key=lambda c: c.tier.value):
            chain.y_pos = y_pos
            y_pos -= line_spacing
            chain.to_svg(tx, tz, builder, format_fn)
        
        # Position vertical chains (left of building)
        x_pos = tx(min_x) - base_offset
        for chain in sorted(vertical_chains, key=lambda c: c.tier.value):
            chain.y_pos = x_pos
            x_pos -= line_spacing
            chain.to_svg(tx, tz, builder, format_fn)


def generate_intelligent_dimensions(
    rooms: List[Dict],
    walls: List[Dict],
    doors: List[Dict],
    windows: List[Dict],
    builder,
    tx, tz,
    format_fn
):
    """
    Main entry point for intelligent dimensioning.
    
    Args:
        rooms: Room data from building JSON
        walls: Wall data from building JSON
        doors: Door data
        windows: Window data
        builder: SVG builder
        tx, tz: Coordinate transform functions
        format_fn: Dimension formatting function
    """
    dim = IntelligentDimensioning(rooms, walls)
    dim.generate_chains()
    dim.render_to_svg(builder, tx, tz, format_fn)
    
    return len(dim.chains)


# Test function
if __name__ == "__main__":
    import json
    
    # Load test data
    test_json = "/root/.openclaw/workspace/test_pipeline/test_house.json"
    with open(test_json) as f:
        data = json.load(f)
    
    dim = IntelligentDimensioning(data["rooms"], data["walls"])
    chains = dim.generate_chains()
    
    print(f"Generated {len(chains)} intelligent dimension chains:")
    for c in chains:
        print(f"  - {c.label}: {c.orientation}, tier {c.tier.name}, {len(c.segments)} segments")
