"""v4 Claude 호출(agent/llm.py): 대본(set_claude_script)으로 structured · chat_tools · claude_stream ·
claude_json의 요청 꼴과 장부(llm_usage) 기록을 본다. 유료 호출 0회(LLM_LIVE=false, 키 비움)."""

import asyncio
import importlib.util
import re
import uuid
from typing import Literal, get_args

import pytest
from pydantic import BaseModel, SecretStr
from redis.asyncio import Redis

from app import queue
from app.agent import llm
from app.config import settings
from app.usage import models as usage_models
from app.usage import prices
from tests.conftest import BACKEND, REDIS_URL, query


class Plan(BaseModel):
    reply: str
    kind: Literal["a", "b"] = "a"
    tags: list[str] = []


class Nudge(BaseModel):
    send: bool
    text: str


@pytest.fixture
def script():
    llm.clear_stubs()
    yield llm.set_claude_script
    llm.clear_stubs()


def run(monkeypatch, make):
    """이 이벤트 루프에서 만든 Redis로 바꿔 돌린다(다른 루프의 연결을 쓰지 않게)."""

    async def go():
        r = Redis.from_url(REDIS_URL)
        monkeypatch.setattr(queue, "redis", r)
        try:
            return await make()
        finally:
            await r.aclose()

    return asyncio.run(go())


def rows():
    return query("select * from llm_usage order by created_at, id")


def _user(email: str) -> uuid.UUID:
    uid = uuid.uuid4()
    query(
        "insert into users (id, email, password_hash, name, role)"
        " values ($1, $2, 'x', '시험', 'customer')",
        uid,
        email,
    )
    return uid


def test_purposes_match_usage_table_and_migration():
    spec = importlib.util.spec_from_file_location(
        "m0039", BACKEND / "migrations" / "versions" / "0039_v4_llm_usage.py"
    )
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    assert set(get_args(llm.Purpose)) == set(usage_models.PURPOSES)
    assert set(re.findall(r"'(\w+)'", mig.PURPOSES)) == set(usage_models.PURPOSES)
    assert set(get_args(llm.Role)) <= set(usage_models.PURPOSES)


def test_claude_models_by_purpose(monkeypatch):
    assert llm.claude_model_for("assistant") == ("claude-sonnet-5-5", "medium")
    assert llm.claude_model_for("floorplan")[0] == "claude-sonnet-5-5"
    assert llm.claude_model_for("v2_chat")[0] == "claude-sonnet-5-5"
    assert llm.claude_model_for("orchestrator")[0] == "claude-sonnet-5-5"
    assert llm.claude_model_for("composer") == ("claude-haiku-5-5", "low")  # 기존 가벼운 역할
    for p in ("nudge", "memory", "trade", "planner", "general", "check"):
        assert llm.claude_model_for(p)[0] == "claude-haiku-5-5"
    assert llm.claude_model_for("judge")[0] == "claude-opus-5-5"
    monkeypatch.setattr(settings, "llm_claude_light_roles", "trade")
    assert llm.claude_model_for("composer")[0] == "claude-sonnet-5-5"


def test_structured_uses_claude_json_output_and_records(monkeypatch, script):
    log = script(
        [
            {
                "json": {"reply": "처음이시군요", "kind": "b", "tags": []},
                "usage": {"input": 1200, "output": 80, "cache_read": 3000},
            }
        ]
    )
    hook: list[dict] = []
    monkeypatch.setattr(llm, "USAGE_HOOK", hook.append)
    msgs = [("system", "지시문"), ("user", "안녕")]
    out = run(monkeypatch, lambda: llm.structured("composer", Plan, msgs))
    assert out == Plan(reply="처음이시군요", kind="b")
    (req,) = log
    assert req["model"] == "claude-haiku-5-5"
    assert req["output_config"]["effort"] == "low"
    fmt = req["output_config"]["format"]
    assert fmt["type"] == "json_schema" and fmt["schema"]["additionalProperties"] is False
    assert req["system"] == [
        {"type": "text", "text": "지시문", "cache_control": {"type": "ephemeral"}}
    ]
    assert req["messages"] == [{"role": "user", "content": "안녕"}]
    # 강제 도구 · 표본 값 · 생각 끄기를 보내지 않는다
    assert not {"tools", "tool_choice", "temperature", "thinking"} & req.keys()
    (row,) = rows()
    assert (row["purpose"], row["model"], row["ok"], row["error"]) == (
        "composer",
        "claude-haiku-5-5",
        True,
        None,
    )
    assert (row["input_tokens"], row["cache_read_tokens"], row["output_tokens"]) == (1200, 3000, 80)
    # 1200 × $0.10 + 3000 × $0.01 + 80 × $0.50 (백만 토큰당) = 120 + 30 + 40 마이크로달러
    assert (row["cost_micros"], row["price_ver"], row["user_id"]) == (190, prices.PRICE_VER, None)
    assert hook == [
        {
            "role": "composer",
            "model": "claude-haiku-5-5",
            "input": 4200,
            "cached": 3000,
            "output": 80,
            "reasoning": 0,
            "cost_micros": 190,
        }
    ]


