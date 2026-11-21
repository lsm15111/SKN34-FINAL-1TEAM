"""한 공사 기록 탭(C63 · I2) · 업체 공사 한 건 기록(V23) · 확정 공정표 캘린더 파일(I1 · C36).

- 기록: 실측 요청 이력(visit_events) + 실측 견적서 보냄(금액) + 업체 확정 이력(deal_events) + 공사 날짜
  (업체가 냄 · 고객이 다른 날짜 요청) + 추가 금액(올림 · 고침 · 답)을 시간 순으로. 글은 화면이 code ·
  날 · 반나절로 만든다. 고객과 업체가 같은 기록을 보되, 업체 쪽은 그 업체 요청 · 확정만 보인다.
- 읽기만 한다. 권한은 부르는 쪽(service)이 먼저 확인한다. 고객 이름 · 연락처는 넣지 않는다.
"""

import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.quote.models import VendorQuote
from app.schedule.models import DateProposal, DateRequest, Deal, DealEvent, ExtraCharge
from app.schedule.schemas import LogItemOut
from app.visit.models import Visit, VisitEvent, VisitProposal, VisitProposalSlot

# 이력 코드가 비어 있는 옛 행: 바뀐 상태로 코드를 정한다 (data-model 3장 visit_events.code)
VISIT_CODE = {
    "requested": "asked",
    "offered": "answered",
    "picked": "picked",
    "proposed": "proposed",
    "booked": "booked",
    "visited": "visited",
    "no_show": "no_show",
    "declined": "declined",
    "expired": "expired",
    "cancelled": "cancelled",
    "closed": "closed",
    "chosen": "chosen",
}
DEAL_CODE = {
    "confirmed": "confirmed",
    "checking": "done_posted",
    "done": "checked",
    "fixing": "fixing",
    "reselected": "reselected",
}


def _actor(by_id: uuid.UUID | None, owner_id: uuid.UUID | None, vendor_id: uuid.UUID | None):
    if by_id is not None and by_id == owner_id:
        return "customer"
    if by_id is not None and by_id == vendor_id:
        return "vendor"
    return "mijip"  # 기한 일 · 자동 끝 · 관리자


def _item(
    at,
    actor,
    name,
    trade,
    code,
    day=None,
    half=None,
    day_to=None,
    amount=None,
    half_to=None,
    days=(),
):
    two = half_to is not None  # 반나절 둘: 같은 날 오전 · 오후여도 둘째 칸을 남긴다
    return LogItemOut(
        at=at,
        actor=actor,
        vendor_name=name,
        trade=trade,
        code=code,
        day=day,
        half=half,
        day_to=day_to if day_to is not None and (two or day_to != day) else None,
        amount=amount,
        half_to=half_to if two else None,
        days=list(days),
    )


SLOT_CODES = ("proposed", "change_countered")  # 업체가 반나절 1~3개를 낸 기록 (visit_proposals)


async def _proposal_slots(
    s: AsyncSession, visit_ids: list[uuid.UUID]
) -> dict[tuple[uuid.UUID, str], list[list[tuple[date, str]]]]:
    """(요청, 기록 코드)마다 낸 순서대로 제안 반나절 목록. 다른 날 제안(proposed) · 바꾸기 요청에 낸
    다른 날(change_countered)을 나눈다. 기록 줄에는 앞 두 칸을 그린다('12.16 오후 · 12.17 오전')."""
    rows = (
        await s.execute(
            select(VisitProposal.id, VisitProposal.visit_id, VisitProposal.change_id)
            .where(VisitProposal.visit_id.in_(visit_ids))
            .order_by(VisitProposal.created_at, VisitProposal.id)
        )
    ).all()
    if not rows:
        return {}
    slots: dict[uuid.UUID, list[tuple[date, str]]] = {}
    q = select(VisitProposalSlot).where(VisitProposalSlot.proposal_id.in_([r.id for r in rows]))
    for x in await _all(s, q):
        slots.setdefault(x.proposal_id, []).append((x.day, x.half))
    out: dict[tuple[uuid.UUID, str], list[list[tuple[date, str]]]] = {}
    for r in rows:
        code = "change_countered" if r.change_id is not None else "proposed"
        got = sorted(slots.get(r.id, []), key=lambda x: (x[0], x[1] == "pm"))
        out.setdefault((r.visit_id, code), []).append(got)
    return out


async def _all(s: AsyncSession, q) -> list:
    return list((await s.execute(q)).scalars())


def _deal_code(ev: DealEvent) -> str:
    if ev.code is not None:
        return ev.code
    if ev.to_status == "scheduled":
        return "dates_accepted" if ev.from_status == "confirmed" else "dates_changed"
    return DEAL_CODE.get(ev.to_status, ev.to_status)


