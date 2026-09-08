"""Validation rules for QBD Algebra.

Every state change triggers validation. Invalid states are rejected with explanation.
"""

from typing import Dict, List, Any, Optional, Set, Tuple
from .state import QBDState
from .errors import (
    ValidationResult, QBDError, QBDWarning, ErrorCode, ErrorType,
    ResolutionOption,
    contradiction_error, unsatisfiable_error, unknown_reference_error
)
from .defaults import get_room_defaults, BUILDING_DEFAULTS


class QBDValidator:
    """Validates QBD state for consistency and feasibility."""

    def __init__(self, state: QBDState):
        self.state = state

    def validate_all(self) -> ValidationResult:
        """Run all validation checks."""
        result = ValidationResult(valid=True)

        # Structural validation
        self._validate_structural(result)

        # Logical validation
        self._validate_logical(result)

        # Feasibility validation
        self._validate_feasibility(result)

        return result

    # =========================================================================
    # Structural Validation
    # =========================================================================

    def _validate_structural(self, result: ValidationResult):
        """Validate structural correctness."""

        # Check rooms have required fields
        for room in self.state.rooms:
            if not room.get("name"):
                result.add_error(QBDError(
                    code=ErrorCode.VALIDATION_FAILED,
                    error_type=ErrorType.STRUCTURAL,
                    message=f"Room {room.get('id', 'unknown')} missing required field: name"
                ))

            if not room.get("type"):
                result.add_error(QBDError(
                    code=ErrorCode.VALIDATION_FAILED,
                    error_type=ErrorType.STRUCTURAL,
                    message=f"Room {room.get('id', 'unknown')} missing required field: type"
                ))

            # Check valid area range
            area_min = room.get("area_min")
            area_max = room.get("area_max")
            if area_min is not None and area_max is not None:
                if area_min > area_max:
                    result.add_error(QBDError(
                        code=ErrorCode.INVALID_VALUE,
                        error_type=ErrorType.STRUCTURAL,
                        message=f"Room {room.get('id')}: area_min ({area_min}) > area_max ({area_max})"
                    ))

        # Check unique IDs
        room_ids = [r.get("id") for r in self.state.rooms]
        seen = set()
        for rid in room_ids:
            if rid in seen:
                result.add_error(QBDError(
                    code=ErrorCode.VALIDATION_FAILED,
                    error_type=ErrorType.STRUCTURAL,
                    message=f"Duplicate room ID: {rid}"
                ))
            seen.add(rid)

        # Validate adjacency references
        for adj in self.state.adjacencies:
            if adj.get("room_a") not in room_ids:
                result.add_error(unknown_reference_error(
                    "room", adj.get("room_a")
                ))
            if adj.get("room_b") not in room_ids:
                result.add_error(unknown_reference_error(
                    "room", adj.get("room_b")
                ))

            # Check valid strength
            strength = adj.get("strength")
            if strength not in ("required", "preferred", "optional"):
                result.add_error(QBDError(
                    code=ErrorCode.INVALID_VALUE,
                    error_type=ErrorType.STRUCTURAL,
                    message=f"Invalid adjacency strength: {strength}"
                ))

            # Check valid connection type
            conn_type = adj.get("connection_type")
            if conn_type not in ("open", "door", "visual"):
                result.add_error(QBDError(
                    code=ErrorCode.INVALID_VALUE,
                    error_type=ErrorType.STRUCTURAL,
                    message=f"Invalid connection type: {conn_type}"
                ))

        # Validate separation references
        for sep in self.state.separations:
            if sep.get("room_a") not in room_ids:
                result.add_error(unknown_reference_error(
                    "room", sep.get("room_a")
                ))
            if sep.get("room_b") not in room_ids:
                result.add_error(unknown_reference_error(
                    "room", sep.get("room_b")
                ))

    # =========================================================================
    # Logical Validation
    # =========================================================================

    def _validate_logical(self, result: ValidationResult):
        """Validate logical consistency."""

        # Check for self-references in relationships
        for adj in self.state.adjacencies:
            if adj.get("room_a") == adj.get("room_b"):
                result.add_error(QBDError(
                    code=ErrorCode.VALIDATION_FAILED,
                    error_type=ErrorType.LOGICAL,
                    message="Room cannot be adjacent to itself"
                ))

        for sep in self.state.separations:
            if sep.get("room_a") == sep.get("room_b"):
                result.add_error(QBDError(
                    code=ErrorCode.VALIDATION_FAILED,
                    error_type=ErrorType.LOGICAL,
                    message="Room cannot be separated from itself"
                ))

        # Check for contradictions: same rooms both adjacent and separated
        adj_pairs = self._get_relationship_pairs(self.state.adjacencies)
        sep_pairs = self._get_relationship_pairs(self.state.separations)

        for pair in adj_pairs & sep_pairs:
            room_a, room_b = pair
            result.add_error(contradiction_error(
                f"Rooms {room_a} and {room_b} are both adjacent and separated",
                f"adjacent({room_a}, {room_b})",
                f"separate({room_a}, {room_b})",
                [
                    ResolutionOption("remove_adjacency", "Remove adjacency requirement"),
                    ResolutionOption("remove_separation", "Remove separation requirement"),
                ]
            ))

        # Check ensuite has parent bedroom
        ensuites = [r for r in self.state.rooms if r.get("type") == "ensuite"]
        bedrooms = [r for r in self.state.rooms
                    if r.get("type") in ("bedroom", "primary_bedroom")]

        for ensuite in ensuites:
            # Check if there's an adjacency to a bedroom
            has_parent = False
            for adj in self.state.adjacencies:
                other = None
                if adj.get("room_a") == ensuite.get("id"):
                    other = adj.get("room_b")
                elif adj.get("room_b") == ensuite.get("id"):
                    other = adj.get("room_a")

                if other:
                    for br in bedrooms:
                        if br.get("id") == other:
                            has_parent = True
                            break
                if has_parent:
                    break

            if not has_parent and bedrooms:
                result.add_warning(QBDWarning(
                    warning_type="orphan_ensuite",
                    message=f"Ensuite {ensuite.get('id')} has no adjacent bedroom"
                ))

    def _get_relationship_pairs(self, relationships: List[Dict]) -> Set[Tuple[str, str]]:
        """Get normalized pairs from relationships."""
        pairs = set()
        for rel in relationships:
            a, b = rel.get("room_a"), rel.get("room_b")
            if a and b:
                pairs.add(tuple(sorted([a, b])))
        return pairs

    # =========================================================================
    # Feasibility Validation
    # =========================================================================

    def _validate_feasibility(self, result: ValidationResult):
        """Validate that constraints can be satisfied."""

        # Calculate total program area
        total_area_min = 0
        total_area_max = 0

        for room in self.state.rooms:
            area_min = room.get("area_min")
            area_max = room.get("area_max")

            if area_min is not None:
                total_area_min += area_min
            if area_max is not None:
                total_area_max += area_max

        # Check against footprint constraint
        footprint_max = self.state.constraints.get("footprint_max")
        if footprint_max is not None and total_area_min > 0:
            # Apply circulation factor
            circulation_factor = 1.15  # default balanced
            open_plan = self.state.priorities.get("open_plan", 5)
            if open_plan >= 8:
                circulation_factor = 1.10
            elif open_plan <= 2:
                circulation_factor = 1.20

            program_required = total_area_min * circulation_factor

            if program_required > footprint_max:
                overage = program_required - footprint_max

                # Generate resolution options
                resolutions = [
                    ResolutionOption(
                        "increase_footprint",
                        f"Increase footprint limit to {program_required:.0f} m²",
                        {"new_value": program_required}
                    ),
                ]

                # Suggest rooms to shrink
                for room in sorted(self.state.rooms,
                                   key=lambda r: r.get("area_min", 0),
                                   reverse=True)[:3]:
                    room_area = room.get("area_min", 0)
                    if room_area > 5:  # Only suggest if room is reasonably sized
                        resolutions.append(ResolutionOption(
                            "reduce_room",
                            f"Reduce {room.get('name')} size",
                            {"room_id": room.get("id"), "reduce_by": min(overage, room_area * 0.3)}
                        ))

                result.add_error(unsatisfiable_error(
                    "Program exceeds footprint limit",
                    {
                        "program_required": round(program_required, 1),
                        "footprint_max": footprint_max,
                        "overage": round(overage, 1),
                    },
                    resolutions
                ))

        # Check minimum room sizes
        for room in self.state.rooms:
            room_type = room.get("type")
            area_min = room.get("area_min")

            if room_type and area_min:
                defaults = get_room_defaults(room_type)
                min_buildable = 2.0  # 2 m² absolute minimum

                if area_min < min_buildable:
                    result.add_error(QBDError(
                        code=ErrorCode.VALIDATION_FAILED,
                        error_type=ErrorType.FEASIBILITY,
                        message=f"Room {room.get('name')} too small to build: {area_min} m²"
                    ))

        # Check site fit (if site dimensions specified)
        site = self.state.site
        if site.get("width") and site.get("depth"):
            setbacks = site.get("setbacks") or {}
            left = setbacks.get("left") or 0
            right = setbacks.get("right") or 0
            front = setbacks.get("front") or 0
            rear = setbacks.get("rear") or 0
            buildable_width = site["width"] - (left + right)
            buildable_depth = site["depth"] - (front + rear)
            buildable_area = (buildable_width * buildable_depth) / 1_000_000  # mm² to m²

            if footprint_max and footprint_max > buildable_area:
                result.add_warning(QBDWarning(
                    warning_type="site_constraint",
                    message=f"Footprint limit ({footprint_max} m²) exceeds buildable area ({buildable_area:.1f} m²)"
                ))

        # Warn if approaching limits
        if footprint_max and total_area_min > 0:
            utilization = (total_area_min * 1.15) / footprint_max
            if 0.9 <= utilization < 1.0:
                result.add_warning(QBDWarning(
                    warning_type="tight_fit",
                    message=f"Program is {utilization*100:.0f}% of footprint limit, circulation may be tight"
                ))


def validate_state(state: QBDState) -> ValidationResult:
    """Convenience function to validate a state."""
    validator = QBDValidator(state)
    return validator.validate_all()
