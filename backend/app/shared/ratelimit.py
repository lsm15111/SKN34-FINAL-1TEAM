"""요청 횟수 제한 (Redis). 로그인 · 회원가입 · 파일 올리기 · 프로젝트 만들기가 같이 쓴다.

세는 것과 만료 설정을 한 번에(MULTI) 해서, 동시에 몰려도 한도를 넘지 못하고 키가 영원히 남지 않는다.
Redis가 안 되면 막지 않고 통과시킨다(fail-open). 원본 데이터는 DB에 있어 서비스는 계속된다.
"""

import hashlib
import logging

from redis.exceptions import RedisError

from app.queue import redis
from app.shared.errors import AppError

log = logging.getLogger(__name__)


def key(*parts: str) -> str:
    """이메일 · IP 같은 원문을 Redis에 두지 않게 해시로 만든다."""
    return "rl:" + hashlib.sha256("|".join(parts).encode()).hexdigest()[:32]


async def hit(k: str, limit: int, window_s: int, message: str) -> None:
    """한 번 센다. 한도를 넘으면 429와 Retry-After를 낸다."""
    try:
        async with redis.pipeline(transaction=True) as p:
            p.incr(k)
            p.expire(k, window_s, nx=True)
            p.ttl(k)
            count, _, ttl = await p.execute()
    except RedisError:
        log.warning("요청 제한을 확인하지 못해 통과시켜요 (Redis 연결 안 됨)")
        return
    if int(count) > limit:
        raise AppError(
            429, "too_many_attempts", message, headers={"Retry-After": str(max(int(ttl), 1))}
        )


async def reset(k: str) -> None:
    try:
        await redis.delete(k)
    except RedisError:
        pass


def client_ip(request) -> str:
    """요청 보낸 곳. 운영에서는 Caddy가 X-Forwarded-For를 덮어쓰고 uvicorn --proxy-headers가 읽는다."""
    return request.client.host if request.client else "unknown"
