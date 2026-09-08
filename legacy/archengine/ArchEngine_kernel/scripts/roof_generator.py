#!/usr/bin/env python3
"""
roof_generator.py - Generate roof geometry from building footprint

Generates various roof types:
- Gable (simple and cross-gable)
- Hip
- Dutch gable (hip with gable ends)
- Shed
- Flat
- Mansard

All dimensions in millimeters.
"""

import math
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional
from enum import Enum


class RoofType(Enum):
    """Available roof types."""
    GABLE = "gable"
    HIP = "hip"
    DUTCH_GABLE = "dutch_gable"
    SHED = "shed"
    FLAT = "flat"
    MANSARD = "mansard"
    GAMBREL = "gambrel"


class RoofMaterial(Enum):
    """Roofing materials."""
    ASPHALT_SHINGLE = "asphalt_shingle"
    METAL_STANDING_SEAM = "metal_standing_seam"
    METAL_CORRUGATED = "metal_corrugated"
    CLAY_TILE = "clay_tile"
    CONCRETE_TILE = "concrete_tile"
    SLATE = "slate"
    WOOD_SHAKE = "wood_shake"
    TPO_MEMBRANE = "tpo_membrane"  # For flat roofs
    EPDM = "epdm"  # For flat roofs


@dataclass
class RoofSurface:
    """A single roof surface (face)."""
    name: str
    vertices: List[List[float]]  # [[x, y, z], ...]
    normal: List[float]  # [nx, ny, nz]
    slope: float  # Degrees from horizontal
    area: float  # Square mm
    material: str = "asphalt_shingle"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "vertices": self.vertices,
            "normal": self.normal,
            "slope": self.slope,
            "area": self.area,
            "material": self.material
        }


@dataclass
class RoofEdge:
    """A roof edge (ridge, hip, valley, eave, rake)."""
    edge_type: str  # "ridge", "hip", "valley", "eave", "rake"
    start: List[float]
    end: List[float]
    length: float

    def to_dict(self) -> dict:
        return {
            "type": self.edge_type,
            "start": self.start,
            "end": self.end,
            "length": self.length
        }


@dataclass
class Roof:
    """Complete roof definition."""
    roof_type: RoofType
    pitch: float  # Rise per 12 run (e.g., 4 = 4:12 pitch)
    overhang: float  # Eave overhang in mm
    ridge_height: float  # Height of ridge above plate
    surfaces: List[RoofSurface]
    edges: List[RoofEdge]
    material: RoofMaterial = RoofMaterial.ASPHALT_SHINGLE
    fascia_height: float = 150  # mm
    soffit_width: float = 0  # Calculated from overhang

    def to_dict(self) -> dict:
        return {
            "type": self.roof_type.value,
            "pitch": self.pitch,
            "overhang": self.overhang,
            "ridge_height": self.ridge_height,
            "material": self.material.value,
            "fascia_height": self.fascia_height,
            "surfaces": [s.to_dict() for s in self.surfaces],
            "edges": [e.to_dict() for e in self.edges],
            "total_area": sum(s.area for s in self.surfaces)
        }


# =============================================================================
# GEOMETRY HELPERS
# =============================================================================

def pitch_to_angle(pitch: float) -> float:
    """Convert pitch (rise per 12 run) to angle in degrees."""
    return math.degrees(math.atan(pitch / 12.0))


def pitch_to_slope_factor(pitch: float) -> float:
    """Calculate slope factor for area calculations."""
    angle_rad = math.atan(pitch / 12.0)
    return 1.0 / math.cos(angle_rad)


def calculate_ridge_height(span: float, pitch: float) -> float:
    """Calculate ridge height from eave to ridge."""
    half_span = span / 2.0
    return half_span * (pitch / 12.0)


