"""추천 질문 고르기: 후보(질문 은행 · LLM)를 모아 답할 수 있고 지금 대화에 이어지는 것만 최대 3개. LLM · DB 없음.

- 질문 은행: 지식 조각에 묶인 예시 질문(hints). 인용한 조각의 바로 앞뒤 조각(깊이) → 방금 질문으로 다시 찾은
  위 12개 조각(관련) 순서로 모은다
- 거르기(순서대로)
  - 모양: 6~30자 물음표 문장, '그럼 · 그거'로 시작 안 함
  - 금액 · 기간 · 비율을 묻는 질문(계산 엔진 몫), 업체 · 브랜드 추천을 묻는 질문
  - 범위 밖 공정(창호 · 욕실 · 타일 · 바닥 · 전기 · 조명 등)과 인테리어 밖 주제(매매 · 분양 · 행정 처분)
  - 이어짐: 질문 임베딩이 있으면 방금 질문과 뜻이 MIN_SIM 이상 가까운 것만 남기고 가까운 순으로 고른다.
    임베딩이 없으면 흔한 말을 뺀 낱말(글자 두 개 묶음)이 방금 질문과 하나도 안 겹치면 뺀다
  - 겹침: 방금 질문 · 고른 것과 뜻이 같아 보이면(자카드 ≥ 0.4 또는 작은 쪽 기준 겹침 ≥ 0.6) 뺀다
  - 답할 수 있음: 키워드 검색 enough, 맨 위 출처 등급 ≥ 0.5, 맨 위가 이번 답에 인용된 조각이 아님(이미 답함),
    은행 질문은 묶인 조각이 위 3개 안
- 고르기: 임베딩이 있으면 뜻이 가까운 순, 없으면 은행 2개까지 + LLM 후보. 통과한 게 없으면 비운다
- 기준은 evaluation/answer 판정으로 맞췄다 (2026-11-13: 추천 질문 자연스러움 0.53 → 다시 잼)
"""

import re
from dataclasses import dataclass

from app.knowledge import bm25

MIN_LEN, MAX_LEN = 6, 30
DUP_JACCARD, DUP_OVERLAP = 0.4, 0.6
# 뜻 가까움(text-embedding-3-small 코사인) 아래 · 위 한계. 0.65 이상은 방금 질문을 거의 되풀이한 것
MIN_SIM, SAME_SIM = 0.4, 0.65
NEAR = 1  # 인용한 조각과 같은 문서에서 앞뒤로 볼 조각 수
RELATED = 12  # 방금 질문으로 다시 찾아 볼 조각 수
BAD_START = re.compile(r"^(그럼|그거|그건|그게|그러면|이거|저거)")
NUMBER_Q = re.compile(
    r"얼마|비용|가격|금액|평당|단가|비싸|저렴|몇\s*일|며칠|기간|몇\s*평|몇\s*만\s*원|퍼센트|%|몇\s*프로"
)
RECOMMEND_Q = re.compile(r"추천|브랜드|제품|어느 업체|어디 업체|업체 알려|잘하는 (곳|업체|팀)")
# 1차 범위(도배 · 목공) 밖 공정과 인테리어 밖 주제
OUT_Q = re.compile(
    r"창호|샷시|섀시|창문|욕실|화장실|타일|방수|바닥|마루|장판|전기|콘센트|조명|방등|LED|수전|배관|설비|"
    r"싱크|주방|가구|붙박이|필름|시트지|페인트|도장|중문|에어컨|보일러|"
    r"발코니|베란다|확장|비내력벽|입주\s*청소|전세|월세|세입자|집주인|임대차|불이 안|전등|"
    r"매도인|매수인|분양|이행강제금|행위허가|증설"
)
# 이어짐 · 겹침을 잴 때 빼는 흔한 말 (글자 두 개 묶음)
COMMON = frozenset(
    ["인테", "테리", "리어", "공사", "고객", "객이", "업체", "있나", "나요", "해요", "하나", "어요", "뭐예",
     "예요", "되나", "언제", "어떻", "떻게", "무엇", "엇을", "엇부", "누가", "해야", "할까", "까요", "있어",
     "는지", "가요", "세요", "에요", "이에", "인가", "하면", "려면", "돼요", "되요", "할때", "뭐가", "알려",
     "려줘", "는데", "으면", "어떤", "떤게", "이유", "유가", "우리", "집에", "이랑", "랑은", "하는", "는게"]
)  # fmt: skip


