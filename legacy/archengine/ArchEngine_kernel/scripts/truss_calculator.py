#!/usr/bin/env python3
"""
truss_calculator.py - Roof Truss Design, Calculation, and Analysis

Provides:
- Truss geometry calculation for common types
- Member sizing based on spans and loads
- Basic structural analysis (forces, reactions)
- SVG rendering for sections and details
"""

import math
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional
from enum import Enum


# =============================================================================
# ENUMS AND CONSTANTS
# =============================================================================

class TrussType(Enum):
    FINK = "fink"               # Most common - W pattern webbing
    HOWE = "howe"               # Vertical webs with diagonals
    KING_POST = "king_post"     # Single vertical post at center
    QUEEN_POST = "queen_post"   # Two vertical posts
    SCISSOR = "scissor"         # Raised ceiling / cathedral
    ATTIC = "attic"             # Room in attic space
    MONO = "mono"               # Single slope (lean-to)
    HIP = "hip"                 # Hip roof end truss
    FLAT = "flat"               # Flat/low slope


class MemberType(Enum):
    TOP_CHORD = "top_chord"
    BOTTOM_CHORD = "bottom_chord"
    KING_POST = "king_post"
    WEB = "web"
    WEB_VERTICAL = "web_vertical"
    WEB_DIAGONAL = "web_diagonal"


class LoadType(Enum):
    DEAD = "dead"           # Self-weight, roofing, ceiling
    LIVE = "live"           # Snow, maintenance
    WIND = "wind"           # Uplift/pressure


# Material properties (typical values)
LUMBER_PROPERTIES = {
    'SPF_2': {  # Spruce-Pine-Fir #2
        'Fb': 8.3,      # Bending stress MPa
        'Ft': 4.8,      # Tension parallel MPa
        'Fc': 11.0,     # Compression parallel MPa
        'E': 9500,      # Modulus of elasticity MPa
        'density': 420,  # kg/m³
    },
    'SYP_2': {  # Southern Yellow Pine #2
        'Fb': 10.3,
        'Ft': 5.5,
        'Fc': 12.4,
        'E': 11000,
        'density': 560,
    },
    'LVL': {  # Laminated Veneer Lumber
        'Fb': 19.3,
        'Ft': 14.5,
        'Fc': 18.6,
        'E': 13800,
        'density': 580,
    }
}

# Standard lumber sizes (actual dimensions in mm)
LUMBER_SIZES = {
    '2x4': (38, 89),
    '2x6': (38, 140),
    '2x8': (38, 184),
    '2x10': (38, 235),
    '2x12': (38, 286),
}


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class Point2D:
    x: float
    y: float

    def distance_to(self, other: 'Point2D') -> float:
        return math.sqrt((self.x - other.x)**2 + (self.y - other.y)**2)


@dataclass
class TrussMember:
    """A single truss member (chord or web)"""
    id: str
    member_type: MemberType
    start: Point2D
    end: Point2D
    size: str = '2x4'           # Lumber size
    length: float = 0           # Calculated length
    axial_force: float = 0      # Tension (+) or compression (-)

    def __post_init__(self):
        self.length = self.start.distance_to(self.end)


@dataclass
class TrussJoint:
    """A joint/node in the truss"""
    id: str
    position: Point2D
    is_support: bool = False
    support_type: str = ""      # "pin", "roller"
    connected_members: List[str] = field(default_factory=list)
    reaction_x: float = 0
    reaction_y: float = 0


@dataclass
class TrussLoad:
    """Applied load on truss"""
    load_type: LoadType
    joint_id: str               # Which joint receives the load
    fx: float = 0               # Horizontal force (N)
    fy: float = 0               # Vertical force (N)


@dataclass
class TrussDesign:
    """Complete truss design"""
    truss_type: TrussType
    span: float                 # Overall span in mm
    pitch: float                # Pitch as rise/12 run
    heel_height: float          # Height at bearing point
    spacing: float              # Truss spacing (typically 600mm)
    overhang: float             # Eave overhang
    members: List[TrussMember] = field(default_factory=list)
    joints: List[TrussJoint] = field(default_factory=list)
    loads: List[TrussLoad] = field(default_factory=list)

    # Calculated properties
    ridge_height: float = 0
    total_height: float = 0
    top_chord_length: float = 0
    bottom_chord_length: float = 0

    # Analysis results
    max_tension: float = 0
    max_compression: float = 0
    is_analyzed: bool = False


