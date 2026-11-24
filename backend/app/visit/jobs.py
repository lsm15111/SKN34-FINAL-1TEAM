"""visit 기한 일 처리 함수 (visit_reply_due · visit_pick_due · visit_accept_due · visit_proposal_due · visit_change_due · visit_reminder · visit_quote_due).

worker.JOB_HANDLERS가 이 HANDLERS를 모은다. 계약은 jobs.service.JobHandler:
새 세션에서 '아직 그 상태 · 기한이 지났을 때만' 조건부 UPDATE → 바꿨으면 Outcome(changed=True, 신호),
아니면 False(skipped). 같은 일이 두 번 돌아도 두 번째는 False다. commit · 신호는 worker.sweep_jobs가 한다.
잠금 순서는 사람의 요청과 같다: 프로젝트 → 요청 → 제안 · 바꾸기 행.
"""

import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.calc import deadline
from app.jobs.models import Job
from app.jobs.service import JobHandler, Outcome, StatePush
from app.notify import service as notify_service
from app.notify.catalog import link
from app.project import service as project_service
from app.quote import service as quote_service
from app.shared.korean import i_ga
from app.visit import flow
from app.visit import repository as repo
from app.visit import service as svc
from app.visit.models import Visit, VisitChange, VisitEvent, VisitProposal


async def _work(s: AsyncSession, v: Visit) -> str:
    """업체 알림 끝 공사 이름 ('노원구 상계동 도배')"""
    return flow._work(await flow._home(s, v), v)


def _signal(v: Visit, owner: uuid.UUID | None) -> Outcome:
    """commit 뒤 양쪽 화면 다시 읽기 · 안 읽은 알림 수"""
    users = (owner, v.vendor_id)
    return Outcome(
        changed=True, states=[StatePush(users, "visit", v.id, v.project_id)], unread=list(users)
    )


async def _locked(s: AsyncSession, visit_id: uuid.UUID | None) -> Visit | None:
    """요청을 프로젝트 → 요청 순서로 잠그고 다시 읽는다 (대상이 지워졌으면 None)"""
    if visit_id is None:
        return None
    v = await repo.get(s, visit_id)
    if v is None:
        return None
    await project_service.lock(s, v.project_id)
    return await repo.lock(s, visit_id)


async def _owner(s: AsyncSession, v: Visit) -> uuid.UUID:
    return (await repo.home_facts(s, [(v.project_id, v.trade)]))[(v.project_id, v.trade)].owner_id


def _event(v: Visit, frm: str, to: str, code: str, now: datetime, **kw) -> VisitEvent:
    return VisitEvent(visit_id=v.id, from_status=frm, to_status=to, code=code, at=now, **kw)


async def on_reply_due(s: AsyncSession, job: Job, now: datetime) -> bool | Outcome:
    """요청 + 48시간: 아직 requested면 expired(reply) · 담기 칸 비움 · 고객 알림 '답하지 않았어요'"""
    v = await _locked(s, job.ref_id)
    if v is None or v.status != "requested" or not deadline.is_over(now, v.reply_due_at):
        return False
    values = {"status": "expired", "expired_reason": "reply"}
    if not await repo.set_status(s, v.id, allowed_from=("requested",), values=values):
        return False
    s.add(_event(v, "requested", "expired", "expired", now))
    await svc.end_visit(s, v, now=now, shortlist_code="expired")
    owner = await _owner(s, v)
    await notify_service.add(
        s,
        user_id=owner,
        kind="visit_reply_expired",
        body=f"{i_ga(v.vendor_name)} 48시간 안에 답하지 않았어요. 한 번 더 요청할 수 있어요",
        link=link("visit_reply_expired", pid=v.project_id),
        dedup_key=f"visit_reply_expired:{v.id}",
        project_id=v.project_id,
    )
    return _signal(v, owner)


async def on_pick_due(s: AsyncSession, job: Job, now: datetime) -> bool | Outcome:
    """업체 답 + 7일: 아직 offered면 expired(pick) · 담기 칸 비움 · 업체 알림 (기간이 풀린다)"""
    v = await _locked(s, job.ref_id)
    if v is None or v.status != "offered":
        return False
    w = (await repo.windows(s, [v.id])).get(v.id)
    if w is None or not deadline.is_over(now, w.pick_due_at):
        return False
    values = {"status": "expired", "expired_reason": "pick"}
    if not await repo.set_status(s, v.id, allowed_from=("offered",), values=values):
        return False
    s.add(_event(v, "offered", "expired", "expired", now))
    await svc.end_visit(s, v, now=now, shortlist_code="expired")
    await notify_service.add(
        s,
        user_id=v.vendor_id,
        kind="visit_pick_expired",
        body=f"고객이 날짜를 고르지 않았어요. 그 기간이 다시 열렸어요 · {await _work(s, v)}",
        link=link("visit_pick_expired", vid=v.id),
        dedup_key=f"visit_pick_expired:{v.id}",
    )
    return _signal(v, await _owner(s, v))


