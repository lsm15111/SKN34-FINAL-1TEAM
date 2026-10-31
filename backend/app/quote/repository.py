"""가견적 요청 DB 읽기 · 쓰기. commit은 service가 한다."""

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.quote.models import QuoteRequest

INBOX_LIMIT = 100


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
