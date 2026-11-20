"""v4 비서 먼저 말 걸기(assistant_nudges) · 기억(assistant_memory) + jobs.kind assistant_memory

Revision ID: 0042_v4_assistant_nudges_memory
Revises: 0041_v4_assistant_actions
Create Date: 2026-11-21

- assistant_nudges: 코드가 고른 제안 한 줄. (사람, dedup_key)는 한 줄, 기다리는 줄은 due_at 부분 색인으로 거둔다.
  보낸 줄(sent · opened · dismissed)은 문장 · 보낸 때가 있고, 열기 · 닫기는 사람이 한 때(acted_at)가 있다.
- assistant_memory: 고객 말에서만 뽑은 기억. (사람, 키)는 한 줄(덮어씀), 근거 메시지가 지워지면 같이 지운다.
- jobs.kind에 assistant_memory(턴 저장 직후 기억 뽑기)를 더한다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0042_v4_assistant_nudges_memory"
down_revision: str | Sequence[str] | None = "0041_v4_assistant_actions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TRIGGERS = (
    "('visit_offered', 'quote_sent', 'dates_proposed', 'work_eve', 'no_pick',"
    " 'visit_requested', 'visit_picked', 'deal_confirmed')"
)
STATUSES = "('pending', 'held', 'sent', 'opened', 'dismissed', 'expired')"
KEYS = "('avail_days', 'avail_half', 'living', 'style', 'material', 'priority', 'pet', 'diy')"
OLD_JOB_KINDS = (
    "kind in ('visit_reply_due', 'visit_pick_due', 'visit_accept_due', 'visit_proposal_due',"
    " 'visit_change_due', 'visit_reminder', 'visit_quote_due', 'quote_valid_soon',"
    " 'deal_dates_due', 'deal_request_due', 'deal_done_remind', 'deal_auto_done',"
    " 'thread_redact')"
)
NEW_JOB_KINDS = (
    "kind in ('visit_reply_due', 'visit_pick_due', 'visit_accept_due', 'visit_proposal_due',"
    " 'visit_change_due', 'visit_reminder', 'visit_quote_due', 'quote_valid_soon',"
    " 'deal_dates_due', 'deal_request_due', 'deal_done_remind', 'deal_auto_done',"
    " 'thread_redact', 'assistant_memory')"
)


def upgrade() -> None:
    op.create_table(
        "assistant_nudges",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("surface", sa.String(length=10), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("trigger", sa.String(length=20), nullable=False),
        sa.Column("ref_id", sa.Uuid(), nullable=False),
        sa.Column("dedup_key", sa.String(length=80), nullable=False),
        sa.Column("channel", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=10), server_default="pending", nullable=False),
        sa.Column("score", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("body", sa.String(length=200), nullable=True),
        sa.Column("src", sa.String(length=5), nullable=True),
        sa.Column("reason", sa.String(length=20), nullable=True),
        sa.Column("card", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("action_id", sa.Uuid(), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("surface in ('customer', 'vendor')", name="surface"),
        sa.CheckConstraint(f"trigger in {TRIGGERS}", name="trigger"),
        sa.CheckConstraint("channel in ('feed', 'notify')", name="channel"),
        sa.CheckConstraint(f"status in {STATUSES}", name="status"),
        sa.CheckConstraint("src is null or src in ('ai', 'guide')", name="src"),
        sa.CheckConstraint("score between 0 and 100", name="score"),
        sa.CheckConstraint("char_length(dedup_key) between 8 and 80", name="dedup_key"),
        sa.CheckConstraint(
            "body is null or char_length(btrim(body)) between 1 and 200", name="body"
        ),
        sa.CheckConstraint(
            "status not in ('sent', 'opened', 'dismissed')"
            " or (sent_at is not null and body is not null and src is not null)",
            name="sent",
        ),
        sa.CheckConstraint(
            "status not in ('opened', 'dismissed') or acted_at is not null", name="acted"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["action_id"], ["assistant_actions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "dedup_key", name="uq_assistant_nudges_user_dedup"),
    )
    op.create_index(
        "ix_assistant_nudges_due",
        "assistant_nudges",
        ["due_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index("ix_assistant_nudges_user_sent", "assistant_nudges", ["user_id", "sent_at"])
    op.create_table(
        "assistant_memory",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=12), nullable=False),
        sa.Column("value", sa.String(length=60), nullable=False),
        sa.Column("evidence_message_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_quote", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(f"key in {KEYS}", name="key"),
        sa.CheckConstraint("char_length(btrim(value)) between 1 and 60", name="value"),
        sa.CheckConstraint(
            "char_length(btrim(evidence_quote)) between 1 and 200", name="evidence_quote"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["evidence_message_id"], ["chat_messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "key", name="uq_assistant_memory_user_key"),
    )
    op.create_index(
        op.f("ix_assistant_memory_evidence_message_id"),
        "assistant_memory",
        ["evidence_message_id"],
    )
    op.drop_constraint(op.f("ck_jobs_kind"), "jobs", type_="check")
    op.create_check_constraint(op.f("ck_jobs_kind"), "jobs", NEW_JOB_KINDS)


def downgrade() -> None:
    op.execute("delete from jobs where kind = 'assistant_memory'")
    op.drop_constraint(op.f("ck_jobs_kind"), "jobs", type_="check")
    op.create_check_constraint(op.f("ck_jobs_kind"), "jobs", OLD_JOB_KINDS)
    op.drop_index(op.f("ix_assistant_memory_evidence_message_id"), table_name="assistant_memory")
    op.drop_table("assistant_memory")
    op.drop_index("ix_assistant_nudges_user_sent", table_name="assistant_nudges")
    op.drop_index("ix_assistant_nudges_due", table_name="assistant_nudges")
    op.drop_table("assistant_nudges")
