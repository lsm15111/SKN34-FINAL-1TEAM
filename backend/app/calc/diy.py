"""반셀프 직접 할 일 날짜: 업체 공사 날짜(공정표 블록) + 고객이 고른 칩 → 할 일마다 '언제부터 · 언제까지'.

- 순수 함수예요(DB · HTTP · 시계 없음). 오늘 날짜 · 공휴일 · 입주일은 인자로 받아요.
- 규칙은 판 이름을 붙인 상수(RULES_V4)예요. 결과에 판(rule_ver)을 적고, 바꿀 때는 새 판을 더해 RULES를 옮겨요.
  · diy_v2(2026-11-22, QA r1 D5 · D10): 페인트 마감은 도배 시작 − (PAINT_DRY_DAYS + 1)일이라 칠을 끝내고 사흘을
    통째로 비워요(v1은 − 3일이라 빈 날이 이틀). 빠듯한 일(short)의 공정표 날은 할 수 있는 첫날이에요(v1은 전에 할 일이면
    마감 날이라 목공 바로 뒤 도배인 공정표에서 페인트가 목공 시작 전에 놓였어요).
  · diy_v3(2026-11-22, QA r2 c3): 사는 집(occupied)이면 입주 청소가 마감이 아니라서, 뒤에 할 일(입주 청소 빼고)의
    마감을 공사 뒤 첫 주말(일요일)까지 늘려요(lived). 빈 집은 v2와 같아요.
  · diy_v4(2026-11-24, QA r6 c2): 페인트(문틀 · 몰딩)는 목공 → 칠 → 도배 순서예요. 공정표에 목공 날짜가 없으면
    (믿집은 목공을 잇지 않아 고객이 따로 하는 새 몰딩 · 걸레받이 · 문틀은 날짜를 몰라요) 시작을 오늘로 열지 않고
    날짜 없이 '목공이 끝난 뒤'(after)로 둬요. 마감 · 공정표에 둘 날은 v3와 같아요(v3은 목공이 없으면 오늘부터).
- 기준 블록: 목공 · 도배 공사(공정 이름), 업체 공사 전체(all: 첫날 ~ 마지막 날), 도배 뒤 자연 건조(dry),
  입주 청소(clean), 입주일(move_in). 없는 기준은 다음 후보로 넘어가고, 후보가 모두 없으면 그쪽 끝은 비워요.
  · 전에 할 일(before): 그 공사 시작 전까지 끝내요. 페인트는 칠을 끝내고 PAINT_DRY_DAYS일을 비워요
    (도배 시작 − (PAINT_DRY_DAYS + 1)일까지 칠해요).
  · 뒤에 할 일(after): 그 공사가 끝난 다음 날부터 해요. 실리콘은 굳을 날을 두고 입주 청소 전날까지,
    조명 · 새 커버 · 손잡이는 입주 청소 날(청소 전)까지예요.
  · 꼭 있어야 하는 기준(needs)이 없으면 그 걸음은 빼요(도배가 없으면 콘센트 덮개 떼기는 없어요).
  · 벽지 직접 구매(paper_buy, 2026-11-22): 오늘부터 도배 시작 전날까지 벽지를 사서 현장에 받아 둬요(도배가 없으면 없어요).
- 고객이 할 수 있는 날: any(모든 날) · weekend(주말 요일 · 공휴일). 창 안에서 그런 날로 좁혀요. 그런 날이 없으면
  날짜는 창 그대로 두고 fit=False(why no_free_day)예요.
- 오늘보다 앞선 시작은 오늘로 당겨요. 시작이 마감보다 늦으면 fit=False(why short), 마감이 오늘보다 앞이면
  late=True(why late)예요.
- 공정표에 둘 날(day): 전에 할 일은 마감 날, 뒤에 할 일은 시작 날이에요. 빠듯하면(short) 규칙의 tight 끝
  (diy_v2는 모두 start: 앞 공사가 끝난 다음 날)이에요. 마감(end)은 그대로 알려요.
- 업체 공사 날짜가 하나도 없으면 날짜 없이(start · end · day 모두 None) 순서만 돌려줘요.
"""

from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from typing import Literal

from app.calc.schedule import WEEKEND

