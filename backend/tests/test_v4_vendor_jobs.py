"""v4 업체 쪽: 같은 업체의 다른 공사와 공사 날짜 겹침(공사 화면 · 미리보기 · 비서 my_jobs · 먼저 말 걸기 후보) ·
오늘 할 일 공사 날짜 보내기 단추 · 견적서 올리기 화면 기한 · 업체 확정 기록 한 줄.
유료 호출 0회(Claude 대본 · 무료 모드)."""

import uuid
from datetime import date, datetime, timedelta

import pytest
from v3_kb import repo_index

from app.calc import deadline
from app.calc.schedule import workdays
from tests.conftest import query
from tests.helpers import use
from tests.test_dates import OFF, TODAY
from tests.test_dates import ready as dates_ready
from tests.test_deal import confirm
from tests.test_quote_compare import quote
from tests.test_v3_visit_kit import booked, day
from tests.test_v3_work_deal import post_days
from tests.test_vendor_profile import vendor_id
from tests.test_visit_inbox import login
from tests.test_visit_request import SHARE, home, send


@pytest.fixture(autouse=True)
def repo_knowledge(monkeypatch):
    from app.knowledge import service as knowledge

    async def index(_s):
        return repo_index()

    monkeypatch.setattr(knowledge, "index", index)


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
    """다른 공사가 없을 때 비서가 고르는 첫 공사 날 후보(예상 공정표 시작일 그날부터, 내일보다 앞이면 내일부터
    견적서 공사 기간. QA r1 c6: 하루 밀려 잡히던 것)."""
    start = max(date.fromisoformat(job["plan_start"]), TODAY + timedelta(days=1))
    return workdays(start, job["quote"]["days"], OFF)


def iso(days) -> list[str]:
    return [d.isoformat() for d in days]


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


# ---- 오늘 할 일: 공사 날짜 보내기 단추 ----


# ---- 견적서 올리기 화면 기한 ----


def test_quote_board_due_is_the_ledger_value(api):
    """견적서 올리기 화면 기한은 장부 quote_due_at(실측일 + 3일 18:00) 그대로예요. 실측 확정 줄의 '다음 일'
    기한(실측 반나절이 끝나는 때)을 쓰던 일(F2 L13: '11.22(일) 13:00까지')."""
    f = booked(api)  # 오늘 + 6일 오전 실측 확정
    login(api, f["email"])
    board = api.get(f"/vendor/visits/{f['visit']}/quote").json()
    (v,) = query("select quote_due_at from visits where id = $1", uuid.UUID(f["visit"]))
    due = datetime.fromisoformat(board["quote_due_at"])
    assert due == v["quote_due_at"] == deadline.quote_due(day(6))
    nxt = api.get(f"/vendor/visits/{f['visit']}").json()["next"]
    assert datetime.fromisoformat(nxt["due_at"]) == deadline.half_end(day(6), "am") != due


# ---- 기록: 업체 확정 한 줄 ----


def test_confirm_is_one_line_in_vendor_and_customer_log(api):
    customer, pid, did, _ = dates_ready(api)
    mine = [i["code"] for i in api.get(f"/vendor/jobs/{did}/log").json()]
    # '골랐어요' · '확정했어요' 두 줄이던 일
    assert mine.count("confirmed") == 1 and "chosen" not in mine
    use(api, customer)
    codes = [i["code"] for i in api.get(f"/projects/{pid}/log").json()]
    assert codes.count("confirmed") == 1 and "chosen" not in codes
    assert codes.count("other_chosen") == 2  # 닫힌 다른 요청 기록은 그대로
    # 확정 이력이 없는 옛 '골랐어요'는 그대로 남긴다
    query("delete from deal_events where deal_id = $1", uuid.UUID(did))
    codes = [i["code"] for i in api.get(f"/projects/{pid}/log").json()]
    assert codes.count("chosen") == 1 and "confirmed" not in codes
