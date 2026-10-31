import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.shared.ids import uuid7

QUOTE_STATUSES = ("requested", "viewed")


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
