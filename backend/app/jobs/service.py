"""기한 일(jobs) 넣기 · 취소 · 거두기 · 끝내기 (dev-04, D14 A).

- 상태를 바꾸는 service가 **같은 트랜잭션**에 add()를 부른다(아웃박스). 이미 끝난 기한은 cancel().
- worker(조립 층)가 1분마다 claim()으로 가져가 kind별 처리 함수를 부르고 finish() · fail()로 끝낸다.
  시간이 모자라 시작하지 못한 일은 release()로 돌려놓는다. 이 패키지는 흐름 기능(visit · schedule)을 import하지 않는다.
- 처리 함수는 멱등이어야 한다: '아직 그 상태 · 기한이 지났을 때만' 조건부 UPDATE, 알림은 dedup_key.
- 처리 함수는 bool 또는 Outcome을 돌려준다. Outcome이면 worker가 commit 뒤에 화면 신호(state) ·
  안 읽은 알림 수(notif)를 보낸다(이 패키지는 realtime · notify를 부르지 않는다).
"""

import uuid
from collections.abc import Awaitable, Callable, Collection, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs.models import ATTEMPTS_MAX, KINDS, Job
from app.shared.ids import uuid7


@dataclass(frozen=True)
class StatePush:
    """commit 뒤에 보낼 화면 신호 하나 (realtime.service.push_state 인자 그대로)"""

    user_ids: tuple[uuid.UUID | None, ...]
    kind: str  # realtime StateKind: visit · deal · quote · extra · review · vendor_app · thread
    ref_id: uuid.UUID
    project_id: uuid.UUID | None = None


@dataclass
class Outcome:
    """처리 함수가 bool 대신 돌려줄 수 있는 결과. changed=False면 skipped로 끝난다.
    states는 commit 뒤 push_state로, unread의 사람에게는 안 읽은 알림 수(push_unread)를 보낸다."""

    changed: bool
    states: list[StatePush] = field(default_factory=list)
    unread: list[uuid.UUID | None] = field(default_factory=list)


# 처리 함수 계약 (worker.sweep_jobs가 부른다): 바꿨으면 True(done), 이미 바뀌었거나 대상이 없으면
# False(skipped). commit 뒤 신호가 필요하면 Outcome을 돌려준다.
JobHandler = Callable[[AsyncSession, Job, datetime], Awaitable[bool | Outcome]]
# 처리 함수가 commit 뒤에 할 일을 세션에 남기는 칸: s.info[AFTER_COMMIT]에 '인자 없는 async 함수'를
# 차례로 넣으면 worker가 commit 뒤에 await한다(실패하면 버리고 로그만). 처리가 실패하면 버린다.
AFTER_COMMIT = "after_commit"


def outcome(result: bool | Outcome) -> Outcome:
    """처리 함수가 돌려준 값을 Outcome으로 맞춘다 (bool이면 신호 없음)."""
    return result if isinstance(result, Outcome) else Outcome(changed=bool(result))


BATCH = 50  # 한 번에 거두는 수
LOCK = timedelta(
    minutes=2
)  # 처리하는 동안 다른 worker가 못 가져가는 시간 (넘으면 멈춘 일로 다시 거둔다)
RETRY = (
    timedelta(minutes=1),
    timedelta(minutes=5),
    timedelta(minutes=30),
)  # 실패하면 다시 해 볼 때
STUCK = "Stuck"  # 멈춘 일을 다시 거둘 때 last_error (지난 처리가 끝나지 못함)


def key(kind: str, ref_id: uuid.UUID | None, run_at: datetime) -> str:
    """같은 일을 두 번 넣지 않는 이름: kind:ref_id:실행 시각(UTC 분, YYYYMMDDHHMM). 80자 안."""
    if run_at.tzinfo is None:
        raise ValueError("run_at에는 시간대가 있어야 해요")
    return f"{kind}:{ref_id or '-'}:{run_at.astimezone(UTC):%Y%m%d%H%M}"


async def add(
    s: AsyncSession,
    *,
    kind: str,
    ref_id: uuid.UUID | None,
    run_at: datetime,
    dedup_key: str | None = None,
) -> bool:
    """기한 일 하나를 넣는다. 같은 dedup_key가 이미 있으면 아무것도 하지 않는다(멱등).
    돌려주는 값: 새로 넣었는지. run_at은 계산 엔진(calc.deadline)이 만든 timezone 있는 시각."""
    if kind not in KINDS:
        raise ValueError(f"알 수 없는 기한 일: {kind}")
    if run_at.tzinfo is None:
        raise ValueError("run_at에는 시간대가 있어야 해요")
    res = await s.execute(
        insert(Job)
        .values(
            id=uuid7(),
            kind=kind,
            ref_id=ref_id,
            run_at=run_at,
            dedup_key=dedup_key or key(kind, ref_id, run_at),
        )
        .on_conflict_do_nothing(index_elements=["dedup_key"])
        .returning(Job.id)
    )
    return res.scalar_one_or_none() is not None


