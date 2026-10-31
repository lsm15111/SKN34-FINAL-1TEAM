"""외부 업체 DB 읽기 · 쓰기. commit은 service가 한다."""

import hashlib
import secrets
import uuid
from collections.abc import Iterable, Sequence
from datetime import datetime

from sqlalchemy import ARRAY, String, case, cast, delete, exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.directory.models import ContactOptout, ExtVendor, ExtVendorContact
from app.directory.sources import Holding, VendorRow
from app.shared.ids import uuid7

BATCH = 500  # 한 INSERT에 넣는 행 수 (인자 수 한도 안쪽)
# 출처가 다시 채우는 칸. 홈페이지 링크 · 국세청 상태 · 장소 ID · 출장비 · 수신거부는 다시 모아도 그대로 둔다
SOURCE_COLS = (
    "name",
    "trades",
    "industries",
    "sido",
    "sgg",
    "address",
    "lat",
    "lng",
    "reg_kind",
    "reg_no",
    "phone",
)


def key_hash(kind: str, value: str) -> str:
    return hashlib.sha256(f"{kind}:{value}".encode()).hexdigest()


def identity_hashes(
    source: str, source_id: str, reg_no: str | None, contacts: Iterable[tuple[str, str]] = ()
) -> list[str]:
    """수신거부를 알아볼 열쇠: 출처 번호 · 사업자번호 · 동의한 연락처. 원문 대신 해시만 둔다."""
    keys = [key_hash("src", f"{source}:{source_id}")]
    if reg_no:
        keys.append(key_hash("biz", reg_no))
    keys += [key_hash(channel, value) for channel, value in contacts]
    return keys


def new_token() -> str:
    return secrets.token_urlsafe(32)


def _chunks[T](items: Sequence[T], size: int = 1000) -> Iterable[Sequence[T]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


async def opted_out_hashes(s: AsyncSession, hashes: Sequence[str]) -> set[str]:
    found: set[str] = set()
    for part in _chunks(list(hashes)):
        q = select(ContactOptout.key_hash).where(ContactOptout.key_hash.in_(part))
        found |= set((await s.execute(q)).scalars())
    return found


async def upsert(s: AsyncSession, rows: Sequence[VendorRow], *, now: datetime) -> int:
    """출처 번호가 같으면 출처 칸만 고친다. 수신거부 목록에 걸리는 업체는 처음부터 수신거부로 둔다."""
    saved = 0
    for part in _chunks(rows, BATCH):
        latest = {(r.source, r.source_id): r for r in part}  # 같은 묶음에 두 번 있으면 뒤의 것
        keys = {k: identity_hashes(r.source, r.source_id, r.reg_no) for k, r in latest.items()}
        blocked = await opted_out_hashes(s, [h for hs in keys.values() for h in hs])
        values = [
            {
                "id": uuid7(),
                "source": r.source,
                "source_id": r.source_id,
                **{c: getattr(r, c) for c in SOURCE_COLS},
                "fetched_at": now,
                "updated_at": now,
                "optout_token": new_token(),
                "opted_out": any(h in blocked for h in keys[k]),
            }
            for k, r in latest.items()
        ]
        stmt = insert(ExtVendor).values(values)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_ext_vendors_source_ref",
            set_={c: stmt.excluded[c] for c in SOURCE_COLS}
            | {
                "fetched_at": stmt.excluded.fetched_at,
                "updated_at": stmt.excluded.updated_at,
                "opted_out": or_(ExtVendor.opted_out, stmt.excluded.opted_out),
            },
        )
        await s.execute(stmt)
        saved += len(values)
    return saved


async def delete_by_source(s: AsyncSession, source: str, source_ids: Sequence[str]) -> int:
    removed = 0
    for part in _chunks(list(source_ids)):
        res = await s.execute(
            delete(ExtVendor).where(ExtVendor.source == source, ExtVendor.source_id.in_(part))
        )
        removed += res.rowcount
    return removed


async def candidates(
    s: AsyncSession, trades: Sequence[str], sido: str, sgg: str, limit: int
) -> list[ExtVendor]:
    """같은 시 · 도에서 공정이 겹치는 업체. 같은 시 · 군 · 구, 동의한 연락처, 견적 창구, 포트폴리오,
    건설업 등록 순으로 앞에 둔다. 수신거부와 휴업 · 폐업 업체는 뺀다."""
    consented = exists().where(ExtVendorContact.vendor_id == ExtVendor.id)
    q = (
        select(ExtVendor)
        .where(
            ExtVendor.opted_out.is_(False),
            ExtVendor.sido == sido,
            ExtVendor.trades.op("&&")(cast(list(trades), ARRAY(String(10)))),
            or_(ExtVendor.biz_status.is_(None), ExtVendor.biz_status.in_(("active", "unknown"))),
        )
        .order_by(
            case((ExtVendor.sgg == sgg, 0), else_=1),
            case((consented, 0), else_=1),
            case((ExtVendor.quote_url.is_not(None), 0), else_=1),
            case((func.cardinality(ExtVendor.portfolio_urls) > 0, 0), else_=1),
            case((ExtVendor.reg_kind == "construction", 0), else_=1),
            ExtVendor.name,
            ExtVendor.id,
        )
        .limit(limit)
    )
    return list((await s.execute(q)).scalars())


