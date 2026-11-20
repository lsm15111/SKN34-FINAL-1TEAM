"""공사 중 추가 금액: 올리기 · 계산 엔진 금액 · 사진 · 고객 확인 · 이야기 · 합계 · 상태 규칙 · 동시 409 · 권한 · 제약."""

import asyncio
import uuid
from datetime import timedelta

import asyncpg
import pytest

from app.auth.models import User
from app.calc.common import from_entered
from app.db import SessionLocal
from app.schedule import service
from app.schedule.schemas import AckIn
from app.shared.errors import AppError
from tests.conftest import BACKEND, query
from tests.helpers import JPEG, PDF, no_surprises, signup, upload, use
from tests.test_dates import SEEN0, TODAY, days, mokgong_deal, propose, ready
from tests.test_visit_inbox import login
from tests.test_visit_request import listed

MOLD = {"title": "곰팡이 방지 처리", "reason": "안방 창가 벽에 곰팡이가 있어 방지 처리를 했어요."}


def scheduled(api):
    """도배 날짜까지 수락한 집. (고객 토큰, 프로젝트, 확정). 업체(마루와벽)로 로그인해 있다."""
    customer, pid, did, _ = ready(api)
    x = propose(api, did, *days(14)).json()["proposal"]["id"]
    use(api, customer)
    assert api.post(f"/projects/{pid}/deals/{did}/dates/{x}/accept", json=SEEN0).status_code == 200
    login(api, "maru@mitjip.test")
    return customer, pid, did


def photo(api, name: str = "mold.jpg") -> str:
    r = upload(api, kind="work_photo", content=JPEG, name=name)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def extra(api, did: str, amount: int, mode: str = "excluded", **over):
    return api.post(
        f"/vendor/jobs/{did}/extras",
        json={**MOLD, "entered_amount": amount, "vat_mode": mode, **over},
    )


def notes(kind: str) -> list[dict]:
    rows = query(
        "select body, link, dedup_key from notifications where kind = $1 order by created_at", kind
    )
    return [dict(x) for x in rows]


def test_add_then_ok_and_talk(api):
    customer, pid, did = scheduled(api)
    f = photo(api)
    r = extra(api, did, 150_000, file_ids=[f])
    assert r.status_code == 201, r.text
    (a,) = r.json()["extras"]["items"]
    m = from_entered(150_000, "excluded")
    assert (a["supply"], a["vat"], a["total"], a["ack"]) == (m.supply, m.vat, m.total, "pending")
    assert a["total"] == 165_000 and a["photos"][0]["file_id"] == f
    b = extra(api, did, 55_000, "included", title="걸레받이 보수").json()["extras"]["items"][1]
    assert (b["supply"], b["vat"], b["total"]) == (50_000, 5_000, 55_000)
    assert notes("extra_added") == [
        {
            "body": "마루와벽이 추가 금액을 알렸어요 · 도배",
            "link": f"/projects/{pid}/plan",
            "dedup_key": f"extra:{x['id']}",
        }
        for x in (a, b)
    ]
    (row,) = api.get("/vendor/visits", params={"tab": "jobs"}).json()["items"]
    assert row["extras_pending"] == 2
    assert api.get(f"/vendor/jobs/{did}/extras/{a['id']}/files/{f}").status_code == 200

    use(api, customer)
    (t,) = api.get(f"/projects/{pid}/schedule").json()["trades"]
    assert t["extras"]["pending"] == {"supply": 200_000, "vat": 20_000, "total": 220_000}
    assert t["deal"]["quote"]["total"] == 3_388_000  # 확정 금액은 그대로
    (pe,) = api.get(f"/projects/{pid}/plan").json()["extras"]
    assert (pe["trade"], len(pe["items"])) == ("dobae", 2)
    pic = api.get(f"/projects/{pid}/deals/{did}/extras/{a['id']}/files/{f}")
    assert pic.status_code == 200 and pic.headers["content-type"].startswith("image/")

    base = f"/projects/{pid}/deals/{did}/extras"
    ok = api.post(f"{base}/{a['id']}/ack", json={"ack": "ok"})
    assert ok.status_code == 200, ok.text
    assert ok.json()["ok"]["total"] == 165_000 and ok.json()["pending"]["total"] == 55_000
    talk = api.post(f"{base}/{b['id']}/ack", json={"ack": "talk"}).json()
    assert (talk["talk"]["total"], talk["pending"]["total"]) == (55_000, 0)
    assert [x["ack"] for x in talk["items"]] == ["ok", "talk"]
    assert all(x["acked_at"] for x in talk["items"])
    again = api.post(f"{base}/{a['id']}/ack", json={"ack": "talk"})
    assert (
        again.status_code == 409
        and again.json()["error"]["message"] == "이미 답한 추가 금액이에요."
    )
    assert [n["body"] for n in notes("extra_acked")] == [  # v3: 업체 알림에 공사 이름
        "고객이 추가 금액을 확인했어요 · 노원구 도배",
        "고객이 추가 금액을 이야기하고 싶어 해요 · 노원구 도배",
    ]
    assert api.post(f"{base}/{a['id']}/ack", json={"ack": "maybe"}).status_code == 422
    login(api, "maru@mitjip.test")
    (row,) = api.get("/vendor/visits", params={"tab": "jobs"}).json()["items"]
    assert row["extras_pending"] == 0


