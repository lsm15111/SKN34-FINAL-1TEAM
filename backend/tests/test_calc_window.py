"""창호 계산 엔진. 기대값은 2026 하반기 기준 단가로 손으로 계산한 값이다."""

from decimal import Decimal
from itertools import product

import pytest

from app.calc import window
from app.calc.common import pyeong_to_m2
from app.refprice.window import WINDOW_2026H2 as P
from tests.calc_checks import check_quote


def q(**kw) -> window.WindowQuote:
    base = {"area_m2": pyeong_to_m2(Decimal(34)), "area_basis": "supply", "occupied": False}
    return window.quote(window.WindowInput(**(base | kw)), P)


def amounts(r) -> dict[str, int | None]:
    return {ln.key: ln.amount for ln in r.lines}


def test_all_pvc_low_e_for_34_pyeong():
    r = q()
    # 공급 112.4㎡ ÷ 1.2 = 전용 93.7㎡ → 창 9개 × 4.3㎡ = 38.7㎡, 유리 38.7 × 0.75 × 2겹 = 58.1㎡
    assert (r.windows, r.frame_m2, r.glass_m2) == (9, Decimal("38.7"), Decimal("58.1"))
    a = amounts(r)
    assert a["frame"] == 3_870_000  # 38.7 × 100,000 (가정값)
    assert a["frame_install"] == 933_057  # 9 × 103,673
    assert a["glass"] == 3_000_575  # 58.1 × 51,645 = 3,000,574.5 → 반올림
    assert a["glass_install"] == 1_499_387  # 58.1 × 25,807
    assert a["seal"] == 280_703  # 9 × 8.4m × 3,713
    assert (r.subtotal, r.vat, r.total) == (9_583_722, 958_372, 10_542_094)
    basis = {ln.key: ln.basis for ln in r.lines}
    assert basis["frame"] == "assumed" and basis["frame_install"] == basis["glass"] == "public"
    states = {ln.key: ln.state for ln in r.lines}
    assert states["demolish"] == states["lift"] == states["trim"] == "after_visit"
    # 설치 품 9 × 0.405 + 58.1 × 0.097 = 9.27 → 4명이면 반나절 5번
    assert [(s.key, s.half_days) for s in r.steps] == [("remove", 1), ("install", 5), ("finish", 1)]
    assert (r.man_days, r.days) == (Decimal("11.5"), Decimal("3.5"))


def test_balcony_extension_drops_inner_windows():
    plain, ext = q(), q(balcony_ext=True)
    assert ext.windows == plain.windows - P.ext_fewer
    assert ext.total < plain.total
    assert any("안쪽 창" in x for x in ext.assumptions)
    # 일부만 바꾸면 고른 개수 그대로 쓴다
    assert q(scope="some", count=3, balcony_ext=True).windows == 3


def test_system_window_has_no_separate_install_and_one_glass_layer():
    r = q(frame="system")
    keys = {ln.key for ln in r.lines}
    assert "frame_install" not in keys
    assert r.glass_m2 == Decimal("29.0")  # 38.7 × 0.75 × 1겹 = 29.025 → 29.0
    assert amounts(r)["frame"] == 15_480_000 and r.total > q().total
    assert any("설치까지 넣은" in x for x in r.assumptions)


def test_clear_glass_is_cheaper():
    assert next(ln for ln in q(glass="clear").lines if ln.key == "glass").unit_price == 35_721
    assert q(glass="clear").total < q().total


def test_every_combination_keeps_the_rules():
    for scope, frame, glass, ext, occupied in product(
        window.SCOPES, window.FRAMES, window.GLASSES, (False, True), (False, True)
    ):
        kw = {
            "scope": scope,
            "count": 4,
            "frame": frame,
            "glass": glass,
            "balcony_ext": ext,
            "occupied": occupied,
        }
        r = q(**kw)
        check_quote(r)
        assert r.windows >= 1 and (r.steps[0].key == "prep") == occupied
        assert q(**(kw | {"area_m2": Decimal("150.0")})).total >= r.total
        assert q(**(kw | {"area_m2": Decimal("20.0")})).windows >= 1
        if scope == "some":
            assert q(**(kw | {"count": 5})).total >= r.total


@pytest.mark.parametrize(
    "kw",
    [
        {"area_m2": Decimal(0)},
        {"area_basis": "pyeong"},
        {"scope": "half"},
        {"frame": "wood"},
        {"glass": "triple"},
        {"scope": "some", "count": 0},
        {"scope": "some", "count": window.MAX_WINDOWS + 1},
    ],
)
def test_bad_input(kw):
    with pytest.raises(ValueError):
        q(**kw)
