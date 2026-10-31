"""가견적 받기: 앱 안 가견적 요청 · 이력 (2개)

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-01

autogenerate 초안을 읽고 고쳤다. 새 표라 CHECK는 초안에 모두 들어 있다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "quote_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("trade", sa.String(length=10), nullable=False),
        sa.Column("vendor_id", sa.Uuid(), nullable=False),
        sa.Column("message", sa.Text(), server_default="", nullable=False),
        sa.Column("status", sa.String(length=10), server_default="requested", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("viewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(status = 'viewed') = (viewed_at is not null)",
            name=op.f("ck_quote_requests_viewed"),
        ),
        sa.CheckConstraint(
            "status in ('requested', 'viewed')", name=op.f("ck_quote_requests_status")
        ),
        sa.CheckConstraint("length(message) <= 1000", name=op.f("ck_quote_requests_message")),
        sa.ForeignKeyConstraint(
            ["project_id", "trade"],
            ["project_trades.project_id", "project_trades.trade"],
            name="fk_quote_requests_trade",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["vendor_id"],
            ["vendors.user_id"],
            name=op.f("fk_quote_requests_vendor_id_vendors"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quote_requests")),
        sa.UniqueConstraint("project_id", "trade", "vendor_id", name="uq_quote_requests_target"),
    )
    op.create_index(
        op.f("ix_quote_requests_vendor_id"), "quote_requests", ["vendor_id"], unique=False
    )
    op.create_table(
        "quote_request_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("from_status", sa.String(length=10), nullable=True),
        sa.Column("to_status", sa.String(length=10), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column(
            "at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "from_status is null or from_status in ('requested', 'viewed')",
            name=op.f("ck_quote_request_events_from_status"),
        ),
        sa.CheckConstraint(
            "to_status in ('requested', 'viewed')", name=op.f("ck_quote_request_events_to_status")
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            name=op.f("fk_quote_request_events_actor_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["quote_requests.id"],
            name=op.f("fk_quote_request_events_request_id_quote_requests"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quote_request_events")),
    )
    op.create_index(
        op.f("ix_quote_request_events_request_id"),
        "quote_request_events",
        ["request_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_quote_request_events_request_id"), table_name="quote_request_events")
    op.drop_table("quote_request_events")
    op.drop_index(op.f("ix_quote_requests_vendor_id"), table_name="quote_requests")
    op.drop_table("quote_requests")
