"""프로젝트 공정 10개: 바닥재 · 필름 · 도장 · 타일 · 욕실 · 주방 · 전기·조명 · 창호를 더한다

Revision ID: 0002_project_trades
Revises: 0001
Create Date: 2026-11-01

새 공정은 고른 공간만 둔다 (공정 칸은 상담에서 묻는다). 표 · 열은 그대로이고 CHECK만 바꾼다.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_project_trades"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NAME = "ck_project_trades_trade"
OLD = "trade in ('dobae', 'mokgong')"
NEW = (
    "trade in ('dobae', 'mokgong', 'floor', 'film', 'paint', 'tile', 'bath', 'kitchen',"
    " 'electric', 'window')"
)


def upgrade() -> None:
    op.drop_constraint(op.f(NAME), "project_trades", type_="check")
    op.create_check_constraint(op.f(NAME), "project_trades", NEW)


def downgrade() -> None:
    # 새 공정을 고른 프로젝트가 있으면 CHECK를 만들지 못해 멈춘다 (고객 데이터를 지우지 않는다)
    op.drop_constraint(op.f(NAME), "project_trades", type_="check")
    op.create_check_constraint(op.f(NAME), "project_trades", OLD)
