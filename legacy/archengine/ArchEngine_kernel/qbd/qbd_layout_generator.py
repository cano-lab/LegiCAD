"""
QBD Layout Generator
====================
Converts QBD answers into a relationship-based floor plan.

Flow:
1. QBD answers → SpatialGraph (relationships)
2. SpatialGraph → PlacedLayout (coordinates)
3. PlacedLayout → Output format (Revit or ArchEngine)

Supports multiple output formats:
- REVIT: Feet, Revit wall type variables
- ARCHENGINE: Millimeters for UE5 viewer (auto-converts to cm)
"""

import math
from enum import Enum
from typing import Dict, List, Any, Optional

from room_relationships import SpatialGraph, Zone, OpeningType, ROOM_TYPES
from wall_graph import LayoutSpec, WallType
from coordinate_solver import solve_layout, PlacedLayout, WallCoordinate


# =============================================================================
# OUTPUT FORMAT
# =============================================================================

class OutputFormat(Enum):
    """Output format for generated layouts."""
    REVIT = "revit"           # Feet, Revit wall type variables
    ARCHENGINE = "archengine" # mm for UE5 viewer (converts to cm internally)


# Unit conversion constants
FEET_TO_MM = 304.8  # 1 foot = 304.8 mm
FEET_TO_CM = 30.48  # 1 foot = 30.48 cm


# =============================================================================
# QBD ANSWERS → SPATIAL GRAPH
# =============================================================================

