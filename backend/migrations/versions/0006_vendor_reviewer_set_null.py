"""vendor reviewer set null: 처리한 관리자를 지워도 승인 기록은 남긴다

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-29 20:10:00

vendors.reviewed_by → users.id 에 ON DELETE가 없어서 관리자 계정을 지울 수 없었다.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FK = "fk_vendors_reviewed_by_users"


def upgrade() -> None:
    op.drop_constraint(op.f(FK), "vendors", type_="foreignkey")
    op.create_foreign_key(
        op.f(FK), "vendors", "users", ["reviewed_by"], ["id"], ondelete="SET NULL"
    )


def downgrade() -> None:
    op.drop_constraint(op.f(FK), "vendors", type_="foreignkey")
    op.create_foreign_key(op.f(FK), "vendors", "users", ["reviewed_by"], ["id"])
