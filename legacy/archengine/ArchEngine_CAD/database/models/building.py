"""
Building element models: Wall, Door, Window, Room, WallType, Roof.
"""
from sqlalchemy import Column, String, Integer, Float, Boolean, ForeignKey, Enum, JSON
from sqlalchemy.orm import relationship
import enum

from database.models.base import Base, TimestampMixin, SyncMixin, generate_uuid


class WallCategory(enum.Enum):
    """Wall category for determining thickness and properties."""
    EXTERIOR = "exterior"
    INTERIOR = "interior"
    WET_WALL = "wet_wall"


class Wall(Base, TimestampMixin, SyncMixin):
    """
    Wall element in a building.

    Walls are defined by start/end points in 3D space with height.
    They can have doors and windows hosted on them.
    """
    __tablename__ = "walls"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(
        String(36),
        ForeignKey("projects.id"),
        nullable=False
    )

    # Order index within project
    index = Column(Integer, nullable=False)

    # Start point (mm)
    start_x = Column(Float, nullable=False)
    start_y = Column(Float, nullable=False, default=0)  # Elevation
    start_z = Column(Float, nullable=False)

    # End point (mm)
    end_x = Column(Float, nullable=False)
    end_y = Column(Float, nullable=False, default=0)
    end_z = Column(Float, nullable=False)

    # Dimensions
    height = Column(Float, default=2700)

    # Type and category (string for legacy compatibility)
    category = Column(String(50), default="interior", nullable=False)
    wall_type_id = Column(
        String(36),
        ForeignKey("wall_types.id"),
        nullable=True
    )
    level_name = Column(String(100), default="Level 1")

    # Constraints for LLM workflow
    is_pinned = Column(Boolean, default=False)
    locked_properties = Column(JSON, default=list)

    # Room associations (list of room IDs)
    room_ids = Column(JSON, default=list)

    # Relationships
    project = relationship("Project", back_populates="walls")
    wall_type = relationship("WallType", lazy="joined")
    doors = relationship(
        "Door",
        back_populates="wall",
        lazy="dynamic",
        cascade="all, delete-orphan"
    )
    windows = relationship(
        "Window",
        back_populates="wall",
        lazy="dynamic",
        cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Wall(id={self.id}, index={self.index})>"

    @property
    def start(self) -> tuple:
        """Get start point as tuple."""
        return (self.start_x, self.start_y, self.start_z)

    @property
    def end(self) -> tuple:
        """Get end point as tuple."""
        return (self.end_x, self.end_y, self.end_z)

    @property
    def length(self) -> float:
        """Calculate wall length."""
        import math
        dx = self.end_x - self.start_x
        dz = self.end_z - self.start_z
        return math.sqrt(dx * dx + dz * dz)

    def to_legacy_dict(self) -> dict:
        """Convert to legacy JSON format."""
        return {
            "start": [self.start_x, self.start_y, self.start_z],
            "end": [self.end_x, self.end_y, self.end_z],
            "height": self.height,
            "category": self.category or "interior",
            "wall_type": self.wall_type.type_key if self.wall_type else "",
            "level_name": self.level_name,
            "is_pinned": self.is_pinned,
            "locked_properties": self.locked_properties or [],
            "rooms": self.room_ids or [],
        }


class Door(Base, TimestampMixin, SyncMixin):
    """
    Door element hosted on a wall.
    """
    __tablename__ = "doors"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(
        String(36),
        ForeignKey("projects.id"),
        nullable=False
    )
    wall_id = Column(
        String(36),
        ForeignKey("walls.id"),
        nullable=False
    )

    # Order index within project
    index = Column(Integer, nullable=False)
    wall_index = Column(Integer, nullable=False)  # Legacy compatibility

    # Position on wall (distance from wall start)
    offset = Column(Float, nullable=False)

    # Dimensions (mm)
    width = Column(Float, default=914)  # 36"
    height = Column(Float, default=2134)  # 84"

    # Door type and swing
    door_type = Column(String(50), default="swing")
    swing = Column(String(50), default="left_in")

    # Extended properties
    hardware = Column(String(100), nullable=True)
    frame = Column(String(100), nullable=True)
    fire_rating = Column(Integer, default=0)

    # Room references
    room1 = Column(String(100), nullable=True)
    room2 = Column(String(100), nullable=True)

    # Constraints
    is_pinned = Column(Boolean, default=False)
    locked_properties = Column(JSON, default=list)

    # Relationships
    project = relationship("Project", back_populates="doors")
    wall = relationship("Wall", back_populates="doors")

    def __repr__(self):
        return f"<Door(id={self.id}, index={self.index})>"

    def to_legacy_dict(self) -> dict:
        """Convert to legacy JSON format."""
        return {
            "wall_index": self.wall_index,
            "offset": self.offset,
            "width": self.width,
            "height": self.height,
            "type": self.door_type,
            "swing": self.swing,
            "hardware": self.hardware,
            "frame": self.frame,
            "room1": self.room1,
            "room2": self.room2,
            "is_pinned": self.is_pinned,
            "locked_properties": self.locked_properties or [],
        }


class Window(Base, TimestampMixin, SyncMixin):
    """
    Window element hosted on a wall.
    """
    __tablename__ = "windows"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(
        String(36),
        ForeignKey("projects.id"),
        nullable=False
    )
    wall_id = Column(
        String(36),
        ForeignKey("walls.id"),
        nullable=False
    )

    # Order index
    index = Column(Integer, nullable=False)
    wall_index = Column(Integer, nullable=False)  # Legacy

    # Position on wall
    offset = Column(Float, nullable=False)

    # Dimensions (mm)
    width = Column(Float, default=1200)
    height = Column(Float, default=1200)
    sill_height = Column(Float, default=900)

    # Window type
    window_type = Column(String(50), default="casement")

    # Performance properties
    glazing = Column(String(100), nullable=True)
    u_factor = Column(Float, nullable=True)
    shgc = Column(Float, nullable=True)

    # Room reference
    room = Column(String(100), nullable=True)

    # Constraints
    is_pinned = Column(Boolean, default=False)
    locked_properties = Column(JSON, default=list)

    # Relationships
    project = relationship("Project", back_populates="windows")
    wall = relationship("Wall", back_populates="windows")

    def __repr__(self):
        return f"<Window(id={self.id}, index={self.index})>"

    def to_legacy_dict(self) -> dict:
        """Convert to legacy JSON format."""
        return {
            "wall_index": self.wall_index,
            "offset": self.offset,
            "width": self.width,
            "height": self.height,
            "sill_height": self.sill_height,
            "type": self.window_type,
            "glazing": self.glazing,
            "u_factor": self.u_factor,
            "shgc": self.shgc,
            "room": self.room,
            "is_pinned": self.is_pinned,
            "locked_properties": self.locked_properties or [],
        }


class Room(Base, TimestampMixin, SyncMixin):
    """
    Room definition with bounds and properties.
    """
    __tablename__ = "rooms"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(
        String(36),
        ForeignKey("projects.id"),
        nullable=False
    )

    # Room identifier (original string key like "living")
    room_key = Column(String(100), nullable=False)

    # Display name and type
    name = Column(String(255), nullable=False)
    room_type = Column(String(100), nullable=False)

    # Bounding box (mm)
    bounds_x = Column(Float, nullable=False)
    bounds_y = Column(Float, nullable=False)
    bounds_width = Column(Float, nullable=False)
    bounds_height = Column(Float, nullable=False)

    # Center point
    center_x = Column(Float, nullable=True)
    center_z = Column(Float, nullable=True)

    # Polygon vertices (optional, for complex rooms)
    vertices = Column(JSON, nullable=True)  # [[x,z], ...]

    # Area
    area = Column(Float, default=0)  # sqmm
    area_sqm = Column(Float, nullable=True)
    area_sqft = Column(Float, nullable=True)

    # Properties
    zone = Column(String(50), nullable=True)  # public, private, service
    floor_finish = Column(String(100), nullable=True)
    wall_finish = Column(String(100), nullable=True)
    ceiling_finish = Column(String(100), nullable=True)
    ceiling_height = Column(Float, nullable=True)

    # Constraints
    is_pinned = Column(Boolean, default=False)
    locked_properties = Column(JSON, default=list)

    # Relationships
    project = relationship("Project", back_populates="rooms")

    def __repr__(self):
        return f"<Room(id={self.id}, key={self.room_key}, name={self.name})>"

    def to_legacy_dict(self) -> dict:
        """Convert to legacy JSON format."""
        result = {
            "name": self.name,
            "room_type": self.room_type,
            "bounds": {
                "x": self.bounds_x,
                "y": self.bounds_y,
                "width": self.bounds_width,
                "height": self.bounds_height,
            },
            "area": self.area,
            "is_pinned": self.is_pinned,
            "locked_properties": self.locked_properties or [],
        }
        if self.center_x is not None:
            result["center"] = {"x": self.center_x, "z": self.center_z}
        if self.vertices:
            result["vertices"] = self.vertices
        if self.zone:
            result["zone"] = self.zone
        if self.floor_finish:
            result["floor_finish"] = self.floor_finish
        if self.wall_finish:
            result["wall_finish"] = self.wall_finish
        if self.ceiling_finish:
            result["ceiling_finish"] = self.ceiling_finish
        if self.ceiling_height:
            result["ceiling_height"] = self.ceiling_height
        return result


class WallType(Base, TimestampMixin):
    """
    Wall type definition with layers.
    """
    __tablename__ = "wall_types"

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

    # Wall type identifier
    type_key = Column(String(100), nullable=False)  # "ext_2x6_r21"
    name = Column(String(255), nullable=False)
    category = Column(
        Enum(WallCategory),
        default=WallCategory.INTERIOR,
        nullable=False
    )

    # Computed properties
    total_thickness = Column(Float, default=0)
    total_r_value = Column(Float, default=0)
    fire_rating = Column(Integer, default=0)

    # Layers as JSON for flexibility
    # Each layer: {name, material, thickness, function, color, r_value}
    layers = Column(JSON, default=list)

    # Relationships
    project = relationship("Project", back_populates="wall_types")

    def __repr__(self):
        return f"<WallType(id={self.id}, key={self.type_key})>"

    def to_legacy_dict(self) -> dict:
        """Convert to legacy JSON format."""
        return {
            "id": self.type_key,
            "name": self.name,
            "category": self.category.value if self.category else "interior",
            "total_thickness": self.total_thickness,
            "total_r_value": self.total_r_value,
            "fire_rating": self.fire_rating,
            "layers": self.layers or [],
        }


class Roof(Base, TimestampMixin, SyncMixin):
    """
    Roof definition with surfaces.
    """
    __tablename__ = "roofs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(
        String(36),
        ForeignKey("projects.id"),
        nullable=False
    )

    # Roof properties
    roof_type = Column(String(50), default="gable")
    pitch = Column(Float, default=4)  # rise/run
    overhang = Column(Float, default=600)  # mm
    ridge_height = Column(Float, nullable=True)

    # Material
    material = Column(String(100), default="asphalt_shingle")
    fascia_height = Column(Float, default=150)

    # Geometry as JSON
    surfaces = Column(JSON, default=list)  # List of surface polygons
    edges = Column(JSON, default=list)  # Ridge, hip, valley edges

    # Computed area
    total_area = Column(Float, nullable=True)

    # Relationships
    project = relationship("Project", back_populates="roofs")

    def __repr__(self):
        return f"<Roof(id={self.id}, type={self.roof_type})>"

    def to_legacy_dict(self) -> dict:
        """Convert to legacy JSON format."""
        return {
            "type": self.roof_type,
            "pitch": self.pitch,
            "overhang": self.overhang,
            "ridge_height": self.ridge_height,
            "material": self.material,
            "fascia_height": self.fascia_height,
            "surfaces": self.surfaces or [],
            "edges": self.edges or [],
            "total_area": self.total_area,
        }
