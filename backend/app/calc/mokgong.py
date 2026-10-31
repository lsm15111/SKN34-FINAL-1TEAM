"""목공 표준견적서와 예상 공정표. 항목은 천장 몰딩 · 걸레받이 · 방문 · 천장 평탄화 넷이다.

금액은 원 정수이고 반올림은 won() 한 곳에서만 한다. 길이 · 면적은 소수 한 자리, 품은 0.5 단위로 올린다.
실측 전이라 길이 · 면적은 평형에서 가정값으로 추정하고, 그 가정은 결과의 assumptions에 그대로 남긴다.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from app.calc.common import (
    COUNTED,
    PYEONG_M2,
    AreaBasis,
    Line,
    Step,
    half_days,
    half_up,
    m2,
    won,
)

Item = Literal["molding", "base", "door", "flatten"]
ITEMS: tuple[Item, ...] = ("molding", "base", "door", "flatten")


@dataclass(frozen=True)
class MokgongPrices:
    """계산에 쓰는 기준 단가와 가정값 한 벌. refprice가 버전별로 만들어 넘긴다."""

    version: str
    molding: int  # 천장 몰딩 설치 원/m (재료 제외)
    molding_mat: int  # 몰딩 자재 원/m
    molding_ratio: Decimal  # 몰딩 소요량 m/m (할증 포함)
    base: int  # 걸레받이 설치 원/m (재료 제외)
    base_mat: int  # 걸레받이 자재 원/m
    base_ratio: Decimal  # 걸레받이 소요량 m/m (할증 포함)
    door_install: int  # 방문 문틀 세우기 · 문짝 달기 원/개 (재료 제외)
    door_leaf_install: int  # 방문 문짝만 달기 원/개 (재료 제외)
    door_set_mat: int  # 방문 문틀 · 문짝 · 문선 자재 원/개 (경첩 · 손잡이 포함)
    door_leaf_mat: int  # 방문 문짝 자재 원/개 (경첩 · 손잡이 포함)
    casing: int  # 문선 설치 원/m (재료 제외)
    casing_per_door: Decimal  # 문 하나 문선 길이 m, 양면 (가정값)
    frame: int  # 경량천장틀 원/㎡ (재료 제외)
    board: int  # 천장 석고보드 1겹 원/㎡ (석고보드 제외)
    ceiling_mat: int  # 천장틀 · 석고보드 자재 원/㎡
    md_molding: Decimal  # 내장공 품 인/m
    md_base: Decimal  # 내장공 품 인/m
    md_door: Decimal  # 창호공 품 인/개
    md_casing: Decimal  # 창호공 품 인/m (문선)
    md_frame: Decimal  # 내장공 품 인/㎡
    md_board: Decimal  # 내장공 품 인/㎡
    molding_per_py: Decimal  # 공급 1평당 몰딩 길이 m (가정값)
    base_per_py: Decimal  # 공급 1평당 걸레받이 길이 m (가정값)
    supply_per_exclusive: Decimal  # 전용 → 공급 환산 (가정값)
    flatten_share: Decimal  # 평탄화 면적 = 전용면적 × 이 비율 (가정값)
    crew: int  # 하루 들어가는 목수 수 (가정값)
    vat_rate: Decimal
    sources: dict[str, str]  # 줄 키 → 출처 문구


@dataclass(frozen=True)
class MokgongInput:
    area_m2: Decimal
    area_basis: AreaBasis
    items: tuple[Item, ...]
    occupied: bool
    doors: int = 0
    door_frame: bool = True  # 문틀까지 바꾸는지 (아니면 문짝만)


@dataclass(frozen=True)
class MokgongQuote:
    version: str
    molding_m: Decimal
    base_m: Decimal
    flatten_m2: Decimal
    doors: int
    lines: list[Line]
    subtotal: int
    vat: int
    total: int
    man_days: Decimal  # 목수 품
    steps: list[Step]
    days: Decimal
    assumptions: list[str]


def quote(inp: MokgongInput, p: MokgongPrices) -> MokgongQuote:
    if inp.area_m2 <= 0:
        raise ValueError("면적은 0보다 커야 해요")
    items = set(inp.items)
    if not items or not items <= set(ITEMS):
        raise ValueError("목공 항목을 하나 이상 골라야 해요")
    if "door" in items and inp.doors < 1:
        raise ValueError("방문 개수를 넣어야 해요")
    src = p.sources
    if inp.area_basis == "supply":
        supply, exclusive = inp.area_m2, m2(inp.area_m2 / p.supply_per_exclusive)
    else:
        supply, exclusive = m2(inp.area_m2 * p.supply_per_exclusive), inp.area_m2
    py = supply / PYEONG_M2

    lines: list[Line] = []
    md_ceiling = md_door = md_trim = Decimal(0)
    flatten = molding = base = Decimal(0)
    doors = inp.doors if "door" in items else 0

    if "flatten" in items:
        flatten = m2(exclusive * p.flatten_share)
        md_ceiling = flatten * (p.md_frame + p.md_board)
        lines += [
            Line(
                "frame",
                "천장 평탄화 · 경량천장틀",
                flatten,
                "㎡",
                p.frame,
                won(flatten * p.frame),
                "included",
                src["frame"],
            ),
            Line(
                "board",
                "천장 평탄화 · 석고보드 1겹",
                flatten,
                "㎡",
                p.board,
                won(flatten * p.board),
                "included",
                src["board"],
            ),
            Line(
                "ceiling_mat",
                "천장틀 · 석고보드 자재",
                flatten,
                "㎡",
                p.ceiling_mat,
                won(flatten * p.ceiling_mat),
                "included",
                src["ceiling_mat"],
                "assumed",
            ),
        ]
    if doors:
        with_frame = inp.door_frame
        install = p.door_install if with_frame else p.door_leaf_install
        door_mat = p.door_set_mat if with_frame else p.door_leaf_mat
        md_door = doors * p.md_door
        lines.append(
            Line(
                "door",
                "방문 교체 (문틀 · 문짝)" if with_frame else "방문 교체 (문짝만)",
                Decimal(doors),
                "개",
                install,
                won(Decimal(doors * install)),
                "included",
                src["door_install" if with_frame else "door_leaf_install"],
                "public" if with_frame else "assumed",
            )
        )
        if with_frame:
            casing = m2(p.casing_per_door * doors)
            md_door += casing * p.md_casing
            lines.append(
                Line(
                    "casing",
                    "문선 설치 (문 둘레 양면)",
                    casing,
                    "m",
                    p.casing,
                    won(casing * p.casing),
                    "included",
                    src["casing"],
                )
            )
        lines.append(
            Line(
                "door_mat",
                "방문 자재 (ABS 문틀 · 문짝 · 문선)" if with_frame else "방문 자재 (ABS 문짝)",
                Decimal(doors),
                "개",
                door_mat,
                won(Decimal(doors * door_mat)),
                "included",
                src["door_set_mat" if with_frame else "door_leaf_mat"],
                "assumed",
            )
        )
    if "molding" in items:
        molding = m2(py * p.molding_per_py)
        mat = m2(molding * p.molding_ratio)
        md_trim += molding * p.md_molding
        lines += [
            Line(
                "molding",
                "천장 몰딩 설치",
                molding,
                "m",
                p.molding,
                won(molding * p.molding),
                "included",
                src["molding"],
            ),
            Line(
                "molding_mat",
                "몰딩 자재",
                mat,
                "m",
                p.molding_mat,
                won(mat * p.molding_mat),
                "included",
                src["molding_mat"],
                "assumed",
            ),
        ]
    if "base" in items:
        base = m2(py * p.base_per_py)
        mat = m2(base * p.base_ratio)
        md_trim += base * p.md_base
        lines += [
            Line(
                "base",
                "걸레받이 설치 (MDF)",
                base,
                "m",
                p.base,
                won(base * p.base),
                "included",
                src["base"],
            ),
            Line(
                "base_mat",
                "걸레받이 자재",
                mat,
                "m",
                p.base_mat,
                won(mat * p.base_mat),
                "included",
                src["base_mat"],
                "assumed",
            ),
        ]

    if "flatten" in items:
        lines.append(
            Line(
                "remove_ceiling",
                "기존 등박스 · 우물천장 철거",
                None,
                "식",
                None,
                None,
                "after_visit",
                src["none"],
                "none",
            )
        )
    if doors and inp.door_frame:
        lines.append(
            Line(
                "remove_door",
                "기존 방문 · 문틀 철거",
                None,
                "식",
                None,
                None,
                "after_visit",
                src["none"],
                "none",
            )
        )
    if molding or base:
        lines.append(
            Line(
                "remove_trim",
                "기존 몰딩 · 걸레받이 철거",
                None,
                "식",
                None,
                None,
                "after_visit",
                src["none"],
                "none",
            )
        )
    lines.append(
        Line("waste", "폐기물 처리", None, "식", None, None, "after_visit", src["none"], "none")
    )
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
    if flatten or molding or base:
        steps.append(Step("remove", "철거 · 바탕 정리", 1))
    if flatten:
        steps.append(Step("ceiling", "천장 평탄화 (틀 · 석고보드)", half_days(md_ceiling, p.crew)))
    if doors:
        steps.append(Step("door", "방문 교체", half_days(md_door, p.crew)))
    if molding or base:
        name = " · ".join(n for n, q in (("몰딩", molding), ("걸레받이", base)) if q)
        steps.append(Step("trim", name, half_days(md_trim, p.crew)))
    steps.append(Step("finish", "정리 · 청소", 1))
    days = Decimal(sum(s.half_days for s in steps)) / 2

    assumptions = []
    if inp.area_basis == "exclusive":
        assumptions.append(f"공급면적은 전용면적 × {p.supply_per_exclusive}로 환산했어요.")
    if molding:
        assumptions.append(
            f"몰딩 길이는 공급 1평에 {p.molding_per_py}m로 집 전체를 잡았어요. 실측 때 방마다 다시 재요."
        )
    if base:
        assumptions.append(
            f"걸레받이 길이는 공급 1평에 {p.base_per_py}m로 집 전체를 잡았어요. 실측 때 방마다 다시 재요."
        )
    if flatten:
        assumptions.append(
            f"평탄화 면적은 전용면적의 {int(p.flatten_share * 100)}%(거실 천장 정도)로 잡았어요."
        )
    if doors and inp.door_frame:
        assumptions.append(
            "방문 설치 · 문선은 표준시장단가(재료 제외)이고, 문 자재는 공공 가격이 없어 ABS 문 기준 "
            f"팀 가정값이에요. 문선은 문 하나에 양면 {p.casing_per_door}m로 잡았어요. "
            "기존 문 · 문틀 철거는 실측 후에 정해요."
        )
    elif doors:
        assumptions.append(
            "문짝만 다는 공공 단가가 없어 설치는 문 설치 공공 단가의 절반으로 잡았고, "
            "문짝 자재는 ABS 문 기준 팀 가정값이에요."
        )
    assumptions.append(f"하루 목수 {p.crew}명이 들어가는 것으로 기간을 잡았어요.")

    return MokgongQuote(
        version=p.version,
        molding_m=molding,
        base_m=base,
        flatten_m2=flatten,
        doors=doors,
        lines=lines,
        subtotal=subtotal,
        vat=vat,
        total=subtotal + vat,
        man_days=half_up(md_ceiling + md_door + md_trim),
        steps=steps,
        days=days,
        assumptions=assumptions,
    )
