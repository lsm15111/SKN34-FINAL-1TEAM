"""일반 설명(믿집 자료 밖) 실제 호출 평가. 유료 — 실행 전에 어림 비용을 찍어요. 프로젝트 없음 맥락만 돌려요.

    cd backend && PYTHONPATH=".;tests;../evaluation;../evaluation/v3" LLM_LIVE=true \
      DATABASE_URL=...mitjip_v3 uv run python ../evaluation/v3/general_eval.py --tag g1

- 질문: general_questions.jsonl(무엇 · 어떻게 16개 · 빼야 할 질문 21개, 켜기 전에 적어 두고 고르기에 쓰지 않음)
  + 질문 은행 held-out 도배 · 목공 26개(data/v3/questions, 처음 보는 말투)
- 지식: DB 적재본(knowledge.index) + 질문 임베딩 의미 순위(knowledge.nearest) — 운영과 같아요
- 남기는 것: .cache/<tag>/general_answers.jsonl (공개 답 · 일반 설명 여부 · 지시문 · 뺀 이유 · 실제 토큰 · 값)
"""

import argparse
import asyncio
import json
import sys
import time
import uuid
from collections import Counter
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
PRICE = {
    "gpt-6.1-terra": (1.00, 5.00, 0.05),
    "gpt-6-luna": (0.10, 0.50, 0.01),
}  # 100만 토큰당 입력 · 출력 · 캐시


def usd(u: dict) -> float:
    pin, pout, pcache = PRICE.get(u["model"], (1.0, 5.0, 0.05))
    return (
        max(u["input"] - u["cached"], 0) * pin + u["cached"] * pcache + u["output"] * pout
    ) / 1e6


def questions() -> list[dict]:
    rows = [
        json.loads(x)
        for x in (HERE / "general_questions.jsonl").read_text("utf-8").splitlines()
        if x.strip()
    ]
    for f in sorted((ROOT / "data/v3/questions").glob("*.jsonl")):
        for x in f.read_text("utf-8").splitlines():
            if not x.strip():
                continue
            q = json.loads(x)
            if q["trade"] in ("dobae", "mokgong") and q["split"] == "heldout":
                rows.append(
                    {"id": q["id"], "group": "heldout", "q": q["text"], "expect": q["expect"]}
                )
    return rows


async def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="g1")
    ap.add_argument("--only", default="", help="쉼표로 질문 id만")
    a = ap.parse_args()

    from app.agent import llm
    from app.agent.v3.answer import KB
    from app.agent.v3.schemas import TurnContext
    from app.agent.v3.turn import run_turn
    from app.chat.service import _public
    from app.chat.tools import general_facts
    from app.config import settings
    from app.db import SessionLocal
    from app.knowledge import cards
    from app.knowledge import service as knowledge

    if not settings.llm_live:
        sys.exit("LLM_LIVE=true 가 필요해요(유료)")
    usage: list[dict] = []
    llm.USAGE_HOOK = usage.append
    qs = questions()
    if a.only:
        keep = set(a.only.split(","))
        qs = [q for q in qs if q["id"] in keep]
    model = llm.model_for("general")[0]
    pin, pout, _ = PRICE.get(model, (1.0, 5.0, 0.05))
    print(
        f"턴 {len(qs)}개 · 일반 설명 {model} · 어림 비용 ${len(qs) * 2 * (2200 * pin + 300 * pout) / 1e6:.3f}"
    )
    out_dir = HERE / ".cache" / a.tag
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    async with SessionLocal() as s:
        ix = await knowledge.index(s)
        for q in qs:
            usage.clear()
            t0 = time.perf_counter()
            emb = await llm.embed_query(q["q"])
            kb = KB(ix=ix, cards=cards.default(), dense=await knowledge.nearest(s, emb))
            today = date(2026, 11, 20)
            ctx = TurnContext(user_id=uuid.UUID(int=0), today=today, mode="llm")
            r = await run_turn(q["q"], ctx, kb=kb, general=general_facts(q["q"], today))
            pub = _public(r.answer)
            gen = [x for sec in pub.sections if sec.source == "general" for x in sec.sentences]
            cost = sum(usd(u) for u in usage)
            rows.append({**q, "route": r.answer.trace.route, "trades": r.answer.trace.trades,
                         "policy": r.answer.trace.policy, "prompts": r.answer.trace.prompts,
                         "dropped": r.answer.trace.dropped, "general": gen,
                         "unknown": pub.unknown, "s": round(time.perf_counter() - t0, 2),
                         "usd": round(cost, 6), "answer": pub.model_dump(mode="json")})  # fmt: skip
            tag = (
                "일반"
                if gen
                else ("작성기" if "composer_v3" in r.answer.trace.prompts else "그 밖")
            )
            print(
                q["id"],
                q["group"],
                r.answer.trace.route,
                r.answer.trace.trades,
                tag,
                f"${cost:.5f}",
            )
    with (out_dir / "general_answers.jsonl").open("w", encoding="utf-8") as fh:
        for x in rows:
            fh.write(json.dumps(x, ensure_ascii=False) + "\n")
    for grp in ("what_how", "exclude", "heldout"):
        g = [x for x in rows if x["group"] == grp]
        if not g:
            continue
        c = Counter("일반" if x["general"] else ("작성기" if "composer_v3" in x["prompts"] else (
            "모름" if any("확인하지 못했어요" in u for u in x["unknown"]) else "그 밖")) for x in g)  # fmt: skip
        print(f"{grp} {len(g)}개: {dict(c)}")
    bad = [x["id"] for x in rows if x["group"] == "exclude" and x["general"]]
    print(f"빼야 할 질문에서 일반 설명이 나온 턴: {len(bad)} {bad}")
    print(
        f"실제 사용량 합계 ${sum(x['usd'] for x in rows):.4f} · 평균 {sum(x['s'] for x in rows) / max(len(rows), 1):.2f}초"
    )


if __name__ == "__main__":
    asyncio.run(main())
