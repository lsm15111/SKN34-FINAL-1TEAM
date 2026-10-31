"""전기 · 조명 계산 엔진. 기대값은 2026 하반기 기준 단가로 손으로 계산한 값이다."""

from decimal import Decimal
from itertools import product

import pytest

from app.calc import electric
from app.calc.common import pyeong_to_m2
from app.refprice.electric import ELECTRIC_2026H2 as P
from tests.calc_checks import check_quote


def q(**kw) -> electric.ElectricQuote:
    base = {"area_m2": pyeong_to_m2(Decimal(34)), "area_basis": "supply", "occupied": False}
    return electric.quote(electric.ElectricInput(**(base | kw)), P)


def line(r, key):
    return next(ln for ln in r.lines if ln.key == key)


def test_all_lights_and_devices_for_34_pyeong():
    r = q()
    # 공급 112.4㎡ ÷ 1.2 = 전용 93.7㎡ → 조명 ⌈93.7 ÷ 6⌉ = 16, 콘센트 ⌈÷ 2.5⌉ = 38, 스위치 ⌈÷ 5⌉ = 19
    assert (r.lights, r.outlets, r.switches) == (16, 38, 19)
    assert (line(r, "light").amount, line(r, "light_install").amount) == (960_000, 320_000)
    outlet = line(r, "outlet")
    # 콘센트 자재 1,502 + 공동주택 콘센트 설치 23,595 = 25,097원/개, 공공 근거
    assert (outlet.unit_price, outlet.amount, outlet.basis) == (25_097, 953_686, "public")
    switch = line(r, "switch")
    assert (switch.unit_price, switch.amount, switch.basis) == (25_482, 484_158, "assumed")
    assert (r.subtotal, r.vat, r.total) == (2_717_844, 271_784, 2_989_628)
    # 품: 16 × 0.15 + 57 × (21,113 ÷ 276,108) = 6.76 → 2명이면 반나절 7번
    assert [(s.key, s.half_days) for s in r.steps] == [("fixture", 7), ("finish", 1)]
    assert (r.man_days, r.days) == (Decimal(7), Decimal(4))
    assert any("새 아파트를 지을 때 기준" in x for x in r.assumptions)
    assert "ceiling_patch" not in {ln.key for ln in r.lines}


def test_some_devices_downlights_and_new_points():
    r = q(light_type="downlight", outlets="some", outlet_count=10, new_points=3, occupied=True)
    # 일부 10개는 스위치 10 // 3 = 3, 콘센트 7에 새 자리 콘센트 3을 더한다
    assert (r.lights, r.outlets, r.switches) == (38, 10, 3)
    assert line(r, "conduit").qty == Decimal("18.0") and line(r, "conduit").amount == 161_154
    assert line(r, "cable").qty == Decimal("54.0") and line(r, "cable").amount == 149_202
    assert line(r, "box").amount == 110_283  # 3 × 36,761
    assert r.subtotal == 1_888_055
    states = {ln.key: ln.state for ln in r.lines}
    assert states["ceiling_patch"] == states["panel"] == states["moving"] == "after_visit"
    assert [s.key for s in r.steps] == ["prep", "wire", "fixture", "finish"]
    # 배선은 본 작업, 기구 달기는 도배 · 바닥 뒤 작업
    assert [s.key for s in r.steps if s.late] == ["fixture"]


def test_new_points_only():
    r = q(lights="none", outlets="none", new_points=2)
    assert (r.lights, r.outlets, r.switches) == (0, 2, 0)
    assert r.subtotal == 50_194 + 107_436 + 99_468 + 73_522
    assert {ln.key for ln in r.lines} == {"outlet", "conduit", "cable", "box", "panel"}
    assert next(s for s in r.steps if s.key == "fixture").name == "콘센트 달기 (2차)"


def test_every_combination_keeps_the_rules():
    for lights, kind, outlets, points, occupied in product(
        electric.RANGES, electric.LIGHT_TYPES, electric.RANGES, (0, 1, 4), (False, True)
    ):
        if lights == outlets == "none" and points == 0:
            continue
        kw = {
            "lights": lights,
            "light_count": 5,
            "light_type": kind,
            "outlets": outlets,
            "outlet_count": 7,
            "new_points": points,
            "occupied": occupied,
        }
        r = q(**kw)
        check_quote(r)
        assert q(**(kw | {"area_m2": Decimal("150.0")})).total >= r.total
        assert q(**(kw | {"new_points": points + 1})).total >= r.total
        if lights == "some":
            assert q(**(kw | {"light_count": 6})).total >= r.total
        if outlets == "some":
            assert q(**(kw | {"outlet_count": 8})).total >= r.total
        assert all(ln.basis == "assumed" for ln in r.lines if ln.key.startswith("light"))


@pytest.mark.parametrize(
    "kw",
    [
        {"area_m2": Decimal(0)},
        {"area_basis": "pyeong"},
        {"lights": "half"},
        {"light_type": "neon"},
        {"outlets": "many"},
        {"lights": "some", "light_count": 0},
        {"outlets": "some", "outlet_count": 0},
        {"outlets": "some", "outlet_count": electric.MAX_DEVICES + 1},
        {"new_points": -1},
        {"new_points": electric.MAX_POINTS + 1},
        {"lights": "none", "outlets": "none"},
    ],
)
def test_bad_input(kw):
    with pytest.raises(ValueError):
        q(**kw)
