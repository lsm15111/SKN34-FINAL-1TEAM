"""도배 표준견적서와 예상 공정표.

금액은 원 정수이고 반올림은 won() 한 곳에서만 한다. 면적은 ㎡ 소수 한 자리, 품은 0.5 단위로 올린다.
실측 전이라 면적은 평형에서 가정값으로 추정하고, 그 가정은 결과의 assumptions에 그대로 남긴다.

- quote(): 옛 표준견적서(도배지 ㎡ × 공공 재료비). v2 업체 단가표 예시 · 다른 계산이 그대로 쓴다.
- quote_v3() · standard_v3(): v3 표준견적서(D07 A · D02 A). 도배지 줄만 '벽지 평 × 시장 평균 가격'으로 바꾸고,
  부분 공사는 고른 공간 몫으로 벽 · 천장 면적을 줄인다. 가견적 v3 수량(QtyV3)도 같이 만든다.
- 단가 판에 회귀 계수(area_per_supply · area_per_room)가 있으면 집 전체 도배 면적을
  '공급㎡ × 계수 + 방 개수 × ㎡'로 센다(whole-house-area.md 방안 4). 없으면 옛 '면적 × area_factor'.
- v4 조건별 두 기준(ADR docs/v4/adr/0004): pick_profile()이 공사 조건으로 '도배만 하는 공사'(시장 가운데) ·
  '리모델링'(서울 업체 실견적 보정)을 고른다. 단가 판에 profile이 있으면 초배지 줄 대신 부자재 줄을 두고
  퍼티 · 식대 · 운송비 줄을 더한다. profile이 없는 옛 판은 옛 줄 그대로다.
- 가견적과 같은 규칙(ADR 0006): 판에 품 배수(md_mult)가 있으면 품 = 0.5 올림(표준품셈 품 × 도배 유형별 배수).
  same_rules 판은 '선택' 줄 키를 StandardV3.optional_keys로 넘겨 가견적도 그 줄을 합계 밖에 둔다.
- v4 반셀프 '벽지 직접 구매'(own_paper, 2026-11-22 리드 결정): 도배지 줄을 '안 함'(까닭 '고객 구매')으로 두어
  합계에서 뺀다. 수량 · 단가 · 금액은 참고로 남긴다(업체 가견적과 견줄 때 with_own_paper). 포함 상태는 6종 그대로다.
  도배지 줄이 '안 함'인 것은 이때뿐이다(own_paper_line).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from typing import Literal, Protocol

from app.calc.common import (
    BASIS_LABEL,
    COUNTED,
    PYEONG_M2,
    AreaBasis,
    Basis,
    Line,
    LineState,
    Money,
    Step,
    half_days,
    half_up,
    m2,
    won,
)
from app.calc.space_share import (
    RoomSpaceShares,
    SpaceShares,
    room_kinds,
    rooms_needed,
    share_of,
)
from app.calc.standard_quote import HouseRules, house_pyeong

Grade = Literal["economy", "basic"]
GRADE_PAPER = {"economy": "합지", "basic": "실크"}
Face = Literal["wall", "ceiling"]
FACES: tuple[Face, ...] = ("wall", "ceiling")
Scope = Literal["full", "partial"]
# 조건별 두 기준(ADR 0004): 도배만 하는 공사 · 전체 철거나 큰 목공이 든 리모델링
Profile = Literal["paper_only", "remodel"]


@dataclass(frozen=True)
class ProfilePrices:
    """두 기준 중 하나의 줄 값 · 상태. refprice가 판마다 만들어 DobaePrices.profile에 넣는다."""

    key: Profile
    name: str  # 화면 이름: 도배만 하는 공사 기준 · 리모델링 기준
    source: str  # 근거 이름: 시장 실견적 가운데(8출처 619건, 2026-11) …
    labor_basis: Basis  # 벽 · 천장 시공 줄 근거 (공공 단가 그대로면 public)
    labor_mult: Mapping[str, Decimal]  # 도배 유형별 시공 ㎡ 단가 배수 (합지 0.55 = 시장 품 비)
    paper_ratio: Mapping[str, Decimal]  # 도배 유형별 정배지 소요량 (도배 면적 × 이 값 = 벽지 ㎡)
    material_py: Mapping[str, int]  # 부자재 원/공급 평 (초배지 줄 대신)
    putty_py: int  # 퍼티 원/공급 평
    putty_state: LineState
    meal_md: int | None  # 식대 원/품. None이면 줄 없음(일당에 식대가 든 시장 관행)
    truck: int  # 운송비 · 경비 원/한 번
    truck_state: LineState
    sources: Mapping[str, str]  # material · putty · meal · truck · labor_mult → 출처


# 두 기준 표준견적서 줄 이름 · 단위. 이름 끝 괄호는 고객 화면 줄 아래 짧은 뜻이에요
# (지금 '벽 도배 시공 (풀 포함)'과 같은 꼴, 화면이 괄호를 떼어 보여요). 키는 가견적 v3 줄(estimate.V3_ROWS)과 같다
PROFILE_LINES: dict[Profile, dict[str, tuple[str, str]]] = {
    "paper_only": {
        "wall": ("벽 도배 시공 (풀 포함)", "㎡"),
        "ceiling": ("천장 도배 시공 (풀 포함)", "㎡"),
        "material": ("부자재 (풀 · 부직포 · 네바리 · 실리콘 등)", "공급 평"),
        "putty": ("퍼티작업 (사전퍼티 · 밑작업)", "공급 평"),
        "truck": ("운송 · 경비 (자재 운반 · 주차 등)", "식"),
    },
    "remodel": {
        "wall": ("벽 도배 시공 (인건비)", "㎡"),
        "ceiling": ("천장 도배 시공 (인건비)", "㎡"),
        "material": ("부자재 (풀 · 부직포 · 네바리 · 실리콘 등)", "공급 평"),
        "putty": ("퍼티작업 (사전퍼티 · 밑작업)", "공급 평"),
        "meal": ("식대 (1명 하루 밥값)", "품"),
        "truck": ("운송비 (자재 운반 차)", "대"),
    },
}


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
    # v3 회귀식 (가정값): 도배 면적 = 공급㎡ × area_per_supply + 방 개수 × area_per_room.
    # 비우면 옛 area_factor를 쓴다. 전용면적은 supply_per_exclusive로 공급면적을 잡는다
    area_per_supply: Decimal | None = None
    area_per_room: Decimal | None = None
    supply_per_exclusive: Decimal | None = None
    # 방 개수 기본값: (공급 평 이상, 방 개수)를 작은 평부터. 고객이 방 개수를 안 넣었을 때 쓴다
    room_bands: tuple[tuple[Decimal, int], ...] = ()
    room_fallback: int = 3  # 면적을 모를 때 화면에 먼저 보이는 방 개수
    # v4 조건별 두 기준(ADR 0004). 비우면 옛 v3 줄(초배지 · 퍼티 · 식대 · 운송비 없음)
    profile: ProfilePrices | None = None
    # 도배 유형별 품 배수(ADR 0006). 비우면 표준품셈 품 그대로(옛 판). 공정표는 모은 조건 없이 세므로
    # 두 기준 판이 같은 값이어야 해요(품 · 기간은 기준과 상관없음)
    md_mult: Mapping[str, Decimal] | None = None
    # 가견적도 이 판 표준견적서와 같은 줄 규칙: 표준에서 '선택'인 줄은 가견적에서도 합계 밖(ADR 0006)
    same_rules: bool = False


def num(x: Decimal) -> str:
    """글에 넣는 숫자: 25.0 → 25, 1.55 → 1.55"""
    return format(x.normalize(), "f")


def supply_m2(area_m2: Decimal, basis: AreaBasis, p: DobaePrices) -> Decimal:
    """회귀식에 넣을 공급면적 (전용이면 × supply_per_exclusive)"""
    if basis == "supply":
        return area_m2
    if p.supply_per_exclusive is None:
        raise ValueError("전용 → 공급 환산값이 없는 단가 판이에요")
    return area_m2 * p.supply_per_exclusive


def default_rooms(area_m2: Decimal, basis: AreaBasis, p: DobaePrices) -> int:
    """평형으로 채우는 방 개수 기본값 (room_bands). 표가 없으면 room_fallback"""
    if not p.room_bands or area_m2 <= 0:
        return p.room_fallback
    py = supply_m2(area_m2, basis, p) / PYEONG_M2
    rooms = p.room_bands[0][1]
    for floor, n in p.room_bands:
        if py >= floor:
            rooms = n
    return rooms


def room_bands_m2(p: DobaePrices) -> list[tuple[AreaBasis, Decimal, int]]:
    """방 개수 기본값 표를 ㎡로: (면적 기준, 이 ㎡ 이상, 방 개수). ㎡는 소수 한 자리로 올려
    default_rooms와 같은 답이 나오게 한다(화면이 칸만 찾게)."""
    out: list[tuple[AreaBasis, Decimal, int]] = []
    for basis in ("supply", "exclusive"):
        per = Decimal(1) if basis == "supply" else p.supply_per_exclusive
        if per is None:
            continue
        for floor, n in p.room_bands:
            edge = (floor * PYEONG_M2 / per).quantize(Decimal("0.1"), rounding=ROUND_CEILING)
            out.append((basis, edge, n))
    return out


@dataclass(frozen=True)
class DobaeInput:
    area_m2: Decimal
    area_basis: AreaBasis
    grade: Grade
    include_ceiling: bool
    occupied: bool
    balcony_ext: bool = False


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
            "assumed" if inp.grade == "economy" else "public",
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

    md = wall * p.md_wall + ceil_used * p.md_ceiling
    if inp.occupied:
        md = md / p.occupied_output
    man_days = half_up(md)
    work = half_days(man_days, p.crew)
    steps = [Step("prep", "짐 정리 · 보양", 1)] if inp.occupied else []
    steps.append(
        Step(
            "paper", "벽지 바르기 (벽 · 천장)" if inp.include_ceiling else "벽지 바르기 (벽)", work
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


# ---- v3 표준견적서 (D07 A · D02 A, data-model 6장) ----


class PaperPrice(Protocol):
    """도배지 시장 평균 가격 한 판. refprice.wallpaper_market.PaperMarket이 이 이름들을 가진다."""

    version: str  # 견적에 고정하는 판 (standard_quotes.market_ver)
    name: str  # 실크벽지 · 합지벽지
    per_py: int  # 원/벽지 평 (부가세 별도, 화면 값 = 평균)
    n: int  # 근거 줄 수


@dataclass(frozen=True)
class DobaeV3Input:
    area_m2: Decimal
    area_basis: AreaBasis
    grade: Grade
    occupied: bool
    faces: tuple[Face, ...] = FACES
    share: Decimal | None = None  # 부분 공사: 고른 공간 몫 합(0~1). 비우면 전체
    balcony_ext: bool = False
    rooms: int | None = None  # 방 개수 (회귀식 단가 판에서 꼭 필요)
    # 부자재 · 퍼티 수량(공급 평, 부분 공사면 공간 몫을 곱한 값). 두 기준(profile) 판에서 꼭 필요
    floor_py: Decimal | None = None
    # 벽지를 고객이 직접 사요(반셀프 '벽지 직접 구매'): 도배지 줄 '안 함' · 고객 구매
    own_paper: bool = False


# 반셀프 '벽지 직접 구매': 도배지 줄 까닭(줄 근거 글 앞머리) · 가정 줄
OWN_PAPER = "고객 구매"
OWN_PAPER_ASSUMED = "벽지는 고객이 직접 사요(고객 구매). 도배지 줄은 합계에 넣지 않았어요."


def paper_py(paper_m2: Decimal) -> Decimal:
    """도배지 소요량 ㎡ → 벽지 평 (0.1평 반올림, 벽지 1평 = 3.3058㎡)"""
    return m2(paper_m2 / PYEONG_M2)


def own_paper_line(key: str, state: str) -> bool:
    """고객이 직접 사서 합계에서 뺀 도배지 줄인가. 도배지 줄은 own_paper일 때만 '안 함'이에요(quote · quote_v3)."""
    return key == "paper" and state == "excluded"


class _AmountLine(Protocol):
    key: str
    state: str
    amount: int | None


def with_own_paper(lines: Sequence[_AmountLine], vat_rate: Decimal) -> Money:
    """고객 구매 도배지 줄까지 넣은 공급가 · 부가세 · 합계(표준견적서 합계와 같은 반올림). 업체 가견적은 벽지 값이
    든 값이라('시공만' 값은 뒤로) 견줄 때 이 값을 써요. 고객 구매 줄이 없으면 표준견적서 합계와 같아요."""
    supply = sum(
        ln.amount
        for ln in lines
        if (ln.state in COUNTED or own_paper_line(ln.key, ln.state)) and ln.amount is not None
    )
    vat = won(Decimal(supply) * vat_rate)
    return Money(supply, vat, supply + vat)


def without_paper(lines: Sequence[_AmountLine], vat_rate: Decimal) -> Money:
    """도배지 줄을 뺀 공급가 · 부가세 · 합계(벽지 직접 구매로 바꿨을 때의 표준견적서 합계와 같은 반올림)."""
    supply = sum(
        ln.amount
        for ln in lines
        if ln.state in COUNTED and ln.key != "paper" and ln.amount is not None
    )
    vat = won(Decimal(supply) * vat_rate)
    return Money(supply, vat, supply + vat)


@dataclass(frozen=True)
class PaperSplit:
    """벽지(도배지 줄)를 넣은 합계 · 뺀 합계 · 그 차(벽지 값의 부가세 포함 몫). 모두 표준견적서와 같은 반올림."""

    with_paper: Money
    without_paper: Money
    share: int  # with_paper.total − without_paper.total: 벽지를 고객이 사면 합계에서 빠지는 돈(부가세 포함)


def paper_split(lines: Sequence[_AmountLine], vat_rate: Decimal) -> PaperSplit:
    """표준견적서 줄(벽지 직접 구매든 아니든) → 벽지를 넣은 합계 · 뺀 합계 · 벽지 값(부가세 포함 몫).
    도배지 줄 금액은 공급가라 부가세 포함 합계에서 그대로 빼면 틀린 값이 나와요(QA r3 s5: 2,952,491 − 913,665).
    비서 도구는 이 값으로 '벽지를 직접 사면 얼마로 바뀌어요?' · '벽지까지 맡기면 얼마예요?'에 답해요."""
    a, b = with_own_paper(lines, vat_rate), without_paper(lines, vat_rate)
    return PaperSplit(a, b, a.total - b.total)


class _QtyLine(Protocol):
    key: str
    qty: Decimal | None
    state: str


def paper_m2_from_lines(lines: Sequence[_QtyLine], p: DobaePrices) -> Decimal:
    """v3 표준견적서 줄의 벽 · 천장 시공 수량으로 도배지 소요량(㎡)을 다시 센다.
    옛 v2 업체 단가(도배지 ㎡당)로 가견적을 낼 때 쓴다(quote()의 도배지 ㎡ 수량과 같은 값)."""
    area = sum(
        (
            ln.qty
            for ln in lines
            if ln.key in ("wall", "ceiling") and ln.state in COUNTED and ln.qty is not None
        ),
        Decimal(0),
    )
    return m2(area * p.paper_ratio)


def _paper_source(paper: PaperPrice) -> str:
    return f"벽지 시장 평균 가격 · {paper.name} 근거 {paper.n}줄 ({paper.version})"


def _profile_lines(
    pf: ProfilePrices, grade: Grade, floor_py: Decimal, man_days: Decimal
) -> list[Line]:
    """두 기준 판의 부자재 · 퍼티 · 식대 · 운송비(경비) 줄. 금액은 줄마다 won() 한 번."""
    names, src = PROFILE_LINES[pf.key], pf.sources
    material = pf.material_py[grade]
    out = [
        Line(
            "material",
            names["material"][0],
            floor_py,
            names["material"][1],
            material,
            won(floor_py * material),
            "included",
            src["material"],
            "market",
        ),
        Line(
            "putty",
            names["putty"][0],
            floor_py,
            names["putty"][1],
            pf.putty_py,
            won(floor_py * pf.putty_py),
            pf.putty_state,
            src["putty"],
            "market",
        ),
    ]
    if pf.meal_md is not None:
        out.append(
            Line(
                "meal",
                names["meal"][0],
                man_days,
                names["meal"][1],
                pf.meal_md,
                won(man_days * pf.meal_md),
                "included",
                src["meal"],
                "market",
            )
        )
    one = Decimal("1.0")
    out.append(
        Line(
            "truck",
            names["truck"][0],
            one,
            names["truck"][1],
            pf.truck,
            won(one * pf.truck),
            pf.truck_state,
            src["truck"],
            "market",
        )
    )
    return out


def quote_v3(inp: DobaeV3Input, p: DobaePrices, paper: PaperPrice) -> DobaeQuote:
    """v3 표준견적서. 도배지 줄 = 벽지 평(도배 면적 × 소요량 ÷ 3.3058) × 시장 평균 가격(basis market).
    부분 공사면 벽 · 천장 면적에 공간 몫을 곱하고, 고르지 않은 면은 '안 함'(수량 · 금액 없음).
    두 기준 판(p.profile)이면 시공 ㎡ 단가에 도배 유형 배수(합지 0.55)를 곱해 원 단위로 끊고, 소요량은
    도배 유형별 값을 쓰고, 초배지 줄 대신 부자재 · 퍼티 · 식대 · 운송비 줄을 둔다(합계는 포함 상태대로)."""
    if inp.area_m2 <= 0:
        raise ValueError("면적은 0보다 커야 해요")
    pf = p.profile
    if pf is not None and (inp.floor_py is None or inp.floor_py <= 0):
        raise ValueError("부자재 · 퍼티 수량(공급 평)이 있어야 해요")
    if not inp.faces or not set(inp.faces) <= set(FACES):
        raise ValueError("벽 · 천장 중 하나 이상 골라야 해요")
    if inp.share is not None and not Decimal(0) < inp.share <= 1:
        raise ValueError("공간 몫은 0보다 크고 1 이하여야 해요")
    by_rooms = p.area_per_supply is not None and p.area_per_room is not None
    if by_rooms:
        if inp.rooms is None:
            raise ValueError("방 개수가 있어야 해요")
        room_kinds(inp.rooms)  # 1~5 밖이면 ValueError
        sup = supply_m2(inp.area_m2, inp.area_basis, p)
        gross = sup * p.area_per_supply + inp.rooms * p.area_per_room
    else:
        gross = inp.area_m2 * p.area_factor[inp.area_basis]
    if inp.balcony_ext and p.balcony_factor != 1:
        gross *= p.balcony_factor
    ceiling = m2(gross * p.ceiling_share)
    wall = m2(gross) - ceiling
    if inp.share is not None:
        wall, ceiling = m2(wall * inp.share), m2(ceiling * inp.share)
    do_wall, do_ceil = "wall" in inp.faces, "ceiling" in inp.faces
    wall_used = wall if do_wall else Decimal(0)
    ceil_used = ceiling if do_ceil else Decimal(0)
    paper_area = wall_used + ceil_used
    src = p.sources

    # 품 · 기간 (두 기준 판의 식대 줄 · 가견적 인건비가 품을 쓴다). 기준과 상관없고, 품 배수가 있는 판은
    # 도배 유형별로 곱한다(ADR 0006: 시장 실견적 품 ÷ 표준품셈 품, 합지는 실크의 0.55배)
    md = wall_used * p.md_wall + ceil_used * p.md_ceiling
    if p.md_mult is not None:
        md *= p.md_mult[inp.grade]
    if inp.occupied:
        md = md / p.occupied_output
    man_days = m2(half_up(md))  # 0.5 단위 값을 소수 한 자리 꼴로 (5 → 5.0, 값은 그대로)

    mult = pf.labor_mult[inp.grade] if pf else Decimal(1)
    labor_wall, labor_ceiling = won(p.labor_wall * mult), won(p.labor_ceiling * mult)
    ratio = pf.paper_ratio[inp.grade] if pf else p.paper_ratio
    names = PROFILE_LINES[pf.key] if pf else {}
    labor_basis: Basis = "public" if pf is None else pf.labor_basis if mult == 1 else "market"

    def labor_src(key: str) -> str:
        if pf is None or mult == 1:
            return src[key]
        return f"{src[key]} × {num(mult)} ({pf.sources['labor_mult']})"

    wall_amt = won(wall_used * labor_wall)
    ceil_amt = won(ceil_used * labor_ceiling)
    paper_qty = paper_py(m2(paper_area * ratio))
    # 벽지 직접 구매면 도배지 줄은 '안 함'(까닭 고객 구매). 수량 · 단가 · 금액은 참고로 남기고 합계에서 뺀다
    paper_state: LineState = "excluded" if inp.own_paper else "included"
    paper_src = f"{OWN_PAPER} · {_paper_source(paper)}" if inp.own_paper else _paper_source(paper)
    lines = [
        Line(
            "wall",
            names.get("wall", ("벽 도배 시공 (풀 포함)",))[0],
            wall if do_wall else None,
            "㎡",
            labor_wall,
            wall_amt if do_wall else None,
            "included" if do_wall else "excluded",
            labor_src("wall"),
            labor_basis,
        ),
        Line(
            "ceiling",
            names.get("ceiling", ("천장 도배 시공 (풀 포함)",))[0],
            ceiling if do_ceil else None,
            "㎡",
            labor_ceiling,
            ceil_amt if do_ceil else None,
            "included" if do_ceil else "excluded",
            labor_src("ceiling"),
            labor_basis,
        ),
        Line(
            "paper",
            f"{paper.name} 시장 평균 가격",
            paper_qty,
            "벽지 평",
            paper.per_py,
            won(paper_qty * paper.per_py),
            paper_state,
            paper_src,
            "market",
        ),
    ]
    if pf is None:
        primer_qty = m2(wall_used * p.primer_wall_ratio + ceil_used * p.primer_ceiling_ratio)
        lines.append(
            Line(
                "primer",
                "초배지",
                primer_qty,
                "㎡",
                p.primer,
                won(primer_qty * p.primer),
                "included",
                src["primer"],
            )
        )
    else:
        lines += _profile_lines(pf, inp.grade, inp.floor_py, man_days)
    if inp.occupied:
        extra = won(Decimal(wall_amt + ceil_amt) * p.labor_ratio * (1 / p.occupied_output - 1))
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

    work = half_days(man_days, p.crew)
    steps = [Step("prep", "짐 정리 · 보양", 1)] if inp.occupied else []
    face_name = " · ".join({"wall": "벽", "ceiling": "천장"}[f] for f in FACES if f in inp.faces)
    steps.append(Step("paper", f"벽지 바르기 ({face_name})", work))
    steps.append(Step("finish", "마감 · 확인 · 청소", 1))
    days = m2(Decimal(sum(s.half_days for s in steps)) / 2)

    if by_rooms:
        conv = (
            ""
            if inp.area_basis == "supply"
            else f"(전용 × {num(p.supply_per_exclusive)} = 공급 {num(m2(sup))}㎡)"
        )
        area_note = (
            f"도배 면적은 공급면적{conv} × {num(p.area_per_supply)} + 방 {inp.rooms}개 × "
            f"{num(p.area_per_room)}㎡로 추정했어요(공개 평면도 20곳 기준, 발코니 확장 집). "
            "실측 때 방마다 다시 재요."
        )
    else:
        area_note = f"도배 면적은 {BASIS_LABEL[inp.area_basis]} × {p.area_factor[inp.area_basis]}로 추정했어요. 실측 때 방마다 다시 재요."
    paper_note = (
        f"도배지는 {paper.name} 시장 평균 가격으로 셌어요(벽지 1평 = 3.3058㎡)."
        if pf is None
        else f"도배지는 {paper.name} 시장 평균 가격으로, 소요량은 도배 면적의 "
        f"{num(ratio)}배로 셌어요(벽지 1평 = 3.3058㎡)."
    )
    assumptions = [
        area_note,
        f"천장은 도배 면적의 {int(p.ceiling_share * 100)}%로 잡았어요.",
        paper_note,
        f"하루 도배공 {p.crew}명이 들어가는 것으로 기간을 잡았어요.",
    ]
    if pf is not None and mult != 1:
        assumptions.append(
            f"{paper.name}는 실크보다 빨리 붙여 시공비를 {num(mult)}배로 셌어요(시장 품 비)."
        )
    if inp.share is not None:  # 글: copy-fixes CF-45
        assumptions.insert(
            0, "부분 공사는 고른 공간의 넓이를 어림해 계산했어요. 실측 뒤 업체 견적서로 확정해요."
        )
    if inp.balcony_ext and p.balcony_factor != 1:
        assumptions.append(f"발코니 확장은 도배 면적을 {p.balcony_factor}배로 잡았어요.")
    if inp.own_paper:
        assumptions.append(OWN_PAPER_ASSUMED)
    return DobaeQuote(
        version=p.version,
        paper_m2=paper_area,
        wall_m2=wall_used,
        ceiling_m2=ceil_used,
        lines=lines,
        subtotal=subtotal,
        vat=vat,
        total=subtotal + vat,
        man_days=man_days,
        steps=steps,
        days=days,
        assumptions=assumptions,
    )


@dataclass(frozen=True)
class HomeV3:
    """v3 기본 정보 중 계산에 쓰는 것. 손님 답(HomeInfoIn) · 저장한 공사에서 만든다."""

    area_m2: Decimal
    area_basis: AreaBasis
    grade: Grade
    occupied: bool
    scope: Scope = "full"
    spaces: tuple[str, ...] = ()  # 부분 공사 공간 종류
    faces: tuple[Face, ...] = FACES
    balcony_ext: bool = False
    rooms: int | None = None  # 방 개수. 비우면 평형 기본값(옛 공사 · v2 공사)


def rooms_of(h: HomeV3, p: DobaePrices) -> int:
    """계산에 쓰는 방 개수: 넣은 값, 없으면 평형 기본값(고른 방 칩이 더 많으면 그만큼, 최대 5)"""
    if h.rooms is not None:
        return h.rooms
    return min(max(default_rooms(h.area_m2, h.area_basis, p), rooms_needed(h.spaces)), 5)


@dataclass(frozen=True)
class QtyV3:
    """가견적 v3 수량 (dev-06): 공급 평 · 벽지 평 · 품. 부분 공사면 공간 몫으로 줄인 값"""

    floor_py: Decimal
    paper_py: Decimal
    man_day: Decimal


@dataclass(frozen=True)
class StandardV3:
    quote: DobaeQuote
    pyeong: Decimal  # 내 집 평 (공급 기준, 표시용)
    share: Decimal | None  # 부분 공사 공간 몫 합
    share_ver: str | None  # 공간 몫 표 판 (부분일 때만)
    market_ver: str  # 벽지 시장 평균 가격 판
    qty: QtyV3
    rooms: int | None = None  # 계산에 쓴 방 개수 (회귀식 판만)
    # 가견적도 합계 밖에 둘 표준 '선택' 줄 키 (same_rules 판만, ADR 0006). estimate_v3(optional_keys=)
    optional_keys: frozenset[str] = frozenset()


def standard_v3(
    h: HomeV3,
    p: DobaePrices,
    paper: PaperPrice,
    shares: SpaceShares | RoomSpaceShares,
    house: HouseRules,
    why: Sequence[str] = (),
    own_paper: bool = False,
) -> StandardV3:
    """기본 정보 → v3 표준견적서 + 가견적 수량. 표준견적서 저장 · 손님 계산 · 가견적이 같은 값을 쓴다.
    부분 공사 몫은 방 개수에 맞는 표로 센다(방 개수에 없는 방 칩이면 ValueError).
    두 기준 판이면 고른 기준과 근거(why, pick_profile 결과)를 가정 첫 줄에 적는다.
    own_paper(벽지 직접 구매)면 도배지 줄을 '안 함'(고객 구매)으로 합계에서 뺀다. 가견적 수량(qty)은 그대로다."""
    if h.area_m2 <= 0:
        raise ValueError("면적은 0보다 커야 해요")
    by_rooms = p.area_per_supply is not None
    rooms = rooms_of(h, p) if by_rooms else None
    share = None
    if h.scope == "partial":
        table = shares.for_rooms(rooms or 3)
        unknown = [k for k in dict.fromkeys(h.spaces) if k not in table.share]
        if unknown and isinstance(shares, RoomSpaceShares):
            raise ValueError("방 개수보다 많은 방을 골랐어요")
        share = share_of(h.spaces, table)
    py = house_pyeong(None, h.area_m2, h.area_basis, house)
    floor = py if share is None else m2(py * share)  # 부자재 · 퍼티 · 가견적 '공급 평' 수량
    q = quote_v3(
        DobaeV3Input(
            h.area_m2,
            h.area_basis,
            h.grade,
            h.occupied,
            h.faces,
            share,
            h.balcony_ext,
            rooms,
            floor if p.profile is not None else None,
            own_paper,
        ),
        p,
        paper,
    )
    if p.profile is not None:
        q = replace(q, assumptions=[profile_note(p.profile, q.lines, why), *q.assumptions])
    paper_line = next(ln for ln in q.lines if ln.key == "paper")
    qty = QtyV3(floor_py=floor, paper_py=paper_line.qty or Decimal(0), man_day=q.man_days)
    share_ver = shares.version if share is not None else None
    optional = frozenset(ln.key for ln in q.lines if p.same_rules and ln.state == "optional")
    return StandardV3(q, py, share, share_ver, paper.version, qty, rooms, optional)


# ---- v4 조건별 두 기준 고르기 (ADR docs/v4/adr/0004-금액-조건별-두-기준.md) ----


@dataclass(frozen=True)
class WorkFacts:
    """기준 고르기에 쓰는 공사 조건. 서비스가 공사(고른 목공 항목)와 모은 조건(project_conditions)으로 만든다."""

    mok_items: tuple[str, ...] = ()  # 고른 목공 항목 (molding · base · door · flatten)
    said: Mapping[str, str] = field(default_factory=dict)  # 모은 조건 {칸: 고객이 고른 단추 글}


@dataclass(frozen=True)
class ProfilePick:
    profile: Profile
    why: tuple[str, ...]  # 리모델링으로 고른 근거 이름. 도배만 하는 공사면 비어 있다


# 모은 조건 '철거 범위'(2026-11-21 리드 결정): 키 · 값은 코드 값이에요(단추 글 아님). 화면 · 비서가 같은 키를 써요
DEMOLITION_KEY = "demolition"
DEMOLITION = {"full": "전체 철거", "partial": "부분 철거", "none": "철거 안 함"}

# 리모델링 신호: (근거 이름, 목공 항목, 모은 조건 칸, 그 칸의 '한다' 값, '안 한다' 값).
# 목공 두 줄의 값은 agent.v3.trades 되묻기 단추 글과 같아요(테스트가 본다). 모은 조건이 '한다' · '안 한다'면 그 답을,
# 칸이 없거나 '아직 몰라요' · 단추 글이 아닌 답이면 공사에 고른 목공 항목을 본다(목공 항목이 없는 신호는 아님).
# 몰딩 · 걸레받이 교체는 흔한 가벼운 공사라 신호가 아니에요(2026-11-21 리드 결정). 철거는 전체 철거만 신호예요
REMODEL_SIGNALS: tuple[tuple[str, str | None, str, str, str], ...] = (
    ("문틀 교체", "door", "mokgong.doors", "문틀까지", "문짝만"),
    ("천장 평탄화", "flatten", "mokgong.ceiling", "네", "아니요"),
    ("전체 철거", None, DEMOLITION_KEY, "full", "none"),
)
SCOPE_KEY = "mokgong.molding_scope"  # '이번 공사는 어디까지 하세요?'
SCOPE_ALL = "벽 · 천장까지 새로"  # 철거 뒤 벽 · 천장을 새로 마감하는 공사 → 리모델링


def _said(w: WorkFacts, key: str) -> str | None:
    v = w.said.get(key)
    return " ".join(v.split()) if v else None


def pick_profile(w: WorkFacts) -> ProfilePick:
    """공사 조건 → 두 기준 중 하나. 문틀 교체 · 천장 평탄화 · 전체 철거 · '벽 · 천장까지 새로' 중 하나라도 있으면
    리모델링(서울 업체 실견적 보정), 없으면 도배만 하는 공사(시장 실견적 가운데). 몰딩 교체만은 도배만이다."""
    why: list[str] = []
    for name, item, key, yes, no in REMODEL_SIGNALS:
        said = _said(w, key)
        hit = said == yes if said in (yes, no) else item is not None and item in w.mok_items
        if hit:
            why.append(name)
    if _said(w, SCOPE_KEY) == SCOPE_ALL:
        why.append(f"'{SCOPE_ALL}'")
    return ProfilePick("remodel" if why else "paper_only", tuple(why))


def profile_note(pf: ProfilePrices, lines: Sequence[Line], why: Sequence[str] = ()) -> str:
    """가정 첫 줄: 고른 기준 · 근거 · 값 출처, 합계 밖 '선택' 줄 이름."""
    head = f"{pf.name}으로 셌어요" + (f"(근거: {' · '.join(why)})" if why else "")
    optional = [ln.name.split(" (")[0] for ln in lines if ln.state == "optional"]
    tail = f" {' · '.join(optional)}는 '선택' 줄이라 합계에 넣지 않았어요." if optional else ""
    return f"{head}. 값은 {pf.source}이에요.{tail}"


# ---- 비서 근거: 어떻게 셌나요 · 줄이는 길 (2026-11-23 고객 질문 '인건비 5품 · 21.6평은 어떻게 나와요') ----


def _r2(x: Decimal) -> Decimal:
    """글에 보일 중간 값(소수 둘째 자리 반올림). 보이기만 하고 수량 · 금액에는 쓰지 않아요."""
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _won(x: int) -> str:
    return f"{x:,}원"


def count_basis(h: HomeV3, p: DobaePrices, house: HouseRules, v: StandardV3) -> list[str]:
    """표준견적서(standard_v3 결과 v)의 수량 · 품을 어떻게 셌는지 글 줄. 숫자는 quote_v3와 같은 식으로 다시 낸 값이고,
    다시 낸 면적 · 벽지 평 · 품이 v와 다르면 빈 목록이에요(틀린 근거를 말하지 않게).
    업체 가견적 수량(공급 평 · 벽지 평 · 품)도 같은 값이라 가견적 줄 물음('인건비 5품은 어떻게')의 근거도 된다.
    면적을 방 개수 회귀식으로 세는 판(area_per_supply)만 센다."""
    if p.area_per_supply is None or p.area_per_room is None or v.rooms is None:
        return []
    q, pf = v.quote, p.profile
    # 도배 면적: quote_v3와 같은 식(공급㎡ × 계수 + 방 × ㎡ → 천장 몫 → 공간 몫 → 고른 면)
    sup = supply_m2(h.area_m2, h.area_basis, p)
    gross = sup * p.area_per_supply + v.rooms * p.area_per_room
    if h.balcony_ext and p.balcony_factor != 1:
        gross *= p.balcony_factor
    ceiling = m2(gross * p.ceiling_share)
    wall = m2(gross) - ceiling
    if v.share is not None:
        wall, ceiling = m2(wall * v.share), m2(ceiling * v.share)
    wall_used = wall if "wall" in h.faces else Decimal(0)
    ceil_used = ceiling if "ceiling" in h.faces else Decimal(0)
    ratio = pf.paper_ratio[h.grade] if pf else p.paper_ratio
    need = m2((wall_used + ceil_used) * ratio)
    paper = next((ln for ln in q.lines if ln.key == "paper"), None)
    md = wall_used * p.md_wall + ceil_used * p.md_ceiling
    terms = [
        f"{name} {num(area)}㎡ × {num(per)}"
        for name, area, per in (("벽", wall_used, p.md_wall), ("천장", ceil_used, p.md_ceiling))
        if area
    ]
    steps = [f"{' + '.join(terms)} = 약 {num(_r2(md))}품(표준품셈)"]
    if p.md_mult is not None:
        md *= p.md_mult[h.grade]
        steps.append(f"시장 품 비 × {num(p.md_mult[h.grade])} = 약 {num(_r2(md))}품")
    if h.occupied:
        md = md / p.occupied_output
        steps.append(f"짐 있는 집 ÷ {num(p.occupied_output)} = 약 {num(_r2(md))}품")
    same = (
        (wall_used, ceil_used) == (q.wall_m2, q.ceiling_m2)
        and paper is not None
        and paper.qty == paper_py(need)
        and m2(half_up(md)) == q.man_days
    )
    if not same:
        return []
    out: list[str] = []
    if h.area_basis == "supply":
        out.append(
            f"내 집 평수는 공급 {num(h.area_m2)}㎡ ÷ {num(PYEONG_M2)} = 공급 {num(v.pyeong)}평이에요."
        )
    else:
        out.append(
            f"내 집 평수는 공급 기준이라 전용 {num(h.area_m2)}㎡(전용 {num(m2(h.area_m2 / PYEONG_M2))}평)에 "
            f"전용 → 공급 환산 {num(house.supply_per_exclusive)}배를 곱해 공급 {num(v.pyeong)}평이에요."
        )
    if pf is not None and v.share is None:
        out.append(f"부자재 · 퍼티 수량(공급 평)은 이 {num(v.qty.floor_py)}평이에요.")
    elif pf is not None:
        out.append(
            f"부자재 · 퍼티 수량(공급 평)은 공급 {num(v.pyeong)}평 × 고른 공간 몫 {num(v.share)} = "
            f"{num(v.qty.floor_py)}평이에요."
        )
    conv = "" if h.area_basis == "supply" else f"(전용 × {num(p.supply_per_exclusive)})"
    out.append(
        f"도배 면적(벽 + 천장)은 공급 {num(m2(sup))}㎡{conv} × {num(p.area_per_supply)} + 방 {v.rooms}개 × "
        f"{num(p.area_per_room)}㎡ = {num(m2(gross))}㎡로 어림했어요(공개 평면도 20곳으로 만든 식). 그중 천장이 "
        f"{int(p.ceiling_share * 100)}%예요."
    )
    if v.share is not None:
        out.append(f"고른 공간 몫 × {num(v.share)} = 벽 {num(wall)}㎡ · 천장 {num(ceiling)}㎡예요.")
    face = {("wall",): "천장은 빼고 벽만", ("ceiling",): "벽은 빼고 천장만"}.get(tuple(h.faces))
    if face:
        out.append(f"{face} 셌어요.")
    out.append(
        f"벽지는 도배 면적 {num(wall_used + ceil_used)}㎡ × 소요량 {num(ratio)} = {num(need)}㎡를 벽지 1평"
        f"({num(PYEONG_M2)}㎡)으로 나눠 {num(paper.qty)} 벽지 평이에요."
    )
    out.append(
        f"품(기능공 1명이 하루 하는 일)은 {', '.join(steps)}이고, 0.5 단위로 올려 {num(q.man_days)}품이에요. "
        "업체 가견적의 인건비 · 식대 수량(품)도 이 값이에요."
    )
    around = "짐 정리 · 보양, 마감 · 청소" if h.occupied else "마감 · 청소"
    out.append(
        f"하루 도배공 {p.crew}명이 나눠 벽지 바르기는 {num(Decimal(half_days(q.man_days, p.crew)) / 2)}일이고, "
        f"{around}를 더해 예상 {num(q.days)}일이에요(반나절 단위)."
    )
    if pf is not None and pf.meal_md is not None:
        meal = next((ln for ln in q.lines if ln.key == "meal"), None)
        if meal is not None and meal.amount is not None:
            out.append(
                f"식대는 {num(q.man_days)}품 × {_won(pf.meal_md)} = {_won(meal.amount)}(공급가)이에요"
                f"({pf.name}: {pf.source})."
            )
    elif pf is not None:
        out.append(
            f"{pf.name}은 식대를 따로 줄로 두지 않아요(일당에 포함으로 봐요). 업체 가견적에 식대 줄이 있으면 "
            "그 업체가 따로 받는 값이에요."
        )
    return out


@dataclass(frozen=True)
class SaveWay:
    """벽지 종류(실크 · 합지)는 그대로 두고 조건 하나만 바꾼 표준견적서."""

    key: str  # own_paper 벽지 직접 구매 · walls_only 천장 빼고 벽만 · empty_home 빈 집에서
    total: int  # 바꾸면 표준견적서 합계(부가세 포함)
    less: int  # 지금 합계보다 줄어드는 돈(부가세 포함)


def save_ways(base: StandardV3, variants: Mapping[str, StandardV3]) -> list[SaveWay]:
    """지금 표준견적서와, 조건 하나만 바꿔 다시 센 표준견적서들의 합계 차(부가세 포함). 줄지 않으면 빼고 많이 주는 순."""
    got = [SaveWay(k, x.quote.total, base.quote.total - x.quote.total) for k, x in variants.items()]
    return sorted((w for w in got if w.less > 0), key=lambda w: -w.less)
