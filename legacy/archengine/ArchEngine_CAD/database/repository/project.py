"""
Project repository for project-specific database operations.
"""
from typing import List, Optional, Dict, Any
from sqlalchemy import select, and_
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.project import Project, ProjectVersion
from database.repository.base import BaseRepository, AsyncBaseRepository


class ProjectRepository(BaseRepository[Project]):
    """
    Repository for Project entities with project-specific queries.
    """

    def __init__(self, session: Session):
        super().__init__(Project, session)

    def get_by_workspace(
        self,
        workspace_id: str,
        skip: int = 0,
        limit: int = 100,
        include_deleted: bool = False
    ) -> List[Project]:
        """Get all projects in a workspace."""
        query = self.session.query(Project).filter(
            Project.workspace_id == workspace_id
        )

        if not include_deleted:
            query = query.filter(Project.deleted_at.is_(None))

        return query.order_by(Project.updated_at.desc()).offset(skip).limit(limit).all()

    def get_with_elements(self, id: str) -> Optional[Project]:
        """Get project with all building elements loaded."""
        return self.session.query(Project).options(
            joinedload(Project.walls),
            joinedload(Project.doors),
            joinedload(Project.windows),
            joinedload(Project.rooms),
            joinedload(Project.wall_types),
            joinedload(Project.roofs),
            joinedload(Project.sheets),
        ).filter(Project.id == id).first()

    def get_by_name(self, workspace_id: str, name: str) -> Optional[Project]:
        """Find project by name within a workspace."""
        return self.session.query(Project).filter(
            and_(
                Project.workspace_id == workspace_id,
                Project.name == name,
                Project.deleted_at.is_(None)
            )
        ).first()

    def search(
        self,
        workspace_id: str,
        query: str,
        limit: int = 20
    ) -> List[Project]:
        """Search projects by name or building type."""
        return self.session.query(Project).filter(
            and_(
                Project.workspace_id == workspace_id,
                Project.deleted_at.is_(None),
                Project.name.ilike(f"%{query}%")
            )
        ).limit(limit).all()

    def export_to_dict(self, project: Project) -> Dict[str, Any]:
        """Export project with all elements to legacy JSON format."""
        # Load all relationships if not already loaded
        if not self.session.object_session(project):
            project = self.get_with_elements(project.id)

        return project.to_legacy_dict() if project else {}

    def import_from_dict(
        self,
        data: Dict[str, Any],
        workspace_id: str
    ) -> Project:
        """Create project from legacy JSON format."""
        from database.models.building import Wall, Door, Window, Room, WallType, Roof

        # Create project
        project = Project(
            workspace_id=workspace_id,
            name=data.get("name", "Imported Project"),
            building_type=data.get("building_type", "residential"),
            width=data.get("width", 12000),
            depth=data.get("depth", 10000),
            stories=data.get("stories", 1),
            wall_height=data.get("wall_height", 2700),
            qbd_answers=data.get("qbd_answers", {}),
            settings=data.get("settings", {}),
        )
        self.session.add(project)
        self.session.flush()

        # Import wall types
        wall_types_in = data.get("wall_types", {})
        if isinstance(wall_types_in, dict):
            wall_types_iter = wall_types_in.values()
        else:
            wall_types_iter = wall_types_in or []
        for wt_data in wall_types_iter:
            wt = WallType(
                project_id=project.id,
                type_key=wt_data.get("id") or wt_data.get("type_key", ""),
                name=wt_data.get("name", ""),
                total_thickness=wt_data.get("total_thickness", wt_data.get("thickness", 140)),
                total_r_value=wt_data.get("total_r_value", 0),
                layers=wt_data.get("layers", []),
            )
            self.session.add(wt)

        # Import walls — keep mapping from input wall_index/index to new id
        wall_map = {}
        for i, wall_data in enumerate(data.get("walls_batch", [])):
            wall_index = wall_data.get("wall_index", wall_data.get("index", i))
            start = wall_data.get("start") or [0, 0, 0]
            end = wall_data.get("end") or [0, 0, 0]
            rooms_pair = wall_data.get("rooms") or []
            wall = Wall(
                project_id=project.id,
                index=wall_index,
                start_x=start[0], start_y=start[1] if len(start) > 1 else 0, start_z=start[2] if len(start) > 2 else 0,
                end_x=end[0], end_y=end[1] if len(end) > 1 else 0, end_z=end[2] if len(end) > 2 else 0,
                height=wall_data.get("height", 2700),
                category=wall_data.get("category", "interior"),
                level_name=wall_data.get("level_name", "Level 1"),
                wall_type_id=None,
                room_ids=list(rooms_pair),
                is_pinned=wall_data.get("is_pinned", False),
            )
            self.session.add(wall)
            self.session.flush()
            wall_map[wall_index] = wall.id

        # Import doors
        for i, door_data in enumerate(data.get("doors", [])):
            door = Door(
                project_id=project.id,
                wall_id=wall_map.get(door_data.get("wall_index")),
                index=i,
                wall_index=door_data.get("wall_index", 0),
                offset=door_data.get("offset", 0),
                width=door_data.get("width", 914),
                height=door_data.get("height", 2134),
                door_type=door_data.get("type", "swing"),
                swing=door_data.get("swing", "left_in"),
                room1=door_data.get("room1"),
                room2=door_data.get("room2"),
            )
            self.session.add(door)

        # Import windows
        for i, win_data in enumerate(data.get("windows", [])):
            window = Window(
                project_id=project.id,
                wall_id=wall_map.get(win_data.get("wall_index")),
                index=i,
                wall_index=win_data.get("wall_index", 0),
                offset=win_data.get("offset", 0),
                width=win_data.get("width", 1200),
                height=win_data.get("height", 1200),
                sill_height=win_data.get("sill_height", 900),
                window_type=win_data.get("type", "casement"),
                room=win_data.get("room"),
            )
            self.session.add(window)

        # Import rooms — bounds in schema is an object {x, y, width, height}
        for room_key, room_data in (data.get("rooms") or {}).items():
            bounds = room_data.get("bounds") or {}
            center = room_data.get("center") or {}
            room = Room(
                project_id=project.id,
                room_key=room_key,
                name=room_data.get("name", room_key),
                room_type=room_data.get("room_type") or room_data.get("type") or "other",
                bounds_x=bounds.get("x", 0),
                bounds_y=bounds.get("y", 0),
                bounds_width=bounds.get("width", 0),
                bounds_height=bounds.get("height", 0),
                center_x=center.get("x") if center else None,
                center_z=center.get("y") if center else None,
                area=room_data.get("area", 0),
                zone=room_data.get("zone"),
            )
            self.session.add(room)

        # Import roofs
        for roof_data in (data.get("roofs") or []):
            roof = Roof(
                project_id=project.id,
                roof_type=roof_data.get("type", "gable"),
                pitch=roof_data.get("pitch", 6),
                overhang=roof_data.get("overhang", 600),
                material=roof_data.get("material", "asphalt_shingle"),
                surfaces=roof_data.get("surfaces", []),
                edges=roof_data.get("edges", []),
            )
            self.session.add(roof)

        self.session.flush()
        return project


