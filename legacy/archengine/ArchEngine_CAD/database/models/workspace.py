"""
Workspace and user preference models.
"""
from sqlalchemy import Column, String, Text, Boolean, ForeignKey, JSON
from sqlalchemy.orm import relationship

from database.models.base import Base, TimestampMixin, SyncMixin, generate_uuid


class Workspace(Base, TimestampMixin, SyncMixin):
    """
    User workspace containing multiple projects.

    A workspace is the top-level container for organizing projects,
    templates, and shared settings.
    """
    __tablename__ = "workspaces"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    owner_id = Column(String(36), nullable=True)  # Future: user reference
    settings = Column(JSON, default=dict)  # Workspace-level settings

    # Relationships
    projects = relationship(
        "Project",
        back_populates="workspace",
        lazy="dynamic",
        cascade="all, delete-orphan"
    )
    templates = relationship(
        "Template",
        back_populates="workspace",
        lazy="dynamic",
        cascade="all, delete-orphan"
    )
    preferences = relationship(
        "UserPreference",
        back_populates="workspace",
        lazy="dynamic"
    )

    def __repr__(self):
        return f"<Workspace(id={self.id}, name={self.name})>"


class UserPreference(Base, TimestampMixin):
    """
    User preferences and UI settings.

    Stores per-user, per-workspace preferences like theme,
    snap settings, recent files, and window geometry.
    """
    __tablename__ = "user_preferences"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), nullable=True)  # Future: user reference
    workspace_id = Column(
        String(36),
        ForeignKey("workspaces.id"),
        nullable=True
    )

    # UI preferences
    theme = Column(String(50), default="dark")
    grid_visible = Column(Boolean, default=True)
    snap_enabled = Column(Boolean, default=True)
    ortho_mode = Column(Boolean, default=False)

    # Snap settings
    snap_endpoint = Column(Boolean, default=True)
    snap_midpoint = Column(Boolean, default=True)
    snap_perpendicular = Column(Boolean, default=True)
    snap_parallel = Column(Boolean, default=False)
    snap_extension = Column(Boolean, default=False)
    snap_angular = Column(Boolean, default=False)

    # Drawing defaults
    default_wall_height = Column(String(20), default="2700")
    default_scale = Column(String(20), default="1:100")
    default_sheet_size = Column(String(20), default="ARCH_D")

    # Recent files and state
    recent_projects = Column(JSON, default=list)  # List of project IDs
    window_geometry = Column(JSON, default=dict)  # {x, y, width, height}
    dock_state = Column(Text, nullable=True)  # Qt dock layout state

    # Relationships
    workspace = relationship("Workspace", back_populates="preferences")

    def __repr__(self):
        return f"<UserPreference(id={self.id}, user_id={self.user_id})>"

    def add_recent_project(self, project_id: str, max_recent: int = 10):
        """Add a project to recent list, maintaining max size."""
        recent = list(self.recent_projects or [])
        if project_id in recent:
            recent.remove(project_id)
        recent.insert(0, project_id)
        self.recent_projects = recent[:max_recent]
