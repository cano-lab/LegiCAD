"""
Generator Adapters - Wrap existing generators for in-memory SVG generation.

These adapters allow the CAD application to generate drawings without
file I/O by working directly with document data dictionaries.
"""
import sys
from pathlib import Path
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from dataclasses import dataclass

# IMPORTANT: Import CAD sheets module BEFORE adding kernel scripts to path
# to prevent the kernel scripts' sheets module from shadowing it
from sheets.models import SheetType, SheetConfig

# Add kernel scripts to path for imports
_kernel_scripts = Path(__file__).parent.parent.parent / "ArchEngine_kernel" / "scripts"
if str(_kernel_scripts) not in sys.path:
    sys.path.insert(0, str(_kernel_scripts))


@dataclass
class GeneratorResult:
    """Result of a generation attempt."""
    success: bool
    svg_content: Optional[str] = None
    error_message: Optional[str] = None


class GeneratorAdapter(ABC):
    """
    Base class for generator adapters.
    Adapters wrap existing generators to work with in-memory data.
    """

    @abstractmethod
    def generate(self, data: Dict[str, Any], sheet: SheetConfig) -> GeneratorResult:
        """
        Generate SVG content from document data.

        Args:
            data: Building data dictionary (from document.to_dict())
            sheet: Sheet configuration

        Returns:
            GeneratorResult with SVG content or error
        """
        pass

    @staticmethod
    def parse_scale(scale_str: str) -> float:
        """
        Parse scale string like "1:100" to a factor.
        Returns SVG scale factor for reasonable screen display.
        """
        try:
            if ':' in scale_str:
                parts = scale_str.split(':')
                numerator = float(parts[0])
                denominator = float(parts[1])
                # For SVG, we use a factor that produces reasonable pixel sizes
                # 1:100 -> 0.15 for ~3000px output width on typical buildings
                return numerator / denominator * 15
            return 0.15
        except (ValueError, IndexError):
            return 0.15


class FloorPlanAdapter(GeneratorAdapter):
    """Adapter for floor plan generation."""

    def generate(self, data: Dict[str, Any], sheet: SheetConfig) -> GeneratorResult:
        try:
            from generate_plans import PlanGenerator

            # Create a modified generator that accepts data dict
            generator = _create_plan_generator_from_data(data)
            scale = self.parse_scale(sheet.scale)
            svg_content = generator.generate_floor_plan_svg(scale=scale)

            return GeneratorResult(success=True, svg_content=svg_content)

        except ImportError as e:
            return GeneratorResult(
                success=False,
                error_message=f"Failed to import plan generator: {e}"
            )
        except Exception as e:
            return GeneratorResult(
                success=False,
                error_message=f"Floor plan generation failed: {e}"
            )


class RoofPlanAdapter(GeneratorAdapter):
    """Adapter for roof plan generation."""

    def generate(self, data: Dict[str, Any], sheet: SheetConfig) -> GeneratorResult:
        try:
            generator = _create_plan_generator_from_data(data)
            scale = self.parse_scale(sheet.scale)
            svg_content = generator.generate_roof_plan_svg(scale=scale)

            return GeneratorResult(success=True, svg_content=svg_content)

        except ImportError as e:
            return GeneratorResult(
                success=False,
                error_message=f"Failed to import plan generator: {e}"
            )
        except Exception as e:
            return GeneratorResult(
                success=False,
                error_message=f"Roof plan generation failed: {e}"
            )


class ElevationAdapter(GeneratorAdapter):
    """Adapter for elevation generation."""

    def __init__(self, direction: str = "south"):
        """
        Initialize elevation adapter.

        Args:
            direction: "north", "south", "east", or "west"
        """
        self.direction = direction

    def generate(self, data: Dict[str, Any], sheet: SheetConfig) -> GeneratorResult:
        try:
            from generate_elevations import generate_elevation, render_elevation_svg, get_project_info_from_json

            scale = self.parse_scale(sheet.scale)

            # Generate elevation data
            elevation = generate_elevation(data, self.direction)

            # Get project info for title block
            project_info = get_project_info_from_json(data)

            # Render to SVG
            svg_content = render_elevation_svg(
                elevation,
                scale=scale,
                project_info=project_info,
                drawing_type=f'elevation_{self.direction}'
            )

            return GeneratorResult(success=True, svg_content=svg_content)

        except ImportError as e:
            return GeneratorResult(
                success=False,
                error_message=f"Failed to import elevation generator: {e}"
            )
        except Exception as e:
            return GeneratorResult(
                success=False,
                error_message=f"Elevation generation failed: {e}"
            )


