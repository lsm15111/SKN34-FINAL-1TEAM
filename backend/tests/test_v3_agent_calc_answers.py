"""기간 · 비용 · 업체 추천 답(calc_lines · vendor_pick · tools.general_facts). 숫자는 모두 계산 엔진 값. DB 없음."""

import time
from datetime import date

from app.agent.v3 import calc_lines
from app.agent.v3.gate import gate
from app.agent.v3.policy import policy_of
from app.agent.v3.schemas import (
    PlanBlockFact,
    PlanFacts,
    ProjectFacts,
    StandardFacts,
    VendorPickFact,
)
from app.calc import vendor_pick
from app.chat.tools import asked_area, general_facts, house_size, with_said
from app.v2 import guard

PLAN = PlanFacts(start=date(2027, 1, 4), end=date(2027, 1, 5), work_days=2)
STD = StandardFacts(total=1974069, supply=1794608, vat=179461)


def _ok(lines: calc_lines.Lines) -> None:
    """문장 숫자가 모두 계산 값 글(calc_text)에 있어서 출력 검사를 지나는지."""
    allowed = guard.numbers(lines.calc_text)
    for t in [*lines.lines, *(c for r in lines.table for c in r)]:  # 표 칸도 같은 검사
        assert guard._why(t, allowed, allowed) is None, t


def test_area_from_question():
    assert asked_area("34평 도배하면 며칠 걸려요?") == (112.4, "supply", "34평")
    assert asked_area("84㎡ 아파트 도배 비용")[1:] == ("exclusive", "전용 84㎡")
    assert asked_area("공급 112㎡")[1] == "supply"
    assert asked_area("3평 원룸") is None and asked_area("도배 며칠?") is None
    t = time.perf_counter()
    asked_area("3" + " " * 50_000 + "평")
    assert time.perf_counter() - t < 0.5


def test_period_with_project_plan_gives_dates():
    out = calc_lines.period("dobae", ProjectFacts(plan=PLAN), general_facts("도배 며칠 걸려요?"))
    assert out.lines[0] == "이 집 예상 공정표로는 1.4(월) ~ 1.5(화), 일하는 날 2일이에요."
    assert out.boxes[0].ref == "plan.range"
    _ok(out)


def test_period_of_trade_not_in_project_says_so_and_counts_this_house():
    """도배만 한 공사에 '목공도 같이 하면요?': 공정표에 없는 공종이라고 먼저 말하고 이 집 크기로 센 일수를 줘요."""
    blocks = [PlanBlockFact(trade="dobae", ko="도배", start=date(2027, 1, 4), end=date(2027, 1, 5))]
    facts = ProjectFacts(plan=PLAN.model_copy(update={"blocks": blocks}), area_m2=112.4)
    g = general_facts("목공도 같이 하면요?")
    g.here = house_size(facts)
    out = calc_lines.period("mokgong", facts, g)
    assert out.lines[0] == "이 공사에는 목공이 들어 있지 않아서 공정표에 목공 날짜는 없어요."
    assert "몰딩 · 걸레받이 목공은 약" in out.lines[1]
    assert out.boxes[0].ref == "general.here.mokgong_days"
    assert not any("예상 공정표로는" in t for t in out.lines)  # 도배 공정표 줄을 되풀이하지 않아요
    _ok(out)
    assert calc_lines.period("dobae", facts, g).lines[1] == "도배는 1.4(월) ~ 1.5(화)에 해요."


def test_period_without_project_uses_examples_or_asked_size():
    ex = calc_lines.period("dobae", None, general_facts("도배 공사 며칠 걸려요?"))
    # 품은 시장 품 계수를 곱한 계산 엔진 값(판 2026.11b, ADR 0006)
    assert ex.lines[0] == "믿집 계산으로 빈집 도배(벽 + 천장)는 평수에 따라 약 2~2.5일이에요."
    assert [r[0] for r in ex.table] == ["24평", "34평", "44평"]  # 평수별 2열 표
    assert ex.table[1][1] == "빈집 약 2일 · 살면서 약 3일"
    assert ex.cards and ex.cards[0].choices[0].action == "start"
    _ok(ex)
    one = calc_lines.period("dobae", None, general_facts("34평 도배하면 며칠 걸려요?"))
    assert one.lines[0].startswith("믿집 계산으로 34평 도배는 빈집이면 약 ")
    _ok(one)


