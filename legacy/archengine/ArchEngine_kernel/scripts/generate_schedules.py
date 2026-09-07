#!/usr/bin/env python3
"""
generate_schedules.py - Generate door and window schedules for permit drawings

Tables listing all openings with dimensions, types, and locations.
"""

import json
from pathlib import Path
from typing import List, Dict
from dataclasses import dataclass


@dataclass
class ScheduleEntry:
    """Single entry in a schedule."""
    mark: str  # D1, W1, etc.
    qty: int
    width_mm: float
    height_mm: float
    type_name: str
    location: str
    remarks: str = ""


def extract_openings(data: dict) -> tuple[List[ScheduleEntry], List[ScheduleEntry]]:
    """Extract doors and windows from building data.

    Reads the canonical qbd schema's top-level `doors` / `windows`
    arrays first; falls back to the legacy `wall.openings` shape if the
    top-level arrays are absent. The fallback was the only path the
    original implementation supported, but qbd_layout_generator never
    populates `wall.openings` — it writes top-level arrays. The Rust
    port (ls-qbd::schedule) uses the same precedence.
    """
    doors = []
    windows = []
    door_count = 0
    window_count = 0

    room_names = {}
    rooms_in = data.get('rooms', [])
    if isinstance(rooms_in, dict):
        rooms_in = [{**v, 'id': v.get('id', k)} if isinstance(v, dict) else {'id': k, 'name': k}
                    for k, v in rooms_in.items()]
    for room in rooms_in:
        room_names[room.get('id', '')] = room.get('name', 'Unknown')

    def room_label(rid: str) -> str:
        if not rid:
            return ''
        return room_names.get(rid, rid)

    def location_for(wall_idx: int, room1: str, room2: str) -> str:
        r1, r2 = room_label(room1), room_label(room2)
        if r1 and r2:
            return f"{r1} - {r2}"
        if r1:
            return r1
        if r2:
            return r2
        return f"Wall {wall_idx}"

    # Canonical path: top-level doors/windows.
    top_doors = data.get('doors', []) or []
    top_windows = data.get('windows', []) or []

    for d in top_doors:
        door_count += 1
        width_mm = float(d.get('width', 914))
        height_mm = float(d.get('height', 2134))
        if width_mm < 1000:
            type_name = "Single Door"
        elif width_mm < 2000:
            type_name = "Double Door"
        else:
            type_name = "Sliding Door"
        doors.append(ScheduleEntry(
            mark=f"D{door_count}",
            qty=1,
            width_mm=width_mm,
            height_mm=height_mm,
            type_name=type_name,
            location=location_for(int(d.get('wall_index', 0)),
                                  d.get('room1', ''), d.get('room2', '')),
            remarks="",
        ))

    for w in top_windows:
        window_count += 1
        width_mm = float(w.get('width', 1200))
        height_mm = float(w.get('height', 1200))
        sill_mm = float(w.get('sill_height', 900))
        if width_mm < 800:
            type_name = "Casement"
        elif width_mm < 1500:
            type_name = "Double Hung"
        else:
            type_name = "Picture Window"
        windows.append(ScheduleEntry(
            mark=f"W{window_count}",
            qty=1,
            width_mm=width_mm,
            height_mm=height_mm,
            type_name=type_name,
            location=location_for(int(w.get('wall_index', 0)),
                                  w.get('room', ''), ''),
            remarks=f"Sill {int(sill_mm)}mm",
        ))

    # If the canonical path produced any output, return it.
    if doors or windows:
        return doors, windows

    # Legacy fallback: walls with nested .openings (kernel internal format).
    wall_rooms = {}
    for wall in data.get('walls', []):
        idx = wall.get('id', '')
        r1 = room_names.get(wall.get('room1', ''), wall.get('room1', ''))
        r2 = room_names.get(wall.get('room2', ''), wall.get('room2', ''))
        wall_rooms[idx] = f"{r1} - {r2}"

    for wall_idx, wall in enumerate(data.get('walls', [])):
        for opening in wall.get('openings', []):
            o_type = opening.get('type', 'door')
            width_ft = opening.get('width_ft', 3)
            width_mm = width_ft * 304.8

            wall_id = wall.get('id', '')
            location = wall_rooms.get(wall_id, f"Wall {wall_idx}")

            if o_type == 'door':
                door_count += 1
                height_mm = 2100  # Standard door height
                
                # Determine door type by width
                if width_mm < 1000:
                    type_name = "Single Door"
                elif width_mm < 2000:
                    type_name = "Double Door"
                else:
                    type_name = "Sliding Door"
                
                doors.append(ScheduleEntry(
                    mark=f"D{door_count}",
                    qty=1,
                    width_mm=width_mm,
                    height_mm=height_mm,
                    type_name=type_name,
                    location=location,
                    remarks=""
                ))
            else:  # window
                window_count += 1
                height_mm = 1200  # Standard window height
                sill_mm = 900
                
                # Determine window type
                if width_mm < 800:
                    type_name = "Casement"
                elif width_mm < 1500:
                    type_name = "Double Hung"
                else:
                    type_name = "Picture Window"
                
                windows.append(ScheduleEntry(
                    mark=f"W{window_count}",
                    qty=1,
                    width_mm=width_mm,
                    height_mm=height_mm,
                    type_name=type_name,
                    location=location,
                    remarks=f"Sill {sill_mm}mm"
                ))
    
    return doors, windows


