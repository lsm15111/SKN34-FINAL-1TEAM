"""카드 단추 누르기: 사람이 화면에서 하듯 카드에서 고른 것을 `context.choice` 계약 꼴로 보내요.

계약(backend/app/assistant/choices.py). 무료 모드는 이 단추를 눌러야 고객 승인 카드가 생겨요.
- 고객 `visit_request:v1,v2[,r1]` · `visit_slot:s1` · `vendor_confirm:m1` · `dates_accept:p1` · `delay_accept:p1`
- 업체 `window_answer:m1,w1` · `decline:m1,<full · out_of_area · other>` · `dates:d1,n1`

- 이름표는 이 대화에서 앞서 받은 카드(data의 ref 칸)에서 골라요. 같은 종류 카드가 여럿이면 나중 것이에요.
- 카드에 이름표가 없는 단추(공사 날짜 · 연기 수락 p# · 업체 기간 w# · 공사 날 n#)는 대화 이름표 표(Redis)에서
  찾고 ref_from='refs'로 적어요. 화면은 이 표를 볼 수 없어서 지금 화면으로는 못 누르는 단추예요(보고할 틈).
- 같은 종류 승인 카드가 이미 열려 있거나 실행됐으면 누르지 않아요(skip: 글 턴 · 먼저 말 걸기가 이미 만들었음).
- 고를 카드가 없으면 need_card로 돌려줘요. 러너가 ask 글(예: '공사 일정 보여 주세요')을 보낸 뒤 한 번 더 봐요.
"""

import re
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta

# 단추 종류 → (화면, 이름표가 있는 카드 종류)
KINDS: dict[str, tuple[str, str | None]] = {
    "visit_request": ("customer", "vendor_picks"),
    "visit_slot": ("customer", "visit_slots"),
    "vendor_confirm": ("customer", "quote_compare"),
    "dates_accept": ("customer", "schedule"),
    "delay_accept": ("customer", "schedule"),
    "window_answer": ("vendor", None),
    "decline": ("vendor", None),
    "dates": ("vendor", None),
}
# 이미 승인 카드가 있으면 누르지 않을 때 같이 보는 DB 행동 종류(날짜 수락은 서버가 연기 · 첫 날짜를 고른다)
SAME: dict[str, tuple[str, ...]] = {
    "dates_accept": ("dates_accept", "delay_accept"),
    "delay_accept": ("dates_accept", "delay_accept"),
}
LIVE = ("proposed", "approved", "executed")
OPEN = ("proposed", "approved")
# 요청(visit)이 대상인 고객 단추: vendor를 주면 그 업체 요청의 승인 카드만 봐요(먼저 말 걸기가 업체마다 만들어요)
PER_VISIT = ("visit_slot", "vendor_confirm")
DECLINE_CODES = ("full", "out_of_area", "other")
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
WEEKDAY_KO = "월화수목금토일"
HALF_KO = {"am": "오전", "pm": "오후"}
DECLINE_TEXT = {
    "out_of_area": "다니는 지역이 아니라 이 요청은 못 받아요",
    "full": "일정이 꽉 차서 이 요청은 못 받아요",
    "other": "이 요청은 못 받아요",
}
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


@dataclass
class Press:
    """단추 하나를 누른 결과. status: pressed(보냄) · skip(이미 승인 카드 있음) · missed(못 누름) · need_card."""

    kind: str
    status: str
    choice: str | None = None
    text: str | None = None
    card_id: str | None = None
    ref_from: str | None = None  # card(카드 data) · refs(대화 이름표 표, 화면은 못 봄)
    why: str | None = None
    picked: dict = field(default_factory=dict)

    def record(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v not in (None, {}, [])}


# ---- 작은 도움 ----


def cards_of(turns: list[dict]) -> list[dict]:
    """앞선 턴들이 받은 카드(card_id · kind · data), 받은 차례대로."""
    return [c for t in turns for c in t.get("card_data") or []]


def latest(cards: list[dict], kind: str, has: str | None = None) -> dict | None:
    """그 종류의 가장 나중 카드(has를 주면 data[has]가 비지 않은 것만)."""
    for c in reversed(cards):
        d = c.get("data")
        if c.get("kind") == kind and isinstance(d, dict) and (has is None or d.get(has)):
            return c
    return None


def weekday(iso: str) -> str:
    return WEEKDAYS[date.fromisoformat(str(iso)[:10]).weekday()]


def day_ko(iso: str, half: str | None = None) -> str:
    d = date.fromisoformat(str(iso)[:10])
    s = f"{d.month}월 {d.day}일({WEEKDAY_KO[d.weekday()]})"
    return f"{s} {HALF_KO.get(half or '', '')}".strip() if half else s


def ro(name: str) -> str:
    """'마루와벽' → '마루와벽으로', '결도배' → '결도배로'(받침 · ㄹ받침)."""
    last = (name or " ")[-1]
    code = ord(last) - 0xAC00
    if 0 <= code < 11172 and code % 28 not in (0, 8):
        return f"{name}으로"
    return f"{name}로"


