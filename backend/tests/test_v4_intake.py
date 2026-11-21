"""v4 첫 대화 기본 정보 8개(2026-11-21 사용자 결정) 중 방 개수 · 공사 시작 희망 · 직접 할 일(반셀프 칩).
공사 희망 시기 칩 날짜는 test_v4_start_wish.

- 직접 할 일(반셀프 칩)은 공사를 만들 때 HomeInfoIn.diy로 같은 트랜잭션에 저장한다(None 묻지 않음 · [] 없어요).
  가입 뒤에는 PUT /projects/{id}/diy로 고친다(만든 고객만, 남의 것 404, 업체 403, 모르는 키 422).
- 모은 조건 칩 이름표는 '직접 할 일: 페인트(문틀 · 몰딩)'처럼 화면 말로 보인다."""

import uuid

import asyncpg
import pytest

from tests.conftest import query
from tests.helpers import signup, use
from tests.test_v3_project_home import HOME, create
from tests.test_vendor_profile import approved_vendor

PAINT = "페인트(문틀 · 몰딩)"
CLEAN = "입주 청소"


def diy_rows(pid: str) -> list[tuple[str, str, str]]:
    rows = query(
        "select trade, key, value from project_conditions where project_id = $1::uuid"
        " and key like 'diy.%' order by key",
        pid,
    )
    return [(r["trade"], r["key"], r["value"]) for r in rows]


def chips(api, pid: str) -> list[tuple[str, str]]:
    r = api.get(f"/projects/{pid}/conditions")
    assert r.status_code == 200, r.text
    return [(c["label"], c["value"]) for c in r.json()]


# ---- 공사 만들기 · 고치기의 직접 할 일 ----


def test_create_project_saves_rooms_and_diy_in_one_go(api):
    signup(api)
    r = create(api, {**HOME, "rooms": 3, "diy": ["clean", "paint", "paint"]})
    assert r.status_code == 201, r.text
    p = r.json()
    assert (p["home"]["rooms"], p["home"]["start_date"]) == (3, HOME["start_date"])
    assert diy_rows(p["id"]) == [("diy", "diy.clean", "self"), ("diy", "diy.paint", "self")]
    assert chips(api, p["id"]) == [("직접 할 일", CLEAN), ("직접 할 일", PAINT)]

    none = create(api, {**HOME, "diy": []}).json()  # 없어요
    assert diy_rows(none["id"]) == [("diy", "diy.none", "self")]
    assert chips(api, none["id"]) == [("직접 할 일", "없어요")]
    asked_not = create(api, {**HOME, "start_date": None}).json()  # 안 보내면 묻지 않은 것
    assert diy_rows(asked_not["id"]) == [] and asked_not["home"]["start_date"] is None

    # 손님 답 옮기기(Idempotency-Key)도 같은 칸으로 저장한다
    key = str(uuid.uuid4())
    moved = create(api, {**HOME, "diy": ["light"]}, key)
    assert moved.status_code == 201 and moved.json()["source"] == "guest"
    assert diy_rows(moved.json()["id"]) == [("diy", "diy.light", "self")]
    again = create(api, {**HOME, "diy": ["light"]}, key)
    assert again.status_code == 200 and again.json()["id"] == moved.json()["id"]

    before = query("select count(*) as n from projects")[0]["n"]
    bad = create(api, {**HOME, "diy": ["floor"]})
    assert bad.status_code == 422 and bad.json()["error"]["fields"][0]["loc"][0] == "diy"
    assert create(api, {**HOME, "diy": ["paint"] * 7}).status_code == 422
    assert query("select count(*) as n from projects")[0]["n"] == before


def test_guest_standard_takes_diy_but_does_not_use_it(api):
    api.cookies.clear()
    plain = api.post("/guest/standard", json=HOME).json()
    with_diy = api.post("/guest/standard", json={**HOME, "diy": ["paint", "clean"]})
    assert with_diy.status_code == 200, with_diy.text
    assert (with_diy.json()["total"], with_diy.json()["days"]) == (plain["total"], plain["days"])
    assert api.post("/guest/standard", json={**HOME, "diy": ["tile"]}).status_code == 422


