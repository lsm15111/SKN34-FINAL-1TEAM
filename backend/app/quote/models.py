import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.shared.ids import uuid7

QUOTE_STATUSES = ("requested", "viewed")
CONTACT_STATUSES = ("draft", "queued", "sent", "failed", "blocked")
_CONTACT_IN = "('draft', 'queued', 'sent', 'failed', 'blocked')"


class QuoteRequest(Base):
    """앱 안 가견적 요청: 고객 → 승인 업체, 공정 하나. 업체가 가견적서를 쓰는 것은 다음 단계다."""

    __tablename__ = "quote_requests"
    __table_args__ = (
        UniqueConstraint("project_id", "trade", "vendor_id", name="uq_quote_requests_target"),
        # 프로젝트에서 고른 공정에만 요청한다
        ForeignKeyConstraint(
            ["project_id", "trade"],
            ["project_trades.project_id", "project_trades.trade"],
            ondelete="CASCADE",
            name="fk_quote_requests_trade",
        ),
        CheckConstraint("status in ('requested', 'viewed')", name="status"),
        CheckConstraint("(status = 'viewed') = (viewed_at is not null)", name="viewed"),
        CheckConstraint("length(message) <= 1000", name="message"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    project_id: Mapped[uuid.UUID] = mapped_column()
    trade: Mapped[str] = mapped_column(String(10))
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vendors.user_id", ondelete="CASCADE"), index=True
    )
    message: Mapped[str] = mapped_column(Text, default="", server_default="")
    status: Mapped[str] = mapped_column(String(10), default="requested", server_default="requested")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class QuoteRequestEvent(Base):
    """가견적 요청 상태 이력. 상태를 바꾸는 트랜잭션에서 같이 남긴다."""

    __tablename__ = "quote_request_events"
    __table_args__ = (
        CheckConstraint(
            "from_status is null or from_status in ('requested', 'viewed')", name="from_status"
        ),
        CheckConstraint("to_status in ('requested', 'viewed')", name="to_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("quote_requests.id", ondelete="CASCADE"), index=True
    )
    from_status: Mapped[str | None] = mapped_column(String(10))
    to_status: Mapped[str] = mapped_column(String(10))
    # 누른 사람 계정이 지워져도 이력은 남긴다
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ContactRequest(Base):
    """외부 업체에 믿집이 대신 보내는 가견적 요청 (아웃박스). 기능 플래그가 꺼져 있으면 queued에서 멈춘다.

    고객이 수신 업체 · 보낼 내용에 동의한 때를 남긴다. 받는 곳은 업체가 동의해 준 연락처뿐이다.
    """

    __tablename__ = "contact_requests"
    __table_args__ = (
        UniqueConstraint("project_id", "trade", "vendor_id", name="uq_contact_requests_target"),
        ForeignKeyConstraint(
            ["project_id", "trade"],
            ["project_trades.project_id", "project_trades.trade"],
            ondelete="CASCADE",
            name="fk_contact_requests_trade",
        ),
        CheckConstraint(f"status in {_CONTACT_IN}", name="status"),
        CheckConstraint("channel in ('sms', 'email', 'form')", name="channel"),
        CheckConstraint("length(btrim(body)) between 10 and 800", name="body"),
        CheckConstraint("(status = 'sent') = (sent_at is not null)", name="sent"),
        CheckConstraint("(status = 'sent') = (sender is not null)", name="sender"),
        # 지금 보내는 쪽은 보내지 않고 기록만 하는 dry_run 하나뿐이다
        CheckConstraint("sender is null or sender in ('dry_run')", name="sender_kind"),
        Index("ix_contact_requests_customer_day", "customer_id", "created_at"),
        Index("ix_contact_requests_vendor_day", "vendor_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID] = mapped_column()
    trade: Mapped[str] = mapped_column(String(10))
    vendor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ext_vendors.id", ondelete="CASCADE"))
    channel: Mapped[str] = mapped_column(String(5))
    body: Mapped[str] = mapped_column(Text)
    consented_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(10), default="draft", server_default="draft")
    sender: Mapped[str | None] = mapped_column(String(10))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ContactRequestEvent(Base):
    """대신 연락 상태 이력. 막히거나 실패한 이유도 남긴다 (보낸 내용 · 연락처는 남기지 않는다)."""

    __tablename__ = "contact_request_events"
    __table_args__ = (
        CheckConstraint(f"from_status is null or from_status in {_CONTACT_IN}", name="from_status"),
        CheckConstraint(f"to_status in {_CONTACT_IN}", name="to_status"),
        CheckConstraint(
            "reason is null or reason in ('consent', 'opted_out', 'no_contact', 'send_error')",
            name="reason",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("contact_requests.id", ondelete="CASCADE"), index=True
    )
    from_status: Mapped[str | None] = mapped_column(String(10))
    to_status: Mapped[str] = mapped_column(String(10))
    reason: Mapped[str | None] = mapped_column(String(12))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
