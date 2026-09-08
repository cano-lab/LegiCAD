"""
Database module for ArchEngine CAD.

Provides SQLAlchemy models, repository pattern, and database engine management.
"""
from database.engine import (
    get_engine,
    get_session,
    get_async_session,
    init_db,
    init_db_async,
    close_db,
    close_db_async,
    get_db,
    DatabaseSession,
)
from database.models import (
    Base,
    Workspace,
    Project,
    Wall,
    Door,
    Window,
    Room,
    WallType,
    Roof,
    SheetConfig,
    ProjectVersion,
    Template,
    UserPreference,
)
from database.repository import (
    BaseRepository,
    AsyncBaseRepository,
    ProjectRepository,
    ProjectVersionRepository,
    AsyncProjectRepository,
    BuildingRepository,
    WallRepository,
    DoorRepository,
    WindowRepository,
    RoomRepository,
    WallTypeRepository,
    RoofRepository,
)

__all__ = [
    # Engine
    "get_engine",
    "get_session",
    "get_async_session",
    "init_db",
    "init_db_async",
    "close_db",
    "close_db_async",
    "get_db",
    "DatabaseSession",
    # Models
    "Base",
    "Workspace",
    "Project",
    "Wall",
    "Door",
    "Window",
    "Room",
    "WallType",
    "Roof",
    "SheetConfig",
    "ProjectVersion",
    "Template",
    "UserPreference",
    # Repositories
    "BaseRepository",
    "AsyncBaseRepository",
    "ProjectRepository",
    "ProjectVersionRepository",
    "AsyncProjectRepository",
    "BuildingRepository",
    "WallRepository",
    "DoorRepository",
    "WindowRepository",
    "RoomRepository",
    "WallTypeRepository",
    "RoofRepository",
]
