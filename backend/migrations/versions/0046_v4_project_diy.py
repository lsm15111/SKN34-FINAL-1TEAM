"""v4 모은 조건 직접 할 일(diy.<키>): 칩 키와 '없어요'만, 값은 self만

Revision ID: 0046_v4_project_diy
Revises: 0043_v4_project_demolition
Create Date: 2026-11-21

- 공사 조건(project_conditions)의 diy.로 시작하는 칸은 project/diy.py 칩 키(paint · outlet · light · silicone ·
  handle · clean)와 없어요(none)만 받고, 값은 self 하나다. 다른 칸은 그대로다.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0046_v4_project_diy"
down_revision: str | Sequence[str] | None = "0043_v4_project_demolition"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_check_constraint(
        op.f("ck_project_conditions_diy"),
        "project_conditions",
        "key not like 'diy.%' or (value = 'self' and key in ('diy.paint', 'diy.outlet', 'diy.light',"
        " 'diy.silicone', 'diy.handle', 'diy.clean', 'diy.none'))",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_project_conditions_diy"), "project_conditions", type_="check")
