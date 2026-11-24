"""업체 정보: 승인된 업체 본인만 보고 저장, 동시 저장은 409, 사진 더하기 · 빼기, 고객용 공개 정보."""

import asyncio
import uuid
from datetime import timedelta

import asyncpg
import pytest

from app.config import settings
from app.db import SessionLocal
from app.shared.clock import now_utc, today_seoul
from app.shared.errors import AppError
from app.vendor import repository as repo
from app.vendor import service
from tests.conftest import query
from tests.helpers import JPEG, biz_no_for, signup, upload, use, vendor_signup

URL = "/vendor/profile"


def approved_vendor(api, email: str = "vendor@mitjip.test") -> str:
    """업체 가입 뒤 관리자가 승인한 것처럼 바꾼다. 세션 토큰을 돌려준다."""
    assert vendor_signup(api, email=email).status_code == 201
    query(
        "update vendors set status = 'approved', reviewed_at = now(), approved_at = now()"
        " where user_id = (select id from users where email = $1)",
        email,
    )
    return api.cookies.get(settings.session_cookie)


def vendor_id(email: str = "vendor@mitjip.test") -> uuid.UUID:
    return query("select id from users where email = $1", email)[0]["id"]


def body(**over) -> dict:
    b = {
        "updated_at": None,
        "phone": "010-5937-2210",
        "address": "서울특별시 도봉구 예시로 1",
        "site_url": "www.example.com",
        "trades": ["dobae"],
        "areas": [{"sido": "seoul", "sgg": "노원구"}, {"sido": "seoul", "sgg": "도봉구"}],
        "contact_method": "phone",
        "call_start": "09:00",
        "call_end": "18:00",
        "visit_fee": 0,
        "interior_license": "등록했어요",
        "faqs": [
            {"key": "process", "answer": "전화로 날짜를 정해 실측해요."},
            {"key": "duration", "answer": "  "},  # 비운 답은 지운다
        ],
        "links": [{"label": "블로그", "url": "https://blog.example.com/a"}],
    }
    b.update(over)
    return b


def portfolio(api, file_id, **meta):
    return api.post("/vendor/portfolio", json={"file_id": str(file_id), "title": "벽지", **meta})


def test_save_and_read_back(api):
    approved_vendor(api)
    first = api.get(URL)
    assert first.status_code == 200, first.text
    assert first.json()["updated_at"] is None and first.json()["faqs"] == []

    r = api.put(URL, json=body(biz_name="바꾼 상호", biz_no="1234567890"))
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["phone"] == "01059372210" and got["site_url"] == "https://www.example.com"
    assert [a["label"] for a in got["areas"]] == ["서울 노원구", "서울 도봉구"]
    assert got["faqs"] == [{"key": "process", "answer": "전화로 날짜를 정해 실측해요."}]
    assert got["links"] == [{"label": "블로그", "url": "https://blog.example.com/a"}]
    assert got["call_start"] == "09:00:00" and got["visit_fee"] == 0
    assert got["tax_kind"] == "general" and got["insurance"] is None
    assert got["updated_at"] is not None
    assert got["biz_name"] == "예시도배"  # 심사 대상은 여기서 안 바뀐다
    assert got["biz_no"] == biz_no_for("vendor@mitjip.test")
    assert api.get(URL).json() == got


def test_save_with_stale_updated_at_is_409(api):
    approved_vendor(api)
    first = api.put(URL, json=body()).json()
    again = api.put(URL, json=body())  # 처음 읽은 값(None)으로 또 저장
    assert again.status_code == 409 and again.json()["error"]["code"] == "stale"
    second = api.put(URL, json=body(updated_at=first["updated_at"], trades=["mokgong", "dobae"]))
    assert second.status_code == 200 and second.json()["trades"] == ["dobae", "mokgong"]
    assert api.put(URL, json=body(updated_at=first["updated_at"])).status_code == 409
    naive = api.put(URL, json=body(updated_at="2026-11-03T10:00:00"))
    assert naive.status_code == 422  # 시간대 없는 시각은 받지 않는다


def test_two_saves_at_the_same_time_only_one_wins(api):
    approved_vendor(api)
    vid = vendor_id()

    async def save(delay: float, hold: float) -> bool:
        await asyncio.sleep(delay)
        async with SessionLocal() as s:
            values = {"visit_fee": 1000, "updated_at": now_utc()}
            ok = await repo.save_if_unchanged(s, vid, None, values)
            await asyncio.sleep(hold)  # 첫 번째가 행을 잡고 있는 동안 두 번째는 기다린다
            await s.commit()
            return ok

    async def both():
        return await asyncio.gather(save(0, 0.3), save(0.1, 0))

    assert asyncio.run(both()) == [True, False]  # 두 번째는 바뀐 updated_at을 보고 0행