def test_price_project_and_asked_size_differ():
    f = ProjectFacts(area_m2=69.4, area_basis="supply", standard=STD, grade="basic")
    out = calc_lines.price("dobae", f, general_facts("33평 도배 비용 얼마예요?"), "33평 도배 비용")
    # 질문 평수가 이 집과 다르면 질문 평수 줄이 먼저, 이 집 값은 '참고로'로 뒤에(r2 점검 C05)
    assert out.lines[0].startswith("물어보신 33평이면")
    assert "참고로 이 집 표준견적서 합계는 부가세 포함 약 197만 원이에요." in out.lines
    assert sum("실측 뒤 정하는" in x for x in out.lines) == 1  # 빠진 줄 안내는 한 번
    _ok(out)
    # 공정이 둘인 집에서 도배를 물으면 도배 합계(계산 엔진 공정별 값)
    two = STD.model_copy(update={"trades": {"dobae": 1_500_000, "mokgong": 474_069}})
    f2 = ProjectFacts(area_m2=69.4, area_basis="supply", standard=two, grade="basic")
    out = calc_lines.price("dobae", f2, general_facts("도배 비용 얼마예요?"), "도배 비용")
    assert (
        out.lines[0]
        == "이 집 표준견적서의 도배 합계는 부가세 포함 약 150만 원이에요(전체 약 197만 원)."
    )
    _ok(out)


def test_refund_warranty_and_quote_check_are_not_price_or_period():
    assert "price" not in policy_of("도배 하자로 분쟁조정하면 저는 얼마를 돌려받을까요?")
    assert "period" not in policy_of("도배하고 하자가 생기면 A/S는 얼마 동안 해 줘요?")
    assert "price" not in policy_of("도배 견적이 적정한지 어떻게 알 수 있어요?")
    assert "price" in policy_of("도배 비용 얼마예요?") and "period" in policy_of(
        "도배 며칠 걸려요?"
    )


def test_grade_question_with_project_points_to_condition_change():
    f = ProjectFacts(area_m2=69.4, area_basis="supply", standard=STD, grade="basic")
    q = "합지 말고 실크로 하면 얼마나 더 비싸요?"
    out = calc_lines.price("dobae", f, general_facts(q), q)
    assert "실크(기본형)로 계산했고" in out.lines[0] and "조건 바꾸기" in out.lines[1]
    _ok(out)


def test_door_price_comes_from_carpentry_calc():
    q = "방문 교체 비용 얼마예요?"
    g = general_facts(q)
    out = calc_lines.price("mokgong", None, g, q)
    assert g.door_set and g.door_leaf and g.door_set > g.door_leaf
    assert "문틀까지" in out.lines[0] and len(out.boxes) == 2
    _ok(out)


def test_pair_period_does_not_add_numbers():
    out = calc_lines.pair_period(None, general_facts("도배랑 몰딩 같이 하면 며칠?"))
    assert all("목공 약" in r[1] and "도배 약" in r[1] for r in out.table)  # 더하지 않고 따로
    _ok(out)


def test_period_only_question_is_not_price():
    assert "price" not in policy_of("도배랑 몰딩 같이 하면 공사 기간이 얼마나 돼요?")
    assert "price" in policy_of("도배 비용이 얼마나 돼요?")


def test_vendor_pick_scores_and_reasons():
    c = [
        vendor_pick.Candidate("a", "가업체", True, 2_000_000, -6, 4.8, 20, 30),
        vendor_pick.Candidate("b", "나업체", True, 2_300_000, 8, 4.9, 2, 1),
        vendor_pick.Candidate(
            "c", "다업체", True, None, None, 5.0, 50, 50
        ),  # 가견적 없음 → 고르지 않음
        vendor_pick.Candidate("d", "라업체", True, 2_100_000, 0, None, 0, 5),
    ]
    picks = vendor_pick.pick(c)
    assert [p.c.name for p in picks] == [
        "가업체",
        "라업체",
        "나업체",
    ]  # 점수에는 표준 대비 %를 써요
    assert vendor_pick.reasons(picks[0]) == ["별점 4.8 · 리뷰 20개", "믿집 공사 30건"]