class ProjectVersionRepository(BaseRepository[ProjectVersion]):
    """Repository for project version history."""

    def __init__(self, session: Session):
        super().__init__(ProjectVersion, session)

    def get_versions(
        self,
        project_id: str,
        limit: int = 50
    ) -> List[ProjectVersion]:
        """Get version history for a project."""
        return self.session.query(ProjectVersion).filter(
            ProjectVersion.project_id == project_id
        ).order_by(ProjectVersion.version_number.desc()).limit(limit).all()

    def get_latest_version(self, project_id: str) -> Optional[ProjectVersion]:
        """Get the latest version of a project."""
        return self.session.query(ProjectVersion).filter(
            ProjectVersion.project_id == project_id
        ).order_by(ProjectVersion.version_number.desc()).first()

    def create_version(
        self,
        project: Project,
        message: str = ""
    ) -> ProjectVersion:
        """Create a new version snapshot of a project."""
        latest = self.get_latest_version(project.id)
        next_version = (latest.version_number + 1) if latest else 1

        version = ProjectVersion(
            project_id=project.id,
            version_number=next_version,
            snapshot=project.to_legacy_dict(),
            message=message,
        )
        return self.create(version)


class AsyncProjectRepository(AsyncBaseRepository[Project]):
    """Async version of ProjectRepository for FastAPI."""

    def __init__(self, session: AsyncSession):
        super().__init__(Project, session)

    async def get_by_workspace(
        self,
        workspace_id: str,
        skip: int = 0,
        limit: int = 100,
        include_deleted: bool = False
    ) -> List[Project]:
        """Get all projects in a workspace."""
        stmt = select(Project).where(Project.workspace_id == workspace_id)

        if not include_deleted:
            stmt = stmt.where(Project.deleted_at.is_(None))

        stmt = stmt.order_by(Project.updated_at.desc()).offset(skip).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_with_elements(self, id: str) -> Optional[Project]:
        """Get project with all building elements loaded."""
        stmt = select(Project).options(
            joinedload(Project.walls),
            joinedload(Project.doors),
            joinedload(Project.windows),
            joinedload(Project.rooms),
            joinedload(Project.wall_types),
            joinedload(Project.roofs),
            joinedload(Project.sheets),
        ).where(Project.id == id)

        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def search(
        self,
        workspace_id: str,
        query: str,
        limit: int = 20
    ) -> List[Project]:
        """Search projects by name."""
        stmt = select(Project).where(
            and_(
                Project.workspace_id == workspace_id,
                Project.deleted_at.is_(None),
                Project.name.ilike(f"%{query}%")
            )
        ).limit(limit)

        result = await self.session.execute(stmt)
        return list(result.scalars().all())
