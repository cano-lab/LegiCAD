"""
Pydantic schemas for Project API.
"""
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field


class ProjectBase(BaseModel):
    """Base schema for Project."""
    name: str = Field(..., min_length=1, max_length=255)
    building_type: str = Field(default="residential")
    width: float = Field(default=12000, gt=0)
    depth: float = Field(default=10000, gt=0)
    stories: int = Field(default=1, ge=1, le=10)
    wall_height: float = Field(default=2700, gt=0)


class ProjectCreate(ProjectBase):
    """Schema for creating a project."""
    workspace_id: str
    qbd_answers: Optional[Dict[str, Any]] = None
    settings: Optional[Dict[str, Any]] = None


class ProjectUpdate(BaseModel):
    """Schema for updating a project."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    building_type: Optional[str] = None
    width: Optional[float] = Field(None, gt=0)
    depth: Optional[float] = Field(None, gt=0)
    stories: Optional[int] = Field(None, ge=1, le=10)
    wall_height: Optional[float] = Field(None, gt=0)
    qbd_answers: Optional[Dict[str, Any]] = None
    settings: Optional[Dict[str, Any]] = None


class ProjectResponse(ProjectBase):
    """Schema for project response."""
    id: str
    workspace_id: str
    qbd_answers: Dict[str, Any] = {}
    settings: Dict[str, Any] = {}
    created_at: datetime
    updated_at: datetime
    is_dirty: bool = False
    sync_version: int = 0

    class Config:
        from_attributes = True


class ProjectListResponse(BaseModel):
    """Schema for paginated project list."""
    items: List[ProjectResponse]
    total: int
    skip: int
    limit: int


class ProjectExport(BaseModel):
    """Schema for full project export (legacy JSON format)."""
    name: str
    building_type: str
    width: float
    depth: float
    stories: int
    wall_height: float
    qbd_answers: Dict[str, Any] = {}
    settings: Dict[str, Any] = {}
    walls_batch: List[Dict[str, Any]] = []
    doors: List[Dict[str, Any]] = []
    windows: List[Dict[str, Any]] = []
    rooms: Dict[str, Dict[str, Any]] = {}
    wall_types: Dict[str, Dict[str, Any]] = {}
    roofs: List[Dict[str, Any]] = []


class ProjectImport(BaseModel):
    """Schema for importing project from JSON."""
    data: Dict[str, Any]
    workspace_id: str
    name: Optional[str] = None  # Override name from data


class VersionResponse(BaseModel):
    """Schema for project version."""
    id: str
    project_id: str
    version_number: int
    message: str
    created_at: datetime

    class Config:
        from_attributes = True


class VersionCreate(BaseModel):
    """Schema for creating a version snapshot."""
    message: str = ""
