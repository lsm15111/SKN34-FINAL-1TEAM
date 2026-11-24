"""v4 받은 견적서 점검: llm_usage.purpose에 quote_check(외부 견적서 글 · 가린 사진에서 줄 뽑기)를 더한다.

Revision ID: 0061_v4_quote_check
Revises: 0060_v4_prework
Create Date: 2026-11-25

- 되돌리면 새 값 줄을 지우고 CHECK를 옛 목록으로 돌린다.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0061_v4_quote_check"
down_revision: str | Sequence[str] | None = "0060_v4_prework"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_PURPOSES = (
    "('assistant', 'floorplan', 'nudge', 'memory', 'v2_chat', 'research', 'orchestrator',"
    " 'trade', 'quote_explanation', 'schedule', 'composer', 'general', 'planner', 'judge',"
    " 'check')"
)
# llm_usage.purpose 목록(usage/models.py PURPOSES와 같다, 시험이 맞춰 본다)
PURPOSES = (
    "('assistant', 'floorplan', 'nudge', 'memory', 'v2_chat', 'research', 'quote_check',"
    " 'orchestrator', 'trade', 'quote_explanation', 'schedule', 'composer', 'general',"
    " 'planner', 'judge', 'check')"
)


def _swap(sql: str) -> None:
    op.drop_constraint(op.f("ck_llm_usage_purpose"), "llm_usage", type_="check")
    op.create_check_constraint(op.f("ck_llm_usage_purpose"), "llm_usage", sql)


def upgrade() -> None:
    _swap(f"purpose in {PURPOSES}")


def downgrade() -> None:
    op.execute("delete from llm_usage where purpose = 'quote_check'")
    _swap(f"purpose in {OLD_PURPOSES}")
