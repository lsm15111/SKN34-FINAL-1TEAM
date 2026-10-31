"""라우터 평가 사례 약 5,000개를 만든다. 레지스트리 카탈로그(공정 칸 · 선택지 · 범위)로 고객 말과 기대를 만들고 시드를 고정한다.

- 범주 20개 × 249개 (dev 166 · held-out 83): 공통 칸(면적 · 면적 기준 · 거주 · 발코니 · 준공 연도),
  공정 칸(하나 고르기 · 여러 개 고르기 정하기/더하기/빼기 · 숫자 · 모르겠어요 · 두 칸), 공통 + 공정 칸,
  질문(카드 공정 · 카드에 없는 공정), 바꾸기 + 질문, 공정 더하기(+ 그 공정 칸 · 두 공정 한꺼번에) ·
  빼기(+ 남은 공정 칸) · 묻기만 함(더하지 않고 그 공정 전문가에게), 업체 소개 · 견적 요청('가견적 받기' 안내),
  범위 밖, 안 바꿈(맞장구 · 이미 같은 값 · 이미 있는 공정 더하기 · 하나뿐인 공정 빼기: 상담 코드가 남긴다)
- 범주 안에서 목표(어느 칸 · 어떤 값 · 말하는 꼴)와 카드 공정 묶음은 조합마다 고르게, 카드 상태(덜 참 · 다 참) ·
  앞 대화 · 잡음은 값마다 고르게 채운다
- 고객 말은 phrases.py 조각으로 만든다. 묶음마다 조각 3개 중 1개는 held-out 전용이라 두 나눔이 같은 조각을 쓰지 않는다
- 기대는 모범 출력(RouterOut)을 상담 코드(apply_route · normalize)에 넣어 바뀐 칸으로 만든다 (스펙이 버리는 값은 기대에도 없다).
  같이 쓰는 칸(share)은 고객이 공정을 집어 말하지 않으면 같은 칸을 모두 바꾸는 것이 기대다.
  범위 · 공정 더하기 기대는 라우터 v5 프롬프트(consult_v5.md)를 따른다
- 근사 중복: 나눔 · 범주마다 고객 말 글자 3-gram Jaccard 0.8 이상이면 다시 뽑는다 (수는 답이라 그대로 둔다)

실행 (저장소 루트에서): cd backend && uv run python ../evaluation/router/make_cases.py
→ evaluation/router/cases_5k.jsonl (커밋 안 함) · sample_100.jsonl (커밋)
"""

import itertools
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

from app.agent.schemas import RouterOut
from app.consult import service
from app.consult.trades import REGISTRY
from app.consult.trades.base import UNKNOWN, FieldSpec
from evaluation.common import gen, house, trades
from evaluation.router import phrases as P
from evaluation.router.score import apply, effect
from evaluation.scorers.trade_plan import choice_words
from evaluation.scorers.witness import josa

TOTAL = 5000
TRIES = 60  # 근사 중복을 피해 다시 뽑는 횟수
FULL = HERE / "cases_5k.jsonl"
SAMPLE = HERE / "sample_100.jsonl"
CATEGORIES = (
    "common.area",
    "common.basis",
    "common.occupied",
    "common.balcony",
    "common.year",
    "field.choice",
    "field.multi",
    "field.count",
    "field.unknown",
    "field.two",
    "mixed",
    "question",
    "question.other",
    "change.question",
    "trade.add",
    "trade.remove",
    "trade.ask",
    "vendor",
    "out_of_scope",
    "no_change",
)
KINDS = ("choice", "multi", "count", "unknown")
CHANGED = "알겠어요. 바꾼 값으로 다시 계산했어요."
ADDED = "알겠어요. 더한 공정의 칸은 화면에서 골라 주세요."
VENDOR = "업체는 결과 화면의 '가견적 받기'에서 볼 수 있어요."
KEEP_LAST = "공정은 하나는 남아 있어야 해서 그대로 뒀어요."  # 하나뿐인 공정을 빼 달라고 할 때
VENDOR_WORDS = ["가견적"]  # 업체 소개 · 견적 요청 답에 꼭 있어야 할 말
PRE = gen.Fragments(
    {
        "pre": [
            "", "아 그리고 ", "참, ", "음 ", "그럼 ", "근데 ", "혹시 ", "네 그리고 ", "아 ",
            "그리고 ", "저기 ", "아 맞다 ", "", "일단 ", "그러면 ", "아 참 ", "말씀드리면 ",
            "음 그러니까 ", "제가 깜빡했는데 ", "추가로 ", "그건 그렇고 ",
        ]
    }
)  # fmt: skip
NOISE = ("partial_space", "add_space", "ceiling_typo", "spelling", "yeo", "informal", "tail")


