"""
SVG Parser for extracting editable elements from generated drawings.

Parses SVG content to extract:
- Dimension text elements (class="dimension" or class="dim-text")
- Room labels
- Other annotated elements

Returns structured data that can be used to create editable overlay items.
"""
import re
import xml.etree.ElementTree as ET
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass

from sheets.dimension_item import DimensionData


# SVG namespace
SVG_NS = {'svg': 'http://www.w3.org/2000/svg'}


def parse_svg_dimensions(svg_content: str) -> List[DimensionData]:
    """
    Parse SVG content and extract all dimension text elements.

    Looks for <text> elements with:
    - class="dimension"
    - class="dim-text"

    Args:
        svg_content: Raw SVG string

    Returns:
        List of DimensionData objects
    """
    dimensions = []

    try:
        # Parse SVG
        root = ET.fromstring(svg_content)

        # Find all text elements
        text_elements = root.findall('.//{http://www.w3.org/2000/svg}text')

        # Also try without namespace (some SVGs don't use it properly)
        text_elements.extend(root.findall('.//text'))

        dim_index = 0
        for elem in text_elements:
            css_class = elem.get('class', '')

            # Check if it's a dimension element
            if 'dimension' in css_class or 'dim-text' in css_class:
                dim_data = _parse_text_element(elem, dim_index)
                if dim_data:
                    dimensions.append(dim_data)
                    dim_index += 1

    except ET.ParseError as e:
        print(f"SVG parse error: {e}")
        # Fall back to regex parsing
        dimensions = _parse_dimensions_regex(svg_content)

    return dimensions


def _parse_text_element(elem: ET.Element, index: int) -> Optional[DimensionData]:
    """
    Parse a single text element into DimensionData.

    Args:
        elem: XML element
        index: Index for generating unique ID

    Returns:
        DimensionData or None if invalid
    """
    # Get position
    try:
        x = float(elem.get('x', 0))
        y = float(elem.get('y', 0))
    except ValueError:
        return None

    # Get text content
    text = elem.text or ''
    text = text.strip()
    if not text:
        # Check for nested tspan elements
        for tspan in elem:
            if tspan.text:
                text = tspan.text.strip()
                break

    if not text:
        return None

    # Parse font properties from style attribute
    style = elem.get('style', '')
    font_size = _extract_font_size(elem, style)
    font_family = _extract_font_family(elem, style)
    font_weight = _extract_font_weight(elem, style)

    # Get text-anchor
    text_anchor = elem.get('text-anchor', 'start')
    if not text_anchor and 'text-anchor' in style:
        match = re.search(r'text-anchor:\s*(\w+)', style)
        if match:
            text_anchor = match.group(1)

    # Parse transform for rotation
    transform = elem.get('transform', '')
    rotation = _extract_rotation(transform)

    # Generate unique ID
    dim_id = f"dim_{index}_{hash((x, y, text)) % 10000}"

    return DimensionData(
        id=dim_id,
        x=x,
        y=y,
        original_text=text,
        font_size=font_size,
        font_family=font_family,
        font_weight=font_weight,
        text_anchor=text_anchor,
        rotation=rotation,
        transform=transform if transform else None,
    )


def _extract_font_size(elem: ET.Element, style: str) -> float:
    """Extract font size from element attributes or style."""
    # Check font-size attribute
    font_size_attr = elem.get('font-size')
    if font_size_attr:
        return _parse_size_value(font_size_attr)

    # Check style attribute
    match = re.search(r'font(?:-size)?:\s*(?:bold\s+)?(\d+(?:\.\d+)?)', style)
    if match:
        return float(match.group(1))

    # Check font shorthand (e.g., "font: bold 300px Arial")
    match = re.search(r'font:\s*(?:bold\s+)?(\d+(?:\.\d+)?)px', style)
    if match:
        return float(match.group(1))

    return 300  # Default