def calculate_normal(v1: List[float], v2: List[float], v3: List[float]) -> List[float]:
    """Calculate surface normal from three vertices."""
    # Edge vectors
    e1 = [v2[i] - v1[i] for i in range(3)]
    e2 = [v3[i] - v1[i] for i in range(3)]

    # Cross product
    nx = e1[1] * e2[2] - e1[2] * e2[1]
    ny = e1[2] * e2[0] - e1[0] * e2[2]
    nz = e1[0] * e2[1] - e1[1] * e2[0]

    # Normalize
    length = math.sqrt(nx*nx + ny*ny + nz*nz)
    if length > 0:
        return [nx/length, ny/length, nz/length]
    return [0, 1, 0]


def calculate_polygon_area(vertices: List[List[float]]) -> float:
    """Calculate area of a 3D polygon using the shoelace formula."""
    if len(vertices) < 3:
        return 0.0

    # Calculate normal to determine projection plane
    normal = calculate_normal(vertices[0], vertices[1], vertices[2])

    # Project to 2D based on largest normal component
    abs_normal = [abs(n) for n in normal]
    max_idx = abs_normal.index(max(abs_normal))

    # Choose projection plane
    if max_idx == 0:  # Project to YZ
        proj = [[v[1], v[2]] for v in vertices]
    elif max_idx == 1:  # Project to XZ
        proj = [[v[0], v[2]] for v in vertices]
    else:  # Project to XY
        proj = [[v[0], v[1]] for v in vertices]

    # Shoelace formula
    n = len(proj)
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += proj[i][0] * proj[j][1]
        area -= proj[j][0] * proj[i][1]

    return abs(area) / 2.0


def offset_point(x: float, z: float, dx: float, dz: float, distance: float) -> Tuple[float, float]:
    """Offset a point perpendicular to a direction."""
    length = math.sqrt(dx*dx + dz*dz)
    if length == 0:
        return x, z
    # Perpendicular direction
    px = -dz / length
    pz = dx / length
    return x + px * distance, z + pz * distance


# =============================================================================
# ROOF GENERATORS
# =============================================================================

