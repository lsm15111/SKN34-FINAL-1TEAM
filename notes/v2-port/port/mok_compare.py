"""MVP JS CALC10.mokgong과 calc.mvp_mokgong 대조. backend 폴더에서 PYTHONPATH=. 로 돌린다."""
import dataclasses, io, itertools, json, subprocess, sys
from decimal import Decimal as D
from app.calc.mvp_mokgong import CountSel, DoorSel, MokSel, MvpMokgongInput, quote
from app.calc.plan_qty import Plan, from_plan
from app.calc.common import m2
from app.refprice.book import MOKGONG_2026H2 as MG
from app.refprice.mvp_materials import MOK_2026_11 as B
HERE = sys.argv[1]
EMPTY = from_plan(Plan(spaces=()))
doors = [("none", None), ("replace", "door-yerim-abs-foam-set"), ("replace", "door-yerim-sound-set"), ("overlay", "door-woodin-membrane-brick"), ("leaf", "door-ace-abs-ad001-plain"), ("leaf", "door-yerim-paint-yfd101p")]
moldings = [("none", None), ("flat", "molding-youngrim-flat"), ("step", "molding-youngrim-ceiling-no1"), ("minus", "molding-youngrim-minus"), ("minus", "molding-dc-alu-minus")]
bases = [None, "molding-youngrim-pvc-baseboard80", "molding-namuman-mdf-baseboard", "molding-dc-hidden-baseboard"]
extras = [{}, {"flatten_overlay": True}, {"ceiling_redo": True, "coffer": D(1), "cove": D("6.5")}, {"curtain_box": True, "partition": D("4.3"), "hatch": D(2)}]
specials = [(0, 0), (1, 2)]
areas = [D("82.6"), D("109.1")]
plans = [None, dict(molding_m=D("88.4"), base_m=D("71.3"), ceiling_m2=D("63.2"), windows_m=D("9.6"), doors=5)]
cases, pys = [], []
for i, (dm, mo, ba, ex, sp, ar, pl) in enumerate(itertools.product(doors, moldings, bases, extras, specials, areas, plans)):
    if i % 3: continue
    cnt = None if i % 2 else 3
    sel = MokSel(door=DoorSel(dm[0], dm[1], cnt), slide=CountSel(sp[0], "door-yerim-hidden-sliding-set"), hidden=CountSel(sp[1], "door-yerim-hidden-set"), molding_type=mo[0], molding=mo[1], base=ba, extras=ex)
    pq = dataclasses.replace(EMPTY, **pl) if pl else None
    inp = MvpMokgongInput(area_m2=ar, sel=sel, occupied=bool(i % 4 == 0), doors=4, plan=pq, plan_name="시험 도면" if pl else "")
    auto = {"ceiling_m2": float(pl["ceiling_m2"]) if pl else float(m2(ar / D("1.32"))), "windows_m": float(pl["windows_m"]) if pl else 0}
    jsel = {"door": {"mode": dm[0], "pick": dm[1], "count": cnt}, "slide": {"n": sp[0], "pick": "door-yerim-hidden-sliding-set"}, "hidden": {"n": sp[1], "pick": "door-yerim-hidden-set"}, "molding": {"type": mo[0], "pick": mo[1]}, "base": {"pick": ba}, "extras": {k: (True if v is True else float(v)) for k, v in ex.items()}}
    measured = {"name": "시험 도면", "molding_m": float(pl["molding_m"]), "base_m": float(pl["base_m"])} if pl else None
    jdoors = (pl["doors"] if pl else 4)
    cases.append({"js": {"area_m2": float(ar), "occupied": inp.occupied, "doors": jdoors, "measured": measured, "auto": auto, "sel": jsel}})
    pys.append(inp)
io.open(f"{HERE}/mok_cases.json", "w", encoding="utf-8").write(json.dumps(cases, ensure_ascii=False))
subprocess.run(["node", "mok_golden.js", "mok_cases.json", "mok_golden.json"], cwd=HERE, check=True)
gold = json.load(io.open(f"{HERE}/mok_golden.json", encoding="utf-8"))
bad = 0
for inp, g in zip(pys, gold):
    r = quote(inp, B, MG)
    if (r is None) != (g is None):
        bad += 1; print("none mismatch", inp.sel); continue
    if r is None: continue
    pl = [[l.key, l.name, None if l.qty is None else float(l.qty), l.unit_price, l.amount, l.state, l.price_basis, l.calc, l.source] for l in r.lines]
    got = {"lines": pl, "supply": r.subtotal, "vat": r.vat, "total": r.total, "man_days": float(r.man_days), "steps": [[s.key, s.half_days] for s in r.steps], "days": float(r.days), "notes": r.assumptions, "extra": r.extra_amount}
    for k in got:
        if got[k] != g[k]:
            bad += 1
            if bad <= 6: print("DIFF", k, "\n py", got[k], "\n js", g[k])
            break
print("cases", len(pys), "mismatches", bad, "none", sum(g is None for g in gold))
