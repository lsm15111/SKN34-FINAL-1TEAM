"""비서 표 읽기 · 쓰기. commit은 하지 않는다(service · actions가 한다). 모든 조회에 user_id를 붙인다.

상태 바꾸기는 조건부 UPDATE 한 번이고 바뀐 행 수(또는 행)를 돌려준다: 1행이 아니면 부르는 쪽이 409로 바꾼다.
"""

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant.models import AssistantAction, AssistantTurn
from app.chat.models import Chat, ChatMessage

# ---- 대화 ----


async def assistant_chat(
    s: AsyncSession, user_id: uuid.UUID, project_id: uuid.UUID | None
) -> Chat | None:
    """그 사람 · 그 공사의 비서 대화(kind=assistant) 하나. 공사가 없으면(업체) 공사 칸이 빈 대화."""
    q = select(Chat).where(Chat.user_id == user_id, Chat.kind == "assistant")
    q = q.where(Chat.project_id == project_id if project_id else Chat.project_id.is_(None))
    return await s.scalar(q.order_by(Chat.created_at).limit(1))


async def messages(
    s: AsyncSession, chat_id: uuid.UUID, limit: int, before: int | None = None
) -> list[ChatMessage]:
    """최근 limit줄을 오래된 것부터(같은 턴이면 질문 먼저). before를 주면 그 턴보다 앞만."""
    q = select(ChatMessage).where(ChatMessage.chat_id == chat_id)
    if before is not None:
        q = q.where(ChatMessage.turn < before)
    rows = await s.scalars(
        q.order_by(ChatMessage.turn.desc(), (ChatMessage.role == "assistant").desc()).limit(limit)
    )
    return list(reversed(rows.all()))


# ---- 턴 ----


async def turn_by_key(s: AsyncSession, user_id: uuid.UUID, client_key: str) -> AssistantTurn | None:
    return await s.scalar(
        select(AssistantTurn).where(
            AssistantTurn.user_id == user_id, AssistantTurn.client_key == client_key
        )
    )


async def turn_owned(
    s: AsyncSession, user_id: uuid.UUID, turn_id: uuid.UUID
) -> AssistantTurn | None:
    return await s.scalar(
        select(AssistantTurn).where(AssistantTurn.id == turn_id, AssistantTurn.user_id == user_id)
    )


async def turns_of(s: AsyncSession, chat_id: uuid.UUID, revs: Sequence[int]) -> list[AssistantTurn]:
    """대화의 끝난 턴들 중 trace.rev가 revs 안인 것(대화 기록과 잇기)."""
    if not revs:
        return []
    rows = await s.scalars(
        select(AssistantTurn)
        .where(
            AssistantTurn.chat_id == chat_id,
            AssistantTurn.trace["rev"].as_integer().in_(list(revs)),
        )
        .execution_options(populate_existing=True)
    )
    return list(rows.all())


async def failed_turns(
    s: AsyncSession, chat_id: uuid.UUID, since: datetime | None, limit: int
) -> list[AssistantTurn]:
    """대화에 남지 않은(실패한) 턴. 대화 기록에 실패 말로 보인다."""
    q = select(AssistantTurn).where(
        AssistantTurn.chat_id == chat_id, AssistantTurn.status == "failed"
    )
    if since is not None:
        q = q.where(AssistantTurn.created_at >= since)
    rows = await s.scalars(q.order_by(AssistantTurn.created_at.desc()).limit(limit))
    return list(rows.all())


async def fail_stalled(s: AsyncSession, now: datetime, before: datetime, chat_id=None) -> int:
    """heartbeat가 before보다 오래 멈춘 running 턴 → failed 'stalled'. 바꾼 수."""
    q = update(AssistantTurn).where(
        AssistantTurn.status == "running", AssistantTurn.heartbeat_at < before
    )
    if chat_id is not None:
        q = q.where(AssistantTurn.chat_id == chat_id)
    res = await s.execute(q.values(status="failed", error_code="stalled", ended_at=now))
    return res.rowcount or 0


async def beat(s: AsyncSession, turn_id: uuid.UUID, now: datetime) -> None:
    await s.execute(
        update(AssistantTurn)
        .where(AssistantTurn.id == turn_id, AssistantTurn.status == "running")
        .values(heartbeat_at=now)
    )


async def end_turn(s: AsyncSession, turn_id: uuid.UUID, now: datetime, **values) -> bool:
    """running → done · stopped · failed (조건부). 됐으면 True."""
    res = await s.execute(
        update(AssistantTurn)
        .where(AssistantTurn.id == turn_id, AssistantTurn.status == "running")
        .values(ended_at=now, **values)
    )
    return res.rowcount == 1


