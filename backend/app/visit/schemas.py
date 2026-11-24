import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, field_validator, model_validator

from app.quote.schemas import QuoteBriefOut, VendorQuoteOut
from app.shared.text import Tidy
from app.vendor.schemas import (
    AreaOut,
    ContactOut,
    EstimateOut,
    EstimateV3Out,
    PublicProfileOut,
    RatingOut,
    ReviewLinkOut,
)

Direction = Literal["less", "more", "same"]  # 표준견적서보다 적어요 · 많아요 · 같아요
Trade = Literal["dobae", "mokgong"]
# 사람이 쓰는 글 칸: Annotated[Text, Field(...), Tidy](Tidy는 맨 뒤, 제어 문자 지움 · 보안 QA r2 N2)
Text = Annotated[str, StringConstraints(strip_whitespace=True)]
# ---- v3 실측 일정 ----
Half = Literal["am", "pm"]  # 오전 · 오후
VisitStatus = Literal[
    "requested",
    "offered",
    "picked",
    "proposed",
    "booked",
    "visited",
    "quoted",
    "chosen",
    "declined",
    "expired",
    "cancelled",
    "no_show",
    "closed",
]
Grade = Literal["economy", "basic"]  # 도배 벽지: 합지(저가형) · 실크(기본형)
# 겹치는 날 없음 까닭(C22): 공사 시작보다 늦음 · 희망 기간보다 늦음 · 희망 기간보다 이름 · 겹치지만 빈 칸 없음
NoOverlap = Literal["after_work_start", "after_wish", "before_wish", "full"]
# 업체 카드 상태: 담을 수 있음 · 가견적 준비 중(D06 A) · 이 벽지는 안 해요(D07 A) · 두 번 답 없던 업체(C18)
CardState = Literal["ok", "no_estimate", "paper_unsupported", "blocked_retry"]
CancelCode = Literal["changed", "other_vendor", "late_quote", "other"]
# 다음 할 일: 업체 답 · 고객 고르기 · 업체 수락 · 제안 고르기 · 바꾸기 답 · 실측 · 견적서 · 확정 · 없음
NextKind = Literal[
    "reply", "pick", "accept", "proposal", "change", "visit", "quote", "confirm", "none"
]