class Retry(Exception):
    """이 설계로는 사례를 못 만든다 (다시 뽑는다)"""


# ---------------------------------------------------------------- 말 만들기
def eulo(word: str) -> str:
    ch = word.strip()[-1]
    if not "가" <= ch <= "힣":
        return "으로"
    jong = (ord(ch) - 0xAC00) % 28
    return "으로" if jong and jong != 8 else "로"  # ㄹ 받침은 '로'


def fill(tpl: str, x: str = "", **kw) -> str:
    j = {"은": "은는", "을": "을를", "이": "이가", "과": "과와"}
    marks = {k: josa(x, v) for k, v in j.items()} if x else dict.fromkeys(j, "")
    marks |= {
        "랑": ("이랑" if josa(x, "01") == "0" else "랑") if x else "",
        "으로": eulo(x) if x else "",
    }
    return tpl.format(x=x, **marks, **kw)


def end(s: str) -> str:
    return s if s.endswith(("?", ".", "!")) else s + "."


def join_ko(words: list[str]) -> str:
    if len(words) == 2:
        a, b = words
        return f"{a}{'이랑' if josa(a, '01') == '0' else '랑'} {b}"
    return ", ".join(words)


class Talk:
    """조각 고르기 (나눔 지킴, 쓴 조각은 used에 남김)"""

    def __init__(self, r, split: str) -> None:
        self.r, self.split, self.used = r, split, []

    def pick(self, name: str) -> str:
        if name in P.BANK.table:
            return P.BANK.pick(self.r, name, self.split, self.used)
        raise KeyError(name)

    def pre(self) -> str:
        return PRE.pick(self.r, "pre", self.split, self.used)


def plain(label: str) -> str:
    """화면 말에서 괄호 설명을 뗀다 ('덧방 (위에 덧붙이기)' → '덧방')"""
    return re.sub(r"\s*\(.*?\)", "", label).strip()


def noun_options(trade: str, f: FieldSpec) -> dict[str, list[str]]:
    """여러 개 고르는 칸의 선택지 → 고객이 부르는 말 (phrases.MULTI_NOUN, 없으면 화면 말)"""
    got = P.MULTI_NOUN.get((trade, f.key))
    return got or {v: ws for v, ws in choice_words(f, (REGISTRY[trade].label,)).items()}


def field_phrase(t: Talk, trade: str, f: FieldSpec, value) -> str:
    """칸 값으로 정하는 말. 묶음이 없으면 스펙 화면 말로 만든다 (새 공정: 칸 이름을 붙여 어느 칸인지 드러낸다).
    같이 쓰는 칸(share)은 공정을 집지 않는 SHARE 말을 쓴다 (기대가 같은 칸을 모두 바꾸는 것이라서)"""
    r = t.r
    head = f"{f.label}{josa(f.label, '은는')}"
    base = f"share:{f.share}" if f.share else f"field:{trade}:{f.key}"
    if f.kind == "count" and value != UNKNOWN:
        key = f"{base}:count"
        if key in P.BANK.table:
            return fill(t.pick(key), c=value)
        unit = f.unit or "개"
        return f"{head} {value}{unit}{'이에요' if josa(unit, '01') == '0' else '예요'}"
    key = f"{base}:{value}"
    if key in P.BANK.table:
        return t.pick(key)
    if value == UNKNOWN:
        return r.choice((f"{head} 잘 모르겠어요", f"{head} 몰라요"))
    word = plain(next(c.label for c in f.choices if c.value == value))
    if word.endswith("요"):
        return f"{head} {word}"
    return r.choice((f"{head} {word}{eulo(word)} 할게요", f"{head} {word}{eulo(word)} 해 주세요"))


