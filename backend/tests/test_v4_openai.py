"""v4 OpenAI 길(LLM_PROVIDER=openai, docs/v4/10-openai.md): claude_stream · claude_json을 OpenAI Responses로 보낸다.
유료 호출 0회(가짜 OpenAI 클라이언트 · 가짜 HTTP 전송).

- 꼴 바꾸기: Claude 꼴 messages(글 · 그림 · tool_use · tool_result · system · 생각 · 서버 도구 블록) → Responses
  input, 도구(함수 + Claude 웹 도구 → web_search 하나), tool_choice, 막은 곳 안내 말, utm_source 떼기.
- 비서 턴: 글 조각이 그대로 흐르고, 도구 부름 → 도구 결과가 function_call_output으로 다음 요청에 간다. 장부는 OpenAI
  가격표로 센다.
- 조사: web_search_call(검색 · 열기 · 실패한 열기)이 Claude 서버 도구 블록 꼴로 바뀌어 진행 기록 · 항목 · 그림이 Claude
  길과 같은 규칙으로 나온다(막은 곳 · 가져오기를 막은 곳은 남지 않는다).
- 구조화 답: json_schema(엄격) → 값, 거절 · 잘림 · 꼴 틀림 · 400 · 실패. 도면 읽기는 OpenAI로 가지 않는다.
- 진짜 SDK(AsyncOpenAI)를 가짜 HTTP로: SSE 이벤트를 SDK가 읽은 꼴 그대로 받는다.
"""

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from pydantic import SecretStr
from v3_kb import repo_index

from app.agent import llm
from app.assistant import linkimage, research
from app.assistant.models import AssistantResearch
from app.config import settings
from app.db import SessionLocal
from app.usage import prices
from tests.conftest import query
from tests.test_v4_assistant_turns import PHONE_TEXT, ask, home, names, ok, turn_row
from tests.test_v4_llm_claude import Nudge
from tests.test_v4_llm_claude import rows as usage_rows
from tests.test_v4_llm_claude import run as run_loop
from tests.test_v4_research import result_of, rows, run, start_turn
from tests.test_v4_research_trail import GUIDE, LX, LX_IMG, MAP, SH, SOOMGO, html, pages, text


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


def ns(x):
    """dict · list → 속성으로 읽는 가짜 SDK 값."""
    if isinstance(x, dict):
        return SimpleNamespace(**{k: ns(v) for k, v in x.items()})
    if isinstance(x, list):
        return [ns(v) for v in x]
    return x


def usage(inp: int, out: int, cached: int = 0, wrote: int = 0, reasoning: int = 0) -> dict:
    return {
        "input_tokens": inp,
        "input_tokens_details": {"cached_tokens": cached, "cache_write_tokens": wrote},
        "output_tokens": out,
        "output_tokens_details": {"reasoning_tokens": reasoning},
        "total_tokens": inp + out,
    }


def completed(u: dict, model: str = "gpt-6.1-terra", reason: str | None = None):
    status = "incomplete" if reason else "completed"
    return ns({
        "type": f"response.{status}",
        "response": {"model": model, "status": status, "usage": u,
                     "incomplete_details": {"reason": reason} if reason else None},
    })  # fmt: skip


def message(said: str, cites: tuple = ()) -> dict:
    notes = [
        {"type": "url_citation", "url": u, "title": t, "start_index": 0, "end_index": 1}
        for u, t in cites
    ]
    return {"type": "message", "id": "msg_1", "role": "assistant",
            "content": [{"type": "output_text", "text": said, "annotations": notes}]}  # fmt: skip


def say(said: str, cites: tuple = ()) -> list:
    """글 항목: 시작 → 조각 → 끝."""
    m = message(said, cites)
    parts = [said[i : i + 5] for i in range(0, len(said), 5)]
    return [
        ns({"type": "response.output_item.added", "item": {**m, "content": []}}),
        *[ns({"type": "response.output_text.delta", "delta": p}) for p in parts],
        ns({"type": "response.output_item.done", "item": m}),
    ]


