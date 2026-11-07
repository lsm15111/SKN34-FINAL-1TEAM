"""실측 요청: 3곳 한도 · 같은 업체 한 번 · 취소된 칸 다시 쓰기, 연락처 동의, 가견적 사본, 알림, 연락처 공개 규칙."""

import asyncio
import uuid
from datetime import date

import asyncpg
import pytest

from app.auth.models import User
from app.calc.schedule import contact_until
from app.db import SessionLocal
from app.shared.clock import today_seoul
from app.shared.errors import AppError
from app.visit import service
from app.visit.models import Visit
from app.visit.schemas import VisitCreateIn
from tests.conftest import query
from tests.helpers import make_admin, no_surprises, signup, vendor_signup
from tests.test_project import SOON, SOON_END
from tests.test_project import body as project_body
from tests.test_vendor_profile import URL as PROFILE
from tests.test_vendor_profile import approved_vendor, vendor_id
from tests.test_vendor_profile import body as profile_body
from tests.test_visit_vendors import NOWON_32, priced

SHARE = {"apt_name": "상계주공", "dong": "101", "ho": "1203", "consent_ver": service.CONSENT_VER}
BAD_EVENT = (
    "insert into visit_events (id, visit_id, to_status)"
    " select gen_random_uuid(), id, 'lost' from visits"
)
VISIT_ROW = (
    "insert into visits (id, project_id, trade, vendor_id, vendor_name, slot)"
    " select gen_random_uuid(), project_id, trade, {vendor}, 'x', {slot} from visits"
)


def listed(api, email: str, name: str, **profile) -> str:
    """승인 · 업체 정보까지 저장한 도배 업체 (확인한 단가는 없음)"""
    approved_vendor(api, email)
    assert api.put(PROFILE, json=profile_body(**profile)).status_code == 200
    query("update vendors set biz_name = $1 where user_id = $2", name, vendor_id(email))
    return str(vendor_id(email))


def home(api, email: str = "home@mitjip.test") -> tuple[str, dict]:
    token = signup(api, email)
    r = api.post("/projects", json=project_body(**NOWON_32))
    assert r.status_code == 201, r.text
    return token, r.json()


def send(api, pid: str, ids: list[str], **body):
    return api.post(f"/projects/{pid}/visits", json={"trade": "dobae", "vendor_ids": ids, **body})


def md(d: str) -> str:
    x = date.fromisoformat(d)
    return f"{x:%m.%d}({'월화수목금토일'[x.weekday()]})"


