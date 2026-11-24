"""점검 고침 X4(상태 흐름 · 세션, 2026-11-24 점검 R3 · R4).

- R3#1 = R4#1: 읽기 중 표준견적서 · 예상 공정표 저장이 동시 저장에 지면 세션 전체를 되돌려 먼저 읽은 객체가
  만료(MissingGreenlet 500)되던 것. 두 요청이 같은 낡은 판을 본 뒤에야 저장하게 맞춰(_meet) 진짜로 겹치게 한다.
- R4#2 · #7 기한 일 이름 · R4#3 숨긴 리뷰 다시 쓰기 · R4#4 멈춤 풀기 대화 · R4#5 옛 취소 잠금 ·
  R4#6 추천 칸 · R4#9 은행 낱말 · R4#10 조사 · R4#11 늦은 전날 알림
- R3#2 철거 범위 판 · R3#3 주방 방문 · R3#4 링크 신고 숨김
합성 데이터만 쓴다.
"""

import asyncio
import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from types import SimpleNamespace as N

from app.auth.models import User
from app.calc import deadline
from app.calc.common import FORMULA_VERSION
from app.db import SessionLocal
from app.project import service as project_service
from app.quote import service as quote_service
from app.schedule import service as schedule_service
from app.schedule.schemas import AcceptIn, DateRequestIn, DatesIn
from app.shared.clock import SEOUL, now_utc, today_seoul
from app.shared.ids import uuid7
from app.thread import rules
from app.visit import flow
from app.visit import service as visit_service
from app.visit.schemas import VisitCreateIn
from tests import test_final_plan as fp
from tests.conftest import query
from tests.helpers import make_admin, no_surprises, signup, use
from tests.test_project import body as project_body
from tests.test_v3_project_home import HOME, create
from tests.test_v3_review_api import LINK, deal_for, write
from tests.test_v3_thread_api import pair, send
from tests.test_v3_visit_kit import (
    add,
    answer,
    ask,
    booked,
    changed,
    choose,
    customer,
    d,
    day,
    handle,
    notes,
    pending_jobs,
    quiet,
    requested,
    run,
    status,
    user_id,
    vendor,
    visit_of,
    with_user,
)
from tests.test_v4_standard_profile import _dobae, _keys, _say
from tests.test_visit_inbox import login
from tests.test_visit_vendors import NOWON_32

# ---- R3#1 = R4#1: 읽기 중 저장이 동시 저장에 져도 세션 객체가 살아 있다 ----


def _meet(monkeypatch, mod, kind: str | None = None, n: int = 2) -> None:
    """요청마다 처음 읽는 저장본(mod._latest, kind를 주면 그 종류) 뒤에서 n개가 모일 때까지 기다린다.
    모두 같은 낡은 판을 본 뒤에 새 판을 넣으니 늦은 쪽은 고유 제약에 걸린다(진 쪽). n개가 지나간 뒤는 그대로."""
    real = mod._latest
    gate = asyncio.Barrier(n)
    seen: set = set()

    async def meet(s, project_id, *rest):
        got = await real(s, project_id, *rest)
        task = asyncio.current_task()
        if (kind is None or rest[:1] == (kind,)) and task not in seen and len(seen) < n:
            seen.add(task)
            await asyncio.wait_for(gate.wait(), 20)
        return got

    monkeypatch.setattr(mod, "_latest", meet)


def _both(*calls):
    """같이 부르고 결과를 돌려준다. AppError가 아닌 예외(MissingGreenlet 등)는 그대로 던진다."""

    async def go():
        return await asyncio.gather(*(c() for c in calls), return_exceptions=True)

    return no_surprises(run(go()))


def _one_new(rows: list) -> bool:
    """낡은 판 뒤에 새 판(지금 산식)이 딱 하나, 맨 끝 버전으로 쌓였는지(진 쪽은 이긴 쪽 판을 읽음)"""
    new = [r["version"] for r in rows if r["formula_ver"] == FORMULA_VERSION]
    return len(new) == 1 and new[0] == max(r["version"] for r in rows) and len(rows) > 1