def search(id_: str, q: str, urls: list[str]) -> list:
    item = {"type": "web_search_call", "id": id_, "status": "completed",
            "action": {"type": "search", "query": q, "sources": [{"type": "url", "url": u} for u in urls]}}  # fmt: skip
    start = {**item, "status": "in_progress", "action": {"type": "search", "query": None}}
    return [
        ns({"type": "response.output_item.added", "item": start}),
        ns({"type": "response.output_item.done", "item": item}),
    ]


def opened(id_: str, url: str, status: str = "completed") -> list:
    """페이지 열기. 시작 때는 아직 검색인지 열기인지 모른다(검색으로 알렸다가 끝에서 열기로 고친다)."""
    item = {"type": "web_search_call", "id": id_, "status": status,
            "action": {"type": "open_page", "url": url}}  # fmt: skip
    start = {**item, "status": "in_progress", "action": {"type": "search", "query": None}}
    return [
        ns({"type": "response.output_item.added", "item": start}),
        ns({"type": "response.output_item.done", "item": item}),
    ]


def called(call_id: str, name: str, args: dict) -> list:
    item = {"type": "function_call", "id": f"fc_{call_id}", "call_id": call_id, "name": name,
            "arguments": json.dumps(args, ensure_ascii=False), "status": "completed"}  # fmt: skip
    return [
        ns({"type": "response.output_item.added", "item": {**item, "arguments": ""}}),
        ns({"type": "response.output_item.done", "item": item}),
    ]


def answer(said: str = "", *, refusal: bool = False, status: str = "completed", reason=None):
    """스트림 아닌 응답(구조화 답)."""
    part = {"type": "refusal", "refusal": "안 돼요"} if refusal else {
        "type": "output_text", "text": said, "annotations": []}  # fmt: skip
    r = ns({"model": "gpt-6-luna", "status": status, "usage": usage(800, 40),
            "incomplete_details": {"reason": reason} if reason else None,
            "output": [{"type": "message", "content": [part]}]})  # fmt: skip
    r.output_text = "" if refusal else said
    return r


class Stream:
    def __init__(self, events: list) -> None:
        self.events = events

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def __aiter__(self):
        for e in self.events:
            if isinstance(e, BaseException):
                raise e
            yield e


class Responses:
    def __init__(self, steps: list) -> None:
        self.steps, self.log = list(steps), []

    async def create(self, **req):
        self.log.append(json.loads(json.dumps(req, ensure_ascii=False, default=str)))
        step = self.steps.pop(0)
        if isinstance(step, BaseException):
            raise step
        return Stream(step) if req.get("stream") else step


@pytest.fixture
def openai(monkeypatch):
    """OpenAI 길을 켜고 가짜 클라이언트를 끼운다. 돌려준 함수에 단계(스트림이면 이벤트 목록, 아니면 응답 · 예외)를
    넣으면 보낸 요청 목록을 돌려준다. 다른 유료 길(임베딩 · LangChain)은 부르면 실패하게 막는다."""
    llm.clear_stubs()

    async def no_embed(_texts):
        return None

    async def no_langchain(*_a, **_k):
        raise AssertionError("LangChain OpenAI 길을 부르면 안 돼요")

    monkeypatch.setattr(llm, "embed_texts", no_embed)
    monkeypatch.setattr(llm, "_openai_structured", no_langchain)

    def install(steps: list) -> list:
        r = Responses(steps)
        monkeypatch.setattr(llm, "_openai", lambda: SimpleNamespace(responses=r))
        monkeypatch.setattr(settings, "llm_live", True)
        monkeypatch.setattr(settings, "llm_provider", "openai")
        monkeypatch.setattr(settings, "openai_api_key", SecretStr("test-not-real"))
        monkeypatch.setattr(settings, "jev_enabled", False)
        return r.log

    yield install
    llm.clear_stubs()


