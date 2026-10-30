import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.vendor.models import Vendor, VendorArea, VendorTrade


async def review_of(s: AsyncSession, user_id: uuid.UUID) -> tuple[str, str | None] | None:
    """(승인 상태, 반려 사유)"""
    row = (
        await s.execute(
            select(Vendor.status, Vendor.reject_reason).where(Vendor.user_id == user_id)
        )
    ).first()
    return (row[0], row[1]) if row else None


async def list_with_users(s: AsyncSession, status: str | None) -> list[tuple[Vendor, User]]:
    q = (
        select(Vendor, User)
        .join(User, User.id == Vendor.user_id)
        .order_by(Vendor.created_at.desc())
    )
    if status:
        q = q.where(Vendor.status == status)
    return [(v, u) for v, u in (await s.execute(q)).all()]


async def get_with_user(s: AsyncSession, vendor_id: uuid.UUID) -> tuple[Vendor, User] | None:
    row = (
        await s.execute(
            select(Vendor, User)
            .join(User, User.id == Vendor.user_id)
            .where(Vendor.user_id == vendor_id)
        )
    ).first()
    return (row[0], row[1]) if row else None


async def trades_and_areas(s: AsyncSession, ids: list[uuid.UUID]) -> tuple[dict, dict]:
    trades: dict[uuid.UUID, list[str]] = {i: [] for i in ids}
    areas: dict[uuid.UUID, list[tuple[str, str]]] = {i: [] for i in ids}
    for vid, t in (
        await s.execute(
            select(VendorTrade.vendor_id, VendorTrade.trade).where(VendorTrade.vendor_id.in_(ids))
        )
    ).all():
        trades[vid].append(t)
    q = select(VendorArea.vendor_id, VendorArea.sido, VendorArea.sgg).where(
        VendorArea.vendor_id.in_(ids)
    )
    for vid, sido, sgg in (await s.execute(q)).all():
        areas[vid].append((sido, sgg))
    return trades, areas


async def set_status(
    s: AsyncSession,
    vendor_id: uuid.UUID,
    *,
    to: str,
    allowed_from: tuple[str, ...],
    reason: str | None,
    by: uuid.UUID,
    at: datetime,
) -> bool:
    """지금 상태가 allowed_from일 때만 바꾼다 (동시에 두 관리자가 눌러도 한 번만 바뀜)."""
    res = await s.execute(
        update(Vendor)
        .where(Vendor.user_id == vendor_id, Vendor.status.in_(allowed_from))
        .values(status=to, reject_reason=reason, reviewed_by=by, reviewed_at=at)
    )
    return res.rowcount == 1
