"""무료 모드 고객 길 고르기: 규칙만 / 모델만 / 규칙 먼저 + 모델(기준값)을 dev로 고르고, held-out은 고른 하나만 한 번.

    cd backend && uv run python ../evaluation/v4/intent/select_route.py            # dev로 고르기(results/route_dev.json)
    cd backend && uv run python ../evaluation/v4/intent/select_route.py --final    # 고른 길 · 두 기준선 held-out(results/route_heldout.json)
    cd backend && uv run python ../evaluation/v4/intent/select_route.py --second   # 2판: held-out 두 번째 · 확인 세트

- 고객 말만 봐요(연결은 무료 모드 고객 길에만 해요). 업체 화면 · LLM 모드 길은 그대로예요.
- 길 흉내(DB 없음, free.answer와 같은 순서)
  1. 의도 → handler: 규칙(free.intent_of) 또는 모델 라벨(LABEL_DO). 업체 연결 의도(compare · slots · vendors)인데 도배 없이
     다른 공정만 말하면 today 카드(도배만 안내).
  2. handler가 없으면 지식 길: 지금처럼 v3 관문 단계 카드(step) 또는, 모델이 지식 · 범위 밖으로 정했으면 카드 없이 답만.
  - 카드는 상태에 따라 비기도 해서(업체 · 견적서 없음) 정해 둔 카드 종류로 견줘요. 두 방식 모두 같은 handler를 써요.
- 정답 카드: CARD_OF[정답 라벨]. 업체 연결이 아직 도배만이라, 업체 · 실측 · 견적서 정답인데 도배 없이 다른 공정만 말하면 today.
- 모델 확률은 dev에서는 겹 밖 확률(train.py의 results/dev_oof.json), held-out에서는 내보낸 모델(intent_v4)이에요.
- 고르는 값: dev 카드 정답률(같으면 macro-F1). 범위 밖 재현율이 규칙만보다 낮으면 범위 밖 규칙(v3 policy)을 먼저 둔 판을 봐요.
"""

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[2] / "backend"))

import baseline
import metrics as M
from kit import jsonl, utf8_stdout

from app.agent.v3 import policy as v3_policy
from app.assistant import free, intent_v4

RESULTS = HERE / "results"
LABELS = intent_v4.LABELS
CARD = intent_v4.CARD_OF
RULE_LABEL = {
    "compare": "quote_compare", "slots": "visit", "vendors": "vendor_pick", "schedule": "schedule",
    "standard": "standard_quote", "home": "home_info", "today": "guide",
}  # fmt: skip
LABEL_DO = {v: k for k, v in RULE_LABEL.items()}  # 모델 라벨 → handler(지식 · 범위 밖은 없음)
HANDLER_CARD = {k: CARD[v] for k, v in RULE_LABEL.items()}
LINKED_LABELS = {RULE_LABEL[k] for k in free.LINKED}
THRESHOLDS = [round(0.2 + 0.05 * k, 2) for k in range(15)]


def other_trade_only(text: str) -> bool:
    found = free.trades_in(text)
    return bool(found) and "dobae" not in found


def gold_card(row: dict) -> set:
    if row["label"] in LINKED_LABELS and other_trade_only(row["text"]):
        return {"today"}
    return {CARD[row["label"]]}


def path(row: dict, intent: str | None, decided: str, model_label: str | None) -> tuple:
    """(라벨, 카드 묶음). decided: rule | model | none(지금 지식 길)."""
    text = row["text"]
    if intent is not None:
        label = RULE_LABEL[intent]
        if intent in free.LINKED and other_trade_only(text):
            return label, {"today"}
        return label, {HANDLER_CARD[intent]}
    if decided == "model":  # 모델이 지식 · 범위 밖으로 정함: 카드 없이 답만
        return model_label, {None}
    route, _ = baseline.route_of(text)
    return baseline.label_of(route, row["label"]), baseline.ROUTE_CARDS[route]


