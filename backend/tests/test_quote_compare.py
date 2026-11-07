"""실측 견적서 다시 올리기 · 고객 비교 화면 · 견적서 파일 내주기."""

import asyncio
import uuid
from datetime import timedelta

from app.auth.models import User
from app.calc.quote_diff import percent_vs
from app.db import SessionLocal
from app.shared.clock import today_seoul
from app.shared.errors import AppError
from app.visit import service
from tests.conftest import BACKEND, query
from tests.helpers import no_surprises, signup, use
from tests.test_vendor_quote import FULL, doc, url
from tests.test_visit_inbox import login, visit_of
from tests.test_visit_request import home, listed, send
from tests.test_visit_vendors import priced

TODAY = today_seoul()


def quote(api, v: str, amount: int, mode: str = "excluded", name: str = "견적.pdf", **over):
    body = {
        **FULL,
        "file_ids": [doc(api, name)],
        "entered_amount": amount,
        "vat_mode": mode,
        **over,
    }
    assert api.put(url(v), json=body).status_code == 200
    r = api.post(f"{url(v)}/send")
    assert r.status_code == 200, r.text
    return r.json()


def three(api):
    """마루와벽(가견적 있음) · 결도배 · 한결인테리어에 도배 실측을 요청한 집"""
    a = priced(api, "maru@mitjip.test", "마루와벽")
    b = listed(api, "gyeol@mitjip.test", "결도배")
    c = listed(api, "hangyeol@mitjip.test", "한결인테리어")
    customer, p = home(api)
    assert send(api, p["id"], [a, b, c]).status_code == 201
    return customer, p, visit_of(a), visit_of(b), visit_of(c)


def test_resend_and_compare(api):
    customer, p, va, vb, vc = three(api)
    login(api, "gyeol@mitjip.test")
    quote(api, vb, 3_762_000, "included", valid_until=(TODAY + timedelta(days=5)).isoformat())
    login(api, "maru@mitjip.test")
    first = quote(api, va, 3_080_000)["sent"][0]
    assert api.post(f"{url(va)}/send").json()["error"]["code"] == "already_sent"  # 고친 게 없음

    again = quote(api, va, 3_110_000, name="견적_고침.pdf", days=4)
    assert [q["version"] for q in again["sent"]] == [2, 1]
    assert again["sent"][0]["code"] == first["code"]  # 같은 번호에 버전만 올린다
    (row,) = query("select status, quote_ver from visits where id = $1", uuid.UUID(va))
    assert (row["status"], row["quote_ver"]) == ("quoted", 2)
    ev = query(
        "select from_status, to_status, code from visit_events where visit_id = $1"
        " and code = 'resent'",
        uuid.UUID(va),
    )
    assert [(e["from_status"], e["to_status"]) for e in ev] == [("quoted", "quoted")]
    me = query("select id from users where email = 'home@mitjip.test'")[0]["id"]
    bodies = [
        r["body"]
        for r in query("select body from notifications where user_id = $1 order by created_at", me)
    ]
    assert bodies == [
        "결도배가 실측 견적서를 보냈어요 · 도배",
        "마루와벽이 실측 견적서를 보냈어요 · 도배",
        "마루와벽이 실측 견적서를 다시 올렸어요 · 도배",
    ]
    query(
        "update vendor_quotes set valid_until = $1 where visit_id = $2",
        TODAY - timedelta(days=1),
        uuid.UUID(vb),
    )

    use(api, customer)
    r = api.get(f"/projects/{p['id']}/quotes", params={"trade": "dobae"})
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["standard_total"] == 2_945_656 and c["sent_counts"] == {"dobae": 2}
    assert c["formula_ver"] and c["price_ver"] and c["computed_at"]
    names = [(x["vendor_name"], x["status"]) for x in c["vendors"]]
    assert names == [("결도배", "quoted"), ("마루와벽", "quoted"), ("한결인테리어", "requested")]
    gyeol, maru, waiting = c["vendors"]
    assert gyeol["expired"] is True and maru["expired"] is False
    assert (
        gyeol["latest"]["total"] == 3_762_000 and gyeol["changed"] == [] and gyeol["history"] == []
    )
    assert maru["seen_ver"] == 2 and maru["latest"]["version"] == 2
    assert maru["latest"]["total"] == 3_421_000 and maru["latest"]["supply"] == 3_110_000
    assert [h["total"] for h in maru["history"]] == [3_388_000]  # 처음 금액
    assert maru["changed"] == ["total", "days"]
    assert maru["vs_standard"] == str(percent_vs(3_421_000, 2_945_656))
    assert (
        maru["estimate_total"] == 2_883_865
        and maru["latest"]["files"][0]["filename"] == "견적_고침.pdf"
    )
    assert waiting["latest"] is None and waiting["seen_ver"] is None and waiting["expired"] is False
    (mine,) = [x for x in api.get(f"/projects/{p['id']}/visits").json()["visits"] if x["id"] == va]
    assert mine["quote"]["version"] == 2
    assert api.get(f"/projects/{p['id']}/quotes", params={"trade": "mokgong"}).status_code == 422
    assert vc