Free = Literal["any", "weekend"]
Edge = Literal["start", "end"]
Kind = Literal["before", "after"]
Why = Literal["", "short", "no_free_day", "late"]
Bound = tuple[tuple[str, Edge, int], ...]  # (기준 블록, 끝, 더할 날) 후보를 앞에서부터

KEYS: tuple[str, ...] = ("paint", "outlet", "light", "silicone", "handle", "clean", "paper_buy")
# 칠을 끝내고 도배 전까지 통째로 비울 날(제조사 완전 건조 72시간: KCC 숲으로 홈앤멀티멜 데이터시트, 2026-11-21 확인).
# 마감 날 저녁에 칠을 끝내도 72시간이 지나게 마감은 도배 시작 − (PAINT_DRY_DAYS + 1)일이에요(diy_v2)
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
    ("paper_buy", ""): "벽지 사서 받아 두기",
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
    tight: Edge = "start"  # 빠듯할 때(short) 공정표에 둘 날: start 할 수 있는 첫날 · end 마감 날
    ver: str = "diy_v2"  # 이 규칙의 판(할 일 rule_ver에 적어요)
    # 사는 집이면 마감을 업체 공사 뒤 첫 주말(일요일)까지 늘려요(입주 청소가 마감이 아니에요, diy_v3)
    lived: bool = False
    # 시작 기준 공사가 공정표에 없으면 시작을 오늘로 열지 않고 날짜 없이 '그 공사가 끝난 뒤'로 둬요(diy_v4: 페인트 · 목공)
    wait: str | None = None


RULE_VER = "diy_v4"
RULES_V2: tuple[Rule, ...] = (
    # 페인트(문틀 · 몰딩): 목공이 끝난 뒤, 도배 전에 칠하고 사흘을 비워 말린다
    Rule("paint", "", "before", (("mokgong", "end", 1),),
         (("dobae", "start", -(PAINT_DRY_DAYS + 1)), ("clean", "start", -1), ("move_in", "start", -1))),
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
    # 벽지 직접 구매: 오늘부터(시작 기준 없음) 도배 시작 전날까지 사서 현장에 받아 둬요
    Rule("paper_buy", "", "before", (), (("dobae", "start", -1),), needs="dobae"),
)  # fmt: skip
# 판 diy_v1(2026-11-21, 기록): 페인트 마감 = 도배 − PAINT_DRY_DAYS일(빈 날 이틀), 빠듯한 전에 할 일은 마감 날에 둬요
RULES_V1: tuple[Rule, ...] = tuple(
    replace(
        r,
        ver="diy_v1",
        tight="end" if r.kind == "before" else "start",
        end=(("dobae", "start", -PAINT_DRY_DAYS), *r.end[1:]) if r.key == "paint" else r.end,
    )
    for r in RULES_V2
)
# 판 diy_v3(2026-11-22, QA r2 c3): v2 + 사는 집이면 뒤에 할 일(입주 청소 빼고) 마감을 공사 뒤 첫 주말까지
RULES_V3: tuple[Rule, ...] = tuple(
    replace(r, ver="diy_v3", lived=r.kind == "after" and r.key != "clean") for r in RULES_V2
)
# 판 diy_v4(2026-11-24, QA r6 c2): v3 + 페인트는 공정표에 목공 날짜가 없으면 시작이 '목공이 끝난 뒤'(날짜 없음)
RULES_V4: tuple[Rule, ...] = tuple(
    replace(r, ver="diy_v4", wait="mokgong" if r.key == "paint" else None) for r in RULES_V3
)
RULES = RULES_V4


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
    # 시작이 날짜 없는 앞 공사 뒤예요(start None): 'mokgong'이면 목공이 끝난 뒤부터 마감(end)까지(diy_v4)
    after: str | None = None

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


def first_sunday(d: date) -> date:
    """d와 같거나 뒤인 첫 일요일(그 주말의 끝)."""
    return d + timedelta(days=(6 - d.weekday()) % 7)


