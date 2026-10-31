"""업체 공정 10개: 업체가 하는 공정을 프로젝트 공정과 같은 10개로 넓힌다

Revision ID: 0006_vendor_trades
Revises: 0005
Create Date: 2026-11-01

autogenerate 초안은 비어 있다 (CHECK 바뀜은 잡지 못한다). 표 · 열은 그대로이고 CHECK만 손으로 바꾼다.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006_vendor_trades"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NAME = "ck_vendor_trades_trade"
OLD = "trade in ('dobae', 'mokgong')"
NEW = (
    "trade in ('dobae', 'mokgong', 'floor', 'film', 'paint', 'tile', 'bath', 'kitchen',"
    " 'electric', 'window')"
)


def upgrade() -> None:
    op.drop_constraint(op.f(NAME), "vendor_trades", type_="check")
    op.create_check_constraint(op.f(NAME), "vendor_trades", NEW)


def downgrade() -> None:
    # 새 공정을 하는 업체가 있으면 CHECK를 만들지 못해 멈춘다 (업체 데이터를 지우지 않는다)
    op.drop_constraint(op.f(NAME), "vendor_trades", type_="check")
    op.create_check_constraint(op.f(NAME), "vendor_trades", OLD)
