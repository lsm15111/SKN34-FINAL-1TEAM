"""앱 안 가견적 요청 · 업체 받은편지함: 권한, 상태 전이, 동시 요청 (가짜 고객 · 가짜 업체)."""

import asyncio
import uuid

from app.auth.models import User
from app.db import SessionLocal
from app.quote import service
from app.quote.schemas import QuoteRequestIn
from app.shared.errors import AppError
from tests.conftest import query
from tests.helpers import signup, use
from tests.sourcing_helpers import app_vendor, customer_project


def world(api):
    a_token, a_id = app_vendor(api, "a@mitjip.test", "가짜도배A", trades=("dobae", "mokgong"))
    b_token, b_id = app_vendor(api, "b@mitjip.test", "가짜도배B")
    _, far_id = app_vendor(api, "far@mitjip.test", "가짜먼곳", area=("busan", "중구"))
    c_token, pid = customer_project(api)
    return {"a": (a_token, a_id), "b": (b_token, b_id), "far": far_id, "c": c_token, "pid": pid}


def ask(api, pid, vendor_id, trade="dobae", **kw):
    return api.post(
        f"/projects/{pid}/quote-requests", json={"trade": trade, "vendor_id": vendor_id, **kw}
    )


def test_customer_requests_and_vendor_sees_it(api):
    w = world(api)
    r = ask(api, w["pid"], w["a"][1], message="실크로 하고 싶어요")
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "requested"
    card = next(
        c
        for c in api.get(f"/projects/{w['pid']}/sourcing").json()["candidates"]
        if c["id"] == w["a"][1]
    )
    assert card["requests"] == [{"trade": "dobae", "status": "requested", "label": "요청했어요"}]

    use(api, w["a"][0])
    inbox = api.get("/vendor/quote-requests")
    assert inbox.status_code == 200, inbox.text
    (item,) = inbox.json()
    assert (item["trade_label"], item["region"], item["message"]) == (
        "도배",
        "서울 마포구",
        "실크로 하고 싶어요",
    )
    assert item["facts"][0] == "도배: 기본형, 거실 · 방 · 방 2" and not any(
        f.startswith("목공") for f in item["facts"]
    )  # 요청한 공정만
    assert "customer@mitjip.test" not in inbox.text  # 고객 연락처는 넘기지 않는다
    use(api, w["b"][0])
    assert api.get("/vendor/quote-requests").json() == []  # 다른 업체 것은 안 보인다


def test_viewed_once_then_409_and_history(api):
    w = world(api)
    req = ask(api, w["pid"], w["a"][1]).json()["id"]
    use(api, w["b"][0])
    assert api.post(f"/vendor/quote-requests/{req}/viewed").status_code == 404  # 남의 것
    use(api, w["a"][0])
    ok = api.post(f"/vendor/quote-requests/{req}/viewed")
    assert ok.status_code == 200 and ok.json()["status"] == "viewed" and ok.json()["viewed_at"]
    again = api.post(f"/vendor/quote-requests/{req}/viewed")
    assert again.status_code == 409 and again.json()["error"]["code"] == "invalid_state"
    hist = query("select from_status, to_status from quote_request_events order by at")
    assert [(h["from_status"], h["to_status"]) for h in hist] == [
        (None, "requested"),
        ("requested", "viewed"),
    ]


def test_same_request_twice_is_409(api):
    w = world(api)
    assert ask(api, w["pid"], w["a"][1]).status_code == 201
    dup = ask(api, w["pid"], w["a"][1])
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "already_requested"
    assert ask(api, w["pid"], w["a"][1], trade="mokgong").status_code == 201  # 공정이 다르면 따로


def test_same_request_at_the_same_time_is_409_not_500(api):
    w = world(api)
    (cust,) = query("select id from users where email = 'customer@mitjip.test'")

    async def both():
        async def once():
            async with SessionLocal() as s:
                user = await s.get(User, cust["id"])
                data = QuoteRequestIn(trade="dobae", vendor_id=uuid.UUID(w["a"][1]))
                try:
                    await service.create_quote_request(s, user, uuid.UUID(w["pid"]), data)
                    return 201
                except AppError as exc:
                    return exc.status

        return await asyncio.gather(once(), once())

    assert sorted(asyncio.run(both())) == [201, 409]
    assert query("select count(*) n from quote_requests")[0]["n"] == 1
    assert query("select count(*) n from quote_request_events")[0]["n"] == 1


def test_only_eligible_vendors_and_project_trades(api):
    w = world(api)
    assert ask(api, w["pid"], w["far"]).json()["error"]["code"] == "vendor"  # 다른 지역
    assert ask(api, w["pid"], w["b"][1], trade="mokgong").json()["error"]["code"] == "vendor"
    assert ask(api, w["pid"], str(uuid.uuid4())).status_code == 422
    assert ask(api, w["pid"], w["a"][1], trade="tile").json()["error"]["code"] == "trade"
    _, pending = app_vendor(api, "p@mitjip.test", "가짜대기", approved=False)
    use(api, w["c"])
    assert ask(api, w["pid"], pending).status_code == 422  # 승인 전 업체


def test_permissions_and_limits(api):
    w = world(api)
    assert ask(api, w["pid"], w["a"][1], message="가" * 1001).status_code == 422
    big = api.post(
        f"/projects/{w['pid']}/quote-requests",
        content=b"{" + b" " * (1024 * 1024 + 10) + b"}",
        headers={"content-type": "application/json"},
    )
    assert big.status_code == 413
    assert api.get("/vendor/quote-requests").status_code == 403  # 고객은 받은편지함이 없다
    signup(api, "other@mitjip.test")
    assert ask(api, w["pid"], w["a"][1]).status_code == 404  # 남의 프로젝트
    use(api, w["a"][0])
    assert ask(api, w["pid"], w["a"][1]).status_code == 403  # 업체는 요청을 못 만든다
    _, _ = app_vendor(api, "wait@mitjip.test", "가짜승인대기", approved=False)
    nope = api.get("/vendor/quote-requests")
    assert nope.status_code == 403 and nope.json()["error"]["code"] == "vendor_not_approved"
    api.cookies.clear()
    assert ask(api, w["pid"], w["a"][1]).status_code == 401