def test_only_while_working(api):
    customer, _pid, did, _ = ready(api)
    r = extra(api, did, 10_000)  # 날짜 수락 전
    assert r.status_code == 409 and r.json()["error"]["code"] == "invalid_state"
    for status, code in (("checking", 409), ("done", 409), ("fixing", 201)):
        query(
            "update deals set status = $1, start_date = current_date + 7, end_date = current_date + 9,"
            " work_done_on = current_date",
            status,
        )
        assert extra(api, did, 10_000).status_code == code, status
    use(api, customer)
    _, pid2, did2, _ = ready_other(api)
    assert api.post(f"/projects/{pid2}/deals/{did2}/reselect").status_code == 200
    login(api, "maru2@mitjip.test")
    gone = extra(api, did2, 10_000)
    assert (
        gone.status_code == 409 and gone.json()["error"]["message"] == "다시 고른 업체의 공사예요."
    )


def test_trade_not_in_home_saves_nothing(api):
    """집 정보로 필요한 기간을 못 세는 공정(도배만 고른 집의 목공)은 저장하기 전에 409.
    공사 화면 응답을 못 만드는데 추가 금액 · 알림만 저장되면 안 된다."""
    _customer, pid, _did, _ = ready(api)
    soon = TODAY + timedelta(days=1)
    vid = listed(api, "barum@mitjip.test", "바름집수리")  # 업체로 로그인
    mok = mokgong_deal(pid, vid, "scheduled", soon, soon + timedelta(days=2))
    r = extra(api, mok, 10_000)
    assert r.status_code == 409 and r.json()["error"]["code"] == "trade", r.text
    assert query("select count(*) n from extra_charges")[0]["n"] == 0
    assert notes("extra_added") == []


def ready_other(api):
    """같은 업체(마루와벽)가 아닌 새 업체 · 새 고객으로 확정만 한 집"""
    from tests.test_deal import confirm
    from tests.test_project import body as project_body
    from tests.test_quote_compare import quote
    from tests.test_visit_request import listed, send
    from tests.test_visit_vendors import NOWON_32

    v = listed(api, "maru2@mitjip.test", "마루와벽둘")
    token = signup(api, "home2@mitjip.test")
    pid = api.post("/projects", json=project_body(**NOWON_32)).json()["id"]
    assert send(api, pid, [v]).status_code == 201
    vid = str(query("select id from visits where project_id = $1", uuid.UUID(pid))[0]["id"])
    login(api, "maru2@mitjip.test")
    quote(api, vid, 1_000_000)
    use(api, token)
    did = confirm(api, pid, vid).json()["deal"]["id"]
    return token, pid, did, vid


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"entered_amount": 1_000_000_001}, "invalid"),
        ({"entered_amount": -1}, "invalid"),
        ({"title": "가" * 41}, "invalid"),
        ({"title": " "}, "invalid"),
        ({"reason": " "}, "invalid"),
        ({"vat_mode": "half"}, "invalid"),
    ],
)
def test_input_limits(api, body, code):
    _, _, did = scheduled(api)
    r = extra(api, did, 10_000, **body)
    assert r.status_code == 422 and r.json()["error"]["code"] == code, r.text


def test_exempt_vendor_and_photos(api):
    _, _, did = scheduled(api)
    query(
        "update vendors set tax_kind = 'exempt' where user_id = (select id from users where email = 'maru@mitjip.test')"
    )
    r = extra(api, did, 100_000)
    assert r.status_code == 422 and r.json()["error"]["code"] == "vat_mode"
    x = extra(api, did, 100_000, "exempt").json()["extras"]["items"][0]
    assert (x["supply"], x["vat"], x["total"]) == (100_000, 0, 100_000)
    six = [photo(api, f"{i}.jpg") for i in range(6)]
    assert extra(api, did, 1, "exempt", file_ids=six).status_code == 422  # 5장까지
    doc = upload(api, kind="quote_doc", content=PDF, name="a.pdf").json()["id"]
    assert extra(api, did, 1, "exempt", file_ids=[doc]).json()["error"]["code"] == "file"
    assert extra(api, did, 1, "exempt", file_ids=[six[0]]).status_code == 201
    used = extra(api, did, 1, "exempt", file_ids=[six[0]])
    assert used.status_code == 409 and used.json()["error"]["code"] == "file_used"
    assert extra(api, did, 1, "exempt", file_ids=[six[1], six[1]]).status_code == 422
    signup(api, "someone@mitjip.test")
    theirs = upload(api, kind="photo", content=JPEG, name="x.jpg").json()["id"]
    login(api, "maru@mitjip.test")
    assert extra(api, did, 1, "exempt", file_ids=[theirs]).json()["error"]["code"] == "file"


