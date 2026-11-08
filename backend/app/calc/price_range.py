"""예상 범위: 이 집 금액이 대부분(10~90%) 들어갈 구간과 그 폭을 만든 이유.

폭은 세 가지에서 나온다.
- 수량: 면적 · 길이를 얼마나 정확히 아는지. 가정값 → 평형대 → 면적 입력 → 고객이 잼 → 업체가 잼(실측).
- 단가: 업체마다 다른 값. 업체 단가를 모르면 시장 흩어짐, 가견적(업체 단가를 앎)이면 실측 보정만 남는다.
- 조건: '실측 후' 줄(철거 · 폐기물 · 짐 이동 …). 하기로 정했으면 늘 더하고, 모르면 '할 확률' p만큼 섞는다.

본체(수량 · 단가)는 로그 정규로 보고 σ² = σ수량² + σ단가²로 묶는다(둘은 독립으로 본다).
수량은 줄을 수량 근거(면적 · 둘레 · 천장 · 문)로 묶는다. 같은 근거의 줄은 같이 틀리고(금액 비율로 σ를 더함),
다른 근거끼리는 독립이다(제곱합). 일부 공간만 고르면 '고른 공간 몫'(calc.spaces)도 가정값이라 그 σ를 따로 더한다.
조건 줄 금액은 [하한, 상한] 균등으로 보고 칸으로 나눠 본체와 섞는다.
여러 공정의 합계는 본체를 평균 · 분산이 같은 로그 정규 하나로 묶고(공정끼리 상관 trade_corr), 조건 줄은 모두 섞는다.
작은 공사는 출장 · 최소 인건비 같은 고정비가 면적에 비례해 줄지 않는다. 그래서 중심에 고정비 × (1 − 공사 몫)을
더하고(집 전체 단가에는 이미 녹아 있음), 업체 단가 흩어짐도 공사가 작을수록 넓힌다(small_sigma).
구간은 섞은 분포의 10% · 50% · 90% 지점을 이분법으로 찾는다. 무작위를 쓰지 않아 같은 입력이면 같은 구간이다.
금액은 원 정수이고, 보이는 끝값은 만 원 단위로 하한 내림 · 중간 반올림 · 상한 올림한다.
"""

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from math import erf, exp, log, sqrt
from typing import Literal

Precision = Literal["guess", "band", "area", "self", "visit"]
# 덜 정확한 것 → 더 정확한 것. 다음에 물을 것을 고를 때 한 단계 위를 본다
LADDER: tuple[Precision, ...] = ("guess", "band", "area", "self", "visit")
CondState = Literal["yes", "open"]

# 줄 키 → 수량 근거. 같은 근거의 줄은 같이 틀린다(도배는 모두 도배 면적에서 나온다)
QTY_DRIVER: dict[str, dict[str, str]] = {
    "dobae": {k: "area" for k in ("wall", "ceiling", "paper", "primer", "occupied")},
    "mokgong": {
        **{k: "flat" for k in ("frame", "board", "ceiling_mat")},
        **{k: "door" for k in ("door", "casing", "door_mat")},
        **{k: "edge" for k in ("molding", "molding_mat", "base", "base_mat")},
    },
}

MAN = Decimal(10_000)
GRID = 8  # 조건 줄 금액 [하한, 상한]을 나누는 칸 수
STEPS = 48  # 분위수 이분법 반복 수 (상한 수천만 원 ÷ 2^48 → 1원보다 훨씬 작다)


@dataclass(frozen=True)
class CondRule:
    """'실측 후' 줄 하나의 시장 범위(부가세 빼고). per가 lump면 한 번(식), qty면 수량(㎡ · m · 개)당.
    p는 할지 모를 때 쓰는 '할 확률' 사전값이다. min_scale이 있으면 한 번(식) 금액도 공사 크기(고른 공간 몫)를
    따라 줄이되 이 비율 밑으로는 줄이지 않는다(폐기물 · 짐 이동처럼 양에 따라 늘지만 최소 한 번은 드는 것)."""

    per: Literal["lump", "qty"]
    low: int
    high: int
    p: Decimal
    source: str
    min_scale: Decimal | None = None

    def __post_init__(self) -> None:
        if not 0 <= self.low <= self.high:
            raise ValueError("조건 줄 범위는 0 ≤ 하한 ≤ 상한이어야 해요")
        if not 0 <= self.p <= 1:
            raise ValueError("할 확률은 0~1이어야 해요")
        if self.min_scale is not None and not 0 < self.min_scale <= 1:
            raise ValueError("최소 비율은 0보다 크고 1 이하여야 해요")


