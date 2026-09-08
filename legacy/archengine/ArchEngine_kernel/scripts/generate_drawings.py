#!/usr/bin/env python3
"""
generate_drawings.py - Generate complete architectural drawing set from building JSON

Creates a full set of construction documents:
- Floor Plan
- Roof Plan
- Elevations (North, South, East, West)
- Sections (Longitudinal, Transverse)

All drawings output as SVG files ready for viewing or conversion to PDF/DXF.
"""

import json
import argparse
import subprocess
import sys
from pathlib import Path
from datetime import datetime

def run_generator(script_name: str, input_path: str, output_dir: str, scale: float) -> bool:
    """Run a generator script and return success status."""
    script_path = Path(__file__).parent / script_name

    if not script_path.exists():
        print(f"  WARNING: {script_name} not found")
        return False

    try:
        result = subprocess.run(
            [sys.executable, str(script_path), input_path, '-o', output_dir, '-s', str(scale)],
            capture_output=True,
            text=True,
            cwd=str(script_path.parent)
        )

        if result.returncode != 0:
            print(f"  ERROR: {script_name} failed")
            print(result.stderr)
            return False

        # Print output (indented)
        for line in result.stdout.strip().split('\n'):
            print(f"  {line}")

        return True

    except Exception as e:
        print(f"  ERROR: {e}")
        return False

def generate_drawing_index(output_dir: str, building_data: dict) -> str:
    """Generate an HTML index page for all drawings."""

    drawings = [
        ("Floor Plan", "floor_plan.svg"),
        ("Roof Plan", "roof_plan.svg"),
        ("South Elevation", "elevation_south.svg"),
        ("North Elevation", "elevation_north.svg"),
        ("East Elevation", "elevation_east.svg"),
        ("West Elevation", "elevation_west.svg"),
        ("Section A-A", "section_a.svg"),
        ("Section B-B", "section_b.svg"),
    ]

    building_id = building_data.get('building_id', 'Unknown')
    sqft = building_data.get('sqft', 0)
    answers = building_data.get('qbd_answers', {})
    description = answers.get('description', 'Building')

    html = f'''<!DOCTYPE html>
<html>
<head>
    <title>Drawing Set - {building_id}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }}
        h1 {{ color: #333; border-bottom: 2px solid #333; padding-bottom: 10px; }}
        .info {{ background: white; padding: 20px; margin-bottom: 20px; border-radius: 5px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }}
        .info p {{ margin: 5px 0; }}
        .drawings {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 20px; }}
        .drawing {{ background: white; padding: 15px; border-radius: 5px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }}
        .drawing h3 {{ margin: 0 0 10px 0; color: #333; }}
        .drawing a {{ color: #0066cc; text-decoration: none; }}
        .drawing a:hover {{ text-decoration: underline; }}
        .drawing img {{ max-width: 100%; height: auto; border: 1px solid #ddd; margin-top: 10px; }}
        .timestamp {{ color: #999; font-size: 12px; margin-top: 30px; }}
    </style>
</head>
<body>
    <h1>Architectural Drawing Set</h1>

    <div class="info">
        <p><strong>Project:</strong> {description}</p>
        <p><strong>Building ID:</strong> {building_id}</p>
        <p><strong>Area:</strong> {sqft} sq ft</p>
        <p><strong>Bedrooms:</strong> {answers.get('bedrooms', 'N/A')} | <strong>Bathrooms:</strong> {answers.get('bathrooms', 'N/A')}</p>
    </div>

    <div class="drawings">
'''

    for title, filename in drawings:
        filepath = Path(output_dir) / filename
        if filepath.exists():
            html += f'''        <div class="drawing">
            <h3>{title}</h3>
            <a href="{filename}" target="_blank">Open Full Size</a>
            <a href="{filename}"><img src="{filename}" alt="{title}"></a>
        </div>
'''

    html += f'''    </div>

    <p class="timestamp">Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>
</body>
</html>
'''

    return html

def main():
    parser = argparse.ArgumentParser(
        description='Generate complete architectural drawing set from building JSON',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  python generate_drawings.py
  python generate_drawings.py my_building.json -o ./output
  python generate_drawings.py -s 0.03  # Smaller scale for large buildings
        '''
    )
    parser.add_argument('input', nargs='?',
                        default='../../Shared/TestData/output/generated_building.json',
                        help='Input JSON file path')
    parser.add_argument('-o', '--output',
                        default='../../Shared/TestData/output',
                        help='Output directory for drawing files')
    parser.add_argument('-s', '--scale', type=float, default=0.05,
                        help='Scale factor for drawings (default: 0.05)')
    parser.add_argument('--skip-floor-plan', action='store_true',
                        help='Skip floor plan generation')
    parser.add_argument('--skip-elevations', action='store_true',
                        help='Skip elevation generation')
    parser.add_argument('--skip-sections', action='store_true',
                        help='Skip section generation')

    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"ERROR: Input file not found: {input_path}")
        sys.exit(1)

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("ARCHITECTURAL DRAWING SET GENERATOR")
    print("=" * 60)
    print(f"Input:  {input_path}")
    print(f"Output: {output_dir}")
    print(f"Scale:  {args.scale}")
    print("=" * 60)

    # Load building data for index generation
    with open(input_path, 'r') as f:
        building_data = json.load(f)

    results = {}

    # Floor Plan
    if not args.skip_floor_plan:
        print("\n[1/4] FLOOR PLAN")
        print("-" * 40)
        # Floor plan uses different script - check if it exists
        floor_plan_script = Path(__file__).parent / "generate_plans.py"
        if floor_plan_script.exists():
            results['floor_plan'] = run_generator('generate_plans.py', str(input_path), str(output_dir), args.scale)
        else:
            print("  Floor plan generator not found, skipping")
            results['floor_plan'] = False

    # Elevations
    if not args.skip_elevations:
        print("\n[2/4] ELEVATIONS")
        print("-" * 40)
        results['elevations'] = run_generator('generate_elevations.py', str(input_path), str(output_dir), args.scale)

    # Sections
    if not args.skip_sections:
        print("\n[3/4] SECTIONS")
        print("-" * 40)
        results['sections'] = run_generator('generate_sections.py', str(input_path), str(output_dir), args.scale)

    # Generate index page
    print("\n[4/4] DRAWING INDEX")
    print("-" * 40)
    try:
        index_html = generate_drawing_index(str(output_dir), building_data)
        index_path = output_dir / "drawings_index.html"
        with open(index_path, 'w') as f:
            f.write(index_html)
        print(f"  Wrote {index_path}")
        results['index'] = True
    except Exception as e:
        print(f"  ERROR: {e}")
        results['index'] = False

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    all_files = list(output_dir.glob("*.svg")) + list(output_dir.glob("*.html"))
    print(f"Total files generated: {len(all_files)}")

    for name, success in results.items():
        status = "OK" if success else "FAILED/SKIPPED"
        print(f"  {name}: {status}")

    print(f"\nOpen {output_dir / 'drawings_index.html'} to view all drawings")
    print("=" * 60)

if __name__ == '__main__':
    main()
