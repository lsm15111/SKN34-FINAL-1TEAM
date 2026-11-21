"""시뮬레이터 채점 · 날짜 옮기기 · 승인 규칙. DB · 앱 없이 도는 순수 함수예요(시험이 바로 불러요).

- 날짜: 시나리오는 world.today 기준 날짜로 적혀 있어요. 앱은 실제 시계를 쓰니 모든 날짜를 7의 배수 날만큼
  옮겨요(요일이 그대로). 옮긴 '오늘'은 실제 오늘 ~ 6일 뒤예요. 대본 글의 'M월 D일'도 같이 옮겨요.
- 승인 규칙(script.decide): 사람 역할이 카드 요약 · 실행할 값(payload)만 보고 승인 · 거절 · 그대로 둠을 정해요.
  첫 번째로 맞는 규칙을 따르고, 맞는 규칙이 없으면 누르지 않아요(leave).
- 통과: 끝 상태(expected_end) + 대화 확인(checks)을 모두 맞아야 해요(docs/v4/eval/plan.md). 잴 수 없는 칸은
  na로 두고 통과 계산에서 빼요. 단, 있어야 하는 기억(memory.has)은 기능이 없으면 실패예요.
"""

import json
import math
import re
from collections.abc import Callable
from datetime import date, timedelta

ISO = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
# 'M월 D일'과 그 뒤 범위 끝('12월 17일부터 19일' · '12월 17일~19일'의 19일)
KO_DATE = re.compile(r"(\d{1,2})월\s*(\d{1,2})일(?:(\s*(?:부터|~|-|에서)\s*)(\d{1,2})일)?")
WEEKDAY = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
DOS = ("approve", "reject", "leave")
SCREENS = ("vendor_brief", "vendor_checklist", "vendor_today", "customer_today", "customer_board")


def db_kind(kind: str) -> str:
    """시나리오 이름(propose_visit_slot) → DB 행동 종류(visit_slot)."""
    return kind.removeprefix("propose_")


# ---- 날짜 옮기기 ----


def week_shift(world_today: date, real_today: date) -> int:
    """옮길 날 수: 7의 배수 중 '옮긴 오늘 ≥ 실제 오늘'인 가장 작은 값."""
    return 7 * math.ceil((real_today - world_today).days / 7)


def shift_iso(text: str, days: int) -> str:
    if not days:
        return text

    def one(m: re.Match) -> str:
        try:
            d = date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            return m[0]
        return (d + timedelta(days=days)).isoformat()

    return ISO.sub(one, text)


def shift_obj(obj, days: int):
    """글 속 ISO 날짜(YYYY-MM-DD, 'YYYY-MM-DD:am' 포함)를 모두 옮긴 사본."""
    if isinstance(obj, str):
        return shift_iso(obj, days)
    if isinstance(obj, list):
        return [shift_obj(x, days) for x in obj]
    if isinstance(obj, dict):
        return {k: shift_obj(v, days) for k, v in obj.items()}
    return obj


def shift_ko(text: str, days: int, base: date) -> str:
    """'M월 D일'을 옮겨요. 해는 base(시나리오 오늘)에 가장 가까운 해로 봐요.
    '12월 17일부터 19일'처럼 범위 끝에 월이 없으면 끝도 같이 옮기고, 옮긴 끝의 달이 바뀌면 달을 붙여요."""
    if not days:
        return text

    def one(m: re.Match) -> str:
        best = None
        for y in (base.year - 1, base.year, base.year + 1):
            try:
                d = date(y, int(m[1]), int(m[2]))
            except ValueError:
                continue
            if best is None or abs((d - base).days) < abs((best - base).days):
                best = d
        if best is None:
            return m[0]
        x = best + timedelta(days=days)
        out = f"{x.month}월 {x.day}일"
        if m[4] is None:
            return out
        end = _range_end(best, int(m[4]))
        if end is None:
            return f"{out}{m[3]}{m[4]}일"
        y = end + timedelta(days=days)
        return out + m[3] + (f"{y.day}일" if y.month == x.month else f"{y.month}월 {y.day}일")

    return KO_DATE.sub(one, text)


def _range_end(start: date, day: int) -> date | None:
    """범위 끝 'D일'(월 없음): 시작 날 이후의 그날(같은 달, 지났으면 다음 달)."""
    for k in (0, 1):
        y, mo = start.year + (start.month + k - 1) // 12, (start.month + k - 1) % 12 + 1
        try:
            d = date(y, mo, day)
        except ValueError:
            continue
        if d >= start:
            return d
    return None


