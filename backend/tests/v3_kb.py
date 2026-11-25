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
from app.knowledge.v3_csv import START2
from app.knowledge.v3_csv import rows as v3_rows

ROOT = Path(__file__).resolve().parents[2]
CSV_DIRS = [ROOT / "data/processed", ROOT / "data/consult"]
V3 = ROOT / "data/v3/knowledge/chunks.jsonl"
V3_ITER2 = ROOT / "data/v3/knowledge/iter2/chunks.jsonl"  # 개선 2회차(K21001~)


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
    if V3_ITER2.exists():
        raw = V3_ITER2.read_bytes()
        lines = [json.loads(x) for x in raw.decode("utf-8-sig").splitlines() if x.strip()]
        out.append(
            ("v3_knowledge_iter2_rag", v3_rows(lines, hashlib.sha256(raw).hexdigest(), START2))
        )
    return out


@cache
def repo_index() -> bm25.Index:
    chunks, docs = assemble(datasets())
    return bm25.build(chunks, docs, "repo")


def repo_kb() -> KB:
    return KB(ix=repo_index(), cards=cards.default())
