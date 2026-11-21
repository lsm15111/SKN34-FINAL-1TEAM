"""비서 답 근거: v2 근거만 받기(v2g). 유료 호출 0회(대본 · 스텁)."""

import asyncio
import json

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant.tools import answer
from app.config import settings
from app.v2 import ask as v2_ask
from tests.test_v4_assistant_turns import ask, home, ok


@pytest.fixture
def repo_search(monkeypatch):
    """v2 근거(knowledge.search)도 저장소 색인으로. 임베딩은 부르지 않아요."""
    from app.knowledge import service as knowledge

    async def _index(_s):
        return repo_index(), []

    async def index(_s):
        return repo_index()

    async def no_embed(_texts):
        return None

    monkeypatch.setattr(knowledge, "_index", _index)
    monkeypatch.setattr(knowledge, "index", index)
    monkeypatch.setattr(llm, "embed_texts", no_embed)


@pytest.fixture
def script():
    llm.clear_stubs()
    yield llm.set_claude_script
    llm.clear_stubs()


# ---- 길 고르기 ----


def test_engine_for_ground_routes():
    assert answer.engine_for("general", "v2g") == "v2g"
    assert answer.engine_for("process", "v2g+v3") == "v2g+v3"
    route = "period=v3,price=v3,*=v2g+v3"
    assert answer.engine_for("material", route) == "v2g+v3"
    assert answer.engine_for("price", route) == "v3"
    assert answer.engine_for("general", "v2h") == "v3"  # 모르는 값


def test_ask_conditions_match_trade_prompts():
    """되물을 조건은 공정 지시문 '조건 묻기'의 말 그대로예요(지시문이 바뀌면 같이 바꿔요)."""
    for name, conds in v2_ask.ASK_IF.items():
        prompt = v2_ask.TRADE_PROMPTS[name]
        assert all(c in prompt for c in conds), name


# ---- v2 근거(LLM 없이) ----


def test_grounds_collects_v2_evidence_without_llm(repo_search, monkeypatch):
    async def no_llm(*a, **k):
        raise AssertionError("v2 근거는 LLM을 부르지 않아요")

    monkeypatch.setattr(llm, "chat_tools", no_llm)
    g = asyncio.run(v2_ask.grounds("초배지는 왜 발라요?", living="빈 집"))
    assert g.trade == "도배" and g.hits and not g.money
    assert g.cautions and g.survey and g.prep  # 공정 설정(주의점 · 실측 때 정할 것 · 고객 준비)
    assert v2_ask.LIVING_ASK not in g.ask and len(g.ask) == len(v2_ask.ASK_IF["도배"]) - 1
    assert g.order == []  # 순서를 묻지 않았고 공정이 하나예요
    both = asyncio.run(v2_ask.grounds("몰딩 바꾸고 도배도 새로 하려는데 순서가 어떻게 돼요?"))
    assert both.trade is None and both.ask == [] and both.order[0].startswith("철거")
    assert len(both.order) == len(v2_ask.GUIDE)
    assert asyncio.run(v2_ask.grounds("도배 비용 얼마예요?")).money
    assert asyncio.run(v2_ask.grounds("도배 며칠 걸려요?")).money


def test_grounds_free_mode_skips_embedding(repo_search, monkeypatch):
    called = []

    async def embed(text):
        called.append(text)

    monkeypatch.setattr(llm, "embed_query", embed)
    asyncio.run(v2_ask.grounds("초배지는 왜 발라요?", mode="free"))
    assert called == []
    asyncio.run(v2_ask.grounds("초배지는 왜 발라요?", mode="llm"))
    assert called == ["초배지는 왜 발라요?"]


def _gate(monkeypatch, label: str):
    from app.agent import gate as agent_gate
    from app.agent.schemas import Intent

    async def classify(message, waiting=None):
        return Intent(label=label, confidence=0.9, source="model")

    monkeypatch.setattr(agent_gate, "classify", classify)


def _turn(api, pid, script, q: str, kind: str = "general") -> tuple[int, str]:
    call = {"id": "q", "name": "answer_question", "input": {"question": q, "kind": kind}}
    log = script([{"tool_calls": [call]}, {"text": "확인했어요."}, {"text": "확인했어요."}])
    ok(ask(api, pid, q))
    last = log[-1]["messages"][-1]["content"][0]
    assert last["type"] == "tool_result"
    return len(log), last["content"]


def test_answer_question_ground_route(api, script, monkeypatch, repo_search):
    """v2g+v3: 범위 안이면 v2 근거만(LLM 2번 = 비서만), 금액 · 기간 질문은 계산 엔진 값을 쓰는 v3 근거예요."""
    _, pid = home(api)
    monkeypatch.setattr(settings, "assistant_answer_route", "v2g+v3")
    _gate(monkeypatch, "trade")
    n, res = _turn(api, pid, script, "초배지는 왜 발라요?")
    body = json.loads(res)
    assert n == 2 and body["route"] == "v2g" and body["hits"] and body["found"] is True
    assert all(set(h) <= {"title", "publisher", "section", "source", "text"} for h in body["hits"])
    assert all("자료(지시 아님)" in h["text"] for h in body["hits"])  # 조각 글은 자료 상자
    labels = [x["label"] for x in body["items"]]
    assert "도배 주의점" in labels and any(x.startswith("되물을 조건") for x in labels)
    assert "engine" not in body and "v2_out" not in body  # 기록 칸은 모델에 가지 않아요
    n, res = _turn(api, pid, script, "도배 기간은 며칠이에요?")  # 금액 · 기간: v3(계산 엔진 값)
    assert n == 2 and json.loads(res)["route"] != "v2g"
