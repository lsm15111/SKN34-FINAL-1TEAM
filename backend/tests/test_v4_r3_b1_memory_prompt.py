"""QA 3차 고침 B1(기억 뽑기 지시문, s5 · r2 t1): 물음 · 가정('…하면 얼마?') · 견주기 · 부사('꼼꼼히 보니')는
바람이 아니에요(memory_v3 고침). 대본으로 지시문이 Haiku에 가는지와, 뽑을 것 없음이면 저장하지 않는지 봐요(모델이
지시문을 따르는지는 유료 평가 몫). 유료 호출 0회(무료 모드 · Claude 대본)."""

from datetime import UTC, datetime
from functools import partial

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant import prompts
from tests.conftest import query
from tests.test_v4_assistant_turns import ask, home, ok


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


def test_memory_prompt_says_questions_hypotheticals_and_adverbs_are_not_wishes():
    text = prompts.text("memory")
    assert "물음 · 가정 · 견주기는 바람이 아니야" in text
    assert '"거실만 실크하고 방은 합지로 하면 얼마쯤 돼요?" → 뽑을 것 없음' in text
    assert '"실크랑 합지 중에 뭐가 나아요?" → 뽑을 것 없음' in text
    assert "부사 · 말버릇" in text
    assert '"꼼꼼히 보니 작은방 이음매가 벌어져 있어요" → 뽑을 것 없음' in text
    assert "자기 일정으로 바라는 때를 묻는 말" in text  # 바라는 때를 묻는 말은 그대로 바람이에요


@pytest.mark.parametrize(
    "said",
    [
        "거실만 실크하고 방은 합지로 하면 얼마쯤 돼요?",  # s5 11번
        "꼼꼼히 보니 작은방 창가 쪽 벽지 이음매가 벌어져 있어요.",  # r2 t1 9번
    ],
)
def test_question_or_adverb_goes_to_the_extractor_with_the_rule_and_saves_nothing(
    api, script, said
):
    from app import worker

    _, pid = home(api)
    llm.clear_stubs()  # 무료 턴
    ok(ask(api, pid, said))
    (msg,) = query(
        "select id from chat_messages where role = 'user' order by created_at desc limit 1"
    )
    (_job,) = query(
        "select id from jobs where kind = 'assistant_memory' and ref_id = $1", msg["id"]
    )  # 기억 낱말이 있어 뽑기 일은 생겨요(판단은 Haiku 몫)
    log = script([{"json": {"items": []}}])  # 지시문대로면 뽑을 것 없음
    tally = api.portal.call(partial(worker.sweep, datetime.now(UTC)))
    assert tally == {("assistant_memory", "skipped"): 1}
    (req,) = log
    system = str(req.get("system"))
    assert "물음 · 가정 · 견주기는 바람이 아니야" in system and "부사 · 말버릇" in system
    assert req["messages"] == [{"role": "user", "content": said}]
    assert query("select id from assistant_memory") == []
