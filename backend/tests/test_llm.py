"""LLM 설정: 역할별 모델 · 생각 깊이, Batch 호출. 실제 호출은 하지 않는다."""

import asyncio
from types import SimpleNamespace as NS

import pytest
from pydantic import BaseModel

from app.agent import llm
from app.config import settings


class Out(BaseModel):
    x: int


def test_role_settings_fall_back_to_the_default_model(monkeypatch):
    for k, v in {
        "llm_model": "base-model",
        "llm_effort": "medium",
        "llm_model_router": "",
        "llm_effort_router": "low",
        "llm_model_plan": "plan-model",
        "llm_effort_plan": "",
    }.items():
        monkeypatch.setattr(settings, k, v)
    assert llm.pick() == ("base-model", "medium")
    assert llm.pick("router") == ("base-model", "low")
    assert llm.pick("plan") == ("plan-model", "medium")
    with pytest.raises(ValueError):
        llm.pick("nope")


def test_stub_never_calls_the_api():
    with pytest.raises(llm.LlmError) as e:
        asyncio.run(llm.parse("system", "user", Out, role="expert"))
    assert e.value.reason == "stub"


def test_judge_role_has_its_own_settings(monkeypatch):
    monkeypatch.setattr(settings, "llm_model", "base-model")
    monkeypatch.setattr(settings, "llm_model_judge", "")
    monkeypatch.setattr(settings, "llm_effort_judge", "low")
    assert llm.pick("judge") == ("base-model", "low")
    monkeypatch.setattr(settings, "llm_model_judge", "judge-model")
    assert llm.pick("judge")[0] == "judge-model"


def _message(text: str, stop: str = "end_turn"):
    usage = NS(
        input_tokens=10,
        output_tokens=5,
        cache_read_input_tokens=None,
        cache_creation_input_tokens=3,
    )
    content = [NS(type="thinking"), NS(type="text", text=text)]
    return NS(model="m", stop_reason=stop, content=content, usage=usage)


class FakeBatches:
    """가짜 Batch API: 낸 요청을 기억하고, 두 번째 조회에서 끝났다고 한다."""

    def __init__(self, rows: list) -> None:
        self.rows, self.requests, self.polls = rows, None, 0

    async def create(self, requests):
        self.requests = requests
        return NS(id="batch_1", processing_status="in_progress")

    async def retrieve(self, batch_id):
        assert batch_id == "batch_1"
        self.polls += 1
        return NS(processing_status="ended" if self.polls >= 2 else "in_progress")

    async def results(self, batch_id):
        async def rows():
            for r in self.rows:
                yield r

        return rows()


def test_parse_batch_returns_results_by_custom_id(monkeypatch):
    rows = [  # 요청 순서와 다르게 돌아온다
        NS(custom_id="c", result=NS(type="errored", error=NS(error=NS(type="api_error")))),
        NS(custom_id="a", result=NS(type="succeeded", message=_message('{"x": 1}'))),
        NS(custom_id="b", result=NS(type="succeeded", message=_message('{"x": "아님"}'))),
        NS(custom_id="e", result=NS(type="succeeded", message=_message("", stop="refusal"))),
        NS(custom_id="f", result=NS(type="expired")),
    ]
    batches = FakeBatches(rows)
    monkeypatch.setattr(llm, "_client", NS(messages=NS(batches=batches)))
    monkeypatch.setattr(settings, "llm_model_judge", "judge-model")
    monkeypatch.setattr(settings, "llm_effort_judge", "low")
    items = [(cid, "시스템", f"글 {cid}") for cid in ("a", "b", "c", "d", "e", "f")]
    got = asyncio.run(llm.parse_batch(items, Out, role="judge", live=True, poll_s=0))

    assert list(got) == ["a", "b", "c", "d", "e", "f"] and batches.polls == 2
    out, usage = got["a"]
    assert out == Out(x=1)
    assert (usage.model, usage.input_tokens, usage.cache_read_tokens) == ("m", 10, 0)
    assert (usage.cache_write_tokens, usage.role, usage.ms) == (3, "judge", 0)
    reasons = {k: v.reason for k, v in got.items() if isinstance(v, llm.LlmError)}
    assert reasons == {
        "b": "schema",
        "c": "batch_api_error",
        "d": "batch_missing",
        "e": "refusal",
        "f": "batch_expired",
    }
    req = batches.requests[0]
    assert req["custom_id"] == "a"
    p = req["params"]
    assert p["model"] == "judge-model" and p["messages"] == [{"role": "user", "content": "글 a"}]
    assert p["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert p["output_config"]["effort"] == "low"
    assert p["output_config"]["format"]["type"] == "json_schema"
    assert "x" in p["output_config"]["format"]["schema"]["properties"]


def test_batch_needs_live_and_good_ids(monkeypatch):
    monkeypatch.setattr(llm, "_client", NS(messages=NS(batches=FakeBatches([]))))
    with pytest.raises(llm.LlmError) as e:
        asyncio.run(llm.parse_batch([("a", "s", "u")], Out))  # LLM_LIVE=false
    assert e.value.reason == "stub"
    for bad in ([("a", "s", "u"), ("a", "s", "u")], [("한글", "s", "u")], []):
        with pytest.raises(ValueError):
            asyncio.run(llm.submit_batch(bad, Out, live=True))


def test_wait_batch_gives_up_after_max_wait(monkeypatch):
    stuck = NS(retrieve=lambda batch_id: _done(NS(processing_status="in_progress")))
    monkeypatch.setattr(llm, "_client", NS(messages=NS(batches=stuck)))
    with pytest.raises(llm.LlmError) as e:
        asyncio.run(llm.wait_batch("batch_1", poll_s=0, max_wait_s=0))
    assert e.value.reason == "batch_timeout"


async def _done(value):
    return value
