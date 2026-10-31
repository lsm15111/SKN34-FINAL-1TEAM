"""타일 계산 엔진. 기대값은 2026 하반기 기준 단가로 손으로 계산한 값이다 (DB · HTTP 없음)."""

from decimal import Decimal
from itertools import combinations, product

import pytest

from app.calc import tile
from app.calc.common import COUNTED
from app.refprice.tile import TILE_2026H2 as P

AREAS = [Decimal(x) / 10 for x in range(150, 3001, 37)]  # 15.0 ~ 300.0㎡
PART_SETS = [c for n in (1, 2, 3) for c in combinations(tile.PARTS, n)]


def q(**kw) -> tile.TileQuote:
    base = {
        "area_m2": Decimal("112.4"),
        "area_basis": "supply",
        "parts": tile.PARTS,
        "size": "medium",
        "method": "remove",
        "occupied": False,
    }
    return tile.quote(tile.TileInput(**(base | kw)), P)


def line(r: tile.TileQuote, key: str):
    return next(ln for ln in r.lines if ln.key == key)


def test_all_parts_34_pyeong_supply_with_removal():
    r = q()
    # 공급 112.4㎡ = 34평 → 주방 벽 4.08 · 현관 2.04 · 베란다 6.80㎡
    assert r.part_m2 == {
        "kitchen": Decimal("4.1"),
        "entrance": Decimal("2.0"),
        "balcony": Decimal("6.8"),
    }
    assert (r.wall_m2, r.floor_m2) == (Decimal("4.1"), Decimal("8.8"))
    assert line(r, "kitchen").amount == 174_553  # 4.1 × 42,574 (압착 벽 중간)
    assert line(r, "entrance").amount == 70_050  # 2.0 × 35,025 (압착 바닥 중간)
    assert line(r, "balcony").amount == 238_170  # 6.8 × 35,025
    assert line(r, "wall_mat").amount == 64_500  # 4.305 → 4.3 × 15,000
    assert line(r, "floor_mat").amount == 174_800  # 9.24 → 9.2 × 19,000
    assert line(r, "sub").amount == 51_600  # 12.9 × 4,000
    assert (r.subtotal, r.vat, r.total) == (773_673, 77_367, 851_040)
    # 바탕 고르기 · 철거 · 폐기물은 실측 후라 합계에 없다
    assert line(r, "base_wall").amount == 55_621 and line(r, "base_floor").amount == 89_021
    assert {ln.state for ln in r.lines if ln.key.startswith(("base_", "remove", "waste"))} == {
        "after_visit"
    }
    # 품 = (4.1 × 41,296 + 8.8 × 33,974) ÷ 294,379 = 1.59 → 2.0
    assert r.man_days == Decimal("2.0")
    assert [(s.key, s.half_days) for s in r.steps] == [
        ("remove", 2),
        ("tile", 2),
        ("cure", 2),
        ("finish", 1),
    ]
    assert r.days == Decimal("3.5")


def test_kitchen_overlay_small_exclusive_occupied():
    r = q(
        area_m2=Decimal("84.0"),
        area_basis="exclusive",
        parts=("kitchen",),
        size="small",
        method="overlay",
        occupied=True,
    )
    # 전용 84.0 × 1.2 = 공급 100.8㎡ = 30.5평 → 주방 벽 3.66 → 3.7㎡
    assert r.part_m2 == {"kitchen": Decimal("3.7")} and r.floor_m2 == 0
    assert line(r, "kitchen").amount == 115_381  # 3.7 × 31,184 (접착 벽 작은)
    assert line(r, "wall_mat").amount == 46_800  # 3.885 → 3.9 × 12,000
    assert line(r, "sub").amount == 14_800
    assert (r.subtotal, r.vat, r.total) == (176_981, 17_698, 194_679)
    assert [ln.key for ln in r.lines] == ["kitchen", "wall_mat", "sub", "waste", "moving"]
    assert [(s.key, s.half_days) for s in r.steps] == [("prep", 1), ("tile", 1), ("finish", 1)]
    assert r.man_days == Decimal("0.5") and r.days == Decimal("1.5")
    assert any("전용면적 × 1.2" in a for a in r.assumptions)


def test_large_tile_material_is_assumed():
    r = q(size="large")
    assert line(r, "wall_mat").basis == line(r, "floor_mat").basis == "assumed"
    assert line(r, "kitchen").basis == "public"
    assert any("팀 가정값" in a for a in r.assumptions)
    assert line(q(size="small"), "floor_mat").basis == "public"


@pytest.mark.parametrize(
    "kw",
    [
        {"area_m2": Decimal(0)},
        {"parts": ()},
        {"parts": ("bath",)},
        {"size": "huge"},
        {"method": "paint"},
        {"area_basis": "pyeong"},
    ],
)
def test_bad_input(kw):
    with pytest.raises(ValueError):
        q(**kw)


def test_properties_over_all_combinations():
    for parts, size, area_basis, occupied in product(
        PART_SETS, tile.SIZES, ("supply", "exclusive"), (False, True)
    ):
        prev = None
        for area in AREAS:
            removed, overlay = (
                q(
                    area_m2=area,
                    area_basis=area_basis,
                    parts=parts,
                    size=size,
                    method=m,
                    occupied=occupied,
                )
                for m in ("remove", "overlay")
            )
            assert removed.subtotal >= overlay.subtotal  # 덧방이 철거 후 붙이기보다 비싸지 않다
            for r in (removed, overlay):
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
                assert ("prep" in keys) == occupied
                assert ("cure" in keys) == any(a in parts for a in tile.FLOOR_PARTS)
                assert all(s.half_days >= 1 for s in r.steps)
                assert r.days == Decimal(sum(s.half_days for s in r.steps)) / 2
            assert "remove" in [s.key for s in removed.steps]
            assert "remove" not in [s.key for s in overlay.steps]
            if prev is not None:  # 면적이 커지면 금액이 줄지 않는다
                assert removed.total >= prev.total
            prev = removed
