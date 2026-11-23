"""v3 에이전트 시험용 지식: 저장소에 있는 RAG CSV(상담 · 팀 · 책) + v3 지식 요지로 만든 검색 색인과 카드.

운영은 같은 CSV를 data_ingest로 DB에 넣고 knowledge.service.index로 읽는다. 시험은 DB 없이 같은 규칙(sources.assemble)으로 읽는다.
"""

import csv
import hashlib
import json
from functools import cache
from pathlib import Path

from app.agent.v3.answer import KB
from app.knowledge import bm25, cards
from app.knowledge.sources import assemble
from app.knowledge.v3_csv import START2, START3
from app.knowledge.v3_csv import rows as v3_rows

ROOT = Path(__file__).resolve().parents[2]
CSV_DIRS = [ROOT / "data/processed", ROOT / "data/consult"]
V3 = ROOT / "data/v3/knowledge/chunks.jsonl"
V3_ITER2 = ROOT / "data/v3/knowledge/iter2/chunks.jsonl"  # 개선 2회차(K21001~)
V3_ITER3 = ROOT / "data/v3/knowledge/iter3/chunks.jsonl"  # 개선 3회차(K22001~)


def datasets() -> list[tuple[str, list[dict[str, str]]]]:
    out = []
    for d in CSV_DIRS:
        for p in sorted(d.glob("*_rag.csv")):
            with p.open(encoding="utf-8-sig", newline="") as f:
                out.append((p.stem, list(csv.DictReader(f))))
    if V3.exists():
        raw = V3.read_bytes()
        lines = [json.loads(x) for x in raw.decode("utf-8-sig").splitlines() if x.strip()]
        out.append(("v3_knowledge_rag", v3_rows(lines, hashlib.sha256(raw).hexdigest())))
    for key, path, start in (
        ("v3_knowledge_iter2_rag", V3_ITER2, START2),
        ("v3_knowledge_iter3_rag", V3_ITER3, START3),
    ):
        if path.exists():
            raw = path.read_bytes()
            lines = [json.loads(x) for x in raw.decode("utf-8-sig").splitlines() if x.strip()]
            out.append((key, v3_rows(lines, hashlib.sha256(raw).hexdigest(), start)))
    return out


def expert_datasets() -> list[tuple[str, list[dict[str, str]]]]:
    """공정 지식 묶음(app/knowledge/expert/*.jsonl). 운영은 expert_pack ingest로 DB에 넣어요."""
    from app.knowledge import expert_pack

    data, problems = expert_pack.check()
    if problems:
        raise ValueError(f"공정 지식 묶음 검사 실패: {problems[0]}")
    return [(expert_pack.KEY, expert_pack.rows(data))]


@cache
def repo_index() -> bm25.Index:
    chunks, docs = assemble(datasets())
    return bm25.build(chunks, docs, "repo")


@cache
def eval_index() -> bm25.Index:
    """평가 색인: 저장소 지식 + 공정 지식 묶음(운영 DB와 같은 자료). 백엔드 시험은 repo_index 그대로예요."""
    chunks, docs = assemble([*datasets(), *expert_datasets()])
    return bm25.build(chunks, docs, "repo+expert")


def repo_kb() -> KB:
    return KB(ix=repo_index(), cards=cards.default())
