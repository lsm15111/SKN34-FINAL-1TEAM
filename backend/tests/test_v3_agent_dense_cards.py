"""v3 무료 모드 의미 검색(KB.dense)으로 카드 다시 확인하기 + 서비스가 무료 모드에서 질문 임베딩을 만드는지.

- answer.accept: 위 규칙(검색 맞물림 · T_HIGH)으로 못 받았을 때만, 근거 조각이 의미 검색 위 D_LOCK개에 있는
  카드에 덤 BD를 더해 한 번 더 본다. 의미 순위가 없으면 예전과 같다.
- chat.service.ai_turn: 키가 있고 ai_embed_free면 무료 모드도 embed_query를 DB 세션 전에 부른다(스텁, 유료 호출 0회).
"""

import json
import uuid
from dataclasses import replace

import pytest
from helpers import signup, use
from pydantic import SecretStr
from v3_kb import repo_index, repo_kb

from app.agent.v3 import answer
from app.agent.v3.answer import Part
from app.knowledge import cards

KB = repo_kb()
CS = KB.cards
A = CS.by_id["mokgong.method.curtain-box"]
B = CS.by_id["dobae.prep.after-dry"]
CURTAIN = "안방 창가 쪽에 커튼박스 만들고 싶어요"


def m(card, score: float) -> cards.Match:
    return cards.Match(card=card, score=score, key=card.keys[0])


def test_v3_card_dense_lock_accepts_mid_score_card():
    cite = A.cites()[0]
    assert answer.accept([m(A, 0.42)], [], None)[0] is None
    assert answer.accept([m(A, 0.42)], [], [])[0] is None
    best, _ = answer.accept([m(A, 0.42)], [], [cite, "K1", "K2"])
    assert best is not None and best.card.id == A.id


def test_v3_card_dense_lock_needs_top_d_and_score():
    cite = A.cites()[0]
    far = ["K1", "K2", "K3", cite]  # 의미 순위 위 D_LOCK(3)개 밖
    assert answer.accept([m(A, 0.42)], [], far)[0] is None
    low = answer.T_CARD - answer.BD - 0.01
    assert answer.accept([m(A, low)], [], [cite])[0] is None


def test_v3_card_dense_does_not_reorder_an_accepted_card():
    # 위 규칙으로 받을 카드(B, T_HIGH)가 있으면 의미 맞물림 카드(A)로 바꾸지 않는다
    best, _ = answer.accept([m(B, 0.70), m(A, 0.60)], [], [A.cites()[0]])
    assert best is not None and best.card.id == B.id


def test_v3_card_without_dense_keeps_keyword_rule():
    cite = A.cites()[0]
    assert answer.accept([m(A, 0.50)], [cite], None)[0].card.id == A.id  # 검색 맞물림 0.50 + B3
    assert answer.accept([m(A, 0.50)], [], None)[0] is None
    assert answer.accept([m(A, 0.62)], [], None)[0].card.id == A.id  # T_HIGH


def test_v3_card_knowledge_uses_dense_from_kb():
    rid = next(k for k, v in repo_index().by_rid.items() if v.chunk.ref == A.cites()[0])
    plain = Part()
    assert answer.knowledge(plain, KB, CURTAIN, trade="mokgong", route="trade") != "card"
    part = Part()
    how = answer.knowledge(part, replace(KB, dense=(rid,)), CURTAIN, trade="mokgong", route="trade")
    assert how == "card" and part.used_cards[0].startswith(f"card:{A.id}@")
    # 색인에 없는 rid는 무시한다(키워드 결과 그대로)
    other = Part()
    answer.knowledge(
        other, replace(KB, dense=("없는/키",)), CURTAIN, trade="mokgong", route="trade"
    )
    assert other.used_cards == plain.used_cards


# ---- 서비스: 무료 모드 임베딩 (시험 DB 필요)


@pytest.fixture
def spy(monkeypatch):
    """embed_query · knowledge.nearest · knowledge.index를 가짜로 바꾸고 부른 순서를 남긴다."""
    from app.agent import llm
    from app.config import settings
    from app.knowledge import service as knowledge

    calls: list[str] = []

    async def embed(text):
        calls.append("embed")
        return ("stub-model", [0.1] * 4)

    async def nearest(_s, emb):
        calls.append("nearest" if emb else "nearest-none")
        return ()

    async def index(_s):
        calls.append("index")
        return repo_index()

    monkeypatch.setattr(llm, "embed_query", embed)
    monkeypatch.setattr(knowledge, "nearest", nearest)
    monkeypatch.setattr(knowledge, "index", index)
    monkeypatch.setattr(settings, "openai_api_key", SecretStr("sk-test-not-real"))
    return calls


def ask(api, text="합지랑 실크 중에 뭐로 해야 해요?"):
    r = api.post("/ai/turns", json={"client_key": uuid.uuid4().hex, "text": text})
    assert r.status_code == 200, r.text
    return r


def test_v3_ai_api_free_mode_embeds_before_db_session(api, spy):
    use(api, signup(api))
    assert json.loads(ask(api).text.rsplit("data: ", 1)[1])["mode"] == "free"
    assert spy[:3] == ["embed", "index", "nearest"]


def test_v3_ai_api_free_embed_off_or_no_key_keeps_keyword_only(api, spy, monkeypatch):
    from app.config import settings

    use(api, signup(api))
    monkeypatch.setattr(settings, "ai_embed_free", False)
    ask(api)
    assert "embed" not in spy and "nearest-none" in spy
    spy.clear()
    monkeypatch.setattr(settings, "ai_embed_free", True)
    monkeypatch.setattr(settings, "openai_api_key", SecretStr(""))
    ask(api)
    assert "embed" not in spy and "nearest-none" in spy


def test_v3_ai_api_free_mode_embed_failure_falls_back(api, spy, monkeypatch):
    from app.agent import llm

    async def fail(_text):
        spy.append("embed-fail")

    monkeypatch.setattr(llm, "embed_query", fail)
    use(api, signup(api))
    r = ask(api)
    assert "embed-fail" in spy and "nearest-none" in spy
    assert "event: done" in r.text
