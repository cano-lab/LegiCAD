#!/usr/bin/env python3
"""
pdf_export.py - Professional architectural PDF export with Bluebeam-style precision

Creates construction-quality PDF drawings with:
- Vector precision (no rasterization)
- Standard architectural sheet sizes
- Precise line weights (hairline to heavy)
- Professional typography
- Layer organization
- Bookmarks and navigation
- Multi-page drawing sets
- Print-ready output at standard scales

Requires: reportlab, svglib (install with: pip install reportlab svglib)
"""

import os
import io
import math
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Union
from enum import Enum
from datetime import datetime

try:
    from reportlab.lib import colors
    from reportlab.lib.units import mm, inch
    from reportlab.lib.pagesizes import letter, legal, A1, A2, A3, A4
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.graphics import renderPDF
    from reportlab.lib.styles import getSampleStyleSheet
    pt = 1  # 1 point is the base unit in reportlab
    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False
    # Define fallback units for when reportlab isn't installed
    # (72 points = 1 inch, 1 inch = 25.4 mm)
    pt = 1
    inch = 72
    mm = 72 / 25.4
    letter = (612, 792)
    legal = (612, 1008)
    A4 = (595.276, 841.89)
    A3 = (841.89, 1190.55)
    A2 = (1190.55, 1683.78)
    A1 = (1683.78, 2383.94)

try:
    from svglib.svglib import svg2rlg
    HAS_SVGLIB = True
except ImportError:
    HAS_SVGLIB = False

from logging_config import get_logger, log_step

logger = get_logger('pdf_export')


# =============================================================================
# CONSTANTS AND ENUMS
# =============================================================================

class SheetSize(Enum):
    """Standard architectural sheet sizes."""
    # US Architectural sizes
    ARCH_A = "arch_a"   # 9" x 12"
    ARCH_B = "arch_b"   # 12" x 18"
    ARCH_C = "arch_c"   # 18" x 24"
    ARCH_D = "arch_d"   # 24" x 36"
    ARCH_E = "arch_e"   # 36" x 48"
    ARCH_E1 = "arch_e1" # 30" x 42"

    # ISO sizes
    A4 = "a4"           # 210mm x 297mm
    A3 = "a3"           # 297mm x 420mm
    A2 = "a2"           # 420mm x 594mm
    A1 = "a1"           # 594mm x 841mm
    A0 = "a0"           # 841mm x 1189mm

    # ANSI sizes
    ANSI_A = "ansi_a"   # 8.5" x 11" (Letter)
    ANSI_B = "ansi_b"   # 11" x 17" (Tabloid)
    ANSI_C = "ansi_c"   # 17" x 22"
    ANSI_D = "ansi_d"   # 22" x 34"
    ANSI_E = "ansi_e"   # 34" x 44"


# Sheet size dimensions in points (72 pt = 1 inch)
SHEET_DIMENSIONS = {
    # US Architectural
    SheetSize.ARCH_A: (9 * inch, 12 * inch),
    SheetSize.ARCH_B: (12 * inch, 18 * inch),
    SheetSize.ARCH_C: (18 * inch, 24 * inch),
    SheetSize.ARCH_D: (24 * inch, 36 * inch),
    SheetSize.ARCH_E: (36 * inch, 48 * inch),
    SheetSize.ARCH_E1: (30 * inch, 42 * inch),
    # ISO
    SheetSize.A4: A4,
    SheetSize.A3: A3,
    SheetSize.A2: A2,
    SheetSize.A1: A1,
    SheetSize.A0: (841 * mm, 1189 * mm),
    # ANSI
    SheetSize.ANSI_A: letter,
    SheetSize.ANSI_B: (11 * inch, 17 * inch),
    SheetSize.ANSI_C: (17 * inch, 22 * inch),
    SheetSize.ANSI_D: (22 * inch, 34 * inch),
    SheetSize.ANSI_E: (34 * inch, 44 * inch),
}


class LineWeight(Enum):
    """Standard architectural line weights."""
    HAIRLINE = 0.13 * mm    # 0.13mm - Dimension lines, hatching
    FINE = 0.18 * mm        # 0.18mm - Text, annotations
    LIGHT = 0.25 * mm       # 0.25mm - Minor details
    MEDIUM = 0.35 * mm      # 0.35mm - Object lines
    HEAVY = 0.50 * mm       # 0.50mm - Section cut lines
    EXTRA_HEAVY = 0.70 * mm # 0.70mm - Border lines
    BORDER = 1.00 * mm      # 1.00mm - Sheet border


