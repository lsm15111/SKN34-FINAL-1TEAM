"""점검 플랫폼: 시공 사진 FK를 ON DELETE CASCADE로.

Revision ID: 0057_v4_audit_platform
Revises: 0055_v4_audit_flow
Create Date: 2026-11-24

- vendor_portfolio.file_id → files: ON DELETE가 없으면(NO ACTION) 시공 사진을 올린 업체가 탈퇴할 때 회원 행을 지우며
  파일(주인 CASCADE)이 업체 → 사진 줄 CASCADE보다 먼저 지워져 FK 위반(500)이에요. 파일이 지워지면 사진 줄도 지워요.
- 되돌리면 FK를 옛 꼴(ON DELETE 없음)로 돌려요.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0057_v4_audit_platform"
down_revision: str | Sequence[str] | None = "0055_v4_audit_flow"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FK = "fk_vendor_portfolio_file_id_files"


def _portfolio_fk(ondelete: str | None) -> None:
    op.drop_constraint(op.f(FK), "vendor_portfolio", type_="foreignkey")
    op.create_foreign_key(
        op.f(FK), "vendor_portfolio", "files", ["file_id"], ["id"], ondelete=ondelete
    )


def upgrade() -> None:
    _portfolio_fk("CASCADE")


def downgrade() -> None:
    _portfolio_fk(None)
