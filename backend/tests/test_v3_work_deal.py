"""v3 업체 확정 · 다시 고르기 · 공사 날 목록 · 기록 · 캘린더 파일:
확정 때 다른 업체 대화 읽기만 · 기한 일 취소 · 공사 날짜 기한 일, 유효기간 지난 견적서 409, 날 목록 규칙(422),
수락하면 날 목록대로 확정 공정표 · .ics, 기록 탭(고객 · 업체) 권한."""

import asyncio
import uuid
from datetime import date, datetime, timedelta

import redis

from app.auth.models import User
from app.calc.schedule import workdays
from app.db import SessionLocal
from app.jobs import service as jobs
from app.realtime import service as realtime
from app.refprice.holidays import days_off
from app.schedule import service
from app.schedule.schemas import ConfirmIn
from app.shared.clock import today_seoul
from app.thread import service as thread_service
from tests.conftest import REDIS_URL, query
from tests.helpers import signup, use
from tests.test_dates import HOLIDAY, SEEN0, mokgong_scheduled, ready
from tests.test_deal import confirm, setup
from tests.test_visit_inbox import login

TODAY = today_seoul()
OFF = days_off(TODAY, TODAY + timedelta(days=500))


def run(coro):
    return asyncio.run(coro)


def vendor_of(visit_id: str) -> uuid.UUID:
    return query("select vendor_id from visits where id = $1", uuid.UUID(visit_id))[0]["vendor_id"]


def open_thread(pid: str, visit_id: str) -> uuid.UUID:
    """실측이 확정된 것처럼 (공사, 업체) 대화를 연다 (thread.service.open, B1b 계약)"""
    owner = query("select owner_id from projects where id = $1", uuid.UUID(pid))[0]["owner_id"]
    vendor = vendor_of(visit_id)  # query()는 루프 밖에서 (asyncio.run 안에서 다시 부를 수 없다)

    async def go():
        async with SessionLocal() as s:
            tid = await thread_service.open(
                s,
                project_id=uuid.UUID(pid),
                vendor_id=vendor,
                customer_id=owner,
                visit_id=uuid.UUID(visit_id),
                customer_label="상계동 고객",
                vendor_label="업체",
                area_label="노원구 상계동 69.4㎡",
            )
            await s.commit()
            return tid

    return run(go())


def add_job(kind: str, ref, days_later: int = 3) -> None:
    async def go():
        async with SessionLocal() as s:
            at = datetime.now().astimezone() + timedelta(days=days_later)
            assert await jobs.add(s, kind=kind, ref_id=ref, run_at=at)
            await s.commit()

    run(go())


def thread_row(tid) -> dict:
    return dict(query("select status, ro_reason from threads where id = $1", tid)[0])


def cards(tid) -> list[tuple]:
    rows = query(
        "select system_code, ref_id from thread_messages where thread_id = $1 order by seq", tid
    )
    return [(r["system_code"], r["ref_id"]) for r in rows]


def quote_id(visit_id: str) -> uuid.UUID:
    return query("select id from vendor_quotes where visit_id = $1", uuid.UUID(visit_id))[0]["id"]


def stream(user_id) -> list[tuple[bytes, bytes]]:
    sync = redis.Redis.from_url(REDIS_URL)
    return [(i[1][b"e"], i[1][b"d"]) for i in sync.xrange(realtime.stream_key(user_id))]


