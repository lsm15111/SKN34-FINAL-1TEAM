"""v4 비용 장부 · 상한(usage): 가격 셈, 사용자 하루 · 서비스 하루 · 전체 상한(80% 경고 · 90% 막음),
Redis 정수 카운터와 Redis가 안 될 때의 장부 합계, llm_usage 제약. 유료 호출 0회."""

import asyncio
import logging
import os
import subprocess
import sys
import uuid

import asyncpg
import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from app import queue
from app.agent import llm
from app.config import settings
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
    assert prices.cost("gpt-6.1-terra", input_tokens=1_000_000) == (4_000_000, f"{ver}:fallback")


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