def _plans_ok(pid) -> bool:
    rows = query(
        "select version, formula_ver from plans where project_id = $1 and kind = 'expected'",
        uuid.UUID(str(pid)),
    )
    return _one_new(rows)


def _stale_plan(api, pid: str) -> None:
    """예상 공정표를 만들어 두고 낡게(산식 판이 바뀐 배포 뒤처럼)"""
    assert api.get(f"/projects/{pid}/plan").status_code == 200
    query("update plans set formula_ver = 'old' where project_id = $1", uuid.UUID(pid))


def _job(vid: uuid.UUID, did: str):
    return lambda: with_user(
        vid, lambda s, u: schedule_service.job_for(s, u, uuid.UUID(did), today_seoul())
    )


def test_job_for_twice_at_once_both_ok(api, monkeypatch):
    quiet(monkeypatch)
    _customer, pid, dm, _dd = fp.two(api)
    _stale_plan(api, pid)
    barum = user_id("barum@mitjip.test")
    _meet(monkeypatch, schedule_service, "expected")
    out = _both(_job(barum, dm), _job(barum, dm))
    assert [type(x).__name__ for x in out] == ["JobOut", "JobOut"]
    assert _plans_ok(pid)


def test_accept_dates_with_job_read_at_once(api, monkeypatch):
    quiet(monkeypatch)
    customer_token, pid, dm, _dd = fp.two(api)
    xm = uuid.UUID(fp.proposal_of(api, "barum@mitjip.test", dm, fp.MOK))
    use(api, customer_token)
    _stale_plan(api, pid)
    home, barum = user_id("home@mitjip.test"), user_id("barum@mitjip.test")
    _meet(monkeypatch, schedule_service, "expected")

    def accept():
        return with_user(
            home,
            lambda s, u: schedule_service.accept_dates(
                s, u, uuid.UUID(pid), uuid.UUID(dm), xm, AcceptIn(seen_version=0), fp.TODAY
            ),
        )

    out = _both(accept, _job(barum, dm))
    assert [type(x).__name__ for x in out] == ["ScheduleOut", "JobOut"]
    assert query("select status from deals where id = $1", uuid.UUID(dm))[0]["status"] == (
        "scheduled"
    )
    assert _plans_ok(pid)


def test_request_dates_with_job_read_at_once(api, monkeypatch):
    quiet(monkeypatch)
    customer_token, pid, _dm, dd = fp.both_accepted(api)
    use(api, customer_token)
    _stale_plan(api, pid)
    home, maru = user_id("home@mitjip.test"), user_id("maru@mitjip.test")
    w1, w2 = fp.run(fp.DOB[0] + timedelta(days=7), 2)
    data = DateRequestIn(wish_dates=[w1, w2], reason="이사 일정이 늦어졌어요.")
    _meet(monkeypatch, schedule_service, "expected")

    def request():
        return with_user(
            home,
            lambda s, u: schedule_service.request_dates(
                s, u, uuid.UUID(pid), uuid.UUID(dd), data, fp.TODAY
            ),
        )

    out = _both(request, _job(maru, dd))
    assert [type(x).__name__ for x in out] == ["ScheduleOut", "JobOut"]
    assert query("select count(*) n from date_requests where status = 'open'")[0]["n"] == 1
    assert _plans_ok(pid)


def test_propose_dates_with_job_read_at_once(api, monkeypatch):
    quiet(monkeypatch)
    _customer, pid, dm, _dd = fp.two(api)
    _stale_plan(api, pid)
    barum = user_id("barum@mitjip.test")
    data = DatesIn(start=fp.MOK[0], end=fp.MOK[1], crew=4, method="app")
    _meet(monkeypatch, schedule_service, "expected")

    def propose():
        return with_user(
            barum,
            lambda s, u: schedule_service.propose_dates(s, u, uuid.UUID(dm), data, fp.TODAY),
        )

    out = _both(propose, _job(barum, dm))
    assert [type(x).__name__ for x in out] == ["JobOut", "JobOut"]
    assert query("select count(*) n from date_proposals where status = 'pending'")[0]["n"] == 1
    assert _plans_ok(pid)


