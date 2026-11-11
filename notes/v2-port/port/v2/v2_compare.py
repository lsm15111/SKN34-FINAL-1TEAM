"""v2 API(서비스 함수)와 v10 JS 대조. backend 폴더에서: PYTHONPATH=. uv run python <이 파일> <이 폴더>"""
import io, json, random, subprocess, sys
from datetime import date
from app.mvp import v2_schemas as v2, v2_service as sv
from app.refprice.v2_ref import materials
from app.refprice.mvp_plans import plans
from app.refprice.mvp_materials import MOK_2026_11 as B

HERE = sys.argv[1]; TODAY = date(2026, 11, 11)
N = int(sys.argv[2]) if len(sys.argv) > 2 else 1
rnd = random.Random(7)
CATS = ["wallpaper", "floor", "tile", "bath", "furniture", "carpentry", "film", "paint", "middoor", "light", "window", "finish"]
PP9 = {"room": ["living", "room", "hall", "dress"], "kitchen": ["kitchen"], "entry": ["entry"], "bath": ["bath"], "window": []}
mats = list(materials().values()); pids = sorted(plans())
prods = B.products


def pick_of(kind, typ=None):
    return rnd.choice([k for k, p in prods.items() if p.kind == kind and (typ is None or p.type == typ)])


def rand_mok():
    if rnd.random() < 0.25:
        return None
    mode = rnd.choice(["none", "replace", "overlay", "leaf", "replace"])
    dk = {"replace": "door_set", "overlay": "door_leaf", "leaf": "door_leaf"}.get(mode)
    mt = rnd.choice(["none", "flat", "step", "minus"])
    ex = {}
    for x in B.extras:
        r = rnd.random()
        if r < 0.12:
            ex[x.key] = True
        elif r < 0.2:
            ex[x.key] = rnd.choice([1, 2, 3.5, 0])
    return {"door": {"mode": mode, "pick": pick_of(dk) if dk and rnd.random() < 0.9 else None, "count": rnd.choice([None, None, 0, 2, 4])},
            "slide": {"n": rnd.choice([0, 0, 1]), "pick": "door-yerim-hidden-sliding-set"}, "hidden": {"n": rnd.choice([0, 0, 2]), "pick": "door-yerim-hidden-set"},
            "molding": {"type": mt, "pick": pick_of("molding", mt) if mt != "none" else None}, "base": {"pick": rnd.choice([None, pick_of("base"), pick_of("base")])}, "extras": ex}


def rand_quote():
    k = rnd.random()
    cats = CATS if k < 0.3 else [c for c in CATS if rnd.random() < 0.5] or ["wallpaper"]
    if k > 0.85:
        cats = rnd.choice([["wallpaper"], ["carpentry"], ["wallpaper", "carpentry"], ["paint"], ["paint", "floor"]])
    cats = [c for c in CATS if c in cats]
    picks = {}
    for c in rnd.sample(CATS, len(CATS)):
        if rnd.random() < 0.5:
            ms = [m for m in mats if m.cat == c]
            if ms:
                picks[c] = rnd.choice(ms).id
    plan = None
    if rnd.random() < 0.4:
        sp = rnd.choice([None, None, ["room"], ["kitchen", "bath"], ["room", "entry"], ["window"]])
        kinds = list(dict.fromkeys(x for s in sp for x in PP9[s])) if sp else None
        plan = {"id": rnd.choice(pids), "expanded": rnd.random() < 0.7, "kinds": kinds, "spaces": sp}
    return {"pyeong": rnd.choice([None, 18, 24, 25.5, 27, 28, 32, 34, 37.5, 41, 55]), "living": rnd.choice(["living", "vacant", None]), "cats": cats, "picks": picks,
            "plan": plan, "balcony": rnd.random() < 0.3, "mok": rand_mok(), "tier": rnd.choice(["economy", "basic", "premium"])}


def day(off):
    return date.fromordinal(TODAY.toordinal() + off).isoformat()


cases = []
for _ in range(700 * N):
    cases.append({"fn": "quoteOf", "in": rand_quote()})