def has_weekday(start: str, end: str, days: list[str]) -> bool:
    a, b = date.fromisoformat(str(start)[:10]), date.fromisoformat(str(end)[:10])
    span = min((b - a).days, 40)
    return any(WEEKDAYS[(a + timedelta(days=i)).weekday()] in days for i in range(span + 1))


def slot_ok(s: dict, rule: dict, name: str | None) -> bool:
    if name and s.get("vendor_name") != name:
        return False
    if rule.get("weekday_in") and weekday(s["day"]) not in rule["weekday_in"]:
        return False
    return not (rule.get("half_in") and s.get("half") not in rule["half_in"])


def window_ok(w: dict, rule: dict) -> bool:
    if rule.get("start_to") and str(w.get("start")) > rule["start_to"]:
        return False
    return not (rule.get("end_from") and str(w.get("end")) < rule["end_from"])


def name_of(world, ref: str | None) -> str | None:
    if not ref:
        return None
    v = world.vendors.get(ref)
    return v["name"] if v else None


def ref_of(table: dict, kind: str, **match) -> str | None:
    """대화 이름표 표에서 그 종류 · 값이 맞는 이름표(가장 나중 것)."""
    got = None
    for ref, it in (table or {}).items():
        if it.get("kind") == kind and all(str(it.get(k)) == str(v) for k, v in match.items()):
            got = ref
    return got


# ---- 고르기 ----


def plan(spec: dict, turns: list[dict], world, live: set[str] | dict[str, set[str]], table: dict,
         visit_id: str | None = None) -> Press:  # fmt: skip
    """press 걸음 → 보낼 고른 것. table: 대화 이름표 표.
    live: 상태별 행동 종류(DB 이름) {status: {kind}} — 러너가 이 단추의 대상(업체 요청)으로 걸러 줘요.
    집합만 주면 열림 · 실행 모두로 봐요. again이면 열린 카드만 막아요."""
    kind = spec["kind"]
    if not isinstance(live, dict):
        live = {"proposed": set(live), "executed": set(live)}
    block = OPEN if spec.get("again") else LIVE
    kinds = {k for st in block for k in live.get(st, set())}
    if any(k in kinds for k in SAME.get(kind, (kind,))):
        return Press(kind, "skip", why="같은 종류 승인 카드가 이미 있어요")
    cards = cards_of(turns)
    fn = PICKERS[kind]
    return fn(spec, cards, world, table, visit_id)


def _visit_request(spec, cards, world, table, visit_id) -> Press:
    c = latest(cards, "vendor_picks", "picks")
    if c is None:
        return Press("visit_request", "need_card", why="업체 추천 카드가 없어요")
    picks = c["data"]["picks"]
    if spec.get("vendors"):
        want = [name_of(world, r) for r in spec["vendors"]]
        chosen = [p for p in picks if p.get("name") in want]
    else:
        chosen = picks[: int(spec.get("top") or 2)]
    if not chosen:
        return Press("visit_request", "missed", why="고를 업체가 카드에 없어요")
    args = [p["ref"] for p in chosen]
    picked: dict = {"vendors": [p.get("name") for p in chosen]}
    if spec.get("wish"):
        wc = latest(cards, "visit_slots", "wishes")
        w = next(
            (
                x
                for x in (wc["data"]["wishes"] if wc else [])
                if has_weekday(x["start"], x["end"], spec["wish"].get("weekday_in") or WEEKDAYS)
            ),
            None,
        )
        if w is not None:
            args.append(w["ref"])
            picked["wish"] = f"{w['start']}~{w['end']}"
        else:
            picked["wish"] = "희망 기간 카드 없음(서버 기본 기간)"
    names = " · ".join(p.get("name") or "" for p in chosen)
    return Press("visit_request", "pressed", choice=f"visit_request:{','.join(args)}",
                 text=f"{names}에 요청할래요", card_id=c.get("card_id"), ref_from="card",
                 picked=picked)  # fmt: skip


def _visit_slot(spec, cards, world, table, visit_id) -> Press:
    """반나절 후보 카드는 업체(요청)마다 하나라, 나중 카드부터 규칙에 맞는 후보를 찾아요."""
    slots = [
        c
        for c in reversed(cards)
        if c.get("kind") == "visit_slots" and (c.get("data") or {}).get("candidates")
    ]
    if not slots:
        return Press("visit_slot", "need_card", why="반나절 후보 카드가 없어요")
    name = name_of(world, spec.get("vendor"))
    rule = spec.get("slot") or {}
    c, s = next(
        ((c, x) for c in slots for x in c["data"]["candidates"] if slot_ok(x, rule, name)),
        (slots[0], None),
    )
    if s is None:
        return Press("visit_slot", "missed", why="규칙에 맞는 반나절 후보가 카드에 없어요")
    return Press("visit_slot", "pressed", choice=f"visit_slot:{s['ref']}",
                 text=f"{ro(day_ko(s['day'], s['half']))} 할래요", card_id=c.get("card_id"),
                 ref_from="card", picked={"vendor": s.get("vendor_name"), "day": s["day"],
                                          "half": s.get("half")})  # fmt: skip


