"""LLM 모드 한 턴 토큰 · 비용 어림(유료 호출 0회): llm.structured를 가로채 보낼 메시지만 모아 o200k로 센다.

    cd backend && LLM_LIVE=false OPENAI_API_KEY= PYTHONPATH=.:tests uv run python ../evaluation/v3/cost_estimate.py
- 출력 토큰은 답 2~4문장 JSON(문장 4개 × 약 60토큰 + 인용) ≈ 250으로 어림. 추론 토큰(low)은 따로 +200으로 어림.
- 값(100만 토큰): terra 입력 $1.00 · 출력 $5.00, luna 입력 $0.10 · 출력 $0.50, 임베딩 $0.02 (agent-web.md C15)
"""

import asyncio
import json
import sys
import uuid
from datetime import date
from pathlib import Path

import tiktoken

HERE = Path(__file__).resolve().parent
QS = [
    "34평 아파트 도배를 처음 해 보는데 뭐부터 해야 해요?", "실크벽지랑 합지벽지 차이가 뭐예요? 어떤 게 나아요?",
    "33평 아파트 전체 도배 비용 얼마 정도 해요?", "도배한 지 2주 됐는데 벽지 이음매가 벌어졌어요. 하자인가요?",
    "몰딩 교체하고 도배도 하려는데 순서를 어떻게 해야 해요?", "곰팡이 핀 벽은 도배 전에 어떻게 처리하는지 사진으로 보여 줘",
    "도배 끝나고 창문 열어도 되나요?", "이 견적서에서 철거 줄은 왜 합계에 없어요?", "실측은 언제 와요?",
    "도배 업체 한 곳만 추천해 주세요", "화장실 문 교체하려면 어떻게 해요?", "오늘 점심 뭐 먹지?",
    "욕실 타일 견적 계산해 줘", "도배 공사 며칠 걸려요?",
]  # fmt: skip
PRICE = {"gpt-6.1-terra": (1.00, 5.00), "gpt-6-luna": (0.10, 0.50)}
OUT_TOK, REASON_TOK = 250, 200


async def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.path.insert(0, str(HERE))
    import coverage_check as cc
    from v3_kb import repo_kb

    from app.agent import llm
    from app.agent.v3.schemas import TurnContext
    from app.agent.v3.turn import run_turn

    enc = tiktoken.get_encoding("o200k_base")
    calls: list[tuple[str, int]] = []

    async def capture(role, schema, messages):
        name, effort = llm.model_for(role)
        calls.append((f"{name}|{effort}", sum(len(enc.encode(t)) for _, t in messages)))
        raise llm.LLMError("어림만")

    llm.structured = capture  # type: ignore[assignment]
    kb = repo_kb()
    rows = []
    for q in QS:
        calls.clear()
        ctx = TurnContext(user_id=uuid.UUID(int=0), today=date(2026, 11, 19), mode="llm")
        r = await run_turn(q, ctx, kb=kb, facts=cc.FACTS)
        usd = 0.0
        for model_eff, tin in calls:
            model, eff = model_eff.split("|")
            pin, pout = PRICE[model]
            out = OUT_TOK + (REASON_TOK if eff not in ("none", "") else 0)
            usd += tin / 1e6 * pin + out / 1e6 * pout
        emb = len(enc.encode(q)) / 1e6 * 0.02
        rows.append({"q": q, "route": r.answer.trace.route, "llm_calls": [c[0] for c in calls],
                     "in_tokens": [c[1] for c in calls], "usd": round(usd + emb, 6)})  # fmt: skip
    print(json.dumps(rows, ensure_ascii=False, indent=1))
    tot = sum(x["usd"] for x in rows)
    print("평균 한 턴 $", round(tot / len(rows), 6), "· 1만 턴 $", round(tot / len(rows) * 1e4, 2))


if __name__ == "__main__":
    asyncio.run(main())
