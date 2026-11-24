"""점검 X5 플랫폼 · 비용 · 계정 고침(R5 #1~#10, R6 B3). 점검 보고의 재현을 그대로 두고 고친 뒤의 모습을 본다.
유료 호출 0회(LLM 자리는 가짜 함수)."""

import asyncio
import io
import logging
import threading
import uuid
from collections import Counter
from datetime import timedelta
from pathlib import Path

import anyio.to_thread
import pytest
from botocore.exceptions import ClientError
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers, UploadFile

from app import worker
from app.agent import llm
from app.auth import service as auth_service
from app.config import settings
from app.db import SessionLocal
from app.files import images, storage
from app.files import service as files_service
from app.jobs import service as jobs
from app.jobs.models import ATTEMPTS_MAX
from app.shared import clock
from app.usage import service as usage
from tests.conftest import query
from tests.helpers import JPEG, PASSWORD, PDF, PNG, make_admin, signup, upload, use, vendor_signup
from tests.test_v4_llm_claude import _user
from tests.test_v4_llm_usage import _go, caps, spend  # noqa: F401 (caps는 fixture)
from tests.test_vendor_profile import approved_vendor, vendor_id
from tests.test_vendor_profile import body as profile_body
from tests.test_visit_request import home, listed, send


def stored(key: str) -> Path:
    return Path(settings.files_dir) / key


def ids_of(rows: list[dict]) -> list[str]:
    return [r["vendor_id"] for r in rows]


# ---- #1 시공 사진을 올린 업체도 탈퇴된다(vendor_portfolio.file_id ON DELETE CASCADE) ----


def test_r5_1_vendor_with_portfolio_and_price_file_withdraws(api):
    approved_vendor(api, "pf@mitjip.test")
    assert api.put("/vendor/profile", json=profile_body()).status_code == 200
    photo = upload(api, kind="portfolio", content=JPEG, name="a.jpg").json()["id"]
    assert (
        api.post("/vendor/portfolio", json={"file_id": photo, "title": "벽지"}).status_code == 201
    )
    doc = upload(api, kind="price_doc", content=PDF, name="단가.pdf").json()["id"]
    r = api.post("/vendor/price-files", json={"file_id": doc, "trade": "dobae"})
    assert r.status_code == 201, r.text
    keys = [r["storage_key"] for r in query("select storage_key from files")]
    assert len(keys) == 3  # 사업자등록증 · 시공 사진 · 근거 파일

    r = api.post("/me/withdraw", json={"password": PASSWORD})
    assert r.status_code == 204, r.text
    left = query(
        "select (select count(*) from users) u, (select count(*) from files) f,"
        " (select count(*) from vendor_portfolio) p"
    )[0]
    assert dict(left) == {"u": 0, "f": 0, "p": 0}
    assert not [k for k in keys if stored(k).exists()]
    (fk,) = query(
        "select confdeltype from pg_constraint where conname = 'fk_vendor_portfolio_file_id_files'"
    )
    assert fk["confdeltype"] == b"c"  # 파일이 지워지면 사진 줄도 지운다


# ---- #2 새 계정 합 하루 상한은 탈퇴한 계정이 쓴 돈도 센다(부른 때 장부 줄에 표시) ----


@pytest.mark.parametrize("redis", ["up", "down"])
def test_r5_2_new_pool_keeps_spending_of_withdrawn_accounts(monkeypatch, caps, redis):  # noqa: F811
    news = [_user(f"pool-{i}@mitjip.test") for i in range(7)]

    async def first():
        for uid in news[:6]:
            await spend(uid, "assistant", output_tokens=15_000)  # 한 계정 $0.15씩, 합 $0.90
        with pytest.raises(usage.OverCap) as e:
            await usage.allow(news[6], "assistant")
        return e.value.scope

    assert _go(monkeypatch, redis, first) == "new_pool_day"
    # 탈퇴(auth.repository.delete_user = delete from users): 장부 줄의 user_id는 비워진다(SET NULL)
    query("delete from users where id = any($1::uuid[])", news[:6])

    async def second():
        (pool,) = [b for b in usage.buckets(news[6], joined=clock.now_utc()) if b.new_days]
        if redis == "up":
            await usage.queue.redis.delete(pool.key)  # 카운터를 장부 합계로 다시 맞추는 때(SYNC_S)
        with pytest.raises(usage.OverCap) as e:
            await usage.allow(news[6], "assistant")  # 탈퇴해도 그날 쓴 돈은 새 계정 합에 남는다
        return e.value.scope, await usage.db_spent(pool)

    assert _go(monkeypatch, redis, second) == ("new_pool_day", 900_000)
    rows = query("select user_id, new_account from llm_usage")
    assert len(rows) == 6 and all(r["user_id"] is None and r["new_account"] for r in rows)