def test_two_resends_at_once_and_chosen(api):
    _, p, va, _, _ = three(api)
    login(api, "maru@mitjip.test")
    quote(api, va, 3_080_000)
    api.put(url(va), json={**FULL, "file_ids": [doc(api, "고침.pdf")]})
    maru = query("select id from users where email = 'maru@mitjip.test'")[0]["id"]

    async def go():
        async with SessionLocal() as s:
            vendor = await s.get(User, maru)
            return await service.send_quote(s, vendor, uuid.UUID(va), TODAY)

    async def both():
        return await asyncio.gather(go(), go(), return_exceptions=True)

    results = no_surprises(asyncio.run(both()))
    errors = [r for r in results if isinstance(r, AppError)]
    assert len(errors) == 1 and errors[0].status == 409
    assert query("select quote_ver from visits where id = $1", uuid.UUID(va))[0][0] == 2
    assert len(query("select id from notifications where kind = 'quote_resent'")) == 1

    query("update visits set status = 'chosen' where id = $1", uuid.UUID(va))
    r = api.put(url(va), json=FULL)
    assert (
        r.status_code == 409
        and r.json()["error"]["message"] == "고객이 확정해서 다시 올릴 수 없어요."
    )
    assert api.post(f"{url(va)}/send").status_code == 409
    assert p


def test_quote_files_go_only_to_the_right_people(api):
    customer, p, va, vb, _ = three(api)
    login(api, "maru@mitjip.test")
    v1 = quote(api, va, 3_080_000, name="처음.pdf")["sent"][0]
    v2 = quote(api, va, 3_110_000, name="고침.pdf")["sent"][0]
    f1, f2 = v1["files"][0]["file_id"], v2["files"][0]["file_id"]
    draft = api.put(url(va), json={**FULL, "file_ids": [doc(api, "임시.pdf")]}).json()["draft"]
    f3 = draft["files"][0]["file_id"]
    assert api.get(f"{url(va)}/files/{f3}").status_code == 200  # 업체 본인: 임시 저장본도
    assert api.get(f"{url(va)}/files/{f1}").status_code == 200
    assert (
        api.get(f"/projects/{p['id']}/quotes/{v2['id']}/files/{f2}").status_code == 403
    )  # 업체 → 고객 API
    login(api, "gyeol@mitjip.test")
    b_file = quote(api, vb, 3_500_000, name="결.pdf")["sent"][0]["files"][0]["file_id"]
    assert api.get(f"{url(va)}/files/{f1}").status_code == 404  # 다른 업체
    assert api.get(f"{url(vb)}/files/{f1}").status_code == 404  # 다른 요청 파일
    assert api.get(f"{url(vb)}/files/{b_file}").status_code == 200

    use(api, customer)
    base = f"/projects/{p['id']}/quotes"
    ok = api.get(f"{base}/{v2['id']}/files/{f2}")
    assert ok.status_code == 200 and ok.headers["content-type"] == "application/pdf"
    assert api.get(f"{base}/{v1['id']}/files/{f1}").status_code == 200  # 예전 버전도 기록으로
    assert api.get(f"{base}/{v2['id']}/files/{f1}").status_code == 404  # 버전과 파일이 안 맞음
    assert api.get(f"{base}/{draft['id']}/files/{f3}").status_code == 404  # 임시 저장본
    assert api.get(f"{url(va)}/files/{f1}").status_code == 403  # 고객 → 업체 API
    signup(api, "stranger@mitjip.test")
    assert api.get(f"{base}/{v2['id']}/files/{f2}").status_code == 404  # 남의 집
    _, other = home(api, "other-home@mitjip.test")
    assert api.get(f"/projects/{other['id']}/quotes/{v2['id']}/files/{f2}").status_code == 404


def test_code_migration_down_and_up(api):
    from alembic import command
    from alembic.config import Config

    _, _, va, _, _ = three(api)
    login(api, "maru@mitjip.test")
    quote(api, va, 3_080_000)
    quote(api, va, 3_110_000, name="고침.pdf")
    assert len({r["code"] for r in query("select code from vendor_quotes")}) == 1
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    try:
        command.downgrade(cfg, "0011_v2_vendor_quote")
        assert (
            len({r["code"] for r in query("select code from vendor_quotes")}) == 2
        )  # 예전: 버전마다
    finally:
        command.upgrade(cfg, "head")
    assert query("select count(*) n from vendor_quotes")[0]["n"] == 2
