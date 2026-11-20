"""v4 비서 의도 held-out 평가: 지금 무료 모드 길(v3 입구 관문 → step_card) vs 새 의도 모델(LLM 0회 · DB 없음).

    cd backend && uv run python ../evaluation/v4/intent/evaluate.py --final

held-out은 마지막에 한 번만 봐요(--final). 고르기(모델 · C · 온도 · 기준값)는 train.py가 dev로 끝냈어요.
- base_v3: 지금 길(baseline.py). model: intent_v4의 가장 높은 라벨 → CARD_OF 카드.
- model_t: 신뢰도 < 기준값이면 base_v3 길로(무료 모드에 넣을 꼴).
- sk_*: train.py --final이 남긴 비교 모델 예측(온도 보정 없음). sk_lr_char는 본 모델과 같은 가중치의 보정 전 확률이에요.
- 지표 · 구간은 metrics.py(부트스트랩 2,000번, 항목을 다시 뽑아요). 결과: results/heldout.json
"""

import argparse
import gzip
import json
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[2] / "backend"))

import baseline
import metrics as M
from kit import jsonl, utf8_stdout

from app.assistant import intent_v4

RESULTS = HERE / "results"
LABELS = intent_v4.LABELS
CARD = intent_v4.CARD_OF
THRESHOLDS = [round(0.2 + 0.05 * k, 2) for k in range(15)]


def run_model(rows: list[dict]) -> dict:
    out: dict = {"pred": [], "conf": [], "probs": []}
    for r in rows:
        p = intent_v4.probs(r["text"])
        lab = max(p, key=p.__getitem__)
        out["pred"].append(lab)
        out["conf"].append(p[lab])
        out["probs"].append({k: round(v, 6) for k, v in p.items()})
    out["cards"] = [{CARD[x]} for x in out["pred"]]
    return out


def score(rows: list[dict], sys_: dict, *, ece_ok: bool = True, boot: bool = True) -> dict:
    gold = [r["label"] for r in rows]
    alt = [r.get("alt", []) for r in rows]
    pred = sys_["pred"]
    gl = M.lenient(gold, alt, pred)
    gold_cards = [{CARD[r["label"]]} for r in rows]
    gold_cards_l = [{CARD[r["label"]], *(CARD[a] for a in r.get("alt", []))} for r in rows]
    hits = M.card_hits(gold_cards, sys_["cards"])
    hits_l = M.card_hits(gold_cards_l, sys_["cards"])
    correct = [g == p for g, p in zip(gold, pred, strict=True)]
    n = len(rows)
    res = {
        "n": n,
        "accuracy": M.accuracy(gold, pred),
        "macro_f1": M.macro_f1(gold, pred, LABELS),
        "macro_f1_lenient": M.macro_f1(gl, pred, LABELS),
        "oos_recall": M.recall_of(gold, pred),
        "card_acc": sum(hits) / n,
        "card_acc_lenient": sum(hits_l) / n,
        "per_label": M.per_label(gold, pred, LABELS),
    }
    if ece_ok:
        res["ece"] = M.ece(sys_["conf"], correct)
        res["reliability"] = M.reliability(sys_["conf"], correct)
    if boot:
        pk = M.pick
        res["ci"] = {
            "macro_f1": M.bootstrap(lambda i: M.macro_f1(pk(gold, i), pk(pred, i), LABELS), n),
            "oos_recall": M.bootstrap(lambda i: M.recall_of(pk(gold, i), pk(pred, i)), n),
            "card_acc": M.bootstrap(lambda i: sum(pk(hits, i)) / len(i), n),
            "accuracy": M.bootstrap(lambda i: M.accuracy(pk(gold, i), pk(pred, i)), n),
        }
        if ece_ok:
            res["ci"]["ece"] = M.bootstrap(lambda i: M.ece(pk(sys_["conf"], i), pk(correct, i)), n)
    return res