# ---- #3 멈춘 업체(새 요청만 막기)는 옛 목록 줄 · 옛 몸통 실측 요청에서도 빠진다 ----


def test_r5_3_paused_vendor_is_out_of_old_rows_and_old_request_body(api):
    paused = listed(api, "stop@mitjip.test", "멈춘도배")
    other = listed(api, "keep@mitjip.test", "그대로도배")
    token, p = home(api)
    pid = p["id"]
    use(api, make_admin(api))
    r = api.post(f"/admin/vendors/{paused}/suspend", json={"scope": "new", "note": "신고 처리"})
    assert r.status_code == 200, r.text

    use(api, token)
    got = api.get(f"/projects/{pid}/vendors", params={"trade": "dobae"}).json()
    assert ids_of(got["vendors"]) == [other]  # 옛 목록 줄에도 없다
    assert paused not in ids_of(got.get("local") or [])
    r = send(api, pid, [paused])  # 희망 기간 없는 옛 몸통(visit.service.request_visits)
    assert r.status_code == 409 and r.json()["error"]["code"] == "unavailable", r.text
    r = send(api, pid, [paused, other])
    assert r.status_code == 201, r.text
    assert r.json()["failed"] == [{"vendor_id": paused, "code": "unavailable"}]
    assert ids_of(r.json()["created"]) == [other]
    assert (
        query("select count(*) n from visits where vendor_id = $1", uuid.UUID(paused))[0]["n"] == 0
    )


# ---- #4 확정한 업체가 탈퇴해도 고객이 확정한 견적서 파일은 고객 쪽에 남는다 ----


def test_r5_4_vendor_withdraw_keeps_the_confirmed_quote_file(api):
    from tests.test_deal import confirm, setup
    from tests.test_visit_inbox import login

    customer, pid, va, vb, _ = setup(api)
    seen = {
        x["visit_id"]: x["seen_ver"]
        for x in api.get(f"/projects/{pid}/quotes?trade=dobae").json()["vendors"]
    }
    assert confirm(api, pid, va, seen[va]).status_code == 200
    sql = (
        "select f.id, f.storage_key, f.owner_id, q.id quote_id from vendor_quote_files x"
        " join vendor_quotes q on q.id = x.quote_id join files f on f.id = x.file_id"
        " where q.visit_id = $1"
    )
    (before,) = query(sql, uuid.UUID(va))
    maru = vendor_id("maru@mitjip.test")
    license_key = query(
        "select storage_key from files where owner_id = $1 and kind = 'license'", maru
    )[0]["storage_key"]

    login(api, "maru@mitjip.test")
    assert api.post("/me/withdraw", json={"password": PASSWORD}).status_code == 204
    owner = query("select owner_id from projects where id = $1", uuid.UUID(pid))[0]["owner_id"]
    after = query(sql, uuid.UUID(va))
    assert [(r["id"], r["owner_id"]) for r in after] == [
        (before["id"], owner)
    ]  # 고객 몫으로 남는다
    assert stored(before["storage_key"]).exists()
    assert query("select count(*) n from files where owner_id = $1", maru)[0]["n"] == 0
    assert not stored(license_key).exists()  # 업체의 다른 파일은 지웠다
    gyeol = query(sql, uuid.UUID(vb))  # 다른 업체 견적서는 그대로
    assert gyeol and gyeol[0]["owner_id"] == vendor_id("gyeol@mitjip.test")

    use(api, customer)
    got = api.get(f"/projects/{pid}/quotes/{before['quote_id']}/files/{before['id']}")
    assert got.status_code == 200 and got.content.startswith(b"%PDF")
    deal = query("select status, vendor_id, quote_id from deals")[0]
    assert (deal["status"], deal["vendor_id"], deal["quote_id"]) == (
        "confirmed",
        None,
        before["quote_id"],
    )
    # 고객이 탈퇴하면 남겨 둔 파일도 함께 지운다
    assert api.post("/me/withdraw", json={"password": PASSWORD}).status_code == 204
    assert query("select count(*) n from files where id = $1", before["id"])[0]["n"] == 0
    assert not stored(before["storage_key"]).exists()


