"""RAG 평가용 합친 말뭉치. 서버 적재용 CSV를 서버 검색과 같은 규칙(backend/app/knowledge/sources.py)으로 읽는다.

    python evaluation/rag/corpus.py            # evaluation/rag/.cache/corpus.json
    python evaluation/rag/corpus.py --no-local # 로컬 추가 자료(책 등) 빼기

읽는 CSV
- data/processed/*_rag.csv: 팀 전처리 자료 → K2001~ (파일 이름 순 → id 순)
- data/consult/*_rag.csv: 화면 자료(rag5) → K1~ (`ref` 열)
- data/local/*_rag.csv: 로컬 추가 자료(git 제외, 책 등) → K5001~ (`ref` 열)
화면 자료 CSV는 `python -m app.knowledge.json_csv`로 JSON에서 만든다.
"""

import argparse
import csv
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.knowledge.sources import assemble

DIRS = [ROOT / "data/processed", ROOT / "data/consult"]
LOCAL = ROOT / "data/local"
OUT = Path(__file__).parent / ".cache/corpus.json"


def read(path: Path) -> tuple[str, list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return path.stem, list(csv.DictReader(f))


def build(with_local: bool) -> dict:
    dirs = DIRS + ([LOCAL] if with_local and LOCAL.is_dir() else [])
    datasets = [read(p) for d in dirs for p in sorted(d.glob("*_rag.csv"))]
    chunks, docs = assemble(datasets)
    versions = sorted({r["source_version"] for _, rows in datasets for r in rows[:1] if "ref" in r})
    team = sum(1 for c in chunks if 2001 <= int(c.ref[1:]) < 5000)
    return {
        "version": "+".join([*versions, f"team{team}"]),
        "docs": {k: asdict(d) for k, d in docs.items()},
        "chunks": [
            {
                "k": c.ref,
                "doc": c.doc,
                "sec": c.sec,
                "text": c.text,
                "hints": list(c.hints),
                "trades": list(c.trades),
            }
            for c in chunks
        ],
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-local", action="store_true")
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    c = build(not a.no_local)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")
    print(f"{a.out.name} · {len(c['chunks'])}조각 · {c['version']}")