def route(row: dict, design: str, p: dict, t: float = 0.0, oos_first: bool = False) -> tuple:
    text = row["text"]
    if oos_first and v3_policy.out_of_scope(text, bool(free.trades_in(text))):
        return "out_of_scope", {None}
    rule = free.intent_of(text, "customer")
    lab = max(p, key=p.__getitem__)
    sure = p[lab] >= t
    if design == "rules":
        return path(row, rule, "rule" if rule else "none", None)
    if design == "model":
        return path(row, LABEL_DO.get(lab), "model", lab)
    # 2판: 모델만 + 순서 · 시기 · 방법 질문은 지식(free.customer_intent와 같음)
    if design == "model_how":
        if lab in free.HOW_LABELS and rule is None and free.asks_how(text):
            return path(row, None, "model", "knowledge")
        return path(row, LABEL_DO.get(lab), "model", lab)
    # rules_model: 규칙 먼저, 없으면 신뢰도 ≥ t인 모델, 그 아래는 지금 지식 길
    if rule is not None:
        return path(row, rule, "rule", None)
    if sure:
        return path(row, LABEL_DO.get(lab), "model", lab)
    return path(row, None, "none", None)


def run(rows: list[dict], probs: list[dict], design: str, t: float = 0.0, oos_first=False) -> dict:
    got = [route(r, design, p, t, oos_first) for r, p in zip(rows, probs, strict=True)]
    return {
        "pred": [g[0] for g in got],
        "cards": [g[1] for g in got],
        "conf": [max(p.values()) for p in probs],
    }


def old_base(rows: list[dict]) -> dict:
    """옛 기준선: v3 관문 → step_card(지식 길만 있는 꼴)."""
    return baseline.run(rows)


def measure(rows: list[dict], sys_: dict, boot: bool = False) -> dict:
    gold = [r["label"] for r in rows]
    gc = [gold_card(r) for r in rows]
    hits = M.card_hits(gc, sys_["cards"])
    out = {
        "n": len(rows),
        "card_acc": sum(hits) / len(rows),
        "macro_f1": M.macro_f1(gold, sys_["pred"], LABELS),
        "accuracy": M.accuracy(gold, sys_["pred"]),
        "oos_recall": M.recall_of(gold, sys_["pred"]),
        "per_label": M.per_label(gold, sys_["pred"], LABELS),
    }
    if boot:
        pk, n, pred = M.pick, len(rows), sys_["pred"]
        out["ci"] = {
            "card_acc": M.bootstrap(lambda i: sum(pk(hits, i)) / len(i), n),
            "macro_f1": M.bootstrap(lambda i: M.macro_f1(pk(gold, i), pk(pred, i), LABELS), n),
            "oos_recall": M.bootstrap(lambda i: M.recall_of(pk(gold, i), pk(pred, i)), n),
        }
    return out


def paired(rows: list[dict], a: dict, b: dict) -> dict:
    """b − a(같은 표본 부트스트랩)."""
    gold = [r["label"] for r in rows]
    gc = [gold_card(r) for r in rows]
    ha, hb = M.card_hits(gc, a["cards"]), M.card_hits(gc, b["cards"])
    n = len(rows)

    def d_f1(i):
        g = M.pick(gold, i)
        fb = M.macro_f1(g, M.pick(b["pred"], i), LABELS)
        return fb - M.macro_f1(g, M.pick(a["pred"], i), LABELS)

    return {
        "card_acc": (sum(hb) - sum(ha)) / n,
        "card_acc_ci": M.bootstrap(lambda i: (sum(M.pick(hb, i)) - sum(M.pick(ha, i))) / len(i), n),
        "macro_f1": M.macro_f1(gold, b["pred"], LABELS) - M.macro_f1(gold, a["pred"], LABELS),
        "macro_f1_ci": M.bootstrap(d_f1, n),
    }