def generate_gable_roof(
    width: float,
    depth: float,
    plate_height: float,
    pitch: float = 4.0,
    overhang: float = 600,
    material: RoofMaterial = RoofMaterial.ASPHALT_SHINGLE
) -> Roof:
    """
    Generate a simple gable roof.

    Ridge runs along the depth (Z) axis.
    """
    ridge_rise = calculate_ridge_height(width, pitch)
    ridge_height = plate_height + ridge_rise
    slope_angle = pitch_to_angle(pitch)
    slope_factor = pitch_to_slope_factor(pitch)

    # Key points
    center_x = width / 2

    surfaces = []
    edges = []

    # Left (west) roof surface
    left_vertices = [
        [-overhang, plate_height, -overhang],  # SW eave
        [-overhang, plate_height, depth + overhang],  # NW eave
        [center_x, ridge_height, depth + overhang],  # N ridge
        [center_x, ridge_height, -overhang],  # S ridge
    ]
    left_normal = calculate_normal(left_vertices[0], left_vertices[1], left_vertices[2])
    left_area = (width / 2 + overhang) * (depth + 2 * overhang) * slope_factor

    surfaces.append(RoofSurface(
        name="West Slope",
        vertices=left_vertices,
        normal=left_normal,
        slope=slope_angle,
        area=left_area,
        material=material.value
    ))

    # Right (east) roof surface
    right_vertices = [
        [center_x, ridge_height, -overhang],  # S ridge
        [center_x, ridge_height, depth + overhang],  # N ridge
        [width + overhang, plate_height, depth + overhang],  # NE eave
        [width + overhang, plate_height, -overhang],  # SE eave
    ]
    right_normal = calculate_normal(right_vertices[0], right_vertices[1], right_vertices[2])
    right_area = (width / 2 + overhang) * (depth + 2 * overhang) * slope_factor

    surfaces.append(RoofSurface(
        name="East Slope",
        vertices=right_vertices,
        normal=right_normal,
        slope=slope_angle,
        area=right_area,
        material=material.value
    ))

    # Edges
    # Ridge
    edges.append(RoofEdge(
        edge_type="ridge",
        start=[center_x, ridge_height, -overhang],
        end=[center_x, ridge_height, depth + overhang],
        length=depth + 2 * overhang
    ))

    # Eaves
    edges.append(RoofEdge(
        edge_type="eave",
        start=[-overhang, plate_height, -overhang],
        end=[-overhang, plate_height, depth + overhang],
        length=depth + 2 * overhang
    ))
    edges.append(RoofEdge(
        edge_type="eave",
        start=[width + overhang, plate_height, -overhang],
        end=[width + overhang, plate_height, depth + overhang],
        length=depth + 2 * overhang
    ))

    # Rakes (gable ends)
    rake_length = math.sqrt((width/2 + overhang)**2 + ridge_rise**2)
    edges.append(RoofEdge(
        edge_type="rake",
        start=[-overhang, plate_height, -overhang],
        end=[center_x, ridge_height, -overhang],
        length=rake_length
    ))
    edges.append(RoofEdge(
        edge_type="rake",
        start=[center_x, ridge_height, -overhang],
        end=[width + overhang, plate_height, -overhang],
        length=rake_length
    ))
    edges.append(RoofEdge(
        edge_type="rake",
        start=[-overhang, plate_height, depth + overhang],
        end=[center_x, ridge_height, depth + overhang],
        length=rake_length
    ))
    edges.append(RoofEdge(
        edge_type="rake",
        start=[center_x, ridge_height, depth + overhang],
        end=[width + overhang, plate_height, depth + overhang],
        length=rake_length
    ))

    return Roof(
        roof_type=RoofType.GABLE,
        pitch=pitch,
        overhang=overhang,
        ridge_height=ridge_height,
        surfaces=surfaces,
        edges=edges,
        material=material,
        soffit_width=overhang
    )


