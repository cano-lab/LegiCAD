"""Default values for QBD Algebra.

Contains default room sizes, furniture dimensions, clearances,
and other constants used throughout the system.
"""

from typing import Dict, List, Any
from dataclasses import dataclass


# =============================================================================
# Room Type Defaults
# =============================================================================

@dataclass
class RoomTypeDefaults:
    """Default values for a room type."""
    area_min: float  # m²
    area_max: float  # m²
    default_features: List[str]
    default_adjacencies: List[tuple]  # (room_type, strength)
    aspect_ratio_min: float  # width/length
    aspect_ratio_max: float
    ceiling_height: int  # mm


ROOM_DEFAULTS: Dict[str, RoomTypeDefaults] = {
    "bedroom": RoomTypeDefaults(
        area_min=9.0, area_max=14.0,
        default_features=["closet"],
        default_adjacencies=[("bathroom", "preferred")],
        aspect_ratio_min=0.75, aspect_ratio_max=1.3,
        ceiling_height=2700
    ),
    "primary_bedroom": RoomTypeDefaults(
        area_min=14.0, area_max=25.0,
        default_features=["closet", "ensuite"],
        default_adjacencies=[("ensuite", "required")],
        aspect_ratio_min=0.75, aspect_ratio_max=1.3,
        ceiling_height=2700
    ),
    "bathroom": RoomTypeDefaults(
        area_min=4.0, area_max=7.0,
        default_features=["toilet", "sink", "tub_shower"],
        default_adjacencies=[],
        aspect_ratio_min=0.5, aspect_ratio_max=2.0,
        ceiling_height=2700
    ),
    "ensuite": RoomTypeDefaults(
        area_min=4.5, area_max=9.0,
        default_features=["toilet", "sink", "shower"],
        default_adjacencies=[],  # Parent bedroom is required, handled specially
        aspect_ratio_min=0.5, aspect_ratio_max=2.0,
        ceiling_height=2700
    ),
    "powder_room": RoomTypeDefaults(
        area_min=1.5, area_max=3.0,
        default_features=["toilet", "sink"],
        default_adjacencies=[("entry", "preferred")],
        aspect_ratio_min=0.5, aspect_ratio_max=2.0,
        ceiling_height=2700
    ),
    "kitchen": RoomTypeDefaults(
        area_min=9.0, area_max=20.0,
        default_features=["sink", "stove", "fridge"],
        default_adjacencies=[("living", "preferred"), ("dining", "preferred")],
        aspect_ratio_min=0.5, aspect_ratio_max=2.0,
        ceiling_height=2700
    ),
    "living": RoomTypeDefaults(
        area_min=16.0, area_max=35.0,
        default_features=["seating"],
        default_adjacencies=[("entry", "preferred")],
        aspect_ratio_min=0.6, aspect_ratio_max=1.6,
        ceiling_height=2700
    ),
    "dining": RoomTypeDefaults(
        area_min=9.0, area_max=16.0,
        default_features=["table"],
        default_adjacencies=[("kitchen", "preferred")],
        aspect_ratio_min=0.7, aspect_ratio_max=1.4,
        ceiling_height=2700
    ),
    "office": RoomTypeDefaults(
        area_min=7.0, area_max=14.0,
        default_features=["desk"],
        default_adjacencies=[],
        aspect_ratio_min=0.7, aspect_ratio_max=1.4,
        ceiling_height=2700
    ),
    "laundry": RoomTypeDefaults(
        area_min=3.0, area_max=7.0,
        default_features=["washer", "dryer"],
        default_adjacencies=[],
        aspect_ratio_min=0.5, aspect_ratio_max=2.0,
        ceiling_height=2700
    ),
    "mudroom": RoomTypeDefaults(
        area_min=3.0, area_max=7.0,
        default_features=["hooks", "bench"],
        default_adjacencies=[("entry", "required"), ("garage", "preferred")],
        aspect_ratio_min=0.5, aspect_ratio_max=2.0,
        ceiling_height=2700
    ),
    "garage_1car": RoomTypeDefaults(
        area_min=18.0, area_max=25.0,
        default_features=[],
        default_adjacencies=[("entry", "preferred")],
        aspect_ratio_min=0.5, aspect_ratio_max=1.5,
        ceiling_height=2700
    ),
    "garage_2car": RoomTypeDefaults(
        area_min=35.0, area_max=50.0,
        default_features=[],
        default_adjacencies=[("entry", "preferred")],
        aspect_ratio_min=0.6, aspect_ratio_max=1.5,
        ceiling_height=2700
    ),
    "entry": RoomTypeDefaults(
        area_min=2.0, area_max=6.0,
        default_features=[],
        default_adjacencies=[],
        aspect_ratio_min=0.5, aspect_ratio_max=2.0,
        ceiling_height=2700
    ),
    "hallway": RoomTypeDefaults(
        area_min=2.0, area_max=8.0,
        default_features=[],
        default_adjacencies=[],
        aspect_ratio_min=0.2, aspect_ratio_max=0.5,
        ceiling_height=2700
    ),
    "closet": RoomTypeDefaults(
        area_min=1.0, area_max=4.0,
        default_features=["shelving", "rod"],
        default_adjacencies=[],
        aspect_ratio_min=0.3, aspect_ratio_max=3.0,
        ceiling_height=2700
    ),
    "walk_in_closet": RoomTypeDefaults(
        area_min=3.0, area_max=9.0,
        default_features=["shelving", "rod", "island"],
        default_adjacencies=[],
        aspect_ratio_min=0.5, aspect_ratio_max=2.0,
        ceiling_height=2700
    ),
    "pantry": RoomTypeDefaults(
        area_min=1.5, area_max=5.0,
        default_features=["shelving"],
        default_adjacencies=[("kitchen", "required")],
        aspect_ratio_min=0.3, aspect_ratio_max=3.0,
        ceiling_height=2700
    ),
}


