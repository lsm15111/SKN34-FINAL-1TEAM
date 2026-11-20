"""v4 비서: 철거 범위 칸(집 정보 API · 손님 표준견적서 · 카드 고르기 demolition:<값>) · 비서 밖(v3 화면 단추)에서
처리해 대상 상태가 바뀐 열린 제안 닫기(expired + handled_elsewhere). 유료 호출 0회(Claude 대본 · 무료 모드)."""

import json
import uuid

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant import service as assistant_service
from app.shared.clock import now_utc
from tests.conftest import query
from tests.helpers import signup, use
from tests.test_dates import SEEN0, days, propose
from tests.test_dates import ready as dates_ready
from tests.test_deal import confirm
from tests.test_deal import setup as deal_setup
from tests.test_v3_project_home import HOME
from tests.test_v3_visit_kit import answer, choose, quiet, requested
from tests.test_v4_assistant_actions import action_row, acts, approve, code, propose_home
from tests.test_v4_assistant_more import dobae
from tests.test_v4_assistant_nudges import offered_nudge, run
from tests.test_v4_assistant_turns import ask, home, ok
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


def sweep(api) -> dict:
    return run(api, assistant_service.sweep, now_utc())


def handled(aid: str) -> bool:
    row = action_row(aid)
    return row["status"] == "expired" and json.loads(row["result"]) == {
        "reason": "handled_elsewhere"
    }


# ---- 철거 범위 칸 ----


def test_home_info_api_saves_demolition(api):
    _, pid = home(api)
    assert api.get(f"/projects/{pid}").json()["home"]["demolition"] is None
    r = api.patch(f"/projects/{pid}", json={**HOME, "demolition": "full"})
    assert r.status_code == 200, r.text
    assert (r.json()["rev"], r.json()["home"]["demolition"]) == (2, "full")
    assert dobae(pid, api)["profile"] == "remodel"
    r = api.patch(f"/projects/{pid}", json=HOME)  # 안 보내면 그대로
    assert r.json()["home"]["demolition"] == "full"
    r = api.patch(f"/projects/{pid}", json={**HOME, "demolition": None})  # null이면 지운다
    assert r.json()["home"]["demolition"] is None
    assert query("select count(*) as n from project_conditions")[0]["n"] == 0
    assert dobae(pid, api)["profile"] == "paper_only"
    assert api.patch(f"/projects/{pid}", json={**HOME, "demolition": "all"}).status_code == 422
    signup(api, "second@mitjip.test")
    r = api.post("/projects", json={**HOME, "demolition": "partial"})
    assert r.status_code == 201 and r.json()["home"]["demolition"] == "partial"
    g = api.post("/guest/standard", json={**HOME, "demolition": "full"})
    assert g.status_code == 200 and g.json()["profile"] == "remodel"
    assert api.post("/guest/standard", json=HOME).json()["profile"] == "paper_only"


def test_card_choice_demolition_makes_an_approve_card(api, script):
    _, pid = home(api)
    llm.clear_stubs()  # 꺼짐(무료 모드): 사람이 누른 고르기는 코드가 승인 카드로 만든다
    ev = ok(ask(api, pid, "전체 철거할게요", context={"choice": "demolition:full"}))
    assert ev[-1][1]["mode"] == "free"
    (a,) = [x for x in acts(ev) if x["status"] == "proposed"]
    assert a["kind"] == "home_info"
    assert a["summary"]["rows"] == [
        {"label": "철거 범위", "value": "전체 철거", "sub": "지금 없음"}
    ]
    said = [d for e, d, _ in ev if e == "card" and d["kind"] == "answer"][-1]
    assert "승인 카드" in said["data"]["text"]
    r = approve(api, a["action_id"], seen=a["target_ver"])
    assert r.status_code == 200 and r.json()["status"] == "executed", r.text
    assert api.get(f"/projects/{pid}").json()["home"]["demolition"] == "full"
    # 켜짐: 카드는 코드가 먼저 만들고 모델에는 화면 말로 알린다. 모르는 값은 버린다
    log = script([{"text": "카드를 확인하고 눌러 주세요."}])
    choice = ["demolition:partial", "demolition:all"]
    ev = ok(ask(api, pid, "부분만 할게요", context={"choice": choice}))
    (b,) = [x for x in acts(ev) if x["status"] == "proposed"]
    assert b["summary"]["rows"][0]["value"] == "부분 철거"
    sent = json.dumps(log[0]["messages"], ensure_ascii=False)
    assert "(카드에서 고름: 철거 범위: 부분 철거)" in sent and "demolition:all" not in sent
    assert "승인 카드를 만들었어요" in sent


# ---- 화면에서 직접 처리한 제안 닫기 ----


def test_home_edit_on_screen_closes_the_open_home_proposal(api, script, monkeypatch):
    quiet(monkeypatch)
    _, pid = home(api)
    a = propose_home(api, script, pid, {"rooms": 3})
    _, other = home(api, "other@mitjip.test")
    b = propose_home(api, script, other, {"rooms": 2})  # 그대로인 대상은 남는다
    login(api, "home@mitjip.test")
    assert sweep(api)["handled"] == 0
    assert api.patch(f"/projects/{pid}", json={**HOME, "occupied": True}).status_code == 200
    assert sweep(api)["handled"] == 1
    assert handled(a["action_id"]) and action_row(b["action_id"])["status"] == "proposed"
    (got,) = api.get("/assistant/actions", params={"status": "expired"}).json()
    assert got["action_id"] == a["action_id"] and got["error_code"] == "handled_elsewhere"
    r = approve(api, a["action_id"])
    assert code(r) == (409, "action_closed") and "이미 처리" in r.json()["error"]["message"]
    assert sweep(api)["handled"] == 0


