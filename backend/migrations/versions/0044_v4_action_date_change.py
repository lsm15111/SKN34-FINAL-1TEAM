"""v4 비서 행동 종류에 공사 날짜 바꾸기 요청(date_change)을 더한다

Revision ID: 0044_v4_action_date_change
Revises: 0043_v4_project_demolition
Create Date: 2026-11-21

- 고객이 승인하면 POST …/date-requests와 같은 schedule service 함수가 요청을 넣는다(propose_date_change).
- 되돌리면 date_change 행을 지우고 CHECK를 옛 목록으로 돌린다.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0044_v4_action_date_change"
down_revision: str | Sequence[str] | None = "0043_v4_project_demolition"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_KINDS = (
    "kind in ('home_info', 'visit_request', 'visit_slot', 'vendor_confirm', 'dates_accept',"
    " 'delay_accept', 'window_answer', 'decline', 'dates')"
)
NEW_KINDS = (
    "kind in ('home_info', 'visit_request', 'visit_slot', 'vendor_confirm', 'dates_accept',"
    " 'delay_accept', 'date_change', 'window_answer', 'decline', 'dates')"
)


def upgrade() -> None:
    op.drop_constraint(op.f("ck_assistant_actions_kind"), "assistant_actions", type_="check")
    op.create_check_constraint(op.f("ck_assistant_actions_kind"), "assistant_actions", NEW_KINDS)


def downgrade() -> None:
    op.execute("delete from assistant_actions where kind = 'date_change'")
    op.drop_constraint(op.f("ck_assistant_actions_kind"), "assistant_actions", type_="check")
    op.create_check_constraint(op.f("ck_assistant_actions_kind"), "assistant_actions", OLD_KINDS)
