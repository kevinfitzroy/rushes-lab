"""按 target_type 反查资源名 + 父项目 — approval / request-link 共用 (#136 #137)。

approval / request-link 都需要"target_type + target_id → 人类可读名 + 父项目导航",
抽成一个 helper 避免两处 type-dispatch 反查逻辑漂移。
"""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.tables import Asset, Folder, Project


async def resolve_target_name_and_project(
    db: AsyncSession,
    target_type: str,
    target_id: uuid.UUID,
) -> tuple[str | None, uuid.UUID | None]:
    """返 (target_name, parent_project_id)。

    - folder / sensitive_folder → (folder.name, folder.project_id)
    - asset                     → (asset.filename, asset 所属 folder 的 project_id)
    - project                   → (project.name, project.id 自身)
    缺失资源返 (None, None) — 调用方按需 fallback。
    """
    if target_type in ("folder", "sensitive_folder"):
        f = await db.get(Folder, target_id)
        return (f.name, f.project_id) if f else (None, None)
    if target_type == "asset":
        a = await db.get(Asset, target_id)
        if a is None:
            return (None, None)
        f = await db.get(Folder, a.folder_id)
        return (a.filename, f.project_id if f else None)
    if target_type == "project":
        p = await db.get(Project, target_id)
        return (p.name, target_id) if p else (None, None)
    return (None, None)
