import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.shared.ids import uuid7

LINE_STATES = ("included", "bundled", "separate", "optional", "after_visit", "excluded")


class StandardQuote(Base):
    """표준견적서 한 공정 · 한 버전. 집 정보(rev) · 산식 · 단가 버전이 바뀌면 새 버전을 쌓는다."""

    __tablename__ = "standard_quotes"
    __table_args__ = (
        UniqueConstraint("project_id", "trade", "version", name="uq_standard_quotes_version"),
        CheckConstraint("trade in ('dobae', 'mokgong')", name="trade"),
        CheckConstraint("version >= 1", name="version"),
        CheckConstraint("supply >= 0 and vat >= 0 and total = supply + vat", name="money"),
        CheckConstraint("scope in ('full', 'partial')", name="scope"),
        CheckConstraint(
            "faces <@ array['wall', 'ceiling']::varchar[] and cardinality(faces) between 1 and 2",
            name="faces",
        ),
        # 부분 공사만 공간 몫 표 판이 있다
        CheckConstraint("(scope = 'partial') = (share_ver is not null)", name="share_ver"),
        CheckConstraint("market_ver is null or length(btrim(market_ver)) > 0", name="market_ver"),
        CheckConstraint("trade = 'dobae' or not own_paper", name="own_paper"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    trade: Mapped[str] = mapped_column(String(10))
    version: Mapped[int] = mapped_column(SmallInteger)
    project_rev: Mapped[int] = mapped_column(SmallInteger)
    formula_ver: Mapped[str] = mapped_column(String(20))
    price_ver: Mapped[str] = mapped_column(String(20))
    grade: Mapped[str | None] = mapped_column(String(10))
    area_m2: Mapped[Decimal] = mapped_column(Numeric(7, 1))
    area_basis: Mapped[str] = mapped_column(String(10))
    pyeong: Mapped[Decimal] = mapped_column(Numeric(5, 1))
    supply: Mapped[int] = mapped_column(BigInteger)
    vat: Mapped[int] = mapped_column(BigInteger)
    total: Mapped[int] = mapped_column(BigInteger)
    man_day: Mapped[Decimal] = mapped_column(Numeric(4, 1))
    crew: Mapped[int] = mapped_column(SmallInteger)
    notes: Mapped[list[str]] = mapped_column(ARRAY(String(200)), default=list, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # v3 (0024): 만든 때의 공사 범위 · 면 · 고른 공간 kind 사본 · 공간 몫 표 판(부분일 때만)
    scope: Mapped[str] = mapped_column(String(8), default="full", server_default="full")
    faces: Mapped[list[str]] = mapped_column(
        ARRAY(String(8)),
        default=lambda: ["wall", "ceiling"],
        server_default=text("'{wall,ceiling}'"),
    )
    space_keys: Mapped[list[str]] = mapped_column(
        ARRAY(String(12)), default=list, server_default="{}"
    )
    share_ver: Mapped[str | None] = mapped_column(String(20))
    # v3 (0033): 벽지 시장 평균 가격 판(paper-market-2026.11). price_ver(공공 단가 판)와 따로 고정한다
    market_ver: Mapped[str | None] = mapped_column(String(40))
    # v4 (0053): 만든 때 고객이 벽지를 직접 샀는지(반셀프 '벽지 직접 구매'). 참이면 도배지 줄이 '안 함'(고객 구매)이고
    # 합계에서 빠졌다(계산 엔진). 칩이 바뀌면 새 판을 쌓는다
    own_paper: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))


class StandardQuoteLine(Base):
    """표준견적서 줄. 표준 행 키와 포함 상태 6종으로 남긴다(합계에는 포함 · 따로 계산만)."""

    __tablename__ = "standard_quote_lines"
    __table_args__ = (
        CheckConstraint(
            "state in ('included', 'bundled', 'separate', 'optional', 'after_visit', 'excluded')",
            name="state",
        ),
        CheckConstraint("basis in ('public', 'market', 'assumed', 'none')", name="basis"),
    )

    quote_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("standard_quotes.id", ondelete="CASCADE"), primary_key=True
    )
    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(60))
    qty: Mapped[Decimal | None] = mapped_column(Numeric(9, 1))
    unit: Mapped[str] = mapped_column(String(10))
    unit_price: Mapped[int | None] = mapped_column(BigInteger)
    amount: Mapped[int | None] = mapped_column(BigInteger)
    state: Mapped[str] = mapped_column(String(12))
    basis: Mapped[str] = mapped_column(String(10))
    source: Mapped[str] = mapped_column(String(120))
    sort: Mapped[int] = mapped_column(SmallInteger)


