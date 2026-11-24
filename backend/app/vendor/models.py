import uuid
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import (
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
    Text,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.shared.ids import uuid7

TRADES = ("dobae", "mokgong")
# 자주 묻는 5가지: 진행 순서 · 견적 계산 방식 · 추가금이 생기는 경우 · 공사 기간 · A/S · 환불
FAQ_KEYS = ("process", "pricing", "extra_cost", "duration", "as_refund")
LINKS_MAX = 5  # 시공 사례 링크
PORTFOLIO_MAX = 20  # 시공 사진
PRICE_FILES_MAX = 10  # 공정마다 가견적 근거 파일
# 심사 사유 코드. other(직접 쓰기)는 업체에 보낼 말이 꼭 있어야 한다
NEEDS_INFO_CODES = ("blurry", "name_mismatch", "owner_mismatch", "other")
# info_mismatch: 사업자등록증과 신청 정보가 달라요 (v3 A04, 0025)
REJECT_CODES = ("wrong_business", "closed", "info_mismatch", "other")
# v3 (0025)
TAX_KINDS = ("general", "simplified", "exempt")  # 일반 · 간이(L02: 부가세를 따로 안 붙임) · 면세
SUSPEND_SCOPES = ("new", "all")  # 새 요청만 막기 · 진행 중인 것도 닫기 (D26)
VISIT_CAPACITY_MAX = 3  # 반나절 한 칸에 받는 실측 수 1~3, 기본 2 (L03)
VISIT_CAPACITY_DEFAULT = 2
# 단가 묶음 줄 판: 옛 도배(㎡ 시공) · v3 도배(1201~1208, 평 · 품 · 대) · 목공
ROWS_VERS = ("dobae_v2", "dobae_v3", "mokgong_v1")
ROWS_VER_OF = {"dobae": "dobae_v2", "mokgong": "mokgong_v1"}  # v2 흐름이 새 묶음을 만들 때
PRICE_MODES = ("price", "included", "excluded")  # 단가 × 수량 · 다른 줄에 포함(0원) · 빼기
REVIEW_LINKS_MAX = 3  # 외부 리뷰 링크
LINK_STATUSES = ("checking", "shown", "hidden")
# 심사 이력: 가입 신청 · 승인 · 보완 요청 · 거절 · 보완해서 다시 보냄 · 거절 뒤 다시 신청
REVIEW_ACTIONS = ("apply", "approve", "needs_info", "reject", "resubmit", "reapply")
SUBMIT_ACTIONS = ("apply", "resubmit", "reapply")  # 업체가 낸 것 (관리자가 볼 차례가 된다)

_CODE_KIND = (
    "{code} is null"
    " or ({status} = '{info}' and {code} in ('blurry', 'name_mismatch', 'owner_mismatch', 'other'))"
    " or ({status} = '{rej}'"
    " and {code} in ('wrong_business', 'closed', 'info_mismatch', 'other'))"
)


class Vendor(Base):
    """업체 회원. 가입 신청(상호 · 대표자 · 사업자번호 · 휴대폰 · 공정 · 지역 + 사업자등록증)을
    관리자가 심사해 승인해야 업체 기능을 쓴다. 보완 요청 · 거절이면 사유 코드와 보낼 말이 남는다.
    연락 방식 · 통화 시간 · 실측 비용은 고객에게 보이고, 휴대폰 · 채널 주소는 실측 요청 뒤에만 보인다.
    """

    __tablename__ = "vendors"
    __table_args__ = (
        CheckConstraint(
            "status in ('pending', 'needs_info', 'approved', 'rejected')", name="status"
        ),
        CheckConstraint("biz_no is null or biz_no ~ '^[0-9]{10}$'", name="biz_no"),
        CheckConstraint(
            "(status in ('needs_info', 'rejected')) = (review_code is not null)", name="review_code"
        ),
        CheckConstraint(
            _CODE_KIND.format(
                code="review_code", status="status", info="needs_info", rej="rejected"
            ),
            name="review_code_kind",
        ),
        CheckConstraint(
            "review_note is null or (review_code is not null and length(btrim(review_note)) > 0)",
            name="review_note",
        ),
        CheckConstraint(
            "review_code is distinct from 'other' or review_note is not null", name="review_other"
        ),
        CheckConstraint("(status = 'approved') = (approved_at is not null)", name="approved_at"),
        CheckConstraint("phone ~ '^01[0-9]{8,9}$'", name="phone"),
        CheckConstraint(
            "contact_method in ('phone', 'sms', 'kakao', 'web')", name="contact_method"
        ),
        # 카카오톡 채널 · 홈페이지 상담은 주소가 있어야 연락할 수 있다
        CheckConstraint(
            "contact_method not in ('kakao', 'web') or contact_url is not null", name="contact_url"
        ),
        CheckConstraint(
            "(call_start is null) = (call_end is null)"
            " and (call_start is null or call_start < call_end)",
            name="call_time",
        ),
        CheckConstraint("visit_fee >= 0", name="visit_fee"),
        CheckConstraint("not visit_fee_refund or visit_fee > 0", name="visit_fee_refund"),
        CheckConstraint("tax_kind in ('general', 'simplified', 'exempt')", name="tax_kind"),
        CheckConstraint(
            "suspend_scope is null or suspend_scope in ('new', 'all')", name="suspend_scope"
        ),
        CheckConstraint("(suspended_at is null) = (suspend_scope is null)", name="suspended"),
        CheckConstraint("visit_capacity between 1 and 3", name="visit_capacity"),
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
    # 보완 요청 · 거절 사유 코드와 업체에 보낼 말 (승인 · 심사 중이면 비어 있다)
    review_code: Mapped[str | None] = mapped_column(String(20))
    review_note: Mapped[str | None] = mapped_column(String(300))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 마지막으로 정한 관리자 · 시각. 계정이 지워져도 기록은 남긴다 (누가 했는지만 비움)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # 전화 · 문자 · 카카오톡 채널 · 홈페이지 상담. 채널 · 상담 주소는 kakao · web일 때만
    contact_method: Mapped[str | None] = mapped_column(String(5))
    contact_url: Mapped[str | None] = mapped_column(String(300))
    call_start: Mapped[time | None] = mapped_column(Time)
    call_end: Mapped[time | None] = mapped_column(Time)
    # 실측 출장비(원, 부가세 포함, 0 = 무료)와 '계약하면 빼 줘요'
    visit_fee: Mapped[int | None] = mapped_column(BigInteger)
    visit_fee_refund: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # 일반과세(general) · 간이과세(simplified, L02) · 면세(exempt)
    tax_kind: Mapped[str] = mapped_column(String(10), default="general", server_default="general")
    # 업체가 적는 짧은 글. 비면 고객 화면에 '확인 안 됨'으로 보인다
    interior_license: Mapped[str | None] = mapped_column(String(100))
    insurance: Mapped[str | None] = mapped_column(String(100))
    opened_on: Mapped[date | None] = mapped_column(Date)  # 개업일 (사업자 확인 때 채운다)
    # 업체 정보 마지막 저장. 비면 아직 저장 안 함 (PUT이 이 값으로 동시 저장을 막는다)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # v3 (0025): 기간 답하기 '바로 확정' 처음 값 · 목록 배지(I5). 기준은 visit_windows.instant
    instant_default: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # 업체 기능 멈춤(D26). 승인 상태(status)와 따로 둔다
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    suspend_scope: Mapped[str | None] = mapped_column(String(4))
    # 반나절 한 칸에 받는 실측 수(L03). visit_holds.seat가 1..이 값 안에서 칸을 잡는다
    visit_capacity: Mapped[int] = mapped_column(SmallInteger, default=2, server_default="2")


class VendorTrade(Base):
    """업체가 하는 공정"""

    __tablename__ = "vendor_trades"
    __table_args__ = (CheckConstraint("trade in ('dobae', 'mokgong')", name="trade"),)

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
    """포트폴리오 사진 (선택). 공간 · 평형 · 시공 시기는 업체가 적는다."""

    __tablename__ = "vendor_portfolio"
    __table_args__ = (
        CheckConstraint("pyeong between 1 and 200", name="pyeong"),
        CheckConstraint("area_m2 > 0", name="area_m2"),
        CheckConstraint("paper is null or paper in ('economy', 'basic')", name="paper"),
        CheckConstraint(
            "area_basis is null or (area_basis in ('supply', 'exclusive') and area_m2 is not null)",
            name="area_basis",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vendors.user_id", ondelete="CASCADE"), index=True
    )
    # 파일이 지워지면 사진 줄도 지운다(0055): 탈퇴 때 파일(주인 CASCADE)이 업체 줄보다 먼저 지워져도 막히지 않게
    file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"), unique=True
    )
    title: Mapped[str] = mapped_column(String(60))
    sort: Mapped[int] = mapped_column(SmallInteger, default=0)
    space: Mapped[str | None] = mapped_column(String(20))  # 거실 · 안방
    pyeong: Mapped[int | None] = mapped_column(SmallInteger)  # 아파트 평형(업체가 적은 값)
    taken_on: Mapped[date | None] = mapped_column(Date)  # 시공한 때 (화면에는 연 · 월만)
    # v3 (0025, V16): 면적은 ㎡로 · 벽지(합지 economy · 실크 basic). pyeong은 옛 행용
    area_m2: Mapped[Decimal | None] = mapped_column(Numeric(7, 1))
    paper: Mapped[str | None] = mapped_column(String(10))
    area_basis: Mapped[str | None] = mapped_column(String(10))  # v3 (0034): 공급 · 전용 (C47)


class VendorFaq(Base):
    """자주 묻는 5가지에 업체가 적은 답. 답이 없는 질문은 행이 없다."""

    __tablename__ = "vendor_faqs"
    __table_args__ = (
        CheckConstraint(
            "key in ('process', 'pricing', 'extra_cost', 'duration', 'as_refund')", name="key"
        ),
        CheckConstraint("length(btrim(answer)) > 0", name="answer"),
    )

    vendor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vendors.user_id", ondelete="CASCADE"), primary_key=True
    )
    key: Mapped[str] = mapped_column(String(12), primary_key=True)
    answer: Mapped[str] = mapped_column(String(200))


class VendorLink(Base):
    """시공 사례 링크. 5개까지(sort 0~4)."""

    __tablename__ = "vendor_links"
    __table_args__ = (CheckConstraint("sort between 0 and 4", name="sort"),)

    vendor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vendors.user_id", ondelete="CASCADE"), primary_key=True
    )
    sort: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    label: Mapped[str | None] = mapped_column(String(40))
    url: Mapped[str] = mapped_column(String(300))


