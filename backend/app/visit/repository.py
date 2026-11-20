import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from app.notify.models import Notification
from app.project.models import Project, ProjectTrade
from app.review.models import Review
from app.schedule.models import DateProposal, Deal
from app.thread.models import Thread
from app.vendor.models import Vendor, VendorReviewLink
from app.visit.models import (
    LIVE,
    Shortlist,
    Visit,
    VisitChange,
    VisitEvent,
    VisitHold,
    VisitPhoto,
    VisitProposal,
    VisitProposalSlot,
    VisitWindow,
)


async def of_project(s: AsyncSession, project_id: uuid.UUID, trade: str | None) -> list[Visit]:
    """이 집 실측 요청 (최근 순, 닫힌 것 포함)"""
    q = select(Visit).where(Visit.project_id == project_id)
    if trade:
        q = q.where(Visit.trade == trade)
    q = q.order_by(Visit.created_at.desc(), Visit.id.desc())
    return list((await s.execute(q)).scalars().all())


async def live(s: AsyncSession, project_id: uuid.UUID, trade: str) -> list[Visit]:
    """칸을 차지하는 요청 (요청함 · 견적서 옴 · 확정)"""
    q = select(Visit).where(
        Visit.project_id == project_id, Visit.trade == trade, Visit.status.in_(LIVE)
    )
    return list((await s.execute(q)).scalars().all())


