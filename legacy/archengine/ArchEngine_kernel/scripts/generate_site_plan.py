"""
generate_site_plan.py - Site plan SVG generator.

Produces a permit-style site plan: lot boundary, building footprint, setbacks,
driveway. Distances in feet (Ontario residential convention is mixed; permit
sets in Toronto/Ottawa typically use imperial for site plans).
"""
from dataclasses import dataclass
from typing import Dict


@dataclass
class SitePlan:
    lot_width_ft: float
    lot_depth_ft: float
    building_x_ft: float
    building_z_ft: float
    building_width_ft: float
    building_depth_ft: float
    front_setback_ft: float
    side_setback_ft: float
    rear_setback_ft: float
    driveway_width_ft: float


def generate_site_plan_svg(site: SitePlan, building_data: Dict) -> str:
    scale = 5.0
    margin = 60.0
    w = site.lot_width_ft * scale + 2 * margin
    h = site.lot_depth_ft * scale + 2 * margin

    def x(ft: float) -> float:
        return margin + ft * scale

    def y(ft: float) -> float:
        return h - margin - ft * scale

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
        f'<rect width="{w}" height="{h}" fill="white"/>',
        f'<rect x="{x(0)}" y="{y(site.lot_depth_ft)}" '
        f'width="{site.lot_width_ft*scale}" height="{site.lot_depth_ft*scale}" '
        f'fill="#f4f4f0" stroke="black" stroke-width="2"/>',
    ]

    setback_attrs = 'fill="none" stroke="#888" stroke-width="1" stroke-dasharray="6,4"'
    parts.append(
        f'<rect x="{x(site.side_setback_ft)}" '
        f'y="{y(site.lot_depth_ft - site.rear_setback_ft)}" '
        f'width="{(site.lot_width_ft - 2*site.side_setback_ft)*scale}" '
        f'height="{(site.lot_depth_ft - site.front_setback_ft - site.rear_setback_ft)*scale}" '
        f'{setback_attrs}/>'
    )

    parts.append(
        f'<rect x="{x(site.building_x_ft)}" '
        f'y="{y(site.building_z_ft + site.building_depth_ft)}" '
        f'width="{site.building_width_ft*scale}" '
        f'height="{site.building_depth_ft*scale}" '
        f'fill="#d8d4c8" stroke="black" stroke-width="1.5"/>'
    )

    drive_x = site.building_x_ft + (site.building_width_ft - site.driveway_width_ft) / 2
    parts.append(
        f'<rect x="{x(drive_x)}" y="{y(site.building_z_ft)}" '
        f'width="{site.driveway_width_ft*scale}" '
        f'height="{site.building_z_ft*scale}" '
        f'fill="#e8e4d8" stroke="#888" stroke-width="1"/>'
    )

    label_attrs = 'font-family="Helvetica, Arial, sans-serif" font-size="11" fill="black"'
    parts.append(
        f'<text x="{x(site.lot_width_ft/2)}" y="{y(-2)}" text-anchor="middle" {label_attrs}>'
        f'LOT: {site.lot_width_ft:.0f}\' x {site.lot_depth_ft:.0f}\''
        f'</text>'
    )
    parts.append(
        f'<text x="{x(site.building_x_ft + site.building_width_ft/2)}" '
        f'y="{y(site.building_z_ft + site.building_depth_ft/2)}" '
        f'text-anchor="middle" dominant-baseline="middle" {label_attrs}>'
        f'BUILDING'
        f'</text>'
    )
    parts.append(
        f'<text x="{x(2)}" y="{y(2)}" {label_attrs}>'
        f'Setbacks: F {site.front_setback_ft:.0f}\' / S {site.side_setback_ft:.0f}\' / R {site.rear_setback_ft:.0f}\''
        f'</text>'
    )

    parts.append('</svg>')
    return '\n'.join(parts)
