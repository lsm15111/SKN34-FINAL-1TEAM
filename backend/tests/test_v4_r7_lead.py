"""QA r7 리드 고침: 실측 요청 칸(공정마다 3곳)이 다 차면 추천 카드를 보내지 않고, 모자라면 요청 승인 카드를
만들지 않아요(c1 높음: 다 찬 뒤 추천 카드 → 요청 카드 승인이 409 slots_full). 유료 호출 0회(Claude 대본)."""

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant.tools import customer as customer_tools
from app.assistant.tools import propose
from tests.test_v3_visit_kit import add, customer, quiet, vendor
from tests.test_v3_visit_kit import ask as send_visits
from tests.test_v4_assistant_cards import proposed
from tests.test_v4_assistant_turns import ask, ok
from tests.test_v4_r6_a1_cards import RECOMMEND, SHOW_PICKS, cards, tool_result


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


NAMES = ("결도배", "마루와벽", "한결도배", "솜씨도배", "바른도배")


def test_slots_bound_request_cards_and_picks(api, script, monkeypatch):
    quiet(monkeypatch)
    vids = [vendor(api, f"r7v{i}@mitjip.test", n) for i, n in enumerate(NAMES)]
    _, pid = customer(api)
    for v in vids[:2]:
        assert add(api, pid, v).status_code == 201
    r = send_visits(api, pid, vids[:2])
    assert r.status_code == 201, r.text  # 2곳 진행 중 → 빈 칸 하나

    # 빈 칸이 하나인데 두 곳 요청 카드는 만들지 않아요(만들면 승인 때 409 slots_full)
    req = {
        "id": "p",
        "name": "propose_visit_request",
        "input": {"trade": "dobae", "vendor_refs": ["v1", "v2"]},
    }
    log = script(
        [
            {"tool_calls": [RECOMMEND]},
            {"tool_calls": [req]},
            {"text": "한 곳만 더 요청할 수 있어요."},
        ]
    )
    ev = ok(ask(api, pid, "추천한 두 곳에도 실측 요청해 줘"))
    assert cards(ev, "vendor_picks")  # 빈 칸이 있으면 추천 카드는 보여요
    assert tool_result(log, 1)["count"] == 3
    err = tool_result(log, 2)
    assert err["error"] == "slots_full" and err["message"] == propose.slots_full_said(2, 1)
    assert "1곳만 더 요청할 수 있어요" in err["message"]
    assert proposed(ev) == []

    # 3곳째가 차면 추천 · 카드 다시 보이기 모두 카드 없이 까닭 · 다음 할 일
    assert add(api, pid, vids[2]).status_code == 201
    r = send_visits(api, pid, [vids[2]])
    assert r.status_code == 201, r.text
    log = script([{"tool_calls": [RECOMMEND]}, {"text": "요청 3곳이 다 찼어요."}])
    ev = ok(ask(api, pid, "업체 추천해 줘"))
    assert not cards(ev, "vendor_picks")
    got = tool_result(log, 1)
    assert got["count"] == 0 and got["picks"] == []
    assert customer_tools.FULL_NOTE in got["note"] and got["next"].startswith("진행 중인")
    assert any(e == "status" and d.get("task") for e, d, _ in ev)  # 진행 중인 요청 작업 카드

    log = script([{"tool_calls": [SHOW_PICKS]}, {"text": "요청 3곳이 다 찼어요."}])
    ev = ok(ask(api, pid, "추천 카드 다시 보여 줘"))
    assert not cards(ev, "vendor_picks")
    got = tool_result(log, 1)
    assert got.get("shown") is None and customer_tools.FULL_NOTE in got["note"]


def test_slots_full_said_reads_both_ways():
    assert propose.slots_full_said(3, 0) == (
        "실측 요청은 공정마다 3곳까지예요. 지금 3곳이 진행 중이라 새 업체에 요청할 수 없어요. "
        "진행 중인 요청 한 곳을 취소하면 다른 업체에 요청할 수 있어요."
    )
    assert "2곳만 더 요청할 수 있어요" in propose.slots_full_said(1, 2)


# ---- 앞 턴 카드를 두고 한 '만들었어요'를 반대 말로 바꾸지 않기(QA r7 c1 9턴) ----


def test_made_words_about_an_earlier_card_are_dropped_not_reversed(api, script):
    from app.assistant import policy
    from tests.test_v4_assistant_actions import approve
    from tests.test_v4_assistant_offers import proposed as offered
    from tests.test_v4_assistant_offers import tokens
    from tests.test_v4_assistant_turns import home

    _, pid = home(api)
    script(
        [
            {
                "tool_calls": [
                    {"id": "p", "name": "propose_home_info", "input": {"fields": {"rooms": 3}}}
                ]
            },
            {"text": "방 개수를 고치는 카드를 확인해 주세요."},
        ]
    )
    (a,) = offered(ok(ask(api, pid, "방은 세 개예요")))
    assert approve(api, a["action_id"], seen=a["target_ver"]).status_code == 200
    # 다음 턴 '?': 방금 승인한 카드를 두고 '만들었어요'라고 해도 '아직 만들지 않았어요'로 뒤집지 않아요
    script([{"text": "방금 방 개수를 고치는 승인 카드를 만들었어요. 저장도 끝났어요."}])
    text = tokens(ok(ask(api, pid, "?")))
    assert policy.CARD_NOT_MADE not in text and "만들었어요" not in text
    assert "저장도 끝났어요" in text


# ---- 날짜 바꾸기 이유의 연락처는 고객에게 가림(QA r7 화면 N1) ----


def test_change_reason_hides_contacts_from_the_customer(api):
    from tests.helpers import use
    from tests.test_final_plan import DOB, after, both_accepted, propose

    customer_token, pid, _dm, dd = both_accepted(api)
    said = "급하면 010-1234-5678로 전화 주세요."
    r = propose(api, "maru@mitjip.test", dd, after(DOB[1]), kind="change", reason=said)
    assert r.status_code == 200, r.text
    assert r.json()["proposal"]["reason"] == said  # 업체 본인 화면은 쓴 그대로
    use(api, customer_token)
    got = api.get(f"/projects/{pid}/schedule").json()
    (x,) = [t["proposal"] for t in got["trades"] if t["proposal"] and t["proposal"]["reason"]]
    assert "010-1234-5678" not in x["reason"] and "전화 주세요" in x["reason"]
