"""바닥재 계산 엔진. 기대값은 2026 하반기 기준 단가로 손으로 계산한 값이다 (DB · HTTP 없음)."""

from decimal import Decimal
from itertools import product

import pytest

from app.calc import floor
from app.calc.common import COUNTED
from app.refprice.floor import FLOOR_2026H2 as P

AREAS = [Decimal(x) / 10 for x in range(150, 3001, 37)]  # 15.0 ~ 300.0㎡


def q(**kw) -> floor.FloorQuote:
    base = {
        "area_m2": Decimal("112.4"),
        "area_basis": "supply",
        "kind": "engineered",
        "occupied": False,
    }
    return floor.quote(floor.FloorInput(**(base | kw)), P)


def line(r: floor.FloorQuote, key: str):
    return next(ln for ln in r.lines if ln.key == key)


def test_engineered_34_pyeong_supply_with_removal():
    r = q()
    # 공급 112.4㎡ ÷ 1.2 = 전용 93.7㎡ × 0.8 = 바닥 75.0㎡
    assert r.floor_m2 == Decimal("75.0")
    assert line(r, "lay").amount == 930_600  # 75.0 × 12,408
    mat = line(r, "mat")
    assert mat.qty == Decimal("78.8") and mat.amount == 1_733_600  # 78.75 → 78.8 × 22,000
    assert mat.basis == "assumed"
    level = line(r, "level")  # 평탄화는 실측 후라 합계에 없다
    assert level.state == "after_visit" and level.amount == 1_004_325  # 75.0 × 13,391
    assert (r.subtotal, r.vat, r.total) == (2_664_200, 266_420, 2_930_620)
    # 품 = 75.0 × 11,663 ÷ 257,926 = 3.39 → 3.5, 마루공 2명이면 반나절 4번
    assert r.man_days == Decimal("3.5")
    assert [(s.key, s.half_days) for s in r.steps] == [("remove", 2), ("lay", 4), ("finish", 1)]
    assert not any(s.late for s in r.steps)  # 마루는 도배 앞에 하는 본 작업
    assert r.days == Decimal("3.5")
    states = {ln.key: ln.state for ln in r.lines}
    assert states["remove"] == states["waste"] == "after_visit" and "moving" not in states


def test_thin_vinyl_exclusive_occupied_without_removal():
    r = q(
        area_m2=Decimal("84.0"),
        area_basis="exclusive",
        kind="vinyl_18",
        occupied=True,
        remove=False,
    )
    assert r.floor_m2 == Decimal("67.2")  # 84.0 × 0.8
    assert line(r, "lay").amount == 489_283  # 67.2 × 7,281 = 489,283.2
    mat = line(r, "mat")
    assert mat.qty == Decimal("73.9") and mat.amount == 778_167  # 73.92 → 73.9 × 10,530
    assert mat.basis == "public"
    assert (r.subtotal, r.vat, r.total) == (1_267_450, 126_745, 1_394_195)
    keys = [ln.key for ln in r.lines]
    assert "remove" not in keys and "level" not in keys and "sub" not in keys
    assert line(r, "moving").state == "after_visit"
    assert [(s.key, s.half_days) for s in r.steps] == [("prep", 1), ("lay", 2), ("finish", 1)]
    assert [s.key for s in r.steps if s.late] == ["lay"]  # 장판은 도배가 끝난 뒤에 깐다
    assert r.man_days == Decimal("2.0") and r.days == Decimal(2)
    assert not any("전용면적은" in a for a in r.assumptions)


