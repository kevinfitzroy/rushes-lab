"""组织(default org)查询 — 原 contact_sync.get_default_organization 迁移而来(#154 删飞书后独立成模块)。

飞书下线(ADR-0007 / #154)后组织轴保留:OpenFGA `organization:<tenant_key>` 仍是
权限体系的根节点;`organizations.feishu_tenant_key` 列保留只读(历史对照)。
"""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.tables import Organization


async def get_default_organization(db: AsyncSession) -> tuple[uuid.UUID, str] | None:
    """从 settings.default_organization_id 拿 + db 查 tenant_key。"""
    from app.settings import get_settings
    settings = get_settings()
    if not settings.default_organization_id:
        return None
    org_id = uuid.UUID(settings.default_organization_id)
    org = await db.get(Organization, org_id)
    if org is None:
        return None
    tenant_key = org.feishu_tenant_key or str(org_id)
    return org_id, tenant_key