class VendorPriceFile(Base):
    """가견적 근거 파일 (예전 가견적서 · 견적서 · 단가표, files.kind = price_doc)"""

    __tablename__ = "vendor_price_files"
    __table_args__ = (CheckConstraint("trade in ('dobae', 'mokgong')", name="trade"),)

    file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"), primary_key=True
    )
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vendors.user_id", ondelete="CASCADE"), index=True
    )
    trade: Mapped[str] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VendorPriceSet(Base):
    """가견적 단가 묶음 한 버전. draft(고치는 중) → confirmed(고객 가견적에 씀) → retired(예전 것).

    (업체, 공정)마다 draft 하나 · confirmed 하나만 둔다. 실측 요청은 그때의 confirmed 묶음을 가리킨다.
    """

    __tablename__ = "vendor_price_sets"
    __table_args__ = (
        UniqueConstraint("vendor_id", "trade", "version", name="uq_vendor_price_sets_version"),
        Index(
            "uq_vendor_price_sets_draft",
            "vendor_id",
            "trade",
            unique=True,
            postgresql_where=text("status = 'draft'"),
        ),
        Index(
            "uq_vendor_price_sets_confirmed",
            "vendor_id",
            "trade",
            unique=True,
            postgresql_where=text("status = 'confirmed'"),
        ),
        CheckConstraint("trade in ('dobae', 'mokgong')", name="trade"),
        CheckConstraint("version >= 1", name="version"),
        CheckConstraint("status in ('draft', 'confirmed', 'retired')", name="status"),
        CheckConstraint("(status = 'draft') = (confirmed_at is null)", name="confirmed_at"),
        CheckConstraint("rows_ver in ('dobae_v2', 'dobae_v3', 'mokgong_v1')", name="rows_ver"),
        CheckConstraint("(trade = 'mokgong') = (rows_ver = 'mokgong_v1')", name="rows_ver_trade"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vendors.user_id", ondelete="CASCADE"), index=True
    )
    trade: Mapped[str] = mapped_column(String(10))
    version: Mapped[int] = mapped_column(SmallInteger)
    status: Mapped[str] = mapped_column(String(10), default="draft", server_default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # v3 (0025): 줄 묶음 판. 옛 v2 묶음은 그대로 두고, v3 목록은 dobae_v3 확인 묶음만 가견적에 쓴다
    rows_ver: Mapped[str] = mapped_column(String(12), default="dobae_v2", server_default="dobae_v2")


class VendorPriceLine(Base):
    """단가 묶음의 표준 행 한 줄. 받는 법(mode): 단가(원, 부가세 빼고) × 수량 · 같은 묶음의 다른 줄에
    포함(0원) · 빼기(가견적에 안 넣음). v3 키는 calc PRICE_ROWS['dobae_v3']."""

    __tablename__ = "vendor_price_lines"
    __table_args__ = (
        CheckConstraint("mode in ('price', 'included', 'excluded')", name="mode"),
        CheckConstraint("(mode = 'price') = (unit_price is not null)", name="mode_price"),
        CheckConstraint("(mode = 'included') = (included_in is not null)", name="mode_included"),
        CheckConstraint("unit_price >= 0", name="unit_price"),
        CheckConstraint("included_in <> key", name="included_in"),
    )

    set_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vendor_price_sets.id", ondelete="CASCADE"), primary_key=True
    )
    key: Mapped[str] = mapped_column(String(20), primary_key=True)
    unit_price: Mapped[int | None] = mapped_column(BigInteger)
    included_in: Mapped[str | None] = mapped_column(String(20))
    mode: Mapped[str] = mapped_column(String(10), default="price", server_default="price")
    # 근거 파일을 지워도 확인한 단가는 남긴다 (출처만 비움)
    source_file_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("files.id", ondelete="SET NULL"), index=True
    )


