"""LLM 비용 장부와 상한 (계약서 2장 llm_usage · 7장 비용 상한). agent/llm.py의 _guard · _sink가 부른다.

- allow(): 유료 호출 전에 사용자 하루 · 새 계정(한 계정 하루 · 새 계정 합 하루) · 서비스 하루 · 전체 쓴 돈을
  상한과 비교한다. 90% 이상이면 OverCap(llm이 OverBudget으로 바꿔 부르는 쪽이 무료 모드로 간다),
  80% 이상이면 경고 로그를 범위마다 하루 한 번 남긴다.
- 새 계정: 가입(users.created_at)한 지 llm_new_user_days일 안인 고객 · 승인 전 업체 계정. 계정 여러 개로 서비스
  하루 상한을 다 쓰지 못하게(보안 QA M4) 사용자 하루에 더해 한 계정 하루 · 새 계정 합 하루를 본다. 새 계정 합은 부른 때
  새 계정이던 호출(장부 줄 new_account)만 센다: 그 뒤 탈퇴해 사용자 칸이 비어도 그날 쓴 돈은 남는다.
  관리자 · 승인된 업체(exempt)와 사용자를 모르는 일(worker 등)은 새 계정 몫을 보지 않는다.
- record(): 호출 뒤 짧은 세션으로 한 줄을 넣고 commit한다(글 없음). 그다음 Redis 정수 카운터를 올린다.
- 셈: Redis 정수 카운터(마이크로달러)가 먼저다. 키가 없으면 llm_usage 합계로 채우고(SYNC_S마다 다시 맞춤),
  Redis가 안 되면 합계로 바로 센다. 가입 시각 · 역할도 Redis에 하루 두고, 없으면 users에서 읽는다.
  상한을 확인하지 못하면 llm이 유료 호출을 막는다(닫힘 쪽).
- 하루는 서울 날짜다. 상한을 0으로 두면 그 범위의 유료 호출을 모두 막는다.
- 로그에는 범위 · 목적만 남긴다(사용자 id · 글 없음).
"""

import contextlib
import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any, Literal

from redis.exceptions import RedisError
from sqlalchemy import column, func, select, table
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app import queue
from app.auth.models import User
from app.config import settings
from app.db import SessionLocal
from app.shared import clock
from app.usage import prices
from app.usage.models import PURPOSES, LlmUsage

log = logging.getLogger(__name__)

WARN, STOP = 0.8, 0.9
# 카운터를 llm_usage 합계로 다시 맞추는 주기(초). Redis가 잠깐 안 됐을 때 생긴 어긋남도 이 안에서 풀린다
SYNC_S = 600
FLAG_S = 86_400  # 경고 · 막음 로그는 범위마다 하루 한 번. 가입 시각 · 역할도 이만큼 Redis에 둔다
# 업체 승인 상태(읽기 조인). 업체 기능은 위층이라 모델을 import하지 않고 읽을 칸만 적는다
_VENDORS = table("vendors", column("user_id"), column("status"))
_NOT_NEW = "-"  # 가입 시각 캐시에서 '새 계정 몫을 보지 않음'(exempt)
# 키가 있을 때만 올린다. 없으면 다음 allow가 DB 합계로 채운다(이번 호출은 이미 DB에 있다)
_INCR = (
    "if redis.call('exists', KEYS[1]) == 1 then"
    " return redis.call('incrby', KEYS[1], ARGV[1]) end return nil"
)

Scope = Literal["user_day", "new_user_day", "new_pool_day", "service_day", "total"]
# Redis가 안 될 때 나는 것: 연결 · 시간 초과(RedisError · OSError), 다른 이벤트 루프의 연결(RuntimeError)
REDIS_ERRORS = (RedisError, OSError, RuntimeError)
DB_ERRORS = (SQLAlchemyError, OSError)


class OverCap(Exception):
    """상한의 90%를 넘었다. 유료 호출을 하지 않는다."""

    def __init__(self, scope: Scope, spent: int, cap: int) -> None:
        super().__init__(f"LLM 비용 상한({scope})")
        self.scope, self.spent, self.cap = scope, spent, cap


@dataclass(frozen=True)
class Bucket:
    scope: Scope
    key: str
    cap: int  # 마이크로달러
    since: datetime | None  # 이때부터 센다(None이면 처음부터)
    user_id: uuid.UUID | None = None
    # 있으면 새 계정 합: 부른 때 가입한 지 이 일수 안이던 계정의 호출(장부 줄 new_account)만 센다
    new_days: int | None = None


def micros(usd: float) -> int:
    return round(usd * 1_000_000)


def _tag() -> str:
    """같은 Redis를 여러 DB(미리보기 · 시험)가 같이 써도 카운터가 섞이지 않게. 비밀번호는 넣지 않는다."""
    u = make_url(settings.database_url)
    return hashlib.sha256(f"{u.host}:{u.port}/{u.database}".encode()).hexdigest()[:8]


