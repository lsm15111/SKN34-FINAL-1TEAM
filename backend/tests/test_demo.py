"""시연 데이터 (app/demo.py): 단계마다 프로젝트 하나 · 다시 돌리면 계정은 그대로 · 운영에서는 멈춤.
자동 응답: 시연 업체가 견적서 · 공사 날짜 · 날짜 요청 답을 대신 낸다(DEMO_AUTO, 운영에서는 꺼짐)."""

import asyncio

import pytest

from app import demo, worker
from app.db import engine
from app.shared.clock import today_seoul
from app.visit.service import CONSENT_VER
from tests.conftest import query
from tests.helpers import PASSWORD, make_admin


def test_demo_makes_one_project_per_stage(api):
    make_admin(api)
    made = asyncio.run(demo.build(PASSWORD, today_seoul()))
    api.cookies.clear()
    r = api.post("/auth/login", json={"email": demo.CUSTOMER[0], "password": PASSWORD})
    assert r.status_code == 200, r.text
    todo = {x["code"]: x["todo"]["code"] for x in api.get("/projects").json()}
    assert todo == {code: stage for stage, code in made.items()}
    assert list(made) == list(demo.LABEL)

    asyncio.run(demo.build(PASSWORD, today_seoul()))  # 계정은 그대로, 프로젝트만 한 벌 더
    assert len(api.get("/projects").json()) == 10
    assert query("select count(*) n from users where email like 'demo%'")[0]["n"] == 7
    assert query("select count(*) n from vendors where status = 'approved'")[0]["n"] == 6
    sets = query("select count(*) n from vendor_price_sets where status = 'confirmed'")
    assert sets[0]["n"] == 6


def _reply(today, skip: set) -> int:
    async def go():
        try:
            return await demo.auto_reply(today, skip)
        finally:
            await engine.dispose()  # asyncio.run마다 이벤트 루프가 새로 생긴다

    return asyncio.run(go())


def _dobae(api, pid: str) -> dict:
    r = api.get(f"/projects/{pid}/schedule")
    assert r.status_code == 200, r.text
    return r.json()["trades"][0] | {"final_version": r.json()["final_version"]}


def test_demo_auto_reply_answers_like_a_vendor(api):
    make_admin(api)
    today = today_seoul()
    made = asyncio.run(demo.build(PASSWORD, today))
    skip: set = set()
    assert _reply(today, skip) == 0  # 미리 만든 단계(업체가 열어 본 실측 요청 포함)는 그대로
    api.cookies.clear()
    r = api.post("/auth/login", json={"email": demo.CUSTOMER[0], "password": PASSWORD})
    assert r.status_code == 200, r.text
    pid = next(p["id"] for p in api.get("/projects").json() if p["code"] == made["pick"])
    (d1,) = query("select id from users where email = $1", demo.D1)
    vid = str(d1["id"])

    body = {"trade": "dobae", "vendor_ids": [vid], "share_contact_ids": [vid]}
    body |= {"apt_name": "시연아파트", "dong": "101", "ho": "1203"}
    r = api.post(f"/projects/{pid}/visits", json=body | {"consent_ver": CONSENT_VER})
    assert r.status_code == 201, r.text
    visit = r.json()["created"][0]
    assert _reply(today, skip) == 1  # 실측 견적서 보냄
    assert _reply(today, skip) == 0  # 같은 일을 두 번 하지 않는다
    (v,) = query("select status from visits where id = $1", visit["id"])
    sql = "select entered_amount, vat_mode, total from vendor_quotes where visit_id = $1"
    (q,) = query(sql, visit["id"])
    assert v["status"] == "quoted"  # 업체 문서에 적힌 금액 그대로, 합계는 계산 엔진이
    assert (q["entered_amount"], q["vat_mode"], q["total"]) == (3_080_000, "excluded", 3_388_000)
    sql = """select f.content_type from vendor_quote_files qf join files f on f.id = qf.file_id
             join vendor_quotes q on q.id = qf.quote_id where q.visit_id = $1"""
    (doc,) = query(sql, visit["id"])  # 업체 견적서 이미지가 있으면 그 그림을 보낸다
    has_image = (demo.ASSETS / demo.QUOTE_DOCS[demo.D1][0]).exists()
    assert doc["content_type"] == ("image/jpeg" if has_image else "application/pdf")

    r = api.post(f"/projects/{pid}/quotes/{visit['id']}/confirm", json={"seen_ver": 1})
    assert r.status_code == 200, r.text
    assert _reply(today, skip) == 1  # 공사 날짜 냄
    t = _dobae(api, pid)
    assert t["dates_state"] == "proposed" and t["proposal"]["start"] > today.isoformat()

    did = t["deal"]["id"]
    wish = next(o["start"] for o in t["start_options"] if o["start"] != t["proposal"]["start"])
    r = api.post(f"/projects/{pid}/deals/{did}/date-requests", json={"wish_dates": [wish]})
    assert r.status_code == 201, r.text
    assert _reply(today, skip) == 1  # 고객이 고른 시작일로 다시 냄
    t = _dobae(api, pid)
    assert (t["dates_state"], t["proposal"]["start"], t["request"]) == ("proposed", wish, None)

    url = f"/projects/{pid}/deals/{did}/dates/{t['proposal']['id']}/accept"
    r = api.post(url, json={"seen_version": t["final_version"]})
    assert r.status_code == 200, r.text
    t = _dobae(api, pid)
    later = t["start_options"][-1]["start"]
    r = api.post(
        f"/projects/{pid}/deals/{did}/date-requests",
        json={"wish_dates": [later], "reason": "이사 날짜가 바뀌었어요"},
    )
    assert r.status_code == 201, r.text
    assert _reply(today, skip) == 1  # 수락한 날짜 바꾸기 요청에 답함
    t = _dobae(api, pid)
    assert (t["dates_state"], t["proposal"]["start"]) == ("change_proposed", later)
    assert _reply(today, skip) == 0 and not skip


def test_demo_auto_reply_is_off_by_default_and_in_production(monkeypatch):
    assert worker.demo_on() is False
    monkeypatch.setattr(worker.settings, "demo_auto", True)
    assert worker.demo_on() is True
    monkeypatch.setattr(worker.settings, "app_env", "production")
    assert worker.demo_on() is False


def test_demo_needs_an_admin():
    with pytest.raises(RuntimeError):
        asyncio.run(demo.build(PASSWORD, today_seoul()))
    assert query("select count(*) n from users")[0]["n"] == 0


def test_demo_refuses_production(monkeypatch):
    monkeypatch.setattr(demo.settings, "app_env", "production")
    monkeypatch.setenv("DEMO_PASSWORD", PASSWORD)
    with pytest.raises(SystemExit):
        demo.main()
    assert query("select count(*) n from users")[0]["n"] == 0
