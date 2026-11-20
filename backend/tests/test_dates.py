"""공사 날짜: 업체가 내기 · 다시 내기 · 고객 수락 · 다른 날짜 요청 · 기한 · 겹침 · 동시 409 · 권한 · 제약."""

import asyncio
import uuid
from datetime import datetime, timedelta

import asyncpg
import pytest

from app.auth.models import User
from app.calc.deadline import date_request_due
from app.calc.schedule import workdays
from app.db import SessionLocal
from app.refprice.holidays import HOLIDAYS, days_off
from app.schedule import service
from app.schedule.schemas import AcceptIn, DatesIn
from app.shared.clock import today_seoul
from app.shared.errors import AppError
from tests.conftest import BACKEND, query
from tests.helpers import make_admin, no_surprises, signup, use
from tests.test_deal import confirm, setup
from tests.test_visit_inbox import login
from tests.test_visit_request import listed

TODAY = today_seoul()
OFF = days_off(TODAY, TODAY + timedelta(days=400))
WEEKEND_DAY = TODAY + timedelta(days=(5 - TODAY.weekday()) % 7 or 7)  # 다음 토요일
SEEN0 = {"seen_version": 0}  # 확정 공정표가 아직 없을 때 본 버전
HOLIDAY = next(d for d in sorted(HOLIDAYS) if d > TODAY + timedelta(days=1) and d.weekday() < 5)


def days(after: int, n: int = 3) -> tuple[str, str]:
    """오늘부터 after일 뒤 첫 일하는 날에 시작해 일하는 날 n개 (계산 엔진)"""
    got = workdays(TODAY + timedelta(days=after), n, OFF)
    return got[0].isoformat(), got[-1].isoformat()


def ready(api):
    """도배를 마루와벽으로 확정한 집. (고객 토큰, 프로젝트 id, 확정 id, 요청 id). 업체로 로그인해 있다."""
    customer, pid, va, _, _ = setup(api)
    did = confirm(api, pid, va).json()["deal"]["id"]
    login(api, "maru@mitjip.test")
    return customer, pid, did, va


def propose(api, did: str, start: str, end: str, crew: int = 4, **over):
    return api.post(
        f"/vendor/jobs/{did}/dates",
        json={"start": start, "end": end, "crew": crew, "method": "app", **over},
    )


def notes(email: str, kind: str) -> list[dict]:
    uid = query("select id from users where email = $1", email)[0]["id"]
    rows = query(
        "select body, link, dedup_key from notifications where user_id = $1 and kind = $2"
        " order by created_at",
        uid,
        kind,
    )
    return [dict(x) for x in rows]


def sched(api, pid: str) -> dict:
    (t,) = api.get(f"/projects/{pid}/schedule").json()["trades"]
    return t


def mokgong_scheduled(pid: str, start: str, end: str) -> None:
    """같은 집 목공을 다른 업체로 확정 · 날짜 수락한 것처럼 넣는다 (겹침 확인용)"""
    vid = uuid.uuid4()
    query(
        "insert into visits (id, project_id, trade, vendor_name, slot, status)"
        " values ($1, $2, 'mokgong', '바름집수리', 1, 'chosen')",
        vid,
        uuid.UUID(pid),
    )
    query(
        "insert into deals (id, project_id, trade, vendor_name, visit_id, quote_id, status,"
        " dates_due_at, start_date, end_date)"
        " select gen_random_uuid(), $1, 'mokgong', '바름집수리', $2, quote_id, 'scheduled', now(),"
        " $3::date, $4::date from deals limit 1",
        uuid.UUID(pid),
        vid,
        datetime.fromisoformat(start).date(),
        datetime.fromisoformat(end).date(),
    )


