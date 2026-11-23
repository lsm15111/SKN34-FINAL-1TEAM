"""v4 비용 장부 · 상한(usage): 가격 셈, 사용자 하루 · 새 계정(한 계정 · 합) · 서비스 하루 · 전체 상한
(80% 경고 · 90% 막음), Redis 정수 카운터와 Redis가 안 될 때의 장부 합계, llm_usage 제약. 유료 호출 0회."""

import asyncio
import logging
import os
import subprocess
import sys
import uuid
from datetime import datetime, timedelta

import asyncpg
import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from app import queue
from app.agent import llm
from app.config import Settings, settings
from app.shared import clock
from app.usage import prices, service
from tests.conftest import BACKEND, query
from tests.test_v4_llm_claude import Plan, _user, rows, run


@pytest.fixture
def script():
    llm.clear_stubs()
    yield llm.set_claude_script
    llm.clear_stubs()


def spend(user_id=None, purpose="composer", model="claude-sonnet-5-5", **tokens):
    return service.record(user_id=user_id, turn_id=None, purpose=purpose, model=model, **tokens)


def test_prices_per_model():
    ver = prices.PRICE_VER
    # Haiku 프롬프트 10만 토큰까지: 입력 $0.10 · 출력 $0.50 (백만 토큰당). 출력은 프롬프트 길이에 넣지 않는다
    assert prices.cost("claude-haiku-5-5", input_tokens=100_000, output_tokens=1_000_000) == (
        10_000 + 500_000,
        ver,
    )
    # 프롬프트(입력 + 캐시 읽기 + 캐시 쓰기)가 10만을 넘으면 비싼 표: 입력 $0.50 · 읽기 $0.05 · 출력 $2.50
    cost, _ = prices.cost(
        "claude-haiku-5-5", input_tokens=50_000, cache_read=60_000, output_tokens=1000
    )
    assert cost == 25_000 + 3_000 + 2_500
    # Sonnet: 5분 캐시 쓰기 $2.50 · 1시간 쓰기 $4 · 읽기 $0.10 · 출력 $10
    assert prices.cost("claude-sonnet-5-5", cache_write_5m=1_000_000)[0] == 2_500_000
    assert prices.cost("claude-sonnet-5-5", cache_write_1h=1_000_000)[0] == 4_000_000
    assert prices.cost("claude-sonnet-5-5", cache_read=1_000_000)[0] == 100_000
    # Opus: 입력 $4 · 출력 $20, 웹 검색 1번 $0.01
    assert prices.cost("claude-opus-5-5", input_tokens=1_000_000)[0] == 4_000_000
    assert prices.cost("claude-opus-5-5", output_tokens=1_000_000, web_searches=3)[0] == 20_030_000
    assert prices.cost("claude-haiku-5-5", input_tokens=1)[0] == 1  # 올림
    # 날짜가 붙은 이름은 앞부분으로 찾고, 모르는 모델은 가장 비싼 값으로 어림한다
    assert prices.cost("claude-haiku-5-5-20261101", input_tokens=10) == (1, ver)
    assert prices.cost("made-up-model", input_tokens=1_000_000) == (4_000_000, f"{ver}:fallback")
    # OpenAI(공식 가격 문서 2026-11-23): terra 입력 $1 · 30분 쓰기 $1.25 · 읽기 $0.05 · 출력 $5, luna는 10분의 1.
    # 입력이 27만 2천을 넘으면 비싼 표(terra 입력 $2 · 출력 $7.50)
    assert prices.cost("gpt-6.1-terra", input_tokens=100_000) == (100_000, ver)
    got = prices.cost("gpt-6.1-terra-2026-10-01", cache_read=100_000, cache_write_5m=100_000)
    assert got == (5_000 + 125_000, ver)
    assert prices.cost("gpt-6.1-terra", input_tokens=300_000, output_tokens=1000)[0] == 607_500
    assert prices.cost("gpt-6-luna", input_tokens=100_000, output_tokens=100_000)[0] == 60_000
    assert prices.cost("gpt-6-luna", output_tokens=1, web_searches=1)[0] == 10_001


def test_service_day_cap_warns_at_80_and_blocks_at_90(monkeypatch, caplog):
    monkeypatch.setattr(settings, "llm_cap_service_day_usd", 0.01)  # 10,000 마이크로달러

    async def go():
        await spend(output_tokens=850)  # Sonnet 출력 850 × $10 = 8,500
        await service.allow(None, "composer")  # 85%: 경고만
        await spend(output_tokens=50)  # +500 = 9,000
        with pytest.raises(service.OverCap) as e:
            await service.allow(None, "composer")
        return e.value

    with caplog.at_level(logging.WARNING, logger="app.usage.service"):
        e = run(monkeypatch, go)
    assert (e.scope, e.spent, e.cap) == ("service_day", 9000, 10_000)
    logged = [r.getMessage() for r in caplog.records]
    assert any("80%" in m for m in logged) and any("90%" in m for m in logged)


