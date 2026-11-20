"""공사 끝냈어요 · 고객 확인 · 남은 일 · 연락처 1년: 전이 · 마지막 공사일 · 연락처 기한 · 작업함 탭 · 동시 409 · 권한."""

import asyncio
import uuid
from datetime import date, timedelta

from app.auth.models import User
from app.calc.schedule import contact_until
from app.db import SessionLocal
from app.schedule import service
from app.schedule.schemas import CheckIn
from app.shared.clock import today_seoul
from app.shared.errors import AppError
from app.visit import service as visit_service
from tests.conftest import query
from tests.helpers import no_surprises, signup, use
from tests.test_dates import days, mokgong_deal, propose, ready
from tests.test_extras import extra, scheduled
from tests.test_visit_inbox import login
from tests.test_visit_request import listed

TODAY = today_seoul()
WORKED = "update deals set start_date = current_date - 3, end_date = current_date"


def ids(email: str) -> uuid.UUID:
    return query("select id from users where email = $1", email)[0]["id"]


def bodies(kind: str) -> list[str]:
    return [
        r["body"]
        for r in query("select body from notifications where kind = $1 order by created_at", kind)
    ]


def visit_id() -> uuid.UUID:
    return query("select visit_id from deals")[0][0]


def _finish(did: str, today: date):
    maru = ids("maru@mitjip.test")

    async def run():
        async with SessionLocal() as s:
            vendor = await s.get(User, maru)
            return await service.finish(s, vendor, uuid.UUID(did), today)

    return asyncio.run(run())


def test_finish_fixing_finish_again_then_done(api):
    customer, pid, did = scheduled(api)
    early = api.post(f"/vendor/jobs/{did}/done")
    assert (
        early.status_code == 409
        and early.json()["error"]["message"] == "마지막 공사일부터 누를 수 있어요."
    )
    job = api.get(f"/vendor/jobs/{did}").json()
    assert (job["can_finish"], job["accepted_crew"]) == (False, 4)
    query(WORKED)
    assert api.get(f"/vendor/jobs/{did}").json()["can_finish"] is True

    r = api.post(f"/vendor/jobs/{did}/done")
    assert r.status_code == 200, r.text
    job = r.json()
    until = contact_until(TODAY)
    assert (job["status"], job["work_done_on"], job["contact_until"], job["can_finish"]) == (
        "checking",
        TODAY.isoformat(),
        until.isoformat(),
        False,
    )
    assert query("select contact_until from visits where id = $1", visit_id())[0][0] == until
    assert bodies("work_done") == ["마루와벽이 공사를 끝냈다고 알렸어요 · 확인해 주세요"]
    (row,) = api.get("/vendor/visits", params={"tab": "jobs"}).json()["items"]
    assert (row["deal_status"], row["work_done_on"], row["contact_until"]) == (
        "checking",
        TODAY.isoformat(),
        until.isoformat(),
    )
    again = api.post(f"/vendor/jobs/{did}/done")
    assert again.status_code == 409 and again.json()["error"]["code"] == "invalid_state"
    assert extra(api, did, 10_000).status_code == 409  # 끝낸 뒤 추가 금액 막힘
    late = propose(api, did, *days(14), kind="change", reason="미뤄요.")
    assert late.status_code == 409  # 끝낸 뒤 날짜 바꾸기 막힘

    use(api, customer)
    url = f"/projects/{pid}/deals/{did}/check"
    assert api.post(url, json={"result": "fixing"}).json()["error"]["code"] == "note"
    r = api.post(url, json={"result": "fixing", "note": "작은방 천장 모서리 벽지가 들떠 있어요."})
    assert r.status_code == 200, r.text
    assert (r.json()["status"], r.json()["fixing_note"]) == (
        "fixing",
        "작은방 천장 모서리 벽지가 들떠 있어요.",
    )
    assert bodies("work_checked") == ["고객이 남은 일이 있대요 · 노원구 도배"]  # v3: 공사 이름
    login(api, "maru@mitjip.test")
    (row,) = api.get("/vendor/visits", params={"tab": "jobs"}).json()["items"]
    assert (row["deal_status"], row["fixing_note"]) == (
        "fixing",
        "작은방 천장 모서리 벽지가 들떠 있어요.",
    )
    assert extra(api, did, 10_000).status_code == 201  # 남은 일 하는 동안은 알릴 수 있다

    later = TODAY + timedelta(days=2)
    job = _finish(did, later)  # 남은 일 다 했어요: 연락처 기한을 새로 센다
    assert (job.status, job.work_done_on, job.contact_until) == (
        "checking",
        later,
        contact_until(later),
    )
    assert bodies("work_done")[-1] == "마루와벽이 남은 일을 다 했다고 알렸어요 · 확인해 주세요"

    use(api, customer)
    r = api.post(url, json={"result": "done"})
    assert r.status_code == 200 and r.json()["status"] == "done"
    assert r.json()["contact_until"] == contact_until(later).isoformat()
    assert bodies("work_checked")[-1] == "고객이 공사 끝남을 확인했어요 · 노원구 도배"
    assert api.post(url, json={"result": "done"}).status_code == 409
    events = query("select from_status, to_status, note from deal_events order by at")
    assert [(e["from_status"], e["to_status"]) for e in events][-4:] == [
        ("scheduled", "checking"),
        ("checking", "fixing"),
        ("fixing", "checking"),
        ("checking", "done"),
    ]
    (d,) = api.get(f"/projects/{pid}/deals").json()
    assert (d["status"], d["work_done_on"]) == ("done", later.isoformat())
    assert api.get(f"/projects/{pid}/plan").json()["deals"][0]["status"] == "done"

    login(api, "maru@mitjip.test")
    assert api.get("/vendor/visits", params={"tab": "jobs"}).json()["items"] == []
    done = api.get("/vendor/visits", params={"tab": "done"}).json()["items"]
    mine = next(x for x in done if x["deal_id"] == did)
    # v3(B3): 작업함 줄에는 고객 이름 · 연락처 칸이 없다 (채팅으로, architecture 10장)
    assert (mine["deal_status"], mine["contact_until"]) == (
        "done",
        contact_until(later).isoformat(),
    )
    assert "customer" not in mine
    assert done[0]["deal_id"] == did  # 가장 최근에 끝남
    summary = api.get("/vendor/visits/summary").json()
    assert (summary["jobs"], summary["done"]) == (0, 1)


