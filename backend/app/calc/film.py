"""인테리어 필름 표준견적서와 예상 공정표. 항목은 방문 문짝 · 방문 문틀 · 현관문 · 천장 몰딩 · 붙박이장 문 · 주방 문짝이다.

금액은 원 정수이고 반올림은 won() 한 곳에서만 한다. 넓이는 ㎡ 소수 한 자리, 품은 0.5 단위로 올린다.
실측 전이라 붙이는 넓이는 개수 · 평형에서 가정값으로 추정하고, 그 가정은 결과의 assumptions에 그대로 남긴다.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from app.calc.common import (
    BASIS_LABEL,
    COUNTED,
    PYEONG_M2,
    AreaBasis,
    Basis,
    Line,
    Step,
    half_days,
    half_up,
    m2,
    won,
)

Item = Literal["door", "frame", "entrance", "molding", "closet", "kitchen"]
ITEMS: tuple[Item, ...] = ("door", "frame", "entrance", "molding", "closet", "kitchen")
ITEM_NAME = {
    "door": "방문 문짝",
    "frame": "방문 문틀",
    "entrance": "현관문",
    "molding": "천장 몰딩",
    "closet": "붙박이장 문",
    "kitchen": "주방 문짝",
}
Grade = Literal["basic", "premium"]
GRADES: tuple[Grade, ...] = ("basic", "premium")
GRADE_NAME = {"basic": "일반", "premium": "고급"}


@dataclass(frozen=True)
class FilmPrices:
    """계산에 쓰는 기준 단가와 가정값 한 벌. refprice가 버전별로 만들어 넘긴다."""

    version: str
    wide: int  # 인테리어필름 붙임, 폭 300mm 이상 원/㎡ (필름 제외)
    narrow: int  # 인테리어필름 붙임, 폭 300mm 미만 · 몰딩 · 틀 원/㎡ (필름 제외)
    md_wide: Decimal  # 필름 붙이는 사람 품 인/㎡
    md_narrow: Decimal
    film: dict[str, int]  # 등급별 필름 원/㎡ (프라이머 포함)
    film_ratio: Decimal  # 필름 소요량 ㎡/㎡ (재단 여유 포함, 가정값)
    leaf_m2: Decimal  # 방문 문짝 한 짝 양면 ㎡ (가정값)
    frame_m2: Decimal  # 방문 문틀 · 문선 한 틀 펼친 넓이 ㎡ (가정값)
    entrance_leaf_m2: Decimal  # 현관문 안쪽 면 ㎡ (가정값)
    entrance_frame_m2: Decimal  # 현관 문틀 펼친 넓이 ㎡ (가정값)
    molding_per_py: Decimal  # 공급 1평당 천장 몰딩 길이 m (가정값, 목공과 같다)
    molding_width: Decimal  # 몰딩 펼친 폭 m (가정값)
    closet_per_py: Decimal  # 공급 1평당 붙박이장 문 넓이 ㎡ (가정값)
    kitchen_per_py: Decimal  # 공급 1평당 주방 문짝 넓이 ㎡ (가정값)
    supply_per_exclusive: Decimal  # 전용 → 공급 환산 (가정값)
    crew: int  # 하루 들어가는 사람 수 (가정값)
    vat_rate: Decimal
    sources: dict[str, str]  # 출처 키 → 출처 문구
    assumed: frozenset[str]  # 단가가 팀 가정값인 출처 키


@dataclass(frozen=True)
class FilmInput:
    area_m2: Decimal
    area_basis: AreaBasis
    items: tuple[Item, ...]
    occupied: bool
    grade: Grade = "basic"
    doors: int = 0  # 방문 수 (문짝 · 문틀에 쓴다)


@dataclass(frozen=True)
class FilmQuote:
    version: str
    item_m2: dict[str, Decimal]  # 고른 항목별 붙이는 넓이 (현관문은 문 + 틀)
    film_m2: Decimal  # 필름 자재 넓이 (여유 포함)
    lines: list[Line]
    subtotal: int
    vat: int
    total: int
    man_days: Decimal
    steps: list[Step]
    days: Decimal
    assumptions: list[str]


def quote(inp: FilmInput, p: FilmPrices) -> FilmQuote:
    if inp.area_m2 <= 0:
        raise ValueError("면적은 0보다 커야 해요")
    if inp.area_basis not in BASIS_LABEL:
        raise ValueError("면적 기준은 공급면적이나 전용면적이어야 해요")
    items = set(inp.items)
    if not items or not items <= set(ITEMS):
        raise ValueError("필름 붙일 곳을 하나 이상 골라야 해요")
    if inp.grade not in GRADES:
        raise ValueError("필름 등급을 골라야 해요")
    if items & {"door", "frame"} and inp.doors < 1:
        raise ValueError("방문 개수를 넣어야 해요")
    src = p.sources

    def basis(key: str) -> Basis:
        return "assumed" if key in p.assumed else "public"

    if inp.area_basis == "supply":
        supply = inp.area_m2
    else:
        supply = m2(inp.area_m2 * p.supply_per_exclusive)
    py = supply / PYEONG_M2

    # (줄 키, 항목, 이름, 넓이, 넓은 면인지)
    parts: list[tuple[str, str, str, Decimal, bool]] = []
    if "door" in items:
        parts.append(("door", "door", "방문 문짝 필름 (양면)", m2(inp.doors * p.leaf_m2), True))
    if "frame" in items:
        parts.append(("frame", "frame", "방문 문틀 · 문선 필름", m2(inp.doors * p.frame_m2), False))
    if "entrance" in items:
        parts.append(("entrance", "entrance", "현관문 안쪽 필름", p.entrance_leaf_m2, True))
        parts.append(("entrance_frame", "entrance", "현관 문틀 필름", p.entrance_frame_m2, False))
    if "molding" in items:
        molding = m2(py * p.molding_per_py * p.molding_width)
        parts.append(("molding", "molding", "천장 몰딩 필름", molding, False))
    if "closet" in items:
        parts.append(("closet", "closet", "붙박이장 문 필름", m2(py * p.closet_per_py), True))
    if "kitchen" in items:
        parts.append(("kitchen", "kitchen", "주방 문짝 필름", m2(py * p.kitchen_per_py), True))

    lines: list[Line] = []
    item_m2: dict[str, Decimal] = {}
    md = Decimal(0)
    for key, item, name, qty, wide in parts:
        unit, src_key = (p.wide, "wide") if wide else (p.narrow, "narrow")
        lines.append(
            Line(
                key,
                f"{name} (필름 제외)",
                qty,
                "㎡",
                unit,
                won(qty * unit),
                "included",
                src[src_key],
                basis(src_key),
            )
        )
        item_m2[item] = item_m2.get(item, Decimal(0)) + qty
        md += qty * (p.md_wide if wide else p.md_narrow)
    film_m2 = m2(sum(item_m2.values(), Decimal(0)) * p.film_ratio)
    film_key = f"film_{inp.grade}"
    lines += [
        Line(
            "film",
            f"인테리어 필름 ({GRADE_NAME[inp.grade]}) · 프라이머",
            film_m2,
            "㎡",
            p.film[inp.grade],
            won(film_m2 * p.film[inp.grade]),
            "included",
            src[film_key],
            basis(film_key),
        ),
        Line(
            "repair",
            "바탕 보수 · 기존 시트 제거",
            None,
            "식",
            None,
            None,
            "after_visit",
            src["none"],
            "none",
        ),
    ]
    if inp.occupied:
        lines.append(
            Line(
                "moving",
                "짐 이동 · 보양",
                None,
                "식",
                None,
                None,
                "after_visit",
                src["none"],
                "none",
            )
        )

    subtotal = sum(ln.amount for ln in lines if ln.state in COUNTED and ln.amount is not None)
    vat = won(Decimal(subtotal) * p.vat_rate)

    steps = [Step("prep", "짐 정리 · 보양", 1)] if inp.occupied else []
    steps.append(Step("film", "바탕 정리 · 프라이머 · 필름 붙이기", half_days(md, p.crew)))
    steps.append(Step("finish", "마감 확인 · 청소", 1))
    days = Decimal(sum(s.half_days for s in steps)) / 2

    assumptions = []
    if items & {"door", "frame"}:
        assumptions.append(
            f"방문 하나는 문짝 양면 {p.leaf_m2}㎡ · 문틀과 문선 {p.frame_m2}㎡로 잡았어요."
        )
    if "entrance" in items:
        assumptions.append(
            f"현관문은 안쪽 면 {p.entrance_leaf_m2}㎡ · 문틀 {p.entrance_frame_m2}㎡로 잡았어요."
        )
    if items & {"molding", "closet", "kitchen"}:
        if inp.area_basis == "exclusive":
            assumptions.append(f"공급면적은 전용면적 × {p.supply_per_exclusive}로 환산했어요.")
        per = []
        if "molding" in items:
            per.append(f"몰딩 {p.molding_per_py}m(펼친 폭 {p.molding_width}m)")
        if "closet" in items:
            per.append(f"붙박이장 문 {p.closet_per_py}㎡")
        if "kitchen" in items:
            per.append(f"주방 문짝 {p.kitchen_per_py}㎡")
        assumptions.append(f"공급 1평에 {' · '.join(per)}로 잡았어요. 실측 때 다시 재요.")
    assumptions.append(f"필름은 재단 여유를 넣어 붙이는 넓이의 {p.film_ratio}배로 잡았어요.")
    if film_key in p.assumed:
        assumptions.append("필름 자재값은 공공 가격이 없어 팀 가정값이에요.")
    assumptions.append(
        f"필름 직종은 공공 노임이 없어 내장공 기준으로 품을 잡고, 하루 {p.crew}명이"
        " 들어가는 것으로 기간을 잡았어요."
    )

    return FilmQuote(
        version=p.version,
        item_m2=item_m2,
        film_m2=film_m2,
        lines=lines,
        subtotal=subtotal,
        vat=vat,
        total=subtotal + vat,
        man_days=half_up(md),
        steps=steps,
        days=days,
        assumptions=assumptions,
    )