# ---- #5 S3에서 못 지워도 탈퇴는 204(쿠키도 지움), 남은 수는 기록 ----


class _S3DeleteFails:
    def __init__(self):
        self.items: dict[str, bytes] = {}

    def put_object(self, *, Bucket, Key, Body):
        self.items[Key] = Body

    def get_object(self, *, Bucket, Key):
        raise AssertionError

    def delete_object(self, *, Bucket, Key):
        raise ClientError({"Error": {"Code": "AccessDenied", "Message": "x"}}, "DeleteObject")


def test_r5_5_withdraw_is_204_when_s3_delete_fails(api, monkeypatch, caplog):
    fake = _S3DeleteFails()
    monkeypatch.setattr(settings, "files_s3_bucket", "mitjip-test-files")
    monkeypatch.setattr(storage, "_s3", lambda: fake)
    signup(api)
    assert upload(api).status_code == 201
    with caplog.at_level(logging.ERROR):
        r = api.post("/me/withdraw", json={"password": PASSWORD})
    assert r.status_code == 204, r.text
    assert settings.session_cookie in r.headers.get("set-cookie", "")  # 쿠키를 지운다
    assert query("select count(*) n from users")[0]["n"] == 0
    assert len(fake.items) == 1  # 저장소에 남은 것은
    assert any("1개" in x.getMessage() for x in caplog.records)  # 수를 기록으로 남긴다
    assert api.get("/me").status_code == 401


# ---- #6 집 정보 동(emd)의 제어 문자는 지운다 ----


def test_r5_6_project_emd_control_chars_are_removed(api):
    signup(api)
    body = {
        "sido": "seoul",
        "sgg": "노원구",
        "emd": "상계\u0000동",
        "area_m2": "84.9",
        "area_basis": "supply",
        "occupied": False,
        "grade": "basic",
    }
    r = api.post("/projects", json=body)
    assert r.status_code == 201, r.text
    assert r.json()["emd"] == "상계동"
    r = api.post("/projects", json={**body, "emd": "\u0000 \u200b"})  # 보이는 글자가 없으면 비움
    assert r.status_code == 201, r.text
    assert r.json()["emd"] is None


# ---- #7 관리자 업체 검색어의 NUL ----


def test_r5_7_admin_vendor_search_ignores_nul(api):
    assert vendor_signup(api, email="maru@mitjip.test", biz_name="마루와벽").status_code == 201
    use(api, make_admin(api))
    r = api.get("/admin/vendors", params={"q": "마루\u0000"})
    assert r.status_code == 200, r.text
    assert [v["biz_name"] for v in r.json()] == ["마루와벽"]
    assert api.get("/admin/vendors", params={"q": "\u0000"}).status_code == 200


# ---- #8 관리자가 정지한 업체 회원은 목록 · 자세히 · 실측 요청에서 빠진다 ----