def bad_request():
    import openai as sdk

    req = httpx.Request("POST", "https://api.openai.com/v1/responses")
    return sdk.BadRequestError("bad", response=httpx.Response(400, request=req), body=None)


def test_claude_messages_and_tools_become_responses_shape():
    msgs = [
        {"role": "user", "content": "벽지 고르고 싶어요"},
        {"role": "assistant", "content": [
            {"type": "thinking", "thinking": "", "signature": "s"},
            {"type": "text", "text": "알아볼게요."},
            {"type": "tool_use", "id": "toolu_1", "name": "start_research", "input": {"kind": "materials"}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_1", "content": '{"ok": true}', "is_error": False},
            {"type": "text", "text": "지금까지로 답해요"},
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "QUJD"}},
        ]},
        {"role": "system", "content": "지금: 11월 23일"},
        {"role": "assistant", "content": [
            {"type": "server_tool_use", "id": "srv_1", "name": "web_search", "input": {"query": "q"}},
            {"type": "web_search_tool_result", "tool_use_id": "srv_1", "content": []},
            {"type": "text", "text": "요약: 끝"},
        ]},
        {"role": "assistant", "content": ""},
    ]  # fmt: skip
    assert llm._oa_input(msgs) == [
        {"role": "user", "content": "벽지 고르고 싶어요"},
        {"role": "assistant", "content": "알아볼게요."},  # 생각 블록은 뺀다
        {"type": "function_call", "call_id": "toolu_1", "name": "start_research",
         "arguments": '{"kind": "materials"}'},
        {"type": "function_call_output", "call_id": "toolu_1", "output": '{"ok": true}'},
        {"role": "user", "content": [
            {"type": "input_text", "text": "지금까지로 답해요"},
            {"type": "input_image", "image_url": "data:image/png;base64,QUJD", "detail": "auto"}]},
        {"role": "system", "content": "지금: 11월 23일"},
        {"role": "assistant", "content": "요약: 끝"},  # 서버 도구 블록은 뺀다
    ]  # fmt: skip

    schema = {"type": "object", "properties": {"x": {"type": "string"}}}
    tools, web = llm._oa_tools([
        {"name": "b_tool", "description": "B", "input_schema": schema, "strict": True},
        {"name": "a_tool", "description": "A", "parameters": {"type": "object", "properties": {}}},
        research.SEARCH_TOOL,
        research.FETCH_TOOL,
        {"type": "code_execution_20260120", "name": "code_execution"},
    ])  # fmt: skip
    assert [t.get("name", t["type"]) for t in tools] == ["a_tool", "b_tool", "web_search"]
    assert tools[1] == {
        "type": "function", "name": "b_tool", "description": "B", "parameters": schema,
        "strict": False,
    }  # fmt: skip
    assert tools[2] == llm.OA_WEB_TOOL and web == 8  # 검색 4 + 가져오기 4
    assert llm._oa_choice(None) == llm._oa_choice({"type": "auto"}) == "auto"
    assert llm._oa_choice({"type": "none"}) == "none"
    assert llm._oa_choice({"type": "any"}) == "required"
    assert llm._oa_choice({"type": "tool", "name": "x"}) == {"type": "function", "name": "x"}

    # 토큰: 입력은 캐시 읽기 · 쓰기를 뺀 값, 쓰기는 30분 · 12시간 나눔대로(형에 없는 나눔 칸은 dict로 온다)
    split = ns({"usage": {**usage(3000, 20, cached=100, wrote=2900)}})
    split.usage.input_tokens_details.cache_write_tokens_details = {
        "ttl_30m_tokens": 2400, "ttl_12h_tokens": 500}  # fmt: skip
    assert llm._oa_usage(split, 2) == {
        "input": 0, "cache_read": 100, "cache_write_5m": 2400, "cache_write_1h": 500,
        "output": 20, "web_searches": 2, "thinking": 0,
    }  # fmt: skip
    assert llm._oa_usage(ns({"usage": None}), 1) == {"web_searches": 1}

    # 막은 곳: 검색 도구가 막은 곳은 열지도 인용하지도 않고, 가져오기만 막은 곳은 검색 결과로만
    never, closed = llm._oa_web_note(research.TOOLS).split("검색 결과로만")
    assert "map.naver.com" in never and "instagram.com" in never and "soomgo.com" not in never
    assert "soomgo.com" in closed and "blog.naver.com" in closed
    assert llm._oa_clean("https://a.kr/p?utm_source=openai") == "https://a.kr/p"
    assert llm._oa_clean("https://a.kr/p?utm_source=openai&x=1") == "https://a.kr/p?x=1"
    assert (
        llm._oa_clean("[a](https://a.kr/p?x=1&utm_source=openai) 끝")
        == "[a](https://a.kr/p?x=1) 끝"
    )
    # 모델 · 강도: Sonnet 자리는 agent 모델, Haiku 자리는 light 모델
    assert llm.openai_model_for("assistant") == ("gpt-6.1-terra", "low")
    assert llm.openai_model_for("research") == ("gpt-6.1-terra", "low")
    assert llm.openai_model_for("nudge") == ("gpt-6-luna", "none")
    assert llm.openai_model_for("memory") == ("gpt-6-luna", "none")