def test_vendor_pick_reasons_never_compare_with_standard():
    """추천 사유에 표준견적서와 견준 말이 없어요(사용자 결정 2026-11-21). %가 낮든 높든 같아요."""
    for pct in (-30, -6, 0, 8, 41, None):
        for local, instant in ((True, False), (False, True)):
            c = vendor_pick.Candidate("a", "가업체", local, 2_000_000, pct, 4.8, 3, 2, instant)
            (p,) = vendor_pick.pick([c], n=1)
            got = vendor_pick.reasons(p)
            assert got and not [r for r in got if "표준" in r or "%" in r], (pct, got)


def test_vendor_answer_with_and_without_project():
    v = VendorPickFact(vendor_id="a", name="마루와벽", reasons=["믿집 공사 31건"])
    out = calc_lines.vendors(ProjectFacts(vendors=[v]))
    assert out.cards[0].kind == "vendor_reco" and out.cards[0].vendors[0].name == "마루와벽"
    assert "고르는 건 고객님" in out.lines[0] and "광고로 순서를 바꾸지 않아요" in out.cards[0].text
    # 보인 기준 = 실제 계산(무게를 계산 엔진 상수에서 읽어요) · 가견적 부가세 포함 · 빠진 비용
    w = vendor_pick
    for x in (
        f"{w.W_RATING:.0%}",
        f"{w.W_DONE:.0%}",
        f"{w.W_PRICE:.0%}",
        "가까운 구",
        "부가세 포함",
    ):
        assert x in out.cards[0].text, x
    _ok(out)
    none = calc_lines.vendors(None)
    assert none.cards[0].choices[0].action == "start"


def test_choosing_a_vendor_goes_to_guide_but_recommendation_stays_trade():
    assert gate("좋은 도배 업체 고르는 법 알려 주세요").route == "guide"
    assert gate("도배 업체 한 곳만 추천해 주세요").route == "trade"
    t = time.perf_counter()
    gate("좋은" + " " * 40_000 + "업체")
    assert time.perf_counter() - t < 1.0


def test_payment_question_is_not_price():
    assert "price" not in policy_of("도배 계약금은 얼마나 줘야 해요?")
    assert "price" not in policy_of("잔금은 언제 줘요?")
    assert "price" in policy_of(
        "도배 평당 단가랑 계약금은 얼마예요?"
    )  # 시세 말이 같이 있으면 금액 질문


def test_free_answers_for_core_questions():
    """계산 답 뒤에 '모름' 줄이 붙지 않고, 계약금 질문은 금액 예시로 가지 않아요(유료 호출 0회)."""
    import asyncio
    import uuid

    from v3_kb import repo_kb

    from app.agent.v3.schemas import TurnContext
    from app.agent.v3.turn import run_turn

    ctx = TurnContext(user_id=uuid.UUID(int=0), today=date(2026, 11, 19), mode="free")

    def ask(q: str):
        return asyncio.run(run_turn(q, ctx, kb=repo_kb(), general=general_facts(q))).answer

    a = ask("도배 공사 며칠 걸려요?")
    assert a.sections[0].source == "calc" and not a.unknown
    a = ask("도배 계약금은 얼마나 줘야 해요?")
    assert not any(s.source == "calc" for s in a.sections) and not a.calc  # 시세 예시로 새지 않아요


def test_start_date_in_question_gives_end_date():
    from app.calc import schedule
    from app.chat.tools import asked_start

    today = date(2026, 11, 19)  # 목요일
    assert asked_start("12월 1일부터 하면 언제 끝나요?", today) == date(2026, 12, 1)
    assert asked_start("1/4부터 도배하면요?", today) == date(2027, 1, 4)
    assert asked_start("다음 주 월요일에 시작하면?", today) == date(2026, 11, 23)
    assert asked_start("내일 시작해요", today) == date(2026, 11, 20)
    assert asked_start("도배는 2.5일에 끝나요?", today) is None  # 기간을 날짜로 읽지 않아요
    assert asked_start("11월 3일에 했어요", today) == date(2027, 11, 3)  # 지난 날짜는 다음 해
    assert asked_start("2월 30일", today) is None
    # 반나절 단위 2.5일 → 일하는 날 3일, 주말은 건너뛰어요(11.27 금 → 11.30 월 · 12.1 화)
    assert schedule.span(date(2026, 11, 27), 2.5) == (date(2026, 11, 27), date(2026, 12, 1), 3)
    g = general_facts("12월 1일부터 34평 도배하면 언제 끝나요?", today)
    assert g.start == date(2026, 12, 1) and g.asked is not None and g.asked.dobae_dates
    out = calc_lines.period("dobae", None, g)
    assert any("12.1(화)에 시작하면 34평 도배는 12.1(화) ~ " in x for x in out.lines), out.lines
    _ok(out)
    g = general_facts("다음 주 월요일부터 도배하면 며칠 걸려요?", today)
    out = calc_lines.period("dobae", None, g)
    assert out.lines[0].startswith("11.23(월)에 시작하면 빈집 도배(벽 + 천장)는 평수에 따라")
    assert out.table[0] == ["24평", "11.23(월) ~ 11.24(화) · 약 2일"], out.table
    _ok(out)
    t0 = time.perf_counter()
    asked_start("1" * 5000 + "월" + "2" * 5000, today)  # 긴 입력에도 빨라요(ReDoS)
    assert time.perf_counter() - t0 < 0.5


