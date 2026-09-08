"""
Offline sync manager for ArchEngine CAD.

Maintains a local SQLite cache and queues changes for sync
when the server becomes available.
"""
import os
import json
import sqlite3
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class SyncStatus(Enum):
    """Sync operation status."""
    PENDING = "pending"
    SYNCING = "syncing"
    SYNCED = "synced"
    CONFLICT = "conflict"
    FAILED = "failed"


@dataclass
class ChangeRecord:
    """Record of a pending change."""
    id: int
    operation: str  # create, update, delete
    entity_type: str  # project, wall, door, etc.
    entity_id: str
    project_id: str
    data: Dict[str, Any]
    timestamp: datetime
    status: SyncStatus = SyncStatus.PENDING
    retries: int = 0
    error: Optional[str] = None


class OfflineSyncManager:
    """
    Manages offline data storage and synchronization.

    Features:
    - Local SQLite cache for offline work
    - Change queue for pending uploads
    - Conflict detection and resolution
    - Automatic sync when server available
    """

    def __init__(self, cache_dir: Optional[Path] = None):
        """
        Initialize sync manager.

        Args:
            cache_dir: Directory for cache database.
                      Defaults to ~/.archengine/cache
        """
        self.cache_dir = cache_dir or Path(
            os.environ.get(
                "ARCHENGINE_CACHE_DIR",
                Path.home() / ".archengine" / "cache"
            )
        )
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self._db_path = self.cache_dir / "sync_cache.db"
        self._conn: Optional[sqlite3.Connection] = None

        self._init_database()

    def _init_database(self):
        """Initialize the cache database."""
        self._conn = sqlite3.connect(
            str(self._db_path),
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row

        # Create tables
        self._conn.executescript("""
            -- Cached projects (full JSON snapshots)
            CREATE TABLE IF NOT EXISTS cached_projects (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                data TEXT NOT NULL,
                sync_version INTEGER DEFAULT 0,
                cached_at TEXT NOT NULL,
                synced_at TEXT
            );

            -- Change queue for pending sync
            CREATE TABLE IF NOT EXISTS change_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                operation TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                data TEXT,
                timestamp TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                retries INTEGER DEFAULT 0,
                error TEXT
            );

            -- Sync metadata
            CREATE TABLE IF NOT EXISTS sync_meta (
                key TEXT PRIMARY KEY,
                value TEXT
            );

            -- Index for faster queries
            CREATE INDEX IF NOT EXISTS idx_change_queue_status
                ON change_queue(status);
            CREATE INDEX IF NOT EXISTS idx_change_queue_project
                ON change_queue(project_id);
        """)
        self._conn.commit()

    def close(self):
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    # --- Cache Operations ---

    def cache_project(
        self,
        project_id: str,
        workspace_id: str,
        data: Dict[str, Any],
        sync_version: int = 0,
    ):
        """
        Cache a project locally.

        Args:
            project_id: Project ID
            workspace_id: Workspace ID
            data: Full project data (legacy JSON format)
            sync_version: Server sync version
        """
        now = datetime.utcnow().isoformat()

        self._conn.execute("""
            INSERT OR REPLACE INTO cached_projects
            (id, workspace_id, data, sync_version, cached_at, synced_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            project_id,
            workspace_id,
            json.dumps(data),
            sync_version,
            now,
            now,
        ))
        self._conn.commit()

    def get_cached_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        """Get a cached project by ID."""
        cursor = self._conn.execute(
            "SELECT data FROM cached_projects WHERE id = ?",
            (project_id,)
        )
        row = cursor.fetchone()

        if row:
            return json.loads(row["data"])
        return None

    def get_cached_projects(
        self,
        workspace_id: str,
    ) -> List[Dict[str, Any]]:
        """Get all cached projects for a workspace."""
        cursor = self._conn.execute(
            "SELECT id, data, sync_version, cached_at FROM cached_projects WHERE workspace_id = ?",
            (workspace_id,)
        )

        projects = []
        for row in cursor:
            data = json.loads(row["data"])
            data["_cache_meta"] = {
                "sync_version": row["sync_version"],
                "cached_at": row["cached_at"],
            }
            projects.append(data)

        return projects

    def update_cached_project(
        self,
        project_id: str,
        data: Dict[str, Any],
    ):
        """Update a cached project (for local changes)."""
        now = datetime.utcnow().isoformat()

        self._conn.execute("""
            UPDATE cached_projects
            SET data = ?, cached_at = ?
            WHERE id = ?
        """, (json.dumps(data), now, project_id))
        self._conn.commit()

    def delete_cached_project(self, project_id: str):
        """Remove a project from cache."""
        self._conn.execute(
            "DELETE FROM cached_projects WHERE id = ?",
            (project_id,)
        )
        self._conn.commit()

    # --- Change Queue ---

    def queue_change(
        self,
        operation: str,
        entity_type: str,
        entity_id: str,
        project_id: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> int:
        """
        Queue a change for sync.

        Args:
            operation: create, update, or delete
            entity_type: project, wall, door, window, room
            entity_id: Entity ID
            project_id: Project ID
            data: Change data (for create/update)

        Returns:
            Change record ID
        """
        now = datetime.utcnow().isoformat()

        cursor = self._conn.execute("""
            INSERT INTO change_queue
            (operation, entity_type, entity_id, project_id, data, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            operation,
            entity_type,
            entity_id,
            project_id,
            json.dumps(data) if data else None,
            now,
        ))
        self._conn.commit()

        return cursor.lastrowid

    def get_pending_changes(
        self,
        project_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[ChangeRecord]:
        """Get pending changes to sync."""
        if project_id:
            cursor = self._conn.execute("""
                SELECT * FROM change_queue
                WHERE status = 'pending' AND project_id = ?
                ORDER BY timestamp ASC
                LIMIT ?
            """, (project_id, limit))
        else:
            cursor = self._conn.execute("""
                SELECT * FROM change_queue
                WHERE status = 'pending'
                ORDER BY timestamp ASC
                LIMIT ?
            """, (limit,))

        return [self._row_to_change(row) for row in cursor]

    def mark_synced(self, change_id: int):
        """Mark a change as synced."""
        self._conn.execute("""
            UPDATE change_queue
            SET status = 'synced'
            WHERE id = ?
        """, (change_id,))
        self._conn.commit()

    def mark_failed(self, change_id: int, error: str):
        """Mark a change as failed."""
        self._conn.execute("""
            UPDATE change_queue
            SET status = 'failed', error = ?, retries = retries + 1
            WHERE id = ?
        """, (error, change_id))
        self._conn.commit()

    def mark_conflict(self, change_id: int, error: str):
        """Mark a change as having a conflict."""
        self._conn.execute("""
            UPDATE change_queue
            SET status = 'conflict', error = ?
            WHERE id = ?
        """, (error, change_id))
        self._conn.commit()

    def clear_synced(self):
        """Remove all synced changes from queue."""
        self._conn.execute(
            "DELETE FROM change_queue WHERE status = 'synced'"
        )
        self._conn.commit()

    def get_change_count(self, status: str = "pending") -> int:
        """Get count of changes by status."""
        cursor = self._conn.execute(
            "SELECT COUNT(*) FROM change_queue WHERE status = ?",
            (status,)
        )
        return cursor.fetchone()[0]

    def _row_to_change(self, row) -> ChangeRecord:
        """Convert database row to ChangeRecord."""
        return ChangeRecord(
            id=row["id"],
            operation=row["operation"],
            entity_type=row["entity_type"],
            entity_id=row["entity_id"],
            project_id=row["project_id"],
            data=json.loads(row["data"]) if row["data"] else {},
            timestamp=datetime.fromisoformat(row["timestamp"]),
            status=SyncStatus(row["status"]),
            retries=row["retries"],
            error=row["error"],
        )

    # --- Sync Operations ---

    def sync_project(
        self,
        project_id: str,
        client: "ArchEngineAPIClient",
    ) -> Dict[str, int]:
        """
        Sync a project with the server.

        Args:
            project_id: Project to sync
            client: API client instance

        Returns:
            Counts of synced/failed operations
        """
        from client.api_client import ArchEngineAPIClient

        results = {"synced": 0, "failed": 0, "conflicts": 0}

        # Get pending changes for this project
        changes = self.get_pending_changes(project_id=project_id)

        if not changes:
            return results

        # Group changes by entity type for batch operations
        batches: Dict[str, List[Dict]] = {}
        change_ids: Dict[str, List[int]] = {}

        for change in changes:
            key = change.entity_type
            if key not in batches:
                batches[key] = []
                change_ids[key] = []

            batches[key].append({
                "op": change.operation,
                "type": change.entity_type,
                "id": change.entity_id if change.operation != "create" else None,
                "data": change.data,
            })
            change_ids[key].append(change.id)

        # Execute batch operations
        all_ops = []
        all_ids = []
        for entity_type, ops in batches.items():
            all_ops.extend(ops)
            all_ids.extend(change_ids[entity_type])

        try:
            result = client.batch_operations(project_id, all_ops)

            # Mark all as synced
            for change_id in all_ids:
                self.mark_synced(change_id)

            results["synced"] = result.get("created", 0) + result.get("updated", 0) + result.get("deleted", 0)

        except Exception as e:
            logger.error(f"Sync failed: {e}")
            for change_id in all_ids:
                self.mark_failed(change_id, str(e))
            results["failed"] = len(all_ids)

        return results

    def full_sync(
        self,
        workspace_id: str,
        client: "ArchEngineAPIClient",
    ) -> Dict[str, Any]:
        """
        Perform full sync for a workspace.

        Downloads latest from server, uploads pending changes.
        """
        results = {
            "downloaded": 0,
            "uploaded": 0,
            "conflicts": 0,
        }

        # Get all projects from server
        try:
            response = client.list_projects(workspace_id)
            server_projects = {p["id"]: p for p in response.get("items", [])}
        except Exception as e:
            logger.error(f"Failed to fetch projects: {e}")
            return results

        # Get cached projects
        cached = {p.get("id"): p for p in self.get_cached_projects(workspace_id)}

        # Sync each project
        for project_id, server_data in server_projects.items():
            if project_id not in cached:
                # New project from server - download
                try:
                    full_data = client.export_project(project_id)
                    self.cache_project(
                        project_id,
                        workspace_id,
                        full_data,
                        sync_version=server_data.get("sync_version", 0),
                    )
                    results["downloaded"] += 1
                except Exception as e:
                    logger.error(f"Failed to download project {project_id}: {e}")

        # Upload pending changes
        pending_count = self.get_change_count("pending")
        if pending_count > 0:
            for project_id in set(c.project_id for c in self.get_pending_changes()):
                sync_result = self.sync_project(project_id, client)
                results["uploaded"] += sync_result["synced"]
                results["conflicts"] += sync_result["conflicts"]

        return results

    # --- Metadata ---

    def set_meta(self, key: str, value: str):
        """Set sync metadata."""
        self._conn.execute("""
            INSERT OR REPLACE INTO sync_meta (key, value)
            VALUES (?, ?)
        """, (key, value))
        self._conn.commit()

    def get_meta(self, key: str) -> Optional[str]:
        """Get sync metadata."""
        cursor = self._conn.execute(
            "SELECT value FROM sync_meta WHERE key = ?",
            (key,)
        )
        row = cursor.fetchone()
        return row["value"] if row else None

    def get_last_sync(self) -> Optional[datetime]:
        """Get timestamp of last successful sync."""
        value = self.get_meta("last_sync")
        return datetime.fromisoformat(value) if value else None

    def set_last_sync(self):
        """Update last sync timestamp."""
        self.set_meta("last_sync", datetime.utcnow().isoformat())
