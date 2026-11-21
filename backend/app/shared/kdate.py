"""날짜 · 시각 글 꼴(카피 가이드 F2 · F5, docs/v3/copy-guide.md 2장). 날짜를 계산하지 않고 글 꼴만 만든다.

- 짧은 꼴 '12.15(화)'가 기본(카드 · 요약 줄 · 판 글), 비서도 읽는 제목 · 사실 줄은 긴 꼴 '12월 15일(화)'.
- 0을 붙이지 않는다. today를 주면 그 해가 아닌 날짜에 연도를 붙인다: '2027.1.4(월)' · '2027년 1월 4일(월)'.
  today가 없으면 연도를 붙이지 않는다(오늘을 모르는 곳).
- 범위는 물결표를 붙여 쓴다: '12.7(월)~12.21(월)' · 같은 달 긴 꼴 '12월 1일(화)~4일(금)'.
- 시각 말(새벽 · 아침 · 오전 · 낮 · 오후 · 저녁 · 밤)은 표 하나(PERIODS)로 정한다: '새벽 2시 5분'. 0시는
  '새벽 0시'(날짜와 같은 날로 읽히게), 12시는 '낮 12시'다.
"""

from collections.abc import Iterable
from datetime import date, datetime

from app.shared.clock import SEOUL

WEEK = "월화수목금토일"
# 시(0~23)가 이 값 이상이면 그 말(위에서부터 차례로). 밤 알림 규칙(21~9시)의 두 끝이 '밤 9시' · '아침 9시'로 읽힌다
PERIODS: tuple[tuple[int, str], ...] = (
    (21, "밤"),
    (18, "저녁"),
    (13, "오후"),
    (12, "낮"),
    (10, "오전"),
    (6, "아침"),
    (0, "새벽"),
)


def _other_year(d: date, today: date | None) -> bool:
    return today is not None and d.year != today.year


def md(d: date, today: date | None = None) -> str:
    """'12.15' · 다른 해면 '2027.1.4'(요일 없는 짧은 꼴: 범위 '12.7~12.21')."""
    head = f"{d.year}." if _other_year(d, today) else ""
    return f"{head}{d.month}.{d.day}"


def md_week(d: date, today: date | None = None) -> str:
    """'12.15(화)' · 다른 해면 '2027.1.4(월)'."""
    return f"{md(d, today)}({WEEK[d.weekday()]})"


def md_list(days: Iterable[date], today: date | None = None) -> str:
    """'12.24(목) · 12.28(월)'(날마다, 주말 · 휴일을 건너뛴 날이 보이게)."""
    return " · ".join(md_week(d, today) for d in days)


def md_range(start: date, end: date, today: date | None = None) -> str:
    """'12.7(월)~12.21(월)': 승인 카드 요약 줄 · 판 글의 기간(짧은 꼴)."""
    return f"{md_week(start, today)}~{md_week(end, today)}"


def md_long(d: date, today: date | None = None) -> str:
    """'12월 15일(화)' · 다른 해면 '2027년 1월 4일(월)': 승인 카드 제목 · 사실 줄처럼 비서도 읽는 날짜 글(긴 꼴)."""
    head = f"{d.year}년 " if _other_year(d, today) else ""
    return f"{head}{d.month}월 {d.day}일({WEEK[d.weekday()]})"


def long_range(start: date, end: date, today: date | None = None) -> str:
    """'12월 1일(화)~4일(금)', 달이 바뀌면 '12월 29일(화)~1월 2일(토)'(긴 꼴 기간)."""
    if (start.year, start.month) == (end.year, end.month):
        return f"{md_long(start, today)}~{end.day}일({WEEK[end.weekday()]})"
    return f"{md_long(start, today)}~{md_long(end, today)}"


def day_list(days: list[date], today: date | None = None) -> str:
    """일하는 날 칸: '2일 · 12.24(목) · 12.28(월)'."""
    return f"{len(days)}일 · {md_list(days, today)}"


def period(hour: int) -> str:
    """시(0~23) → 때 말(PERIODS)."""
    return next(word for start, word in PERIODS if hour >= start)


def hour_text(hour: int, minute: int = 0) -> str:
    """'새벽 2시 5분' · '아침 9시' · '낮 12시' · '밤 9시'(12시간 꼴, 0시는 '새벽 0시')."""
    h = hour if hour <= 12 else hour - 12
    tail = f" {minute}분" if minute else ""
    return f"{period(hour)} {h}시{tail}"


def now_text(at: datetime) -> str:
    """서울 시각 → '11월 22일(일) 새벽 2시 5분'(올해 날짜라 연도 없이)."""
    x = at.astimezone(SEOUL)
    return f"{x.month}월 {x.day}일({WEEK[x.weekday()]}) {hour_text(x.hour, x.minute)}"
