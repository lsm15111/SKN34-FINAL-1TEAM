"""LLM 모드 한 턴 시간: ChatGPT 비교 질문 6개를 지금 모델(설정값)과 작은 모델(luna 추론 없음)로 돌려 잰다.

    cd backend && PYTHONPATH=. LLM_LIVE=true uv run python ../evaluation/v3/llm_speed.py

- 유료: 질문 6개 × 2설정 × 묶음 다시 쓰기 1~3회(+ 질문 임베딩). 예상 $0.10 미만.
- 지금 /ai/turns는 답을 다 만든 뒤에 보내서, 여기서 잰 시간 = 사용자가 첫 글자를 보는 시간이에요.
"""

import asyncio
import json
import sys
import time
import uuid
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent


async def one(q: str, ctx, s, knowledge, cards, KB, run_turn, embed_query, check):
    t0 = time.perf_counter()
    emb = await embed_query(check.mask(q)[:300])
    t_emb = time.perf_counter() - t0
    kb = KB(
        ix=await knowledge.index(s), cards=cards.default(), dense=await knowledge.nearest(s, emb)
    )
    res = await run_turn(q, ctx, kb=kb)
    a = res.answer
    return {
        "sec": round(time.perf_counter() - t0, 2),
        "embed": round(t_emb, 2),
        "route": a.trace.route,
        "llm_used": a.trace.prompts,
        "dropped": a.trace.dropped,
        "brief": [x.text for x in a.brief.lines] if a.brief else [],
        "first": a.sections[0].sentences[0].text if a.sections and a.sections[0].sentences else "",
    }


async def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    from app.agent.llm import embed_query
    from app.agent.v3 import check
    from app.agent.v3.answer import KB
    from app.agent.v3.schemas import TurnContext
    from app.agent.v3.turn import run_turn
    from app.config import settings
    from app.db import SessionLocal
    from app.knowledge import cards
    from app.knowledge import service as knowledge

    if not settings.llm_live:
        sys.exit("LLM_LIVE=true 가 필요해요")
    qs = [
        json.loads(x)["q"]
        for x in (HERE / "gpt_compare_questions.jsonl").read_text("utf-8").splitlines()
        if x.strip()
    ]
    ctx = TurnContext(user_id=uuid.UUID(int=0), today=date(2026, 11, 19), mode="llm")
    base_roles = settings.openai_light_roles
    configs = [
        ("지금 설정", base_roles),
        ("모두 luna", "orchestrator,trade,quote_explanation,schedule"),
    ]
    out = {}
    async with SessionLocal() as s:
        for name, roles in configs:
            settings.openai_light_roles = roles
            out[name] = [
                await one(q, ctx, s, knowledge, cards, KB, run_turn, embed_query, check) for q in qs
            ]
    settings.openai_light_roles = base_roles
    print(
        json.dumps(
            {
                "agent_model": settings.openai_agent_model,
                "effort": settings.openai_reasoning_effort,
                "light": settings.openai_light_model,
                "base_light_roles": base_roles,
                "runs": out,
            },
            ensure_ascii=False,
            indent=1,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