def _after_undated(r: Rule, end: date | None, today: date, ok: Callable[[date], bool]) -> DiyTask:
    """시작이 '날짜 없는 앞 공사(r.wait)가 끝난 뒤'인 일: 시작은 비우고(start None · after) 마감만 세요. 공정표에 둘 날은
    마감 쪽 할 수 있는 마지막 날이에요(전에 할 일과 같아요). 그런 날이 오늘부터 마감까지 없으면 no_free_day예요."""
    if end is None:  # 마감도 없으면 날짜 없이 순서만
        return DiyTask(r.key, r.step, r.kind, None, None, None, True, False, "", r.ver, r.wait)
    if end < today:
        return DiyTask(r.key, r.step, r.kind, None, end, end, False, True, "late", r.ver, r.wait)
    last = _scan(today, end, ok, back=True)
    if last is None:
        return DiyTask(
            r.key, r.step, r.kind, None, end, end, False, False, "no_free_day", r.ver, r.wait
        )
    return DiyTask(r.key, r.step, r.kind, None, last, last, True, False, "", r.ver, r.wait)


def _task(
    r: Rule,
    table: Mapping[str, tuple[date, date]],
    today: date,
    ok: Callable[[date], bool],
    occupied: bool = False,
) -> DiyTask | None:
    if "all" not in table:  # 업체 공사 날짜가 없으면 순서만
        return DiyTask(r.key, r.step, r.kind, None, None, None, True, False, "", r.ver)
    if r.needs is not None and r.needs not in table:
        return None
    raw_start, end = _bound(table, r.start), _bound(table, r.end)
    if occupied and r.lived and end is not None:  # 사는 집: 공사 뒤 첫 주말까지(diy_v3)
        end = max(end, first_sunday(table["all"][1] + timedelta(days=1)))
    if raw_start is None and r.wait is not None:  # 앞 공사(목공) 날짜가 공정표에 없어요(diy_v4)
        return _after_undated(r, end, today, ok)
    start = max(raw_start, today) if raw_start is not None else today
    if end is not None and end < today:
        return DiyTask(r.key, r.step, r.kind, raw_start, end, end, False, True, "late", r.ver)
    if end is not None and start > end:  # 앞 공사 끝과 뒤 공사 시작 사이가 모자라요
        day = start if r.tight == "start" else end
        return DiyTask(r.key, r.step, r.kind, start, end, day, False, False, "short", r.ver)
    hi = end if end is not None else start + timedelta(days=FREE_SEARCH_DAYS)
    first = _scan(start, hi, ok)
    if first is None:
        day = end if r.kind == "before" else start
        return DiyTask(r.key, r.step, r.kind, start, end, day, False, False, "no_free_day", r.ver)
    last = _scan(first, end, ok, back=True) if end is not None else None
    day = last if r.kind == "before" and last is not None else first
    return DiyTask(r.key, r.step, r.kind, first, last, day, True, False, "", r.ver)


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
    occupied: bool = False,
) -> list[DiyTask]:
    """고른 칩 키 → 할 일 목록(콘센트는 두 걸음). 공정표에 둘 날 순, 날이 없으면 칩 순서(KEYS)예요.
    occupied(사는 집)면 lived 규칙의 마감을 공사 뒤 첫 주말까지 늘려요(diy_v3)."""
    picked = set(keys)
    if picked - set(KEYS):
        raise ValueError("모르는 직접 할 일이에요")
    if free not in ("any", "weekend"):
        raise ValueError("할 수 있는 날은 any · weekend 중 하나예요")
    table = blocks_of(work, dry, clean, move_in)

    def ok(d: date) -> bool:
        return free == "any" or d.weekday() in weekend or d in days_off

    got = [_task(r, table, today, ok, occupied) for r in rules if r.key in picked]
    order = {k: i for i, k in enumerate(KEYS)}
    out = [t for t in got if t is not None]
    return sorted(out, key=lambda t: (t.day or date.max, order[t.key], t.step != "off"))


def due_soon(tasks: Iterable[DiyTask], today: date, within: int = 7) -> list[DiyTask]:
    """마감이 오늘부터 within일 안인 할 일(지난 것 · 마감 없는 것은 빼요), 마감 가까운 순."""
    last = today + timedelta(days=within)
    got = [t for t in tasks if t.end is not None and not t.late and today <= t.end <= last]
    return sorted(got, key=lambda t: (t.end or date.max, KEYS.index(t.key), t.step != "off"))
