"""예상 범위: 같은 입력이면 같은 구간, 더 정확히 알수록 좁아짐, 조건 줄은 위쪽, 최소 금액, 폭의 몫."""

from dataclasses import replace
from decimal import Decimal

import pytest

from app.calc import dobae, mokgong
from app.calc.common import COUNTED, pyeong_to_m2
from app.calc.price_range import QTY_DRIVER, RangeInput, price_range
from app.refprice.book import DOBAE_2026H2, MOKGONG_2026H2
from app.refprice.market import RANGE_2026H2 as R


def dobae_amounts(pyeong=32, occupied=False) -> dict[str, int]:
    inp = dobae.DobaeInput(pyeong_to_m2(Decimal(pyeong)), "supply", "basic", True, occupied)
    q = dobae.quote(inp, DOBAE_2026H2)
    return {ln.key: ln.amount for ln in q.lines if ln.state in COUNTED}


def mokgong_amounts() -> dict[str, int]:
    inp = mokgong.MokgongInput(
        pyeong_to_m2(Decimal(34)), "supply", ("molding", "base", "door", "flatten"), False, doors=3
    )
    q = mokgong.quote(inp, MOKGONG_2026H2)
    return {ln.key: ln.amount for ln in q.lines if ln.state in COUNTED}


def d(prec="band", **over) -> RangeInput:
    return RangeInput("dobae", dobae_amounts(), {"area": prec}, **over)


def test_same_input_same_range_and_order():
    a, b = price_range(d(), R), price_range(d(), R)
    assert a == b
    assert a.low <= a.mid <= a.high
    assert all(x % 10_000 == 0 for x in (a.low, a.mid, a.high))


def test_more_precise_quantity_is_narrower():
    widths = [price_range(d(p), R) for p in ("band", "area", "self", "visit")]
    spans = [r.high - r.low for r in widths]
    assert spans == sorted(spans, reverse=True) and spans[0] > spans[-1]


def test_vendor_priced_is_narrower_than_market():
    market = price_range(d("area"), R)
    vendor = price_range(d("area", vendor_priced=True), R)
    assert vendor.high - vendor.low < market.high - market.low
    assert {p.driver for p in vendor.parts} == {"qty:area", "visit"}


def test_open_condition_raises_only_top_and_yes_raises_both():
    base = price_range(d("area"), R)
    qty = {"removal": Decimal(200)}
    opened = price_range(d("area", conds={"removal": "open"}, cond_qty=qty), R)
    yes = price_range(d("area", conds={"removal": "yes"}, cond_qty=qty), R)
    assert opened.low == base.low and opened.high > base.high
    assert yes.low > base.low and yes.high == opened.high
    assert any(p.driver == "cond:removal" for p in opened.parts)
    assert any("실측 후" in n for n in opened.notes)


def test_small_job_has_minimum_floor():
    tiny = RangeInput("dobae", {"wall": 50_000}, {"area": "self"})
    r = price_range(tiny, R)
    floor_vat = int(R.min_job["dobae"] * (1 + R.vat_rate))
    assert r.low >= floor_vat - 10_000 and r.mid >= floor_vat - 10_000
    assert any("최소 금액" in n for n in r.notes)


def test_exempt_has_no_vat():
    taxed = price_range(d("area"), R)
    exempt = price_range(d("area", exempt=True), R)
    assert exempt.mid < taxed.mid
    assert abs(taxed.mid - exempt.mid * 1.1) <= 20_000


def test_parts_share_width_and_point_to_next_question():
    r = price_range(d("band", conds={"waste": "open"}), R)
    assert abs(sum(p.share for p in r.parts) - 1) <= Decimal("0.03")
    assert [p.share for p in r.parts] == sorted((p.share for p in r.parts), reverse=True)
    qty = next(p for p in r.parts if p.driver == "qty:area")
    assert qty.better == "area" and qty.low_if is not None
    assert qty.high_if - qty.low_if < r.high - r.low  # 면적을 넣으면 좁아진다
    price = next(p for p in r.parts if p.driver == "price")
    assert price.high_if - price.low_if < r.high - r.low  # 가견적을 받으면 좁아진다


def test_mokgong_groups_by_quantity_driver():
    prec = {"edge": "band", "flat": "guess", "door": "self"}
    r = price_range(RangeInput("mokgong", mokgong_amounts(), prec), R)
    drivers = {p.driver for p in r.parts}
    assert {"qty:edge", "qty:flat", "qty:door", "price"} <= drivers
    door = next(p for p in r.parts if p.driver == "qty:door")
    assert door.share == 0  # 문 개수를 알면 문 수량 폭은 없다
    measured = price_range(
        RangeInput("mokgong", mokgong_amounts(), {**prec, "edge": "self", "flat": "self"}), R
    )
    assert measured.high - measured.low < r.high - r.low


def test_every_counted_line_has_a_driver():
    assert set(dobae_amounts(occupied=True)) <= set(QTY_DRIVER["dobae"])
    assert set(mokgong_amounts()) <= set(QTY_DRIVER["mokgong"])
    for trade, groups in R.qty_sigma.items():
        assert set(groups) == set(QTY_DRIVER[trade].values())
        assert all(s >= 0 for g in groups.values() for s in g.values())
    for trade, conds in R.conds.items():
        assert all(c.low <= c.high for c in conds.values())
        assert trade in R.price_sigma and trade in R.min_job


@pytest.mark.parametrize(
    "bad",
    [
        RangeInput("tile", {"wall": 1}, {"area": "band"}),
        RangeInput("dobae", {"wall": -1}, {"area": "band"}),
        RangeInput("dobae", {"unknown": 1}, {"area": "band"}),
        RangeInput("dobae", {"wall": 1}, {}),
        RangeInput("dobae", {"wall": 1}, {"area": "guess"}),
        RangeInput("dobae", {"wall": 1}, {"area": "band"}, conds={"nope": "open"}),
        RangeInput("dobae", {"wall": 1}, {"area": "band"}, conds={"removal": "open"}),
        RangeInput("dobae", {}, {"area": "band"}),
    ],
)
def test_bad_input_is_rejected(bad):
    with pytest.raises(ValueError):
        price_range(bad, R)


def test_condition_state_must_be_known():
    with pytest.raises(ValueError):
        price_range(replace(d(), conds={"waste": "maybe"}), R)
