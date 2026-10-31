"""외부 업체 모으기 · 고르기 · 수신거부. 다른 기능은 여기 공개 함수만 부른다.

외부 호출(공공 API · 홈페이지)은 DB 트랜잭션을 열기 전에 끝낸다. 받다가 하나라도 실패하면 아무것도 바꾸지 않는다.
"""

import asyncio
import re
import uuid
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import httpx2
from sqlalchemy.ext.asyncio import AsyncSession

from app.directory import client
from app.directory import repository as repo
from app.directory.models import ExtVendor
from app.directory.site import SiteChecker
from app.directory.sources import (
    kakao_place_id,
    kiscon_events,
    kiscon_row,
    read_sangga_csv,
    replay,
)
from app.shared.errors import AppError

RECHECK = timedelta(days=30)  # 국세청 상태 · 홈페이지 · 카카오 장소를 다시 보는 간격
PLACE_URL = "https://place.map.kakao.com/{}"
SOURCE_LABEL = {
    "sangga": "소상공인 상가정보",
    "kiscon": "건설산업지식정보시스템(KISCON) 공시",
    "seed": "개발용 가짜 데이터",
}


@dataclass(frozen=True)
class ExtCard:
    """후보로 보여 줄 외부 업체. 연락처 값은 넣지 않고 동의한 연락 수단 이름만 둔다."""

    id: uuid.UUID
    name: str
    source: str
    trades: list[str]
    industries: list[str]
    sido: str | None
    sgg: str | None
    reg_kind: str | None
    biz_status: str | None
    phone: str | None
    homepage: str | None
    portfolio_urls: list[str]
    quote_url: str | None
    place_url: str | None
    visit_fee: int | None
    fetched_at: datetime
    channels: list[str]
    opted_out: bool


CHANNEL_ORDER = ("sms", "email", "form")  # 대신 연락할 때 고르는 순서


@dataclass(frozen=True)
class Target:
    """대신 연락을 보낼 곳. 보내기 직전에만 만든다."""

    channel: str
    value: str
    optout_token: str


def _card(r: ExtVendor, trades: Sequence[str] | None, channels: list[str]) -> ExtCard:
    return ExtCard(
        id=r.id,
        name=r.name,
        source=r.source,
        trades=[t for t in r.trades if trades is None or t in trades],
        industries=list(r.industries),
        sido=r.sido,
        sgg=r.sgg,
        reg_kind=r.reg_kind,
        biz_status=r.biz_status,
        phone=r.phone,
        homepage=r.homepage,
        portfolio_urls=list(r.portfolio_urls),
        quote_url=r.quote_url,
        place_url=PLACE_URL.format(r.place_ref) if r.place_ref else None,
        visit_fee=r.visit_fee,
        fetched_at=r.fetched_at,
        channels=channels,
        opted_out=r.opted_out,
    )


async def candidates(
    s: AsyncSession, trades: Sequence[str], sido: str, sgg: str, *, limit: int = 12
) -> list[ExtCard]:
    """프로젝트 공정 · 지역에 맞는 외부 업체. 같은 이름이 같은 시 · 군 · 구에 두 번 있으면(출처가 달라) 하나만."""
    rows = await repo.candidates(s, trades, sido, sgg, limit * 2)
    channels = await repo.channels_of(s, [r.id for r in rows])
    out: list[ExtCard] = []
    seen: set[tuple[str, str | None]] = set()
    for r in rows:
        key = (re.sub(r"\W", "", r.name), r.sgg)
        if key not in seen:
            seen.add(key)
            out.append(_card(r, trades, channels.get(r.id, [])))
    return out[:limit]


async def card(s: AsyncSession, vendor_id: uuid.UUID) -> ExtCard | None:
    r = await repo.get(s, vendor_id)
    if r is None:
        return None
    return _card(r, None, (await repo.channels_of(s, [r.id])).get(r.id, []))


def best_channel(channels: Sequence[str]) -> str | None:
    return next((c for c in CHANNEL_ORDER if c in channels), None)


async def contact_target(s: AsyncSession, vendor_id: uuid.UUID, channel: str) -> Target | str:
    """보내기 직전에 다시 본다: 그 수단에 아직 동의가 있는지. 못 보내면 이유('opted_out' · 'no_contact')."""
    r = await repo.get(s, vendor_id)
    if r is None or r.opted_out:
        return "opted_out"
    got = dict(await repo.contacts_of(s, vendor_id))
    if channel not in got:
        return "no_contact"
    return Target(channel=channel, value=got[channel], optout_token=r.optout_token)