@dataclass(frozen=True)
class RangeRules:
    """범위 계산에 쓰는 가정값 한 벌. refprice가 버전별로 만들어 넘긴다.
    price_* · visit_sigma · min_job의 키는 공정(dobae) 또는 공정.등급(dobae.basic). 등급 키가 먼저다."""

    version: str
    z: Decimal  # 1.2816 = 10~90% 구간
    qty_sigma: Mapping[str, Mapping[str, Mapping[str, Decimal]]]  # 공정 → 수량 근거 → 정밀도 → σ
    price_sigma: Mapping[str, Decimal]  # 업체 단가 흩어짐 σ
    price_center: Mapping[str, Decimal]  # 시장 중심 ÷ 공공 기준
    visit_sigma: Mapping[str, Decimal]  # 가견적 → 실측 견적 보정 σ
    min_job: Mapping[str, int]  # 작은 공사도 드는 최소 금액(부가세 빼고)
    conds: Mapping[str, Mapping[str, CondRule]]  # 공정 → '실측 후' 줄 키 → 범위
    vat_rate: Decimal
    sources: Mapping[str, str]
    trade_corr: Decimal = Decimal("0.5")  # 합계 범위: 공정끼리 본체가 같이 움직이는 정도(0~1)
    # 작은 공사 고정비(부가세 빼고, 원). 키는 공정 · 공정.등급 · mokgong.door(방문만). 집 전체 단가에 녹아 있는 몫
    fixed_cost: Mapping[str, int] = field(default_factory=dict)
    # (공사 몫 상한, 업체 단가 σ 배수) 작은 것부터. 공사 몫이 상한 미만이면 그 배수를 쓴다
    small_sigma: tuple[tuple[Decimal, Decimal], ...] = ()


@dataclass(frozen=True)
class RangeInput:
    trade: str
    amounts: Mapping[str, int]  # 합계에 들어간 줄 키 → 금액(부가세 빼고). 표준견적서 또는 가견적
    precision: Mapping[str, Precision]  # 수량 근거 → 정밀도
    grade: str | None = None  # 도배 등급(economy · basic). 시장 중심 · 흩어짐을 등급별로 고른다
    conds: Mapping[str, CondState] = field(default_factory=dict)  # '실측 후' 줄 → 하기로 함 · 모름
    cond_qty: Mapping[str, Decimal] = field(default_factory=dict)  # per=qty 줄의 수량
    cond_p: Mapping[str, Decimal] = field(default_factory=dict)  # 모름일 때 할 확률(사전값 대신)
    vendor_priced: bool = False  # 가견적이면 True(업체 단가를 앎)
    exempt: bool = False  # 면세 업체
    share_sigma: Mapping[str, Decimal] = field(default_factory=dict)  # 수량 근거 → 고른 공간 몫 σ
    # 집 전체 대비 공사 크기(고른 공간 몫). 고정비 · 작은 공사 흩어짐 · min_scale 조건 줄에 쓴다
    job_share: Decimal = Decimal(1)
    fixed_key: str | None = None  # 고정비 키(RangeRules.fixed_cost). 없으면 고정비를 더하지 않는다


@dataclass(frozen=True)
class Part:
    """구간 폭을 만든 이유 하나. share는 '이걸 알면 줄어드는 폭(기대값)'의 몫이다."""

    driver: str  # qty:area · qty:edge · share:area · price · visit · cond:removal …
    share: Decimal  # 0~1, 소수 둘째 자리
    better: Precision | None = None  # 수량: 한 단계 더 알면 되는 정밀도
    low_if: int | None = None  # 수량은 한 단계 더 알 때, 단가는 가견적을 받을 때, 조건은 하게 될 때
    high_if: int | None = None
    low_if_no: int | None = None  # 조건: 안 하게 될 때
    high_if_no: int | None = None


@dataclass(frozen=True)
class PriceRange:
    version: str
    trade: str
    low: int  # 부가세 포함, 만 원 단위
    mid: int
    high: int
    extra_max: int  # 모르는 '실측 후' 줄을 다 하게 되면 더 들 수 있는 최대(부가세 포함). 구간과 따로 보인다
    sigma: Decimal  # 본체(수량 · 단가) σ
    parts: tuple[Part, ...]
    notes: tuple[str, ...]
    fixed_add: int = 0  # 작은 공사라 중심에 더한 고정비(부가세 포함, 만 원 단위). 집 전체면 0


