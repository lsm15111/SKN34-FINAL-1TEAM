"""주방 계산 엔진. 주방은 공공 단가가 없어 금액 줄이 모두 가정값이다. 기대값은 손으로 계산한 값이다."""

from decimal import Decimal
from itertools import product

import pytest

from app.calc import kitchen
from app.calc.common import pyeong_to_m2
from app.refprice.kitchen import KITCHEN_2026H2 as P
from tests.calc_checks import check_quote


def q(**kw) -> kitchen.KitchenQuote:
    base = {"area_m2": pyeong_to_m2(Decimal(34)), "area_basis": "supply", "occupied": False}
    return kitchen.quote(kitchen.KitchenInput(**(base | kw)), P)


def amounts(r) -> dict[str, int | None]:
    return {ln.key: ln.amount for ln in r.lines}


def test_straight_34_pyeong_is_all_assumed():
    r = q()
    # 공급 112.4㎡ = 34평 × 0.1m = 3.4m
    assert r.length_m == Decimal("3.4")
    a = amounts(r)
    assert (a["cabinet"], a["top"]) == (1_530_000, 680_000)  # 3.4 × 450,000 · 3.4 × 200,000
    assert (a["hood"], a["sink"]) == (250_000, 250_000)
    assert (r.subtotal, r.vat, r.total) == (2_710_000, 271_000, 2_981_000)
    # 공공 근거가 없다는 것을 줄마다 숨기지 않는다
    assert {ln.basis for ln in r.lines if ln.state == "included"} == {"assumed"}
    assert {ln.basis for ln in r.lines if ln.state == "after_visit"} == {"none"}
    assert any("공공 기준 단가가 없어" in x for x in r.assumptions)
    # 가구 품 3.4 × 0.4 = 1.36 → 2명이면 반나절 2번
    assert [(s.key, s.half_days) for s in r.steps] == [
        ("remove", 1),
        ("cabinet", 2),
        ("top", 1),
        ("fit", 1),
        ("finish", 1),
    ]
    assert (r.man_days, r.days) == (Decimal("1.5"), Decimal(3))
    # 가구 · 상판 · 연결은 도배 · 바닥 뒤 작업, 철거는 앞
    assert [s.key for s in r.steps if s.late] == ["cabinet", "top", "fit"]
    # 주방 벽 타일은 타일 공정, 인덕션 전용 회로는 실측 후
    induction = next(ln for ln in r.lines if ln.key == "induction")
    assert (induction.name, induction.state) == ("인덕션 전용 회로 (필요하면)", "after_visit")
    assert not any("타일" in ln.name for ln in r.lines)


def test_l_shape_quartz_from_exclusive_area_without_hood():
    r = q(
        area_m2=Decimal("84.9"), area_basis="exclusive", layout="l_shape", top="quartz", hood=False
    )
    # 전용 84.9 × 1.2 = 공급 101.88㎡ → 30.82평 × 0.1 = 3.08m × 1.4 = 4.3m
    assert r.length_m == Decimal("4.3")
    a = amounts(r)
    assert (a["cabinet"], a["top"], a["hood"]) == (1_935_000, 1_720_000, None)
    assert next(ln for ln in r.lines if ln.key == "hood").state == "excluded"
    assert r.subtotal == 3_905_000
    assert any("ㄱ자 배치는 일자의 1.4배" in x for x in r.assumptions)


def test_given_length_wins_and_is_kept_in_bounds():
    r = q(length_m=Decimal("3.0"), layout="parallel")
    assert r.length_m == Decimal("3.0") and amounts(r)["cabinet"] == 1_350_000
    assert not any("싱크대 길이는" in x for x in r.assumptions)
    # 아주 작은 집도 최소 길이, 아주 큰 집도 최대 길이까지만 잡는다
    assert q(area_m2=Decimal("40.0")).length_m == Decimal("2.4")
    assert q(area_m2=Decimal("250.0")).length_m == Decimal("4.2")


def test_every_combination_keeps_the_rules():
    for layout, top, hood, faucet, occupied, length in product(
        kitchen.LAYOUTS,
        kitchen.TOPS,
        (False, True),
        (False, True),
        (False, True),
        (None, Decimal("2.0"), Decimal("4.5")),
    ):
        kw = {
            "layout": layout,
            "top": top,
            "hood": hood,
            "faucet": faucet,
            "occupied": occupied,
            "length_m": length,
        }
        r = q(**kw)
        check_quote(r)
        assert (r.steps[0].key == "prep") == occupied
        assert (r.length_m > 0) and all(ln.basis != "public" for ln in r.lines)
        if length is not None:
            assert q(**(kw | {"length_m": length + 1})).total >= r.total
        bigger = q(**(kw | {"area_m2": Decimal("150.0")}))
        assert bigger.total >= r.total
        assert q(**(kw | {"hood": True, "faucet": True})).total >= r.total


@pytest.mark.parametrize(
    "kw",
    [
        {"area_m2": Decimal(0)},
        {"area_basis": "pyeong"},
        {"layout": "u_shape"},
        {"top": "steel"},
        {"length_m": Decimal(0)},
        {"length_m": Decimal(-1)},
        {"length_m": kitchen.MAX_LENGTH + 1},
    ],
)
def test_bad_input(kw):
    with pytest.raises(ValueError):
        q(**kw)
