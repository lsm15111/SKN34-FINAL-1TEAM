"""키워드(BM25) + 의미 검색(임베딩) 합치기 가중치를 dev 질문으로 고른다. DB · LLM 없이.

python evaluation/rag/dense.py 를 먼저 돌려 .cache/dense.json을 만든다 (backend 폴더에서 uv run)
python evaluation/rag/hybrid.py            # dev 격자 탐색
python evaluation/rag/hybrid.py --final    # 고른 설정으로 held-out까지 한 번
"""

import argparse
import itertools
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from metrics import load_questions, report
from rank_server import bm25, load_index

GRID = {
    "dense_w": [0.0, 0.5, 0.75, 1.0, 1.25],
    "trade_w": [0.0, 0.004, 0.008, 0.012, 0.016, 0.024],
}
KEYWORD_ONLY = {"dense_w": 0.0, "trade_w": 0.0}


def rank(ix, qs, dense, conf, k=20, with_trade=False) -> dict:
    old = dict(bm25.CONF)
    bm25.CONF.update(conf)
    try:
        out = {"name": json.dumps(conf), "rankings": {}, "enough": {}}
        for q in qs:
            near = [ix.by_ref[r].chunk.rid for r in dense.get(q["id"], []) if r in ix.by_ref]
            tr = q["trade"] if with_trade and q["trade"] != "공통" else None
            r = bm25.search(ix, q["text"], k=k, trade=tr, dense=near)
            out["rankings"][q["id"]] = [h.ref for h in r.hits]
            out["enough"][q["id"]] = r.enough
        return out
    finally:
        bm25.CONF.clear()
        bm25.CONF.update(old)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--final", action="store_true")
    ap.add_argument("--conf", help='볼 설정 JSON (비우면 bm25.CONF 기본값), 예: {"dense_w": 1.0}')
    a = ap.parse_args()
    ix = load_index(HERE / ".cache" / "corpus.json")
    qs = load_questions(HERE / "questions.jsonl")
    dense = json.loads((HERE / ".cache" / "dense.json").read_text(encoding="utf-8"))
    if a.final:
        conf = json.loads(a.conf or "{}")
        for label, splits in (("dev", {"dev"}), ("held-out", {"heldout"})):
            for name, c in (("키워드만", KEYWORD_ONLY), ("설정", conf)):
                for wt in (False, True):
                    r = report(rank(ix, qs, dense, c, with_trade=wt), qs, splits)
                    print(label, name, "공정 넘김" if wt else "", json.dumps(r, ensure_ascii=False))
        return
    rows = []
    keys = list(GRID)
    for vals in itertools.product(*GRID.values()):
        conf = dict(zip(keys, vals, strict=True))
        r = report(rank(ix, qs, dense, conf), qs, {"dev"})["전체"]
        rows.append((r["hit@5"], r["mrr"], r["ndcg@5"], r["hit@1"], r["recall@5"], conf))
    rows.sort(key=lambda x: (-x[0], -x[1], -x[2]))
    print("hit@5 · mrr · ndcg@5 · hit@1 · recall@5 · 설정")
    for row in rows[:12]:
        print(" · ".join(f"{v:.3f}" for v in row[:5]), json.dumps(row[5]))
    base = next(x for x in rows if x[5] == KEYWORD_ONLY)
    print("키워드만:", " · ".join(f"{v:.3f}" for v in base[:5]))


if __name__ == "__main__":
    main()