# ---- 행동 ----


async def action_owned(
    s: AsyncSession, user_id: uuid.UUID, action_id: uuid.UUID, surface: str, *, lock: bool = False
) -> AssistantAction | None:
    q = select(AssistantAction).where(
        AssistantAction.id == action_id,
        AssistantAction.user_id == user_id,
        AssistantAction.surface == surface,
    )
    if lock:
        q = q.with_for_update()
    return await s.scalar(q.execution_options(populate_existing=True))


async def action_by_idem(
    s: AsyncSession, user_id: uuid.UUID, idem_key: str
) -> AssistantAction | None:
    return await s.scalar(
        select(AssistantAction)
        .where(AssistantAction.user_id == user_id, AssistantAction.idem_key == idem_key)
        .execution_options(populate_existing=True)
    )


async def actions_by_id(
    s: AsyncSession, user_id: uuid.UUID, ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, AssistantAction]:
    if not ids:
        return {}
    rows = await s.scalars(
        select(AssistantAction)
        .where(AssistantAction.user_id == user_id, AssistantAction.id.in_(list(ids)))
        .execution_options(populate_existing=True)
    )
    return {a.id: a for a in rows.all()}


async def actions_of(
    s: AsyncSession,
    user_id: uuid.UUID,
    surface: str,
    *,
    project_id: uuid.UUID | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[AssistantAction]:
    q = select(AssistantAction).where(
        AssistantAction.user_id == user_id, AssistantAction.surface == surface
    )
    if project_id is not None:
        q = q.where(AssistantAction.project_id == project_id)
    if status is not None:
        q = q.where(AssistantAction.status == status)
    rows = await s.scalars(
        q.order_by(AssistantAction.created_at.desc())
        .limit(limit)
        .execution_options(populate_existing=True)
    )
    return list(rows.all())


async def replace_open(
    s: AsyncSession, user_id: uuid.UUID, kind: str, target_id: uuid.UUID, by: uuid.UUID
) -> list[AssistantAction]:
    """같은 (사람, 종류, 대상)의 열린 제안을 만료(replaced)로 바꾸고 바뀐 행을 돌려준다. by = 새 제안 id."""
    res = await s.execute(
        update(AssistantAction)
        .where(
            AssistantAction.user_id == user_id,
            AssistantAction.kind == kind,
            AssistantAction.target_id == target_id,
            AssistantAction.status == "proposed",
        )
        .values(status="expired", result={"reason": "replaced", "replaced_by": str(by)})
        .returning(AssistantAction)
        .execution_options(populate_existing=True)
    )
    return list(res.scalars().all())


async def set_action(
    s: AsyncSession, action_id: uuid.UUID, frm: Sequence[str], **values
) -> AssistantAction | None:
    """frm 상태일 때만 바꾼다(조건부 UPDATE). 바뀐 행 또는 None."""
    res = await s.execute(
        update(AssistantAction)
        .where(AssistantAction.id == action_id, AssistantAction.status.in_(list(frm)))
        .values(**values)
        .returning(AssistantAction)
        .execution_options(populate_existing=True)
    )
    return res.scalar_one_or_none()


async def expire_due(s: AsyncSession, now: datetime) -> list[AssistantAction]:
    """기한이 지난 열린 제안 → expired(due)."""
    res = await s.execute(
        update(AssistantAction)
        .where(AssistantAction.status == "proposed", AssistantAction.expires_at <= now)
        .values(status="expired", result={"reason": "due"})
        .returning(AssistantAction)
    )
    return list(res.scalars().all())


async def fail_stuck(s: AsyncSession, before: datetime) -> list[AssistantAction]:
    """approved로 오래 남은 행 → failed 'stalled'(다시 실행하지 않는다)."""
    res = await s.execute(
        update(AssistantAction)
        .where(AssistantAction.status == "approved", AssistantAction.decided_at < before)
        .values(status="failed", error_code="stalled")
        .returning(AssistantAction)
    )
    return list(res.scalars().all())


async def open_count(s: AsyncSession, user_id: uuid.UUID, project_id: uuid.UUID | None) -> int:
    q = select(func.count()).select_from(AssistantAction)
    q = q.where(AssistantAction.user_id == user_id, AssistantAction.status == "proposed")
    if project_id is not None:
        q = q.where(
            or_(AssistantAction.project_id == project_id, AssistantAction.project_id.is_(None))
        )
    return int(await s.scalar(q) or 0)
