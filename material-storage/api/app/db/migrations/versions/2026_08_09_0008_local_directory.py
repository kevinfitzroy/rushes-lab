"""本地用户/组管理后台地基 — ADR-0007(issue #150)

Revision ID: 20260809_0008
Revises: 20260809_0007
Create Date: 2026-08-09

- users.feishu_open_id 改 nullable:本地新建用户无飞书身份(ADR-0007「新用户不再有飞书字段」,
  老飞书用户保留历史对照,只读不删)
- users.username 新列(unique, nullable):本地登录名(拼音/工号友好,不强制邮箱;
  P1 本地认证 #149 登录用;老飞书用户为 NULL)

注:#151 的 0007_asset_notes 与 0008 并行开发(都基于 0006),merge 后曾出现双 head;
本 revision 的 down_revision 已调整为 20260809_0007,恢复线性链 0006→0007→0008。
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260809_0008"
down_revision: str | Sequence[str] | None = "20260809_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("users", "feishu_open_id", nullable=True)
    op.add_column("users", sa.Column("username", sa.String(64), unique=True, nullable=True))
    op.create_index("ix_users_username", "users", ["username"])


def downgrade() -> None:
    op.drop_index("ix_users_username", table_name="users")
    op.drop_column("users", "username")
    # ⚠️ 破坏性回滚(review F18):会删掉全部本地创建的用户(feishu_open_id IS NULL,
    # 即 #150 之后 admin 后台建的所有账号);且 approvals.applicant_user_id 等 FK
    # 为 RESTRICT,有本地用户被引用时此语句直接失败。仅限开发环境回滚;
    # 生产一旦开过本地账号,不要 downgrade 到本版本。
    op.execute("DELETE FROM users WHERE feishu_open_id IS NULL")
    op.alter_column("users", "feishu_open_id", nullable=False)
