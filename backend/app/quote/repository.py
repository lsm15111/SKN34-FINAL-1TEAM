"""가견적 요청 DB 읽기 · 쓰기. commit은 service가 한다."""

import uuid
from datetime import datetime

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.quote.models import ContactRequest, ContactRequestEvent, QuoteRequest

INBOX_LIMIT = 100


async def lock(s: AsyncSession, key: str) -> None:
    """트랜잭션이 끝날 때까지 같은 key를 다른 요청이 기다리게 한다 (하루 한도를 정확히 세려고)."""
    await s.execute(text("select pg_advisory_xact_lock(hashtext(:k))"), {"k": key})


async def contacts_since(
    s: AsyncSession,
    since: datetime,
    *,
    customer_id: uuid.UUID | None = None,
    vendor_id: uuid.UUID | None = None,
) -> int:
    q = select(func.count()).select_from(ContactRequest).where(ContactRequest.created_at >= since)
    if customer_id is not None:
        q = q.where(ContactRequest.customer_id == customer_id)
    if vendor_id is not None:
        q = q.where(ContactRequest.vendor_id == vendor_id)
    return int((await s.execute(q)).scalar_one())


async def claimed_since(s: AsyncSession, vendor_id: uuid.UUID, since: datetime) -> int:
    """이 업체에 since 뒤로 보내기 시작한 대신 연락 수 (보냄 · 시험 발송 · 보내는 중 · 실패 모두)"""
    q = select(func.count()).where(
        ContactRequest.vendor_id == vendor_id, ContactRequest.claimed_at >= since
    )
    return int((await s.execute(q)).scalar_one())


async def stuck_contacts(s: AsyncSession, before: datetime, limit: int = 500) -> list[uuid.UUID]:
    """before보다 먼저 선점했는데 아직 sending인 요청"""
    q = (
        select(ContactRequest.id)
        .where(ContactRequest.status == "sending", ContactRequest.claimed_at < before)
        .order_by(ContactRequest.claimed_at, ContactRequest.id)
        .limit(limit)
    )
    return list((await s.execute(q)).scalars())


async def queued_contacts(
    s: AsyncSession, limit: int
) -> list[tuple[uuid.UUID, uuid.UUID, str, str]]:
    """(요청, 외부 업체, 수단, 글). 트랜잭션을 닫은 뒤에도 쓰도록 값으로 돌려준다."""
    q = (
        select(
            ContactRequest.id, ContactRequest.vendor_id, ContactRequest.channel, ContactRequest.body
        )
        .where(ContactRequest.status == "queued")
        .order_by(ContactRequest.created_at, ContactRequest.id)
        .limit(limit)
    )
    return [(i, v, c, b) for i, v, c, b in (await s.execute(q)).all()]


async def contact_states(
    s: AsyncSession, project_id: uuid.UUID
) -> list[tuple[uuid.UUID, str, str, str | None]]:
    """(외부 업체, 공정, 상태, 지금 상태가 된 이유). 상태마다 한 번만 들어가므로 이력 한 줄이 정해진다."""
    reason = (
        select(ContactRequestEvent.reason)
        .where(
            ContactRequestEvent.request_id == ContactRequest.id,
            ContactRequestEvent.to_status == ContactRequest.status,
        )
        .limit(1)
        .scalar_subquery()
    )
    q = select(ContactRequest.vendor_id, ContactRequest.trade, ContactRequest.status, reason).where(
        ContactRequest.project_id == project_id
    )
    return [(v, t, st, why) for v, t, st, why in (await s.execute(q)).all()]


async def move_contact(
    s: AsyncSession,
    request_id: uuid.UUID,
    *,
    to: str,
    allowed_from: tuple[str, ...],
    values: dict,
) -> bool:
    res = await s.execute(
        update(ContactRequest)
        .where(ContactRequest.id == request_id, ContactRequest.status.in_(allowed_from))
        .values(status=to, **values)
    )
    return res.rowcount == 1


async def quote_states(s: AsyncSession, project_id: uuid.UUID) -> list[tuple[uuid.UUID, str, str]]:
    """(업체, 공정, 상태)"""
    q = select(QuoteRequest.vendor_id, QuoteRequest.trade, QuoteRequest.status).where(
        QuoteRequest.project_id == project_id
    )
    return [(v, t, st) for v, t, st in (await s.execute(q)).all()]


async def inbox(s: AsyncSession, vendor_id: uuid.UUID) -> list[QuoteRequest]:
    q = (
        select(QuoteRequest)
        .where(QuoteRequest.vendor_id == vendor_id)
        .order_by(QuoteRequest.created_at.desc(), QuoteRequest.id)
        .limit(INBOX_LIMIT)
    )
    return list((await s.execute(q)).scalars())


async def quote_for_vendor(
    s: AsyncSession, request_id: uuid.UUID, vendor_id: uuid.UUID
) -> QuoteRequest | None:
    q = select(QuoteRequest).where(
        QuoteRequest.id == request_id, QuoteRequest.vendor_id == vendor_id
    )
    return (await s.execute(q)).scalar_one_or_none()


async def move_quote(
    s: AsyncSession,
    request_id: uuid.UUID,
    *,
    to: str,
    allowed_from: tuple[str, ...],
    values: dict,
) -> bool:
    """지금 상태가 allowed_from일 때만 바꾼다 (동시에 두 번 눌러도 한 번만 바뀜)."""
    res = await s.execute(
        update(QuoteRequest)
        .where(QuoteRequest.id == request_id, QuoteRequest.status.in_(allowed_from))
        .values(status=to, **values)
    )
    return res.rowcount == 1
