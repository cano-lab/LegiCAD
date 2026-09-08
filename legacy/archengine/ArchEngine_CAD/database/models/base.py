"""
Base model and common mixins for SQLAlchemy models.
"""
from datetime import datetime
from typing import Any
from sqlalchemy import Column, Integer, DateTime, Boolean, event
from sqlalchemy.orm import declarative_base, declared_attr

Base = declarative_base()


class TimestampMixin:
    """
    Mixin providing created_at and updated_at timestamps.

    Also provides soft delete support via deleted_at.
    """

    @declared_attr
    def created_at(cls):
        return Column(DateTime, default=datetime.utcnow, nullable=False)

    @declared_attr
    def updated_at(cls):
        return Column(
            DateTime,
            default=datetime.utcnow,
            onupdate=datetime.utcnow,
            nullable=False
        )

    @declared_attr
    def deleted_at(cls):
        return Column(DateTime, nullable=True)

    @property
    def is_deleted(self) -> bool:
        """Check if this record has been soft-deleted."""
        return self.deleted_at is not None

    def soft_delete(self) -> None:
        """Mark this record as deleted."""
        self.deleted_at = datetime.utcnow()

    def restore(self) -> None:
        """Restore a soft-deleted record."""
        self.deleted_at = None


class SyncMixin:
    """
    Mixin for offline sync support.

    Provides:
    - sync_version: Optimistic locking version number
    - last_synced_at: When this record was last synced
    - is_dirty: Whether local changes are pending sync
    """

    @declared_attr
    def sync_version(cls):
        return Column(Integer, default=0, nullable=False)

    @declared_attr
    def last_synced_at(cls):
        return Column(DateTime, nullable=True)

    @declared_attr
    def is_dirty(cls):
        return Column(Boolean, default=False, nullable=False)

    def mark_dirty(self) -> None:
        """Mark this record as having local changes."""
        self.is_dirty = True

    def mark_synced(self) -> None:
        """Mark this record as synced with server."""
        self.is_dirty = False
        self.last_synced_at = datetime.utcnow()
        self.sync_version += 1

    def needs_sync(self) -> bool:
        """Check if this record needs to be synced."""
        return self.is_dirty


def generate_uuid():
    """Generate a new UUID for use as primary key."""
    import uuid
    return str(uuid.uuid4())
