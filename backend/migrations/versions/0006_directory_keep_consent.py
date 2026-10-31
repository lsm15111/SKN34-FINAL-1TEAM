"""외부 업체 동의 증빙 남기기: 빠진 업체는 지우지 않고 표시, 연락처 · 연락 기록 FK는 RESTRICT

Revision ID: 0006_directory_keep_consent
Revises: 0005
Create Date: 2026-11-01

autogenerate 초안(FK · 열)을 읽고 고쳤다. 이력 이유 CHECK('closed' 추가)는 손으로 더했다.
되돌리면 빠짐 표시(closed_at)만 없어진다. 행은 지우지 않으니 빠졌던 업체가 다시 후보에 보인다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006_directory_keep_consent"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (표, FK 이름) — 업체 행이 지워질 때 따라 지워지면 동의 · 연락 증빙이 사라진다
FKS = (
    ("ext_vendor_contacts", "fk_ext_vendor_contacts_vendor_id_ext_vendors"),
    ("contact_requests", "fk_contact_requests_vendor_id_ext_vendors"),
)
REASON = "ck_contact_request_events_reason"
OLD_REASONS = "('consent', 'opted_out', 'no_contact', 'send_error')"
NEW_REASONS = "('consent', 'opted_out', 'no_contact', 'closed', 'send_error')"


def _fks(ondelete: str) -> None:
    for table, name in FKS:
        op.drop_constraint(op.f(name), table, type_="foreignkey")
        op.create_foreign_key(
            op.f(name), table, "ext_vendors", ["vendor_id"], ["id"], ondelete=ondelete
        )


def upgrade() -> None:
    op.add_column("ext_vendors", sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True))
    _fks("RESTRICT")
    op.drop_constraint(op.f(REASON), "contact_request_events", type_="check")
    op.create_check_constraint(
        op.f(REASON), "contact_request_events", f"reason is null or reason in {NEW_REASONS}"
    )


def downgrade() -> None:
    # 'closed' 이유가 남아 있으면 CHECK를 만들지 못해 멈춘다 (이력을 지우지 않는다)
    op.drop_constraint(op.f(REASON), "contact_request_events", type_="check")
    op.create_check_constraint(
        op.f(REASON), "contact_request_events", f"reason is null or reason in {OLD_REASONS}"
    )
    _fks("CASCADE")
    op.drop_column("ext_vendors", "closed_at")