class SectionAdapter(GeneratorAdapter):
    """Adapter for building section generation."""

    def __init__(self, section_id: str = "A"):
        """
        Initialize section adapter.

        Args:
            section_id: Section identifier ("A", "B", etc.)
        """
        self.section_id = section_id

    def generate(self, data: Dict[str, Any], sheet: SheetConfig) -> GeneratorResult:
        try:
            from generate_sections import (
                generate_section, render_section_svg, SectionDirection
            )
            from title_block import get_project_info_from_json

            scale = self.parse_scale(sheet.scale)

            # Determine section direction based on section_id
            # A = Transverse (cut across width), B = Longitudinal (cut along length)
            building_width = data.get('width', 10000)
            building_depth = data.get('depth', 10000)

            if self.section_id == "A":
                direction = SectionDirection.TRANSVERSE
                cut_position = building_width / 2
            else:
                direction = SectionDirection.LONGITUDINAL
                cut_position = building_depth / 2

            # Generate section data
            section = generate_section(data, direction, cut_position, self.section_id)

            # Get project info for title block
            project_info = get_project_info_from_json(data)

            # Render to SVG
            svg_content = render_section_svg(
                section,
                scale=scale,
                project_info=project_info,
                drawing_type=f'section_{self.section_id.lower()}'
            )

            return GeneratorResult(success=True, svg_content=svg_content)

        except ImportError as e:
            return GeneratorResult(
                success=False,
                error_message=f"Failed to import section generator: {e}"
            )
        except Exception as e:
            return GeneratorResult(
                success=False,
                error_message=f"Section generation failed: {e}"
            )


class DetailAdapter(GeneratorAdapter):
    """Adapter for construction details."""

    def generate(self, data: Dict[str, Any], sheet: SheetConfig) -> GeneratorResult:
        try:
            from generate_details import (
                generate_wall_section_detail,
                generate_eave_detail,
                generate_window_detail,
                generate_door_detail,
                render_details_svg
            )
            from title_block import get_project_info_from_json

            # Get wall types from data
            wall_types = data.get('wall_types', [])

            # Generate all details
            details = [
                generate_wall_section_detail(wall_types),
                generate_eave_detail(),
                generate_window_detail(),
                generate_door_detail(),
            ]

            # Get project info for title block
            project_info = get_project_info_from_json(data)

            # Render to SVG
            svg_content = render_details_svg(details, project_info)

            return GeneratorResult(success=True, svg_content=svg_content)

        except ImportError as e:
            return GeneratorResult(
                success=False,
                error_message=f"Failed to import detail generator: {e}"
            )
        except Exception as e:
            return GeneratorResult(
                success=False,
                error_message=f"Detail generation failed: {e}"
            )


class ScheduleAdapter(GeneratorAdapter):
    """Adapter for schedule generation (doors, windows, rooms)."""

    def generate(self, data: Dict[str, Any], sheet: SheetConfig) -> GeneratorResult:
        try:
            from generate_schedules import (
                extract_door_schedule,
                extract_window_schedule,
                extract_room_finish_schedule,
                render_schedules_svg
            )
            from title_block import get_project_info_from_json

            # Extract schedules from data
            door_schedule = extract_door_schedule(data)
            window_schedule = extract_window_schedule(data)
            room_schedule = extract_room_finish_schedule(data)

            # Get project info for title block
            project_info = get_project_info_from_json(data)

            # Render to SVG
            svg_content = render_schedules_svg(
                door_schedule,
                window_schedule,
                room_schedule,
                project_info
            )

            return GeneratorResult(success=True, svg_content=svg_content)

        except ImportError as e:
            return GeneratorResult(
                success=False,
                error_message=f"Failed to import schedule generator: {e}"
            )
        except Exception as e:
            return GeneratorResult(
                success=False,
                error_message=f"Schedule generation failed: {e}"
            )


# =============================================================================
# DATA-BASED GENERATOR CREATION
# =============================================================================

