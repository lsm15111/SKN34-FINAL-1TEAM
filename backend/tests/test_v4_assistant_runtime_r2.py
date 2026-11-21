"""v4 비서 런타임 고침 2차(QA r2 갈래 E1): 요청이 틀린 400은 다시 보내지 않고 차단기에도 세지 않음(R1 · P1) ·
빈 글 블록을 보내지 않음 · 스트림 중간 실패 뒤 앞 시도 글(R11) · 도구 시간 상한(R12) · 무료 모드로 넘어간 턴의
LLM 글을 다시 열어도 보임(R14) · 단추로 이 턴에 만든 카드를 '이미 열려 있어요'로 말하지 않음(P17③) · 도구 hint ·
이름표 글이 고객 답에 나오지 않음(M3) · 앞 턴 고객 말의 숫자 · 버린 문장 까닭(P14).
유료 호출 0회(Claude 대본 · 가짜 HTTP 전송)."""

import json
import uuid
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant import runtime
from app.assistant.runtime import RefTable, TurnCtx, TurnResult
from tests.test_v4_assistant_turns import ask, home, ok, turn_row
from tests.test_v4_llm_claude import Nudge, _real_sdk
from tests.test_v4_llm_claude import run as run_llm


@pytest.fixture(autouse=True)
def repo_knowledge(monkeypatch):
    from app.knowledge import service as knowledge

    async def index(_s):
        return repo_index()

    monkeypatch.setattr(knowledge, "index", index)


@pytest.fixture
def script():
    llm.clear_stubs()
    yield llm.set_claude_script
    llm.clear_stubs()


def rejected(status: int = 400) -> Exception:
    """공급자가 요청 자체를 거절한 오류(진짜 SDK 오류 꼴)."""
    import anthropic
    import httpx2

    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    body = {
        "type": "error",
        "error": {
            "type": "invalid_request_error",
            "message": "text content blocks must be non-empty",
        },
    }
    cls = {
        400: anthropic.BadRequestError,
        413: anthropic.RequestTooLargeError,
        422: anthropic.UnprocessableEntityError,
    }[status]
    return cls(
        "요청이 틀렸어요", response=httpx2.Response(status, request=req, json=body), body=body
    )


def tokens(ev) -> str:
    return "".join(d["text"] for e, d, _ in ev if e == "token")


def trace(ev) -> dict:
    return json.loads(turn_row(ev[0][1]["turn_id"])["trace"])


# ---- R1 · P1: 요청이 틀린 400 ----


@pytest.mark.parametrize("status", [400, 413, 422])
def test_rejected_request_is_not_sent_again_nor_trips_the_breaker(api, script, status):
    _, pid = home(api, "a@mitjip.test")
    log = script([rejected(status), {"text": "다른 고객 답이에요."}])
    ev = ok(ask(api, pid, "표준견적서 얼마예요?"))
    assert ev[-1][1]["mode"] == "free" and len(log) == 1  # 같은 요청을 다시 보내지 않는다
    assert trace(ev)["reason"] == "rejected"
    assert api.portal.call(runtime.breaker_open) is False  # 서비스 차단기를 걸지 않는다
    api.cookies.clear()
    _, other = home(api, "b@mitjip.test")
    ev = ok(ask(api, other, "표준견적서 얼마예요?"))
    assert ev[-1][1]["mode"] == "llm" and len(log) == 2  # 다른 고객은 LLM 모드 그대로


def test_real_sdk_rejection_is_llm_rejected_and_overload_is_not(monkeypatch):
    import httpx2

    def reply(status: int, kind: str):
        return httpx2.Response(
            status, json={"type": "error", "error": {"type": kind, "message": "x"}}
        )

    replies = [
        reply(400, "invalid_request_error"),
        reply(400, "invalid_request_error"),
        reply(529, "overloaded_error"),
    ]
    install = _real_sdk(monkeypatch, lambda request: replies.pop(0))
    msgs = [{"role": "user", "content": "q"}]

    async def go():
        install()
        with pytest.raises(llm.LLMRejected):
            await llm.claude_stream("s", msgs)
        with pytest.raises(llm.LLMRejected):
            await llm.claude_json("check", Nudge, "s", "q")
        try:
            await llm.claude_stream("s", msgs)
        except llm.LLMError as e:
            return e
        return None

    got = run_llm(monkeypatch, go)
    assert isinstance(got, llm.LLMError) and not isinstance(got, llm.LLMRejected)  # 일시 오류


def _ctx(text: str, choice: list[str]) -> TurnCtx:
    return TurnCtx(
        turn_id=uuid.uuid4(),
        chat_id=uuid.uuid4(),
        user=SimpleNamespace(id=uuid.uuid4()),
        surface="customer",
        project_id=None,
        visit_id=None,
        today=date(2026, 11, 22),
        now=datetime(2026, 11, 22, 3, tzinfo=UTC),
        text=text,
        choice=choice,
        history=[],
        facts="오늘: 2026-11-22",
        rev=1,
        refs=RefTable(uuid.uuid4()),
        client_key="key-12345678",
    )


def test_messages_never_carry_an_empty_text_block():
    async def emit(_name: str, _data: dict) -> None:
        return None

    msgs = runtime._Turn(_ctx("", ["v1"]), emit, TurnResult())._messages()
    (block,) = msgs[-2]["content"]
    assert block["text"] == "(카드에서 고름: v1)"  # 빈 말 앞 줄 바꿈 없이


def test_blank_text_does_not_call_the_llm(api, script):
    _, pid = home(api)
    log = script([{"text": "부르면 안 돼요."}])
    r = ask(api, pid, "   ")
    if r.status_code == 422:  # 입구가 가린 뒤 빈 말을 막으면 그것으로 됐다
        return
    ev = ok(r)
    assert ev[-1][1]["mode"] == "free" and log == []  # 빈 글 블록을 보내지 않는다
    assert trace(ev)["reason"] == "empty"
    assert api.portal.call(runtime.breaker_open) is False
