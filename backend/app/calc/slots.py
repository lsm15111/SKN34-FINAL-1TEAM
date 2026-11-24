"""v3 실측 반나절 계산 (dev-04 · L03). DB · HTTP · 시계를 모른다: 오늘 · 지금은 인자로 받는다.

- 반나절은 am(오전) · pm(오후). 업체는 반나절마다 capacity(1~3, 기본 2)개 칸을 받는다(L03).
  잡아 둔 것(hold)과 확정(booked)을 모두 칸에 센다. 칸 번호(seat)는 1..capacity 중 빈 가장 작은 수.
- 고를 수 있는 날: 업체 기간(start~end) 안 · 빼는 날 아님 · 오늘(서울)보다 뒤.
- 희망 기간 초안(UC-VIS-01): 공사 시작 희망일 − 28일 ~ − 14일. 추천(D15): 희망일 − 20일에 가장 가까운 칸.
  고객이 말한 희망 기간(v4 비서)은 화면 요청과 같은 규칙으로 본다(said_wish: 내일부터 · 62일 안).
  AI는 이 값을 설명만 한다.
- 업체 공사 날(v4 비서 빈 반나절, ADR 0001): 그날은 실측 칸을 모두 막는다.
- v4 비서 후보: 요청 전 희망 기간(wish_candidates) · 업체 기간 안 반나절(candidates) · 업체가 답할 기간(best_windows).
- 같은 집 다른 업체 실측이 잡은 반나절(확정 · 수락 기다림)은 후보 · 고르기에서 뺀다(free_at_home, 두 업체가 같은 때 오지 않게).
"""

from collections import Counter
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from app.calc.schedule import is_off

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


def free_at_home(day: date, half: str, taken: Collection[tuple[date, str]]) -> bool:
    """같은 집 다른 실측이 그 반나절을 잡지 않았는지. taken = 같은 공사의 다른 요청이 잡은 (날, 반나절)
    (확정 · 업체 수락 기다림). 두 업체가 같은 때 오지 않게 후보 · 고르기에서 뺀다(QA edge P8)."""
    return (day, half) not in taken


WishProblem = Literal["past", "order", "long"]


def said_wish(start: date, end: date, today: date) -> WishProblem | None:
    """고객이 말한 희망 기간 검사(화면 요청 visit.flow.request와 같은 규칙): 내일부터(past) · 끝이 시작보다 앞이
    아님(order) · SPAN_MAX일 안(long). 맞으면 None(QA r7 화면 N3: 비서 요청 카드가 고객이 말한 25~27일을 못 담음)."""
    if start <= today:
        return "past"
    if end < start:
        return "order"
    if (end - start).days > SPAN_MAX:
        return "long"
    return None


def draft_wish(work_start: date | None, today: date) -> tuple[date, date] | None:
    """요청서 희망 기간 초안: 공사 시작 희망일 − 28일 ~ − 14일. 희망일이 없으면 None(UC-VIS-01 A2).
    시작이 내일보다 이르면 내일로 당기고, 그래도 끝이 시작보다 이르면 시작 하루로 둔다."""
    if work_start is None:
        return None
    start = max(work_start - timedelta(days=DRAFT_FROM_DAYS), today + timedelta(days=1))
    end = max(work_start - timedelta(days=DRAFT_TO_DAYS), start)
    return start, end


def recommend(
    work_start: date | None,
    days: Sequence[DayOpen],
    taken: Collection[tuple[date, str]] = (),
) -> Pick | None:
    """추천 반나절: 공사 시작 희망일 − 20일에 가장 가까운 열린 칸 (같으면 이른 날 · 오전 먼저).
    희망일이 없으면 가장 이른 열린 칸. 열린 칸이 없으면 None.
    taken(같은 집 다른 실측이 잡은 반나절)은 빼요(free_at_home, 고르기가 409 slot_clash로 막는 칸)."""
    choices = [
        (x.day, h) for x in days for h in HALVES if x.left(h) > 0 and free_at_home(x.day, h, taken)
    ]
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


# ---- v4 비서: 실측 시간 후보 (계약서 5장 vendor_free_slots · my_free_slots) ----
# 업체 빈 반나절(open_by_day: 날 → 남은 반나절 "am" · "pm")은 visit.service.open_halves_for가 준다(고객 정보 없음).
# 쉬는 날은 계산 엔진 규칙(calc.schedule.is_off: 공휴일 days_off · 주말 요일 weekend)을 따른다. 실측은 기본으로
# 공휴일만 쉬고(weekend=()), 고객이 평일 · 주말을 말하면 days로 거른다. 오늘 · 지난 날은 고르지 않는다.

