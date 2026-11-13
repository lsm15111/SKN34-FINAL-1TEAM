"""RAG 평가용 합친 말뭉치: 화면 자료(rag5) + 서버 자료(data/processed/*_rag.csv) + 로컬 추가 자료(있으면).

    python evaluation/rag/corpus.py            # evaluation/rag/.cache/corpus.json
    python evaluation/rag/corpus.py --no-local # 로컬 추가 자료(책 등) 빼기

번호 규칙 (서버로 합칠 때도 같은 번호를 쓴다)
- K1~K1434: 화면 자료 rag5.json 그대로
- K2001~: 서버 자료 CSV. 파일 이름 순 → 파일 안 순서
- K5001~: 로컬 추가 자료(rag-local.json, git 제외) 그대로
"""

import argparse
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAG5 = ROOT / "frontend/public/v2/rag5.json"
LOCAL = ROOT / "frontend/public/v2/rag-local.json"
CSV_DIR = ROOT / "data/processed"
OUT = Path(__file__).parent / ".cache/corpus.json"
TEAM_START = 2001

# 서버 자료 파일 → 출처 종류 · 공정
TEAM = {
    "04_lhcs_gypsum_rag": ("official", ["목공"]),
    "05_lhcs_wallpaper_rag": ("official", ["도배"]),
    "07_housing_management_rules_rag": ("official", []),
    "08_kcs_carpentry_rag": ("kcs", ["목공"]),
    "09_kcs_insulation_rag": ("kcs", ["목공"]),
    "10_kcs_condensation_rag": ("kcs", ["목공", "도배"]),
    "11_kcs_wallpaper_rag": ("kcs", ["도배"]),
    "12_housing_bylaws_commentary_rag": ("official", []),
}


def team_part() -> tuple[dict, list]:
    docs, chunks, k = {}, [], TEAM_START
    for path in sorted(CSV_DIR.glob("*_rag.csv")):
        kind, trades = TEAM[path.stem]
        doc = f"team:{path.stem}"
        rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))
        first = rows[0]
        docs[doc] = {
            "title": first["source"].replace(".pdf", ""),
            "pub": first["source_org"],
            "url": first["source_url"] or None,
            "kind": kind,
            "rel": "high",
        }
        for r in rows:
            sec = " · ".join(x for x in (r["section"], f"{r['page']}쪽" if r["page"] else "") if x)
            chunks.append(
                {"k": f"K{k}", "doc": doc, "sec": sec, "text": r["content"], "trades": trades,
                 "src_id": r["id"]}
            )  # fmt: skip
            k += 1
    return docs, chunks


def build(with_local: bool) -> dict:
    base = json.loads(RAG5.read_text(encoding="utf-8"))
    docs, chunks = dict(base["docs"]), list(base["chunks"])
    tdocs, tchunks = team_part()
    docs.update(tdocs)
    chunks += tchunks
    version = f"{base['version']}+team{len(tchunks)}"
    if with_local and LOCAL.exists():
        extra = json.loads(LOCAL.read_text(encoding="utf-8"))
        docs.update(extra["docs"])
        chunks += extra["chunks"]
        version += f"+{extra['version']}"
    keys = [c["k"] for c in chunks]
    assert len(keys) == len(set(keys)), "번호가 겹쳐요"
    return {"version": version, "docs": docs, "chunks": chunks}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-local", action="store_true")
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    c = build(not a.no_local)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")
    print(f"{a.out} · {len(c['chunks'])}조각 · {c['version']}")
