"""공정 계산 엔진이 같이 쓰는 것: 줄 · 단계 모양, 반올림, 면적 환산.

금액은 원 정수이고 반올림은 won() 한 곳에서만 한다. 면적 · 길이는 소수 한 자리, 품 · 기간은 0.5 단위로 올린다.
"""

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from typing import Literal, Protocol

AreaBasis = Literal["supply", "exclusive"]
# 포함 상태 6종. 합계에는 included(포함) · separate(따로 계산)만 들어간다
LineState = Literal["included", "bundled", "separate", "optional", "after_visit", "excluded"]
COUNTED = ("included", "separate")
# 줄 단가의 근거: 공공 기준 · 팀 가정값 · 공공 단가 없음(업체 견적에서 확인)
Basis = Literal["public", "assumed", "none"]

PYEONG_M2 = Decimal("3.3058")
BASIS_LABEL = {"supply": "공급면적", "exclusive": "전용면적"}


@dataclass(frozen=True)
class Line:
    key: str
    name: str
    qty: Decimal | None
    unit: str
    unit_price: int | None
    amount: int | None
    state: LineState
    source: str
    basis: Basis = "public"


@dataclass(frozen=True)
class Step:
    key: str
    name: str
    half_days: int
    # 도배가 끝난 뒤에 하는 작업 (장판 깔기 · 가구 설치 · 조명 교체). 공정을 이을 때 뒤로 모은다
    late: bool = False


class Quote(Protocol):
    """공정 견적이 갖출 모양. 공정마다 <공정>Quote가 이 이름들을 가지면 상담 · 요약이 그대로 읽는다."""

    version: str
    lines: list[Line]
    subtotal: int  # VAT 별도 합계 (included · separate 줄만)
    vat: int
    total: int
    man_days: Decimal
    steps: list[Step]
    days: Decimal  # 이 공정만 했을 때 기간
    assumptions: list[str]


def won(x: Decimal) -> int:
    """원 단위 반올림. 계산 엔진 안에서 금액은 모두 이 함수로 끝낸다."""
    return int(x.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def m2(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def half_up(x: Decimal) -> Decimal:
    """0.5 단위로 올린다 (품 · 기간)."""
    return (x * 2).to_integral_value(rounding=ROUND_CEILING) / 2


def half_days(man_days: Decimal, crew: int) -> int:
    """품을 하루 인원으로 나눠 반나절 단위로 올린다. 최소 반나절."""
    return max(int((man_days / crew * 2).to_integral_value(rounding=ROUND_CEILING)), 1)


def pyeong_to_m2(pyeong: Decimal) -> Decimal:
    return m2(pyeong * PYEONG_M2)
