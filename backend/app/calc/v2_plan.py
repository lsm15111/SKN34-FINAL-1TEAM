"""v2 예상 공정표: v10 fixPlan · defaultStart · planTrades · buildPlan을 옮긴 것.

팀 schedule.fix_plan과 다른 점(v10 그대로 둠): 날짜를 낸 공정은 시작일만 고정하고 기간만큼 놓는다,
하루에 여러 공정이 들어갈 수 있다, 자연 건조는 마지막 공정 뒤에 둔다.
날짜는 "YYYY-MM-DD" 글, 오늘은 인자로 받는다. 결과는 v10 객체와 같은 키의 dict.
"""

import itertools
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

PLAN_ORDER = (
    "window",
    "carpentry",
    "bath",
    "tile",
    "film",
    "paint",
    "wallpaper",
    "floor",
    "furniture",
    "middoor",
    "light",
    "finish",
)
TRADE_OF = {"wallpaper": "dobae", "carpentry": "mokgong"}
DRY_DAYS = 2
CLEAN_DAYS = 1
SPAN = 3 * 366
JOB_MAX_DAYS = 120


@dataclass(frozen=True)
class Opts:
    weekend_work: bool
    avoid: frozenset[str]
    holidays: Mapping[str, str]  # "YYYY-MM-DD" → 이름


def _d(s: str) -> date:
    return date.fromisoformat(s)


def add_days(s: str, n: int) -> str:
    return (_d(s) + timedelta(days=n)).isoformat()


def is_off(s: str, o: Opts) -> bool:
    return (not o.weekend_work and _d(s).weekday() >= 5) or s in o.holidays or s in o.avoid


def next_work(s: str, o: Opts) -> str:
    d = s
    for _ in range(SPAN):
        if not is_off(d, o):
            break
        d = add_days(d, 1)
    return d


def trade_days(steps: Sequence[dict]) -> int:
    return (sum(s["half_days"] for s in steps) + 1) // 2


