"""v3 검색 키워드만 vs 키워드 + 의미 검색(하이브리드) 비교: RAG 질문 세트 gold 조각이 위 5개 · 8개 안에 드는 비율.

    cd backend && uv run python ../evaluation/v3/hybrid_check.py   (DATABASE_URL = 임베딩을 넣은 DB)

- 유료 호출: 질문 임베딩만(질문 390개 ≈ 1만 토큰, 약 $0.0002). LLM 답 쓰기는 부르지 않아요.
- 색인은 DB 적재본(knowledge.index), 검색은 v3 answer.search와 같은 search3(공종 무게 · 출처 등급).
"""

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KO = {"도배": "dobae", "목공": "mokgong", "공통": "common"}


async def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    from app.agent import llm
    from app.agent.v3.answer import TAG_TO_CODE
    from app.config import settings
    from app.db import SessionLocal
    from app.knowledge import search3
    from app.knowledge import service as knowledge

    if not settings.llm_live:
        sys.exit("LLM_LIVE=false 라서 질문 임베딩을 만들 수 없어요")
    qs = []
    for f in ("questions.jsonl", "questions_300.jsonl"):
        for line in (ROOT / "evaluation/rag" / f).read_text(encoding="utf-8-sig").splitlines():
            q = json.loads(line) if line.strip() else None
            if q and q.get("gold"):
                qs.append((f, q))
    vecs = []
    for i in range(0, len(qs), 64):
        r = await llm.embed_texts([q["text"] for _, q in qs[i : i + 64]])
        if r is None:
            sys.exit("임베딩 실패")
        vecs += [(r[0], v) for v in r[1]]
    out: dict[str, dict[str, list[int]]] = {}
    async with SessionLocal() as s:
        ix = await knowledge.index(s)
        for (f, q), emb in zip(qs, vecs, strict=True):
            dense = await knowledge.nearest(s, emb)
            tr = KO.get(q.get("trade", ""), "common")
            want = [tr] if tr != "common" else []
            gold = {g["ref"] for g in q["gold"]}
            key = f"{f}:{q.get('split', '-')}"
            row = out.setdefault(key, {"n": [], "kw5": [], "hy5": [], "kw8": [], "hy8": []})
            row["n"].append(1)
            for name, d in (("kw", ()), ("hy", dense)):
                res = search3.search(ix, q["text"], trades=want, tags=TAG_TO_CODE, k=8, dense=d)
                refs = [h.ref for h in res.hits]
                row[f"{name}5"].append(int(bool(gold & set(refs[:5]))))
                row[f"{name}8"].append(int(bool(gold & set(refs[:8]))))
    for key, row in out.items():
        n = len(row["n"])
        print(key, n, {k: round(sum(v) / n, 3) for k, v in row.items() if k != "n"})


if __name__ == "__main__":
    asyncio.run(main())
