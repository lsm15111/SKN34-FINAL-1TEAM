"""점검 질문의 의미 검색 순위를 한 번 만들어 둔다(coverage_check · unknown_check --dense가 읽음).

    cd backend && LLM_LIVE=true DATABASE_URL=<임베딩을 넣은 DB> uv run python ../evaluation/v3/dense_prep.py

- 유료 호출: 질문 임베딩만(llm.embed_texts). LLM 답 쓰기는 부르지 않아요(structured · jev는 부르면 오류).
- 임베딩할 글은 서비스와 같다: check.mask(질문)[:300]. 이미 만든 글은 .cache/q_embed.json에서 다시 써요.
- 순위: knowledge.nearest(DB 활성 버전, 위 dense_n개) → .cache/q_dense.json {글: [rid, ...]}.
"""

import asyncio
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for p in (ROOT / "backend", ROOT / "backend/tests", ROOT / "evaluation", HERE):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import coverage_check as cc

from app.agent import llm
from app.agent.v3 import check
from app.config import settings

CACHE = HERE / ".cache"
EMB = CACHE / "q_embed.json"
DENSE = CACHE / "q_dense.json"


def key(text: str) -> str:
    return check.mask(text)[:300]


async def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    from app.db import SessionLocal
    from app.knowledge import service as knowledge

    llm.structured = cc._no_paid  # type: ignore[assignment]
    llm.jev_choice = cc._no_paid  # type: ignore[assignment]
    CACHE.mkdir(exist_ok=True)
    emb: dict = json.loads(EMB.read_text(encoding="utf-8")) if EMB.exists() else {}
    texts = list(dict.fromkeys(key(q["text"]) for q in cc.load_sets()))
    todo = [
        t for t in texts if t not in emb and t.strip()
    ]  # 빈 글은 서비스도 임베딩 실패 → 키워드만
    if todo and not settings.llm_live:
        sys.exit(f"임베딩이 없는 질문 {len(todo)}개: LLM_LIVE=true로 다시 돌려요")
    chars = sum(len(t) for t in todo)
    for i in range(0, len(todo), 64):
        r = await llm.embed_texts(todo[i : i + 64])
        if r is None:
            sys.exit("임베딩 실패")
        for t, v in zip(todo[i : i + 64], r[1], strict=True):
            emb[t] = [r[0], v]
    if todo:
        EMB.write_text(json.dumps(emb), encoding="utf-8")
    dense: dict[str, list[str]] = {}
    async with SessionLocal() as s:
        for t in texts:
            dense[t] = list(await knowledge.nearest(s, tuple(emb[t]) if t in emb else None))
    DENSE.write_text(json.dumps(dense, ensure_ascii=False), encoding="utf-8")
    empty = sum(1 for v in dense.values() if not v)
    print({"texts": len(texts), "embedded_now": len(todo), "chars_now": chars, "empty_rank": empty})


def load() -> dict[str, tuple[str, ...]]:
    """점검 스크립트용: 글 → 의미 검색 순위. 없으면 멈춘다."""
    if not DENSE.exists():
        sys.exit("의미 검색 순위가 없어요: 먼저 dense_prep.py를 돌려요")
    return {k: tuple(v) for k, v in json.loads(DENSE.read_text(encoding="utf-8")).items()}


if __name__ == "__main__":
    asyncio.run(main())
