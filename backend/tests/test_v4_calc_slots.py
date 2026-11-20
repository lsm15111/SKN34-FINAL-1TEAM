"""v4 비서 실측 시간 후보 (calc.slots): 요청 전 희망 기간 · 업체 기간 안 반나절 · 업체가 답할 기간. 순수 함수."""

from datetime import date, timedelta
from itertools import pairwise

import pytest

from app.calc import slots

TODAY = date(2026, 12, 1)  # 화
WORK = date(2027, 1, 4)  # 공사 시작 희망(월): − 28 ~ − 14 = 12.07 ~ 12.21, − 20 = 12.15


def d(n: int) -> date:
    return TODAY + timedelta(days=n)


def test_wish_candidates_pick_ranges_with_most_open_halves_inside_draft():
    # 12.07 ~ 12.21 중 12.16 ~ 12.20만 오전 · 오후가 비어 있다
    free = {date(2026, 12, 16) + timedelta(days=i): ["am", "pm"] for i in range(5)}
    got = slots.wish_candidates(free, WORK, TODAY)
    assert got[0].open_count == 10
    assert got[0].start <= date(2026, 12, 16) and got[0].end >= date(2026, 12, 20)
    assert got[0].basis == "start_minus_20"
    assert len(got) <= slots.WISH_MAX
    assert all(not slots.overlaps(a.start, a.end, b.start, b.end) for a, b in pairwise(got))
    lo, hi = slots.draft_wish(WORK, TODAY)
    assert all(lo <= r.start <= r.end <= hi for r in got)


def test_wish_candidates_respect_prefer_and_holidays():
    free = {date(2026, 12, 8): ["am"], date(2026, 12, 9): ["pm"], date(2026, 12, 25): ["am", "pm"]}
    pm = slots.wish_candidates(free, WORK, TODAY, prefer="pm")
    assert pm and all(r.start <= date(2026, 12, 9) <= r.end for r in pm[:1])
    assert pm[0].open_count == 1
    # 공휴일(쉬는 날)은 세지 않는다
    off = slots.wish_candidates(
        {date(2026, 12, 15): ["am"]}, WORK, TODAY, days_off={date(2026, 12, 15)}
    )
    assert off == []


def test_wish_candidates_without_work_start_look_28_days_from_tomorrow():
    got = slots.wish_candidates({d(3): ["am"], d(40): ["am"]}, None, TODAY)
    assert got and got[0].basis == "earliest" and got[0].start <= d(3) <= got[0].end
    assert all(r.end <= d(slots.WISH_FALLBACK_DAYS) for r in got)


def test_candidates_spread_over_days_prefer_first_then_closest_to_target():
    days = slots.open_halves(date(2026, 12, 10), date(2026, 12, 18), (), {}, 2, today=TODAY)
    got = slots.candidates(days, WORK, TODAY, prefer="pm")
    assert len(got) == 3
    assert all(c.half == "pm" for c in got)
    assert len({c.day for c in got}) == 3  # 날이 겹치지 않게
    assert got[0].day == date(2026, 12, 15) and "prefer_half" in got[0].why
    assert "start_minus_20" in got[0].why


def test_candidates_weekday_preference_and_fill_same_day_when_short():
    # 12.12(토) · 12.14(월)만 열림
    days = [
        slots.DayOpen(date(2026, 12, 12), 1, 1),
        slots.DayOpen(date(2026, 12, 14), 1, 1),
    ]
    got = slots.candidates(days, None, TODAY, day_prefer="weekday")
    assert got[0].day == date(2026, 12, 14) and "prefer_day" in got[0].why
    assert len(got) == 3  # 날 두 개 → 남은 한 칸은 같은 날 다른 반나절
    assert slots.candidates([slots.DayOpen(TODAY, 2, 2)], None, TODAY) == []  # 오늘은 못 고름


def test_best_windows_trim_and_exclude_closed_days():
    free = {
        d(3): ["am", "pm"],
        d(4): [],
        d(5): ["pm"],
        d(6): ["am", "pm"],
        d(12): ["am"],
    }
    got = slots.best_windows(free, d(1), d(14), TODAY, span=7)
    w = got[0]
    assert (w.start, w.end) == (d(3), d(6))  # 앞뒤 빈 칸 없는 날은 뺀다
    assert w.excluded == (d(4),)
    assert w.open_count == 5
    assert all(not slots.overlaps(a.start, a.end, b.start, b.end) for a, b in pairwise(got))
    assert slots.best_windows(free, d(-5), d(0), TODAY) == []  # 지난 기간


def test_best_windows_skip_holidays_and_bad_args():
    free = {d(3): ["am"], d(4): ["am"]}
    got = slots.best_windows(free, d(1), d(7), TODAY, days_off={d(3)})
    assert got[0].start == d(4) and got[0].open_count == 1
    with pytest.raises(ValueError):
        slots.best_windows(free, d(1), d(7), TODAY, span=0)
    with pytest.raises(ValueError):
        slots.wish_candidates(free, None, TODAY, n=0)
