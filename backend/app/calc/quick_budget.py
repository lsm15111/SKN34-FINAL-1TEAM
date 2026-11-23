"""빠른 예산: 질문 3개(평형 · 바꿀 것 · 도배 유형)로 시장 범위(부가세 포함)를 낸다.

- 모르는 칸(None)은 실견적에서 흔한 값으로 채우고, 채운 값은 assumed에 적는다
- 도배 유형을 모르면 기본형으로 계산하고 저가형 범위를 alt로 따로 낸다(범위 하나에 섞지 않는다)
- 실크벽지 종류(papers)를 넘기면 도배 유형 대신 벽지 종류를 묻는다. 모르면 첫 종류로 계산하고
  나머지 종류 범위를 alt로 낸다
- '더 정확히' 질문(asks)은 답에 따라 범위가 가장 크게 달라지는 칸부터 늘어놓는다
금액은 market_band가 만들고, 여기서는 부가세를 붙여 만 원 단위로 맞춘다. DB · HTTP · 시계 없음.
"""

from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Literal

from app.calc import market_band
from app.calc.common import PYEONG_M2, SUPPLY_PER_EXCLUSIVE, VAT_RATE, AreaBasis, won
from app.calc.plan_qty import PlanQty
from app.calc.precise_common import Grade, SilkPaper, num

DoorMode = Literal["none", "leaf", "frame"]
DOOR_KO = {"none": "안 바꿔요", "leaf": "문짝만", "frame": "문틀까지"}


@dataclass(frozen=True)
class QuickIn:
    area_m2: Decimal
    area_basis: AreaBasis = "supply"
    dobae: bool = True
    molding: bool = False
    base: bool = False
    door: DoorMode | None = None  # 모름 → 안 바꿈
    grade: Grade | None = None  # 모름 → 기본형
    ceiling: bool | None = None  # 모름 → 포함
    occupied: bool | None = None  # 모름 → 빈 집
    paper: SilkPaper | None = None  # 고른 실크벽지 (papers가 있을 때만)
    papers: tuple[
        SilkPaper, ...
    ] = ()  # 고를 수 있는 실크벽지. 비면 도배 유형(합지 · 실크)으로 묻는다
    plan: PlanQty | None = None  # 대표 집 카드(실제 평면)를 골랐으면 그 수량
    plan_name: str = ""
    part: bool = False  # 일부 방만 (plan이 고른 공간만 센 수량)


@dataclass(frozen=True)
class TradeRange:
    trade: Literal["dobae", "mokgong"]
    lo: int
    hi: int
    n: int  # 근거 실견적 수


@dataclass(frozen=True)
class Choice:
    value: str
    label: str
    lo: int
    hi: int


@dataclass(frozen=True)
class Ask:
    key: Literal["door", "ceiling", "occupied", "grade", "paper"]
    q: str
    choices: tuple[Choice, ...]
    spread: int  # 답에 따라 범위 끝이 가장 크게 달라지는 만큼
    note: str = ""


@dataclass(frozen=True)
class QuickOut:
    lo: int
    hi: int
    trades: tuple[TradeRange, ...]
    assumed: tuple[str, ...]
    alt: Choice | None
    asks: tuple[Ask, ...]
    version: str


def _incl(x: int) -> int:
    """부가세 별도 → 포함, 만 원 단위"""
    return won(Decimal(x) * (1 + VAT_RATE) / 10000) * 10000


def _doors(inp: QuickIn, book: market_band.MarketBook) -> tuple[int, str]:
    if inp.plan and inp.plan.doors:
        return inp.plan.doors, f"도면 {inp.plan_name}에서 센"
    supply = inp.area_m2 if inp.area_basis == "supply" else inp.area_m2 * SUPPLY_PER_EXCLUSIVE
    p = book.mokgong
    return market_band.doors_for(
        supply / PYEONG_M2, p.doors_by_py, p.doors_count
    ), "방 + 욕실로 어림한"


def _run(inp: QuickIn, book: market_band.MarketBook) -> tuple[TradeRange, ...]:
    out = []
    if inp.dobae:
        r = market_band.dobae(
            market_band.MarketDobaeInput(
                area_m2=inp.area_m2,
                grade=inp.grade or "basic",
                area_basis=inp.area_basis,
                include_ceiling=inp.ceiling is not False,
                occupied=bool(inp.occupied),
                plan=inp.plan,
                plan_name=inp.plan_name,
                silk=_silk(inp),
            ),
            book,
        )
        out.append(TradeRange("dobae", _incl(r.lo), _incl(r.hi), r.n))
    items: list[market_band.MokItem] = []
    if inp.molding:
        items.append("molding")
    if inp.base:
        items.append("base")
    door = inp.door or "none"
    if door != "none":
        items.append("door")
    if items:
        r = market_band.mokgong(
            market_band.MarketMokgongInput(
                area_m2=inp.area_m2,
                items=tuple(items),
                area_basis=inp.area_basis,
                doors=_doors(inp, book)[0],
                door_frame=door == "frame",
                plan=inp.plan,
                plan_name=inp.plan_name,
            ),
            book,
        )
        out.append(TradeRange("mokgong", _incl(r.lo), _incl(r.hi), r.n))
    return tuple(out)


