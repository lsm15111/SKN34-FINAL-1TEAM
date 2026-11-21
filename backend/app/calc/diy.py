"""반셀프 직접 할 일 날짜: 업체 공사 날짜(공정표 블록) + 고객이 고른 칩 → 할 일마다 '언제부터 · 언제까지'.

- 순수 함수예요(DB · HTTP · 시계 없음). 오늘 날짜 · 공휴일 · 입주일은 인자로 받아요.
- 규칙은 판 이름을 붙인 상수(RULES_V1)예요. 결과에 판(rule_ver)을 적고, 바꿀 때는 새 판을 더해 RULES를 옮겨요.
- 기준 블록: 목공 · 도배 공사(공정 이름), 업체 공사 전체(all: 첫날 ~ 마지막 날), 도배 뒤 자연 건조(dry),
  입주 청소(clean), 입주일(move_in). 없는 기준은 다음 후보로 넘어가고, 후보가 모두 없으면 그쪽 끝은 비워요.
  · 전에 할 일(before): 그 공사 시작 전까지 끝내요. 페인트는 칠이 마를 날을 비워요(도배 시작 − PAINT_DRY_DAYS).
  · 뒤에 할 일(after): 그 공사가 끝난 다음 날부터 해요. 실리콘은 굳을 날을 두고 입주 청소 전날까지,
    조명 · 새 커버 · 손잡이는 입주 청소 날(청소 전)까지예요.
  · 꼭 있어야 하는 기준(needs)이 없으면 그 걸음은 빼요(도배가 없으면 콘센트 덮개 떼기는 없어요).
- 고객이 할 수 있는 날: any(모든 날) · weekend(주말 요일 · 공휴일). 창 안에서 그런 날로 좁혀요. 그런 날이 없으면
  날짜는 창 그대로 두고 fit=False(why no_free_day)예요.
- 오늘보다 앞선 시작은 오늘로 당겨요. 시작이 마감보다 늦으면 fit=False(why short), 마감이 오늘보다 앞이면
  late=True(why late)예요.
- 공정표에 둘 날(day): 전에 할 일은 마감 날, 뒤에 할 일은 시작 날이에요.
- 업체 공사 날짜가 하나도 없으면 날짜 없이(start · end · day 모두 None) 순서만 돌려줘요.
"""

from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from app.calc.schedule import WEEKEND

Free = Literal["any", "weekend"]
Edge = Literal["start", "end"]
Kind = Literal["before", "after"]
Why = Literal["", "short", "no_free_day", "late"]
Bound = tuple[tuple[str, Edge, int], ...]  # (기준 블록, 끝, 더할 날) 후보를 앞에서부터

KEYS: tuple[str, ...] = ("paint", "outlet", "light", "silicone", "handle", "clean")
# 칠을 끝내고 도배 전까지 비울 날(제조사 완전 건조 72시간: KCC 숲으로 홈앤멀티멜 데이터시트, 2026-11-21 확인)
PAINT_DRY_DAYS = 3
COVER_OFF_DAYS = 3  # 콘센트 덮개는 도배 사흘 전부터 떼요(일찍 떼면 드러난 채로 오래 지내요)
FREE_SEARCH_DAYS = 62  # 마감이 없는 일에서 할 수 있는 날을 찾는 범위
SELF = "고객이 직접"  # 공정표 '고객이 직접' 줄 꼬리(calc.schedule 입주 청소 줄과 같은 꼴)
TASK_NAME = {  # 할 일 화면 말(공정표 줄 · 카드 체크 칸)
    ("paint", ""): "페인트(문틀 · 몰딩) 칠하기",
    ("outlet", "off"): "콘센트 · 스위치 덮개 떼기",
    ("outlet", "on"): "콘센트 · 스위치 새 커버 달기",
    ("light", ""): "조명 교체",
    ("silicone", ""): "실리콘 · 줄눈",
    ("handle", ""): "손잡이 · 문고리 바꾸기",
    ("clean", ""): "입주 청소",
}
AFTER_END: Bound = (("clean", "start", 0), ("move_in", "start", -1))  # 입주 청소 날(청소 전)까지


@dataclass(frozen=True)
class Rule:
    key: str
    step: str  # "" 한 번에 하는 일 · off · on(콘센트 덮개 떼기 · 새 커버 달기)
    kind: Kind
    start: Bound  # 언제부터
    end: Bound  # 언제까지
    needs: str | None = None  # 이 기준 블록이 없으면 이 걸음은 빼요


RULE_VER = "diy_v1"
RULES_V1: tuple[Rule, ...] = (
    # 페인트(문틀 · 몰딩): 목공이 끝난 뒤, 도배 전에 칠하고 말린다
    Rule("paint", "", "before", (("mokgong", "end", 1),),
         (("dobae", "start", -PAINT_DRY_DAYS), ("clean", "start", -1), ("move_in", "start", -1))),
    # 콘센트 · 스위치 커버: 도배 전 덮개 떼기 → 도배 뒤 새 커버
    Rule("outlet", "off", "before", (("dobae", "start", -COVER_OFF_DAYS),), (("dobae", "start", -1),),
         needs="dobae"),
    Rule("outlet", "on", "after", (("dobae", "end", 1), ("all", "end", 1)), AFTER_END),
    # 조명 교체: 도배 뒤
    Rule("light", "", "after", (("dobae", "end", 1), ("all", "end", 1)), AFTER_END),
    # 실리콘 · 줄눈: 업체 공사가 다 끝난 뒤, 굳을 날을 두고 입주 청소 전날까지
    Rule("silicone", "", "after", (("all", "end", 1),), (("clean", "start", -1), ("move_in", "start", -1))),
    # 손잡이 · 문고리: 업체 공사가 다 끝난 뒤, 입주 청소 날(청소 전)까지
    Rule("handle", "", "after", (("all", "end", 1),), AFTER_END),
    # 입주 청소: 모든 공사 · 건조 뒤(공정표의 입주 청소 날부터), 입주 전날까지
    Rule("clean", "", "after", (("clean", "start", 0), ("dry", "end", 1), ("all", "end", 1)),
         (("move_in", "start", -1),)),
)  # fmt: skip
RULES = RULES_V1


