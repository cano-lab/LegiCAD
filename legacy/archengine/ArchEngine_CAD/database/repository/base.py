"""
Base repository with generic CRUD operations.
"""
from typing import TypeVar, Generic, List, Optional, Type, Dict, Any
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from database.models.base import Base

T = TypeVar("T", bound=Base)


class BaseRepository(Generic[T]):
    """
    Generic repository providing CRUD operations.

    Subclass this for entity-specific repositories.
    """

    def __init__(self, model: Type[T], session: Session):
        """
        Initialize repository with model class and session.

        Args:
            model: SQLAlchemy model class
            session: Database session
        """
        self.model = model
        self.session = session

    def get(self, id: str) -> Optional[T]:
        """Get entity by ID."""
        return self.session.get(self.model, id)

    def get_all(
        self,
        skip: int = 0,
        limit: int = 100,
        include_deleted: bool = False
    ) -> List[T]:
        """
        Get all entities with pagination.

        Args:
            skip: Number of records to skip
            limit: Maximum records to return
            include_deleted: Include soft-deleted records
        """
        query = self.session.query(self.model)

        if hasattr(self.model, 'deleted_at') and not include_deleted:
            query = query.filter(self.model.deleted_at.is_(None))

        return query.offset(skip).limit(limit).all()

    def create(self, entity: T) -> T:
        """Create a new entity."""
        self.session.add(entity)
        self.session.flush()
        self.session.refresh(entity)
        return entity

    def create_many(self, entities: List[T]) -> List[T]:
        """Create multiple entities."""
        self.session.add_all(entities)
        self.session.flush()
        for entity in entities:
            self.session.refresh(entity)
        return entities

    def update(self, entity: T, data: Dict[str, Any]) -> T:
        """
        Update an entity with new data.

        Args:
            entity: Entity to update
            data: Dictionary of field updates
        """
        for key, value in data.items():
            if hasattr(entity, key):
                setattr(entity, key, value)

        if hasattr(entity, 'mark_dirty'):
            entity.mark_dirty()

        self.session.flush()
        self.session.refresh(entity)
        return entity

    def delete(self, entity: T) -> bool:
        """
        Delete an entity (hard delete).

        Returns True if deleted.
        """
        self.session.delete(entity)
        self.session.flush()
        return True

    def soft_delete(self, entity: T) -> bool:
        """
        Soft delete an entity.

        Returns True if deleted.
        """
        if hasattr(entity, 'soft_delete'):
            entity.soft_delete()
            self.session.flush()
            return True
        return self.delete(entity)

    def restore(self, entity: T) -> bool:
        """
        Restore a soft-deleted entity.

        Returns True if restored.
        """
        if hasattr(entity, 'restore'):
            entity.restore()
            self.session.flush()
            return True
        return False

    def commit(self) -> None:
        """Commit the current transaction."""
        self.session.commit()

    def rollback(self) -> None:
        """Rollback the current transaction."""
        self.session.rollback()


class AsyncBaseRepository(Generic[T]):
    """
    Async version of base repository for FastAPI.
    """

    def __init__(self, model: Type[T], session: AsyncSession):
        self.model = model
        self.session = session

    async def get(self, id: str) -> Optional[T]:
        """Get entity by ID."""
        result = await self.session.get(self.model, id)
        return result

    async def get_all(
        self,
        skip: int = 0,
        limit: int = 100,
        include_deleted: bool = False
    ) -> List[T]:
        """Get all entities with pagination."""
        stmt = select(self.model)

        if hasattr(self.model, 'deleted_at') and not include_deleted:
            stmt = stmt.where(self.model.deleted_at.is_(None))

        stmt = stmt.offset(skip).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, entity: T) -> T:
        """Create a new entity."""
        self.session.add(entity)
        await self.session.flush()
        await self.session.refresh(entity)
        return entity

    async def create_many(self, entities: List[T]) -> List[T]:
        """Create multiple entities."""
        self.session.add_all(entities)
        await self.session.flush()
        for entity in entities:
            await self.session.refresh(entity)
        return entities

    async def update(self, entity: T, data: Dict[str, Any]) -> T:
        """Update an entity with new data."""
        for key, value in data.items():
            if hasattr(entity, key):
                setattr(entity, key, value)

        if hasattr(entity, 'mark_dirty'):
            entity.mark_dirty()

        await self.session.flush()
        await self.session.refresh(entity)
        return entity

    async def delete(self, entity: T) -> bool:
        """Delete an entity (hard delete)."""
        await self.session.delete(entity)
        await self.session.flush()
        return True

    async def soft_delete(self, entity: T) -> bool:
        """Soft delete an entity."""
        if hasattr(entity, 'soft_delete'):
            entity.soft_delete()
            await self.session.flush()
            return True
        return await self.delete(entity)

    async def commit(self) -> None:
        """Commit the current transaction."""
        await self.session.commit()

    async def rollback(self) -> None:
        """Rollback the current transaction."""
        await self.session.rollback()
