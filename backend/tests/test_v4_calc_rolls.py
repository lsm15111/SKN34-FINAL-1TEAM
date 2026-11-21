"""갈래 C 계산 · 자재(DB 없음): 벽지 롤 수 ref(calc.rolls) · 합지 롤 광폭 기본(calc.plan_qty) · 옛 이름 베스띠 ·
벽지 직접 구매(도배지 줄 '안 함' · 고객 구매, 가견적은 벽지 값 그대로) · '선택' 줄에 포함한 줄(missing) ·
빠듯한 직접 할 일 말(할 수 있는 첫날). 기대값은 손으로 검산했어요."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.assistant.tools import diy as diy_tools
from app.calc import diy as calc_diy
from app.calc import dobae, rolls
from app.calc.common import COUNTED, with_vat
from app.calc.estimate import PriceV3, StdLine, VendorPrice, estimate, estimate_v3
from app.calc.plan_qty import PlanOptions, from_plan
from app.quote.schemas import QuoteDraftIn
from app.quote.service import standard_v3
from app.refprice.book import DOBAE_PROFILES, SILK_2026
from app.refprice.floor_plans import plans
from app.v2 import preview_service
from app.v2.ask import _profile_text
from app.v2.schemas import V2AskProfile, V2Calc7In, V2PlanSelIn, V2QuoteIn
from tests.test_v4_qa_r2_calc import MARU_V3

D = Decimal
BACKEND = Path(__file__).resolve().parents[1]


# ---- 1. 롤 수 ref: 벽지 양 → 롤 수(올림), 여분은 따로 ----


def test_roll_sizes_follow_maker_specs_and_grade_picks_the_roll():
    r = rolls.ROLLS
    assert [(k, x.name, x.size, x.area_m2) for k, x in r.items()] == [
        ("silk", "실크", "106cm × 15.6m", D("16.536")),
        ("hapji_wide", "광폭 합지", "93cm × 17.75m", D("16.5075")),
        ("hapji_narrow", "소폭 합지", "53cm × 12.5m", D("6.625")),
    ]
    assert rolls.roll_key("basic") == "silk"
    assert rolls.roll_key("economy") == "hapji_wide"  # 합지는 광폭이 기본
    assert rolls.roll_key("economy", "narrow") == "hapji_narrow"  # 소폭은 고를 때만
    with pytest.raises(ValueError):
        rolls.roll_key("premium")


@pytest.mark.parametrize(
    ("key", "amount", "count"),
    [
        ("silk", {"paper_m2": D("16.536")}, 1),  # 딱 한 롤
        ("silk", {"paper_m2": D("16.537")}, 2),  # 조금이라도 넘으면 올림
        ("silk", {"paper_m2": D(0)}, 0),
        ("silk", {"paper_py": D("5.0")}, 1),  # 5평 = 16.529㎡ < 16.536
        ("silk", {"paper_py": D("5.1")}, 2),
        ("hapji_wide", {"paper_py": D("4.9")}, 1),  # 16.198㎡
        ("hapji_wide", {"paper_py": D("5.0")}, 2),  # 16.529㎡ > 16.5075
        ("hapji_narrow", {"paper_py": D("2.0")}, 1),  # 6.612㎡ < 6.625
        ("hapji_narrow", {"paper_py": D("2.1")}, 2),
        (
            "silk",
            {"paper_py": D("88.9")},
            18,
        ),  # 34평 실크 표준견적서 도배지 줄(293.9㎡ ÷ 16.536 = 17.8)
    ],
)
def test_roll_count_rounds_up_without_spare(key, amount, count):
    n = rolls.need(key, **amount)
    assert n.count == count
    assert (n.spare_min, n.spare_max, n.version) == (1, 2, "rolls-2026.11")  # 여분은 셈 밖


def test_roll_text_and_bad_inputs():
    n = rolls.need("silk", paper_py=D("88.9"))
    assert n.text == "실크(106cm × 15.6m) 약 18롤 · 여분 1~2롤은 따로"
    with pytest.raises(ValueError):
        rolls.need("silk")
    with pytest.raises(ValueError):
        rolls.need("silk", paper_py=D(1), paper_m2=D(1))
    with pytest.raises(ValueError):
        rolls.need("silk", paper_m2=D("-0.1"))


# ---- 2. 도면 수량 합지 롤: 광폭 기본, 소폭은 고를 때만(옛 판은 2.5배쯤 많았어요) ----


def test_plan_hapji_rolls_are_wide_by_default_not_two_and_a_half_times_silk():
    for pid, info in plans().items():
        wide = from_plan(info.plan)
        narrow = from_plan(info.plan, PlanOptions(hapji="narrow"))
        silk = wide.rolls["silk"].rolls
        # 옛 판(소폭만)에서 보이던 값: 실크의 2.1배 넘게
        assert narrow.rolls["hapji"].rolls >= silk * D("2.1"), pid
        # 광폭은 한 롤 넓이가 실크와 거의 같아 롤 수도 비슷해요
        assert wide.rolls["hapji"].rolls <= silk, pid
        assert (wide.rolls["hapji"].ko, narrow.rolls["hapji"].ko) == ("광폭 합지", "소폭 합지")


def test_v2_preview_and_answer_context_use_wide_hapji_rolls():
    q = preview_service.plan_qty("fp06", True, None)
    got = {r.kind: r for r in q.rolls}
    assert (got["hapji"].ko, got["hapji"].size, got["hapji"].rolls) == (
        "광폭 합지",
        "0.93m × 17.75m",
        16,
    )
    assert got["silk"].rolls == 18 and q.rules_version == "2026.11.2"
    text = _profile_text(V2AskProfile(), V2QuoteIn(plan=V2PlanSelIn(id="fp06")))
    assert "실크 18롤 · 합지 16롤" in text  # 옛 판은 합지 41롤
    # v2 셀프 계산기도 빈 칸이면 광폭 합지 롤(소폭은 고를 때만)
    c, wide = V2Calc7In(kind="wallpaper"), rolls.ROLLS["hapji_wide"]
    assert (D(str(c.rollW)), D(str(c.rollLen))) == (wide.width_m, wide.length_m)


# ---- 3. 옛 이름 '베스띠' → '실크벽지 베스트'(보이는 이름만, 키 · id 그대로) ----


def test_old_name_bestti_is_shown_as_silk_best():
    best = SILK_2026["wall-silk-best"]  # 화면 자재 id 그대로
    assert (best.key, best.name) == ("best", "실크벽지 (LX 실크벽지 베스트 or 개나리 로하스)")
    rows = json.loads((BACKEND / "app/refprice/v2_materials.json").read_text(encoding="utf-8"))
    names = {x["id"]: x["name"] for x in rows}
    assert names["wall-silk-best"] == "실크벽지 (LX 실크벽지 베스트 or 개나리 로하스)"
    desc = QuoteDraftIn.model_fields["paper_spec"].description or ""
    assert "실크벽지 베스트" in desc and "베스띠" not in desc
    for f in ("app/demo.py", "app/quote/models.py", "app/refprice/book.py", "app/v2/schemas.py"):
        assert "베스띠" not in (BACKEND / f).read_text(encoding="utf-8"), f


# ---- 4. 벽지 직접 구매: 도배지 줄 '안 함'(고객 구매), 합계에서 빠짐(계산 엔진) ----


@pytest.mark.parametrize("profile", ["paper_only", "remodel"])
@pytest.mark.parametrize("grade", ["basic", "economy"])
def test_own_paper_takes_the_paper_line_out_of_the_total(profile, grade):
    h = dobae.HomeV3(D("112.4"), "supply", grade, False)
    pick = dobae.ProfilePick(profile, ())  # type: ignore[arg-type]
    on, off = standard_v3(h, pick=pick, own_paper=True), standard_v3(h, pick=pick)
    paper_on = next(ln for ln in on.quote.lines if ln.key == "paper")
    paper_off = next(ln for ln in off.quote.lines if ln.key == "paper")
    assert (paper_off.state, paper_on.state) == ("included", "excluded")
    assert paper_on.source.startswith("고객 구매 · ")
    # 수량 · 단가 · 금액은 참고로 그대로, 합계(공급가)에서만 빠져요
    assert (paper_on.qty, paper_on.unit_price, paper_on.amount) == (
        paper_off.qty,
        paper_off.unit_price,
        paper_off.amount,
    )
    assert on.quote.subtotal == off.quote.subtotal - paper_off.amount
    assert on.quote.subtotal == sum(
        ln.amount for ln in on.quote.lines if ln.state in COUNTED and ln.amount is not None
    )
    money = with_vat(on.quote.subtotal, DOBAE_PROFILES[profile].vat_rate)
    assert (on.quote.vat, on.quote.total) == (money.vat, money.total)
    assert on.quote.assumptions[-1] == dobae.OWN_PAPER_ASSUMED
    # 가견적 수량 · '선택' 줄 · 품은 그대로(가견적은 벽지 값이 든 값)
    assert (on.qty, on.optional_keys, on.quote.man_days) == (
        off.qty,
        off.optional_keys,
        off.quote.man_days,
    )
    # 고객 구매 줄까지 넣은 값 = 벽지를 사지 않을 때 표준견적서 합계
    full = dobae.with_own_paper(on.quote.lines, DOBAE_PROFILES[profile].vat_rate)
    assert (full.supply, full.vat, full.total) == (
        off.quote.subtotal,
        off.quote.vat,
        off.quote.total,
    )


def test_own_paper_line_is_only_the_customer_bought_paper():
    assert dobae.own_paper_line("paper", "excluded")
    assert not dobae.own_paper_line("paper", "included")
    assert not dobae.own_paper_line("ceiling", "excluded")  # 부분 공사 '안 함' 면은 아니에요
    # 벽지를 사지 않으면 도배지 줄은 늘 '포함'(부분 공사 · 천장 안 함이어도)
    h = dobae.HomeV3(D("69.4"), "supply", "basic", False, "partial", ("living",), ("wall",))
    (paper,) = [ln for ln in standard_v3(h).quote.lines if ln.key == "paper"]
    assert paper.state == "included"


def test_old_estimate_keeps_the_customer_bought_paper():
    """옛 v2 단가 가견적(저장한 표준견적서 줄 수량)도 고객 구매 도배지 줄을 넣어요('시공만' 값은 뒤로)."""
    prices = {
        "wall": VendorPrice(6650),
        "ceiling": VendorPrice(6800),
        "paper_basic": VendorPrice(3400),
        "primer": VendorPrice(included_in="paper_basic"),
    }

    def lines(state: str) -> list[StdLine]:
        return [
            StdLine("wall", D("120.0"), "included"),
            StdLine("ceiling", D("40.0"), "included"),
            StdLine("paper", D("192.0"), state),
            StdLine("primer", D("176.0"), "included"),
        ]

    off = estimate(lines("included"), prices, trade="dobae", grade="basic")
    on = estimate(lines("excluded"), prices, trade="dobae", grade="basic")
    assert on == off and on.missing == () and on.total == with_vat(on.supply).total
    assert [x.key for x in on.lines] == ["wall", "ceiling", "paper", "primer"]


# ---- 6. '선택' 줄에 포함한 줄은 0원으로 빠지지 않게 missing(가견적 없음) ----


def test_line_included_in_an_optional_row_is_missing():
    qty = standard_v3(dobae.HomeV3(D("69.4"), "supply", "basic", False)).qty
    meal_in_truck = {**MARU_V3, "meal": PriceV3("included", included_in="truck")}
    std = {"wall", "ceiling", "paper", "material"}  # 도배만 하는 공사: 퍼티 · 운송비는 '선택'
    e = estimate_v3(
        meal_in_truck,
        qty,
        grade="basic",
        standard_keys=std,
        optional_keys={"putty", "truck"},
    )
    assert e.missing == ("meal",)  # 운송비는 합계 밖이라 식대 금액을 알 수 없어요
    truck = next(x for x in e.lines if x.row.key == "truck")
    assert truck.optional and truck.amount == 50_000
    # 리모델링 기준(운송비가 합계 안)이면 그대로 돼요
    remodel = std | {"putty", "meal", "truck"}
    assert estimate_v3(meal_in_truck, qty, grade="basic", standard_keys=remodel).missing == ()
    # 합계에 드는 줄(인건비)에 포함은 그대로 돼요
    meal_in_labor = {**MARU_V3, "meal": PriceV3("included", included_in="labor")}
    ok = estimate_v3(
        meal_in_labor, qty, grade="basic", standard_keys=std, optional_keys={"putty", "truck"}
    )
    assert ok.missing == ()


# ---- 7. 빠듯한 직접 할 일 말은 공정표와 같은 날(할 수 있는 첫날) ----


def test_tight_task_says_the_first_possible_day_like_the_plan():
    work = {
        "mokgong": (date(2026, 12, 7), date(2026, 12, 8)),
        "dobae": (date(2026, 12, 9), date(2026, 12, 10)),
    }
    (paint,) = calc_diy.plan(["paint"], work, date(2026, 11, 22))
    assert (paint.why, paint.day, paint.end) == ("short", date(2026, 12, 9), date(2026, 12, 5))
    said = diy_tools.when_text(paint)
    assert said == "12월 9일(수)부터 할 수 있는데 날이 빠듯해요"  # 공정표 줄 날(마감 12월 5일 아님)
    assert "12월 5일" not in said


# ---- 벽지 직접 구매 직접 할 일: 도배 시작 전날까지 사서 받아 두기 ----


def test_paper_buy_task_is_due_the_day_before_dobae():
    dobae_days = {"dobae": (date(2026, 12, 7), date(2026, 12, 9))}  # 월 ~ 수
    (t,) = calc_diy.plan(["paper_buy"], dobae_days, date(2026, 12, 1))
    assert (t.name, t.kind, t.rule_ver) == ("벽지 사서 받아 두기", "before", "diy_v3")
    assert (t.start, t.end, t.day, t.fit) == (
        date(2026, 12, 1),
        date(2026, 12, 6),
        date(2026, 12, 6),
        True,
    )
    assert diy_tools.when_text(t) == "12월 1일(화) ~ 12월 6일(일) 사이에 해요"
    # 도배가 없으면 없어요, 공사 날짜가 없으면 순서만
    mok = {"mokgong": (date(2026, 12, 7), date(2026, 12, 8))}
    assert calc_diy.plan(["paper_buy"], mok, date(2026, 12, 1)) == []
    (undated,) = calc_diy.plan(["paper_buy"], {}, date(2026, 12, 1))
    assert (undated.start, undated.end, undated.day) == (None, None, None)


def test_free_mode_words_find_paper_buy_only_for_buying():
    assert diy_tools.keys_in("벽지 직접 구매 언제 · 어떻게 해요?") == ["paper_buy"]
    assert diy_tools.keys_in("벽지는 제가 살게요") == ["paper_buy"]
    assert diy_tools.keys_in("벽지 사이즈가 어떻게 돼요?") == []
    assert diy_tools.keys_in("실크 벽지 고르는 법 알려 줘") == []
