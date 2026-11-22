"""고침 4차 리드: 업체 추천 결과의 가견적 범위 칸(QA r4 s5: 다른 업체 값을 범위 아래 끝으로 말함). LLM 없음."""

from types import SimpleNamespace

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant.tools import cards
from tests.test_v3_visit_kit import vendor
from tests.test_v4_assistant_new_tools import call, results
from tests.test_v4_assistant_turns import home
from tests.test_visit_vendors import priced


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


def test_picks_give_the_estimate_range_from_the_lowest_to_the_highest(api, script):
    vendor(api, "maru@mitjip.test", "마루와벽")
    priced(api, "gyeol@mitjip.test", "결도배", wall=7000)
    _, pid = home(api)
    _ev, log = call(script, api, pid, "업체 비교해 줘", ("recommend_vendors", {"trade": "dobae"}))
    rec = results(log, 1)[0]  # 모델이 받은 값(허용 칸만)
    wons = [x["estimate_won"] for x in rec["picks"]]
    assert len(wons) == 2 and wons[0] != wons[1]
    assert rec["estimate_low_won"] == min(wons) and rec["estimate_high_won"] == max(wons)


def test_estimate_range_needs_two_priced_picks():
    one = [SimpleNamespace(estimate_won=3_045_900)]
    assert cards.estimate_range(one) == {}
    assert cards.estimate_range([SimpleNamespace(estimate_won=0), *one]) == {}
    two = [SimpleNamespace(estimate_won=3_072_630), SimpleNamespace(estimate_won=3_045_900)]
    assert cards.estimate_range(two) == {
        "estimate_low_won": 3_045_900,
        "estimate_high_won": 3_072_630,
    }
