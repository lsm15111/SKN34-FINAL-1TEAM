"""시장 기준 금액과 범위: 업체 견적서에 보통 적히는 금액(부가세 별도)을 실견적에서 맞춘 값으로 계산한다.

공공 기준(표준견적서)과 따로 두고, 범위는 '시장 기준 × 실견적 띠'로 낸다.
gap_steps는 공공 기준 → 시장 기준을 값 하나씩 바꿔 가며 달라진 금액을 낸다.
금액은 원 정수(won), 범위는 만 원 단위로 반올림한다.
"""

from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Literal

from app.calc.common import PYEONG_M2, AreaBasis, m2, won
from app.calc.mvp_common import Grade, num
from app.calc.plan_qty import PlanQty

Paper = Literal["silk", "hapji"]
MokItem = Literal["molding", "base", "door", "flatten"]


@dataclass(frozen=True)
class Band:
    """실제 견적 ÷ 시장 기준의 중간 50%(lo~hi) · 80%(lo80~hi80)."""

    lo: Decimal
    hi: Decimal
    lo80: Decimal
    hi80: Decimal
    n: int | None = None  # 근거 견적 수


@dataclass(frozen=True)
class MarketDobae:
    area_factor: dict[Paper, Decimal]  # 공급㎡ → 도배 면적
    ceiling_share: Decimal
    labor_wall: int
    labor_ceiling: int
    labor_mult: dict[Paper, Decimal]  # 시장 생산성 보정
    paper: dict[Paper, int]
    paper_ratio: Decimal
    sub_per_py: dict[Paper, int]  # 초배 · 풀 · 부자재 원/공급평
    occupied_mult: Decimal
    balcony_factor: Decimal
    min_job: int
    fixed: int
    band: dict[Paper, Band]
    band_plan: dict[Paper, Band]  # 도면 면적일 때
    checked: dict[Paper, int]


@dataclass(frozen=True)
class MarketExtra:
    key: str
    name: str
    per: Literal["곳", "식"]  # 곳 = 곳 수만큼, 식 = 한 번
    lo: int
    hi: int
    n: int  # 근거 줄 수


@dataclass(frozen=True)
class MarketMokgong:
    molding_per_py: Decimal
    base_per_py: Decimal
    molding_m: int  # 원/m (시공 + 자재)
    base_m: int
    base_only_min: int
    door_set: int
    door_leaf: int
    doors_by_py: tuple[int, ...]  # 평 경계 (28, 38)
    doors_count: tuple[int, ...]  # 경계마다 문 수 (4, 5, 6)
    flatten_per_m2: int
    removal_lump: int
    overhead: Decimal
    band: Band
    checked: int
    extras: tuple[MarketExtra, ...]
    casing9_with_door: tuple[int, int]  # 9mm 문선 문당, 문 교체와 함께면 차액만
    casing9_alone: tuple[int, int]


@dataclass(frozen=True)
class MarketBook:
    version: str
    dobae: MarketDobae
    mokgong: MarketMokgong


@dataclass(frozen=True)
class MarketLine:
    key: str
    name: str
    qty: Decimal | None
    unit: str
    unit_price: int | None
    amount: int
    note: str


@dataclass(frozen=True)
class MarketResult:
    trade: Literal["dobae", "mokgong"]
    paper: Paper | None
    lines: list[MarketLine]
    supply: int  # 시장 기준 (부가세 별도)
    lo: int
    hi: int
    band: Band
    n: int  # 근거 견적 수
    version: str


@dataclass(frozen=True)
class MarketDobaeInput:
    area_m2: Decimal
    grade: Grade
    area_basis: AreaBasis = "supply"
    include_ceiling: bool = True
    occupied: bool = False
    balcony_ext: bool = False
    plan: PlanQty | None = None
    plan_name: str = ""


@dataclass(frozen=True)
class MarketMokgongInput:
    area_m2: Decimal
    items: tuple[MokItem, ...]
    area_basis: AreaBasis = "supply"
    doors: int = 0  # 0이면 평형으로 어림
    door_frame: bool = True
    plan: PlanQty | None = None
    plan_name: str = ""
    extra_amount: int = 0  # 정해진 가격 목공 항목 합 (공공 기준과 같은 금액을 더한다)


SUPPLY_PER_EXCLUSIVE = Decimal("1.2")


def _r10k(x: Decimal) -> int:
    return won(x / 10000) * 10000


def _supply(area: Decimal, basis: AreaBasis) -> Decimal:
    if area <= 0:
        raise ValueError("면적은 0보다 커야 해요")
    return area if basis == "supply" else area * SUPPLY_PER_EXCLUSIVE


def doors_for(py: Decimal, bounds: tuple[int, ...], counts: tuple[int, ...]) -> int:
    for b, n in zip(bounds, counts, strict=False):
        if py < b:
            return n
    return counts[-1]