@dataclass(frozen=True)
class _Mix:
    center: float  # 본체 중심(부가세 빼고)
    sigma: float
    shifts: tuple[tuple[float, float], ...]  # (조건 줄 금액 합, 확률)
    floor: float  # 최소 금액(부가세 빼고)
    k: float  # 1 + 부가세율


def _won(x: float) -> Decimal:
    """float 계산 끝값을 원 단위로 먼저 반올림한다(220000.00000000003 → 220000)"""
    return Decimal(round(x))


def _floor_man(x: float) -> int:
    return int((_won(x) / MAN).to_integral_value(rounding=ROUND_FLOOR) * MAN)


def _ceil_man(x: float) -> int:
    return int((_won(x) / MAN).to_integral_value(rounding=ROUND_CEILING) * MAN)


def _round_man(x: float) -> int:
    return int((_won(x) / MAN).to_integral_value(rounding=ROUND_HALF_UP) * MAN)


def _pick(table: Mapping[str, Decimal], trade: str, grade: str | None):
    if grade and f"{trade}.{grade}" in table:
        return table[f"{trade}.{grade}"]
    if trade in table:
        return table[trade]
    raise ValueError("공정을 다시 확인해 주세요")


def _qty_var(inp: RangeInput, r: RangeRules) -> dict[str, float]:
    """수량 근거별 분산 몫 (금액 비중 × σ)²"""
    t = inp.trade
    supply = sum(inp.amounts.values())
    weight: dict[str, int] = defaultdict(int)
    for key, amount in inp.amounts.items():
        g = QTY_DRIVER[t].get(key)
        if g is None:
            raise ValueError(f"수량 근거를 모르는 줄이에요: {key}")
        weight[g] += amount
    out: dict[str, float] = {}
    for g, w in weight.items():
        prec = inp.precision.get(g)
        sig = r.qty_sigma.get(t, {}).get(g, {}).get(prec) if prec else None
        if sig is None:
            raise ValueError(f"{g} 수량을 얼마나 정확히 아는지 다시 확인해 주세요")
        out[g] = (w / supply * float(sig)) ** 2 if supply else 0.0
    return out


def _share_var(inp: RangeInput) -> dict[str, float]:
    """고른 공간 몫 σ의 분산 몫 (그 근거 줄 금액 비중 × σ)². 일부 공간만 골랐을 때만 있다."""
    t = inp.trade
    supply = sum(inp.amounts.values())
    out: dict[str, float] = {}
    for g, sig in inp.share_sigma.items():
        if sig < 0:
            raise ValueError("고른 공간 몫 σ는 0 이상이어야 해요")
        w = sum(a for k, a in inp.amounts.items() if QTY_DRIVER[t].get(k) == g)
        if sig and w:
            out[g] = (w / supply * float(sig)) ** 2
    return out


def _cond_dist(
    inp: RangeInput, r: RangeRules, fixed: Mapping[str, float] | None = None
) -> tuple[tuple[tuple[float, float], ...], float]:
    """조건 줄 금액 합의 분포(만 원 단위로 묶음)와 '다 하면' 최대. fixed는 조건별 확률을 덮어쓴다."""
    dist: dict[float, float] = {0.0: 1.0}
    extra = 0.0
    for key, state in inp.conds.items():
        rule = r.conds.get(inp.trade, {}).get(key)
        if rule is None:
            raise ValueError(f"범위를 모르는 조건 줄이에요: {key}")
        n = 1.0
        if rule.per == "qty":
            q = inp.cond_qty.get(key)
            if q is None or q < 0:
                raise ValueError(f"{key} 줄의 수량이 있어야 해요")
            n = float(q)
        elif rule.min_scale is not None:
            if not 0 < inp.job_share <= 1:
                raise ValueError("공사 크기 몫은 0보다 크고 1 이하여야 해요")
            n = float(max(inp.job_share, rule.min_scale))
        if state == "yes":
            p = 1.0
        elif state == "open":
            raw = inp.cond_p.get(key, rule.p)
            if not 0 <= raw <= 1:
                raise ValueError("할 확률은 0~1이어야 해요")
            p = float(raw)
            extra += rule.high * n
        else:
            raise ValueError("조건은 '하기로 함' 또는 '모름'이어야 해요")
        if fixed and key in fixed:
            p = fixed[key]
        a, b = rule.low * n, rule.high * n
        points = [a + (b - a) * (i + 0.5) / GRID for i in range(GRID)]
        nxt: dict[float, float] = defaultdict(float)
        for s, w in dist.items():
            if p < 1:
                nxt[s] += w * (1 - p)
            if p > 0:
                for v in points:
                    nxt[float(round((s + v) / 10_000) * 10_000)] += w * p / GRID
        dist = dict(nxt)
    return tuple(sorted(dist.items())), extra


