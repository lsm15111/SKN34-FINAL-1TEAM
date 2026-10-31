"""욕실 계산 엔진. 기대값은 2026 하반기 기준 단가로 손으로 계산한 값이다."""

from decimal import Decimal
from itertools import product

import pytest

from app.calc import bath
from app.calc.common import pyeong_to_m2
from app.refprice.bath import BATH_2026H2 as P
from tests.calc_checks import check_quote


def q(**kw) -> bath.BathQuote:
    base = {"area_m2": pyeong_to_m2(Decimal(34)), "area_basis": "supply", "occupied": False}
    return bath.quote(bath.BathInput(**(base | kw)), P)


def amounts(r) -> dict[str, int | None]:
    return {ln.key: ln.amount for ln in r.lines}


def test_one_bath_full_remove():
    r = q()
    a = amounts(r)
    # 방수 면적 = 바닥 4.0 + 벽 아랫부분 2.5 = 6.5㎡
    assert a["wp_liquid"] == 123_247  # 6.5 × 18,961 = 123,246.5 → 반올림
    assert a["wp_coat"] == 183_521  # 6.5 × 28,234
    assert a["base_wall"] == 230_622  # 17.0 × 13,566
    assert (a["tile_wall"], a["tile_floor"]) == (723_758, 159_284)  # 17.0 × 42,574 · 4.0 × 39,821
    # 타일 자재는 3% 할증: 17.0 × 1.03 = 17.5㎡ × 15,000 · 4.0 × 1.03 = 4.1㎡ × 12,000
    assert (a["wall_tile_mat"], a["floor_tile_mat"]) == (262_500, 49_200)
    assert (a["drain"], a["ceiling"], a["caulk"]) == (40_250, 180_000, 44_556)  # 12m × 3,713
    assert (a["toilet_basin"], a["faucets"], a["accessories"]) == (400_000, 200_000, 120_000)
    assert (r.subtotal, r.vat, r.total) == (2_716_938, 271_694, 2_988_632)
    states = {ln.key: ln.state for ln in r.lines}
    assert states["demolish"] == states["plumbing"] == states["waste"] == "after_visit"
    assert "moving" not in states and "tub" not in states
    # 타일 품: 17.0 × 41,296 ÷ 467,077 + 4.0 × 38,626 ÷ 467,077 = 1.83 → 타일공 2명이면 반나절 2번
    assert [(s.key, s.half_days) for s in r.steps] == [
        ("demolish", 2),
        ("waterproof", 3),
        ("tile", 4),
        ("fit", 1),
        ("finish", 1),
    ]
    assert (r.days, r.man_days) == (Decimal("5.5"), Decimal(3))
    assert r.version == "2026H2"


def test_overlay_skips_waterproofing_and_uses_overlay_labor():
    full, over = q(), q(tile_method="overlay")
    keys = {ln.key for ln in over.lines}
    assert not keys & {"wp_liquid", "wp_coat", "base_wall"}
    wall = next(ln for ln in over.lines if ln.key == "tile_wall")
    assert wall.unit_price == 28_543 and wall.name == "벽 타일 덧붙이기 (접착)"
    assert over.subtotal < full.subtotal
    assert "waterproof" not in [s.key for s in over.steps]
    assert any("덧방" in x for x in over.assumptions)


def test_fixtures_only_has_no_tile_work():
    r = q(scope="fixtures", baths=2)
    a = amounts(r)
    assert a["toilet_basin"] == 800_000 and a["faucets"] == 400_000
    assert a["caulk"] == 29_704  # 2 × 4m × 3,713
    assert r.subtotal == 1_229_704
    assert not {"tile_wall", "ceiling", "accessories", "plumbing"} & a.keys()
    assert [s.key for s in r.steps] == ["demolish", "fit", "finish"]
    assert (r.floor_m2, r.wall_m2) == (Decimal(0), Decimal(0))


def test_tub_choices():
    new, gone = q(tub="new"), q(tub="remove")
    assert amounts(new)["tub"] == 450_000 and new.subtotal == q().subtotal + 450_000
    part = next(ln for ln in gone.lines if ln.key == "partition")
    # 샤워 파티션은 '선택'이라 금액은 보여 주되 합계에는 넣지 않는다
    assert part.state == "optional" and part.amount == 500_000
    assert gone.subtotal == q().subtotal
    assert "욕조" in next(ln.name for ln in gone.lines if ln.key == "demolish")


def test_occupied_adds_prep_and_moving():
    r = q(occupied=True)
    assert r.steps[0].key == "prep" and r.subtotal == q().subtotal
    assert next(ln for ln in r.lines if ln.key == "moving").state == "after_visit"


def test_every_combination_keeps_the_rules():
    for n, scope, method, tub, ceiling, occupied in product(
        range(1, bath.MAX_BATHS + 1),
        bath.SCOPES,
        bath.TILE_METHODS,
        bath.TUBS,
        bath.CEILINGS,
        (False, True),
    ):
        if scope == "fixtures" and tub == "remove":
            continue
        kw = {
            "baths": n,
            "scope": scope,
            "tile_method": method,
            "tub": tub,
            "ceiling": ceiling,
            "occupied": occupied,
        }
        r = q(**kw)
        check_quote(r)
        if n > 1:
            assert r.total >= q(**(kw | {"baths": n - 1})).total
        assert q(**(kw | {"area_m2": Decimal("150.0")})).total >= r.total
        assert all(ln.basis == "assumed" for ln in r.lines if ln.key in ("toilet_basin", "tub"))


@pytest.mark.parametrize(
    "kw",
    [
        {"area_m2": Decimal(0)},
        {"area_basis": "pyeong"},
        {"baths": 0},
        {"baths": bath.MAX_BATHS + 1},
        {"scope": "half"},
        {"tile_method": "paint"},
        {"tub": "gold"},
        {"ceiling": "wood"},
        {"scope": "fixtures", "tub": "remove"},
    ],
)
def test_bad_input(kw):
    with pytest.raises(ValueError):
        q(**kw)
