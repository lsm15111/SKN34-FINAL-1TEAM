"""도배 계산 엔진. 기대값은 2026 하반기 기준 단가로 손으로 계산한 값이다."""

from decimal import Decimal

import pytest

from app.calc.dobae import DobaeInput, half_up, pyeong_to_m2, quote, won
from app.refprice.book import DOBAE_2026H2 as P


def q(**over):
    inp = {
        "area_m2": pyeong_to_m2(Decimal(34)),
        "area_basis": "supply",
        "grade": "basic",
        "include_ceiling": True,
        "occupied": False,
    }
    return quote(DobaeInput(**(inp | over)), P)


def line(r, key):
    return next(ln for ln in r.lines if ln.key == key)


def test_rounding_helpers():
    assert won(Decimal("0.5")) == 1 and won(Decimal("2.49")) == 2
    assert half_up(Decimal("7.01")) == Decimal("7.5") and half_up(Decimal("7.5")) == Decimal("7.5")
    assert pyeong_to_m2(Decimal(34)) == Decimal("112.4")
    assert P.removal == 1_727  # 0.01인/㎡ × 보통인부 172,698원


def test_34pyeong_silk_with_ceiling_empty_house():
    r = q()
    assert (r.wall_m2, r.ceiling_m2, r.paper_m2) == (
        Decimal("210.7"),
        Decimal("70.3"),
        Decimal("281.0"),
    )
    assert line(r, "wall").amount == 1_262_725
    assert line(r, "ceiling").amount == 599_729
    assert line(r, "paper").qty == Decimal("337.2") and line(r, "paper").amount == 1_121_190
    assert line(r, "primer").amount == 74_802
    assert (r.subtotal, r.vat, r.total) == (3_058_446, 305_845, 3_364_291)
    assert r.man_days == Decimal("8.0") and r.days == Decimal("2.5")
    assert [s.key for s in r.steps] == ["paper", "finish"]
    assert r.version == "2026H2"


def test_only_included_and_separate_lines_count():
    r = q()
    counted = sum(ln.amount for ln in r.lines if ln.state in ("included", "separate"))
    assert counted == r.subtotal
    removal = line(r, "removal")
    assert removal.state == "after_visit" and removal.amount == won(Decimal("281.0") * 1727)
    assert line(r, "waste").amount is None


def test_ceiling_excluded_is_not_counted():
    r = q(include_ceiling=False)
    c = line(r, "ceiling")
    assert c.state == "excluded" and c.amount is None
    assert r.paper_m2 == Decimal("210.7")
    assert r.subtotal < q().subtotal


def test_occupied_adds_surcharge_moving_and_time():
    empty, lived = q(), q(occupied=True)
    surcharge = line(lived, "occupied")
    assert surcharge.state == "included" and surcharge.amount > 0
    assert lived.subtotal == empty.subtotal + surcharge.amount
    assert line(lived, "moving").state == "after_visit"
    assert lived.man_days > empty.man_days and lived.steps[0].key == "prep"


def test_grade_and_basis_change_the_numbers():
    assert line(q(grade="economy"), "paper").unit_price == 1_300
    # 같은 숫자라도 전용면적이면 도배 면적이 더 크다 (환산 계수가 다름)
    assert q(area_basis="exclusive").paper_m2 > q().paper_m2
    assert q(balcony_ext=True).paper_m2 > q().paper_m2


def test_zero_area_is_rejected():
    with pytest.raises(ValueError):
        q(area_m2=Decimal(0))
