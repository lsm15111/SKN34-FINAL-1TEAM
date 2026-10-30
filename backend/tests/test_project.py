from datetime import date, timedelta

from tests.conftest import query
from tests.helpers import PDF, make_admin, signup, upload, use, vendor_signup

# 오늘 기준 한 달 뒤 (2년 넘는 날짜는 받지 않는다)
SOON = (date.today() + timedelta(days=30)).isoformat()
SOON_END = (date.today() + timedelta(days=34)).isoformat()


def body(photo_ids=(), plan_ids=(), **over) -> dict:
    b = {
        "sido": "seoul",
        "sgg": "마포구",
        "built_year": 2009,
        "size": {"band": "30"},
        "balcony_ext": True,
        "when": {"kind": "date", "start": SOON, "end": SOON_END},
        "occupied": True,
        "budget": "500-700",
        "spaces": [
            {"key": "a", "name": "거실"},
            {"key": "b", "name": "방"},
            {"key": "c", "name": "방 2"},
        ],
        "trades": {
            "dobae": {"spaces": ["a", "b", "c"], "grade": "basic"},
            "mokgong": {"spaces": ["a"], "items": ["molding", "base"]},
        },
        "photos": [{"space": "a", "file_id": i} for i in photo_ids],
        "plans": list(plan_ids),
    }
    b.update(over)
    return b


def test_create_and_read_a_project(api):
    signup(api)
    photo = upload(api).json()["id"]
    plan = upload(api, kind="plan", content=PDF, name="도면.pdf").json()["id"]
    r = api.post("/projects", json=body([photo], [plan]))
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["region"] == "서울 마포구" and p["size"]["band"] == "30"
    assert [s["name"] for s in p["spaces"]] == ["거실", "방", "방 2"]
    assert len(p["trades"]["dobae"]["spaces"]) == 3 and p["trades"]["mokgong"]["items"] == [
        "molding",
        "base",
    ]
    assert p["trades"]["dobae"]["grade"] == "basic"
    assert p["photos"][0]["file_id"] == photo and p["plans"] == [plan]
    assert api.get(f"/projects/{p['id']}").json() == p
    assert [x["id"] for x in api.get("/projects").json()] == [p["id"]]
    (row,) = query("select size_band, area_m2, start_kind from projects")
    assert row["size_band"] == "30" and row["area_m2"] is None and row["start_kind"] == "date"


def test_dobae_needs_a_grade(api):
    signup(api)
    spaces = {"spaces": ["a"]}
    assert api.post("/projects", json=body(trades={"dobae": spaces})).status_code == 422
    odd = api.post("/projects", json=body(trades={"dobae": {**spaces, "grade": "premium"}}))
    assert odd.status_code == 422
    ok = api.post("/projects", json=body(trades={"dobae": {**spaces, "grade": "economy"}}))
    assert ok.status_code == 201 and ok.json()["trades"]["dobae"]["grade"] == "economy"
    (row,) = query("select grade from project_trades where trade = 'dobae'")
    assert row["grade"] == "economy"


def test_exact_area_instead_of_band(api):
    signup(api)
    r = api.post("/projects", json=body(size={"basis": "exclusive", "m2": "84.9"}))
    assert r.status_code == 201 and r.json()["size"] == {
        "band": None,
        "basis": "exclusive",
        "m2": "84.9",
    }
    both = api.post("/projects", json=body(size={"band": "30", "basis": "supply", "m2": "84.9"}))
    assert both.status_code == 422


def test_checks_region_dates_and_references(api):
    signup(api)
    assert api.post("/projects", json=body(sgg="없는구")).json()["error"]["code"] == "region"
    past = api.post("/projects", json=body(when={"kind": "date", "start": "2000-01-01"}))
    assert past.json()["error"]["code"] == "past_date"
    backwards = api.post(
        "/projects", json=body(when={"kind": "date", "start": SOON_END, "end": SOON})
    )
    assert backwards.status_code == 422
    ghost = api.post(
        "/projects", json=body(trades={"dobae": {"spaces": ["zzz"], "grade": "basic"}})
    )
    assert ghost.status_code == 422
    none = api.post("/projects", json=body(trades={}))
    assert none.status_code == 422
    dup = api.post(
        "/projects", json=body(spaces=[{"key": "a", "name": "방"}, {"key": "b", "name": "방"}])
    )
    assert dup.status_code == 422


def test_files_must_be_mine_and_unused(api):
    other = signup(api, "other@mitjip.test")
    theirs = upload(api).json()["id"]
    signup(api, "me@mitjip.test")
    assert api.post("/projects", json=body([theirs])).json()["error"]["code"] == "file"
    mine = upload(api).json()["id"]
    assert api.post("/projects", json=body([mine])).status_code == 201
    assert api.post("/projects", json=body([mine])).json()["error"]["code"] == "file_used"
    plan_as_photo = upload(api, kind="plan", content=PDF).json()["id"]
    assert api.post("/projects", json=body([plan_as_photo])).json()["error"]["code"] == "file"
    assert other


def test_who_can_create_and_see(api):
    owner = signup(api, "owner@mitjip.test")
    pid = api.post("/projects", json=body()).json()["id"]
    signup(api, "someone@mitjip.test")
    assert api.get(f"/projects/{pid}").status_code == 404
    vendor_signup(api)
    assert api.post("/projects", json=body()).status_code == 403
    make_admin(api)
    assert api.get(f"/projects/{pid}").status_code == 200
    use(api, owner)
    assert api.get(f"/projects/{pid}").status_code == 200


def test_regions_endpoint(api):
    regions = api.get("/regions").json()
    assert len(regions) == 16 and sum(len(g["items"]) for r in regions for g in r["groups"]) == 230
