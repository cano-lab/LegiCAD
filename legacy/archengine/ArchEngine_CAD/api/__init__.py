"""
FastAPI server for ArchEngine CAD.

Provides REST API for database operations.
"""
from api.server import app, create_app

__all__ = ["app", "create_app"]
