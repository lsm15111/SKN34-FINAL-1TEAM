import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, SmallInteger, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.shared.ids import uuid7

# 업체가 하는 공정. 키는 프로젝트 공정(project_trades)과 같은 10개다
TRADES = (
    "dobae",
    "mokgong",
    "floor",
    "film",
    "paint",
    "tile",
    "bath",
    "kitchen",
    "electric",
    "window",
)
_TRADE_IN = ", ".join(f"'{t}'" for t in TRADES)


class Vendor(Base):
    """업체 회원. 가입 때는 사업자등록증만 받고, 관리자가 승인해야 업체 기능을 쓴다.

    상호 · 사업자번호 · 연락처 · 주소 · 사이트는 승인 뒤 업체 정보 관리에서 채운다.
    """

    __tablename__ = "vendors"
    __table_args__ = (
        CheckConstraint("status in ('pending', 'approved', 'rejected')", name="status"),
        CheckConstraint("biz_no is null or biz_no ~ '^[0-9]{10}$'", name="biz_no"),
        CheckConstraint(
            "(status = 'rejected') = (reject_reason is not null)", name="reject_reason"
        ),
        CheckConstraint(
            "reject_reason is null or length(btrim(reject_reason)) > 0", name="reject_reason_text"
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    biz_name: Mapped[str | None] = mapped_column(String(100))
    owner_name: Mapped[str | None] = mapped_column(String(50))
    biz_no: Mapped[str | None] = mapped_column(String(10), unique=True)
    phone: Mapped[str | None] = mapped_column(String(20))
    address: Mapped[str | None] = mapped_column(String(200))
    site_url: Mapped[str | None] = mapped_column(String(300))
    license_file_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("files.id"))
    intro: Mapped[str] = mapped_column(Text, default="", server_default="")
    status: Mapped[str] = mapped_column(String(10), default="pending", server_default="pending")
    reject_reason: Mapped[str | None] = mapped_column(String(300))
    # 처리한 관리자 계정이 지워져도 승인 기록은 남긴다 (누가 했는지만 비움)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VendorTrade(Base):
    """업체가 하는 공정"""

    __tablename__ = "vendor_trades"
    __table_args__ = (CheckConstraint(f"trade in ({_TRADE_IN})", name="trade"),)

    vendor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vendors.user_id", ondelete="CASCADE"), primary_key=True
    )
    trade: Mapped[str] = mapped_column(String(10), primary_key=True)


class VendorArea(Base):
    """업체 시공 지역 (시 · 도 + 시 · 군 · 구)"""

    __tablename__ = "vendor_areas"

    vendor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vendors.user_id", ondelete="CASCADE"), primary_key=True
    )
    sido: Mapped[str] = mapped_column(String(20), primary_key=True)
    sgg: Mapped[str] = mapped_column(String(20), primary_key=True)


class VendorPortfolio(Base):
    """포트폴리오 사진 (선택)"""

    __tablename__ = "vendor_portfolio"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vendors.user_id", ondelete="CASCADE"), index=True
    )
    file_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("files.id"), unique=True)
    title: Mapped[str] = mapped_column(String(60))
    sort: Mapped[int] = mapped_column(SmallInteger, default=0)
