"""v4 비서에게 더 맡기기(07-automation): 행동 · 대상 · 먼저 말 걸기 트리거 값 더하기

Revision ID: 0044_v4_assistant_aftercare
Revises: 0043_v4_project_demolition
Create Date: 2026-11-21

- assistant_actions.kind: 추가 금액 답(extra_answer) · 공사 끝 확인(work_check) · 한 번 더 요청(visit_again).
- assistant_actions.target_kind: 추가 금액(extra). 추가 금액 답 카드는 추가 금액마다 하나다.
- assistant_nudges.trigger: 업체가 빠짐(vendor_out) · 추가 금액(extra_added) · 공사 끝(work_done) ·
  공사 1주 전(prep_week) · 날짜 바꾸기 요청(dates_requested) · 견적서 기한(quote_due).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0044_v4_assistant_aftercare"
down_revision: str | Sequence[str] | None = "0043_v4_project_demolition"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_KINDS = (
    "kind in ('home_info', 'visit_request', 'visit_slot', 'vendor_confirm', 'dates_accept',"
    " 'delay_accept', 'window_answer', 'decline', 'dates')"
)
NEW_KINDS = (
    "kind in ('home_info', 'visit_request', 'visit_slot', 'vendor_confirm', 'dates_accept',"
    " 'delay_accept', 'window_answer', 'decline', 'dates', 'extra_answer', 'work_check',"
    " 'visit_again')"
)
OLD_TARGETS = "target_kind in ('project', 'visit', 'deal', 'proposal')"
NEW_TARGETS = "target_kind in ('project', 'visit', 'deal', 'proposal', 'extra')"
OLD_TRIGGERS = (
    "trigger in ('visit_offered', 'quote_sent', 'dates_proposed', 'work_eve', 'no_pick',"
    " 'visit_requested', 'visit_picked', 'deal_confirmed')"
)
NEW_TRIGGERS = (
    "trigger in ('visit_offered', 'quote_sent', 'dates_proposed', 'work_eve', 'no_pick',"
    " 'visit_requested', 'visit_picked', 'deal_confirmed', 'vendor_out', 'extra_added',"
    " 'work_done', 'prep_week', 'dates_requested', 'quote_due')"
)
NEW_ONLY_KINDS = "('extra_answer', 'work_check', 'visit_again')"
NEW_ONLY_TRIGGERS = (
    "('vendor_out', 'extra_added', 'work_done', 'prep_week', 'dates_requested', 'quote_due')"
)


def _swap(table: str, name: str, sql: str) -> None:
    op.drop_constraint(op.f(f"ck_{table}_{name}"), table, type_="check")
    op.create_check_constraint(op.f(f"ck_{table}_{name}"), table, sql)


def upgrade() -> None:
    _swap("assistant_actions", "kind", NEW_KINDS)
    _swap("assistant_actions", "target_kind", NEW_TARGETS)
    _swap("assistant_nudges", "trigger", NEW_TRIGGERS)


def downgrade() -> None:
    # 새 값 줄을 먼저 지운다(먼저 말 건 줄의 action_id는 SET NULL)
    op.execute(f"delete from assistant_nudges where trigger in {NEW_ONLY_TRIGGERS}")
    op.execute(
        f"delete from assistant_actions where kind in {NEW_ONLY_KINDS} or target_kind = 'extra'"
    )
    _swap("assistant_nudges", "trigger", OLD_TRIGGERS)
    _swap("assistant_actions", "target_kind", OLD_TARGETS)
    _swap("assistant_actions", "kind", OLD_KINDS)
