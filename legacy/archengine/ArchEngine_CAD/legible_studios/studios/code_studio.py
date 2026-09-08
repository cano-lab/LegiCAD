"""
Code Studio - Ontario Building Code (OBC) compliance validator for permit drawings.

Reads building data conforming to Shared/Schemas/qbd_output.schema.json:
- rooms: object map keyed by room_id, each with bounds, area (in unit^2), center, room_type, zone
- doors: flat list, each with x/y/width/type/wall_index/offset/room1/room2
- windows: flat list, each with wall_index/offset/width/height/sill_height/type/room
- walls (walls_batch): flat list, each with start/end/height/category/wall_type/rooms
- unit: "mm" or "feet" — controls all linear and area conversions

Validators are unit-aware: works on both ARCHENGINE (mm) and REVIT (feet) outputs.
"""

import math
from typing import Dict, List, Any, Tuple, Optional
from ..core.constraint_lens import ConstraintLens, LensResult, ConstraintPriority


# OBC residential reference values (Part 9 - Houses and Small Buildings)
MIN_EGRESS_DOOR_WIDTH_M = 0.810           # OBC 9.5.5.2 (810 mm)
MIN_HALLWAY_WIDTH_M = 0.860               # OBC 9.5.6.1 residential
MIN_BEDROOM_EGRESS_WINDOW_AREA_M2 = 0.35  # OBC 9.9.10.1
MIN_BEDROOM_EGRESS_WINDOW_DIM_M = 0.38    # OBC 9.9.10.1
MIN_NATURAL_LIGHT_RATIO = 0.05            # OBC 9.7.1 (5% of floor area)
HABITABLE_ROOM_TYPES = {
    "living", "dining", "kitchen", "bedroom", "primary_bedroom",
    "bedroom_2", "bedroom_3", "den", "office", "family",
}
CIRCULATION_ROOM_TYPES = {"hallway", "corridor", "entry", "mudroom"}


def _to_meters(value: float, unit: str) -> float:
    if unit == "mm":
        return value / 1000.0
    if unit == "feet":
        return value * 0.3048
    return value


def _to_m2(value: float, unit: str) -> float:
    if unit == "mm":
        return value / 1_000_000.0
    if unit == "feet":
        return value * 0.092903  # sqft -> m^2
    return value


