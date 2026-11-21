"""v4 조사 담당(assistant_research) + jobs.kind assistant_research + llm_usage.purpose research

Revision ID: 0049_v4_research
Revises: 0048_v4_memory_move_in
Create Date: 2026-11-22

- assistant_research: 비서가 worker에 맡긴 웹 조사 하나(docs/v4/09-research.md). 공사마다 도는 조사(대기 · 도는 중)는
  하나다(부분 UNIQUE). 목표 · 메모는 가린 글이고 결과는 그 고객 것만이다.
- jobs.kind에 assistant_research(시작 + 6분: 아직 대기 · 도는 중이면 멈춘 조사로 끝내기)를 더한다.
- llm_usage.purpose에 research(조사 담당 호출)를 더한다.
- 되돌리면 새 값 줄을 지우고 CHECK를 옛 목록으로 돌린 뒤 표를 지운다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0049_v4_research"
down_revision: str | Sequence[str] | None = "0048_v4_memory_move_in"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_JOB_KINDS = (
    "kind in ('visit_reply_due', 'visit_pick_due', 'visit_accept_due', 'visit_proposal_due',"
    " 'visit_change_due', 'visit_reminder', 'visit_quote_due', 'quote_valid_soon',"
    " 'deal_dates_due', 'deal_request_due', 'deal_done_remind', 'deal_auto_done',"
    " 'thread_redact', 'assistant_memory')"
)
NEW_JOB_KINDS = (
    "kind in ('visit_reply_due', 'visit_pick_due', 'visit_accept_due', 'visit_proposal_due',"
    " 'visit_change_due', 'visit_reminder', 'visit_quote_due', 'quote_valid_soon',"
    " 'deal_dates_due', 'deal_request_due', 'deal_done_remind', 'deal_auto_done',"
    " 'thread_redact', 'assistant_memory', 'assistant_research')"
)
OLD_PURPOSES = (
    "('assistant', 'floorplan', 'nudge', 'memory', 'v2_chat', 'orchestrator', 'trade',"
    " 'quote_explanation', 'schedule', 'composer', 'general', 'planner', 'judge', 'check')"
)
# llm_usage.purpose 목록(usage/models.py PURPOSES와 같다, 시험이 맞춰 본다)
PURPOSES = (
    "('assistant', 'floorplan', 'nudge', 'memory', 'v2_chat', 'research', 'orchestrator',"
    " 'trade', 'quote_explanation', 'schedule', 'composer', 'general', 'planner', 'judge',"
    " 'check')"
)


def _swap(table: str, name: str, sql: str) -> None:
    op.drop_constraint(op.f(f"ck_{table}_{name}"), table, type_="check")
    op.create_check_constraint(op.f(f"ck_{table}_{name}"), table, sql)


def upgrade() -> None:
    op.create_table(
        "assistant_research",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("turn_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=40), nullable=False),
        sa.Column("goal", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=10), server_default="queued", nullable=False),
        sa.Column("step", sa.String(length=10), nullable=True),
        sa.Column(
            "steps",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "notes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("notes_used", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("stop_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("calls", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("cost_micros", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("error_code", sa.String(length=40), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind in ('outside_vendors', 'materials', 'general')", name="kind"),
        sa.CheckConstraint(
            "status in ('queued', 'running', 'done', 'failed', 'stopped')", name="status"
        ),
        sa.CheckConstraint("step is null or step in ('search', 'read', 'write')", name="step"),
        sa.CheckConstraint("char_length(btrim(title)) between 1 and 40", name="title"),
        sa.CheckConstraint("char_length(btrim(goal)) between 1 and 200", name="goal"),
        sa.CheckConstraint("calls between 0 and 20", name="calls"),
        sa.CheckConstraint("notes_used >= 0", name="notes_used"),
        sa.CheckConstraint("cost_micros >= 0", name="cost"),
        sa.CheckConstraint("(status in ('queued', 'running')) = (ended_at is null)", name="ended"),
        sa.CheckConstraint("status <> 'running' or started_at is not null", name="started"),
        sa.CheckConstraint("(status = 'failed') = (error_code is not null)", name="failed"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_assistant_research_live",
        "assistant_research",
        ["project_id"],
        unique=True,
        postgresql_where=sa.text("status in ('queued', 'running')"),
    )
    op.create_index(
        "ix_assistant_research_project_created",
        "assistant_research",
        ["project_id", "created_at"],
    )
    op.create_index(
        "ix_assistant_research_user_created", "assistant_research", ["user_id", "created_at"]
    )
    _swap("jobs", "kind", NEW_JOB_KINDS)
    _swap("llm_usage", "purpose", f"purpose in {PURPOSES}")


def downgrade() -> None:
    op.execute("delete from jobs where kind = 'assistant_research'")
    op.execute("delete from llm_usage where purpose = 'research'")
    _swap("llm_usage", "purpose", f"purpose in {OLD_PURPOSES}")
    _swap("jobs", "kind", OLD_JOB_KINDS)
    op.drop_index("ix_assistant_research_user_created", table_name="assistant_research")
    op.drop_index("ix_assistant_research_project_created", table_name="assistant_research")
    op.drop_index("uq_assistant_research_live", table_name="assistant_research")
    op.drop_table("assistant_research")
