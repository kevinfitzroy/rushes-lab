"""本地用户/组管理后台地基 — ADR-0007(issue #150)

Revision ID: 20260809_0008
Revises: 20260809_0006
Create Date: 2026-08-09

- users.feishu_open_id 改 nullable:本地新建用户无飞书身份(ADR-0007「新用户不再有飞书字段」,
  老飞书用户保留历史对照,只读不删)
- users.username 新列(unique, nullable):本地登录名(拼音/工号友好,不强制邮箱;
  P1 本地认证 #149 登录用;老飞书用户为 NULL)
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260809_0008"
down_revision: str | Sequence[str] | None = "20260809_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("users", "feishu_open_id", nullable=True)
    op.add_column("users", sa.Column("username", sa.String(64), unique=True, nullable=True))
    op.create_index("ix_users_username", "users", ["username"])


def downgrade() -> None:
    op.drop_index("ix_users_username", table_name="users")
    op.drop_column("users", "username")
    # 回滚前清掉本地新建的无飞书用户(否则 not-null 约束过不去)
    op.execute("DELETE FROM users WHERE feishu_open_id IS NULL")
    op.alter_column("users", "feishu_open_id", nullable=False)