def multi_phrase(
    t: Talk, trade: str, f: FieldSpec, op: str, values: list[str], among: list[str]
) -> str:
    """여러 개 고르는 칸을 정하거나 하나 더하고 빼는 말. 같은 말이 카드의 다른 공정 칸에도 있으면
    어느 공정인지 모호하니 다시 뽑는다 (예: 목공 · 필름의 '몰딩')"""
    names = noun_options(trade, f)
    words = [t.r.choice(names[v]) for v in values]
    others = {
        w
        for o in among
        if o != trade
        for g in REGISTRY[o].fields
        if g.kind == "multi"
        for ws in noun_options(o, g).values()
        for w in ws
    }
    if any(w in o or o in w for w in words for o in others):
        raise Retry
    return fill(t.pick(f"multi:{op}"), x=join_ko(words), t=trade_noun(t.r, trade))


def trade_noun(r, trade: str) -> str:
    """고객이 공정을 부르는 말 (phrases.TRADE_NOUN, 없으면 화면 말)"""
    return r.choice(P.TRADE_NOUN.get(trade) or [REGISTRY[trade].label])


def question_phrase(t: Talk, trade: str) -> str:
    key = f"question:{trade}"
    if key in P.BANK.table:
        return t.pick(key)
    sp = REGISTRY[trade]
    lab = sp.label
    pool = [
        f"{lab} 공사는 어떻게 진행돼요?",
        f"{lab} 할 때 주의할 점이 있어요?",
        f"{lab}{josa(lab, '은는')} 실측 때 뭘 봐요?",
    ]
    for f in sp.fields:
        if len(f.choices) >= 2:
            a, b = plain(f.choices[0].label), plain(f.choices[1].label)
            pool.append(f"{lab} {a}{'이랑' if josa(a, '01') == '0' else '랑'} {b} 차이가 뭐예요?")
    return t.r.choice(pool)


# ---------------------------------------------------------------- 카드
def set_field(r, card: dict, trade: str, f: FieldSpec, ok) -> None:
    """그 칸이 물어지고(when) 지금 값이 ok(값 또는 None)를 지키게 카드 값을 맞춘다.
    먼저 다른 칸은 그대로 두고 이 칸만 바꿔 보고, 조건이 안 맞으면 그 공정 값을 다시 뽑는다."""
    sp = REGISTRY[trade]
    cur = dict(card["values"].get(trade, {}))
    for i in range(200):
        vals = dict(cur) if i == 0 else trades.random_values(r, sp, keep=0.8)
        if not f.asks(vals):
            continue
        opts = [None, *[o for o in trades.options(f)]]
        good = [o for o in opts if ok(o)]
        if not good:
            continue
        v = r.choice(good)
        if v is None:
            vals.pop(f.key, None)
        else:
            vals[f.key] = f.norm(v)
        if sp.relevant(vals) != vals:
            continue
        card["values"][trade] = vals
        card["to_check"] = [x for x in card["to_check"] if not x.startswith(f"{trade}.")]
        return
    raise Retry


def norm_card(card: dict) -> dict:
    return trades.card({"card": card}).model_dump(mode="json")


# ---------------------------------------------------------------- 목표 (범주별)
def targets(kind: str) -> list[tuple[str, FieldSpec]]:
    return [(t, f) for t, sp in REGISTRY.items() for f in sp.fields if f.kind == kind]


def unknown_targets() -> list[tuple[str, FieldSpec]]:
    return [(t, f) for t, sp in REGISTRY.items() for f in sp.fields if f.unknown is not None]


