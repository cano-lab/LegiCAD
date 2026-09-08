#!/usr/bin/env python3
"""
schema_validator.py - JSON Schema validation for ArchEngine building data

Provides validation for:
- Building JSON files against schema
- Wall, door, window, room data structures
- Coordinate system and unit consistency
- Required field checking with helpful error messages
"""

import json
import math
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any, Tuple
from enum import Enum

# Configure module logger
logger = logging.getLogger(__name__)


class ValidationSeverity(Enum):
    """Severity levels for validation issues."""
    ERROR = "error"      # Critical - data cannot be processed
    WARNING = "warning"  # Non-critical but should be fixed
    INFO = "info"        # Informational notes


@dataclass
class ValidationIssue:
    """A single validation issue."""
    severity: ValidationSeverity
    path: str           # JSON path to the issue (e.g., "walls_batch[0].start")
    message: str        # Human-readable description
    expected: Any = None  # Expected value/type
    actual: Any = None    # Actual value/type
    suggestion: str = ""  # How to fix

    def __str__(self) -> str:
        prefix = f"[{self.severity.value.upper()}]"
        msg = f"{prefix} {self.path}: {self.message}"
        if self.suggestion:
            msg += f" (Suggestion: {self.suggestion})"
        return msg


@dataclass
class ValidationResult:
    """Complete validation result."""
    is_valid: bool
    issues: List[ValidationIssue] = field(default_factory=list)
    warnings_count: int = 0
    errors_count: int = 0

    def add_error(self, path: str, message: str, **kwargs):
        self.issues.append(ValidationIssue(
            severity=ValidationSeverity.ERROR,
            path=path,
            message=message,
            **kwargs
        ))
        self.errors_count += 1
        self.is_valid = False

    def add_warning(self, path: str, message: str, **kwargs):
        self.issues.append(ValidationIssue(
            severity=ValidationSeverity.WARNING,
            path=path,
            message=message,
            **kwargs
        ))
        self.warnings_count += 1

    def add_info(self, path: str, message: str, **kwargs):
        self.issues.append(ValidationIssue(
            severity=ValidationSeverity.INFO,
            path=path,
            message=message,
            **kwargs
        ))

    def __str__(self) -> str:
        status = "VALID" if self.is_valid else "INVALID"
        summary = f"Validation {status}: {self.errors_count} errors, {self.warnings_count} warnings"
        if self.issues:
            details = "\n".join(f"  {issue}" for issue in self.issues)
            return f"{summary}\n{details}"
        return summary


# =============================================================================
# TYPE VALIDATORS
# =============================================================================

def is_vec3(value: Any) -> bool:
    """Check if value is a valid 3D vector."""
    if not isinstance(value, (list, tuple)):
        return False
    if len(value) != 3:
        return False
    return all(isinstance(v, (int, float)) for v in value)


def is_vec2(value: Any) -> bool:
    """Check if value is a valid 2D vector."""
    if not isinstance(value, (list, tuple)):
        return False
    if len(value) != 2:
        return False
    return all(isinstance(v, (int, float)) for v in value)


def is_positive_number(value: Any) -> bool:
    """Check if value is a positive number."""
    return isinstance(value, (int, float)) and value > 0


def is_non_negative_number(value: Any) -> bool:
    """Check if value is a non-negative number."""
    return isinstance(value, (int, float)) and value >= 0


def is_valid_height(value: Any, min_height: float = 1000, max_height: float = 20000) -> bool:
    """Check if value is a valid height in mm."""
    if not isinstance(value, (int, float)):
        return False
    return min_height <= value <= max_height


# =============================================================================
# BUILDING DATA VALIDATORS
# =============================================================================

def validate_wall(wall: dict, index: int, result: ValidationResult, walls: List[dict] = None):
    """Validate a single wall entry."""
    path = f"walls_batch[{index}]"

    # Required fields
    if 'start' not in wall:
        result.add_error(path, "Missing required field 'start'",
                        suggestion="Add start point as [x, y, z]")
    elif not is_vec3(wall['start']):
        result.add_error(f"{path}.start", "Invalid start point format",
                        expected="[x, y, z]", actual=wall['start'])

    if 'end' not in wall:
        result.add_error(path, "Missing required field 'end'",
                        suggestion="Add end point as [x, y, z]")
    elif not is_vec3(wall['end']):
        result.add_error(f"{path}.end", "Invalid end point format",
                        expected="[x, y, z]", actual=wall['end'])

    # Check for zero-length wall
    if 'start' in wall and 'end' in wall:
        if is_vec3(wall['start']) and is_vec3(wall['end']):
            start = wall['start']
            end = wall['end']
            length = math.sqrt(
                (end[0] - start[0])**2 +
                (end[1] - start[1])**2 +
                (end[2] - start[2])**2
            )
            if length < 1:  # Less than 1mm
                result.add_error(f"{path}", "Wall has zero or near-zero length",
                                actual=f"length = {length}mm")
            elif length < 100:  # Less than 100mm
                result.add_warning(f"{path}", f"Wall is very short ({length:.0f}mm)")

    # Height validation
    if 'height' in wall:
        if not is_valid_height(wall['height']):
            result.add_error(f"{path}.height", "Invalid wall height",
                            expected="1000-20000mm", actual=wall['height'])
    else:
        result.add_info(f"{path}", "No height specified, will use default (2700mm)")

    # Category validation
    valid_categories = ['exterior', 'interior', 'wet_wall', 'fire_rated', 'garage', 'basement']
    if 'category' in wall:
        if wall['category'] not in valid_categories:
            result.add_warning(f"{path}.category", f"Unknown wall category '{wall['category']}'",
                              suggestion=f"Use one of: {', '.join(valid_categories)}")

    # Wall type validation
    if 'wall_type' in wall:
        if not isinstance(wall['wall_type'], str):
            result.add_error(f"{path}.wall_type", "Wall type must be a string")


