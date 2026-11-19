"""LLM 모드(답 작성기) 실제 호출 평가: 핵심 질문 32개 × (프로젝트 있음 · 없음). 유료 — 실행 전에 어림 비용을 찍어요.
--mode free면 운영 무료 모드와 같게 돌려요(DB 색인 + 질문 임베딩, LLM 0회).

    cd backend && PYTHONPATH=".;tests;../evaluation;../evaluation/v3" LLM_LIVE=true \
      DATABASE_URL=...mitjip_v3 uv run python ../evaluation/v3/composer_eval.py --tag c1 [--model luna|terra]

- 지식: DB 적재본(knowledge.index) + 질문 임베딩 의미 순위(knowledge.nearest), 계산 값: chat.tools.general_facts
- 프로젝트 있음 맥락: coverage_check.FACTS(69.4㎡ · 표준견적서 · 예상 공정표 · 실측 초안 · 가견적) + 예시 추천 업체 2곳
- 남기는 것: .cache/<tag>/composer_answers.jsonl (공개 답 · 걸린 초 · 작성기 사용 · 뺀 이유 · 실제 토큰(입력 · 캐시 읽기 · 출력 · 추론) · 값)
"""

import argparse
import asyncio
import json
import sys
import time
import uuid
from datetime import date
from pathlib import Path

import tiktoken

HERE = Path(__file__).resolve().parent
PRICE = {
    "gpt-6.1-terra": (1.00, 5.00, 0.05),
    "gpt-6-luna": (0.10, 0.50, 0.01),
}  # 100만 토큰당 입력 · 출력 · 캐시 읽기 (agent-web C15, OpenAI 공식 값)


def usd(u: dict) -> float:
    """실제 사용량(llm.USAGE_HOOK)으로 센 값. 캐시 읽은 입력은 캐시 단가, 추론 토큰은 출력에 들어 있어요."""
    pin, pout, pcache = PRICE.get(u["model"], (1.0, 5.0, 0.05))
    fresh = max(u["input"] - u["cached"], 0)
    return (fresh * pin + u["cached"] * pcache + u["output"] * pout) / 1e6


