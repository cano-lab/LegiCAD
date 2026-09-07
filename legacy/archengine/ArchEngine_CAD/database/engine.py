"""
Database engine and session management.

Supports both SQLite (development/local) and PostgreSQL (production).
"""
import os
from pathlib import Path
from typing import Optional, AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from database.models.base import Base

# Default database path
DEFAULT_DB_PATH = Path.home() / ".archengine" / "archengine.db"

# Global engine and session factory
_engine = None
_async_engine = None
_SessionLocal = None
_AsyncSessionLocal = None


def get_database_url(async_mode: bool = False) -> str:
    """
    Get database URL from environment or use default SQLite.

    Environment variables:
    - ARCHENGINE_DATABASE_URL: Full database URL
    - ARCHENGINE_DB_PATH: Path to SQLite file (for SQLite only)
    """
    url = os.environ.get("ARCHENGINE_DATABASE_URL")

    if url:
        if async_mode and url.startswith("sqlite:"):
            # Convert to async SQLite URL
            return url.replace("sqlite:", "sqlite+aiosqlite:")
        elif async_mode and url.startswith("postgresql:"):
            return url.replace("postgresql:", "postgresql+asyncpg:")
        return url

    # Default to SQLite
    db_path = os.environ.get("ARCHENGINE_DB_PATH", str(DEFAULT_DB_PATH))
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    if async_mode:
        return f"sqlite+aiosqlite:///{db_path}"
    return f"sqlite:///{db_path}"


def get_engine(echo: bool = False):
    """
    Get or create the synchronous database engine.

    Args:
        echo: If True, log all SQL statements
    """
    global _engine

    if _engine is None:
        url = get_database_url(async_mode=False)
        _engine = create_engine(
            url,
            echo=echo,
            pool_pre_ping=True,  # Check connection validity
        )

        # SQLite specific settings
        if url.startswith("sqlite"):
            @event.listens_for(_engine, "connect")
            def set_sqlite_pragma(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                try:
                    cursor.execute("PRAGMA foreign_keys=ON")
                except Exception:
                    pass
                # WAL mode can fail on Windows when a file watcher (OneDrive,
                # antivirus, indexing) holds the .db file. Don't let that
                # crash connection setup — fall back to default journal mode.
                try:
                    cursor.execute("PRAGMA journal_mode=WAL")
                except Exception:
                    pass
                cursor.close()

    return _engine


def get_async_engine(echo: bool = False):
    """Get or create the async database engine."""
    global _async_engine

    if _async_engine is None:
        url = get_database_url(async_mode=True)
        _async_engine = create_async_engine(
            url,
            echo=echo,
            pool_pre_ping=True,
        )

    return _async_engine


def get_session_factory() -> sessionmaker:
    """Get the synchronous session factory."""
    global _SessionLocal

    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=get_engine(),
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
        )

    return _SessionLocal


def get_async_session_factory() -> async_sessionmaker:
    """Get the async session factory."""
    global _AsyncSessionLocal

    if _AsyncSessionLocal is None:
        _AsyncSessionLocal = async_sessionmaker(
            bind=get_async_engine(),
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
            class_=AsyncSession,
        )

    return _AsyncSessionLocal


def get_session() -> Session:
    """
    Get a new database session (synchronous).

    Usage:
        session = get_session()
        try:
            # ... use session
            session.commit()
        finally:
            session.close()
    """
    SessionLocal = get_session_factory()
    return SessionLocal()


@asynccontextmanager
async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Get an async database session as context manager.

    Usage:
        async with get_async_session() as session:
            # ... use session
            await session.commit()
    """
    AsyncSessionLocal = get_async_session_factory()
    session = AsyncSessionLocal()
    try:
        yield session
    finally:
        await session.close()


def init_db(echo: bool = False) -> None:
    """
    Initialize the database, creating all tables.

    Call this on application startup.
    """
    engine = get_engine(echo=echo)
    Base.metadata.create_all(bind=engine)


async def init_db_async(echo: bool = False) -> None:
    """Initialize database asynchronously."""
    engine = get_async_engine(echo=echo)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def close_db() -> None:
    """
    Close database connections.

    Call this on application shutdown.
    """
    global _engine, _async_engine, _SessionLocal, _AsyncSessionLocal

    if _engine:
        _engine.dispose()
        _engine = None

    if _async_engine:
        # Note: For async engine, use close_db_async()
        pass

    _SessionLocal = None
    _AsyncSessionLocal = None


async def close_db_async() -> None:
    """Close async database connections."""
    global _async_engine, _AsyncSessionLocal

    if _async_engine:
        await _async_engine.dispose()
        _async_engine = None

    _AsyncSessionLocal = None


# Dependency for FastAPI
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency for database sessions.

    Usage in routes:
        @router.get("/items")
        async def get_items(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with get_async_session() as session:
        yield session


# Context manager for synchronous code (PyQt)
class DatabaseSession:
    """
    Context manager for synchronous database sessions.

    Usage:
        with DatabaseSession() as session:
            project = session.query(Project).first()
            session.commit()
    """

    def __init__(self):
        self.session: Optional[Session] = None

    def __enter__(self) -> Session:
        self.session = get_session()
        return self.session

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            if exc_type is not None:
                self.session.rollback()
            self.session.close()
        return False