async def on_accept_due(s: AsyncSession, job: Job, now: datetime) -> bool | Outcome:
    """고른 때 + 48시간: 아직 picked면 잡아 둔 반나절만 풀고 offered로 (D12 보류 최소 처리, L10).
    고르기 기한도 지났으면 다음 수거에 기한 지남이 되게 한다."""
    v = await _locked(s, job.ref_id)
    if v is None or v.status != "picked":
        return False
    hold = (await repo.holds_of_visits(s, [v.id])).get(v.id)
    if hold is None or hold.kind != "hold" or not deadline.is_over(now, hold.until):
        return False
    if not await repo.set_status(s, v.id, allowed_from=("picked",), values={"status": "offered"}):
        return False
    await repo.release_holds(s, v.id, now)
    s.add(_event(v, "picked", "offered", "hold_released", now, day=hold.day, half=hold.half))
    await flow._back_to_offered(s, v, now)
    owner = await _owner(s, v)
    await notify_service.add(
        s,
        user_id=owner,
        kind="visit_hold_released",
        body=f"{i_ga(v.vendor_name)} 수락하지 않아 날짜를 다시 골라 주세요",
        link=link("visit_hold_released", pid=v.project_id, vid=v.id),
        dedup_key=f"visit_hold_released:{hold.id}",
        project_id=v.project_id,
    )
    return _signal(v, owner)


async def on_proposal_due(s: AsyncSession, job: Job, now: datetime) -> bool | Outcome:
    """제안 + 48시간: 아직 열린 제안이면 expired. 처음 제안이면 요청을 offered로(D12 최소 처리),
    바꾸기 요청에 낸 다른 날이면 그 바꾸기 요청도 expired(원래 일정 그대로)."""
    first = await s.get(VisitProposal, job.ref_id) if job.ref_id else None
    v = await _locked(s, first.visit_id) if first else None
    if v is None:
        return False
    p = await s.get(VisitProposal, first.id, populate_existing=True)
    if p is None or p.status != "open" or not deadline.is_over(now, p.due_at):
        return False
    if not await repo.close_proposal(s, p.id, "expired", now):
        return False
    owner = await _owner(s, v)
    if p.change_id is not None:
        await repo.set_change(
            s,
            p.change_id,
            allowed_from=("countered",),
            values={"status": "expired", "closed_at": now},
        )
        s.add(_event(v, v.status, v.status, "change_expired", now))
        await notify_service.add(
            s,
            user_id=owner,
            kind="visit_change_expired",
            body=f"{v.vendor_name} 일정 바꾸기가 기한이 지나 원래 일정 그대로예요",
            link=await flow._thread_link(s, v, "visit_change_expired", vendor_side=False),
            dedup_key=f"visit_change_expired:{p.change_id}",
            project_id=v.project_id,
        )
        return _signal(v, owner)
    if v.status != "proposed" or not await repo.set_status(
        s, v.id, allowed_from=("proposed",), values={"status": "offered"}
    ):
        return Outcome(changed=True)
    s.add(_event(v, "proposed", "offered", "expired", now))
    await flow._back_to_offered(s, v, now)
    await notify_service.add(
        s,
        user_id=v.vendor_id,
        kind="visit_proposal_expired",
        body=f"고객이 제안한 날을 고르지 않았어요 · {await _work(s, v)}",
        link=link("visit_proposal_expired", vid=v.id),
        dedup_key=f"visit_proposal_expired:{p.id}",
    )
    return _signal(v, owner)


