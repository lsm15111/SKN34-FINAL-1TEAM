"""사람 라벨과 판정기의 일치: 코헨 카파 · TPR · TNR. LLM 0회.

    cd backend
    uv run python ../evaluation/v4/kappa.py --human <human_20.csv> --key <human_20_key.csv> --judgments <judgments.jsonl>
    uv run python ../evaluation/v4/kappa.py --pairs labels.csv --truth 사람 --pred 판정 --positive 실패   # 점수형 두 칸

- 쌍대: 사람 칸(1 · 2 · 같음 · 둘다나쁨 · 모름)을 열쇠로 시스템(A · B · tie)으로 바꿔 판정기 최종과 견줘요.
  둘다나쁨은 tie로 셈해요(승부 없음). 모름 · 빈칸 · 판정기 unknown은 빼요
- 카파: 차원마다(종합 · 정확 · 근거 · 유용 · 간결 · 안전 · 숫자), 범주 A · B · tie. 우연 일치가 1이면 정의 안 됨(None)
- TPR · TNR: --positive(기본 B) 승을 양성으로 봐요. TPR = 사람이 양성이라 한 것 중 판정기도 양성,
  TNR = 사람이 양성이 아니라 한 것 중 판정기도 아님
- 결과: 사람 CSV 옆 kappa.json + 화면 표. 목표(계획 6절 · 조사 3절): κ ≥ 0.7, TNR ≥ 0.9
"""

import argparse
import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from human_sample import DIM_KEY, DIMS_KO
from kit import jsonl, utf8_stdout, wilson

HUMAN = {
    "1": "1",
    "2": "2",
    "같음": "tie",
    "둘다나쁨": "tie",
    "둘 다 나쁨": "tie",
}  # 모름 · 빈칸은 뺌


def cohen_kappa(a: list[str], b: list[str]) -> float | None:
    """두 판정자의 범주 일치(가중치 없음). 우연 일치가 1이면 정의되지 않아 None."""
    n = len(a)
    if n == 0 or n != len(b):
        return None
    cats = set(a) | set(b)
    po = sum(x == y for x, y in zip(a, b, strict=True)) / n
    pe = sum((a.count(c) / n) * (b.count(c) / n) for c in cats)
    if pe >= 1:
        return None
    return round((po - pe) / (1 - pe), 3)


def rates(truth: list[str], pred: list[str], positive: str) -> dict:
    pairs = list(zip(truth, pred, strict=True))
    tp = sum(t == positive and p == positive for t, p in pairs)
    fn = sum(t == positive and p != positive for t, p in pairs)
    tn = sum(t != positive and p != positive for t, p in pairs)
    fp = sum(t != positive and p == positive for t, p in pairs)
    return {
        "tp": tp, "fn": fn, "tn": tn, "fp": fp,
        "tpr": round(tp / (tp + fn), 3) if tp + fn else None, "tpr_ci95": wilson(tp, tp + fn),
        "tnr": round(tn / (tn + fp), 3) if tn + fp else None, "tnr_ci95": wilson(tn, tn + fp),
    }  # fmt: skip


def agreement(truth: list[str], pred: list[str], positive: str) -> dict:
    n = len(truth)
    same = sum(x == y for x, y in zip(truth, pred, strict=True))
    return {"n": n, "agree": round(same / n, 3) if n else None, "agree_ci95": wilson(same, n),
            "kappa": cohen_kappa(truth, pred), **rates(truth, pred, positive)}  # fmt: skip


def human_to_system(value: str, first: str) -> str | None:
    v = HUMAN.get((value or "").strip())
    if v is None:
        return None
    if v in ("1", "2"):
        return first if v == "1" else ("B" if first == "A" else "A")
    return v


def judge_final(final: str) -> str | None:
    return {"A": "A", "B": "B", "tie": "tie", "both_bad": "tie"}.get(final)


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def pairwise(a) -> dict:
    keys = {r["표본"]: r for r in read_csv(a.key)}
    judged = {r["id"]: r for r in jsonl(a.judgments)}
    out = {}
    for dim_ko in ("종합", *DIMS_KO):
        dim = "overall" if dim_ko == "종합" else DIM_KEY[dim_ko]
        truth, pred = [], []
        for h in read_csv(a.human):
            k = keys.get(h["표본"])
            j = judged.get(k["item_id"]) if k else None
            if j is None:
                continue
            t = human_to_system(h.get(dim_ko, ""), k["답1"])
            p = judge_final(j["dims"][dim]["final"])
            if t is not None and p is not None:
                truth.append(t)
                pred.append(p)
        out[dim_ko] = agreement(truth, pred, a.positive)
    return out


def pointwise(a) -> dict:
    rows = read_csv(a.pairs)
    pairs = [
        (r[a.truth].strip(), r[a.pred].strip())
        for r in rows
        if r.get(a.truth, "").strip() and r.get(a.pred, "").strip()
    ]
    return {"pairs": agreement([t for t, _ in pairs], [p for _, p in pairs], a.positive)}


def main(argv=None) -> int:
    utf8_stdout()
    ap = argparse.ArgumentParser(description="사람 · 판정기 일치(카파 · TPR · TNR)")
    ap.add_argument("--human", type=Path, help="human_sample.py가 만들고 사람이 채운 CSV")
    ap.add_argument("--key", type=Path, help="human_<n>_key.csv")
    ap.add_argument("--judgments", type=Path, help="judge.py의 judgments.jsonl")
    ap.add_argument("--pairs", type=Path, help="점수형: 사람 · 판정 두 칸이 있는 CSV")
    ap.add_argument("--truth", default="사람")
    ap.add_argument("--pred", default="판정")
    ap.add_argument("--positive", default="B", help="양성 범주(쌍대는 B 승, 점수형은 예: 실패)")
    a = ap.parse_args(argv)
    if a.pairs:
        res, out_path = pointwise(a), a.pairs.with_name(a.pairs.stem + "_kappa.json")
    elif a.human and a.key and a.judgments:
        res, out_path = pairwise(a), a.human.with_name(a.human.stem + "_kappa.json")
    else:
        ap.error("--human --key --judgments 또는 --pairs가 필요해요")
    out_path.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{'차원':<6} {'n':>3} {'일치':>6} {'카파':>6} {'TPR':>6} {'TNR':>6}")
    for k, v in res.items():
        kap = "-" if v["kappa"] is None else v["kappa"]
        print(f"{k:<6} {v['n']:>3} {v['agree'] if v['agree'] is not None else '-':>6} {kap:>6} "
              f"{v['tpr'] if v['tpr'] is not None else '-':>6} {v['tnr'] if v['tnr'] is not None else '-':>6}")  # fmt: skip
    print(f"저장: {out_path} · 목표 κ ≥ 0.7, TNR ≥ 0.9(양성 = {a.positive})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
