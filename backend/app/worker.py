"""백그라운드 작업 (arq + Redis).

LLM 호출(추천 이유·가견적 설명·공정표 해석), 기준 단가 수집, 알림 발송처럼
응답을 기다리게 하면 안 되는 일을 여기서 돌린다. 연결 확인용 작업 · 기한 일 수거 ·
시연 업체 자동 응답(DEMO_AUTO=true일 때만)이 있다.
실행: arq app.worker.WorkerSettings

v3 기한 일(dev-04): sweep_jobs가 1분마다(cron, unique) jobs를 거둬 kind별 처리 함수(JOB_HANDLERS)를 부른다.
처리 함수 계약(jobs.service.JobHandler): `async def h(s, job, now) -> bool | Outcome` — 새 세션 · 새
트랜잭션에서 '아직 그 상태 · 기한이 지났을 때만' 조건부 UPDATE를 하고, 바꿨으면 True(done),
이미 바뀌었거나 대상이 없으면 False(skipped). commit · realtime.push_state · notify.push_unread는
sweep이 한다(Outcome의 states · unread). 개발용 기한 당기기는 app/run_due.py가 sweep을 부른다.
B5의 일 함수는 agent/jobs.py의 FUNCTIONS 목록을 WorkerSettings.functions에 붙인다(아직 없음).
"""

import logging
from collections import Counter
from datetime import datetime
from typing import ClassVar

from arq import cron
from arq.connections import RedisSettings

from app import demo
from app.assistant import jobs as assistant_jobs
from app.assistant import service as assistant_service
from app.config import settings
from app.db import SessionLocal
from app.jobs import service as jobs
from app.jobs.models import Job
from app.jobs.service import JobHandler
from app.notify import service as notify_service
from app.quote import jobs as quote_jobs
from app.realtime import service as realtime
from app.schedule import jobs as schedule_jobs
from app.shared.clock import now_utc, today_seoul
from app.visit import jobs as visit_jobs

log = logging.getLogger(__name__)

# kind → 처리 함수 (jobs.models.KINDS). 기능마다 자기 jobs.py의 HANDLERS에 넣고 여기서 모은다
JOB_HANDLERS: dict[str, JobHandler] = {
    **assistant_jobs.HANDLERS,
    **quote_jobs.HANDLERS,
    **schedule_jobs.HANDLERS,
    **visit_jobs.HANDLERS,
}
SWEEP_TIMEOUT = 55  # 1분마다 도니 다음 차례 전에 끝낸다 (unique라 겹치지 않음)


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


async def _signal(s, out: jobs.Outcome, later: list) -> None:
    """commit 뒤: 화면 신호 · 안 읽은 알림 수 · 처리 함수가 남긴 일(s.info[AFTER_COMMIT]).
    실패해도 일은 끝난 것이라 로그만 남긴다(신호는 지워져도 되는 것, 화면은 다시 읽어 맞춘다)."""
    try:
        for p in out.states:
            await realtime.push_state(p.user_ids, p.kind, p.ref_id, p.project_id)
        if out.unread:
            await notify_service.push_unread(s, out.unread)
        for fn in later:
            await fn()
    except Exception as exc:  # noqa: BLE001 - 신호는 지워져도 되는 것
        log.warning("기한 일 신호 실패: %s", type(exc).__name__)


async def _run_one(job: Job, now: datetime) -> str:
    """일 하나: 처리 함수 → finish → commit → 신호. 돌려주는 값: done · skipped · retry · failed."""
    async with SessionLocal() as s:
        try:
            out = jobs.outcome(await JOB_HANDLERS[job.kind](s, job, now))
            await jobs.finish(s, job.id, now=now, skipped=not out.changed)
            await s.commit()
        except Exception as exc:  # noqa: BLE001 - 어떤 실패든 다시 해 볼 일로 남긴다(종류 이름만)
            await s.rollback()
            s.info.pop(jobs.AFTER_COMMIT, None)  # 저장되지 않은 일의 신호는 버린다
            status = await jobs.fail(s, job.id, now=now, error=type(exc).__name__)
            await s.commit()
            return "failed" if status == "failed" else "retry"
        await _signal(s, out, list(s.info.pop(jobs.AFTER_COMMIT, None) or []))
        return "done" if out.changed else "skipped"


async def sweep(now: datetime, limit: int = jobs.BATCH) -> Counter[tuple[str, str]]:
    """기한이 된 일을 한 번(limit개까지) 거둬 처리한다. 처리 함수가 없는 kind는 그대로 둔다.
    돌려주는 값: (kind, 결과) → 수. 결과는 done · skipped · retry(다시 해 볼 일) · failed."""
    tally: Counter[tuple[str, str]] = Counter()
    if not JOB_HANDLERS:
        return tally
    async with SessionLocal() as s:
        claimed = await jobs.claim(s, now, limit=limit, kinds=list(JOB_HANDLERS))
        await s.commit()
    for job in claimed:
        tally[(job.kind, await _run_one(job, now))] += 1
    return tally


async def sweep_jobs(ctx: dict | None = None, now: datetime | None = None) -> int:
    """cron이 1분마다 부른다. 돌려주는 값: 끝낸 수(done + skipped, 실패해 다시 할 일은 빼고)."""
    tally = await sweep(now or now_utc())
    return sum(n for (_, result), n in tally.items() if result in ("done", "skipped"))


async def assistant_sweep(ctx: dict | None = None, now: datetime | None = None) -> int:
    """비서 정리(2분마다, unique): 만료 제안 → expired · 2분 넘은 승인 → failed · 멈춘 턴 → failed ·
    상태 전이 알림 → 먼저 말 걸기 · 기한이 된 제안 평가. 기억 뽑기는 sweep_jobs가 한다. 돌려주는 값: 바꾼 수."""
    got = await assistant_service.sweep(now or now_utc())
    return sum(got.values())


async def assistant_hourly(ctx: dict | None = None, now: datetime | None = None) -> int:
    """먼저 말 걸기 시간 · 무응답 트리거(매시간 5분, unique). 돌려주는 값: 만든 제안 수."""
    got = await assistant_service.hourly(now or now_utc())
    return sum(got.values())


def demo_on() -> bool:
    return settings.demo_auto and settings.app_env != "production"


class WorkerSettings:
    functions: ClassVar[list] = [ping]
    cron_jobs: ClassVar[list] = [
        cron(assistant_sweep, minute=set(range(0, 60, 2)), second=30, unique=True, timeout=60),
        cron(assistant_hourly, minute=5, second=15, unique=True, timeout=60),
        cron(sweep_jobs, second=0, unique=True, timeout=SWEEP_TIMEOUT),
        *([cron(demo_reply, second=set(range(0, 60, 5)), timeout=50)] if demo_on() else []),
    ]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
