"""
Project API routes.
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from database.engine import get_db
from database.models.project import Project, ProjectVersion
from database.repository.project import AsyncProjectRepository
from api.schemas.project import (
    ProjectCreate,
    ProjectUpdate,
    ProjectResponse,
    ProjectListResponse,
    ProjectExport,
    ProjectImport,
    VersionResponse,
    VersionCreate,
)

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=ProjectListResponse)
async def list_projects(
    workspace_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    include_deleted: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """List all projects in a workspace."""
    repo = AsyncProjectRepository(db)
    projects = await repo.get_by_workspace(
        workspace_id=workspace_id,
        skip=skip,
        limit=limit,
        include_deleted=include_deleted,
    )

    return ProjectListResponse(
        items=[ProjectResponse.model_validate(p) for p in projects],
        total=len(projects),  # TODO: Add count query
        skip=skip,
        limit=limit,
    )


@router.post("", response_model=ProjectResponse, status_code=201)
async def create_project(
    project: ProjectCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new project."""
    repo = AsyncProjectRepository(db)

    db_project = Project(
        workspace_id=project.workspace_id,
        name=project.name,
        building_type=project.building_type,
        width=project.width,
        depth=project.depth,
        stories=project.stories,
        wall_height=project.wall_height,
        qbd_answers=project.qbd_answers or {},
        settings=project.settings or {},
    )

    created = await repo.create(db_project)
    await repo.commit()

    return ProjectResponse.model_validate(created)


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get a project by ID."""
    repo = AsyncProjectRepository(db)
    project = await repo.get(project_id)

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    return ProjectResponse.model_validate(project)


@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str,
    updates: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a project."""
    repo = AsyncProjectRepository(db)
    project = await repo.get(project_id)

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    update_data = updates.model_dump(exclude_unset=True)
    updated = await repo.update(project, update_data)
    await repo.commit()

    return ProjectResponse.model_validate(updated)


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: str,
    hard: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """Delete a project (soft delete by default)."""
    repo = AsyncProjectRepository(db)
    project = await repo.get(project_id)

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if hard:
        await repo.delete(project)
    else:
        await repo.soft_delete(project)

    await repo.commit()


@router.get("/{project_id}/export", response_model=ProjectExport)
async def export_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Export project as legacy JSON format."""
    repo = AsyncProjectRepository(db)
    project = await repo.get_with_elements(project_id)

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    return ProjectExport(**project.to_legacy_dict())


@router.post("/import", response_model=ProjectResponse, status_code=201)
async def import_project(
    import_data: ProjectImport,
    db: AsyncSession = Depends(get_db),
):
    """Import project from legacy JSON format."""
    from database.repository.project import ProjectRepository
    from database.engine import get_session

    # Use sync repository for complex import with relationships
    sync_session = get_session()
    try:
        repo = ProjectRepository(sync_session)

        data = import_data.data
        if import_data.name:
            data["name"] = import_data.name

        project = repo.import_from_dict(data, import_data.workspace_id)
        repo.commit()

        return ProjectResponse.model_validate(project)
    finally:
        sync_session.close()


@router.get("/{project_id}/versions", response_model=list[VersionResponse])
async def list_versions(
    project_id: str,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Get version history for a project."""
    from sqlalchemy import select

    stmt = select(ProjectVersion).where(
        ProjectVersion.project_id == project_id
    ).order_by(ProjectVersion.version_number.desc()).limit(limit)

    result = await db.execute(stmt)
    versions = result.scalars().all()

    return [VersionResponse.model_validate(v) for v in versions]


@router.post("/{project_id}/versions", response_model=VersionResponse, status_code=201)
async def create_version(
    project_id: str,
    version_data: VersionCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a version snapshot of a project."""
    repo = AsyncProjectRepository(db)
    project = await repo.get_with_elements(project_id)

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Get next version number
    from sqlalchemy import select, func

    stmt = select(func.max(ProjectVersion.version_number)).where(
        ProjectVersion.project_id == project_id
    )
    result = await db.execute(stmt)
    max_version = result.scalar() or 0

    version = ProjectVersion(
        project_id=project_id,
        version_number=max_version + 1,
        snapshot=project.to_legacy_dict(),
        message=version_data.message,
    )

    db.add(version)
    await db.commit()
    await db.refresh(version)

    return VersionResponse.model_validate(version)


@router.get("/{project_id}/versions/{version_number}", response_model=ProjectExport)
async def get_version(
    project_id: str,
    version_number: int,
    db: AsyncSession = Depends(get_db),
):
    """Get a specific version snapshot."""
    from sqlalchemy import select, and_

    stmt = select(ProjectVersion).where(
        and_(
            ProjectVersion.project_id == project_id,
            ProjectVersion.version_number == version_number
        )
    )

    result = await db.execute(stmt)
    version = result.scalar_one_or_none()

    if not version:
        raise HTTPException(status_code=404, detail="Version not found")

    return ProjectExport(**version.snapshot)
