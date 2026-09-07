"""
API routes.
"""
from api.routes.projects import router as projects_router
from api.routes.buildings import router as buildings_router

__all__ = ["projects_router", "buildings_router"]