def test_confirm_v3_reads_only_other_threads_cancels_jobs_and_adds_dates_due(api):
    customer, pid, va, vb, vc = setup(api)
    tids = {v: open_thread(pid, v) for v in (va, vb, vc)}
    query("update projects set emd = '상계동'")
    add_job("visit_quote_due", uuid.UUID(vb))
    add_job("quote_valid_soon", quote_id(vb))
    add_job("quote_valid_soon", quote_id(va))
    add_job("visit_reply_due", uuid.UUID(vc))
    r = confirm(api, pid, va)
    assert r.status_code == 200, r.text
    deal = r.json()["deal"]
    did = uuid.UUID(deal["id"])
    assert deal["thread_id"] == str(tids[va])

    assert thread_row(tids[va]) == {"status": "open", "ro_reason": None}
    (note,) = query("select body from notifications where kind = 'deal_confirmed'")
    assert (
        note["body"] == "고객이 확정했어요 · 공사 날짜를 내 주세요 · 노원구 상계동 도배"
    )  # 공사 이름
    assert cards(tids[va]) == [("deal_confirmed", did)]
    for v in (vb, vc):  # 다른 업체 대화는 읽기만 + 시스템 카드 한 줄
        assert thread_row(tids[v]) == {"status": "read_only", "ro_reason": "other_chosen"}
        assert cards(tids[v]) == [("other_chosen", uuid.UUID(v))]
    rows = {
        (r["kind"], r["ref_id"]): r for r in query("select kind, ref_id, status, run_at from jobs")
    }
    for key in (
        ("visit_quote_due", uuid.UUID(vb)),
        ("quote_valid_soon", quote_id(vb)),
        ("quote_valid_soon", quote_id(va)),
        ("visit_reply_due", uuid.UUID(vc)),
    ):
        assert rows[key]["status"] == "cancelled", key
    due = rows[("deal_dates_due", did)]
    assert due["status"] == "pending"
    assert due["run_at"] == datetime.fromisoformat(deal["dates_due_at"])
    # commit 뒤 신호: 확정 업체에는 deal, 닫힌 업체에는 visit state + 안 읽은 수
    events = stream(vendor_of(va))
    assert any(e == b"state" and b'"deal"' in d for e, d in events)
    assert any(e == b"notif" for e, _ in events)
    assert any(e == b"state" and b'"visit"' in d for e, d in stream(vendor_of(vb)))
    # 시스템 카드는 두 사람 줄기에 msg (thread.service.notify_message)
    assert any(e == b"msg" and str(tids[vb]).encode() in d for e, d in stream(vendor_of(vb)))
    assert any(e == b"msg" and str(tids[va]).encode() in d for e, d in stream(vendor_of(va)))
    assert customer


def test_direct_service_call_only_keeps_signals_for_the_router(api):
    """service를 바로 부르면(시연 데이터 · asyncio.run) 신호는 세션에 남기만 하고 Redis를 건드리지 않는다
    (다른 이벤트 루프의 연결을 공용 연결 묶음에 남기지 않게). 보내기는 router Session의 flush_later."""
    _, pid, va, _, _ = setup(api)
    me = query("select owner_id from projects")[0]["owner_id"]
    vendor = vendor_of(va)
    before = stream(vendor)

    async def go():
        async with SessionLocal() as s:
            user = await s.get(User, me)
            await service.confirm(
                s, user, uuid.UUID(pid), uuid.UUID(va), ConfirmIn(seen_ver=1), TODAY
            )
            return len(s.info.get(service.LATER, []))

    assert run(go()) == 1  # commit 뒤 신호 한 묶음
    assert stream(vendor) == before  # 보내지 않았다
    assert query("select count(*) n from deals")[0]["n"] == 1


def test_confirm_with_expired_quote_is_409_and_changes_nothing(api):
    customer, pid, va, _, _ = setup(api)
    query(  # 어제까지 (실측한 날과 같아 CHECK valid_until >= measured_on은 지킨다)
        "update vendor_quotes set valid_until = $1 where visit_id = $2",
        TODAY - timedelta(days=1),
        uuid.UUID(va),
    )
    r = confirm(api, pid, va)
    assert r.status_code == 409 and r.json()["error"]["code"] == "expired"
    assert "다시 받기" in r.json()["error"]["message"]
    assert query("select status from visits where id = $1", uuid.UUID(va))[0][0] == "quoted"
    assert query("select count(*) n from deals")[0]["n"] == 0
    assert query("select count(*) n from jobs where kind = 'deal_dates_due'")[0]["n"] == 0
    assert customer


def test_reselect_v3_reads_only_the_thread_and_cancels_deal_jobs(api):
    customer, pid, va, _, _ = setup(api)
    tid = open_thread(pid, va)
    did = confirm(api, pid, va).json()["deal"]["id"]
    r = api.post(f"/projects/{pid}/deals/{did}/reselect")
    assert r.status_code == 200, r.text
    assert thread_row(tid) == {"status": "read_only", "ro_reason": "cancelled"}
    (job,) = query("select status from jobs where kind = 'deal_dates_due'")
    assert job["status"] == "cancelled"
    codes = [r["code"] for r in query("select code from deal_events order by at")]
    assert codes == ["confirmed", "reselected"]
    again = api.post(f"/projects/{pid}/deals/{did}/reselect")
    assert again.status_code == 409
    assert customer


# ---- 공사 날 목록 (V11 · C35, api.md 11장) ----


def picked() -> list[date]:
    """2주 뒤 일하는 날 4개 중 셋째 날을 뺀 3일 (견적서 공사 기간 3일, 사이에 쉬는 날)"""
    got = workdays(TODAY + timedelta(days=14), 4, OFF)
    return [got[0], got[1], got[3]]


