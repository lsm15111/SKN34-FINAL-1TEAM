"""대신 연락 아웃박스: 요청 · 이력 (2개)

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-01

autogenerate 초안을 읽고 고쳤다. 새 표라 CHECK는 초안에 모두 들어 있다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUSES = "('draft', 'queued', 'sent', 'failed', 'blocked')"


def upgrade() -> None:
    op.create_table(
        "contact_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("trade", sa.String(length=10), nullable=False),
        sa.Column("vendor_id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.String(length=5), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("consented_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=10), server_default="draft", nullable=False),
        sa.Column("sender", sa.String(length=10), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(status = 'sent') = (sender is not null)", name=op.f("ck_contact_requests_sender")
        ),
        sa.CheckConstraint(
            "(status = 'sent') = (sent_at is not null)", name=op.f("ck_contact_requests_sent")
        ),
        sa.CheckConstraint(
            "channel in ('sms', 'email', 'form')", name=op.f("ck_contact_requests_channel")
        ),
        sa.CheckConstraint(
            "sender is null or sender in ('dry_run')", name=op.f("ck_contact_requests_sender_kind")
        ),
        sa.CheckConstraint(f"status in {STATUSES}", name=op.f("ck_contact_requests_status")),
        sa.CheckConstraint(
            "length(btrim(body)) between 10 and 800", name=op.f("ck_contact_requests_body")
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["users.id"],
            name=op.f("fk_contact_requests_customer_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "trade"],
            ["project_trades.project_id", "project_trades.trade"],
            name="fk_contact_requests_trade",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["vendor_id"],
            ["ext_vendors.id"],
            name=op.f("fk_contact_requests_vendor_id_ext_vendors"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contact_requests")),
        sa.UniqueConstraint("project_id", "trade", "vendor_id", name="uq_contact_requests_target"),
    )
    op.create_index(
        "ix_contact_requests_customer_day",
        "contact_requests",
        ["customer_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_contact_requests_vendor_day",
        "contact_requests",
        ["vendor_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "contact_request_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("from_status", sa.String(length=10), nullable=True),
        sa.Column("to_status", sa.String(length=10), nullable=False),
        sa.Column("reason", sa.String(length=12), nullable=True),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column(
            "at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            f"from_status is null or from_status in {STATUSES}",
            name=op.f("ck_contact_request_events_from_status"),
        ),
        sa.CheckConstraint(
            "reason is null or reason in ('consent', 'opted_out', 'no_contact', 'send_error')",
            name=op.f("ck_contact_request_events_reason"),
        ),
        sa.CheckConstraint(
            f"to_status in {STATUSES}", name=op.f("ck_contact_request_events_to_status")
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            name=op.f("fk_contact_request_events_actor_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["contact_requests.id"],
            name=op.f("fk_contact_request_events_request_id_contact_requests"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contact_request_events")),
    )
    op.create_index(
        op.f("ix_contact_request_events_request_id"),
        "contact_request_events",
        ["request_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_contact_request_events_request_id"), table_name="contact_request_events")
    op.drop_table("contact_request_events")
    op.drop_index("ix_contact_requests_vendor_day", table_name="contact_requests")
    op.drop_index("ix_contact_requests_customer_day", table_name="contact_requests")
    op.drop_table("contact_requests")