def dobae(inp: MarketDobaeInput, book: MarketBook, p: MarketDobae | None = None) -> MarketResult:
    p = p or book.dobae
    g: Paper = "hapji" if inp.grade == "economy" else "silk"
    supply_m2 = _supply(inp.area_m2, inp.area_basis)
    py = supply_m2 / PYEONG_M2
    gross = supply_m2 * p.area_factor[g]
    if inp.balcony_ext:
        gross *= p.balcony_factor
    ceiling = m2(gross * p.ceiling_share)
    wall = m2(m2(gross) - ceiling)
    if inp.plan:
        wall, ceiling = m2(inp.plan.wall_m2), m2(inp.plan.ceiling_m2)
    ceil_used = ceiling if inp.include_ceiling else Decimal(0)
    paper_area = m2(wall + ceil_used)
    paper_qty = m2(paper_area * p.paper_ratio)
    lw, lc = won(p.labor_wall * p.labor_mult[g]), won(p.labor_ceiling * p.labor_mult[g])
    if inp.plan:
        wall_note = f"도면 {inp.plan_name}에서 잰 벽 면적"
        ceil_note = "도면에서 잰 천장 면적"
    else:
        wall_note = (
            f"도배 면적 = 공급 {num(m2(supply_m2))}㎡ × {num(p.area_factor[g])} (롤 수 관행)"
        )
        ceil_note = f"천장 = 도배 면적 × {num(p.ceiling_share)}"
    lines = [
        MarketLine("wall", "벽 도배 시공", wall, "㎡", lw, won(wall * lw), wall_note),
        MarketLine(
            "ceiling", "천장 도배 시공", ceil_used, "㎡", lc, won(ceil_used * lc), ceil_note
        ),
        MarketLine(
            "paper",
            f"벽지 ({'합지' if g == 'hapji' else '실크'})",
            paper_qty,
            "㎡",
            p.paper[g],
            won(paper_qty * p.paper[g]),
            f"바를 면적 × {num(p.paper_ratio)}",
        ),
        MarketLine(
            "sub",
            "초배 · 풀 · 부자재",
            m2(py),
            "평",
            p.sub_per_py[g],
            won(py * p.sub_per_py[g]),
            "공급평당",
        ),
    ]
    if p.fixed:
        note = "집 크기와 상관없이 한 번"
        lines.append(MarketLine("fixed", "출장 · 준비 · 보양", None, "식", None, p.fixed, note))
    if inp.occupied:
        labor = lines[0].amount + lines[1].amount
        note = f"노무비의 {num(p.occupied_mult * 100)}%"
        amount = won(labor * p.occupied_mult)
        lines.append(MarketLine("occupied", "짐 있는 집 작업", None, "식", None, amount, note))
    supply = sum(ln.amount for ln in lines)
    if supply < p.min_job:
        gap = p.min_job - supply
        lines.append(MarketLine("min", "최소 작업 금액 맞춤", None, "식", None, gap, ""))
        supply = p.min_job
    band = p.band_plan[g] if inp.plan else p.band[g]
    return MarketResult(
        trade="dobae",
        paper=g,
        lines=lines,
        supply=supply,
        lo=_r10k(supply * band.lo),
        hi=_r10k(supply * band.hi),
        band=band,
        n=band.n or p.checked[g],
        version=book.version,
    )


def mokgong(
    inp: MarketMokgongInput, book: MarketBook, p: MarketMokgong | None = None
) -> MarketResult:
    p = p or book.mokgong
    supply_m2 = _supply(inp.area_m2, inp.area_basis)
    py = supply_m2 / PYEONG_M2
    plan, items = inp.plan, set(inp.items)
    lines: list[MarketLine] = []
    if "molding" in items:
        length = m2(plan.molding_m) if plan else m2(py * p.molding_per_py)
        note = (
            f"도면 {inp.plan_name}에서 잰 천장 둘레"
            if plan
            else f"공급 {num(m2(py))}평 × {num(p.molding_per_py)}m"
        )
        lines.append(
            MarketLine(
                "molding",
                "천장 몰딩 (시공 + 자재)",
                length,
                "m",
                p.molding_m,
                won(length * p.molding_m),
                note,
            )
        )
    if "base" in items:
        length = m2(plan.base_m) if plan else m2(py * p.base_per_py)
        note = (
            f"도면 {inp.plan_name}에서 잰 바닥 둘레"
            if plan
            else f"공급 {num(m2(py))}평 × {num(p.base_per_py)}m"
        )
        lines.append(
            MarketLine(
                "base",
                "걸레받이 (시공 + 자재)",
                length,
                "m",
                p.base_m,
                won(length * p.base_m),
                note,
            )
        )
    if "door" in items:
        n = inp.doors or doors_for(py, p.doors_by_py, p.doors_count)
        price = p.door_set if inp.door_frame else p.door_leaf
        name = "방문 (문틀 · 문짝 · 문선)" if inp.door_frame else "방문 (문짝만)"
        note = "" if inp.doors else "방 + 욕실 수로 어림"
        lines.append(MarketLine("door", name, Decimal(n), "개", price, n * price, note))
    if "flatten" in items:
        a = m2(supply_m2 / SUPPLY_PER_EXCLUSIVE * Decimal("0.3"))
        amount = won(a * p.flatten_per_m2)
        lines.append(
            MarketLine("flatten", "천장 평탄화", a, "㎡", p.flatten_per_m2, amount, "전용 × 0.3")
        )
    if p.removal_lump > 0 and items:
        name, note = "철거 · 폐기물 · 양중", "시장 관행 한 번"
        lines.append(MarketLine("removal", name, None, "식", None, p.removal_lump, note))
    supply = sum(ln.amount for ln in lines)
    if p.overhead:
        o = won(supply * p.overhead)
        lines.append(MarketLine("overhead", "공과잡비 · 이윤", None, "식", None, o, ""))
        supply += o
    if inp.items == ("base",) and supply < p.base_only_min:
        gap = p.base_only_min - supply
        lines.append(MarketLine("min", "최소 작업 금액 맞춤", None, "식", None, gap, ""))
        supply = p.base_only_min
    lo, hi = _r10k(supply * p.band.lo), _r10k(supply * p.band.hi)
    # 정해진 가격 항목은 공공 기준과 같은 금액을 더한다 (범위 폭에는 넣지 않는다)
    x = inp.extra_amount
    if x:
        note = "공공 기준과 같은 정해진 단가"
        lines.append(MarketLine("extras", "그 밖의 목공 (정해진 가격)", None, "식", None, x, note))
        supply, lo, hi = supply + x, _r10k(Decimal(lo + x)), _r10k(Decimal(hi + x))
    return MarketResult(
        trade="mokgong",
        paper=None,
        lines=lines,
        supply=supply,
        lo=lo,
        hi=hi,
        band=p.band,
        n=p.checked,
        version=book.version,
    )


