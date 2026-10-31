"""도배 표준견적서와 예상 공정표.

금액은 원 정수이고 반올림은 won() 한 곳에서만 한다. 면적은 ㎡ 소수 한 자리, 품은 0.5 단위로 올린다.
실측 전이라 면적은 평형에서 가정값으로 추정하고, 그 가정은 결과의 assumptions에 그대로 남긴다.
"""

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from typing import Literal

AreaBasis = Literal["supply", "exclusive"]
Grade = Literal["economy", "basic"]
# 포함 상태 6종. 합계에는 included(포함) · separate(따로 계산)만 들어간다
LineState = Literal["included", "bundled", "separate", "optional", "after_visit", "excluded"]
COUNTED = ("included", "separate")

PYEONG_M2 = Decimal("3.3058")
GRADE_PAPER = {"economy": "합지", "basic": "실크"}
BASIS_LABEL = {"supply": "공급면적", "exclusive": "전용면적"}


@dataclass(frozen=True)
class DobaePrices:
    """계산에 쓰는 기준 단가와 가정값 한 벌. refprice가 버전별로 만들어 넘긴다."""

    version: str
    labor_wall: int  # 벽 도배지바름 원/㎡ (풀 포함, 도배지 제외)
    labor_ceiling: int  # 천장 도배지바름 원/㎡
    labor_ratio: Decimal  # 단가 중 노무비 비율. 할증은 노무비에만 붙인다
    paper: dict[str, int]  # 등급별 도배지 재료비 원/㎡
    primer: int  # 초배지 원/㎡
    removal: int  # 기존 벽지 떼내기 원/㎡ (노무비만)
    paper_ratio: Decimal  # 정배지 소요량 ㎡/㎡ (할증 포함)
    primer_wall_ratio: Decimal  # 초배지 소요량 (벽)
    primer_ceiling_ratio: Decimal  # 초배지 소요량 (천장)
    md_wall: Decimal  # 도배공 품 인/㎡ (벽)
    md_ceiling: Decimal  # 도배공 품 인/㎡ (천장, 가산 포함)
    occupied_output: Decimal  # 짐 있는 집 시공량 비율 (0.85 = 15% 감산)
    area_factor: dict[str, Decimal]  # 면적 기준별 도배 면적 환산 (가정값)
    ceiling_share: Decimal  # 도배 면적 중 천장 비율 (가정값)
    balcony_factor: Decimal  # 발코니 확장 가산 (가정값)
    crew: int  # 하루 들어가는 도배공 수 (가정값)
    vat_rate: Decimal
    sources: dict[str, str]  # 줄 키 → 출처 문구


@dataclass(frozen=True)
class DobaeInput:
    area_m2: Decimal
    area_basis: AreaBasis
    grade: Grade
    include_ceiling: bool
    occupied: bool
    balcony_ext: bool = False


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


@dataclass(frozen=True)
class Step:
    key: str
    name: str
    half_days: int


@dataclass(frozen=True)
class DobaeQuote:
    version: str
    paper_m2: Decimal  # 도배하는 면적 (벽 + 천장)
    wall_m2: Decimal
    ceiling_m2: Decimal
    lines: list[Line]
    subtotal: int
    vat: int
    total: int
    man_days: Decimal  # 도배공 품
    steps: list[Step]
    days: Decimal
    assumptions: list[str]


