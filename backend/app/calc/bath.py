"""욕실 표준견적서와 예상 공정표.

범위는 전체(방수 · 타일 · 천장재 · 도기 · 수전)와 도기 · 수전만 두 가지다. 전체는 기존 타일을 뜯고 새로
하거나(철거 후 새로) 기존 타일 위에 덧붙인다(덧방). 실측 전이라 욕실 크기는 흔한 아파트 욕실 크기로 잡고,
그 가정은 결과의 assumptions에 그대로 남긴다. 금액은 원 정수이고 반올림은 won() 한 곳에서만 한다.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from app.calc.common import COUNTED, AreaBasis, Line, Step, half_days, half_up, m2, won

Scope = Literal["full", "fixtures"]
TileMethod = Literal["remove", "overlay"]
Tub = Literal["keep", "remove", "new"]
Ceiling = Literal["smc", "pvc"]
SCOPES: tuple[Scope, ...] = ("full", "fixtures")
TILE_METHODS: tuple[TileMethod, ...] = ("remove", "overlay")
TUBS: tuple[Tub, ...] = ("keep", "remove", "new")
CEILINGS: tuple[Ceiling, ...] = ("smc", "pvc")
CEILING_NAME = {"smc": "SMC", "pvc": "PVC"}
MAX_BATHS = 3


@dataclass(frozen=True)
class BathPrices:
    """계산에 쓰는 기준 단가와 가정값 한 벌. refprice가 버전별로 만들어 넘긴다."""

    version: str
    wp_liquid: int  # 방수 1차 시멘트 액체방수 원/㎡
    wp_coat: int  # 방수 2차 우레탄 도막 원/㎡ (재료 포함)
    base_wall: int  # 벽 타일 바탕 고르기 원/㎡
    tile_wall: int  # 벽 타일 압착붙이기 원/㎡ (타일 제외)
    tile_wall_overlay: int  # 벽 타일 접착붙이기(덧방) 원/㎡ (타일 제외)
    tile_floor: int  # 바닥 타일 압착붙이기 원/㎡ (타일 제외)
    wall_tile_mat: int  # 벽 타일 자재 원/㎡
    floor_tile_mat: int  # 바닥 타일 자재 원/㎡
    tile_ratio: Decimal  # 타일 소요량 ㎡/㎡ (할증 포함)
    drain: int  # 바닥 배수구 원/개
    caulk: int  # 실리콘(수밀코킹) 원/m
    ceiling: dict[str, int]  # 천장재 종류별 원/㎡ (자재 · 설치)
    toilet_basin: int  # 양변기 + 세면기 원/세트 (자재 · 설치)
    faucets: int  # 세면 · 샤워 수전 원/세트 (자재 · 설치)
    accessories: int  # 수건걸이 · 휴지걸이 · 선반 · 거울 원/세트 (자재 · 설치)
    tub_new: int  # 새 욕조 원/개 (자재 · 설치)
    partition: int  # 샤워 파티션 원/개 (자재 · 설치)
    floor_m2: Decimal  # 욕실 한 칸 바닥 ㎡ (가정값)
    wall_m2: Decimal  # 욕실 한 칸 벽 타일 ㎡ (가정값)
    wp_up_m2: Decimal  # 욕실 한 칸 방수를 벽 아랫부분으로 올려 바르는 ㎡ (가정값)
    caulk_full_m: Decimal  # 전체 공사 실리콘 m/욕실 (가정값)
    caulk_fixture_m: Decimal  # 도기 · 수전만 실리콘 m/욕실 (가정값)
    md_tile_wall: Decimal  # 타일공 품 인/㎡ (벽 압착)
    md_tile_wall_overlay: Decimal  # 타일공 품 인/㎡ (벽 덧방)
    md_tile_floor: Decimal  # 타일공 품 인/㎡ (바닥)
    md_fit: Decimal  # 천장재 · 도기 · 수전 · 액세서리 설치 품 인/욕실 (가정값)
    md_fixture_only: Decimal  # 도기 · 수전만 바꿀 때 품 인/욕실 (가정값)
    md_tub: Decimal  # 욕조 설치 품 인/개 (가정값)
    tile_crew: int  # 하루 들어가는 타일공 수 (가정값)
    fit_crew: int  # 하루 들어가는 설치 인원 (천장재 · 도기, 가정값)
    wp_half_days: int  # 방수 두 번 + 물 채워 새는지 보기, 반나절 수 (가정값)
    cure_half_days: int  # 타일 양생, 반나절 수 (가정값)
    vat_rate: Decimal
    sources: dict[str, str]  # 줄 키 → 출처 문구


@dataclass(frozen=True)
class BathInput:
    area_m2: Decimal
    area_basis: AreaBasis
    occupied: bool
    baths: int = 1  # 고칠 욕실 개수
    scope: Scope = "full"
    tile_method: TileMethod = "remove"  # 전체일 때만 본다
    tub: Tub = "keep"
    ceiling: Ceiling = "smc"  # 전체일 때만 본다


@dataclass(frozen=True)
class BathQuote:
    version: str
    baths: int
    floor_m2: Decimal  # 타일 바닥 면적 (전체일 때만, 아니면 0)
    wall_m2: Decimal  # 타일 벽 면적 (전체일 때만, 아니면 0)
    lines: list[Line]
    subtotal: int
    vat: int
    total: int
    man_days: Decimal  # 타일공 · 위생공 품
    steps: list[Step]
    days: Decimal
    assumptions: list[str]


def _check(inp: BathInput) -> None:
    if inp.area_m2 <= 0:
        raise ValueError("면적은 0보다 커야 해요")
    if inp.area_basis not in ("supply", "exclusive"):
        raise ValueError("면적 기준이 잘못됐어요")
    if not 1 <= inp.baths <= MAX_BATHS:
        raise ValueError(f"고칠 욕실은 1~{MAX_BATHS}개예요")
    if inp.scope not in SCOPES or inp.tile_method not in TILE_METHODS:
        raise ValueError("욕실 공사 범위가 잘못됐어요")
    if inp.tub not in TUBS or inp.ceiling not in CEILINGS:
        raise ValueError("욕조나 천장재 값이 잘못됐어요")
    if inp.scope == "fixtures" and inp.tub == "remove":
        raise ValueError("욕조를 없애려면 바닥 타일까지 하는 전체 공사로 골라야 해요")


def _after(key: str, name: str, src: dict[str, str]) -> Line:
    return Line(key, name, None, "식", None, None, "after_visit", src["none"], "none")


def quote(inp: BathInput, p: BathPrices) -> BathQuote:
    _check(inp)
    src = p.sources
    n = inp.baths
    full = inp.scope == "full"
    overlay = full and inp.tile_method == "overlay"
    lines: list[Line] = []
    floor = wall = Decimal(0)
    md_tile = Decimal(0)

    if full:
        floor, wall = m2(p.floor_m2 * n), m2(p.wall_m2 * n)
        if not overlay:
            wp = m2((p.floor_m2 + p.wp_up_m2) * n)
            lines += [
                Line(
                    "wp_liquid",
                    "방수 1차 · 시멘트 액체방수 (바닥 · 벽 아랫부분)",
                    wp,
                    "㎡",
                    p.wp_liquid,
                    won(wp * p.wp_liquid),
                    "included",
                    src["wp_liquid"],
                ),
                Line(
                    "wp_coat",
                    "방수 2차 · 우레탄 도막 (바닥 · 벽 아랫부분)",
                    wp,
                    "㎡",
                    p.wp_coat,
                    won(wp * p.wp_coat),
                    "included",
                    src["wp_coat"],
                ),
                Line(
                    "base_wall",
                    "벽 타일 바탕 고르기",
                    wall,
                    "㎡",
                    p.base_wall,
                    won(wall * p.base_wall),
                    "included",
                    src["base_wall"],
                ),
            ]
        wall_price = p.tile_wall_overlay if overlay else p.tile_wall
        wall_mat, floor_mat = m2(wall * p.tile_ratio), m2(floor * p.tile_ratio)
        lines += [
            Line(
                "tile_wall",
                "벽 타일 덧붙이기 (접착)" if overlay else "벽 타일 붙이기 (압착)",
                wall,
                "㎡",
                wall_price,
                won(wall * wall_price),
                "included",
                src["tile_wall_overlay" if overlay else "tile_wall"],
            ),
            Line(
                "tile_floor",
                "바닥 타일 붙이기 (압착)",
                floor,
                "㎡",
                p.tile_floor,
                won(floor * p.tile_floor),
                "included",
                src["tile_floor"],
            ),
            Line(
                "wall_tile_mat",
                "벽 타일 (도기질 300×600)",
                wall_mat,
                "㎡",
                p.wall_tile_mat,
                won(wall_mat * p.wall_tile_mat),
                "included",
                src["wall_tile_mat"],
            ),
            Line(
                "floor_tile_mat",
                "바닥 타일 (자기질 300×300)",
                floor_mat,
                "㎡",
                p.floor_tile_mat,
                won(floor_mat * p.floor_tile_mat),
                "included",
                src["floor_tile_mat"],
            ),
            Line(
                "drain",
                "바닥 배수구 (트랩 포함)",
                Decimal(n),
                "개",
                p.drain,
                p.drain * n,
                "included",
                src["drain"],
            ),
            Line(
                "ceiling",
                f"천장재 ({CEILING_NAME[inp.ceiling]}, 자재 · 설치)",
                floor,
                "㎡",
                p.ceiling[inp.ceiling],
                won(floor * p.ceiling[inp.ceiling]),
                "included",
                src[f"ceiling_{inp.ceiling}"],
                "assumed",
            ),
        ]
        md_tile = wall * (p.md_tile_wall_overlay if overlay else p.md_tile_wall)
        md_tile += floor * p.md_tile_floor

    lines += [
        Line(
            "toilet_basin",
            "양변기 · 세면기 (자재 · 설치)",
            Decimal(n),
            "세트",
            p.toilet_basin,
            p.toilet_basin * n,
            "included",
            src["toilet_basin"],
            "assumed",
        ),
        Line(
            "faucets",
            "세면 · 샤워 수전 (자재 · 설치)",
            Decimal(n),
            "세트",
            p.faucets,
            p.faucets * n,
            "included",
            src["faucets"],
            "assumed",
        ),
    ]
    if full:
        lines.append(
            Line(
                "accessories",
                "욕실 액세서리 (수건걸이 · 휴지걸이 · 선반 · 거울)",
                Decimal(n),
                "세트",
                p.accessories,
                p.accessories * n,
                "included",
                src["accessories"],
                "assumed",
            )
        )
    if inp.tub == "new":
        lines.append(
            Line(
                "tub",
                "욕조 교체 (자재 · 설치)",
                Decimal(1),
                "개",
                p.tub_new,
                p.tub_new,
                "included",
                src["tub_new"],
                "assumed",
            )
        )
    elif inp.tub == "remove":
        lines.append(
            Line(
                "partition",
                "샤워 파티션 (욕조 자리, 고르면 추가)",
                Decimal(1),
                "개",
                p.partition,
                p.partition,
                "optional",
                src["partition"],
                "assumed",
            )
        )
    caulk = m2((p.caulk_full_m if full else p.caulk_fixture_m) * n)
    lines.append(
        Line(
            "caulk",
            "실리콘 마감",
            caulk,
            "m",
            p.caulk,
            won(caulk * p.caulk),
            "included",
            src["caulk"],
        )
    )

    if not full:
        removed = "기존 도기 · 수전"
    elif overlay:
        removed = "기존 도기 · 천장재"
    else:
        removed = "기존 타일 · 도기 · 천장재"
    if inp.tub in ("remove", "new"):
        removed += " · 욕조"
    lines.append(_after("demolish", f"{removed} 철거", src))
    if full:
        lines.append(_after("plumbing", "급수 · 배수 배관 점검 · 교체", src))
    lines.append(_after("waste", "폐기물 처리", src))
    if inp.occupied:
        lines.append(_after("moving", "짐 이동 · 보양", src))

    subtotal = sum(ln.amount for ln in lines if ln.state in COUNTED and ln.amount is not None)
    vat = won(Decimal(subtotal) * p.vat_rate)

    md_fit = (p.md_fit if full else p.md_fixture_only) * n
    if inp.tub == "new":
        md_fit += p.md_tub
    steps = [Step("prep", "짐 정리 · 보양", 1)] if inp.occupied else []
    if not full:
        steps.append(Step("remove", "기존 도기 · 수전 떼기", 1))
    elif overlay:
        steps.append(Step("remove", "도기 · 천장재 떼기 · 바탕 청소", 1))
    else:
        steps.append(Step("remove", "철거 · 바탕 정리", 2))
        steps.append(Step("waterproof", "방수 두 번 · 물 채워 새는지 확인", p.wp_half_days))
    fit_days = half_days(md_fit, p.fit_crew)
    if full:
        tile_days = half_days(md_tile, p.tile_crew) + p.cure_half_days
        steps.append(Step("tile", "타일 붙이기 · 양생", tile_days))
        steps.append(Step("fit", "천장재 · 도기 · 수전 설치", fit_days))
    else:
        steps.append(Step("fit", "도기 · 수전 설치", fit_days))
    steps.append(Step("finish", "실리콘 · 청소", 1))
    days = Decimal(sum(s.half_days for s in steps)) / 2

    assumptions = []
    if full:
        assumptions.append(
            f"욕실 한 칸을 바닥 {p.floor_m2}㎡ · 벽 타일 {p.wall_m2}㎡(흔한 아파트 공용 욕실 크기)로 "
            "잡았어요. 실측 때 다시 재요."
        )
        if overlay:
            assumptions.append(
                "덧방은 기존 방수층과 바탕을 그대로 쓰는 방식이라 방수 줄이 없어요. "
                "기존 타일이 들떠 있으면 실측 때 철거 후 새로 하는 쪽으로 바뀔 수 있어요."
            )
        else:
            assumptions.append(
                f"방수는 바닥과 벽 아랫부분(욕실 한 칸에 {p.wp_up_m2}㎡)까지 두 번 바르는 것으로 "
                "잡았어요. 방수 단가는 바닥 기준이에요."
            )
        assumptions.append(
            f"타일 소요량에는 버리는 몫 {int((p.tile_ratio - 1) * 100)}%를 넣었어요."
        )
        assumptions.append(
            "타일 붙이는 공공 단가는 시장 값보다 높게 나오는 편이에요. 업체 견적과 견줄 때 참고해요."
        )
    guessed = ["도기", "수전"] + (["천장재", "액세서리"] if full else [])
    guessed += {"new": ["욕조"], "remove": ["샤워 파티션"]}.get(inp.tub, [])
    assumptions.append(
        f"{' · '.join(guessed)} 값은 공공 단가가 없어 보급형 제품 기준 팀 가정값이에요."
    )
    if inp.tub in ("remove", "new"):
        assumptions.append("욕조는 욕실 한 칸에만 있다고 잡았어요.")
    if full:
        wait = (
            "타일 양생 하루를" if overlay else "방수 뒤 물을 채워 새는지 보는 날과 타일 양생 하루를"
        )
        assumptions.append(f"{wait} 공정표에 넣었어요.")
        assumptions.append(f"하루 타일공 {p.tile_crew}명이 들어가는 것으로 기간을 잡았어요.")

    return BathQuote(
        version=p.version,
        baths=n,
        floor_m2=floor,
        wall_m2=wall,
        lines=lines,
        subtotal=subtotal,
        vat=vat,
        total=subtotal + vat,
        man_days=half_up(md_tile + md_fit),
        steps=steps,
        days=days,
        assumptions=assumptions,
    )