HalfPrefer = Literal["any", "am", "pm"]  # 고객이 편한 반나절
DayPrefer = Literal["any", "weekday", "weekend"]  # 고객이 편한 요일
WISH_SPAN = 7  # 희망 기간 후보 길이(일)
WISH_MAX = 2  # r1 ~ r2
SLOT_MAX = 3  # s1 ~ s3
WINDOW_SPAN = 7  # 업체가 답할 기간 후보 길이(일)
WINDOW_MAX = 3  # w1 ~ w3
WISH_FALLBACK_DAYS = 28  # 공사 시작 희망일이 없으면 내일부터 이 날 수 안에서 찾는다
NEAR_TARGET_DAYS = 3  # 희망일 − 20일에서 이만큼 안이어야 '공사 시작 20일 전쯤'이라고 한다


@dataclass(frozen=True)
class WishRange:
    """요청 전 희망 기간 후보. open_count는 그 기간 업체 빈 반나절 수(고객 선호에 맞는 것만)."""

    start: date
    end: date
    open_count: int
    basis: Literal["start_minus_20", "earliest"]


@dataclass(frozen=True)
class SlotPick:
    """업체가 답한 기간 안의 반나절 후보. why는 그 후보의 사실 코드다(화면 · AI가 글로 바꾼다)."""

    day: date
    half: Half
    # prefer_half · prefer_day(고객이 말한 편한 때) · earliest(열린 반나절 중 가장 이름, 하나) ·
    # start_minus_20(희망일 − 20일에 가장 가까움, 하나, NEAR_TARGET_DAYS 안) · weekday · weekend(요일을 말하지 않았을 때)
    why: tuple[str, ...]


@dataclass(frozen=True)
class Window:
    """업체가 답할 기간 후보(WindowIn 꼴): 시작 · 끝은 빈 칸이 있는 날, 그 사이 빈 칸 없는 날은 excluded."""

    start: date
    end: date
    excluded: tuple[date, ...]
    open_count: int


def _off(d: date, days_off: Collection[date], weekend: Collection[int]) -> bool:
    return is_off(d, days_off, weekend)  # 공휴일 · 주말 규칙은 공정표와 같은 함수


def _day_ok(d: date, days: DayPrefer) -> bool:
    if days == "weekday":
        return d.weekday() < 5
    if days == "weekend":
        return d.weekday() >= 5
    return True


def _free(
    open_by_day: Mapping[date, Collection[str]],
    d: date,
    today: date,
    days_off: Collection[date],
    weekend: Collection[int],
) -> list[Half]:
    """그날 고를 수 있는 반나절(오늘 · 지난 날 · 쉬는 날은 없음)."""
    if d <= today or _off(d, days_off, weekend):
        return []
    got = open_by_day.get(d) or ()
    return [h for h in HALVES if h in got]


def wish_candidates(
    open_by_day: Mapping[date, Collection[str]],
    work_start: date | None,
    today: date,
    *,
    prefer: HalfPrefer = "any",
    days: DayPrefer = "any",
    days_off: Collection[date] = (),
    weekend: Collection[int] = (),
    span: int = WISH_SPAN,
    n: int = WISH_MAX,
) -> list[WishRange]:
    """요청 전 희망 기간 후보 r1~r2. 범위는 희망 기간 초안(공사 시작 희망일 − 28 ~ − 14일, draft_wish), 희망일이
    없으면 내일부터 28일. 그 안의 span일 기간을 하루씩 밀며 선호에 맞는 업체 빈 반나절이 많은 순, 같으면
    희망일 − 20일(없으면 내일)에 가까운 순 · 이른 순. 빈 칸이 없는 기간은 빼고, 서로 겹치지 않게 고른다."""
    if span < 1 or n < 1:
        raise ValueError("기간 길이와 후보 수는 1 이상이에요")
    draft = draft_wish(work_start, today)
    lo, hi = draft or (
        today + timedelta(days=1),
        today + timedelta(days=WISH_FALLBACK_DAYS),
    )
    target = work_start - timedelta(days=RECOMMEND_BEFORE_DAYS) if work_start else lo
    basis: Literal["start_minus_20", "earliest"] = "start_minus_20" if work_start else "earliest"
    ranked: list[tuple[int, int, date, WishRange]] = []
    last = max(lo, hi - timedelta(days=span - 1))
    for st in days_between(lo, last):
        en = min(st + timedelta(days=span - 1), hi)
        count = sum(
            1
            for d in days_between(st, en)
            if _day_ok(d, days)
            for h in _free(open_by_day, d, today, days_off, weekend)
            if prefer == "any" or h == prefer
        )
        if count == 0:
            continue
        mid = st + (en - st) / 2
        ranked.append((-count, abs((mid - target).days), st, WishRange(st, en, count, basis)))
    ranked.sort(key=lambda r: r[:3])
    out: list[WishRange] = []
    for *_, r in ranked:
        if all(not overlaps(r.start, r.end, x.start, x.end) for x in out):
            out.append(r)
        if len(out) == n:
            break
    return out


