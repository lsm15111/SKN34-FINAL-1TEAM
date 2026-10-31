"""타일 표준견적서와 예상 공정표. 부위는 주방 벽 · 현관 바닥 · 베란다 바닥이다 (욕실은 따로 본다).

금액은 원 정수이고 반올림은 won() 한 곳에서만 한다. 면적은 ㎡ 소수 한 자리, 품은 0.5 단위로 올린다.
실측 전이라 부위별 면적은 평형에서 가정값으로 추정하고, 그 가정은 결과의 assumptions에 그대로 남긴다.
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

Part = Literal["kitchen", "entrance", "balcony"]
PARTS: tuple[Part, ...] = ("kitchen", "entrance", "balcony")
PART_NAME = {"kitchen": "주방 벽", "entrance": "현관 바닥", "balcony": "베란다 바닥"}
FLOOR_PARTS = ("entrance", "balcony")
Size = Literal["small", "medium", "large"]
SIZES: tuple[Size, ...] = ("small", "medium", "large")
SIZE_NAME = {"small": "작은 타일", "medium": "중간 타일", "large": "큰 타일"}
SIZE_SPEC = {"small": "300×300 이하", "medium": "300×600 안팎", "large": "600×600 안팎"}
Method = Literal["remove", "overlay"]  # 철거 후 새로 붙이기 · 기존 타일 위에 덧방
METHODS: tuple[Method, ...] = ("remove", "overlay")


@dataclass(frozen=True)
class TilePrices:
    """계산에 쓰는 기준 단가와 가정값 한 벌. refprice가 버전별로 만들어 넘긴다."""

    version: str
    wall_press: dict[str, int]  # 크기별 벽 압착붙이기 원/㎡ (타일 제외)
    wall_glue: dict[str, int]  # 크기별 벽 접착붙이기(덧방) 원/㎡ (타일 제외)
    floor: dict[str, int]  # 크기별 바닥 압착붙이기 원/㎡ (타일 제외)
    md_wall_press: dict[str, Decimal]  # 타일공 품 인/㎡
    md_wall_glue: dict[str, Decimal]
    md_floor: dict[str, Decimal]
    base_wall: int  # 타일 바탕 고르기 벽 원/㎡
    base_floor: int  # 타일 바탕 고르기 바닥 원/㎡
    mat_wall: dict[str, int]  # 크기별 벽 타일 원/㎡
    mat_floor: dict[str, int]  # 크기별 바닥 타일 원/㎡
    mat_ratio: Decimal  # 타일 소요량 ㎡/㎡ (깨짐 · 재단 여유 포함, 가정값)
    sub: int  # 붙임재 · 줄눈재 원/㎡
    per_py: dict[str, Decimal]  # 부위별 공급 1평당 타일 면적 ㎡ (가정값)
    supply_per_exclusive: Decimal  # 전용 → 공급 환산 (가정값)
    remove_half_days: int  # 기존 타일 철거 · 바탕 고르기 반나절 수 (가정값)
    cure_half_days: int  # 바닥 타일 양생 반나절 수
    crew: int  # 하루 들어가는 타일공 수 (가정값)
    vat_rate: Decimal
    sources: dict[str, str]  # 출처 키 → 출처 문구
    assumed: frozenset[str]  # 단가가 팀 가정값인 출처 키


@dataclass(frozen=True)
class TileInput:
    area_m2: Decimal
    area_basis: AreaBasis
    parts: tuple[Part, ...]
    size: Size
    method: Method
    occupied: bool


@dataclass(frozen=True)
class TileQuote:
    version: str
    part_m2: dict[str, Decimal]  # 고른 부위별 타일 면적
    wall_m2: Decimal
    floor_m2: Decimal
    lines: list[Line]
    subtotal: int
    vat: int
    total: int
    man_days: Decimal  # 타일공 품
    steps: list[Step]
    days: Decimal
    assumptions: list[str]


def _day_text(half: int) -> str:
    return {1: "반나절", 2: "하루"}.get(half, f"{Decimal(half) / 2}일")


def quote(inp: TileInput, p: TilePrices) -> TileQuote:
    if inp.area_m2 <= 0:
        raise ValueError("면적은 0보다 커야 해요")
    if inp.area_basis not in BASIS_LABEL:
        raise ValueError("면적 기준은 공급면적이나 전용면적이어야 해요")
    chosen = set(inp.parts)
    if not chosen or not chosen <= set(PARTS):
        raise ValueError("타일 부위를 하나 이상 골라야 해요")
    if inp.size not in SIZES:
        raise ValueError("타일 크기를 골라야 해요")
    if inp.method not in METHODS:
        raise ValueError("철거할지 덧방할지 골라야 해요")
    src = p.sources

    def basis(key: str) -> Basis:
        return "assumed" if key in p.assumed else "public"

    if inp.area_basis == "supply":
        supply = inp.area_m2
    else:
        supply = m2(inp.area_m2 * p.supply_per_exclusive)
    py = supply / PYEONG_M2
    part = {a: m2(py * p.per_py[a]) for a in PARTS if a in chosen}
    wall = part.get("kitchen", Decimal(0))
    floor = sum((part[a] for a in FLOOR_PARTS if a in part), Decimal(0))
    has_wall = "kitchen" in part
    has_floor = any(a in part for a in FLOOR_PARTS)
    overlay = inp.method == "overlay"
    size = inp.size

    lines: list[Line] = []
    md = Decimal(0)
    if has_wall:
        key = "wall_glue" if overlay else "wall_press"
        price = (p.wall_glue if overlay else p.wall_press)[size]
        lines.append(
            Line(
                "kitchen",
                f"주방 벽 타일 붙이기 ({'덧방' if overlay else '압착'}, 타일 제외)",
                wall,
                "㎡",
                price,
                won(wall * price),
                "included",
                src[key],
                basis(key),
            )
        )
        md += wall * (p.md_wall_glue if overlay else p.md_wall_press)[size]
    for a in FLOOR_PARTS:
        if a in part:
            lines.append(
                Line(
                    a,
                    f"{PART_NAME[a]} 타일 붙이기 (타일 제외)",
                    part[a],
                    "㎡",
                    p.floor[size],
                    won(part[a] * p.floor[size]),
                    "included",
                    src["floor"],
                    basis("floor"),
                )
            )
            md += part[a] * p.md_floor[size]
    # (키, 이름, 고른 부위가 있는지, 면적, 크기별 타일 단가, 바탕 고르기 단가)
    sides = (
        ("wall", "벽", has_wall, wall, p.mat_wall, p.base_wall),
        ("floor", "바닥", has_floor, floor, p.mat_floor, p.base_floor),
    )
    for kind, label, has, qty, mat_price, _ in sides:
        if not has:
            continue
        mat_qty = m2(qty * p.mat_ratio)
        key = f"mat_{kind}_{size}"
        lines.append(
            Line(
                f"{kind}_mat",
                f"{label} 타일 ({SIZE_NAME[size]})",
                mat_qty,
                "㎡",
                mat_price[size],
                won(mat_qty * mat_price[size]),
                "included",
                src[key],
                basis(key),
            )
        )
    lines.append(
        Line(
            "sub",
            "붙임재 · 줄눈재",
            wall + floor,
            "㎡",
            p.sub,
            won((wall + floor) * p.sub),
            "included",
            src["sub"],
            basis("sub"),
        )
    )
    if not overlay:
        lines.append(
            Line(
                "remove",
                "기존 타일 철거",
                None,
                "식",
                None,
                None,
                "after_visit",
                src["none"],
                "none",
            )
        )
        for kind, label, has, qty, _, base_price in sides:
            if has:
                lines.append(
                    Line(
                        f"base_{kind}",
                        f"{label} 바탕 고르기",
                        qty,
                        "㎡",
                        base_price,
                        won(qty * base_price),
                        "after_visit",
                        src[f"base_{kind}"],
                        basis(f"base_{kind}"),
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
    if not overlay:
        steps.append(Step("remove", "기존 타일 철거 · 바탕 고르기", p.remove_half_days))
    steps.append(Step("tile", "타일 붙이기 · 줄눈", half_days(md, p.crew)))
    if has_floor:
        steps.append(Step("cure", "양생 (밟지 않기)", p.cure_half_days))
    steps.append(Step("finish", "실리콘 마감 · 청소", 1))
    days = Decimal(sum(s.half_days for s in steps)) / 2

    assumptions = []
    if inp.area_basis == "exclusive":
        assumptions.append(f"공급면적은 전용면적 × {p.supply_per_exclusive}로 환산했어요.")
    per = " · ".join(f"{PART_NAME[a]} {p.per_py[a]}㎡" for a in PARTS if a in part)
    assumptions.append(f"타일 면적은 공급 1평에 {per}로 잡았어요. 실측 때 다시 재요.")
    assumptions.append(f"{SIZE_NAME[size]}은 {SIZE_SPEC[size]} 크기 기준 단가예요.")
    assumptions.append(f"타일은 깨짐 · 재단 여유를 넣어 타일 면적의 {p.mat_ratio}배로 잡았어요.")
    if any(k in p.assumed for k in (f"mat_wall_{size}", f"mat_floor_{size}")):
        assumptions.append(f"{SIZE_NAME[size]} 자재값 일부는 공공 가격이 없어 팀 가정값이에요.")
    if overlay:
        assumptions.append("덧방은 기존 타일이 단단히 붙어 있어야 해서 실측 때 확인해요.")
    else:
        assumptions.append(
            f"기존 타일 철거 · 바탕 고르기는 {_day_text(p.remove_half_days)}로 잡았어요."
            " 철거비는 실측 뒤에 정해요."
        )
    if has_floor:
        assumptions.append(
            f"바닥 타일은 붙인 뒤 {_day_text(p.cure_half_days)} 동안 밟지 않는 것으로 잡았어요."
        )
    assumptions.append(f"하루 타일공 {p.crew}명이 들어가는 것으로 기간을 잡았어요.")

    return TileQuote(
        version=p.version,
        part_m2=part,
        wall_m2=wall,
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
