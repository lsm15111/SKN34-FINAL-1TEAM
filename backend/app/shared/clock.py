"""서울 기준 오늘 날짜를 한 곳에서 읽는다. 계산 · 검사 함수에는 이 값을 인자로 넘긴다 (AGENTS.md 3장)."""

from datetime import UTC, date, datetime, timedelta, timezone

SEOUL = timezone(timedelta(hours=9), "Asia/Seoul")  # 한국은 서머타임이 없다


def now_utc() -> datetime:
    return datetime.now(UTC)


def today_seoul() -> date:
    return datetime.now(SEOUL).date()
