"""
Data models for drawing sheets and references.
"""
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Tuple, Any
from datetime import datetime
from enum import Enum


class SheetType(Enum):
    """Types of drawing sheets."""
    FLOOR_PLAN = "floor_plan"
    ROOF_PLAN = "roof_plan"
    ELEVATION_SOUTH = "elevation_south"
    ELEVATION_NORTH = "elevation_north"
    ELEVATION_EAST = "elevation_east"
    ELEVATION_WEST = "elevation_west"
    SECTION_A = "section_a"
    SECTION_B = "section_b"
    DETAILS = "details"
    SCHEDULES = "schedules"
    # Multi-viewport preset sheets (use InteractiveSheet for generation)
    PRESET_FLOOR_PLAN = "preset_floor_plan"
    PRESET_ELEVATIONS = "preset_elevations"
    PRESET_SECTIONS = "preset_sections"
    PRESET_DETAILS = "preset_details"
    PRESET_SCHEDULES = "preset_schedules"


# Default sheet configurations
SHEET_DEFAULTS = {
    SheetType.FLOOR_PLAN: {"title": "Floor Plan", "category": "Plans", "number_suffix": "01"},
    SheetType.ROOF_PLAN: {"title": "Roof Plan", "category": "Plans", "number_suffix": "02"},
    SheetType.ELEVATION_SOUTH: {"title": "South Elevation", "category": "Elevations", "number_suffix": "01"},
    SheetType.ELEVATION_NORTH: {"title": "North Elevation", "category": "Elevations", "number_suffix": "02"},
    SheetType.ELEVATION_EAST: {"title": "East Elevation", "category": "Elevations", "number_suffix": "03"},
    SheetType.ELEVATION_WEST: {"title": "West Elevation", "category": "Elevations", "number_suffix": "04"},
    SheetType.SECTION_A: {"title": "Building Section A", "category": "Sections", "number_suffix": "01"},
    SheetType.SECTION_B: {"title": "Building Section B", "category": "Sections", "number_suffix": "02"},
    SheetType.DETAILS: {"title": "Construction Details", "category": "Details", "number_suffix": "01"},
    SheetType.SCHEDULES: {"title": "Schedules", "category": "Schedules", "number_suffix": "01"},
    # Preset sheets
    SheetType.PRESET_FLOOR_PLAN: {"title": "Floor Plan Sheet", "category": "Plans", "number_suffix": "10"},
    SheetType.PRESET_ELEVATIONS: {"title": "Elevations Sheet", "category": "Elevations", "number_suffix": "10"},
    SheetType.PRESET_SECTIONS: {"title": "Sections Sheet", "category": "Sections", "number_suffix": "10"},
    SheetType.PRESET_DETAILS: {"title": "Details Sheet", "category": "Details", "number_suffix": "10"},
    SheetType.PRESET_SCHEDULES: {"title": "Schedules Sheet", "category": "Schedules", "number_suffix": "10"},
}

# Category prefixes for numbering
CATEGORY_PREFIXES = {
    "Plans": "1",
    "Elevations": "2",
    "Sections": "3",
    "Details": "4",
    "Schedules": "5",
}


@dataclass
class DrawingReference:
    """
    Cross-reference between drawings.
    For example, a section marker on a floor plan pointing to a section sheet.
    """
    source_sheet_id: str          # Sheet containing the marker
    target_sheet_id: str          # Sheet being referenced
    marker_type: str              # "section", "detail", "elevation", "callout"
    marker_id: str                # "A", "B", "1", etc.
    position: Tuple[float, float] # Position on source sheet (mm)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'source_sheet_id': self.source_sheet_id,
            'target_sheet_id': self.target_sheet_id,
            'marker_type': self.marker_type,
            'marker_id': self.marker_id,
            'position': list(self.position),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DrawingReference':
        return cls(
            source_sheet_id=data['source_sheet_id'],
            target_sheet_id=data['target_sheet_id'],
            marker_type=data['marker_type'],
            marker_id=data['marker_id'],
            position=tuple(data['position']),
        )