def mokgong_confirmed(pid: str, vendor_id: str) -> str:
    """도배만 고른 집에 업체가 있는 목공 확정을 넣는다 (평가 시뮬레이터와 같은 방법). 확정 id."""
    vid, did = uuid.uuid4(), uuid.uuid4()
    query(
        "insert into visits (id, project_id, trade, vendor_id, vendor_name, slot, status)"
        " values ($1, $2, 'mokgong', $3, '바름집수리', 1, 'chosen')",
        vid,
        uuid.UUID(pid),
        uuid.UUID(vendor_id),
    )
    query(
        "insert into deals (id, project_id, trade, vendor_id, vendor_name, visit_id, quote_id,"
        " status, dates_due_at)"
        " select $1, $2, 'mokgong', $3, '바름집수리', $4, quote_id, 'confirmed', now()"
        " from deals where project_id = $2 limit 1",
        did,
        uuid.UUID(pid),
        uuid.UUID(vendor_id),
        vid,
    )
    return str(did)


def test_propose_again_then_accept(api):
    customer, pid, did, va = ready(api)
    job = api.get(f"/vendor/jobs/{did}").json()
    assert (job["dates_state"], job["proposal"], job["overdue"]) == ("waiting", None, False)
    # v3(B3): 업체 공사 화면에는 고객 이름 · 연락처 · 주소 칸이 없다 (채팅으로)
    assert "customer" not in job["visit"] and job["quote"]["version"] == 1
    assert job["need"]["days"] >= 1 and job["plan_version"] >= 1 and job["requests_left"] == 2
    a, b = days(14)
    pre = api.get(f"/vendor/jobs/{did}/dates/preview", params={"start": a, "end": b, "crew": 4})
    assert pre.status_code == 200, pre.text
    assert pre.json()["workdays"] == 3 and pre.json()["need"]["crew"] == 4
    assert pre.json()["fit"] == {"conflicts": [], "start_from": None, "end_by": None}

    r = propose(api, did, a, b)
    assert r.status_code == 200, r.text
    first = r.json()["proposal"]
    assert (r.json()["dates_state"], first["start"], first["workdays"], first["changed"]) == (
        "proposed",
        a,
        3,
        False,
    )
    c, d = days(21)
    r = propose(api, did, c, d, crew=3, method="call", call_on=TODAY.isoformat())
    second = r.json()["proposal"]
    assert (second["method"], second["call_on"], second["changed"]) == (
        "call",
        TODAY.isoformat(),
        True,
    )
    rows = query("select id, status, decided_at from date_proposals order by created_at")
    assert [(str(x["id"]), x["status"]) for x in rows] == [
        (first["id"], "superseded"),
        (second["id"], "pending"),
    ]
    assert rows[0]["decided_at"] is not None and rows[1]["decided_at"] is None
    link = f"/projects/{pid}/schedule?trade=dobae"
    assert notes("home@mitjip.test", "dates_proposed") == [
        {
            "body": "마루와벽이 공사 날짜를 냈어요 · 도배",
            "link": link,
            "dedup_key": f"date_proposal:{first['id']}",
        },
        {
            "body": "마루와벽이 공사 날짜를 다시 냈어요 · 도배",
            "link": link,
            "dedup_key": f"date_proposal:{second['id']}",
        },
    ]
    (row,) = api.get("/vendor/visits", params={"tab": "jobs"}).json()["items"]
    assert (
        row["dates_state"],
        row["proposed_start"],
        row["proposed_end"],
        row["proposed_days"],
    ) == (
        "proposed",
        c,
        d,
        0,
    )

    use(api, customer)
    t = sched(api, pid)
    assert (t["dates_state"], t["proposal"]["id"], t["requests_left"]) == (
        "proposed",
        second["id"],
        2,
    )
    assert t["fit"]["conflicts"] == [] and len(t["start_options"]) == 5
    assert all(o["start"] != c for o in t["start_options"])
    base = f"/projects/{pid}/deals/{did}/dates"
    old = api.post(f"{base}/{first['id']}/accept", json=SEEN0)
    assert old.status_code == 409 and old.json()["error"]["code"] == "dates_changed"
    ok = api.post(f"{base}/{second['id']}/accept", json=SEEN0)
    assert ok.status_code == 200, ok.text
    (t,) = ok.json()["trades"]
    assert (
        t["dates_state"],
        t["deal"]["status"],
        t["deal"]["start_date"],
        t["deal"]["end_date"],
    ) == (
        "scheduled",
        "scheduled",
        c,
        d,
    )
    assert t["proposal"] is None
    (x,) = query("select status, decided_at from date_proposals where status = 'accepted'")
    assert x["decided_at"] is not None
    events = query("select from_status, to_status from deal_events order by at")
    assert [(e["from_status"], e["to_status"]) for e in events] == [
        (None, "confirmed"),
        ("confirmed", "scheduled"),
    ]
    assert notes("maru@mitjip.test", "dates_accepted") == [
        {
            "body": "고객이 공사 날짜를 수락했어요 · 노원구 도배",  # v3: 업체 알림에 공사 이름
            "link": f"/vendor/jobs/{did}",
            "dedup_key": f"date_proposal:{second['id']}:accepted",
        }
    ]
    again = api.post(f"{base}/{second['id']}/accept", json=SEEN0)
    assert again.status_code == 409 and again.json()["error"]["code"] == "invalid_state"
    assert api.post(f"/projects/{pid}/deals/{did}/reselect").status_code == 409

    login(api, "maru@mitjip.test")
    late = propose(api, did, a, b)
    assert (
        late.status_code == 409
        and late.json()["error"]["message"] == "고객이 이미 공사 날짜를 수락했어요."
    )
    (row,) = api.get("/vendor/visits", params={"tab": "jobs"}).json()["items"]
    assert (row["dates_state"], row["start_date"], row["end_date"]) == ("scheduled", c, d)
    assert "customer" not in api.get(f"/vendor/visits/{va}").json()  # v3(B3): 연락처 칸 없음


