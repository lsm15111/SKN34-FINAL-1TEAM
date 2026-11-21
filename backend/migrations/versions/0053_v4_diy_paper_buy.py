"""v4 반셀프 '벽지 직접 구매'(paper_buy) 칩 · 표준견적서 고객 구매 표시

Revision ID: 0053_v4_diy_paper_buy
Revises: 0052_v4_amount_min
Create Date: 2026-11-22

- 모은 조건 diy.<키> · 실측 요청 사본 visits.diy CHECK에 paper_buy를 더한다(project/diy.py 칩 키).
- standard_quotes.own_paper: 이 판을 만든 때 고객이 벽지를 직접 샀는지(도배지 줄 '안 함' · 고객 구매, 계산 엔진).
  칩이 바뀌면 표준견적서 새 판을 쌓는 데 쓴다(quote.service._fresh). 도배 판만 참일 수 있다.
- 되돌리면 paper_buy 칩 · 요청 사본을 지우고 옛 CHECK로 돌린다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0053_v4_diy_paper_buy"
down_revision: str | Sequence[str] | None = "0052_v4_amount_min"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = ("paint", "outlet", "light", "silicone", "handle", "clean")
NEW = (*OLD, "paper_buy")


def _conditions_sql(keys: tuple[str, ...]) -> str:
    names = ", ".join(f"'diy.{k}'" for k in (*keys, "none"))
    return f"key not like 'diy.%' or (value = 'self' and key in ({names}))"


def _visits_sql(keys: tuple[str, ...]) -> str:
    return "diy <@ array[" + ", ".join(f"'{k}'" for k in keys) + "]::varchar[]"


def _checks(keys: tuple[str, ...]) -> None:
    op.drop_constraint(op.f("ck_project_conditions_diy"), "project_conditions", type_="check")
    op.create_check_constraint(
        op.f("ck_project_conditions_diy"), "project_conditions", _conditions_sql(keys)
    )
    op.drop_constraint(op.f("ck_visits_diy"), "visits", type_="check")
    op.create_check_constraint(op.f("ck_visits_diy"), "visits", _visits_sql(keys))


def upgrade() -> None:
    _checks(NEW)
    op.add_column(
        "standard_quotes",
        sa.Column("own_paper", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_standard_quotes_own_paper"), "standard_quotes", "trade = 'dobae' or not own_paper"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_standard_quotes_own_paper"), "standard_quotes", type_="check")
    op.drop_column("standard_quotes", "own_paper")
    op.execute("delete from project_conditions where key = 'diy.paper_buy'")
    op.execute(
        "update visits set diy = array_remove(diy, 'paper_buy') where 'paper_buy' = any(diy)"
    )
    _checks(OLD)
