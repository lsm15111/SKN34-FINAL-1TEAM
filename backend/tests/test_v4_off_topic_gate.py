"""v4 범위 밖 막기(LLM 모드): 인테리어와 상관없는 부탁 · 잡담은 LLM을 부르지 않고 무료 모드의 범위 밖 답 틀로 막아요
(2026-11-23 사용자: '치킨 먹고 싶다'에 맞장구). 공사 낱말이 있거나, 대신 전화 · 문자 부탁이거나, 비서가 바로 앞에서
물었으면 LLM이 답해요. 유료 호출 0회(Claude 대본)."""

import json
import re

import pytest

from app.agent import llm
from app.assistant.runtime import asked_last
from tests.test_v4_assistant_turns import ask, home, ok, turn_row

CHATTY = "치킨이 당기시나 봐요! 바삭한 후라이드도 좋겠네요."


@pytest.fixture
def script():
    llm.clear_stubs()
    yield llm.set_claude_script
    llm.clear_stubs()


def answer(ev) -> str:
    return "".join(
        d["data"].get("text", "") for e, d, _ in ev if e == "card" and d.get("kind") == "answer"
    )


def trace_of(ev) -> dict:
    t = turn_row(ev[0][1]["turn_id"])["trace"]
    return json.loads(t) if isinstance(t, str) else t


@pytest.mark.parametrize(
    "text", ["치킨먹고싶다", "오늘 날씨 어때?", "비트코인 사도 돼?", "끝말잇기 하자"]
)
def test_unrelated_talk_is_blocked_without_llm(api, script, text):
    _, pid = home(api)
    log = script([{"text": CHATTY}])
    ev = ok(ask(api, pid, text))
    assert log == []  # LLM을 부르지 않아요
    said = answer(ev)
    assert said and CHATTY not in said
    # 범위 밖 답 틀의 솔직 문장(못 하는 까닭)
    assert re.search(r"못|없어요|어려워요|몰라|집 공사", said)
    assert ev[-1][1]["mode"] == "free" and trace_of(ev)["reason"] == "off_topic"


@pytest.mark.parametrize(
    "text", ["도배하고 치킨 먹을래요", "업체에 전화 좀 해 줘", "도배 순서 알려줘"]
)
def test_work_words_and_call_requests_go_to_the_model(api, script, text):
    _, pid = home(api)
    log = script([{"text": "네, 이어서 도와드릴게요."}])
    ev = ok(ask(api, pid, text))
    assert len(log) == 1 and ev[-1][1]["mode"] == "llm"


def test_answer_to_the_assistant_question_is_not_blocked(api, script):
    _, pid = home(api)
    log = script(
        [{"text": "언제쯤 공사를 시작하고 싶으세요?"}, {"text": "네, 그때쯤으로 생각해 둘게요."}]
    )
    ok(ask(api, pid, "도배 언제 하면 좋아요?"))
    ev = ok(ask(api, pid, "날씨 풀리면요"))
    assert len(log) == 2 and ev[-1][1]["mode"] == "llm"


def test_asked_last_reads_the_last_assistant_text():
    q = {"role": "assistant", "content": [{"type": "text", "text": "언제쯤 시작하고 싶으세요?"}]}
    told = {"role": "assistant", "content": "표준견적서를 열어 두었어요."}
    user = {"role": "user", "content": "날씨 풀리면요"}
    assert asked_last([q, user]) is True
    assert asked_last([q, told, user]) is False
    assert asked_last([user]) is False
