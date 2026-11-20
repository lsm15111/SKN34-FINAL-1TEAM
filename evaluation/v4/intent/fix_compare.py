"""오류 꼴(바람 · 진술 + 순서 · 시기 · 방법 질문 → home_info · standard_quote) 고치기: (a) 규칙 vs (b) 어려운 예 재학습을
dev 쪽으로만 견줘요(held-out · 확인 세트는 보지 않아요).

    cd backend && uv run --with scikit-learn python ../evaluation/v4/intent/fix_compare.py --hard <어려운 예 jsonl>

- 원래 dev에는 이 오류 꼴이 거의 없어서, held-out을 보지 않은 하위 에이전트가 쓴 어려운 예(+ 대조 문장)를 dev 쪽 조각으로 같이 봐요.
- 견주는 줄: dev 고객 말 616 + 어려운 예. 무료 모드 '모델만' 길의 카드 정답률 · macro-F1을 세요.
  - (a) 규칙: 질문 꼴이고 낱말 규칙이 없고 모델이 home_info · standard_quote면 knowledge. 모델은 지금 모델 그대로예요
    (dev 줄은 겹 밖 확률, 어려운 예는 학습에 없던 글이라 내보낸 모델 확률).
    a1 = 리드가 적은 꼴(언제 · 전에 · 후에 · 순서 · 먼저 · 어떻게 · 해야 해요?), a2 = a1 + 돈 · 기간 낱말 빼기,
    a3 = free.asks_how(때 낱말은 묻는 꼴 문장에서만, 돈 · 기간 빼기).
  - (b) 재학습: dev + 어려운 예를 같은 방식 5겹으로 나눠 겹 밖 확률을 다시 만들어요(온도도 다시).
- 결과: results/fix_dev.json
"""

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
from sklearn.model_selection import StratifiedKFold, cross_val_predict

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[2] / "backend"))

import select_route as R
import train as T
from kit import jsonl, utf8_stdout

from app.agent.intent import clean
from app.assistant import free, intent_v4

RESULTS = HERE / "results"
HOW_LABELS = free.HOW_LABELS
# a1: 리드가 적은 꼴 그대로(언제 · 전에 · 후에 · 순서 · 먼저 · 어떻게 · 해야 해요? 중 하나라도)
LEAD_ASK = re.compile(
    r"언제|전에|후에|뒤에|다음에|순서|먼저|나중|어떻게|어떡|"
    r"해야\s{0,2}(?:하나요|하죠|할까요|되나요|될까요|해요\s{0,2}\?|돼요\s{0,2}\?)|"
    r"해도\s{0,2}(?:되나요|될까요|돼요|괜찮)"
)


def a1(text: str) -> bool:
    return bool(LEAD_ASK.search(text))


def a2(text: str) -> bool:  # + 돈 · 기간 낱말이 있으면 뺌
    return a1(text) and not free.MONEY_DAYS.search(text)


def with_rule(rows: list[dict], probs: list[dict], asks) -> dict:
    """모델만 길에 (a) 규칙을 얹은 결과."""
    out = R.run(rows, probs, "model")
    for i, (r, p) in enumerate(zip(rows, probs, strict=True)):
        lab = max(p, key=p.__getitem__)
        if lab in HOW_LABELS and free.intent_of(r["text"], "customer") is None and asks(r["text"]):
            out["pred"][i], out["cards"][i] = "knowledge", {None}
    return out


def oof_all(rows: list[dict], c: float, w) -> tuple[list[dict], float]:
    """rows 전체를 5겹으로 나눈 겹 밖 확률(온도 보정 뒤)."""
    texts = [r["text"] for r in rows]
    labels = [r["label"] for r in rows]
    folds = StratifiedKFold(n_splits=5, shuffle=True, random_state=T.SEED)
    z = cross_val_predict(
        T.make("lr_char", c, w), texts, labels, cv=folds, method="decision_function"
    )
    names = sorted(set(labels))
    y = np.array([names.index(g) for g in labels])
    t = T.temperature(z, y)
    p = T.softmax(z / t)
    return [dict(zip(names, row.tolist(), strict=True)) for row in p], t


def score(rows: list[dict], sys_: dict, idx: list[int]) -> dict:
    sub = [rows[i] for i in idx]
    m = R.measure(sub, {k: [v[i] for i in idx] for k, v in sys_.items() if isinstance(v, list)})
    return {
        "n": len(sub),
        "card_acc": m["card_acc"],
        "macro_f1": m["macro_f1"],
        "oos_recall": m["oos_recall"],
        "accuracy": m["accuracy"],
    }


def main() -> int:
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--hard", required=True, help="어려운 예 jsonl(held-out과 거의 같은 글을 뺀 것)"
    )
    args = ap.parse_args()
    dev = jsonl(HERE / "dev.jsonl")
    for r in dev:
        r["text"] = clean(r["text"])
    hard = jsonl(Path(args.hard))
    for k, r in enumerate(hard, start=1):
        r["text"] = clean(r["text"])
        r.setdefault("id", f"hard:{k}")
        r.setdefault("surface", "customer")
    train = json.loads((RESULTS / "train.json").read_text(encoding="utf-8"))
    best = train["selection"]["lr_char"]["best"]
    oof = json.loads((RESULTS / "dev_oof.json").read_text(encoding="utf-8"))
    assert oof["ids"] == [r["id"] for r in dev]
    probs_dev = [dict(zip(oof["labels"], row, strict=True)) for row in oof["probs"]]
    probs_hard = [intent_v4.probs(r["text"]) for r in hard]  # 학습에 없던 글
    probs_b, temp_b = oof_all(dev + hard, best["C"], best["class_weight"])
    allrows = dev + hard
    p0 = probs_dev + probs_hard
    cust = [i for i, r in enumerate(allrows) if r["surface"] == "customer"]
    rows = [allrows[i] for i in cust]
    p0 = [p0[i] for i in cust]
    pb = [probs_b[i] for i in cust]
    n_dev = sum(1 for i in cust if i < len(dev))
    parts = {
        "dev+hard": list(range(len(rows))),
        "dev": list(range(n_dev)),
        "hard": list(range(n_dev, len(rows))),
        "hard_knowledge": [i for i in range(n_dev, len(rows)) if rows[i]["label"] == "knowledge"],
        "hard_contrast": [i for i in range(n_dev, len(rows)) if rows[i]["label"] != "knowledge"],
    }
    systems = {
        "model": R.run(rows, p0, "model"),
        "a1_rule": with_rule(rows, p0, a1),
        "a2_rule": with_rule(rows, p0, a2),
        "a3_rule": with_rule(rows, p0, free.asks_how),
        "b_hard": R.run(rows, pb, "model"),
    }
    table = {
        k: {part: score(rows, s, idx) for part, idx in parts.items()} for k, s in systems.items()
    }
    rep = {
        "hard": len(hard),
        "temperature_b": temp_b,
        "parts": {k: len(v) for k, v in parts.items()},
    }
    rep["table"] = table
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "fix_dev.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n"
    )
    print("줄 수:", rep["parts"])
    print("| 방식 | dev+어려운 예 카드 · macro-F1 | dev 카드 | 어려운 예 카드(지식 · 대조) |")
    print("| --- | --- | --- | --- |")
    for k, x in table.items():
        print(
            f"| {k} | {x['dev+hard']['card_acc']:.1%} · {x['dev+hard']['macro_f1']:.3f} | "
            f"{x['dev']['card_acc']:.1%} | {x['hard']['card_acc']:.1%} "
            f"({x['hard_knowledge']['card_acc']:.1%} · {x['hard_contrast']['card_acc']:.1%}) |"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