def create_spatial_graph_from_qbd(answers: Dict) -> SpatialGraph:
    """
    Create a SpatialGraph from QBD answers.

    Args:
        answers: Dict of QBD answers (bedrooms, bathrooms, sqft, garage, etc.)

    Returns:
        SpatialGraph with rooms and relationships defined
    """
    graph = SpatialGraph()

    # Parse answers - handle both string and int/float inputs
    sqft_val = answers.get("sqft", answers.get("com_sqft", answers.get("mixed_sqft", 1200)))
    sqft = int(sqft_val) if isinstance(sqft_val, (int, float)) else int(sqft_val)

    bedrooms_val = answers.get("bedrooms", 2)
    bedrooms = int(bedrooms_val) if isinstance(bedrooms_val, (int, float)) else int(str(bedrooms_val).replace("+", ""))

    bathrooms_val = answers.get("bathrooms", 1)
    bathrooms = int(float(bathrooms_val)) if isinstance(bathrooms_val, (int, float)) else int(float(str(bathrooms_val).replace("+", "")))

    garage = answers.get("garage", "none")
    special_rooms = answers.get("special_rooms", [])
    if isinstance(special_rooms, str):
        special_rooms = [special_rooms]
    style = answers.get("style", "modern")

    # Determine if open concept based on style
    open_concept = style in ["modern", "contemporary", "minimal"]

    # =========================================================================
    # ADD ROOMS
    # =========================================================================

    # Entry (always present)
    graph.add_room("entry", "entry", min_area=max(40, int(sqft * 0.03)))

    # Public zone
    graph.add_room("living", "living", min_area=max(180, int(sqft * 0.18)))
    graph.add_room("kitchen", "kitchen", min_area=max(100, int(sqft * 0.10)))

    if sqft > 800:
        graph.add_room("dining", "dining", min_area=max(100, int(sqft * 0.08)))

    # Hallway (if multiple bedrooms)
    if bedrooms > 1:
        graph.add_room("hallway", "hallway", min_area=max(50, int(sqft * 0.04)))

    # Primary bedroom suite
    if bedrooms > 0:
        graph.add_room("primary_bedroom", "primary_bedroom",
                      min_area=max(150, int(sqft * 0.14)))
        graph.add_room("primary_bath", "primary_bath",
                      min_area=max(60, int(sqft * 0.05)))
        graph.add_room("primary_closet", "walk_in_closet",
                      min_area=max(30, int(sqft * 0.025)))

    # Additional bedrooms
    for i in range(2, bedrooms + 1):
        graph.add_room(f"bedroom_{i}", "bedroom",
                      name=f"Bedroom {i}",
                      min_area=max(120, int(sqft * 0.10)))
        graph.add_room(f"closet_{i}", "closet",
                      name=f"Closet {i}",
                      min_area=max(15, int(sqft * 0.015)))

    # Additional bathrooms
    if bathrooms > 1:
        graph.add_room("bathroom_2", "bathroom",
                      name="Bathroom 2",
                      min_area=max(45, int(sqft * 0.035)))

    if bathrooms > 2:
        # Powder room near entry
        graph.add_room("powder_room", "powder_room",
                      min_area=max(25, int(sqft * 0.02)))

    # Laundry
    graph.add_room("laundry", "laundry", min_area=max(35, int(sqft * 0.025)))

    # Garage + mudroom
    if garage != "none":
        garage_area = {"1car": 220, "2car": 440, "3car": 660}.get(garage, 440)
        graph.add_room("garage", "garage", min_area=garage_area)
        graph.add_room("mudroom", "mudroom", min_area=max(40, int(sqft * 0.03)))

    # Special rooms
    if "office" in special_rooms:
        graph.add_room("office", "office", min_area=max(100, int(sqft * 0.06)))

    if "mudroom" in special_rooms and garage == "none":
        graph.add_room("mudroom", "mudroom", min_area=max(40, int(sqft * 0.03)))

    if "pantry" in special_rooms:
        graph.add_room("pantry", "pantry", min_area=max(25, int(sqft * 0.02)))

    # =========================================================================
    # DEFINE RELATIONSHIPS
    # =========================================================================

    # Entry connections
    graph.connect("entry", "living")

    # Public zone relationships
    if open_concept:
        if "dining" in graph.rooms:
            graph.open_to("living", "dining")
            graph.open_to("dining", "kitchen")
        else:
            graph.open_to("living", "kitchen")
    else:
        if "dining" in graph.rooms:
            graph.connect("living", "dining", OpeningType.CASED_OPENING)
            graph.connect("dining", "kitchen")
        else:
            graph.connect("living", "kitchen")

    # Hallway connections
    if "hallway" in graph.rooms:
        graph.connect("living", "hallway")

        # Connect bedrooms to hallway
        graph.connect("hallway", "primary_bedroom")
        for i in range(2, bedrooms + 1):
            graph.connect("hallway", f"bedroom_{i}")

        # Connect bathroom to hallway
        if "bathroom_2" in graph.rooms:
            graph.connect("hallway", "bathroom_2")

        # Laundry often off hallway
        graph.connect("hallway", "laundry")

    else:
        # Single bedroom - connect directly to living
        if "primary_bedroom" in graph.rooms:
            graph.connect("living", "primary_bedroom")
        graph.connect("living", "laundry")

    # Primary suite connections
    if "primary_bedroom" in graph.rooms:
        graph.attached("primary_bedroom", "primary_bath")
        graph.attached("primary_bedroom", "primary_closet")

    # Secondary bedroom closets
    for i in range(2, bedrooms + 1):
        graph.attached(f"bedroom_{i}", f"closet_{i}")

    # Powder room near entry
    if "powder_room" in graph.rooms:
        graph.connect("entry", "powder_room")

    # Garage + mudroom connections
    if "garage" in graph.rooms:
        graph.connect("garage", "mudroom")
        graph.connect("mudroom", "kitchen")

        # Isolate garage from bedrooms (noise, fumes)
        if "primary_bedroom" in graph.rooms:
            graph.isolate("garage", "primary_bedroom")
        for i in range(2, bedrooms + 1):
            graph.isolate("garage", f"bedroom_{i}")

    # Pantry connected to kitchen
    if "pantry" in graph.rooms:
        graph.connect("kitchen", "pantry")

    # Office
    if "office" in graph.rooms:
        if "hallway" in graph.rooms:
            graph.connect("hallway", "office")
        else:
            graph.connect("living", "office")

    # =========================================================================
    # GROUPINGS (for plumbing efficiency)
    # =========================================================================

    wet_rooms = ["kitchen", "laundry"]
    if "primary_bath" in graph.rooms:
        wet_rooms.append("primary_bath")
    if "bathroom_2" in graph.rooms:
        wet_rooms.append("bathroom_2")
    if "powder_room" in graph.rooms:
        wet_rooms.append("powder_room")

    if len(wet_rooms) >= 2:
        graph.group(*wet_rooms)

    return graph


# =============================================================================
# PLACED LAYOUT → OUTPUT FORMAT
# =============================================================================

