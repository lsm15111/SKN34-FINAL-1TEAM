"""v4 비서 기억 키에 이사 · 입주 때(move_in)를 더한다

Revision ID: 0048_v4_memory_move_in
Revises: 0047_v4_visit_diy
Create Date: 2026-11-22

- 고객이 말한 이사 · 입주 때('12월 말 이사')를 기억해 공사 날짜와 견줄 때 다시 묻지 않게 한다(QA r1 c1).
- 되돌리면 move_in 줄을 지우고 CHECK를 옛 목록으로 돌린다.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0048_v4_memory_move_in"
down_revision: str | Sequence[str] | None = "0047_v4_visit_diy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_KEYS = (
    "key in ('avail_days', 'avail_half', 'living', 'style', 'material', 'priority', 'pet', 'diy')"
)
NEW_KEYS = (
    "key in ('avail_days', 'avail_half', 'living', 'style', 'material', 'priority', 'pet', 'diy',"
    " 'move_in')"
)


def upgrade() -> None:
    op.drop_constraint(op.f("ck_assistant_memory_key"), "assistant_memory", type_="check")
    op.create_check_constraint(op.f("ck_assistant_memory_key"), "assistant_memory", NEW_KEYS)


def downgrade() -> None:
    op.execute("delete from assistant_memory where key = 'move_in'")
    op.drop_constraint(op.f("ck_assistant_memory_key"), "assistant_memory", type_="check")
    op.create_check_constraint(op.f("ck_assistant_memory_key"), "assistant_memory", OLD_KEYS)
