"""v4 도배 전 앞 공사 점검: 모은 조건 prework.<공정> 칸 · 비서 행동 종류 prework

Revision ID: 0059_v4_prework
Revises: 0058_v4_audit_agent
Create Date: 2026-11-24

- 모은 조건(project_conditions)의 prework.<공정>은 목공 · 전기 · 필름 · 바닥만, 값은 단추 값(done · todo · none)만
  받는다(project/prework.py). 다른 칸은 그대로다.
- assistant_actions.kind: prework(도배 전 점검 카드 단추로 고른 답, 고객이 승인하면 project.prework.set_prework).
- 되돌리면 prework 행동 · 칸을 지우고 옛 CHECK로 돌린다.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0059_v4_prework"
down_revision: str | Sequence[str] | None = "0058_v4_audit_agent"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PREWORK = (
    "key not like 'prework.%' or (key in ('prework.mokgong', 'prework.electric', 'prework.film',"
    " 'prework.floor') and value in ('done', 'todo', 'none'))"
)
OLD_KINDS = (
    "kind in ('home_info', 'visit_request', 'visit_slot', 'vendor_confirm', 'dates_accept',"
    " 'delay_accept', 'date_change', 'window_answer', 'decline', 'dates', 'extra_answer',"
    " 'work_check', 'visit_again', 'visit_cancel')"
)
NEW_KINDS = (
    "kind in ('home_info', 'visit_request', 'visit_slot', 'vendor_confirm', 'dates_accept',"
    " 'delay_accept', 'date_change', 'window_answer', 'decline', 'dates', 'extra_answer',"
    " 'work_check', 'visit_again', 'visit_cancel', 'prework')"
)


def _kinds(sql: str) -> None:
    op.drop_constraint(op.f("ck_assistant_actions_kind"), "assistant_actions", type_="check")
    op.create_check_constraint(op.f("ck_assistant_actions_kind"), "assistant_actions", sql)


def upgrade() -> None:
    op.create_check_constraint(op.f("ck_project_conditions_prework"), "project_conditions", PREWORK)
    _kinds(NEW_KINDS)


def downgrade() -> None:
    op.execute("delete from assistant_actions where kind = 'prework'")
    _kinds(OLD_KINDS)
    op.drop_constraint(op.f("ck_project_conditions_prework"), "project_conditions", type_="check")
    op.execute("delete from project_conditions where key like 'prework.%'")
