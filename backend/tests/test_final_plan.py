"""확정 공정표 · 수락한 날짜 바꾸기: 수락마다 새 버전, 본 버전 409, 바꾸기 요청 · 새 날짜 · 수락, 겹침, 끝난 뒤 막기."""

import asyncio
import uuid
from datetime import date, timedelta

import asyncpg
import pytest

from app.auth.models import User
from app.calc.schedule import workdays
from app.db import SessionLocal
from app.refprice.holidays import days_off
from app.schedule import service
from app.schedule.schemas import AcceptIn
from app.shared.clock import today_seoul
from app.shared.errors import AppError
from tests.conftest import BACKEND, query
from tests.helpers import no_surprises, signup, use
from tests.test_deal import confirm
from tests.test_project import body as project_body
from tests.test_quote_compare import quote
from tests.test_visit_inbox import login
from tests.test_visit_request import SHARE, listed, send
from tests.test_visit_vendors import NOWON_32

TODAY = today_seoul()
OFF = days_off(TODAY, TODAY + timedelta(days=400))
BOTH = {
    "dobae": {"spaces": ["a", "b", "c"], "grade": "basic"},
    "mokgong": {"spaces": ["a"], "items": ["molding", "base"]},
}


def run(start: date, n: int = 3) -> tuple[date, date]:
    got = workdays(start, n, OFF)
    return got[0], got[-1]


def after(d: date, n: int = 3) -> tuple[date, date]:
    return run(d + timedelta(days=1), n)


MOK = run(TODAY + timedelta(days=14))
DOB = after(MOK[1])


def visit_of(pid: str, trade: str) -> str:
    rows = query(
        "select id from visits where project_id = $1 and trade = $2", uuid.UUID(pid), trade
    )
    return str(rows[0]["id"])


def two(api):
    """목공(바름집수리) · 도배(마루와벽)를 확정한 집. (고객 토큰, 프로젝트, 목공 확정, 도배 확정)"""
    m = listed(api, "barum@mitjip.test", "바름집수리", trades=["mokgong"])
    a = listed(api, "maru@mitjip.test", "마루와벽")
    customer = signup(api, "home@mitjip.test")
    pid = api.post("/projects", json=project_body(**{**NOWON_32, "trades": BOTH})).json()["id"]
    assert send(api, pid, [a], share_contact_ids=[a], **SHARE).status_code == 201
    assert send(api, pid, [m], trade="mokgong").status_code == 201
    vm, vd = visit_of(pid, "mokgong"), visit_of(pid, "dobae")
    login(api, "barum@mitjip.test")
    quote(api, vm, 1_200_000)
    login(api, "maru@mitjip.test")
    quote(api, vd, 3_080_000)
    use(api, customer)
    dm = confirm(api, pid, vm).json()["deal"]["id"]
    dd = confirm(api, pid, vd).json()["deal"]["id"]
    return customer, pid, dm, dd


def propose(api, email: str, did: str, dates: tuple[date, date], **over):
    login(api, email)
    r = api.post(
        f"/vendor/jobs/{did}/dates",
        json={
            "start": dates[0].isoformat(),
            "end": dates[1].isoformat(),
            "crew": 4,
            "method": "app",
            **over,
        },
    )
    return r


def accept(api, pid: str, did: str, xid: str, seen: int):
    return api.post(f"/projects/{pid}/deals/{did}/dates/{xid}/accept", json={"seen_version": seen})


def proposal_of(api, email: str, did: str, dates, **over) -> str:
    r = propose(api, email, did, dates, **over)
    assert r.status_code == 200, r.text
    return r.json()["proposal"]["id"]


def steps(version: int) -> list[tuple]:
    rows = query(
        "select st.trade, st.kind, st.start_date, st.end_date, st.deal_id from plan_steps st"
        " join plans p on p.id = st.plan_id where p.kind = 'final' and p.version = $1"
        " order by st.sort",
        version,
    )
    return [(r["trade"], r["kind"], r["start_date"], r["end_date"], r["deal_id"]) for r in rows]


