"""에이전트가 채우는 출력 모양. 숫자 범위 · 선택지 같은 검사는 LLM 스키마에 두지 않고 코드에서 한다."""

from typing import Literal

from pydantic import BaseModel


class Change(BaseModel):
    """대화에서 뽑은 공정 칸 하나의 변경. 공정 스펙에 맞지 않으면 코드가 버린다."""

    field: str  # "공정.칸" (예: dobae.grade)
    op: Literal["set", "add", "remove"]  # add · remove는 여러 개 고르는 칸(multi)만
    value: str  # 선택지 값 하나, count 숫자, 또는 unknown


class TradeQuestion(BaseModel):
    trade: str  # 공정 키
    question: str  # 그 공정 전문가에게 물을 한 문장


class RouterOut(BaseModel):
    """상담 라우터: 바꿀 칸, 공정 전문가에게 넘길 질문, 고객에게 보일 짧은 답"""

    pyeong: float | None
    area_m2: float | None
    area_basis: Literal["supply", "exclusive", "unknown"] | None
    occupied: bool | None
    balcony_ext: bool | None
    built_year: int | None
    changes: list[Change]
    questions: list[TradeQuestion]
    out_of_scope: bool
    # 대화로 공정을 더하거나 뺀다 (공정 키). 코드가 레지스트리로 검사한다
    trades_add: list[str] = []
    trades_remove: list[str] = []
    reply: str


class ExpertAnswer(BaseModel):
    """공정 전문가 답. sources는 그 공정 지식 '출처' id"""

    answer: str
    sources: list[str]


class PlanStep(BaseModel):
    key: str
    note: str


class Caution(BaseModel):
    text: str
    source: str


class TradePlan(BaseModel):
    """공정 에이전트의 의견. 숫자는 없고, 숫자는 계산 엔진 결과를 화면이 보여 준다."""

    summary: str
    steps: list[PlanStep]
    visit_checks: list[str]
    cautions: list[Caution]
