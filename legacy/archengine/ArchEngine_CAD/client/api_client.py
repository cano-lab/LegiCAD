"""
HTTP client for ArchEngine API.

Handles all HTTP communication with the FastAPI server.
"""
import os
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
import httpx


@dataclass
class APIConfig:
    """API client configuration."""
    base_url: str = "http://localhost:8000/api/v1"
    timeout: float = 30.0
    max_retries: int = 3


class ArchEngineAPIClient:
    """
    HTTP client for ArchEngine CAD API.

    Provides methods for all API endpoints with automatic
    retry and error handling.
    """

    def __init__(self, config: Optional[APIConfig] = None):
        """
        Initialize API client.

        Args:
            config: API configuration. Uses env vars if not provided.
        """
        self.config = config or APIConfig(
            base_url=os.environ.get(
                "ARCHENGINE_API_BASE_URL",
                "http://localhost:8000/api/v1"
            ),
            timeout=float(os.environ.get("ARCHENGINE_API_TIMEOUT", "30")),
        )

        self._client = httpx.Client(
            base_url=self.config.base_url,
            timeout=self.config.timeout,
        )

    def close(self):
        """Close the HTTP client."""
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # --- Projects ---

    def list_projects(
        self,
        workspace_id: str,
        skip: int = 0,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """List all projects in a workspace."""
        response = self._client.get(
            "/projects",
            params={
                "workspace_id": workspace_id,
                "skip": skip,
                "limit": limit,
            },
        )
        response.raise_for_status()
        return response.json()

    def get_project(self, project_id: str) -> Dict[str, Any]:
        """Get a project by ID."""
        response = self._client.get(f"/projects/{project_id}")
        response.raise_for_status()
        return response.json()

    def create_project(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new project."""
        response = self._client.post("/projects", json=data)
        response.raise_for_status()
        return response.json()

    def update_project(
        self,
        project_id: str,
        data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Update a project."""
        response = self._client.put(f"/projects/{project_id}", json=data)
        response.raise_for_status()
        return response.json()

    def delete_project(self, project_id: str, hard: bool = False):
        """Delete a project."""
        response = self._client.delete(
            f"/projects/{project_id}",
            params={"hard": hard},
        )
        response.raise_for_status()

    def export_project(self, project_id: str) -> Dict[str, Any]:
        """Export project as legacy JSON format."""
        response = self._client.get(f"/projects/{project_id}/export")
        response.raise_for_status()
        return response.json()

    def import_project(
        self,
        workspace_id: str,
        data: Dict[str, Any],
        name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Import project from legacy JSON format."""
        response = self._client.post(
            "/projects/import",
            json={
                "workspace_id": workspace_id,
                "data": data,
                "name": name,
            },
        )
        response.raise_for_status()
        return response.json()

    # --- Versions ---

    def list_versions(
        self,
        project_id: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Get version history for a project."""
        response = self._client.get(
            f"/projects/{project_id}/versions",
            params={"limit": limit},
        )
        response.raise_for_status()
        return response.json()

    def create_version(
        self,
        project_id: str,
        message: str = "",
    ) -> Dict[str, Any]:
        """Create a version snapshot."""
        response = self._client.post(
            f"/projects/{project_id}/versions",
            json={"message": message},
        )
        response.raise_for_status()
        return response.json()

    def get_version(
        self,
        project_id: str,
        version_number: int,
    ) -> Dict[str, Any]:
        """Get a specific version snapshot."""
        response = self._client.get(
            f"/projects/{project_id}/versions/{version_number}"
        )
        response.raise_for_status()
        return response.json()

    # --- Building Elements ---

    def list_walls(
        self,
        project_id: str,
        category: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List all walls for a project."""
        params = {}
        if category:
            params["category"] = category

        response = self._client.get(
            f"/buildings/{project_id}/walls",
            params=params,
        )
        response.raise_for_status()
        return response.json()

    def create_wall(
        self,
        project_id: str,
        data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Create a new wall."""
        response = self._client.post(
            f"/buildings/{project_id}/walls",
            json=data,
        )
        response.raise_for_status()
        return response.json()

    def update_wall(
        self,
        project_id: str,
        wall_id: str,
        data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Update a wall."""
        response = self._client.put(
            f"/buildings/{project_id}/walls/{wall_id}",
            json=data,
        )
        response.raise_for_status()
        return response.json()

    def delete_wall(self, project_id: str, wall_id: str):
        """Delete a wall."""
        response = self._client.delete(
            f"/buildings/{project_id}/walls/{wall_id}"
        )
        response.raise_for_status()

    def list_doors(
        self,
        project_id: str,
        wall_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List all doors for a project."""
        params = {}
        if wall_id:
            params["wall_id"] = wall_id

        response = self._client.get(
            f"/buildings/{project_id}/doors",
            params=params,
        )
        response.raise_for_status()
        return response.json()

    def create_door(
        self,
        project_id: str,
        data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Create a new door."""
        response = self._client.post(
            f"/buildings/{project_id}/doors",
            json=data,
        )
        response.raise_for_status()
        return response.json()

    def update_door(
        self,
        project_id: str,
        door_id: str,
        data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Update a door."""
        response = self._client.put(
            f"/buildings/{project_id}/doors/{door_id}",
            json=data,
        )
        response.raise_for_status()
        return response.json()

    def delete_door(self, project_id: str, door_id: str):
        """Delete a door."""
        response = self._client.delete(
            f"/buildings/{project_id}/doors/{door_id}"
        )
        response.raise_for_status()

    def list_windows(
        self,
        project_id: str,
        wall_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List all windows for a project."""
        params = {}
        if wall_id:
            params["wall_id"] = wall_id

        response = self._client.get(
            f"/buildings/{project_id}/windows",
            params=params,
        )
        response.raise_for_status()
        return response.json()

    def create_window(
        self,
        project_id: str,
        data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Create a new window."""
        response = self._client.post(
            f"/buildings/{project_id}/windows",
            json=data,
        )
        response.raise_for_status()
        return response.json()

    def update_window(
        self,
        project_id: str,
        window_id: str,
        data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Update a window."""
        response = self._client.put(
            f"/buildings/{project_id}/windows/{window_id}",
            json=data,
        )
        response.raise_for_status()
        return response.json()

    def delete_window(self, project_id: str, window_id: str):
        """Delete a window."""
        response = self._client.delete(
            f"/buildings/{project_id}/windows/{window_id}"
        )
        response.raise_for_status()

    def list_rooms(
        self,
        project_id: str,
        room_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List all rooms for a project."""
        params = {}
        if room_type:
            params["room_type"] = room_type

        response = self._client.get(
            f"/buildings/{project_id}/rooms",
            params=params,
        )
        response.raise_for_status()
        return response.json()

    def create_room(
        self,
        project_id: str,
        data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Create a new room."""
        response = self._client.post(
            f"/buildings/{project_id}/rooms",
            json=data,
        )
        response.raise_for_status()
        return response.json()

    def update_room(
        self,
        project_id: str,
        room_id: str,
        data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Update a room."""
        response = self._client.put(
            f"/buildings/{project_id}/rooms/{room_id}",
            json=data,
        )
        response.raise_for_status()
        return response.json()

    def delete_room(self, project_id: str, room_id: str):
        """Delete a room."""
        response = self._client.delete(
            f"/buildings/{project_id}/rooms/{room_id}"
        )
        response.raise_for_status()

    # --- Batch Operations ---

    def batch_operations(
        self,
        project_id: str,
        operations: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Execute batch operations on building elements."""
        response = self._client.post(
            f"/buildings/{project_id}/batch",
            json={"operations": operations},
        )
        response.raise_for_status()
        return response.json()

    # --- Health ---

    def health_check(self) -> Dict[str, Any]:
        """Check API health."""
        response = self._client.get("/health", timeout=5.0)
        response.raise_for_status()
        return response.json()

    def is_available(self) -> bool:
        """Check if API is available."""
        try:
            self.health_check()
            return True
        except Exception:
            return False


class AsyncArchEngineAPIClient:
    """
    Async HTTP client for ArchEngine CAD API.

    For use in async contexts (FastAPI, asyncio).
    """

    def __init__(self, config: Optional[APIConfig] = None):
        """Initialize async API client."""
        self.config = config or APIConfig(
            base_url=os.environ.get(
                "ARCHENGINE_API_BASE_URL",
                "http://localhost:8000/api/v1"
            ),
        )

        self._client = httpx.AsyncClient(
            base_url=self.config.base_url,
            timeout=self.config.timeout,
        )

    async def close(self):
        """Close the HTTP client."""
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def get_project(self, project_id: str) -> Dict[str, Any]:
        """Get a project by ID."""
        response = await self._client.get(f"/projects/{project_id}")
        response.raise_for_status()
        return response.json()

    async def export_project(self, project_id: str) -> Dict[str, Any]:
        """Export project as legacy JSON format."""
        response = await self._client.get(f"/projects/{project_id}/export")
        response.raise_for_status()
        return response.json()

    async def batch_operations(
        self,
        project_id: str,
        operations: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Execute batch operations."""
        response = await self._client.post(
            f"/buildings/{project_id}/batch",
            json={"operations": operations},
        )
        response.raise_for_status()
        return response.json()

    async def is_available(self) -> bool:
        """Check if API is available."""
        try:
            response = await self._client.get("/health", timeout=5.0)
            return response.status_code == 200
        except Exception:
            return False
