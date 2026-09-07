"""
Cost Studio - Construction cost estimator + constructability checker.

Reads building data conforming to Shared/Schemas/qbd_output.schema.json. Walls
have start/end/height (no precomputed area); rooms are dict-keyed with area
in unit^2; openings are split into doors + windows lists.

Cost rates default to placeholder Ontario residential numbers; should be
replaced with real Ontario-region data per
memory/project_jurisdictional_scope.md.
"""

import math
from typing import Dict, List, Any
from ..core.constraint_lens import ConstraintLens, LensResult, ConstraintPriority


# Placeholder Ontario residential cost rates. Replace with real regional data.
DEFAULT_COST_RATES = {
    "wall_per_m2": 200,        # finished wall assembly
    "floor_per_m2": 250,       # finished floor incl. subfloor
    "roof_per_m2": 280,
    "window_per_m2": 900,
    "door_each": 1400,
    "foundation_per_m3": 450,
    "complexity_overhead": 0.15,  # 15% added for complexity
}

# Per-room-type rate adjustments ($/m² of room area for finishes)
ROOM_TYPE_RATE_PER_M2 = {
    "kitchen": 2700,
    "bathroom": 3200,
    "primary_bath": 3500,
    "primary_bedroom": 1900,
    "bedroom": 1800,
    "living": 2100,
    "dining": 2000,
    "garage": 1100,
    "default": 1900,
}


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
        return value * 0.092903
    return value


def _wall_length_m(wall: Dict, unit: str) -> float:
    start = wall.get("start") or [0, 0, 0]
    end = wall.get("end") or [0, 0, 0]
    if len(start) >= 3 and len(end) >= 3:
        dx = end[0] - start[0]
        dz = end[2] - start[2]
    else:
        dx = end[0] - start[0]
        dz = end[1] - start[1]
    length = math.sqrt(dx * dx + dz * dz)
    return _to_meters(length, unit)


