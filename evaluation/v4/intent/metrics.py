"""v4 비서 의도 지표(표준 라이브러리만): 라벨별 P · R · F1, macro-F1, 범위 밖 재현율, 카드 정답률, ECE,
낮은 신뢰도 기준값 곡선, 부트스트랩 95% 구간(항목을 다시 뽑아요, 두 방식 차이는 같은 표본으로).

- pred가 None이면 '라벨 없음'(되묻기 · 기준 아래)이에요. 어느 라벨의 정밀도에도 들어가지 않고 틀린 것으로 셉니다.
- 너그러운 채점(alt): 예측이 alt 안에 있으면 맞은 것으로 보고 그 줄의 정답을 예측으로 바꿔 셉니다.
"""

import math
import random
from collections.abc import Callable, Sequence

OOS = "out_of_scope"


def per_label(gold: Sequence[str], pred: Sequence[str | None], labels: Sequence[str]) -> dict:
    out = {}
    for lab in labels:
        tp = sum(1 for g, p in zip(gold, pred, strict=True) if g == lab and p == lab)
        fp = sum(1 for g, p in zip(gold, pred, strict=True) if g != lab and p == lab)
        fn = sum(1 for g, p in zip(gold, pred, strict=True) if g == lab and p != lab)
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        out[lab] = {"p": prec, "r": rec, "f1": f1, "n": tp + fn}
    return out


def macro_f1(gold: Sequence[str], pred: Sequence[str | None], labels: Sequence[str]) -> float:
    """정답에 있는 라벨만 평균해요(표본에 없는 라벨은 빼요)."""
    rows = per_label(gold, pred, labels)
    present = [lab for lab in labels if rows[lab]["n"] > 0]
    return sum(rows[lab]["f1"] for lab in present) / len(present) if present else 0.0


def accuracy(gold: Sequence[str], pred: Sequence[str | None]) -> float:
    return sum(1 for g, p in zip(gold, pred, strict=True) if g == p) / len(gold) if gold else 0.0


def recall_of(gold: Sequence[str], pred: Sequence[str | None], label: str = OOS) -> float:
    n = sum(1 for g in gold if g == label)
    return (
        sum(1 for g, p in zip(gold, pred, strict=True) if g == label and p == label) / n
        if n
        else 0.0
    )


def lenient(
    gold: Sequence[str], alt: Sequence[Sequence[str]], pred: Sequence[str | None]
) -> list[str]:
    """예측이 alt에 있으면 그 줄의 정답을 예측으로 바꾼 정답 목록."""
    return [p if p is not None and p in a else g for g, a, p in zip(gold, alt, pred, strict=True)]


def card_hits(gold_cards: Sequence[set], pred_cards: Sequence[set]) -> list[bool]:
    """카드 정답: 정답 카드(들) 중 하나를 고른 카드(들)가 덮으면 맞음. 카드 없음은 None으로 둬요."""
    return [bool(g & p) for g, p in zip(gold_cards, pred_cards, strict=True)]


def ece(conf: Sequence[float], correct: Sequence[bool], bins: int = 10) -> float:
    """기대 보정 오차: 같은 폭 구간마다 |정확도 − 평균 신뢰도| × 비율의 합."""
    n = len(conf)
    if not n:
        return 0.0
    total = 0.0
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        idx = [i for i, c in enumerate(conf) if (lo < c <= hi) or (b == 0 and c == 0.0)]
        if not idx:
            continue
        acc = sum(1 for i in idx if correct[i]) / len(idx)
        avg = sum(conf[i] for i in idx) / len(idx)
        total += len(idx) / n * abs(acc - avg)
    return total


def reliability(conf: Sequence[float], correct: Sequence[bool], bins: int = 10) -> list[dict]:
    out = []
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        idx = [i for i, c in enumerate(conf) if (lo < c <= hi) or (b == 0 and c == 0.0)]
        if idx:
            out.append(
                {
                    "bin": f"{lo:.1f}~{hi:.1f}",
                    "n": len(idx),
                    "conf": sum(conf[i] for i in idx) / len(idx),
                    "acc": sum(1 for i in idx if correct[i]) / len(idx),
                }
            )
    return out


def curve(
    conf: Sequence[float], correct: Sequence[bool], thresholds: Sequence[float]
) -> list[dict]:
    """기준값 t: 신뢰도 ≥ t만 받고 나머지는 되묻기(또는 옛 길). 받은 비율 · 받은 것의 정확도."""
    n = len(conf)
    out = []
    for t in thresholds:
        idx = [i for i, c in enumerate(conf) if c >= t]
        out.append(
            {
                "t": t,
                "answered": len(idx) / n if n else 0.0,
                "ask": 1 - len(idx) / n if n else 0.0,
                "acc": sum(1 for i in idx if correct[i]) / len(idx) if idx else 0.0,
            }
        )
    return out


def bootstrap(
    stat: Callable[[list[int]], float], n: int, *, reps: int = 2000, seed: int = 20261121
) -> tuple[float, float]:
    """항목 번호를 다시 뽑아 stat을 다시 재요. 2.5% · 97.5% 값."""
    rnd = random.Random(seed)
    vals = sorted(stat([rnd.randrange(n) for _ in range(n)]) for _ in range(reps))
    return vals[int(reps * 0.025)], vals[min(reps - 1, math.ceil(reps * 0.975) - 1)]


def pick(seq: Sequence, idx: list[int]) -> list:
    return [seq[i] for i in idx]


def hybrid(model: dict, base: dict, t: float) -> dict:
    """신뢰도 ≥ t면 모델 라벨 · 카드, 아니면 지금 길(base). model · base: pred · cards · conf 목록."""
    use = [c >= t for c in model["conf"]]
    return {
        "pred": [m if u else b for m, b, u in zip(model["pred"], base["pred"], use, strict=True)],
        "cards": [
            m if u else b for m, b, u in zip(model["cards"], base["cards"], use, strict=True)
        ],
        "conf": list(model["conf"]),
        "answered": sum(use) / len(use) if use else 0.0,
    }
