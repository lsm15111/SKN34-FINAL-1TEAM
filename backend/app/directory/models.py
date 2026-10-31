import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.shared.ids import uuid7

SOURCES = ("sangga", "kiscon", "seed")  # 상가정보 CSV · KISCON 공시 · 개발용 가짜
CHANNELS = ("sms", "email", "form")
TRADE_KEYS = (
    "array['dobae', 'mokgong', 'floor', 'film', 'paint', 'tile', 'bath', 'kitchen', 'electric',"
    " 'window']::varchar[]"
)


class ExtVendor(Base):
    """믿집에 가입하지 않은 외부 업체 한 곳. 허용된 출처에서 모은 공개 정보만 둔다.

    대표자 이름 · 이메일 · 휴대전화는 두지 않는다. phone은 공공 등록 정보에 나온 사무실 번호만이고,
    휴대전화 번호는 DB 제약으로도 막는다. 연락은 업체가 동의해 준 ext_vendor_contacts로만 한다.
    """

    __tablename__ = "ext_vendors"
    __table_args__ = (
        UniqueConstraint("source", "source_id", name="uq_ext_vendors_source_ref"),
        CheckConstraint("source in ('sangga', 'kiscon', 'seed')", name="source"),
        CheckConstraint("length(btrim(source_id)) > 0", name="source_id"),
        CheckConstraint("length(btrim(name)) > 0", name="name"),
        CheckConstraint(f"cardinality(trades) > 0 and trades <@ {TRADE_KEYS}", name="trades"),
        CheckConstraint("cardinality(industries) <= 10", name="industries"),
        CheckConstraint("sgg is null or sido is not null", name="region"),
        CheckConstraint("(lat is null) = (lng is null)", name="point"),
        CheckConstraint(
            "lat is null or (lat between 32 and 39 and lng between 124 and 132)",
            name="point_range",
        ),
        CheckConstraint(
            "reg_kind is null or reg_kind in ('construction', 'business')", name="reg_kind"
        ),
        CheckConstraint("reg_no is null or reg_no ~ '^[0-9]{10}$'", name="reg_no"),
        CheckConstraint("reg_kind <> 'business' or reg_no is not null", name="reg_business"),
        CheckConstraint(
            "biz_status is null or biz_status in ('active', 'suspended', 'closed', 'unknown')",
            name="biz_status",
        ),
        CheckConstraint("(biz_status is null) = (biz_checked_at is null)", name="biz_checked"),
        CheckConstraint("biz_status is null or reg_no is not null", name="biz_status_no"),
        # 사무실 번호(지역 · 070 · 080 · 050x)와 대표번호(15xx · 16xx · 18xx)만. 휴대전화(01x)는 안 된다
        CheckConstraint(
            "phone is null or phone ~ '^(0[2-9][0-9]{7,10}|1[5-9][0-9]{6})$'", name="phone"
        ),
        CheckConstraint("homepage is null or homepage ~ '^https?://'", name="homepage"),
        CheckConstraint("quote_url is null or quote_url ~ '^https?://'", name="quote_url"),
        CheckConstraint("cardinality(portfolio_urls) <= 5", name="portfolio_urls"),
        CheckConstraint("place_ref is null or place_ref ~ '^[0-9]{1,20}$'", name="place_ref"),
        CheckConstraint("visit_fee is null or visit_fee between 0 and 10000000", name="visit_fee"),
        Index("ix_ext_vendors_region", "sido", "sgg"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    source: Mapped[str] = mapped_column(String(10))
    # 출처 안의 번호: 상가업소번호 · 사업자등록번호 · 씨드 번호
    source_id: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(100))
    trades: Mapped[list[str]] = mapped_column(ARRAY(String(10)))
    # 출처의 업종 이름 그대로 (상가정보 소분류 · KISCON 등록 업종). 화면의 '등록 정보'에 쓴다
    industries: Mapped[list[str]] = mapped_column(
        ARRAY(String(60)), default=list, server_default="{}"
    )
    sido: Mapped[str | None] = mapped_column(String(20))
    sgg: Mapped[str | None] = mapped_column(String(20))
    address: Mapped[str | None] = mapped_column(String(200))
    lat: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    lng: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    # 등록 종류: construction = 건설업 등록(KISCON) · business = 사업자등록만. reg_no는 사업자등록번호
    reg_kind: Mapped[str | None] = mapped_column(String(12))
    reg_no: Mapped[str | None] = mapped_column(String(10))
    # 국세청 상태 (계속 · 휴업 · 폐업 · 확인 안 됨)와 확인한 때
    biz_status: Mapped[str | None] = mapped_column(String(10))
    biz_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    phone: Mapped[str | None] = mapped_column(String(12))
    homepage: Mapped[str | None] = mapped_column(String(300))
    # 홈페이지 확인기가 찾은 링크 (주소만, 페이지 내용은 두지 않는다)
    portfolio_urls: Mapped[list[str]] = mapped_column(
        ARRAY(String(300)), default=list, server_default="{}"
    )
    quote_url: Mapped[str | None] = mapped_column(String(300))
    site_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 카카오 장소 ID만 (주소는 place.map.kakao.com/{id}). 카카오 API의 다른 결과는 두지 않는다
    place_ref: Mapped[str | None] = mapped_column(String(20))
    place_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 업체가 공지한 출장(방문) 비용, 원. 0이면 무료라고 공지한 것, 비어 있으면 모름
    visit_fee: Mapped[int | None] = mapped_column(BigInteger)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    opted_out: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # 수신거부 링크에 넣는 무작위 값. 응답에 내보내지 않는다
    optout_token: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ExtVendorContact(Base):
    """외부 업체가 믿집의 연락을 받겠다고 동의해 준 연락처. 자동으로 모은 연락처는 두지 않는다."""

    __tablename__ = "ext_vendor_contacts"
    __table_args__ = (
        UniqueConstraint("vendor_id", "channel", "value", name="uq_ext_vendor_contacts_value"),
        CheckConstraint("channel in ('sms', 'email', 'form')", name="channel"),
        # optin = 업체가 동의 화면에서 직접 · pilot = 파일럿에서 사람이 받은 서면 동의 · seed = 개발용 가짜
        CheckConstraint("source in ('optin', 'pilot', 'seed')", name="source"),
        CheckConstraint("channel <> 'sms' or value ~ '^01[016789][0-9]{7,8}$'", name="sms"),
        CheckConstraint(
            "channel <> 'email' or value ~ '^[^@[:space:]]+@[^@[:space:]]+[.][^@[:space:]]+$'",
            name="email",
        ),
        CheckConstraint("channel <> 'form' or value ~ '^https://'", name="form"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ext_vendors.id", ondelete="CASCADE"), index=True
    )
    channel: Mapped[str] = mapped_column(String(5))
    value: Mapped[str] = mapped_column(String(300))
    consented_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ContactOptout(Base):
    """수신거부 목록. 업체 행이 지워지거나 다시 모여도 남도록 출처 번호 · 사업자번호 · 연락처의 해시를 둔다."""

    __tablename__ = "contact_optouts"
    __table_args__ = (
        CheckConstraint("key_hash ~ '^[0-9a-f]{64}$'", name="key_hash"),
        CheckConstraint("via in ('link', 'admin')", name="via"),
    )

    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ext_vendors.id", ondelete="SET NULL")
    )
    via: Mapped[str] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
