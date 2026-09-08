#!/usr/bin/env python3
"""
wall_types.py - Standard wall type definitions for architectural generation

Provides comprehensive wall assembly definitions including:
- Exterior walls (2x4, 2x6 with various insulation)
- Interior walls (standard, soundproofed)
- Wet walls (plumbing walls)
- Fire-rated walls
- Specialty walls (garage, basement)

All dimensions in millimeters.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional
from enum import Enum


class LayerFunction(Enum):
    """Material layer functions in wall assembly."""
    EXTERIOR_FINISH = "exterior_finish"
    AIR_BARRIER = "air_barrier"
    SHEATHING = "sheathing"
    STRUCTURE = "structure"
    INSULATION = "insulation"
    VAPOR_BARRIER = "vapor_barrier"
    INTERIOR_FINISH = "interior_finish"
    FIRE_RATING = "fire_rating"


class WallCategory(Enum):
    """Wall category classifications."""
    EXTERIOR = "exterior"
    INTERIOR = "interior"
    WET_WALL = "wet_wall"
    FIRE_RATED = "fire_rated"
    GARAGE = "garage"
    BASEMENT = "basement"


@dataclass
class WallLayer:
    """Individual layer in a wall assembly."""
    name: str
    thickness: float  # mm
    material: str
    function: LayerFunction
    r_value: float = 0.0  # R-value per inch
    fire_rating: int = 0  # minutes

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "thickness": self.thickness,
            "material": self.material,
            "function": self.function.value,
            "r_value": self.r_value,
            "fire_rating": self.fire_rating
        }


@dataclass
class WallType:
    """Complete wall type definition."""
    id: str
    name: str
    category: WallCategory
    layers: List[WallLayer]
    description: str = ""
    fire_rating: int = 0  # Total fire rating in minutes

    @property
    def total_thickness(self) -> float:
        """Calculate total wall thickness from layers."""
        return sum(layer.thickness for layer in self.layers)

    @property
    def total_r_value(self) -> float:
        """Calculate total R-value from layers."""
        return sum(layer.r_value * (layer.thickness / 25.4) for layer in self.layers)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category.value,
            "layers": [layer.to_dict() for layer in self.layers],
            "total_thickness": self.total_thickness,
            "total_r_value": self.total_r_value,
            "fire_rating": self.fire_rating,
            "description": self.description
        }


# =============================================================================
# STANDARD WALL TYPE DEFINITIONS
# =============================================================================

# Exterior Walls
EXT_2X4_R13 = WallType(
    id="ext_2x4_r13",
    name="Exterior 2x4 R-13",
    category=WallCategory.EXTERIOR,
    description="Standard 2x4 exterior wall with R-13 batt insulation",
    layers=[
        WallLayer("Lap Siding", 20, "fiber_cement", LayerFunction.EXTERIOR_FINISH),
        WallLayer("House Wrap", 1, "tyvek", LayerFunction.AIR_BARRIER),
        WallLayer("OSB Sheathing", 12, "osb", LayerFunction.SHEATHING, r_value=0.62),
        WallLayer("2x4 Stud Cavity", 89, "wood_frame", LayerFunction.STRUCTURE),
        WallLayer("R-13 Batt", 89, "fiberglass", LayerFunction.INSULATION, r_value=3.7),
        WallLayer("6mil Poly", 0.15, "polyethylene", LayerFunction.VAPOR_BARRIER),
        WallLayer("1/2\" Gypsum", 13, "gypsum", LayerFunction.INTERIOR_FINISH, fire_rating=30),
    ]
)

EXT_2X6_R21 = WallType(
    id="ext_2x6_r21",
    name="Exterior 2x6 R-21",
    category=WallCategory.EXTERIOR,
    description="Energy-efficient 2x6 exterior wall with R-21 batt insulation",
    layers=[
        WallLayer("Lap Siding", 20, "fiber_cement", LayerFunction.EXTERIOR_FINISH),
        WallLayer("House Wrap", 1, "tyvek", LayerFunction.AIR_BARRIER),
        WallLayer("OSB Sheathing", 12, "osb", LayerFunction.SHEATHING, r_value=0.62),
        WallLayer("2x6 Stud Cavity", 140, "wood_frame", LayerFunction.STRUCTURE),
        WallLayer("R-21 Batt", 140, "fiberglass", LayerFunction.INSULATION, r_value=3.8),
        WallLayer("6mil Poly", 0.15, "polyethylene", LayerFunction.VAPOR_BARRIER),
        WallLayer("5/8\" Gypsum", 16, "gypsum", LayerFunction.INTERIOR_FINISH, fire_rating=45),
    ]
)

EXT_2X6_R21_FOAM = WallType(
    id="ext_2x6_r21_foam",
    name="Exterior 2x6 R-21 + Foam",
    category=WallCategory.EXTERIOR,
    description="High-performance 2x6 wall with continuous exterior insulation",
    layers=[
        WallLayer("Lap Siding", 20, "fiber_cement", LayerFunction.EXTERIOR_FINISH),
        WallLayer("1\" Rainscreen", 25, "wood_furring", LayerFunction.AIR_BARRIER),
        WallLayer("2\" Rigid Foam", 51, "xps", LayerFunction.INSULATION, r_value=5.0),
        WallLayer("House Wrap", 1, "tyvek", LayerFunction.AIR_BARRIER),
        WallLayer("OSB Sheathing", 12, "osb", LayerFunction.SHEATHING, r_value=0.62),
        WallLayer("2x6 Stud Cavity", 140, "wood_frame", LayerFunction.STRUCTURE),
        WallLayer("R-21 Batt", 140, "fiberglass", LayerFunction.INSULATION, r_value=3.8),
        WallLayer("Smart Vapor Retarder", 0.5, "membrain", LayerFunction.VAPOR_BARRIER),
        WallLayer("5/8\" Gypsum", 16, "gypsum", LayerFunction.INTERIOR_FINISH, fire_rating=45),
    ]
)

EXT_BRICK_2X4 = WallType(
    id="ext_brick_2x4",
    name="Brick Veneer 2x4",
    category=WallCategory.EXTERIOR,
    description="Traditional brick veneer with 2x4 backup wall",
    layers=[
        WallLayer("Brick Veneer", 90, "brick", LayerFunction.EXTERIOR_FINISH),
        WallLayer("1\" Air Gap", 25, "air", LayerFunction.AIR_BARRIER),
        WallLayer("House Wrap", 1, "tyvek", LayerFunction.AIR_BARRIER),
        WallLayer("OSB Sheathing", 12, "osb", LayerFunction.SHEATHING, r_value=0.62),
        WallLayer("2x4 Stud Cavity", 89, "wood_frame", LayerFunction.STRUCTURE),
        WallLayer("R-13 Batt", 89, "fiberglass", LayerFunction.INSULATION, r_value=3.7),
        WallLayer("6mil Poly", 0.15, "polyethylene", LayerFunction.VAPOR_BARRIER),
        WallLayer("1/2\" Gypsum", 13, "gypsum", LayerFunction.INTERIOR_FINISH, fire_rating=30),
    ]
)

EXT_STUCCO_2X6 = WallType(
    id="ext_stucco_2x6",
    name="Stucco 2x6",
    category=WallCategory.EXTERIOR,
    description="Three-coat stucco system with 2x6 wall",
    layers=[
        WallLayer("3-Coat Stucco", 22, "stucco", LayerFunction.EXTERIOR_FINISH),
        WallLayer("Metal Lath", 2, "galvanized_steel", LayerFunction.EXTERIOR_FINISH),
        WallLayer("2 Layers Paper", 1, "building_paper", LayerFunction.AIR_BARRIER),
        WallLayer("OSB Sheathing", 12, "osb", LayerFunction.SHEATHING, r_value=0.62),
        WallLayer("2x6 Stud Cavity", 140, "wood_frame", LayerFunction.STRUCTURE),
        WallLayer("R-21 Batt", 140, "fiberglass", LayerFunction.INSULATION, r_value=3.8),
        WallLayer("6mil Poly", 0.15, "polyethylene", LayerFunction.VAPOR_BARRIER),
        WallLayer("5/8\" Gypsum", 16, "gypsum", LayerFunction.INTERIOR_FINISH, fire_rating=45),
    ]
)

# Interior Walls
INT_2X4 = WallType(
    id="int_2x4",
    name="Interior 2x4",
    category=WallCategory.INTERIOR,
    description="Standard interior partition wall",
    layers=[
        WallLayer("1/2\" Gypsum", 13, "gypsum", LayerFunction.INTERIOR_FINISH, fire_rating=30),
        WallLayer("2x4 Stud Cavity", 89, "wood_frame", LayerFunction.STRUCTURE),
        WallLayer("1/2\" Gypsum", 13, "gypsum", LayerFunction.INTERIOR_FINISH, fire_rating=30),
    ]
)

INT_2X4_INSULATED = WallType(
    id="int_2x4_insulated",
    name="Interior 2x4 Insulated",
    category=WallCategory.INTERIOR,
    description="Sound-dampening interior wall with insulation",
    layers=[
        WallLayer("1/2\" Gypsum", 13, "gypsum", LayerFunction.INTERIOR_FINISH, fire_rating=30),
        WallLayer("2x4 Stud Cavity", 89, "wood_frame", LayerFunction.STRUCTURE),
        WallLayer("R-13 Sound Batt", 89, "mineral_wool", LayerFunction.INSULATION, r_value=3.7),
        WallLayer("1/2\" Gypsum", 13, "gypsum", LayerFunction.INTERIOR_FINISH, fire_rating=30),
    ]
)

INT_2X6 = WallType(
    id="int_2x6",
    name="Interior 2x6",
    category=WallCategory.INTERIOR,
    description="Thicker interior wall for utilities or sound control",
    layers=[
        WallLayer("1/2\" Gypsum", 13, "gypsum", LayerFunction.INTERIOR_FINISH, fire_rating=30),
        WallLayer("2x6 Stud Cavity", 140, "wood_frame", LayerFunction.STRUCTURE),
        WallLayer("1/2\" Gypsum", 13, "gypsum", LayerFunction.INTERIOR_FINISH, fire_rating=30),
    ]
)

# Wet Walls (Plumbing)
WET_2X6 = WallType(
    id="wet_2x6",
    name="Plumbing Wall 2x6",
    category=WallCategory.WET_WALL,
    description="2x6 wall for plumbing runs (3\" DWV clearance)",
    layers=[
        WallLayer("1/2\" Gypsum", 13, "gypsum", LayerFunction.INTERIOR_FINISH, fire_rating=30),
        WallLayer("2x6 Stud Cavity", 140, "wood_frame", LayerFunction.STRUCTURE),
        WallLayer("1/2\" Gypsum", 13, "gypsum", LayerFunction.INTERIOR_FINISH, fire_rating=30),
    ]
)

WET_2X8 = WallType(
    id="wet_2x8",
    name="Plumbing Wall 2x8",
    category=WallCategory.WET_WALL,
    description="2x8 wall for larger plumbing runs (4\" DWV clearance)",
    layers=[
        WallLayer("1/2\" Gypsum", 13, "gypsum", LayerFunction.INTERIOR_FINISH, fire_rating=30),
        WallLayer("2x8 Stud Cavity", 184, "wood_frame", LayerFunction.STRUCTURE),
        WallLayer("1/2\" Gypsum", 13, "gypsum", LayerFunction.INTERIOR_FINISH, fire_rating=30),
    ]
)

# Fire-Rated Walls
FIRE_1HR = WallType(
    id="fire_1hr",
    name="1-Hour Fire Wall",
    category=WallCategory.FIRE_RATED,
    description="1-hour fire-rated wall assembly",
    fire_rating=60,
    layers=[
        WallLayer("5/8\" Type X Gypsum", 16, "gypsum_type_x", LayerFunction.INTERIOR_FINISH, fire_rating=60),
        WallLayer("2x4 Stud Cavity", 89, "wood_frame", LayerFunction.STRUCTURE),
        WallLayer("R-13 Mineral Wool", 89, "mineral_wool", LayerFunction.INSULATION, r_value=3.7),
        WallLayer("5/8\" Type X Gypsum", 16, "gypsum_type_x", LayerFunction.INTERIOR_FINISH, fire_rating=60),
    ]
)

FIRE_2HR = WallType(
    id="fire_2hr",
    name="2-Hour Fire Wall",
    category=WallCategory.FIRE_RATED,
    description="2-hour fire-rated wall assembly (double layer each side)",
    fire_rating=120,
    layers=[
        WallLayer("5/8\" Type X Gypsum", 16, "gypsum_type_x", LayerFunction.INTERIOR_FINISH, fire_rating=60),
        WallLayer("5/8\" Type X Gypsum", 16, "gypsum_type_x", LayerFunction.FIRE_RATING, fire_rating=60),
        WallLayer("2x4 Stud Cavity", 89, "wood_frame", LayerFunction.STRUCTURE),
        WallLayer("R-13 Mineral Wool", 89, "mineral_wool", LayerFunction.INSULATION, r_value=3.7),
        WallLayer("5/8\" Type X Gypsum", 16, "gypsum_type_x", LayerFunction.FIRE_RATING, fire_rating=60),
        WallLayer("5/8\" Type X Gypsum", 16, "gypsum_type_x", LayerFunction.INTERIOR_FINISH, fire_rating=60),
    ]
)

# Garage Walls
GARAGE_EXT = WallType(
    id="garage_ext",
    name="Garage Exterior",
    category=WallCategory.GARAGE,
    description="Exterior wall for attached garage",
    layers=[
        WallLayer("Lap Siding", 20, "fiber_cement", LayerFunction.EXTERIOR_FINISH),
        WallLayer("House Wrap", 1, "tyvek", LayerFunction.AIR_BARRIER),
        WallLayer("OSB Sheathing", 12, "osb", LayerFunction.SHEATHING, r_value=0.62),
        WallLayer("2x4 Stud Cavity", 89, "wood_frame", LayerFunction.STRUCTURE),
        WallLayer("No Insulation", 89, "air", LayerFunction.STRUCTURE),
        WallLayer("1/2\" Gypsum", 13, "gypsum", LayerFunction.INTERIOR_FINISH, fire_rating=30),
    ]
)

GARAGE_TO_HOUSE = WallType(
    id="garage_to_house",
    name="Garage to House Fire Wall",
    category=WallCategory.GARAGE,
    description="Fire-rated wall between garage and living space",
    fire_rating=60,
    layers=[
        WallLayer("5/8\" Type X Gypsum", 16, "gypsum_type_x", LayerFunction.FIRE_RATING, fire_rating=60),
        WallLayer("2x4 Stud Cavity", 89, "wood_frame", LayerFunction.STRUCTURE),
        WallLayer("R-13 Batt", 89, "fiberglass", LayerFunction.INSULATION, r_value=3.7),
        WallLayer("6mil Poly", 0.15, "polyethylene", LayerFunction.VAPOR_BARRIER),
        WallLayer("1/2\" Gypsum", 13, "gypsum", LayerFunction.INTERIOR_FINISH, fire_rating=30),
    ]
)

# Basement Walls
BASEMENT_FRAMED = WallType(
    id="basement_framed",
    name="Basement Framed Wall",
    category=WallCategory.BASEMENT,
    description="Framed wall against basement concrete",
    layers=[
        WallLayer("Concrete Foundation", 200, "concrete", LayerFunction.STRUCTURE),
        WallLayer("2\" XPS Foam", 51, "xps", LayerFunction.INSULATION, r_value=5.0),
        WallLayer("2x4 Stud Cavity", 89, "wood_frame", LayerFunction.STRUCTURE),
        WallLayer("R-13 Batt", 89, "fiberglass", LayerFunction.INSULATION, r_value=3.7),
        WallLayer("6mil Poly", 0.15, "polyethylene", LayerFunction.VAPOR_BARRIER),
        WallLayer("1/2\" Gypsum", 13, "gypsum", LayerFunction.INTERIOR_FINISH, fire_rating=30),
    ]
)


# =============================================================================
# WALL TYPE REGISTRY
# =============================================================================

WALL_TYPES: Dict[str, WallType] = {
    # Exterior
    "ext_2x4_r13": EXT_2X4_R13,
    "ext_2x6_r21": EXT_2X6_R21,
    "ext_2x6_r21_foam": EXT_2X6_R21_FOAM,
    "ext_brick_2x4": EXT_BRICK_2X4,
    "ext_stucco_2x6": EXT_STUCCO_2X6,
    # Interior
    "int_2x4": INT_2X4,
    "int_2x4_insulated": INT_2X4_INSULATED,
    "int_2x6": INT_2X6,
    # Wet walls
    "wet_2x6": WET_2X6,
    "wet_2x8": WET_2X8,
    # Fire-rated
    "fire_1hr": FIRE_1HR,
    "fire_2hr": FIRE_2HR,
    # Garage
    "garage_ext": GARAGE_EXT,
    "garage_to_house": GARAGE_TO_HOUSE,
    # Basement
    "basement_framed": BASEMENT_FRAMED,
}


def get_wall_type(type_id: str) -> Optional[WallType]:
    """Get a wall type by ID."""
    return WALL_TYPES.get(type_id)


def get_wall_types_for_category(category: WallCategory) -> List[WallType]:
    """Get all wall types for a given category."""
    return [wt for wt in WALL_TYPES.values() if wt.category == category]


def get_all_wall_types() -> List[WallType]:
    """Get all defined wall types."""
    return list(WALL_TYPES.values())


def get_wall_types_as_json() -> List[dict]:
    """Get all wall types as JSON-serializable list."""
    return [wt.to_dict() for wt in WALL_TYPES.values()]


def get_default_wall_type(category: str) -> WallType:
    """Get default wall type for a category string."""
    category_map = {
        "exterior": EXT_2X6_R21,
        "interior": INT_2X4,
        "wet_wall": WET_2X6,
        "fire_rated": FIRE_1HR,
        "garage": GARAGE_EXT,
        "basement": BASEMENT_FRAMED,
    }
    return category_map.get(category, INT_2X4)


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def calculate_wall_cost_per_sqft(wall_type: WallType) -> float:
    """Estimate material cost per square foot of wall."""
    # Rough cost estimates per material type (USD/sqft)
    material_costs = {
        "fiber_cement": 3.50,
        "brick": 12.00,
        "stucco": 8.00,
        "tyvek": 0.20,
        "osb": 0.80,
        "xps": 1.50,
        "fiberglass": 0.50,
        "mineral_wool": 1.00,
        "gypsum": 0.75,
        "gypsum_type_x": 0.90,
        "wood_frame": 2.00,
        "polyethylene": 0.10,
        "air": 0.0,
    }

    total_cost = 0.0
    for layer in wall_type.layers:
        # Scale cost by thickness relative to "standard"
        cost = material_costs.get(layer.material, 1.0)
        total_cost += cost

    return total_cost


def print_wall_type_summary(wall_type: WallType):
    """Print a formatted summary of a wall type."""
    print(f"\n{'='*60}")
    print(f"Wall Type: {wall_type.name} ({wall_type.id})")
    print(f"Category: {wall_type.category.value}")
    print(f"Description: {wall_type.description}")
    print(f"{'='*60}")
    print(f"{'Layer':<25} {'Thickness':>10} {'Material':<20}")
    print(f"{'-'*60}")

    for layer in wall_type.layers:
        print(f"{layer.name:<25} {layer.thickness:>8.1f}mm {layer.material:<20}")

    print(f"{'-'*60}")
    print(f"{'TOTAL THICKNESS':<25} {wall_type.total_thickness:>8.1f}mm")
    print(f"{'TOTAL R-VALUE':<25} {wall_type.total_r_value:>8.1f}")
    if wall_type.fire_rating > 0:
        print(f"{'FIRE RATING':<25} {wall_type.fire_rating:>8} min")


if __name__ == "__main__":
    # Print all wall types
    print("ARCHENGINE WALL TYPE LIBRARY")
    print("="*60)

    for category in WallCategory:
        walls = get_wall_types_for_category(category)
        if walls:
            print(f"\n{category.value.upper()} WALLS:")
            for wt in walls:
                print(f"  - {wt.id}: {wt.name} ({wt.total_thickness:.0f}mm, R-{wt.total_r_value:.1f})")

    # Print detailed info for one example
    print_wall_type_summary(EXT_2X6_R21)