def dev_choice() -> dict:
    dev = [r for r in jsonl(HERE / "dev.jsonl")]
    oof = json.loads((RESULTS / "dev_oof.json").read_text(encoding="utf-8"))
    assert oof["ids"] == [r["id"] for r in dev], (
        "dev와 겹 밖 확률 순서가 달라요(train.py를 다시 돌려요)"
    )
    probs_all = [dict(zip(oof["labels"], row, strict=True)) for row in oof["probs"]]
    keep = [i for i, r in enumerate(dev) if r["surface"] == "customer"]
    rows = [dev[i] for i in keep]
    probs = [probs_all[i] for i in keep]
    table = []
    for oos_first in (False, True):
        table.append(
            {"design": "rules", "t": None, "oos_first": oos_first,
             **measure(rows, run(rows, probs, "rules", oos_first=oos_first))}
        )  # fmt: skip
        table.append(
            {"design": "model", "t": None, "oos_first": oos_first,
             **measure(rows, run(rows, probs, "model", oos_first=oos_first))}
        )  # fmt: skip
        for t in THRESHOLDS:
            table.append(
                {"design": "rules_model", "t": t, "oos_first": oos_first,
                 **measure(rows, run(rows, probs, "rules_model", t, oos_first))}
            )  # fmt: skip
    rules_oos = next(x for x in table if x["design"] == "rules" and not x["oos_first"])
    plain = [x for x in table if not x["oos_first"]]
    best = max(plain, key=lambda x: (round(x["card_acc"], 6), round(x["macro_f1"], 6)))
    # 리드 결정: 범위 밖 재현율이 규칙만보다 떨어지면 범위 밖 규칙을 먼저
    if best["oos_recall"] < rules_oos["oos_recall"]:
        same = [
            x
            for x in table
            if x["oos_first"] and x["design"] == best["design"] and x["t"] == best["t"]
        ]
        best = same[0]
    return {"n": len(rows), "table": table, "choice": best}


def show(name: str, s: dict) -> None:
    ci = s.get("ci")
    if ci:
        print(
            f"{name}: 카드 {s['card_acc']:.1%} ({ci['card_acc'][0]:.1%}~{ci['card_acc'][1]:.1%}) · "
            f"macro-F1 {s['macro_f1']:.3f} ({ci['macro_f1'][0]:.3f}~{ci['macro_f1'][1]:.3f}) · "
            f"범위 밖 {s['oos_recall']:.1%} ({ci['oos_recall'][0]:.1%}~{ci['oos_recall'][1]:.1%})"
        )
    else:
        print(
            f"{name}: 카드 {s['card_acc']:.1%} · macro-F1 {s['macro_f1']:.3f} · 정확도 {s['accuracy']:.1%}"
        )


def second() -> None:
    """2판(순서 · 시기 · 방법 질문 → 지식): held-out은 두 번째로 보고, 확인 세트(라벨 먼저)는 처음 봐요."""
    held = [r for r in jsonl(HERE / "heldout.jsonl") if r["surface"] == "customer"]
    flow = jsonl(HERE / "check_flow.jsonl")
    out: dict = {"look": 2, "note": "held-out 두 번째로 봄(2판 규칙은 dev · 어려운 예로 고름)"}
    for name, rows in (("heldout", held), ("check_flow", flow)):
        probs = [intent_v4.probs(r["text"]) for r in rows]
        systems = {
            "old_v3": old_base(rows),
            "rules": run(rows, probs, "rules"),
            "model": run(rows, probs, "model"),
            "model_how": run(rows, probs, "model_how"),
        }
        rep = {
            "n": len(rows),
            "systems": {k: measure(rows, s, boot=True) for k, s in systems.items()},
            "paired": {
                "how_vs_rules": paired(rows, systems["rules"], systems["model_how"]),
                "how_vs_old": paired(rows, systems["old_v3"], systems["model_how"]),
                "how_vs_model": paired(rows, systems["model"], systems["model_how"]),
            },
            "items": [
                {"id": r["id"], "gold": r["label"], **{k: s["pred"][i] for k, s in systems.items()}}
                for i, r in enumerate(rows)
            ],
        }
        if name == "check_flow":
            for part, keep in (("want", lambda r: r["kind"].startswith("want_")), ("other", None)):
                idx = [
                    i
                    for i, r in enumerate(rows)
                    if (keep(r) if keep else not r["kind"].startswith("want_"))
                ]
                sub = [rows[i] for i in idx]
                rep[f"part_{part}"] = {
                    k: measure(sub, {kk: [v[i] for i in idx] for kk, v in s.items()})
                    for k, s in systems.items()
                }
        out[name] = rep
        print(
            f"{name} {len(rows)}줄"
            + (" (held-out 두 번째)" if name == "heldout" else " (라벨 먼저)")
        )
        for k, s in rep["systems"].items():
            show(f"  {k}", s)
        for k, d in rep["paired"].items():
            print(
                f"  {k}: 카드 {d['card_acc'] * 100:+.1f}%p ({d['card_acc_ci'][0] * 100:+.1f}~"
                f"{d['card_acc_ci'][1] * 100:+.1f}) · macro-F1 {d['macro_f1']:+.3f}"
            )
        for part in ("part_want", "part_other"):
            if part in rep:
                print(
                    f"  {part}: "
                    + " · ".join(f"{k} {s['card_acc']:.0%}" for k, s in rep[part].items())
                )
    (RESULTS / "route_second.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8", newline="\n"
    )