class DrawingScale(Enum):
    """Common architectural scales."""
    FULL = (1, 1, "1:1 (Full Scale)")
    HALF = (1, 2, "1:2")
    QUARTER = (1, 4, "1:4")
    EIGHTH = (1, 8, "1:8")
    TENTH = (1, 10, "1:10")
    TWENTIETH = (1, 20, "1:20")
    FIFTIETH = (1, 50, "1:50")
    HUNDREDTH = (1, 100, "1:100")
    TWO_HUNDREDTH = (1, 200, "1:200")

    # Imperial
    QUARTER_INCH = (1, 48, '1/4" = 1\'-0"')
    HALF_INCH = (1, 24, '1/2" = 1\'-0"')
    THREE_QUARTER_INCH = (1, 16, '3/4" = 1\'-0"')
    ONE_INCH = (1, 12, '1" = 1\'-0"')
    THREE_INCH = (1, 4, '3" = 1\'-0"')


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class PDFStyle:
    """Style configuration for PDF output."""
    line_color: Tuple[float, float, float] = (0, 0, 0)  # RGB 0-1
    fill_color: Optional[Tuple[float, float, float]] = None
    line_weight: LineWeight = LineWeight.MEDIUM
    font_family: str = "Helvetica"
    font_size: float = 10
    text_color: Tuple[float, float, float] = (0, 0, 0)


@dataclass
class DrawingSheet:
    """A single drawing sheet."""
    number: str                     # Sheet number (e.g., "A-101")
    title: str                      # Sheet title
    drawings: List[str] = field(default_factory=list)  # SVG file paths
    scale: DrawingScale = DrawingScale.HUNDREDTH
    revision: str = "-"
    notes: List[str] = field(default_factory=list)


@dataclass
class DrawingSet:
    """Complete drawing set configuration."""
    project_name: str
    project_number: str
    sheets: List[DrawingSheet] = field(default_factory=list)
    sheet_size: SheetSize = SheetSize.ARCH_D
    company_name: str = "ArchEngine"
    company_address: str = ""
    date: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))


# =============================================================================
# PDF CANVAS EXTENSIONS
# =============================================================================

