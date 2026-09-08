"""
Client module for ArchEngine CAD API.

Provides HTTP client, offline sync, document adapter, and JSON diff utilities.
"""
from client.api_client import ArchEngineAPIClient
from client.sync_client import OfflineSyncManager
from client.document_adapter import APIDocumentAdapter
from client.json_diff import (
    JSONDiffer,
    ChangeApplicator,
    DiffResult,
    Change,
    ChangeType,
    diff_and_apply_sync,
)

__all__ = [
    "ArchEngineAPIClient",
    "OfflineSyncManager",
    "APIDocumentAdapter",
    "JSONDiffer",
    "ChangeApplicator",
    "DiffResult",
    "Change",
    "ChangeType",
    "diff_and_apply_sync",
]