for _ in range(400 * N):
    q = rand_quote(); tr = rnd.choice(["mokgong", "dobae", "floor", "paint", "window"])
    props = {}
    for t in rnd.sample(["mokgong", "dobae", "floor", "paint", "window", "bath"], rnd.randint(0, 2)):
        s = rnd.randint(2, 40); props[t] = {"start": day(s), "end": day(s + rnd.randint(0, 6)), "crew": rnd.choice([1, 2, 3])}
    acc = {}
    for t in rnd.sample(["mokgong", "dobae", "floor", "tile"], rnd.randint(0, 2)):
        s = rnd.randint(2, 40); acc[t] = {"start": day(s), "end": day(s + rnd.randint(0, 4))}
    cons = {"weekendWork": rnd.random() < 0.3, "endBy": rnd.choice(["", "", day(rnd.randint(10, 70))]), "startAfter": rnd.choice(["", "", "", day(rnd.randint(-3, 30))]),
            "avoid": [day(rnd.randint(1, 40)) for _ in range(rnd.randint(0, 3))]}
    ts = rnd.randint(-2, 40)
    trial = rnd.choice([None, {"trade": tr, "start": day(ts), "end": day(ts + rnd.randint(-2, 9))}])
    cases.append({"fn": "planOf", "in": {"quote": q, "move": rnd.choice(["", "", "2026-12", "2027-01-15", "2026-11-20"]), "cons": cons, "props": props, "accepted": acc, "trial": trial}})
for _ in range(400 * N):
    q = rand_quote(); q["cats"] = [c for c in CATS if c in set(q["cats"]) | {"wallpaper", "carpentry"}]
    sc = {"ceiling": rnd.random() < 0.7, "removal": rnd.random() < 0.4, "moving": rnd.random() < 0.3, "casing9": rnd.random() < 0.4, "etc": rnd.random() < 0.1,
          "extras": {e: rnd.choice([1, 2, 5, 12]) for e in rnd.sample(["jungmun", "aircon", "wall", "insul", "artwall", "lightbox"], rnd.randint(0, 3))}}
    cases.append({"fn": "checkOf", "in": {"quote": q, "trade": rnd.choice(["dobae", "mokgong"]), "amount": rnd.choice([0, 800000, 1500000, 2500000.4, 3300000, 6000000, 12000000]),
                                          "mode": rnd.choice(["unknown", "excluded", "included"]), "scope": sc}})
for _ in range(300 * N):
    kind = rnd.choice(["wallpaper", "trim", "paint"])
    base = {"w": round(rnd.uniform(1, 7), 1), "d": round(rnd.uniform(1, 6), 1)}
    if kind == "wallpaper":
        base.update(hgt=rnd.choice([2.3, 2.4, 2.6]), doors=rnd.randint(0, 3), windows=rnd.randint(0, 3), ceiling=rnd.random() < .5, rollW=rnd.choice([0.53, 1.06]),
                    rollLen=rnd.choice([12.5, 15.6]), repeat=rnd.choice([0, 32, 64]), loss=rnd.choice([0, 10, 15]))
    elif kind == "trim":
        base.update(doors=rnd.randint(0, 3), pieceLen=rnd.choice([2.4, 2.44, 3.0]), loss=rnd.choice([0, 10]))
    else:
        base.update(hgt=rnd.choice([2.3, 2.4]), doors=rnd.randint(0, 3), windows=rnd.randint(0, 3), ceiling=rnd.random() < .5, coats=rnd.choice([1, 2, 3]), cover=rnd.choice([8, 10, 12.5]))
    cases.append({"fn": "calc7Of", "in": {"kind": kind, **base}})
for _ in range(100 * N):
    cases.append({"fn": "enteredOf", "in": {"amount": rnd.randint(0, 9_000_000), "mode": rnd.choice(["excluded", "included", "exempt"]), "std_total": rnd.choice([None, 0, 3_000_000, 4_567_891])}})


