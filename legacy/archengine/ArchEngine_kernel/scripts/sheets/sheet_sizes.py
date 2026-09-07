"""
Sheet size definitions for architectural drawings.

Standard ARCH sheet sizes in inches, with conversions to points (72 DPI)
and millimeters for SVG viewBox calculations.
"""

from dataclasses import dataclass
from typing import Tuple

# Conversion factors
INCHES_TO_POINTS = 72  # 72 points per inch (standard PDF/SVG)
INCHES_TO_MM = 25.4


@dataclass
class SheetSize:
    """Represents a standard sheet size."""
    name: str
    width_in: float   # Width in inches
    height_in: float  # Height in inches

    @property
    def width_pt(self) -> float:
        """Width in points (for SVG)."""
        return self.width_in * INCHES_TO_POINTS

    @property
    def height_pt(self) -> float:
        """Height in points (for SVG)."""
        return self.height_in * INCHES_TO_POINTS

    @property
    def width_mm(self) -> float:
        """Width in millimeters."""
        return self.width_in * INCHES_TO_MM

    @property
    def height_mm(self) -> float:
        """Height in millimeters."""
        return self.height_in * INCHES_TO_MM

    @property
    def size_pt(self) -> Tuple[float, float]:
        """Size as (width, height) in points."""
        return (self.width_pt, self.height_pt)

    @property
    def size_mm(self) -> Tuple[float, float]:
        """Size as (width, height) in mm."""
        return (self.width_mm, self.height_mm)


# Standard ARCH sheet sizes (landscape orientation)
SHEET_SIZES = {
    "ARCH_A": SheetSize("ARCH_A", 12, 9),      # 12" x 9"
    "ARCH_B": SheetSize("ARCH_B", 18, 12),     # 18" x 12"
    "ARCH_C": SheetSize("ARCH_C", 24, 18),     # 24" x 18"
    "ARCH_D": SheetSize("ARCH_D", 36, 24),     # 36" x 24" (default)
    "ARCH_E": SheetSize("ARCH_E", 48, 36),     # 48" x 36"
}

# Common architectural scales
SCALES = {
    "1:1": 1.0,
    "1:2": 0.5,
    "1:5": 0.2,
    "1:10": 0.1,
    "1:20": 0.05,
    "1:50": 0.02,
    "1:100": 0.01,
    "1:200": 0.005,
    "1:500": 0.002,
}

# Title block dimensions (in points, for ARCH_D)
TITLE_BLOCK = {
    "height": 72,        # 1 inch tall
    "margin": 36,        # 0.5 inch margin
    "border_width": 2,   # Border stroke width
}


def get_sheet_size(name: str) -> SheetSize:
    """Get a sheet size by name."""
    if name not in SHEET_SIZES:
        raise ValueError(f"Unknown sheet size: {name}. Valid sizes: {list(SHEET_SIZES.keys())}")
    return SHEET_SIZES[name]


def get_scale_factor(scale: str) -> float:
    """Get scale factor from scale string like '1:50'."""
    if scale in SCALES:
        return SCALES[scale]

    # Parse custom scale
    if ":" in scale:
        parts = scale.split(":")
        if len(parts) == 2:
            try:
                return float(parts[0]) / float(parts[1])
            except ValueError:
                pass

    raise ValueError(f"Invalid scale: {scale}. Use format like '1:50'")
