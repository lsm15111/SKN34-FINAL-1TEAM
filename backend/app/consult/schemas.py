"""상담 API 입출력. 필수 칸은 프로젝트 정보로 채우고, 빈 칸만 첫 화면 폼으로 받는다.

대화는 궁금한 것 · 바꿀 값에 쓴다. 대화와 카드는 화면이 들고 매 턴 보낸다 (MVP, DB에 남기지 않음).
"""

import uuid
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator

from app.agent.schemas import PlanStep
from app.calc.mokgong import Item

Trade = Literal["dobae", "mokgong"]
CardField = Literal[
    "area", "area_basis", "occupied", "grade", "include_ceiling", "doors", "door_frame"
]
LineState = Literal["included", "bundled", "separate", "optional", "after_visit", "excluded"]


class ConsultCard(BaseModel):
    """요구사항 카드(도배 · 목공). 비어 있는 필수 칸은 코드가 폼으로 묻는다."""

    trades: list[Trade] = Field(default_factory=lambda: ["dobae"], min_length=1, max_length=2)
    area_m2: Decimal | None = Field(default=None, gt=0, le=1000, decimal_places=1)
    area_basis: Literal["supply", "exclusive"] | None = None
    occupied: bool | None = None
    balcony_ext: bool = False
    built_year: int | None = Field(default=None, ge=1900, le=2100)
    # 도배
    grade: Literal["economy", "basic"] | None = None
    include_ceiling: bool | None = None
    # 목공 (항목 · 공간은 프로젝트에서 가져온다)
    mok_items: list[Item] = Field(default_factory=list, max_length=4)
    mok_spaces: list[Annotated[str, StringConstraints(max_length=20)]] = Field(
        default_factory=list, max_length=30
    )
    doors: int | None = Field(default=None, ge=1, le=10)
    door_frame: bool | None = None
    # 고객이 '모르겠어요'라고 해서 기본값을 넣은 칸. 실측 때 확인한다
    to_check: list[CardField] = Field(default_factory=list, max_length=7)

    @model_validator(mode="after")
    def _trades(self) -> "ConsultCard":
        if len(set(self.trades)) != len(self.trades) or len(set(self.mok_items)) != len(
            self.mok_items
        ):
            raise ValueError("같은 값이 두 번 들어 있어요.")
        if "mokgong" in self.trades and not self.mok_items:
            raise ValueError("목공 항목을 하나 이상 골라 주세요.")
        return self


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(max_length=1000)


class Answer(BaseModel):
    """폼에서 고른 · 적은 답"""

    field: CardField
    value: str = Field(max_length=20)


class ConsultIn(BaseModel):
    # 처음에는 비워 보낸다. 그러면 내 프로젝트(project_id)의 정보로 칸을 채운다
    card: ConsultCard | None = None
    history: list[Turn] = Field(default_factory=list, max_length=40)
    message: str | None = Field(default=None, max_length=500)
    answers: list[Answer] = Field(default_factory=list, max_length=7)
    project_id: uuid.UUID | None = None


class Choice(BaseModel):
    value: str
    label: str


class Question(BaseModel):
    field: CardField
    trade: Trade | None  # 어느 공정 질문인지. 공통이면 비어 있다
    text: str
    choices: list[Choice]


class LineOut(BaseModel):
    key: str
    name: str
    qty: Decimal | None
    unit: str
    unit_price: int | None
    amount: int | None
    state: LineState
    source: str


class StepOut(BaseModel):
    key: str
    name: str
    half_days: int


class QuoteOut(BaseModel):
    """표준견적서. 계산 엔진 결과 그대로, VAT 별도 합계와 VAT를 따로 둔다."""

    version: str
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
    """공정 에이전트 의견 (AI가 만든 설명)"""

    summary: str
    steps: list[PlanStep]
    visit_checks: list[str]
    cautions: list[CautionOut]
    prompt_version: str


class TradeOut(BaseModel):
    trade: Trade
    quote: QuoteOut
    plan: PlanOut | None
    # new: 새 의견 · same: 이 공정 칸이 그대로라 다시 만들지 않음 · failed: 만들지 못함
    plan_status: Literal["new", "same", "failed"]


class ScheduleStepOut(BaseModel):
    trade: Trade
    key: str
    name: str
    half_days: int


class ConsultOut(BaseModel):
    card: ConsultCard
    reply: str | None
    questions: list[Question]  # 비어 있지 않으면 폼으로 받는다
    results: list[TradeOut]  # 칸이 다 차면 공정마다 (목공 → 도배 순)
    schedule: list[ScheduleStepOut]  # 공정을 이은 예상 공정표
    days: Decimal | None
    notice: str | None
