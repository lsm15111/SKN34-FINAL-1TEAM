"""v4 반셀프: 실측 요청에 '업체에 알릴 것'(고객이 직접 할 일) 사본

Revision ID: 0046_v4_visit_diy
Revises: 0045_v4_assistant_aftercare
Create Date: 2026-11-21

- visits.diy: 요청 때 고객이 승인 카드에서 보고 승인한 직접 할 일 칩 키(project.diy) 사본. 빈 배열이면 알린 것 없음.
- 값은 paint · outlet · light · silicone · handle · clean만 받는다(CHECK).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0046_v4_visit_diy"
down_revision: str | Sequence[str] | None = "0045_v4_assistant_aftercare"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DIY_SQL = "diy <@ array['paint', 'outlet', 'light', 'silicone', 'handle', 'clean']::varchar[]"


def upgrade() -> None:
    op.add_column(
        "visits",
        sa.Column(
            "diy", postgresql.ARRAY(sa.String(length=10)), server_default="{}", nullable=False
        ),
    )
    op.create_check_constraint(op.f("ck_visits_diy"), "visits", DIY_SQL)


def downgrade() -> None:
    op.drop_constraint(op.f("ck_visits_diy"), "visits", type_="check")
    op.drop_column("visits", "diy")