def is_new(joined: datetime | None, now: datetime) -> bool:
    """가입한 지 llm_new_user_days일 안인 계정인지. 가입 시각이 없으면(사용자 없음 · 관리자 · 승인된 업체) 아니다."""
    days = settings.llm_new_user_days
    return joined is not None and days > 0 and joined > now - timedelta(days=days)


def buckets(
    user_id: uuid.UUID | None, now: datetime | None = None, joined: datetime | None = None
) -> list[Bucket]:
    """셀 범위: 사용자 하루(사용자를 알 때만) · 새 계정이면 한 계정 하루와 새 계정 합 하루 · 서비스 하루 · 전체.

    joined는 새 계정 몫을 볼 가입 시각(joined_at, 관리자 · 승인된 업체면 None)이다.
    """
    now = now or clock.now_utc()
    day = now.astimezone(clock.SEOUL).date()
    start = datetime.combine(day, time(0), tzinfo=clock.SEOUL)
    tag, ymd = _tag(), day.strftime("%Y%m%d")
    out = []
    if user_id is not None:
        cap = micros(settings.llm_cap_user_day_usd)
        out.append(Bucket("user_day", f"llm:cost:{tag}:u:{user_id}:{ymd}", cap, start, user_id))
        if is_new(joined, now):
            cap = micros(settings.llm_cap_new_user_day_usd)
            key = f"llm:cost:{tag}:nu:{user_id}:{ymd}"
            out.append(Bucket("new_user_day", key, cap, start, user_id))
            cap, days = micros(settings.llm_cap_new_pool_day_usd), settings.llm_new_user_days
            out.append(Bucket("new_pool_day", f"llm:cost:{tag}:n:{ymd}", cap, start, new_days=days))
    day_cap = micros(settings.llm_cap_service_day_usd)
    out.append(Bucket("service_day", f"llm:cost:{tag}:d:{ymd}", day_cap, start))
    out.append(Bucket("total", f"llm:cost:{tag}:all", micros(settings.llm_cap_total_usd), None))
    return out


def exempt(role: str, vendor_status: str | None) -> bool:
    """새 계정 몫을 보지 않는 계정: 관리자(CLI로만 만듦) · 승인된 업체(사업자등록증 + 관리자 승인)는 계정을 찍어 낼 수
    없다. 승인 전(심사 중 · 보완 요청 · 거절) 업체는 가입 신청만으로 생겨 고객처럼 센다."""
    return role == "admin" or (role == "vendor" and vendor_status == "approved")


async def joined_at(user_id: uuid.UUID | None) -> datetime | None:
    """새 계정 몫을 볼 가입 시각(users.created_at). 관리자 · 승인된 업체(exempt)이거나 사용자 줄이 없으면
    (그사이 탈퇴) None이라 새 계정 몫을 보지 않는다. 새 계정 몫을 끈 때(일수 0)는 읽지 않는다.

    가입 시각 · 역할은 Redis에 하루 두고, 없거나 Redis가 안 되면 users에서 읽는다(심사 중에 둔 값은 승인 뒤에도
    하루 동안 새 계정으로 센다). DB 오류는 그대로 낸다(allow를 부른 쪽이 닫힘 쪽으로 막는다).
    """
    if user_id is None or settings.llm_new_user_days <= 0:
        return None
    key = f"llm:newacct:{_tag()}:{user_id}"
    try:
        got = await queue.redis.get(key)
    except REDIS_ERRORS:
        got = None
    if got is not None:
        with contextlib.suppress(ValueError):  # 모르는 값이면 users에서 다시 읽는다
            text = got.decode() if isinstance(got, bytes) else got
            return None if text == _NOT_NEW else datetime.fromisoformat(text)
    q = (
        select(User.created_at, User.role, _VENDORS.c.status)
        .outerjoin(_VENDORS, _VENDORS.c.user_id == User.id)
        .where(User.id == user_id)
    )
    async with SessionLocal() as s:
        row = (await s.execute(q)).first()
    if row is None:
        return None
    joined = None if exempt(row.role, row.status) else row.created_at
    with contextlib.suppress(*REDIS_ERRORS):
        await queue.redis.set(key, joined.isoformat() if joined else _NOT_NEW, ex=FLAG_S)
    return joined


async def db_spent(b: Bucket) -> int:
    """llm_usage 합계(마이크로달러)."""
    q = select(func.coalesce(func.sum(LlmUsage.cost_micros), 0))
    if b.user_id is not None:
        q = q.where(LlmUsage.user_id == b.user_id)
    if b.new_days is not None:  # 새 계정 합: 부른 때 새 계정이던 호출만(탈퇴해도 남음)
        q = q.where(LlmUsage.new_account.is_(True))
    if b.since is not None:
        q = q.where(LlmUsage.created_at >= b.since)
    async with SessionLocal() as s:
        return int((await s.execute(q)).scalar_one())


