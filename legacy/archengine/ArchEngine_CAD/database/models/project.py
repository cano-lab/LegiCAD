"""
Project model and version history.
"""
from sqlalchemy import Column, String, Text, Integer, Float, ForeignKey, Enum, JSON
from sqlalchemy.orm import relationship
import enum

from database.models.base import Base, TimestampMixin, SyncMixin, generate_uuid


class ProjectStatus(enum.Enum):
    """Project lifecycle status."""
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class Project(Base, TimestampMixin, SyncMixin):
    """
    Building project container.

    A project represents a single building design with all its
    elements (walls, doors, windows, rooms), sheets, and metadata.
    """
    __tablename__ = "projects"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(
        String(36),
        ForeignKey("workspaces.id"),
        nullable=False
    )

    # Project info
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    project_number = Column(String(100), nullable=True)
    status = Column(
        Enum(ProjectStatus),
        default=ProjectStatus.DRAFT,
        nullable=False
    )

    # Building info (from QBD)
    building_type = Column(String(50), default="residential")
    width = Column(Float, default=10000)  # mm
    depth = Column(Float, default=10000)  # mm
    stories = Column(Integer, default=1)
    wall_height = Column(Float, default=2700)  # Default wall height in mm
    sqm = Column(Float, nullable=True)
    sqft = Column(Float, nullable=True)
    units = Column(String(10), default="mm")

    # QBD answers preserved as JSON
    qbd_answers = Column(JSON, default=dict)

    # Additional project settings/metadata
    settings = Column(JSON, default=dict)

    # File path for legacy compatibility (optional)
    file_path = Column(String(500), nullable=True)

    # Relationships
    workspace = relationship("Workspace", back_populates="projects")
    walls = relationship(
        "Wall",
        back_populates="project",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="Wall.index"
    )
    doors = relationship(
        "Door",
        back_populates="project",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="Door.index"
    )
    windows = relationship(
        "Window",
        back_populates="project",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="Window.index"
    )
    rooms = relationship(
        "Room",
        back_populates="project",
        lazy="selectin",
        cascade="all, delete-orphan"
    )
    wall_types = relationship(
        "WallType",
        back_populates="project",
        lazy="selectin",
        cascade="all, delete-orphan"
    )
    roofs = relationship(
        "Roof",
        back_populates="project",
        lazy="selectin",
        cascade="all, delete-orphan"
    )
    sheets = relationship(
        "SheetConfig",
        back_populates="project",
        lazy="selectin",
        cascade="all, delete-orphan"
    )
    versions = relationship(
        "ProjectVersion",
        back_populates="project",
        lazy="selectin",
        order_by="ProjectVersion.version_number.desc()"
    )

    def __repr__(self):
        return f"<Project(id={self.id}, name={self.name})>"

    def to_legacy_dict(self) -> dict:
        """
        Convert to legacy JSON format for backward compatibility.

        Returns the same structure as the original JSON files.
        """
        return {
            "building_id": self.id,
            "name": self.name,
            "width": self.width,
            "depth": self.depth,
            "stories": self.stories,
            "wall_height": self.wall_height,
            "building_type": self.building_type,
            "sqm": self.sqm,
            "sqft": self.sqft,
            "units": self.units,
            "qbd_answers": self.qbd_answers or {},
            "settings": self.settings or {},
            "walls_batch": [w.to_legacy_dict() for w in self.walls],
            "doors": [d.to_legacy_dict() for d in self.doors],
            "windows": [w.to_legacy_dict() for w in self.windows],
            "rooms": {r.room_key: r.to_legacy_dict() for r in self.rooms},
            "wall_types": {wt.type_key: wt.to_legacy_dict() for wt in self.wall_types},
            "roofs": [r.to_legacy_dict() for r in self.roofs],
        }


class ProjectVersion(Base, TimestampMixin):
    """
    Version history for projects.

    Stores snapshots of project state for undo/history functionality.
    Replaces git-based VersionControl for database-backed projects.
    """
    __tablename__ = "project_versions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(
        String(36),
        ForeignKey("projects.id"),
        nullable=False
    )

    version_number = Column(Integer, nullable=False)
    message = Column(Text, nullable=True)

    # Full project state snapshot
    snapshot = Column(JSON, nullable=False)

    # Summary of what changed (for UI display)
    changes_summary = Column(JSON, nullable=True)

    # For future collaboration
    author_id = Column(String(36), nullable=True)
    author_name = Column(String(255), nullable=True)

    # Relationships
    project = relationship("Project", back_populates="versions")

    def __repr__(self):
        return f"<ProjectVersion(project={self.project_id}, v={self.version_number})>"
