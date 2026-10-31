"""외부 업체 정보: 외부 업체 · 동의한 연락처 · 수신거부 (3개)

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-31

autogenerate 초안을 읽고 고쳤다. 새 표라 CHECK는 초안에 모두 들어 있다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TRADE_KEYS = (
    "array['dobae', 'mokgong', 'floor', 'film', 'paint', 'tile', 'bath', 'kitchen', 'electric',"
    " 'window']::varchar[]"
)


def upgrade() -> None:
    op.create_table(
        "ext_vendors",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=10), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("trades", sa.ARRAY(sa.String(length=10)), nullable=False),
        sa.Column(
            "industries", sa.ARRAY(sa.String(length=60)), server_default="{}", nullable=False
        ),
        sa.Column("sido", sa.String(length=20), nullable=True),
        sa.Column("sgg", sa.String(length=20), nullable=True),
        sa.Column("address", sa.String(length=200), nullable=True),
        sa.Column("lat", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("lng", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("reg_kind", sa.String(length=12), nullable=True),
        sa.Column("reg_no", sa.String(length=10), nullable=True),
        sa.Column("biz_status", sa.String(length=10), nullable=True),
        sa.Column("biz_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("phone", sa.String(length=12), nullable=True),
        sa.Column("homepage", sa.String(length=300), nullable=True),
        sa.Column(
            "portfolio_urls", sa.ARRAY(sa.String(length=300)), server_default="{}", nullable=False
        ),
        sa.Column("quote_url", sa.String(length=300), nullable=True),
        sa.Column("site_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("place_ref", sa.String(length=20), nullable=True),
        sa.Column("place_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("visit_fee", sa.BigInteger(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("opted_out", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("optout_token", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "biz_status is null or biz_status in ('active', 'suspended', 'closed', 'unknown')",
            name=op.f("ck_ext_vendors_biz_status"),
        ),
        sa.CheckConstraint(
            f"cardinality(trades) > 0 and trades <@ {TRADE_KEYS}",
            name=op.f("ck_ext_vendors_trades"),
        ),
        sa.CheckConstraint(
            "homepage is null or homepage ~ '^https?://'", name=op.f("ck_ext_vendors_homepage")
        ),
        sa.CheckConstraint(
            "phone is null or phone ~ '^(0[2-9][0-9]{7,10}|1[5-9][0-9]{6})$'",
            name=op.f("ck_ext_vendors_phone"),
        ),
        sa.CheckConstraint(
            "place_ref is null or place_ref ~ '^[0-9]{1,20}$'",
            name=op.f("ck_ext_vendors_place_ref"),
        ),
        sa.CheckConstraint(
            "quote_url is null or quote_url ~ '^https?://'", name=op.f("ck_ext_vendors_quote_url")
        ),
        sa.CheckConstraint(
            "reg_kind <> 'business' or reg_no is not null",
            name=op.f("ck_ext_vendors_reg_business"),
        ),
        sa.CheckConstraint(
            "reg_kind is null or reg_kind in ('construction', 'business')",
            name=op.f("ck_ext_vendors_reg_kind"),
        ),
        sa.CheckConstraint(
            "reg_no is null or reg_no ~ '^[0-9]{10}$'", name=op.f("ck_ext_vendors_reg_no")
        ),
        sa.CheckConstraint(
            "source in ('sangga', 'kiscon', 'seed')", name=op.f("ck_ext_vendors_source")
        ),
        sa.CheckConstraint(
            "(biz_status is null) = (biz_checked_at is null)",
            name=op.f("ck_ext_vendors_biz_checked"),
        ),
        sa.CheckConstraint("(lat is null) = (lng is null)", name=op.f("ck_ext_vendors_point")),
        sa.CheckConstraint(
            "biz_status is null or reg_no is not null", name=op.f("ck_ext_vendors_biz_status_no")
        ),
        sa.CheckConstraint("cardinality(industries) <= 10", name=op.f("ck_ext_vendors_industries")),
        sa.CheckConstraint(
            "cardinality(portfolio_urls) <= 5", name=op.f("ck_ext_vendors_portfolio_urls")
        ),
        sa.CheckConstraint(
            "lat is null or (lat between 32 and 39 and lng between 124 and 132)",
            name=op.f("ck_ext_vendors_point_range"),
        ),
        sa.CheckConstraint("length(btrim(name)) > 0", name=op.f("ck_ext_vendors_name")),
        sa.CheckConstraint("length(btrim(source_id)) > 0", name=op.f("ck_ext_vendors_source_id")),
        sa.CheckConstraint("sgg is null or sido is not null", name=op.f("ck_ext_vendors_region")),
        sa.CheckConstraint(
            "visit_fee is null or visit_fee between 0 and 10000000",
            name=op.f("ck_ext_vendors_visit_fee"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ext_vendors")),
        sa.UniqueConstraint("optout_token", name=op.f("uq_ext_vendors_optout_token")),
        sa.UniqueConstraint("source", "source_id", name="uq_ext_vendors_source_ref"),
    )
    op.create_index("ix_ext_vendors_region", "ext_vendors", ["sido", "sgg"], unique=False)
    op.create_table(
        "contact_optouts",
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("vendor_id", sa.Uuid(), nullable=True),
        sa.Column("via", sa.String(length=10), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("key_hash ~ '^[0-9a-f]{64}$'", name=op.f("ck_contact_optouts_key_hash")),
        sa.CheckConstraint("via in ('link', 'admin')", name=op.f("ck_contact_optouts_via")),
        sa.ForeignKeyConstraint(
            ["vendor_id"],
            ["ext_vendors.id"],
            name=op.f("fk_contact_optouts_vendor_id_ext_vendors"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("key_hash", name=op.f("pk_contact_optouts")),
    )
    op.create_table(
        "ext_vendor_contacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("vendor_id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.String(length=5), nullable=False),
        sa.Column("value", sa.String(length=300), nullable=False),
        sa.Column("consented_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=10), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "channel <> 'email' or value ~ '^[^@[:space:]]+@[^@[:space:]]+[.][^@[:space:]]+$'",
            name=op.f("ck_ext_vendor_contacts_email"),
        ),
        sa.CheckConstraint(
            "channel <> 'form' or value ~ '^https://'", name=op.f("ck_ext_vendor_contacts_form")
        ),
        sa.CheckConstraint(
            "channel <> 'sms' or value ~ '^01[016789][0-9]{7,8}$'",
            name=op.f("ck_ext_vendor_contacts_sms"),
        ),
        sa.CheckConstraint(
            "channel in ('sms', 'email', 'form')", name=op.f("ck_ext_vendor_contacts_channel")
        ),
        sa.CheckConstraint(
            "source in ('optin', 'pilot', 'seed')", name=op.f("ck_ext_vendor_contacts_source")
        ),
        sa.ForeignKeyConstraint(
            ["vendor_id"],
            ["ext_vendors.id"],
            name=op.f("fk_ext_vendor_contacts_vendor_id_ext_vendors"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ext_vendor_contacts")),
        sa.UniqueConstraint("vendor_id", "channel", "value", name="uq_ext_vendor_contacts_value"),
    )
    op.create_index(
        op.f("ix_ext_vendor_contacts_vendor_id"), "ext_vendor_contacts", ["vendor_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_ext_vendor_contacts_vendor_id"), table_name="ext_vendor_contacts")
    op.drop_table("ext_vendor_contacts")
    op.drop_table("contact_optouts")
    op.drop_index("ix_ext_vendors_region", table_name="ext_vendors")
    op.drop_table("ext_vendors")