def test_contact_is_shown_until_one_year_after_the_last_finish(api):
    customer, pid, did = scheduled(api)
    query(WORKED)
    assert api.post(f"/vendor/jobs/{did}/done").status_code == 200
    use(api, customer)
    assert (
        api.post(f"/projects/{pid}/deals/{did}/check", json={"result": "done"}).status_code == 200
    )
    until = contact_until(TODAY)

    maru, home, vid = ids("maru@mitjip.test"), ids("home@mitjip.test"), visit_id()

    async def look(today: date):
        async with SessionLocal() as s:
            vendor = await s.get(User, maru)
            user = await s.get(User, home)
            seen = await visit_service.vendor_visit(s, vendor, vid, today)
            (deal,) = await service.deals_for(s, user, uuid.UUID(pid), None, today)
            return seen, deal.owner_name

    seen, shown_customer = asyncio.run(look(until))
    # v3(B3): 업체 화면에는 고객 연락처 칸이 없다(채팅으로). 고객 쪽 업체 연락처만 1년 규칙대로
    assert "customer" not in type(seen).model_fields and shown_customer == "예시 대표"
    assert asyncio.run(look(until + timedelta(days=1)))[1] is None  # 하루 지나면 가림


def test_feb_29_counts_to_feb_28(api):
    _, _, did = scheduled(api)
    query(WORKED)
    job = _finish(did, date(2028, 2, 29))
    assert job.contact_until == date(2029, 2, 28)


def test_state_rules(api):
    customer, pid, did, _ = ready(api)  # 날짜 수락 전
    r = api.post(f"/vendor/jobs/{did}/done")
    assert (
        r.status_code == 409
        and r.json()["error"]["message"] == "공사 날짜를 수락한 뒤에 올릴 수 있어요."
    )
    use(api, customer)
    r = api.post(f"/projects/{pid}/deals/{did}/check", json={"result": "done"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "invalid_state"
    assert (
        api.post(f"/projects/{pid}/deals/{did}/check", json={"result": "later"}).status_code == 422
    )


def test_trade_not_in_home_saves_nothing(api):
    """집 정보로 필요한 기간을 못 세는 공정(도배만 고른 집의 목공)은 저장하기 전에 409.
    공사 화면 응답을 못 만드는데 끝냄(상태 · 이력 · 기한 일 · 알림)만 저장되면 안 된다."""
    _customer, pid, _did, _ = ready(api)
    vid = listed(api, "barum@mitjip.test", "바름집수리")  # 업체로 로그인
    mok = uuid.UUID(mokgong_deal(pid, vid, "scheduled", TODAY - timedelta(days=3), TODAY))
    r = api.post(f"/vendor/jobs/{mok}/done")
    assert r.status_code == 409 and r.json()["error"]["code"] == "trade", r.text
    (row,) = query("select status, work_done_on from deals where id = $1", mok)
    assert (row["status"], row["work_done_on"]) == ("scheduled", None)
    assert query("select count(*) n from deal_events where deal_id = $1", mok)[0]["n"] == 0
    assert query("select count(*) n from jobs where ref_id = $1", mok)[0]["n"] == 0
    assert bodies("work_done") == []


def test_two_checks_at_once_only_one_wins(api):
    _customer, pid, did = scheduled(api)
    query(WORKED)
    assert api.post(f"/vendor/jobs/{did}/done").status_code == 200
    me = ids("home@mitjip.test")

    def go(data: CheckIn):
        async def call():
            async with SessionLocal() as s:
                user = await s.get(User, me)
                return await service.check_work(
                    s, user, uuid.UUID(pid), uuid.UUID(did), data, TODAY
                )

        return call

    async def both():
        return await asyncio.gather(
            go(CheckIn(result="done"))(),
            go(CheckIn(result="fixing", note="벽지가 들떠요."))(),
            return_exceptions=True,
        )

    results = no_surprises(asyncio.run(both()))
    errors = [r for r in results if isinstance(r, AppError)]
    assert len(errors) == 1 and errors[0].status == 409
    assert len(query("select id from notifications where kind = 'work_checked'")) == 1


def test_only_my_job_and_my_home(api):
    customer, pid, did = scheduled(api)
    query(WORKED)
    finish = lambda: api.post(f"/vendor/jobs/{did}/done")
    check = lambda: api.post(f"/projects/{pid}/deals/{did}/check", json={"result": "done"})
    login(api, "gyeol@mitjip.test")
    assert finish().status_code == 404  # 다른 업체
    assert check().status_code == 403  # 업체 → 고객 API
    use(api, customer)
    assert finish().status_code == 403  # 고객 → 업체 API
    assert (
        api.post(f"/projects/{pid}/deals/{uuid.uuid4()}/check", json={"result": "done"}).status_code
        == 404
    )
    signup(api, "other@mitjip.test")
    assert check().status_code == 404  # 남의 집
    assert query("select status from deals")[0]["status"] == "scheduled"