def test_request_answer_and_two_requests_only(api):
    customer, pid, did, _ = ready(api)
    a, b = days(14)
    p1 = propose(api, did, a, b).json()["proposal"]
    use(api, customer)
    url = f"/projects/{pid}/deals/{did}/date-requests"
    w1, w2 = days(28, 2)
    r = api.post(url, json={"wish_dates": [w2, w1], "reason": "엘리베이터 점검이 있어요."})
    assert r.status_code == 201, r.text
    (t,) = r.json()["trades"]
    req = t["request"]
    assert (t["dates_state"], t["requests_left"], req["wish_dates"], req["overdue"]) == (
        "requested",
        1,
        [w1, w2],
        False,
    )
    assert t["proposal"]["id"] == p1["id"]  # 낸 날짜는 그대로 남는다
    created = datetime.fromisoformat(req["created_at"])
    # v3: 요청 + 48시간 (api.md 11장, 지금 '다음 날 18:00'에서 바꿈)
    assert datetime.fromisoformat(req["due_at"]) == date_request_due(created)
    assert notes("maru@mitjip.test", "dates_requested") == [
        {
            "body": "고객이 다른 공사 날짜를 요청했어요 · 노원구 도배",  # v3: 업체 알림에 공사 이름
            "link": f"/vendor/jobs/{did}",
            "dedup_key": f"date_request:{req['id']}",
        }
    ]
    twice = api.post(url, json={"wish_dates": [w1]})
    assert twice.status_code == 409 and twice.json()["error"]["code"] == "already_requested"

    login(api, "maru@mitjip.test")
    (row,) = api.get("/vendor/visits", params={"tab": "jobs"}).json()["items"]
    assert (row["dates_state"], row["wish_dates"], row["request_due_at"]) == (
        "requested",
        [w1, w2],
        req["due_at"],
    )
    assert api.get(f"/vendor/jobs/{did}").json()["request"]["id"] == req["id"]
    wrong = propose(api, did, *days(28), request_id=str(uuid.uuid4()))
    assert wrong.status_code == 409 and wrong.json()["error"]["code"] == "request_changed"
    p2 = propose(api, did, *days(28), request_id=req["id"]).json()
    assert (p2["dates_state"], p2["request"], p2["proposal"]["request_id"]) == (
        "proposed",
        None,
        req["id"],
    )
    assert query("select status from date_requests")[0]["status"] == "answered"

    use(api, customer)
    assert api.post(url, json={"wish_dates": [w2]}).status_code == 201  # 두 번째
    login(api, "maru@mitjip.test")
    assert propose(api, did, *days(35)).status_code == 200  # 요청에 답함 (request_id 없이도)
    use(api, customer)
    third = api.post(url, json={"wish_dates": [w1]})
    assert (
        third.status_code == 409
        and third.json()["error"]["message"] == "다른 날짜 요청은 2번까지 할 수 있어요."
    )
    assert query("select date_request_count n from deals")[0]["n"] == 2
    t = sched(api, pid)
    assert (t["requests_left"], t["request"]) == (0, None)
    assert (
        api.post(
            f"/projects/{pid}/deals/{did}/dates/{t['proposal']['id']}/accept", json=SEEN0
        ).status_code
        == 200
    )


