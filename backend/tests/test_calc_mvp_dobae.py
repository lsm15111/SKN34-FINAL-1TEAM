"""MVP 도배 계산. DB · HTTP 없이 순수 함수만 본다. 기대값은 손으로 검산한 값이다."""

from dataclasses import replace
from decimal import Decimal

import pytest

from app.calc import dobae as team
from app.calc.mvp_dobae import MvpDobaeInput, quote
from app.calc.plan_qty import Plan, from_plan
from app.refprice.book import DOBAE_2026H2 as P

D = Decimal
PLAN = replace(from_plan(Plan(spaces=())), wall_m2=D("72.0"), ceiling_m2=D("36.8"))


def amounts(r):
    return {ln.key: ln.amount for ln in r.lines}


def test_without_plan_matches_team_dobae():
    r = quote(MvpDobaeInput(area_m2=D("109.1"), grade="basic"), P)
    t = team.quote(team.DobaeInput(D("109.1"), "supply", "basic", True, False), P)
    assert [(ln.key, ln.qty, ln.amount, ln.state) for ln in r.lines] == [
        (ln.key, ln.qty, ln.amount, ln.state) for ln in t.lines
    ]
    assert (r.total, r.man_days, r.days) == (t.total, t.man_days, t.days)
    # 공급 109.1㎡ × 2.5 = 272.75 → 천장 68.2, 벽 204.6
    assert (r.wall_m2, r.ceiling_m2, r.subtotal) == (D("204.6"), D("68.2"), 2_969_211)
    assert r.lines[0].calc == (
        "벽 면적 = 도배 면적 272.8㎡ − 천장 68.2㎡ (도배 면적 = 공급 109.1㎡ × 2.5)"
    )


def test_premium_uses_silk_price():
    a = quote(MvpDobaeInput(area_m2=D("84.9"), grade="premium"), P)
    b = quote(MvpDobaeInput(area_m2=D("84.9"), grade="basic"), P)
    assert a.paper_grade == "basic" and a.total == b.total
    assert a.lines[2].name == "도배지 (실크)"


def test_plan_areas_economy_occupied():
    inp = MvpDobaeInput(
        area_m2=D("84.9"), grade="economy", occupied=True, plan=PLAN, plan_name="시험"
    )
    r = quote(inp, P)
    a = amounts(r)
    # 벽 72 × 5,993, 천장 36.8 × 8,531 = 313,940.8
    assert (a["wall"], a["ceiling"]) == (431_496, 313_941)
    # 합지 108.8 × 1.2 = 130.56 → 130.6㎡ × 1,300, 초배지 72 × 1.2 + 36.8 × 0.8 = 115.84 → 115.8㎡ × 242
    assert (a["paper"], a["primer"]) == (169_780, 28_024)
    # 할증 745,437 × 0.96 × (1 ÷ 0.85 − 1) = 126,285.8
    assert a["occupied"] == 126_286
    assert (r.subtotal, r.vat, r.total) == (1_069_527, 106_953, 1_176_480)
    # 품 (72 × 0.024 + 36.8 × 0.0351) ÷ 0.85 = 3.55 → 4.0, 도배공 4명이면 반나절 2번
    assert r.man_days == D("4.0")
    assert [(s.key, s.half_days) for s in r.steps] == [("prep", 1), ("paper", 2), ("finish", 1)]
    assert r.lines[0].calc == "도면 시험에서 방마다 잰 벽 면적(문 · 창 뺌)"
    assert r.lines[2].price_basis == "assumed"


def test_plan_ignores_balcony_factor():
    base = MvpDobaeInput(area_m2=D("84.9"), grade="basic", plan=PLAN, plan_name="시험")
    r1, r2 = quote(base, P), quote(replace(base, balcony_ext=True), P)
    assert r1.total == r2.total
    assert not any("발코니" in n for n in r2.assumptions)


def test_ceiling_off_keeps_line_but_excluded():
    r = quote(MvpDobaeInput(area_m2=D("84.9"), grade="basic", include_ceiling=False), P)
    ceiling = next(ln for ln in r.lines if ln.key == "ceiling")
    assert (ceiling.state, ceiling.amount) == ("excluded", None)
    assert r.paper_m2 == r.wall_m2


def test_rejects_zero_area():
    with pytest.raises(ValueError):
        quote(MvpDobaeInput(area_m2=D(0), grade="basic"), P)
