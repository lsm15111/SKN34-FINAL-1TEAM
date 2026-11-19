"""도배 표준견적서와 예상 공정표.

금액은 원 정수이고 반올림은 won() 한 곳에서만 한다. 면적은 ㎡ 소수 한 자리, 품은 0.5 단위로 올린다.
실측 전이라 면적은 평형에서 가정값으로 추정하고, 그 가정은 결과의 assumptions에 그대로 남긴다.

- quote(): 옛 표준견적서(도배지 ㎡ × 공공 재료비). v2 업체 단가표 예시 · 다른 계산이 그대로 쓴다.
- quote_v3() · standard_v3(): v3 표준견적서(D07 A · D02 A). 도배지 줄만 '벽지 평 × 시장 평균 가격'으로 바꾸고,
  부분 공사는 고른 공간 몫으로 벽 · 천장 면적을 줄인다. 가견적 v3 수량(QtyV3)도 같이 만든다.
- 단가 판에 회귀 계수(area_per_supply · area_per_room)가 있으면 집 전체 도배 면적을
  '공급㎡ × 계수 + 방 개수 × ㎡'로 센다(whole-house-area.md 방안 4). 없으면 옛 '면적 × area_factor'.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal
from typing import Literal, Protocol

from app.calc.common import (
    BASIS_LABEL,
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


def paper_py(paper_m2: Decimal) -> Decimal:
    """도배지 소요량 ㎡ → 벽지 평 (0.1평 반올림, 벽지 1평 = 3.3058㎡)"""
    return m2(paper_m2 / PYEONG_M2)


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


def quote_v3(inp: DobaeV3Input, p: DobaePrices, paper: PaperPrice) -> DobaeQuote:
    """v3 표준견적서. 도배지 줄 = 벽지 평(도배 면적 × 소요량 ÷ 3.3058) × 시장 평균 가격(basis market).
    부분 공사면 벽 · 천장 면적에 공간 몫을 곱하고, 고르지 않은 면은 '안 함'(수량 · 금액 없음)."""
    if inp.area_m2 <= 0:
        raise ValueError("면적은 0보다 커야 해요")
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

    wall_amt = won(wall_used * p.labor_wall)
    ceil_amt = won(ceil_used * p.labor_ceiling)
    paper_qty = paper_py(m2(paper_area * p.paper_ratio))
    primer_qty = m2(wall_used * p.primer_wall_ratio + ceil_used * p.primer_ceiling_ratio)
    lines = [
        Line(
            "wall",
            "벽 도배 시공 (풀 포함)",
            wall if do_wall else None,
            "㎡",
            p.labor_wall,
            wall_amt if do_wall else None,
            "included" if do_wall else "excluded",
            src["wall"],
        ),
        Line(
            "ceiling",
            "천장 도배 시공 (풀 포함)",
            ceiling if do_ceil else None,
            "㎡",
            p.labor_ceiling,
            ceil_amt if do_ceil else None,
            "included" if do_ceil else "excluded",
            src["ceiling"],
        ),
        Line(
            "paper",
            f"{paper.name} 시장 평균 가격",
            paper_qty,
            "벽지 평",
            paper.per_py,
            won(paper_qty * paper.per_py),
            "included",
            _paper_source(paper),
            "market",
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

    md = wall_used * p.md_wall + ceil_used * p.md_ceiling
    if inp.occupied:
        md = md / p.occupied_output
    man_days = m2(half_up(md))  # 0.5 단위 값을 소수 한 자리 꼴로 (5 → 5.0, 값은 그대로)
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
    assumptions = [
        area_note,
        f"천장은 도배 면적의 {int(p.ceiling_share * 100)}%로 잡았어요.",
        f"도배지는 {paper.name} 시장 평균 가격으로 셌어요(벽지 1평 = 3.3058㎡).",
        f"하루 도배공 {p.crew}명이 들어가는 것으로 기간을 잡았어요.",
    ]
    if inp.share is not None:  # 글: copy-fixes CF-45
        assumptions.insert(
            0, "부분 공사는 고른 공간의 넓이를 어림해 계산했어요. 실측 뒤 업체 견적서로 확정해요."
        )
    if inp.balcony_ext and p.balcony_factor != 1:
        assumptions.append(f"발코니 확장은 도배 면적을 {p.balcony_factor}배로 잡았어요.")
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


def standard_v3(
    h: HomeV3,
    p: DobaePrices,
    paper: PaperPrice,
    shares: SpaceShares | RoomSpaceShares,
    house: HouseRules,
) -> StandardV3:
    """기본 정보 → v3 표준견적서 + 가견적 수량. 표준견적서 저장 · 손님 계산 · 가견적이 같은 값을 쓴다.
    부분 공사 몫은 방 개수에 맞는 표로 센다(방 개수에 없는 방 칩이면 ValueError)."""
    by_rooms = p.area_per_supply is not None
    rooms = rooms_of(h, p) if by_rooms else None
    share = None
    if h.scope == "partial":
        table = shares.for_rooms(rooms or 3)
        unknown = [k for k in dict.fromkeys(h.spaces) if k not in table.share]
        if unknown and isinstance(shares, RoomSpaceShares):
            raise ValueError("방 개수보다 많은 방을 골랐어요")
        share = share_of(h.spaces, table)
    q = quote_v3(
        DobaeV3Input(
            h.area_m2, h.area_basis, h.grade, h.occupied, h.faces, share, h.balcony_ext, rooms
        ),
        p,
        paper,
    )
    py = house_pyeong(None, h.area_m2, h.area_basis, house)
    paper_line = next(ln for ln in q.lines if ln.key == "paper")
    qty = QtyV3(
        floor_py=py if share is None else m2(py * share),
        paper_py=paper_line.qty or Decimal(0),
        man_day=q.man_days,
    )
    share_ver = shares.version if share is not None else None
    return StandardV3(q, py, share, share_ver, paper.version, qty, rooms)