def _standards(pid) -> list:
    return query(
        "select version, formula_ver from standard_quotes where project_id = $1 and trade = 'dobae'"
        " order by version",
        uuid.UUID(str(pid)),
    )


def test_visits_board_twice_at_once_both_ok(api, monkeypatch):
    quiet(monkeypatch)
    f = booked(api)
    pid, home = uuid.UUID(f["pid"]), user_id("home@mitjip.test")
    query("update standard_quotes set formula_ver = 'old' where project_id = $1", pid)
    _meet(monkeypatch, quote_service)

    def board():
        return with_user(
            home,
            lambda s, u: visit_service.visits_for(s, u, pid, None, today_seoul(), now_utc()),
        )

    out = _both(board, board)
    assert [len(x.visits) for x in out] == [1, 1]
    assert _one_new(_standards(pid))


def test_my_projects_twice_at_once_both_ok(api, monkeypatch):
    quiet(monkeypatch)
    _token, first = customer(api)
    second = api.post("/projects", json=project_body(**NOWON_32)).json()["id"]
    for pid in (first, second):
        assert api.get(f"/projects/{pid}/standard").status_code == 200
    query("update standard_quotes set formula_ver = 'old'")
    home = user_id("home@mitjip.test")
    _meet(monkeypatch, quote_service)

    def mine():
        return with_user(home, lambda s, u: schedule_service.my_projects(s, u, today_seoul()))

    out = _both(mine, mine)
    assert [len(x) for x in out] == [2, 2]
    for pid in (first, second):
        assert _one_new(_standards(pid))


def test_lost_standard_save_keeps_caller_objects(api, monkeypatch):
    """진 쪽 흉내(R3 재현): 저장본을 한 번 못 본 척해 같은 판을 다시 넣다 고유 제약에 걸려도 user가 살아 있고
    이긴 쪽(저장된) 판을 돌려준다."""
    signup(api)
    pid = create(api, HOME).json()["id"]
    assert api.get(f"/projects/{pid}/standard").status_code == 200
    me = user_id("customer@mitjip.test")
    real = quote_service._latest
    calls = {"n": 0}

    async def raced(s, project_id):
        calls["n"] += 1
        return {} if calls["n"] == 1 else await real(s, project_id)

    monkeypatch.setattr(quote_service, "_latest", raced)

    async def go():
        async with SessionLocal() as s:
            user = await s.get(User, me)
            p = await project_service.get_for(s, user, uuid.UUID(pid))
            rows = await quote_service.ensure_standard(s, p)
            return user.id, {t: r.version for t, r in rows.items()}

    uid, versions = run(go())
    assert uid == me and versions.get("dobae") == 1 and set(versions.values()) == {1}
    assert [(r["version"], r["formula_ver"]) for r in _standards(pid)] == [(1, FORMULA_VERSION)]


# ---- R4#2 · #7: 기한 일 · 알림 이름이 앞 일과 겹치지 않는다 ----


def test_accept_due_job_comes_back_when_same_slot_picked_again(api):
    f = requested(api)
    login(api, f["email"])
    assert answer(api, f["visit"], start=1, end=12, instant=False).status_code == 200
    use(api, f["token"])
    r = choose(api, f["pid"], f["visit"], n=1, half="am")  # 기한 = 내일 09:00(반나절 시작)
    assert r.status_code == 200 and r.json()["status"] == "picked", r.text
    login(api, f["email"])
    body = {"reason_code": "no_crew", "slots": [{"day": d(9), "half": "pm"}]}
    assert api.post(f"/vendor/visits/{f['visit']}/propose", json=body).status_code == 200
    use(api, f["token"])
    assert api.post(f"/projects/{f['pid']}/visits/{f['visit']}/repick").status_code == 200
    r = choose(api, f["pid"], f["visit"], n=1, half="am")  # 같은 반나절 다시
    assert r.status_code == 200 and r.json()["status"] == "picked", r.text
    hold = query("select until from visit_holds where status = 'active'")[0]
    (job,) = pending_jobs(f["visit"], "visit_accept_due")  # 앞 일은 취소됐고 새 일이 기다린다
    assert job["run_at"] == hold["until"]
    later = hold["until"] + timedelta(minutes=5)
    assert changed(handle("visit_accept_due", f["visit"], later, run_at=job["run_at"]))
    assert status(f["visit"]) == "offered"  # 기한이 지나 잡기가 풀렸다
    assert query("select count(*) n from visit_holds where status = 'active'")[0]["n"] == 0


