"""v3 모은 조건(맥락 L3): project_conditions

Revision ID: 0038_v3_project_conditions
Revises: 0036_v3_rooms
Create Date: 2026-11-20

고객이 고른 공사 조건(예: 철거 범위 · 직접 할 일)을 공사 · 칸마다 하나씩 둔다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0038_v3_project_conditions"
down_revision: str | Sequence[str] | None = "0036_v3_rooms"
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