def candidates(
    days: Sequence[DayOpen],
    work_start: date | None,
    today: date,
    *,
    prefer: HalfPrefer = "any",
    day_prefer: DayPrefer = "any",
    days_off: Collection[date] = (),
    weekend: Collection[int] = (),
    n: int = SLOT_MAX,
    taken: Collection[tuple[date, str]] = (),
) -> list[SlotPick]:
    """업체가 답한 기간의 열린 반나절에서 후보 s1~s3. 순서: 선호(반나절 · 요일)에 맞는 수가 많음 →
    희망일 − 20일(없으면 오늘)에 가까움 → 이른 날 · 오전. 날이 겹치지 않게 먼저 고르고, 모자라면 같은 날
    다른 반나절로 채운다. 까닭(why)은 후보마다 그 후보에 맞는 사실만 단다(SlotPick).
    taken(같은 집 다른 실측이 잡은 반나절)은 후보에서 뺀다(free_at_home)."""
    target = work_start - timedelta(days=RECOMMEND_BEFORE_DAYS) if work_start else None
    # (어긋남 수, 기준과 거리, 날, 반나절 순서, 반나절, 편한 반나절 맞음, 편한 요일 맞음)
    pool: list[tuple[int, int, date, int, Half, bool, bool]] = []
    for x in days:
        if x.day <= today or _off(x.day, days_off, weekend):
            continue
        for h in HALVES:
            if x.left(h) <= 0 or not free_at_home(x.day, h, taken):
                continue
            fit_half = prefer != "any" and h == prefer
            fit_day = day_prefer != "any" and _day_ok(x.day, day_prefer)
            miss = int(prefer != "any" and not fit_half) + int(day_prefer != "any" and not fit_day)
            dist = abs((x.day - target).days) if target else (x.day - today).days
            pool.append((miss, dist, x.day, HALVES.index(h), h, fit_half, fit_day))
    pool.sort(key=lambda p: p[:4])
    picked: list[tuple[int, int, date, int, Half, bool, bool]] = []
    for p in pool:
        if len(picked) < n and all(p[2] != o[2] for o in picked):
            picked.append(p)
    for p in pool:
        if len(picked) < n and p not in picked:
            picked.append(p)
    earliest = min(((p[2], p[3]) for p in pool), default=None)
    near = (
        min(picked, key=lambda p: (abs((p[2] - target).days), p[2], p[3]))
        if target is not None and picked
        else None
    )
    out: list[SlotPick] = []
    for p in picked:
        _miss, _dist, d, hi, h, fit_half, fit_day = p
        why = [
            *(["prefer_half"] if fit_half else []),
            *(["prefer_day"] if fit_day else []),
            *(["earliest"] if (d, hi) == earliest else []),
        ]
        if p is near and target is not None and abs((d - target).days) <= NEAR_TARGET_DAYS:
            why.append("start_minus_20")
        if not fit_day:
            why.append("weekend" if d.weekday() >= 5 else "weekday")
        out.append(SlotPick(d, h, tuple(why)))
    return out


def best_windows(
    open_by_day: Mapping[date, Collection[str]],
    start: date,
    end: date,
    today: date,
    *,
    days_off: Collection[date] = (),
    weekend: Collection[int] = (),
    span: int = WINDOW_SPAN,
    n: int = WINDOW_MAX,
) -> list[Window]:
    """업체가 답할 기간 후보 w1~w3: start ~ end(내일부터) 안 span일 기간 중 빈 반나절이 많은 순, 같으면 이른
    기간. 앞뒤 빈 칸 없는 날은 기간에서 빼고, 사이의 빈 칸 없는 날 · 쉬는 날은 excluded로 둔다. 겹치지 않게 고른다."""
    if span < 1 or n < 1:
        raise ValueError("기간 길이와 후보 수는 1 이상이에요")
    lo = max(start, today + timedelta(days=1))
    if end < lo:
        return []
    ranked: list[tuple[int, date, Window]] = []
    for st in days_between(lo, max(lo, end - timedelta(days=span - 1))):
        span_days = days_between(st, min(st + timedelta(days=span - 1), end))
        free = {d: _free(open_by_day, d, today, days_off, weekend) for d in span_days}
        open_days = [d for d in span_days if free[d]]
        if not open_days:
            continue
        first, last = open_days[0], open_days[-1]
        excluded = tuple(d for d in span_days if first < d < last and not free[d])
        count = sum(len(free[d]) for d in open_days)
        ranked.append((-count, first, Window(first, last, excluded, count)))
    ranked.sort(key=lambda r: r[:2])
    out: list[Window] = []
    for *_, w in ranked:
        if all(not overlaps(w.start, w.end, x.start, x.end) for x in out):
            out.append(w)
        if len(out) == n:
            break
    return out
