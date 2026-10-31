"""도장 계산 엔진. 기대값은 2026 하반기 기준 단가로 손으로 계산한 값이다 (DB · HTTP 없음)."""

from decimal import Decimal
from itertools import combinations, product

import pytest

from app.calc import paint
from app.calc.common import COUNTED
from app.refprice.paint import PAINT_2026H2 as P

AREAS = [Decimal(x) / 10 for x in range(150, 3001, 113)]  # 15.0 ~ 297.5㎡
SURFACE_SETS = [c for n in (1, 2, 3, 4) for c in combinations(paint.SURFACES, n)]


def q(**kw) -> paint.PaintQuote:
    base = {
        "area_m2": Decimal("112.4"),
        "area_basis": "supply",
        "surfaces": paint.SURFACES,
        "occupied": False,
        "doors": 3,
    }
    return paint.quote(paint.PaintInput(**(base | kw)), P)


def amounts(r: paint.PaintQuote) -> dict[str, int | None]:
    return {ln.key: ln.amount for ln in r.lines}


def test_everything_34_pyeong_supply_full_putty():
    r = q()
    # 공급 112.4 × 2.5 = 281.0㎡ → 벽 210.75 → 210.8 · 천장 70.25 → 70.3, 문 3 × 4.8, 베란다 34평 × 0.8
    assert (r.wall_m2, r.ceiling_m2, r.door_m2, r.balcony_m2) == (
        Decimal("210.8"),
        Decimal("70.3"),
        Decimal("14.4"),
        Decimal("27.2"),
    )
    a = amounts(r)
    assert a["wall"] == 1_425_008  # 210.8 × 3,380 × 2회
    assert a["ceiling"] == 568_727  # 70.3 × 4,045 × 2회
    assert a["putty_wall"] == 4_055_370  # 210.8 × 19,238 (올퍼티)
    assert a["putty_ceiling"] == 1_639_326  # 70.3 × 23,319
    assert (a["door"], a["door_prep"]) == (180_115, 35_179)  # 14.4 × 6,254 × 2 · 14.4 × 2,443
    # 페인트 (210.8 + 70.3 + 14.4) × 0.11L × 2회 = 65.01 → 65.0L × 3,729
    assert r.paint_l == Decimal("65.0") and a["paint_mat"] == 242_385
    assert (a["balcony"], a["balcony_mat"]) == (275_808, 136_000)  # 27.2 × 3,380 × 3 · × 5,000
    assert (r.subtotal, r.vat, r.total) == (8_557_918, 855_792, 9_413_710)
    # 벽지 제거는 실측 후라 합계에 없다
    removal = next(ln for ln in r.lines if ln.key == "removal")
    assert removal.state == "after_visit" and removal.amount == 485_460  # 281.1 × 1,727
    # 품: 퍼티 20.81 · 칠 8.07 · 베란다 1.01 → 30.0, 도장공 3명
    assert r.man_days == Decimal("30.0")
    assert [(s.key, s.half_days) for s in r.steps] == [
        ("mask", 1),
        ("putty", 14),
        ("paint", 6),
        ("balcony", 1),
        ("finish", 1),
    ]
    assert r.days == Decimal("11.5")
    assert any("업체 일정보다 길게" in x for x in r.assumptions)  # 공공 품셈 기간이라 알린다


def test_doors_only_eco_exclusive_occupied():
    r = q(
        area_m2=Decimal("84.0"),
        area_basis="exclusive",
        surfaces=("door",),
        paint="eco",
        doors=4,
        occupied=True,
    )
    assert (r.wall_m2, r.ceiling_m2, r.door_m2, r.balcony_m2) == (0, 0, Decimal("19.2"), 0)
    a = amounts(r)
    assert (a["door"], a["door_prep"]) == (240_154, 46_906)  # 19.2 × 12,508 · 19.2 × 2,443
    mat = next(ln for ln in r.lines if ln.key == "paint_mat")
    assert mat.qty == Decimal("4.2") and mat.amount == 37_800 and mat.basis == "assumed"
    assert (r.subtotal, r.vat, r.total) == (324_860, 32_486, 357_346)
    assert list(a) == ["door", "door_prep", "paint_mat", "waste", "moving"]
    assert [(s.key, s.half_days) for s in r.steps] == [
        ("prep", 1),
        ("mask", 1),
        ("paint", 1),
        ("finish", 1),
    ]
    assert r.man_days == Decimal("1.5") and r.days == Decimal(2)
    assert any("친환경 수성 페인트값" in x for x in r.assumptions)


def test_ceiling_only_with_spot_putty():
    r = q(surfaces=("ceiling",), putty="spot")
    a = amounts(r)
    assert a["ceiling"] == 568_727
    putty = next(ln for ln in r.lines if ln.key == "putty")
    assert (putty.state, putty.basis, putty.amount) == ("after_visit", "none", None)
    assert a["paint_mat"] == 57_800  # 15.466 → 15.5L × 3,729 = 57,799.5
    assert a["removal"] == 121_408  # 70.3 × 1,727 (실측 후)
    assert (r.subtotal, r.vat, r.total) == (626_527, 62_653, 689_180)
    assert [(s.key, s.half_days) for s in r.steps] == [
        ("mask", 1),
        ("putty", 1),
        ("paint", 2),
        ("finish", 1),
    ]
    assert not any("업체 일정보다 길게" in x for x in r.assumptions)


def test_putty_range_and_paint_grade_order_the_price():
    spot, joint, full = (q(putty=x).subtotal for x in paint.PUTTIES)
    assert spot < joint < full
    assert q(paint="standard").subtotal < q(paint="eco").subtotal
    assert q(doors=5).subtotal > q(doors=3).subtotal
    assert q(balcony_ext=True).wall_m2 > q().wall_m2


@pytest.mark.parametrize(
    "kw",
    [
        {"area_m2": Decimal(0)},
        {"surfaces": ()},
        {"surfaces": ("roof",)},
        {"paint": "oil"},
        {"putty": "none"},
        {"doors": 0},
        {"area_basis": "pyeong"},
    ],
)
def test_bad_input(kw):
    with pytest.raises(ValueError):
        q(**kw)


def test_properties_over_all_combinations():
    combos = product(
        SURFACE_SETS,
        paint.PAINTS,
        paint.PUTTIES,
        ("supply", "exclusive"),
        (False, True),
        (False, True),
    )
    for surfaces, grade, putty, area_basis, occupied, ext in combos:
        prev = None
        for area in AREAS:
            r = q(
                area_m2=area,
                area_basis=area_basis,
                surfaces=surfaces,
                paint=grade,
                putty=putty,
                occupied=occupied,
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
            assert ("prep" in keys) == occupied and "mask" in keys
            assert ("putty" in keys) == any(s in surfaces for s in ("wall", "ceiling"))
            assert ("balcony" in keys) == ("balcony" in surfaces)
            assert all(s.half_days >= 1 for s in r.steps)
            assert r.days == Decimal(sum(s.half_days for s in r.steps)) / 2
            if prev is not None:  # 면적이 커지면 면적 · 금액이 줄지 않는다
                assert r.wall_m2 >= prev.wall_m2 and r.ceiling_m2 >= prev.ceiling_m2
                assert r.total >= prev.total
            prev = r
