"""고침 3차 A1(QA r3): 다음에 물을 말 · 단계 칩. 유료 호출 0회(Claude 대본).

- 단계는 업체 상태에서 나온 실제 단계로(c1 · s5: 견적 · 확정 단계에 '실측 일정을 챙길까요?', 실측 · 견적이 한 단계였음).
- 이름과 보내는 말을 맞춘다(s5: '실측 일정을 챙길까요?'를 누르면 '오늘 할 일 알려 줘').
- 먼저 말 건 줄의 제안은 그 일이 끝나면 뺀다(c4: 견준 뒤에도 '받은 견적서를 견줘 볼까요?' 9턴).
- 업체 고르기는 고를 수 있는 업체 수로, 0곳이면 믿집 밖 찾기(c4 · f1: 2곳 구에 '업체 3곳', s3: 0곳 지역 10턴).
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant import service as S
from tests.conftest import query
from tests.helpers import use
from tests.test_quote_compare import quote
from tests.test_v3_visit_kit import booked, customer, requested
from tests.test_v4_assistant_free import two_vendors
from tests.test_v4_assistant_nudges import add_nudge
from tests.test_v4_assistant_turns import ask, ok
from tests.test_visit_inbox import login


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


def suggests(api, script, pid: str, text: str = "도배는 어떻게 해요?", tools=None) -> dict:
    """한 턴을 돌리고 done 이벤트의 다음에 물을 말(id → 칸)."""
    steps = [{"tool_calls": tools}] if tools else []
    script([*steps, {"text": "네, 궁금한 걸 물어봐 주세요."}])
    ev = ok(ask(api, pid, text))
    assert ev[-1][0] == "done"
    return {x["id"]: x for x in ev[-1][1]["suggest"]}


def test_visit_idea_name_matches_what_it_sends():
    text, _why, say = S.STEP_IDEAS["visit"]
    assert (text, say) == ("오늘 할 일을 볼까요?", "오늘 할 일 알려 줘")
    assert all("실측 일정을 챙길까요" not in t for t, _, _ in S.STEP_IDEAS.values())


def test_pick_idea_counts_the_vendors_that_can_be_picked(api, script):
    pid, _ = two_vendors(api)  # 노원구에 업체 2곳
    got = suggests(api, script, pid)
    assert got["step-standard"]["text"] == "업체 2곳을 골라 둘까요?"
    assert got["step-standard"]["say"] == "업체 추천해 줘"


def test_no_vendor_district_offers_outside_search_instead(api, script):
    _, pid = customer(api)  # 업체 0곳
    got = suggests(api, script, pid)
    assert "step-standard" not in got
    out = got["step-outside"]
    assert (out["text"], out["say"]) == ("믿집 밖에서 찾아볼까요?", "믿집 밖 도배 업체 찾아 줘")


def test_requested_stage_offers_today_not_vendor_picks(api, script):
    f = requested(api)
    got = suggests(api, script, f["pid"])
    assert got["step-visit"]["text"] == "오늘 할 일을 볼까요?"
    assert "step-standard" not in got


def test_quote_stage_offers_compare_and_nudge_idea_goes_after_comparing(api, script):
    f = booked(api)
    login(api, f["email"])
    quote(api, f["visit"], 2_300_000)
    use(api, f["token"])
    got = suggests(api, script, f["pid"])
    # 견적서가 오면 실측이 아니라 견적 견주기 단계(c1 · s5: '실측 일정을 챙길까요?')
    assert got["step-deal"]["text"] == "견적서를 견줘 볼까요?" and "step-visit" not in got
    uid = query("select id from users where email = 'home@mitjip.test'")[0]["id"]
    nid = add_nudge(
        uid,
        trigger="quote_sent",
        channel="feed",
        status="sent",
        project_id=uuid.UUID(f["pid"]),
        ref=uuid.UUID(f["visit"]),
        sent_at=datetime.now(UTC) - timedelta(minutes=1),
        body="마루와벽이 실측 견적서를 보냈어요. 받은 견적서를 견줘 볼까요?",
        src="guide",
    )
    got = suggests(api, script, f["pid"], "견적서 어때요?")
    assert got[f"n-{nid}"]["text"] == "받은 견적서를 견줘 볼까요?"
    # 견적 비교 카드를 본 턴 뒤로는 줄의 제안도 단계 제안도 빠진다(일이 끝남)
    tools = [{"id": "c", "name": "compare_quotes", "input": {"trade": "dobae"}}]
    got = suggests(api, script, f["pid"], "견줘 줘", tools)
    assert f"n-{nid}" not in got and "step-deal" not in got
    got = suggests(api, script, f["pid"], "포함 항목은요?")
    assert f"n-{nid}" not in got


def test_compare_chip_goes_after_the_vendor_is_confirmed(api, script):
    from tests.test_deal import confirm

    f = booked(api)
    login(api, f["email"])
    quote(api, f["visit"], 2_300_000)
    use(api, f["token"])
    today = [{"id": "t", "name": "today_tasks", "input": {}}]
    script([{"tool_calls": today}, {"text": "오늘 정할 일이에요."}])
    ev = ok(ask(api, f["pid"], "오늘 뭐 해요?"))
    assert "견적서 비교 보기" in ev[-1][1]["chips"]
    assert confirm(api, f["pid"], f["visit"]).status_code == 200
    script([{"tool_calls": today}, {"text": "오늘 정할 일이에요."}])
    ev = ok(ask(api, f["pid"], "이제 뭐 해요?"))
    # 확정 뒤 견적 비교 칩은 지난 단계(QA r3 c1 20턴 · c2 13턴)
    assert "견적서 비교 보기" not in ev[-1][1]["chips"]