async def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="c1")
    ap.add_argument("--model", default="", choices=["", "luna", "terra"])
    ap.add_argument("--only", default="", help="쉼표로 질문 id만(예: C02,C11)")
    ap.add_argument("--contexts", default="project,none")
    ap.add_argument(
        "--mode", default="llm", choices=["llm", "free"],
        help="free = 운영 무료 모드와 같게(DB 색인 + 질문 임베딩 의미 순위, LLM 0회)",
    )  # fmt: skip
    a = ap.parse_args()

    import coverage_check as cc

    from app.agent import llm
    from app.agent.v3.answer import KB
    from app.agent.v3.schemas import TurnContext, VendorPickFact
    from app.agent.v3.turn import run_turn
    from app.chat.service import _public
    from app.chat.tools import general_facts
    from app.config import settings
    from app.db import SessionLocal
    from app.knowledge import cards
    from app.knowledge import service as knowledge

    if not settings.llm_live:
        sys.exit("LLM_LIVE=true 가 필요해요(유료)")
    if a.model == "terra":
        settings.openai_light_roles = "trade"  # composer → terra
    elif a.model == "luna":
        settings.openai_light_roles = "trade,composer"
    enc = tiktoken.get_encoding("o200k_base")
    usage: list[dict] = []
    real = llm.structured
    llm.USAGE_HOOK = usage.append  # 실제 사용량(입력 · 캐시 읽기 · 출력 · 추론 토큰)

    async def counted(role, schema, messages):
        t0 = time.perf_counter()
        out = await real(role, schema, messages)
        if usage:  # 어림(o200k)도 같이 남겨 실제와 견줘요
            usage[-1]["est_in"] = sum(len(enc.encode(t)) for _, t in messages)
            usage[-1]["s"] = round(time.perf_counter() - t0, 2)
        return out

    llm.structured = counted  # type: ignore[assignment]
    qs = [
        json.loads(x)
        for x in (HERE / "core_questions.jsonl").read_text("utf-8").splitlines()
        if x.strip()
    ]
    if a.only:
        keep = set(a.only.split(","))
        qs = [q for q in qs if q["id"] in keep]
    facts = cc.FACTS.model_copy(deep=True)
    facts.vendors = [
        VendorPickFact(vendor_id="v1", name="마루와벽", estimate_total=2100000, vs_standard_pct=6,
                       rating=4.8, review_count=12, done_count=31, score=0.78,
                       reasons=["별점 4.8 · 리뷰 12개", "믿집 공사 31건", "가견적이 표준견적서보다 6% 높아요"]),
        VendorPickFact(vendor_id="v2", name="결도배", estimate_total=1990000, vs_standard_pct=1,
                       rating=4.6, review_count=7, done_count=12, score=0.71,
                       reasons=["별점 4.6 · 리뷰 7개", "믿집 공사 12건", "가견적이 표준견적서보다 1% 높아요"]),
    ]  # fmt: skip
    ctxs = [c for c in a.contexts.split(",") if c]
    n_turn = len(qs) * len(ctxs)
    model = llm.model_for("composer")[0]
    pin, pout, _ = PRICE.get(model, (1.0, 5.0, 0.05))
    est = n_turn * (2600 * pin + 600 * pout) / 1e6
    if a.mode == "free":
        est = 0.0
    print(
        f"턴 {n_turn}개 · {a.mode} · 작성기 {model} · 어림 비용 ${est:.3f} (+ 질문 임베딩 ≈ $0.0001)"
    )
    out_dir = HERE / ".cache" / a.tag
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    async with SessionLocal() as s:
        ix = await knowledge.index(s)
        for q in qs:
            for c in ctxs:
                usage.clear()
                t0 = time.perf_counter()
                emb = await llm.embed_query(q["q"])
                kb = KB(ix=ix, cards=cards.default(), dense=await knowledge.nearest(s, emb))
                today = date(2026, 11, 19)
                ctx = TurnContext(user_id=uuid.UUID(int=0), today=today, mode=a.mode)  # type: ignore[arg-type]
                f = facts if c == "project" else None
                r = await run_turn(
                    q["q"], ctx, kb=kb, facts=f, general=general_facts(q["q"], today)
                )
                secs = round(time.perf_counter() - t0, 2)
                pub = _public(r.answer)
                cost = sum(usd(u) for u in usage)
                rows.append({"id": q["id"], "q": q["q"], "context": c, "route": r.answer.trace.route,
                             "prompts": r.answer.trace.prompts, "dropped": r.answer.trace.dropped,
                             "s": secs, "usage": list(usage), "usd": round(cost, 6),
                             "answer": pub.model_dump(mode="json")})  # fmt: skip
                print(
                    q["id"], c, r.answer.trace.route, r.answer.trace.prompts, secs, f"${cost:.5f}"
                )
    with (out_dir / "composer_answers.jsonl").open("w", encoding="utf-8") as fh:
        for x in rows:
            fh.write(json.dumps(x, ensure_ascii=False) + "\n")
    tot = sum(x["usd"] for x in rows)
    used = sum(1 for x in rows if any(p.startswith("composer_") for p in x["prompts"]))
    calls = [u for x in rows for u in x["usage"]]
    tin = sum(u["input"] for u in calls)
    tcache = sum(u["cached"] for u in calls)
    print(
        f"작성기 쓴 턴 {used}/{len(rows)} · 실제 사용량 합계 ${tot:.4f} · 평균 {sum(x['s'] for x in rows) / max(len(rows), 1):.2f}초"
    )
    print(
        f"LLM 호출 {len(calls)}번 · 입력 {tin:,} (캐시 읽기 {tcache:,}, {tcache / max(tin, 1):.0%}) · 출력 {sum(u['output'] for u in calls):,} · 추론 {sum(u['reasoning'] for u in calls):,} 토큰"
    )


if __name__ == "__main__":
    asyncio.run(main())