def test_only_approved_vendor_can_use_profile(api):
    calls = (
        lambda: api.get(URL),
        lambda: api.put(URL, json=body()),
        lambda: portfolio(api, uuid.uuid4()),
        lambda: api.delete(f"/vendor/portfolio/{uuid.uuid4()}"),
    )
    assert all(c().status_code == 401 for c in calls)
    signup(api)
    assert all(c().status_code == 403 for c in calls)  # 고객
    vendor_signup(api)
    for c in calls:  # 승인 전 업체
        r = c()
        assert r.status_code == 403 and r.json()["error"]["code"] == "vendor_not_approved"
    query(
        "update vendors set status = 'rejected', review_code = 'other', review_note = '흐려요', approved_at = null"
    )
    assert all(c().status_code == 403 for c in calls)


def test_input_is_checked(api):
    approved_vendor(api)

    def put(**over) -> int:
        return api.put(URL, json=body(**over)).status_code

    assert put(contact_method="kakao") == 422  # 카카오톡 채널인데 주소 없음
    assert put(contact_method="web", contact_url="javascript:alert(1)") == 422
    assert put(call_start="18:00", call_end="09:00") == 422
    assert put(call_end=None) == 422  # 시작만
    assert put(call_start="09:00+09:00") == 422
    assert put(visit_fee=-1) == 422
    assert put(visit_fee=0, visit_fee_refund=True) == 422
    assert put(trades=[]) == 422 and put(trades=["floor"]) == 422
    assert put(areas=[]) == 422
    r = api.put(URL, json=body(areas=[{"sido": "seoul", "sgg": "없는구"}]))
    assert r.status_code == 422 and r.json()["error"]["code"] == "region"
    links = [{"url": f"https://blog.example.com/{i}"} for i in range(6)]
    assert put(links=links) == 422  # 5개까지
    assert put(links=[{"url": "not a url"}]) == 422
    assert put(faqs=[{"key": "process", "answer": "a"}, {"key": "process", "answer": "b"}]) == 422
    assert put(faqs=[{"key": "price", "answer": "a"}]) == 422
    assert put(faqs=[{"key": "process", "answer": "가" * 201}]) == 422
    assert put(phone="02-123-4567") == 422

    ok = api.put(
        URL,
        json=body(
            contact_method="kakao",
            contact_url="pf.kakao.com/_example",
            visit_fee=20000,
            visit_fee_refund=True,
            links=links[:5],
        ),
    )
    assert ok.status_code == 200, ok.text
    got = ok.json()
    assert got["contact_url"] == "https://pf.kakao.com/_example" and len(got["links"]) == 5
    phone = api.put(
        URL, json=body(updated_at=got["updated_at"], contact_url="https://pf.kakao.com/_x")
    )
    assert phone.json()["contact_url"] is None  # 전화 · 문자는 채널 주소를 두지 않는다


@pytest.mark.parametrize(
    "sql",
    [
        "update vendors set contact_method = 'kakao', contact_url = null",
        "update vendors set contact_method = 'fax'",
        "update vendors set call_start = '18:00', call_end = '09:00'",
        "update vendors set call_start = '09:00', call_end = null",
        "update vendors set visit_fee = -1",
        "update vendors set visit_fee = 0, visit_fee_refund = true",
        "update vendors set tax_kind = 'simple'",
        "update vendors set phone = '010-1234-5678'",
        "insert into vendor_faqs select user_id, 'price', '답' from vendors",
        "insert into vendor_faqs select user_id, 'process', '  ' from vendors",
        "insert into vendor_links select user_id, 5, null, 'https://a.example.com' from vendors",
        "update files set kind = 'contract'",
    ],
)
def test_db_checks(api, sql):
    approved_vendor(api)
    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        query(sql)


def test_portfolio_pyeong_check_in_db(api):
    approved_vendor(api)
    fid = upload(api, kind="portfolio").json()["id"]
    assert portfolio(api, fid).status_code == 201
    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        query("update vendor_portfolio set pyeong = 0")


