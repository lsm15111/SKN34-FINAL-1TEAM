"""LLM 설정: 역할별 모델 · 생각 깊이. 실제 호출은 하지 않는다."""

import asyncio

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