@dataclass(frozen=True)
class DiyTask:
    key: str
    step: str
    kind: Kind
    start: date | None  # 언제부터(None: 정한 날 없음)
    end: date | None  # 언제까지(None: 마감 없음)
    day: date | None  # 공정표에 둘 날
    fit: bool  # 창 안에 고객이 할 수 있는 날이 있음
    late: bool  # 마감이 오늘보다 앞
    why: Why
    rule_ver: str = RULE_VER

    @property
    def name(self) -> str:
        return TASK_NAME[(self.key, self.step)]


def blocks_of(
    work: Mapping[str, tuple[date, date]],
    dry: tuple[date, date] | None = None,
    clean: tuple[date, date] | None = None,
    move_in: date | None = None,
) -> dict[str, tuple[date, date]]:
    """기준 블록 표: 공정(work) · 업체 공사 전체(all) · 자연 건조(dry) · 입주 청소(clean) · 입주일(move_in)."""
    out: dict[str, tuple[date, date]] = {}
    for trade, (a, b) in work.items():
        if b < a:
            raise ValueError("공사 끝날이 시작일보다 앞이에요")
        out[trade] = (a, b)
    if work:
        out["all"] = (min(a for a, _ in work.values()), max(b for _, b in work.values()))
    if dry is not None:
        out["dry"] = dry
    if clean is not None:
        out["clean"] = clean
    if move_in is not None:
        out["move_in"] = (move_in, move_in)
    return out


def _bound(table: Mapping[str, tuple[date, date]], cands: Bound) -> date | None:
    for name, edge, add in cands:
        got = table.get(name)
        if got is not None:
            return (got[0] if edge == "start" else got[1]) + timedelta(days=add)
    return None


def _scan(lo: date, hi: date, ok: Callable[[date], bool], *, back: bool = False) -> date | None:
    """lo ~ hi(둘 다 넣어서)에서 ok인 첫 날(back이면 마지막 날)."""
    step = timedelta(days=-1 if back else 1)
    d = hi if back else lo
    while lo <= d <= hi:
        if ok(d):
            return d
        d += step
    return None


def _task(
    r: Rule,
    table: Mapping[str, tuple[date, date]],
    today: date,
    ok: Callable[[date], bool],
) -> DiyTask | None:
    if "all" not in table:  # 업체 공사 날짜가 없으면 순서만
        return DiyTask(r.key, r.step, r.kind, None, None, None, True, False, "")
    if r.needs is not None and r.needs not in table:
        return None
    raw_start, end = _bound(table, r.start), _bound(table, r.end)
    start = max(raw_start, today) if raw_start is not None else today
    if end is not None and end < today:
        return DiyTask(r.key, r.step, r.kind, raw_start, end, end, False, True, "late")
    if end is not None and start > end:  # 앞 공사 끝과 뒤 공사 시작 사이가 모자라요
        day = end if r.kind == "before" else start
        return DiyTask(r.key, r.step, r.kind, start, end, day, False, False, "short")
    hi = end if end is not None else start + timedelta(days=FREE_SEARCH_DAYS)
    first = _scan(start, hi, ok)
    if first is None:
        day = end if r.kind == "before" else start
        return DiyTask(r.key, r.step, r.kind, start, end, day, False, False, "no_free_day")
    last = _scan(first, end, ok, back=True) if end is not None else None
    day = last if r.kind == "before" and last is not None else first
    return DiyTask(r.key, r.step, r.kind, first, last, day, True, False, "")


def plan(
    keys: Iterable[str],
    work: Mapping[str, tuple[date, date]],
    today: date,
    *,
    dry: tuple[date, date] | None = None,
    clean: tuple[date, date] | None = None,
    move_in: date | None = None,
    free: Free = "any",
    days_off: Collection[date] = (),
    weekend: Collection[int] = WEEKEND,
    rules: Sequence[Rule] = RULES,
) -> list[DiyTask]:
    """고른 칩 키 → 할 일 목록(콘센트는 두 걸음). 공정표에 둘 날 순, 날이 없으면 칩 순서(KEYS)예요."""
    picked = set(keys)
    if picked - set(KEYS):
        raise ValueError("모르는 직접 할 일이에요")
    if free not in ("any", "weekend"):
        raise ValueError("할 수 있는 날은 any · weekend 중 하나예요")
    table = blocks_of(work, dry, clean, move_in)

    def ok(d: date) -> bool:
        return free == "any" or d.weekday() in weekend or d in days_off

    got = [_task(r, table, today, ok) for r in rules if r.key in picked]
    order = {k: i for i, k in enumerate(KEYS)}
    out = [t for t in got if t is not None]
    return sorted(out, key=lambda t: (t.day or date.max, order[t.key], t.step != "off"))


def due_soon(tasks: Iterable[DiyTask], today: date, within: int = 7) -> list[DiyTask]:
    """마감이 오늘부터 within일 안인 할 일(지난 것 · 마감 없는 것은 빼요), 마감 가까운 순."""
    last = today + timedelta(days=within)
    got = [t for t in tasks if t.end is not None and not t.late and today <= t.end <= last]
    return sorted(got, key=lambda t: (t.end or date.max, KEYS.index(t.key), t.step != "off"))