async def spent(b: Bucket) -> int:
    """Redis 카운터 → 키가 없으면 DB 합계로 채움 → Redis가 안 되면 DB 합계."""
    try:
        got = await queue.redis.get(b.key)
    except REDIS_ERRORS:  # Redis가 안 되면 llm_usage 합계로 센다
        return await db_spent(b)
    if got is not None:
        return int(got)
    n = await db_spent(b)
    with contextlib.suppress(*REDIS_ERRORS):
        await queue.redis.set(b.key, n, ex=SYNC_S, nx=True)
    return n


async def _once(key: str) -> bool:
    """하루 한 번만 True. Redis가 안 되면 늘 True(로그가 늘어날 뿐)."""
    try:
        return bool(await queue.redis.set(key, 1, ex=FLAG_S, nx=True))
    except REDIS_ERRORS:
        return True


async def allow(user_id: uuid.UUID | None, purpose: str) -> None:
    """유료 호출 전에 부른다. 90% 이상이면 OverCap, 80% 이상이면 경고 로그."""
    for b in buckets(user_id, joined=await joined_at(user_id)):
        n = await spent(b)
        if n >= b.cap * STOP:
            if await _once(f"{b.key}:stop"):
                log.warning(
                    "LLM 비용이 상한의 90%%를 넘어 유료 호출을 막아요 (%s, %s)", b.scope, purpose
                )
            raise OverCap(b.scope, n, b.cap)
        if n >= b.cap * WARN and await _once(f"{b.key}:warn"):
            log.warning("LLM 비용이 상한의 80%%를 넘었어요 (%s)", b.scope)


async def record(
    *,
    user_id: uuid.UUID | None,
    turn_id: uuid.UUID | None,
    purpose: str,
    model: str,
    input_tokens: int = 0,
    cache_read: int = 0,
    cache_write_5m: int = 0,
    cache_write_1h: int = 0,
    output_tokens: int = 0,
    web_searches: int = 0,
    error: str | None = None,
    latency_ms: int = 0,
) -> int:
    """호출 한 번을 장부에 남기고 비용(마이크로달러)을 돌려준다. 부른 때 새 계정이었으면 줄에 표시한다(new_account).

    장부 · 카운터가 안 돼도 호출 결과는 살린다(로그만). purpose가 표에 없으면 ValueError(코드 실수).
    """
    if purpose not in PURPOSES:
        raise ValueError("모르는 purpose")
    now, joined = clock.now_utc(), None
    # 가입 시각을 못 읽으면(DB 오류) 새 계정 표시 없이 남긴다(서비스 하루 · 전체 셈에는 그대로 든다)
    with contextlib.suppress(*DB_ERRORS):
        joined = await joined_at(user_id)
    model = (model or "unknown").strip()[:60] or "unknown"
    t = [max(int(x or 0), 0) for x in (input_tokens, cache_read, cache_write_5m, cache_write_1h)]
    out, searches = max(int(output_tokens or 0), 0), max(int(web_searches or 0), 0)
    cost, ver = prices.cost(
        model,
        input_tokens=t[0],
        cache_read=t[1],
        cache_write_5m=t[2],
        cache_write_1h=t[3],
        output_tokens=out,
        web_searches=searches,
    )
    error = (error or "").strip()[:40] or None
    values: dict[str, Any] = {
        "turn_id": turn_id,
        "purpose": purpose,
        "model": model,
        "input_tokens": t[0],
        "cache_read_tokens": t[1],
        "cache_write_tokens": t[2] + t[3],
        "output_tokens": out,
        "web_searches": min(searches, 32_767),
        "cost_micros": cost,
        "price_ver": ver,
        "ok": error is None,
        "error": error,
        "latency_ms": max(int(latency_ms), 0),
        "new_account": is_new(joined, now),
    }
    try:
        await _insert(user_id, values)
    except DB_ERRORS:
        log.warning("LLM 사용 기록을 남기지 못했어요 (%s)", purpose)
    if cost:
        for b in buckets(user_id, now, joined):
            with contextlib.suppress(*REDIS_ERRORS):
                await queue.redis.eval(_INCR, 1, b.key, cost)
    return cost


async def _insert(user_id: uuid.UUID | None, values: dict[str, Any]) -> None:
    async with SessionLocal() as s:
        s.add(LlmUsage(user_id=user_id, **values))
        try:
            await s.commit()
            return
        except IntegrityError:
            if user_id is None:
                raise
            await s.rollback()
    # 그사이 사용자가 지워졌으면(FK) 사용자 없이 남긴다. 서비스 하루 · 전체 셈에는 그대로 들어간다
    async with SessionLocal() as s:
        s.add(LlmUsage(user_id=None, **values))
        await s.commit()
