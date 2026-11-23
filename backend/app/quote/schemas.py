import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, field_validator, model_validator

from app.calc.schedule import JOB_MAX_DAYS
from app.quote.models import QUOTE_FILES_MAX
from app.shared.text import Tidy

VatMode = Literal["included", "excluded", "exempt"]  # 넣은 금액이 부가세 포함 · 부가세 빼고 · 면세
AMOUNT_MAX = 1_000_000_000
# 도배 금액 기준(ADR 0004): 도배만 하는 공사 · 전체 철거나 큰 목공이 든 리모델링
Profile = Literal["paper_only", "remodel"]


class StandardLineOut(BaseModel):
    key: str
    name: str
    qty: Decimal | None
    unit: str
    unit_price: int | None
    amount: int | None
    state: str
    source: str
    basis: str | None = Field(
        default=None, description="v3: public · market · assumed · none (줄 근거)"
    )


class RollOut(BaseModel):
    """벽지 롤 수(calc.rolls): 롤 한 개 넓이(제조사 규격)로 나눠 올림. 여분은 셈 밖이에요."""

    key: Literal["silk", "hapji_wide", "hapji_narrow"]
    name: str = Field(description="실크 · 광폭 합지 · 소폭 합지")
    size: str = Field(description="롤 크기(폭 × 길이) '106cm × 15.6m'")
    count: int = Field(description="롤 수(올림, 여분 빼고)")
    spare_min: int = Field(description="여분 롤(셈 밖, 따로 보이기만)")
    spare_max: int
    text: str = Field(description="화면 말 '실크(106cm × 15.6m) 약 11롤 · 여분 1~2롤은 따로'")


class StandardTradeOut(BaseModel):
    trade: str
    version: int
    grade: str | None
    lines: list[StandardLineOut]
    supply: int
    vat: int
    total: int
    man_day: Decimal
    crew: int
    notes: list[str]
    days: Decimal | None = Field(
        default=None,
        description="이 공정만 했을 때 예상 일수(반나절 단위 · 계산 엔진). 전체 days는 공정별 일수의 합",
    )
    profile: Profile | None = Field(
        default=None,
        description="도배 금액 기준(계산 엔진이 공사 조건으로 고름): paper_only 도배만 하는 공사 · "
        "remodel 리모델링. 목공 · 옛 판은 비움",
    )
    profile_name: str | None = Field(
        default=None, description="기준 화면 이름: 도배만 하는 공사 기준 · 리모델링 기준"
    )
    own_paper: bool = Field(
        default=False,
        description="도배: 고객이 벽지를 직접 사요(반셀프 '벽지 직접 구매'). 도배지 줄(key paper)은 '안 함' · "
        "고객 구매라 합계 밖이에요(수량 · 금액은 참고)",
    )
    rolls: RollOut | None = Field(
        default=None,
        description="도배: 도배지 줄 양 → 벽지 롤 수(계산 엔진, 보이기용. 돈은 벽지 평으로 세요). "
        "지식 카드 계산 ref standard.rolls",
    )
    paper_note: str | None = Field(
        default=None,
        description="벽지 직접 구매일 때 안내 한 줄(틀): 업체 가견적은 벽지 값이 든 값이에요",
    )


class BudgetOut(BaseModel):
    band: str
    status: Literal["within", "over", "open"]  # open: 위 한도 없음 · 아직 몰라요
    over_by: int | None  # 넣은 예산 위 한도보다 많은 금액 (부가세 포함 합계 기준)


