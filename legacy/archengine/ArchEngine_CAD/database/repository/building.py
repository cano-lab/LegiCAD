"""
Building element repositories for walls, doors, windows, rooms.
"""
from typing import List, Optional, Dict, Any, Tuple
from sqlalchemy import select, and_, or_
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.building import Wall, Door, Window, Room, WallType, Roof
from database.repository.base import BaseRepository, AsyncBaseRepository


class WallRepository(BaseRepository[Wall]):
    """Repository for Wall entities."""

    def __init__(self, session: Session):
        super().__init__(Wall, session)

    def get_by_project(self, project_id: str) -> List[Wall]:
        """Get all walls for a project."""
        return self.session.query(Wall).filter(
            Wall.project_id == project_id
        ).order_by(Wall.index).all()

    def get_by_index(self, project_id: str, index: int) -> Optional[Wall]:
        """Get wall by its index within a project."""
        return self.session.query(Wall).filter(
            and_(
                Wall.project_id == project_id,
                Wall.index == index
            )
        ).first()

    def get_by_category(self, project_id: str, category: str) -> List[Wall]:
        """Get walls by category (exterior, interior, etc.)."""
        return self.session.query(Wall).filter(
            and_(
                Wall.project_id == project_id,
                Wall.category == category
            )
        ).order_by(Wall.index).all()

    def get_next_index(self, project_id: str) -> int:
        """Get the next available wall index."""
        result = self.session.query(Wall.index).filter(
            Wall.project_id == project_id
        ).order_by(Wall.index.desc()).first()

        return (result[0] + 1) if result else 0

    def update_positions(
        self,
        wall: Wall,
        start: Tuple[float, float, float],
        end: Tuple[float, float, float]
    ) -> Wall:
        """Update wall start/end positions."""
        wall.start_x, wall.start_y, wall.start_z = start
        wall.end_x, wall.end_y, wall.end_z = end
        wall.mark_dirty()
        self.session.flush()
        return wall

    def batch_create(self, project_id: str, walls_data: List[Dict[str, Any]]) -> List[Wall]:
        """Create multiple walls from batch data."""
        walls = []
        next_index = self.get_next_index(project_id)

        for i, data in enumerate(walls_data):
            wall = Wall(
                project_id=project_id,
                index=data.get("index", next_index + i),
                start_x=data["start"][0],
                start_y=data["start"][1],
                start_z=data["start"][2],
                end_x=data["end"][0],
                end_y=data["end"][1],
                end_z=data["end"][2],
                height=data.get("height", 2700),
                category=data.get("category", "exterior"),
                is_pinned=data.get("is_pinned", False),
            )
            walls.append(wall)

        return self.create_many(walls)


class DoorRepository(BaseRepository[Door]):
    """Repository for Door entities."""

    def __init__(self, session: Session):
        super().__init__(Door, session)

    def get_by_project(self, project_id: str) -> List[Door]:
        """Get all doors for a project."""
        return self.session.query(Door).filter(
            Door.project_id == project_id
        ).all()

    def get_by_wall(self, wall_id: str) -> List[Door]:
        """Get all doors on a specific wall."""
        return self.session.query(Door).filter(
            Door.wall_id == wall_id
        ).order_by(Door.offset).all()

    def get_by_wall_index(self, project_id: str, wall_index: int) -> List[Door]:
        """Get doors by wall index."""
        return self.session.query(Door).join(Wall).filter(
            and_(
                Door.project_id == project_id,
                Wall.index == wall_index
            )
        ).all()


class WindowRepository(BaseRepository[Window]):
    """Repository for Window entities."""

    def __init__(self, session: Session):
        super().__init__(Window, session)

    def get_by_project(self, project_id: str) -> List[Window]:
        """Get all windows for a project."""
        return self.session.query(Window).filter(
            Window.project_id == project_id
        ).all()

    def get_by_wall(self, wall_id: str) -> List[Window]:
        """Get all windows on a specific wall."""
        return self.session.query(Window).filter(
            Window.wall_id == wall_id
        ).order_by(Window.offset).all()

    def get_by_wall_index(self, project_id: str, wall_index: int) -> List[Window]:
        """Get windows by wall index."""
        return self.session.query(Window).join(Wall).filter(
            and_(
                Window.project_id == project_id,
                Wall.index == wall_index
            )
        ).all()


class RoomRepository(BaseRepository[Room]):
    """Repository for Room entities."""

    def __init__(self, session: Session):
        super().__init__(Room, session)

    def get_by_project(self, project_id: str) -> List[Room]:
        """Get all rooms for a project."""
        return self.session.query(Room).filter(
            Room.project_id == project_id
        ).all()

    def get_by_key(self, project_id: str, room_key: str) -> Optional[Room]:
        """Get room by its key."""
        return self.session.query(Room).filter(
            and_(
                Room.project_id == project_id,
                Room.room_key == room_key
            )
        ).first()

    def get_by_type(self, project_id: str, room_type: str) -> List[Room]:
        """Get rooms by type (bedroom, bathroom, etc.)."""
        return self.session.query(Room).filter(
            and_(
                Room.project_id == project_id,
                Room.room_type == room_type
            )
        ).all()

    def update_bounds(self, room: Room, bounds: Dict[str, Any], area: float) -> Room:
        """Update room bounds and area."""
        room.bounds = bounds
        room.area = area
        room.mark_dirty()
        self.session.flush()
        return room