def both_accepted(api):
    customer, pid, dm, dd = two(api)
    xm = proposal_of(api, "barum@mitjip.test", dm, MOK)
    xd = proposal_of(api, "maru@mitjip.test", dd, DOB)
    use(api, customer)
    assert accept(api, pid, dm, xm, 0).status_code == 200
    assert accept(api, pid, dd, xd, 1).status_code == 200
    return customer, pid, dm, dd


def test_each_accept_makes_a_new_final_version(api):
    customer, pid, dm, dd = two(api)
    xm = proposal_of(api, "barum@mitjip.test", dm, MOK)
    xd = proposal_of(api, "maru@mitjip.test", dd, DOB)
    use(api, customer)
    assert api.get(f"/projects/{pid}/plan").json()["kind"] == "expected"
    assert api.get(f"/projects/{pid}/plan", params={"kind": "final"}).status_code == 404
    assert api.get(f"/projects/{pid}/schedule").json()["final_version"] == 0

    r = accept(api, pid, dm, xm, 0)
    assert r.status_code == 200, r.text
    assert r.json()["final_version"] == 1
    got = steps(1)
    assert [(t, k) for t, k, *_ in got] == [
        ("mokgong", "work"),
        ("dobae", "work"),
        (None, "dry"),
        (None, "clean"),
    ]
    assert got[0][2:] == (*MOK, uuid.UUID(dm)) and got[1][4] is None  # 도배는 아직 날짜 없음(예상)
    assert got[1][2] == after(MOK[1])[0]  # 목공 다음 일하는 날부터 예상 자리

    plan = api.get(f"/projects/{pid}/plan").json()
    assert (plan["kind"], plan["version"]) == ("final", 1)
    blocks = {b["trade"] or b["kind"]: b for b in plan["blocks"]}
    assert (blocks["mokgong"]["state"], blocks["mokgong"]["vendor_name"]) == (
        "confirmed",
        "바름집수리",
    )
    assert (blocks["dobae"]["state"], blocks["dobae"]["start"], blocks["dobae"]["end"]) == (
        "pending",  # 수락 전: 마루와벽이 낸 날짜
        DOB[0].isoformat(),
        DOB[1].isoformat(),
    )
    assert (
        blocks["dry"]["state"] == "expected"
        and blocks["dry"]["start"] == (DOB[1] + timedelta(days=1)).isoformat()
    )
    days = {d["day"]: d for d in plan["days"]}
    assert days[MOK[0].isoformat()]["state"] == "confirmed"
    assert days[DOB[0].isoformat()]["state"] == "pending"
    assert plan["changes"] == []
    assert (
        api.get(f"/projects/{pid}/plan", params={"kind": "expected"}).json()["kind"] == "expected"
    )

    stale = accept(api, pid, dd, xd, 0)  # 목공 수락 전 화면에서 누름
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "plan_changed"
    assert query("select status from deals where trade = 'dobae'")[0]["status"] == "confirmed"
    ok = accept(api, pid, dd, xd, 1)
    assert ok.status_code == 200 and ok.json()["final_version"] == 2
    got = steps(2)
    assert got[1][2:] == (*DOB, uuid.UUID(dd))
    plan = api.get(f"/projects/{pid}/plan").json()
    assert {b["state"] for b in plan["blocks"] if b["kind"] == "work"} == {"confirmed"}
    assert (plan["version"], plan["start"]) == (2, MOK[0].isoformat())
    assert query("select count(*) n from plans where kind = 'final'")[0]["n"] == 2