def test_request_creates_visits_locks_home_and_notifies(api):
    a = priced(api, "maru@mitjip.test", "마루와벽")
    b = listed(api, "gyeol@mitjip.test", "결도배")
    x = listed(api, "gangnam@mitjip.test", "강남도배", areas=[{"sido": "seoul", "sgg": "강남구"}])
    token, p = home(api)
    pid = p["id"]
    estimate = api.get(f"/projects/{pid}/vendors", params={"trade": "dobae"}).json()
    assert estimate["slots_left"] == 3 and estimate["consent_ver"] == service.CONSENT_VER
    a_total = next(v for v in estimate["vendors"] if v["vendor_id"] == a)["estimate_total"]

    r = send(api, pid, [a, b, x], message="평일 오후가 좋아요", share_contact_ids=[a], **SHARE)
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["failed"] == [{"vendor_id": x, "code": "unavailable"}]
    got = {v["vendor_id"]: v for v in out["created"]}
    assert (got[a]["slot"], got[b]["slot"]) == (1, 2)
    assert got[a]["share_contact"] is True and got[b]["share_contact"] is False
    assert got[a]["estimate_total"] == a_total == 2_883_865  # 14번 계산과 같은 사본
    assert got[b]["estimate_total"] is None  # 가견적 없음
    assert got[a]["contact"]["phone"] == "01059372210" and got[a]["contact_visible"] is True
    assert got[a]["message"] == "평일 오후가 좋아요" and got[a]["vendor_name"] == "마루와벽"

    rows = {
        str(r["vendor_id"]): r
        for r in query("select vendor_id, consent_ver, consent_at, estimate_set_id from visits")
    }
    confirmed = query("select id from vendor_price_sets where status = 'confirmed'")[0]["id"]
    assert rows[a]["consent_ver"] == service.CONSENT_VER and rows[a]["consent_at"] is not None
    assert rows[a]["estimate_set_id"] == confirmed
    assert rows[b]["consent_ver"] is None and rows[b]["estimate_set_id"] is None
    (proj,) = query("select locked_at, apt_name, dong, ho from projects")
    assert proj["locked_at"] is not None
    assert (proj["apt_name"], proj["dong"], proj["ho"]) == ("상계주공", "101", "1203")
    edit = api.patch(f"/projects/{pid}", json=project_body(**NOWON_32))
    assert edit.status_code == 409 and edit.json()["error"]["code"] == "locked"
    events = query("select from_status, to_status, by_id from visit_events")
    me = query("select id from users where email = 'home@mitjip.test'")[0]["id"]
    assert [(e["from_status"], e["to_status"], e["by_id"]) for e in events] == [
        (None, "requested", me)
    ] * 2

    for vid in (a, b):
        n = query(
            "select body, link, dedup_key from notifications where user_id = $1", uuid.UUID(vid)
        )
        visit_id = got[vid]["id"]
        assert [dict(r) for r in n] == [
            {
                "body": "새 실측 요청이 왔어요 · 도배",
                "link": f"/vendor/requests/{visit_id}",
                "dedup_key": f"visit:{visit_id}",
            }
        ]
    assert (
        query("select count(*) n from notifications where user_id = $1", uuid.UUID(x))[0]["n"] == 0
    )

    listing = api.get(f"/projects/{pid}/visits").json()
    assert listing["slots_left"] == {"dobae": 1} and listing["consent_ver"] == service.CONSENT_VER
    text = (
        f"[믿집] 실측 요청이에요. 요청 번호 {p['code']} · 도배 기본형 · 노원구 아파트 32평(공급 105.8㎡)"
        f" · 희망 시기 {md(SOON)} ~ {md(SOON_END)} · 빈 집이에요."
    )
    assert listing["request_texts"] == [{"trade": "dobae", "text": text}]
    assert {v["vendor_id"] for v in listing["visits"]} == {a, b}
    rows14 = {
        v["vendor_id"]: v for v in api.get(f"/projects/{pid}/vendors?trade=dobae").json()["vendors"]
    }
    assert rows14[a]["visit"] == {
        "id": got[a]["id"],
        "status": "requested",
        "decline_code": None,
        "close_reason": None,
    }
    detail = api.get(f"/projects/{pid}/vendors/{b}", params={"trade": "dobae"}).json()
    assert detail["visit"]["id"] == got[b]["id"]
    assert token


def test_three_slots_one_request_per_vendor_and_freed_slots(api):
    v = {n: listed(api, f"{n}@mitjip.test", n) for n in ("a", "b", "c", "d")}
    _, p = home(api)
    pid = p["id"]
    assert [x["slot"] for x in send(api, pid, [v["a"], v["b"], v["c"]]).json()["created"]] == [
        1,
        2,
        3,
    ]

    def code(ids) -> tuple[int, str]:
        r = send(api, pid, ids)
        return r.status_code, r.json().get("error", {}).get("code", "")

    assert code([v["d"]]) == (409, "slots_full")  # 4번째
    assert code([v["a"]]) == (409, "already")  # 같은 업체 두 번
    assert code([str(uuid.uuid4())]) == (409, "unavailable")
    b_visit = query("select id from visits where vendor_id = $1", uuid.UUID(v["b"]))[0]["id"]
    query("update visits set status = 'cancelled' where id = $1", b_visit)
    assert code([v["b"], v["d"]]) == (409, "slots_full")  # 빈 칸은 하나
    again = send(api, pid, [v["d"]]).json()
    assert again["created"][0]["slot"] == 2 and again["failed"] == []  # 취소된 칸을 다시 쓴다
    query("update visits set status = 'cancelled' where vendor_id = $1", uuid.UUID(v["d"]))
    back = send(api, pid, [v["b"]]).json()["created"][0]  # 취소한 업체에 다시 요청
    assert back["slot"] == 2 and back["status"] == "requested"
    listing = api.get(f"/projects/{pid}/visits", params={"trade": "dobae"}).json()
    assert len(listing["visits"]) == 5 and listing["slots_left"] == {"dobae": 0}
    hidden = [x for x in listing["visits"] if x["status"] == "cancelled"]
    assert len(hidden) == 2 and all(
        not x["contact_visible"] and x["contact"] is None for x in hidden
    )
    rows = api.get(f"/projects/{pid}/vendors", params={"trade": "dobae"}).json()["vendors"]
    assert {x["vendor_id"]: x["visit"]["status"] for x in rows}[v["b"]] == "requested"  # 최근 요청