def plan_change(
    r, t: Talk, card: dict, kind: str, among: list[str] | None = None
) -> tuple[str, list[dict]]:
    """카드 공정 칸 하나를 바꾸는 말 + 모범 변경. kind: choice · multi · count · unknown.
    among: 바꿀 공정 후보이자 같이 쓰는 칸을 맞출 공정 (기본: 카드 공정)"""
    among = card["trades"] if among is None else among
    pool = [(tr, f) for tr, f in (unknown_targets() if kind == "unknown" else targets(kind))]
    pool = [(tr, f) for tr, f in pool if tr in among]
    if not pool:
        raise Retry
    trade, f = r.choice(pool)
    if kind == "choice":
        value = r.choice(f.values)
        set_field(r, card, trade, f, lambda o: o != value)
        return field_phrase(t, trade, f, value), _changes(among, trade, f, "set", value)
    if kind == "count":
        value = r.randint(f.min, min(f.max, f.min + 7))
        set_field(r, card, trade, f, lambda o: o != value)
        return field_phrase(t, trade, f, value), _changes(among, trade, f, "set", str(value))
    if kind == "unknown":
        set_field(r, card, trade, f, lambda o: True)
        return field_phrase(t, trade, f, UNKNOWN), _changes(among, trade, f, "set", UNKNOWN)
    op = r.choice(("set", "add", "remove"))
    vals = list(f.values)
    if op == "set":
        want = r.choice(trades.subsets(f))
        set_field(r, card, trade, f, lambda o: o != want)
        return multi_phrase(t, trade, f, "set", want, among), _changes(
            among, trade, f, "set", ",".join(want)
        )
    x = r.choice(vals)
    if op == "add":
        set_field(r, card, trade, f, lambda o: o is None or (x not in o and len(o) < f.max))
    else:
        set_field(r, card, trade, f, lambda o: o is not None and x in o and len(o) > max(f.min, 1))
    return multi_phrase(t, trade, f, op, [x], among), _changes(among, trade, f, op, x)


def add_change(r, t: Talk, trade: str, after: list[str]) -> tuple[str, list[dict]]:
    """이번에 더하는 공정의 칸 하나를 정하는 말 + 모범 변경 (그 공정은 아직 값이 없다)"""
    pool = [
        f for f in REGISTRY[trade].fields if f.kind in ("choice", "count", "multi") and f.asks({})
    ]
    if not pool:
        raise Retry
    f = r.choice(pool)
    if f.kind == "choice":
        value = r.choice(f.values)
        return field_phrase(t, trade, f, value), _changes(after, trade, f, "set", value)
    if f.kind == "count":
        n = r.randint(f.min, min(f.max, f.min + 7))
        return field_phrase(t, trade, f, n), _changes(after, trade, f, "set", str(n))
    want = r.choice(trades.subsets(f))
    text = multi_phrase(t, trade, f, "set", want, after)
    return text, _changes(after, trade, f, "set", ",".join(want))


def _changes(among: list[str], trade: str, f: FieldSpec, op: str, value: str) -> list[dict]:
    """같이 쓰는 칸(share)이면 공정들의 같은 칸을 모두 바꾸는 것이 기대 (고객이 공정을 집어 말하지 않음)"""
    out = [{"field": f"{trade}.{f.key}", "op": op, "value": value}]
    if f.share and op == "set":
        for other in among:
            g = next((g for g in REGISTRY[other].fields if g.share == f.share), None)
            if other != trade and g is not None:
                out.append({"field": f"{other}.{g.key}", "op": "set", "value": value})
    return out