def test_two_trades_accepted_at_once_one_409(api):
    customer, pid, dm, dd = two(api)
    xm = uuid.UUID(proposal_of(api, "barum@mitjip.test", dm, MOK))
    xd = uuid.UUID(proposal_of(api, "maru@mitjip.test", dd, DOB))
    use(api, customer)
    api.get(f"/projects/{pid}/schedule")
    me = query("select id from users where email = 'home@mitjip.test'")[0]["id"]

    def go(did, xid):
        async def call():
            async with SessionLocal() as s:
                user = await s.get(User, me)
                return await service.accept_dates(
                    s, user, uuid.UUID(pid), uuid.UUID(did), xid, AcceptIn(seen_version=0), TODAY
                )

        return call

    async def both():
        return await asyncio.gather(go(dm, xm)(), go(dd, xd)(), return_exceptions=True)

    results = no_surprises(asyncio.run(both()))
    errors = [r for r in results if isinstance(r, AppError)]
    assert len(errors) == 1 and (errors[0].status, errors[0].code) == (409, "plan_changed")
    assert query("select count(*) n from plans where kind = 'final'")[0]["n"] == 1
    assert query("select count(*) n from deals where status = 'scheduled'")[0]["n"] == 1


def test_change_request_new_dates_then_accept(api):
    customer, pid, _dm, dd = both_accepted(api)
    url = f"/projects/{pid}/deals/{dd}/date-requests"
    w1, w2 = run(DOB[0] + timedelta(days=7), 2)
    no_reason = api.post(url, json={"wish_dates": [w1.isoformat()]})
    assert no_reason.status_code == 422 and no_reason.json()["error"]["code"] == "reason"
    r = api.post(
        url,
        json={"wish_dates": [w1.isoformat(), w2.isoformat()], "reason": "이사 일정이 늦어졌어요."},
    )
    assert r.status_code == 201, r.text
    t = r.json()["trades"][1]
    assert (t["dates_state"], t["deal"]["start_date"]) == ("change_requested", DOB[0].isoformat())
    assert len(t["start_options"]) == 5

    login(api, "maru@mitjip.test")
    job = api.get(f"/vendor/jobs/{dd}").json()
    assert job["dates_state"] == "change_requested"
    opts = [(o["start"], o["end"]) for o in job["request_options"]]
    e1, e2 = workdays(w1, 3, OFF)[-1], workdays(w2, 3, OFF)[-1]  # 지금과 같은 3일
    assert opts == [(w1.isoformat(), e1.isoformat()), (w2.isoformat(), e2.isoformat())]
    (row,) = [x for x in api.get("/vendor/visits", params={"tab": "jobs"}).json()["items"]]
    assert (row["dates_state"], row["wish_dates"]) == (
        "change_requested",
        [w1.isoformat(), w2.isoformat()],
    )
    wrong = propose(api, "maru@mitjip.test", dd, after(w2), kind="change")
    assert wrong.status_code == 422 and wrong.json()["error"]["code"] == "request_dates"
    r = propose(api, "maru@mitjip.test", dd, (w1, e1), kind="change")
    assert r.status_code == 200, r.text
    x = r.json()["proposal"]
    assert (x["kind"], x["reason"], r.json()["dates_state"]) == ("change", None, "change_proposed")
    assert query("select status from date_requests")[0]["status"] == "answered"
    (n,) = query(
        "select body, link from notifications where kind = 'dates_proposed' order by created_at desc limit 1"
    )
    assert (n["body"], n["link"]) == (
        "마루와벽이 새 도배 날짜를 올렸어요",
        f"/projects/{pid}/schedule?view=dates",
    )

    use(api, customer)
    assert (
        query("select start_date from deals where trade = 'dobae'")[0][0] == DOB[0]
    )  # 수락 전엔 그대로
    plan = api.get(f"/projects/{pid}/plan").json()
    dob = next(b for b in plan["blocks"] if b["trade"] == "dobae")
    assert (dob["state"], dob["start"]) == ("confirmed", DOB[0].isoformat())
    (ch,) = plan["changes"]
    assert (ch["current_start"], ch["proposal"]["start"], ch["fit"]["conflicts"]) == (
        DOB[0].isoformat(),
        w1.isoformat(),
        [],
    )
    moved = {b["trade"] or b["kind"]: b for b in ch["blocks"]}
    assert (
        moved["dobae"]["state"] == "pending"
        and moved["dry"]["start"] == (e1 + timedelta(days=1)).isoformat()
    )
    assert ch["end"] > plan["end"]  # 건조 · 청소도 같이 밀린다

    ok = accept(api, pid, dd, x["id"], 2)
    assert ok.status_code == 200, ok.text
    (d,) = query("select status, start_date, end_date from deals where trade = 'dobae'")
    assert (d["status"], d["start_date"], d["end_date"]) == ("scheduled", w1, e1)
    (ev,) = query("select from_status, to_status, note from deal_events where note is not null")
    assert (ev["from_status"], ev["to_status"]) == ("scheduled", "scheduled")
    assert ev["note"] == f"날짜 바꿈 {DOB[0]}~{DOB[1]} → {w1}~{e1}"
    assert steps(3)[1][2:4] == (w1, e1)
    (n,) = query(
        "select body from notifications where kind = 'dates_accepted' order by created_at desc limit 1"
    )
    assert n["body"] == "고객이 새 공사 날짜를 수락했어요 · 노원구 도배"  # v3: 공사 이름
    assert api.get(f"/projects/{pid}/plan").json()["changes"] == []