async def channels_of(s: AsyncSession, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, list[str]]:
    """업체가 동의한 연락 수단 이름만 (값은 읽지 않는다)"""
    out: dict[uuid.UUID, set[str]] = {}
    for part in _chunks(list(ids)):
        q = select(ExtVendorContact.vendor_id, ExtVendorContact.channel).where(
            ExtVendorContact.vendor_id.in_(part)
        )
        for vid, channel in (await s.execute(q)).all():
            out.setdefault(vid, set()).add(channel)
    return {k: sorted(v) for k, v in out.items()}


async def get(s: AsyncSession, vendor_id: uuid.UUID) -> ExtVendor | None:
    return await s.get(ExtVendor, vendor_id)


async def by_token(s: AsyncSession, token: str) -> ExtVendor | None:
    q = select(ExtVendor).where(ExtVendor.optout_token == token)
    return (await s.execute(q)).scalar_one_or_none()


async def contacts_of(s: AsyncSession, vendor_id: uuid.UUID) -> list[tuple[str, str]]:
    """(수단, 값). 보내기 직전과 수신거부 때만 읽는다."""
    q = (
        select(ExtVendorContact.channel, ExtVendorContact.value)
        .where(ExtVendorContact.vendor_id == vendor_id)
        .order_by(ExtVendorContact.consented_at)
    )
    return [(c, v) for c, v in (await s.execute(q)).all()]


async def add_optouts(
    s: AsyncSession, hashes: Sequence[str], *, vendor_id: uuid.UUID, via: str
) -> None:
    rows = [{"key_hash": h, "vendor_id": vendor_id, "via": via} for h in hashes]
    await s.execute(insert(ContactOptout).values(rows).on_conflict_do_nothing())


async def opt_out(s: AsyncSession, vendor_id: uuid.UUID, *, now: datetime) -> None:
    """수신거부로 표시하고 동의 연락처는 지운다 (동의를 거둔 것으로 본다)."""
    await s.execute(delete(ExtVendorContact).where(ExtVendorContact.vendor_id == vendor_id))
    await s.execute(
        update(ExtVendor).where(ExtVendor.id == vendor_id).values(opted_out=True, updated_at=now)
    )


async def biz_nos_due(s: AsyncSession, before: datetime, limit: int) -> list[str]:
    """국세청 상태를 확인할 사업자번호: 아직 안 봤거나 before보다 오래전에 본 것"""
    q = (
        select(ExtVendor.reg_no)
        .where(
            ExtVendor.reg_no.is_not(None),
            or_(ExtVendor.biz_checked_at.is_(None), ExtVendor.biz_checked_at < before),
        )
        .group_by(ExtVendor.reg_no)
        .order_by(func.min(ExtVendor.biz_checked_at).nulls_first())
        .limit(limit)
    )
    return list((await s.execute(q)).scalars())


async def set_biz_status(s: AsyncSession, statuses: dict[str, str], *, now: datetime) -> int:
    changed = 0
    for no, status in statuses.items():
        res = await s.execute(
            update(ExtVendor)
            .where(ExtVendor.reg_no == no)
            .values(biz_status=status, biz_checked_at=now, updated_at=now)
        )
        changed += res.rowcount
    return changed


async def homepages_due(
    s: AsyncSession, before: datetime, limit: int
) -> list[tuple[uuid.UUID, str]]:
    """홈페이지를 확인할 업체: 수신거부가 아니고, 아직 안 봤거나 before보다 오래전에 본 것"""
    q = (
        select(ExtVendor.id, ExtVendor.homepage)
        .where(
            ExtVendor.homepage.is_not(None),
            ExtVendor.opted_out.is_(False),
            or_(ExtVendor.site_checked_at.is_(None), ExtVendor.site_checked_at < before),
        )
        .order_by(ExtVendor.site_checked_at.nulls_first(), ExtVendor.id)
        .limit(limit)
    )
    return [(i, h) for i, h in (await s.execute(q)).all()]


async def save_links(
    s: AsyncSession,
    vendor_id: uuid.UUID,
    *,
    now: datetime,
    portfolio_urls: list[str] | None,
    quote_url: str | None,
) -> None:
    """확인한 때를 남긴다. 링크를 찾았으면(portfolio_urls가 None이 아니면) 링크도 바꾼다."""
    values: dict = {"site_checked_at": now, "updated_at": now}
    if portfolio_urls is not None:
        values |= {"portfolio_urls": portfolio_urls, "quote_url": quote_url}
    await s.execute(update(ExtVendor).where(ExtVendor.id == vendor_id).values(**values))


async def kiscon_holdings(s: AsyncSession, reg_nos: Sequence[str]) -> dict[str, Holding]:
    """KISCON에서 온 업체의 지금 등록 업종 (이벤트를 이어서 돌릴 출발점)"""
    out: dict[str, Holding] = {}
    for part in _chunks(list(reg_nos)):
        q = select(
            ExtVendor.source_id,
            ExtVendor.name,
            ExtVendor.industries,
            ExtVendor.address,
            ExtVendor.phone,
        ).where(ExtVendor.source == "kiscon", ExtVendor.source_id.in_(part))
        for sid, name, items, address, phone in (await s.execute(q)).all():
            out[sid] = Holding(name=name, items=frozenset(items), address=address, phone=phone)
    return out
