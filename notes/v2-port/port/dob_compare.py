import dataclasses, io, itertools, json, subprocess, sys
from decimal import Decimal as D
from app.calc import dobae as team
from app.calc.mvp_dobae import MvpDobaeInput, paper_grade, quote
from app.calc.plan_qty import Plan, from_plan
from app.refprice.book import DOBAE_2026H2 as P
HERE = sys.argv[1]
EMPTY = from_plan(Plan(spaces=()))
plans = [None, (D("72.0"), D("36.8")), (D("141.3"), D("80.5"))]
cases, pys = [], []
for ar, basis, g, ceil, occ, bal, pl in itertools.product([D("59.5"), D("84.9"), D("109.1"), D("33.1")], ["supply", "exclusive"], ["economy", "basic", "premium"], [True, False], [True, False], [True, False], plans):
    pq = dataclasses.replace(EMPTY, wall_m2=pl[0], ceiling_m2=pl[1]) if pl else None
    inp = MvpDobaeInput(area_m2=ar, grade=g, area_basis=basis, include_ceiling=ceil, occupied=occ, balcony_ext=bal, plan=pq, plan_name="시험" if pl else "")
    pys.append(inp)
    cases.append({"area_m2": float(ar), "area_basis": basis, "grade": paper_grade(g), "include_ceiling": ceil, "occupied": occ, "balcony_ext": bal, "measured": {"name": "시험", "wall_m2": float(pl[0]), "ceiling_m2": float(pl[1])} if pl else None})
io.open(f"{HERE}/dob_cases.json", "w", encoding="utf-8").write(json.dumps(cases, ensure_ascii=False))
subprocess.run(["node", "dob_golden.js", "dob_cases.json", "dob_golden.json"], cwd=HERE, check=True)
gold = json.load(io.open(f"{HERE}/dob_golden.json", encoding="utf-8"))
bad = team_bad = 0
for inp, g in zip(pys, gold):
    r = quote(inp, P)
    pl = [[l.key, l.name, None if l.qty is None else float(l.qty), l.unit_price, l.amount, l.state, l.price_basis, "" if l.key == "removal" else l.calc, l.source] for l in r.lines]
    for x in g["lines"]:
        if x[0] == "removal": x[7] = ""
    got = {"lines": pl, "supply": r.subtotal, "vat": r.vat, "total": r.total, "man_days": float(r.man_days), "steps": [[s.key, s.name, s.half_days] for s in r.steps], "days": float(r.days), "notes": r.assumptions}
    for k in got:
        if got[k] != g[k]:
            bad += 1
            if bad <= 4: print("DIFF", k, "\n py", got[k], "\n js", g[k])
            break
    if inp.plan is None and inp.grade != "premium":
        t = team.quote(team.DobaeInput(inp.area_m2, inp.area_basis, inp.grade, inp.include_ceiling, inp.occupied, inp.balcony_ext), P)
        if [(l.key, l.qty, l.amount, l.state) for l in t.lines] != [(l.key, l.qty, l.amount, l.state) for l in r.lines] or (t.total, t.man_days, t.days) != (r.total, r.man_days, r.days):
            team_bad += 1
print("cases", len(pys), "js mismatches", bad, "team mismatches", team_bad)