def test_vendor_change_needs_reason_and_overlap_blocks_accept(api):
    customer, pid, dm, dd = both_accepted(api)
    plain = propose(api, "maru@mitjip.test", dd, after(DOB[1]))
    assert (
        plain.status_code == 409
        and plain.json()["error"]["message"] == "고객이 이미 공사 날짜를 수락했어요."
    )
    no_reason = propose(api, "maru@mitjip.test", dd, after(DOB[1]), kind="change")
    assert no_reason.status_code == 422 and no_reason.json()["error"]["code"] == "reason"
    early = propose(api, "barum@mitjip.test", dm, MOK, kind="change", reason=" ")
    assert early.status_code == 422  # 빈 이유
    # 도배를 목공 마지막 날로 당기면 겹친다: 낼 수는 있고 수락은 막는다
    bad = (MOK[1], workdays(MOK[1], 3, OFF)[-1])
    r = propose(api, "maru@mitjip.test", dd, bad, kind="change", reason="자재가 일찍 와요.")
    assert r.status_code == 200, r.text
    (n,) = query(
        "select body from notifications where kind = 'dates_proposed' order by created_at desc limit 1"
    )
    assert n["body"] == "마루와벽이 도배 날짜를 바꾸자고 했어요"
    use(api, customer)
    (ch,) = api.get(f"/projects/{pid}/plan").json()["changes"]
    assert [c["trade"] for c in ch["fit"]["conflicts"]] == ["mokgong"]
    no = accept(api, pid, dd, r.json()["proposal"]["id"], 2)
    assert no.status_code == 409 and no.json()["error"]["code"] == "overlap"
    assert query("select start_date from deals where trade = 'dobae'")[0][0] == DOB[0]


def test_mokgong_choices_end_before_accepted_dobae(api):
    customer, pid, dm, dd = two(api)
    w = workdays(TODAY + timedelta(days=1), 6, OFF)  # 내일부터 일하는 날 6개
    dob = run(w[5])  # 도배를 6번째 일하는 날부터 먼저 수락한다
    xd = proposal_of(api, "maru@mitjip.test", dd, dob)
    use(api, customer)
    assert accept(api, pid, dd, xd, 0).status_code == 200
    mok = after(dob[1])  # 목공은 도배 뒤로 냈다 (낼 수는 있고 수락은 못 한다)
    proposal_of(api, "barum@mitjip.test", dm, mok)
    use(api, customer)
    t = api.get(f"/projects/{pid}/schedule").json()["trades"][0]
    assert t["deal"]["trade"] == "mokgong" and [c["trade"] for c in t["fit"]["conflicts"]] == [
        "dobae"
    ]
    # 3일짜리 목공 후보는 도배 시작 전날까지 끝나는 것만 (5개를 채우지 않는다)
    assert [(o["start"], o["end"]) for o in t["start_options"]] == [
        (w[0].isoformat(), w[2].isoformat()),
        (w[1].isoformat(), w[3].isoformat()),
        (w[2].isoformat(), w[4].isoformat()),
    ]
    url = f"/projects/{pid}/deals/{dm}/date-requests"
    bad = api.post(url, json={"wish_dates": [w[3].isoformat()]})  # 끝나는 날이 도배 첫날
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "wish_dates"
    assert query("select count(*) from date_requests")[0][0] == 0
    ok = api.post(url, json={"wish_dates": [w[0].isoformat(), w[2].isoformat()]})
    assert ok.status_code == 201, ok.text


