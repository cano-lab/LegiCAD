"""
InteractiveSheet - Main class for generating architectural SVG sheets.

Generates complete architectural floor plan sheets with:
- Standard ARCH sheet sizes
- LOD (Level of Detail) layers
- Title blocks
- Interactive data attributes
"""

import json
from pathlib import Path
from typing import Dict, Any, Optional, Union, List, Callable
from datetime import datetime
from xml.etree.ElementTree import Element, SubElement

from .sheet_sizes import get_sheet_size, get_scale_factor, SheetSize, TITLE_BLOCK
from .svg_builder import SVGBuilder
from .lod_layers import LODLevel, get_css_for_lod_visibility
from .elements.walls import render_walls, render_wall_outline, get_wall_bounds
from .elements.doors import render_doors, render_door_symbol
from .elements.windows import render_windows, render_window_symbol
from .elements.rooms import render_rooms
from .elements.dimensions import (
    render_dimensions,
    render_overall_dimensions,
    render_coordinate_markers,
    render_grid_system,
    render_centerline_chain,
    render_opening_dimensions,
)
from .elements.dimensions_enhanced import (
    render_complete_dimensions,
    render_opening_dimensions_metric,
)
from .viewport import Viewport, ViewportBounds, ViewportRenderer, create_standard_layout
from .sheet_types import (
    DrawingType,
    SheetType,
    ViewportContent,
    ViewportConfig,
    SheetPreset,
    get_preset,
)
from .generators.elevation_renderer import render_elevation
from .generators.section_renderer import render_section
from .generators.schedule_renderer import render_schedule
from .generators.detail_renderer import render_detail


