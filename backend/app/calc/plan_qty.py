"""도면 수량: 도면에서 읽은 공간(치수선 = 벽 중심선, mm)으로 도배 · 몰딩 · 걸레받이 · 방문 수량을 낸다.

금액은 만들지 않는다. 금액은 이 수량과 기준 단가로 공정 계산이 만든다.
면적 · 길이는 소수 한 자리(m2), 롤 · 개수는 올림이다.
"""

from dataclasses import dataclass, field
from decimal import ROUND_CEILING, Decimal
from typing import Literal

from app.calc.common import m2

SpaceKind = Literal[
    "room", "living", "kitchen", "entry", "hall", "dress", "bath", "balcony", "utility"
]
# 벽지: 다 바름 · 주방(싱크대 · 타일 벽이라 절반) · 안 바름(욕실 · 발코니 · 다용도실)
Paper = Literal["full", "kitchen", "none"]
# 치수를 읽은 확신: 치수선 그대로 · 치수선 합차 · 그림 비율 추정
Sure = Literal["high", "mid", "low"]
WindowType = Literal["full", "half"]  # 바닥까지 큰 창 · 허리 높이 창
RollKind = Literal["hapji", "silk"]

MM = Decimal(1000)


@dataclass(frozen=True)
class Window:
    w_mm: int
    t: WindowType


@dataclass(frozen=True)
class PlanSpace:
    """직사각형 공간 하나. L자 공간은 두 칸으로 나누고 나눈 경계는 open_mm에 넣는다."""

    id: str
    ko: str
    kind: SpaceKind
    w_mm: int
    d_mm: int
    paper: Paper
    ext_mm: int = 0  # 발코니 확장으로 늘어난 길이
    ext_side: Literal["w", "d"] = "d"
    open_mm: int = 0  # 벽 없이 트인 길이 합
    door_open: int = 0  # 이 공간 벽에 뚫린 문 수 (양쪽 공간에 각각 셈)
    own_door: bool = False  # 출입구에 방문이 있음 = 방문 교체 개수
    windows: tuple[Window, ...] = ()
    sure: Sure = "mid"


@dataclass(frozen=True)
class Plan:
    spaces: tuple[PlanSpace, ...]
    wall_int_mm: int = 180  # 안벽 두께. 치수선에서 빼서 안쪽 길이로 만든다
    wall_given: bool = False  # 도면에 벽 두께가 적혀 있었는지


@dataclass(frozen=True)
class PlanOptions:
    expanded: bool = True  # 발코니 확장 공간으로 셈
    ceiling: bool = True  # 천장도 도배
    ceiling_h: Decimal = Decimal("2.3")  # 천장 높이 m. 도면에 없어 아파트 흔한 값
    kinds: tuple[SpaceKind, ...] | None = None  # 이 공간 종류만 셈 (없으면 전부)


@dataclass(frozen=True)
class Roll:
    ko: str
    w: Decimal  # 폭 m
    length: Decimal  # 한 롤 길이 m


@dataclass(frozen=True)
class PlanRules:
    """수량 가정값 한 벌. 바뀌면 version을 올린다."""

    version: str = "2026.11.1"
    door_w: Decimal = Decimal("0.9")
    door_h: Decimal = Decimal("2.1")
    win_h: dict[str, Decimal] = field(
        default_factory=lambda: {"full": Decimal("2.1"), "half": Decimal("1.2")}
    )
    kitchen_share: Decimal = Decimal("0.5")
    loss: Decimal = Decimal("0.10")  # 자르고 남는 양
    piece_m: Decimal = Decimal("2.4")  # 몰딩 · 걸레받이 한 개 길이
    primer_wall: Decimal = Decimal("1.2")  # 초배지 소요량 (팀 도배 계산과 같음)
    primer_ceiling: Decimal = Decimal("0.8")
    casing_per_door: Decimal = Decimal("10.2")  # 문선: 문 하나 양면 m (팀 목공 계산과 같음)
    strip_extra: Decimal = Decimal("0.1")  # 벽지 한 띠 = 천장 높이 + 10cm
    rolls: dict[str, Roll] = field(
        default_factory=lambda: {
            "hapji": Roll("합지", Decimal("0.53"), Decimal("12.5")),
            "silk": Roll("실크", Decimal("1.06"), Decimal("15.6")),
        }
    )


