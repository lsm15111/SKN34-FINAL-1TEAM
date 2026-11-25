"""v3 평가 말뭉치: 지금 말뭉치(evaluation/rag/corpus.py와 같은 CSV) + 데이터 담당 v3 지식 요지(K20001~, app.knowledge.v3_csv.START).

    cd backend && .venv/Scripts/python.exe ../evaluation/v3/corpus3.py

- v3 지식 JSONL은 app.knowledge.v3_csv로 CSV(.cache/v3_knowledge_rag.csv)를 만든 뒤 같은 규칙(sources.assemble)으로 읽어요.
- 출력: .cache/corpus3.json (git 밖). 카드 검사 · 묶음 · E2 · E3가 이 파일을 먼저 봐요(없으면 corpus.json).
- 제품 쪽 적재(data_ingest)는 B6 · 리드 몫이에요(verification/b5.md '다른 묶음에 부탁').
"""

import csv
import hashlib
import json
from dataclasses import asdict

from common import CACHE, ROOT, utf8_stdout
from corpus import DIRS, _digest, read

from app.knowledge.json_csv import EXTRA, REQUIRED
from app.knowledge.sources import assemble
from app.knowledge.v3_csv import START2, rows

SRC = ROOT / "data/v3/knowledge/chunks.jsonl"
CSV_OUT = CACHE / "v3_knowledge_rag.csv"
SRC2 = ROOT / "data/v3/knowledge/iter2/chunks.jsonl"  # 개선 2회차(K21001~)
CSV_OUT2 = CACHE / "v3_knowledge_iter2_rag.csv"
OUT = CACHE / "corpus3.json"


def main() -> None:
    utf8_stdout()
    raw = SRC.read_bytes()
    lines = [json.loads(x) for x in raw.decode("utf-8-sig").splitlines() if x.strip()]
    v3 = rows(lines, hashlib.sha256(raw).hexdigest())
    CACHE.mkdir(parents=True, exist_ok=True)
    with CSV_OUT.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=REQUIRED + EXTRA, lineterminator="\n")
        w.writeheader()
        w.writerows(v3)
    extra = [read(CSV_OUT)]
    if SRC2.exists():
        raw2 = SRC2.read_bytes()
        lines2 = [json.loads(x) for x in raw2.decode("utf-8-sig").splitlines() if x.strip()]
        with CSV_OUT2.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=REQUIRED + EXTRA, lineterminator="\n")
            w.writeheader()
            w.writerows(rows(lines2, hashlib.sha256(raw2).hexdigest(), START2))
        extra.append(read(CSV_OUT2))
    datasets = [read(p) for d in DIRS for p in sorted(d.glob("*_rag.csv"))] + extra
    chunks, docs = assemble(datasets)
    versions = sorted(
        f"{key}@{_digest(r['source_sha256'] for r in rs)[:12]}"
        for key, rs in datasets
        if rs and "ref" in rs[0]
    )
    team = sum(1 for c in chunks if 2001 <= int(c.ref[1:]) < 5000)
    out = {
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
    OUT.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"{OUT.name} · {len(chunks)}조각(v3 지식 {len(v3)}) · {out['version']}")


if __name__ == "__main__":
    main()
