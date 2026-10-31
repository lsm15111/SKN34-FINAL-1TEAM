"""외부 업체 모으기 · 고르기 · 수신거부. 다른 기능은 여기 공개 함수만 부른다.

외부 호출(공공 API · 홈페이지)은 DB 트랜잭션을 열기 전에 끝낸다. 받다가 하나라도 실패하면 아무것도 바꾸지 않는다.
"""

import asyncio
from datetime import datetime
from pathlib import Path

import httpx2
from sqlalchemy.ext.asyncio import AsyncSession

from app.directory import client
from app.directory import repository as repo
from app.directory.sources import kiscon_events, kiscon_row, read_sangga_csv, replay


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
