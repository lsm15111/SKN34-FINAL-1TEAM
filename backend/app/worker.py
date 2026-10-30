"""백그라운드 작업 (arq + Redis).

LLM 호출(추천 이유·가견적 설명·공정표 해석), 기준 단가 수집, 알림 발송처럼
응답을 기다리게 하면 안 되는 일을 여기서 돌린다. 지금은 연결 확인용 작업 하나뿐이다.
실행: arq app.worker.WorkerSettings
"""

from typing import ClassVar

from arq.connections import RedisSettings

from app.config import settings


async def ping(ctx: dict) -> str:
    return "pong"


class WorkerSettings:
    functions: ClassVar[list] = [ping]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
