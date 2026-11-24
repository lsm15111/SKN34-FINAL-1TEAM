"""비서 기한 일 처리 함수(HANDLERS, worker.sweep_jobs가 부른다). 계약: jobs.service.JobHandler.

- assistant_memory: 비서 턴 저장(finish_turn)이 같은 트랜잭션에 넣은 일. ref_id = 그 턴의 고객 메시지.
  비서 대화(chats.kind=assistant)의 고객 줄만 읽고, 읽은 뒤 트랜잭션을 닫고 Haiku(memory.extract)를 부른다.
  검사(memory.validate)를 지난 것만 저장하고, 그 말이 직접 할 일을 업체에 넘기면 앞 기억에서 뺀다(Haiku는 뺀 일을
  뽑지 않는다). commit은 worker가 한다.
- 미루기(리드 결정 11-22, QA r3 f1: 무료 모드에 한 '주말에만'이 기억되지 않음): LLM이 꺼졌거나 비용 상한이면
  (memory.Later) 같은 kind · 같은 말로 뒤 시각의 일을 한 줄 더 넣고 이번 줄은 skipped로 끝낸다. 다음 시각은 계산
  엔진(calc.deadline.memory_later_at)이 정한다: 하루 상한(사용자 · 새 계정 · 서비스 하루)이면 다음 서울 날 0시 10분
  (상한이 다시 차요, 그날도 상한이면 또 미뤄요), 그 밖(꺼짐 · 전체 상한 · 셀 수 없음)이면 30분 · 2시간 · 6시간 ·
  12시간 뒤, 말한 때부터 3일을 넘으면 더 미루지 않는다. 말마다 몇 분씩 늦춰 한꺼번에 몰리지 않게 한다.
  같은 말은 한 번만 뽑는다(열린 일은 늘 한 줄: 이번 줄을 끝내는 트랜잭션에 다음 줄을 넣고, dedup_key가 차례마다
  달라요). 미뤘다 뽑은 말 · 공급자 오류로 다시 하는 일은 그 뒤에 직접 할 일을 저장 · 정한 공사면 직접 할 일 조각을
  버린다(옛 말이 새 결정을 이기지 않게).
- 모든 기억 뽑기 일은 그 말을 한 때(메시지 created_at)를 memory.save에 넘긴다: 그 뒤에 바뀐 칸(나중 말 · 고객이
  지움 · 칩으로 줄임)은 덮지 않는다(R1b #8 지운 기억이 미룬 일로 되살아남 · #9 다시 하는 일이 새 기억을 덮음).
"""

import logging
import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant import memory
from app.chat.models import Chat, ChatMessage
from app.jobs import service as jobs_service
from app.jobs.models import Job
from app.jobs.service import JobHandler

log = logging.getLogger(__name__)

KIND = "assistant_memory"
LATER = ":later"  # 미룬 일의 dedup_key 꼬리(차례 번호가 붙어요)
# 서울 날이 바뀌면 다시 차는 비용 상한(usage.Scope). 전체 상한(total) · 셀 수 없음(unknown) · 꺼짐(off)은 간격으로
DAY_SCOPES = frozenset({"user_day", "new_user_day", "new_pool_day", "service_day"})
SPREAD_MINUTES = 30  # 말마다 0 ~ 29분 늦춰 한꺼번에 몰리지 않게


async def remember(s: AsyncSession, job: Job, now: datetime) -> bool:
    """고객 메시지 한 줄 → 기억. 메시지가 없거나 비서 대화의 고객 줄이 아니면 False(skipped). LLM을 못 쓰면 뒤로
    미룬다(_later, skipped)."""
    if job.ref_id is None:
        return False
    row = (
        await s.execute(
            select(ChatMessage.text, ChatMessage.created_at, Chat.user_id, Chat.project_id)
            .join(Chat, Chat.id == ChatMessage.chat_id)
            .where(
                ChatMessage.id == job.ref_id,
                ChatMessage.role == "user",
                Chat.kind == "assistant",
            )
        )
    ).first()
    if row is None:
        return False
    text, said_at, user_id, project_id = row
    await s.commit()  # LLM을 기다리는 동안 트랜잭션을 쥐지 않는다(읽기만 했다)
    try:
        got = await memory.extract(text, user_id)
    except memory.Later as e:
        await _later(s, job, said_at, now, e.scope)
        return False
    why: list[str] = []
    items = memory.validate(got, text, why)
    # 어디서 빠지는지 보이게(QA r6 c3 M9: 강아지를 두 번 말해도 기억 없음, 뽑기 · 검사 중 어디인지 기록이 없었어요).
    # 키 · 까닭 코드만 남기고 값 · 고객 글은 남기지 않아요
    log.info("기억 뽑기: 뽑음 %d · 남김 %d · 뺌 %s", len(got), len(items), ",".join(why) or "-")
    late = LATER in job.dedup_key or job.attempts > 0  # 미룬 일 · 공급자 오류로 다시 하는 일
    settled = late and await _diy_settled(s, user_id, project_id, said_at)
    if settled:  # 미룬 사이 직접 할 일을 저장 · 정했어요: 옛 말의 직접 할 일은 버려요(칩이 원본)
        items = [it for it in items if it.key != "diy"]
    saved = await memory.save(
        s,
        user_id,
        job.ref_id,
        items,
        now,
        said=None if settled else text,
        said_at=said_at,  # 그 말 뒤에 바뀐 칸(나중 말 · 지움 · 칩으로 줄임)은 덮지 않아요
    )
    return saved > 0


async def _later(s: AsyncSession, job: Job, said_at: datetime, now: datetime, scope: str) -> bool:
    """같은 말로 뒤 시각의 기억 뽑기 일을 한 줄 넣는다(commit은 worker가 이번 줄을 끝내며). 더 미루지 않으면 False."""
    from app.calc import deadline

    tries = int(
        await s.scalar(
            select(func.count()).select_from(Job).where(Job.kind == KIND, Job.ref_id == job.ref_id)
        )
        or 1
    )
    at = deadline.memory_later_at(
        now,
        said_at,
        tries,
        next_day=scope in DAY_SCOPES,
        spread_minutes=job.ref_id.int % SPREAD_MINUTES if job.ref_id else 0,
    )
    if at is None:
        return False
    return await jobs_service.add(
        s, kind=KIND, ref_id=job.ref_id, run_at=at, dedup_key=f"{KIND}:{job.ref_id}{LATER}{tries}"
    )


async def _diy_settled(
    s: AsyncSession, user_id: uuid.UUID, project_id: uuid.UUID | None, said_at: datetime
) -> bool:
    """그 말 뒤에 이 공사의 직접 할 일을 정했는지: 칩을 저장했거나(화면 · 승인) 직접 할 일 카드를 승인 · 거절 ·
    거뒀어요(읽기만)."""
    from app.assistant.models import AssistantAction
    from app.project.diy import PREFIX
    from app.project.models import ProjectCondition

    if project_id is None:
        return False
    saved = await s.scalar(
        select(func.max(ProjectCondition.updated_at)).where(
            ProjectCondition.project_id == project_id, ProjectCondition.key.like(f"{PREFIX}%")
        )
    )
    if saved is not None and saved > said_at:
        return True
    decided = await s.scalar(
        select(func.count())
        .select_from(AssistantAction)
        .where(
            AssistantAction.user_id == user_id,
            AssistantAction.project_id == project_id,
            AssistantAction.kind == "home_info",
            AssistantAction.decided_at > said_at,
            AssistantAction.payload["fields"].has_key("diy"),
        )
    )
    return bool(decided)


HANDLERS: dict[str, JobHandler] = {KIND: remember}
