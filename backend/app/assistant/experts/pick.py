"""공정 고르기(LLM 없이). 질문 낱말이 먼저, 없으면 이 공사 공정, 그래도 모르면 지식 조각 갈래를 봐요.

- question: 질문에 도배 · 목공 낱말이 있어요(지식 검색 낱말 bm25.TRADE_WORDS + 공정 설정 증상 낱말). 둘 다면 둘 다.
- other: 다른 공정(바닥 · 욕실 · 전기 …) 낱말만 있어요. 이 공사 공정으로 넘기지 않아요(알아 두기가 맡아요).
- project: 질문 낱말이 없고 이 공사 공정이 하나예요.
- 그 밖(이 공사 공정이 둘이거나 공사가 없음)은 지식 조각 갈래(infer)로: 한 공정 조각이 공통보다 많으면 그 공정
  (knowledge), 두 공정 조각이 섞여 공통보다 많으면 갈림(split, 어느 공정인지 하나 물어요), 아니면 모름(unknown,
  공통 근거로 답해요).
"""

from dataclasses import dataclass
from typing import Literal

from app.agent.trades import TRADES
from app.knowledge import bm25

ORDER = bm25.SCOPES  # ("도배", "목공")
Why = Literal["question", "other", "project", "knowledge", "split", "unknown"]
# 전문가 고르기에만 더 보는 공정 낱말(지식 검색 낱말 · 공정 설정 증상 낱말에 없는 목공 일). 전기 · 가구 낱말과
# 겹쳐도 목공이 맡는 몫(박스 · 철거)이 있어 목공 전문가를 불러요(QA r6 c2 T23 '우물천장 간접조명'이 다른 공정으로 감)
EXTRA_WORDS: dict[str, tuple[str, ...]] = {
    "목공": ("우물천장", "등박스", "간접조명", "아트월", "붙박이장"),
}
INFER_TOP = 6  # 갈래를 셀 조각 수(주제가 맞는 것만, bm25.on_topic)
INFER_MIN = 2  # 한 공정으로 볼 때 그 공정 조각 수 하한
SPLIT_ASK = "도배 · 목공 중 어느 공사 얘기인지"


@dataclass(frozen=True)
class Pick:
    trades: tuple[str, ...] = ()  # 부를 전문가(도배 · 목공 순서)
    why: Why = "unknown"


def named(question: str) -> tuple[str, ...]:
    """질문 낱말로 알아본 공정(도배 · 목공 순서). 일상어 낱말(실크 · 테두리)도 비서 안에서는 공정 낱말로 봐요."""
    hit = set(bm25.trades_of(question))
    hit |= {c.name for c in TRADES.values() if any(w in question for w in c.symptom_words)}
    hit |= {t for t, words in EXTRA_WORDS.items() if any(w in question for w in words)}
    return tuple(t for t in ORDER if t in hit)


def pick(question: str, project: tuple[str, ...] = (), *, other: bool = False) -> Pick:
    """질문 낱말 → (다른 공정 낱말이 없을 때) 이 공사 공정 하나 → 모름(부르는 쪽이 infer로 더 봐요)."""
    got = named(question)
    if got:
        return Pick(got, "question")
    if other:
        return Pick((), "other")
    own = tuple(t for t in ORDER if t in project)
    if len(own) == 1:
        return Pick(own, "project")
    return Pick((), "unknown")


def infer(hits: list[bm25.Hit]) -> Pick:
    """모를 때 지식 조각 갈래로 정해요(검색 순서대로 주제가 맞는 조각 INFER_TOP개).
    공통(전체 · 공통 표시와 도배 · 목공을 같이 단 조각)이 공정 조각만큼 있거나 공정 조각이 INFER_MIN보다 적으면 모름,
    한 공정만 있으면 그 공정, 두 공정이 섞이면 한쪽이 두 배 넘을 때만 그 공정이고 아니면 갈림이에요."""
    top = bm25.on_topic(hits, (*ORDER, bm25.COMMON))[:INFER_TOP]
    d = sum(1 for h in top if h.scope == ("도배",))
    m = sum(1 for h in top if h.scope == ("목공",))
    common = len(top) - d - m
    if d + m < INFER_MIN or common >= d + m:
        return Pick((), "unknown")
    if d >= INFER_MIN and d > 2 * m:
        return Pick(("도배",), "knowledge")
    if m >= INFER_MIN and m > 2 * d:
        return Pick(("목공",), "knowledge")
    if d and m:
        return Pick((), "split")
    return Pick((), "unknown")