def paired(rows: list[dict], a: dict, b: dict) -> dict:
    """b − a 차이의 부트스트랩 구간(같은 표본)."""
    gold = [r["label"] for r in rows]
    gc = [{CARD[r["label"]]} for r in rows]
    ha, hb = M.card_hits(gc, a["cards"]), M.card_hits(gc, b["cards"])
    n = len(rows)

    def d_f1(i):
        g = M.pick(gold, i)
        return M.macro_f1(g, M.pick(b["pred"], i), LABELS) - M.macro_f1(
            g, M.pick(a["pred"], i), LABELS
        )

    def d_card(i):
        return (sum(M.pick(hb, i)) - sum(M.pick(ha, i))) / len(i)

    return {
        "macro_f1": M.macro_f1(gold, b["pred"], LABELS) - M.macro_f1(gold, a["pred"], LABELS),
        "macro_f1_ci": M.bootstrap(d_f1, n),
        "card_acc": (sum(hb) - sum(ha)) / n,
        "card_acc_ci": M.bootstrap(d_card, n),
    }


def _ms(fn, rows: list[dict], reps: int) -> list[float]:
    out = []
    for _ in range(reps):
        for r in rows:
            s = time.perf_counter()
            fn(r["text"])
            out.append((time.perf_counter() - s) * 1000)
    return sorted(out)


def latency(rows: list[dict]) -> dict:
    """한 문장 추론 시간(ms, 순수 파이썬, held-out × 5번). 비교로 지금 입구 관문 한 번 값도 재요."""
    t0 = time.perf_counter()
    intent_v4._model.cache_clear()
    intent_v4._model()
    load_ms = (time.perf_counter() - t0) * 1000
    times = _ms(intent_v4.probs, rows, 5)
    gate = _ms(baseline.route_of, rows, 5)
    raw = json.loads(gzip.decompress(intent_v4.MODEL.read_bytes()))
    return {
        "load_ms": round(load_ms, 1),
        "ms_median": round(statistics.median(times), 3),
        "ms_p95": round(times[int(len(times) * 0.95)], 3),
        "gate_v3_ms_median": round(statistics.median(gate), 3),
        "gate_v3_ms_p95": round(gate[int(len(gate) * 0.95)], 3),
        "file_kb": round(intent_v4.MODEL.stat().st_size / 1024, 1),
        "features": len(raw["features"]),
    }


def confusion(rows: list[dict], pred: list) -> dict:
    out = {g: {p: 0 for p in [*LABELS, None]} for g in LABELS}
    for r, p in zip(rows, pred, strict=True):
        out[r["label"]][p] += 1
    return {g: {str(p): c for p, c in row.items() if c} for g, row in out.items()}


def fmt(x: float, ci: tuple | None = None, pct: bool = False) -> str:
    f = (lambda v: f"{v * 100:.1f}%") if pct else (lambda v: f"{v:.3f}")
    return f"{f(x)} ({f(ci[0])}~{f(ci[1])})" if ci else f(x)