def test_user_day_cap_blocks_only_that_user(monkeypatch):
    a, b = _user("cap-a@mitjip.test"), _user("cap-b@mitjip.test")
    monkeypatch.setattr(settings, "llm_cap_user_day_usd", 0.001)  # 1,000 마이크로달러

    async def go():
        await spend(a, "assistant", "claude-haiku-5-5", output_tokens=1800)  # 900 = 90%
        with pytest.raises(service.OverCap) as e:
            await service.allow(a, "assistant")
        await service.allow(b, "assistant")  # 다른 사용자는 그대로
        await service.allow(None, "nudge")  # 사용자 없는 일(worker)도 그대로
        return e.value.scope

    assert run(monkeypatch, go) == "user_day"


def test_redis_counter_starts_from_llm_usage_and_counts_up(monkeypatch):
    async def go():
        await spend(output_tokens=100)  # 1,000: 키가 없어 장부에만
        day, _ = (b for b in service.buckets(None))
        assert await queue.redis.get(day.key) is None
        await service.allow(None, "composer")  # 장부 합계로 채운다
        assert int(await queue.redis.get(day.key)) == 1000
        await spend(output_tokens=50)  # 키가 있으니 +500
        total = service.buckets(None)[1]
        return (
            int(await queue.redis.get(day.key)),
            int(await queue.redis.get(total.key) or 0),
            await queue.redis.ttl(day.key),
        )

    day_n, total_n, ttl = run(monkeypatch, go)
    # 전체 키는 allow가 채운 뒤라 같은 값. 키는 SYNC_S 안에 장부 합계로 다시 맞춘다
    assert (day_n, total_n) == (1500, 1500) and 0 < ttl <= service.SYNC_S


class _Down:
    """연결이 안 되는 Redis 자리."""

    async def get(self, *a, **k):
        raise RedisConnectionError("down")

    set = eval = get


def test_counts_from_llm_usage_when_redis_is_down(monkeypatch):
    monkeypatch.setattr(settings, "llm_cap_service_day_usd", 0.01)
    monkeypatch.setattr(queue, "redis", _Down())

    async def go():
        assert await spend(output_tokens=900) == 9000  # 장부에는 남는다
        with pytest.raises(service.OverCap):
            await service.allow(None, "memory")

    asyncio.run(go())
    (row,) = rows()
    assert row["cost_micros"] == 9000


# ---- 새 계정 몫(보안 QA M4): 가입 7일 안은 한 계정 하루 $0.20 · 새 계정 모두 합쳐 하루 $1 ----

CAPS = (
    "llm_cap_user_day_usd",
    "llm_cap_new_user_day_usd",
    "llm_cap_new_pool_day_usd",
    "llm_cap_service_day_usd",
    "llm_cap_total_usd",
    "llm_new_user_days",
)


@pytest.fixture
def caps(monkeypatch):
    """상한을 설정 기본값으로 둔다(로컬 환경변수와 상관없이)."""
    for name in CAPS:
        monkeypatch.setattr(settings, name, Settings.model_fields[name].default)


def _joined(uid: uuid.UUID, at: datetime) -> uuid.UUID:
    query("update users set created_at = $2 where id = $1", uid, at)
    return uid


def _account(email: str, role: str, at: datetime) -> uuid.UUID:
    """at에 가입한 role 계정."""
    uid = uuid.uuid4()
    query(
        "insert into users (id, email, password_hash, name, role, created_at)"
        " values ($1, $2, 'x', '시험', $3, $4)",
        uid,
        email,
        role,
        at,
    )
    return uid


def _go(monkeypatch, redis: str, make):
    """redis가 up이면 이 루프의 Redis로, down이면 연결이 안 되는 Redis(장부 합계로 셈)로 돌린다."""
    if redis == "down":
        monkeypatch.setattr(queue, "redis", _Down())
        return asyncio.run(make())
    return run(monkeypatch, make)


def test_cap_defaults():
    got = {n: Settings.model_fields[n].default for n in (*CAPS, "llm_cap_turn_usd")}
    assert got == {
        "llm_cap_user_day_usd": 1.0,
        "llm_cap_new_user_day_usd": 0.2,
        "llm_cap_new_pool_day_usd": 1.0,
        "llm_cap_service_day_usd": 5.0,
        "llm_cap_total_usd": 45.0,
        "llm_new_user_days": 7,
        "llm_cap_turn_usd": 0.06,
    }


