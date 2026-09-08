#!/usr/bin/env python3
"""
text_to_json.py - Convert plain text building descriptions to QBD JSON format

Parses natural language building descriptions and generates structured JSON
output compatible with ArchEngine UE5 viewer and plan generators.

Usage:
    python text_to_json.py "3 bedroom 2 bath house 1800 sqft"
    python text_to_json.py --file description.txt
    python text_to_json.py --interactive

Output:
    Writes to Shared/TestData/output/generated_building.json
"""

import json
import re
import sys
import uuid
import math
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Tuple
from pathlib import Path
from enum import Enum


class RoomType(Enum):
    LIVING = "living"
    KITCHEN = "kitchen"
    DINING = "dining"
    BEDROOM = "bedroom"
    BATHROOM = "bathroom"
    HALF_BATH = "half_bath"
    MASTER_BEDROOM = "master_bedroom"
    MASTER_BATH = "master_bath"
    OFFICE = "office"
    LAUNDRY = "laundry"
    GARAGE = "garage"
    MUDROOM = "mudroom"
    PANTRY = "pantry"
    CLOSET = "closet"
    HALLWAY = "hallway"
    FOYER = "foyer"
    GREAT_ROOM = "great_room"
    FAMILY_ROOM = "family_room"
    BONUS_ROOM = "bonus_room"
    UTILITY = "utility"


# Room size defaults in mm (width x depth)
ROOM_SIZES = {
    RoomType.LIVING: (4500, 5000),
    RoomType.KITCHEN: (3600, 4200),
    RoomType.DINING: (3600, 4200),
    RoomType.BEDROOM: (3600, 4000),
    RoomType.BATHROOM: (2400, 3000),
    RoomType.HALF_BATH: (1500, 2400),
    RoomType.MASTER_BEDROOM: (4800, 5400),
    RoomType.MASTER_BATH: (3000, 3600),
    RoomType.OFFICE: (3000, 3600),
    RoomType.LAUNDRY: (2400, 3000),
    RoomType.GARAGE: (6000, 6000),
    RoomType.MUDROOM: (2400, 2400),
    RoomType.PANTRY: (1800, 2400),
    RoomType.CLOSET: (1800, 2400),
    RoomType.HALLWAY: (1200, 3600),
    RoomType.FOYER: (2400, 3000),
    RoomType.GREAT_ROOM: (6000, 7200),
    RoomType.FAMILY_ROOM: (4200, 5400),
    RoomType.BONUS_ROOM: (4200, 4800),
    RoomType.UTILITY: (2400, 3000),
}

# Zone classification
ROOM_ZONES = {
    RoomType.LIVING: "public",
    RoomType.KITCHEN: "service",
    RoomType.DINING: "public",
    RoomType.BEDROOM: "private",
    RoomType.BATHROOM: "service",
    RoomType.HALF_BATH: "service",
    RoomType.MASTER_BEDROOM: "private",
    RoomType.MASTER_BATH: "private",
    RoomType.OFFICE: "private",
    RoomType.LAUNDRY: "service",
    RoomType.GARAGE: "service",
    RoomType.MUDROOM: "service",
    RoomType.PANTRY: "service",
    RoomType.CLOSET: "private",
    RoomType.HALLWAY: "circulation",
    RoomType.FOYER: "public",
    RoomType.GREAT_ROOM: "public",
    RoomType.FAMILY_ROOM: "public",
    RoomType.BONUS_ROOM: "flex",
    RoomType.UTILITY: "service",
}


@dataclass
class ParsedRoom:
    """Parsed room from text description"""
    room_type: RoomType
    name: str
    count: int = 1
    width: float = 0  # mm
    depth: float = 0  # mm

    def __post_init__(self):
        if self.width == 0 or self.depth == 0:
            default = ROOM_SIZES.get(self.room_type, (3000, 3600))
            self.width = self.width or default[0]
            self.depth = self.depth or default[1]


@dataclass
class PlacedRoom:
    """Room with placement coordinates"""
    id: str
    name: str
    room_type: str
    x: float
    y: float
    width: float
    depth: float
    zone: str
    level: str = "Level 1"


@dataclass
class Wall:
    """Wall definition"""
    start: List[float]
    end: List[float]
    height: float
    wall_type: str
    category: str
    level_name: str
    rooms: List[str]


@dataclass
class Door:
    """Door definition"""
    wall_index: int
    offset: float
    width: float
    height: float
    door_type: str
    swing: str
    room1: str
    room2: str


@dataclass
class Window:
    """Window definition"""
    wall_index: int
    offset: float
    width: float
    height: float
    sill_height: float
    window_type: str
    room: str