def test_assistant_turn_runs_on_openai_and_sends_tool_results_back(api, openai):
    _, pid = home(api)
    log = openai([
        [*called("call_1", "get_home", {}), completed(usage(9000, 300, cached=6000, wrote=2000, reasoning=100))],
        [*say("노원구 집이에요. 공급 69.4㎡ 기준이에요. 2,000,000원이면 돼요. 제가 저장했어요."),
         completed(usage(9500, 40, cached=9000))],
    ])  # fmt: skip
    ev = ok(ask(api, pid, PHONE_TEXT))
    assert names(ev)[:4] == ["ack", "status", "card", "token"]
    assert ev[2][1]["kind"] == "home_info"
    said = "".join(d["text"] for e, d, _ in ev if e == "token")
    assert "69.4㎡" in said and "2,000,000" not in said and "저장했어요" not in said
    assert ev[-1][1]["mode"] == "llm"
    first, second = log
    assert (first["model"], first["reasoning"], first["store"], first["stream"]) == (
        "gpt-6.1-terra", {"effort": "low"}, False, True)  # fmt: skip
    assert first["instructions"] and first["tool_choice"] == "auto"
    tools = [t["name"] for t in first["tools"]]
    assert tools == sorted(tools) and "get_home" in tools
    assert all(t["type"] == "function" and t["strict"] is False for t in first["tools"])
    assert "include" not in first and "max_tool_calls" not in first  # 비서 턴에는 웹 도구가 없다
    user, facts = first["input"][-2:]
    assert user["role"] == "user" and facts["role"] == "system" and "지금:" in facts["content"]
    assert "010-1234-5678" not in json.dumps(first, ensure_ascii=False)
    call, result = second["input"][-2:]
    assert call == {
        "type": "function_call",
        "call_id": "call_1",
        "name": "get_home",
        "arguments": "{}",
    }
    assert result["type"] == "function_call_output" and result["call_id"] == "call_1"
    assert "region" in result["output"] and pid not in result["output"]
    # 장부: OpenAI 가격표(입력은 캐시 읽기 · 쓰기를 뺀 값)
    got = query("select purpose, model, input_tokens, cache_read_tokens, cache_write_tokens, "
                "output_tokens, cost_micros, price_ver from llm_usage order by created_at")  # fmt: skip
    want = prices.cost(
        "gpt-6.1-terra", input_tokens=1000, cache_read=6000, cache_write_5m=2000, output_tokens=300
    )
    assert dict(got[0]) == {
        "purpose": "assistant", "model": "gpt-6.1-terra", "input_tokens": 1000,
        "cache_read_tokens": 6000, "cache_write_tokens": 2000, "output_tokens": 300,
        "cost_micros": want[0], "price_ver": want[1],
    }  # fmt: skip
    assert [r["purpose"] for r in got] == ["assistant", "assistant"]
    t = turn_row(ev[0][1]["turn_id"])
    assert (t["mode"], t["tool_calls"]) == ("llm", 1)


