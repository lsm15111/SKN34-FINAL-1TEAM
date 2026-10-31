"""인테리어 필름 계산 엔진. 기대값은 2026 하반기 기준 단가로 손으로 계산한 값이다 (DB · HTTP 없음)."""

from decimal import Decimal
from itertools import combinations, product

import pytest

from app.calc import film
from app.calc.common import COUNTED
from app.refprice.film import FILM_2026H2 as P

AREAS = [Decimal(x) / 10 for x in range(150, 3001, 113)]  # 15.0 ~ 297.5㎡
ITEM_SETS = [c for n in range(1, len(film.ITEMS) + 1) for c in combinations(film.ITEMS, n)]


def q(**kw) -> film.FilmQuote:
    base = {
        "area_m2": Decimal("112.4"),
        "area_basis": "supply",
        "items": ("door", "frame", "entrance", "molding"),
        "occupied": False,
        "doors": 3,
    }
    return film.quote(film.FilmInput(**(base | kw)), P)


def amounts(r: film.FilmQuote) -> dict[str, int | None]:
    return {ln.key: ln.amount for ln in r.lines}


def test_doors_frames_entrance_molding_34_pyeong():
    r = q()
    # 방문 3 × 3.8 · 3 × 1.5, 현관 2.1 + 0.8, 몰딩 34평 × 2.4m × 0.1m = 8.16 → 8.2㎡
    assert r.item_m2 == {
        "door": Decimal("11.4"),
        "frame": Decimal("4.5"),
        "entrance": Decimal("2.9"),
        "molding": Decimal("8.2"),
    }
    a = amounts(r)
    assert a["door"] == 261_436  # 11.4 × 22,933 (넓은 면)
    assert a["frame"] == 192_006  # 4.5 × 42,668 (좁은 면 · 틀)
    assert (a["entrance"], a["entrance_frame"]) == (48_159, 34_134)
    assert a["molding"] == 349_878  # 8.2 × 42,668
    assert r.film_m2 == Decimal("35.1") and a["film"] == 280_800  # 27.0 × 1.3 × 8,000
    assert (r.subtotal, r.vat, r.total) == (1_166_413, 116_641, 1_283_054)
    repair = next(ln for ln in r.lines if ln.key == "repair")
    assert (repair.state, repair.basis) == ("after_visit", "none")
    # 품 = (13.5 × 22,266 + 13.5 × 41,426) ÷ 258,904 = 3.32 → 3.5
    assert r.man_days == Decimal("3.5")
    assert [(s.key, s.half_days) for s in r.steps] == [("film", 4), ("finish", 1)]
    assert r.days == Decimal("2.5")


def test_closet_and_kitchen_premium_exclusive_occupied():
    r = q(
        area_m2=Decimal("84.0"),
        area_basis="exclusive",
        items=("closet", "kitchen"),
        grade="premium",
        occupied=True,
        doors=0,
    )
    # 전용 84.0 × 1.2 = 공급 100.8㎡ = 30.5평 → 붙박이장 7.62 → 7.6 · 주방 4.57 → 4.6㎡
    assert r.item_m2 == {"closet": Decimal("7.6"), "kitchen": Decimal("4.6")}
    a = amounts(r)
    assert (a["closet"], a["kitchen"]) == (174_291, 105_492)
    assert r.film_m2 == Decimal("15.9") and a["film"] == 238_500  # 15.86 → 15.9 × 15,000
    assert (r.subtotal, r.vat, r.total) == (518_283, 51_828, 570_111)
    assert list(a) == ["closet", "kitchen", "film", "repair", "moving"]
    assert [(s.key, s.half_days) for s in r.steps] == [("prep", 1), ("film", 2), ("finish", 1)]
    assert r.man_days == Decimal("1.5") and r.days == Decimal(2)
    assert any("전용면적 × 1.2" in x for x in r.assumptions)


def test_film_material_is_assumed_and_labor_is_public():
    r = q()
    basis = {ln.key: ln.basis for ln in r.lines}
    assert basis["film"] == "assumed"
    assert basis["door"] == basis["frame"] == basis["molding"] == "public"
    assert q(grade="premium").subtotal > q().subtotal


@pytest.mark.parametrize(
    "kw",
    [
        {"area_m2": Decimal(0)},
        {"items": ()},
        {"items": ("window",)},
        {"grade": "gold"},
        {"doors": 0},
        {"items": ("frame",), "doors": 0},
        {"area_basis": "pyeong"},
    ],
)
def test_bad_input(kw):
    with pytest.raises(ValueError):
        q(**kw)


def test_properties_over_all_combinations():
    for items, grade, area_basis, occupied, doors in product(
        ITEM_SETS, film.GRADES, ("supply", "exclusive"), (False, True), (1, 4)
    ):
        prev = None
        for area in AREAS:
            r = q(
                area_m2=area,
                area_basis=area_basis,
                items=items,
                grade=grade,
                occupied=occupied,
                doors=doors,
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
            assert set(r.item_m2) == set(items)
            keys = [s.key for s in r.steps]
            assert len(set(keys)) == len(keys) and keys[-1] == "finish"
            assert ("prep" in keys) == occupied
            assert all(s.half_days >= 1 for s in r.steps)
            assert r.days == Decimal(sum(s.half_days for s in r.steps)) / 2
            if prev is not None:  # 면적이 커지면 금액이 줄지 않는다
                assert r.total >= prev.total
            prev = r


def test_more_doors_never_cost_less():
    for items in (("door",), ("frame",), ("door", "frame", "closet")):
        totals = [q(items=items, doors=n).total for n in range(1, 9)]
        assert totals == sorted(totals) and totals[0] < totals[-1]
