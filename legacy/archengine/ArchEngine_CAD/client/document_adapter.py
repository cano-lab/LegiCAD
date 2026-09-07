"""
API Document Adapter - Bridge between ArchDocument and API backend.

Wraps the existing ArchDocument to provide transparent API backend
support while maintaining full backward compatibility.
"""
import os
from typing import Optional, Dict, List, Any
from pathlib import Path
import logging

from PyQt6.QtCore import QObject, pyqtSignal, QTimer

from core.document import ArchDocument
from client.api_client import ArchEngineAPIClient
from client.sync_client import OfflineSyncManager

logger = logging.getLogger(__name__)


class APIDocumentAdapter(QObject):
    """
    Adapter that wraps ArchDocument to add API backend support.

    This adapter:
    - Proxies all ArchDocument methods and properties
    - Tracks changes for batch sync
    - Uses API backend when available, falls back to local
    - Maintains full backward compatibility

    Usage:
        # Instead of:
        doc = ArchDocument()

        # Use:
        doc = APIDocumentAdapter()  # or APIDocumentAdapter(use_api=True)

        # All existing code works unchanged:
        doc.load(path)
        doc.modify_wall(0, start=(0, 0, 0))
        doc.save()
    """

    # Re-export ArchDocument signals
    document_changed = pyqtSignal()
    element_added = pyqtSignal(str, str)
    element_modified = pyqtSignal(str, str)
    element_removed = pyqtSignal(str, str)
    element_pinned = pyqtSignal(str, str, bool)

    # Additional signals
    sync_started = pyqtSignal()
    sync_completed = pyqtSignal(dict)  # {synced: int, failed: int}
    sync_failed = pyqtSignal(str)  # error message
    connection_changed = pyqtSignal(bool)  # is_connected

    def __init__(
        self,
        parent=None,
        use_api: Optional[bool] = None,
        workspace_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ):
        """
        Initialize the adapter.

        Args:
            parent: Qt parent object
            use_api: Enable API backend. If None, checks ARCHENGINE_USE_API_BACKEND env var
            workspace_id: Workspace ID for API operations
            project_id: Project ID for API operations (if loading existing)
        """
        super().__init__(parent)

        # Configuration
        self._use_api = use_api if use_api is not None else (
            os.environ.get("ARCHENGINE_USE_API_BACKEND", "").lower() == "true"
        )
        self._workspace_id = workspace_id
        self._project_id = project_id

        # Wrapped document
        self._document = ArchDocument(self)

        # API components
        self._api_client: Optional[ArchEngineAPIClient] = None
        self._sync_manager: Optional[OfflineSyncManager] = None

        # Change tracking for batch sync
        self._pending_changes: List[Dict] = []
        self._auto_sync_enabled = False
        self._sync_timer: Optional[QTimer] = None
        self._is_connected = False

        # Connect document signals
        self._connect_document_signals()

        # Initialize API if enabled
        if self._use_api:
            self._init_api()

    def _connect_document_signals(self):
        """Forward document signals."""
        self._document.document_changed.connect(self.document_changed.emit)
        self._document.element_added.connect(self._on_element_added)
        self._document.element_modified.connect(self._on_element_modified)
        self._document.element_removed.connect(self._on_element_removed)
        self._document.element_pinned.connect(self.element_pinned.emit)

    def _init_api(self):
        """Initialize API client and sync manager."""
        try:
            self._api_client = ArchEngineAPIClient()
            self._sync_manager = OfflineSyncManager()

            # Check connection
            self._is_connected = self._api_client.is_available()
            self.connection_changed.emit(self._is_connected)

            # Set up auto-sync timer (sync every 30 seconds if changes pending)
            self._sync_timer = QTimer(self)
            self._sync_timer.timeout.connect(self._auto_sync)
            self._sync_timer.setInterval(30000)

        except Exception as e:
            logger.error(f"Failed to initialize API: {e}")
            self._use_api = False

    # =========================================================================
    # Property Proxies
    # =========================================================================

    @property
    def file_path(self) -> Optional[Path]:
        """Get current file path."""
        return self._document.file_path

    @property
    def modified(self) -> bool:
        """Check if document has unsaved changes."""
        return self._document.modified

    @property
    def undo_stack(self):
        """Get undo stack."""
        return self._document.undo_stack

    @property
    def data(self) -> Dict[str, Any]:
        """Get raw JSON data."""
        return self._document.data

    @property
    def walls(self):
        """Get parsed walls."""
        return self._document.walls

    @property
    def doors(self):
        """Get parsed doors."""
        return self._document.doors

    @property
    def windows(self):
        """Get parsed windows."""
        return self._document.windows

    @property
    def rooms(self):
        """Get parsed rooms."""
        return self._document.rooms

    @property
    def wall_types(self):
        """Get parsed wall types."""
        return self._document.wall_types

    @property
    def building_width(self) -> float:
        """Get building width."""
        return self._document.building_width

    @property
    def building_depth(self) -> float:
        """Get building depth."""
        return self._document.building_depth

    # =========================================================================
    # File I/O with API Support
    # =========================================================================

    def new(self):
        """Create a new empty document."""
        self._document.new()
        self._pending_changes.clear()
        self._project_id = None

    def load(self, file_path: Path) -> bool:
        """
        Load document from file or API.

        If API is enabled and a project_id is set, loads from API.
        Otherwise loads from local file.
        """
        # Try API first if enabled and we have a project ID
        if self._use_api and self._project_id and self._is_connected:
            try:
                data = self._api_client.export_project(self._project_id)
                self._document.load_from_dict(data)

                # Cache locally
                if self._sync_manager:
                    self._sync_manager.cache_project(
                        self._project_id,
                        self._workspace_id or "default",
                        data,
                    )

                return True
            except Exception as e:
                logger.warning(f"API load failed, trying local: {e}")

        # Try local cache if offline
        if self._use_api and self._project_id and self._sync_manager:
            cached = self._sync_manager.get_cached_project(self._project_id)
            if cached:
                self._document.load_from_dict(cached)
                return True

        # Fall back to local file
        return self._document.load(file_path)

    def load_from_api(self, project_id: str, workspace_id: str = "default") -> bool:
        """
        Load a project directly from the API.

        Args:
            project_id: Project ID to load
            workspace_id: Workspace ID

        Returns:
            True if successful
        """
        if not self._use_api:
            raise RuntimeError("API backend not enabled")

        self._project_id = project_id
        self._workspace_id = workspace_id

        if self._is_connected:
            try:
                data = self._api_client.export_project(project_id)
                self._document.load_from_dict(data)

                # Cache locally
                if self._sync_manager:
                    self._sync_manager.cache_project(
                        project_id,
                        workspace_id,
                        data,
                    )

                return True
            except Exception as e:
                logger.error(f"Failed to load from API: {e}")

        # Try local cache
        if self._sync_manager:
            cached = self._sync_manager.get_cached_project(project_id)
            if cached:
                self._document.load_from_dict(cached)
                return True

        return False

    def save(self, file_path: Optional[Path] = None) -> bool:
        """
        Save document to file and/or API.

        If API is enabled, syncs changes to server.
        Always saves to local file as backup.
        """
        # Save locally first
        success = self._document.save(file_path)

        # Sync to API if enabled
        if success and self._use_api and self._project_id:
            self._sync_to_api()

        return success

    def save_to_api(self) -> bool:
        """
        Save/sync document to API.

        Creates a new project if no project_id is set.
        """
        if not self._use_api:
            raise RuntimeError("API backend not enabled")

        if not self._workspace_id:
            raise ValueError("workspace_id required for API save")

        data = self._document.to_dict()

        try:
            if self._project_id:
                # Update existing project
                self._api_client.update_project(
                    self._project_id,
                    {
                        "name": data.get("name", "Untitled"),
                        "building_type": data.get("building_type", "residential"),
                        "width": data.get("width", 10000),
                        "depth": data.get("depth", 10000),
                        "qbd_answers": data.get("qbd_answers", {}),
                        "settings": data.get("settings", {}),
                    }
                )

                # Sync building elements
                self._sync_pending_changes()

            else:
                # Create new project
                result = self._api_client.import_project(
                    self._workspace_id,
                    data,
                )
                self._project_id = result["id"]

            # Update cache
            if self._sync_manager:
                self._sync_manager.cache_project(
                    self._project_id,
                    self._workspace_id,
                    data,
                )

            return True

        except Exception as e:
            logger.error(f"Failed to save to API: {e}")
            self.sync_failed.emit(str(e))
            return False

    # =========================================================================
    # Method Proxies
    # =========================================================================

    def to_dict(self) -> Dict[str, Any]:
        """Export document data as dictionary."""
        return self._document.to_dict()

    def to_json(self) -> Dict[str, Any]:
        """Alias for to_dict()."""
        return self._document.to_json()

    def load_from_dict(self, data: Dict[str, Any]):
        """Load document from dictionary."""
        self._document.load_from_dict(data)
        self._pending_changes.clear()

    def get_data(self) -> Dict[str, Any]:
        """Get current document data."""
        return self._document.get_data()

    def get_project_info(self) -> Dict:
        """Get project information."""
        return self._document.get_project_info()

    def get_wall_type(self, type_id: str):
        """Get wall type by ID."""
        return self._document.get_wall_type(type_id)

    def get_wall_types(self):
        """Get available wall types."""
        return self._document.get_wall_types()

    def get_element(self, element_type: str, element_id: str):
        """Get element by type and ID."""
        return self._document.get_element(element_type, element_id)

    def get_walls_at_point(self, x: float, z: float, tolerance: float = 50):
        """Find walls near a point."""
        return self._document.get_walls_at_point(x, z, tolerance)

    def get_geometry_query(self):
        """Get ArchGeometry QueryAPI."""
        return self._document.get_geometry_query()

    def validate_with_archgeometry(self):
        """Validate document with archgeometry."""
        return self._document.validate_with_archgeometry()

    # =========================================================================
    # Modification Methods (with change tracking)
    # =========================================================================

    def set_modified(self, modified: bool = True):
        """Set modified flag."""
        self._document.set_modified(modified)

    def modify_wall(self, index: int, **changes):
        """Modify a wall's properties."""
        self._document.modify_wall(index, **changes)
        self._track_change("update", "wall", str(index), changes)

    def modify_wall_undoable(self, index: int, **changes):
        """Modify a wall with undo support."""
        self._document.modify_wall_undoable(index, **changes)
        self._track_change("update", "wall", str(index), changes)

    def move_wall_undoable(self, index: int, grip_type: str,
                           old_start: tuple, old_end: tuple,
                           new_start: tuple, new_end: tuple):
        """Move a wall with undo support."""
        self._document.move_wall_undoable(
            index, grip_type, old_start, old_end, new_start, new_end
        )
        self._track_change("update", "wall", str(index), {
            "start": new_start,
            "end": new_end,
        })

    def add_wall_undoable(self, wall_data: Dict) -> int:
        """Add a wall with undo support."""
        index = self._document.add_wall_undoable(wall_data)
        self._track_change("create", "wall", str(index), wall_data)
        return index

    def delete_wall_undoable(self, index: int):
        """Delete a wall with undo support."""
        self._document.delete_wall_undoable(index)
        self._track_change("delete", "wall", str(index), {})

    def modify_door(self, index: int, **changes):
        """Modify a door's properties."""
        self._document.modify_door(index, **changes)
        self._track_change("update", "door", str(index), changes)

    def modify_door_undoable(self, index: int, **changes):
        """Modify a door with undo support."""
        self._document.modify_door_undoable(index, **changes)
        self._track_change("update", "door", str(index), changes)

    def add_door_undoable(self, door_data: Dict) -> int:
        """Add a door with undo support."""
        index = self._document.add_door_undoable(door_data)
        self._track_change("create", "door", str(index), door_data)
        return index

    def delete_door_undoable(self, door_index: int):
        """Delete a door with undo support."""
        self._document.delete_door_undoable(door_index)
        self._track_change("delete", "door", str(door_index), {})

    def modify_window(self, index: int, **changes):
        """Modify a window's properties."""
        self._document.modify_window(index, **changes)
        self._track_change("update", "window", str(index), changes)

    def modify_window_undoable(self, index: int, **changes):
        """Modify a window with undo support."""
        self._document.modify_window_undoable(index, **changes)
        self._track_change("update", "window", str(index), changes)

    def add_window_undoable(self, window_data: Dict) -> int:
        """Add a window with undo support."""
        index = self._document.add_window_undoable(window_data)
        self._track_change("create", "window", str(index), window_data)
        return index

    def delete_window_undoable(self, window_index: int):
        """Delete a window with undo support."""
        self._document.delete_window_undoable(window_index)
        self._track_change("delete", "window", str(window_index), {})

    def add_room_undoable(self, room_data: Dict) -> str:
        """Add a room with undo support."""
        room_id = self._document.add_room_undoable(room_data)
        self._track_change("create", "room", room_id, room_data)
        return room_id

    def delete_room_undoable(self, room_id: str):
        """Delete a room with undo support."""
        self._document.delete_room_undoable(room_id)
        self._track_change("delete", "room", room_id, {})

    # =========================================================================
    # Constraint System
    # =========================================================================

    def pin_element(self, element_type: str, element_id: str, pinned: bool = True):
        """Pin or unpin an element."""
        self._document.pin_element(element_type, element_id, pinned)

    def lock_property(self, element_type: str, element_id: str, property_name: str):
        """Lock a property."""
        self._document.lock_property(element_type, element_id, property_name)

    def unlock_property(self, element_type: str, element_id: str, property_name: str):
        """Unlock a property."""
        self._document.unlock_property(element_type, element_id, property_name)

    def get_pinned_elements(self):
        """Get all pinned elements."""
        return self._document.get_pinned_elements()

    def is_property_locked(self, element_type: str, element_id: str, property_name: str) -> bool:
        """Check if a property is locked."""
        return self._document.is_property_locked(element_type, element_id, property_name)

    # =========================================================================
    # Version History
    # =========================================================================

    def get_history(self) -> List[Dict]:
        """Get version history."""
        if self._use_api and self._project_id and self._is_connected:
            try:
                return self._api_client.list_versions(self._project_id)
            except Exception as e:
                logger.warning(f"Failed to get API history: {e}")

        return self._document.get_history()

    def create_version(self, message: str = "") -> bool:
        """Create a version snapshot."""
        if self._use_api and self._project_id and self._is_connected:
            try:
                self._api_client.create_version(self._project_id, message)
                return True
            except Exception as e:
                logger.error(f"Failed to create version: {e}")
                return False

        return False

    def revert_to_version(self, version: Any) -> bool:
        """Revert to a previous version."""
        if self._use_api and self._project_id and self._is_connected:
            try:
                if isinstance(version, int):
                    data = self._api_client.get_version(self._project_id, version)
                    self._document.load_from_dict(data)
                    return True
            except Exception as e:
                logger.error(f"Failed to revert: {e}")
                return False

        # Fall back to git-based versioning
        if isinstance(version, str):
            return self._document.revert_to_version(version)

        return False

    # =========================================================================
    # Change Tracking and Sync
    # =========================================================================

    def _track_change(
        self,
        operation: str,
        entity_type: str,
        entity_id: str,
        data: Dict,
    ):
        """Track a change for sync."""
        if not self._use_api:
            return

        change = {
            "op": operation,
            "type": entity_type,
            "id": entity_id if operation != "create" else None,
            "data": data,
        }

        self._pending_changes.append(change)

        # Queue for offline sync
        if self._sync_manager and self._project_id:
            self._sync_manager.queue_change(
                operation,
                entity_type,
                entity_id,
                self._project_id,
                data,
            )

        # Start auto-sync timer if enabled
        if self._auto_sync_enabled and self._sync_timer:
            if not self._sync_timer.isActive():
                self._sync_timer.start()

    def _on_element_added(self, element_type: str, element_id: str):
        """Handle element added signal."""
        self.element_added.emit(element_type, element_id)

    def _on_element_modified(self, element_type: str, element_id: str):
        """Handle element modified signal."""
        self.element_modified.emit(element_type, element_id)

    def _on_element_removed(self, element_type: str, element_id: str):
        """Handle element removed signal."""
        self.element_removed.emit(element_type, element_id)

    def _sync_to_api(self):
        """Sync current state to API."""
        if not self._is_connected:
            return

        self.sync_started.emit()

        try:
            self._sync_pending_changes()
            self.sync_completed.emit({"synced": len(self._pending_changes), "failed": 0})
            self._pending_changes.clear()
        except Exception as e:
            self.sync_failed.emit(str(e))

    def _sync_pending_changes(self):
        """Sync pending changes to API."""
        if not self._pending_changes or not self._project_id:
            return

        if self._is_connected:
            try:
                result = self._api_client.batch_operations(
                    self._project_id,
                    self._pending_changes,
                )
                logger.info(f"Synced {result.get('created', 0)} created, "
                           f"{result.get('updated', 0)} updated, "
                           f"{result.get('deleted', 0)} deleted")
            except Exception as e:
                logger.error(f"Batch sync failed: {e}")
                raise

    def _auto_sync(self):
        """Auto-sync timer callback."""
        if self._pending_changes and self._is_connected:
            self._sync_to_api()

    # =========================================================================
    # Connection Management
    # =========================================================================

    def check_connection(self) -> bool:
        """Check and update API connection status."""
        if not self._api_client:
            return False

        was_connected = self._is_connected
        self._is_connected = self._api_client.is_available()

        if self._is_connected != was_connected:
            self.connection_changed.emit(self._is_connected)

            # If just reconnected, sync pending changes
            if self._is_connected and self._pending_changes:
                self._sync_to_api()

        return self._is_connected

    @property
    def is_connected(self) -> bool:
        """Check if connected to API."""
        return self._is_connected

    @property
    def use_api(self) -> bool:
        """Check if API backend is enabled."""
        return self._use_api

    @property
    def project_id(self) -> Optional[str]:
        """Get current project ID."""
        return self._project_id

    @property
    def workspace_id(self) -> Optional[str]:
        """Get current workspace ID."""
        return self._workspace_id

    def set_auto_sync(self, enabled: bool, interval_ms: int = 30000):
        """Enable or disable auto-sync."""
        self._auto_sync_enabled = enabled

        if self._sync_timer:
            self._sync_timer.setInterval(interval_ms)
            if enabled and self._pending_changes:
                self._sync_timer.start()
            else:
                self._sync_timer.stop()

    def get_pending_changes_count(self) -> int:
        """Get number of pending changes to sync."""
        return len(self._pending_changes)

    def force_sync(self) -> bool:
        """Force immediate sync of all pending changes."""
        if not self._use_api:
            return True

        if not self.check_connection():
            return False

        try:
            self._sync_to_api()
            return True
        except Exception:
            return False

    # =========================================================================
    # LLM Integration
    # =========================================================================

    def apply_llm_changes(self, new_json: Dict[str, Any]) -> Dict[str, Any]:
        """
        Apply changes from LLM-generated JSON.

        Compares the new JSON with current state and applies only the
        differences, providing efficient updates while allowing the LLM
        to work with familiar full JSON structures.

        Args:
            new_json: The modified JSON from the LLM

        Returns:
            Dict with keys:
                - diff: The DiffResult object
                - applied: Number of changes applied
                - failed: Number of changes that failed
                - errors: List of error details
                - summary: Human-readable summary

        Example:
            # LLM modifies the building JSON
            new_json = llm_modify_building(current_json, user_prompt)

            # Apply only the changes
            result = document.apply_llm_changes(new_json)
            print(result["summary"])  # "5 changes: walls: +2 ~1 -0, doors: +1 ~0 -1"
        """
        from client.json_diff import JSONDiffer, ChangeApplicator
        import asyncio

        # Get current state
        old_json = self.get_data()

        # Find differences
        differ = JSONDiffer()
        diff = differ.diff(old_json, new_json)

        if not diff.has_changes:
            return {
                "diff": diff,
                "applied": 0,
                "failed": 0,
                "errors": [],
                "summary": "No changes detected",
            }

        # Apply changes via API or locally
        if self._use_api and self._project_id and self._is_connected:
            # Apply via API for proper transactions
            applicator = ChangeApplicator(self._api_client, self._project_id)

            loop = asyncio.new_event_loop()
            try:
                apply_result = loop.run_until_complete(applicator.apply(diff))
            finally:
                loop.close()

            # Refresh local document from API
            if apply_result["applied"] > 0:
                self._load_from_api()
        else:
            # Apply locally to the document
            apply_result = self._apply_changes_locally(diff, new_json)

        return {
            "diff": diff,
            "applied": apply_result["applied"],
            "failed": apply_result["failed"],
            "errors": apply_result.get("errors", []),
            "summary": diff.summary(),
        }

    def _apply_changes_locally(self, diff, new_json: Dict[str, Any]) -> Dict[str, Any]:
        """Apply changes directly to the local document."""
        from client.json_diff import ChangeType

        applied = 0
        failed = 0
        errors = []

        for change in diff.changes:
            try:
                if change.element_type == "project":
                    # Update project-level properties
                    for key, value in change.data.items():
                        if hasattr(self._document, key):
                            setattr(self._document, key, value)
                        elif hasattr(self._document, '_data'):
                            self._document._data[key] = value
                    applied += 1

                elif change.element_type == "wall":
                    if change.change_type == ChangeType.ADD:
                        self._document.add_wall(change.data)
                    elif change.change_type == ChangeType.UPDATE:
                        self._document.modify_wall(change.index, **change.data)
                    elif change.change_type == ChangeType.DELETE:
                        self._document.delete_wall(change.index)
                    applied += 1

                elif change.element_type == "door":
                    if change.change_type == ChangeType.ADD:
                        self._document.add_door(change.data)
                    elif change.change_type == ChangeType.DELETE:
                        # Find and delete door by wall_index + offset
                        doors = self._document.get_doors()
                        for i, d in enumerate(doors):
                            if (d.get("wall_index") == change.data.get("wall_index") and
                                d.get("offset") == change.data.get("offset")):
                                self._document.delete_door(i)
                                break
                    applied += 1

                elif change.element_type == "window":
                    if change.change_type == ChangeType.ADD:
                        self._document.add_window(change.data)
                    elif change.change_type == ChangeType.DELETE:
                        windows = self._document.get_windows()
                        for i, w in enumerate(windows):
                            if (w.get("wall_index") == change.data.get("wall_index") and
                                w.get("offset") == change.data.get("offset")):
                                self._document.delete_window(i)
                                break
                    applied += 1

                elif change.element_type == "room":
                    if change.change_type == ChangeType.ADD:
                        room_data = change.data.copy()
                        room_data["key"] = change.element_id
                        self._document.add_room(room_data)
                    elif change.change_type == ChangeType.DELETE:
                        self._document.delete_room(change.element_id)
                    applied += 1

            except Exception as e:
                failed += 1
                errors.append({
                    "change": f"{change.change_type.value} {change.element_type}",
                    "error": str(e)
                })

        self._document.set_modified(True)
        self.document_changed.emit()

        return {"applied": applied, "failed": failed, "errors": errors}

    def get_json_for_llm(self) -> Dict[str, Any]:
        """
        Get current building JSON formatted for LLM editing.

        Returns the same format used by text_to_json and schema_modifier,
        suitable for sending to an LLM for modification.

        Returns:
            Dict containing the full building structure
        """
        return self.get_data()

    # =========================================================================
    # Cleanup
    # =========================================================================

    def close(self):
        """Clean up resources."""
        if self._sync_timer:
            self._sync_timer.stop()

        if self._api_client:
            self._api_client.close()

        if self._sync_manager:
            self._sync_manager.close()

    def __del__(self):
        """Destructor."""
        self.close()
