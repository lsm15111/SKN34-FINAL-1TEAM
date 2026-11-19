"""지식 보강 3회차: 나눠 쓴 조각(parts/*.jsonl)을 묶고 출처표를 만들어요. 원문을 길게 옮겼는지도 재요.

- 출력: chunks.jsonl · sources.csv(문서별 조각 수)
- 줄 순서 = 조각 번호(K22001부터, app.knowledge.v3_csv.START3). 카드가 번호로 인용하므로, chunks.jsonl이 이미 있으면
  있던 줄은 그 순서 그대로 두고 새 조각만 끝에 (빈 주제 · id 순으로) 더해요. 있던 조각이 parts에서 빠지면 멈춰요.
- 원문 옮김: 근거(evidence)가 저장소 사본(consult/rag5.json 조각 · data/processed CSV · data/v3 CSV)이면 2회차와 같이
  요지 · 해요체 요지와 근거 본문이 공백 빼고 가장 길게 같은 글자 수를 재요(웹에서 연 근거는 본문이 없어 못 재요).
실행: python -X utf8 data/v3/knowledge/iter3/build.py   (그다음 check.py)
"""

from __future__ import annotations

import csv
import importlib.util
import json
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
_spec = importlib.util.spec_from_file_location("iter2_build", HERE.parent / "iter2" / "build.py")
_it2 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_it2)  # 2회차와 같은 재기(local_texts · longest · COPY_LIMIT)
COPY_LIMIT, local_texts, longest = _it2.COPY_LIMIT, _it2.local_texts, _it2.longest

START3 = 22001  # app.knowledge.v3_csv.START3와 같아야 해요(보이기용)


def main() -> None:
    rows = []
    for p in sorted((HERE / "parts").glob("*.jsonl")):
        rows += [json.loads(x) for x in p.read_text(encoding="utf-8-sig").splitlines() if x.strip()]
    by_id = {r["id"]: r for r in rows}
    if len(by_id) != len(rows):
        raise SystemExit("parts에 같은 id가 두 번 있어요")
    out = HERE / "chunks.jsonl"
    old = (
        [json.loads(x)["id"] for x in out.read_text(encoding="utf-8").splitlines() if x.strip()]
        if out.exists()
        else []
    )
    gone = [i for i in old if i not in by_id]
    if gone:
        raise SystemExit(
            f"이미 번호를 받은 조각이 parts에서 빠졌어요(카드 인용이 틀어져요): {gone}"
        )
    new = sorted((r for r in rows if r["id"] not in set(old)), key=lambda r: (r["gap"], r["id"]))
    rows = [by_id[i] for i in old] + new
    texts = local_texts()
    measured, over, worst = 0, [], (0, "")
    for r in rows:
        ev = [texts[e] for e in r.get("evidence", []) if e in texts]
        if not ev:
            continue
        measured += 1
        n = max(longest(r[k], t) for k in ("summary", "summary_haeyo") for t in ev)
        if n > worst[0]:
            worst = (n, r["id"])
        if n > COPY_LIMIT:
            over.append(f"{r['id']}({n})")
    with out.open("w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    docs: dict[str, dict] = {}
    gaps = defaultdict(set)
    for r in rows:
        k = r["doc_key"]
        d = docs.setdefault(k, {"doc_key": k, "source_name": r["source_name"], "publisher": r.get("publisher", ""),
                                "kind": r.get("kind", ""), "source_url": r["source_url"], "license": r["license"],
                                "verify": set(), "chunk_count": 0})  # fmt: skip
        d["verify"].add(r.get("verify", ""))
        d["chunk_count"] += 1
        gaps[k].add(r["gap"])
    with (HERE / "sources.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["doc_key", "source_name", "publisher", "kind", "source_url", "license", "verify",
                    "chunk_count", "gaps"])  # fmt: skip
        for k, d in sorted(docs.items(), key=lambda kv: (-kv[1]["chunk_count"], kv[0])):
            w.writerow([k, d["source_name"], d["publisher"], d["kind"], d["source_url"], d["license"],
                        ";".join(sorted(d["verify"])), d["chunk_count"], ";".join(sorted(gaps[k]))])  # fmt: skip
    print(
        f"{len(rows)}조각(있던 {len(old)} · 새 {len(new)}) → chunks.jsonl K{START3}~K{START3 + len(rows) - 1}"
    )
    print(f"문서 {len(docs)}개 → sources.csv")
    print(
        f"원문 옮김(저장소 근거가 있는 {measured}조각): 가장 긴 같은 글자 {worst[0]}자({worst[1]}) · "
        f"{COPY_LIMIT}자 넘는 조각 {len(over)}개 {' '.join(over)}"
    )


if __name__ == "__main__":
    main()
