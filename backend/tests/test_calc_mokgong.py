"""목공 계산 엔진과 공정 잇기. DB · HTTP 없이 순수 함수만 본다."""

from decimal import Decimal

import pytest

from app.calc import dobae, mokgong
from app.calc.sequence import sequence
from app.refprice.book import DOBAE_2026H2, MOKGONG_2026H2

P = MOKGONG_2026H2
ALL = ("molding", "base", "door", "flatten")


def q(**kw) -> mokgong.MokgongQuote:
    base = {
        "area_m2": Decimal("112.4"),
        "area_basis": "supply",
        "items": ALL,
        "occupied": False,
        "doors": 3,
    }
    return mokgong.quote(mokgong.MokgongInput(**(base | kw)), P)


def amounts(r: mokgong.MokgongQuote) -> dict[str, int | None]:
    return {ln.key: ln.amount for ln in r.lines}


def test_all_items_for_34_pyeong_supply():
    r = q()
    # 공급 112.4㎡ = 34평 → 몰딩 81.6m · 걸레받이 61.2m, 전용 93.7㎡ × 0.3 = 평탄화 28.1㎡
    assert (r.molding_m, r.base_m, r.flatten_m2, r.doors) == (
        Decimal("81.6"),
        Decimal("61.2"),
        Decimal("28.1"),
        3,
    )
    a = amounts(r)
    assert a["molding"] == 666_509 and a["molding_mat"] == 269_400  # 81.6 × 8,168 · 89.8m × 3,000
    assert a["base"] == 229_928 and a["base_mat"] == 127_200  # 61.2 × 3,757 · 63.6m × 2,000
    assert (a["frame"], a["board"], a["ceiling_mat"]) == (310_617, 363_530, 224_800)
    assert a["door"] == 1_290_330  # 3 × 430,110
    assert (r.subtotal, r.vat, r.total) == (3_482_314, 348_231, 3_830_545)
    # 철거 · 폐기물은 실측 후라 합계에 없다
    states = {ln.key: ln.state for ln in r.lines}
    assert states["remove_ceiling"] == states["remove_trim"] == states["waste"] == "after_visit"
    assert "moving" not in states
    assert r.man_days == Decimal(7)
    assert [(s.key, s.half_days) for s in r.steps] == [
        ("remove", 1),
        ("ceiling", 3),
        ("door", 1),
        ("trim", 4),
        ("finish", 1),
    ]
    assert r.days == Decimal(5)


def test_door_leaf_only_and_exclusive_area():
    r = q(items=("door",), doors=2, door_frame=False, area_basis="exclusive", occupied=True)
    a = amounts(r)
    assert a["door"] == 2 * 255_954 and r.subtotal == 511_908
    names = {ln.key: ln.name for ln in r.lines}
    assert names["door"] == "방문 교체 (문짝만)" and "moving" in names
    assert "remove_trim" not in names and "frame" not in names
    assert [s.key for s in r.steps] == ["prep", "door", "finish"]
    assert any("전용면적 × 1.2" in x for x in r.assumptions)


def test_exclusive_area_is_converted_to_supply_for_lengths():
    sup = q(items=("molding",))
    exc = q(items=("molding",), area_m2=Decimal("93.7"), area_basis="exclusive")
    # 전용 93.7㎡ × 1.2 = 공급 112.4㎡라서 같은 길이가 나온다
    assert sup.molding_m == exc.molding_m == Decimal("81.6")


@pytest.mark.parametrize(
    "kw",
    [{"area_m2": Decimal(0)}, {"items": ()}, {"items": ("door",), "doors": 0}],
)
def test_bad_input(kw):
    with pytest.raises(ValueError):
        q(**kw)


def test_sequence_puts_carpentry_before_wallpaper():
    d = dobae.quote(
        dobae.DobaeInput(Decimal("112.4"), "supply", "basic", True, occupied=True), DOBAE_2026H2
    )
    m = q(items=("molding", "base"), occupied=True)
    steps, days = sequence({"dobae": d.steps, "mokgong": m.steps})
    # 짐 정리는 처음 한 번, 목공 정리 · 청소는 도배 마감에 합친다
    assert [(s.trade, s.key) for s in steps] == [
        ("mokgong", "prep"),
        ("mokgong", "remove"),
        ("mokgong", "trim"),
        ("dobae", "paper"),
        ("dobae", "finish"),
    ]
    assert days == Decimal(sum(s.half_days for s in steps)) / 2

    only, only_days = sequence({"mokgong": m.steps})
    assert [s.key for s in only] == [s.key for s in m.steps] and only_days == m.days
