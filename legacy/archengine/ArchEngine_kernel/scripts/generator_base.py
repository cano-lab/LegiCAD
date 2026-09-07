#!/usr/bin/env python3
"""
generator_base.py - Base utilities for all drawing generators

Provides:
- Common error handling decorators
- Input/output file handling
- JSON loading with validation
- SVG output utilities
- Command-line argument parsing helpers
"""

import json
import sys
import traceback
import functools
from pathlib import Path
from typing import Dict, Any, Optional, Callable, TypeVar, List
from dataclasses import dataclass
from datetime import datetime
import argparse

# Import logging (handle case where it's not available)
try:
    from logging_config import get_logger, setup_logging
    HAS_LOGGING = True
except ImportError:
    HAS_LOGGING = False
    import logging
    def get_logger(name):
        return logging.getLogger(name)
    def setup_logging(**kwargs):
        logging.basicConfig(level=logging.INFO)

# Import validation (handle case where it's not available)
try:
    from schema_validator import validate_building_data
    HAS_VALIDATION = True
except ImportError:
    HAS_VALIDATION = False
    def validate_building_data(data):
        class MockResult:
            is_valid = True
            errors_count = 0
            warnings_count = 0
        return MockResult()


logger = get_logger('generator_base')

T = TypeVar('T')


# =============================================================================
# ERROR HANDLING
# =============================================================================

class GeneratorError(Exception):
    """Base exception for generator errors."""
    pass


class InputError(GeneratorError):
    """Error with input file or data."""
    pass


class OutputError(GeneratorError):
    """Error writing output file."""
    pass


class ValidationError(GeneratorError):
    """Data validation error."""
    pass