# Only define canvas class if reportlab is available
if HAS_REPORTLAB:
    class ArchitecturalCanvas(canvas.Canvas):
        """Extended canvas with architectural drawing features."""

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.current_layer = "Default"
            self.layers = {}
            self._setup_fonts()

        def _setup_fonts(self):
            """Register additional fonts if available."""
            # Try to register common architectural fonts
            font_dirs = [
                "C:/Windows/Fonts",
                "/usr/share/fonts",
                "/Library/Fonts",
            ]

            fonts_to_try = [
                ("ArialNarrow", "arialn.ttf"),
                ("TektonPro", "TektonPro-Regular.otf"),
            ]

            for font_name, font_file in fonts_to_try:
                for font_dir in font_dirs:
                    font_path = os.path.join(font_dir, font_file)
                    if os.path.exists(font_path):
                        try:
                            pdfmetrics.registerFont(TTFont(font_name, font_path))
                            logger.debug(f"Registered font: {font_name}")
                            break
                        except Exception as e:
                            logger.debug(f"Could not register font {font_name}: {e}")

        def set_line_weight(self, weight: LineWeight):
            """Set line weight from LineWeight enum."""
            self.setLineWidth(weight.value)

        def set_layer(self, layer_name: str):
            """Set current layer (for organization/filtering)."""
            self.current_layer = layer_name
            if layer_name not in self.layers:
                self.layers[layer_name] = []

        def draw_line_precise(self, x1: float, y1: float, x2: float, y2: float,
                              weight: LineWeight = LineWeight.MEDIUM,
                              color: Tuple[float, float, float] = (0, 0, 0)):
            """Draw a line with precise weight and color."""
            self.setStrokeColorRGB(*color)
            self.setLineWidth(weight.value)
            self.line(x1, y1, x2, y2)

        def draw_rect_precise(self, x: float, y: float, width: float, height: float,
                              stroke_weight: LineWeight = LineWeight.MEDIUM,
                              stroke_color: Tuple[float, float, float] = (0, 0, 0),
                              fill_color: Optional[Tuple[float, float, float]] = None):
            """Draw a rectangle with precise styling."""
            self.setStrokeColorRGB(*stroke_color)
            self.setLineWidth(stroke_weight.value)

            if fill_color:
                self.setFillColorRGB(*fill_color)
                self.rect(x, y, width, height, fill=1, stroke=1)
            else:
                self.rect(x, y, width, height, fill=0, stroke=1)

        def draw_text_precise(self, text: str, x: float, y: float,
                              font_size: float = 10,
                              font_family: str = "Helvetica",
                              color: Tuple[float, float, float] = (0, 0, 0),
                              anchor: str = "sw"):  # sw, s, se, w, c, e, nw, n, ne
            """Draw text with precise positioning and styling."""
            self.setFillColorRGB(*color)
            self.setFont(font_family, font_size)

            # Calculate text dimensions for anchoring
            text_width = self.stringWidth(text, font_family, font_size)
            text_height = font_size  # Approximate

            # Adjust position based on anchor
            if anchor in ['n', 'c', 's']:
                x -= text_width / 2
            elif anchor in ['ne', 'e', 'se']:
                x -= text_width

            if anchor in ['n', 'ne', 'nw']:
                y -= text_height
            elif anchor in ['c', 'e', 'w']:
                y -= text_height / 2

            self.drawString(x, y, text)

        def draw_dimension(self, x1: float, y1: float, x2: float, y2: float,
                           value: str, offset: float = 10 * mm,
                           text_size: float = 8, units: str = "mm"):
            """Draw a dimension line with text."""
            # Calculate direction
            dx = x2 - x1
            dy = y2 - y1
            length = math.sqrt(dx*dx + dy*dy)

            if length < 0.1:
                return

            # Normalize direction
            nx = dx / length
            ny = dy / length

            # Perpendicular direction
            px = -ny
            py = nx

            # Offset points
            ox1 = x1 + px * offset
            oy1 = y1 + py * offset
            ox2 = x2 + px * offset
            oy2 = y2 + py * offset

            # Draw extension lines
            self.set_line_weight(LineWeight.HAIRLINE)
            self.setStrokeColorRGB(0, 0, 0)
            self.line(x1, y1, ox1 + px * 2*mm, oy1 + py * 2*mm)
            self.line(x2, y2, ox2 + px * 2*mm, oy2 + py * 2*mm)

            # Draw dimension line
            self.line(ox1, oy1, ox2, oy2)

            # Draw arrows/ticks
            arrow_size = 2 * mm
            # Start tick
            self.line(ox1 - px*arrow_size/2, oy1 - py*arrow_size/2,
                      ox1 + px*arrow_size/2, oy1 + py*arrow_size/2)
            # End tick
            self.line(ox2 - px*arrow_size/2, oy2 - py*arrow_size/2,
                      ox2 + px*arrow_size/2, oy2 + py*arrow_size/2)

            # Draw text
            mid_x = (ox1 + ox2) / 2
            mid_y = (oy1 + oy2) / 2

            # Rotate text to align with dimension line
            angle = math.degrees(math.atan2(dy, dx))
            if angle > 90 or angle < -90:
                angle += 180

            self.saveState()
            self.translate(mid_x, mid_y)
            self.rotate(angle)
            self.setFont("Helvetica", text_size)
            self.drawCentredString(0, 2*mm, value)
            self.restoreState()


# =============================================================================
# SVG TO PDF CONVERTER
# =============================================================================

def convert_svg_to_pdf_drawing(svg_path: str, scale: float = 1.0):
    """
    Convert an SVG file to a ReportLab drawing object.

    Args:
        svg_path: Path to SVG file
        scale: Scale factor to apply

    Returns:
        ReportLab drawing object or None if conversion fails
    """
    if not HAS_SVGLIB:
        logger.error("svglib not installed. Install with: pip install svglib")
        return None

    try:
        drawing = svg2rlg(svg_path)
        if drawing is None:
            logger.error(f"Failed to parse SVG: {svg_path}")
            return None

        if scale != 1.0:
            drawing.width *= scale
            drawing.height *= scale
            drawing.scale(scale, scale)

        return drawing

    except Exception as e:
        logger.error(f"Error converting SVG to PDF drawing: {e}")
        return None


