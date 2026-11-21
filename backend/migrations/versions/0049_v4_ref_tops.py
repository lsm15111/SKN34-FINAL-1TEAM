"""v4 비서 이름표 번호를 DB에도 둔다(assistant_ref_tops)

Revision ID: 0049_v4_ref_tops
Revises: 0048_v4_memory_move_in
Create Date: 2026-11-22

- 대화마다 이름표 머리글자(v · m · s …)별로 쓴 가장 큰 번호. 늘기만 한다.
- Redis 표 · 번호 기록이 모두 지워져도 지난 카드 단추의 이름표가 새 대상을 가리키지 않게 한다(QA edge P3).
- 대화를 지우면 같이 지운다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0049_v4_ref_tops"
down_revision: str | Sequence[str] | None = "0048_v4_memory_move_in"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "assistant_ref_tops",
        sa.Column("chat_id", sa.Uuid(), nullable=False),
        sa.Column("prefix", sa.String(length=1), nullable=False),
        sa.Column("top", sa.Integer(), nullable=False),
        sa.CheckConstraint("prefix ~ '^[a-z]$'", name="prefix"),
        sa.CheckConstraint("top >= 1", name="top"),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("chat_id", "prefix"),
    )


def downgrade() -> None:
    op.drop_table("assistant_ref_tops")