class TextParser:
    """Parse natural language building descriptions"""

    # Map architectural style to default roof type and pitch
    STYLE_TO_ROOF = {
        'modern': ('flat', 0.5),
        'contemporary': ('shed', 2),
        'traditional': ('gable', 6),
        'craftsman': ('gable', 4),
        'colonial': ('gable', 8),
        'ranch': ('gable', 4),
        'farmhouse': ('gable', 8),
        'mediterranean': ('hip', 4),
        'victorian': ('hip', 8),
        'cape_cod': ('gable', 10),
        'tudor': ('gable', 12),
        'split_level': ('gable', 4),
    }

    # Roof materials by style
    STYLE_TO_MATERIAL = {
        'modern': 'metal',
        'contemporary': 'metal',
        'traditional': 'asphalt_shingle',
        'craftsman': 'asphalt_shingle',
        'colonial': 'asphalt_shingle',
        'ranch': 'asphalt_shingle',
        'farmhouse': 'metal',
        'mediterranean': 'tile',
        'victorian': 'slate',
        'cape_cod': 'asphalt_shingle',
        'tudor': 'slate',
    }

    def __init__(self):
        self.rooms: List[ParsedRoom] = []
        self.total_sqft = 0
        self.total_sqm = 0
        self.building_type = "residential"
        self.style = "traditional"
        self.stories = 1
        self.garage_type = "none"
        self.roof_type = "gable"
        self.roof_pitch = 6
        self.roof_material = "asphalt_shingle"

    def parse(self, text: str) -> Dict:
        """Parse text and return extracted building parameters"""
        text = text.lower().strip()

        # Extract square footage
        self._parse_sqft(text)

        # Extract rooms
        self._parse_bedrooms(text)
        self._parse_bathrooms(text)
        self._parse_special_rooms(text)

        # Extract style and type
        self._parse_style(text)
        self._parse_building_type(text)
        self._parse_stories(text)
        self._parse_garage(text)

        # Parse roof (after style, so we can use defaults)
        self._parse_roof(text)

        # Add standard rooms if not explicitly mentioned
        self._add_default_rooms()

        return {
            "rooms": self.rooms,
            "sqft": self.total_sqft,
            "sqm": self.total_sqm,
            "building_type": self.building_type,
            "style": self.style,
            "stories": self.stories,
            "garage": self.garage_type,
            "roof_type": self.roof_type,
            "roof_pitch": self.roof_pitch,
            "roof_material": self.roof_material
        }

    def _parse_sqft(self, text: str):
        """Extract square footage from text"""
        # Match patterns like "1800 sqft", "1,800 sq ft", "2000 square feet"
        patterns = [
            r'(\d+[,\d]*)\s*(?:sq\.?\s*ft|sqft|square\s*feet)',
            r'(\d+[,\d]*)\s*(?:sq\.?\s*m|sqm|square\s*meters?)',
        ]

        for i, pattern in enumerate(patterns):
            match = re.search(pattern, text)
            if match:
                value = int(match.group(1).replace(',', ''))
                if i == 0:  # sqft
                    self.total_sqft = value
                    self.total_sqm = int(value * 0.0929)
                else:  # sqm
                    self.total_sqm = value
                    self.total_sqft = int(value * 10.764)
                return

        # Default based on bedrooms if not specified
        self.total_sqft = 1200  # Will be updated based on rooms

    def _parse_bedrooms(self, text: str):
        """Extract bedroom count"""
        patterns = [
            r'(\d+)\s*(?:bed(?:room)?s?|br|bdr)',
            r'(\w+)\s*(?:bed(?:room)?s?|br)',
        ]

        word_to_num = {
            'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5,
            'six': 6, 'a': 1, 'single': 1
        }

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                val = match.group(1)
                if val.isdigit():
                    count = int(val)
                else:
                    count = word_to_num.get(val, 1)

                # First bedroom is master
                if count >= 1:
                    self.rooms.append(ParsedRoom(
                        room_type=RoomType.MASTER_BEDROOM,
                        name="Primary Bedroom"
                    ))

                # Additional bedrooms
                for i in range(1, count):
                    self.rooms.append(ParsedRoom(
                        room_type=RoomType.BEDROOM,
                        name=f"Bedroom {i + 1}"
                    ))
                return

    def _parse_bathrooms(self, text: str):
        """Extract bathroom count"""
        patterns = [
            r'(\d+\.?\d*)\s*(?:bath(?:room)?s?|ba)',
            r'(\w+)\s*(?:bath(?:room)?s?)',
        ]

        word_to_num = {
            'one': 1, 'two': 2, 'three': 3, 'four': 4,
            'a': 1, 'half': 0.5
        }

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                val = match.group(1)
                if re.match(r'\d+\.?\d*', val):
                    count = float(val)
                else:
                    count = word_to_num.get(val, 1)

                full_baths = int(count)
                has_half = (count % 1) >= 0.5

                # Master bath if we have master bedroom
                has_master = any(r.room_type == RoomType.MASTER_BEDROOM for r in self.rooms)

                if has_master and full_baths >= 1:
                    self.rooms.append(ParsedRoom(
                        room_type=RoomType.MASTER_BATH,
                        name="Primary Bath"
                    ))
                    full_baths -= 1

                # Additional full baths
                for i in range(full_baths):
                    self.rooms.append(ParsedRoom(
                        room_type=RoomType.BATHROOM,
                        name=f"Bathroom {i + 1}" if full_baths > 1 else "Bathroom"
                    ))

                # Half bath
                if has_half:
                    self.rooms.append(ParsedRoom(
                        room_type=RoomType.HALF_BATH,
                        name="Half Bath"
                    ))
                return

    def _parse_special_rooms(self, text: str):
        """Parse special room mentions"""
        room_keywords = {
            'office': RoomType.OFFICE,
            'study': RoomType.OFFICE,
            'den': RoomType.OFFICE,
            'laundry': RoomType.LAUNDRY,
            'mudroom': RoomType.MUDROOM,
            'mud room': RoomType.MUDROOM,
            'pantry': RoomType.PANTRY,
            'great room': RoomType.GREAT_ROOM,
            'family room': RoomType.FAMILY_ROOM,
            'bonus room': RoomType.BONUS_ROOM,
            'bonus': RoomType.BONUS_ROOM,
            'dining room': RoomType.DINING,
            'dining': RoomType.DINING,
            'foyer': RoomType.FOYER,
            'entry': RoomType.FOYER,
        }

        for keyword, room_type in room_keywords.items():
            if keyword in text:
                # Don't add duplicates
                if not any(r.room_type == room_type for r in self.rooms):
                    self.rooms.append(ParsedRoom(
                        room_type=room_type,
                        name=room_type.value.replace('_', ' ').title()
                    ))

    def _parse_style(self, text: str):
        """Extract architectural style"""
        styles = ['modern', 'contemporary', 'traditional', 'craftsman',
                  'colonial', 'ranch', 'farmhouse', 'mediterranean', 'victorian']
        for style in styles:
            if style in text:
                self.style = style
                return

    def _parse_building_type(self, text: str):
        """Extract building type"""
        if any(word in text for word in ['apartment', 'condo', 'flat']):
            self.building_type = "apartment"
        elif any(word in text for word in ['townhouse', 'town house', 'townhome']):
            self.building_type = "townhouse"
        elif any(word in text for word in ['commercial', 'office building', 'retail']):
            self.building_type = "commercial"
        else:
            self.building_type = "residential"

    def _parse_stories(self, text: str):
        """Extract number of stories"""
        patterns = [
            r'(\d+)\s*(?:story|stories|storey|storeys|floor|floors|level|levels)',
            r'(single|one|two|three)\s*(?:story|storey)',
        ]

        word_to_num = {'single': 1, 'one': 1, 'two': 2, 'three': 3}

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                val = match.group(1)
                if val.isdigit():
                    self.stories = int(val)
                else:
                    self.stories = word_to_num.get(val, 1)
                return

        # Check for "ranch" which implies single story
        if 'ranch' in text:
            self.stories = 1

    def _parse_garage(self, text: str):
        """Extract garage type"""
        if 'no garage' in text:
            self.garage_type = "none"
        elif any(x in text for x in ['3 car', 'three car', '3-car']):
            self.garage_type = "3_car"
            self.rooms.append(ParsedRoom(
                room_type=RoomType.GARAGE,
                name="3-Car Garage",
                width=9000,
                depth=6600
            ))
        elif any(x in text for x in ['2 car', 'two car', '2-car', 'double garage']):
            self.garage_type = "2_car"
            self.rooms.append(ParsedRoom(
                room_type=RoomType.GARAGE,
                name="2-Car Garage",
                width=6000,
                depth=6600
            ))
        elif any(x in text for x in ['1 car', 'one car', '1-car', 'single garage', 'garage']):
            self.garage_type = "1_car"
            self.rooms.append(ParsedRoom(
                room_type=RoomType.GARAGE,
                name="Garage",
                width=3600,
                depth=6600
            ))

    def _parse_roof(self, text: str):
        """Extract roof type, pitch, and material - or infer from style"""
        # Check for explicit roof type mentions
        roof_types = {
            'flat roof': 'flat',
            'gable roof': 'gable',
            'hip roof': 'hip',
            'shed roof': 'shed',
            'mansard': 'mansard',
            'gambrel': 'gambrel',
        }

        for keyword, roof_type in roof_types.items():
            if keyword in text:
                self.roof_type = roof_type
                break
        else:
            # Infer from style
            style_roof = self.STYLE_TO_ROOF.get(self.style, ('gable', 6))
            self.roof_type = style_roof[0]
            self.roof_pitch = style_roof[1]

        # Check for explicit pitch
        pitch_match = re.search(r'(\d+)[:/]12\s*(?:pitch|roof)?', text)
        if pitch_match:
            self.roof_pitch = int(pitch_match.group(1))
        elif self.roof_type == 'flat':
            self.roof_pitch = 0.25  # 1/4:12 for drainage
        elif self.roof_type not in ['flat', 'shed']:
            # Use style default if not already set
            if not hasattr(self, '_pitch_set'):
                style_roof = self.STYLE_TO_ROOF.get(self.style, ('gable', 6))
                self.roof_pitch = style_roof[1]

        # Check for explicit material
        materials = {
            'metal roof': 'metal',
            'standing seam': 'metal',
            'shingle': 'asphalt_shingle',
            'asphalt': 'asphalt_shingle',
            'tile roof': 'tile',
            'clay tile': 'tile',
            'slate roof': 'slate',
            'cedar shake': 'wood_shake',
        }

        for keyword, material in materials.items():
            if keyword in text:
                self.roof_material = material
                break
        else:
            # Infer from style
            self.roof_material = self.STYLE_TO_MATERIAL.get(self.style, 'asphalt_shingle')

    def _add_default_rooms(self):
        """Add default rooms if not explicitly mentioned"""
        room_types = [r.room_type for r in self.rooms]

        # Always need living space
        if RoomType.LIVING not in room_types and RoomType.GREAT_ROOM not in room_types:
            self.rooms.append(ParsedRoom(
                room_type=RoomType.LIVING,
                name="Living Room"
            ))

        # Always need kitchen
        if RoomType.KITCHEN not in room_types:
            self.rooms.append(ParsedRoom(
                room_type=RoomType.KITCHEN,
                name="Kitchen"
            ))

        # Add hallway for circulation if multiple bedrooms
        bedrooms = [r for r in self.rooms if r.room_type in
                   [RoomType.BEDROOM, RoomType.MASTER_BEDROOM]]
        if len(bedrooms) > 1 and RoomType.HALLWAY not in room_types:
            self.rooms.append(ParsedRoom(
                room_type=RoomType.HALLWAY,
                name="Hallway"
            ))


