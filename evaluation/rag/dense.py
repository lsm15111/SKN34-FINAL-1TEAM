"""의미 검색(임베딩) 순위: 질문 임베딩으로 DB(pgvector)의 활성 지식 조각을 가까운 순서로 뽑는다.

    cd backend && uv run python ../evaluation/rag/dense.py [--k 50]

- 질문 임베딩은 .cache/qvec.json에 두고 다시 쓴다 (질문이 바뀐 것만 새로 부른다. 유료: 질문 90개 약 2천 토큰)
- 결과: .cache/dense.json {질문 id: [조각 번호 ...]}
- DATABASE_URL은 조각 임베딩이 들어 있는 DB (예: mitjip_rag)
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parents[1] / "backend"))

from openai import AsyncOpenAI
from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.knowledge import repository
from app.knowledge.models import RagChunk
from app.knowledge.sources import assemble
from app.refprice.models import RefDatasetVersion

CACHE = HERE / ".cache"


async def embed(texts: list[str]) -> list[list[float]]:
    client = AsyncOpenAI(api_key=settings.openai_api_key.get_secret_value(), max_retries=2)
    try:
        r = await client.embeddings.create(
            model=settings.openai_embedding_model, input=texts, dimensions=1536
        )
        print(f"임베딩 {len(texts)}개 · {r.usage.total_tokens}토큰")
        return [d.embedding for d in sorted(r.data, key=lambda d: d.index)]
    finally:
        await client.close()


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", type=Path, default=HERE / "questions.jsonl")
    ap.add_argument("--k", type=int, default=50)
    ap.add_argument("--out", type=Path, default=CACHE / "dense.json")
    a = ap.parse_args()
    qs = [json.loads(x) for x in a.questions.read_text(encoding="utf-8").splitlines() if x.strip()]
    path = CACHE / "qvec.json"
    vec = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    todo = [q for q in qs if vec.get(q["id"], {}).get("text") != q["text"]]
    if todo:
        for q, v in zip(todo, await embed([q["text"] for q in todo]), strict=True):
            vec[q["id"]] = {"text": q["text"], "v": v}
        path.write_text(json.dumps(vec), encoding="utf-8")
    async with SessionLocal() as s:
        versions = await repository.active_versions(s)
        datasets = await repository.chunk_rows(s, versions)
        chunks, _ = assemble(datasets)
        ref_of = {c.rid: c.ref for c in chunks}
        ids = [v for v, _ in versions]
        out = {}
        for q in qs:
            rows = await s.execute(
                select(RefDatasetVersion.dataset_key, RagChunk.record_key)
                .join(RefDatasetVersion, RefDatasetVersion.id == RagChunk.dataset_id)
                .where(RagChunk.dataset_id.in_(ids), RagChunk.embedding.is_not(None))
                .order_by(RagChunk.embedding.cosine_distance(vec[q["id"]]["v"]))
                .limit(a.k)
            )
            out[q["id"]] = [ref_of[f"{k}/{r}"] for k, r in rows]
    a.out.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"{a.out.name} · {len(out)}문항 · 위 {a.k}개")


if __name__ == "__main__":
    asyncio.run(main())
