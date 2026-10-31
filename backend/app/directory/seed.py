"""로컬 개발용 가짜 외부 업체를 넣는다. APP_ENV=local에서만 돈다.

이름 · 번호는 가짜임이 드러나게 쓴다: 상호 '가짜인테리어 N', 사업자번호 000000000N(실제로 없는 번호),
사무실 번호 02-0000-000N, 문자 번호 010-0000-000N, 홈페이지 example.com(문서용 예약 도메인).
받는 길마다 한 곳씩 보이게 만든다: 대신 요청(동의 연락처) · 견적 창구 링크 · 전화 · 정보만.
이미 있으면 고쳐 쓴다(출처 번호 기준). 실행: docker compose exec api python -m app.directory.seed
"""

import asyncio
import sys
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import SessionLocal, engine
from app.directory import repository as repo
from app.directory.models import ExtVendor, ExtVendorContact
from app.directory.sources import VendorRow
from app.shared.clock import now_utc

SITE = "https://example.com/fake-{}"

# (번호, 시 · 도, 시 · 군 · 구, 공정, 따로 채울 칸, 동의 연락처)
FAKES: list[tuple[int, str, str, list[str], dict, str | None]] = [
    (1, "seoul", "마포구", ["dobae", "mokgong"], {"visit_fee": 0}, "01000000001"),
    (
        2,
        "seoul",
        "마포구",
        ["dobae"],
        {
            "homepage": SITE.format(2),
            "quote_url": SITE.format(2) + "/estimate",
            "portfolio_urls": [SITE.format(2) + "/portfolio"],
        },
        None,
    ),
    (3, "seoul", "마포구", ["mokgong"], {"visit_fee": 50000}, None),
    (4, "seoul", "서대문구", ["dobae", "mokgong"], {}, None),
    (5, "gyeonggi", "수원시", ["dobae", "floor"], {"homepage": SITE.format(5)}, None),
]


def _row(n: int, sido: str, sgg: str, trades: list[str]) -> VendorRow:
    registered = n == 4
    return VendorRow(
        source="seed",
        source_id=f"fake-{n:03d}",
        name=f"가짜인테리어 {n}",
        trades=trades,
        industries=["실내건축공사업"] if registered else ["인테리어 디자인업"],
        sido=sido,
        sgg=sgg,
        address=f"가짜 주소 {n} (개발용)",
        reg_kind="construction" if registered else None,
        reg_no=f"{n:010d}" if registered else None,
        phone=f"020000000{n}" if n == 3 else None,
    )


async def seed(s: AsyncSession, now: datetime) -> int:
    await repo.upsert(s, [_row(n, sido, sgg, t) for n, sido, sgg, t, _, _ in FAKES], now=now)
    for n, _, _, _, extra, sms in FAKES:
        sid = f"fake-{n:03d}"
        if extra:
            await s.execute(
                update(ExtVendor)
                .where(ExtVendor.source == "seed", ExtVendor.source_id == sid)
                .values(**extra)
            )
        if sms:
            q = select(ExtVendor.id).where(ExtVendor.source == "seed", ExtVendor.source_id == sid)
            vid = (await s.execute(q)).scalar_one()
            await s.execute(
                insert(ExtVendorContact)
                .values(vendor_id=vid, channel="sms", value=sms, consented_at=now, source="seed")
                .on_conflict_do_nothing()
            )
    await s.commit()
    return len(FAKES)


async def _run() -> int:
    async with SessionLocal() as s:
        n = await seed(s, now_utc())
    await engine.dispose()
    return n


def main(argv: list[str]) -> None:
    if settings.app_env != "local":
        raise SystemExit("가짜 외부 업체는 로컬(APP_ENV=local)에서만 넣을 수 있어요.")
    print(f"가짜 외부 업체 {asyncio.run(_run())}곳을 넣었어요.")


if __name__ == "__main__":
    main(sys.argv[1:])
