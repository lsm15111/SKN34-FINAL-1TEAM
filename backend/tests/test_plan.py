"""예상 공정표: 집 정보로 계산해 저장하고, 시작일 · 주말 공사로 다시 계산한다."""

from datetime import date, timedelta

from app.refprice.holidays import days_off
from tests.helpers import signup
from tests.test_project import body, whole


def _next_monday(after_days: int = 30) -> date:
    """공휴일이 없는 주의 월요일(테스트가 날짜에 따라 흔들리지 않게)"""
    d = date.today() + timedelta(days=after_days)
    d += timedelta(days=(7 - d.weekday()) % 7)
    while days_off(d, d + timedelta(days=14)):
        d += timedelta(days=7)
    return d


def test_plan_follows_the_chosen_start_date(api):
    signup(api)
    start = _next_monday()
    p = api.post(
        "/projects",
        json=whole(
            size={"basis": "supply", "m2": "105.8"},
            occupied=False,
            balcony_ext=False,
            when={
                "kind": "date",
                "start": start.isoformat(),
                "end": (start + timedelta(days=10)).isoformat(),
            },
        ),
    ).json()
    r = api.get(f"/projects/{p['id']}/plan")
    assert r.status_code == 200, r.text
    plan = r.json()
    work = [b for b in plan["blocks"] if b["kind"] == "work"]
    assert [b["trade"] for b in work] == ["mokgong", "dobae"]
    assert work[0]["start"] == start.isoformat() and work[0]["days"] == 3
    assert [b["kind"] for b in plan["blocks"]][-2:] == ["dry", "clean"]
    assert plan["work_days"] == 5 and plan["version"] == 1
    assert plan["days"][0]["day"] == start.isoformat()
    assert api.get(f"/projects/{p['id']}/plan").json()["version"] == 1  # 저장본을 쓴다


def test_redo_with_weekend_work_makes_a_new_version(api):
    signup(api)
    p = api.post("/projects", json=body()).json()
    first = api.get(f"/projects/{p['id']}/plan").json()
    sat = _next_monday() + timedelta(days=5)
    r = api.post(f"/projects/{p['id']}/plan", json={"start": sat.isoformat(), "weekend_work": True})
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["version"] == first["version"] + 1 and got["weekend_work"] is True
    assert got["blocks"][0]["start"] == sat.isoformat()
    past = api.post(f"/projects/{p['id']}/plan", json={"start": date.today().isoformat()})
    assert past.status_code == 422


def test_redo_is_closed_after_a_vendor_is_confirmed(api):
    from tests.conftest import query
    from tests.test_deal import confirm, setup

    _customer, pid, va, _, _ = setup(api)
    start = {"start": _next_monday().isoformat(), "weekend_work": True}
    assert api.post(f"/projects/{pid}/plan", json=start).status_code == 200  # 확정 전엔 된다
    assert confirm(api, pid, va).status_code == 200
    before = query("select count(*) from plans where kind = 'expected'")[0][0]
    r = api.post(f"/projects/{pid}/plan", json={**start, "weekend_work": False})
    assert r.status_code == 409 and r.json()["error"]["code"] == "dates_locked"
    assert query("select count(*) from plans where kind = 'expected'")[0][0] == before
    query("update deals set status = 'reselected'")  # 다시 고르면 다시 열린다
    assert api.post(f"/projects/{pid}/plan", json=start).status_code == 200


def test_plan_is_owner_only(api):
    signup(api)
    p = api.post("/projects", json=body()).json()
    signup(api, "other@mitjip.test")
    assert api.get(f"/projects/{p['id']}/plan").status_code == 404