def common_phrase(r, t: Talk, card: dict, form: str) -> tuple[str, dict]:
    """공통 칸 말 + 모범 출력 값"""
    n = r.choice((r.randint(15, 60), r.choice((18, 24, 25, 32, 33, 34, 43, 49))))
    m = r.choice((round(r.uniform(39, 198), 1), r.choice((59, 74, 84, 99, 114))))
    m = int(m) if float(m).is_integer() else m
    if form == "area":
        sub = r.choice(("py", "py_supply", "py_excl", "m2", "m2_excl", "m2_supply", "py_unknown"))
        basis = {"supply": "supply", "excl": "exclusive", "unknown": "unknown"}.get(
            sub.split("_")[-1]
        )
        text = fill(t.pick(f"common:area_{sub}"), n=n, m=m)
        out = {"pyeong": n} if sub.startswith("py") else {"area_m2": m}
        return text, out | ({"area_basis": basis} if basis else {})
    if form == "basis":
        sub = r.choice(("supply", "excl", "unknown"))
        basis = {"supply": "supply", "excl": "exclusive", "unknown": "unknown"}[sub]
        cur = "unknown" if "area_basis" in card["to_check"] else card["area_basis"]
        if cur == basis:
            card["area_basis"] = "exclusive" if basis == "supply" else "supply"
            card["to_check"] = [x for x in card["to_check"] if x != "area_basis"]
        if card["area_m2"] is None:
            card["area_m2"] = house.area(r, "supply", r.choice(house.SIZES))["area_m2"]
            card["area_basis"] = card["area_basis"] or (
                "exclusive" if basis == "supply" else "supply"
            )
        return t.pick(f"common:basis_{sub}"), {"area_basis": basis}
    if form == "occupied":
        v = r.choice((True, False))
        card["occupied"] = r.choice((not v, None))
        return t.pick(f"common:occupied_{'yes' if v else 'no'}"), {"occupied": v}
    if form == "balcony":
        v = r.choice((True, False))
        card["balcony_ext"] = not v
        return t.pick(f"common:balcony_{'yes' if v else 'no'}"), {"balcony_ext": v}
    y = r.randint(1985, 2024)
    if card["built_year"] == y:
        card["built_year"] = None
    return fill(t.pick("common:year"), y=y), {"built_year": y}


