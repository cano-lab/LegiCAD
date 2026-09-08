"""
Template model for reusable configurations.
"""
from sqlalchemy import Column, String, Text, Boolean, ForeignKey, JSON
from sqlalchemy.orm import relationship

from database.models.base import Base, TimestampMixin, generate_uuid


class Template(Base, TimestampMixin):
    """
    Reusable templates for projects, wall types, sheet sets, etc.

    Templates can be workspace-specific or global (builtin).
    """
    __tablename__ = "templates"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(
        String(36),
        ForeignKey("workspaces.id"),
        nullable=True  # Null for global/builtin templates
    )

    # Template info
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    # Type of template
    template_type = Column(String(50), nullable=False)
    # Types: "project", "wall_types", "sheet_set", "title_block"

    # Template content as JSON
    content = Column(JSON, nullable=False)

    # Classification
    category = Column(String(100), nullable=True)
    tags = Column(JSON, default=list)

    # System vs user templates
    is_builtin = Column(Boolean, default=False)

    # Relationships
    workspace = relationship("Workspace", back_populates="templates")

    def __repr__(self):
        return f"<Template(id={self.id}, name={self.name}, type={self.template_type})>"

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "template_type": self.template_type,
            "content": self.content,
            "category": self.category,
            "tags": self.tags or [],
            "is_builtin": self.is_builtin,
        }
