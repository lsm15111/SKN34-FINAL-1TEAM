"""대신 연락 아웃박스 · 수신거부: 동의, 기능 플래그, 야간, 하루 한도, 상태 이력 (가짜 업체 · 보내지 않음)."""

import asyncio
import uuid
from datetime import UTC, datetime

import asyncpg
import pytest

from app.config import settings
from app.db import SessionLocal
from app.quote import service, tasks
from app.quote.sender import DryRunSender, SendError
from app.quote.service import DRY_RUN_LABEL, OFF_NOTICE
from tests.conftest import query
from tests.helpers import signup, use
from tests.sourcing_helpers import app_vendor, consent, customer_project, ext_vendor

DAY = datetime(2026, 11, 2, 1, 0, tzinfo=UTC)  # 서울 10시
NIGHT = datetime(2026, 11, 2, 13, 0, tzinfo=UTC)  # 서울 22시
BODY = "안녕하세요. 마포구 아파트 도배 가견적을 받고 싶어요. 실측 가능한 날을 알려 주세요."


def world(api):
    v = ext_vendor("c-ok", name="가짜동의업체")
    consent(v)
    plain = ext_vendor("c-plain", name="가짜연락처없음")
    far = ext_vendor("c-far", name="가짜부산", sido="busan", sgg="해운대구")
    token, pid = customer_project(api)
    return {"v": v, "plain": plain, "far": far, "token": token, "pid": pid}


def send(api, w, vendor=None, **over):
    data = {"project_id": w["pid"], "trade": "dobae", "vendor_id": vendor or w["v"], "body": BODY}
    return api.post("/contact-requests", json={**data, "consent": True, **over})


def dispatch(sender, now=DAY):
    async def go():
        async with SessionLocal() as s:
            return await service.dispatch_contacts(s, sender, now=now)

    return asyncio.run(go())


def status():
    return [r["status"] for r in query("select status from contact_requests order by created_at")]


def history():
    rows = query("select from_status, to_status, reason from contact_request_events order by at")
    return [(r["from_status"], r["to_status"], r["reason"]) for r in rows]


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(settings, "contact_send_enabled", True)
    monkeypatch.setattr(settings, "contact_sender_contact", "help@mitjip.example")


def test_consent_and_body_are_required(api):
    w = world(api)
    data = {"project_id": w["pid"], "trade": "dobae", "vendor_id": w["v"], "body": BODY}
    assert api.post("/contact-requests", json=data).status_code == 422  # 동의 없음
    assert send(api, w, consent=False).status_code == 422
    assert send(api, w, body="짧아요").status_code == 422
    assert send(api, w, body=BODY + " https://evil.example/x").status_code == 422  # 링크 금지
    assert send(api, w, body="가" * 801).status_code == 422
    assert query("select count(*) n from contact_requests")[0]["n"] == 0


def test_flag_off_keeps_it_queued_and_sends_nothing(api):
    w = world(api)
    r = send(api, w)
    assert r.status_code == 201, r.text
    out = r.json()
    assert (out["status"], out["channel"], out["send_enabled"]) == ("queued", "sms", False)
    assert out["notice"] == OFF_NOTICE
    assert history() == [(None, "draft", None), ("draft", "queued", "consent")]
    (row,) = query("select consented_at, customer_id from contact_requests")
    assert row["consented_at"] is not None
    sender = DryRunSender()
    assert dispatch(sender) == {"skipped": "disabled"}
    assert asyncio.run(tasks.dispatch_contact_requests({"sender": sender})) == {
        "skipped": "disabled"
    }
    assert sender.outbox == [] and status() == ["queued"]


def test_no_sender_contact_or_night_means_wait(api, on, monkeypatch):
    w = world(api)
    send(api, w)
    sender = DryRunSender()
    assert dispatch(sender, NIGHT) == {"skipped": "night"}
    monkeypatch.setattr(settings, "contact_sender_contact", "")
    assert dispatch(sender, DAY) == {"skipped": "no_sender_contact"}
    assert sender.outbox == [] and status() == ["queued"]


def test_daytime_send_shows_sender_and_optout_link(api, on):
    w = world(api)
    send(api, w)
    sender = DryRunSender()
    assert dispatch(sender) == {"sent": 1}
    (msg,) = sender.outbox
    token = query("select optout_token from ext_vendors where source_id = 'c-ok'")[0][
        "optout_token"
    ]
    assert (msg.channel, msg.to) == ("sms", "01000000001")
    assert msg.text.startswith(BODY) and "[믿집]" in msg.text and "help@mitjip.example" in msg.text
    assert msg.text.endswith(f"받지 않으려면: http://localhost:3000/opt-out?t={token}")
    (row,) = query("select status, sender, sent_at from contact_requests")
    assert (row["status"], row["sender"]) == ("sent", "dry_run") and row["sent_at"]
    assert history()[-1] == ("queued", "sent", None)
    card = next(
        c
        for c in api.get(f"/projects/{w['pid']}/sourcing").json()["candidates"]
        if c["id"] == w["v"]
    )
    assert card["route"] == "proxy" and card["requests"][0]["label"] == DRY_RUN_LABEL
    assert dispatch(DryRunSender()) == {}  # 다시 돌려도 두 번 보내지 않는다