def build_case(r, cat: str, row: dict) -> tuple[dict, dict, list[str]]:
    """(input, 모범 출력, 꼭 바뀌어야 할 공정 칸)"""
    t = Talk(r, row["split"])
    picked = row["trades"].split("+")
    form = row.get("form", "")
    if cat == "question.other" and set(picked) >= set(trades.registered()):
        if len(picked) < 2:
            raise Retry
        picked.remove(r.choice(picked))  # 카드에 없는 공정이 있어야 하는 범주
    if form == "two":  # 카드에 없는 공정이 둘 이상 있어야 한다
        while len(picked) > 1 and len(trades.registered()) - len(picked) < 2:
            picked.remove(r.choice(picked))
    if form == "last_trade":  # 공정이 하나뿐인 카드
        picked = [r.choice(picked)]
    card = house.random_card(r, picked, row["state"] == "full")
    out: dict = {
        "changes": [],
        "questions": [],
        "out_of_scope": False,
        "trades_add": [],
        "trades_remove": [],
    }
    said: list[str] = []
    main: list[str] = []
    if cat.startswith("common."):
        kind = cat.split(".")[1]
        if kind == "year" and form == "age":
            said.append(fill(t.pick("common:year_age"), k=r.randint(3, 35)))
        else:
            text, vals = common_phrase(r, t, card, kind)
            said.append(text)
            out |= vals
    elif cat in ("field.choice", "field.multi", "field.count", "field.unknown"):
        text, ch = plan_change(r, t, card, cat.split(".")[1])
        said.append(text)
        out["changes"] += ch
        main.append(ch[0]["field"])
    elif cat == "field.two":
        kinds = r.sample(["choice", "multi", "count", "unknown"], 2)
        for kind in kinds:
            text, ch = plan_change(r, t, card, kind)
            if {c["field"] for c in ch} & {c["field"] for c in out["changes"]}:
                raise Retry
            said.append(text)
            out["changes"] += ch
            main.append(ch[0]["field"])
    elif cat == "mixed":
        text, vals = common_phrase(r, t, card, form)
        said.append(text)
        out |= vals
        text, ch = plan_change(r, t, card, r.choice(("choice", "multi", "count", "unknown")))
        said.append(text)
        out["changes"] += ch
        main.append(ch[0]["field"])
    elif cat in ("question", "question.other"):
        others = [k for k in trades.registered() if k not in picked]
        pool = picked if cat == "question" else others
        if not pool:
            raise Retry
        trade = r.choice(pool)
        q = question_phrase(t, trade)
        said.append(q)
        out["questions"].append({"trade": trade, "question": q})
    elif cat == "change.question":
        text, ch = plan_change(r, t, card, r.choice(("choice", "multi", "count", "unknown")))
        trade = ch[0]["field"].split(".")[0] if form == "same" else r.choice(trades.registered())
        q = question_phrase(t, trade)
        said += [text, q]
        out["changes"] += ch
        out["questions"].append({"trade": trade, "question": q})
        main.append(ch[0]["field"])
    elif cat == "trade.add":  # 공정을 더한다 (+ 그 공정 칸 하나, 또는 두 공정을 한꺼번에)
        others = [k for k in trades.registered() if k not in picked]
        xs = r.sample(others, 2 if form == "two" else 1) if len(others) >= 2 else others
        if not xs or (form == "two" and len(xs) < 2):
            raise Retry
        x = xs[0]
        said.append(fill(t.pick("trade:add"), x=join_ko([trade_noun(r, k) for k in xs])))
        out["trades_add"] += xs
        main.append("trades")
        if form == "with_field":
            after = [k for k in trades.registered() if k in picked or k == x]
            text, ch = add_change(r, t, x, after)
            said.append(text)
            out["changes"] += ch
            main.append(ch[0]["field"])
    elif cat == "trade.remove":  # 공정을 뺀다 (+ 남은 공정 칸 하나)
        if len(picked) < 2:
            raise Retry
        x = r.choice(picked)
        said.append(fill(t.pick("trade:remove"), x=trade_noun(r, x)))
        out["trades_remove"].append(x)
        main.append("trades")
        if form == "with_field":
            rest = [k for k in picked if k != x]
            text, ch = plan_change(r, t, card, r.choice(KINDS), among=rest)
            said.append(text)
            out["changes"] += ch
            main.append(ch[0]["field"])
    elif cat == "trade.ask":  # 묻기만 함 → 더하지 않고 그 공정 전문가에게 넘긴다
        others = [k for k in trades.registered() if k not in picked]
        if not others:
            raise Retry
        x = r.choice(others)
        q = fill(t.pick("trade:ask"), x=trade_noun(r, x))
        said.append(q)
        out["questions"].append({"trade": x, "question": end(q)})
    elif cat == "vendor":  # 업체 소개 · 견적 요청 → 범위 안, '가견적 받기' 안내
        said.append(t.pick("common:vendor"))
    elif cat == "out_of_scope":
        said.append(t.pick("common:out_of_scope"))
        out["out_of_scope"] = True
    elif form == "chitchat":
        said.append(t.pick("common:chitchat"))
    elif form == "same_value":  # 이미 같은 값 → 넣지 않는 것이 기대
        pool = [(tr, f) for tr, f in targets("choice") if tr in picked]
        if not pool:
            raise Retry
        trade, f = r.choice(pool)
        value = r.choice(f.values)
        set_field(r, card, trade, f, lambda o: o == value)
        said.append(field_phrase(t, trade, f, value))
    elif form == "last_trade":  # 하나 남은 공정을 빼 달라는 말 → 상담 코드가 남긴다 (바뀌지 않음)
        said.append(fill(t.pick("trade:remove"), x=trade_noun(r, picked[0])))
        out["reply"] = KEEP_LAST
    else:  # already: 이미 카드에 있는 공정을 하겠다는 말 → 더하지 않는 것이 기대
        said.append(fill(t.pick("trade:add"), x=trade_noun(r, r.choice(picked))))
    card = norm_card(card)
    text = " ".join(end(s) for s in said)
    text = t.pre() + text
    if row["noise"] == "noisy":
        text, _ = gen.noisy(text, r, k=1, ops=NOISE)
    history = []
    if row["history"] == "some":
        history = [
            {"role": "user", "text": end(t.pick("common:history_user"))},
            {"role": "assistant", "text": t.pick("common:history_bot")},
        ]
    ideal = ideal_out(out, cat)
    return {"card": card, "history": history, "message": text, "tpl": t.used}, ideal, main