@dataclass
class SheetConfig:
    """Configuration for a single drawing sheet."""
    id: str                              # Unique ID (e.g., "floor_plan_1")
    sheet_type: SheetType                # Type of sheet
    title: str                           # Display title
    number: str                          # Drawing number (e.g., "A-101")
    scale: str = "1:100"                 # Drawing scale
    revision: str = "-"                  # Revision letter
    enabled: bool = True                 # Auto-regenerate enabled
    svg_content: Optional[str] = None    # Cached SVG content
    last_generated: Optional[datetime] = None
    references_out: List[DrawingReference] = field(default_factory=list)  # Markers on this sheet
    references_in: List[DrawingReference] = field(default_factory=list)   # Sheets referencing this
    dimension_overrides: Dict[str, str] = field(default_factory=dict)     # Editable dimension overrides
    # Preset configuration (for PRESET_* sheet types)
    preset_name: Optional[str] = None    # Name of preset used
    preset_config: Optional[Dict[str, Any]] = None  # Serialized preset config
    # Generation metadata (solver used, generation timestamp, etc.)
    generation_metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def category(self) -> str:
        """Get the category for this sheet type."""
        return SHEET_DEFAULTS.get(self.sheet_type, {}).get('category', 'Other')

    @property
    def has_content(self) -> bool:
        """Check if SVG content is available."""
        return self.svg_content is not None and len(self.svg_content) > 0

    @property
    def status(self) -> str:
        """Get generation status."""
        if not self.enabled:
            return "Disabled"
        if not self.has_content:
            return "Not Generated"
        if self.last_generated:
            return f"Generated {self.last_generated.strftime('%H:%M')}"
        return "Ready"

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'sheet_type': self.sheet_type.value,
            'title': self.title,
            'number': self.number,
            'scale': self.scale,
            'revision': self.revision,
            'enabled': self.enabled,
            'last_generated': self.last_generated.isoformat() if self.last_generated else None,
            'references_out': [ref.to_dict() for ref in self.references_out],
            'references_in': [ref.to_dict() for ref in self.references_in],
            'dimension_overrides': self.dimension_overrides,
            'preset_name': self.preset_name,
            'preset_config': self.preset_config,
            'generation_metadata': self.generation_metadata,
            # Note: svg_content not saved - regenerated on load
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SheetConfig':
        return cls(
            id=data['id'],
            sheet_type=SheetType(data['sheet_type']),
            title=data['title'],
            number=data['number'],
            scale=data.get('scale', '1:100'),
            revision=data.get('revision', '-'),
            enabled=data.get('enabled', True),
            last_generated=datetime.fromisoformat(data['last_generated']) if data.get('last_generated') else None,
            references_out=[DrawingReference.from_dict(r) for r in data.get('references_out', [])],
            references_in=[DrawingReference.from_dict(r) for r in data.get('references_in', [])],
            dimension_overrides=data.get('dimension_overrides', {}),
            preset_name=data.get('preset_name'),
            preset_config=data.get('preset_config'),
            generation_metadata=data.get('generation_metadata', {}),
        )


@dataclass
class TitleBlockInfo:
    """Title block information for all sheets."""
    project_name: str = "Untitled Project"
    project_number: str = ""
    project_address: str = ""
    client_name: str = ""
    architect_name: str = ""
    architect_address: str = ""
    date: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            'project_name': self.project_name,
            'project_number': self.project_number,
            'project_address': self.project_address,
            'client_name': self.client_name,
            'architect_name': self.architect_name,
            'architect_address': self.architect_address,
            'date': self.date,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TitleBlockInfo':
        return cls(**data)


@dataclass
class DrawingSet:
    """Complete set of drawings for a project."""
    prefix: str = "A-"                              # Number prefix (user customizable)
    sheets: Dict[str, SheetConfig] = field(default_factory=dict)
    title_block: TitleBlockInfo = field(default_factory=TitleBlockInfo)
    default_scale: str = "1:100"
    auto_regenerate: bool = True

    def get_sheet(self, sheet_id: str) -> Optional[SheetConfig]:
        """Get a sheet by ID."""
        return self.sheets.get(sheet_id)

    def get_sheets_by_category(self, category: str) -> List[SheetConfig]:
        """Get all sheets in a category."""
        return [s for s in self.sheets.values() if s.category == category]

    def get_sheets_by_type(self, sheet_type: SheetType) -> List[SheetConfig]:
        """Get all sheets of a specific type."""
        return [s for s in self.sheets.values() if s.sheet_type == sheet_type]

    def generate_number(self, sheet_type: SheetType) -> str:
        """Generate a drawing number for a new sheet."""
        defaults = SHEET_DEFAULTS.get(sheet_type, {})
        category = defaults.get('category', 'Other')
        cat_prefix = CATEGORY_PREFIXES.get(category, '9')
        suffix = defaults.get('number_suffix', '01')
        return f"{self.prefix}{cat_prefix}{suffix}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            'prefix': self.prefix,
            'sheets': {k: v.to_dict() for k, v in self.sheets.items()},
            'title_block': self.title_block.to_dict(),
            'default_scale': self.default_scale,
            'auto_regenerate': self.auto_regenerate,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DrawingSet':
        return cls(
            prefix=data.get('prefix', 'A-'),
            sheets={k: SheetConfig.from_dict(v) for k, v in data.get('sheets', {}).items()},
            title_block=TitleBlockInfo.from_dict(data.get('title_block', {})),
            default_scale=data.get('default_scale', '1:100'),
            auto_regenerate=data.get('auto_regenerate', True),
        )

    @classmethod
    def create_default(cls, prefix: str = "A-") -> 'DrawingSet':
        """Create a default drawing set with standard sheets."""
        drawing_set = cls(prefix=prefix)

        # Create default sheets (only non-preset types)
        for sheet_type in SheetType:
            # Skip preset types for default set
            if sheet_type.value.startswith('preset_'):
                continue
            defaults = SHEET_DEFAULTS.get(sheet_type, {})
            sheet_id = sheet_type.value
            sheet = SheetConfig(
                id=sheet_id,
                sheet_type=sheet_type,
                title=defaults.get('title', sheet_type.value),
                number=drawing_set.generate_number(sheet_type),
                scale=drawing_set.default_scale,
            )
            drawing_set.sheets[sheet_id] = sheet

        return drawing_set
