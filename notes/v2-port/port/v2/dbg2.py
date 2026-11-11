import io, json, sys
from datetime import date
from app.mvp import v2_schemas as v2, v2_service as sv
HERE = sys.argv[1]
cases = json.load(io.open(f"{HERE}/v2_cases.json", encoding="utf-8")); gold = json.load(io.open(f"{HERE}/v2_golden.json", encoding="utf-8"))
n = 0
for c, g in zip(cases, gold):
    if c["fn"] != "checkOf" or "ok" not in g: continue
    py = json.loads(sv.check(v2.MvpV2CheckIn(**c["in"]), date(2026,11,11)).model_dump_json())
    js = g["ok"]
    if js.get("notes") != py.get("notes") or js.get("lo") != py.get("lo"):
        n += 1
        if n < 6: print(js.get("notes"), "|", py.get("notes"), js.get("lo"), py.get("lo"), js.get("warn"), py.get("warn"), c["in"]["scope"], c["in"]["quote"]["plan"])
