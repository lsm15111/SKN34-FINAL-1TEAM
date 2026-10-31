"""업체 정보 관리: 포트폴리오 링크 열과 링크 · 홈페이지 CHECK

Revision ID: 0009_vendor_profile
Revises: 0008_vendor_trades
Create Date: 2026-11-01

열(portfolio_urls)은 autogenerate로 확인했고, CHECK는 손으로 더했다.
홈페이지(site_url)는 지금까지 쓰는 곳이 없어 비어 있으므로 CHECK를 바로 건다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009_vendor_profile"
down_revision: str | Sequence[str] | None = "0008_vendor_trades"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHECKS = {
    "site_url": "site_url is null or site_url ~ '^https?://'",
    "portfolio_urls": "cardinality(portfolio_urls) <= 5",
    "portfolio_links": (
        "array_to_string(portfolio_urls, ' ', '!') ~ '^(https?://[^[:space:]]+( |$))*$'"
    ),
}


def upgrade() -> None:
    op.add_column(
        "vendors",
        sa.Column(
            "portfolio_urls", sa.ARRAY(sa.String(length=300)), server_default="{}", nullable=False
        ),
    )
    for name, sql in CHECKS.items():
        op.create_check_constraint(op.f(f"ck_vendors_{name}"), "vendors", sql)


def downgrade() -> None:
    for name in CHECKS:
        op.drop_constraint(op.f(f"ck_vendors_{name}"), "vendors", type_="check")
    op.drop_column("vendors", "portfolio_urls")
