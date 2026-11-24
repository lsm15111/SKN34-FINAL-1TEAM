"""받은 견적서 견주기(calc.quote_compare, 순수 함수): 외부 견적서 줄 ↔ 이 집 도배 표준견적서 줄.

줄 맞추기 · 빠짐 · 많음 · 비슷 · 표준에 없음 · 할인 · 금액 없는 줄 · 부가세 기준 · 적힌 합계 · 합계만 있는 견적서 · 올퍼티 ·
희망 예산 · 폭 출처(시장 띠)를 본다. DB · LLM 없음."""

from decimal import Decimal

import pytest

from app.calc import quote_compare as qc
from app.calc.common import Line
from app.calc.quote_compare import OutsideLine
from app.refprice.market import MARKET_2026_11


def std_line(key: str, name: str, amount: int | None, state: str) -> Line:
    return Line(key, name, None, "식", None, amount, state, "시험")  # type: ignore[arg-type]


# 21평 도배만 하는 공사 기준 꼴(공급가): 합계에 드는 줄 = 시공 1,100,000 · 벽지 900,000 · 부자재 150,000
STANDARD = [
    std_line("wall", "벽 도배 시공 (풀 포함)", 700_000, "included"),
    std_line("ceiling", "천장 도배 시공 (풀 포함)", 400_000, "included"),
    std_line("paper", "실크 시장 평균 가격", 900_000, "included"),
    std_line("material", "부자재 (풀 · 부직포 · 네바리 · 실리콘 등)", 150_000, "included"),
    std_line("putty", "퍼티작업 (사전퍼티 · 밑작업)", 300_000, "optional"),
    std_line("truck", "운송 · 경비 (자재 운반 · 주차 등)", 50_000, "optional"),
    std_line("removal", "기존 벽지 철거", 200_000, "after_visit"),
    std_line("waste", "폐기물 처리", None, "after_visit"),
]


def out(name: str, amount: int | None, vat: str = "excluded", **kw) -> OutsideLine:
    return OutsideLine(name=name, amount=amount, vat=vat, **kw)  # type: ignore[arg-type]


def row(c: qc.Compare, key: str) -> qc.Row:
    return next(r for r in c.rows if r.key == key)


@pytest.mark.parametrize(
    ("name", "item"),
    [
        ("실크벽지(LG 베스띠)", "paper"),
        ("벽지 자재비", "paper"),
        ("LX 디아망", "paper"),
        ("도배 인건비", "labor"),
        ("인건비 (2인 x 2일, 풀 포함)", "labor"),
        ("시공비", "labor"),
        ("기술자 6품", "labor"),
        ("부자재(풀, 초배지)", "material"),
        ("초배지", "material"),
        ("도배풀", "material"),
        ("올퍼티", "putty_full"),
        ("전체 퍼티 작업", "putty_full"),
        ("퍼티 작업", "putty_part"),
        ("부분 빠데", "putty_part"),
        ("기존 벽지 제거", "removal"),
        ("폐기물 처리", "waste"),
        ("보양 작업", "cover"),
        ("장판 보양", "cover"),
        ("가구 이동", "cover"),
        ("식대", "meal_truck"),
        ("운반비 · 주차", "meal_truck"),
        ("걸레받이 교체", "other"),
        ("곰팡이 제거", "other"),
        ("몰딩 (자재 포함)", "other"),
        ("실크 도배 일체", "bundle"),
        ("도배 공사 (자재+인건비)", "bundle"),
        ("실크 도배", "bundle"),
        ("도배 32평", "bundle"),
        ("할인", "discount"),
        ("단수 정리", "discount"),
        ("합계", "skip"),
        ("부가세 10%", "skip"),
        ("소계", "skip"),
    ],
)
def test_line_names_map_to_standard_items(name, item):
    assert qc.item_of(name) == item


def test_negative_amount_is_a_discount_and_paper_named_labor_becomes_bundle():
    assert qc.item_of("특가", -50_000) == "discount"
    # 벽지 줄이 따로 없으면 벽지 이름이 든 시공 줄은 벽지 · 인건비 · 부자재 묶음으로 봐요
    alone = qc.classify([out("실크벽지 시공", 2_500_000)])
    assert alone == ["bundle"]
    # 벽지 줄이 따로 있으면 시공 줄은 인건비 그대로
    pair = qc.classify([out("실크벽지", 1_000_000), out("실크벽지 시공", 1_500_000)])
    assert pair == ["paper", "labor"]
    # '자재 별도'라고 적힌 시공 줄은 묶음이 아니에요
    assert qc.classify([out("실크 도배 시공 (자재 별도)", 1_500_000)]) == ["labor"]