def test_r5_8_suspended_vendor_account_is_hidden_and_not_requestable(api):
    vid = listed(api, "sus@mitjip.test", "정지된도배")
    token, p = home(api)
    pid = p["id"]
    admin = make_admin(api)
    use(api, admin)
    assert api.post(f"/admin/members/{vid}/suspend", json={"note": "사기 의심"}).status_code == 200

    use(api, token)
    got = api.get(f"/projects/{pid}/vendors", params={"trade": "dobae"}).json()
    assert vid not in ids_of(got["vendors"]) and vid not in ids_of(got.get("local") or [])
    assert api.get(f"/projects/{pid}/vendors/{vid}", params={"trade": "dobae"}).status_code == 404
    r = send(api, pid, [vid])
    assert r.status_code == 409 and r.json()["error"]["code"] == "unavailable", r.text
    assert query("select count(*) n from visits")[0]["n"] == 0

    use(api, admin)  # 정지를 풀면 다시 보인다
    assert api.post(f"/admin/members/{vid}/unsuspend", json={}).status_code == 200
    use(api, token)
    got = api.get(f"/projects/{pid}/vendors", params={"trade": "dobae"}).json()
    assert vid in ids_of(got["vendors"])


# ---- #9 오래 걸리는 기한 일: 일마다 시간 제한 · 멈춘 일은 다시 거둘 때 센다 · 못 할 일은 돌려놓는다 ----


def _add_jobs(t0, *kinds_minutes: tuple[str, int]) -> None:
    async def go():
        async with SessionLocal() as s:
            for kind, minutes in kinds_minutes:
                at = t0 - timedelta(minutes=minutes)
                await jobs.add(s, kind=kind, ref_id=uuid.uuid4(), run_at=at)
            await s.commit()

    asyncio.run(go())


def _jobs() -> dict:
    rows = query("select kind, status, attempts, last_error from jobs order by run_at")
    return {r["kind"]: (r["status"], r["attempts"], r["last_error"]) for r in rows}


async def _hang(s, job, now):
    await asyncio.sleep(3600)  # LLM · 잠금 기다림처럼 끝나지 않는 처리


def test_r5_9_hanging_job_times_out_and_the_batch_goes_on(monkeypatch):
    ran: list[str] = []

    async def ok(s, job, now):
        ran.append(job.kind)
        return True

    monkeypatch.setattr(worker, "JOB_HANDLERS", {"visit_reminder": _hang, "visit_quote_due": ok})
    monkeypatch.setattr(worker, "JOB_TIMEOUT", 0.2)
    t0 = clock.now_utc()
    _add_jobs(t0, ("visit_reminder", 10), ("visit_quote_due", 5))
    # arq 제한(SWEEP_TIMEOUT) 대신 넉넉한 바깥 제한: 그 안에 스스로 끝나야 한다
    tally = asyncio.run(asyncio.wait_for(worker.sweep(t0), timeout=10))
    assert tally == Counter({("visit_reminder", "retry"): 1, ("visit_quote_due", "done"): 1})
    assert _jobs() == {
        "visit_reminder": ("pending", 1, "TimeoutError"),  # 1분 뒤 다시, 5번이면 failed
        "visit_quote_due": ("done", 0, None),  # 같은 묶음의 일도 처리했다
    }
    assert ran == ["visit_quote_due"]


def test_r5_9_job_cut_while_waiting_on_the_db_still_records_the_failure(monkeypatch):
    """DB를 기다리던 처리가 시간 제한에 끊겨도 그 연결을 다시 쓰지 않고 새 세션에 실패를 남긴다."""
    from sqlalchemy import text

    async def slow_db(s, job, now):
        await s.execute(text("select pg_sleep(5)"))  # 잠금 기다림처럼 오래 걸리는 쿼리
        return True

    monkeypatch.setattr(worker, "JOB_HANDLERS", {"visit_reminder": slow_db})
    monkeypatch.setattr(worker, "JOB_TIMEOUT", 0.3)
    t0 = clock.now_utc()
    _add_jobs(t0, ("visit_reminder", 1))
    tally = asyncio.run(asyncio.wait_for(worker.sweep(t0), timeout=10))
    assert tally == Counter({("visit_reminder", "retry"): 1})
    assert _jobs() == {"visit_reminder": ("pending", 1, "TimeoutError")}


