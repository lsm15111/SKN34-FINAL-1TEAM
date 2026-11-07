"""L0 평가 지표(LLM 호출 없음). 정답 세트와 예측 파일을 비교해 지표를 내고 evaluation/results/에 남긴다.

    python evaluation/run.py intent --pred preds.jsonl [--split heldout]
        예측 줄: {"id": "Q001", "route": "coach", "confidence": 0.93}
    python evaluation/run.py rag --pred ranked.jsonl [--split heldout] [--k 5]
        예측 줄: {"id": "R01", "ranked": ["dobae.silk.removal", ...]}

외부 라이브러리 없이 계산한다(CI · 로컬 동일). 지표 정의: docs/agent/09-eval.md.
"""

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent


def read(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def classification(gold: dict[str, str], pred: dict[str, str]) -> dict:
    """정확도 · macro-F1 · 클래스별 P/R/F1 · 혼동행렬. 예측이 없는 문장은 'missing'으로 센다."""
    labels = sorted(set(gold.values()) | {p for p in pred.values() if p})
    conf: dict[str, Counter] = defaultdict(Counter)
    for i, g in gold.items():
        conf[g][pred.get(i, "missing")] += 1
    per: dict[str, dict] = {}
    for c in labels:
        tp = conf[c][c]
        fp = sum(conf[g][c] for g in labels if g != c)
        fn = sum(n for p, n in conf[c].items() if p != c)
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        per[c] = {
            "precision": round(prec, 4),
            "recall": round(rec, 4),
            "f1": round(f1, 4),
            "n": sum(conf[c].values()),
        }
    gold_labels = sorted(set(gold.values()))
    acc = sum(conf[c][c] for c in gold_labels) / len(gold) if gold else 0.0
    macro = sum(per[c]["f1"] for c in gold_labels) / len(gold_labels) if gold_labels else 0.0
    return {
        "n": len(gold),
        "accuracy": round(acc, 4),
        "macro_f1": round(macro, 4),
        "per_class": per,
        "confusion": {g: dict(conf[g]) for g in gold_labels},
    }


def ece(
    gold: dict[str, str], pred: dict[str, str], conf: dict[str, float], bins: int = 10
) -> float:
    """기대 보정 오차: 신뢰도 구간마다 |정확도 − 평균 신뢰도|의 가중 평균."""
    buckets: dict[int, list[tuple[bool, float]]] = defaultdict(list)
    for i, g in gold.items():
        if i in conf:
            c = min(max(conf[i], 0.0), 1.0)
            buckets[min(int(c * bins), bins - 1)].append((pred.get(i) == g, c))
    n = sum(len(b) for b in buckets.values())
    if not n:
        return 0.0
    err = sum(
        abs(sum(ok for ok, _ in b) / len(b) - sum(c for _, c in b) / len(b)) * len(b)
        for b in buckets.values()
    )
    return round(err / n, 4)


def retrieval(gold: dict[str, set[str]], ranked: dict[str, list[str]], k: int = 5) -> dict:
    """Recall@k · nDCG@10 · MRR(관련 조각이 여러 개면 모두 같은 가중)."""
    rec, ndcg, mrr = [], [], []
    for i, rel in gold.items():
        got = ranked.get(i, [])
        rec.append(len(rel & set(got[:k])) / len(rel) if rel else 0.0)
        dcg = sum(1 / math.log2(r + 2) for r, key in enumerate(got[:10]) if key in rel)
        ideal = sum(1 / math.log2(r + 2) for r in range(min(len(rel), 10)))
        ndcg.append(dcg / ideal if ideal else 0.0)
        first = next((r for r, key in enumerate(got) if key in rel), None)
        mrr.append(1 / (first + 1) if first is not None else 0.0)
    n = len(gold) or 1
    return {
        "n": len(gold),
        f"recall@{k}": round(sum(rec) / n, 4),
        "ndcg@10": round(sum(ndcg) / n, 4),
        "mrr": round(sum(mrr) / n, 4),
    }


def run_intent(split: str, pred_path: Path) -> dict:
    gold = {r["id"]: r["route"] for r in read(HERE / "intent" / f"{split}.jsonl")}
    preds = read(pred_path)
    pred = {p["id"]: p.get("route", "") for p in preds}
    conf = {p["id"]: float(p["confidence"]) for p in preds if "confidence" in p}
    out = classification(gold, pred)
    out["ece"] = ece(gold, pred, conf)
    risky = [i for i, g in gold.items() if g == "abuse"]
    out["abuse_recall"] = (
        round(sum(pred.get(i) == "abuse" for i in risky) / len(risky), 4) if risky else None
    )
    return out


def run_rag(split: str, pred_path: Path, k: int) -> dict:
    gold = {r["id"]: set(r["relevant"]) for r in read(HERE / "rag" / f"{split}.jsonl")}
    ranked = {p["id"]: list(p["ranked"]) for p in read(pred_path)}
    return retrieval(gold, ranked, k)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="믿집 L0 평가 지표")
    ap.add_argument("set", choices=["intent", "rag"])
    ap.add_argument("--pred", type=Path, required=True)
    ap.add_argument("--split", default="dev", choices=["dev", "heldout"])
    ap.add_argument("--k", type=int, default=5)
    a = ap.parse_args(argv)
    result = run_intent(a.split, a.pred) if a.set == "intent" else run_rag(a.split, a.pred, a.k)
    result |= {
        "set": a.set,
        "split": a.split,
        "date": date.today().isoformat(),
        "pred": a.pred.name,
    }
    out = HERE / "results" / f"{a.set}-{a.split}-{result['date']}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {k: v for k, v in result.items() if k not in ("per_class", "confusion")},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