# =============================================================================
# Furniture Dimensions (mm)
# =============================================================================

@dataclass
class FurnitureDimensions:
    """Furniture dimensions and clearances in mm."""
    width: int
    length: int
    clearance_front: int
    clearance_back: int
    clearance_left: int
    clearance_right: int

    @property
    def footprint(self) -> float:
        """Return footprint in m²."""
        return (self.width * self.length) / 1_000_000

    @property
    def total_footprint(self) -> float:
        """Return footprint including clearances in m²."""
        total_width = self.width + self.clearance_left + self.clearance_right
        total_length = self.length + self.clearance_front + self.clearance_back
        return (total_width * total_length) / 1_000_000


FURNITURE_DEFAULTS: Dict[str, FurnitureDimensions] = {
    # Beds
    "twin_bed": FurnitureDimensions(965, 1905, 900, 0, 900, 900),
    "full_bed": FurnitureDimensions(1370, 1905, 900, 0, 900, 900),
    "queen_bed": FurnitureDimensions(1525, 2030, 900, 0, 900, 900),
    "king_bed": FurnitureDimensions(1930, 2030, 900, 0, 900, 900),

    # Seating
    "sofa_2seat": FurnitureDimensions(1525, 915, 900, 0, 0, 0),
    "sofa_3seat": FurnitureDimensions(2135, 915, 900, 0, 0, 0),
    "sectional": FurnitureDimensions(3050, 2440, 900, 0, 0, 0),
    "armchair": FurnitureDimensions(900, 900, 600, 0, 0, 0),

    # Dining
    "dining_4": FurnitureDimensions(1220, 915, 900, 900, 900, 900),
    "dining_6": FurnitureDimensions(1830, 915, 900, 900, 900, 900),
    "dining_8": FurnitureDimensions(2440, 1065, 900, 900, 900, 900),

    # Office
    "desk": FurnitureDimensions(1525, 760, 900, 0, 600, 600),
    "office_chair": FurnitureDimensions(600, 600, 0, 0, 0, 0),

    # Bedroom
    "dresser": FurnitureDimensions(1525, 510, 900, 0, 0, 0),
    "nightstand": FurnitureDimensions(600, 450, 0, 0, 0, 0),

    # Bathroom
    "toilet": FurnitureDimensions(510, 760, 600, 0, 450, 450),
    "vanity_single": FurnitureDimensions(915, 560, 760, 0, 0, 0),
    "vanity_double": FurnitureDimensions(1525, 560, 760, 0, 0, 0),
    "tub": FurnitureDimensions(815, 1525, 760, 0, 0, 0),
    "shower": FurnitureDimensions(915, 915, 760, 0, 0, 0),
    "shower_large": FurnitureDimensions(1220, 1220, 760, 0, 0, 0),

    # Kitchen
    "fridge": FurnitureDimensions(915, 760, 900, 0, 0, 0),
    "stove": FurnitureDimensions(760, 660, 900, 0, 0, 0),
    "dishwasher": FurnitureDimensions(610, 610, 0, 0, 0, 0),
    "kitchen_island": FurnitureDimensions(1830, 915, 900, 900, 900, 900),

    # Laundry
    "washer": FurnitureDimensions(685, 760, 600, 0, 0, 0),
    "dryer": FurnitureDimensions(685, 760, 600, 0, 0, 0),
}