class CostStudio(ConstraintLens):
    """Construction cost estimator + constructability."""

    def __init__(self, cost_rates: Dict = None):
        self.rates = {**DEFAULT_COST_RATES, **(cost_rates or {})}

    @property
    def name(self) -> str:
        return "Cost Studio"

    @property
    def description(self) -> str:
        return "Construction cost estimate + constructability flags"

    def analyze(self, geometry: Dict[str, Any], intensity: float = 0.5) -> LensResult:
        result = LensResult(studio_name=self.name)

        unit = geometry.get("unit", "mm")
        rooms = self._iter_rooms(geometry)
        walls = geometry.get("walls_batch") or geometry.get("walls") or []
        doors = geometry.get("doors") or []
        windows = geometry.get("windows") or []

        # Areas
        total_floor_m2 = sum(_to_m2(r.get("area", 0), unit) for _, r in rooms)
        total_wall_m2 = sum(
            _wall_length_m(w, unit) * _to_meters(w.get("height", 2700), unit)
            for w in walls
        )
        window_area_m2 = sum(
            _to_meters(w.get("width", 0), unit) * _to_meters(w.get("height", 0), unit)
            for w in windows
        )

        # Cost components
        wall_cost = total_wall_m2 * self.rates["wall_per_m2"]
        floor_cost = total_floor_m2 * self.rates["floor_per_m2"]
        roof_cost = total_floor_m2 * self.rates["roof_per_m2"]  # roof area ≈ floor footprint for single-story
        window_cost = window_area_m2 * self.rates["window_per_m2"]
        door_cost = len(doors) * self.rates["door_each"]

        finish_cost = sum(
            _to_m2(r.get("area", 0), unit) * ROOM_TYPE_RATE_PER_M2.get(
                (r.get("room_type") or "").lower(), ROOM_TYPE_RATE_PER_M2["default"]
            )
            for _, r in rooms
        )

        subtotal = wall_cost + floor_cost + roof_cost + window_cost + door_cost + finish_cost
        total_cost = subtotal * (1 + self.rates["complexity_overhead"])

        # Metrics
        result.metrics["unit"] = unit
        result.metrics["total_floor_area_m2"] = round(total_floor_m2, 1)
        result.metrics["total_floor_area_sqft"] = round(total_floor_m2 * 10.7639, 1)
        result.metrics["total_wall_area_m2"] = round(total_wall_m2, 1)
        result.metrics["window_area_m2"] = round(window_area_m2, 2)
        result.metrics["window_to_floor_ratio"] = round(
            window_area_m2 / total_floor_m2 if total_floor_m2 > 0 else 0, 3
        )
        result.metrics["door_count"] = len(doors)
        result.metrics["window_count"] = len(windows)
        result.metrics["wall_count"] = len(walls)
        result.metrics["room_count"] = len(rooms)

        result.metrics["wall_cost"] = round(wall_cost, 0)
        result.metrics["floor_cost"] = round(floor_cost, 0)
        result.metrics["roof_cost"] = round(roof_cost, 0)
        result.metrics["window_cost"] = round(window_cost, 0)
        result.metrics["door_cost"] = round(door_cost, 0)
        result.metrics["finish_cost"] = round(finish_cost, 0)
        result.metrics["estimated_cost_cad"] = round(total_cost, 0)
        result.metrics["cost_per_m2"] = round(
            total_cost / total_floor_m2 if total_floor_m2 > 0 else 0, 0
        )
        result.metrics["cost_per_sqft"] = round(
            (total_cost / total_floor_m2 / 10.7639) if total_floor_m2 > 0 else 0, 0
        )

        # Constructability — penalize complex shapes
        corner_count = self._count_corners(walls, unit)
        unique_lengths = len({round(_wall_length_m(w, unit), 2) for w in walls})
        result.metrics["corner_count"] = corner_count
        result.metrics["unique_wall_lengths"] = unique_lengths
        constructability = self._assess_constructability(corner_count, unique_lengths)
        result.metrics["constructability_score"] = round(constructability, 2)

        # Violations
        if intensity > 0.3:
            for w in walls:
                length_m = _wall_length_m(w, unit)
                if length_m > 6 and (w.get("category") or "").lower() != "exterior":
                    result.add_violation(
                        message=(
                            f"Long non-structural wall ({length_m:.1f}m) may need engineered lumber (LVL)"
                        ),
                        priority=ConstraintPriority.INFO if intensity < 0.7 else ConstraintPriority.WARNING,
                        suggestion="Break into shorter spans or specify LVL header",
                    )

            wtf_ratio = result.metrics["window_to_floor_ratio"]
            if wtf_ratio > 0.40:
                result.add_violation(
                    message=f"High window ratio ({wtf_ratio:.0%}) drives cost and heat loss",
                    priority=ConstraintPriority.INFO,
                    suggestion="Reduce window area in non-light-critical rooms",
                )

            if corner_count > 20:
                result.add_violation(
                    message=f"Complex geometry ({corner_count} corners) increases labor cost",
                    priority=ConstraintPriority.WARNING,
                    suggestion="Simplify building footprint where possible",
                )

        result.score = constructability
        return result

    def get_visual_overlays(self, geometry: Dict[str, Any], intensity: float = 0.5) -> List[Dict]:
        return []

    # ------------------------------------------------------------------ helpers

    def _iter_rooms(self, geometry: Dict):
        rooms = geometry.get("rooms")
        if isinstance(rooms, dict):
            return list(rooms.items())
        if isinstance(rooms, list):
            return [(r.get("id") or r.get("name") or f"room_{i}", r)
                    for i, r in enumerate(rooms) if isinstance(r, dict)]
        return []

    def _count_corners(self, walls: List[Dict], unit: str) -> int:
        """Approximate: count distinct (x, z) endpoints across all walls."""
        endpoints = set()
        for w in walls:
            for pt in (w.get("start") or [], w.get("end") or []):
                if len(pt) >= 3:
                    endpoints.add((round(pt[0], 2), round(pt[2], 2)))
        return len(endpoints)

    def _assess_constructability(self, corner_count: int, unique_lengths: int) -> float:
        score = 1.0
        score -= max(0, corner_count - 8) * 0.01
        score -= max(0, unique_lengths - 10) * 0.02
        return max(0.0, min(1.0, score))