def fix_plan(trades: Sequence[dict], start: str, o: Opts) -> dict:
    """trades: [{trade, ko, steps, crew, fixed: {start} | None, state}] 순서대로."""
    blocks: list[dict] = []
    days: dict[str, list[dict]] = {}
    cursor, prep_done = start, False
    for t in trades:
        steps = [s for s in t["steps"] if not (s["key"] == "prep" and prep_done)]
        if any(s["key"] == "prep" for s in t["steps"]):
            prep_done = True
        n = max(trade_days(steps), 1)
        fixed = (t.get("fixed") or {}).get("start")
        d = next_work(fixed or cursor, o)
        work = []
        while len(work) < n:
            work.append(d)
            d = next_work(add_days(d, 1), o)
        halves = [s["name"] for s in steps for _ in range(s["half_days"])]
        total = len(halves)
        for k, w in enumerate(work):
            names = [h for i, h in enumerate(halves) if i * n // total == k]
            if not names and total:
                names = [halves[k * total // n]]
            todo = list(dict.fromkeys(names))
            days.setdefault(w, []).append({"trade": t["trade"], "ko": t["ko"], "todo": todo})
        blocks.append(
            {
                "trade": t["trade"],
                "ko": t["ko"],
                "kind": "work",
                "start": work[0],
                "end": work[-1],
                "days": n,
                "crew": t.get("crew"),
                "state": t.get("state") or "expected",
            }
        )
        cursor = add_days(work[-1], 1)
    if any(t["trade"] == "dobae" for t in trades):
        s, e = cursor, add_days(cursor, DRY_DAYS - 1)
        blocks.append(_soft("dry", "자연 건조", s, e, DRY_DAYS))
        for i in range(DRY_DAYS):
            days[add_days(s, i)] = [
                {"trade": "dry", "ko": "자연 건조", "todo": ["창문을 닫고 자연 건조"]}
            ]
        cursor = add_days(e, 1)
    blocks.append(_soft("clean", "입주 청소", cursor, add_days(cursor, CLEAN_DAYS - 1), CLEAN_DAYS))
    days[cursor] = [{"trade": "clean", "ko": "입주 청소", "todo": ["입주 청소 · 고객이 직접"]}]
    end = blocks[-1]["end"]
    out = []
    d = start
    while d <= end:
        out.append(
            {"date": d, "off": is_off(d, o), "holiday": o.holidays.get(d), "items": days.get(d, [])}
        )
        d = add_days(d, 1)
    work_days = sum(b["days"] for b in blocks if b["kind"] == "work")
    return {"start": start, "end": end, "blocks": blocks, "days": out, "work_days": work_days}


def _soft(trade: str, ko: str, s: str, e: str, n: int) -> dict:
    return {
        "trade": trade,
        "ko": ko,
        "kind": trade,
        "start": s,
        "end": e,
        "days": n,
        "crew": None,
        "state": "expected",
    }


def _span(a: str, b: str) -> int:
    return (_d(a) - _d(b)).days


def move_target(move: str) -> str | None:
    """입주일(YYYY-MM이면 1일) 하루 전."""
    if not move:
        return None
    return add_days(move + "-01" if len(move) == 7 else move, -1)


def default_start(
    trades: Sequence[dict], o: Opts, today: str, end_by: str, start_after: str, move: str
) -> str:
    tomorrow = add_days(today, 1)
    earliest = next_work(tomorrow, Opts(False, frozenset(), o.holidays))
    if start_after:
        return next_work(max(earliest, start_after), o)
    target = end_by or move_target(move)
    if target:  # 끝(청소 포함)이 목표일 안쪽이 될 때까지 최대 8번 앞당긴다
        start = next_work(target, o)
        for _ in range(8):
            over = _span(fix_plan(trades, start, o)["end"], target)
            if over <= 0:
                break
            start = add_days(start, -math.ceil(over))
        return earliest if start < earliest else next_work(start, o)
    return next_work(add_days(today, 14), o)


def plan_trades(
    quote: dict,
    cats: Sequence[str],
    props: Mapping[str, dict],
    accepted: Mapping[str, dict],
) -> list[dict]:
    out = []
    for c in PLAN_ORDER:
        if c not in cats:
            continue
        p = next((t for t in quote["precise"] if t["trade"] == TRADE_OF.get(c)), None) or next(
            (t for t in quote["ref"] if t["cat"] == c), None
        )
        if p is None:
            continue
        trade = TRADE_OF.get(c, c)
        prop, acc = props.get(trade), accepted.get(trade)
        fixed = {"start": acc["start"]} if acc else {"start": prop["start"]} if prop else None
        out.append(
            {
                "trade": trade,
                "ko": p["ko"],
                "steps": p["steps"],
                "crew": (prop or {}).get("crew") or p["crew"],
                "fixed": fixed,
                "state": "confirmed" if acc else "pending" if prop else "expected",
                "need": p["days"],
            }
        )
    return out


def work_count(s: str, e: str, o: Opts) -> int:
    n, d = 0, s
    while d <= e:
        if not is_off(d, o):
            n += 1
        d = add_days(d, 1)
    return n


def build_plan(
    trades: list[dict],
    o: Opts,
    today: str,
    end_by: str,
    start_after: str,
    move: str,
) -> dict:
    start = default_start(trades, o, today, end_by, start_after, move)
    plan = fix_plan(trades, start, o)
    plan["trades"] = trades
    warn = []
    target = end_by or move_target(move)
    if target and plan["end"] > target:
        late = _span(plan["end"], target)
        warn.append(
            f"목표({target})보다 {late}일 늦어요. 공정을 줄이거나 주말 공사를 고려해 보세요."
        )
    bs = plan["blocks"]
    for a, b in itertools.pairwise(bs):
        if a["kind"] == "work" and b["kind"] == "work" and b["start"] <= a["end"]:
            warn.append(f"{a['ko']}와 {b['ko']} 날짜가 겹쳐요")
    plan["warn"] = warn
    return plan


def trial(
    plan: dict, trade: str, start: str, end: str, o: Opts, today: str, accepted: Mapping[str, dict]
) -> dict:
    """업체가 낸 날짜를 넣어 보기: 밀리는 공정(customerDateCard) · 낼 수 있는지(vendorDateCard)."""
    trades = [
        {**t, "fixed": {"start": start}} if t["trade"] == trade else t for t in plan["trades"]
    ]
    tried = fix_plan(trades, plan["start"], o)
    old = {b["trade"]: b for b in plan["blocks"]}
    moved = [
        {"trade": b["trade"], "ko": b["ko"], "start": b["start"]}
        for b in tried["blocks"]
        if b["trade"] in old and old[b["trade"]]["start"] != b["start"] and b["trade"] != trade
    ]
    clash = any(
        k != trade and not (end < a["start"] or start > a["end"]) for k, a in accepted.items()
    )
    error = None
    if start < add_days(today, 1):
        error = "시작일은 내일부터 1년 안으로 골라 주세요."
    elif end < start:
        error = "끝나는 날은 시작일과 같거나 뒤로 골라 주세요."
    elif _span(end, start) > JOB_MAX_DAYS:
        error = "공사 날짜는 120일 안으로 골라 주세요."
    elif is_off(start, o) or is_off(end, o):
        error = "시작일과 끝나는 날은 일하는 날로 골라 주세요. 주말 · 공휴일은 쉬어요."
    need = next((t["need"] for t in plan["trades"] if t["trade"] == trade), None)
    wd = work_count(start, end, o) if end >= start and _span(end, start) <= JOB_MAX_DAYS else 0
    return {
        "trade": trade,
        "start": start,
        "end": end,
        "moved": moved,
        "clash": clash,
        "error": error,
        "work_days": wd,
        "need": need,
        "short": need is not None and wd < need,
    }


def weeks(blocks: Sequence[dict]) -> list[dict]:
    """v10 weekList: 공정 시작일이 든 주(월~일)로 묶는다. n = 첫 주부터 몇 주차."""
    if not blocks:
        return []

    def monday(s: str) -> str:
        return add_days(s, -_d(s).weekday())

    first = monday(blocks[0]["start"])
    out: dict[str, list[dict]] = {}
    for b in blocks:
        out.setdefault(monday(b["start"]), []).append(b)
    return [
        {"n": _span(w, first) // 7 + 1, "start": w, "end": add_days(w, 6), "blocks": bs}
        for w, bs in out.items()
    ]