# =============================================================================
# TRUSS GEOMETRY GENERATORS
# =============================================================================

def generate_fink_truss(span: float, pitch: float, heel_height: float = 150,
                        overhang: float = 600) -> TrussDesign:
    """
    Generate a Fink (W) truss geometry.

    The Fink truss is the most common residential roof truss,
    characterized by W-shaped webbing pattern.
    """
    # Basic geometry
    half_span = span / 2
    pitch_angle = math.atan(pitch / 12)
    ridge_rise = half_span * (pitch / 12)
    ridge_height = heel_height + ridge_rise

    # Create joints
    joints = []

    # Bottom chord joints (left to right)
    j_left = TrussJoint("J1", Point2D(0, 0), is_support=True, support_type="pin")
    j_bl = TrussJoint("J2", Point2D(span * 0.25, 0))
    j_center = TrussJoint("J3", Point2D(half_span, 0))
    j_br = TrussJoint("J4", Point2D(span * 0.75, 0))
    j_right = TrussJoint("J5", Point2D(span, 0), is_support=True, support_type="roller")

    # Top chord joints
    j_tl = TrussJoint("J6", Point2D(span * 0.25, heel_height + ridge_rise * 0.5))
    j_ridge = TrussJoint("J7", Point2D(half_span, ridge_height))
    j_tr = TrussJoint("J8", Point2D(span * 0.75, heel_height + ridge_rise * 0.5))

    # Heel joints (where top chord meets support)
    j_heel_l = TrussJoint("J9", Point2D(0, heel_height))
    j_heel_r = TrussJoint("J10", Point2D(span, heel_height))

    joints = [j_left, j_bl, j_center, j_br, j_right, j_tl, j_ridge, j_tr, j_heel_l, j_heel_r]

    # Create members
    members = []

    # Bottom chord
    members.append(TrussMember("BC1", MemberType.BOTTOM_CHORD, j_left.position, j_bl.position))
    members.append(TrussMember("BC2", MemberType.BOTTOM_CHORD, j_bl.position, j_center.position))
    members.append(TrussMember("BC3", MemberType.BOTTOM_CHORD, j_center.position, j_br.position))
    members.append(TrussMember("BC4", MemberType.BOTTOM_CHORD, j_br.position, j_right.position))

    # Top chord (left side)
    members.append(TrussMember("TC1", MemberType.TOP_CHORD, j_heel_l.position, j_tl.position))
    members.append(TrussMember("TC2", MemberType.TOP_CHORD, j_tl.position, j_ridge.position))

    # Top chord (right side)
    members.append(TrussMember("TC3", MemberType.TOP_CHORD, j_ridge.position, j_tr.position))
    members.append(TrussMember("TC4", MemberType.TOP_CHORD, j_tr.position, j_heel_r.position))

    # King post (center vertical)
    members.append(TrussMember("KP", MemberType.KING_POST, j_center.position, j_ridge.position))

    # Web members (W pattern)
    members.append(TrussMember("W1", MemberType.WEB_DIAGONAL, j_bl.position, j_tl.position))
    members.append(TrussMember("W2", MemberType.WEB_DIAGONAL, j_tl.position, j_center.position))
    members.append(TrussMember("W3", MemberType.WEB_DIAGONAL, j_center.position, j_tr.position))
    members.append(TrussMember("W4", MemberType.WEB_DIAGONAL, j_tr.position, j_br.position))

    # Vertical heel members
    members.append(TrussMember("H1", MemberType.WEB_VERTICAL, j_left.position, j_heel_l.position))
    members.append(TrussMember("H2", MemberType.WEB_VERTICAL, j_right.position, j_heel_r.position))

    return TrussDesign(
        truss_type=TrussType.FINK,
        span=span,
        pitch=pitch,
        heel_height=heel_height,
        spacing=600,
        overhang=overhang,
        members=members,
        joints=joints,
        ridge_height=ridge_height,
        total_height=ridge_height,
        top_chord_length=half_span / math.cos(pitch_angle),
        bottom_chord_length=span
    )


