"""v3 실측 일정 화면 보조 계산 (dev-04). DB · HTTP · 시계를 모른다: 오늘은 인자로 받는다.

- 반나절 시각(캘린더 파일 .ics): 오전 09:00 ~ 13:00 · 오후 13:00 ~ 18:00 (끝은 deadline.HALF_END, L09).
- 벽지 바꿔 보기 차이(C11 '합지 −31만 1,850원'): 다른 벽지 가견적 합계 − 고른 벽지 합계.
- 한 번 더 요청(시도 2)의 희망 기간: 앞 요청 기간에서 지난 날을 빼고 내일부터.
- 집 이름표(copy-guide F7 · ADR copy-03): '노원구 상계동 · 공급 69.4㎡'. ㎡는 숫자에 붙이고 소수 한 자리.
- 업체 답 시간(C11 '보통 1일 안에 답'): 요청부터 기간 답까지 걸린 시간의 가운데 값, 시간 단위 올림.
- 다른 날 제안 고를 거리(V07): 고객 희망 기간 안에서 업체가 받을 수 있는 반나절.
- 겹치는 날 없음 까닭(C22) · 견적서 두 곳 차이(C33) · 유효기간 3일 안(D20).
"""

import math
import statistics
from collections.abc import Collection, Mapping, Sequence
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from app.calc import slots
from app.calc.deadline import HALF_END, HALF_START
from app.shared.clock import SEOUL

Half = Literal["am", "pm"]
# 반나절이 시작하는 시각(HALF_START)은 deadline에 있어요(업체 수락 기한도 써요). 실제 시각은 확정 뒤 채팅으로 정한다
BASIS_LABEL: dict[str, str] = {"supply": "공급", "exclusive": "전용"}  # area_basis → 화면 말


def area_text(area_m2: Decimal | int | str, basis: str | None = None) -> str:
    """'공급 69.4㎡' · '전용 59.9㎡'. 기준을 모르면(None) '69.4㎡'"""
    m2 = Decimal(str(area_m2)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    if m2 <= 0:
        raise ValueError("면적은 0보다 커야 해요")
    if basis is not None and basis not in BASIS_LABEL:
        raise ValueError(f"알 수 없는 면적 기준: {basis}")
    text = f"{format(m2, 'f')}㎡"
    return f"{BASIS_LABEL[basis]} {text}" if basis else text


def area_label(
    sgg: str | None,
    emd: str | None,
    area_m2: Decimal | int | str | None,
    basis: str | None,
) -> str:
    """'노원구 상계동 · 공급 69.4㎡'. 동이 없으면 구까지, 면적이 없으면(평형만 고른 옛 공사) 곳만."""
    place = " ".join(x for x in (sgg, emd) if x)
    if area_m2 is None:
        return place
    size = area_text(area_m2, basis)
    return f"{place} · {size}" if place else size


def half_span(day: date, half: Half) -> tuple[datetime, datetime]:
    """반나절 칸의 시작 · 끝 시각 (서울)"""
    return datetime.combine(day, HALF_START[half], SEOUL), datetime.combine(
        day, HALF_END[half], SEOUL
    )


def grade_diff(other_total: int, base_total: int) -> int:
    """다른 벽지로 바꾸면 고객이 낼 금액이 얼마나 달라지는지 (음수면 적어요)"""
    if other_total < 0 or base_total < 0:
        raise ValueError("금액은 0보다 작을 수 없어요")
    return other_total - base_total


def again_wish(start: date, end: date, today: date) -> tuple[date, date]:
    """한 번 더 요청의 희망 기간: 앞 기간에서 오늘까지의 날을 뺀다. 다 지났으면 내일 하루."""
    if end < start:
        raise ValueError("기간을 다시 확인해 주세요")
    first = max(start, today + timedelta(days=1))
    return first, max(end, first)


VALID_SOON_DAYS = 3  # 유효기간 '곧 지나요' (D20 알림 3일 전과 같다)


def reply_hours(waits: Sequence[timedelta]) -> int | None:
    """업체가 요청에 기간을 답하기까지 걸린 시간의 가운데 값 (시간, 올림, 1시간보다 짧아도 1).
    답한 요청이 없으면 None"""
    if not waits:
        return None
    if any(w < timedelta(0) for w in waits):
        raise ValueError("답한 때가 요청한 때보다 앞일 수 없어요")
    mid = statistics.median(w.total_seconds() for w in waits)
    return max(math.ceil(mid / 3600), 1)


def propose_options(
    start: date,
    end: date,
    taken: Mapping[tuple[date, Half], int],
    capacity: int,
    today: date,
    skip: Collection[tuple[date, Half]] = (),
) -> list[tuple[date, Half]]:
    """다른 날 제안 고를 거리: 고객 희망 기간(start~end) 안 · 내일부터 · 업체 칸이 남은 반나절.
    skip(고객이 고른 반나절 등)은 뺀다. 이른 날 · 오전 먼저."""
    days = slots.open_halves(start, end, [], taken, capacity, today)
    return [
        (d.day, h) for d in days for h in slots.HALVES if d.left(h) > 0 and (d.day, h) not in skip
    ]


def no_overlap_reason(
    wish_start: date,
    wish_end: date,
    work_start: date | None,
    win_start: date,
    win_end: date,
    open_count: int,
) -> Literal["after_work_start", "after_wish", "before_wish", "full"] | None:
    """C22 '겹치는 날이 없어요' 까닭. 고를 수 있으면 None.
    업체 기간이 희망 기간보다 늦으면 after_wish(공사 시작 희망일보다도 늦으면 after_work_start),
    이르면 before_wish, 겹치지만 남은 칸이 0이면 full."""
    if win_start > wish_end:
        return (
            "after_work_start"
            if work_start is not None and win_start > work_start
            else "after_wish"
        )
    if win_end < wish_start:
        return "before_wish"
    return "full" if open_count <= 0 else None


def quote_gap(totals: Sequence[int]) -> int | None:
    """받은 견적서 합계의 가장 큰 값 − 가장 작은 값 (C33 '두 곳이 40만 7,000원 차이 나요'). 2곳 미만이면 None"""
    if any(x < 0 for x in totals):
        raise ValueError("금액은 0보다 작을 수 없어요")
    return max(totals) - min(totals) if len(totals) >= 2 else None


def quote_vs_estimate(quote_total: int, estimate_total: int) -> int:
    """실측 견적서 − 요청 때 가견적 (고객이 낼 금액 기준, 음수면 가견적보다 적어요)"""
    return grade_diff(quote_total, estimate_total)


def valid_soon(valid_until: date, today: date, days: int = VALID_SOON_DAYS) -> bool:
    """유효기간이 오늘(서울)부터 days일 안에 끝나는지 (이미 지났으면 False)"""
    return today <= valid_until <= today + timedelta(days=days)
