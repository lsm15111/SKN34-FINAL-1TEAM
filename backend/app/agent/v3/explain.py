"""설명 질문 꼴과 공정 정보 (코드 규칙 · 데이터, LLM 없음). 답 작성기(composer)가 꼴마다 쓰는 법을 바꿔요.

- explain: 도배 · 목공의 뜻 · 하는 일 · 순서 · 고를 것 · 방법 질문('목공이 뭐야 · 도배 어떻게 해'). 숫자를 묻지 않아요.
  일반 설명을 섞고, 공종마다 블록으로 길게 쓰고, 처음엔 개요 1~2줄만 보여요. 확인할 곳 줄은 붙이지 않아요.
- house: 우리 집 조건 질문('우리 집 몰딩 바꿔야 할까?'). 흔한 경우로 나눠 대략 답하고, 끝에 확인할 곳 한 줄을 둬요.
- None: 그 밖(금액 · 기간 · 업체 · 하자 · 법률 · 위험한 작업 · 다른 공종). 지금처럼 자료로만 짧게 써요.
일반 설명 문장(인용 없음)은 숫자 · 업체 · 브랜드 · 하자 판정 · 법률 · 위험한 작업 말을 빼고(general.py와 같은 규칙),
공종 순서를 말하면 공종 순서 데이터(TradeSpec.order)와 맞는지 본다(order_ok).
공정 정보(facts)는 코드 데이터(공종 순서 · 순서 문장 · 상담 칸 · 실측 때 보는 것 · 준비 · 표준 행 이름)로 만든 근거예요.
"""

import itertools
import re
from typing import Literal

from app.agent.v3 import general
from app.agent.v3.trades import BY_CODE, ORDER_RULES, SPECS, mention_spans, slot_label, trades_in
from app.calc.estimate import PRICE_ROWS, V3_ROWS

Kind = Literal["explain", "house"]
TRADES = general.TRADES  # 도배 · 목공(1차 범위)
ROUTES = ("trade", "multi")
ORDER_REF = "rule:trade-order"
ORDER_TITLE = "믿집 공정 순서"

# 설명해 달라는 말('설명해줘 · 알려 줘'), 하는 일('뭐 하는 공정이야'), 하는 까닭('초배는 왜 해?')도 설명 질문으로 봐요
ASK_EXPLAIN = re.compile(
    r"설명|알려\s{0,2}(?:줘|주세요|줄래|주실래)|가르쳐|뭐\s{1,2}(?:하는|해|해요|하나요)|무슨\s{0,2}일|하는\s{0,2}일|"
    r"왜\s{0,2}(?:하|해|필요|쓰|넣|바르|붙|비싸|싸)"
)
# 우리 집 조건: 이 집 · 오래된 집을 두고 해야 하는지 · 나은지를 묻는 말
HOUSE = re.compile(
    r"(?:우리|저희|제)\s{0,2}집|(?:오래된|낡은|구축|신축)\s{0,2}(?:아파트|집)|"
    r"(?:\d{1,2}|이십|삼십)\s{0,2}년\s{0,2}(?:된|차|넘은)"
)
DECIDE = re.compile(
    r"해야\s{0,2}(?:해|하나|할까|돼|되나|되나요)|할까|될까|괜찮|나을까|나아|바꿔야|필요(?:해|한가|할까|있)|"
    r"어때|어떨까|좋을까|되나요|돼요\?"
)
BLOCK = general.BLOCK_FLAGS - {"my_house"}


def kind(question: str, route: str, trades: list[str], policy: list[str]) -> Kind | None:
    """질문 꼴(설명 · 우리 집 조건). 도배 · 목공 질문만이고, 숫자 · 업체 · 하자 · 위험한 작업을 물으면 None."""
    if route not in ROUTES or not trades or any(t not in TRADES for t in trades):
        return None
    flags = set(policy)
    if flags & BLOCK:
        return None
    q = question or ""
    if general.NUM_ASK.search(q) or general.RISK.search(q):
        return None
    if "my_house" in flags or (HOUSE.search(q) and DECIDE.search(q)):
        return "house"
    if general.WHAT_HOW.search(q) or ASK_EXPLAIN.search(q):
        return "explain"
    return None


