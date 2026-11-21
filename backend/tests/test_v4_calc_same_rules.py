"""가견적과 표준견적서가 같은 수량 · 같은 줄 규칙(ADR docs/v4/adr/0006): 판 2026.11b-market · 2026.11b-remodel.

- 품 = 0.5 올림(표준품셈 품 × 품 배수: 실크 0.91 · 합지 0.91 × 0.55). 두 기준이 같은 값이에요(공정표와 맞춤)
- 금액 줄 값은 앞 판(2026.11-*)과 같아요. 리모델링 식대 줄만 품을 따라가요
- 표준견적서 '선택' 줄(퍼티 · 운송 · 경비)은 가견적에서도 '선택': 금액은 보이고 합계 · 비교 %에는 안 넣어요
기대값은 손으로 검산했다(24평 = 공급 79.3㎡ · 방 3개 → 벽 119.7㎡ · 천장 64.4㎡,
표준품셈 품 = 119.7 × 0.024 + 64.4 × 0.0351 = 5.13324)."""

from decimal import Decimal

import pytest

from app.calc import dobae, estimate
from app.calc.common import COUNTED, pyeong_to_m2, won
from app.calc.space_share import SPACE_SHARE_ROOMS_2026_11
from app.refprice.book import (
    DOBAE_DEFAULT,
    DOBAE_MARKET_2026_11,
    DOBAE_MARKET_2026_11B,
    DOBAE_PROFILES,
    DOBAE_REMODEL_2026_11,
    DOBAE_REMODEL_2026_11B,
    dobae_prices_of,
)
from app.refprice.house import HOUSE_2026H2
from app.refprice.wallpaper_market import paper_market

D = Decimal
PY24 = pyeong_to_m2(D(24))  # 79.3㎡
# 오늘 사용자 흐름의 시험 업체 단가(시장 기준값 근처)
TRIAL = {
    "putty": estimate.PriceV3("price", 15_000),
    "paper_hapji": estimate.PriceV3("price", 4_600),
    "paper_silk": estimate.PriceV3("price", 10_500),
    "material": estimate.PriceV3("price", 6_900),
    "labor": estimate.PriceV3("price", 270_000),
    "meal": estimate.PriceV3("price", 10_000),
    "truck": estimate.PriceV3("price", 50_000),
}


def std(p: dobae.DobaePrices, grade="basic", occupied=False, area=PY24) -> dobae.StandardV3:
    h = dobae.HomeV3(area, "supply", grade, occupied)
    return dobae.standard_v3(h, p, paper_market(grade), SPACE_SHARE_ROOMS_2026_11, HOUSE_2026H2)


def est(v: dobae.StandardV3, grade="basic") -> estimate.EstimateV3:
    keys = {ln.key for ln in v.quote.lines if ln.state in COUNTED}
    return estimate.estimate_v3(
        TRIAL,
        v.qty,
        grade=grade,
        standard_total=v.quote.total,
        standard_keys=keys,
        optional_keys=v.optional_keys,
    )


def rows(q: dobae.DobaeQuote) -> dict:
    return {ln.key: (ln.qty, ln.unit_price, ln.amount, ln.state) for ln in q.lines}


@pytest.mark.parametrize(
    ("grade", "occupied", "man_days", "days"),
    [
        ("basic", False, "5.0", "2.0"),  # 5.13324 × 0.91 = 4.67 → 5.0
        ("basic", True, "5.5", "2.5"),  # ÷ 0.85 = 5.50 → 5.5
        ("economy", False, "3.0", "1.5"),  # × 0.5005 = 2.57 → 3.0
        ("economy", True, "3.5", "2.0"),  # ÷ 0.85 = 3.02 → 3.5
    ],
)
def test_man_days_use_market_ratio(grade, occupied, man_days, days):
    old = std(DOBAE_MARKET_2026_11, grade, occupied).quote
    v = std(DOBAE_MARKET_2026_11B, grade, occupied)
    assert (v.quote.man_days, v.quote.days) == (D(man_days), D(days))
    assert v.qty.man_day == v.quote.man_days  # 가견적 인건비 · 식대 수량 = 공정표 품
    assert old.man_days == (D("6.5") if occupied else D("5.5"))  # 앞 판은 표준품셈 그대로


