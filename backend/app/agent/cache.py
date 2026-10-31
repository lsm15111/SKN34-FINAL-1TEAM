"""에이전트 결과의 짧은 캐시 (Redis). 지워져도 되는 값만 두고, 읽기 · 쓰기가 안 되면 없는 것으로 친다.

키는 부르는 쪽이 입력 전체를 해시해서 만든다 (원문을 Redis 키에 두지 않는다).
"""

import hashlib
import json
import logging

from redis.exceptions import RedisError

from app.queue import redis

log = logging.getLogger(__name__)


def key(prefix: str, *parts: str) -> str:
    return f"{prefix}:" + hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


async def get(k: str) -> dict | None:
    try:
        raw = await redis.get(k)
    except (RedisError, OSError):
        log.warning("캐시를 읽지 못했어요 (Redis 연결 안 됨)")
        return None
    if raw is None:
        return None
    try:
        out = json.loads(raw)
    except ValueError:
        return None
    return out if isinstance(out, dict) else None


async def put(k: str, value: dict, ttl_s: int) -> None:
    try:
        await redis.set(k, json.dumps(value, ensure_ascii=False), ex=ttl_s)
    except (RedisError, OSError):
        log.warning("캐시에 쓰지 못했어요 (Redis 연결 안 됨)")
