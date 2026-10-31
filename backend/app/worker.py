"""백그라운드 작업 (arq + Redis).

LLM 호출(추천 이유·가견적 설명·공정표 해석), 기준 단가 수집, 알림 발송처럼
응답을 기다리게 하면 안 되는 일을 여기서 돌린다.
실행: arq app.worker.WorkerSettings
"""

from typing import ClassVar

from arq.connections import RedisSettings

from app.config import settings
from app.directory import tasks as directory_tasks
from app.quote import tasks as quote_tasks


async def ping(ctx: dict) -> str:
    return "pong"


class WorkerSettings:
    # 작업은 한 줄에 하나씩 더한다
    functions: ClassVar[list] = [
        directory_tasks.check_homepages,
        directory_tasks.import_sangga_csv,
        directory_tasks.sync_kiscon,
        directory_tasks.verify_biz_status,
        quote_tasks.dispatch_contact_requests,
        ping,
    ]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
