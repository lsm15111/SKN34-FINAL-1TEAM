"""비서 표 읽기 · 쓰기. commit은 하지 않는다(service · actions가 한다). 모든 조회에 user_id를 붙인다.

상태 바꾸기는 조건부 UPDATE 한 번이고 바뀐 행 수(또는 행)를 돌려준다: 1행이 아니면 부르는 쪽이 409로 바꾼다.
"""

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant.models import (
    AssistantAction,
    AssistantMemory,
    AssistantNudge,
    AssistantTurn,
)
from app.chat.models import Chat, ChatMessage
from app.project.models import Project
from app.schedule.models import DateProposal
from app.shared.ids import uuid7
from app.visit.models import LIVE, Visit

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


async def open_on(
    s: AsyncSession, user_id: uuid.UUID, target_kind: str, target_id: uuid.UUID
) -> list[AssistantAction]:
    """그 사람 · 그 대상의 열린 제안(proposed). 대상마다 하나지만 옛 행이 남았을 수 있어 목록으로 읽는다."""
    rows = await s.scalars(
        select(AssistantAction)
        .where(
            AssistantAction.user_id == user_id,
            AssistantAction.target_kind == target_kind,
            AssistantAction.target_id == target_id,
            AssistantAction.status == "proposed",
        )
        .execution_options(populate_existing=True)
    )
    return list(rows.all())


