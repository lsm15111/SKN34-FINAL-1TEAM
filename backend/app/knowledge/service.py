"""지식 검색: 활성 지식 버전을 색인해 두고 키워드(BM25)로 찾는다. LLM · 임베딩 호출 없음.

색인은 활성 버전 목록이 바뀔 때만 다시 만든다 (프로세스마다 한 벌).
"""

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from app.knowledge import bm25, repository
from app.knowledge.sources import assemble

_cache: tuple[tuple[str, ...], bm25.Index] | None = None


def _build(datasets: list[tuple[str, list[dict]]], version: str) -> bm25.Index:
    chunks, docs = assemble(datasets)
    return bm25.build(chunks, docs, version)


async def index(s: AsyncSession) -> bm25.Index:
    global _cache
    versions = await repository.active_versions(s)
    key = tuple(sorted(str(v) for v, _ in versions))
    if _cache and _cache[0] == key:
        return _cache[1]
    datasets = await repository.chunk_rows(s, versions)
    # 색인 만들기는 0.3초쯤 걸려 작업 스레드로 넘긴다. 동시에 두 번 만들어도 결과는 같다
    ix = await asyncio.to_thread(_build, datasets, ",".join(key))
    _cache = (key, ix)
    return ix


async def search(
    s: AsyncSession,
    q: str,
    *,
    queries: list[str] | tuple[str, ...] = (),
    trade: str | None = None,
    k: int = 6,
    policy_text: str | None = None,
) -> bm25.Result:
    """질문(+ 검색어 여러 개)으로 근거 조각을 찾는다. 활성 자료가 없으면 빈 결과"""
    ix = await index(s)
    return bm25.search(ix, q, queries=queries, trade=trade, k=k, policy_text=policy_text)


async def verify_cites(s: AsyncSession, text: str) -> tuple[str, int]:
    """[K번호] 인용 중 문장과 맞지 않는 것을 뗀다. (고친 글, 뗀 수)"""
    return bm25.verify_cites(await index(s), text)