RULES = PlanRules()


@dataclass(frozen=True)
class SpaceQty:
    id: str
    ko: str
    kind: SpaceKind
    w_m: Decimal  # 안쪽 가로
    d_m: Decimal
    floor_m2: Decimal
    perim_m: Decimal  # 트인 길이를 뺀 둘레
    wall_m2: Decimal
    ceiling_m2: Decimal
    molding_m: Decimal
    base_m: Decimal
    own_door: bool
    papered: bool
    kitchen: bool
    sure: Sure
    ext: bool  # 확장한 공간


@dataclass(frozen=True)
class RollCount:
    kind: RollKind
    ko: str
    size: str  # "1.06m × 15.6m"
    per_roll: int  # 한 롤에서 나오는 벽 띠 수
    rolls: int


@dataclass(frozen=True)
class PlanQty:
    rules_version: str
    options: PlanOptions
    spaces: list[SpaceQty]
    wall_m2: Decimal
    ceiling_m2: Decimal
    paper_m2: Decimal
    primer_m2: Decimal
    rolls: dict[RollKind, RollCount]
    molding_m: Decimal
    molding_pcs: int
    base_m: Decimal
    base_pcs: int
    doors: int
    casing_m: Decimal
    windows_m: Decimal  # 벽지 바르는 공간의 창 폭 합 (커튼박스 길이)
    low: list[str]  # 그림 비율로 추정한 공간 이름 (실측 때 확인)
    assumptions: list[str]


def _up(x: Decimal) -> int:
    return int(x.to_integral_value(rounding=ROUND_CEILING))


@dataclass(frozen=True)
class _Raw:
    """반올림 전 공간 값. 합계는 반올림 전 값으로 더한다."""

    q: SpaceQty
    w: Decimal  # 소수 한 자리로 반올림한 안쪽 가로 (천장 띠 셈에 씀)
    d: Decimal
    wall: Decimal
    ceiling: Decimal
    molding: Decimal
    base: Decimal
    win_w: Decimal  # 창 폭 합


def _space(sp: PlanSpace, plan: Plan, o: PlanOptions, r: PlanRules) -> _Raw:
    if sp.w_mm < 0 or sp.d_mm < 0 or sp.ext_mm < 0 or sp.open_mm < 0 or sp.door_open < 0:
        raise ValueError("공간 치수는 0 이상이어야 해요")
    t = Decimal(plan.wall_int_mm) / MM
    ext_off = Decimal(sp.ext_mm) / MM if (not o.expanded and sp.ext_mm) else Decimal(0)
    w = Decimal(sp.w_mm) / MM - t
    d = Decimal(sp.d_mm) / MM - t
    if sp.ext_side == "w":
        w -= ext_off
    else:
        d -= ext_off
    w, d = max(Decimal(0), w), max(Decimal(0), d)
    # 전부 확장분인 칸(확장 안 하면 없어지는 칸)은 통째로 뺀다
    gone = w < Decimal("0.05") or d < Decimal("0.05")
    out = o.kinds is not None and sp.kind not in o.kinds
    shares = {"full": Decimal(1), "kitchen": r.kitchen_share, "none": Decimal(0)}
    share = Decimal(0) if gone or out else shares[sp.paper]
    h = o.ceiling_h
    perim = max(Decimal(0), 2 * (w + d) - Decimal(sp.open_mm) / MM)
    doors_a = sp.door_open * r.door_w * r.door_h
    win_a = sum((Decimal(x.w_mm) / MM * r.win_h[x.t] for x in sp.windows), Decimal(0))
    full_w = sum((Decimal(x.w_mm) / MM for x in sp.windows if x.t == "full"), Decimal(0))
    wall = max(Decimal(0), perim * h - doors_a - win_a) * share
    ceiling = w * d if share else Decimal(0)
    molding = perim * share
    base = max(Decimal(0), perim - sp.door_open * r.door_w - full_w) * share
    q = SpaceQty(
        id=sp.id,
        ko=sp.ko,
        kind=sp.kind,
        w_m=m2(w),
        d_m=m2(d),
        floor_m2=m2(w * d),
        perim_m=m2(perim),
        wall_m2=m2(wall),
        ceiling_m2=m2(ceiling),
        molding_m=m2(molding),
        base_m=m2(base),
        own_door=sp.own_door and not out,
        papered=share > 0,
        kitchen=sp.paper == "kitchen",
        sure=sp.sure,
        ext=bool(sp.ext_mm) and o.expanded,
    )
    win_w = sum((Decimal(x.w_mm) / MM for x in sp.windows), Decimal(0))
    return _Raw(q, q.w_m, q.d_m, wall, ceiling, molding, base, win_w)