VAT_MODES = ("included", "excluded", "exempt")  # 넣은 금액이 부가세 포함 · 부가세 빼고 · 면세
QUOTE_FILES_MAX = 10
# 보낸 견적서에 꼭 있어야 하는 칸: 낼 금액 · 부가세 방식 (파일 1개 이상은 service가 본다)
_SENT_FIELDS = " and ".join(f"{c} is not null" for c in ("entered_amount", "vat_mode", "total"))


class VendorQuote(Base):
    """업체 실측 견적서 한 버전. 파일은 업체 양식 그대로, 낼 금액 · 부가세 방식 · 공사 기간 ·
    유효기간만 칸에 적는다(줄로 바꾸지 않음). 실측한 날 · 공사 기간 · 유효기간은 선택이다. 공급가 · 부가세 · 합계는 계산 엔진이 만든다.
    sent_at이 비면 임시 저장(요청마다 하나), 보내면 그 버전은 바꾸지 않는다."""

    __tablename__ = "vendor_quotes"
    __table_args__ = (
        UniqueConstraint("visit_id", "version", name="uq_vendor_quotes_version"),
        UniqueConstraint("code", "version", name="uq_vendor_quotes_code_version"),
        Index(
            "uq_vendor_quotes_draft",
            "visit_id",
            unique=True,
            postgresql_where=text("sent_at is null"),
        ),
        CheckConstraint("version >= 1", name="version"),
        CheckConstraint("code ~ '^Q-[0-9]{4}-[0-9]{4,}$'", name="code"),
        CheckConstraint("vat_mode in ('included', 'excluded', 'exempt')", name="vat_mode"),
        CheckConstraint("entered_amount >= 0", name="entered_amount"),
        # 1원 이상(0052): 0원으로 임시 저장한 옛 행이 있을 수 있어 NOT VALID(새로 넣거나 고치는 행부터)
        CheckConstraint(
            "entered_amount >= 1", name="entered_amount_min", postgresql_not_valid=True
        ),
        CheckConstraint(
            "(supply is null) = (total is null) and (vat is null) = (total is null)"
            " and (total is null or (supply >= 0 and vat >= 0 and total = supply + vat))",
            name="money",
        ),
        CheckConstraint(
            "total is null or (entered_amount is not null and vat_mode is not null)",
            name="money_from",
        ),
        CheckConstraint(
            "vat_mode is distinct from 'exempt' or vat is null or vat = 0", name="exempt"
        ),
        CheckConstraint("days between 1 and 120", name="days"),
        CheckConstraint("valid_until >= measured_on", name="valid_until"),
        CheckConstraint(f"sent_at is null or ({_SENT_FIELDS})", name="sent_fields"),
        CheckConstraint("paper_spec is null or length(btrim(paper_spec)) > 0", name="paper_spec"),
        CheckConstraint("warranty_months between 0 and 120", name="warranty_months"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    visit_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("visits.id", ondelete="CASCADE"), index=True
    )
    # Q-2611-0041. 요청마다 번호 하나, 다시 올리면 같은 번호에 버전만 올린다
    code: Mapped[str] = mapped_column(String(16))
    version: Mapped[int] = mapped_column(SmallInteger)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    measured_on: Mapped[date | None] = mapped_column(Date)
    entered_amount: Mapped[int | None] = mapped_column(BigInteger)  # 업체가 적은 낼 금액
    vat_mode: Mapped[str | None] = mapped_column(String(10))
    supply: Mapped[int | None] = mapped_column(BigInteger)
    vat: Mapped[int | None] = mapped_column(BigInteger)
    total: Mapped[int | None] = mapped_column(BigInteger)  # 고객이 낼 금액
    days: Mapped[int | None] = mapped_column(SmallInteger)  # 공사 기간 (일)
    valid_until: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # v3 (0025, D21) '포함됐나요?' 칩 4칸: 기존 벽지 철거 · 폐기물 처리 · 벽지 제조사 · 규격 · 하자 보수 기간
    incl_removal: Mapped[bool | None] = mapped_column(Boolean)
    incl_waste: Mapped[bool | None] = mapped_column(Boolean)
    paper_spec: Mapped[str | None] = mapped_column(String(60))  # LX 실크벽지 베스트 · 폭 106cm
    warranty_months: Mapped[int | None] = mapped_column(SmallInteger)


class VendorQuoteFile(Base):
    """견적서 버전에 붙인 업체 양식 파일 (files.kind = quote_doc).
    같은 요청의 버전끼리는 같은 파일을 다시 붙일 수 있고, 다른 요청의 견적서에는 못 붙인다(service)."""

    __tablename__ = "vendor_quote_files"
    __table_args__ = (CheckConstraint("sort between 0 and 9", name="sort"),)

    quote_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vendor_quotes.id", ondelete="CASCADE"), primary_key=True
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    sort: Mapped[int] = mapped_column(SmallInteger)
