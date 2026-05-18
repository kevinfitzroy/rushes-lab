"""approvals CHECK 加 'folder' — #129 支持 folder 级临时 download 申请。

Revision ID: 20260518_0005
Revises: 20260518_0004
Create Date: 2026-05-18
"""
from collections.abc import Sequence

from alembic import op

revision: str = "20260518_0005"
down_revision: str | Sequence[str] | None = "20260518_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_approval_target_type", "approvals", type_="check")
    op.create_check_constraint(
        "ck_approval_target_type", "approvals",
        "target_type IN ('sensitive_folder', 'asset', 'project', 'folder')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_approval_target_type", "approvals", type_="check")
    op.create_check_constraint(
        "ck_approval_target_type", "approvals",
        "target_type IN ('sensitive_folder', 'asset', 'project')",
    )
