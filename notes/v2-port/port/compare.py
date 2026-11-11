import json, sys
from decimal import Decimal
from app.calc.plan_qty import Plan, PlanOptions, PlanSpace, Window, from_plan
plans = {p["id"]: p for p in json.load(open(sys.argv[1], encoding="utf-8"))}
gold = json.load(open(sys.argv[2], encoding="utf-8"))
def to_plan(p):
    sps = tuple(PlanSpace(id=s["id"], ko=s["ko"], kind=s["kind"], w_mm=s["w"], d_mm=s["d"], paper=s["paper"], ext_mm=s.get("ext", 0), ext_side=s.get("ext_side", "d"), open_mm=s.get("open", 0), door_open=s.get("door_open", 0), own_door=bool(s.get("own_door")), windows=tuple(Window(x["w"], x["t"]) for x in s.get("win", [])), sure=s.get("sure", "mid")) for s in p["spaces"])
    wm = p.get("wall_mm") or {}
    return Plan(spaces=sps, wall_int_mm=wm.get("int", 180), wall_given=bool(wm.get("given")))
D = lambda x: Decimal(str(x))
bad = 0; tie = []; ttie = []
for g in gold:
    o = g["opts"]
    po = PlanOptions(expanded=o.get("expanded", True), ceiling=o.get("ceiling", True), ceiling_h=D(o.get("ceiling_h", "2.3")), kinds=tuple(o["kinds"]) if "kinds" in o else None)
    r = from_plan(to_plan(plans[g["id"]]), po)
    t = g["total"]
    mine = {"wall_m2": r.wall_m2, "ceiling_m2": r.ceiling_m2, "paper_m2": r.paper_m2, "primer_m2": r.primer_m2, "molding_m": r.molding_m, "molding_pcs": r.molding_pcs, "base_m": r.base_m, "base_pcs": r.base_pcs, "doors": r.doors, "casing_m": r.casing_m, "hapji": r.rolls["hapji"].rolls, "silk": r.rolls["silk"].rolls}
    js = {k: t[k] for k in mine if k in t} | {"hapji": t["rolls"]["hapji"]["rolls"], "silk": t["rolls"]["silk"]["rolls"]}
    for k in mine:
        if D(mine[k]) != D(js[k]):
            diff = abs(D(mine[k]) - D(js[k]))
            if diff == Decimal("0.1"): ttie.append((g["id"], g["combo"], k, mine[k], js[k]))
            else: bad += 1; print("TOTAL", g["id"], g["combo"], k, "py", mine[k], "js", js[k])
    for a, b in zip(r.spaces, g["spaces"]):
        for k, kk in [("w_m","w"),("d_m","d"),("floor_m2","floor"),("perim_m","perim"),("wall_m2","wall"),("ceiling_m2","ceiling"),("molding_m","molding"),("base_m","base"),("own_door","own_door"),("papered","papered")]:
            x, y = getattr(a, k), b[kk]
            if isinstance(x, bool):
                if x != y: bad += 1; print("SPACE-BOOL", g["id"], g["combo"], a.id, k, x, y)
            elif D(x) != D(y):
                diff = abs(D(x) - D(y))
                if diff == Decimal("0.1"): tie.append((g["id"], a.id, k, x, y))
                else: bad += 1; print("SPACE", g["id"], g["combo"], a.id, k, x, y)
    if r.low != g["low"]: bad += 1; print("LOW", g["id"])
print("py<js", sum(1 for *_, x, y in tie + ttie if Decimal(str(x)) < Decimal(str(y)))); print("cases", len(gold), "mismatches", bad, "space 0.1 ties", len(tie), "total 0.1", len(ttie)); print(sorted(set((a,b,c) for a,b,c,_,_ in tie))[:12]); print(ttie[:10])