class WallTypeRepository(BaseRepository[WallType]):
    """Repository for WallType entities."""

    def __init__(self, session: Session):
        super().__init__(WallType, session)

    def get_by_project(self, project_id: str) -> List[WallType]:
        """Get all wall types for a project."""
        return self.session.query(WallType).filter(
            WallType.project_id == project_id
        ).all()

    def get_by_key(self, project_id: str, type_key: str) -> Optional[WallType]:
        """Get wall type by key."""
        return self.session.query(WallType).filter(
            and_(
                WallType.project_id == project_id,
                WallType.type_key == type_key
            )
        ).first()

    def get_default(self, project_id: str) -> Optional[WallType]:
        """Get the default wall type for a project."""
        return self.session.query(WallType).filter(
            and_(
                WallType.project_id == project_id,
                WallType.is_default == True
            )
        ).first()


class RoofRepository(BaseRepository[Roof]):
    """Repository for Roof entities."""

    def __init__(self, session: Session):
        super().__init__(Roof, session)

    def get_by_project(self, project_id: str) -> List[Roof]:
        """Get all roofs for a project."""
        return self.session.query(Roof).filter(
            Roof.project_id == project_id
        ).all()

    def get_primary(self, project_id: str) -> Optional[Roof]:
        """Get the primary roof for a project."""
        return self.session.query(Roof).filter(
            Roof.project_id == project_id
        ).first()


class BuildingRepository:
    """
    Aggregate repository for all building elements.

    Provides a unified interface for batch operations across
    walls, doors, windows, rooms, and roofs.
    """

    def __init__(self, session: Session):
        self.session = session
        self.walls = WallRepository(session)
        self.doors = DoorRepository(session)
        self.windows = WindowRepository(session)
        self.rooms = RoomRepository(session)
        self.wall_types = WallTypeRepository(session)
        self.roofs = RoofRepository(session)

    def get_all_elements(self, project_id: str) -> Dict[str, Any]:
        """Get all building elements for a project."""
        return {
            "walls": [w.to_legacy_dict() for w in self.walls.get_by_project(project_id)],
            "doors": [d.to_legacy_dict() for d in self.doors.get_by_project(project_id)],
            "windows": [w.to_legacy_dict() for w in self.windows.get_by_project(project_id)],
            "rooms": {r.room_key: r.to_legacy_dict() for r in self.rooms.get_by_project(project_id)},
            "wall_types": {wt.type_key: wt.to_legacy_dict() for wt in self.wall_types.get_by_project(project_id)},
            "roofs": [r.to_legacy_dict() for r in self.roofs.get_by_project(project_id)],
        }

    def batch_update(
        self,
        project_id: str,
        operations: List[Dict[str, Any]]
    ) -> Dict[str, int]:
        """
        Execute batch operations on building elements.

        Operations format:
        [
            {"op": "create", "type": "wall", "data": {...}},
            {"op": "update", "type": "door", "id": "...", "data": {...}},
            {"op": "delete", "type": "window", "id": "..."},
        ]

        Returns counts of operations performed.
        """
        counts = {"created": 0, "updated": 0, "deleted": 0}

        for op in operations:
            operation = op.get("op")
            element_type = op.get("type")
            data = op.get("data", {})
            element_id = op.get("id")

            repo = self._get_repo_for_type(element_type)
            if not repo:
                continue

            if operation == "create":
                data["project_id"] = project_id
                entity = self._create_element(element_type, data)
                if entity:
                    repo.create(entity)
                    counts["created"] += 1

            elif operation == "update" and element_id:
                entity = repo.get(element_id)
                if entity:
                    repo.update(entity, data)
                    counts["updated"] += 1

            elif operation == "delete" and element_id:
                entity = repo.get(element_id)
                if entity:
                    repo.delete(entity)
                    counts["deleted"] += 1

        self.session.flush()
        return counts

    def _get_repo_for_type(self, element_type: str):
        """Get repository for element type."""
        repos = {
            "wall": self.walls,
            "door": self.doors,
            "window": self.windows,
            "room": self.rooms,
            "wall_type": self.wall_types,
            "roof": self.roofs,
        }
        return repos.get(element_type)

    def _create_element(self, element_type: str, data: Dict[str, Any]):
        """Create element instance from data."""
        if element_type == "wall":
            return Wall(
                project_id=data["project_id"],
                index=data.get("index", 0),
                start_x=data.get("start", [0, 0, 0])[0],
                start_y=data.get("start", [0, 0, 0])[1],
                start_z=data.get("start", [0, 0, 0])[2],
                end_x=data.get("end", [0, 0, 0])[0],
                end_y=data.get("end", [0, 0, 0])[1],
                end_z=data.get("end", [0, 0, 0])[2],
                height=data.get("height", 2700),
                category=data.get("category", "exterior"),
            )
        elif element_type == "door":
            return Door(
                project_id=data["project_id"],
                wall_id=data.get("wall_id"),
                offset=data.get("offset", 500),
                width=data.get("width", 900),
                height=data.get("height", 2100),
            )
        elif element_type == "window":
            return Window(
                project_id=data["project_id"],
                wall_id=data.get("wall_id"),
                offset=data.get("offset", 500),
                width=data.get("width", 1200),
                height=data.get("height", 1200),
                sill_height=data.get("sill_height", 900),
            )
        elif element_type == "room":
            return Room(
                project_id=data["project_id"],
                room_key=data.get("room_key", ""),
                name=data.get("name", ""),
                room_type=data.get("room_type", "other"),
            )
        return None

    def commit(self):
        """Commit all changes."""
        self.session.commit()

    def rollback(self):
        """Rollback all changes."""
        self.session.rollback()
