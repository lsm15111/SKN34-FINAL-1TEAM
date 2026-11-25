"""점검 고침 X4: 관리자가 숨긴 리뷰를 지운 공사(review_holds)

Revision ID: 0055_v4_audit_flow
Revises: 0053_v4_diy_paper_buy
Create Date: 2026-11-24

- 관리자가 숨긴 리뷰를 쓴 사람이 지우면 그 공사를 남긴다. 같은 공사에 다시 쓰면 숨긴 채(같은 기준)로 시작하고,
  관리자가 그 공사 리뷰를 다시 보이게 하면 지운다(점검 R4#3: 지우고 다시 써서 숨김을 푸는 길).
- 되돌리면 표를 지운다(다시 쓴 리뷰는 그대로).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0055_v4_audit_flow"
down_revision: str | Sequence[str] | None = "0053_v4_diy_paper_buy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "review_holds",
        sa.Column("deal_id", sa.Uuid(), nullable=False),
        sa.Column("hidden_code", sa.String(length=12), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "hidden_code in ('abuse', 'privacy', 'unrelated', 'paid')", name="hidden_code"
        ),
        sa.ForeignKeyConstraint(["deal_id"], ["deals.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("deal_id"),
    )


def downgrade() -> None:
    op.drop_table("review_holds")
