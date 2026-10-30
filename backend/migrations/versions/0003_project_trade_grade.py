"""project trade grade: 도배 유형(저가형 · 기본형)

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-29 17:24:49

0002로 만든 도배 행에는 유형이 없어서 열은 비워 둘 수 있게 둔다. 새 요청은 API가 유형을 꼭 받는다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("project_trades", sa.Column("grade", sa.String(length=10), nullable=True))
    op.create_check_constraint(
        op.f("ck_project_trades_grade"),
        "project_trades",
        "grade is null or grade in ('economy', 'basic')",
    )
    op.create_check_constraint(
        op.f("ck_project_trades_grade_trade"),
        "project_trades",
        "trade = 'dobae' or grade is null",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_project_trades_grade_trade"), "project_trades", type_="check")
    op.drop_constraint(op.f("ck_project_trades_grade"), "project_trades", type_="check")
    op.drop_column("project_trades", "grade")
