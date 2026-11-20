"""v3 모은 조건(맥락 L3): project_conditions

Revision ID: 0038_v3_project_conditions
Revises: 0037_v3_chat_state
Create Date: 2026-11-20

AI 상담에서 고객이 되묻기에 답하거나 단추로 고른 값(예: dobae.grade = 기본형)을 공사마다 둔다.
에이전트는 다음 턴부터 같은 칸을 다시 묻지 않는다. LLM이 짐작한 값은 넣지 않는다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0038_v3_project_conditions"
down_revision: str | Sequence[str] | None = "0037_v3_chat_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "project_conditions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("trade", sa.String(length=20), nullable=False),
        sa.Column("key", sa.String(length=40), nullable=False),
        sa.Column("value", sa.String(length=40), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("char_length(key) between 3 and 40", name="key"),
        sa.CheckConstraint("char_length(btrim(value)) between 1 and 40", name="value"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "key", name="uq_project_conditions_key"),
    )
    op.create_index(op.f("ix_project_conditions_project_id"), "project_conditions", ["project_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_project_conditions_project_id"), table_name="project_conditions")
    op.drop_table("project_conditions")
