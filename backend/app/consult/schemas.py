"""상담 API 입출력. 공정 칸은 공정 스펙(consult.trades)으로 검사하고, 폼 질문 · 화면 말도 스펙에서 만든다.

필수 칸은 프로젝트 정보로 채우고, 빈 칸만 첫 화면 폼으로 받는다. 대화는 궁금한 것 · 바꿀 값에 쓴다.
대화와 카드는 화면이 들고 매 턴 보낸다 (MVP, DB에 남기지 않음).
"""

import uuid
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StrictInt, StringConstraints, model_validator

from app.agent.schemas import PlanStep
from app.consult.trades import REGISTRY

Short = Annotated[str, StringConstraints(max_length=20)]
# 공정 칸 값: choice → 문자열, multi → 문자열 목록, count → 정수
CardValue = Short | StrictInt | Annotated[list[Short], Field(max_length=10)]
LineState = Literal["included", "bundled", "separate", "optional", "after_visit", "excluded"]
COMMON_CHECKS = ("area_basis",)  # '모르겠어요'가 있는 공통 칸


def _known_trades(trades: list[str]) -> bool:
    return len(set(trades)) == len(trades) and set(trades) <= REGISTRY.keys()


class ConsultCard(BaseModel):
    """요구사항 카드. 공통 칸 + 공정별 칸(values). 비어 있는 필수 칸은 코드가 폼으로 묻는다."""

    trades: list[str] = Field(default_factory=lambda: ["dobae"], min_length=1, max_length=10)
    area_m2: Decimal | None = Field(default=None, gt=0, le=1000, decimal_places=1)
    area_basis: Literal["supply", "exclusive"] | None = None
    occupied: bool | None = None
    balcony_ext: bool = False
    built_year: int | None = Field(default=None, ge=1900, le=2100)
    # 공정 키 → 칸 키 → 값 (예: {"dobae": {"grade": "basic"}})
    values: dict[str, dict[str, CardValue]] = Field(default_factory=dict)
    # 공정 키 → 공간 이름 (견적 받기에서 가져온다)
    spaces: dict[str, Annotated[list[Short], Field(max_length=30)]] = Field(default_factory=dict)
    # 고객이 '모르겠어요'라고 해서 기본값을 넣은 칸 (area_basis 또는 "dobae.grade" 꼴). 실측 때 확인한다
    to_check: list[str] = Field(default_factory=list, max_length=40)

    @model_validator(mode="after")
    def _specs(self) -> "ConsultCard":
        if not _known_trades(self.trades):
            raise ValueError("상담할 수 있는 공정을 다시 골라 주세요.")
        if not (self.values.keys() | self.spaces.keys()) <= set(self.trades):
            raise ValueError("고르지 않은 공정의 값이 들어 있어요.")
        for trade, vals in self.values.items():
            spec = REGISTRY[trade]
            for k, v in vals.items():
                f = spec.field(k)
                if f is None or not f.ok(v):
                    raise ValueError("공정 칸 값을 다시 확인해 주세요.")
        for name in self.to_check:
            trade, _, k = name.partition(".")
            f = REGISTRY[trade].field(k) if trade in self.trades else None
            if name not in COMMON_CHECKS and (f is None or f.unknown is None):
                raise ValueError("확인할 칸 이름을 다시 확인해 주세요.")
        if len(set(self.to_check)) != len(self.to_check):
            raise ValueError("같은 칸이 두 번 들어 있어요.")
        return self


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(max_length=1000)


class Answer(BaseModel):
    """폼에서 고른 · 적은 답. field는 공통 칸(area · area_basis · occupied) 또는 "공정.칸"."""

    field: str = Field(max_length=40)
    value: Short | Annotated[list[Short], Field(max_length=10)]


class ConsultIn(BaseModel):
    # 처음에는 비워 보낸다. 그러면 내 프로젝트(project_id)의 정보로 칸을 채운다
    card: ConsultCard | None = None
    history: list[Turn] = Field(default_factory=list, max_length=40)
    message: str | None = Field(default=None, max_length=500)
    answers: list[Answer] = Field(default_factory=list, max_length=40)
    project_id: uuid.UUID | None = None
    # 프로젝트 없이 시작할 때만 쓰는 공정 목록 (비우면 도배)
    trades: list[str] | None = Field(default=None, min_length=1, max_length=10)

    @model_validator(mode="after")
    def _trades(self) -> "ConsultIn":
        if self.trades is not None and not _known_trades(self.trades):
            raise ValueError("상담할 수 있는 공정을 다시 골라 주세요.")
        return self


class ChoiceOut(BaseModel):
    value: str
    label: str
    desc: str = ""


class Question(BaseModel):
    field: str  # 공통 칸(area · area_basis · occupied) 또는 "공정.칸" (예: dobae.grade)
    trade: str | None  # 어느 공정 질문인지. 공통이면 비어 있다
    text: str
    # text: 글로 받기(빠른 선택 있음) · choice: 하나 고르기 · multi: 여러 개 고르기 · count: 숫자 고르기
    kind: Literal["text", "choice", "multi", "count"]
    choices: list[ChoiceOut]  # count면 '모르겠어요'만 들어 있다 (있을 때)
    min: int | None = None  # multi · count만
    max: int | None = None


class LineOut(BaseModel):
    key: str
    name: str
    qty: Decimal | None
    unit: str
    unit_price: int | None
    amount: int | None
    state: LineState
    source: str
    basis: Literal["public", "assumed", "none"]  # 공공 기준 · 팀 가정값 · 공공 단가 없음(확인 필요)


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


class Fact(BaseModel):
    """카드 값을 화면 말로 (지금까지 정한 것)"""

    trade: str | None  # 공통이면 비어 있다
    label: str
    text: str
    check: bool = False  # 모른다고 해서 기본값을 넣은 칸 (실측 때 확인)


class TradeOut(BaseModel):
    trade: str
    label: str
    quote: QuoteOut
    plan: PlanOut | None
    # new: 새 의견 · same: 이 공정 칸이 그대로라 다시 만들지 않음 · failed: 만들지 못함
    plan_status: Literal["new", "same", "failed"]


class ScheduleStepOut(BaseModel):
    trade: str
    key: str
    name: str
    half_days: int
    # prep 짐 정리 · 보양, remove 철거, main 본 작업, late 도배 뒤 작업(장판 · 가구 · 조명), finish 정리 · 청소
    phase: Literal["prep", "remove", "main", "late", "finish"]


class BasisCounts(BaseModel):
    """견적 줄 근거별 개수 ('안 함' 줄은 빼고)"""

    public: int
    assumed: int
    none: int


class SummaryOut(BaseModel):
    """공정 전체 합계 (계산 엔진이 공정 금액을 더한 값)와 이은 공정표 기간"""

    subtotal: int
    vat: int
    total: int
    days: Decimal
    basis_counts: BasisCounts


class ConsultOut(BaseModel):
    card: ConsultCard
    trade_labels: dict[str, str]  # 카드 공정 키 → 화면 말 (공정 순서대로)
    reply: str | None
    questions: list[Question]  # 비어 있지 않으면 폼으로 받는다
    facts: list[Fact]  # 지금까지 정한 것 (화면 말)
    results: list[TradeOut]  # 칸이 다 차면 공정마다 (공정 순서대로)
    schedule: list[ScheduleStepOut]  # 공정을 이은 예상 공정표
    summary: SummaryOut | None
    overlaps: list[str]  # 같이 고른 공정끼리 범위가 겹칠 수 있다는 알림 (계산은 그대로)
    notice: str | None
