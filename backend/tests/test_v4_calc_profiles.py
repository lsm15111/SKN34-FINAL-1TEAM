"""v4 조건별 두 기준(ADR docs/v4/adr/0004): 기준 고르기 · 줄 구조 · 합지 시공비 · 선택 줄 · 판 고정.
기대값은 손으로 검산했다(24평 = 공급 79.3㎡, 방 3개 → 벽 119.7㎡ · 천장 64.4㎡)."""

from decimal import Decimal

import pytest

from app.agent.v3.trades import SPECS
from app.calc import dobae, estimate
from app.calc.common import COUNTED, pyeong_to_m2, won
from app.calc.space_share import SPACE_SHARE_ROOMS_2026_11
from app.refprice.book import (
    DOBAE_DEFAULT,
    DOBAE_MARKET_2026_11,
    DOBAE_PROFILES,
    DOBAE_REMODEL_2026_11,
    DOBAE_V3_2026_11,
    dobae_prices_of,
)
from app.refprice.house import HOUSE_2026H2
from app.refprice.wallpaper_market import paper_market

D = Decimal
PY24 = pyeong_to_m2(D(24))  # 79.3㎡


def std(h: dobae.HomeV3, p: dobae.DobaePrices, why=()) -> dobae.StandardV3:
    return dobae.standard_v3(
        h, p, paper_market(h.grade), SPACE_SHARE_ROOMS_2026_11, HOUSE_2026H2, why
    )


def home(grade: str = "basic", occupied: bool = False, **kw) -> dobae.HomeV3:
    return dobae.HomeV3(PY24, "supply", grade, occupied, **kw)  # type: ignore[arg-type]


def rows(q: dobae.DobaeQuote) -> dict:
    return {ln.key: (ln.qty, ln.unit, ln.unit_price, ln.amount, ln.state) for ln in q.lines}


# ---- 기준 고르기 ----


def pick(items=()) -> dobae.ProfilePick:
    return dobae.pick_profile(dobae.WorkFacts(tuple(items)))


def test_no_conditions_is_paper_only():
    assert pick() == dobae.ProfilePick("paper_only", ())
    assert DOBAE_DEFAULT is DOBAE_MARKET_2026_11  # 공사 조건이 없는 계산(손님 · 평수 질문)


def test_molding_or_base_only_is_paper_only():
    """몰딩 · 걸레받이만 바꾸는 집은 흔한 가벼운 공사라 도배만 하는 공사 기준이에요(리드 결정)."""
    w = dobae.WorkFacts
    assert pick(["molding", "base"]) == dobae.ProfilePick("paper_only", ())
    assert pick(["base"]).profile == "paper_only"
    said = {"mokgong.molding": "바꿔요", "mokgong.molding_scope": "도배만 새로"}
    assert dobae.pick_profile(w(("molding",), said)).profile == "paper_only"
    # 몰딩을 바꿔도 문틀 · 천장이 같이 있으면 리모델링이고, 근거에 몰딩은 안 적어요
    assert dobae.pick_profile(w(("molding", "door"))).why == ("문틀 교체",)


@pytest.mark.parametrize(
    ("items", "said", "why"),
    [
        (["door"], {}, ("문틀 교체",)),
        (["flatten"], {}, ("천장 평탄화",)),
        ([], {"mokgong.doors": "문틀까지"}, ("문틀 교체",)),
        ([], {"mokgong.ceiling": "네"}, ("천장 평탄화",)),
        ([], {"mokgong.molding_scope": "벽 · 천장까지 새로"}, ("'벽 · 천장까지 새로'",)),
        (["door", "flatten", "molding"], {}, ("문틀 교체", "천장 평탄화")),
    ],
)
def test_big_carpentry_or_full_scope_is_remodel(items, said, why):
    got = dobae.pick_profile(dobae.WorkFacts(tuple(items), said))
    assert got == dobae.ProfilePick("remodel", why)