async def opt_out(s: AsyncSession, token: str, *, now: datetime) -> None:
    """수신거부 링크. 업체를 목록에서 빼고 동의 연락처를 지운다. 다시 모아도 수신거부로 남는다."""
    r = await repo.by_token(s, token)
    if r is None:
        raise AppError(404, "not_found", "수신거부 링크가 올바르지 않아요.")
    contacts = await repo.contacts_of(s, r.id)
    await repo.add_optouts(
        s,
        repo.identity_hashes(r.source, r.source_id, r.reg_no, contacts),
        vendor_id=r.id,
        via="link",
    )
    await repo.opt_out(s, r.id, now=now)
    await s.commit()


async def import_sangga_csv(s: AsyncSession, path: Path, *, now: datetime) -> dict[str, int]:
    """상가정보 CSV 한 파일을 읽어 인테리어 관련 업종만 넣거나 고친다."""
    total, rows = await asyncio.to_thread(read_sangga_csv, path)  # 큰 파일 읽기는 작업 스레드에서
    saved = await repo.upsert(s, rows, now=now)
    await s.commit()
    return {"read": total, "matched": len(rows), "saved": saved}


async def sync_kiscon(
    s: AsyncSession, http: httpx2.AsyncClient, key: str, start: str, end: str, *, now: datetime
) -> dict[str, int]:
    """공시 기간의 KISCON 이벤트를 받아 지금 등록 상태로 맞춘다. 업종이 모두 빠진 업체는 지운다."""
    items = await client.kiscon_items(http, key, start, end)  # 다 받은 뒤에만 DB를 연다
    events = list(kiscon_events(items))
    touched = sorted({e.reg_no for e in events})
    before = await repo.kiscon_holdings(s, touched)
    after = replay(before, events)
    rows = [kiscon_row(no, after[no]) for no in touched if no in after]
    gone = [no for no in touched if no in before and no not in after]
    saved = await repo.upsert(s, rows, now=now)
    removed = await repo.delete_by_source(s, "kiscon", gone)
    await s.commit()
    return {"items": len(items), "events": len(events), "saved": saved, "removed": removed}


async def verify_biz(
    s: AsyncSession, http: httpx2.AsyncClient, key: str, *, now: datetime, limit: int = 1000
) -> dict[str, int]:
    """국세청에 사업자 상태(계속 · 휴업 · 폐업)만 물어 본다. 명단을 만들지 않고 이미 있는 번호만 확인한다."""
    numbers = await repo.biz_nos_due(s, now - RECHECK, limit)
    await s.rollback()  # 읽기 트랜잭션을 닫고 HTTP 동안 DB 연결을 붙잡지 않는다
    statuses: dict[str, str] = {}
    for i in range(0, len(numbers), client.NTS_BATCH):
        statuses |= await client.nts_status(http, key, numbers[i : i + client.NTS_BATCH])
    changed = await repo.set_biz_status(s, statuses, now=now)
    await s.commit()
    return {"asked": len(numbers), "answered": len(statuses), "changed": changed}


async def match_places(
    s: AsyncSession, http: httpx2.AsyncClient, key: str, *, now: datetime, limit: int = 200
) -> dict[str, int]:
    """카카오 장소 검색에서 이름 · 시 · 군 · 구가 같은 장소 하나를 찾으면 그 ID만 남긴다 (화면의 카카오맵 링크)."""
    targets = await repo.places_due(s, now - RECHECK, limit)
    await s.rollback()  # 검색하는 동안 DB 연결을 붙잡지 않는다
    found: dict[uuid.UUID, str | None] = {}
    for vendor_id, name, sido, sgg, lat, lng in targets:
        # 좌표가 있으면 그 둘레에서 이름으로, 없으면 시 · 군 · 구를 붙여 찾는다
        q = name if lat is not None else f"{sgg} {name}"
        docs = await client.kakao_places(http, key, q, x=lng, y=lat)
        found[vendor_id] = kakao_place_id(name, sido, sgg, docs)
    saved = await repo.save_places(s, found, now=now)
    await s.commit()
    return {
        "asked": len(targets),
        "matched": sum(v is not None for v in found.values()),
        "saved": saved,
    }


async def check_homepages(
    s: AsyncSession, site: SiteChecker, *, now: datetime, limit: int = 50
) -> dict[str, int]:
    """홈페이지 한 장씩 읽어 포트폴리오 · 견적 링크만 남긴다. 업체마다 따로 저장한다(중간에 멈춰도 앞의 것은 남게)."""
    targets = await repo.homepages_due(s, now - RECHECK, limit)
    await s.rollback()
    seen: Counter[str] = Counter()
    for vendor_id, homepage in targets:
        got = await site.check(homepage)  # DB 트랜잭션 밖에서
        seen[got.status] += 1
        await repo.save_links(
            s,
            vendor_id,
            now=now,
            portfolio_urls=got.portfolio_urls if got.status == "ok" else None,
            quote_url=got.quote_url,
        )
        await s.commit()
    return dict(seen)
