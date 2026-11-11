"""시장 기준 금액 · 범위. DB · HTTP 없이 순수 함수만 본다. 기대값은 손으로 검산한 값이다."""

from dataclasses import replace
from decimal import Decimal

import pytest

from app.calc.market_band import (
    MarketDobaeInput,
    MarketMokgongInput,
    dobae,
    extras_range,
    gap_steps,
    mokgong,
)
from app.calc.plan_qty import Plan, from_plan
from app.refprice.mvp_market import (
    GAP_DOBAE,
    GAP_MOKGONG,
    PUBLIC_EQ_DOBAE,
    PUBLIC_EQ_MOKGONG,
)
from app.refprice.mvp_market import (
    MARKET_2026_11 as BOOK,
)

D = Decimal


def amounts(r):
    return {ln.key: ln.amount for ln in r.lines}


def test_dobae_silk_without_plan():
    r = dobae(MarketDobaeInput(area_m2=D("109.1"), grade="basic"), BOOK)
    a = amounts(r)
    # 109.1 × 2.24 = 244.384 → 천장 × 0.37 = 90.4, 벽 244.4 − 90.4 = 154.0
    # 시공 5,993 × 0.94 = 5,633원, 8,531 × 0.94 = 8,019원
    assert (a["wall"], a["ceiling"]) == (154 * 5_633, 724_918)
    # 실크 244.4 × 1.2 = 293.28 → 293.3㎡ × 2,909, 부자재 33.0평 × 6,700
    assert (a["paper"], a["sub"]) == (853_210, 221_117)
    assert r.supply == 2_666_727
    # 범위 × 0.89 ~ × 1.27, 만 원 단위
    assert (r.lo, r.hi, r.n, r.paper) == (2_370_000, 3_390_000, 679, "silk")


def test_dobae_plan_uses_plan_band_and_premium_is_silk():
    plan = replace(from_plan(Plan(spaces=())), wall_m2=D("72.0"), ceiling_m2=D("36.8"))
    inp = MarketDobaeInput(area_m2=D("84.9"), grade="premium", plan=plan, plan_name="시험")
    r = dobae(inp, BOOK)
    assert r.paper == "silk" and r.band.lo == D("0.95") and r.n == 604
    assert r.lines[0].qty == D("72.0") and r.lines[0].note == "도면 시험에서 잰 벽 면적"


def test_dobae_small_job_hits_minimum():
    r = dobae(MarketDobaeInput(area_m2=D("10"), grade="economy"), BOOK)
    assert r.supply == 300_000 and r.lines[-1].key == "min"


def test_mokgong_base_only_minimum():
    # 공급 33.1㎡ = 10.0평 × 1.8 = 18.0m × 5,837 = 105,066 → 최소 40만 원
    r = mokgong(MarketMokgongInput(area_m2=D("33.1"), items=("base",)), BOOK)
    assert amounts(r) == {"base": 105_066, "min": 294_934}
    assert (r.supply, r.lo, r.hi) == (400_000, 320_000, 500_000)


def test_mokgong_default_doors_and_fixed_extras():
    inp = MarketMokgongInput(area_m2=D("84.9"), items=("door",), extra_amount=1_301_200)
    r = mokgong(inp, BOOK)
    # 25.7평은 28평 아래라 방 + 욕실 4개 × 40만 원, 범위 × 0.8 ~ × 1.25에 정해진 가격을 더함
    assert amounts(r) == {"door": 1_600_000, "extras": 1_301_200}
    assert (r.supply, r.lo, r.hi) == (2_901_200, 2_580_000, 3_300_000)


def test_extras_range():
    r = extras_range(BOOK.mokgong, {"jungmun": 1, "aircon": 2}, casing_doors=4, with_door=True)
    # 중문 90만~110만 + 단내림 2곳 × 40만~55만 + 9mm 문선 4개 × 5만~15만
    assert (r.lo, r.hi) == (1_900_000, 2_800_000)
    assert r.notes[0] == "현관 중문(3연동): 90만~110만 원 (실견적 4줄)"
    assert r.notes[1] == "에어컨 단내림 2곳: 곳당 40만~55만 원 (실견적 4줄)"


def test_gap_steps_end_at_market_supply():
    inp = MarketDobaeInput(area_m2=D("109.1"), grade="basic")
    g = gap_steps(inp, BOOK, PUBLIC_EQ_DOBAE, GAP_DOBAE, pub_supply=2_969_211, pub_vat=296_921)
    assert g.start == 3_266_132 and g.end == dobae(inp, BOOK).supply
    assert g.steps[0].key == "vat" and g.steps[0].d == -296_921
    keys = [s.key for s in g.steps]
    assert keys == sorted(keys, key=["vat", "lines", *[k for k, _, _ in GAP_DOBAE]].index)
    labor = next(s for s in g.steps if s.key == "labor_mult")
    assert labor.why.startswith("실크는")


def test_gap_steps_mokgong_counts_bath_doors():
    inp = MarketMokgongInput(area_m2=D("84.9"), items=("door",))
    g = gap_steps(inp, BOOK, PUBLIC_EQ_MOKGONG, GAP_MOKGONG, pub_supply=731_884, pub_vat=73_188)
    step = {s.key: s.d for s in g.steps}
    # 문 2개(방) → 4개(방 + 욕실), 그 사이 40만 원짜리로 바뀐 뒤라 2 × 40만
    assert step["doors_count"] == 800_000
    assert g.end == 1_600_000


def test_rejects_zero_area():
    with pytest.raises(ValueError):
        dobae(MarketDobaeInput(area_m2=D(0), grade="basic"), BOOK)