async def items(
    s: AsyncSession,
    *,
    owner_id: uuid.UUID | None,
    visit_ids: list[uuid.UUID],
    deal_ids: list[uuid.UUID],
) -> list[LogItemOut]:
    """요청 · 확정 기록을 시간 순으로 (같은 때면 들어온 순). 업체 확정은 한 사건이라 한 줄이다: 확정 이력
    (deal_events confirmed)이 있는 요청의 '골랐어요'(visit_events chosen)는 남기지 않는다."""
    out: list[LogItemOut] = []
    deals: dict[uuid.UUID, Deal] = {}
    deal_events: list[DealEvent] = []
    if deal_ids:
        deals = {d.id: d for d in await _all(s, select(Deal).where(Deal.id.in_(deal_ids)))}
    if deals:
        deal_events = await _all(s, select(DealEvent).where(DealEvent.deal_id.in_(list(deals))))
    confirmed = {deals[ev.deal_id].visit_id for ev in deal_events if _deal_code(ev) == "confirmed"}
    visits: dict[uuid.UUID, Visit] = {}
    if visit_ids:
        visits = {v.id: v for v in await _all(s, select(Visit).where(Visit.id.in_(visit_ids)))}
    if visits:
        offered = await _proposal_slots(s, list(visits))
        events = select(VisitEvent).where(VisitEvent.visit_id.in_(list(visits)))
        for ev in await _all(s, events.order_by(VisitEvent.at, VisitEvent.id)):
            if ev.to_status == "quoted":  # 견적서 보냄은 아래 견적서 버전(금액)으로 남긴다
                continue
            v = visits[ev.visit_id]
            code = ev.code or VISIT_CODE.get(ev.to_status, ev.to_status)
            if code == "chosen" and v.id in confirmed:  # 업체 확정 한 줄(deal_events)로 남긴다
                continue
            if ev.from_status is None and ev.code is None and v.attempt > 1:
                code = "re_asked"
            day, half, day_to, half_to = ev.day, ev.half, ev.day_to, None
            queue = offered.get((ev.visit_id, code)) if code in SLOT_CODES else None
            if queue:  # 같은 요청의 제안을 낸 순서대로 짝짓는다
                got = queue.pop(0)
                if got:
                    day, half = got[0]
                if len(got) > 1:
                    day_to, half_to = got[1]
            out.append(
                _item(
                    ev.at,
                    _actor(ev.by_id, owner_id, v.vendor_id),
                    v.vendor_name,
                    v.trade,
                    code,
                    day,
                    half,
                    day_to,
                    half_to=half_to,
                )
            )
        sent = select(VendorQuote).where(
            VendorQuote.visit_id.in_(list(visits)), VendorQuote.sent_at.is_not(None)
        )
        for q in await _all(s, sent):
            v = visits[q.visit_id]
            code = "quote_resent" if q.version > 1 else "quote_sent"
            out.append(_item(q.sent_at, "vendor", v.vendor_name, v.trade, code, amount=q.total))
    if deals:
        ids = list(deals)
        for ev in deal_events:
            d = deals[ev.deal_id]
            out.append(
                _item(
                    ev.at,
                    _actor(ev.by_id, owner_id, d.vendor_id),
                    d.vendor_name,
                    d.trade,
                    _deal_code(ev),
                )
            )
        for x in await _all(s, select(DateProposal).where(DateProposal.deal_id.in_(ids))):
            d = deals[x.deal_id]
            first, last = (x.days[0], x.days[-1]) if x.days else (x.start_date, x.end_date)
            out.append(
                _item(
                    x.created_at,
                    _actor(x.by_id, owner_id, d.vendor_id),
                    d.vendor_name,
                    d.trade,
                    "dates_sent",
                    first,
                    None,
                    last,
                    days=sorted(x.days or []),  # 하나씩 고른 공사 날 (옛 범위 길은 비어 있다)
                )
            )
        for r in await _all(s, select(DateRequest).where(DateRequest.deal_id.in_(ids))):
            d = deals[r.deal_id]
            wish = sorted(r.wish_dates)
            out.append(
                _item(
                    r.created_at,
                    _actor(r.by_id, owner_id, d.vendor_id),
                    d.vendor_name,
                    d.trade,
                    "date_requested",
                    wish[0],
                    None,
                    wish[-1],
                    days=wish,
                )
            )
        for x in await _all(s, select(ExtraCharge).where(ExtraCharge.deal_id.in_(ids))):
            d = deals[x.deal_id]
            code = "extra_revised" if x.version > 1 else "extra_sent"
            out.append(
                _item(
                    x.created_at,
                    _actor(x.by_id, owner_id, d.vendor_id),
                    d.vendor_name,
                    d.trade,
                    code,
                    amount=x.total,
                )
            )
            if x.acked_at is not None:
                out.append(
                    _item(
                        x.acked_at,
                        "customer",
                        d.vendor_name,
                        d.trade,
                        f"extra_{x.ack}",
                        amount=x.total,
                    )
                )
    out.sort(key=lambda i: i.at)  # 파이썬 정렬은 같은 때 들어온 순을 지킨다
    return out


# ---- 캘린더 파일 (.ics, RFC 5545). 주소 · 연락처 없이 공정 · 업체 이름만 ----


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> str:
    """한 줄 75바이트로 접는다 (UTF-8 글자를 가르지 않는다)"""
    out, cur, size = [], "", 0
    for ch in line:
        n = len(ch.encode("utf-8"))
        if size + n > 75:
            out.append(cur)
            cur, size = " ", 1
        cur += ch
        size += n
    out.append(cur)
    return "\r\n".join(out)


def calendar(name: str, events: list[tuple[str, date, str]], now: datetime) -> str:
    """하루짜리 일정들 (uid, 날, 제목) → .ics 본문"""
    stamp = f"{now.astimezone(UTC):%Y%m%dT%H%M%SZ}"
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//mitjip//plan//KO",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape(name)}",
    ]
    for uid, day, title in events:
        lines += [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{day:%Y%m%d}",
            f"DTEND;VALUE=DATE:{day + timedelta(days=1):%Y%m%d}",
            f"SUMMARY:{_escape(title)}",
            "TRANSP:OPAQUE",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(x) for x in lines) + "\r\n"
