"""
Application configuration and settings
"""
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field
import json


@dataclass
class Config:
    """Application configuration."""

    # Window state
    window_geometry: Optional[bytes] = None
    window_state: Optional[bytes] = None

    # Recent files
    last_project: Optional[str] = None
    recent_files: list = field(default_factory=list)
    max_recent_files: int = 10

    # Editor settings
    grid_size: int = 10000  # mm (10m grid for cleaner view)
    grid_visible: bool = True
    ortho_mode: bool = True
    snap_enabled: bool = True

    # Individual snap toggles
    snap_endpoint: bool = True
    snap_midpoint: bool = True
    snap_perpendicular: bool = True
    snap_parallel: bool = True
    snap_extension: bool = True
    snap_angular: bool = True

    # Display settings
    background_color: str = "#1a1a2e"
    grid_color: str = "#2a2a4e"
    wall_color_exterior: str = "#e0e0e0"
    wall_color_interior: str = "#a0a0a0"
    selection_color: str = "#ffff00"

    # Default scale
    default_scale: float = 0.05  # 1mm = 0.05 pixels

    # Paths
    @property
    def config_dir(self) -> Path:
        """Get config directory."""
        config_path = Path.home() / ".legiblestudio"
        config_path.mkdir(exist_ok=True)
        return config_path

    @property
    def config_file(self) -> Path:
        """Get config file path."""
        return self.config_dir / "config.json"

    def __post_init__(self):
        """Load config from file if exists."""
        self.load()

    def load(self):
        """Load configuration from file."""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    data = json.load(f)

                for key, value in data.items():
                    if hasattr(self, key):
                        setattr(self, key, value)
            except (json.JSONDecodeError, IOError):
                pass  # Use defaults

    def save(self):
        """Save configuration to file."""
        data = {
            'last_project': self.last_project,
            'recent_files': self.recent_files[:self.max_recent_files],
            'grid_size': self.grid_size,
            'grid_visible': self.grid_visible,
            'ortho_mode': self.ortho_mode,
            'snap_enabled': self.snap_enabled,
            'snap_endpoint': self.snap_endpoint,
            'snap_midpoint': self.snap_midpoint,
            'snap_perpendicular': self.snap_perpendicular,
            'snap_parallel': self.snap_parallel,
            'snap_extension': self.snap_extension,
            'snap_angular': self.snap_angular,
            'background_color': self.background_color,
            'default_scale': self.default_scale,
        }

        try:
            with open(self.config_file, 'w') as f:
                json.dump(data, f, indent=2)
        except IOError:
            pass

    def add_recent_file(self, path: Path):
        """Add a file to recent files list."""
        path_str = str(path.resolve())

        # Remove if already in list
        if path_str in self.recent_files:
            self.recent_files.remove(path_str)

        # Add to front
        self.recent_files.insert(0, path_str)

        # Trim to max
        self.recent_files = self.recent_files[:self.max_recent_files]

        # Update last project
        self.last_project = path_str

        self.save()