def test_said_answer_wins_over_project_item():
    """모은 조건(고객이 고른 단추)이 같은 일의 목공 항목보다 먼저예요. '아직 몰라요' · 단추가 아닌 답은 항목을 봐요"""
    w = dobae.WorkFacts
    assert dobae.pick_profile(w(("door",), {"mokgong.doors": "문짝만"})).profile == "paper_only"
    assert dobae.pick_profile(w(("flatten",), {"mokgong.ceiling": "아니요"})).why == ()
    assert dobae.pick_profile(w(("door",), {"mokgong.doors": "아직 몰라요"})).why == ("문틀 교체",)
    assert dobae.pick_profile(w((), {"mokgong.doors": "글쎄요"})).profile == "paper_only"
    # 띄어쓰기만 다른 단추 글은 같은 답
    assert dobae.pick_profile(w((), {"mokgong.doors": " 문틀까지 "})).profile == "remodel"


def test_signal_values_are_the_agent_buttons():
    """기준 고르기가 읽는 값은 되묻기 단추 글과 같아야 해요(글이 바뀌면 이 테스트가 잡아요)."""
    options = {s.key: set(s.options) for spec in SPECS for s in spec.slots}
    for _, item, key, yes, no in dobae.REMODEL_SIGNALS:
        assert {yes, no} <= options[key], key
        assert item in ("door", "flatten")
    assert dobae.SCOPE_ALL in options[dobae.SCOPE_KEY]


# ---- 도배만 하는 공사 기준 (시장 가운데, 추천안 R) ----


def test_paper_only_silk_24py():
    v = std(home(), DOBAE_MARKET_2026_11)
    q = v.quote
    assert rows(q) == {
        "wall": (D("119.7"), "㎡", 5_993, 717_362, "included"),
        "ceiling": (D("64.4"), "㎡", 8_531, 549_396, "included"),
        # 184.1㎡ × 1.248(실크 × 1.04) = 229.8㎡ → ÷ 3.3058 = 69.5 벽지 평 × 10,749
        "paper": (D("69.5"), "벽지 평", 10_749, 747_056, "included"),
        "material": (D("24.0"), "공급 평", 6_900, 165_600, "included"),  # 초배지 줄 대신
        "putty": (D("24.0"), "공급 평", 14_264, 342_336, "optional"),  # 합계 밖
        "truck": (D("1.0"), "식", 50_000, 50_000, "optional"),  # 합계 밖
        "removal": (D("184.1"), "㎡", 1_727, 317_941, "after_visit"),
        "waste": (None, "식", None, None, "after_visit"),
    }
    assert "primer" not in rows(q) and "meal" not in rows(q)
    assert (q.subtotal, q.vat, q.total) == (2_179_414, 217_941, 2_397_355)
    assert (q.man_days, q.days, q.version) == (D("5.5"), D("2.0"), "2026.11-market")
    assert v.qty == dobae.QtyV3(D("24.0"), D("69.5"), D("5.5"))
    names = {ln.key: ln.name for ln in q.lines}
    assert names["material"] == "부자재 (풀 · 부직포 · 네바리 · 실리콘 등)"
    assert names["wall"] == "벽 도배 시공 (풀 포함)" and names["truck"].startswith("운송 · 경비")
    assert q.assumptions[0] == (
        "도배만 하는 공사 기준으로 셌어요. 값은 시장 실견적 가운데(8출처 619건, 2026-11)이에요. "
        "퍼티작업 · 운송 · 경비는 '선택' 줄이라 합계에 넣지 않았어요."
    )


def test_paper_only_hapji_labor_is_055():
    """합지 시공비 = 공공 ㎡ 단가 × 0.55를 원 단위로(3,296 · 4,692), 소요량 1.2, 부자재 3,300원/평"""
    q = std(home("economy"), DOBAE_MARKET_2026_11).quote
    got = rows(q)
    assert got["wall"] == (D("119.7"), "㎡", 3_296, 394_531, "included")
    assert got["ceiling"] == (D("64.4"), "㎡", 4_692, 302_165, "included")
    # 184.1㎡ × 1.2 = 220.9㎡ → 66.8 벽지 평 × 4,577
    assert got["paper"] == (D("66.8"), "벽지 평", 4_577, 305_744, "included")
    assert got["material"] == (D("24.0"), "공급 평", 3_300, 79_200, "included")
    assert q.subtotal == 1_081_640
    wall = next(ln for ln in q.lines if ln.key == "wall")
    assert wall.basis == "market" and "× 0.55" in wall.source
    assert "합지벽지는 실크보다 빨리 붙여 시공비를 0.55배로 셌어요(시장 품 비)." in q.assumptions
    assert q.man_days == D("5.5")  # 품 · 기간은 그대로(공정표는 안 바뀜)


