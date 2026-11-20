"""v4 비서 의도 모델 학습 · 내보내기 (scikit-learn은 이 스크립트에서만 써요. 서비스 추론은 순수 파이썬).

    cd backend && uv run --with scikit-learn python ../evaluation/v4/intent/train.py           # dev 교차검증 · 학습 · 내보내기
    cd backend && uv run --with scikit-learn python ../evaluation/v4/intent/train.py --final   # + 비교 모델 held-out 예측

- 학습 · 고르기는 dev.jsonl만 써요(held-out은 고르기에 쓰지 않아요).
  - 모델마다 C · 무게(class_weight)를 dev 5겹 교차검증 macro-F1로 골라요.
  - 온도(temperature): 겹 밖 점수로 음의 로그 우도가 가장 작은 값 하나를 골라요(확률 보정, 가장 높은 라벨은 그대로).
  - 기준값: 겹 밖 예측으로 '기준값 아래는 지금 길(v3 관문 → step_card)'을 섞었을 때 카드 정답률이 가장 높은 값.
- 본 모델: TF-IDF(낱말 안 글자 2~4개, sublinear) + 로지스틱 회귀(v1 관문과 같은 꼴).
  비교: 선형 SVM(시그모이드 보정) · 낱말 1~2 + 글자 2~4 + 로지스틱 회귀.
- 내보내기: backend/app/assistant/assistant_intent_v1.json.gz(가중치 · 온도 · 기준값 + checks: 학습 쪽 확률).
  결과: results/train.json(--final이면 results/compare_models_heldout.json도)
"""

import argparse
import gzip
import json
import sys
import time
from pathlib import Path

import numpy as np
import sklearn
from sklearn.calibration import CalibratedClassifierCV
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import FeatureUnion, make_pipeline
from sklearn.svm import LinearSVC

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[2] / "backend"))

import baseline
import metrics as M
from kit import jsonl, utf8_stdout

from app.agent.intent import clean
from app.assistant import intent_v4

SEED = 20261121
OUT = HERE.parents[2] / "backend" / "app" / "assistant" / "assistant_intent_v1.json.gz"
RESULTS = HERE / "results"
GRID_C = (1.0, 3.0, 10.0, 30.0, 100.0)
SVM_C = (0.1, 0.3, 1.0, 3.0)
WEIGHTS = (None, "balanced")
THRESHOLDS = [round(0.2 + 0.05 * k, 2) for k in range(15)]
CHECKS = 18  # 내보낼 checks 수(dev 글에서 라벨마다 2개)
KINDS = {
    "lr_char": "글자 2~4 TF-IDF + 로지스틱 회귀(본 모델)",
    "svm_char": "글자 2~4 TF-IDF + 선형 SVM(시그모이드 보정)",
    "lr_word_char": "낱말 1~2 + 글자 2~4 TF-IDF + 로지스틱 회귀",
}


def char_vec() -> TfidfVectorizer:
    return TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), sublinear_tf=True)


def make(kind: str, c: float, weight: str | None):
    if kind == "lr_char":
        return make_pipeline(
            char_vec(), LogisticRegression(C=c, class_weight=weight, max_iter=5000)
        )
    if kind == "svm_char":
        svm = LinearSVC(C=c, class_weight=weight)
        return make_pipeline(char_vec(), CalibratedClassifierCV(svm, method="sigmoid", cv=3))
    if kind == "lr_word_char":
        word = TfidfVectorizer(
            analyzer="word", token_pattern=r"(?u)\b\w+\b", ngram_range=(1, 2), sublinear_tf=True
        )
        union = FeatureUnion([("word", word), ("char", char_vec())])
        return make_pipeline(union, LogisticRegression(C=c, class_weight=weight, max_iter=5000))
    raise ValueError(kind)


def load(name: str) -> list[dict]:
    rows = jsonl(HERE / f"{name}.jsonl")
    for r in rows:
        r["text"] = clean(r["text"])
    return rows