def layout_to_walls(layout: PlacedLayout,
                   output_format: OutputFormat = OutputFormat.REVIT,
                   level_name: str = "Level 1",
                   wall_height: float = 10.0,
                   exterior_wall_type: str = None,
                   interior_wall_type: str = None,
                   wet_wall_type: str = None) -> List[Dict]:
    """
    Convert a PlacedLayout to wall definitions.

    Args:
        layout: PlacedLayout from coordinate solver
        output_format: Target output format (REVIT or ARCHENGINE)
        level_name: Level name
        wall_height: Wall height in feet (converted for ArchEngine)
        exterior_wall_type: Wall type for exterior walls
        interior_wall_type: Wall type for interior walls
        wet_wall_type: Wall type for wet walls (plumbing)

    Returns:
        List of wall dicts
    """
    walls_batch = []

    # Unit conversion factor
    unit_scale = FEET_TO_MM if output_format == OutputFormat.ARCHENGINE else 1.0

    for idx, wall in enumerate(layout.walls):
        # Skip open walls (no physical wall)
        if wall.wall_type == WallType.NONE:
            continue

        # Determine wall type and category
        if wall.wall_type == WallType.EXTERIOR:
            category = "exterior"
            if output_format == OutputFormat.REVIT:
                type_str = exterior_wall_type or "${default_exterior_wall_type}"
            else:
                type_str = "ext_2x6_r21"  # ArchEngine wall type ID
        elif wall.wall_type == WallType.WET:
            category = "wet_wall"
            if output_format == OutputFormat.REVIT:
                type_str = wet_wall_type or "${default_wet_wall_type}"
            else:
                type_str = "wet_2x6"  # ArchEngine wall type ID
        else:
            category = "interior"
            if output_format == OutputFormat.REVIT:
                type_str = interior_wall_type or "${default_interior_wall_type}"
            else:
                type_str = "int_2x4"  # ArchEngine wall type ID

        # Convert coordinates
        start_x = wall.start.x * unit_scale
        start_y = wall.start.y * unit_scale
        end_x = wall.end.x * unit_scale
        end_y = wall.end.y * unit_scale
        height = wall_height * unit_scale

        wall_dict = {
            "start": [start_x, 0, start_y],  # [x, y, z] - y is up in ArchEngine
            "end": [end_x, 0, end_y],
            "height": height,
            "wall_type": type_str,
            "level_name": level_name,
            "category": category,
            "rooms": [wall.room1, wall.room2]
        }

        # Add wall index for ArchEngine door/window references
        if output_format == OutputFormat.ARCHENGINE:
            wall_dict["wall_index"] = idx

        walls_batch.append(wall_dict)

    return walls_batch


# Keep backwards-compatible alias
def layout_to_revit_walls(layout: PlacedLayout,
                         level_name: str = "Level 1",
                         wall_height: float = 10.0,
                         exterior_wall_type: str = None,
                         interior_wall_type: str = None,
                         wet_wall_type: str = None) -> List[Dict]:
    """Backwards-compatible wrapper for layout_to_walls with REVIT format."""
    return layout_to_walls(
        layout,
        OutputFormat.REVIT,
        level_name,
        wall_height,
        exterior_wall_type,
        interior_wall_type,
        wet_wall_type
    )


def layout_to_doors(layout: PlacedLayout,
                   output_format: OutputFormat = OutputFormat.REVIT,
                   level_name: str = "Level 1",
                   wall_list: List[Dict] = None) -> List[Dict]:
    """
    Extract door placements from layout.

    Args:
        layout: PlacedLayout from coordinate solver
        output_format: Target output format (REVIT or ARCHENGINE)
        level_name: Level name
        wall_list: Optional wall list (for wall_index lookup in ArchEngine format)

    Returns:
        List of door placement dicts
    """
    doors = []

    # Unit conversion factor
    unit_scale = FEET_TO_MM if output_format == OutputFormat.ARCHENGINE else 1.0

    # Build wall index lookup if needed
    wall_indices = {}
    if wall_list:
        for idx, w in enumerate(wall_list):
            wall_indices[w.get("wall_id", f"wall_{idx}")] = idx

    for wall_idx, wall in enumerate(layout.walls):
        for open_start, open_end, open_type in wall.openings:
            if open_type.value in ["door", "double_door", "pocket_door", "barn_door", "french_door"]:
                # Door center
                center_x = (open_start.x + open_end.x) / 2 * unit_scale
                center_y = (open_start.y + open_end.y) / 2 * unit_scale

                # Door width
                width = math.sqrt((open_end.x - open_start.x)**2 +
                                 (open_end.y - open_start.y)**2) * unit_scale

                # Standard door height (6'8" = 80 inches = 2032mm)
                height = 6.67 * unit_scale  # 6'8" in feet

                door_dict = {
                    "x": center_x,
                    "y": center_y,
                    "width": width,
                    "type": open_type.value,
                    "room1": wall.room1,
                    "room2": wall.room2,
                    "level_name": level_name
                }

                if output_format == OutputFormat.ARCHENGINE:
                    # ArchEngine format includes wall_index, height, offset, swing
                    door_dict["wall_index"] = wall_indices.get(wall.wall_id, wall_idx)
                    door_dict["height"] = height
                    # Calculate offset from wall start
                    wall_start_x = wall.start.x * unit_scale
                    wall_start_y = wall.start.y * unit_scale
                    offset = math.sqrt((center_x - wall_start_x)**2 +
                                      (center_y - wall_start_y)**2)
                    door_dict["offset"] = offset
                    door_dict["swing"] = "left_in"  # Default swing direction
                else:
                    door_dict["wall_id"] = wall.wall_id

                doors.append(door_dict)

    return doors


