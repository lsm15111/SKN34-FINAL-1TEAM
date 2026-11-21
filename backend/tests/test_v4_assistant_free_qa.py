"""v4 비서 무료 모드: QA 1차(r1) 무료 턴 재현 말 고정. 다른 공정은 알아 두기 자료로 답하고, 앞 문장을 빼도 '다만'으로 시작하지 않는다(mt-028).
유료 호출 0회(LLM 꺼짐 = 무료 모드)."""

import re

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant import free
from tests.test_v3_visit_kit import customer, vendor
from tests.test_v4_assistant_turns import ask, ok


@pytest.fixture(autouse=True)
def free_mode(monkeypatch):
    from app.assistant import service
    from app.knowledge import service as knowledge

    async def index(_s):
        return repo_index()

    monkeypatch.setattr(knowledge, "index", index)
    monkeypatch.setattr(service, "TURNS_PER_HOUR", 100_000)
    llm.clear_stubs()  # 대본 없음 + LLM_LIVE=false → 무료 모드
    yield
    llm.clear_stubs()


def turn(api, pid: str, text: str, **body) -> tuple[str, list[str]]:
    """무료 모드 한 턴 → (답 글, 답 말고 보낸 카드 종류)."""
    ev = ok(ask(api, pid, text, **body))
    assert ev[-1][1]["mode"] == "free"
    answer = [d["data"]["text"] for e, d, _ in ev if e == "card" and d["kind"] == "answer"][-1]
    return answer, [d["kind"] for e, d, _ in ev if e == "card" and d["kind"] != "answer"]


def two_vendors(api) -> str:
    vendor(api, "maru@mitjip.test", "마루와벽")
    vendor(api, "gyeol@mitjip.test", "결도배")
    return customer(api)[1]


def test_c5_other_trades_answer_from_know_notes(api):
    pid = two_vendors(api)
    said, kinds = turn(api, pid, "보일러 배관 공사랑 장판은 무슨 순서예요?")
    assert said.startswith("보일러 · 난방 배관을 먼저 손보고") and kinds == []
    assert (
        said.endswith("믿집은 설비 · 바닥 업체를 잇지 않아요.") and "확인하지 못했어요" not in said
    )
    said, kinds = turn(api, pid, "콘센트 위치를 옮기고 싶어요")
    assert "전기 공사" in said and "비데" not in said and "home_info" not in kinds
    assert said.endswith("믿집은 전기 업체를 잇지 않아요.")
    said, _ = turn(api, pid, "욕실 타일 덧방이 나아요 철거가 나아요?")
    assert "덧방" in said and said.endswith("업체를 잇지 않아요.")
    said, kinds = turn(api, pid, "욕실 공사 얼마예요?")
    assert said == free.OTHER_MONEY.format(names="욕실") and kinds == []
    for text in ("보일러 배관 공사랑 장판은 무슨 순서예요?", "콘센트 위치를 옮기고 싶어요"):
        got = turn(api, pid, text)[0]
        assert not re.search(r"\d", got) and len(free.sents(got)) <= 3


def test_mt028_answer_keeps_general_rule_and_no_leading_join(api, monkeypatch):
    """'도배랑 장판 같이 하면 어떤 걸 먼저 해요?': '믿집 공정표는 …'은 카드 말이 아니라 남기고, 앞 문장을 빼도 '다만'으로
    시작하지 않는다."""
    from app.chat import service as chat_service
    from app.chat.schemas import AiAnswerOnlyOut

    pid = two_vendors(api)
    said, kinds = turn(api, pid, "도배랑 장판 같이 하면 어떤 걸 먼저 해요?")
    assert said.startswith("믿집 공정표는 도배 다음에 바닥을 놓아요.") and kinds == []
    reply = "예상 공정표는 이렇게 잡혔어요. 다만 마루는 도배 전에 깔아요."

    async def fake(user, text, today, **kw):
        return AiAnswerOnlyOut.model_construct(mode="free", route="guide", answer=None, text=reply)

    monkeypatch.setattr(chat_service, "answer_only", fake)
    said, _ = turn(api, pid, "도배 처음인데 궁금해요")
    assert said == "마루는 도배 전에 깔아요."  # 공정표 카드가 없어 첫 문장을 뺐다 → 이음말도 뗀다
