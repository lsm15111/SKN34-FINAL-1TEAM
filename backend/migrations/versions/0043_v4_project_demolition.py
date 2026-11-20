"""v4 모은 조건 철거 범위(demolition): 값은 full · partial · none만

Revision ID: 0043_v4_project_demolition
Revises: 0042_v4_assistant_nudges_memory
Create Date: 2026-11-21

- 공사 조건(project_conditions)의 칸 demolition은 코드 값만 받는다(전체 철거 full이면 리모델링 기준).
- 다른 칸(되묻기 단추 글)은 그대로다.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0043_v4_project_demolition"
down_revision: str | Sequence[str] | None = "0042_v4_assistant_nudges_memory"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_check_constraint(
        op.f("ck_project_conditions_demolition"),
        "project_conditions",
        "key <> 'demolition' or value in ('full', 'partial', 'none')",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_project_conditions_demolition"), "project_conditions", type_="check"
    )