async def cancel(
    s: AsyncSession,
    *,
    now: datetime,
    kind: str | None = None,
    ref_id: uuid.UUID | None = None,
    dedup_key: str | None = None,
) -> int:
    """아직 기다리는(pending) 일을 cancelled로. dedup_key 하나, 또는 (kind, ref_id)의 기다리는 일 모두.
    돌려주는 값: 바꾼 수. 이미 처리 중 · 끝난 일은 건드리지 않는다(처리 함수가 상태를 다시 본다)."""
    if dedup_key is not None:
        cond = [Job.dedup_key == dedup_key]
    elif kind is not None and ref_id is not None:
        cond = [Job.kind == kind, Job.ref_id == ref_id]
    else:
        raise ValueError("dedup_key 또는 (kind, ref_id)가 있어야 해요")
    res = await s.execute(
        update(Job)
        .where(*cond, Job.status == "pending")
        .values(status="cancelled", done_at=now)
        .execution_options(synchronize_session=False)
    )
    return res.rowcount


async def cancel_refs(
    s: AsyncSession,
    *,
    now: datetime,
    ref_ids: Iterable[uuid.UUID | None],
    kinds: Collection[str] | None = None,
) -> int:
    """대상(ref_id)이 끝나 필요 없어진 기다리는 일을 한꺼번에 cancelled로 (kinds를 주면 그 kind만).
    id는 uuid7이라 표가 달라도 겹치지 않는다. 돌려주는 값: 바꾼 수."""
    refs = list({r for r in ref_ids if r is not None})
    if not refs:
        return 0
    q = update(Job).where(Job.ref_id.in_(refs), Job.status == "pending")
    if kinds is not None:
        q = q.where(Job.kind.in_(list(kinds)))
    res = await s.execute(
        q.values(status="cancelled", done_at=now).execution_options(synchronize_session=False)
    )
    return res.rowcount


async def claim(
    s: AsyncSession, now: datetime, limit: int = BATCH, kinds: Collection[str] | None = None
) -> list[Job]:
    """기한이 된 일(pending · run_at ≤ now)과 멈춘 일(running · locked_until < now)을 가져가 running으로.
    FOR UPDATE SKIP LOCKED라 worker 둘이 같은 행을 가져가지 않는다. kinds를 주면 그 kind만.
    멈춘 일은 지난 처리가 끝나지 못한 것(worker 시간 제한 · 프로세스 멈춤)이라 한 번 실패로 센다(attempts + 1,
    last_error Stuck). ATTEMPTS_MAX에 닿으면 failed로 끝내고 돌려주지 않는다(끝없이 다시 거두지 않게).
    commit은 부르는 쪽(곧바로)."""
    due = or_(
        and_(Job.status == "pending", Job.run_at <= now),
        and_(Job.status == "running", Job.locked_until < now),
    )
    q = select(Job).where(due)
    if kinds is not None:
        q = q.where(Job.kind.in_(list(kinds)))
    q = (
        q.order_by(Job.run_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    )
    rows = []
    for j in (await s.execute(q)).scalars():
        if j.status == "running":
            j.attempts += 1
            j.last_error = STUCK
            if j.attempts >= ATTEMPTS_MAX:
                j.status, j.locked_until, j.done_at = "failed", None, now
                continue
        j.status = "running"
        j.locked_until = now + LOCK
        rows.append(j)
    await s.flush()
    return rows


async def release(s: AsyncSession, job_ids: list[uuid.UUID]) -> int:
    """거두었지만 처리를 시작하지 않은 일을 기다림(pending)으로 돌려놓는다(센 횟수 · 실행 시각 그대로).
    sweep이 시간 제한 안에 끝낼 수 없을 때 쓴다. 돌려주는 값: 돌려놓은 수. commit은 부르는 쪽."""
    if not job_ids:
        return 0
    res = await s.execute(
        update(Job)
        .where(Job.id.in_(job_ids), Job.status == "running")
        .values(status="pending", locked_until=None)
        .execution_options(synchronize_session=False)
    )
    return res.rowcount


async def finish(
    s: AsyncSession, job_id: uuid.UUID, *, now: datetime, skipped: bool = False
) -> None:
    """처리 끝: done(바꾼 것이 있음) · skipped(이미 바뀌어 할 일이 없었음 · 대상 없음)."""
    await s.execute(
        update(Job)
        .where(Job.id == job_id, Job.status == "running")
        .values(status="skipped" if skipped else "done", locked_until=None, done_at=now)
        .execution_options(synchronize_session=False)
    )


async def fail(s: AsyncSession, job_id: uuid.UUID, *, now: datetime, error: str) -> str | None:
    """처리 실패: 1 · 5 · 30분 뒤 다시(최대 5번), 넘으면 failed. error는 오류 종류 이름만(개인정보 없음).
    돌려주는 값: 바뀐 상태(pending · failed), 처리 중이 아니었으면 None."""
    j = await s.get(Job, job_id, populate_existing=True)
    if j is None or j.status != "running":
        return None
    tries = j.attempts + 1
    j.attempts = tries
    j.last_error = (error or "error")[:60]
    j.locked_until = None
    if tries >= ATTEMPTS_MAX:
        j.status = "failed"
        j.done_at = now
    else:
        j.status = "pending"
        j.run_at = now + RETRY[min(tries - 1, len(RETRY) - 1)]
    await s.flush()
    return j.status