# ---- 승인 규칙 ----


def _day(x) -> date | None:
    if isinstance(x, date):
        return x
    if isinstance(x, str) and len(x) >= 10:
        try:
            return date.fromisoformat(x[:10])
        except ValueError:
            return None
    return None


def view_of(action: dict, payload: dict | None, extra: dict | None = None) -> dict:
    """승인 규칙이 보는 값: 카드 요약(금액 · 판) + 실행할 값(날짜 · 반나절 · 업체 수 · 칸)."""
    s, p = action.get("summary") or {}, payload or {}
    days = p.get("days") or []
    v = {
        "kind": action.get("kind"),
        "amount": s.get("amount_won"),
        "version": s.get("version"),
        "day": p.get("day"),
        "half": p.get("half"),
        "wish_start": p.get("wish_start"),
        "wish_end": p.get("wish_end"),
        "vendors": len(p["vendor_ids"]) if p.get("vendor_ids") else None,
        "fields": p.get("fields") or {},
        "code": p.get("code"),
        "start": p.get("start") or (days[0] if days else None),
        "end": p.get("end") or (days[-1] if days else None),
    }
    v.update(extra or {})
    return v


def _weekday_in(want, v, _t) -> bool:
    d = _day(v.get("day")) or _day(v.get("start"))
    return d is not None and d.weekday() in {WEEKDAY[x] for x in want}


def _wish_has(want, v, _t) -> bool:
    a, b = _day(v.get("wish_start")), _day(v.get("wish_end"))
    if a is None or b is None:
        return False
    days = {WEEKDAY[x] for x in want}
    return any((a + timedelta(n)).weekday() in days for n in range(min((b - a).days + 1, 62)))


def _area_in(want, v, _t) -> bool:
    a = (v.get("fields") or {}).get("area_m2")
    try:
        x = float(a)
    except (TypeError, ValueError):
        return False
    return any(lo <= x <= hi for lo, hi in want)


def _field_eq(want, v, _t) -> bool:
    f = v.get("fields") or {}
    return all(k in f and str(f[k]).lower() == str(x).lower() for k, x in want.items())


def _date_cmp(key: str, after: bool):
    """시작(또는 실측 날) · 끝 날짜를 기준 날과 견줘요."""

    def f(want, v, _t) -> bool:
        d = _day(v.get(key)) or (_day(v.get("day")) if key == "start" else None)
        w = _day(want)
        return d is not None and w is not None and (d >= w if after else d <= w)

    return f


def _num(key: str, most: bool):
    def f(want, v, _t) -> bool:
        x = v.get(key)
        return isinstance(x, int | float) and (x <= want if most else x >= want)

    return f


PREDICATES: dict[str, Callable[[object, dict, int], bool]] = {
    "has": lambda want, v, _t: all(v.get(k) not in (None, "", []) for k in want),
    "missing": lambda want, v, _t: any(v.get(k) in (None, "", []) for k in want),
    "amount_max": _num("amount", True),
    "amount_min": _num("amount", False),
    "vendors_max": _num("vendors", True),
    "vendors_min": _num("vendors", False),
    "weekday_in": _weekday_in,
    "half_in": lambda want, v, _t: v.get("half") in want,
    "wish_has_weekday": _wish_has,
    "start_from": _date_cmp("start", True),
    "start_to": _date_cmp("start", False),
    "end_from": _date_cmp("end", True),
    "end_to": _date_cmp("end", False),
    "area_in": _area_in,
    "field_eq": _field_eq,
    "code_in": lambda want, v, _t: v.get("code") in want,
    "after_turn": lambda want, _v, t: t >= want,
    "before_turn": lambda want, _v, t: t < want,
}


def matches(cond: dict | None, view: dict, turn: int) -> bool:
    return all(PREDICATES[k](want, view, turn) for k, want in (cond or {}).items())


def decide(rules: list[dict], kind: str, view: dict, turn: int) -> tuple[str, int | None]:
    """(누를 것, 맞은 규칙 번호). kind는 DB 종류예요."""
    for i, r in enumerate(rules or []):
        if db_kind(r["kind"]) == kind and matches(r.get("if"), view, turn):
            return r["do"], i
    return "leave", None


