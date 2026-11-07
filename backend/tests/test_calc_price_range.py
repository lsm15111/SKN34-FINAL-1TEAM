"""예상 범위: 같은 입력이면 같은 구간, 더 정확히 알수록 좁아짐, 조건 줄은 할 확률만큼, 최소 금액, 폭의 몫."""

from dataclasses import replace
from decimal import Decimal

import pytest

from app.calc import dobae, mokgong
from app.calc.common import COUNTED, pyeong_to_m2
from app.calc.price_range import QTY_DRIVER, RangeInput, price_range, price_range_total
from app.refprice.book import DOBAE_2026H2, MOKGONG_2026H2
from app.refprice.market import RANGE_2026H2 as R


def dobae_amounts(pyeong=32, occupied=False, grade="basic") -> dict[str, int]:
    inp = dobae.DobaeInput(pyeong_to_m2(Decimal(pyeong)), "supply", grade, True, occupied)
    q = dobae.quote(inp, DOBAE_2026H2)
    return {ln.key: ln.amount for ln in q.lines if ln.state in COUNTED}


def mokgong_amounts() -> dict[str, int]:
    inp = mokgong.MokgongInput(
        pyeong_to_m2(Decimal(34)), "supply", ("molding", "base", "door", "flatten"), False, doors=3
    )
    q = mokgong.quote(inp, MOKGONG_2026H2)
    return {ln.key: ln.amount for ln in q.lines if ln.state in COUNTED}


def d(prec="band", **over) -> RangeInput:
    return RangeInput("dobae", dobae_amounts(), {"area": prec}, grade="basic", **over)


def span(r) -> int:
    return r.high - r.low


def test_same_input_same_range_and_order():
    a, b = price_range(d(), R), price_range(d(), R)
    assert a == b
    assert a.low <= a.mid <= a.high
    assert all(x % 10_000 == 0 for x in (a.low, a.mid, a.high))
    assert a.version == "2026H2-r2" and a.extra_max == 0


def test_more_precise_quantity_is_narrower():
    spans = [span(price_range(d(p), R)) for p in ("band", "area", "self", "visit")]
    assert spans == sorted(spans, reverse=True) and spans[0] > spans[-1]


def test_vendor_priced_is_narrower_than_market():
    market = price_range(d("area"), R)
    vendor = price_range(d("area", vendor_priced=True), R)
    assert span(vendor) < span(market)
    assert {p.driver for p in vendor.parts} == {"qty:area", "visit"}


def test_market_center_follows_grade():
    # 공공 기준이 시장보다 높게 나오는 합지는 중심을 더 낮춘다(시장 중심 ÷ 공공 기준 0.65 < 0.85)
    basic = price_range(RangeInput("dobae", dobae_amounts(), {"area": "area"}, grade="basic"), R)
    eco_amounts = dobae_amounts(grade="economy")
    eco = price_range(RangeInput("dobae", eco_amounts, {"area": "area"}, grade="economy"), R)
    no_grade = price_range(RangeInput("dobae", eco_amounts, {"area": "area"}), R)
    assert eco.mid < no_grade.mid  # 등급 키(0.65)가 공정 키(0.80)보다 먼저
    assert basic.mid > eco.mid


def test_condition_probability_moves_the_range():
    qty = {"removal": Decimal(280)}
    base = price_range(d("area"), R)
    no = price_range(d("area", conds={"removal": "open"}, cond_qty=qty, cond_p={"removal": 0}), R)
    half = price_range(d("area", conds={"removal": "open"}, cond_qty=qty), R)
    yes = price_range(d("area", conds={"removal": "yes"}, cond_qty=qty), R)
    assert (no.low, no.high) == (base.low, base.high)
    assert base.low <= half.low <= yes.low and base.high < half.high <= yes.high
    # 다 하면 최대 280㎡ × 2,900원 × 부가세 = 893,200 → 만 원 올림. 하기로 했으면 구간에 들어가 따로 안 보임
    assert half.extra_max == 900_000 and yes.extra_max == 0
    assert any("실측 후" in n for n in half.notes)


def test_condition_part_reports_both_outcomes():
    r = price_range(d("area", conds={"removal": "open"}, cond_qty={"removal": Decimal(280)}), R)
    cond = next(p for p in r.parts if p.driver == "cond:removal")
    assert cond.share > 0
    assert (
        cond.low_if > cond.low_if_no and cond.high_if > cond.high_if_no
    )  # 하면 위로, 안 하면 아래로


def test_small_job_has_minimum_floor():
    r = price_range(RangeInput("dobae", {"wall": 50_000}, {"area": "self"}, grade="basic"), R)
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
    assert qty.better == "area" and qty.high_if - qty.low_if < span(r)  # 면적을 넣으면 좁아진다
    price = next(p for p in r.parts if p.driver == "price")
    assert price.high_if - price.low_if < span(r)  # 가견적을 받으면 좁아진다
    assert price.share > qty.share  # 표준견적서 폭은 업체 단가 차이가 가장 크다(T4)


def test_explain_off_skips_parts_but_keeps_range():
    full, quick = price_range(d("area"), R), price_range(d("area"), R, explain=False)
    assert (quick.low, quick.mid, quick.high) == (full.low, full.mid, full.high)
    assert quick.parts == ()