def generate_hip_roof(
    width: float,
    depth: float,
    plate_height: float,
    pitch: float = 4.0,
    overhang: float = 600,
    material: RoofMaterial = RoofMaterial.ASPHALT_SHINGLE
) -> Roof:
    """
    Generate a hip roof.

    All four sides slope inward.
    Ridge runs along the longer axis.
    """
    # Determine ridge orientation based on building shape
    if width >= depth:
        # Ridge runs along X (width)
        short_span = depth
        long_span = width
        ridge_along_x = True
    else:
        # Ridge runs along Z (depth)
        short_span = width
        long_span = depth
        ridge_along_x = False

    # Calculate geometry
    hip_inset = short_span / 2  # Hip comes in from end by half the short span
    ridge_rise = calculate_ridge_height(short_span, pitch)
    ridge_height = plate_height + ridge_rise
    slope_angle = pitch_to_angle(pitch)
    slope_factor = pitch_to_slope_factor(pitch)

    surfaces = []
    edges = []

    if ridge_along_x:
        # Ridge runs along X axis
        ridge_start_x = hip_inset
        ridge_end_x = width - hip_inset
        center_z = depth / 2

        # South slope (front)
        south_verts = [
            [-overhang, plate_height, -overhang],
            [width + overhang, plate_height, -overhang],
            [ridge_end_x, ridge_height, center_z],
            [ridge_start_x, ridge_height, center_z],
        ]
        surfaces.append(RoofSurface(
            name="South Slope",
            vertices=south_verts,
            normal=calculate_normal(south_verts[0], south_verts[1], south_verts[2]),
            slope=slope_angle,
            area=calculate_polygon_area(south_verts) * slope_factor,
            material=material.value
        ))

        # North slope (back)
        north_verts = [
            [ridge_start_x, ridge_height, center_z],
            [ridge_end_x, ridge_height, center_z],
            [width + overhang, plate_height, depth + overhang],
            [-overhang, plate_height, depth + overhang],
        ]
        surfaces.append(RoofSurface(
            name="North Slope",
            vertices=north_verts,
            normal=calculate_normal(north_verts[0], north_verts[1], north_verts[2]),
            slope=slope_angle,
            area=calculate_polygon_area(north_verts) * slope_factor,
            material=material.value
        ))

        # West hip end
        west_verts = [
            [-overhang, plate_height, -overhang],
            [ridge_start_x, ridge_height, center_z],
            [-overhang, plate_height, depth + overhang],
        ]
        surfaces.append(RoofSurface(
            name="West Hip",
            vertices=west_verts,
            normal=calculate_normal(west_verts[0], west_verts[1], west_verts[2]),
            slope=slope_angle,
            area=calculate_polygon_area(west_verts) * slope_factor,
            material=material.value
        ))

        # East hip end
        east_verts = [
            [width + overhang, plate_height, -overhang],
            [width + overhang, plate_height, depth + overhang],
            [ridge_end_x, ridge_height, center_z],
        ]
        surfaces.append(RoofSurface(
            name="East Hip",
            vertices=east_verts,
            normal=calculate_normal(east_verts[0], east_verts[1], east_verts[2]),
            slope=slope_angle,
            area=calculate_polygon_area(east_verts) * slope_factor,
            material=material.value
        ))

        # Edges
        # Ridge
        if ridge_end_x > ridge_start_x:
            edges.append(RoofEdge(
                edge_type="ridge",
                start=[ridge_start_x, ridge_height, center_z],
                end=[ridge_end_x, ridge_height, center_z],
                length=ridge_end_x - ridge_start_x
            ))

        # Hip edges
        hip_length = math.sqrt(hip_inset**2 + (depth/2)**2 + ridge_rise**2)
        edges.append(RoofEdge(
            edge_type="hip",
            start=[-overhang, plate_height, -overhang],
            end=[ridge_start_x, ridge_height, center_z],
            length=hip_length
        ))
        edges.append(RoofEdge(
            edge_type="hip",
            start=[-overhang, plate_height, depth + overhang],
            end=[ridge_start_x, ridge_height, center_z],
            length=hip_length
        ))
        edges.append(RoofEdge(
            edge_type="hip",
            start=[width + overhang, plate_height, -overhang],
            end=[ridge_end_x, ridge_height, center_z],
            length=hip_length
        ))
        edges.append(RoofEdge(
            edge_type="hip",
            start=[width + overhang, plate_height, depth + overhang],
            end=[ridge_end_x, ridge_height, center_z],
            length=hip_length
        ))

        # Eaves
        for start, end in [
            ([-overhang, plate_height, -overhang], [width + overhang, plate_height, -overhang]),
            ([width + overhang, plate_height, -overhang], [width + overhang, plate_height, depth + overhang]),
            ([width + overhang, plate_height, depth + overhang], [-overhang, plate_height, depth + overhang]),
            ([-overhang, plate_height, depth + overhang], [-overhang, plate_height, -overhang]),
        ]:
            length = math.sqrt(sum((end[i] - start[i])**2 for i in range(3)))
            edges.append(RoofEdge(edge_type="eave", start=start, end=end, length=length))

    else:
        # Ridge runs along Z axis (similar logic, rotated)
        ridge_start_z = hip_inset
        ridge_end_z = depth - hip_inset
        center_x = width / 2

        # West slope
        west_verts = [
            [-overhang, plate_height, -overhang],
            [-overhang, plate_height, depth + overhang],
            [center_x, ridge_height, ridge_end_z],
            [center_x, ridge_height, ridge_start_z],
        ]
        surfaces.append(RoofSurface(
            name="West Slope",
            vertices=west_verts,
            normal=calculate_normal(west_verts[0], west_verts[1], west_verts[2]),
            slope=slope_angle,
            area=calculate_polygon_area(west_verts) * slope_factor,
            material=material.value
        ))

        # East slope
        east_verts = [
            [center_x, ridge_height, ridge_start_z],
            [center_x, ridge_height, ridge_end_z],
            [width + overhang, plate_height, depth + overhang],
            [width + overhang, plate_height, -overhang],
        ]
        surfaces.append(RoofSurface(
            name="East Slope",
            vertices=east_verts,
            normal=calculate_normal(east_verts[0], east_verts[1], east_verts[2]),
            slope=slope_angle,
            area=calculate_polygon_area(east_verts) * slope_factor,
            material=material.value
        ))

        # South hip
        south_verts = [
            [-overhang, plate_height, -overhang],
            [center_x, ridge_height, ridge_start_z],
            [width + overhang, plate_height, -overhang],
        ]
        surfaces.append(RoofSurface(
            name="South Hip",
            vertices=south_verts,
            normal=calculate_normal(south_verts[0], south_verts[1], south_verts[2]),
            slope=slope_angle,
            area=calculate_polygon_area(south_verts) * slope_factor,
            material=material.value
        ))

        # North hip
        north_verts = [
            [-overhang, plate_height, depth + overhang],
            [width + overhang, plate_height, depth + overhang],
            [center_x, ridge_height, ridge_end_z],
        ]
        surfaces.append(RoofSurface(
            name="North Hip",
            vertices=north_verts,
            normal=calculate_normal(north_verts[0], north_verts[1], north_verts[2]),
            slope=slope_angle,
            area=calculate_polygon_area(north_verts) * slope_factor,
            material=material.value
        ))

        # Ridge
        if ridge_end_z > ridge_start_z:
            edges.append(RoofEdge(
                edge_type="ridge",
                start=[center_x, ridge_height, ridge_start_z],
                end=[center_x, ridge_height, ridge_end_z],
                length=ridge_end_z - ridge_start_z
            ))

        # Hip edges and eaves (similar to above)
        hip_length = math.sqrt((width/2)**2 + hip_inset**2 + ridge_rise**2)
        for corner, ridge_pt in [
            ([-overhang, plate_height, -overhang], [center_x, ridge_height, ridge_start_z]),
            ([width + overhang, plate_height, -overhang], [center_x, ridge_height, ridge_start_z]),
            ([-overhang, plate_height, depth + overhang], [center_x, ridge_height, ridge_end_z]),
            ([width + overhang, plate_height, depth + overhang], [center_x, ridge_height, ridge_end_z]),
        ]:
            edges.append(RoofEdge(edge_type="hip", start=corner, end=ridge_pt, length=hip_length))

        # Eaves
        for start, end in [
            ([-overhang, plate_height, -overhang], [width + overhang, plate_height, -overhang]),
            ([width + overhang, plate_height, -overhang], [width + overhang, plate_height, depth + overhang]),
            ([width + overhang, plate_height, depth + overhang], [-overhang, plate_height, depth + overhang]),
            ([-overhang, plate_height, depth + overhang], [-overhang, plate_height, -overhang]),
        ]:
            length = math.sqrt(sum((end[i] - start[i])**2 for i in range(3)))
            edges.append(RoofEdge(edge_type="eave", start=start, end=end, length=length))

    return Roof(
        roof_type=RoofType.HIP,
        pitch=pitch,
        overhang=overhang,
        ridge_height=ridge_height,
        surfaces=surfaces,
        edges=edges,
        material=material,
        soffit_width=overhang
    )