def softmax(z: np.ndarray) -> np.ndarray:
    e = np.exp(z - z.max(1, keepdims=True))
    return e / e.sum(1, keepdims=True)


def select(texts: list[str], labels: list[str]) -> dict:
    """모델마다 dev 5겹 교차검증 macro-F1로 C · 무게를 고른다."""
    folds = StratifiedKFold(n_splits=5, shuffle=True, random_state=SEED)
    names = sorted(set(labels))
    out = {}
    for kind in KINDS:
        best = None
        tried = []
        for c in SVM_C if kind == "svm_char" else GRID_C:
            for w in WEIGHTS:
                proba = cross_val_predict(
                    make(kind, c, w), texts, labels, cv=folds, method="predict_proba"
                )
                pred = [names[i] for i in proba.argmax(1)]
                f1 = M.macro_f1(labels, pred, intent_v4.LABELS)
                tried.append({"C": c, "class_weight": w, "macro_f1": round(f1, 4)})
                if best is None or f1 > best["macro_f1"]:
                    best = {"C": c, "class_weight": w, "macro_f1": f1}
        out[kind] = {"best": best, "tried": tried}
        print(
            f"{kind}: C={best['C']} 무게={best['class_weight']} dev 교차검증 macro-F1 {best['macro_f1']:.3f}"
        )
    return out


def temperature(z: np.ndarray, y: np.ndarray) -> float:
    """겹 밖 점수 z로 음의 로그 우도가 가장 작은 온도(0.05~3, 로그 눈금 300칸)."""
    best_t, best_nll = 1.0, float("inf")
    for t in np.exp(np.linspace(np.log(0.05), np.log(3.0), 300)):
        p = softmax(z / t)
        nll = -float(np.mean(np.log(p[np.arange(len(y)), y] + 1e-12)))
        if nll < best_nll:
            best_t, best_nll = float(t), nll
    return round(best_t, 4)


def calibrate(texts: list[str], labels: list[str], c: float, w: str | None) -> dict:
    """본 모델의 겹 밖 점수로 온도 · 기준값을 고른다(기준값 아래는 지금 길로 섞어 카드 정답률 최대)."""
    folds = StratifiedKFold(n_splits=5, shuffle=True, random_state=SEED)
    z = cross_val_predict(
        make("lr_char", c, w), texts, labels, cv=folds, method="decision_function"
    )
    names = sorted(set(labels))
    y = np.array([names.index(g) for g in labels])
    t = temperature(z, y)
    raw, cal = softmax(z), softmax(z / t)
    pred = [names[i] for i in cal.argmax(1)]
    correct = [p == g for p, g in zip(pred, labels, strict=True)]
    model = {
        "pred": pred,
        "conf": cal.max(1).tolist(),
        "cards": [{intent_v4.CARD_OF[p]} for p in pred],
    }
    rows = [{"text": x, "label": g} for x, g in zip(texts, labels, strict=True)]
    base = baseline.run(rows)
    gold_cards = [{intent_v4.CARD_OF[g]} for g in labels]
    curve = M.curve(model["conf"], correct, THRESHOLDS)
    for row in curve:
        h = M.hybrid(model, base, row["t"])
        row["hybrid_card_acc"] = sum(M.card_hits(gold_cards, h["cards"])) / len(rows)
    pick = max(curve, key=lambda r: (round(r["hybrid_card_acc"], 6), -r["t"]))
    return {
        "temperature": t,
        "threshold": pick["t"],
        "ece_raw": M.ece(raw.max(1).tolist(), correct),
        "ece_cal": M.ece(model["conf"], correct),
        "base_card_acc": sum(M.card_hits(gold_cards, base["cards"])) / len(rows),
        "curve": curve,
    }


