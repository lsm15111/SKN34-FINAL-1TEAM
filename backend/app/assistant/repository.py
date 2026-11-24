"""비서 표 읽기 · 쓰기. commit은 하지 않는다(service · actions가 한다). 모든 조회에 user_id를 붙인다.

상태 바꾸기는 조건부 UPDATE 한 번이고 바뀐 행 수(또는 행)를 돌려준다: 1행이 아니면 부르는 쪽이 409로 바꾼다.
"""

import re
import uuid
from collections.abc import Sequence
from datetime import date, datetime

from sqlalchemy import and_, case, delete, func, or_, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant.models import (
    AssistantAction,
    AssistantMemory,
    AssistantMemoryMark,
    AssistantNudge,
    AssistantTurn,
)
from app.chat.models import Chat, ChatMessage
from app.notify.models import Notification
from app.project.models import Project, ProjectCondition
from app.quote.models import VendorQuote
from app.schedule.models import DateProposal
from app.shared.ids import uuid7
from app.visit.models import ENDED, LIVE, Visit, VisitEvent, VisitProposal

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


async def turn_started(s: AsyncSession, chat_id: uuid.UUID, turn: int) -> datetime | None:
    """그 턴부터 첫 말 시각. 대화 기록 쪽 사이 경계: 먼저 말 건 줄은 보낸 때가 이 시각 앞이면 앞 쪽에 끼운다."""
    return await s.scalar(
        select(func.min(ChatMessage.created_at)).where(
            ChatMessage.chat_id == chat_id, ChatMessage.turn >= turn
        )
    )


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
    """대화의 끝난 턴들 중 trace.rev가 revs 안인 것(대화 기록과 잇기). 실패한 턴은 빼요: 저장하지 못해 대화 rev가
    그대로라 다음 턴이 같은 rev로 저장돼요(R1a B6, 한 글에 두 턴이 붙지 않게)."""
    if not revs:
        return []
    rows = await s.scalars(
        select(AssistantTurn)
        .where(
            AssistantTurn.chat_id == chat_id,
            AssistantTurn.status != "failed",
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


async def decided_of(
    s: AsyncSession,
    user_id: uuid.UUID,
    surface: str,
    *,
    project_id: uuid.UUID | None = None,
    limit: int = 4,
    closed: Sequence[str] = ("due", "handled_elsewhere"),
) -> list[AssistantAction]:
    """사람이 최근에 처리한 제안(실행됨 · 거절함 · 실행 못 함)과 실행 없이 닫힌 제안(만료 까닭이 closed), 처리한 때
    새것부터. 닫힌 제안은 기한이 지나 닫혔으면 기한(방금 닫힌 오래된 카드가 밀려나지 않게), 그 밖은 만든 때.
    턴 사실 '최근 처리한 카드'."""
    reason = AssistantAction.result["reason"].astext
    shut = and_(AssistantAction.status == "expired", reason.in_(list(closed)))
    q = select(AssistantAction).where(
        AssistantAction.user_id == user_id,
        AssistantAction.surface == surface,
        or_(AssistantAction.status.in_(("executed", "rejected", "failed")), shut),
    )
    if project_id is not None:
        q = q.where(AssistantAction.project_id == project_id)
    due = and_(AssistantAction.status == "expired", reason == "due")
    when = func.coalesce(
        AssistantAction.decided_at,
        case((due, AssistantAction.expires_at), else_=AssistantAction.created_at),
    )
    rows = await s.scalars(
        q.order_by(when.desc()).limit(limit).execution_options(populate_existing=True)
    )
    return list(rows.all())


async def lock_target(s: AsyncSession, user_id: uuid.UUID, target_id: uuid.UUID) -> None:
    """같은 (사람, 대상)의 제안 만들기를 줄 세운다(트랜잭션 잠금, commit · rollback에 풀림). 대화 턴 · 먼저 말
    걸기가 거의 같이 제안해도 뒤의 것이 앞의 행을 보고 다시 쓴다(행 하나)."""
    key = f"assistant-offer:{user_id}:{target_id}"
    await s.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(key, 0))))


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