def handle_errors(func: Callable[..., T]) -> Callable[..., T]:
    """
    Decorator to handle common errors in generator functions.
    Provides consistent error reporting and exit codes.
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except FileNotFoundError as e:
            logger.error(f"File not found: {e}")
            sys.exit(1)
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON: {e}")
            sys.exit(1)
        except ValidationError as e:
            logger.error(f"Validation error: {e}")
            sys.exit(1)
        except OutputError as e:
            logger.error(f"Output error: {e}")
            sys.exit(1)
        except GeneratorError as e:
            logger.error(f"Generator error: {e}")
            sys.exit(1)
        except KeyboardInterrupt:
            logger.info("Generation cancelled by user")
            sys.exit(130)
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            logger.debug(traceback.format_exc())
            sys.exit(1)
    return wrapper


def safe_execute(func: Callable[..., T], *args, default: T = None, **kwargs) -> T:
    """
    Execute a function safely, returning default on error.
    """
    try:
        return func(*args, **kwargs)
    except Exception as e:
        logger.warning(f"Error in {func.__name__}: {e}")
        return default


# =============================================================================
# FILE HANDLING
# =============================================================================

def load_building_json(file_path: str, validate: bool = True) -> Dict[str, Any]:
    """
    Load and optionally validate a building JSON file.

    Args:
        file_path: Path to JSON file
        validate: Whether to validate against schema

    Returns:
        Loaded and validated data dictionary

    Raises:
        InputError: If file cannot be loaded
        ValidationError: If validation fails
    """
    path = Path(file_path)

    if not path.exists():
        raise InputError(f"Input file not found: {file_path}")

    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise InputError(f"Invalid JSON in {file_path}: {e}")
    except Exception as e:
        raise InputError(f"Could not read {file_path}: {e}")

    if validate and HAS_VALIDATION:
        result = validate_building_data(data)
        if not result.is_valid:
            raise ValidationError(
                f"Validation failed with {result.errors_count} errors"
            )
        if result.warnings_count > 0:
            logger.warning(f"Validation passed with {result.warnings_count} warnings")

    return data


def ensure_output_dir(output_dir: str) -> Path:
    """
    Ensure output directory exists.

    Args:
        output_dir: Path to output directory

    Returns:
        Path object for the directory

    Raises:
        OutputError: If directory cannot be created
    """
    path = Path(output_dir)

    try:
        path.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        raise OutputError(f"Could not create output directory {output_dir}: {e}")

    return path


def write_svg(content: str, file_path: str) -> str:
    """
    Write SVG content to file.

    Args:
        content: SVG content string
        file_path: Output file path

    Returns:
        Absolute path to written file

    Raises:
        OutputError: If file cannot be written
    """
    path = Path(file_path)

    try:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
    except Exception as e:
        raise OutputError(f"Could not write SVG to {file_path}: {e}")

    logger.info(f"Wrote: {path}")
    return str(path.absolute())


def write_json(data: dict, file_path: str, indent: int = 2) -> str:
    """
    Write JSON data to file.

    Args:
        data: Data dictionary
        file_path: Output file path
        indent: JSON indentation level

    Returns:
        Absolute path to written file
    """
    path = Path(file_path)

    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=indent)
    except Exception as e:
        raise OutputError(f"Could not write JSON to {file_path}: {e}")

    logger.info(f"Wrote: {path}")
    return str(path.absolute())


# =============================================================================
# DATA EXTRACTION HELPERS
# =============================================================================

def get_building_dimensions(data: dict) -> tuple:
    """
    Extract building dimensions from data.

    Returns:
        Tuple of (width, depth, height) in mm
    """
    width = data.get('width', 10000)
    depth = data.get('depth', 10000)

    # Get height from walls
    walls = data.get('walls_batch', [])
    if walls:
        height = max(w.get('height', 2700) for w in walls)
    else:
        height = 2700

    return width, depth, height


def get_wall_thickness(wall: dict, wall_types: List[dict]) -> float:
    """
    Get the total thickness of a wall from its type.

    Args:
        wall: Wall data dictionary
        wall_types: List of wall type definitions

    Returns:
        Wall thickness in mm
    """
    wall_type_id = wall.get('wall_type', '')

    for wt in wall_types:
        if wt.get('id') == wall_type_id:
            # Sum layer thicknesses
            if 'layers' in wt:
                return sum(l.get('thickness', 0) for l in wt['layers'])
            return wt.get('total_thickness', 150)

    # Default based on category
    category = wall.get('category', 'interior')
    defaults = {
        'exterior': 189,  # 2x6 wall
        'interior': 115,  # 2x4 wall
        'wet_wall': 166,  # 2x6 wet wall
    }
    return defaults.get(category, 115)


def get_project_info(data: dict) -> dict:
    """
    Extract project information for title blocks.

    Args:
        data: Building data dictionary

    Returns:
        Project info dictionary
    """
    qbd = data.get('qbd_answers', {})

    return {
        'name': qbd.get('description', 'Residential Project'),
        'number': data.get('building_id', 'P-001'),
        'address': qbd.get('address', ''),
        'client': qbd.get('client_name', ''),
        'date': datetime.now().strftime('%Y-%m-%d'),
        'bedrooms': qbd.get('bedrooms', 'N/A'),
        'bathrooms': qbd.get('bathrooms', 'N/A'),
        'sqft': data.get('sqft', data.get('sqm', 0) * 10.764),
    }


# =============================================================================
# ARGUMENT PARSING
# =============================================================================

def create_base_parser(description: str) -> argparse.ArgumentParser:
    """
    Create a base argument parser with common options.

    Args:
        description: Description for the parser

    Returns:
        Configured ArgumentParser
    """
    parser = argparse.ArgumentParser(
        description=description,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument(
        'input',
        nargs='?',
        default='../../Shared/TestData/output/generated_building.json',
        help='Input JSON file path'
    )

    parser.add_argument(
        '-o', '--output',
        default='../../Shared/TestData/output',
        help='Output directory for generated files'
    )

    parser.add_argument(
        '-s', '--scale',
        type=float,
        default=0.05,
        help='Scale factor for drawings (default: 0.05)'
    )

    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose output'
    )

    parser.add_argument(
        '-q', '--quiet',
        action='store_true',
        help='Suppress non-error output'
    )

    parser.add_argument(
        '--no-validate',
        action='store_true',
        help='Skip input validation'
    )

    return parser


def setup_from_args(args) -> tuple:
    """
    Setup logging and load data from parsed arguments.

    Args:
        args: Parsed argument namespace

    Returns:
        Tuple of (data, output_dir)
    """
    # Setup logging
    import logging
    if args.quiet:
        level = logging.ERROR
    elif args.verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO

    if HAS_LOGGING:
        setup_logging(name='archengine', level=level, console=True, colors=True)

    # Load data
    data = load_building_json(args.input, validate=not args.no_validate)

    # Ensure output directory
    output_dir = ensure_output_dir(args.output)

    return data, output_dir


# =============================================================================
# SVG HELPERS
# =============================================================================

def svg_header(width: float, height: float, title: str = "Drawing") -> str:
    """
    Generate SVG header with proper namespace and viewBox.

    Args:
        width: SVG width in pixels
        height: SVG height in pixels
        title: Document title

    Returns:
        SVG header string
    """
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg"
     xmlns:xlink="http://www.w3.org/1999/xlink"
     width="{width:.0f}" height="{height:.0f}"
     viewBox="0 0 {width:.0f} {height:.0f}">
  <title>{title}</title>
'''


def svg_footer() -> str:
    """Generate SVG footer."""
    return '</svg>\n'


def svg_styles() -> str:
    """Generate common SVG styles for architectural drawings."""
    return '''  <style>
    /* Line weights */
    .line-hairline { stroke-width: 0.13mm; }
    .line-fine { stroke-width: 0.18mm; }
    .line-light { stroke-width: 0.25mm; }
    .line-medium { stroke-width: 0.35mm; }
    .line-heavy { stroke-width: 0.50mm; }
    .line-border { stroke-width: 0.70mm; }

    /* Common elements */
    .wall { fill: #f5f5f5; stroke: #333; stroke-width: 0.35mm; }
    .wall-cut { fill: #e0e0e0; stroke: #000; stroke-width: 0.50mm; }
    .opening { fill: white; stroke: #333; stroke-width: 0.25mm; }
    .dimension { font-family: Arial, sans-serif; font-size: 8px; fill: #333; }
    .label { font-family: Arial, sans-serif; font-size: 10px; fill: #333; }
    .title { font-family: Arial, sans-serif; font-size: 14px; font-weight: bold; fill: #333; }

    /* Room labels */
    .room-label {
      font-family: Arial, sans-serif;
      font-size: 12px;
      fill: #333;
      text-anchor: middle;
    }
  </style>
'''


@dataclass
class GeneratorResult:
    """Result of a generator execution."""
    success: bool
    files_created: List[str]
    errors: List[str]
    warnings: List[str]
    elapsed_seconds: float = 0.0

    def __str__(self) -> str:
        status = "SUCCESS" if self.success else "FAILED"
        return f"{status}: {len(self.files_created)} files, {len(self.errors)} errors"


# =============================================================================
# MAIN GUARD
# =============================================================================

if __name__ == '__main__':
    # Run a simple test
    setup_logging(name='test', level=10, console=True, colors=True)
    logger = get_logger('test')

    logger.info("Generator base module loaded successfully")
    logger.info(f"Logging available: {HAS_LOGGING}")
    logger.info(f"Validation available: {HAS_VALIDATION}")