def generate_king_post_truss(span: float, pitch: float, heel_height: float = 150,
                             overhang: float = 600) -> TrussDesign:
    """
    Generate a King Post truss geometry.

    Simplest truss form with single vertical post at center.
    Good for smaller spans up to ~8m.
    """
    half_span = span / 2
    pitch_angle = math.atan(pitch / 12)
    ridge_rise = half_span * (pitch / 12)
    ridge_height = heel_height + ridge_rise

    joints = [
        TrussJoint("J1", Point2D(0, 0), is_support=True, support_type="pin"),
        TrussJoint("J2", Point2D(half_span, 0)),
        TrussJoint("J3", Point2D(span, 0), is_support=True, support_type="roller"),
        TrussJoint("J4", Point2D(0, heel_height)),
        TrussJoint("J5", Point2D(half_span, ridge_height)),
        TrussJoint("J6", Point2D(span, heel_height)),
    ]

    j = {j.id: j for j in joints}

    members = [
        # Bottom chord
        TrussMember("BC1", MemberType.BOTTOM_CHORD, j["J1"].position, j["J2"].position),
        TrussMember("BC2", MemberType.BOTTOM_CHORD, j["J2"].position, j["J3"].position),
        # Top chord
        TrussMember("TC1", MemberType.TOP_CHORD, j["J4"].position, j["J5"].position),
        TrussMember("TC2", MemberType.TOP_CHORD, j["J5"].position, j["J6"].position),
        # King post
        TrussMember("KP", MemberType.KING_POST, j["J2"].position, j["J5"].position),
        # Heel verticals
        TrussMember("H1", MemberType.WEB_VERTICAL, j["J1"].position, j["J4"].position),
        TrussMember("H2", MemberType.WEB_VERTICAL, j["J3"].position, j["J6"].position),
    ]

    return TrussDesign(
        truss_type=TrussType.KING_POST,
        span=span,
        pitch=pitch,
        heel_height=heel_height,
        spacing=600,
        overhang=overhang,
        members=members,
        joints=joints,
        ridge_height=ridge_height,
        total_height=ridge_height,
        top_chord_length=half_span / math.cos(pitch_angle),
        bottom_chord_length=span
    )


def generate_queen_post_truss(span: float, pitch: float, heel_height: float = 150,
                              overhang: float = 600) -> TrussDesign:
    """
    Generate a Queen Post truss geometry.

    Two vertical posts creating a flat section at top.
    Good for spans 8-12m.
    """
    half_span = span / 2
    third_span = span / 3
    pitch_angle = math.atan(pitch / 12)

    # Posts at 1/3 points
    post_height = heel_height + third_span * (pitch / 12)
    ridge_height = heel_height + half_span * (pitch / 12)

    joints = [
        TrussJoint("J1", Point2D(0, 0), is_support=True, support_type="pin"),
        TrussJoint("J2", Point2D(third_span, 0)),
        TrussJoint("J3", Point2D(span - third_span, 0)),
        TrussJoint("J4", Point2D(span, 0), is_support=True, support_type="roller"),
        TrussJoint("J5", Point2D(0, heel_height)),
        TrussJoint("J6", Point2D(third_span, post_height)),
        TrussJoint("J7", Point2D(span - third_span, post_height)),
        TrussJoint("J8", Point2D(span, heel_height)),
    ]

    j = {j.id: j for j in joints}

    members = [
        # Bottom chord
        TrussMember("BC1", MemberType.BOTTOM_CHORD, j["J1"].position, j["J2"].position),
        TrussMember("BC2", MemberType.BOTTOM_CHORD, j["J2"].position, j["J3"].position),
        TrussMember("BC3", MemberType.BOTTOM_CHORD, j["J3"].position, j["J4"].position),
        # Top chord
        TrussMember("TC1", MemberType.TOP_CHORD, j["J5"].position, j["J6"].position),
        TrussMember("TC2", MemberType.TOP_CHORD, j["J6"].position, j["J7"].position),  # Flat section
        TrussMember("TC3", MemberType.TOP_CHORD, j["J7"].position, j["J8"].position),
        # Queen posts
        TrussMember("QP1", MemberType.WEB_VERTICAL, j["J2"].position, j["J6"].position),
        TrussMember("QP2", MemberType.WEB_VERTICAL, j["J3"].position, j["J7"].position),
        # Heel verticals
        TrussMember("H1", MemberType.WEB_VERTICAL, j["J1"].position, j["J5"].position),
        TrussMember("H2", MemberType.WEB_VERTICAL, j["J4"].position, j["J8"].position),
    ]

    return TrussDesign(
        truss_type=TrussType.QUEEN_POST,
        span=span,
        pitch=pitch,
        heel_height=heel_height,
        spacing=600,
        overhang=overhang,
        members=members,
        joints=joints,
        ridge_height=post_height,  # No true ridge on queen post
        total_height=post_height,
        top_chord_length=span,  # Approximate
        bottom_chord_length=span
    )


