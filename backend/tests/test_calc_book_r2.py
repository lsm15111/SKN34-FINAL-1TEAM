"""기준 단가 r2: 표준품셈 · 표준시장단가 원문과 대조해 고친 값이 근거와 맞는지 본다(docs/research/T2 · T3).
r1(지금 기본값)은 그대로다. 기대값은 원문 수치로 손으로 계산했다."""

from decimal import Decimal

from app.calc import dobae, mokgong
from app.calc.common import pyeong_to_m2
from app.calc.standard_quote import house_pyeong
from app.refprice.book import DOBAE_2026H2, DOBAE_2026H2_R2, MOKGONG_2026H2, MOKGONG_2026H2_R2
from app.refprice.house import HOUSE_2026H2, HOUSE_2026H2_R2
from tests.calc_checks import check_quote


def dq(p, pyeong=34, basis="supply", area=None, balcony=False):
    area = area or pyeong_to_m2(Decimal(pyeong))
    return dobae.quote(dobae.DobaeInput(area, basis, "basic", True, False, balcony), p)


def test_r1_is_unchanged():
    assert DOBAE_2026H2.version == "2026H2" and DOBAE_2026H2.removal == 1_727
    assert MOKGONG_2026H2.supply_per_exclusive == Decimal("1.2")
    assert HOUSE_2026H2.supply_per_exclusive == Decimal("1.2")


def test_dobae_area_matches_floor_plan_reference():
    # AI Hub 도면 기반 참값(벽 + 천장): 24평형(전용 59) 177~189㎡, 34평형(전용 84) 251~268㎡ (T2 4.4)
    r2_34 = dq(DOBAE_2026H2_R2).paper_m2
    r1_34 = dq(DOBAE_2026H2).paper_m2
    assert Decimal(251) <= r2_34 <= Decimal(268) < r1_34
    r2_24 = dq(DOBAE_2026H2_R2, area=Decimal("79.0")).paper_m2  # 24평형 공급 약 79㎡
    assert Decimal(177) <= r2_24 <= Decimal(189)
    assert dq(DOBAE_2026H2_R2, basis="exclusive", area=Decimal(84)).paper_m2 == Decimal("252.0")


def test_dobae_ceiling_share_and_man_days():
    r = dq(DOBAE_2026H2_R2)
    assert r.ceiling_m2 / r.paper_m2 > Decimal("0.29")  # 천장 30%
    # 표준품셈 34평형 도배공 약 6.2인 → 0.5 올림 6.5, 4명이면 2일 + 마감 반나절
    assert r.man_days == Decimal("6.5") and r.days == Decimal("2.5")
    assert dq(DOBAE_2026H2).man_days == Decimal("8.0")  # r1은 천장 감을 두 번 곱해 많았다
    check_quote(r)


def test_dobae_removal_uses_standard_dismantling():
    assert DOBAE_2026H2_R2.removal == 2_944  # 벽 2,702 · 천장 3,507원/㎡를 천장 30%로 섞음
    line = next(ln for ln in dq(DOBAE_2026H2_R2).lines if ln.key == "removal")
    assert line.state == "after_visit" and line.unit_price == 2_944


def test_mokgong_supply_ratio_and_casing():
    inp = mokgong.MokgongInput(Decimal(84), "exclusive", ("molding", "door"), False, doors=3)
    r1, r2 = mokgong.quote(inp, MOKGONG_2026H2), mokgong.quote(inp, MOKGONG_2026H2_R2)
    assert r2.molding_m > r1.molding_m  # 전용 84㎡ → 공급 109.2㎡(r1은 100.8㎡로 약 8% 적었다)
    casing = next(ln for ln in r2.lines if ln.key == "casing")
    assert casing.qty == Decimal("33.0")  # 문 3개 × 11.0m
    check_quote(r2)


def test_house_pyeong_from_exclusive():
    # 전용 84㎡는 흔히 34평형(공급 112㎡ 안팎)
    assert house_pyeong(None, Decimal(84), "exclusive", HOUSE_2026H2_R2) == Decimal("33.0")
    assert house_pyeong(None, Decimal(84), "exclusive", HOUSE_2026H2) == Decimal("30.5")
