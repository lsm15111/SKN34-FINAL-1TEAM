"""DB 없이 /mvp API 흐름 점검: 로그인 · 프로젝트 읽기만 바꿔 끼운다 (커밋 안 함)."""
import uuid
from types import SimpleNamespace as N
from decimal import Decimal as D
from fastapi.testclient import TestClient
from app.main import app
from app.auth.deps import current_user
from app.db import get_session
from app.project import service as ps
from app.shared.errors import AppError

ME = N(id=uuid.uuid4(), role="customer")
PID = uuid.uuid4()
def proj(**over):
    p = dict(id=PID, rev=1, occupied=True, balcony_ext=True, size=N(band="30", m2=None, basis=None),
             trades=N(dobae=N(grade="basic"), mokgong=N(items=["molding", "base"])))
    p.update(over); return N(**p)
PROJ = proj()
async def get_for(s, user, project_id):
    if project_id != PID: raise AppError(404, "not_found", "프로젝트를 찾을 수 없어요.")
    return PROJ
ps.get_for = get_for
async def no_session(): yield None
app.dependency_overrides[get_session] = no_session
c = TestClient(app)
print("no login", c.get("/mvp/plans").status_code)
app.dependency_overrides[current_user] = lambda: ME
print("plans", len(c.get("/mvp/plans").json()))
q = c.get("/mvp/plans/fp04/qty", params={"kinds": ["kitchen"], "expanded": "false"}); print("qty", q.status_code, q.json()["doors"], q.json()["wall_m2"])
print("bad kind", c.get("/mvp/plans/fp04/qty", params={"kinds": ["garage"]}).status_code, "nope", c.get("/mvp/plans/nope/qty").status_code)
m = c.get("/mvp/materials").json(); print("materials", len(m["products"]), len(m["extras"]), sorted(m["grades"]))
H = {"origin": "http://localhost:3000"}
r = c.post(f"/mvp/projects/{PID}/preview", json={}); pv = r.json(); print("preview", r.status_code, [(t["trade"], t["total"], t["market"]["lo"], t["market"]["hi"]) for t in pv["trades"]], pv["total"])
from app.calc import dobae as team
from app.refprice.book import DOBAE_2026H2
from app.calc.standard_quote import house_area
from app.refprice.house import HOUSE_2026H2
a, b = house_area("30", None, None, HOUSE_2026H2)
t = team.quote(team.DobaeInput(a, b, "basic", True, True, True), DOBAE_2026H2); print("team dobae total", t.total, "== preview", pv["trades"][1]["total"])
choice = {"plan_id": "fp04", "grade": "premium", "mok": {"door": {"mode": "replace", "pick": "door-yerim-sound-set"}, "molding_type": "minus", "molding": "molding-youngrim-minus", "base": "molding-youngrim-baseboard801", "extras": {"flatten_overlay": True, "coffer": 1}}}
r = c.post(f"/mvp/projects/{PID}/preview", json=choice); pv = r.json(); print("plan preview", r.status_code)
mok, dob = pv["trades"]; L = {l["key"]: l for l in mok["lines"]}
print(" door qty", L["door"]["qty"], "plan doors", pv["plan_qty"]["doors"], "| molding", L["molding"]["qty"], pv["plan_qty"]["molding_m"], L["molding"]["price_basis"], "| coffer", L["coffer"]["amount"])
print(" dobae grade", dob["grade"], "wall", dob["lines"][0]["qty"], pv["plan_qty"]["wall_m2"], "band n", dob["market"]["n"], "gap", [(g["key"], g["d"]) for g in dob["market"]["gap"]])
r = c.post(f"/mvp/projects/{PID}/preview", json={"mok": {"door": {"mode": "replace", "pick": "door-ace-abs-ad001-plain"}}}); print("wrong pick", r.status_code, r.json()["error"])
print("neg qty", c.post(f"/mvp/projects/{PID}/preview", json={"mok": {"extras": {"coffer": -1}}}).status_code, "plan nope", c.post(f"/mvp/projects/{PID}/preview", json={"plan_id": "nope"}).status_code, "other project", c.post(f"/mvp/projects/{uuid.uuid4()}/preview", json={}).status_code)
PROJ = proj(trades=N(dobae=None, mokgong=N(items=["molding"])), size=N(band=None, m2=D("84.9"), basis="exclusive"))
r = c.post(f"/mvp/projects/{PID}/preview", json={}); print("exclusive, mokgong only", r.status_code, r.json()["area_basis"], [t["trade"] for t in r.json()["trades"]], r.json()["trades"][0]["lines"][0]["calc"])
