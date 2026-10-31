import uuid
from datetime import datetime

from sqlalchemy import delete, func, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert
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


async def approved_serving(
    s: AsyncSession, trades: list[str], sido: str, sgg: str
) -> list[tuple[Vendor, list[str]]]:
    """승인된 업체 중 그 공정을 하고 그 시 · 군 · 구를 맡는 곳 (맞는 공정 목록과 함께)"""
    q = (
        select(Vendor, func.array_agg(VendorTrade.trade.distinct()))
        .join(User, User.id == Vendor.user_id)
        .join(VendorTrade, VendorTrade.vendor_id == Vendor.user_id)
        .join(VendorArea, VendorArea.vendor_id == Vendor.user_id)
        .where(
            Vendor.status == "approved",
            User.status == "active",
            VendorTrade.trade.in_(trades),
            VendorArea.sido == sido,
            VendorArea.sgg == sgg,
        )
        .group_by(Vendor.user_id)
        .order_by(Vendor.reviewed_at, Vendor.user_id)
    )
    return [(v, sorted(ts)) for v, ts in (await s.execute(q)).all()]


async def get(s: AsyncSession, vendor_id: uuid.UUID) -> Vendor | None:
    return (await s.execute(select(Vendor).where(Vendor.user_id == vendor_id))).scalar_one_or_none()


async def update_profile(
    s: AsyncSession,
    vendor_id: uuid.UUID,
    *,
    biz_name: str,
    site_url: str | None,
    portfolio_urls: list[str],
) -> bool:
    """승인된 업체일 때만 바꾼다. 바꾼 행은 트랜잭션이 끝날 때까지 잠겨, 같은 업체의 저장은 줄을 선다."""
    res = await s.execute(
        update(Vendor)
        .where(Vendor.user_id == vendor_id, Vendor.status == "approved")
        .values(biz_name=biz_name, site_url=site_url, portfolio_urls=portfolio_urls)
    )
    return res.rowcount == 1


async def set_trades(s: AsyncSession, vendor_id: uuid.UUID, trades: list[str]) -> None:
    """빠진 공정만 지우고 새 공정만 더한다 (이미 있으면 그대로)."""
    await s.execute(
        delete(VendorTrade).where(
            VendorTrade.vendor_id == vendor_id, VendorTrade.trade.not_in(trades)
        )
    )
    if trades:
        rows = [{"vendor_id": vendor_id, "trade": t} for t in trades]
        await s.execute(insert(VendorTrade).values(rows).on_conflict_do_nothing())


async def set_areas(s: AsyncSession, vendor_id: uuid.UUID, areas: list[tuple[str, str]]) -> None:
    """빠진 지역만 지우고 새 지역만 더한다 (이미 있으면 그대로)."""
    await s.execute(
        delete(VendorArea).where(
            VendorArea.vendor_id == vendor_id,
            tuple_(VendorArea.sido, VendorArea.sgg).not_in(areas),
        )
    )
    if areas:
        rows = [{"vendor_id": vendor_id, "sido": a, "sgg": b} for a, b in areas]
        await s.execute(insert(VendorArea).values(rows).on_conflict_do_nothing())


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
