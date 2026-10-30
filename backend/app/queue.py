from redis.asyncio import Redis

from app.config import settings

# 작업 큐(arq)와 짧은 캐시·요청 제한에 쓰는 Redis 연결
# 응답 없는 Redis에 요청이 붙잡히지 않게 1초 안에 포기한다 (요청 제한은 그때 통과시킨다)
redis = Redis.from_url(settings.redis_url, socket_timeout=1, socket_connect_timeout=1)


async def ping() -> None:
    await redis.ping()
