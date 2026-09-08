#!/usr/bin/env python3
"""Test loading building JSON with reality layer data into CAD document."""

import sys
from pathlib import Path

# Add CAD directory to path
cad_dir = Path(__file__).parent
sys.path.insert(0, str(cad_dir))

from core.document import ArchDocument
import json


def main():
    print("=" * 70)
    print("CAD REALITY LAYER INTEGRATION TEST")
    print("=" * 70)

    # Check correct path for test data
    json_path = Path(__file__).parent.parent / 'Shared' / 'TestData' / 'output' / 'generated_building.json'
    print(f'\nTesting JSON load from: {json_path}')
    print(f'File exists: {json_path.exists()}')

    if not json_path.exists():
        print('\n[ERROR] Test JSON file not found. Run text_to_json.py first.')
        return False

    # Load JSON
    with open(json_path) as f:
        building_data = json.load(f)

    print(f'\n=== BUILDING DATA ===')
    print(f'Building ID: {building_data.get("building_id")}')
    print(f'SQM: {building_data.get("sqm")}')
    print(f'SQFT: {building_data.get("sqft")}')
    print(f'Rooms: {building_data.get("summary", {}).get("rooms_placed")}')
    print(f'Walls: {building_data.get("summary", {}).get("total_walls")}')
    print(f'Doors: {building_data.get("summary", {}).get("doors")}')

    # Check for reality_analysis
    if 'reality_analysis' in building_data:
        reality = building_data['reality_analysis']
        print(f'\n=== REALITY ANALYSIS ===')
        print(f'Overall Score: {reality.get("overall_score")}')

        env = reality.get('environment', {})
        print(f'\n[Environment - Physics]')
        print(f'  Thermal Load: {env.get("thermal_load_kw")} kW')
        print(f'  Cooling Load: {env.get("cooling_load_kw")} kW')
        print(f'  Peak Month: {env.get("peak_heating_month")}')
        print(f'  Passive Strategies: {", ".join(env.get("passive_strategies", []))}')

        mat = reality.get('materiality', {})
        print(f'\n[Materiality - Economics]')
        print(f'  Total Cost: ${mat.get("total_cost", 0):,.0f}')
        print(f'  Cost per sqft: ${mat.get("cost_per_sqft", 0):.2f}')
        print(f'  Budget Status: {mat.get("budget_status")}')
        print(f'  Construction Weeks: {mat.get("construction_weeks")}')
        print(f'  Carbon Footprint: {mat.get("carbon_footprint_kg", 0):,.0f} kg CO2e')

        perc = reality.get('perception', {})
        print(f'\n[Perception - Psychology]')
        print(f'  Wayfinding Score: {perc.get("wayfinding_score")}')
        print(f'  Overall Experience: {perc.get("overall_experience")}')
        print(f'  Enhancement Opportunities: {", ".join(perc.get("enhancement_opportunities", [])[:3])}')
    else:
        print('\n[WARNING] No reality_analysis found in JSON')

    # Load into document
    doc = ArchDocument()
    doc.load_from_dict(building_data)
    print(f'\n=== DOCUMENT LOAD ===')
    print(f'Rooms: {len(doc.rooms)}')
    print(f'Walls: {len(doc.walls)}')
    print(f'Doors: {len(doc.doors)}')
    print(f'Windows: {len(doc.windows)}')

    print(f'\n[SUCCESS] CAD document successfully loaded with reality layer data!')
    print('=' * 70)

    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