class InteractiveSheet:
    """
    Generates architectural drawing sheets as SVG.

    Supports single or multi-viewport layouts:
        - Single viewport (default): One drawing fills the sheet
        - Multi-viewport: Multiple drawings with independent scales
        - Sheet presets: Pre-configured layouts with content assignments

    Usage:
        # Single viewport
        sheet = InteractiveSheet(
            json_path="path/to/building.json",
            sheet_size="ARCH_D",
            scale="1:50"
        )

        # Multi-viewport with preset layout
        sheet = InteractiveSheet(
            json_path="path/to/building.json",
            sheet_size="ARCH_D",
            layout="main_with_details"
        )

        # Sheet preset with content assignments
        from sheets import get_preset, DrawingType, ViewportContent
        preset = get_preset("elevations", 1296, 864)  # ARCH_D size
        preset.set_content("vp-elev-north", ViewportContent(DrawingType.SECTION))
        sheet = InteractiveSheet(
            json_path="path/to/building.json",
            sheet_size="ARCH_D",
            preset=preset
        )

        svg_content = sheet.generate()
    """

    def __init__(
        self,
        json_path: Optional[Union[str, Path]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        sheet_size: str = "ARCH_D",
        scale: str = "1:50",
        title: str = "Floor Plan",
        project_name: str = "Project",
        sheet_number: str = "A-001",
        layout: Optional[str] = None,
        viewports: Optional[List[Viewport]] = None,
        preset: Optional[SheetPreset] = None,
    ):
        """
        Initialize the sheet generator.

        Args:
            json_path: Path to JSON building data file
            json_data: Building data dict (alternative to json_path)
            sheet_size: Sheet size name (ARCH_A through ARCH_E)
            scale: Drawing scale (e.g., "1:50", "1:100")
            title: Drawing title
            project_name: Project name for title block
            sheet_number: Sheet number for title block
            layout: Preset layout name ("single", "split_horizontal",
                    "main_with_details", "quad") - overrides scale
            viewports: Custom viewport list - overrides layout and scale
            preset: SheetPreset with ViewportConfig content assignments -
                    overrides layout and viewports
        """
        self.sheet_size: SheetSize = get_sheet_size(sheet_size)
        self.scale_factor = get_scale_factor(scale)
        self.scale_text = scale
        self.title = title
        self.project_name = project_name
        self.sheet_number = sheet_number
        self.layout_name = layout
        self.custom_viewports = viewports
        self.preset = preset

        # Store viewport configs for content-aware rendering
        self.viewport_configs: Dict[str, ViewportConfig] = {}

        # Load building data
        if json_path:
            self.data = self._load_json(json_path)
        elif json_data:
            self.data = json_data
        else:
            self.data = {}

        # Extract building elements
        self.walls = self.data.get("walls_batch", [])
        self.doors = self.data.get("doors", [])
        self.windows = self.data.get("windows", [])
        self.rooms = self.data.get("rooms", [])

        # Setup viewports
        self._setup_viewports()

    def _load_json(self, path: Union[str, Path]) -> Dict[str, Any]:
        """Load building data from JSON file."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Building data not found: {path}")

        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _setup_viewports(self) -> None:
        """Setup viewports based on preset, layout, or custom viewports."""
        if self.preset:
            # Use preset with content assignments
            self.viewports = [vc.viewport for vc in self.preset.viewports]
            self.viewport_configs = {
                vc.viewport.id: vc for vc in self.preset.viewports
            }
        elif self.custom_viewports:
            self.viewports = self.custom_viewports
        elif self.layout_name:
            layouts = create_standard_layout(
                self.sheet_size.width_pt,
                self.sheet_size.height_pt,
            )
            if self.layout_name not in layouts:
                raise ValueError(f"Unknown layout: {self.layout_name}. "
                               f"Available: {list(layouts.keys())}")
            self.viewports = layouts[self.layout_name]
        else:
            # Single viewport mode (legacy behavior)
            self.viewports = None

        # Set content bounds for viewports if we have walls
        if self.viewports and self.walls:
            min_x, min_z, max_x, max_z = get_wall_bounds(self.walls)
            bounds = ViewportBounds(min_x, min_z, max_x, max_z)
            for vp in self.viewports:
                if vp.content_bounds is None:
                    vp.content_bounds = bounds
                    vp.auto_scale(padding=40)

    def _calculate_drawing_area(self) -> tuple:
        """
        Calculate the available drawing area on the sheet.

        Returns:
            (x, y, width, height, margin) in points
        """
        margin = TITLE_BLOCK["margin"]
        title_height = TITLE_BLOCK["height"]

        x = margin
        y = margin
        width = self.sheet_size.width_pt - 2 * margin
        height = self.sheet_size.height_pt - 2 * margin - title_height

        return (x, y, width, height, margin)

    def _calculate_transform(self) -> tuple:
        """
        Calculate the transform to fit building in drawing area.

        Returns:
            (scale, offset_x, offset_y, drawing_height)
            - offset_x, offset_y are the translation to apply to the LOD group
            - drawing_height is passed to renderers for Y-flip calculations
        """
        margin = TITLE_BLOCK["margin"]
        title_height = TITLE_BLOCK["height"]
        padding = 50  # Points of padding inside drawing area

        # Drawing area bounds (above title block)
        draw_left = margin + padding
        draw_top = margin + padding
        draw_right = self.sheet_size.width_pt - margin - padding
        draw_bottom = self.sheet_size.height_pt - margin - title_height - padding

        available_width = draw_right - draw_left
        available_height = draw_bottom - draw_top

        # Get building bounds
        min_x, min_z, max_x, max_z = get_wall_bounds(self.walls)
        building_width = max_x - min_x
        building_depth = max_z - min_z

        if building_width == 0 or building_depth == 0:
            return (self.scale_factor, draw_left, draw_top, available_height)

        # Scale from mm to points, then apply architectural scale
        mm_to_pt = 72 / 25.4  # 72 points per inch, 25.4 mm per inch
        base_scale = mm_to_pt * self.scale_factor

        # Check if building fits at requested scale
        scaled_width = building_width * base_scale
        scaled_height = building_depth * base_scale

        # Adjust scale if building doesn't fit
        if scaled_width > available_width or scaled_height > available_height:
            fit_scale_x = available_width / building_width
            fit_scale_y = available_height / building_depth
            final_scale = min(fit_scale_x, fit_scale_y)
        else:
            final_scale = base_scale

        # Calculate centered position
        final_width = building_width * final_scale
        final_height = building_depth * final_scale

        # Center horizontally, offset to move building origin to center
        center_x = draw_left + (available_width - final_width) / 2
        offset_x = center_x - min_x * final_scale

        # Center vertically (note: Y flipping happens in renderers)
        center_y = draw_top + (available_height - final_height) / 2
        offset_y = center_y - min_z * final_scale

        # The renderers will flip Y using: height - y
        # We pass the height they should use for flipping
        flip_height = draw_top + available_height

        return (final_scale, offset_x, offset_y, flip_height)

    def _render_sheet_border(self, builder: SVGBuilder) -> None:
        """Render sheet border and margins."""
        margin = TITLE_BLOCK["margin"]
        border_width = TITLE_BLOCK["border_width"]

        # Outer border
        builder.rect(
            x=margin,
            y=margin,
            width=self.sheet_size.width_pt - 2 * margin,
            height=self.sheet_size.height_pt - 2 * margin,
            id="sheet-border",
            stroke="#000000",
            stroke_width=border_width,
            fill="none",
        )

    def _render_title_block(self, builder: SVGBuilder) -> None:
        """Render title block at bottom of sheet."""
        margin = TITLE_BLOCK["margin"]
        title_height = TITLE_BLOCK["height"]
        border_width = TITLE_BLOCK["border_width"]

        # Title block position
        tb_x = margin
        tb_y = self.sheet_size.height_pt - margin - title_height
        tb_width = self.sheet_size.width_pt - 2 * margin
        tb_height = title_height

        g = builder.group(id="title-block")

        # Title block border
        builder.rect(
            x=tb_x,
            y=tb_y,
            width=tb_width,
            height=tb_height,
            parent=g,
            stroke="#000000",
            stroke_width=border_width,
            fill="#ffffff",
        )

        # Divider lines
        section_width = tb_width / 4

        for i in range(1, 4):
            builder.line(
                tb_x + i * section_width, tb_y,
                tb_x + i * section_width, tb_y + tb_height,
                parent=g,
                stroke="#000000",
                stroke_width=0.5,
            )

        # Text content
        text_y = tb_y + tb_height / 2

        # Project name
        builder.text(
            content=self.project_name,
            x=tb_x + section_width / 2,
            y=text_y - 8,
            parent=g,
            font_size=12,
            font_weight="bold",
            text_anchor="middle",
            dominant_baseline="middle",
        )
        builder.text(
            content="PROJECT",
            x=tb_x + section_width / 2,
            y=text_y + 10,
            parent=g,
            font_size=8,
            fill="#666666",
            text_anchor="middle",
            dominant_baseline="middle",
        )

        # Title
        builder.text(
            content=self.title,
            x=tb_x + section_width * 1.5,
            y=text_y - 8,
            parent=g,
            font_size=12,
            font_weight="bold",
            text_anchor="middle",
            dominant_baseline="middle",
        )
        builder.text(
            content="TITLE",
            x=tb_x + section_width * 1.5,
            y=text_y + 10,
            parent=g,
            font_size=8,
            fill="#666666",
            text_anchor="middle",
            dominant_baseline="middle",
        )

        # Scale
        builder.text(
            content=self.scale_text,
            x=tb_x + section_width * 2.5,
            y=text_y - 8,
            parent=g,
            font_size=12,
            font_weight="bold",
            text_anchor="middle",
            dominant_baseline="middle",
        )
        builder.text(
            content="SCALE",
            x=tb_x + section_width * 2.5,
            y=text_y + 10,
            parent=g,
            font_size=8,
            fill="#666666",
            text_anchor="middle",
            dominant_baseline="middle",
        )

        # Sheet number and date
        builder.text(
            content=self.sheet_number,
            x=tb_x + section_width * 3.5,
            y=text_y - 8,
            parent=g,
            font_size=14,
            font_weight="bold",
            text_anchor="middle",
            dominant_baseline="middle",
        )
        builder.text(
            content=datetime.now().strftime("%Y-%m-%d"),
            x=tb_x + section_width * 3.5,
            y=text_y + 10,
            parent=g,
            font_size=8,
            fill="#666666",
            text_anchor="middle",
            dominant_baseline="middle",
        )

    def _render_lod_layer(
        self,
        builder: SVGBuilder,
        level: LODLevel,
        scale: float,
        offset_x: float,
        offset_y: float,
        height: float,
        parent: Optional[Element] = None,
    ) -> None:
        """
        Render a single LOD layer.

        Args:
            builder: SVG builder
            level: LOD level to render
            scale: Drawing scale
            offset_x, offset_y: Transform offsets
            height: SVG height for Y transform
            parent: Optional parent element (for pan/zoom container)
        """
        # Create layer group with transform
        g = builder.group(
            parent=parent,
            id=f"lod-{level.value}",
            class_=f"lod-layer lod-{level.value}",
            transform=f"translate({offset_x}, {offset_y})",
            data={"lod": str(level.value)},
        )

        if level == LODLevel.OVERVIEW:
            # LOD 1: Room labels and building outline
            render_rooms(
                builder, self.rooms, g,
                scale=scale,
                transform_y=False,
                height=0,
                include_fills=True,
            )
            render_wall_outline(
                builder, self.walls, g,
                scale=scale,
                transform_y=False,
                height=0,
            )

        elif level == LODLevel.STANDARD:
            # LOD 2: Walls, doors, windows
            render_walls(
                builder, self.walls, g,
                scale=scale,
                transform_y=False,
                height=0,
            )
            render_doors(
                builder, self.doors, self.walls, g,
                scale=scale,
                transform_y=False,
                height=0,
            )
            render_windows(
                builder, self.windows, self.walls, g,
                scale=scale,
                transform_y=False,
                height=0,
            )

        elif level == LODLevel.DETAILED:
            # LOD 3: Complete dimension set on all 4 sides (metric)
            render_complete_dimensions(
                builder, self.walls, g,
                scale=scale,
                transform_y=False,
                height=0,
            )
            # Opening dimensions (doors/windows)
            render_opening_dimensions_metric(
                builder, self.doors, self.windows, self.walls, g,
                scale=scale,
                transform_y=False,
                height=0,
            )

        elif level == LODLevel.CONSTRUCTION:
            # LOD 4: VR/Field - coordinate markers at all corners
            # Per DIMENSIONING.md: "VR/AR Layout - Raw coordinates relative to site datum"
            render_coordinate_markers(
                builder, self.walls, g,
                scale=scale,
                transform_y=False,
                height=0,
            )

    def _get_content_renderer(
        self,
        drawing_type: DrawingType,
        content: ViewportContent,
    ) -> Callable[[SVGBuilder, Element, float, float, float], None]:
        """
        Get the appropriate content renderer for a drawing type.

        Args:
            drawing_type: Type of drawing to render
            content: Content configuration with filters/options

        Returns:
            Renderer callback function
        """
        # Floor plan renderer - full LOD layers
        if drawing_type == DrawingType.FLOOR_PLAN:
            def render_floor_plan(b: SVGBuilder, parent: Element, scale: float, ox: float, oy: float):
                for level in LODLevel:
                    self._render_lod_layer(b, level, scale, ox, oy, 0, parent=parent)
            return render_floor_plan

        # Roof plan - show roof outline (placeholder)
        if drawing_type == DrawingType.ROOF_PLAN:
            def render_roof_plan(b: SVGBuilder, parent: Element, scale: float, ox: float, oy: float):
                self._render_placeholder(b, parent, "Roof Plan", scale, ox, oy)
            return render_roof_plan

        # Key plan - simplified overview
        if drawing_type == DrawingType.KEY_PLAN:
            def render_key_plan(b: SVGBuilder, parent: Element, scale: float, ox: float, oy: float):
                self._render_lod_layer(b, LODLevel.OVERVIEW, scale, ox, oy, 0, parent=parent)
            return render_key_plan

        # Elevations - use real elevation renderer
        if drawing_type == DrawingType.ELEVATION_NORTH:
            def render_elev_n(b: SVGBuilder, parent: Element, scale: float, ox: float, oy: float):
                render_elevation(b, parent, self.data, "north", scale, ox, oy)
            return render_elev_n

        if drawing_type == DrawingType.ELEVATION_SOUTH:
            def render_elev_s(b: SVGBuilder, parent: Element, scale: float, ox: float, oy: float):
                render_elevation(b, parent, self.data, "south", scale, ox, oy)
            return render_elev_s

        if drawing_type == DrawingType.ELEVATION_EAST:
            def render_elev_e(b: SVGBuilder, parent: Element, scale: float, ox: float, oy: float):
                render_elevation(b, parent, self.data, "east", scale, ox, oy)
            return render_elev_e

        if drawing_type == DrawingType.ELEVATION_WEST:
            def render_elev_w(b: SVGBuilder, parent: Element, scale: float, ox: float, oy: float):
                render_elevation(b, parent, self.data, "west", scale, ox, oy)
            return render_elev_w

        # Sections - use real section renderer
        if drawing_type == DrawingType.SECTION:
            section_id = content.section_id or "A"
            direction = "transverse" if section_id.upper() == "A" else "longitudinal"
            def render_sec(b: SVGBuilder, parent: Element, scale: float, ox: float, oy: float):
                render_section(b, parent, self.data, direction, section_id, scale, ox, oy)
            return render_sec

        # Details - use real detail renderer
        if drawing_type == DrawingType.DETAIL:
            detail_id = content.detail_id or "1"
            def render_det(b: SVGBuilder, parent: Element, scale: float, ox: float, oy: float):
                render_detail(b, parent, self.data, detail_id, scale, ox, oy)
            return render_det

        # Schedules - use real schedule renderer
        if drawing_type == DrawingType.DOOR_SCHEDULE:
            def render_door_sch(b: SVGBuilder, parent: Element, scale: float, ox: float, oy: float):
                render_schedule(b, parent, self.data, "door", scale, ox, oy)
            return render_door_sch

        if drawing_type == DrawingType.WINDOW_SCHEDULE:
            def render_win_sch(b: SVGBuilder, parent: Element, scale: float, ox: float, oy: float):
                render_schedule(b, parent, self.data, "window", scale, ox, oy)
            return render_win_sch

        if drawing_type == DrawingType.ROOM_SCHEDULE:
            def render_room_sch(b: SVGBuilder, parent: Element, scale: float, ox: float, oy: float):
                render_schedule(b, parent, self.data, "room", scale, ox, oy)
            return render_room_sch

        if drawing_type == DrawingType.FINISH_SCHEDULE:
            def render_finish_sch(b: SVGBuilder, parent: Element, scale: float, ox: float, oy: float):
                render_schedule(b, parent, self.data, "room", scale, ox, oy)  # Use room for finish
            return render_finish_sch

        # Legend - placeholder
        if drawing_type == DrawingType.LEGEND:
            def render_legend(b: SVGBuilder, parent: Element, scale: float, ox: float, oy: float):
                self._render_placeholder(b, parent, "Legend", scale, ox, oy)
            return render_legend

        # Notes - placeholder
        if drawing_type == DrawingType.NOTES:
            def render_notes(b: SVGBuilder, parent: Element, scale: float, ox: float, oy: float):
                self._render_placeholder(b, parent, "General Notes", scale, ox, oy)
            return render_notes

        # Custom - use custom renderer if provided
        if drawing_type == DrawingType.CUSTOM and content.custom_renderer:
            return content.custom_renderer

        # Default - floor plan rendering
        def render_default(b: SVGBuilder, parent: Element, scale: float, ox: float, oy: float):
            for level in LODLevel:
                self._render_lod_layer(b, level, scale, ox, oy, 0, parent=parent)
        return render_default

    def _render_placeholder(
        self,
        builder: SVGBuilder,
        parent: Element,
        label: str,
        scale: float,
        ox: float,
        oy: float,
        is_table: bool = False,
    ) -> None:
        """
        Render a placeholder for drawing types not yet implemented.

        Shows a labeled box indicating what content would appear.
        """
        g = SubElement(parent, "g")
        g.set("class", "placeholder-content")

        # Get viewport bounds from parent clip path
        # For now, use a centered approach
        if is_table:
            # Table placeholder - show grid lines
            builder.text(
                content=f"[ {label} ]",
                x=ox + 50,
                y=oy + 30,
                parent=g,
                font_size=14,
                font_weight="bold",
                fill="#999999",
                font_style="italic",
            )
            # Add table header line indication
            builder.line(
                ox + 20, oy + 50,
                ox + 400, oy + 50,
                parent=g,
                stroke="#cccccc",
                stroke_width=1,
            )
        else:
            # Drawing placeholder
            builder.text(
                content=f"[ {label} ]",
                x=ox + 50,
                y=oy + 50,
                parent=g,
                font_size=16,
                font_weight="bold",
                fill="#999999",
                font_style="italic",
            )

    def _render_viewports(self, builder: SVGBuilder) -> None:
        """
        Render all viewports with their content.

        Each viewport is clipped and can have independent scale.
        Content is rendered based on DrawingType when using presets.
        """
        vp_renderer = ViewportRenderer(builder)

        for viewport in self.viewports:
            # Get content configuration if using preset
            config = self.viewport_configs.get(viewport.id)

            if config:
                # Content-aware rendering
                renderer = self._get_content_renderer(
                    config.content.drawing_type,
                    config.content,
                )
                vp_renderer.render_viewport(viewport, renderer)
            else:
                # Default floor plan rendering (legacy mode)
                def render_content(b: SVGBuilder, parent: Element, scale: float, ox: float, oy: float):
                    for level in LODLevel:
                        self._render_lod_layer(b, level, scale, ox, oy, 0, parent=parent)
                vp_renderer.render_viewport(viewport, render_content)

    def _render_lod_controls(self, builder: SVGBuilder) -> None:
        """
        Render LOD toggle controls in the SVG.

        Adds interactive buttons to toggle LOD layer visibility.
        Uses inline onclick handlers for SVG compatibility.
        """
        from xml.etree.ElementTree import SubElement

        margin = TITLE_BLOCK["margin"]
        btn_width = 70
        btn_height = 22
        btn_spacing = 6
        # Position from LEFT side of sheet for reliability
        start_x = margin + 50
        start_y = margin + 8

        # Add JavaScript functions for LOD toggle
        script = SubElement(builder.root, "script")
        script.set("type", "text/javascript")
        script.text = """
// <![CDATA[
function setLOD(level) {
    var svg = document.documentElement;
    svg.classList.remove('show-lod-1', 'show-lod-2', 'show-lod-3', 'show-lod-4');
    if (level > 0) {
        svg.classList.add('show-lod-' + level);
    }
    // Button indices: 0=Overview(1), 1=Standard(2), 2=Detailed(3), 3=VR/Field(4), 4=All(0)
    for (var i = 0; i <= 4; i++) {
        var rectId = 'lod-rect-' + i;
        var rect = document.getElementById(rectId);
        if (rect) {
            var isActive = (level > 0 && i == level - 1) || (level == 0 && i == 4);
            rect.setAttribute('fill', isActive ? '#cce5ff' : '#f0f0f0');
        }
    }
}
// ]]>
        """

        # Control panel group - white background for visibility
        g = builder.group(id="lod-controls", class_="lod-controls")

        # Background panel
        panel_width = (btn_width + btn_spacing) * 5 + 60
        builder.rect(
            x=start_x - 45,
            y=start_y - 4,
            width=panel_width,
            height=btn_height + 8,
            parent=g,
            rx=4,
            stroke="#cccccc",
            stroke_width=1,
            fill="#ffffff",
        )

        # Label
        builder.text(
            content="LOD:",
            x=start_x - 35,
            y=start_y + btn_height / 2,
            parent=g,
            font_size=10,
            font_weight="bold",
            fill="#333333",
            text_anchor="start",
            dominant_baseline="middle",
        )

        # LOD buttons with onclick handlers - added VR/Field option
        lod_names = ["Overview", "Standard", "Detailed", "VR/Field", "All"]
        lod_values = [1, 2, 3, 4, 0]  # 4 = VR/Field with coordinates, 0 = show all

        for i, (name, lod_val) in enumerate(zip(lod_names, lod_values)):
            btn_x = start_x + i * (btn_width + btn_spacing)

            btn_g = SubElement(g, "g")
            btn_g.set("id", f"lod-btn-{i}")
            btn_g.set("class", "lod-btn")
            btn_g.set("onclick", f"setLOD({lod_val})")
            btn_g.set("style", "cursor: pointer;")

            # Button background with unique ID for color updates
            rect = SubElement(btn_g, "rect")
            rect.set("id", f"lod-rect-{i}")
            rect.set("x", str(btn_x))
            rect.set("y", str(start_y))
            rect.set("width", str(btn_width))
            rect.set("height", str(btn_height))
            rect.set("rx", "4")
            rect.set("stroke", "#666666")
            rect.set("stroke-width", "1")
            rect.set("fill", "#cce5ff" if i == 4 else "#f0f0f0")  # "All" selected by default

            # Button label
            builder.text(
                content=name,
                x=btn_x + btn_width / 2,
                y=start_y + btn_height / 2,
                parent=btn_g,
                font_size=9,
                fill="#333333",
                text_anchor="middle",
                dominant_baseline="middle",
            )


    def generate(self) -> str:
        """
        Generate the complete SVG sheet.

        Returns:
            SVG content as string
        """
        # Create SVG builder
        builder = SVGBuilder(
            width=self.sheet_size.width_pt,
            height=self.sheet_size.height_pt,
        )

        # Add CSS for LOD visibility
        builder.add_css(get_css_for_lod_visibility())

        # Add symbol definitions
        render_door_symbol(builder)
        render_window_symbol(builder)

        # Render sheet structure
        self._render_sheet_border(builder)
        self._render_title_block(builder)

        if self.viewports:
            # Multi-viewport mode
            self._render_viewports(builder)
        else:
            # Single viewport mode (legacy)
            scale, offset_x, offset_y, height = self._calculate_transform()
            for level in LODLevel:
                self._render_lod_layer(builder, level, scale, offset_x, offset_y, height)

        # Add LOD toggle controls (outside content group so they don't pan)
        self._render_lod_controls(builder)

        return builder.to_string()

    def save(self, output_path: Union[str, Path]) -> None:
        """
        Generate and save SVG to file.

        Args:
            output_path: Path to save SVG file
        """
        svg_content = self.generate()
        output_path = Path(output_path)

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(svg_content)

        print(f"Saved: {output_path}")
