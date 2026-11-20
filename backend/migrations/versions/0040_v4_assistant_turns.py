"""v4 비서 턴 장부(assistant_turns) + chats.kind

Revision ID: 0040_v4_assistant_turns
Revises: 0039_v4_llm_usage
Create Date: 2026-11-21

- chats.kind: ai(v3 AI 칸) · assistant(v4 비서). 옛 행은 ai다. v3 목록은 ai만 보인다.
- assistant_turns: 비서 대화 한 번의 실행. running 행이 대화 잠금(부분 UNIQUE)이고, 같은 (사람, client_key)는
  한 번만 돈다. 글은 넣지 않는다(카드 · 흔적만).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0040_v4_assistant_turns"
down_revision: str | Sequence[str] | None = "0039_v4_llm_usage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "chats", sa.Column("kind", sa.String(length=10), server_default="ai", nullable=False)
    )
    op.create_check_constraint("kind", "chats", "kind in ('ai', 'assistant')")
    op.create_table(
        "assistant_turns",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("chat_id", sa.Uuid(), nullable=False),
        sa.Column("surface", sa.String(length=10), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("visit_id", sa.Uuid(), nullable=True),
        sa.Column("client_key", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=10), server_default="running", nullable=False),
        sa.Column("mode", sa.String(length=5), server_default="free", nullable=False),
        sa.Column("tool_calls", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("cost_micros", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("error_code", sa.String(length=40), nullable=True),
        sa.Column(
            "trace",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "cards",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "heartbeat_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("surface in ('customer', 'vendor')", name="surface"),
        sa.CheckConstraint("status in ('running', 'done', 'stopped', 'failed')", name="status"),
        sa.CheckConstraint("mode in ('llm', 'free')", name="mode"),
        sa.CheckConstraint("tool_calls between 0 and 6", name="tool_calls"),
        sa.CheckConstraint("cost_micros >= 0", name="cost"),
        sa.CheckConstraint("char_length(client_key) between 8 and 64", name="client_key"),
        sa.CheckConstraint("(status = 'failed') = (error_code is not null)", name="failed"),
        sa.CheckConstraint("(status = 'running') = (ended_at is null)", name="ended"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["visit_id"], ["visits.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "client_key", name="uq_assistant_turns_user_key"),
    )
    op.create_index(
        "uq_assistant_turns_running",
        "assistant_turns",
        ["chat_id"],
        unique=True,
        postgresql_where=sa.text("status = 'running'"),
    )
    op.create_index("ix_assistant_turns_chat_created", "assistant_turns", ["chat_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_assistant_turns_chat_created", table_name="assistant_turns")
    op.drop_index("uq_assistant_turns_running", table_name="assistant_turns")
    op.drop_table("assistant_turns")
    op.drop_constraint(op.f("ck_chats_kind"), "chats", type_="check")
    op.drop_column("chats", "kind")