def test_two_acks_at_once_only_one_wins(api):
    _customer, pid, did = scheduled(api)
    xid = uuid.UUID(extra(api, did, 150_000).json()["extras"]["items"][0]["id"])
    me = query("select id from users where email = 'home@mitjip.test'")[0]["id"]

    def go(ack: str):
        async def call():
            async with SessionLocal() as s:
                user = await s.get(User, me)
                return await service.ack_extra(
                    s, user, uuid.UUID(pid), uuid.UUID(did), xid, AckIn(ack=ack)
                )

        return call

    async def both():
        return await asyncio.gather(go("ok")(), go("talk")(), return_exceptions=True)

    results = no_surprises(asyncio.run(both()))
    errors = [r for r in results if isinstance(r, AppError)]
    assert len(errors) == 1 and errors[0].status == 409
    assert len(query("select id from notifications where kind = 'extra_acked'")) == 1


def test_only_my_job_and_my_home(api):
    customer, pid, did = scheduled(api)
    f = photo(api)
    xid = extra(api, did, 150_000, file_ids=[f]).json()["extras"]["items"][0]["id"]
    vendor_calls = (
        lambda: extra(api, did, 1),
        lambda: api.get(f"/vendor/jobs/{did}/extras/{xid}/files/{f}"),
    )
    customer_calls = (
        lambda: api.post(f"/projects/{pid}/deals/{did}/extras/{xid}/ack", json={"ack": "ok"}),
        lambda: api.get(f"/projects/{pid}/deals/{did}/extras/{xid}/files/{f}"),
    )
    login(api, "gyeol@mitjip.test")
    assert all(c().status_code == 404 for c in vendor_calls)  # 다른 업체
    assert all(c().status_code == 403 for c in customer_calls)  # 업체 → 고객 API
    use(api, customer)
    assert all(c().status_code == 403 for c in vendor_calls)  # 고객 → 업체 API
    other = str(uuid.uuid4())
    assert (
        api.post(f"/projects/{pid}/deals/{did}/extras/{other}/ack", json={"ack": "ok"}).status_code
        == 404
    )
    assert api.get(f"/projects/{pid}/deals/{did}/extras/{xid}/files/{other}").status_code == 404
    assert api.get(f"/projects/{pid}/deals/{other}/extras/{xid}/files/{f}").status_code == 404
    signup(api, "other@mitjip.test")
    assert all(c().status_code == 404 for c in customer_calls)  # 남의 집
    assert query("select ack from extra_charges")[0]["ack"] == "pending"


@pytest.mark.parametrize(
    "sql",
    [
        "update extra_charges set title = ' '",
        "update extra_charges set reason = ''",
        "update extra_charges set vat_mode = 'half'",
        "update extra_charges set entered_amount = -1, supply = -1, total = -1 - vat",
        "update extra_charges set total = total + 1",  # 합계 ≠ 공급가 + 부가세
        "update extra_charges set vat_mode = 'exempt'",  # 면세인데 부가세
        "update extra_charges set supply = supply + 1, total = total + 1",  # 적은 금액과 다름
        "update extra_charges set ack = 'maybe'",
        "update extra_charges set ack = 'ok'",  # 답한 때 없음
        "update extra_charges set acked_at = now()",  # 기다림인데 답한 때
        "update extra_charge_files set sort = 5",
    ],
)
def test_extra_db_constraints(api, sql):
    _, _, did = scheduled(api)
    assert extra(api, did, 150_000, file_ids=[photo(api)]).status_code == 201
    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        query(sql)


def test_extra_migration_down_and_up(api):
    from alembic import command
    from alembic.config import Config

    _, _, did = scheduled(api)
    assert extra(api, did, 150_000).status_code == 201
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    try:
        command.downgrade(cfg, "0016_v2_date_change")
        names = {
            r["tablename"]
            for r in query("select tablename from pg_tables where schemaname = 'public'")
        }
        assert not {"extra_charges", "extra_charge_files"} & names
    finally:
        command.upgrade(cfg, "head")
    assert extra(api, did, 150_000).status_code == 201
