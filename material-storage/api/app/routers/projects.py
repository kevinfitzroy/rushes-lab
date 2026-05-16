"""projects router — CRUD + OpenFGA tuple wiring。"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.db.tables import Project
from app.models import ProjectCreateIn, ProjectOut

router = APIRouter()


@router.post("", response_model=ProjectOut, status_code=201)
async def create_project(
    payload: ProjectCreateIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ProjectOut:
    """新建 project + 写 OpenFGA organization → project tuple。"""
    project = Project(
        id=uuid.uuid4(),
        organization_id=payload.organization_id,
        code=payload.code,
        name=payload.name,
        description=payload.description,
        minio_bucket=payload.minio_bucket,
    )
    db.add(project)
    try:
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        raise HTTPException(400, detail=f"project code conflict or invalid org: {e.orig}") from e

    permissions = request.app.state.permissions
    await permissions.bootstrap_project(
        project_id=str(project.id), organization_id=str(project.organization_id)
    )

    await db.refresh(project)
    return ProjectOut.model_validate(project)


@router.get("", response_model=list[ProjectOut])
async def list_projects(
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
    offset: int = 0,
) -> list[ProjectOut]:
    """Phase B-2 first batch 不 enforce OpenFGA filter,Phase B-3 加。"""
    stmt = (
        select(Project)
        .where(Project.is_archived.is_(False))
        .order_by(Project.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    res = await db.execute(stmt)
    rows = res.scalars().all()
    return [ProjectOut.model_validate(r) for r in rows]


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> ProjectOut:
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "project not found")
    return ProjectOut.model_validate(project)