def post_days(api, did: str, days: list[date], **over):
    body = {"days": [d.isoformat() for d in days], "crew": 2, **over}
    return api.post(f"/vendor/jobs/{did}/dates", json=body)


def test_day_list_rules_are_422_on_days(api):
    _, _, did, _ = ready(api)
    first, second, last = picked()
    sat = TODAY + timedelta(days=(5 - TODAY.weekday()) % 7 or 7)
    far = workdays(first + timedelta(days=125), 1, OFF)[0]
    bad = {
        "count": [first, second],  # 견적서 공사 기간 3일과 다름
        "weekend": [first, second, sat],
        "holiday": [first, second, HOLIDAY],
        "today": [TODAY, first, second],
        "span": [first, second, far],
    }
    for name, days in bad.items():
        r = post_days(api, did, days)
        assert r.status_code == 422, (name, r.text)
        assert r.json()["error"]["fields"][0]["loc"] == ["days"], name
    assert (
        "견적서 공사 기간(3일)" in post_days(api, did, [first, second]).json()["error"]["message"]
    )
    dup = post_days(api, did, [first, first, second])
    assert dup.status_code == 422  # 같은 날 두 번 (몸통 검사)
    assert api.post(f"/vendor/jobs/{did}/dates", json={"crew": 2}).status_code == 422
    assert query("select count(*) n from date_proposals")[0]["n"] == 0

    r = post_days(api, did, [last, first, second])  # 순서는 서버가 맞춘다
    assert r.status_code == 200, r.text
    x = r.json()["proposal"]
    assert x["days"] == [d.isoformat() for d in (first, second, last)]
    assert (x["start"], x["end"], x["workdays"]) == (first.isoformat(), last.isoformat(), 3)
    assert r.json()["dates_state"] == "proposed"


def test_day_list_overlapping_another_trade_is_422(api):
    _, pid, did, _ = ready(api)
    first, second, last = picked()
    mokgong_scheduled(pid, first.isoformat(), second.isoformat())  # 목공이 같은 날에
    r = post_days(api, did, [first, second, last])
    assert r.status_code == 422 and r.json()["error"]["fields"][0]["loc"] == ["days"]
    assert "겹치는 날" in r.json()["error"]["message"]


def test_accepting_a_day_list_fixes_work_days_plan_and_calendar(api):
    customer, pid, did, _ = ready(api)
    first, second, last = picked()
    x = post_days(api, did, [first, second, last]).json()["proposal"]["id"]
    use(api, customer)
    picked_days = [d.isoformat() for d in (first, second, last)]
    todo = api.get(f"/projects/{pid}/overview").json()["todo"]
    assert (todo["code"], todo["days"]) == ("dates_received", picked_days)  # C43 할 일 아래 날
    before = datetime.now().astimezone()
    preview = api.get(f"/projects/{pid}/schedule").json()["request_due_preview"]
    due = datetime.fromisoformat(preview)  # C52: 지금 요청하면 업체가 올릴 기한 (요청 + 48시간)
    assert (
        before + timedelta(hours=47, minutes=59)
        <= due
        <= datetime.now().astimezone() + timedelta(hours=48)
    )
    assert api.get(f"/projects/{pid}/plan.ics").status_code == 404  # 확정 전
    r = api.post(f"/projects/{pid}/deals/{did}/dates/{x}/accept", json=SEEN0)
    assert r.status_code == 200, r.text
    (t,) = r.json()["trades"]
    assert t["deal"]["work_days"] == picked_days
    todo = api.get(f"/projects/{pid}/overview").json()["todo"]
    assert (todo["code"], todo["days"]) == ("before_work", picked_days)
    plan = api.get(f"/projects/{pid}/plan").json()
    assert plan["kind"] == "final"
    by_day = {d["day"]: d for d in plan["days"]}
    gap = workdays(TODAY + timedelta(days=14), 4, OFF)[2]  # 고른 날 사이 빠진 일하는 날
    for d in (first, second, last):
        assert (by_day[d.isoformat()]["kind"], by_day[d.isoformat()]["trade"]) == ("work", "dobae")
    assert by_day[gap.isoformat()]["kind"] == "off"
    dobae = next(b for b in plan["blocks"] if b["trade"] == "dobae")
    assert (dobae["start"], dobae["end"], dobae["days"]) == (
        first.isoformat(),
        last.isoformat(),
        3,
    )

    ics = api.get(f"/projects/{pid}/plan.ics")
    assert ics.status_code == 200 and ics.headers["content-type"].startswith("text/calendar")
    assert "attachment" in ics.headers["content-disposition"]
    text = ics.text
    assert text.startswith("BEGIN:VCALENDAR\r\n") and text.endswith("END:VCALENDAR\r\n")
    starts = [ln.split(":")[1] for ln in text.split("\r\n") if ln.startswith("DTSTART")]
    assert starts == [f"{d:%Y%m%d}" for d in (first, second, last)]
    assert text.count("BEGIN:VEVENT") == 3 and "도배 공사" in text
    assert "상계주공" not in text and "1203호" not in text  # 주소 · 동 · 호 없음
    login(api, "maru@mitjip.test")
    job = api.get(f"/vendor/jobs/{did}").json()
    assert job["work_days"] == [d.isoformat() for d in (first, second, last)]
    assert api.get(f"/projects/{pid}/plan.ics").status_code == 403  # 업체가 고객 경로
    signup(api, "other@mitjip.test")
    assert api.get(f"/projects/{pid}/plan.ics").status_code == 404  # 남의 집


