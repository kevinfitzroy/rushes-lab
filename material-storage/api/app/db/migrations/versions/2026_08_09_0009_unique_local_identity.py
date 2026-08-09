"""本地身份键补 DB 层 UNIQUE — users.username / users.oidc_sub(review F3)

Revision ID: 20260809_0009
Revises: 20260809_0010
Create Date: 2026-08-09

背景:0008 / 0010 用 `op.add_column(unique=True)` 只发普通 ALTER COLUMN,
不会渲染 UNIQUE;随后 `ix_users_username` / `ix_users_oidc_sub` 都是普通 btree。
后果:
  - create_directory_user 的"先 SELECT 再 INSERT"重复检查在并发下可产生同名 username;
  - OIDC 留口启用后 upsert_user_from_userinfo 按 oidc_sub 匹配,遇重复行抛
    MultipleResultsFound → 登录 500。
修复:去掉冗余普通索引,改为 DB 层唯一约束(PG 约束自带唯一索引,查询语义等价)。
"""
from collections.abc import Sequence

from alembic import op

revision: str = "20260809_0009"
down_revision: str | Sequence[str] | None = "20260809_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_users_username", table_name="users")
    op.drop_index("ix_users_oidc_sub", table_name="users")
    op.create_unique_constraint("uq_users_username", "users", ["username"])
    op.create_unique_constraint("uq_users_oidc_sub", "users", ["oidc_sub"])


def downgrade() -> None:
    op.drop_constraint("uq_users_username", "users", type_="unique")
    op.drop_constraint("uq_users_oidc_sub", "users", type_="unique")
    op.create_index("ix_users_username", "users", ["username"])
    op.create_index("ix_users_oidc_sub", "users", ["oidc_sub"])