def format_dim_mm(mm: float) -> str:
    """Format dimension in mm or meters."""
    if mm >= 1000:
        return f"{mm/1000:.2f} m"
    return f"{mm:.0f} mm"


def generate_schedule_svg(entries: List[ScheduleEntry], title: str) -> str:
    """Generate schedule table as SVG."""
    
    row_height = 40
    header_height = 50
    margin = 50
    
    # Column widths
    col_mark = 80
    col_qty = 60
    col_width = 100
    col_height = 100
    col_type = 200
    col_location = 250
    col_remarks = 150
    
    table_width = col_mark + col_qty + col_width + col_height + col_type + col_location + col_remarks
    table_height = header_height + len(entries) * row_height
    
    svg_width = table_width + 2 * margin
    svg_height = table_height + 3 * margin + 60  # Extra for title
    
    lines = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    lines.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{svg_width}" height="{svg_height}" viewBox="0 0 {svg_width} {svg_height}">')
    lines.append('  <rect width="100%" height="100%" fill="white"/>')
    
    # Styles
    lines.append('  <style>')
    lines.append('    .title { font-family: Arial, sans-serif; font-size: 24px; font-weight: bold; fill: #333; }')
    lines.append('    .header { font-family: Arial, sans-serif; font-size: 14px; font-weight: bold; fill: #fff; }')
    lines.append('    .cell { font-family: Arial, sans-serif; font-size: 12px; fill: #333; }')
    lines.append('    .header-bg { fill: #333; }')
    lines.append('    .cell-bg { fill: #fff; }')
    lines.append('    .cell-bg-alt { fill: #f5f5f5; }')
    lines.append('    .border { stroke: #333; stroke-width: 1; fill: none; }')
    lines.append('  </style>')
    
    # Title
    title_y = margin + 30
    lines.append(f'  <text x="{svg_width/2}" y="{title_y}" text-anchor="middle" class="title">{title}</text>')
    
    # Table origin
    table_x = margin
    table_y = margin + 60
    
    # Header row
    lines.append(f'  <rect x="{table_x}" y="{table_y}" width="{table_width}" height="{header_height}" class="header-bg"/>')
    
    x = table_x
    headers = ['MARK', 'QTY', 'WIDTH', 'HEIGHT', 'TYPE', 'LOCATION', 'REMARKS']
    widths = [col_mark, col_qty, col_width, col_height, col_type, col_location, col_remarks]
    
    for header, width in zip(headers, widths):
        lines.append(f'  <text x="{x + width/2}" y="{table_y + header_height/2 + 5}" text-anchor="middle" class="header">{header}</text>')
        x += width
    
    # Data rows
    y = table_y + header_height
    for i, entry in enumerate(entries):
        bg_class = 'cell-bg-alt' if i % 2 else 'cell-bg'
        lines.append(f'  <rect x="{table_x}" y="{y}" width="{table_width}" height="{row_height}" class="{bg_class}"/>')
        
        x = table_x
        cells = [
            entry.mark,
            str(entry.qty),
            format_dim_mm(entry.width_mm),
            format_dim_mm(entry.height_mm),
            entry.type_name,
            entry.location,
            entry.remarks
        ]
        
        for cell, width in zip(cells, widths):
            lines.append(f'  <text x="{x + 5}" y="{y + row_height/2 + 4}" class="cell">{cell}</text>')
            x += width
        
        y += row_height
    
    # Border
    lines.append(f'  <rect x="{table_x}" y="{table_y}" width="{table_width}" height="{table_height}" class="border"/>')
    
    # Vertical lines
    x = table_x
    for width in widths[:-1]:
        x += width
        lines.append(f'  <line x1="{x}" y1="{table_y}" x2="{x}" y2="{table_y + table_height}" class="border"/>')
    
    # Horizontal lines
    y = table_y + header_height
    for i in range(len(entries)):
        lines.append(f'  <line x1="{table_x}" y1="{y}" x2="{table_x + table_width}" y2="{y}" class="border"/>')
        y += row_height
    
    lines.append('</svg>')
    return '\n'.join(lines)


def main():
    """Generate door and window schedules."""
    test_json = Path('/root/.openclaw/workspace/test_pipeline/test_house.json')
    
    with open(test_json) as f:
        data = json.load(f)
    
    doors, windows = extract_openings(data)
    
    output_dir = Path('/root/.openclaw/workspace/test_pipeline/permit_set/schedules')
    output_dir.mkdir(exist_ok=True)
    
    # Door schedule
    if doors:
        door_svg = generate_schedule_svg(doors, "DOOR SCHEDULE")
        door_path = output_dir / 'door_schedule.svg'
        with open(door_path, 'w') as f:
            f.write(door_svg)
        print(f"Door schedule: {door_path} ({len(doors)} doors)")
    
    # Window schedule
    if windows:
        win_svg = generate_schedule_svg(windows, "WINDOW SCHEDULE")
        win_path = output_dir / 'window_schedule.svg'
        with open(win_path, 'w') as f:
            f.write(win_svg)
        print(f"Window schedule: {win_path} ({len(windows)} windows)")
    
    print("\nSchedules generated successfully!")


if __name__ == '__main__':
    main()
