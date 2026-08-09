"""盲搜 user_labels 模糊匹配的 array_to_string 表达式 trgm 索引(#151 review F1/F8)

Revision ID: 20260809_0011
Revises: 20260809_0010
Create Date: 2026-08-09

review-2026-08-09-wave1-2.md 的 F1(P0)+ F8(P2)修复:
- F1:label_fuzzy 从 unnest EXISTS(渲染出的 `lbl.unnest_1` 列名 PG 不认,
  GET /assets/search 每次 500)改为 `array_to_string(user_labels,' ') ILIKE`。
- F8:该表达式配 GIN trgm 索引,让盲搜的标签模糊分支可走索引
  (原先 `q = ANY(array)` 不走 GIN array_ops,unnest 不可索引,四路 OR 只能全表扫)。
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260809_0011"
down_revision: str | Sequence[str] | None = "20260809_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_asset_user_labels_str_trgm",
        "assets",
        [sa.literal_column("array_to_string(user_labels, ' ')")],
        postgresql_using="gin",
        postgresql_ops={"array_to_string(user_labels, ' ')": "gin_trgm_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_asset_user_labels_str_trgm", table_name="assets")