def won(x: Decimal) -> int:
    """원 단위 반올림. 계산 엔진 안에서 금액은 모두 이 함수로 끝낸다."""
    return int(x.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def m2(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def half_up(x: Decimal) -> Decimal:
    """0.5 단위로 올린다 (품 · 기간)."""
    return (x * 2).to_integral_value(rounding=ROUND_CEILING) / 2


def pyeong_to_m2(pyeong: Decimal) -> Decimal:
    return m2(pyeong * PYEONG_M2)


def quote(inp: DobaeInput, p: DobaePrices) -> DobaeQuote:
    if inp.area_m2 <= 0:
        raise ValueError("면적은 0보다 커야 해요")
    gross = inp.area_m2 * p.area_factor[inp.area_basis]
    if inp.balcony_ext:
        gross *= p.balcony_factor
    ceiling = m2(gross * p.ceiling_share)
    wall = m2(gross) - ceiling
    ceil_used = ceiling if inp.include_ceiling else Decimal(0)
    paper_area = wall + ceil_used
    src = p.sources

    wall_amt = won(wall * p.labor_wall)
    ceil_amt = won(ceiling * p.labor_ceiling)
    paper_qty = m2(paper_area * p.paper_ratio)
    primer_qty = m2(wall * p.primer_wall_ratio + ceil_used * p.primer_ceiling_ratio)
    lines = [
        Line(
            "wall",
            "벽 도배 시공 (풀 포함)",
            wall,
            "㎡",
            p.labor_wall,
            wall_amt,
            "included",
            src["wall"],
        ),
        Line(
            "ceiling",
            "천장 도배 시공 (풀 포함)",
            ceiling,
            "㎡",
            p.labor_ceiling,
            ceil_amt if inp.include_ceiling else None,
            "included" if inp.include_ceiling else "excluded",
            src["ceiling"],
        ),
        Line(
            "paper",
            f"도배지 ({GRADE_PAPER[inp.grade]})",
            paper_qty,
            "㎡",
            p.paper[inp.grade],
            won(paper_qty * p.paper[inp.grade]),
            "included",
            src[f"paper_{inp.grade}"],
        ),
        Line(
            "primer",
            "초배지",
            primer_qty,
            "㎡",
            p.primer,
            won(primer_qty * p.primer),
            "included",
            src["primer"],
        ),
    ]
    if inp.occupied:
        labor = Decimal(wall_amt + (ceil_amt if inp.include_ceiling else 0))
        extra = won(labor * p.labor_ratio * (1 / p.occupied_output - 1))
        lines.append(
            Line(
                "occupied",
                "짐 있는 집 작업 할증",
                None,
                "식",
                None,
                extra,
                "included",
                src["occupied"],
            )
        )
    lines.append(
        Line(
            "removal",
            "기존 벽지 철거",
            paper_area,
            "㎡",
            p.removal,
            won(paper_area * p.removal),
            "after_visit",
            src["removal"],
        )
    )
    lines.append(Line("waste", "폐기물 처리", None, "식", None, None, "after_visit", src["none"]))
    if inp.occupied:
        lines.append(
            Line("moving", "짐 이동 · 보양", None, "식", None, None, "after_visit", src["none"])
        )

    subtotal = sum(ln.amount for ln in lines if ln.state in COUNTED and ln.amount is not None)
    vat = won(Decimal(subtotal) * p.vat_rate)

    md = wall * p.md_wall + ceil_used * p.md_ceiling
    if inp.occupied:
        md = md / p.occupied_output
    man_days = half_up(md)
    work = max(int((man_days / p.crew * 2).to_integral_value(rounding=ROUND_CEILING)), 1)
    steps = [Step("prep", "짐 정리 · 보양", 1)] if inp.occupied else []
    steps.append(
        Step(
            "paper", "초배 · 정배 (벽 · 천장)" if inp.include_ceiling else "초배 · 정배 (벽)", work
        )
    )
    steps.append(Step("finish", "마감 · 확인 · 청소", 1))
    days = Decimal(sum(s.half_days for s in steps)) / 2

    assumptions = [
        f"도배 면적은 {BASIS_LABEL[inp.area_basis]} × {p.area_factor[inp.area_basis]}로 추정했어요. 실측 때 방마다 다시 재요.",
        f"천장은 도배 면적의 {int(p.ceiling_share * 100)}%로 잡았어요.",
        f"하루 도배공 {p.crew}명이 들어가는 것으로 기간을 잡았어요.",
    ]
    if inp.balcony_ext:
        assumptions.append(f"발코니 확장은 도배 면적을 {p.balcony_factor}배로 잡았어요.")
    return DobaeQuote(
        version=p.version,
        paper_m2=paper_area,
        wall_m2=wall,
        ceiling_m2=ceiling,
        lines=lines,
        subtotal=subtotal,
        vat=vat,
        total=subtotal + vat,
        man_days=man_days,
        steps=steps,
        days=days,
        assumptions=assumptions,
    )