def test_short_tail_differs_per_row():
    a, b = uuid7(), uuid7()
    assert flow._short(a) != flow._short(b)


def test_change_to_other_half_same_day_keeps_day_jobs(api):
    f = booked(api)  # 6일 오전 확정
    r = api.post(
        f"/projects/{f['pid']}/visits/{f['visit']}/changes", json={"day": d(6), "half": "pm"}
    )
    assert r.status_code in (200, 201), r.text
    cid = r.json()["id"]
    login(api, f["email"])
    r = api.post(f"/vendor/visits/{f['visit']}/changes/{cid}/accept")  # 곧바로 받음
    assert r.status_code == 200, r.text
    v = query("select booked_day, booked_half from visits where id = $1", uuid.UUID(f["visit"]))
    assert (v[0]["booked_day"], v[0]["booked_half"]) == (day(6), "pm")
    assert len(pending_jobs(f["visit"], "visit_reminder")) == 1
    assert len(pending_jobs(f["visit"], "visit_quote_due")) == 1


# ---- R4#3: 관리자가 숨긴 리뷰는 지우고 다시 써도 숨긴 채 ----


def test_hidden_review_rewritten_stays_hidden_until_admin_shows(api):
    p = pair(api)
    did = deal_for(p)
    use(api, p.customer)
    body = "업체 사장님 번호 010-1111-2222로 직접 하세요"
    rid = write(api, p, did, body=body).json()["id"]
    admin = make_admin(api)
    use(api, admin)
    assert api.post(f"/admin/reviews/{rid}/hide", json={"code": "privacy"}).status_code == 200
    use(api, p.customer)
    assert api.delete(f"/reviews/{rid}").status_code == 204
    again = write(api, p, did, body=body)
    assert again.status_code == 201, again.text  # 지운 뒤 다시 쓰기는 그대로 된다
    rows = query("select status, hidden_code from reviews")
    assert [(r["status"], r["hidden_code"]) for r in rows] == [("hidden", "privacy")]
    page = api.get(f"/projects/{p.pid}/vendors/{p.vid}/reviews").json()
    assert page["items"] == [] and page["rating"]["count"] == 0  # 고객 목록 · 별점에 안 들어감
    use(api, p.vendor)
    (row,) = api.get("/vendor/reviews").json()["items"]
    assert row["hidden"] is True
    use(api, admin)
    new_id = again.json()["id"]
    assert api.post(f"/admin/reviews/{new_id}/show", json={}).status_code == 200
    assert query("select count(*) n from review_holds")[0]["n"] == 0  # 관리자가 봤으니 표시 지움
    use(api, p.customer)
    page = api.get(f"/projects/{p.pid}/vendors/{p.vid}/reviews").json()
    assert len(page["items"]) == 1 and page["rating"]["count"] == 1
    assert api.delete(f"/reviews/{new_id}").status_code == 204  # 보이던 리뷰를 지우면 표시 없음
    assert write(api, p, did).status_code == 201
    assert query("select status from reviews")[0]["status"] == "shown"


# ---- R4#4: 멈춤 풀기는 살아 있는 요청의 대화만 다시 연다 ----


def test_unsuspend_keeps_chat_of_closed_visit_read_only(api):
    f = booked(api)
    make_admin(api)
    r = api.post(f"/admin/vendors/{f['vendor']}/suspend", json={"scope": "all", "note": "점검"})
    assert r.status_code == 200, r.text
    assert status(f["visit"]) == "closed"
    r = api.post(f"/admin/vendors/{f['vendor']}/unsuspend", json={"note": "풀기"})
    assert r.status_code == 200, r.text
    t = query("select id, status, ro_reason from threads")[0]
    assert (t["status"], t["ro_reason"]) == ("read_only", "admin")  # 닫힌 요청의 대화는 읽기만
    login(api, f["email"])
    r = send(api, t["id"], "다시 연락드려요")
    assert r.status_code == 409, r.text


