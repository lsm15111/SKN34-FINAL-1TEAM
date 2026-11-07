"""예상 범위: 이 집 금액이 대부분(10~90%) 들어갈 구간과 그 폭을 만든 이유.

폭은 세 가지에서 나온다.
- 수량: 면적 · 길이를 얼마나 정확히 아는지. 가정값 → 평형대 → 면적 입력 → 고객이 잼 → 업체가 잼(실측).
- 단가: 업체마다 다른 값. 업체 단가를 모르면 시장 흩어짐, 가견적(업체 단가를 앎)이면 실측 보정만 남는다.
- 조건: '실측 후' 줄(철거 · 폐기물 · 짐 이동 …). 하기로 정했으면 하한 · 상한에 다 넣고,
  아직 모르면 상한에만 넣는다(안 할 수도 있어서).

수량 · 단가는 로그 정규로 보고 σ² = σ수량² + σ단가²로 묶는다(둘은 독립으로 본다).
수량은 줄을 수량 근거(면적 · 둘레 · 천장 · 문)로 묶는다. 같은 근거의 줄은 같이 틀리고(금액 비율로 σ를 더함),
다른 근거끼리는 독립이다(제곱합).
구간 = 중심 × exp(±z·σ). 무작위를 쓰지 않아 같은 입력이면 같은 구간이다.
금액은 원 정수이고, 보이는 끝값은 만 원 단위로 하한 내림 · 중간 반올림 · 상한 올림한다.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
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


@dataclass(frozen=True)
class CondRule:
    """'실측 후' 줄 하나의 시장 범위(부가세 빼고). per가 lump면 한 번(식), qty면 수량(㎡ · m · 개)당."""

    per: Literal["lump", "qty"]
    low: int
    high: int
    source: str

    def __post_init__(self) -> None:
        if not 0 <= self.low <= self.high:
            raise ValueError("조건 줄 범위는 0 ≤ 하한 ≤ 상한이어야 해요")


@dataclass(frozen=True)
class RangeRules:
    """범위 계산에 쓰는 가정값 한 벌. refprice가 버전별로 만들어 넘긴다."""

    version: str
    z: Decimal  # 1.2816 = 10~90% 구간
    qty_sigma: Mapping[str, Mapping[str, Mapping[str, Decimal]]]  # 공정 → 수량 근거 → 정밀도 → σ
    price_sigma: Mapping[str, Decimal]  # 공정 → 업체 단가 흩어짐 σ
    price_center: Mapping[str, Decimal]  # 공정 → 시장 중심 ÷ 공공 기준
    visit_sigma: Mapping[str, Decimal]  # 공정 → 가견적 → 실측 견적 보정 σ
    min_job: Mapping[str, int]  # 공정 → 작은 공사도 드는 최소 금액(부가세 빼고)
    conds: Mapping[str, Mapping[str, CondRule]]  # 공정 → '실측 후' 줄 키 → 범위
    vat_rate: Decimal
    sources: Mapping[str, str]


@dataclass(frozen=True)
class RangeInput:
    trade: str
    amounts: Mapping[str, int]  # 합계에 들어간 줄 키 → 금액(부가세 빼고). 표준견적서 또는 가견적
    precision: Mapping[str, Precision]  # 수량 근거 → 정밀도
    conds: Mapping[str, CondState] = field(default_factory=dict)  # '실측 후' 줄 → 하기로 함 · 모름
    cond_qty: Mapping[str, Decimal] = field(default_factory=dict)  # per=qty 줄의 수량
    vendor_priced: bool = False  # 가견적이면 True(업체 단가를 앎)
    exempt: bool = False  # 면세 업체


@dataclass(frozen=True)
class Part:
    """구간 폭을 만든 이유 하나."""

    driver: str  # qty:area · qty:edge · price · visit · cond:removal …
    share: Decimal  # 폭 중 이 이유의 몫(0~1, 소수 둘째 자리)
    better: Precision | None = None  # 수량: 한 단계 더 알면 되는 정밀도
    low_if: int | None = None  # 한 단계 더 알 때(수량) · 가견적을 받을 때(단가)의 구간
    high_if: int | None = None


@dataclass(frozen=True)
class PriceRange:
    version: str
    trade: str
    low: int  # 부가세 포함, 만 원 단위
    mid: int
    high: int
    sigma: Decimal  # 수량 · 단가를 묶은 σ (조건 줄 제외)
    parts: tuple[Part, ...]
    notes: tuple[str, ...]


@dataclass(frozen=True)
class _Core:
    lo: Decimal  # 부가세 빼고, 최소 금액 적용 전
    mid: Decimal
    hi: Decimal
    sigma: Decimal
    ln_width: Decimal  # 로그 정규 부분의 폭
    q_var: dict[str, Decimal]  # 수량 근거 → 분산 몫(σ²)
    p_var: Decimal
    cond_width: dict[str, Decimal]  # 조건 줄 → 폭
    floor: bool  # 최소 금액을 적용했는지
    out: tuple[int, int, int]  # 부가세 포함, 만 원 단위


def _floor_man(x: Decimal) -> int:
    return int((x / MAN).to_integral_value(rounding=ROUND_FLOOR) * MAN)


def _ceil_man(x: Decimal) -> int:
    return int((x / MAN).to_integral_value(rounding=ROUND_CEILING) * MAN)


def _round_man(x: Decimal) -> int:
    return int((x / MAN).to_integral_value(rounding=ROUND_HALF_UP) * MAN)


def _core(inp: RangeInput, r: RangeRules) -> _Core:
    t = inp.trade
    if t not in QTY_DRIVER or t not in r.price_sigma:
        raise ValueError("공정을 다시 확인해 주세요")
    if any(a < 0 for a in inp.amounts.values()):
        raise ValueError("금액은 0 이상이어야 해요")
    supply = Decimal(sum(inp.amounts.values()))
    if supply <= 0 and not inp.conds:
        raise ValueError("금액이 있는 줄이 없어요")

    weight: dict[str, Decimal] = {}
    for key, amount in inp.amounts.items():
        g = QTY_DRIVER[t].get(key)
        if g is None:
            raise ValueError(f"수량 근거를 모르는 줄이에요: {key}")
        weight[g] = weight.get(g, Decimal(0)) + Decimal(amount)
    q_var: dict[str, Decimal] = {}
    for g, w in weight.items():
        prec = inp.precision.get(g)
        sig = r.qty_sigma.get(t, {}).get(g, {}).get(prec) if prec else None
        if sig is None:
            raise ValueError(f"{g} 수량을 얼마나 정확히 아는지 다시 확인해 주세요")
        term = w / supply * sig if supply else Decimal(0)
        q_var[g] = term * term

    p_sig = r.visit_sigma[t] if inp.vendor_priced else r.price_sigma[t]
    center = supply if inp.vendor_priced else supply * r.price_center[t]
    p_var = p_sig * p_sig
    sigma = (sum(q_var.values(), Decimal(0)) + p_var).sqrt()
    lo = center * (-r.z * sigma).exp()
    hi = center * (r.z * sigma).exp()

    c_lo = c_mid = c_hi = Decimal(0)
    cond_width: dict[str, Decimal] = {}
    for key, state in inp.conds.items():
        rule = r.conds.get(t, {}).get(key)
        if rule is None:
            raise ValueError(f"범위를 모르는 조건 줄이에요: {key}")
        n = Decimal(1)
        if rule.per == "qty":
            n = inp.cond_qty.get(key, Decimal(-1))
            if n < 0:
                raise ValueError(f"{key} 줄의 수량이 있어야 해요")
        a, b = Decimal(rule.low) * n, Decimal(rule.high) * n
        if state == "yes":
            c_lo, c_mid, c_hi = c_lo + a, c_mid + (a + b) / 2, c_hi + b
            cond_width[key] = b - a
        elif state == "open":
            c_hi += b
            cond_width[key] = b
        else:
            raise ValueError("조건은 '하기로 함' 또는 '모름'이어야 해요")

    low, mid, high = lo + c_lo, center + c_mid, hi + c_hi
    m = Decimal(r.min_job[t])
    floor = low < m
    low, mid, high = max(low, m), max(mid, m), max(high, m)
    k = 1 + (Decimal(0) if inp.exempt else r.vat_rate)
    out = (_floor_man(low * k), _round_man(mid * k), _ceil_man(high * k))
    return _Core(lo, mid, hi, sigma, hi - lo, q_var, p_var, cond_width, floor, out)


def _better(table: Mapping[str, Decimal], now: Precision) -> Precision | None:
    later = LADDER[LADDER.index(now) + 1 :]
    return next((p for p in later if p in table), None)


def price_range(inp: RangeInput, r: RangeRules) -> PriceRange:
    c = _core(inp, r)
    t = inp.trade
    var = sum(c.q_var.values(), Decimal(0)) + c.p_var
    total = c.ln_width + sum(c.cond_width.values(), Decimal(0))

    def share(width: Decimal) -> Decimal:
        x = width / total if total > 0 else Decimal(0)
        return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    parts: list[Part] = []
    for g, v in c.q_var.items():
        now = inp.precision[g]
        nxt = _better(r.qty_sigma[t][g], now)
        low_if = high_if = None
        if nxt is not None:
            low_if, _, high_if = _core(replace(inp, precision={**inp.precision, g: nxt}), r).out
        width = c.ln_width * v / var if var > 0 else Decimal(0)
        parts.append(Part(f"qty:{g}", share(width), nxt, low_if, high_if))
    p_width = c.ln_width * c.p_var / var if var > 0 else Decimal(0)
    if inp.vendor_priced:
        parts.append(Part("visit", share(p_width)))
    else:
        low_if, _, high_if = _core(replace(inp, vendor_priced=True), r).out
        parts.append(Part("price", share(p_width), None, low_if, high_if))
    parts += [Part(f"cond:{k}", share(w)) for k, w in c.cond_width.items()]
    parts.sort(key=lambda p: p.share, reverse=True)

    notes: list[str] = []
    if not inp.vendor_priced:
        notes.append("업체 단가를 아직 몰라 업체마다 다른 단가를 범위에 넣었어요.")
    opened = [k for k, s in inp.conds.items() if s == "open"]
    if opened:
        notes.append(f"'실측 후' 줄 {len(opened)}개는 할지 몰라 범위 위쪽에만 넣었어요.")
    if c.floor:
        notes.append("작은 공사라 업체가 보통 받는 최소 금액을 아래쪽 끝으로 잡았어요.")
    low, mid, high = c.out
    return PriceRange(r.version, t, low, mid, high, c.sigma, tuple(parts), tuple(notes))
