"""백그라운드 작업 (arq + Redis).

LLM 호출(추천 이유·가견적 설명·공정표 해석), 기준 단가 수집, 알림 발송처럼
응답을 기다리게 하면 안 되는 일을 여기서 돌린다. 지금은 연결 확인용 작업과
시연 업체 자동 응답(DEMO_AUTO=true일 때만)이 있다.
실행: arq app.worker.WorkerSettings
"""

from typing import ClassVar

from arq import cron
from arq.connections import RedisSettings

from app import demo
from app.config import settings
from app.shared.clock import today_seoul


async def ping(ctx: dict) -> str:
    return "pong"


async def demo_reply(ctx: dict) -> int:
    """시연 업체 할 일을 대신 한다 (app/demo.py auto_reply)"""
    # 한 번 도는 동안 다음 차례가 겹치거나 시연 데이터를 만드는 중이면 건너뛴다
    if not await ctx["redis"].set(demo.LOCK, "1", nx=True, ex=60):
        return 0
    try:
        return await demo.auto_reply(today_seoul(), ctx.setdefault("demo_skip", set()))
    finally:
        await ctx["redis"].delete(demo.LOCK)


def demo_on() -> bool:
    return settings.demo_auto and settings.app_env != "production"


class WorkerSettings:
    functions: ClassVar[list] = [ping]
    cron_jobs: ClassVar[list] = (
        [cron(demo_reply, second=set(range(0, 60, 5)), timeout=50)] if demo_on() else []
    )
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
