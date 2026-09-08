"""
Viewport system for multi-drawing architectural sheets.

A viewport is a rectangular area on a sheet that displays a drawing
at a specific scale. Multiple viewports can be placed on a single sheet,
each with independent scale, position, and optional interactive zoom.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple, Callable
from xml.etree.ElementTree import Element, SubElement

from .svg_builder import SVGBuilder
from .lod_layers import LODLevel


@dataclass
class ViewportBounds:
    """Bounds of content to display in viewport (in model units, mm)."""
    min_x: float
    min_z: float
    max_x: float
    max_z: float

    @property
    def width(self) -> float:
        return self.max_x - self.min_x

    @property
    def height(self) -> float:
        return self.max_z - self.min_z

    @property
    def center(self) -> Tuple[float, float]:
        return (self.min_x + self.width / 2, self.min_z + self.height / 2)


@dataclass
class Viewport:
    """
    A viewport displaying a portion of a drawing on a sheet.

    Attributes:
        id: Unique viewport identifier
        x, y: Position on sheet (in points, from top-left)
        width, height: Size on sheet (in points)
        scale: Drawing scale (e.g., "1:50", "1:100")
        title: Optional viewport title
        content_bounds: Bounds of model content to display
        show_frame: Whether to draw viewport border
        lod_levels: Which LOD levels to show in this viewport
    """
    id: str
    x: float
    y: float
    width: float
    height: float
    scale: str = "1:50"
    title: Optional[str] = None
    content_bounds: Optional[ViewportBounds] = None
    show_frame: bool = True
    lod_levels: List[LODLevel] = field(default_factory=lambda: list(LODLevel))
    _scale_factor: float = field(init=False, default=0.0)

    def __post_init__(self):
        """Calculate scale factor from scale string."""
        from .sheet_sizes import get_scale_factor
        self._scale_factor = get_scale_factor(self.scale)

    @property
    def scale_factor(self) -> float:
        """Scale factor (mm to points)."""
        return self._scale_factor

    def get_transform(self) -> Tuple[float, float, float]:
        """
        Calculate transform to fit content in viewport.

        Returns:
            (scale, offset_x, offset_y) to center content in viewport
        """
        if not self.content_bounds:
            return (self._scale_factor, self.x, self.y)

        # Content size in points at current scale
        content_w = self.content_bounds.width * self._scale_factor
        content_h = self.content_bounds.height * self._scale_factor

        # Calculate offset to center content
        offset_x = self.x + (self.width - content_w) / 2 - self.content_bounds.min_x * self._scale_factor
        offset_y = self.y + (self.height - content_h) / 2 - self.content_bounds.min_z * self._scale_factor

        return (self._scale_factor, offset_x, offset_y)

    def auto_scale(self, padding: float = 20) -> None:
        """
        Automatically adjust scale to fit content in viewport.

        Args:
            padding: Padding inside viewport (in points)
        """
        if not self.content_bounds:
            return

        available_w = self.width - 2 * padding
        available_h = self.height - 2 * padding

        # Calculate scale needed to fit
        scale_x = available_w / self.content_bounds.width if self.content_bounds.width > 0 else 1
        scale_y = available_h / self.content_bounds.height if self.content_bounds.height > 0 else 1

        # Use smaller scale to fit both dimensions
        self._scale_factor = min(scale_x, scale_y)

        # Round to nearest standard scale if close
        standard_scales = [1/25, 1/50, 1/100, 1/200, 1/500]
        for std in standard_scales:
            if abs(self._scale_factor - std) / std < 0.1:
                self._scale_factor = std
                break


class ViewportRenderer:
    """
    Renders viewports on a sheet.

    Handles clipping, framing, and coordinate transforms for each viewport.
    """

    def __init__(self, builder: SVGBuilder):
        self.builder = builder
        self._clip_counter = 0

    def render_viewport(
        self,
        viewport: Viewport,
        render_callback: Callable[[SVGBuilder, Element, float, float, float], None],
    ) -> Element:
        """
        Render a viewport with its content.

        Args:
            viewport: Viewport definition
            render_callback: Function to render content, receives:
                (builder, parent_group, scale, offset_x, offset_y)

        Returns:
            Viewport group element
        """
        # Create clip path for viewport
        clip_id = f"clip-{viewport.id}"
        self._create_clip_path(clip_id, viewport.x, viewport.y, viewport.width, viewport.height)

        # Create viewport group
        vp_group = self.builder.group(
            id=viewport.id,
            class_="viewport",
            data={
                "viewport-id": viewport.id,
                "scale": viewport.scale,
            },
        )

        # Optional frame
        if viewport.show_frame:
            self._render_frame(vp_group, viewport)

        # Content group with clipping
        content_group = SubElement(vp_group, "g")
        content_group.set("clip-path", f"url(#{clip_id})")
        content_group.set("class", "viewport-content")

        # Get transform and render content
        scale, offset_x, offset_y = viewport.get_transform()
        render_callback(self.builder, content_group, scale, offset_x, offset_y)

        # Optional title
        if viewport.title:
            self._render_title(vp_group, viewport)

        return vp_group

    def _create_clip_path(self, clip_id: str, x: float, y: float, w: float, h: float) -> None:
        """Create a clip path in defs."""
        clip_path = SubElement(self.builder.defs, "clipPath")
        clip_path.set("id", clip_id)

        rect = SubElement(clip_path, "rect")
        rect.set("x", str(x))
        rect.set("y", str(y))
        rect.set("width", str(w))
        rect.set("height", str(h))

    def _render_frame(self, parent: Element, viewport: Viewport) -> None:
        """Render viewport border frame."""
        self.builder.rect(
            x=viewport.x,
            y=viewport.y,
            width=viewport.width,
            height=viewport.height,
            parent=parent,
            stroke="#000000",
            stroke_width=0.5,
            fill="none",
        )

    def _render_title(self, parent: Element, viewport: Viewport) -> None:
        """Render viewport title below frame."""
        self.builder.text(
            content=viewport.title,
            x=viewport.x + viewport.width / 2,
            y=viewport.y + viewport.height + 15,
            parent=parent,
            font_size=10,
            font_weight="bold",
            fill="#000000",
            text_anchor="middle",
        )

        # Scale indicator
        self.builder.text(
            content=f"Scale {viewport.scale}",
            x=viewport.x + viewport.width / 2,
            y=viewport.y + viewport.height + 27,
            parent=parent,
            font_size=8,
            fill="#666666",
            text_anchor="middle",
        )


def create_standard_layout(
    sheet_width: float,
    sheet_height: float,
    margin: float = 36,
    title_block_height: float = 72,
) -> Dict[str, Viewport]:
    """
    Create standard viewport layouts for common sheet arrangements.

    Returns dict of named viewports for different layout types.
    """
    drawable_width = sheet_width - 2 * margin
    drawable_height = sheet_height - 2 * margin - title_block_height

    layouts = {
        # Single large viewport
        "single": [
            Viewport(
                id="vp-main",
                x=margin,
                y=margin,
                width=drawable_width,
                height=drawable_height,
                title="Floor Plan",
            ),
        ],

        # Two viewports side by side
        "split_horizontal": [
            Viewport(
                id="vp-left",
                x=margin,
                y=margin,
                width=drawable_width / 2 - 10,
                height=drawable_height,
                title="Floor Plan",
            ),
            Viewport(
                id="vp-right",
                x=margin + drawable_width / 2 + 10,
                y=margin,
                width=drawable_width / 2 - 10,
                height=drawable_height,
                title="Elevation",
            ),
        ],

        # Large main + smaller details
        "main_with_details": [
            Viewport(
                id="vp-main",
                x=margin,
                y=margin,
                width=drawable_width * 0.65,
                height=drawable_height,
                title="Floor Plan",
            ),
            Viewport(
                id="vp-detail-1",
                x=margin + drawable_width * 0.7,
                y=margin,
                width=drawable_width * 0.3,
                height=drawable_height / 2 - 10,
                title="Detail A",
                scale="1:25",
            ),
            Viewport(
                id="vp-detail-2",
                x=margin + drawable_width * 0.7,
                y=margin + drawable_height / 2 + 10,
                width=drawable_width * 0.3,
                height=drawable_height / 2 - 10,
                title="Detail B",
                scale="1:25",
            ),
        ],

        # Four equal quadrants
        "quad": [
            Viewport(
                id="vp-tl",
                x=margin,
                y=margin,
                width=drawable_width / 2 - 10,
                height=drawable_height / 2 - 10,
                title="Floor Plan",
            ),
            Viewport(
                id="vp-tr",
                x=margin + drawable_width / 2 + 10,
                y=margin,
                width=drawable_width / 2 - 10,
                height=drawable_height / 2 - 10,
                title="North Elevation",
            ),
            Viewport(
                id="vp-bl",
                x=margin,
                y=margin + drawable_height / 2 + 10,
                width=drawable_width / 2 - 10,
                height=drawable_height / 2 - 10,
                title="East Elevation",
            ),
            Viewport(
                id="vp-br",
                x=margin + drawable_width / 2 + 10,
                y=margin + drawable_height / 2 + 10,
                width=drawable_width / 2 - 10,
                height=drawable_height / 2 - 10,
                title="Section A-A",
            ),
        ],
    }

    return layouts
