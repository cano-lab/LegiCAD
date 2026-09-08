"""
subdivision_solver.py - BSP-style top-down room placement.

Alternative to coordinate_solver's backtracking approach. Starts with the
building envelope and subdivides it room by room, big rooms first. Result:
clean envelope walls (4 for rectangle, 6 for L), no unused interior space.

Algorithm (per user spec 2026-04-30):
    1. Anchor: place entry at the entry edge (small footprint).
    2. Hallway: reserve a minimal strip (44") from entry into the building.
    3. BIG rooms (program-defined): living, dining, kitchen, primary_bedroom,
       garage. Cut perpendicular to longest edge of best free rectangle;
       slice anchored on the side that satisfies must_touch.
    4. MEDIUM rooms: bedrooms, primary_bath, office, mudroom.
    5. SMALL rooms: bathrooms, closets, laundry, pantry — fill remainder.
    6. Verify min_area; if any room infeasible, shrink big-room targets and
       retry (one iteration max for now).

Phase 1 (this version): rectangular envelope only, simple greedy placement.
L-envelope, budget integration, and look-ahead heuristics deferred.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Set

from collections import defaultdict
from coordinate_solver import Rect, Point, PlacedRoom, PlacedLayout, WallCoordinate
from wall_graph import WallType, OpeningType
from room_relationships import SpatialGraph


# =============================================================================
# ROOM TIERS — program role determines size priority
# =============================================================================

BIG_ROOM_TYPES = {
    "living", "great_room", "dining", "kitchen",
    "primary_bedroom", "garage",
}

MEDIUM_ROOM_TYPES = {
    "bedroom", "primary_bath", "office", "mudroom", "foyer",
}

SMALL_ROOM_TYPES = {
    "bathroom", "powder_room",
    "closet", "walk_in_closet", "coat_closet",
    "laundry", "pantry", "mechanical",
}


def _room_tier(room_id: str, room_type: str) -> str:
    """Return 'big', 'medium', or 'small' based on program role."""
    base = room_type
    # Strip numeric suffix: "bedroom_2" -> "bedroom"
    if room_type not in (BIG_ROOM_TYPES | MEDIUM_ROOM_TYPES | SMALL_ROOM_TYPES):
        base = room_id.split("_")[0]
    if base in BIG_ROOM_TYPES:
        return "big"
    if base in MEDIUM_ROOM_TYPES:
        return "medium"
    if base in SMALL_ROOM_TYPES:
        return "small"
    return "medium"


# =============================================================================
# SOLVER
# =============================================================================

@dataclass
class SubdivisionResult:
    placed: Dict[str, Rect] = field(default_factory=dict)
    free: List[Rect] = field(default_factory=list)
    unplaced: List[str] = field(default_factory=list)
    iterations: int = 1
    # (child_id, parent_id) en-suite/J&J pairs. A child may appear multiple
    # times with different parents → that's a Jack-and-Jill arrangement
    # (bath shared between two bedrooms, with a door to each).
    suite_pairs: List[Tuple[str, str]] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return len(self.unplaced) == 0


class SubdivisionSolver:
    HALLWAY_WIDTH = 4.0  # feet (~1220mm)
    ENTRY_WIDTH = 6.0
    ENTRY_DEPTH = 8.0
    MIN_ROOM_DIM = 4.0  # feet — minimum closet depth; below this is unusable
    MIN_BEDROOM_DEPTH = 10.0  # feet — narrow dim for a livable bedroom

    def __init__(self, graph: SpatialGraph, envelope: Rect, entry_edge: str = "south"):
        self.graph = graph
        self.envelope = envelope
        self.entry_edge = entry_edge

    def solve(self) -> SubdivisionResult:
        """Two-strip layout: public strip + private wing. The hallway is a
        SHORT stub inside the private wing, with bedrooms clustered on its
        three non-public sides (left/right/back). Each bedroom shares only a
        short edge with the hallway and extends deep into its zone — cuts
        corridor sqft ~70-80% vs a full-width spine."""
        rooms_dict = self.graph.rooms

        entry_room = rooms_dict.get("entry")
        hallway_room = rooms_dict.get("hallway")

        public_rooms = []
        private_rooms = []

        # Suite bundling — small rooms placed inside their parent's slice.
        suite_pairs = {
            "primary_closet": "primary_bedroom",
            "primary_bath": "primary_bedroom",
            "closet_2": "bedroom_2",
            "closet_3": "bedroom_3",
            "closet_4": "bedroom_4",
            "mudroom": "garage",
            "laundry": "garage",
            "entry": "living",
            "dining": "kitchen",
            # Powder room sits off the entry — bundle it inside living's slice
            # so it doesn't slice the public strip and break garage→living.
            "powder_room": "living",
        }
        bundles: Dict[str, List] = defaultdict(list)
        for child_id, parent_id in suite_pairs.items():
            if child_id in rooms_dict and parent_id in rooms_dict:
                bundles[parent_id].append((child_id, rooms_dict[child_id]))

        for rid, r in rooms_dict.items():
            if rid == "hallway":
                continue
            if rid in suite_pairs:
                continue
            z = _zone_of(rid, r.room_type)
            if z in ("public", "service"):
                public_rooms.append(r)
            else:
                private_rooms.append(r)

        for r in rooms_dict.values():
            r.target_area = max(r.min_area * 1.10, r.min_area)
        for parent_id, children in bundles.items():
            parent = rooms_dict.get(parent_id)
            if parent:
                child_total = sum(c.target_area for _, c in children)
                parent.target_area = parent.target_area + child_total
                parent._bundled_children = children

        env = self.envelope

        # Hallway is INSIDE the private wing now — only two strips at top level.
        public_area = sum(r.target_area for r in public_rooms)
        private_area = sum(r.target_area for r in private_rooms)

        # Wing depth budget — back zone (primary, ≥10ft) + side zones (≥10ft
        # for a single bedroom, +6ft for an extra stacked bath). Grow when
        # 4+ private rooms force stacking on a side.
        if len(private_rooms) >= 4:
            min_wing_depth = self.MIN_BEDROOM_DEPTH + self.MIN_BEDROOM_DEPTH + self.MIN_ROOM_DIM * 1.5
        else:
            min_wing_depth = self.MIN_BEDROOM_DEPTH * 2

        if self.entry_edge in ("south", "north"):
            public_h = env.height * (public_area / max(public_area + private_area, 1))
            public_h = max(self.MIN_ROOM_DIM * 2, public_h)
            private_wing_h = env.height - public_h
            if private_wing_h < min_wing_depth:
                private_wing_h = min(min_wing_depth, env.height - self.MIN_ROOM_DIM * 2)
                public_h = env.height - private_wing_h

            if self.entry_edge == "south":
                public_strip = Rect(env.x, env.y, env.width, public_h)
                private_wing = Rect(env.x, env.y + public_h, env.width, private_wing_h)
            else:  # north
                private_wing = Rect(env.x, env.y, env.width, private_wing_h)
                public_strip = Rect(env.x, env.y + private_wing_h, env.width, public_h)
        else:
            public_w = env.width * (public_area / max(public_area + private_area, 1))
            public_w = max(self.MIN_ROOM_DIM * 2, public_w)
            private_wing_w = env.width - public_w
            if private_wing_w < min_wing_depth:
                private_wing_w = min(min_wing_depth, env.width - self.MIN_ROOM_DIM * 2)
                public_w = env.width - private_wing_w

            if self.entry_edge == "west":
                public_strip = Rect(env.x, env.y, public_w, env.height)
                private_wing = Rect(env.x + public_w, env.y, private_wing_w, env.height)
            else:  # east
                private_wing = Rect(env.x, env.y, private_wing_w, env.height)
                public_strip = Rect(env.x + private_wing_w, env.y, public_w, env.height)

        # Bathroom min width — use a conservative depth proxy (~half the wing
        # short axis) to ensure BSP allocates ≥6ft width to baths.
        BATH_MIN_WIDTH = 6.0
        if self.entry_edge in ("south", "north"):
            bath_proxy_depth = max(private_wing.height * 0.45, BATH_MIN_WIDTH)
        else:
            bath_proxy_depth = max(private_wing.width * 0.45, BATH_MIN_WIDTH)
        for r in private_rooms:
            rt = r.room_type
            base = rt if rt in PRIVATE_ZONE else r.id.split("_")[0]
            if base in ("bathroom", "primary_bath", "powder_room"):
                r.target_area = max(r.target_area, BATH_MIN_WIDTH * bath_proxy_depth)

        placed: Dict[str, Rect] = {}

        for rid, rect in self._bsp_strip(public_strip, list(public_rooms)).items():
            placed[rid] = rect

        placed.update(self._layout_private_clustered(
            private_wing, hallway_room, private_rooms, self.entry_edge))

        # Build the suite_pairs list. Static entries from the bundling dict,
        # plus J&J entries for any shared bath placed in the asymmetric layout.
        pair_list: List[Tuple[str, str]] = list(suite_pairs.items())
        # Detect the J&J shared bath (smallest non-primary bath, if 4+ private rooms).
        if len(private_rooms) >= 4:
            def _is_bath(r):
                base = r.room_type if r.room_type in PRIVATE_ZONE else r.id.split("_")[0]
                return base in ("bathroom", "powder_room") and r.id != "primary_bath"
            sorted_priv = sorted(private_rooms, key=lambda r: -r.target_area)
            non_bath = [r for r in sorted_priv if not _is_bath(r)]
            bath_share = next((r for r in reversed(sorted_priv) if _is_bath(r)), None)
            if bath_share and len(non_bath) >= 3:
                # Asymmetric layout pairs bath_share with bed_back (non_bath[1])
                # and bed_side (non_bath[2]). Add both pairs.
                pair_list.append((bath_share.id, non_bath[1].id))
                pair_list.append((bath_share.id, non_bath[2].id))

        unplaced = [rid for rid in rooms_dict if rid not in placed]
        return SubdivisionResult(placed=placed, free=[], unplaced=unplaced,
                                  suite_pairs=pair_list)

    def _layout_private_clustered(self, wing: Rect, hallway_room,
                                   rooms: List, entry_edge: str) -> Dict[str, Rect]:
        """Asymmetric cluster: primary on one full-height side, secondary
        bedrooms flanking a short hallway, shared bath as Jack-and-Jill.

        For south entry with 4 rooms (primary + 2 bedrooms + 1 bath):
            +--------+----+--------+--------+
            |        |    |                 |
            | primary|    |   bed_2         |  <- back zone (north)
            | suite  |    |                 |
            |        |hall+--------+--------+
            |        |    | bed_3  | bath_2 |  <- side_b (south of back),
            |        |    |        |        |     bath_2 in NE corner pocket
            +--------+----+--------+--------+
            |          public area          |
            +-------------------------------+

        bath_2 borders bed_2 (north) and bed_3 (west) → J&J doors on both,
        no en-suite trap. All bedrooms have direct hallway access:
        - primary via hallway west edge
        - bed_3 via hallway east edge
        - bed_2 via hallway tip (4ft segment)
        """
        if not rooms:
            return {}

        HW = self.HALLWAY_WIDTH
        MIN = self.MIN_ROOM_DIM
        BEDROOM_D = self.MIN_BEDROOM_DEPTH

        # Currently this layout strategy is south-only; fall back to the
        # symmetric cluster for other entry edges.
        if entry_edge != "south":
            return self._layout_private_symmetric(wing, hallway_room, rooms, entry_edge)

        rooms_sorted = sorted(rooms, key=lambda r: -r.target_area)

        # Identify the J&J shared bath (smallest non-primary bath room).
        def is_bath(r):
            base = r.room_type if r.room_type in PRIVATE_ZONE else r.id.split("_")[0]
            return base in ("bathroom", "powder_room") and r.id != "primary_bath"

        bath_share = next((r for r in reversed(rooms_sorted) if is_bath(r)), None)
        non_bath = [r for r in rooms_sorted if r is not bath_share]

        # Pick rooms by role.
        primary = non_bath[0] if non_bath else None
        bed_back = non_bath[1] if len(non_bath) >= 2 else None    # in back zone
        bed_side = non_bath[2] if len(non_bath) >= 3 else None    # in side_b lower
        # If <3 non-bath rooms, fall back to symmetric layout.
        if not (primary and bed_back and bed_side):
            return self._layout_private_symmetric(wing, hallway_room, rooms, entry_edge)

        placed: Dict[str, Rect] = {}

        # Geometry: hallway is CENTERED on wing.width — the public BSP also
        # places the central pass-through public room (living) in the wing's
        # middle x range, so a centered hallway lands over a pass-through
        # neighbor and gets a working egress door.
        hall_x = wing.x + (wing.width - HW) / 2

        # side_a (primary): full wing height, west of hallway
        a_w = hall_x - wing.x
        side_a_zone = Rect(wing.x, wing.y, a_w, wing.height)

        # Lower-east zone (bed_side, the secondary bedroom touching hallway)
        lower_east_w = wing.x2 - (hall_x + HW)
        hall_len = max(BEDROOM_D, bed_side.target_area / max(lower_east_w, 1))
        # Keep some depth for upper zone.
        hall_len = min(hall_len, wing.height - BEDROOM_D)
        upper_h = wing.height - hall_len
        if upper_h < BEDROOM_D:
            upper_h = BEDROOM_D
            hall_len = wing.height - upper_h

        hallway_rect = Rect(hall_x, wing.y, HW, hall_len)
        bed_side_zone = Rect(hall_x + HW, wing.y, lower_east_w, hall_len)

        # Upper east zone (above hallway tip): extends from hall_x to wing.x2
        # — absorbs the strip directly above the hallway. Holds bed_back +
        # bath_share in a NE pocket arrangement.
        upper_zone = Rect(hall_x, wing.y + hall_len,
                          wing.x2 - hall_x, upper_h)

        if bath_share:
            pocket_w = max(BEDROOM_D, bath_share.target_area / max(upper_h, 1))
            pocket_w = min(pocket_w, upper_zone.width * 0.5)
            bed_back_zone = Rect(upper_zone.x, upper_zone.y,
                                 upper_zone.width - pocket_w, upper_h)
            pocket_zone = Rect(upper_zone.x2 - pocket_w, upper_zone.y,
                               pocket_w, upper_h)
        else:
            bed_back_zone = upper_zone
            pocket_zone = None

        # --- Placement ---
        if hallway_room:
            placed["hallway"] = hallway_rect

        # Primary in side_a — bundler handles its bath/closet children.
        placed[primary.id] = side_a_zone
        children = getattr(primary, "_bundled_children", None)
        if children:
            placed.update(self._place_bundled_children(
                side_a_zone, primary, children, "y"))

        # bed_side in lower east
        placed[bed_side.id] = bed_side_zone
        children_side = getattr(bed_side, "_bundled_children", None)
        if children_side:
            placed.update(self._place_bundled_children(
                bed_side_zone, bed_side, children_side, "y"))

        # bed_back in upper east zone (west portion if bath_share present)
        placed[bed_back.id] = bed_back_zone
        children_back = getattr(bed_back, "_bundled_children", None)
        if children_back:
            placed.update(self._place_bundled_children(
                bed_back_zone, bed_back, children_back,
                "x" if bed_back_zone.width >= bed_back_zone.height else "y"))

        # bath_share in NE pocket
        if bath_share and pocket_zone is not None:
            placed[bath_share.id] = pocket_zone

        # Place any remaining rooms (>4 case) — stack via BSP within bed_back_zone.
        remaining = [r for r in rooms
                     if r.id not in placed and r is not primary
                     and r is not bed_back and r is not bed_side
                     and r is not bath_share]
        if remaining:
            back_set = [bed_back] + remaining
            del placed[bed_back.id]
            sub = self._bsp_strip(
                bed_back_zone, back_set,
                axis="x" if bed_back_zone.width >= bed_back_zone.height else "y")
            placed.update(sub)

        return placed

    def _layout_private_symmetric(self, wing: Rect, hallway_room,
                                   rooms: List, entry_edge: str) -> Dict[str, Rect]:
        """Symmetric 3-side cluster (used when asymmetric doesn't apply)."""
        if not rooms:
            return {}

        HW = self.HALLWAY_WIDTH
        MIN = self.MIN_ROOM_DIM
        BEDROOM_D = self.MIN_BEDROOM_DEPTH

        rooms_sorted = sorted(rooms, key=lambda r: -r.target_area)
        back_rooms = [rooms_sorted[0]] if rooms_sorted else []
        side_a_rooms = [rooms_sorted[1]] if len(rooms_sorted) >= 2 else []
        side_b_rooms = [rooms_sorted[2]] if len(rooms_sorted) >= 3 else []
        for r in rooms_sorted[3:]:
            if (sum(rr.target_area for rr in side_a_rooms) <=
                sum(rr.target_area for rr in side_b_rooms)):
                side_a_rooms.append(r)
            else:
                side_b_rooms.append(r)

        side_area = (sum(r.target_area for r in side_a_rooms) +
                     sum(r.target_area for r in side_b_rooms))

        def stacked_depth(side_list):
            d = 0.0
            for r in side_list:
                base = r.room_type if r.room_type in PRIVATE_ZONE else r.id.split("_")[0]
                d += BEDROOM_D if base in ("bedroom", "primary_bedroom",
                                            "office") else MIN * 1.5
            return d

        min_side_extent = max(stacked_depth(side_a_rooms),
                              stacked_depth(side_b_rooms), MIN * 1.5)
        min_back_extent = BEDROOM_D if back_rooms else MIN * 1.5

        if entry_edge in ("south", "north"):
            side_zone_h_avail = wing.width - HW
            area_side_h = (side_area / max(side_zone_h_avail, MIN)
                           if side_area > 0 else MIN)
            side_zone_h = max(min_side_extent, area_side_h)
            max_side_extent = wing.height - min_back_extent
            if side_zone_h > max_side_extent:
                side_zone_h = max(MIN * 1.5, max_side_extent)
            back_h = wing.height - side_zone_h
            if back_h < MIN * 1.5:
                back_h = MIN * 1.5
                side_zone_h = wing.height - back_h

            hall_x = wing.x + (wing.width - HW) / 2

            if entry_edge == "south":
                hall_y = wing.y
                west_zone = Rect(wing.x, wing.y, hall_x - wing.x, side_zone_h)
                east_zone = Rect(hall_x + HW, wing.y,
                                 wing.x2 - (hall_x + HW), side_zone_h)
                back_zone = Rect(wing.x, wing.y + side_zone_h, wing.width, back_h)
            else:
                hall_y = wing.y2 - side_zone_h
                west_zone = Rect(wing.x, hall_y, hall_x - wing.x, side_zone_h)
                east_zone = Rect(hall_x + HW, hall_y,
                                 wing.x2 - (hall_x + HW), side_zone_h)
                back_zone = Rect(wing.x, wing.y, wing.width, back_h)

            hallway_rect = Rect(hall_x, hall_y, HW, side_zone_h)
            side_a_zone, side_b_zone = west_zone, east_zone
            side_axis = "y"
            back_axis = "x" if back_zone.width >= back_zone.height else "y"
        else:
            side_zone_w_avail = wing.height - HW
            area_side_w = (side_area / max(side_zone_w_avail, MIN)
                           if side_area > 0 else MIN)
            side_zone_w = max(min_side_extent, area_side_w)
            max_side_extent = wing.width - min_back_extent
            if side_zone_w > max_side_extent:
                side_zone_w = max(MIN * 1.5, max_side_extent)
            back_w = wing.width - side_zone_w
            if back_w < MIN * 1.5:
                back_w = MIN * 1.5
                side_zone_w = wing.width - back_w

            hall_y = wing.y + (wing.height - HW) / 2

            if entry_edge == "west":
                hall_x = wing.x
                south_zone = Rect(wing.x, wing.y, side_zone_w, hall_y - wing.y)
                north_zone = Rect(wing.x, hall_y + HW,
                                  side_zone_w, wing.y2 - (hall_y + HW))
                back_zone = Rect(wing.x + side_zone_w, wing.y, back_w, wing.height)
            else:
                hall_x = wing.x2 - side_zone_w
                south_zone = Rect(hall_x, wing.y, side_zone_w, hall_y - wing.y)
                north_zone = Rect(hall_x, hall_y + HW,
                                  side_zone_w, wing.y2 - (hall_y + HW))
                back_zone = Rect(wing.x, wing.y, back_w, wing.height)

            hallway_rect = Rect(hall_x, hall_y, side_zone_w, HW)
            side_a_zone, side_b_zone = south_zone, north_zone
            side_axis = "x"
            back_axis = "x" if back_zone.width >= back_zone.height else "y"

        placed: Dict[str, Rect] = {}
        if hallway_room:
            placed["hallway"] = hallway_rect
        if side_a_rooms and side_a_zone.width >= MIN and side_a_zone.height >= MIN:
            placed.update(self._bsp_strip(side_a_zone, side_a_rooms, axis=side_axis))
        if side_b_rooms and side_b_zone.width >= MIN and side_b_zone.height >= MIN:
            placed.update(self._bsp_strip(side_b_zone, side_b_rooms, axis=side_axis))
        if back_rooms and back_zone.width >= MIN and back_zone.height >= MIN:
            placed.update(self._bsp_strip(back_zone, back_rooms, axis=back_axis))
        return placed

    def _bsp_strip(self, strip: Rect, rooms: List, axis: Optional[str] = None) -> Dict[str, Rect]:
        """Recursive BSP within a strip. ALL cuts use the same axis (the strip's
        original LONG axis), so every leaf face spans the strip's short axis
        and therefore shares an edge with the hallway."""
        if axis is None:
            axis = "x" if strip.width >= strip.height else "y"
        if not rooms:
            return {}
        if len(rooms) == 1:
            room = rooms[0]
            placed = {room.id: strip}
            # If this room has bundled children (closets), sub-divide its slice
            # to place them inside (en-suite, not on the corridor).
            children = getattr(room, "_bundled_children", None)
            if children:
                placed.update(self._place_bundled_children(strip, room, children, axis))
            return placed

        rooms_sorted = sorted(rooms, key=lambda r: -r.target_area)
        total = sum(r.target_area for r in rooms)
        half = total / 2.0

        a, b = [], []
        acc = 0.0
        for r in rooms_sorted:
            if acc + r.target_area <= half * 1.2 or not a:
                a.append(r)
                acc += r.target_area
            else:
                b.append(r)
        if not a:
            a.append(b.pop(0))
        if not b:
            b.append(a.pop(-1))

        ratio = sum(r.target_area for r in a) / total

        if axis == "x":
            # All cuts in a horizontal strip stay vertical — every leaf spans full height
            cut = strip.x + strip.width * ratio
            cut = max(strip.x + self.MIN_ROOM_DIM,
                      min(cut, strip.x2 - self.MIN_ROOM_DIM))
            face_a = Rect(strip.x, strip.y, cut - strip.x, strip.height)
            face_b = Rect(cut, strip.y, strip.x2 - cut, strip.height)
        else:
            cut = strip.y + strip.height * ratio
            cut = max(strip.y + self.MIN_ROOM_DIM,
                      min(cut, strip.y2 - self.MIN_ROOM_DIM))
            face_a = Rect(strip.x, strip.y, strip.width, cut - strip.y)
            face_b = Rect(strip.x, cut, strip.width, strip.y2 - cut)

        return {**self._bsp_strip(face_a, a, axis),
                **self._bsp_strip(face_b, b, axis)}

    def _place_bundled_children(self, parent_slice: Rect, parent, children: List,
                                 strip_axis: str) -> Dict[str, Rect]:
        """Place bundled children (closets, en-suite bath, etc.) inside the
        parent slice. Picks the cut orientation (height-wise band vs width-wise
        band) that leaves the parent with the most livable shape — important
        for shallow back zones where a height-wise bath strip would starve
        the bedroom remainder."""
        BATH_MIN_DEPTH = 6.5
        LIVABLE_MIN = self.MIN_ROOM_DIM * 1.5
        has_bath = any(
            c.room_type in ("primary_bath", "bathroom") or c.id.split("_")[0] == "bathroom"
            for _, c in children
        )
        child_area = sum(c.target_area for _, c in children)
        result: Dict[str, Rect] = {}

        # Compute candidate band dimensions for both orientations.
        band_h = max(child_area / max(parent_slice.width, 1.0), self.MIN_ROOM_DIM)
        if has_bath:
            band_h = max(band_h, BATH_MIN_DEPTH)
        rem_h = parent_slice.height - band_h

        band_w = max(child_area / max(parent_slice.height, 1.0), self.MIN_ROOM_DIM)
        if has_bath:
            band_w = max(band_w, BATH_MIN_DEPTH)
        rem_w = parent_slice.width - band_w

        h_ok = rem_h >= LIVABLE_MIN and parent_slice.width >= LIVABLE_MIN
        w_ok = rem_w >= LIVABLE_MIN and parent_slice.height >= LIVABLE_MIN

        # Pick orientation. Default to strip-axis natural ('h' for axis='x',
        # 'w' for axis='y') when both viable; force the viable one when only
        # one works; pick the less-bad when neither is great.
        natural = "h" if strip_axis == "x" else "w"
        if h_ok and w_ok:
            cut = natural
        elif h_ok:
            cut = "h"
        elif w_ok:
            cut = "w"
        else:
            cut = "h" if rem_h > rem_w else "w"

        if cut == "h":
            env_cy = self.envelope.y + self.envelope.height / 2
            band_at_top = parent_slice.y + parent_slice.height / 2 > env_cy
            if band_at_top:
                band = Rect(parent_slice.x, parent_slice.y2 - band_h,
                            parent_slice.width, band_h)
                parent_rect = Rect(parent_slice.x, parent_slice.y,
                                   parent_slice.width, parent_slice.height - band_h)
            else:
                band = Rect(parent_slice.x, parent_slice.y,
                            parent_slice.width, band_h)
                parent_rect = Rect(parent_slice.x, parent_slice.y + band_h,
                                   parent_slice.width, parent_slice.height - band_h)
            result[parent.id] = parent_rect
        else:  # cut == 'w'
            env_cx = self.envelope.x + self.envelope.width / 2
            band_at_right = parent_slice.x + parent_slice.width / 2 > env_cx
            if band_at_right:
                band = Rect(parent_slice.x2 - band_w, parent_slice.y,
                            band_w, parent_slice.height)
                parent_rect = Rect(parent_slice.x, parent_slice.y,
                                   parent_slice.width - band_w, parent_slice.height)
            else:
                band = Rect(parent_slice.x, parent_slice.y,
                            band_w, parent_slice.height)
                parent_rect = Rect(parent_slice.x + band_w, parent_slice.y,
                                   parent_slice.width - band_w, parent_slice.height)
            result[parent.id] = parent_rect

        # Split the band among children. Pick the longer axis of the band so
        # children come out closer to square. Enforce MIN_ROOM_DIM per child
        # along the cut axis so smaller children don't end up as slivers when
        # area-proportional split would starve them.
        if len(children) == 1:
            result[children[0][0]] = band
        else:
            cut_along = "x" if band.width >= band.height else "y"
            total_extent = band.width if cut_along == "x" else band.height
            n = len(children)
            min_per = self.MIN_ROOM_DIM
            # If even MIN per child won't fit, fall back to proportional.
            if total_extent < min_per * n:
                sizes = [total_extent * (c.target_area / sum(cc.target_area for _, cc in children))
                         for _, c in children]
            else:
                # Each child gets max(MIN, area-proportional). Renormalize so
                # the sum equals total_extent.
                total_area = sum(c.target_area for _, c in children)
                raw = [max(min_per, total_extent * (c.target_area / total_area))
                       for _, c in children]
                # If raw sums > total_extent, scale down — but never below MIN.
                # Iteratively shave from largest until fits.
                while sum(raw) > total_extent + 1e-3:
                    overshoot = sum(raw) - total_extent
                    # Find largest reducible (above MIN)
                    cuttable = [(i, raw[i]) for i in range(n) if raw[i] > min_per + 1e-3]
                    if not cuttable:
                        break
                    cuttable.sort(key=lambda t: -t[1])
                    take = min(cuttable[0][1] - min_per, overshoot)
                    raw[cuttable[0][0]] -= take
                sizes = raw
            if cut_along == "x":
                cursor = band.x
                for (child_id, _), w in zip(children, sizes):
                    result[child_id] = Rect(cursor, band.y, w, band.height)
                    cursor += w
            else:
                cursor = band.y
                for (child_id, _), h in zip(children, sizes):
                    result[child_id] = Rect(band.x, cursor, band.width, h)
                    cursor += h
        return result

    def _bsp(self, face: Rect, rooms: List, depth: int) -> Dict[str, Rect]:
        """Recursive bisection. Each call: subdivide `face` among `rooms`."""
        if not rooms:
            return {}
        if len(rooms) == 1:
            # Whole face becomes this room
            return {rooms[0].id: face}

        # Pick cut axis: at depth 0, perpendicular to the entry edge
        # (separates front/back). After that, perpendicular to longest edge
        # of the current face (keeps room aspects square-ish).
        if depth == 0 and self.entry_edge in ("south", "north"):
            axis = "y"  # horizontal cut
        elif depth == 0 and self.entry_edge in ("east", "west"):
            axis = "x"  # vertical cut
        else:
            axis = "x" if face.width >= face.height else "y"

        # Partition rooms into two groups
        group_a, group_b = self._partition(rooms, face, axis, depth)
        if not group_a or not group_b:
            # Degenerate split — shouldn't happen with our heuristic but handle it
            single = group_a or group_b
            return self._bsp(face, single, depth + 1)

        # Cut position by area ratio
        area_a = sum(r.target_area for r in group_a)
        area_b = sum(r.target_area for r in group_b)
        ratio = area_a / (area_a + area_b)
        # Clamp ratio so we don't produce tiny faces unable to fit MIN_ROOM_DIM
        if axis == "x":
            min_ratio = self.MIN_ROOM_DIM / face.width
            max_ratio = 1.0 - min_ratio
            ratio = max(min_ratio, min(max_ratio, ratio))
            cut = face.x + face.width * ratio
            face_a = Rect(face.x, face.y, cut - face.x, face.height)
            face_b = Rect(cut, face.y, face.x2 - cut, face.height)
        else:
            min_ratio = self.MIN_ROOM_DIM / face.height
            max_ratio = 1.0 - min_ratio
            ratio = max(min_ratio, min(max_ratio, ratio))
            cut = face.y + face.height * ratio
            face_a = Rect(face.x, face.y, face.width, cut - face.y)
            face_b = Rect(face.x, cut, face.width, face.y2 - cut)

        return {**self._bsp(face_a, group_a, depth + 1),
                **self._bsp(face_b, group_b, depth + 1)}

    def _partition(self, rooms: List, face: Rect, axis: str,
                   depth: int) -> Tuple[List, List]:
        """Split rooms into two groups for a BSP cut. Strategy:
           - Depth 0: zone-based (public/circulation vs private/service)
           - Deeper: balanced area split"""
        if depth == 0:
            front, back = [], []
            for r in rooms:
                z = _zone_of(r.id, r.room_type)
                if z in ("public", "circulation"):
                    front.append(r)
                else:
                    back.append(r)
            if front and back:
                # Anchor "front" to the entry-edge side
                if self.entry_edge in ("south", "west"):
                    return front, back
                return back, front

        # Balanced area split (rooms sorted big→small for stability)
        rooms_sorted = sorted(rooms, key=lambda r: -r.target_area)
        half = sum(r.target_area for r in rooms) / 2.0
        a, b = [], []
        acc_a = 0.0
        for r in rooms_sorted:
            if acc_a + r.target_area <= half * 1.2:
                a.append(r)
                acc_a += r.target_area
            else:
                b.append(r)
        # Make sure both groups are non-empty
        if not a:
            a.append(b.pop(0))
        if not b:
            b.append(a.pop(-1))
        return a, b


class _BSPFailure(Exception):
    """Raised when BSP can't continue. Includes partial placements."""
    def __init__(self, placed: Dict[str, Rect], unplaced: List[str]):
        super().__init__("BSP subdivision failed")
        self.placed = placed
        self.unplaced = unplaced


PUBLIC_ZONE = {"entry", "living", "great_room", "dining", "kitchen",
               "foyer", "powder_room"}
PRIVATE_ZONE = {"primary_bedroom", "bedroom", "primary_bath", "bathroom",
                "primary_closet", "closet", "walk_in_closet", "coat_closet",
                "office"}
SERVICE_ZONE = {"mudroom", "pantry", "mechanical", "laundry", "garage"}
CIRCULATION_ZONE = {"hallway"}


def _zone_of(room_id: str, room_type: str) -> str:
    base = room_type
    if room_type not in (PUBLIC_ZONE | PRIVATE_ZONE | SERVICE_ZONE | CIRCULATION_ZONE):
        base = room_id.split("_")[0]
    if base in PUBLIC_ZONE: return "public"
    if base in PRIVATE_ZONE: return "private"
    if base in SERVICE_ZONE: return "service"
    if base in CIRCULATION_ZONE: return "circulation"
    return "other"

    # ============================ legacy below =============================

    def _solve_pass(self, target_scale: float) -> SubdivisionResult:
        free: List[Rect] = [self.envelope]
        placed: Dict[str, Rect] = {}
        unplaced: List[str] = []

        # 1. Anchor: entry
        entry_rect = self._place_entry()
        placed["entry"] = entry_rect
        free = self._subtract(free, entry_rect)

        # 2. Hallway: minimal strip
        if "hallway" in self.graph.rooms:
            hall = self._place_hallway(entry_rect)
            if hall is not None:
                placed["hallway"] = hall
                free = self._subtract(free, hall)

        # 3-5. Place by tier, biggest first within each tier
        tiers = self._rooms_by_tier()
        for tier_name in ("big", "medium", "small"):
            for room_id in tiers.get(tier_name, []):
                if room_id in placed:
                    continue
                rect, free = self._place_room(room_id, free, placed,
                                               target_scale=target_scale)
                if rect is None:
                    unplaced.append(room_id)
                else:
                    placed[room_id] = rect

        return SubdivisionResult(placed=placed, free=free, unplaced=unplaced)

    # ------------------------------------------------------------------ steps

    def _place_entry(self) -> Rect:
        """Place entry at a corner of the entry edge (not centered) so the
        remainder is a single continuous rectangle, not 4 fragments."""
        env = self.envelope
        w, d = self.ENTRY_WIDTH, self.ENTRY_DEPTH
        if self.entry_edge == "south":
            return Rect(env.x, env.y, w, d)  # SW corner
        if self.entry_edge == "north":
            return Rect(env.x, env.y2 - d, w, d)  # NW corner
        if self.entry_edge == "west":
            return Rect(env.x, env.y, d, w)  # SW corner
        return Rect(env.x2 - d, env.y, d, w)  # SE corner (east entry)

    def _place_hallway(self, entry_rect: Rect) -> Optional[Rect]:
        """Single perpendicular strip from the entry into the building."""
        env = self.envelope
        hw = self.HALLWAY_WIDTH
        edge_clearance = 8.0  # leave 8ft for end-of-hallway rooms
        if self.entry_edge in ("south", "north"):
            x_center = entry_rect.x + entry_rect.width / 2
            if self.entry_edge == "south":
                y_start = entry_rect.y2
                y_end = env.y2 - edge_clearance
            else:
                y_start = env.y + edge_clearance
                y_end = entry_rect.y
            length = y_end - y_start
            if length < self.MIN_ROOM_DIM:
                return None
            return Rect(x_center - hw / 2, y_start, hw, length)
        else:  # west / east
            y_center = entry_rect.y + entry_rect.height / 2
            if self.entry_edge == "west":
                x_start = entry_rect.x2
                x_end = env.x2 - edge_clearance
            else:
                x_start = env.x + edge_clearance
                x_end = entry_rect.x
            length = x_end - x_start
            if length < self.MIN_ROOM_DIM:
                return None
            return Rect(x_start, y_center - hw / 2, length, hw)

    def _rooms_by_tier(self) -> Dict[str, List[str]]:
        """Group rooms by tier; sort each tier biggest-first by min_area."""
        tiers: Dict[str, List[str]] = {"big": [], "medium": [], "small": []}
        for rid, room in self.graph.rooms.items():
            if rid in ("entry", "hallway"):
                continue
            tier = _room_tier(rid, room.room_type)
            tiers[tier].append(rid)
        for tier in tiers:
            tiers[tier].sort(key=lambda rid: -self.graph.rooms[rid].min_area)
        return tiers

    def _place_room(self, room_id: str, free: List[Rect],
                    placed: Dict[str, Rect],
                    target_scale: float = 1.10) -> Tuple[Optional[Rect], List[Rect]]:
        """Pick best free rect, cut a slice for the room."""
        room = self.graph.rooms[room_id]
        target_area = room.min_area * target_scale

        must_touch = self._must_touch_for(room_id, placed)

        # Score and pick best free rect
        candidates: List[Tuple[float, Rect]] = []
        for fr in free:
            if fr.area < room.min_area * 0.95:
                continue
            score = self._score_free(fr, room, target_area, must_touch, placed)
            candidates.append((score, fr))
        if not candidates:
            return None, free

        candidates.sort(key=lambda c: -c[0])
        chosen = candidates[0][1]

        # Cut perpendicular to longest edge
        room_rect = self._cut_slice(chosen, target_area, must_touch, placed)
        if room_rect is None:
            return None, free

        new_free = self._subtract(free, room_rect)
        return room_rect, new_free

    def _cut_slice(self, free_r: Rect, target_area: float,
                   must_touch: List[str], placed: Dict[str, Rect],
                   target_aspect: float = 1.0) -> Optional[Rect]:
        """Cut a corner chunk from free_r sized to ~target_area with a
        roughly square aspect (default). The remainder is L-shaped; _subtract
        handles its decomposition into rectangles for subsequent placements.

        target_aspect: width/height ratio of the room (1.0 = square).
        """
        import math
        # Compute desired room dimensions
        room_h = math.sqrt(target_area / target_aspect)
        room_w = target_area / room_h

        # Clamp to free rect — if it doesn't fit, take the most that does
        if room_w > free_r.width:
            room_w = free_r.width
            room_h = target_area / room_w
        if room_h > free_r.height:
            room_h = free_r.height
            room_w = target_area / room_h
        if room_w > free_r.width:  # second pass after height clamp
            room_w = free_r.width

        # Reject if either dim is unusable
        if room_w < self.MIN_ROOM_DIM or room_h < self.MIN_ROOM_DIM:
            return None

        # Pick which corner to anchor at based on must_touch adjacency
        anchor_x = "low"  # left
        anchor_y = "low"  # bottom
        tol = 0.5
        for mt_id in must_touch:
            if mt_id not in placed:
                continue
            mt = placed[mt_id]
            if abs(mt.x2 - free_r.x) < tol:
                anchor_x = "low"   # mt is left of free → anchor room left edge to free.x
            elif abs(mt.x - free_r.x2) < tol:
                anchor_x = "high"  # mt is right of free → anchor right edge
            if abs(mt.y2 - free_r.y) < tol:
                anchor_y = "low"
            elif abs(mt.y - free_r.y2) < tol:
                anchor_y = "high"

        x = free_r.x if anchor_x == "low" else free_r.x2 - room_w
        y = free_r.y if anchor_y == "low" else free_r.y2 - room_h
        return Rect(x, y, room_w, room_h)

    def _anchor_left(self, free_r: Rect, must_touch: List[str],
                     placed: Dict[str, Rect], axis: str) -> bool:
        """Return True if the slice should anchor on the lower-coordinate side
        of free_r (left if axis=x, bottom if axis=y), False for upper side."""
        tol = 0.5
        for mt_id in must_touch:
            if mt_id not in placed:
                continue
            mt = placed[mt_id]
            if axis == "x":
                # If must_touch is to the LEFT of free_r, anchor left
                if abs(mt.x2 - free_r.x) < tol:
                    return True
                if abs(mt.x - free_r.x2) < tol:
                    return False
            else:
                if abs(mt.y2 - free_r.y) < tol:
                    return True
                if abs(mt.y - free_r.y2) < tol:
                    return False
        return True  # default: anchor low side

    def _must_touch_for(self, room_id: str, placed: Dict[str, Rect]) -> List[str]:
        """Find which already-placed rooms this room must touch."""
        results = []
        # SpatialGraph stores adjacencies in graph.adjacencies (or similar).
        # Use a defensive lookup via room attributes or graph methods.
        for attr in ("must_touch", "adjacencies"):
            data = getattr(self.graph, attr, None)
            if isinstance(data, dict) and room_id in data:
                for other_id in data[room_id]:
                    if other_id in placed:
                        results.append(other_id)
                return results
        # Fallback: heuristic adjacencies based on room type
        room_type = self.graph.rooms[room_id].room_type
        defaults = {
            "living": ["entry", "hallway"],
            "kitchen": ["living", "dining"],
            "dining": ["kitchen", "living"],
            "bedroom": ["hallway"],
            "primary_bedroom": ["hallway"],
            "primary_bath": ["primary_bedroom"],
            "primary_closet": ["primary_bedroom"],
            "bathroom": ["hallway"],
            "powder_room": ["hallway", "living"],
            "closet": ["hallway"],
            "laundry": ["hallway", "mudroom"],
            "garage": ["mudroom", "entry"],
            "mudroom": ["garage", "entry"],
        }
        for adj in defaults.get(room_type, []):
            if adj in placed:
                results.append(adj)
        return results

    def _score_free(self, free_r: Rect, room, target_area: float,
                    must_touch: List[str], placed: Dict[str, Rect]) -> float:
        """Higher = better fit for this room."""
        score = 0.0
        # Strong bonus for adjacency to must_touch
        for mt_id in must_touch:
            if mt_id in placed and self._rects_adjacent(free_r, placed[mt_id]):
                score += 200
        # Prefer rects close to target area (penalize way-too-big rects too)
        area_ratio = free_r.area / target_area
        if area_ratio < 1.0:
            score -= (1.0 - area_ratio) * 100  # penalize too-small
        elif area_ratio > 3.0:
            score -= (area_ratio - 3.0) * 10  # mild penalize way-too-large
        # Aspect ratio: prefer rects that aren't pencil-thin
        aspect = min(free_r.width, free_r.height) / max(free_r.width, free_r.height)
        score += aspect * 30
        return score

    def _rects_adjacent(self, a: Rect, b: Rect) -> bool:
        tol = 0.5
        if abs(a.x2 - b.x) < tol or abs(a.x - b.x2) < tol:
            return a.y < b.y2 and a.y2 > b.y
        if abs(a.y2 - b.y) < tol or abs(a.y - b.y2) < tol:
            return a.x < b.x2 and a.x2 > b.x
        return False

    def _subtract(self, free: List[Rect], placed: Rect) -> List[Rect]:
        """Subtract placed from each free rect, splitting into up to 4 remainders."""
        out: List[Rect] = []
        for f in free:
            # No overlap → unchanged
            if (f.x2 <= placed.x or f.x >= placed.x2 or
                    f.y2 <= placed.y or f.y >= placed.y2):
                out.append(f)
                continue
            # Left strip
            if f.x < placed.x - 0.01:
                out.append(Rect(f.x, f.y, placed.x - f.x, f.height))
            # Right strip
            if f.x2 > placed.x2 + 0.01:
                out.append(Rect(placed.x2, f.y, f.x2 - placed.x2, f.height))
            # Bottom strip (within placed's x range)
            x_lo = max(f.x, placed.x)
            x_hi = min(f.x2, placed.x2)
            if f.y < placed.y - 0.01 and x_hi > x_lo + 0.01:
                out.append(Rect(x_lo, f.y, x_hi - x_lo, placed.y - f.y))
            # Top strip
            if f.y2 > placed.y2 + 0.01 and x_hi > x_lo + 0.01:
                out.append(Rect(x_lo, placed.y2, x_hi - x_lo, f.y2 - placed.y2))
        # Drop slivers smaller than MIN_ROOM_DIM in either dimension
        return [r for r in out if r.width >= self.MIN_ROOM_DIM
                and r.height >= self.MIN_ROOM_DIM]


# =============================================================================
# WALL GENERATION (envelope-based, like coordinate_solver's new path)
# =============================================================================

def _generate_walls(placed: Dict[str, Rect], envelope: Rect,
                    entry_edge: str) -> List[WallCoordinate]:
    """Generate exterior walls along envelope perimeter + interior walls
    between adjacent rooms."""
    walls: List[WallCoordinate] = []

    # Exterior: 4 walls along envelope perimeter
    # Entry door on entry edge
    half_door = 1.5
    edge_perimeter = [
        ("south", Point(envelope.x, envelope.y), Point(envelope.x2, envelope.y)),
        ("east", Point(envelope.x2, envelope.y), Point(envelope.x2, envelope.y2)),
        ("north", Point(envelope.x2, envelope.y2), Point(envelope.x, envelope.y2)),
        ("west", Point(envelope.x, envelope.y2), Point(envelope.x, envelope.y)),
    ]
    entry_rect = placed.get("entry")
    for i, (edge, start, end) in enumerate(edge_perimeter):
        wall = WallCoordinate(
            wall_id=f"ext_{edge}",
            start=start, end=end,
            wall_type=WallType.EXTERIOR,
            room1="exterior", room2="exterior",
        )
        # Attach entry door if this is the entry edge
        if entry_rect is not None and edge == entry_edge:
            if edge == "south":
                cx = entry_rect.x + entry_rect.width / 2
                wall.openings.append((Point(cx - half_door, envelope.y),
                                       Point(cx + half_door, envelope.y),
                                       OpeningType.DOOR))
            elif edge == "north":
                cx = entry_rect.x + entry_rect.width / 2
                wall.openings.append((Point(cx - half_door, envelope.y2),
                                       Point(cx + half_door, envelope.y2),
                                       OpeningType.DOOR))
            elif edge == "west":
                cy = entry_rect.y + entry_rect.height / 2
                wall.openings.append((Point(envelope.x, cy - half_door),
                                       Point(envelope.x, cy + half_door),
                                       OpeningType.DOOR))
            else:
                cy = entry_rect.y + entry_rect.height / 2
                wall.openings.append((Point(envelope.x2, cy - half_door),
                                       Point(envelope.x2, cy + half_door),
                                       OpeningType.DOOR))
        walls.append(wall)

    # Interior: for each room edge, generate walls covering the FULL edge —
    # either as shared walls with neighbors or as walls facing empty interior
    # space (so every room is closed, even with gaps in the layout).
    walls.extend(_generate_interior_walls(placed, envelope))
    return walls


def _generate_interior_walls(placed: Dict[str, Rect],
                             envelope: Rect) -> List[WallCoordinate]:
    """For each room edge that's NOT on the envelope perimeter, ensure it has
    walls covering its full length: shared walls where neighbors meet, plus
    walls where the edge faces empty interior space."""
    tol = 0.5
    walls: List[WallCoordinate] = []
    seen_segments: Set[Tuple[float, float, float, float]] = set()

    def add_wall(start: Point, end: Point, room1: str, room2: str, is_wet: bool = False):
        # Canonical key (lower-coord endpoint first) to dedupe
        if (start.x, start.y) < (end.x, end.y):
            key = (round(start.x, 1), round(start.y, 1), round(end.x, 1), round(end.y, 1))
        else:
            key = (round(end.x, 1), round(end.y, 1), round(start.x, 1), round(start.y, 1))
        if key in seen_segments:
            return
        seen_segments.add(key)
        wt = WallType.WET if is_wet else WallType.FULL
        walls.append(WallCoordinate(
            wall_id=f"int_{room1}__{room2}",
            start=start, end=end, wall_type=wt,
            room1=room1, room2=room2,
        ))

    def on_envelope(coord: float, axis: str) -> bool:
        if axis == "x":
            return abs(coord - envelope.x) < tol or abs(coord - envelope.x2) < tol
        return abs(coord - envelope.y) < tol or abs(coord - envelope.y2) < tol

    def subtract_intervals(start: float, end: float,
                            covered: List[Tuple[float, float, str]]) -> List[Tuple[float, float, str]]:
        """Given an interval [start, end] and a list of (a, b, neighbor_id)
        covered sub-intervals, return list of (a, b, neighbor_id_or_'exterior')
        sub-intervals tiling [start, end]."""
        # Sort by start
        covered = sorted(covered, key=lambda c: c[0])
        result: List[Tuple[float, float, str]] = []
        cursor = start
        for a, b, who in covered:
            if a > cursor + tol:
                result.append((cursor, a, "exterior"))  # uncovered gap
            if b > cursor + tol:
                result.append((max(cursor, a), b, who))
                cursor = b
        if cursor < end - tol:
            result.append((cursor, end, "exterior"))
        # Merge consecutive same-neighbor segments (rare but cleaner)
        merged: List[Tuple[float, float, str]] = []
        for seg in result:
            if merged and merged[-1][2] == seg[2] and abs(merged[-1][1] - seg[0]) < tol:
                merged[-1] = (merged[-1][0], seg[1], seg[2])
            else:
                merged.append(seg)
        return merged

    for room_id, rect in placed.items():
        # 4 edges: south (y=rect.y), north (y=rect.y2), west (x=rect.x), east (x=rect.x2)
        # For each edge, if it's on envelope perimeter skip (exterior covers it).
        # Otherwise compute neighbor coverage and emit walls for each segment.

        # SOUTH edge: y = rect.y, x from rect.x to rect.x2
        if not on_envelope(rect.y, "y"):
            covered = []
            for other_id, other in placed.items():
                if other_id == room_id: continue
                if abs(other.y2 - rect.y) < tol:  # other touches our south
                    a = max(rect.x, other.x)
                    b = min(rect.x2, other.x2)
                    if b > a + tol:
                        covered.append((a, b, other_id))
            for a, b, who in subtract_intervals(rect.x, rect.x2, covered):
                add_wall(Point(a, rect.y), Point(b, rect.y), room_id, who)

        # NORTH edge: y = rect.y2
        if not on_envelope(rect.y2, "y"):
            covered = []
            for other_id, other in placed.items():
                if other_id == room_id: continue
                if abs(other.y - rect.y2) < tol:
                    a = max(rect.x, other.x)
                    b = min(rect.x2, other.x2)
                    if b > a + tol:
                        covered.append((a, b, other_id))
            for a, b, who in subtract_intervals(rect.x, rect.x2, covered):
                add_wall(Point(a, rect.y2), Point(b, rect.y2), room_id, who)

        # WEST edge: x = rect.x
        if not on_envelope(rect.x, "x"):
            covered = []
            for other_id, other in placed.items():
                if other_id == room_id: continue
                if abs(other.x2 - rect.x) < tol:
                    a = max(rect.y, other.y)
                    b = min(rect.y2, other.y2)
                    if b > a + tol:
                        covered.append((a, b, other_id))
            for a, b, who in subtract_intervals(rect.y, rect.y2, covered):
                add_wall(Point(rect.x, a), Point(rect.x, b), room_id, who)

        # EAST edge: x = rect.x2
        if not on_envelope(rect.x2, "x"):
            covered = []
            for other_id, other in placed.items():
                if other_id == room_id: continue
                if abs(other.x - rect.x2) < tol:
                    a = max(rect.y, other.y)
                    b = min(rect.y2, other.y2)
                    if b > a + tol:
                        covered.append((a, b, other_id))
            for a, b, who in subtract_intervals(rect.y, rect.y2, covered):
                add_wall(Point(rect.x2, a), Point(rect.x2, b), room_id, who)

    return walls


def _shared_edge(a: Rect, b: Rect, tol: float) -> Optional[Tuple[Point, Point, bool]]:
    """Return the shared edge between a and b, or None if not adjacent."""
    # Vertical shared edge (a.x2 == b.x or a.x == b.x2)
    if abs(a.x2 - b.x) < tol:
        y1 = max(a.y, b.y)
        y2 = min(a.y2, b.y2)
        if y2 > y1 + tol:
            return Point(a.x2, y1), Point(a.x2, y2), False
    if abs(a.x - b.x2) < tol:
        y1 = max(a.y, b.y)
        y2 = min(a.y2, b.y2)
        if y2 > y1 + tol:
            return Point(a.x, y1), Point(a.x, y2), False
    # Horizontal shared edge
    if abs(a.y2 - b.y) < tol:
        x1 = max(a.x, b.x)
        x2 = min(a.x2, b.x2)
        if x2 > x1 + tol:
            return Point(x1, a.y2), Point(x2, a.y2), False
    if abs(a.y - b.y2) < tol:
        x1 = max(a.x, b.x)
        x2 = min(a.x2, b.x2)
        if x2 > x1 + tol:
            return Point(x1, a.y), Point(x2, a.y), False
    return None


# =============================================================================
# PUBLIC ENTRY POINT
# =============================================================================

def solve_layout_subdivision(graph: SpatialGraph, width: float, depth: float,
                             entry_edge: str = "south") -> PlacedLayout:
    """Convenience function returning a PlacedLayout (compatible with downstream)."""
    envelope = Rect(0, 0, width, depth)
    solver = SubdivisionSolver(graph, envelope, entry_edge)
    result = solver.solve()

    placed_rooms = {rid: PlacedRoom(rid, rect) for rid, rect in result.placed.items()}
    walls = _generate_walls(result.placed, envelope, entry_edge)
    _add_egress_doors(walls, result.placed, envelope, graph,
                      suite_pairs_dict=result.suite_pairs)

    return PlacedLayout(
        rooms=placed_rooms,
        walls=walls,
        building_bounds=envelope,
        is_complete=result.success,
        unplaced_rooms=result.unplaced,
        score=1.0 if result.success else 0.5,
    )


PASS_THROUGH_TYPES = {"entry", "hallway", "foyer", "mudroom",
                      "living", "great_room", "dining", "kitchen"}


def _can_pass_through(room_id: str, graph: SpatialGraph) -> bool:
    """True if this room can be a routing waypoint (not just a destination).
    Bedrooms/bathrooms/closets are destinations; you can't walk through them."""
    if room_id == "entry":
        return True
    room = graph.rooms.get(room_id)
    rt = room.room_type if room else room_id
    base = rt
    # Strip trailing _N: "bedroom_2" -> "bedroom"
    if rt not in PASS_THROUGH_TYPES and rt not in (PRIVATE_ZONE | SERVICE_ZONE):
        base = room_id.split("_")[0]
    return base in PASS_THROUGH_TYPES


def _add_egress_doors(walls: List[WallCoordinate],
                      placed: Dict[str, Rect],
                      envelope: Rect,
                      graph: SpatialGraph,
                      suite_pairs_dict=None) -> None:
    """Mutate walls to add DOOR openings forming a spanning tree from entry.
    Constrained BFS: routes through public/circulation rooms only — never
    crosses private rooms (bedrooms, baths, closets). If a room can't be
    reached under that constraint, prints a diagnostic — that's a layout
    problem the hallway needs to solve."""
    from collections import defaultdict, deque

    if "entry" not in placed:
        return

    # Build adjacency: room_id -> [(neighbor_id, wall_index)]
    # Only consider walls long enough to fit a door — otherwise BFS can latch
    # onto a 2ft sliver of shared edge and never give the room a real opening.
    door_width = 0.9 / 0.3048  # 900mm in feet
    min_door_wall = door_width * 1.2
    adjacency: Dict[str, List[Tuple[str, int]]] = defaultdict(list)
    for i, w in enumerate(walls):
        if w.wall_type == WallType.EXTERIOR:
            continue
        a, b = w.room1, w.room2
        if a in placed and b in placed and a != b:
            seg_len = ((w.end.x - w.start.x) ** 2 +
                       (w.end.y - w.start.y) ** 2) ** 0.5
            if seg_len < min_door_wall:
                continue
            adjacency[a].append((b, i))
            adjacency[b].append((a, i))

    # PASS 1 — En-suite pattern: bathrooms/closets connect to their PARENT
    # bedroom (the adjacent bedroom), not to a corridor. Place these doors
    # first so the constrained BFS treats parent bedrooms as already linked
    # to their en-suite destinations.
    tree_edges: List[Tuple[str, str, int]] = []
    visited = {"entry"}
    paired = set()  # room ids already connected via en-suite

    # Suite pairs come from the solver. Accept either a list of tuples
    # (preferred — supports J&J via duplicate child entries with different
    # parents) or a legacy dict. Fall back to a default static set.
    if suite_pairs_dict is None:
        suite_pairs = [
            ("primary_bath", "primary_bedroom"),
            ("primary_closet", "primary_bedroom"),
            ("closet_2", "bedroom_2"),
            ("closet_3", "bedroom_3"),
            ("closet_4", "bedroom_4"),
            ("mudroom", "garage"),
            ("laundry", "garage"),
            ("entry", "living"),
            ("dining", "kitchen"),
        ]
    elif isinstance(suite_pairs_dict, dict):
        suite_pairs = list(suite_pairs_dict.items())
    else:
        suite_pairs = list(suite_pairs_dict)
    for child, parent in suite_pairs:
        if child not in placed or parent not in placed:
            continue
        # Find wall between them
        for nb_id, wall_idx in adjacency.get(child, []):
            if nb_id == parent:
                tree_edges.append((parent, child, wall_idx))
                paired.add(child)
                break

    # PASS 2a — BFS through PASS-THROUGH rooms only (build the circulation
    # spine: entry → public rooms → hallway). Private rooms are deferred so
    # the next pass can attach them to the highest-priority neighbor (hallway).
    queue = deque(["entry"])
    while queue:
        current = queue.popleft()
        if not _can_pass_through(current, graph):
            continue
        for neighbor, wall_idx in adjacency[current]:
            if neighbor in visited:
                continue
            if not _can_pass_through(neighbor, graph):
                continue  # destinations attached in pass 2b
            visited.add(neighbor)
            tree_edges.append((current, neighbor, wall_idx))
            queue.append(neighbor)

    # PASS 2b — Attach each destination room to its BEST pass-through
    # neighbor. "Best" = hallway > other pass-through. This ensures bedroom
    # doors come off the corridor when possible, not off the living room.
    def neighbor_priority(nb_id: str) -> int:
        if nb_id == "hallway" or nb_id.startswith("hallway_"):
            return 0
        return 1

    for room_id in list(placed):
        if room_id in visited or room_id == "entry":
            continue
        if room_id in paired:
            continue  # already has an en-suite door from pass 1
        best = None  # (priority, parent_id, wall_idx)
        for neighbor, wall_idx in adjacency.get(room_id, []):
            if neighbor in visited and _can_pass_through(neighbor, graph):
                pri = neighbor_priority(neighbor)
                if best is None or pri < best[0]:
                    best = (pri, neighbor, wall_idx)
        if best:
            _, parent, wall_idx = best
            tree_edges.append((parent, room_id, wall_idx))
            visited.add(room_id)

    # After BFS, mark en-suite children visited if their parent is reachable
    for child, parent in suite_pairs:
        if parent in visited and child in placed:
            visited.add(child)

    # Diagnostic: which rooms can't be reached under the privacy constraint?
    unreachable = [r for r in placed if r != "entry" and r not in visited]
    if unreachable:
        print(f"[Egress] WARNING: cannot reach without crossing private rooms: {unreachable}")
        print(f"[Egress]   Need hallway extension to bridge these.")

    # Add one door opening per tree edge, centered on the shared wall
    for parent, child, wall_idx in tree_edges:
        wall = walls[wall_idx]
        seg_start, seg_end = wall.start, wall.end
        seg_len = ((seg_end.x - seg_start.x) ** 2 +
                   (seg_end.y - seg_start.y) ** 2) ** 0.5
        if seg_len < door_width * 1.2:
            continue
        cx = (seg_start.x + seg_end.x) / 2
        cy = (seg_start.y + seg_end.y) / 2
        dx = (seg_end.x - seg_start.x) / seg_len
        dy = (seg_end.y - seg_start.y) / seg_len
        d_start = Point(cx - dx * door_width / 2, cy - dy * door_width / 2)
        d_end = Point(cx + dx * door_width / 2, cy + dy * door_width / 2)
        wall.openings.append((d_start, d_end, OpeningType.DOOR))
