#!/usr/bin/env python3
"""
test_pipeline.py - Test the complete drawing generation pipeline

Runs basic tests on all modules and generates a test drawing set.
"""

import sys
import os
from pathlib import Path

# Add script directory to path
script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir))


def test_imports():
    """Test that all modules can be imported."""
    print("\n" + "=" * 60)
    print("TESTING MODULE IMPORTS")
    print("=" * 60)

    modules = [
        ('logging_config', 'Logging configuration'),
        ('schema_validator', 'Schema validation'),
        ('wall_types', 'Wall type definitions'),
        ('roof_generator', 'Roof generation'),
        ('generator_base', 'Generator base utilities'),
        ('title_block', 'Title block generation'),
    ]

    results = []
    for module_name, description in modules:
        try:
            __import__(module_name)
            print(f"  [OK] {description} ({module_name})")
            results.append(True)
        except ImportError as e:
            print(f"  [FAIL] {description} ({module_name}): {e}")
            results.append(False)

    # Check optional dependencies
    print("\nOptional dependencies:")
    try:
        import reportlab
        print(f"  [OK] reportlab {reportlab.Version}")
    except ImportError:
        print("  [SKIP] reportlab (PDF export will be disabled)")

    try:
        import svglib
        print(f"  [OK] svglib")
    except ImportError:
        print("  [SKIP] svglib (SVG to PDF conversion will be disabled)")

    return all(results)


def test_wall_types():
    """Test wall type definitions."""
    print("\n" + "=" * 60)
    print("TESTING WALL TYPES")
    print("=" * 60)

    from wall_types import (
        get_wall_type, get_all_wall_types, get_default_wall_type,
        EXT_2X6_R21, INT_2X4, WallCategory
    )

    # Test getting wall types
    all_types = get_all_wall_types()
    print(f"  Total wall types defined: {len(all_types)}")

    # Test specific wall type
    ext_wall = get_wall_type('ext_2x6_r21')
    if ext_wall:
        print(f"  ext_2x6_r21 thickness: {ext_wall.total_thickness}mm")
        print(f"  ext_2x6_r21 R-value: {ext_wall.total_r_value:.1f}")
        print(f"  ext_2x6_r21 layers: {len(ext_wall.layers)}")
    else:
        print("  [FAIL] Could not get ext_2x6_r21")
        return False

    # Test default wall types
    for category in ['exterior', 'interior', 'wet_wall']:
        default = get_default_wall_type(category)
        print(f"  Default {category}: {default.id} ({default.total_thickness}mm)")

    return True


def test_roof_generator():
    """Test roof generation."""
    print("\n" + "=" * 60)
    print("TESTING ROOF GENERATOR")
    print("=" * 60)

    from roof_generator import (
        generate_gable_roof, generate_hip_roof,
        add_roof_to_building, RoofType
    )

    # Test gable roof
    gable = generate_gable_roof(12000, 9000, 2700, pitch=4.0, overhang=600)
    print(f"  Gable roof surfaces: {len(gable.surfaces)}")
    print(f"  Gable roof edges: {len(gable.edges)}")
    print(f"  Ridge height: {gable.ridge_height}mm")

    # Test hip roof
    hip = generate_hip_roof(12000, 9000, 2700, pitch=4.0, overhang=600)
    print(f"  Hip roof surfaces: {len(hip.surfaces)}")
    print(f"  Hip roof edges: {len(hip.edges)}")

    # Test adding roof to building data
    test_building = {
        'width': 12000,
        'depth': 9000,
        'walls_batch': [{'height': 2700}],
        'qbd_answers': {'style': 'traditional'}
    }

    updated = add_roof_to_building(test_building)
    if 'roofs' in updated and len(updated['roofs']) > 0:
        print(f"  Building roof added: {updated['roofs'][0]['type']}")
    else:
        print("  [FAIL] Roof not added to building")
        return False

    return True


def test_schema_validator():
    """Test schema validation."""
    print("\n" + "=" * 60)
    print("TESTING SCHEMA VALIDATOR")
    print("=" * 60)

    from schema_validator import validate_building_data, ValidationResult

    # Test valid data
    valid_data = {
        'width': 12000,
        'depth': 9000,
        'walls_batch': [
            {'start': [0, 0, 0], 'end': [12000, 0, 0], 'height': 2700, 'category': 'exterior'}
        ],
        'doors': [],
        'windows': [],
        'rooms': {}
    }

    result = validate_building_data(valid_data)
    print(f"  Valid data: {'PASSED' if result.is_valid else 'FAILED'}")
    print(f"  Errors: {result.errors_count}, Warnings: {result.warnings_count}")

    # Test invalid data
    invalid_data = {
        'walls_batch': [
            {'start': 'invalid', 'end': [12000, 0, 0]}  # Invalid start
        ]
    }

    result = validate_building_data(invalid_data)
    print(f"  Invalid data detected: {'YES' if not result.is_valid else 'NO'}")

    return True


def test_logging():
    """Test logging configuration."""
    print("\n" + "=" * 60)
    print("TESTING LOGGING")
    print("=" * 60)

    from logging_config import setup_logging, get_logger, log_section, log_step
    import logging

    # Setup logging
    logger = setup_logging(name='test', level=logging.INFO, console=True, colors=True)

    print("  Testing log levels (with colors if terminal supports it):")
    logger.debug("  Debug message (may not show at INFO level)")
    logger.info("  Info message")
    logger.warning("  Warning message")

    return True


def test_sample_data():
    """Test loading sample data."""
    print("\n" + "=" * 60)
    print("TESTING SAMPLE DATA")
    print("=" * 60)

    import json

    # Find sample data
    test_data_dir = script_dir.parent.parent / 'Shared' / 'TestData'
    sample_files = [
        test_data_dir / 'sample_building_complete.json',
        test_data_dir / 'sample_qbd_output.json',
        test_data_dir / 'output' / 'generated_building.json',
    ]

    for sample_file in sample_files:
        if sample_file.exists():
            try:
                with open(sample_file, 'r') as f:
                    data = json.load(f)
                print(f"  [OK] {sample_file.name}")
                print(f"       Size: {data.get('width', 'N/A')}mm x {data.get('depth', 'N/A')}mm")
                print(f"       Walls: {len(data.get('walls_batch', []))}")
                print(f"       Roofs: {len(data.get('roofs', []))}")
            except Exception as e:
                print(f"  [FAIL] {sample_file.name}: {e}")
        else:
            print(f"  [SKIP] {sample_file.name} not found")

    return True


def run_all_tests():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("ARCHENGINE GENERATOR PIPELINE TESTS")
    print("=" * 60)
    print(f"Python version: {sys.version}")
    print(f"Script directory: {script_dir}")

    results = []

    results.append(('Imports', test_imports()))
    results.append(('Wall Types', test_wall_types()))
    results.append(('Roof Generator', test_roof_generator()))
    results.append(('Schema Validator', test_schema_validator()))
    results.append(('Logging', test_logging()))
    results.append(('Sample Data', test_sample_data()))

    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)

    passed = 0
    failed = 0
    for name, result in results:
        status = "PASSED" if result else "FAILED"
        icon = "[OK]" if result else "[FAIL]"
        print(f"  {icon} {name}: {status}")
        if result:
            passed += 1
        else:
            failed += 1

    print(f"\nTotal: {passed} passed, {failed} failed")
    print("=" * 60)

    return failed == 0


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)
