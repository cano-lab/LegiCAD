"""
Pydantic schemas for Building elements API.
"""
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime
from pydantic import BaseModel, Field


# Wall schemas
class WallBase(BaseModel):
    """Base schema for Wall."""
    index: int = Field(..., ge=0)
    start: List[float] = Field(..., min_length=3, max_length=3)
    end: List[float] = Field(..., min_length=3, max_length=3)
    height: float = Field(default=2700, gt=0)
    category: str = Field(default="exterior")
    wall_type_id: Optional[str] = None
    is_pinned: bool = False


class WallCreate(WallBase):
    """Schema for creating a wall."""
    pass


class WallUpdate(BaseModel):
    """Schema for updating a wall."""
    start: Optional[List[float]] = Field(None, min_length=3, max_length=3)
    end: Optional[List[float]] = Field(None, min_length=3, max_length=3)
    height: Optional[float] = Field(None, gt=0)
    category: Optional[str] = None
    wall_type_id: Optional[str] = None
    is_pinned: Optional[bool] = None


class WallResponse(WallBase):
    """Schema for wall response."""
    id: str
    project_id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# Door schemas
class DoorBase(BaseModel):
    """Base schema for Door."""
    wall_id: Optional[str] = None
    offset: float = Field(default=500, ge=0)
    width: float = Field(default=900, gt=0)
    height: float = Field(default=2100, gt=0)
    door_type: str = Field(default="single")
    swing: str = Field(default="left")


class DoorCreate(DoorBase):
    """Schema for creating a door."""
    wall_index: Optional[int] = None  # Alternative to wall_id


class DoorUpdate(BaseModel):
    """Schema for updating a door."""
    wall_id: Optional[str] = None
    offset: Optional[float] = Field(None, ge=0)
    width: Optional[float] = Field(None, gt=0)
    height: Optional[float] = Field(None, gt=0)
    door_type: Optional[str] = None
    swing: Optional[str] = None


class DoorResponse(DoorBase):
    """Schema for door response."""
    id: str
    project_id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# Window schemas
class WindowBase(BaseModel):
    """Base schema for Window."""
    wall_id: Optional[str] = None
    offset: float = Field(default=500, ge=0)
    width: float = Field(default=1200, gt=0)
    height: float = Field(default=1200, gt=0)
    sill_height: float = Field(default=900, ge=0)


class WindowCreate(WindowBase):
    """Schema for creating a window."""
    wall_index: Optional[int] = None  # Alternative to wall_id


class WindowUpdate(BaseModel):
    """Schema for updating a window."""
    wall_id: Optional[str] = None
    offset: Optional[float] = Field(None, ge=0)
    width: Optional[float] = Field(None, gt=0)
    height: Optional[float] = Field(None, gt=0)
    sill_height: Optional[float] = Field(None, ge=0)


class WindowResponse(WindowBase):
    """Schema for window response."""
    id: str
    project_id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# Room schemas
class RoomBase(BaseModel):
    """Base schema for Room."""
    room_key: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    room_type: str = Field(default="other")
    bounds: Dict[str, Any] = {}
    area: float = Field(default=0, ge=0)


class RoomCreate(RoomBase):
    """Schema for creating a room."""
    pass


class RoomUpdate(BaseModel):
    """Schema for updating a room."""
    name: Optional[str] = Field(None, min_length=1)
    room_type: Optional[str] = None
    bounds: Optional[Dict[str, Any]] = None
    area: Optional[float] = Field(None, ge=0)


class RoomResponse(RoomBase):
    """Schema for room response."""
    id: str
    project_id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# Batch operation schemas
class BatchOperation(BaseModel):
    """Single operation in a batch request."""
    op: Literal["create", "update", "delete"]
    type: Literal["wall", "door", "window", "room", "wall_type", "roof"]
    id: Optional[str] = None  # Required for update/delete
    data: Optional[Dict[str, Any]] = None  # Required for create/update


class BatchRequest(BaseModel):
    """Batch operations request."""
    operations: List[BatchOperation]


class BatchResponse(BaseModel):
    """Batch operations response."""
    created: int
    updated: int
    deleted: int
    errors: List[str] = []
