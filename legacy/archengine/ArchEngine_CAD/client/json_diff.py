"""
JSON Diff Helper for LLM-generated changes.

Compares old and new JSON structures and applies only the changes via API,
allowing LLMs to work with familiar JSON while getting database efficiency.
"""
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum


class ChangeType(Enum):
    """Type of change detected."""
    ADD = "add"
    UPDATE = "update"
    DELETE = "delete"


@dataclass
class Change:
    """Represents a single change to an element."""
    change_type: ChangeType
    element_type: str  # "wall", "door", "window", "room", etc.
    element_id: Optional[str] = None  # For updates/deletes
    index: Optional[int] = None  # For walls (legacy index)
    data: Optional[Dict[str, Any]] = None  # For adds/updates
    old_data: Optional[Dict[str, Any]] = None  # For context


@dataclass
class DiffResult:
    """Result of comparing two JSON structures."""
    changes: List[Change] = field(default_factory=list)

    # Summary counts
    walls_added: int = 0
    walls_updated: int = 0
    walls_deleted: int = 0
    doors_added: int = 0
    doors_updated: int = 0
    doors_deleted: int = 0
    windows_added: int = 0
    windows_updated: int = 0
    windows_deleted: int = 0
    rooms_added: int = 0
    rooms_updated: int = 0
    rooms_deleted: int = 0
    roofs_added: int = 0
    roofs_updated: int = 0
    roofs_deleted: int = 0
    project_updated: bool = False

    @property
    def has_changes(self) -> bool:
        """Check if any changes were detected."""
        return len(self.changes) > 0

    @property
    def total_changes(self) -> int:
        """Total number of changes."""
        return len(self.changes)

    def summary(self) -> str:
        """Get human-readable summary of changes."""
        if not self.has_changes:
            return "No changes detected"

        parts = []
        if self.project_updated:
            parts.append("project settings updated")
        if self.walls_added or self.walls_updated or self.walls_deleted:
            parts.append(f"walls: +{self.walls_added} ~{self.walls_updated} -{self.walls_deleted}")
        if self.doors_added or self.doors_updated or self.doors_deleted:
            parts.append(f"doors: +{self.doors_added} ~{self.doors_updated} -{self.doors_deleted}")
        if self.windows_added or self.windows_updated or self.windows_deleted:
            parts.append(f"windows: +{self.windows_added} ~{self.windows_updated} -{self.windows_deleted}")
        if self.rooms_added or self.rooms_updated or self.rooms_deleted:
            parts.append(f"rooms: +{self.rooms_added} ~{self.rooms_updated} -{self.rooms_deleted}")
        if self.roofs_added or self.roofs_updated or self.roofs_deleted:
            parts.append(f"roofs: +{self.roofs_added} ~{self.roofs_updated} -{self.roofs_deleted}")

        return f"{self.total_changes} changes: " + ", ".join(parts)


