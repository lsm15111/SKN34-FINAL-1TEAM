"""바닥재 표준견적서와 예상 공정표. 종류는 장판(얇은 · 두꺼운) · 강마루 · 강화마루 · 포세린 타일이다.

금액은 원 정수이고 반올림은 won() 한 곳에서만 한다. 면적은 ㎡ 소수 한 자리, 품은 0.5 단위로 올린다.
실측 전이라 바닥 면적은 평형에서 가정값으로 추정하고, 그 가정은 결과의 assumptions에 그대로 남긴다.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from app.calc.common import (
    BASIS_LABEL,
    COUNTED,
    AreaBasis,
    Basis,
    Line,
    Step,
    half_days,
    half_up,
    m2,
    won,
)

Kind = Literal["vinyl_18", "vinyl_22", "engineered", "laminate", "porcelain"]
KINDS: tuple[Kind, ...] = ("vinyl_18", "vinyl_22", "engineered", "laminate", "porcelain")
KIND_NAME = {
    "vinyl_18": "장판 1.8T",
    "vinyl_22": "장판 2.2T",
    "engineered": "강마루",
    "laminate": "강화마루",
    "porcelain": "포세린 타일",
}
# 시공 방식 묶음. 시공 단가 · 품 · 자재 소요량은 묶음마다 같다
Group = Literal["vinyl", "wood", "tile"]
GROUP: dict[str, Group] = {
    "vinyl_18": "vinyl",
    "vinyl_22": "vinyl",
    "engineered": "wood",
    "laminate": "wood",
    "porcelain": "tile",
}
LAY_STEP = {"vinyl": "장판 깔기", "wood": "마루 깔기", "tile": "타일 붙이기 · 줄눈"}


@dataclass(frozen=True)
class FloorPrices:
    """계산에 쓰는 기준 단가와 가정값 한 벌. refprice가 버전별로 만들어 넘긴다."""

    version: str
    lay: dict[str, int]  # 묶음별 시공 원/㎡ (주자재 제외)
    mat: dict[str, int]  # 종류별 자재 원/㎡
    mat_ratio: dict[str, Decimal]  # 묶음별 자재 소요량 ㎡/㎡ (재단 여유 포함, 가정값)
    tile_sub: int  # 타일 붙임재 · 줄눈재 원/㎡
    level: int  # 바닥 평탄화(셀프레벨링) 원/㎡ (자재 제외)
    md: dict[str, Decimal]  # 묶음별 기능공 품 인/㎡
    supply_per_exclusive: Decimal  # 전용 → 공급 환산 (가정값)
    floor_share: Decimal  # 바닥재 면적 = 전용면적 × 이 비율 (가정값)
    balcony_factor: Decimal  # 발코니 확장 가산 (가정값)
    remove_half_days: int  # 기존 바닥 철거 · 바탕 정리 반나절 수 (가정값)
    cure_half_days: int  # 타일 양생 반나절 수
    crew: int  # 하루 들어가는 기능공 수 (가정값)
    vat_rate: Decimal
    sources: dict[str, str]  # 출처 키 → 출처 문구
    assumed: frozenset[str]  # 단가가 팀 가정값인 출처 키


@dataclass(frozen=True)
class FloorInput:
    area_m2: Decimal
    area_basis: AreaBasis
    kind: Kind
    occupied: bool
    remove: bool = True  # 기존 바닥재를 걷어 내는지
    balcony_ext: bool = False


@dataclass(frozen=True)
class FloorQuote:
    version: str
    floor_m2: Decimal  # 바닥재를 까는 면적
    lines: list[Line]
    subtotal: int
    vat: int
    total: int
    man_days: Decimal  # 기능공 품
    steps: list[Step]
    days: Decimal
    assumptions: list[str]


def _day_text(half: int) -> str:
    return {1: "반나절", 2: "하루"}.get(half, f"{Decimal(half) / 2}일")


def quote(inp: FloorInput, p: FloorPrices) -> FloorQuote:
    if inp.area_m2 <= 0:
        raise ValueError("면적은 0보다 커야 해요")
    if inp.area_basis not in BASIS_LABEL:
        raise ValueError("면적 기준은 공급면적이나 전용면적이어야 해요")
    if inp.kind not in KINDS:
        raise ValueError("바닥재 종류를 골라야 해요")
    src = p.sources

    def basis(key: str) -> Basis:
        return "assumed" if key in p.assumed else "public"

    if inp.area_basis == "supply":
        exclusive = m2(inp.area_m2 / p.supply_per_exclusive)
    else:
        exclusive = inp.area_m2
    gross = exclusive * p.floor_share
    if inp.balcony_ext:
        gross *= p.balcony_factor
    floor = m2(gross)
    g = GROUP[inp.kind]
    name = KIND_NAME[inp.kind]

    mat_qty = m2(floor * p.mat_ratio[g])
    mat_key = f"mat_{inp.kind}"
    lines = [
        Line(
            "lay",
            f"{name} 시공 (자재 제외)",
            floor,
            "㎡",
            p.lay[g],
            won(floor * p.lay[g]),
            "included",
            src[f"lay_{g}"],
            basis(f"lay_{g}"),
        ),
        Line(
            "mat",
            f"{name} 자재",
            mat_qty,
            "㎡",
            p.mat[inp.kind],
            won(mat_qty * p.mat[inp.kind]),
            "included",
            src[mat_key],
            basis(mat_key),
        ),
    ]
    if g == "tile":
        lines.append(
            Line(
                "sub",
                "붙임재 · 줄눈재",
                floor,
                "㎡",
                p.tile_sub,
                won(floor * p.tile_sub),
                "included",
                src["sub"],
                basis("sub"),
            )
        )
    if inp.remove:
        lines.append(
            Line(
                "remove",
                "기존 바닥재 철거",
                None,
                "식",
                None,
                None,
                "after_visit",
                src["none"],
                "none",
            )
        )
        if g != "vinyl":
            lines.append(
                Line(
                    "level",
                    "바닥 평탄화 (셀프레벨링, 자재 제외)",
                    floor,
                    "㎡",
                    p.level,
                    won(floor * p.level),
                    "after_visit",
                    src["level"],
                    basis("level"),
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

    md = floor * p.md[g]
    steps = [Step("prep", "짐 정리 · 보양", 1)] if inp.occupied else []
    if inp.remove:
        steps.append(Step("remove", "기존 바닥 철거 · 바탕 정리", p.remove_half_days))
    steps.append(Step("lay", LAY_STEP[g], half_days(md, p.crew)))
    if g == "tile":
        steps.append(Step("cure", "양생 (밟지 않기)", p.cure_half_days))
    steps.append(Step("finish", "마감 확인 · 청소", 1))
    days = Decimal(sum(s.half_days for s in steps)) / 2

    assumptions = []
    if inp.area_basis == "supply":
        assumptions.append(f"전용면적은 공급면적 ÷ {p.supply_per_exclusive}로 환산했어요.")
    assumptions.append(
        f"바닥재 면적은 전용면적의 {int(p.floor_share * 100)}%(욕실 · 현관 · 붙박이장 자리 빼고)로"
        " 잡았어요. 실측 때 방마다 다시 재요."
    )
    if inp.balcony_ext:
        assumptions.append(f"발코니 확장 부분까지 바닥재 면적을 {p.balcony_factor}배로 잡았어요.")
    assumptions.append(f"자재는 재단 여유를 넣어 바닥재 면적의 {p.mat_ratio[g]}배로 잡았어요.")
    if mat_key in p.assumed:
        assumptions.append(f"{name} 자재값은 공공 가격이 없어 팀 가정값이에요.")
    if g == "tile":
        assumptions.append(
            "포세린 시공 단가는 600×600 크기 기준이에요. 더 큰 타일은 실측 때 다시 봐요."
        )
        assumptions.append(
            f"타일을 붙인 뒤 {_day_text(p.cure_half_days)} 동안 밟지 않는 것으로 잡았어요."
        )
    if inp.remove:
        assumptions.append(
            f"기존 바닥 철거는 {_day_text(p.remove_half_days)}로 잡았어요."
            " 철거비는 지금 바닥재를 보고 정해요."
        )
    else:
        assumptions.append("기존 바닥 위에 바로 깔 수 있는지는 실측 때 확인해요.")
    assumptions.append(f"하루 기능공 {p.crew}명이 들어가는 것으로 기간을 잡았어요.")

    return FloorQuote(
        version=p.version,
        floor_m2=floor,
        lines=lines,
        subtotal=subtotal,
        vat=vat,
        total=subtotal + vat,
        man_days=half_up(md),
        steps=steps,
        days=days,
        assumptions=assumptions,
    )
