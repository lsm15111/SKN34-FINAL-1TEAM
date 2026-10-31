"""외부 업체 수집 작업 (arq). worker.py가 functions에 한 줄씩 등록한다.

키가 없으면 부르지 않고 건너뛴다. 실패는 짧은 이유만 로그에 남긴다 (키 · 주소 · 업체 정보는 남기지 않는다).
테스트는 ctx["http"]에 가짜 HTTP 클라이언트를 넣는다.
"""

import csv
import logging
import re
from contextlib import nullcontext
from datetime import timedelta
from pathlib import Path

from app.config import settings
from app.db import SessionLocal
from app.directory import client, service
from app.directory.site import SiteChecker
from app.shared.clock import now_utc, today_seoul

log = logging.getLogger(__name__)
_DAY = re.compile(r"^\d{8}$")


def _http(ctx: dict, timeout: float = client.API_TIMEOUT_S):
    given = ctx.get("http")
    return nullcontext(given) if given is not None else client.http_client(timeout)


async def import_sangga_csv(ctx: dict, path: str) -> dict:
    """상가정보 CSV 파일 하나 (사람이 내려받아 서버에 둔 파일 경로)"""
    p = Path(path)
    if p.suffix.lower() != ".csv" or not p.is_file():
        return {"error": "no_file"}
    async with SessionLocal() as s:
        try:
            return await service.import_sangga_csv(s, p, now=now_utc())
        except (ValueError, csv.Error) as exc:
            log.warning("상가정보 CSV를 읽지 못했어요 (%s)", type(exc).__name__)
            return {"error": "bad_csv"}


async def sync_kiscon(ctx: dict, start: str | None = None, end: str | None = None) -> dict:
    """KISCON 공시를 기간(YYYYMMDD)만큼 받아 반영한다. 기간을 안 주면 지난 7일."""
    if not settings.data_go_kr_key:
        return {"skipped": "no_key"}
    today = today_seoul()
    start = start or (today - timedelta(days=7)).strftime("%Y%m%d")
    end = end or today.strftime("%Y%m%d")
    if not (_DAY.match(start) and _DAY.match(end)) or start > end:
        return {"error": "bad_period"}
    async with _http(ctx) as http, SessionLocal() as s:
        try:
            return await service.sync_kiscon(
                s, http, settings.data_go_kr_key, start, end, now=now_utc()
            )
        except client.ApiError as exc:
            log.warning("KISCON 공시를 받지 못했어요 (%s)", exc.reason)
            return {"error": exc.reason}


async def verify_biz_status(ctx: dict, limit: int = 1000) -> dict:
    """모아 둔 사업자번호의 국세청 상태만 확인한다 (검증 전용)."""
    if not settings.data_go_kr_key:
        return {"skipped": "no_key"}
    async with _http(ctx) as http, SessionLocal() as s:
        try:
            return await service.verify_biz(
                s, http, settings.data_go_kr_key, now=now_utc(), limit=limit
            )
        except client.ApiError as exc:
            log.warning("국세청 상태를 확인하지 못했어요 (%s)", exc.reason)
            return {"error": exc.reason}


async def match_kakao_places(ctx: dict, limit: int = 200) -> dict:
    """외부 업체의 카카오맵 장소 ID만 맞춘다. 검색 결과의 다른 칸(전화 · 주소 · 분류)은 저장하지 않는다."""
    if not settings.kakao_rest_key:
        return {"skipped": "no_key"}
    async with _http(ctx) as http, SessionLocal() as s:
        try:
            return await service.match_places(
                s, http, settings.kakao_rest_key, now=now_utc(), limit=limit
            )
        except client.ApiError as exc:
            log.warning("카카오 장소를 찾지 못했어요 (%s)", exc.reason)
            return {"error": exc.reason}


async def check_homepages(ctx: dict, limit: int = 50) -> dict:
    """업체 홈페이지에서 포트폴리오 · 견적 링크만 찾는다 (robots.txt 준수, 요청 간격)."""
    async with _http(ctx, settings.crawl_timeout_s) as http, SessionLocal() as s:
        site = SiteChecker(http, interval=settings.crawl_interval_s, **ctx.get("site", {}))
        return await service.check_homepages(s, site, now=now_utc(), limit=limit)