def test_optional_lines_stay_out_of_the_total():
    for g in ("basic", "economy"):
        q = std(home(g, occupied=True), DOBAE_MARKET_2026_11).quote
        counted = sum(ln.amount for ln in q.lines if ln.state in COUNTED and ln.amount)
        optional = {ln.key for ln in q.lines if ln.state == "optional"}
        assert optional == {"putty", "truck"} and q.subtotal == counted
        assert all(ln.amount for ln in q.lines if ln.state == "optional")  # 금액은 보여 줘요


# ---- 리모델링 기준 (서울 업체 실견적 보정, P3) ----


def test_remodel_silk_24py():
    q = std(home(), DOBAE_REMODEL_2026_11, ("문틀 교체",)).quote
    assert rows(q) == {
        "wall": (D("119.7"), "㎡", 7_200, 861_840, "included"),  # 0.024인/㎡ × 30만
        "ceiling": (D("64.4"), "㎡", 10_530, 678_132, "included"),  # 0.0351인/㎡ × 30만
        # 184.1㎡ × 1.58 = 290.9㎡ → 88.0 벽지 평
        "paper": (D("88.0"), "벽지 평", 10_749, 945_912, "included"),
        "material": (D("24.0"), "공급 평", 16_000, 384_000, "included"),
        "putty": (D("24.0"), "공급 평", 20_000, 480_000, "included"),
        "meal": (D("5.5"), "품", 15_000, 82_500, "included"),  # 품 5.5 × 15,000
        "truck": (D("1.0"), "대", 30_000, 30_000, "included"),
        "removal": (D("184.1"), "㎡", 1_727, 317_941, "after_visit"),
        "waste": (None, "식", None, None, "after_visit"),
    }
    assert (q.subtotal, q.vat, q.total) == (3_462_384, 346_238, 3_808_622)
    assert q.version == "2026.11-remodel" and q.man_days == D("5.5")
    names = {ln.key: ln.name for ln in q.lines}
    assert names["wall"] == "벽 도배 시공 (인건비)"  # 풀은 부자재 줄에 있어요
    assert q.assumptions[0] == (
        "리모델링 기준으로 셌어요(근거: 문틀 교체). 값은 서울 업체 실견적 보정(2026-11)이에요."
    )


def test_remodel_hapji_and_occupied():
    q = std(home("economy", occupied=True), DOBAE_REMODEL_2026_11).quote
    got = rows(q)
    assert got["wall"][2:4] == (3_960, 474_012)  # 7,200 × 0.55
    assert got["ceiling"][2:4] == (5_792, 373_005)  # 10,530 × 0.55 = 5,791.5 → 5,792
    # 짐 있는 집: 시공 금액 × (1/0.85 − 1) (리모델링 판은 시공 줄이 모두 노무비)
    assert got["occupied"][3] == won(D(474_012 + 373_005) * (1 / D("0.85") - 1)) == 149_474
    assert got["meal"][0] == q.man_days == D("6.5")  # 짐 있는 집은 품이 늘고 식대도 따라가요


def test_rounding_happens_once_per_line():
    for p in DOBAE_PROFILES.values():
        for g in ("basic", "economy"):
            q = std(home(g, occupied=True), p).quote
            for ln in q.lines:
                if ln.amount is not None and ln.qty is not None:
                    assert ln.amount == won(ln.qty * ln.unit_price), (p.version, ln.key)
            counted = sum(ln.amount for ln in q.lines if ln.state in COUNTED and ln.amount)
            assert q.subtotal == counted and q.vat == won(D(q.subtotal) * D("0.1"))