def generate_scissor_truss(span: float, pitch: float, ceiling_pitch: float = None,
                           heel_height: float = 150, overhang: float = 600) -> TrussDesign:
    """
    Generate a Scissor truss geometry.

    Creates vaulted/cathedral ceiling effect.
    Bottom chord slopes upward toward center.
    """
    if ceiling_pitch is None:
        ceiling_pitch = pitch / 2  # Typically half the roof pitch

    half_span = span / 2
    pitch_angle = math.atan(pitch / 12)
    ceiling_angle = math.atan(ceiling_pitch / 12)

    ridge_rise = half_span * (pitch / 12)
    ceiling_rise = half_span * (ceiling_pitch / 12)

    ridge_height = heel_height + ridge_rise
    ceiling_peak = ceiling_rise  # Bottom chord peak at center

    joints = [
        TrussJoint("J1", Point2D(0, 0), is_support=True, support_type="pin"),
        TrussJoint("J2", Point2D(half_span, ceiling_peak)),  # Bottom chord peak
        TrussJoint("J3", Point2D(span, 0), is_support=True, support_type="roller"),
        TrussJoint("J4", Point2D(0, heel_height)),
        TrussJoint("J5", Point2D(half_span, ridge_height)),
        TrussJoint("J6", Point2D(span, heel_height)),
        # Web intersection points
        TrussJoint("J7", Point2D(span * 0.25, ceiling_rise * 0.5)),
        TrussJoint("J8", Point2D(span * 0.75, ceiling_rise * 0.5)),
    ]

    j = {j.id: j for j in joints}

    members = [
        # Bottom chord (scissor pattern - slopes up to center)
        TrussMember("BC1", MemberType.BOTTOM_CHORD, j["J1"].position, j["J7"].position),
        TrussMember("BC2", MemberType.BOTTOM_CHORD, j["J7"].position, j["J2"].position),
        TrussMember("BC3", MemberType.BOTTOM_CHORD, j["J2"].position, j["J8"].position),
        TrussMember("BC4", MemberType.BOTTOM_CHORD, j["J8"].position, j["J3"].position),
        # Top chord
        TrussMember("TC1", MemberType.TOP_CHORD, j["J4"].position, j["J5"].position),
        TrussMember("TC2", MemberType.TOP_CHORD, j["J5"].position, j["J6"].position),
        # Heel verticals
        TrussMember("H1", MemberType.WEB_VERTICAL, j["J1"].position, j["J4"].position),
        TrussMember("H2", MemberType.WEB_VERTICAL, j["J3"].position, j["J6"].position),
        # Web members
        TrussMember("W1", MemberType.WEB_DIAGONAL, j["J7"].position, j["J5"].position),
        TrussMember("W2", MemberType.WEB_DIAGONAL, j["J8"].position, j["J5"].position),
    ]

    return TrussDesign(
        truss_type=TrussType.SCISSOR,
        span=span,
        pitch=pitch,
        heel_height=heel_height,
        spacing=600,
        overhang=overhang,
        members=members,
        joints=joints,
        ridge_height=ridge_height,
        total_height=ridge_height,
        top_chord_length=half_span / math.cos(pitch_angle),
        bottom_chord_length=span
    )