def test_research_runs_on_openai_web_search_with_the_same_rules(api, script, openai, monkeypatch):
    _, pid = home(api)
    start_turn(api, script, pid, "materials", "실크벽지 질감 인기 제품")  # 비서 턴은 Claude 대본
    rid = rows()[-1]["id"]
    seen: list[str] = []
    monkeypatch.setattr(
        linkimage,
        "_client",
        pages(
            seen,
            {
                "https://www.lxzin.com/robots.txt": text("User-agent: *\nDisallow: /mypage*/"),
                "https://www.shinhanwall.co.kr/robots.txt": text("User-agent: *\nDisallow: /brands/"),
            },
            {LX: html(f'<head><meta property="og:image" content="{LX_IMG}"></head>')},
        ),
    )  # fmt: skip
    final = (
        "요약: 많이 고르는 실크 벽지 두 가지를 찾았어요.\n항목:\n"
        f"- 디아망 회벽/화이트 (PR002-01) | 회벽처럼 요철이 크고 두꺼워요 | 순백보다 살짝 회색이 돌아요 | "
        f"{LX}?utm_source=openai\n"
        f"- 조용한 사색 (15053-1) | 요철이 얕고 매트해요 | - | {SH}\n"
        "- 지어낸 제품 | 좋아요 | - | https://made-up.example/x"
    )
    cites = (
        (f"{LX}?utm_source=openai", "디아망 / 회벽/화이트 | LX 지인"),
        (f"{SH}&utm_source=openai", "KCC신한벽지 - 조용한 사색"),
    )
    log = openai([[
        *say("LX Z:IN 공식 페이지에서 인기 실크 제품부터 볼게요."),
        *search("ws_search1", "LX 실크벽지 인기 제품 010-1234-5678", [MAP, LX, SH]),
        *opened("ws_open1", LX),
        *opened("ws_open2", SOOMGO),  # 가져오기를 막은 곳: 기록 안 함
        *opened("ws_open3", GUIDE, status="failed"),
        ns({"type": "response.web_search_call.completed"}),  # 모르는 이벤트는 넘긴다
        *say(final, cites),
        completed(usage(30_000, 1_500, cached=10_000)),
    ]])  # fmt: skip
    llm.clear_stubs()  # 비서 턴 대본을 끄면 조사는 OpenAI로 간다
    assert run(api, research.run, rid) == "done"

    async def load():
        async with SessionLocal() as s:
            return await s.get(AssistantResearch, rid)

    r = run(api, load)
    trail = [(t.kind, t.text, t.title, t.n, t.ok) for t in research.data_of(r).trail]
    assert trail == [
        ("start", None, None, None, None),
        ("say", "LX Z:IN 공식 페이지에서 인기 실크 제품부터 볼게요.", None, None, None),
        ("search", "LX 실크벽지 인기 제품", None, 2, None),
        ("read", "lxzin.com", None, None, True),
        ("read", "dobae-guide.example.kr", None, None, False),
        ("write", None, None, None, None),
        ("end", "done", None, None, None),
    ]
    raw = json.dumps(r.steps, ensure_ascii=False)
    assert "soomgo" not in raw and "1234-5678" not in raw and "utm_source" not in raw
    lines = research.data_of(r).trail
    assert [(h.title, h.source, h.href) for h in lines[2].hits] == [
        ("lxzin.com", "lxzin.com", LX),  # 검색 결과에는 제목이 없어 도메인으로
        ("shinhanwall.co.kr", "shinhanwall.co.kr", SH),
    ]
    (row,) = [x for x in rows() if x["id"] == rid]
    res = result_of(row)
    assert res["items"] == [
        {"name": "디아망 회벽/화이트 (PR002-01)", "feature": "회벽처럼 요철이 크고 두꺼워요",
         "caution": "순백보다 살짝 회색이 돌아요", "href": LX, "source": "lxzin.com", "image": LX_IMG},
        {"name": "조용한 사색 (15053-1)", "feature": "요철이 얕고 매트해요", "caution": None,
         "href": SH, "source": "shinhanwall.co.kr", "image": None},
    ]  # fmt: skip
    assert res["summary"] == "많이 고르는 실크 벽지 두 가지를 찾았어요."
    assert "map.naver" not in json.dumps(res, ensure_ascii=False)

    (req,) = log
    assert req["model"] == "gpt-6.1-terra" and req["max_output_tokens"] == research.MAX_TOKENS
    assert req["tools"] == [llm.OA_WEB_TOOL] and req["tool_choice"] == "auto"
    assert req["include"] == llm.OA_INCLUDE and req["max_tool_calls"] == 8
    assert req["instructions"].endswith(llm._oa_web_note(research.TOOLS))
    (spent,) = query(
        "select purpose, model, web_searches, cost_micros from llm_usage where purpose = 'research'"
    )
    want = prices.cost(
        "gpt-6.1-terra", input_tokens=20_000, cache_read=10_000, output_tokens=1_500, web_searches=4
    )[0]
    assert dict(spent) == {
        "purpose": "research", "model": "gpt-6.1-terra", "web_searches": 4, "cost_micros": want,
    }  # fmt: skip


