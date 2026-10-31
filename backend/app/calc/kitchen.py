"""주방 표준견적서와 예상 공정표. 항목은 싱크대(하부장 · 상부장) · 상판 · 레인지후드 · 싱크볼과 수전이다.

주방 가구는 공공 기준 단가가 없어 금액 줄이 모두 팀 가정값(basis="assumed")이다. 실측 전이라 길이를 모르면
평형과 배치에서 추정하고, 그 가정은 결과의 assumptions에 그대로 남긴다. 금액은 원 정수이고 반올림은 won()
한 곳에서만 한다.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from app.calc.common import COUNTED, PYEONG_M2, AreaBasis, Line, Step, half_days, half_up, m2, won

Layout = Literal["straight", "l_shape", "parallel"]
Top = Literal["acrylic", "quartz"]
LAYOUTS: tuple[Layout, ...] = ("straight", "l_shape", "parallel")
TOPS: tuple[Top, ...] = ("acrylic", "quartz")
LAYOUT_NAME = {"straight": "일자", "l_shape": "ㄱ자", "parallel": "11자"}
TOP_NAME = {"acrylic": "인조대리석", "quartz": "엔지니어드스톤"}
MAX_LENGTH = Decimal(10)


@dataclass(frozen=True)
class KitchenPrices:
    """계산에 쓰는 가정값 한 벌. refprice가 버전별로 만들어 넘긴다."""

    version: str
    cabinet: int  # 하부장 1m + 그 위 상부장 원/m (자재 · 설치)
    top: dict[str, int]  # 상판 종류별 원/m (자재 · 가공 · 설치)
    hood: int  # 레인지후드 원/개 (자재 · 설치)
    sink: int  # 싱크볼 · 수전 원/세트 (자재 · 설치)
    len_per_py: Decimal  # 공급 1평당 일자 싱크대 길이 m (가정값)
    len_min: Decimal  # 추정 길이 하한 m (가정값)
    len_max: Decimal  # 추정 길이 상한 m (가정값)
    layout_factor: dict[str, Decimal]  # 배치별 길이 배수 (가정값)
    supply_per_exclusive: Decimal  # 전용 → 공급 환산 (가정값)
    md_cabinet: Decimal  # 가구 설치 품 인/m (가정값)
    crew: int  # 하루 들어가는 설치 인원 (가정값)
    vat_rate: Decimal
    sources: dict[str, str]  # 줄 키 → 출처 문구


@dataclass(frozen=True)
class KitchenInput:
    area_m2: Decimal
    area_basis: AreaBasis
    occupied: bool
    layout: Layout = "straight"
    top: Top = "acrylic"
    length_m: Decimal | None = None  # 하부장 전체 길이. 모르면 평형과 배치로 추정
    hood: bool = True  # 레인지후드를 바꾸는지
    faucet: bool = True  # 싱크볼 · 수전을 바꾸는지


@dataclass(frozen=True)
class KitchenQuote:
    version: str
    length_m: Decimal  # 계산에 쓴 하부장 길이
    lines: list[Line]
    subtotal: int
    vat: int
    total: int
    man_days: Decimal  # 가구 설치 품
    steps: list[Step]
    days: Decimal
    assumptions: list[str]


def _check(inp: KitchenInput) -> None:
    if inp.area_m2 <= 0:
        raise ValueError("면적은 0보다 커야 해요")
    if inp.area_basis not in ("supply", "exclusive"):
        raise ValueError("면적 기준이 잘못됐어요")
    if inp.layout not in LAYOUTS or inp.top not in TOPS:
        raise ValueError("주방 배치나 상판 값이 잘못됐어요")
    if inp.length_m is not None and not 0 < inp.length_m <= MAX_LENGTH:
        raise ValueError(f"싱크대 길이는 0보다 크고 {MAX_LENGTH}m 이하여야 해요")


def _after(key: str, name: str, src: dict[str, str]) -> Line:
    return Line(key, name, None, "식", None, None, "after_visit", src["none"], "none")


def quote(inp: KitchenInput, p: KitchenPrices) -> KitchenQuote:
    _check(inp)
    src = p.sources
    supply = inp.area_m2 if inp.area_basis == "supply" else inp.area_m2 * p.supply_per_exclusive
    if inp.length_m is None:
        straight = min(max(supply / PYEONG_M2 * p.len_per_py, p.len_min), p.len_max)
        length = m2(straight * p.layout_factor[inp.layout])
    else:
        length = m2(inp.length_m)

    top_price = p.top[inp.top]
    lines = [
        Line(
            "cabinet",
            "싱크대 하부장 · 상부장 (PET 도어, 자재 · 설치)",
            length,
            "m",
            p.cabinet,
            won(length * p.cabinet),
            "included",
            src["cabinet"],
            "assumed",
        ),
        Line(
            "top",
            f"상판 ({TOP_NAME[inp.top]}, 자재 · 가공 · 설치)",
            length,
            "m",
            top_price,
            won(length * top_price),
            "included",
            src[f"top_{inp.top}"],
            "assumed",
        ),
        Line(
            "hood",
            "레인지후드 (자재 · 설치)",
            Decimal(1),
            "개",
            p.hood,
            p.hood if inp.hood else None,
            "included" if inp.hood else "excluded",
            src["hood"],
            "assumed",
        ),
        Line(
            "sink",
            "싱크볼 · 수전 (자재 · 설치)",
            Decimal(1),
            "세트",
            p.sink,
            p.sink if inp.faucet else None,
            "included" if inp.faucet else "excluded",
            src["sink"],
            "assumed",
        ),
        _after("demolish", "기존 싱크대 철거", src),
        _after("plumbing", "급수 · 배수 · 가스 위치 조정", src),
        _after("waste", "폐기물 처리", src),
    ]
    if inp.occupied:
        lines.append(_after("moving", "짐 이동 · 보양", src))

    subtotal = sum(ln.amount for ln in lines if ln.state in COUNTED and ln.amount is not None)
    vat = won(Decimal(subtotal) * p.vat_rate)

    md = length * p.md_cabinet
    parts = [n for n, on in (("싱크볼 · 수전", inp.faucet), ("후드", inp.hood)) if on]
    steps = [Step("prep", "짐 정리 · 보양", 1)] if inp.occupied else []
    steps += [
        Step("remove", "기존 싱크대 철거", 1),
        Step("cabinet", "하부장 · 상부장 설치", half_days(md, p.crew)),
        Step("top", "상판 설치", 1),
        Step("fit", " · ".join(parts) + " 연결" if parts else "싱크 급수 · 배수 연결", 1),
        Step("finish", "실리콘 · 청소", 1),
    ]
    days = Decimal(sum(s.half_days for s in steps)) / 2

    assumptions = [
        (
            "주방 가구는 공공 기준 단가가 없어 모든 금액이 보급형 제품 기준 팀 가정값이에요. "
            "업체 견적과 견줄 때 참고만 해 주세요."
        ),
        "가구 단가는 하부장 1m와 그 위 상부장을 합친 값이에요.",
    ]
    if inp.length_m is None:
        if inp.area_basis == "exclusive":
            assumptions.append(f"공급면적은 전용면적 × {p.supply_per_exclusive}로 환산했어요.")
        text = (
            f"싱크대 길이는 공급 1평에 {p.len_per_py}m"
            f"(최소 {p.len_min}m · 최대 {p.len_max}m)로 잡았어요."
        )
        if inp.layout != "straight":
            factor = p.layout_factor[inp.layout]
            text += f" {LAYOUT_NAME[inp.layout]} 배치는 일자의 {factor}배예요."
        assumptions.append(text + " 실측 때 다시 재요.")
    assumptions += [
        "주방 벽 타일과 인덕션 전용선 같은 전기 배선은 타일 · 전기 공정에서 따로 봐요.",
        f"하루 {p.crew}명이 들어가는 것으로 기간을 잡았어요.",
    ]

    return KitchenQuote(
        version=p.version,
        length_m=length,
        lines=lines,
        subtotal=subtotal,
        vat=vat,
        total=subtotal + vat,
        man_days=half_up(md),
        steps=steps,
        days=days,
        assumptions=assumptions,
    )
