"""공정마다 진행 단계 · 지금 할 일 판정 (순수 함수, 오늘 · 지금 시각은 인자로).

단계 6개: 집 정보 · 공정 → 기준 금액(표준견적서) → 업체 고르기 → 실측 → 업체 확정 → 공사 날짜.
공사 날짜를 수락한 뒤에는 단계를 다 마쳤고, 공사 중 · 끝냄 확인 · 끝남은 phase로 나눈다.
지금 할 일은 고객이 누를 일이 있는 것부터(TODO_RANK 순) 한 줄을 고른다.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

StepState = Literal["done", "now", "todo"]
STEPS = ("house", "standard", "pick", "visit", "deal", "dates")
# 고객이 먼저 해야 할 일 → 기다리는 일 순서. 프로젝트의 '지금 할 일'은 공정 중 가장 앞선 것
TODO_RANK = (
    "check",  # 업체가 끝냈다고 알림 → 확인하기
    "dates_received",  # 업체가 공사 날짜를 냄 → 날짜 확인하기
    "dates_change",  # 수락한 날짜를 바꾸자고 함 → 확인하기
    "extra",  # 추가 금액 → 확인하기
    "quotes_arrived",  # 실측 견적서가 모두 옴 → 비교하기
    "quotes_partial",  # 일부만 옴 → 비교하기
    "dates_overdue",  # 업체가 기한까지 날짜를 안 냄 → 확인하기
    "pick",  # 업체 고르기
    "visit_requested",  # 실측 요청함 → 실측 일정 보기
    "before_work",  # 공사 전 (체크 목록)
    "dates_waiting",  # 업체가 날짜를 정하는 중
    "dates_requested",  # 다른 날짜를 요청함 · 업체 답 기다림
    "working",  # 공사 중
    "fixing",  # 남은 일을 업체가 하는 중
    "done",  # 끝남
)
Phase = Literal["estimate", "progress", "work", "done"]


@dataclass(frozen=True)
class TradeFacts:
    trade: str
    created_on: date
    standard_on: date | None
    asked: int  # 이번 고르기에서 요청한 업체 수 (다시 고르기로 닫힌 것은 빼고)
    asked_on: date | None
    quotes: int  # 견적서를 받은 요청 수 (비교에 들어가는 것)
    waiting: int  # 견적서를 기다리는 요청 수
    quoted_on: date | None  # 마지막으로 견적서를 받은 날
    deal_status: str | None = None  # confirmed · scheduled · checking · fixing · done
    deal_on: date | None = None
    dates_due_at: datetime | None = None  # 업체가 처음 날짜를 낼 기한
    proposed: bool = False  # 수락 기다리는 날짜가 있음
    proposed_on: date | None = None
    request_open: bool = False  # 고객이 낸 다른 날짜 · 바꾸기 요청이 열림
    accepted_on: date | None = None
    start: date | None = None
    end: date | None = None
    work_done_on: date | None = None
    extras_pending: int = 0


@dataclass(frozen=True)
class StepView:
    key: str
    state: StepState
    on: date | None  # 끝난 날 · 지금 단계가 시작된 날
    count: int | None = None  # 요청한 곳 · 받은 견적서 수


@dataclass(frozen=True)
class Progress:
    trade: str
    steps: tuple[StepView, ...]
    current: int  # 지금 단계 번호 1~6 (다 마쳤으면 6)
    phase: Phase
    todo: str
    overdue: bool  # 기한 지남 (상태가 아님)


AFTER_DATES = ("scheduled", "checking", "fixing", "done")


def _todo(f: TradeFacts, today: date, overdue: bool) -> str:
    st = f.deal_status
    if st is None:
        if f.quotes:
            return "quotes_partial" if f.waiting else "quotes_arrived"
        return "visit_requested" if f.asked else "pick"
    if st == "confirmed":
        if f.proposed and not f.request_open:
            return "dates_received"
        if f.request_open:
            return "dates_requested"
        return "dates_overdue" if overdue else "dates_waiting"
    if st == "checking":
        return "check"
    if st == "done":
        return "done"
    if f.extras_pending:
        return "extra"
    if st == "scheduled" and f.proposed and not f.request_open:
        return "dates_change"
    if st == "fixing":
        return "fixing"
    if st == "scheduled" and f.request_open:
        return "dates_requested"
    return "before_work" if f.start is not None and today < f.start else "working"


def progress(f: TradeFacts, today: date, now: datetime) -> Progress:
    """한 공정의 단계 · 지금 할 일. now는 기한(시각)과 견줄 때만 쓴다."""
    if now.tzinfo is None:
        raise ValueError("지금 시각은 시간대가 있어야 해요")
    st = f.deal_status
    dealt = st is not None
    accepted = st in AFTER_DATES
    overdue = (
        st == "confirmed"
        and not f.proposed
        and not f.request_open
        and f.dates_due_at is not None
        and now > f.dates_due_at
    )
    done = {
        "house": True,
        "standard": f.standard_on is not None,
        "pick": f.asked > 0 or dealt,
        "visit": dealt,
        "deal": dealt,
        "dates": accepted,
    }
    on = {
        "house": f.created_on,
        "standard": f.standard_on,
        "pick": f.asked_on,
        "visit": f.quoted_on,
        "deal": f.deal_on,
        "dates": f.accepted_on if accepted else f.proposed_on,
    }
    count = {"pick": f.asked, "visit": f.quotes}
    first = next((i for i, k in enumerate(STEPS) if not done[k]), len(STEPS) - 1)
    steps = tuple(
        StepView(
            k,
            "done" if done[k] else ("now" if i == first else "todo"),
            on[k] if done[k] or i == first else None,
            count.get(k),
        )
        for i, k in enumerate(STEPS)
    )
    if st == "done":
        phase: Phase = "done"
    elif accepted:
        phase = "work"
    elif f.asked or dealt:
        phase = "progress"
    else:
        phase = "estimate"
    return Progress(f.trade, steps, first + 1, phase, _todo(f, today, overdue), overdue)


def project_phase(items: Sequence[Progress]) -> Phase:
    """프로젝트 전체: 모두 끝났으면 끝남, 모두 공사 날짜를 수락했으면 공사, 요청이 없으면 견적만."""
    phases = {p.phase for p in items}
    if not items or phases == {"estimate"}:
        return "estimate"
    if phases == {"done"}:
        return "done"
    if phases <= {"work", "done"}:
        return "work"
    return "progress"


def first_todo(items: Sequence[Progress]) -> Progress | None:
    """프로젝트의 '지금 할 일': 공정 중 TODO_RANK가 가장 앞선 것 (같으면 앞 공정)"""
    if not items:
        return None
    return min(items, key=lambda p: TODO_RANK.index(p.todo))