def test_missing_more_same_and_diff_on_the_same_vat_basis():
    lines = [
        out("실크벽지(LG 베스띠)", 1_000_000),  # 부가세 별도 → 1,100,000
        out("도배 인건비", 1_600_000),  # → 1,760,000
        out("폐기물 처리", 100_000),  # → 110,000 (표준은 실측 후 · 금액 없음)
    ]
    c = qc.compare(lines, STANDARD, grade="basic")
    paper = row(c, "paper")
    assert (paper.outside, paper.standard, paper.diff, paper.state) == (
        1_100_000,
        990_000,
        110_000,
        "same",
    )
    labor = row(c, "labor")
    assert (labor.outside, labor.standard, labor.diff, labor.state) == (
        1_760_000,
        1_210_000,
        550_000,
        "more",
    )
    material = row(c, "material")
    assert (material.state, material.outside, material.standard, material.diff) == (
        "missing",
        None,
        165_000,
        None,
    )
    waste = row(c, "waste")
    assert (waste.state, waste.outside, waste.standard) == ("extra", 110_000, None)
    assert waste.note and "실측 후" in waste.note
    # 합계: 같은 범위(표준 합계에 드는 줄)로 견줘요. 표준에 금액이 없는 폐기물(표준에 없음)은 줄로만 보이고 빼요
    assert (c.outside_cmp, c.standard_cmp, c.diff, c.state) == (
        2_860_000,
        2_365_000,
        495_000,
        "same",
    )
    assert c.outside_total == 2_970_000 and c.extra_total == 110_000
    assert c.added == () and not c.vat_unknown
    assert any("초배지 · 부자재" in a for a in c.asks)
    assert any(a.startswith("인건비가 표준보다 550,000원 많아요") for a in c.asks)
    # 철거는 표준도 실측 후라 빠짐이 아니라 물을 것이에요
    assert not any(r.key == "removal" for r in c.rows)
    assert any("철거" in a for a in c.asks)


def test_vat_included_and_unknown_lines_keep_the_written_amount():
    lines = [
        out("실크벽지", 990_000, vat="included"),
        out("도배 인건비", 1_210_000, vat="unknown"),
        out("부자재", 165_000, vat="included"),
    ]
    c = qc.compare(lines, STANDARD, grade="basic")
    assert [(r.key, r.outside, r.diff, r.state) for r in c.rows] == [
        ("paper", 990_000, 0, "same"),
        ("labor", 1_210_000, 0, "same"),
        ("material", 165_000, 0, "same"),
    ]
    assert c.vat_unknown and c.diff == 0
    assert any("부가세" in a for a in c.asks)


def test_optional_putty_is_added_to_the_standard_when_the_quote_has_it():
    lines = [
        out("실크벽지", 900_000),
        out("인건비", 1_100_000),
        out("부자재", 150_000),
        out("올퍼티", 600_000),
    ]
    c = qc.compare(lines, STANDARD, grade="basic")
    putty = row(c, "putty")
    assert putty.name == "퍼티(올퍼티)"
    assert (putty.outside, putty.standard, putty.diff, putty.state) == (
        660_000,
        330_000,
        330_000,
        "more",
    )
    assert putty.note and "선택" in putty.note
    assert c.added == ("퍼티",)
    # 표준 합계 밖 퍼티 300,000(공급가)을 더한 같은 범위: (2,150,000 + 300,000) × 1.1
    assert c.standard_cmp == 2_695_000 and c.outside_cmp == 3_025_000 and c.state == "same"


def test_small_line_gap_is_same_and_less_is_flagged():
    lines = [
        out("실크벽지", 600_000),  # 660,000 vs 990,000 → 적음
        out("인건비", 1_100_000),
        out("부자재", 150_000),
        out("운반비", 20_000),  # 22,000 vs 55,000: 띠 밖이지만 차이가 5만 원 아래라 비슷
    ]
    c = qc.compare(lines, STANDARD, grade="basic")
    assert row(c, "paper").state == "less"
    truck = row(c, "meal_truck")
    assert (truck.outside, truck.standard, truck.state) == (22_000, 55_000, "same")
    assert "식대 · 운송" in c.added


