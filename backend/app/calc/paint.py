"""도장 표준견적서와 예상 공정표. 칠할 곳은 벽 · 천장 · 문(문틀 포함) · 베란다(탄성코트)다.

금액은 원 정수이고 반올림은 won() 한 곳에서만 한다. 면적 · 페인트 양은 소수 한 자리, 품은 0.5 단위로 올린다.
실측 전이라 칠 면적은 평형에서 가정값으로 추정하고, 그 가정은 결과의 assumptions에 그대로 남긴다.
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

Surface = Literal["wall", "ceiling", "door", "balcony"]
SURFACES: tuple[Surface, ...] = ("wall", "ceiling", "door", "balcony")
SURFACE_NAME = {"wall": "벽", "ceiling": "천장", "door": "문 · 문틀", "balcony": "베란다"}
Paint = Literal["standard", "eco"]
PAINTS: tuple[Paint, ...] = ("standard", "eco")
PAINT_NAME = {"standard": "일반 수성", "eco": "친환경 수성"}
Putty = Literal["spot", "joint", "full"]  # 부분 보수 · 이음매만(줄퍼티) · 전체(올퍼티)
PUTTIES: tuple[Putty, ...] = ("spot", "joint", "full")
PUTTY_NAME = {"spot": "부분 보수", "joint": "줄퍼티", "full": "올퍼티"}


@dataclass(frozen=True)
class PaintPrices:
    """계산에 쓰는 기준 단가와 가정값 한 벌. refprice가 버전별로 만들어 넘긴다."""

    version: str
    roll: dict[str, int]  # 부위(wall · ceiling)별 수성페인트 롤러칠 1회 원/㎡ (페인트 제외)
    brush: int  # 수성페인트 붓칠 1회 원/㎡ (문 · 문틀, 페인트 제외)
    wood_prep: int  # 목재면 바탕 만들기(퍼티 · 연마) 원/㎡
    putty: dict[str, dict[str, int]]  # 부위 → 퍼티 범위(joint · full) → 원/㎡
    removal: int  # 기존 벽지 떼내기 원/㎡ (노무비만)
    paint_l: dict[str, int]  # 페인트 종류별 원/L
    paint_ratio: Decimal  # 페인트 소요량 L/㎡ (한 번 칠할 때, 가정값)
    coats: int  # 벽 · 천장 · 문 칠 횟수 (가정값)
    elastic_coats: int  # 베란다 탄성코트 칠 횟수 (하도 + 상도, 가정값)
    elastic_mat: int  # 탄성코트 자재 원/㎡
    md_roll: dict[str, Decimal]  # 도장공 품 인/㎡ (한 번 칠할 때)
    md_brush: Decimal
    md_wood_prep: Decimal
    md_putty: dict[str, dict[str, Decimal]]
    area_factor: dict[str, Decimal]  # 면적 기준별 벽 · 천장 칠 면적 환산 (가정값, 도배와 같다)
    ceiling_share: Decimal  # 칠 면적 중 천장 비율 (가정값)
    balcony_factor: Decimal  # 발코니 확장 가산 (가정값)
    door_m2: Decimal  # 문 하나(문짝 양면 + 문틀 · 문선) 칠 면적 (가정값)
    balcony_per_py: Decimal  # 공급 1평당 베란다 벽 · 천장 칠 면적 ㎡ (가정값)
    supply_per_exclusive: Decimal  # 전용 → 공급 환산 (가정값)
    mask_half_days: int  # 보양(마스킹) 반나절 수
    spot_half_days: int  # 부분 퍼티 반나절 수 (가정값)
    crew: int  # 하루 들어가는 도장공 수 (가정값)
    vat_rate: Decimal
    sources: dict[str, str]  # 출처 키 → 출처 문구
    assumed: frozenset[str]  # 단가가 팀 가정값인 출처 키


@dataclass(frozen=True)
class PaintInput:
    area_m2: Decimal
    area_basis: AreaBasis
    surfaces: tuple[Surface, ...]
    occupied: bool
    paint: Paint = "standard"
    putty: Putty = "full"
    doors: int = 0
    balcony_ext: bool = False


@dataclass(frozen=True)
class PaintQuote:
    version: str
    wall_m2: Decimal  # 고른 부위만 (안 고르면 0)
    ceiling_m2: Decimal
    door_m2: Decimal
    balcony_m2: Decimal
    paint_l: Decimal  # 수성페인트 양 (탄성코트 제외)
    lines: list[Line]
    subtotal: int
    vat: int
    total: int
    man_days: Decimal  # 도장공 품
    steps: list[Step]
    days: Decimal
    assumptions: list[str]


def quote(inp: PaintInput, p: PaintPrices) -> PaintQuote:
    if inp.area_m2 <= 0:
        raise ValueError("면적은 0보다 커야 해요")
    if inp.area_basis not in BASIS_LABEL:
        raise ValueError("면적 기준은 공급면적이나 전용면적이어야 해요")
    chosen = set(inp.surfaces)
    if not chosen or not chosen <= set(SURFACES):
        raise ValueError("칠할 곳을 하나 이상 골라야 해요")
    if inp.paint not in PAINTS:
        raise ValueError("페인트 종류를 골라야 해요")
    if inp.putty not in PUTTIES:
        raise ValueError("퍼티 범위를 골라야 해요")
    if "door" in chosen and inp.doors < 1:
        raise ValueError("문 개수를 넣어야 해요")
    src = p.sources

    def basis(key: str) -> Basis:
        return "assumed" if key in p.assumed else "public"

    # 벽 · 천장은 도배와 같은 방식으로 추정한다. 둘을 따로 반올림해서 면적이 커지면 줄지 않게 한다
    gross = inp.area_m2 * p.area_factor[inp.area_basis]
    if inp.balcony_ext:
        gross *= p.balcony_factor
    zero = Decimal(0)
    wall = m2(gross * (1 - p.ceiling_share)) if "wall" in chosen else zero
    ceiling = m2(gross * p.ceiling_share) if "ceiling" in chosen else zero
    door = m2(inp.doors * p.door_m2) if "door" in chosen else zero
    if inp.area_basis == "supply":
        supply = inp.area_m2
    else:
        supply = m2(inp.area_m2 * p.supply_per_exclusive)
    balcony = m2(supply / PYEONG_M2 * p.balcony_per_py) if "balcony" in chosen else zero
    flat = [s for s in ("wall", "ceiling") if s in chosen]  # 퍼티 · 롤러칠 하는 곳
    flat_m2 = {"wall": wall, "ceiling": ceiling}
    painted = [s for s in ("wall", "ceiling", "door") if s in chosen]  # 수성페인트로 칠하는 곳

    lines: list[Line] = []
    md_putty = md_paint = md_balcony = zero
    for s in flat:
        unit = p.roll[s] * p.coats
        lines.append(
            Line(
                s,
                f"{SURFACE_NAME[s]} 칠 (롤러 {p.coats}회, 페인트 제외)",
                flat_m2[s],
                "㎡",
                unit,
                won(flat_m2[s] * unit),
                "included",
                src[f"roll_{s}"],
                basis(f"roll_{s}"),
            )
        )
        md_paint += flat_m2[s] * p.md_roll[s] * p.coats
    if flat and inp.putty == "spot":
        lines.append(
            Line(
                "putty",
                f"{' · '.join(SURFACE_NAME[s] for s in flat)} 부분 퍼티 (보수할 곳만)",
                None,
                "식",
                None,
                None,
                "after_visit",
                src["none"],
                "none",
            )
        )
    elif flat:
        for s in flat:
            unit = p.putty[s][inp.putty]
            key = f"putty_{s}_{inp.putty}"
            lines.append(
                Line(
                    f"putty_{s}",
                    f"{SURFACE_NAME[s]} 퍼티 · 샌딩 ({PUTTY_NAME[inp.putty]})",
                    flat_m2[s],
                    "㎡",
                    unit,
                    won(flat_m2[s] * unit),
                    "included",
                    src[key],
                    basis(key),
                )
            )
            md_putty += flat_m2[s] * p.md_putty[s][inp.putty]
    if "door" in chosen:
        unit = p.brush * p.coats
        lines += [
            Line(
                "door",
                f"문 · 문틀 칠 (붓 {p.coats}회, 페인트 제외)",
                door,
                "㎡",
                unit,
                won(door * unit),
                "included",
                src["brush"],
                basis("brush"),
            ),
            Line(
                "door_prep",
                "문 · 문틀 바탕 연마 (퍼티 포함)",
                door,
                "㎡",
                p.wood_prep,
                won(door * p.wood_prep),
                "included",
                src["wood_prep"],
                basis("wood_prep"),
            ),
        ]
        md_paint += door * (p.md_brush * p.coats + p.md_wood_prep)
    paint_l = m2((wall + ceiling + door) * p.paint_ratio * p.coats)
    if painted:
        key = f"paint_{inp.paint}"
        lines.append(
            Line(
                "paint_mat",
                f"수성페인트 ({PAINT_NAME[inp.paint]})",
                paint_l,
                "L",
                p.paint_l[inp.paint],
                won(paint_l * p.paint_l[inp.paint]),
                "included",
                src[key],
                basis(key),
            )
        )
    if "balcony" in chosen:
        unit = p.roll["wall"] * p.elastic_coats
        lines += [
            Line(
                "balcony",
                f"베란다 탄성코트 칠 ({p.elastic_coats}회, 자재 제외)",
                balcony,
                "㎡",
                unit,
                won(balcony * unit),
                "included",
                src["elastic"],
                basis("elastic"),
            ),
            Line(
                "balcony_mat",
                "탄성코트 자재",
                balcony,
                "㎡",
                p.elastic_mat,
                won(balcony * p.elastic_mat),
                "included",
                src["elastic_mat"],
                basis("elastic_mat"),
            ),
            Line(
                "balcony_prep",
                "베란다 곰팡이 제거 · 바탕 보수",
                None,
                "식",
                None,
                None,
                "after_visit",
                src["none"],
                "none",
            ),
        ]
        md_balcony = balcony * p.md_roll["wall"] * p.elastic_coats
    if flat:
        lines.append(
            Line(
                "removal",
                "기존 벽지 제거 (벽지가 있으면)",
                wall + ceiling,
                "㎡",
                p.removal,
                won((wall + ceiling) * p.removal),
                "after_visit",
                src["removal"],
                basis("removal"),
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
    steps.append(Step("mask", "보양 (마스킹)", p.mask_half_days))
    if flat and inp.putty == "spot":
        steps.append(Step("putty", "부분 퍼티 · 샌딩", p.spot_half_days))
    elif flat:
        steps.append(Step("putty", "바탕 정리 · 퍼티 · 샌딩", half_days(md_putty, p.crew)))
    if painted:
        names = " · ".join(SURFACE_NAME[s] for s in painted)
        steps.append(Step("paint", f"칠하기 ({names})", half_days(md_paint, p.crew)))
    if "balcony" in chosen:
        steps.append(Step("balcony", "베란다 탄성코트", half_days(md_balcony, p.crew)))
    steps.append(Step("finish", "보양 제거 · 마감 확인 · 청소", 1))
    days = Decimal(sum(s.half_days for s in steps)) / 2

    assumptions = []
    if flat:
        assumptions.append(
            f"벽 · 천장 면적은 {BASIS_LABEL[inp.area_basis]} × {p.area_factor[inp.area_basis]}로"
            f" 추정하고 천장을 그중 {int(p.ceiling_share * 100)}%로 잡았어요."
            " 실측 때 방마다 다시 재요."
        )
        if inp.balcony_ext:
            assumptions.append(f"발코니 확장은 벽 · 천장 면적을 {p.balcony_factor}배로 잡았어요.")
        if inp.putty == "spot":
            assumptions.append("부분 퍼티는 보수할 곳을 실측 때 보고 정해요.")
        else:
            assumptions.append(
                "퍼티 · 칠 기간은 공공 품셈 기준이라 업체 일정보다 길게 나올 수 있어요."
            )
    if "door" in chosen:
        assumptions.append(f"문 하나(문짝 양면 · 문틀)를 {p.door_m2}㎡로 잡았어요.")
    if painted:
        assumptions.append(
            f"{p.coats}번 칠하고, 한 번 칠할 때 1㎡에 페인트 {p.paint_ratio}L가 드는 것으로"
            " 잡았어요. 짙은 색을 덮으면 더 칠할 수 있어요."
        )
    if painted and f"paint_{inp.paint}" in p.assumed:
        assumptions.append(f"{PAINT_NAME[inp.paint]} 페인트값은 공공 가격이 없어 팀 가정값이에요.")
    if "balcony" in chosen:
        if inp.area_basis == "exclusive":
            assumptions.append(f"공급면적은 전용면적 × {p.supply_per_exclusive}로 환산했어요.")
        assumptions.append(
            f"베란다 칠 면적은 공급 1평에 {p.balcony_per_py}㎡로 잡고 탄성코트를"
            f" {p.elastic_coats}번 칠하는 것으로 잡았어요."
        )
        if "elastic_mat" in p.assumed:
            assumptions.append("탄성코트 자재값은 공공 가격이 없어 팀 가정값이에요.")
    assumptions.append(f"하루 도장공 {p.crew}명이 들어가는 것으로 기간을 잡았어요.")

    return PaintQuote(
        version=p.version,
        wall_m2=wall,
        ceiling_m2=ceiling,
        door_m2=door,
        balcony_m2=balcony,
        paint_l=paint_l,
        lines=lines,
        subtotal=subtotal,
        vat=vat,
        total=subtotal + vat,
        man_days=half_up(md_putty + md_paint + md_balcony),
        steps=steps,
        days=days,
        assumptions=assumptions,
    )
