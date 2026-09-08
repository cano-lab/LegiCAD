"""
Generator Service - Manages in-process SVG generation for drawing sheets.

Provides:
- Automatic regeneration when document changes
- Manual generation trigger
- Progress reporting via signals
"""
from typing import Dict, Any, Optional, List
from PyQt6.QtCore import QObject, pyqtSignal, QTimer

from sheets.models import SheetType, SheetConfig
from sheets.sheet_registry import SheetRegistry
from generators.generator_adapters import get_adapter_for_sheet_type, GeneratorResult


class GeneratorService(QObject):
    """
    Service for generating drawing sheets from document data.

    Handles both automatic and manual regeneration, with progress reporting.
    """

    # Signals
    generation_started = pyqtSignal(str)      # sheet_id
    generation_completed = pyqtSignal(str)    # sheet_id
    generation_failed = pyqtSignal(str, str)  # sheet_id, error_message
    all_generation_started = pyqtSignal()
    all_generation_completed = pyqtSignal()
    progress_updated = pyqtSignal(int, int)   # current, total

    def __init__(
        self,
        registry: SheetRegistry,
        get_document_data: callable,
        parent=None
    ):
        """
        Initialize the generator service.

        Args:
            registry: Sheet registry for managing sheets
            get_document_data: Callable returning document data dict
            parent: Parent QObject
        """
        super().__init__(parent)
        self._registry = registry
        self._get_document_data = get_document_data

        # Auto-regeneration timer (debounce rapid changes)
        self._auto_regen_timer = QTimer(self)
        self._auto_regen_timer.setSingleShot(True)
        self._auto_regen_timer.setInterval(500)  # 500ms debounce
        self._auto_regen_timer.timeout.connect(self._do_auto_regenerate)

        # Pending sheets for regeneration
        self._pending_sheets: List[str] = []

        # Currently generating flag
        self._is_generating = False

    # =========================================================================
    # Public API
    # =========================================================================

    def generate_sheet(self, sheet_id: str) -> bool:
        """
        Generate a single sheet.

        Args:
            sheet_id: ID of sheet to generate

        Returns:
            True if generation started, False if sheet not found
        """
        sheet = self._registry.get_sheet(sheet_id)
        if not sheet:
            return False

        self._generate_single(sheet)
        return True

    def generate_all(self):
        """Generate all enabled sheets."""
        sheets = self._registry.get_enabled_sheets()
        if not sheets:
            return

        self.all_generation_started.emit()
        self._is_generating = True

        total = len(sheets)
        for i, sheet in enumerate(sheets):
            self.progress_updated.emit(i, total)
            self._generate_single(sheet)

        self.progress_updated.emit(total, total)
        self._is_generating = False
        self.all_generation_completed.emit()

    def generate_by_type(self, sheet_type: SheetType):
        """Generate all sheets of a specific type."""
        sheets = self._registry.get_sheets_by_type(sheet_type)
        for sheet in sheets:
            if sheet.enabled:
                self._generate_single(sheet)

    def schedule_regeneration(self, sheet_ids: Optional[List[str]] = None):
        """
        Schedule sheets for regeneration (debounced).

        Args:
            sheet_ids: Specific sheets to regenerate, or None for all enabled
        """
        if not self._registry.auto_regenerate:
            return

        if sheet_ids:
            # Add to pending list
            for sheet_id in sheet_ids:
                if sheet_id not in self._pending_sheets:
                    self._pending_sheets.append(sheet_id)
        else:
            # Schedule all enabled sheets
            self._pending_sheets = [s.id for s in self._registry.get_enabled_sheets()]

        # Restart debounce timer
        self._auto_regen_timer.start()

    def cancel_pending(self):
        """Cancel any pending regeneration."""
        self._auto_regen_timer.stop()
        self._pending_sheets.clear()

    # =========================================================================
    # Internal Methods
    # =========================================================================

    def _generate_single(self, sheet: SheetConfig):
        """Generate a single sheet."""
        self.generation_started.emit(sheet.id)

        # Get adapter for sheet type
        adapter = get_adapter_for_sheet_type(sheet.sheet_type)
        if not adapter:
            error = f"No generator available for {sheet.sheet_type.value}"
            self.generation_failed.emit(sheet.id, error)
            return

        # Get document data
        try:
            data = self._get_document_data()
        except Exception as e:
            self.generation_failed.emit(sheet.id, f"Failed to get document data: {e}")
            return

        # Add text size settings to data
        text_sizes = self._registry.text_sizes
        data.update(text_sizes)

        # Generate SVG
        result: GeneratorResult = adapter.generate(data, sheet)

        if result.success and result.svg_content:
            self._registry.set_sheet_content(sheet.id, result.svg_content)
            self.generation_completed.emit(sheet.id)
        else:
            error = result.error_message or "Unknown generation error"
            self.generation_failed.emit(sheet.id, error)

    def _do_auto_regenerate(self):
        """Execute pending auto-regeneration."""
        if not self._pending_sheets:
            return

        if self._is_generating:
            # Already generating, reschedule
            self._auto_regen_timer.start()
            return

        sheets_to_generate = self._pending_sheets[:]
        self._pending_sheets.clear()

        self._is_generating = True
        self.all_generation_started.emit()

        total = len(sheets_to_generate)
        for i, sheet_id in enumerate(sheets_to_generate):
            self.progress_updated.emit(i, total)
            sheet = self._registry.get_sheet(sheet_id)
            if sheet and sheet.enabled:
                self._generate_single(sheet)

        self.progress_updated.emit(total, total)
        self._is_generating = False
        self.all_generation_completed.emit()

    # =========================================================================
    # Connection Helpers
    # =========================================================================

    def connect_to_document(self, document):
        """
        Connect to document signals for auto-regeneration.

        Args:
            document: ArchDocument instance
        """
        # Connect to document change signals
        document.document_changed.connect(
            lambda: self.schedule_regeneration()
        )
        document.element_modified.connect(
            lambda t, i: self.schedule_regeneration()
        )
        document.element_added.connect(
            lambda t, i: self.schedule_regeneration()
        )
        document.element_removed.connect(
            lambda t, i: self.schedule_regeneration()
        )
