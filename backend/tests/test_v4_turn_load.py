"""SSE 턴 부하 지킴(부하 QA 1 · 고칠 제안 2 · 7, 보안 I2 · 예외 P15): 로그인 확인은 짧은 세션으로 끝내 스트림 동안
DB 연결을 쥐지 않기 · 넘칠 때 바로 503(Retry-After)으로 거절(턴 자리 · 풀 기다림) · 턴 본문 한도 16KB. 유료 호출 0회."""

import json
import uuid
from datetime import timedelta

import asyncpg
import pytest
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from v3_kb import repo_index

from app import db
from app.assistant import runtime
from app.assistant import service as assistant_service
from app.chat import service as chat_service
from app.config import settings
from app.shared import request_guards as guards
from tests.conftest import TEST_DB, TEST_DSN, query
from tests.helpers import make_admin, signup, use, vendor_signup
from tests.test_v3_project_home import HOME
from tests.test_vendor_profile import approved_vendor

KB = 1024


@pytest.fixture(autouse=True)
def repo_knowledge(monkeypatch):
    """시험 DB에는 지식 자료가 없어 운영과 같은 CSV 색인을 넘긴다(무료 답 파이프라인용)."""
    from app.knowledge import service as knowledge

    async def index(_s):
        return repo_index()

    monkeypatch.setattr(knowledge, "index", index)


def home(api, email: str = "load@mitjip.test") -> tuple[str, str]:
    token = signup(api, email)
    r = api.post("/projects", json=HOME)
    assert r.status_code == 201, r.text
    return token, r.json()["id"]


def turn(api, pid: str, text: str = "오늘 뭐 하면 돼요?"):
    body = {"project_id": pid, "client_key": uuid.uuid4().hex, "text": text}
    return api.post("/assistant/turns", json=body)


def vendor_turn(api, text: str = "오늘 할 일 알려 주세요"):
    return api.post("/vendor/assistant/turns", json={"client_key": uuid.uuid4().hex, "text": text})


def ai_turn(api, text: str = "합지랑 실크 중에 뭐로 해야 해요?"):
    return api.post("/ai/turns", json={"client_key": uuid.uuid4().hex, "text": text})


def done(r) -> None:
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/event-stream")
    assert "event: done" in r.text, r.text[-300:]


async def held() -> list[str]:
    """이 시험 DB에서 트랜잭션을 연 채 쉬는 연결(앱이 쥔 것)의 마지막 SQL"""
    conn = await asyncpg.connect(TEST_DSN)
    try:
        rows = await conn.fetch(
            "select query from pg_stat_activity where datname = $1"
            " and pid <> pg_backend_pid() and state like 'idle in transaction%'",
            TEST_DB,
        )
        return [r["query"] for r in rows]
    finally:
        await conn.close()


@pytest.fixture
def mid_turn(monkeypatch):
    """턴 일이 도는 동안(비서: 스트림을 연 뒤 · AI 칸: 답을 만드는 동안) 앱이 쥔 연결과 쓰는 턴 자리를 적는다."""
    seen: list[dict] = []

    async def note() -> None:
        slots = getattr(guards, "TURNS", None)
        seen.append({"held": await held(), "slots": slots.used if slots else None})

    run_turn = runtime.run_turn
    ai = chat_service.ai_turn

    async def spy_run(ctx, emit):
        await note()
        return await run_turn(ctx, emit)

    async def spy_ai(user, body, today, on_part=None):
        await note()
        return await ai(user, body, today, on_part=on_part)

    monkeypatch.setattr(runtime, "run_turn", spy_run)
    monkeypatch.setattr(chat_service, "ai_turn", spy_ai)
    return seen


# ---- 1. 로그인 확인은 짧은 세션으로 (스트림 동안 연결 0) ----


def test_customer_turn_holds_no_db_connection_while_streaming(api, mid_turn):
    _, pid = home(api)
    done(turn(api, pid))
    assert [x["held"] for x in mid_turn] == [[]]


def test_vendor_turn_holds_no_db_connection_while_streaming(api, mid_turn):
    approved_vendor(api, "load-vendor@mitjip.test")
    done(vendor_turn(api))
    assert [x["held"] for x in mid_turn] == [[]]


def test_ai_turn_holds_no_db_connection_while_answering(api, mid_turn):
    use(api, signup(api))
    done(ai_turn(api))
    assert [x["held"] for x in mid_turn] == [[]]