def _vendor_confirm(spec, cards, world, table, visit_id) -> Press:
    c = latest(cards, "quote_compare", "cols")
    if c is None:
        return Press("vendor_confirm", "need_card", why="견적서 비교 카드가 없어요")
    name = name_of(world, spec.get("vendor"))
    col = next(
        (
            x
            for x in c["data"]["cols"]
            if x.get("state") == "quoted" and (name is None or x.get("vendor_name") == name)
        ),
        None,
    )
    if col is None:
        return Press("vendor_confirm", "missed", why="확정할 견적서가 카드에 없어요")
    return Press("vendor_confirm", "pressed", choice=f"vendor_confirm:{col['ref']}",
                 text=f"{ro(col.get('vendor_name') or '')} 확정할래요", card_id=c.get("card_id"),
                 ref_from="card", picked={"vendor": col.get("vendor_name"),
                                          "version": col.get("version")})  # fmt: skip


def _dates_accept(spec, cards, world, table, visit_id, kind: str = "dates_accept") -> Press:
    c = latest(cards, "schedule")
    if c is None or (c.get("data") or {}).get("phase") != "dates":
        return Press(kind, "need_card", why="수락할 공사 날짜 카드가 없어요")
    pid = next(iter(UUID_RE.findall(c.get("card_id") or "")), None)
    ref, src = _card_ref(c.get("data"), "p"), "card"
    if (
        ref is None and pid
    ):  # 카드 data에 없으면 card_id(dates-{제안 id})로 대화 이름표 표에서 찾아요
        ref, src = ref_of(table, "proposal", id=pid), "refs"
    if ref is None:
        return Press(kind, "missed", why="공사 날짜 카드에 이름표(p#)가 없어요")
    text = "바뀐 날짜로 할래요" if kind == "delay_accept" else "이 공사 날짜로 할래요"
    return Press(kind, "pressed", choice=f"{kind}:{ref}", text=text, card_id=c.get("card_id"),
                 ref_from=src, picked={"start": c["data"].get("start"),
                                       "end": c["data"].get("end")})  # fmt: skip


def _delay_accept(spec, cards, world, table, visit_id) -> Press:
    return _dates_accept(spec, cards, world, table, visit_id, "delay_accept")


def _decline(spec, cards, world, table, visit_id) -> Press:
    code = spec.get("code") or "other"
    if code not in DECLINE_CODES:
        return Press("decline", "missed", why=f"모르는 까닭 {code}")
    if not visit_id:
        return Press("decline", "missed", why="보던 요청이 없어요")
    return Press("decline", "pressed", choice=f"decline:{code}", text=DECLINE_TEXT[code],
                 ref_from="card", picked={"code": code})  # fmt: skip


def _window_answer(spec, cards, world, table, visit_id) -> Press:
    rule = spec.get("window") or {}
    refs = [
        r
        for r, it in (table or {}).items()
        if it.get("kind") == "window"
        and str(it.get("visit_id")) == str(visit_id)
        and window_ok(it, rule)
    ]
    if not refs:
        return Press("window_answer", "missed", why="빈 기간 이름표(w#)가 카드에 없어요")
    w = table[refs[-1]]
    return Press("window_answer", "pressed", choice=f"window_answer:{refs[-1]}",
                 text="이 기간으로 답할래요", ref_from="refs",
                 picked={"start": w.get("start"), "end": w.get("end")})  # fmt: skip


def _dates(spec, cards, world, table, visit_id) -> Press:
    start = (spec.get("days") or {}).get("start")
    refs = [
        r
        for r, it in (table or {}).items()
        if it.get("kind") == "days" and (start is None or str(it.get("start")) == start)
    ]
    if not refs:
        return Press("dates", "missed", why="공사 날 후보 이름표(n#)가 카드에 없어요")
    n = table[refs[-1]]
    return Press("dates", "pressed", choice=f"dates:{refs[-1]}", text="이 날짜로 보낼래요",
                 ref_from="refs", picked={"start": n.get("start"), "end": n.get("end")})  # fmt: skip


def _card_ref(data, prefix: str) -> str | None:
    """카드 data 안의 그 머리글자 이름표(가장 앞 것). 화면이 볼 수 있는 이름표예요."""
    if isinstance(data, dict):
        r = data.get("ref")
        if isinstance(r, str) and r[:1] == prefix and r[1:].isdigit():
            return r
        for v in data.values():
            got = _card_ref(v, prefix)
            if got:
                return got
    elif isinstance(data, list):
        for v in data:
            got = _card_ref(v, prefix)
            if got:
                return got
    return None


PICKERS = {
    "visit_request": _visit_request,
    "visit_slot": _visit_slot,
    "vendor_confirm": _vendor_confirm,
    "dates_accept": _dates_accept,
    "delay_accept": _delay_accept,
    "window_answer": _window_answer,
    "decline": _decline,
    "dates": _dates,
}