def generate_shed_roof(
    width: float,
    depth: float,
    plate_height: float,
    pitch: float = 2.0,
    overhang: float = 600,
    high_side: str = "north",  # "north", "south", "east", "west"
    material: RoofMaterial = RoofMaterial.ASPHALT_SHINGLE
) -> Roof:
    """
    Generate a single-slope shed roof.
    """
    if high_side in ["north", "south"]:
        span = depth
    else:
        span = width

    rise = span * (pitch / 12.0)
    high_height = plate_height + rise
    slope_angle = pitch_to_angle(pitch)
    slope_factor = pitch_to_slope_factor(pitch)

    surfaces = []
    edges = []

    if high_side == "north":
        vertices = [
            [-overhang, plate_height, -overhang],  # SW (low)
            [width + overhang, plate_height, -overhang],  # SE (low)
            [width + overhang, high_height, depth + overhang],  # NE (high)
            [-overhang, high_height, depth + overhang],  # NW (high)
        ]
    elif high_side == "south":
        vertices = [
            [-overhang, high_height, -overhang],  # SW (high)
            [width + overhang, high_height, -overhang],  # SE (high)
            [width + overhang, plate_height, depth + overhang],  # NE (low)
            [-overhang, plate_height, depth + overhang],  # NW (low)
        ]
    elif high_side == "east":
        vertices = [
            [-overhang, plate_height, -overhang],  # SW (low)
            [width + overhang, high_height, -overhang],  # SE (high)
            [width + overhang, high_height, depth + overhang],  # NE (high)
            [-overhang, plate_height, depth + overhang],  # NW (low)
        ]
    else:  # west
        vertices = [
            [-overhang, high_height, -overhang],  # SW (high)
            [width + overhang, plate_height, -overhang],  # SE (low)
            [width + overhang, plate_height, depth + overhang],  # NE (low)
            [-overhang, high_height, depth + overhang],  # NW (high)
        ]

    area = (width + 2 * overhang) * (depth + 2 * overhang) * slope_factor

    surfaces.append(RoofSurface(
        name="Main Slope",
        vertices=vertices,
        normal=calculate_normal(vertices[0], vertices[1], vertices[2]),
        slope=slope_angle,
        area=area,
        material=material.value
    ))

    # Add eave edges
    for i in range(4):
        start = vertices[i]
        end = vertices[(i + 1) % 4]
        length = math.sqrt(sum((end[j] - start[j])**2 for j in range(3)))
        edge_type = "eave" if start[1] == end[1] else "rake"
        edges.append(RoofEdge(edge_type=edge_type, start=start, end=end, length=length))

    return Roof(
        roof_type=RoofType.SHED,
        pitch=pitch,
        overhang=overhang,
        ridge_height=high_height,
        surfaces=surfaces,
        edges=edges,
        material=material,
        soffit_width=overhang
    )