class JSONDiffer:
    """
    Compares two building JSON structures and identifies changes.

    Usage:
        differ = JSONDiffer()
        result = differ.diff(old_json, new_json)
        print(result.summary())
        for change in result.changes:
            print(f"{change.change_type.value} {change.element_type}")
    """

    # Fields that identify if a wall has meaningfully changed
    WALL_COMPARE_FIELDS = ["start", "end", "height", "category", "wall_type", "is_pinned"]

    # Fields for door comparison
    DOOR_COMPARE_FIELDS = ["wall_index", "offset", "width", "height", "door_type", "swing"]

    # Fields for window comparison
    WINDOW_COMPARE_FIELDS = ["wall_index", "offset", "width", "height", "sill_height"]

    # Fields for room comparison
    ROOM_COMPARE_FIELDS = ["name", "type", "bounds", "area"]

    # Fields for roof comparison
    ROOF_COMPARE_FIELDS = ["type", "pitch", "surfaces"]

    # Project-level fields
    PROJECT_COMPARE_FIELDS = ["name", "width", "depth", "stories", "wall_height", "building_type"]

    def diff(self, old_json: Dict[str, Any], new_json: Dict[str, Any]) -> DiffResult:
        """
        Compare two building JSON structures.

        Args:
            old_json: The original JSON structure
            new_json: The modified JSON structure (e.g., from LLM)

        Returns:
            DiffResult containing all detected changes
        """
        result = DiffResult()

        # Compare project-level fields
        self._diff_project(old_json, new_json, result)

        # Compare walls
        self._diff_walls(
            old_json.get("walls_batch", []),
            new_json.get("walls_batch", []),
            result
        )

        # Compare doors
        self._diff_doors(
            old_json.get("doors", []),
            new_json.get("doors", []),
            result
        )

        # Compare windows
        self._diff_windows(
            old_json.get("windows", []),
            new_json.get("windows", []),
            result
        )

        # Compare rooms
        self._diff_rooms(
            old_json.get("rooms", {}),
            new_json.get("rooms", {}),
            result
        )

        # Compare roofs
        self._diff_roofs(
            old_json.get("roofs", []),
            new_json.get("roofs", []),
            result
        )

        return result

    def _diff_project(
        self,
        old_json: Dict[str, Any],
        new_json: Dict[str, Any],
        result: DiffResult
    ):
        """Check for project-level changes."""
        changes = {}
        for field in self.PROJECT_COMPARE_FIELDS:
            old_val = old_json.get(field)
            new_val = new_json.get(field)
            if old_val != new_val and new_val is not None:
                changes[field] = new_val

        if changes:
            result.project_updated = True
            result.changes.append(Change(
                change_type=ChangeType.UPDATE,
                element_type="project",
                data=changes,
                old_data={f: old_json.get(f) for f in changes.keys()}
            ))

    def _diff_walls(
        self,
        old_walls: List[Dict],
        new_walls: List[Dict],
        result: DiffResult
    ):
        """Compare wall lists."""
        # Index walls by their index field (or position)
        old_by_index = {w.get("index", i): w for i, w in enumerate(old_walls)}
        new_by_index = {w.get("index", i): w for i, w in enumerate(new_walls)}

        old_indices = set(old_by_index.keys())
        new_indices = set(new_by_index.keys())

        # Deleted walls
        for idx in old_indices - new_indices:
            result.walls_deleted += 1
            result.changes.append(Change(
                change_type=ChangeType.DELETE,
                element_type="wall",
                index=idx,
                old_data=old_by_index[idx]
            ))

        # Added walls
        for idx in new_indices - old_indices:
            result.walls_added += 1
            result.changes.append(Change(
                change_type=ChangeType.ADD,
                element_type="wall",
                index=idx,
                data=new_by_index[idx]
            ))

        # Updated walls
        for idx in old_indices & new_indices:
            if self._wall_changed(old_by_index[idx], new_by_index[idx]):
                result.walls_updated += 1
                result.changes.append(Change(
                    change_type=ChangeType.UPDATE,
                    element_type="wall",
                    index=idx,
                    data=new_by_index[idx],
                    old_data=old_by_index[idx]
                ))

    def _wall_changed(self, old: Dict, new: Dict) -> bool:
        """Check if a wall has meaningfully changed."""
        for field in self.WALL_COMPARE_FIELDS:
            if old.get(field) != new.get(field):
                return True
        return False

    def _diff_doors(
        self,
        old_doors: List[Dict],
        new_doors: List[Dict],
        result: DiffResult
    ):
        """Compare door lists."""
        # Match doors by wall_index + offset (unique position)
        def door_key(d: Dict) -> Tuple:
            return (d.get("wall_index"), d.get("offset"))

        old_by_key = {door_key(d): d for d in old_doors}
        new_by_key = {door_key(d): d for d in new_doors}

        old_keys = set(old_by_key.keys())
        new_keys = set(new_by_key.keys())

        # Deleted doors
        for key in old_keys - new_keys:
            result.doors_deleted += 1
            result.changes.append(Change(
                change_type=ChangeType.DELETE,
                element_type="door",
                data={"wall_index": key[0], "offset": key[1]},
                old_data=old_by_key[key]
            ))

        # Added doors
        for key in new_keys - old_keys:
            result.doors_added += 1
            result.changes.append(Change(
                change_type=ChangeType.ADD,
                element_type="door",
                data=new_by_key[key]
            ))

        # Updated doors
        for key in old_keys & new_keys:
            if self._element_changed(old_by_key[key], new_by_key[key], self.DOOR_COMPARE_FIELDS):
                result.doors_updated += 1
                result.changes.append(Change(
                    change_type=ChangeType.UPDATE,
                    element_type="door",
                    data=new_by_key[key],
                    old_data=old_by_key[key]
                ))

    def _diff_windows(
        self,
        old_windows: List[Dict],
        new_windows: List[Dict],
        result: DiffResult
    ):
        """Compare window lists."""
        # Match windows by wall_index + offset
        def window_key(w: Dict) -> Tuple:
            return (w.get("wall_index"), w.get("offset"))

        old_by_key = {window_key(w): w for w in old_windows}
        new_by_key = {window_key(w): w for w in new_windows}

        old_keys = set(old_by_key.keys())
        new_keys = set(new_by_key.keys())

        # Deleted windows
        for key in old_keys - new_keys:
            result.windows_deleted += 1
            result.changes.append(Change(
                change_type=ChangeType.DELETE,
                element_type="window",
                data={"wall_index": key[0], "offset": key[1]},
                old_data=old_by_key[key]
            ))

        # Added windows
        for key in new_keys - old_keys:
            result.windows_added += 1
            result.changes.append(Change(
                change_type=ChangeType.ADD,
                element_type="window",
                data=new_by_key[key]
            ))

        # Updated windows
        for key in old_keys & new_keys:
            if self._element_changed(old_by_key[key], new_by_key[key], self.WINDOW_COMPARE_FIELDS):
                result.windows_updated += 1
                result.changes.append(Change(
                    change_type=ChangeType.UPDATE,
                    element_type="window",
                    data=new_by_key[key],
                    old_data=old_by_key[key]
                ))

    def _diff_rooms(
        self,
        old_rooms: Dict[str, Dict],
        new_rooms: Dict[str, Dict],
        result: DiffResult
    ):
        """Compare room dictionaries."""
        old_keys = set(old_rooms.keys())
        new_keys = set(new_rooms.keys())

        # Deleted rooms
        for key in old_keys - new_keys:
            result.rooms_deleted += 1
            result.changes.append(Change(
                change_type=ChangeType.DELETE,
                element_type="room",
                element_id=key,
                old_data=old_rooms[key]
            ))

        # Added rooms
        for key in new_keys - old_keys:
            result.rooms_added += 1
            result.changes.append(Change(
                change_type=ChangeType.ADD,
                element_type="room",
                element_id=key,
                data=new_rooms[key]
            ))

        # Updated rooms
        for key in old_keys & new_keys:
            if self._element_changed(old_rooms[key], new_rooms[key], self.ROOM_COMPARE_FIELDS):
                result.rooms_updated += 1
                result.changes.append(Change(
                    change_type=ChangeType.UPDATE,
                    element_type="room",
                    element_id=key,
                    data=new_rooms[key],
                    old_data=old_rooms[key]
                ))

    def _diff_roofs(
        self,
        old_roofs: List[Dict],
        new_roofs: List[Dict],
        result: DiffResult
    ):
        """Compare roof lists."""
        # Match roofs by index (usually just one roof)
        old_by_idx = {i: r for i, r in enumerate(old_roofs)}
        new_by_idx = {i: r for i, r in enumerate(new_roofs)}

        old_indices = set(old_by_idx.keys())
        new_indices = set(new_by_idx.keys())

        # Deleted roofs
        for idx in old_indices - new_indices:
            result.roofs_deleted += 1
            result.changes.append(Change(
                change_type=ChangeType.DELETE,
                element_type="roof",
                index=idx,
                old_data=old_by_idx[idx]
            ))

        # Added roofs
        for idx in new_indices - old_indices:
            result.roofs_added += 1
            result.changes.append(Change(
                change_type=ChangeType.ADD,
                element_type="roof",
                index=idx,
                data=new_by_idx[idx]
            ))

        # Updated roofs
        for idx in old_indices & new_indices:
            if self._element_changed(old_by_idx[idx], new_by_idx[idx], self.ROOF_COMPARE_FIELDS):
                result.roofs_updated += 1
                result.changes.append(Change(
                    change_type=ChangeType.UPDATE,
                    element_type="roof",
                    index=idx,
                    data=new_by_idx[idx],
                    old_data=old_by_idx[idx]
                ))

    def _element_changed(self, old: Dict, new: Dict, fields: List[str]) -> bool:
        """Check if an element has changed based on specified fields."""
        for field in fields:
            if old.get(field) != new.get(field):
                return True
        return False


