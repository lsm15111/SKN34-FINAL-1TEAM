"""v4 비서 행동 종류에 보낸 실측 요청 취소(visit_cancel)를 더하고, 보이는 먼저 말 건 줄의 due_at 색인을 만든다

Revision ID: 0050_v4_visit_cancel
Revises: 0049_v4_ref_tops
Create Date: 2026-11-22

- assistant_actions.kind: visit_cancel(고객이 승인하면 visit.service.cancel이 이유 코드로 취소).
- assistant_nudges: 보이는 줄(sent · opened)의 due_at은 정리가 마지막으로 본 때다. 정리가 오래 안 본 줄부터 읽게
  (due_at, id) 부분 색인을 둔다.
- 되돌리면 visit_cancel 행을 지우고 CHECK를 옛 목록으로 돌린다.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0050_v4_visit_cancel"
down_revision: str | Sequence[str] | None = "0049_v4_ref_tops"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_KINDS = (
    "kind in ('home_info', 'visit_request', 'visit_slot', 'vendor_confirm', 'dates_accept',"
    " 'delay_accept', 'date_change', 'window_answer', 'decline', 'dates', 'extra_answer',"
    " 'work_check', 'visit_again')"
)
NEW_KINDS = (
    "kind in ('home_info', 'visit_request', 'visit_slot', 'vendor_confirm', 'dates_accept',"
    " 'delay_accept', 'date_change', 'window_answer', 'decline', 'dates', 'extra_answer',"
    " 'work_check', 'visit_again', 'visit_cancel')"
)
SHOWN_DUE = "ix_assistant_nudges_shown_due"


def _swap(sql: str) -> None:
    op.drop_constraint(op.f("ck_assistant_actions_kind"), "assistant_actions", type_="check")
    op.create_check_constraint(op.f("ck_assistant_actions_kind"), "assistant_actions", sql)


def upgrade() -> None:
    _swap(NEW_KINDS)
    op.create_index(
        SHOWN_DUE,
        "assistant_nudges",
        ["due_at", "id"],
        unique=False,
        postgresql_where="status in ('sent', 'opened')",
    )


def downgrade() -> None:
    op.drop_index(
        SHOWN_DUE, table_name="assistant_nudges", postgresql_where="status in ('sent', 'opened')"
    )
    op.execute("delete from assistant_actions where kind = 'visit_cancel'")
    _swap(OLD_KINDS)
