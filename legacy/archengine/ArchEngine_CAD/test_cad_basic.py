#!/usr/bin/env python3
"""Test CAD application - basic module import test."""

import sys
from pathlib import Path

# Add CAD directory to path
cad_dir = Path(__file__).parent
sys.path.insert(0, str(cad_dir))

def test_cad_modules():
    """Test that all CAD modules can be imported."""
    print("=" * 70)
    print("CAD APPLICATION MODULE TEST")
    print("=" * 70)

    tests_passed = 0
    tests_failed = 0

    modules_to_test = [
        # Core modules
        ("core.events", "event_bus"),
        ("core.version_control", "VersionControl"),
        ("core.document", "ArchDocument"),
        ("core.selection", "SelectionManager"),
        ("core.diagnostics", "DiagnosticsManager"),

        # Panel modules
        ("panels.materials_panel", "MaterialsPanel"),
        ("panels.smart_panel_container", "SmartPanelContainer"),
        ("panels.smart_panels", "PanelDefinition"),
        ("panels.panel_registry", "PANEL_NAVIGATION"),

        # API modules
        ("api.server", None),  # Just check module import

        # Application
        ("app.application", "ArchEngineApplication"),
    ]

    for module_name, item_name in modules_to_test:
        try:
            module = __import__(module_name, fromlist=[item_name] if item_name else [])
            if item_name:
                getattr(module, item_name)
            print(f"  [OK] {module_name}" + (f" ({item_name})" if item_name else ""))
            tests_passed += 1
        except Exception as e:
            print(f"  [FAIL] {module_name}" + (f" ({item_name})" if item_name else "") + f": {e}")
            tests_failed += 1

    # Test document creation
    print("\n[Document Creation Test]")
    print("-" * 70)
    try:
        from core.document import ArchDocument
        doc = ArchDocument()
        print(f"  [OK] Created empty document")
        print(f"         - Rooms: {len(doc.rooms)}")
        print(f"         - Walls: {len(doc.walls)}")
        print(f"         - Doors: {len(doc.doors)}")
        print(f"         - Windows: {len(doc.windows)}")
        tests_passed += 1
    except Exception as e:
        print(f"  [FAIL] Document creation: {e}")
        tests_failed += 1

    # Test loading sample building JSON
    print("\n[JSON Loading Test]")
    print("-" * 70)
    try:
        from core.document import ArchDocument
        import json

        # Check if test JSON exists
        json_path = Path(__file__).parent.parent.parent / "Shared" / "TestData" / "output" / "generated_building.json"
        if json_path.exists():
            with open(json_path) as f:
                building_data = json.load(f)

            doc = ArchDocument()
            doc.load_from_dict(building_data)

            print(f"  [OK] Loaded building from JSON")
            print(f"         - Rooms: {len(doc.rooms)}")
            print(f"         - Walls: {len(doc.walls)}")
            print(f"         - Doors: {len(doc.doors)}")
            print(f"         - Windows: {len(doc.windows)}")

            # Check for reality_analysis
            if 'reality_analysis' in building_data:
                reality = building_data['reality_analysis']
                print(f"         - Reality Score: {reality.get('overall_score', 'N/A')}")
                print(f"         - Thermal Load: {reality['environment'].get('thermal_load_kw', 'N/A')} kW")
                print(f"         - Total Cost: ${reality['materiality'].get('total_cost', 0):,.0f}")

            tests_passed += 1
        else:
            print(f"  [SKIP] Test JSON not found at {json_path}")
    except Exception as e:
        print(f"  [FAIL] JSON loading: {e}")
        import traceback
        traceback.print_exc()
        tests_failed += 1

    # Summary
    print("\n" + "=" * 70)
    print(f"RESULTS: {tests_passed} passed, {tests_failed} failed")
    print("=" * 70)

    return tests_failed == 0


if __name__ == "__main__":
    success = test_cad_modules()
    sys.exit(0 if success else 1)