def test_structured_main_role_uses_sonnet(monkeypatch, script):
    log = script([{"json": {"reply": "네"}}])
    run(monkeypatch, lambda: llm.structured("orchestrator", Plan, [("system", "s"), ("user", "u")]))
    assert (log[0]["model"], log[0]["output_config"]["effort"]) == ("claude-sonnet-5-5", "medium")


@pytest.mark.parametrize(
    ("step", "error"),
    [
        ({"text": "JSON 아님"}, "invalid_output"),
        ({"text": "", "stop": "refusal"}, "refusal"),
        ({"json": {"reply": "끊"}, "stop": "max_tokens"}, "max_tokens"),
        (TimeoutError("느림"), "TimeoutError"),
    ],
)
def test_structured_failures_are_llm_errors_and_recorded(monkeypatch, script, step, error):
    script([step])
    with pytest.raises(llm.LLMError):
        run(monkeypatch, lambda: llm.structured("general", Plan, [("system", "s"), ("user", "u")]))
    (row,) = rows()
    assert (row["purpose"], row["ok"], row["error"]) == ("general", False, error)


def test_legacy_stub_without_script_writes_nothing():
    llm.clear_stubs()
    llm.set_stub("composer", Plan(reply="스텁"))
    try:
        out = asyncio.run(llm.structured("composer", Plan, [("user", "u")]))
        chat = asyncio.run(llm.chat_tools("s", [{"role": "user", "content": "q"}], []))
    finally:
        llm.clear_stubs()
    assert out.reply == "스텁" and chat["text"] == llm.CHAT_STUB_TEXT
    assert rows() == []


def test_from_v2_messages():
    convo, used = llm._from_v2(
        [
            {"role": "assistant", "content": "지난 답(앞이 잘림)"},
            {"role": "user", "content": [{"type": "text", "text": "벽 사진"}, {"type": "image", "data": "QUJD"}]},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "name": "show_step", "arguments": {"step": "quote"}}]},
            {"role": "tool", "tool_call_id": "c1", "content": '{"ok": true}'},
            {"role": "assistant", "content": ""},
            {"role": "user", "content": "더 알려 줘"},
        ]
    )  # fmt: skip
    assert convo == [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "벽 사진"},
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "QUJD"}},
            ],
        },
        {"role": "assistant", "content": [{"type": "tool_use", "id": "c1", "name": "show_step", "input": {"step": "quote"}}]},
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "c1", "content": '{"ok": true}'},
                {"type": "text", "text": "더 알려 줘"},
            ],
        },
    ]  # fmt: skip
    assert used == {"show_step"}


