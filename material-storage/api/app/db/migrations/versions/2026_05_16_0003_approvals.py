"""approvals 表 — Phase B-2 iter6。

Revision ID: 20260516_0003
Revises: 20260516_0002
Create Date: 2026-05-16
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260516_0003"
down_revision: str | Sequence[str] | None = "20260516_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "approvals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("applicant_user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("duration_seconds", sa.Integer, nullable=True),
        sa.Column("reason", sa.String(2000), nullable=False),
        sa.Column("status", sa.String(16), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("feishu_instance_code", sa.String(64), nullable=True),
        sa.Column("approver_user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.String(2000), nullable=True),
        sa.Column("granted_tuple_ref", postgresql.JSONB,
                  server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.create_unique_constraint("uq_approval_feishu_instance",
                                "approvals", ["feishu_instance_code"])
    op.create_check_constraint(
        "ck_approval_target_type", "approvals",
        "target_type IN ('sensitive_folder', 'asset', 'project')",
    )
    op.create_check_constraint(
        "ck_approval_action", "approvals",
        "action IN ('download', 'access')",
    )
    op.create_check_constraint(
        "ck_approval_status", "approvals",
        "status IN ('pending', 'approved', 'rejected', 'revoked', 'expired')",
    )
    op.create_index("ix_approval_applicant", "approvals", ["applicant_user_id"])
    op.create_index("ix_approval_target_id", "approvals", ["target_id"])
    op.create_index("ix_approval_status_created", "approvals", ["status", "created_at"])
    op.create_index("ix_approval_target", "approvals", ["target_type", "target_id"])
    op.create_index("ix_approval_feishu_instance", "approvals", ["feishu_instance_code"])


def downgrade() -> None:
    op.drop_index("ix_approval_feishu_instance", table_name="approvals")
    op.drop_index("ix_approval_target", table_name="approvals")
    op.drop_index("ix_approval_status_created", table_name="approvals")
    op.drop_index("ix_approval_target_id", table_name="approvals")
    op.drop_index("ix_approval_applicant", table_name="approvals")
    op.drop_constraint("ck_approval_status", "approvals", type_="check")
    op.drop_constraint("ck_approval_action", "approvals", type_="check")
    op.drop_constraint("ck_approval_target_type", "approvals", type_="check")
    op.drop_constraint("uq_approval_feishu_instance", "approvals", type_="unique")
    op.drop_table("approvals")