def validate_door(door: dict, index: int, result: ValidationResult, walls_count: int):
    """Validate a single door entry."""
    path = f"doors[{index}]"

    # Wall index
    if 'wall_index' not in door:
        result.add_error(path, "Missing required field 'wall_index'")
    elif not isinstance(door['wall_index'], int):
        result.add_error(f"{path}.wall_index", "wall_index must be an integer",
                        actual=type(door['wall_index']).__name__)
    elif door['wall_index'] < 0 or door['wall_index'] >= walls_count:
        result.add_error(f"{path}.wall_index", "wall_index out of range",
                        expected=f"0-{walls_count-1}", actual=door['wall_index'])

    # Offset
    if 'offset' not in door:
        result.add_error(path, "Missing required field 'offset'")
    elif not is_non_negative_number(door['offset']):
        result.add_error(f"{path}.offset", "offset must be a non-negative number")

    # Dimensions
    if 'width' in door:
        if not is_positive_number(door['width']):
            result.add_error(f"{path}.width", "width must be a positive number")
        elif door['width'] < 600 or door['width'] > 3000:
            result.add_warning(f"{path}.width", f"Unusual door width ({door['width']}mm)",
                              suggestion="Typical range is 600-1500mm")

    if 'height' in door:
        if not is_positive_number(door['height']):
            result.add_error(f"{path}.height", "height must be a positive number")
        elif door['height'] < 1800 or door['height'] > 3000:
            result.add_warning(f"{path}.height", f"Unusual door height ({door['height']}mm)",
                              suggestion="Typical range is 2030-2440mm")

    # Door type
    valid_types = ['swing', 'pocket', 'sliding', 'bifold', 'entry', 'french', 'barn']
    if 'type' in door:
        if door['type'] not in valid_types:
            result.add_warning(f"{path}.type", f"Unknown door type '{door['type']}'",
                              suggestion=f"Use one of: {', '.join(valid_types)}")


def validate_window(window: dict, index: int, result: ValidationResult, walls_count: int):
    """Validate a single window entry."""
    path = f"windows[{index}]"

    # Wall index
    if 'wall_index' not in window:
        result.add_error(path, "Missing required field 'wall_index'")
    elif not isinstance(window['wall_index'], int):
        result.add_error(f"{path}.wall_index", "wall_index must be an integer")
    elif window['wall_index'] < 0 or window['wall_index'] >= walls_count:
        result.add_error(f"{path}.wall_index", "wall_index out of range",
                        expected=f"0-{walls_count-1}", actual=window['wall_index'])

    # Offset
    if 'offset' not in window:
        result.add_error(path, "Missing required field 'offset'")
    elif not is_non_negative_number(window['offset']):
        result.add_error(f"{path}.offset", "offset must be a non-negative number")

    # Dimensions
    if 'width' in window:
        if not is_positive_number(window['width']):
            result.add_error(f"{path}.width", "width must be a positive number")
        elif window['width'] < 300 or window['width'] > 4000:
            result.add_warning(f"{path}.width", f"Unusual window width ({window['width']}mm)")

    if 'height' in window:
        if not is_positive_number(window['height']):
            result.add_error(f"{path}.height", "height must be a positive number")
        elif window['height'] < 300 or window['height'] > 3000:
            result.add_warning(f"{path}.height", f"Unusual window height ({window['height']}mm)")

    # Sill height
    if 'sill_height' in window:
        if not is_non_negative_number(window['sill_height']):
            result.add_error(f"{path}.sill_height", "sill_height must be non-negative")
        elif window['sill_height'] < 200:
            result.add_warning(f"{path}.sill_height", "Very low sill height may not meet code")

    # Window type
    valid_types = ['fixed', 'casement', 'double_hung', 'sliding', 'awning', 'hopper', 'picture']
    if 'type' in window:
        if window['type'] not in valid_types:
            result.add_warning(f"{path}.type", f"Unknown window type '{window['type']}'")


