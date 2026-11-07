"""선제 안내 트리거: 지금 프로젝트 상황 → 켜진 트리거 키 → 보여 줄 카드(순수 함수, 오늘 날짜는 인자).

카드 본문은 사람이 검수한 데이터(knowledge/data/cards.jsonl)이고, 여기서는 고르기만 한다.
LLM이 실패해도 카드는 보인다. docs/agent/05-coaching.md 3절.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

# calc/progress.py STEPS → 단계 트리거
STAGE_OF_STEP = {
    "house": "stage_start",
    "standard": "stage_quote",
    "pick": "stage_pick",
    "visit": "stage_visit",
    "deal": "stage_deal",
    "dates": "stage_prework",
}
EVENTS = (
    "estimates_listed",
    "visit_requested",
    "quote_arrived",
    "deal_confirmed",
    "mokgong_done",
    "dobae_done",
    "work_done",
)
TRIGGERS = (
    *STAGE_OF_STEP.values(),
    "stage_consult",
    "stage_work",
    "stage_after",
    "trade_dobae",
    "trade_mokgong",
    "has_both_trades",
    "old_building",
    "asbestos_era",
    "occupied",
    "silk_selected",
    "hapji_selected",
    "ceiling_unknown",
    "balcony_ext",
    *EVENTS,
    "d_minus_14",
    "d_minus_7",
    "d_minus_3",
    "winter_work",
    "on_question",
)
OLD_YEARS = 15  # 준공 15년 이상이면 벽 · 천장 보수 위험(T1 F02 · T7 M-03)
ASBESTOS_BEFORE = 2009  # 2009년부터 석면 사용 금지 — 그 전 착공 건물의 천장재는 함유 여부 확인 권장
WINTER = (12, 1, 2)


@dataclass(frozen=True)
class CardContext:
    today: date
    step: str  # calc.progress의 지금 단계(house · standard · pick · visit · deal · dates)
    trades: frozenset[str]  # dobae · mokgong
    built_year: int | None = None
    occupied: bool = False
    grade: str | None = None  # 도배 등급 economy · basic
    balcony_ext: bool = False
    ceiling: str | None = None  # 도배 브리프 천장 포함 슬롯 yes · no · after_visit · None
    flatten: bool = False  # 목공 항목에 천장 평탄화
    work_start: date | None = None  # 첫 공사 날짜(수락한 것)
    working: bool = False  # 공사 중
    finished: bool = False  # 공사 끝냄
    events: frozenset[str] = field(default_factory=frozenset)  # 이번에 생긴 일(EVENTS)


def triggers(ctx: CardContext) -> set[str]:
    on: set[str] = set()
    if ctx.finished:
        on.add("stage_after")
    elif ctx.working:
        on.add("stage_work")
    else:
        on.add(STAGE_OF_STEP.get(ctx.step, "stage_start"))
        if ctx.step == "standard":
            on.add("stage_consult")  # 표준견적서를 본 뒤가 상담 단계
    for t in ctx.trades:
        on.add(f"trade_{t}")
    if {"dobae", "mokgong"} <= ctx.trades:
        on.add("has_both_trades")
    if ctx.built_year and ctx.today.year - ctx.built_year >= OLD_YEARS:
        on.add("old_building")
    if ctx.built_year and ctx.built_year < ASBESTOS_BEFORE and ctx.flatten:
        on.add("asbestos_era")
    if ctx.occupied:
        on.add("occupied")
    if "dobae" in ctx.trades and ctx.grade:
        on.add("silk_selected" if ctx.grade == "basic" else "hapji_selected")
    if "dobae" in ctx.trades and ctx.ceiling in (None, "after_visit"):
        on.add("ceiling_unknown")
    if ctx.balcony_ext:
        on.add("balcony_ext")
    on |= set(ctx.events) & set(EVENTS)
    if ctx.work_start and not ctx.working and not ctx.finished:
        left = (ctx.work_start - ctx.today).days
        for n in (3, 7, 14):  # 가장 가까운 기준 하나만
            if 0 <= left <= n:
                on.add(f"d_minus_{n}")
                break
        if ctx.work_start.month in WINTER:
            on.add("winter_work")
    return on


def pick(
    cards: Sequence[Mapping],
    on: Iterable[str],
    seen: Iterable[str] = (),
    muted: Iterable[str] = (),
    limit: int = 1,
) -> list[Mapping]:
    """켜진 트리거의 카드 중 안 본 것 · 끄지 않은 공정의 것을 priority 높은 순 · 쉬운 것(level 낮은) 먼저 limit장.
    on_question 카드는 물었을 때만(코치가 검색으로) 쓰므로 여기서는 고르지 않는다."""
    active = set(on) - {"on_question"}
    done, off = set(seen), set(muted)
    rows = [
        c
        for c in cards
        if c.get("trigger") in active and c.get("key") not in done and c.get("trade") not in off
    ]
    rows.sort(key=lambda c: (-int(c.get("priority", 0)), int(c.get("level", 2)), c.get("key", "")))
    return rows[:limit]
