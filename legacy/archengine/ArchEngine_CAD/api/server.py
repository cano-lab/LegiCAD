"""
FastAPI server for ArchEngine CAD.

Run with: uvicorn api.server:app --reload
"""
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from database.engine import init_db_async, close_db_async


def create_app(
    title: str = "ArchEngine CAD API",
    debug: bool = False,
) -> FastAPI:
    """
    Create and configure the FastAPI application.

    Args:
        title: API title for documentation
        debug: Enable debug mode
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Application lifespan events."""
        # Startup
        await init_db_async(echo=debug)
        yield
        # Shutdown
        await close_db_async()

    app = FastAPI(
        title=title,
        description="REST API for ArchEngine CAD application",
        version="1.0.0",
        lifespan=lifespan,
        debug=debug,
    )

    # CORS middleware for web clients
    app.add_middleware(
        CORSMiddleware,
        allow_origins=os.environ.get(
            "ARCHENGINE_CORS_ORIGINS",
            "http://localhost:3000,http://localhost:8080"
        ).split(","),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Global exception handler
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        """Handle unexpected exceptions."""
        return JSONResponse(
            status_code=500,
            content={
                "detail": str(exc) if debug else "Internal server error",
                "type": type(exc).__name__,
            },
        )

    # Include routers
    from api.routes.projects import router as projects_router
    from api.routes.buildings import router as buildings_router
    from api.routes.solvers import router as solvers_router

    app.include_router(projects_router, prefix="/api/v1")
    app.include_router(buildings_router, prefix="/api/v1")
    app.include_router(solvers_router, prefix="/api/v1")

    # Health check endpoint
    @app.get("/health")
    async def health_check():
        """Health check endpoint."""
        return {"status": "healthy", "version": "1.0.0"}

    # Root endpoint
    @app.get("/")
    async def root():
        """Root endpoint with API info."""
        return {
            "name": "ArchEngine CAD API",
            "version": "1.0.0",
            "docs": "/docs",
            "openapi": "/openapi.json",
        }

    return app


# Default application instance
app = create_app(debug=os.environ.get("ARCHENGINE_DEBUG", "").lower() == "true")


def run_server(
    host: str = "127.0.0.1",
    port: int = 8000,
    reload: bool = False,
):
    """
    Run the API server.

    Args:
        host: Host to bind to
        port: Port to listen on
        reload: Enable auto-reload for development
    """
    import uvicorn

    uvicorn.run(
        "api.server:app",
        host=host,
        port=port,
        reload=reload,
    )


if __name__ == "__main__":
    run_server(reload=True)