def test_portfolio_add_edit_and_remove(api):
    approved_vendor(api)
    a = upload(api, kind="portfolio", content=JPEG, name="거실.jpg").json()["id"]
    b = upload(api, kind="portfolio", content=JPEG, name="안방.jpg").json()["id"]
    pa = portfolio(api, a, title="실크 벽지", space="거실", pyeong=32, taken_on="2026-09-01")
    assert pa.status_code == 201, pa.text
    pb = portfolio(api, b, title="합지 벽지").json()
    again = portfolio(api, a)
    assert again.status_code == 409 and again.json()["error"]["code"] == "file_used"
    lic = query("select license_file_id from vendors")[0]["license_file_id"]
    assert portfolio(api, lic).status_code == 422  # 시공 사진이 아닌 파일
    future = (today_seoul() + timedelta(days=40)).isoformat()
    assert portfolio(api, b, taken_on=future).status_code == 422
    assert portfolio(api, b, pyeong=0).status_code == 422

    prof = api.get(URL).json()
    assert [p["title"] for p in prof["portfolio"]] == ["실크 벽지", "합지 벽지"]
    assert prof["portfolio"][0]["space"] == "거실" and prof["portfolio"][0]["pyeong"] == 32
    edit = [
        {"id": pb["id"], "title": "안방 · 합지 벽지", "pyeong": 24},
        {"id": pa.json()["id"], "title": "거실 · 실크 벽지"},
    ]
    r = api.put(URL, json=body(portfolio=edit))
    assert r.status_code == 200, r.text
    assert [(p["title"], p["pyeong"]) for p in r.json()["portfolio"]] == [
        ("안방 · 합지 벽지", 24),
        ("거실 · 실크 벽지", None),
    ]
    short = api.put(URL, json=body(updated_at=r.json()["updated_at"], portfolio=edit[:1]))
    assert short.status_code == 409  # 그사이 사진이 바뀌었다 (화면을 다시 열어야 함)

    assert api.delete(f"/vendor/portfolio/{pb['id']}").status_code == 204
    assert api.delete(f"/vendor/portfolio/{pb['id']}").status_code == 404
    assert api.get(f"/files/{b}").status_code == 404  # 파일도 지웠다
    assert query("select count(*) n from files where id = $1", uuid.UUID(b))[0]["n"] == 0
    assert [p["file_id"] for p in api.get(URL).json()["portfolio"]] == [a]

    approved_vendor(api, "other@mitjip.test")
    assert api.delete(f"/vendor/portfolio/{pa.json()['id']}").status_code == 404  # 남의 사진
    assert portfolio(api, a).status_code == 422  # 남의 파일


def test_portfolio_is_limited(api, monkeypatch):
    approved_vendor(api)
    monkeypatch.setattr(service, "PORTFOLIO_MAX", 1)
    ids = [upload(api, kind="portfolio").json()["id"] for _ in range(2)]
    assert portfolio(api, ids[0]).status_code == 201
    full = portfolio(api, ids[1])
    assert full.status_code == 409 and full.json()["error"]["code"] == "portfolio_full"


def _run(fn, *args):
    async def go():
        async with SessionLocal() as s:
            return await fn(s, *args)

    return asyncio.run(go())


def test_public_profile_hides_contacts_and_needs_approval(api):
    token = approved_vendor(api)
    api.put(URL, json=body(contact_method="kakao", contact_url="https://pf.kakao.com/_x"))
    vid = vendor_id()
    approved_vendor(api, "quiet@mitjip.test")  # 승인됐지만 업체 정보를 아직 안 적은 업체
    vendor_signup(api, email="waiting@mitjip.test")  # 승인 전

    pub = _run(service.public_profile, vid).model_dump()
    assert {"phone", "contact_url", "address", "site_url"}.isdisjoint(pub)
    assert pub["contact_method"] == "kakao" and pub["address_area"] == "서울특별시 도봉구"
    assert pub["faqs"][0]["key"] == "process" and pub["insurance"] is None

    found = _run(service.list_public, "dobae", "seoul", "노원구")
    assert [v.vendor_id for v in found] == [vid]
    assert {"phone", "contact_url"}.isdisjoint(found[0].model_dump())
    assert _run(service.list_public, "mokgong", "seoul", "노원구") == []
    assert _run(service.list_public, "dobae", "seoul", "강남구") == []
    assert [v.vendor_id for v in _run(service.list_public, None, "seoul", None)] == [vid]

    quiet = _run(service.public_profile, vendor_id("quiet@mitjip.test"))
    assert quiet.contact_method is None and quiet.faqs == []  # 목록에는 안 나온다
    with pytest.raises(AppError) as e:
        _run(service.public_profile, vendor_id("waiting@mitjip.test"))
    assert e.value.status == 404

    query(
        "update vendors set status = 'rejected', review_code = 'other', review_note = '흐려요', approved_at = null where user_id = $1",
        vid,
    )
    assert _run(service.list_public, "dobae", "seoul", "노원구") == []
    with pytest.raises(AppError):
        _run(service.public_profile, vid)
    use(api, token)
    assert api.get(URL).status_code == 403
