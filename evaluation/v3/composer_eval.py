"""LLM 모드(답 작성기) 실제 호출 평가: 핵심 질문 32개 × (프로젝트 있음 · 없음). 유료 — 실행 전에 어림 비용을 찍어요.

    cd backend && PYTHONPATH=".;tests;../evaluation;../evaluation/v3" LLM_LIVE=true \
      DATABASE_URL=...mitjip_v3 uv run python ../evaluation/v3/composer_eval.py --tag c1 [--model luna|terra]

- 지식: DB 적재본(knowledge.index) + 질문 임베딩 의미 순위(knowledge.nearest), 계산 값: chat.tools.general_facts
- 프로젝트 있음 맥락: coverage_check.FACTS(69.4㎡ · 표준견적서 · 예상 공정표 · 실측 초안 · 가견적) + 예시 추천 업체 2곳
- 남기는 것: .cache/<tag>/composer_answers.jsonl (공개 답 · 걸린 초 · 작성기 사용 · 뺀 이유 · 입력 토큰 어림)
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
    "gpt-6.1-terra": (1.00, 5.00),
    "gpt-6-luna": (0.10, 0.50),
}  # 100만 토큰당 입력 · 출력 (agent-web C15)


async def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="c1")
    ap.add_argument("--model", default="", choices=["", "luna", "terra"])
    ap.add_argument("--only", default="", help="쉼표로 질문 id만(예: C02,C11)")
    ap.add_argument("--contexts", default="project,none")
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

    async def counted(role, schema, messages):
        name, effort = llm.model_for(role)
        tin = sum(len(enc.encode(t)) for _, t in messages)
        t0 = time.perf_counter()
        out = await real(role, schema, messages)
        tout = len(enc.encode(out.model_dump_json()))
        usage.append({"role": role, "model": name, "effort": effort, "in": tin, "out": tout,
                      "s": round(time.perf_counter() - t0, 2)})  # fmt: skip
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
    pin, pout = PRICE.get(model, (1.0, 5.0))
    est = n_turn * (2600 * pin + 600 * pout) / 1e6
    print(f"턴 {n_turn}개 · 작성기 {model} · 어림 비용 ${est:.3f} (+ 질문 임베딩 ≈ $0.0001)")
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
                ctx = TurnContext(user_id=uuid.UUID(int=0), today=date(2026, 11, 19), mode="llm")
                f = facts if c == "project" else None
                r = await run_turn(q["q"], ctx, kb=kb, facts=f, general=general_facts(q["q"]))
                secs = round(time.perf_counter() - t0, 2)
                pub = _public(r.answer)
                cost = sum(u["in"] / 1e6 * PRICE.get(u["model"], (1, 5))[0]
                           + u["out"] / 1e6 * PRICE.get(u["model"], (1, 5))[1] for u in usage)  # fmt: skip
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
    used = sum(1 for x in rows if "composer_v1" in x["prompts"])
    print(
        f"작성기 쓴 턴 {used}/{len(rows)} · 어림 합계 ${tot:.4f} · 평균 {sum(x['s'] for x in rows) / max(len(rows), 1):.2f}초"
    )


if __name__ == "__main__":
    asyncio.run(main())
