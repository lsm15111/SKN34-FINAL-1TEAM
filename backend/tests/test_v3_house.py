"""이 집 답 모양(agent-08 무료 판): 결론 한 줄 · 이 집 견적서 카드 · 업체에 요청할 말."""

import re

from test_v3_agent_turn import FACTS, turn

from app.agent.v3 import gate, templates

DIGIT = re.compile(r"\d")


def test_quote_line_question_gets_house_card_and_calc_numbers_only():
    a = turn("철거는 왜 합계에 안 들어가요?", facts=FACTS).answer
    assert a.lead  # 첫 문장이 결론으로 올라와요
    (card,) = [c for c in a.cards if c.kind == "house"]
    assert card.title == "이 집 견적서의 기존 벽지 철거"
    rows = {r.cells[0]: r.cells[1] for r in card.table.rows}
    assert (
        rows["수량 · 단가"] == "173.5㎡ · 1,727원" and rows["금액"] == "299,635원"
    )  # 계산 값 그대로
    assert len(a.vendor) == 2 and "173.5㎡" in a.vendor[0] and a.vendor[1].endswith("적어 주세요.")
    assert "업체에:" in a.plain()  # 다음 턴 직전 대화에도 남아요


def test_meaning_question_goes_to_trade_and_vendor_has_no_numbers():
    g = gate.gate(
        "퍼티 작업이 뭐야?", view=None, waiting=None, button=None, has_project=True, ignore=[]
    )
    assert g.route == "trade"  # 날짜 말이 없는 뜻 질문은 일정이 아니에요
    a = turn("퍼티 작업이 뭐야?", facts=FACTS).answer
    assert a.lead.startswith("퍼티")
    assert len(a.vendor) == 2 and "퍼티 작업" in a.vendor[0]
    assert not any(DIGIT.search(v) for v in a.vendor)  # 계산 값이 없으면 숫자를 쓰지 않아요
    assert not [
        c for c in a.cards if c.kind == "house"
    ]  # 금액을 묻지 않았으니 견적서 카드는 없어요


def test_problem_question_asks_cause_first_without_verdict():
    from app.agent.v3.schemas import Button

    first = turn("벽지에 곰팡이가 폈어요", facts=FACTS)
    assert first.answer.ask is not None and first.answer.vendor == []  # 되묻는 턴은 부탁 줄 없음
    a = turn("있어요", facts=FACTS, waiting=first.waiting,
             button=Button(route="trade", trade="dobae", slot="dobae.mold", value="있어요")).answer  # fmt: skip
    assert a.vendor[0].startswith("곰팡이가 왜 그런지 원인부터")  # 칸 답은 원래 질문으로 고른다
    assert not any(re.search(r"하자예요|보상|업체\s*잘못", v) for v in a.vendor)
    assert not [
        c for c in a.cards if c.kind == "house"
    ]  # '벽지' 낱말만으로 견적서 줄을 붙이지 않아요


def test_guide_question_keeps_old_shape():
    a = turn("계약서는 언제 써요?", facts=FACTS).answer
    assert a.lead == "" and a.vendor == []


def test_shape_skips_filler_and_misreads():
    # 자료에서 뽑은 답의 채움 글은 결론이 아니에요
    a = turn("도배 전에 곰팡이 어떻게 없애요?", facts=FACTS).answer
    assert a.lead and a.lead != templates.EXTRACT_SUMMARY_LEAD
    # '얼마나'(수명 · 기간)는 금액 질문이 아니에요: 견적서 카드 · 견적 부탁을 붙이지 않아요
    a = turn("합지 벽지 수명은 얼마나 가요?", facts=FACTS).answer
    assert not [c for c in a.cards if c.kind == "house"]
    assert not any("견적서에는" in v for v in a.vendor)
    # 문제 낱말이 있어도 기간을 물으면 원인 확인 부탁을 쓰지 않아요
    a = turn("도배 들뜸 보수 기간은 언제까지예요?", facts=FACTS).answer
    assert not any("원인부터" in v for v in a.vendor)
    # 공종 이름만 있는 금액 질문에 줄 하나짜리 카드를 붙이지 않아요
    a = turn("도배 얼마예요?", facts=FACTS).answer
    assert not [c for c in a.cards if c.kind == "house"]


def test_ask_turn_keeps_old_shape_and_slot_answer_uses_asked_question():
    from app.agent.v3.schemas import Button

    first = turn("합지랑 실크 중에 뭐로 해야 해요?")
    assert first.answer.ask is not None  # 되묻는 턴
    assert first.answer.lead == "" and first.answer.vendor == []
    r = turn("세 놓을 집", waiting=first.waiting,
             button=Button(route="trade", trade="dobae", slot="dobae.grade", value="세 놓을 집"))  # fmt: skip
    assert r.answer.ask is None
    # 칸 답('세 놓을 집')만으로는 작업 이름이 없어요: 되물은 원래 질문의 '합지'로 부탁 줄을 골라요
    assert len(r.answer.vendor) == 2 and "합지" in r.answer.vendor[0]


def test_choice_button_route_goes_to_trade():
    """리뷰 회귀: '공사 방법과 자재가 궁금해요' 선택지는 단추의 길(route)로 공정 상담에 가요.
    화면이 단추 정보를 빼고 글만 보내면 다시 고르라는 답(ask_back)이 돼요."""
    from app.agent.v3.schemas import Button

    q = "공사 방법과 자재가 궁금해요"
    assert turn(q, facts=FACTS).answer.trace.route == "ask_back"
    assert turn(q, facts=FACTS, button=Button(route="trade")).answer.trace.route == "trade"