def _rolls(spaces: list[_Raw], kind: RollKind, o: PlanOptions, r: PlanRules) -> RollCount:
    """벽지 롤 수. 벽은 띠(폭) 단위로 세고, 천장은 짧은 변 방향으로 띠를 놓는다."""
    roll = r.rolls[kind]
    h = o.ceiling_h
    per_roll = max(1, int(roll.length // (h + r.strip_extra)))
    raw = Decimal(0)
    for s in spaces:
        if s.wall > 0:
            raw += Decimal(_up(s.wall / (roll.w * h))) / per_roll
        if o.ceiling and s.ceiling > 0:
            long, short = max(s.w, s.d), min(s.w, s.d)
            strips_per_roll = max(1, int(roll.length // (long + r.strip_extra)))
            raw += Decimal(_up(short / roll.w)) / strips_per_roll
    return RollCount(
        kind=kind,
        ko=roll.ko,
        size=f"{roll.w}m × {roll.length}m",
        per_roll=per_roll,
        rolls=_up(raw * (1 + r.loss)),
    )


def from_plan(plan: Plan, o: PlanOptions | None = None, r: PlanRules = RULES) -> PlanQty:
    o = o or PlanOptions()
    if o.ceiling_h <= 0:
        raise ValueError("천장 높이는 0보다 커야 해요")
    raws = [_space(sp, plan, o, r) for sp in plan.spaces]
    paper = [s for s in raws if s.q.papered]
    wall = sum((s.wall for s in paper), Decimal(0))
    ceiling = sum((s.ceiling for s in paper), Decimal(0)) if o.ceiling else Decimal(0)
    molding = sum((s.molding for s in paper), Decimal(0))
    base = sum((s.base for s in paper), Decimal(0))
    doors = sum(1 for s in raws if s.q.own_door)
    pct = int(r.loss * 100)
    return PlanQty(
        rules_version=r.version,
        options=o,
        spaces=[s.q for s in raws],
        wall_m2=m2(wall),
        ceiling_m2=m2(ceiling),
        paper_m2=m2(wall + ceiling),
        primer_m2=m2(wall * r.primer_wall + ceiling * r.primer_ceiling),
        rolls={k: _rolls(paper, k, o, r) for k in ("hapji", "silk")},
        molding_m=m2(molding),
        molding_pcs=_up(molding * (1 + r.loss) / r.piece_m),
        base_m=m2(base),
        base_pcs=_up(base * (1 + r.loss) / r.piece_m),
        doors=doors,
        casing_m=m2(doors * r.casing_per_door),
        windows_m=m2(sum((s.win_w for s in paper), Decimal(0))),
        low=[s.q.ko for s in raws if s.q.sure == "low"],
        assumptions=[
            f"천장 높이 {o.ceiling_h}m(도면에 없어 아파트 흔한 값)",
            f"벽 두께 {plan.wall_int_mm}mm를 치수선에서 빼서 안쪽 길이로 계산"
            + ("(도면 표기)" if plan.wall_given else "(도면에 없어 흔한 값)"),
            (
                f"문 {r.door_w}m × {r.door_h}m, 큰 창 높이 {r.win_h['full']}m · "
                f"작은 창 {r.win_h['half']}m"
            ),
            "주방은 싱크대 · 수납장 · 타일 벽이 있어 벽지 · 몰딩 · 걸레받이를 절반으로",
            f"자르고 남는 양 {pct}% 포함, 몰딩 · 걸레받이 한 개 {r.piece_m}m",
        ],
    )
