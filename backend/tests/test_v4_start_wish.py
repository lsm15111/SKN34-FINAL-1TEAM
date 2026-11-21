"""공사 희망 시기 칩 → 공사 시작 희망일(calc.start_wish, 2026-11-21 사용자 결정 '처음 기본 정보 8개').

칩 날짜를 시험으로 고정한다(오늘 서울 기준): 이번 달 = 이번 달 마지막 날 · 다음 달 = 다음 달 15일 ·
2~3달 뒤 = 3달 뒤 달의 1일. GET /guest/start-options는 로그인 없이 같은 값을 주고, 그 날짜는 희망일 검사를 지난다."""

import calendar
from datetime import date, timedelta

import pytest

from app.calc.start_wish import START_WISHES, start_wish
from app.shared.clock import today_seoul
from tests.test_v3_project_home import HOME


@pytest.mark.parametrize(
    ("today", "want"),
    [
        (date(2026, 11, 21), (date(2026, 11, 30), date(2026, 12, 15), date(2027, 2, 1))),
        (date(2026, 11, 30), (date(2026, 11, 30), date(2026, 12, 15), date(2027, 2, 1))),
        (date(2026, 12, 1), (date(2026, 12, 31), date(2027, 1, 15), date(2027, 3, 1))),
        (date(2027, 10, 31), (date(2027, 10, 31), date(2027, 11, 15), date(2028, 1, 1))),
        (date(2028, 2, 3), (date(2028, 2, 29), date(2028, 3, 15), date(2028, 5, 1))),
    ],
)
def test_start_wish_chips_map_to_fixed_dates(today, want):
    """이번 달 = 이번 달 마지막 날 · 다음 달 = 다음 달 15일 · 2~3달 뒤 = 3달 뒤 달의 1일"""
    assert tuple(start_wish(k, today) for k in START_WISHES) == want


def _plus_months(d: date, n: int) -> date:
    k = d.year * 12 + d.month - 1 + n
    y, m = k // 12, k % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def test_start_wish_stays_inside_each_period_every_day():
    """두 해 동안 날마다: 이번 달은 오늘 ~ 이번 달 끝, 다음 달은 다음 달 안, 2~3달 뒤는 오늘 + 2달 ~ + 3달."""
    d = date(2026, 1, 1)
    while d < date(2028, 1, 1):
        this, nxt, later = (start_wish(k, d) for k in START_WISHES)
        assert d <= this and (this.year, this.month) == (d.year, d.month)
        assert (nxt.year, nxt.month) == (_plus_months(d, 1).year, _plus_months(d, 1).month)
        assert _plus_months(d, 2) <= later <= _plus_months(d, 3)
        d += timedelta(days=1)
    with pytest.raises(ValueError):
        start_wish("someday", date(2026, 11, 21))  # type: ignore[arg-type]


def test_start_options_api_without_login(api):
    api.cookies.clear()
    r = api.get("/guest/start-options")
    assert r.status_code == 200, r.text
    today = today_seoul()
    assert r.json() == [
        {"key": k, "start_date": start_wish(k, today).isoformat()} for k in START_WISHES
    ]
    for opt in r.json():  # 칩 날짜는 희망일 검사(오늘 ~ 2년 안)를 지난다
        g = api.post("/guest/standard", json={**HOME, "start_date": opt["start_date"]})
        assert g.status_code == 200, g.text