async def attempts(
    s: AsyncSession, project_id: uuid.UUID, trade: str, vendor_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    """업체마다 이 집 · 이 공정에 보낸 요청의 가장 큰 시도 번호 (없으면 빠진다)"""
    if not vendor_ids:
        return {}
    q = (
        select(Visit.vendor_id, func.max(Visit.attempt))
        .where(
            Visit.project_id == project_id,
            Visit.trade == trade,
            Visit.vendor_id.in_(vendor_ids),
        )
        .group_by(Visit.vendor_id)
    )
    return {vid: int(n) for vid, n in (await s.execute(q)).all()}


async def latest_by_vendor(
    s: AsyncSession, project_id: uuid.UUID, trade: str, vendor_ids: list[uuid.UUID]
) -> dict[uuid.UUID, Visit]:
    """업체마다 이 집 · 이 공정의 가장 최근 요청"""
    q = (
        select(Visit)
        .where(
            Visit.project_id == project_id,
            Visit.trade == trade,
            Visit.vendor_id.in_(vendor_ids),
        )
        .order_by(Visit.vendor_id, Visit.created_at.desc(), Visit.id.desc())
        .ext(distinct_on(Visit.vendor_id))
    )
    return {v.vendor_id: v for v in (await s.execute(q)).scalars()}


async def get(s: AsyncSession, visit_id: uuid.UUID) -> Visit | None:
    return await s.get(Visit, visit_id, populate_existing=True)


async def set_status(
    s: AsyncSession, visit_id: uuid.UUID, *, allowed_from: tuple[str, ...], values: dict
) -> bool:
    """지금 상태가 allowed_from일 때만 바꾼다 (동시에 두 번 눌러도 한 번만 바뀜)."""
    res = await s.execute(
        update(Visit)
        .where(Visit.id == visit_id, Visit.status.in_(allowed_from))
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    return res.rowcount == 1


async def mark_seen(s: AsyncSession, visit_id: uuid.UUID, at: datetime) -> None:
    """처음 열었을 때만 찍는다 (두 번 불러도 처음 시각 그대로)."""
    await s.execute(
        update(Visit)
        .where(Visit.id == visit_id, Visit.vendor_seen_at.is_(None))
        .values(vendor_seen_at=at)
        .execution_options(synchronize_session=False)
    )


def _last_event():
    return (
        select(VisitEvent.visit_id, func.max(VisitEvent.at).label("at"))
        .group_by(VisitEvent.visit_id)
        .subquery()
    )


async def last_events(s: AsyncSession, visit_ids: list[uuid.UUID]) -> dict[uuid.UUID, datetime]:
    """요청마다 마지막 상태가 바뀐 때 (닫힌 날 · 견적서를 보낸 날)"""
    if not visit_ids:
        return {}
    q = select(VisitEvent.visit_id, func.max(VisitEvent.at)).where(
        VisitEvent.visit_id.in_(visit_ids)
    )
    return {vid: at for vid, at in (await s.execute(q.group_by(VisitEvent.visit_id))).all()}


async def of_vendor(
    s: AsyncSession,
    vendor_id: uuid.UUID,
    statuses: tuple[str, ...],
    before: datetime | None = None,
    limit: int | None = None,
) -> list[tuple[Visit, datetime]]:
    """업체가 받은 요청과 마지막으로 상태가 바뀐 때 (마지막 이벤트가 최근인 순)"""
    last = _last_event()
    q = (
        select(Visit, last.c.at)
        .join(last, last.c.visit_id == Visit.id)
        .where(Visit.vendor_id == vendor_id, Visit.status.in_(statuses))
    )
    if before is not None:
        q = q.where(last.c.at < before)
    q = q.order_by(last.c.at.desc(), Visit.id.desc())
    if limit is not None:
        q = q.limit(limit)
    return [(v, at) for v, at in (await s.execute(q)).all()]


async def counts_of_vendor(s: AsyncSession, vendor_id: uuid.UUID) -> dict[str, int]:
    q = select(Visit.status, func.count()).where(Visit.vendor_id == vendor_id)
    return {st: n for st, n in (await s.execute(q.group_by(Visit.status))).all()}


async def recent_moves(s: AsyncSession, vendor_id: uuid.UUID, since: datetime) -> dict[str, int]:
    """그 업체 요청이 since 뒤에 어떤 상태로 몇 번 바뀌었나 (받음 · 견적서 보냄 · 확정)"""
    q = (
        select(VisitEvent.to_status, func.count())
        .join(Visit, Visit.id == VisitEvent.visit_id)
        .where(Visit.vendor_id == vendor_id, VisitEvent.at >= since)
        .group_by(VisitEvent.to_status)
    )
    return {st: n for st, n in (await s.execute(q)).all()}


async def lock(s: AsyncSession, visit_id: uuid.UUID) -> Visit | None:
    """같은 요청의 견적서 저장 · 보내기가 줄 서게 요청 행을 잠그고 다시 읽는다."""
    q = select(Visit).where(Visit.id == visit_id).with_for_update()
    return (await s.execute(q.execution_options(populate_existing=True))).scalar_one_or_none()


async def set_quote_ver(
    s: AsyncSession,
    visit_id: uuid.UUID,
    *,
    again: bool,
    seen: int | None,
    new: int,
    first_from: tuple[str, ...] = ("requested",),
) -> bool:
    """첫 보내기: first_from(v2 requested · v3 booked · visited) → quoted.
    다시 올리기: quoted이고 quote_ver가 본 버전일 때만 새 버전으로."""
    cond = (
        [Visit.status == "quoted", Visit.quote_ver == seen]
        if again
        else [Visit.status.in_(first_from)]
    )
    res = await s.execute(
        update(Visit)
        .where(Visit.id == visit_id, *cond)
        .values(status="quoted", quote_ver=new)
        .execution_options(synchronize_session=False)
    )
    return res.rowcount == 1


async def choose(s: AsyncSession, visit_id: uuid.UUID, seen: int) -> bool:
    """견적서 옴이고 고객이 본 버전이 지금 버전일 때만 확정으로 바꾼다."""
    res = await s.execute(
        update(Visit)
        .where(Visit.id == visit_id, Visit.status == "quoted", Visit.quote_ver == seen)
        .values(status="chosen")
        .execution_options(synchronize_session=False)
    )
    return res.rowcount == 1


async def by_ids(s: AsyncSession, visit_ids: list[uuid.UUID]) -> dict[uuid.UUID, Visit]:
    if not visit_ids:
        return {}
    q = select(Visit).where(Visit.id.in_(visit_ids)).execution_options(populate_existing=True)
    return {v.id: v for v in (await s.execute(q)).scalars()}


# ======== v3 담기 · 업체 기간 · 반나절 잡기 · 제안 · 바꾸기 ========


async def shortlists_active(s: AsyncSession, project_id: uuid.UUID, trade: str) -> list[Shortlist]:
    """이 집 · 이 공정에 담은 업체 (칸 번호 순)"""
    q = (
        select(Shortlist)
        .where(
            Shortlist.project_id == project_id,
            Shortlist.trade == trade,
            Shortlist.status == "active",
        )
        .order_by(Shortlist.slot)
        .execution_options(populate_existing=True)
    )
    return list((await s.execute(q)).scalars().all())


async def remove_shortlist(
    s: AsyncSession, shortlist_id: uuid.UUID | None, code: str, at: datetime
) -> bool:
    """담기 칸 비우기 (살아 있을 때만). 두 번 불러도 한 번만 바뀐다."""
    if shortlist_id is None:
        return False
    res = await s.execute(
        update(Shortlist)
        .where(Shortlist.id == shortlist_id, Shortlist.status == "active")
        .values(status="removed", removed_code=code, removed_at=at)
        .execution_options(synchronize_session=False)
    )
    return res.rowcount == 1


async def remove_shortlists_of(
    s: AsyncSession,
    project_id: uuid.UUID,
    trade: str,
    code: str,
    at: datetime,
    keep: set[uuid.UUID],
) -> int:
    """이 공정의 담기 칸을 비운다 (keep에 든 칸은 그대로). 확정 · 다시 고르기에서 쓴다."""
    q = update(Shortlist).where(
        Shortlist.project_id == project_id,
        Shortlist.trade == trade,
        Shortlist.status == "active",
    )
    if keep:
        q = q.where(Shortlist.id.not_in(list(keep)))
    res = await s.execute(
        q.values(status="removed", removed_code=code, removed_at=at).execution_options(
            synchronize_session=False
        )
    )
    return res.rowcount


async def windows(s: AsyncSession, visit_ids: list[uuid.UUID]) -> dict[uuid.UUID, VisitWindow]:
    if not visit_ids:
        return {}
    q = (
        select(VisitWindow)
        .where(VisitWindow.visit_id.in_(visit_ids))
        .execution_options(populate_existing=True)
    )
    return {w.visit_id: w for w in (await s.execute(q)).scalars()}


async def holds_of_visits(
    s: AsyncSession, visit_ids: list[uuid.UUID]
) -> dict[uuid.UUID, VisitHold]:
    """요청마다 살아 있는 반나절 잡기 (요청 하나에 하나)"""
    if not visit_ids:
        return {}
    q = (
        select(VisitHold)
        .where(VisitHold.visit_id.in_(visit_ids), VisitHold.status == "active")
        .execution_options(populate_existing=True)
    )
    return {h.visit_id: h for h in (await s.execute(q)).scalars()}


async def vendor_holds(
    s: AsyncSession, vendor_id: uuid.UUID, start: date, end: date
) -> list[VisitHold]:
    """업체 달력에서 살아 있는 잡기 (잡아 둠 · 확정), 날 · 반나절 · 칸 순"""
    q = (
        select(VisitHold)
        .where(
            VisitHold.vendor_id == vendor_id,
            VisitHold.status == "active",
            VisitHold.day >= start,
            VisitHold.day <= end,
        )
        .order_by(VisitHold.day, VisitHold.half, VisitHold.seat)
        .execution_options(populate_existing=True)
    )
    return list((await s.execute(q)).scalars().all())


async def used_seats(s: AsyncSession, vendor_id: uuid.UUID, day: date, half: str) -> list[int]:
    """그 반나절에서 이미 쓴 칸 번호 (다른 트랜잭션이 commit한 것까지 새로 읽는다)"""
    q = select(VisitHold.seat).where(
        VisitHold.vendor_id == vendor_id,
        VisitHold.day == day,
        VisitHold.half == half,
        VisitHold.status == "active",
    )
    return list((await s.execute(q)).scalars().all())


async def release_holds(s: AsyncSession, visit_id: uuid.UUID, at: datetime) -> int:
    """그 요청의 살아 있는 잡기를 푼다 (없으면 0)"""
    res = await s.execute(
        update(VisitHold)
        .where(VisitHold.visit_id == visit_id, VisitHold.status == "active")
        .values(status="released", released_at=at)
        .execution_options(synchronize_session=False)
    )
    return res.rowcount


async def book_hold(s: AsyncSession, hold_id: uuid.UUID) -> bool:
    """잡아 둔 반나절 → 확정 (잡아 둠이고 살아 있을 때만)"""
    res = await s.execute(
        update(VisitHold)
        .where(VisitHold.id == hold_id, VisitHold.status == "active", VisitHold.kind == "hold")
        .values(kind="booked", until=None)
        .execution_options(synchronize_session=False)
    )
    return res.rowcount == 1


async def proposals_open(
    s: AsyncSession, visit_ids: list[uuid.UUID]
) -> dict[uuid.UUID, VisitProposal]:
    """요청마다 열린 제안 (처음 제안 · 바꾸기 요청에 낸 다른 날)"""
    if not visit_ids:
        return {}
    q = (
        select(VisitProposal)
        .where(VisitProposal.visit_id.in_(visit_ids), VisitProposal.status == "open")
        .execution_options(populate_existing=True)
    )
    return {p.visit_id: p for p in (await s.execute(q)).scalars()}


async def proposal_slots(
    s: AsyncSession, proposal_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[tuple[date, str]]]:
    if not proposal_ids:
        return {}
    q = (
        select(VisitProposalSlot)
        .where(VisitProposalSlot.proposal_id.in_(proposal_ids))
        .order_by(VisitProposalSlot.day, VisitProposalSlot.half)
    )
    out: dict[uuid.UUID, list[tuple[date, str]]] = {}
    for x in (await s.execute(q)).scalars():
        out.setdefault(x.proposal_id, []).append((x.day, x.half))
    return out


async def close_proposal(
    s: AsyncSession, proposal_id: uuid.UUID, status: str, at: datetime
) -> bool:
    """열린 제안을 닫는다 (picked · repicked · expired)"""
    res = await s.execute(
        update(VisitProposal)
        .where(VisitProposal.id == proposal_id, VisitProposal.status == "open")
        .values(status=status, closed_at=at)
        .execution_options(synchronize_session=False)
    )
    return res.rowcount == 1


async def changes_open(s: AsyncSession, visit_ids: list[uuid.UUID]) -> dict[uuid.UUID, VisitChange]:
    """요청마다 열린 일정 바꾸기 요청 (open · countered)"""
    if not visit_ids:
        return {}
    q = (
        select(VisitChange)
        .where(VisitChange.visit_id.in_(visit_ids), VisitChange.status.in_(("open", "countered")))
        .execution_options(populate_existing=True)
    )
    return {c.visit_id: c for c in (await s.execute(q)).scalars()}


async def lock_change(s: AsyncSession, change_id: uuid.UUID) -> VisitChange | None:
    q = select(VisitChange).where(VisitChange.id == change_id).with_for_update()
    return (await s.execute(q.execution_options(populate_existing=True))).scalar_one_or_none()


async def set_change(
    s: AsyncSession, change_id: uuid.UUID, *, allowed_from: tuple[str, ...], values: dict
) -> bool:
    """일정 바꾸기 요청 상태를 바꾼다 (지금 상태가 allowed_from일 때만)"""
    res = await s.execute(
        update(VisitChange)
        .where(VisitChange.id == change_id, VisitChange.status.in_(allowed_from))
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    return res.rowcount == 1


async def latest_of_vendor(
    s: AsyncSession, project_id: uuid.UUID, trade: str, vendor_id: uuid.UUID
) -> Visit | None:
    """이 집 · 이 공정에서 그 업체에 보낸 가장 마지막 시도"""
    q = (
        select(Visit)
        .where(Visit.project_id == project_id, Visit.trade == trade, Visit.vendor_id == vendor_id)
        .order_by(Visit.attempt.desc(), Visit.created_at.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    )
    return (await s.execute(q)).scalar_one_or_none()


async def visits_of_vendor(
    s: AsyncSession, vendor_id: uuid.UUID, statuses: tuple[str, ...]
) -> list[Visit]:
    q = select(Visit).where(Visit.vendor_id == vendor_id, Visit.status.in_(statuses))
    return list((await s.execute(q)).scalars().all())


# ---- 읽기 조인 (다른 기능 표는 읽기만) ----


@dataclass(frozen=True)
class VendorFacts:
    """실측 일정에 쓰는 업체 값 (vendors 읽기 조인)"""

    vendor_id: uuid.UUID
    name: str
    status: str
    instant_default: bool
    capacity: int
    suspended: bool


async def vendor_facts(
    s: AsyncSession, vendor_ids: list[uuid.UUID]
) -> dict[uuid.UUID, VendorFacts]:
    if not vendor_ids:
        return {}
    q = select(
        Vendor.user_id,
        Vendor.biz_name,
        Vendor.status,
        Vendor.instant_default,
        Vendor.visit_capacity,
        Vendor.suspended_at,
    ).where(Vendor.user_id.in_(vendor_ids))
    return {
        vid: VendorFacts(vid, name or "업체", st, bool(inst), int(cap or 1), sus is not None)
        for vid, name, st, inst, cap, sus in (await s.execute(q)).all()
    }


@dataclass(frozen=True)
class HomeFacts:
    """업체에 가도 되는 집 정보 (projects · project_trades 읽기 조인). 이름 · 연락처 · 동 · 호는 없다."""

    project_id: uuid.UUID
    owner_id: uuid.UUID
    sido: str
    sgg: str
    emd: str | None
    area_m2: Decimal | None
    area_basis: str | None
    occupied: bool
    budget_won: int | None
    scope: str | None
    grade: str | None


async def home_facts(
    s: AsyncSession, keys: list[tuple[uuid.UUID, str]]
) -> dict[tuple[uuid.UUID, str], HomeFacts]:
    """(공사, 공정)마다 집 정보"""
    if not keys:
        return {}
    ids = list({k[0] for k in keys})
    q = (
        select(
            Project.id,
            Project.owner_id,
            Project.sido,
            Project.sgg,
            Project.emd,
            Project.area_m2,
            Project.area_basis,
            Project.occupied,
            Project.budget_won,
            ProjectTrade.trade,
            ProjectTrade.scope,
            ProjectTrade.grade,
        )
        .outerjoin(ProjectTrade, ProjectTrade.project_id == Project.id)
        .where(Project.id.in_(ids))
    )
    out: dict[tuple[uuid.UUID, str], HomeFacts] = {}
    base: dict[uuid.UUID, tuple] = {}
    for pid, owner, sido, sgg, emd, m2, basis, occ, budget, trade, scope, grade in (
        await s.execute(q)
    ).all():
        base[pid] = (pid, owner, sido, sgg, emd, m2, basis, bool(occ), budget)
        if trade is not None:
            out[(pid, trade)] = HomeFacts(*base[pid], scope, grade)
    for pid, trade in keys:
        if (pid, trade) not in out and pid in base:
            out[(pid, trade)] = HomeFacts(*base[pid], None, None)
    return out


async def shown_review_links(s: AsyncSession, vendor_id: uuid.UUID) -> list[VendorReviewLink]:
    """고객에게 보이는 외부 리뷰 링크 (관리자가 '보여요'로 확인한 것만)"""
    q = (
        select(VendorReviewLink)
        .where(VendorReviewLink.vendor_id == vendor_id, VendorReviewLink.status == "shown")
        .order_by(VendorReviewLink.sort)
    )
    return list((await s.execute(q)).scalars().all())


async def address_sent(s: AsyncSession, project_id: uuid.UUID, vendor_id: uuid.UUID) -> bool:
    """고객이 채팅으로 동 · 호를 보냈는지 (I7 B 전날 알림 한 줄)"""
    q = select(Thread.address_sent_at).where(
        Thread.project_id == project_id, Thread.vendor_id == vendor_id
    )
    return (await s.execute(q)).scalar_one_or_none() is not None


async def noticed(s: AsyncSession, user_id: uuid.UUID, dedup_key: str) -> bool:
    """그 알림을 이미 보냈는지 (알림만 하는 기한 일이 두 번째에 False를 돌려주려고)"""
    q = select(Notification.id).where(
        Notification.user_id == user_id, Notification.dedup_key == dedup_key
    )
    return (await s.execute(q)).first() is not None


# ---- v3 2차: 요청 사진 · 업체 답 시간 · 별점 · 업체 멈춤 ----


async def photos_of(
    s: AsyncSession, visit_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[VisitPhoto]]:
    """요청마다 사진 (보낸 순)"""
    if not visit_ids:
        return {}
    q = select(VisitPhoto).where(VisitPhoto.visit_id.in_(visit_ids)).order_by(VisitPhoto.sort)
    out: dict[uuid.UUID, list[VisitPhoto]] = {}
    for x in (await s.execute(q)).scalars().all():
        out.setdefault(x.visit_id, []).append(x)
    return out


async def has_photo(s: AsyncSession, visit_id: uuid.UUID, file_id: uuid.UUID) -> bool:
    q = select(VisitPhoto.file_id).where(
        VisitPhoto.visit_id == visit_id, VisitPhoto.file_id == file_id
    )
    return (await s.execute(q)).first() is not None


async def reply_waits(s: AsyncSession, vendor_id: uuid.UUID, limit: int = 20) -> list[timedelta]:
    """그 업체가 최근 기간을 답한 요청들의 (답한 때 − 요청한 때), 최근 limit건"""
    q = (
        select(VisitWindow.answered_at, Visit.created_at)
        .join(Visit, Visit.id == VisitWindow.visit_id)
        .where(Visit.vendor_id == vendor_id)
        .order_by(VisitWindow.answered_at.desc())
        .limit(limit)
    )
    return [a - c for a, c in (await s.execute(q)).all() if a >= c]


async def ratings(
    s: AsyncSession, vendor_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[int, int, dict[str, int], int]]:
    """업체마다 (보이는 리뷰 별점 합, 리뷰 수, 칩별 수, 믿집에서 끝낸 공사 수). 숨긴 리뷰는 뺀다
    (reviews · deals 읽기 조인, review.service와 같은 규칙)."""
    if not vendor_ids:
        return {}
    shown = (Review.vendor_id.in_(vendor_ids), Review.status == "shown")
    sums = {
        vid: (int(total), int(n))
        for vid, total, n in (
            await s.execute(
                select(Review.vendor_id, func.coalesce(func.sum(Review.rating), 0), func.count())
                .where(*shown)
                .group_by(Review.vendor_id)
            )
        ).all()
    }
    tag = func.unnest(Review.tags).label("tag")
    sub = select(Review.vendor_id.label("vid"), tag).where(*shown).subquery()
    tags: dict[uuid.UUID, dict[str, int]] = {}
    for vid, name, n in (
        await s.execute(select(sub.c.vid, sub.c.tag, func.count()).group_by(sub.c.vid, sub.c.tag))
    ).all():
        tags.setdefault(vid, {})[name] = int(n)
    done = dict(
        (
            await s.execute(
                select(Deal.vendor_id, func.count())
                .where(Deal.vendor_id.in_(vendor_ids), Deal.status == "done")
                .group_by(Deal.vendor_id)
            )
        ).all()
    )
    return {
        vid: (*sums.get(vid, (0, 0)), tags.get(vid, {}), int(done.get(vid, 0)))
        for vid in vendor_ids
    }


async def remove_vendor_shortlists(
    s: AsyncSession, vendor_id: uuid.UUID, code: str, at: datetime
) -> list[tuple[uuid.UUID, str]]:
    """그 업체를 담은 살아 있는 칸을 모두 비운다 (업체 멈춤). 돌려주는 값: 비운 (공사, 공종)"""
    res = await s.execute(
        update(Shortlist)
        .where(Shortlist.vendor_id == vendor_id, Shortlist.status == "active")
        .values(status="removed", removed_code=code, removed_at=at)
        .returning(Shortlist.project_id, Shortlist.trade)
        .execution_options(synchronize_session=False)
    )
    return [tuple(r) for r in res.all()]


async def vendor_work_spans(
    s: AsyncSession, vendor_id: uuid.UUID, start: date, end: date
) -> list[tuple[date, date, list[date] | None]]:
    """업체 공사 날짜 중 start ~ end와 겹치는 것 (시작, 끝, 날 목록): 날짜를 수락한 공사(scheduled)와
    고객 답을 기다리는 공사 날짜 제안(pending, 확정 · 날짜 수락 상태 공사만). 고객 · 집 정보는 읽지 않는다."""
    accepted = select(Deal.start_date, Deal.end_date, Deal.work_days).where(
        Deal.vendor_id == vendor_id,
        Deal.status == "scheduled",
        Deal.start_date <= end,
        Deal.end_date >= start,
    )
    pending = (
        select(DateProposal.start_date, DateProposal.end_date, DateProposal.days)
        .join(Deal, Deal.id == DateProposal.deal_id)
        .where(
            Deal.vendor_id == vendor_id,
            Deal.status.in_(("confirmed", "scheduled")),
            DateProposal.status == "pending",
            DateProposal.start_date <= end,
            DateProposal.end_date >= start,
        )
    )
    rows = [*(await s.execute(accepted)).all(), *(await s.execute(pending)).all()]
    return [(first, last, list(days) if days else None) for first, last, days in rows]