def layout_to_rooms_data(layout: PlacedLayout,
                        output_format: OutputFormat = OutputFormat.REVIT,
                        level_name: str = "Level 1") -> Dict[str, Dict]:
    """
    Extract room data from layout for room boundaries/tags.

    Args:
        layout: PlacedLayout from coordinate solver
        output_format: Target output format (REVIT or ARCHENGINE)
        level_name: Level name for room association (required in V2)

    Returns:
        Dict of room_id -> room data
    """
    rooms = {}

    # Unit conversion factor
    unit_scale = FEET_TO_MM if output_format == OutputFormat.ARCHENGINE else 1.0
    area_scale = (FEET_TO_MM ** 2) if output_format == OutputFormat.ARCHENGINE else 1.0

    # Zone mapping for ArchEngine
    zone_mapping = {
        "living": "public",
        "dining": "public",
        "kitchen": "service",
        "entry": "circulation",
        "hallway": "circulation",
        "primary_bedroom": "private",
        "bedroom": "private",
        "primary_bath": "private",
        "bathroom": "private",
        "powder_room": "service",
        "closet": "private",
        "walk_in_closet": "private",
        "laundry": "service",
        "garage": "service",
        "mudroom": "circulation",
        "office": "private",
        "pantry": "service",
    }

    for room_id, room in layout.rooms.items():
        room_dict = {
            "name": room_id.replace("_", " ").title(),
            "level": level_name,  # Required in V2
            "bounds": {
                "x": room.rect.x * unit_scale,
                "y": room.rect.y * unit_scale,
                "width": room.rect.width * unit_scale,
                "height": room.rect.height * unit_scale
            },
            "area": room.area * area_scale,
            "center": {
                "x": room.center.x * unit_scale,
                "y": room.center.y * unit_scale
            }
        }

        if output_format == OutputFormat.ARCHENGINE:
            # Add room_type and zone for ArchEngine
            room_type = room_id.split("_")[0] if "_" in room_id else room_id
            room_dict["room_type"] = room_type
            room_dict["zone"] = zone_mapping.get(room_type, "private")

        rooms[room_id] = room_dict

    return rooms


# =============================================================================
# WINDOWS GENERATION
# =============================================================================

def layout_to_windows(layout: PlacedLayout,
                     walls_batch: List[Dict],
                     output_format: OutputFormat = OutputFormat.REVIT,
                     level_name: str = "Level 1",
                     window_height: float = 4.0,
                     sill_height: float = 3.0) -> List[Dict]:
    """
    Generate windows for exterior walls.

    Places windows on exterior walls for rooms that benefit from natural light.

    Args:
        layout: PlacedLayout from coordinate solver
        walls_batch: List of wall dicts (to get wall indices)
        output_format: Target output format
        level_name: Level name
        window_height: Window height in feet
        sill_height: Sill height from floor in feet

    Returns:
        List of window dicts
    """
    windows = []

    unit_scale = FEET_TO_MM if output_format == OutputFormat.ARCHENGINE else 1.0

    # Rooms that should have windows on exterior walls
    rooms_needing_windows = {
        "living", "dining", "kitchen", "primary_bedroom",
        "bedroom", "office", "bedroom_2", "bedroom_3", "bedroom_4"
    }

    # Window type based on room
    window_types = {
        "living": "double_hung",
        "dining": "double_hung",
        "kitchen": "sliding",
        "primary_bedroom": "double_hung",
        "bedroom": "double_hung",
        "office": "casement",
    }

    window_id = 0

    for wall_idx, wall_dict in enumerate(walls_batch):
        if wall_dict["category"] != "exterior":
            continue

        rooms = wall_dict.get("rooms", [])
        interior_room = None

        for room in rooms:
            if room != "exterior" and room != "unassigned":
                interior_room = room
                break

        if not interior_room:
            continue

        # Check if this room should have windows
        room_base = interior_room.split("_")[0] if "_" in interior_room else interior_room
        if room_base not in rooms_needing_windows and interior_room not in rooms_needing_windows:
            continue

        # Calculate wall length
        start = wall_dict["start"]
        end = wall_dict["end"]
        wall_length = math.sqrt((end[0] - start[0])**2 + (end[2] - start[2])**2)

        # Minimum wall length for a window (in output units)
        min_wall_length = 4.0 * unit_scale  # 4 feet minimum

        if wall_length < min_wall_length:
            continue

        # Window width based on wall length (typically 3' windows)
        window_width = 3.0 * unit_scale

        # How many windows fit?
        available_length = wall_length - (2.0 * unit_scale)  # Leave 1' margins on each side
        num_windows = max(1, int(available_length / (window_width + 2.0 * unit_scale)))

        # Distribute windows evenly
        spacing = wall_length / (num_windows + 1)

        for i in range(num_windows):
            offset = spacing * (i + 1)

            window_type = window_types.get(room_base, "double_hung")

            window_dict = {
                "wall_index": wall_idx,
                "offset": offset,
                "width": window_width,
                "height": window_height * unit_scale,
                "sill_height": sill_height * unit_scale,
                "type": window_type,
                "room": interior_room,
                "level_name": level_name
            }

            windows.append(window_dict)
            window_id += 1

    return windows


