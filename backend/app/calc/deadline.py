"""v3 기한 계산 (dev-04 · 9판 rules.due). DB · HTTP · 시계를 모른다: 지금 시각 · 날짜는 인자로 받는다.

- 모든 시각은 timezone 있는 datetime을 받고 돌려준다. 날짜 기준은 서울(SEOUL)이다.
- 'N시간 뒤'는 그대로 더하고(48시간), 'N일 뒤 18:00'은 서울 날짜 + N일의 18:00이다(calc.schedule.due_at).
- 화면의 '지남'은 is_over(now, due_at)로 따로 센다(worker가 늦어도 화면은 맞다).
- 바꾸기 쉽게 기한 값은 이 파일 맨 위 상수에만 둔다(L09 · D12 보류 최소 처리 포함).
"""

from datetime import date, datetime, time, timedelta
from typing import Literal

from app.calc.schedule import DUE_HOUR, due_at
from app.shared.clock import SEOUL

Half = Literal["am", "pm"]

REPLY_HOURS = 48  # 업체 첫 답: 보낸 때 + 48시간 (D15 C)
PICK_DAYS = 7  # 고객 날짜 고르기: 업체 답 + 7일 (D09)
ACCEPT_HOURS = 48  # 업체 수락: 고른 때 + 48시간, 그동안 반나절을 잡아 둔다 (D10)
PROPOSAL_HOURS = 48  # 다른 날 제안 고르기: 제안 + 48시간
CHANGE_HOURS = 48  # 일정 바꾸기 요청 답: 요청 + 48시간 (답이 없으면 원래 일정 그대로)
QUOTE_DAYS = 3  # 실측 견적서: 실측일 + 3일 18:00 (D19)
REMINDER_DAYS_BEFORE = 1  # 실측 전날 18:00 알림
DATES_DAYS = 2  # 공사 날짜: 업체 확정 + 2일 18:00 (지금 그대로)
DATE_REQUEST_HOURS = 48  # 다른 날짜 요청 답: 요청 + 48시간 (지금 다음 날 18:00에서 바꿈)
DONE_REMIND_DAYS = 4  # 공사 끝 알림 + 4일: '3일 뒤 자동으로 끝나요' (D24)
AUTO_DONE_DAYS = 7  # 공사 끝 알림 + 7일: 자동으로 끝 (D24)
VALID_SOON_DAYS = (3, 1)  # 견적서 유효기간 3일 · 1일 전 18:00 알림 (D20)
SOON_HOURS = 12  # 이 시간 안으로 남으면 화면이 '곧 지나요'를 보인다
# 실측 시각 지남(L09): 오전 칸은 13:00, 오후 칸은 18:00이 지나면 '실측 받았어요'를 누를 수 있다
HALF_END: dict[str, time] = {"am": time(13, 0), "pm": time(18, 0)}
# 반나절이 시작하는 시각(캘린더 · 업체 수락 기한). 실제 시각은 확정 뒤 채팅으로 정한다
HALF_START: dict[str, time] = {"am": time(9, 0), "pm": time(13, 0)}
# 기한이 지난 뒤(D12 보류)의 최소 처리: 잡아 둔 반나절만 풀고 '날짜 고를 차례'로 (L10, 팀 확인)
AFTER_ACCEPT_DUE = "release_hold"
AFTER_PROPOSAL_DUE = "release_hold"


def _aware(at: datetime) -> datetime:
    if at.tzinfo is None:
        raise ValueError("시각은 시간대가 있어야 해요")
    return at


def reply_due(sent_at: datetime) -> datetime:
    return _aware(sent_at) + timedelta(hours=REPLY_HOURS)


def pick_due(answered_at: datetime, last_day: date | None = None) -> datetime:
    """고객 날짜 고르기 기한: 업체 답 + 7일. 업체 기간의 마지막 날(last_day)이 오기 전(그날 0시, 서울)을 넘지 않아요.
    고를 수 있는 날은 내일부터라 마지막 날은 그 전날까지 골라야 해요(QA r6 화면 M6: 기간 끝 11.28인데 기한 11.30)."""
    due = _aware(answered_at) + timedelta(days=PICK_DAYS)
    if last_day is None:
        return due
    return min(due, datetime.combine(last_day, time(0), SEOUL))


def accept_due(picked_at: datetime, day: date | None = None, half: Half | None = None) -> datetime:
    """업체 수락 기한(잡아 둔 반나절의 visit_holds.until과 같다): 고른 때 + 48시간. 고른 반나절(day · half)이
    시작하기 전을 넘지 않아요(QA r6 화면 M6: 11.25 오후를 골랐는데 수락 기한 11.25 22:06)."""
    due = _aware(picked_at) + timedelta(hours=ACCEPT_HOURS)
    if day is None or half is None:
        return due
    return min(due, datetime.combine(day, HALF_START[half], SEOUL))


