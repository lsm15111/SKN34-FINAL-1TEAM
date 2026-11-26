"""바닥 상담에 쓰는 키워드 검색. 고객 말 → 시방서 말 보강(terms.py)은 꺼 둬요.

보강은 아직 저장소에 없는 바닥 원문(KCS · LHCS)용이에요. 지금 dev 자료에서 재면 근거가 8자리 안에 다 드는
바닥 질문이 43 → 40(위 5 + 보강 3) · 42(모자랄 때만) · 43(위 7 + 1)이라 켜지 않아요(2026-11-26).
바닥 원문을 넣는 W8 뒤에 다시 재서 EXPAND를 정해요."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from app.agent.v3.specialists.floor.terms import TERMS
from app.knowledge import search3

if TYPE_CHECKING:
    from app.agent.v3.answer import KB
    from app.knowledge.bm25 import Result

MAX_GROUPS = 2  # 기존 검색은 앞 80자만 쓰므로 보강 말은 두 묶음 · 묶음마다 두 낱말까지
MAX_WORDS = 2
K, KEEP, RESERVE = 8, 5, 3  # 검색 자리: 원래 질문 위 5개 + 보강에서만 나온 3개
EXPAND = False


def _plain(s: str) -> str:
    return "".join(s.split()).lower()


def search_query(question: str) -> str:
    """질문에 든 고객 말 묶음(문장 앞 순서)의 문서 말을 앞에 붙여요. 이미 문서 말이 있으면 빼요."""
    q = _plain(question)
    hits: list[tuple[int, int, tuple[str, ...]]] = []  # 시작 · 끝 · 문서 말
    for say, doc in TERMS:
        spans = [
            (q.find(_plain(w)), q.find(_plain(w)) + len(_plain(w))) for w in say if _plain(w) in q
        ]
        if spans:
            s, e = min(spans, key=lambda x: (x[0], -x[1]))
            hits.append((s, e, doc))
    kept: list[tuple[int, int, tuple[str, ...]]] = []
    for s, e, doc in sorted(hits, key=lambda x: (x[0], -(x[1] - x[0]))):
        if any(ks <= s and e <= ke for ks, ke, _ in kept):  # '강마루' 안의 '마루'는 건너뛴다
            continue
        kept.append((s, e, doc))
    words: list[str] = []
    for _, _, doc in kept[:MAX_GROUPS]:
        words += [w for w in doc if _plain(w) not in q and w not in words][:MAX_WORDS]
    return f"{' '.join(words)} {question}" if words else question


def retrieve(kb: KB, question: str) -> Result:
    """원래 질문의 위 KEEP개는 그대로 두고, 보강 검색에서만 나온 조각을 RESERVE자리에 붙여요.

    한 번에 합치면 원래 질문으로 찾던 조각이 밀려나요(v4 전문가 검색 용어와 같은 문제).
    출처 제한은 늘 고객의 원래 질문으로 판단해요(도배 retrieval과 같음).
    """
    base = search3.search(kb.ix, question, trades=["floor"], tags=kb.tags, k=K)
    query = search_query(question) if EXPAND else question
    if query == question:
        return base
    ext = search3.search(kb.ix, query, trades=["floor"], tags=kb.tags, k=K, policy_text=question)
    top = base.hits[:KEEP]
    seen = {h.ref for h in top}
    extra = [h for h in ext.hits if h.ref not in seen][:RESERVE]
    seen |= {h.ref for h in extra}
    rest = [h for h in base.hits[KEEP:] if h.ref not in seen]
    hits = (top + extra + rest)[:K]
    return replace(base, hits=hits, enough=base.enough or ext.enough)