# =============================================================================
# LEVELS GENERATION
# =============================================================================

def layout_to_levels(output_format: OutputFormat = OutputFormat.REVIT,
                    num_levels: int = 1,
                    floor_to_floor_height: float = 10.0) -> List[Dict]:
    """
    Generate level definitions.

    Args:
        output_format: Target output format
        num_levels: Number of floors
        floor_to_floor_height: Height between floors in feet

    Returns:
        List of level dicts
    """
    unit_scale = FEET_TO_MM if output_format == OutputFormat.ARCHENGINE else 1.0

    levels = []

    for i in range(num_levels):
        level_num = i + 1
        elevation = i * floor_to_floor_height * unit_scale

        levels.append({
            "id": f"level_{level_num}",
            "name": f"Level {level_num}",
            "elevation": elevation,
            "floor_to_floor_height": floor_to_floor_height * unit_scale
        })

    # Add roof level
    roof_elevation = num_levels * floor_to_floor_height * unit_scale
    levels.append({
        "id": "roof_level",
        "name": "Roof Level",
        "elevation": roof_elevation,
        "floor_to_floor_height": 0
    })

    return levels


# =============================================================================
# DIMENSIONS GENERATION
# =============================================================================

def layout_to_dimensions(layout: PlacedLayout,
                        output_format: OutputFormat = OutputFormat.REVIT,
                        level_name: str = "Level 1") -> List[Dict]:
    """
    Generate dimension annotations for the layout.

    Creates:
    - Overall building dimensions
    - Room dimensions

    Args:
        layout: PlacedLayout from coordinate solver
        output_format: Target output format
        level_name: Level name

    Returns:
        List of dimension dicts
    """
    dimensions = []

    unit_scale = FEET_TO_MM if output_format == OutputFormat.ARCHENGINE else 1.0
    unit_name = "mm" if output_format == OutputFormat.ARCHENGINE else "feet"

    dim_id = 0

    # Find overall bounds
    min_x = min_y = float('inf')
    max_x = max_y = float('-inf')

    for room in layout.rooms.values():
        min_x = min(min_x, room.rect.x)
        min_y = min(min_y, room.rect.y)
        max_x = max(max_x, room.rect.x + room.rect.width)
        max_y = max(max_y, room.rect.y + room.rect.height)

    # Overall width dimension (bottom edge)
    dimensions.append({
        "id": f"dim_{dim_id}",
        "type": "linear",
        "start_point": [min_x * unit_scale, 0, min_y * unit_scale],
        "end_point": [max_x * unit_scale, 0, min_y * unit_scale],
        "value": (max_x - min_x) * unit_scale,
        "unit": unit_name,
        "label": "Overall Width",
        "level": level_name
    })
    dim_id += 1

    # Overall depth dimension (left edge)
    dimensions.append({
        "id": f"dim_{dim_id}",
        "type": "linear",
        "start_point": [min_x * unit_scale, 0, min_y * unit_scale],
        "end_point": [min_x * unit_scale, 0, max_y * unit_scale],
        "value": (max_y - min_y) * unit_scale,
        "unit": unit_name,
        "label": "Overall Depth",
        "level": level_name
    })
    dim_id += 1

    # Room dimensions
    for room_id, room in layout.rooms.items():
        room_name = room_id.replace("_", " ").title()

        # Room width
        dimensions.append({
            "id": f"dim_{dim_id}",
            "type": "linear",
            "start_point": [room.rect.x * unit_scale, 0, room.rect.y * unit_scale],
            "end_point": [(room.rect.x + room.rect.width) * unit_scale, 0, room.rect.y * unit_scale],
            "value": room.rect.width * unit_scale,
            "unit": unit_name,
            "label": f"{room_name} Width",
            "level": level_name
        })
        dim_id += 1

        # Room height (depth in plan view)
        dimensions.append({
            "id": f"dim_{dim_id}",
            "type": "linear",
            "start_point": [room.rect.x * unit_scale, 0, room.rect.y * unit_scale],
            "end_point": [room.rect.x * unit_scale, 0, (room.rect.y + room.rect.height) * unit_scale],
            "value": room.rect.height * unit_scale,
            "unit": unit_name,
            "label": f"{room_name} Depth",
            "level": level_name
        })
        dim_id += 1

    return dimensions


