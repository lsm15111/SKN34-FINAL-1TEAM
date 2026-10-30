"""vendor reject reason text: 반려 사유는 공백만으로 둘 수 없다

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-29 19:30:00

API가 앞뒤 공백을 지우고 비면 422로 막는다. DB도 같은 규칙을 지킨다.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_check_constraint(
        op.f("ck_vendors_reject_reason_text"),
        "vendors",
        "reject_reason is null or length(btrim(reject_reason)) > 0",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_vendors_reject_reason_text"), "vendors", type_="check")
