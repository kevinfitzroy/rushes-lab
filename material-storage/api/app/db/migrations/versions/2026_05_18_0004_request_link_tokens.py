"""request_link_tokens 表 — #112 admin 生成"申请入口"分享链接。

接收者点开链接 → 看到资源元信息 → 走正常 approval 流程(不是直接授权)。
跟 share token(audit_events 反范式存)语义独立,所以独立表(advisor 决定避免污染 share)。

Revision ID: 20260518_0004
Revises: 20260516_0003
Create Date: 2026-05-18
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260518_0004"
down_revision: str | Sequence[str] | None = "20260516_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "request_link_tokens",
        sa.Column("token", sa.String(64), primary_key=True),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("allowed_actions", postgresql.ARRAY(sa.String(16)), nullable=False),
        sa.Column("inviter_user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        # nullable = 任意登录用户;非空 = 限定只此 open_id 可用
        sa.Column("receiver_open_id", sa.String(64), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        # 多次使用,记首次:advisor 决策 default multi-use,后续可加 single_use 字段
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_request_link_target_type", "request_link_tokens",
        "target_type IN ('sensitive_folder', 'asset', 'project', 'folder')",
    )
    op.create_index("ix_request_link_target", "request_link_tokens",
                    ["target_type", "target_id"])
    op.create_index("ix_request_link_inviter", "request_link_tokens", ["inviter_user_id"])
    op.create_index("ix_request_link_expires", "request_link_tokens", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_request_link_expires", table_name="request_link_tokens")
    op.drop_index("ix_request_link_inviter", table_name="request_link_tokens")
    op.drop_index("ix_request_link_target", table_name="request_link_tokens")
    op.drop_constraint("ck_request_link_target_type", "request_link_tokens", type_="check")
    op.drop_table("request_link_tokens")