def test_unsuspend_reopens_chat_of_live_deal(api):
    p = pair(api)
    deal_for(p, status="scheduled")  # 확정한 공사(요청 chosen)는 멈춤으로 닫히지 않는다
    admin = make_admin(api)
    use(api, admin)
    url = f"/admin/vendors/{p.vid}"
    assert api.post(f"{url}/suspend", json={"scope": "all", "note": "확인"}).status_code == 200
    assert query("select status from threads")[0]["status"] == "read_only"
    assert api.post(f"{url}/unsuspend", json={}).status_code == 200
    t = query("select status, ro_reason from threads")[0]
    assert (t["status"], t["ro_reason"]) == ("open", None)
    use(api, p.vendor)
    assert send(api, p.tid, "공사 날 뵐게요").status_code == 201


# ---- R4#5: 몸통 없는(v2) 취소도 프로젝트를 잠가 새 요청과 줄 선다 ----


def test_v2_cancel_waits_for_new_request_and_keeps_lock(api, monkeypatch):
    quiet(monkeypatch)
    f = requested(api)  # 업체 A 요청 → 집 정보 잠김
    b = vendor(api, "b@mitjip.test", "결도배")
    use(api, f["token"])
    assert add(api, f["pid"], b).status_code == 201
    pid, home = uuid.UUID(f["pid"]), user_id("home@mitjip.test")
    real = visit_service._listed

    async def slow_listed(*a, **k):
        await asyncio.sleep(1.5)  # 새 요청이 프로젝트를 잠근 구간을 넓힌다
        return await real(*a, **k)

    monkeypatch.setattr(visit_service, "_listed", slow_listed)
    data = VisitCreateIn(
        trade="dobae", vendor_ids=[uuid.UUID(b)], wish_start=day(2), wish_end=day(16)
    )

    async def req_b():
        async with SessionLocal() as s:
            user = await s.get(User, home)
            return await flow.request(s, user, pid, data, now_utc(), screen=True)

    async def cancel_a():
        await asyncio.sleep(0.8)  # B가 프로젝트를 잠근 뒤
        async with SessionLocal() as s:
            user = await s.get(User, home)
            return await visit_service.cancel(s, user, pid, uuid.UUID(f["visit"]), today_seoul())

    async def both():
        return await asyncio.gather(req_b(), cancel_a(), return_exceptions=True)

    no_surprises(run(both()))
    assert status(f["visit"]) == "cancelled"
    assert status(visit_of(f["pid"], b)) == "requested"
    locked = query("select locked_at from projects where id = $1", pid)[0]["locked_at"]
    assert locked is not None  # 살아 있는 요청이 있어 집 정보 잠금 그대로


# ---- R4#6: 날짜 고르기 추천은 같은 집 다른 실측이 잡은 반나절을 빼요 ----


def test_pick_view_recommend_skips_home_clash(api):
    f = booked(api)  # 업체 A: 오늘 + 6일 오전 확정
    b = vendor(api, "b@mitjip.test", "결도배")
    use(api, f["token"])
    assert add(api, f["pid"], b).status_code == 201
    assert ask(api, f["pid"], [b]).status_code == 201
    vb = visit_of(f["pid"], b)
    login(api, "b@mitjip.test")
    assert answer(api, vb, start=6, end=6, instant=True).status_code == 200  # B 기간: 6일 하루
    use(api, f["token"])
    got = api.get(f"/projects/{f['pid']}/visits/{vb}").json()
    assert any(m["day"] == d(6) and m["half"] == "am" for m in got["mine"])
    assert (got["recommend"]["day"], got["recommend"]["half"]) == (d(6), "pm")
    r = choose(api, f["pid"], vb, n=6, half="pm")  # 추천을 누르면 된다
    assert r.status_code == 200 and r.json()["status"] == "booked", r.text


# ---- R4#9: 흔한 말과 같은 은행 이름 뒤 전화번호는 계좌로 안 본다 ----


