"""공사 희망 시기 칩 → 공사 시작 희망일 (v4 첫 대화 집 확인 카드, 2026-11-21 사용자 결정 '처음 기본 정보 8개').

DB · HTTP · 시계를 모른다: 오늘(서울)은 인자로 받는다. 칩은 대략의 시기라 그 시기의 대표 날 하나로 바꾼다.
- 이번 달(this_month): 이번 달 마지막 날. 이번 달 안에서 실측 · 견적서를 받을 여유가 가장 큰 날이에요.
- 다음 달(next_month): 다음 달 15일(그 달 가운데).
- 2~3달 뒤(in_2_3_months): 3달 뒤 달의 1일. 오늘이 며칠이든 '오늘 + 2달 ~ 오늘 + 3달' 안에 들어요.
'아직 몰라요'는 날짜가 없고(희망일 비움), '날짜 고르기'는 고객이 고른 날 그대로라 여기서 만들지 않는다.
"""

import calendar
from datetime import date
from typing import Literal

StartWish = Literal["this_month", "next_month", "in_2_3_months"]
START_WISHES: tuple[StartWish, ...] = ("this_month", "next_month", "in_2_3_months")
MID_DAY = 15  # 다음 달 대표 날


def _month_ahead(today: date, n: int) -> tuple[int, int]:
    """오늘이 든 달에서 n달 뒤의 (해, 달)"""
    k = today.year * 12 + today.month - 1 + n
    return k // 12, k % 12 + 1


def start_wish(key: StartWish, today: date) -> date:
    """칩 하나 → 공사 시작 희망일. 모르는 칩이면 ValueError."""
    if key == "this_month":
        return date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])
    if key == "next_month":
        return date(*_month_ahead(today, 1), MID_DAY)
    if key == "in_2_3_months":
        return date(*_month_ahead(today, 3), 1)
    raise ValueError("모르는 공사 희망 시기예요")