def test_confirm_on_screen_closes_confirm_and_other_requests(api, script, monkeypatch):
    quiet(monkeypatch)
    _, pid, va, _vb, vc = deal_setup(api)
    script(
        [
            {"tool_calls": [{"id": "c", "name": "compare_quotes", "input": {"trade": "dobae"}}]},
            {
                "tool_calls": [
                    {"id": "p", "name": "propose_vendor_confirm", "input": {"visit_ref": "m1"}}
                ]
            },
            {"text": "확정 카드를 만들었어요. 보고 눌러 주세요."},
        ]
    )
    (a,) = acts(ok(ask(api, pid, "마루와벽으로 할래요")))
    assert a["kind"] == "vendor_confirm"
    sweep(api)  # 업체 새 요청(먼저 말 걸기)이 답하기 제안을 만든다(한결인테리어는 아직 답 전)
    (w,) = query(
        "select id from assistant_actions where kind = 'window_answer' and target_id = $1",
        uuid.UUID(vc),
    )
    assert action_row(a["action_id"])["status"] == "proposed"
    assert confirm(api, pid, va).status_code in (200, 201)  # v3 화면 단추로 직접 확정
    assert sweep(api)["handled"] == 2
    assert handled(a["action_id"]) and handled(str(w["id"]))  # 다른 요청은 닫혀 답할 수 없다


def test_dates_on_screen_close_vendor_and_customer_proposals(api, script, monkeypatch):
    quiet(monkeypatch)
    customer_token, pid, did, _ = dates_ready(api)  # 업체(마루와벽)로 로그인해 있다
    script(
        [
            {"tool_calls": [{"id": "j", "name": "my_jobs", "input": {}}]},
            {
                "tool_calls": [
                    {
                        "id": "d",
                        "name": "propose_dates",
                        "input": {"deal_ref": "d1", "days_ref": "n1"},
                    }
                ]
            },
            {"text": "공사 날짜 카드를 만들었어요."},
        ]
    )
    r = api.post(
        "/vendor/assistant/turns",
        json={"client_key": uuid.uuid4().hex, "text": "공사 날짜 보낼래요"},
    )
    (v,) = [x for x in acts(ok(r)) if x["status"] == "proposed"]
    assert v["kind"] == "dates" and v["target_ver"] == "waiting"
    start, end = days(10)
    assert propose(api, did, start, end).status_code == 200  # v3 화면에서 직접 날짜 보냄
    use(api, customer_token)
    script(
        [
            {"tool_calls": [{"id": "g", "name": "get_schedule", "input": {}}]},
            {
                "tool_calls": [
                    {"id": "a", "name": "propose_dates_accept", "input": {"proposal_ref": "p1"}}
                ]
            },
            {"text": "수락 카드를 만들었어요."},
        ]
    )
    (c,) = [x for x in acts(ok(ask(api, pid, "공사 날짜 어때요?"))) if x["status"] == "proposed"]
    assert c["kind"] == "dates_accept"
    xid = query("select id from date_proposals where status = 'pending'")[0]["id"]
    r = api.post(f"/projects/{pid}/deals/{did}/dates/{xid}/accept", json=SEEN0)
    assert r.status_code == 200, r.text  # v3 화면에서 직접 수락
    sweep(api)
    assert handled(v["action_id"]) and handled(c["action_id"])


def test_vendor_window_on_screen_closes_brief_proposal(api, monkeypatch):
    quiet(monkeypatch)
    f = requested(api)
    login(api, f["email"])
    aid = api.get(f"/vendor/assistant/briefs/{f['visit']}").json()["suggest"]["action_id"]
    assert answer(api, f["visit"]).status_code == 200  # v3 화면에서 직접 기간 답하기
    sweep(api)
    assert handled(aid)
    (got,) = api.get("/vendor/assistant/actions", params={"status": "expired"}).json()
    assert got["error_code"] == "handled_elsewhere"
    assert code(approve(api, aid, prefix="/vendor/assistant")) == (409, "action_closed")


def test_slot_picked_on_screen_closes_the_nudge_and_its_action(api, monkeypatch):
    f, n = offered_nudge(api, monkeypatch)
    assert choose(api, f["pid"], f["visit"]).status_code == 200  # 먼저 말 건 카드 대신 v3 화면에서
    sweep(api)
    assert handled(str(n["action_id"]))
    (row,) = query("select status, reason from assistant_nudges where id = $1", n["id"])
    assert (row["status"], row["reason"]) == ("expired", "handled")
    feed = api.get("/assistant/feed", params={"project_id": f["pid"]}).json()
    assert f"n-{n['id']}" not in {x["id"] for x in feed["items"]}


def test_tool_names_match_their_functions():
    """도구 함수를 꺼내 쓸 때 장식(@tool)이 다른 함수에 붙지 않았는지 (my_jobs가 날짜 후보 함수에 붙었던 일)"""
    from app.assistant import tools
    from app.assistant.tools import answer, customer, floorplan, propose, vendor  # noqa: F401

    assert {n: t.run.__name__ for n, t in tools.REGISTRY.items()} == {n: n for n in tools.REGISTRY}
