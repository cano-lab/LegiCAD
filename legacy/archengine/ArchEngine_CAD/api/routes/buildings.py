"""
Building elements API routes.
"""
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from database.engine import get_db
from database.models.building import Wall, Door, Window, Room
from api.schemas.building import (
    WallCreate,
    WallUpdate,
    WallResponse,
    DoorCreate,
    DoorUpdate,
    DoorResponse,
    WindowCreate,
    WindowUpdate,
    WindowResponse,
    RoomCreate,
    RoomUpdate,
    RoomResponse,
    BatchRequest,
    BatchResponse,
)

router = APIRouter(prefix="/buildings/{project_id}", tags=["buildings"])


# --- Walls ---

@router.get("/walls", response_model=List[WallResponse])
async def list_walls(
    project_id: str,
    category: str = None,
    db: AsyncSession = Depends(get_db),
):
    """List all walls for a project."""
    stmt = select(Wall).where(Wall.project_id == project_id)

    if category:
        stmt = stmt.where(Wall.category == category)

    stmt = stmt.order_by(Wall.index)
    result = await db.execute(stmt)
    walls = result.scalars().all()

    return [_wall_to_response(w) for w in walls]


@router.post("/walls", response_model=WallResponse, status_code=201)
async def create_wall(
    project_id: str,
    wall: WallCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new wall."""
    db_wall = Wall(
        project_id=project_id,
        index=wall.index,
        start_x=wall.start[0],
        start_y=wall.start[1],
        start_z=wall.start[2],
        end_x=wall.end[0],
        end_y=wall.end[1],
        end_z=wall.end[2],
        height=wall.height,
        category=wall.category,
        wall_type_id=wall.wall_type_id,
        is_pinned=wall.is_pinned,
    )

    db.add(db_wall)
    await db.commit()
    await db.refresh(db_wall)

    return _wall_to_response(db_wall)


@router.get("/walls/{wall_id}", response_model=WallResponse)
async def get_wall(
    project_id: str,
    wall_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get a wall by ID."""
    wall = await db.get(Wall, wall_id)

    if not wall or wall.project_id != project_id:
        raise HTTPException(status_code=404, detail="Wall not found")

    return _wall_to_response(wall)


@router.put("/walls/{wall_id}", response_model=WallResponse)
async def update_wall(
    project_id: str,
    wall_id: str,
    updates: WallUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a wall."""
    wall = await db.get(Wall, wall_id)

    if not wall or wall.project_id != project_id:
        raise HTTPException(status_code=404, detail="Wall not found")

    update_data = updates.model_dump(exclude_unset=True)

    if "start" in update_data:
        wall.start_x, wall.start_y, wall.start_z = update_data.pop("start")
    if "end" in update_data:
        wall.end_x, wall.end_y, wall.end_z = update_data.pop("end")

    for key, value in update_data.items():
        setattr(wall, key, value)

    wall.mark_dirty()
    await db.commit()
    await db.refresh(wall)

    return _wall_to_response(wall)


@router.delete("/walls/{wall_id}", status_code=204)
async def delete_wall(
    project_id: str,
    wall_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Delete a wall."""
    wall = await db.get(Wall, wall_id)

    if not wall or wall.project_id != project_id:
        raise HTTPException(status_code=404, detail="Wall not found")

    await db.delete(wall)
    await db.commit()


def _wall_to_response(wall: Wall) -> WallResponse:
    """Convert Wall model to response schema."""
    return WallResponse(
        id=wall.id,
        project_id=wall.project_id,
        index=wall.index,
        start=[wall.start_x, wall.start_y, wall.start_z],
        end=[wall.end_x, wall.end_y, wall.end_z],
        height=wall.height,
        category=wall.category,
        wall_type_id=wall.wall_type_id,
        is_pinned=wall.is_pinned,
        created_at=wall.created_at,
        updated_at=wall.updated_at,
    )


# --- Doors ---

@router.get("/doors", response_model=List[DoorResponse])
async def list_doors(
    project_id: str,
    wall_id: str = None,
    db: AsyncSession = Depends(get_db),
):
    """List all doors for a project."""
    stmt = select(Door).where(Door.project_id == project_id)

    if wall_id:
        stmt = stmt.where(Door.wall_id == wall_id)

    result = await db.execute(stmt)
    doors = result.scalars().all()

    return [DoorResponse.model_validate(d) for d in doors]


@router.post("/doors", response_model=DoorResponse, status_code=201)
async def create_door(
    project_id: str,
    door: DoorCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new door."""
    wall_id = door.wall_id
    wall_index = door.wall_index

    # Resolve wall_index to wall_id if provided, or vice versa
    if door.wall_index is not None and not wall_id:
        stmt = select(Wall).where(
            and_(
                Wall.project_id == project_id,
                Wall.index == door.wall_index
            )
        )
        result = await db.execute(stmt)
        wall = result.scalar_one_or_none()
        if wall:
            wall_id = wall.id
            wall_index = wall.index
    elif wall_id and wall_index is None:
        # Get wall_index from the wall
        wall = await db.get(Wall, wall_id)
        if wall:
            wall_index = wall.index

    if wall_index is None:
        wall_index = 0  # Default fallback

    # Get next door index
    from sqlalchemy import func
    stmt = select(func.coalesce(func.max(Door.index), -1) + 1).where(
        Door.project_id == project_id
    )
    result = await db.execute(stmt)
    next_index = result.scalar()

    db_door = Door(
        project_id=project_id,
        wall_id=wall_id,
        wall_index=wall_index,
        index=next_index,
        offset=door.offset,
        width=door.width,
        height=door.height,
        door_type=door.door_type,
        swing=door.swing,
    )

    db.add(db_door)
    await db.commit()
    await db.refresh(db_door)

    return DoorResponse.model_validate(db_door)


@router.put("/doors/{door_id}", response_model=DoorResponse)
async def update_door(
    project_id: str,
    door_id: str,
    updates: DoorUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a door."""
    door = await db.get(Door, door_id)

    if not door or door.project_id != project_id:
        raise HTTPException(status_code=404, detail="Door not found")

    for key, value in updates.model_dump(exclude_unset=True).items():
        setattr(door, key, value)

    door.mark_dirty()
    await db.commit()
    await db.refresh(door)

    return DoorResponse.model_validate(door)


@router.delete("/doors/{door_id}", status_code=204)
async def delete_door(
    project_id: str,
    door_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Delete a door."""
    door = await db.get(Door, door_id)

    if not door or door.project_id != project_id:
        raise HTTPException(status_code=404, detail="Door not found")

    await db.delete(door)
    await db.commit()


# --- Windows ---

@router.get("/windows", response_model=List[WindowResponse])
async def list_windows(
    project_id: str,
    wall_id: str = None,
    db: AsyncSession = Depends(get_db),
):
    """List all windows for a project."""
    stmt = select(Window).where(Window.project_id == project_id)

    if wall_id:
        stmt = stmt.where(Window.wall_id == wall_id)

    result = await db.execute(stmt)
    windows = result.scalars().all()

    return [WindowResponse.model_validate(w) for w in windows]


@router.post("/windows", response_model=WindowResponse, status_code=201)
async def create_window(
    project_id: str,
    window: WindowCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new window."""
    wall_id = window.wall_id
    wall_index = window.wall_index

    # Resolve wall_index to wall_id if provided, or vice versa
    if window.wall_index is not None and not wall_id:
        stmt = select(Wall).where(
            and_(
                Wall.project_id == project_id,
                Wall.index == window.wall_index
            )
        )
        result = await db.execute(stmt)
        wall = result.scalar_one_or_none()
        if wall:
            wall_id = wall.id
            wall_index = wall.index
    elif wall_id and wall_index is None:
        # Get wall_index from the wall
        wall = await db.get(Wall, wall_id)
        if wall:
            wall_index = wall.index

    if wall_index is None:
        wall_index = 0  # Default fallback

    # Get next window index
    from sqlalchemy import func
    stmt = select(func.coalesce(func.max(Window.index), -1) + 1).where(
        Window.project_id == project_id
    )
    result = await db.execute(stmt)
    next_index = result.scalar()

    db_window = Window(
        project_id=project_id,
        index=next_index,
        wall_id=wall_id,
        wall_index=wall_index,
        offset=window.offset,
        width=window.width,
        height=window.height,
        sill_height=window.sill_height,
    )

    db.add(db_window)
    await db.commit()
    await db.refresh(db_window)

    return WindowResponse.model_validate(db_window)


@router.put("/windows/{window_id}", response_model=WindowResponse)
async def update_window(
    project_id: str,
    window_id: str,
    updates: WindowUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a window."""
    window = await db.get(Window, window_id)

    if not window or window.project_id != project_id:
        raise HTTPException(status_code=404, detail="Window not found")

    for key, value in updates.model_dump(exclude_unset=True).items():
        setattr(window, key, value)

    window.mark_dirty()
    await db.commit()
    await db.refresh(window)

    return WindowResponse.model_validate(window)


@router.delete("/windows/{window_id}", status_code=204)
async def delete_window(
    project_id: str,
    window_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Delete a window."""
    window = await db.get(Window, window_id)

    if not window or window.project_id != project_id:
        raise HTTPException(status_code=404, detail="Window not found")

    await db.delete(window)
    await db.commit()


# --- Rooms ---

@router.get("/rooms", response_model=List[RoomResponse])
async def list_rooms(
    project_id: str,
    room_type: str = None,
    db: AsyncSession = Depends(get_db),
):
    """List all rooms for a project."""
    stmt = select(Room).where(Room.project_id == project_id)

    if room_type:
        stmt = stmt.where(Room.room_type == room_type)

    result = await db.execute(stmt)
    rooms = result.scalars().all()

    return [RoomResponse.model_validate(r) for r in rooms]


@router.post("/rooms", response_model=RoomResponse, status_code=201)
async def create_room(
    project_id: str,
    room: RoomCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new room."""
    db_room = Room(
        project_id=project_id,
        room_key=room.room_key,
        name=room.name,
        room_type=room.room_type,
        bounds=room.bounds,
        area=room.area,
    )

    db.add(db_room)
    await db.commit()
    await db.refresh(db_room)

    return RoomResponse.model_validate(db_room)


@router.put("/rooms/{room_id}", response_model=RoomResponse)
async def update_room(
    project_id: str,
    room_id: str,
    updates: RoomUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a room."""
    room = await db.get(Room, room_id)

    if not room or room.project_id != project_id:
        raise HTTPException(status_code=404, detail="Room not found")

    for key, value in updates.model_dump(exclude_unset=True).items():
        setattr(room, key, value)

    room.mark_dirty()
    await db.commit()
    await db.refresh(room)

    return RoomResponse.model_validate(room)


@router.delete("/rooms/{room_id}", status_code=204)
async def delete_room(
    project_id: str,
    room_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Delete a room."""
    room = await db.get(Room, room_id)

    if not room or room.project_id != project_id:
        raise HTTPException(status_code=404, detail="Room not found")

    await db.delete(room)
    await db.commit()


# --- Batch Operations ---

@router.post("/batch", response_model=BatchResponse)
async def batch_operations(
    project_id: str,
    request: BatchRequest,
    db: AsyncSession = Depends(get_db),
):
    """Execute batch operations on building elements."""
    from database.repository.building import BuildingRepository
    from database.engine import get_session

    # Use sync session for batch operations
    sync_session = get_session()
    try:
        repo = BuildingRepository(sync_session)

        operations = [op.model_dump() for op in request.operations]
        result = repo.batch_update(project_id, operations)
        repo.commit()

        return BatchResponse(
            created=result["created"],
            updated=result["updated"],
            deleted=result["deleted"],
        )
    except Exception as e:
        sync_session.rollback()
        return BatchResponse(
            created=0,
            updated=0,
            deleted=0,
            errors=[str(e)],
        )
    finally:
        sync_session.close()