def test_open_request_is_closed_when_the_customer_accepts(api):
    customer, pid, did, _ = ready(api)
    p1 = propose(api, did, *days(14)).json()["proposal"]
    use(api, customer)
    assert (
        api.post(
            f"/projects/{pid}/deals/{did}/date-requests", json={"wish_dates": [days(28)[0]]}
        ).status_code
        == 201
    )
    assert (
        api.post(f"/projects/{pid}/deals/{did}/dates/{p1['id']}/accept", json=SEEN0).status_code
        == 200
    )
    assert query("select status from date_requests")[0]["status"] == "withdrawn"


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"start": TODAY.isoformat(), "end": days(3)[1]}, "start"),  # 오늘은 못 냄
        ({"start": days(14)[1], "end": days(14)[0]}, "end"),
        ({"start": days(14)[0], "end": (TODAY + timedelta(days=150)).isoformat()}, "end"),
        ({"start": WEEKEND_DAY.isoformat(), "end": days(14)[1]}, "off_day"),
        (
            {"start": HOLIDAY.isoformat(), "end": workdays(HOLIDAY, 2, OFF)[-1].isoformat()},
            "off_day",
        ),
        ({"method": "call"}, "call_on"),
        ({"method": "call", "call_on": (TODAY + timedelta(days=1)).isoformat()}, "call_on"),
        ({"crew": 0}, "invalid"),
        ({"crew": 21}, "invalid"),
    ],
)
def test_vendor_date_rules(api, body, code):
    _, _, did, _ = ready(api)
    a, b = days(14)
    r = api.post(
        f"/vendor/jobs/{did}/dates",
        json={"start": a, "end": b, "crew": 4, "method": "app", **body},
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == code, r.text
    assert query("select count(*) n from date_proposals")[0]["n"] == 0


@pytest.mark.parametrize(
    ("wish", "code"),
    [
        ([TODAY.isoformat()], "wish_dates"),
        ([WEEKEND_DAY.isoformat()], "wish_dates"),
        ([HOLIDAY.isoformat()], "wish_dates"),
        ([days(20)[0], days(20)[0]], "invalid"),
        ([days(20)[0], days(21)[0], days(22)[0], days(23)[0]], "invalid"),
        ([], "invalid"),
    ],
)
def test_customer_wish_rules(api, wish, code):
    customer, pid, did, _ = ready(api)
    assert propose(api, did, *days(14)).status_code == 200
    use(api, customer)
    r = api.post(f"/projects/{pid}/deals/{did}/date-requests", json={"wish_dates": wish})
    assert r.status_code == 422 and r.json()["error"]["code"] == code, r.text


def test_request_needs_dates_first(api):
    customer, pid, did, _ = ready(api)
    use(api, customer)
    r = api.post(f"/projects/{pid}/deals/{did}/date-requests", json={"wish_dates": [days(20)[0]]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "no_dates"


def test_overlap_can_be_sent_but_not_accepted(api):
    customer, pid, did, _ = ready(api)
    mok = workdays(TODAY + timedelta(days=14), 3, OFF)
    mokgong_scheduled(pid, mok[0].isoformat(), mok[-1].isoformat())
    a, b = mok[-1].isoformat(), workdays(mok[-1], 3, OFF)[-1].isoformat()  # 목공 마지막 날에 시작
    pre = api.get(
        f"/vendor/jobs/{did}/dates/preview", params={"start": a, "end": b, "crew": 4}
    ).json()
    after = workdays(mok[-1] + timedelta(days=1), 1, OFF)[0].isoformat()
    assert [c["trade"] for c in pre["fit"]["conflicts"]] == ["mokgong"]
    assert pre["fit"]["start_from"] == after
    r = propose(api, did, a, b)
    assert r.status_code == 200  # 낼 수는 있다
    assert [o["trade"] for o in r.json()["others"]] == ["mokgong"]
    use(api, customer)
    t = api.get(f"/projects/{pid}/schedule").json()["trades"][1]
    assert t["deal"]["trade"] == "dobae" and t["fit"]["conflicts"][0]["vendor_name"] == "바름집수리"
    assert t["start_options"][0]["start"] == after  # 겹치지 않는 첫날부터
    r = api.post(f"/projects/{pid}/deals/{did}/dates/{t['proposal']['id']}/accept", json=SEEN0)
    assert (
        r.status_code == 409
        and r.json()["error"]["message"] == "겹치는 날이 있어 수락할 수 없어요."
    )
    assert query("select status from deals where trade = 'dobae'")[0]["status"] == "confirmed"


@pytest.mark.parametrize("v3", [False, True])
def test_trade_not_in_home_saves_nothing(api, v3):
    """집 정보로 필요한 기간을 못 세는 공정(도배만 고른 집의 목공)은 저장하기 전에 409.
    공사 화면 응답을 못 만드는데 날짜 · 알림만 저장되면 안 된다."""
    _customer, pid, _did, _ = ready(api)
    mok = mokgong_confirmed(pid, listed(api, "barum@mitjip.test", "바름집수리"))  # 업체로 로그인
    picked = workdays(TODAY + timedelta(days=14), 3, OFF)  # 견적서 공사 기간 3일
    over = {"days": [d.isoformat() for d in picked]} if v3 else {}
    r = propose(api, mok, *days(14), **over)
    assert r.status_code == 409 and r.json()["error"]["code"] == "trade", r.text
    assert query("select count(*) n from date_proposals")[0]["n"] == 0
    assert notes("home@mitjip.test", "dates_proposed") == []


def test_overdue_is_not_a_state(api):
    customer, pid, did, _ = ready(api)
    query("update deals set dates_due_at = now() - interval '1 hour'")
    assert api.get(f"/vendor/jobs/{did}").json()["overdue"] is True
    assert api.get("/vendor/visits", params={"tab": "jobs"}).json()["items"][0]["overdue"] is True
    use(api, customer)
    assert sched(api, pid)["deal"]["overdue"] is True
    assert query("select status from deals")[0]["status"] == "confirmed"  # 저절로 취소되지 않는다
    login(api, "maru@mitjip.test")
    assert propose(api, did, *days(14)).json()["overdue"] is False  # 늦게라도 내면 풀린다
    use(api, customer)
    assert (
        api.post(
            f"/projects/{pid}/deals/{did}/date-requests", json={"wish_dates": [days(28)[0]]}
        ).status_code
        == 201
    )
    query("update date_requests set due_at = now() - interval '1 hour'")
    t = sched(api, pid)
    assert t["deal"]["overdue"] is True and t["request"]["overdue"] is True


def test_reselect_closes_dates_and_requests(api):
    customer, pid, did, _ = ready(api)
    propose(api, did, *days(14))
    use(api, customer)
    api.post(f"/projects/{pid}/deals/{did}/date-requests", json={"wish_dates": [days(28)[0]]})
    assert api.post(f"/projects/{pid}/deals/{did}/reselect").status_code == 200
    assert query("select status from date_proposals")[0]["status"] == "withdrawn"
    (r,) = query("select status, closed_at from date_requests")
    assert r["status"] == "withdrawn" and r["closed_at"] is not None
    assert api.get(f"/projects/{pid}/schedule").json()["trades"] == []
    login(api, "maru@mitjip.test")
    late = propose(api, did, *days(14))
    assert (
        late.status_code == 409
        and late.json()["error"]["message"] == "고객이 업체를 다시 고르기로 했어요."
    )


def _run_both(first, second):
    async def both():
        return await asyncio.gather(first(), second(), return_exceptions=True)

    return no_surprises(asyncio.run(both()))


def test_two_accepts_at_once_only_one_wins(api):
    _customer, pid, did, _ = ready(api)
    x = uuid.UUID(propose(api, did, *days(14)).json()["proposal"]["id"])
    me = query("select id from users where email = 'home@mitjip.test'")[0]["id"]

    async def go():
        async with SessionLocal() as s:
            user = await s.get(User, me)
            return await service.accept_dates(
                s, user, uuid.UUID(pid), uuid.UUID(did), x, AcceptIn(seen_version=0), TODAY
            )

    results = _run_both(go, go)
    errors = [r for r in results if isinstance(r, AppError)]
    assert len(errors) == 1 and errors[0].status == 409
    assert query("select count(*) n from deal_events where to_status = 'scheduled'")[0]["n"] == 1
    assert len(query("select id from notifications where kind = 'dates_accepted'")) == 1


def test_accept_and_propose_again_at_once(api):
    _customer, pid, did, _ = ready(api)
    x = uuid.UUID(propose(api, did, *days(14)).json()["proposal"]["id"])
    me = query("select id from users where email = 'home@mitjip.test'")[0]["id"]
    maru = query("select id from users where email = 'maru@mitjip.test'")[0]["id"]
    a, b = days(21)

    async def accept():
        async with SessionLocal() as s:
            user = await s.get(User, me)
            return await service.accept_dates(
                s, user, uuid.UUID(pid), uuid.UUID(did), x, AcceptIn(seen_version=0), TODAY
            )

    async def again():
        async with SessionLocal() as s:
            vendor = await s.get(User, maru)
            data = DatesIn(start=a, end=b, crew=4, method="app")
            return await service.propose_dates(s, vendor, uuid.UUID(did), data, TODAY)

    results = _run_both(accept, again)
    errors = [r for r in results if isinstance(r, AppError)]
    assert len(errors) == 1 and errors[0].status == 409
    assert query("select count(*) n from date_proposals where status = 'pending'")[0]["n"] == (
        0 if errors[0].code == "invalid_state" else 1
    )


def test_only_my_jobs_and_my_home(api):
    customer, pid, did, _ = ready(api)
    x = propose(api, did, *days(14)).json()["proposal"]["id"]
    vendor_calls = (
        lambda: api.get(f"/vendor/jobs/{did}"),
        lambda: propose(api, did, *days(14)),
        lambda: api.get(
            f"/vendor/jobs/{did}/dates/preview",
            params={"start": days(14)[0], "end": days(14)[1], "crew": 4},
        ),
    )
    customer_calls = (
        lambda: api.get(f"/projects/{pid}/schedule"),
        lambda: api.post(f"/projects/{pid}/deals/{did}/dates/{x}/accept", json=SEEN0),
        lambda: api.post(
            f"/projects/{pid}/deals/{did}/date-requests", json={"wish_dates": [days(28)[0]]}
        ),
    )
    login(api, "gyeol@mitjip.test")
    assert all(c().status_code == 404 for c in vendor_calls)  # 다른 업체
    assert all(c().status_code == 403 for c in customer_calls)  # 업체 → 고객 API
    use(api, customer)
    assert all(c().status_code == 403 for c in vendor_calls)  # 고객 → 업체 API
    assert (
        api.post(f"/projects/{pid}/deals/{did}/dates/{uuid.uuid4()}/accept", json=SEEN0).status_code
        == 404
    )
    assert (
        api.post(f"/projects/{pid}/deals/{uuid.uuid4()}/dates/{x}/accept", json=SEEN0).status_code
        == 404
    )
    signup(api, "other@mitjip.test")
    assert all(c().status_code == 404 for c in customer_calls)  # 남의 집
    make_admin(api)
    assert all(c().status_code == 403 for c in customer_calls)  # 관리자
    assert query("select status from deals")[0]["status"] == "confirmed"


SECOND_PENDING = (
    "insert into date_proposals (id, deal_id, start_date, end_date, crew, method)"
    " select gen_random_uuid(), deal_id, start_date, end_date, crew, 'app' from date_proposals"
)
SECOND_OPEN = (
    "insert into date_requests (id, deal_id, wish_dates, due_at)"
    " select gen_random_uuid(), deal_id, wish_dates, due_at from date_requests"
)


@pytest.mark.parametrize(
    ("sql", "error"),
    [
        ("update date_proposals set status = 'lost'", "check"),
        ("update date_proposals set end_date = start_date - 1", "check"),
        ("update date_proposals set end_date = start_date + 121", "check"),
        ("update date_proposals set crew = 0", "check"),
        ("update date_proposals set crew = 21", "check"),
        ("update date_proposals set method = 'call'", "check"),  # 통화한 날 없음
        ("update date_proposals set call_on = current_date", "check"),  # app인데 통화한 날
        ("update date_proposals set kind = 'change'", "check"),  # 바꿀 때는 이유가 있다
        ("update date_proposals set reason = ' '", "check"),
        ("update date_proposals set plan_version = 0", "check"),
        ("update date_proposals set status = 'accepted'", "check"),  # 정한 때 없음
        (SECOND_PENDING, "unique"),
        ("update date_requests set status = 'lost'", "check"),
        ("update date_requests set wish_dates = '{}'", "check"),
        (
            "update date_requests set wish_dates = wish_dates || wish_dates || wish_dates || wish_dates",
            "check",
        ),
        ("update date_requests set reason = ' '", "check"),
        ("update date_requests set status = 'answered'", "check"),  # 닫은 때 없음
        (SECOND_OPEN, "unique"),
        ("update deals set date_request_count = 3", "check"),
    ],
)
def test_dates_db_constraints(api, sql, error):
    customer, pid, did, _ = ready(api)
    propose(api, did, *days(14))
    use(api, customer)
    assert (
        api.post(
            f"/projects/{pid}/deals/{did}/date-requests", json={"wish_dates": [days(28)[0]]}
        ).status_code
        == 201
    )
    wanted = {
        "check": asyncpg.exceptions.CheckViolationError,
        "unique": asyncpg.exceptions.UniqueViolationError,
    }[error]
    with pytest.raises(wanted):
        query(sql)


def test_dates_migration_down_and_up(api):
    from alembic import command
    from alembic.config import Config

    _customer, _pid, did, _ = ready(api)
    propose(api, did, *days(14))
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    try:
        command.downgrade(cfg, "0014_v2_quote_file_share")
        names = {
            r["tablename"]
            for r in query("select tablename from pg_tables where schemaname = 'public'")
        }
        assert not {"date_proposals", "date_requests"} & names
    finally:
        command.upgrade(cfg, "head")
    assert query("select count(*) n from date_proposals")[0]["n"] == 0
    assert query("select status from deals")[0]["status"] == "confirmed"
    assert propose(api, did, *days(14)).status_code == 200