def test_two_requests_at_once_only_one_fits(api):
    v = [listed(api, f"v{i}@mitjip.test", f"업체{i}") for i in range(4)]
    _, p = home(api)
    api.get(f"/projects/{p['id']}/standard")  # 표준견적서를 먼저 저장해 둔다
    me = query("select id from users where email = 'home@mitjip.test'")[0]["id"]

    async def ask(ids):
        async with SessionLocal() as s:
            user = await s.get(User, me)
            data = VisitCreateIn(trade="dobae", vendor_ids=[uuid.UUID(i) for i in ids])
            return await service.request_visits(s, user, uuid.UUID(p["id"]), data, today_seoul())

    async def both():
        return await asyncio.gather(ask(v[:2]), ask(v[2:]), return_exceptions=True)

    results = no_surprises(asyncio.run(both()))
    errors = [r for r in results if isinstance(r, AppError)]
    assert len(errors) == 1 and errors[0].status == 409 and errors[0].code == "slots_full"
    assert query("select count(*) n from visits")[0]["n"] == 2

    async def same():
        return await asyncio.gather(ask([v[3]]), ask([v[3]]), return_exceptions=True)

    query("delete from visits")
    results = no_surprises(asyncio.run(same()))
    errors = [r for r in results if isinstance(r, AppError)]
    assert len(errors) == 1 and errors[0].code == "already"
    assert query("select count(*) n from visits")[0]["n"] == 1


def test_contact_sharing_rules(api):
    a = listed(api, "a@mitjip.test", "가")
    b = listed(api, "b@mitjip.test", "나")
    _, p = home(api)
    pid = p["id"]

    def code(**body) -> tuple[int, str]:
        r = send(api, pid, [a, b], **body)
        return r.status_code, r.json().get("error", {}).get("code", "")

    query("update users set phone = null where email = 'home@mitjip.test'")
    assert code(share_contact_ids=[a], **SHARE) == (422, "phone_required")
    query("update users set phone = '01012345678' where email = 'home@mitjip.test'")
    assert code(share_contact_ids=[a], **{**SHARE, "dong": " "}) == (422, "address_required")
    assert code(share_contact_ids=[a], **{**SHARE, "ho": None}) == (422, "address_required")
    assert code(share_contact_ids=[a], **{**SHARE, "consent_ver": "2020-01-01"}) == (
        409,
        "consent_changed",
    )
    assert code(share_contact_ids=[str(uuid.uuid4())], **SHARE)[0] == 422  # 요청 안 하는 업체
    assert send(api, pid, [a, a]).status_code == 422
    assert send(api, pid, []).status_code == 422
    assert send(api, pid, [a, b, a, b]).status_code == 422
    assert send(api, pid, [a], message="가" * 301).status_code == 422
    assert query("select count(*) n from visits")[0]["n"] == 0
    assert query("select locked_at from projects")[0]["locked_at"] is None  # 실패하면 잠그지 않는다
    ok = send(api, pid, [a, b], share_contact_ids=[b], **SHARE).json()["created"]
    assert {x["vendor_id"]: x["share_contact"] for x in ok} == {a: False, b: True}


