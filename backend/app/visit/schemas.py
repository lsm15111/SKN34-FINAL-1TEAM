import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, field_validator, model_validator

from app.quote.schemas import QuoteBriefOut, RangeOut, VendorQuoteOut
from app.vendor.schemas import AreaOut, ContactOut, EstimateOut, PublicProfileOut

Direction = Literal["less", "more", "same"]  # 표준견적서보다 적어요 · 많아요 · 같아요
Trade = Literal["dobae", "mokgong"]
Text = Annotated[str, StringConstraints(strip_whitespace=True)]


class VisitBrief(BaseModel):
    """그 업체에 이 집 · 이 공정으로 보낸 가장 최근 실측 요청"""

    id: uuid.UUID
    status: str
    decline_code: str | None
    close_reason: str | None = Field(
        description="닫힌 까닭: other_chosen(다른 업체 확정) · reselected(다시 고르기)"
    )


class VendorRowOut(BaseModel):
    """업체 고르기 한 줄. 연락처(휴대폰 · 채널 주소)는 실측 요청 뒤에만 보인다."""

    vendor_id: uuid.UUID
    biz_name: str | None
    trades: list[str]
    areas: list[AreaOut] = Field(description="활동 지역 (화면이 처음 2곳 + 외 N곳으로 줄인다)")
    verified_on: date | None = Field(description="사업자 확인(승인)한 날, 서울 날짜")
    visit_fee: int | None = Field(description="실측 출장비(원, 부가세 포함). 0 = 무료")
    visit_fee_refund: bool
    contact_method: str | None
    call_start: time | None
    call_end: time | None
    estimate_total: int | None = Field(
        description="가견적 합계(고객이 낼 금액). 없으면 '가견적 없음'"
    )
    vs_standard: Decimal | None = Field(description="표준견적서 대비 % (음수면 적어요)")
    vs_direction: Direction | None
    estimate_range: RangeOut | None = Field(
        default=None,
        description="실측 뒤 예상 범위: 가견적 + 실측 보정 + '실측 후' 줄 (가견적이 없으면 비어 있다)",
    )
    visit: VisitBrief | None = Field(description="최근 실측 요청 (없으면 비어 있다)")


class VendorListOut(BaseModel):
    """이 집 업체 고르기: 그 공정을 하고 이 집 지역(구)에서 일하는 승인된 업체"""

    project_id: uuid.UUID
    trade: str
    region: str = Field(description="이 집 지역 (서울 노원구)")
    area_name: str = Field(description="이 집 시 · 군 · 구 (노원구)")
    standard_total: int = Field(description="그 공정 표준견적서 합계 (부가세 포함)")
    standard_range: RangeOut = Field(
        description="그 공정 표준견적서 예상 범위 (업체 단가를 모를 때)"
    )
    slots_left: int = Field(description="그 공정에 더 담을 수 있는 업체 수 (3곳까지)")
    consent_ver: str = Field(description="연락처 보내기 동의 문구 버전 (요청할 때 그대로 보낸다)")
    vendors: list[VendorRowOut]


class EstimateDetailOut(EstimateOut):
    """가견적 '어떻게 계산했나요': 업체가 확인한 단가 × 이 집 표준견적서 수량 (믿집 계산)"""

    set_id: uuid.UUID = Field(description="쓴 단가 묶음 (실측 요청 때 고정한다)")
    confirmed_on: date = Field(description="업체가 단가를 확인한 날, 서울 날짜")
    confirmed_at: datetime
    exempt: bool = Field(description="면세 업체면 부가세 0")
    vs_standard: Decimal | None
    vs_direction: Direction | None
    range: RangeOut = Field(description="실측 뒤 예상 범위와 그 폭의 이유")


class VendorDetailOut(BaseModel):
    """이 집 기준 업체 자세히"""

    project_id: uuid.UUID
    trade: str
    standard_total: int
    profile: PublicProfileOut
    verified_on: date | None
    years_open: int | None = Field(description="업력: 개업일부터 오늘까지 꽉 찬 햇수")
    in_area: bool = Field(description="이 집이 출장 지역 안인지")
    area_name: str = Field(description="이 집 시 · 군 · 구 (노원구)")
    dong: str | None = Field(description="이 집 읍 · 면 · 동 (프로젝트에 있을 때만)")
    estimate: EstimateDetailOut | None = Field(description="가견적 없음이면 비어 있다")
    visit: VisitBrief | None
    not_included: list[str] = Field(
        description="가견적에 빠진 줄 이름 (실측 후 줄 · 업체 단가 칸이 없는 줄)"
    )