def render_svg_to_canvas(canvas, svg_path: str,
                          x: float, y: float, scale: float = 1.0):
    """
    Render an SVG file onto a PDF canvas at specified position.

    Args:
        canvas: PDF canvas to render onto
        svg_path: Path to SVG file
        x: X position on canvas
        y: Y position on canvas
        scale: Scale factor
    """
    drawing = convert_svg_to_pdf_drawing(svg_path, scale)
    if drawing:
        renderPDF.draw(drawing, canvas, x, y)


# =============================================================================
# TITLE BLOCK RENDERER
# =============================================================================

def render_title_block(canvas,
                       sheet_size: SheetSize,
                       drawing_set: DrawingSet,
                       sheet: DrawingSheet,
                       margin: float = 0.5 * inch):
    """
    Render a professional title block on the sheet.
    """
    width, height = SHEET_DIMENSIONS[sheet_size]

    # Title block dimensions (bottom right)
    tb_width = 5 * inch
    tb_height = 1.5 * inch
    tb_x = width - margin - tb_width
    tb_y = margin

    # Draw title block border
    canvas.set_line_weight(LineWeight.HEAVY)
    canvas.setStrokeColorRGB(0, 0, 0)
    canvas.rect(tb_x, tb_y, tb_width, tb_height, fill=0, stroke=1)

    # Internal dividers
    canvas.set_line_weight(LineWeight.LIGHT)

    # Horizontal dividers
    canvas.line(tb_x, tb_y + 0.5*inch, tb_x + tb_width, tb_y + 0.5*inch)
    canvas.line(tb_x, tb_y + 1.0*inch, tb_x + tb_width, tb_y + 1.0*inch)

    # Vertical dividers
    canvas.line(tb_x + 3.5*inch, tb_y, tb_x + 3.5*inch, tb_y + 0.5*inch)
    canvas.line(tb_x + 4.0*inch, tb_y + 0.5*inch, tb_x + 4.0*inch, tb_y + 1.0*inch)

    # Project name (large, top)
    canvas.setFont("Helvetica-Bold", 14)
    canvas.drawCentredString(tb_x + tb_width/2, tb_y + tb_height - 0.3*inch,
                              drawing_set.project_name)

    # Company name
    canvas.setFont("Helvetica", 8)
    canvas.drawCentredString(tb_x + tb_width/2, tb_y + tb_height - 0.5*inch,
                              drawing_set.company_name)

    # Sheet title
    canvas.setFont("Helvetica-Bold", 12)
    canvas.drawCentredString(tb_x + 1.75*inch, tb_y + 0.75*inch, sheet.title)

    # Sheet number
    canvas.setFont("Helvetica-Bold", 16)
    canvas.drawCentredString(tb_x + 4.25*inch, tb_y + 0.75*inch, sheet.number)

    # Scale
    scale_text = sheet.scale.value[2] if hasattr(sheet.scale, 'value') else str(sheet.scale)
    canvas.setFont("Helvetica", 8)
    canvas.drawString(tb_x + 0.1*inch, tb_y + 0.3*inch, f"SCALE: {scale_text}")

    # Date
    canvas.drawString(tb_x + 1.5*inch, tb_y + 0.3*inch, f"DATE: {drawing_set.date}")

    # Project number
    canvas.drawString(tb_x + 3.6*inch, tb_y + 0.3*inch, f"PROJ: {drawing_set.project_number}")

    # Revision
    canvas.drawString(tb_x + 3.6*inch, tb_y + 0.15*inch, f"REV: {sheet.revision}")

    # Draw sheet border
    canvas.set_line_weight(LineWeight.BORDER)
    canvas.rect(margin, margin, width - 2*margin, height - 2*margin, fill=0, stroke=1)

    # Inner border
    canvas.set_line_weight(LineWeight.LIGHT)
    inner_margin = margin + 0.25*inch
    canvas.rect(inner_margin, inner_margin,
                width - 2*inner_margin, height - 2*inner_margin, fill=0, stroke=1)


# =============================================================================
# MAIN PDF GENERATOR
# =============================================================================

