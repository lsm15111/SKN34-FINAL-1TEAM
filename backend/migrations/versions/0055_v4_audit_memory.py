"""v4 점검 고침(기억): 기억 칸마다 마지막으로 바뀐 때(assistant_memory_marks)

Revision ID: 0055_v4_audit_memory
Revises: 0054_v4_follow_up
Create Date: 2026-11-24

- (사람, 키)마다 그 값을 말한 때 · 고객이 지운 때 · 칩으로 줄인 때를 남긴다. 미뤘다 뽑거나 다시 하는 기억 뽑기 일이
  그 뒤에 바뀐 칸을 덮지 않게 한다(R1b #8 지운 기억이 미룬 일로 되살아남 · #9 다시 하는 일이 새 기억을 덮음).
- 값 · 글은 두지 않는다. 지금 있는 기억 줄은 바뀐 때(updated_at)로 채운다. 되돌리면 표를 지운다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0055_v4_audit_memory"
down_revision: str | Sequence[str] | None = "0054_v4_follow_up"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KEYS = (
    "key in ('avail_days', 'avail_half', 'living', 'style', 'material', 'priority', 'pet', 'diy',"
    " 'move_in')"
)


def upgrade() -> None:
    op.create_table(
        "assistant_memory_marks",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=12), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(KEYS, name="key"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "key"),
    )
    op.execute(
        "insert into assistant_memory_marks (user_id, key, changed_at)"
        " select user_id, key, updated_at from assistant_memory"
    )


def downgrade() -> None:
    op.drop_table("assistant_memory_marks")
