import dataclasses, io, itertools, json, subprocess, sys
from decimal import Decimal as D
from app.calc.market_band import MarketDobaeInput, MarketMokgongInput, dobae, extras_range, gap_steps, mokgong
from app.calc.plan_qty import Plan, from_plan
from app.refprice.mvp_market import GAP_DOBAE, GAP_MOKGONG, MARKET_2026_11 as B, PUBLIC_EQ_DOBAE, PUBLIC_EQ_MOKGONG
HERE = sys.argv[1]
EMPTY = from_plan(Plan(spaces=()))
cases, pys = [], []
areas = [D("33.1"), D("59.5"), D("84.9"), D("109.1"), D("135.2")]
for ar, basis, g, ceil, occ, bal, pl in itertools.product(areas, ["supply", "exclusive"], ["economy", "basic"], [True, False], [True, False], [True, False], [None, (D("72.0"), D("36.8"), D("35.9"), D("31.7"))]):
    pq = dataclasses.replace(EMPTY, wall_m2=pl[0], ceiling_m2=pl[1]) if pl else None
    inp = MarketDobaeInput(ar, g, basis, ceil, occ, bal, pq, "시험" if pl else "")
    pub = {"supply": int(ar * 27000), "vat": int(ar * 2700)}
    pys.append(("dobae", inp, pub))
    cases.append({"kind": "dobae", "pub": pub, "input": {"area_m2": float(ar), "area_basis": basis, "grade": g, "include_ceiling": ceil, "occupied": occ, "balcony_ext": bal, "measured": {"name": "시험", "wall_m2": float(pl[0]), "ceiling_m2": float(pl[1])} if pl else None}})
item_sets = [("molding",), ("base",), ("door",), ("flatten",), ("molding", "base"), ("molding", "base", "door"), ("molding", "base", "door", "flatten")]
for ar, basis, items, doors, frame, pl, x in itertools.product(areas, ["supply", "exclusive"], item_sets, [0, 3], [True, False], [None, (D("35.9"), D("31.7"))], [0, 1_301_200]):
    pq = dataclasses.replace(EMPTY, molding_m=pl[0], base_m=pl[1]) if pl else None
    inp = MarketMokgongInput(ar, items, basis, doors, frame, pq, "시험" if pl else "", x)
    pub = {"supply": int(ar * 15000) + x, "vat": int(ar * 1500)}
    pys.append(("mokgong", inp, pub))
    cases.append({"kind": "mokgong", "pub": pub, "input": {"area_m2": float(ar), "area_basis": basis, "items": list(items), "doors": doors, "door_frame": frame, "measured": {"name": "시험", "molding_m": float(pl[0]), "base_m": float(pl[1])} if pl else None, "extra_amount": x}})
for picks, cd, wd in [({}, 0, False), ({"jungmun": 1, "aircon": 2}, 0, False), ({"wall": 1, "insul": 3, "artwall": 1, "lightbox": 1}, 4, True), ({}, 5, False)]:
    pys.append(("extras", (picks, cd, wd), None))
    cases.append({"kind": "extras", "picks": picks, "casing": {"doors": cd, "with_door": wd} if cd else None})
io.open(f"{HERE}/mk_cases.json", "w", encoding="utf-8").write(json.dumps(cases, ensure_ascii=False))
subprocess.run(["node", "mk_golden.js", "mk_cases.json", "mk_golden.json"], cwd=HERE, check=True)
gold = json.load(io.open(f"{HERE}/mk_golden.json", encoding="utf-8"))
bad = 0
for (kind, inp, pub), g in zip(pys, gold):
    if kind == "extras":
        r = extras_range(B.mokgong, inp[0], inp[1], inp[2]); got = {"lo": r.lo, "hi": r.hi, "notes": r.notes}
    else:
        r = (dobae if kind == "dobae" else mokgong)(inp, B)
        gp = gap_steps(inp, B, PUBLIC_EQ_DOBAE if kind == "dobae" else PUBLIC_EQ_MOKGONG, GAP_DOBAE if kind == "dobae" else GAP_MOKGONG, pub["supply"], pub["vat"])
        got = {"lines": [[l.key, l.name, None if l.qty is None else float(l.qty), l.unit_price, l.amount, l.note] for l in r.lines], "supply": r.supply, "lo": r.lo, "hi": r.hi, "band": [float(r.band.lo), float(r.band.hi)], "gap": {"from": gp.start, "steps": [[s.key, s.d] for s in gp.steps], "to": gp.end}}
    for k in got:
        if got[k] != g[k]:
            bad += 1
            if bad <= 5: print("DIFF", kind, k, "\n py", got[k], "\n js", g[k])
            break
print("cases", len(pys), "mismatches", bad)