def test_extra_lines_are_left_out_of_the_compare_total_and_discount_stays():
    lines = [
        out("실크벽지", 900_000),
        out("인건비", 1_100_000),
        out("부자재", 150_000),
        out("걸레받이 교체", 200_000),
        out("할인", -100_000),
    ]
    c = qc.compare(lines, STANDARD, grade="basic")
    extra = [r for r in c.rows if r.state == "extra"]
    assert [(r.name, r.outside) for r in extra] == [("걸레받이 교체", 220_000)]
    disc = [r for r in c.rows if r.state == "discount"]
    assert [(r.name, r.outside) for r in disc] == [("할인", -110_000)]
    assert c.extra_total == 220_000
    assert c.outside_total == 2_365_000 + 220_000 - 110_000
    assert c.outside_cmp == 2_365_000 - 110_000
    assert c.diff == -110_000


def test_lines_the_standard_has_no_amount_for_stay_out_of_the_same_scope_total():
    # QA r10 c3 · u1: 표준에 금액이 없는 폐기물 · 보양 줄이 받은 쪽 합에만 들어가 차이 · 판정이 어긋났어요
    lines = [
        out("실크벽지", 1_000_000),
        out("도배 인건비", 1_400_000),
        out("부자재", 150_000),
        out("폐기물 처리", 200_000),  # 표준은 실측 후 · 금액 없음
        out("보양 작업", 50_000),  # 표준에 보양 줄이 없음
    ]
    c = qc.compare(
        lines,
        STANDARD,
        grade="basic",
        stated_total=2_800_000,
        stated_vat="excluded",
        budget=(None, 3_000_000),
    )
    # 줄에는 그대로 보여요(표준에 없음)
    assert [(r.key, r.state, r.outside) for r in c.rows if r.state == "extra"] == [
        ("waste", "extra", 220_000),
        ("cover", "extra", 55_000),
    ]
    # 같은 범위는 벽지 · 인건비 · 부자재만(2,550,000 × 1.1). 두 줄을 넣으면 띠 위(많음)로 뒤집혀요
    assert (c.outside_cmp, c.standard_cmp, c.diff, c.state) == (
        2_805_000,
        2_365_000,
        440_000,
        "same",
    )
    assert c.extra_total == 275_000 and c.outside_total == 3_080_000
    # 적힌 합계(빠진 줄 묻기) · 희망 예산은 받은 줄 모두 합과 견줘요
    assert c.stated_gap is None
    assert c.budget is not None and (c.budget.state, c.budget.gap) == ("over", 80_000)


def test_lines_without_amount_count_as_present_and_separate_ones_are_asked():
    lines = [
        out("실크벽지", 900_000),
        out("인건비", 1_100_000),
        OutsideLine(name="부자재", amount=None, note="included"),
        OutsideLine(name="폐기물", amount=None, note="separate"),
    ]
    c = qc.compare(lines, STANDARD, grade="basic")
    material = row(c, "material")
    assert material.state == "noprice" and material.outside is None
    assert material.note and "포함" in material.note
    waste = row(c, "waste")
    assert waste.state == "noprice" and waste.note and "따로" in waste.note
    assert not any(r.state == "missing" for r in c.rows)
    assert any("폐기물" in a and "얼마" in a for a in c.asks)


def test_unit_price_times_qty_is_counted_by_the_engine():
    lines = [
        OutsideLine(
            name="실크벽지",
            amount=None,
            qty=Decimal(45),
            unit="롤",
            unit_price=20_000,
            vat="excluded",
        ),
        out("인건비", 1_100_000),
        out("부자재", 150_000),
    ]
    c = qc.compare(lines, STANDARD, grade="basic")
    assert row(c, "paper").outside == 990_000  # 45 × 20,000 = 900,000 → 부가세 포함


def test_bundle_line_compares_against_paper_labor_and_material_together():
    lines = [out("실크 도배 일체", 2_000_000), out("폐기물", 100_000)]
    c = qc.compare(lines, STANDARD, grade="basic")
    keys = [r.key for r in c.rows]
    assert "paper" not in keys and "labor" not in keys and "material" not in keys
    b = row(c, "bundle")
    assert b.name == qc.BUNDLE_NAME
    assert (b.outside, b.standard, b.diff, b.state) == (2_200_000, 2_365_000, -165_000, "same")
    assert not any(r.state == "missing" for r in c.rows)


