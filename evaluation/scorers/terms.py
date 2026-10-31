"""어려운 용어 표. 에이전트 글에 이 말을 쓰면 처음 나오는 문장에서 쉬운 말로 풀어야 한다.

풀이는 같은 문장 안에 있으면 된다. 예: '밑종이를 먼저 바르고(초배) 새 벽지를 발라요(정배).'
목록은 도배 · 목공 지식(SKILL.md)과 계산 엔진 줄 · 단계 이름에 나오는 업계 말에서 골랐다.
새 공정 용어는 그 공정 지식을 보고 더한다 (trades를 비우면 모든 공정에서 본다).
- 등박스 · 우물천장 · 무몰딩 · 히든 걸레받이처럼 아파트 인테리어에서 흔히 쓰는 말은 넣지 않았다.
- '품이 더 들어요'는 일상 말이라 넣지 않았다. 품셈 같은 기준 이름만 본다.
- 할증은 목공에서만 본다. 도배의 '짐 있는 집 작업 할증'은 흔히 아는 '웃돈' 뜻이고,
  목공 지식의 할증은 '버리는 몫'이라 풀지 않으면 웃돈으로 잘못 읽힌다.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class Term:
    pattern: re.Pattern[str]  # 용어
    gloss: re.Pattern[str]  # 풀이로 인정하는 말
    easy: str  # 쉬운 말 예
    trades: tuple[str, ...] = ()  # 이 용어를 보는 공정 키 (비우면 모든 공정)


def _t(pattern: str, gloss: str, easy: str, trades: tuple[str, ...] = ()) -> Term:
    return Term(re.compile(pattern), re.compile(gloss), easy, trades)


_EVEN = r"바탕을?\s?고르|고르게|평평|매끈"
TERMS: dict[str, Term] = {
    "초배": _t(
        r"초배",
        r"밑\s?(종이|지|바름|바탕)|애벌|속지|바탕\s?종이|(먼저|밑에)\s?(바르|붙이|발라|붙여)",
        "밑종이를 먼저 바르는 일",
    ),
    "정배": _t(
        r"정배",
        r"겉\s?(지|벽지|종이)|마감\s?벽지|새\s?벽지|(위에|마지막으로?)\s?(바르|붙이|발라|붙여)"
        r"|벽지를\s?(바르|붙이|발라|붙여)",
        "새 벽지를 겉에 바르는 일",
    ),
    "퍼티": _t(
        r"퍼티", _EVEN + r"|메우|메꾸|메워|메꿔|채우|채워|틈|구멍|갈라진", "갈라진 곳 메우기"
    ),
    "샌딩": _t(r"샌딩", _EVEN + r"|갈아|사포|문질", "사포로 갈아 매끈하게"),
    "덧방": _t(
        r"덧방",
        r"(그\s?)?위에\s?(덧)?(바르|붙이|발라|붙여)|떼지\s?않고|안\s?떼고|겹쳐",
        "기존 벽지 위에 바로 바르기",
    ),
    "보양": _t(r"보양", r"덮|감싸|보호|가리|씌우|비닐", "바닥 · 가구 덮기"),
    "할증": _t(
        r"할증",
        r"버리는\s?(몫|양)|여유분|넉넉|자투리",
        "버리는 몫까지 더 잡은 양",
        ("mokgong",),
    ),
    "소요량": _t(r"소요량", r"필요한\s?양|드는\s?양|쓰는\s?양|들어가는\s?양", "필요한 양"),
    "문선": _t(r"문선", r"문\s?(둘레|테두리)|둘레\s?마감|테두리", "문 둘레 마감"),
    "천장틀": _t(r"천장틀", r"뼈대|틀을\s?(짜|만들|세우)|받침", "천장 뼈대"),
    "품셈 · 단가 이름": _t(
        r"품셈|표준시장단가|노임단가|시중노임",
        r"공공\s?(기준|단가)|나라|정부|기준\s?(값|단가|가격)",
        "공공 기준",
    ),
}


def unexplained(sents: Iterable[str], trade: str | None = None) -> list[str]:
    """처음 나온 문장에서 풀이 없이 쓴 어려운 용어 (trade를 주면 그 공정이 보는 용어만)"""
    sents = list(sents)
    out = []
    for name, term in TERMS.items():
        if trade is not None and term.trades and trade not in term.trades:
            continue
        first = next((s for s in sents if term.pattern.search(s)), None)
        if first is not None and not term.gloss.search(first):
            out.append(name)
    return out