class PDFDrawingSetGenerator:
    """
    Generate professional PDF drawing sets from SVG drawings.
    """

    def __init__(self, drawing_set: DrawingSet):
        """
        Initialize the PDF generator.

        Args:
            drawing_set: Drawing set configuration
        """
        if not HAS_REPORTLAB:
            raise ImportError(
                "reportlab is required for PDF export. "
                "Install with: pip install reportlab"
            )

        self.drawing_set = drawing_set
        self.sheet_size = drawing_set.sheet_size
        self.page_width, self.page_height = SHEET_DIMENSIONS[self.sheet_size]
        self.margin = 0.5 * inch

    def generate(self, output_path: str, svg_files: Dict[str, str] = None):
        """
        Generate the complete PDF drawing set.

        Args:
            output_path: Output PDF file path
            svg_files: Optional mapping of sheet numbers to SVG file paths
        """
        logger.info(f"Generating PDF drawing set: {output_path}")
        logger.info(f"Sheet size: {self.sheet_size.value} ({self.page_width/inch:.1f}\" x {self.page_height/inch:.1f}\")")

        # Create canvas
        c = ArchitecturalCanvas(output_path, pagesize=(self.page_width, self.page_height))

        # Set PDF metadata
        c.setTitle(f"{self.drawing_set.project_name} - Drawing Set")
        c.setAuthor(self.drawing_set.company_name)
        c.setSubject("Architectural Drawing Set")
        c.setCreator("ArchEngine PDF Export")

        # Generate each sheet
        for i, sheet in enumerate(self.drawing_set.sheets):
            logger.info(f"Generating sheet {sheet.number}: {sheet.title}")

            # Render title block
            render_title_block(c, self.sheet_size, self.drawing_set, sheet, self.margin)

            # Render drawings
            drawing_area_width = self.page_width - 2 * self.margin
            drawing_area_height = self.page_height - 2 * self.margin - 1.5 * inch  # Leave room for title block

            for j, svg_path in enumerate(sheet.drawings):
                if os.path.exists(svg_path):
                    # Calculate position and scale
                    # For now, center single drawing
                    scale = min(
                        drawing_area_width / (800 * mm),  # Assuming max SVG width
                        drawing_area_height / (600 * mm)  # Assuming max SVG height
                    ) * 0.9  # 90% of available space

                    x = self.margin + drawing_area_width / 2
                    y = self.margin + 1.5 * inch + drawing_area_height / 2

                    render_svg_to_canvas(c, svg_path, x, y, scale)
                else:
                    logger.warning(f"SVG file not found: {svg_path}")

            # Add page
            c.showPage()

        # Save PDF
        c.save()
        logger.success(f"PDF saved: {output_path}")

        return output_path


def generate_single_sheet_pdf(
    svg_path: str,
    output_path: str,
    sheet_size: SheetSize = SheetSize.ARCH_D,
    title: str = "Drawing",
    sheet_number: str = "A-001",
    project_name: str = "Project",
    scale: DrawingScale = DrawingScale.HUNDREDTH
) -> str:
    """
    Generate a single-sheet PDF from an SVG file.

    Args:
        svg_path: Path to input SVG file
        output_path: Path for output PDF file
        sheet_size: Sheet size
        title: Drawing title
        sheet_number: Sheet number
        project_name: Project name
        scale: Drawing scale

    Returns:
        Path to generated PDF
    """
    if not HAS_REPORTLAB:
        raise ImportError("reportlab is required. Install with: pip install reportlab")

    drawing_set = DrawingSet(
        project_name=project_name,
        project_number="P-001",
        sheet_size=sheet_size,
        sheets=[
            DrawingSheet(
                number=sheet_number,
                title=title,
                drawings=[svg_path],
                scale=scale
            )
        ]
    )

    generator = PDFDrawingSetGenerator(drawing_set)
    return generator.generate(output_path)


