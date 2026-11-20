"""v3 실측 반나절 계산 (dev-04 · L03). DB · HTTP · 시계를 모른다: 오늘 · 지금은 인자로 받는다.

- 반나절은 am(오전) · pm(오후). 업체는 반나절마다 capacity(1~3, 기본 2)개 칸을 받는다(L03).
  잡아 둔 것(hold)과 확정(booked)을 모두 칸에 센다. 칸 번호(seat)는 1..capacity 중 빈 가장 작은 수.
- 고를 수 있는 날: 업체 기간(start~end) 안 · 빼는 날 아님 · 오늘(서울)보다 뒤.
- 희망 기간 초안(UC-VIS-01): 공사 시작 희망일 − 28일 ~ − 14일. 추천(D15): 희망일 − 20일에 가장 가까운 칸.
  AI는 이 값을 설명만 한다.
- 업체 공사 날(v4 비서 빈 반나절, ADR 0001): 그날은 실측 칸을 모두 막는다.
"""

from collections import Counter
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

Half = Literal["am", "pm"]
HALVES: tuple[Half, ...] = ("am", "pm")
CAPACITY_MAX = 3
DRAFT_FROM_DAYS = 28  # 희망 기간 초안 시작: 공사 시작 희망일 − 28일
DRAFT_TO_DAYS = 14  # 희망 기간 초안 끝: 공사 시작 희망일 − 14일
RECOMMEND_BEFORE_DAYS = 20  # 추천 기준: 공사 시작 희망일 − 20일 ('1.4(월) − 20일 = 12.15(화)')
SPAN_MAX = 62  # 기간 최대 길이(일, DB CHECK와 같다)


@dataclass(frozen=True)
class DayOpen:
    """하루의 남은 칸 수 (0이면 마감)"""

    day: date
    am: int
    pm: int

    def left(self, half: Half) -> int:
        return self.am if half == "am" else self.pm


@dataclass(frozen=True)
class Pick:
    """추천 반나절과 근거 (basis는 화면 · AI가 글로 바꾼다)"""

    day: date
    half: Half
    target: date  # 기준 날 (희망일 − 20일)
    basis: Literal["start_minus_20", "earliest"]


def days_between(start: date, end: date) -> list[date]:
    if end < start or (end - start).days > SPAN_MAX:
        raise ValueError("기간을 다시 확인해 주세요")
    return [start + timedelta(days=n) for n in range((end - start).days + 1)]


def taken_count(holds: Iterable[tuple[date, Half]]) -> dict[tuple[date, Half], int]:
    """살아 있는 잡기(hold · booked)들 → (날, 반나절)마다 쓴 칸 수"""
    return dict(Counter(holds))


def open_halves(
    start: date,
    end: date,
    excluded: Collection[date],
    taken: Mapping[tuple[date, Half], int],
    capacity: int,
    today: date,
) -> list[DayOpen]:
    """업체 기간의 날마다 남은 칸 수. 빼는 날 · 오늘(서울) 이전 · 당일은 0칸."""
    if not 1 <= capacity <= CAPACITY_MAX:
        raise ValueError("반나절 칸 수는 1~3이에요")
    out = []
    for d in days_between(start, end):
        if d in excluded or d <= today:
            out.append(DayOpen(d, 0, 0))
            continue
        am = max(capacity - taken.get((d, "am"), 0), 0)
        pm = max(capacity - taken.get((d, "pm"), 0), 0)
        out.append(DayOpen(d, am, pm))
    return out


def count_open(days: Iterable[DayOpen]) -> int:
    """고를 수 있는 칸 수 = 반나절마다 남은 칸의 합 (D14 '열린 반나절 N칸')"""
    return sum(x.am + x.pm for x in days)


def is_open(days: Iterable[DayOpen], day: date, half: Half) -> bool:
    return any(x.day == day and x.left(half) > 0 for x in days)


def free_seat(used: Collection[int], capacity: int) -> int | None:
    """그 반나절에서 비어 있는 가장 작은 칸 번호 (없으면 None → 409 slot_taken)"""
    for seat in range(1, min(capacity, CAPACITY_MAX) + 1):
        if seat not in used:
            return seat
    return None


def overlaps(a_start: date, a_end: date, b_start: date, b_end: date) -> bool:
    """두 기간이 하루라도 겹치는지 (C22 '겹치는 날 없음' 판정)"""
    return a_start <= b_end and b_start <= a_end


def draft_wish(work_start: date | None, today: date) -> tuple[date, date] | None:
    """요청서 희망 기간 초안: 공사 시작 희망일 − 28일 ~ − 14일. 희망일이 없으면 None(UC-VIS-01 A2).
    시작이 내일보다 이르면 내일로 당기고, 그래도 끝이 시작보다 이르면 시작 하루로 둔다."""
    if work_start is None:
        return None
    start = max(work_start - timedelta(days=DRAFT_FROM_DAYS), today + timedelta(days=1))
    end = max(work_start - timedelta(days=DRAFT_TO_DAYS), start)
    return start, end


def recommend(work_start: date | None, days: Sequence[DayOpen]) -> Pick | None:
    """추천 반나절: 공사 시작 희망일 − 20일에 가장 가까운 열린 칸 (같으면 이른 날 · 오전 먼저).
    희망일이 없으면 가장 이른 열린 칸. 열린 칸이 없으면 None."""
    choices = [(x.day, h) for x in days for h in HALVES if x.left(h) > 0]
    if not choices:
        return None
    if work_start is None:
        d, h = min(choices, key=lambda c: (c[0], HALVES.index(c[1])))
        return Pick(d, h, d, "earliest")
    target = work_start - timedelta(days=RECOMMEND_BEFORE_DAYS)
    d, h = min(choices, key=lambda c: (abs((c[0] - target).days), c[0], HALVES.index(c[1])))
    return Pick(d, h, target, "start_minus_20")


def work_days_in(
    spans: Iterable[tuple[date, date, Collection[date] | None]], start: date, end: date
) -> set[date]:
    """업체 공사 날 중 start ~ end 안의 날. spans = (시작, 끝, 날 목록)이고, 날 목록이 있으면 그 날만,
    없으면(옛 길: 시작 ~ 끝으로 낸 날짜) 일하는 날을 몰라 그 사이 모든 날을 막는다."""
    out: set[date] = set()
    for first, last, days in spans:
        if days:
            out.update(d for d in days if start <= d <= end)
            continue
        d = max(first, start)
        while d <= min(last, end):
            out.add(d)
            d += timedelta(days=1)
    return out