# =============================================================================
# Opening Dimensions (mm)
# =============================================================================

@dataclass
class OpeningDimensions:
    """Door or window dimensions."""
    width: int
    height: int


DOOR_DEFAULTS: Dict[str, OpeningDimensions] = {
    "standard": OpeningDimensions(914, 2134),  # 36" x 84"
    "entry": OpeningDimensions(914, 2134),
    "double_entry": OpeningDimensions(1524, 2134),  # 60" x 84"
    "interior": OpeningDimensions(762, 2032),  # 30" x 80"
    "closet": OpeningDimensions(610, 2032),  # 24" x 80"
    "pocket": OpeningDimensions(762, 2032),
    "sliding": OpeningDimensions(1524, 2032),
    "garage_single": OpeningDimensions(2743, 2134),  # 9' x 7'
    "garage_double": OpeningDimensions(4877, 2134),  # 16' x 7'
}

WINDOW_DEFAULTS: Dict[str, OpeningDimensions] = {
    "standard": OpeningDimensions(1200, 1200),
    "small": OpeningDimensions(600, 600),
    "large": OpeningDimensions(1800, 1500),
    "picture": OpeningDimensions(2400, 1800),
    "sliding": OpeningDimensions(1800, 1200),
    "casement": OpeningDimensions(600, 1200),
    "bathroom": OpeningDimensions(600, 450),
}

WINDOW_SILL_HEIGHT = 900  # mm from floor


# =============================================================================
# Building Constraints
# =============================================================================

@dataclass
class BuildingConstraintDefaults:
    """Default building constraints."""
    stories_max: int = 2
    ceiling_height: int = 2700  # mm (9')
    wall_thickness_exterior: int = 170  # mm (2x6 + sheathing + drywall)
    wall_thickness_interior: int = 115  # mm (2x4 + drywall)
    min_room_width: int = 2400  # mm (8')
    min_hallway_width: int = 900  # mm (3')
    min_door_clearance: int = 450  # mm from corner


BUILDING_DEFAULTS = BuildingConstraintDefaults()


# =============================================================================
# Circulation Factors
# =============================================================================

CIRCULATION_FACTORS = {
    "open_plan_high": 1.10,  # Minimal hallways
    "balanced": 1.15,
    "defined_rooms_high": 1.20,  # More hallways
}


# =============================================================================
# Priority Defaults
# =============================================================================

PRIORITY_DEFAULTS = {
    "natural_light": 5,
    "privacy": 5,
    "open_plan": 5,
    "circulation_efficiency": 5,
    "outdoor_connection": 5,
    "views": 5,
    "minimize_hallways": 5,
    "compact_footprint": 5,
}


# =============================================================================
# Regional Defaults
# =============================================================================

REGIONAL_DEFAULTS = {
    "canada": {
        "units": "metric",
        "setbacks": {"front": 7500, "rear": 6000, "left": 1500, "right": 1500},
        "ceiling_height": 2440,
    },
    "us": {
        "units": "imperial",
        "setbacks": {"front": 7500, "rear": 6000, "left": 1500, "right": 1500},
        "ceiling_height": 2440,
    },
    "europe": {
        "units": "metric",
        "setbacks": {"front": 5000, "rear": 5000, "left": 3000, "right": 3000},
        "ceiling_height": 2500,
    },
}


# =============================================================================
# Helper Functions
# =============================================================================

def get_room_defaults(room_type: str) -> RoomTypeDefaults:
    """Get defaults for a room type."""
    return ROOM_DEFAULTS.get(room_type, ROOM_DEFAULTS["bedroom"])


def get_furniture_dimensions(furniture_type: str) -> FurnitureDimensions:
    """Get dimensions for a furniture type."""
    return FURNITURE_DEFAULTS.get(furniture_type)


def get_door_dimensions(door_type: str = "standard") -> OpeningDimensions:
    """Get dimensions for a door type."""
    return DOOR_DEFAULTS.get(door_type, DOOR_DEFAULTS["standard"])


def get_window_dimensions(window_type: str = "standard") -> OpeningDimensions:
    """Get dimensions for a window type."""
    return WINDOW_DEFAULTS.get(window_type, WINDOW_DEFAULTS["standard"])


def sqft_to_sqm(sqft: float) -> float:
    """Convert square feet to square meters."""
    return sqft * 0.092903


def sqm_to_sqft(sqm: float) -> float:
    """Convert square meters to square feet."""
    return sqm / 0.092903


def mm_to_m(mm: float) -> float:
    """Convert millimeters to meters."""
    return mm / 1000


def m_to_mm(m: float) -> float:
    """Convert meters to millimeters."""
    return m * 1000