def test_json_answers_on_openai_and_their_failures(monkeypatch, openai):
    log = openai([
        answer('{"send": true, "text": "확인해 주세요"}'),
        answer(refusal=True),
        answer('{"send": tr', status="incomplete", reason="max_output_tokens"),
        answer('{"send": "maybe"}'),  # 꼴 틀림
        bad_request(),
        answer(status="failed"),
    ])  # fmt: skip

    async def go():
        got = await llm.claude_json("nudge", Nudge, "지시문", "사실")
        for _ in range(3):
            with pytest.raises(llm.LLMBadOutput):
                await llm.claude_json("nudge", Nudge, "s", "q")
        with pytest.raises(llm.LLMRejected):
            await llm.claude_json("memory", Nudge, "s", "q")
        with pytest.raises(llm.LLMError) as e:
            await llm.claude_json("nudge", Nudge, "s", "q")
        assert not isinstance(e.value, llm.LLMBadOutput)  # 공급자 실패는 다시 해 볼 수 있는 오류
        return got

    assert run_loop(monkeypatch, go) == Nudge(send=True, text="확인해 주세요")
    first = log[0]
    assert (first["model"], first["reasoning"], first["store"]) == (
        "gpt-6-luna",
        {"effort": "none"},
        False,
    )
    fmt = first["text"]["format"]
    assert (fmt["type"], fmt["name"], fmt["strict"]) == ("json_schema", "Nudge", True)
    assert fmt["schema"]["additionalProperties"] is False
    assert set(fmt["schema"]["required"]) == {"send", "text"}
    assert first["instructions"] == "지시문" and first["input"] == [
        {"role": "user", "content": "사실"}
    ]
    assert "stream" not in first and "tools" not in first
    assert [(x["purpose"], x["error"]) for x in usage_rows()] == [
        ("nudge", None),
        ("nudge", "refusal"),
        ("nudge", "max_tokens"),
        ("nudge", "invalid_output"),
        ("memory", "BadRequestError"),
        ("nudge", "response_failed"),
    ]