def rule_problems(rule: dict, kinds: set[str]) -> list[str]:
    """build_sets --check용: 규칙 모양 확인."""
    out = []
    if rule.get("kind") not in kinds:
        out.append(f"모르는 kind {rule.get('kind')}")
    if rule.get("do") not in DOS:
        out.append(f"모르는 do {rule.get('do')}")
    for k in rule.get("if") or {}:
        if k not in PREDICATES:
            out.append(f"모르는 조건 {k}")
    for x in (rule.get("if") or {}).get("weekday_in", []) + (rule.get("if") or {}).get(
        "wish_has_weekday", []
    ):
        if x not in WEEKDAY:
            out.append(f"모르는 요일 {x}")
    return out


# ---- 채점 ----


def _item(part: str, what: str, ok: bool, got=None, *, na: bool = False, why: str = "") -> dict:
    return {"part": part, "what": what, "ok": bool(ok), "na": na, "got": got, "why": why}


def _label(e: dict) -> str:
    return "/".join(str(e[k]) for k in ("vendor", "trade") if e.get(k)) or "*"


def _check_rows(part: str, specs: list[dict], rows: list[dict], extra) -> list[dict]:
    out = []
    for e in specs or []:
        mine = [
            r
            for r in rows
            if r["trade"] == e["trade"] and (e.get("vendor") is None or r["vendor"] == e["vendor"])
        ]
        good = [r for r in mine if r["status"] in e["status_in"] and extra(e, r)]
        ok = len(good) == e["count"] if "count" in e else bool(good)
        want = f"{e['count']}건" if "count" in e else "1건 이상"
        got = [
            {k: r.get(k) for k in ("status", "start", "quote_version") if r.get(k)} for r in mine
        ]
        out.append(_item("end", f"{part} {_label(e)} {'·'.join(e['status_in'])} {want}", ok, got))
    return out


def _deal_extra(e: dict, r: dict) -> bool:
    if e.get("start") and r.get("start") != e["start"]:
        return False
    if "pending_change" in e and bool(r.get("pending_change")) != bool(e["pending_change"]):
        return False
    return not ("quote_version" in e and r.get("quote_version") != e["quote_version"])


def _visit_extra(e: dict, r: dict) -> bool:
    return e.get("decline_code") is None or r.get("decline_code") == e["decline_code"]


def check_end(expected: dict, state: dict) -> list[dict]:
    """끝 상태 = 정답인지. state: visits · deals · actions · memory(None이면 기억 기능 없음)."""
    out = _check_rows("실측", expected.get("visits"), state["visits"], _visit_extra)
    out += _check_rows("확정", expected.get("deals"), state["deals"], _deal_extra)
    acts = expected.get("actions") or {}
    rows = state["actions"]

    def n(kind: str, status: str | None = None, code: str | None = None) -> int:
        k = db_kind(kind)
        return sum(
            1
            for a in rows
            if (k == "*" or a["kind"] == k)
            and (status is None or a["status"] == status)
            and (code is None or a.get("error_code") == code)
        )

    for status in ("executed", "rejected", "failed"):
        for e in acts.get(status) or []:
            got = n(e["kind"], status, e.get("error_code"))
            ok = got == e["count"] if "count" in e else got >= e.get("min", 1)
            want = f"={e['count']}" if "count" in e else f"≥{e.get('min', 1)}"
            out.append(_item("end", f"행동 {db_kind(e['kind'])} {status} {want}", ok, got))
    for k in acts.get("never_executed") or []:
        got = n(k, "executed")
        out.append(_item("end", f"행동 {db_kind(k)} 실행 0건", got == 0, got))
    for k, most in (acts.get("max_proposed") or {}).items():
        got = n(k)
        out.append(_item("end", f"행동 {db_kind(k)} 제안 ≤{most}", got <= most, got))
    if acts.get("none_without_approval"):
        bad = [
            a["kind"] for a in rows if a["status"] == "executed" and not a.get("approved_by_runner")
        ]
        out.append(_item("end", "승인 없이 실행 0건", not bad, bad))
    out += _check_memory(expected.get("memory") or {}, state.get("memory"), state.get("memory_why"))
    return out