class LayoutGenerator:
    """Generate floor plan layout from parsed rooms"""

    def __init__(self, rooms: List[ParsedRoom], target_sqm: int = 0,
                 roof_type: str = "gable", roof_pitch: float = 6,
                 roof_material: str = "asphalt_shingle", style: str = "traditional"):
        self.rooms = rooms
        self.target_sqm = target_sqm
        self.placed_rooms: List[PlacedRoom] = []
        self.walls: List[Wall] = []
        self.doors: List[Door] = []
        self.windows: List[Window] = []
        self.wall_height = 2700  # mm
        self.building_width = 0
        self.building_depth = 0
        # Roof parameters
        self.roof_type = roof_type
        self.roof_pitch = roof_pitch
        self.roof_material = roof_material
        self.style = style

    def generate(self) -> Dict:
        """Generate complete building layout"""
        # Scale rooms if target sqm specified
        if self.target_sqm > 0:
            self._scale_rooms()

        # Place rooms in grid layout
        self._place_rooms()

        # Generate walls
        self._generate_walls()

        # Generate doors
        self._generate_doors()

        # Generate windows
        self._generate_windows()

        return self._to_json()

    def _scale_rooms(self):
        """Scale room sizes to match target square meters"""
        current_area = sum(r.width * r.depth for r in self.rooms)
        target_area = self.target_sqm * 1_000_000  # Convert sqm to mm²

        if current_area > 0:
            scale = math.sqrt(target_area / current_area)
            for room in self.rooms:
                room.width *= scale
                room.depth *= scale

    def _place_rooms(self):
        """Place rooms in a simple grid layout"""
        # Sort rooms by zone for better placement
        zone_order = ['public', 'service', 'private', 'circulation', 'flex']
        sorted_rooms = sorted(self.rooms,
            key=lambda r: zone_order.index(ROOM_ZONES.get(r.room_type, 'flex')))

        # Simple row-based placement
        current_x = 0
        current_y = 0
        row_height = 0
        max_width = 0

        # Determine rough building width based on target
        if self.target_sqm > 0:
            target_width = math.sqrt(self.target_sqm * 1_000_000) * 1.2
        else:
            target_width = 15000  # Default 15m

        for i, room in enumerate(sorted_rooms):
            # Check if we need a new row
            if current_x + room.width > target_width and current_x > 0:
                current_x = 0
                current_y += row_height
                row_height = 0

            # Create room ID
            room_id = f"{room.room_type.value}_{i}"
            if room.room_type == RoomType.MASTER_BEDROOM:
                room_id = "master_bedroom"
            elif room.room_type == RoomType.MASTER_BATH:
                room_id = "master_bath"
            elif room.room_type == RoomType.LIVING:
                room_id = "living"
            elif room.room_type == RoomType.KITCHEN:
                room_id = "kitchen"
            elif room.room_type == RoomType.GARAGE:
                room_id = "garage"

            placed = PlacedRoom(
                id=room_id,
                name=room.name,
                room_type=room.room_type.value,
                x=current_x,
                y=current_y,
                width=room.width,
                depth=room.depth,
                zone=ROOM_ZONES.get(room.room_type, "flex")
            )
            self.placed_rooms.append(placed)

            current_x += room.width
            row_height = max(row_height, room.depth)
            max_width = max(max_width, current_x)

        self.building_width = max_width
        self.building_depth = current_y + row_height

    def _generate_walls(self):
        """Generate walls for all rooms"""
        # Exterior walls (building perimeter)
        self._add_wall(
            [0, 0, 0], [self.building_width, 0, 0],
            "ext_2x6_r21", "exterior", ["exterior", self._room_at(0, 0)]
        )
        self._add_wall(
            [self.building_width, 0, 0], [self.building_width, 0, self.building_depth],
            "ext_2x6_r21", "exterior", ["exterior", self._room_at(self.building_width - 1, 0)]
        )
        self._add_wall(
            [self.building_width, 0, self.building_depth], [0, 0, self.building_depth],
            "ext_2x6_r21", "exterior", ["exterior", self._room_at(0, self.building_depth - 1)]
        )
        self._add_wall(
            [0, 0, self.building_depth], [0, 0, 0],
            "ext_2x6_r21", "exterior", ["exterior", self._room_at(0, 0)]
        )

        # Interior walls between rooms
        for i, room in enumerate(self.placed_rooms):
            # Right wall (if not building edge)
            right_x = room.x + room.width
            if right_x < self.building_width:
                neighbor = self._room_at(right_x + 1, room.y + room.depth / 2)
                if neighbor and neighbor != room.id:
                    wall_type = "wet_2x6" if self._is_wet_wall(room.id, neighbor) else "int_2x4"
                    category = "wet_wall" if wall_type == "wet_2x6" else "interior"
                    self._add_wall(
                        [right_x, 0, room.y], [right_x, 0, room.y + room.depth],
                        wall_type, category, [room.id, neighbor]
                    )

            # Bottom wall (if not building edge)
            bottom_y = room.y + room.depth
            if bottom_y < self.building_depth:
                neighbor = self._room_at(room.x + room.width / 2, bottom_y + 1)
                if neighbor and neighbor != room.id:
                    wall_type = "wet_2x6" if self._is_wet_wall(room.id, neighbor) else "int_2x4"
                    category = "wet_wall" if wall_type == "wet_2x6" else "interior"
                    self._add_wall(
                        [room.x, 0, bottom_y], [room.x + room.width, 0, bottom_y],
                        wall_type, category, [room.id, neighbor]
                    )

    def _add_wall(self, start: List[float], end: List[float],
                  wall_type: str, category: str, rooms: List[str]):
        """Add a wall to the list"""
        self.walls.append(Wall(
            start=start,
            end=end,
            height=self.wall_height,
            wall_type=wall_type,
            category=category,
            level_name="Level 1",
            rooms=rooms
        ))

    def _room_at(self, x: float, y: float) -> Optional[str]:
        """Find room at given coordinates"""
        for room in self.placed_rooms:
            if (room.x <= x < room.x + room.width and
                room.y <= y < room.y + room.depth):
                return room.id
        return None

    def _is_wet_wall(self, room1: str, room2: str) -> bool:
        """Check if wall should be a wet wall (plumbing)"""
        wet_rooms = ['bathroom', 'master_bath', 'half_bath', 'kitchen', 'laundry']
        r1_wet = any(w in room1 for w in wet_rooms)
        r2_wet = any(w in room2 for w in wet_rooms)
        return r1_wet and r2_wet

    def _generate_doors(self):
        """Generate doors between rooms"""
        # Entry door on front wall
        self.doors.append(Door(
            wall_index=0,
            offset=2000,
            width=914,
            height=2134,
            door_type="entry",
            swing="left_in",
            room1="exterior",
            room2=self._room_at(2000, 100) or "living"
        ))

        # Interior doors between adjacent rooms
        for i, wall in enumerate(self.walls):
            if wall.category == "interior" or wall.category == "wet_wall":
                # Calculate wall length
                length = math.sqrt(
                    (wall.end[0] - wall.start[0])**2 +
                    (wall.end[2] - wall.start[2])**2
                )

                if length >= 2000:  # Only add door if wall is long enough
                    # Determine door type based on rooms
                    door_type = "swing"
                    if any("bath" in r for r in wall.rooms):
                        door_type = "pocket"
                    elif "closet" in wall.rooms[0] or "closet" in wall.rooms[1]:
                        door_type = "bifold"

                    self.doors.append(Door(
                        wall_index=i,
                        offset=length / 2,
                        width=812 if "bath" in str(wall.rooms) else 914,
                        height=2134,
                        door_type=door_type,
                        swing="left_in",
                        room1=wall.rooms[0],
                        room2=wall.rooms[1]
                    ))

    def _generate_windows(self):
        """Generate windows on exterior walls"""
        for i, wall in enumerate(self.walls):
            if wall.category != "exterior":
                continue

            # Get interior room
            interior_room = wall.rooms[1] if wall.rooms[0] == "exterior" else wall.rooms[0]
            if not interior_room or interior_room == "exterior":
                continue

            # Skip garage windows
            if "garage" in interior_room:
                continue

            # Calculate wall length
            length = math.sqrt(
                (wall.end[0] - wall.start[0])**2 +
                (wall.end[2] - wall.start[2])**2
            )

            # Add windows based on wall length
            num_windows = max(1, int(length / 3000))
            window_spacing = length / (num_windows + 1)

            for w in range(num_windows):
                offset = window_spacing * (w + 1)

                # Bathroom windows are smaller and higher
                if "bath" in interior_room:
                    self.windows.append(Window(
                        wall_index=i,
                        offset=offset,
                        width=600,
                        height=600,
                        sill_height=1500,
                        window_type="casement",
                        room=interior_room
                    ))
                else:
                    self.windows.append(Window(
                        wall_index=i,
                        offset=offset,
                        width=1200,
                        height=1200,
                        sill_height=900,
                        window_type="double_hung",
                        room=interior_room
                    ))

    def _to_json(self) -> Dict:
        """Convert layout to JSON structure"""
        # Calculate total area
        total_area_mm2 = sum(r.width * r.depth for r in self.placed_rooms)
        total_sqm = total_area_mm2 / 1_000_000

        # Build rooms dict
        rooms_dict = {}
        for room in self.placed_rooms:
            rooms_dict[room.id] = {
                "name": room.name,
                "room_type": room.room_type,
                "bounds": {
                    "x": room.x,
                    "y": room.y,
                    "width": room.width,
                    "height": room.depth
                },
                "area": room.width * room.depth,
                "center": {
                    "x": room.x + room.width / 2,
                    "y": room.y + room.depth / 2
                },
                "zone": room.zone,
                "level": room.level
            }

        # Build walls array
        walls_array = []
        for wall in self.walls:
            walls_array.append({
                "start": wall.start,
                "end": wall.end,
                "height": wall.height,
                "wall_type": wall.wall_type,
                "category": wall.category,
                "level_name": wall.level_name,
                "rooms": wall.rooms
            })

        # Build doors array
        doors_array = []
        for door in self.doors:
            doors_array.append({
                "wall_index": door.wall_index,
                "offset": door.offset,
                "width": door.width,
                "height": door.height,
                "type": door.door_type,
                "swing": door.swing,
                "room1": door.room1,
                "room2": door.room2
            })

        # Build windows array
        windows_array = []
        for window in self.windows:
            windows_array.append({
                "wall_index": window.wall_index,
                "offset": window.offset,
                "width": window.width,
                "height": window.height,
                "sill_height": window.sill_height,
                "type": window.window_type,
                "room": window.room
            })

        # Generate roof
        roofs_array = self._generate_roof()

        # Generate floor slabs
        floors_array = self._generate_floors()

        return {
            "success": True,
            "building_id": str(uuid.uuid4())[:8],
            "width": self.building_width,
            "depth": self.building_depth,
            "sqm": round(total_sqm, 1),
            "sqft": round(total_sqm * 10.764),
            "unit": "mm",
            "output_format": "archengine",
            "walls_batch": walls_array,
            "floors_batch": floors_array,
            "doors": doors_array,
            "windows": windows_array,
            "rooms": rooms_dict,
            "roofs": roofs_array,
            "wall_types": self._get_wall_types(),
            "levels": [
                {
                    "name": "Level 1",
                    "elevation": 0,
                    "height": self.wall_height
                },
                {
                    "name": "Roof Level",
                    "elevation": self.wall_height,
                    "height": 0
                }
            ],
            "summary": {
                "total_walls": len(walls_array),
                "exterior_walls": len([w for w in walls_array if w["category"] == "exterior"]),
                "interior_walls": len([w for w in walls_array if w["category"] == "interior"]),
                "wet_walls": len([w for w in walls_array if w["category"] == "wet_wall"]),
                "floors": len(floors_array),
                "doors": len(doors_array),
                "windows": len(windows_array),
                "rooms_placed": len(rooms_dict),
                "roofs": len(roofs_array)
            }
        }

    def _generate_floors(self) -> List[Dict]:
        """Generate floor slabs from building bounds and room layout"""
        floors = []

        # Main floor slab covering entire building footprint
        # Format matches kernel's floors_batch parsing: start, end, thickness, level_name, room
        floors.append({
            "start": [0, 0, 0],
            "end": [self.building_width, 0, self.building_depth],
            "thickness": 150,  # 150mm (6") concrete slab on grade
            "level_name": "Level 1",
            "room": None,  # Full building slab, not room-specific
            "material": "concrete"
        })

        return floors

    def _get_wall_types(self) -> List[Dict]:
        """Return wall assembly definitions with layers for section views"""
        return [
            {
                "id": "ext_2x6_r21",
                "name": "Exterior 2x6 R-21",
                "layers": [
                    {"name": "Siding", "material": "vinyl_siding", "thickness": 6, "function": "exterior_finish", "color": [0.85, 0.85, 0.8, 1.0], "r_value": 0.6},
                    {"name": "House Wrap", "material": "tyvek", "thickness": 1, "function": "membrane", "color": [0.95, 0.95, 0.95, 1.0], "r_value": 0.0},
                    {"name": "OSB Sheathing", "material": "osb", "thickness": 11, "function": "sheathing", "color": [0.76, 0.60, 0.42, 1.0], "r_value": 0.6},
                    {"name": "2x6 Stud + R-21", "material": "wood_insulation", "thickness": 140, "function": "structure", "color": [1.0, 0.85, 0.4, 1.0], "r_value": 21.0},
                    {"name": "Vapor Barrier", "material": "poly", "thickness": 0.15, "function": "membrane", "color": [0.8, 0.8, 0.9, 1.0], "r_value": 0.0},
                    {"name": "Drywall", "material": "gypsum", "thickness": 13, "function": "interior_finish", "color": [0.95, 0.95, 0.92, 1.0], "r_value": 0.5}
                ]
            },
            {
                "id": "int_2x4",
                "name": "Interior 2x4 Partition",
                "layers": [
                    {"name": "Drywall", "material": "gypsum", "thickness": 13, "function": "interior_finish", "color": [0.95, 0.95, 0.92, 1.0], "r_value": 0.5},
                    {"name": "2x4 Stud", "material": "wood", "thickness": 89, "function": "structure", "color": [0.9, 0.75, 0.5, 1.0], "r_value": 3.5},
                    {"name": "Drywall", "material": "gypsum", "thickness": 13, "function": "interior_finish", "color": [0.95, 0.95, 0.92, 1.0], "r_value": 0.5}
                ]
            },
            {
                "id": "wet_2x6",
                "name": "Wet Wall 2x6 (Plumbing)",
                "layers": [
                    {"name": "Tile", "material": "ceramic_tile", "thickness": 10, "function": "exterior_finish", "color": [0.9, 0.9, 0.95, 1.0], "r_value": 0.1},
                    {"name": "Cement Board", "material": "cement_board", "thickness": 13, "function": "sheathing", "color": [0.7, 0.7, 0.7, 1.0], "r_value": 0.2},
                    {"name": "2x6 Stud (Plumbing)", "material": "wood", "thickness": 140, "function": "structure", "color": [0.9, 0.75, 0.5, 1.0], "r_value": 4.4},
                    {"name": "Drywall", "material": "gypsum", "thickness": 13, "function": "interior_finish", "color": [0.95, 0.95, 0.92, 1.0], "r_value": 0.5}
                ]
            }
        ]

    def _generate_roof(self) -> List[Dict]:
        """Generate roof geometry based on building footprint and style"""
        overhang = 600  # mm eave overhang

        # Calculate ridge height based on pitch (rise per 12" run)
        if self.roof_type in ["gable", "hip"]:
            half_span_ft = (self.building_depth / 2) / 304.8  # mm to feet
            ridge_rise = half_span_ft * self.roof_pitch * 25.4  # back to mm
            ridge_height = self.wall_height + ridge_rise
        elif self.roof_type == "shed":
            span_ft = self.building_depth / 304.8
            ridge_rise = span_ft * self.roof_pitch * 25.4
            ridge_height = self.wall_height + ridge_rise
        else:  # flat
            ridge_height = self.wall_height + 150  # minimal slope for drainage

        roof = {
            "id": "roof_1",
            "type": self.roof_type,
            "pitch": self.roof_pitch,
            "overhang": overhang,
            "material": self.roof_material,
            "level_name": "Roof Level",
            "ridges": [],
            "surfaces": [],
            "dormers": [],
            "skylights": []
        }

        w = self.building_width
        d = self.building_depth
        h = self.wall_height
        rh = ridge_height
        ov = overhang

        if self.roof_type == "gable":
            # Ridge runs along the length (X axis), centered on depth
            # Kernel format: [X=width, Y=height, Z=depth]
            roof["ridges"] = [{
                "id": "ridge_1",
                "start_point": [-ov, rh, d / 2],
                "end_point": [w + ov, rh, d / 2],
                "height": rh - h
            }]
            roof["surfaces"] = [
                {
                    "id": "surface_south",
                    "vertices": [
                        [-ov, h, -ov], [w + ov, h, -ov],
                        [w + ov, rh, d / 2], [-ov, rh, d / 2]
                    ],
                    "pitch": self.roof_pitch,
                    "orientation": "south"
                },
                {
                    "id": "surface_north",
                    "vertices": [
                        [-ov, rh, d / 2], [w + ov, rh, d / 2],
                        [w + ov, h, d + ov], [-ov, h, d + ov]
                    ],
                    "pitch": self.roof_pitch,
                    "orientation": "north"
                }
            ]

        elif self.roof_type == "hip":
            # Hip roof - ridge runs along the LONGER dimension
            # For a proper hip, ridge is inset from ends by half the SHORTER dimension
            # Kernel format: [X=width, Y=height, Z=depth]

            if w >= d:
                # Building is wider than deep - ridge runs along X (width)
                # Ridge is centered on depth (Z = d/2), inset from width ends
                ridge_inset = d / 2  # Inset from X ends by half the depth
                ridge_z = d / 2  # Ridge is centered on depth

                roof["ridges"] = [{
                    "id": "ridge_1",
                    "start_point": [ridge_inset, rh, ridge_z],
                    "end_point": [w - ridge_inset, rh, ridge_z],
                    "height": rh - h
                }]
                roof["surfaces"] = [
                    {
                        "id": "surface_south",
                        "vertices": [
                            [-ov, h, -ov], [w + ov, h, -ov],
                            [w - ridge_inset, rh, ridge_z], [ridge_inset, rh, ridge_z]
                        ],
                        "pitch": self.roof_pitch,
                        "orientation": "south"
                    },
                    {
                        "id": "surface_north",
                        "vertices": [
                            [ridge_inset, rh, ridge_z], [w - ridge_inset, rh, ridge_z],
                            [w + ov, h, d + ov], [-ov, h, d + ov]
                        ],
                        "pitch": self.roof_pitch,
                        "orientation": "north"
                    },
                    {
                        "id": "surface_west",
                        "vertices": [
                            [-ov, h, -ov], [ridge_inset, rh, ridge_z],
                            [-ov, h, d + ov]
                        ],
                        "pitch": self.roof_pitch,
                        "orientation": "west"
                    },
                    {
                        "id": "surface_east",
                        "vertices": [
                            [w + ov, h, -ov], [w + ov, h, d + ov],
                            [w - ridge_inset, rh, ridge_z]
                        ],
                        "pitch": self.roof_pitch,
                        "orientation": "east"
                    }
                ]
            else:
                # Building is deeper than wide - ridge runs along Z (depth)
                # Ridge is centered on width (X = w/2), inset from depth ends
                ridge_inset = w / 2  # Inset from Z ends by half the width
                ridge_x = w / 2  # Ridge is centered on width

                roof["ridges"] = [{
                    "id": "ridge_1",
                    "start_point": [ridge_x, rh, ridge_inset],
                    "end_point": [ridge_x, rh, d - ridge_inset],
                    "height": rh - h
                }]
                roof["surfaces"] = [
                    {
                        "id": "surface_west",
                        "vertices": [
                            [-ov, h, -ov], [ridge_x, rh, ridge_inset],
                            [ridge_x, rh, d - ridge_inset], [-ov, h, d + ov]
                        ],
                        "pitch": self.roof_pitch,
                        "orientation": "west"
                    },
                    {
                        "id": "surface_east",
                        "vertices": [
                            [w + ov, h, -ov], [w + ov, h, d + ov],
                            [ridge_x, rh, d - ridge_inset], [ridge_x, rh, ridge_inset]
                        ],
                        "pitch": self.roof_pitch,
                        "orientation": "east"
                    },
                    {
                        "id": "surface_south",
                        "vertices": [
                            [-ov, h, -ov], [w + ov, h, -ov],
                            [ridge_x, rh, ridge_inset]
                        ],
                        "pitch": self.roof_pitch,
                        "orientation": "south"
                    },
                    {
                        "id": "surface_north",
                        "vertices": [
                            [w + ov, h, d + ov], [-ov, h, d + ov],
                            [ridge_x, rh, d - ridge_inset]
                        ],
                        "pitch": self.roof_pitch,
                        "orientation": "north"
                    }
                ]

        elif self.roof_type == "shed":
            # Single slope, high side at back (north)
            # Kernel format: [X=width, Y=height, Z=depth]
            roof["surfaces"] = [{
                "id": "surface_main",
                "vertices": [
                    [-ov, h, -ov], [w + ov, h, -ov],
                    [w + ov, rh, d + ov], [-ov, rh, d + ov]
                ],
                "pitch": self.roof_pitch,
                "orientation": "south"
            }]

        else:  # flat
            # Kernel format: [X=width, Y=height, Z=depth]
            roof["surfaces"] = [{
                "id": "surface_flat",
                "vertices": [
                    [-ov, rh, -ov], [w + ov, rh, -ov],
                    [w + ov, rh, d + ov], [-ov, rh, d + ov]
                ],
                "pitch": 0.25,
                "orientation": "flat"
            }]

        return [roof]


