"""이어 하기(사용자 11-24 '취소도 띄워주고 취소사용자가하면 바로 이어서 면적 바꾸는것까지 띄워줘야'): 실측 요청이 살아
있어 잠긴 집 정보를 고쳐 달라고 하면 요청마다 취소 카드를 내밀고, 모두 취소하면 바로 이어서 집 정보 카드를 대화 줄
(follow_up) 하나로 내밀어요. 하나라도 거절하면 잇지 않아요."""

from decimal import Decimal

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant import follow
from app.assistant.tools import propose
from tests.conftest import query
from tests.test_v3_visit_kit import add, vendor
from tests.test_v3_visit_kit import ask as ask_visits
from tests.test_v4_assistant_actions import acts, approve
from tests.test_v4_assistant_aftercare import action
from tests.test_v4_assistant_closing import feed
from tests.test_v4_assistant_new_tools import call, reject, results
from tests.test_v4_assistant_nudges import nudges
from tests.test_v4_assistant_turns import home

AREA = {"area_m2": "84", "area_basis": "exclusive"}


@pytest.fixture(autouse=True)
def repo_knowledge(monkeypatch):
    from app.knowledge import service as knowledge

    async def index(_s):
        return repo_index()

    monkeypatch.setattr(knowledge, "index", index)


@pytest.fixture(autouse=True)
def off():
    llm.clear_stubs()  # 대본이 없으면 LLM_LIVE=false라 무료 모드
    yield
    llm.clear_stubs()


@pytest.fixture
def script():
    yield llm.set_claude_script


def home_two_requests(api) -> str:
    """집 정보(v3)가 있는 공사에 마루와벽 · 결도배 실측 요청까지(고객으로 로그인한 채). 공사 id."""
    a = vendor(api, "maru@mitjip.test", "마루와벽")
    b = vendor(api, "gyeol@mitjip.test", "결도배")
    _token, pid = home(api, "follow@mitjip.test")
    for vid in (a, b):
        assert add(api, pid, vid).status_code == 201
    assert ask_visits(api, pid, [a, b]).status_code == 201
    return pid


def cancels_after_asking(api, script, pid: str) -> tuple[dict, list[dict]]:
    ev, log = call(
        script, api, pid, "집 면적이 84㎡예요, 고쳐 줘", ("propose_home_info", {"fields": AREA})
    )
    got = results(log)[0]
    return got, [x for x in acts(ev) if x["status"] == "proposed"]


def test_cancelling_every_request_brings_the_home_card_right_after(api, script):
    pid = home_two_requests(api)
    got, cards = cancels_after_asking(api, script, pid)
    # 요청마다 취소 카드 + 두 길 안내(요청을 두고 알리기 · 취소하고 바로 고치기). 집 정보 카드는 아직 없어요
    assert (got["state"], got["step"], got["count"]) == ("new", propose.NEED_CANCEL, 2)
    assert "모두 취소하면 바로 이어서" in got["note"] and "실측 때나 채팅이" in got["note"]
    assert any("84" in r["value"] for r in got["rows"])  # 바꿀 값(카드에 갈 줄)
    assert sorted(x["kind"] for x in cards) == ["visit_cancel", "visit_cancel"]
    thens = [action(x["action_id"])["payload"]["then"] for x in cards]
    assert thens[0] == thens[1] and thens[0]["kind"] == "home_info"
    assert Decimal(thens[0]["fields"]["area_m2"]) == 84
    assert thens[0]["fields"]["area_basis"] == "exclusive"
    # 첫 취소: 하나 남아 아직 잇지 않아요
    assert approve(api, cards[0]["action_id"]).json()["status"] == "executed"
    assert nudges(trigger="follow_up") == []
    # 둘째 취소: 잠금이 풀리고 집 정보 카드가 줄 하나로 바로 와요(승인 응답 안에서 만들어요)
    assert approve(api, cards[1]["action_id"]).json()["status"] == "executed"
    (n,) = nudges(trigger="follow_up")
    assert (n["status"], n["channel"], n["src"], n["body"]) == (
        "sent",
        "feed",
        "guide",
        follow.HOME_BODY,
    )
    home = action(n["action_id"])
    assert (home["kind"], home["status"], home["origin"]) == ("home_info", "proposed", "nudge")
    assert home["payload"]["fields"]["area_basis"] == "exclusive"
    # 대화 기록: 문장 · 집 정보 카드 · 승인 카드, 다음에 물을 말은 없어요(승인 카드가 다음 걸음)
    (line,) = [x for x in feed(api, pid)["items"] if x["id"] == f"n-{n['id']}"]
    kinds = [p["t"] for p in line["parts"]]
    assert kinds[0] == "text" and "action" in kinds and "suggest" not in kinds
    # 누르면 바뀌어요
    r = approve(api, str(n["action_id"]), seen=home["target_ver"])
    assert r.json()["status"] == "executed", r.text
    p = api.get(f"/projects/{pid}").json()
    assert Decimal(str(p["home"]["area_m2"])) == 84 and p["home"]["area_basis"] == "exclusive"


def test_a_rejected_cancel_keeps_the_requests_and_brings_nothing(api, script):
    pid = home_two_requests(api)
    _, cards = cancels_after_asking(api, script, pid)
    reject(api, cards[0])  # 이 요청은 두기로 했어요
    assert approve(api, cards[1]["action_id"]).json()["status"] == "executed"
    assert nudges(trigger="follow_up") == []
    assert api.get(f"/projects/{pid}").json()["locked"] is True
    assert (
        query("select count(*) as n from assistant_actions where kind = 'home_info'")[0]["n"] == 0
    )


def test_the_same_group_brings_one_line_only(api, script):
    pid = home_two_requests(api)
    _, cards = cancels_after_asking(api, script, pid)
    for x in cards:
        assert approve(api, x["action_id"]).json()["status"] == "executed"
    # 이미 실행된 카드를 다시 눌러도(같은 응답) 줄은 하나예요
    assert approve(api, cards[1]["action_id"]).json()["status"] == "executed"
    assert len(nudges(trigger="follow_up")) == 1
