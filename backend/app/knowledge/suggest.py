"""추천 질문 고르기: 후보(질문 은행 · 다음 단계 · LLM)를 모아 답할 수 있는 것만 최대 3개. LLM · DB 없음.

- 질문 은행: 지식 조각에 묶인 예시 질문(hints). 인용한 조각의 바로 앞뒤 조각(깊이) → 방금 질문으로 다시 찾은
  위 12개 조각(관련) 순서로 모은다
- 거르기(순서대로): 모양(6~30자 물음표 문장, '그럼 · 그거'로 시작 안 함) → 금액 · 기간을 묻는 질문 뺌(계산 엔진 몫)
  → 방금 질문 · 고른 것과 겹침(글자 두 개 묶음 자카드 ≥ 0.6) → 답할 수 있음(키워드 검색 enough, 맨 위 출처 등급 ≥ 0.5)
  → 이미 답함(맨 위 조각이 이번 답에 인용된 조각) → 은행 질문은 묶인 조각이 위 3개 안
- 고르기: 은행 2개까지 + 다음 단계 · LLM 후보로 채움. 통과한 게 없으면 비운다
"""

import re
from dataclasses import dataclass

from app.knowledge import bm25

MIN_LEN, MAX_LEN = 6, 30
DUP = 0.6
NEAR = 1  # 인용한 조각과 같은 문서에서 앞뒤로 볼 조각 수
RELATED = 12  # 방금 질문으로 다시 찾아 볼 조각 수
BAD_START = re.compile(r"^(그럼|그거|그건|그게|그러면|이거|저거)")
NUMBER_Q = re.compile(
    r"얼마|비용|가격|금액|평당|단가|비싸|저렴|몇\s*일|며칠|기간|몇\s*평|몇\s*만\s*원"
)
# 공정 답 뒤에 넓게 물을 다음 단계 (공정 순서: 목공 → 도배 → 바닥재)
NEXT_STEP = {
    "도배": ("도배 끝나고 바닥은 언제 깔아요?", "도배 끝나면 무엇을 확인해야 해요?"),
    "목공": ("목공 끝나고 도배는 바로 해요?", "목공 끝나면 무엇을 확인해야 해요?"),
}


@dataclass(frozen=True)
class Pick:
    text: str
    ref: str | None = None  # 질문 은행 질문이 묶인 조각


def _jaccard(a: str, b: str) -> float:
    x, y = set(bm25.grams(a)), set(bm25.grams(b))
    return len(x & y) / len(x | y) if x | y else 0.0


def _bank(
    ix: bm25.Index, question: str, shown: list[str], cited: set[str], trade: str | None
) -> list[Pick]:
    """인용한 조각(없으면 맨 위 조각)의 앞뒤 조각 → 질문과 관련된 조각의 예시 질문. 인용한 조각 것은 이미 답해서 뺀다"""
    picked: list[bm25.Item] = []
    for ref in [r for r in shown if r in cited] or shown[:1]:
        x = ix.by_ref.get(ref)
        if x is None:
            continue
        same = [y for y in ix.items if y.chunk.doc == x.chunk.doc]
        i = same.index(x)
        picked.extend(same[max(0, i - NEAR) : i + NEAR + 1])
    picked.extend(ix.by_ref[h.ref] for h in bm25.search(ix, question, k=RELATED, trade=trade).hits)
    out: list[Pick] = []
    for y in dict.fromkeys(picked):
        if y.chunk.ref not in cited:
            out.extend(Pick(h.strip(), y.chunk.ref) for h in y.chunk.hints if h.strip())
    return out


def pick(
    ix: bm25.Index,
    question: str,
    *,
    shown: list[str],
    cited: set[str],
    llm: list[str] | tuple[str, ...] = (),
    trade: str | None = None,
    n: int = 3,
) -> list[Pick]:
    trade = trade or bm25.trade_of(question)
    chosen: list[Pick] = []

    def ok(p: Pick) -> bool:
        t = p.text
        if not MIN_LEN <= len(t) <= MAX_LEN or not t.endswith("?"):
            return False
        if BAD_START.match(t) or NUMBER_Q.search(t):
            return False
        if any(_jaccard(t, s) >= DUP for s in [question, *(c.text for c in chosen)]):
            return False
        r = bm25.search(ix, t, k=3, trade=trade)
        if not r.enough or not r.hits:
            return False
        top = ix.by_ref[r.hits[0].ref]
        if bm25.TIER.get(top.doc.kind, 0.5) < 0.5 or top.chunk.ref in cited:
            return False
        return p.ref is None or p.ref in {h.ref for h in r.hits}

    def take(cands: list[Pick], limit: int) -> None:
        for p in cands:
            if len(chosen) >= limit:
                return
            if ok(p):
                chosen.append(p)

    take(_bank(ix, question, shown, cited, trade), 2)
    wide = [Pick(t) for t in NEXT_STEP.get(trade or "", ())]
    take([Pick(str(t).strip()) for t in llm] + wide, n)
    return chosen
