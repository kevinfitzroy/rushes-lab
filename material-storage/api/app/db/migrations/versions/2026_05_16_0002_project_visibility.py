"""project.visibility + folders.is_sensitive deprecation — Phase B-2 next iter

Revision ID: 20260516_0002
Revises: 20260516_0001
Create Date: 2026-05-16

变更:
- 加 projects.visibility 字段:public / private(default) / stealth
  控制 metadata 列表可见性(material-storage backend 在 list_projects filter)
- 保留 folders.is_sensitive 字段,但**不再驱动 OpenFGA model 区分**(去 sensitive_folder type)
  字段保留作 future cleanup(可下个 migration drop)
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260516_0002"
down_revision: str | Sequence[str] | None = "20260516_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # add projects.visibility(default 'private')
    op.add_column(
        "projects",
        sa.Column(
            "visibility",
            sa.String(16),
            server_default=sa.text("'private'"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_project_visibility",
        "projects",
        "visibility IN ('public', 'private', 'stealth')",
    )
    op.create_index("ix_project_visibility", "projects", ["visibility"])


def downgrade() -> None:
    op.drop_index("ix_project_visibility", table_name="projects")
    op.drop_constraint("ck_project_visibility", "projects", type_="check")
    op.drop_column("projects", "visibility")
