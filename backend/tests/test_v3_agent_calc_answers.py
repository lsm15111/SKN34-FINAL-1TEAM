"""기간 · 비용 · 업체 추천 답(calc_lines · vendor_pick · tools.general_facts). 숫자는 모두 계산 엔진 값. DB 없음."""

import time
from datetime import date

from app.agent.v3 import calc_lines
from app.agent.v3.gate import gate
from app.agent.v3.policy import policy_of
from app.agent.v3.schemas import PlanFacts, ProjectFacts, StandardFacts, VendorPickFact
from app.calc import vendor_pick
from app.chat.tools import asked_area, general_facts
from app.v2 import guard

PLAN = PlanFacts(start=date(2027, 1, 4), end=date(2027, 1, 5), work_days=2)
STD = StandardFacts(total=1974069, supply=1794608, vat=179461)


def _ok(lines: calc_lines.Lines) -> None:
    """문장 숫자가 모두 계산 값 글(calc_text)에 있어서 출력 검사를 지나는지."""
    allowed = guard.numbers(lines.calc_text)
    for t in lines.lines:
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


def test_period_without_project_uses_examples_or_asked_size():
    ex = calc_lines.period("dobae", None, general_facts("도배 공사 며칠 걸려요?"))
    assert "24평" in ex.lines[0] and "34평" in ex.lines[0] and "44평" in ex.lines[0]
    assert ex.cards and ex.cards[0].choices[0].action == "start"
    _ok(ex)
    one = calc_lines.period("dobae", None, general_facts("34평 도배하면 며칠 걸려요?"))
    assert one.lines[0].startswith("믿집 계산으로 34평 도배는 빈집이면 약 ")
    _ok(one)


def test_price_project_and_asked_size_differ():
    f = ProjectFacts(area_m2=69.4, area_basis="supply", standard=STD, grade="basic")
    out = calc_lines.price("dobae", f, general_facts("33평 도배 비용 얼마예요?"), "33평 도배 비용")
    assert out.lines[0] == "이 집 표준견적서 합계는 부가세 포함 약 197만 원이에요."
    assert any(x.startswith("물어보신 33평이면") for x in out.lines)
    _ok(out)


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
    assert "목공 약" in out.lines[0] and "도배 약" in out.lines[0]
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
    assert [p.c.name for p in picks] == ["가업체", "라업체", "나업체"]
    assert vendor_pick.reasons(picks[0]) == [
        "별점 4.8 · 리뷰 20개", "믿집 공사 30건", "가견적이 표준견적서보다 6% 낮아요",
    ]  # fmt: skip


def test_vendor_answer_with_and_without_project():
    v = VendorPickFact(vendor_id="a", name="마루와벽", reasons=["믿집 공사 31건"])
    out = calc_lines.vendors(ProjectFacts(vendors=[v]))
    assert out.cards[0].kind == "vendor_reco" and out.cards[0].vendors[0].name == "마루와벽"
    assert "고르는 건 고객님" in out.lines[0] and "광고로 순서를 바꾸지 않아요" in out.cards[0].text
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
