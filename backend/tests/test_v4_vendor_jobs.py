"""v4 업체 쪽: 같은 업체의 다른 공사와 공사 날짜 겹침(공사 화면 · 미리보기 · 비서 my_jobs · 먼저 말 걸기 후보).
유료 호출 0회(Claude 대본 · 무료 모드)."""

import json
import uuid
from datetime import date, timedelta

import pytest
from v3_kb import repo_index

from app.agent import llm
from app.assistant import proactive
from app.calc.schedule import workdays
from tests.conftest import query
from tests.helpers import use
from tests.test_dates import OFF, TODAY
from tests.test_dates import ready as dates_ready
from tests.test_deal import confirm
from tests.test_quote_compare import quote
from tests.test_v3_visit_kit import quiet
from tests.test_v3_work_deal import post_days
from tests.test_v4_assistant_actions import acts, approve
from tests.test_v4_assistant_nudges import at, run
from tests.test_v4_assistant_turns import ok
from tests.test_vendor_profile import vendor_id
from tests.test_visit_inbox import login
from tests.test_visit_request import SHARE, home, send


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


def second_deal(api) -> tuple[str, str]:
    """같은 업체(마루와벽)가 다른 고객 집에서도 도배를 확정받은 공사. (그 고객 토큰, 확정 id).
    마루와벽으로 로그인한 채 끝난다."""
    maru = str(vendor_id("maru@mitjip.test"))
    token, p = home(api, "home2@mitjip.test")
    assert send(api, p["id"], [maru], share_contact_ids=[maru], **SHARE).status_code == 201
    (v,) = query("select id from visits where project_id = $1", uuid.UUID(p["id"]))
    login(api, "maru@mitjip.test")
    quote(api, str(v["id"]), 3_080_000)
    use(api, token)
    r = confirm(api, p["id"], str(v["id"]))
    assert r.status_code == 200, r.text
    login(api, "maru@mitjip.test")
    return token, r.json()["deal"]["id"]


def first_block(job: dict) -> list[date]:
    """다른 공사가 없을 때 비서가 고르는 첫 공사 날 후보(예상 공정표 시작 다음 날부터 견적서 공사 기간)."""
    start = max(date.fromisoformat(job["plan_start"]), TODAY) + timedelta(days=1)
    return workdays(start, job["quote"]["days"], OFF)


def iso(days) -> list[str]:
    return [d.isoformat() for d in days]


def my_jobs(api, script) -> dict:
    """업체 비서 턴에서 my_jobs 도구 결과(모델에 간 값)."""
    log = script(
        [
            {"tool_calls": [{"id": "j", "name": "my_jobs", "input": {}}]},
            {"text": "공사 날짜 후보를 찾았어요."},
        ]
    )
    r = api.post(
        "/vendor/assistant/turns", json={"client_key": uuid.uuid4().hex, "text": "할 일 보여 줘"}
    )
    ok(r)
    return json.loads(log[1]["messages"][-1]["content"][0]["content"])


def test_other_job_days_are_busy_and_direct_pick_only_warns(api):
    _, _, did, _ = dates_ready(api)
    _, did2 = second_deal(api)
    job = api.get(f"/vendor/jobs/{did}").json()
    assert job["busy_days"] == []  # 다른 공사가 아직 날짜를 안 냈다
    first = first_block(job)
    assert post_days(api, did2, first).status_code == 200  # 다른 공사에 그 날을 냈다(수락 기다림)
    job = api.get(f"/vendor/jobs/{did}").json()
    assert job["busy_days"] == iso(first)
    assert api.get(f"/vendor/jobs/{did2}").json()["busy_days"] == []  # 자기 공사 날은 빼고 센다
    # 미리보기(서버 값): 겹치는 날을 알려 주고 막지는 않는다
    pre = api.get(
        f"/vendor/jobs/{did}/dates/preview",
        params={"start": first[0].isoformat(), "end": first[-1].isoformat(), "crew": 4},
    )
    assert pre.status_code == 200, pre.text
    assert pre.json()["overlaps"] == iso(first)
    later = workdays(first[-1] + timedelta(days=1), 3, OFF)
    pre = api.get(
        f"/vendor/jobs/{did}/dates/preview",
        params={"start": later[0].isoformat(), "end": later[-1].isoformat(), "crew": 4},
    )
    assert pre.json()["overlaps"] == []
    r = post_days(api, did, first)  # 화면에서 겹치는 날을 직접 골라도 보낼 수 있다(경고만)
    assert r.status_code == 200, r.text
    assert r.json()["busy_days"] == iso(first)