def test_offsite_bank_words_need_bank():
    plain = [
        "우리 팀장 번호 010-1234-5678로 연락 주세요",
        "하나만 여쭤볼게요. 010 1234 5678로 문자 주세요",
        "제일 빠른 날은 010-9876-5432로 알려 드릴게요",
        "기업 행사가 있어 010-2222-3333으로 연락 주세요",
    ]
    assert [rules.offsite(x) for x in plain] == [False] * 4
    accounts = [
        "우리은행 1002-123-456789로 보내 주세요",
        "하나 은행 123-456789-12345 예금주 홍길동",
        "SC제일 123-45-678901 로 부탁드려요",
        "국민은행 123456-78-901234 로 보내 주세요",
        "신한 110 123 456789 예금주 홍길동",
    ]
    assert [rules.offsite(x) for x in accounts] == [True] * 5


# ---- R4#10: 날짜 뒤 조사 ----


def test_dates_change_todo_josa():
    pid, due = uuid.uuid4(), datetime(2026, 12, 1, 9, 0, tzinfo=UTC)
    deal = N(
        vendor_name="마루와벽", dates_due_at=due, start_date=None, end_date=None, work_days=None
    )
    base = date(2026, 12, 7)  # 월요일

    def text(end: date) -> str:
        x = N(start_date=base, end_date=end, days=None)
        ctx = {"proposal": x, "request": None, "facts": None}
        return schedule_service._todo_out(pid, "dates_change", "dobae", deal, ctx).text

    want = {"월": "로", "화": "로", "수": "로", "목": "으로", "금": "으로", "토": "로", "일": "로"}
    for i, (w, josa) in enumerate(want.items()):
        got = text(base + timedelta(days=i))
        assert got.endswith(f"({w}){josa} 바꾸자고 했어요"), got


# ---- R4#11: 늦게 돈 전날 알림은 실측 날에 '내일'이라고 하지 않는다 ----


def test_late_reminder_on_visit_day_is_skipped(api):
    f = booked(api)  # 오늘 + 6일 오전
    at = deadline.reminder_at(day(6))
    late = datetime.combine(day(6), time(15, 0), SEOUL)  # 실측 당일 오후
    assert not changed(handle("visit_reminder", f["visit"], late, run_at=at))
    assert notes("home@mitjip.test", "visit_reminder") == []
    on_time = datetime.combine(day(5), time(18, 1), SEOUL)  # 전날 18시는 그대로 보낸다
    assert changed(handle("visit_reminder", f["visit"], on_time, run_at=at))
    (n,) = notes("home@mitjip.test", "visit_reminder")
    assert n["body"].startswith("내일 오전 실측이에요")


# ---- R3#2: 철거 범위만 바꿔도 표준견적서 새 판 ----


def _demolition(pid: str, value: str) -> None:
    query(
        "insert into project_conditions (id, project_id, trade, key, value)"
        " values (gen_random_uuid(), $1::uuid, 'dobae', 'demolition', $2)"
        " on conflict (project_id, key) do update set value = excluded.value, updated_at = now()",
        pid,
        value,
    )


def test_demolition_change_makes_new_standard_version(api):
    signup(api)
    pid = create(api, HOME).json()["id"]
    _say(pid, "mokgong.doors", "문틀까지")
    a = _dobae(api.get(f"/projects/{pid}/standard").json())
    assert _keys(a)["removal"] == "after_visit" and "전체 철거" not in a["notes"][0]
    _demolition(pid, "full")
    b = _dobae(api.get(f"/projects/{pid}/standard").json())
    assert b["version"] == a["version"] + 1
    assert _keys(b)["removal"] == "excluded"  # 전체 철거 공사가 기존 벽지를 떼요(ADR 0007)
    assert "전체 철거" in b["notes"][0]
    c = _dobae(api.get(f"/projects/{pid}/standard").json())
    assert c["version"] == b["version"]  # 다시 읽으면 그대로(같은 계산)


# ---- R3#3: '주방'은 방문 개수에 안 든다 ----