def test_r5_9_stuck_job_counts_as_a_try_and_fails_at_the_max():
    """처리 중에 worker가 멈춰(arq 제한 · 프로세스 죽음) running으로 남은 일은 다시 거둘 때마다 한 번 실패로 센다."""
    t0 = clock.now_utc()
    _add_jobs(t0, ("visit_reminder", 1))

    async def go():
        got = []
        for i in range(ATTEMPTS_MAX + 1):
            at = t0 + (jobs.LOCK + timedelta(seconds=1)) * i  # 잠금이 풀린 뒤마다
            async with SessionLocal() as s:
                got.append(len(await jobs.claim(s, at)))  # 거두기만 하고 끝내지 못함(멈춤)
                await s.commit()
        return got

    assert asyncio.run(go()) == [1, 1, 1, 1, 1, 0]
    (row,) = query("select status, attempts, last_error, locked_until, done_at from jobs")
    assert (row["status"], row["attempts"], row["last_error"]) == ("failed", ATTEMPTS_MAX, "Stuck")
    assert row["locked_until"] is None and row["done_at"] is not None


def test_r5_9_sweep_puts_back_jobs_it_has_no_time_for(monkeypatch):
    ran: list[str] = []

    async def ok(s, job, now):
        ran.append(job.kind)
        return True

    monkeypatch.setattr(worker, "JOB_HANDLERS", {"visit_reminder": _hang, "visit_quote_due": ok})
    monkeypatch.setattr(worker, "JOB_TIMEOUT", 0.3)
    monkeypatch.setattr(worker, "SWEEP_BUDGET", 0.1)  # 첫 일 뒤로는 새 일을 시작할 시간이 없다
    t0 = clock.now_utc()
    _add_jobs(t0, ("visit_reminder", 30), ("visit_reminder", 20), ("visit_quote_due", 10))
    first = asyncio.run(asyncio.wait_for(worker.sweep(t0), timeout=10))
    assert first == Counter({("visit_reminder", "retry"): 1})
    rows = query("select kind, status, attempts, locked_until from jobs order by run_at")
    assert [(r["kind"], r["status"], r["attempts"]) for r in rows] == [
        ("visit_reminder", "pending", 0),  # 손대지 않은 일은 돌려놓는다(센 횟수 그대로)
        ("visit_quote_due", "pending", 0),
        ("visit_reminder", "pending", 1),  # 시간 제한에 걸린 일은 1분 뒤로
    ]
    assert all(r["locked_until"] is None for r in rows)
    monkeypatch.setattr(worker, "SWEEP_BUDGET", 10)
    again = asyncio.run(asyncio.wait_for(worker.sweep(t0), timeout=10))  # 다음 차례에 처리
    assert again == Counter({("visit_reminder", "retry"): 1, ("visit_quote_due", "done"): 1})
    assert ran == ["visit_quote_due"]


# ---- #10 사진 처리 · 비밀번호 해시를 기다리는 요청이 작업 스레드 자리를 쥐지 않는다 ----


def _photo() -> UploadFile:
    return UploadFile(
        io.BytesIO(PNG), filename="a.png", headers=Headers({"content-type": "image/png"})
    )


def test_r5_10_waiting_photos_do_not_hold_worker_threads(monkeypatch):
    gate, lock = threading.Event(), threading.Lock()
    busy, peak = [0], [0]

    def slow_clean(data, mime):  # 큰 사진처럼 오래 걸리는 처리
        with lock:
            busy[0] += 1
            peak[0] = max(peak[0], busy[0])
        gate.wait(10)
        with lock:
            busy[0] -= 1
        return data, mime

    monkeypatch.setattr(images, "_clean", slow_clean)

    async def go():
        anyio.to_thread.current_default_thread_limiter().total_tokens = 2  # 기본 40자리를 줄여 본다
        photos = [asyncio.create_task(files_service.prepare("photo", _photo())) for _ in range(4)]
        await asyncio.sleep(0.3)
        try:  # 로그인 · 파일 형식 보기 · 저장처럼 기본 자리를 쓰는 다른 일이 바로 돈다
            return await asyncio.wait_for(run_in_threadpool(lambda: "free"), timeout=3)
        finally:
            gate.set()
            await asyncio.gather(*photos)

    assert asyncio.run(go()) == "free"
    assert peak[0] == 1  # 사진은 여전히 한 장씩