async def on_change_due(s: AsyncSession, job: Job, now: datetime) -> bool | Outcome:
    """바꾸기 요청 + 48시간: 업체가 아직 답하지 않았으면 요청 expired · 원래 일정 그대로 · 고객 알림"""
    first = await s.get(VisitChange, job.ref_id) if job.ref_id else None
    v = await _locked(s, first.visit_id) if first else None
    if v is None:
        return False
    c = await s.get(VisitChange, first.id, populate_existing=True)
    if c is None or c.status != "open" or not deadline.is_over(now, c.due_at):
        return False
    values = {"status": "expired", "closed_at": now}
    if not await repo.set_change(s, c.id, allowed_from=("open",), values=values):
        return False
    s.add(_event(v, v.status, v.status, "change_expired", now, day=c.to_day, half=c.to_half))
    owner = await _owner(s, v)
    await notify_service.add(
        s,
        user_id=owner,
        kind="visit_change_expired",
        body=f"{v.vendor_name} 답이 없어 원래 일정 그대로예요",
        link=await flow._thread_link(s, v, "visit_change_expired", vendor_side=False),
        dedup_key=f"visit_change_expired:{c.id}",
        project_id=v.project_id,
    )
    return _signal(v, owner)


async def on_reminder(s: AsyncSession, job: Job, now: datetime) -> bool | Outcome:
    """실측 전날 18:00: 아직 그 날로 확정이면 양쪽 알림. 고객이 동 · 호수를 아직 안 보냈으면 한 줄 더(I7 B)."""
    v = await repo.get(s, job.ref_id) if job.ref_id else None
    if v is None or v.status != "booked" or v.booked_day is None:
        return False
    at = deadline.reminder_at(v.booked_day)
    if job.run_at != at or not deadline.is_over(now, at):  # 일정이 바뀌었으면 옛 알림은 하지 않는다
        return False
    # worker가 늦게 돌아 실측 날이 됐으면 '내일 … 실측이에요'는 틀린 말이라 보내지 않아요(점검 R4#11)
    if svc.today_of(now) >= v.booked_day:
        return False
    owner = await _owner(s, v)
    key = f"visit_reminder:{v.id}:{v.booked_day:%Y%m%d}{v.booked_half}"
    if await repo.noticed(s, owner, key):
        return False
    half = svc.HALF_LABEL[v.booked_half]
    tail = (
        ""
        if await repo.address_sent(s, v.project_id, v.vendor_id)
        else " · 동 · 호수는 채팅으로 알려 주세요"
    )
    await notify_service.add(
        s,
        user_id=owner,
        kind="visit_reminder",
        body=f"내일 {half} 실측이에요 · {v.vendor_name}{tail}",
        link=link("visit_reminder", pid=v.project_id, vid=v.id),
        dedup_key=key,
        project_id=v.project_id,
    )
    h = (await repo.home_facts(s, [(v.project_id, v.trade)]))[(v.project_id, v.trade)]
    std = (await quote_service.latest_of(s, [v.project_id])).get((v.project_id, v.trade))
    await notify_service.add(
        s,
        user_id=v.vendor_id,
        kind="visit_reminder",
        body=f"내일 {half} 실측이에요 · {svc.area_label(h, std) or h.sgg}",
        link=f"/vendor/requests/{v.id}",
        dedup_key=key,
    )
    return Outcome(changed=True, unread=[owner, v.vendor_id])


async def on_quote_due(s: AsyncSession, job: Job, now: datetime) -> bool | Outcome:
    """실측일 + 3일 18:00: 견적서가 아직 없으면 고객 알림 '견적서가 늦어요'(기다리기 · 닫기)"""
    v = await repo.get(s, job.ref_id) if job.ref_id else None
    if v is None or v.status not in ("booked", "visited") or v.quote_due_at is None:
        return False
    if not deadline.is_over(now, v.quote_due_at):
        return False
    if (await quote_service.sent_briefs(s, [v.id])).get(v.id) is not None:
        return False
    owner = await _owner(s, v)
    key = f"quote_late:{v.id}:{v.quote_due_at:%Y%m%d}"
    if await repo.noticed(s, owner, key):
        return False
    await notify_service.add(
        s,
        user_id=owner,
        kind="quote_late",
        body=f"{v.vendor_name} 실측 견적서가 늦어요. 더 기다리거나 닫을 수 있어요",
        link=link("quote_late", pid=v.project_id),
        dedup_key=key,
        project_id=v.project_id,
    )
    return Outcome(
        changed=True,
        states=[StatePush((owner,), "visit", v.id, v.project_id)],
        unread=[owner],
    )


HANDLERS: dict[str, JobHandler] = {
    "visit_reply_due": on_reply_due,
    "visit_pick_due": on_pick_due,
    "visit_accept_due": on_accept_due,
    "visit_proposal_due": on_proposal_due,
    "visit_change_due": on_change_due,
    "visit_reminder": on_reminder,
    "visit_quote_due": on_quote_due,
}