def text_to_json(text: str) -> Dict:
    """Main conversion function: text description to QBD JSON"""
    # Parse the text
    parser = TextParser()
    parsed = parser.parse(text)

    # Generate layout with roof parameters
    generator = LayoutGenerator(
        rooms=parsed["rooms"],
        target_sqm=parsed.get("sqm", 0),
        roof_type=parsed.get("roof_type", "gable"),
        roof_pitch=parsed.get("roof_pitch", 6),
        roof_material=parsed.get("roof_material", "asphalt_shingle"),
        style=parsed.get("style", "traditional")
    )

    result = generator.generate()

    # Add QBD answers for reference
    result["qbd_answers"] = {
        "description": text,
        "building_type": parsed["building_type"],
        "style": parsed["style"],
        "stories": parsed["stories"],
        "garage": parsed["garage"],
        "roof_type": parsed["roof_type"],
        "roof_pitch": parsed["roof_pitch"],
        "roof_material": parsed["roof_material"],
        "sqft": parsed.get("sqft", result["sqft"]),
        "bedrooms": len([r for r in parsed["rooms"]
                        if r.room_type in [RoomType.BEDROOM, RoomType.MASTER_BEDROOM]]),
        "bathrooms": len([r for r in parsed["rooms"]
                         if r.room_type in [RoomType.BATHROOM, RoomType.MASTER_BATH, RoomType.HALF_BATH]])
    }

    return result