def main() -> int:
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--final", action="store_true")
    args = ap.parse_args()
    if not args.final:
        print("held-out은 마지막에 한 번만 봐요. 정말이면 --final을 같이 주세요.")
        return 2
    rows = jsonl(HERE / "heldout.jsonl")
    base = baseline.run(rows)
    model = run_model(rows)
    t = intent_v4.threshold()
    mt = M.hybrid(model, base, t)
    systems = {"base_v3": base, "model": model, "model_t": mt}
    extra = HERE / "results" / "compare_models_heldout.json"
    if extra.exists():
        got = json.loads(extra.read_text(encoding="utf-8"))
        assert got["ids"] == [r["id"] for r in rows], "비교 모델 예측과 held-out 순서가 달라요"
        for kind, m in got["models"].items():
            systems[f"sk_{kind}"] = {
                "pred": m["pred"], "conf": m["conf"], "cards": [{CARD[x]} for x in m["pred"]],
            }  # fmt: skip
    slices = {
        "customer": [i for i, r in enumerate(rows) if r["surface"] == "customer"],
        "vendor": [i for i, r in enumerate(rows) if r["surface"] == "vendor"],
        "no_ctx": [i for i, r in enumerate(rows) if not r.get("ctx")],
    }
    report: dict = {"threshold": t, "n": len(rows), "systems": {}, "slices": {}}
    for name, s in systems.items():
        report["systems"][name] = score(rows, s, ece_ok=True, boot=True)
    for sl, idx in slices.items():
        sub_rows = [rows[i] for i in idx]
        report["slices"][sl] = {
            name: score(
                sub_rows,
                {k: [v[i] for i in idx] for k, v in s.items() if isinstance(v, list)},
                ece_ok=False,
                boot=False,
            )
            for name, s in (("base_v3", base), ("model", model), ("model_t", mt))
        }
    report["paired"] = {
        "model_vs_base": paired(rows, base, model),
        "model_t_vs_base": paired(rows, base, mt),
    }
    gold = [r["label"] for r in rows]
    correct = [g == p for g, p in zip(gold, model["pred"], strict=True)]
    curve = M.curve(model["conf"], correct, THRESHOLDS)
    gc = [{CARD[r["label"]]} for r in rows]
    for c in curve:
        h = M.hybrid(model, base, c["t"])
        c["hybrid_card_acc"] = sum(M.card_hits(gc, h["cards"])) / len(rows)
        c["hybrid_macro_f1"] = M.macro_f1(gold, h["pred"], LABELS)
    report["curve"] = curve
    report["confusion_model"] = confusion(rows, model["pred"])
    report["confusion_base"] = confusion(rows, base["pred"])
    report["routes_base"] = {r: base["route"].count(r) for r in sorted(set(base["route"]))}
    report["latency"] = latency(rows)
    report["items"] = [
        {"id": r["id"], "gold": r["label"], "base": b, "route": rt, "model": m, "conf": round(c, 4)}
        for r, b, rt, m, c in zip(
            rows, base["pred"], base["route"], model["pred"], model["conf"], strict=True
        )
    ]
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "heldout.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1, default=str),
        encoding="utf-8",
        newline="\n",
    )
    # 표
    print(f"held-out {len(rows)}줄 · 기준값 {t}")
    print("| 방식 | macro-F1 | 범위 밖 재현율 | 카드 정답률 | 정확도 | ECE |")
    print("| --- | --- | --- | --- | --- | --- |")
    for name, s in report["systems"].items():
        ci = s["ci"]
        print(
            f"| {name} | {fmt(s['macro_f1'], ci['macro_f1'])} | {fmt(s['oos_recall'], ci['oos_recall'], True)} | "
            f"{fmt(s['card_acc'], ci['card_acc'], True)} | {fmt(s['accuracy'], ci['accuracy'], True)} | "
            f"{fmt(s['ece'], ci['ece'])} |"
        )
    for k, d in report["paired"].items():
        print(
            f"{k}: macro-F1 {d['macro_f1']:+.3f} ({d['macro_f1_ci'][0]:+.3f}~{d['macro_f1_ci'][1]:+.3f}) · "
            f"카드 {d['card_acc'] * 100:+.1f}%p ({d['card_acc_ci'][0] * 100:+.1f}~{d['card_acc_ci'][1] * 100:+.1f})"
        )
    print("라벨별 F1(base → model):")
    for lab in LABELS:
        b = report["systems"]["base_v3"]["per_label"][lab]
        m = report["systems"]["model"]["per_label"][lab]
        print(f"  {lab}: {b['f1']:.2f} → {m['f1']:.2f} (n={m['n']}, P {m['p']:.2f} R {m['r']:.2f})")
    print("기준값 곡선(t: 받은 비율 · 받은 것 정확도 · 섞은 카드 정답률):")
    for c in curve:
        print(f"  {c['t']:.2f}: {c['answered']:.1%} · {c['acc']:.1%} · {c['hybrid_card_acc']:.1%}")
    print("속도:", report["latency"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