async def replace_open(
    s: AsyncSession, user_id: uuid.UUID, target_kind: str, target_id: uuid.UUID, by: uuid.UUID
) -> list[AssistantAction]:
    """같은 (사람, 대상)의 열린 제안을 종류와 상관없이 만료(replaced)로 바꾸고 바뀐 행을 돌려준다(대상마다 열린
    제안 하나, 계약서 6장). by = 새 제안 id."""
    res = await s.execute(
        update(AssistantAction)
        .where(
            AssistantAction.user_id == user_id,
            AssistantAction.target_kind == target_kind,
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


async def open_actions(s: AsyncSession, limit: int) -> list[AssistantAction]:
    """모든 사람의 열린 제안(proposed), 새 것부터 (sweep: 화면에서 직접 처리했는지 보기)."""
    rows = await s.scalars(
        select(AssistantAction)
        .where(AssistantAction.status == "proposed")
        .order_by(AssistantAction.created_at.desc())
        .limit(limit)
    )
    return list(rows.all())


async def close_handled(s: AsyncSession, ids: Sequence[uuid.UUID], reason: str) -> list[uuid.UUID]:
    """열린 제안만 → expired(reason). 그 행동을 단 먼저 말 걸기 줄(sent · opened)도 expired(handled)."""
    res = await s.execute(
        update(AssistantAction)
        .where(AssistantAction.id.in_(list(ids)), AssistantAction.status == "proposed")
        .values(status="expired", result={"reason": reason})
        .returning(AssistantAction.id)
    )
    closed = list(res.scalars().all())
    if closed:
        await s.execute(
            update(AssistantNudge)
            .where(AssistantNudge.action_id.in_(closed), AssistantNudge.status.in_(SHOWN))
            .values(status="expired", reason="handled")
        )
    return closed


async def project_states(
    s: AsyncSession, ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, tuple[int, bool]]:
    """공사 id → (rev, 잠김). 읽기 조인."""
    if not ids:
        return {}
    rows = await s.execute(
        select(Project.id, Project.rev, Project.locked_at).where(Project.id.in_(list(ids)))
    )
    return {i: (rev, locked is not None) for i, rev, locked in rows}


async def visit_states(s: AsyncSession, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, str]:
    """실측 id → 상태. 읽기 조인."""
    if not ids:
        return {}
    rows = await s.execute(select(Visit.id, Visit.status).where(Visit.id.in_(list(ids))))
    return {k: v for k, v in rows}


async def live_visits(
    s: AsyncSession, project_ids: Sequence[uuid.UUID]
) -> set[tuple[uuid.UUID, str, uuid.UUID | None]]:
    """공사들의 살아 있는 실측 (공사, 공정, 업체). 읽기 조인."""
    if not project_ids:
        return set()
    rows = await s.execute(
        select(Visit.project_id, Visit.trade, Visit.vendor_id).where(
            Visit.project_id.in_(list(project_ids)), Visit.status.in_(LIVE)
        )
    )
    return {(p, t, v) for p, t, v in rows}


async def proposal_states(s: AsyncSession, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, str]:
    """업체가 낸 공사 날짜 id → 상태. 읽기 조인."""
    if not ids:
        return {}
    rows = await s.execute(
        select(DateProposal.id, DateProposal.status).where(DateProposal.id.in_(list(ids)))
    )
    return {k: v for k, v in rows}


async def open_count(s: AsyncSession, user_id: uuid.UUID, project_id: uuid.UUID | None) -> int:
    q = select(func.count()).select_from(AssistantAction)
    q = q.where(AssistantAction.user_id == user_id, AssistantAction.status == "proposed")
    if project_id is not None:
        q = q.where(
            or_(AssistantAction.project_id == project_id, AssistantAction.project_id.is_(None))
        )
    return int(await s.scalar(q) or 0)


# ---- 먼저 말 걸기 ----

SHOWN = ("sent", "opened")  # 대화 기록에 보이는 줄
SENT = ("sent", "opened", "dismissed")  # 보낸 줄(상한 · 점수가 센다)


async def insert_nudge(s: AsyncSession, **values) -> bool:
    """(사람, dedup_key)가 없을 때만 넣는다(멱등). 넣었으면 True."""
    res = await s.execute(
        insert(AssistantNudge)
        .values(id=uuid7(), **values)
        .on_conflict_do_nothing(constraint="uq_assistant_nudges_user_dedup")
        .returning(AssistantNudge.id)
    )
    return res.scalar_one_or_none() is not None


async def nudge_owned(
    s: AsyncSession, user_id: uuid.UUID, nudge_id: uuid.UUID, surface: str
) -> AssistantNudge | None:
    return await s.scalar(
        select(AssistantNudge)
        .where(
            AssistantNudge.id == nudge_id,
            AssistantNudge.user_id == user_id,
            AssistantNudge.surface == surface,
        )
        .execution_options(populate_existing=True)
    )


async def due_nudges(s: AsyncSession, now: datetime, limit: int) -> list[AssistantNudge]:
    rows = await s.scalars(
        select(AssistantNudge)
        .where(AssistantNudge.status == "pending", AssistantNudge.due_at <= now)
        .order_by(AssistantNudge.due_at)
        .limit(limit)
    )
    return list(rows.all())


async def set_nudge(
    s: AsyncSession, nudge_id: uuid.UUID, frm: Sequence[str], **values
) -> AssistantNudge | None:
    """frm 상태일 때만 바꾼다(조건부 UPDATE). 바뀐 행 또는 None."""
    res = await s.execute(
        update(AssistantNudge)
        .where(AssistantNudge.id == nudge_id, AssistantNudge.status.in_(list(frm)))
        .values(**values)
        .returning(AssistantNudge)
        .execution_options(populate_existing=True)
    )
    return res.scalar_one_or_none()


async def sent_count(
    s: AsyncSession, user_id: uuid.UUID, since: datetime, channel: str | None = None
) -> int:
    q = select(func.count()).select_from(AssistantNudge)
    q = q.where(
        AssistantNudge.user_id == user_id,
        AssistantNudge.status.in_(SENT),
        AssistantNudge.sent_at >= since,
    )
    if channel is not None:
        q = q.where(AssistantNudge.channel == channel)
    return int(await s.scalar(q) or 0)


async def dismissals(
    s: AsyncSession, user_id: uuid.UUID, since: datetime
) -> list[tuple[str, datetime]]:
    """since 뒤에 닫은 제안(트리거, 닫은 때)."""
    rows = await s.execute(
        select(AssistantNudge.trigger, AssistantNudge.acted_at).where(
            AssistantNudge.user_id == user_id,
            AssistantNudge.status == "dismissed",
            AssistantNudge.acted_at >= since,
        )
    )
    return [(t, at) for t, at in rows]


async def replace_shown(
    s: AsyncSession, user_id: uuid.UUID, ref_id: uuid.UUID, keep: uuid.UUID
) -> int:
    """같은 대상의 보이는 제안을 새 제안(keep)으로 바꾼다(expired · replaced). 대상마다 열린 제안은 하나."""
    res = await s.execute(
        update(AssistantNudge)
        .where(
            AssistantNudge.user_id == user_id,
            AssistantNudge.ref_id == ref_id,
            AssistantNudge.id != keep,
            AssistantNudge.status.in_(SHOWN),
        )
        .values(status="expired", reason="replaced")
    )
    return res.rowcount or 0


async def shown_nudges(
    s: AsyncSession,
    user_id: uuid.UUID,
    surface: str,
    project_id: uuid.UUID | None,
    *,
    since: datetime | None = None,
    open_only: bool = False,
    limit: int = 10,
) -> list[AssistantNudge]:
    """대화 기록에 보일 제안(새것부터). 고객은 그 공사 것만, 업체는 업체 것 모두."""
    q = select(AssistantNudge).where(
        AssistantNudge.user_id == user_id,
        AssistantNudge.surface == surface,
        AssistantNudge.status.in_(("sent",) if open_only else SHOWN),
    )
    if project_id is not None:
        q = q.where(AssistantNudge.project_id == project_id)
    if since is not None:
        q = q.where(AssistantNudge.sent_at >= since)
    rows = await s.scalars(
        q.order_by(AssistantNudge.sent_at.desc())
        .limit(limit)
        .execution_options(populate_existing=True)
    )
    return list(rows.all())


async def last_dismissed(
    s: AsyncSession, user_id: uuid.UUID, project_id: uuid.UUID, since: datetime
) -> AssistantNudge | None:
    return await s.scalar(
        select(AssistantNudge)
        .where(
            AssistantNudge.user_id == user_id,
            AssistantNudge.project_id == project_id,
            AssistantNudge.status == "dismissed",
            AssistantNudge.acted_at >= since,
        )
        .order_by(AssistantNudge.acted_at.desc())
        .limit(1)
    )


# ---- 기억 ----


async def memories(s: AsyncSession, user_id: uuid.UUID) -> list[AssistantMemory]:
    rows = await s.scalars(
        select(AssistantMemory)
        .where(AssistantMemory.user_id == user_id)
        .order_by(AssistantMemory.updated_at.desc(), AssistantMemory.key)
        .execution_options(populate_existing=True)
    )
    return list(rows.all())


async def upsert_memory(
    s: AsyncSession,
    user_id: uuid.UUID,
    *,
    key: str,
    value: str,
    message_id: uuid.UUID,
    quote: str,
    now: datetime,
) -> None:
    """(사람, 키)마다 한 줄: 새 말로 덮어쓴다."""
    stmt = insert(AssistantMemory).values(
        id=uuid7(),
        user_id=user_id,
        key=key,
        value=value,
        evidence_message_id=message_id,
        evidence_quote=quote,
        created_at=now,
        updated_at=now,
    )
    await s.execute(
        stmt.on_conflict_do_update(
            constraint="uq_assistant_memory_user_key",
            set_={
                "value": value,
                "evidence_message_id": message_id,
                "evidence_quote": quote,
                "updated_at": now,
            },
        )
    )


async def trim_memory(s: AsyncSession, user_id: uuid.UUID, keep: int) -> int:
    """새것부터 keep줄만 남긴다(옛 선호가 새 선호를 이기지 않게). 지운 수."""
    old = (
        select(AssistantMemory.id)
        .where(AssistantMemory.user_id == user_id)
        .order_by(AssistantMemory.updated_at.desc(), AssistantMemory.key)
        .offset(keep)
    )
    res = await s.execute(delete(AssistantMemory).where(AssistantMemory.id.in_(old)))
    return res.rowcount or 0


async def delete_memory(s: AsyncSession, user_id: uuid.UUID, memory_id: uuid.UUID) -> bool:
    res = await s.execute(
        delete(AssistantMemory).where(
            AssistantMemory.id == memory_id, AssistantMemory.user_id == user_id
        )
    )
    return res.rowcount == 1