@dataclass(frozen=True)
class ExtrasRange:
    lo: int
    hi: int
    notes: list[str]


def _man(x: int) -> str:
    return f"{num(Decimal(x) / 10000)}만"


def extras_range(
    p: MarketMokgong, picks: dict[str, int], casing_doors: int = 0, with_door: bool = False
) -> ExtrasRange:
    """받은 견적 맞춰 보기: 고른 흔한 추가 항목(picks = key → 곳 수)과 9mm 문선의 범위를 더한다."""
    lo = hi = 0
    notes = []
    for e in p.extras:
        c = picks.get(e.key, 0)
        if not c:
            continue
        k = c if e.per == "곳" else 1
        lo, hi = lo + e.lo * k, hi + e.hi * k
        where, each = (f" {k}곳", "곳당 ") if e.per == "곳" else ("", "")
        few = ", 근거 적음" if e.n < 4 else ""
        notes.append(f"{e.name}{where}: {each}{_man(e.lo)}~{_man(e.hi)} 원 (실견적 {e.n}줄{few})")
    if casing_doors > 0:
        a, b = p.casing9_with_door if with_door else p.casing9_alone
        lo, hi = lo + a * casing_doors, hi + b * casing_doors
        tail = " (문 교체 값에 더 붙는 만큼)" if with_door else ""
        notes.append(f"9mm 문선 {casing_doors}개: 문당 {_man(a)}~{_man(b)} 원{tail}")
    return ExtrasRange(lo, hi, notes)


@dataclass(frozen=True)
class GapStep:
    key: str
    name: str
    why: str
    d: int  # 이 값만 시장으로 바꿨을 때 달라진 금액


@dataclass(frozen=True)
class Gap:
    start: int  # 표준견적서 합계 (부가세 포함)
    steps: list[GapStep]
    end: int  # 시장 기준 (부가세 별도)


def gap_steps(
    inp: MarketDobaeInput | MarketMokgongInput,
    book: MarketBook,
    public_eq: MarketDobae | MarketMokgong,
    order: tuple[tuple[str, str, str], ...],
    pub_supply: int,
    pub_vat: int,
) -> Gap:
    """공공 기준 → 시장 기준. public_eq는 공공 기준과 같은 값으로 맞춘 시장 계산 값 한 벌,
    order는 (바꿀 칸, 이름, 이유)를 바꾸는 순서대로."""
    is_dobae = isinstance(inp, MarketDobaeInput)
    target = book.dobae if is_dobae else book.mokgong

    def run(p):
        return dobae(inp, book, p) if is_dobae else mokgong(inp, book, p)  # type: ignore[arg-type]

    why_vat = "표준견적서는 부가세 포함, 업체 견적은 보통 부가세 별도로 적어요."
    steps = [GapStep("vat", "부가세", why_vat, -pub_vat)]
    cur = public_eq
    prev = run(cur).supply
    if abs(prev - pub_supply) >= 1000:
        why = "시장 견적처럼 줄을 묶어 다시 계산하면서 생긴 작은 차이예요."
        steps.append(GapStep("lines", "줄 묶음", why, prev - pub_supply))
    for key, name, why in order:
        cur = replace(cur, **{key: getattr(target, key)})
        s = run(cur).supply
        if key == "labor_mult" and is_dobae and inp.grade != "economy":
            why = "실크는 시장 도배사 하루 작업량이 품셈보다 조금 많아서 시공비가 약간 낮아요."
        if abs(s - prev) >= 1000:
            steps.append(GapStep(key, name, why, s - prev))
        prev = s
    return Gap(pub_supply + pub_vat, steps, prev)