def generate_flat_roof(
    width: float,
    depth: float,
    plate_height: float,
    parapet_height: float = 300,
    overhang: float = 0,
    material: RoofMaterial = RoofMaterial.TPO_MEMBRANE
) -> Roof:
    """
    Generate a flat roof with optional parapet.
    """
    roof_height = plate_height + parapet_height

    vertices = [
        [0, roof_height, 0],
        [width, roof_height, 0],
        [width, roof_height, depth],
        [0, roof_height, depth],
    ]

    area = width * depth

    surfaces = [RoofSurface(
        name="Flat Roof",
        vertices=vertices,
        normal=[0, 1, 0],
        slope=0,
        area=area,
        material=material.value
    )]

    edges = []
    for i in range(4):
        start = vertices[i]
        end = vertices[(i + 1) % 4]
        length = math.sqrt(sum((end[j] - start[j])**2 for j in range(3)))
        edges.append(RoofEdge(edge_type="parapet", start=start, end=end, length=length))

    return Roof(
        roof_type=RoofType.FLAT,
        pitch=0,
        overhang=overhang,
        ridge_height=roof_height,
        surfaces=surfaces,
        edges=edges,
        material=material,
        soffit_width=0
    )


# =============================================================================
# MAIN GENERATOR FUNCTION
# =============================================================================