# =============================================================================
# TRUSS FACTORY
# =============================================================================

def create_truss(truss_type: TrussType, span: float, pitch: float,
                 heel_height: float = None, overhang: float = 600,
                 **kwargs) -> TrussDesign:
    """
    Factory function to create a truss of the specified type.

    Args:
        truss_type: Type of truss to create
        span: Overall span in mm
        pitch: Roof pitch as rise per 12 run
        heel_height: Height at bearing (calculated if None)
        overhang: Eave overhang in mm

    Returns:
        TrussDesign with geometry
    """
    from generate_sections import calculate_rafter_depth, calculate_heel_height

    # Calculate heel height if not provided
    if heel_height is None:
        rafter_depth = calculate_rafter_depth(span / 2)
        heel_height = calculate_heel_height(pitch, rafter_depth)

    generators = {
        TrussType.FINK: generate_fink_truss,
        TrussType.KING_POST: generate_king_post_truss,
        TrussType.QUEEN_POST: generate_queen_post_truss,
        TrussType.SCISSOR: generate_scissor_truss,
    }

    generator = generators.get(truss_type, generate_fink_truss)
    return generator(span, pitch, heel_height, overhang, **kwargs)


# =============================================================================
# LOAD CALCULATOR
# =============================================================================

def calculate_truss_loads(truss: TrussDesign,
                          dead_load: float = 0.5,      # kPa
                          live_load: float = 1.0,      # kPa (snow)
                          roofing_weight: float = 0.3  # kPa
                          ) -> TrussDesign:
    """
    Calculate loads on truss joints.

    Args:
        truss: Truss design to load
        dead_load: Dead load in kPa (roof + ceiling)
        live_load: Live load in kPa (snow, maintenance)
        roofing_weight: Roofing material weight in kPa

    Returns:
        Truss with loads added
    """
    # Tributary width (truss spacing)
    trib_width = truss.spacing / 1000  # Convert to meters

    # Total load per unit area
    total_load = dead_load + live_load + roofing_weight  # kPa = kN/m²

    # Distribute load to top chord joints
    # (simplified - uniform distribution along top chord)

    truss.loads = []

    # Find top chord joints
    top_chord_joints = []
    for member in truss.members:
        if member.member_type == MemberType.TOP_CHORD:
            for joint in truss.joints:
                if (joint.position.x == member.start.x and joint.position.y == member.start.y) or \
                   (joint.position.x == member.end.x and joint.position.y == member.end.y):
                    if joint not in top_chord_joints:
                        top_chord_joints.append(joint)

    # Calculate tributary area for each joint
    if top_chord_joints:
        trib_length = truss.top_chord_length / len(top_chord_joints) / 1000  # m
        load_per_joint = total_load * trib_width * trib_length  # kN

        for joint in top_chord_joints:
            if not joint.is_support:  # Don't apply loads directly to supports
                truss.loads.append(TrussLoad(
                    load_type=LoadType.DEAD,
                    joint_id=joint.id,
                    fy=-load_per_joint * 1000  # Convert to N, negative = downward
                ))

    return truss


# =============================================================================
# STRUCTURAL ANALYSIS (Method of Joints - Simplified)
# =============================================================================