def test_requests_are_two_in_total_and_closed_after_work_done(api):
    customer, pid, dm, dd = both_accepted(api)
    url = f"/projects/{pid}/deals/{dd}/date-requests"
    for k in (1, 2):
        w = run(DOB[0] + timedelta(days=7 * k), 1)[0]
        assert (
            api.post(
                url, json={"wish_dates": [w.isoformat()], "reason": "사정이 생겼어요."}
            ).status_code
            == 201
        )
        login(api, "maru@mitjip.test")
        assert (
            propose(
                api, "maru@mitjip.test", dd, (w, workdays(w, 3, OFF)[-1]), kind="change"
            ).status_code
            == 200
        )
        use(api, customer)
    third = api.post(
        url,
        json={
            "wish_dates": [run(DOB[0] + timedelta(days=30), 1)[0].isoformat()],
            "reason": "또요.",
        },
    )
    assert third.status_code == 409 and third.json()["error"]["code"] == "requests_used"
    # 업체가 '공사 끝냈어요'를 올린 뒤(24번)에는 날짜를 바꾸지 않는다
    query(
        "update deals set status = 'checking', work_done_on = current_date where trade = 'mokgong'"
    )
    r = api.post(
        f"/projects/{pid}/deals/{dm}/date-requests",
        json={"wish_dates": [DOB[0].isoformat()], "reason": "x"},
    )
    assert (
        r.status_code == 409
        and r.json()["error"]["message"] == "공사를 끝냈다고 올린 뒤에는 날짜를 바꿀 수 없어요."
    )
    late = propose(api, "barum@mitjip.test", dm, after(DOB[1]), kind="change", reason="미뤄요.")
    assert late.status_code == 409


def test_plan_is_only_for_the_owner(api):
    customer, pid, _dm, _dd = both_accepted(api)
    login(api, "maru@mitjip.test")
    assert api.get(f"/projects/{pid}/plan").status_code == 404  # 업체도 고객 공정표는 못 본다
    signup(api, "other@mitjip.test")
    assert api.get(f"/projects/{pid}/plan").status_code == 404
    use(api, customer)
    assert api.get(f"/projects/{pid}/plan", params={"kind": "draft"}).status_code == 422


def test_change_migration_down_and_up(api):
    from alembic import command
    from alembic.config import Config

    _customer, pid, _dm, dd = both_accepted(api)
    w = run(DOB[0] + timedelta(days=7), 1)[0]
    api.post(
        f"/projects/{pid}/deals/{dd}/date-requests",
        json={"wish_dates": [w.isoformat()], "reason": "이사가 늦어요."},
    )
    assert (
        propose(
            api, "maru@mitjip.test", dd, (w, workdays(w, 3, OFF)[-1]), kind="change"
        ).status_code
        == 200
    )
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    try:
        command.downgrade(cfg, "0015_v2_dates")
        # 예전 규칙: 바꿀 때는 이유 필수 → 요청의 이유를 옮겨 적는다
        assert (
            query("select reason from date_proposals where kind = 'change'")[0][0]
            == "이사가 늦어요."
        )
        with pytest.raises(asyncpg.exceptions.CheckViolationError):
            query("update date_proposals set reason = null where kind = 'change'")
    finally:
        command.upgrade(cfg, "head")
    query(
        "update date_proposals set reason = null where kind = 'change'"
    )  # 요청에 답한 것은 이유 없이
    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        query("update date_proposals set reason = null, request_id = null where kind = 'change'")