class CodeStudio(ConstraintLens):
    """OBC compliance checks: egress, corridors, natural light, accessibility."""

    @property
    def name(self) -> str:
        return "Code Studio (OBC)"

    @property
    def description(self) -> str:
        return "Ontario Building Code Part 9 compliance for residential"

    def analyze(self, geometry: Dict[str, Any], intensity: float = 0.5) -> LensResult:
        result = LensResult(studio_name=self.name)

        unit = geometry.get("unit", "mm")
        rooms = self._iter_rooms(geometry)
        doors = geometry.get("doors") or []
        windows = geometry.get("windows") or []
        stairs = geometry.get("stairs") or []

        # Egress paths
        egress_paths = self._egress_paths(rooms, doors, unit)
        result.metrics["egress_paths"] = len(egress_paths)
        result.metrics["min_egress_door_width_m"] = round(
            min((p["width_m"] for p in egress_paths), default=0.0), 3
        )

        # Corridors
        corridors = self._identify_corridors(rooms, unit)
        result.metrics["corridors"] = len(corridors)
        result.metrics["min_corridor_width_m"] = round(
            min((c["width_m"] for c in corridors), default=0.0), 3
        )

        # Natural light per habitable room
        light = self._natural_light(rooms, windows, unit)
        result.metrics["habitable_rooms"] = light["habitable_rooms"]
        result.metrics["habitable_rooms_with_light"] = light["compliant"]
        result.metrics["natural_light_compliance"] = round(light["ratio"], 3)

        # Bedroom egress windows
        bedroom_check = self._bedroom_egress_windows(rooms, windows, unit)
        result.metrics["bedrooms"] = bedroom_check["bedrooms"]
        result.metrics["bedrooms_with_egress_window"] = bedroom_check["with_egress"]

        # Violations
        if intensity > 0.3:
            for path in egress_paths:
                if path["width_m"] < MIN_EGRESS_DOOR_WIDTH_M:
                    result.add_violation(
                        message=(
                            f"Door for room '{path['room_id']}' is "
                            f"{path['width_m']*1000:.0f}mm; OBC 9.5.5.2 requires "
                            f"{MIN_EGRESS_DOOR_WIDTH_M*1000:.0f}mm"
                        ),
                        priority=ConstraintPriority.CRITICAL,
                        element_id=f"door_in_room_{path['room_id']}",
                        suggestion=f"Widen to {MIN_EGRESS_DOOR_WIDTH_M*1000:.0f}mm or seek variance",
                    )

            for c in corridors:
                if c["width_m"] < MIN_HALLWAY_WIDTH_M:
                    result.add_violation(
                        message=(
                            f"Hallway '{c['room_id']}' width {c['width_m']*1000:.0f}mm "
                            f"below OBC 9.5.6.1 minimum of {MIN_HALLWAY_WIDTH_M*1000:.0f}mm"
                        ),
                        priority=ConstraintPriority.CRITICAL,
                        element_id=c["room_id"],
                        suggestion="Widen corridor or rearrange adjacent rooms",
                    )

            for room_id, info in bedroom_check["per_room"].items():
                if not info["has_egress"]:
                    result.add_violation(
                        message=(
                            f"Bedroom '{room_id}' lacks an egress window "
                            f"(OBC 9.9.10.1 requires min {MIN_BEDROOM_EGRESS_WINDOW_AREA_M2}m^2 "
                            f"clear opening, {MIN_BEDROOM_EGRESS_WINDOW_DIM_M*1000:.0f}mm min dimension)"
                        ),
                        priority=ConstraintPriority.CRITICAL,
                        element_id=room_id,
                        suggestion="Add a code-compliant egress window to an exterior wall",
                    )

            for room_id, info in light["per_room"].items():
                if not info["compliant"] and info["floor_area_m2"] > 0:
                    result.add_violation(
                        message=(
                            f"Room '{room_id}' window/floor ratio "
                            f"{info['ratio']:.1%} below OBC 9.7.1 minimum "
                            f"of {MIN_NATURAL_LIGHT_RATIO:.0%}"
                        ),
                        priority=ConstraintPriority.WARNING,
                        element_id=room_id,
                        suggestion="Add or enlarge windows on this room's exterior walls",
                    )

            for stair in stairs:
                riser = stair.get("riser_height", stair.get("riser_mm", 0))
                tread = stair.get("tread_depth", stair.get("tread_mm", 0))
                if riser > 200 or (tread and tread < 235):
                    result.add_violation(
                        message=(
                            f"Stair non-compliant (riser {riser}mm, tread {tread}mm); "
                            f"OBC 9.8 limits riser to 200mm, tread minimum 235mm"
                        ),
                        priority=ConstraintPriority.CRITICAL,
                        element_id=stair.get("id", "stair"),
                        suggestion="Adjust to max 200mm riser, min 235mm tread",
                    )

        result.score = self._calculate_score(result)
        return result

    def get_visual_overlays(self, geometry: Dict[str, Any], intensity: float = 0.5) -> List[Dict]:
        return []

    # ------------------------------------------------------------------ helpers

    def _iter_rooms(self, geometry: Dict) -> List[Tuple[str, Dict]]:
        """Return list of (room_id, room_data) tuples regardless of input shape."""
        rooms = geometry.get("rooms")
        if isinstance(rooms, dict):
            return list(rooms.items())
        if isinstance(rooms, list):
            return [(r.get("id") or r.get("name") or f"room_{i}", r)
                    for i, r in enumerate(rooms) if isinstance(r, dict)]
        return []

    def _egress_paths(self, rooms, doors, unit) -> List[Dict]:
        paths = []
        room_ids = {rid for rid, _ in rooms}
        for door in doors:
            r1 = door.get("room1")
            r2 = door.get("room2")
            for rid in (r1, r2):
                if rid and rid in room_ids:
                    paths.append({
                        "room_id": rid,
                        "width_m": _to_meters(door.get("width", 0), unit),
                        "type": door.get("type", "door"),
                    })
        return paths

    def _identify_corridors(self, rooms, unit) -> List[Dict]:
        out = []
        for room_id, data in rooms:
            room_type = (data.get("room_type") or "").lower()
            zone = (data.get("zone") or "").lower()
            if room_type in CIRCULATION_ROOM_TYPES or zone == "circulation":
                bounds = data.get("bounds") or {}
                w = _to_meters(min(bounds.get("width", 0), bounds.get("height", 0)), unit)
                out.append({"room_id": room_id, "width_m": w})
        return out

    def _windows_for_room(self, room_id: str, windows: List[Dict]) -> List[Dict]:
        return [w for w in windows if w.get("room") == room_id]

    def _natural_light(self, rooms, windows, unit) -> Dict:
        per_room = {}
        habitable = 0
        compliant = 0
        for room_id, data in rooms:
            room_type = (data.get("room_type") or "").lower()
            if room_type not in HABITABLE_ROOM_TYPES and not room_type.startswith("bedroom"):
                continue
            habitable += 1
            floor_area = _to_m2(data.get("area", 0), unit)
            window_area = sum(
                _to_m2((w.get("width", 0) * w.get("height", 0)), unit)
                for w in self._windows_for_room(room_id, windows)
            )
            ratio = window_area / floor_area if floor_area > 0 else 0.0
            ok = ratio >= MIN_NATURAL_LIGHT_RATIO
            if ok:
                compliant += 1
            per_room[room_id] = {
                "floor_area_m2": floor_area,
                "window_area_m2": window_area,
                "ratio": ratio,
                "compliant": ok,
            }
        return {
            "per_room": per_room,
            "habitable_rooms": habitable,
            "compliant": compliant,
            "ratio": (compliant / habitable) if habitable else 0.0,
        }

    def _bedroom_egress_windows(self, rooms, windows, unit) -> Dict:
        per_room = {}
        bedrooms = 0
        with_egress = 0
        for room_id, data in rooms:
            room_type = (data.get("room_type") or "").lower()
            if not (room_type.startswith("bedroom") or room_type == "primary_bedroom"):
                continue
            bedrooms += 1
            has_egress = False
            for w in self._windows_for_room(room_id, windows):
                wm = _to_meters(w.get("width", 0), unit)
                hm = _to_meters(w.get("height", 0), unit)
                area_m2 = wm * hm
                min_dim = min(wm, hm)
                if area_m2 >= MIN_BEDROOM_EGRESS_WINDOW_AREA_M2 and min_dim >= MIN_BEDROOM_EGRESS_WINDOW_DIM_M:
                    has_egress = True
                    break
            if has_egress:
                with_egress += 1
            per_room[room_id] = {"has_egress": has_egress}
        return {"per_room": per_room, "bedrooms": bedrooms, "with_egress": with_egress}

    def _calculate_score(self, result: LensResult) -> float:
        score = 1.0
        score -= result.get_critical_count() * 0.5
        score -= result.get_warning_count() * 0.1
        return max(0.0, min(1.0, score))