def test_decotile_34_pyeong_supply():
    r = q(kind="decotile")
    lay = line(r, "lay")
    assert lay.amount == 1_223_100 and lay.basis == "public"  # 75.0 × 16,308
    mat = line(r, "mat")
    assert mat.qty == Decimal("78.8") and mat.amount == 1_347_480  # 78.75 → 78.8 × 17,100
    assert mat.basis == "public"
    assert line(r, "level").state == "after_visit"
    assert (r.subtotal, r.vat, r.total) == (2_570_580, 257_058, 2_827_638)
    # 품 = 75.0 × 15,166 ÷ 258,904 = 4.39 → 4.5, 2명이면 반나절 5번. 도배 앞에 하는 본 작업
    assert r.man_days == Decimal("4.5")
    assert [(s.key, s.half_days, s.late) for s in r.steps] == [
        ("remove", 2, False),
        ("lay", 5, False),
        ("finish", 1, False),
    ]
    assert r.days == Decimal(4)
    assert any("데코타일 시공비" in a for a in r.assumptions)


def test_porcelain_with_balcony_extension():
    r = q(kind="porcelain", balcony_ext=True)
    assert r.floor_m2 == Decimal("86.2")  # 93.7 × 0.8 × 1.15 = 86.204
    assert line(r, "lay").amount == 2_743_056  # 86.2 × 31,822
    assert line(r, "mat").amount == 2_624_500  # 90.51 → 90.5 × 29,000
    assert line(r, "sub").amount == 344_800  # 86.2 × 4,000
    assert (r.subtotal, r.vat, r.total) == (5_712_356, 571_236, 6_283_592)
    assert [(s.key, s.half_days) for s in r.steps] == [
        ("remove", 2),
        ("lay", 10),
        ("cure", 2),
        ("finish", 1),
    ]
    assert any("1.15배" in a for a in r.assumptions)


def test_supply_and_exclusive_give_the_same_floor():
    assert q().floor_m2 == q(area_m2=Decimal("93.7"), area_basis="exclusive").floor_m2


def test_kinds_are_ordered_by_price():
    total = {k: q(kind=k).subtotal for k in floor.KINDS}
    assert total["vinyl_18"] < total["vinyl_22"] < total["laminate"] < total["engineered"]
    assert total["vinyl_22"] < total["decotile"] < total["engineered"] < total["porcelain"]


@pytest.mark.parametrize(
    "kw",
    [
        {"area_m2": Decimal(0)},
        {"area_m2": Decimal(-1)},
        {"kind": "marble"},
        {"area_basis": "pyeong"},
    ],
)
def test_bad_input(kw):
    with pytest.raises(ValueError):
        q(**kw)


def test_properties_over_all_combinations():
    combos = list(
        product(floor.KINDS, ("supply", "exclusive"), (False, True), (False, True), (False, True))
    )
    for kind, area_basis, occupied, remove, ext in combos:
        prev = None
        for area in AREAS:
            r = q(
                area_m2=area,
                area_basis=area_basis,
                kind=kind,
                occupied=occupied,
                remove=remove,
                balcony_ext=ext,
            )
            counted = [ln.amount for ln in r.lines if ln.state in COUNTED]
            assert None not in counted
            assert r.subtotal == sum(counted) and r.total == r.subtotal + r.vat
            for ln in r.lines:
                assert ln.basis in ("public", "assumed", "none")
                assert (ln.basis == "assumed") == ln.source.startswith("팀 가정값")
                if ln.basis == "none":
                    assert ln.unit_price is None and ln.amount is None
                assert all(v is None or v >= 0 for v in (ln.qty, ln.unit_price, ln.amount))
            assert len({ln.key for ln in r.lines}) == len(r.lines)
            keys = [s.key for s in r.steps]
            assert len(set(keys)) == len(keys) and keys[-1] == "finish"
            assert ("prep" in keys) == occupied and ("remove" in keys) == remove
            late = [s.key for s in r.steps if s.late]
            assert late == (["lay"] if floor.GROUP[kind] == "vinyl" else [])
            assert all(s.half_days >= 1 for s in r.steps)
            assert r.days == Decimal(sum(s.half_days for s in r.steps)) / 2
            assert r.man_days >= 0 and r.version == "2026H2"
            if prev is not None:  # 면적이 커지면 금액 · 면적이 줄지 않는다
                assert r.floor_m2 >= prev.floor_m2 and r.total >= prev.total
            prev = r