# =============================================================================
# MAIN GENERATOR FUNCTION
# =============================================================================

def generate_floor_plan_from_qbd(answers: Dict,
                                 width: float = None,
                                 depth: float = None,
                                 grid_size: float = 2.0,
                                 max_nodes: int = 50000,
                                 output_format: OutputFormat = OutputFormat.REVIT,
                                 creative_mode: bool = False,
                                 solver_mode: str = "subdivision") -> Dict:
    """
    Generate a complete floor plan from QBD answers.

    Args:
        answers: QBD answer dict
        width: Building width (auto-calculated if None)
        depth: Building depth (auto-calculated if None)
        grid_size: Grid snap size
        max_nodes: Max solver nodes
        output_format: Target output format (REVIT or ARCHENGINE)
        creative_mode: If True, use organic growth for interesting non-rectangular shapes

    Returns:
        Dict with walls_batch, doors, rooms, and metadata
    """
    # Calculate dimensions if not provided
    sqft = int(answers.get("sqft", answers.get("com_sqft", answers.get("mixed_sqft", "1200"))))

    # Step 1: Create spatial graph from answers
    graph = create_spatial_graph_from_qbd(answers)
    print(f"[QBD Layout] Created graph with {len(graph.rooms)} rooms")

    # Step 1b: Auto-size building if program demands more than user requested.
    # Sum of min_area across all rooms is the floor; +20% covers walls and
    # circulation. If user provided explicit width/depth, respect them.
    user_provided_dims = (width is not None and depth is not None)
    if not user_provided_dims:
        total_min_area = sum(r.min_area for r in graph.rooms.values())
        required_sqft = int(total_min_area * 1.35)  # 35% overhead — L-shape needs more slack than free-form
        if required_sqft > sqft:
            print(
                f"[QBD Layout] Program requires {required_sqft} sqft "
                f"({len(graph.rooms)} rooms, min_area sum {total_min_area:.0f} sqft + 25% overhead). "
                f"User requested {sqft} sqft. Auto-resizing to {required_sqft} sqft."
            )
            sqft = required_sqft
        ratio = 1.4  # Golden ratio-ish
        depth = math.sqrt(sqft / ratio)
        width = sqft / depth

    width = round(width, 0)
    depth = round(depth, 0)

    format_name = output_format.value.upper()
    print(f"[QBD Layout] Generating {width}x{depth} ({sqft} sqft) for {format_name}")

    # Validate
    issues = graph.validate()
    if issues:
        print(f"[QBD Layout] Validation issues: {issues}")

    # Step 2: Solve layout (subdivision = new top-down BSP, backtracking = legacy)
    if solver_mode == "subdivision":
        from subdivision_solver import solve_layout_subdivision
        entry_edge = getattr(graph, "entry_edge", "south") or "south"
        layout = solve_layout_subdivision(graph, width, depth, entry_edge=entry_edge)
    else:
        layout = solve_layout(graph, width, depth, grid_size, max_nodes, creative_mode=creative_mode)

    if not layout.rooms:
        return {
            "success": False,
            "error": "Could not place any rooms. Try larger dimensions or fewer rooms.",
            "width": width,
            "depth": depth,
            "sqft": sqft,
            "output_format": output_format.value
        }

    print(f"[QBD Layout] Placed {len(layout.rooms)}/{len(graph.rooms)} rooms")

    # Step 3: Convert to target format
    level_name = "Level 1"  # Default level for single-story layouts
    walls_batch = layout_to_walls(layout, output_format)
    doors = layout_to_doors(layout, output_format, wall_list=walls_batch)
    rooms_data = layout_to_rooms_data(layout, output_format, level_name=level_name)
    # Windows disabled for now - will add room-based window placement later
    windows = []
    levels = layout_to_levels(output_format)
    dimensions = layout_to_dimensions(layout, output_format, level_name=level_name)

    # Unit conversion for dimensions in result
    unit_scale = FEET_TO_MM if output_format == OutputFormat.ARCHENGINE else 1.0
    unit_name = "mm" if output_format == OutputFormat.ARCHENGINE else "feet"

    # Generate building ID
    import uuid
    building_id = str(uuid.uuid4())[:8]

    result = {
        "success": True,
        "building_id": building_id,
        "width": width * unit_scale,
        "depth": depth * unit_scale,
        "sqft": sqft,  # Keep sqft in sqft (don't convert to mm²)
        "output_format": output_format.value,
        "unit": unit_name,
        "creative_mode": creative_mode,  # Track which solver mode was used
        "walls_batch": walls_batch,
        "doors": doors,
        "windows": windows,
        "levels": levels,
        "dimensions": dimensions,
        "rooms": rooms_data,
        "is_complete": layout.is_complete,
        "unplaced_rooms": layout.unplaced_rooms,
        "score": layout.score,
        "summary": {
            "total_walls": len(walls_batch),
            "exterior_walls": len([w for w in walls_batch if w["category"] == "exterior"]),
            "interior_walls": len([w for w in walls_batch if w["category"] == "interior"]),
            "wet_walls": len([w for w in walls_batch if w["category"] == "wet_wall"]),
            "doors": len(doors),
            "windows": len(windows),
            "rooms_placed": len([r for r in layout.rooms if not r.startswith('dead_space_')]),
            "rooms_requested": len(graph.rooms),
            "circulation_cells": len([r for r in layout.rooms if r.startswith('dead_space_')])
        }
    }

    # Add ArchEngine-specific fields
    if output_format == OutputFormat.ARCHENGINE:
        result["qbd_answers"] = answers

    return result