def test_patch_overwrites_diy_only_when_sent(api):
    signup(api)
    pid = create(api, {**HOME, "diy": ["paint"]}).json()["id"]
    assert api.patch(f"/projects/{pid}", json=HOME).json()["rev"] == 2
    assert diy_rows(pid) == [("diy", "diy.paint", "self")]  # 안 보내면 그대로
    assert api.patch(f"/projects/{pid}", json={**HOME, "diy": None}).status_code == 200
    assert diy_rows(pid) == [("diy", "diy.paint", "self")]  # null도 그대로(묻지 않음)
    r = api.patch(f"/projects/{pid}", json={**HOME, "diy": ["outlet", "handle"]})
    assert r.status_code == 200, r.text
    assert [k for _, k, _ in diy_rows(pid)] == ["diy.handle", "diy.outlet"]


# ---- PUT /projects/{id}/diy ----


def test_put_diy_is_for_the_owner_only(api):
    owner = signup(api)
    pid = create(api, HOME).json()["id"]
    r = api.put(f"/projects/{pid}/diy", json={"diy": ["outlet", "paint"]})
    assert r.status_code == 200, r.text
    assert r.json() == {"diy": ["paint", "outlet"]}  # 칩 순서
    assert chips(api, pid) == [("직접 할 일", "콘센트 · 스위치 커버"), ("직접 할 일", PAINT)]
    assert api.get(f"/projects/{pid}").json()["rev"] == 1  # 집 정보 rev는 그대로
    r = api.put(f"/projects/{pid}/diy", json={"diy": []})
    assert r.json() == {"diy": []} and diy_rows(pid) == [("diy", "diy.none", "self")]
    r = api.put(f"/projects/{pid}/diy", json={"diy": ["silicone"]})
    assert r.json() == {"diy": ["silicone"]} and diy_rows(pid) == [("diy", "diy.silicone", "self")]

    for body in ({"diy": ["tile"]}, {"diy": ["paint"], "extra": 1}, {}, {"diy": None}):
        assert api.put(f"/projects/{pid}/diy", json=body).status_code == 422, body
    assert api.put(f"/projects/{uuid.uuid4()}/diy", json={"diy": []}).status_code == 404

    signup(api, "other@mitjip.test")  # 남의 공사는 있는지조차 알리지 않는다
    assert api.put(f"/projects/{pid}/diy", json={"diy": ["clean"]}).status_code == 404
    assert api.get(f"/projects/{pid}/conditions").status_code == 404
    use(api, approved_vendor(api))
    assert api.put(f"/projects/{pid}/diy", json={"diy": ["clean"]}).status_code == 403
    api.cookies.clear()
    assert api.put(f"/projects/{pid}/diy", json={"diy": ["clean"]}).status_code == 401
    assert diy_rows(pid) == [("diy", "diy.silicone", "self")]
    use(api, owner)
    assert chips(api, pid) == [("직접 할 일", "실리콘 · 줄눈")]


def test_diy_keys_are_checked_by_db(api):
    signup(api)
    pid = create(api, HOME).json()["id"]
    insert = (
        "insert into project_conditions (id, project_id, trade, key, value)"
        " values (gen_random_uuid(), $1::uuid, 'diy', $2, $3)"
    )
    for key, value in (("diy.floor", "self"), ("diy.paint", "yes")):
        with pytest.raises(asyncpg.CheckViolationError):
            query(insert, pid, key, value)
    query(insert, pid, "diy.paint", "self")
    query(insert, pid, "dobae.mold", "있어요")  # 다른 칸은 그대로
    assert set(chips(api, pid)) == {("직접 할 일", PAINT), ("곰팡이 · 물자국", "있어요")}
