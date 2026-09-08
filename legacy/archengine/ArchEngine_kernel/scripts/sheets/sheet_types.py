"""
Sheet type presets and drawing content configuration.

Provides standard architectural sheet layouts that users can customize.
Each sheet type defines default viewports with appropriate drawing content.
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import List, Dict, Any, Optional, Callable
from .viewport import Viewport, ViewportBounds


class DrawingType(Enum):
    """Types of architectural drawings that can be placed in viewports."""
    FLOOR_PLAN = auto()      # Plan view of a floor level
    ROOF_PLAN = auto()       # Plan view of roof
    SITE_PLAN = auto()       # Site/plot plan
    REFLECTED_CEILING = auto()  # Reflected ceiling plan

    ELEVATION_NORTH = auto()  # Building elevations
    ELEVATION_SOUTH = auto()
    ELEVATION_EAST = auto()
    ELEVATION_WEST = auto()

    SECTION = auto()         # Building section
    WALL_SECTION = auto()    # Wall section detail

    DETAIL = auto()          # Construction detail

    DOOR_SCHEDULE = auto()   # Schedules
    WINDOW_SCHEDULE = auto()
    ROOM_SCHEDULE = auto()
    FINISH_SCHEDULE = auto()

    KEY_PLAN = auto()        # Small reference plan
    LEGEND = auto()          # Symbol legend
    NOTES = auto()           # General notes

    CUSTOM = auto()          # User-defined content


class SheetType(Enum):
    """Standard architectural sheet types."""
    FLOOR_PLAN = "A-1xx"       # Floor plans
    ELEVATIONS = "A-2xx"       # Elevations
    SECTIONS = "A-3xx"         # Sections
    DETAILS = "A-5xx"          # Details
    SCHEDULES = "A-6xx"        # Schedules
    CUSTOM = "X-xxx"           # Custom layout


@dataclass
class ViewportContent:
    """
    Configuration for what content appears in a viewport.

    Attributes:
        drawing_type: Type of drawing to display
        floor_level: Which floor (for plans) - 0=ground, 1=first, -1=basement
        section_id: Section identifier (for sections)
        detail_id: Detail identifier (for details)
        custom_renderer: Optional custom rendering function
        data_filter: Optional filter for which elements to show
    """
    drawing_type: DrawingType
    floor_level: int = 0
    section_id: Optional[str] = None
    detail_id: Optional[str] = None
    custom_renderer: Optional[Callable] = None
    data_filter: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        # Default filters based on drawing type
        if self.data_filter is None:
            self.data_filter = {}


@dataclass
class ViewportConfig:
    """
    Extended viewport configuration with content assignment.

    Wraps a Viewport with content configuration, allowing any
    drawing type to be assigned to any viewport position.
    """
    viewport: Viewport
    content: ViewportContent

    @classmethod
    def create(
        cls,
        id: str,
        x: float,
        y: float,
        width: float,
        height: float,
        drawing_type: DrawingType,
        title: Optional[str] = None,
        scale: str = "1:50",
        **content_kwargs
    ) -> "ViewportConfig":
        """Convenience method to create viewport with content."""
        viewport = Viewport(
            id=id,
            x=x,
            y=y,
            width=width,
            height=height,
            scale=scale,
            title=title or drawing_type.name.replace("_", " ").title(),
        )
        content = ViewportContent(drawing_type=drawing_type, **content_kwargs)
        return cls(viewport=viewport, content=content)


@dataclass
class SheetPreset:
    """
    A preset sheet configuration with default viewports.

    Users can:
    - Use as-is for standard layouts
    - Modify viewport positions/sizes
    - Change content assignments
    - Add/remove viewports
    """
    name: str
    sheet_type: SheetType
    description: str
    viewports: List[ViewportConfig] = field(default_factory=list)

    def get_viewport(self, viewport_id: str) -> Optional[ViewportConfig]:
        """Get viewport config by ID."""
        for vc in self.viewports:
            if vc.viewport.id == viewport_id:
                return vc
        return None

    def set_content(self, viewport_id: str, content: ViewportContent) -> bool:
        """Change content assignment for a viewport."""
        vc = self.get_viewport(viewport_id)
        if vc:
            vc.content = content
            return True
        return False

    def add_viewport(self, config: ViewportConfig) -> None:
        """Add a new viewport to the sheet."""
        self.viewports.append(config)

    def remove_viewport(self, viewport_id: str) -> bool:
        """Remove a viewport by ID."""
        for i, vc in enumerate(self.viewports):
            if vc.viewport.id == viewport_id:
                self.viewports.pop(i)
                return True
        return False

    def clone(self) -> "SheetPreset":
        """Create a copy of this preset for customization."""
        import copy
        return copy.deepcopy(self)


def create_floor_plan_preset(
    sheet_width: float,
    sheet_height: float,
    margin: float = 36,
    title_block_height: float = 72,
) -> SheetPreset:
    """
    Create a floor plan sheet preset.

    Layout: Large floor plan with key plan and legend.
    """
    drawable_w = sheet_width - 2 * margin
    drawable_h = sheet_height - 2 * margin - title_block_height

    # Main floor plan takes most of the space
    main_w = drawable_w * 0.75
    main_h = drawable_h

    # Side panel for key plan and legend
    side_w = drawable_w * 0.22
    side_x = margin + main_w + drawable_w * 0.03

    viewports = [
        ViewportConfig.create(
            id="vp-floor-plan",
            x=margin,
            y=margin,
            width=main_w,
            height=main_h,
            drawing_type=DrawingType.FLOOR_PLAN,
            title="Floor Plan",
            scale="1:50",
        ),
        ViewportConfig.create(
            id="vp-key-plan",
            x=side_x,
            y=margin,
            width=side_w,
            height=side_w,  # Square
            drawing_type=DrawingType.KEY_PLAN,
            title="Key Plan",
            scale="1:200",
        ),
        ViewportConfig.create(
            id="vp-legend",
            x=side_x,
            y=margin + side_w + 20,
            width=side_w,
            height=drawable_h - side_w - 20,
            drawing_type=DrawingType.LEGEND,
            title="Legend",
            scale="1:1",
        ),
    ]

    return SheetPreset(
        name="Floor Plan Sheet",
        sheet_type=SheetType.FLOOR_PLAN,
        description="Standard floor plan with key plan and legend",
        viewports=viewports,
    )


def create_elevations_preset(
    sheet_width: float,
    sheet_height: float,
    margin: float = 36,
    title_block_height: float = 72,
) -> SheetPreset:
    """
    Create an elevations sheet preset.

    Layout: Four elevations in 2x2 grid.
    """
    drawable_w = sheet_width - 2 * margin
    drawable_h = sheet_height - 2 * margin - title_block_height

    vp_w = (drawable_w - 20) / 2
    vp_h = (drawable_h - 20) / 2

    viewports = [
        ViewportConfig.create(
            id="vp-elev-north",
            x=margin,
            y=margin,
            width=vp_w,
            height=vp_h,
            drawing_type=DrawingType.ELEVATION_NORTH,
            title="North Elevation",
            scale="1:100",
        ),
        ViewportConfig.create(
            id="vp-elev-south",
            x=margin + vp_w + 20,
            y=margin,
            width=vp_w,
            height=vp_h,
            drawing_type=DrawingType.ELEVATION_SOUTH,
            title="South Elevation",
            scale="1:100",
        ),
        ViewportConfig.create(
            id="vp-elev-east",
            x=margin,
            y=margin + vp_h + 20,
            width=vp_w,
            height=vp_h,
            drawing_type=DrawingType.ELEVATION_EAST,
            title="East Elevation",
            scale="1:100",
        ),
        ViewportConfig.create(
            id="vp-elev-west",
            x=margin + vp_w + 20,
            y=margin + vp_h + 20,
            width=vp_w,
            height=vp_h,
            drawing_type=DrawingType.ELEVATION_WEST,
            title="West Elevation",
            scale="1:100",
        ),
    ]

    return SheetPreset(
        name="Elevations Sheet",
        sheet_type=SheetType.ELEVATIONS,
        description="Four building elevations",
        viewports=viewports,
    )


def create_sections_preset(
    sheet_width: float,
    sheet_height: float,
    margin: float = 36,
    title_block_height: float = 72,
) -> SheetPreset:
    """
    Create a sections sheet preset.

    Layout: Two sections stacked vertically.
    """
    drawable_w = sheet_width - 2 * margin
    drawable_h = sheet_height - 2 * margin - title_block_height

    vp_h = (drawable_h - 20) / 2

    viewports = [
        ViewportConfig.create(
            id="vp-section-a",
            x=margin,
            y=margin,
            width=drawable_w,
            height=vp_h,
            drawing_type=DrawingType.SECTION,
            title="Section A-A",
            scale="1:50",
            section_id="A",
        ),
        ViewportConfig.create(
            id="vp-section-b",
            x=margin,
            y=margin + vp_h + 20,
            width=drawable_w,
            height=vp_h,
            drawing_type=DrawingType.SECTION,
            title="Section B-B",
            scale="1:50",
            section_id="B",
        ),
    ]

    return SheetPreset(
        name="Sections Sheet",
        sheet_type=SheetType.SECTIONS,
        description="Building sections",
        viewports=viewports,
    )


def create_details_preset(
    sheet_width: float,
    sheet_height: float,
    margin: float = 36,
    title_block_height: float = 72,
    grid: tuple = (3, 2),  # columns, rows
) -> SheetPreset:
    """
    Create a details sheet preset.

    Layout: Grid of detail viewports.
    """
    drawable_w = sheet_width - 2 * margin
    drawable_h = sheet_height - 2 * margin - title_block_height

    cols, rows = grid
    gap = 15
    vp_w = (drawable_w - gap * (cols - 1)) / cols
    vp_h = (drawable_h - gap * (rows - 1)) / rows

    viewports = []
    detail_num = 1

    for row in range(rows):
        for col in range(cols):
            viewports.append(
                ViewportConfig.create(
                    id=f"vp-detail-{detail_num}",
                    x=margin + col * (vp_w + gap),
                    y=margin + row * (vp_h + gap),
                    width=vp_w,
                    height=vp_h,
                    drawing_type=DrawingType.DETAIL,
                    title=f"Detail {detail_num}",
                    scale="1:10",
                    detail_id=str(detail_num),
                )
            )
            detail_num += 1

    return SheetPreset(
        name="Details Sheet",
        sheet_type=SheetType.DETAILS,
        description=f"{cols}x{rows} detail grid",
        viewports=viewports,
    )


def create_schedules_preset(
    sheet_width: float,
    sheet_height: float,
    margin: float = 36,
    title_block_height: float = 72,
) -> SheetPreset:
    """
    Create a schedules sheet preset.

    Layout: Door, window, and room schedules.
    """
    drawable_w = sheet_width - 2 * margin
    drawable_h = sheet_height - 2 * margin - title_block_height

    # Three schedules stacked
    vp_h = (drawable_h - 40) / 3

    viewports = [
        ViewportConfig.create(
            id="vp-door-schedule",
            x=margin,
            y=margin,
            width=drawable_w,
            height=vp_h,
            drawing_type=DrawingType.DOOR_SCHEDULE,
            title="Door Schedule",
            scale="1:1",
        ),
        ViewportConfig.create(
            id="vp-window-schedule",
            x=margin,
            y=margin + vp_h + 20,
            width=drawable_w,
            height=vp_h,
            drawing_type=DrawingType.WINDOW_SCHEDULE,
            title="Window Schedule",
            scale="1:1",
        ),
        ViewportConfig.create(
            id="vp-room-schedule",
            x=margin,
            y=margin + 2 * (vp_h + 20),
            width=drawable_w,
            height=vp_h,
            drawing_type=DrawingType.ROOM_SCHEDULE,
            title="Room Schedule",
            scale="1:1",
        ),
    ]

    return SheetPreset(
        name="Schedules Sheet",
        sheet_type=SheetType.SCHEDULES,
        description="Door, window, and room schedules",
        viewports=viewports,
    )


def get_preset(
    preset_name: str,
    sheet_width: float,
    sheet_height: float,
) -> SheetPreset:
    """
    Get a sheet preset by name.

    Args:
        preset_name: One of "floor_plan", "elevations", "sections",
                     "details", "schedules"
        sheet_width: Sheet width in points
        sheet_height: Sheet height in points

    Returns:
        SheetPreset configured for the given sheet size
    """
    presets = {
        "floor_plan": create_floor_plan_preset,
        "elevations": create_elevations_preset,
        "sections": create_sections_preset,
        "details": create_details_preset,
        "schedules": create_schedules_preset,
    }

    if preset_name not in presets:
        raise ValueError(f"Unknown preset: {preset_name}. "
                        f"Available: {list(presets.keys())}")

    return presets[preset_name](sheet_width, sheet_height)


def list_presets() -> List[str]:
    """List available preset names."""
    return ["floor_plan", "elevations", "sections", "details", "schedules"]
