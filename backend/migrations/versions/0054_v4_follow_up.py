"""v4 이어 하기: 먼저 말 건 줄 트리거에 follow_up(사람이 누른 카드 뒤 코드가 바로 내미는 다음 카드).

Revision ID: 0054_v4_follow_up
Revises: 0053_v4_diy_paper_buy
Create Date: 2026-11-24

- 잠긴 집 정보를 고치려다 실측 요청 취소 카드가 나간 뒤, 묶음이 모두 취소되면 집 정보 카드를 줄 하나로 내밀어요.
- 되돌리면 follow_up 줄을 지우고 옛 CHECK로 돌린다(달린 승인 카드는 그대로).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0054_v4_follow_up"
down_revision: str | Sequence[str] | None = "0053_v4_diy_paper_buy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_TRIGGERS = (
    "trigger in ('visit_offered', 'quote_sent', 'dates_proposed', 'work_eve', 'no_pick',"
    " 'visit_requested', 'visit_picked', 'deal_confirmed', 'vendor_out', 'extra_added',"
    " 'work_done', 'prep_week', 'dates_requested', 'quote_due')"
)
NEW_TRIGGERS = (
    "trigger in ('visit_offered', 'quote_sent', 'dates_proposed', 'work_eve', 'no_pick',"
    " 'visit_requested', 'visit_picked', 'deal_confirmed', 'vendor_out', 'extra_added',"
    " 'work_done', 'prep_week', 'dates_requested', 'quote_due', 'follow_up')"
)


def _swap(sql: str) -> None:
    op.drop_constraint(op.f("ck_assistant_nudges_trigger"), "assistant_nudges", type_="check")
    op.create_check_constraint(op.f("ck_assistant_nudges_trigger"), "assistant_nudges", sql)


def upgrade() -> None:
    _swap(NEW_TRIGGERS)


def downgrade() -> None:
    op.execute("delete from assistant_nudges where trigger = 'follow_up'")
    _swap(OLD_TRIGGERS)
