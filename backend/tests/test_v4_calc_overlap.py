"""업체 공사 겹침(계산 엔진, DB 없음): 다른 공사로 찬 날 · 겹치는 날 · 그 날을 피한 공사 날 후보.
팀 수만큼 하루에 공사를 받는다(팀 수 칸이 없으면 한 팀). 날짜는 2026년 12월(1일 화요일, 25일 공휴일)."""

from datetime import date, timedelta

import pytest

from app.calc.schedule import (
    busy_days,
    free_block,
    free_blocks,
    job_days,
    overlap_days,
    workdays,
)
from app.refprice.holidays import days_off

OFF = days_off(date(2026, 12, 1), date(2027, 3, 31))


def d(day: int, month: int = 12) -> date:
    return date(2026 if month == 12 else 2027, month, day)


def test_one_team_any_other_job_day_is_busy():
    jobs = [[d(8), d(9), d(10)], [d(10), d(11)], [d(15), d(15)]]
    assert busy_days(jobs) == {d(8), d(9), d(10), d(11), d(15)}  # 한 공사 안 같은 날은 한 번
    assert busy_days([]) == frozenset()


def test_two_teams_allow_one_overlap():
    jobs = [[d(8), d(9), d(10)], [d(10), d(11)], [d(10), d(14)], [d(14)]]
    assert busy_days(jobs, teams=2) == {d(10), d(14)}  # 두 건 이상인 날만 찬다
    assert busy_days(jobs, teams=3) == {d(10)}
    with pytest.raises(ValueError):
        busy_days(jobs, teams=0)


def test_job_days_uses_picked_days_or_calendar_range():
    assert job_days(d(8), d(14), [d(14), d(8), d(9), d(8)]) == [d(8), d(9), d(14)]
    # 옛 범위 길(날 목록 없음)은 처음 ~ 끝 달력 날 모두(주말도 그 공사가 쥔 날로 본다)
    assert job_days(d(11), d(14)) == [d(11), d(12), d(13), d(14)]
    with pytest.raises(ValueError):
        job_days(d(14), d(11))


def test_overlap_days_are_sorted_and_only_picked_ones():
    assert overlap_days([d(10), d(8), d(14)], {d(8), d(9), d(10)}) == [d(8), d(10)]
    assert overlap_days([d(11)], {d(10)}) == []


def test_free_block_without_busy_is_plain_workdays():
    assert free_block(d(8), 3, (), OFF) == workdays(d(8), 3, OFF) == [d(8), d(9), d(10)]


def test_free_block_skips_a_job_on_the_same_days():
    """F2: 같은 업체의 12.8~12.10 공사가 있으면 그 뒤 첫 일하는 날부터 3일(주말은 건너뜀)."""
    busy = busy_days([[d(8), d(9), d(10)]])
    assert free_block(d(8), 3, busy, OFF) == [d(11), d(14), d(15)]


def test_free_block_weekend_and_holiday():
    # 금요일 시작이면 주말을 건너 월 · 화로 잇고, 월요일이 차면 화요일부터
    assert free_block(d(4), 3, (), OFF) == [d(4), d(7), d(8)]
    assert free_block(d(4), 3, {d(7)}, OFF) == [d(8), d(9), d(10)]
    # 공휴일(12.25 금)은 일하는 날이 아니라 겹침도 없다: 12.24(목) · 12.28(월) · 12.29(화)
    assert free_block(d(24), 3, {d(25)}, OFF) == [d(24), d(28), d(29)]
    # 쉬는 날에 찬 공사는 주말에 쉬는 공사와 겹치지 않고, 주말에도 하는 공사는 그날을 피한다
    sat = d(12)
    assert free_block(d(11), 2, {sat}, OFF) == [d(11), d(14)]
    assert free_block(d(11), 2, {sat}, OFF, weekend=()) == [d(13), d(14)]


def test_free_block_boundaries():
    # 묶음 끝 다음 날 · 시작 전날의 공사는 겹치지 않는다
    assert free_block(d(8), 3, {d(7), d(11)}, OFF) == [d(8), d(9), d(10)]
    # 묶음 첫날이 차면 하루 뒤로, 끝날이 차면 그날 다음부터
    assert free_block(d(8), 3, {d(8)}, OFF) == [d(9), d(10), d(11)]
    assert free_block(d(8), 3, {d(10)}, OFF) == [d(11), d(14), d(15)]
    # 끝날이 until을 넘으면 없다(1년 안 · 낼 수 있는 날만)
    assert free_block(d(8), 3, {d(8)}, OFF, until=d(10)) is None
    assert free_block(d(8), 3, (), OFF, until=d(10)) == [d(8), d(9), d(10)]
    with pytest.raises(ValueError):
        free_block(d(8), 0)


def test_free_blocks_second_candidate_a_week_after_the_first():
    assert free_blocks(d(8), 3, 2, (), OFF) == [[d(8), d(9), d(10)], [d(15), d(16), d(17)]]
    # 첫 후보가 밀리면 둘째도 그 뒤 일주일부터, 둘 다 찬 날을 피한다
    busy = busy_days([[d(8), d(9), d(10)], [d(18), d(21)]])
    got = free_blocks(d(8), 3, 2, busy, OFF)
    assert got == [[d(11), d(14), d(15)], [d(22), d(23), d(24)]]
    assert all(not set(b) & busy for b in got)
    # 기한 안에 하나뿐이면 하나만
    assert free_blocks(d(8), 3, 2, busy, OFF, until=d(17)) == [[d(11), d(14), d(15)]]
    assert free_blocks(d(8), 3, 0) == []
    with pytest.raises(ValueError):
        free_blocks(d(8), 3, 2, gap=0)


def test_free_blocks_skip_a_long_busy_stretch():
    long = [d(8) + timedelta(days=i) for i in range(40)]  # 12.8 ~ 1.16(토) 모두 찬 업체
    (first,) = free_blocks(d(8), 2, 1, busy_days([long]), OFF)
    assert first == [d(18, 1), d(19, 1)]  # 1.17(일) 다음 일하는 날 1.18(월)부터
