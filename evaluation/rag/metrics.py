"""RAG 검색 지표: 순위 파일(rank_*.json)과 정답(questions.jsonl의 gold)으로 계산한다. 표준 라이브러리만.

    python evaluation/rag/metrics.py evaluation/rag/.cache/rank_base.json evaluation/rag/.cache/rank_current.json
    python evaluation/rag/metrics.py ... --final     # held-out까지 (마지막에 한 번만)

지표 (정답 grade 2 = 직접 답, 1 = 부분 관련)
- hit@1 · hit@5: 위 1 · 5개 안에 grade 2 조각이 있는 질문 비율
- recall@5: grade 1 이상 정답 중 위 5개에 든 비율의 평균
- mrr: grade 1 이상 첫 정답 순위의 역수 평균 (10위까지)
- ndcg@5: grade를 점수로 쓴 nDCG
- 답 없음(no_source) 질문과 정답 조각이 없는 질문은 위 지표에서 빼고, 검색이 '자료 부족(enough=false)'이라고 한 비율을 따로 본다
- 계산 엔진(engine) 질문은 검색으로 재지 않는다 (금액 · 기간은 계산 엔진이 답한다)
"""

import argparse
import json
import math
from pathlib import Path

HERE = Path(__file__).parent


def load_questions(path: Path) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def scores(ranked: list[str], gold: dict[str, int]) -> dict[str, float]:
    top5 = ranked[:5]
    strong = [r for r, g in gold.items() if g >= 2]
    first = next((i for i, r in enumerate(ranked[:10]) if gold.get(r, 0) >= 1), None)
    dcg = sum((2 ** gold.get(r, 0) - 1) / math.log2(i + 2) for i, r in enumerate(top5))
    ideal = sorted(gold.values(), reverse=True)[:5]
    idcg = sum((2**g - 1) / math.log2(i + 2) for i, g in enumerate(ideal))
    return {
        "hit@1": float(bool(ranked[:1]) and gold.get(ranked[0], 0) >= 2) if strong else float(gold.get(ranked[0], 0) >= 1) if ranked else 0.0,
        "hit@5": float(any(gold.get(r, 0) >= 2 for r in top5)) if strong else float(any(gold.get(r, 0) >= 1 for r in top5)),
        "recall@5": sum(1 for r in gold if r in top5) / len(gold),
        "mrr": 1 / (first + 1) if first is not None else 0.0,
        "ndcg@5": dcg / idcg if idcg else 0.0,
    }  # fmt: skip


def report(rank: dict, qs: list[dict], splits: set[str]) -> dict:
    rows = [q for q in qs if q["split"] in splits]
    groups: dict[str, list[dict]] = {}
    nosrc = []
    for q in rows:
        if q["expect"] == "engine":
            continue
        gold = {g["ref"]: g["grade"] for g in q["gold"]}
        if q["expect"] == "no_source" or not gold:
            nosrc.append(not rank["enough"].get(q["id"], True))
            continue
        s = scores(rank["rankings"].get(q["id"], []), gold)
        for key in ("전체", q["trade"]):
            groups.setdefault(key, []).append(s)
    out = {
        k: {m: round(sum(x[m] for x in v) / len(v), 3) for m in v[0]} | {"n": len(v)}
        for k, v in groups.items()
    }
    out["답 없음 → 자료 부족 판단"] = {
        "rate": round(sum(nosrc) / len(nosrc), 3) if nosrc else None,
        "n": len(nosrc),
    }
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("ranks", nargs="+", type=Path)
    ap.add_argument("--questions", type=Path, default=HERE / "questions.jsonl")
    ap.add_argument("--final", action="store_true", help="held-out까지 본다 (마지막에 한 번)")
    a = ap.parse_args()
    qs = load_questions(a.questions)
    if not any(q["gold"] for q in qs):
        raise SystemExit("정답(gold)이 아직 없어요")
    split_sets = [("dev", {"dev"})] + ([("held-out", {"heldout"})] if a.final else [])
    for path in a.ranks:
        rank = json.loads(path.read_text(encoding="utf-8"))
        for label, splits in split_sets:
            print(f"## {rank['name']} · {label}")
            for k, v in report(rank, qs, splits).items():
                print(f"  {k}: " + " · ".join(f"{m} {x}" for m, x in v.items()))


if __name__ == "__main__":
    main()