def proposal_due(proposed_at: datetime) -> datetime:
    return _aware(proposed_at) + timedelta(hours=PROPOSAL_HOURS)


def change_due(requested_at: datetime) -> datetime:
    return _aware(requested_at) + timedelta(hours=CHANGE_HOURS)


def date_request_due(requested_at: datetime) -> datetime:
    return _aware(requested_at) + timedelta(hours=DATE_REQUEST_HOURS)


def _at(day: date, hour: int = DUE_HOUR) -> datetime:
    return datetime.combine(day, time(hour), SEOUL)


def quote_due(visit_day: date) -> datetime:
    """실측일 + 3일 18:00 (서울)"""
    return _at(visit_day + timedelta(days=QUOTE_DAYS))


def reminder_at(visit_day: date) -> datetime:
    """실측 전날 18:00 (서울)"""
    return _at(visit_day - timedelta(days=REMINDER_DAYS_BEFORE))


def dates_due(confirmed_at: datetime) -> datetime:
    """업체 확정 + 2일 18:00 (서울)"""
    return due_at(_aware(confirmed_at), DATES_DAYS)


def done_remind_at(done_posted_at: datetime) -> datetime:
    return _aware(done_posted_at) + timedelta(days=DONE_REMIND_DAYS)


def auto_done_at(done_posted_at: datetime) -> datetime:
    return _aware(done_posted_at) + timedelta(days=AUTO_DONE_DAYS)


def valid_soon_at(valid_until: date) -> list[datetime]:
    """유효기간 N일 전 18:00 알림 시각들 (이른 것 먼저)"""
    return [_at(valid_until - timedelta(days=n)) for n in VALID_SOON_DAYS]


def half_end(day: date, half: Half) -> datetime:
    """반나절 칸이 끝나는 시각(L09): 오전 13:00 · 오후 18:00 (서울)"""
    return datetime.combine(day, HALF_END[half], SEOUL)


def is_over(now: datetime, due: datetime | None) -> bool:
    """기한이 지났는지 (기한이 없으면 False). 같은 시각이면 지난 것으로 본다."""
    return due is not None and _aware(now) >= _aware(due)


def is_soon(now: datetime, due: datetime | None, hours: int = SOON_HOURS) -> bool:
    """아직 안 지났고 hours시간 안으로 남았는지 ('곧 지나요')"""
    return due is not None and not is_over(now, due) and due - now <= timedelta(hours=hours)


def visited_ok(now: datetime, day: date, half: Half) -> bool:
    """'실측 받았어요'를 누를 수 있는지: 그 반나절이 끝난 뒤(L09)"""
    return is_over(now, half_end(day, half))


# v4 비서 기억 뽑기 미루기(LLM 꺼짐 · 비용 상한, 리드 결정 11-22 · QA r3 f1): 같은 말을 다시 볼 간격(차례마다),
# 하루 비용 상한이면 다음 서울 날 이 시각(상한이 다시 차요), 말한 때부터 이 날수를 넘으면 더 미루지 않아요
MEMORY_LATER = (timedelta(minutes=30), timedelta(hours=2), timedelta(hours=6), timedelta(hours=12))
MEMORY_NEXT_DAY_AT = time(0, 10)
MEMORY_LATER_DAYS = 3


def memory_later_at(
    now: datetime, said_at: datetime, tries: int, *, next_day: bool, spread_minutes: int = 0
) -> datetime | None:
    """기억 뽑기를 미룰 다음 시각. tries = 이 말로 이미 돈 일 수(1부터). 하루 비용 상한이면(next_day) 다음 서울 날
    0시 10분, 아니면 MEMORY_LATER 간격(다 쓰면 None). spread_minutes만큼 늦춰 한꺼번에 몰리지 않게 해요. 말한 때부터
    MEMORY_LATER_DAYS일을 넘으면 None(옛 말로 새 조건을 덮지 않게)."""
    now, said_at = _aware(now), _aware(said_at)
    if next_day:
        day = now.astimezone(SEOUL).date() + timedelta(days=1)
        at = datetime.combine(day, MEMORY_NEXT_DAY_AT, SEOUL)
    elif 1 <= tries <= len(MEMORY_LATER):
        at = now + MEMORY_LATER[tries - 1]
    else:
        return None
    at += timedelta(minutes=spread_minutes)
    return at if at - said_at <= timedelta(days=MEMORY_LATER_DAYS) else None