async def rejected_on(
    s: AsyncSession, user_id: uuid.UUID, kind: str, target_kind: str, target_id: uuid.UUID
) -> list[AssistantAction]:
    """그 사람이 거절한 같은 종류 · 같은 대상의 제안(새것부터). 새 사실 없이 다시 만들지 않으려고 읽는다."""
    rows = await s.scalars(
        select(AssistantAction)
        .where(
            AssistantAction.user_id == user_id,
            AssistantAction.kind == kind,
            AssistantAction.target_kind == target_kind,
            AssistantAction.target_id == target_id,
            AssistantAction.status == "rejected",
        )
        .order_by(AssistantAction.created_at.desc())
    )
    return list(rows.all())


async def replace_open(
    s: AsyncSession,
    user_id: uuid.UUID,
    target_kind: str,
    target_id: uuid.UUID,
    by: uuid.UUID,
    kinds: Sequence[str],
) -> list[AssistantAction]:
    """같은 (사람, 대상)의 열린 제안 중 종류가 kinds(서로 바꾸는 묶음, actions.swap_kinds)인 것을 만료(replaced)로
    바꾸고 바뀐 행을 돌려준다. by = 새 제안 id."""
    res = await s.execute(
        update(AssistantAction)
        .where(
            AssistantAction.user_id == user_id,
            AssistantAction.target_kind == target_kind,
            AssistantAction.target_id == target_id,
            AssistantAction.kind.in_(list(kinds)),
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


async def open_actions(
    s: AsyncSession, limit: int, after: tuple[datetime, uuid.UUID] | None = None
) -> list[AssistantAction]:
    """모든 사람의 열린 제안(proposed), 새 것부터 한 쪽 (sweep: 화면에서 직접 처리했는지 보기). after(앞 쪽 마지막
    줄의 created_at · id)를 주면 그보다 오래된 줄부터 읽는다(커서: 줄 수가 쪽보다 많아도 빠짐없이)."""
    q = select(AssistantAction).where(AssistantAction.status == "proposed")
    if after is not None:
        q = q.where(tuple_(AssistantAction.created_at, AssistantAction.id) < tuple_(*after))
    rows = await s.scalars(
        q.order_by(AssistantAction.created_at.desc(), AssistantAction.id.desc()).limit(limit)
    )
    return list(rows.all())


async def close_handled(
    s: AsyncSession, ids: Sequence[uuid.UUID], reason: str, line: str = "handled"
) -> list[uuid.UUID]:
    """열린 제안만 → expired(reason). 그 행동을 단 먼저 말 걸기 줄(sent · opened)도 expired(line: 할 일이 끝남
    handled · 대상이 기한 · 날이 지나 끝남 LAPSED)."""
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
            .values(status="expired", reason=line)
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


async def project_diys(s: AsyncSession, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, set[str]]:
    """공사 id → 직접 할 일 칩 줄의 키(모은 조건 diy.*). 줄이 없는 공사는 빠진다. 읽기 조인."""
    if not ids:
        return {}
    rows = await s.execute(
        select(ProjectCondition.project_id, ProjectCondition.key).where(
            ProjectCondition.project_id.in_(list(ids)), ProjectCondition.key.like("diy.%")
        )
    )
    out: dict[uuid.UUID, set[str]] = {}
    for pid, key in rows:
        out.setdefault(pid, set()).add(key)
    return out


async def project_budgets(s: AsyncSession, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, int | None]:
    """공사 id → 희망 예산(집 정보 '예산' 칸, 원. 없으면 None). 읽기 조인."""
    if not ids:
        return {}
    rows = await s.execute(select(Project.id, Project.budget_won).where(Project.id.in_(list(ids))))
    return {i: won for i, won in rows}


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


async def open_slot_halves(
    s: AsyncSession, user_id: uuid.UUID, project_id: uuid.UUID, visit_id: uuid.UUID
) -> set[tuple[date, str]]:
    """같은 공사의 다른 실측 요청에 열린 실측 시간 승인 카드가 고른 반나절(날, am · pm). 대화 도구 · 먼저 말 걸기가 같은
    반나절을 두 업체에 내지 않게 본다(QA r6 c4 1: 두 업체 모두 11.28 오전 카드, 둘째 승인이 409 slot_clash)."""
    rows = await s.scalars(
        select(AssistantAction.payload).where(
            AssistantAction.user_id == user_id,
            AssistantAction.project_id == project_id,
            AssistantAction.kind == "visit_slot",
            AssistantAction.status == "proposed",
            AssistantAction.target_id != visit_id,
        )
    )
    out = set()
    for p in rows.all():
        if p and p.get("day") and p.get("half"):
            out.add((date.fromisoformat(str(p["day"])), str(p["half"])))
    return out


async def last_pick(s: AsyncSession, visit_id: uuid.UUID) -> tuple[date, str] | None:
    """그 실측 요청에서 고객이 마지막으로 고른 반나절(이력 picked의 날 · am · pm, 읽기 조인). 업체가 다른 날을 낸
    요청(proposed)이면 업체가 어렵다고 한 때예요(다시 고르기 후보에서 뒤로 미뤄요, QA r10 c1 T9). 없으면 None."""
    row = (
        await s.execute(
            select(VisitEvent.day, VisitEvent.half)
            .where(
                VisitEvent.visit_id == visit_id,
                VisitEvent.to_status == "picked",
                VisitEvent.day.is_not(None),
                VisitEvent.half.is_not(None),
            )
            .order_by(VisitEvent.at.desc(), VisitEvent.id.desc())
            .limit(1)
        )
    ).first()
    return (row.day, str(row.half)) if row else None


# ---- 먼저 말 걸기 ----

SHOWN = ("sent", "opened")  # 대화 기록에 보이는 줄


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
    """since 뒤에 보낸 먼저 말 건 줄 수(하루 알림 상한 · 24시간 감점). 보낸 뒤 할 일이 끝나 닫힌 줄(expired:
    acted · handled · replaced)도 보낸 줄이라 상태와 상관없이 sent_at으로 센다."""
    q = select(func.count()).select_from(AssistantNudge)
    q = q.where(AssistantNudge.user_id == user_id, AssistantNudge.sent_at >= since)
    if channel is not None:
        q = q.where(AssistantNudge.channel == channel)
    return int(await s.scalar(q) or 0)


DEFERRED = ("night", "cap")  # 밤 · 하루 상한으로 미룬 줄의 까닭(policy.NudgeRules.check)


async def deferred_nudges(
    s: AsyncSession,
    user_id: uuid.UUID,
    surface: str,
    project_id: uuid.UUID | None,
    now: datetime,
) -> tuple[int, datetime | None]:
    """밤 · 하루 상한으로 미뤄 아직 기다리는 먼저 말 걸기 줄: (수, 가장 이른 보낼 때). 고객은 그 공사 줄만 센다."""
    q = select(func.count(), func.min(AssistantNudge.due_at)).where(
        AssistantNudge.user_id == user_id,
        AssistantNudge.surface == surface,
        AssistantNudge.status == "pending",
        AssistantNudge.reason.in_(DEFERRED),
        AssistantNudge.due_at > now,
    )
    if project_id is not None:
        q = q.where(AssistantNudge.project_id == project_id)
    n, due = (await s.execute(q)).one()
    return int(n or 0), due


async def dismissals(
    s: AsyncSession, user_id: uuid.UUID, since: datetime
) -> list[tuple[str, datetime, uuid.UUID]]:
    """since 뒤에 닫은 제안(트리거, 닫은 때, 대상 id)."""
    rows = await s.execute(
        select(AssistantNudge.trigger, AssistantNudge.acted_at, AssistantNudge.ref_id).where(
            AssistantNudge.user_id == user_id,
            AssistantNudge.status == "dismissed",
            AssistantNudge.acted_at >= since,
        )
    )
    return [(t, at, ref) for t, at, ref in rows]


# 행동 종류 → 그 행동을 실행하면 할 일이 끝나는 먼저 말 걸기 줄의 트리거(줄의 대상 ref_id = 행동 대상, 또는
# 행동 payload의 공사 날짜 제안 proposal_id일 때). 날짜 바꾸기 요청(date_change, 대상 = 확정)은 그 확정의 '공사
# 전날'(ref = 확정)과 요청할 때 수락 기다리던 날짜의 '공사 날짜 왔어요'(ref = 제안)를 닫는다
SETTLES: dict[str, tuple[str, ...]] = {
    "visit_request": ("no_pick", "vendor_out"),
    "visit_slot": ("visit_offered",),
    "vendor_confirm": ("quote_sent",),
    "dates_accept": ("dates_proposed",),
    "delay_accept": ("dates_proposed",),
    "date_change": ("work_eve", "dates_proposed"),
    "window_answer": ("visit_requested", "visit_picked"),
    "decline": ("visit_requested", "visit_picked"),
    "dates": ("deal_confirmed", "dates_requested"),
    # 07 자동화(대상: 추가 금액 · 확정 · 빠진 요청)
    "extra_answer": ("extra_added",),
    "work_check": ("work_done",),
    "visit_again": ("vendor_out",),
    # 보낸 실측 요청 취소: 그 요청의 반나절 고르기 줄
    "visit_cancel": ("visit_offered",),
}


async def close_lines_of(
    s: AsyncSession,
    a: AssistantAction,
    reason: str = "acted",
    kinds: Sequence[str] | None = None,
) -> int:
    """행동 a를 실행했다: 그 사람의 보이는 먼저 말 건 줄(sent · opened) 중 같은 대상 · 같은 묶음 종류(kinds, 없으면
    a의 종류만)의 승인 카드를 단 줄(새 카드로 바뀐 옛 카드 포함)과 같은 대상을 가리키는 줄(SETTLES)을 닫는다(expired ·
    reason). 다른 종류 카드를 단 줄(예: 업체 빠짐 줄의 실측 요청 카드)은 직접 할 일 실행으로 닫지 않는다. 닫은 줄 수."""
    same = select(AssistantAction.id).where(
        AssistantAction.user_id == a.user_id,
        AssistantAction.target_kind == a.target_kind,
        AssistantAction.target_id == a.target_id,
        AssistantAction.kind.in_(list(kinds or (a.kind,))),
    )
    hit = AssistantNudge.action_id.in_(same)
    if a.kind in SETTLES:
        refs = {a.target_id}
        pid = (a.payload or {}).get("proposal_id")
        if pid:
            refs.add(uuid.UUID(str(pid)))
        hit = or_(
            hit,
            AssistantNudge.ref_id.in_(list(refs)) & AssistantNudge.trigger.in_(SETTLES[a.kind]),
        )
    res = await s.execute(
        update(AssistantNudge)
        .where(AssistantNudge.user_id == a.user_id, AssistantNudge.status.in_(SHOWN), hit)
        .values(status="expired", reason=reason)
    )
    return res.rowcount or 0


async def settled_events(
    s: AsyncSession, user_id: uuid.UUID, notification_ids: Sequence[uuid.UUID]
) -> set[uuid.UUID]:
    """알림 id 중 끝난 일의 소식: 그 알림에서 만든 먼저 말 건 줄(dedup_key ev:{알림 id})이 할 일을 끝내거나 기한 ·
    날이 지나 닫힌 것(OVER)과, 가리키는 실측 요청이 끝났거나(취소 · 못 받음 · 기한 지남 · 안 옴 · 닫힘) 확정된 것
    (QA r3 s6 B3 · c4 #37: 취소한 요청의 '실측이 정해졌어요', 다른 업체를 확정해 닫힌 요청의 소식). 오늘 정할 일
    '새 소식'에서 끝난 일을 다시 보이지 않게 쓴다."""
    if not notification_ids:
        return set()
    keys = {f"ev:{i}": i for i in notification_ids}
    rows = await s.scalars(
        select(AssistantNudge.dedup_key).where(
            AssistantNudge.user_id == user_id,
            AssistantNudge.dedup_key.in_(list(keys)),
            AssistantNudge.status == "expired",
            AssistantNudge.reason.in_(OVER),
        )
    )
    return {keys[k] for k in rows.all()} | await _visit_done_news(s, user_id, notification_ids)


# 실측 요청 하나를 가리키는 알림 주소
NEWS_VISIT = re.compile(r"/projects/[^/?#]+/visits/([0-9a-fA-F-]{36})")
NEWS_QUOTE = re.compile(r"^quote:([0-9a-fA-F-]{36})$")  # 견적서 알림(dedup_key quote:{견적서 id})
# 업체가 다른 날을 낸 알림(dedup_key visit_proposed:{제안 id}): 그 제안이 닫히면(고름 · 다시 고름 · 기한 지남) 끝난 소식
NEWS_PROPOSAL = re.compile(r"^visit_proposed:([0-9a-fA-F-]{36})$")
VISIT_DONE = (*ENDED, "chosen")  # 이 요청의 진행 소식은 끝난 일(끝남 · 닫힘 · 확정)


def _uuid(text: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(text)
    except ValueError:
        return None


async def _visit_done_news(
    s: AsyncSession, user_id: uuid.UUID, notification_ids: Sequence[uuid.UUID]
) -> set[uuid.UUID]:
    """알림 중 가리키는 실측 요청(주소 · 견적서)이 끝났거나 확정된 것과, 업체가 다른 날을 낸 알림 중 그 제안이 닫힌 것
    (QA r10 c1: 다시 골라 실측이 잡힌 뒤에도 '다른 날을 제안했어요'가 새 소식에 남음). 끝남 알림 자체('못 받아요' ·
    '답하지 않았어요')는 요청을 가리키지 않아(공사 실측 목록 주소) 남는다."""
    found = await s.execute(
        select(Notification.id, Notification.link, Notification.dedup_key).where(
            Notification.user_id == user_id, Notification.id.in_(list(notification_ids))
        )
    )
    about: dict[uuid.UUID, uuid.UUID] = {}  # 알림 → 실측 요청
    quotes: dict[uuid.UUID, uuid.UUID] = {}  # 알림 → 견적서
    offers: dict[uuid.UUID, uuid.UUID] = {}  # 알림 → 업체가 낸 다른 날 제안
    for nid, link, key in found.all():
        m = NEWS_VISIT.search(link or "")
        q = NEWS_QUOTE.match(key or "")
        if (o := NEWS_PROPOSAL.match(key or "")) and (x := _uuid(o.group(1))):
            offers[nid] = x
        if m and (v := _uuid(m.group(1))):
            about[nid] = v
        elif q and (x := _uuid(q.group(1))):
            quotes[nid] = x
    closed: set[uuid.UUID] = set()
    if offers:
        shut = set(
            await s.scalars(
                select(VisitProposal.id).where(
                    VisitProposal.id.in_(list(set(offers.values()))),
                    VisitProposal.status != "open",
                )
            )
        )
        closed = {n for n, x in offers.items() if x in shut}
    if quotes:
        rows = await s.execute(
            select(VendorQuote.id, VendorQuote.visit_id).where(
                VendorQuote.id.in_(list(set(quotes.values())))
            )
        )
        of = dict(rows.all())
        about |= {n: of[x] for n, x in quotes.items() if x in of}
    if not about:
        return closed
    gone = set(
        await s.scalars(
            select(Visit.id).where(
                Visit.id.in_(list(set(about.values()))), Visit.status.in_(VISIT_DONE)
            )
        )
    )
    return closed | {n for n, v in about.items() if v in gone}


async def shown_all(s: AsyncSession, limit: int) -> list[AssistantNudge]:
    """모든 사람의 보이는 먼저 말 건 줄(sent · opened), 새것부터(정리: 할 일이 끝난 줄 닫기)."""
    rows = await s.scalars(
        select(AssistantNudge)
        .where(AssistantNudge.status.in_(SHOWN))
        .order_by(AssistantNudge.sent_at.desc())
        .limit(limit)
    )
    return list(rows.all())


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


SETTLED = ("acted", "handled")  # 할 일이 끝나 닫은 줄의 까닭: 대화 기록에 '완료'로 남는다
# 기한 · 날이 지나 닫은 줄의 까닭(할 일을 한 게 아니에요, R1b #10 · 고정 선 5): '완료'로 남기지 않아 대화 기록에서
# 빠진다(새 줄에 밀린 replaced와 같게). 실측 요청 기한 지남 · 공사 날이 옴 · 고객 확인 없이 자동으로 끝난 공사
LAPSED = "lapsed"
OVER = (*SETTLED, LAPSED)  # 더 할 일이 없는 줄(오늘 정할 일 '새 소식'에서 빼는 기준)


async def feed_nudges(
    s: AsyncSession,
    user_id: uuid.UUID,
    surface: str,
    project_id: uuid.UUID | None,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
    settled: bool = False,
    limit: int = 30,
) -> list[AssistantNudge]:
    """대화 기록 한 쪽에 끼울 먼저 말 건 줄(새것부터): 보이는 줄(sent · opened)과, settled면 할 일이 끝나 닫힌 줄
    (expired acted · handled, '완료'로 남김). 보낸 때가 [since, until) 안인 줄만. 고객은 그 공사 것만.
    닫은 줄(dismissed) · 새 줄에 밀린 줄(replaced)은 오지 않는다."""
    hit = AssistantNudge.status.in_(SHOWN)
    if settled:
        done = and_(AssistantNudge.status == "expired", AssistantNudge.reason.in_(SETTLED))
        hit = or_(hit, done)
    q = select(AssistantNudge).where(
        AssistantNudge.user_id == user_id,
        AssistantNudge.surface == surface,
        AssistantNudge.sent_at.is_not(None),
        AssistantNudge.body.is_not(None),
        hit,
    )
    if project_id is not None:
        q = q.where(AssistantNudge.project_id == project_id)
    if since is not None:
        q = q.where(AssistantNudge.sent_at >= since)
    if until is not None:
        q = q.where(AssistantNudge.sent_at < until)
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


async def delete_memory(s: AsyncSession, user_id: uuid.UUID, memory_id: uuid.UUID) -> str | None:
    """내 기억 한 줄을 지운다. 지운 줄의 키(없거나 남의 것이면 None)."""
    res = await s.execute(
        delete(AssistantMemory)
        .where(AssistantMemory.id == memory_id, AssistantMemory.user_id == user_id)
        .returning(AssistantMemory.key)
    )
    return res.scalar_one_or_none()


async def memory_marks(s: AsyncSession, user_id: uuid.UUID) -> dict[str, datetime]:
    """기억 칸마다 마지막으로 바뀐 때(말한 때 · 지운 때 · 칩으로 줄인 때)."""
    rows = await s.execute(
        select(AssistantMemoryMark.key, AssistantMemoryMark.changed_at).where(
            AssistantMemoryMark.user_id == user_id
        )
    )
    return {key: at for key, at in rows.all()}


async def mark_memory(s: AsyncSession, user_id: uuid.UUID, key: str, at: datetime) -> None:
    """기억 칸이 바뀐 때를 적는다(늘기만, 지운 칸도 남긴다)."""
    stmt = insert(AssistantMemoryMark).values(user_id=user_id, key=key, changed_at=at)
    await s.execute(
        stmt.on_conflict_do_update(
            index_elements=["user_id", "key"],
            set_={
                "changed_at": func.greatest(
                    AssistantMemoryMark.changed_at, stmt.excluded.changed_at
                )
            },
        )
    )
