"""공정 전문가 답(ExpertAnswer) 코드 채점. 모델 원문(코드 검사 전) 기준이다.

'질문에 맞게 답했는지'는 코드로는 핵심 말(groups)만 보고, 판정 LLM(rubric_expert_v1)이 매긴다.
"""

import re

from app.agent.trade import NUMBER_CLAIM
from evaluation.common import trades
from evaluation.scorers.rules import bad_endings, sentences
from evaluation.scorers.terms import unexplained
from evaluation.scorers.trade_plan import NUM_WORD

LIMIT = 300  # app.agent.trade.TradeAgent.check_answer와 같다
MAX_SENTENCES = 4  # 프롬프트는 두세 문장
CHECKS = {
    "answer_ok": "답이 있고 300자 이하",
    "no_number": "지어낸 금액 · 기간 · 면적 없음 (숫자 · '하루' 같은 말 포함)",
    "sources_known": "출처는 그 공정 지식 목록 안",
    "style": "'-해요'체",
    "terms": "업계 말은 처음 나온 문장에서 풀어 씀",
    "short": f"{MAX_SENTENCES}문장 이하",
    "no_ask": "되묻지 않음",
    "on_topic": "물은 것의 핵심 말이 있음 (비교는 둘 다, 비용 · 기간은 화면 · 실측 안내, 범위 밖은 따로 하는 공사)",
}


def score(case: dict, raw: dict) -> dict:
    """{'checks': {검사 id: 통과}, 'detail': {검사 id: 까닭}, 'chars': 글자 수, 'sentences': 문장 수}"""
    trade = case["trade"]
    text = (raw.get("answer") or "").strip()
    sents = sentences(text)
    checks: dict[str, bool] = {}
    detail: dict[str, str] = {}

    def put(cid: str, ok: bool, why: str = "") -> None:
        checks[cid] = ok
        if not ok and why:
            detail[cid] = why

    put("answer_ok", bool(text) and len(text) <= LIMIT, f"{len(text)}자")
    nums = [m.group(0) for p in (NUMBER_CLAIM, NUM_WORD) for m in p.finditer(text)]
    put("no_number", not nums, ", ".join(nums[:3]))
    bad = [s for s in raw.get("sources") or [] if s not in trades.sources(trade)]
    put("sources_known", not bad, f"목록 밖 {bad}")
    put("style", not bad_endings(sents), "; ".join(bad_endings(sents))[:60])
    put("terms", not (u := unexplained(sents, trade)), ", ".join(u))
    put("short", len(sents) <= MAX_SENTENCES, f"{len(sents)}문장")
    asks = [s for s in sents if s.rstrip().endswith("?")]
    put("no_ask", not asks, asks[0][:40] if asks else "")
    missing = [g for g in case["expect"]["groups"] if not re.search(g, text)]
    put("on_topic", not missing, f"없는 말 {missing}")
    return {"checks": checks, "detail": detail, "chars": len(text), "sentences": len(sents)}