def chain() -> str:
    """공종 순서 한 줄(같은 순서 공종은 ' · '로 묶음). 공통은 빼요."""
    steps: dict[int, list[str]] = {}
    for s in SPECS:
        if s.code != "common":
            steps.setdefault(s.order, []).append(s.ko)
    return " → ".join(" · ".join(v) for _, v in sorted(steps.items()))


def _rows(code: str) -> list[str]:
    """믿집 표준견적서 · 가견적에 들어가는 그 공종의 일(계산 엔진 줄 이름, 자재 줄은 뺌)."""
    names = [r.name.replace(" (", "(") for r in PRICE_ROWS.get(code, ()) if "자재" not in r.name]
    if code == "dobae":
        names += [
            f"{r.label or r.name}({r.note})" if r.note else r.label or r.name for r in V3_ROWS[:1]
        ]
    return list(dict.fromkeys(names))


# 상담 칸을 '무엇을 정하는지' 말로(단추 이름 '바꿔요 · 그대로 둬요'를 옮겨 쓰지 않게). 없는 칸은 칸 이름 그대로
CHOICE = {
    "dobae.grade": "오래 살 집인지 세 놓을 집인지(벽지 유형)",
    "dobae.ceiling": "천장도 도배할지",
    "dobae.living": "살면서 공사하는지",
    "dobae.mold": "곰팡이 · 물자국이 있는지",
    "dobae.area_basis": "넣은 면적이 공급면적인지 전용면적인지",
    "mokgong.molding": "몰딩도 바꿀지",
    "mokgong.doors": "방문은 문짝만 바꿀지 문틀까지 바꿀지",
    "mokgong.ceiling": "천장 평탄화를 할지",
}


def _trade_text(code: str) -> str:
    spec = BY_CODE[code]  # type: ignore[index]
    pairs = [t for (a, b), t in ORDER_RULES.items() if code in (a, b)]
    choose = [CHOICE.get(x.key, slot_label(x.key)) for x in spec.slots]
    parts = [
        f"{spec.ko} 순서: " + " ".join(pairs),
        f"믿집 견적에 들어가는 {spec.ko} 일: " + " / ".join(_rows(code)) + ".",
        "상담 때 정하는 것: " + " / ".join(choose) + ".",
        "실측 때 업체가 보는 것: " + " / ".join(spec.survey) + ".",
        "고객이 준비할 것: " + " / ".join(spec.prep) + ".",
        "주의: " + " ".join(spec.cautions),
    ]
    if code == "dobae":
        parts.append("믿집 도배 유형: 저가형은 합지, 기본형은 실크예요.")
    return " ".join(parts)


def facts(trades: list[str]) -> list[dict]:
    """공정 정보 근거(코드 데이터). ref는 출처 칸과 인용 검사에 써요."""
    out = [{"ref": ORDER_REF, "제목": ORDER_TITLE, "글": f"믿집이 쓰는 공정 순서: {chain()}."}]
    for code in dict.fromkeys(trades):
        if code in TRADES:
            out.append(
                {"ref": f"rule:trade.{code}", "제목": f"믿집 공정 정보 · {BY_CODE[code].ko}",
                 "글": _trade_text(code)}
            )  # fmt: skip
    return out


def sources(items: list[dict]) -> dict[str, dict]:
    """공정 정보 ref → 출처 칸(rule 근거는 믿집이 만든 데이터)."""
    return {
        x["ref"]: {"ref": x["ref"], "title": x["제목"], "kind": "rule", "publisher": "믿집"}
        for x in items
    }