def test_new_account_buckets_follow_join_time(monkeypatch, caps):
    uid, now = uuid.uuid4(), datetime(2026, 11, 22, 12, 0, tzinfo=clock.SEOUL)

    def scopes(joined):
        return {b.scope: b.cap for b in service.buckets(uid, now, joined)}

    old = {"user_day": 1_000_000, "service_day": 5_000_000, "total": 45_000_000}
    new = old | {"new_user_day": 200_000, "new_pool_day": 1_000_000}
    assert scopes(now - timedelta(days=7) + timedelta(seconds=1)) == new  # 7일이 안 됨
    assert [b.scope for b in service.buckets(uid, now, now)] == [
        "user_day", "new_user_day", "new_pool_day", "service_day", "total",
    ]  # fmt: skip
    assert scopes(now - timedelta(days=7)) == old  # 꼭 7일이면 새 계정이 아니다
    assert scopes(now - timedelta(days=8)) == old
    assert scopes(None) == old  # 가입 시각을 모름(사용자 줄 없음)
    # 사용자 없는 일(worker 등)은 서비스 하루 · 전체만 본다
    assert [b.scope for b in service.buckets(None, now, now)] == ["service_day", "total"]
    monkeypatch.setattr(settings, "llm_new_user_days", 0)  # 0이면 새 계정 몫을 보지 않는다
    assert scopes(now) == old


