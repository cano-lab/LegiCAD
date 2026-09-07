#!/usr/bin/env python3
"""
Physics Bridge - Connects ArchEngine (C++) to Python physics modules
"""

import sys
import json
import os

# Add physics module to path
physics_path = os.path.join(os.path.dirname(__file__), '..', '..', 'RevitMCP-physics-engine', 'server', 'physics')
sys.path.insert(0, os.path.abspath(physics_path))

from structural import StructuralAnalyzer, Material, MaterialType
from thermal import ThermalAnalyzer
from lighting import LightingAnalyzer
from acoustic import AcousticAnalyzer
from dataclasses import asdict


def get_material(name: str) -> Material:
    """Get material by name."""
    materials = {
        'steel': Material.steel_a992(),
        'a36': Material.steel_a36(),
        'a992': Material.steel_a992(),
        'wood': Material.wood_df(),
        'spf': Material.wood_spf(),
        'df': Material.wood_df(),
        'concrete': Material.concrete_4000(),
        'concrete_3000': Material.concrete_3000(),
        'concrete_4000': Material.concrete_4000(),
    }
    return materials.get(name.lower(), Material.steel_a992())


class PhysicsBridge:
    """Bridge between C++ and Python physics."""

    def __init__(self):
        self.structural = StructuralAnalyzer()
        self.thermal = ThermalAnalyzer()
        self.lighting = LightingAnalyzer()
        self.acoustic = AcousticAnalyzer()

    def analyze_beam(self, span_ft: float, width_in: float, depth_in: float,
                     material: str, uniform_load_plf: float = 100.0, **kwargs) -> dict:
        """Analyze a beam and return results as dict."""
        mat = get_material(material)
        result = self.structural.analyze_simple_beam(
            span_ft=span_ft,
            width_in=width_in,
            depth_in=depth_in,
            material=mat,
            uniform_load_plf=uniform_load_plf
        )
        return {
            'passes': result.passes,
            'max_stress_psi': result.max_stress_psi,
            'allowable_stress_psi': result.allowable_stress_psi,
            'max_deflection_in': result.max_deflection_in,
            'allowable_deflection_in': result.allowable_deflection_in,
            'utilization_ratio': result.utilization_ratio,
            'warnings': result.warnings
        }

    def analyze_column(self, height_ft: float, width_in: float, depth_in: float,
                       material: str, axial_load_lbs: float = 10000.0, **kwargs) -> dict:
        """Analyze a column and return results as dict."""
        mat = get_material(material)
        result = self.structural.analyze_column(
            height_ft=height_ft,
            width_in=width_in,
            depth_in=depth_in,
            material=mat,
            axial_load_lbs=axial_load_lbs
        )
        return {
            'passes': result.passes,
            'applied_load_lbs': result.applied_load_lbs,
            'allowable_load_lbs': result.allowable_load_lbs,
            'slenderness_ratio': result.slenderness_ratio,
            'utilization_ratio': result.utilization_ratio,
            'buckling_mode': result.buckling_mode,
            'warnings': result.warnings
        }

    def analyze_thermal(self, elements: list, outdoor_temp_f: float = 35.0,
                        indoor_temp_f: float = 70.0, **kwargs) -> dict:
        """Analyze thermal performance."""
        results = []
        for elem in elements:
            # Simple wall/floor thermal analysis
            area_sqft = elem.get('area_sqft', 100)
            r_value = elem.get('r_value', 13)
            u_value = 1.0 / r_value
            heat_loss = u_value * area_sqft * (indoor_temp_f - outdoor_temp_f)
            results.append({
                'element_id': elem.get('id', 'unknown'),
                'u_value': u_value,
                'heat_loss_btu_hr': heat_loss,
                'passes': r_value >= 13  # Basic code compliance
            })
        return {'elements': results, 'total_heat_loss': sum(r['heat_loss_btu_hr'] for r in results)}

    def analyze_lighting(self, room_width_ft: float, room_depth_ft: float,
                         room_height_ft: float, window_area_sqft: float = 0,
                         reflectances: dict = None, **kwargs) -> dict:
        """Analyze lighting/daylight."""
        floor_area = room_width_ft * room_depth_ft
        window_ratio = window_area_sqft / floor_area if floor_area > 0 else 0

        # Simple daylight factor estimation
        daylight_factor = window_ratio * 10  # Rough approximation
        avg_lux = daylight_factor * 100  # Rough exterior illuminance factor

        return {
            'daylight_factor': daylight_factor,
            'avg_illuminance_lux': avg_lux,
            'window_to_floor_ratio': window_ratio,
            'meets_code': window_ratio >= 0.08,  # 8% minimum for habitable
            'recommendations': ['Add skylights' if daylight_factor < 2 else 'Adequate daylight']
        }

    def analyze_acoustic(self, room_volume_cuft: float, surface_areas: dict = None,
                         absorption_coeffs: dict = None, **kwargs) -> dict:
        """Analyze room acoustics."""
        if surface_areas is None:
            surface_areas = {'walls': 400, 'floor': 100, 'ceiling': 100}
        if absorption_coeffs is None:
            absorption_coeffs = {'walls': 0.05, 'floor': 0.1, 'ceiling': 0.7}

        # Calculate RT60 using Sabine formula
        total_absorption = sum(
            surface_areas.get(surf, 0) * absorption_coeffs.get(surf, 0.1)
            for surf in surface_areas
        )

        rt60 = 0.049 * room_volume_cuft / total_absorption if total_absorption > 0 else 999

        return {
            'rt60_seconds': rt60,
            'total_absorption_sabins': total_absorption,
            'room_volume_cuft': room_volume_cuft,
            'quality': 'Good' if 0.4 <= rt60 <= 0.8 else 'Needs treatment',
            'recommendations': self._acoustic_recommendations(rt60)
        }

    def _acoustic_recommendations(self, rt60: float) -> list:
        if rt60 > 1.5:
            return ['Add acoustic panels', 'Consider acoustic ceiling tiles', 'Add soft furnishings']
        elif rt60 > 0.8:
            return ['Consider some acoustic treatment']
        elif rt60 < 0.4:
            return ['Room may feel dead - reduce absorption']
        return ['Acoustic conditions are good']


    def analyze_frame(self, elements: list, **kwargs) -> dict:
        """Analyze entire structural frame at once (batched)."""
        beams = []
        columns = []
        all_pass = True
        max_beam_util = 0.0
        max_col_util = 0.0

        for elem in elements:
            elem_type = elem.get('type', 'beam').lower()

            if elem_type == 'beam':
                result = self.analyze_beam(
                    span_ft=elem.get('span_ft', 10),
                    width_in=elem.get('width_in', 6),
                    depth_in=elem.get('depth_in', 12),
                    material=elem.get('material', 'steel'),
                    uniform_load_plf=elem.get('uniform_load_plf', 100)
                )
                beams.append(result)
                if not result['passes']:
                    all_pass = False
                max_beam_util = max(max_beam_util, result['utilization_ratio'])

            elif elem_type == 'column':
                result = self.analyze_column(
                    height_ft=elem.get('height_ft', 10),
                    width_in=elem.get('width_in', 6),
                    depth_in=elem.get('depth_in', 6),
                    material=elem.get('material', 'steel'),
                    axial_load_lbs=elem.get('axial_load_lbs', 10000)
                )
                columns.append(result)
                if not result['passes']:
                    all_pass = False
                max_col_util = max(max_col_util, result['utilization_ratio'])

        return {
            'beams': beams,
            'columns': columns,
            'all_pass': all_pass,
            'max_beam_utilization': max_beam_util,
            'max_column_utilization': max_col_util
        }


def main():
    """CLI entry point for physics bridge."""
    if len(sys.argv) < 3:
        print("Usage: physics_bridge.py <function> <input.json> [output.json]", file=sys.stderr)
        sys.exit(1)

    function = sys.argv[1]
    input_file = sys.argv[2]
    output_file = sys.argv[3] if len(sys.argv) > 3 else None

    # Load input
    with open(input_file) as f:
        args = json.load(f)

    # Create bridge and call function
    bridge = PhysicsBridge()

    if hasattr(bridge, function):
        result = getattr(bridge, function)(**args)
    else:
        result = {'error': f'Unknown function: {function}'}

    # Output result
    if output_file:
        with open(output_file, 'w') as f:
            json.dump(result, f, indent=2)
    else:
        print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
