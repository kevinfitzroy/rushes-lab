"""asset notes(备注)+ trgm 索引 — issue #151 标签 + 盲搜

Revision ID: 20260809_0007
Revises: 20260809_0006
Create Date: 2026-08-09

- assets.notes TEXT:素材备注(盲搜匹配范围:文件名 + user_labels + 备注)
- assets.notes pg_trgm GIN 索引(与 filename 同款;百万行 ILIKE 走索引)
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260809_0007"
down_revision: str | Sequence[str] | None = "20260809_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("assets", sa.Column("notes", sa.Text(), nullable=True))
    # pg_trgm 已由 0006 建扩展;同款 GIN trgm 索引支撑 notes ILIKE 盲搜
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_index(
        "ix_asset_notes_trgm", "assets", ["notes"],
        postgresql_using="gin",
        postgresql_ops={"notes": "gin_trgm_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_asset_notes_trgm", table_name="assets")
    op.drop_column("assets", "notes")