def _extract_font_family(elem: ET.Element, style: str) -> str:
    """Extract font family from element attributes or style."""
    font_family = elem.get('font-family')
    if font_family:
        return font_family

    match = re.search(r'font-family:\s*([^;]+)', style)
    if match:
        return match.group(1).strip().strip('"\'')

    # Check font shorthand
    match = re.search(r'font:[^;]*\s(\w+)(?:;|$)', style)
    if match:
        return match.group(1)

    return "Arial"


def _extract_font_weight(elem: ET.Element, style: str) -> str:
    """Extract font weight from element attributes or style."""
    font_weight = elem.get('font-weight')
    if font_weight:
        return font_weight

    if 'font-weight: bold' in style or 'font: bold' in style:
        return "bold"

    return "normal"


def _extract_rotation(transform: str) -> float:
    """Extract rotation angle from SVG transform attribute."""
    if not transform:
        return 0

    # Look for rotate(angle) or rotate(angle, cx, cy)
    match = re.search(r'rotate\(\s*(-?\d+(?:\.\d+)?)', transform)
    if match:
        return float(match.group(1))

    return 0


def _parse_size_value(value: str) -> float:
    """Parse a size value (e.g., '300px', '300')."""
    match = re.match(r'(-?\d+(?:\.\d+)?)', value)
    if match:
        return float(match.group(1))
    return 300


def _parse_dimensions_regex(svg_content: str) -> List[DimensionData]:
    """
    Fallback regex-based parsing for malformed SVG.

    Args:
        svg_content: Raw SVG string

    Returns:
        List of DimensionData objects
    """
    dimensions = []

    # Pattern to match dimension text elements
    pattern = r'<text[^>]*class="[^"]*dimension[^"]*"[^>]*x="([^"]+)"[^>]*y="([^"]+)"[^>]*>([^<]+)</text>'

    matches = re.finditer(pattern, svg_content, re.IGNORECASE)

    for i, match in enumerate(matches):
        try:
            x = float(match.group(1))
            y = float(match.group(2))
            text = match.group(3).strip()

            if text:
                dimensions.append(DimensionData(
                    id=f"dim_{i}_{hash((x, y, text)) % 10000}",
                    x=x,
                    y=y,
                    original_text=text,
                ))
        except ValueError:
            continue

    return dimensions


def get_svg_viewbox(svg_content: str) -> Optional[Tuple[float, float, float, float]]:
    """
    Extract viewBox from SVG content.

    Returns:
        Tuple of (x, y, width, height) or None
    """
    match = re.search(r'viewBox="([^"]+)"', svg_content)
    if match:
        parts = match.group(1).split()
        if len(parts) == 4:
            try:
                return tuple(float(p) for p in parts)
            except ValueError:
                pass
    return None


def remove_dimensions_from_svg(svg_content: str) -> str:
    """
    Remove dimension text elements from SVG content.

    This is used to avoid rendering dimensions twice - once in the SVG
    and once as editable overlay items.

    Args:
        svg_content: Original SVG string

    Returns:
        SVG string with dimension elements removed
    """
    # Parse and manipulate
    try:
        root = ET.fromstring(svg_content)

        # Find and remove dimension text elements
        for parent in root.iter():
            for child in list(parent):
                if child.tag.endswith('text'):
                    css_class = child.get('class', '')
                    if 'dimension' in css_class or 'dim-text' in css_class:
                        parent.remove(child)

        # Convert back to string
        return ET.tostring(root, encoding='unicode')

    except ET.ParseError:
        # Fallback: use regex to comment out dimension elements
        pattern = r'(<text[^>]*class="[^"]*dimension[^"]*"[^>]*>[^<]*</text>)'
        return re.sub(pattern, r'<!-- \1 -->', svg_content)


def apply_dimension_overrides(
    dimensions: List[DimensionData],
    overrides: Dict[str, str]
) -> List[DimensionData]:
    """
    Apply saved overrides to dimension data.

    Args:
        dimensions: List of parsed dimensions
        overrides: Dict mapping dimension IDs to override text

    Returns:
        Same list with overrides applied
    """
    for dim in dimensions:
        if dim.id in overrides:
            dim.override_text = overrides[dim.id]
    return dimensions