def _silk(inp: QuickIn) -> SilkPaper | None:
    if not inp.papers:
        return None
    return inp.paper or inp.papers[0]


def _total(ts: tuple[TradeRange, ...]) -> tuple[int, int]:
    return sum(t.lo for t in ts), sum(t.hi for t in ts)


def _choices(inp: QuickIn, book, key: str, opts: list[tuple[object, str]]) -> tuple[Choice, ...]:
    return tuple(
        Choice(str(v).lower(), label, *_total(_run(replace(inp, **{key: v}), book)))
        for v, label in opts
    )


def quick(inp: QuickIn, book: market_band.MarketBook) -> QuickOut:
    if not (inp.dobae or inp.molding or inp.base or inp.door not in (None, "none")):
        raise ValueError("바꿀 것을 하나 이상 골라 주세요")
    supply = inp.area_m2 if inp.area_basis == "supply" else inp.area_m2 * SUPPLY_PER_EXCLUSIVE
    py = supply / PYEONG_M2
    assumed = []
    if inp.plan:
        what = "고른 공간만" if inp.part else "집 전체"
        assumed.append(f"도면 {inp.plan_name}에서 잰 면적 · 길이 ({what})")
    else:
        assumed.append(f"공급 {num(py.quantize(Decimal('0.1')))}평으로 어림한 면적 · 길이")
    silk = bool(inp.papers)
    if inp.dobae and silk and inp.paper is None:
        assumed.append(f"벽지는 {inp.papers[0].name}로 계산")
    elif inp.dobae and not silk and inp.grade is None:
        assumed.append("도배는 기본형(실크)으로 계산")
    if inp.dobae and inp.ceiling is None:
        assumed.append("천장 도배 포함")
    if inp.occupied is None:
        assumed.append("빈 집에서 공사")
    if inp.door is None:
        assumed.append("방문은 안 바꿈")
    if inp.door in ("leaf", "frame"):
        n, how = _doors(inp, book)
        assumed.append(f"방문 {n}짝 ({how} 개수)")
    if inp.dobae:
        assumed.append("기존 벽지 철거 · 폐기물은 실측 후")

    ts = _run(inp, book)
    lo, hi = _total(ts)
    alt = None
    if inp.dobae and silk and inp.paper is None and len(inp.papers) > 1:
        other = inp.papers[1]
        alt = Choice(other.key, f"{other.name}면", *_total(_run(replace(inp, paper=other), book)))
    elif inp.dobae and not silk and inp.grade is None:
        alt = Choice(
            "economy", "저가형(합지)이면", *_total(_run(replace(inp, grade="economy"), book))
        )

    asks: list[Ask] = []
    if inp.door is None:
        asks.append(
            Ask("door", "방문도 바꿔요?", _choices(inp, book, "door", list(DOOR_KO.items())), 0)
        )
    if inp.dobae and inp.ceiling is None:
        opts = [(True, "천장도 해요"), (False, "벽만 해요")]
        asks.append(Ask("ceiling", "천장도 도배해요?", _choices(inp, book, "ceiling", opts), 0))
    if inp.dobae and silk and inp.paper is None:
        choices = tuple(
            Choice(s.key, s.name, *_total(_run(replace(inp, paper=s), book))) for s in inp.papers
        )
        asks.append(Ask("paper", "실크벽지 종류를 정했어요?", choices, 0))
    elif inp.dobae and not silk and inp.grade is None:
        opts = [("basic", "기본형(실크)"), ("economy", "저가형(합지)")]
        asks.append(Ask("grade", "도배 유형을 정했어요?", _choices(inp, book, "grade", opts), 0))
    if inp.occupied is None:
        opts = [(False, "빈 집이에요"), (True, "살면서 해요")]
        note = "짐을 옮기며 하면 기간이 늘 수 있어요. 기간은 공정표에서 계산해요"
        asks.append(
            Ask("occupied", "살면서 공사해요?", _choices(inp, book, "occupied", opts), 0, note)
        )
    asks = [
        replace(a, spread=max(max(abs(c.lo - lo), abs(c.hi - hi)) for c in a.choices)) for a in asks
    ]
    asks.sort(key=lambda a: -a.spread)
    return QuickOut(lo, hi, ts, tuple(assumed), alt, tuple(asks), book.version)
