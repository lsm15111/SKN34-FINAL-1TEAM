import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.calc.schedule import JOB_MAX_DAYS
from app.quote.models import QUOTE_FILES_MAX

VatMode = Literal["included", "excluded", "exempt"]  # 넣은 금액이 부가세 포함 · 부가세 빼고 · 면세
AMOUNT_MAX = 1_000_000_000


class StandardLineOut(BaseModel):
    key: str
    name: str
    qty: Decimal | None
    unit: str
    unit_price: int | None
    amount: int | None
    state: str
    source: str


class RangePartOut(BaseModel):
    driver: str = Field(
        description="폭의 이유: qty:area · qty:edge · qty:flat · qty:door(수량) · share:area · share:edge"
        "(고른 공간 몫) · price(업체 단가) · visit(실측 보정) · cond:removal …('실측 후' 줄)"
    )
    share: Decimal = Decimal(0)
    better: str | None = Field(
        default=None, description="수량: 이만큼 알면 폭이 줄어요 (area 면적 입력 · self 셀프 실측)"
    )
    low_if: int | None = Field(
        default=None,
        description="수량은 더 알 때, 단가는 가견적을 받을 때, 조건 줄은 하게 될 때 범위",
    )
    high_if: int | None = None
    low_if_no: int | None = Field(default=None, description="조건 줄: 안 하게 될 때 범위")
    high_if_no: int | None = None


class RangeOut(BaseModel):
    """예상 범위 (믿집 계산, 부가세 포함, 만 원 단위). 이 집 금액이 10곳 중 8곳쯤 들어갈 구간"""

    version: str
    low: int
    mid: int
    high: int
    extra_max: int = Field(
        description="모르는 '실측 후' 줄을 다 하게 되면 더 들 수 있는 최대 (구간과 따로 보인다)"
    )
    precision: str = Field(description="집 크기를 얼마나 아는지: band(평형대) · area(면적 입력)")
    whole: bool = Field(description="집 전체인지 (아니면 고른 공간 몫으로 잡았어요)")
    parts: list[RangePartOut] = Field(
        description="폭을 만든 이유, 몫이 큰 순 (목록에서는 비어 있다)"
    )
    notes: list[str]


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
    space_share: Decimal = Field(description="고른 공간 몫 (집 전체 수량 대비, 1이면 집 전체)")
    range: RangeOut


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
    range: RangeOut = Field(description="공정을 합친 예상 범위 (공정이 하나면 그 공정 범위)")
    budget: BudgetOut | None


class QuoteDraftIn(BaseModel):
    """실측 견적서 임시 저장 (통째로). 파일은 먼저 POST /files (kind=quote_doc)로 올린다."""

    file_ids: list[uuid.UUID] = Field(default_factory=list, max_length=QUOTE_FILES_MAX)
    measured_on: date | None = Field(default=None, description="실측한 날")
    entered_amount: int | None = Field(
        default=None, ge=0, le=AMOUNT_MAX, description="견적서에 적은 낼 금액 그대로 (원)"
    )
    vat_mode: VatMode | None = None
    days: int | None = Field(default=None, ge=1, le=JOB_MAX_DAYS, description="공사 기간 (일)")
    valid_until: date | None = Field(default=None, description="견적 유효기간 (이날까지)")

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


class QuoteBriefOut(BaseModel):
    """고객 쪽 요청 목록에 붙는 보낸 최신 견적서 요약"""

    id: uuid.UUID
    code: str
    version: int
    total: int
    days: int | None
    valid_until: date | None
    sent_at: datetime