def batch_convert_svg_to_pdf(
    svg_dir: str,
    output_dir: str,
    sheet_size: SheetSize = SheetSize.ARCH_D,
    project_name: str = "Project",
    create_set: bool = True
) -> List[str]:
    """
    Convert all SVG files in a directory to PDF.

    Args:
        svg_dir: Directory containing SVG files
        output_dir: Output directory for PDF files
        sheet_size: Sheet size for all drawings
        project_name: Project name
        create_set: If True, also create a combined drawing set PDF

    Returns:
        List of generated PDF file paths
    """
    svg_dir = Path(svg_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    svg_files = list(svg_dir.glob("*.svg"))
    if not svg_files:
        logger.warning(f"No SVG files found in {svg_dir}")
        return []

    logger.info(f"Converting {len(svg_files)} SVG files to PDF")

    # Drawing number mapping
    drawing_numbers = {
        "floor_plan": ("A-101", "FLOOR PLAN"),
        "roof_plan": ("A-102", "ROOF PLAN"),
        "elevation_south": ("A-201", "SOUTH ELEVATION"),
        "elevation_north": ("A-202", "NORTH ELEVATION"),
        "elevation_east": ("A-203", "EAST ELEVATION"),
        "elevation_west": ("A-204", "WEST ELEVATION"),
        "section_a": ("A-301", "SECTION A-A"),
        "section_b": ("A-302", "SECTION B-B"),
        "details": ("A-501", "CONSTRUCTION DETAILS"),
        "schedules": ("A-601", "SCHEDULES"),
    }

    generated_files = []
    sheets = []

    for svg_path in sorted(svg_files):
        svg_name = svg_path.stem

        # Get drawing info
        sheet_num, title = drawing_numbers.get(svg_name, ("A-000", svg_name.upper().replace("_", " ")))

        pdf_path = output_dir / f"{svg_name}.pdf"

        try:
            generate_single_sheet_pdf(
                str(svg_path),
                str(pdf_path),
                sheet_size=sheet_size,
                title=title,
                sheet_number=sheet_num,
                project_name=project_name
            )
            generated_files.append(str(pdf_path))

            sheets.append(DrawingSheet(
                number=sheet_num,
                title=title,
                drawings=[str(svg_path)]
            ))

        except Exception as e:
            logger.error(f"Failed to convert {svg_path}: {e}")

    # Create combined drawing set
    if create_set and sheets:
        set_path = output_dir / "drawing_set.pdf"

        try:
            drawing_set = DrawingSet(
                project_name=project_name,
                project_number="P-001",
                sheet_size=sheet_size,
                sheets=sorted(sheets, key=lambda s: s.number)
            )

            generator = PDFDrawingSetGenerator(drawing_set)
            generator.generate(str(set_path))
            generated_files.append(str(set_path))

        except Exception as e:
            logger.error(f"Failed to create drawing set: {e}")

    logger.info(f"Generated {len(generated_files)} PDF files")
    return generated_files


# =============================================================================
# COMMAND LINE INTERFACE
# =============================================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='Convert SVG architectural drawings to PDF',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  python pdf_export.py floor_plan.svg -o floor_plan.pdf
  python pdf_export.py ./drawings/ -o ./pdfs/ --batch
  python pdf_export.py ./drawings/ -o ./pdfs/ --batch --sheet-size arch_e
        '''
    )
    parser.add_argument('input', help='Input SVG file or directory')
    parser.add_argument('-o', '--output', required=True, help='Output PDF file or directory')
    parser.add_argument('--batch', action='store_true', help='Batch convert all SVGs in directory')
    parser.add_argument('--sheet-size', default='arch_d',
                       choices=[s.value for s in SheetSize],
                       help='Sheet size (default: arch_d)')
    parser.add_argument('--project', default='Project', help='Project name')
    parser.add_argument('--title', default='Drawing', help='Drawing title (single file mode)')
    parser.add_argument('--number', default='A-001', help='Sheet number (single file mode)')
    parser.add_argument('--no-set', action='store_true', help='Do not create combined drawing set (batch mode)')

    args = parser.parse_args()

    # Configure logging
    from logging_config import setup_logging
    setup_logging(name='archengine', level=logging.INFO, console=True, colors=True)

    # Parse sheet size
    sheet_size = SheetSize(args.sheet_size)

    if args.batch:
        # Batch mode
        batch_convert_svg_to_pdf(
            args.input,
            args.output,
            sheet_size=sheet_size,
            project_name=args.project,
            create_set=not args.no_set
        )
    else:
        # Single file mode
        generate_single_sheet_pdf(
            args.input,
            args.output,
            sheet_size=sheet_size,
            title=args.title,
            sheet_number=args.number,
            project_name=args.project
        )


if __name__ == '__main__':
    main()