def test_accepted_job_days_stay_busy_and_closed_ones_free(api):
    _, _, did, _ = dates_ready(api)
    token2, did2 = second_deal(api)
    first = first_block(api.get(f"/vendor/jobs/{did}").json())
    x = post_days(api, did2, first).json()["proposal"]["id"]
    use(api, token2)
    pid2 = query("select project_id from deals where id = $1", uuid.UUID(did2))[0]["project_id"]
    r = api.post(f"/projects/{pid2}/deals/{did2}/dates/{x}/accept", json={"seen_version": 0})
    assert r.status_code == 200, r.text
    login(api, "maru@mitjip.test")
    assert api.get(f"/vendor/jobs/{did}").json()["busy_days"] == iso(first)  # 수락한 날
    query(
        "update deals set status = 'done', work_done_on = $2 where id = $1", uuid.UUID(did2), TODAY
    )
    assert api.get(f"/vendor/jobs/{did}").json()["busy_days"] == []  # 끝난 공사는 세지 않는다


def test_my_jobs_candidates_avoid_the_same_vendor_other_job(api, script):
    """F2(L14): 비서가 고른 공사 날짜가 같은 업체의 다른 공사(12.8~12.10)와 겹쳤던 일."""
    _, _, did, _ = dates_ready(api)
    _, did2 = second_deal(api)
    first = first_block(api.get(f"/vendor/jobs/{did}").json())
    assert post_days(api, did2, first).status_code == 200
    got = my_jobs(api, script)
    (row,) = [d for d in got["deals"] if d.get("candidates")]
    days = [date.fromisoformat(x) for c in row["candidates"] for x in c["days"]]
    assert days and not set(days) & set(first)  # 두 후보 모두 다른 공사 날을 피한다
    a, b = row["candidates"]
    assert date.fromisoformat(a["start"]) > first[-1]
    assert date.fromisoformat(b["start"]) >= date.fromisoformat(a["start"]) + timedelta(days=7)
    # 그 후보로 만든 승인 카드도 겹치지 않는다(실행은 승인 뒤)
    log = script(
        [
            {
                "tool_calls": [
                    {
                        "id": "d",
                        "name": "propose_dates",
                        "input": {"deal_ref": row["ref"], "days_ref": a["ref"]},
                    }
                ]
            },
            {"text": "공사 날짜 카드를 만들었어요."},
        ]
    )
    r = api.post(
        "/vendor/assistant/turns",
        json={"client_key": uuid.uuid4().hex, "text": "첫 후보로 보낼래요"},
    )
    (act,) = [x for x in acts(ok(r)) if x["status"] == "proposed"]
    assert log and act["kind"] == "dates" and act["target_ver"] == "waiting"
    (payload,) = query(
        "select payload from assistant_actions where id = $1", uuid.UUID(act["action_id"])
    )
    assert json.loads(payload["payload"])["days"] == a["days"]


def test_deal_confirmed_nudge_candidate_avoids_the_other_job(api, monkeypatch):
    """먼저 말 걸기(deal_confirmed) 승인 카드도 같은 후보 함수(date_candidates)를 써서 겹치지 않는다."""
    quiet(monkeypatch)
    _, _, did, _ = dates_ready(api)
    _, did2 = second_deal(api)
    first = first_block(api.get(f"/vendor/jobs/{did}").json())
    assert post_days(api, did2, first).status_code == 200
    now = at(14)
    run(api, proactive.scan_events, now)
    run(api, proactive.evaluate_due, now)
    (n,) = query(
        "select status, action_id from assistant_nudges where trigger = 'deal_confirmed'"
        " and ref_id = $1",
        uuid.UUID(did),
    )
    assert n["status"] == "sent" and n["action_id"] is not None
    (a,) = query("select kind, payload from assistant_actions where id = $1", n["action_id"])
    days = [date.fromisoformat(x) for x in json.loads(a["payload"])["days"]]
    assert a["kind"] == "dates" and days and not set(days) & set(first)
    r = approve(api, str(n["action_id"]), prefix="/vendor/assistant")
    assert r.status_code == 200 and r.json()["status"] == "executed", r.text
    (p,) = query("select days from date_proposals where deal_id = $1", uuid.UUID(did))
    assert list(p["days"]) == days