def ideal_out(out: dict, cat: str) -> dict:
    """모범 출력: 공통 칸은 말한 것만, 질문을 넘기면 답은 비우고, 범위 밖이면 공정만 상담한다고 말한다.
    업체 소개 · 견적 요청이면 '가견적 받기'를, 공정을 더했으면 그 칸을 화면에서 고르라고 말한다 (v5)"""
    d = dict.fromkeys(("pyeong", "area_m2", "area_basis", "occupied", "balcony_ext", "built_year"))
    d |= {k: v for k, v in out.items() if k in d}
    if out.get("reply"):
        reply = out["reply"]
    elif out["questions"]:
        reply = ""
    elif cat == "out_of_scope":
        reply = service.OUT_OF_SCOPE
    elif cat == "vendor":
        reply = VENDOR
    elif out["trades_add"]:
        reply = ADDED
    elif out["changes"] or out["trades_remove"] or any(v is not None for v in d.values()):
        reply = CHANGED
    else:
        reply = "네, 알겠어요."
    return d | {
        "changes": out["changes"],
        "questions": out["questions"],
        "out_of_scope": out["out_of_scope"],
        "trades_add": out["trades_add"],
        "trades_remove": out["trades_remove"],
        "reply": reply,
    }


# ---------------------------------------------------------------- 설계 · 생성
def trade_sets() -> list[str]:
    keys = trades.registered()
    sets = [c for k in range(1, min(3, len(keys)) + 1) for c in itertools.combinations(keys, k)]
    return ["+".join(s) for s in sets]


def feasible(cat: str, picked: list[str]) -> bool:
    """이 범주를 이 카드 공정 묶음으로 만들 수 있는지 (그 종류 칸이 있는 공정이 카드에 있는지)"""
    kinds = {
        "field.choice": ("choice",),
        "field.multi": ("multi",),
        "field.count": ("count",),
    }.get(cat)
    fields = [f for t in picked for f in REGISTRY[t].fields]
    if kinds:
        return any(f.kind in kinds for f in fields)
    if cat == "field.unknown":
        return any(f.unknown is not None for f in fields)
    if cat == "field.two":
        return len(fields) >= 2
    if cat == "question.other":
        return len(picked) < len(trades.registered()) or len(picked) > 1
    if cat in ("trade.add", "trade.ask"):
        return len(picked) < len(trades.registered())
    if cat == "trade.remove":
        return len(picked) >= 2
    return bool(fields)


def design(cat: str) -> tuple[dict, dict]:
    """(격자 칸, 고르게 채울 칸)"""
    sets = [s for s in trade_sets() if feasible(cat, s.split("+"))]
    core: dict = {"trades": tuple(sets)}
    if cat == "common.year":
        core["form"] = ("year", "year", "age")
    elif cat == "mixed":
        core["form"] = ("area", "basis", "occupied", "balcony", "year")
    elif cat == "change.question":
        core["form"] = ("same", "any")
    elif cat == "trade.add":  # 두 공정을 한꺼번에 더하려면 카드 밖 공정이 둘 이상 있어야 한다
        core["form"] = ("only", "with_field") + (("two",) if len(trades.registered()) > 2 else ())
    elif cat == "trade.remove":
        core["form"] = ("only", "with_field")
    elif cat == "no_change":  # last_trade: 하나뿐인 공정을 빼 달라고 함 (상담 코드가 남긴다)
        core["form"] = ("chitchat", "same_value", "already", "last_trade")
    extra = {"state": ("partial", "full"), "history": ("none", "some"), "noise": ("none", "noisy")}
    return core, extra


def expected_kind(cat: str, form: str) -> str:
    """기대 모양: change(바뀐 칸 있음) · none(없음) · any"""
    if cat in ("question", "question.other", "trade.ask", "vendor", "out_of_scope", "no_change"):
        return "none"
    if cat == "common.year" and form == "age":
        return "none"
    return "change"


