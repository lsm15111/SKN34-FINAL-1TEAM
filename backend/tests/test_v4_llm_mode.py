"""v4 기반: LLM 모드 판단이 고른 공급자 키 · LLM_LIVE · 비용 상한을 따르는지, v3 턴의 LLM 호출이
그 사용자로 장부(llm_usage)에 남는지. 유료 호출 0회(대본 · 스텁)."""

import pytest
from pydantic import SecretStr

from app.agent import llm
from app.agent.v3.llm_mode import LlmSection
from app.config import settings
from tests.conftest import query
from tests.helpers import signup, use
from tests.test_v3_ai_api import ask, done
from tests.v3_kb import repo_index


@pytest.fixture(autouse=True)
def repo_knowledge(monkeypatch):
    """시험 DB에는 지식 자료가 없어 운영과 같은 CSV 색인을 넘긴다(test_v3_ai_api와 같다)."""
    from app.knowledge import service as knowledge

    async def index(_s):
        return repo_index()

    monkeypatch.setattr(knowledge, "index", index)


def test_v3_mode_follows_provider_key(monkeypatch):
    from app.chat import service

    monkeypatch.setattr(settings, "llm_live", True)
    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    monkeypatch.setattr(settings, "anthropic_api_key", SecretStr("k"))
    monkeypatch.setattr(settings, "openai_api_key", SecretStr(""))
    assert service.mode() == "llm"  # OpenAI 키 없이 Claude 키로 LLM 모드
    monkeypatch.setattr(settings, "anthropic_api_key", SecretStr(""))
    monkeypatch.setattr(settings, "openai_api_key", SecretStr("k"))
    assert service.mode() == "free"  # Claude 공급자인데 Claude 키가 없으면 무료
    monkeypatch.setattr(settings, "llm_provider", "openai")
    assert service.mode() == "llm"  # 되돌리기(OpenAI)면 OpenAI 키로
    monkeypatch.setattr(settings, "llm_live", False)
    assert service.mode() == "free"


def test_v2_health_live_needs_provider_key(api, monkeypatch):
    use(api, signup(api, "health@mitjip.test"))
    assert api.get("/v2/ask/health").json() == {"ok": True, "live": False}
    monkeypatch.setattr(settings, "llm_live", True)
    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    monkeypatch.setattr(settings, "anthropic_api_key", SecretStr(""))
    assert api.get("/v2/ask/health").json()["live"] is False  # 키 없음
    monkeypatch.setattr(settings, "anthropic_api_key", SecretStr("k"))
    assert api.get("/v2/ask/health").json()["live"] is True


def test_v3_turn_goes_free_when_over_cost_cap(api, monkeypatch):
    from app.chat import service

    monkeypatch.setattr(service, "mode", lambda: "llm")
    monkeypatch.setattr(llm, "_stubs", {})
    llm.set_stub("trade", LlmSection(sentences=[]))
    use(api, signup(api, "cap@mitjip.test"))
    monkeypatch.setattr(settings, "llm_cap_service_day_usd", 0)  # 0이면 유료 호출을 모두 막는다
    assert done(ask(api))["mode"] == "free"
    monkeypatch.setattr(settings, "llm_cap_service_day_usd", 5.0)
    assert done(ask(api))["mode"] == "llm"


def test_v3_turn_llm_calls_are_recorded_for_the_user(api, monkeypatch):
    from app.chat import service

    monkeypatch.setattr(service, "mode", lambda: "llm")
    llm.clear_stubs()
    # 꼴이 틀린 답: 호출마다 실패로 남고 그 몫은 무료 묶음으로 돌아간다
    llm.set_claude_script([{"text": "{}"}] * 12)
    try:
        use(api, signup(api, "ctx@mitjip.test"))
        assert done(ask(api))["mode"] == "llm"
    finally:
        llm.clear_stubs()
    (uid,) = [r["id"] for r in query("select id from users where email = 'ctx@mitjip.test'")]
    got = query("select user_id, ok, error from llm_usage")
    assert got and all(r["user_id"] == uid for r in got)
    assert all((r["ok"], r["error"]) == (False, "invalid_output") for r in got)