def test_money_lines_same_as_previous_book():
    """도배만 하는 공사 기준은 줄 값 · 합계가 앞 판과 같아요. 리모델링은 식대 줄(품 × 15,000)만 달라요."""
    for g in ("basic", "economy"):
        for occ in (False, True):
            a, b = std(DOBAE_MARKET_2026_11, g, occ).quote, std(DOBAE_MARKET_2026_11B, g, occ).quote
            assert rows(a) == rows(b) and (a.subtotal, a.total) == (b.subtotal, b.total)
            a, b = (
                std(DOBAE_REMODEL_2026_11, g, occ).quote,
                std(DOBAE_REMODEL_2026_11B, g, occ).quote,
            )
            ra, rb = rows(a), rows(b)
            assert {k: v for k, v in ra.items() if k != "meal"} == {
                k: v for k, v in rb.items() if k != "meal"
            }
            assert rb["meal"][0] == b.man_days and rb["meal"][2] == won(b.man_days * 15_000)
    q = std(DOBAE_REMODEL_2026_11B, "economy").quote
    assert rows(q)["meal"] == (D("3.0"), 15_000, 45_000, "included")  # 앞 판 5.5품 82,500원
    assert (q.subtotal, q.total) == (2_188_793, 2_407_672)


def test_man_days_same_for_both_profiles():
    """공정표 · 표준견적서 기간은 모은 조건 없이 세요(quote.service.calc_trades). 두 기준의 품이 같아야 맞아요."""
    assert DOBAE_PROFILES["paper_only"].md_mult == DOBAE_PROFILES["remodel"].md_mult
    for g in ("basic", "economy"):
        for occ in (False, True):
            a, b = (std(p, g, occ).quote for p in DOBAE_PROFILES.values())
            assert (a.man_days, a.steps, a.days) == (b.man_days, b.steps, b.days)


def test_estimate_optional_lines_follow_standard():
    v = std(DOBAE_MARKET_2026_11B)
    assert v.optional_keys == {"putty", "truck"}
    e = est(v)
    got = {x.row.key: (x.qty, x.amount, x.in_standard, x.optional) for x in e.lines}
    assert got == {
        "putty": (D("24.0"), 360_000, False, True),  # 선택: 금액은 보여요
        "paper_silk": (D("69.5"), 729_750, True, False),
        "material": (D("24.0"), 165_600, True, False),
        "labor": (D("5.0"), 1_350_000, True, False),
        "meal": (D("5.0"), 50_000, False, False),  # 표준에 줄이 없어 비교 %만 빼요
        "truck": (D(1), 50_000, False, True),
    }
    assert (e.supply, e.vat, e.total) == (2_295_350, 229_535, 2_524_885)  # 퍼티 · 운송은 합계 밖
    assert e.compare_total == won(D(729_750 + 165_600 + 1_350_000) * D("1.1"))
    # 앞 판은 옛 규칙 그대로(선택 줄 없음, 표준품셈 품 5.5)
    old = est(std(DOBAE_MARKET_2026_11))
    assert not any(x.optional for x in old.lines) and old.supply == 2_845_350
    # 리모델링 기준은 '선택' 줄이 없어 모두 합계에 있어요
    r = std(DOBAE_REMODEL_2026_11B)
    assert r.optional_keys == frozenset() and not any(x.optional for x in est(r).lines)


def test_optional_keys_are_ignored_for_lines_in_the_total():
    """합계에 드는 표준 줄과 같은 일은 '선택' 키에 있어도 선택이 아니에요."""
    v = std(DOBAE_MARKET_2026_11B)
    keys = {ln.key for ln in v.quote.lines if ln.state in COUNTED}
    e = estimate.estimate_v3(
        TRIAL, v.qty, grade="basic", standard_keys=keys, optional_keys={"putty", "paper"}
    )
    assert {x.row.key for x in e.lines if x.optional} == {"putty"}