def diff(js, py, path, out):
    if isinstance(js, dict):
        if not isinstance(py, dict):
            out.append((path, js, py)); return
        for k, v in js.items():
            if k not in py:
                if v is not None:
                    out.append((path + "." + k, v, "<없음>"))
                continue
            diff(v, py[k], path + "." + k, out)
    elif isinstance(js, list):
        if not isinstance(py, list) or len(js) != len(py):
            out.append((path, js, py)); return
        for i, (a, b) in enumerate(zip(js, py)):
            diff(a, b, f"{path}[{i}]", out)
    elif isinstance(js, (int, float)) and not isinstance(js, bool) and isinstance(py, (int, float)) and not isinstance(py, bool):
        if abs(js - py) > 1e-9 * max(1, abs(js)):
            out.append((path, js, py))
    elif js != py:
        out.append((path, js, py))


def run(cases, tag):
    io.open(f"{HERE}/{tag}_cases.json", "w", encoding="utf-8").write(json.dumps(cases, ensure_ascii=False))
    subprocess.run(["node", "v2_golden.js", f"{tag}_cases.json", f"{tag}_golden.json"], cwd=HERE, check=True)
    gold = json.load(io.open(f"{HERE}/{tag}_golden.json", encoding="utf-8"))
    stats = {}; shown = 0; extra = []
    for c, g in zip(cases, gold):
        fn = c["fn"]; st = stats.setdefault(fn, [0, 0, 0])
        st[0] += 1
        try:
            if fn == "quoteOf": py = sv.quote(v2.MvpV2QuoteIn(**c["in"]), TODAY)
            elif fn == "planOf": py = sv.plan(v2.MvpV2PlanIn(**c["in"]), TODAY)
            elif fn == "checkOf": py = sv.check(v2.MvpV2CheckIn(**c["in"]), TODAY)
            elif fn == "calc7Of": py = sv.calc7(v2.MvpV2Calc7In(**c["in"]))
            elif fn == "estOf": py = sv.estimate(v2.MvpV2EstimateIn(**c["in"]))
            else: py = sv.entered(v2.MvpV2EnteredIn(**c["in"]))
            py = json.loads(py.model_dump_json(by_alias=True)); perr = None
        except Exception as e:
            py = None; perr = f"{type(e).__name__}: {getattr(e, 'message', e)}"
        js = g.get("ok")
        if fn == "checkOf" and js and js.get("none"):
            js = None; g = {"err": "trade 없음"}
        if "err" in g or perr:
            if "err" in g and perr:
                st[2] += 1; continue
            st[1] += 1
            if shown < 15:
                shown += 1; print("ERR", fn, "js:", str(g.get("err", ""))[:200], "| py:", perr, json.dumps(c["in"], ensure_ascii=False)[:300])
            continue
        if fn == "checkOf" and js.get("warn") == "etc":
            js["warn"] = py["warn"]
        if fn == "quoteOf":
            extra.extend(py["precise"])
        out = []; diff(js, py, fn, out)
        if out:
            st[1] += 1
            if shown < 40 and (fn != "quoteOf" or "measured" not in str(out) and "lines[" not in str(out[0][0])):
                shown += 1; print("DIFF", fn, [(p, str(a)[:200], str(b)[:200]) for p, a, b in out[:4]], json.dumps(c["in"], ensure_ascii=False)[:500])
    print(tag, {k: f"{v[0]}가지 · 다름 {v[1]} · 둘 다 오류 {v[2]}" for k, v in stats.items()})
    return extra


precise = run(cases, "v2")
# 가견적: 견적 결과의 정밀 공정 줄에 단가를 넣어 본다
est = []
for t in precise[: 300 * N]:
    lines = [{k: ln[k] for k in ("key", "name", "qty", "state")} for ln in t["lines"]]
    prices = {}
    for ln in lines:
        pk = f"paper_{t['grade'] or 'basic'}" if ln["key"] == "paper" else ln["key"]
        if rnd.random() < 0.93:
            prices[pk] = rnd.choice([0, 1200, 3500, 8000, 95000, 180000.5])
    est.append({"fn": "estOf", "in": {"trade": t["trade"], "grade": t["grade"], "lines": lines, "prices": prices, "std_total": t["total"]}})
run(est, "est")