@pytest.mark.parametrize("redis", ["up", "down"])
def test_new_account_blocked_at_90_percent_of_20_cents(monkeypatch, caplog, caps, redis):
    a = _user("new-a@mitjip.test")  # 방금 가입

    async def go():
        await spend(a, "assistant", output_tokens=17_000)  # Sonnet 출력 × $10 = $0.17(85%)
        await service.allow(a, "assistant")  # 경고만
        await spend(a, "assistant", output_tokens=1_000)  # $0.18 = $0.20의 90%
        with pytest.raises(service.OverCap) as e:
            await service.allow(a, "assistant")
        return e.value

    with caplog.at_level(logging.WARNING, logger="app.usage.service"):
        e = _go(monkeypatch, redis, go)
    assert (e.scope, e.spent, e.cap) == ("new_user_day", 180_000, 200_000)
    assert any("80%" in r.getMessage() and "new_user_day" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("redis", ["up", "down"])
def test_account_older_than_7_days_keeps_one_dollar(monkeypatch, caps, redis):
    old = _joined(_user("old@mitjip.test"), clock.now_utc() - timedelta(days=8))
    new = _user("new@mitjip.test")

    async def go():
        await spend(old, "assistant", output_tokens=18_000)  # $0.18: 새 계정이면 막힐 돈
        await service.allow(old, "assistant")
        await spend(old, "assistant", output_tokens=71_000)  # $0.89
        await service.allow(old, "assistant")
        await service.allow(new, "assistant")  # 오래된 계정의 돈은 새 계정 합에 들어가지 않는다
        await spend(old, "assistant", output_tokens=1_000)  # $0.90 = $1.00의 90%
        with pytest.raises(service.OverCap) as e:
            await service.allow(old, "assistant")
        return e.value

    e = _go(monkeypatch, redis, go)
    assert (e.scope, e.spent, e.cap) == ("user_day", 900_000, 1_000_000)


@pytest.mark.parametrize("redis", ["up", "down"])
def test_new_accounts_share_one_dollar_a_day(monkeypatch, caps, redis):
    news = [_user(f"pool-{i}@mitjip.test") for i in range(7)]
    old = _joined(_user("pool-old@mitjip.test"), clock.now_utc() - timedelta(days=30))

    async def go():
        await spend(old, "assistant", output_tokens=50_000)  # 오래된 계정 $0.50: 새 계정 합 밖
        for uid in news[:6]:
            await service.allow(uid, "assistant")
            await spend(uid, "assistant", output_tokens=15_000)  # 한 계정 $0.15(75%)씩, 합 $0.90
        with pytest.raises(service.OverCap) as e:
            await service.allow(news[6], "assistant")  # 아직 안 쓴 새 계정도 막힌다
        await service.allow(old, "assistant")  # 오래된 계정 · 사용자 없는 일은 그대로
        await service.allow(None, "nudge")
        (pool,) = [b for b in service.buckets(news[6], joined=clock.now_utc()) if b.new_days]
        return e.value, await service.spent(pool), await service.db_spent(pool)

    e, counted, summed = _go(monkeypatch, redis, go)
    assert (e.scope, e.spent, e.cap) == ("new_pool_day", 900_000, 1_000_000)
    assert counted == summed == 900_000  # Redis 카운터와 장부 합계가 같다


@pytest.mark.parametrize("redis", ["up", "down"])
def test_vendor_and_admin_are_not_new_accounts(monkeypatch, caps, redis):
    """업체(사업자등록증 + 관리자 승인) · 관리자(CLI로만)는 가입 1일이어도 새 계정 몫을 보지 않는다."""
    day_ago = clock.now_utc() - timedelta(days=1)
    vendor = _account("v1@mitjip.test", "vendor", day_ago)
    admin = _account("a1@mitjip.test", "admin", day_ago)
    customer = _account("c1@mitjip.test", "customer", day_ago)

    async def go():
        await service.allow(customer, "assistant")  # 새 계정 합 카운터를 먼저 채운다
        for uid in (vendor, admin, customer):
            await spend(uid, "assistant", output_tokens=19_000)  # $0.19 = $0.20의 95%
        await service.allow(vendor, "assistant")
        await service.allow(admin, "assistant")
        with pytest.raises(service.OverCap) as e:
            await service.allow(customer, "assistant")
        (pool,) = [b for b in service.buckets(customer, joined=day_ago) if b.new_days]
        return e.value, await service.spent(pool), await service.db_spent(pool)

    e, counted, summed = _go(monkeypatch, redis, go)
    assert (e.scope, e.spent, e.cap) == ("new_user_day", 190_000, 200_000)
    assert counted == summed == 190_000  # 업체 · 관리자 돈은 새 계정 합에 들어가지 않는다


def test_new_pool_counts_only_calls_made_while_new(caps):
    """새 계정 합의 장부 합계는 오늘, 부른 때 가입 7일 안이던 고객 계정의 호출만 센다."""
    now = datetime(2026, 11, 22, 12, 0, tzinfo=clock.SEOUL)
    x = _joined(_user("x@mitjip.test"), now - timedelta(days=7, hours=2))  # 오늘 10시에 7일이 됨
    y = _joined(_user("y@mitjip.test"), now - timedelta(hours=4))  # 오늘 8시 가입
    z = _joined(_user("z@mitjip.test"), now - timedelta(days=30))
    v = _account("v@mitjip.test", "vendor", now - timedelta(days=1))
    a = _account("a@mitjip.test", "admin", now - timedelta(days=1))
    sql = (
        "insert into llm_usage (id, user_id, purpose, model, price_ver, ok, cost_micros, created_at)"
        " values ($1, $2, 'assistant', 'claude-haiku-5-5', 'v', true, $3, $4)"
    )
    for uid, hours_ago, cost in [
        (x, 3, 1),  # 9시: 새 계정이던 때라 센다
        (x, 1, 10),  # 11시: 7일이 지난 뒤라 안 센다
        (x, 13, 100),  # 어제 23시: 오늘이 아니다
        (y, 2, 1000),  # 10시: 센다
        (z, 1, 10_000),  # 오래된 계정
        (None, 1, 100_000),  # 사용자 없는 일
        (v, 1, 1_000_000),  # 가입 1일 업체
        (a, 1, 10_000_000),  # 가입 1일 관리자
    ]:
        query(sql, uuid.uuid4(), uid, cost, now - timedelta(hours=hours_ago))
    (pool,) = [b for b in service.buckets(y, now, now - timedelta(hours=4)) if b.new_days]
    assert asyncio.run(service.db_spent(pool)) == 1001


def test_join_time_is_cached_and_unknown_join_time_blocks(monkeypatch, caps):
    """가입 시각 · 역할은 Redis에 둔다: DB가 잠깐 안 돼도 Redis 카운터로 센다(전과 같음).
    가입 시각을 Redis · DB 어디서도 못 읽으면 막는다(닫힘 쪽). 새 계정 몫을 끄면 가입 시각을 읽지 않는다."""
    a = _user("cached@mitjip.test")

    def no_db():
        raise OSError("DB 연결 안 됨")

    async def go():
        assert await llm.budget_ok(a, "t")  # 가입 시각 · 카운터를 Redis에 채운다
        key = f"llm:newacct:{service._tag()}:{a}"
        assert await queue.redis.get(key) is not None
        monkeypatch.setattr(service, "SessionLocal", no_db)
        cached = await llm.budget_ok(a, "t")
        await queue.redis.set(key, "모름")  # 읽을 수 없는 값이면 DB로 가는데 DB도 안 된다
        unknown = await llm.budget_ok(a, "t")
        monkeypatch.setattr(settings, "llm_new_user_days", 0)
        return cached, unknown, await llm.budget_ok(a, "t")

    assert run(monkeypatch, go) == (True, False, True)


def test_over_cap_stops_paid_call_before_request(monkeypatch, script):
    monkeypatch.setattr(settings, "llm_cap_total_usd", 0)  # 0이면 모두 막는다
    log = script([{"json": {"reply": "x"}}])
    with pytest.raises(llm.OverBudget) as e:
        run(monkeypatch, lambda: llm.structured("composer", Plan, [("system", "s"), ("user", "u")]))
    assert e.value.scope == "total" and isinstance(e.value, llm.LLMError)
    assert log == [] and rows() == []


def test_v3_caller_falls_back_when_over_cap(monkeypatch, script):
    from app.agent.v3 import general

    monkeypatch.setattr(settings, "llm_cap_service_day_usd", 0)
    log = script([{"json": {"ok": True, "lead": "x", "kind": "body", "items": []}}])
    dropped: list[str] = []
    out = run(
        monkeypatch,
        lambda: general.explain("몰딩이 뭐예요?", route="guide", trade=None, dropped=dropped),
    )
    assert out == [] and dropped == ["일반 설명 실패"] and log == []


def test_guard_blocks_when_cap_cannot_be_checked(monkeypatch, script):
    async def broken(*a, **k):
        raise OSError("DB 연결 안 됨")

    monkeypatch.setattr(service, "allow", broken)
    log = script([{"json": {"send": True, "text": "x"}}])
    with pytest.raises(llm.OverBudget) as e:
        asyncio.run(llm.claude_json("nudge", Plan, "s", "q"))
    assert e.value.scope == "unknown" and log == []


def test_record_keeps_cost_when_user_is_gone(monkeypatch):
    ghost = uuid.uuid4()  # users에 없는 사람(그사이 탈퇴)
    run(monkeypatch, lambda: spend(ghost, "assistant", "claude-haiku-5-5", output_tokens=10))
    (row,) = rows()
    assert (row["user_id"], row["cost_micros"]) == (None, 5)
    uid = _user("gone@mitjip.test")
    run(monkeypatch, lambda: spend(uid, "assistant", "claude-haiku-5-5", output_tokens=10))
    query("delete from users where id = $1", uid)  # 탈퇴해도 비용 줄은 남는다(SET NULL)
    assert [r["user_id"] for r in rows()] == [None, None]


def test_record_rejects_unknown_purpose():
    with pytest.raises(ValueError):
        asyncio.run(service.record(user_id=None, turn_id=None, purpose="chat", model="m"))


def test_llm_usage_constraints_and_no_text_columns():
    sql = (
        "insert into llm_usage (id, purpose, model, price_ver, ok, error)"
        " values ($1, $2, $3, 'v', $4, $5)"
    )
    query(sql, uuid.uuid4(), "assistant", "claude-haiku-5-5", True, None)
    bad = [
        ("chat", "m", True, None),  # 모르는 목적
        ("assistant", " ", True, None),  # 빈 모델
        ("assistant", "m", False, None),  # 실패인데 종류 없음
        ("assistant", "m", True, "boom"),  # 성공인데 오류
    ]
    for purpose, model, ok, error in bad:
        with pytest.raises(asyncpg.exceptions.CheckViolationError):
            query(sql, uuid.uuid4(), purpose, model, ok, error)
    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        query(
            "insert into llm_usage (id, purpose, model, price_ver, ok, output_tokens)"
            " values ($1, 'check', 'm', 'v', true, -1)",
            uuid.uuid4(),
        )
    cols = {
        r["column_name"]
        for r in query(
            "select column_name from information_schema.columns where table_name = 'llm_usage'"
        )
    }
    assert cols == {
        "id", "user_id", "turn_id", "purpose", "model", "input_tokens", "cache_read_tokens",
        "cache_write_tokens", "output_tokens", "web_searches", "cost_micros", "price_ver", "ok",
        "error", "latency_ms", "created_at",
    }  # fmt: skip


def test_record_works_when_only_usage_is_imported():
    """worker · 평가 스크립트처럼 장부만 불러와도 넣기가 된다(users FK를 metadata에서 찾는다)."""
    code = (
        "import asyncio\n"
        "from app.usage import service\n"
        "asyncio.run(service.record(user_id=None, turn_id=None, purpose='check',"
        " model='claude-haiku-5-5', output_tokens=10))\n"
    )
    r = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        cwd=BACKEND,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    assert r.returncode == 0, r.stderr[-800:]
    (row,) = rows()  # record는 넣기 오류를 삼키니 줄이 실제로 있는지 본다
    assert (row["purpose"], row["cost_micros"]) == ("check", 5)
