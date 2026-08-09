"""通用 OIDC provider 留口 — users.oidc_sub(issue #154)

Revision ID: 20260809_0010
Revises: 20260809_0008
Create Date: 2026-08-09

- users.oidc_sub 新列(unique, nullable):通用 OIDC 登录的身份匹配键
  (ADR-0007 决策 3;飞书 OIDC 抽象为 provider 配置后,OIDC 用户按 sub 匹配)。
  默认不配置任何 provider = 纯本地登录,该列保持 NULL。
- users.feishu_open_id / feishu_union_id 列保留只读(历史对照),不删。
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260809_0010"
down_revision: str | Sequence[str] | None = "20260809_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("oidc_sub", sa.String(255), unique=True, nullable=True))
    op.create_index("ix_users_oidc_sub", "users", ["oidc_sub"])


def downgrade() -> None:
    op.drop_index("ix_users_oidc_sub", table_name="users")
    op.drop_column("users", "oidc_sub")
