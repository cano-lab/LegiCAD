"""
Sheet configuration models.
"""
from sqlalchemy import Column, String, Text, Boolean, ForeignKey, JSON
from sqlalchemy.orm import relationship

from database.models.base import Base, TimestampMixin, SyncMixin, generate_uuid


class SheetConfig(Base, TimestampMixin, SyncMixin):
    """
    Drawing sheet configuration.

    Stores sheet metadata, preset configuration, and references.
    The actual SVG content is generated on demand, not stored.
    """
    __tablename__ = "sheet_configs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(
        String(36),
        ForeignKey("projects.id"),
        nullable=False
    )

    # Sheet identification
    sheet_key = Column(String(100), nullable=False)  # "floor_plan", etc.
    sheet_type = Column(String(50), nullable=False)
    title = Column(String(255), nullable=False)
    number = Column(String(50), nullable=False)

    # Drawing settings
    scale = Column(String(20), default="1:100")
    revision = Column(String(10), default="-")
    enabled = Column(Boolean, default=True)

    # Sheet size
    sheet_size = Column(String(20), default="ARCH_D")

    # Preset configuration (for multi-viewport sheets)
    preset_name = Column(String(100), nullable=True)
    preset_config = Column(JSON, nullable=True)  # Viewport configurations

    # Cross-references
    references_out = Column(JSON, default=list)  # Markers on this sheet
    references_in = Column(JSON, default=list)  # Sheets referencing this

    # Dimension overrides (user edits)
    dimension_overrides = Column(JSON, default=dict)

    # Relationships
    project = relationship("Project", back_populates="sheets")

    def __repr__(self):
        return f"<SheetConfig(id={self.id}, number={self.number})>"

    def to_legacy_dict(self) -> dict:
        """Convert to legacy format for compatibility."""
        return {
            "id": self.sheet_key,
            "sheet_type": self.sheet_type,
            "title": self.title,
            "number": self.number,
            "scale": self.scale,
            "revision": self.revision,
            "enabled": self.enabled,
            "preset_name": self.preset_name,
            "preset_config": self.preset_config,
            "references_out": self.references_out or [],
            "references_in": self.references_in or [],
            "dimension_overrides": self.dimension_overrides or {},
        }


class TitleBlockInfo(Base, TimestampMixin):
    """
    Title block configuration for a project or template.
    """
    __tablename__ = "title_blocks"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(
        String(36),
        ForeignKey("projects.id"),
        nullable=True
    )
    template_id = Column(
        String(36),
        ForeignKey("templates.id"),
        nullable=True
    )

    # Project info
    project_name = Column(String(255), default="Untitled Project")
    project_number = Column(String(100), nullable=True)
    project_address = Column(Text, nullable=True)

    # Client info
    client_name = Column(String(255), nullable=True)
    client_address = Column(Text, nullable=True)

    # Architect info
    architect_name = Column(String(255), nullable=True)
    architect_address = Column(Text, nullable=True)
    architect_license = Column(String(100), nullable=True)

    # Date and revision
    date = Column(String(50), nullable=True)
    issue_date = Column(String(50), nullable=True)

    # Logo and branding
    logo_path = Column(String(500), nullable=True)

    def __repr__(self):
        return f"<TitleBlockInfo(id={self.id}, project={self.project_name})>"

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "project_name": self.project_name,
            "project_number": self.project_number,
            "project_address": self.project_address,
            "client_name": self.client_name,
            "architect_name": self.architect_name,
            "architect_address": self.architect_address,
            "date": self.date,
        }