class VisitCreateIn(BaseModel):
    """실측 요청 보내기: 한 공정에 업체 1~3곳. 연락처는 share_contact_ids에 고른 업체에만 간다."""

    trade: Trade
    vendor_ids: list[uuid.UUID] = Field(min_length=1, max_length=3)
    message: Annotated[Text, Field(max_length=300)] | None = Field(
        default=None, description="업체에 남길 말"
    )
    share_contact_ids: list[uuid.UUID] = Field(
        default_factory=list, max_length=3, description="내 연락처를 보낼 업체 (vendor_ids 안에서)"
    )
    apt_name: Annotated[Text, Field(max_length=40)] | None = Field(
        default=None, description="아파트 이름 (연락처를 보내면 필수)"
    )
    dong: Annotated[Text, Field(max_length=10)] | None = None
    ho: Annotated[Text, Field(max_length=10)] | None = None
    consent_ver: str | None = Field(
        default=None, max_length=20, description="동의한 문구 버전 (연락처를 보내면 필수)"
    )

    @field_validator("message", "apt_name", "dong", "ho")
    @classmethod
    def _blank(cls, v: str | None) -> str | None:
        return v or None

    @model_validator(mode="after")
    def _ids(self) -> "VisitCreateIn":
        if len(set(self.vendor_ids)) != len(self.vendor_ids):
            raise ValueError("같은 업체를 두 번 담았어요.")
        if not set(self.share_contact_ids) <= set(self.vendor_ids):
            raise ValueError("연락처는 요청하는 업체에만 보낼 수 있어요.")
        return self


class FailedOut(BaseModel):
    vendor_id: uuid.UUID
    code: Literal["unavailable", "already"] = Field(
        description="unavailable: 지금 믿집에서 일할 수 없는 업체 · already: 이미 요청한 업체"
    )


class VisitOut(BaseModel):
    """고객이 보는 실측 요청 한 건. 업체 연락처는 공개 규칙을 지날 때만 들어 있다."""

    id: uuid.UUID
    trade: str
    vendor_id: uuid.UUID | None
    vendor_name: str
    status: str
    slot: int
    created_at: datetime
    share_contact: bool = Field(description="내 연락처를 보냈는지")
    message: str | None
    decline_code: str | None
    close_reason: str | None = Field(
        description="닫힌 까닭: other_chosen(다른 업체 확정) · reselected(다시 고르기)"
    )
    estimate_total: int | None = Field(description="요청 때 가견적 사본 (없으면 비어 있다)")
    contact_visible: bool
    contact: ContactOut | None
    closed_at: datetime | None = Field(description="취소 · 못 받음 · 닫힘이 된 때")
    quote: QuoteBriefOut | None = Field(description="업체가 보낸 최신 실측 견적서 요약")


class VisitCreateOut(BaseModel):
    created: list[VisitOut]
    failed: list[FailedOut]


class ReselectIn(BaseModel):
    """견적 비교에서 다시 고르기 (확정 전): 이 공정의 요청을 모두 닫는다"""

    trade: Trade


class ReselectOut(BaseModel):
    """다시 고르기 결과: 닫은 요청과 다시 빈 칸 수"""

    trade: str
    closed: list[uuid.UUID] = Field(description="닫은 실측 요청 (연락처는 바로 가려진다)")
    slots_left: int = Field(description="다시 담을 수 있는 업체 수")


class RequestTextOut(BaseModel):
    trade: str
    text: str = Field(description="연락할 때 보낼 문구 (문자 · 카카오톡에 붙여 넣는다)")


class VisitListOut(BaseModel):
    project_id: uuid.UUID
    consent_ver: str
    slots_left: dict[str, int] = Field(description="공정마다 더 담을 수 있는 업체 수")
    request_texts: list[RequestTextOut]
    visits: list[VisitOut] = Field(description="최근 순, 닫힌 것 포함")


class DeclineIn(BaseModel):
    code: Literal["full", "out_of_area", "other"] = Field(
        description="일정이 꽉 찼어요 · 지역 밖이에요 · 그 밖"
    )


class CustomerContactOut(BaseModel):
    """고객이 보내기로 고른 연락처 (요청이 닫히면 바로 가려진다)"""

    name: str
    phone: str | None
    address: str | None = Field(description="자세히에서만: 서울 노원구 상계주공 101동 1203호")


class VendorVisitRow(BaseModel):
    """업체 작업함 한 줄. 고객 연락처는 고객이 보낸 요청이 열려 있을 때만 들어 있다."""

    id: uuid.UUID
    received_at: datetime
    code: str = Field(description="요청 번호 (연락처가 없으면 고객이 이 번호를 말한다)")
    trade: str
    grade: str | None = Field(description="도배 유형 (economy · basic)")
    region: str
    area_name: str
    pyeong: Decimal | None = Field(description="표준견적서에 저장한 평 (공급 기준)")
    status: str
    new: bool = Field(description="아직 열어 보지 않은 새 요청")
    share_contact: bool
    closed_at: datetime | None
    decline_code: str | None
    close_reason: str | None
    waiting_days: int | None = Field(description="견적서를 보낸 뒤 기다린 날 (서울 날짜)")
    customer: CustomerContactOut | None