def export(model, texts: list[str], labels: list[str], meta: dict) -> dict:
    vec, lr = model.steps[0][1], model.steps[-1][1]
    names = [str(x) for x in lr.classes_]
    idf, coef = vec.idf_, lr.coef_  # coef: (라벨 수, 특징 수)
    features = {
        g: [round(float(idf[j]), 7), *(round(float(x), 7) for x in coef[:, j])]
        for g, j in sorted(vec.vocabulary_.items())
    }
    # checks: dev 글에서 라벨마다 2개(앞에서부터) — held-out 글은 넣지 않아요
    picked: list[int] = []
    for k in range(len(texts)):
        if sum(1 for i in picked if labels[i] == labels[k]) < 2:
            picked.append(k)
    picked = picked[:CHECKS]
    z = model.decision_function([texts[i] for i in picked])
    probs = softmax(z / meta["temperature"])
    checks = [
        {"text": texts[i], "probs": [round(float(p), 7) for p in row]}
        for i, row in zip(picked, probs, strict=True)
    ]
    blob = {
        "version": "assistant_intent_v1",
        "source": (
            f"evaluation/v4/intent dev {len(texts)}줄 → TF-IDF(char_wb 2~4, sublinear) + LR "
            f"C={meta['C']} class_weight={meta['class_weight']} (scikit-learn {sklearn.__version__})"
        ),
        "labels": names,
        "ngram": [2, 4],
        "temperature": meta["temperature"],
        "threshold": meta["threshold"],
        "intercept": [round(float(x), 7) for x in lr.intercept_],
        "features": features,
        "checks": checks,
    }
    raw = json.dumps(blob, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    OUT.write_bytes(gzip.compress(raw, compresslevel=9, mtime=0))
    return {"features": len(features), "bytes": OUT.stat().st_size, "labels": names}


def heldout_preds(sel: dict, texts: list[str], labels: list[str]) -> dict:
    """비교 모델(고른 설정)을 dev 전체로 다시 학습해 held-out 예측을 남긴다(고르기에 쓰지 않음, 온도 보정 없음)."""
    held = load("heldout")
    ht = [r["text"] for r in held]
    out = {}
    for kind, s in sel.items():
        b = s["best"]
        m = make(kind, b["C"], b["class_weight"]).fit(texts, labels)
        t0 = time.perf_counter()
        proba = m.predict_proba(ht)
        ms = (time.perf_counter() - t0) * 1000 / len(ht)
        names = [str(x) for x in m.classes_]
        out[kind] = {
            "pred": [names[i] for i in proba.argmax(1)],
            "conf": [round(float(c), 6) for c in proba.max(1)],
            "ms_per_text_sklearn_batch": round(ms, 4),
        }
    return {"ids": [r["id"] for r in held], "models": out}


def main() -> int:
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--final", action="store_true", help="비교 모델 held-out 예측도 남겨요(한 번만)"
    )
    args = ap.parse_args()
    dev = load("dev")
    texts = [r["text"] for r in dev]
    labels = [r["label"] for r in dev]
    sel = select(texts, labels)
    best = sel["lr_char"]["best"]
    cal = calibrate(texts, labels, best["C"], best["class_weight"])
    print(
        f"온도 {cal['temperature']} · ECE {cal['ece_raw']:.3f} → {cal['ece_cal']:.3f}(dev 겹 밖) · "
        f"기준값 {cal['threshold']}"
    )
    meta = {**best, "temperature": cal["temperature"], "threshold": cal["threshold"]}
    model = make("lr_char", best["C"], best["class_weight"]).fit(texts, labels)
    info = export(model, texts, labels, meta)
    print(f"내보냄: {OUT.name} 특징 {info['features']}개 · {info['bytes'] / 1024:.0f}KB")
    report = {
        "dev": len(dev),
        "synthetic": sum(1 for r in dev if r.get("synthetic")),
        "sklearn": sklearn.__version__,
        "selection": sel,
        "calibration": cal,
        "export": info,
    }
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "train.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n"
    )
    if args.final:
        got = heldout_preds(sel, texts, labels)
        (RESULTS / "compare_models_heldout.json").write_text(
            json.dumps(got, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n"
        )
        print("비교 모델 held-out 예측을 남겼어요(지표는 evaluate.py가 같은 방식으로 재요)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