class StandardOut(BaseModel):
    project_id: uuid.UUID
    code: str
    project_rev: int
    formula_ver: str
    price_ver: str
    computed_at: datetime
    area_m2: Decimal
    area_basis: str
    pyeong: Decimal
    trades: list[StandardTradeOut]
    supply: int
    vat: int
    total: int
    budget: BudgetOut | None
    # ---- v3 (C07 · C60 · D01, 1단계에서 채움): 도배지 평 × 시장 평균 · 부분 공사 공간 몫 ----
    scope: Literal["full", "partial"] | None = Field(default=None, description="전체 · 부분")
    spaces: list[str] = Field(default=[], description="부분 공사 공간 kind 사본")
    faces: list[str] = Field(default=[], description="벽 · 천장 사본")
    share_ver: str | None = Field(default=None, description="공간 몫 표 판 (부분일 때만)")
    market_ver: str | None = Field(default=None, description="벽지 시장 평균 가격 판 (도배지 줄)")
    budget_fit: Literal["within", "over"] | None = Field(
        default=None, description="예산(원) 안 · 밖 (예산이 없으면 비움)"
    )
    days: Decimal | None = Field(
        default=None,
        description="예상 공사 일수 (C07 '예상 2일', 반나절 단위 · 계산 엔진, 손님 계산 days와 같은 값."
        " 여러 공정이면 공정별 일수의 합)",
    )


class QuoteDraftIn(BaseModel):
    """실측 견적서 임시 저장 (통째로). 파일은 먼저 POST /files (kind=quote_doc)로 올린다."""

    file_ids: list[uuid.UUID] = Field(default_factory=list, max_length=QUOTE_FILES_MAX)
    measured_on: date | None = Field(default=None, description="실측한 날")
    # 0원은 받지 않아요(0원 견적서가 보내지던 것, QA P7). 보낼 때도 한 번 더 본다(quote.service.seal_draft)
    entered_amount: int | None = Field(
        default=None, ge=1, le=AMOUNT_MAX, description="견적서에 적은 낼 금액 그대로 (원)"
    )
    vat_mode: VatMode | None = None
    days: int | None = Field(default=None, ge=1, le=JOB_MAX_DAYS, description="공사 기간 (일)")
    valid_until: date | None = Field(default=None, description="견적 유효기간 (이날까지)")
    # v3 '포함됐나요?' 칩 4칸 (D21). 비우면 '안 적었어요'
    incl_removal: bool | None = Field(default=None, description="기존 벽지 철거 포함")
    incl_waste: bool | None = Field(default=None, description="폐기물 처리 포함")
    paper_spec: (
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=60), Tidy] | None
    ) = Field(default=None, description="벽지 제조사 · 규격 (LX 실크벽지 베스트 · 폭 106cm)")
    warranty_months: int | None = Field(
        default=None, ge=0, le=120, description="하자 보수 기간(개월)"
    )

    @field_validator("paper_spec")
    @classmethod
    def _blank(cls, v: str | None) -> str | None:
        return v or None

    @model_validator(mode="after")
    def _files(self) -> "QuoteDraftIn":
        if len(set(self.file_ids)) != len(self.file_ids):
            raise ValueError("같은 파일을 두 번 붙였어요.")
        return self


class QuoteFileOut(BaseModel):
    file_id: uuid.UUID
    filename: str
    content_type: str
    size: int
    sort: int


class VendorQuoteOut(BaseModel):
    """실측 견적서 한 버전. supply · vat · total은 계산 엔진(from_entered)이 만든 값이다."""

    id: uuid.UUID
    code: str
    version: int
    sent_at: datetime | None = Field(description="비면 임시 저장")
    measured_on: date | None
    entered_amount: int | None
    vat_mode: str | None
    supply: int | None
    vat: int | None
    total: int | None = Field(description="고객이 낼 금액")
    days: int | None
    valid_until: date | None
    created_at: datetime
    updated_at: datetime
    files: list[QuoteFileOut]
    # v3 '포함됐나요?' 칩 4칸 (D21)
    incl_removal: bool | None = None
    incl_waste: bool | None = None
    paper_spec: str | None = None
    warranty_months: int | None = None


class QuoteBriefOut(BaseModel):
    """고객 쪽 요청 목록에 붙는 보낸 최신 견적서 요약"""

    id: uuid.UUID
    code: str
    version: int
    total: int
    days: int | None
    valid_until: date | None
    sent_at: datetime