def validate_room(room_id: str, room: dict, result: ValidationResult):
    """Validate a single room entry."""
    path = f"rooms.{room_id}"

    # Name
    if 'name' not in room:
        result.add_warning(path, "Room has no name specified")

    # Bounds
    if 'bounds' in room:
        bounds = room['bounds']
        if not isinstance(bounds, dict):
            result.add_error(f"{path}.bounds", "bounds must be an object")
        else:
            for field in ['x', 'y', 'width', 'height']:
                if field not in bounds:
                    result.add_warning(f"{path}.bounds", f"Missing field '{field}'")
                elif not isinstance(bounds[field], (int, float)):
                    result.add_error(f"{path}.bounds.{field}", "Must be a number")

    # Room type
    valid_types = ['living', 'kitchen', 'bedroom', 'bathroom', 'dining', 'office',
                   'garage', 'laundry', 'closet', 'hallway', 'entry', 'utility']
    if 'room_type' in room:
        if room['room_type'] not in valid_types:
            result.add_info(f"{path}.room_type", f"Custom room type '{room['room_type']}'")


def validate_roof(roof: dict, index: int, result: ValidationResult):
    """Validate a roof entry."""
    path = f"roofs[{index}]"

    # Type
    valid_types = ['gable', 'hip', 'dutch_gable', 'shed', 'flat', 'mansard', 'gambrel']
    if 'type' in roof:
        if roof['type'] not in valid_types:
            result.add_warning(f"{path}.type", f"Unknown roof type '{roof['type']}'")

    # Pitch
    if 'pitch' in roof:
        if not isinstance(roof['pitch'], (int, float)):
            result.add_error(f"{path}.pitch", "pitch must be a number")
        elif roof['pitch'] < 0 or roof['pitch'] > 24:
            result.add_warning(f"{path}.pitch", f"Unusual roof pitch ({roof['pitch']}:12)")

    # Surfaces
    if 'surfaces' in roof:
        if not isinstance(roof['surfaces'], list):
            result.add_error(f"{path}.surfaces", "surfaces must be an array")
        else:
            for i, surface in enumerate(roof['surfaces']):
                if 'vertices' not in surface:
                    result.add_error(f"{path}.surfaces[{i}]", "Missing vertices")
                elif not isinstance(surface['vertices'], list):
                    result.add_error(f"{path}.surfaces[{i}].vertices", "vertices must be an array")
                elif len(surface['vertices']) < 3:
                    result.add_error(f"{path}.surfaces[{i}].vertices", "Need at least 3 vertices")


# =============================================================================
# MAIN VALIDATION FUNCTION
# =============================================================================

def validate_building_data(data: dict, strict: bool = False) -> ValidationResult:
    """
    Validate complete building data.

    Args:
        data: Building data dictionary
        strict: If True, warnings become errors

    Returns:
        ValidationResult with all issues found
    """
    result = ValidationResult(is_valid=True)

    # Top-level structure
    if not isinstance(data, dict):
        result.add_error("", "Building data must be an object")
        return result

    # Required fields for generators
    required_fields = ['width', 'depth']
    for field in required_fields:
        if field not in data:
            result.add_warning("", f"Missing recommended field '{field}'",
                              suggestion="Add building dimensions for accurate generation")

    # Width and depth
    if 'width' in data:
        if not is_positive_number(data['width']):
            result.add_error("width", "width must be a positive number")
        elif data['width'] < 1000:
            result.add_warning("width", "Building width seems very small")
        elif data['width'] > 100000:
            result.add_warning("width", "Building width seems very large")

    if 'depth' in data:
        if not is_positive_number(data['depth']):
            result.add_error("depth", "depth must be a positive number")
        elif data['depth'] < 1000:
            result.add_warning("depth", "Building depth seems very small")
        elif data['depth'] > 100000:
            result.add_warning("depth", "Building depth seems very large")

    # Walls
    walls = data.get('walls_batch', [])
    if not walls:
        result.add_warning("walls_batch", "No walls defined")
    else:
        if not isinstance(walls, list):
            result.add_error("walls_batch", "walls_batch must be an array")
        else:
            for i, wall in enumerate(walls):
                validate_wall(wall, i, result, walls)

    walls_count = len(walls) if isinstance(walls, list) else 0

    # Doors
    doors = data.get('doors', [])
    if doors:
        if not isinstance(doors, list):
            result.add_error("doors", "doors must be an array")
        else:
            for i, door in enumerate(doors):
                validate_door(door, i, result, walls_count)

    # Windows
    windows = data.get('windows', [])
    if windows:
        if not isinstance(windows, list):
            result.add_error("windows", "windows must be an array")
        else:
            for i, window in enumerate(windows):
                validate_window(window, i, result, walls_count)

    # Rooms
    rooms = data.get('rooms', {})
    if rooms:
        if not isinstance(rooms, dict):
            result.add_error("rooms", "rooms must be an object")
        else:
            for room_id, room in rooms.items():
                validate_room(room_id, room, result)

    # Roofs
    roofs = data.get('roofs', [])
    if roofs:
        if not isinstance(roofs, list):
            result.add_error("roofs", "roofs must be an array")
        else:
            for i, roof in enumerate(roofs):
                validate_roof(roof, i, result)

    # Wall types
    wall_types = data.get('wall_types', [])
    if wall_types and not isinstance(wall_types, list):
        result.add_error("wall_types", "wall_types must be an array")

    # Convert warnings to errors if strict mode
    if strict:
        for issue in result.issues:
            if issue.severity == ValidationSeverity.WARNING:
                issue.severity = ValidationSeverity.ERROR
                result.errors_count += 1
                result.warnings_count -= 1
                result.is_valid = False

    logger.info(f"Validation complete: {result.errors_count} errors, {result.warnings_count} warnings")

    return result


