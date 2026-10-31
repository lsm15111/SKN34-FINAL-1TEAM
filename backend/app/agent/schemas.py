"""에이전트가 채우는 출력 모양. 숫자 범위 같은 검사는 LLM 스키마에 두지 않고 코드에서 한다."""

from typing import Literal

from pydantic import BaseModel


class CardUpdate(BaseModel):
    """상담사가 대화에서 뽑은 집 정보와 고객 말에 대한 짧은 답"""

    pyeong: float | None
    area_m2: float | None
    area_basis: Literal["supply", "exclusive", "unknown"] | None
    grade: Literal["economy", "basic", "unknown"] | None
    include_ceiling: Literal["yes", "no", "unknown"] | None
    occupied: bool | None
    balcony_ext: bool | None
    built_year: int | None
    out_of_scope: bool
    reply: str


class PlanStep(BaseModel):
    key: str
    note: str


class Caution(BaseModel):
    text: str
    source: str


class DobaePlan(BaseModel):
    """도배 공정 에이전트의 의견. 숫자는 없고, 숫자는 계산 엔진 결과를 화면이 보여 준다."""

    summary: str
    steps: list[PlanStep]
    visit_checks: list[str]
    cautions: list[Caution]