class VendorReview(Base):
    """심사 이력 한 줄. 업체가 낸 것(apply · resubmit · reapply)과 관리자 결정(approve · needs_info ·
    reject)을 쌓는다. by는 한 사람(업체 본인이면 업체 id), 시스템이면 비어 있다.
    changes는 다시 낼 때 바뀐 칸의 전 값만 통째로 남긴다."""

    __tablename__ = "vendor_reviews"
    __table_args__ = (
        CheckConstraint(
            "action in ('apply', 'approve', 'needs_info', 'reject', 'resubmit', 'reapply')",
            name="action",
        ),
        CheckConstraint("(action in ('needs_info', 'reject')) = (code is not null)", name="code"),
        CheckConstraint(
            _CODE_KIND.format(code="code", status="action", info="needs_info", rej="reject"),
            name="code_kind",
        ),
        CheckConstraint(
            "note is null or (code is not null and length(btrim(note)) > 0)", name="note"
        ),
        CheckConstraint("code is distinct from 'other' or note is not null", name="note_other"),
        CheckConstraint("changes is null or action in ('resubmit', 'reapply')", name="changes"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vendors.user_id", ondelete="CASCADE"), index=True
    )
    action: Mapped[str] = mapped_column(String(12))
    code: Mapped[str | None] = mapped_column(String(20))
    note: Mapped[str | None] = mapped_column(String(300))
    changes: Mapped[dict | None] = mapped_column(JSONB)
    by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VendorReviewLink(Base):
    """외부 리뷰 링크 (V18, 3개까지). 바꾸면 '확인 중'이 되고 관리자가 확인해야 고객에게 보인다(A01)."""

    __tablename__ = "vendor_review_links"
    __table_args__ = (
        CheckConstraint("sort between 0 and 2", name="sort"),
        CheckConstraint("url ~ '^https://'", name="url"),
        CheckConstraint("status in ('checking', 'shown', 'hidden')", name="status"),
        CheckConstraint("(status = 'checking') = (checked_at is null)", name="checked"),
        CheckConstraint("note is null or length(btrim(note)) > 0", name="note"),
    )

    vendor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vendors.user_id", ondelete="CASCADE"), primary_key=True
    )
    sort: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    label: Mapped[str | None] = mapped_column(String(40))
    url: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(10), default="checking", server_default="checking")
    note: Mapped[str | None] = mapped_column(String(300))  # 관리자 메모 (업체에 보이지 않음)
    checked_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