def test_stream_failures_callbacks_and_cut_answers(monkeypatch, openai):
    get_home = {
        "name": "get_home",
        "description": "집",
        "input_schema": {"type": "object", "properties": {}},
    }
    log = openai([
        bad_request(),  # 요청 거절 → LLMRejected(장부에 토큰 없이)
        [ns({"type": "response.created"}), ns({"type": "response.failed", "response": {"usage": None}})],
        [*say("앞 글")],  # 끝 알림 없이 닫힘
        [*say("글 조각이에요")],  # on_text 오류는 그대로
        [*called("c1", "get_home", {}), completed(usage(100, 10), reason="max_output_tokens")],
        [*say("못 도와드려요"), completed(usage(100, 10), reason="content_filter")],
    ])  # fmt: skip

    async def boom(_t: str) -> None:
        raise ValueError("화면 끊김")

    async def go():
        msgs = [{"role": "user", "content": "q"}]
        with pytest.raises(llm.LLMRejected):
            await llm.claude_stream("s", msgs)
        with pytest.raises(llm.LLMError):
            await llm.claude_stream("s", msgs)
        with pytest.raises(llm.LLMError):
            await llm.claude_stream("s", msgs)
        with pytest.raises(ValueError):
            await llm.claude_stream("s", msgs, on_text=boom)
        cut = await llm.claude_stream("s", msgs, tools=[get_home], tool_choice={"type": "none"})
        filtered = await llm.claude_stream("s", msgs)
        return cut, filtered

    cut, filtered = run_loop(monkeypatch, go)
    assert cut.stop == "max_tokens" and cut.tool_calls == []  # 잘린 인자로 도구를 돌리지 않는다
    assert cut.content[0]["type"] == "tool_use" and log[4]["tool_choice"] == "none"
    assert filtered.stop == "refusal"
    assert [x["error"] for x in usage_rows()] == [
        "BadRequestError", "response_failed", "no_final", "callback", "max_tokens", "refusal",
    ]  # fmt: skip
    # 끊긴 호출은 보수적 추정치(보낸 글자 수)로 남긴다
    assert all(x["input_tokens"] > 0 for x in usage_rows()[1:4])


# ── 진짜 SDK(AsyncOpenAI)를 가짜 HTTP 전송으로: SSE 이벤트 해석 · 요청 꼴 (네트워크 없음) ──

EVENTS = [
    {"type": "response.created", "sequence_number": 0,
     "response": {"id": "resp_1", "object": "response", "status": "in_progress", "model": "gpt-6.1-terra",
                  "output": []}},
    {"type": "response.output_item.added", "sequence_number": 1, "output_index": 0,
     "item": {"type": "web_search_call", "id": "ws_1", "status": "in_progress",
              "action": {"type": "search", "query": ""}}},
    {"type": "response.web_search_call.searching", "sequence_number": 2, "output_index": 0, "item_id": "ws_1"},
    {"type": "response.output_item.done", "sequence_number": 3, "output_index": 0,
     "item": {"type": "web_search_call", "id": "ws_1", "status": "completed",
              "action": {"type": "search", "query": "LX 실크벽지", "sources": [{"type": "url", "url": LX}]}}},
    {"type": "response.output_item.added", "sequence_number": 4, "output_index": 1,
     "item": {"type": "message", "id": "msg_1", "role": "assistant", "status": "in_progress", "content": []}},
    {"type": "response.output_text.delta", "sequence_number": 5, "output_index": 1, "item_id": "msg_1",
     "content_index": 0, "delta": "요약: 찾았어요.", "logprobs": []},
    {"type": "response.output_item.done", "sequence_number": 6, "output_index": 1,
     "item": {"type": "message", "id": "msg_1", "role": "assistant", "status": "completed",
              "content": [{"type": "output_text", "text": "요약: 찾았어요.", "logprobs": [],
                           "annotations": [{"type": "url_citation", "url": f"{LX}?utm_source=openai",
                                            "title": "디아망 | LX 지인", "start_index": 0, "end_index": 3}]}]}},
    {"type": "response.completed", "sequence_number": 7,
     "response": {"id": "resp_1", "object": "response", "status": "completed",
                  "model": "gpt-6.1-terra-2026-10-01", "output": [],
                  "usage": usage(5000, 80, reasoning=20)}},
]  # fmt: skip
JSON_ANSWER = {
    "id": "resp_2", "object": "response", "created_at": 0, "status": "completed", "model": "gpt-6-luna",
    "output": [{"type": "message", "id": "msg_2", "role": "assistant", "status": "completed",
                "content": [{"type": "output_text", "text": '{"send": false, "text": ""}', "annotations": []}]}],
    "usage": usage(700, 12),
}  # fmt: skip