def test_partial_scope_uses_share_for_floor_lines():
    h = home(scope="partial", spaces=("living", "kitchen"), faces=("wall",))
    v = std(h, DOBAE_REMODEL_2026_11)
    floor = {ln.key: ln.qty for ln in v.quote.lines if ln.unit == "공급 평"}
    assert floor == {"material": v.qty.floor_py, "putty": v.qty.floor_py}
    assert v.qty.floor_py == dobae.m2(v.pyeong * v.share) < v.pyeong


# ---- 판 고정 ----


def test_versions_are_fixed_and_old_version_is_unchanged():
    """새 표준견적서는 기준 판으로, 이미 만든 견적의 판(2026H2-rooms)은 옛 줄 · 금액 그대로 다시 셀 수 있어요."""
    old = std(home(), DOBAE_V3_2026_11).quote
    assert old.version == "2026H2-rooms" and old.subtotal == 2_032_029
    assert {ln.key for ln in old.lines} == {
        "wall",
        "ceiling",
        "paper",
        "primer",
        "removal",
        "waste",
    }
    assert DOBAE_V3_2026_11.profile is None
    assert {p.version for p in DOBAE_PROFILES.values()} == {"2026.11-market", "2026.11-remodel"}
    assert dobae_prices_of("2026H2-rooms") is DOBAE_V3_2026_11
    assert dobae_prices_of("2026.11-remodel") is DOBAE_REMODEL_2026_11
    assert dobae_prices_of(None) is dobae_prices_of("없는 판") is DOBAE_MARKET_2026_11
    for p in DOBAE_PROFILES.values():
        assert len(p.version) <= 20  # standard_quotes.price_ver varchar(20)
        q = std(home(occupied=True), p, ("문틀 교체",)).quote
        assert all(len(ln.source) <= 120 and len(ln.name) <= 60 for ln in q.lines)
        assert all(len(a) <= 200 for a in q.assumptions)  # standard_quotes.notes


def test_profile_line_keys_match_vendor_rows():
    """새 표준 행 키는 가견적 v3 줄(1201 퍼티 · 1205 부자재 · 1207 식대 · 1208 운송비)과 같아요."""
    keys = {k for lines in dobae.PROFILE_LINES.values() for k in lines} - {"wall", "ceiling"}
    assert keys <= {k for v in estimate.V3_STD_KEYS.values() for k in v}
    assert set(estimate.V3_STD_KEYS) == set(estimate.V3_BY_KEY)


# ---- 가견적 비교 %: 그 집 기준의 표준견적서 합계 줄로 가른다 ----


def test_estimate_inside_lines_follow_the_profile():
    prices = {
        "putty": estimate.PriceV3("price", 15_000),
        "paper_silk": estimate.PriceV3("price", 11_000),
        "material": estimate.PriceV3("price", 7_000),
        "labor": estimate.PriceV3("price", 280_000),
        "meal": estimate.PriceV3("price", 10_000),
        "truck": estimate.PriceV3("price", 50_000),
    }
    outside = {}
    for p in (DOBAE_MARKET_2026_11, DOBAE_REMODEL_2026_11, DOBAE_V3_2026_11):
        v = std(home(), p)
        keys = {ln.key for ln in v.quote.lines if ln.state in COUNTED}
        e = estimate.estimate_v3(
            prices, v.qty, grade="basic", standard_total=v.quote.total, standard_keys=keys
        )
        outside[p.version] = {x.row.key for x in e.lines if not x.in_standard}
        inside = sum(x.amount for x in e.lines if x.in_standard)
        assert e.compare_total == won(D(inside) * D("1.1"))
    assert outside == {
        "2026.11-market": {"putty", "meal", "truck"},  # 퍼티 · 운송 · 경비는 '선택', 식대 줄 없음
        "2026.11-remodel": set(),  # 리모델링 기준은 모두 합계에 있어요
        "2026H2-rooms": {"putty", "meal", "truck"},  # 옛 판(초배지 ↔ 부자재)도 지금과 같아요
    }
    # 키를 안 주면 옛 고정값
    e = estimate.estimate_v3(prices, std(home(), DOBAE_V3_2026_11).qty, grade="basic")
    assert {x.row.key for x in e.lines if not x.in_standard} == {"putty", "meal", "truck"}