def test_chat_tools_converts_v2_tools_and_tool_loop(monkeypatch, script):
    from app.v2.ask_tools import tools_for

    log = script(
        [
            {
                "text": "계산해 볼게요.",
                "tool_calls": [{"id": "toolu_1", "name": "price_reference", "input": {}}],
                "usage": {"input": 900, "output": 40},
            },
            {
                "text": "도배는 표준견적서로 보면 돼요.",
                "usage": {"input": 300, "cache_read": 900, "output": 60},
            },
        ]
    )
    tools = tools_for("chat")
    msgs: list[dict] = [{"role": "user", "content": "도배 얼마예요?"}]

    async def go():
        r1 = await llm.chat_tools("지시문", msgs, tools)
        msgs.append({"role": "assistant", "content": r1["text"], "tool_calls": r1["tool_calls"]})
        msgs.append({"role": "tool", "tool_call_id": "toolu_1", "content": '{"합계": 1}'})
        r2 = await llm.chat_tools("지시문", msgs, [])  # 마지막 라운드: 도구 없이
        return r1, r2

    r1, r2 = run(monkeypatch, go)
    assert r1["stop"] == "tool_calls"
    assert r1["tool_calls"] == [{"id": "toolu_1", "name": "price_reference", "arguments": {}}]
    # 300 × $2 + 900 × $0.10 + 60 × $10 = 600 + 90 + 600 마이크로달러
    assert r2 == {
        "text": "도배는 표준견적서로 보면 돼요.",
        "tool_calls": [],
        "stop": "stop",
        "usage": {"input": 1200, "cached": 900, "output": 60, "cost_micros": 1290},
    }
    first, second = log
    assert first["model"] == "claude-sonnet-5-5" and first["tool_choice"] == {"type": "auto"}
    names = [t["name"] for t in first["tools"]]
    assert names == sorted(names) and set(names) == {t["name"] for t in tools}
    assert all(t["strict"] for t in first["tools"])
    assert all(t["input_schema"]["additionalProperties"] is False for t in first["tools"])
    assert all("parameters" not in t for t in first["tools"])
    assert first["tools"][-1]["cache_control"] == {"type": "ephemeral"}
    assert first["cache_control"] == {"type": "ephemeral"}
    assert first["messages"] == [
        {"role": "user", "content": [{"type": "text", "text": "도배 얼마예요?"}]}
    ]
    assert second["messages"][1:] == [
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "계산해 볼게요."},
                {"type": "tool_use", "id": "toolu_1", "name": "price_reference", "input": {}},
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "toolu_1", "content": '{"합계": 1}'}
            ],
        },
    ]
    # 도구 기록이 있으니 이름만 둔 도구를 두고 부르지 못하게 막는다
    assert second["tool_choice"] == {"type": "none"}
    assert [t["name"] for t in second["tools"]] == ["price_reference"]
    assert [(r["purpose"], r["cost_micros"]) for r in rows()] == [
        ("v2_chat", 2200),
        ("v2_chat", 1290),
    ]


def test_claude_stream_streams_text_keeps_thinking_and_records_ctx(monkeypatch, script):
    uid, turn = _user("stream@mitjip.test"), uuid.uuid4()
    log = script(
        [
            {
                "thinking": True,
                "text": "벽지는 실크와 합지가 있어요. 어느 쪽이 좋을까요?",
                "tool_calls": [{"id": "toolu_9", "name": "get_home", "input": {}}],
                "usage": {"input": 2000, "cache_write": 1500, "output": 120},
            },
            {"json": {"send": True, "text": "기억"}},
        ]
    )
    got: list[str] = []

    async def on_text(t: str) -> None:
        got.append(t)

    tools = [
        {"type": "web_search_20260209", "name": "web_search", "max_uses": 3},
        {"name": "get_home", "description": "집 정보", "input_schema": {"type": "object", "properties": {}}},
    ]  # fmt: skip

    async def go():
        with llm.call_ctx(user_id=uid, turn_id=turn, purpose="assistant") as ctx:
            reply = await llm.claude_stream(
                ["판 고정 지시문"],
                [{"role": "user", "content": "벽지 뭐가 좋아요?"}],
                tools=tools,
                on_text=on_text,
            )
            await llm.claude_json("memory", Nudge, "기억 지시문", "한 줄")  # 인자 목적이 이긴다
            return reply, ctx.spent_micros

    reply, spent = run(monkeypatch, go)
    assert "".join(got) == reply.text and len(got) > 1
    assert reply.stop == "tool_use"
    assert reply.tool_calls == [{"id": "toolu_9", "name": "get_home", "input": {}}]
    assert reply.content[0] == {"type": "thinking", "thinking": "", "signature": "script-signature"}
    assert reply.content[-1] == {
        "type": "tool_use",
        "id": "toolu_9",
        "name": "get_home",
        "input": {},
    }
    req = log[0]
    assert req["model"] == "claude-sonnet-5-5" and req["output_config"] == {"effort": "medium"}
    assert req["tool_choice"] == {"type": "auto"} and req["cache_control"] == {"type": "ephemeral"}
    assert [t["name"] for t in req["tools"]] == ["get_home", "web_search"]
    assert req["tools"][0]["strict"] is True and "strict" not in req["tools"][1]
    assert req["tools"][-1]["cache_control"] == {"type": "ephemeral"}
    assert req["system"] == [
        {"type": "text", "text": "판 고정 지시문", "cache_control": {"type": "ephemeral"}}
    ]
    stream_row, memory_row = rows()
    assert (stream_row["user_id"], stream_row["turn_id"], stream_row["purpose"]) == (
        uid,
        turn,
        "assistant",
    )
    # 2000 × $2 + 1500 × $2.50(5분 캐시 쓰기) + 120 × $10 = 4000 + 3750 + 1200 마이크로달러
    assert stream_row["cost_micros"] == reply.cost_micros == 8950
    assert stream_row["cache_write_tokens"] == 1500
    assert (memory_row["purpose"], memory_row["user_id"]) == ("memory", uid)
    assert spent == 8950 + memory_row["cost_micros"]


