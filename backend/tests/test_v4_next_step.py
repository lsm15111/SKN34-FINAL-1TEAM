"""v4 지식 답 뒤 다음 할 일 한 줄(2026-11-23 사용자: 쓰면서 다음 흐름으로 이끌기): 지식 도구로 답한 턴에 다음 일 카드 ·
승인 카드가 없고 답이 물음으로 끝나지 않으면 코드가 지금 할 일 줄을 붙여요. 같은 단계에서는 한 번만이에요.
유료 호출 0회(Claude 대본)."""

import pytest

from app.agent import llm
from tests.test_v4_assistant_turns import ask, home, ok

ASK = {"id": "q", "name": "answer_question", "input": {"question": "실크벽지 들뜸은 왜 생겨요?", "kind": "general"}}
SAID = "바탕이 고르지 않거나 초배가 덜 되면 들뜰 수 있어요."


@pytest.fixture
def script():
    llm.clear_stubs()
    yield llm.set_claude_script
    llm.clear_stubs()


def said(ev) -> str:
    return "".join(d.get("text", "") for e, d, _ in ev if e == "token")


def test_knowledge_answer_gets_the_next_step_once(api, script):
    _, pid = home(api)
    script([{"tool_calls": [ASK]}, {"text": SAID}, {"tool_calls": [ASK]}, {"text": SAID}])
    first = said(ok(ask(api, pid, "실크벽지 들뜸은 왜 생겨요?")))
    assert first.startswith(SAID) and first.rstrip().endswith("차례예요.")
    again = said(ok(ask(api, pid, "실크벽지 들뜸은 왜 생겨요?")))  # 같은 단계: 다시 붙이지 않아요
    assert again.strip() == SAID


def test_no_next_step_when_the_answer_asks_back(api, script):
    _, pid = home(api)
    script([{"tool_calls": [ASK]}, {"text": "들뜬 곳이 천장인가요, 벽인가요?"}])
    assert "차례예요" not in said(ok(ask(api, pid, "실크벽지 들뜸은 왜 생겨요?")))


def test_no_next_step_without_knowledge_tools(api, script):
    _, pid = home(api)
    script([{"text": "철거 → 목공 → 도배 순서예요."}])
    assert said(ok(ask(api, pid, "도배 순서 알려줘"))).strip() == "철거 → 목공 → 도배 순서예요."


def test_no_next_step_when_a_step_card_is_shown(api, script):
    _, pid = home(api)
    show = {"id": "s", "name": "show_card", "input": {"kind": "standard_quote"}}
    script([{"tool_calls": [ASK, show]}, {"text": SAID}])
    ev = ok(ask(api, pid, "실크벽지 들뜸은 왜 생겨요?"))
    assert "standard_quote" in [d["kind"] for e, d, _ in ev if e == "card"]
    assert "차례예요" not in said(ev)
