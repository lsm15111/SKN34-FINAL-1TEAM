import io, json, sys
from datetime import date
from app.mvp import v2_schemas as v2, v2_service as sv
HERE = sys.argv[1]; T = date(2026, 11, 11)
cases = json.load(io.open(f"{HERE}/v2_cases.json", encoding="utf-8")); gold = json.load(io.open(f"{HERE}/v2_golden.json", encoding="utf-8"))
tie = other = 0; plans = set()
for c, g in zip(cases, gold):
    if c["fn"] == "quoteOf":
        py = json.loads(sv.quote(v2.MvpV2QuoteIn(**c["in"]), T).model_dump_json()); js = g["ok"]
        if js["total"] != py["total"] or js["inp"]["measured"] != py["inp"]["measured"]:
            m1, m2 = js["inp"]["measured"], py["inp"]["measured"]
            if m1 and m1 != m2 and all(abs(m1[k] - m2[k]) <= 0.1001 for k in ("wall_m2", "ceiling_m2", "molding_m", "base_m")): tie += 1; plans.add((c["in"]["plan"]["id"], c["in"]["plan"]["expanded"], str(c["in"]["plan"]["kinds"])))
            else: other += 1; print("OTHER", js["total"], py["total"])
print("tie", tie, "other", other, sorted(plans))