class VisitBrief(BaseModel):
    """그 업체에 이 집 · 이 공정으로 보낸 가장 최근 실측 요청"""

    id: uuid.UUID
    status: str
    decline_code: str | None
    close_reason: str | None = Field(
        description="닫힌 까닭: other_chosen(다른 업체 확정) · reselected(다시 고르기) · vendor_stopped(업체 기능 멈춤)"
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
    visit: VisitBrief | None = Field(description="최근 실측 요청 (없으면 비어 있다)")


class VendorListOut(BaseModel):
    """이 집 업체 고르기: 그 공정을 하고 이 집 지역(구)에서 일하는 승인된 업체"""

    project_id: uuid.UUID
    trade: str
    region: str = Field(description="이 집 지역 (서울 노원구)")
    area_name: str = Field(description="이 집 시 · 군 · 구 (노원구)")
    standard_total: int = Field(description="그 공정 표준견적서 합계 (부가세 포함)")
    slots_left: int = Field(description="그 공정에 더 담을 수 있는 업체 수 (3곳까지)")
    consent_ver: str = Field(description="연락처 보내기 동의 문구 버전 (요청할 때 그대로 보낸다)")
    vendors: list[VendorRowOut]
    # ---- v3 (C10 · C12 · D06, 1단계에서 채움). 가견적 낮은 순, 0곳이면 가까운 구 ----
    local: list["VendorCardOut"] = Field(default=[], description="이 집 구 업체")
    nearby: list["VendorCardOut"] = Field(
        default=[], description="가까운 구 업체 (local이 0곳일 때)"
    )
    nearby_sgg: list[str] = Field(default=[], description="가까운 구 이름")
    shortlist: "ShortlistCountOut | None" = Field(default=None, description="담은 수 · 남은 칸")
    paper_note: str | None = Field(
        default=None,
        description="벽지 직접 구매일 때 가견적 안내 한 줄(틀, quote.service.OWN_PAPER_NOTE)",
    )


class EstimateDetailOut(EstimateOut):
    """가견적 '어떻게 계산했나요': 업체가 확인한 단가 × 이 집 표준견적서 수량 (믿집 계산)"""

    set_id: uuid.UUID = Field(description="쓴 단가 묶음 (실측 요청 때 고정한다)")
    confirmed_on: date = Field(description="업체가 단가를 확인한 날, 서울 날짜")
    confirmed_at: datetime
    exempt: bool = Field(description="면세 업체면 부가세 0")
    vs_standard: Decimal | None
    vs_direction: Direction | None


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
    # ---- v3 (C11 · D07, 1단계에서 채움) ----
    estimate_v3: EstimateV3Out | None = Field(
        default=None, description="가견적 1201~1208 (?grade=로 다른 벽지 미리 보기)"
    )
    grade: Grade | None = Field(
        default=None,
        description="보여 준 벽지: ?grade= 값, 없으면 공사 벽지 (가견적이 없어도 채움, 목공은 비움)",
    )
    grade_diff: int | None = Field(
        default=None,
        description="다른 벽지 − 보여 준 벽지 (원, 믿집 계산). C11 '합지 −31만 1,850원'은 실크를 볼 때"
        " 합지 칸 아래 값. 두 벽지 가견적이 다 있을 때만",
    )
    reply_hours: int | None = Field(
        default=None,
        description="업체가 지난 요청에 기간을 답하기까지 걸린 시간의 가운데 값(시간, 올림, 최근 20건)."
        " 답한 적이 없으면 비움 (C11 '보통 1일 안에 답')",
    )
    state: CardState | None = Field(default=None, description="담을 수 있는지")
    instant_badge: bool | None = Field(default=None, description="'바로 확정' 배지 (I5)")
    rating: RatingOut | None = Field(default=None, description="별점 요약")
    review_links: list[ReviewLinkOut] = Field(default=[], description="외부 리뷰 링크 (보여요만)")
    shortlisted: bool | None = Field(default=None, description="이미 담았는지")


class VendorCardOut(BaseModel):
    """v3 업체 보기 카드 한 줄 (C10 · D06). 고객 이름 · 연락처는 없다."""

    vendor_id: uuid.UUID
    name: str
    sgg: str = Field(description="업체가 있는 구 (가까운 구 업체 표시)")
    estimate_total: int | None = Field(description="가견적 합계 (부가세 포함, 준비 중이면 비움)")
    vs_standard_pct: Decimal | None = Field(description="표준견적서 대비 % (믿집 계산)")
    rating: Decimal | None = Field(description="별점 평균 (소수 한 자리)")
    review_count: int
    done_count: int = Field(description="믿집에서 끝낸 공사 수")
    visit_fee: int | None = Field(description="실측 출장비 (0 = 무료)")
    instant_badge: bool = Field(description="'바로 확정' 배지 (I5)")
    state: CardState
    shortlisted: bool


class ShortlistCountOut(BaseModel):
    count: int
    left: int = Field(description="더 담을 수 있는 칸 (3칸까지)")


# ---- v3 담기 (shortlist) ----


class ShortlistIn(BaseModel):
    trade: Trade
    vendor_id: uuid.UUID
    grade: Grade | None = Field(
        default=None, description="v3 고른 벽지 (C11, 도배만). 비면 공사 벽지"
    )


class ShortlistItemOut(BaseModel):
    vendor_id: uuid.UUID
    name: str
    slot: int = Field(description="칸 번호 1~3")
    grade: Grade | None = Field(default=None, description="담을 때 고른 벽지 (비면 공사 벽지)")
    estimate_total: int | None = Field(description="그 벽지로 센 가견적 (믿집 계산)")
    state: CardState
    visit_id: uuid.UUID | None = Field(description="이 업체에 보낸 살아 있는 요청 (없으면 비움)")
    visit_status: VisitStatus | None
    added_at: datetime


class ShortlistOut(BaseModel):
    """담은 업체 (공사 · 공종마다 3칸)"""

    project_id: uuid.UUID
    trade: str
    items: list[ShortlistItemOut]
    count: int
    left: int


# ---- v3 실측 일정: 요청서 초안 · 상태판 · 날짜 고르기 (C13~C22 · D03 · D08 · D15~D17) ----


class DraftVendorOut(BaseModel):
    vendor_id: uuid.UUID
    name: str
    estimate_total: int | None
    grade: Literal["economy", "basic"] | None


class VisitDraftOut(BaseModel):
    """요청서 · AI 초안 카드가 같이 쓰는 값 (계산 엔진: 공사 시작 희망일 − 28일 ~ − 14일)"""

    trade: str
    wish_start: date | None = Field(description="희망일이 없으면 비움 (UC-VIS-01 A2)")
    wish_end: date | None
    basis_start: date | None = Field(description="공사 시작 희망일 (초안의 근거)")
    vendors: list[DraftVendorOut] = Field(description="담은 업체")


class SlotIn(BaseModel):
    """반나절 하나"""

    day: date
    half: Half


class SlotOut(BaseModel):
    day: date
    half: Half


class VisitNextOut(BaseModel):
    """다음 할 일과 기한 (지남 · 곧 지남은 서버가 계산 엔진으로 센다)"""

    kind: NextKind
    who: Literal["customer", "vendor", "none"]
    due_at: datetime | None
    overdue: bool
    soon: bool = Field(description="12시간 안으로 남음")


class WindowOut(BaseModel):
    """업체가 되는 기간 (V04 답)"""

    start: date
    end: date
    excluded: list[date]
    instant: bool = Field(description="바로 확정: 고르면 확인 창 뒤 바로 정해져요")
    answered_at: datetime
    pick_due_at: datetime


class BookedOut(BaseModel):
    """잡아 둔 · 확정한 반나절"""

    day: date
    half: Half
    kind: Literal["hold", "booked"] = Field(description="hold: 업체 수락 기다림")
    hold_until: datetime | None = Field(description="잡아 둔 기한 (수락 기다릴 때)")


class VisitProposalOut(BaseModel):
    """업체가 낸 다른 날 (V07 · V20)"""

    id: uuid.UUID
    reason_code: Literal["other_site", "no_crew", "other"] | None
    note: str | None
    slots: list[SlotOut]
    status: Literal["open", "picked", "repicked", "expired"]
    due_at: datetime
    change_id: uuid.UUID | None = Field(description="바꾸기 요청에 낸 것이면 그 요청")


class ChangeOut(BaseModel):
    """확정 뒤 일정 바꾸기 요청 (C28 · V20)"""

    id: uuid.UUID
    visit_id: uuid.UUID
    from_day: date
    from_half: Half
    to_day: date
    to_half: Half
    status: Literal["open", "accepted", "countered", "withdrawn", "expired"]
    due_at: datetime
    proposal: VisitProposalOut | None = Field(description="업체가 다른 날을 냈으면 (countered)")
    created_at: datetime


class VisitCanOut(BaseModel):
    """지금 누를 수 있는 단추"""

    pick: bool
    cancel: bool
    again: bool = Field(description="한 번 더 요청 (시도 2까지)")
    visited: bool = Field(description="'실측 받았어요' (반나절이 끝난 뒤, L09)")
    change: bool
    requote: bool = Field(description="유효기간 지난 견적서 '다시 받기' (D20)")


class BoardRowOut(BaseModel):
    """실측 일정 상태판의 업체 한 곳 (C14 · D03 비교표의 열)"""

    visit_id: uuid.UUID
    vendor_id: uuid.UUID | None
    vendor_name: str
    attempt: int
    status: VisitStatus
    next: VisitNextOut
    window: WindowOut | None
    booked: BookedOut | None
    proposal: VisitProposalOut | None
    change: ChangeOut | None
    can: VisitCanOut
    estimate_total: int | None = Field(description="요청 때 고정한 가견적")
    thread_id: uuid.UUID | None = Field(description="실측이 확정되면 열리는 채팅")
    quote: QuoteBriefOut | None
    cancel_code: CancelCode | None
    expired_reason: Literal["reply", "pick"] | None
    expired_due_at: datetime | None = Field(
        default=None,
        description="기한이 지나 끝난 요청의 그 기한 시각 (답 없음 = 업체 답 기한 · 고르기 없음 = 고르기 기한)",
    )


class VisitHeadOut(BaseModel):
    """요청 머리 (C15 요청 내용 보기)"""

    trade: str
    sent_at: datetime
    wish_start: date | None
    wish_end: date | None
    work_wish_on: date | None = Field(description="공사 시작 희망일 (L04)")
    photos: list[uuid.UUID] = Field(description="요청 사진 (위치 정보 지움, 보낸 순)")
    photo_labels: list[str | None] = Field(
        default=[], description="사진 이름표 (photos와 같은 순서, 없으면 비움)"
    )


class DayHalvesOut(BaseModel):
    """날짜 고르기 달력의 하루 (L03: 반나절마다 남은 칸 수도 준다)"""

    day: date
    am: bool
    pm: bool
    am_left: int
    pm_left: int


class RecommendOut(BaseModel):
    """추천 반나절 (계산 엔진, AI는 설명만)"""

    day: date
    half: Half
    target: date = Field(description="기준 날 (공사 시작 희망일 − 20일)")
    basis: Literal["start_minus_20", "earliest"]


class MyVisitOut(BaseModel):
    """내 다른 실측 (달력에 같이 보임)"""

    visit_id: uuid.UUID
    vendor_name: str
    day: date
    half: Half


class VisitPickOut(BaseModel):
    """날짜 고르기 · 확정 · 제안 · 겹침 없음 화면 (C16 · C19 · C21 · C22 · D15~D17)"""

    visit_id: uuid.UUID
    project_id: uuid.UUID
    trade: str
    vendor_id: uuid.UUID | None
    vendor_name: str
    attempt: int = Field(default=1, description="몇 번째 요청 (한 번 더 요청이면 2)")
    status: VisitStatus
    next: VisitNextOut
    wish_start: date | None
    wish_end: date | None
    work_wish_on: date | None
    window: WindowOut | None
    days: list[DayHalvesOut] = Field(description="업체 기간의 날마다 열린 반나절")
    full: list[SlotOut] = Field(description="마감 (다른 고객이 잡음)")
    mine: list[MyVisitOut] = Field(description="내 다른 실측")
    instant: bool
    recommend: RecommendOut | None
    overlap: bool = Field(description="내 희망 기간과 업체 기간이 겹치는지")
    ways: list[Literal["ask_other", "other_vendor", "change_wish"]] = Field(
        description="겹치는 날이 없거나 고를 칸이 없을 때 길 3개 (C22)"
    )
    no_overlap_reason: NoOverlap | None = Field(
        default=None,
        description="C22 까닭: after_work_start(업체 기간이 공사 시작보다 늦음) · after_wish(희망 기간보다"
        " 늦음) · before_wish(희망 기간보다 이름) · full(겹치지만 고를 칸이 없음). 고를 수 있으면 비움",
    )
    booked: BookedOut | None
    proposal: VisitProposalOut | None
    change: ChangeOut | None
    thread_id: uuid.UUID | None


class PickOut(BaseModel):
    visit_id: uuid.UUID
    status: Literal["booked", "picked"]
    booked: BookedOut
    thread_id: uuid.UUID | None = Field(description="바로 확정이면 열린 채팅")


class VisitStateOut(BaseModel):
    """상태를 바꾼 뒤 그 요청 (화면은 다시 읽는다)"""

    visit_id: uuid.UUID
    status: VisitStatus
    next: VisitNextOut


class VisitedIn(BaseModel):
    result: Literal["visited", "no_show"] = Field(description="실측 받았어요 · 업체가 안 왔어요")


class CancelIn(BaseModel):
    """실측 취소 이유 (C30). 그 밖이면 한 줄"""

    code: CancelCode
    note: Annotated[Text, Field(max_length=100), Tidy] | None = None

    @field_validator("note")
    @classmethod
    def _blank(cls, v: str | None) -> str | None:
        return v or None


class VisitCreateIn(BaseModel):
    """실측 요청 보내기: 한 공정에 업체 1~3곳. 연락처는 share_contact_ids에 고른 업체에만 간다."""

    trade: Trade
    vendor_ids: list[uuid.UUID] = Field(min_length=1, max_length=3)
    message: Annotated[Text, Field(max_length=300), Tidy] | None = Field(
        default=None, description="업체에 남길 말"
    )
    share_contact_ids: list[uuid.UUID] = Field(
        default_factory=list, max_length=3, description="내 연락처를 보낼 업체 (vendor_ids 안에서)"
    )
    apt_name: Annotated[Text, Field(max_length=40), Tidy] | None = Field(
        default=None, description="아파트 이름 (연락처를 보내면 필수)"
    )
    dong: Annotated[Text, Field(max_length=10), Tidy] | None = None
    ho: Annotated[Text, Field(max_length=10), Tidy] | None = None
    consent_ver: str | None = Field(
        default=None, max_length=20, description="동의한 문구 버전 (연락처를 보내면 필수)"
    )
    # ---- v3: 담긴 업체만 · 희망 기간 · 사진 (연락처 칸은 v3에서 쓰지 않는다) ----
    wish_start: date | None = Field(default=None, description="v3 희망 기간 시작")
    wish_end: date | None = Field(default=None, description="v3 희망 기간 끝 (62일 안)")
    photo_file_ids: list[uuid.UUID] = Field(
        default_factory=list,
        max_length=10,
        description="v3 요청 사진 (POST /files kind=photo). 이름표를 붙이려면 photos를 써요",
    )
    photos: list["VisitPhotoIn"] = Field(
        default_factory=list, max_length=10, description="v3 요청 사진 + 이름표 (10장까지)"
    )
    grade: Grade | None = Field(
        default=None,
        description="v3 고른 벽지 (C11, 도배만). 비면 담을 때 고른 벽지, 그것도 없으면 공사 벽지",
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
        if self.photos and self.photo_file_ids:
            raise ValueError("사진은 photos 하나로 보내 주세요.")
        if self.photo_file_ids:
            self.photos = [VisitPhotoIn(file_id=x) for x in self.photo_file_ids]
            self.photo_file_ids = []
        ids = [x.file_id for x in self.photos]
        if len(set(ids)) != len(ids):
            raise ValueError("같은 사진을 두 번 붙였어요.")
        return self


class VisitPhotoIn(BaseModel):
    """요청 사진 한 장 (이름표는 '거실 벽' · '안방 천장'처럼 20자 안)"""

    file_id: uuid.UUID
    label: Annotated[Text, Field(max_length=20), Tidy] | None = None

    @field_validator("label")
    @classmethod
    def _blank(cls, v: str | None) -> str | None:
        return v or None


class FailedOut(BaseModel):
    vendor_id: uuid.UUID
    code: Literal[
        "unavailable",
        "already",
        "not_shortlisted",
        "no_estimate",
        "paper_unsupported",
        "blocked_retry",
    ] = Field(
        description="unavailable: 지금 믿집에서 일할 수 없는 업체 · already: 이미 요청한 업체 ·"
        " (v3) not_shortlisted: 담지 않은 업체 · no_estimate · paper_unsupported · blocked_retry"
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
        description="닫힌 까닭: other_chosen(다른 업체 확정) · reselected(다시 고르기) · vendor_stopped(업체 기능 멈춤)"
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
    # ---- v3 상태판 (C14 · D03, 1단계에서 채움) ----
    head: VisitHeadOut | None = Field(default=None, description="요청 머리")
    board: list[BoardRowOut] = Field(default=[], description="업체마다 한 줄 (요청 순)")


class DeclineIn(BaseModel):
    code: Literal["full", "out_of_area", "other"] = Field(
        description="일정이 꽉 찼어요 · 지역 밖이에요 · 그 밖"
    )
    note: Annotated[Text, Field(max_length=100), Tidy] | None = Field(
        default=None, description="v3: 그 밖일 때 한 줄"
    )


class VendorVisitRow(BaseModel):
    """업체가 보는 요청 한 줄. 집은 구 · 동까지만이고 고객 이름 · 연락처 · 동 · 호는 없다(B3: 연락은
    실측이 확정되면 채팅으로)."""

    id: uuid.UUID
    received_at: datetime
    code: str = Field(description="요청 번호 (연락처가 없으면 고객이 이 번호를 말한다)")
    trade: str
    grade: str | None = Field(description="도배 유형 (economy · basic). v3는 요청 때 고른 벽지")
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
    # ---- v3 작업함 (V03 · D04, 1단계에서 채움). 고객 이름 · 연락처는 없다 ----
    area_label: str | None = Field(default=None, description="노원구 상계동 · 공급 69.4㎡")
    home: str | None = Field(default=None, description="아파트 · 도배 전체 · 빈 집")
    wish_start: date | None = None
    wish_end: date | None = None
    work_wish_on: date | None = Field(default=None, description="공사 시작 희망일 (L04)")
    estimate_total: int | None = None
    budget_won: int | None = Field(default=None, description="고객 예산 (D03 B)")
    state: "StateTagOut | None" = Field(default=None, description="상태 아이콘 + 글자 (N4 C)")
    next: "VendorNextOut | None" = Field(default=None, description="다음 할 일 · 기한")
    attempt: int | None = None


class StateTagOut(BaseModel):
    """상태 아이콘 + 글자 (N4 C)"""

    icon: Literal["todo", "wait", "ok", "done", "late"]
    label: str = Field(description="해요체 화면 말 (영어 상태값을 보이지 않는다)")


class VendorNextOut(BaseModel):
    label: str = Field(description="기간 답하기 · 수락하기 · 견적서 보내기 …")
    due_at: datetime | None
    overdue: bool


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
    sched: int = Field(default=0, description="v3 일정 탭: 앞으로 잡힌 실측 (1단계에서 채움)")


class VendorVisitDetailOut(VendorVisitRow):
    """업체가 보는 요청 자세히"""

    area_m2: Decimal | None
    area_basis: str | None
    occupied: bool
    home_text: str = Field(description="노원구 · 32평 · 빈 집")
    when_text: str = Field(description="희망 시기: 11.16(월) ~ 11.23(월)")
    message: str | None
    # ---- v3 기간 답하기 (V04 · D14, 1단계에서 채움) ----
    photos: list[uuid.UUID] = Field(
        default=[],
        description="요청 사진 (보낸 순). 보기: GET /vendor/visits/{visit_id}/photos/{file_id}",
    )
    photo_labels: list[str | None] = Field(
        default=[], description="사진 이름표 (photos와 같은 순서, 없으면 비움)"
    )
    # v4 반셀프(QA r7 N5): 요청 브리핑 카드만이 아니라 요청 화면 · 작업함 옆 자세히에도 보여요
    diy: list[str] = Field(
        default=[],
        description="고객이 직접 할 일(반셀프 칩 화면 말). 요청 때 고객이 업체에 알린 사본(visits.diy), "
        "없으면 빈 목록",
    )
    capacity: int | None = Field(default=None, description="반나절 한 칸에 받는 실측 수 (L03)")
    instant_default: bool | None = None
    window: WindowOut | None = None
    booked: BookedOut | None = None
    proposal: VisitProposalOut | None = None
    change: ChangeOut | None = None
    taken: list["VendorSlotOut"] = Field(default=[], description="내 달력: 잡힌 · 잡아 둔 반나절")
    other_windows: list["OtherWindowOut"] = Field(default=[], description="다른 요청에 답한 기간")
    open_count: int | None = Field(
        default=None,
        description="고객이 고를 수 있는 칸 수. ?start=&end=&excluded=를 주면 그 기간으로 미리 센 값"
        "(보내기 전), 안 주면 답한 기간(없으면 희망 기간)",
    )
    propose_options: list["SlotOut"] = Field(
        default=[],
        description="다른 날 제안 고를 거리 (수락 기다릴 때): 고객 희망 기간 안 · 내가 받을 수 있는"
        " 반나절, 고객이 고른 반나절은 빼고 (계산 엔진)",
    )
    reply_due_at: datetime | None = None
    thread_id: uuid.UUID | None = None


class VendorSlotOut(BaseModel):
    """업체 일정 반나절 한 칸 (V08 · D14 달력)"""

    visit_id: uuid.UUID
    day: date
    half: Half
    kind: Literal["hold", "booked"]
    seat: int
    area_label: str = Field(description="노원구 상계동 · 공급 69.4㎡ (고객 이름 없음)")
    hold_until: datetime | None


class OtherWindowOut(BaseModel):
    visit_id: uuid.UUID
    start: date
    end: date


class VendorScheduleOut(BaseModel):
    """업체 일정 탭 (V08): 반나절별 확정 · 잡아 둠"""

    start: date
    end: date
    capacity: int
    items: list[VendorSlotOut] = Field(description="날 · 반나절 · 동네 순")


class WindowIn(BaseModel):
    """기간 답하기 (V04): 기간 + 빼는 날 + 바로 확정"""

    start: date
    end: date
    excluded: list[date] = Field(default_factory=list, max_length=31)
    instant: bool = False

    @model_validator(mode="after")
    def _range(self) -> "WindowIn":
        if self.end < self.start or (self.end - self.start).days > 62:
            raise ValueError("기간을 다시 골라 주세요. (62일 안)")
        if any(d < self.start or d > self.end for d in self.excluded):
            raise ValueError("빼는 날은 기간 안에서 골라 주세요.")
        if len(set(self.excluded)) != len(self.excluded):
            raise ValueError("같은 날을 두 번 뺐어요.")
        return self


class WindowAnswerOut(BaseModel):
    visit_id: uuid.UUID
    status: VisitStatus
    open_halves: int = Field(description="고객이 고를 수 있는 칸 수")
    pick_due_at: datetime


class ProposeIn(BaseModel):
    """다른 날 제안 (V07): 반나절 1~3개 · 고객 희망 기간 안"""

    reason_code: Literal["other_site", "no_crew", "other"]
    note: Annotated[Text, Field(max_length=100), Tidy] | None = None
    slots: list[SlotIn] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def _distinct(self) -> "ProposeIn":
        if len({(x.day, x.half) for x in self.slots}) != len(self.slots):
            raise ValueError("같은 반나절을 두 번 골랐어요.")
        return self


class SlotsIn(BaseModel):
    """바꾸기 요청에 다른 날 내기 (V20)"""

    slots: list[SlotIn] = Field(min_length=1, max_length=3)


class VendorVisitStateOut(BaseModel):
    visit_id: uuid.UUID
    status: VisitStatus
    booked: BookedOut | None
    thread_id: uuid.UUID | None


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
    quote_due_at: datetime | None = Field(
        default=None,
        description="견적서 낼 기한: 장부 visits.quote_due_at(실측일 + 3일 18:00) 그대로. "
        "처음 보내기 전(실측 확정 · 실측 받음)만, 그 밖은 비어 있다",
    )


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
    # ---- v3 비교 (C33 · D18, 1단계에서 채움) ----
    diff_vs_estimate: int | None = Field(
        default=None, description="가견적과 차이 (믿집 계산, 고객이 낼 금액 기준)"
    )
    visit_day: date | None = Field(default=None, description="실측일")
    valid_soon: bool = Field(default=False, description="유효기간 3일 안")
    valid_soon_at: list[datetime] = Field(
        default=[],
        description="유효기간 알림 시각 (3일 · 1일 전 18:00, 이른 것 먼저, 지난 시각은 빼고)",
    )
    requote_at: datetime | None = Field(default=None, description="'다시 받기' 요청한 때")
    rating: RatingOut | None = None


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
    gap_total: int | None = Field(
        default=None,
        description="받은 견적서(최신 버전) 합계의 가장 큰 값 − 가장 작은 값 (2곳 이상일 때, 믿집 계산."
        " C33 '두 곳이 40만 7,000원 차이 나요')",
    )


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
    booked: int = Field(default=0, description="실측 날짜가 정해진(실측 받음 포함) 요청 수")


class VisitQuotesOut(BaseModel):
    """서류: 한 업체가 보낸 실측 견적서 버전들 (닫힌 요청도 기록으로 남는다)"""

    visit_id: uuid.UUID
    trade: str
    vendor_name: str
    status: str
    close_reason: str | None
    versions: list[VendorQuoteOut] = Field(description="최신 먼저")


VendorListOut.model_rebuild()
VendorVisitRow.model_rebuild()
VendorVisitDetailOut.model_rebuild()
VisitCreateIn.model_rebuild()
