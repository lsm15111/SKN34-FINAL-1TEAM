"""점검 플랫폼: 시공 사진 FK를 ON DELETE CASCADE로 · 장부 줄에 새 계정 몫 표시(llm_usage.new_account).

Revision ID: 0055_v4_audit_platform
Revises: 0054_v4_follow_up
Create Date: 2026-11-24

- vendor_portfolio.file_id → files: ON DELETE가 없으면(NO ACTION) 시공 사진을 올린 업체가 탈퇴할 때 회원 행을 지우며
  파일(주인 CASCADE)이 업체 → 사진 줄 CASCADE보다 먼저 지워져 FK 위반(500)이에요. 파일이 지워지면 사진 줄도 지워요.
- llm_usage.new_account: 부른 때 새 계정 몫을 보던 호출. 새 계정 합 하루 상한이 이 줄만 세요. 사용자 줄과 조인해 세던
  때는 탈퇴하면(user_id SET NULL) 그 돈이 빠졌어요. 이미 있는 줄은 옛 셈(부른 때 가입 7일 안이던 고객 계정)으로 채워요.
- 되돌리면 칸을 지우고 FK를 옛 꼴(ON DELETE 없음)로 돌려요.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0055_v4_audit_platform"
down_revision: str | Sequence[str] | None = "0054_v4_follow_up"
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
    op.add_column(
        "llm_usage",
        sa.Column("new_account", sa.Boolean(), server_default="false", nullable=False),
    )
    # 옛 셈 그대로(usage.service.db_spent의 users 조인, 새 계정 일수 기본 7일)
    op.execute(
        "update llm_usage l set new_account = true from users u"
        " where u.id = l.user_id and u.role = 'customer'"
        " and u.created_at > l.created_at - interval '7 days'"
    )


def downgrade() -> None:
    op.drop_column("llm_usage", "new_account")
    _portfolio_fk(None)
