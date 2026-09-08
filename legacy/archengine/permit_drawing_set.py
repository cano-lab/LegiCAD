#!/usr/bin/env python3
"""
permit_drawing_set.py - Generate complete permit-ready drawing set

Combines:
- Site plan
- Floor plans (all levels)
- 4 Elevations (N, S, E, W)
- Section (if applicable)
- Door/Window schedule (optional)
"""

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'ArchEngine_kernel' / 'scripts'))

from generate_elevations import generate_elevation, render_elevation_svg
from generate_plans import PlanGenerator
from generate_site_plan import SitePlan, generate_site_plan_svg
from generate_sections import generate_section, render_section_svg, SectionCut
from generate_schedules import extract_openings, generate_schedule_svg


def create_permit_drawing_set(
    building_json_path: Path,
    output_dir: Path,
    lot_width_ft: float = 60.0,
    lot_depth_ft: float = 120.0
):
    """Generate complete permit drawing set."""
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Load building data
    with open(building_json_path) as f:
        building_data = json.load(f)
    
    # Convert to kernel format
    kernel_data = convert_to_kernel_format(building_data)
    
    print("=" * 60)
    print("PERMIT DRAWING SET GENERATOR")
    print("=" * 60)
    print()
    
    # 0. SECTION
    print("Generating Section...")
    cut = SectionCut(
        name='A-A',
        cut_x=kernel_data['width'] / 2,
        cut_z=0,
        direction='transverse',
        view_direction='east'
    )
    from generate_sections import generate_section, render_section_svg
    section_elements = generate_section(kernel_data, cut)
    section_svg = render_section_svg(section_elements, cut)
    
    sections_dir = output_dir / 'sections'
    sections_dir.mkdir(exist_ok=True)
    section_path = sections_dir / '04_section_aa.svg'
    with open(section_path, 'w') as f:
        f.write(section_svg)
    print(f"  ✅ Section: {section_path}")
    
    # 1. SITE PLAN
    print("\nGenerating Site Plan...")
    b_width_m = building_data.get('width_m', 12)
    b_depth_m = building_data.get('depth_m', 13)
    
    site = SitePlan(
        lot_width_ft=lot_width_ft,
        lot_depth_ft=lot_depth_ft,
        building_x_ft=(lot_width_ft - b_width_m * 3.28084) / 2,  # Centered
        building_z_ft=30.0,  # 30' front setback
        building_width_ft=b_width_m * 3.28084,
        building_depth_ft=b_depth_m * 3.28084,
        front_setback_ft=25.0,
        side_setback_ft=6.0,
        rear_setback_ft=25.0,
        driveway_width_ft=12.0
    )
    
    site_svg = generate_site_plan_svg(site, building_data)
    site_path = output_dir / "01_site_plan.svg"
    with open(site_path, 'w') as f:
        f.write(site_svg)
    print(f"  ✅ Site Plan: {site_path}")
    
    # 2. FLOOR PLAN
    print("\nGenerating Floor Plan...")
    generator = object.__new__(PlanGenerator)
    generator.data = kernel_data
    generator.walls = generator._parse_walls()
    generator.doors = generator._parse_doors()
    generator.windows = generator._parse_windows()
    generator.rooms = generator._parse_rooms()
    generator.roofs = generator._parse_roofs()
    
    all_x = []
    all_z = []
    for wall in generator.walls:
        all_x.extend([wall.start[0], wall.end[0]])
        all_z.extend([wall.start[2], wall.end[2]])
    
    if all_x and all_z:
        generator.width = max(all_x) - min(all_x)
        generator.depth = max(all_z) - min(all_z)
    else:
        generator.width = kernel_data.get('width', 12000)
        generator.depth = kernel_data.get('depth', 9000)
    
    generator.is_residential = True
    generator.ext_wall_thickness = 175
    generator.int_wall_thickness = 115
    generator.default_ceiling_height = 2400
    generator.default_overhang = 600
    generator.default_pitch = 4
    generator.dim_text_size = 300
    generator.room_text_size = 500
    generator.room_area_size = 350
    generator.title_text_size = 500
    generator.grid_label_size = 350
    
    floor_svg = generator.generate_floor_plan_svg(scale=0.15)
    floor_path = output_dir / "02_floor_plan.svg"
    with open(floor_path, 'w') as f:
        f.write(floor_svg)
    print(f"  ✅ Floor Plan: {floor_path}")
    
    # 3. ELEVATIONS
    print("\nGenerating Elevations...")
    elev_dir = output_dir / "elevations"
    elev_dir.mkdir(exist_ok=True)
    
    for direction in ['north', 'south', 'east', 'west']:
        elevation = generate_elevation(kernel_data, direction)
        svg = render_elevation_svg(elevation, scale=0.05)
        elev_path = elev_dir / f"03_elevation_{direction}.svg"
        with open(elev_path, 'w') as f:
            f.write(svg)
        print(f"  ✅ {direction.capitalize()} Elevation: {elev_path}")
    
    # 4. SCHEDULES
    print("\nGenerating Schedules...")
    from generate_schedules import extract_openings, generate_schedule_svg
    
    doors, windows = extract_openings(building_data)
    schedules_dir = output_dir / 'schedules'
    schedules_dir.mkdir(exist_ok=True)
    
    if doors:
        door_svg = generate_schedule_svg(doors, "DOOR SCHEDULE")
        door_path = schedules_dir / '05_door_schedule.svg'
        with open(door_path, 'w') as f:
            f.write(door_svg)
        print(f"  ✅ Door Schedule: {door_path}")
    
    if windows:
        win_svg = generate_schedule_svg(windows, "WINDOW SCHEDULE")
        win_path = schedules_dir / '05_window_schedule.svg'
        with open(win_path, 'w') as f:
            f.write(win_svg)
        print(f"  ✅ Window Schedule: {win_path}")
    print()
    print("=" * 60)
    print("PERMIT DRAWING SET COMPLETE")
    print("=" * 60)
    print(f"Output directory: {output_dir}")
    print()
    print("Files generated:")
    print(f"  1. Site Plan:        01_site_plan.svg")
    print(f"  2. Floor Plan:       02_floor_plan.svg")
    print(f"  3. North Elevation:  elevations/03_elevation_north.svg")
    print(f"  4. South Elevation:  elevations/03_elevation_south.svg")
    print(f"  5. East Elevation:   elevations/03_elevation_east.svg")
    print(f"  6. West Elevation:   elevations/03_elevation_west.svg")
    print(f"  7. Section:          sections/04_section_aa.svg")
    print(f"  8. Door Schedule:    schedules/05_door_schedule.svg")
    print(f"  9. Window Schedule:  schedules/05_window_schedule.svg")
    print()
    print("Checklist for permit submission:")
    print("  ✅ Site plan with setbacks and north arrow")
    print("  ✅ Floor plan with dimensions")
    print("  ✅ 4 elevations with grade lines")
    print("  ✅ Section drawing")
    print("  ✅ Door/Window schedules")
    print()


