"""
SVG building utilities for generating architectural drawing elements.

Provides a simple, dependency-free way to build SVG documents
with proper structure, groups, and element attributes.
"""

from typing import List, Dict, Optional, Tuple, Any
from xml.etree.ElementTree import Element, SubElement, tostring
import xml.etree.ElementTree as ET


class SVGBuilder:
    """
    Builder class for constructing SVG documents.

    Usage:
        builder = SVGBuilder(width=2592, height=3456)
        g = builder.group(id="walls", class_="lod-layer")
        builder.path(parent=g, d="M0,0 L100,100", stroke="#000")
        svg_string = builder.to_string()
    """

    def __init__(self, width: float, height: float, viewbox: Optional[str] = None):
        """
        Initialize SVG builder.

        Args:
            width: SVG width in points
            height: SVG height in points
            viewbox: Optional viewBox override (default: "0 0 width height")
        """
        self.width = width
        self.height = height
        self.viewbox = viewbox or f"0 0 {width} {height}"

        # Create root SVG element
        self.root = Element("svg")
        self.root.set("xmlns", "http://www.w3.org/2000/svg")
        self.root.set("xmlns:xlink", "http://www.w3.org/1999/xlink")
        self.root.set("width", f"{width}")
        self.root.set("height", f"{height}")
        self.root.set("viewBox", self.viewbox)

        # Create defs section for symbols
        self.defs = SubElement(self.root, "defs")

        # Style element for CSS
        self._style = SubElement(self.defs, "style")
        self._style.set("type", "text/css")
        self._css_rules: List[str] = []

    def add_css(self, rule: str):
        """Add a CSS rule to the stylesheet."""
        self._css_rules.append(rule)

    def group(
        self,
        parent: Optional[Element] = None,
        id: Optional[str] = None,
        class_: Optional[str] = None,
        transform: Optional[str] = None,
        data: Optional[Dict[str, str]] = None,
    ) -> Element:
        """
        Create a group element.

        Args:
            parent: Parent element (default: root)
            id: Element ID
            class_: CSS class
            transform: SVG transform string
            data: Dict of data-* attributes
        """
        parent = parent if parent is not None else self.root
        g = SubElement(parent, "g")

        if id:
            g.set("id", id)
        if class_:
            g.set("class", class_)
        if transform:
            g.set("transform", transform)
        if data:
            for key, value in data.items():
                g.set(f"data-{key}", str(value))

        return g

    def path(
        self,
        d: str,
        parent: Optional[Element] = None,
        id: Optional[str] = None,
        class_: Optional[str] = None,
        stroke: str = "#000000",
        stroke_width: float = 1,
        fill: str = "none",
        stroke_dasharray: Optional[str] = None,
        data: Optional[Dict[str, str]] = None,
    ) -> Element:
        """
        Create a path element.

        Args:
            d: Path data string
            parent: Parent element (default: root)
            id: Element ID
            class_: CSS class
            stroke: Stroke color
            stroke_width: Stroke width
            fill: Fill color
            stroke_dasharray: Dash pattern
            data: Dict of data-* attributes
        """
        parent = parent if parent is not None else self.root
        path = SubElement(parent, "path")
        path.set("d", d)
        path.set("stroke", stroke)
        path.set("stroke-width", str(stroke_width))
        path.set("fill", fill)

        if stroke_dasharray:
            path.set("stroke-dasharray", stroke_dasharray)
        if id:
            path.set("id", id)
        if class_:
            path.set("class", class_)
        if data:
            for key, value in data.items():
                path.set(f"data-{key}", str(value))

        return path

    def rect(
        self,
        x: float,
        y: float,
        width: float,
        height: float,
        parent: Optional[Element] = None,
        id: Optional[str] = None,
        class_: Optional[str] = None,
        stroke: str = "#000000",
        stroke_width: float = 1,
        fill: str = "none",
        rx: Optional[float] = None,
        data: Optional[Dict[str, str]] = None,
    ) -> Element:
        """Create a rectangle element."""
        parent = parent if parent is not None else self.root
        rect = SubElement(parent, "rect")
        rect.set("x", str(x))
        rect.set("y", str(y))
        rect.set("width", str(width))
        rect.set("height", str(height))
        rect.set("stroke", stroke)
        rect.set("stroke-width", str(stroke_width))
        rect.set("fill", fill)

        if id:
            rect.set("id", id)
        if class_:
            rect.set("class", class_)
        if rx is not None:
            rect.set("rx", str(rx))
        if data:
            for key, value in data.items():
                rect.set(f"data-{key}", str(value))

        return rect

    def line(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        parent: Optional[Element] = None,
        id: Optional[str] = None,
        class_: Optional[str] = None,
        stroke: str = "#000000",
        stroke_width: float = 1,
        stroke_dasharray: Optional[str] = None,
        data: Optional[Dict[str, str]] = None,
    ) -> Element:
        """Create a line element."""
        parent = parent if parent is not None else self.root
        line = SubElement(parent, "line")
        line.set("x1", str(x1))
        line.set("y1", str(y1))
        line.set("x2", str(x2))
        line.set("y2", str(y2))
        line.set("stroke", stroke)
        line.set("stroke-width", str(stroke_width))

        if stroke_dasharray:
            line.set("stroke-dasharray", stroke_dasharray)
        if id:
            line.set("id", id)
        if class_:
            line.set("class", class_)
        if data:
            for key, value in data.items():
                line.set(f"data-{key}", str(value))

        return line

    def circle(
        self,
        cx: float,
        cy: float,
        r: float,
        parent: Optional[Element] = None,
        id: Optional[str] = None,
        class_: Optional[str] = None,
        stroke: str = "#000000",
        stroke_width: float = 1,
        fill: str = "none",
        data: Optional[Dict[str, str]] = None,
    ) -> Element:
        """Create a circle element."""
        parent = parent if parent is not None else self.root
        circle = SubElement(parent, "circle")
        circle.set("cx", str(cx))
        circle.set("cy", str(cy))
        circle.set("r", str(r))
        circle.set("stroke", stroke)
        circle.set("stroke-width", str(stroke_width))
        circle.set("fill", fill)

        if id:
            circle.set("id", id)
        if class_:
            circle.set("class", class_)
        if data:
            for key, value in data.items():
                circle.set(f"data-{key}", str(value))

        return circle

    def text(
        self,
        content: str,
        x: float,
        y: float,
        parent: Optional[Element] = None,
        id: Optional[str] = None,
        class_: Optional[str] = None,
        font_family: str = "Arial, sans-serif",
        font_size: float = 12,
        font_weight: str = "normal",
        font_style: str = "normal",
        fill: str = "#000000",
        text_anchor: str = "start",
        dominant_baseline: str = "auto",
        transform: Optional[str] = None,
        data: Optional[Dict[str, str]] = None,
    ) -> Element:
        """Create a text element."""
        parent = parent if parent is not None else self.root
        text_elem = SubElement(parent, "text")
        text_elem.set("x", str(x))
        text_elem.set("y", str(y))
        text_elem.set("font-family", font_family)
        text_elem.set("font-size", str(font_size))
        text_elem.set("font-weight", font_weight)
        if font_style != "normal":
            text_elem.set("font-style", font_style)
        text_elem.set("fill", fill)
        text_elem.set("text-anchor", text_anchor)
        text_elem.set("dominant-baseline", dominant_baseline)
        text_elem.text = content

        if id:
            text_elem.set("id", id)
        if class_:
            text_elem.set("class", class_)
        if transform:
            text_elem.set("transform", transform)
        if data:
            for key, value in data.items():
                text_elem.set(f"data-{key}", str(value))

        return text_elem

    def polyline(
        self,
        points: List[Tuple[float, float]],
        parent: Optional[Element] = None,
        id: Optional[str] = None,
        class_: Optional[str] = None,
        stroke: str = "#000000",
        stroke_width: float = 1,
        fill: str = "none",
        data: Optional[Dict[str, str]] = None,
    ) -> Element:
        """Create a polyline element."""
        parent = parent if parent is not None else self.root
        polyline = SubElement(parent, "polyline")
        points_str = " ".join(f"{x},{y}" for x, y in points)
        polyline.set("points", points_str)
        polyline.set("stroke", stroke)
        polyline.set("stroke-width", str(stroke_width))
        polyline.set("fill", fill)

        if id:
            polyline.set("id", id)
        if class_:
            polyline.set("class", class_)
        if data:
            for key, value in data.items():
                polyline.set(f"data-{key}", str(value))

        return polyline

    def polygon(
        self,
        points: List[Tuple[float, float]],
        parent: Optional[Element] = None,
        id: Optional[str] = None,
        class_: Optional[str] = None,
        stroke: str = "#000000",
        stroke_width: float = 1,
        fill: str = "none",
        data: Optional[Dict[str, str]] = None,
    ) -> Element:
        """Create a polygon element."""
        parent = parent if parent is not None else self.root
        polygon = SubElement(parent, "polygon")
        points_str = " ".join(f"{x},{y}" for x, y in points)
        polygon.set("points", points_str)
        polygon.set("stroke", stroke)
        polygon.set("stroke-width", str(stroke_width))
        polygon.set("fill", fill)

        if id:
            polygon.set("id", id)
        if class_:
            polygon.set("class", class_)
        if data:
            for key, value in data.items():
                polygon.set(f"data-{key}", str(value))

        return polygon

    def use(
        self,
        href: str,
        x: float = 0,
        y: float = 0,
        parent: Optional[Element] = None,
        id: Optional[str] = None,
        class_: Optional[str] = None,
        transform: Optional[str] = None,
        data: Optional[Dict[str, str]] = None,
    ) -> Element:
        """Create a use element to reference a symbol."""
        parent = parent if parent is not None else self.root
        use = SubElement(parent, "use")
        use.set("href", href)
        use.set("x", str(x))
        use.set("y", str(y))

        if id:
            use.set("id", id)
        if class_:
            use.set("class", class_)
        if transform:
            use.set("transform", transform)
        if data:
            for key, value in data.items():
                use.set(f"data-{key}", str(value))

        return use

    def symbol(
        self,
        id: str,
        viewbox: Optional[str] = None,
    ) -> Element:
        """
        Create a symbol in the defs section.

        Returns the symbol element to add children to.
        """
        symbol = SubElement(self.defs, "symbol")
        symbol.set("id", id)
        if viewbox:
            symbol.set("viewBox", viewbox)
        return symbol

    def arc_path(
        self,
        cx: float,
        cy: float,
        r: float,
        start_angle: float,
        end_angle: float,
    ) -> str:
        """
        Generate path data for an arc.

        Args:
            cx, cy: Center point
            r: Radius
            start_angle: Start angle in degrees (0 = right, 90 = down)
            end_angle: End angle in degrees
        """
        import math

        # Convert to radians
        start_rad = math.radians(start_angle)
        end_rad = math.radians(end_angle)

        # Calculate start and end points
        x1 = cx + r * math.cos(start_rad)
        y1 = cy + r * math.sin(start_rad)
        x2 = cx + r * math.cos(end_rad)
        y2 = cy + r * math.sin(end_rad)

        # Determine arc sweep direction
        angle_diff = end_angle - start_angle
        large_arc = 1 if abs(angle_diff) > 180 else 0
        sweep = 1 if angle_diff > 0 else 0

        return f"M {x1},{y1} A {r},{r} 0 {large_arc},{sweep} {x2},{y2}"

    def to_string(self, indent: bool = True) -> str:
        """
        Convert SVG to string.

        Args:
            indent: Whether to indent the output (default: True)
        """
        # Update CSS in style element
        if self._css_rules:
            self._style.text = "\n" + "\n".join(self._css_rules) + "\n"

        # Convert to string
        if indent:
            ET.indent(self.root, space="  ")

        xml_str = tostring(self.root, encoding="unicode")

        # Add XML declaration
        return f'<?xml version="1.0" encoding="UTF-8"?>\n{xml_str}'


def escape_text(text: str) -> str:
    """Escape special characters for SVG text content."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )
