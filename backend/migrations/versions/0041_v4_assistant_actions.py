"""v4 비서 대기 행동(assistant_actions): 제안 도구가 만들고 사람이 승인해야 실행된다

Revision ID: 0041_v4_assistant_actions
Revises: 0040_v4_assistant_turns
Create Date: 2026-11-21

- 상태: proposed → approved → executed, 또는 rejected · expired · failed. 바꾸기는 조건부 UPDATE(actions.py).
- 같은 (사람, idem_key)는 한 줄, 열린 제안은 (사람, 종류, 대상)마다 하나(부분 UNIQUE).
- target_id는 FK 없이 공사 · 실측 · 확정 · 제안을 가리킨다. 만료 까닭은 result.reason(error_code는 실패만).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0041_v4_assistant_actions"
down_revision: str | Sequence[str] | None = "0040_v4_assistant_turns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KINDS = (
    "('home_info', 'visit_request', 'visit_slot', 'vendor_confirm', 'dates_accept',"
    " 'delay_accept', 'window_answer', 'decline', 'dates')"
)
STATUSES = "('proposed', 'approved', 'executed', 'rejected', 'expired', 'failed')"


def upgrade() -> None:
    op.create_table(
        "assistant_actions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("surface", sa.String(length=10), nullable=False),
        sa.Column("origin", sa.String(length=10), server_default="turn", nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("target_kind", sa.String(length=10), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("target_ver", sa.String(length=40), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("idem_key", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=10), server_default="proposed", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=40), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("surface in ('customer', 'vendor')", name="surface"),
        sa.CheckConstraint("origin in ('turn', 'nudge')", name="origin"),
        sa.CheckConstraint(f"kind in {KINDS}", name="kind"),
        sa.CheckConstraint(f"status in {STATUSES}", name="status"),
        sa.CheckConstraint(
            "target_kind in ('project', 'visit', 'deal', 'proposal')", name="target_kind"
        ),
        sa.CheckConstraint("char_length(idem_key) between 8 and 64", name="idem_key"),
        sa.CheckConstraint("expires_at > created_at", name="expires"),
        sa.CheckConstraint(
            "(status in ('proposed', 'expired')) = (decided_at is null)", name="decided"
        ),
        sa.CheckConstraint("(status = 'executed') = (executed_at is not null)", name="executed"),
        sa.CheckConstraint("(status = 'failed') = (error_code is not null)", name="failed"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "idem_key", name="uq_assistant_actions_user_idem"),
    )
    op.create_index(
        "uq_assistant_actions_open",
        "assistant_actions",
        ["user_id", "kind", "target_id"],
        unique=True,
        postgresql_where=sa.text("status = 'proposed'"),
    )
    op.create_index(
        "ix_assistant_actions_due",
        "assistant_actions",
        ["expires_at"],
        postgresql_where=sa.text("status = 'proposed'"),
    )
    op.create_index(
        "ix_assistant_actions_user_created", "assistant_actions", ["user_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_assistant_actions_user_created", table_name="assistant_actions")
    op.drop_index("ix_assistant_actions_due", table_name="assistant_actions")
    op.drop_index("uq_assistant_actions_open", table_name="assistant_actions")
    op.drop_table("assistant_actions")