def test_turn_routes_keep_login_role_owner_and_approval_rules(api):
    pid = str(uuid.uuid4())
    for r in (turn(api, pid), vendor_turn(api), ai_turn(api)):
        assert r.status_code == 401 and r.json()["error"]["code"] == "login_required"
    use(api, make_admin(api))
    for r in (turn(api, pid), vendor_turn(api), ai_turn(api)):
        assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"
    assert vendor_signup(api, email="wait@mitjip.test").status_code == 201  # 승인 전 업체
    r = vendor_turn(api)
    assert r.status_code == 403 and r.json()["error"]["code"] == "vendor_not_approved"
    assert turn(api, pid).status_code == 403 and ai_turn(api).status_code == 403
    _, other = home(api, "other@mitjip.test")
    home(api, "owner@mitjip.test")
    r = turn(api, other)  # 남의 공사
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    assert vendor_turn(api).status_code == 403  # 고객이 업체 턴


def test_brief_login_writes_last_seen_once_an_hour_and_refuses_expired(api):
    _, pid = home(api)
    query("update user_sessions set last_seen_at = now() - interval '2 hours'")
    done(turn(api, pid))
    (row,) = query("select now() - last_seen_at as ago from user_sessions")
    assert row["ago"] < timedelta(minutes=1)
    query("update user_sessions set expires_at = now() - interval '1 minute'")
    r = turn(api, pid)
    assert r.status_code == 401 and r.json()["error"]["code"] == "login_required"


# ---- 2. 넘칠 때 정직하게 거절 (503 + Retry-After) ----


def test_pool_wait_timeout_is_503_with_retry_after(api, monkeypatch):
    _, pid = home(api)

    async def pool_empty(*_a, **_k):
        raise PoolTimeoutError("QueuePool limit of size 5 overflow 5 reached, connection timed out")

    monkeypatch.setattr(assistant_service, "start_turn", pool_empty)
    r = turn(api, pid)
    assert r.status_code == 503 and r.json()["error"]["code"] == "unavailable"
    assert r.headers["retry-after"] == str(settings.busy_retry_after)


def test_pool_waits_less_than_ten_seconds():
    assert db.POOL["pool_timeout"] == settings.db_pool_timeout < 10
    assert settings.busy_retry_after >= 1 and settings.turn_slots >= 1


def test_full_turn_slots_refuse_at_once_after_login(api, monkeypatch):
    _, pid = home(api)
    monkeypatch.setattr(settings, "turn_slots", 1)
    assert guards.TURNS.take()  # 다른 턴이 자리를 쥔 것처럼
    try:
        for r in (turn(api, pid), ai_turn(api)):
            assert r.status_code == 503 and r.json()["error"]["code"] == "busy"
            assert r.headers["retry-after"] == str(settings.busy_retry_after)
            assert r.json()["error"]["message"].endswith("해 주세요.")
        approved_vendor(api, "busy-vendor@mitjip.test")
        r = vendor_turn(api)
        assert r.status_code == 503 and r.json()["error"]["code"] == "busy"
        api.cookies.clear()
        assert turn(api, pid).status_code == 401  # 로그인 확인이 먼저(자리 다툼에 끼지 않음)
    finally:
        guards.TURNS.give()
    assert guards.TURNS.used == 0


def test_turn_slot_is_held_while_streaming_and_given_back(api, monkeypatch, mid_turn):
    _, pid = home(api)
    monkeypatch.setattr(settings, "turn_slots", 1)
    done(turn(api, pid))
    assert [x["slots"] for x in mid_turn] == [1]  # 스트림 동안 자리를 쥐고
    assert guards.TURNS.used == 0  # 끝나면 돌려준다
    r = turn(api, str(uuid.uuid4()))  # 스트림 전 오류(남의 · 없는 공사)여도 돌려준다
    assert r.status_code == 404 and guards.TURNS.used == 0
    done(turn(api, pid))  # 자리가 하나여도 차례로는 계속 된다


# ---- 3. 턴 본문 한도 16KB (/ai/turns와 같게) ----


@pytest.mark.parametrize("path", ["/assistant/turns", "/vendor/assistant/turns"])
def test_turn_body_over_16kb_is_413_before_reading(api, path):
    assert guards.limit_for(path) == guards.limit_for("/ai/turns") == 16 * KB
    big = b'{"text": "' + b"x" * (16 * KB) + b'"}'
    r = api.post(path, content=big, headers={"content-type": "application/json"})
    assert r.status_code == 413 and r.json()["error"]["code"] == "too_large"


def test_longest_turn_body_fits_16kb(api):
    """글 1,000자를 모두 \\u 이스케이프(이모지 짝 12바이트)로 보내고 고르기 5개 · 카드 id를 채워도 한도 안"""
    use(api, signup(api))
    body = {
        "project_id": str(uuid.uuid4()),
        "client_key": "k" * 64,
        "text": "\U0001f600" * 1000,
        "context": {"card_id": "c" * 64, "choice": ["\U0001f600" * 40] * 5},
    }
    raw = json.dumps(body).encode()
    assert 14 * KB < len(raw) < 16 * KB
    r = api.post("/assistant/turns", content=raw, headers={"content-type": "application/json"})
    assert r.status_code == 404  # 본문 한도는 넘었고 남의 · 없는 공사라 404
