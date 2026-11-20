"""v2 API: 예시 평면도 · 목공 자재 · 견적 미리 보기. 미리 보기는 저장하지 않는다."""

from app.calc import dobae
from app.calc.space_share import SPACE_SHARE_2026_11
from app.project.schemas import ProjectOut
from app.quote.service import home_v3
from app.refprice.book import DOBAE_2026H2
from app.refprice.house import HOUSE_2026H2
from app.refprice.wallpaper_market import paper_market
from tests.conftest import query
from tests.helpers import signup
from tests.test_project import body


def _project(api, **over) -> str:
    signup(api)
    r = api.post("/projects", json=body(**over))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_reads_need_login(api):
    assert api.get("/v2/floor-plans").status_code == 401
    assert api.get("/v2/materials").status_code == 401


def test_plans_and_plan_qty(api):
    signup(api)
    plans = api.get("/v2/floor-plans").json()
    assert len(plans) == 20
    areas = [float(p["supply_m2"]) for p in plans]
    assert areas == sorted(areas)
    q = api.get("/v2/floor-plans/fp04/qty").json()
    assert q["expanded"] is True and q["doors"] > 0 and float(q["paper_m2"]) > 0
    # 도면 치수(벽 가운데 기준)는 안쪽 길이보다 길다
    sp = q["spaces"][0]
    assert float(sp["plan_w_m"]) > float(sp["w_m"]) and float(sp["plan_d_m"]) > 0
    narrow = api.get("/v2/floor-plans/fp04/qty", params={"kinds": ["kitchen"], "expanded": "false"})
    assert narrow.status_code == 200 and narrow.json()["doors"] == 0
    assert float(narrow.json()["wall_m2"]) < float(q["wall_m2"])
    assert api.get("/v2/floor-plans/nope/qty").status_code == 404
    assert api.get("/v2/floor-plans/fp04/qty", params={"kinds": ["garage"]}).status_code == 422


def test_materials(api):
    signup(api)
    m = api.get("/v2/materials").json()
    assert len(m["products"]) == 17 and len(m["extras"]) == 18
    # 천장 몰딩 · 걸레받이는 자주 쓰는 3가지씩만
    kinds = [p["kind"] for p in m["products"]]
    assert kinds.count("molding") == 3 and kinds.count("base") == 3
    assert set(m["grades"]) == {"economy", "basic", "premium"}


def test_preview_without_plan_matches_standard_dobae(api):
    pid = _project(api)
    r = api.post(f"/v2/projects/{pid}/preview", json={})
    assert r.status_code == 200, r.text
    pv = r.json()
    assert [t["trade"] for t in pv["trades"]] == ["mokgong", "dobae"]
    # 도면이 없으면 도배는 옛 판(2026H2, 면적 × 2.5)으로 센 v3 표준견적서와 같은 금액. v3 표준견적서는
    # 도배지 줄만 벽지 평 × 시장 평균(리드 결정)이라 그 줄을 뺀 공급가가 같다.
    # 지금 표준견적서는 목공에 몰딩 교체가 있어 리모델링 기준(판 2026.11-remodel, ADR 0004)이라
    # 퍼티 · 부자재 · 식대 · 운송비 줄이 더해져 v2 미리보기보다 크다
    pv_d = pv["trades"][1]
    p = ProjectOut.model_validate(api.get(f"/projects/{pid}").json())
    h = home_v3(p)
    old = dobae.standard_v3(
        h, DOBAE_2026H2, paper_market(h.grade), SPACE_SHARE_2026_11, HOUSE_2026H2
    ).quote
    old_paper = next(ln.amount for ln in old.lines if ln.key == "paper")
    paper = next(ln["amount"] for ln in pv_d["lines"] if ln["key"] == "paper")
    assert pv_d["supply"] - paper == old.subtotal - old_paper
    st = api.get(f"/projects/{pid}/standard").json()
    vers = {
        r["trade"]: r["price_ver"] for r in query("select trade, price_ver from standard_quotes")
    }
    assert pv_d["version"] == "2026H2" and vers == {"mokgong": "2026H2", "dobae": "2026.11-remodel"}
    assert st["trades"][1]["supply"] > old.subtotal
    mok = pv["trades"][0]
    assert {ln["key"] for ln in mok["lines"]} >= {"molding", "molding_mat", "base", "base_mat"}
    assert mok["market"]["lo"] <= mok["market"]["hi"]
    assert pv["total"] == sum(t["total"] for t in pv["trades"])
    assert pv["grade"] == "basic" and pv["plan"] is None
    # 미리 보기는 저장하지 않는다 (표준견적서 저장본만 있음)
    assert len(query("select 1 from standard_quotes")) == 2


def test_preview_with_plan_and_choices(api):
    pid = _project(api)
    choice = {
        "plan_id": "fp04",
        "grade": "premium",
        "mok": {
            "door": {"mode": "replace", "pick": "door-yerim-sound-set"},
            "molding_type": "minus",
            "molding": "molding-youngrim-minus",
            "base": "molding-youngrim-baseboard801",
            "extras": {"flatten_overlay": True, "coffer": 1},
        },
    }
    r = api.post(f"/v2/projects/{pid}/preview", json=choice)
    assert r.status_code == 200, r.text
    pv = r.json()
    assert pv["plan"]["id"] == "fp04" and pv["area_basis"] == "supply"
    mok, dob = pv["trades"]
    lines = {ln["key"]: ln for ln in mok["lines"]}
    # 방문 수 · 몰딩 길이는 도면에서
    assert lines["door"]["qty"] == f"{pv['plan_qty']['doors']}"
    assert lines["molding"]["qty"] == pv["plan_qty"]["molding_m"]
    assert lines["molding"]["price_basis"] == "assumed"  # 무몰딩 배수는 팀 가정값
    assert lines["coffer"]["amount"] == 700_000
    assert dob["grade"] == "basic"  # 프리미엄 도배는 실크 단가
    assert dob["lines"][0]["qty"] == pv["plan_qty"]["wall_m2"]
    assert dob["market"]["n"] == 604  # 도면 면적 띠


def test_preview_rejects_bad_choice_and_other_people(api):
    pid = _project(api)
    wrong = {"mok": {"door": {"mode": "replace", "pick": "door-ace-abs-ad001-plain"}}}
    r = api.post(f"/v2/projects/{pid}/preview", json=wrong)
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid"
    neg = {"mok": {"extras": {"coffer": -1}}}
    assert api.post(f"/v2/projects/{pid}/preview", json=neg).status_code == 422
    assert api.post(f"/v2/projects/{pid}/preview", json={"plan_id": "nope"}).status_code == 404
    signup(api, "other@mitjip.test")
    assert api.post(f"/v2/projects/{pid}/preview", json={}).status_code == 404