def analyze_truss(truss: TrussDesign) -> TrussDesign:
    """
    Perform basic structural analysis using method of joints.

    Calculates:
    - Support reactions
    - Axial forces in all members

    Note: This is a simplified analysis. Real engineering
    requires proper structural software.
    """
    # Calculate total vertical load
    total_fy = sum(load.fy for load in truss.loads)

    # Find support joints
    supports = [j for j in truss.joints if j.is_support]

    if len(supports) >= 2:
        # Simple beam - divide reaction equally for symmetric loading
        # (This is simplified - real analysis uses equilibrium equations)
        reaction_per_support = -total_fy / len(supports)

        for support in supports:
            support.reaction_y = reaction_per_support
            support.reaction_x = 0

    # Simplified member force calculation
    # For a symmetric Fink truss with uniform load:
    # - Top chord: compression (approximate = total_load * span / (4 * height))
    # - Bottom chord: tension (similar magnitude)
    # - Webs: varies

    if truss.ridge_height > 0 and truss.span > 0:
        # Approximate horizontal thrust
        H = abs(total_fy) * truss.span / (8 * truss.ridge_height)

        for member in truss.members:
            if member.member_type == MemberType.TOP_CHORD:
                # Compression
                member.axial_force = -H * 1.2  # Approximate with factor
            elif member.member_type == MemberType.BOTTOM_CHORD:
                # Tension
                member.axial_force = H
            elif member.member_type == MemberType.KING_POST:
                # Tension (hanging the bottom chord)
                member.axial_force = abs(total_fy) * 0.3
            elif member.member_type in [MemberType.WEB, MemberType.WEB_DIAGONAL]:
                # Varies - approximate
                member.axial_force = H * 0.5

    # Find max forces
    forces = [abs(m.axial_force) for m in truss.members]
    tensions = [m.axial_force for m in truss.members if m.axial_force > 0]
    compressions = [m.axial_force for m in truss.members if m.axial_force < 0]

    truss.max_tension = max(tensions) if tensions else 0
    truss.max_compression = min(compressions) if compressions else 0
    truss.is_analyzed = True

    return truss


# =============================================================================
# MEMBER SIZING
# =============================================================================

def size_truss_members(truss: TrussDesign, material: str = 'SPF_2',
                       safety_factor: float = 2.5) -> TrussDesign:
    """
    Size truss members based on calculated forces.

    Args:
        truss: Analyzed truss design
        material: Lumber type from LUMBER_PROPERTIES
        safety_factor: Factor of safety for member sizing

    Returns:
        Truss with sized members
    """
    if not truss.is_analyzed:
        truss = analyze_truss(truss)

    props = LUMBER_PROPERTIES.get(material, LUMBER_PROPERTIES['SPF_2'])

    for member in truss.members:
        force = abs(member.axial_force)  # N
        force_kn = force / 1000

        if member.axial_force < 0:
            # Compression - size for Fc
            allowable_stress = props['Fc'] / safety_factor  # MPa
        else:
            # Tension - size for Ft
            allowable_stress = props['Ft'] / safety_factor  # MPa

        # Required area = Force / Allowable stress
        required_area = force_kn * 1000 / allowable_stress  # mm²

        # Find smallest lumber that works
        for size_name, (width, depth) in LUMBER_SIZES.items():
            area = width * depth
            if area >= required_area:
                member.size = size_name
                break
        else:
            member.size = '2x12'  # Largest standard size

    return truss


# =============================================================================
# SVG RENDERING
# =============================================================================