def _small(inp: RangeInput, r: RangeRules) -> float:
    """작은 공사일수록 업체마다 고정비가 달라 단가 흩어짐이 넓다(방 1칸 × 1.3, 벽 한 면 × 1.8)"""
    for upper, mult in r.small_sigma:
        if inp.job_share < upper:
            return float(mult)
    return 1.0


def _fixed(inp: RangeInput, r: RangeRules) -> float:
    """작은 공사에 붙는 고정비(부가세 빼고). 집 전체 단가에 이미 녹아 있는 몫이라 (1 − 공사 몫)만큼만 더한다"""
    if inp.fixed_key is None or inp.job_share >= 1:
        return 0.0
    if inp.fixed_key not in r.fixed_cost:
        raise ValueError("고정비 키를 다시 확인해 주세요")
    return r.fixed_cost[inp.fixed_key] * (1 - float(inp.job_share))


def _mix(
    inp: RangeInput,
    r: RangeRules,
    *,
    price_sigma: float | None = None,
    fixed: Mapping[str, float] | None = None,
) -> _Mix:
    t = inp.trade
    if t not in QTY_DRIVER:
        raise ValueError("공정을 다시 확인해 주세요")
    if any(a < 0 for a in inp.amounts.values()):
        raise ValueError("금액은 0 이상이어야 해요")
    supply = sum(inp.amounts.values())
    if supply <= 0 and not inp.conds:
        raise ValueError("금액이 있는 줄이 없어요")
    if not 0 < inp.job_share <= 1:
        raise ValueError("공사 크기 몫은 0보다 크고 1 이하여야 해요")
    q = _qty_var(inp, r)
    sh = _share_var(inp)
    if price_sigma is None:
        table = r.visit_sigma if inp.vendor_priced else r.price_sigma
        price_sigma = float(_pick(table, t, inp.grade)) * _small(inp, r)
    center = supply * (1.0 if inp.vendor_priced else float(_pick(r.price_center, t, inp.grade)))
    center += _fixed(inp, r)
    sigma = sqrt(sum(q.values()) + sum(sh.values()) + price_sigma**2)
    shifts, _ = _cond_dist(inp, r, fixed)
    k = 1.0 if inp.exempt else 1.0 + float(r.vat_rate)
    # 최소 금액도 고정비 키(방문만 바꾸는 공사 등)에 따로 있으면 그것을 쓴다
    if inp.fixed_key in r.min_job:
        floor = float(r.min_job[inp.fixed_key])
    else:
        floor = float(_pick(r.min_job, t, inp.grade))
    return _Mix(center, sigma, shifts, floor, k)


def _cdf(m: _Mix, x: float) -> float:
    total = 0.0
    for s, w in m.shifts:
        y = x - s
        if m.center <= 0 or m.sigma == 0:
            total += w if y >= m.center else 0.0
        elif y > 0:
            total += w * 0.5 * (1 + erf((log(y) - log(m.center)) / (m.sigma * sqrt(2))))
    return total


