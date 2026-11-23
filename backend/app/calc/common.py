"""계산 엔진이 같이 쓰는 것: 줄 · 단계 모양, 반올림, 면적 환산, 부가세.

금액은 원 정수이고 반올림은 won() 한 곳에서만 한다. 면적 · 길이는 소수 한 자리, 품 · 기간은 0.5 단위로 올린다.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from typing import Literal, Protocol

AreaBasis = Literal["supply", "exclusive"]
# 포함 상태 6종. 합계에는 included(포함) · separate(따로 계산)만 들어간다
LineState = Literal["included", "bundled", "separate", "optional", "after_visit", "excluded"]
COUNTED = ("included", "separate")
# 줄 단가의 근거: 공공 기준 · 시장 데이터 기준(v3 도배지 시장 평균) · 팀 가정값 · 공공 단가 없음(업체 견적에서 확인)
Basis = Literal["public", "market", "assumed", "none"]

PYEONG_M2 = Decimal("3.3058")
# 전용 → 공급 환산 한 값(ADR docs/v4/adr/0007): 공개 분양 · 임대 공고 평면 20곳 공급 ÷ 전용 가운데
# (data/v3/area/area_rules.json). 내 집 평 · 도배 면적 · 목공 길이 · 시세 범위가 모두 이 값을 써요.
# 바꿀 때는 이 값을 쓰는 판(refprice 집 크기 · 도배 · 목공)을 새로 만들어요(이미 만든 견적은 옛 판 그대로)
SUPPLY_PER_EXCLUSIVE = Decimal("1.315")
BASIS_LABEL = {"supply": "공급면적", "exclusive": "전용면적"}
# 계산 산식 버전. 공정 계산 · 공정표 잇기 · 평 계산이 바뀌면 올린다. 저장한 표준견적서 · 공정표에 같이 남긴다
# 2026.11.2: v3 표준견적서(도배지 줄 벽지 평 × 시장 평균 · 부분 공사 공간 몫)
FORMULA_VERSION = "2026.11.2"


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
    """공정 표준견적이 갖출 모양. 도배 · 목공 Quote가 이 이름들을 가진다."""

    version: str
    lines: list[Line]
    subtotal: int  # 공급가 (부가세 빼고, included · separate 줄만)
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


VAT_RATE = Decimal("0.1")  # 부가가치세 10% (부가가치세법 제30조)
VatMode = Literal["included", "excluded", "exempt"]


@dataclass(frozen=True)
class Money:
    supply: int  # 공급가 (부가세 빼고)
    vat: int
    total: int  # 고객이 낼 금액 (부가세 포함)


def with_vat(supply: int, rate: Decimal = VAT_RATE) -> Money:
    """공급가 → 부가세 · 합계. 부가세는 공급가 × 세율을 원 단위로 반올림한다."""
    if supply < 0 or rate < 0:
        raise ValueError("공급가와 세율은 0 이상이어야 해요")
    vat = won(Decimal(supply) * rate)
    return Money(supply, vat, supply + vat)


def from_entered(amount: int, mode: VatMode, rate: Decimal = VAT_RATE) -> Money:
    """업체가 적은 금액과 그 금액의 부가세 방식 → 공급가 · 부가세 · 합계.

    - excluded(부가세 빼고): 적은 금액이 공급가다.
    - included(부가세 포함): 적은 금액이 합계다. 공급가 = 합계 ÷ (1 + 세율) 반올림, 부가세 = 나머지.
    - exempt(면세): 부가세 0, 적은 금액이 공급가 · 합계다.
    """
    if amount < 0:
        raise ValueError("금액은 0 이상이어야 해요")
    if mode == "excluded":
        return with_vat(amount, rate)
    if mode == "included":
        supply = won(Decimal(amount) / (1 + rate))
        return Money(supply, amount - supply, amount)
    if mode == "exempt":
        return Money(amount, 0, amount)
    raise ValueError("부가세 방식을 다시 골라 주세요")


def add_money(items: Iterable[Money]) -> Money:
    """금액 여러 줄의 공급가 · 부가세 · 합계를 각각 더한다 (줄마다 이미 원 단위라 반올림하지 않는다)."""
    rows = list(items)
    return Money(sum(m.supply for m in rows), sum(m.vat for m in rows), sum(m.total for m in rows))


def sum_won(values: Iterable[int]) -> int:
    """원 단위 금액 여러 개를 더한다 (공정별 낼 금액 합계)."""
    return sum(values)


def sum_days(values: Iterable[Decimal]) -> Decimal:
    """공정별 예상 일수(반나절 단위)를 차례로 한 것처럼 더한다 (표준견적서 '예상 2일')."""
    return m2(sum(values, Decimal(0)))