# =============================================================================
# ARCHENGINE EXPORT
# =============================================================================

def export_for_archengine(answers: Dict,
                          width: float = None,
                          depth: float = None,
                          output_path: str = None) -> Dict:
    """
    Export a floor plan in ArchEngine format (compatible with UE5 viewer).

    Args:
        answers: QBD answer dict
        width: Building width in feet (auto-calculated if None)
        depth: Building depth in feet (auto-calculated if None)
        output_path: Optional path to save JSON file

    Returns:
        Dict in ArchEngine QBD format (mm units)
    """
    import json

    result = generate_floor_plan_from_qbd(
        answers,
        width=width,
        depth=depth,
        output_format=OutputFormat.ARCHENGINE
    )

    if output_path and result["success"]:
        with open(output_path, "w") as f:
            json.dump(result, f, indent=2)
        print(f"[ArchEngine] Exported to {output_path}")

    return result


def export_for_revit(answers: Dict,
                     width: float = None,
                     depth: float = None) -> Dict:
    """
    Export a floor plan in Revit format (feet units).

    Args:
        answers: QBD answer dict
        width: Building width in feet (auto-calculated if None)
        depth: Building depth in feet (auto-calculated if None)

    Returns:
        Dict in Revit format (feet units)
    """
    return generate_floor_plan_from_qbd(
        answers,
        width=width,
        depth=depth,
        output_format=OutputFormat.REVIT
    )


# =============================================================================
# GENERATE EXECUTION PLAN
# =============================================================================

def generate_qbd_plan(answers: Dict, output_format: OutputFormat = OutputFormat.REVIT) -> List[Dict]:
    """
    Generate a Revit execution plan from QBD answers.

    This replaces the old room-list based approach with the
    relationship-based layout system.

    Args:
        answers: QBD answer dict
        output_format: Target output format (default REVIT)

    Returns:
        List of execution steps for Revit
    """
    # Generate the layout
    result = generate_floor_plan_from_qbd(answers, output_format=output_format)

    if not result["success"]:
        return [{
            "step": 1,
            "tool": "error",
            "description": "Layout generation failed",
            "args": {"error": result.get("error", "Unknown error")}
        }]

    width = result["width"]
    depth = result["depth"]

    # Build execution plan
    plan = [
        {
            "step": 1,
            "tool": "create_levels_batch",
            "description": "Create floor levels",
            "args": {
                "levels": [
                    {"name": "Level 1", "elevation": 0.0},
                    {"name": "Roof Level", "elevation": 10.0}
                ]
            }
        },
        {
            "step": 2,
            "tool": "create_walls_batch",
            "description": f"Create walls ({result['summary']['total_walls']} walls)",
            "args": {
                "walls": result["walls_batch"]
            }
        },
        {
            "step": 3,
            "tool": "create_floor",
            "description": "Create floor slab",
            "args": {
                "points": [[0, 0, 0], [width, 0, 0],
                          [width, depth, 0], [0, depth, 0]],
                "level_name": "Level 1"
            }
        },
        {
            "step": 4,
            "tool": "create_roof_footprint",
            "description": "Create roof",
            "args": {
                "points": [[0, 0, 0], [width, 0, 0],
                          [width, depth, 0], [0, depth, 0]],
                "level_name": "Roof Level",
                "slope_degrees": 0.0
            }
        }
    ]

    # Add door placements if we have doors
    if result["doors"]:
        plan.append({
            "step": 5,
            "tool": "create_doors_batch",
            "description": f"Place doors ({len(result['doors'])} doors)",
            "args": {
                "doors": result["doors"]
            }
        })

    return plan