def price_cdf(inp: RangeInput, r: RangeRules, amount: int) -> Decimal:
    """실제 금액(부가세 포함, 면세면 그대로)이 이 분포의 몇 % 지점인지(0~1, 소수 셋째 자리).
    실측 견적이 범위의 어디쯤인지 보이거나(범위 밖 차이 설명) 실견적으로 범위를 검증할 때 쓴다.
    최소 금액 아래는 0으로 본다(범위 하한을 최소 금액으로 올린 것과 같은 기준)."""
    if amount < 0:
        raise ValueError("금액은 0 이상이어야 해요")
    m = _mix(inp, r)
    x = amount / m.k
    p = 0.0 if x < m.floor else _cdf(m, x)
    return Decimal(min(max(p, 0.0), 1.0)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def _quantile(m: _Mix, prob: float) -> float:
    lo, hi = 0.0, m.center * exp(6 * m.sigma) + (m.shifts[-1][0] if m.shifts else 0.0) + 1.0
    for _ in range(STEPS):
        mid = (lo + hi) / 2
        if _cdf(m, mid) < prob:
            lo = mid
        else:
            hi = mid
    return hi


def _bounds(m: _Mix, z: float) -> tuple[int, int, int, bool]:
    """부가세 포함 · 만 원 단위 (하한, 중간, 상한)과 최소 금액을 적용했는지"""
    p_lo = 0.5 * (1 + erf(-z / sqrt(2)))
    lo, mid, hi = (_quantile(m, p) for p in (p_lo, 0.5, 1 - p_lo))
    floor = lo < m.floor
    lo, mid, hi = (max(v, m.floor) for v in (lo, mid, hi))
    return _floor_man(lo * m.k), _round_man(mid * m.k), _ceil_man(hi * m.k), floor


def _better(table: Mapping[str, Decimal], now: Precision) -> Precision | None:
    later = LADDER[LADDER.index(now) + 1 :]
    return next((p for p in later if p in table), None)


def price_range(inp: RangeInput, r: RangeRules, *, explain: bool = True) -> PriceRange:
    """explain=False면 폭의 이유(parts)를 계산하지 않는다(업체 목록처럼 범위만 필요할 때)."""
    z = float(r.z)
    m = _mix(inp, r)
    low, mid, high, floor = _bounds(m, z)
    width = high - low
    t = inp.trade

    def narrowed(**kw) -> tuple[int, int]:
        lo, _, hi, _ = _bounds(_mix(**kw), z)
        return lo, hi

    gains: list[tuple[Part, float]] = []
    for g in _qty_var(inp, r) if explain else ():
        nxt = _better(r.qty_sigma[t][g], inp.precision[g])
        if nxt is None:
            gains.append((Part(f"qty:{g}", Decimal(0)), 0.0))
            continue
        lo, hi = narrowed(inp=replace(inp, precision={**inp.precision, g: nxt}), r=r)
        gains.append((Part(f"qty:{g}", Decimal(0), nxt, lo, hi), max(width - (hi - lo), 0)))
    for g in _share_var(inp) if explain else ():
        # 고른 공간을 재면 몫 가정과 집 크기 가정이 함께 사라진다(셀프 실측)
        table = r.qty_sigma[t][g]
        nxt = "self" if "self" in table else _better(table, inp.precision[g])
        prec = {**inp.precision, g: nxt} if nxt else inp.precision
        lo, hi = narrowed(
            inp=replace(inp, precision=prec, share_sigma={**inp.share_sigma, g: Decimal(0)}), r=r
        )
        gains.append((Part(f"share:{g}", Decimal(0), nxt, lo, hi), max(width - (hi - lo), 0)))
    if not explain:
        pass
    elif inp.vendor_priced:
        lo, hi = narrowed(inp=inp, r=r, price_sigma=0.0)
        gains.append((Part("visit", Decimal(0)), max(width - (hi - lo), 0)))
    else:
        visit = float(_pick(r.visit_sigma, t, inp.grade))
        lo, hi = narrowed(inp=inp, r=r, price_sigma=visit)
        gains.append((Part("price", Decimal(0), None, lo, hi), max(width - (hi - lo), 0)))
    for key, state in inp.conds.items() if explain else ():
        if state == "yes":
            continue
        p = float(inp.cond_p.get(key, r.conds[t][key].p))
        y_lo, y_hi = narrowed(inp=inp, r=r, fixed={key: 1.0})
        n_lo, n_hi = narrowed(inp=inp, r=r, fixed={key: 0.0})
        expected = p * (y_hi - y_lo) + (1 - p) * (n_hi - n_lo)
        part = Part(f"cond:{key}", Decimal(0), None, y_lo, y_hi, n_lo, n_hi)
        gains.append((part, max(width - expected, 0)))

    total = sum(g for _, g in gains)
    parts = [
        replace(
            part,
            share=Decimal(g / total if total > 0 else 0).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            ),
        )
        for part, g in gains
    ]
    parts.sort(key=lambda p: p.share, reverse=True)

    _, extra = _cond_dist(inp, r)
    notes: list[str] = []
    if not inp.vendor_priced:
        notes.append("업체 단가를 아직 몰라 업체마다 다른 단가를 범위에 넣었어요.")
    if any(s == "open" for s in inp.conds.values()):
        notes.append("할지 모르는 '실측 후' 줄은 할 가능성만큼 범위에 섞었어요.")
    fixed = _fixed(inp, r)
    if fixed:
        notes.append("작은 공사라 출장 · 최소 인건비 같은 고정비를 더해 잡았어요.")
    if floor:
        notes.append("작은 공사라 업체가 보통 받는 최소 금액을 아래쪽 끝으로 잡았어요.")
    return PriceRange(
        version=r.version,
        trade=t,
        low=low,
        mid=mid,
        high=high,
        extra_max=_ceil_man(extra * m.k) if extra else 0,
        sigma=Decimal(m.sigma).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP),
        parts=tuple(parts),
        notes=tuple(notes),
        fixed_add=_round_man(fixed * m.k) if fixed else 0,
    )


