"""v4 비서 공사 날짜 바꾸기 제안(propose_date_change → 행동 date_change): 확정 이름표(d…) · 까닭 코드 · 바라는 때
(며칠 뒤 · 이날부터) → 시작해도 되는 날 1~3개(계산 엔진) · 승인하면 POST …/date-requests와 같은 schedule service 함수 ·
같은 대상의 '공사 전날' 먼저 말 건 줄을 닫음(SETTLES) · 거절한 요청은 다시 만들지 않음 · 무료 모드 '공사 미루고 싶어요'도
승인 카드로 · 묻는 말은 안내만 · 업체 대화도 고객의 날짜 요청에 먼저 말 걸기와 같은 카드로 답함. 유료 호출 0회(Claude 대본)."""

import json
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant import actions
from app.calc.schedule import workdays
from app.refprice.holidays import days_off
from app.shared.clock import today_seoul
from tests.conftest import query
from tests.test_v4_assistant_actions import action_row, acts, approve
from tests.test_v4_assistant_free import vendor_turn
from tests.test_v4_assistant_nudges import add_nudge
from tests.test_v4_assistant_offers import scheduled
from tests.test_v4_assistant_turns import ask, ok
from tests.test_visit_inbox import login

TODAY = today_seoul()
OFF = days_off(TODAY, TODAY + timedelta(days=400))


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


def proposed(ev) -> list[dict]:
    return [x for x in acts(ev) if x["status"] == "proposed"]


def change_turn(**wish) -> list[dict]:
    return [
        {"tool_calls": [{"id": "g", "name": "get_schedule", "input": {}}]},
        {
            "tool_calls": [
                {
                    "id": "c",
                    "name": "propose_date_change",
                    "input": {"deal_ref": "d1", "reason": "move", **wish},
                }
            ]
        },
        {"text": "날짜 바꾸기 요청 카드를 만들었어요. 카드를 확인하고 눌러 주세요."},
    ]


def start_of(pid: str) -> date:
    return query("select start_date from deals where project_id = $1::uuid", pid)[0]["start_date"]


def test_change_card_then_approval_sends_the_date_request(api, script):
    _token, pid, did = scheduled(api)
    start = start_of(pid)
    script(change_turn(delay_days=7))
    ev = ok(ask(api, pid, "이사가 밀려서 공사를 일주일 미루고 싶어요"))
    (a,) = proposed(ev)
    assert a["kind"] == "date_change" and a["summary"]["approve_label"]
    wish = json.loads(action_row(a["action_id"])["payload"])["wish_dates"]
    first = workdays(start + timedelta(days=7), 1, OFF)[0]  # 계산 엔진: 7일 뒤 첫 일하는 날
    assert wish[0] == first.isoformat() and 1 <= len(wish) <= 3
    assert query("select count(*) n from date_requests")[0]["n"] == 0  # 승인 전에는 요청 없음
    uid = query("select user_id from assistant_actions")[0]["user_id"]
    eve = add_nudge(
        uid,
        trigger="work_eve",
        ref=uuid.UUID(did),
        project_id=uuid.UUID(pid),
        status="sent",
        sent_at=datetime.now(UTC),
        body="내일 공사가 시작돼요.",
        src="guide",
    )
    r = approve(api, a["action_id"])
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "executed" and r.json()["result"]["href"].endswith("/schedule")
    (req,) = query("select wish_dates, reason, status from date_requests")
    assert [d.isoformat() for d in req["wish_dates"]] == wish
    assert (req["reason"], req["status"]) == (actions.CHANGE_REASONS["move"], "open")
    t = api.get(f"/projects/{pid}/schedule").json()["trades"][0]
    assert (t["dates_state"], t["deal"]["start_date"]) == ("change_requested", start.isoformat())
    (line,) = query("select status, reason from assistant_nudges where id = $1", eve)
    assert (line["status"], line["reason"]) == ("expired", "acted")  # 공사 전날 줄은 할 일이 끝남
    # 열린 요청이 있으면 다시 만들지 않는다(도구 오류)
    log = script(change_turn(delay_days=14))
    ev = ok(ask(api, pid, "한 주 더 미뤄 주세요"))
    assert proposed(ev) == []
    err = log[2]["messages"][-1]["content"][0]
    assert err["is_error"] and "already_requested" in err["content"]