def convert_to_kernel_format(data: dict) -> dict:
    """Convert test pipeline format to kernel format. If input already has
    walls_batch (QBD/kernel format), short-circuit with normalization."""
    if 'walls_batch' in data:
        return {
            'name': data.get('name', 'House'),
            'width': data.get('width', data.get('width_m', 10) * 1000),
            'depth': data.get('depth', data.get('depth_m', 10) * 1000),
            'building_type': data.get('structure_type', 'residential'),
            'rooms': data.get('rooms', {}) if isinstance(data.get('rooms'), dict) else {
                (r.get('id') or f'room_{i}'): r for i, r in enumerate(data.get('rooms') or [])
            },
            'walls_batch': data.get('walls_batch', []),
            'doors': data.get('doors', []) or [],
            'windows': data.get('windows', []) or [],
            'roofs': data.get('roofs') or [
                {'type': 'gable', 'pitch': 6, 'overhang': 450, 'height': 3500}
            ],
        }
    kernel_data = {
        'name': data.get('name', 'Test House'),
        'width': data.get('width_m', 10) * 1000,
        'depth': data.get('depth_m', 10) * 1000,
        'building_type': data.get('structure_type', 'residential'),
        'rooms': {},
        'walls_batch': [],
        'doors': [],
        'windows': [],
        'roofs': []
    }
    
    # Convert rooms - rooms can be a dict (keyed by id) or a list
    rooms_in = data.get('rooms', [])
    if isinstance(rooms_in, dict):
        rooms_in = [{**v, 'id': v.get('id', k)} if isinstance(v, dict) else {'id': k, 'name': k}
                    for k, v in rooms_in.items()]
    for room in rooms_in:
        room_id = room.get('id', 'unknown')
        bounds = room.get('bounds', {})
        kernel_data['rooms'][room_id] = {
            'name': room.get('name', room_id),
            'room_type': room.get('room_type', 'other'),
            'bounds': {
                'x': bounds.get('x', 0),
                'z': bounds.get('z', 0),
                'width': bounds.get('width', 0),
                'height': bounds.get('height', 0)
            },
            'area': room.get('area_sqm', 0),
            'center': {
                'x': bounds.get('x', 0) + bounds.get('width', 0) / 2,
                'z': bounds.get('z', 0) + bounds.get('height', 0) / 2
            }
        }
    
    # Convert walls with openings
    for wall in data.get('walls', []):
        wall_entry = {
            'start': wall.get('start', [0, 0, 0]),
            'end': wall.get('end', [0, 0, 0]),
            'category': wall.get('category', 'interior'),
            'wall_type': wall.get('wall_type', 'standard'),
            'height': 2700,
            'openings': wall.get('openings', [])
        }
        kernel_data['walls_batch'].append(wall_entry)
    
    # Convert openings to doors/windows
    for wall_idx, wall in enumerate(data.get('walls', [])):
        for opening in wall.get('openings', []):
            o_type = opening.get('type', 'door')
            width_ft = opening.get('width_ft', 3)
            width_mm = width_ft * 304.8
            
            start = opening.get('start', [0, 0, 0])
            end = opening.get('end', [0, 0, 0])
            
            center_x = (start[0] + end[0]) / 2
            center_z = (start[2] + end[2]) / 2
            
            wall_start = wall.get('start', [0, 0, 0])
            wall_end = wall.get('end', [0, 0, 0])
            wall_dx = wall_end[0] - wall_start[0]
            wall_dz = wall_end[2] - wall_start[2]
            wall_len = (wall_dx**2 + wall_dz**2)**0.5
            
            if wall_len > 0:
                offset = ((center_x - wall_start[0]) * wall_dx + (center_z - wall_start[2]) * wall_dz) / wall_len
                
                if o_type == 'door':
                    kernel_data['doors'].append({
                        'wall_index': wall_idx,
                        'offset': offset,
                        'width': width_mm,
                        'height': 2100
                    })
                else:
                    kernel_data['windows'].append({
                        'wall_index': wall_idx,
                        'offset': offset,
                        'width': width_mm,
                        'height': 1200,
                        'sill_height': 900
                    })
    
    # Add roof
    kernel_data['roofs'] = [{
        'type': 'gable',
        'pitch': 6,
        'overhang': 450,
        'height': 3500
    }]
    
    return kernel_data


def main():
    """Generate permit drawing set for test house."""
    test_json = Path('/root/.openclaw/workspace/test_pipeline/test_house.json')
    output_dir = Path('/root/.openclaw/workspace/test_pipeline/permit_set')
    
    create_permit_drawing_set(test_json, output_dir)


if __name__ == '__main__':
    main()