# =============================================================================
# TEST
# =============================================================================

if __name__ == "__main__":
    import json

    print("=" * 60)
    print("QBD LAYOUT GENERATOR TEST")
    print("=" * 60)

    # Simulate simple QBD answers (fewer rooms for faster test)
    test_answers = {
        "start": "residential",
        "res_type": "single_family",
        "bedrooms": "2",
        "bathrooms": "1",
        "sqft": "1200",
        "garage": "none",
        "special_rooms": [],
        "style": "modern"
    }

    print(f"\nTest answers: {test_answers}")

    # Test REVIT format
    print("\n" + "-" * 40)
    print("REVIT FORMAT (feet)")
    print("-" * 40)

    revit_result = generate_floor_plan_from_qbd(
        test_answers,
        grid_size=4.0,
        max_nodes=10000,
        output_format=OutputFormat.REVIT
    )

    if revit_result["success"]:
        print(f"\n[OK] Revit layout generated!")
        print(f"   Dimensions: {revit_result['width']}x{revit_result['depth']} ft = {revit_result['sqft']} sqft")
        print(f"   Format: {revit_result['output_format']}")
        print(f"   Complete: {revit_result['is_complete']}")

        print(f"\n   Walls (first 3):")
        for wall in revit_result["walls_batch"][:3]:
            print(f"      {wall['category']}: ({wall['start'][0]:.1f}, {wall['start'][2]:.1f}) -> ({wall['end'][0]:.1f}, {wall['end'][2]:.1f}) ft")

    # Test ARCHENGINE format
    print("\n" + "-" * 40)
    print("ARCHENGINE FORMAT (mm)")
    print("-" * 40)

    arch_result = generate_floor_plan_from_qbd(
        test_answers,
        grid_size=4.0,
        max_nodes=10000,
        output_format=OutputFormat.ARCHENGINE
    )

    if arch_result["success"]:
        print(f"\n[OK] ArchEngine layout generated!")
        print(f"   Building ID: {arch_result['building_id']}")
        print(f"   Dimensions: {arch_result['width']:.0f}x{arch_result['depth']:.0f} {arch_result['unit']} = {arch_result['sqft']} sqft")
        print(f"   Format: {arch_result['output_format']}")
        print(f"   Complete: {arch_result['is_complete']}")

        print(f"\n   Walls (first 3):")
        for wall in arch_result["walls_batch"][:3]:
            print(f"      {wall['category']}: ({wall['start'][0]:.0f}, {wall['start'][2]:.0f}) -> ({wall['end'][0]:.0f}, {wall['end'][2]:.0f}) mm")

        print(f"\n   Windows ({len(arch_result['windows'])} total):")
        for window in arch_result["windows"][:3]:
            print(f"      wall {window['wall_index']}: {window['type']} {window['width']:.0f}x{window['height']:.0f} mm for {window['room']}")

        print(f"\n   Levels ({len(arch_result['levels'])} total):")
        for level in arch_result["levels"]:
            print(f"      {level['name']}: elevation={level['elevation']:.0f} mm")

        print(f"\n   Dimensions ({len(arch_result['dimensions'])} total, first 4):")
        for dim in arch_result["dimensions"][:4]:
            print(f"      {dim['label']}: {dim['value']:.0f} {dim['unit']}")

        print(f"\n   Rooms (first 3):")
        for room_id, room_data in list(arch_result["rooms"].items())[:3]:
            print(f"      {room_id}: {room_data['area']:.0f} mm², zone={room_data.get('zone', 'N/A')}")

        # Save sample ArchEngine output
        sample_path = "test_archengine_output.json"
        with open(sample_path, "w") as f:
            json.dump(arch_result, f, indent=2)
        print(f"\n   Sample saved to: {sample_path}")

    # Test convenience functions
    print("\n" + "-" * 40)
    print("CONVENIENCE FUNCTIONS")
    print("-" * 40)

    revit_export = export_for_revit(test_answers)
    print(f"   export_for_revit: {revit_export['output_format']}, {revit_export['width']}x{revit_export['depth']} ft")

    arch_export = export_for_archengine(test_answers)
    print(f"   export_for_archengine: {arch_export['output_format']}, {arch_export['width']:.0f}x{arch_export['depth']:.0f} mm")

    # Test execution plan generation
    print("\n" + "=" * 60)
    print("EXECUTION PLAN TEST")
    print("=" * 60)

    plan = generate_qbd_plan(test_answers)
    for step in plan:
        print(f"\n   Step {step['step']}: {step['tool']}")
        print(f"      {step['description']}")
