import io, json, sys
from datetime import date
from app.mvp import v2_schemas as v2, v2_service as sv
HERE = sys.argv[1]
cases = json.load(io.open(f"{HERE}/v2_cases.json", encoding="utf-8")); gold = json.load(io.open(f"{HERE}/v2_golden.json", encoding="utf-8"))
n = 0
from collections import Counter
kinds = Counter()
for c, g in zip(cases, gold):
    if c["fn"] not in ("quoteOf", "checkOf"): continue
    try:
        py = json.loads((sv.quote(v2.MvpV2QuoteIn(**c["in"]), date(2026, 11, 11)) if c["fn"] == "quoteOf" else sv.check(v2.MvpV2CheckIn(**c["in"]), date(2026,11,11))).model_dump_json(by_alias=True))
    except Exception as e:
        print("ERR", e); continue
    js = g["ok"]
    if c["fn"] == "checkOf":
        for k in ("lo", "hi", "supply", "where", "pct", "notes"):
            if js.get(k) != py.get(k): kinds["check." + k] += 1; 
        if n < 6 and any(js.get(k) != py.get(k) for k in ("lo","hi")): n += 1; print("CHK", {k: (js.get(k), py.get(k)) for k in ("lo","hi","notes")}, c["in"]["trade"], c["in"]["quote"]["plan"], c["in"]["quote"]["pyeong"])
        continue
    for a, b in zip(js["precise"], py["precise"]):
        ka, kb = [l["key"] for l in a["lines"]], [l["key"] for l in b["lines"]]
        if ka != kb:
            kinds[(a["trade"], tuple(set(ka) ^ set(kb)))] += 1
            continue
        for la, lb in zip(a["lines"], b["lines"]):
            for k in la:
                if la[k] != lb[k] and not (isinstance(la[k], (int, float)) and lb[k] is not None and abs(la[k] - lb[k]) < 1e-9):
                    kinds[(a["trade"], la["key"], k)] += 1
                    if n < 10: n += 1; print("LINE", a["trade"], la["key"], k, la[k], "|", lb[k], json.dumps(c["in"]["mok"], ensure_ascii=False)[:300], c["in"]["plan"], c["in"]["pyeong"])
    if js["inp"].get("measured") != py["inp"].get("measured"): kinds["measured"] += 1
for k, v in kinds.most_common(): print(v, k)
