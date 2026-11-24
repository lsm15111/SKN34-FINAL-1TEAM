"""v4 먼저 말 걸기: 트리거에 visit_proposed(업체가 실측 다른 날을 제안함 → 고객 대화 줄)를 더한다.

Revision ID: 0062_v4_visit_proposed_nudge
Revises: 0061_v4_quote_check
Create Date: 2026-11-25

- 되돌리면 visit_proposed 줄을 지우고 옛 CHECK로 돌린다.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0062_v4_visit_proposed_nudge"
down_revision: str | Sequence[str] | None = "0061_v4_quote_check"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_TRIGGERS = (
    "trigger in ('visit_offered', 'quote_sent', 'dates_proposed', 'work_eve', 'no_pick',"
    " 'visit_requested', 'visit_picked', 'deal_confirmed', 'vendor_out', 'extra_added',"
    " 'work_done', 'prep_week', 'dates_requested', 'quote_due', 'follow_up')"
)
NEW_TRIGGERS = (
    "trigger in ('visit_offered', 'quote_sent', 'dates_proposed', 'work_eve', 'no_pick',"
    " 'visit_requested', 'visit_picked', 'deal_confirmed', 'vendor_out', 'extra_added',"
    " 'work_done', 'prep_week', 'dates_requested', 'quote_due', 'follow_up', 'visit_proposed')"
)


def _swap(sql: str) -> None:
    op.drop_constraint(op.f("ck_assistant_nudges_trigger"), "assistant_nudges", type_="check")
    op.create_check_constraint(op.f("ck_assistant_nudges_trigger"), "assistant_nudges", sql)


def upgrade() -> None:
    _swap(NEW_TRIGGERS)


def downgrade() -> None:
    op.execute("delete from assistant_nudges where trigger = 'visit_proposed'")
    _swap(OLD_TRIGGERS)