def generate_roof(
    building_data: dict,
    roof_type: str = "gable",
    pitch: float = 4.0,
    overhang: float = 600,
    material: str = "asphalt_shingle"
) -> dict:
    """
    Generate roof geometry from building data.

    Args:
        building_data: Building JSON with width, depth, walls_batch
        roof_type: Type of roof ("gable", "hip", "shed", "flat")
        pitch: Roof pitch as rise per 12 run
        overhang: Eave overhang in mm
        material: Roofing material

    Returns:
        Roof data as dictionary for JSON serialization
    """
    width = building_data.get('width', 10000)
    depth = building_data.get('depth', 10000)

    # Get plate height from walls
    walls = building_data.get('walls_batch', [])
    plate_height = 2700  # Default
    if walls:
        plate_height = max(w.get('height', 2700) for w in walls)

    # Parse material
    try:
        roof_material = RoofMaterial(material)
    except ValueError:
        roof_material = RoofMaterial.ASPHALT_SHINGLE

    # Generate based on type
    if roof_type == "gable":
        roof = generate_gable_roof(width, depth, plate_height, pitch, overhang, roof_material)
    elif roof_type == "hip":
        roof = generate_hip_roof(width, depth, plate_height, pitch, overhang, roof_material)
    elif roof_type == "shed":
        roof = generate_shed_roof(width, depth, plate_height, pitch, overhang, "north", roof_material)
    elif roof_type == "flat":
        roof = generate_flat_roof(width, depth, plate_height, 300, overhang, roof_material)
    else:
        # Default to gable
        roof = generate_gable_roof(width, depth, plate_height, pitch, overhang, roof_material)

    return roof.to_dict()


def add_roof_to_building(building_data: dict, roof_config: dict = None) -> dict:
    """
    Add roof data to building JSON.

    Args:
        building_data: Existing building JSON
        roof_config: Optional roof configuration dict

    Returns:
        Updated building data with roof
    """
    if roof_config is None:
        # Determine roof type from style
        style = building_data.get('qbd_answers', {}).get('style', 'traditional')
        if style in ['modern', 'contemporary']:
            roof_type = 'flat'
            pitch = 0.25  # Slight slope for drainage
        elif style in ['craftsman', 'bungalow']:
            roof_type = 'gable'
            pitch = 6.0  # Steeper pitch
        else:
            roof_type = 'gable'
            pitch = 4.0

        roof_config = {
            'type': roof_type,
            'pitch': pitch,
            'overhang': 600,
            'material': 'asphalt_shingle'
        }

    roof_data = generate_roof(
        building_data,
        roof_type=roof_config.get('type', 'gable'),
        pitch=roof_config.get('pitch', 4.0),
        overhang=roof_config.get('overhang', 600),
        material=roof_config.get('material', 'asphalt_shingle')
    )

    # Add to building data
    building_data['roofs'] = [roof_data]

    return building_data


if __name__ == "__main__":
    # Test roof generation
    import json

    test_building = {
        'width': 12000,
        'depth': 9000,
        'walls_batch': [{'height': 2700}],
        'qbd_answers': {'style': 'traditional'}
    }

    print("Testing Gable Roof:")
    gable = generate_gable_roof(12000, 9000, 2700, pitch=4.0, overhang=600)
    print(f"  Surfaces: {len(gable.surfaces)}")
    print(f"  Edges: {len(gable.edges)}")
    print(f"  Ridge height: {gable.ridge_height}mm")
    print(f"  Total area: {sum(s.area for s in gable.surfaces) / 1000000:.1f} sqm")

    print("\nTesting Hip Roof:")
    hip = generate_hip_roof(12000, 9000, 2700, pitch=4.0, overhang=600)
    print(f"  Surfaces: {len(hip.surfaces)}")
    print(f"  Edges: {len(hip.edges)}")
    print(f"  Ridge height: {hip.ridge_height}mm")

    print("\nFull building with roof:")
    updated = add_roof_to_building(test_building)
    print(json.dumps(updated['roofs'][0], indent=2)[:500] + "...")
