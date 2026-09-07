#!/usr/bin/env python3
"""
generate_all.py - Complete architectural drawing set generator with PDF export

Comprehensive drawing generation pipeline:
1. Validates input JSON against schema
2. Enriches data with wall types and roof geometry
3. Generates all drawing types (plans, elevations, sections, details, schedules)
4. Exports to SVG and PDF formats
5. Creates HTML index and drawing set PDF

Usage:
    python generate_all.py input.json -o output_dir
    python generate_all.py input.json -o output_dir --pdf --sheet-size arch_d
"""

import json
import argparse
import subprocess
import sys
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import traceback

# Add script directory to path for imports
script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir))

# Import local modules
from logging_config import setup_logging, get_logger, log_section, log_step, ProgressLogger
from schema_validator import validate_building_data, generate_validation_report
from wall_types import get_wall_types_as_json, get_wall_type, get_default_wall_type
from roof_generator import add_roof_to_building, generate_roof

try:
    from pdf_export import (
        batch_convert_svg_to_pdf, SheetSize, DrawingSet, DrawingSheet,
        PDFDrawingSetGenerator, HAS_REPORTLAB
    )
    PDF_AVAILABLE = HAS_REPORTLAB
except ImportError:
    PDF_AVAILABLE = False

# Initialize logger
logger = get_logger('generate_all')


# =============================================================================
# CONFIGURATION
# =============================================================================

GENERATOR_SCRIPTS = {
    'plans': ('generate_plans.py', 'Floor Plan & Roof Plan'),
    'elevations': ('generate_elevations.py', 'Building Elevations'),
    'sections': ('generate_sections.py', 'Building Sections'),
    'details': ('generate_details.py', 'Construction Details'),
    'schedules': ('generate_schedules.py', 'Door/Window/Finish Schedules'),
}

DRAWING_FILES = [
    ('A-101', 'Floor Plan', 'floor_plan.svg'),
    ('A-102', 'Roof Plan', 'roof_plan.svg'),
    ('A-201', 'South Elevation', 'elevation_south.svg'),
    ('A-202', 'North Elevation', 'elevation_north.svg'),
    ('A-203', 'East Elevation', 'elevation_east.svg'),
    ('A-204', 'West Elevation', 'elevation_west.svg'),
    ('A-301', 'Section A-A', 'section_a.svg'),
    ('A-302', 'Section B-B', 'section_b.svg'),
    ('A-501', 'Construction Details', 'details.svg'),
    ('A-601', 'Schedules', 'schedules.svg'),
]


# =============================================================================
# DATA ENRICHMENT
# =============================================================================

def enrich_building_data(data: dict) -> dict:
    """
    Enrich building data with wall types and roof geometry.

    Args:
        data: Raw building JSON data

    Returns:
        Enriched building data
    """
    logger.info("Enriching building data...")

    # Add wall types if not present
    if 'wall_types' not in data or not data['wall_types']:
        logger.info("  Adding standard wall type definitions")
        data['wall_types'] = get_wall_types_as_json()

    # Validate and fix wall references
    walls = data.get('walls_batch', [])
    wall_type_ids = {wt['id'] for wt in data.get('wall_types', [])}

    for i, wall in enumerate(walls):
        wall_type = wall.get('wall_type', '')
        if wall_type and wall_type not in wall_type_ids:
            # Try to find a matching wall type
            category = wall.get('category', 'interior')
            default = get_default_wall_type(category)
            logger.debug(f"  Wall {i}: Replacing unknown type '{wall_type}' with '{default.id}'")
            wall['wall_type'] = default.id

    # Add roof if not present
    if 'roofs' not in data or not data['roofs']:
        logger.info("  Generating roof geometry")
        data = add_roof_to_building(data)

    # Ensure required fields
    if 'building_id' not in data:
        data['building_id'] = f"BLDG-{datetime.now().strftime('%Y%m%d')}"

    if 'units' not in data:
        data['units'] = 'mm'

    logger.info("  Data enrichment complete")
    return data