def test_only_the_owner_customer_can_request(api):
    a = listed(api, "a@mitjip.test", "가")
    _, p = home(api)
    pid = p["id"]
    assert send(api, pid, [a], trade="mokgong").status_code == 422  # 이 집은 도배만
    assert api.get(f"/projects/{pid}/visits", params={"trade": "mokgong"}).status_code == 422
    signup(api, "other@mitjip.test")
    assert send(api, pid, [a]).status_code == 404
    assert api.get(f"/projects/{pid}/visits").status_code == 404
    vendor_signup(api, email="v@mitjip.test")
    assert send(api, pid, [a]).status_code == 403
    assert api.get(f"/projects/{pid}/visits").status_code == 403
    make_admin(api)
    assert send(api, pid, [a]).status_code == 403
    assert api.get(f"/projects/{pid}/visits").status_code == 403
    api.cookies.clear()
    assert send(api, pid, [a]).status_code == 401
    assert query("select count(*) n from visits")[0]["n"] == 0


def test_contact_visible_by_status_and_until():
    today = date(2029, 2, 28)
    assert service.contact_visible("requested", None, today)
    assert service.contact_visible("quoted", None, today)
    for status in ("cancelled", "declined", "closed"):
        assert not service.contact_visible(status, None, today)
    until = contact_until(date(2028, 2, 29))  # 공사 끝낸 날이 2/29이면 다음 해 2/28까지
    assert until == date(2029, 2, 28)
    assert service.contact_visible("chosen", until, date(2029, 2, 28))  # 마지막 날까지 보인다
    assert not service.contact_visible("chosen", until, date(2029, 3, 1))
    assert service.contact_visible("chosen", None, today)  # 아직 공사를 안 끝냄
    shared = Visit(status="requested", share_contact=True, contact_until=None)
    assert service.customer_contact_visible(shared, today)
    assert not service.customer_contact_visible(
        Visit(status="requested", share_contact=False), today
    )
    assert not service.customer_contact_visible(
        Visit(status="cancelled", share_contact=True), today
    )


@pytest.mark.parametrize(
    ("sql", "error"),
    [
        ("update visits set slot = 4", "check"),
        ("update visits set status = 'lost'", "check"),
        ("update visits set status = 'declined'", "check"),  # 못 받음 사유 없음
        ("update visits set decline_code = 'full'", "check"),  # 요청함인데 사유
        ("update visits set status = 'declined', decline_code = 'busy'", "check"),
        ("update visits set status = 'closed'", "check"),  # 닫힌 까닭 없음
        ("update visits set share_contact = true", "check"),  # 동의 없이 연락처
        ("update visits set consent_ver = '2026-11-01'", "check"),  # 동의 시각 없음
        ("update visits set message = '  '", "check"),
        ("update visits set estimate_total = -1", "check"),
        ("update visits set quote_ver = 0", "check"),
        (VISIT_ROW.format(vendor="null", slot="slot"), "unique"),  # 같은 칸
        (VISIT_ROW.format(vendor="vendor_id", slot="3"), "unique"),  # 같은 업체
        (BAD_EVENT, "check"),
    ],
)
def test_db_constraints(api, sql, error):
    a = listed(api, "a@mitjip.test", "가")
    _, p = home(api)
    assert send(api, p["id"], [a]).status_code == 201
    wanted = {
        "check": asyncpg.exceptions.CheckViolationError,
        "unique": asyncpg.exceptions.UniqueViolationError,
    }[error]
    with pytest.raises(wanted):
        query(sql)


def test_closed_requests_free_the_unique_slots(api):
    a = listed(api, "a@mitjip.test", "가")
    _, p = home(api)
    assert send(api, p["id"], [a]).status_code == 201
    query("update visits set status = 'declined', decline_code = 'full'")
    query(VISIT_ROW.format(vendor="vendor_id", slot="slot"))  # 못 받은 요청은 칸을 비운다
    assert query("select count(*) n from visits")[0]["n"] == 2