@dataclass(frozen=True)
class Pick:
    text: str
    ref: str | None = None  # 질문 은행 질문이 묶인 조각


def _jaccard(a: str, b: str) -> float:
    x, y = set(bm25.grams(a)), set(bm25.grams(b))
    return len(x & y) / len(x | y) if x | y else 0.0


def _words(t: str) -> set[str]:
    return {g for g in bm25.grams(t) if len(g) == 2 and g not in COMMON}


def _same(a: str, b: str) -> bool:
    """뜻이 같아 보이는 질문: 흔한 말을 뺀 낱말이 많이 겹친다"""
    x, y = _words(a), _words(b)
    if not x or not y:
        return _jaccard(a, b) >= DUP_JACCARD
    inter = len(x & y)
    return inter / len(x | y) >= DUP_JACCARD or inter / min(len(x), len(y)) >= DUP_OVERLAP


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


def candidates(
    ix: bm25.Index,
    question: str,
    *,
    shown: list[str],
    cited: set[str],
    llm: list[str] | tuple[str, ...] = (),
) -> list[Pick]:
    """후보: 질문 은행(깊이 → 관련) + LLM 후보. 같은 글은 하나만"""
    trade = bm25.trade_of(question)
    seen: set[str] = set()
    out: list[Pick] = []
    for p in [*_bank(ix, question, shown, cited, trade), *(Pick(str(t).strip()) for t in llm)]:
        if p.text and p.text not in seen:
            seen.add(p.text)
            out.append(p)
    return out


def pick(
    ix: bm25.Index,
    question: str,
    *,
    cands: list[Pick],
    cited: set[str],
    sims: dict[str, float] | None = None,
    trade: str | None = None,
    n: int = 3,
) -> list[Pick]:
    """sims = 후보 글 → 방금 질문과의 뜻 가까움(코사인). 없으면 글자 규칙으로 이어짐을 본다"""
    trade = trade or bm25.trade_of(question)
    asked = _words(question)
    chosen: list[Pick] = []

    def ok(p: Pick) -> bool:
        t = p.text
        if not MIN_LEN <= len(t) <= MAX_LEN or not t.endswith("?") or BAD_START.match(t):
            return False
        if NUMBER_Q.search(t) or RECOMMEND_Q.search(t) or OUT_Q.search(t):
            return False
        if sims is not None:
            if not MIN_SIM <= sims.get(t, -1.0) < SAME_SIM:
                return False
        elif asked and not (_words(t) & asked):
            return False
        if any(_same(t, s) for s in [question, *(c.text for c in chosen)]):
            return False
        r = bm25.search(ix, t, k=3, trade=trade)
        if not r.enough or not r.hits:
            return False
        top = ix.by_ref[r.hits[0].ref]
        if bm25.TIER.get(top.doc.kind, 0.5) < 0.5 or top.chunk.ref in cited:
            return False
        return p.ref is None or p.ref in {h.ref for h in r.hits}

    if sims is not None:
        order = sorted(cands, key=lambda p: -sims.get(p.text, -1.0))
        limits = [(order, n)]
    else:
        limits = [([p for p in cands if p.ref], 2), ([p for p in cands if not p.ref], n)]
    for group, limit in limits:
        for p in group:
            if len(chosen) >= limit:
                break
            if ok(p):
                chosen.append(p)
    return chosen