def main():
    """CLI entry point"""
    import argparse

    arg_parser = argparse.ArgumentParser(
        description="Convert plain text building descriptions to QBD JSON"
    )
    arg_parser.add_argument(
        "description",
        nargs="?",
        help="Building description text"
    )
    arg_parser.add_argument(
        "--file", "-f",
        help="Read description from file"
    )
    arg_parser.add_argument(
        "--output", "-o",
        help="Output file path (default: Shared/TestData/output/generated_building.json)"
    )
    arg_parser.add_argument(
        "--interactive", "-i",
        action="store_true",
        help="Interactive mode - enter description interactively"
    )
    arg_parser.add_argument(
        "--pretty", "-p",
        action="store_true",
        default=True,
        help="Pretty print JSON output"
    )

    args = arg_parser.parse_args()

    # Get description text
    if args.interactive:
        print("Enter building description (press Enter twice to finish):")
        lines = []
        while True:
            line = input()
            if line == "":
                break
            lines.append(line)
        description = " ".join(lines)
    elif args.file:
        with open(args.file, 'r') as f:
            description = f.read()
    elif args.description:
        description = args.description
    else:
        # Default example
        description = "3 bedroom 2 bathroom modern house 1500 sqft with 2 car garage and office"
        print(f"Using default description: {description}")

    # Convert to JSON
    result = text_to_json(description)

    # Determine output path
    script_dir = Path(__file__).parent
    output_dir = script_dir.parent.parent / "Shared" / "TestData" / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.output:
        output_path = Path(args.output)
    else:
        output_path = output_dir / "generated_building.json"

    # Write output
    with open(output_path, 'w') as f:
        if args.pretty:
            json.dump(result, f, indent=2)
        else:
            json.dump(result, f)

    print(f"\nGenerated building layout:")
    print(f"  Size: {result['width']/1000:.1f}m x {result['depth']/1000:.1f}m")
    print(f"  Area: {result['sqm']} sqm ({result['sqft']} sqft)")
    print(f"  Rooms: {result['summary']['rooms_placed']}")
    print(f"  Walls: {result['summary']['total_walls']} ({result['summary']['exterior_walls']} exterior)")
    print(f"  Floors: {result['summary']['floors']}")
    print(f"  Doors: {result['summary']['doors']}")
    print(f"  Windows: {result['summary']['windows']}")
    print(f"\nOutput written to: {output_path}")

    return result


if __name__ == "__main__":
    main()
