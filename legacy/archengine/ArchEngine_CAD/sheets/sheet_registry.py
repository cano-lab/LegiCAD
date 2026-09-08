"""
Sheet Registry - Central management for all drawing sheets.
Handles sheet lifecycle, numbering, and cross-references.
"""
from typing import Optional, List, Dict, Callable
from PyQt6.QtCore import QObject, pyqtSignal

from sheets.models import (
    SheetConfig, SheetType, DrawingSet, DrawingReference,
    TitleBlockInfo, SHEET_DEFAULTS, CATEGORY_PREFIXES
)


class SheetRegistry(QObject):
    """
    Central registry for managing all drawing sheets.
    Provides signals for UI updates and methods for sheet manipulation.
    """

    # Signals
    sheet_added = pyqtSignal(str)           # sheet_id
    sheet_removed = pyqtSignal(str)         # sheet_id
    sheet_updated = pyqtSignal(str)         # sheet_id
    sheet_content_changed = pyqtSignal(str) # sheet_id - SVG content updated
    prefix_changed = pyqtSignal(str)        # new prefix
    drawing_set_loaded = pyqtSignal()       # Full drawing set loaded/reset

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drawing_set = DrawingSet.create_default()
        self._generation_callbacks: Dict[SheetType, Callable] = {}

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def drawing_set(self) -> DrawingSet:
        """Get the current drawing set."""
        return self._drawing_set

    @property
    def prefix(self) -> str:
        """Get the drawing number prefix."""
        return self._drawing_set.prefix

    @prefix.setter
    def prefix(self, value: str):
        """Set the drawing number prefix and renumber all sheets."""
        if self._drawing_set.prefix != value:
            self._drawing_set.prefix = value
            self._renumber_all_sheets()
            self.prefix_changed.emit(value)

    @property
    def title_block(self) -> TitleBlockInfo:
        """Get title block info."""
        return self._drawing_set.title_block

    @title_block.setter
    def title_block(self, value: TitleBlockInfo):
        """Set title block info."""
        self._drawing_set.title_block = value
        # Notify all sheets need updating
        for sheet_id in self._drawing_set.sheets:
            self.sheet_updated.emit(sheet_id)

    @property
    def auto_regenerate(self) -> bool:
        """Get auto-regenerate setting."""
        return self._drawing_set.auto_regenerate

    @auto_regenerate.setter
    def auto_regenerate(self, value: bool):
        """Set auto-regenerate setting."""
        self._drawing_set.auto_regenerate = value

    @property
    def text_sizes(self) -> dict:
        """Get text size settings."""
        return getattr(self._drawing_set, '_text_sizes', {
            'dim_text_size': 300,
            'room_text_size': 500,
            'room_area_size': 350,
        })

    @text_sizes.setter
    def text_sizes(self, value: dict):
        """Set text size settings."""
        self._drawing_set._text_sizes = value

    @property
    def dimension_settings(self) -> dict:
        """Get dimension settings."""
        return getattr(self._drawing_set, '_dimension_settings', {
            'auto_exterior_walls': True,
            'auto_openings': True,
            'auto_rooms': True,
            'auto_heights': True,
            'unit': 'mm',
            'display_format': 'metric',
            'text_size': 300,
            'line_width': 3,
            'tick_length': 150,
            'offset_from_wall': 600,
            'chain_spacing': 400,
        })

    @dimension_settings.setter
    def dimension_settings(self, value: dict):
        """Set dimension settings."""
        self._drawing_set._dimension_settings = value

    # =========================================================================
    # Sheet Access
    # =========================================================================

    def get_sheet(self, sheet_id: str) -> Optional[SheetConfig]:
        """Get a sheet by ID."""
        return self._drawing_set.get_sheet(sheet_id)

    def get_all_sheets(self) -> List[SheetConfig]:
        """Get all sheets."""
        return list(self._drawing_set.sheets.values())

    def get_sheets_by_category(self, category: str) -> List[SheetConfig]:
        """Get all sheets in a category."""
        return self._drawing_set.get_sheets_by_category(category)

    def get_sheets_by_type(self, sheet_type: SheetType) -> List[SheetConfig]:
        """Get all sheets of a type."""
        return self._drawing_set.get_sheets_by_type(sheet_type)

    def get_enabled_sheets(self) -> List[SheetConfig]:
        """Get all sheets with auto-regenerate enabled."""
        return [s for s in self._drawing_set.sheets.values() if s.enabled]

    def get_categories(self) -> List[str]:
        """Get list of categories that have sheets."""
        categories = set()
        for sheet in self._drawing_set.sheets.values():
            categories.add(sheet.category)
        # Return in standard order
        order = ["Plans", "Elevations", "Sections", "Details", "Schedules", "Other"]
        return [c for c in order if c in categories]

    # =========================================================================
    # Sheet Management
    # =========================================================================

    def add_sheet(self, sheet_type: SheetType, title: Optional[str] = None) -> SheetConfig:
        """
        Add a new sheet of the given type.
        Returns the created sheet.
        """
        # Generate unique ID
        base_id = sheet_type.value
        sheet_id = base_id
        counter = 1
        while sheet_id in self._drawing_set.sheets:
            counter += 1
            sheet_id = f"{base_id}_{counter}"

        # Get defaults
        defaults = SHEET_DEFAULTS.get(sheet_type, {})

        # Create sheet
        sheet = SheetConfig(
            id=sheet_id,
            sheet_type=sheet_type,
            title=title or defaults.get('title', sheet_type.value),
            number=self._drawing_set.generate_number(sheet_type),
            scale=self._drawing_set.default_scale,
        )

        self._drawing_set.sheets[sheet_id] = sheet
        self.sheet_added.emit(sheet_id)
        return sheet

    def add_sheet_config(self, sheet: SheetConfig) -> SheetConfig:
        """
        Add a pre-configured sheet.
        Used for preset-based sheets with custom configurations.
        """
        # Ensure unique ID
        sheet_id = sheet.id
        counter = 1
        while sheet_id in self._drawing_set.sheets:
            counter += 1
            sheet_id = f"{sheet.sheet_type.value}_{counter}"

        sheet.id = sheet_id
        self._drawing_set.sheets[sheet_id] = sheet
        self.sheet_added.emit(sheet_id)
        return sheet

    def remove_sheet(self, sheet_id: str) -> bool:
        """
        Remove a sheet by ID.
        Also cleans up any references to/from this sheet.
        """
        if sheet_id not in self._drawing_set.sheets:
            return False

        # Clean up references
        self._remove_references_for_sheet(sheet_id)

        # Remove sheet
        del self._drawing_set.sheets[sheet_id]
        self.sheet_removed.emit(sheet_id)
        return True

    def update_sheet(self, sheet_id: str, **kwargs) -> bool:
        """
        Update sheet properties.
        Accepts keyword arguments matching SheetConfig fields.
        """
        sheet = self.get_sheet(sheet_id)
        if not sheet:
            return False

        for key, value in kwargs.items():
            if hasattr(sheet, key) and key not in ('id', 'sheet_type'):
                setattr(sheet, key, value)

        self.sheet_updated.emit(sheet_id)
        return True

    def set_sheet_content(self, sheet_id: str, svg_content: str):
        """
        Update a sheet's SVG content.
        Called after generation.
        """
        from datetime import datetime

        sheet = self.get_sheet(sheet_id)
        if sheet:
            sheet.svg_content = svg_content
            sheet.last_generated = datetime.now()
            self.sheet_content_changed.emit(sheet_id)

    def clear_sheet_content(self, sheet_id: str):
        """Clear a sheet's SVG content."""
        sheet = self.get_sheet(sheet_id)
        if sheet:
            sheet.svg_content = None
            sheet.last_generated = None
            self.sheet_content_changed.emit(sheet_id)

    # =========================================================================
    # Numbering
    # =========================================================================

    def set_prefix(self, prefix: str):
        """Set the drawing number prefix and renumber all sheets."""
        self.prefix = prefix  # Uses property setter

    def renumber_sheet(self, sheet_id: str, new_number: str) -> bool:
        """Manually set a sheet's drawing number."""
        sheet = self.get_sheet(sheet_id)
        if not sheet:
            return False

        sheet.number = new_number
        self.sheet_updated.emit(sheet_id)
        return True

    def _renumber_all_sheets(self):
        """Renumber all sheets with current prefix."""
        for sheet in self._drawing_set.sheets.values():
            sheet.number = self._drawing_set.generate_number(sheet.sheet_type)
            self.sheet_updated.emit(sheet.id)

    # =========================================================================
    # Cross-References
    # =========================================================================

    def add_reference(
        self,
        source_sheet_id: str,
        target_sheet_id: str,
        marker_type: str,
        marker_id: str,
        position: tuple
    ) -> Optional[DrawingReference]:
        """
        Add a cross-reference between sheets.
        For example, a section marker on floor plan pointing to section sheet.
        """
        source_sheet = self.get_sheet(source_sheet_id)
        target_sheet = self.get_sheet(target_sheet_id)

        if not source_sheet or not target_sheet:
            return None

        reference = DrawingReference(
            source_sheet_id=source_sheet_id,
            target_sheet_id=target_sheet_id,
            marker_type=marker_type,
            marker_id=marker_id,
            position=position,
        )

        source_sheet.references_out.append(reference)
        target_sheet.references_in.append(reference)

        self.sheet_updated.emit(source_sheet_id)
        self.sheet_updated.emit(target_sheet_id)

        return reference

    def remove_reference(self, source_sheet_id: str, marker_id: str) -> bool:
        """Remove a reference by source sheet and marker ID."""
        source_sheet = self.get_sheet(source_sheet_id)
        if not source_sheet:
            return False

        # Find and remove the reference
        for ref in source_sheet.references_out[:]:
            if ref.marker_id == marker_id:
                source_sheet.references_out.remove(ref)

                # Also remove from target
                target_sheet = self.get_sheet(ref.target_sheet_id)
                if target_sheet:
                    target_sheet.references_in = [
                        r for r in target_sheet.references_in
                        if not (r.source_sheet_id == source_sheet_id and r.marker_id == marker_id)
                    ]
                    self.sheet_updated.emit(ref.target_sheet_id)

                self.sheet_updated.emit(source_sheet_id)
                return True

        return False

    def get_references_for_sheet(self, sheet_id: str) -> Dict[str, List[DrawingReference]]:
        """
        Get all references for a sheet.
        Returns dict with 'outgoing' and 'incoming' lists.
        """
        sheet = self.get_sheet(sheet_id)
        if not sheet:
            return {'outgoing': [], 'incoming': []}

        return {
            'outgoing': sheet.references_out,
            'incoming': sheet.references_in,
        }

    def _remove_references_for_sheet(self, sheet_id: str):
        """Remove all references to and from a sheet."""
        sheet = self.get_sheet(sheet_id)
        if not sheet:
            return

        # Remove outgoing references from target sheets
        for ref in sheet.references_out:
            target = self.get_sheet(ref.target_sheet_id)
            if target:
                target.references_in = [
                    r for r in target.references_in
                    if r.source_sheet_id != sheet_id
                ]

        # Remove incoming references from source sheets
        for ref in sheet.references_in:
            source = self.get_sheet(ref.source_sheet_id)
            if source:
                source.references_out = [
                    r for r in source.references_out
                    if r.target_sheet_id != sheet_id
                ]

    # =========================================================================
    # Serialization
    # =========================================================================

    def to_dict(self) -> dict:
        """Serialize registry state to dict."""
        return self._drawing_set.to_dict()

    def from_dict(self, data: dict):
        """Load registry state from dict."""
        self._drawing_set = DrawingSet.from_dict(data)
        self.drawing_set_loaded.emit()

    def reset(self, prefix: str = "A-"):
        """Reset to default drawing set."""
        self._drawing_set = DrawingSet.create_default(prefix)
        self.drawing_set_loaded.emit()

    # =========================================================================
    # Generation Callbacks
    # =========================================================================

    def register_generator(self, sheet_type: SheetType, callback: Callable):
        """
        Register a generation callback for a sheet type.
        Callback signature: callback(sheet: SheetConfig, document_data: dict) -> str (SVG)
        """
        self._generation_callbacks[sheet_type] = callback

    def get_generator(self, sheet_type: SheetType) -> Optional[Callable]:
        """Get the registered generator for a sheet type."""
        return self._generation_callbacks.get(sheet_type)

    def has_generator(self, sheet_type: SheetType) -> bool:
        """Check if a generator is registered for a sheet type."""
        return sheet_type in self._generation_callbacks