class VendorVisitPage(BaseModel):
    items: list[VendorVisitRow]
    next_before: datetime | None = Field(description="끝남 탭 다음 쪽 커서 (없으면 끝)")


class RecentOut(BaseModel):
    requested: int
    quoted: int
    chosen: int


class InboxSummaryOut(BaseModel):
    todo: int
    waiting: int
    done: int
    jobs: int = Field(description="확정된 공사 (19번 뒤에 채운다)")
    recent: RecentOut = Field(description="최근 30일: 받은 요청 · 보낸 견적서 · 확정")


class VendorVisitDetailOut(VendorVisitRow):
    """업체가 보는 요청 자세히"""

    area_m2: Decimal | None
    area_basis: str | None
    occupied: bool
    home_text: str = Field(description="노원구 · 32평 · 빈 집")
    when_text: str = Field(description="희망 시기: 11.16(월) ~ 11.23(월)")
    message: str | None


class QuoteBoardOut(BaseModel):
    """업체 실측 견적서 올리기 화면: 임시 저장본 · 보낸 버전 · 칸 한도"""

    visit_id: uuid.UUID
    visit_status: str
    tax_kind: str = Field(description="면세 업체(exempt)는 부가세 방식이 exempt만 된다")
    vat_modes: list[str] = Field(description="고를 수 있는 부가세 방식")
    files_max: int
    days_max: int
    draft: VendorQuoteOut | None = Field(description="임시 저장본 (없으면 비어 있다)")
    sent: list[VendorQuoteOut] = Field(description="보낸 버전 (최신 먼저)")


class QuoteVersionBrief(BaseModel):
    """예전에 보낸 버전 요약 (다시 올리기 기록)"""

    version: int
    sent_at: datetime
    total: int
    days: int | None
    valid_until: date | None
    file_count: int


class CompareRowOut(BaseModel):
    """견적서 비교 화면의 업체 한 곳"""

    visit_id: uuid.UUID
    vendor_id: uuid.UUID | None
    vendor_name: str
    status: str = Field(description="requested(견적서 기다림) · quoted · chosen")
    requested_at: datetime
    seen_ver: int | None = Field(description="이 화면을 연 때의 본 버전. 확정할 때 그대로 보낸다")
    latest: VendorQuoteOut | None = Field(description="보낸 최신 버전 (기다림이면 비어 있다)")
    history: list[QuoteVersionBrief] = Field(description="그 전에 보낸 버전 (최신 먼저)")
    changed: list[str] = Field(
        description="바로 앞 버전과 달라진 칸: total · days · valid_until · files(파일 수)"
    )
    estimate_total: int | None = Field(description="요청 때 가견적 사본")
    vs_standard: Decimal | None = Field(description="표준견적서 대비 % (믿집 계산)")
    vs_direction: Direction | None
    expired: bool = Field(description="유효기간이 오늘(서울)보다 앞")


class CompareOut(BaseModel):
    """한 공정의 실측 견적 비교: 표준견적서와 업체가 보낸 견적서"""

    project_id: uuid.UUID
    trade: str
    standard_total: int = Field(description="표준견적서 합계 (부가세 포함)")
    formula_ver: str
    price_ver: str
    computed_at: datetime
    sent_counts: dict[str, int] = Field(description="공정마다 받은 실측 견적서 수")
    vendors: list[CompareRowOut] = Field(description="받은 것(받은 순) 먼저, 그다음 기다리는 곳")


class VisitFactsOut(BaseModel):
    """한 공정의 실측 요청 요약 (내 공사 단계 판정에 쓴다). 다시 고르기로 닫힌 요청은 뺀다."""

    trade: str
    asked: int
    asked_at: datetime | None
    quotes: int = Field(description="견적서를 받은 요청 수")
    waiting: int = Field(description="견적서를 기다리는 요청 수")
    quoted_at: datetime | None = Field(description="마지막으로 견적서를 받은 때")
    quoted_names: list[str]
    waiting_names: list[str]
    last_at: datetime | None = Field(description="요청 상태가 마지막으로 바뀐 때")


class VisitQuotesOut(BaseModel):
    """서류: 한 업체가 보낸 실측 견적서 버전들 (닫힌 요청도 기록으로 남는다)"""

    visit_id: uuid.UUID
    trade: str
    vendor_name: str
    status: str
    close_reason: str | None
    versions: list[VendorQuoteOut] = Field(description="최신 먼저")
