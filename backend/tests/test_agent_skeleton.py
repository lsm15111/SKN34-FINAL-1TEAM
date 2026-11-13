"""에이전트 뼈대: 관문 분기, 출력 검사, 공정 고르기, LLM 스텁 (LLM_LIVE=false, 유료 호출 0회)."""

import asyncio
import uuid

import pytest
from pydantic import BaseModel

from app.agent import llm
from app.agent.graph import AGENT_NODES, NODES, ROUTE, build_graph, default_nodes
from app.agent.schemas import FAILED_TEXT, AgentAnswer, Intent, Section, Turn, TurnContext
from app.agent.trades import match_trades

CTX = TurnContext(user_id=uuid.uuid4(), chat_id=uuid.uuid4())


def run(nodes, label=None, message=""):
    state = {"ctx": CTX, "message": message}
    if label:
        state["intent"] = Intent(label=label, confidence=0.9, source="model")
    return asyncio.run(build_graph(nodes).ainvoke(state))


@pytest.mark.parametrize(("label", "node"), ROUTE.items())
def test_gate_sends_each_intent_to_one_agent(label, node):
    visited: list[str] = []

    def make(name):
        async def fake(state):
            visited.append(name)
            answer = AgentAnswer(sections=[Section(sentences=[name])])
            return {"answer": answer} if name in AGENT_NODES else {}

        return fake

    out = run({name: make(name) for name in NODES}, label)
    assert visited == ["gate", node, "output_check"]
    assert out["answer"].sections[0].sentences == [node]


def test_default_nodes_reply_without_llm():
    ask = run(default_nodes())["answer"]  # 의도 없음(None) → 되묻기
    assert ask.cards[0].kind == "choices"
    # 선택지를 누르면 의도가 같이 와서 다시 분류하지 않는다. 범위 밖만 빼고 모두
    assert [c.intent for c in ask.cards[0].options] == list(ROUTE)[:-1]
    out = run(default_nodes(), "out_of_scope")["answer"]
    assert (
        out.sections[0].sentences == ["지금은 아파트 도배와 목공만 도와드려요."] and not out.cards
    )
    # 아직 답을 만들지 않는 에이전트는 실패 문구로 알린다
    out = run(default_nodes(), "orchestrator")["answer"]
    assert out.sections[0].sentences == [FAILED_TEXT] and out.failed


@pytest.mark.parametrize("sentences", [[], ["", "  "]])
def test_output_check_replaces_empty_section(sentences):
    async def empty(state):
        return {"answer": AgentAnswer(sections=[Section(title="[도배]", sentences=sentences)])}

    out = run({**default_nodes(), "trade": empty}, "trade")["answer"]
    assert out.sections[0].sentences == [FAILED_TEXT] and out.failed


def test_failed_answer_clears_waiting():
    async def ask_then_fail(state):
        return {"answer": AgentAnswer(failed=True), "waiting": "trade"}

    async def ask(state):
        return {
            "answer": AgentAnswer(sections=[Section(sentences=["몇 개예요?"])]),
            "waiting": "trade",
        }

    assert run({**default_nodes(), "trade": ask_then_fail}, "trade")["waiting"] is None
    assert run({**default_nodes(), "trade": ask}, "trade")["waiting"] == "trade"


def test_build_graph_needs_every_node():
    nodes = default_nodes()
    del nodes["schedule"]
    with pytest.raises(ValueError, match="schedule"):
        build_graph(nodes)


@pytest.mark.parametrize(
    ("text", "trades"),
    [
        ("벽지가 누렇게 떴어요", ["dobae"]),
        ("천장 테두리 나무 바꾸고 싶어요", ["mokgong"]),
        ("도배랑 몰딩 같이 하고 싶어요", ["dobae", "mokgong"]),
        ("집 좀 고치고 싶어요", ["dobae", "mokgong"]),
        ("실측 방문은 언제 오나요", ["dobae", "mokgong"]),  # 방문(visit)은 문이 아니다
        # 다른 공정에도 쓰는 증상은 한 공정으로 좁히지 않는다
        ("장판이 들떠요", ["dobae", "mokgong"]),
        ("욕실 곰팡이 어떻게 해요", ["dobae", "mokgong"]),
        ("싱크대 문짝 바꾸고 싶어요", ["dobae", "mokgong"]),
    ],
)
def test_match_trades_one_when_clear_else_both(text, trades):
    assert match_trades(text) == trades


def test_trade_intent_passes_trades_to_trade_agent():
    assert run(default_nodes(), "trade", "몰딩 바꿀래요")["trades"] == ["mokgong"]


def test_history_reaches_agent():
    history = [
        Turn(role="user", text="몰딩 바꿀래요"),
        Turn(role="assistant", text="방이 몇 개예요?"),
    ]
    seen = []

    async def trade(state):
        seen.append(state.get("history"))
        return {"answer": AgentAnswer(sections=[Section(sentences=["네"])])}

    state = {"ctx": CTX, "message": "두 개요", "history": history}
    state["intent"] = Intent(label="trade", confidence=0.9, source="model")
    asyncio.run(build_graph({**default_nodes(), "trade": trade}).ainvoke(state))
    assert seen == [history]


class Plan(BaseModel):
    reply: str


def test_llm_stub_without_live_call():
    msgs = [("user", "안녕")]
    llm.clear_stubs()
    try:
        assert asyncio.run(llm.structured("orchestrator", AgentAnswer, msgs)) == AgentAnswer()
        with pytest.raises(llm.LLMError):  # 필수 칸이 있는데 스텁이 없으면 실패로 알린다
            asyncio.run(llm.structured("orchestrator", Plan, msgs))
        llm.set_stub("orchestrator", Plan(reply="처음이시군요"))
        assert asyncio.run(llm.structured("orchestrator", Plan, msgs)).reply == "처음이시군요"
    finally:
        llm.clear_stubs()


def test_light_model_only_for_listed_roles(monkeypatch):
    """짧은 구조화 출력 역할만 작은 모델, 나머지와 대화는 기본 모델."""
    from app.agent import llm
    from app.config import settings

    monkeypatch.setattr(settings, "openai_agent_model", "big")
    monkeypatch.setattr(settings, "openai_reasoning_effort", "low")
    monkeypatch.setattr(settings, "openai_light_model", "small")
    monkeypatch.setattr(settings, "openai_light_effort", "none")
    monkeypatch.setattr(settings, "openai_light_roles", "trade, schedule")
    assert llm.model_for("trade") == ("small", "none")
    assert llm.model_for("schedule") == ("small", "none")
    assert llm.model_for("orchestrator") == ("big", "low")
    monkeypatch.setattr(settings, "openai_light_model", "")
    assert llm.model_for("trade") == ("big", "low")