def test_vendor_pick_accepts_decimal_rating():
    """업체 카드 별점은 Decimal로 와요(visit.schemas). float과 섞여도 점수를 내야 해요."""
    from decimal import Decimal

    c = vendor_pick.Candidate("a", "가업체", True, 2_000_000, -6, Decimal("4.8"), 12, 30)  # type: ignore[arg-type]
    (p,) = vendor_pick.pick([c], n=1)
    assert p.rating_shrunk == 4.56 and 0 < p.score <= 1.05  # (4.8 × 12 + 4.0 × 5) ÷ 17


def test_card_synonyms_find_bathroom_cards():
    """'화장실'로 물어도 '욕실' 열쇠 카드를 찾아요(카드 찾기 전용 같은 뜻 말, 좁게)."""
    from app.knowledge import cards

    cs = cards.default()
    a = cards.find(cs, "화장실 리모델링은 덧방이 나아요, 전체 철거가 나아요?", trades=["bath"], k=1)
    b = cards.find(cs, "욕실 리모델링은 덧방이 나아요, 전체 철거가 나아요?", trades=["bath"], k=1)
    assert a and b and a[0].card.id == b[0].card.id and a[0].score >= b[0].score - 0.01


def test_where_line_by_timing_and_topic():
    from app.agent.v3.answer import said_in, where_for

    assert where_for("업체 포트폴리오 사진이 진짜인지 어떻게 확인해요?", None) is None
    assert (
        where_for("몰딩 이음매가 벌어졌는데 언제까지 보수 요청할 수 있어요?", "mokgong")
        == "시공한 업체"
    )
    assert where_for("문틀 고정한 폼이 굳기 전에 문을 써도 돼요?", "mokgong") == "시공하는 업체"
    assert (
        where_for("계약서 특약에는 어떤 내용을 넣어요?", None) == "표준계약서 · 1372 소비자상담센터"
    )
    assert where_for("도배 비용이 궁금해요", "dobae") == "실측 때 업체"
    assert said_in("벽에 곰팡이나 물자국이 있나요?", "곰팡이 핀 벽은 어떻게 처리해요?")
    assert not said_in("벽에 곰팡이나 물자국이 있나요?", "도배 전에 뭘 준비해요?")


def test_said_start_and_area_carry_into_pair_dates():
    """앞 턴에 말한 32평 · 12월 1일을 이어받으면 목공 다음 도배를 그날부터 이어 놓은 날짜로 답해요(계산 엔진)."""
    from app.agent.v3.context import SaidArea

    today = date(2026, 11, 20)
    a32 = SaidArea(m2=105.8, label="32평")
    g = with_said(general_facts("목공도 같이 하면요?", today), a32, date(2026, 12, 1), today)
    out = calc_lines.pair_period(None, g)
    assert out.lines[0].startswith("믿집 계산으로 32평을 12.1(화)에 시작하면 목공은 12.1(화) ~ ")
    assert ", 도배는 " in out.lines[0] and out.lines[1].endswith("에 끝나요.")
    assert out.boxes[0].ref == "general.asked.pair"
    _ok(out)
    old = with_said(general_facts("목공도 같이 하면요?", today), a32, date(2026, 11, 1), today)
    assert (
        old.start is None and old.asked is not None
    )  # 지난 날짜는 이어받지 않아요(평수는 이어받아요)