def _create_plan_generator_from_data(data: Dict[str, Any]):
    """
    Create a PlanGenerator that works with in-memory data.
    Monkey-patches the class to skip file loading.
    """
    from generate_plans import PlanGenerator

    # Create instance without calling __init__
    generator = object.__new__(PlanGenerator)

    # Set data directly
    generator.data = data

    # Call the parsing methods
    generator.walls = generator._parse_walls()
    generator.doors = generator._parse_doors()
    generator.windows = generator._parse_windows()
    generator.rooms = generator._parse_rooms()
    generator.roofs = generator._parse_roofs()

    # Get building bounds
    generator.width = data.get('width', 12000)
    generator.depth = data.get('depth', 9000)

    # Building type
    building_type = data.get('building_type', 'residential')
    qbd_answers = data.get('qbd_answers', {})
    generator.is_residential = (
        building_type.lower() in ['residential', 'house', 'home'] or
        qbd_answers.get('building_type', '').lower() in ['residential', 'house', 'home'] or
        'bedroom' in str(qbd_answers).lower()
    )

    # Wall thickness
    generator.ext_wall_thickness = 175
    generator.int_wall_thickness = 115

    # Roof defaults
    generator.default_overhang = 600
    generator.default_pitch = 4

    # Text sizes (in viewBox units/mm) - configurable
    generator.dim_text_size = data.get('dim_text_size', 300)
    generator.room_text_size = data.get('room_text_size', 500)
    generator.room_area_size = data.get('room_area_size', 350)
    generator.title_text_size = data.get('title_text_size', 500)
    generator.grid_label_size = data.get('grid_label_size', 350)

    return generator


def _create_elevation_generator_from_data(data: Dict[str, Any]):
    """Create an ElevationGenerator that works with in-memory data."""
    try:
        from generate_elevations import ElevationGenerator

        generator = object.__new__(ElevationGenerator)
        generator.data = data
        generator._initialize_from_data()
        return generator
    except (ImportError, AttributeError):
        # Fallback: create minimal stub
        return _MinimalElevationGenerator(data)


def _create_section_generator_from_data(data: Dict[str, Any]):
    """Create a SectionGenerator that works with in-memory data."""
    try:
        from generate_sections import SectionGenerator

        generator = object.__new__(SectionGenerator)
        generator.data = data
        generator._initialize_from_data()
        return generator
    except (ImportError, AttributeError):
        return _MinimalSectionGenerator(data)


def _create_detail_generator_from_data(data: Dict[str, Any]):
    """Create a DetailGenerator that works with in-memory data."""
    try:
        from generate_details import DetailGenerator

        generator = object.__new__(DetailGenerator)
        generator.data = data
        generator._initialize_from_data()
        return generator
    except (ImportError, AttributeError):
        return _MinimalDetailGenerator(data)


def _create_schedule_generator_from_data(data: Dict[str, Any]):
    """Create a ScheduleGenerator that works with in-memory data."""
    try:
        from generate_schedules import ScheduleGenerator

        generator = object.__new__(ScheduleGenerator)
        generator.data = data
        generator._initialize_from_data()
        return generator
    except (ImportError, AttributeError):
        return _MinimalScheduleGenerator(data)


# =============================================================================
# MINIMAL FALLBACK GENERATORS
# =============================================================================

class _MinimalElevationGenerator:
    """Minimal elevation generator when full generator unavailable."""

    def __init__(self, data: Dict):
        self.data = data
        self.width = data.get('width', 10000)
        self.depth = data.get('depth', 10000)
        self.height = 2700

    def generate_elevation_svg(self, direction: str, scale: float = 0.05) -> str:
        return self._generate_placeholder("Elevation", direction.title(), scale)

    def _generate_placeholder(self, type_name: str, subtitle: str, scale: float) -> str:
        w = max(self.width, self.depth) + 2000
        h = self.height + 2000
        return f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg"
     width="{int(w * scale)}" height="{int(h * scale)}"
     viewBox="0 0 {w} {h}">
  <rect width="{w}" height="{h}" fill="#f5f5f5"/>
  <text x="{w/2}" y="{h/2 - 200}" text-anchor="middle"
        font-family="Arial" font-size="400" fill="#999">{type_name}</text>
  <text x="{w/2}" y="{h/2 + 200}" text-anchor="middle"
        font-family="Arial" font-size="300" fill="#bbb">{subtitle}</text>
  <text x="{w/2}" y="{h/2 + 500}" text-anchor="middle"
        font-family="Arial" font-size="200" fill="#ccc">(Generator not available)</text>
