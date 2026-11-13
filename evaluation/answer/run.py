"""답 품질 평가 1단계: 30문항을 실제 상담 흐름(/v2/ask와 같은 ask.start)으로 답하게 하고 기록한다. 유료.

    cd backend && uv run python ../evaluation/answer/run.py [--limit 30] [--cap 2.0]

- LLM_LIVE=true · OPENAI_API_KEY가 필요하다. DATABASE_URL은 지식 자료가 활성인 DB(예: mitjip_rag)
- 입구 관문의 Jev(별도 유료)는 끈다: 학습 모델 신뢰도가 낮으면 관문 없이 진행
- 화면 도구(고객 상태 저장 · 단계 카드)는 실행한 셈 치고 {"ok": true}로 돌려준다
- 실제 토큰 사용량으로 비용을 세고, 누적이 --cap 달러를 넘으면 멈춘다
- 결과: evaluation/answer/.cache/answers.jsonl (질문 · 답 · 근거 · 보여 준 조각 글 · 도구 · 토큰 · 비용)
"""

import argparse
import asyncio
import json
import sys
import time
from datetime import date
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parents[1] / "backend"))

from app.agent import llm
from app.config import settings
from app.v2 import ask
from app.v2 import schemas as v2

# 2026-11-13 공식 가격, 달러/100만 토큰 (입력 · 캐시 입력 · 출력)
PRICE = {"gpt-6.1-terra": (1.0, 0.05, 5.0)}
QUOTE = {"pyeong": 32, "cats": ["wallpaper", "carpentry"], "tier": "basic"}
PROFILE = {"pyeong": 32, "scope": "도배 · 목공", "tier": "basic"}


def cost(model: str, u: dict) -> float:
    p_in, p_cached, p_out = PRICE[model]
    fresh = u["input"] - u["cached"]
    return (fresh * p_in + u["cached"] * p_cached + u["output"] * p_out) / 1_000_000


async def no_jev(*_a, **_k):
    raise llm.LLMError("평가에서는 Jev를 쓰지 않는다")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", type=Path, default=HERE / "set30.jsonl")
    ap.add_argument("--out", type=Path, default=HERE / ".cache" / "answers.jsonl")
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--cap", type=float, default=2.0, help="누적 비용 상한(달러)")
    a = ap.parse_args()
    if not settings.llm_live:
        raise SystemExit("LLM_LIVE=true가 필요해요")
    model = settings.openai_agent_model
    if model not in PRICE:
        raise SystemExit(f"가격을 모르는 모델이에요: {model}")
    qs = [json.loads(x) for x in a.set.read_text(encoding="utf-8").splitlines() if x.strip()]
    qs = qs[: a.limit]
    a.out.parent.mkdir(parents=True, exist_ok=True)

    llm.jev_choice = no_jev
    real_chat, real_search = llm.chat_tools, ask._search
    rec: dict = {}

    async def chat(system, messages, tools):
        r = await real_chat(system, messages, tools)
        rec["calls"].append({"tools": [c["name"] for c in r["tool_calls"]], "usage": r["usage"]})
        return r

    async def search(q, **kw):
        r = await real_search(q, **kw)
        for h in r.hits:
            rec["shown"].setdefault(h.ref, {"ref": h.ref, "source_type": h.source_type,
                                            "title": h.title, "section": h.section, "text": h.text})  # fmt: skip
        rec["searches"].append({"query": q, "enough": r.enough, "refs": [h.ref for h in r.hits]})
        return r

    llm.chat_tools, ask._search = chat, search
    total = 0.0
    with a.out.open("w", encoding="utf-8") as f:
        for i, q in enumerate(qs, 1):
            rec.clear()
            rec.update(calls=[], shown={}, searches=[])
            t0 = time.perf_counter()
            body = v2.V2AskIn(message=q["text"], quote=QUOTE, profile=PROFILE)
            out = await ask.start(f"eval-{q['id']}", body, date(2026, 11, 13))
            for _ in range(6):  # 화면 도구는 실행한 셈 친다
                if out.done or not out.turn:
                    break
                res = v2.V2AskResumeIn(
                    results=[{"id": c.id, "content": '{"ok": true}'} for c in out.tool_calls]
                )
                out = await ask.resume(f"eval-{q['id']}", out.turn, res)
            usage = {
                k: sum(c["usage"][k] for c in rec["calls"]) for k in ("input", "cached", "output")
            }
            c = cost(model, usage)
            total += c
            row = {
                **{k: q[k] for k in ("id", "split", "kind", "set", "trade", "text", "answer_type", "note")},
                "gold": [g["ref"] for g in q["gold"] if g["grade"] == 2],
                "answer": out.text, "failed": out.failed, "gate": out.gate,
                "intent": out.intent.model_dump() if out.intent else None,
                "dropped": out.dropped, "cites_dropped": out.cites_dropped,
                "sources": [s.ref for s in out.sources], "suggest": [s.text for s in out.suggest],
                "searches": rec["searches"], "shown": list(rec["shown"].values()),
                "calls": rec["calls"], "usage": usage, "cost": round(c, 5),
                "seconds": round(time.perf_counter() - t0, 1),
            }  # fmt: skip
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            print(f"{i:2d}/{len(qs)} {q['id']} {row['seconds']}초 · LLM {len(rec['calls'])}번 · "
                  f"${c:.4f} (누적 ${total:.4f})", flush=True)  # fmt: skip
            if total > a.cap:
                print(f"비용 상한 ${a.cap}을 넘어 멈춰요", flush=True)
                break
    print(f"끝 · {a.out.name} · 합계 ${total:.4f}")


if __name__ == "__main__":
    asyncio.run(main())