def label(x: dict) -> str:
    name = {"rules": "규칙만", "model": "모델만", "rules_model": "규칙 먼저 + 모델"}[x["design"]]
    if x["t"] is not None:
        name += f"(기준값 {x['t']})"
    return name + (" · 범위 밖 규칙 먼저" if x["oos_first"] else "")


def main() -> int:
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--final", action="store_true", help="고른 길 하나와 두 기준선을 held-out으로 한 번"
    )
    ap.add_argument(
        "--second",
        action="store_true",
        help="2판: held-out 두 번째 · 확인 세트(results/route_second.json)",
    )
    args = ap.parse_args()
    if args.second:
        second()
        return 0
    got = dev_choice()
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "route_dev.json").write_text(
        json.dumps(got, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n"
    )
    print(f"dev 고객 말 {got['n']}줄(모델 확률은 겹 밖)")
    print("| 길 | 카드 정답률 | macro-F1 | 범위 밖 재현율 |")
    print("| --- | --- | --- | --- |")
    for x in got["table"]:
        if x["design"] != "rules_model" or x["t"] in (0.2, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9):
            print(
                f"| {label(x)} | {x['card_acc']:.1%} | {x['macro_f1']:.3f} | {x['oos_recall']:.1%} |"
            )
    c = got["choice"]
    print(f"고른 길: {label(c)}")
    if not args.final:
        return 0
    held = [r for r in jsonl(HERE / "heldout.jsonl") if r["surface"] == "customer"]
    probs = [intent_v4.probs(r["text"]) for r in held]
    systems = {
        "old_v3": old_base(held),
        "rules": run(held, probs, "rules"),
        "chosen": run(held, probs, c["design"], c["t"] or 0.0, c["oos_first"]),
    }
    rep = {
        "choice": {k: c[k] for k in ("design", "t", "oos_first")},
        "n": len(held),
        "systems": {k: measure(held, s, boot=True) for k, s in systems.items()},
        "paired": {
            "chosen_vs_rules": paired(held, systems["rules"], systems["chosen"]),
            "chosen_vs_old": paired(held, systems["old_v3"], systems["chosen"]),
            "rules_vs_old": paired(held, systems["old_v3"], systems["rules"]),
        },
        "items": [
            {"id": r["id"], "gold": r["label"], "old": o, "rules": ru, "chosen": ch}
            for r, o, ru, ch in zip(
                held,
                systems["old_v3"]["pred"],
                systems["rules"]["pred"],
                systems["chosen"]["pred"],
                strict=True,
            )
        ],
    }
    (RESULTS / "route_heldout.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=1, default=str), encoding="utf-8", newline="\n"
    )
    print(f"held-out 고객 말 {len(held)}줄(한 번)")
    for k, s in rep["systems"].items():
        ci = s["ci"]
        print(
            f"{k}: 카드 {s['card_acc']:.1%} ({ci['card_acc'][0]:.1%}~{ci['card_acc'][1]:.1%}) · "
            f"macro-F1 {s['macro_f1']:.3f} ({ci['macro_f1'][0]:.3f}~{ci['macro_f1'][1]:.3f}) · "
            f"범위 밖 {s['oos_recall']:.1%} ({ci['oos_recall'][0]:.1%}~{ci['oos_recall'][1]:.1%})"
        )
    for k, d in rep["paired"].items():
        print(
            f"{k}: 카드 {d['card_acc'] * 100:+.1f}%p ({d['card_acc_ci'][0] * 100:+.1f}~"
            f"{d['card_acc_ci'][1] * 100:+.1f}) · macro-F1 {d['macro_f1']:+.3f} "
            f"({d['macro_f1_ci'][0]:+.3f}~{d['macro_f1_ci'][1]:+.3f})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
