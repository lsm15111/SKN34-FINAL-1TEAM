"""백그라운드 작업 (arq + Redis).

LLM 호출(추천 이유·가견적 설명·공정표 해석), 기준 단가 수집, 알림 발송처럼
응답을 기다리게 하면 안 되는 일을 여기서 돌린다.
실행: arq app.worker.WorkerSettings
"""

from typing import ClassVar

from arq import cron
from arq.connections import RedisSettings
from arq.cron import CronJob

from app.config import settings
from app.directory import tasks as directory_tasks
from app.quote import tasks as quote_tasks
from app.shared.clock import SEOUL


async def ping(ctx: dict) -> str:
    return "pong"


def cron_schedule() -> list[CronJob]:
    """주기 작업 (서울 시각). CRON_ENABLED=false면 하나도 돌리지 않는다.

    각 작업은 스스로도 멈춘다: 대신 연락은 CONTACT_SEND_ENABLED=false면, KISCON은 키가 없으면 건너뛴다.
    """
    if not settings.cron_enabled:
        return []
    return [
        # 대신 연락 보내기: 5분마다. job_id를 고정해 앞 작업이 끝나기 전에는 다시 넣지 않는다
        cron(
            quote_tasks.dispatch_contact_requests,
            minute=set(range(0, 60, 5)),
            job_id="dispatch_contact_requests",
        ),
        # sending에 오래 멈춘 대신 연락을 failed(확인 필요)로: 10분마다
        cron(quote_tasks.fail_stuck_contacts, minute=set(range(2, 60, 10))),
        # KISCON 공시(지난 7일): 하루 한 번
        cron(directory_tasks.sync_kiscon, hour=4, minute=10, timeout=1800),
        # 업체 홈페이지 링크 확인: 주 한 번 (요청 간격 때문에 오래 걸린다)
        cron(directory_tasks.check_homepages, weekday="mon", hour=4, minute=40, timeout=3600),
    ]


class WorkerSettings:
    # 작업은 한 줄에 하나씩 더한다
    functions: ClassVar[list] = [
        directory_tasks.check_homepages,
        directory_tasks.import_sangga_csv,
        directory_tasks.match_kakao_places,
        directory_tasks.sync_kiscon,
        directory_tasks.verify_biz_status,
        quote_tasks.dispatch_contact_requests,
        quote_tasks.fail_stuck_contacts,
        ping,
    ]
    cron_jobs: ClassVar[list[CronJob]] = cron_schedule()
    timezone = SEOUL  # cron 시각을 서울 기준으로 본다
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
