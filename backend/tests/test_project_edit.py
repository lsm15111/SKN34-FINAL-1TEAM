"""요청 번호 · 집 정보 고치기 · 실측 요청 뒤 잠금."""

import re

from app.shared.clock import today_seoul
from tests.conftest import query
from tests.helpers import signup, upload, use, vendor_signup
from tests.test_project import body


def test_code_is_given_and_unique(api):
    signup(api)
    a = api.post("/projects", json=body()).json()
    b = api.post("/projects", json=body()).json()
    assert re.fullmatch(rf"MJ-{today_seoul():%y%m}-\d{{4}}", a["code"])
    assert a["code"] != b["code"] and a["rev"] == 1 and a["locked"] is False
    assert {x["code"] for x in api.get("/projects").json()} == {a["code"], b["code"]}


def test_edit_replaces_parts_and_bumps_rev(api):
    signup(api)
    photo = upload(api).json()["id"]
    p = api.post("/projects", json=body([photo])).json()
    edited = body(
        [photo],  # 이 프로젝트에 붙은 사진은 다시 써도 된다
        trades={"dobae": {"spaces": ["a"], "grade": "economy"}},
        spaces=[{"key": "a", "name": "거실"}],
    )
    r = api.patch(f"/projects/{p['id']}", json=edited)
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["rev"] == 2 and got["code"] == p["code"]
    assert got["trades"]["dobae"]["grade"] == "economy" and got["trades"]["mokgong"] is None
    assert [s["name"] for s in got["spaces"]] == ["거실"]
    assert got["photos"][0]["file_id"] == photo


def test_cannot_edit_after_visit_request_or_someone_elses(api):
    owner = signup(api)
    p = api.post("/projects", json=body()).json()
    signup(api, "other@mitjip.test")
    assert api.patch(f"/projects/{p['id']}", json=body()).status_code == 404
    assert vendor_signup(api).status_code == 201
    assert api.patch(f"/projects/{p['id']}", json=body()).status_code == 403

    use(api, owner)
    query("update projects set locked_at = now() where id = $1", p["id"])
    r = api.patch(f"/projects/{p['id']}", json=body())
    assert r.status_code == 409 and r.json()["error"]["code"] == "locked"
    assert api.get(f"/projects/{p['id']}").json()["locked"] is True