def test_send_failure_is_recorded(api, on):
    w = world(api)
    send(api, w)

    class Broken(DryRunSender):
        async def send(self, msg):
            raise SendError("provider_down")

    assert dispatch(Broken()) == {"failed": 1}
    assert status() == ["failed"] and history()[-1] == ("queued", "failed", "send_error")


def test_optout_link_blocks_and_hides_the_vendor(api, on):
    w = world(api)
    send(api, w)
    token = query("select optout_token from ext_vendors where source_id = 'c-ok'")[0][
        "optout_token"
    ]
    api.cookies.clear()  # 업체는 로그인하지 않는다
    assert api.post("/directory/opt-out", json={"token": "x" * 30}).status_code == 404
    assert api.post("/directory/opt-out", json={"token": "bad token!"}).status_code == 422
    ok = api.post("/directory/opt-out", json={"token": token})
    assert ok.status_code == 200 and ok.json()["done"] is True
    assert api.post("/directory/opt-out", json={"token": token}).status_code == 200  # 두 번 눌러도
    (v,) = query("select opted_out from ext_vendors where source_id = 'c-ok'")
    assert v["opted_out"] is True
    assert query("select count(*) n from ext_vendor_contacts")[0]["n"] == 0  # 동의 연락처도 지운다
    assert query("select count(*) n from contact_optouts")[0]["n"] == 2  # 출처 번호 + 연락처 해시
    assert dispatch(DryRunSender()) == {"blocked": 1}
    assert history()[-1] == ("queued", "blocked", "opted_out")
    use(api, w["token"])
    ids = [c["id"] for c in api.get(f"/projects/{w['pid']}/sourcing").json()["candidates"]]
    assert w["v"] not in ids
    assert send(api, w).json()["error"]["code"] == "opted_out"


def test_closed_vendor_is_blocked_and_cannot_be_requested(api, on):
    w = world(api)
    assert send(api, w).status_code == 201
    query("update ext_vendors set closed_at = now() where id = $1", uuid.UUID(w["v"]))
    assert dispatch(DryRunSender()) == {"blocked": 1}
    assert history()[-1] == ("queued", "blocked", "closed")
    assert send(api, w).json()["error"]["code"] == "vendor"


def test_consent_and_contact_history_survive_vendor_deletion_attempts(api):
    w = world(api)
    delete = "delete from ext_vendors where id = $1"
    with pytest.raises(asyncpg.exceptions.ForeignKeyViolationError):
        query(delete, uuid.UUID(w["v"]))  # 동의 연락처가 있는 업체
    assert send(api, w).status_code == 201
    query("delete from ext_vendor_contacts")
    with pytest.raises(asyncpg.exceptions.ForeignKeyViolationError):
        query(delete, uuid.UUID(w["v"]))  # 대신 연락 기록이 있는 업체
    query(delete, uuid.UUID(w["plain"]))  # 기록이 없는 업체는 지울 수 있다
    assert query("select count(*) n from contact_requests")[0]["n"] == 1


def test_only_consented_vendors_in_the_region(api):
    w = world(api)
    assert send(api, w, vendor=w["plain"]).json()["error"]["code"] == "no_contact"
    assert send(api, w, vendor=w["far"]).json()["error"]["code"] == "vendor"
    assert send(api, w, vendor=str(uuid.uuid4())).json()["error"]["code"] == "vendor"
    assert send(api, w, trade="tile").json()["error"]["code"] == "trade"
    assert send(api, w).status_code == 201
    dup = send(api, w)
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "already_requested"


def test_daily_limits_per_customer_and_vendor(api, on, monkeypatch):
    monkeypatch.setattr(settings, "contact_daily_per_vendor", 1)
    w = world(api)
    assert send(api, w).status_code == 201
    _, other_pid = customer_project(api, "second@mitjip.test")
    other = {**w, "pid": other_pid}
    limited = send(api, other)
    assert limited.status_code == 429 and limited.json()["error"]["code"] == "contact_limit"

    monkeypatch.setattr(settings, "contact_daily_per_vendor", 5)
    monkeypatch.setattr(settings, "contact_daily_per_customer", 1)
    assert send(api, other).status_code == 201
    v2 = ext_vendor("c-ok2", name="가짜동의업체2")
    consent(v2, value="01000000002")
    assert send(api, other, vendor=v2).status_code == 429  # 고객 한 명 하루 한도

    # 보낼 때도 업체당 하루 한도를 지킨다: 넘으면 다음 날로 미룬다
    monkeypatch.setattr(settings, "contact_daily_per_vendor", 1)
    assert dispatch(DryRunSender()) == {"sent": 1, "deferred": 1}
    assert sorted(status()) == ["queued", "sent"]


def test_permissions(api):
    w = world(api)
    signup(api, "other@mitjip.test")
    assert send(api, w).status_code == 404  # 남의 프로젝트
    vendor_token, _ = app_vendor(api, "app@mitjip.test", "가짜앱업체")
    use(api, vendor_token)
    assert send(api, w).status_code == 403
    api.cookies.clear()
    assert send(api, w).status_code == 401


def test_optout_is_rate_limited(api):
    for _ in range(20):
        api.post("/directory/opt-out", json={"token": "y" * 30})
    r = api.post("/directory/opt-out", json={"token": "y" * 30})
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0