@pytest.mark.parametrize(
    ("area", "grade", "occupied", "std_total", "before", "after", "days"),
    [
        # F1 실크 · 32평(공급 105.8㎡) · 살면서: 표준의 1.27배 → 1.04배 (퍼티 48만 · 운송 5만은 선택)
        ("105.8", "basic", True, 3_241_268, 4_117_630, 3_380_630, ("3.0", "3.0")),
        # F3 합지 · 24평(공급 79.3㎡) · 빈 집: 2.24배 → 1.21배, 기간 2일 → 1.5일
        ("79.3", "economy", False, 1_189_804, 2_665_168, 1_444_168, ("2.0", "1.5")),
    ],
)
def test_user_flows(area, grade, occupied, std_total, before, after, days):
    a, b = (
        std(DOBAE_MARKET_2026_11, grade, occupied, D(area)),
        std(DOBAE_MARKET_2026_11B, grade, occupied, D(area)),
    )
    assert a.quote.total == b.quote.total == std_total
    assert (est(a, grade).total, est(b, grade).total) == (before, after)
    assert (str(a.quote.days), str(b.quote.days)) == days


def test_hapji_material_row_matches_standard_material_line():
    """1209 합지 부자재(2026-11-21): 합지 집 가견적 부자재 줄은 표준견적서 부자재 줄과 같은 수량 · 같은 줄(포함)이에요.
    업체가 표준과 같은 값(3,300원)을 넣으면 두 줄 금액이 같아요. 넣지 않은 옛 묶음은 1205 값(6,900원)을 써요."""
    v = std(DOBAE_MARKET_2026_11B, "economy", False, D("79.3"))  # F3 합지 24평 · 빈 집
    line = next(ln for ln in v.quote.lines if ln.key == "material")
    assert (line.qty, line.unit_price, line.amount, line.state) == (
        D("24.0"),
        3_300,
        79_200,
        "included",
    )
    keys = {ln.key for ln in v.quote.lines if ln.state in COUNTED}
    new = estimate.estimate_v3(
        {**TRIAL, "material_hapji": estimate.PriceV3("price", 3_300)},
        v.qty,
        grade="economy",
        standard_total=v.quote.total,
        standard_keys=keys,
        optional_keys=v.optional_keys,
    )
    mat = next(x for x in new.lines if x.row.key == "material_hapji")
    assert (mat.qty, mat.amount, mat.in_standard, mat.optional) == (D("24.0"), 79_200, True, False)
    old = est(v, "economy")  # 옛 묶음(1209 없음): 24.0평 × 6,900 = 165,600
    assert old.total == 1_444_168 and old.total - new.total == 95_040  # 86,400 + 부가세 8,640
    assert new.total == 1_349_128  # 표준 1,189,804의 1.13배(앞 1.21배)


def test_versions_are_fixed():
    assert DOBAE_DEFAULT is DOBAE_MARKET_2026_11B
    assert {p.version for p in DOBAE_PROFILES.values()} == {"2026.11b-market", "2026.11b-remodel"}
    assert all(len(p.version) <= 20 for p in DOBAE_PROFILES.values())  # price_ver varchar(20)
    # 이미 만든 견적의 판은 그 판 그대로 다시 셀 수 있어요(품 배수 · 같은 줄 규칙 없음)
    for old in (DOBAE_MARKET_2026_11, DOBAE_REMODEL_2026_11):
        assert dobae_prices_of(old.version) is old
        assert (old.md_mult, old.same_rules) == (None, False)
    assert dobae_prices_of("2026.11b-remodel") is DOBAE_REMODEL_2026_11B
    assert DOBAE_MARKET_2026_11B.md_mult == {"basic": D("0.91"), "economy": D("0.5005")}