</svg>'''


class _MinimalSectionGenerator(_MinimalElevationGenerator):
    """Minimal section generator."""

    def generate_section_svg(self, section_id: str, scale: float = 0.05) -> str:
        return self._generate_placeholder("Section", section_id, scale)


class _MinimalDetailGenerator(_MinimalElevationGenerator):
    """Minimal detail generator."""

    def generate_details_svg(self, scale: float = 0.05) -> str:
        return self._generate_placeholder("Details", "Construction", scale)


class _MinimalScheduleGenerator(_MinimalElevationGenerator):
    """Minimal schedule generator."""

    def generate_schedules_svg(self, scale: float = 0.05) -> str:
        return self._generate_placeholder("Schedules", "Door/Window/Room", scale)



class PresetAdapter(GeneratorAdapter):
    """Adapter for preset-based multi-viewport sheets using InteractiveSheet."""

    def __init__(self, preset_name: str):
        """
        Initialize preset adapter.

        Args:
            preset_name: Name of preset (floor_plan, elevations, sections, details, schedules)
        """
        self.preset_name = preset_name

    def generate(self, data: Dict[str, Any], sheet: SheetConfig) -> GeneratorResult:
        try:
            from sheets.interactive_sheet import InteractiveSheet
            from sheets.sheet_types import get_preset
            from sheets.sheet_sizes import get_sheet_size

            # Get sheet size - default to ARCH_D
            sheet_size_name = data.get('sheet_size', 'ARCH_D')
            sheet_size = get_sheet_size(sheet_size_name)

            # Get or reconstruct preset
            if sheet.preset_config:
                # Reconstruct from saved config
                preset = get_preset(self.preset_name, sheet_size.width_pt, sheet_size.height_pt)
                # TODO: Apply saved viewport configs
            else:
                preset = get_preset(self.preset_name, sheet_size.width_pt, sheet_size.height_pt)

            # Create InteractiveSheet with preset
            interactive_sheet = InteractiveSheet(
                json_data=data,
                sheet_size=sheet_size_name,
                scale=sheet.scale,
                title=sheet.title,
                project_name=data.get('project_name', 'Project'),
                sheet_number=sheet.number,
                preset=preset,
            )

            # Generate SVG
            svg_content = interactive_sheet.generate()

            return GeneratorResult(success=True, svg_content=svg_content)

        except ImportError as e:
            return GeneratorResult(
                success=False,
                error_message=f"Failed to import InteractiveSheet: {e}"
            )
        except Exception as e:
            return GeneratorResult(
                success=False,
                error_message=f"Preset sheet generation failed: {e}"
            )


# =============================================================================
# ADAPTER FACTORY
# =============================================================================

def get_adapter_for_sheet_type(sheet_type: SheetType) -> Optional[GeneratorAdapter]:
    """
    Get the appropriate adapter for a sheet type.

    Args:
        sheet_type: The type of sheet

    Returns:
        Configured adapter instance, or None if no adapter available
    """
    adapters = {
        SheetType.FLOOR_PLAN: FloorPlanAdapter(),
        SheetType.ROOF_PLAN: RoofPlanAdapter(),
        SheetType.ELEVATION_SOUTH: ElevationAdapter("south"),
        SheetType.ELEVATION_NORTH: ElevationAdapter("north"),
        SheetType.ELEVATION_EAST: ElevationAdapter("east"),
        SheetType.ELEVATION_WEST: ElevationAdapter("west"),
        SheetType.SECTION_A: SectionAdapter("A"),
        SheetType.SECTION_B: SectionAdapter("B"),
        SheetType.DETAILS: DetailAdapter(),
        SheetType.SCHEDULES: ScheduleAdapter(),
        # Preset-based multi-viewport sheets
        SheetType.PRESET_FLOOR_PLAN: PresetAdapter("floor_plan"),
        SheetType.PRESET_ELEVATIONS: PresetAdapter("elevations"),
        SheetType.PRESET_SECTIONS: PresetAdapter("sections"),
        SheetType.PRESET_DETAILS: PresetAdapter("details"),
        SheetType.PRESET_SCHEDULES: PresetAdapter("schedules"),
    }

    return adapters.get(sheet_type)
