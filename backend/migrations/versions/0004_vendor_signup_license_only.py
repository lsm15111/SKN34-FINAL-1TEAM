"""vendor signup license only: 업체 가입은 기본 회원정보 + 사업자등록증만

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-29 18:40:00

상호 · 대표자 · 사업자번호 · 연락처 · 주소 · 사이트는 승인 뒤 업체 정보 관리(FFV-08)에서 채우므로 비워 둘 수 있게 한다.
되돌릴 때 이 칸이 빈 업체가 있으면 NOT NULL로 못 바꿔서 실패한다(지어낸 값으로 채우지 않는다).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = [
    ("biz_name", sa.String(length=100)),
    ("owner_name", sa.String(length=50)),
    ("biz_no", sa.String(length=10)),
    ("phone", sa.String(length=20)),
    ("address", sa.String(length=200)),
    ("site_url", sa.String(length=300)),
]


def upgrade() -> None:
    for name, type_ in COLUMNS:
        op.alter_column("vendors", name, existing_type=type_, nullable=True)
    op.drop_constraint(op.f("ck_vendors_biz_no"), "vendors", type_="check")
    op.create_check_constraint(
        op.f("ck_vendors_biz_no"), "vendors", "biz_no is null or biz_no ~ '^[0-9]{10}$'"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_vendors_biz_no"), "vendors", type_="check")
    op.create_check_constraint(op.f("ck_vendors_biz_no"), "vendors", "biz_no ~ '^[0-9]{10}$'")
    for name, type_ in COLUMNS:
        op.alter_column("vendors", name, existing_type=type_, nullable=False)
