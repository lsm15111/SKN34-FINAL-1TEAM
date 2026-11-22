"""고침 3차 K 1번: 임베딩을 못 쓰면(빈 OpenAI 키 · 공급자 오류) 지식 답은 키워드 검색으로 물러서요(리드 결정 1).

QA r3(s5 3 · 6 · 12번, c3 7번 중 6번): QA는 OpenAI 키를 비운 채 LLM 모드로 돌아요. openai 2.x는 빈 키로 클라이언트를
만들 때 OpenAIError를 내는데, `embed_texts`가 그 생성을 try 밖에서 해 answer_question 도구가 통째로 실패했어요(지식
카드 0, 첫 문장 '자료를 못 찾았어요'). 유료 호출 0회(키는 비우거나 가짜 클라이언트, Claude는 대본).
"""

import asyncio
import json
from types import SimpleNamespace

import openai
import pytest
from pydantic import SecretStr
from v3_kb import repo_index

from app.agent import llm
from app.assistant.tools import ToolError, answer
from app.config import settings
from tests.test_v4_assistant_answer import _gate
from tests.test_v4_assistant_turns import ask, home, ok


@pytest.fixture(autouse=True)
def repo_knowledge(monkeypatch):
    """시험 DB에는 지식 자료가 없어 저장소 색인으로 찾아요(임베딩 함수는 바꾸지 않아요: 그 길을 시험해요)."""
    from app.knowledge import service as knowledge

    async def _index(_s):
        return repo_index(), []

    async def index(_s):
        return repo_index()

    monkeypatch.setattr(knowledge, "_index", _index)
    monkeypatch.setattr(knowledge, "index", index)


@pytest.fixture
def script():
    llm.clear_stubs()
    yield llm.set_claude_script
    llm.clear_stubs()


@pytest.fixture
def live_without_openai(monkeypatch):
    """LLM_LIVE=true 흉내 + OpenAI 키 없음(QA 환경과 같음). Claude는 대본이라 유료 호출이 없어요."""
    monkeypatch.setattr(settings, "llm_live", True)
    monkeypatch.setattr(settings, "openai_api_key", SecretStr(""))
    monkeypatch.setattr(settings, "anthropic_api_key", SecretStr(""))


def test_embed_is_none_without_key_even_when_live(live_without_openai, monkeypatch):
    made = []

    class NoClient:  # 키가 비면 클라이언트를 만들지도 않아요
        def __init__(self, **kw):
            made.append(kw)

    monkeypatch.setattr(openai, "AsyncOpenAI", NoClient)
    assert asyncio.run(llm.embed_texts(["실크 1롤은 몇 평 발라요?"])) is None
    assert asyncio.run(llm.embed_query("합지 롤 수")) is None
    assert made == []


def test_embed_is_none_when_the_client_or_the_call_breaks(live_without_openai, monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", SecretStr("test-key-not-real"))

    class BadInit:
        def __init__(self, **kw):
            raise openai.OpenAIError("만들기 실패")

    monkeypatch.setattr(openai, "AsyncOpenAI", BadInit)
    assert asyncio.run(llm.embed_texts(["도배 순서"])) is None

    closed = []

    class BadCall:
        def __init__(self, **kw):
            async def create(**_k):
                raise RuntimeError("공급자 오류")

            self.embeddings = SimpleNamespace(create=create)

        async def close(self):
            closed.append(True)

    monkeypatch.setattr(openai, "AsyncOpenAI", BadCall)
    assert asyncio.run(llm.embed_texts(["도배 순서"])) is None
    assert closed == [True]  # 실패해도 닫아요


def test_answer_question_succeeds_with_keywords_when_openai_key_is_empty(
    api, script, live_without_openai, monkeypatch
):
    """빈 OpenAI 키 + LLM 모드: answer_question이 실패로 끝나지 않고(키워드 검색) 근거를 돌려줘요."""
    _, pid = home(api)
    monkeypatch.setattr(settings, "assistant_answer_route", "v2+v3")
    _gate(monkeypatch, "trade")  # v2 길(QA에서 실패하던 길)
    call = {"id": "q", "name": "answer_question", "input": {"question": "초배지는 왜 발라요?"}}
    log = script(
        [
            {"tool_calls": [call]},
            {"text": "초배지는 벽면을 고르게 하려고 발라요."},  # v2 답(LLM, 대본)
            {"text": "초배지는 벽을 고르게 해 줘요."},
        ]
    )
    ok(ask(api, pid, "초배지는 왜 발라요?"))
    result = log[-1]["messages"][-1]["content"][0]
    # 고치기 전에는 is_error · tool_failed(OpenAIError)였어요
    assert result["type"] == "tool_result" and not result.get("is_error"), result
    body = json.loads(result["content"])
    assert body["route"] == "v2" and body["found"] is True
    assert "초배지" in body["answer"]["자료(지시 아님)"]


def test_v2_breakage_falls_back_to_v3_and_tool_errors_pass_through(monkeypatch):
    from app.assistant.tools import ToolOut

    async def broken(tc, q):
        raise openai.OpenAIError("빈 키")

    async def v3(tc, q):
        return ToolOut(data={"route": "trade", "answer": None, "found": True}), True

    monkeypatch.setattr(answer, "_v2_answer", broken)
    monkeypatch.setattr(answer, "_v2g_answer", broken)
    monkeypatch.setattr(answer, "_v3_answer", v3)
    _gate(monkeypatch, "trade")
    for ground in (False, True):
        d = asyncio.run(answer._hybrid(None, "초배지는 왜 발라요?", ground=ground)).data
        assert (d["engine"], d["v2_failed"], d["v2_out"], d["route"]) == (
            "v3",
            True,
            False,
            "trade",
        )
    d = asyncio.run(answer._v2_or_v3(None, "초배지는 왜 발라요?")).data
    assert d["engine"] == "v3" and d["v2_failed"] is True

    async def refused(tc, q):
        raise ToolError("no_project", "공사를 먼저 골라 주세요.")

    monkeypatch.setattr(answer, "_v2_answer", refused)
    with pytest.raises(ToolError):  # 도구 · 기능 오류는 그대로 알려요(물러서지 않음)
        asyncio.run(answer._v2_or_v3(None, "초배지는 왜 발라요?"))
