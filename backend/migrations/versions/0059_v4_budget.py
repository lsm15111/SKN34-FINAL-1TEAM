"""v4 비서 행동 종류에 희망 예산(budget)을 더한다

Revision ID: 0059_v4_budget
Revises: 0058_v4_audit_agent
Create Date: 2026-11-25

- assistant_actions.kind: budget(고객이 승인하면 project.service.set_budget이 집 정보 '예산' 칸을 바꾼다).
- 값 꼴은 projects.budget_won CHECK(0024: 10만 원 ~ 100억 원 · 만 원 단위)가 그대로 지킨다.
- 되돌리면 budget 행을 지우고 CHECK를 옛 목록으로 돌린다.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0059_v4_budget"
down_revision: str | Sequence[str] | None = "0058_v4_audit_agent"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_KINDS = (
    "kind in ('home_info', 'visit_request', 'visit_slot', 'vendor_confirm', 'dates_accept',"
    " 'delay_accept', 'date_change', 'window_answer', 'decline', 'dates', 'extra_answer',"
    " 'work_check', 'visit_again', 'visit_cancel')"
)
NEW_KINDS = (
    "kind in ('home_info', 'visit_request', 'visit_slot', 'vendor_confirm', 'dates_accept',"
    " 'delay_accept', 'date_change', 'window_answer', 'decline', 'dates', 'extra_answer',"
    " 'work_check', 'visit_again', 'visit_cancel', 'budget')"
)


def _swap(sql: str) -> None:
    op.drop_constraint(op.f("ck_assistant_actions_kind"), "assistant_actions", type_="check")
    op.create_check_constraint(op.f("ck_assistant_actions_kind"), "assistant_actions", sql)


def upgrade() -> None:
    _swap(NEW_KINDS)


def downgrade() -> None:
    op.execute("delete from assistant_actions where kind = 'budget'")
    _swap(OLD_KINDS)