def _merge_shifts(
    a: tuple[tuple[float, float], ...], b: tuple[tuple[float, float], ...]
) -> tuple[tuple[float, float], ...]:
    out: dict[float, float] = defaultdict(float)
    for s1, w1 in a:
        for s2, w2 in b:
            out[float(round((s1 + s2) / 10_000) * 10_000)] += w1 * w2
    return tuple(sorted(out.items()))


def price_range_total(inps: list[RangeInput], r: RangeRules) -> PriceRange:
    """여러 공정을 합친 예상 범위(부가세 포함). 폭의 이유는 공정마다 따로 본다(parts는 비움).

    본체: 공정마다 로그 정규(중심 c, σ)의 평균 · 분산을 더하고(상관 trade_corr) 같은 평균 · 분산의 로그 정규로 묶는다.
    조건 줄: 공정마다 분포를 서로 독립으로 보고 모두 섞는다. 최소 금액은 공정별 최소 금액의 합이다."""
    if not inps:
        raise ValueError("공정이 하나 이상 있어야 해요")
    if len({inp.trade for inp in inps}) != len(inps):
        raise ValueError("공정이 겹쳐요")
    if len(inps) == 1:
        return replace(price_range(inps[0], r, explain=False), trade="total")
    mixes = [_mix(inp, r) for inp in inps]
    if len({m.k for m in mixes}) != 1:
        raise ValueError("부가세 방식이 같은 공정끼리만 합쳐요")
    means = [m.center * exp(m.sigma**2 / 2) for m in mixes]
    vars_ = [mu**2 * (exp(m.sigma**2) - 1) for mu, m in zip(means, mixes, strict=True)]
    rho = float(r.trade_corr)
    mean = sum(means)
    var = sum(vars_) + 2 * rho * sum(
        sqrt(vars_[i] * vars_[j]) for i in range(len(vars_)) for j in range(i + 1, len(vars_))
    )
    s2 = log(1 + var / mean**2) if mean > 0 else 0.0
    shifts: tuple[tuple[float, float], ...] = ((0.0, 1.0),)
    for m in mixes:
        shifts = _merge_shifts(shifts, m.shifts)
    total = _Mix(
        center=mean * exp(-s2 / 2),
        sigma=sqrt(s2),
        shifts=shifts,
        floor=sum(m.floor for m in mixes),
        k=mixes[0].k,
    )
    low, mid, high, floor = _bounds(total, float(r.z))
    extra = sum(_cond_dist(inp, r)[1] for inp in inps)
    fixed = sum(_fixed(inp, r) for inp in inps)
    notes = [
        "공정마다 범위를 낸 뒤 합쳤어요. 두 공정 단가는 지역 · 시기에 따라 함께 오르내릴 수 있어 일부 같이 움직이는 것으로 봤어요."
    ]
    if floor:
        notes.append("작은 공사라 업체가 보통 받는 최소 금액을 아래쪽 끝으로 잡았어요.")
    return PriceRange(
        version=r.version,
        trade="total",
        low=low,
        mid=mid,
        high=high,
        extra_max=_ceil_man(extra * total.k) if extra else 0,
        sigma=Decimal(total.sigma).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP),
        parts=(),
        notes=tuple(notes),
        fixed_add=_round_man(fixed * total.k) if fixed else 0,
    )