def test_r5_10_waiting_password_checks_do_not_hold_worker_threads(monkeypatch):
    gate, lock = threading.Event(), threading.Lock()
    busy, peak = [0], [0]

    class SlowHasher:
        def verify(self, hashed, password):  # argon2처럼 오래 걸리는 확인
            with lock:
                busy[0] += 1
                peak[0] = max(peak[0], busy[0])
            gate.wait(10)
            with lock:
                busy[0] -= 1
            return True

    async def no_limit(*a, **k):  # 시도 횟수 세기(Redis)는 이 시험 밖
        return None

    monkeypatch.setattr(auth_service, "_hasher", SlowHasher())
    monkeypatch.setattr(auth_service.ratelimit, "hit", no_limit)
    monkeypatch.setattr(auth_service.ratelimit, "reset", no_limit)

    async def go():
        anyio.to_thread.current_default_thread_limiter().total_tokens = 2
        checks = [
            asyncio.create_task(
                auth_service._check_password(f"u{i}@mitjip.test", "h", "pw", f"10.0.0.{i}")
            )
            for i in range(6)
        ]
        await asyncio.sleep(0.3)
        try:
            return await asyncio.wait_for(run_in_threadpool(lambda: "free"), timeout=3)
        finally:
            gate.set()
            await asyncio.gather(*checks)

    assert asyncio.run(go()) == "free"
    assert peak[0] == 4  # 해시는 여전히 한 번에 4개까지


# ---- R6 B3 승인 전 업체는 유료 v2 상담을 못 쓰고, 새 계정 몫에 든다 ----


def test_r6_b3_pending_vendor_cannot_use_paid_v2_ask(api, monkeypatch):
    calls = []

    async def fake_chat_tools(system, messages, tools):
        calls.append(1)  # 실제로는 여기서 유료 호출
        return {"text": "도배 전에 벽을 말려요.", "tool_calls": [], "stop": "stop"}

    monkeypatch.setattr(llm, "chat_tools", fake_chat_tools)
    assert vendor_signup(api, email="pending-vendor@mitjip.test").status_code == 201
    assert api.get("/me").json()["vendor_status"] == "pending"
    r = api.post("/v2/ask", json={"message": "도배 전에 뭘 준비해요?"})
    assert r.status_code == 403, r.text
    r = api.post("/v2/ask/t1", json={"results": [{"id": "c1", "content": "{}"}]})
    assert r.status_code == 403, r.text
    assert calls == []
    approved_vendor(api, "approved-vendor@mitjip.test")  # 승인 업체도 v2 상담은 고객 화면 것
    assert api.post("/v2/ask", json={"message": "도배 전에 뭘 준비해요?"}).status_code == 403
    signup(api, "ask-customer@mitjip.test")
    r = api.post("/v2/ask", json={"message": "도배 전에 뭘 준비해요?"})
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("redis", ["up", "down"])
def test_r6_b3_pending_vendor_counts_as_a_new_account(api, monkeypatch, caps, redis):  # noqa: F811
    assert vendor_signup(api, email="pv@mitjip.test").status_code == 201
    pending = vendor_id("pv@mitjip.test")
    approved_vendor(api, "av@mitjip.test")
    approved = vendor_id("av@mitjip.test")

    async def go():
        joined = (await usage.joined_at(pending), await usage.joined_at(approved))
        await spend(approved, "assistant", output_tokens=19_000)  # $0.19 = $0.20의 95%
        await usage.allow(approved, "assistant")  # 승인 업체는 새 계정 몫을 보지 않는다
        await spend(pending, "assistant", output_tokens=19_000)
        with pytest.raises(usage.OverCap) as e:
            await usage.allow(pending, "assistant")  # 심사 중 업체는 새 계정처럼 막힌다
        (pool,) = [b for b in usage.buckets(pending, joined=joined[0]) if b.new_days]
        return joined, e.value.scope, await usage.db_spent(pool)

    (j_pending, j_approved), scope, pooled = _go(monkeypatch, redis, go)
    assert j_pending is not None and j_approved is None
    assert (scope, pooled) == ("new_user_day", 190_000)  # 새 계정 합에는 심사 중 업체 돈만
    flags = {r["user_id"]: r["new_account"] for r in query("select * from llm_usage")}
    assert flags == {pending: True, approved: False}