def test_real_sdk_reads_sse_events_and_json_answers(monkeypatch):
    from openai import AsyncOpenAI

    llm.clear_stubs()
    monkeypatch.setattr(settings, "llm_live", True)
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", SecretStr("test-not-real"))
    sent: list[tuple[str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        sent.append((request.url.path, body))
        if body.get("stream"):
            sse = "".join(
                f"event: {e['type']}\ndata: {json.dumps(e, ensure_ascii=False)}\n\n" for e in EVENTS
            )
            return httpx.Response(
                200, headers={"content-type": "text/event-stream"}, content=sse.encode()
            )
        return httpx.Response(200, json=JSON_ANSWER)

    async def go():
        llm._oa_clients[asyncio.get_running_loop()] = AsyncOpenAI(
            api_key="test-not-real",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        ended: list[dict] = []
        texts: list[str] = []
        starts: list[tuple[str, str | None]] = []

        async def on_text(t: str) -> None:
            texts.append(t)

        async def on_block(kind: str, name: str | None) -> None:
            starts.append((kind, name))

        async def on_end(b: dict) -> None:
            ended.append(json.loads(json.dumps(b)))

        reply = await llm.claude_stream(
            "조사 지시문", [{"role": "user", "content": "q"}], tools=research.TOOLS, purpose="research",
            on_text=on_text, on_block=on_block, on_block_end=on_end,
        )  # fmt: skip
        got = await llm.claude_json("nudge", Nudge, "s", "q")
        return reply, got, ended, texts, starts

    reply, got, ended, texts, starts = run_loop(monkeypatch, go)
    assert texts == ["요약: 찾았어요."]
    assert starts == [
        ("server_tool_use", "web_search"),
        ("web_search_tool_result", None),
        ("text", None),
    ]
    assert [b["type"] for b in ended] == ["server_tool_use", "web_search_tool_result", "text"]
    assert ended[0]["input"] == {"query": "LX 실크벽지"}
    assert ended[1]["content"] == [{"type": "web_search_result", "url": LX, "title": ""}]
    # 끝나면 인용 제목으로 결과 제목을 채운다(utm_source를 뗀 주소로 맞춘다)
    assert reply.content[1]["content"] == [
        {"type": "web_search_result", "url": LX, "title": "디아망 | LX 지인"}
    ]
    assert (reply.stop, reply.model, reply.usage["web_searches"]) == (
        "end_turn",
        "gpt-6.1-terra-2026-10-01",
        1,
    )
    assert reply.text == "요약: 찾았어요."
    assert got == Nudge(send=False, text="")
    (path1, stream_req), (path2, json_req) = sent
    assert path1 == path2 == "/v1/responses"
    assert stream_req["stream"] is True and stream_req["store"] is False
    assert stream_req["tools"] == [llm.OA_WEB_TOOL] and stream_req["include"] == llm.OA_INCLUDE
    assert stream_req["instructions"].startswith("조사 지시문")
    assert json_req["text"]["format"]["name"] == "Nudge" and "stream" not in json_req
    assert [(x["purpose"], x["model"], x["error"]) for x in usage_rows()] == [
        ("research", "gpt-6.1-terra-2026-10-01", None),
        ("nudge", "gpt-6-luna", None),
    ]
