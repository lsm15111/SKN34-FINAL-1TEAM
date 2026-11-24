"""v4 QA 9차 고침 F1 지시문(customer_v4 · nudge_write_v3, QA r9 c1 · c2): 첫 답 안내가 누출로 빠지지 않기 · 도배 밖 일 끝도
지금 단계 · 단추 이름 · '표준견적서' · 가림 말 · 첫 견적서만 왔을 때 확정 권하지 않기. 유료 호출 0회."""


def test_first_answer_line_is_not_a_leak():
    """M4: 첫 답의 '도배 궁금한 점 · 직접 할 일 · 집 조건 바꾸기' 안내를 지시문 예시 그대로 써도 누출로 빠지지
    않아요(c1 · c2 T1 trace '지시문 누출'). 지시문의 다른 규칙 글은 그대로 걸러요."""
    from app.agent.v3 import check
    from app.agent.v3.schemas import Sentence
    from app.assistant import prompts

    rules = prompts.rules("customer")
    for line in (
        "도배 궁금한 점 · 직접 할 일 · 집 조건 바꾸기도 물어보세요.",
        "도배 궁금한 점 · 직접 할 일 · 집 조건 바꾸기도 물어보실 수 있어요.",
    ):
        got, why = check.sentence_ok(Sentence(text=line), set(), None, None, rules)
        assert got is not None, why
    assert "도배 궁금한 점 · 직접 할 일 · 집 조건 바꾸기도 물어보세요." in prompts.text("customer")
    leak = "도구를 부를 땐 결과를 보고 나서 써. 도구 앞에 쓴 글도 고객에게 그대로 보여요."
    assert check.sentence_ok(Sentence(text=leak), set(), None, None, rules)[1] == "지시문 누출"


def test_rules_bring_out_of_scope_answers_back_to_the_step():
    """M2: 도배 밖 일 답의 끝도 지금 단계의 다음 걸음이에요('실측 때 도배 업체에 물어보세요'는 요청 뒤에만). 지난 답과
    같은 지금 단계 문장은 다시 풀어 말하지 않아요."""
    from app.assistant import prompts

    rules = prompts.rules("customer").splitlines()
    other = next(x for x in rules if x.startswith("- 도배 밖 일"))
    assert "끝은 다른 답처럼 지금 단계의 다음 걸음 하나야" in other
    assert "실측 요청을 보낸 뒤(턴 사실 업체 줄)에 도배와 맞물리는 일일 때만" in other
    end = next(x for x in rules if x.startswith("- 끝은 지금 단계의 다음 걸음"))
    assert "범위 밖에는 바닥 · 욕실 · 전기 같은 도배 밖 공사도 들어" in end
    assert "지난 답에서 이미 말했으면 다시 풀어 말하지 말고" in end


def test_rules_name_buttons_words_masks_and_first_quote():
    """그대로 · 낮음: 단추 이름 넣기 · '표준견적서' · 가림 말 · 첫 견적서만 왔을 때 확정 권하지 않기."""
    from app.assistant import prompts

    rules = prompts.rules("customer")
    assert "'카드를 눌러 주세요'로 끝내지 말고 단추 이름을 넣어" in rules
    assert "'승인 기다리는 카드' 끝 [ ] 안" in rules
    assert "'표준견적'으로 줄이지 말고 '표준견적서'" in rules
    assert "'(번호 가림)' 같은 표시는 믿집이 가린 자리라" in rules
    assert "다른 업체 견적서를 기다리는 중(턴 사실 업체 줄)이면 업체 확정을 권하지 말고" in rules
    nudge = prompts.text("nudge_write")
    assert "- waiting: 아직 실측 견적서를 기다리는 업체야. 업체 확정을 권하지 말고" in nudge