def test_mokgong_groups_by_quantity_driver():
    prec = {"edge": "band", "flat": "guess", "door": "self"}
    r = price_range(RangeInput("mokgong", mokgong_amounts(), prec), R)
    drivers = {p.driver for p in r.parts}
    assert {"qty:edge", "qty:flat", "qty:door", "price"} <= drivers
    assert next(p for p in r.parts if p.driver == "qty:door").share == 0  # 문 개수를 알면 폭이 없다
    measured = price_range(
        RangeInput("mokgong", mokgong_amounts(), {**prec, "edge": "self", "flat": "self"}), R
    )
    assert span(measured) < span(r)


def test_every_counted_line_has_a_driver_and_rules_are_complete():
    assert set(dobae_amounts(occupied=True)) <= set(QTY_DRIVER["dobae"])
    assert set(mokgong_amounts()) <= set(QTY_DRIVER["mokgong"])
    for trade, groups in R.qty_sigma.items():
        assert set(groups) == set(QTY_DRIVER[trade].values())
        assert all(s >= 0 for g in groups.values() for s in g.values())
        for table in (R.price_sigma, R.price_center, R.visit_sigma, R.min_job):
            assert trade in table
    for conds in R.conds.values():
        assert all(c.low <= c.high and 0 <= c.p <= 1 and c.source for c in conds.values())


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
        RangeInput(
            "dobae",
            {"wall": 1},
            {"area": "band"},
            conds={"waste": "open"},
            cond_p={"waste": Decimal(2)},
        ),
        RangeInput("dobae", {}, {"area": "band"}),
    ],
)
def test_bad_input_is_rejected(bad):
    with pytest.raises(ValueError):
        price_range(bad, R)


def test_condition_state_must_be_known():
    with pytest.raises(ValueError):
        price_range(replace(d(), conds={"waste": "maybe"}), R)


def test_chosen_space_share_widens_and_measuring_rooms_narrows():
    whole = price_range(d("area"), R)
    part = price_range(d("area", share_sigma={"area": Decimal("0.2")}), R)
    assert span(part) > span(whole)
    sh = next(p for p in part.parts if p.driver == "share:area")
    assert sh.better == "self" and sh.high_if - sh.low_if < span(part)  # 고른 방을 재면 좁아진다
    with pytest.raises(ValueError):
        price_range(d("area", share_sigma={"area": Decimal(-1)}), R)


def test_small_job_scales_lump_conditions_with_a_floor():
    scaled = replace(R.conds["dobae"]["waste"], min_scale=Decimal("0.3"))
    rules = replace(R, conds={**R.conds, "dobae": {**R.conds["dobae"], "waste": scaled}})
    full = price_range(d("area", conds={"waste": "open"}), rules)
    small = price_range(d("area", conds={"waste": "open"}, job_share=Decimal("0.1")), rules)
    # 폐기물 최대 20만 원 → 공사 몫 0.1이어도 최소 비율 0.3: 6만 원 × 부가세 = 6만 6천 → 만 원 올림
    assert full.extra_max == 220_000 and small.extra_max == 70_000
    with pytest.raises(ValueError):
        price_range(d("area", conds={"waste": "open"}, job_share=Decimal(0)), rules)


def test_total_range_sits_between_independent_and_added_ranges():
    dob = d("area")
    mok = RangeInput(
        "mokgong", mokgong_amounts(), {"edge": "area", "flat": "guess", "door": "self"}
    )
    a, b = price_range(dob, R), price_range(mok, R)
    tot = price_range_total([dob, mok], R)
    assert tot.trade == "total" and tot.parts == ()
    # 오른쪽으로 긴 분포라 합의 가운데는 가운데끼리 더한 값보다 조금 크다
    assert a.mid + b.mid - 10_000 <= tot.mid <= (a.mid + b.mid) * 1.03
    assert span(tot) <= span(a) + span(b)  # 둘이 늘 같이 움직이지는 않는다
    assert span(tot) >= max(span(a), span(b))
    loose = price_range_total([dob, mok], replace(R, trade_corr=Decimal(0)))
    tight = price_range_total([dob, mok], replace(R, trade_corr=Decimal(1)))
    assert span(loose) <= span(tot) <= span(tight)
    one = price_range_total([dob], R)
    assert (one.low, one.mid, one.high) == (a.low, a.mid, a.high)
    with pytest.raises(ValueError):
        price_range_total([dob, dob], R)
    with pytest.raises(ValueError):
        price_range_total([], R)


def test_small_job_adds_fixed_cost_and_wider_price_spread():
    amounts = dobae_amounts()
    part = {k: v * 14 // 100 for k, v in amounts.items()}  # 작은방 하나(집 전체의 14%)
    base = RangeInput("dobae", part, {"area": "area"}, grade="basic")
    small = replace(base, job_share=Decimal("0.14"), fixed_key="dobae.basic")
    a, b = price_range(base, R), price_range(small, R)
    # 고정비 15만 × (1 − 0.14) × 부가세 1.1 = 약 14만 원을 중심에 더한다
    assert b.fixed_add == 140_000 and b.mid - a.mid >= 120_000
    assert any("고정비" in n for n in b.notes)
    assert (b.high - b.low) / b.mid > (a.high - a.low) / a.mid  # 방 1칸 단가 흩어짐 × 1.3
    whole = price_range(replace(d("area"), fixed_key="dobae.basic"), R)
    assert (
        whole.fixed_add == 0 and whole.mid == price_range(d("area"), R).mid
    )  # 집 전체엔 이미 녹아 있다
    vendor = price_range(replace(small, vendor_priced=True), R)
    assert vendor.fixed_add == 140_000  # 업체 단가 × 수량에도 고정비는 빠져 있다
    with pytest.raises(ValueError):
        price_range(replace(small, fixed_key="nope"), R)
