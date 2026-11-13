"""서버 검색(backend/app/knowledge/bm25.py)으로 평가 질문마다 순위를 뽑는다. DB · LLM 없이 합친 말뭉치를 바로 읽는다.

python evaluation/rag/rank_server.py [--name server] [--k 20] [--trade]
python evaluation/rag/metrics.py evaluation/rag/.cache/rank_server.json
"""

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parents[1] / "backend"))

from app.knowledge import bm25


def load_index(path: Path) -> bm25.Index:
    j = json.loads(path.read_text(encoding="utf-8"))
    docs = {
        key: bm25.Doc(
            **{f: str(d.get(f) or "") for f in ("title", "pub", "date", "kind", "rel", "url")}
        )
        for key, d in j["docs"].items()
    }
    chunks = [
        bm25.Chunk(
            ref=c["k"],
            doc=c["doc"],
            text=c.get("text") or "",
            sec=c.get("sec") or "",
            hints=tuple(c.get("hints") or ()),
            trades=tuple(c.get("trades") or ()),
        )
        for c in j["chunks"]
    ]
    return bm25.build(chunks, docs, j.get("version") or "")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", type=Path, default=HERE / ".cache" / "corpus.json")
    ap.add_argument("--questions", type=Path, default=HERE / "questions.jsonl")
    ap.add_argument("--name", default="server")
    ap.add_argument("--k", type=int, default=20)
    ap.add_argument("--trade", action="store_true", help="질문의 공정(도배 · 목공)을 검색에 넘긴다")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    ix = load_index(a.corpus)
    qs = [json.loads(x) for x in a.questions.read_text(encoding="utf-8").splitlines() if x.strip()]
    out = {"name": a.name, "rag": "backend/app/knowledge/bm25.py", "version": ix.version, "k": a.k,
           "trade": a.trade, "rankings": {}, "enough": {}}  # fmt: skip
    for q in qs:
        trade = q["trade"] if a.trade and q["trade"] != "공통" else None
        r = bm25.search(ix, q["text"], k=a.k, trade=trade)
        out["rankings"][q["id"]] = [h.ref for h in r.hits]
        out["enough"][q["id"]] = r.enough
    path = a.out or HERE / ".cache" / f"rank_{a.name}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{a.name}: {len(qs)}문항 · {ix.version}")


if __name__ == "__main__":
    main()