# =============================================================================
# GENERATOR EXECUTION
# =============================================================================

def run_generator(script_name: str, input_path: str, output_dir: str, scale: float) -> Tuple[bool, str]:
    """
    Run a generator script and return success status.

    Args:
        script_name: Name of the generator script
        input_path: Path to input JSON file
        output_dir: Output directory
        scale: Drawing scale factor

    Returns:
        Tuple of (success, output_message)
    """
    script_path = script_dir / script_name

    if not script_path.exists():
        return False, f"Script not found: {script_name}"

    try:
        result = subprocess.run(
            [sys.executable, str(script_path), input_path, '-o', output_dir, '-s', str(scale)],
            capture_output=True,
            text=True,
            cwd=str(script_path.parent),
            timeout=120  # 2 minute timeout
        )

        if result.returncode != 0:
            error_msg = result.stderr.strip() if result.stderr else "Unknown error"
            return False, f"Script failed: {error_msg}"

        output = result.stdout.strip()
        return True, output

    except subprocess.TimeoutExpired:
        return False, "Script timed out (>120s)"
    except Exception as e:
        return False, f"Execution error: {e}"


# =============================================================================
# HTML INDEX GENERATION
# =============================================================================

def generate_html_index(output_dir: Path, building_data: dict, results: dict) -> str:
    """Generate an enhanced HTML index page for all drawings."""

    building_id = building_data.get('building_id', 'Unknown')
    sqft = building_data.get('sqm', 0) * 10.764 if 'sqm' in building_data else building_data.get('sqft', 0)
    answers = building_data.get('qbd_answers', {})
    description = answers.get('description', 'Residential Building')

    # Count successful generations
    successful = sum(1 for v in results.values() if v[0])
    total = len(results)

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Drawing Set - {building_id}</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
            min-height: 100vh;
            padding: 40px 20px;
        }}
        .container {{ max-width: 1400px; margin: 0 auto; }}
        header {{
            background: white;
            border-radius: 12px;
            padding: 30px;
            margin-bottom: 30px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.1);
        }}
        h1 {{
            color: #1a1a2e;
            font-size: 2rem;
            margin-bottom: 10px;
        }}
        .subtitle {{ color: #666; font-size: 1.1rem; }}
        .stats {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 20px;
            margin-top: 20px;
        }}
        .stat {{
            background: #f8f9fa;
            padding: 15px;
            border-radius: 8px;
            text-align: center;
        }}
        .stat-value {{ font-size: 1.5rem; font-weight: bold; color: #1a1a2e; }}
        .stat-label {{ font-size: 0.85rem; color: #666; margin-top: 5px; }}
        .drawings-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
            gap: 25px;
        }}
        .drawing-card {{
            background: white;
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 4px 15px rgba(0,0,0,0.08);
            transition: transform 0.2s, box-shadow 0.2s;
        }}
        .drawing-card:hover {{
            transform: translateY(-5px);
            box-shadow: 0 8px 25px rgba(0,0,0,0.15);
        }}
        .drawing-preview {{
            background: #f8f9fa;
            padding: 20px;
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 200px;
        }}
        .drawing-preview img {{
            max-width: 100%;
            max-height: 180px;
            object-fit: contain;
        }}
        .drawing-info {{
            padding: 20px;
            border-top: 1px solid #eee;
        }}
        .drawing-number {{
            display: inline-block;
            background: #1a1a2e;
            color: white;
            padding: 4px 10px;
            border-radius: 4px;
            font-size: 0.8rem;
            font-weight: bold;
        }}
        .drawing-title {{
            font-size: 1.1rem;
            font-weight: 600;
            color: #1a1a2e;
            margin: 10px 0;
        }}
        .drawing-actions {{
            display: flex;
            gap: 10px;
        }}
        .btn {{
            flex: 1;
            padding: 10px 15px;
            border: none;
            border-radius: 6px;
            font-size: 0.9rem;
            cursor: pointer;
            text-decoration: none;
            text-align: center;
            transition: background 0.2s;
        }}
        .btn-primary {{
            background: #4361ee;
            color: white;
        }}
        .btn-primary:hover {{ background: #3a56d4; }}
        .btn-secondary {{
            background: #e9ecef;
            color: #333;
        }}
        .btn-secondary:hover {{ background: #dee2e6; }}
        .missing {{
            opacity: 0.5;
            pointer-events: none;
        }}
        footer {{
            text-align: center;
            margin-top: 40px;
            color: #666;
            font-size: 0.9rem;
        }}
        .badge {{
            display: inline-block;
            padding: 3px 8px;
            border-radius: 4px;
            font-size: 0.75rem;
            font-weight: bold;
        }}
        .badge-success {{ background: #d4edda; color: #155724; }}
        .badge-warning {{ background: #fff3cd; color: #856404; }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>{description}</h1>
            <p class="subtitle">Project: {building_id}</p>
            <div class="stats">
                <div class="stat">
                    <div class="stat-value">{sqft:.0f}</div>
                    <div class="stat-label">Square Feet</div>
                </div>
                <div class="stat">
                    <div class="stat-value">{answers.get('bedrooms', 'N/A')}</div>
                    <div class="stat-label">Bedrooms</div>
                </div>
                <div class="stat">
                    <div class="stat-value">{answers.get('bathrooms', 'N/A')}</div>
                    <div class="stat-label">Bathrooms</div>
                </div>
                <div class="stat">
                    <div class="stat-value">{successful}/{total}</div>
                    <div class="stat-label">Drawings Generated</div>
                </div>
            </div>
        </header>

        <div class="drawings-grid">
'''

    for sheet_num, title, filename in DRAWING_FILES:
        filepath = output_dir / filename
        exists = filepath.exists()
        pdf_exists = (output_dir / filename.replace('.svg', '.pdf')).exists()

        card_class = "" if exists else "missing"

        html += f'''            <div class="drawing-card {card_class}">
                <div class="drawing-preview">
                    {'<img src="' + filename + '" alt="' + title + '">' if exists else '<span style="color:#999">Drawing not generated</span>'}
                </div>
                <div class="drawing-info">
                    <span class="drawing-number">{sheet_num}</span>
                    <h3 class="drawing-title">{title}</h3>
                    <div class="drawing-actions">
                        <a href="{filename}" target="_blank" class="btn btn-primary" {'disabled' if not exists else ''}>View SVG</a>
                        {'<a href="' + filename.replace('.svg', '.pdf') + '" target="_blank" class="btn btn-secondary">PDF</a>' if pdf_exists else ''}
                    </div>
                </div>
            </div>
'''

    html += f'''        </div>

        <footer>
            <p>Generated by ArchEngine on {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>
        </footer>
    </div>
</body>
</html>
'''

    return html


# =============================================================================
# MAIN PIPELINE
# =============================================================================

def run_pipeline(
    input_path: str,
    output_dir: str,
    scale: float = 0.05,
    validate: bool = True,
    enrich: bool = True,
    generate_pdf: bool = False,
    sheet_size: str = 'arch_d',
    skip: List[str] = None
) -> Dict[str, Tuple[bool, str]]:
    """
    Run the complete drawing generation pipeline.

    Args:
        input_path: Path to input JSON file
        output_dir: Output directory path
        scale: Drawing scale factor
        validate: Run schema validation
        enrich: Enrich data with wall types and roofs
        generate_pdf: Generate PDF output
        sheet_size: PDF sheet size
        skip: List of generators to skip

    Returns:
        Dictionary of generator results
    """
    skip = skip or []
    results = {}

    input_path = Path(input_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load building data
    with log_section(logger, "Loading Building Data"):
        try:
            with open(input_path, 'r') as f:
                building_data = json.load(f)
            logger.info(f"Loaded: {input_path}")
            logger.info(f"Building size: {building_data.get('width', 'N/A')}mm x {building_data.get('depth', 'N/A')}mm")
        except Exception as e:
            logger.error(f"Failed to load input file: {e}")
            return {'load': (False, str(e))}

    # Validate
    if validate:
        with log_section(logger, "Schema Validation"):
            validation_result = validate_building_data(building_data)

            if not validation_result.is_valid:
                report = generate_validation_report(validation_result)
                logger.error("Validation failed:")
                for line in report.split('\n')[:20]:
                    logger.error(f"  {line}")

                # Write validation report
                report_path = output_dir / 'validation_report.txt'
                with open(report_path, 'w') as f:
                    f.write(report)
                logger.info(f"Full validation report: {report_path}")

                results['validation'] = (False, "Schema validation failed")
            else:
                logger.success(f"Validation passed ({validation_result.warnings_count} warnings)")
                results['validation'] = (True, "Passed")

    # Enrich data
    if enrich:
        with log_section(logger, "Data Enrichment"):
            try:
                building_data = enrich_building_data(building_data)

                # Save enriched data
                enriched_path = output_dir / 'enriched_building.json'
                with open(enriched_path, 'w') as f:
                    json.dump(building_data, f, indent=2)
                logger.info(f"Enriched data saved: {enriched_path}")

                results['enrichment'] = (True, "Data enriched")
            except Exception as e:
                logger.error(f"Data enrichment failed: {e}")
                results['enrichment'] = (False, str(e))

    # Use enriched data for generation
    enriched_path = output_dir / 'enriched_building.json'
    if enriched_path.exists():
        gen_input = str(enriched_path)
    else:
        gen_input = str(input_path)

    # Run generators
    total_generators = len([g for g in GENERATOR_SCRIPTS if g not in skip])
    progress = ProgressLogger(logger, total_generators, "Drawing Generation")

    with log_section(logger, "Generating Drawings"):
        for gen_name, (script_name, description) in GENERATOR_SCRIPTS.items():
            if gen_name in skip:
                logger.info(f"Skipping: {description}")
                results[gen_name] = (False, "Skipped")
                continue

            with log_step(logger, description):
                success, message = run_generator(script_name, gen_input, str(output_dir), scale)
                results[gen_name] = (success, message)

                if success:
                    for line in message.split('\n'):
                        if line.strip():
                            logger.debug(f"  {line}")
                else:
                    logger.error(f"  {message}")

            progress.step(description)

    # Generate HTML index
    with log_section(logger, "Generating Index"):
        try:
            index_html = generate_html_index(output_dir, building_data, results)
            index_path = output_dir / 'index.html'
            with open(index_path, 'w') as f:
                f.write(index_html)
            logger.success(f"HTML index: {index_path}")
            results['index'] = (True, str(index_path))
        except Exception as e:
            logger.error(f"Failed to generate index: {e}")
            results['index'] = (False, str(e))

    # Generate PDFs
    if generate_pdf:
        with log_section(logger, "PDF Export"):
            if not PDF_AVAILABLE:
                logger.warning("PDF export requires reportlab. Install with: pip install reportlab svglib")
                results['pdf'] = (False, "reportlab not installed")
            else:
                try:
                    pdf_sheet_size = SheetSize(sheet_size)
                    project_name = building_data.get('qbd_answers', {}).get('description', 'Project')

                    pdf_files = batch_convert_svg_to_pdf(
                        str(output_dir),
                        str(output_dir),
                        sheet_size=pdf_sheet_size,
                        project_name=project_name,
                        create_set=True
                    )

                    logger.success(f"Generated {len(pdf_files)} PDF files")
                    results['pdf'] = (True, f"{len(pdf_files)} PDFs generated")
                except Exception as e:
                    logger.error(f"PDF export failed: {e}")
                    logger.debug(traceback.format_exc())
                    results['pdf'] = (False, str(e))

    return results


def print_summary(results: Dict[str, Tuple[bool, str]], output_dir: Path):
    """Print a summary of the generation results."""
    print("\n" + "=" * 70)
    print("GENERATION SUMMARY")
    print("=" * 70)

    successful = sum(1 for v in results.values() if v[0])
    total = len(results)

    print(f"\nResults: {successful}/{total} successful\n")

    for name, (success, message) in results.items():
        status = "OK" if success else "FAILED"
        status_color = "\033[32m" if success else "\033[31m"
        reset = "\033[0m"
        print(f"  {status_color}[{status:6}]{reset} {name}: {message[:50]}")

    print("\n" + "-" * 70)

    # List generated files
    svg_files = list(output_dir.glob("*.svg"))
    pdf_files = list(output_dir.glob("*.pdf"))

    print(f"\nOutput directory: {output_dir}")
    print(f"  SVG files: {len(svg_files)}")
    print(f"  PDF files: {len(pdf_files)}")

    index_path = output_dir / 'index.html'
    if index_path.exists():
        print(f"\nView drawings: file://{index_path.absolute()}")

    print("=" * 70)


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Generate complete architectural drawing set from building JSON',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  python generate_all.py building.json -o ./output
  python generate_all.py building.json -o ./output --pdf
  python generate_all.py building.json -o ./output --pdf --sheet-size arch_e
  python generate_all.py building.json -o ./output --skip plans sections
        '''
    )

    parser.add_argument('input', nargs='?',
                       default='../../Shared/TestData/output/generated_building.json',
                       help='Input JSON file path')
    parser.add_argument('-o', '--output',
                       default='../../Shared/TestData/output',
                       help='Output directory')
    parser.add_argument('-s', '--scale', type=float, default=0.05,
                       help='Scale factor (default: 0.05)')
    parser.add_argument('--pdf', action='store_true',
                       help='Generate PDF output')
    parser.add_argument('--sheet-size', default='arch_d',
                       choices=['arch_a', 'arch_b', 'arch_c', 'arch_d', 'arch_e',
                               'a4', 'a3', 'a2', 'a1', 'a0'],
                       help='PDF sheet size (default: arch_d)')
    parser.add_argument('--skip', nargs='+', default=[],
                       choices=list(GENERATOR_SCRIPTS.keys()),
                       help='Generators to skip')
    parser.add_argument('--no-validate', action='store_true',
                       help='Skip schema validation')
    parser.add_argument('--no-enrich', action='store_true',
                       help='Skip data enrichment')
    parser.add_argument('-v', '--verbose', action='store_true',
                       help='Verbose output')
    parser.add_argument('-q', '--quiet', action='store_true',
                       help='Quiet mode (errors only)')

    args = parser.parse_args()

    # Setup logging
    import logging
    if args.quiet:
        log_level = logging.ERROR
    elif args.verbose:
        log_level = logging.DEBUG
    else:
        log_level = logging.INFO

    setup_logging(
        name='archengine',
        level=log_level,
        console=True,
        colors=True,
        log_dir=args.output
    )

    # Check input file
    input_path = Path(args.input)
    if not input_path.exists():
        logger.error(f"Input file not found: {input_path}")
        sys.exit(1)

    # Run pipeline
    results = run_pipeline(
        input_path=str(input_path),
        output_dir=args.output,
        scale=args.scale,
        validate=not args.no_validate,
        enrich=not args.no_enrich,
        generate_pdf=args.pdf,
        sheet_size=args.sheet_size,
        skip=args.skip
    )

    # Print summary
    print_summary(results, Path(args.output))

    # Exit with appropriate code
    all_success = all(v[0] for v in results.values())
    sys.exit(0 if all_success else 1)


if __name__ == '__main__':
    main()
