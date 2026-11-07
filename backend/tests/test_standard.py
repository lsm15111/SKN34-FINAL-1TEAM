"""표준견적서: 처음 볼 때 계산해 저장하고, 집 정보를 고치면 새 버전을 쌓는다."""

from tests.conftest import query
from tests.helpers import signup, vendor_signup
from tests.test_project import body


def test_standard_is_saved_once_and_counts_only_included(api):
    signup(api)
    p = api.post(
        "/projects",
        json=body(size={"basis": "supply", "m2": "105.8"}, occupied=False, balcony_ext=False),
    ).json()
    r = api.get(f"/projects/{p['id']}/standard")
    assert r.status_code == 200, r.text
    st = r.json()
    assert [t["trade"] for t in st["trades"]] == ["mokgong", "dobae"]
    dobae = st["trades"][1]
    assert dobae["supply"] == 2_677_869 and dobae["total"] == 2_945_656  # 시안 예시 집 · r2 단가
    assert dobae["man_day"] == "6.0"
    counted = sum(ln["amount"] for ln in dobae["lines"] if ln["state"] in ("included", "separate"))
    assert counted == dobae["supply"]
    assert st["total"] == sum(t["total"] for t in st["trades"]) == st["supply"] + st["vat"]
    assert st["code"] == p["code"] and st["pyeong"] == "32.0"
    assert st["budget"] == {"band": "500-700", "status": "within", "over_by": None}

    again = api.get(f"/projects/{p['id']}/standard").json()
    assert again["trades"][1]["version"] == 1
    assert len(query("select 1 from standard_quotes")) == 2


def test_edit_makes_a_new_version(api):
    signup(api)
    p = api.post("/projects", json=body()).json()
    first = api.get(f"/projects/{p['id']}/standard").json()
    edited = body(trades={"dobae": {"spaces": ["a"], "grade": "economy"}})
    assert api.patch(f"/projects/{p['id']}", json=edited).status_code == 200
    st = api.get(f"/projects/{p['id']}/standard").json()
    assert [t["trade"] for t in st["trades"]] == ["dobae"]
    assert st["trades"][0]["version"] == 2 and st["trades"][0]["grade"] == "economy"
    assert st["total"] < first["total"]
    assert st["project_rev"] == 2


def test_only_owner_sees_the_standard(api):
    signup(api)
    p = api.post("/projects", json=body()).json()
    signup(api, "other@mitjip.test")
    assert api.get(f"/projects/{p['id']}/standard").status_code == 404
    assert vendor_signup(api).status_code == 201
    assert api.get(f"/projects/{p['id']}/standard").status_code == 404
