"""도배 상담 API 입출력. 대화와 카드는 화면이 들고 매 턴 보낸다 (MVP, DB에 남기지 않음)."""

import uuid
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.agent.schemas import PlanStep

CardField = Literal["area", "area_basis", "grade", "include_ceiling", "occupied"]


class DobaeCard(BaseModel):
    """요구사항 카드(도배). 비어 있는 필수 칸을 코드가 하나씩 묻는다."""

    area_m2: Decimal | None = Field(default=None, gt=0, le=1000, decimal_places=1)
    area_basis: Literal["supply", "exclusive"] | None = None
    grade: Literal["economy", "basic"] | None = None
    include_ceiling: bool | None = None
    occupied: bool | None = None
    balcony_ext: bool = False
    built_year: int | None = Field(default=None, ge=1900, le=2100)
    # 고객이 '모르겠어요'라고 해서 기본값을 넣은 칸. 실측 때 확인한다
    to_check: list[CardField] = Field(default_factory=list, max_length=5)


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(max_length=1000)


class Answer(BaseModel):
    """선택지 버튼으로 고른 답"""

    field: CardField
    value: str = Field(max_length=20)


class ConsultIn(BaseModel):
    card: DobaeCard = Field(default_factory=DobaeCard)
    history: list[Turn] = Field(default_factory=list, max_length=40)
    message: str | None = Field(default=None, max_length=500)
    answer: Answer | None = None
    # 처음 한 번, 내 프로젝트의 기본정보로 칸을 채운다
    project_id: uuid.UUID | None = None


class Choice(BaseModel):
    value: str
    label: str


class Question(BaseModel):
    field: CardField
    text: str
    choices: list[Choice]


class LineOut(BaseModel):
    key: str
    name: str
    qty: Decimal | None
    unit: str
    unit_price: int | None
    amount: int | None
    state: Literal["included", "bundled", "separate", "optional", "after_visit", "excluded"]
    source: str


class StepOut(BaseModel):
    key: str
    name: str
    half_days: int


class QuoteOut(BaseModel):
    """표준견적서(도배). 계산 엔진 결과 그대로, VAT 별도 합계와 VAT를 따로 둔다."""

    version: str
    paper_m2: Decimal
    wall_m2: Decimal
    ceiling_m2: Decimal
    lines: list[LineOut]
    subtotal: int
    vat: int
    total: int
    man_days: Decimal
    steps: list[StepOut]
    days: Decimal
    assumptions: list[str]


class CautionOut(BaseModel):
    text: str
    source: str  # 출처 이름


class PlanOut(BaseModel):
    """도배 공정 에이전트 의견 (AI가 만든 설명)"""

    summary: str
    steps: list[PlanStep]
    visit_checks: list[str]
    cautions: list[CautionOut]
    prompt_version: str


class ConsultOut(BaseModel):
    card: DobaeCard
    reply: str | None
    question: Question | None
    quote: QuoteOut | None
    plan: PlanOut | None
    # new: 새 의견 · same: 카드가 그대로라 다시 만들지 않음 · failed: 만들지 못함
    plan_status: Literal["new", "same", "failed"] | None
    notice: str | None