def validate_file(file_path: str, strict: bool = False) -> ValidationResult:
    """
    Validate a JSON file.

    Args:
        file_path: Path to the JSON file
        strict: If True, warnings become errors

    Returns:
        ValidationResult with all issues found
    """
    path = Path(file_path)

    if not path.exists():
        result = ValidationResult(is_valid=False)
        result.add_error("", f"File not found: {file_path}")
        return result

    try:
        with open(path, 'r') as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        result = ValidationResult(is_valid=False)
        result.add_error("", f"Invalid JSON: {e}")
        return result
    except Exception as e:
        result = ValidationResult(is_valid=False)
        result.add_error("", f"Error reading file: {e}")
        return result

    return validate_building_data(data, strict)


def generate_validation_report(result: ValidationResult, output_path: str = None) -> str:
    """
    Generate a detailed validation report.

    Args:
        result: ValidationResult to report on
        output_path: Optional path to write report to

    Returns:
        Report as string
    """
    lines = [
        "=" * 70,
        "ARCHENGINE BUILDING DATA VALIDATION REPORT",
        "=" * 70,
        "",
        f"Status: {'VALID' if result.is_valid else 'INVALID'}",
        f"Errors: {result.errors_count}",
        f"Warnings: {result.warnings_count}",
        "",
    ]

    if result.issues:
        # Group by severity
        errors = [i for i in result.issues if i.severity == ValidationSeverity.ERROR]
        warnings = [i for i in result.issues if i.severity == ValidationSeverity.WARNING]
        infos = [i for i in result.issues if i.severity == ValidationSeverity.INFO]

        if errors:
            lines.append("ERRORS:")
            lines.append("-" * 70)
            for issue in errors:
                lines.append(f"  {issue.path}: {issue.message}")
                if issue.expected:
                    lines.append(f"    Expected: {issue.expected}")
                if issue.actual:
                    lines.append(f"    Actual: {issue.actual}")
                if issue.suggestion:
                    lines.append(f"    Suggestion: {issue.suggestion}")
            lines.append("")

        if warnings:
            lines.append("WARNINGS:")
            lines.append("-" * 70)
            for issue in warnings:
                lines.append(f"  {issue.path}: {issue.message}")
                if issue.suggestion:
                    lines.append(f"    Suggestion: {issue.suggestion}")
            lines.append("")

        if infos:
            lines.append("INFO:")
            lines.append("-" * 70)
            for issue in infos:
                lines.append(f"  {issue.path}: {issue.message}")
            lines.append("")

    lines.append("=" * 70)

    report = "\n".join(lines)

    if output_path:
        with open(output_path, 'w') as f:
            f.write(report)
        logger.info(f"Validation report written to {output_path}")

    return report


# =============================================================================
# COMMAND LINE INTERFACE
# =============================================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='Validate ArchEngine building JSON files',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('input', help='Input JSON file to validate')
    parser.add_argument('-o', '--output', help='Output validation report to file')
    parser.add_argument('-s', '--strict', action='store_true',
                       help='Treat warnings as errors')
    parser.add_argument('-q', '--quiet', action='store_true',
                       help='Only output errors')

    args = parser.parse_args()

    # Configure logging
    log_level = logging.WARNING if args.quiet else logging.INFO
    logging.basicConfig(level=log_level, format='%(levelname)s: %(message)s')

    # Validate
    result = validate_file(args.input, strict=args.strict)

    # Generate report
    report = generate_validation_report(result, args.output)

    if not args.quiet:
        print(report)

    # Exit with appropriate code
    exit(0 if result.is_valid else 1)


if __name__ == '__main__':
    main()
