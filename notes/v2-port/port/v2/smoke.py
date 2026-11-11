import uuid, json
from types import SimpleNamespace as N
from fastapi.testclient import TestClient
from app.main import app
from app.auth.deps import current_user
c = TestClient(app)
print("no login", c.post("/mvp/v2/quote", json={}).status_code)
app.dependency_overrides[current_user] = lambda: N(id=uuid.uuid4(), role="customer")
q = {"pyeong": 32, "living": "living", "cats": ["wallpaper","carpentry","floor","paint","window","bath"], "picks": {}, "plan": None, "balcony": False, "mok": None, "tier": "basic"}
r = c.post("/mvp/v2/quote", json=q); print("quote", r.status_code); j = r.json()
if r.status_code != 200: print(j); raise SystemExit
print(j["code"], j["total"], j["band"], [ (t["trade"], t["total"], t["band"]["lo"], t["gap"]["to"]) for t in j["precise"]], [(t["cat"], t["lo"], t["hi"]) for t in j["ref"]], j["inp"])
q2 = dict(q, plan={"id": "fp04", "expanded": True, "kinds": ["living","room"], "spaces": ["room"]}, mok={"door": {"mode": "replace", "pick": "door-yerim-sound-set", "count": None}, "slide": {"n": 1, "pick": "door-yerim-hidden-sliding-set"}, "hidden": {"n": 0, "pick": None}, "molding": {"type": "minus", "pick": "molding-youngrim-minus"}, "base": {"pick": "molding-dc-hidden-baseboard"}, "extras": {"flatten_overlay": True, "coffer": 2, "hatch": True}})
r = c.post("/mvp/v2/quote", json=q2); print("quote plan", r.status_code, r.json()["inp"] if r.status_code == 200 else r.json())
p = c.post("/mvp/v2/plan", json={"quote": q, "move": "2026-12", "cons": {"weekendWork": False, "endBy": "", "startAfter": "", "avoid": []}, "props": {"mokgong": {"start": "2026-11-20", "end": "2026-11-24", "crew": 3}}, "accepted": {}, "trial": {"trade": "mokgong", "start": "2026-11-20", "end": "2026-11-24"}})
pj = p.json(); print("plan", p.status_code, pj.get("start"), pj.get("end"), pj.get("warn"), pj.get("trial"), len(pj.get("weeks", [])))
for kind in ["dobae", "mokgong"]:
    r = c.post("/mvp/v2/check", json={"quote": q, "trade": kind, "amount": 2500000, "mode": "included", "scope": {"removal": True, "casing9": True, "extras": {"aircon": 2}}}); print("check", kind, r.status_code, r.json())
print("check warn", c.post("/mvp/v2/check", json={"quote": q, "trade": "dobae", "amount": 0}).json())
print("calc7", c.post("/mvp/v2/calc7", json={"kind": "wallpaper", "w": 3.6, "d": 3, "hgt": 2.3, "doors": 1, "windows": 1, "ceiling": True, "rollW": 1.06, "rollLen": 15.6, "repeat": 0, "loss": 10}).json(),
      c.post("/mvp/v2/calc7", json={"kind": "trim", "w": 3.6, "d": 3, "doors": 1, "pieceLen": 2.4, "loss": 10}).json(), c.post("/mvp/v2/calc7", json={"kind": "paint", "w": 3.6, "d": 3, "hgt": 2.3, "doors": 1, "windows": 1, "ceiling": False, "coats": 2, "cover": 10}).json())
print("extras", c.post("/mvp/v2/extras-range", json={"picks": {"aircon": 2}, "casing": {"doors": 4, "with_door": True}}).json())
print("mx", len(c.get("/mvp/v2/market-extras").json()))
t = j["precise"][1]
print("estimate", c.post("/mvp/v2/estimate", json={"trade": "dobae", "grade": "basic", "lines": [{k: l[k] for k in ("key","name","qty","state")} for l in t["lines"]], "prices": {"wall": 5000, "ceiling": 7000, "paper_basic": 3000, "primer": 200, "occupied": 0}, "std_total": t["total"]}).json())
print("estimate miss", c.post("/mvp/v2/estimate", json={"trade": "dobae", "lines": [{k: l[k] for k in ("key","name","qty","state")} for l in t["lines"]], "prices": {}, "std_total": t["total"]}).json())
print("entered", c.post("/mvp/v2/entered", json={"amount": 3300000, "mode": "included", "std_total": 3000000}).json())
print("llm", c.post("/mvp/v2/llm", json={"system": "x", "messages": [{"role": "user", "content": [{"type": "text", "text": "hi"}, {"type": "image", "data": "AAAA"}]}], "tools": [{"name": "f", "description": "d", "parameters": {"type": "object"}}]}).json(), c.get("/mvp/v2/llm/health").json())
print("llm too many", c.post("/mvp/v2/llm", json={"messages": [{"role": "user", "content": "a"}] * 31}).status_code, "sys", c.post("/mvp/v2/llm", json={"system": "a" * 60001, "messages": [{"role": "user", "content": "a"}]}).status_code)
print("plans", c.get("/mvp/plans").json()[0]["sup_note"], c.get("/mvp/plans/fp04/qty", params={"ceiling": "false"}).json()["est"], c.get("/mvp/plans/fp04/qty", params={"ceiling": "false"}).json()["ceiling_m2"])
m = c.get("/mvp/materials").json(); print("mats", m["fixed"], [p["per"] for p in m["products"]][:3])