def render_truss_svg(truss: TrussDesign, scale: float = 0.1,
                     show_forces: bool = False, show_dimensions: bool = True) -> str:
    """
    Render truss to SVG for display in sections or details.

    Args:
        truss: Truss design to render
        scale: Scale factor
        show_forces: Show member force values
        show_dimensions: Show key dimensions

    Returns:
        SVG string
    """
    # Calculate bounds
    margin = 500
    all_x = [j.position.x for j in truss.joints]
    all_y = [j.position.y for j in truss.joints]

    min_x = min(all_x) - margin
    max_x = max(all_x) + margin
    min_y = min(all_y) - margin
    max_y = max(all_y) + margin

    vb_w = max_x - min_x
    vb_h = max_y - min_y

    lines = []
    lines.append(f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg"
     width="{int(vb_w * scale)}" height="{int(vb_h * scale)}"
     viewBox="{min_x} {min_y} {vb_w} {vb_h}">''')

    lines.append('  <title>Truss Detail</title>')

    # Styles
    lines.append('''  <style>
    .member { stroke: #333; stroke-width: 8; stroke-linecap: round; }
    .member-tension { stroke: #2196F3; }
    .member-compression { stroke: #f44336; }
    .top-chord { stroke-width: 12; }
    .bottom-chord { stroke-width: 12; }
    .joint { fill: #333; }
    .support { fill: #666; stroke: #333; stroke-width: 4; }
    .dimension { font-family: Arial; font-size: 120px; fill: #666; }
    .force-label { font-family: Arial; font-size: 100px; fill: #333; }
  </style>''')

    # Flip Y for SVG (Y increases downward)
    flip_y = max_y

    lines.append(f'<g transform="translate(0, {flip_y}) scale(1, -1)">')

    # Draw members
    for member in truss.members:
        x1, y1 = member.start.x, member.start.y
        x2, y2 = member.end.x, member.end.y

        # Determine class based on member type and force
        classes = ['member']
        if member.member_type == MemberType.TOP_CHORD:
            classes.append('top-chord')
        elif member.member_type == MemberType.BOTTOM_CHORD:
            classes.append('bottom-chord')

        if show_forces and truss.is_analyzed:
            if member.axial_force > 0:
                classes.append('member-tension')
            elif member.axial_force < 0:
                classes.append('member-compression')

        lines.append(f'  <line x1="{x1:.0f}" y1="{y1:.0f}" x2="{x2:.0f}" y2="{y2:.0f}" class="{" ".join(classes)}"/>')

    # Draw joints
    for joint in truss.joints:
        x, y = joint.position.x, joint.position.y

        if joint.is_support:
            # Draw triangle for pin, circle for roller
            if joint.support_type == "pin":
                points = f"{x},{y - 80} {x - 60},{y - 140} {x + 60},{y - 140}"
                lines.append(f'  <polygon points="{points}" class="support"/>')
            else:  # roller
                lines.append(f'  <circle cx="{x}" cy="{y - 100}" r="50" class="support"/>')
                lines.append(f'  <line x1="{x - 70}" y1="{y - 160}" x2="{x + 70}" y2="{y - 160}" stroke="#333" stroke-width="6"/>')

        lines.append(f'  <circle cx="{x:.0f}" cy="{y:.0f}" r="30" class="joint"/>')

    lines.append('</g>')

    # Dimensions (outside flip group for right-side-up text)
    if show_dimensions:
        # Span dimension
        lines.append(f'<line x1="0" y1="{flip_y + 300}" x2="{truss.span}" y2="{flip_y + 300}" stroke="#666" stroke-width="4"/>')
        lines.append(f'<text x="{truss.span/2}" y="{flip_y + 450}" text-anchor="middle" class="dimension">{truss.span:.0f}mm</text>')

        # Height dimension
        lines.append(f'<text x="{-300}" y="{flip_y - truss.ridge_height/2}" text-anchor="middle" class="dimension" transform="rotate(-90, {-300}, {flip_y - truss.ridge_height/2})">{truss.ridge_height:.0f}mm</text>')

    lines.append('</svg>')

    return '\n'.join(lines)


# =============================================================================
# MAIN / TESTING
# =============================================================================

def main():
    """Test truss generation and analysis."""

    print("Truss Calculator Test")
    print("=" * 50)

    # Create a Fink truss for a 10m span
    truss = create_truss(TrussType.FINK, span=10000, pitch=6)

    print(f"\nTruss Type: {truss.truss_type.value}")
    print(f"Span: {truss.span}mm")
    print(f"Pitch: {truss.pitch}:12")
    print(f"Heel Height: {truss.heel_height:.0f}mm")
    print(f"Ridge Height: {truss.ridge_height:.0f}mm")
    print(f"Members: {len(truss.members)}")
    print(f"Joints: {len(truss.joints)}")

    # Apply loads
    truss = calculate_truss_loads(truss, dead_load=0.5, live_load=1.5)
    print(f"\nLoads applied: {len(truss.loads)}")

    # Analyze
    truss = analyze_truss(truss)
    print(f"\nAnalysis complete:")
    print(f"  Max Tension: {truss.max_tension:.0f}N")
    print(f"  Max Compression: {truss.max_compression:.0f}N")

    # Size members
    truss = size_truss_members(truss)
    print(f"\nMember sizes:")
    for member in truss.members:
        print(f"  {member.id}: {member.size} ({member.member_type.value})")

    # Generate SVG
    svg = render_truss_svg(truss, show_forces=True)

    # Save test output
    from pathlib import Path
    output_path = Path(__file__).parent.parent.parent / "Shared" / "TestData" / "output" / "truss_test.svg"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w') as f:
        f.write(svg)
    print(f"\nSVG saved to: {output_path}")


if __name__ == '__main__':
    main()