@pytest.mark.parametrize("stop", ["refusal", "max_tokens"])
def test_claude_stream_drops_tool_calls_on_refusal_or_cut(monkeypatch, script, stop):
    script([{"text": "그건", "tool_calls": [{"name": "get_home", "input": {}}], "stop": stop}])
    reply = run(
        monkeypatch,
        lambda: llm.claude_stream("s", [{"role": "user", "content": "q"}], purpose="assistant"),
    )
    assert reply.stop == stop and reply.tool_calls == []
    (row,) = rows()
    assert (row["ok"], row["error"]) == (False, stop)


def test_claude_stream_failure_records_partial_usage(monkeypatch, script):
    script(
        [
            {
                "text": "앞부분만",
                "fail": ConnectionResetError("끊김"),
                "usage": {"input": 700, "output": 5},
            }
        ]
    )
    got: list[str] = []

    async def on_text(t: str) -> None:
        got.append(t)

    with pytest.raises(llm.LLMError):
        run(
            monkeypatch,
            lambda: llm.claude_stream(
                "s", [{"role": "user", "content": "q"}], on_text=on_text, purpose="floorplan"
            ),
        )
    assert "".join(got) == "앞부분만"
    (row,) = rows()
    assert (row["purpose"], row["ok"], row["error"], row["input_tokens"]) == (
        "floorplan",
        False,
        "ConnectionResetError",
        700,
    )


def test_claude_stream_callback_error_is_raised_as_is(monkeypatch, script):
    script([{"text": "가나다라마바사아자차"}])

    async def on_text(t: str) -> None:
        raise KeyError("화면 연결 끊김")

    with pytest.raises(KeyError):
        run(
            monkeypatch,
            lambda: llm.claude_stream("s", [{"role": "user", "content": "q"}], on_text=on_text),
        )
    (row,) = rows()
    assert (row["purpose"], row["error"]) == ("assistant", "callback")


def test_claude_json_light_and_judge_models(monkeypatch, script):
    log = script(
        [{"json": {"send": True, "text": "견적이 왔어요"}}, {"json": {"send": False, "text": ""}}]
    )

    async def go():
        a = await llm.claude_json("nudge", Nudge, "판단 지시문", "사실: 견적 도착")
        b = await llm.claude_json(
            "judge", Nudge, None, [{"role": "user", "content": "판정"}], max_tokens=500
        )
        return a, b

    a, b = run(monkeypatch, go)
    assert a == Nudge(send=True, text="견적이 왔어요") and b.send is False
    assert [r["model"] for r in log] == ["claude-haiku-5-5", "claude-opus-5-5"]
    assert log[0]["messages"] == [{"role": "user", "content": "사실: 견적 도착"}]
    assert "system" not in log[1] and log[1]["max_tokens"] == 500
    assert [r["purpose"] for r in rows()] == ["nudge", "judge"]


def test_claude_functions_are_off_without_script_or_key(monkeypatch):
    llm.clear_stubs()
    with pytest.raises(llm.LLMOff):
        asyncio.run(llm.claude_stream("s", [{"role": "user", "content": "q"}]))
    with pytest.raises(llm.LLMOff):
        asyncio.run(llm.claude_json("memory", Nudge, "s", "q"))
    monkeypatch.setattr(settings, "llm_live", True)
    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    monkeypatch.setattr(settings, "anthropic_api_key", SecretStr(""))
    with pytest.raises(llm.LLMOff):  # 키 없음
        asyncio.run(llm.claude_json("memory", Nudge, "s", "q"))
    monkeypatch.setattr(settings, "anthropic_api_key", SecretStr("not-used"))
    monkeypatch.setattr(settings, "llm_provider", "openai")
    with pytest.raises(llm.LLMOff):  # 되돌리기(OpenAI) 중에는 Claude 함수도 끈다
        asyncio.run(llm.claude_stream("s", [{"role": "user", "content": "q"}]))
    assert rows() == []


def test_available_follows_live_and_provider_key(monkeypatch):
    monkeypatch.setattr(settings, "llm_live", True)
    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    monkeypatch.setattr(settings, "anthropic_api_key", SecretStr("k"))
    monkeypatch.setattr(settings, "openai_api_key", SecretStr(""))
    assert llm.available()
    monkeypatch.setattr(settings, "llm_provider", "openai")
    assert not llm.available()
    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    monkeypatch.setattr(settings, "llm_live", False)
    assert not llm.available()