def test_total_only_quote_compares_the_total_and_asks_for_lines():
    c = qc.compare([], STANDARD, grade="basic", stated_total=3_000_000, stated_vat="included")
    assert [(r.key, r.outside, r.standard, r.state) for r in c.rows] == [
        ("bundle", 3_000_000, 2_365_000, "same")
    ]
    assert c.total_only and any("줄마다" in a for a in c.asks)
    with pytest.raises(ValueError):
        qc.compare([], STANDARD, grade="basic")


def test_stated_total_that_does_not_match_the_lines_is_asked():
    lines = [out("실크벽지", 900_000), out("인건비", 1_100_000), out("부자재", 150_000)]
    same = qc.compare(lines, STANDARD, stated_total=2_150_000, stated_vat="excluded")
    assert same.stated_gap is None
    off = qc.compare(lines, STANDARD, stated_total=2_400_000, stated_vat="excluded")
    assert off.stated_gap == 275_000  # (2,400,000 − 2,150,000) × 1.1
    assert any("275,000원" in a for a in off.asks)


def test_quote_without_dobae_lines_is_refused():
    with pytest.raises(ValueError):
        qc.compare([out("걸레받이", 200_000), out("몰딩", 300_000)], STANDARD)


def test_full_putty_by_grade_demolition_and_engine_putty_state():
    assert qc.full_putty("economy", "full", "included")[0] == "no"
    need, why = qc.full_putty("basic", "full", "optional")
    assert need == "need" and "전체 철거" in why
    need, why = qc.full_putty("basic", "partial", "included")
    assert need == "check" and "리모델링" in why
    need, why = qc.full_putty("basic", None, "optional")
    assert need == "check" and "부분퍼티" in why
    assert qc.full_putty(None, None, None)[0] == "check"  # 도배 유형을 모르면 실크로 봐요


def test_putty_check_compares_the_need_with_what_the_quote_has():
    base = [out("실크벽지", 900_000), out("인건비", 1_100_000), out("부자재", 150_000)]
    need = qc.compare(
        [*base, out("부분 퍼티", 100_000)], STANDARD, grade="basic", demolition="full"
    )
    assert (need.putty.need, need.putty.found) == ("need", "part")
    assert need.putty.ask and "올퍼티" in need.putty.ask and need.putty.ask in need.asks
    hapji = qc.compare([*base, out("올퍼티", 500_000)], STANDARD, grade="economy")
    assert (hapji.putty.need, hapji.putty.found) == ("no", "full")
    assert hapji.putty.ask and "합지" in hapji.putty.ask
    plain = qc.compare(base, STANDARD, grade="basic")
    assert (plain.putty.need, plain.putty.found, plain.putty.ask) == ("check", "none", None)


def test_budget_is_compared_with_the_quote_total():
    lines = [out("실크벽지", 900_000), out("인건비", 1_100_000), out("부자재", 150_000)]
    over = qc.compare(lines, STANDARD, budget=(1_500_000, 2_000_000))
    assert over.budget is not None
    assert (over.budget.state, over.budget.gap) == ("over", 365_000)
    within = qc.compare(lines, STANDARD, budget=(None, 3_000_000))
    assert within.budget is not None and (within.budget.state, within.budget.gap) == (
        "within",
        None,
    )
    under = qc.compare(lines, STANDARD, budget=(3_000_000, None))
    assert under.budget is not None and (under.budget.state, under.budget.gap) == (
        "under",
        635_000,
    )
    assert qc.compare(lines, STANDARD).budget is None
    with pytest.raises(ValueError):
        qc.budget_check(1, 5, 3)


def test_band_is_the_market_middle_half_and_no_percent_in_texts():
    book = MARKET_2026_11.dobae.band
    assert qc.BAND["basic"] == (book["silk"].lo, book["silk"].hi)
    assert qc.BAND["economy"] == (book["hapji"].lo, book["hapji"].hi)
    lines = [
        out("실크벽지", 2_000_000),
        out("인건비", 500_000),
        out("올퍼티", 900_000),
        out("걸레받이", 100_000),
    ]
    c = qc.compare(lines, STANDARD, grade="economy", stated_total=9_000_000)
    texts = [*c.asks, c.putty.why, *(r.note or "" for r in c.rows)]
    assert all("%" not in t for t in texts)