class ChangeApplicator:
    """
    Applies detected changes via the API.

    Usage:
        applicator = ChangeApplicator(api_client, project_id)
        results = await applicator.apply(diff_result)
    """

    def __init__(self, api_client, project_id: str):
        """
        Initialize the applicator.

        Args:
            api_client: The APIClient instance
            project_id: The project to apply changes to
        """
        self.api = api_client
        self.project_id = project_id

    async def apply(self, diff: DiffResult) -> Dict[str, Any]:
        """
        Apply all changes from a diff result.

        Args:
            diff: The DiffResult from JSONDiffer.diff()

        Returns:
            Summary of applied changes with any errors
        """
        results = {
            "applied": 0,
            "failed": 0,
            "errors": []
        }

        for change in diff.changes:
            try:
                await self._apply_change(change)
                results["applied"] += 1
            except Exception as e:
                results["failed"] += 1
                results["errors"].append({
                    "change": f"{change.change_type.value} {change.element_type}",
                    "error": str(e)
                })

        return results

    async def _apply_change(self, change: Change):
        """Apply a single change."""
        element_type = change.element_type
        change_type = change.change_type

        if element_type == "project":
            await self._apply_project_change(change)
        elif element_type == "wall":
            await self._apply_wall_change(change)
        elif element_type == "door":
            await self._apply_door_change(change)
        elif element_type == "window":
            await self._apply_window_change(change)
        elif element_type == "room":
            await self._apply_room_change(change)
        elif element_type == "roof":
            await self._apply_roof_change(change)

    async def _apply_project_change(self, change: Change):
        """Apply project-level update."""
        await self.api.update_project(self.project_id, change.data)

    async def _apply_wall_change(self, change: Change):
        """Apply wall add/update/delete."""
        if change.change_type == ChangeType.ADD:
            await self.api.create_wall(self.project_id, change.data)
        elif change.change_type == ChangeType.UPDATE:
            # Need to find wall by index first
            walls = await self.api.list_walls(self.project_id)
            wall = next((w for w in walls if w.get("index") == change.index), None)
            if wall:
                await self.api.update_wall(self.project_id, wall["id"], change.data)
        elif change.change_type == ChangeType.DELETE:
            walls = await self.api.list_walls(self.project_id)
            wall = next((w for w in walls if w.get("index") == change.index), None)
            if wall:
                await self.api.delete_wall(self.project_id, wall["id"])

    async def _apply_door_change(self, change: Change):
        """Apply door add/update/delete."""
        if change.change_type == ChangeType.ADD:
            await self.api.create_door(self.project_id, change.data)
        elif change.change_type == ChangeType.UPDATE:
            # Find door by wall_index + offset
            doors = await self.api.list_doors(self.project_id)
            door = next((d for d in doors
                        if d.get("wall_index") == change.old_data.get("wall_index")
                        and d.get("offset") == change.old_data.get("offset")), None)
            if door:
                await self.api.update_door(self.project_id, door["id"], change.data)
        elif change.change_type == ChangeType.DELETE:
            doors = await self.api.list_doors(self.project_id)
            door = next((d for d in doors
                        if d.get("wall_index") == change.data.get("wall_index")
                        and d.get("offset") == change.data.get("offset")), None)
            if door:
                await self.api.delete_door(self.project_id, door["id"])

    async def _apply_window_change(self, change: Change):
        """Apply window add/update/delete."""
        if change.change_type == ChangeType.ADD:
            await self.api.create_window(self.project_id, change.data)
        elif change.change_type == ChangeType.UPDATE:
            windows = await self.api.list_windows(self.project_id)
            window = next((w for w in windows
                          if w.get("wall_index") == change.old_data.get("wall_index")
                          and w.get("offset") == change.old_data.get("offset")), None)
            if window:
                await self.api.update_window(self.project_id, window["id"], change.data)
        elif change.change_type == ChangeType.DELETE:
            windows = await self.api.list_windows(self.project_id)
            window = next((w for w in windows
                          if w.get("wall_index") == change.data.get("wall_index")
                          and w.get("offset") == change.data.get("offset")), None)
            if window:
                await self.api.delete_window(self.project_id, window["id"])

    async def _apply_room_change(self, change: Change):
        """Apply room add/update/delete."""
        if change.change_type == ChangeType.ADD:
            room_data = change.data.copy()
            room_data["room_key"] = change.element_id
            await self.api.create_room(self.project_id, room_data)
        elif change.change_type == ChangeType.UPDATE:
            rooms = await self.api.list_rooms(self.project_id)
            room = next((r for r in rooms if r.get("room_key") == change.element_id), None)
            if room:
                await self.api.update_room(self.project_id, room["id"], change.data)
        elif change.change_type == ChangeType.DELETE:
            rooms = await self.api.list_rooms(self.project_id)
            room = next((r for r in rooms if r.get("room_key") == change.element_id), None)
            if room:
                await self.api.delete_room(self.project_id, room["id"])

    async def _apply_roof_change(self, change: Change):
        """Apply roof add/update/delete."""
        if change.change_type == ChangeType.ADD:
            await self.api.create_roof(self.project_id, change.data)
        elif change.change_type == ChangeType.UPDATE:
            roofs = await self.api.list_roofs(self.project_id)
            if change.index < len(roofs):
                await self.api.update_roof(self.project_id, roofs[change.index]["id"], change.data)
        elif change.change_type == ChangeType.DELETE:
            roofs = await self.api.list_roofs(self.project_id)
            if change.index < len(roofs):
                await self.api.delete_roof(self.project_id, roofs[change.index]["id"])


def diff_and_apply_sync(
    api_client,
    project_id: str,
    old_json: Dict[str, Any],
    new_json: Dict[str, Any]
) -> Tuple[DiffResult, Dict[str, Any]]:
    """
    Synchronous convenience function for diffing and applying changes.

    Args:
        api_client: The APIClient instance
        project_id: The project to update
        old_json: Original building JSON
        new_json: Modified building JSON (from LLM)

    Returns:
        Tuple of (DiffResult, apply_results)
    """
    import asyncio

    differ = JSONDiffer()
    diff = differ.diff(old_json, new_json)

    if not diff.has_changes:
        return diff, {"applied": 0, "failed": 0, "errors": []}

    applicator = ChangeApplicator(api_client, project_id)

    # Run async apply in sync context
    loop = asyncio.new_event_loop()
    try:
        results = loop.run_until_complete(applicator.apply(diff))
    finally:
        loop.close()

    return diff, results