def test_log_tab_for_customer_and_vendor(api):
    customer, pid, va, vb, vc = setup(api)
    did = confirm(api, pid, va).json()["deal"]["id"]
    login(api, "maru@mitjip.test")
    first, second, last = picked()
    x = post_days(api, did, [first, second, last]).json()["proposal"]["id"]
    use(api, customer)
    assert api.post(f"/projects/{pid}/deals/{did}/dates/{x}/accept", json=SEEN0).status_code == 200

    log = api.get(f"/projects/{pid}/log").json()
    ats = [datetime.fromisoformat(i["at"]) for i in log]
    assert ats == sorted(ats)  # 시간 순
    codes = [i["code"] for i in log]
    assert codes.count("asked") == 3
    sent = [i for i in log if i["code"] == "quote_sent"]
    assert sorted(i["amount"] for i in sent) == [3_388_000, 3_762_000]
    assert {i["actor"] for i in sent} == {"vendor"}
    assert {i["actor"] for i in log if i["code"] == "asked"} == {"customer"}
    # 업체 확정은 한 줄(확정 이력 confirmed). 같은 요청의 '골랐어요'(chosen)는 남기지 않는다
    assert codes.count("other_chosen") == 2 and "chosen" not in codes
    assert codes.count("confirmed") == 1
    dates = next(i for i in log if i["code"] == "dates_sent")
    assert (dates["day"], dates["day_to"], dates["vendor_name"]) == (
        first.isoformat(),
        last.isoformat(),
        "마루와벽",
    )
    assert dates["days"] == [d.isoformat() for d in (first, second, last)]  # 날 목록 (C63)
    assert codes[-1] == "dates_accepted"

    # 업체가 다른 날 반나절 둘을 제안한 기록 (visit 흐름 대신 표에 바로): 두 칸 = day · half · day_to · half_to
    s1, s2 = TODAY + timedelta(days=10), TODAY + timedelta(days=11)
    (prop,) = query(
        "insert into visit_proposals (id, visit_id, reason_code, status, due_at) values"
        " (gen_random_uuid(), $1, 'other_site', 'open', now() + interval '48 hours') returning id",
        uuid.UUID(vc),
    )
    for day, half in ((s2, "am"), (s1, "pm")):
        query(
            "insert into visit_proposal_slots (proposal_id, day, half) values ($1, $2, $3)",
            prop["id"],
            day,
            half,
        )
    query(
        "insert into visit_events (id, visit_id, from_status, to_status, code, day, half)"
        " values (gen_random_uuid(), $1, 'picked', 'proposed', 'proposed', $2, 'pm')",
        uuid.UUID(vc),
        s1,
    )
    (slot,) = [i for i in api.get(f"/projects/{pid}/log").json() if i["code"] == "proposed"]
    assert (slot["day"], slot["half"], slot["day_to"], slot["half_to"]) == (
        s1.isoformat(),
        "pm",
        s2.isoformat(),
        "am",
    )

    login(api, "maru@mitjip.test")
    mine = api.get(f"/vendor/jobs/{did}/log").json()
    assert {i["vendor_name"] for i in mine} == {"마루와벽"}  # 다른 업체 기록은 안 보인다
    assert [i["code"] for i in mine].count("asked") == 1
    assert api.get(f"/projects/{pid}/log").status_code == 403  # 업체가 고객 경로
    login(api, "gyeol@mitjip.test")
    assert api.get(f"/vendor/jobs/{did}/log").status_code == 404  # 다른 업체 공사
    use(api, customer)
    assert api.get(f"/vendor/jobs/{did}/log").status_code == 403  # 고객이 업체 경로
    signup(api, "other@mitjip.test")
    assert api.get(f"/projects/{pid}/log").status_code == 404  # 남의 집
    assert vb and vc
