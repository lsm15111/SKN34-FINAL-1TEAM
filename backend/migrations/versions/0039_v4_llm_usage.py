"""v4 LLM 호출 장부(llm_usage): 호출마다 토큰 · 비용 · 성공 여부(글 없음)

Revision ID: 0039_v4_llm_usage
Revises: 0038_v3_project_conditions
Create Date: 2026-11-21

비용 상한(usage.service)이 하루 · 전체 합계를 센다. 색인은 날짜 · 사용자별 하루 합계용이다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0039_v4_llm_usage"
down_revision: str | Sequence[str] | None = "0038_v3_project_conditions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PURPOSES = (
    "('assistant', 'floorplan', 'nudge', 'memory', 'v2_chat', 'orchestrator', 'trade',"
    " 'quote_explanation', 'schedule', 'composer', 'general', 'planner', 'judge', 'check')"
)


def upgrade() -> None:
    op.create_table(
        "llm_usage",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("turn_id", sa.Uuid(), nullable=True),
        sa.Column("purpose", sa.String(length=20), nullable=False),
        sa.Column("model", sa.String(length=60), nullable=False),
        sa.Column("input_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cache_read_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cache_write_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("web_searches", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("cost_micros", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("price_ver", sa.String(length=40), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("error", sa.String(length=40), nullable=True),
        sa.Column("latency_ms", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(f"purpose in {PURPOSES}", name="purpose"),
        sa.CheckConstraint("char_length(btrim(model)) > 0", name="model"),
        sa.CheckConstraint(
            "input_tokens >= 0 and cache_read_tokens >= 0 and cache_write_tokens >= 0"
            " and output_tokens >= 0",
            name="tokens",
        ),
        sa.CheckConstraint("web_searches >= 0", name="web_searches"),
        sa.CheckConstraint("cost_micros >= 0", name="cost"),
        sa.CheckConstraint("latency_ms >= 0", name="latency"),
        sa.CheckConstraint("ok = (error is null)", name="ok"),
        sa.CheckConstraint("error is null or char_length(btrim(error)) > 0", name="error"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_llm_usage_created", "llm_usage", ["created_at"])
    op.create_index("ix_llm_usage_user_created", "llm_usage", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_llm_usage_user_created", table_name="llm_usage")
    op.drop_index("ix_llm_usage_created", table_name="llm_usage")
    op.drop_table("llm_usage")