def build(total: int = TOTAL) -> tuple[list[dict], dict]:
    r = gen.rng("router")
    per = max(3, total // len(CATEGORIES) // 3 * 3)
    near = gen.NearDup(0.8, keep_numbers=True)
    stats = Counter()
    cases: list[dict] = []
    for cat in CATEGORIES:
        core, extra = design(cat)
        rows = gen.balanced_rows(r, per, core, extra)
        gen.assign_splits(rows, group=lambda x, core=core: tuple(x[k] for k in core))
        for row in rows:
            for attempt in range(300):
                try:
                    inp, ideal, main = build_case(r, cat, row)
                except Retry:
                    stats["retry"] += 1
                    continue
                c = trades.card(inp)
                want = effect(c, apply(c, RouterOut.model_validate(ideal), ideal))
                kind = expected_kind(cat, row.get("form", ""))
                if (kind == "change") != bool(want) or not set(main) <= set(want):
                    stats["retry"] += 1
                    continue
                if near.add(inp["message"], (row["split"], cat)):
                    break
                stats["near"] += 1
                if attempt >= TRIES:  # 조각이 적은 범주: 말은 겹쳐도 카드 상태가 다른 사례로 남긴다
                    stats[f"near_kept:{cat}"] += 1
                    break
            else:
                raise SystemExit(f"{cat}: 사례를 만들지 못했어요")
            tpl = inp.pop("tpl")
            strata = {k: v for k, v in row.items() if k != "split"}
            strata["trades"] = "+".join(inp["card"]["trades"])
            moved = [f"+{k}" for k in ideal["trades_add"]] + [
                f"-{k}" for k in ideal["trades_remove"]
            ]
            strata["targets"] = (
                ",".join(moved + sorted({ch["field"] for ch in ideal["changes"]})) or "-"
            )
            cases.append(
                {
                    "split": row["split"],
                    "category": cat,
                    "strata": strata,
                    "input": inp,
                    "expect": {
                        "effect": want,
                        "questions": sorted({q["trade"] for q in ideal["questions"]}),
                        "out_of_scope": ideal["out_of_scope"],
                        "reply_has": VENDOR_WORDS if cat == "vendor" else [],
                        "ideal": ideal,
                    },
                    "tpl": tpl,
                }
            )
    return gen.number_cases(cases, "rt"), dict(stats)


def sample(cases: list[dict], n: int = 100) -> list[dict]:
    return gen.sample_2to1(cases, n, key=lambda c: c["category"])


def report(cases: list[dict], smp: list[dict], stats: dict) -> str:
    tpl = {s: {x for c in cases if c["split"] == s for x in c["tpl"]} for s in gen.SPLITS}
    fields = Counter(k for c in cases for k in c["expect"]["effect"])
    msgs = {s: {c["input"]["message"] for c in cases if c["split"] == s} for s in gen.SPLITS}
    kept = {k: v for k, v in sorted(stats.items()) if k.startswith("near_kept:")}
    parts = [
        gen.count_table(cases, "category", "범주"),
        *(gen.count_table(cases, f"strata.{k}") for k in ("trades", "state", "history", "noise")),
        "바뀌는 칸 (기대): " + ", ".join(f"{k} {v}" for k, v in sorted(fields.items())),
        (
            f"고객 말 조각: dev {len(tpl['dev'])}개 · held-out {len(tpl['heldout'])}개, "
            f"두 나눔이 같이 쓴 조각 {len(tpl['dev'] & tpl['heldout'])}개"
        ),
        (
            f"서로 다른 고객 말: dev {len(msgs['dev'])}개 · held-out {len(msgs['heldout'])}개 · "
            f"두 나눔에 같이 나온 말 {len(msgs['dev'] & msgs['heldout'])}개"
        ),
        f"다시 뽑음: 설계가 안 맞음 {stats.get('retry', 0)}번 · 근사 중복 {stats.get('near', 0)}번",
        f"근사 중복을 {TRIES}번 안에 못 피해 남긴 사례 (말은 비슷하고 카드 상태가 다름): "
        + (", ".join(f"{k.split(':')[1]} {v}" for k, v in kept.items()) or "없음"),
        "표본 100: "
        + ", ".join(f"{k} {v}" for k, v in sorted(Counter(c["split"] for c in smp).items())),
    ]
    return "\n\n".join(parts)


def main() -> None:
    for stream in (sys.stdout, sys.stderr):  # Windows 콘솔에서도 한글이 깨지지 않게
        stream.reconfigure(encoding="utf-8")
    cases, stats = build()
    smp = sample(cases)
    gen.write_jsonl(FULL, cases)
    gen.write_jsonl(SAMPLE, smp)
    assert gen.read_jsonl(FULL) == cases, "다시 읽은 사례가 달라요"
    print(
        f"저장: {FULL.relative_to(ROOT)} ({len(cases)}개) · {SAMPLE.relative_to(ROOT)} ({len(smp)}개)"
    )
    print()
    print(report(cases, smp, stats))


if __name__ == "__main__":
    main()