def test_rejected_change_is_not_made_again_but_a_new_date_is(api, script):
    _token, pid, _did = scheduled(api)
    script(change_turn(delay_days=7))
    (a,) = proposed(ok(ask(api, pid, "공사를 일주일 미루고 싶어요")))
    assert api.post(f"/assistant/actions/{a['action_id']}/reject").json()["status"] == "rejected"
    log = script(change_turn(delay_days=7))
    ev = ok(ask(api, pid, "음 그래도 일주일 미루는 게 좋겠어요"))
    assert proposed(ev) == []
    assert "고객이 거절한 제안이에요" in log[2]["messages"][-1]["content"][0]["content"]
    later = (start_of(pid) + timedelta(days=21)).isoformat()
    script(change_turn(wish_from=later))
    (b,) = proposed(ok(ask(api, pid, f"{later}부터면 좋겠어요")))
    assert b["kind"] == "date_change" and b["action_id"] != a["action_id"]  # 날짜가 바뀜 = 새 사실


def test_change_needs_one_wish_and_a_scheduled_deal(api, script):
    _token, pid, _did = scheduled(api)
    log = script(
        [
            {"tool_calls": [{"id": "g", "name": "get_schedule", "input": {}}]},
            {
                "tool_calls": [
                    {
                        "id": "c",
                        "name": "propose_date_change",
                        "input": {"deal_ref": "d1", "reason": "other"},
                    }
                ]
            },
            {"text": "언제로 바꿀지 알려 주세요."},
        ]
    )
    ok(ask(api, pid, "공사 날짜 바꾸고 싶어요"))
    err = log[2]["messages"][-1]["content"][0]
    assert err["is_error"] and "bad_input" in err["content"]
    assert query("select count(*) n from assistant_actions")[0]["n"] == 0


# ---- 무료 모드 ----


def test_free_postpone_makes_a_change_card_and_a_question_only_guides(api):
    llm.clear_stubs()
    _token, pid, _did = scheduled(api)
    start = start_of(pid)
    ev = ok(ask(api, pid, "공사 미루면 어떻게 돼요?"))
    assert ev[-1][1]["mode"] == "free" and proposed(ev) == []
    text = [d for e, d, _ in ev if e == "card" and d["kind"] == "answer"][-1]["data"]["text"]
    assert "날짜 바꾸기" in text
    # 업체가 미루자는 말 · 바라는 말이 없는 말은 고객 요청 카드를 만들지 않는다
    for said in ("업체가 날짜를 미루자는데 어떻게 돼요?", "공사가 연기돼서 걱정이에요"):
        assert proposed(ok(ask(api, pid, said))) == []
    ev = ok(ask(api, pid, "공사를 2주 미루고 싶어요"))
    (a,) = proposed(ev)
    assert a["kind"] == "date_change"
    wish = json.loads(action_row(a["action_id"])["payload"])["wish_dates"]
    assert wish[0] == workdays(start + timedelta(days=14), 1, OFF)[0].isoformat()
    text = [d for e, d, _ in ev if e == "card" and d["kind"] == "answer"][-1]["data"]["text"]
    assert "승인 카드" in text and "눌러" in text


# ---- 업체: 대화로 고객의 날짜 바꾸기 요청에 답하기 ----


def test_vendor_chat_answers_a_change_request_like_the_nudge(api, script):
    """수락한 뒤 고객이 날짜 바꾸기를 요청하면(change_requested) 업체 대화도 먼저 말 걸기(dates_requested)와 같은
    조건으로 공사 날짜 보내기 카드를 만든다(고객이 고른 시작일 · kind change · 요청 id)."""
    _token, pid, did = scheduled(api)
    w1 = workdays(TODAY + timedelta(days=35), 1, OFF)[0].isoformat()
    body = {"wish_dates": [w1], "reason": "이사 날짜가 바뀌었어요."}
    r = api.post(f"/projects/{pid}/deals/{did}/date-requests", json=body)
    assert r.status_code == 201, r.text
    login(api, "maru@mitjip.test")
    script(
        [
            {"tool_calls": [{"id": "j", "name": "my_jobs", "input": {}}]},
            {
                "tool_calls": [
                    {
                        "id": "p",
                        "name": "propose_dates",
                        "input": {"deal_ref": "d1", "days_ref": "n1"},
                    }
                ]
            },
            {
                "text": "고객이 고른 날로 공사 날짜 보내기 카드를 만들었어요. 카드를 확인하고 눌러 주세요."
            },
        ]
    )
    ev = ok(vendor_turn(api, None, "고객이 날짜를 바꿔 달래요. 답해 줘"))
    (a,) = proposed(ev)
    row = action_row(a["action_id"])
    pl = json.loads(row["payload"])
    assert (a["kind"], row["target_ver"], pl["kind"], pl["days"][0]) == (
        "dates",
        "change_requested",
        "change",
        w1,
    )
    r = approve(api, a["action_id"], prefix="/vendor/assistant")
    assert r.json()["status"] == "executed", r.text
    (p,) = query("select start_date, kind from date_proposals where status = 'pending'")
    assert (p["start_date"].isoformat(), p["kind"]) == (w1, "change")