def _check_memory(m: dict, memory: list[dict] | None, why: str | None = None) -> list[dict]:
    """why: 기억이 비었을 때 까닭(예: 무료 모드라 기억 뽑기 LLM이 꺼짐). 있어야 하는 기억이 없을 때 붙여요."""
    out = []
    if memory is None:
        for h in m.get("has") or []:
            out.append(_item("end", f"기억 {h['key']}", False, None, why="기억 기능 없음"))
        if m.get("absent_keys") or m.get("absent_values"):
            out.append(
                _item("end", "기억에 없어야 할 것", True, None, na=True, why="기억 기능 없음")
            )
        return out
    for h in m.get("has") or []:
        vals = [x.get("value") or "" for x in memory if x.get("key") == h["key"]]
        ok = any(any(c in v for c in h.get("contains") or [""]) for v in vals)
        out.append(
            _item("end", f"기억 {h['key']}", ok, vals, why="" if ok or memory else why or "")
        )
    for k in m.get("absent_keys") or []:
        got = [x for x in memory if x.get("key") == k]
        out.append(_item("end", f"기억 없음 {k}", not got, len(got)))
    blob = json.dumps(memory, ensure_ascii=False)
    for v in m.get("absent_values") or []:
        out.append(_item("end", f"기억 값 없음 '{v}'", v not in blob))
    return out


def check_process(checks: dict, run: dict) -> list[dict]:
    """대화 확인: 턴 도구 수 · 필수 · 금지 도구 · 보인 글 · 도구 입력 · 비용."""
    out = []
    turns = [t for t in run["turns"] if t.get("kind") == "say"]
    used = {name for t in turns for name in t.get("tools") or []}
    if "max_tool_calls_per_turn" in checks:
        most = max((t.get("tool_calls") or 0 for t in turns), default=0)
        cap = checks["max_tool_calls_per_turn"]
        out.append(_item("check", f"턴 도구 ≤{cap}", most <= cap, most))
    for t in checks.get("required_tools") or []:
        out.append(_item("check", f"필수 도구 {t}", t in used))
    for t in checks.get("forbidden_tools") or []:
        out.append(_item("check", f"금지 도구 {t}", t not in used))
    shown = run.get("shown") or ""
    for s in checks.get("no_text") or []:
        out.append(_item("check", f"글 없음 '{s}'", s not in shown))
    for rx in checks.get("no_regex") or []:
        m = re.search(rx, shown)
        out.append(_item("check", f"정규식 없음 {rx[:24]}", m is None, m[0] if m else None))
    args = json.dumps(run.get("tool_args") or [], ensure_ascii=False)
    for s in checks.get("no_tool_args") or []:
        out.append(_item("check", f"도구 입력 없음 '{s}'", s not in args))
    if "max_cost_usd" in checks:
        cost = run.get("cost_usd") or 0.0
        cap = checks["max_cost_usd"]
        out.append(_item("check", f"비용 ≤${cap}", cost <= cap, round(cost, 6)))
    for spec in checks.get("answer_has") or []:
        out += _answer_has(spec, turns)
    return out


def _answer_has(spec: dict, turns: list[dict]) -> list[dict]:
    """사용자가 when_said를 말한 턴의 답(보인 것: 글 · 카드)을 봐요. any가 있으면 그중 하나가, regex가 있으면
    그 꼴이 나와야 하고, no_cards 카드는 없어야 해요.
    예: '몰딩 교체는 언제 해요?' → 목공 순서 · 시기 답(목공은 자기 공정), 업체 추천 · 실측 카드 없음.
        '목공 업체도 추천해 주세요' → '아직 도배 업체만 연결돼요' 꼴의 짧은 안내."""
    said = [t for t in turns if spec["when_said"] in (t.get("say") or "")]
    want = [" · ".join(spec["any"])] if spec.get("any") else []
    want += ["정규식"] if spec.get("regex") else []
    what = f"'{spec['when_said']}' 답에 {' + '.join(want)}"
    if not said:
        return [_item("check", what, True, None, na=True, why="그 말을 하지 않음")]
    out = []
    for t in said:
        shown = t.get("shown") or ""
        ok = not spec.get("any") or any(x in shown for x in spec["any"])
        ok = ok and (not spec.get("regex") or re.search(spec["regex"], shown) is not None)
        out.append(_item("check", what, ok, t.get("text")))
        bad = sorted(set(t.get("cards") or []) & set(spec.get("no_cards") or []))
        if spec.get("no_cards"):
            out.append(_item("check", f"'{spec['when_said']}' 답에 카드 없음", not bad, bad))
    return out


def passed(items: list[dict]) -> bool:
    return all(i["ok"] for i in items if not i["na"])


def pass_hat(counts: list[int], n: int, k: int) -> float | None:
    """pass^k(τ-bench): 과제마다 C(c, k) / C(n, k)의 평균. c = n번 중 통과 수."""
    if not counts or k > n:
        return None
    return sum(math.comb(c, k) / math.comb(n, k) for c in counts) / len(counts)
