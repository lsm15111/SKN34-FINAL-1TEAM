"""화면 지식 자료(JSON: docs · chunks) → 팀 전처리 CSV 형식. 만든 CSV는 `python -m app.data_ingest`로 적재한다.

    python -m app.knowledge.json_csv ../frontend/public/v2/rag5.json ../data/consult/consult_knowledge_rag.csv
    python -m app.knowledge.json_csv ../frontend/public/v2/rag-local.json ../data/local/interior_guide_book_rag.csv

- 팀 열 그대로 + 검색에 쓰는 열(ref · doc · trades · hints · rel · doc_date · license · page_known)
- 쪽 번호를 모르는 자료라 page는 1, page_known은 false로 둔다 (page 열이 1 이상을 요구해서)
- source_sha256은 입력 JSON 파일의 SHA-256
"""

import argparse
import csv
import hashlib
import json
from pathlib import Path

TEAM_COLUMNS = [
    "id", "trade", "category", "content", "source", "source_org", "source_url", "section", "page",
    "source_type", "source_sha256", "source_version", "effective_date", "historical",
    "current_rule_usable", "needs_review", "review_reason", "automatic_calculation_usable",
    "application_scope", "cost_basis_policy", "effective_date_original", "rag_reference_usable",
]  # fmt: skip
EXTRA = ["ref", "doc", "trades", "hints", "rel", "doc_date", "license", "page_known"]


def rows(data: dict, sha: str) -> list[dict[str, str]]:
    out = []
    for c in data["chunks"]:
        d = data["docs"].get(c["doc"]) or {}
        trades = ";".join(c.get("trades") or [])
        out.append(
            {
                "id": c.get("id") or c["k"],
                "trade": trades,
                "category": ";".join(c.get("topics") or []),
                "content": c["text"],
                "source": d.get("title") or "",
                "source_org": d.get("pub") or "",
                "source_url": d.get("url") or "",
                "section": c.get("sec") or "",
                "page": "1",
                "source_type": d.get("kind") or "",
                "source_sha256": sha,
                "source_version": data.get("version") or "",
                "effective_date": "",
                "historical": "false",
                "current_rule_usable": "false",
                "needs_review": "false",
                "review_reason": "",
                "automatic_calculation_usable": "false",
                "application_scope": "",
                "cost_basis_policy": "",
                "effective_date_original": "",
                "rag_reference_usable": "true",
                "ref": c["k"],
                "doc": c["doc"],
                "trades": trades,
                "hints": json.dumps(c.get("hints") or [], ensure_ascii=False),
                "rel": d.get("rel") or "",
                "doc_date": d.get("date") or "",
                "license": d.get("license") or "",
                "page_known": "false",
            }
        )
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="화면 지식 JSON → 팀 전처리 CSV")
    ap.add_argument("src", type=Path)
    ap.add_argument("out", type=Path)
    a = ap.parse_args()
    raw = a.src.read_bytes()
    data = json.loads(raw.decode("utf-8"))
    out = rows(data, hashlib.sha256(raw).hexdigest())
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with a.out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=TEAM_COLUMNS + EXTRA, lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"{a.out.name}: {len(out)}행")


if __name__ == "__main__":
    main()
