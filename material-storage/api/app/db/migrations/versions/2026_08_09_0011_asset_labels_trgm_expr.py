"""盲搜 user_labels 模糊匹配的 trgm 表达式索引(#151 review F1/F8)

Revision ID: 20260809_0011
Revises: 20260809_0009
Create Date: 2026-08-09

review-2026-08-09-wave1-2.md 的 F1(P0)+ F8(P2)修复:
- F1:label_fuzzy 从 unnest EXISTS(渲染出的 `lbl.unnest_1` 列名 PG 不认,
  GET /assets/search 每次 500)改为整数组拼串后 ILIKE。
- F8:该表达式配 GIN trgm 索引,让盲搜的标签模糊分支可走索引
  (原先 `q = ANY(array)` 不走 GIN array_ops,unnest 不可索引,四路 OR 只能全表扫)。

⚠️ 为什么要包一层 `ms_labels_text()` 而不是直接索引 `array_to_string(user_labels,' ')`:
  PG 里 `array_to_string(anyarray, text)` 是 **STABLE**(provolatile='s',因为对
  anyarray 而言要调元素类型的输出函数),直接进索引表达式会被拒:

      ERROR:  functions in index expression must be marked IMMUTABLE

  本 revision 首版就是这么写的,`alembic upgrade head` 必然失败(PG16 实测)。
  固定成 varchar[] 之后拼串是确定性的,按 PG 社区标准做法用 IMMUTABLE SQL 包装函数落地。
  **查询侧必须用同一个函数**(`func.ms_labels_text(...)`,见 routers/assets.py),
  表达式不一致索引就不会被命中。

注:0009(#168 的 unique 约束)与 0011 并行开发(都基于 0010),merge 后曾出现双 head;
本 revision 的 down_revision 已调整为 20260809_0009,恢复线性链 0006→0007→0008→0010→0009→0011。
"""
from collections.abc import Sequence

from alembic import op

revision: str = "20260809_0011"
down_revision: str | Sequence[str] | None = "20260809_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FN_SIGNATURE = "ms_labels_text(character varying[])"


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION ms_labels_text(labels character varying[])
        RETURNS text
        LANGUAGE sql
        IMMUTABLE STRICT PARALLEL SAFE
        AS $$ SELECT array_to_string(labels, ' ') $$
        """
    )
    op.execute(
        "CREATE INDEX ix_asset_user_labels_str_trgm ON assets "
        "USING gin (ms_labels_text(user_labels) gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_asset_user_labels_str_trgm")
    op.execute(f"DROP FUNCTION IF EXISTS {_FN_SIGNATURE}")