# 순서 낱말: 이 공종(묶음) 바로 뒤에 붙어 '이 공종 다음에 다른 공종' · '이 공종 전에 다른 공종'을 말해요
_JOIN = re.compile(r"^(?:\s|·|,|과|와|이랑|랑|및|하고|이나|나|또는)*$")
_PARTICLE = r"\s{0,2}(?:공정|작업|공사)?\s{0,2}(?:이|가|을|를|은|는|도)?\s{0,2}"
AFTER = re.compile(
    rf"^{_PARTICLE}(?:바로\s{{0,2}})?(?:끝난|끝나고|끝내고|끝나면|끝나야|마친|마치고|마치면|마쳐야|마무리|다음|뒤|이후|"
    r"후(?:에|엔|로|[\s,.]|$))"
)
BEFORE = re.compile(
    rf"^{_PARTICLE}(?:바로\s{{0,2}})?(?:전에|전까지|전엔|보다\s{{0,2}}먼저|보다\s{{0,2}}앞|앞에|앞서)"
)
SEQUENCE = re.compile(r"→|순서로|순으로|차례로|그다음|그\s{0,2}다음|이어서")
SAME_TIME = re.compile(r"동시에|같은\s{0,2}날|함께\s{0,2}(?:해|진행)|같이\s{0,2}(?:해|진행)")
LAST = re.compile(
    r"(?:맨|가장)\s{0,2}마지막|마지막\s{0,2}(?:공정|단계|순서|작업)(?:이에요|예요|이고|이라|으로)"
)
FIRST = re.compile(r"(?:맨|가장)\s{0,2}먼저|첫\s{0,2}(?:공정|단계|순서)")
ROUGH = re.compile(r"거의|가까|쯤|무렵|후반|중반|초반|하나예요|중\s{0,2}하나")


def _claims(text: str) -> list[tuple[str, str]]:
    """문장이 말하는 (앞 공종, 뒤 공종) 짝. '·'로 이은 공종은 한 묶음이고, 묶음 바로 뒤의 순서 낱말이
    가리키는 짝은 다음 묶음(없으면 앞 묶음)이에요: '목공이 끝난 뒤 도배' · '도배는 목공이 끝난 뒤에'."""
    codes = [c for c in trades_in(text) if c != "common"]
    spans = mention_spans(text, codes)
    if len(spans) < 2:
        return []
    groups: list[list[tuple[int, int, str]]] = [[spans[0]]]
    for sp in spans[1:]:
        if _JOIN.match(text[groups[-1][-1][1] : sp[0]]):
            groups[-1].append(sp)
        else:
            groups.append([sp])
    out: list[tuple[str, str]] = []
    anchored = False
    for i, g in enumerate(groups):
        tail = text[g[-1][1] : g[-1][1] + 14]
        mine = [c for _, _, c in g]
        near = groups[i + 1] if i + 1 < len(groups) else (groups[i - 1] if i else [])
        others = [c for _, _, c in near]
        if AFTER.match(tail):
            out += [(a, b) for a in mine for b in others]
            anchored = True
        elif BEFORE.match(tail):
            out += [(b, a) for a in mine for b in others]
            anchored = True
    if not anchored and SEQUENCE.search(text) and not SAME_TIME.search(text):
        flat = [c for _, _, c in spans]  # '철거, 전기, 목공 순서로': 나온 차례가 순서예요
        out += list(itertools.pairwise(flat))
    return out


def order_ok(text: str) -> bool:
    """공종 순서 말이 공종 순서 데이터와 맞는지. 순서를 말하지 않으면 True."""
    order = {s.code: s.order for s in SPECS}
    for a, b in _claims(text):
        if order[a] > order[b]:
            return False
    if not ROUGH.search(text):
        codes = [c for c in trades_in(text) if c != "common"]
        top = max(order.values())
        low = min(v for c, v in order.items() if c != "common")
        if codes and LAST.search(text) and order[codes[0]] < top:
            return False
        if codes and FIRST.search(text) and order[codes[0]] > low and len(codes) == 1:
            return False
    return True


def general_why(text: str) -> str | None:
    """일반 설명 문장(인용 없음)을 빼는 이유. 없으면 None."""
    t = text.strip()
    if general.OUT_NUM.search(t):
        return "일반 설명: 숫자"
    if general.OUT_WORD.search(t):
        return "일반 설명: 빼는 말"
    if not order_ok(t):
        return "순서 틀림"
    return None
