"""
Application configuration with environment variable support.

Configuration values are loaded from environment variables with sensible defaults.
"""
import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class APIConfig:
    """API backend configuration."""

    # Enable API backend (set ARCHENGINE_USE_API_BACKEND=true)
    enabled: bool = field(
        default_factory=lambda: os.environ.get(
            "ARCHENGINE_USE_API_BACKEND", ""
        ).lower() == "true"
    )

    # API server URL
    base_url: str = field(
        default_factory=lambda: os.environ.get(
            "ARCHENGINE_API_BASE_URL",
            "http://localhost:8000/api/v1"
        )
    )

    # Request timeout (seconds)
    timeout: float = field(
        default_factory=lambda: float(
            os.environ.get("ARCHENGINE_API_TIMEOUT", "30")
        )
    )

    # Auto-sync interval (milliseconds, 0 to disable)
    auto_sync_interval: int = field(
        default_factory=lambda: int(
            os.environ.get("ARCHENGINE_AUTO_SYNC_INTERVAL", "30000")
        )
    )


@dataclass
class DatabaseConfig:
    """Database configuration."""

    # Database URL (SQLite by default)
    url: Optional[str] = field(
        default_factory=lambda: os.environ.get("ARCHENGINE_DATABASE_URL")
    )

    # SQLite database path (used if url not set)
    db_path: Path = field(
        default_factory=lambda: Path(
            os.environ.get(
                "ARCHENGINE_DB_PATH",
                str(Path.home() / ".archengine" / "archengine.db")
            )
        )
    )

    # Echo SQL statements (for debugging)
    echo: bool = field(
        default_factory=lambda: os.environ.get(
            "ARCHENGINE_DB_ECHO", ""
        ).lower() == "true"
    )


@dataclass
class CacheConfig:
    """Offline cache configuration."""

    # Cache directory
    dir: Path = field(
        default_factory=lambda: Path(
            os.environ.get(
                "ARCHENGINE_CACHE_DIR",
                str(Path.home() / ".archengine" / "cache")
            )
        )
    )

    # Maximum cache size (MB, 0 for unlimited)
    max_size_mb: int = field(
        default_factory=lambda: int(
            os.environ.get("ARCHENGINE_CACHE_MAX_SIZE", "500")
        )
    )


@dataclass
class AppConfig:
    """Main application configuration."""

    # Application data directory
    data_dir: Path = field(
        default_factory=lambda: Path(
            os.environ.get(
                "ARCHENGINE_DATA_DIR",
                str(Path.home() / ".archengine")
            )
        )
    )

    # Debug mode
    debug: bool = field(
        default_factory=lambda: os.environ.get(
            "ARCHENGINE_DEBUG", ""
        ).lower() == "true"
    )

    # Sub-configurations
    api: APIConfig = field(default_factory=APIConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)

    def __post_init__(self):
        """Ensure directories exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.cache.dir.mkdir(parents=True, exist_ok=True)


# Global configuration instance
_config: Optional[AppConfig] = None


def get_config() -> AppConfig:
    """Get the global configuration instance."""
    global _config
    if _config is None:
        _config = AppConfig()
    return _config


def reload_config() -> AppConfig:
    """Reload configuration from environment."""
    global _config
    _config = AppConfig()
    return _config


# Convenience accessors
def is_api_enabled() -> bool:
    """Check if API backend is enabled."""
    return get_config().api.enabled


def get_api_url() -> str:
    """Get API base URL."""
    return get_config().api.base_url


def is_debug() -> bool:
    """Check if debug mode is enabled."""
    return get_config().debug