def _mok_project(names: list[str]):
    spaces = [N(id=f"s{i}", name=n) for i, n in enumerate(names)]
    return N(
        id="p", rev=1, occupied=False, balcony_ext=False, home=None,
        size=N(band=None, m2=Decimal("84.9"), basis="supply"),
        spaces=spaces,
        trades=N(dobae=None, mokgong=N(spaces=[s.id for s in spaces], items=["door"])),
    )  # fmt: skip


def test_kitchen_is_not_a_room_for_doors():
    def doors(names: list[str]) -> Decimal | None:
        (c,) = quote_service.calc_trades(_mok_project(names))
        return next(ln for ln in c.lines if ln.key == "door").qty

    assert doors(["안방", "작은방", "주방"]) == doors(["안방", "작은방"]) == 2
    assert doors(["주방"]) == doors(["거실", "주방"]) == 1  # 방이 없으면 1개(기존 규칙)
    (c,) = quote_service.calc_trades(_mok_project(["안방", "작은방", "주방"]))
    assert "방문은 목공을 고른 방 수(2개)로 잡았어요." in c.notes


# ---- R3#4: 링크 신고 '링크 숨김'은 신고한 주소만 숨긴다 ----


BAD, GOOD = "https://blog.example.com/bad", "https://cafe.example.com/good"


def _links_shown(p) -> None:
    now = datetime.now(UTC)
    query(LINK, p.vid, 0, "블로그 후기", BAD, "shown", now)
    query(LINK, p.vid, 1, "카페 후기", GOOD, "shown", now)


def _link_report(api, p, token: str) -> str:
    """고객(token)이 0번 링크(BAD)를 신고"""
    use(api, token)
    r = api.post(
        "/reports",
        json={
            "kind": "link",
            "vendor_id": str(p.vid),
            "link_sort": 0,
            "reason_code": "wrong_place",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _links() -> list[tuple[int, str, str]]:
    rows = query("select sort, url, status from vendor_review_links order by sort")
    return [(r["sort"], r["url"], r["status"]) for r in rows]


def test_hide_link_skips_replaced_link(api):
    p = pair(api)
    _links_shown(p)
    rid = _link_report(api, p, p.customer)
    use(api, p.vendor)  # 신고된 0번을 빼고 좋은 링크만 남김 → 좋은 링크가 0번으로 당겨진다
    r = api.put("/vendor/review-links", json={"links": [{"label": "카페 후기", "url": GOOD}]})
    assert r.status_code == 200, r.text
    before = _links()
    admin = make_admin(api)
    use(api, admin)
    got = api.post(f"/admin/reports/{rid}/resolve", json={"action": "hide_link"})
    assert got.status_code == 409 and got.json()["error"]["code"] == "stale", got.text
    assert _links() == before  # 좋은 링크는 그대로
    assert query("select status from reports")[0]["status"] == "open"  # 다른 처리를 고를 수 있다
    assert query("select count(*) n from admin_actions")[0]["n"] == 0
    assert api.post(f"/admin/reports/{rid}/resolve", json={"action": "none"}).status_code == 200


def test_hide_link_follows_moved_link(api):
    p = pair(api)
    _links_shown(p)
    rid = _link_report(api, p, p.customer)
    other = _link_report(api, p, signup(api, "c2@mitjip.test"))  # 다른 고객도 같은 링크를 신고
    use(api, p.vendor)  # 순서만 바꿈 → 신고한 주소가 1번으로
    links = [{"label": "카페 후기", "url": GOOD}, {"label": "블로그 후기", "url": BAD}]
    assert api.put("/vendor/review-links", json={"links": links}).status_code == 200
    admin = make_admin(api)
    use(api, admin)
    got = api.post(f"/admin/reports/{rid}/resolve", json={"action": "hide_link"})
    assert got.status_code == 200, got.text
    status_of = {url: st for _, url, st in _links()}
    assert status_of[BAD] == "hidden" and status_of[GOOD] != "hidden"
    assert [x["action"] for x in query("select action from admin_actions")] == ["link_hidden"]
    got = api.post(f"/admin/reports/{other}/resolve", json={"action": "hide_link"})
    assert got.status_code == 409 and got.json()["error"]["code"] == "already", got.text
